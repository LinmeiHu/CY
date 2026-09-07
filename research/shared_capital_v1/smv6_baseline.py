"""Bounded local SMV6 callback replay and orders captured before cash rejection."""
import json
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from five_strategy_bundle.strategies import smv6
from research.shared_capital_v1.causal_adapters import CausalCashPlatform
from research.shared_capital_v1.run_shared_capital_v1 import sha256, write_json
from research.shared_capital_v1.validation import account_validation

HERE = Path(__file__).resolve().parent


class IntentPlatform(CausalCashPlatform):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.intents = []

    def order_target_percent(self, symbol, target_weight):
        row = self._current_row(symbol)
        if self.event_stage == "open" and row is not None and bool(row.executable_09_30):
            mark = self._mark(symbol, "open")
            desired = math.floor(self.nav("open") * target_weight / mark / self.lot_size) * self.lot_size
            delta = desired - self.shares.get(symbol, 0)
            request = min(max(delta, 0), self._volume_cap(symbol, "OPEN_BAR_09_30"))
            if request > 0:
                price = self._fill_price(mark, 1)
                self.intents.append({"strategy": "SMV6", "route": "NATIVE_CALLBACK", "family": "ETF_TIMING",
                    "event_id": f"SMV6|{self.current_date}|{symbol}|{len(self.intents)}", "parent_event_id": "",
                    "symbol": symbol, "decision_at": pd.Timestamp(self.current_date),
                    "earliest_execution_at": pd.Timestamp(self.current_date) + pd.Timedelta(hours=9, minutes=30),
                    "side": "BUY", "native_priority": len(self.intents), "native_requested_quantity": request,
                    "native_requested_notional": request * price * (1 + self.commission_rate),
                    "reason": "NATIVE_TARGET_PERCENT", "state_requirements": json.dumps(self.shares, sort_keys=True),
                    "cash_before": self.cash})
        return super().order_target_percent(symbol, target_weight)


def load_bounded(inputs):
    daily, minute, hashes = {}, {}, []
    con = duckdb.connect()
    symbols = [smv6.canonical_symbol(s) for s in smv6.raw_pool()] + ["000852.SH"]
    for symbol in symbols:
        dp = inputs["smv6_qmt_root"] / "daily" / f"symbol={symbol}" / "daily.parquet"
        mp = inputs["smv6_hybrid_root"] / "minute_critical" / f"symbol={symbol}" / "critical.parquet"
        for path in (dp, mp):
            hashes.append({"path": str(path), "sha256": sha256(path)})
        frame = con.execute("SELECT * FROM read_parquet(?) WHERE trade_date < DATE '2024-01-01' ORDER BY trade_date", [str(dp)]).fetchdf()
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        frame = frame.set_index("trade_date")
        frame.loc[frame.row_status.ne("VALID"), ["pre_adj_open", "pre_adj_high", "pre_adj_low", "pre_adj_close", "volume_raw", "amount_cny"]] = np.nan
        daily[symbol] = frame
        frame = con.execute("SELECT * FROM read_parquet(?) WHERE trade_date < DATE '2024-01-01'", [str(mp)]).fetchdf()
        frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
        minute[symbol] = frame
    ap = inputs["smv6_hybrid_root"] / "execution_availability/critical_execution.parquet"
    hashes.append({"path": str(ap), "sha256": sha256(ap)})
    availability = con.execute("SELECT * FROM read_parquet(?) WHERE trade_date < DATE '2024-01-01'", [str(ap)]).fetchdf()
    availability["trade_date"] = pd.to_datetime(availability.trade_date).dt.date
    con.close()
    write_json(HERE / "output/smv6_input_hashes.json", hashes)
    return daily, minute, availability


