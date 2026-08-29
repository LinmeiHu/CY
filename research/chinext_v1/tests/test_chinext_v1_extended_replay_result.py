"""Integrity lock for the single preregistered V1 2018-2021 first view."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_extended_replay_summary.json"
REPORT = ROOT / "research/chinext_v1/reports/chinext_v1_extended_replay.md"
MANIFEST = (
    ROOT / "research/chinext_v1/reports/chinext_v1_extended_replay_artifact_manifest.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_preregistered_first_view_metrics_and_sample_status_are_frozen() -> None:
    result = json.loads(SUMMARY.read_text(encoding="utf-8"))
    formal = result["formal_replay"]
    assert formal["execution_count"] == 1
    assert formal["label"] == "PREREGISTERED_EXTENDED_HISTORY_VALIDATION"
    assert formal["sample_status_after_run"] == (
        "CONSUMED_PREREGISTERED_EXTENDED_HISTORY_VALIDATION"
    )
    assert formal["performance_generated_before_preregistration"] is False
    assert formal["ledger_summary_determinism"] == "PASS_BYTE_IDENTICAL"
    assert result["portfolio"]["total_return"] == 0.6482237267899993
    assert result["portfolio"]["max_drawdown"] == -0.20762679470782652
    assert result["execution"]["completed_round_trip_count"] == 194
    assert result["portfolio"]["win_rate"] == 0.4536082474226804
    assert result["portfolio"]["median_trade_return"] == -0.00970512426371722
    assert result["portfolio"]["average_trade_return"] == 0.030455684400042576
    assert result["pnl_concentration"]["top20_positive_pnl_concentration"] == (
        0.7351787051890619
    )
    assert result["pnl_concentration"]["return_ex_best20"] == -0.5015728892100006
    assert {year: row["return"] for year, row in result["year_by_year"].items()} == {
        "2018": -0.03783516999999992,
        "2019": 0.23490683088052555,
        "2020": 0.05267228742443164,
        "2021": 0.31776904262665284,
    }


def test_tracked_manifest_binds_summary_report_and_raw_ledgers() -> None:
    result = json.loads(SUMMARY.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["files"]["summary"]["sha256"] == sha256(SUMMARY)
    assert manifest["files"]["report"]["sha256"] == sha256(REPORT)
    for name in ("daily_nav", "event_ledger", "execution_ledger"):
        assert manifest["files"][name]["sha256"] == result["audit"][f"{name}_sha256"]
