"""Gap native pre-capital requests replayed into a physical research account."""
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from five_strategy_bundle.strategies import ogr
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1.shared_account.engine import Intent, PhysicalAccount
from research.shared_capital_v1.validation import account_validation

HERE = Path(__file__).resolve().parent


def replay(strategy, trades, daily, start, end):
    trades = trades.loc[trades.entry_date.between(start, end)].copy()
    trades["target_at_entry"] = trades.target_coordinate / trades.entry_coordinate_price * .998 / 1.002 - 1
    trades = trades.sort_values(["entry_time", "target_at_entry", "pre_gap_inside_density_relative_local", "symbol", "gap_id"], ascending=[True, False, True, True, True], kind="stable")
    days = pd.DatetimeIndex(sorted(daily.loc[daily.trade_date.between(start, end), "trade_date"].unique()))
    bysymbol = {s: f.set_index("trade_date").close.sort_index() for s, f in daily.loc[daily.symbol.isin(trades.symbol)].groupby("symbol")}
    bydate = {pd.Timestamp(d): f for d, f in trades.groupby("entry_date")}
    account = PhysicalAccount(strategy)
    cash = {"MAIN": 500000., "CHINEXT": 500000.}
    active, intents, other, nav = {}, [], [], []

    def mark(when, include_close=False):
        for eid, row in active.items():
            series = bysymbol[row["symbol"]]
            before = series.loc[series.index <= when.normalize()] if include_close else series.loc[series.index < when.normalize()]
            price = float(before.iloc[-1]) if len(before) else row["entry_raw_price"]
            account.mark({row["symbol"]: price})

    for day in days:
        for eid, row in list(active.items()):
            for event in json.loads(row.cash_events_json if hasattr(row, 'cash_events_json') else row["cash_events_json"]):
                if pd.Timestamp(event["date"]) == day:
                    before = account.cash
                    account.credit(eid, float(event["cash_per_share"]), day)
                    cash[row["board"]] += account.cash - before
        cohort = bydate.get(day, pd.DataFrame())
        times = sorted(set(pd.to_datetime(cohort.entry_time) if len(cohort) else []) | {pd.Timestamp(row["exit_time"]) for row in active.values() if pd.Timestamp(row["exit_time"]).normalize() == day})
        for when in times:
            for eid, row in sorted(list(active.items()), key=lambda item: (pd.Timestamp(item[1]["exit_time"]), item[1]["symbol"])):
                if pd.Timestamp(row["exit_time"]) <= when:
                    before = account.cash
                    account.close(eid, row["exit_raw_price"], when, .002)
                    cash[row["board"]] += account.cash - before
                    del active[eid]
            incoming = cohort.loc[cohort.entry_time.eq(when)] if len(cohort) else cohort
            for row in incoming.itertuples(index=False):
                live = [p for p in active.values() if p["board"] == row.board]
                reason = "DUPLICATE_SYMBOL" if any(p["symbol"] == row.symbol for p in live) else "CAPACITY" if len(live) >= 80 else None
                if reason:
                    other.append({"event_id": row.gap_id, "reason": reason})
                    continue
                mark(when)
                value = sum(account.lots[eid]["quantity"] * account.marks[p["symbol"]] for eid, p in active.items() if p["board"] == row.board)
                outlay = (cash[row.board] + value) / 80
                intent = Intent(strategy, "FIXED_BELOW_L_REPAIR", "GAP", row.gap_id, row.gap_id, row.symbol,
                    pd.Timestamp(row.signal_time), when, (-row.target_at_entry, row.pre_gap_inside_density_relative_local, row.symbol, row.gap_id),
                    outlay / (row.entry_raw_price * 1.002), row.entry_raw_price, .002, board=row.board, native_base_cash_limit=cash[row.board])
                intents.append({**asdict(intent), "native_requested_notional": intent.native_requested_notional})
                home = {s: 1e6 for s in account.strategies}
                home[strategy] = sum(cash.values()) + account.exposure()
                before = account.cash
                account.fund([intent], home, "P0", when)
                if row.gap_id in account.lots:
                    cash[row.board] -= before - account.cash
                    active[row.gap_id] = row._asdict()
        mark(day, True)
        state = account.checkpoint(day + pd.Timedelta(hours=15), "CLOSE")
        nav.append({"trade_date": day, "nav": state["nav"] - 3e6, "cash": sum(cash.values()), "gross_exposure": account.exposure(), "active_positions": len(active)})
    return account, pd.DataFrame(intents), pd.DataFrame(other), pd.DataFrame(nav)


