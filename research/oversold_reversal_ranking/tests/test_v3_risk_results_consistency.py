from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

LANE = Path(__file__).resolve().parents[1]
RESULTS = LANE / "reports" / "v3_risk_results.json"
REPORT = LANE / "reports" / "V3_RISK_REPORT.md"


def _assert_finite(value: Any) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def test_v3_counts_labels_and_cash_policies_reconcile() -> None:
    payload = json.loads(RESULTS.read_text())
    _assert_finite(payload)
    assert payload["verdict"] == "SIZING_SIGNAL_ONLY"
    assert set(payload["checks"].values()) == {0}
    assert all(
        item["content_hash_verified"]
        for item in payload["input_identities"]["data_files"]
    )
    sample = payload["sample_profile"]
    assert sample["v2_valid_events"] == 22_543
    assert sample["valid_v3_events"] == 22_357
    assert sample["feature_unavailable_events"] == 186
    assert sample["feature_attrition_reasons"] == {"ZERO_RANGE_T0": 186}

    n = sample["valid_v3_events"]
    assert sum(row["n"] for row in payload["composite_gradient"]) == n
    for rows in payload["individual_feature_gradients"].values():
        assert sum(row["n"] for row in rows) == n
    assert payload["baseline"]["severe_events"] == 9_422
    assert payload["baseline"]["no_trigger_events"] == 3_139

    baseline_return = payload["baseline"]["mean_ret_20"]
    for row in payload["veto_policies"]:
        assert row["original_opportunities"] == n
        skipped = round(row["skipped_event_rate"] * n)
        assert row["entered_trades"] + skipped == n
        if row["policy"] != "BUY_ALL":
            assert math.isclose(
                row["alpha_retention"],
                row["opportunity_mean_ret_20"] / baseline_return,
            )


def test_v3_report_agrees_with_machine_output() -> None:
    payload = json.loads(RESULTS.read_text())
    report = REPORT.read_text()
    sample = payload["sample_profile"]
    separation = payload["severe_risk_separation"]
    assert f"Valid V3 cohort: {sample['valid_v3_events']:,} events" in report
    assert f"{sample['feature_unavailable_events']} events have a zero-range t0 bar" in report
    assert (
        f"Severe-MAE incidence: {payload['baseline']['severe_mae_rate_20']:.2%} "
        f"({payload['baseline']['severe_events']:,} events)."
    ) in report
    spread_points = separation["q5_minus_q1_severe_mae_rate"] * 100
    assert f"Severe-MAE incidence: +{spread_points:.2f} percentage points." in report
    assert "`SIZING_SIGNAL_ONLY`" in report
    assert report.count("## SINGLE NEXT STEP") == 1
    required = {
        "## ENVIRONMENT",
        "## PREDECESSOR FINDINGS",
        "## FROZEN CARRIER",
        "## PRIMARY RISK OUTCOME",
        "## FROZEN t0 FEATURES",
        "## INDIVIDUAL FEATURE RESULTS",
        "## COMPOSITE RISK SCORE",
        "## SEVERE-RISK SEPARATION",
        "## CONDITIONAL / MATCHED RESULTS",
        "## RISK CAPTURE",
        "## VETO POLICY TABLE",
        "## ALPHA RETENTION",
        "## SKIPPED EVENTS",
        "## SIMPLE BASELINE COMPARISON",
        "## TIME STABILITY",
        "## ECONOMIC INTERPRETATION",
        "## VERDICT",
    }
    assert required.issubset(set(report.splitlines()))
