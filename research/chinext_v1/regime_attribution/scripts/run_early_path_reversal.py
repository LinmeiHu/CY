#!/usr/bin/env python3
"""Test whether five-session peak giveback precedes additional trade failure."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_phase2_feature_library as phase2  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-EPR-001_spec.json"
LANDMARK = WORK / "artifacts/post_landmark_persistence.csv"
ENTRIES = WORK / "artifacts/entry_gap_premium_attribution.csv"
CONTROLS = WORK / "artifacts/pre_entry_transitions.csv"
BOUNDARY = WORK / "artifacts/false_breakout_boundary_attribution.csv"
OUTPUT_TABLE = WORK / "artifacts/early_path_reversal.csv"
OUTPUT_JSON = WORK / "artifacts/early_path_reversal.json"
REPORT = WORK / "reports/early_path_reversal.md"

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


class ReversalError(RuntimeError):
    """Raised when frozen identity, path, or sample invariants fail."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def finite_or_default(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-EPR-001":
        raise ReversalError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_REVERSAL_OUTCOME_TEST":
        raise ReversalError("experiment is not frozen")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        actual = sha256_file(path) if path.is_file() else "MISSING"
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise ReversalError(f"frozen input mismatch: {mismatches}")
    phase2.validate_inputs()
    return spec, identities


def load_base() -> pd.DataFrame:
    landmark = pd.read_csv(LANDMARK)
    if len(landmark) != 295 or landmark.trade_id.nunique() != 295:
        raise ReversalError("accepted day-5 survivor sample changed")
    entries = pd.read_csv(
        ENTRIES,
        usecols=["trade_id", "entry_signal_date", "entry_execution_date", "execution_price"],
    )
    controls = pd.read_csv(CONTROLS, usecols=["trade_id", *BASE_CONTROLS])
    boundary = pd.read_csv(BOUNDARY, usecols=["trade_id", "false_breakout", "oriented_order"])
    frame = landmark.merge(entries, on="trade_id", validate="one_to_one")
    frame = frame.merge(controls, on="trade_id", validate="one_to_one")
    frame = frame.merge(boundary, on="trade_id", validate="one_to_one")
    frame["entry_year"] = frame.entry_year.astype(int)
    for column in ("false_breakout", "extreme_winner", "severe_loss"):
        frame[column] = frame[column].astype(bool)
    if frame["return_5d"].isna().any() or frame["residual_return_after_5d"].isna().any():
        raise ReversalError("day-5 outcome fields are incomplete")
    return frame


