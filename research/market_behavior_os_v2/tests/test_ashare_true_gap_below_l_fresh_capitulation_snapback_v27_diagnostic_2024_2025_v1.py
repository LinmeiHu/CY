from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_fresh_capitulation_snapback_v27_diagnostic_2024_2025_v1 as subject,
)


def test_contract_keeps_v27_rule_and_strength_nonbinding() -> None:
    contract = subject.contract_value()
    assert contract["admission_unchanged"]["mature_decline"].endswith(">= 20")
    assert contract["admission_unchanged"]["fresh_shock"].startswith("gap_age <= 14")
    assert contract["former_strength_audit"]["binding_gate"] is False


def test_strength_summary_is_descriptive_and_exact() -> None:
    frame = pd.DataFrame(
        {
            "former_ordered_runup_120d": [0.20, 0.30, 0.50, 1.00],
            "pre_gap_drawdown_from_120d_peak": [0.20, 0.30, 0.40, 0.50],
            "pre_peak_to_gap_sessions": [20, 40, 60, 80],
        }
    )
    result = subject.strength_summary(frame)
    assert result["n"] == 4
    assert result["ordered_runup_ge_30pct_count"] == 3
    assert result["ordered_runup_ge_50pct_count"] == 2
    assert result["ordered_runup_ge_100pct_count"] == 1
    assert result["pre_gap_drawdown_ge_30pct_rate"] == 0.75


def test_diagnostic_verdict_does_not_call_mixed_result_validated() -> None:
    result = {
        "goal_checks": {"frequency": False, "mean": True},
        "portfolio": {"COMBINED": {"mean_net": 0.04}},
        "accepted_trade_yearly": {
            "2024": {"mean_net": 0.03},
            "2025": {"mean_net": 0.02},
        },
    }
    assert subject.diagnostic_verdict(result) == "V27_2024_2025_DIAGNOSTIC_MIXED"


def test_strength_outcome_summary_uses_only_predeclared_cuts() -> None:
    frame = pd.DataFrame(
        {
            "former_ordered_runup_120d": [0.20, 0.30, 0.49, 0.50],
            "entry_date": pd.to_datetime(
                ["2024-01-01", "2024-02-01", "2025-01-01", "2025-02-01"]
            ),
            "net_return": [0.01, 0.02, -0.01, 0.04],
        }
    )
    result = subject.strength_outcome_summary(frame)
    assert set(result) == {
        "runup_lt_30pct",
        "runup_ge_30pct",
        "runup_lt_50pct",
        "runup_ge_50pct",
    }
    assert result["runup_ge_30pct"]["n"] == 3
    assert result["runup_ge_50pct"]["n"] == 1
