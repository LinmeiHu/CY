#!/usr/bin/env python3
"""Execute EXP-P6-001 winner/loss archetypes and conversion incrementality."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
SPEC = WORK / "experiments/EXP-P6-001_spec.json"
P5_SPEC = WORK / "experiments/EXP-P5-001_spec.json"
P5_TRADES = WORK / "artifacts/trade_mechanism_attribution.csv"
P5_COHORTS = WORK / "artifacts/entry_cohort_attribution.csv"
P5_RESULT = WORK / "artifacts/breadth_opportunity_conversion.json"
OUTPUT_ARCHETYPES = WORK / "artifacts/winner_severe_archetypes.csv"
OUTPUT_JSON = WORK / "artifacts/conversion_incrementality.json"
REPORT = WORK / "reports/phase6_winner_loss_conversion_mechanisms.md"

EXPECTED_SPEC = "03d79098b42433805270467cd8ce8c458cc8591fc2e8fcf84e7534541382aa7a"
EXPECTED = {
    P5_SPEC: "25806c3528fa6bf9c5657218fa26054a9ef86df24b5344602136812d644300b7",
    P5_TRADES: "2b026a4117b3b6a257085d46f2048657cbbf95df963198979f72152ef16d6b41",
    P5_COHORTS: "a2b7934bae35ce9eabc434ad0f7c00af9dcafb00b2485a5277071d0ffbd54995",
    P5_RESULT: "2bb830692d365ea37ed929bd8f6e77b6346c177cf96649df8c717f385b199912",
}

ARCHETYPES = [
    "all_cycles",
    "winner20",
    "winner50",
    "annual_top10_pnl",
    "annual_top20_pnl",
    "global_top10_pnl",
    "global_top20_pnl",
    "failed_opportunity20",
    "lost_opportunity20",
    "false_breakout",
    "severe_loss",
    "extreme_loss",
]
ENDPOINTS = {
    "capture_ratio_opportunity20": 1,
    "conversion20_within_opportunity": 1,
    "giveback_from_peak": -1,
}
CONTROLS = ["mfe", "holding_trading_days", "time_to_mfe_fraction"]
MINIMUM_CONTROLLED_SAMPLE = 50


class Phase6Error(RuntimeError):
    """Raised when a frozen Phase 6 identity or analysis contract fails."""


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


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite_or_none(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def validate_inputs() -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any], dict[str, str]]:
    if sha256_file(SPEC) != EXPECTED_SPEC:
        raise Phase6Error("EXP-P6-001 spec hash mismatch")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_ARCHETYPE_RESULT":
        raise Phase6Error("EXP-P6-001 is not frozen before results")
    identities = {str(path): sha256_file(path) for path in EXPECTED}
    mismatch = {
        str(path): {"expected": expected, "actual": identities[str(path)]}
        for path, expected in EXPECTED.items()
        if identities[str(path)] != expected
    }
    if mismatch:
        raise Phase6Error(f"Phase 6 input identity mismatch: {mismatch}")

    frame = pd.read_csv(P5_TRADES)
    if len(frame) != 399 or frame.trade_id.nunique() != 399:
        raise Phase6Error("Phase 5 trade table does not contain 399 unique cycles")
    for column in (
        "entry_signal_date",
        "entry_execution_date",
        "exit_signal_date",
        "exit_execution_date",
    ):
        frame[column] = pd.to_datetime(frame[column], errors="raise")
    if not (frame.entry_signal_date < frame.entry_execution_date).all():
        raise Phase6Error("entry signal/execution order is not strictly causal")
    if not (frame.exit_signal_date <= frame.exit_execution_date).all():
        raise Phase6Error("exit signal/execution order is invalid")
    if frame[["mfe", "mae", "round_trip_return", "realized_pnl"]].isna().any().any():
        raise Phase6Error("required frozen outcomes are missing")

    phase5 = json.loads(P5_RESULT.read_text(encoding="utf-8"))
    if phase5.get("experiment_id") != "EXP-P5-001" or phase5.get("sample_cycles") != 399:
        raise Phase6Error("Phase 5 result identity/sample mismatch")
    frame["entry_year"] = frame.entry_signal_date.dt.year
    frame["exit_year"] = frame.exit_execution_date.dt.year
    frame["time_to_mfe_fraction"] = frame.days_to_mfe / frame.holding_trading_days.clip(lower=1)
    return spec, add_fixed_archetypes(frame), phase5, identities


def deterministic_top_flag(
    frame: pd.DataFrame, n: int, group: str | None = None
) -> pd.Series:
    flag = pd.Series(False, index=frame.index, dtype=bool)
    if group is None:
        ordered = frame.sort_values(
            ["realized_pnl", "trade_id"],
            ascending=[False, True],
            kind="mergesort",
        )
        flag.loc[ordered.head(n).index] = True
        return flag
    for _, rows in frame.groupby(group, sort=True):
        ordered = rows.sort_values(
            ["realized_pnl", "trade_id"],
            ascending=[False, True],
            kind="mergesort",
        )
        flag.loc[ordered.head(n).index] = True
    return flag


def add_fixed_archetypes(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    expected = {
        "winner20": out.round_trip_return >= 0.20,
        "winner50": out.round_trip_return >= 0.50,
        "failed_opportunity20": (out.mfe >= 0.20) & (out.round_trip_return < 0.20),
        "lost_opportunity20": (out.mfe >= 0.20) & (out.round_trip_return <= 0),
        "false_breakout": (out.mfe < 0.10) & (out.round_trip_return <= 0),
        "severe_loss": out.round_trip_return <= -0.10,
        "extreme_loss": out.round_trip_return <= -0.20,
    }
    for column in ("false_breakout", "severe_loss", "extreme_loss"):
        if column in out and not out[column].astype(bool).equals(expected[column].astype(bool)):
            raise Phase6Error(f"Phase 5 {column} semantics do not match frozen Phase 6 definition")
    for column, values in expected.items():
        out[column] = values.astype(bool)
    out["annual_top10_pnl"] = deterministic_top_flag(out, 10, "exit_year")
    out["annual_top20_pnl"] = deterministic_top_flag(out, 20, "exit_year")
    out["global_top10_pnl"] = deterministic_top_flag(out, 10)
    out["global_top20_pnl"] = deterministic_top_flag(out, 20)
    out["all_cycles"] = True
    return out


def category_counts(rows: pd.DataFrame, column: str) -> str:
    values = rows[column].dropna().astype(str).value_counts()
    ordered = {key: int(values[key]) for key in sorted(values.index)}
    return json.dumps(ordered, sort_keys=True, separators=(",", ":"))


def numeric_summary(rows: pd.DataFrame, column: str, statistic: str) -> float | None:
    values = rows[column].replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    if not len(values):
        return None
    if statistic == "mean":
        return float(values.mean())
    if statistic == "median":
        return float(values.median())
    if statistic == "p25":
        return float(values.quantile(0.25))
    if statistic == "p75":
        return float(values.quantile(0.75))
    raise Phase6Error(f"unknown statistic {statistic}")


def archetype_summaries(frame: pd.DataFrame) -> pd.DataFrame:
    total = len(frame)
    positive_pnl = float(frame.realized_pnl.clip(lower=0).sum())
    records: list[dict[str, Any]] = []
    for name in ARCHETYPES:
        rows = frame[frame[name]]
        complete = rows[rows.breadth_composite.notna()]
        record: dict[str, Any] = {
            "archetype": name,
            "count": int(len(rows)),
            "cycle_share": float(len(rows) / total),
            "breadth_complete_count": int(len(complete)),
            "breadth_missing_count": int(rows.breadth_composite.isna().sum()),
            "breadth_composite_mean": numeric_summary(rows, "breadth_composite", "mean"),
            "breadth_composite_median": numeric_summary(rows, "breadth_composite", "median"),
            "breadth_composite_p25": numeric_summary(rows, "breadth_composite", "p25"),
            "breadth_composite_p75": numeric_summary(rows, "breadth_composite", "p75"),
            "mfe_mean": numeric_summary(rows, "mfe", "mean"),
            "mfe_median": numeric_summary(rows, "mfe", "median"),
            "mae_mean": numeric_summary(rows, "mae", "mean"),
            "mae_median": numeric_summary(rows, "mae", "median"),
            "round_trip_return_mean": numeric_summary(rows, "round_trip_return", "mean"),
            "round_trip_return_median": numeric_summary(rows, "round_trip_return", "median"),
            "realized_pnl_sum": float(rows.realized_pnl.sum()),
            "positive_pnl_capture": (
                float(rows.realized_pnl.clip(lower=0).sum() / positive_pnl)
                if positive_pnl > 0
                else None
            ),
            "holding_days_mean": numeric_summary(rows, "holding_trading_days", "mean"),
            "holding_days_median": numeric_summary(rows, "holding_trading_days", "median"),
            "time_to_mfe_fraction_median": numeric_summary(rows, "time_to_mfe_fraction", "median"),
            "return_5d_mean": numeric_summary(rows, "return_5d", "mean"),
            "return_5d_observed": int(rows.return_5d.notna().sum()),
            "return_10d_mean": numeric_summary(rows, "return_10d", "mean"),
            "return_10d_observed": int(rows.return_10d.notna().sum()),
            "return_20d_mean": numeric_summary(rows, "return_20d", "mean"),
            "return_20d_observed": int(rows.return_20d.notna().sum()),
            "opportunity20_rate": float(rows.opportunity20.mean()) if len(rows) else None,
            "converted20_rate": float(rows.converted20.mean()) if len(rows) else None,
            "false_breakout_rate": float(rows.false_breakout.mean()) if len(rows) else None,
            "severe_loss_rate": float(rows.severe_loss.mean()) if len(rows) else None,
            "entry_year_counts_json": category_counts(rows, "entry_year"),
            "exit_year_counts_json": category_counts(rows, "exit_year"),
            "breadth_tercile_counts_json": category_counts(rows, "breadth_tercile"),
            "exit_reason_counts_json": category_counts(rows, "canonical_exit_reason"),
        }
        records.append(record)
    return pd.DataFrame(records)


def partial_rank(
    frame: pd.DataFrame,
    endpoint: str,
    minimum: int = MINIMUM_CONTROLLED_SAMPLE,
) -> dict[str, Any]:
    columns = [
        "breadth_composite",
        endpoint,
        *CONTROLS,
        "entry_year",
        "canonical_exit_reason",
    ]
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    result: dict[str, Any] = {"n": int(len(data)), "partial_rank_rho": None, "p_value": None}
    if len(data) < minimum or data.breadth_composite.nunique() < 2 or data[endpoint].nunique() < 2:
        return result

    predictor = data.breadth_composite.rank(method="average", pct=True).to_numpy(float)
    continuous = pd.DataFrame(index=data.index)
    for control in CONTROLS:
        continuous[control] = data[control].rank(method="average", pct=True)
    if endpoint == "conversion20_within_opportunity":
        outcome = data[endpoint].to_numpy(float)
    else:
        outcome = data[endpoint].rank(method="average", pct=True).to_numpy(float)
    years = pd.get_dummies(
        data.entry_year.astype(str), prefix="year", drop_first=True, dtype=float
    )
    exits = pd.get_dummies(
        data.canonical_exit_reason.astype(str), prefix="exit", drop_first=True, dtype=float
    )
    design = np.column_stack(
        [
            np.ones(len(data)),
            continuous.to_numpy(float),
            years.to_numpy(float),
            exits.to_numpy(float),
        ]
    )
    x_residual = predictor - design @ np.linalg.lstsq(design, predictor, rcond=None)[0]
    y_residual = outcome - design @ np.linalg.lstsq(design, outcome, rcond=None)[0]
    if np.std(x_residual) == 0 or np.std(y_residual) == 0:
        return result
    estimate = pearsonr(x_residual, y_residual)
    result["partial_rank_rho"] = finite_or_none(estimate.statistic)
    result["p_value"] = finite_or_none(estimate.pvalue)
    return result


def controlled_results(frame: pd.DataFrame) -> dict[str, Any]:
    opportunity = frame[frame.opportunity20 & frame.breadth_composite.notna()].copy()
    if len(opportunity) < MINIMUM_CONTROLLED_SAMPLE:
        raise Phase6Error("complete opportunity20 sample is below the frozen minimum")
    results: dict[str, Any] = {}
    supported: list[str] = []
    for endpoint, expected_direction in ENDPOINTS.items():
        full = partial_rank(opportunity, endpoint)
        loyo: dict[str, dict[str, Any]] = {}
        for year in range(2018, 2026):
            loyo[str(year)] = partial_rank(opportunity[opportunity.entry_year != year], endpoint)
        expected_sign_count = sum(
            estimate["partial_rank_rho"] is not None
            and expected_direction * estimate["partial_rank_rho"] > 0
            for estimate in loyo.values()
        )
        passes = (
            full["partial_rank_rho"] is not None
            and expected_direction * full["partial_rank_rho"] >= 0.10
            and expected_sign_count >= 7
        )
        if passes:
            supported.append(endpoint)
        results[endpoint] = {
            **full,
            "expected_direction": expected_direction,
            "loyo": loyo,
            "loyo_expected_sign_count": int(expected_sign_count),
            "passes_incremental_support_gate": bool(passes),
        }
    return {
        "controlled_opportunity20_cycles": int(len(opportunity)),
        "control_columns": CONTROLS,
        "categorical_controls": ["entry_year", "canonical_exit_reason"],
        "endpoints": results,
        "supported_endpoints": supported,
        "incremental_conversion_support": bool(supported),
    }


def format_number(value: Any, digits: int = 3) -> str:
    number = finite_or_none(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def build_report(
    archetypes: pd.DataFrame,
    controlled: dict[str, Any],
    phase5: dict[str, Any],
    verdict: str,
) -> str:
    lines = [
        "# Phase 6 — winner/loss archetypes and conversion incrementality",
        "",
        "EXP-P6-001 consumes only the frozen Phase 5 mechanism table. It performs no replay, threshold search, overlay simulation, post-exit extension, or causal exit counterfactual.",
        "",
        "## Mechanism verdict",
        "",
        f"`{verdict}`. Breadth is not a supported downside gate; Phase 5's frozen severe-loss rho is {format_number(phase5['endpoint_attribution']['severe_loss']['rho'])} with only one negative LOYO estimate.",
        "",
        "## Fixed archetypes",
        "",
        "| Archetype | N | Breadth median | MFE mean | Return mean | P&L sum | Positive-P&L capture | Holding median |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in archetypes.to_dict("records"):
        lines.append(
            f"| {row['archetype']} | {row['count']} | {format_number(row['breadth_composite_median'])} | "
            f"{format_number(row['mfe_mean'])} | {format_number(row['round_trip_return_mean'])} | "
            f"{format_number(row['realized_pnl_sum'], 0)} | {format_number(row['positive_pnl_capture'])} | "
            f"{format_number(row['holding_days_median'], 1)} |"
        )
    lines += [
        "",
        "Archetypes overlap by construction. Annual Top-N uses exit execution year and deterministic P&L/trade-ID ordering; global Top-N spans the three independently funded baseline blocks and is descriptive only.",
        "",
        "## Fixed controlled conversion model",
        "",
        f"Complete MFE>=20% opportunity cycles: {controlled['controlled_opportunity20_cycles']}.",
        "",
        "| Endpoint | Partial rho | P-value | Expected-sign LOYO | Pass |",
        "|---|---:|---:|---:|---|",
    ]
    for endpoint, result in controlled["endpoints"].items():
        lines.append(
            f"| {endpoint} | {format_number(result['partial_rank_rho'])} | "
            f"{format_number(result['p_value'])} | {result['loyo_expected_sign_count']}/8 | "
            f"{'YES' if result['passes_incremental_support_gate'] else 'NO'} |"
        )
    lines += [
        "",
        "The identical design ranks breadth, MFE, holding duration, and time-to-MFE fraction, then controls entry-year and canonical-exit-reason fixed effects. Binary conversion remains binary. No alternate design was tried.",
        "",
        "## Interpretation boundary",
        "",
        "A surviving partial association would show residual conversion/capture information, not that an exit rule caused the return. A failure supports entry opportunity as primary only with qualification because all years are outcome-consumed and the controlled sample is small.",
        "",
        "## Strategy candidate",
        "",
        "None in Phase 6. The experiment does not authorize a gate, exposure rule, or exit adaptation.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec, frame, phase5, identities = validate_inputs()
    archetypes = archetype_summaries(frame)
    if archetypes.archetype.tolist() != ARCHETYPES:
        raise Phase6Error("archetype output ordering changed")
    archetype_text = archetypes.to_csv(index=False, lineterminator="\n", float_format="%.17g")
    atomic_write(OUTPUT_ARCHETYPES, archetype_text)
    controlled = controlled_results(frame)
    if controlled["incremental_conversion_support"]:
        verdict = "AMBIGUOUS_CONVERSION_OR_CAPTURE_RETAINS_INCREMENTAL_ASSOCIATION"
    else:
        verdict = "SUPPORTED_ENTRY_OPPORTUNITY_PRIMARY_WITH_QUALIFICATION"
    severe = phase5["endpoint_attribution"]["severe_loss"]
    negative_loyo = sum(
        value is not None and value < 0 for value in severe["loyo"].values()
    )
    payload = {
        "experiment_id": spec["experiment_id"],
        "result": "PASS",
        "evidence_grade": spec["evidence_grade"],
        "spec_sha256": EXPECTED_SPEC,
        "input_hashes": identities,
        "output_hashes": {"winner_severe_archetypes_csv": sha256_file(OUTPUT_ARCHETYPES)},
        "sample_cycles": int(len(frame)),
        "breadth_complete_cycles": int(frame.breadth_composite.notna().sum()),
        "archetype_counts": {
            row.archetype: int(row["count"]) for _, row in archetypes.iterrows()
        },
        "top_pnl_trade_ids": {
            name: frame.loc[frame[name]].sort_values(
                ["realized_pnl", "trade_id"], ascending=[False, True], kind="mergesort"
            ).trade_id.tolist()
            for name in ("global_top10_pnl", "global_top20_pnl")
        },
        "controlled_conversion": controlled,
        "downside_gate_falsification": {
            "phase5_severe_loss_rho": severe["rho"],
            "phase5_expected_negative_loyo_count": int(negative_loyo),
            "downside_gate_support": False,
            "verdict": "REJECTED_AS_DOWNSIDE_GATE",
        },
        "h8_verdict": verdict,
        "formal_strategy_replays": 0,
        "post_exit_price_rows_read": 0,
        "thresholds_optimized": 0,
        "alternative_control_sets_tested": 0,
        "overlay_simulations": 0,
    }
    atomic_write(OUTPUT_JSON, json.dumps(clean_json(payload), indent=2, sort_keys=True) + "\n")
    atomic_write(REPORT, build_report(archetypes, controlled, phase5, verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
