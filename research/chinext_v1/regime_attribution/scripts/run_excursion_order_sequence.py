#!/usr/bin/env python3
"""Execute the preregistered MFE/MAE excursion-order mechanism test."""

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

import run_post_entry_landmark_emergence as landmark  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-EOS-001_spec.json"
YEARLY_TRADES = WORK / "artifacts/yearly_trades.csv"
TRANSITIONS = WORK / "artifacts/pre_entry_transitions.csv"
OUTPUT_TABLE = WORK / "artifacts/excursion_order_attribution.csv"
OUTPUT_JSON = WORK / "artifacts/excursion_order_sequence.json"
REPORT = WORK / "reports/excursion_order_sequence.md"

ENDPOINT_DIRECTIONS = {"extreme_winner": 1, "false_breakout": -1}


class ExcursionOrderError(RuntimeError):
    """Raised when a frozen identity, sample, or path invariant fails."""


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


def normalized_excursion_order(
    days_to_mfe: pd.Series,
    days_to_mae: pd.Series,
    holding_trading_days: pd.Series,
) -> pd.Series:
    denominator = holding_trading_days.astype(float).clip(lower=1.0)
    return (days_to_mfe.astype(float) - days_to_mae.astype(float)) / denominator


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-EOS-001":
        raise ExcursionOrderError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_EXCURSION_OUTCOME_TEST":
        raise ExcursionOrderError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatch: dict[str, Any] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise ExcursionOrderError(f"missing bound input: {name}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatch[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatch:
        raise ExcursionOrderError(f"frozen input mismatch: {mismatch}")
    return spec, identities


def load_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = [
        "trade_id",
        "holding_trading_days",
        "mfe",
        "mae",
        "days_to_mfe",
        "days_to_mae",
        "round_trip_return",
        "realized_pnl",
        "canonical_exit_reason",
    ]
    path = pd.read_csv(YEARLY_TRADES, usecols=columns)
    if len(path) != 399 or path.trade_id.nunique() != 399:
        raise ExcursionOrderError("yearly trade path is not 399 unique cycles")
    required = [
        "holding_trading_days",
        "mfe",
        "mae",
        "days_to_mfe",
        "days_to_mae",
        "round_trip_return",
        "realized_pnl",
        "canonical_exit_reason",
    ]
    if path[required].replace([np.inf, -np.inf], np.nan).isna().any().any():
        raise ExcursionOrderError("required path field is missing or nonfinite")
    integer_fields = ("holding_trading_days", "days_to_mfe", "days_to_mae")
    for column in integer_fields:
        if not np.allclose(path[column], np.round(path[column]), rtol=0.0, atol=0.0):
            raise ExcursionOrderError(f"non-integer path coordinate: {column}")
    if (path.holding_trading_days < 0).any():
        raise ExcursionOrderError("negative holding duration")
    if (
        (path.days_to_mfe < 0).any()
        or (path.days_to_mae < 0).any()
        or (path.days_to_mfe > path.holding_trading_days).any()
        or (path.days_to_mae > path.holding_trading_days).any()
    ):
        raise ExcursionOrderError("excursion coordinate outside held path")
    controls = pd.read_csv(TRANSITIONS)
    if len(controls) != 399 or controls.trade_id.nunique() != 399:
        raise ExcursionOrderError("accepted transition table is not 399 unique cycles")
    control_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_year",
        "entry_industry",
        *landmark.BASE_CONTROLS,
    ]
    frame = path.merge(
        controls[control_columns], on="trade_id", how="left", validate="one_to_one"
    )
    if frame["entry_year"].isna().any():
        raise ExcursionOrderError("path failed to join accepted entry lineage")
    frame["extreme_winner"] = frame.round_trip_return >= 0.50
    frame["false_breakout"] = (frame.mfe < 0.10) & (frame.round_trip_return <= 0.0)
    expected = spec["sample"]["expected_endpoint_counts"]
    actual = {
        "extreme_winner": int(frame.extreme_winner.sum()),
        "false_breakout": int(frame.false_breakout.sum()),
    }
    if actual != expected:
        raise ExcursionOrderError(f"endpoint counts changed: {actual} != {expected}")
    frame["adverse_excursion_magnitude"] = -frame.mae
    frame["excursion_order_days"] = frame.days_to_mfe - frame.days_to_mae
    frame["normalized_excursion_order"] = normalized_excursion_order(
        frame.days_to_mfe, frame.days_to_mae, frame.holding_trading_days
    )
    frame["excursion_order_sign"] = np.sign(frame.excursion_order_days).astype(int)
    frame["mae_before_mfe"] = frame.excursion_order_days > 0
    if (frame.normalized_excursion_order.abs() > 1.0 + 1e-12).any():
        raise ExcursionOrderError("normalized order outside [-1, 1]")
    audit = {
        "cycles": int(len(frame)),
        "endpoint_counts": actual,
        "tie_count": int((frame.excursion_order_days == 0).sum()),
        "zero_duration_count": int((frame.holding_trading_days == 0).sum()),
        "coordinate_failures": 0,
        "post_exit_rows_read": 0,
        "strategy_replays": 0,
        "entry_or_exit_rules_tested": 0,
        "phase1_first_occurrence_semantics": "Python max/min over chronological held-path tuples; first occurrence wins a tie",
    }
    return frame, audit


