#!/usr/bin/env python3
"""Execute EXP-OBL-007 for exact canonical-reference age."""

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

SPEC = WORK / "experiments/EXP-OBL-007_spec.json"
FEATURES = WORK / "artifacts/formation_features_v3.csv"
OUTCOMES = REGIME / "artifacts/trade_mechanism_attribution.csv"
CONTROLS = REGIME / "artifacts/pre_entry_transitions.csv"
TRADES = REGIME / "artifacts/yearly_trades.csv"

OUTPUT_TABLE = WORK / "artifacts/reference_age_outcome_reveal.csv"
OUTPUT_JSON = WORK / "artifacts/EXP-OBL-007_result.json"
REPORT = WORK / "reports/EXP-OBL-007_reference_age_outcome_reveal.md"
EVIDENCE_PACKET = WORK / "reports/EXP-OBL-007_evidence_packet.md"

PREDICTOR = "sessions_since_reference"
PRIMARY_ENDPOINTS = base.PRIMARY_ENDPOINTS
FORMATION_CONTROLS = ("prebreakout_distance", "breakout_margin")
CONTROL_COLUMNS = (*base.CONTROL_COLUMNS, *FORMATION_CONTROLS)


class ReferenceAgeRevealError(RuntimeError):
    """Raised when a frozen binding, join, population, or decision contract fails."""


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-007":
        raise ReferenceAgeRevealError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_OUTCOME_JOIN":
        raise ReferenceAgeRevealError("outcome reveal is not frozen")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise ReferenceAgeRevealError(f"missing bound input: {role}: {path}")
        actual = base.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise ReferenceAgeRevealError(f"frozen input mismatch: {mismatches}")
    return spec, identities


