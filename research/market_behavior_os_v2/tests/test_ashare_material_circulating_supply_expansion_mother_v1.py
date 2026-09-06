import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_material_circulating_supply_expansion_mother_v1_stage_a as stage_a,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_material_circulating_supply_expansion_mother_v1_stage_b as stage_b,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_material_circulating_supply_expansion_mother_v1_charts as charts,
)


def test_causal_cooldown_uses_only_prior_admitted_event() -> None:
    frame = pd.DataFrame(
        [
            {"event_id": "a", "symbol": "000001.SZ", "signal_cal_idx": 100, "signal_date": pd.Timestamp("2018-01-01"), "causal_industry": "X"},
            {"event_id": "b", "symbol": "000001.SZ", "signal_cal_idx": 150, "signal_date": pd.Timestamp("2018-03-01"), "causal_industry": "X"},
            {"event_id": "c", "symbol": "000001.SZ", "signal_cal_idx": 221, "signal_date": pd.Timestamp("2018-07-01"), "causal_industry": "X"},
        ]
    )
    result = stage_a.causal_cooldown(frame)
    assert result.event_id.tolist() == ["a", "c"]


def test_supply_shock_definition_is_single_frozen_material_threshold() -> None:
    assert stage_a.MINIMUM_SHARE_INCREASE == 0.5
    assert stage_a.COOLDOWN == 120


def test_anatomy_entry_and_horizons_are_frozen() -> None:
    assert stage_b.HORIZONS == (20, 60, 120)
    assert stage_b.ROUND_TRIP_COST == 0.004
    assert stage_b.MAXIMUM_CONTEXT_DATE == pd.Timestamp("2021-06-30")


def test_chart_bucket_uses_frozen_four_percent_boundary() -> None:
    assert charts.outcome_bucket("COMPLETED", 0.04) == "PROFIT_GE_4PCT"
    assert charts.outcome_bucket("COMPLETED", 0.039) == "PROFIT_0_TO_4PCT"
    assert charts.outcome_bucket("COMPLETED", -0.10) == "SEVERE_LOSS"
