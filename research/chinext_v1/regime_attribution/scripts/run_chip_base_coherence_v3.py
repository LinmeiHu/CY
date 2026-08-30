#!/usr/bin/env python3
"""Contract-exact EXP-CBC-003 execution of unchanged H-025 science."""

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

SPEC = WORK / "experiments/EXP-CBC-003_spec.json"
OUTPUT_TABLE = WORK / "artifacts/chip_base_coherence_attribution_v3.csv"
OUTPUT_JSON = WORK / "artifacts/chip_base_coherence_attribution_v3.json"
REPORT = WORK / "reports/chip_base_coherence_attribution_v3.md"
EVIDENCE_PACKET = WORK / "reports/chip_base_coherence_v3_evidence_packet.md"
DISCOVERY_YEARS = (2020, 2021, 2022, 2023)
MIN_CONTROLLED_N = 120


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-CBC-003":
        raise base.ChipCoherenceError("unexpected contract-exact experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_CONTRACT_EXACT_CHIP_ASSOCIATION":
        raise base.ChipCoherenceError("contract-exact experiment is not frozen")
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


def rank_association_exact(frame: Any, feature: str, endpoint: str) -> dict[str, Any]:
    observed = tuple(sorted(int(year) for year in frame.entry_year.unique()))
    if observed != DISCOVERY_YEARS:
        raise base.ChipCoherenceError(f"unexpected discovery years: {observed}")
    full = base.wla.safe_spearman(frame[feature], frame[endpoint])
    ranked = frame[[feature, endpoint, "entry_year"]].copy()
    ranked["x_rank"] = ranked.groupby("entry_year")[feature].rank(
        pct=True, method="average"
    )
    ranked["y_rank"] = ranked.groupby("entry_year")[endpoint].rank(
        pct=True, method="average"
    )
    within = base.wla.safe_spearman(ranked.x_rank, ranked.y_rank)
    loyo = {
        str(year): base.wla.safe_spearman(
            frame.loc[frame.entry_year != year, feature],
            frame.loc[frame.entry_year != year, endpoint],
        )
        for year in DISCOVERY_YEARS
    }
    positive = sum(
        item["rho"] is not None and item["rho"] > 0 for item in loyo.values()
    )
    negative = sum(
        item["rho"] is not None and item["rho"] < 0 for item in loyo.values()
    )
    return {
        **full,
        "within_year_rank_rho": within["rho"],
        "within_year_rank_p_value": within["p_value"],
        "loyo": loyo,
        "loyo_positive_count": int(positive),
        "loyo_negative_count": int(negative),
    }


def partial_rank_exact(
    frame: Any,
    feature: str,
    endpoint: str,
    *,
    extra_controls: tuple[str, ...] = (),
    category_controls: tuple[str, ...] = ("entry_year",),
) -> dict[str, Any]:
    np = base.d5d.np
    pd = base.d5d.pd
    controls = [*base.BASE_CONTROLS, *extra_controls]
    columns = [feature, endpoint, *controls, *category_controls]
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    result = {"n": int(len(data)), "partial_rank_rho": None, "p_value": None}
    if (
        len(data) < MIN_CONTROLLED_N
        or data[feature].nunique() < 2
        or data[endpoint].nunique() < 2
    ):
        return result
    predictor = data[feature].rank(pct=True, method="average").to_numpy(float)
    if pd.api.types.is_bool_dtype(data[endpoint]):
        outcome = data[endpoint].astype(float).to_numpy()
    else:
        outcome = data[endpoint].rank(pct=True, method="average").to_numpy(float)
    ranked = np.column_stack(
        [data[column].rank(pct=True, method="average") for column in controls]
    )
    design_parts = [np.ones((len(data), 1)), ranked]
    for category in category_controls:
        dummies = pd.get_dummies(
            data[category].astype(str), prefix=category, drop_first=True, dtype=float
        )
        if len(dummies.columns):
            design_parts.append(dummies.to_numpy(float))
    design = np.column_stack(design_parts)
    x_residual = predictor - design @ np.linalg.lstsq(
        design, predictor, rcond=None
    )[0]
    y_residual = outcome - design @ np.linalg.lstsq(design, outcome, rcond=None)[0]
    if np.std(x_residual) == 0 or np.std(y_residual) == 0:
        return result
    estimate = base.d5d.pearsonr(x_residual, y_residual)
    result["partial_rank_rho"] = base.wla.finite_or_none(estimate.statistic)
    result["p_value"] = base.wla.finite_or_none(estimate.pvalue)
    return result


def controlled_loyo_exact(frame: Any, feature: str, endpoint: str) -> dict[str, Any]:
    observed = tuple(sorted(int(year) for year in frame.entry_year.unique()))
    if observed != DISCOVERY_YEARS:
        raise base.ChipCoherenceError(f"unexpected discovery years: {observed}")
    full = partial_rank_exact(frame, feature, endpoint)
    loyo = {
        str(year): partial_rank_exact(
            frame[frame.entry_year != year], feature, endpoint
        )
        for year in DISCOVERY_YEARS
    }
    if any(item["n"] < MIN_CONTROLLED_N for item in loyo.values()):
        raise base.ChipCoherenceError("pre-audited controlled omission became too small")
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    return {**full, "loyo": loyo, "loyo_positive_count": int(positive)}


def analyze(frame: Any) -> dict[str, Any]:
    feature = "chip_base_coherence"
    raw = rank_association_exact(frame, feature, "mfe")
    controlled = controlled_loyo_exact(frame, feature, "mfe")
    i70 = rank_association_exact(frame, "chip_base_coherence_i70", "mfe")
    opportunity = rank_association_exact(frame, feature, "opportunity20")
    non_false = rank_association_exact(frame, feature, "non_false_breakout")
    duration_exit = partial_rank_exact(
        frame,
        feature,
        "mfe",
        extra_controls=("holding_trading_days",),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    ex_top4 = rank_association_exact(
        frame.loc[~base.top_pnl_flag(frame, 4)], feature, "mfe"
    )
    ex_severe = rank_association_exact(
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
        "narrow_i90": rank_association_exact(frame, "narrow_i90", "mfe"),
        "i90_base_retention": rank_association_exact(
            frame, "i90_base_retention", "mfe"
        ),
        "upward_cost_migration": rank_association_exact(
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
        "experiment_id": "EXP-CBC-003",
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
            "loyo_years": list(DISCOVERY_YEARS),
            "minimum_controlled_n": MIN_CONTROLLED_N,
            "scientific_inheritance": "EXP-CBC-001_EXACT_SCIENCE_WITH_CONTRACT_EXACT_DISCOVERY_YEAR_LOYO",
        }
    )
    columns = [
        "trade_id", "baseline_block", "symbol", "entry_signal_date", "entry_year",
        "entry_industry", "available_at", "daily_snapshot_id", "minute_snapshot_id",
        "state_version", "mass_sum", "state_quality", "cyqk_close_pre",
        "i90_width_pct", "i70_width_pct", "i90_base_retention",
        "i70_base_retention", "migration_mass", "average_cost_delta",
        "upward_cost_migration", "narrow_i90", "narrow_i70",
        "chip_base_coherence", "chip_base_coherence_i70", "mfe", "opportunity20",
        "false_breakout", "non_false_breakout", "severe_loss", "realized_pnl",
        "holding_trading_days", "canonical_exit_reason", *base.BASE_CONTROLS,
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
    report = base.build_report(result, audit).replace("EXP-CBC-001", "EXP-CBC-003")
    base.atomic_write(REPORT, report)
    base.atomic_write(
        EVIDENCE_PACKET,
        report.replace("# Chip-base", "# EXP-CBC-003 structured evidence — Chip-base"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
