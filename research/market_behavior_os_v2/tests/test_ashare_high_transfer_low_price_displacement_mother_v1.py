from types import SimpleNamespace

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_high_transfer_low_price_displacement_mother_v1_stage_a as stage_a,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_high_transfer_low_price_displacement_mother_v1_stage_b as stage_b,
)


def test_causal_cooldown_uses_last_admitted_event() -> None:
    raw = pd.DataFrame(
        {
            "symbol": ["A", "A", "A", "B"],
            "signal_cal_idx": [100, 110, 121, 105],
            "signal_date": pd.to_datetime(
                ["2015-01-01", "2015-01-15", "2015-02-02", "2015-01-08"]
            ),
            "event_id": ["A|1", "A|2", "A|3", "B|1"],
        }
    )
    result = stage_a.causal_cooldown(raw)
    assert result.event_id.tolist() == ["A|1", "B|1", "A|3"]


def test_buy_and_sell_limits_are_strict() -> None:
    base = dict(
        trade_status=1,
        current_day_data_tradable=True,
        current_valid=True,
        market_rule_valid=True,
        corporate_action_valid=True,
        corporate_action_blocking=False,
        corporate_action_count=0,
        hard_valid=True,
        open=10.0,
        coord_open=10.0,
        coordinate_factor=1.0,
        up_limit_price=11.0,
        down_limit_price=9.0,
    )
    assert stage_b.buyable(SimpleNamespace(**base))
    assert stage_b.sellable_open(SimpleNamespace(**base))
    assert not stage_b.buyable(SimpleNamespace(**{**base, "open": 11.0}))
    assert not stage_b.sellable_open(SimpleNamespace(**{**base, "open": 9.0}))


def test_industry_compound_requires_eighty_percent_coverage() -> None:
    lookup = {("I", idx): 0.01 for idx in range(101, 105)}
    assert np.isclose(stage_b.industry_compound(lookup, "I", 100, 5), 1.01**4 - 1)
    del lookup[("I", 104)]
    assert np.isnan(stage_b.industry_compound(lookup, "I", 100, 5))


def test_frozen_horizons_are_not_parameterized() -> None:
    assert stage_b.HORIZONS == (5, 20, 60, 120)
    assert stage_b.ROUND_TRIP_COST == 0.004
