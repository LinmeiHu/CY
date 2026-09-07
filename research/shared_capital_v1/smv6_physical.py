"""Native SMV6 callbacks funded by the physical/virtual P0 engine.

Orders enter the engine before cash rejection. Actual engine fills update the
native callback's positions and cash. The same callbacks are merged by the
common scheduler; native SuperMind platform equivalence remains unverified.
"""
from dataclasses import asdict
from types import SimpleNamespace
import json

import pandas as pd

from five_strategy_bundle.strategies import smv6
from research.shared_capital_v1.causal_adapters import CausalCashPlatform, corrected_function
from research.shared_capital_v1.shared_account.engine import Intent, PhysicalAccount
from research.shared_capital_v1.shared_account.scheduler import Event, run_streams
from research.shared_capital_v1.smv6_baseline import HERE, load_bounded


class PhysicalPlatform(CausalCashPlatform):
    def __init__(self, *args, **kwargs):
        physical = kwargs.pop("physical", None)
        super().__init__(*args, **kwargs)
        self.physical = physical if physical is not None else PhysicalAccount("OGR", initial_cash=self.initial_cash * 4)
        self.intent_rows = []

    @property
    def cash(self):
        return self.physical.sleeve_cash["SMV6"] if hasattr(self, "physical") else self._initializing_cash

    @cash.setter
    def cash(self, value):
        if hasattr(self, "physical"):
            raise ValueError("native callback bypassed physical cash ledger")
        self._initializing_cash = value

    def nav(self, stage):
        value = super().nav(stage)
        if hasattr(self, "physical"):
            self.physical.mark({s: self._mark(s, stage) for s, q in self.shares.items() if q}, basis="PRE_ADJUSTED_ETF")
        return value

    def _timestamp(self):
        return pd.Timestamp(self.current_date) + (pd.Timedelta(hours=9, minutes=30) if self.event_stage == "open" else pd.Timedelta(hours=15))

    def _engine_buy(self, symbol, requested, price):
        nav = self.nav("open")
        identity = f"SMV6|{self.current_date}|{symbol}|{len(self.intent_rows)}"
        intent = Intent("SMV6", "NATIVE_CALLBACK", "ETF_TIMING", identity, "", symbol,
            pd.Timestamp(self.current_date), self._timestamp(), (len(self.intent_rows),),
            requested, price, self.commission_rate, lot_size=self.lot_size, price_basis="PRE_ADJUSTED_ETF",
            state_requirements=json.dumps(self.shares, sort_keys=True))
        self.intent_rows.append({**asdict(intent), "native_requested_notional": intent.native_requested_notional})
        home = {s: self.initial_cash for s in self.physical.strategies}
        home["SMV6"] = nav
        self.physical.fund([intent], home, "P0", self._timestamp())
        lot = self.physical.lots.get(identity)
        return 0 if lot is None else int(lot["quantity"])

    def _engine_sell(self, symbol, quantity, price):
        remaining = quantity
        for eid, lot in list(self.physical.lots.items()):
            if lot["symbol"] != symbol or lot["strategy"] != "SMV6":
                continue
            qty = min(remaining, lot["quantity"])
            self.physical.close(eid, price, self._timestamp(), self.commission_rate, quantity=qty)
            remaining -= qty
            if remaining == 0:
                break
        if remaining:
            raise ValueError("native shares not represented by physical lots")

    _physical_order_target_percent = corrected_function(smv6.CashPlatform.order_target_percent, [
        ("delta = min(delta, affordable)", "delta = self._engine_buy(symbol, delta, price)"),
        ("self.cash -= delta * price + fee", "if delta < 0:\n        self._engine_sell(symbol, -delta, price)"),
        ("if self.cash < -1e-8:", "if self.physical.cash < -1e-8:"),
    ])
    def order_target_percent(self, symbol, target_weight):
        self.nav("open")
        return self._physical_order_target_percent(symbol, target_weight)

    order_target = corrected_function(smv6.CashPlatform.order_target, [
        ("self.cash += qty * price - fee", "self._engine_sell(symbol, qty, price)"),
    ])

    _attributed_record_account = corrected_function(smv6.CashPlatform.record_account, [
        ('if self.cash < -1e-10 or exposure > nav + 1e-10:', 'if self.physical.cash < -1e-10:'),
    ])
    def record_account(self):
        self._attributed_record_account()
        self.physical.mark({s: self._mark(s, "eod") for s, q in self.shares.items() if q}, basis="PRE_ADJUSTED_ETF")
        state = self.physical.checkpoint(self._timestamp(), "CLOSE")
        represented = {}
        for lot in self.physical.lots.values():
            if lot['strategy'] == 'SMV6':
                represented[lot['symbol']] = represented.get(lot['symbol'], 0.) + lot['quantity']
        if represented != {s: q for s, q in self.shares.items() if q}:
            raise ValueError("native/physical holdings mismatch")
        if abs(self.physical.sleeve_cash["SMV6"] + self.physical.exposure("SMV6") - self.accounts[-1]["nav"]) > 1e-6:
            raise ValueError("native/physical equity mismatch")


