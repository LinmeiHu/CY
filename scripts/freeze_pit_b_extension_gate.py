#!/usr/bin/env python3
"""Produce an explicit fail-closed year gate for the 2010-2017 extension."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe-audit", required=True)
    p.add_argument("--input-audit", required=True)
    p.add_argument("--bar-audit")
    p.add_argument("--cross-audit")
    p.add_argument("--lineage-audit")
    p.add_argument("--bridge-audit")
    p.add_argument("--output", required=True)
    ns = p.parse_args()
    universe = json.loads(Path(ns.universe_audit).read_text(encoding="utf-8"))
    inputs = json.loads(Path(ns.input_audit).read_text(encoding="utf-8"))
    input_reasons = list(inputs.get("gate_reasons", []))
    input_metrics = {
        "industry_events": inputs.get("industry_events", {}),
        "qmt_capital": inputs.get("qmt_capital", {}),
    }
    lineage = json.loads(Path(ns.lineage_audit).read_text(encoding="utf-8")) if ns.lineage_audit else None
    lineage_reasons = list(lineage.get("gate_reasons", [])) if lineage else []
    bridge = json.loads(Path(ns.bridge_audit).read_text(encoding="utf-8")) if ns.bridge_audit else None
    bridge_reasons = list(bridge.get("failure_reasons", [])) if bridge else []
    bridge_assets = {item.get("asset"): item for item in (bridge or {}).get("assets", [])}
    years = {}
    for year, item in universe.get("annual", {}).items():
        reasons = []
        if not item.get("research_ready"):
            reasons.append("historical security universe lacks complete date-effective coverage or has failed snapshots")
        if bridge:
            # The materialized bridge is the authoritative contract for fields
            # it emits. Keep the raw-source audits as evidence, but do not let
            # their pre-bridge missing lineage fields create contradictory gate
            # reasons.
            if not bridge_assets.get("QD-008-industry", {}).get("research_ready", False):
                reasons.append("historical industry bridge is not research-ready")
            if not bridge_assets.get("QD-009-circulating-capital", {}).get("research_ready", False):
                reasons.append("historical circulating-capital bridge is not research-ready")
        else:
            reasons.append("industry/capital row-level PIT join and revision lineage are not activated")
            reasons.extend(input_reasons)
            reasons.extend(lineage_reasons)
        # Row-level hard-invalid observations are excluded, not an annual
        # failure.  This is the PIT-B policy used by the 2020-2026 sample.
        row_exclusions = [reason for reason in bridge_reasons if "hard_valid=false" in reason]
        blockers = [reason for reason in bridge_reasons if "hard_valid=false" not in reason]
        reasons.extend(blockers)
        ready = not reasons
        years[year] = {
            "status": "RESEARCH_CONDITIONAL" if ready else "FAIL_CLOSED",
            "research_ready": ready,
            "row_exclusions": row_exclusions,
            "reasons": reasons,
        }
    report = {
        "asset_id": "CYQ-PIT-B-EXTENSION-2010-2017",
        "status": "RESEARCH_CONDITIONAL",
        "registry_activation": "UNAVAILABLE",
        "annual": years,
        "evidence": {"universe_audit": ns.universe_audit, "input_audit": ns.input_audit},
        "input_audit_summary": {"gate_reasons": input_reasons, "metrics": input_metrics},
        "bridge_audit_summary": {
            "failure_reasons": bridge_reasons,
            "assets": bridge_assets,
            "raw_source_audits_retained_as_evidence": True,
        } if bridge else None,
        "policy": "PIT-B conditional sample excludes row-level hard_invalid observations; registry activation remains required before state, signals, sizing, execution, backtests, or performance claims.",
    }
    if ns.lineage_audit:
        report["evidence"]["lineage_contract_audit"] = ns.lineage_audit
    if ns.bridge_audit:
        report["evidence"]["historical_pit_bridge_audit"] = ns.bridge_audit
    if ns.bar_audit:
        report["evidence"]["bar_universe_audit"] = ns.bar_audit
    if ns.cross_audit:
        report["evidence"]["cross_table_pit_audit"] = ns.cross_audit
    out = Path(ns.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
