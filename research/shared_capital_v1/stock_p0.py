"""Native stock P0 funding replay through the physical/virtual ledger.

Native coordinate units are preserved and explicitly research-only. An active
coordinate-lineage change stops the account: deleting that historical entry,
inventing a liquidation, or continuing a stale coordinate mark is forbidden.
"""
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import numpy as np

from five_strategy_bundle.execution.daily import load_daily, replay_shared_router, replay_sleeves
from research.shared_capital_v1.build_inputs import execution_paths
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1.shared_account.engine import Intent, PhysicalAccount

HERE = Path(__file__).resolve().parent


def replay(strategy, entries, daily, start, end, *, enforce_lineage=True, boundaries=()):
    entries = entries.loc[entries.entry_date.between(start, end)].copy()
    rank = ["source_rank_order"] if strategy == "ATRDR" else ["industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"]
    fields = ["entry_date", "sleeve", "signal_date", *rank, "event_id"] if strategy == "ATRDR" else ["entry_date", *rank, "event_id"]
    ascending = [True, True, False, True, True] if strategy == "ATRDR" else [True, False, False, False, True]
    entries = entries.sort_values(fields, ascending=ascending, kind="stable")
    days = pd.DatetimeIndex(sorted(daily.loc[daily.trade_date.between(start, end), "trade_date"].unique()))
    columns = ["symbol", "trade_date", "coord_open", "coord_close", "invalid_step_cum"]
    grouped = {(str(row.symbol), pd.Timestamp(row.trade_date)): row for row in daily[columns].itertuples(index=False)}
    candidates = {pd.Timestamp(day): rows for day, rows in entries.groupby("entry_date")}
    account = PhysicalAccount("OGR")
    account.boundary_snapshots = {}
    cash = {"MAIN": 500000., "CHINEXT": 500000.}
    active = {}
    intents, rejects, nav_rows = [], [], []
    blocker = None

    def mark(day, field):
        for eid, position in active.items():
            row = grouped.get((position["symbol"], day))
            if row is not None and enforce_lineage and float(row.invalid_step_cum) != position["lineage"]:
                raise ValueError(f"ACTIVE_COORDINATE_LINEAGE_CHANGE:{day.date()}:{eid}: native outcome abort is not an executable exit")
            price = np.nan if row is None else getattr(row, field)
            # The sealed stock account explicitly defines previous known mark
            # fallback. Lineage failures above never enter that fallback.
            if pd.notna(price) and np.isfinite(price) and price > 0:
                account.mark({position["symbol"]: float(price)})

    def exits(day, target):
        for eid, position in sorted(list(active.items())):
            if pd.notna(position["exit_date"]) and pd.Timestamp(position["exit_date"]) == day and str(position["exit_reason"]).startswith("TARGET_") == target:
                before = account.cash
                account.close(eid, float(position["exit_price"]), day + pd.Timedelta(hours=15 if target else 9, minutes=0 if target else 30), .002)
                cash[position["sleeve"]] += account.cash - before
                del active[eid]

    for day in days:
        try:
            for boundary in boundaries:
                if day >= pd.Timestamp(boundary) and boundary not in account.boundary_snapshots:
                    account.boundary_snapshots[boundary] = {
                        "asof": nav_rows[-1]["trade_date"] if nav_rows else None,
                        "cash": sum(cash.values()), "board_cash": dict(cash),
                        "nav": sum(cash.values()) + account.exposure(),
                        "positions": dict(account.positions),
                        "native_active": {k: dict(v) for k, v in active.items()},
                        "virtual_lots": {k: dict(v) for k, v in account.lots.items()},
                        "completed_fills": len(account.fills),
                        "boundary_mark": "PREVIOUS_COMPLETED_CLOSE_BEFORE_FIRST_SESSION"}
            # Coordinate actions known at this open must be reconciled before
            # reusing native coordinate quantities for any exit or valuation.
            mark(day, "coord_open")
            exits(day, False)
            board_nav = {b: cash[b] + sum(account.lots[eid]["quantity"] * account.marks[p["symbol"]] for eid, p in active.items() if p["sleeve"] == b) for b in cash}
            counts = {"MAIN": 0, "CHINEXT": 0}
            cohort = candidates.get(day, pd.DataFrame())
            for row in cohort.itertuples(index=False):
                board = row.sleeve
                live = [p for p in active.values() if p["sleeve"] == board]
                reason = "ACTIVE_SYMBOL" if any(p["symbol"] == row.symbol for p in live) else "MAX_K" if len(live) >= 30 else "DAILY_CAP" if counts[board] >= 10 else None
                if reason:
                    rejects.append({"event_id": row.event_id, "reason": reason})
                    continue
                outlay = board_nav[board] / 30
                intent = Intent(strategy, getattr(row, "route", "MCB"), "DEMAND", row.event_id,
                    getattr(row, "parent_event_id", ""), row.symbol, pd.Timestamp(row.signal_date) + pd.Timedelta(hours=15),
                    day + pd.Timedelta(hours=9, minutes=30), tuple(getattr(row, k) for k in rank),
                    outlay / (float(row.entry_price) * 1.002), float(row.entry_price), .002,
                    board=board, native_base_cash_limit=cash[board])
                intents.append({**asdict(intent), "native_requested_notional": intent.native_requested_notional})
                home = {s: 1e6 for s in account.strategies}
                home[strategy] = sum(cash.values()) + account.exposure()
                before = account.cash
                account.fund([intent], home, "P0", intent.earliest_execution_at)
                if row.event_id in account.lots:
                    cash[board] -= before - account.cash
                    data = grouped[(str(row.symbol), day)]
                    active[row.event_id] = {**row._asdict(), "lineage": float(data.invalid_step_cum)}
                    counts[board] += 1
            exits(day, True)
            mark(day, "coord_close")
            snapshot = account.checkpoint(day + pd.Timedelta(hours=15), "CLOSE")
            nav_rows.append({"trade_date": day, "nav": snapshot["nav"] - 3e6, "cash": sum(cash.values()),
                             "gross_exposure": account.exposure(), "active_positions": len(active)})
        except ValueError as exc:
            blocker = str(exc)
            break
    return account, pd.DataFrame(intents), pd.DataFrame(rejects), pd.DataFrame(nav_rows), blocker