def reconstruct_early_path(
    frame: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    contract = spec["transient_contract"]
    identities = frame[
        ["trade_id", "baseline_block", "symbol", "entry_execution_date"]
    ].copy()
    with tempfile.TemporaryDirectory(prefix="chinext_v1_epr001_") as temporary:
        transient_root = Path(temporary)
        manifest = phase2.extended.materialize_transient_inputs(transient_root)
        if manifest["canonical_sha256"] != contract["canonical_sha256"]:
            raise ReversalError("transient canonical identity changed")
        if manifest["membership"]["sha256"] != contract["membership_sha256"]:
            raise ReversalError("transient membership identity changed")
        connection = phase2.duckdb.connect()
        connection.execute("SET threads=1")
        phase2.create_membership_tables(connection, transient_root / "daily_membership.parquet")
        panel_counts = phase2.create_panel_tables(connection, transient_root)
        phase2.create_stock_features(connection)
        connection.register("entry_ids", identities)
        rows = connection.execute(
            """
            WITH mapped AS (
              SELECT i.*,c.cal_idx AS entry_idx
              FROM entry_ids i
              JOIN calendar c ON CAST(i.entry_execution_date AS DATE)=c.trade_date
            )
            SELECT m.trade_id,m.entry_idx,w.cal_idx,w.trade_date,
                   w.high,w.low,w.close,w.critical_valid,w.coordinate_step_valid,
                   w.corporate_action_count,w.corporate_action_available_date,
                   w.corporate_action_blocking,w.corporate_action_valid,
                   w.share_multiplier,w.cash_per_share,w.rights_ratio
            FROM mapped m
            JOIN stock_windows w
              ON w.baseline_block=m.baseline_block AND w.symbol=m.symbol
             AND w.cal_idx BETWEEN m.entry_idx AND m.entry_idx+4
            ORDER BY m.trade_id,w.cal_idx
            """
        ).fetchdf()
        connection.close()
    if len(rows) != 1475 or not rows.groupby("trade_id").size().eq(5).all():
        raise ReversalError("five-session path coverage changed")
    if not rows.critical_valid.astype(bool).all():
        raise ReversalError("hard-invalid early path row")
    after_entry = rows.cal_idx > rows.entry_idx
    if not rows.loc[after_entry, "coordinate_step_valid"].astype(bool).all():
        raise ReversalError("invalid early-path action coordinate")
    prices = frame[["trade_id", "execution_price", "return_5d"]]
    rows = rows.merge(prices, on="trade_id", validate="many_to_one")
    features: list[dict[str, Any]] = []
    action_trades = 0
    return5_errors: list[float] = []
    for trade_id, group in rows.groupby("trade_id", sort=True):
        group = group.sort_values("cal_idx")
        entry_price = float(group.execution_price.iloc[0])
        share_factor = 1.0
        cash_per_original_share = 0.0
        close_returns: list[tuple[int, float]] = []
        high_returns: list[tuple[int, float]] = []
        low_returns: list[tuple[int, float]] = []
        trade_actions = 0
        for offset, row in enumerate(group.itertuples()):
            count = int(row.corporate_action_count or 0)
            if offset > 0 and count > 0:
                multiplier = finite_or_default(row.share_multiplier, 1.0)
                cash = finite_or_default(row.cash_per_share, 0.0)
                rights = finite_or_default(row.rights_ratio, 0.0)
                visible = pd.notna(row.corporate_action_available_date) and (
                    str(row.corporate_action_available_date)[:10] <= str(row.trade_date)[:10]
                )
                valid = (
                    not bool(row.corporate_action_blocking)
                    and bool(row.corporate_action_valid)
                    and visible
                    and rights == 0.0
                    and multiplier > 0.0
                )
                if not valid:
                    raise ReversalError(f"unresolved early action: {trade_id}")
                cash_per_original_share += share_factor * cash
                share_factor *= multiplier
                trade_actions += count

            def total_return(price: float) -> float:
                return (
                    (share_factor * price + cash_per_original_share) / entry_price - 1.0
                )

            close_returns.append((offset, total_return(float(row.close))))
            high_returns.append((offset, total_return(float(row.high))))
            low_returns.append((offset, total_return(float(row.low))))
        accepted = float(group.return_5d.iloc[0])
        return5_error = abs(close_returns[-1][1] - accepted)
        if return5_error > 1e-12:
            raise ReversalError(f"day-5 reconstruction mismatch: {trade_id}")
        return5_errors.append(return5_error)
        peak_day, peak_close = max(close_returns, key=lambda item: item[1])
        trough_day, trough_close = min(close_returns, key=lambda item: item[1])
        early_high = max(value for _, value in high_returns)
        early_low = min(value for _, value in low_returns)
        features.append(
            {
                "trade_id": trade_id,
                "early_peak_close_return": peak_close,
                "early_trough_close_return": trough_close,
                "early_peak_day": peak_day,
                "early_trough_day": trough_day,
                "early_peak_to_day5_giveback": peak_close - accepted,
                "early_high_to_day5_giveback": early_high - accepted,
                "early_high_return": early_high,
                "early_low_return": early_low,
                "early_peak_earliness": (4.0 - peak_day) / 4.0,
                "early_action_count": trade_actions,
            }
        )
        action_trades += int(trade_actions > 0)
    path = pd.DataFrame(features)
    audit = {
        "survivor_cycles": 295,
        "path_rows": 1475,
        "five_rows_per_cycle": True,
        "hard_invalid_rows": 0,
        "invalid_action_steps": 0,
        "early_action_cycles": action_trades,
        "return5_max_abs_reconstruction_error": max(return5_errors),
        "transient_canonical_sha256": manifest["canonical_sha256"],
        "transient_membership_sha256": manifest["membership"]["sha256"],
        "panel_counts": panel_counts,
        "strategy_replays": 0,
        "post_exit_price_rows_read": 0,
        "rules_tested": 0,
    }
    return path, audit


def partial_rank(
    frame: pd.DataFrame,
    feature: str,
    endpoint: str,
    *,
    extra_controls: tuple[str, ...] = ("return_5d",),
    category_controls: tuple[str, ...] = ("entry_year",),
) -> dict[str, Any]:
    controls = [*BASE_CONTROLS, *extra_controls]
    columns = [feature, endpoint, *controls, *category_controls]
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    result = {"n": int(len(data)), "partial_rank_rho": None, "p_value": None}
    if len(data) < 180 or data[feature].nunique() < 2 or data[endpoint].nunique() < 2:
        return result
    predictor = data[feature].rank(pct=True, method="average").to_numpy(float)
    if pd.api.types.is_bool_dtype(data[endpoint]):
        outcome = data[endpoint].astype(float).to_numpy()
    else:
        outcome = data[endpoint].rank(pct=True, method="average").to_numpy(float)
    ranked_controls = np.column_stack(
        [data[column].rank(pct=True, method="average") for column in controls]
    )
    design_parts = [np.ones((len(data), 1)), ranked_controls]
    for category in category_controls:
        dummies = pd.get_dummies(
            data[category].astype(str), prefix=category, drop_first=True, dtype=float
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
    feature = "early_peak_to_day5_giveback"
    frame = frame.copy()
    frame["future_failure"] = -frame.residual_return_after_5d
    raw = wla.rank_association(frame, feature, "future_failure")
    controlled = controlled_loyo(frame, feature, "future_failure")
    false_breakout = wla.rank_association(frame, feature, "false_breakout")
    topology = wla.rank_association(frame, feature, "oriented_order")
    high_neighbor = wla.rank_association(
        frame, "early_high_to_day5_giveback", "future_failure"
    )
    duration_exit = partial_rank(
        frame,
        feature,
        "future_failure",
        extra_controls=("return_5d", "holding_trading_days"),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    top4 = wla.deterministic_top_flag(frame, 4)
    ex_top4 = wla.rank_association(frame.loc[~top4], feature, "future_failure")
    ex_severe = wla.rank_association(frame.loc[~frame.severe_loss], feature, "future_failure")
    ex_extreme = wla.rank_association(
        frame.loc[~frame.extreme_winner], feature, "future_failure"
    )
    security = wla.omit_group_sensitivity(
        frame, feature, "future_failure", "symbol"
    )
    industry = wla.omit_group_sensitivity(
        frame[frame.entry_industry.notna()],
        feature,
        "future_failure",
        "entry_industry",
    )
    blocks = {
        str(name): wla.safe_spearman(rows[feature], rows.future_failure)
        for name, rows in frame.groupby("baseline_block", sort=True)
    }
    raw_gate = bool(
        raw["rho"] is not None
        and raw["rho"] >= 0.10
        and raw["within_year_rank_rho"] is not None
        and raw["within_year_rank_rho"] > 0
        and raw["loyo_positive_count"] >= 7
    )
    controlled_gate = bool(
        controlled["partial_rank_rho"] is not None
        and controlled["partial_rank_rho"] >= 0.10
        and controlled["loyo_positive_count"] >= 7
    )
    false_breakout_gate = bool(
        false_breakout["rho"] is not None
        and false_breakout["rho"] >= 0.10
        and false_breakout["loyo_positive_count"] >= 7
    )
    neighbor_gate = bool(
        high_neighbor["rho"] is not None
        and high_neighbor["rho"] > 0
        and high_neighbor["loyo_positive_count"] >= 6
        and topology["rho"] is not None
        and topology["rho"] > 0
    )
    falsification_gate = bool(
        duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.08
        and all(item["rho"] is not None and item["rho"] > 0 for item in (ex_top4, ex_severe, ex_extreme))
        and sum(item["rho"] is not None and item["rho"] > 0 for item in blocks.values()) >= 2
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
    )
    if all((raw_gate, controlled_gate, false_breakout_gate, neighbor_gate, falsification_gate)):
        decision = "DEEPEN"
        verdict = "EARLY_GIVEBACK_PRECEDES_ADDITIONAL_FALSE_BREAKOUT_FAILURE"
    elif raw_gate and controlled_gate and false_breakout_gate:
        decision = "REFINE"
        verdict = "EARLY_REVERSAL_SURVIVES_CORE_TESTS_BUT_FAILS_FULL_FALSIFICATION"
    elif raw_gate and controlled_gate:
        decision = "PIVOT"
        verdict = "EARLY_GIVEBACK_RELATES_TO_FUTURE_RETURN_BUT_NOT_FALSE_BREAKOUT_TOPOLOGY"
    elif raw_gate:
        decision = "PIVOT"
        verdict = "RAW_EARLY_GIVEBACK_IS_REDUNDANT_WITH_DAY5_OR_PREENTRY_STATE"
    else:
        decision = "REJECT"
        verdict = "NO_STABLE_EARLY_REVERSAL_TO_FUTURE_FAILURE_MECHANISM"
    return {
        "experiment_id": "EXP-EPR-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "raw": raw,
            "controlled_beyond_day5": controlled,
            "false_breakout": false_breakout,
            "h016_topology": topology,
            "high_based_neighbor": high_neighbor,
            "duration_exit_control": duration_exit,
            "ex_top4_pnl": ex_top4,
            "ex_severe_loss": ex_severe,
            "ex_extreme_winner": ex_extreme,
            "leave_one_security_out": security,
            "leave_one_industry_out": industry,
            "blocks": blocks,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "false_breakout_gate": false_breakout_gate,
            "neighbor_gate": neighbor_gate,
            "falsification_gate": falsification_gate,
        },
        "secondary": {
            "peak_earliness_vs_future_failure": wla.rank_association(
                frame, "early_peak_earliness", "future_failure"
            ),
            "day5_return_vs_future_failure": wla.rank_association(
                frame, "return_5d", "future_failure"
            ),
        },
        "strategy_modification": "NONE",
        "interpretation_boundary": "day-5 path is post-entry and outcome-consumed; no entry, hold, or exit action is authorized",
    }


def build_report(result: dict[str, Any], audit: dict[str, Any]) -> str:
    primary = result["primary"]
    lines = [
        "# Early held-path reversal and post-day-5 failure",
        "",
        "EXP-EPR-001 tests one continuous close-peak-to-day-5 giveback feature. It is holding-path mechanism evidence, not an entry or exit rule.",
        "",
        "## Integrity and sample",
        "",
        f"- Day-5 survivors / path rows: `{audit['survivor_cycles']}` / `{audit['path_rows']}`.",
        f"- Early corporate-action cycles: `{audit['early_action_cycles']}`; hard-invalid/action-invalid rows: `0` / `0`.",
        "- Accepted day-5 returns reconstruct to <=1e-12 under exact share/cash action accounting.",
        "- No post-exit row, counterfactual exit, replay, threshold, or strategy rule was used.",
        "",
        "## Frozen tests",
        "",
        "| Test | Estimate | LOYO + |",
        "|---|---:|---:|",
        f"| Giveback vs future failure | {primary['raw']['rho']:.3f} | {primary['raw']['loyo_positive_count']}/8 |",
        f"| Controlled beyond day-5 state | {primary['controlled_beyond_day5']['partial_rank_rho']:.3f} | {primary['controlled_beyond_day5']['loyo_positive_count']}/8 |",
        f"| Giveback vs false breakout | {primary['false_breakout']['rho']:.3f} | {primary['false_breakout']['loyo_positive_count']}/8 |",
        f"| Giveback vs H-016 topology | {primary['h016_topology']['rho']:.3f} | {primary['h016_topology']['loyo_positive_count']}/8 |",
        f"| High-based neighbor vs future failure | {primary['high_based_neighbor']['rho']:.3f} | {primary['high_based_neighbor']['loyo_positive_count']}/8 |",
        "",
        "## Decision",
        "",
        f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
        "",
        f"Frozen gates raw/control/false-breakout/neighbor/falsification: `{primary['raw_gate']}` / `{primary['controlled_gate']}` / `{primary['false_breakout_gate']}` / `{primary['neighbor_gate']}` / `{primary['falsification_gate']}`.",
        "",
        "No entry, ranking, sizing, holding, exit, or production modification was tested or authorized.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec, identities = validate_spec()
    frame = load_base()
    path, audit = reconstruct_early_path(frame, spec)
    frame = frame.merge(path, on="trade_id", validate="one_to_one")
    frame["future_failure"] = -frame.residual_return_after_5d
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_HOLDING_PATH_MECHANISM",
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_year",
        "entry_industry",
        "return_5d",
        "residual_return_after_5d",
        "future_failure",
        "early_peak_close_return",
        "early_trough_close_return",
        "early_peak_day",
        "early_trough_day",
        "early_peak_to_day5_giveback",
        "early_high_to_day5_giveback",
        "early_high_return",
        "early_low_return",
        "early_peak_earliness",
        "early_action_count",
        "false_breakout",
        "oriented_order",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
        "extreme_winner",
        "severe_loss",
        *BASE_CONTROLS,
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
    atomic_write(REPORT, build_report(result, audit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
