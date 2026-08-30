#!/usr/bin/env python3
"""Falsify whether false-breakout excursion order is a path-boundary artifact."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_excursion_order_sequence as excursion  # noqa: E402
import run_post_entry_landmark_emergence as landmark  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-FBB-001_spec.json"
EXCURSION_TABLE = WORK / "artifacts/excursion_order_attribution.csv"
EXCURSION_RESULT = WORK / "artifacts/excursion_order_sequence.json"
TRANSITIONS = WORK / "artifacts/pre_entry_transitions.csv"
OUTPUT_TABLE = WORK / "artifacts/false_breakout_boundary_attribution.csv"
OUTPUT_JSON = WORK / "artifacts/false_breakout_boundary_falsification.json"
REPORT = WORK / "reports/false_breakout_boundary_falsification.md"


class BoundaryError(RuntimeError):
    """Raised when a frozen identity, sample, or boundary invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def boundary_flags(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    result["mfe_at_entry"] = frame.days_to_mfe.eq(0)
    result["mae_at_entry"] = frame.days_to_mae.eq(0)
    result["mfe_at_exit"] = frame.days_to_mfe.eq(frame.holding_trading_days)
    result["mae_at_exit"] = frame.days_to_mae.eq(frame.holding_trading_days)
    result["boundary_clean"] = ~result.mfe_at_entry & ~result.mae_at_exit
    result["strict_interior"] = (
        frame.days_to_mfe.gt(0)
        & frame.days_to_mfe.lt(frame.holding_trading_days)
        & frame.days_to_mae.gt(0)
        & frame.days_to_mae.lt(frame.holding_trading_days)
    )
    return result


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-FBB-001":
        raise BoundaryError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_BOUNDARY_OUTCOME_TEST":
        raise BoundaryError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatch: dict[str, Any] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise BoundaryError(f"missing bound input: {name}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatch[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatch:
        raise BoundaryError(f"frozen input mismatch: {mismatch}")
    return spec, identities


def load_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    upstream = json.loads(EXCURSION_RESULT.read_text(encoding="utf-8"))
    if (
        upstream.get("experiment_id") != "EXP-EOS-001"
        or upstream.get("decision") != "REFINE"
        or upstream.get("passing_endpoints") != ["false_breakout"]
        or upstream.get("strategy_modification") != "NONE"
    ):
        raise BoundaryError("accepted excursion-order result identity/status changed")
    frame = pd.read_csv(EXCURSION_TABLE)
    if len(frame) != 399 or frame.trade_id.nunique() != 399:
        raise BoundaryError("accepted excursion table is not 399 unique cycles")
    controls = pd.read_csv(TRANSITIONS)
    if len(controls) != 399 or controls.trade_id.nunique() != 399:
        raise BoundaryError("accepted pre-entry controls are not 399 unique cycles")
    control_columns = ["trade_id", *landmark.BASE_CONTROLS]
    frame = frame.merge(
        controls[control_columns], on="trade_id", how="left", validate="one_to_one"
    )
    if frame[list(landmark.BASE_CONTROLS)].isna().all(axis=1).any():
        raise BoundaryError("a path failed to join accepted pre-entry controls")
    flags = boundary_flags(frame)
    for column in flags.columns:
        frame[column] = flags[column].astype(bool)
    expected = spec["sample"]["expected_boundary_counts"]
    actual = {column: int(frame[column].sum()) for column in expected}
    if actual != expected:
        raise BoundaryError(f"boundary counts changed: {actual} != {expected}")
    frame["adverse_excursion_magnitude"] = -frame.mae
    frame["oriented_order"] = -frame.normalized_excursion_order
    frame["oriented_order_days"] = -frame.excursion_order_days
    frame["oriented_order_sign"] = -frame.excursion_order_sign
    clean = frame[frame.boundary_clean]
    clean_false = int(clean.false_breakout.astype(bool).sum())
    if clean_false < spec["sample"]["minimum_boundary_clean_false_breakouts"]:
        raise BoundaryError("boundary-clean false-breakout count below frozen minimum")
    audit = {
        "cycles": int(len(frame)),
        "boundary_counts": actual,
        "boundary_clean_false_breakouts": clean_false,
        "strict_interior_false_breakouts": int(
            frame.loc[frame.strict_interior, "false_breakout"].astype(bool).sum()
        ),
        "post_exit_rows_read": 0,
        "strategy_replays": 0,
        "counterfactual_paths": 0,
        "entry_or_exit_rules_tested": 0,
    }
    return frame, audit


def partial_rank(
    frame: pd.DataFrame,
    *,
    boundary_controls: bool,
) -> dict[str, Any]:
    extra = ["mfe", "adverse_excursion_magnitude", "holding_trading_days"]
    if boundary_controls:
        extra.extend(["mfe_at_entry", "mae_at_exit"])
    return landmark.partial_rank(
        frame,
        "oriented_order",
        "false_breakout",
        extra_controls=tuple(extra),
        category_controls=("entry_year", "canonical_exit_reason"),
    )


def controlled_loyo(
    frame: pd.DataFrame,
    *,
    boundary_controls: bool,
) -> dict[str, Any]:
    full = partial_rank(frame, boundary_controls=boundary_controls)
    loyo = {
        str(year): partial_rank(
            frame[frame.entry_year != year], boundary_controls=boundary_controls
        )
        for year in range(2018, 2026)
    }
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    return {**full, "loyo": loyo, "loyo_positive_count": int(positive)}


def bottom_flag(frame: pd.DataFrame, n: int) -> pd.Series:
    ordered = frame.sort_values(
        ["realized_pnl", "trade_id"], ascending=[True, True], kind="mergesort"
    )
    flag = pd.Series(False, index=frame.index)
    flag.loc[ordered.head(n).index] = True
    return flag


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    full_boundary_control = controlled_loyo(frame, boundary_controls=True)
    clean = frame[frame.boundary_clean].copy()
    clean_raw = wla.rank_association(clean, "oriented_order", "false_breakout")
    clean_controlled = controlled_loyo(clean, boundary_controls=False)
    clean_days = wla.rank_association(
        clean, "oriented_order_days", "false_breakout"
    )
    clean_sign = wla.rank_association(
        clean, "oriented_order_sign", "false_breakout"
    )
    interior = frame[frame.strict_interior].copy()
    interior_raw = wla.rank_association(
        interior, "oriented_order", "false_breakout"
    )
    bottom4 = bottom_flag(clean, 4)
    ex_bottom4 = wla.rank_association(
        clean.loc[~bottom4], "oriented_order", "false_breakout"
    )
    holding5 = wla.rank_association(
        clean[clean.holding_trading_days >= 5],
        "oriented_order",
        "false_breakout",
    )
    security = wla.omit_group_sensitivity(
        clean, "oriented_order", "false_breakout", "symbol"
    )
    industry = wla.omit_group_sensitivity(
        clean[clean.entry_industry.notna()],
        "oriented_order",
        "false_breakout",
        "entry_industry",
    )
    blocks = {
        str(name): wla.safe_spearman(rows.oriented_order, rows.false_breakout)
        for name, rows in clean.groupby("baseline_block", sort=True)
    }
    boundary_rates: dict[str, Any] = {}
    for column in ("mfe_at_entry", "mae_at_exit"):
        boundary_rates[column] = {
            str(value): {
                "n": int(len(rows)),
                "false_breakout_rate": wla.finite_or_none(
                    rows.false_breakout.astype(float).mean()
                ),
            }
            for value, rows in frame.groupby(column, sort=True)
        }
    full_gate = bool(
        full_boundary_control["partial_rank_rho"] is not None
        and full_boundary_control["partial_rank_rho"] >= 0.10
        and full_boundary_control["loyo_positive_count"] >= 7
    )
    clean_raw_gate = bool(
        clean_raw["rho"] is not None
        and clean_raw["rho"] >= 0.15
        and clean_raw["within_year_rank_rho"] is not None
        and clean_raw["within_year_rank_rho"] > 0
        and clean_raw["loyo_positive_count"] >= 7
    )
    clean_controlled_gate = bool(
        clean_controlled["partial_rank_rho"] is not None
        and clean_controlled["partial_rank_rho"] >= 0.10
        and clean_controlled["loyo_positive_count"] >= 7
    )
    neighbor_gate = bool(
        clean_days["rho"] is not None
        and clean_days["rho"] > 0
        and clean_days["loyo_positive_count"] >= 6
        and clean_sign["rho"] is not None
        and clean_sign["rho"] > 0
        and clean_sign["loyo_positive_count"] >= 6
        and interior_raw["rho"] is not None
        and interior_raw["rho"] > 0
        and interior_raw["loyo_positive_count"] >= 6
    )
    positive_blocks = sum(
        item["rho"] is not None and item["rho"] > 0 for item in blocks.values()
    )
    falsification_gate = bool(
        ex_bottom4["rho"] is not None
        and ex_bottom4["rho"] >= 0.05
        and holding5["rho"] is not None
        and holding5["rho"] >= 0.05
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
        and positive_blocks >= 2
    )
    if (
        full_gate
        and clean_raw_gate
        and clean_controlled_gate
        and neighbor_gate
        and falsification_gate
    ):
        decision = "DEEPEN"
        verdict = "FALSE_BREAKOUT_ORDER_SURVIVES_ENTRY_EXIT_BOUNDARY_FALSIFICATION"
    elif full_gate and clean_raw_gate:
        decision = "REFINE"
        verdict = "ORDER_SURVIVES_BOUNDARY_REMOVAL_BUT_NOT_ALL_INCREMENTAL_GATES"
    elif clean_raw_gate:
        decision = "PIVOT"
        verdict = "BOUNDARY_CLEAN_ORDER_IS_REDUNDANT_WITH_MAGNITUDE_OR_EXIT_MECHANICS"
    else:
        decision = "REJECT"
        verdict = "FALSE_BREAKOUT_ORDER_IS_PRIMARILY_AN_ENTRY_EXIT_BOUNDARY_ARTIFACT"
    return {
        "experiment_id": "EXP-FBB-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "full_sample_boundary_controlled": full_boundary_control,
        "boundary_clean": {
            "raw": clean_raw,
            "controlled": clean_controlled,
            "raw_days_neighbor": clean_days,
            "sign_neighbor": clean_sign,
            "ex_global_bottom1pct_pnl": ex_bottom4,
            "holding_at_least_5_sessions": holding5,
            "leave_one_security_out": security,
            "leave_one_industry_out": industry,
            "baseline_block": blocks,
        },
        "strict_interior_raw": interior_raw,
        "boundary_false_breakout_rates": boundary_rates,
        "gates": {
            "full_boundary_control": full_gate,
            "boundary_clean_raw": clean_raw_gate,
            "boundary_clean_controlled": clean_controlled_gate,
            "neighbors": neighbor_gate,
            "falsification": falsification_gate,
        },
        "interpretation_boundary": "completed-path structure remains conditioned on the frozen exit path even after explicit entry/exit extremum removal",
        "strategy_modification": "NONE",
    }


def fmt(value: Any, digits: int = 3) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def build_report(audit: dict[str, Any], result: dict[str, Any]) -> str:
    full = result["full_sample_boundary_controlled"]
    clean = result["boundary_clean"]
    gates = result["gates"]
    lines = [
        "# False-breakout excursion-order boundary falsification",
        "",
        "EXP-FBB-001 asks whether the H-015 false-breakout topology survives removing the most direct entry/exit-boundary mechanics. It is descriptive falsification, not an exit experiment.",
        "",
        "## Boundary audit",
        "",
        f"- All / boundary-clean / strict-interior cycles: `{audit['cycles']}` / `{audit['boundary_counts']['boundary_clean']}` / `{audit['boundary_counts']['strict_interior']}`.",
        f"- MFE-at-entry / MAE-at-exit cycles: `{audit['boundary_counts']['mfe_at_entry']}` / `{audit['boundary_counts']['mae_at_exit']}`.",
        f"- Boundary-clean / strict-interior false breakouts: `{audit['boundary_clean_false_breakouts']}` / `{audit['strict_interior_false_breakouts']}`.",
        f"- Post-exit rows / replays / counterfactual paths / rules tested: `{audit['post_exit_rows_read']}` / `{audit['strategy_replays']}` / `{audit['counterfactual_paths']}` / `{audit['entry_or_exit_rules_tested']}`.",
        "",
        "## Preregistered tests",
        "",
        "| Full boundary-controlled rho | LOYO + | Boundary-clean raw rho | Within-year | LOYO + | Boundary-clean controlled rho | LOYO + | Strict-interior rho |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {fmt(full['partial_rank_rho'])} | {full['loyo_positive_count']}/8 | "
        f"{fmt(clean['raw']['rho'])} | {fmt(clean['raw']['within_year_rank_rho'])} | {clean['raw']['loyo_positive_count']}/8 | "
        f"{fmt(clean['controlled']['partial_rank_rho'])} | {clean['controlled']['loyo_positive_count']}/8 | "
        f"{fmt(result['strict_interior_raw']['rho'])} |",
        "",
        "## Frozen gates",
        "",
        f"- Full boundary control / clean raw / clean controlled / neighbors / falsification: `{'PASS' if gates['full_boundary_control'] else 'FAIL'}` / `{'PASS' if gates['boundary_clean_raw'] else 'FAIL'}` / `{'PASS' if gates['boundary_clean_controlled'] else 'FAIL'}` / `{'PASS' if gates['neighbors'] else 'FAIL'}` / `{'PASS' if gates['falsification'] else 'FAIL'}`.",
        "",
        "## Scientific decision",
        "",
        f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
        "",
        "Removing extrema at the two hypothesized boundaries reduces direct path-construction mechanics, but any surviving result still uses the completed frozen path and remains non-actionable.",
        "",
        "## Strategy candidate",
        "",
        "None. No entry, exit, hold, stop, ranking, sizing, or production change was tested or authorized.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec, identities = validate_spec()
    frame, audit = load_frame(spec)
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_PATH_MECHANICS_FALSIFICATION",
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
        }
    )
    output_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_year",
        "entry_industry",
        "canonical_exit_reason",
        "holding_trading_days",
        "mfe",
        "mae",
        "days_to_mfe",
        "days_to_mae",
        "normalized_excursion_order",
        "oriented_order",
        "mfe_at_entry",
        "mae_at_entry",
        "mfe_at_exit",
        "mae_at_exit",
        "boundary_clean",
        "strict_interior",
        "round_trip_return",
        "realized_pnl",
        "false_breakout",
    ]
    atomic_write(
        OUTPUT_TABLE,
        frame[output_columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(
        OUTPUT_JSON, json.dumps(wla.clean_json(result), indent=2, sort_keys=True) + "\n"
    )
    atomic_write(REPORT, build_report(audit, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
