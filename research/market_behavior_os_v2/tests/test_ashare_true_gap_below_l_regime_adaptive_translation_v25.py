from __future__ import annotations

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_regime_adaptive_translation_v25 as v25,
)


def test_translation_regime_uses_natural_zero_and_fails_closed() -> None:
    values = pd.Series([-0.001, 0.0, 0.01])
    assert v25.translation_regime(values).tolist() == [
        "WEAK_A50_H10",
        "REPAIRED_A67_H20",
        "REPAIRED_A67_H20",
    ]
    with pytest.raises(v25.V25Error, match="missing"):
        v25.translation_regime(pd.Series([None]))


def _development_item(frequency: float) -> dict[str, object]:
    return {
        "portfolio_accepted_trades_per_year": frequency,
        "portfolio_mean_net": 0.031,
        "portfolio_median_net": 0.01,
        "portfolio_severe10": 0.10,
        "positive_trade_mean_years": 4,
        "positive_portfolio_years": 4,
        "attack_date_equal_mean": 0.01,
        "post_2023_signal_count": 0,
    }


def test_frequency_is_strict_floor_without_upper_cap() -> None:
    assert all(v25.development_checks(_development_item(500.0)).values())
    assert not v25.development_checks(_development_item(50.0))["accepted_trades_per_year_gt_50"]


def test_contract_changes_translation_not_admission() -> None:
    contract = v25.contract_value()
    rule = contract["single_translation_rule"]
    assert rule["admission_filter"] == "NONE; all V24 signals remain eligible"
    assert rule["if_nonnegative"] == {"target": "A67 below L", "time_stop": "H20"}
    assert rule["if_negative"] == {"target": "A50 below L", "time_stop": "H10"}
