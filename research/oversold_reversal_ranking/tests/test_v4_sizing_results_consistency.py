from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

LANE = Path(__file__).resolve().parents[1]
RESULTS = LANE / "reports" / "v4_sizing_results.json"
V3_RESULTS = LANE / "reports" / "v3_risk_results.json"
REPORT = LANE / "reports" / "V4_SIZING_REPORT.md"


def _assert_finite(value: Any) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def test_v4_cohort_weights_and_contributions_reconcile() -> None:
    payload = json.loads(RESULTS.read_text())
    v3 = json.loads(V3_RESULTS.read_text())
    _assert_finite(payload)
    assert payload["verdict"] == "SIZING_SURVIVES"
    assert set(payload["checks"].values()) == {0}
    assert all(
        item["content_hash_verified"]
        for item in payload["input_identities"]["data_files"]
    )
    sample = payload["sample_profile"]
    assert sample["events"] == v3["sample_profile"]["valid_v3_events"] == 22_357
    assert sample["securities"] == v3["sample_profile"]["event_securities"]
    assert math.isclose(sample["primary_mean_weight"], 1.0, abs_tol=1e-12)
    assert math.isclose(sample["clv_primary_mean_weight"], 1.0, abs_tol=1e-12)
    assert sample["conservative_mean_weight"] < 1.0
    assert sum(row["n"] for row in sample["quintile_weights"]) == sample["events"]

    metrics = {row["policy"]: row for row in payload["policy_metrics"]}
    assert set(metrics) == {
        "EQUAL_SIZE",
        "RISK_AWARE_CAPITAL_PRESERVING",
        "CONSERVATIVE_OVERLAY",
        "CLV_ONLY_CAPITAL_PRESERVING",
    }
    assert {row["n"] for row in metrics.values()} == {sample["events"]}
    equal = metrics["EQUAL_SIZE"]
    primary = metrics["RISK_AWARE_CAPITAL_PRESERVING"]
    assert primary["mean_weighted_ret_20"] > equal["mean_weighted_ret_20"]
    assert primary["mean_capital_mae_20"] > equal["mean_capital_mae_20"]
    assert primary["q10_capital_mae_20"] > equal["q10_capital_mae_20"]
    assert primary["capital_severe_loss_rate"] < equal["capital_severe_loss_rate"]
    assert primary["return_downside_efficiency"] > equal["return_downside_efficiency"]
    assert math.isclose(
        primary["underlying_severe_event_rate"], equal["underlying_severe_event_rate"]
    )

    contributions = payload["quintile_contributions"]
    assert sum(row["n"] for row in contributions) == sample["events"]
    assert math.isclose(
        sum(row["weighted_ret_20_contribution"] for row in contributions),
        primary["mean_weighted_ret_20"],
        abs_tol=1e-12,
    )
    assert math.isclose(
        sum(row["capital_mae_20_contribution"] for row in contributions),
        primary["mean_capital_mae_20"],
        abs_tol=1e-12,
    )


def test_v4_allocation_and_stability_support_verdict() -> None:
    payload = json.loads(RESULTS.read_text())
    allocation = payload["capital_allocation_comparison"]
    assert allocation["UNDERLYING_SEVERE"]["capital_share_difference"] < 0
    assert allocation["V2_NO_TRIGGER"]["capital_share_difference"] < 0
    assert allocation["POSITIVE_RET20"]["capital_share_difference"] > 0
    assert allocation["LARGE_WINNER_RET20_GE_10"]["capital_share_difference"] > 0
    assert allocation["LOSING_RET20"]["capital_share_difference"] < 0

    by_period: dict[str, dict[str, dict[str, Any]]] = {}
    for row in payload["time_stability"]:
        by_period.setdefault(row["v4_time_block"], {})[row["policy"]] = row
    assert set(by_period) == {"2018-2020", "2021-2023", "2024-2026"}
    for rows in by_period.values():
        equal = rows["EQUAL_SIZE"]
        primary = rows["RISK_AWARE_CAPITAL_PRESERVING"]
        assert primary["mean_weighted_ret_20"] > equal["mean_weighted_ret_20"]
        assert primary["q10_capital_mae_20"] > equal["q10_capital_mae_20"]
        assert primary["return_downside_efficiency"] > equal["return_downside_efficiency"]
        assert primary["severe_event_capital_share"] < equal["severe_event_capital_share"]
        assert primary["no_trigger_capital_share"] < equal["no_trigger_capital_share"]

    by_liquidity: dict[int, dict[str, dict[str, Any]]] = {}
    for row in payload["liquidity_sanity"]:
        by_liquidity.setdefault(row["liquidity_tercile"], {})[row["policy"]] = row
    assert set(by_liquidity) == {1, 2, 3}
    for rows in by_liquidity.values():
        equal = rows["EQUAL_SIZE"]
        primary = rows["RISK_AWARE_CAPITAL_PRESERVING"]
        assert primary["return_downside_efficiency"] > equal["return_downside_efficiency"]
        assert primary["severe_event_capital_share"] < equal["severe_event_capital_share"]


def test_v4_report_agrees_with_machine_output() -> None:
    payload = json.loads(RESULTS.read_text())
    report = REPORT.read_text()
    sample = payload["sample_profile"]
    metrics = {row["policy"]: row for row in payload["policy_metrics"]}
    primary = metrics["RISK_AWARE_CAPITAL_PRESERVING"]
    assert f"V4 reuses all {sample['events']:,} valid V3 events" in report
    assert f"| Mean weighted Ret20 | 4.37% | {primary['mean_weighted_ret_20']:.2%} |" in report
    assert "`SIZING_SURVIVES`" in report
    assert report.count("## SINGLE NEXT STEP") == 1
    required = {
        "## ENVIRONMENT",
        "## PREDECESSOR FINDINGS",
        "## FROZEN CARRIER AND SCORE",
        "## FROZEN SIZING POLICIES",
        "## PRIMARY EQUAL-CAPITAL COMPARISON",
        "## CAPITAL ALLOCATION",
        "## QUINTILE CONTRIBUTIONS",
        "## CONSERVATIVE OVERLAY",
        "## SIMPLE BASELINE COMPARISON",
        "## TIME STABILITY",
        "## LIQUIDITY / INDUSTRY SANITY",
        "## LIMITATIONS",
        "## ECONOMIC INTERPRETATION",
        "## VERDICT",
    }
    assert required.issubset(set(report.splitlines()))
