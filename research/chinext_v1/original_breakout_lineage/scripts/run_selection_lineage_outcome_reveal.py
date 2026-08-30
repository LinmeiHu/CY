#!/usr/bin/env python3
"""Execute EXP-OBL-010 against the frozen selection lineage."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
REGIME = ROOT / "research/chinext_v1/regime_attribution"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_lineage_outcome_reveal as base  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-010_spec.json"
FEATURES = WORK / "artifacts/selection_competition_features_v2.csv"
FREEZE = WORK / "lineage_freezes/LINEAGE-OBL-009.json"
OUTCOMES = REGIME / "artifacts/trade_mechanism_attribution.csv"
CONTROLS = REGIME / "artifacts/pre_entry_transitions.csv"
TRADES = REGIME / "artifacts/yearly_trades.csv"

OUTPUT_TABLE = WORK / "artifacts/selection_lineage_outcome_reveal.csv"
OUTPUT_JSON = WORK / "artifacts/EXP-OBL-010_result.json"
REPORT = WORK / "reports/EXP-OBL-010_selection_lineage_outcome_reveal.md"
EVIDENCE_PACKET = WORK / "reports/EXP-OBL-010_evidence_packet.md"

PREDICTOR = "contested_selection"
PRIMARY_ENDPOINTS = base.PRIMARY_ENDPOINTS
CONTROL_COLUMNS = base.CONTROL_COLUMNS
CONTEXT_CONTROLS = (
    *CONTROL_COLUMNS,
    "candidate_count",
    "vacancies_before_selection",
    "selected_rank_percentile",
)


class SelectionRevealError(RuntimeError):
    """Raised when the freeze, join, population, or decision contract fails."""


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-010":
        raise SelectionRevealError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_OUTCOME_JOIN":
        raise SelectionRevealError("outcome reveal is not frozen")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise SelectionRevealError(f"missing bound input: {role}: {path}")
        actual = base.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise SelectionRevealError(f"frozen input mismatch: {mismatches}")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze.get("lineage_freeze_id") != "LINEAGE-OBL-009-2BECCEFAF46C1140":
        raise SelectionRevealError("selection lineage freeze identity changed")
    if freeze.get("outcome_access_before_freeze") is not False:
        raise SelectionRevealError("selection freeze outcome boundary changed")
    if freeze.get("feature_table_sha256") != base.sha256_file(FEATURES):
        raise SelectionRevealError("selection features no longer match freeze")
    return spec, identities


def load_analysis_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, float]:
    features = pd.read_csv(
        FEATURES,
        usecols=[
            "trade_id",
            "baseline_block",
            "symbol",
            "entry_signal_date",
            "entry_year",
            "selection_lineage_id",
            "candidate_count",
            "vacancies_before_selection",
            "selection_pressure",
            "selected_rank",
            "selected_rank_percentile",
            "selected_rs_score",
            "selected_margin_to_cutoff",
        ],
    )
    outcomes = pd.read_csv(
        OUTCOMES,
        usecols=[
            "trade_id",
            "mfe",
            "round_trip_return",
            "realized_pnl",
            "opportunity20",
            "false_breakout",
            "severe_loss",
        ],
    )
    controls = pd.read_csv(
        CONTROLS,
        usecols=["trade_id", "entry_industry", *CONTROL_COLUMNS],
    )
    trades = pd.read_csv(
        TRADES,
        usecols=[
            "trade_id",
            "entry_execution_date",
            "mae",
            "holding_trading_days",
            "canonical_exit_reason",
        ],
    )
    for name, frame in (
        ("features", features),
        ("outcomes", outcomes),
        ("controls", controls),
        ("trades", trades),
    ):
        if len(frame) != 399 or frame.trade_id.nunique() != 399:
            raise SelectionRevealError(f"{name} input is not 399 unique cycles")
    if features.selection_lineage_id.value_counts().to_dict() != {
        "L_UNCONTESTED": 351,
        "L_CONTESTED": 48,
    }:
        raise SelectionRevealError("frozen selection lineage counts changed")
    features[PREDICTOR] = features.selection_lineage_id.eq("L_CONTESTED").astype(float)
    frame = features.merge(outcomes, on="trade_id", validate="one_to_one")
    frame = frame.merge(controls, on="trade_id", validate="one_to_one")
    frame = frame.merge(trades, on="trade_id", validate="one_to_one")
    for column in ("opportunity20", "false_breakout", "severe_loss"):
        frame[column] = frame[column].astype(bool)
    frame["non_false_breakout"] = (~frame.false_breakout).astype(float)
    frame["extreme_winner"] = frame.round_trip_return >= 0.50
    expected = spec["population"]["expected_outcome_counts"]
    actual = {name: int(frame[name].sum()) for name in expected}
    if actual != expected:
        raise SelectionRevealError(f"frozen outcome counts changed: {actual}")
    rs_difference = np.abs(frame.selected_rs_score - frame.entry_rs_score)
    maximum_rs_difference = float(rs_difference.max())
    if maximum_rs_difference > 1e-12:
        raise SelectionRevealError(
            f"selection-event RS differs from accepted entry RS: {maximum_rs_difference}"
        )
    if not np.isfinite(
        frame[
            [
                PREDICTOR,
                "candidate_count",
                "vacancies_before_selection",
                "selection_pressure",
                "selected_rank_percentile",
                "mfe",
                "mae",
                "round_trip_return",
                "realized_pnl",
            ]
        ].to_numpy(float)
    ).all():
        raise SelectionRevealError("nonfinite required feature or outcome")
    if not (frame.mfe >= 0).all() or not (frame.mae <= 0).all():
        raise SelectionRevealError("MFE/MAE sign convention changed")
    frame["entry_year"] = frame.entry_year.astype(int)
    return frame, maximum_rs_difference


def endpoint_packet(frame: pd.DataFrame, endpoint: str) -> dict[str, Any]:
    return base.endpoint_packet(frame, PREDICTOR, endpoint, CONTROL_COLUMNS)


def analyze(
    frame: pd.DataFrame,
    spec: dict[str, Any],
    maximum_rs_difference: float,
) -> dict[str, Any]:
    primary = {endpoint: endpoint_packet(frame, endpoint) for endpoint in PRIMARY_ENDPOINTS}
    qvalues = base.benjamini_hochberg(
        {endpoint: primary[endpoint]["raw"]["pvalue"] for endpoint in PRIMARY_ENDPOINTS}
    )
    for endpoint in PRIMARY_ENDPOINTS:
        primary[endpoint]["raw_bh_qvalue"] = qvalues[endpoint]

    secondary = {
        feature: {
            endpoint: base.association(frame, feature, endpoint)
            for endpoint in (*PRIMARY_ENDPOINTS, "round_trip_return", "extreme_winner")
        }
        for feature in (
            "selection_pressure",
            "selected_rank_percentile",
            "selected_margin_to_cutoff",
        )
    }
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
            endpoint: base.association(sample, PREDICTOR, endpoint)
            for endpoint in PRIMARY_ENDPOINTS
        }
        for name, sample in attack_samples.items()
    }
    context_frame, year_columns = base.add_year_dummies(frame)
    attacks["candidate_vacancy_rank_control"] = {
        endpoint: base.partial_rank(
            context_frame,
            PREDICTOR,
            endpoint,
            (*CONTEXT_CONTROLS, *year_columns),
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
    duration_frame, duration_year_columns = base.add_year_dummies(duration_frame)
    attacks["holding_duration_exit_control"] = {
        endpoint: base.partial_rank(
            duration_frame,
            PREDICTOR,
            endpoint,
            (
                *CONTROL_COLUMNS,
                "holding_trading_days",
                *tuple(exit_dummies.columns),
                *duration_year_columns,
            ),
        )
        for endpoint in PRIMARY_ENDPOINTS
    }
    attacks["security_leave_one_out"] = {
        endpoint: base.leave_group_out(frame, "symbol", PREDICTOR, endpoint)
        for endpoint in PRIMARY_ENDPOINTS
    }
    attacks["industry_leave_one_out"] = {
        endpoint: base.leave_group_out(
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
    sample_attack_gate = all(
        attacks[name][endpoint]["rho"] > gates_spec["attack_minimum_rho_exclusive"]
        for name in attack_samples
        for endpoint in PRIMARY_ENDPOINTS
    )
    context_gate = all(
        attacks["candidate_vacancy_rank_control"][endpoint]["partial_rank_rho"]
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
    falsification_gate = (
        sample_attack_gate and context_gate and duration_gate and concentration_gate
    )
    gates = {
        "raw_both_endpoints": raw_gate,
        "controlled_both_endpoints": controlled_gate,
        "temporal_both_endpoints": temporal_gate,
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
        verdict = "CONTESTED_SELECTION_SURVIVES_ALL_EXPLORATORY_GATES"
    elif raw_gate and controlled_gate and temporal_gate:
        decision = "SUPPORTED_WEAK"
        verdict = "CONTESTED_SELECTION_PRESENT_BUT_FAILS_FALSIFICATION"
    elif any(endpoint_support.values()):
        decision = "REFINE"
        verdict = "CONTESTED_SELECTION_MECHANISM_IS_ENDPOINT_SPECIFIC"
    else:
        decision = "REJECTED"
        verdict = "CONTESTED_SELECTION_FAILS_PRIMARY_RAW_OR_CONTROLLED_GATES"
    complete = (
        frame[[PREDICTOR, *PRIMARY_ENDPOINTS, *CONTROL_COLUMNS]]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    if len(complete) < spec["population"]["controlled_minimum_complete_rows"]:
        raise SelectionRevealError("controlled complete-case population shrank")
    lineage_summary = (
        frame.groupby("selection_lineage_id", sort=True)
        .agg(
            n=("trade_id", "size"),
            mean_mfe=("mfe", "mean"),
            median_mfe=("mfe", "median"),
            non_false_rate=("non_false_breakout", "mean"),
            mean_terminal_return=("round_trip_return", "mean"),
            extreme_winner_rate=("extreme_winner", "mean"),
            severe_loss_rate=("severe_loss", "mean"),
        )
        .reset_index()
        .to_dict(orient="records")
    )
    return {
        "experiment_id": "EXP-OBL-010",
        "hypothesis_id": "H-OBL-008",
        "lineage_freeze_id": "LINEAGE-OBL-009-2BECCEFAF46C1140",
        "evidence_grade": "EXPLORATORY_REVEAL_ON_HISTORICALLY_CONSUMED_BOUNDED_PIT_B",
        "population": {
            "events": len(frame),
            "controlled_complete": len(complete),
            "contested": int(frame[PREDICTOR].sum()),
            "uncontested": int((1 - frame[PREDICTOR]).sum()),
        },
        "maximum_selection_rs_reconciliation_difference": maximum_rs_difference,
        "primary": primary,
        "lineage_summary": lineage_summary,
        "secondary_not_decision_rescuing": secondary,
        "attacks": attacks,
        "gates": gates,
        "endpoint_support": endpoint_support,
        "decision": decision,
        "verdict": verdict,
        "interpretation_boundary": (
            "Selection lineage was frozen without outcomes and is available at signal "
            "close for T+1 or later only. This reveal authorizes no entry, exit, size, "
            "overlay, production change, or CY-011 access."
        ),
    }


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# EXP-OBL-010 contested-selection outcome reveal",
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
    lines.extend(
        [
            "",
            f"Gates: `{json.dumps(result['gates'], sort_keys=True)}`.",
            "",
            result["interpretation_boundary"],
        ]
    )
    return "\n".join(lines) + "\n"


def render_evidence_packet(result: dict[str, Any]) -> str:
    return (
        "# EXP-OBL-010 evidence packet\n\n"
        f"- Freeze: `{result['lineage_freeze_id']}`\n"
        f"- Population: `{result['population']['events']}` events; "
        f"`{result['population']['contested']}` contested\n"
        f"- Decision: `{result['decision']}`\n"
        f"- Verdict: `{result['verdict']}`\n"
        f"- Gates: `{json.dumps(result['gates'], sort_keys=True)}`\n\n"
        "Continuous pressure/rank, terminal return, and right-tail evidence cannot "
        "rescue failed co-primary gates. No strategy modification is authorized.\n"
    )


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    frame, maximum_rs_difference = load_analysis_frame(spec)
    result = analyze(frame, spec, maximum_rs_difference)
    result["input_identities"] = identities
    output_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "selection_lineage_id",
        PREDICTOR,
        "candidate_count",
        "vacancies_before_selection",
        "selection_pressure",
        "selected_rank",
        "selected_rank_percentile",
        "selected_rs_score",
        "selected_margin_to_cutoff",
        "mfe",
        "mae",
        "opportunity20",
        "false_breakout",
        "non_false_breakout",
        "round_trip_return",
        "realized_pnl",
        "extreme_winner",
        "severe_loss",
        "holding_trading_days",
        "canonical_exit_reason",
        "entry_industry",
        *CONTROL_COLUMNS,
    ]
    base.atomic_csv(OUTPUT_TABLE, frame[output_columns].sort_values("trade_id"))
    result["output_table_sha256"] = base.sha256_file(OUTPUT_TABLE)
    base.atomic_write(
        OUTPUT_JSON,
        json.dumps(base.clean_json(result), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
    )
    base.atomic_write(REPORT, render_report(result))
    base.atomic_write(EVIDENCE_PACKET, render_evidence_packet(result))
    print(json.dumps(base.clean_json(result), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
