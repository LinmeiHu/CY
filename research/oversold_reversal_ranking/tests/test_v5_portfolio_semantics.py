from __future__ import annotations

import math
from datetime import date

from research.oversold_reversal_ranking import (
    v2_timing,
    v3_risk_filter,
    v5_portfolio,
)


def test_v5_imports_frozen_carrier_and_score_builders() -> None:
    assert v5_portfolio.create_timing_tables is v2_timing.create_timing_tables
    assert v5_portfolio.create_risk_tables is v3_risk_filter.create_risk_tables
    assert v5_portfolio.RAW_RISK_WEIGHTS == {
        1: 1.25,
        2: 1.125,
        3: 1.0,
        4: 0.875,
        5: 0.75,
    }


def test_causal_buckets_use_strictly_prior_dates_and_neutral_warmup() -> None:
    first = date(2020, 1, 2)
    second = date(2020, 1, 3)
    events = [
        {"event_id": 1, "signal_date": first, "symbol": "A", "risk_score": 0.1},
        {"event_id": 2, "signal_date": first, "symbol": "B", "risk_score": 0.9},
        {"event_id": 3, "signal_date": second, "symbol": "C", "risk_score": 0.05},
        {"event_id": 4, "signal_date": second, "symbol": "D", "risk_score": 0.95},
    ]
    assigned = v5_portfolio.assign_causal_buckets(events, minimum_history=2)
    by_id = {row["event_id"]: row for row in assigned}
    assert by_id[1]["causal_warmup"] and by_id[2]["causal_warmup"]
    assert by_id[1]["causal_raw_weight"] == by_id[2]["causal_raw_weight"] == 1.0
    assert by_id[3]["causal_prior_event_n"] == 2
    assert by_id[4]["causal_prior_event_n"] == 2
    assert by_id[3]["causal_risk_q"] == 1
    assert by_id[4]["causal_risk_q"] == 5
    assert by_id[3]["causal_raw_weight"] > by_id[4]["causal_raw_weight"]


def test_cost_model_and_historical_stamp_duty() -> None:
    before = date(2023, 8, 25)
    after = date(2023, 8, 28)
    assert math.isclose(v5_portfolio.buy_cost_rate("BASE"), 0.0008)
    assert math.isclose(v5_portfolio.sell_cost_rate(before, "BASE"), 0.0018)
    assert math.isclose(v5_portfolio.sell_cost_rate(after, "BASE"), 0.0013)
    assert math.isclose(v5_portfolio.buy_cost_rate("HIGH_COST"), 0.0016)
    assert math.isclose(v5_portfolio.sell_cost_rate(before, "HIGH_COST"), 0.0026)
    assert math.isclose(v5_portfolio.sell_cost_rate(after, "HIGH_COST"), 0.0021)


def _event(event_id: int, symbol: str, raw_weight: float) -> dict[str, object]:
    return {
        "event_id": event_id,
        "symbol": symbol,
        "signal_date": date(2020, 1, 1),
        "entry_date": date(2020, 1, 2),
        "scheduled_exit_date": date(2020, 1, 3),
        "expected_exit_delay_sessions": 0,
        "causal_raw_weight": raw_weight,
    }


def test_tiny_portfolio_replay_reconciles_cash_nav_and_daily_competition() -> None:
    events = [_event(1, "A", 1.25), _event(2, "B", 0.75)]
    prices = {
        (symbol, trade_date): {
            "adjusted_open": 1.0,
            "adjusted_close": 1.0,
            "sellable_open": True,
        }
        for symbol in ("A", "B")
        for trade_date in (date(2020, 1, 2), date(2020, 1, 3))
    }
    calendar = [date(2020, 1, 2), date(2020, 1, 3)]
    equal = v5_portfolio.simulate_portfolio(
        policy="EQUAL_SIZE",
        cost_mode="GROSS",
        events=events,
        prices=prices,
        calendar=calendar,
    )
    risk = v5_portfolio.simulate_portfolio(
        policy="RISK_AWARE_SIZE",
        cost_mode="GROSS",
        events=events,
        prices=prices,
        calendar=calendar,
    )
    assert math.isclose(sum(t["initial_notional"] for t in equal["trades"]), 0.05)
    assert math.isclose(sum(t["initial_notional"] for t in risk["trades"]), 0.05)
    assert [t["initial_notional"] for t in equal["trades"]] == [0.025, 0.025]
    risk_by_symbol = {t["symbol"]: t["initial_notional"] for t in risk["trades"]}
    assert math.isclose(risk_by_symbol["A"], 0.03125)
    assert math.isclose(risk_by_symbol["B"], 0.01875)
    for simulation in (equal, risk):
        assert simulation["flow"]["entered"] == 2
        assert simulation["daily"][0]["concurrent_positions"] == 2
        assert simulation["daily"][1]["concurrent_positions"] == 0
        assert math.isclose(simulation["daily"][-1]["cash"], 1.0)
        assert math.isclose(simulation["daily"][-1]["nav"], 1.0)


def test_buy_cost_scaling_never_creates_negative_cash() -> None:
    event = _event(1, "A", 1.0)
    prices = {
        ("A", date(2020, 1, 2)): {
            "adjusted_open": 1.0,
            "adjusted_close": 1.0,
            "sellable_open": True,
        },
        ("A", date(2020, 1, 3)): {
            "adjusted_open": 1.0,
            "adjusted_close": 1.0,
            "sellable_open": True,
        },
    }
    simulation = v5_portfolio.simulate_portfolio(
        policy="EQUAL_SIZE",
        cost_mode="BASE",
        events=[event],
        prices=prices,
        calendar=[date(2020, 1, 2), date(2020, 1, 3)],
        initial_nav=0.01,
    )
    assert min(row["cash"] for row in simulation["daily"]) >= 0.0
    assert all(
        math.isclose(row["nav"], row["cash"] + row["market_value"])
        for row in simulation["daily"]
    )


def test_many_consecutive_signal_days_activate_cash_constraint_without_leverage() -> None:
    entry_dates = [date(2020, 1, day) for day in range(2, 23)]
    exit_date = date(2020, 1, 23)
    events = []
    prices = {}
    calendar = [*entry_dates, exit_date]
    for index, entry_date in enumerate(entry_dates, start=1):
        symbol = f"S{index:02d}"
        events.append(
            {
                "event_id": index,
                "symbol": symbol,
                "signal_date": date(2020, 1, 1),
                "entry_date": entry_date,
                "scheduled_exit_date": exit_date,
                "expected_exit_delay_sessions": 0,
                "causal_raw_weight": 1.0,
            }
        )
        for trade_date in calendar[calendar.index(entry_date) :]:
            prices[(symbol, trade_date)] = {
                "adjusted_open": 1.0,
                "adjusted_close": 1.0,
                "sellable_open": True,
            }
    simulation = v5_portfolio.simulate_portfolio(
        policy="EQUAL_SIZE",
        cost_mode="BASE",
        events=events,
        prices=prices,
        calendar=calendar,
    )
    assert simulation["flow"]["cash_constrained_days"] >= 1
    assert simulation["flow"]["cost_scaled_days"] >= 1
    assert min(row["cash"] for row in simulation["daily"]) >= 0.0
    assert max(row["exposure"] for row in simulation["daily"]) <= 1.0