def load_analysis_frame(spec: dict[str, Any]) -> pd.DataFrame:
    features = pd.read_csv(
        FEATURES,
        usecols=[
            "trade_id",
            "baseline_block",
            "symbol",
            "entry_signal_date",
            "entry_execution_date",
            "entry_year",
            PREDICTOR,
            *FORMATION_CONTROLS,
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
        usecols=["trade_id", "entry_industry", *base.CONTROL_COLUMNS],
    )
    trades = pd.read_csv(
        TRADES,
        usecols=[
            "trade_id",
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
            raise ReferenceAgeRevealError(f"{name} input is not 399 unique cycles")
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
        raise ReferenceAgeRevealError(f"frozen outcome counts changed: {actual}")
    if not np.isfinite(
        frame[
            [
                PREDICTOR,
                *FORMATION_CONTROLS,
                "mfe",
                "round_trip_return",
                "realized_pnl",
                "mae",
            ]
        ].to_numpy(float)
    ).all():
        raise ReferenceAgeRevealError("nonfinite required feature or outcome")
    if not frame[PREDICTOR].between(0, 59).all():
        raise ReferenceAgeRevealError("reference age is outside the canonical window")
    if frame[PREDICTOR].nunique() != 60:
        raise ReferenceAgeRevealError("frozen reference-age support changed")
    if not (frame.mfe >= 0).all() or not (frame.mae <= 0).all():
        raise ReferenceAgeRevealError("MFE/MAE sign convention changed")
    frame["entry_year"] = frame.entry_year.astype(int)
    return frame


def endpoint_packet(frame: pd.DataFrame, endpoint: str) -> dict[str, Any]:
    return base.endpoint_packet(frame, PREDICTOR, endpoint, CONTROL_COLUMNS)


def right_tail_summary(frame: pd.DataFrame) -> dict[str, Any]:
    positive_total = float(frame.loc[frame.realized_pnl > 0, "realized_pnl"].sum())
    packet: dict[str, Any] = {}
    for fraction, count in (("top_1pct", 4), ("top_5pct", 20), ("top_10pct", 40)):
        sample = frame.nlargest(count, "round_trip_return")
        positive = float(sample.loc[sample.realized_pnl > 0, "realized_pnl"].sum())
        packet[fraction] = {
            "n": len(sample),
            "mean_reference_age": float(sample[PREDICTOR].mean()),
            "median_reference_age": float(sample[PREDICTOR].median()),
            "positive_pnl_share": None if positive_total <= 0 else positive / positive_total,
        }
    return packet


def analyze(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    primary = {endpoint: endpoint_packet(frame, endpoint) for endpoint in PRIMARY_ENDPOINTS}
    qvalues = base.benjamini_hochberg(
        {endpoint: primary[endpoint]["raw"]["pvalue"] for endpoint in PRIMARY_ENDPOINTS}
    )
    for endpoint in PRIMARY_ENDPOINTS:
        primary[endpoint]["raw_bh_qvalue"] = qvalues[endpoint]

    secondary = {
        endpoint: base.association(frame, PREDICTOR, endpoint)
        for endpoint in (
            "opportunity20",
            "round_trip_return",
            "extreme_winner",
            "severe_loss",
            "mae",
        )
    }
    top4 = set(
        frame.assign(abs_pnl=frame.realized_pnl.abs()).nlargest(4, "abs_pnl").trade_id
    )
    attack_samples = {
        "ex_top1pct_absolute_pnl": frame[~frame.trade_id.isin(top4)],
        "ex_extreme_winners": frame[~frame.extreme_winner],
        "ex_severe_losses": frame[~frame.severe_loss],
        "ex_reference_age_zero": frame[frame[PREDICTOR] != 0],
        "ex_reference_age_window_boundary": frame[frame[PREDICTOR] != 59],
    }
    attacks: dict[str, Any] = {
        name: {
            endpoint: base.association(sample, PREDICTOR, endpoint)
            for endpoint in PRIMARY_ENDPOINTS
        }
        for name, sample in attack_samples.items()
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
    duration_frame, year_columns = base.add_year_dummies(duration_frame)
    attacks["holding_duration_exit_control"] = {
        endpoint: base.partial_rank(
            duration_frame,
            PREDICTOR,
            endpoint,
            (
                *CONTROL_COLUMNS,
                "holding_trading_days",
                *tuple(exit_dummies.columns),
                *year_columns,
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
    falsification_gate = sample_attack_gate and duration_gate and concentration_gate
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
        verdict = "REFERENCE_AGE_SURVIVES_ALL_EXPLORATORY_GATES"
    elif raw_gate and controlled_gate and temporal_gate:
        decision = "SUPPORTED_WEAK"
        verdict = "REFERENCE_AGE_PRESENT_BUT_FAILS_FALSIFICATION"
    elif any(endpoint_support.values()):
        decision = "REFINE"
        verdict = "REFERENCE_AGE_MECHANISM_IS_ENDPOINT_SPECIFIC"
    else:
        decision = "REJECTED"
        verdict = "REFERENCE_AGE_FAILS_PRIMARY_RAW_OR_CONTROLLED_GATES"
    complete = (
        frame[[PREDICTOR, *PRIMARY_ENDPOINTS, *CONTROL_COLUMNS]]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    if len(complete) < spec["population"]["controlled_minimum_complete_rows"]:
        raise ReferenceAgeRevealError("controlled complete-case population shrank")
    return {
        "experiment_id": "EXP-OBL-007",
        "hypothesis_id": "H-OBL-006",
        "evidence_grade": "EXPLORATORY_REVEAL_ON_HISTORICALLY_CONSUMED_BOUNDED_PIT_B",
        "predictor": PREDICTOR,
        "population": {
            "events": len(frame),
            "controlled_complete": len(complete),
            "reference_age_unique": int(frame[PREDICTOR].nunique()),
            "reference_age_minimum": int(frame[PREDICTOR].min()),
            "reference_age_maximum": int(frame[PREDICTOR].max()),
        },
        "primary": primary,
        "secondary_not_decision_rescuing": secondary,
        "right_tail_not_decision_rescuing": right_tail_summary(frame),
        "attacks": attacks,
        "gates": gates,
        "endpoint_support": endpoint_support,
        "decision": decision,
        "verdict": verdict,
        "interpretation_boundary": (
            "Reference age and all formation controls existed by the completed signal "
            "session. This mechanism reveal authorizes no bin, threshold, entry, exit, "
            "size, overlay, production change, or CY-011 access."
        ),
    }


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# EXP-OBL-007 canonical-reference-age outcome reveal",
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
        "# EXP-OBL-007 evidence packet\n\n"
        f"- Population: `{result['population']['events']}` events; "
        f"`{result['population']['controlled_complete']}` complete controlled rows\n"
        f"- Reference-age support: `{result['population']['reference_age_minimum']}`"
        f"..`{result['population']['reference_age_maximum']}`\n"
        f"- Decision: `{result['decision']}`\n"
        f"- Verdict: `{result['verdict']}`\n"
        f"- Gates: `{json.dumps(result['gates'], sort_keys=True)}`\n\n"
        "Right-tail and terminal-return evidence cannot rescue a failed co-primary gate. "
        "No strategy modification or CY-011 access is authorized.\n"
    )


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    frame = load_analysis_frame(spec)
    result = analyze(frame, spec)
    result["input_identities"] = identities
    output_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        PREDICTOR,
        *FORMATION_CONTROLS,
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
        *base.CONTROL_COLUMNS,
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
