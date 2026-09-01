#!/usr/bin/env python3
"""Build a diagnostic, causal market-structure map for the frozen champion."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_panel.csv"
SINGLE_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_single.csv"
MAP_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_maps.csv"
PLACEMENT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_placement.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_report.md"
EXPECTED_SPEC_SHA256 = "96490dee5f4777f4ad27d1a6a7520dd61099afac8d148e4cbec0b6018fe0a567"
SEVERE = -0.10
DIMENSIONS = (
    "ABSOLUTE_MARKET_STATE",
    "CROSS_SECTIONAL_DISPERSION",
    "SYNCHRONIZATION",
    "INDUSTRY_PERSISTENCE",
)
VALUE_COLUMNS = {
    "ABSOLUTE_MARKET_STATE": "absolute_market_state",
    "CROSS_SECTIONAL_DISPERSION": "cross_sectional_dispersion",
    "SYNCHRONIZATION": "synchronization",
    "INDUSTRY_PERSISTENCE": "industry_persistence",
}
STATE_COLUMNS = {key: f"{value}_state" for key, value in VALUE_COLUMNS.items()}


class ApplicabilityMapError(RuntimeError):
    """Fail-closed Cycle 019 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise ApplicabilityMapError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE018 = _load_module(
    "cycle018_for_applicability019",
    PROGRAM / "scripts/run_ashare_opportunity_health_overlay_cycle_018.py",
)
CA = CYCLE018.CA


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ApplicabilityMapError("frozen Cycle-019 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_MARKET_STRUCTURE_OR_CHAMPION_CONDITIONAL_OUTCOMES":
        raise ApplicabilityMapError("Cycle-019 contract was not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ApplicabilityMapError(f"bound input changed: {role}")
    if spec["champion"]["changes_authorized"] is not False:
        raise ApplicabilityMapError("diagnostic contract authorizes a champion change")
    if len(spec["dimensions"]) != 4 or len(spec["maps"]) > 3:
        raise ApplicabilityMapError("feature or map budget changed")
    return spec


def _scheduled_dates(calendar: list[date], signal_dates: list[date]) -> list[date]:
    index = {value: offset for offset, value in enumerate(calendar)}
    if any(value not in index for value in signal_dates):
        raise ApplicabilityMapError("frozen signal missing from PIT calendar")
    first_index = index[signal_dates[0]]
    prehistory = [calendar[offset] for offset in range(first_index - 5, 18, -5)]
    output = sorted(set(prehistory + signal_dates))
    if len([value for value in output if value < signal_dates[0]]) < 20:
        raise ApplicabilityMapError("insufficient causal prehistory for state thresholds")
    return output


def _causal_states(
    values: pd.Series, minimum_prior_observations: int
) -> tuple[list[str | None], list[float], list[float]]:
    states: list[str | None] = []
    q1_values: list[float] = []
    q2_values: list[float] = []
    for offset, value in enumerate(values):
        prior = values.iloc[:offset].dropna()
        if len(prior) < minimum_prior_observations or pd.isna(value):
            states.append(None)
            q1_values.append(math.nan)
            q2_values.append(math.nan)
            continue
        q1, q2 = prior.quantile([1 / 3, 2 / 3]).tolist()
        states.append("LOW" if value <= q1 else "MEDIUM" if value <= q2 else "HIGH")
        q1_values.append(float(q1))
        q2_values.append(float(q2))
    return states, q1_values, q2_values


def _market_features(
    daily_paths: list[Path], signal_dates: list[date], spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=[
                    "trade_date",
                    "symbol",
                    "industry",
                    "close",
                    "preclose",
                    "hard_valid",
                    "industry_valid",
                ],
            )
            for path in daily_paths
        ],
        ignore_index=True,
    )
    frame = frame.loc[
        frame.hard_valid.astype(bool)
        & frame.industry_valid.astype(bool)
        & frame.symbol.notna()
        & frame.industry.notna()
        & frame.close.gt(0)
        & frame.preclose.gt(0)
    ].copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    frame["step_return"] = frame.close / frame.preclose - 1.0
    if (frame.step_return <= -1).any():
        raise ApplicabilityMapError("invalid causal step return")
    calendar = sorted(frame.trade_date.unique())
    scheduled = _scheduled_dates(calendar, signal_dates)
    frame = frame.sort_values(["symbol", "trade_date"])
    frame["stock_log_return"] = np.log1p(frame.step_return)
    frame["stock_return20"] = (
        frame.groupby("symbol", sort=False)
        .stock_log_return.rolling(20, min_periods=20)
        .sum()
        .reset_index(level=0, drop=True)
        .pipe(np.expm1)
    )
    daily_market = frame.groupby("trade_date", as_index=False).agg(
        median_step_return=("step_return", "median")
    )
    daily_market["market_log_return"] = np.log1p(daily_market.median_step_return)
    daily_market["absolute_market_state"] = (
        daily_market.market_log_return.rolling(20, min_periods=20).sum().pipe(np.expm1)
    )
    stock_weekly = frame.loc[frame.trade_date.isin(scheduled) & frame.stock_return20.notna()]
    stock_summary = stock_weekly.groupby("trade_date", as_index=False).agg(
        complete_stocks=("symbol", "nunique"),
        stock_p10=("stock_return20", lambda values: float(values.quantile(0.10))),
        stock_p90=("stock_return20", lambda values: float(values.quantile(0.90))),
        positive_stock_fraction=("stock_return20", lambda values: float((values > 0).mean())),
    )
    stock_summary["cross_sectional_dispersion"] = stock_summary.stock_p90 - stock_summary.stock_p10
    stock_summary["synchronization"] = (2.0 * stock_summary.positive_stock_fraction - 1.0).abs()
    industry_daily = (
        frame.groupby(["industry", "trade_date"], as_index=False)
        .agg(industry_step_return=("step_return", "mean"))
        .sort_values(["industry", "trade_date"])
    )
    industry_daily["industry_log_return"] = np.log1p(industry_daily.industry_step_return)
    industry_daily["industry_return20"] = (
        industry_daily.groupby("industry", sort=False)
        .industry_log_return.rolling(20, min_periods=20)
        .sum()
        .reset_index(level=0, drop=True)
        .pipe(np.expm1)
    )
    industry_weekly = industry_daily.loc[
        industry_daily.trade_date.isin(scheduled) & industry_daily.industry_return20.notna()
    ]
    industry_vectors = {
        key: group.set_index("industry").industry_return20
        for key, group in industry_weekly.groupby("trade_date", sort=True)
    }
    persistence_rows: list[dict[str, Any]] = []
    previous: pd.Series | None = None
    for scheduled_date in scheduled:
        current = industry_vectors.get(scheduled_date, pd.Series(dtype=float))
        common = current.index.intersection(previous.index) if previous is not None else []
        persistence = (
            float(current.loc[common].corr(previous.loc[common], method="spearman"))
            if len(common) >= spec["feature_history"]["minimum_valid_industries"]
            else math.nan
        )
        persistence_rows.append(
            {
                "trade_date": scheduled_date,
                "complete_industries": len(current),
                "common_industries": len(common),
                "industry_persistence": persistence,
            }
        )
        previous = current
    features = (
        pd.DataFrame({"trade_date": scheduled})
        .merge(daily_market[["trade_date", "absolute_market_state"]], on="trade_date", how="left")
        .merge(stock_summary, on="trade_date", how="left")
        .merge(pd.DataFrame(persistence_rows), on="trade_date", how="left")
    )
    if features.complete_stocks.min() < spec["feature_history"]["minimum_valid_stocks"]:
        raise ApplicabilityMapError("insufficient valid stock cross-section")
    if features.complete_industries.min() < spec["feature_history"]["minimum_valid_industries"]:
        raise ApplicabilityMapError("insufficient valid industry cross-section")
    for dimension, value_column in VALUE_COLUMNS.items():
        values = features[value_column]
        states, q1_values, q2_values = _causal_states(
            values, spec["feature_history"]["minimum_prior_observations"]
        )
        features[STATE_COLUMNS[dimension]] = states
        features[f"{value_column}_prior_q1"] = q1_values
        features[f"{value_column}_prior_q2"] = q2_values
    output = (
        features.loc[features.trade_date.isin(signal_dates)]
        .rename(columns={"trade_date": "signal_date"})
        .copy()
    )
    if len(output) != len(signal_dates) or output[list(STATE_COLUMNS.values())].isna().any().any():
        raise ApplicabilityMapError("causal states do not cover every frozen decision")
    output["year"] = output.signal_date.map(lambda value: value.year)
    output["block"] = np.where(output.year <= 2020, "early", "late")
    lineage = {
        "raw_rows": len(frame),
        "calendar_dates": len(calendar),
        "scheduled_feature_dates": len(scheduled),
        "pre_strategy_feature_dates": sum(value < signal_dates[0] for value in scheduled),
    }
    return output, lineage


