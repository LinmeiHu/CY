"""Explicit research execution corrections; frozen modules remain historical references.

Only the listed orchestration expressions are replaced. Each replacement must
match exactly once, so upstream drift fails closed. No thresholds/ranks/exits
are edited. These functions are not claims of full historical validation.
"""
import inspect
import math
import textwrap

import numpy as np
import pandas as pd

from five_strategy_bundle.errors import ReproductionError
from five_strategy_bundle.strategies import atrdr
from five_strategy_bundle.strategies.smv6 import CashPlatform
from five_strategy_bundle.execution.daily import fixed_target_outcomes


def corrected_function(function, replacements, **bindings):
    source = textwrap.dedent(inspect.getsource(function))
    for old, new in replacements:
        if source.count(old) != 1:
            raise ReproductionError(f"correction source drift: {function.__name__}: {old}")
        source = source.replace(old, new)
    namespace = {**function.__globals__, **bindings}
    exec(compile(source, f"<causal correction:{function.__module__}.{function.__name__}>", "exec"), namespace)
    return namespace[function.__name__]


def entered_population(frame):
    """Execution identity is established at entry, independent of outcome status."""
    if frame.event_id.isna().any() or frame.event_id.duplicated().any():
        raise ReproductionError("entry event identity failure")
    entered = frame.entry_date.notna()
    if not np.isfinite(pd.to_numeric(frame.loc[entered, "entry_price"])).all() or frame.loc[entered, "entry_price"].le(0).any():
        raise ReproductionError("invalid entry price")
    if pd.to_datetime(frame.loc[entered, "entry_date"]).le(pd.to_datetime(frame.loc[entered, "signal_date"])).any():
        raise ReproductionError("unfinished/same-bar entry")
    result = frame.loc[entered].copy()
    for column in ("exit_date", "exit_cal_idx", "exit_price", "exit_reason", "holding_sessions", "gross_return", "net_return"):
        if column not in result:
            result[column] = pd.NaT if column == "exit_date" else np.nan
    return result


route_v27_bear = corrected_function(atrdr.route_v27_bear, [
    ('slow_outcomes.loc[slow_outcomes.status.eq("COMPLETED")]', 'entered_population(slow_outcomes)'),
], entered_population=entered_population)

select_fast_capacity = corrected_function(atrdr.select_fast_capacity, [
    ('outcomes.status.eq("COMPLETED")\n            | (outcomes.status.eq("INCOMPLETE_OUTCOME_TAIL") & outcomes.entry_date.notna())',
     'outcomes.entry_date.notna()'),
])

# The shared producer now preserves its schema for every outcome population.
causal_fixed_target_outcomes = fixed_target_outcomes


def record_pending_signals(platform, context, prior_holdings, *, previous_event_date='CONTEXT'):
    """Reporting metadata uses the event date already established by frozen alpha."""
    if not context.pending_desired or set(context.pending_desired) <= prior_holdings:
        return
    if previous_event_date == 'CONTEXT':
        previous_event_date = context.prev_trade_date
    if previous_event_date is None:
        # The first native init callback has no previous callback date, although
        # its completed input history can already support a valid signal.
        history = platform.history(['000852.SH'], ['close'], 1, '1d')['000852.SH']
        previous_event_date = history.index[-1] if len(history) else pd.NaT
    signal_date = pd.Timestamp(previous_event_date)
    if pd.isna(signal_date) or signal_date >= pd.Timestamp(platform.current_date):
        raise ReproductionError("missing/invalid frozen prior trading date")
    for symbol in context.pending_desired:
        if symbol not in prior_holdings:
            platform._record("BUY_SIGNAL", symbol, reason=context.pending_reason,
                             signal_date=signal_date.date())


class CausalCashPlatform(CashPlatform):
    """Local approximation: open-bar open is known; its close is unfinished.

    Missing executable open marks stop the callback before any order is placed.
    No unregistered last-known fallback is invented for opening NAV. End-of-day
    retains the native completed daily mark, with finite-value validation.
    """
    def _minute_price(self, symbol, role, field):
        if role == "OPEN_BAR_09_30":
            field = "pre_adj_open"
        return super()._minute_price(symbol, role, field)

    def _mark(self, symbol, stage):
        if stage == "open":
            row = self._current_row(symbol)
            price = self._minute_price(symbol, "OPEN_BAR_09_30", "pre_adj_open")
            if row is None or not bool(row.executable_09_30) or not math.isfinite(price) or price <= 0:
                raise ReproductionError(f"MISSING_LEGAL_OPEN_MARK:{self.current_date}:{symbol}")
            return price
        value = super()._mark(symbol, stage)
        if not math.isfinite(value) or value <= 0:
            raise ReproductionError(f"MISSING_LEGAL_CLOSE_MARK:{self.current_date}:{symbol}")
        return value

    def nav(self, stage):
        result = super().nav(stage)
        if not math.isfinite(result) or result <= 0 or not math.isfinite(self.cash):
            raise ReproductionError("invalid local account NAV/cash")
        return result

    def order_target_percent(self, symbol, target_weight):
        # Validate all opening holding marks before native sizing mutates state.
        self.nav("open")
        return super().order_target_percent(symbol, target_weight)
