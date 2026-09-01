from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

LANE = Path(__file__).resolve().parents[1]
RESULTS = LANE / "reports" / "v7_episode_results.json"
REPORT = LANE / "reports" / "V7_EPISODE_REPORT.md"


def _assert_finite(value: Any) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def test_v7_controls_chronology_envelopes_and_results_reconcile() -> None:
    payload = json.loads(RESULTS.read_text())
    _assert_finite(payload)
    assert payload["verdict"] == "EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE"
    assert set(payload["checks"].values()) == {0}
    assert all(
        identity["content_hash_verified"]
        for identity in payload["input_identities"]["data_files"]
    )
    assert all(
        control["maximum_absolute_difference"] == 0.0
        for control in payload["control_reproduction"].values()
    )
    sample = payload["sample_profile"]
    assert sample["events"] == 22_357
    assert sample["securities"] == 4_835
    assert sample["active_signal_dates"] == 1_228
    assert sample["episodes"] == len(payload["episode_diagnostics"]) == 59
    assert [row["episode_session"] for row in payload["capital_timing_by_episode_session"]] == list(
        range(1, 21)
    )
    for episode in payload["episode_diagnostics"]:
        assert math.isclose(
            episode["episode_envelope"], episode["episode_start_nav"], abs_tol=1e-14
        )
        assert episode["cumulative_deployed_capital"] <= episode["episode_envelope"] + 1e-12
        assert 0.0 <= episode["envelope_utilization"] <= 1.0 + 1e-12

    flow = payload["signal_flow"]["V7_EPISODE_GROSS"]
    assert (
        flow["entered"]
        + flow["low_intensity_skips"]
        + flow["missed_for_zero_cash"]
        + flow["missed_for_exhausted_envelope"]
        == sample["events"]
    )
    assert flow["overlapping_security_skips"] == 0
    assert flow["invalid_entry_price"] == 0


def test_v7_episode_structure_improves_full_sample_but_fails_stability_gate() -> None:
    payload = json.loads(RESULTS.read_text())
    metrics = payload["portfolio_metrics"]
    v5 = metrics["V5_EQUAL_GROSS"]
    v6 = metrics["V6_COUNT_AWARE_GROSS"]
    v7 = metrics["V7_EPISODE_GROSS"]
    assert math.isclose(v5["ending_nav"], 1.0016248464593533, abs_tol=1e-14)
    assert math.isclose(v6["ending_nav"], 1.0195803468609994, abs_tol=1e-14)
    assert math.isclose(v7["ending_nav"], 1.1611851190229434, abs_tol=1e-14)
    assert v7["max_drawdown"] > v6["max_drawdown"] > v5["max_drawdown"]
    assert v7["average_exposure"] < v6["average_exposure"] < v5["average_exposure"]

    blocks = payload["time_stability"]
    assert all(row["v7_minus_v6"] > 0 for row in blocks)
    assert sum(row["v7_minus_v5"] > 0 for row in blocks) == 1
    assert blocks[-1]["v7_gross_return"] < 0
    episodes = payload["episode_summary"]
    assert episodes["episode_win_rate"] < 0.50
    assert episodes["median_episode_pnl"] < 0
    assert episodes["positive_pnl_share_top_ten_percent"] > 0.52

    saturation = payload["capital_saturation_comparison"]
    assert saturation["V7_EPISODE_BUDGET"]["cash_blocked_percentage"] < saturation[
        "V6_DATE_BUDGET"
    ]["cash_blocked_percentage"]
    assert saturation["V7_EPISODE_BUDGET"]["fraction_high_intensity_signals_any_allocation"] < 0.55
    assert saturation["V7_EPISODE_BUDGET"]["zero_allocation_signals_cash"] > saturation[
        "V6_DATE_BUDGET"
    ]["zero_allocation_signals_cash"]


def test_v7_report_contains_required_evidence_and_closes_lane() -> None:
    payload = json.loads(RESULTS.read_text())
    report = REPORT.read_text()
    required = {
        "## 1. EXECUTIVE CONCLUSION",
        "## 2. ENVIRONMENT / COMMIT / VALIDATION",
        "## 3. FROZEN RESEARCH HISTORY",
        "## 4. V7 HYPOTHESIS AND FROZEN CONTRACT",
        "## 5. CONTROL REPRODUCTION",
        "## 6. EPISODE POPULATION",
        "## 7. PER-EPISODE ECONOMICS",
        "## 8. CAPITAL SATURATION",
        "## 9. CAPITAL TIMING WITHIN EPISODES",
        "## 10. EVENT / DATE / CLUSTER / EPISODE BRIDGE",
        "## 11. GROSS PORTFOLIO COMPARISON",
        "## 12. ANNUAL RESULTS",
        "## 13. BROAD-PERIOD STABILITY",
        "## 14. DRAWDOWN AND RISK INTERPRETATION",
        "## 15. ECONOMIC INTERPRETATION",
        "## 16. EXACT VERDICT",
        "## 17. CAPITALIZATION-LANE CLOSURE",
    }
    assert required.issubset(set(report.splitlines()))
    assert report.count("## 17. CAPITALIZATION-LANE CLOSURE") == 1
    assert f"`{payload['verdict']}`" in report
    assert "1.1612" in report
    assert "52.44%" in report
    assert "54.70%" in report
    assert "No V8 rescue study is recommended" in report
