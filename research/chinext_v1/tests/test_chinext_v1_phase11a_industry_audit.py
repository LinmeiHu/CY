import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "research/chinext_v1"
REPORTS = ROOT / "reports"


def test_industry_spec_frozen_before_outcomes():
    spec = json.loads((REPORTS / "chinext_v1_phase11a_industry_spec.json").read_text())
    assert spec["status"] == "FROZEN_BEFORE_OUTCOME_ANALYSIS"
    assert spec["primary_industry_taxonomy"].startswith("CY-006")
    assert spec["same_industry_minimum_trades"] == 5
    assert spec["governance"]["formal_replay_executions"] == 0
    assert spec["governance"]["sector_cap_counterfactual"] == "NO"


def test_frozen_trade_identity_and_mapping_coverage():
    summary = json.loads((REPORTS / "chinext_v1_phase11a_industry_audit_summary.json").read_text())
    assert summary["phase11a_result"] == "PASS"
    assert summary["formal_replay_executions"] == 0
    assert summary["new_trades"] == 0
    assert summary["new_nav"] == 0
    assert summary["pit_rebuilt"] == "NO"
    assert summary["strategy_modified"] == "NO"
    assert summary["coverage_by_sample"]["OOS"]["trade_count"] == 94
    assert summary["coverage_by_sample"]["DEVELOPMENT"]["trade_count"] == 111
    assert summary["coverage_by_sample"]["OOS"]["coverage_rate"] == 1.0
    assert summary["coverage_by_sample"]["DEVELOPMENT"]["coverage_rate"] == 1.0
    assert summary["cyclical_mapping_status"] == "NOT_AVAILABLE"


def test_trade_industry_csv_is_lf_and_preserves_unmapped_column():
    p = REPORTS / "chinext_v1_phase11a_trade_industry.csv"
    data = p.read_bytes()
    assert b"\r" not in data
    rows = list(csv.DictReader(p.open(newline="")))
    assert len(rows) == 205
    assert {r["sample"] for r in rows} == {"OOS", "DEVELOPMENT"}
    assert "industry_status" not in rows[0] or rows[0]["pit_status"] == "PIT_VERIFIED_CY006_BOUNDED"


def test_no_current_classification_backfill_or_industry_filter():
    source = (ROOT / "scripts/run_chinext_v1_phase11a_industry_audit.py").read_text()
    assert "source_notice_date" in source
    assert "industry_valid" in source
    assert "current_survivor" not in source.lower()
    assert "sector_cap" not in source.lower() or "counterfactual" in source.lower()
