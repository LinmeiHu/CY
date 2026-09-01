from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

LANE = Path(__file__).resolve().parents[1]
RESULTS = LANE / "reports" / "results.json"
REPORT = LANE / "reports" / "REPORT.md"


def _assert_finite(value: Any) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def test_final_results_are_complete_and_finite() -> None:
    payload = json.loads(RESULTS.read_text())
    _assert_finite(payload)
    assert set(payload["checks"].values()) == {0}
    assert all(
        item["content_hash_verified"]
        for item in payload["input_identities"]["data_files"]
    )
    observations = payload["sample_profile"]["observations"]
    events = payload["sample_profile"]["dedup20_events"]
    assert sum(row["n"] for row in payload["depth_curve"]) == observations
    assert sum(row["n"] for row in payload["dedup20_depth_curve"]) == events
    for key in ("drawdown_x_crash_speed", "drawdown_x_relative_decline"):
        assert len(payload[key]) == 12
        assert sum(row["n"] for row in payload[key]) == observations
    for key in (
        "dedup20_drawdown_x_crash_speed",
        "dedup20_drawdown_x_relative_decline",
    ):
        assert len(payload[key]) == 12
        assert sum(row["n"] for row in payload[key]) == events


def test_report_agrees_with_machine_results() -> None:
    payload = json.loads(RESULTS.read_text())
    report = REPORT.read_text()
    sample = payload["sample_profile"]
    assert f"Complete observations: {sample['observations']:,}" in report
    assert f"Fixed 20-trading-session de-duplicated events: {sample['dedup20_events']:,}" in report
    assert "`DEPTH_ONLY`" in report
    assert report.count("## SINGLE NEXT STEP") == 1
    required = {
        "## DRAWDOWN DEPTH RESULTS",
        "## DRAWDOWN × CRASH SPEED",
        "## DRAWDOWN × RELATIVE DECLINE",
        "## THREE-AXIS INTERACTION",
        "## DAILY CROSS-SECTIONAL RESULTS",
        "## INCREMENTALITY",
        "## DE-DUPLICATION",
        "## TIME STABILITY",
        "## LIQUIDITY / INDUSTRY CHECK",
        "## FAILURE MODES",
        "## ECONOMIC INTERPRETATION",
        "## VERDICT",
    }
    assert required.issubset(set(report.splitlines()))
