#!/usr/bin/env python3
"""Execute preregistered post-entry landmark right-tail emergence analysis."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-PEL-001_spec.json"
YEARLY_TRADES = WORK / "artifacts/yearly_trades.csv"
TRANSITIONS = WORK / "artifacts/pre_entry_transitions.csv"
OUTPUT_TABLE = WORK / "artifacts/post_entry_landmark_attribution.csv"
OUTPUT_JSON = WORK / "artifacts/post_entry_landmark_emergence.json"
REPORT = WORK / "reports/post_entry_landmark_emergence.md"

BASE_CONTROLS = (
    "entry_rs_score",
    "entry_mom20",
    "entry_box_width",
    "entry_minvol_location",
    "entry_breakout_volume_ratio",
    "index_return_20d",
    "index_realized_vol20",
    "breadth_composite",
    "entry_beta60",
    "entry_log_amount20",
)
SECONDARY_ENDPOINTS = (
    "winner20",
    "false_breakout",
    "severe_loss",
    "mfe",
    "round_trip_return",
)


class LandmarkError(RuntimeError):
    """Raised when a frozen identity, sample, or model invariant fails."""


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


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-PEL-001":
        raise LandmarkError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_LANDMARK_OUTCOME_JOIN":
        raise LandmarkError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatch: dict[str, Any] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise LandmarkError(f"missing bound input: {name}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatch[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatch:
        raise LandmarkError(f"frozen input mismatch: {mismatch}")
    return spec, identities


def load_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = pd.read_csv(
        YEARLY_TRADES,
        usecols=["trade_id", "return_5d", "return_10d", "return_20d"],
    )
    if len(path) != 399 or path.trade_id.nunique() != 399:
        raise LandmarkError("yearly trade path table is not 399 unique cycles")
    expected = spec["sample"]["expected_available"]
    actual = {
        "return_5d": int(path.return_5d.notna().sum()),
        "return_10d": int(path.return_10d.notna().sum()),
        "return_20d": int(path.return_20d.notna().sum()),
    }
    if actual != expected:
        raise LandmarkError(f"landmark availability changed: {actual} != {expected}")
    base = pd.read_csv(TRANSITIONS)
    if len(base) != 399 or base.trade_id.nunique() != 399:
        raise LandmarkError("accepted transition table is not 399 unique cycles")
    for column in ("entry_signal_date", "entry_execution_date"):
        base[column] = pd.to_datetime(base[column], errors="raise")
    if not (base.entry_signal_date < base.entry_execution_date).all():
        raise LandmarkError("entry signal/execution order is invalid")
    frame = base.merge(path, on="trade_id", validate="one_to_one")
    for column in ("extreme_winner", "winner20", "false_breakout", "severe_loss"):
        frame[column] = frame[column].astype(bool)
    landmark = frame[frame.return_5d.notna()].copy()
    if len(landmark) != expected["return_5d"]:
        raise LandmarkError("primary landmark sample changed")
    if int(landmark.extreme_winner.sum()) < spec["sample"]["minimum_extreme_winners"]:
        raise LandmarkError("primary landmark extreme-winner count below minimum")
    audit = {
        "all_cycles": 399,
        "landmark5_cycles": int(len(landmark)),
        "landmark10_cycles": actual["return_10d"],
        "landmark20_cycles": actual["return_20d"],
        "landmark5_extreme_winners": int(landmark.extreme_winner.sum()),
        "landmark5_winner20": int(landmark.winner20.sum()),
        "causal_entry_failures": 0,
        "post_exit_price_rows_read": 0,
        "strategy_replays": 0,
        "counterfactual_early_returns": 0,
    }
    return landmark, audit


def partial_rank(
    frame: pd.DataFrame,
    feature: str,
    endpoint: str,
    *,
    extra_controls: tuple[str, ...] = (),
    category_controls: tuple[str, ...] = ("entry_year",),
) -> dict[str, Any]:
    controls = [*BASE_CONTROLS, *extra_controls]
    columns = [feature, endpoint, *controls, *category_controls]
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    result = {"n": int(len(data)), "partial_rank_rho": None, "p_value": None}
    if len(data) < 200 or data[feature].nunique() < 2 or data[endpoint].nunique() < 2:
        return result
    predictor = data[feature].rank(pct=True, method="average").to_numpy(float)
    if pd.api.types.is_bool_dtype(data[endpoint]) or set(data[endpoint].unique()).issubset(
        {0, 1, False, True}
    ):
        outcome = data[endpoint].astype(float).to_numpy()
    else:
        outcome = data[endpoint].rank(pct=True, method="average").to_numpy(float)
    ranked = pd.DataFrame(index=data.index)
    for control in controls:
        ranked[control] = data[control].rank(pct=True, method="average")
    design_parts = [np.ones((len(data), 1)), ranked.to_numpy(float)]
    for category in category_controls:
        dummies = pd.get_dummies(
            data[category].fillna("MISSING").astype(str),
            prefix=category,
            drop_first=True,
            dtype=float,
        )
        if len(dummies.columns):
            design_parts.append(dummies.to_numpy(float))
    design = np.column_stack(design_parts)
    x_residual = predictor - design @ np.linalg.lstsq(design, predictor, rcond=None)[0]
    y_residual = outcome - design @ np.linalg.lstsq(design, outcome, rcond=None)[0]
    if np.std(x_residual) == 0 or np.std(y_residual) == 0:
        return result
    estimate = pearsonr(x_residual, y_residual)
    result["partial_rank_rho"] = wla.finite_or_none(estimate.statistic)
    result["p_value"] = wla.finite_or_none(estimate.pvalue)
    return result


def controlled_loyo(frame: pd.DataFrame, feature: str, endpoint: str) -> dict[str, Any]:
    full = partial_rank(frame, feature, endpoint)
    loyo = {
        str(year): partial_rank(frame[frame.entry_year != year], feature, endpoint)
        for year in range(2018, 2026)
    }
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    return {**full, "loyo": loyo, "loyo_positive_count": int(positive)}


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    raw = wla.rank_association(frame, "return_5d", "extreme_winner")
    controlled = controlled_loyo(frame, "return_5d", "extreme_winner")
    holding_exit = partial_rank(
        frame,
        "return_5d",
        "extreme_winner",
        extra_controls=("holding_trading_days",),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    top4 = wla.deterministic_top_flag(frame, 4)
    ex_top4 = wla.rank_association(frame.loc[~top4], "return_5d", "extreme_winner")
    extreme_symbols = sorted(frame.loc[frame.extreme_winner, "symbol"].astype(str).unique())
    security = wla.omit_group_sensitivity(
        frame, "return_5d", "extreme_winner", "symbol", extreme_symbols
    )
    industry = wla.omit_group_sensitivity(
        frame[frame.entry_industry.notna()],
        "return_5d",
        "extreme_winner",
        "entry_industry",
    )
    blocks = {
        str(name): wla.safe_spearman(rows.return_5d, rows.extreme_winner)
        for name, rows in frame.groupby("baseline_block", sort=True)
    }
    neighbors: dict[str, Any] = {}
    for column in ("return_10d", "return_20d"):
        subset = frame[frame[column].notna()]
        neighbors[column] = wla.rank_association(subset, column, "extreme_winner")
    entry_benchmark = wla.rank_association(frame, "entry_rs_score", "extreme_winner")
    raw_gate = bool(
        raw["rho"] is not None
        and raw["rho"] >= 0.20
        and raw["within_year_rank_rho"] is not None
        and raw["within_year_rank_rho"] > 0
        and raw["loyo_positive_count"] >= 7
    )
    controlled_gate = bool(
        controlled["partial_rank_rho"] is not None
        and controlled["partial_rank_rho"] >= 0.20
        and controlled["loyo_positive_count"] >= 7
    )
    neighbor_gate = all(
        item["rho"] is not None
        and item["rho"] > 0
        and item["loyo_positive_count"] >= 6
        for item in neighbors.values()
    )
    falsification_gate = bool(
        ex_top4["rho"] is not None
        and ex_top4["rho"] > 0
        and holding_exit["partial_rank_rho"] is not None
        and holding_exit["partial_rank_rho"] >= 0.10
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
    )
    if raw_gate and controlled_gate and neighbor_gate and falsification_gate:
        decision = "DEEPEN"
        verdict = "RIGHT_TAIL_SEPARATES_BY_LANDMARK5_WITH_QUALIFICATION"
    elif raw_gate and controlled_gate:
        decision = "REFINE"
        verdict = "EARLY_CONTINUATION_ASSOCIATION_MECHANICALLY_OR_TEMPORALLY_QUALIFIED"
    elif raw_gate:
        decision = "PIVOT"
        verdict = "RAW_EARLY_CONTINUATION_REDUNDANT_OR_MECHANICAL"
    else:
        decision = "REJECT"
        verdict = "NO_STABLE_LANDMARK5_SEPARATION"
    secondary = {
        endpoint: wla.rank_association(frame, "return_5d", endpoint)
        for endpoint in SECONDARY_ENDPOINTS
    }
    return {
        "experiment_id": "EXP-PEL-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "raw": raw,
            "controlled": controlled,
            "holding_duration_exit_reason_control": holding_exit,
            "ex_global_top1pct_pnl": ex_top4,
            "leave_one_extreme_security_out": security,
            "leave_one_industry_out": industry,
            "baseline_block": blocks,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "neighbor_gate": neighbor_gate,
            "falsification_gate": falsification_gate,
        },
        "neighbors": neighbors,
        "entry_rs_benchmark": entry_benchmark,
        "secondary": secondary,
        "controls": [*BASE_CONTROLS, "entry_year"],
        "interpretation_boundary": "return_5d is part of the realized holding path and terminal outcome; association locates emergence but is not a causal or tradable predictor",
        "strategy_modification": "NONE",
    }


def fmt(value: Any, digits: int = 3) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def build_report(frame: pd.DataFrame, audit: dict[str, Any], result: dict[str, Any]) -> str:
    p = result["primary"]
    lines = [
        "# Post-entry landmark emergence of the CHINEXT V1 right tail",
        "",
        "EXP-PEL-001 asks when extreme winners first separate after entry. It is descriptive holding-path mechanism evidence, not an entry signal, exit rule, or causal prediction experiment.",
        "",
        "## Landmark audit",
        "",
        f"- Frozen cycles: `{audit['all_cycles']}`; day-5/day-10/day-20 observable samples: `{audit['landmark5_cycles']}` / `{audit['landmark10_cycles']}` / `{audit['landmark20_cycles']}`.",
        f"- Day-5 extreme winners/winner20: `{audit['landmark5_extreme_winners']}` / `{audit['landmark5_winner20']}`.",
        f"- Causal-entry/post-exit/counterfactual/replay failures: `{audit['causal_entry_failures']}` / `{audit['post_exit_price_rows_read']}` / `{audit['counterfactual_early_returns']}` / `{audit['strategy_replays']}`.",
        "- Missing later landmarks are not imputed. Each horizon is conditioned on the trade remaining observable under the frozen strategy through that landmark.",
        "",
        "## Primary day-5 test",
        "",
        "| Raw rho | Within-year rho | LOYO + | Controlled rho | Controlled LOYO + | Holding/exit rho | Ex-top-1% rho | Pass raw/control/neighbor/falsification |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
        f"| {fmt(p['raw']['rho'])} | {fmt(p['raw']['within_year_rank_rho'])} | {p['raw']['loyo_positive_count']}/8 | "
        f"{fmt(p['controlled']['partial_rank_rho'])} | {p['controlled']['loyo_positive_count']}/8 | "
        f"{fmt(p['holding_duration_exit_reason_control']['partial_rank_rho'])} | "
        f"{fmt(p['ex_global_top1pct_pnl']['rho'])} | "
        f"{'Y' if p['raw_gate'] else 'N'}/{'Y' if p['controlled_gate'] else 'N'}/"
        f"{'Y' if p['neighbor_gate'] else 'N'}/{'Y' if p['falsification_gate'] else 'N'} |",
        "",
        "The controlled design uses only frozen pre-entry V1, market, breadth, beta, liquidity, and year state. Holding duration and exit reason are a separate post-outcome sensitivity because they are strategy-path mediators, not causal entry controls.",
        "",
        "## Fixed later-landmark confirmation",
        "",
        "| Landmark | N | Extreme-winner rho | Within-year rho | LOYO + |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, item in result["neighbors"].items():
        lines.append(
            f"| {name} | {item['n']} | {fmt(item['rho'])} | "
            f"{fmt(item['within_year_rank_rho'])} | {item['loyo_positive_count']}/8 |"
        )
    lines += [
        "",
        "## Outcome-class day-5 distribution",
        "",
        "| Outcome class | N | Median day-5 return | Mean day-5 return |",
        "|---|---:|---:|---:|",
    ]
    for outcome_class, rows in frame.groupby("outcome_class", sort=True):
        lines.append(
            f"| {outcome_class} | {len(rows)} | {fmt(rows.return_5d.median())} | "
            f"{fmt(rows.return_5d.mean())} |"
        )
    lines += [
        "",
        "## Scientific decision",
        "",
        f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
        "",
        "Day-5 return is part of the future holding path and eventual trade return. Even a robust association would only locate when tail separation becomes visible; it cannot be called an entry edge, and this experiment does not test any sell/hold action.",
        "",
        "## Strategy candidate",
        "",
        "None. EXP-PEL-001 authorizes no entry, exit, ranking, sizing, or production change.",
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
            "evidence_grade": "EXPLORATORY_HOLDING_PATH_MECHANISM",
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "entry_industry",
        "outcome_class",
        "return_5d",
        "return_10d",
        "return_20d",
        "extreme_winner",
        "winner20",
        "false_breakout",
        "severe_loss",
        "mfe",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
    ]
    atomic_write(
        OUTPUT_TABLE,
        frame[columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(
        OUTPUT_JSON, json.dumps(wla.clean_json(result), indent=2, sort_keys=True) + "\n"
    )
    atomic_write(REPORT, build_report(frame, audit, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
