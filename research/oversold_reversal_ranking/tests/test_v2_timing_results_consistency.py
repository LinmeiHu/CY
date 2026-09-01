from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

LANE = Path(__file__).resolve().parents[1]
RESULTS = LANE / "reports" / "v2_timing_results.json"
REPORT = LANE / "reports" / "V2_TIMING_REPORT.md"


def _assert_finite(value: Any) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def test_v2_policy_counts_and_outputs_reconcile() -> None:
    payload = json.loads(RESULTS.read_text())
    _assert_finite(payload)
    assert payload["verdict"] == "RISK_FILTER_ONLY"
    assert set(payload["checks"].values()) == {0}
    assert all(
        item["content_hash_verified"]
        for item in payload["input_identities"]["data_files"]
    )
    sample = payload["sample_profile"]
    waiting = payload["primary_waiting_summary"]
    assert waiting["opportunities"] == sample["valid_deep_events"]
    assert waiting["trigger_signals"] + waiting["no_trigger_events"] == waiting["opportunities"]
    assert (
        waiting["executed_triggers"] + waiting["rejected_trigger_entries"]
        == waiting["trigger_signals"]
    )
    assert (
        payload["primary_trigger_curve"][-1]["cumulative_triggered"]
        == waiting["trigger_signals"]
    )
    assert (
        sum(row["trigger_signals"] for row in payload["primary_lag_distribution"])
        == waiting["trigger_signals"]
    )
    for key in ("primary_entry_anchored", "primary_event_anchored"):
        assert {row["policy"] for row in payload[key]} == {
            "IMMEDIATE",
            "FIXED_DELAY_1",
            "REVERSAL_WAIT",
        }
        assert {row["opportunities"] for row in payload[key]} == {
            sample["valid_deep_events"]
        }


def test_v2_report_agrees_with_machine_output() -> None:
    payload = json.loads(RESULTS.read_text())
    report = REPORT.read_text()
    n = payload["sample_profile"]["valid_deep_events"]
    assert f"Primary valid de-duplicated events: {n:,}" in report
    assert "`RISK_FILTER_ONLY`" in report
    assert report.count("## SINGLE NEXT STEP") == 1
    required = {
        "## FROZEN CARRIER",
        "## EVENT COHORT",
        "## PRIMARY REVERSAL TRIGGER",
        "## WAITING POLICY",
        "## IMMEDIATE BASELINE",
        "## FIXED-DELAY CONTROL",
        "## REVERSAL-TIMING POLICY",
        "## FAIR POLICY COMPARISON",
        "## WAITING COST",
        "## NO-TRIGGER EVENTS",
        "## FALLING-KNIFE RISK",
        "## V-SHAPED REBOUND COST",
        "## FIXED-DELAY ATTRIBUTION",
        "## DEPTH INTERACTION",
        "## TIME STABILITY",
        "## LIQUIDITY / INDUSTRY SANITY",
        "## ECONOMIC INTERPRETATION",
        "## VERDICT",
    }
    assert required.issubset(set(report.splitlines()))

    event_rows = {row["policy"]: row for row in payload["primary_event_anchored"]}
    labels = {
        "IMMEDIATE": "Immediate",
        "FIXED_DELAY_1": "Fixed delay 1",
        "REVERSAL_WAIT": "Reversal wait",
    }
    for policy, label in labels.items():
        row = event_rows[policy]
        expected_prefix = (
            f"| {label} | {row['n_trades']:,} | {row['participation_rate']:.2%} | "
            f"{row['mean_event_ret_20']:.2%} | {row['median_event_ret_20']:.2%} | "
            f"{row['positive_event_rate_20']:.2%} |"
        )
        assert expected_prefix in report

    waiting = payload["primary_waiting_summary"]
    assert (
        f"{waiting['trigger_signals']:,} trigger ({waiting['trigger_rate']:.2%})"
        in report
    )
    no_trigger = next(
        row
        for row in payload["primary_immediate_counterfactuals"]
        if row["cohort"] == "NO_TRIGGER"
    )
    assert f"{no_trigger['n']:,} no-trigger events" in report
    assert (
        f"| Mean | {no_trigger['mean_ret_5']:.2%} | {no_trigger['mean_ret_10']:.2%} | "
        f"{no_trigger['mean_ret_20']:.2%} |"
        in report
    )
