#!/usr/bin/env python3
"""Run the frozen stock-intraday and independent A-share discovery cycle."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-INTRADAY-INDEP-CYCLE-004_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-INTRADAY-INDEP-CYCLE-004_candidate_panel.csv"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-INTRADAY-INDEP-CYCLE-004_screen_summary.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-INTRADAY-INDEP-CYCLE-004_equity.csv"
RISK_EXIT_PATH = PROGRAM / "artifacts/ASHARE-INTRADAY-INDEP-CYCLE-004_risk_exits.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-INTRADAY-INDEP-CYCLE-004_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-INTRADAY-INDEP-CYCLE-004_report.md"
EXPECTED_SPEC_SHA256 = "fa923737b7fe9f6e38b263e751f1c2b39b871c6cc86677efcb24238f3337a103"
DAILY_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
MINUTE_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2")
DAILY_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
MINUTE_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/CY-008-pit-b-minute-v2-2018-2026-20260821.json"
)
PRIOR_SCRIPT = PROGRAM / "scripts/run_ashare_indep_funnel_001.py"
DIVERSIFIED_SCRIPT = PROGRAM / "scripts/run_ashare_diversified_cycle_002.py"
CA_SCRIPT = PROGRAM / "scripts/run_ashare_ca_replay_003.py"


class CycleError(RuntimeError):
    """Fail-closed error for cycle 004."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise CycleError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


