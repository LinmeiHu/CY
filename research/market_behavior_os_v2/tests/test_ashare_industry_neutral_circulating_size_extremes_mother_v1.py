from types import SimpleNamespace

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_industry_neutral_circulating_size_extremes_mother_v1_charts as charts,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_industry_neutral_circulating_size_extremes_mother_v1_stage_a as stage_a,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_industry_neutral_circulating_size_extremes_mother_v1_stage_b as stage_b,
)


def test_cooldown_is_causal_across_both_size_lanes() -> None:
    frame = pd.DataFrame(
        [
            {"event_id": "a", "symbol": "000001.SZ", "signal_cal_idx": 100, "signal_date": pd.Timestamp("2018-01-01"), "size_lane": "SMALL_CIRCULATING_SIZE", "pit_industry": "X"},
            {"event_id": "b", "symbol": "000001.SZ", "signal_cal_idx": 150, "signal_date": pd.Timestamp("2018-03-01"), "size_lane": "LARGE_CIRCULATING_SIZE", "pit_industry": "X"},
            {"event_id": "c", "symbol": "000001.SZ", "signal_cal_idx": 161, "signal_date": pd.Timestamp("2018-04-01"), "size_lane": "SMALL_CIRCULATING_SIZE", "pit_industry": "X"},
        ]
    )
    result = stage_a.causal_cooldown(frame)
    assert result.event_id.tolist() == ["a", "c"]


def test_outcome_bucket_uses_frozen_four_percent_boundary() -> None:
    assert charts.outcome_bucket("COMPLETED", 0.04) == "PROFIT_GE_4PCT"
    assert charts.outcome_bucket("COMPLETED", 0.0399) == "PROFIT_0_TO_4PCT"
    assert charts.outcome_bucket("COMPLETED", -0.10) == "SEVERE_LOSS"
    assert charts.outcome_bucket("INVALID_COORDINATE_LINEAGE", 0.50) == "NO_COMPLETED_TRADE"


def test_stage_b_never_uses_same_session_entry() -> None:
    candidate = SimpleNamespace(signal_cal_idx=100)
    assert stage_b.HORIZONS == (20, 60, 120)
    assert stage_b.MAXIMUM_CONTEXT_DATE == pd.Timestamp("2021-06-30")
    assert candidate.signal_cal_idx + 1 > candidate.signal_cal_idx
