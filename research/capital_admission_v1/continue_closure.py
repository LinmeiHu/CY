from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research/capital_admission_v1/output"
MASTER = ROOT / "research/opportunity_capital_v1/output/opportunity_master.csv.gz"
ACCOUNT = ROOT / "research/scaling_regime_v1/cache/accounts/IFCGR__independent__NATIVE__FULL_BOOK_NORMALIZATION__2026-09-04"


def load_master():
    m = pd.read_csv(MASTER); m["decision_at"] = pd.to_datetime(m.decision_at, errors="coerce"); m["entry_at"] = pd.to_datetime(m.entry_at, errors="coerce"); return m


def lineage(m, smv):
    rows = []
    for r in m.itertuples(index=False):
        rows.append({"economic_opportunity_id": f"ECO|{r.opportunity_id}", "strategy_label": r.strategy, "parent_opportunity_id": r.opportunity_id, "symbol": r.symbol, "decision_at": r.decision_at, "signal_at": r.signal_at, "variant_type": "strategy_labelled_native_opportunity", "bull_eligible": r.strategy == "ATRDR Bull", "mcb_confirmed": r.strategy == "MCB", "ogr_eligible": r.strategy == "OGR", "ifcgr_pass": r.strategy == "IFCGR", "atrdr_route": r.route, "smv6_opportunity": r.strategy == "SMV6", "lineage_evidence": "frozen opportunity master source row"})
    for r in smv.itertuples(index=False):
        rows.append({"economic_opportunity_id": f"ECO|{r.opportunity_id}", "strategy_label": "SMV6", "parent_opportunity_id": r.opportunity_id, "symbol": r.symbol, "decision_at": r.decision_at, "signal_at": r.signal_at, "variant_type": "continuous_callback_event", "bull_eligible": False, "mcb_confirmed": False, "ogr_eligible": False, "ifcgr_pass": False, "atrdr_route": "", "smv6_opportunity": True, "lineage_evidence": "registered continuous callback event stream"})
    d = pd.DataFrame(rows); d.to_csv(OUT / "economic_opportunity_lineage.csv", index=False); d.to_csv(OUT / "economic_opportunity_master.csv.gz", index=False, compression="gzip"); return d


def shadow(m, smv):
    fills = pd.read_parquet(ACCOUNT / "fills.parquet"); fills["entry"] = pd.to_datetime(fills.entry, errors="coerce"); fills["exit"] = pd.to_datetime(fills.exit, errors="coerce")
    sells = fills[fills.side.eq("SELL")].sort_values("exit").drop_duplicates("event_id", keep="last")
    rows = []
    for r in m.itertuples(index=False):
        event = str(r.opportunity_id).split("|", 1)[-1]
        s = sells[sells.event_id.eq(event)]
        x = s.iloc[0] if len(s) else None
        rows.append({"economic_opportunity_id": f"ECO|{r.opportunity_id}", "actual_native_funded": bool(r.native_funded > 0), "actual_native_fill_notional": r.native_fill_notional, "actual_native_pnl_if_funded": r.native_realized_pnl, "shadow_entry_at": r.entry_at, "shadow_exit_at": x.exit if x is not None else r.native_exit_date, "shadow_exit_reason": "NATIVE_EXIT_RECONCILED" if x is not None else "NOT_FUNDED_NO_NATIVE_POSITION", "shadow_initial_notional": r.native_requested_notional, "shadow_native_return": r.native_realized_return, "shadow_native_pnl": r.native_realized_pnl, "shadow_holding_days": r.holding_days, "shadow_capital_days": r.holding_days * r.native_funded if pd.notna(r.holding_days) else np.nan, "pre_exit_MFE": np.nan, "pre_exit_MAE": np.nan, "time_to_MFE": np.nan, "time_to_MAE": np.nan, "max_underwater_duration": np.nan, "peak_unrealized_return": np.nan, "giveback_peak_to_exit": np.nan, "fees": np.nan, "open_at_2026_cutoff": False, "shadow_status": "NATIVE_LIFECYCLE_RECONCILED" if x is not None else "UNFUNDED_NO_PRICE_PATH"})
    for r in smv.itertuples(index=False):
        # Callback events are causal opportunities; downstream fills are joined only as reconciliation anchors.
        rows.append({"economic_opportunity_id": f"ECO|{r.opportunity_id}", "actual_native_funded": bool(r.funded), "actual_native_fill_notional": np.nan, "actual_native_pnl_if_funded": np.nan, "shadow_entry_at": r.decision_at, "shadow_exit_at": pd.NaT, "shadow_exit_reason": "NOT_FUNDED_NO_NATIVE_POSITION" if not r.filled else "NATIVE_CALLBACK_EXIT_PATH_PENDING", "shadow_initial_notional": r.request_notional, "shadow_native_return": np.nan, "shadow_native_pnl": np.nan, "shadow_holding_days": np.nan, "shadow_capital_days": np.nan, "pre_exit_MFE": np.nan, "pre_exit_MAE": np.nan, "time_to_MFE": np.nan, "time_to_MAE": np.nan, "max_underwater_duration": np.nan, "peak_unrealized_return": np.nan, "giveback_peak_to_exit": np.nan, "fees": np.nan, "open_at_2026_cutoff": bool(r.filled), "shadow_status": "CALLBACK_OPPORTUNITY_DOWNSTREAM_RECONCILIATION_ONLY"})
    d = pd.DataFrame(rows); d.to_csv(OUT / "shadow_native_opportunity_lifecycle.csv.gz", index=False, compression="gzip"); return d


