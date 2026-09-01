from __future__ import annotations

import math
from datetime import date, timedelta

from research.oversold_reversal_ranking import v6_cluster_capital, v7_episode_portfolio


def _reference(
    entry_date: date, count: int, ratio: float, warmup: bool = False
) -> dict[str, object]:
    return {
        "entry_date": entry_date,
        "signal_count": count,
        "prior_active_dates": 100,
        "prior_median_positive_count": count / ratio if not warmup else None,
        "count_ratio": ratio,
        "warmup": warmup,
    }


def _events(
    start_id: int, count: int, entry_date: date, exit_date: date
) -> list[dict[str, object]]:
    return [
        {
            "event_id": start_id + index,
            "symbol": f"S{start_id + index:04d}",
            "signal_date": entry_date - timedelta(days=1),
            "entry_date": entry_date,
            "scheduled_exit_date": exit_date,
            "expected_exit_delay_sessions": 0,
        }
        for index in range(count)
    ]


def test_v7_reuses_v6_intensity_and_frozen_twenty_session_horizon() -> None:
    assert (
        v7_episode_portfolio.v6.assign_causal_cluster_reference
        is v6_cluster_capital.assign_causal_cluster_reference
    )
    assert v7_episode_portfolio.EPISODE_SESSIONS == 20
    assert v7_episode_portfolio.EPISODE_ENVELOPE_FRACTION == 1.0
    assert v7_episode_portfolio.BASE_REQUEST_FRACTION == 0.05


def test_episode_schedule_is_causal_inclusive_and_nonoverlapping() -> None:
    calendar = [date(2020, 1, 2) + timedelta(days=index) for index in range(45)]
    active = [
        _reference(calendar[0], 1, 1.0, warmup=True),
        _reference(calendar[1], 2, 2.0),
        _reference(calendar[6], 1, 0.5),
        _reference(calendar[20], 3, 3.0),
        _reference(calendar[21], 4, 4.0),
    ]
    exit_date = calendar[-1]
    events = []
    next_id = 1
    for row in active:
        batch = _events(next_id, int(row["signal_count"]), row["entry_date"], exit_date)
        events.extend(batch)
        next_id += len(batch)
    schedule, episodes = v7_episode_portfolio.assign_episode_schedule(active, events, calendar)
    by_date = {row["entry_date"]: row for row in schedule}
    assert by_date[calendar[0]]["episode_id"] is None
    assert by_date[calendar[1]]["episode_id"] == 1
    assert by_date[calendar[1]]["episode_session"] == 1
    assert by_date[calendar[6]]["episode_id"] == 1
    assert not by_date[calendar[6]]["high_intensity"]
    assert by_date[calendar[20]]["episode_id"] == 1
    assert by_date[calendar[20]]["episode_session"] == 20
    assert by_date[calendar[21]]["episode_id"] == 2
    assert episodes[0]["episode_end_date"] == calendar[20]
    assert episodes[1]["episode_start_entry_date"] == calendar[21]


def test_episode_envelope_is_cumulative_cash_backed_and_low_dates_get_zero() -> None:
    calendar = [date(2020, 1, 2) + timedelta(days=index) for index in range(25)]
    first, second, third, low, exit_date = (
        calendar[0],
        calendar[1],
        calendar[2],
        calendar[3],
        calendar[-1],
    )
    active = [
        _reference(first, 10, 10.0),
        _reference(second, 20, 20.0),
        _reference(third, 2, 2.0),
        _reference(low, 1, 1.0),
    ]
    events = []
    next_id = 1
    for row in active:
        batch = _events(next_id, int(row["signal_count"]), row["entry_date"], exit_date)
        events.extend(batch)
        next_id += len(batch)
    schedule, episodes = v7_episode_portfolio.assign_episode_schedule(active, events, calendar)
    prices = {
        (event["symbol"], trade_date): {
            "adjusted_open": 1.0,
            "adjusted_close": 1.0,
            "sellable_open": True,
        }
        for event in events
        for trade_date in calendar[calendar.index(event["entry_date"]) :]
    }
    simulation = v7_episode_portfolio.simulate_episode_portfolio(
        events=events,
        prices=prices,
        calendar=calendar,
        schedule=schedule,
        episode_specs=episodes,
    )
    allocations = {row["entry_date"]: row for row in simulation["daily_allocations"]}
    assert math.isclose(allocations[first]["deployed_capital"], 0.5)
    assert math.isclose(allocations[second]["raw_request"], 1.0)
    assert math.isclose(allocations[second]["episode_request"], 0.5)
    assert math.isclose(allocations[second]["deployed_capital"], 0.5)
    assert math.isclose(allocations[third]["episode_request"], 0.0, abs_tol=1e-15)
    assert math.isclose(allocations[third]["deployed_capital"], 0.0, abs_tol=1e-15)
    assert allocations[low]["raw_request"] == allocations[low]["deployed_capital"] == 0.0
    assert math.isclose(simulation["episodes"][0]["cumulative_deployed"], 1.0)
    assert simulation["flow"]["entered"] == 30
    assert simulation["flow"]["missed_for_exhausted_envelope"] == 2
    assert simulation["flow"]["low_intensity_skips"] == 1
    assert min(row["cash"] for row in simulation["daily"]) >= 0.0
    assert max(row["exposure"] for row in simulation["daily"]) <= 1.0
    assert math.isclose(simulation["daily"][-1]["nav"], 1.0)
