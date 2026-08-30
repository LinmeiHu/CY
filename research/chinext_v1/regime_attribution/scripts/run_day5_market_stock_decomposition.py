#!/usr/bin/env python3
"""Decompose accepted day-5 continuation into market and stock-specific parts."""

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

SPEC = WORK / "experiments/EXP-D5D-001_spec.json"
LANDMARK = WORK / "artifacts/post_entry_landmark_attribution.csv"
ACCEPTED_RESULT = WORK / "artifacts/post_entry_landmark_emergence.json"
CONTROLS = WORK / "artifacts/pre_entry_transitions.csv"
INDEX = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
CALENDAR = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet"
)
OUTPUT_TABLE = WORK / "artifacts/day5_market_stock_decomposition.csv"
OUTPUT_JSON = WORK / "artifacts/day5_market_stock_decomposition.json"
REPORT = WORK / "reports/day5_market_stock_decomposition.md"
EVIDENCE_PACKET = WORK / "reports/day5_market_stock_decomposition_evidence_packet.md"

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


class DecompositionError(RuntimeError):
    """Raised when a frozen identity, alignment, or population invariant fails."""


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


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-D5D-001":
        raise DecompositionError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_COMPONENT_OUTCOME_TEST":
        raise DecompositionError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        actual = sha256_file(path) if path.is_file() else "MISSING"
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise DecompositionError(f"frozen input mismatch: {mismatches}")
    return spec, identities


