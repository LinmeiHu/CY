#!/usr/bin/env python3
"""Clean EXP-CBC-002 execution of unchanged H-025 science."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_chip_base_coherence as base  # noqa: E402

SPEC = WORK / "experiments/EXP-CBC-002_spec.json"
OUTPUT_TABLE = WORK / "artifacts/chip_base_coherence_attribution_v2.csv"
OUTPUT_JSON = WORK / "artifacts/chip_base_coherence_attribution_v2.json"
REPORT = WORK / "reports/chip_base_coherence_attribution_v2.md"
EVIDENCE_PACKET = WORK / "reports/chip_base_coherence_v2_evidence_packet.md"


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-CBC-002":
        raise base.ChipCoherenceError("unexpected clean experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_VALID_CHIP_OUTCOME_ASSOCIATION":
        raise base.ChipCoherenceError("clean experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = base.resolve_path(binding["path"])
        actual = base.sha256_file(path) if path.is_file() else "MISSING"
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise base.ChipCoherenceError(f"frozen input mismatch: {mismatches}")
    base.validate_registry()
    inventory_audit = base.validate_inventory()
    return spec, {**identities, **{k: str(v) for k, v in inventory_audit.items()}}


def analyze(frame: Any) -> dict[str, Any]:
    feature = "chip_base_coherence"
    raw = base.wla.rank_association(frame, feature, "mfe")
    controlled = base.d5d.controlled_loyo(
        frame, feature, "mfe", extra_controls=()
    )
    i70 = base.wla.rank_association(frame, "chip_base_coherence_i70", "mfe")
    opportunity = base.wla.rank_association(frame, feature, "opportunity20")
    non_false = base.wla.rank_association(frame, feature, "non_false_breakout")
    duration_exit = base.d5d.partial_rank(
        frame,
        feature,
        "mfe",
        extra_controls=("holding_trading_days",),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    ex_top4 = base.wla.rank_association(
        frame.loc[~base.top_pnl_flag(frame, 4)], feature, "mfe"
    )
    ex_severe = base.wla.rank_association(
        frame.loc[~frame.severe_loss], feature, "mfe"
    )
    security = base.wla.omit_group_sensitivity(frame, feature, "mfe", "symbol")
    industry = base.wla.omit_group_sensitivity(
        frame, feature, "mfe", "entry_industry"
    )
    blocks = {
        str(name): base.wla.safe_spearman(rows[feature], rows.mfe)
        for name, rows in frame.groupby("baseline_block", sort=True)
    }
    components = {
        "narrow_i90": base.wla.rank_association(frame, "narrow_i90", "mfe"),
        "i90_base_retention": base.wla.rank_association(
            frame, "i90_base_retention", "mfe"
        ),
        "upward_cost_migration": base.wla.rank_association(
            frame, "upward_cost_migration", "mfe"
        ),
    }
    raw_gate = bool(
        raw["rho"] is not None
        and raw["rho"] >= 0.12
        and raw["within_year_rank_rho"] is not None
        and raw["within_year_rank_rho"] > 0
        and raw["loyo_positive_count"] == 4
    )
    controlled_gate = bool(
        controlled["partial_rank_rho"] is not None
        and controlled["partial_rank_rho"] >= 0.10
        and controlled["loyo_positive_count"] == 4
    )
    neighbor_gate = bool(
        i70["rho"] is not None
        and i70["rho"] > 0
        and i70["loyo_positive_count"] >= 3
        and opportunity["rho"] is not None
        and opportunity["rho"] > 0
        and opportunity["loyo_positive_count"] >= 3
        and non_false["rho"] is not None
        and non_false["rho"] > 0
        and non_false["loyo_positive_count"] >= 3
    )
    block_rhos = [packet["rho"] for packet in blocks.values()]
    temporal_gate = bool(
        len(block_rhos) == 2
        and all(value is not None and value > 0 for value in block_rhos)
    )
    component_rhos = [packet["rho"] for packet in components.values()]
    component_gate = bool(
        sum(value is not None and value > 0 for value in component_rhos) >= 2
        and all(value is not None and value >= -0.05 for value in component_rhos)
    )
    falsification_gate = bool(
        duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.08
        and ex_top4["rho"] is not None
        and ex_top4["rho"] > 0
        and ex_severe["rho"] is not None
        and ex_severe["rho"] > 0
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
        and component_gate
    )
    if all((raw_gate, controlled_gate, neighbor_gate, temporal_gate, falsification_gate)):
        decision = "VALIDATE"
        verdict = "CHIP_BASE_COHERENCE_DESERVES_LOCKED_TEMPORAL_VALIDATION"
    elif raw_gate and controlled_gate:
        decision = "REFINE"
        verdict = "CHIP_BASE_COHERENCE_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION"
    elif raw_gate:
        decision = "PIVOT"
        verdict = "RAW_CHIP_COHERENCE_IS_REDUNDANT_OR_UNSTABLE"
    else:
        decision = "REJECT"
        verdict = "NO_STABLE_CHIP_BASE_COHERENCE_OPPORTUNITY_EFFECT"
    return {
        "experiment_id": "EXP-CBC-002",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "raw": raw,
            "controlled": controlled,
            "i70_neighbor": i70,
            "opportunity20": opportunity,
            "non_false_breakout": non_false,
            "duration_exit_control": duration_exit,
            "ex_top4_pnl": ex_top4,
            "ex_severe_loss": ex_severe,
            "leave_one_security_out": security,
            "leave_one_industry_out": industry,
            "blocks": blocks,
            "components": components,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "neighbor_gate": neighbor_gate,
            "temporal_gate": temporal_gate,
            "component_gate": component_gate,
            "falsification_gate": falsification_gate,
        },
        "strategy_modification": "NONE",
        "holdout_access": "NONE_2024_2026_REMAINS_LOCKED",
        "interpretation_boundary": (
            "PIT-B discovery on already-consumed 2020-2023 outcomes cannot authorize "
            "a chip filter, threshold, ranking, sizing, entry, exit, or production rule"
        ),
    }


def main() -> int:
    spec, identities = validate_spec()
    frame, audit = base.load_frame(spec)
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": base.sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_PIT_B_DISCOVERY",
            "duckdb_version": base.duckdb.__version__,
            "scientific_inheritance": "EXP-CBC-001_EXACT_EXCEPT_FRESH_ID_PATHS_AND_EXPLICIT_EMPTY_CONTROL_ARGUMENT",
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_year",
        "entry_industry",
        "available_at",
        "daily_snapshot_id",
        "minute_snapshot_id",
        "state_version",
        "mass_sum",
        "state_quality",
        "cyqk_close_pre",
        "i90_width_pct",
        "i70_width_pct",
        "i90_base_retention",
        "i70_base_retention",
        "migration_mass",
        "average_cost_delta",
        "upward_cost_migration",
        "narrow_i90",
        "narrow_i70",
        "chip_base_coherence",
        "chip_base_coherence_i70",
        "mfe",
        "opportunity20",
        "false_breakout",
        "non_false_breakout",
        "severe_loss",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
        *base.BASE_CONTROLS,
    ]
    base.atomic_write(
        OUTPUT_TABLE,
        frame[columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    base.atomic_write(
        OUTPUT_JSON,
        json.dumps(base.wla.clean_json(result), indent=2, sort_keys=True) + "\n",
    )
    report = base.build_report(result, audit).replace("EXP-CBC-001", "EXP-CBC-002")
    base.atomic_write(REPORT, report)
    base.atomic_write(
        EVIDENCE_PACKET,
        report.replace(
            "# Chip-base", "# EXP-CBC-002 structured evidence — Chip-base"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