def controlled_loyo(
    frame: pd.DataFrame, feature: str, endpoint: str
) -> dict[str, Any]:
    extra = ("mfe", "adverse_excursion_magnitude", "holding_trading_days")

    def estimate(rows: pd.DataFrame) -> dict[str, Any]:
        return landmark.partial_rank(
            rows,
            feature,
            endpoint,
            extra_controls=extra,
            category_controls=("entry_year", "canonical_exit_reason"),
        )

    full = estimate(frame)
    loyo = {
        str(year): estimate(frame[frame.entry_year != year])
        for year in range(2018, 2026)
    }
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    return {**full, "loyo": loyo, "loyo_positive_count": int(positive)}


def analyze_endpoint(
    frame: pd.DataFrame,
    endpoint: str,
    direction: int,
    q_value: float | None,
) -> dict[str, Any]:
    oriented = frame.copy()
    oriented["oriented_order"] = direction * oriented.normalized_excursion_order
    oriented["oriented_order_days"] = direction * oriented.excursion_order_days
    oriented["oriented_order_sign"] = direction * oriented.excursion_order_sign
    raw = wla.rank_association(oriented, "oriented_order", endpoint)
    controlled = controlled_loyo(oriented, "oriented_order", endpoint)
    day_neighbor = wla.rank_association(oriented, "oriented_order_days", endpoint)
    sign_neighbor = wla.rank_association(oriented, "oriented_order_sign", endpoint)
    top4 = wla.deterministic_top_flag(oriented, 4)
    ex_top4 = wla.rank_association(
        oriented.loc[~top4], "oriented_order", endpoint
    )
    long_enough = wla.rank_association(
        oriented.loc[oriented.holding_trading_days >= 5],
        "oriented_order",
        endpoint,
    )
    opposite_tail = (
        ~oriented.false_breakout if endpoint == "extreme_winner" else ~oriented.extreme_winner
    )
    ex_opposite_tail = wla.rank_association(
        oriented.loc[opposite_tail], "oriented_order", endpoint
    )
    security = wla.omit_group_sensitivity(
        oriented, "oriented_order", endpoint, "symbol"
    )
    industry = wla.omit_group_sensitivity(
        oriented[oriented.entry_industry.notna()],
        "oriented_order",
        endpoint,
        "entry_industry",
    )
    yearly = {
        str(year): wla.safe_spearman(rows.oriented_order, rows[endpoint])
        for year, rows in oriented.groupby("entry_year", sort=True)
    }
    blocks = {
        str(name): wla.safe_spearman(rows.oriented_order, rows[endpoint])
        for name, rows in oriented.groupby("baseline_block", sort=True)
    }
    raw_gate = bool(
        raw["rho"] is not None
        and raw["rho"] >= 0.15
        and raw["within_year_rank_rho"] is not None
        and raw["within_year_rank_rho"] > 0
        and raw["loyo_positive_count"] >= 7
        and q_value is not None
        and q_value <= 0.05
    )
    controlled_gate = bool(
        controlled["partial_rank_rho"] is not None
        and controlled["partial_rank_rho"] >= 0.10
        and controlled["loyo_positive_count"] >= 7
    )
    neighbor_gate = bool(
        day_neighbor["rho"] is not None
        and day_neighbor["rho"] > 0
        and day_neighbor["loyo_positive_count"] >= 6
        and sign_neighbor["rho"] is not None
        and sign_neighbor["rho"] > 0
        and sign_neighbor["loyo_positive_count"] >= 6
    )
    positive_blocks = sum(
        item["rho"] is not None and item["rho"] > 0 for item in blocks.values()
    )
    falsification_gate = bool(
        ex_top4["rho"] is not None
        and ex_top4["rho"] >= 0.05
        and long_enough["rho"] is not None
        and long_enough["rho"] >= 0.05
        and ex_opposite_tail["rho"] is not None
        and ex_opposite_tail["rho"] >= 0.05
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
        and positive_blocks >= 2
    )
    return {
        "expected_direction": direction,
        "raw_oriented": raw,
        "raw_actual_rho": (
            None if raw["rho"] is None else float(direction * raw["rho"])
        ),
        "q_value_bh_two_endpoints": q_value,
        "controlled_oriented": controlled,
        "neighbor_raw_days_oriented": day_neighbor,
        "neighbor_sign_oriented": sign_neighbor,
        "yearly_oriented": yearly,
        "baseline_block_oriented": blocks,
        "ex_global_top1pct_pnl_oriented": ex_top4,
        "holding_at_least_5_sessions_oriented": long_enough,
        "ex_opposite_tail_oriented": ex_opposite_tail,
        "leave_one_security_out_oriented": security,
        "leave_one_industry_out_oriented": industry,
        "raw_gate": raw_gate,
        "controlled_gate": controlled_gate,
        "neighbor_gate": neighbor_gate,
        "falsification_gate": falsification_gate,
        "passes_all": bool(
            raw_gate and controlled_gate and neighbor_gate and falsification_gate
        ),
    }


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    p_values: dict[str, float | None] = {}
    for endpoint, direction in ENDPOINT_DIRECTIONS.items():
        oriented = direction * frame.normalized_excursion_order
        p_values[endpoint] = wla.safe_spearman(oriented, frame[endpoint])["p_value"]
    q_values = wla.bh_adjust(p_values)
    endpoints = {
        endpoint: analyze_endpoint(frame, endpoint, direction, q_values[endpoint])
        for endpoint, direction in ENDPOINT_DIRECTIONS.items()
    }
    passing = [name for name, item in endpoints.items() if item["passes_all"]]
    raw_control = [
        name
        for name, item in endpoints.items()
        if item["raw_gate"] and item["controlled_gate"]
    ]
    if len(passing) == 2:
        decision = "DEEPEN"
        verdict = "EXCURSION_SEQUENCE_DISTINGUISHES_WINNERS_AND_FALSE_BREAKOUTS"
    elif len(passing) == 1:
        decision = "REFINE"
        verdict = f"EXCURSION_SEQUENCE_SURVIVES_ONLY_FOR_{passing[0].upper()}"
    elif raw_control:
        decision = "PIVOT"
        verdict = "ORDER_ASSOCIATION_FAILS_NEIGHBOR_OR_CONCENTRATION_FALSIFICATION"
    else:
        decision = "REJECT"
        verdict = "EXCURSION_SEQUENCE_IS_NOT_INCREMENTAL_TO_MAGNITUDE_AND_PATH_MECHANICS"
    return {
        "experiment_id": "EXP-EOS-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "endpoints": endpoints,
        "passing_endpoints": passing,
        "primary_feature": "(days_to_mfe - days_to_mae) / max(holding_trading_days, 1)",
        "positive_feature_meaning": "MAE occurs earlier than MFE",
        "interpretation_boundary": "full-path ordering is post-entry descriptive structure conditioned on the frozen exit path, not an actionable state or causal rule",
        "strategy_modification": "NONE",
    }


