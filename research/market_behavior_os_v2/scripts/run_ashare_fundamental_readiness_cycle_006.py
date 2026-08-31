#!/usr/bin/env python3
"""Fail-close fundamental readiness and run the frozen daily-data fallback."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_result.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_panel.csv"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_summary.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_equity.csv"
EXIT_PATH = PROGRAM / "artifacts/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_risk_exits.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_report.md"
CYCLE5_SCRIPT = PROGRAM / "scripts/run_ashare_external_prior_cycle_005.py"
EXPECTED_SPEC_SHA256 = "4758aea50fe102c2f038cc5817e4809e2309b4baf91073c88e53f31f44b64b25"
COST = 0.002


class Cycle006Error(RuntimeError):
    """Fail-closed cycle-006 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise Cycle006Error(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE5 = _load_module("ashare_cycle_005_for_006", CYCLE5_SCRIPT)


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise Cycle006Error("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_INTERNAL_FORWARD_OUTCOME_ACCESS":
        raise Cycle006Error("internal hypotheses were not frozen")
    if spec["fundamental_track"]["status"] != "PIT_FUNDAMENTAL_DATA_BLOCKED":
        raise Cycle006Error("fundamental track did not fail closed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Cycle006Error(f"bound input changed: {name}")
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
) -> tuple[pd.DataFrame, list[date], dict[str, Any]]:
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
        raise Cycle006Error(f"daily source audit changed: {audit}")
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
       AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
       AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
       AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
       AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
       AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
       AND d.open>0 AND d.high>=greatest(d.open,d.close)
       AND d.low<=least(d.open,d.close) AND d.close>0 AND d.volume>=0 AND d.amount>=0)
        history_valid,
      (d.hard_valid IS TRUE AND d.trade_status=1
       AND d.current_day_data_tradable IS TRUE AND d.is_st IS FALSE) current_valid,
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
       AND coalesce(share_multiplier,1)>0
       AND previous_close-coalesce(cash_per_share,0)>0
      THEN ln(close/((previous_close-coalesce(cash_per_share,0))
        /coalesce(share_multiplier,1))) ELSE NULL END step_log_return,
      CASE WHEN history_valid AND previous_history_valid
       AND cal_idx-previous_cal_idx=1 AND coalesce(corporate_action_count,0)=0
       AND previous_close>0 AND open>0 THEN ln(open/previous_close) ELSE NULL END
        overnight_log_return
      FROM base"""
    )
    con.execute(
        """CREATE TEMP TABLE rolling AS SELECT *,
      quantile_cont(step_log_return,0.10) OVER w60 left_tail_stability_60,
      -sum(pow(overnight_log_return,2)) OVER w60
       /nullif(sum(pow(step_log_return,2)) OVER w60,0)
        overnight_information_stability_60,
      -avg(CASE WHEN trade_status=1 AND current_day_data_tradable IS TRUE
        AND amount>0 THEN 0.0 ELSE 1.0 END) OVER w60 trading_continuity_60,
      count(step_log_return) OVER w60 valid_steps60,
      count(overnight_log_return) OVER w60 valid_overnights60,
      count(step_log_return) OVER w252 valid_steps252,
      lag(cal_idx,252) OVER ws cal_idx_lag252,
      avg(amount) OVER p20 avg_amount20,count(*) OVER p20 prior_count20,
      median(step_log_return) OVER (PARTITION BY trade_date) market_median_step,
      stddev_samp(step_log_return) OVER w20 raw_vol20
      FROM steps WINDOW ws AS (PARTITION BY symbol ORDER BY trade_date),
      w20 AS (PARTITION BY symbol ORDER BY trade_date
        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
      w60 AS (PARTITION BY symbol ORDER BY trade_date
        ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
      w252 AS (PARTITION BY symbol ORDER BY trade_date
        ROWS BETWEEN 251 PRECEDING AND CURRENT ROW),
      p20 AS (PARTITION BY symbol ORDER BY trade_date
        ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)"""
    )
    frame = con.execute(
        """SELECT * FROM rolling WHERE month_end AND current_valid AND history_valid
      AND cal_idx>=252 AND valid_steps252=252 AND cal_idx-cal_idx_lag252=252
      AND valid_steps60=60 AND valid_overnights60>=50
      AND prior_count20=20 AND avg_amount20>=50000000
      AND isfinite(left_tail_stability_60)
      AND isfinite(overnight_information_stability_60)
      AND isfinite(trading_continuity_60) AND isfinite(raw_vol20)
      ORDER BY trade_date,symbol"""
    ).fetchdf()
    con.close()
    if frame.empty or frame.duplicated(["symbol", "trade_date"]).any():
        raise Cycle006Error("invalid internal eligible frame")
    return frame, calendar, audit


def _rank_legs(work: pd.DataFrame) -> list[pd.DataFrame]:
    work = work.sort_values(["trade_date", "signal_score", "symbol"], ascending=[True, False, True])
    work["descending_rank"] = work.groupby("trade_date").cumcount() + 1
    work["ascending_rank"] = work.groupby("trade_date").cumcount(ascending=False) + 1
    work["middle_distance"] = (work["descending_rank"] - (work["candidate_count"] + 1) / 2).abs()
    legs: list[pd.DataFrame] = []
    for leg, order in (
        ("top", ["trade_date", "descending_rank", "symbol"]),
        ("middle", ["trade_date", "middle_distance", "symbol"]),
        ("bottom", ["trade_date", "ascending_rank", "symbol"]),
    ):
        selected = work.sort_values(order).groupby("trade_date", sort=True).head(20).copy()
        selected["leg"] = leg
        selected["signal_rank"] = selected.groupby("trade_date").cumcount() + 1
        legs.append(selected)
    return legs


def _select(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    definitions = {
        "left_tail_stability_60": frame.left_tail_stability_60,
        "overnight_information_stability_60": frame.overnight_information_stability_60,
        "trading_continuity_60": frame.trading_continuity_60,
    }
    outputs: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []
    for family, score in definitions.items():
        work = frame.copy()
        work["signal_score"] = score
        work = work.loc[np.isfinite(work.signal_score)].copy()
        work["family"] = family
        work["track"] = "internal"
        work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")

        def rank_correlation(group: pd.DataFrame) -> float:
            signal_rank = group.signal_score.rank(pct=True)
            low_vol_rank = (-group.raw_vol20).rank(pct=True)
            if signal_rank.nunique() < 2 or low_vol_rank.nunique() < 2:
                return math.nan
            return float(signal_rank.corr(low_vol_rank))

        correlations = work.groupby("trade_date").apply(rank_correlation, include_groups=False)
        diagnostics.append(
            {
                "family": family,
                "eligible_rows": len(work),
                "decision_dates": int(work.trade_date.nunique()),
                "median_candidates": float(work.groupby("trade_date").size().median()),
                "median_avg_amount20_cny": float(work.avg_amount20.median()),
                "median_date_rank_correlation_with_low_vol": float(correlations.median()),
            }
        )
        outputs.extend(_rank_legs(work))
    control = frame.copy()
    control["family"] = "date_control"
    control["track"] = "control"
    control["leg"] = "control"
    control["signal_score"] = np.nan
    control["candidate_count"] = control.groupby("trade_date").symbol.transform("size")
    control["hash_order"] = control.apply(
        lambda row: hashlib.sha256(f"{row.symbol}|006|{row.trade_date}".encode()).hexdigest(),
        axis=1,
    )
    control = (
        control.sort_values(["trade_date", "hash_order", "symbol"])
        .groupby("trade_date", sort=True)
        .head(20)
    )
    control["signal_rank"] = control.groupby("trade_date").cumcount() + 1
    outputs.append(control)
    selections = pd.concat(outputs, ignore_index=True)
    selections["natural_horizon"] = 20
    selections["rebalance_sessions"] = 20
    selections["decision_at"] = pd.to_datetime(selections.trade_date) + pd.Timedelta(hours=15)
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
    selections = selections[columns].sort_values(
        ["family", "leg", "trade_date", "signal_rank", "symbol"]
    )
    if selections.duplicated(["family", "leg", "trade_date", "symbol"]).any():
        raise Cycle006Error("duplicate selection")
    if (pd.to_datetime(selections.available_at) > selections.decision_at).any():
        raise Cycle006Error("selection availability after decision")
    return selections.reset_index(drop=True), pd.DataFrame(diagnostics)


def _summary(panel: pd.DataFrame) -> pd.DataFrame:
    years = pd.to_datetime(panel.trade_date).dt.year
    masks = {
        "full": pd.Series(True, index=panel.index),
        "early_2018_2020": years <= 2020,
        "late_2021_2023": years >= 2021,
    }
    controls = panel.loc[(panel.family == "date_control") & (panel.status_h20 == "COMPLETE")]
    control_net = controls.groupby("trade_date").net_return_h20.mean()
    control_gross = controls.groupby("trade_date").gross_return_h20.mean()
    control_severe = controls.groupby("trade_date").net_return_h20.apply(
        lambda values: float((values <= -0.10).mean())
    )
    rows: list[dict[str, Any]] = []
    families = panel.loc[panel.family != "date_control"]
    for (family, leg), group in families.groupby(["family", "leg"], sort=True):
        for period, mask in masks.items():
            subset = group.loc[mask.loc[group.index]]
            valid = subset.loc[subset.status_h20 == "COMPLETE"].copy()
            valid["control_net"] = valid.trade_date.map(control_net)
            valid["control_gross"] = valid.trade_date.map(control_gross)
            valid["control_severe"] = valid.trade_date.map(control_severe)
            valid = valid.loc[
                valid.control_net.notna()
                & valid.control_gross.notna()
                & valid.control_severe.notna()
            ]
            net = valid.net_return_h20.astype(float)
            gross = valid.gross_return_h20.astype(float)
            rows.append(
                {
                    "family": family,
                    "leg": leg,
                    "period": period,
                    "count": len(valid),
                    "signal_dates": int(valid.trade_date.nunique()),
                    "mean_gross_return": gross.mean(),
                    "mean_net_return": net.mean(),
                    "median_net_return": net.median(),
                    "gross_excess_vs_date_control": (gross - valid.control_gross).mean(),
                    "net_excess_vs_date_control": (net - valid.control_net).mean(),
                    "severe_loss_fraction": float((net <= -0.10).mean()),
                    "control_severe_loss_fraction": float(valid.control_severe.mean()),
                    "severe_loss_disadvantage": float(
                        (net <= -0.10).mean() - valid.control_severe.mean()
                    ),
                    "entry_executable_fraction": float(subset.entry_status.eq("EXECUTABLE").mean()),
                    "median_candidate_count": float(subset.candidate_count.median()),
                    "median_avg_amount20_cny": float(subset.avg_amount20.median()),
                    "p10_entry_amount_cny": float(valid.entry_amount_h20.quantile(0.10)),
                }
            )
    return pd.DataFrame(rows).sort_values(["family", "leg", "period"])


def _decisions(summary: pd.DataFrame, diagnostics: pd.DataFrame) -> list[dict[str, Any]]:
    diag = diagnostics.set_index("family").to_dict("index")
    decisions: list[dict[str, Any]] = []
    for family, rows in summary.groupby("family", sort=True):
        indexed = rows.set_index(["leg", "period"])
        top = indexed.loc[("top", "full")]
        early = indexed.loc[("top", "early_2018_2020")]
        late = indexed.loc[("top", "late_2021_2023")]
        middle = indexed.loc[("middle", "full")]
        bottom = indexed.loc[("bottom", "full")]
        correlation = diag[family]["median_date_rank_correlation_with_low_vol"]
        gates = {
            "complete_top_positions": int(top["count"]) >= 300,
            "decision_dates_each_block": int(early.signal_dates) >= 20
            and int(late.signal_dates) >= 20,
            "entry_execution_fraction": float(top.entry_executable_fraction) >= 0.90,
            "full_excess": float(top.net_excess_vs_date_control) > 0,
            "both_block_excess": min(
                float(early.net_excess_vs_date_control),
                float(late.net_excess_vs_date_control),
            )
            >= 0,
            "top_middle_bottom_ordered": float(top.mean_net_return)
            >= float(middle.mean_net_return)
            >= float(bottom.mean_net_return),
            "severe_loss": float(top.severe_loss_disadvantage) <= 0.02,
            "candidate_breadth": float(diag[family]["median_candidates"]) >= 20,
            "nonredundant_with_low_vol": abs(float(correlation)) <= 0.80,
        }
        decisions.append(
            {
                "family": family,
                "passes_all_screen_gates": all(gates.values()),
                "gate_results": gates,
                "complete_positions": int(top["count"]),
                "gross_excess": float(top.gross_excess_vs_date_control),
                "net_excess": float(top.net_excess_vs_date_control),
                "early_excess": float(early.net_excess_vs_date_control),
                "late_excess": float(late.net_excess_vs_date_control),
                "severe_loss_disadvantage": float(top.severe_loss_disadvantage),
                "top_mean_net": float(top.mean_net_return),
                "middle_mean_net": float(middle.mean_net_return),
                "bottom_mean_net": float(bottom.mean_net_return),
                "entry_executable_fraction": float(top.entry_executable_fraction),
                "diagnostics": diag[family],
            }
        )
    eligible = sorted(
        (row for row in decisions if row["passes_all_screen_gates"]),
        key=lambda row: (
            min(row["early_excess"], row["late_excess"]),
            row["net_excess"],
            -row["severe_loss_disadvantage"],
            row["family"],
        ),
        reverse=True,
    )
    promoted = {row["family"] for row in eligible[:1]}
    for row in decisions:
        row["replay_decision"] = "PROMOTE_EXECUTABLE" if row["family"] in promoted else "NO_REPLAY"
        if row["passes_all_screen_gates"]:
            row["classification"] = "DEFENSIVE_INFORMATION_SCREEN"
        elif not row["gate_results"]["nonredundant_with_low_vol"]:
            row["classification"] = "REDUNDANT_WITH_LOW_VOL"
        elif row["early_excess"] * row["late_excess"] < 0:
            row["classification"] = "CHRONOLOGICALLY_MIXED"
        elif row["net_excess"] < 0:
            row["classification"] = "ADVERSE"
        else:
            row["classification"] = "ECONOMICALLY_NULL"
    return decisions


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
    lines = [
        "# PIT fundamental readiness and bounded internal fallback",
        "",
        f"Status: `{result['status']}`.",
        "",
        "Fundamental priors were not tested: historical statement revisions are not "
        "available under a registered PIT contract. No data was acquired.",
        "",
        "## Internal fallback screens",
        "",
        "| Family | Gross excess | Net excess | Early | Late | Severe disadvantage | "
        "Top / Middle / Bottom net | Low-vol rank rho | Classification | Replay |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in result["decisions"]:
        lines.append(
            f"| {row['family']} | {row['gross_excess']:.4%} | "
            f"{row['net_excess']:.4%} | {row['early_excess']:.4%} | "
            f"{row['late_excess']:.4%} | {row['severe_loss_disadvantage']:.4%} | "
            f"{row['top_mean_net']:.4%} / {row['middle_mean_net']:.4%} / "
            f"{row['bottom_mean_net']:.4%} | "
            f"{row['diagnostics']['median_date_rank_correlation_with_low_vol']:.3f} | "
            f"{row['classification']} | {row['replay_decision']} |"
        )
    lines += [
        "",
        "## Executable replay",
        "",
        "| Family | Classification | Total | Annualized | Max DD | Sharpe | Severe | "
        "Turnover | Trades | Mean names | Capacity p10 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["replays"]:
        lines.append(
            f"| {row['family']} | {row['classification']} | "
            f"{row['total_return']:.2%} | {row['annualized_return']:.2%} | "
            f"{row['maximum_drawdown']:.2%} | {row['daily_sharpe']:.3f} | "
            f"{row['severe_trade_fraction']:.2%} | "
            f"{row['turnover_multiple_initial_capital']:.2f}x | "
            f"{row['completed_trades']:,} | {row['mean_positions']:.1f} | "
            f"CNY {row['p10_capacity_cny_at_5pct_amount']:,.0f} |"
        )
    lines += [
        "",
        "Post-2023 market outcomes and CY-011 were not read. No fundamental proxy, "
        "combination, habitat, neighboring window, or preserved-candidate tuning was used.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, _ = CYCLE5.CYCLE4._input_paths()
    with tempfile.TemporaryDirectory(prefix="ashare-cycle-006-") as temporary:
        frame, calendar, input_audit = _build_frame(daily_paths, Path(temporary))
    selections, diagnostics = _select(frame)
    panel, path_rows = CYCLE5._attach_outcomes(daily_paths, selections, calendar)
    summary = _summary(panel)
    decisions = _decisions(summary, diagnostics)
    promoted = [
        row["family"] for row in decisions if row["replay_decision"] == "PROMOTE_EXECUTABLE"
    ]
    replays: list[dict[str, Any]] = []
    equities: list[pd.DataFrame] = []
    exits: list[pd.DataFrame] = []
    action_audit: dict[str, Any] = {"not_run": not promoted}
    if promoted:
        top_panel = panel.loc[panel.leg == "top"].copy()
        plans = CYCLE5._plans(top_panel, promoted, calendar)
        market_rows = CYCLE5.DIVERSIFIED._query_execution_rows(daily_paths, plans, calendar)
        ca_spec = json.loads((PROGRAM / "experiments/ASHARE-CA-REPLAY-003_spec.json").read_text())
        events, action_audit = CYCLE5.CA._load_risk_events(ca_spec, calendar)
        for family in promoted:
            replay, equity, risk_exits = CYCLE5._replay(
                family, plans, market_rows, calendar, events
            )
            replay["track"] = "internal"
            replay["classification"] = CYCLE5._classify(spec, replay)
            replays.append(replay)
            equities.append(equity)
            if not risk_exits.empty:
                exits.append(risk_exits)
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": "PIT_FUNDAMENTAL_DATA_BLOCKED_INTERNAL_FALLBACK_COMPLETE",
        "fundamental_track": spec["fundamental_track"],
        "acquisition": {
            "performed": False,
            "external_volume": "/Volumes/quant",
            "research_root_created": False,
            "bytes_written": 0,
        },
        "input_audit": input_audit,
        "eligible_rows": len(frame),
        "eligible_symbols": int(frame.symbol.nunique()),
        "decision_dates": int(frame.trade_date.nunique()),
        "future_path_rows_read": path_rows,
        "diagnostics": diagnostics.to_dict("records"),
        "decisions": decisions,
        "promoted_families": promoted,
        "replays": replays,
        "action_audit": action_audit,
        "combinations": [],
        "preserved_status": {
            "chinext_rs_veto": "FROZEN",
            "industry_diffusion": "PROMISING_BUT_MIXED",
            "industry_diffusion_acceleration": "PROMISING_BUT_MIXED",
            "low_idiosyncratic_volatility": "PROMISING_BUT_MIXED",
            "industry_leadership_acceleration": "COMPLEMENTARY_INFORMATION",
            "quiet_vwap_acceptance": "WEAK_COMPLEMENTARY_REPLAY_BLOCKED",
            "dispersion_relative_value": "PARKED_RESOURCE",
        },
        "questions": {
            "what_market_behavior_are_we_still_not_studying": (
                "Archival PIT fundamentals, borrow-feasible relative value, order-book "
                "flow, and independent post-development confirmation."
            ),
            "new_strategy_archetype_implied": None,
        },
    }
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        "readiness_manifest_sha256": sha256_file(PROGRAM / "FUNDAMENTAL_DATA_MANIFEST.json"),
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