def run():
    config = json.loads((HERE.parent / "five_strategy_exit_risk_v1/input_config.json").read_text())
    daily = ogr.load_daily(Path(config["inputs"]["daily_hist"]), end="2023-12-31")
    outcomes = pd.read_parquet(HERE / "cache/ogr/outcomes.parquet")
    board = corrected_function(ogr._replay_board, [
        ('period_end = min(\n        pd.Timestamp(trades.exit_date.max()).normalize(), pd.Timestamp(account_end)\n    )', 'period_end = pd.Timestamp(account_end)'),
    ])
    native = corrected_function(ogr.replay_portfolio, [], _replay_board=board)
    rows = []
    for strategy in ("OGR", "IFCGR"):
        for period, start, end in (("2018_2021", "2018-01-01", "2021-12-31"), ("2022_2023", "2022-01-01", "2023-12-31")):
            selected = pd.read_parquet(HERE / "cache/ifcgr" / period / "signals.parquet") if strategy == "IFCGR" else pd.read_parquet(HERE / "cache/ogr/signals.parquet")
            trades = outcomes.loc[outcomes.gap_id.isin(selected.gap_id) & outcomes.entry_date.between(start, end)].copy()
            account, intents, other, nav = replay(strategy, trades, daily, start, end)
            accepted, ledger, golden = native(trades, daily, account_start=start, account_end=end)
            reference = golden.loc[golden.board.eq("COMBINED")]
            joined = nav.merge(reference, on="trade_date", suffixes=("_new", "_native"), validate="one_to_one")
            diffs = {name: float((joined[name + "_new"] - joined[name + "_native"] * (1 if name == "active_positions" else 1e6)).abs().max()) for name in ("cash", "nav", "gross_exposure", "active_positions")}
            fills = pd.DataFrame(account.fills)
            buys = fills.loc[fills.side.eq("BUY")]
            qty = buys[["event_id", "native_requested_quantity"]].merge(accepted[["gap_id", "qty"]], left_on="event_id", right_on="gap_id", how="outer", validate="one_to_one", indicator=True)
            quantity_diff = float((qty.native_requested_quantity - qty.qty * 500000.).abs().max())
            matched = qty._merge.eq("both").all() and len(joined) == len(nav) == len(reference)
            audit = account_validation(nav, sorted(daily.loc[daily.trade_date.between(start, end), "trade_date"].unique()))
            status = "PASS" if matched and max(diffs.values()) < 1e-6 and quantity_diff < 1e-6 and audit["status"] == "PASS" else "FAIL"
            out = HERE / "cache" / strategy.lower() / period
            out.mkdir(parents=True, exist_ok=True)
            for name, frame in (("intents", intents), ("other_rejected", other), ("nav", nav), ("fills", fills), ("checkpoints", pd.DataFrame(account.checkpoints)), ("native_nav", golden)):
                if "native_priority" in frame:
                    frame = frame.copy()
                    frame["native_priority"] = frame.native_priority.map(json.dumps)
                frame.to_parquet(out / f"p0_{name}.parquet", index=False)
            rows.append({"strategy": strategy, "period": period, "eligible_count": int(selected.signal_date.between(start, end).sum()),
                         "intent_count": len(intents), "funded_count": len(buys), "trade_count": int(fills.side.eq("SELL").sum()),
                         "initial_cash": 1e6, "initial_positions": "{}", "final_nav": float(nav.nav.iloc[-1]),
                         "max_abs_cash_diff": diffs["cash"], "max_abs_position_diff": quantity_diff,
                         "max_abs_nav_diff": diffs["nav"], "prefix_invariance_status": "PENDING_FULL_PARENT_PREFIX_REGENERATION",
                         "status": status, "scope": "NATIVE_FIXED_GAP_STANDALONE_P0_ACCOUNT_RECONCILIATION"})
            pd.DataFrame(rows).to_csv(HERE / "output/gap_p0_reconciliation.csv", index=False)
            print(rows[-1], flush=True)


if __name__ == "__main__":
    run()
