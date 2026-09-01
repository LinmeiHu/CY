from __future__ import annotations

import math
from datetime import date

from research.oversold_reversal_ranking import v5_portfolio, v6_cluster_capital


def _event(event_id: int, symbol: str, entry_date: date, exit_date: date) -> dict[str, object]:
    return {
        "event_id": event_id,
        "symbol": symbol,
        "signal_date": date(2020, 1, 1),
        "entry_date": entry_date,
        "scheduled_exit_date": exit_date,
        "expected_exit_delay_sessions": 0,
    }


def test_v6_reuses_v5_execution_contract_and_retires_stock_risk_weights() -> None:
    assert v6_cluster_capital.v5.simulate_portfolio is v5_portfolio.simulate_portfolio
    assert v6_cluster_capital.BASE_BUDGET_FRACTION == v5_portfolio.DAILY_TRANCHE_FRACTION == 0.05
    assert "risk" not in v6_cluster_capital.simulate_count_aware.__doc__.lower()


def test_cluster_reference_uses_strict_prior_active_dates_and_neutral_warmup() -> None:
    d1, d2, d3 = date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)
    events = [
        {"entry_date": d1},
        {"entry_date": d2},
        {"entry_date": d2},
        {"entry_date": d2},
        {"entry_date": d3},
        {"entry_date": d3},
    ]
    rows = v6_cluster_capital.assign_causal_cluster_reference(events, minimum_history=2)
    assert [row["signal_count"] for row in rows] == [1, 3, 2]
    assert rows[0]["warmup"] and rows[1]["warmup"]
    assert rows[0]["count_ratio"] == rows[1]["count_ratio"] == 1.0
    assert rows[2]["prior_active_dates"] == 2
    assert rows[2]["prior_median_positive_count"] == 2.0
    assert rows[2]["count_ratio"] == 1.0


def test_count_aware_budget_scales_total_capital_and_splits_same_date_equally() -> None:
    first, second, exit_date = date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)
    events = [
        _event(1, "A", first, exit_date),
        _event(2, "B", second, exit_date),
        _event(3, "C", second, exit_date),
    ]
    calendar = [first, second, exit_date]
    prices = {
        (symbol, trade_date): {"adjusted_open": 1.0, "adjusted_close": 1.0, "sellable_open": True}
        for symbol, start in (("A", first), ("B", second), ("C", second))
        for trade_date in calendar[calendar.index(start) :]
    }
    reference = v6_cluster_capital.assign_causal_cluster_reference(events, minimum_history=1)
    simulation = v6_cluster_capital.simulate_count_aware(
        events=events,
        prices=prices,
        calendar=calendar,
        cluster_reference=reference,
    )
    allocations = simulation["daily_allocations"]
    assert math.isclose(allocations[0]["actual_entry_notional"], 0.05)
    assert math.isclose(allocations[1]["desired_budget"], 0.10)
    by_symbol = {trade["symbol"]: trade["initial_notional"] for trade in simulation["trades"]}
    assert math.isclose(by_symbol["A"], 0.05)
    assert math.isclose(by_symbol["B"], 0.05)
    assert math.isclose(by_symbol["C"], 0.05)
    assert min(row["cash"] for row in simulation["daily"]) >= 0.0
    assert max(row["exposure"] for row in simulation["daily"]) <= 1.0
    assert math.isclose(simulation["daily"][-1]["nav"], 1.0)


def test_finite_cash_caps_cluster_budget_without_leverage() -> None:
    first, second, exit_date = date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6)
    events = [_event(1, "A", first, exit_date)]
    events.extend(_event(index + 2, f"S{index:03d}", second, exit_date) for index in range(100))
    calendar = [first, second, exit_date]
    prices = {
        (event["symbol"], trade_date): {
            "adjusted_open": 1.0,
            "adjusted_close": 1.0,
            "sellable_open": True,
        }
        for event in events
        for trade_date in calendar[calendar.index(event["entry_date"]) :]
    }
    reference = v6_cluster_capital.assign_causal_cluster_reference(events, minimum_history=1)
    simulation = v6_cluster_capital.simulate_count_aware(
        events=events,
        prices=prices,
        calendar=calendar,
        cluster_reference=reference,
    )
    second_allocation = simulation["daily_allocations"][1]
    assert math.isclose(second_allocation["desired_budget"], 5.0)
    assert math.isclose(second_allocation["actual_entry_notional"], 0.95)
    assert math.isclose(second_allocation["budget_shortfall"], 4.05)
    assert second_allocation["cash_constrained"]
    assert min(row["cash"] for row in simulation["daily"]) >= 0.0
    assert max(row["exposure"] for row in simulation["daily"]) <= 1.0
