import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3] / "research/chinext_v1"
REPORTS = ROOT / "reports"


def test_breadth_spec_is_frozen_and_governed():
    spec = json.loads((REPORTS / "chinext_v1_phase10a3_breadth_spec.json").read_text())
    assert spec["status"] == "FROZEN_BEFORE_OUTCOME_ANALYSIS"
    assert spec["minimum_valid_coverage"] == 0.95
    assert spec["governance"]["formal_replay_executions"] == 0
    assert spec["governance"]["current_survivor_fallback"] == "NO"
    assert spec["features"] == [
        "above_ma20_breadth", "above_ma60_breadth",
        "positive_20d_momentum_breadth", "positive_60d_momentum_breadth",
        "b60_breakout_breadth", "cross_sectional_median_20d_return",
        "cross_sectional_median_close_vs_ma20",
    ]


def test_breadth_audit_zero_replay_and_exact_dates():
    summary = json.loads((REPORTS / "chinext_v1_phase10a3_breadth_audit_summary.json").read_text())
    assert summary["phase10a3_result"] == "PASS"
    assert summary["formal_replay_executions"] == 0
    assert summary["new_trades"] == 0
    assert summary["new_nav"] == 0
    assert summary["pit_rebuilt"] == "NO"
    assert summary["strategy_modified"] == "NO"
    assert summary["daily_date_count"] == 969
    assert summary["temporal_matched"]["frozen_pair_count"] == 33
    assert summary["temporal_matched"]["usable_pair_count"] == 33


def test_daily_breadth_has_lf_and_exact_feature_columns():
    p = REPORTS / "chinext_v1_phase10a3_daily_breadth.csv"
    data = p.read_bytes()
    assert b"\r" not in data
    header = data.splitlines()[0].decode()
    for col in ("trade_date", "pit_member_count", "above_ma20_breadth", "b60_breakout_breadth", "cross_sectional_median_20d_return"):
        assert col in header


def test_daily_breadth_denominator_and_coverage_contract():
    import csv

    p = REPORTS / "chinext_v1_phase10a3_daily_breadth.csv"
    rows = list(csv.DictReader(p.open(newline="")))
    assert len(rows) == 969
    assert len({r["trade_date"] for r in rows}) == len(rows)
    for r in rows[:10]:
        n = int(r["pit_member_count"])
        valid = int(r["above_ma20_breadth_valid_count"])
        assert abs(float(r["above_ma20_breadth_coverage"]) - valid / n) < 1e-12
        if valid / n < 0.95:
            assert r["above_ma20_breadth"] == ""


def test_frozen_inputs_and_b60_is_completed_day_exclusive():
    summary = json.loads((REPORTS / "chinext_v1_phase10a3_breadth_audit_summary.json").read_text())
    assert summary["strategy_sha256"] == "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    assert summary["development_pit_manifest_sha256"] == "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7"
    assert summary["holdout_pit_manifest_sha256"] == "4763562dac0538961b8fa5435b7a9475d92bc6e6562faca259b6429ff86bcb43"
    source = (ROOT / "scripts/run_chinext_v1_phase10a3_breadth_audit.py").read_text()
    assert "shift(1).rolling(60" in source
    assert "current_survivor" not in source.lower()