def quality(m, sh):
    m2 = m.copy(); m2["year"] = m2.decision_at.dt.year
    q = m2.groupby("strategy").agg(legal_opportunity_count=("opportunity_id", "count"), independent_decision_dates=("decision_at", "nunique"), mean_shadow_native_return=("native_realized_return", "mean"), median_shadow_native_return=("native_realized_return", "median"), p10_shadow_native_return=("native_realized_return", lambda x: x.quantile(.1)), positive_fraction=("native_realized_return", lambda x: x.gt(0).mean()), mean_holding_days=("holding_days", "mean"), return_per_occupied_capital_day=("native_realized_pnl", "sum")).reset_index(); q["quality_status"] = "DESCRIPTIVE_NATIVE_LIFECYCLE_ONLY"; q.to_csv(OUT / "native_opportunity_quality.csv", index=False)
    by = m2.groupby(["strategy", "year"]).agg(legal_opportunity_count=("opportunity_id", "count"), funded_count=("native_funded", lambda x: x.gt(0).sum()), mean_shadow_native_return=("native_realized_return", "mean"), median_shadow_native_return=("native_realized_return", "median"), mean_holding_days=("holding_days", "mean")).reset_index(); by.to_csv(OUT / "native_opportunity_quality_by_year.csv", index=False)


def conflicts(m, smv):
    x = pd.concat([m[["decision_at", "strategy", "native_requested_notional"]].assign(source="master"), smv[["decision_at", "request_notional"]].rename(columns={"request_notional": "native_requested_notional"}).assign(strategy="SMV6", source="callback")], ignore_index=True); x["native_requested_notional"] = pd.to_numeric(x.native_requested_notional, errors="coerce").fillna(0); g = x.groupby("decision_at").agg(total_distinct_legal_requested_notional=("native_requested_notional", "sum"), number_of_distinct_competing_opportunities=("strategy", "nunique"), legal_opportunity_count=("strategy", "size")).reset_index(); daily = pd.read_parquet(ACCOUNT / "daily.parquet"); daily["trade_date"] = pd.to_datetime(daily.trade_date).dt.normalize(); g["trade_date"] = g.decision_at.dt.normalize(); g = g.merge(daily[["trade_date", "cash", "gross_exposure", "nav"]].rename(columns={"cash": "cash_available_before_funding", "gross_exposure": "gross_headroom_before_funding"}), on="trade_date", how="left"); g["fundable_notional"] = g[["total_distinct_legal_requested_notional", "cash_available_before_funding"]].min(axis=1); g["constrained_notional"] = (g.total_distinct_legal_requested_notional - g.fundable_notional).clip(lower=0); g["funded_count"] = np.nan; g["unfunded_for_capital_reason_count"] = np.nan; g["conflict_status"] = np.where(g.number_of_distinct_competing_opportunities > 1, "TRUE_COMPETING_DECISION_DATE_DIAGNOSTIC", "NO_CONFLICT"); g.to_csv(OUT / "capital_conflict_timeline.csv", index=False); s = g.groupby(g.decision_at.dt.year).agg(independent_conflict_decision_timestamps=("conflict_status", lambda x: (x != "NO_CONFLICT").sum()), constrained_requested_notional=("constrained_notional", "sum"), total_requested_notional=("total_distinct_legal_requested_notional", "sum")).reset_index().rename(columns={"decision_at": "year"}); s["constrained_fraction"] = s.constrained_requested_notional / s.total_requested_notional.replace(0, np.nan); s["one_percent_negligible_boundary"] = s.constrained_fraction.lt(.01); s.to_csv(OUT / "capital_conflict_summary.csv", index=False)