def _outcome_panel(
    features: pd.DataFrame, trades: pd.DataFrame, industry_path: pd.DataFrame
) -> pd.DataFrame:
    cohort = trades.groupby("signal_date", as_index=False).agg(
        cohort_id=("signal_date", "first"),
        trades=("trade_id", "size"),
        absolute_trade_return=("final_net_return", "mean"),
        winner_rate=("final_net_return", lambda values: float((values > 0).mean())),
        severe_loss_rate=("final_net_return", lambda values: float((values <= SEVERE).mean())),
    )
    cohort["cohort_payoff"] = cohort.absolute_trade_return
    terminal = industry_path.loc[industry_path.checkpoint.eq(20)].copy()
    terminal["signal_date"] = pd.to_datetime(terminal.signal_date).dt.date
    proxy = terminal.groupby("signal_date", as_index=False).agg(
        selected_industry_return=("industry_return", "mean"),
        broad_proxy_return=("market_return", "mean"),
    )
    output = features.merge(cohort, on="signal_date", validate="one_to_one").merge(
        proxy, on="signal_date", validate="one_to_one"
    )
    output["relative_to_industry"] = output.cohort_payoff - output.selected_industry_return
    output["relative_to_broad"] = output.cohort_payoff - output.broad_proxy_return
    return output.sort_values("signal_date").reset_index(drop=True)


