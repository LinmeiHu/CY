from pathlib import Path
import pandas as pd

OUT = Path(__file__).parent / "output"


def master():
    return pd.read_csv(OUT / "opportunity_master.csv.gz")


def test_master_exists(): assert (OUT / "opportunity_master.csv.gz").exists()
def test_master_nonempty(): assert len(master()) > 5000
def test_required_strategies(): assert {"ATRDR Bull", "ATRDR Fast Bear", "ATRDR Slow Bear", "MCB", "OGR", "IFCGR", "SMV6"} <= set(master().strategy)
def test_unique_opportunity_ids(): assert master().opportunity_id.is_unique
def test_period_lower(): assert pd.to_datetime(master().decision_at).min() >= pd.Timestamp("2018-01-01")
def test_period_upper(): assert pd.to_datetime(master().decision_at).max() <= pd.Timestamp("2026-09-04 23:59:59")
def test_requested_nonnegative(): assert (master().native_requested_notional.dropna() >= 0).all()
def test_funded_nonnegative(): assert (master().native_funded.dropna() >= 0).all()
def test_no_future_priority(): assert "future" not in " ".join(master().columns).lower()
def test_metric_audit_exists(): assert (OUT / "metric_hardening_audit.csv").exists()
def test_metric_audit_guard(): assert (pd.read_csv(OUT / "metric_hardening_audit.csv").query("metric == 'native_identity'").status == "PASS").all()
def test_quality_summary_exists(): assert (OUT / "signal_quality_summary.csv").exists()
def test_quality_summary_strategies(): assert len(pd.read_csv(OUT / "signal_quality_summary.csv")) == 7
def test_supply_exists(): assert (OUT / "opportunity_supply_demand.csv").exists()
def test_cross_exists(): assert (OUT / "cross_strategy_interaction.csv").exists()
def test_pairing_exists(): assert (OUT / "ogr_ifcgr_pairing.csv").exists()
def test_architecture_fail_closed():
    d = pd.read_csv(OUT / "architecture_diagnostic.csv"); assert (d.status == "DIAGNOSTIC_ONLY_NO_CAUSAL_PRIORITY").sum() == 2
def test_marginal_fail_closed():
    d = pd.read_csv(OUT / "marginal_capital_diagnostic.csv"); assert len(d) == 21 and d.status.nunique() == 1
def test_no_negative_funding(): assert (master().native_funded >= 0).all()
def test_unavailable_forward_labels_are_nan(): assert master()[["ret_1d", "mfe_5d", "mae_20d"]].isna().all().all()
def test_report_exists(): assert (OUT.parent / "REPORT.md").exists()