def fmt(value: Any, digits: int = 3) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def build_report(audit: dict[str, Any], result: dict[str, Any]) -> str:
    lines = [
        "# Full-path excursion-order attribution",
        "",
        "EXP-EOS-001 tests whether adversity-before-opportunity ordering distinguishes extreme winners from false breakouts after magnitude and path controls. It is descriptive full-path topology, not an entry or exit rule.",
        "",
        "## Path audit",
        "",
        f"- Complete cycles: `{audit['cycles']}`; extreme winners / false breakouts: `{audit['endpoint_counts']['extreme_winner']}` / `{audit['endpoint_counts']['false_breakout']}`.",
        f"- Same-session MFE/MAE ties / zero-duration cycles: `{audit['tie_count']}` / `{audit['zero_duration_count']}`.",
        f"- Coordinate failures / post-exit rows / replays / rules tested: `{audit['coordinate_failures']}` / `{audit['post_exit_rows_read']}` / `{audit['strategy_replays']}` / `{audit['entry_or_exit_rules_tested']}`.",
        "- Positive normalized order means the first MAE occurs before the first MFE. Chronological first occurrence wins exact magnitude ties in the accepted Phase 1 path construction.",
        "",
        "## Preregistered endpoints",
        "",
        "All displayed rhos except `actual rho` are oriented so positive supports the endpoint-specific prediction.",
        "",
        "| Endpoint | Actual raw rho | Oriented within-year | LOYO + | BH q | Controlled oriented rho | LOYO + | Raw/control/neighbor/falsification |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for endpoint, item in result["endpoints"].items():
        raw = item["raw_oriented"]
        controlled = item["controlled_oriented"]
        lines.append(
            f"| {endpoint} | {fmt(item['raw_actual_rho'])} | {fmt(raw['within_year_rank_rho'])} | "
            f"{raw['loyo_positive_count']}/8 | {fmt(item['q_value_bh_two_endpoints'])} | "
            f"{fmt(controlled['partial_rank_rho'])} | {controlled['loyo_positive_count']}/8 | "
            f"{'Y' if item['raw_gate'] else 'N'}/{'Y' if item['controlled_gate'] else 'N'}/"
            f"{'Y' if item['neighbor_gate'] else 'N'}/{'Y' if item['falsification_gate'] else 'N'} |"
        )
    lines += [
        "",
        "## Scientific decision",
        "",
        f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
        "",
        "The model controls ranked MFE, adverse-excursion magnitude, holding duration, fixed pre-entry state, entry year, and canonical exit reason. A surviving result still describes a completed frozen path and cannot establish when or how to trade.",
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
            "evidence_grade": "EXPLORATORY_FULL_PATH_MECHANISM",
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
        "excursion_order_days",
        "normalized_excursion_order",
        "excursion_order_sign",
        "mae_before_mfe",
        "round_trip_return",
        "realized_pnl",
        "extreme_winner",
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