def load_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    landmark = pd.read_csv(LANDMARK)
    if len(landmark) != 295 or landmark.trade_id.nunique() != 295:
        raise DecompositionError("accepted day-5 survivor population changed")
    if landmark.return_5d.isna().any() or not (landmark.return_5d > -1.0).all():
        raise DecompositionError("accepted day-5 return is missing or log-invalid")
    expected = spec["sample"]
    if int(landmark.extreme_winner.astype(bool).sum()) != expected["extreme_winners"]:
        raise DecompositionError("accepted extreme-winner count changed")
    controls = pd.read_csv(CONTROLS, usecols=["trade_id", *BASE_CONTROLS])
    if len(controls) != 399 or controls.trade_id.nunique() != 399:
        raise DecompositionError("accepted pre-entry control population changed")
    frame = landmark.merge(controls, on="trade_id", validate="one_to_one")
    complete = int(frame[list(BASE_CONTROLS)].notna().all(axis=1).sum())
    if complete != expected["fixed_control_complete"]:
        raise DecompositionError("fixed-control complete population changed")

    calendar = pd.read_parquet(CALENDAR, columns=["trade_date"])
    calendar["trade_date"] = pd.to_datetime(calendar.trade_date, errors="raise")
    calendar = calendar.sort_values("trade_date").reset_index(drop=True)
    if calendar.trade_date.duplicated().any():
        raise DecompositionError("calendar dates are not unique")
    calendar["cal_idx"] = np.arange(len(calendar), dtype=int)

    frame["entry_execution_date"] = pd.to_datetime(
        frame.entry_execution_date, errors="raise"
    )
    frame = frame.merge(
        calendar.rename(columns={"trade_date": "entry_execution_date"}),
        on="entry_execution_date",
        how="left",
        validate="many_to_one",
    )
    if frame.cal_idx.isna().any():
        raise DecompositionError("entry execution date is absent from calendar")
    date_by_index = dict(zip(calendar.cal_idx, calendar.trade_date, strict=True))
    frame["day5_session_date"] = [
        date_by_index.get(int(index) + 4) for index in frame.cal_idx
    ]
    if frame.day5_session_date.isna().any():
        raise DecompositionError("fifth held-session date is absent from calendar")

    index = pd.read_csv(INDEX, dtype={"trade_date": str})
    index["trade_date"] = pd.to_datetime(index.trade_date, format="%Y%m%d", errors="raise")
    if index.trade_date.duplicated().any():
        raise DecompositionError("399102 anchor dates are not unique")
    for column in ("open", "close"):
        index[column] = pd.to_numeric(index[column], errors="raise")
    entry_index = index[["trade_date", "open"]].rename(
        columns={"trade_date": "entry_execution_date", "open": "market_entry_open"}
    )
    day5_index = index[["trade_date", "close"]].rename(
        columns={"trade_date": "day5_session_date", "close": "market_day5_close"}
    )
    frame = frame.merge(entry_index, on="entry_execution_date", validate="many_to_one")
    frame = frame.merge(day5_index, on="day5_session_date", validate="many_to_one")
    if len(frame) != expected["cycles"] or frame.trade_id.nunique() != expected["cycles"]:
        raise DecompositionError("index alignment changed the survivor population")
    if (frame[["market_entry_open", "market_day5_close"]] <= 0).any(axis=None):
        raise DecompositionError("399102 alignment contains invalid prices")

    frame["stock_day5_log_return"] = np.log1p(frame.return_5d.astype(float))
    frame["market_day5_log_return"] = np.log(
        frame.market_day5_close / frame.market_entry_open
    )
    frame["stock_specific_day5_excess"] = (
        frame.stock_day5_log_return - frame.market_day5_log_return
    )
    frame["beta_adjusted_day5_excess"] = (
        frame.stock_day5_log_return
        - frame.entry_beta60.astype(float) * frame.market_day5_log_return
    )
    frame["market_day5_simple_return"] = (
        frame.market_day5_close / frame.market_entry_open - 1.0
    )
    frame["simple_day5_excess"] = frame.return_5d - frame.market_day5_simple_return
    reconstruction = np.expm1(
        frame.stock_specific_day5_excess + frame.market_day5_log_return
    )
    error = float(np.max(np.abs(reconstruction - frame.return_5d)))
    if error > 1e-12:
        raise DecompositionError("log-component additivity does not reconstruct return_5d")
    if not (
        frame.entry_execution_date < frame.day5_session_date
    ).all():
        raise DecompositionError("day-5 session does not follow entry execution")
    for column in ("extreme_winner", "winner20", "false_breakout", "severe_loss"):
        frame[column] = frame[column].astype(bool)
    audit = {
        "cycles": int(len(frame)),
        "extreme_winners": int(frame.extreme_winner.sum()),
        "fixed_control_complete": complete,
        "entry_dates_mapped": int(frame.entry_execution_date.notna().sum()),
        "day5_dates_mapped": int(frame.day5_session_date.notna().sum()),
        "index_entry_open_complete": int(frame.market_entry_open.notna().sum()),
        "index_day5_close_complete": int(frame.market_day5_close.notna().sum()),
        "duplicate_trade_ids": int(frame.trade_id.duplicated().sum()),
        "duplicate_calendar_dates": int(calendar.trade_date.duplicated().sum()),
        "duplicate_index_dates": int(index.trade_date.duplicated().sum()),
        "log_additivity_max_abs_error": error,
        "available_at_timestamp": "DAY5_SESSION_15:30_ASIA_SHANGHAI",
        "potential_action_timestamp": "NEXT_VALID_SESSION_OR_LATER_ONLY; EXPLANATORY_TEST_AUTHORIZES_NO_ACTION",
        "post_exit_prices_read": 0,
        "counterfactual_returns": 0,
        "strategy_replays": 0,
        "thresholds_or_rules_tested": 0,
    }
    return frame, audit


