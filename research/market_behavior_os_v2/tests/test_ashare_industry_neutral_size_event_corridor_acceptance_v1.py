from types import SimpleNamespace

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_industry_neutral_size_event_corridor_acceptance_v1_stage_1 as stage_1,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_industry_neutral_size_event_corridor_acceptance_v1_stage_2 as stage_2,
)


def close_row(cal_idx: int, close: float) -> SimpleNamespace:
    timestamp = pd.Timestamp("2020-01-01 15:00:00") + pd.Timedelta(days=cal_idx)
    return SimpleNamespace(
        cal_idx=cal_idx,
        coord_high=close + 0.1,
        coord_low=close - 0.1,
        coord_close=close,
        invalid_step_cum=2.0,
        available_at=timestamp,
        decision_at=timestamp,
        current_day_data_tradable=True,
        current_valid=True,
        hard_valid=True,
        trade_status=1,
    )


def test_acceptance_requires_current_close_and_three_of_five_above() -> None:
    accepted = [close_row(idx, close) for idx, close in enumerate([9.9, 10.1, 10.2, 9.9, 10.3], 1)]
    rejected_current = [close_row(idx, close) for idx, close in enumerate([10.1, 10.2, 10.3, 10.1, 9.9], 1)]
    assert stage_1.price_acceptance(accepted, 10.0, 2.0)
    assert not stage_1.price_acceptance(rejected_current, 10.0, 2.0)


def test_acceptance_fails_closed_on_coordinate_lineage_change() -> None:
    rows = [close_row(idx, 10.2) for idx in range(1, 6)]
    rows[2].invalid_step_cum = 3.0
    assert not stage_1.price_acceptance(rows, 10.0, 2.0)


def test_market_opportunity_is_bull_or_strict_dual_repair() -> None:
    timestamp = pd.Timestamp("2020-01-01 15:00:00")
    repaired = SimpleNamespace(
        market_regime="TRANSITION",
        market_median_ret20=-0.02,
        market_median_ret60=-0.10,
        market_positive_ret20_share=0.45,
        market_positive_ret60_share=0.30,
        latest_source_timestamp=timestamp,
    )
    stale = SimpleNamespace(**{**repaired.__dict__, "latest_source_timestamp": timestamp + pd.Timedelta(seconds=1)})
    one_leg = SimpleNamespace(**{**repaired.__dict__, "market_positive_ret20_share": 0.20})
    assert stage_1.market_opportunity(repaired, timestamp)
    assert not stage_1.market_opportunity(stale, timestamp)
    assert not stage_1.market_opportunity(one_leg, timestamp)


def test_frozen_timing_and_breadth_constants() -> None:
    assert stage_1.FORMATION_SESSIONS == 5
    assert (stage_1.TRIGGER_RELATIVE_START, stage_1.TRIGGER_RELATIVE_END) == (5, 19)
    assert stage_1.ENTRY_DELAY_MAX == 3
    assert stage_1.TIME_EXIT_SESSIONS == 120
    assert stage_1.MINIMUM_ANNUAL_COMPLETED_STRICT == 50


def test_stage_2_summary_uses_net_return_and_strict_boundaries() -> None:
    frame = pd.DataFrame(
        {
            "net_return": [0.04, 0.10, -0.10, -0.02],
            "holding_market_sessions": [5, 10, 20, 25],
        }
    )
    result = stage_2.summarize(frame)
    assert result["n"] == 4
    assert result["positive_rate"] == 0.5
    assert result["profit_ge_4pct_rate"] == 0.5
    assert result["severe_loss_le_minus_10pct_rate"] == 0.25
    assert stage_2.ROUND_TRIP_COST == 0.004
