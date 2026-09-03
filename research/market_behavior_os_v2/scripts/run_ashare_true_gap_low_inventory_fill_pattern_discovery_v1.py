#!/usr/bin/env python3
# ruff: noqa: E501
"""Pre-2021 descriptive discovery for low-inventory downward true-gap fills.

This is deliberately not a strategy, prediction exercise, or return study.  It
starts from the frozen V6 CORE causal-first-return population, freezes a broad
low-inventory mother population without outcomes, then opens only the frozen
structural U-fill labels through 2020.  A deterministic descriptive partition
summarises in-sample regularities as at most three simple conditions and emits
an outcome-labelled chart book for human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-LOW-INVENTORY-FILL-PATTERN-DISCOVERY-V1"
SOURCE_EXPERIMENT = "ASHARE-TRUE-GAP-CAUSAL-CLUSTER-V6-ONE-SHOT-DISCOVERY"
SOURCE_SPEC_HASH = "2705011d21792acfea34c6fe07819aa1a9e6dd91247bc27e66616749cc3ee162"
AUTHORITATIVE_START_HEAD = "014390855b2e7610aaee6f15fefbf411f700c8d4"

SOURCE_SPEC = OS / f"experiments/{SOURCE_EXPERIMENT}_spec.json"
SOURCE_OUTCOMES = OS / f"artifacts/{SOURCE_EXPERIMENT}_structural_outcomes.parquet"
V8_LEDGER = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_clean_fracture_first_return_semantic_v8/semantic_ledger.parquet")
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
VAP_BINS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1/vap_session_bins.parquet")

EXT = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_low_inventory_fill_pattern_discovery_v1")
STAGE_A_LEDGER = EXT / "stage_a_low_inventory_mother_population.parquet"
DISCOVERY_LEDGER = EXT / "descriptive_discovery_ledger.parquet"
DIRECT_ANALYSIS = EXT / "direct_feature_analysis.parquet"
CHART_PATHS = EXT / "chart_daily_paths.parquet"
CHART_VAP = EXT / "chart_vap_profiles.parquet"
CHART_DIR = EXT / "signal_charts"

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
CHART_INDEX = OS / f"artifacts/{EXPERIMENT}_chart_index.csv"
CONDITION_TABLE = OS / f"artifacts/{EXPERIMENT}_simple_conditions.csv"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
PDF = ROOT / f"output/pdf/{EXPERIMENT}_signal_chart_book.pdf"

DISCOVERY_START = pd.Timestamp("2014-01-01")
DISCOVERY_END = pd.Timestamp("2020-12-31 23:59:59")
OUTCOME_HORIZONS = (5, 10, 20, 40)
PRIMARY_HORIZON = 20
PRE_GAP_SESSIONS = 120
CHART_PRE_GAP_SESSIONS = 90
CHART_POST_GAP_SESSIONS = 90
CHART_COUNT = 40
EPS = 1e-12

# Broad, outcome-blind semantic retrieval.  Density 1.0 means no more raw
# volume per unit price width than the local [L-2W,U+2W) reference region.
MAX_INSIDE_DENSITY = 1.00
MAX_CORRIDOR_DENSITY = 1.00
MAX_INSIDE_TOUCH_SESSIONS = 12
MAX_CORRIDOR_TOUCH_SESSIONS = 20

FEATURE_DIRECTIONS = {
    "collapse_leg_duration_sessions": "HIGH",
    "peak_to_gap_sessions": "HIGH",
    "collapse_drawdown": "HIGH",
    "decline_path_efficiency": "HIGH",
    "max_interim_rebound_fraction": "LOW",
    "max_depth_below_l_before_event": "HIGH",
    "gap_age_sessions": "HIGH",
    "true_gap_width_pct": "HIGH",
    "pre_gap_inside_density_relative_local": "LOW",
    "pre_gap_corridor_density_relative_local": "LOW",
    "pre_gap_inside_touch_sessions": "LOW",
    "pre_gap_corridor_touch_sessions": "LOW",
    "post_gap_freeze_corridor_float_turnover": "LOW",
    "prior_completed_session_near_touch_count": "LOW",
    "post_gap_corridor_approach_sessions": "LOW",
    "settling_sessions_after_trough": "HIGH",
    "approach_return_10d": "HIGH",
    "approach_path_efficiency_10d": "HIGH",
    "higher_low_share_10d": "HIGH",
}


class DiscoveryError(RuntimeError):
    pass


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_rank(value: str) -> str:
    return hashlib.sha256(f"{EXPERIMENT}|{value}".encode()).hexdigest()


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "PRE_2021_IN_SAMPLE_DESCRIPTIVE_PATTERN_DISCOVERY_NOT_PREDICTION_NOT_STRATEGY",
        "source": {
            "experiment": SOURCE_EXPERIMENT,
            "spec_sha256": SOURCE_SPEC_HASH,
            "population": "unchanged V6 CORE causal-first-return candidates",
            "true_gap": "High_t < Low_t_minus_1",
            "interval": "[High_t, Low_t_minus_1] = [L,U]",
            "identity_changed": False,
        },
        "chronology": {
            "discovery_start": "2014-01-01",
            "discovery_end": "2020-12-31",
            "required_complete_structural_horizon_sessions": 40,
            "2021_and_later_used": False,
        },
        "stage_a_outcome_blind_mother_population": {
            "memory": "CORE",
            "history": "exactly 120 completed same-lineage hard-valid PIT sessions with 241 one-minute bars before gap formation",
            "inside_gap_density": {"definition": "raw VAP per 0.1W bin inside z=[0,1), divided by raw VAP per 0.1W bin in z=[-2,3)", "maximum": MAX_INSIDE_DENSITY},
            "corridor_density": {"definition": "raw VAP per 0.1W bin inside z=[-0.5,1.5), divided by raw VAP per 0.1W bin in z=[-2,3)", "maximum": MAX_CORRIDOR_DENSITY},
            "maximum_pre_gap_sessions_intersecting_exact_gap": MAX_INSIDE_TOUCH_SESSIONS,
            "maximum_pre_gap_sessions_intersecting_corridor": MAX_CORRIDOR_TOUCH_SESSIONS,
            "not_hard_gated": ["collapse duration", "peak-to-gap duration", "collapse depth", "prior near-touch", "post-gap approach", "entry", "return", "PnL"],
            "missing_policy": "FAIL_CLOSED",
        },
        "stage_b_structural_outcome": {
            "source": str(SOURCE_OUTCOMES),
            "primary": "frozen structural U full-fill within 20 completed trading sessions after V6 causal first return",
            "secondary_horizons_sessions": list(OUTCOME_HORIZONS),
            "same_day_structural_fill_included": True,
            "execution_or_trading_claim": False,
            "return_or_pnl_opened": False,
        },
        "descriptive_conditions": {
            "candidate_features": FEATURE_DIRECTIONS,
            "thresholds": "full-discovery q30/q50/q70 in the predeclared economic direction; count features additionally permit natural zero",
            "selection": "greedy at most 3 conditions; each addition must improve pooled U_FILL_20 by >=2 percentage points, have positive median calendar-year uplift, retain >=40 events and >=5 represented years",
            "selector_order": "more calendar years with positive uplift; then median calendar-year uplift; then pooled uplift; then support; then deterministic feature name",
            "interpretation": "in-sample descriptive regularity only; no out-of-sample or predictive claim",
        },
        "charts": {
            "count": CHART_COUNT,
            "selection": "deterministic representative sample from simple-rule matches, preserving successes and failures where available",
            "window": "90 completed sessions before gap through max(90 sessions after gap, 40 after causal first return)",
            "marks": ["gap formation", "V6 freeze", "causal first return", "L", "U", "first U fill if within 40 sessions"],
            "outcome_visible": True,
            "returns_visible": False,
        },
        "governance": {
            "prediction_analysis_run": False,
            "strategy_backtest_run": False,
            "return_analysis_run": False,
            "2021_plus_data_used": False,
            "repository_2024_plus_data_opened": False,
        },
    }


def spec_value(contract_hash: str) -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT,
        "authoritative_start_head": AUTHORITATIVE_START_HEAD,
        "contract_sha256": contract_hash,
        "source_spec_sha256": SOURCE_SPEC_HASH,
        "mission": "From a broad pre-2021 low-inventory downward true-gap population, describe which frozen causal first returns later complete U and reduce the observed regularity to a few simple in-sample conditions for chart review.",
        "stage_order": ["FREEZE_OUTCOME_BLIND_MOTHER_POPULATION", "OPEN_PRE_2021_STRUCTURAL_FILL_ONLY", "DESCRIBE_SUCCESS_VERSUS_FAILURE", "SUMMARIZE_AT_MOST_THREE_SIMPLE_CONDITIONS", "RENDER_SIGNAL_CHART_BOOK", "STOP_FOR_HUMAN_REVIEW"],
        "prohibited": ["returns", "PnL", "trade replay", "entry/exit optimization", "predictive claim", "2021+ data", "2024+ data"],
        "contract": contract_value(),
    }


def validate_inputs() -> None:
    required = [SOURCE_SPEC, SOURCE_OUTCOMES, V8_LEDGER, DAILY, VAP_BINS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise DiscoveryError(f"missing input(s): {missing}")
    if sha256(SOURCE_SPEC) != SOURCE_SPEC_HASH:
        raise DiscoveryError("frozen V6 source spec hash mismatch")


def freeze_stage_a_contract() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    contract_hash = sha256(CONTRACT)
    write_json(SPEC, spec_value(contract_hash))
    return {"contract_sha256": contract_hash, "spec_sha256": sha256(SPEC)}


def _read_stage_a_features() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("SET threads=1")
    frame = con.execute(f"""
      SELECT *
      FROM read_parquet('{V8_LEDGER}')
      WHERE causal_first_return>=TIMESTAMP '2014-01-01'
        AND causal_first_return<TIMESTAMP '2021-01-01'
      ORDER BY causal_first_return,candidate_id
    """).fetchdf()
    con.close()
    forbidden = [c for c in frame.columns if any(token in c.lower() for token in ("pnl", "profit", "win", "u_fill", "target_hit", "mae", "mfe"))]
    if forbidden:
        raise DiscoveryError(f"outcome-like field entered Stage A: {forbidden}")
    for column in ("causal_first_return", "gap_date", "cluster_freeze_time", "local_trough_time"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.causal_first_return.max() > DISCOVERY_END:
        raise DiscoveryError("Stage A chronology boundary failure")
    return frame


def _last_2020_calendar_index() -> int:
    con = duckdb.connect()
    value = con.execute(f"SELECT max(cal_idx) FROM read_parquet('{DAILY}') WHERE trade_date<=DATE '2020-12-31'").fetchone()[0]
    con.close()
    if value is None:
        raise DiscoveryError("missing 2020 calendar endpoint")
    return int(value)


def _load_approach_features(population: pd.DataFrame) -> pd.DataFrame:
    seed = EXT / "stage_a_seed.parquet"
    write_parquet(population[["candidate_id", "symbol", "gap_cal_idx", "first_return_cal_idx", "invalid_step_cum", "local_trough_time", "L", "W"]], seed)
    con = duckdb.connect()
    con.execute("SET threads=1")
    days = con.execute(f"""
      SELECT s.candidate_id,d.trade_date,d.cal_idx,d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
        d.hard_valid,d.history_valid,d.current_valid
      FROM read_parquet('{seed}') s
      JOIN read_parquet('{DAILY}') d
        ON d.symbol=s.symbol
       AND d.invalid_step_cum=s.invalid_step_cum
       AND d.cal_idx BETWEEN s.gap_cal_idx-120 AND s.first_return_cal_idx-1
      WHERE d.trade_date<=DATE '2020-12-31'
      ORDER BY s.candidate_id,d.cal_idx
    """).fetchdf()
    con.close()
    days.trade_date = pd.to_datetime(days.trade_date)
    grouped = {key: part for key, part in days.groupby("candidate_id", sort=False)}
    rows: list[dict[str, Any]] = []
    for event in population.itertuples(index=False):
        part = grouped.get(event.candidate_id, days.iloc[0:0]).copy()
        part = part.loc[part.hard_valid.fillna(False) & part.history_valid.fillna(False) & part.current_valid.fillna(False)].sort_values("cal_idx")
        last10 = part.tail(10)
        if len(last10) >= 2:
            closes = last10.coord_close.astype(float).to_numpy()
            lows = last10.coord_low.astype(float).to_numpy()
            net = float(closes[-1] / closes[0] - 1.0)
            total = float(np.abs(np.diff(closes)).sum())
            efficiency = float(max(closes[-1] - closes[0], 0.0) / total) if total > EPS else 0.0
            higher_low = float(np.mean(np.diff(lows) > 0))
        else:
            net = math.nan
            efficiency = math.nan
            higher_low = math.nan
        trough_rows = part.loc[part.trade_date.eq(pd.Timestamp(event.local_trough_time).normalize())]
        settling = math.nan if trough_rows.empty else int(event.first_return_cal_idx - int(trough_rows.iloc[0].cal_idx))
        rows.append({
            "candidate_id": event.candidate_id,
            "settling_sessions_after_trough": settling,
            "approach_return_10d": net,
            "approach_path_efficiency_10d": efficiency,
            "higher_low_share_10d": higher_low,
        })
    return pd.DataFrame(rows)


def build_stage_a_mother_population() -> pd.DataFrame:
    frame = _read_stage_a_features()
    last_idx = _last_2020_calendar_index()
    frame["complete_h40_before_2021"] = frame.first_return_cal_idx.astype(int).add(40).le(last_idx)
    frame["gate_exact_120_history"] = frame.valid_pre_sessions.eq(PRE_GAP_SESSIONS)
    frame["gate_feature_lineage"] = frame.peak_row_available & frame.leg_path_available & frame.gap_formed_in_main_collapse_leg & frame.causal_first_return.gt(frame.cluster_freeze_time)
    frame["gate_low_inside_inventory"] = frame.pre_gap_inside_density_relative_local.le(MAX_INSIDE_DENSITY)
    frame["gate_low_corridor_inventory"] = frame.pre_gap_corridor_density_relative_local.le(MAX_CORRIDOR_DENSITY)
    frame["gate_low_inside_occupancy"] = frame.pre_gap_inside_touch_sessions.le(MAX_INSIDE_TOUCH_SESSIONS)
    frame["gate_low_corridor_occupancy"] = frame.pre_gap_corridor_touch_sessions.le(MAX_CORRIDOR_TOUCH_SESSIONS)
    gates = ["complete_h40_before_2021", "gate_exact_120_history", "gate_feature_lineage", "gate_low_inside_inventory", "gate_low_corridor_inventory", "gate_low_inside_occupancy", "gate_low_corridor_occupancy"]
    frame["low_inventory_mother_population"] = frame[gates].fillna(False).all(axis=1)
    mother = frame.loc[frame.low_inventory_mother_population].copy()
    if mother.empty:
        raise DiscoveryError("empty low-inventory mother population")
    approach = _load_approach_features(mother)
    mother = mother.merge(approach, on="candidate_id", validate="one_to_one")
    if mother.causal_first_return.max() > DISCOVERY_END:
        raise DiscoveryError("post-2020 Stage A row")
    if mother.candidate_id.duplicated().any():
        raise DiscoveryError("duplicate mother-population candidate")
    write_parquet(mother, STAGE_A_LEDGER)
    return mother


def attach_structural_outcomes(mother: pd.DataFrame) -> pd.DataFrame:
    seed = EXT / "stage_b_candidate_ids.parquet"
    write_parquet(mother[["candidate_id"]], seed)
    labels = ",".join(f"o.u_full_fill_{h}d" for h in OUTCOME_HORIZONS)
    con = duckdb.connect()
    con.execute("SET threads=1")
    outcomes = con.execute(f"""
      SELECT o.candidate_id,o.signal_date,o.signal_cal_idx,o.same_day_u_fill_time,
        CASE WHEN o.later_u_fill_cal_idx<=o.signal_cal_idx+40 THEN o.later_u_fill_cal_idx ELSE NULL END AS later_u_fill_cal_idx,
        CASE WHEN o.u_fill_offset<=40 THEN o.u_fill_offset ELSE NULL END AS u_fill_offset,
        {labels}
      FROM read_parquet('{SOURCE_OUTCOMES}') o
      JOIN read_parquet('{seed}') s USING(candidate_id)
      WHERE o.signal_date<=DATE '2020-12-31'
      ORDER BY o.signal_date,o.candidate_id
    """).fetchdf()
    con.close()
    outcomes.signal_date = pd.to_datetime(outcomes.signal_date)
    outcomes.same_day_u_fill_time = pd.to_datetime(outcomes.same_day_u_fill_time)
    if outcomes.signal_date.max() > DISCOVERY_END or len(outcomes) != len(mother):
        raise DiscoveryError("structural outcome identity/chronology failure")
    ledger = mother.merge(outcomes, on="candidate_id", how="left", validate="one_to_one")
    if ledger[[f"u_full_fill_{h}d" for h in OUTCOME_HORIZONS]].isna().any().any():
        raise DiscoveryError("missing structural fill label")
    if ledger.u_fill_offset.dropna().gt(40).any():
        raise DiscoveryError("post-H40 structural path entered discovery ledger")
    ledger["discovery_year"] = ledger.causal_first_return.dt.year
    write_parquet(ledger, DISCOVERY_LEDGER)
    return ledger


def _summarize_group(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "n": len(frame),
        "symbols": int(frame.symbol.nunique()),
        "years": int(frame.discovery_year.nunique()),
        **{f"u_fill_{h}d": float(frame[f"u_full_fill_{h}d"].mean()) for h in OUTCOME_HORIZONS},
        "median_u_fill_offset_among_40d_fills": None if not frame.u_full_fill_40d.any() else float(frame.loc[frame.u_full_fill_40d, "u_fill_offset"].median()),
    }


def direct_feature_analysis(ledger: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    target = f"u_full_fill_{PRIMARY_HORIZON}d"
    for feature in FEATURE_DIRECTIONS:
        values = pd.to_numeric(ledger[feature], errors="coerce")
        valid = ledger.loc[values.notna()].copy()
        if valid.empty or values.nunique(dropna=True) < 2:
            continue
        valid["feature_value"] = pd.to_numeric(valid[feature], errors="coerce")
        try:
            valid["quartile"] = pd.qcut(valid.feature_value.rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
        except ValueError:
            continue
        for quartile, part in valid.groupby("quartile", observed=True):
            rows.append({
                "feature": feature,
                "slice": str(quartile),
                "n": len(part),
                "feature_mean": float(part.feature_value.mean()),
                "feature_median": float(part.feature_value.median()),
                "u_fill_5d": float(part.u_full_fill_5d.mean()),
                "u_fill_10d": float(part.u_full_fill_10d.mean()),
                "u_fill_20d": float(part[target].mean()),
                "u_fill_40d": float(part.u_full_fill_40d.mean()),
            })
        success = valid.loc[valid[target]]
        failure = valid.loc[~valid[target]]
        rows.append({
            "feature": feature,
            "slice": "SUCCESS_MINUS_FAILURE",
            "n": len(valid),
            "feature_mean": float(success.feature_value.mean() - failure.feature_value.mean()) if len(success) and len(failure) else math.nan,
            "feature_median": float(success.feature_value.median() - failure.feature_value.median()) if len(success) and len(failure) else math.nan,
            "u_fill_5d": math.nan,
            "u_fill_10d": math.nan,
            "u_fill_20d": math.nan,
            "u_fill_40d": math.nan,
        })
    result = pd.DataFrame(rows)
    write_parquet(result, DIRECT_ANALYSIS)
    return result


def _condition_mask(frame: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    values = pd.to_numeric(frame[condition["feature"]], errors="coerce")
    if condition["operator"] == "<=":
        return values.notna() & values.le(float(condition["threshold"]))
    if condition["operator"] == ">=":
        return values.notna() & values.ge(float(condition["threshold"]))
    if condition["operator"] == "==":
        return values.notna() & values.eq(float(condition["threshold"]))
    raise DiscoveryError(f"unknown operator: {condition['operator']}")


def _candidate_conditions(ledger: pd.DataFrame) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    count_features = {"prior_completed_session_near_touch_count", "post_gap_corridor_approach_sessions", "pre_gap_inside_touch_sessions", "pre_gap_corridor_touch_sessions"}
    for feature, direction in FEATURE_DIRECTIONS.items():
        values = pd.to_numeric(ledger[feature], errors="coerce").dropna()
        if values.nunique() < 2:
            continue
        operator = ">=" if direction == "HIGH" else "<="
        thresholds = [(f"Q{q}", float(values.quantile(q / 100.0))) for q in (30, 50, 70)]
        if feature in count_features and values.min() <= 0 <= values.max():
            thresholds.append(("ZERO", 0.0))
        seen: set[tuple[str, float]] = set()
        for label, threshold in thresholds:
            key = (operator, round(threshold, 12))
            if key in seen:
                continue
            seen.add(key)
            result.append({"feature": feature, "operator": operator, "threshold": threshold, "threshold_source": label})
    return result


def _condition_metrics(ledger: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    target = f"u_full_fill_{PRIMARY_HORIZON}d"
    part = ledger.loc[mask]
    if part.empty:
        return {"n": 0, "years": 0, "pooled_rate": math.nan, "pooled_lift": math.nan, "median_year_lift": math.nan, "positive_year_lift_count": 0}
    base_by_year = ledger.groupby("discovery_year")[target].mean()
    selected_by_year = part.groupby("discovery_year")[target].mean()
    common = selected_by_year.index.intersection(base_by_year.index)
    lifts = selected_by_year.loc[common] - base_by_year.loc[common]
    return {
        "n": len(part),
        "years": int(part.discovery_year.nunique()),
        "pooled_rate": float(part[target].mean()),
        "pooled_lift": float(part[target].mean() - ledger[target].mean()),
        "median_year_lift": float(lifts.median()) if len(lifts) else math.nan,
        "positive_year_lift_count": int(lifts.gt(0).sum()),
    }


def discover_simple_conditions(ledger: pd.DataFrame) -> tuple[list[dict[str, Any]], pd.DataFrame, pd.Series]:
    candidates = _candidate_conditions(ledger)
    active = pd.Series(True, index=ledger.index)
    selected: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    current_rate = float(ledger[f"u_full_fill_{PRIMARY_HORIZON}d"].mean())
    for step in range(1, 4):
        evaluated: list[tuple[tuple[float, float, int, int, str], dict[str, Any], pd.Series, dict[str, Any]]] = []
        used_features = {item["feature"] for item in selected}
        for condition in candidates:
            if condition["feature"] in used_features:
                continue
            mask = active & _condition_mask(ledger, condition)
            metrics = _condition_metrics(ledger, mask)
            incremental = metrics["pooled_rate"] - current_rate if np.isfinite(metrics["pooled_rate"]) else math.nan
            eligible = metrics["n"] >= 40 and metrics["years"] >= 5 and metrics["median_year_lift"] > 0 and incremental >= 0.02
            row = {"step": step, **condition, **metrics, "incremental_rate_gain": incremental, "eligible": bool(eligible), "selected": False}
            audit_rows.append(row)
            if eligible:
                # Chronological breadth comes first so a larger one-year effect cannot
                # displace a weaker but directionally consistent observation.
                key = (metrics["positive_year_lift_count"], metrics["median_year_lift"], metrics["pooled_lift"], metrics["n"], f"{condition['feature']}|{condition['threshold_source']}")
                evaluated.append((key, condition, mask, metrics))
        if not evaluated:
            break
        _, chosen, chosen_mask, metrics = max(evaluated, key=lambda item: item[0])
        chosen = {**chosen, **metrics, "step": step}
        selected.append(chosen)
        active = chosen_mask
        current_rate = metrics["pooled_rate"]
        for row in reversed(audit_rows):
            if row["step"] == step and row["feature"] == chosen["feature"] and row["operator"] == chosen["operator"] and math.isclose(float(row["threshold"]), float(chosen["threshold"]), rel_tol=0, abs_tol=1e-12):
                row["selected"] = True
                break
    if not selected:
        # The absence of a robust simple split is itself the descriptive result.
        active = pd.Series(True, index=ledger.index)
    table = pd.DataFrame(audit_rows)
    table.to_csv(CONDITION_TABLE, index=False)
    return selected, table, active


def select_chart_sample(ledger: pd.DataFrame, rule_mask: pd.Series) -> pd.DataFrame:
    pool = ledger.loc[rule_mask].copy()
    last_idx = _last_2020_calendar_index()
    pool = pool.loc[pool.gap_cal_idx.astype(int).add(CHART_POST_GAP_SESSIONS).le(last_idx)].copy()
    if pool.empty:
        raise DiscoveryError("empty chart pool")
    pool["_rank"] = pool.candidate_id.map(stable_rank)
    pool["primary_fill"] = pool[f"u_full_fill_{PRIMARY_HORIZON}d"].astype(bool)
    selected_parts: list[pd.DataFrame] = []
    used: set[str] = set()
    # Seed every available year/board/outcome cell with one case.
    for _, part in pool.groupby(["discovery_year", "board", "primary_fill"], sort=True):
        pick = part.sort_values("_rank", kind="mergesort").head(1)
        if len(pick):
            selected_parts.append(pick)
            used.update(pick.candidate_id.astype(str))
    selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else pool.iloc[0:0]
    remaining_slots = min(CHART_COUNT, len(pool)) - len(selected)
    if remaining_slots > 0:
        remaining = pool.loc[~pool.candidate_id.isin(used)].copy()
        # Include every remaining failure up to twelve pages; failures are scarce
        # and are essential counterexamples for the human pattern review.
        failures = remaining.loc[~remaining.primary_fill].sort_values("_rank").head(min(12, remaining_slots))
        selected = pd.concat([selected, failures], ignore_index=True)
        used.update(failures.candidate_id.astype(str))
        remaining_slots = min(CHART_COUNT, len(pool)) - len(selected)
        if remaining_slots > 0:
            rest = remaining.loc[~remaining.candidate_id.isin(used)].sort_values("_rank").head(remaining_slots)
            selected = pd.concat([selected, rest], ignore_index=True)
    selected = selected.head(CHART_COUNT).sort_values(["discovery_year", "board", "candidate_id"], kind="mergesort").reset_index(drop=True)
    selected["chart_id"] = [f"LOWINV-FILL-{index:03d}" for index in range(1, len(selected) + 1)]
    selected.drop(columns=["_rank"], errors="ignore").to_csv(CHART_INDEX, index=False)
    return selected


def load_chart_data(sample: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    seed = EXT / "chart_seed.parquet"
    write_parquet(sample[["candidate_id", "symbol", "gap_cal_idx", "first_return_cal_idx", "invalid_step_cum"]], seed)
    con = duckdb.connect()
    con.execute("SET threads=1")
    paths = con.execute(f"""
      SELECT s.candidate_id,d.trade_date,d.cal_idx,d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.volume,d.hard_valid,d.history_valid,d.current_valid
      FROM read_parquet('{seed}') s
      JOIN read_parquet('{DAILY}') d
        ON d.symbol=s.symbol AND d.invalid_step_cum=s.invalid_step_cum
       AND d.cal_idx BETWEEN s.gap_cal_idx-{CHART_PRE_GAP_SESSIONS}
                         AND greatest(s.gap_cal_idx+{CHART_POST_GAP_SESSIONS},s.first_return_cal_idx+40)
      WHERE d.trade_date<=DATE '2020-12-31'
      ORDER BY s.candidate_id,d.cal_idx
    """).fetchdf()
    profiles = con.execute(f"""
      SELECT v.candidate_id,v.z_bin,
        sum(CASE WHEN v.session_offset BETWEEN -120 AND -1 THEN v.raw_volume ELSE 0 END) AS pre_raw_volume
      FROM read_parquet('{VAP_BINS}') v JOIN read_parquet('{seed}') s USING(candidate_id)
      WHERE v.trade_date<=DATE '2020-12-31' AND v.z_bin BETWEEN -20 AND 29
      GROUP BY 1,2 ORDER BY 1,2
    """).fetchdf()
    con.close()
    paths.trade_date = pd.to_datetime(paths.trade_date)
    valid = paths.hard_valid.fillna(False) & paths.history_valid.fillna(False) & paths.current_valid.fillna(False)
    paths = paths.loc[valid].copy()
    write_parquet(paths, CHART_PATHS)
    write_parquet(profiles, CHART_VAP)
    return paths, profiles


def _candles(ax: Any, frame: pd.DataFrame) -> None:
    width = 0.55
    for row in frame.itertuples(index=False):
        x = mdates.date2num(pd.Timestamp(row.trade_date).to_pydatetime())
        color = "#d62728" if row.coord_close >= row.coord_open else "#138a5b"
        ax.vlines(x, row.coord_low, row.coord_high, color=color, linewidth=0.58, alpha=0.95, zorder=3)
        bottom = min(row.coord_open, row.coord_close)
        height = abs(row.coord_close - row.coord_open)
        if height <= EPS:
            ax.hlines(row.coord_close, x - width / 2, x + width / 2, color=color, linewidth=0.8, zorder=4)
        else:
            ax.add_patch(Rectangle((x - width / 2, bottom), width, height, facecolor=color, edgecolor=color, linewidth=0.35, zorder=4))


def _condition_text(conditions: list[dict[str, Any]]) -> list[str]:
    if not conditions:
        return ["No robust additional simple condition selected"]
    return [f"{item['feature']} {item['operator']} {item['threshold']:.4g}" for item in conditions]


def render_pdf(sample: pd.DataFrame, paths: pd.DataFrame, profiles: pd.DataFrame, conditions: list[dict[str, Any]], ledger: pd.DataFrame) -> None:
    PDF.parent.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path_groups = {key: part for key, part in paths.groupby("candidate_id", sort=False)}
    profile_groups = {key: part for key, part in profiles.groupby("candidate_id", sort=False)}
    metadata = {
        "Title": f"{EXPERIMENT} signal chart book",
        "Author": "CY Market Behavior OS",
        "Subject": "Pre-2021 in-sample descriptive structural U-fill review; no returns",
        "Keywords": "A-share,true-gap,low-inventory,structural-fill,descriptive",
        "CreationDate": datetime(2000, 1, 1, tzinfo=UTC),
        "ModDate": datetime(2000, 1, 1, tzinfo=UTC),
    }
    with PdfPages(PDF, metadata=metadata) as pdf:
        fig = plt.figure(figsize=(15.5, 8.7), facecolor="white")
        fig.text(0.06, 0.88, "Low-inventory downward true-gap fill patterns", fontsize=25, fontweight="bold")
        fig.text(0.06, 0.82, "2014–2020 descriptive discovery • structural U fill only • no return / trade / prediction claim", fontsize=13, color="#444444")
        mother = _summarize_group(ledger)
        rule = _summarize_group(ledger.loc[ledger.descriptive_rule_match])
        lines = [
            f"Broad low-inventory mother population: {mother['n']} events / {mother['symbols']} symbols",
            f"Mother U-fill rates: 5D {mother['u_fill_5d']:.1%} | 10D {mother['u_fill_10d']:.1%} | 20D {mother['u_fill_20d']:.1%} | 40D {mother['u_fill_40d']:.1%}",
            f"Simple-condition match: {rule['n']} events / {rule['symbols']} symbols",
            f"Matched U-fill rates: 5D {rule['u_fill_5d']:.1%} | 10D {rule['u_fill_10d']:.1%} | 20D {rule['u_fill_20d']:.1%} | 40D {rule['u_fill_40d']:.1%}",
            "",
            "Descriptive conditions (discovered in-sample):",
            *[f"  {index}. {line}" for index, line in enumerate(_condition_text(conditions), 1)],
            "",
            f"Chart pages: {len(sample)} deterministic examples from condition matches; successes and failures are both shown.",
            "Each page spans 90 sessions before the gap through at least 90 sessions after it and 40 sessions after first return.",
            "Orange band = true gap [L,U]; grey band = surrounding inventory corridor [L−0.5W,U+0.5W).",
            "Fill means price structurally reached U; it is not an executable trade result.",
        ]
        fig.text(0.07, 0.72, "\n".join(lines), fontsize=12, va="top", linespacing=1.55, family="DejaVu Sans")
        fig.text(0.06, 0.05, "2021 and later are not used. Stop after human review; optimise later only under a separate freeze.", fontsize=11, color="#8b0000")
        pdf.savefig(fig, facecolor="white")
        plt.close(fig)

        for event in sample.itertuples(index=False):
            days = path_groups.get(event.candidate_id, paths.iloc[0:0]).sort_values("cal_idx", kind="mergesort")
            profile = profile_groups.get(event.candidate_id, profiles.iloc[0:0]).copy()
            if days.empty:
                raise DiscoveryError(f"missing chart path: {event.candidate_id}")
            fill_date = pd.NaT
            if pd.notna(event.same_day_u_fill_time):
                fill_date = pd.Timestamp(event.same_day_u_fill_time)
            elif pd.notna(event.later_u_fill_cal_idx):
                row = days.loc[days.cal_idx.eq(int(event.later_u_fill_cal_idx))]
                if not row.empty:
                    fill_date = pd.Timestamp(row.iloc[0].trade_date)

            fig = plt.figure(figsize=(15.5, 8.7), facecolor="white")
            grid = fig.add_gridspec(
                2,
                2,
                width_ratios=[6.8, 1.35],
                height_ratios=[4.8, 1.1],
                left=0.045,
                right=0.985,
                bottom=0.105,
                top=0.865,
                wspace=0.045,
                hspace=0.04,
            )
            ax = fig.add_subplot(grid[0, 0])
            vol = fig.add_subplot(grid[1, 0], sharex=ax)
            vap_ax = fig.add_subplot(grid[:, 1], sharey=ax)
            _candles(ax, days)
            for axis in (ax, vap_ax):
                axis.axhspan(event.L - 0.5 * event.W, event.U + 0.5 * event.W, color="#9e9e9e", alpha=0.10, zorder=0)
                axis.axhspan(event.L, event.U, color="#ff9800", alpha=0.24, zorder=1)
                axis.axhline(event.L, color="#d95f02", linestyle="--", linewidth=1.0)
                axis.axhline(event.U, color="#d95f02", linestyle="--", linewidth=1.0)

            gap_time = pd.Timestamp(event.gap_date)
            freeze_time = pd.Timestamp(event.cluster_freeze_time)
            return_time = pd.Timestamp(event.causal_first_return)
            ax.axvline(gap_time, color="#e31a1c", linewidth=1.2)
            ax.axvline(freeze_time, color="#1f78b4", linewidth=1.0, linestyle="--")
            ax.axvline(return_time, color="#6a3d9a", linewidth=1.2, linestyle=":")
            ax.scatter(return_time, event.L, marker="^", s=70, color="#6a3d9a", zorder=9)
            if pd.notna(fill_date) and bool(event.u_full_fill_40d):
                ax.axvline(fill_date, color="#087830", linewidth=1.1, linestyle="-.")
                ax.scatter(fill_date, event.U, marker="*", s=110, color="#087830", zorder=10)
                ax.annotate(f"first U fill\n{fill_date.date().isoformat()} / +{int(event.u_fill_offset)} sessions", (fill_date, event.U), xytext=(5, 10), textcoords="offset points", fontsize=8, color="#087830")
            ax.text(gap_time, 0.98, f"gap\n{gap_time.date().isoformat()}", transform=ax.get_xaxis_transform(), rotation=90, va="top", ha="right", fontsize=7, color="#b2182b")
            ax.text(freeze_time, 0.98, f"freeze\n{freeze_time.date().isoformat()}", transform=ax.get_xaxis_transform(), rotation=90, va="top", ha="right", fontsize=7, color="#2166ac")
            ax.text(return_time, 0.98, f"first return\n{return_time.date().isoformat()}", transform=ax.get_xaxis_transform(), rotation=90, va="top", ha="right", fontsize=7, color="#54278f")

            volume = days.volume.astype(float)
            colors = np.where(days.coord_close >= days.coord_open, "#d62728", "#138a5b")
            vol.bar(days.trade_date, volume / 1e6, width=0.7, color=colors, alpha=0.55)
            vol.set_ylabel("Volume (m)", fontsize=8)
            vol.grid(axis="y", alpha=0.18)
            if not profile.empty:
                y = event.L + (profile.z_bin.astype(float) + 0.5) * 0.10 * event.W
                values = profile.pre_raw_volume.astype(float)
                vap_ax.barh(y, values / max(float(values.max()), EPS), height=0.085 * event.W, color="#4c78a8", alpha=0.75)
            vap_ax.set_title("Raw VAP\n120 sessions pre-gap", fontsize=10)
            vap_ax.set_xlim(left=0)
            vap_ax.tick_params(axis="y", labelleft=False)
            vap_ax.grid(axis="x", alpha=0.18)

            ax.set_xlim(days.trade_date.min() - pd.Timedelta(days=3), days.trade_date.max() + pd.Timedelta(days=3))
            lo = min(float(days.coord_low.min()), float(event.L - 2 * event.W))
            hi = max(float(days.coord_high.max()), float(event.U + 2 * event.W))
            pad = max((hi - lo) * 0.06, float(event.W))
            ax.set_ylim(lo - pad, hi + pad)
            ax.set_ylabel("QD-010 comparable price")
            ax.grid(alpha=0.18)
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=12))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            plt.setp(ax.get_xticklabels(), visible=False)
            vol.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=12))
            vol.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            plt.setp(vol.get_xticklabels(), rotation=28, ha="right", fontsize=8)
            ax.annotate(f"U={event.U:.4f}", (days.trade_date.min(), event.U), xytext=(3, 2), textcoords="offset points", fontsize=8, color="#a63603")
            ax.annotate(f"L={event.L:.4f}", (days.trade_date.min(), event.L), xytext=(3, -11), textcoords="offset points", fontsize=8, color="#a63603")

            outcome = "U FILL <=20D" if event.u_full_fill_20d else ("U FILL 21–40D" if event.u_full_fill_40d else "NO U FILL <=40D")
            outcome_color = "#087830" if event.u_full_fill_20d else ("#a66b00" if event.u_full_fill_40d else "#b2182b")
            fig.suptitle(
                f"{event.chart_id} | {event.symbol} | {event.board} | {outcome}",
                fontsize=15,
                fontweight="bold",
                color=outcome_color,
                y=0.995,
            )
            facts = (
                f"Gap {gap_time.date()}  [L,U]=[{event.L:.4f},{event.U:.4f}]  width={event.true_gap_width_pct:.2%}   "
                f"first return {return_time.date()}  age={int(event.gap_age_sessions)} sessions\n"
                f"pre-gap density: exact={event.pre_gap_inside_density_relative_local:.2f}, corridor={event.pre_gap_corridor_density_relative_local:.2f}   "
                f"touch sessions: exact={int(event.pre_gap_inside_touch_sessions)}, corridor={int(event.pre_gap_corridor_touch_sessions)}   "
                f"collapse: peak→gap={int(event.peak_to_gap_sessions)}, duration={int(event.collapse_leg_duration_sessions)}, depth={event.collapse_drawdown:.1%}   "
                f"prior near-touch={int(event.prior_completed_session_near_touch_count)}"
            )
            fig.text(0.015, 0.935, facts, fontsize=8.6, va="top", linespacing=1.35)
            legend = [
                Rectangle((0, 0), 1, 1, facecolor="#ff9800", alpha=0.24, label="true gap [L,U]"),
                Rectangle((0, 0), 1, 1, facecolor="#9e9e9e", alpha=0.10, label="inventory corridor [L−0.5W,U+0.5W)"),
                plt.Line2D([0], [0], color="#e31a1c", label="gap formation"),
                plt.Line2D([0], [0], color="#6a3d9a", linestyle=":", label="causal first return"),
            ]
            if pd.notna(fill_date) and bool(event.u_full_fill_40d):
                legend.append(plt.Line2D([0], [0], marker="*", color="#087830", linestyle="None", label="first structural U fill"))
            ax.legend(handles=legend, loc="best", fontsize=8)
            fig.text(0.01, 0.018, "Structural price-path outcome only. No entry, exit, cost, return, PnL, or predictive claim.", fontsize=8, color="#555555")
            png = CHART_DIR / f"{event.chart_id}_{event.symbol}.png"
            fig.savefig(png, dpi=145, bbox_inches="tight", facecolor="white")
            pdf.savefig(fig, dpi=145, facecolor="white")
            plt.close(fig)


def summarize(ledger: pd.DataFrame, conditions: list[dict[str, Any]], condition_table: pd.DataFrame, sample: pd.DataFrame, hashes: dict[str, str]) -> dict[str, Any]:
    rule = ledger.loc[ledger.descriptive_rule_match]
    stable_splits = (
        condition_table.loc[(condition_table.step == 1) & condition_table.eligible]
        .sort_values(["positive_year_lift_count", "median_year_lift", "pooled_lift", "n"], ascending=False)
        .head(8)
        .to_dict("records")
    )
    contrast_features = [
        "post_gap_freeze_corridor_float_turnover",
        "higher_low_share_10d",
        "collapse_leg_duration_sessions",
        "peak_to_gap_sessions",
        "collapse_drawdown",
        "true_gap_width_pct",
        "prior_completed_session_near_touch_count",
    ]
    contrasts = {}
    for feature in contrast_features:
        success = pd.to_numeric(ledger.loc[ledger.u_full_fill_20d, feature], errors="coerce")
        failure = pd.to_numeric(ledger.loc[~ledger.u_full_fill_20d, feature], errors="coerce")
        contrasts[feature] = {
            "success_median": float(success.median()),
            "failure_median": float(failure.median()),
            "success_mean": float(success.mean()),
            "failure_mean": float(failure.mean()),
        }
    yearly = []
    for year, base in ledger.groupby("discovery_year", sort=True):
        chosen = rule.loc[rule.discovery_year.eq(year)]
        yearly.append({"year": int(year), "mother": _summarize_group(base), "simple_rule": _summarize_group(chosen) if len(chosen) else {"n": 0}})
    result = {
        "experiment": EXPERIMENT,
        "status": "STOPPED_FOR_HUMAN_PATTERN_REVIEW",
        "scientific_interpretation": "PRE_2021_IN_SAMPLE_DESCRIPTIVE_ONLY",
        "hashes": hashes,
        "mother_population": _summarize_group(ledger),
        "simple_conditions": conditions,
        "simple_rule_population": _summarize_group(rule),
        "top_stable_univariate_splits": stable_splits,
        "success_failure_feature_contrasts": contrasts,
        "yearly": yearly,
        "board": {str(board): {"mother": _summarize_group(part), "simple_rule": _summarize_group(rule.loc[rule.board.eq(board)]) if (rule.board == board).any() else {"n": 0}} for board, part in ledger.groupby("board")},
        "condition_candidates_evaluated": len(condition_table),
        "chart_book": {"pages": len(sample) + 1, "signal_charts": len(sample), "success_20d": int(sample.u_full_fill_20d.sum()), "success_40d": int(sample.u_full_fill_40d.sum()), "pdf": str(PDF)},
        "audit": {
            "V6_EVENT_IDENTITY_CHANGED_COUNT": 0,
            "MOTHER_POPULATION_SELECTED_WITH_OUTCOME_COUNT": 0,
            "FEATURE_USES_POST_FIRST_RETURN_INFORMATION_COUNT": 0,
            "STRUCTURAL_PATH_AFTER_H40_USED_COUNT": int(ledger.u_fill_offset.dropna().gt(40).sum()),
            "RETURN_ANALYSIS_RUN": "NO",
            "STRATEGY_BACKTEST_RUN": "NO",
            "PREDICTIVE_VALIDATION_RUN": "NO",
            "DATA_2021_OR_LATER_USED": "NO",
            "REPOSITORY_2024_PLUS_DATA_OPENED": "NO",
        },
        "next": "Human review of the chart book, then separately freeze any semantic correction or predictive test.",
    }
    result["hashes"].update({
        "stage_a_ledger_sha256": sha256(STAGE_A_LEDGER),
        "discovery_ledger_sha256": sha256(DISCOVERY_LEDGER),
        "direct_analysis_sha256": sha256(DIRECT_ANALYSIS),
        "condition_table_sha256": sha256(CONDITION_TABLE),
        "chart_index_sha256": sha256(CHART_INDEX),
        "pdf_sha256": sha256(PDF),
    })
    return result


def write_report(result: dict[str, Any]) -> None:
    mother = result["mother_population"]
    rule = result["simple_rule_population"]
    conditions = result["simple_conditions"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Status",
        "",
        "`STOPPED_FOR_HUMAN_PATTERN_REVIEW`",
        "",
        "This is a pre-2021 in-sample descriptive pattern discovery. It uses no returns, PnL, trade replay, model prediction, or 2021+ observations.",
        "",
        "## Broad mother population",
        "",
        f"The outcome-blind Stage-A screen retained {mother['n']} V6 CORE causal-first-return events across {mother['symbols']} symbols. It requires exact 120-session PIT minute history and low raw price occupancy both inside `[L,U]` and in `[L−0.5W,U+0.5W)`, but deliberately does not pre-gate long decline, depth, prior near-touch, or approach shape.",
        "",
        "|Population|N|5D U fill|10D U fill|20D U fill|40D U fill|",
        "|---|---:|---:|---:|---:|---:|",
        f"|Mother|{mother['n']}|{mother['u_fill_5d']:.2%}|{mother['u_fill_10d']:.2%}|{mother['u_fill_20d']:.2%}|{mother['u_fill_40d']:.2%}|",
        f"|Simple conditions|{rule['n']}|{rule['u_fill_5d']:.2%}|{rule['u_fill_10d']:.2%}|{rule['u_fill_20d']:.2%}|{rule['u_fill_40d']:.2%}|",
        "",
        "## Descriptive simple conditions",
        "",
    ]
    if conditions:
        for index, item in enumerate(conditions, 1):
            lines.append(f"{index}. `{item['feature']} {item['operator']} {item['threshold']:.6g}` ({item['threshold_source']}; N={item['n']}, pooled 20D fill={item['pooled_rate']:.2%}, pooled lift={item['pooled_lift']:+.2%}, median annual lift={item['median_year_lift']:+.2%}).")
    else:
        lines.append("No additional condition met the pre-frozen support, chronology and incremental-lift requirements. The broad low-inventory screen itself is the only descriptive screen.")
    lines += [
        "",
        "These conditions are discovered and evaluated on the same 2014–2020 observations. They are a compact description of this sample, not evidence of prediction or a strategy.",
        "",
        "The condition selector prioritises the number of calendar years with positive uplift before effect size. This prevents a large one-year partition from outranking a smaller but chronologically broader descriptive difference.",
        "",
        "## Calendar-year view",
        "",
        "|Year|Mother N|Mother 20D|Rule N|Rule 20D|",
        "|---:|---:|---:|---:|---:|",
    ]
    for item in result["yearly"]:
        rule_year = item["simple_rule"]
        rule_rate = "—" if not rule_year.get("n") else f"{rule_year['u_fill_20d']:.2%}"
        lines.append(f"|{item['year']}|{item['mother']['n']}|{item['mother']['u_fill_20d']:.2%}|{rule_year.get('n',0)}|{rule_rate}|")
    lines += [
        "",
        "## Human chart review",
        "",
        f"The PDF contains one summary page and {result['chart_book']['signal_charts']} deterministic condition-match charts. It deliberately includes both fills and non-fills. Each chart marks gap formation, `[L,U]`, the surrounding corridor, V6 freeze, causal first return, and the first U fill within 40 sessions when present.",
        "",
        "## Audit",
        "",
        f"`{json.dumps(result['audit'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Next action",
        "",
        "Review the charts for semantic fidelity. Only after that review should a separate task alter the semantic screen or reserve later years for a predictive test.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> dict[str, Any]:
    validate_inputs()
    hashes = freeze_stage_a_contract()
    mother = build_stage_a_mother_population()
    ledger = attach_structural_outcomes(mother)
    direct_feature_analysis(ledger)
    conditions, table, rule_mask = discover_simple_conditions(ledger)
    ledger["descriptive_rule_match"] = rule_mask.astype(bool)
    write_parquet(ledger, DISCOVERY_LEDGER)
    sample = select_chart_sample(ledger, rule_mask)
    paths, profiles = load_chart_data(sample)
    render_pdf(sample, paths, profiles, conditions, ledger)
    result = summarize(ledger, conditions, table, sample, hashes)
    write_json(RESULT, result)
    write_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-result", action="store_true")
    args = parser.parse_args()
    result = run()
    if args.print_result:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
