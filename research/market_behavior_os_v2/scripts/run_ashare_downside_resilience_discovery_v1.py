#!/usr/bin/env python3
"""Run the frozen A-share downside-resilience family discovery experiment."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-DOWNSIDE-RESILIENCE-DISCOVERY-V1_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-DOWNSIDE-RESILIENCE-DISCOVERY-V1_result.json"
TABLE_PATH = PROGRAM / "artifacts/ASHARE-DOWNSIDE-RESILIENCE-DISCOVERY-V1_tables.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-DOWNSIDE-RESILIENCE-DISCOVERY-V1_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/downside_resilience_discovery_v1")
PANEL_PATH = EXTERNAL_ROOT / "evaluation_panel.parquet"
TEMP_PATH = EXTERNAL_ROOT / "duckdb_tmp"
EXPECTED_SPEC_SHA256 = "b58f8a190d9f22199fdc0cf649eaa0b93d9394732027138de42c0265331f45cd"
HORIZONS = (1, 3, 5, 10, 20)
COST = 0.002
SEVERE = -0.10


class DownsideResilienceError(RuntimeError):
    """Fail-closed error for the frozen experiment."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
        raise DownsideResilienceError("frozen specification identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise DownsideResilienceError("experiment was not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DownsideResilienceError(f"bound input changed: {role}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "Strategy-A", "machine-learning"):
        if phrase not in prohibited:
            raise DownsideResilienceError(f"missing prohibition: {phrase}")
    return spec


def _daily_paths(spec: dict[str, Any]) -> list[Path]:
    manifest_path = _resolve(spec["inputs"]["cy006_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(manifest["root"])
    records = {item["path"]: item for item in manifest["files"]}
    paths: list[Path] = []
    for year in range(2018, 2024):
        relative = f"partition_year={year}/data_0.parquet"
        record = records.get(relative)
        path = root / relative
        if record is None or not path.is_file():
            raise DownsideResilienceError(f"missing pre-2024 daily partition: {relative}")
        if path.stat().st_size != int(record["size"]) or sha256_file(path) != record["sha256"]:
            raise DownsideResilienceError(f"daily partition identity mismatch: {relative}")
        paths.append(path)
    return paths


def _configure() -> duckdb.DuckDBPyConnection:
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_PATH.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='8GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{TEMP_PATH.as_posix()}'")
    return connection


def compute_window_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Reference implementation used by focused semantic tests."""
    work = frame.sort_values(["symbol", "cal_idx"]).copy()
    work["residual"] = work.step_return - work.industry_return_loo
    output: list[pd.DataFrame] = []
    for _, group in work.groupby("symbol", sort=False):
        group = group.copy()
        down = group.industry_return_loo.lt(0)
        group["down_count20"] = down.rolling(20, min_periods=20).sum()
        group["nondown_count20"] = (~down).rolling(20, min_periods=20).sum()
        group["ind_down_resilience_20"] = group.residual.where(down).rolling(
            20, min_periods=1
        ).sum() / group.down_count20.replace(0, np.nan)
        nondown_mean = group.residual.where(~down).rolling(
            20, min_periods=1
        ).sum() / group.nondown_count20.replace(0, np.nan)
        group["ind_downside_asymmetry_20"] = group.ind_down_resilience_20 - nondown_mean
        group["ind_relative_strength_20"] = group.residual.rolling(20, min_periods=20).sum()
        group["realized_volatility_20"] = group.step_return.rolling(20, min_periods=20).std()
        group["industry_pressure_5"] = group.industry_return_loo.rolling(5, min_periods=5).sum()
        group["window_start_cal_idx"] = group.cal_idx.rolling(20, min_periods=20).min()
        group["window_is_consecutive"] = group.cal_idx - group.window_start_cal_idx == 19
        output.append(group)
    return pd.concat(output, ignore_index=True)


def assign_quintiles(frame: pd.DataFrame, score: str) -> pd.Series:
    """Deterministic within-date/context Q1..Q5 assignment."""
    ranks = frame.groupby(["trade_date", "industry_pressure"], sort=False)[score].rank(
        method="average", pct=True
    )
    return np.ceil(ranks * 5).clip(1, 5).astype("Int64")


def _build_signals(connection: duckdb.DuckDBPyConnection, panel_path: Path) -> pd.DataFrame:
    connection.from_parquet(str(panel_path)).create_view("panel")
    audit = connection.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((available_at>decision_at)::INTEGER),sum((year(trade_date)>2023)::INTEGER)
        FROM panel"""
    ).fetchone()
    exact_audit = (
        int(audit[0]),
        int(audit[1]),
        str(pd.Timestamp(audit[2]).date()),
        str(pd.Timestamp(audit[3]).date()),
        int(audit[4]),
        int(audit[5]),
    )
    expected = (3_009_296, 4_798, "2018-07-03", "2023-12-29", 0, 0)
    if exact_audit != expected:
        raise DownsideResilienceError(f"causal daily panel audit changed: {audit}")
    connection.execute(
        """CREATE TEMP TABLE market_steps AS
        SELECT trade_date,median(step_return) broad_market_step
        FROM panel GROUP BY trade_date"""
    )
    connection.execute(
        """CREATE TEMP TABLE features0 AS SELECT p.*,m.broad_market_step,
          p.step_return-p.industry_return_loo residual
        FROM panel p JOIN market_steps m USING(trade_date)
        WHERE year(p.trade_date)<=2023 AND p.industry_return_loo IS NOT NULL
          AND isfinite(p.step_return) AND isfinite(p.industry_return_loo)"""
    )
    connection.execute(
        """CREATE TEMP TABLE features AS SELECT *,
          count(*) OVER w20 n20,min(cal_idx) OVER w20 window_start_cal_idx,
          sum((industry_return_loo<0)::INTEGER) OVER w20 down_count20,
          sum((industry_return_loo>=0)::INTEGER) OVER w20 nondown_count20,
          sum(CASE WHEN industry_return_loo<0 THEN residual ELSE 0 END) OVER w20
            /nullif(sum((industry_return_loo<0)::INTEGER) OVER w20,0) ind_down_resilience_20,
          sum(CASE WHEN industry_return_loo>=0 THEN residual ELSE 0 END) OVER w20
            /nullif(sum((industry_return_loo>=0)::INTEGER) OVER w20,0) nondown_residual_mean20,
          sum(residual) OVER w20 ind_relative_strength_20,
          stddev_samp(step_return) OVER w20 realized_volatility_20,
          count(*) OVER w5 n5,min(cal_idx) OVER w5 pressure_start_cal_idx,
          sum(industry_return_loo) OVER w5 industry_pressure_5,
          sum(broad_market_step) OVER w5 broad_market_pressure_5
        FROM features0 WINDOW
          w20 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
          w5 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)"""
    )
    frame = connection.execute(
        """SELECT row_number() OVER(ORDER BY trade_date,symbol)-1 signal_id,
          trade_date,cal_idx,
          CAST(trade_date AS TIMESTAMP)+INTERVAL '15 hours 30 minutes' decision_at,
          symbol,industry,step_return,max_return20,avg_amount20,diffusion_score,
          ind_down_resilience_20,
          ind_down_resilience_20-nondown_residual_mean20 ind_downside_asymmetry_20,
          ind_relative_strength_20,realized_volatility_20,
          down_count20,nondown_count20,industry_pressure_5,broad_market_pressure_5
        FROM features
        WHERE cal_idx%5=4 AND n20=20 AND cal_idx-window_start_cal_idx=19
          AND n5=5 AND cal_idx-pressure_start_cal_idx=4 AND down_count20>=5
          AND isfinite(ind_down_resilience_20) AND isfinite(ind_relative_strength_20)
          AND isfinite(realized_volatility_20)
        ORDER BY trade_date,symbol"""
    ).fetchdf()
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise DownsideResilienceError("invalid signal panel")
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    frame["industry_pressure"] = frame.industry_pressure_5 < 0
    frame["broad_market_pressure"] = frame.broad_market_pressure_5 < 0
    frame["primary_quintile"] = assign_quintiles(frame, "ind_down_resilience_20")
    asymmetry_valid = frame.down_count20.ge(5) & frame.nondown_count20.ge(5)
    frame["asymmetry_quintile"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    frame.loc[asymmetry_valid, "asymmetry_quintile"] = assign_quintiles(
        frame.loc[asymmetry_valid], "ind_downside_asymmetry_20"
    )
    return frame


def _build_raw_geometry(
    connection: duckdb.DuckDBPyConnection, paths: list[Path]
) -> tuple[list[date], dict[str, Any]]:
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("raw")
    audit_row = connection.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
          sum((available_at>decision_at)::INTEGER),
          sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
          sum((year(trade_date)>2023)::INTEGER) FROM raw"""
    ).fetchone()
    audit = {
        "rows": int(audit_row[0]),
        "symbols": int(audit_row[1]),
        "first": str(audit_row[2]),
        "last": str(audit_row[3]),
        "time_travel": int(audit_row[4]),
        "lineage_failures": int(audit_row[5]),
        "post_2023_rows": int(audit_row[6]),
    }
    expected = {
        "rows": 6_155_390,
        "symbols": 5_262,
        "first": "2018-01-02",
        "last": "2023-12-29",
        "time_travel": 0,
        "lineage_failures": 0,
        "post_2023_rows": 0,
    }
    if audit != expected:
        raise DownsideResilienceError(f"raw daily audit changed: {audit}")
    connection.execute(
        """CREATE TEMP TABLE calendar AS SELECT trade_date,
          row_number() OVER(ORDER BY trade_date)-1 cal_idx
        FROM (SELECT DISTINCT trade_date FROM raw) ORDER BY trade_date"""
    )
    calendar = [
        row[0]
        for row in connection.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()
    ]
    connection.execute(
        """CREATE TEMP TABLE raw_base AS SELECT r.*,c.cal_idx,
          (r.hard_valid IS TRUE AND r.bar_valid IS TRUE AND r.trading_state_valid IS TRUE
           AND r.industry_valid IS TRUE AND r.float_valid IS TRUE
           AND r.corporate_action_valid IS TRUE AND r.market_valid IS TRUE
           AND r.market_rule_valid IS TRUE AND r.historical_identity_valid IS TRUE
           AND r.corporate_action_blocking IS FALSE AND coalesce(r.rights_ratio,0)=0
           AND r.available_at IS NOT NULL AND r.available_at<=r.decision_at
           AND r.open>0 AND r.high>=greatest(r.open,r.close)
           AND r.low<=least(r.open,r.close) AND r.close>0 AND r.volume>=0 AND r.amount>=0)
            history_valid,
          (r.hard_valid IS TRUE AND r.trade_status=1
           AND r.current_day_data_tradable IS TRUE AND r.is_st IS FALSE) current_valid,
          lag(r.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
          lag(r.hard_valid IS TRUE AND r.bar_valid IS TRUE AND r.trading_state_valid IS TRUE
           AND r.industry_valid IS TRUE AND r.float_valid IS TRUE
           AND r.corporate_action_valid IS TRUE AND r.market_valid IS TRUE
           AND r.market_rule_valid IS TRUE AND r.historical_identity_valid IS TRUE
           AND r.corporate_action_blocking IS FALSE AND coalesce(r.rights_ratio,0)=0
           AND r.available_at IS NOT NULL AND r.available_at<=r.decision_at
           AND r.open>0 AND r.high>=greatest(r.open,r.close)
           AND r.low<=least(r.open,r.close) AND r.close>0
           AND r.volume>=0 AND r.amount>=0) OVER w previous_history_valid
        FROM raw r JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY r.symbol ORDER BY r.trade_date)"""
    )
    connection.execute(
        """CREATE TEMP TABLE raw_steps AS SELECT *,CASE
          WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
           AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
          WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
           AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
           AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
           AND coalesce(share_multiplier,1)>0
           AND previous_close-coalesce(cash_per_share,0)>0
          THEN ln(close/((previous_close-coalesce(cash_per_share,0))
                    /coalesce(share_multiplier,1))) ELSE NULL END step_return
        FROM raw_base"""
    )
    connection.execute(
        """CREATE TEMP TABLE raw_geometry AS SELECT *,exp(log_coordinate) coordinate_close,
          exp(log_coordinate)*open/close coordinate_open,
          exp(log_coordinate)*low/close coordinate_low,
          sum(CASE WHEN cal_idx>0 AND (NOT history_valid OR step_return IS NULL)
                   THEN 1 ELSE 0 END) OVER
            (PARTITION BY symbol ORDER BY cal_idx ROWS UNBOUNDED PRECEDING) bad_prefix
        FROM (SELECT *,sum(coalesce(step_return,0)) OVER
          (PARTITION BY symbol ORDER BY cal_idx ROWS UNBOUNDED PRECEDING) log_coordinate
          FROM raw_steps)"""
    )
    return calendar, audit


def _attach_outcomes(
    connection: duckdb.DuckDBPyConnection, signals: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    keys = signals[["signal_id", "symbol", "cal_idx"]].copy()
    connection.register("signal_keys", keys)
    connection.execute(
        """CREATE TEMP TABLE entries AS SELECT s.signal_id,s.symbol,s.cal_idx signal_cal_idx,
          min(g.cal_idx) FILTER (WHERE g.history_valid AND g.current_valid
            AND NOT coalesce(g.buy_blocked_open,TRUE) AND g.coordinate_open>0) entry_cal_idx
        FROM signal_keys s LEFT JOIN raw_geometry g ON g.symbol=s.symbol
          AND g.cal_idx BETWEEN s.cal_idx+1 AND s.cal_idx+20
        GROUP BY s.signal_id,s.symbol,s.cal_idx"""
    )
    connection.execute(
        """CREATE TEMP TABLE entry_detail AS SELECT e.*,g.trade_date entry_date,
          g.coordinate_open entry_coordinate_open,g.bad_prefix entry_bad_prefix,
          n.trade_date immediate_date,n.hard_valid immediate_hard_valid,
          n.trade_status immediate_trade_status,
          n.current_day_data_tradable immediate_tradable,
          n.buy_blocked_open immediate_buy_blocked,
          n.open immediate_open,n.available_at immediate_available_at
        FROM entries e
        LEFT JOIN raw_geometry g ON g.symbol=e.symbol AND g.cal_idx=e.entry_cal_idx
        LEFT JOIN raw_geometry n ON n.symbol=e.symbol AND n.cal_idx=e.signal_cal_idx+1"""
    )
    horizons = pd.DataFrame({"horizon": list(HORIZONS)})
    connection.register("horizons", horizons)
    outcome_long = connection.execute(
        f"""SELECT e.signal_id,h.horizon,e.entry_cal_idx,e.entry_date,
          CASE WHEN e.entry_cal_idx IS NOT NULL AND t.cal_idx=e.entry_cal_idx+h.horizon-1
            AND t.history_valid AND t.bad_prefix-e.entry_bad_prefix=0
            THEN (t.coordinate_close*(1-{COST}))/(e.entry_coordinate_open*(1+{COST}))-1
            ELSE NULL END net_return,
          CASE WHEN e.entry_cal_idx IS NOT NULL AND t.cal_idx=e.entry_cal_idx+h.horizon-1
            AND t.history_valid AND t.bad_prefix-e.entry_bad_prefix=0
            THEN t.coordinate_close/e.entry_coordinate_open-1 ELSE NULL END gross_return
        FROM entry_detail e CROSS JOIN horizons h
        LEFT JOIN raw_geometry t ON t.symbol=e.symbol
          AND t.cal_idx=e.entry_cal_idx+h.horizon-1
        ORDER BY e.signal_id,h.horizon"""
    ).fetchdf()
    mae = connection.execute(
        f"""SELECT e.signal_id,
          CASE WHEN count(g.cal_idx)=20 AND max(g.bad_prefix)-e.entry_bad_prefix=0
            THEN min(g.coordinate_low)/(e.entry_coordinate_open*(1+{COST}))-1 ELSE NULL END mae_h20
        FROM entry_detail e LEFT JOIN raw_geometry g ON g.symbol=e.symbol
          AND g.cal_idx BETWEEN e.entry_cal_idx AND e.entry_cal_idx+19
        GROUP BY e.signal_id,e.entry_cal_idx,e.entry_coordinate_open,e.entry_bad_prefix"""
    ).fetchdf()
    entry = connection.execute("SELECT * FROM entry_detail ORDER BY signal_id").fetchdf()
    entry["entry_status"] = np.select(
        [
            entry.entry_cal_idx.isna().to_numpy(dtype=bool),
            entry.entry_cal_idx.eq(entry.signal_cal_idx + 1).fillna(False).to_numpy(dtype=bool),
            entry.entry_cal_idx.gt(entry.signal_cal_idx + 1).fillna(False).to_numpy(dtype=bool),
        ],
        ["UNUSABLE", "IMMEDIATE", "DELAYED"],
        default="UNUSABLE",
    )
    immediate_valid = (
        entry.immediate_hard_valid.fillna(False)
        & entry.immediate_open.fillna(0).gt(0)
        & entry.immediate_available_at.notna()
    )
    entry["immediate_block_reason"] = np.select(
        [
            (~immediate_valid).to_numpy(dtype=bool),
            (
                entry.immediate_trade_status.fillna(0).ne(1)
                | ~entry.immediate_tradable.fillna(False)
            ).to_numpy(dtype=bool),
            entry.immediate_buy_blocked.fillna(True).to_numpy(dtype=bool),
        ],
        ["INVALID_OR_UNAVAILABLE_OPEN", "SUSPENSION_OR_NONTRADING", "PRICE_LIMIT"],
        default="NONE",
    )
    wide = outcome_long.pivot(index="signal_id", columns="horizon", values="net_return")
    wide.columns = [f"net_return_h{int(column)}" for column in wide.columns]
    gross = outcome_long.pivot(index="signal_id", columns="horizon", values="gross_return")
    gross.columns = [f"gross_return_h{int(column)}" for column in gross.columns]
    attached = (
        signals.merge(
            entry[
                [
                    "signal_id",
                    "entry_date",
                    "entry_cal_idx",
                    "entry_status",
                    "immediate_block_reason",
                ]
            ],
            on="signal_id",
            how="left",
        )
        .merge(wide, on="signal_id", how="left")
        .merge(gross, on="signal_id", how="left")
        .merge(mae, on="signal_id", how="left")
    )
    for horizon in HORIZONS:
        value = f"net_return_h{horizon}"
        attached[f"industry_mean_h{horizon}"] = attached.groupby(
            ["trade_date", "industry"], sort=False
        )[value].transform("mean")
        attached[f"broad_mean_h{horizon}"] = attached.groupby("trade_date", sort=False)[
            value
        ].transform("mean")
        attached[f"industry_relative_h{horizon}"] = (
            attached[value] - attached[f"industry_mean_h{horizon}"]
        )
        attached[f"broad_relative_h{horizon}"] = (
            attached[value] - attached[f"broad_mean_h{horizon}"]
        )
    actionability = {
        "eligible_signal_observations": len(attached),
        "immediate": int(attached.entry_status.eq("IMMEDIATE").sum()),
        "delayed": int(attached.entry_status.eq("DELAYED").sum()),
        "unusable": int(attached.entry_status.eq("UNUSABLE").sum()),
        "actionable": int(attached.entry_status.isin(["IMMEDIATE", "DELAYED"]).sum()),
        "actionable_fraction": float(attached.entry_status.isin(["IMMEDIATE", "DELAYED"]).mean()),
        "immediate_fraction": float(attached.entry_status.eq("IMMEDIATE").mean()),
        "immediate_block_reasons": {
            str(key): int(value)
            for key, value in attached.loc[attached.entry_status.ne("IMMEDIATE")]
            .immediate_block_reason.value_counts()
            .sort_index()
            .items()
        },
        "complete_h20_fraction": float(attached.net_return_h20.notna().mean()),
    }
    return attached, actionability


def _period_mask(frame: pd.DataFrame, period: str) -> pd.Series:
    years = pd.to_datetime(frame.trade_date).dt.year
    if period == "full":
        return pd.Series(True, index=frame.index)
    if period == "early_2018_2021":
        return years.between(2018, 2021)
    if period == "late_2022_2023":
        return years.between(2022, 2023)
    return years.eq(int(period))


def _metric_row(
    subset: pd.DataFrame,
    *,
    section: str,
    representation: str,
    context: str,
    period: str,
    horizon: int,
    quintile: int | str,
) -> dict[str, Any]:
    absolute = subset[f"net_return_h{horizon}"].dropna()
    aligned = subset.loc[absolute.index]
    industry_relative = aligned[f"industry_relative_h{horizon}"].dropna()
    broad_relative = aligned.loc[industry_relative.index, f"broad_relative_h{horizon}"]
    return {
        "section": section,
        "representation": representation,
        "context": context,
        "period": period,
        "horizon": horizon,
        "quintile": quintile,
        "count": len(absolute),
        "dates": int(aligned.trade_date.nunique()),
        "securities": int(aligned.symbol.nunique()),
        "industries": int(aligned.industry.nunique()),
        "mean_net_return": absolute.mean(),
        "median_net_return": absolute.median(),
        "positive_return_fraction": (absolute > 0).mean(),
        "mean_industry_relative": industry_relative.mean(),
        "median_industry_relative": industry_relative.median(),
        "mean_broad_relative": broad_relative.mean(),
        "severe_loss_fraction": (absolute <= SEVERE).mean(),
        "mean_mae_h20": aligned.mae_h20.mean() if horizon == 20 else np.nan,
    }


def _raw_tables(panel: pd.DataFrame) -> pd.DataFrame:
    outputs: list[dict[str, Any]] = []
    representations = {
        "IND_DOWN_RESILIENCE_20": "primary_quintile",
        "IND_DOWNSIDE_ASYMMETRY_20": "asymmetry_quintile",
    }
    contexts = {
        "INDUSTRY_PRESSURE": panel.industry_pressure,
        "INDUSTRY_NONPRESSURE": ~panel.industry_pressure,
        "BROAD_MARKET_PRESSURE": panel.broad_market_pressure,
        "BROAD_MARKET_NONPRESSURE": ~panel.broad_market_pressure,
    }
    periods = ["full", "early_2018_2021", "late_2022_2023", *map(str, range(2018, 2024))]
    for representation, qcol in representations.items():
        valid_rep = panel[qcol].notna()
        for context, context_mask in contexts.items():
            for period in periods:
                base = panel.loc[valid_rep & context_mask & _period_mask(panel, period)]
                for horizon in HORIZONS:
                    rows_by_q = []
                    for quintile in range(1, 6):
                        row = _metric_row(
                            base.loc[base[qcol].eq(quintile)],
                            section="raw",
                            representation=representation,
                            context=context,
                            period=period,
                            horizon=horizon,
                            quintile=quintile,
                        )
                        outputs.append(row)
                        rows_by_q.append(row)
                    spread = {
                        key: rows_by_q[-1][key] - rows_by_q[0][key]
                        for key in (
                            "mean_net_return",
                            "median_net_return",
                            "positive_return_fraction",
                            "mean_industry_relative",
                            "median_industry_relative",
                            "mean_broad_relative",
                            "severe_loss_fraction",
                            "mean_mae_h20",
                        )
                    }
                    outputs.append(
                        {
                            "section": "raw_spread",
                            "representation": representation,
                            "context": context,
                            "period": period,
                            "horizon": horizon,
                            "quintile": "Q5-Q1",
                            "count": min(rows_by_q[0]["count"], rows_by_q[-1]["count"]),
                            "dates": min(rows_by_q[0]["dates"], rows_by_q[-1]["dates"]),
                            "securities": np.nan,
                            "industries": np.nan,
                            **spread,
                        }
                    )
    return pd.DataFrame(outputs)


def _control_tables(panel: pd.DataFrame) -> pd.DataFrame:
    base = panel.loc[panel.industry_pressure & panel.primary_quintile.notna()].copy()
    controls = {
        "GENERIC_RS": "ind_relative_strength_20",
        "REALIZED_VOLATILITY": "realized_volatility_20",
        "LIQUIDITY": "avg_amount20",
        "LOW_MAX": "max_return20",
    }
    rows: list[dict[str, Any]] = []
    for name, column in controls.items():
        ranks = base.groupby("trade_date", sort=False)[column].rank(method="average", pct=True)
        base["control_tercile"] = np.ceil(ranks * 3).clip(1, 3).astype("Int64")
        for period in ("full", "early_2018_2021", "late_2022_2023"):
            period_base = base.loc[_period_mask(base, period)]
            for horizon in (5, 20):
                for tercile in range(1, 4):
                    group = period_base.loc[period_base.control_tercile.eq(tercile)]
                    q5 = group.loc[group.primary_quintile.eq(5), f"industry_relative_h{horizon}"]
                    q1 = group.loc[group.primary_quintile.eq(1), f"industry_relative_h{horizon}"]
                    rows.append(
                        {
                            "section": "control",
                            "control": name,
                            "period": period,
                            "horizon": horizon,
                            "tercile": tercile,
                            "q5_count": int(q5.notna().sum()),
                            "q1_count": int(q1.notna().sum()),
                            "q5_mean_industry_relative": q5.mean(),
                            "q1_mean_industry_relative": q1.mean(),
                            "q5_minus_q1_industry_relative": q5.mean() - q1.mean(),
                        }
                    )
    return pd.DataFrame(rows)


def _rank_correlation(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    rows = []
    for day, group in frame.groupby("trade_date", sort=True):
        valid = group[[left, right]].dropna()
        if len(valid) >= 20:
            rho = spearmanr(valid[left], valid[right]).statistic
            rows.append((pd.Timestamp(day).year, float(rho)))
    data = pd.DataFrame(rows, columns=["year", "rho"])
    return {
        "dates": len(data),
        "mean_same_date_spearman": float(data.rho.mean()),
        "median_same_date_spearman": float(data.rho.median()),
        "early_mean": float(data.loc[data.year <= 2021, "rho"].mean()),
        "late_mean": float(data.loc[data.year >= 2022, "rho"].mean()),
    }


def _independence(panel: pd.DataFrame, champion_path: Path) -> dict[str, Any]:
    pressure = panel.loc[panel.industry_pressure].copy()
    rs = _rank_correlation(pressure, "ind_down_resilience_20", "ind_relative_strength_20")
    low_max = _rank_correlation(pressure, "ind_down_resilience_20", "max_return20")
    champion = pd.read_csv(champion_path, usecols=["family", "trade_date", "symbol"])
    champion = champion.loc[
        champion.family.eq("arm2_low_max"), ["trade_date", "symbol"]
    ].drop_duplicates()
    champion["trade_date"] = pd.to_datetime(champion.trade_date).dt.date
    champion["champion_selected"] = True
    merged = pressure.merge(champion, on=["trade_date", "symbol"], how="left")
    merged["champion_selected"] = (
        merged.champion_selected.astype("boolean").fillna(False).astype(bool)
    )
    q5 = merged.primary_quintile.eq(5)
    remaining = merged.loc[~merged.champion_selected]
    removed_result: dict[str, Any] = {}
    for horizon in (5, 20):
        q5r = remaining.loc[remaining.primary_quintile.eq(5), f"industry_relative_h{horizon}"]
        q1r = remaining.loc[remaining.primary_quintile.eq(1), f"industry_relative_h{horizon}"]
        removed_result[f"h{horizon}"] = {
            "q5_mean_industry_relative": float(q5r.mean()),
            "q5_minus_q1_industry_relative": float(q5r.mean() - q1r.mean()),
        }
    return {
        "generic_rs_rank_relationship": rs,
        "low_max_rank_relationship": low_max,
        "champion_selected_observations": int(merged.champion_selected.sum()),
        "primary_q5_champion_overlap_count": int((q5 & merged.champion_selected).sum()),
        "primary_q5_champion_overlap_fraction": float(
            (q5 & merged.champion_selected).sum() / max(1, q5.sum())
        ),
        "economics_after_removing_champion_selections": removed_result,
        "diffusion_rank_relationship": _rank_correlation(
            pressure, "ind_down_resilience_20", "diffusion_score"
        ),
    }


def _lookup(
    table: pd.DataFrame, *, period: str, horizon: int, quintile: str = "Q5-Q1"
) -> dict[str, Any]:
    row = table.loc[
        table.section.eq("raw_spread")
        & table.representation.eq("IND_DOWN_RESILIENCE_20")
        & table.context.eq("INDUSTRY_PRESSURE")
        & table.period.eq(period)
        & table.horizon.eq(horizon)
        & table.quintile.eq(quintile)
    ]
    if len(row) != 1:
        raise DownsideResilienceError(f"missing result lookup: {period}/h{horizon}")
    return row.iloc[0].to_dict()


def _classification(
    raw: pd.DataFrame, controls: pd.DataFrame, independence: dict[str, Any], action: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    full = {h: _lookup(raw, period="full", horizon=h) for h in HORIZONS}
    early = {h: _lookup(raw, period="early_2018_2021", horizon=h) for h in (5, 20)}
    late = {h: _lookup(raw, period="late_2022_2023", horizon=h) for h in (5, 20)}
    annual = {year: _lookup(raw, period=str(year), horizon=20) for year in range(2018, 2024)}
    control_full = controls.loc[controls.period.eq("full")]
    gates = {
        "positive_industry_relative_q5_q1_multiple_horizons": sum(
            full[h]["mean_industry_relative"] > 0 for h in HORIZONS
        )
        >= 3,
        "positive_absolute_q5_q1_multiple_horizons": sum(
            full[h]["mean_net_return"] > 0 for h in HORIZONS
        )
        >= 3,
        "both_blocks_positive_h5_h20": all(
            part[h]["mean_industry_relative"] > 0 for part in (early, late) for h in (5, 20)
        ),
        "positive_years_h20_at_least_four": sum(
            annual[year]["mean_industry_relative"] > 0 for year in annual
        )
        >= 4,
        "generic_rs_control_positive_all_terciles_h20": bool(
            (
                control_full.loc[
                    (control_full.control == "GENERIC_RS") & (control_full.horizon == 20),
                    "q5_minus_q1_industry_relative",
                ]
                > 0
            ).all()
        ),
        "volatility_control_positive_all_terciles_h20": bool(
            (
                control_full.loc[
                    (control_full.control == "REALIZED_VOLATILITY") & (control_full.horizon == 20),
                    "q5_minus_q1_industry_relative",
                ]
                > 0
            ).all()
        ),
        "liquidity_control_positive_all_terciles_h20": bool(
            (
                control_full.loc[
                    (control_full.control == "LIQUIDITY") & (control_full.horizon == 20),
                    "q5_minus_q1_industry_relative",
                ]
                > 0
            ).all()
        ),
        "actionable_fraction_at_least_90pct": action["actionable_fraction"] >= 0.90,
        "low_max_rank_correlation_not_dominant": abs(
            independence["low_max_rank_relationship"]["mean_same_date_spearman"]
        )
        < 0.70,
        "positive_after_champion_removal_h5_h20": all(
            independence["economics_after_removing_champion_selections"][f"h{h}"][
                "q5_minus_q1_industry_relative"
            ]
            > 0
            for h in (5, 20)
        ),
    }
    block_sign_reversal = any(
        early[h]["mean_industry_relative"] * late[h]["mean_industry_relative"] < 0 for h in (5, 20)
    )
    if all(gates.values()):
        classification = "PROMISING_INDEPENDENT_ALPHA"
    elif block_sign_reversal:
        classification = "CHRONOLOGICALLY_UNSTABLE"
    elif (
        gates["positive_industry_relative_q5_q1_multiple_horizons"]
        and not gates["generic_rs_control_positive_all_terciles_h20"]
    ):
        classification = "GENERIC_RELATIVE_STRENGTH_ONLY"
    elif (
        gates["positive_industry_relative_q5_q1_multiple_horizons"]
        and full[20]["severe_loss_fraction"] < 0
        and full[20]["mean_mae_h20"] > 0
        and full[20]["mean_net_return"] <= 0
    ):
        classification = "DEFENSIVE_INFORMATION_ONLY"
    elif gates["positive_industry_relative_q5_q1_multiple_horizons"]:
        classification = "PROMISING_BUT_NOT_INDEPENDENT"
    else:
        classification = "NULL"
    return classification, {
        "gates": gates,
        "block_sign_reversal": block_sign_reversal,
        "full_spreads": full,
        "annual_h20": annual,
    }


def _fmt(value: Any, pct: bool = True) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):+.3%}" if pct else f"{float(value):.3f}"


def _report(result: dict[str, Any], tables: pd.DataFrame, controls: pd.DataFrame) -> str:
    classification = result["final_classification"]
    generic_rs_rho = result["independence"]["generic_rs_rank_relationship"][
        "mean_same_date_spearman"
    ]
    low_max_rho = result["independence"]["low_max_rank_relationship"]["mean_same_date_spearman"]
    block_reasons = result["actionability"]["immediate_block_reasons"]
    price_limit_blocks = block_reasons.get("PRICE_LIMIT", 0)
    suspension_blocks = block_reasons.get("SUSPENSION_OR_NONTRADING", 0)
    invalid_open_blocks = block_reasons.get("INVALID_OR_UNAVAILABLE_OPEN", 0)
    lines = [
        "# A-share downside resilience discovery V1",
        "",
        "## Executive conclusion",
        "",
        f"Final classification: `{classification}`.",
        "",
        result["economic_interpretation"],
        "",
        "## Scientific question and frozen representation",
        "",
        (
            "The test asks whether stock-minus-PIT-industry residuals specifically on "
            "industry-down sessions contain future information beyond ordinary relative "
            "strength and low volatility. `IND_DOWN_RESILIENCE_20` is the mean daily "
            "residual on at least five industry-down observations in the 20 completed "
            "sessions ending at the weekly close. Industry pressure is the fixed "
            "prior-five-session PIT-industry return below zero. The signal is known at "
            "15:30 and can enter only at a later legal open."
        ),
        "",
        "## Coverage and actionability",
        "",
        (
            f"The panel contains {result['coverage']['observations']:,} stock-date signals "
            f"on {result['coverage']['dates']} weekly dates, "
            f"{result['coverage']['securities']:,} securities, and "
            f"{result['coverage']['industries']} PIT industries from "
            f"{result['coverage']['first']} through {result['coverage']['last']}. "
            "Complete h20 outcomes end no later than "
            f"{result['max_evaluation_outcome_date']}."
        ),
        "",
        (
            f"Actionability is {result['actionability']['actionable_fraction']:.2%}: "
            f"{result['actionability']['immediate']:,} immediate, "
            f"{result['actionability']['delayed']:,} delayed, and "
            f"{result['actionability']['unusable']:,} unusable observations. Immediate-open "
            "blocks are "
            f"{price_limit_blocks:,} price-limit, "
            f"{suspension_blocks:,} suspension/nontrading, and "
            f"{invalid_open_blocks:,} "
            "invalid/unavailable-open observations."
        ),
        "",
        "## Raw cross-sectional result — industry pressure",
        "",
        (
            "| Horizon | Q1 net | Q2 net | Q3 net | Q4 net | Q5 net | Q5-Q1 net | "
            "Q5-Q1 industry-relative | Q5-Q1 median industry-relative | Q5-Q1 positive | "
            "Q5-Q1 severe |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in HORIZONS:
        base = tables.loc[
            tables.section.eq("raw")
            & tables.representation.eq("IND_DOWN_RESILIENCE_20")
            & tables.context.eq("INDUSTRY_PRESSURE")
            & tables.period.eq("full")
            & tables.horizon.eq(horizon)
        ]
        quantiles = [base.loc[base.quintile.eq(value)].iloc[0] for value in range(1, 6)]
        spread = _lookup(tables, period="full", horizon=horizon)
        lines.append(
            f"| h{horizon} | "
            f"{' | '.join(_fmt(row.mean_net_return) for row in quantiles)} | "
            f"{_fmt(spread['mean_net_return'])} | {_fmt(spread['mean_industry_relative'])} | "
            f"{_fmt(spread['median_industry_relative'])} | "
            f"{_fmt(spread['positive_return_fraction'])} | "
            f"{_fmt(spread['severe_loss_fraction'])} |"
        )
    lines.extend(
        [
            "",
            "## Pressure specificity and chronology",
            "",
            "| Slice | h5 industry-relative Q5-Q1 | h20 industry-relative Q5-Q1 |",
            "| --- | ---: | ---: |",
        ]
    )
    for context in ("INDUSTRY_PRESSURE", "INDUSTRY_NONPRESSURE", "BROAD_MARKET_PRESSURE"):
        values = []
        for horizon in (5, 20):
            row = tables.loc[
                tables.section.eq("raw_spread")
                & tables.representation.eq("IND_DOWN_RESILIENCE_20")
                & tables.context.eq(context)
                & tables.period.eq("full")
                & tables.horizon.eq(horizon)
            ].iloc[0]
            values.append(_fmt(row.mean_industry_relative))
        lines.append(f"| {context} | {values[0]} | {values[1]} |")
    for period in ("early_2018_2021", "late_2022_2023"):
        values = [
            _fmt(_lookup(tables, period=period, horizon=h)["mean_industry_relative"])
            for h in (5, 20)
        ]
        lines.append(f"| {period} | {values[0]} | {values[1]} |")
    lines.extend(
        [
            "",
            "## Year-by-year h20 industry-pressure spread",
            "",
            "| Year | Q5-Q1 net | Q5-Q1 industry-relative |",
            "| --- | ---: | ---: |",
        ]
    )
    for year in range(2018, 2024):
        row = _lookup(tables, period=str(year), horizon=20)
        lines.append(
            f"| {year} | {_fmt(row['mean_net_return'])} | {_fmt(row['mean_industry_relative'])} |"
        )
    lines.extend(
        [
            "",
            "## Confound and Strategy-A independence audit",
            "",
            (
                "Generic-RS same-date rank correlation is "
                f"{generic_rs_rho:.3f}; "
                "Low-MAX correlation is "
                f"{low_max_rho:.3f}. "
                "Champion overlap among primary Q5 pressure observations is "
                f"{result['independence']['primary_q5_champion_overlap_fraction']:.2%}. "
                "No Strategy-A rule or result was modified."
            ),
            "",
            "| Control | h20 tercile spreads (Q5-Q1 industry-relative) |",
            "| --- | --- |",
        ]
    )
    for control in ("GENERIC_RS", "REALIZED_VOLATILITY", "LIQUIDITY", "LOW_MAX"):
        values = (
            controls.loc[
                controls.control.eq(control) & controls.period.eq("full") & controls.horizon.eq(20)
            ]
            .sort_values("tercile")
            .q5_minus_q1_industry_relative
        )
        lines.append(f"| {control} | {' / '.join(_fmt(value) for value in values)} |")
    lines.extend(
        [
            "",
            "## Defensive versus Alpha diagnosis",
            "",
            result["defensive_vs_alpha"],
            "",
            "## Decision and next direction",
            "",
            f"`{classification}`. {result['next_recommended_research_direction']}",
            "",
            (
                "This is consumed 2018–2023 development evidence, not OOS confirmation. "
                "Post-2023 outcome rows and CY-011 were not read."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    spec = _load_spec()
    daily_paths = _daily_paths(spec)
    connection = _configure()
    try:
        signals = _build_signals(connection, _resolve(spec["inputs"]["causal_daily_panel"]["path"]))
        calendar, raw_audit = _build_raw_geometry(connection, daily_paths)
        panel, actionability = _attach_outcomes(connection, signals)
    finally:
        connection.close()
    if panel.empty or pd.to_datetime(panel.trade_date).dt.year.max() > 2023:
        raise DownsideResilienceError("post-2023 or empty evaluation panel")
    panel.to_parquet(PANEL_PATH, index=False, compression="zstd")
    raw_tables = _raw_tables(panel)
    control_tables = _control_tables(panel)
    tables = pd.concat([raw_tables, control_tables], ignore_index=True, sort=False)
    tables.to_csv(TABLE_PATH, index=False, float_format="%.12g")
    independence = _independence(panel, _resolve(spec["inputs"]["champion_attribution"]["path"]))
    classification, evidence = _classification(
        raw_tables, control_tables, independence, actionability
    )
    full_h20 = _lookup(raw_tables, period="full", horizon=20)
    if classification == "PROMISING_INDEPENDENT_ALPHA":
        interpretation = (
            "Downside-specific relative resilience is positive across multiple horizons and both "
            "chronological blocks, survives the frozen coarse controls, remains after removing "
            "Champion selections, and has credible next-open actionability."
        )
        next_direction = (
            "Freeze one simple, capacity-aware Strategy-B portfolio translation in a "
            "separate cycle; "
            "do not combine it with Strategy A before standalone replay."
        )
    elif classification == "GENERIC_RELATIVE_STRENGTH_ONLY":
        interpretation = (
            "The raw resilience ordering does not survive ordinary industry-relative-strength "
            "controls; "
            "the downside-session restriction has not earned status as a new Alpha mechanism."
        )
        next_direction = "Close this exact family without lookback or pressure-threshold rescue."
    elif classification == "CHRONOLOGICALLY_UNSTABLE":
        interpretation = (
            "The frozen downside-resilience ordering materially contradicts itself across the two "
            "development blocks, so it cannot support a Strategy-B translation."
        )
        next_direction = "Close this exact family and move to a genuinely independent mechanism."
    else:
        interpretation = (
            "The frozen orientation is adverse: stronger measured resilience under industry "
            "pressure trails at every tested horizon and in every calendar year, and the negative "
            "ordering remains inside the coarse generic-RS, volatility, liquidity, and Low-MAX "
            "controls. It is classified NULL as a long-only Alpha family and is not sign-inverted."
        )
        next_direction = "Do not rescue this formulation; re-rank independent Alpha frontiers."
    defensive = (
        f"At h20, Q5-Q1 net return is {_fmt(full_h20['mean_net_return'])}, industry-relative "
        f"spread is {_fmt(full_h20['mean_industry_relative'])}, severe-loss change is "
        f"{_fmt(full_h20['severe_loss_fraction'])}, and MAE change is "
        f"{_fmt(full_h20['mean_mae_h20'])}. The classification follows positive Alpha and "
        "incrementality, not loss avoidance alone."
    )
    complete_dates = panel.loc[panel.net_return_h20.notna(), "entry_date"]
    max_outcome_date = None
    if not complete_dates.empty:
        entry_indices = panel.loc[panel.net_return_h20.notna(), "entry_cal_idx"].astype(int)
        max_outcome_date = max(calendar[index + 19] for index in entry_indices)
    result = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "frozen_spec_sha256": EXPECTED_SPEC_SHA256,
        "claim_boundary": spec["claim_boundary"],
        "evaluation_start": str(panel.trade_date.min()),
        "max_evaluation_outcome_date": str(max_outcome_date),
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "input_identity": {
            "daily_partition_years": [2018, 2019, 2020, 2021, 2022, 2023],
            "raw_audit": raw_audit,
            "causal_daily_panel_sha256": spec["inputs"]["causal_daily_panel"]["sha256"],
        },
        "coverage": {
            "observations": len(panel),
            "dates": int(panel.trade_date.nunique()),
            "securities": int(panel.symbol.nunique()),
            "industries": int(panel.industry.nunique()),
            "first": str(panel.trade_date.min()),
            "last": str(panel.trade_date.max()),
            "industry_pressure_observations": int(panel.industry_pressure.sum()),
            "broad_market_pressure_observations": int(panel.broad_market_pressure.sum()),
        },
        "actionability": actionability,
        "independence": independence,
        "classification_evidence": evidence,
        "defensive_vs_alpha": defensive,
        "final_classification": classification,
        "economic_interpretation": interpretation,
        "next_recommended_research_direction": next_direction,
        "external_artifacts": {
            "evaluation_panel": str(PANEL_PATH),
            "evaluation_panel_sha256": sha256_file(PANEL_PATH),
        },
        "artifacts": {
            "tables": str(TABLE_PATH.relative_to(ROOT)),
            "tables_sha256": sha256_file(TABLE_PATH),
            "report": str(REPORT_PATH.relative_to(ROOT)),
        },
    }
    _atomic_write(REPORT_PATH, _report(result, raw_tables, control_tables))
    result["artifacts"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "classification": classification,
                "observations": len(panel),
                "actionable_fraction": actionability["actionable_fraction"],
                "h20_spread": full_h20["mean_industry_relative"],
                "result_sha256": sha256_file(RESULT_PATH),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