def callback_stream(platform, calendar):
    namespace = smv6.frozen_namespace(platform)
    context = SimpleNamespace(portfolio=SimpleNamespace(stock_account=SimpleNamespace(positions=platform.positions)))
    namespace['init'](context)
    platform.native_context = context
    def before(day):
        platform.current_date = day.date()
        platform.event_stage = 'before_trading'
        prior = set(platform.positions)
        namespace['before_trading'](context)
        smv6.record_pending_signals(platform, context, prior)
    def opening():
        platform.event_stage = 'open'
        namespace['execute_pending_open'](context, platform.bar_dict(), 'LOCAL_09_30')
    def signal():
        platform.event_stage = 'signal'
        namespace['run_1457_exit_signal'](context, platform.bar_dict(include_signal=True))
        for symbol in context.pending_close_sells:
            platform._record('TAIL_SELL_SIGNAL', symbol, price=platform._minute_price(symbol, 'PSEUDO_CLOSE_14_57_OPEN', 'pre_adj_open'), reason=context.pending_close_reason)
    def closing():
        platform.event_stage = 'close'
        namespace['execute_pending_close_sells'](context, platform.bar_dict(include_close=True))
    for day in calendar:
        yield Event(day, 'PREPARE', 'SMV6', str(day), lambda d=day: before(d))
        yield Event(day + pd.Timedelta(hours=9, minutes=30), 'OPEN_CALLBACK', 'SMV6', str(day), opening)
        yield Event(day + pd.Timedelta(hours=14, minutes=57), 'SIGNAL', 'SMV6', str(day), signal)
        yield Event(day + pd.Timedelta(hours=15), 'EXIT', 'SMV6', str(day), closing)
        yield Event(day + pd.Timedelta(hours=15), 'CLOSE', 'SMV6', str(day), platform.record_account)


def scheduled_callbacks(platform, calendar):
    platform.physical.scheduler_trace = run_streams([callback_stream(platform, calendar)])
    events = pd.DataFrame(platform.events).sort_values(['trade_date','symbol','event_type']).reset_index(drop=True)
    return events, pd.DataFrame(platform.accounts)


def run():
    from pathlib import Path
    inputs = {k: Path(v) for k, v in json.loads((HERE.parent / "five_strategy_exit_risk_v1/input_config.json").read_text())["inputs"].items()}
    daily, minute, availability = load_bounded(inputs)
    rows = []
    for period, start, end in (("2018_2021", "2018-01-01", "2021-12-31"), ("2022_2023", "2022-01-01", "2023-12-31")):
        calendar = list(daily["000852.SH"].loc[start:end].dropna(subset=["pre_adj_close"]).index)
        platform = PhysicalPlatform(daily, minute, availability, calendar, initial_cash=1e6, lot_size=100, fee_bps=0)
        events, nav = scheduled_callbacks(platform, calendar)
        root = HERE / "cache/smv6" / period
        reference = pd.read_parquet(root / "CAUSAL_CORRECTED_BASELINE_nav.parquet")
        reference_events = pd.read_parquet(root / "CAUSAL_CORRECTED_BASELINE_events.parquet")
        fields = ["trade_date", "symbol", "event_type", "filled_delta_qty", "position_qty"]
        pd.testing.assert_frame_equal(events[fields], reference_events[fields], check_dtype=False)
        if (platform.commission_rate, platform.slippage_total, platform.minute_volume_limit) != (.0002, .0016, .5):
            raise ValueError("frozen native execution costs changed")
        joined = nav.merge(reference, on="trade_date", validate="one_to_one", suffixes=("_physical", "_native"))
        cash_diff = float((joined.cash_physical - joined.cash_native).abs().max())
        nav_diff = float((joined.nav_physical - joined.nav_native).abs().max())
        position_diff = float((joined.position_count_physical - joined.position_count_native).abs().max())
        if len(joined) != len(calendar) or max(cash_diff, nav_diff, position_diff) > 1e-6:
            raise ValueError(f"SMV6 physical native mismatch: {cash_diff} {nav_diff} {position_diff}")
        for name, frame in (("nav", nav), ("events", events), ("fills", pd.DataFrame(platform.physical.fills)), ("intents", pd.DataFrame(platform.intent_rows)), ("checkpoints", pd.DataFrame(platform.physical.checkpoints))):
            frame.to_parquet(root / f"physical_p0_{name}.parquet", index=False)
        rows.append({"strategy": "SMV6", "period": period, "final_nav": float(nav.nav.iloc[-1]),
            "intent_count": len(platform.intent_rows), "funded_count": sum(f["side"] == "BUY" for f in platform.physical.fills),
            "trade_count": sum(f["side"] == "SELL" for f in platform.physical.fills), "initial_cash": 1e6, "initial_positions": "{}",
            "max_abs_cash_diff": cash_diff, "max_abs_position_diff": position_diff, "max_abs_nav_diff": nav_diff,
            "prefix_invariance_status": "CALLBACK_BASELINE_PREFIX_PASS", "status": "NATIVE_PHYSICAL_ACCOUNT_RECONCILED",
            "scope": "LOCAL_PLATFORM_APPROXIMATION_SINGLE_STRATEGY_PHYSICAL_P0"})
    pd.DataFrame(rows).to_csv(HERE / "output/smv6_physical_p0_reconciliation.csv", index=False)
    print(rows, flush=True)


if __name__ == "__main__":
    run()