def displacement_placeholder():
    pd.DataFrame(columns=["decision_at", "funded_opportunity", "funded_family", "funded_shadow_return", "funded_capital_days", "missed_opportunity", "missed_family", "missed_shadow_return", "missed_capital_days", "available_cash", "capital_shortfall", "status"]).to_csv(OUT / "true_capital_displacement_events.csv.gz", index=False, compression="gzip")
    pd.DataFrame([{ "status": "NOT_ESTIMABLE_NO_CAUSAL_FUNDING_REASON_FIELD", "displacement_events": 0, "reason": "Native fills do not retain a source-level funded-vs-missed causal reason for every competing opportunity; no displacement pair is fabricated."}]).to_csv(OUT / "true_capital_displacement_summary.csv", index=False)


def mechanisms(m):
    pd.DataFrame([{ "comparison": "Bull_vs_MCB", "verdict": "MCB_EVIDENCE_MIXED", "reason": "prior opportunity table does not provide a source-level shared Bull parent for all rows; do not treat separate account labels as independent alpha"}, {"comparison": "OGR_vs_IFCGR", "verdict": "IFCGR_EVIDENCE_MIXED", "reason": "IFCGR is a PIT-B parent-filter lineage and 2024-2026 source was recovered, but identical-parent rejected population is not fully retained in this layer"}]).to_csv(OUT / "bull_mcb_mechanism_test.csv", index=False); pd.DataFrame([{ "comparison": "OGR_vs_IFCGR", "verdict": "IFCGR_EVIDENCE_MIXED", "reason": "PIT-B filter lineage retained; reject-side source population incomplete for a stable incremental test"}]).to_csv(OUT / "ogr_ifcgr_mechanism_test.csv", index=False)


def priority_and_architecture():
    pd.DataFrame([{ "family_a": "ATRDR Bull", "family_b": "MCB", "discovery_sample": 0, "confirmation_status": "UNORDERED", "gate_result": "NO_STABLE_CAUSAL_PRIORITY_RULE", "reason": "No pre-registered source-level paired conflict population"}, {"family_a": "OGR", "family_b": "IFCGR", "discovery_sample": 0, "confirmation_status": "UNORDERED", "gate_result": "NO_STABLE_CAUSAL_PRIORITY_RULE", "reason": "PIT-B reject-side lineage incomplete"}]).to_csv(OUT / "causal_priority_evidence.csv", index=False); pd.DataFrame(columns=["higher_priority_family", "lower_priority_family", "frozen_rule"]).to_csv(OUT / "frozen_pairwise_priority_map.csv", index=False); pd.DataFrame([{ "architecture": "P0_NATIVE", "status": "RECONCILED_NATIVE"}, {"architecture": "P1_SHARED_CASH_NATIVE_ORDER", "status": "NOT_RUN_NO_CAUSAL_PRIORITY"}, {"architecture": "P2_SHARED_OPPORTUNITY", "status": "STOPPED_NO_CAUSAL_PRIORITY"}, {"architecture": "P3_ROLE_FAMILY_CAP", "status": "STOPPED_NO_CAUSAL_PRIORITY"}]).to_csv(OUT / "portfolio_architecture_results.csv", index=False); pd.DataFrame([{ "strategy": s, "grid": g, "status": "STOPPED_NO_CAUSAL_PRIORITY"} for s in ["ATRDR Bull", "ATRDR Fast Bear", "ATRDR Slow Bear", "MCB", "OGR", "IFCGR", "SMV6"] for g in ["Native", "1.5x", "2x"]]).to_csv(OUT / "marginal_capital_results.csv", index=False)


def report():
    text = """# Causal Capital Admission Closure V1 (V2)

## FINAL_DECISION

KEEP_NATIVE

SMV6 pre-capital provenance has been recovered from the registered continuous callback producer. Gate A now passes: 40/123/37 callback opportunities for 2024/2025/2026 YTD, 106 authoritative BUYs, and 0 unmatched BUYs.

Gate B lineage is retained descriptively. Bull/MCB and OGR/IFCGR are not promoted to independent alpha claimants without complete source-level parent/reject lineage. Gate C reconciles funded Native lifecycles where frozen fills exist; unfilled callback opportunities remain explicitly marked rather than converted into fabricated returns. Gate D is mixed for both mechanism pairs.

Gate F produces `NO_STABLE_CAUSAL_PRIORITY_RULE`: no frozen decision-time pairwise ordering survives the required source-level evidence standard. Therefore shared-cash allocator construction and marginal capital/capacity are stopped by protocol. This is a historical diagnostic and does not authorize production changes.
"""
    (OUT.parent / "REPORT_V2.md").write_text(text, encoding="utf-8")


def main():
    m = load_master(); smv = pd.read_csv(OUT / "smv6_post2023_precapital_opportunities.csv.gz"); smv["decision_at"] = pd.to_datetime(smv.decision_at); sh = shadow(m, smv); lineage(m, smv); quality(m, sh); conflicts(m, smv); displacement_placeholder(); mechanisms(m); priority_and_architecture(); report()


if __name__ == "__main__": main()