def partial_rank(
    frame: pd.DataFrame,
    feature: str,
    endpoint: str,
    *,
    extra_controls: tuple[str, ...],
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
    x_residual = predictor - design @ np.linalg.lstsq(design, predictor, rcond=None)[0]
    y_residual = outcome - design @ np.linalg.lstsq(design, outcome, rcond=None)[0]
    if np.std(x_residual) == 0 or np.std(y_residual) == 0:
        return result
    estimate = pearsonr(x_residual, y_residual)
    result["partial_rank_rho"] = wla.finite_or_none(estimate.statistic)
    result["p_value"] = wla.finite_or_none(estimate.pvalue)
    return result


def controlled_loyo(
    frame: pd.DataFrame,
    feature: str,
    endpoint: str,
    *,
    extra_controls: tuple[str, ...],
) -> dict[str, Any]:
    full = partial_rank(frame, feature, endpoint, extra_controls=extra_controls)
    loyo = {
        str(year): partial_rank(
            frame[frame.entry_year != year],
            feature,
            endpoint,
            extra_controls=extra_controls,
        )
        for year in range(2018, 2026)
    }
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    return {**full, "loyo": loyo, "loyo_positive_count": int(positive)}


def analyze(frame: pd.DataFrame, accepted_result: dict[str, Any]) -> dict[str, Any]:
    endpoint = "extreme_winner"
    stock = "stock_specific_day5_excess"
    market = "market_day5_log_return"
    stock_raw = wla.rank_association(frame, stock, endpoint)
    stock_controlled = controlled_loyo(
        frame, stock, endpoint, extra_controls=(market,)
    )
    market_raw = wla.rank_association(frame, market, endpoint)
    market_controlled = controlled_loyo(
        frame, market, endpoint, extra_controls=(stock,)
    )
    beta_raw = wla.rank_association(frame, "beta_adjusted_day5_excess", endpoint)
    beta_controlled = controlled_loyo(
        frame, "beta_adjusted_day5_excess", endpoint, extra_controls=(market,)
    )
    simple = wla.rank_association(frame, "simple_day5_excess", endpoint)
    total = wla.rank_association(frame, "return_5d", endpoint)
    accepted_total = accepted_result["primary"]["raw"]
    if abs(float(total["rho"]) - float(accepted_total["rho"])) > 1e-15:
        raise DecompositionError("accepted H-013 day-5 association did not reproduce")

    duration_exit = partial_rank(
        frame,
        stock,
        endpoint,
        extra_controls=(market, "holding_trading_days"),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    top4 = wla.deterministic_top_flag(frame, 4)
    ex_top4 = wla.rank_association(frame.loc[~top4], stock, endpoint)
    securities = sorted(frame.loc[frame.extreme_winner, "symbol"].astype(str).unique())
    security = wla.omit_group_sensitivity(
        frame, stock, endpoint, "symbol", securities
    )
    industry = wla.omit_group_sensitivity(
        frame[frame.entry_industry.notna()], stock, endpoint, "entry_industry"
    )
    blocks = {
        str(name): wla.safe_spearman(rows[stock], rows[endpoint])
        for name, rows in frame.groupby("baseline_block", sort=True)
    }

    stock_raw_gate = bool(
        stock_raw["rho"] is not None
        and stock_raw["rho"] >= 0.20
        and stock_raw["within_year_rank_rho"] is not None
        and stock_raw["within_year_rank_rho"] > 0
        and stock_raw["loyo_positive_count"] >= 7
    )
    stock_controlled_gate = bool(
        stock_controlled["partial_rank_rho"] is not None
        and stock_controlled["partial_rank_rho"] >= 0.20
        and stock_controlled["loyo_positive_count"] >= 7
    )
    market_gate = bool(
        market_raw["rho"] is not None
        and market_raw["rho"] >= 0.10
        and market_raw["loyo_positive_count"] >= 7
        and market_controlled["partial_rank_rho"] is not None
        and market_controlled["partial_rank_rho"] >= 0.10
        and market_controlled["loyo_positive_count"] >= 7
    )
    neighbor_gate = bool(
        beta_raw["rho"] is not None
        and beta_raw["rho"] >= 0.15
        and beta_raw["loyo_positive_count"] >= 6
        and beta_controlled["partial_rank_rho"] is not None
        and beta_controlled["partial_rank_rho"] >= 0.15
        and beta_controlled["loyo_positive_count"] >= 6
        and simple["rho"] is not None
        and simple["rho"] > 0
        and simple["loyo_positive_count"] >= 6
    )
    block_values = [value for value in blocks.values() if value is not None]
    temporal_gate = bool(
        len(block_values) == 3
        and sum(value > 0 for value in block_values) >= 2
        and min(block_values) >= -0.05
    )
    falsification_gate = bool(
        ex_top4["rho"] is not None
        and ex_top4["rho"] > 0
        and duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.10
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
    )

    stock_core = stock_raw_gate and stock_controlled_gate
    stock_full = stock_core and neighbor_gate and temporal_gate and falsification_gate
    if stock_full and not market_gate:
        decision = "DEEPEN"
        verdict = "DAY5_SEPARATION_IS_PRIMARILY_STOCK_SPECIFIC"
    elif stock_full and market_gate:
        decision = "REFINE"
        verdict = "DAY5_SEPARATION_HAS_STOCK_SPECIFIC_AND_MARKET_COMPONENTS"
    elif stock_core:
        decision = "REFINE"
        verdict = "STOCK_SPECIFIC_COMPONENT_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION"
    elif market_gate:
        decision = "PIVOT"
        verdict = "DAY5_SEPARATION_IS_PRIMARILY_CONTEMPORANEOUS_MARKET_DRIVEN"
    elif stock_raw_gate:
        decision = "PIVOT"
        verdict = "RAW_STOCK_SPECIFIC_COMPONENT_IS_REDUNDANT_OR_UNSTABLE"
    else:
        decision = "REJECT"
        verdict = "NO_STABLE_MARKET_OR_STOCK_SPECIFIC_DAY5_COMPONENT"

    return {
        "experiment_id": "EXP-D5D-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "stock_specific_raw": stock_raw,
            "stock_specific_controlled": stock_controlled,
            "market_raw": market_raw,
            "market_controlled": market_controlled,
            "beta_adjusted_raw": beta_raw,
            "beta_adjusted_controlled": beta_controlled,
            "simple_excess_neighbor": simple,
            "accepted_total_return_benchmark": total,
            "duration_exit_control": duration_exit,
            "ex_top4_pnl": ex_top4,
            "leave_one_extreme_security_out": security,
            "leave_one_industry_out": industry,
            "blocks": blocks,
            "stock_raw_gate": stock_raw_gate,
            "stock_controlled_gate": stock_controlled_gate,
            "market_gate": market_gate,
            "neighbor_gate": neighbor_gate,
            "temporal_gate": temporal_gate,
            "falsification_gate": falsification_gate,
        },
        "secondary": {
            endpoint_name: wla.rank_association(frame, stock, endpoint_name)
            for endpoint_name in (
                "winner20",
                "false_breakout",
                "severe_loss",
                "mfe",
                "round_trip_return",
            )
        },
        "strategy_modification": "NONE",
        "interpretation_boundary": (
            "Both components use post-entry information through the fifth held "
            "session and overlap arithmetically with the terminal outcome; the "
            "experiment explains H-013 but authorizes no entry, hold, or exit action"
        ),
    }


def fmt(value: Any) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.3f}"