def run():
    inputs = {k: Path(v) for k, v in json.loads((HERE.parent / "five_strategy_exit_risk_v1/input_config.json").read_text())["inputs"].items()}
    daily, minute, availability = load_bounded(inputs)
    rows = []
    for period, start, end in (("2018_2021", "2018-01-01", "2021-12-31"), ("2022_2023", "2022-01-01", "2023-12-31")):
        calendar = list(daily["000852.SH"].loc[start:end].dropna(subset=["pre_adj_close"]).index)
        out = HERE / "cache/smv6" / period
        out.mkdir(parents=True, exist_ok=True)
        for label, cls in (("LEGACY_EXECUTION_RESET_CONTROL", smv6.CashPlatform), ("CAUSAL_CORRECTED_BASELINE", IntentPlatform)):
            platform = cls(daily, minute, availability, calendar, initial_cash=1_000_000., lot_size=100, fee_bps=0)
            try:
                events, accounts = smv6._run_callbacks(platform, calendar, account=True)
                events.to_parquet(out / f"{label}_events.parquet", index=False)
                accounts.to_parquet(out / f"{label}_nav.parquet", index=False)
                audit = account_validation(accounts, calendar)
                status, reason = audit["status"], audit["reason"]
                if hasattr(platform, "intents"):
                    pd.DataFrame(platform.intents).to_parquet(out / "precapital_intents.parquet", index=False)
                nav = float(accounts.nav.iloc[-1])
            except Exception as exc:
                status, reason, nav = "ACCOUNTING_BLOCKED", str(exc), None
                pd.DataFrame(platform.events).to_parquet(out / f"{label}_partial_events.parquet", index=False)
                pd.DataFrame(platform.accounts).to_parquet(out / f"{label}_partial_nav.parquet", index=False)
            rows.append({"strategy": "SMV6", "period": period, "baseline": label, "status": status,
                         "reason": reason, "final_nav": nav, "completed_dates": len(platform.accounts),
                         "required_dates": len(calendar), "initial_cash": 1_000_000., "initial_positions": "{}",
                         "initial_state": "NATIVE_CALLBACK_INIT_RESET", "fidelity": "LOCAL_PLATFORM_APPROXIMATION"})
            pd.DataFrame(rows).to_csv(HERE / "output/smv6_baseline_reconciliation.csv", index=False)
            print(rows[-1], flush=True)


def prefix_audit():
    inputs = {k: Path(v) for k, v in json.loads((HERE.parent / "five_strategy_exit_risk_v1/input_config.json").read_text())["inputs"].items()}
    daily, minute, availability = load_bounded(inputs)
    rows = []
    for period, start, cutoff in (("2018_2021", "2018-01-01", "2020-12-31"), ("2022_2023", "2022-01-01", "2022-12-30")):
        calendar = list(daily["000852.SH"].loc[start:cutoff].dropna(subset=["pre_adj_close"]).index)
        truncated_daily = {s: f.loc[:cutoff].copy() for s, f in daily.items()}
        truncated_minute = {s: f.loc[pd.to_datetime(f.trade_date).le(cutoff)].copy() for s, f in minute.items()}
        truncated_avail = availability.loc[pd.to_datetime(availability.trade_date).le(cutoff)].copy()
        p = IntentPlatform(truncated_daily, truncated_minute, truncated_avail, calendar, initial_cash=1e6, lot_size=100, fee_bps=0)
        events, nav = smv6._run_callbacks(p, calendar, account=True)
        root = HERE / "cache/smv6" / period
        full_nav = pd.read_parquet(root / "CAUSAL_CORRECTED_BASELINE_nav.parquet")
        full_events = pd.read_parquet(root / "CAUSAL_CORRECTED_BASELINE_events.parquet")
        full_nav = full_nav.loc[pd.to_datetime(full_nav.trade_date).le(cutoff)].reset_index(drop=True)
        full_events = full_events.loc[pd.to_datetime(full_events.trade_date).le(cutoff)].reset_index(drop=True)
        pd.testing.assert_frame_equal(nav, full_nav)
        pd.testing.assert_frame_equal(events, full_events, check_dtype=False)
        rows.append({"strategy": "SMV6", "period": period, "cutoff": cutoff, "account_rows": len(nav), "event_rows": len(events), "status": "PASS", "scope": "BOUNDED_RAW_INPUT_CALLBACK_PREFIX_ACCOUNT_AND_ORDERS"})
    pd.DataFrame(rows).to_csv(HERE / "output/smv6_historical_prefix.csv", index=False)
    print(rows, flush=True)


if __name__ == "__main__":
    run()
    prefix_audit()