PRIOR = _load_module("ashare_indep_funnel_001_for_004", PRIOR_SCRIPT)
DIVERSIFIED = _load_module("ashare_diversified_cycle_002_for_004", DIVERSIFIED_SCRIPT)
CA = _load_module("ashare_ca_replay_003_for_004", CA_SCRIPT)


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


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


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CycleError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BOTH_TRACKS_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise CycleError("tracks were not frozen before forward outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CycleError(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "same-bar", "feature factory"):
        if phrase not in prohibited:
            raise CycleError(f"missing prohibition: {phrase}")
    if len(spec["track_a"]["families"]) != 7 or len(spec["track_b"]["families"]) != 5:
        raise CycleError("frozen family count changed")
    return spec


def _manifest_paths(manifest_path: Path, root: Path, prefix: str) -> list[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {
        record["path"]: record for record in manifest["files"] if record["path"].startswith(prefix)
    }
    paths: list[Path] = []
    for year in range(2018, 2024):
        relative = f"{prefix}partition_year={year}/data_0.parquet"
        record = records.get(relative)
        path = root / relative
        if record is None or not path.is_file():
            raise CycleError(f"missing manifest partition: {relative}")
        if path.stat().st_size != int(record["size"]) or sha256_file(path) != record["sha256"]:
            raise CycleError(f"partition identity mismatch: {relative}")
        paths.append(path)
    return paths


def _input_paths() -> tuple[list[Path], list[Path]]:
    daily = _manifest_paths(DAILY_MANIFEST, DAILY_ROOT, "")
    minute = _manifest_paths(MINUTE_MANIFEST, MINUTE_ROOT, "daily/")
    return daily, minute


def _configure(temp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET memory_limit='6GB'")
    # Industry leave-one-out sums feed the tracked raw-score ledger. Serial
    # aggregation prevents parallel floating-point reduction order from changing
    # low-order panel bits across otherwise identical runs.
    connection.execute("SET threads=1")
    connection.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def _build_frame(
    daily_paths: list[Path], minute_paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, list[date], dict[str, Any]]:
    con = _configure(temp_path)
    con.from_parquet([str(path) for path in daily_paths], union_by_name=True).create_view("daily")
    con.from_parquet([str(path) for path in minute_paths], union_by_name=True).create_view("minute")
    daily_audit = con.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((available_at>decision_at)::INTEGER),
        sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER)
        FROM daily"""
    ).fetchone()
    minute_audit = con.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
        sum((hard_valid AND CAST(available_at AS TIME)<>TIME '15:30:00')::INTEGER)
        FROM minute"""
    ).fetchone()
    audit = {
        "daily_rows": int(daily_audit[0]),
        "daily_symbols": int(daily_audit[1]),
        "daily_first": str(daily_audit[2]),
        "daily_last": str(daily_audit[3]),
        "daily_time_travel": int(daily_audit[4]),
        "daily_lineage_failures": int(daily_audit[5]),
        "minute_rows": int(minute_audit[0]),
        "minute_symbols": int(minute_audit[1]),
        "minute_first": str(minute_audit[2]),
        "minute_last": str(minute_audit[3]),
        "minute_lineage_failures": int(minute_audit[4]),
        "minute_non_1530_hard_valid": int(minute_audit[5]),
    }
    expected = {
        "daily_rows": 6155390,
        "daily_symbols": 5262,
        "daily_first": "2018-01-02",
        "daily_last": "2023-12-29",
        "daily_time_travel": 0,
        "daily_lineage_failures": 0,
        "minute_rows": 6114413,
        "minute_symbols": 5235,
        "minute_first": "2018-01-02",
        "minute_last": "2023-12-29",
        "minute_lineage_failures": 0,
        "minute_non_1530_hard_valid": 0,
    }
    if audit != expected:
        raise CycleError(f"source audit changed: {audit}")
    con.execute("""CREATE TEMP TABLE calendar AS SELECT trade_date,
        row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM daily) ORDER BY trade_date""")
    calendar = [
        row[0] for row in con.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()
    ]
    con.execute("""CREATE TEMP TABLE base AS SELECT d.*,c.cal_idx,
      (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
       AND d.industry_valid IS TRUE AND d.float_valid IS TRUE AND d.corporate_action_valid IS TRUE
       AND d.market_valid IS TRUE AND d.market_rule_valid IS TRUE
       AND d.historical_identity_valid IS TRUE AND d.corporate_action_blocking IS FALSE
       AND coalesce(d.rights_ratio,0)=0 AND d.available_at IS NOT NULL
       AND d.available_at<=d.decision_at AND d.open>0 AND d.high>=greatest(d.open,d.close)
       AND d.low<=least(d.open,d.close) AND d.close>0
       AND d.volume>=0 AND d.amount>=0) history_valid,
      (d.hard_valid IS TRUE AND d.trade_status=1 AND d.current_day_data_tradable IS TRUE
       AND d.is_st IS FALSE) current_valid,
      lag(d.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
      lag(d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
       AND d.industry_valid IS TRUE AND d.float_valid IS TRUE AND d.corporate_action_valid IS TRUE
       AND d.market_valid IS TRUE AND d.market_rule_valid IS TRUE
       AND d.historical_identity_valid IS TRUE AND d.corporate_action_blocking IS FALSE
       AND coalesce(d.rights_ratio,0)=0 AND d.available_at IS NOT NULL
       AND d.available_at<=d.decision_at AND d.open>0 AND d.high>=greatest(d.open,d.close)
       AND d.low<=least(d.open,d.close) AND d.close>0
       AND d.volume>=0 AND d.amount>=0) OVER w previous_history_valid
      FROM daily d JOIN calendar c USING(trade_date)
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)""")
    con.execute("""CREATE TEMP TABLE steps AS SELECT *,CASE
      WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
       AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
      WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
       AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
       AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
       AND coalesce(share_multiplier,1)>0 AND previous_close-coalesce(cash_per_share,0)>0
      THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
      ELSE NULL END step_log_return FROM base""")
    con.execute("""CREATE TEMP TABLE coordinates AS SELECT *,
      median(step_log_return) OVER (PARTITION BY trade_date) market_median_step,
      sum(coalesce(step_log_return,0)) OVER
        (PARTITION BY symbol ORDER BY trade_date ROWS UNBOUNDED PRECEDING) log_coordinate
      FROM steps""")
    con.execute("""CREATE TEMP TABLE rolling AS SELECT *,
      sum(step_log_return) OVER w5 r5,sum(step_log_return) OVER w20 r20,
      count(step_log_return) OVER w120 valid_steps120,lag(cal_idx,120) OVER ws cal_idx_lag120,
      avg(amount) OVER p5 avg_amount5,avg(amount) OVER p20 avg_amount20,
      avg(amount) OVER p20long avg_amount20_prior,count(*) OVER p20 prior_count20,
      exp(log_coordinate)*open/close coordinate_open,
      lag(exp(log_coordinate)) OVER ws previous_coordinate_close
      FROM coordinates WINDOW ws AS (PARTITION BY symbol ORDER BY trade_date),
      w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
      w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
      w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
      p5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
      p20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
      p20long AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 25 PRECEDING AND 6 PRECEDING)""")
    con.execute("""CREATE TEMP TABLE joined AS SELECT r.*,m.available_at minute_available_at,
      m.snapshot_id minute_snapshot_id,m.opening_30m_return,m.closing_30m_return,
      m.close_vs_vwap,m.last_hour_volume_share,m.realized_volatility,
      avg(m.realized_volatility) OVER (PARTITION BY r.symbol ORDER BY r.trade_date
        ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) prior5_realized_volatility
      FROM rolling r JOIN minute m USING(symbol,trade_date)
      WHERE m.hard_valid IS TRUE AND m.session_complete IS TRUE AND m.available_at IS NOT NULL
        AND m.available_at<=CAST(r.trade_date AS TIMESTAMP)+INTERVAL '15 hours 30 minutes'
        AND m.snapshot_id IS NOT NULL""")
    con.execute("""CREATE TEMP TABLE eligible0 AS SELECT *,
      (high-low)/nullif(preclose,0) daily_range,
      amount/nullif(avg_amount5,0)-avg_amount5/nullif(avg_amount20_prior,0) liquidity_recovery_score
      FROM joined WHERE current_valid AND history_valid AND cal_idx>=120 AND cal_idx%5=4
      AND valid_steps120=120 AND cal_idx-cal_idx_lag120=120 AND prior_count20=20
      AND avg_amount20>=50000000 AND coordinate_open>0 AND previous_coordinate_close>0
      AND isfinite(r5) AND isfinite(r20) AND isfinite(step_log_return)
      AND isfinite(opening_30m_return) AND isfinite(closing_30m_return)
      AND isfinite(close_vs_vwap) AND isfinite(last_hour_volume_share)
      AND realized_volatility>0 AND prior5_realized_volatility>0""")
    con.execute("""CREATE TEMP TABLE eligible1 AS SELECT *,
      count(*) OVER (PARTITION BY trade_date,industry) industry_count,
      (sum(r5) OVER (PARTITION BY trade_date,industry)-r5)
       /nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0) industry_loo_r5,
      (sum(r20) OVER (PARTITION BY trade_date,industry)-r20)
       /nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0) industry_loo_r20,
      (sum((r20>0)::INTEGER) OVER (PARTITION BY trade_date,industry)-(r20>0)::INTEGER)
       /nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0) industry_loo_diffusion,
      (sum(close_vs_vwap) OVER (PARTITION BY trade_date,industry)-close_vs_vwap)
       /nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0) industry_loo_vwap
      FROM eligible0""")
    frame = con.execute("""SELECT *,
      lag(cal_idx) OVER (PARTITION BY symbol ORDER BY trade_date) prior_week_cal_idx,
      lag(industry_loo_r20) OVER (PARTITION BY symbol ORDER BY trade_date)
        prior_week_industry_loo_r20,
      lag(industry_loo_diffusion) OVER (PARTITION BY symbol ORDER BY trade_date)
        prior_week_industry_loo_diffusion
      FROM eligible1 ORDER BY trade_date,symbol""").fetchdf()
    con.close()
    if frame.duplicated(["symbol", "trade_date"]).any() or frame.empty:
        raise CycleError("invalid eligible frame")
    return frame, calendar, audit


def _rank(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True)


def _residualize(group: pd.DataFrame) -> pd.Series:
    valid = (
        group[["raw_rank", "control_return", "control_range", "control_r20"]].notna().all(axis=1)
    )
    output = pd.Series(np.nan, index=group.index)
    if valid.sum() < 20:
        return output
    y = group.loc[valid, "raw_rank"].to_numpy(float)
    x = group.loc[valid, ["control_return", "control_range", "control_r20"]].to_numpy(float)
    x = np.column_stack([np.ones(len(x)), x])
    output.loc[valid] = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
    return output


def _family_scores(frame: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = frame.copy()
    base["control_return"] = base.groupby("trade_date")["step_log_return"].transform(_rank)
    base["control_range"] = base.groupby("trade_date")["daily_range"].transform(_rank)
    base["control_r20"] = base.groupby("trade_date")["r20"].transform(_rank)
    ranked_vwap = base.groupby("trade_date")["close_vs_vwap"].transform(_rank)
    ranked_close = base.groupby("trade_date")["closing_30m_return"].transform(_rank)
    ranked_late_volume = base.groupby("trade_date")["last_hour_volume_share"].transform(_rank)
    ranked_quiet = base.groupby("trade_date")["realized_volatility"].transform(lambda x: _rank(-x))
    definitions: dict[str, tuple[pd.Series, pd.Series]] = {
        "vwap_acceptance": (base.close_vs_vwap, pd.Series(True, index=base.index)),
        "closing_acceptance": (base.closing_30m_return, pd.Series(True, index=base.index)),
        "opening_weakness_recovery": (
            base.closing_30m_return - base.opening_30m_return,
            (base.opening_30m_return < 0) & (base.closing_30m_return > 0),
        ),
        "late_volume_confirmed_demand": (
            (ranked_vwap + ranked_close + ranked_late_volume) / 3,
            pd.Series(True, index=base.index),
        ),
        "intraday_volatility_contraction": (
            -np.log(base.realized_volatility / base.prior5_realized_volatility),
            pd.Series(True, index=base.index),
        ),
        "relative_intraday_strength": (
            base.close_vs_vwap - base.industry_loo_vwap,
            base.industry_count >= 6,
        ),
        "quiet_vwap_acceptance": (
            (ranked_vwap + ranked_quiet) / 2,
            pd.Series(True, index=base.index),
        ),
        "industry_leadership_acceleration": (
            base.industry_loo_r20 - base.prior_week_industry_loo_r20,
            (base.industry_count >= 6) & (base.cal_idx - base.prior_week_cal_idx == 5),
        ),
        "industry_diffusion_acceleration": (
            base.industry_loo_diffusion - base.prior_week_industry_loo_diffusion,
            (base.industry_count >= 6) & (base.cal_idx - base.prior_week_cal_idx == 5),
        ),
        "residual_mean_reversion_5": (-(base.r5 - base.industry_loo_r5), base.industry_count >= 6),
        "liquidity_recovery": (base.liquidity_recovery_score, base.step_log_return > 0),
        "down_market_resilience": (
            base.step_log_return - base.market_median_step,
            base.market_median_step < 0,
        ),
    }
    horizons = {
        row["id"]: int(row["horizon"])
        for track in ("track_a", "track_b")
        for row in spec[track]["families"]
    }
    track_a = {row["id"] for row in spec["track_a"]["families"]}
    family_rows: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []
    for family, (score, mask) in definitions.items():
        work = base.loc[mask].copy()
        work["raw_score"] = score.loc[mask]
        work = work.loc[np.isfinite(work.raw_score)].copy()
        work["raw_rank"] = work.groupby("trade_date")["raw_score"].transform(_rank)
        correlations = {
            control: float(work[["raw_rank", control]].corr().iloc[0, 1])
            for control in ("control_return", "control_range", "control_r20")
        }
        if family in track_a:
            work["signal_score"] = (
                work.groupby("trade_date", group_keys=False)
                .apply(_residualize, include_groups=False)
                .reindex(work.index)
            )
        else:
            work["signal_score"] = work.raw_rank
        work = work.loc[np.isfinite(work.signal_score)].copy()
        work["family"] = family
        work["leg"] = "top"
        work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
        work["signal_rank"] = work.groupby("trade_date")["signal_score"].rank(
            method="first", ascending=False
        )
        keep = work.loc[
            work.signal_rank <= 20,
            [
                "family",
                "leg",
                "trade_date",
                "cal_idx",
                "minute_available_at",
                "symbol",
                "industry",
                "signal_score",
                "raw_score",
                "signal_rank",
                "candidate_count",
                "avg_amount20",
            ],
        ]
        keep = keep.rename(columns={"minute_available_at": "available_at"})
        keep["decision_at"] = pd.to_datetime(keep.trade_date) + pd.Timedelta(hours=15, minutes=30)
        keep["natural_horizon"] = horizons[family]
        family_rows.append(keep)
        diagnostics.append(
            {
                "family": family,
                "track": "A" if family in track_a else "B",
                "eligible_rows": len(work),
                "decision_dates": int(work.trade_date.nunique()),
                "median_candidates": float(work.groupby("trade_date").size().median()),
                "daily_control_correlations": correlations,
                "maximum_absolute_daily_control_correlation": max(
                    abs(value) for value in correlations.values()
                ),
            }
        )
    control = base.copy()
    control["family"] = "date_control"
    control["leg"] = "control"
    control["candidate_count"] = control.groupby("trade_date").symbol.transform("size")
    control["signal_rank"] = control.apply(
        lambda row: hashlib.sha256(f"{row.symbol}|004|{row.trade_date}".encode()).hexdigest(),
        axis=1,
    )
    control = (
        control.sort_values(["trade_date", "signal_rank", "symbol"]).groupby("trade_date").head(20)
    )
    control["signal_rank"] = control.groupby("trade_date").cumcount() + 1
    control["decision_at"] = pd.to_datetime(control.trade_date) + pd.Timedelta(hours=15, minutes=30)
    control["available_at"] = control["minute_available_at"]
    control["signal_score"] = np.nan
    control["raw_score"] = np.nan
    control["natural_horizon"] = 20
    columns = [
        "family",
        "leg",
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "signal_score",
        "raw_score",
        "signal_rank",
        "candidate_count",
        "avg_amount20",
        "natural_horizon",
    ]
    selections = pd.concat([*family_rows, control[columns]], ignore_index=True)[columns]
    selections = selections.sort_values(
        ["family", "leg", "trade_date", "signal_rank", "symbol"]
    ).reset_index(drop=True)
    if selections.duplicated(["family", "leg", "trade_date", "symbol"]).any():
        raise CycleError("duplicate selection")
    return selections, pd.DataFrame(diagnostics)


def _decisions(
    spec: dict[str, Any], summary: pd.DataFrame, panel: pd.DataFrame, diagnostics: pd.DataFrame
) -> list[dict[str, Any]]:
    controls = summary.loc[(summary.family == "date_control") & (summary.leg == "control")]
    diagnostic_map = diagnostics.set_index("family").to_dict("index")
    output: list[dict[str, Any]] = []
    for track in ("track_a", "track_b"):
        for family_spec in spec[track]["families"]:
            family = family_spec["id"]
            horizon = int(family_spec["horizon"])
            rows = summary.loc[
                (summary.family == family) & (summary.leg == "top") & (summary.horizon == horizon)
            ].set_index("period")
            control = controls.loc[controls.horizon == horizon].set_index("period")
            full = rows.loc["full"]
            early = rows.loc["early_2018_2020"]
            late = rows.loc["late_2021_2023"]
            severe_disadvantage = float(
                full.severe_loss_fraction - control.loc["full", "severe_loss_fraction"]
            )
            gates = {
                "complete_positions": int(full["count"]) >= 500,
                "decision_dates_each_block": int(early.signal_dates) >= 40
                and int(late.signal_dates) >= 40,
                "entry_executable_fraction": float(full.entry_executable_fraction) >= 0.90,
                "full_excess": float(full.mean_excess_vs_date_control) > 0,
                "early_excess": float(early.mean_excess_vs_date_control) >= 0,
                "late_excess": float(late.mean_excess_vs_date_control) >= 0,
                "severe_loss": severe_disadvantage <= 0.01,
                "candidate_breadth": float(diagnostic_map[family]["median_candidates"]) >= 20,
                "daily_incrementality": track == "track_b"
                or float(diagnostic_map[family]["maximum_absolute_daily_control_correlation"])
                <= 0.80,
            }
            passed = all(gates.values())
            classification = "STANDALONE_ALPHA" if passed else "NO_USEFUL_EVIDENCE"
            if track == "track_a" and not gates["daily_incrementality"]:
                classification = "REDUNDANT_WITH_DAILY"
            elif (
                not passed
                and float(full.mean_excess_vs_date_control) > 0
                and min(
                    float(early.mean_excess_vs_date_control),
                    float(late.mean_excess_vs_date_control),
                )
                >= 0
            ):
                classification = "COMPLEMENTARY_INFORMATION"
            elif (
                not passed
                and severe_disadvantage <= -0.02
                and float(full.mean_excess_vs_date_control) >= -0.001
            ):
                classification = "RISK_INFORMATION"
            elif (
                not passed
                and float(early.mean_excess_vs_date_control)
                * float(late.mean_excess_vs_date_control)
                < 0
            ):
                classification = "CONDITIONAL_INFORMATION"
            output.append(
                {
                    "family": family,
                    "track": "A" if track == "track_a" else "B",
                    "mechanism": family_spec["mechanism"],
                    "natural_horizon": horizon,
                    "information_classification": classification,
                    "passes_all_screen_gates": passed,
                    "gate_results": gates,
                    "full_excess": float(full.mean_excess_vs_date_control),
                    "early_excess": float(early.mean_excess_vs_date_control),
                    "late_excess": float(late.mean_excess_vs_date_control),
                    "minimum_block_excess": min(
                        float(early.mean_excess_vs_date_control),
                        float(late.mean_excess_vs_date_control),
                    ),
                    "severe_loss_disadvantage": severe_disadvantage,
                    "complete_positions": int(full["count"]),
                    "diagnostics": diagnostic_map[family],
                }
            )
    for track, maximum in (("A", 2), ("B", 1)):
        passed = sorted(
            (row for row in output if row["track"] == track and row["passes_all_screen_gates"]),
            key=lambda row: (
                row["minimum_block_excess"],
                row["full_excess"],
                -row["severe_loss_disadvantage"],
                row["family"],
            ),
            reverse=True,
        )
        promoted = {row["family"] for row in passed[:maximum]}
        for row in output:
            if row["track"] == track:
                row["executable_decision"] = (
                    "PROMOTE_EXECUTABLE"
                    if row["family"] in promoted
                    else (
                        "PASSED_NOT_EXECUTED_MAXIMUM"
                        if row["passes_all_screen_gates"]
                        else "NO_EXECUTABLE_REPLAY"
                    )
                )
    return output


def _make_plans(panel: pd.DataFrame, promoted: list[str], calendar: list[date]) -> pd.DataFrame:
    index = {day: idx for idx, day in enumerate(calendar)}
    plans: list[dict[str, Any]] = []
    for family in promoted:
        rows = panel.loc[
            (panel.family == family) & (panel.leg == "top") & (panel.signal_rank <= 10)
        ]
        for row in rows.itertuples(index=False):
            signal_date = pd.Timestamp(row.trade_date).date()
            entry = index[signal_date] + 1
            due = entry + int(row.natural_horizon)
            if due < len(calendar):
                plans.append(
                    {
                        "family": family,
                        "signal_date": signal_date,
                        "symbol": row.symbol,
                        "industry": str(row.industry),
                        "entry_index": entry,
                        "due_index": due,
                        "horizon": int(row.natural_horizon),
                    }
                )
    return pd.DataFrame(plans)


def _classify_replay(spec: dict[str, Any], replay: dict[str, Any]) -> str:
    candidate = spec["executable_replay"]["candidate_all_required"]
    if (
        replay["status"] == "COMPLETE"
        and replay["terminal_open_lots"] == 0
        and replay["entry_execution_fraction"] >= candidate["entry_executable_fraction_min"]
        and replay["total_return"] > 0
        and replay["daily_sharpe"] >= candidate["sharpe_min"]
        and replay["maximum_drawdown"] >= candidate["max_drawdown_min"]
        and replay["severe_trade_fraction"] <= candidate["severe_loss_fraction_max"]
    ):
        return "STRATEGY_CANDIDATE"
    mixed = spec["executable_replay"]["promising_but_mixed_all_required"]
    if (
        replay["status"] == "COMPLETE"
        and replay["terminal_open_lots"] == 0
        and replay["total_return"] > 0
        and replay["daily_sharpe"] > 0
        and replay["maximum_drawdown"] >= mixed["max_drawdown_min"]
    ):
        return "PROMISING_BUT_MIXED"
    return "PARKED" if replay["status"] == "COMPLETE" else "REPLAY_BLOCKED"


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Stock-level intraday alpha and independent discovery",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            f"The shared causal domain contains {result['eligible_rows']:,} eligible rows, "
            f"{result['eligible_symbols']:,} symbols, and {result['decision_dates']} weekly "
            "decisions. All signals use completed-session CY008 summaries available at 15:30 "
            "and enter no earlier than the next market open. Track-A selection is the same-date "
            "cross-sectional residual after three frozen daily controls."
        ),
        "",
        "## Cheap screens",
        "",
        (
            "| Track | Family | Mechanism | Eligible | Dates | Median breadth | "
            "Max daily-control correlation | Full excess | Early | Late | "
            "Severe disadvantage | Role | Decision |"
        ),
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in result["decisions"]:
        diagnostic = row["diagnostics"]
        lines.append(
            f"| {row['track']} | {row['family']} | {row['mechanism']} | "
            f"{diagnostic['eligible_rows']:,} | {diagnostic['decision_dates']} | "
            f"{diagnostic['median_candidates']:.0f} | "
            f"{diagnostic['maximum_absolute_daily_control_correlation']:.3f} | "
            f"{row['full_excess']:.4%} | {row['early_excess']:.4%} | "
            f"{row['late_excess']:.4%} | {row['severe_loss_disadvantage']:.4%} | "
            f"{row['information_classification']} | {row['executable_decision']} |"
        )
    lines += [
        "",
        "## Frozen executable replays",
        "",
        (
            "| Family | Classification | Total | Annualized | Max DD | Sharpe | Severe | "
            "Turnover | Mean names | Mean industries | Capacity p10 |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for replay in result["replays"]:
        if replay["status"] != "COMPLETE":
            lines.append(
                f"| {replay['family']} | {replay['classification']} | "
                "— | — | — | — | — | — | — | — | — |"
            )
            continue
        lines.append(
            f"| {replay['family']} | {replay['classification']} | "
            f"{replay['total_return']:.2%} | {replay['annualized_return']:.2%} | "
            f"{replay['maximum_drawdown']:.2%} | {replay['daily_sharpe']:.3f} | "
            f"{replay['severe_trade_fraction']:.2%} | "
            f"{replay['turnover_multiple_initial_capital']:.2f}x | "
            f"{replay['mean_positions']:.1f} | {replay['mean_industries']:.1f} | "
            f"CNY {replay['p10_capacity_cny_at_5pct_amount']:,.0f} |"
        )
    lines += [
        "",
        (
            "Post-2023 outcomes and CY011 were not accessed. Industry Diffusion, Low "
            "Idiosyncratic Volatility, the CHINEXT RS veto, minute-volatility overlay, "
            "Industry Rotation, and resource-parked dispersion were not modified or retuned."
        ),
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, minute_paths = _input_paths()
    with tempfile.TemporaryDirectory(prefix="ashare-cycle-004-") as temp:
        frame, calendar, audit = _build_frame(daily_paths, minute_paths, Path(temp))
    selections, diagnostics = _family_scores(frame, spec)
    panel, future_rows = DIVERSIFIED._attach_screen_outcomes(daily_paths, selections, calendar)
    summary = PRIOR._screen_summary(panel)
    decisions = _decisions(spec, summary, panel, diagnostics)
    promoted = [
        row["family"] for row in decisions if row["executable_decision"] == "PROMOTE_EXECUTABLE"
    ]
    replays: list[dict[str, Any]] = []
    equities: list[pd.DataFrame] = []
    risk_exits: list[pd.DataFrame] = []
    action_audit: dict[str, Any] = {"not_run": not promoted}
    if promoted:
        plans = _make_plans(panel, promoted, calendar)
        market_rows = DIVERSIFIED._query_execution_rows(daily_paths, plans, calendar)
        ca_spec = json.loads(
            _resolve(spec["inputs"]["ca_contract_spec"]["path"]).read_text(encoding="utf-8")
        )
        events, action_audit = CA._load_risk_events(ca_spec, calendar)
        for family in promoted:
            try:
                replay, equity, exits = CA._replay(family, plans, market_rows, calendar, events)
            except CA.CorporateActionReplayError as error:
                replay = {
                    "family": family,
                    "status": "BLOCKED_DATA_CONTRACT",
                    "blocker": str(error),
                }
                equity = pd.DataFrame()
                exits = pd.DataFrame()
            replay["classification"] = _classify_replay(spec, replay)
            replays.append(replay)
            if not equity.empty:
                equities.append(equity)
            if not exits.empty:
                risk_exits.append(exits)
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_FROZEN_TWO_TRACK_DISCOVERY",
        "input_audit": audit,
        "eligible_rows": len(frame),
        "eligible_symbols": int(frame.symbol.nunique()),
        "decision_dates": int(frame.trade_date.nunique()),
        "future_path_rows_read": future_rows,
        "feature_diagnostics": diagnostics.to_dict("records"),
        "decisions": decisions,
        "promoted_families": promoted,
        "replays": replays,
        "action_audit": action_audit,
        "preserved_status": {
            "industry_diffusion": "PROMISING_BUT_MIXED_UNCHANGED",
            "low_idiosyncratic_volatility": "PROMISING_BUT_MIXED_UNCHANGED",
            "chinext_rs_veto": "FROZEN_UNCHANGED",
            "minute_volatility_overlay": "DOWNGRADED_UNCHANGED",
            "industry_rotation": "CLOSED_UNCHANGED",
            "dispersion": "RESOURCE_PARKED_UNCHANGED",
        },
        "questions": {
            "what_market_behavior_are_we_still_not_studying": (
                "Order-flow imbalance, auction microstructure, objective stock-level support "
                "tests, and order-book liquidity are absent from accepted inputs."
            ),
            "new_strategy_archetype_implied": (
                "No; diffusion acceleration remains within the existing participation and "
                "diffusion archetype, and quiet VWAP acceptance has unresolved executable "
                "economics."
            ),
        },
    }
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    pd.concat(equities, ignore_index=True).to_csv(
        EQUITY_PATH, index=False
    ) if equities else pd.DataFrame().to_csv(EQUITY_PATH, index=False)
    if risk_exits:
        pd.concat(risk_exits, ignore_index=True).to_csv(RISK_EXIT_PATH, index=False)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
        "summary_sha256": sha256_file(SUMMARY_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
        "risk_exits_sha256": sha256_file(RISK_EXIT_PATH) if RISK_EXIT_PATH.is_file() else None,
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