def build_report(result: dict[str, Any], audit: dict[str, Any]) -> str:
    primary = result["primary"]
    lines = [
        "# Day-5 market-versus-stock decomposition",
        "",
        "EXP-D5D-001 decomposes the already-accepted H-013 day-5 landmark. It does not retest H-019 and does not create a holding or exit rule.",
        "",
        "## Integrity and timing",
        "",
        f"- Accepted survivors/extreme winners/control-complete: `{audit['cycles']}` / `{audit['extreme_winners']}` / `{audit['fixed_control_complete']}`.",
        "- All entry opens and exact fifth-session 399102 closes map one-to-one through the frozen calendar and anchor.",
        f"- Log-component reconstruction maximum absolute error: `{audit['log_additivity_max_abs_error']:.3g}`.",
        f"- AVAILABLE_AT_TIMESTAMP: `{audit['available_at_timestamp']}`.",
        f"- POTENTIAL_ACTION_TIMESTAMP: `{audit['potential_action_timestamp']}`.",
        "- No post-exit price, counterfactual return, threshold, replay, or strategy rule is used.",
        "",
        "## Frozen component tests",
        "",
        "| Component | Raw rho | Raw LOYO + | Controlled rho | Controlled LOYO + |",
        "|---|---:|---:|---:|---:|",
        f"| Stock-specific log excess | {fmt(primary['stock_specific_raw']['rho'])} | {primary['stock_specific_raw']['loyo_positive_count']}/8 | {fmt(primary['stock_specific_controlled']['partial_rank_rho'])} | {primary['stock_specific_controlled']['loyo_positive_count']}/8 |",
        f"| 399102 log return | {fmt(primary['market_raw']['rho'])} | {primary['market_raw']['loyo_positive_count']}/8 | {fmt(primary['market_controlled']['partial_rank_rho'])} | {primary['market_controlled']['loyo_positive_count']}/8 |",
        f"| Beta-adjusted stock excess | {fmt(primary['beta_adjusted_raw']['rho'])} | {primary['beta_adjusted_raw']['loyo_positive_count']}/8 | {fmt(primary['beta_adjusted_controlled']['partial_rank_rho'])} | {primary['beta_adjusted_controlled']['loyo_positive_count']}/8 |",
        "",
        "The stock-specific controlled test includes the contemporaneous 399102 component plus frozen pre-entry V1, market, breadth, beta, liquidity, and year state. The market controlled test conditions on the stock-specific component and the same pre-entry state.",
        "",
        "## Falsification",
        "",
        f"- Blocks: `{json.dumps(primary['blocks'], sort_keys=True)}`.",
        f"- Ex-Top4 P&L rho: `{fmt(primary['ex_top4_pnl']['rho'])}`; duration/exit partial rho: `{fmt(primary['duration_exit_control']['partial_rank_rho'])}`.",
        f"- Gates stock raw/control, market, neighbors, temporal, falsification: `{primary['stock_raw_gate']}` / `{primary['stock_controlled_gate']}` / `{primary['market_gate']}` / `{primary['neighbor_gate']}` / `{primary['temporal_gate']}` / `{primary['falsification_gate']}`.",
        "",
        "## Scientific decision",
        "",
        f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
        "",
        "The decomposition is explanatory and outcome-overlapping. It cannot establish an ex-ante predictor or authorize an entry, hold, sell, sizing, or production modification.",
        "",
    ]
    return "\n".join(lines)


