#!/usr/bin/env python3
"""Execute EXP-OBL-011 continuous selection-pressure follow-up."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_lineage_outcome_reveal as stats  # noqa: E402
import run_selection_lineage_outcome_reveal as selection  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-011_spec.json"
OUTPUT_TABLE = WORK / "artifacts/selection_pressure_outcome_reveal.csv"
OUTPUT_JSON = WORK / "artifacts/EXP-OBL-011_result.json"
REPORT = WORK / "reports/EXP-OBL-011_selection_pressure_outcome_reveal.md"
EVIDENCE_PACKET = WORK / "reports/EXP-OBL-011_evidence_packet.md"

PREDICTOR = "selection_pressure"
PRIMARY_ENDPOINTS = stats.PRIMARY_ENDPOINTS
CONTROL_COLUMNS = (*selection.CONTROL_COLUMNS, "contested_selection")


class PressureRevealError(RuntimeError):
    """Raised when a frozen binding, population, or decision contract fails."""


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-011":
        raise PressureRevealError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_POST_SECONDARY_BEFORE_EXECUTION":
        raise PressureRevealError("pressure follow-up is not frozen")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise PressureRevealError(f"missing bound input: {role}: {path}")
        actual = stats.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise PressureRevealError(f"frozen input mismatch: {mismatches}")
    return spec, identities


def endpoint_packet(frame: pd.DataFrame, endpoint: str) -> dict[str, Any]:
    return stats.endpoint_packet(frame, PREDICTOR, endpoint, CONTROL_COLUMNS)


def analyze(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    primary = {endpoint: endpoint_packet(frame, endpoint) for endpoint in PRIMARY_ENDPOINTS}
    qvalues = stats.benjamini_hochberg(
        {endpoint: primary[endpoint]["raw"]["pvalue"] for endpoint in PRIMARY_ENDPOINTS}
    )
    for endpoint in PRIMARY_ENDPOINTS:
        primary[endpoint]["raw_bh_qvalue"] = qvalues[endpoint]

    top4 = set(
        frame.assign(abs_pnl=frame.realized_pnl.abs()).nlargest(4, "abs_pnl").trade_id
    )
    attack_samples = {
        "ex_top1pct_absolute_pnl": frame[~frame.trade_id.isin(top4)],
        "ex_extreme_winners": frame[~frame.extreme_winner],
        "ex_severe_losses": frame[~frame.severe_loss],
        "ex_2025": frame[frame.entry_year != 2025],
        "post_2021": frame[frame.entry_year >= 2022],
    }
    attacks: dict[str, Any] = {
        name: {
            endpoint: stats.association(sample, PREDICTOR, endpoint)
            for endpoint in PRIMARY_ENDPOINTS
        }
        for name, sample in attack_samples.items()
    }
    component_frame, component_years = stats.add_year_dummies(frame)
    attacks["candidate_vacancy_components"] = {
        endpoint: stats.partial_rank(
            component_frame,
            PREDICTOR,
            endpoint,
            (
                *CONTROL_COLUMNS,
                "candidate_count",
                "vacancies_before_selection",
                *component_years,
            ),
        )
        for endpoint in PRIMARY_ENDPOINTS
    }
    exit_dummies = pd.get_dummies(
        frame.canonical_exit_reason.astype(str),
        prefix="exit",
        drop_first=True,
        dtype=float,
    )
    duration_frame = pd.concat(
        [frame.reset_index(drop=True), exit_dummies.reset_index(drop=True)], axis=1
    )
    duration_frame, duration_years = stats.add_year_dummies(duration_frame)
    attacks["holding_duration_exit_control"] = {
        endpoint: stats.partial_rank(
            duration_frame,
            PREDICTOR,
            endpoint,
            (
                *CONTROL_COLUMNS,
                "holding_trading_days",
                *tuple(exit_dummies.columns),
                *duration_years,
            ),
        )
        for endpoint in PRIMARY_ENDPOINTS
    }
    attacks["security_leave_one_out"] = {
        endpoint: stats.leave_group_out(frame, "symbol", PREDICTOR, endpoint)
        for endpoint in PRIMARY_ENDPOINTS
    }
    attacks["industry_leave_one_out"] = {
        endpoint: stats.leave_group_out(
            frame, "entry_industry", PREDICTOR, endpoint
        )
        for endpoint in PRIMARY_ENDPOINTS
    }

    gates_spec = spec["decision_gates"]
    raw_gate = all(
        primary[endpoint]["raw"]["rho"] >= gates_spec["raw_minimum_rho"]
        and primary[endpoint]["raw_loyo"]["positive"]
        >= gates_spec["raw_minimum_positive_loyo"]
        and primary[endpoint]["raw_bh_qvalue"] <= gates_spec["maximum_bh_qvalue"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    controlled_gate = all(
        primary[endpoint]["controlled"]["partial_rank_rho"]
        >= gates_spec["controlled_minimum_rho"]
        and primary[endpoint]["controlled_loyo"]["positive"]
        >= gates_spec["controlled_minimum_positive_loyo"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    temporal_gate = all(
        sum(packet["rho"] > 0 for packet in primary[endpoint]["blocks"].values())
        >= gates_spec["minimum_positive_blocks"]
        and min(packet["rho"] for packet in primary[endpoint]["blocks"].values())
        > gates_spec["minimum_block_rho_exclusive"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    sample_gate = all(
        attacks[name][endpoint]["rho"] > gates_spec["attack_minimum_rho_exclusive"]
        for name in attack_samples
        for endpoint in PRIMARY_ENDPOINTS
    )
    component_gate = all(
        attacks["candidate_vacancy_components"][endpoint]["partial_rank_rho"]
        > gates_spec["attack_minimum_rho_exclusive"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    duration_gate = all(
        attacks["holding_duration_exit_control"][endpoint]["partial_rank_rho"]
        > gates_spec["attack_minimum_rho_exclusive"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    concentration_gate = all(
        attacks[group][endpoint]["positive_fraction"]
        >= gates_spec["minimum_leave_group_positive_fraction"]
        and attacks[group][endpoint]["minimum"]
        > gates_spec["leave_group_minimum_rho_exclusive"]
        for group in ("security_leave_one_out", "industry_leave_one_out")
        for endpoint in PRIMARY_ENDPOINTS
    )
    falsification_gate = sample_gate and component_gate and duration_gate and concentration_gate
    gates = {
        "raw_both_endpoints": raw_gate,
        "controlled_both_endpoints": controlled_gate,
        "all_three_blocks_both_endpoints": temporal_gate,
        "falsification": falsification_gate,
    }
    endpoint_support = {
        endpoint: (
            primary[endpoint]["raw"]["rho"] >= gates_spec["raw_minimum_rho"]
            and primary[endpoint]["controlled"]["partial_rank_rho"]
            >= gates_spec["controlled_minimum_rho"]
        )
        for endpoint in PRIMARY_ENDPOINTS
    }
    if all(gates.values()):
        decision = "VALIDATE"
        verdict = "SELECTION_PRESSURE_SURVIVES_STRICT_FOLLOWUP_GATES"
    elif any(endpoint_support.values()):
        decision = "REFINE"
        verdict = "SELECTION_PRESSURE_FAILS_TEMPORAL_OR_FALSIFICATION_GATE"
    else:
        decision = "REJECTED"
        verdict = "SELECTION_PRESSURE_FAILS_PRIMARY_MAGNITUDE_GATES"
    complete = (
        frame[[PREDICTOR, *PRIMARY_ENDPOINTS, *CONTROL_COLUMNS]]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    if len(complete) < spec["population"]["controlled_minimum_complete_rows"]:
        raise PressureRevealError("controlled complete-case population shrank")
    return {
        "experiment_id": "EXP-OBL-011",
        "hypothesis_id": "H-OBL-009",
        "lineage_freeze_id": "LINEAGE-OBL-009-2BECCEFAF46C1140",
        "evidence_grade": "POST_SECONDARY_EXPLORATORY_REVEAL_BOUNDED_PIT_B",
        "multiple_testing_qualification": (
            "Primary predictor was observed as a preregistered non-rescuing secondary "
            "in EXP-OBL-010; this follow-up is not independent confirmation."
        ),
        "population": {"events": len(frame), "controlled_complete": len(complete)},
        "primary": primary,
        "attacks": attacks,
        "gates": gates,
        "endpoint_support": endpoint_support,
        "decision": decision,
        "verdict": verdict,
        "interpretation_boundary": (
            "Selection pressure was frozen before outcomes, but selected for this test "
            "after secondary inspection. No threshold, rule, strategy change, or CY-011 "
            "access is authorized."
        ),
    }


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# EXP-OBL-011 continuous selection-pressure follow-up",
        "",
        f"Decision: `{result['decision']}`.",
        "",
        f"Verdict: `{result['verdict']}`.",
        "",
        "| Endpoint | Raw rho | Raw LOYO + | Controlled rho | Controlled LOYO + | BH q |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for endpoint in PRIMARY_ENDPOINTS:
        packet = result["primary"][endpoint]
        lines.append(
            f"| {endpoint} | {packet['raw']['rho']:.6f} | "
            f"{packet['raw_loyo']['positive']}/{packet['raw_loyo']['total']} | "
            f"{packet['controlled']['partial_rank_rho']:.6f} | "
            f"{packet['controlled_loyo']['positive']}/{packet['controlled_loyo']['total']} | "
            f"{packet['raw_bh_qvalue']:.6g} |"
        )
    lines.extend(["", f"Gates: `{json.dumps(result['gates'], sort_keys=True)}`.", "", result["multiple_testing_qualification"], "", result["interpretation_boundary"]])
    return "\n".join(lines) + "\n"


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    frame, _ = selection.load_analysis_frame(spec)
    result = analyze(frame, spec)
    result["input_identities"] = identities
    output_columns = [
        "trade_id", "baseline_block", "symbol", "entry_signal_date",
        "entry_execution_date", "entry_year", "selection_lineage_id",
        "contested_selection", "candidate_count", "vacancies_before_selection",
        PREDICTOR, "selected_rank_percentile", "selected_rs_score", "mfe", "mae",
        "false_breakout", "non_false_breakout", "round_trip_return", "realized_pnl",
        "extreme_winner", "severe_loss", "holding_trading_days",
        "canonical_exit_reason", "entry_industry", *selection.CONTROL_COLUMNS,
    ]
    stats.atomic_csv(OUTPUT_TABLE, frame[output_columns].sort_values("trade_id"))
    result["output_table_sha256"] = stats.sha256_file(OUTPUT_TABLE)
    stats.atomic_write(OUTPUT_JSON, json.dumps(stats.clean_json(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    stats.atomic_write(REPORT, render_report(result))
    stats.atomic_write(
        EVIDENCE_PACKET,
        "# EXP-OBL-011 evidence packet\n\n"
        f"- Decision: `{result['decision']}`\n"
        f"- Verdict: `{result['verdict']}`\n"
        f"- Gates: `{json.dumps(result['gates'], sort_keys=True)}`\n\n"
        "This is a post-secondary exploratory follow-up, not independent confirmation. "
        "No strategy modification is authorized.\n",
    )
    print(json.dumps(stats.clean_json(result), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