def run():
    inputs = {k: Path(v) for k, v in json.loads((HERE.parent / "five_strategy_exit_risk_v1/input_config.json").read_text())["inputs"].items()}
    summaries, issues = [], []
    for strategy in ("ATRDR", "MCB"):
        entries = pd.read_parquet(HERE / "cache" / strategy.lower() / "precapital_entry_population.parquet")
        daily = load_daily(execution_paths(inputs), entries.symbol.tolist())
        for period, start, end in (("2018_2021", "2018-01-01", "2021-12-31"), ("2022_2023", "2022-01-01", "2023-12-31")):
            account, intents, rejected, nav, blocker = replay(strategy, entries, daily, start, end)
            out = HERE / "cache" / strategy.lower() / period
            out.mkdir(parents=True, exist_ok=True)
            for name, frame in (("intents", intents), ("other_rejected", rejected), ("nav", nav), ("fills", pd.DataFrame(account.fills)), ("checkpoints", pd.DataFrame(account.checkpoints))):
                frame.to_parquet(out / f"p0_{name}.parquet", index=False)
            cohort = entries.loc[entries.entry_date.between(start, end)].copy()
            bounded_daily = daily.loc[daily.trade_date.between(start, end)]
            if strategy == "ATRDR":
                accepted, _, native_nav = replay_shared_router(cohort, bounded_daily, nav_end=pd.Timestamp(end))
                native_nav["cash"] = native_nav.main_cash + native_nav.chinext_cash
            else:
                accepted, _, native_nav, _ = replay_sleeves(cohort, bounded_daily,
                    rank_columns=("industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"), k_per_sleeve=30, daily_cap=10)
            reference = native_nav.set_index("trade_date")[["combined_nav", "cash"]].reindex(nav.trade_date).ffill().fillna(1.)
            nav_diff = float(np.max(np.abs(nav.nav.to_numpy() - reference.combined_nav.to_numpy() * 1e6)))
            cash_diff = float(np.max(np.abs(nav.cash.to_numpy() - reference.cash.to_numpy() * 1e6)))
            buys = pd.DataFrame(account.fills).loc[lambda f: f.side.eq("BUY")]
            accepted = accepted.loc[accepted.entry_date.le(nav.trade_date.max())]
            quantities = buys[["event_id", "quantity"]].merge(accepted[["event_id", "qty"]], on="event_id", how="outer", validate="one_to_one", indicator=True)
            position_diff = float((quantities.quantity - quantities.qty * 1e6).abs().max()) if quantities._merge.eq("both").all() else float("inf")
            native_nav.to_parquet(out / "native_reference_nav.parquet", index=False)
            reconciles = max(nav_diff, cash_diff, position_diff) < 1e-6
            summaries.append({"strategy": strategy, "period": period, "eligible_count": int(entries.entry_date.between(start, end).sum()),
                "intent_count": len(intents), "funded_count": sum(f["side"] == "BUY" for f in account.fills),
                "trade_count": sum(f["side"] == "SELL" for f in account.fills), "initial_cash": 1e6, "initial_positions": "{}",
                "final_nav": None if blocker or nav.empty else float(nav.nav.iloc[-1]),
                "max_abs_cash_diff": cash_diff, "max_abs_position_diff": position_diff, "max_abs_nav_diff": nav_diff,
                "prefix_invariance_status": "ACCOUNTING_BLOCKED" if blocker else "PENDING_FULL_NATIVE_COMPARISON",
                "status": "ACCOUNTING_BLOCKED" if blocker else "NATIVE_ACCOUNT_RECONCILED" if reconciles else "VALIDATION_BLOCKED", "reason": blocker or "full causal and shared initial-state gates pending" if reconciles else "native account comparison failure",
                "completed_dates": len(nav), "last_completed_date": None if nav.empty else str(nav.trade_date.iloc[-1].date()),
                "fidelity": "NORMALIZED_RESEARCH_ACCOUNT"})
            if blocker:
                issues.append({"strategy": strategy, "period": period, "first_blocker": blocker})
            print(summaries[-1], flush=True)
            pd.DataFrame(summaries).to_csv(HERE / "output/stock_p0_reconciliation.csv", index=False)
    if issues:
        pd.DataFrame(issues).to_csv(HERE / "output/native_coordinate_blockers.csv", index=False)


if __name__ == "__main__":
    run()