def build_evidence_packet(result: dict[str, Any], audit: dict[str, Any]) -> str:
    primary = result["primary"]
    return "\n".join(
        [
            "# EXP-D5D-001 structured evidence packet",
            "",
            "## Question",
            "",
            "Does stock-specific continuation, rather than contemporaneous 399102 movement, carry the already-known H-013 day-5 extreme-winner separation?",
            "",
            "## Integrity",
            "",
            f"- Population/control complete: `{audit['cycles']}` / `{audit['fixed_control_complete']}`.",
            f"- Component reconstruction error: `{audit['log_additivity_max_abs_error']:.3g}`.",
            f"- Timing: `{audit['available_at_timestamp']}`; action no earlier than `{audit['potential_action_timestamp']}`.",
            "",
            "## Evidence",
            "",
            f"- Stock-specific raw/controlled: `{fmt(primary['stock_specific_raw']['rho'])}` / `{fmt(primary['stock_specific_controlled']['partial_rank_rho'])}`.",
            f"- Market raw/controlled: `{fmt(primary['market_raw']['rho'])}` / `{fmt(primary['market_controlled']['partial_rank_rho'])}`.",
            f"- Beta-adjusted raw/controlled: `{fmt(primary['beta_adjusted_raw']['rho'])}` / `{fmt(primary['beta_adjusted_controlled']['partial_rank_rho'])}`.",
            f"- Decision: `{result['decision']}` / `{result['mechanism_verdict']}`.",
            "",
            "## Boundary",
            "",
            "No threshold, alternate landmark, hold/exit policy, entry filter, replay, or V1 modification was tested.",
            "",
        ]
    )


def main() -> int:
    spec, identities = validate_spec()
    accepted_result = json.loads(ACCEPTED_RESULT.read_text(encoding="utf-8"))
    if accepted_result.get("experiment_id") != "EXP-PEL-001":
        raise DecompositionError("accepted H-013 result identity changed")
    frame, audit = load_frame(spec)
    result = analyze(frame, accepted_result)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_HOLDING_PATH_COMPONENT_ATTRIBUTION",
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_execution_date",
        "day5_session_date",
        "entry_year",
        "entry_industry",
        "return_5d",
        "stock_day5_log_return",
        "market_entry_open",
        "market_day5_close",
        "market_day5_log_return",
        "stock_specific_day5_excess",
        "beta_adjusted_day5_excess",
        "market_day5_simple_return",
        "simple_day5_excess",
        "extreme_winner",
        "winner20",
        "false_breakout",
        "severe_loss",
        "mfe",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
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
    atomic_write(EVIDENCE_PACKET, build_evidence_packet(result, audit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
