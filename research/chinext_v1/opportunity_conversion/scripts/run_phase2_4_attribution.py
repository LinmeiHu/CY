#!/usr/bin/env python3
"""Opportunity supply, causal entry structure, and MFE monetization attribution."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/opportunity_conversion"
PRIOR = ROOT / "research/chinext_v1/regime_attribution"
PANEL = WORK / "artifacts/trade_conversion_panel.csv"
FEATURES = PRIOR / "artifacts/daily_regime_features.parquet"
SPEC = WORK / "experiments/phase2_4_spec.json"
OUTPUT_JSON = WORK / "artifacts/phase2_4_attribution.json"
SUPPLY_CSV = WORK / "artifacts/daily_candidate_supply.csv"
ENTRY_RESULTS_CSV = WORK / "artifacts/causal_entry_feature_results.csv"
MATCHED_CSV = WORK / "artifacts/right_tail_false_breakout_matched.csv"
PATH_RESULTS_CSV = WORK / "artifacts/mfe_monetization_results.csv"
REPORT2 = WORK / "reports/phase2_opportunity_supply.md"
REPORT3 = WORK / "reports/phase3_entry_selection.md"
REPORT4 = WORK / "reports/phase4_mfe_monetization.md"

BLOCKS = {
    "EXTENDED_2018_2021": ROOT
    / "research/chinext_v1/output/chinext_v1_extended_2018_2021",
    "HOLDOUT_O0_2022_2023": ROOT
    / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE",
    "DEVELOPMENT_2024_2025": ROOT
    / "research/chinext_v1/output/chinext_v1_pit_replay",
}
EXPECTED_CANDIDATES = {
    "EXTENDED_2018_2021": 380,
    "HOLDOUT_O0_2022_2023": 266,
    "DEVELOPMENT_2024_2025": 1175,
}
EXPECTED_EVALUATIONS = {
    "EXTENDED_2018_2021": 486,
    "HOLDOUT_O0_2022_2023": 344,
    "DEVELOPMENT_2024_2025": 1324,
}
ENTRY_FEATURES = [
    "entry_rs_score",
    "entry_mom20",
    "entry_mom60",
    "entry_mom120",
    "entry_box_width",
    "entry_vol_ratio",
    "entry_minvol_location",
    "entry_minimum_volume_ratio",
    "entry_breakout_volume_ratio",
]
ENTRY_OUTCOMES = [
    "mfe",
    "opportunity20",
    "terminal_return",
    "right_tail_classification",
    "false_breakout",
    "severe_loss_classification",
]
PATH_VARIABLES = [
    "time_to_mfe_fraction",
    "pre_mfe_mae",
    "pre_peak_direction_efficiency",
    "pre_peak_positive_day_fraction",
    "pre_peak_max_drawdown",
    "holding_trading_days",
    "days_from_peak_to_exit",
    "post_peak_positive_day_fraction",
    "holding_path_mean_close_return",
    "post_peak_decay_rate",
]
CAPTURE_OUTCOMES = [
    "opportunity20_capture",
    "terminal_return",
    "positive_capture",
    "right_tail_conversion20",
    "post_mfe_giveback",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def rank_array(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def correlation(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def fisher_p_value(rho: float | None, n: int, control_rank: int) -> float | None:
    if rho is None or n <= control_rank + 3 or abs(rho) >= 1:
        return 0.0 if rho is not None and abs(rho) >= 1 else None
    z = math.atanh(rho) * math.sqrt(max(1, n - control_rank - 3))
    return math.erfc(abs(z) / math.sqrt(2.0))


def partial_spearman(
    frame: pd.DataFrame,
    x: str,
    y: str,
    *,
    year_control: bool = True,
    continuous_controls: list[str] | None = None,
) -> dict[str, Any]:
    continuous_controls = continuous_controls or []
    columns = [x, y, *continuous_controls]
    if year_control:
        columns.append("entry_year")
    data = frame[columns].dropna().copy()
    if len(data) < 4:
        return {"n": len(data), "rho": None, "p_value": None, "control_rank": 0}
    xr = rank_array(data[x].to_numpy(dtype=float))
    yr = rank_array(data[y].to_numpy(dtype=float))
    design_parts = [np.ones(len(data))]
    for control in continuous_controls:
        design_parts.append(rank_array(data[control].to_numpy(dtype=float)))
    if year_control:
        dummies = pd.get_dummies(data["entry_year"].astype(str), drop_first=True)
        if len(dummies.columns):
            design_parts.extend(
                dummies[column].to_numpy(dtype=float) for column in dummies.columns
            )
    design = np.column_stack(design_parts)
    x_residual = xr - design @ np.linalg.lstsq(design, xr, rcond=None)[0]
    y_residual = yr - design @ np.linalg.lstsq(design, yr, rcond=None)[0]
    rho = correlation(x_residual, y_residual)
    control_rank = int(np.linalg.matrix_rank(design))
    return {
        "n": int(len(data)),
        "rho": rho,
        "p_value": fisher_p_value(rho, len(data), control_rank),
        "control_rank": control_rank,
    }


def yearly_and_loyo(
    frame: pd.DataFrame,
    x: str,
    y: str,
    continuous_controls: list[str] | None = None,
) -> dict[str, Any]:
    years = sorted(int(value) for value in frame["entry_year"].dropna().unique())
    yearly: dict[str, float | None] = {}
    for year in years:
        subset = frame.loc[frame["entry_year"].eq(year)]
        row = partial_spearman(
            subset,
            x,
            y,
            year_control=False,
            continuous_controls=continuous_controls,
        )
        yearly[str(year)] = row["rho"]
    loyo: dict[str, float | None] = {}
    for omitted in years:
        subset = frame.loc[~frame["entry_year"].eq(omitted)]
        row = partial_spearman(
            subset,
            x,
            y,
            year_control=True,
            continuous_controls=continuous_controls,
        )
        loyo[str(omitted)] = row["rho"]
    valid_yearly = [value for value in yearly.values() if value is not None]
    valid_loyo = [value for value in loyo.values() if value is not None]
    return {
        "yearly": yearly,
        "yearly_positive": sum(value > 0 for value in valid_yearly),
        "yearly_negative": sum(value < 0 for value in valid_yearly),
        "yearly_valid": len(valid_yearly),
        "loyo": loyo,
        "loyo_positive": sum(value > 0 for value in valid_loyo),
        "loyo_negative": sum(value < 0 for value in valid_loyo),
        "loyo_valid": len(valid_loyo),
    }


def bh_adjust(values: list[float | None]) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    indexed = sorted(
        ((index, value) for index, value in enumerate(values) if value is not None),
        key=lambda item: float(item[1]),
    )
    count = len(indexed)
    running = 1.0
    for reverse_rank, (index, value) in enumerate(reversed(indexed), start=1):
        rank = count - reverse_rank + 1
        adjusted = min(running, float(value) * count / rank)
        running = adjusted
        result[index] = adjusted
    return result


def quantiles(values: pd.Series) -> dict[str, Any]:
    clean = values.dropna().astype(float)
    if clean.empty:
        return {"count": 0, "mean": None, "median": None, "p25": None, "p75": None, "p90": None}
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "p25": float(clean.quantile(0.25)),
        "p75": float(clean.quantile(0.75)),
        "p90": float(clean.quantile(0.90)),
    }


def build_supply_panel(features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames: list[pd.DataFrame] = []
    audit: dict[str, Any] = {}
    for block, directory in BLOCKS.items():
        nav = pd.DataFrame(read_jsonl(directory / "daily_nav.jsonl"))
        nav["trade_date"] = nav["trade_date"].astype(str)
        events = [
            row
            for row in read_jsonl(directory / "event_ledger.jsonl")
            if row.get("event") == "ENTRY_SIGNAL_EVALUATED"
        ]
        candidate_by_day: dict[str, int] = {}
        evaluation_by_day: dict[str, int] = {}
        for row in events:
            day = str(row["signal_date"])
            evaluation_by_day[day] = evaluation_by_day.get(day, 0) + 1
            minimum = row.get("minvol") or {}
            rs = row.get("rs") or {}
            if minimum.get("passed") is True and rs.get("score") is not None:
                candidate_by_day[day] = candidate_by_day.get(day, 0) + 1
        executions = read_jsonl(directory / "execution_ledger.jsonl")
        selected_by_day: dict[str, int] = {}
        for row in executions:
            if (
                row.get("status") == "FILLED"
                and row.get("side") == "BUY"
                and row.get("new_position") is True
            ):
                day = str(row["signal_date"])
                selected_by_day[day] = selected_by_day.get(day, 0) + 1
        nav["baseline_block"] = block
        nav["entry_year"] = nav["trade_date"].str[:4].astype(int)
        nav["evaluation_eligible"] = ~(
            nav["market_normal_exit"].astype(bool)
            | nav["market_emergency_exit"].astype(bool)
        )
        nav["candidate_evaluation_count"] = nav["trade_date"].map(evaluation_by_day).fillna(0).astype(int)
        nav["candidate_count"] = nav["trade_date"].map(candidate_by_day).fillna(0).astype(int)
        nav["selected_entry_count"] = nav["trade_date"].map(selected_by_day).fillna(0).astype(int)
        if (nav.loc[~nav["evaluation_eligible"], "candidate_evaluation_count"] != 0).any():
            raise RuntimeError(f"candidate evaluation occurred on market-exit day: {block}")
        if int(nav["candidate_count"].sum()) != EXPECTED_CANDIDATES[block]:
            raise RuntimeError(f"candidate count does not reconcile: {block}")
        if int(nav["candidate_evaluation_count"].sum()) != EXPECTED_EVALUATIONS[block]:
            raise RuntimeError(f"evaluation count does not reconcile: {block}")
        selected_count = int(nav["selected_entry_count"].sum())
        audit[block] = {
            "session_count": int(len(nav)),
            "evaluation_eligible_sessions": int(nav["evaluation_eligible"].sum()),
            "candidate_evaluation_count": int(nav["candidate_evaluation_count"].sum()),
            "final_candidate_count": int(nav["candidate_count"].sum()),
            "candidate_positive_sessions": int((nav["candidate_count"] > 0).sum()),
            "selected_entry_count_including_terminal_open": selected_count,
        }
        frames.append(nav)
    supply = pd.concat(frames, ignore_index=True)
    feature_columns = [
        "baseline_block",
        "trade_date",
        "eligible_count",
        "breadth_above_ma20",
        "breadth_positive_return20",
        "breadth_above_ma20_change20",
        "cross_sectional_return20_p90_p10_spread",
        "cross_sectional_return20_std",
    ]
    joined = supply.merge(
        features[feature_columns], on=["baseline_block", "trade_date"], how="left", validate="one_to_one"
    )
    if len(joined) != 1942:
        raise RuntimeError("daily supply panel must contain 1,942 sessions")
    if not np.array_equal(
        joined["basic_eligible"].to_numpy(dtype=int),
        joined["eligible_count"].to_numpy(dtype=int),
    ):
        raise RuntimeError("daily eligible count does not match frozen feature library")
    joined["candidate_count"] = joined["candidate_count"].astype(float)
    joined["candidate_rate_per_eligible"] = np.where(
        joined["eligible_count"] > 0,
        joined["candidate_count"] / joined["eligible_count"],
        np.nan,
    )
    joined["candidate_positive"] = (joined["candidate_count"] > 0).astype(float)
    eligible = joined["evaluation_eligible"]
    joined.loc[~eligible, ["candidate_count", "candidate_rate_per_eligible", "candidate_positive"]] = np.nan
    return joined, audit


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("frozen_before_execution") is not True:
        raise RuntimeError("Phase 2-4 spec is not frozen")
    panel = pd.read_csv(PANEL)
    if len(panel) != 399 or panel["trade_id"].nunique() != 399:
        raise RuntimeError("conversion panel population mismatch")
    bool_columns = [
        "right_tail_classification",
        "severe_loss_classification",
        "opportunity20",
        "opportunity50",
        "positive_capture",
        "false_breakout",
    ]
    for column in bool_columns:
        panel[column] = panel[column].map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0})
    panel["right_tail_conversion20"] = panel["right_tail_conversion20"].map(
        {True: 1.0, False: 0.0, "True": 1.0, "False": 0.0}
    )
    connection = duckdb.connect()
    features = connection.execute(
        "SELECT * FROM read_parquet(?) ORDER BY baseline_block,trade_date",
        [str(FEATURES)],
    ).fetchdf()
    connection.close()
    features["trade_date"] = features["trade_date"].astype(str)

    supply, supply_audit = build_supply_panel(features)
    atomic_csv(SUPPLY_CSV, supply)
    supply_eval = supply.loc[supply["evaluation_eligible"].eq(True)].copy()
    supply_relations: dict[str, Any] = {}
    for outcome in ("candidate_count", "candidate_rate_per_eligible", "candidate_positive"):
        primary = partial_spearman(
            supply_eval.rename(columns={"entry_year": "entry_year"}),
            "breadth_above_ma20",
            outcome,
            year_control=True,
        )
        stability = yearly_and_loyo(
            supply_eval,
            "breadth_above_ma20",
            outcome,
        )
        supply_relations[outcome] = {**primary, **stability}
    supply_eval["breadth_within_year_rank"] = supply_eval.groupby("entry_year")["breadth_above_ma20"].rank(pct=True)
    supply_eval["breadth_quintile"] = np.minimum(
        5, np.floor(supply_eval["breadth_within_year_rank"] * 5).fillna(-1).astype(int) + 1
    )
    supply_quintiles: list[dict[str, Any]] = []
    for quintile, group in supply_eval.dropna(subset=["breadth_above_ma20"]).groupby("breadth_quintile"):
        supply_quintiles.append(
            {
                "quintile": int(quintile),
                "sessions": int(len(group)),
                "mean_breadth": float(group["breadth_above_ma20"].mean()),
                "mean_candidate_count": float(group["candidate_count"].mean()),
                "candidate_positive_rate": float(group["candidate_positive"].mean()),
                "mean_candidate_rate_per_eligible": float(group["candidate_rate_per_eligible"].mean()),
                "mean_selected_entry_count": float(group["selected_entry_count"].mean()),
            }
        )
    candidate_to_selection = partial_spearman(
        supply_eval, "candidate_count", "selected_entry_count", year_control=True
    )

    trade_breadth_relations: dict[str, Any] = {}
    for outcome in (
        "mfe",
        "opportunity20",
        "opportunity50",
        "time_to_mfe_fraction",
        "terminal_return",
    ):
        primary = partial_spearman(
            panel,
            "breadth_above_ma20",
            outcome,
            year_control=True,
        )
        stability = yearly_and_loyo(panel, "breadth_above_ma20", outcome)
        trade_breadth_relations[outcome] = {**primary, **stability}
    panel["breadth_within_year_rank"] = panel.groupby("entry_year")["breadth_above_ma20"].rank(pct=True)
    panel["breadth_quintile"] = np.minimum(
        5, np.floor(panel["breadth_within_year_rank"] * 5).fillna(-1).astype(int) + 1
    )
    trade_quintiles: list[dict[str, Any]] = []
    for quintile, group in panel.dropna(subset=["breadth_above_ma20"]).groupby("breadth_quintile"):
        mfe_stats = quantiles(group["mfe"])
        trade_quintiles.append(
            {
                "quintile": int(quintile),
                "trade_count": int(len(group)),
                "mean_breadth": float(group["breadth_above_ma20"].mean()),
                "mfe_mean": mfe_stats["mean"],
                "mfe_median": mfe_stats["median"],
                "mfe_iqr": float(mfe_stats["p75"] - mfe_stats["p25"]),
                "mfe_p90": mfe_stats["p90"],
                "opportunity20_rate": float(group["opportunity20"].mean()),
                "opportunity50_rate": float(group["opportunity50"].mean()),
                "terminal_return_mean": float(group["terminal_return"].mean()),
                "terminal_return_median": float(group["terminal_return"].median()),
            }
        )

    entry_rows: list[dict[str, Any]] = []
    for feature in ENTRY_FEATURES:
        for outcome in ENTRY_OUTCOMES:
            primary = partial_spearman(
                panel,
                feature,
                outcome,
                year_control=True,
                continuous_controls=["breadth_above_ma20"],
            )
            year_only = partial_spearman(
                panel, feature, outcome, year_control=True
            )
            stability = yearly_and_loyo(
                panel,
                feature,
                outcome,
                continuous_controls=["breadth_above_ma20"],
            )
            entry_rows.append(
                {
                    "feature": feature,
                    "outcome": outcome,
                    "n": primary["n"],
                    "rho_year_breadth": primary["rho"],
                    "p_value_asymptotic": primary["p_value"],
                    "rho_year_only": year_only["rho"],
                    "yearly_positive": stability["yearly_positive"],
                    "yearly_negative": stability["yearly_negative"],
                    "yearly_valid": stability["yearly_valid"],
                    "loyo_positive": stability["loyo_positive"],
                    "loyo_negative": stability["loyo_negative"],
                    "loyo_valid": stability["loyo_valid"],
                    "yearly_json": json.dumps(stability["yearly"], sort_keys=True),
                    "loyo_json": json.dumps(stability["loyo"], sort_keys=True),
                }
            )
    q_values = bh_adjust([row["p_value_asymptotic"] for row in entry_rows])
    for row, q_value in zip(entry_rows, q_values, strict=True):
        row["bh_q_54"] = q_value
        rho = row["rho_year_breadth"]
        row["passes_preregistered_gate"] = bool(
            rho is not None
            and abs(float(rho)) >= 0.10
            and row["yearly_valid"] == 8
            and max(row["yearly_positive"], row["yearly_negative"]) >= 6
            and row["loyo_valid"] == 8
            and max(row["loyo_positive"], row["loyo_negative"]) == 8
            and q_value is not None
            and q_value <= 0.10
        )
    entry_results = pd.DataFrame(entry_rows)
    atomic_csv(ENTRY_RESULTS_CSV, entry_results)

    right_tail = panel.loc[
        panel["right_tail_classification"].eq(1) & panel["breadth_above_ma20"].notna()
    ].copy()
    false_breakout = panel.loc[
        panel["false_breakout"].eq(1) & panel["breadth_above_ma20"].notna()
    ].copy()
    matched_rows: list[dict[str, Any]] = []
    for _, winner in right_tail.iterrows():
        pool = false_breakout.loc[false_breakout["entry_year"].eq(winner["entry_year"])]
        if pool.empty:
            continue
        distances = (pool["breadth_above_ma20"] - winner["breadth_above_ma20"]).abs()
        match = pool.loc[distances.idxmin()]
        row: dict[str, Any] = {
            "right_tail_trade_id": winner["trade_id"],
            "matched_false_breakout_trade_id": match["trade_id"],
            "entry_year": int(winner["entry_year"]),
            "right_tail_breadth": float(winner["breadth_above_ma20"]),
            "false_breakout_breadth": float(match["breadth_above_ma20"]),
            "absolute_breadth_distance": float(
                abs(winner["breadth_above_ma20"] - match["breadth_above_ma20"])
            ),
        }
        for feature in ENTRY_FEATURES:
            row[f"{feature}_difference"] = float(winner[feature] - match[feature])
        matched_rows.append(row)
    matched = pd.DataFrame(matched_rows)
    atomic_csv(MATCHED_CSV, matched)
    matched_summary = {
        "pair_count": int(len(matched)),
        "unique_false_breakouts_used": int(matched["matched_false_breakout_trade_id"].nunique()),
        "breadth_distance": quantiles(matched["absolute_breadth_distance"]),
        "features": {
            feature: {
                "mean_difference": float(matched[f"{feature}_difference"].mean()),
                "median_difference": float(matched[f"{feature}_difference"].median()),
                "positive_pair_fraction": float((matched[f"{feature}_difference"] > 0).mean()),
            }
            for feature in ENTRY_FEATURES
        },
    }

    opportunities = panel.loc[panel["opportunity20"].eq(1)].copy()
    path_rows: list[dict[str, Any]] = []
    for variable in PATH_VARIABLES:
        for outcome in CAPTURE_OUTCOMES:
            primary = partial_spearman(
                opportunities,
                variable,
                outcome,
                year_control=True,
                continuous_controls=["mfe"],
            )
            stability = yearly_and_loyo(
                opportunities,
                variable,
                outcome,
                continuous_controls=["mfe"],
            )
            path_rows.append(
                {
                    "path_variable": variable,
                    "capture_outcome": outcome,
                    "n": primary["n"],
                    "rho_year_mfe": primary["rho"],
                    "p_value_asymptotic": primary["p_value"],
                    "yearly_positive": stability["yearly_positive"],
                    "yearly_negative": stability["yearly_negative"],
                    "yearly_valid": stability["yearly_valid"],
                    "loyo_positive": stability["loyo_positive"],
                    "loyo_negative": stability["loyo_negative"],
                    "loyo_valid": stability["loyo_valid"],
                    "yearly_json": json.dumps(stability["yearly"], sort_keys=True),
                    "loyo_json": json.dumps(stability["loyo"], sort_keys=True),
                }
            )
    path_q = bh_adjust([row["p_value_asymptotic"] for row in path_rows])
    for row, q_value in zip(path_rows, path_q, strict=True):
        row["bh_q_50"] = q_value
    path_results = pd.DataFrame(path_rows)
    atomic_csv(PATH_RESULTS_CSV, path_results)

    exit_groups: list[dict[str, Any]] = []
    for reason, group in opportunities.groupby("canonical_exit_reason"):
        exit_groups.append(
            {
                "canonical_exit_reason": reason,
                "count": int(len(group)),
                "years_present": int(group["entry_year"].nunique()),
                "median_mfe": float(group["mfe"].median()),
                "median_terminal_return": float(group["terminal_return"].median()),
                "median_capture": float(group["opportunity20_capture"].median()),
                "positive_capture_rate": float(group["positive_capture"].mean()),
                "right_tail_conversion_rate": float(group["right_tail_conversion20"].mean()),
                "median_post_mfe_giveback": float(group["post_mfe_giveback"].median()),
                "median_holding_days": float(group["holding_trading_days"].median()),
                "median_time_to_mfe_fraction": float(group["time_to_mfe_fraction"].median()),
            }
        )
    mfe_bands: list[dict[str, Any]] = []
    band_series = pd.cut(
        opportunities["mfe"],
        bins=[0.20, 0.50, float("inf")],
        labels=["MFE20_TO_50", "MFE_GE_50"],
        right=False,
    )
    for band, group in opportunities.groupby(band_series, observed=True):
        mfe_bands.append(
            {
                "mfe_band": str(band),
                "count": int(len(group)),
                "median_terminal_return": float(group["terminal_return"].median()),
                "median_capture": float(group["opportunity20_capture"].median()),
                "positive_capture_rate": float(group["positive_capture"].mean()),
                "right_tail_conversion_rate": float(group["right_tail_conversion20"].mean()),
                "median_post_mfe_giveback": float(group["post_mfe_giveback"].median()),
                "median_time_to_mfe_fraction": float(group["time_to_mfe_fraction"].median()),
            }
        )
    breadth_capture = {
        outcome: {
            **partial_spearman(
                opportunities,
                "breadth_above_ma20",
                outcome,
                year_control=True,
                continuous_controls=["mfe"],
            ),
            **yearly_and_loyo(
                opportunities,
                "breadth_above_ma20",
                outcome,
                continuous_controls=["mfe"],
            ),
        }
        for outcome in CAPTURE_OUTCOMES
    }

    payload = {
        "spec_id": spec["spec_id"],
        "spec_sha256": sha256_file(SPEC),
        "strategy_modified": False,
        "formal_replays": 0,
        "phase2": {
            "status": "PASS",
            "supply_audit": supply_audit,
            "supply_rows": int(len(supply)),
            "evaluation_eligible_rows": int(supply["evaluation_eligible"].sum()),
            "breadth_covered_evaluation_rows": int(
                supply_eval["breadth_above_ma20"].notna().sum()
            ),
            "supply_relations": supply_relations,
            "supply_quintiles": supply_quintiles,
            "candidate_to_selection": candidate_to_selection,
            "trade_count": int(len(panel)),
            "trade_breadth_coverage": int(panel["breadth_above_ma20"].notna().sum()),
            "trade_breadth_relations": trade_breadth_relations,
            "trade_quintiles": trade_quintiles,
        },
        "phase3": {
            "status": "PASS",
            "test_count": len(entry_rows),
            "gate_pass_count_before_extreme_sensitivity": int(
                entry_results["passes_preregistered_gate"].sum()
            ),
            "gate_pass_rows": entry_results.loc[
                entry_results["passes_preregistered_gate"].eq(True)
            ].to_dict(orient="records"),
            "matched_right_tail_false_breakout": matched_summary,
            "p_value_note": "Fisher-z asymptotic approximation on partial rank residuals; stability and effect gates remain primary",
        },
        "phase4": {
            "status": "PASS",
            "opportunity20_count": int(len(opportunities)),
            "opportunity20_breadth_coverage": int(
                opportunities["breadth_above_ma20"].notna().sum()
            ),
            "opportunity50_count": int(panel["opportunity50"].sum()),
            "mfe_bands": mfe_bands,
            "exit_groups": exit_groups,
            "breadth_capture_relations": breadth_capture,
            "path_test_count": len(path_rows),
            "path_bh_q10_count": int((path_results["bh_q_50"] <= 0.10).sum()),
            "mechanical_warning": spec["phase4"]["mechanical_warning"],
        },
        "source_hashes": {
            "panel": sha256_file(PANEL),
            "features": sha256_file(FEATURES),
            "spec": sha256_file(SPEC),
        },
    }
    atomic_write(OUTPUT_JSON, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    p2 = payload["phase2"]
    lines2 = [
        "# Phase 2 — Opportunity Supply and Quality",
        "",
        "OC-EXP-P2-001: **PASS**. No breadth threshold or overlay was tested.",
        "",
        "## Candidate-supply lineage",
        "",
        "| Block | Sessions | Evaluation sessions | Candidate evaluations | Final candidates | Candidate-positive sessions | Selected entries* |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for block, row in supply_audit.items():
        lines2.append(
            f"| {block} | {row['session_count']} | {row['evaluation_eligible_sessions']} | "
            f"{row['candidate_evaluation_count']} | {row['final_candidate_count']} | "
            f"{row['candidate_positive_sessions']} | {row['selected_entry_count_including_terminal_open']} |"
        )
    lines2 += [
        "",
        "*Selected entries include the ten terminal-open 2024-2025 cycles; all outcome analysis remains on 399 completed cycles.",
        "",
        "## Continuous breadth relationships",
        "",
        "| Quantity/quality outcome | N | year-controlled rho | Year signs + / - | LOYO + / - |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in supply_relations.items():
        lines2.append(
            f"| Daily {name} | {row['n']} | {row['rho']:.3f} | "
            f"{row['yearly_positive']} / {row['yearly_negative']} | "
            f"{row['loyo_positive']} / {row['loyo_negative']} |"
        )
    for name, row in trade_breadth_relations.items():
        rho = "NA" if row["rho"] is None else f"{row['rho']:.3f}"
        lines2.append(
            f"| Selected trade {name} | {row['n']} | {rho} | "
            f"{row['yearly_positive']} / {row['yearly_negative']} | "
            f"{row['loyo_positive']} / {row['loyo_negative']} |"
        )
    lines2 += ["", "## Within-year breadth quintiles", "", "| Q | Trades | MFE median | MFE p90 | MFE IQR | Opp20 | Opp50 | Terminal median |", "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in trade_quintiles:
        lines2.append(
            f"| {row['quintile']} | {row['trade_count']} | {row['mfe_median']:.2%} | "
            f"{row['mfe_p90']:.2%} | {row['mfe_iqr']:.2%} | {row['opportunity20_rate']:.2%} | "
            f"{row['opportunity50_rate']:.2%} | {row['terminal_return_median']:.2%} |"
        )
    lines2 += [
        "",
        "The daily supply denominator excludes market-exit days on which authoritative V1 intentionally suppresses candidate evaluation. Missing breadth is not imputed.",
    ]
    atomic_write(REPORT2, "\n".join(lines2) + "\n")

    pass_rows = entry_results.loc[entry_results["passes_preregistered_gate"].eq(True)]
    lines3 = [
        "# Phase 3 — Winner versus False Positive",
        "",
        "OC-EXP-P3-001: **PASS** as an experiment; promotion remains subject to Phase 7 extreme/top-N sensitivity.",
        "",
        f"Tested `{len(entry_rows)}` frozen causal-feature/outcome pairs. `{len(pass_rows)}` pass the preregistered effect, yearly, LOYO, and BH gates before extreme sensitivity.",
        "",
        "| Feature | Outcome | N | rho(year+breadth) | q(54) | Year + / - | LOYO + / - |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    display = entry_results.reindex(entry_results["rho_year_breadth"].abs().sort_values(ascending=False).index).head(18)
    for _, row in display.iterrows():
        lines3.append(
            f"| {row['feature']} | {row['outcome']} | {int(row['n'])} | {row['rho_year_breadth']:.3f} | "
            f"{row['bh_q_54']:.3f} | {int(row['yearly_positive'])} / {int(row['yearly_negative'])} | "
            f"{int(row['loyo_positive'])} / {int(row['loyo_negative'])} |"
        )
    lines3 += [
        "",
        f"Same-year nearest-breadth comparison formed `{matched_summary['pair_count']}` right-tail/false-breakout pairs using `{matched_summary['unique_false_breakouts_used']}` distinct false breakouts. Matching uses outcomes only for diagnosis and is not a classifier.",
        "",
        "P-values use an asymptotic Fisher-z approximation on partial rank residuals. Effect magnitude and temporal stability, not nominal significance alone, govern promotion.",
    ]
    atomic_write(REPORT3, "\n".join(lines3) + "\n")

    lines4 = [
        "# Phase 4 — MFE Monetization",
        "",
        f"OC-EXP-P4-001: **PASS** on `{len(opportunities)}` opportunity20 cycles (`{int(panel['opportunity50'].sum())}` opportunity50).",
        "",
        "## MFE bands",
        "",
        "| Band | N | Terminal median | Capture median | Positive capture | Right-tail conversion | Giveback median | Time-to-MFE fraction |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in mfe_bands:
        lines4.append(
            f"| {row['mfe_band']} | {row['count']} | {row['median_terminal_return']:.2%} | "
            f"{row['median_capture']:.2%} | {row['positive_capture_rate']:.2%} | "
            f"{row['right_tail_conversion_rate']:.2%} | {row['median_post_mfe_giveback']:.2%} | "
            f"{row['median_time_to_mfe_fraction']:.2f} |"
        )
    lines4 += [
        "",
        "## Breadth conditional on MFE magnitude and year",
        "",
        "| Outcome | N | rho | Year + / - | LOYO + / - |",
        "|---|---:|---:|---:|---:|",
    ]
    for outcome, row in breadth_capture.items():
        rho = "NA" if row["rho"] is None else f"{row['rho']:.3f}"
        lines4.append(
            f"| {outcome} | {row['n']} | {rho} | {row['yearly_positive']} / {row['yearly_negative']} | "
            f"{row['loyo_positive']} / {row['loyo_negative']} |"
        )
    lines4 += [
        "",
        "## Strongest path associations",
        "",
        "| Path variable | Capture outcome | N | rho(year+MFE) | q(50) | Year + / - | LOYO + / - |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    display_path = path_results.reindex(path_results["rho_year_mfe"].abs().sort_values(ascending=False).index).head(18)
    for _, row in display_path.iterrows():
        q = "NA" if pd.isna(row["bh_q_50"]) else f"{row['bh_q_50']:.3f}"
        lines4.append(
            f"| {row['path_variable']} | {row['capture_outcome']} | {int(row['n'])} | "
            f"{row['rho_year_mfe']:.3f} | {q} | {int(row['yearly_positive'])} / {int(row['yearly_negative'])} | "
            f"{int(row['loyo_positive'])} / {int(row['loyo_negative'])} |"
        )
    lines4 += [
        "",
        "Post-peak giveback, mean close return, and decay contain realized path information. They locate leakage but are not decision-time predictors and cannot pass the strategy gate by themselves.",
    ]
    atomic_write(REPORT4, "\n".join(lines4) + "\n")


if __name__ == "__main__":
    main()
