#!/usr/bin/env python3
"""Run frozen external-prior replication, internal chip discovery, and combinations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-EXTERNAL-PRIOR-CYCLE-005_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-EXTERNAL-PRIOR-CYCLE-005_candidate_panel.csv"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-EXTERNAL-PRIOR-CYCLE-005_screen_summary.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-EXTERNAL-PRIOR-CYCLE-005_equity.csv"
EXIT_PATH = PROGRAM / "artifacts/ASHARE-EXTERNAL-PRIOR-CYCLE-005_risk_exits.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-EXTERNAL-PRIOR-CYCLE-005_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-EXTERNAL-PRIOR-CYCLE-005_report.md"
CYCLE4_SCRIPT = PROGRAM / "scripts/run_ashare_intraday_indep_cycle_004.py"
DIVERSIFIED_SCRIPT = PROGRAM / "scripts/run_ashare_diversified_cycle_002.py"
CA_SCRIPT = PROGRAM / "scripts/run_ashare_ca_replay_003.py"
EXPECTED_SPEC_SHA256 = "afb8e407f5a9154b4d0606d6882b752a04b8079f0fba9a6288c9db1f77faa6fa"
COST = 0.002


class Cycle005Error(RuntimeError):
    """Fail-closed error for cycle 005."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise Cycle005Error(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE4 = _load_module("ashare_cycle_004_for_005", CYCLE4_SCRIPT)
