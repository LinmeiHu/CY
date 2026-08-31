#!/usr/bin/env python3
# ruff: noqa: E501
"""Run low-skew independence, breakdown admission, and bounded alpha discovery."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_result.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_panel.csv"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_summary.csv"
REDUNDANCY_PATH = PROGRAM / "artifacts/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_redundancy.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_equity.csv"
EXIT_PATH = PROGRAM / "artifacts/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_risk_exits.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_report.md"
CHX_OUTPUT = PROGRAM / "artifacts/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_chinext"
CYCLE7_PATH = PROGRAM / "scripts/run_ashare_support_recovery_cycle_007.py"
SHARED_CHX_PATH = PROGRAM / "scripts/run_hab_chx_downrev_strat_001.py"
EXPECTED_SPEC_SHA256 = "eef33288ea86418af7ae2d1b23987a9d95112f1754d437569e899ef6c5a2f1fe"
COST = 0.002


class Cycle008Error(RuntimeError):
    """Fail-closed cycle-008 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise Cycle008Error(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE7 = _load_module("ashare_cycle_007_for_008", CYCLE7_PATH)
CYCLE5 = CYCLE7.CYCLE5
SHARED = _load_module("hab_chx_shared_for_008", SHARED_CHX_PATH)


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise Cycle008Error("frozen cycle-008 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_ALL_TRACKS_BEFORE_NEW_FORWARD_OUTCOME_ACCESS":
        raise Cycle008Error("all tracks were not frozen before outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Cycle008Error(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "breakdown exit-role", "baseline shopping"):
        if phrase not in prohibited:
            raise Cycle008Error(f"missing prohibition: {phrase}")
    return spec


def _configure(temp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET memory_limit='6GB'")
    connection.execute("SET threads=1")
    connection.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def _build_frame(
    daily_paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, list[date], set[tuple[date, str]], set[tuple[date, str]], dict[str, Any]]:
    con = _configure(temp_path)
    con.from_parquet([str(path) for path in daily_paths], union_by_name=True).create_view("daily")
    source = con.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((available_at>decision_at)::INTEGER),
        sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER)
        FROM daily"""
    ).fetchone()
    audit = {
        "rows": int(source[0]),
        "symbols": int(source[1]),
        "first": str(source[2]),
        "last": str(source[3]),
        "time_travel": int(source[4]),
        "lineage_failures": int(source[5]),
    }
    expected = {
        "rows": 6_155_390,
        "symbols": 5_262,
        "first": "2018-01-02",
        "last": "2023-12-29",
        "time_travel": 0,
        "lineage_failures": 0,
    }
    if audit != expected:
        raise Cycle008Error(f"daily source audit changed: {audit}")
    con.execute(
        """CREATE TEMP TABLE calendar AS SELECT trade_date,
        row_number() OVER (ORDER BY trade_date)-1 cal_idx
        FROM (SELECT DISTINCT trade_date FROM daily) ORDER BY trade_date"""
    )
    calendar = [
        row[0] for row in con.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()
    ]
    con.execute(
        """CREATE TEMP TABLE base AS SELECT d.*,c.cal_idx,
        (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.open>0 AND d.high>=greatest(d.open,d.close)
         AND d.low<=least(d.open,d.close) AND d.close>0 AND d.volume>=0 AND d.amount>=0)
          history_valid,
        (d.hard_valid IS TRUE AND d.trade_status=1 AND d.current_day_data_tradable IS TRUE
         AND d.is_st IS FALSE) current_valid,
        lag(d.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
        lag(d.hard_valid IS TRUE AND d.bar_valid IS TRUE
         AND d.trading_state_valid IS TRUE AND d.industry_valid IS TRUE
         AND d.float_valid IS TRUE AND d.corporate_action_valid IS TRUE
         AND d.market_valid IS TRUE AND d.market_rule_valid IS TRUE
         AND d.historical_identity_valid IS TRUE AND d.corporate_action_blocking IS FALSE
         AND coalesce(d.rights_ratio,0)=0 AND d.available_at IS NOT NULL
         AND d.available_at<=d.decision_at AND d.open>0
         AND d.high>=greatest(d.open,d.close) AND d.low<=least(d.open,d.close)
         AND d.close>0 AND d.volume>=0 AND d.amount>=0) OVER w previous_history_valid
        FROM daily d JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)"""
    )
    con.execute(
        """CREATE TEMP TABLE steps AS SELECT *,CASE
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
         AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
         AND coalesce(share_multiplier,1)>0 AND previous_close-coalesce(cash_per_share,0)>0
        THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
        ELSE NULL END step_return FROM base"""
    )
    con.execute(
        """CREATE TEMP TABLE with_market AS SELECT *,
        median(step_return) OVER (PARTITION BY trade_date) market_step
        FROM steps"""
    )
    con.execute(
        """CREATE TEMP TABLE coordinates AS SELECT *,step_return-market_step residual_step,
        sum(coalesce(step_return,0)) OVER (PARTITION BY symbol ORDER BY trade_date) log_coordinate
        FROM with_market"""
    )
    con.execute(
        """CREATE TEMP TABLE paths AS SELECT *,exp(log_coordinate) coordinate_close,
        exp(log_coordinate)*open/close coordinate_open,
        exp(log_coordinate)*low/close coordinate_low,
        lag(exp(log_coordinate)) OVER w previous_coordinate_close,
        sqrt(sum(pow(step_return,2)) OVER w5) rv5,
        (close-low)/nullif(high-low,0) close_location
        FROM coordinates WINDOW
        w AS (PARTITION BY symbol ORDER BY trade_date),
        w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)"""
    )
    con.execute(
        """CREATE TEMP TABLE rolling AS SELECT *,
        min(coordinate_low) OVER p20 support_l20,
        avg(amount) OVER p20 avg_amount20,count(*) OVER p20 prior20_count,
        count(step_return) OVER p20 prior_valid20,
        count(step_return) OVER w120 valid120,lag(cal_idx,120) OVER ws cal_idx_lag120,
        skewness(step_return) OVER w60 return_skew60,
        stddev_samp(residual_step) OVER w20 idio_vol20,
        count(residual_step) OVER w20 residual_count20,
        avg(residual_step) OVER w60 residual_mean60,
        stddev_samp(residual_step) OVER w60 residual_sd60,
        avg(residual_step) FILTER (WHERE market_step<0) OVER w60 down_residual_mean60,
        avg(residual_step) FILTER (WHERE market_step>=0) OVER w60 up_residual_mean60,
        count(*) FILTER (WHERE market_step<0) OVER w60 down_market_count60,
        count(*) FILTER (WHERE market_step>=0) OVER w60 up_market_count60,
        stddev_samp(rv5) OVER w60 vol_of_vol60,
        count(rv5) OVER w60 rv5_count60,
        sum((coordinate_open<previous_coordinate_close)::INTEGER) OVER w60 negative_gap_count60,
        sum((coordinate_open<previous_coordinate_close AND close>open)::INTEGER) OVER w60
          negative_gap_absorbed60,
        avg(close_location) OVER w20 close_location_mean20,
        count(close_location) OVER w20 close_location_count20
        FROM paths WINDOW
        ws AS (PARTITION BY symbol ORDER BY trade_date),
        p20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
        w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW)"""
    )
    con.execute(
        """CREATE TEMP TABLE eligible AS SELECT *,
        -return_skew60 low_skew_score,-idio_vol20 low_idio_score,
        residual_mean60/nullif(residual_sd60,0) residual_sharpe_60,
        down_residual_mean60-up_residual_mean60 down_up_residual_asymmetry_60,
        -vol_of_vol60 low_volatility_of_volatility_60,
        negative_gap_absorbed60/nullif(negative_gap_count60,0) negative_gap_absorption_rate_60,
        close_location_mean20 close_location_persistence_20
        FROM rolling WHERE history_valid AND current_valid AND valid120=120
        AND cal_idx-cal_idx_lag120=120 AND prior20_count=20 AND avg_amount20>=50000000
        AND residual_count20=20 AND cal_idx%20=0"""
    )
    frame = con.execute(
        """SELECT * FROM eligible WHERE isfinite(low_skew_score) AND isfinite(low_idio_score)
        ORDER BY trade_date,symbol"""
    ).fetchdf()
    coverage_rows = con.execute(
        """SELECT trade_date,symbol,coordinate_close<support_l20 breakdown
        FROM rolling WHERE symbol LIKE '30%.SZ' AND history_valid AND current_valid
        AND prior20_count=20 AND prior_valid20=20"""
    ).fetchall()
    con.close()
    coverage = {(row[0], str(row[1])) for row in coverage_rows}
    breakdown = {(row[0], str(row[1])) for row in coverage_rows if bool(row[2])}
    audit["chinext_breakdown_coverage_rows"] = len(coverage)
    audit["chinext_breakdown_rows"] = len(breakdown)
    if frame.empty or frame.duplicated(["symbol", "trade_date"]).any():
        raise Cycle008Error("invalid cycle-008 eligible frame")
    return frame, calendar, coverage, breakdown, audit


def _percentile_rank(group: pd.Series) -> pd.Series:
    return group.rank(method="average", pct=True)


def _prepare_ranks(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = frame.copy()
    work["low_skew_rank"] = work.groupby("trade_date").low_skew_score.transform(_percentile_rank)
    work["low_idio_rank"] = work.groupby("trade_date").low_idio_score.transform(_percentile_rank)

    def residualize(group: pd.DataFrame) -> pd.Series:
        x = group.low_idio_rank.to_numpy(float)
        y = group.low_skew_rank.to_numpy(float)
        variance = float(np.var(x))
        beta = 0.0 if variance == 0 else float(np.cov(x, y, ddof=0)[0, 1] / variance)
        alpha = float(y.mean() - beta * x.mean())
        return pd.Series(y - alpha - beta * x, index=group.index)

    work["low_skew_residual_rank"] = work.groupby("trade_date", group_keys=False).apply(
        residualize, include_groups=False
    )
    correlations = work.groupby("trade_date").apply(
        lambda group: group.low_skew_rank.corr(group.low_idio_rank), include_groups=False
    )
    years = pd.to_datetime(pd.Series(correlations.index), errors="coerce").dt.year.to_numpy()
    values = correlations.to_numpy(float)
    relationship = {
        "median_same_date_rank_correlation": float(np.nanmedian(values)),
        "early_median": float(np.nanmedian(values[years <= 2020])),
        "late_median": float(np.nanmedian(values[years >= 2021])),
        "minimum": float(np.nanmin(values)),
        "maximum": float(np.nanmax(values)),
        "dates": int(np.isfinite(values).sum()),
    }
    for column, label in (("low_idio_rank", "idio"), ("low_skew_rank", "skew")):
        work[f"{label}_tertile"] = work.groupby("trade_date")[column].transform(
            lambda values_: pd.qcut(
                values_.rank(method="first"), 3, labels=["low", "middle", "high"]
            ).astype(str)
        )
    return work, relationship


def _select_top(
    frame: pd.DataFrame,
    family: str,
    score: pd.Series,
    track: str,
    horizon: int,
    count: int = 20,
) -> pd.DataFrame:
    work = frame.loc[np.isfinite(score)].copy()
    work["signal_score"] = score.loc[work.index]
    work["family"] = family
    work["track"] = track
    work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
    work = (
        work.sort_values(["trade_date", "signal_score", "symbol"], ascending=[True, False, True])
        .groupby("trade_date", sort=True)
        .head(count)
    )
    work["signal_rank"] = work.groupby("trade_date").cumcount() + 1
    work["natural_horizon"] = horizon
    work["rebalance_sessions"] = 20
    return work


def _control(frame: pd.DataFrame, family: str, seed: str, track: str = "control") -> pd.DataFrame:
    work = frame.copy()
    work["hash_order"] = work.apply(
        lambda row: hashlib.sha256(f"{row.symbol}|{seed}|{row.trade_date}".encode()).hexdigest(),
        axis=1,
    )
    work = (
        work.sort_values(["trade_date", "hash_order", "symbol"])
        .groupby("trade_date", sort=True)
        .head(20)
    )
    work["family"] = family
    work["track"] = track
    work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
    work["signal_score"] = np.nan
    work["signal_rank"] = work.groupby("trade_date").cumcount() + 1
    work["natural_horizon"] = 20
    work["rebalance_sessions"] = 20
    return work


def _build_selections(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    selections: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []

    def add(selection: pd.DataFrame) -> None:
        selections.append(selection)
        diagnostics.append(
            {
                "family": selection.family.iloc[0],
                "track": selection.track.iloc[0],
                "selected_rows": len(selection),
                "decision_dates": int(selection.trade_date.nunique()),
                "symbols": int(selection.symbol.nunique()),
                "median_candidates": float(selection.candidate_count.median()),
                "median_avg_amount20_cny": float(selection.avg_amount20.median()),
            }
        )

    add(_select_top(frame, "low_skewness_60", frame.low_skew_score, "track_a", 5))
    add(_select_top(frame, "low_idio_20_comparator", frame.low_idio_score, "track_a", 5))
    add(
        _select_top(
            frame,
            "low_skewness_residual_to_low_idio",
            frame.low_skew_residual_rank,
            "track_a_residual",
            5,
        )
    )
    for stratum in ("low", "middle", "high"):
        idio_slice = frame.loc[frame.idio_tertile.eq(stratum)]
        add(
            _select_top(
                idio_slice,
                f"low_skew_within_idio_{stratum}",
                idio_slice.low_skew_score,
                "track_a_conditional",
                5,
            )
        )
        skew_slice = frame.loc[frame.skew_tertile.eq(stratum)]
        add(
            _select_top(
                skew_slice,
                f"low_idio_within_skew_{stratum}",
                skew_slice.low_idio_score,
                "track_a_conditional",
                5,
            )
        )
        idio_control = _control(idio_slice, f"control_idio_{stratum}", f"008I{stratum}")
        idio_control["natural_horizon"] = 5
        add(idio_control)
        skew_control = _control(skew_slice, f"control_skew_{stratum}", f"008S{stratum}")
        skew_control["natural_horizon"] = 5
        add(skew_control)
    track_c = {
        "residual_sharpe_60": (frame.residual_sharpe_60, 20),
        "down_up_residual_asymmetry_60": (frame.down_up_residual_asymmetry_60, 20),
        "low_volatility_of_volatility_60": (frame.low_volatility_of_volatility_60, 20),
        "negative_gap_absorption_rate_60": (
            frame.negative_gap_absorption_rate_60.where(frame.negative_gap_count60 >= 10),
            5,
        ),
        "close_location_persistence_20": (frame.close_location_persistence_20, 5),
    }
    for family, (score, horizon) in track_c.items():
        add(_select_top(frame, family, score, "track_c", horizon))
    global_control = _control(frame, "date_control", "008")
    add(global_control)
    global_control5 = global_control.copy()
    global_control5["family"] = "date_control_h5"
    global_control5["natural_horizon"] = 5
    add(global_control5)
    selection = pd.concat(selections, ignore_index=True)
    selection["decision_at"] = pd.to_datetime(selection.trade_date) + pd.Timedelta(
        hours=15, minutes=30
    )
    columns = [
        "family",
        "track",
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "signal_score",
        "signal_rank",
        "candidate_count",
        "avg_amount20",
        "natural_horizon",
        "rebalance_sessions",
    ]
    selection = selection[columns].sort_values(["family", "trade_date", "signal_rank", "symbol"])
    if selection.duplicated(["family", "trade_date", "symbol"]).any():
        raise Cycle008Error("duplicate selection rows")
    return selection.reset_index(drop=True), pd.DataFrame(diagnostics)


def _control_family(family: str, horizon: int) -> str:
    if family.startswith("low_skew_within_idio_"):
        return "control_idio_" + family.rsplit("_", 1)[-1]
    if family.startswith("low_idio_within_skew_"):
        return "control_skew_" + family.rsplit("_", 1)[-1]
    return "date_control_h5" if horizon == 5 else "date_control"


def _summary(panel: pd.DataFrame) -> pd.DataFrame:
    years = pd.to_datetime(panel.trade_date).dt.year
    masks = {
        "full": pd.Series(True, index=panel.index),
        "early_2018_2020": years <= 2020,
        "late_2021_2023": years >= 2021,
    }
    rows: list[dict[str, Any]] = []
    controls: dict[tuple[str, int], dict[str, pd.Series]] = {}
    for (family, horizon), group in panel.loc[panel.track.eq("control")].groupby(
        ["family", "natural_horizon"]
    ):
        valid = group.loc[group[f"status_h{horizon}"].eq("COMPLETE")]
        controls[(family, int(horizon))] = {
            "return": valid.groupby("trade_date")[f"net_return_h{horizon}"].mean(),
            "severe": valid.groupby("trade_date")[f"net_return_h{horizon}"].apply(
                lambda values: float((values <= -0.10).mean())
            ),
        }
    for family, group in panel.loc[~panel.track.eq("control")].groupby("family", sort=True):
        horizon = int(group.natural_horizon.iloc[0])
        control_name = _control_family(family, horizon)
        comparison = controls[(control_name, horizon)]
        for period, mask in masks.items():
            subset = group.loc[mask.loc[group.index]]
            valid = subset.loc[subset[f"status_h{horizon}"].eq("COMPLETE")].copy()
            valid["control"] = valid.trade_date.map(comparison["return"])
            valid["control_severe"] = valid.trade_date.map(comparison["severe"])
            valid = valid.dropna(subset=["control", "control_severe"])
            returns = valid[f"net_return_h{horizon}"].astype(float)
            rows.append(
                {
                    "family": family,
                    "track": str(group.track.iloc[0]),
                    "period": period,
                    "horizon": horizon,
                    "count": len(valid),
                    "signal_dates": int(valid.trade_date.nunique()),
                    "mean_net_return": returns.mean(),
                    "median_net_return": returns.median(),
                    "net_excess_vs_control": (returns - valid.control).mean(),
                    "severe_loss_fraction": float((returns <= -0.10).mean()),
                    "control_severe_fraction": float(
                        valid.groupby("trade_date").control_severe.first().mean()
                    ),
                    "entry_executable_fraction": float(subset.entry_status.eq("EXECUTABLE").mean()),
                    "median_candidate_count": float(subset.candidate_count.median()),
                    "p10_entry_amount_cny": valid[f"entry_amount_h{horizon}"].quantile(0.10),
                }
            )
    summary = pd.DataFrame(rows)
    return summary.sort_values(["family", "period"]).reset_index(drop=True)


def _period_rows(summary: pd.DataFrame, family: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    rows = summary.loc[summary.family.eq(family)].set_index("period")
    return rows.loc["full"], rows.loc["early_2018_2020"], rows.loc["late_2021_2023"]


def _classify_track_a(
    summary: pd.DataFrame, relationship: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    residual, residual_early, residual_late = _period_rows(
        summary, "low_skewness_residual_to_low_idio"
    )
    skew_conditional: dict[str, Any] = {}
    idio_conditional: dict[str, Any] = {}
    for stratum in ("low", "middle", "high"):
        full, early, late = _period_rows(summary, f"low_skew_within_idio_{stratum}")
        skew_conditional[stratum] = {
            "full": float(full.net_excess_vs_control),
            "early": float(early.net_excess_vs_control),
            "late": float(late.net_excess_vs_control),
        }
        full, early, late = _period_rows(summary, f"low_idio_within_skew_{stratum}")
        idio_conditional[stratum] = {
            "full": float(full.net_excess_vs_control),
            "early": float(early.net_excess_vs_control),
            "late": float(late.net_excess_vs_control),
        }
    residual_pass = all(
        float(value) > 0
        for value in (
            residual.net_excess_vs_control,
            residual_early.net_excess_vs_control,
            residual_late.net_excess_vs_control,
        )
    )
    correlation = abs(float(relationship["median_same_date_rank_correlation"]))
    conditional_full_positive = sum(row["full"] > 0 for row in skew_conditional.values())
    if correlation >= 0.70:
        classification = "MOSTLY_REDUNDANT_WITH_LOW_IDIO"
    elif correlation < 0.50 and residual_pass:
        classification = "DISTINCT_STANDALONE_INFORMATION"
    elif residual_pass or conditional_full_positive >= 2:
        classification = "COMPLEMENTARY_DEFENSIVE_INFORMATION"
    else:
        classification = "NO_INCREMENTAL_VALUE"
    evidence = {
        "relationship": relationship,
        "residual": {
            "full": float(residual.net_excess_vs_control),
            "early": float(residual_early.net_excess_vs_control),
            "late": float(residual_late.net_excess_vs_control),
            "passes": residual_pass,
        },
        "low_skew_within_low_idio_tertiles": skew_conditional,
        "low_idio_within_low_skew_tertiles": idio_conditional,
    }
    return classification, evidence


def _track_c_decisions(summary: pd.DataFrame, diagnostics: pd.DataFrame) -> list[dict[str, Any]]:
    diag = diagnostics.set_index("family").to_dict("index")
    families = sorted(summary.loc[summary.track.eq("track_c"), "family"].unique())
    decisions: list[dict[str, Any]] = []
    for family in families:
        full, early, late = _period_rows(summary, family)
        severe_disadvantage = float(full.severe_loss_fraction - full.control_severe_fraction)
        gates = {
            "complete_positions": int(full["count"]) >= 300,
            "dates_each_block": int(early.signal_dates) >= 20 and int(late.signal_dates) >= 20,
            "execution": float(full.entry_executable_fraction) >= 0.90,
            "full_excess": float(full.net_excess_vs_control) > 0,
            "both_blocks": min(
                float(early.net_excess_vs_control), float(late.net_excess_vs_control)
            )
            >= 0,
            "severe_loss": severe_disadvantage <= 0.02,
            "breadth": float(full.median_candidate_count) >= 20,
        }
        passes = all(gates.values())
        if passes:
            classification = "STANDALONE_ALPHA"
        elif float(early.net_excess_vs_control) * float(late.net_excess_vs_control) < 0:
            classification = "CHRONOLOGICALLY_MIXED"
        elif severe_disadvantage < -0.01 and float(full.net_excess_vs_control) >= 0:
            classification = "DEFENSIVE_INFORMATION"
        elif float(full.net_excess_vs_control) < 0:
            classification = "ADVERSE"
        else:
            classification = "ECONOMICALLY_NULL"
        decisions.append(
            {
                "family": family,
                "natural_horizon": int(full.horizon),
                "classification": classification,
                "passes_all_screen_gates": passes,
                "gates": gates,
                "net_excess": float(full.net_excess_vs_control),
                "early_excess": float(early.net_excess_vs_control),
                "late_excess": float(late.net_excess_vs_control),
                "severe_loss_disadvantage": severe_disadvantage,
                "complete_positions": int(full["count"]),
                "signal_dates": int(full.signal_dates),
                "diagnostics": diag[family],
                "replay_decision": "NO_REPLAY",
            }
        )
    eligible = sorted(
        [row for row in decisions if row["passes_all_screen_gates"]],
        key=lambda row: (
            min(row["early_excess"], row["late_excess"]),
            row["net_excess"],
            -row["severe_loss_disadvantage"],
        ),
        reverse=True,
    )
    for row in eligible[:2]:
        row["replay_decision"] = "PROMOTE_EXECUTABLE"
    return decisions


def _replay_families(
    panel: pd.DataFrame,
    families: list[str],
    daily_paths: list[Path],
    calendar: list[date],
) -> tuple[list[dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    if not families:
        return [], pd.DataFrame(), pd.DataFrame()
    controls = {
        5: "date_control_h5",
        20: "date_control",
    }
    requested = list(families)
    for family in families:
        horizon = int(panel.loc[panel.family.eq(family), "natural_horizon"].iloc[0])
        if controls[horizon] not in requested:
            requested.append(controls[horizon])
    plans = CYCLE5._plans(panel, requested, calendar)
    market = CYCLE5.DIVERSIFIED._query_execution_rows(daily_paths, plans, calendar)
    ca_spec = json.loads((PROGRAM / "experiments/ASHARE-CA-REPLAY-003_spec.json").read_text())
    events, _ = CYCLE5.CA._load_risk_events(ca_spec, calendar)
    results: dict[str, dict[str, Any]] = {}
    equities: list[pd.DataFrame] = []
    exits: list[pd.DataFrame] = []
    for family in requested:
        try:
            replay, equity, risk = CYCLE5._replay(family, plans, market, calendar, events)
            results[family] = replay
            equity["family"] = family
            equities.append(equity)
            if not risk.empty:
                exits.append(risk)
        except Exception as error:  # fail closed per-family; never repair or rescue here
            results[family] = {"family": family, "status": "REPLAY_BLOCKED", "error": str(error)}
    output: list[dict[str, Any]] = []
    for family in families:
        row = dict(results[family])
        if row.get("status") == "REPLAY_BLOCKED":
            row["classification"] = "PARKED_EXECUTION_BLOCKER"
            output.append(row)
            continue
        horizon = int(panel.loc[panel.family.eq(family), "natural_horizon"].iloc[0])
        control = results[controls[horizon]]
        row["control_family"] = controls[horizon]
        row["control_metrics"] = control
        row["total_return_excess_vs_control"] = (
            None
            if control.get("status") == "REPLAY_BLOCKED"
            else float(row["total_return"] - control["total_return"])
        )
        candidate_gate = (
            float(row["total_return"]) > 0
            and row["total_return_excess_vs_control"] is not None
            and float(row["total_return_excess_vs_control"]) > 0
            and float(row["daily_sharpe"]) >= 0.50
            and float(row["maximum_drawdown"]) >= -0.35
            and float(row["severe_trade_fraction"]) <= 0.10
            and int(row["terminal_open_lots"]) == 0
            and float(row["entry_execution_fraction"]) >= 0.90
        )
        if candidate_gate:
            row["classification"] = "STRATEGY_CANDIDATE"
        elif (
            float(row["total_return"]) > 0
            and row["total_return_excess_vs_control"] is not None
            and float(row["total_return_excess_vs_control"]) > 0
            and float(row["daily_sharpe"]) > 0
        ):
            row["classification"] = "PROMISING_BUT_MIXED"
        else:
            row["classification"] = "REJECTED"
        output.append(row)
    return (
        output,
        pd.concat(equities, ignore_index=True) if equities else pd.DataFrame(),
        pd.concat(exits, ignore_index=True) if exits else pd.DataFrame(),
    )


def _new_breakdown_audit() -> dict[str, Any]:
    return {
        "active_sessions": set(),
        "veto_sessions": set(),
        "missing_state_sessions": set(),
        "vetoed_candidate_sessions": set(),
        "vetoed_ranked_candidates": 0,
        "candidate_count": 0,
        "covered_candidate_count": 0,
        "out_of_domain_candidate_count": 0,
        "vetoed_candidate_count": 0,
        "candidate_sessions": set(),
    }


@contextmanager
def _breakdown_context(
    coverage: set[tuple[date, str]],
    breakdown: set[tuple[date, str]],
    audit: dict[str, Any],
) -> Iterator[None]:
    original = SHARED.engine_module.rank_candidates_for_arm

    def filtered_rank(
        candidate_symbols: list[str], rs: dict[str, Any], day: date, policy: Any
    ) -> list[str]:
        if candidate_symbols:
            audit["candidate_sessions"].add(day)
        allowed: list[str] = []
        for symbol in candidate_symbols:
            audit["candidate_count"] += 1
            key = (day, symbol)
            if key not in coverage:
                audit["out_of_domain_candidate_count"] += 1
                allowed.append(symbol)
                continue
            audit["covered_candidate_count"] += 1
            if key in breakdown:
                audit["vetoed_candidate_count"] += 1
                audit["veto_sessions"].add(day)
                audit["vetoed_candidate_sessions"].add(day)
                continue
            allowed.append(symbol)
        ranked = original(allowed, rs, day, policy)
        audit["vetoed_ranked_candidates"] += len(candidate_symbols) - len(allowed)
        return ranked

    SHARED.engine_module.rank_candidates_for_arm = filtered_rank
    try:
        yield
    finally:
        SHARED.engine_module.rank_candidates_for_arm = original


def _run_breakdown_replay(
    coverage: set[tuple[date, str]], breakdown: set[tuple[date, str]]
) -> dict[str, Any]:
    shared_spec = SHARED._load_spec()
    if CHX_OUTPUT.exists():
        shutil.rmtree(CHX_OUTPUT)
    CHX_OUTPUT.mkdir(parents=True, exist_ok=False)
    original_root = SHARED.OUTPUT_ROOT
    original_context = SHARED._admission_veto
    original_audit = SHARED._new_audit

    @contextmanager
    def context(_state: Any, audit: dict[str, Any]) -> Iterator[None]:
        with _breakdown_context(coverage, breakdown, audit):
            yield

    SHARED.OUTPUT_ROOT = CHX_OUTPUT
    SHARED._admission_veto = context
    SHARED._new_audit = _new_breakdown_audit
    try:
        development_engine, development_audit = SHARED._run_development({})
        consumed_engine, consumed_audit = SHARED._run_consumed_block(shared_spec, {})
    finally:
        SHARED.OUTPUT_ROOT = original_root
        SHARED._admission_veto = original_context
        SHARED._new_audit = original_audit
    baselines = SHARED._baseline_metrics(shared_spec)
    candidates = {
        "development_2018_2021": SHARED._candidate_metrics(development_engine),
        "consumed_2022_2023": SHARED._candidate_metrics(consumed_engine),
    }
    comparisons: dict[str, Any] = {}
    audits = {
        "development_2018_2021": development_audit,
        "consumed_2022_2023": consumed_audit,
    }
    for block in candidates:
        comparisons[block] = {
            "baseline": baselines[block],
            "candidate": candidates[block],
            "candidate_minus_baseline": SHARED._delta(candidates[block], baselines[block]),
            "audit": {
                "candidate_sessions": len(audits[block]["candidate_sessions"]),
                "candidate_count": int(audits[block]["candidate_count"]),
                "covered_candidate_count": int(audits[block]["covered_candidate_count"]),
                "out_of_domain_candidate_count": int(
                    audits[block]["out_of_domain_candidate_count"]
                ),
                "vetoed_candidate_count": int(audits[block]["vetoed_candidate_count"]),
                "vetoed_candidate_sessions": len(audits[block]["vetoed_candidate_sessions"]),
            },
        }
    checks = {
        "return_improves_both_blocks": all(
            row["candidate"]["total_return"] > row["baseline"]["total_return"]
            for row in comparisons.values()
        ),
        "drawdown_no_worse_both_blocks": all(
            row["candidate"]["max_drawdown"] >= row["baseline"]["max_drawdown"]
            for row in comparisons.values()
        ),
        "sharpe_improves_both_blocks": all(
            row["candidate"]["sharpe_rf0"] > row["baseline"]["sharpe_rf0"]
            for row in comparisons.values()
        ),
        "severe_loss_no_worse_both_blocks": all(
            row["candidate"]["severe_loss_rate"]
            <= (0.119 if block == "development_2018_2021" else 0.064)
            for block, row in comparisons.items()
        ),
        "zero_same_day_fills": all(
            row["candidate"]["same_day_fills"] == 0 for row in comparisons.values()
        ),
    }
    affected = sum(row["audit"]["vetoed_candidate_count"] for row in comparisons.values())
    if affected == 0:
        classification = "PARKED_NO_AFFECTED_DECISIONS"
    elif all(checks.values()):
        classification = "USEFUL_RISK_COMPONENT"
    elif checks["drawdown_no_worse_both_blocks"] or checks["severe_loss_no_worse_both_blocks"]:
        classification = "PROMISING_BUT_MIXED"
    elif affected > 0:
        classification = "REJECTED"
    return {
        "role": "CHINEXT_V1_NEW_ADMISSION_AVOIDANCE",
        "classification": classification,
        "comparisons": comparisons,
        "checks": checks,
        "alternative_exit_role_opened": False,
    }


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


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _render(result: dict[str, Any]) -> str:
    track_a = result["track_a"]
    residual = track_a["evidence"]["residual"]
    track_b = result["track_b"]
    affected = sum(
        row["audit"]["vetoed_candidate_count"]
        for row in track_b["comparisons"].values()
    )
    lines = [
        "# Low-skew independence, confirmed-breakdown translation, and alpha discovery",
        "",
        f"Status: `{result['status']}`.",
        "",
        "## Low skewness",
        "",
        f"Classification: `{track_a['classification']}`. Median same-date rank "
        f"correlation with Low Idio: {track_a['evidence']['relationship']['median_same_date_rank_correlation']:.3f} "
        f"({track_a['evidence']['relationship']['early_median']:.3f} / "
        f"{track_a['evidence']['relationship']['late_median']:.3f}).",
        f"Residual h5 excess is {residual['full']:.3%} full, "
        f"{residual['early']:.3%} early, and {residual['late']:.3%} late. "
        "No standalone Low-Skew replay was authorized.",
        "",
        "## Confirmed breakdown",
        "",
        f"Role: `{track_b['role']}`. Classification: `{track_b['classification']}`. "
        f"Affected admissions: {affected}.",
        "",
        "## Track C",
        "",
        "| Family | h | Net excess | Early | Late | Severe disadvantage | Classification | Replay |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in result["track_c"]["decisions"]:
        lines.append(
            f"| {row['family']} | {row['natural_horizon']} | {row['net_excess']:.3%} | "
            f"{row['early_excess']:.3%} | {row['late_excess']:.3%} | "
            f"{row['severe_loss_disadvantage']:.3%} | {row['classification']} | "
            f"{row['replay_decision']} |"
        )
    for replay in result["track_c"]["replays"]:
        lines += [
            "",
            f"Executable `{replay['family']}`: total {replay['total_return']:.2%}, "
            f"annualized {replay['annualized_return']:.2%}, max drawdown "
            f"{replay['maximum_drawdown']:.2%}, Sharpe {replay['daily_sharpe']:.3f}, "
            f"severe {replay['severe_trade_fraction']:.2%}, "
            f"classification `{replay['classification']}`.",
        ]
    lines += [
        "",
        "All results use consumed 2018-2023 development history. Post-2023 outcomes and "
        "CY-011 were not read; PIT fundamentals remained parked.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, _ = CYCLE5.CYCLE4._input_paths()
    with tempfile.TemporaryDirectory(prefix="ashare-cycle-008-") as temporary:
        frame, calendar, coverage, breakdown, input_audit = _build_frame(
            daily_paths, Path(temporary)
        )
    frame, relationship = _prepare_ranks(frame)
    selections, diagnostics = _build_selections(frame)
    panel, path_rows = CYCLE5._attach_outcomes(daily_paths, selections, calendar)
    summary = _summary(panel)
    track_a_classification, track_a_evidence = _classify_track_a(summary, relationship)
    track_c_decisions = _track_c_decisions(summary, diagnostics)
    replay_families: list[str] = []
    if track_a_classification == "DISTINCT_STANDALONE_INFORMATION":
        replay_families.append("low_skewness_60")
    replay_families.extend(
        row["family"] for row in track_c_decisions if row["replay_decision"] == "PROMOTE_EXECUTABLE"
    )
    replays, equity, risk_exits = _replay_families(panel, replay_families, daily_paths, calendar)
    track_b = _run_breakdown_replay(coverage, breakdown)
    low_skew_replay = next((row for row in replays if row["family"] == "low_skewness_60"), None)
    track_c_replays = [row for row in replays if row["family"] != "low_skewness_60"]
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_ALL_BOUNDED_TRACKS",
        "honesty_boundary": spec["honesty_boundary"],
        "input_audit": input_audit,
        "eligible_rows": len(frame),
        "eligible_symbols": int(frame.symbol.nunique()),
        "decision_dates": int(frame.trade_date.nunique()),
        "future_path_rows_read": path_rows,
        "track_a": {
            "definition": spec["track_a"],
            "classification": track_a_classification,
            "evidence": track_a_evidence,
            "replay": low_skew_replay,
            "final_status": (
                (
                    "COMPLEMENTARY_ONLY_NO_STANDALONE_REPLAY"
                    if track_a_classification == "COMPLEMENTARY_DEFENSIVE_INFORMATION"
                    else "NO_REPLAY_INCREMENTAL_GATE"
                )
                if low_skew_replay is None
                else low_skew_replay.get("classification", "REPLAY_COMPLETE")
            ),
        },
        "track_b": {**spec["track_b"], **track_b},
        "track_c": {
            "hypotheses": spec["track_c"],
            "decisions": track_c_decisions,
            "replays": track_c_replays,
            "combination": None,
        },
        "preserved_portfolio": {
            "chinext_rs_veto": "UNCHANGED",
            "industry_diffusion": "PROMISING_BUT_MIXED_UNCHANGED",
            "industry_diffusion_acceleration": "PROMISING_BUT_MIXED_UNCHANGED",
            "low_idio": "PROMISING_BUT_MIXED_COMPARATOR_ONLY",
            "industry_leadership_acceleration": "COMPLEMENTARY_UNCHANGED",
            "quiet_vwap": "WEAK_COMPLEMENTARY_REPLAY_BLOCKED_UNCHANGED",
            "minute_volatility_overlay": "COST_SENSITIVE_UNCHANGED",
            "dispersion": "PARKED_RESOURCE_UNCHANGED",
            "pit_fundamentals": "DATA_BLOCKED_PARKED",
        },
        "questions": {
            "what_market_behavior_are_we_still_not_studying": (
                "Order-book and queue pressure, borrow-feasible short legs, immutable-vintage "
                "fundamentals, and independent post-development confirmation."
            ),
            "new_strategy_archetype_implied": None,
        },
    }
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    pd.DataFrame(
        [
            {"measure": key, **(value if isinstance(value, dict) else {"value": value})}
            for key, value in track_a_evidence.items()
        ]
    ).to_csv(REDUNDANCY_PATH, index=False)
    equity.to_csv(EQUITY_PATH, index=False)
    risk_exits.to_csv(EXIT_PATH, index=False)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
        "summary_sha256": sha256_file(SUMMARY_PATH),
        "redundancy_sha256": sha256_file(REDUNDANCY_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
        "risk_exits_sha256": sha256_file(EXIT_PATH),
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