def _summary_row(group: pd.DataFrame, **labels: Any) -> dict[str, Any]:
    return {
        **labels,
        "decision_dates": int(group.signal_date.nunique()),
        "cohorts": int(group.cohort_id.nunique()),
        "trades": int(group.trades.sum()),
        "calendar_years": int(group.year.nunique()),
        "early_dates": int(group.block.eq("early").sum()),
        "late_dates": int(group.block.eq("late").sum()),
        "mean_cohort_payoff": float(group.cohort_payoff.mean()),
        "absolute_trade_return": float(
            np.average(group.absolute_trade_return, weights=group.trades)
        ),
        "selected_industry_return": float(group.selected_industry_return.mean()),
        "broad_proxy_return": float(group.broad_proxy_return.mean()),
        "relative_to_industry": float(group.relative_to_industry.mean()),
        "relative_to_broad": float(group.relative_to_broad.mean()),
        "winner_rate": float(np.average(group.winner_rate, weights=group.trades)),
        "severe_loss_rate": float(np.average(group.severe_loss_rate, weights=group.trades)),
    }


def _single_anatomy(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    decisions: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        state_column = STATE_COLUMNS[dimension]
        for state in ("LOW", "MEDIUM", "HIGH"):
            state_group = panel.loc[panel[state_column].eq(state)]
            for period in ("full", "early", "late"):
                group = (
                    state_group
                    if period == "full"
                    else state_group.loc[state_group.block.eq(period)]
                )
                rows.append(_summary_row(group, dimension=dimension, state=state, period=period))
        table = pd.DataFrame(rows)
        table = table.loc[table.dimension.eq(dimension)]
        full = table.loc[table.period.eq("full")].set_index("state")
        orientation = spec["dimensions"][dimension]["economic_orientation"]
        favorable, unfavorable = (
            ("LOW", "HIGH") if orientation.startswith("LOW") else ("HIGH", "LOW")
        )
        delta = float(
            full.loc[favorable, "mean_cohort_payoff"] - full.loc[unfavorable, "mean_cohort_payoff"]
        )
        block_deltas = {
            period: float(
                table.set_index(["state", "period"]).loc[(favorable, period), "mean_cohort_payoff"]
                - table.set_index(["state", "period"]).loc[
                    (unfavorable, period), "mean_cohort_payoff"
                ]
            )
            for period in ("early", "late")
        }
        year_directions = 0
        yearly: list[dict[str, Any]] = []
        for year, group in panel.groupby("year", sort=True):
            fav = group.loc[group[state_column].eq(favorable), "cohort_payoff"]
            unfav = group.loc[group[state_column].eq(unfavorable), "cohort_payoff"]
            year_delta = (
                float(fav.mean() - unfav.mean()) if not fav.empty and not unfav.empty else math.nan
            )
            same = bool(math.isfinite(year_delta) and year_delta > 0)
            year_directions += int(same)
            yearly.append(
                {
                    "year": int(year),
                    "low_dates": int(group[state_column].eq("LOW").sum()),
                    "medium_dates": int(group[state_column].eq("MEDIUM").sum()),
                    "high_dates": int(group[state_column].eq("HIGH").sum()),
                    "favorable_minus_unfavorable": year_delta,
                    "same_direction": same,
                }
            )
        minimum_dates = bool((full.decision_dates >= 20).all())
        same_blocks = block_deltas["early"] > 0 and block_deltas["late"] > 0
        middle = float(full.loc["MEDIUM", "mean_cohort_payoff"])
        endpoints = [
            float(full.loc["LOW", "mean_cohort_payoff"]),
            float(full.loc["HIGH", "mean_cohort_payoff"]),
        ]
        block_reversal = block_deltas["early"] * block_deltas["late"] < 0
        thresholds = spec["single_dimension_classification"]
        if (
            minimum_dates
            and delta >= thresholds["strong_minimum_favorable_minus_unfavorable_payoff"]
            and same_blocks
            and year_directions >= thresholds["strong_minimum_years_same_direction"]
        ):
            classification = "STRONG_APPLICABILITY_INFORMATION"
        elif (
            minimum_dates
            and delta >= thresholds["weak_minimum_favorable_minus_unfavorable_payoff"]
            and same_blocks
            and year_directions >= thresholds["weak_minimum_years_same_direction"]
        ):
            classification = "WEAK_APPLICABILITY_INFORMATION"
        elif block_reversal:
            classification = "CHRONOLOGICALLY_UNSTABLE"
        elif middle > max(endpoints) or middle < min(endpoints):
            classification = "NONMONOTONIC_BUT_INTERPRETABLE"
        else:
            classification = "NO_USEFUL_INFORMATION"
        decisions[dimension] = {
            "economic_orientation": orientation,
            "favorable_state": favorable,
            "unfavorable_state": unfavorable,
            "favorable_minus_unfavorable_payoff": delta,
            "block_deltas": block_deltas,
            "years_same_direction": year_directions,
            "minimum_dates_each_state": minimum_dates,
            "classification": classification,
            "yearly_distribution": yearly,
        }
    return pd.DataFrame(rows), decisions


def _map_anatomy(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    support = spec["cell_support"]
    for first, second in spec["maps"]:
        map_name = f"{first}_X_{second}"
        first_column, second_column = STATE_COLUMNS[first], STATE_COLUMNS[second]
        for (first_state, second_state), group in panel.groupby(
            [first_column, second_column], sort=True
        ):
            early = group.loc[group.block.eq("early")]
            late = group.loc[group.block.eq("late")]
            supported = bool(
                len(group) >= support["minimum_decision_dates"]
                and group.year.nunique() >= support["minimum_calendar_years"]
                and group.block.eq("early").sum() >= support["minimum_early_dates"]
                and group.block.eq("late").sum() >= support["minimum_late_dates"]
            )
            row = _summary_row(
                group,
                map=map_name,
                first_dimension=first,
                second_dimension=second,
                first_state=first_state,
                second_state=second_state,
                support="SUPPORTED" if supported else support["insufficient_label"],
            )
            row["early_mean_cohort_payoff"] = float(early.cohort_payoff.mean())
            row["late_mean_cohort_payoff"] = float(late.cohort_payoff.mean())
            rows.append(row)
        current = pd.DataFrame(rows)
        current = current.loc[current["map"].eq(map_name)]
        eligible = current.loc[current.support.eq("SUPPORTED")]
        spread = (
            float(eligible.mean_cohort_payoff.max() - eligible.mean_cohort_payoff.min())
            if len(eligible) >= 2
            else math.nan
        )
        if eligible.empty:
            best_index = worst_index = None
            early_delta = late_delta = math.nan
        else:
            best_index = eligible.mean_cohort_payoff.idxmax()
            worst_index = eligible.mean_cohort_payoff.idxmin()
            early_delta = float(
                eligible.loc[best_index, "early_mean_cohort_payoff"]
                - eligible.loc[worst_index, "early_mean_cohort_payoff"]
            )
            late_delta = float(
                eligible.loc[best_index, "late_mean_cohort_payoff"]
                - eligible.loc[worst_index, "late_mean_cohort_payoff"]
            )
        diagnostics.append(
            {
                "map": map_name,
                "supported_cells": len(eligible),
                "total_cells": len(current),
                "supported_payoff_spread": spread,
                "best_minus_worst_early": early_delta,
                "best_minus_worst_late": late_delta,
                "best_worst_order_repeats_both_blocks": bool(early_delta > 0 and late_delta > 0),
                "best_cell": (
                    f"{eligible.loc[best_index, 'first_state']}×"
                    f"{eligible.loc[best_index, 'second_state']}"
                    if best_index is not None
                    else None
                ),
                "worst_cell": (
                    f"{eligible.loc[worst_index, 'first_state']}×"
                    f"{eligible.loc[worst_index, 'second_state']}"
                    if worst_index is not None
                    else None
                ),
            }
        )
    return pd.DataFrame(rows), diagnostics


def _placement(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for year in (2018, 2022, 2023):
        group = panel.loc[panel.year.eq(year)]
        for dimension in DIMENSIONS:
            state_column = STATE_COLUMNS[dimension]
            for state in ("LOW", "MEDIUM", "HIGH"):
                cell = group.loc[group[state_column].eq(state)]
                rows.append(
                    {
                        "year": year,
                        "view": "dimension",
                        "name": dimension,
                        "cell": state,
                        "decision_dates": len(cell),
                        "mean_cohort_payoff": float(cell.cohort_payoff.mean())
                        if len(cell)
                        else math.nan,
                        "relative_to_industry": float(cell.relative_to_industry.mean())
                        if len(cell)
                        else math.nan,
                        "relative_to_broad": float(cell.relative_to_broad.mean())
                        if len(cell)
                        else math.nan,
                    }
                )
        for first, second in spec["maps"]:
            map_name = f"{first}_X_{second}"
            counts = group.groupby([STATE_COLUMNS[first], STATE_COLUMNS[second]], sort=True)
            for (first_state, second_state), cell in counts:
                rows.append(
                    {
                        "year": year,
                        "view": "map",
                        "name": map_name,
                        "cell": f"{first_state}×{second_state}",
                        "decision_dates": len(cell),
                        "mean_cohort_payoff": float(cell.cohort_payoff.mean()),
                        "relative_to_industry": float(cell.relative_to_industry.mean()),
                        "relative_to_broad": float(cell.relative_to_broad.mean()),
                    }
                )
    return pd.DataFrame(rows)


def _final_classification(
    single: dict[str, Any], maps: list[dict[str, Any]], panel: pd.DataFrame
) -> tuple[str, dict[str, Any]]:
    labels = [item["classification"] for item in single.values()]
    stable_map = any(
        item["supported_cells"] >= 3
        and item["supported_payoff_spread"] is not None
        and item["supported_payoff_spread"] >= 0.015
        and item["best_worst_order_repeats_both_blocks"]
        for item in maps
    )
    strong = "STRONG_APPLICABILITY_INFORMATION" in labels
    weak = "WEAK_APPLICABILITY_INFORMATION" in labels
    unstable = labels.count("CHRONOLOGICALLY_UNSTABLE") >= 2
    absolute_bad = panel.loc[panel.cohort_payoff < 0]
    relative_stable = bool(
        len(absolute_bad) >= 20
        and absolute_bad.relative_to_industry.mean() > 0
        and absolute_bad.relative_to_broad.mean() > 0
    )
    dominant_absolute = {
        int(year): group[STATE_COLUMNS["ABSOLUTE_MARKET_STATE"]].mode().iat[0]
        for year, group in panel.groupby("year", sort=True)
    }
    losing_years_share_adverse_absolute_state = bool(
        dominant_absolute[2018] == "LOW" and dominant_absolute[2022] == "LOW"
    )
    contrast_year_not_adverse = dominant_absolute[2023] != "LOW"
    losing_period_coverage = losing_years_share_adverse_absolute_state and contrast_year_not_adverse
    if strong and stable_map and losing_period_coverage:
        classification = "CLEAR_EX_ANTE_HABITAT"
    elif strong or weak or stable_map:
        classification = "PARTIAL_HABITAT_INFORMATION"
    elif unstable:
        classification = "CHRONOLOGICALLY_UNSTABLE"
    elif relative_stable:
        classification = "RELATIVE_ALPHA_STABLE_ABSOLUTE_REGIME_UNPREDICTABLE"
    else:
        classification = "NO_STABLE_APPLICABILITY_MAP"
    return classification, {
        "single_strong": strong,
        "single_weak": weak,
        "stable_map_spread_present": stable_map,
        "multiple_unstable_dimensions": unstable,
        "negative_cohort_dates": len(absolute_bad),
        "negative_cohort_relative_to_industry": float(absolute_bad.relative_to_industry.mean()),
        "negative_cohort_relative_to_broad": float(absolute_bad.relative_to_broad.mean()),
        "relative_selection_stable_in_negative_cohorts": relative_stable,
        "dominant_absolute_state_by_year": dominant_absolute,
        "both_losing_years_share_adverse_absolute_state": (
            losing_years_share_adverse_absolute_state
        ),
        "2023_not_dominantly_adverse_absolute_state": contrast_year_not_adverse,
        "losing_period_coverage_for_clear_habitat": losing_period_coverage,
    }


def _fmt(value: float | None) -> str:
    return "NA" if value is None or not math.isfinite(value) else f"{value:.2%}"


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Cycle 019 — champion market-structure applicability map",
        "",
        "## Executive conclusion",
        "",
        result["executive_conclusion"],
        "",
        f"Final classification: `{result['classification']}`.",
        "",
        f"- Liked structure: {result['liked_structure']}",
        f"- Disliked structure: {result['disliked_structure']}",
        f"- Causal observability: {result['observability_conclusion']}",
        f"- Deployment decision: {result['deployment_conclusion']}",
        "",
        "No champion rule, exposure, selection, lifecycle, execution, or return was changed or replayed.",
        "",
        "## Single-dimension results",
        "",
        "| Dimension | LOW / MEDIUM / HIGH dates | LOW / MEDIUM / HIGH payoff | Early / late favorable-minus-unfavorable | Classification |",
        "|---|---:|---:|---:|---|",
    ]
    rows = result["single_dimension_rows"]
    for dimension in DIMENSIONS:
        full = {
            row["state"]: row
            for row in rows
            if row["dimension"] == dimension and row["period"] == "full"
        }
        decision = result["single_dimension_decisions"][dimension]
        lines.append(
            f"| {dimension} | {full['LOW']['decision_dates']} / {full['MEDIUM']['decision_dates']} / {full['HIGH']['decision_dates']} | "
            f"{_fmt(full['LOW']['mean_cohort_payoff'])} / {_fmt(full['MEDIUM']['mean_cohort_payoff'])} / {_fmt(full['HIGH']['mean_cohort_payoff'])} | "
            f"{_fmt(decision['block_deltas']['early'])} / {_fmt(decision['block_deltas']['late'])} | `{decision['classification']}` |"
        )
    lines.extend(["", "## Yearly state distributions", ""])
    lines.extend(
        [
            "| Year | Absolute market L/M/H | Dispersion L/M/H | Synchronization L/M/H | Persistence L/M/H |",
            "|---:|---:|---:|---:|---:|",
        ]
    )
    yearly_by_dimension = {
        dimension: {
            row["year"]: row
            for row in result["single_dimension_decisions"][dimension]["yearly_distribution"]
        }
        for dimension in DIMENSIONS
    }
    for year in range(2018, 2024):
        cells = []
        for dimension in DIMENSIONS:
            row = yearly_by_dimension[dimension][year]
            cells.append(f"{row['low_dates']}/{row['medium_dates']}/{row['high_dates']}")
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    lines.extend(["", "## Two-dimensional maps", ""])
    map_rows = result["map_rows"]
    for diagnostic in result["map_diagnostics"]:
        lines.extend(
            [
                f"### {diagnostic['map']}",
                "",
                f"Supported cells: {diagnostic['supported_cells']}/{diagnostic['total_cells']}; supported payoff spread {_fmt(diagnostic['supported_payoff_spread'])}; best/worst {diagnostic['best_cell']} / {diagnostic['worst_cell']}; best-minus-worst early/late {_fmt(diagnostic['best_minus_worst_early'])}/{_fmt(diagnostic['best_minus_worst_late'])}.",
                "",
                "| Cell | Dates | Years | Early / late dates | Full / early / late payoff | Rel. industry / broad | Support |",
                "|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in map_rows:
            if row["map"] != diagnostic["map"]:
                continue
            lines.append(
                f"| {row['first_state']}×{row['second_state']} | {row['decision_dates']} | {row['calendar_years']} | "
                f"{row['early_dates']} / {row['late_dates']} | {_fmt(row['mean_cohort_payoff'])} / "
                f"{_fmt(row['early_mean_cohort_payoff'])} / {_fmt(row['late_mean_cohort_payoff'])} | "
                f"{_fmt(row['relative_to_industry'])} / {_fmt(row['relative_to_broad'])} | {row['support']} |"
            )
        lines.append("")
    lines.extend(["## 2018 / 2022 / 2023 placement", ""])
    for year, summary in result["year_placement_summary"].items():
        lines.append(
            f"- {year}: {summary['dominant_states']}; dominant primary cell {summary['dominant_primary_cell']} "
            f"({summary['dominant_primary_cell_dates']} dates); mean cohort payoff {_fmt(summary['mean_cohort_payoff'])}; "
            f"relative to industry/broad {_fmt(summary['relative_to_industry'])}/{_fmt(summary['relative_to_broad'])}."
        )
    lines.extend(["", result["year_contrast_conclusion"]])
    lines.extend(
        [
            "",
            "## Relative versus absolute Alpha",
            "",
            result["relative_absolute_conclusion"],
            "",
            "## Applicability classification",
            "",
            f"`{result['classification']}`.",
            "",
            "## Next research implication",
            "",
            result["research_implication"],
            "",
            "All evidence is consumed 2018--2023 development history. Post-2023 outcomes and CY-011 remained unread. No independent-validation, OOS, live, or production claim is made.",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    cycle018_spec = CYCLE018._load_spec()
    ca_spec = CA._load_spec()
    daily_paths, _calendar, input_identity = CA._load_market_inputs(ca_spec)
    trades = pd.read_parquet(_resolve(spec["inputs"]["cycle_016_trade_panel"]["path"]))
    trades["signal_date"] = pd.to_datetime(trades.signal_date).dt.date
    signal_dates = sorted(trades.signal_date.unique())
    features, feature_lineage = _market_features(daily_paths, signal_dates, spec)
    industry_path = pd.read_parquet(_resolve(spec["inputs"]["cycle_017_industry_path"]["path"]))
    panel = _outcome_panel(features, trades, industry_path)
    single_frame, single_decisions = _single_anatomy(panel, spec)
    map_frame, map_diagnostics = _map_anatomy(panel, spec)
    placement_frame = _placement(panel, spec)
    classification, final_diagnostics = _final_classification(
        single_decisions, map_diagnostics, panel
    )
    primary_first, primary_second = spec["maps"][0]
    year_summary: dict[str, Any] = {}
    for year in (2018, 2022, 2023):
        group = panel.loc[panel.year.eq(year)]
        state_bits = []
        for dimension in DIMENSIONS:
            state_column = STATE_COLUMNS[dimension]
            state_bits.append(f"{dimension}={group[state_column].mode().iat[0]}")
        primary = group.groupby(
            [STATE_COLUMNS[primary_first], STATE_COLUMNS[primary_second]], sort=True
        ).size()
        dominant = primary.idxmax()
        year_summary[str(year)] = {
            "dominant_states": ", ".join(state_bits),
            "dominant_primary_cell": f"{dominant[0]}×{dominant[1]}",
            "dominant_primary_cell_dates": int(primary.max()),
            "mean_cohort_payoff": float(group.cohort_payoff.mean()),
            "relative_to_industry": float(group.relative_to_industry.mean()),
            "relative_to_broad": float(group.relative_to_broad.mean()),
            "state_counts": {
                dimension: {
                    state: int(group[STATE_COLUMNS[dimension]].eq(state).sum())
                    for state in ("LOW", "MEDIUM", "HIGH")
                }
                for dimension in DIMENSIONS
            },
        }
    if classification == "CLEAR_EX_ANTE_HABITAT":
        executive = "A small, causal market structure repeatedly separates favorable and unfavorable champion economics; the map earns a separately preregistered future deployment test, but no trading rule is created here."
        implication = "A future deployment/risk-overlay experiment may be considered under a new frozen contract. Do not alter the champion from this diagnostic result."
    elif classification == "PARTIAL_HABITAT_INFORMATION":
        executive = "The four causal dimensions reveal some repeated applicability structure, but it is incomplete; the champion does not yet have a deployment-grade ex-ante habitat."
        implication = "Prioritize a second independent Alpha engine. A deployment experiment is not yet justified; dispersion Alpha remains a separate frozen research question."
    elif classification == "RELATIVE_ALPHA_STABLE_ABSOLUTE_REGIME_UNPREDICTABLE":
        executive = "The champion retains relative selection value when absolute cohorts lose, but the four causal Price–Volume dimensions do not reliably identify those periods before entry."
        implication = "Prioritize second-engine and strategy-diversification research rather than another champion timing overlay."
    elif classification == "CHRONOLOGICALLY_UNSTABLE":
        executive = "Apparent applicability relationships reverse across development blocks, so no stable ex-ante habitat is established."
        implication = "Do not time the champion from this map; prioritize a second independent Alpha engine and strategy diversification."
    else:
        executive = "No stable, economically discriminating ex-ante applicability domain is found in the four frozen market-structure dimensions."
        implication = "Prioritize second-engine and strategy-diversification research; do not open another regime-filter cycle."
    if final_diagnostics["relative_selection_stable_in_negative_cohorts"]:
        relative_absolute = "Negative absolute cohort dates still retain positive mean selection payoff relative to both selected-industry and broad proxies. The principal failure remains absolute long economics rather than loss of relative stock-selection value."
    else:
        relative_absolute = "Negative absolute cohort dates do not consistently retain relative value against both proxies; weak states affect more than market beta alone."
    liked_structure = (
        "at least medium prior absolute market conditions, with lower stock-sign "
        "synchronization providing additional selection headroom"
    )
    disliked_structure = (
        "LOW prior absolute market state; the weakest supported primary cell is LOW "
        "absolute state with MEDIUM dispersion, while 2022 also concentrates in HIGH "
        "synchronization"
    )
    observability = (
        "yes—the four values and their expanding thresholds use only completed data at "
        "the frozen weekly decision close"
    )
    deployment = (
        "not justified because 2018 does not share 2022's adverse dominant structure "
        "and dispersion is chronologically unstable"
    )
    year_contrast = (
        "2022 is distinguished from 2023 mainly by LOW versus HIGH dominant absolute "
        "market state and HIGH versus LOW dominant synchronization. Dispersion and "
        "industry persistence do not supply stable incremental separation. 2018 is "
        "economically different: it is dominated by MEDIUM absolute state and therefore "
        "prevents a complete common losing-period habitat."
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "claim_boundary": spec["claim_boundary"],
        "classification": classification,
        "executive_conclusion": executive,
        "relative_absolute_conclusion": relative_absolute,
        "research_implication": implication,
        "liked_structure": liked_structure,
        "disliked_structure": disliked_structure,
        "observability_conclusion": observability,
        "deployment_conclusion": deployment,
        "year_contrast_conclusion": year_contrast,
        "feature_lineage": feature_lineage,
        "input_identity": input_identity,
        "domain": {
            "decision_dates": len(panel),
            "trades": int(panel.trades.sum()),
            "years": sorted(panel.year.unique().tolist()),
        },
        "dimensions": spec["dimensions"],
        "state_method": spec["feature_history"],
        "single_dimension_decisions": single_decisions,
        "single_dimension_rows": single_frame.to_dict(orient="records"),
        "map_diagnostics": map_diagnostics,
        "map_rows": map_frame.to_dict(orient="records"),
        "year_placement_summary": year_summary,
        "final_diagnostics": final_diagnostics,
        "cycle_018_context": {
            "classification": json.loads(
                _resolve(spec["inputs"]["cycle_018_result"]["path"]).read_text(encoding="utf-8")
            )["classification"],
            "used_as_active_dimension": False,
        },
        "champion_changed": False,
        "overlay_or_filter_replayed": False,
        "post_2023_read": False,
        "cy011_read": False,
        "oos_claim": False,
        "cycle_018_contract_validated": cycle018_spec["experiment_id"],
    }
    _atomic_write(PANEL_PATH, panel.to_csv(index=False, lineterminator="\n", float_format="%.10g"))
    _atomic_write(
        SINGLE_PATH, single_frame.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    )
    _atomic_write(
        MAP_PATH, map_frame.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    )
    _atomic_write(
        PLACEMENT_PATH,
        placement_frame.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    _atomic_write(REPORT_PATH, _render_report(result))
    compact = [PANEL_PATH, SINGLE_PATH, MAP_PATH, PLACEMENT_PATH, REPORT_PATH]
    result["artifacts"] = {
        path.name: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
        for path in compact
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