DIVERSIFIED = _load_module("ashare_diversified_002_for_005", DIVERSIFIED_SCRIPT)
CA = _load_module("ashare_ca_003_for_005", CA_SCRIPT)


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
        raise Cycle005Error("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_ALL_TRACKS_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise Cycle005Error("all tracks were not frozen before outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Cycle005Error(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "habitat", "quiet-VWAP"):
        if phrase not in prohibited:
            raise Cycle005Error(f"missing prohibition: {phrase}")
    return spec


def _configure(temp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET memory_limit='6GB'")
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
        raise Cycle005Error(f"source audit changed: {audit}")
    con.execute(
        """CREATE TEMP TABLE calendar AS SELECT trade_date,
        row_number() OVER (ORDER BY trade_date)-1 AS cal_idx,
        lead(month(trade_date)) OVER (ORDER BY trade_date)<>month(trade_date) AS month_end
        FROM (SELECT DISTINCT trade_date FROM daily) ORDER BY trade_date"""
    )
    calendar = [
        row[0] for row in con.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()
    ]
    con.execute(
        """CREATE TEMP TABLE base AS SELECT d.*,c.cal_idx,c.month_end,
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
      ELSE NULL END step_log_return FROM base"""
    )
    con.execute(
        """CREATE TEMP TABLE coordinates AS SELECT *,
      median(step_log_return) OVER (PARTITION BY trade_date) market_median_step,
      sum(coalesce(step_log_return,0)) OVER
        (PARTITION BY symbol ORDER BY trade_date ROWS UNBOUNDED PRECEDING) log_coordinate
      FROM steps"""
    )
    con.execute(
        """CREATE TEMP TABLE rolling AS SELECT *,
      exp(log_coordinate) coordinate_close,
      exp(log_coordinate)*high/close coordinate_high,
      sum(step_log_return) OVER w5 r5,
      sum(step_log_return) OVER w20 r20,
      sum(step_log_return) OVER w120 r120,
      sum(step_log_return) OVER w240 r240,
      max(step_log_return) OVER w20 max_return20,
      sum(ln(close/open)) OVER w5 intraday_return5,
      max(exp(log_coordinate)*high/close) OVER w252 high252,
      count(step_log_return) OVER w252 valid_steps252,
      lag(cal_idx,252) OVER ws cal_idx_lag252,
      avg(amount) OVER p20 avg_amount20,count(*) OVER p20 prior_count20,
      stddev_samp(step_log_return-market_median_step) OVER w20 idio_vol20
      FROM coordinates WINDOW ws AS (PARTITION BY symbol ORDER BY trade_date),
      w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
      w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
      w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
      w240 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 239 PRECEDING AND CURRENT ROW),
      w252 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW),
      p20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)"""
    )
    con.execute(
        """CREATE TEMP TABLE eligible0 AS SELECT r.*,m.available_at minute_available_at,
      m.snapshot_id minute_snapshot_id,
      -list_sum(list_transform(list_zip(m.chip_prices,m.chip_volumes),
        x -> CASE WHEN x[1]>r.close THEN x[2] ELSE 0 END))/nullif(list_sum(m.chip_volumes),0)
        chip_overhang_clearance,
      list_sum(list_transform(list_zip(m.chip_prices,m.chip_volumes),
        x -> CASE WHEN x[1]>=0.97*r.close AND x[1]<=r.close THEN x[2] ELSE 0 END))
        /nullif(list_sum(m.chip_volumes),0) chip_support_density,
      -sqrt(list_sum(list_transform(list_zip(m.chip_prices,m.chip_volumes),
        x -> x[2]*pow(ln(x[1]/r.close),2)))/nullif(list_sum(m.chip_volumes),0))
        chip_cost_concentration
      FROM rolling r JOIN minute m USING(symbol,trade_date)
      WHERE r.current_valid AND r.history_valid AND r.cal_idx>=252
        AND (r.cal_idx%5=4 OR r.month_end)
        AND r.valid_steps252=252 AND r.cal_idx-r.cal_idx_lag252=252
        AND r.prior_count20=20 AND r.avg_amount20>=50000000
        AND isfinite(r.r5) AND isfinite(r.r20) AND isfinite(r.r120) AND isfinite(r.r240)
        AND isfinite(r.max_return20) AND isfinite(r.intraday_return5)
        AND r.high252>0 AND r.coordinate_close>0 AND isfinite(r.idio_vol20)
        AND m.hard_valid IS TRUE AND m.session_complete IS TRUE
        AND m.available_at<=CAST(r.trade_date AS TIMESTAMP)+INTERVAL '15 hours 30 minutes'
        AND m.snapshot_id IS NOT NULL AND list_sum(m.chip_volumes)>0"""
    )
    con.execute(
        """CREATE TEMP TABLE eligible1 AS SELECT *,
      count(*) OVER (PARTITION BY trade_date,industry) industry_count,
      (sum(r120) OVER (PARTITION BY trade_date,industry)-r120)
       /nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0) industry_loo_r120,
      (sum((r20>0)::INTEGER) OVER (PARTITION BY trade_date,industry)-(r20>0)::INTEGER)
       /nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0) industry_loo_diffusion
      FROM eligible0"""
    )
    frame = con.execute(
        """SELECT *,lag(cal_idx) OVER (PARTITION BY symbol ORDER BY trade_date) prior_week_cal_idx,
      lag(industry_loo_diffusion) OVER (PARTITION BY symbol ORDER BY trade_date)
        prior_week_industry_loo_diffusion
      FROM eligible1 ORDER BY trade_date,symbol"""
    ).fetchdf()
    con.close()
    if frame.empty or frame.duplicated(["symbol", "trade_date"]).any():
        raise Cycle005Error("invalid eligible frame")
    return frame, calendar, audit


def _rank(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True)


def _select(frame: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    weekly = frame.cal_idx % 5 == 4
    monthly = frame.month_end.fillna(False).astype(bool)
    exact_week = frame.cal_idx - frame.prior_week_cal_idx == 5
    diffusion_accel = frame.industry_loo_diffusion - frame.prior_week_industry_loo_diffusion
    max_rank = frame.groupby("trade_date")["max_return20"].transform(lambda x: _rank(-x))
    low_idio_rank = frame.groupby("trade_date")["idio_vol20"].transform(lambda x: _rank(-x))
    diffusion_rank = diffusion_accel.groupby(frame.trade_date).transform(_rank)
    definitions: dict[str, tuple[pd.Series, pd.Series, str, int, int]] = {
        "jt_momentum_12_1": (frame.r240 - frame.r20, monthly, "external", 120, 20),
        "gh_52_week_high": (frame.coordinate_close / frame.high252, monthly, "external", 120, 20),
        "industry_momentum_120": (
            frame.industry_loo_r120,
            monthly & (frame.industry_count >= 6),
            "external",
            120,
            20,
        ),
        "max_lottery_20": (-frame.max_return20, monthly, "external", 20, 20),
        "intraday_reversal_5": (-frame.intraday_return5, weekly, "external", 5, 5),
        "chip_overhang_clearance": (frame.chip_overhang_clearance, weekly, "internal", 20, 5),
        "chip_support_density": (frame.chip_support_density, weekly, "internal", 20, 5),
        "chip_cost_concentration": (frame.chip_cost_concentration, weekly, "internal", 20, 5),
        "max_lottery_plus_low_idio": (
            (max_rank + low_idio_rank) / 2,
            monthly,
            "combination",
            20,
            20,
        ),
        "diffusion_accel_plus_low_idio": (
            (diffusion_rank + low_idio_rank) / 2,
            weekly & exact_week & (frame.industry_count >= 6),
            "combination",
            20,
            5,
        ),
    }
    outputs: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []
    for family, (score, mask, track, horizon, rebalance) in definitions.items():
        work = frame.loc[mask].copy()
        work["signal_score"] = score.loc[mask]
        work = work.loc[np.isfinite(work.signal_score)].copy()
        work["family"] = family
        work["leg"] = "top"
        work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
        work = work.sort_values(
            ["trade_date", "signal_score", "symbol"], ascending=[True, False, True]
        )
        work["signal_rank"] = work.groupby("trade_date").cumcount() + 1
        selected = work.loc[work.signal_rank <= 20].copy()
        selected["natural_horizon"] = horizon
        selected["rebalance_sessions"] = rebalance
        selected["track"] = track
        minute_signal = family in {
            "intraday_reversal_5",
            "chip_overhang_clearance",
            "chip_support_density",
            "chip_cost_concentration",
        }
        selected["decision_at"] = pd.to_datetime(selected.trade_date) + pd.Timedelta(
            hours=15, minutes=30 if minute_signal else 0
        )
        if minute_signal:
            selected["available_at"] = selected.minute_available_at
        columns = [
            "family",
            "track",
            "leg",
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
        outputs.append(selected[columns])
        diagnostics.append(
            {
                "family": family,
                "track": track,
                "eligible_rows": len(work),
                "decision_dates": int(work.trade_date.nunique()),
                "median_candidates": float(work.groupby("trade_date").size().median()),
                "median_avg_amount20_cny": float(work.avg_amount20.median()),
            }
        )
    control = frame.copy()
    control["family"] = "date_control"
    control["track"] = "control"
    control["leg"] = "control"
    control["candidate_count"] = control.groupby("trade_date").symbol.transform("size")
    control["hash_order"] = control.apply(
        lambda row: hashlib.sha256(f"{row.symbol}|005|{row.trade_date}".encode()).hexdigest(),
        axis=1,
    )
    control = (
        control.sort_values(["trade_date", "hash_order", "symbol"]).groupby("trade_date").head(20)
    )
    control["signal_rank"] = control.groupby("trade_date").cumcount() + 1
    control["signal_score"] = np.nan
    control["natural_horizon"] = 120
    control["rebalance_sessions"] = 5
    control["decision_at"] = pd.to_datetime(control.trade_date) + pd.Timedelta(hours=15, minutes=30)
    control["available_at"] = control.minute_available_at
    columns = [
        "family",
        "track",
        "leg",
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
    selections = pd.concat([*outputs, control[columns]], ignore_index=True)[columns]
    selections = selections.sort_values(
        ["family", "trade_date", "signal_rank", "symbol"]
    ).reset_index(drop=True)
    if selections.duplicated(["family", "trade_date", "symbol"]).any():
        raise Cycle005Error("duplicate selection")
    return selections, pd.DataFrame(diagnostics)


def _future_links(selections: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    cal_index = {day: index for index, day in enumerate(calendar)}
    rows: list[tuple[int, str, date, int]] = []
    for candidate in selections.itertuples():
        signal = pd.Timestamp(candidate.trade_date).date()
        start = cal_index[signal]
        final_horizon = min(int(candidate.natural_horizon), len(calendar) - start - 1)
        for horizon in range(1, final_horizon + 1):
            rows.append((candidate.Index, candidate.symbol, calendar[start + horizon], horizon))
    return pd.DataFrame(rows, columns=["candidate_row", "symbol", "trade_date", "horizon"])


def _screen_outcome(group: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {"entry_status": "MISSING_PATH"}
    for horizon in (5, 20, 120):
        output[f"status_h{horizon}"] = "INCOMPLETE"
    group = group.sort_values("horizon")
    if group.empty or group.horizon.tolist() != list(range(1, len(group) + 1)):
        return output
    entry = group.iloc[0]
    if not (
        bool(entry.hard_valid)
        and int(entry.trade_status) == 1
        and bool(entry.current_day_data_tradable)
        and not bool(entry.buy_blocked_open)
        and float(entry.open) > 0
        and pd.Timestamp(entry.available_at).date() <= pd.Timestamp(entry.trade_date).date()
    ):
        output["entry_status"] = "NEXT_OPEN_NOT_EXECUTABLE"
        return output
    output["entry_status"] = "EXECUTABLE"
    entry_open = float(entry.open)
    shares = 1.0
    cash = 0.0
    adverse = math.inf
    for row in group.itertuples(index=False):
        prices = (row.high, row.low, row.close)
        if (
            not bool(row.hard_valid)
            or pd.Timestamp(row.available_at).date() > pd.Timestamp(row.trade_date).date()
            or not all(
                value is not None and math.isfinite(float(value)) and float(value) > 0
                for value in prices
            )
        ):
            return output
        if row.horizon > 1 and int(row.corporate_action_count or 0) > 0:
            action = CYCLE4.PRIOR._visible_action(row)
            if action is None:
                return output
            multiplier, cash_per_share = action
            cash += shares * cash_per_share
            shares *= multiplier
        adverse = min(adverse, (cash + shares * float(row.low)) / entry_open - 1)
        if row.horizon in (5, 20, 120):
            gross = (cash + shares * float(row.close)) / entry_open - 1
            net = (cash + shares * float(row.close) * (1 - COST)) / (entry_open * (1 + COST)) - 1
            output.update(
                {
                    f"status_h{row.horizon}": "COMPLETE",
                    f"gross_return_h{row.horizon}": gross,
                    f"net_return_h{row.horizon}": net,
                    f"adverse_excursion_h{row.horizon}": adverse,
                    f"entry_amount_h{row.horizon}": float(entry.amount),
                }
            )
    return output


def _attach_outcomes(
    daily_paths: list[Path], selections: pd.DataFrame, calendar: list[date]
) -> tuple[pd.DataFrame, int]:
    links = _future_links(selections, calendar)
    rows = CYCLE4.PRIOR._query_path_rows(daily_paths, links)
    outcomes = {
        int(key): _screen_outcome(group) for key, group in rows.groupby("candidate_row", sort=True)
    }
    panel = selections.join(pd.DataFrame.from_dict(outcomes, orient="index"), how="left")
    panel["entry_status"] = panel.entry_status.fillna("MISSING_PATH")
    for horizon in (5, 20, 120):
        panel[f"status_h{horizon}"] = panel[f"status_h{horizon}"].fillna("INCOMPLETE")
    return panel, len(rows)


def _summary(panel: pd.DataFrame) -> pd.DataFrame:
    years = pd.to_datetime(panel.trade_date).dt.year
    masks = {
        "full": pd.Series(True, index=panel.index),
        "early_2018_2020": years <= 2020,
        "late_2021_2023": years >= 2021,
    }
    controls = panel.loc[panel.family == "date_control"]
    control_means = {
        h: controls.loc[controls[f"status_h{h}"] == "COMPLETE"]
        .groupby("trade_date")[f"net_return_h{h}"]
        .mean()
        for h in (5, 20, 120)
    }
    rows = []
    for family, group in panel.loc[panel.family != "date_control"].groupby("family", sort=True):
        horizon = int(group.natural_horizon.iloc[0])
        for period, mask in masks.items():
            subset = group.loc[mask.loc[group.index]]
            valid = subset.loc[subset[f"status_h{horizon}"] == "COMPLETE"]
            returns = valid[f"net_return_h{horizon}"].astype(float)
            comparison = valid.trade_date.map(control_means[horizon])
            comparable = comparison.notna()
            valid = valid.loc[comparable]
            returns = returns.loc[comparable]
            comparison = comparison.loc[comparable]
            excess = returns - comparison
            rows.append(
                {
                    "family": family,
                    "track": group.track.iloc[0],
                    "period": period,
                    "horizon": horizon,
                    "count": len(valid),
                    "signal_dates": int(valid.trade_date.nunique()),
                    "mean_return": returns.mean(),
                    "median_return": returns.median(),
                    "mean_excess_vs_date_control": excess.mean(),
                    "severe_loss_fraction": float((returns <= -0.10).mean()),
                    "control_severe_loss_fraction": float((comparison <= -0.10).mean()),
                    "severe_loss_disadvantage": float(
                        (returns <= -0.10).mean() - (comparison <= -0.10).mean()
                    ),
                    "entry_executable_fraction": float(subset.entry_status.eq("EXECUTABLE").mean()),
                    "median_candidate_count": float(subset.candidate_count.median()),
                    "median_avg_amount20_cny": float(subset.avg_amount20.median()),
                    "p10_entry_amount_cny": valid[f"entry_amount_h{horizon}"].quantile(0.10),
                }
            )
    return pd.DataFrame(rows).sort_values(["family", "period"]).reset_index(drop=True)


def _screen_decisions(
    spec: dict[str, Any], summary: pd.DataFrame, diagnostics: pd.DataFrame
) -> list[dict[str, Any]]:
    diag = diagnostics.set_index("family").to_dict("index")
    decisions = []
    for family, rows in summary.groupby("family", sort=True):
        indexed = rows.set_index("period")
        full = indexed.loc["full"]
        early = indexed.loc["early_2018_2020"]
        late = indexed.loc["late_2021_2023"]
        monthly = int(full.horizon) == 120 or family in {
            "max_lottery_20",
            "max_lottery_plus_low_idio",
        }
        gates = {
            "complete_positions": int(full["count"]) >= (300 if monthly else 500),
            "decision_dates_each_block": int(early.signal_dates) >= (20 if monthly else 40)
            and int(late.signal_dates) >= (20 if monthly else 40),
            "entry_executable_fraction": float(full.entry_executable_fraction) >= 0.90,
            "full_excess": float(full.mean_excess_vs_date_control) > 0,
            "both_block_excess": min(
                float(early.mean_excess_vs_date_control), float(late.mean_excess_vs_date_control)
            )
            >= 0,
            "severe_loss": float(full.severe_loss_disadvantage) <= 0.02,
            "candidate_breadth": float(diag[family]["median_candidates"]) >= 20,
        }
        decisions.append(
            {
                "family": family,
                "track": str(full.track),
                "natural_horizon": int(full.horizon),
                "passes_all_screen_gates": all(gates.values()),
                "gate_results": gates,
                "full_excess": float(full.mean_excess_vs_date_control),
                "early_excess": float(early.mean_excess_vs_date_control),
                "late_excess": float(late.mean_excess_vs_date_control),
                "minimum_block_excess": min(
                    float(early.mean_excess_vs_date_control),
                    float(late.mean_excess_vs_date_control),
                ),
                "severe_loss_disadvantage": float(full.severe_loss_disadvantage),
                "complete_positions": int(full["count"]),
                "diagnostics": diag[family],
            }
        )
    for track, maximum in (("external", 3), ("internal", 1)):
        eligible = sorted(
            (row for row in decisions if row["track"] == track and row["passes_all_screen_gates"]),
            key=lambda row: (
                row["minimum_block_excess"],
                row["full_excess"],
                -row["severe_loss_disadvantage"],
                row["family"],
            ),
            reverse=True,
        )
        promoted = {row["family"] for row in eligible[:maximum]}
        for row in decisions:
            if row["track"] == track:
                row["replay_decision"] = (
                    "PROMOTE_EXECUTABLE"
                    if row["family"] in promoted
                    else (
                        "PASSED_NOT_EXECUTED_MAXIMUM"
                        if row["passes_all_screen_gates"]
                        else "NO_REPLAY"
                    )
                )
    combo_map = {row["family"]: row for row in decisions}
    for row in decisions:
        if row["track"] != "combination":
            continue
        inputs = (
            ("max_lottery_20",)
            if row["family"] == "max_lottery_plus_low_idio"
            else ("industry_diffusion_acceleration",)
        )
        baseline = combo_map.get(inputs[0])
        if baseline is None:
            # Cycle-004 diffusion acceleration is bound; use its frozen screen values.
            baseline = {
                "full_excess": 0.0096624735514221,
                "minimum_block_excess": 0.007287406787514674,
                "severe_loss_disadvantage": -0.03483237168775313,
            }
        improvement = row["full_excess"] - baseline["full_excess"]
        severe_improvement = baseline["severe_loss_disadvantage"] - row["severe_loss_disadvantage"]
        incremental = (
            row["passes_all_screen_gates"]
            and improvement >= 0.001
            and row["minimum_block_excess"] >= baseline["minimum_block_excess"]
            and (improvement >= 0.002 or severe_improvement >= 0.01)
        )
        row["incremental_vs_named_baseline"] = {
            "baseline": inputs[0],
            "full_excess_improvement": improvement,
            "severe_disadvantage_improvement": severe_improvement,
            "passes": incremental,
        }
        row["replay_decision"] = (
            "PROMOTE_INCREMENTAL_COMBINATION" if incremental else "COMPLEXITY_NOT_EARNED"
        )
    return decisions


@dataclass
class Lot:
    symbol: str
    industry: str
    due_index: int
    shares: float
    invested_cost: float
    action_cash: float = 0.0
    forced_effective_date: date | None = None
    forced_event_id: str | None = None


def _plans(panel: pd.DataFrame, promoted: list[str], calendar: list[date]) -> pd.DataFrame:
    index = {day: i for i, day in enumerate(calendar)}
    output = []
    for family in promoted:
        for row in panel.loc[(panel.family == family) & (panel.signal_rank <= 10)].itertuples(
            index=False
        ):
            signal = pd.Timestamp(row.trade_date).date()
            entry = index[signal] + 1
            due = entry + int(row.natural_horizon)
            if due < len(calendar):
                output.append(
                    {
                        "family": family,
                        "signal_date": signal,
                        "symbol": row.symbol,
                        "industry": str(row.industry),
                        "entry_index": entry,
                        "due_index": due,
                        "horizon": int(row.natural_horizon),
                        "rebalance_sessions": int(row.rebalance_sessions),
                    }
                )
    return pd.DataFrame(output)


def _replay(
    family: str,
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    family_plans = plans.loc[plans.family == family]
    horizon = int(family_plans.horizon.iloc[0])
    rebalance = int(family_plans.rebalance_sessions.iloc[0])
    vintages = math.ceil(horizon / rebalance)
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    entry_map = {
        int(i): list(group.itertuples(index=False))
        for i, group in family_plans.groupby("entry_index", sort=True)
    }
    event_decisions, symbol_events = CA._event_maps(events)
    initial = 10_000_000.0
    cash = initial
    lots = []
    turnover = 0.0
    planned_entries = entries = risk_blocked = completed = severe = forced_exits = (
        forced_pending
    ) = 0
    capacity = []
    nav_rows = []
    exit_rows = []
    start = int(family_plans.entry_index.min())
    final_due = int(family_plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)
    for cal_index in range(start, final_index + 1):
        current = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current >= lot.forced_effective_date:
                raise Cycle005Error(
                    f"pre-effective exit failed:{family}:{lot.symbol}:{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current))
            if row is None or not CA._holding_row_usable(row):
                raise Cycle005Error(f"invalid holding row:{family}:{lot.symbol}:{current}")
            if int(row.corporate_action_count or 0) > 0:
                action = CA.PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise Cycle005Error(f"unresolved action:{family}:{lot.symbol}:{current}")
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise Cycle005Error(
                        f"share event reached effective date:{family}:{lot.symbol}:{current}"
                    )
                lot.action_cash += lot.shares * cash_per_share
        survivors = []
        for lot in lots:
            row = row_map[(lot.symbol, current)]
            forced = lot.forced_effective_date is not None
            due = cal_index >= lot.due_index
            if not forced and not due:
                survivors.append(lot)
                continue
            if not CA._sellable(row):
                forced_pending += int(forced)
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1 - COST)
            cash += proceeds
            turnover += gross
            completed += 1
            severe += int(proceeds / lot.invested_cost - 1 <= -0.10)
            forced_exits += int(forced)
            if forced:
                exit_rows.append(
                    {
                        "family": family,
                        "symbol": lot.symbol,
                        "event_id": lot.forced_event_id,
                        "effective_date": lot.forced_effective_date,
                        "fill_date": current,
                        "fill_price": float(row.open),
                        "shares": lot.shares,
                    }
                )
        lots = survivors
        pre_nav = cash + sum(
            lot.action_cash + lot.shares * float(row_map[(lot.symbol, current)].open)
            for lot in lots
        )
        planned = entry_map.get(cal_index, [])
        planned_entries += len(planned)
        executable = []
        for plan in planned:
            row = row_map.get((plan.symbol, current))
            if CA._entry_blocked(plan.symbol, plan.signal_date, current, symbol_events):
                risk_blocked += 1
                continue
            if (
                row is not None
                and CA.PRIOR._valid_market_row(row)
                and int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        cohort = min(cash, pre_nav / vintages)
        if executable and cohort > 0:
            allocation = cohort / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1 + COST))
                gross = shares * float(row.open)
                invested = gross * (1 + COST)
                cash -= invested
                turnover += gross
                lots.append(
                    Lot(plan.symbol, str(plan.industry), int(plan.due_index), shares, invested)
                )
                entries += 1
                capacity.append(float(row.amount) * 0.05 * len(executable) * vintages)
        for lot in lots:
            for event in event_decisions.get((lot.symbol, current), ()):
                if (
                    lot.forced_effective_date is None
                    or event.effective_date < lot.forced_effective_date
                ):
                    lot.forced_effective_date = event.effective_date
                    lot.forced_event_id = event.event_id
        nav = cash
        industries = {}
        for lot in lots:
            row = row_map[(lot.symbol, current)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            industries[lot.industry] = industries.get(lot.industry, 0) + value
        invested_value = sum(industries.values())
        hhi = (
            sum((value / invested_value) ** 2 for value in industries.values())
            if invested_value > 0
            else 0
        )
        nav_rows.append(
            {
                "trade_date": current,
                "family": family,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industries),
                "industry_hhi": hhi,
            }
        )
        if cal_index >= final_due and not lots and cal_index not in entry_map:
            break
    equity = pd.DataFrame(nav_rows)
    if lots:
        raise Cycle005Error(f"terminal open lots:{family}:{len(lots)}")
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / initial - 1)
    drawdown = equity.nav / equity.nav.cummax() - 1
    years = len(equity) / 252
    annualized = (equity.nav.iloc[-1] / initial) ** (1 / years) - 1
    volatility = returns.std(ddof=1)
    sharpe = math.sqrt(252) * returns.mean() / volatility if volatility > 0 else 0
    max_dd = float(drawdown.min())
    result = {
        "family": family,
        "status": "COMPLETE",
        "start_date": str(equity.trade_date.iloc[0]),
        "end_date": str(equity.trade_date.iloc[-1]),
        "total_return": float(equity.nav.iloc[-1] / initial - 1),
        "annualized_return": float(annualized),
        "maximum_drawdown": max_dd,
        "daily_sharpe": float(sharpe),
        "calmar": float(annualized / abs(max_dd)) if max_dd < 0 else None,
        "turnover_multiple_initial_capital": float(turnover / initial),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "risk_blocked_entries": risk_blocked,
        "completed_trades": completed,
        "severe_trade_fraction": float(severe / completed),
        "forced_pre_effective_exits": forced_exits,
        "forced_exit_pending_days": forced_pending,
        "terminal_open_lots": len(lots),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
    }
    return result, equity, pd.DataFrame(exit_rows)


def _classify(spec: dict[str, Any], replay: dict[str, Any]) -> str:
    if replay["status"] != "COMPLETE" or replay.get("terminal_open_lots") != 0:
        return "REPLAY_BLOCKED"
    gate = spec["replay"]["candidate_all_required"]
    if (
        replay["entry_execution_fraction"] >= gate["entry_execution_fraction_min"]
        and replay["total_return"] > 0
        and replay["daily_sharpe"] >= gate["sharpe_min"]
        and replay["maximum_drawdown"] >= gate["maximum_drawdown_min"]
        and replay["severe_trade_fraction"] <= gate["severe_trade_fraction_max"]
    ):
        return "REPLICATES_STRONGLY" if replay.get("track") == "external" else "STRATEGY_CANDIDATE"
    mixed = spec["replay"]["mixed_all_required"]
    if (
        replay["total_return"] > 0
        and replay["daily_sharpe"] > 0
        and replay["maximum_drawdown"] >= mixed["maximum_drawdown_min"]
    ):
        return "REPLICATES_WEAKLY" if replay.get("track") == "external" else "PROMISING_BUT_MIXED"
    return "ADVERSE" if replay["total_return"] < 0 else "ECONOMICALLY_NULL"


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# External strategy prior replication and internal discovery",
        "",
        f"Status: `{result['status']}`.",
        "",
        f"Shared domain: {result['eligible_rows']:,} eligible rows, "
        f"{result['eligible_symbols']:,} symbols, {result['decision_dates']} union "
        "decision dates (weekly anchors plus calendar month-ends). All outcomes are "
        "consumed 2018--2023 development evidence.",
        "",
        "## Cheap screens",
        "",
        "| Track | Family | Horizon | Full excess | Early | Late | "
        "Severe disadvantage | Classification | Replay |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in result["decisions"]:
        lines.append(
            f"| {row['track']} | {row['family']} | {row['natural_horizon']} | "
            f"{row['full_excess']:.4%} | {row['early_excess']:.4%} | "
            f"{row['late_excess']:.4%} | {row['severe_loss_disadvantage']:.4%} | "
            f"{row['classification']} | {row['replay_decision']} |"
        )
    lines += [
        "",
        "## Executable replays",
        "",
        "| Family | Track | Classification | Total | Annualized | Max DD | Sharpe | "
        "Severe | Turnover | Trades | Mean names | Capacity p10 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["replays"]:
        if row["status"] != "COMPLETE":
            lines.append(
                f"| {row['family']} | {row['track']} | {row['classification']} | "
                "— | — | — | — | — | — | — | — | — |"
            )
            continue
        lines.append(
            f"| {row['family']} | {row['track']} | {row['classification']} | "
            f"{row['total_return']:.2%} | {row['annualized_return']:.2%} | "
            f"{row['maximum_drawdown']:.2%} | {row['daily_sharpe']:.3f} | "
            f"{row['severe_trade_fraction']:.2%} | "
            f"{row['turnover_multiple_initial_capital']:.2f}x | "
            f"{row['completed_trades']:,} | {row['mean_positions']:.1f} | "
            f"CNY {row['p10_capacity_cny_at_5pct_amount']:,.0f} |"
        )
    lines += [
        "",
        "Canonical BAB and pairs implementations conflict with A-share shorting/leverage "
        "constraints. Residual momentum lacks registered PIT factor inputs. Amihud's "
        "annual characteristic was not silently changed into a monthly proxy. The prior "
        "price-limit continuation formulation remains adverse and was not rerun.",
        "",
        "Post-2023 outcomes and CY-011 were not read. No habitat, parameter search, or "
        "preserved-candidate tuning was used.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, minute_paths = CYCLE4._input_paths()
    with tempfile.TemporaryDirectory(prefix="ashare-cycle-005-") as temp:
        frame, calendar, audit = _build_frame(daily_paths, minute_paths, Path(temp))
    selections, diagnostics = _select(frame, spec)
    panel, future_rows = _attach_outcomes(daily_paths, selections, calendar)
    summary = _summary(panel)
    decisions = _screen_decisions(spec, summary, diagnostics)
    for row in decisions:
        if row["track"] == "external":
            row["classification"] = (
                "REPLICATES_WEAKLY"
                if row["passes_all_screen_gates"]
                else (
                    "CHRONOLOGICALLY_MIXED"
                    if row["early_excess"] * row["late_excess"] < 0
                    else ("ADVERSE" if row["full_excess"] < 0 else "ECONOMICALLY_NULL")
                )
            )
        elif row["track"] == "internal":
            row["classification"] = (
                "STANDALONE_ALPHA_SCREEN"
                if row["passes_all_screen_gates"]
                else (
                    "CHRONOLOGICALLY_MIXED"
                    if row["early_excess"] * row["late_excess"] < 0
                    else ("ADVERSE" if row["full_excess"] < 0 else "ECONOMICALLY_NULL")
                )
            )
        else:
            row["classification"] = (
                "INCREMENTAL_COMBINATION"
                if row["replay_decision"] == "PROMOTE_INCREMENTAL_COMBINATION"
                else "COMPLEXITY_NOT_EARNED"
            )
    promoted = [
        row["family"]
        for row in decisions
        if row["replay_decision"] in {"PROMOTE_EXECUTABLE", "PROMOTE_INCREMENTAL_COMBINATION"}
    ]
    plans = _plans(panel, promoted, calendar) if promoted else pd.DataFrame()
    replays = []
    equities = []
    exits = []
    action_audit = {"not_run": not promoted}
    if promoted:
        market_rows = DIVERSIFIED._query_execution_rows(daily_paths, plans, calendar)
        ca_spec = json.loads((PROGRAM / "experiments/ASHARE-CA-REPLAY-003_spec.json").read_text())
        events, action_audit = CA._load_risk_events(ca_spec, calendar)
        decision_map = {row["family"]: row for row in decisions}
        for family in promoted:
            try:
                replay, equity, risk_exits = _replay(family, plans, market_rows, calendar, events)
            except Cycle005Error as error:
                replay = {
                    "family": family,
                    "status": "BLOCKED_DATA_CONTRACT",
                    "blocker": str(error),
                }
                equity = pd.DataFrame()
                risk_exits = pd.DataFrame()
            replay["track"] = decision_map[family]["track"]
            replay["classification"] = _classify(spec, replay)
            replays.append(replay)
            if not equity.empty:
                equities.append(equity)
            if not risk_exits.empty:
                exits.append(risk_exits)
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_EXTERNAL_PRIOR_INTERNAL_COMBINATION_CYCLE",
        "input_audit": audit,
        "eligible_rows": len(frame),
        "eligible_symbols": int(frame.symbol.nunique()),
        "decision_dates": int(frame.trade_date.nunique()),
        "future_path_rows_read": future_rows,
        "prior_map": {
            "total": 10,
            "newly_screened": 5,
            "not_newly_tested": spec["external_not_newly_tested"],
        },
        "diagnostics": diagnostics.to_dict("records"),
        "decisions": decisions,
        "promoted_families": promoted,
        "replays": replays,
        "action_audit": action_audit,
        "preserved_status": {
            "chinext_rs_veto": "FROZEN",
            "industry_diffusion": "PROMISING_BUT_MIXED",
            "industry_diffusion_acceleration": "PROMISING_BUT_MIXED",
            "industry_leadership_acceleration": "COMPLEMENTARY_INFORMATION",
            "low_idiosyncratic_volatility": "PROMISING_BUT_MIXED",
            "quiet_vwap_acceptance": "WEAK_COMPLEMENTARY_REPLAY_BLOCKED",
            "minute_volatility_overlay": "DOWNGRADED_CLOSED",
            "industry_rotation": "CLOSED",
        },
        "questions": {
            "what_market_behavior_are_we_still_not_studying": (
                "PIT fundamentals, borrow-feasible short legs, order-book flow, and "
                "independent post-development confirmation."
            ),
            "new_strategy_archetype_implied": None,
        },
    }
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    (pd.concat(equities, ignore_index=True) if equities else pd.DataFrame()).to_csv(
        EQUITY_PATH, index=False
    )
    (pd.concat(exits, ignore_index=True) if exits else pd.DataFrame()).to_csv(
        EXIT_PATH, index=False
    )
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "prior_map_sha256": sha256_file(PROGRAM / "STRATEGY_PRIOR_MAP.md"),
        "panel_sha256": sha256_file(PANEL_PATH),
        "summary_sha256": sha256_file(SUMMARY_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
        "risk_exits_sha256": sha256_file(EXIT_PATH),
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
