from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_clean_corridor_v26 as v26,
)


def test_clean_corridor_mask_is_inclusive_and_fails_closed() -> None:
    frame = pd.DataFrame(
        {
            "gap_width_pct": [0.03, 0.030001, 0.02, None],
            "pre_gap_corridor_touch_sessions": [10, 10, 11, 0],
        }
    )
    assert v26.clean_corridor_mask(frame).tolist() == [True, False, False, False]


def _combined(frequency: float, year_mean: float = 0.001) -> dict[str, object]:
    return {
        "accepted_trades_per_year": frequency,
        "mean_net": 0.031,
        "median_net": 0.01,
        "severe10": 0.10,
        "attack_date_equal_mean": 0.01,
        "yearly": {str(year): {"mean_net": year_mean} for year in v26.ALL_YEARS},
        "portfolio_annual_returns": {str(year): 0.001 for year in v26.ALL_YEARS},
    }


def test_goal_uses_combined_strict_annual_average_without_upper_cap() -> None:
    assert all(v26.goal_checks(_combined(500.0)).values())
    assert not v26.goal_checks(_combined(50.0))["accepted_trades_per_year_gt_50"]


def test_goal_requires_every_year_trade_mean_positive() -> None:
    item = _combined(60.0)
    item["yearly"]["2023"]["mean_net"] = -0.001  # type: ignore[index]
    assert not v26.goal_checks(item)["every_2017_2023_trade_mean_positive"]
