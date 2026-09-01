#!/usr/bin/env python3
"""Run frozen multi-timescale Industry Diffusion and daily-alpha Cycle 015."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-MULTISCALE-DIFFUSION-DAILY-ALPHA-CYCLE-015_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-MULTISCALE-DIFFUSION-DAILY-ALPHA-CYCLE-015_result.json"
CHURN_PATH = PROGRAM / "artifacts/ASHARE-MULTISCALE-DIFFUSION-DAILY-ALPHA-CYCLE-015_churn.csv"
HALFLIFE_PATH = (
    PROGRAM / "artifacts/ASHARE-MULTISCALE-DIFFUSION-DAILY-ALPHA-CYCLE-015_half_life.csv"
)
TRACK_B_PATH = (
    PROGRAM / "artifacts/ASHARE-MULTISCALE-DIFFUSION-DAILY-ALPHA-CYCLE-015_daily_screen.csv"
)
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-MULTISCALE-DIFFUSION-DAILY-ALPHA-CYCLE-015_equity.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-MULTISCALE-DIFFUSION-DAILY-ALPHA-CYCLE-015_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/multiscale_diffusion_daily_alpha_cycle_015")
DAILY_PANEL_PATH = EXTERNAL_ROOT / "daily_feature_panel.parquet"
SCHEDULE_PATH = EXTERNAL_ROOT / "daily_low_max_schedule.parquet"
TEMP_PATH = EXTERNAL_ROOT / "duckdb_tmp"
CONSTRUCTION_PATH = PROGRAM / "scripts/run_ashare_industry_diffusion_construction_011.py"
LOW_MAX_PATH = PROGRAM / "scripts/run_ashare_low_max_confirmation_cycle_012.py"
EXPECTED_SPEC_SHA256 = "b53c054c64072fda8269532200e51e6b90b868070e468c57f789bd038ad05bb2"
COSTS = (0.002, 0.003, 0.004)
SEVERE = -0.10


class Cycle015Error(RuntimeError):
    """Fail-closed error for Cycle 015."""


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
        raise Cycle015Error(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CONSTRUCTION = _load_module("construction_for_cycle015", CONSTRUCTION_PATH)
LOW_MAX = _load_module("low_max_for_cycle015", LOW_MAX_PATH)
CA = CONSTRUCTION.BASELINE


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise Cycle015Error("frozen Cycle-015 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != (
        "FROZEN_ARCHITECTURES_CHURN_HALFLIFE_AND_DAILY_HYPOTHESES_BEFORE_FORWARD_OUTCOMES"
    ):
        raise Cycle015Error("Cycle-015 contract was not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Cycle015Error(f"bound input changed: {role}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "daily full liquidation", "other frequency"):
        if phrase not in prohibited:
            raise Cycle015Error(f"missing prohibition: {phrase}")
    return spec


def _build_daily_frame(paths: list[Path]) -> tuple[pd.DataFrame, dict[str, Any]]:
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_PATH.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='10GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{TEMP_PATH.as_posix()}'")
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")
    audit_row = connection.execute("""
      SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((available_at>decision_at)::INTEGER),
        sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
        sum((hard_valid AND market_rule_valid AND
          (limit_pct IS NULL OR up_limit_price IS NULL))::INTEGER)
      FROM source
    """).fetchone()
    audit = {
        "rows": int(audit_row[0]),
        "symbols": int(audit_row[1]),
        "first": str(audit_row[2]),
        "last": str(audit_row[3]),
        "time_travel": int(audit_row[4]),
        "lineage_failures": int(audit_row[5]),
        "limit_rule_failures": int(audit_row[6]),
    }
    expected = {
        "rows": 6_155_390,
        "symbols": 5_262,
        "first": "2018-01-02",
        "last": "2023-12-29",
        "time_travel": 0,
        "lineage_failures": 0,
        "limit_rule_failures": 0,
    }
    if audit != expected:
        raise Cycle015Error(f"daily source audit changed: {audit}")
    connection.execute("""
      CREATE TEMP TABLE calendar AS
      SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 cal_idx
      FROM (SELECT DISTINCT trade_date FROM source) ORDER BY trade_date
    """)
    connection.execute("""
      CREATE TEMP TABLE base AS SELECT s.*,c.cal_idx,
        (s.hard_valid IS TRUE AND s.bar_valid IS TRUE AND s.trading_state_valid IS TRUE
         AND s.industry_valid IS TRUE AND s.float_valid IS TRUE
         AND s.corporate_action_valid IS TRUE AND s.market_valid IS TRUE
         AND s.market_rule_valid IS TRUE AND s.historical_identity_valid IS TRUE
         AND s.corporate_action_blocking IS FALSE AND coalesce(s.rights_ratio,0)=0
         AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
         AND s.open>0 AND s.high>=greatest(s.open,s.close)
         AND s.low<=least(s.open,s.close) AND s.close>0 AND s.volume>=0 AND s.amount>=0)
          history_valid,
        (s.hard_valid IS TRUE AND s.trade_status=1
         AND s.current_day_data_tradable IS TRUE AND s.is_st IS FALSE) current_valid,
        lag(s.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
        lag(s.hard_valid IS TRUE AND s.bar_valid IS TRUE AND s.trading_state_valid IS TRUE
         AND s.industry_valid IS TRUE AND s.float_valid IS TRUE
         AND s.corporate_action_valid IS TRUE AND s.market_valid IS TRUE
         AND s.market_rule_valid IS TRUE AND s.historical_identity_valid IS TRUE
         AND s.corporate_action_blocking IS FALSE AND coalesce(s.rights_ratio,0)=0
         AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
         AND s.open>0 AND s.high>=greatest(s.open,s.close)
         AND s.low<=least(s.open,s.close) AND s.close>0
         AND s.volume>=0 AND s.amount>=0) OVER w previous_history_valid
      FROM source s JOIN calendar c USING(trade_date)
      WINDOW w AS (PARTITION BY s.symbol ORDER BY s.trade_date)
    """)
    connection.execute("""
      CREATE TEMP TABLE steps0 AS SELECT *,CASE
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
         AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
         AND coalesce(share_multiplier,1)>0 AND previous_close-coalesce(cash_per_share,0)>0
        THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
        ELSE NULL END step_return
      FROM base
    """)
    connection.execute("""
      CREATE TEMP TABLE steps AS SELECT *,
        step_return-median(step_return) OVER(PARTITION BY trade_date) residual_step
      FROM steps0
    """)
    connection.execute("""
      CREATE TEMP TABLE coordinates AS SELECT *,
        sum(coalesce(step_return,0)) OVER
          (PARTITION BY symbol ORDER BY trade_date ROWS UNBOUNDED PRECEDING) log_coordinate
      FROM steps
    """)
    connection.execute("""
      CREATE TEMP TABLE geometry0 AS SELECT *,exp(log_coordinate) coordinate_close,
        exp(log_coordinate)*open/close coordinate_open,
        exp(log_coordinate)*high/close coordinate_high,
        exp(log_coordinate)*low/close coordinate_low,
        lag(exp(log_coordinate)) OVER ws previous_coordinate_close,
        count(step_return) OVER w120 valid_steps120,lag(cal_idx,120) OVER ws cal_idx_lag120,
        sum(step_return) OVER w5 r5,sum(step_return) OVER w20 r20,
        max(step_return) OVER w20 max_return20,
        count(step_return) OVER w20 valid_steps20,
        avg(amount) OVER p20 avg_amount20,median(amount) OVER p20 median_amount20,
        avg(volume) OVER p20 avg_volume20,count(*) OVER p20 prior_count20,
        count(residual_step) OVER w20 residual_count20,
        stddev_samp(residual_step) OVER w20 idio_vol20,
        sum(CASE WHEN step_return>0 THEN volume WHEN step_return<0 THEN -volume ELSE 0 END)
          OVER w20 / nullif(sum(volume) OVER w20,0) signed_volume_share20
      FROM coordinates WINDOW
        ws AS (PARTITION BY symbol ORDER BY trade_date),
        w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
        w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        w120 AS (PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
        p20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
    """)
    connection.execute("""
      CREATE TEMP TABLE geometry AS SELECT *,
        (coordinate_high-coordinate_low)/nullif(previous_coordinate_close,0) range_fraction,
        ln(coordinate_open/nullif(previous_coordinate_close,0)) gap_return,
        ln(coordinate_close/nullif(coordinate_open,0)) intraday_return,
        CASE WHEN coordinate_high>coordinate_low
          THEN (coordinate_close-coordinate_low)/(coordinate_high-coordinate_low)
          ELSE 0.5 END close_location
      FROM geometry0
    """)
    connection.execute("""
      CREATE TEMP TABLE rolling AS SELECT *,
        median(range_fraction) OVER p5 median_range5_prior,
        median(range_fraction) OVER p20 median_range20_prior,
        count(range_fraction) OVER p20 range_count20
      FROM geometry WINDOW
        p5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        p20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
    """)
    connection.execute("""
      CREATE TEMP TABLE eligible0 AS SELECT *,
        range_fraction/nullif(median_range20_prior,0) range_ratio,
        median_range5_prior/nullif(median_range20_prior,0) compression_ratio,
        amount/nullif(median_amount20,0) activity_ratio,
        (high>=up_limit_price-greatest(0.001,abs(up_limit_price)*1e-6)) limit_touch
      FROM rolling
      WHERE current_valid AND history_valid AND cal_idx>=120
        AND valid_steps120=120 AND cal_idx-cal_idx_lag120=120
        AND valid_steps20=20 AND prior_count20=20
        AND avg_amount20>=50000000 AND avg_volume20>0 AND previous_coordinate_close>0
        AND coordinate_open>0
        AND isfinite(r5) AND isfinite(r20) AND isfinite(max_return20)
        AND residual_count20=20 AND isfinite(idio_vol20)
        AND isfinite(signed_volume_share20)
    """)
    frame = connection.execute("""
      SELECT *,count(*) OVER(PARTITION BY trade_date,industry) industry_count,
        (sum((r20>0)::INTEGER) OVER(PARTITION BY trade_date,industry)-(r20>0)::INTEGER)
          / nullif(count(*) OVER(PARTITION BY trade_date,industry)-1,0) diffusion_score,
        (sum(step_return) OVER(PARTITION BY trade_date,industry)-step_return)
          / nullif(count(*) OVER(PARTITION BY trade_date,industry)-1,0) industry_return_loo,
        (sum((step_return>0)::INTEGER) OVER(PARTITION BY trade_date,industry)
          -(step_return>0)::INTEGER)
          / nullif(count(*) OVER(PARTITION BY trade_date,industry)-1,0) industry_breadth_loo
      FROM eligible0 QUALIFY industry_count>=6
      ORDER BY trade_date,industry,symbol
    """).fetch_df()
    connection.close()
    keep = [
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "step_return",
        "gap_return",
        "intraday_return",
        "range_fraction",
        "range_ratio",
        "compression_ratio",
        "close_location",
        "r20",
        "max_return20",
        "avg_amount20",
        "activity_ratio",
        "limit_touch",
        "limit_pct",
        "up_limit_price",
        "diffusion_score",
        "industry_return_loo",
        "industry_breadth_loo",
    ]
    frame = frame[keep].copy()
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise Cycle015Error("invalid daily feature panel")
    frame.to_parquet(DAILY_PANEL_PATH, index=False, compression="zstd")
    return frame, audit


def _weekly_selections(
    daily: pd.DataFrame, construction_spec: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    weekly = daily.loc[daily.cal_idx.mod(5).eq(4)].copy()
    baseline = CONSTRUCTION._frozen_baseline(weekly, construction_spec)
    low_max = CONSTRUCTION._select_modifier(
        weekly, baseline, "industry_diffusion_low_max", "max_return20", ascending=True
    )
    if CONSTRUCTION._allocation_difference(baseline, low_max) != 0:
        raise Cycle015Error("weekly Low-MAX changed frozen industry allocation")
    return baseline, low_max


def _build_daily_schedule(
    daily: pd.DataFrame,
    baseline: pd.DataFrame,
    weekly_low_max: pd.DataFrame,
    calendar: list[date],
) -> pd.DataFrame:
    cal_index = {day: index for index, day in enumerate(calendar)}
    daily = daily.copy()
    daily["trade_date"] = pd.to_datetime(daily.trade_date).dt.date
    groups = {
        (day, str(industry)): group.sort_values(["max_return20", "symbol"])
        for (day, industry), group in daily.groupby(["trade_date", "industry"], sort=False)
    }
    rows: list[dict[str, Any]] = []
    for signal_timestamp, cohort in baseline.groupby("trade_date", sort=True):
        signal_date = pd.Timestamp(signal_timestamp).date()
        signal_index = cal_index[signal_date]
        entry_index = signal_index + 1
        due_index = entry_index + 20
        if due_index >= len(calendar):
            continue
        cohort_id = signal_date.isoformat()
        allocations = cohort.groupby("industry").size()
        prior_desired: dict[str, list[str]] = {}
        for decision_index in range(signal_index, due_index - 1):
            decision_date = calendar[decision_index]
            for industry, target_raw in allocations.items():
                target = int(target_raw)
                opportunity = groups.get((decision_date, str(industry)))
                chosen = (
                    opportunity.head(target).copy() if opportunity is not None else pd.DataFrame()
                )
                if len(chosen) < target:
                    fallback_symbols = [
                        symbol
                        for symbol in prior_desired.get(str(industry), [])
                        if symbol not in set(chosen.get("symbol", pd.Series(dtype=str)))
                    ]
                    fallback = pd.DataFrame(
                        {
                            "symbol": fallback_symbols[: target - len(chosen)],
                            "max_return20": [math.nan]
                            * min(len(fallback_symbols), target - len(chosen)),
                        }
                    )
                    chosen = pd.concat([chosen, fallback], ignore_index=True, sort=False)
                if len(chosen) < target:
                    raise Cycle015Error(
                        f"daily Low-MAX cannot preserve industry count:{decision_date}:{industry}"
                    )
                prior_desired[str(industry)] = chosen.symbol.astype(str).tolist()
                for rank, item in enumerate(chosen.itertuples(index=False), start=1):
                    rows.append(
                        {
                            "cohort_id": cohort_id,
                            "signal_date": signal_date,
                            "decision_date": decision_date,
                            "decision_index": decision_index,
                            "fill_index": decision_index + 1,
                            "due_index": due_index,
                            "industry": str(industry),
                            "target_count": target,
                            "symbol": item.symbol,
                            "max_return20": float(item.max_return20),
                            "quality_rank": rank,
                        }
                    )
    schedule = pd.DataFrame(rows)
    if (
        schedule.empty
        or schedule.duplicated(["cohort_id", "decision_date", "industry", "symbol"]).any()
    ):
        raise Cycle015Error("invalid daily Low-MAX schedule")
    initial = schedule.loc[schedule.decision_date.eq(schedule.signal_date)]
    left = set(zip(initial.signal_date, initial.symbol, strict=True))
    scheduled_signal_dates = set(initial.signal_date)
    comparable_weekly = weekly_low_max.loc[
        pd.to_datetime(weekly_low_max.trade_date).dt.date.isin(scheduled_signal_dates)
    ]
    right = set(
        zip(
            pd.to_datetime(comparable_weekly.trade_date).dt.date,
            comparable_weekly.symbol,
            strict=True,
        )
    )
    if left != right:
        raise Cycle015Error(
            "daily architecture initial selections do not reproduce weekly Low-MAX:"
            f" daily_only={sorted(left - right)[:5]} weekly_only={sorted(right - left)[:5]}"
        )
    schedule.to_parquet(SCHEDULE_PATH, index=False, compression="zstd")
    return schedule


def _churn_and_half_life(
    daily: pd.DataFrame, schedule: pd.DataFrame
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    daily = daily.copy()
    daily["trade_date"] = pd.to_datetime(daily.trade_date).dt.date
    universe = {
        (day, str(industry)): group.set_index("symbol")["max_return20"].sort_index()
        for (day, industry), group in daily.groupby(["trade_date", "industry"], sort=False)
    }
    transition_rows: list[dict[str, Any]] = []
    half_rows: list[dict[str, Any]] = []
    episode_lengths: list[int] = []
    for (cohort_id, industry), group in schedule.groupby(["cohort_id", "industry"], sort=True):
        dates = sorted(group.decision_date.unique())
        prior_set: set[str] | None = None
        prior_date: date | None = None
        active_start: dict[str, int] = {}
        for position, decision_date in enumerate(dates):
            current_rows = group.loc[group.decision_date.eq(decision_date)]
            current_set = set(current_rows.symbol)
            for symbol in current_set - set(active_start):
                active_start[symbol] = position
            for symbol in set(active_start) - current_set:
                episode_lengths.append(position - active_start.pop(symbol))
            if prior_set is not None and prior_date is not None:
                prior_ranks = universe.get(
                    (prior_date, str(industry)), pd.Series(dtype=float)
                )
                current_ranks = universe.get(
                    (decision_date, str(industry)), pd.Series(dtype=float)
                )
                common = sorted(
                    set(prior_ranks.index) & set(current_ranks.index)
                )
                rank_corr = (
                    float(
                        spearmanr(
                            prior_ranks.loc[common],
                            current_ranks.loc[common],
                        ).statistic
                    )
                    if len(common) >= 6
                    else math.nan
                )
                entered = sorted(current_set - prior_set)
                rejected = sorted(prior_set - current_set)
                overlap = len(current_set & prior_set) / len(current_set)
                transition_rows.append(
                    {
                        "cohort_id": cohort_id,
                        "industry": str(industry),
                        "decision_date": decision_date,
                        "rank_correlation": rank_corr,
                        "selection_overlap": overlap,
                        "changed_fraction": 1.0 - overlap,
                        "replacements_requested": len(entered),
                    }
                )
                for pair_index, (new_symbol, old_symbol) in enumerate(
                    zip(entered, rejected, strict=True)
                ):
                    half_rows.append(
                        {
                            "uid": f"{cohort_id}|{industry}|{decision_date}|{pair_index}",
                            "cohort_id": cohort_id,
                            "industry": str(industry),
                            "decision_date": decision_date,
                            "new_symbol": new_symbol,
                            "rejected_symbol": old_symbol,
                        }
                    )
            prior_set = current_set
            prior_date = decision_date
        for start in active_start.values():
            episode_lengths.append(len(dates) - start)
    transitions = pd.DataFrame(transition_rows)
    half_life = pd.DataFrame(half_rows)
    by_date = transitions.groupby("decision_date").replacements_requested.sum()
    metrics = {
        "rank_autocorrelation_mean": float(transitions.rank_correlation.mean()),
        "rank_autocorrelation_median": float(transitions.rank_correlation.median()),
        "selection_overlap_mean": float(transitions.selection_overlap.mean()),
        "changed_preferred_fraction_mean": float(transitions.changed_fraction.mean()),
        "requested_replacements": int(transitions.replacements_requested.sum()),
        "transition_rows": len(transitions),
        "days_with_no_desired_change": int((by_date == 0).sum()),
        "decision_days": int(by_date.size),
        "median_desired_episode_sessions": float(np.median(episode_lengths)),
        "mean_desired_episode_sessions": float(np.mean(episode_lengths)),
    }
    return metrics, transitions, half_life


def _track_b_candidates(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    return_gap = frame.step_return.astype(float)
    no_limit = ~frame.limit_touch.astype(bool)
    families: list[pd.DataFrame] = []

    def add(name: str, event: pd.Series, control: pd.Series, strength: pd.Series) -> None:
        for role, mask in (("event", event), ("control", control)):
            part = frame.loc[mask].copy()
            part["hypothesis"] = name
            part["role"] = role
            part["strength"] = strength.loc[mask].to_numpy(float)
            families.append(part)

    accepted = return_gap.between(0.01, 0.08) & frame.close_location.ge(0.80) & no_limit
    add(
        "GAPLESS_RANGE_ACCEPTANCE",
        accepted & frame.gap_return.abs().le(0.005) & frame.range_ratio.ge(2.0),
        accepted & frame.gap_return.abs().le(0.005) & frame.range_ratio.between(0.8, 1.2),
        frame.range_ratio,
    )
    release = (
        return_gap.between(0.01, 0.08)
        & frame.close_location.ge(0.75)
        & frame.range_ratio.ge(1.5)
        & no_limit
    )
    add(
        "COMPRESSION_RELEASE_ACCEPTANCE",
        release & frame.compression_ratio.le(0.65),
        release & frame.compression_ratio.between(0.9, 1.1),
        -frame.compression_ratio,
    )
    aligned = return_gap.between(0.01, 0.08) & frame.close_location.ge(0.75) & no_limit
    add(
        "OVERNIGHT_INTRADAY_ALIGNMENT",
        aligned & frame.gap_return.between(0.01, 0.05) & frame.intraday_return.ge(0.01),
        aligned & frame.gap_return.abs().le(0.002) & frame.intraday_return.gt(0),
        frame.intraday_return,
    )
    nonleader = (
        frame.industry_return_loo.ge(0.01)
        & frame.industry_breadth_loo.ge(0.70)
        & frame.close_location.ge(0.75)
        & no_limit
    )
    add(
        "BROAD_INDUSTRY_NONLEADER_ACCEPTANCE",
        nonleader & return_gap.ge(0.002) & return_gap.le(frame.industry_return_loo),
        nonleader & return_gap.ge(frame.industry_return_loo + 0.01),
        frame.close_location,
    )
    shock = (
        frame.industry_return_loo.ge(0.01)
        & (return_gap - frame.industry_return_loo).le(-0.02)
        & no_limit
    )
    add(
        "INDUSTRY_SHOCK_RECOVERY_CONFIRMATION",
        shock & frame.close_location.ge(0.60),
        shock & frame.close_location.le(0.30),
        frame.close_location,
    )
    output = pd.concat(families, ignore_index=True)
    output["uid"] = (
        "B|"
        + output.hypothesis
        + "|"
        + output.role
        + "|"
        + output.trade_date.astype(str)
        + "|"
        + output.symbol
    )
    output["block"] = np.where(pd.to_datetime(output.trade_date).dt.year <= 2020, "early", "late")
    return output


def _nearest_pairs(candidates: pd.DataFrame) -> pd.DataFrame:
    features = ["step_return", "log_amount", "r20", "range_ratio"]
    scales = np.array([0.03, 1.0, 0.10, 1.0])
    candidates = candidates.copy()
    candidates["log_amount"] = np.log(candidates.avg_amount20.astype(float))
    candidates[features] = candidates[features].replace([np.inf, -np.inf], np.nan)
    candidates = candidates.dropna(subset=features)
    rows: list[dict[str, Any]] = []
    for hypothesis, family in candidates.groupby("hypothesis", sort=True):
        events = family.loc[family.role.eq("event")]
        controls = family.loc[family.role.eq("control")]
        control_dates = {
            day: group.sort_values("symbol")
            for day, group in controls.groupby("trade_date", sort=False)
        }
        for day, event_group in events.groupby("trade_date", sort=False):
            control = control_dates.get(day)
            if control is None or control.empty:
                continue
            full_tree = cKDTree(control[features].to_numpy(float) / scales)
            industry_pools = {
                industry: (
                    group.sort_values("symbol"),
                    cKDTree(group[features].to_numpy(float) / scales),
                )
                for industry, group in control.groupby("industry", sort=False)
            }
            for event in event_group.itertuples(index=False):
                pool, tree = industry_pools.get(event.industry, (control, full_tree))
                vector = np.array([getattr(event, name) for name in features], dtype=float)
                distance, index = tree.query(vector / scales, k=1)
                matched = pool.iloc[int(index)]
                rows.append(
                    {
                        "comparison": hypothesis,
                        "event_uid": event.uid,
                        "control_uid": matched.uid,
                        "event_block": event.block,
                        "same_industry": bool(event.industry == matched.industry),
                        "match_distance": float(distance),
                    }
                )
    return pd.DataFrame(rows)


def _query_rows(paths: list[Path], keys: set[tuple[str, date]]) -> pd.DataFrame:
    key_frame = pd.DataFrame(sorted(keys), columns=["symbol", "trade_date"])
    connection = duckdb.connect()
    connection.register("needed_keys", key_frame)
    rows = connection.execute(
        """
      SELECT d.trade_date,d.symbol,d.open,d.close,d.amount,d.hard_valid,d.trade_status,
        d.current_day_data_tradable,d.buy_blocked_open,d.sell_blocked_open,
        d.corporate_action_count,d.corporate_action_valid,d.corporate_action_blocking,
        d.corporate_action_available_date,d.share_multiplier,d.cash_per_share,
        d.rights_ratio,d.available_at,d.invalid_reasons,d.corporate_action_problems,
        d.corporate_action_ids,d.corporate_action_snapshot_id
      FROM read_parquet(?) d JOIN needed_keys k USING(symbol,trade_date)
      ORDER BY d.trade_date,d.symbol
    """,
        [[str(path) for path in paths]],
    ).fetch_df()
    connection.close()
    if rows.duplicated(["symbol", "trade_date"]).any():
        raise Cycle015Error("duplicate execution row")
    return rows


def _execution_keys(
    schedule: pd.DataFrame,
    track_b: pd.DataFrame,
    pairs: pd.DataFrame,
    calendar: list[date],
) -> set[tuple[str, date]]:
    keys: set[tuple[str, date]] = set()
    for row in schedule.itertuples(index=False):
        for index in range(int(row.fill_index), min(int(row.due_index) + 20, len(calendar))):
            keys.add((row.symbol, calendar[index]))
    needed_uids = set(pairs.event_uid) | set(pairs.control_uid)
    selected = track_b.loc[track_b.uid.isin(needed_uids)]
    cal_index = {day: index for index, day in enumerate(calendar)}
    for row in selected.itertuples(index=False):
        start = cal_index[row.trade_date] + 1
        for index in range(start, min(start + 25, len(calendar))):
            keys.add((row.symbol, calendar[index]))
    return keys


def _row_usable(row: Any) -> bool:
    return CA._holding_row_usable(row)


def _buyable(row: Any) -> bool:
    return (
        CONSTRUCTION.CYCLE2._valid_market_row(row)
        and int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and not bool(row.buy_blocked_open)
    )


@dataclass
class DynamicLot:
    cohort_id: str
    signal_date: date
    symbol: str
    industry: str
    due_index: int
    shares: float
    invested_cost: float
    entry_index: int
    action_cash: float = 0.0
    forced_effective_date: date | None = None
    forced_event_id: str | None = None


def _dynamic_replay(
    schedule: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
    cost: float,
) -> tuple[dict[str, Any], pd.DataFrame]:
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    schedule_map = {
        (int(fill), str(cohort), str(industry)): group
        for (fill, cohort, industry), group in schedule.groupby(
            ["fill_index", "cohort_id", "industry"], sort=True
        )
    }
    initial_map = {
        (int(group.fill_index.iloc[0]), str(cohort)): group
        for cohort, group in schedule.loc[
            schedule.decision_date.eq(schedule.signal_date)
        ].groupby("cohort_id", sort=False)
    }
    event_decisions, symbol_events = CA._event_maps(events)
    initial = 10_000_000.0
    cash = initial
    lots: list[DynamicLot] = []
    turnover = 0.0
    requested_replacements = 0
    executed_replacements = 0
    blocked_replacements = 0
    planned_entries = 0
    entries = 0
    completed = 0
    severe = 0
    winners = 0
    forced_exits = 0
    holding_sessions: list[int] = []
    capacity: list[float] = []
    nav_rows: list[dict[str, Any]] = []
    start_index = int(schedule.fill_index.min())
    final_due = int(schedule.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)

    for cal_index in range(start_index, final_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise Cycle015Error(
                    f"pre-effective daily exit failed:{lot.symbol}:{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current_date))
            if row is None or not _row_usable(row):
                raise Cycle015Error(f"invalid daily holding row:{lot.symbol}:{current_date}")
            if int(row.corporate_action_count or 0) > 0:
                action = CA.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise Cycle015Error(f"unresolved action:{lot.symbol}:{current_date}")
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise Cycle015Error(f"share action reached effective date:{lot.symbol}")
                lot.action_cash += lot.shares * cash_per_share

        survivors: list[DynamicLot] = []
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            forced = lot.forced_effective_date is not None
            due = cal_index >= lot.due_index
            if not forced and not due:
                survivors.append(lot)
                continue
            if not CA._sellable(row):
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1.0 - cost)
            cash += proceeds
            turnover += gross
            payoff = proceeds / lot.invested_cost - 1.0
            completed += 1
            severe += int(payoff <= SEVERE)
            winners += int(payoff > 0)
            forced_exits += int(forced)
            holding_sessions.append(cal_index - lot.entry_index)
        lots = survivors

        active_groups = {
            (lot.cohort_id, lot.industry)
            for lot in lots
            if cal_index < lot.due_index and lot.forced_effective_date is None
        }
        for cohort_id, industry in sorted(active_groups):
            desired_group = schedule_map.get((cal_index, cohort_id, industry))
            if desired_group is None:
                continue
            group_lots = [
                lot for lot in lots if lot.cohort_id == cohort_id and lot.industry == industry
            ]
            current_symbols = {lot.symbol for lot in group_lots}
            desired = set(desired_group.symbol)
            removed = sorted(current_symbols - desired)
            additions = sorted(desired - current_symbols)
            for old_symbol, new_symbol in zip(removed, additions, strict=False):
                requested_replacements += 1
                old_lot = next(lot for lot in group_lots if lot.symbol == old_symbol)
                old_row = row_map.get((old_symbol, current_date))
                new_row = row_map.get((new_symbol, current_date))
                replacement_signal_date = calendar[cal_index - 1]
                if (
                    old_row is None
                    or new_row is None
                    or not CA._sellable(old_row)
                    or not _buyable(new_row)
                    or CA._entry_blocked(
                        new_symbol, replacement_signal_date, current_date, symbol_events
                    )
                ):
                    blocked_replacements += 1
                    continue
                gross = old_lot.shares * float(old_row.open)
                proceeds = old_lot.action_cash + gross * (1.0 - cost)
                turnover += gross
                payoff = proceeds / old_lot.invested_cost - 1.0
                completed += 1
                severe += int(payoff <= SEVERE)
                winners += int(payoff > 0)
                holding_sessions.append(cal_index - old_lot.entry_index)
                purchase_gross = proceeds / (1.0 + cost)
                shares = purchase_gross / float(new_row.open)
                invested = purchase_gross * (1.0 + cost)
                turnover += purchase_gross
                lots.remove(old_lot)
                replacement = DynamicLot(
                    cohort_id=cohort_id,
                    signal_date=replacement_signal_date,
                    symbol=new_symbol,
                    industry=industry,
                    due_index=old_lot.due_index,
                    shares=shares,
                    invested_cost=invested,
                    entry_index=cal_index,
                )
                lots.append(replacement)
                executed_replacements += 1
                entries += 1
                capacity.append(float(new_row.amount) * 0.05 * 40)

        pre_entry_nav = cash + sum(
            lot.action_cash + lot.shares * float(row_map[(lot.symbol, current_date)].open)
            for lot in lots
        )
        for key in sorted(initial_map):
            fill_index, cohort_id = key
            if fill_index != cal_index:
                continue
            desired_group = initial_map[key]
            planned_entries += len(desired_group)
            executable: list[tuple[Any, Any]] = []
            for plan in desired_group.itertuples(index=False):
                row = row_map.get((plan.symbol, current_date))
                if (
                    row is not None
                    and _buyable(row)
                    and not CA._entry_blocked(
                        plan.symbol, plan.signal_date, current_date, symbol_events
                    )
                ):
                    executable.append((plan, row))
            cohort_capital = min(cash, pre_entry_nav / 4)
            if executable:
                if cohort_capital <= 0:
                    raise Cycle015Error(f"nonpositive cohort capital:{cohort_id}:{current_date}")
                allocation = cohort_capital / len(executable)
                for plan, row in executable:
                    shares = allocation / (float(row.open) * (1.0 + cost))
                    gross = shares * float(row.open)
                    invested = gross * (1.0 + cost)
                    cash -= invested
                    turnover += gross
                    lots.append(
                        DynamicLot(
                            cohort_id=cohort_id,
                            signal_date=plan.signal_date,
                            symbol=plan.symbol,
                            industry=plan.industry,
                            due_index=int(plan.due_index),
                            shares=shares,
                            invested_cost=invested,
                            entry_index=cal_index,
                        )
                    )
                    entries += 1
                    capacity.append(float(row.amount) * 0.05 * len(executable) * 4)

        for lot in lots:
            for event in event_decisions.get((lot.symbol, current_date), ()):
                if (
                    lot.forced_effective_date is None
                    or event.effective_date < lot.forced_effective_date
                ):
                    lot.forced_effective_date = event.effective_date
                    lot.forced_event_id = event.event_id

        nav = cash
        industry_values: dict[str, float] = {}
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            industry_values[lot.industry] = industry_values.get(lot.industry, 0.0) + value
        invested = sum(industry_values.values())
        hhi = (
            sum((value / invested) ** 2 for value in industry_values.values())
            if invested > 0
            else 0.0
        )
        nav_rows.append(
            {
                "trade_date": current_date,
                "family": "slow_industry_daily_low_max",
                "cost_per_side": cost,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industry_values),
                "industry_hhi": hhi,
            }
        )
        if cal_index >= final_due and not lots:
            break
    if lots:
        raise Cycle015Error(f"terminal daily lots:{len(lots)}")
    equity = pd.DataFrame(nav_rows)
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / initial - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / initial) ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1)
    sharpe = math.sqrt(252) * returns.mean() / volatility if volatility > 0 else 0.0
    maximum_drawdown = float(drawdown.min())
    metrics = {
        "family": "slow_industry_daily_low_max",
        "cost_per_side": cost,
        "total_return": float(equity.nav.iloc[-1] / initial - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": maximum_drawdown,
        "daily_sharpe": float(sharpe),
        "calmar": float(annualized / abs(maximum_drawdown)) if maximum_drawdown < 0 else None,
        "severe_trade_fraction": float(severe / completed),
        "winner_trade_fraction": float(winners / completed),
        "turnover_multiple_initial_capital": float(turnover / initial),
        "alpha_per_turnover": float((equity.nav.iloc[-1] / initial - 1.0) / (turnover / initial)),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / (planned_entries + requested_replacements)),
        "completed_trades": completed,
        "requested_replacements": requested_replacements,
        "executed_replacements": executed_replacements,
        "blocked_replacements": blocked_replacements,
        "replacement_execution_fraction": float(executed_replacements / requested_replacements)
        if requested_replacements
        else 1.0,
        "average_holding_sessions": float(np.mean(holding_sessions)),
        "median_holding_sessions": float(np.median(holding_sessions)),
        "forced_pre_effective_exits": forced_exits,
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
        "terminal_open_lots": 0,
    }
    return metrics, equity


def _attach_screen_returns(
    candidates: pd.DataFrame,
    pairs: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
) -> pd.DataFrame:
    needed = set(pairs.event_uid) | set(pairs.control_uid)
    selected = candidates.loc[candidates.uid.isin(needed)].copy()
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    cal_index = {day: index for index, day in enumerate(calendar)}
    records: list[dict[str, Any]] = []
    for item in selected.itertuples(index=False):
        signal_index = cal_index[item.trade_date]
        entry_index = signal_index + 1
        record: dict[str, Any] = {"uid": item.uid, "entry_coverage": False}
        if entry_index >= len(calendar):
            records.append(record)
            continue
        entry_row = row_map.get((item.symbol, calendar[entry_index]))
        if entry_row is None or not _buyable(entry_row):
            records.append(record)
            continue
        record["entry_coverage"] = True
        entry_open = float(entry_row.open)
        for horizon in (1, 3, 5):
            value = math.nan
            for index in range(
                entry_index + horizon, min(entry_index + horizon + 20, len(calendar))
            ):
                row = row_map.get((item.symbol, calendar[index]))
                if row is None or not _row_usable(row):
                    break
                if bool(row.corporate_action_blocking) or int(row.corporate_action_count or 0) > 0:
                    break
                if CA._sellable(row):
                    value = float(row.open) / entry_open - 1.0 - 0.004
                    break
            record[f"net_h{horizon}"] = value
        records.append(record)
    return selected.merge(pd.DataFrame(records), on="uid", how="left", validate="one_to_one")


def _summarize_pairs(pairs: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    indexed = outcomes.set_index("uid")
    rows: list[dict[str, Any]] = []
    for comparison, group in pairs.groupby("comparison", sort=True):
        event = indexed.loc[group.event_uid]
        control = indexed.loc[group.control_uid]
        valid = np.ones(len(group), dtype=bool)
        for horizon in (1, 3, 5):
            valid &= event[f"net_h{horizon}"].notna().to_numpy()
            valid &= control[f"net_h{horizon}"].notna().to_numpy()
        event = event.iloc[np.flatnonzero(valid)]
        control = control.iloc[np.flatnonzero(valid)]
        block = group.event_block.to_numpy()[valid]
        row: dict[str, Any] = {
            "hypothesis": comparison,
            "pairs": len(group),
            "complete_pairs": int(valid.sum()),
            "dates": int(event.trade_date.nunique()),
            "symbols": int(event.symbol.nunique()),
            "entry_coverage": float(
                indexed.loc[group.event_uid].entry_coverage.astype(bool).mean()
            ),
            "same_industry_fraction": float(group.same_industry.mean()),
            "mean_match_distance": float(group.match_distance.mean()),
        }
        for horizon in (1, 3, 5):
            delta = event[f"net_h{horizon}"].to_numpy(float) - control[f"net_h{horizon}"].to_numpy(
                float
            )
            row[f"event_mean_h{horizon}"] = float(event[f"net_h{horizon}"].mean())
            row[f"mean_delta_h{horizon}"] = float(np.mean(delta))
        h3_delta = event.net_h3.to_numpy(float) - control.net_h3.to_numpy(float)
        row["h3_delta_early"] = float(np.mean(h3_delta[block == "early"]))
        row["h3_delta_late"] = float(np.mean(h3_delta[block == "late"]))
        row["winner_improvement_h3"] = float(
            np.mean(event.net_h3.to_numpy(float) > 0) - np.mean(control.net_h3.to_numpy(float) > 0)
        )
        row["severe_improvement_h5"] = float(
            np.mean(control.net_h5.to_numpy(float) <= SEVERE)
            - np.mean(event.net_h5.to_numpy(float) <= SEVERE)
        )
        row["events_early"] = int(np.sum(block == "early"))
        row["events_late"] = int(np.sum(block == "late"))
        rows.append(row)
    return pd.DataFrame(rows)


def _classify_track_b(summary: pd.DataFrame) -> tuple[dict[str, str], list[str]]:
    classifications: dict[str, str] = {}
    promoted: list[str] = []
    for row in summary.itertuples(index=False):
        gates = (
            row.complete_pairs >= 1000
            and min(row.events_early, row.events_late) >= 100
            and row.entry_coverage >= 0.90
            and row.mean_delta_h3 >= 0.0025
            and row.h3_delta_early > 0
            and row.h3_delta_late > 0
            and row.severe_improvement_h5 >= 0.01
        )
        if gates:
            classification = "DAILY_STRATEGY_CANDIDATE"
            promoted.append(row.hypothesis)
        elif np.sign(row.h3_delta_early) != np.sign(row.h3_delta_late):
            classification = "CHRONOLOGICALLY_MIXED"
        elif row.mean_delta_h3 > 0 and row.h3_delta_early > 0 and row.h3_delta_late > 0:
            classification = "PROMISING_DAILY_INFORMATION"
        elif row.mean_delta_h3 < 0 and row.h3_delta_early < 0 and row.h3_delta_late < 0:
            classification = "ADVERSE"
        else:
            classification = "ECONOMICALLY_NULL"
        classifications[row.hypothesis] = classification
    return classifications, promoted[:1]


def _half_life_outcomes(
    half_life: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    lookup = outcomes.set_index(["trade_date", "symbol"])
    rows: list[dict[str, Any]] = []
    for item in half_life.itertuples(index=False):
        new_key = (item.decision_date, item.new_symbol)
        old_key = (item.decision_date, item.rejected_symbol)
        if new_key not in lookup.index or old_key not in lookup.index:
            continue
        new = lookup.loc[new_key]
        old = lookup.loc[old_key]
        row = item._asdict()
        for horizon in (1, 3, 5):
            row[f"delta_h{horizon}"] = (
                float(new[f"net_h{horizon}"] - old[f"net_h{horizon}"])
                if pd.notna(new[f"net_h{horizon}"]) and pd.notna(old[f"net_h{horizon}"])
                else math.nan
            )
        rows.append(row)
    panel = pd.DataFrame(rows)
    complete = panel.dropna(subset=["delta_h1", "delta_h3", "delta_h5"])
    years = pd.to_datetime(complete.decision_date).dt.year
    means = {f"h{h}": float(complete[f"delta_h{h}"].mean()) for h in (1, 3, 5)}
    blocks = {
        block: {f"h{h}": float(complete.loc[mask, f"delta_h{h}"].mean()) for h in (1, 3, 5)}
        for block, mask in (("early", years <= 2020), ("late", years >= 2021))
    }
    if (
        means["h1"] > 0
        and means["h3"] > 0
        and means["h5"] > 0
        and (means["h3"] >= means["h1"] or means["h5"] >= means["h1"])
    ):
        classification = "MULTI_DAY_PERSISTENT"
    elif means["h1"] > 0 and means["h3"] <= means["h1"] and means["h5"] <= means["h1"]:
        classification = "FAST_DECAY"
    elif means["h1"] <= 0 < means["h5"]:
        classification = "SLOW"
    else:
        classification = "NONPORTABLE_DAILY_CHURN"
    metrics = {
        "pairs": len(panel),
        "complete_pairs": len(complete),
        "means": means,
        "blocks": blocks,
        "classification": classification,
    }
    return panel, metrics


def _architecture_decision(
    weekly: dict[str, Any], daily: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    deltas: dict[str, Any] = {}
    for label in ("20bps", "30bps", "40bps"):
        base = weekly[label]["low_max"]
        candidate = daily[label]
        deltas[label] = {
            "total_return": candidate["total_return"] - base["total_return"],
            "annualized_return": candidate["annualized_return"] - base["annualized_return"],
            "maximum_drawdown": candidate["maximum_drawdown"] - base["maximum_drawdown"],
            "daily_sharpe": candidate["daily_sharpe"] - base["daily_sharpe"],
            "calmar": candidate["calmar"] - base["calmar"],
            "severe_improvement": base["severe_trade_fraction"]
            - candidate["severe_trade_fraction"],
            "turnover": candidate["turnover_multiple_initial_capital"]
            - base["turnover_multiple_initial_capital"],
            "industry_hhi": candidate["mean_industry_hhi_invested_days"]
            - base["mean_industry_hhi_invested_days"],
            "capacity_ratio": candidate["p10_capacity_cny_at_5pct_amount"]
            / base["p10_capacity_cny_at_5pct_amount"],
        }
        deltas[label]["return_per_incremental_turnover"] = (
            deltas[label]["total_return"] / deltas[label]["turnover"]
            if deltas[label]["turnover"] > 0
            else math.nan
        )
    gate = {
        "return_20": deltas["20bps"]["total_return"] >= 0.05,
        "sharpe_20": deltas["20bps"]["daily_sharpe"] >= 0.05,
        "calmar_20": deltas["20bps"]["calmar"] >= 0.05,
        "drawdown_20": deltas["20bps"]["maximum_drawdown"] >= -0.02,
        "severe_20": deltas["20bps"]["severe_improvement"] >= 0,
        "return_40": deltas["40bps"]["total_return"] >= 0,
        "sharpe_40": deltas["40bps"]["daily_sharpe"] >= 0,
        "alpha_turnover": deltas["20bps"]["return_per_incremental_turnover"] >= 0.001,
        "industry_hhi": deltas["20bps"]["industry_hhi"] <= 0.03,
        "capacity": deltas["20bps"]["capacity_ratio"] >= 0.70,
    }
    if all(gate.values()):
        decision = "DAILY_QUALITY_REFRESH_EARNS_COMPLEXITY"
    elif (
        deltas["20bps"]["total_return"] > 0
        and deltas["20bps"]["daily_sharpe"] > 0
        and (deltas["40bps"]["total_return"] <= 0 or deltas["40bps"]["daily_sharpe"] <= 0)
    ):
        decision = "DAILY_REFRESH_COST_FRAGILE"
    elif deltas["20bps"]["total_return"] < 0 and deltas["20bps"]["daily_sharpe"] < 0:
        decision = "DAILY_REFRESH_DEGRADES_STRATEGY"
    else:
        decision = "WEEKLY_REFRESH_SUFFICIENT"
    return decision, {"deltas": deltas, "gate": gate}


def run() -> dict[str, Any]:
    spec = _load_spec()
    ca_spec = CA._load_spec()
    paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    construction_spec = CONSTRUCTION._load_spec()
    daily, source_audit = _build_daily_frame(paths)
    baseline, weekly_low_max = _weekly_selections(daily, construction_spec)
    schedule = _build_daily_schedule(daily, baseline, weekly_low_max, calendar)
    churn, churn_panel, half_life = _churn_and_half_life(daily, schedule)
    track_b = _track_b_candidates(daily)
    pairs = _nearest_pairs(track_b)
    keys = _execution_keys(schedule, track_b, pairs, calendar)
    market_rows = _query_rows(paths, keys)
    events, action_audit = CA._load_risk_events(ca_spec, calendar)
    weekly_authoritative = json.loads(
        _resolve(spec["inputs"]["low_max_result"]["path"]).read_text(encoding="utf-8")
    )["track_a"]["matched_cost_comparisons"]
    daily_replays: dict[str, Any] = {}
    equities: list[pd.DataFrame] = []
    for cost in COSTS:
        metrics, equity = _dynamic_replay(schedule, market_rows, calendar, events, cost)
        label = f"{round(cost * 10000):.0f}bps"
        daily_replays[label] = metrics
        equities.append(equity)
    architecture_decision, architecture_comparison = _architecture_decision(
        weekly_authoritative, daily_replays
    )

    screen_outcomes = _attach_screen_returns(track_b, pairs, market_rows, calendar)
    daily_summary = _summarize_pairs(pairs, screen_outcomes)
    track_b_classifications, track_b_promotions = _classify_track_b(daily_summary)

    half_candidates = pd.concat(
        [
            half_life.rename(columns={"decision_date": "trade_date", "new_symbol": "symbol"})[
                ["trade_date", "symbol"]
            ],
            half_life.rename(columns={"decision_date": "trade_date", "rejected_symbol": "symbol"})[
                ["trade_date", "symbol"]
            ],
        ],
        ignore_index=True,
    ).drop_duplicates()
    half_candidates["trade_date"] = pd.to_datetime(half_candidates.trade_date).dt.date
    lookup = screen_outcomes[
        ["trade_date", "symbol", "net_h1", "net_h3", "net_h5"]
    ].drop_duplicates(["trade_date", "symbol"])
    lookup["trade_date"] = pd.to_datetime(lookup.trade_date).dt.date
    missing = half_candidates.merge(
        lookup[["trade_date", "symbol"]], on=["trade_date", "symbol"], how="left", indicator=True
    )
    missing = missing.loc[missing._merge.eq("left_only"), ["trade_date", "symbol"]]
    if not missing.empty:
        daily_for_half_life = daily.copy()
        daily_for_half_life["trade_date"] = pd.to_datetime(
            daily_for_half_life.trade_date
        ).dt.date
        extra = daily_for_half_life.merge(
            missing, on=["trade_date", "symbol"], how="inner"
        )
        extra["uid"] = "H|" + extra.trade_date.astype(str) + "|" + extra.symbol
        extra_pairs = pd.DataFrame(
            {
                "event_uid": extra.uid,
                "control_uid": extra.uid,
                "comparison": "HALF_LIFE_KEYS",
                "event_block": np.where(
                    pd.to_datetime(extra.trade_date).dt.year <= 2020, "early", "late"
                ),
                "same_industry": True,
                "match_distance": 0.0,
            }
        )
        extra_outcomes = _attach_screen_returns(extra, extra_pairs, market_rows, calendar)
        lookup = pd.concat(
            [lookup, extra_outcomes[["trade_date", "symbol", "net_h1", "net_h3", "net_h5"]]],
            ignore_index=True,
        ).drop_duplicates(["trade_date", "symbol"])
    half_panel, half_metrics = _half_life_outcomes(half_life, lookup)

    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "claim_boundary": spec["claim_boundary"],
        "input_identity": input_identity,
        "source_audit": source_audit,
        "action_audit": action_audit,
        "domain": {
            "daily_feature_rows": len(daily),
            "symbols": int(daily.symbol.nunique()),
            "dates": int(daily.trade_date.nunique()),
            "daily_schedule_rows": len(schedule),
            "track_b_candidate_rows": len(track_b),
            "track_b_matched_pairs": len(pairs),
        },
        "track_a": {
            "churn": churn,
            "half_life": half_metrics,
            "weekly_authoritative": weekly_authoritative,
            "daily_replays": daily_replays,
            "comparison": architecture_comparison,
            "classification": architecture_decision,
        },
        "track_b": {
            "summary": daily_summary.to_dict(orient="records"),
            "classifications": track_b_classifications,
            "promotions": track_b_promotions,
            "replay_status": "AUTHORIZED_NOT_RUN" if track_b_promotions else "NOT_AUTHORIZED",
        },
        "boundaries": {
            "post_2023_read": False,
            "cy011_read": False,
            "frequency_search": False,
            "industry_signal_changed": False,
            "low_max_changed": False,
            "track_b_parameter_search": False,
            "oos_claim": False,
        },
    }
    _atomic_write(
        CHURN_PATH, churn_panel.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    )
    _atomic_write(
        HALFLIFE_PATH, half_panel.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    )
    _atomic_write(
        TRACK_B_PATH, daily_summary.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    )
    equity_output = pd.concat(equities, ignore_index=True).sort_values(
        ["cost_per_side", "trade_date"]
    )
    _atomic_write(
        EQUITY_PATH, equity_output.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    )
    result["external_artifacts"] = {
        path.name: {
            "path": str(path),
            "rows": len(pd.read_parquet(path)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in (DAILY_PANEL_PATH, SCHEDULE_PATH)
    }
    result["artifacts"] = {
        path.name: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
        for path in (CHURN_PATH, HALFLIFE_PATH, TRACK_B_PATH, EQUITY_PATH)
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
