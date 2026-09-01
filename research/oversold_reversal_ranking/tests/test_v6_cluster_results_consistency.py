from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

LANE = Path(__file__).resolve().parents[1]
RESULTS = LANE / "reports" / "v6_cluster_results.json"
REPORT = LANE / "reports" / "V6_CLUSTER_REPORT.md"


def _assert_finite(value: Any) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def test_v6_control_cohort_and_causal_budget_reconcile() -> None:
    payload = json.loads(RESULTS.read_text())
    _assert_finite(payload)
    assert payload["verdict"] == "CLUSTER_SIGNAL_EXISTS_BUT_CAPITAL_TRANSLATION_FAILS"
    assert set(payload["checks"].values()) == {0}
    assert payload["control_reproduction"]["maximum_absolute_difference"] == 0.0
    assert all(
        identity["content_hash_verified"]
        for identity in payload["input_identities"]["data_files"]
    )
    sample = payload["sample_profile"]
    distribution = payload["signal_count_distribution"]
    assert sample["events"] == distribution["total_events"] == 22_357
    assert sample["securities"] == 4_835
    assert sample["active_entry_dates"] == distribution["active_entry_dates"] == 1_228
    assert sum(distribution["active_date_regime_counts"].values()) == 1_228
    assert len(payload["count_forward_return"]["active_date_records"]) == 1_228
    assert len(payload["budget_diagnostics"]["active_date_records"]) == 1_228

    flow = payload["signal_flow"]["V6_COUNT_AWARE_EQUAL_GROSS"]
    assert flow["entered"] + flow["missed_for_zero_cash"] == sample["events"]
    assert flow["overlapping_security_skips"] == 0
    assert flow["invalid_entry_price"] == 0
    budget = payload["budget_diagnostics"]
    assert math.isclose(
        budget["total_desired_budget"] - budget["total_actual_budget"],
        budget["total_budget_shortfall"],
        abs_tol=1e-12,
    )
    assert budget["fraction_requested_budget_blocked"] > 0.70
    assert budget["highest_count_q5"]["fraction_requested_budget_blocked"] > 0.87


def test_v6_cluster_signal_and_portfolio_verdict_agree() -> None:
    payload = json.loads(RESULTS.read_text())
    bridge = payload["count_forward_return"]
    assert bridge["overall"]["spearman"] > 0.10
    assert bridge["count_rank_quintiles"][-1]["mean_basket_return"] > 0.018
    assert bridge["count_rank_quintiles"][0]["mean_basket_return"] < 0.0
    contribution = payload["event_alpha_contribution"]
    assert contribution["highest_count_dates"]["share_of_total_event_return"] > 0.97
    assert contribution["highest_count_dates"]["share_of_positive_event_return"] > 0.84

    metrics = payload["portfolio_metrics"]
    control = metrics["V5_EQUAL_GROSS_CONTROL"]
    treatment = metrics["V6_COUNT_AWARE_EQUAL_GROSS"]
    assert math.isclose(control["ending_nav"], 1.0016248464593533, abs_tol=1e-14)
    assert treatment["ending_nav"] > control["ending_nav"]
    assert treatment["max_drawdown"] > control["max_drawdown"]
    blocks = payload["time_stability"]
    assert sum(row["treatment_minus_control"] > 0 for row in blocks) == 1
    assert blocks[-1]["count_return_spearman"] < 0.0


def test_v6_report_contains_required_sections_and_machine_results() -> None:
    payload = json.loads(RESULTS.read_text())
    report = REPORT.read_text()
    required = {
        "## 1. EXECUTIVE CONCLUSION",
        "## 2. ENVIRONMENT / COMMIT / VALIDATION",
        "## 3. FROZEN RESEARCH HISTORY",
        "## 4. V5 FAILURE MECHANISM",
        "## 5. V6 HYPOTHESIS",
        "## 6. CAUSAL CAPITAL-BUDGET CONTRACT",
        "## 7. CONTROL REPRODUCTION",
        "## 8. SIGNAL-COUNT DISTRIBUTION",
        "## 9. COUNT -> FORWARD BASKET RETURN",
        "## 10. EVENT-ALPHA CONTRIBUTION BRIDGE",
        "## 11. GROSS PORTFOLIO COMPARISON",
        "## 12. CAPITAL SATURATION ANALYSIS",
        "## 13. HISTORICAL STABILITY",
        "## 14. FAILURE / SUCCESS MECHANISM",
        "## 15. EXACT VERDICT",
        "## 16. SINGLE HIGHEST-VALUE NEXT FRONTIER",
    }
    assert required.issubset(set(report.splitlines()))
    assert report.count("## 16. SINGLE HIGHEST-VALUE NEXT FRONTIER") == 1
    assert f"`{payload['verdict']}`" in report
    assert "1.0016248465" in report
    assert "1.0196" in report
    assert "71.33%" in report
    assert "97.92%" in report
