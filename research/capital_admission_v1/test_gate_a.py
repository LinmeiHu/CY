from pathlib import Path
import json
import pandas as pd

OUT = Path(__file__).parent / "output"

def test_coverage_shape(): assert len(pd.read_csv(OUT / "strategy_year_coverage_reconciliation.csv")) == 63
def test_all_labels(): assert set(pd.read_csv(OUT / "strategy_year_coverage_reconciliation.csv").strategy) == {"ATRDR Bull", "ATRDR Fast Bear", "ATRDR Slow Bear", "MCB", "OGR", "IFCGR", "SMV6"}
def test_all_years(): assert set(pd.read_csv(OUT / "strategy_year_coverage_reconciliation.csv").year) == {str(x) for x in range(2018, 2026)} | {"2026 YTD"}
def test_hard_rule_failures_present(): assert len(pd.read_csv(OUT / "strategy_year_coverage_reconciliation.csv").query("coverage_status == 'FAIL_MISSING_PRECAPITAL'")) >= 3
def test_smv6_post2023_fail():
    d = pd.read_csv(OUT / "strategy_year_coverage_reconciliation.csv"); x = d[(d.strategy == "SMV6") & d.year.isin(["2024", "2025", "2026 YTD"])]
    assert (x.pre_capital_opportunity_count == 0).all() and (x.native_fill_count > 0).all()
def test_ifcgr_post2023_precapital():
    d = pd.read_csv(OUT / "strategy_year_coverage_reconciliation.csv"); x = d[(d.strategy == "IFCGR") & d.year.isin(["2024", "2025", "2026 YTD"])]
    assert (x.pre_capital_opportunity_count > 0).all() and (x.coverage_status == "PASS").all()
def test_trace_exists(): assert (OUT / "required_precapital_source_trace.csv").exists()
def test_smv6_trace_records_hard_cutoff():
    d = pd.read_csv(OUT / "required_precapital_source_trace.csv"); x = d[d.strategy == "SMV6"].iloc[0]
    assert "2024-01-01" in x.evidence and "hard-filters" in x.evidence
def test_decision_blocked(): assert json.loads((OUT / "gate_decision.json").read_text())["status"] == "BLOCKED_REQUIRED_PRECAPITAL_SOURCE_UNAVAILABLE"
def test_report_exists(): assert (OUT.parent / "REPORT.md").exists()
def test_original_gate_artifact_retained(): assert (OUT / "gate_decision.json").exists() and (OUT / "gate_decision_v2.json").exists()
