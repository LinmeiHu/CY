#!/usr/bin/env python3
"""Clean EXP-IBQ-002 execution of the frozen H-021 scientific contract."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_intraday_signal_day_quality as base  # noqa: E402

SPEC = WORK / "experiments/EXP-IBQ-002_spec.json"
OUTPUT_TABLE = WORK / "artifacts/intraday_signal_day_quality_v2.csv"
OUTPUT_JSON = WORK / "artifacts/intraday_signal_day_quality_v2.json"
REPORT = WORK / "reports/intraday_signal_day_quality_v2.md"
EVIDENCE_PACKET = WORK / "reports/intraday_signal_day_quality_v2_evidence_packet.md"


def validate_spec_and_bound_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-IBQ-002":
        raise base.IntradayQualityError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_INTRADAY_OUTCOME_JOIN":
        raise base.IntradayQualityError("experiment is not frozen before outcome join")
    if spec.get("hypothesis_id") != "H-021":
        raise base.IntradayQualityError("unexpected hypothesis identity")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = base.resolve_path(binding["path"])
        if not path.is_file():
            raise base.IntradayQualityError(f"missing bound input: {role}: {path}")
        actual = base.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise base.IntradayQualityError(f"frozen input mismatch: {mismatches}")
    return spec, identities


def analyze(features: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    mechanisms = pd.read_csv(
        base.MECHANISMS,
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
        base.CONTROLS,
        usecols=["trade_id", "entry_industry", *base.CONTROL_COLUMNS[4:]],
    )
    if len(mechanisms) != 399 or mechanisms.trade_id.nunique() != 399:
        raise base.IntradayQualityError("mechanism input is not 399 unique cycles")
    if len(controls) != 399 or controls.trade_id.nunique() != 399:
        raise base.IntradayQualityError("control input is not 399 unique cycles")
    frame = features.merge(mechanisms, on="trade_id", validate="one_to_one")
    frame = frame.merge(controls, on="trade_id", validate="one_to_one")
    for column in ("opportunity20", "false_breakout", "severe_loss"):
        frame[column] = frame[column].astype(bool)
    if int(frame.opportunity20.sum()) != 84 or int(frame.false_breakout.sum()) != 213:
        raise base.IntradayQualityError("fixed outcome counts changed")
    if (frame.opportunity20 & frame.false_breakout).any():
        raise base.IntradayQualityError("success and false-breakout endpoints overlap")
    frame["breakout_success"] = np.where(
        frame.opportunity20,
        1.0,
        np.where(frame.false_breakout, 0.0, np.nan),
    )
    frame["non_false_breakout"] = (~frame.false_breakout).astype(float)
    primary = frame[frame.breakout_success.notna()].copy()
    if len(primary) != 297:
        raise base.IntradayQualityError("fixed success-versus-false population changed")

    primary_year, year_columns = base.add_year_dummies(primary)
    fixed_controls = (*base.CONTROL_COLUMNS, *year_columns)
    raw = base.spearman(primary, "signal_day_path_acceptance", "breakout_success")
    controlled = base.partial_rank(
        primary_year,
        "signal_day_path_acceptance",
        "breakout_success",
        fixed_controls,
    )
    raw_loyo = base.loyo(primary, "signal_day_path_acceptance", "breakout_success")
    controlled_loyo = base.loyo(
        primary,
        "signal_day_path_acceptance",
        "breakout_success",
        base.CONTROL_COLUMNS,
    )
    within_year = base.spearman(
        primary.assign(
            x=primary.groupby("entry_year").signal_day_path_acceptance.rank(pct=True),
            y=primary.groupby("entry_year").breakout_success.rank(pct=True),
        ),
        "x",
        "y",
    )
    blocks = {
        block: base.spearman(sample, "signal_day_path_acceptance", "breakout_success")
        for block, sample in primary.groupby("baseline_block", sort=True)
    }
    components = {
        component: {
            "rho": base.spearman(primary, component, "breakout_success"),
            "loyo": base.loyo(primary, component, "breakout_success"),
        }
        for component in base.FEATURE_COMPONENTS
    }
    neighbors = {
        name: {
            "rho": base.spearman(primary, name, "breakout_success"),
            "loyo": base.loyo(primary, name, "breakout_success"),
        }
        for name in (
            "signal_day_path_acceptance_5m",
            "signal_day_path_acceptance_auction",
        )
    }
    secondary = {
        endpoint: {
            "rho": base.spearman(frame, "signal_day_path_acceptance", endpoint),
            "loyo": base.loyo(frame, "signal_day_path_acceptance", endpoint),
        }
        for endpoint in (
            "opportunity20",
            "non_false_breakout",
            "mfe",
            "round_trip_return",
        )
    }
    top4 = set(frame.assign(abs_pnl=frame.realized_pnl.abs()).nlargest(4, "abs_pnl").trade_id)
    attacks = {
        "ex_top4_absolute_pnl": base.spearman(
            primary[~primary.trade_id.isin(top4)],
            "signal_day_path_acceptance",
            "breakout_success",
        ),
        "ex_extreme_winners": base.spearman(
            primary[primary.round_trip_return < 0.50],
            "signal_day_path_acceptance",
            "breakout_success",
        ),
        "ex_severe_losses": base.spearman(
            primary[~primary.severe_loss],
            "signal_day_path_acceptance",
            "breakout_success",
        ),
        "security_leave_one_out": base.leave_group_out(
            primary, "symbol", "signal_day_path_acceptance", "breakout_success"
        ),
        "industry_leave_one_out": base.leave_group_out(
            primary, "entry_industry", "signal_day_path_acceptance", "breakout_success"
        ),
    }
    gates_spec = spec["decision_gates"]
    raw_gate = (
        raw >= gates_spec["raw_minimum_rho"]
        and raw_loyo["positive"] >= gates_spec["raw_minimum_positive_loyo"]
    )
    controlled_gate = (
        controlled >= gates_spec["controlled_minimum_rho"]
        and controlled_loyo["positive"] >= gates_spec["controlled_minimum_positive_loyo"]
    )
    temporal_gate = (
        sum(value > 0 for value in blocks.values()) >= gates_spec["minimum_positive_blocks"]
        and min(blocks.values()) > gates_spec["minimum_block_rho_exclusive"]
    )
    outcome_gate = all(
        secondary[name]["rho"] >= gates_spec["secondary_minimum_rho"]
        and secondary[name]["loyo"]["positive"]
        >= gates_spec["secondary_minimum_positive_loyo"]
        for name in ("opportunity20", "non_false_breakout")
    )
    neighbor_gate = all(
        item["rho"] >= gates_spec["neighbor_minimum_rho"]
        and item["loyo"]["positive"] >= gates_spec["neighbor_minimum_positive_loyo"]
        for item in neighbors.values()
    )
    tail_gate = all(
        attacks[name] > gates_spec["tail_minimum_rho_exclusive"]
        for name in ("ex_top4_absolute_pnl", "ex_extreme_winners", "ex_severe_losses")
    )
    concentration_gate = all(
        attacks[name]["positive_fraction"]
        >= gates_spec["minimum_leave_group_positive_fraction"]
        and attacks[name]["minimum"] > 0
        for name in ("security_leave_one_out", "industry_leave_one_out")
    )
    falsification_gate = neighbor_gate and tail_gate and concentration_gate
    gates = {
        "raw": raw_gate,
        "controlled_daily_incrementality": controlled_gate,
        "temporal": temporal_gate,
        "outcome_neighbors": outcome_gate,
        "falsification": falsification_gate,
    }
    if all(gates.values()):
        decision = "VALIDATE"
        verdict = "SIGNAL_DAY_PATH_ACCEPTANCE_SURVIVES_EXPLORATORY_FALSIFICATION"
    elif raw_gate and controlled_gate:
        decision = "SUPPORTED_WEAK"
        verdict = "SIGNAL_DAY_PATH_ACCEPTANCE_IS_PRESENT_BUT_NOT_FULLY_ROBUST"
    else:
        decision = "REJECTED"
        verdict = "SIGNAL_DAY_PATH_ACCEPTANCE_FAILS_RAW_OR_DAILY_INCREMENTAL_GATES"

    ordered_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "feature_available_at",
        "potential_action_timestamp",
        "minute_snapshot_id",
        "daily_snapshot_id",
        *base.FEATURE_COMPONENTS,
        "path_efficiency_5m",
        "path_efficiency_auction_inclusive",
        "signal_day_path_acceptance",
        "signal_day_path_acceptance_5m",
        "signal_day_path_acceptance_auction",
        *base.CONTROL_COLUMNS[:4],
        "continuous_session_vwap",
        "flat_signal_session",
        "opportunity20",
        "false_breakout",
        "breakout_success",
        "non_false_breakout",
        "mfe",
        "round_trip_return",
        "realized_pnl",
        "severe_loss",
        "entry_year",
        "entry_industry",
        *base.CONTROL_COLUMNS[4:],
    ]
    complete_controls = int(
        primary[["signal_day_path_acceptance", "breakout_success", *base.CONTROL_COLUMNS]]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .shape[0]
    )
    result = {
        "experiment_id": "EXP-IBQ-002",
        "hypothesis_id": "H-021",
        "evidence_grade": "EXPLORATORY_MECHANISM_EVIDENCE_ON_OUTCOME_CONSUMED_HISTORY",
        "population": {
            "all_completed_cycles": len(frame),
            "success_opportunity20": int(frame.opportunity20.sum()),
            "false_breakout": int(frame.false_breakout.sum()),
            "primary_disjoint_population": len(primary),
            "primary_fixed_control_complete": complete_controls,
        },
        "primary": {
            "raw_rho": raw,
            "within_year_rho": within_year,
            "raw_loyo": raw_loyo,
            "controlled_rho": controlled,
            "controlled_loyo": controlled_loyo,
            "blocks": blocks,
        },
        "components": components,
        "neighbors": neighbors,
        "secondary": secondary,
        "attacks": attacks,
        "gates": gates,
        "decision": decision,
        "verdict": verdict,
        "interpretation_boundary": (
            "Features are complete entry-signal-session observations available at 15:30 "
            "for T+1 or later. They cannot justify an earlier same-session action and do "
            "not identify the original lifecycle breakout timestamp."
        ),
    }
    return frame[ordered_columns].sort_values("trade_id").reset_index(drop=True), result


def main() -> None:
    spec, bound_identities = validate_spec_and_bound_inputs()
    years = list(range(2018, 2026))
    qd004_required = [f"bars/{year}_day_parquet_none.parquet" for year in years]
    cy008_required = [
        path
        for year in years
        for path in (
            f"daily/partition_year={year}/data_0.parquet",
            f"execution_5m/partition_year={year}/data_0.parquet",
        )
    ]
    qd004 = base.inventory_files(base.QD004_INVENTORY, qd004_required)
    cy008 = base.inventory_files(base.CY008_INVENTORY, cy008_required)
    cross_audit = json.loads(base.CY008_AUDIT.read_text(encoding="utf-8"))
    if cross_audit.get("pass") is not True or not all(cross_audit.get("checks", {}).values()):
        raise base.IntradayQualityError("CY-008 cross-year audit is not PASS")
    identities = base.load_identity_frame()
    features, audit = base.construct_feature_frame(identities, qd004, cy008)
    table, result = analyze(features, spec)
    result["audit"] = audit
    result["input_identities"] = bound_identities

    OUTPUT_TABLE.parent.mkdir(parents=True, exist_ok=True)
    temporary_table = OUTPUT_TABLE.with_suffix(".tmp.csv")
    table.to_csv(temporary_table, index=False, float_format="%.12g")
    temporary_table.replace(OUTPUT_TABLE)
    base.atomic_write(
        OUTPUT_JSON,
        json.dumps(base.clean_json(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    report = base.render_report(result, audit).replace("EXP-IBQ-001", "EXP-IBQ-002")
    packet = base.render_evidence_packet(result, audit).replace("EXP-IBQ-001", "EXP-IBQ-002")
    base.atomic_write(REPORT, report)
    base.atomic_write(EVIDENCE_PACKET, packet)
    print(json.dumps(base.clean_json(result), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
