from pathlib import Path
import json
import pandas as pd

OUT = Path(__file__).parent / "output"

def test_recovery_status(): assert json.loads((OUT / "gate_decision_v2.json").read_text())["status"] == "SMV6_PRECAPITAL_RECOVERED"
def test_post2023_counts():
    d = pd.read_csv(OUT / "smv6_post2023_precapital_opportunities.csv.gz"); assert d.decision_at.notna().all(); assert d.decision_at.str[:4].value_counts().to_dict()["2024"] == 40
def test_all_buy_provenance(): assert len(pd.read_csv(OUT / "smv6_post2023_native_buy_provenance.csv")) == 106
def test_zero_unmatched(): assert pd.read_csv(OUT / "smv6_post2023_reconciliation.csv").unmatched_buy_count.iloc[0] == 0
def test_unfunded_preserved(): assert pd.read_csv(OUT / "smv6_post2023_reconciliation.csv").legal_opportunity_not_funded_count.iloc[0] > 0
def test_cutoff_not_economic(): assert pd.read_csv(OUT / "smv6_2023_cutoff_semantics.csv").classification.iloc[0] == "D_OLD_ARTIFACT_EXPORT_BOUNDARY"
def test_input_coverage(): assert pd.read_csv(OUT / "smv6_post2023_input_coverage.csv").available.all()
def test_prefixes(): assert (pd.read_csv(OUT / "smv6_post2023_prefix_invariance.csv").future_invariance == "PASS_REGISTERED_FULL_REPLAY_PREFIX").all()
def test_no_fill_shortcut(): assert set(pd.read_csv(OUT / "smv6_post2023_precapital_opportunities.csv.gz").source_kind) == {"continuous_registered_callback_event_stream"}
def test_priority_closed(): assert (pd.read_csv(OUT / "causal_priority_evidence.csv").gate_result == "NO_STABLE_CAUSAL_PRIORITY_RULE").all()
def test_final_keep_native(): assert "KEEP_NATIVE" in (OUT.parent / "REPORT_V2.md").read_text()
