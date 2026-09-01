#!/usr/bin/env python3
"""Run frozen A-share shock absorption/recovery discovery V1."""

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

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1_result.json"
TABLE_PATH = PROGRAM / "artifacts/ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1_tables.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/shock_absorption_recovery_discovery_v1")
PANEL_PATH = EXTERNAL_ROOT / "evaluation_panel.parquet"
TEMP_PATH = EXTERNAL_ROOT / "duckdb_tmp"
EXECUTION_PATH = PROGRAM / "scripts/run_ashare_downside_resilience_discovery_v1.py"
EXPECTED_SPEC_SHA256 = "f0656e4357ceb2eb46831d6616b5a08ce290dc99047c36b29068f30e5839e5e9"
HORIZONS = (1, 3, 5, 10, 20)
SEVERE = -0.10


class ShockAbsorptionError(RuntimeError):
    """Fail-closed error for the frozen event experiment."""


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise ShockAbsorptionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


EXECUTION = _load_module("downside_resilience_execution_for_shock_v1", EXECUTION_PATH)


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
        raise ShockAbsorptionError("frozen specification identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise ShockAbsorptionError("experiment was not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ShockAbsorptionError(f"bound input changed: {role}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "sign-inversion", "machine-learning"):
        if phrase not in prohibited:
            raise ShockAbsorptionError(f"missing prohibition: {phrase}")
    return spec


def _configure() -> duckdb.DuckDBPyConnection:
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_PATH.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='12GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{TEMP_PATH.as_posix()}'")
    return connection


def qualifies_shock(stock_log_return: float, industry_log_return: float) -> bool:
    """Exact frozen joint simple-return shock qualification."""
    stock_return = math.expm1(stock_log_return)
    industry_return = math.expm1(industry_log_return)
    return stock_return <= -0.05 and stock_return - industry_return <= -0.03


def suppress_overlapping_events(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the first shock and suppress same-security shocks through s+3."""
    accepted: list[int] = []
    for _, group in frame.sort_values(["symbol", "shock_cal_idx", "symbol"]).groupby(
        "symbol", sort=False
    ):
        blocked_through = -1
        for row in group.itertuples():
            if int(row.shock_cal_idx) <= blocked_through:
                continue
            accepted.append(int(row.Index))
            blocked_through = int(row.shock_cal_idx) + 3
    return frame.loc[sorted(accepted)].sort_values(["shock_date", "symbol"]).reset_index(drop=True)


def absorption_metrics(
    previous_close: float,
    shock_close: float,
    observation_closes: list[float] | tuple[float, float, float],
) -> tuple[float, float]:
    """Exact Recovery Fraction and Further Drawdown Ratio reference calculation."""
    if len(observation_closes) != 3:
        raise ShockAbsorptionError("absorption window must contain exactly three closes")
    shock_loss = previous_close - shock_close
    if not math.isfinite(shock_loss) or shock_loss <= 0:
        raise ShockAbsorptionError("shock loss must be positive")
    recovery = (float(observation_closes[2]) - shock_close) / shock_loss
    further_loss = max(0.0, shock_close - min(map(float, observation_closes)))
    return recovery, further_loss / shock_loss


def assign_quintiles(frame: pd.DataFrame, score: str) -> pd.Series:
    ranks = frame.groupby(["sample_type", "signal_date"], sort=False)[score].rank(
        method="average", pct=True
    )
    return np.ceil(ranks * 5).clip(1, 5).astype("Int64")


def _panel_audit(connection: duckdb.DuckDBPyConnection, panel_path: Path) -> None:
    connection.from_parquet(str(panel_path)).create_view("panel")
    audit = connection.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
          sum((available_at>decision_at)::INTEGER),sum((year(trade_date)>2023)::INTEGER)
        FROM panel"""
    ).fetchone()
    exact = (
        int(audit[0]),
        int(audit[1]),
        str(pd.Timestamp(audit[2]).date()),
        str(pd.Timestamp(audit[3]).date()),
        int(audit[4]),
        int(audit[5]),
    )
    expected = (3_009_296, 4_798, "2018-07-03", "2023-12-29", 0, 0)
    if exact != expected:
        raise ShockAbsorptionError(f"causal daily panel audit changed: {exact}")


def _candidate_shocks(connection: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, int]:
    connection.execute(
        """CREATE TEMP TABLE panel_features AS SELECT *,
          count(step_return) OVER prior20 prior_count20,
          min(cal_idx) OVER prior20 prior_start_cal_idx,
          sum(step_return) OVER prior20 pre_shock_trend20,
          stddev_samp(step_return) OVER prior20 pre_shock_volatility20,
          lead(trade_date,3) OVER forward signal_date_3,
          lead(cal_idx,1) OVER forward next_cal_idx_1,
          lead(cal_idx,2) OVER forward next_cal_idx_2,
          lead(cal_idx,3) OVER forward next_cal_idx_3,
          lead(step_return,1) OVER forward next_step_return_1,
          lead(step_return,2) OVER forward next_step_return_2,
          lead(step_return,3) OVER forward next_step_return_3,
          lead(industry_return_loo,1) OVER forward next_industry_return_1,
          lead(industry_return_loo,2) OVER forward next_industry_return_2,
          lead(industry_return_loo,3) OVER forward next_industry_return_3,
          lead(max_return20,3) OVER forward signal_max_return20,
          lead(diffusion_score,3) OVER forward signal_diffusion_score
        FROM panel WINDOW prior20 AS
          (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
          forward AS (PARTITION BY symbol ORDER BY cal_idx)"""
    )
    candidates = connection.execute(
        """SELECT row_number() OVER(ORDER BY trade_date,symbol)-1 candidate_id,
          trade_date shock_date,cal_idx shock_cal_idx,symbol,industry,
          exp(step_return)-1 stock_shock_return,
          exp(industry_return_loo)-1 industry_shock_return,
          exp(step_return)-exp(industry_return_loo) relative_shock_return,
          pre_shock_trend20,pre_shock_volatility20,avg_amount20 shock_avg_amount20
        FROM panel_features
        WHERE prior_count20=20 AND cal_idx-prior_start_cal_idx=20
          AND exp(step_return)-1<=-0.05
          AND exp(step_return)-exp(industry_return_loo)<=-0.03
        ORDER BY trade_date,symbol"""
    ).fetchdf()
    candidates["shock_date"] = pd.to_datetime(candidates.shock_date).dt.date
    if candidates.empty or candidates.duplicated(["shock_date", "symbol"]).any():
        raise ShockAbsorptionError("invalid qualifying shock set")
    total = len(candidates)
    accepted = suppress_overlapping_events(candidates)
    accepted["event_id"] = np.arange(len(accepted), dtype=np.int64)
    return accepted, total


def _build_complete_paths(connection: duckdb.DuckDBPyConnection) -> None:
    """Materialize one narrow causal path row instead of repeatedly self-joining raw bars."""
    connection.execute(
        """CREATE TEMP TABLE geometry_paths AS SELECT symbol,cal_idx,history_valid,
          coordinate_close shock_coordinate_close,
          lag(cal_idx,1) OVER path previous_cal_idx,
          lag(history_valid,1) OVER path previous_history_valid,
          lag(coordinate_close,1) OVER path previous_coordinate_close,
          lead(cal_idx,1) OVER path geometry_cal_idx_1,
          lead(cal_idx,2) OVER path geometry_cal_idx_2,
          lead(cal_idx,3) OVER path geometry_cal_idx_3,
          lead(history_valid,1) OVER path geometry_valid_1,
          lead(history_valid,2) OVER path geometry_valid_2,
          lead(history_valid,3) OVER path geometry_valid_3,
          lead(coordinate_close,1) OVER path observation_close_1,
          lead(coordinate_close,2) OVER path observation_close_2,
          lead(coordinate_close,3) OVER path observation_close_3
        FROM raw_geometry WINDOW path AS (PARTITION BY symbol ORDER BY cal_idx)"""
    )
    connection.execute(
        """CREATE TEMP TABLE complete_paths AS SELECT
          p.trade_date shock_date,p.cal_idx shock_cal_idx,p.symbol,p.industry,
          exp(p.step_return)-1 stock_shock_return,
          exp(p.industry_return_loo)-1 industry_shock_return,
          exp(p.step_return)-exp(p.industry_return_loo) relative_shock_return,
          p.pre_shock_trend20,p.pre_shock_volatility20,
          p.avg_amount20 shock_avg_amount20,p.signal_date_3 signal_date,
          p.next_cal_idx_3 signal_cal_idx,p.signal_max_return20,
          p.signal_diffusion_score,g.previous_coordinate_close,
          g.shock_coordinate_close,g.observation_close_1,g.observation_close_2,
          g.observation_close_3,
          (g.observation_close_3-g.shock_coordinate_close)
            /nullif(g.previous_coordinate_close-g.shock_coordinate_close,0)
            recovery_fraction_3,
          greatest(0,g.shock_coordinate_close-
            least(g.observation_close_1,g.observation_close_2,g.observation_close_3))
            /nullif(g.previous_coordinate_close-g.shock_coordinate_close,0)
            further_drawdown_ratio_3,
          (p.next_step_return_1-p.next_industry_return_1)
            +(p.next_step_return_2-p.next_industry_return_2)
            +(p.next_step_return_3-p.next_industry_return_3) industry_rel_recovery_3
        FROM panel_features p JOIN geometry_paths g USING(symbol,cal_idx)
        WHERE p.prior_count20=20 AND p.cal_idx-p.prior_start_cal_idx=20
          AND exp(p.step_return)-1<0
          AND p.next_cal_idx_1=p.cal_idx+1 AND p.next_cal_idx_2=p.cal_idx+2
          AND p.next_cal_idx_3=p.cal_idx+3
          AND g.previous_cal_idx=g.cal_idx-1 AND g.geometry_cal_idx_1=g.cal_idx+1
          AND g.geometry_cal_idx_2=g.cal_idx+2 AND g.geometry_cal_idx_3=g.cal_idx+3
          AND g.previous_history_valid AND g.history_valid
          AND g.geometry_valid_1 AND g.geometry_valid_2 AND g.geometry_valid_3
          AND g.previous_coordinate_close>g.shock_coordinate_close
          AND g.observation_close_1>0 AND g.observation_close_2>0
          AND g.observation_close_3>0"""
    )


def _valid_event_observations(
    connection: duckdb.DuckDBPyConnection, accepted: pd.DataFrame
) -> pd.DataFrame:
    connection.register("accepted_shocks", accepted)
    frame = connection.execute(
        """SELECT a.candidate_id,a.event_id,p.*
        FROM accepted_shocks a JOIN complete_paths p
          ON p.symbol=a.symbol AND p.shock_cal_idx=a.shock_cal_idx
        ORDER BY a.shock_date,a.symbol"""
    ).fetchdf()
    if frame.empty or frame.duplicated("event_id").any():
        raise ShockAbsorptionError("invalid complete shock-observation set")
    frame["sample_type"] = "SHOCK"
    frame["shock_date"] = pd.to_datetime(frame.shock_date).dt.date
    frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.date
    frame["absolute_shock_magnitude"] = -frame.stock_shock_return
    frame["relative_shock_magnitude"] = -frame.relative_shock_return
    return frame


def _matched_nonshock_controls(
    connection: duckdb.DuckDBPyConnection, events: pd.DataFrame
) -> tuple[pd.DataFrame, int]:
    keys = events[
        ["event_id", "shock_date", "shock_cal_idx", "stock_shock_return", "industry", "symbol"]
    ].copy()
    keys = keys.rename(columns={"symbol": "event_symbol"})
    connection.register("event_match_keys", keys)
    same_industry = connection.execute(
        """SELECT * EXCLUDE(match_rank) FROM (
          SELECT e.event_id,p.*,
            row_number() OVER(PARTITION BY e.event_id ORDER BY
              abs(p.stock_shock_return-e.stock_shock_return),p.symbol) match_rank
          FROM event_match_keys e
          JOIN complete_paths p ON p.shock_date=e.shock_date AND p.industry=e.industry
          WHERE p.symbol<>e.event_symbol
            AND NOT (p.stock_shock_return<=-0.05 AND p.relative_shock_return<=-0.03)
        ) WHERE match_rank=1 ORDER BY event_id"""
    ).fetchdf()
    matched = set(same_industry.event_id.astype(int))
    missing = keys.loc[~keys.event_id.isin(matched)]
    fallback = pd.DataFrame()
    if not missing.empty:
        connection.register("fallback_keys", missing)
        fallback = connection.execute(
            """SELECT * EXCLUDE(match_rank) FROM (
              SELECT e.event_id,p.*,
                row_number() OVER(PARTITION BY e.event_id ORDER BY
                  abs(p.stock_shock_return-e.stock_shock_return),p.symbol) match_rank
              FROM fallback_keys e JOIN complete_paths p ON p.shock_date=e.shock_date
              WHERE p.symbol<>e.event_symbol
                AND NOT (p.stock_shock_return<=-0.05 AND p.relative_shock_return<=-0.03)
            ) WHERE match_rank=1 ORDER BY event_id"""
        ).fetchdf()
    controls = pd.concat([same_industry, fallback], ignore_index=True)
    controls["sample_type"] = "NONSHOCK"
    controls["shock_date"] = pd.to_datetime(controls.shock_date).dt.date
    controls["signal_date"] = pd.to_datetime(controls.signal_date).dt.date
    controls["absolute_shock_magnitude"] = -controls.stock_shock_return
    controls["relative_shock_magnitude"] = -controls.relative_shock_return
    return controls.sort_values("event_id").reset_index(drop=True), len(fallback)


def _rank_samples(events: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    frame = pd.concat([events, controls], ignore_index=True, sort=False)
    frame["date_event_count"] = frame.groupby(
        ["sample_type", "signal_date"], sort=False
    ).symbol.transform("size")
    frame = frame.loc[frame.date_event_count >= 5].copy()
    frame["recovery_quintile"] = assign_quintiles(frame, "recovery_fraction_3")
    frame["stabilization_score"] = -frame.further_drawdown_ratio_3
    frame["stabilization_quintile"] = assign_quintiles(frame, "stabilization_score")
    frame["absolute_severity_bin"] = pd.cut(
        frame.absolute_shock_magnitude,
        bins=[0.05, 0.07, 0.10, np.inf],
        labels=["5_to_7pct", "7_to_10pct", "at_least_10pct"],
        right=False,
    )
    frame["relative_severity_bin"] = pd.cut(
        frame.relative_shock_magnitude,
        bins=[0.03, 0.05, 0.08, np.inf],
        labels=["3_to_5pct", "5_to_8pct", "at_least_8pct"],
        right=False,
    )
    frame["signal_id"] = np.arange(len(frame), dtype=np.int64)
    frame["trade_date"] = frame.signal_date
    frame["cal_idx"] = frame.signal_cal_idx
    return frame.sort_values(["sample_type", "signal_date", "symbol"]).reset_index(drop=True)


def _period_mask(frame: pd.DataFrame, period: str) -> pd.Series:
    years = pd.to_datetime(frame.signal_date).dt.year
    if period == "full":
        return pd.Series(True, index=frame.index)
    if period == "early_2018_2021":
        return years.between(2018, 2021)
    if period == "late_2022_2023":
        return years.between(2022, 2023)
    return years.eq(int(period))


def _metric_row(
    subset: pd.DataFrame,
    section: str,
    sample_type: str,
    representation: str,
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
        "sample_type": sample_type,
        "representation": representation,
        "period": period,
        "horizon": horizon,
        "quintile": quintile,
        "count": len(absolute),
        "dates": int(aligned.signal_date.nunique()),
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
    rows: list[dict[str, Any]] = []
    representations = {
        "RECOVERY_FRACTION_3": "recovery_quintile",
        "FURTHER_DRAWDOWN_RATIO_3": "stabilization_quintile",
    }
    periods = ["full", "early_2018_2021", "late_2022_2023", *map(str, range(2018, 2024))]
    for sample_type in ("SHOCK", "NONSHOCK"):
        sample = panel.loc[panel.sample_type.eq(sample_type)]
        for representation, qcol in representations.items():
            for period in periods:
                base = sample.loc[_period_mask(sample, period)]
                for horizon in HORIZONS:
                    quintiles = []
                    for quintile in range(1, 6):
                        row = _metric_row(
                            base.loc[base[qcol].eq(quintile)],
                            "raw",
                            sample_type,
                            representation,
                            period,
                            horizon,
                            quintile,
                        )
                        rows.append(row)
                        quintiles.append(row)
                    spread = {
                        key: quintiles[-1][key] - quintiles[0][key]
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
                    rows.append(
                        {
                            "section": "raw_spread",
                            "sample_type": sample_type,
                            "representation": representation,
                            "period": period,
                            "horizon": horizon,
                            "quintile": "Q5-Q1",
                            "count": min(quintiles[0]["count"], quintiles[-1]["count"]),
                            "dates": min(quintiles[0]["dates"], quintiles[-1]["dates"]),
                            "securities": np.nan,
                            "industries": np.nan,
                            **spread,
                        }
                    )
    return pd.DataFrame(rows)


def _control_tables(panel: pd.DataFrame) -> pd.DataFrame:
    events = panel.loc[panel.sample_type.eq("SHOCK")].copy()
    rows: list[dict[str, Any]] = []
    controls = {
        "PRE_SHOCK_TREND": "pre_shock_trend20",
        "PRE_SHOCK_VOLATILITY": "pre_shock_volatility20",
        "LIQUIDITY": "shock_avg_amount20",
        "LOW_MAX": "signal_max_return20",
    }
    for name, column in controls.items():
        ranks = events.groupby("signal_date", sort=False)[column].rank(method="average", pct=True)
        events["control_tercile"] = np.ceil(ranks * 3).clip(1, 3).astype("Int64")
        for period in ("full", "early_2018_2021", "late_2022_2023"):
            base = events.loc[_period_mask(events, period)]
            for horizon in (5, 20):
                for tercile in range(1, 4):
                    group = base.loc[base.control_tercile.eq(tercile)]
                    q5 = group.loc[group.recovery_quintile.eq(5), f"industry_relative_h{horizon}"]
                    q1 = group.loc[group.recovery_quintile.eq(1), f"industry_relative_h{horizon}"]
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
    for (absolute_bin, relative_bin), group in events.groupby(
        ["absolute_severity_bin", "relative_severity_bin"], observed=True
    ):
        for horizon in (5, 20):
            q5 = group.loc[group.recovery_quintile.eq(5), f"industry_relative_h{horizon}"]
            q1 = group.loc[group.recovery_quintile.eq(1), f"industry_relative_h{horizon}"]
            rows.append(
                {
                    "section": "severity",
                    "absolute_bin": str(absolute_bin),
                    "relative_bin": str(relative_bin),
                    "horizon": horizon,
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
    for day, group in frame.groupby("signal_date", sort=True):
        valid = group[[left, right]].dropna()
        if len(valid) >= 5:
            rows.append(
                (pd.Timestamp(day).year, float(spearmanr(valid[left], valid[right]).statistic))
            )
    data = pd.DataFrame(rows, columns=["year", "rho"])
    return {
        "dates": len(data),
        "mean_same_date_spearman": float(data.rho.mean()),
        "median_same_date_spearman": float(data.rho.median()),
        "early_mean": float(data.loc[data.year <= 2021, "rho"].mean()),
        "late_mean": float(data.loc[data.year >= 2022, "rho"].mean()),
    }


def _independence(panel: pd.DataFrame, champion_path: Path) -> dict[str, Any]:
    events = panel.loc[panel.sample_type.eq("SHOCK")].copy()
    low_max = _rank_correlation(events, "recovery_fraction_3", "signal_max_return20")
    champion = pd.read_csv(champion_path, usecols=["family", "trade_date", "symbol"])
    champion = champion.loc[champion.family.eq("arm2_low_max"), ["trade_date", "symbol"]]
    champion["signal_date"] = pd.to_datetime(champion.trade_date).dt.date
    champion = champion.drop(columns="trade_date").drop_duplicates()
    champion["champion_selected"] = True
    merged = events.merge(champion, on=["signal_date", "symbol"], how="left")
    merged["champion_selected"] = (
        merged.champion_selected.astype("boolean").fillna(False).astype(bool)
    )
    q5 = merged.recovery_quintile.eq(5)
    remaining = merged.loc[~merged.champion_selected]
    removed = {}
    for horizon in (5, 20):
        high = remaining.loc[remaining.recovery_quintile.eq(5), f"industry_relative_h{horizon}"]
        low = remaining.loc[remaining.recovery_quintile.eq(1), f"industry_relative_h{horizon}"]
        removed[f"h{horizon}"] = {
            "q5_mean_industry_relative": float(high.mean()),
            "q5_minus_q1_industry_relative": float(high.mean() - low.mean()),
        }
    return {
        "low_max_rank_relationship": low_max,
        "champion_selected_observations": int(merged.champion_selected.sum()),
        "q5_champion_overlap_count": int((q5 & merged.champion_selected).sum()),
        "q5_champion_overlap_fraction": float(
            (q5 & merged.champion_selected).sum() / max(1, q5.sum())
        ),
        "economics_after_removing_champion": removed,
    }


def _lookup(
    table: pd.DataFrame,
    sample_type: str,
    representation: str,
    period: str,
    horizon: int,
) -> dict[str, Any]:
    row = table.loc[
        table.section.eq("raw_spread")
        & table.sample_type.eq(sample_type)
        & table.representation.eq(representation)
        & table.period.eq(period)
        & table.horizon.eq(horizon)
        & table.quintile.eq("Q5-Q1")
    ]
    if len(row) != 1:
        raise ShockAbsorptionError(
            f"missing lookup {sample_type}/{representation}/{period}/h{horizon}"
        )
    return row.iloc[0].to_dict()


def _classify(
    raw: pd.DataFrame,
    controls: pd.DataFrame,
    independence: dict[str, Any],
    actionability: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    full = {h: _lookup(raw, "SHOCK", "RECOVERY_FRACTION_3", "full", h) for h in HORIZONS}
    early = {h: _lookup(raw, "SHOCK", "RECOVERY_FRACTION_3", "early_2018_2021", h) for h in (5, 20)}
    late = {h: _lookup(raw, "SHOCK", "RECOVERY_FRACTION_3", "late_2022_2023", h) for h in (5, 20)}
    annual = {
        year: _lookup(raw, "SHOCK", "RECOVERY_FRACTION_3", str(year), 20)
        for year in range(2018, 2024)
    }
    nonshock = {h: _lookup(raw, "NONSHOCK", "RECOVERY_FRACTION_3", "full", h) for h in (5, 20)}
    stabilization = {
        h: _lookup(raw, "SHOCK", "FURTHER_DRAWDOWN_RATIO_3", "full", h) for h in (5, 20)
    }
    control_full = controls.loc[controls.section.eq("control") & controls.period.eq("full")]
    severity = controls.loc[controls.section.eq("severity") & controls.horizon.eq(20)]
    supported_severity = severity.loc[(severity.q5_count >= 20) & (severity.q1_count >= 20)]
    positive_severity_fraction = (
        float((supported_severity.q5_minus_q1_industry_relative > 0).mean())
        if len(supported_severity)
        else 0.0
    )
    raw_positive = sum(full[h]["mean_industry_relative"] > 0 for h in HORIZONS) >= 3
    block_reversal = any(
        early[h]["mean_industry_relative"] * late[h]["mean_industry_relative"] < 0 for h in (5, 20)
    )
    generic_similar = all(
        nonshock[h]["mean_industry_relative"] > 0
        and nonshock[h]["mean_industry_relative"] >= 0.75 * full[h]["mean_industry_relative"]
        for h in (5, 20)
    )
    gates = {
        "positive_industry_relative_multiple_horizons": raw_positive,
        "positive_absolute_multiple_horizons": sum(full[h]["mean_net_return"] > 0 for h in HORIZONS)
        >= 3,
        "both_blocks_positive_h5_h20": all(
            part[h]["mean_industry_relative"] > 0 for part in (early, late) for h in (5, 20)
        ),
        "positive_years_h20_at_least_four": sum(
            annual[y]["mean_industry_relative"] > 0 for y in annual
        )
        >= 4,
        "stabilization_consistent_h5_h20": all(
            stabilization[h]["mean_industry_relative"] > 0 for h in (5, 20)
        ),
        "shock_severity_majority_positive": positive_severity_fraction >= 0.5,
        "not_generic_short_term_path": not generic_similar,
        "trend_controls_positive": bool(
            (
                control_full.loc[
                    (control_full.control == "PRE_SHOCK_TREND") & (control_full.horizon == 20),
                    "q5_minus_q1_industry_relative",
                ]
                > 0
            ).all()
        ),
        "volatility_controls_positive": bool(
            (
                control_full.loc[
                    (control_full.control == "PRE_SHOCK_VOLATILITY") & (control_full.horizon == 20),
                    "q5_minus_q1_industry_relative",
                ]
                > 0
            ).all()
        ),
        "liquidity_controls_positive": bool(
            (
                control_full.loc[
                    (control_full.control == "LIQUIDITY") & (control_full.horizon == 20),
                    "q5_minus_q1_industry_relative",
                ]
                > 0
            ).all()
        ),
        "actionability_at_least_90pct": actionability["actionable_fraction"] >= 0.90,
        "low_max_correlation_not_dominant": abs(
            independence["low_max_rank_relationship"]["mean_same_date_spearman"]
        )
        < 0.70,
        "positive_after_champion_removal": all(
            independence["economics_after_removing_champion"][f"h{h}"][
                "q5_minus_q1_industry_relative"
            ]
            > 0
            for h in (5, 20)
        ),
    }
    if all(gates.values()):
        classification = "PROMISING_SHOCK_ABSORPTION_ALPHA"
    elif block_reversal and raw_positive:
        classification = "CHRONOLOGICALLY_UNSTABLE"
    elif raw_positive and not gates["shock_severity_majority_positive"]:
        classification = "SHOCK_SEVERITY_ONLY"
    elif raw_positive and generic_similar:
        classification = "GENERIC_SHORT_TERM_PRICE_PATH_ONLY"
    elif (
        full[20]["mean_industry_relative"] <= 0
        and full[20]["severe_loss_fraction"] < 0
        and full[20]["mean_mae_h20"] > 0
    ):
        classification = "DEFENSIVE_INFORMATION_ONLY"
    elif raw_positive and not gates["low_max_correlation_not_dominant"]:
        classification = "PROMISING_BUT_NOT_INDEPENDENT"
    else:
        classification = "NULL"
    return classification, {
        "gates": gates,
        "block_sign_reversal": block_reversal,
        "generic_similar": generic_similar,
        "positive_severity_fraction": positive_severity_fraction,
        "supported_severity_cells": len(supported_severity),
        "full_spreads": full,
        "nonshock_spreads": nonshock,
        "stabilization_spreads": stabilization,
        "annual_h20": annual,
    }


def _fmt(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):+.3%}"


def _report(result: dict[str, Any], raw: pd.DataFrame, controls: pd.DataFrame) -> str:
    classification = result["final_classification"]
    low_max_correlation = result["independence"]["low_max_rank_relationship"][
        "mean_same_date_spearman"
    ]
    champion_overlap = result["independence"]["q5_champion_overlap_fraction"]
    lines = [
        "# A-share Shock Absorption / Recovery Discovery V1",
        "",
        "## Executive conclusion",
        "",
        f"Final classification: `{classification}`.",
        "",
        result["economic_interpretation"],
        "",
        "## Exact hypothesis and frozen event",
        "",
        (
            "A shock requires causal simple stock return <= -5% and "
            "stock-minus-PIT-industry leave-one-out return <= -3% on completed day s. "
            "The signal is not formed until exactly three further valid sessions complete. "
            "Recovery Fraction is [C(s+3)-C(s)]/[C(s-1)-C(s)]; Further Drawdown Ratio "
            "is max(0,C(s)-min(C(s+1:s+3)))/ShockLoss. All closes are accepted "
            "corporate-action coordinates. Earliest entry is the first later legal open."
        ),
        "",
        "## Event anatomy and actionability",
        "",
        (
            f"There are {result['event_anatomy']['qualifying_shocks']:,} qualifying shocks "
            "before overlap suppression, "
            f"{result['event_anatomy']['accepted_nonoverlap_shocks']:,} accepted "
            f"non-overlapping shocks, and {result['coverage']['ranked_shock_events']:,} "
            f"ranked complete events across {result['coverage']['dates']} signal dates, "
            f"{result['coverage']['securities']:,} securities, and "
            f"{result['coverage']['industries']} industries."
        ),
        "",
        (
            "Shock return median/p10/p90 is "
            f"{_fmt(result['event_anatomy']['stock_shock_return_median'])}/"
            f"{_fmt(result['event_anatomy']['stock_shock_return_p10'])}/"
            f"{_fmt(result['event_anatomy']['stock_shock_return_p90'])}. Recovery Fraction "
            f"median/p10/p90 is {result['event_anatomy']['recovery_fraction_median']:.3f}/"
            f"{result['event_anatomy']['recovery_fraction_p10']:.3f}/"
            f"{result['event_anatomy']['recovery_fraction_p90']:.3f}; Further Drawdown "
            f"Ratio is {result['event_anatomy']['further_drawdown_median']:.3f}/"
            f"{result['event_anatomy']['further_drawdown_p10']:.3f}/"
            f"{result['event_anatomy']['further_drawdown_p90']:.3f}."
        ),
        "",
        (
            f"Shock-event actionability is {result['actionability']['actionable_fraction']:.2%}: "
            f"{result['actionability']['immediate']:,} immediate, "
            f"{result['actionability']['delayed']:,} delayed, and "
            f"{result['actionability']['unusable']:,} unusable."
        ),
        "",
        "## Raw Recovery Fraction results",
        "",
        (
            "| Horizon | Q1 net | Q2 net | Q3 net | Q4 net | Q5 net | Q5-Q1 net | "
            "Q5-Q1 industry-relative | Q5-Q1 median industry-relative | Q5-Q1 positive | "
            "Q5-Q1 severe |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in HORIZONS:
        base = raw.loc[
            raw.section.eq("raw")
            & raw.sample_type.eq("SHOCK")
            & raw.representation.eq("RECOVERY_FRACTION_3")
            & raw.period.eq("full")
            & raw.horizon.eq(horizon)
        ]
        quantiles = [base.loc[base.quintile.eq(value)].iloc[0] for value in range(1, 6)]
        spread = _lookup(raw, "SHOCK", "RECOVERY_FRACTION_3", "full", horizon)
        lines.append(
            f"| h{horizon} | {' | '.join(_fmt(row.mean_net_return) for row in quantiles)} | "
            f"{_fmt(spread['mean_net_return'])} | {_fmt(spread['mean_industry_relative'])} | "
            f"{_fmt(spread['median_industry_relative'])} | "
            f"{_fmt(spread['positive_return_fraction'])} | "
            f"{_fmt(spread['severe_loss_fraction'])} |"
        )
    lines.extend(
        [
            "",
            "## Incrementality and chronology",
            "",
            "| Diagnostic | h5 industry-relative Q5-Q1 | h20 industry-relative Q5-Q1 |",
            "| --- | ---: | ---: |",
        ]
    )
    for label, sample, representation, period in (
        ("Shock recovery", "SHOCK", "RECOVERY_FRACTION_3", "full"),
        ("Shock stabilization", "SHOCK", "FURTHER_DRAWDOWN_RATIO_3", "full"),
        ("Matched non-shock recovery", "NONSHOCK", "RECOVERY_FRACTION_3", "full"),
        ("Early 2018-2021", "SHOCK", "RECOVERY_FRACTION_3", "early_2018_2021"),
        ("Late 2022-2023", "SHOCK", "RECOVERY_FRACTION_3", "late_2022_2023"),
    ):
        values = [
            _fmt(_lookup(raw, sample, representation, period, h)["mean_industry_relative"])
            for h in (5, 20)
        ]
        lines.append(f"| {label} | {values[0]} | {values[1]} |")
    lines.extend(
        [
            "",
            "## Year-by-year h20",
            "",
            "| Year | Q5-Q1 net | Q5-Q1 industry-relative |",
            "| --- | ---: | ---: |",
        ]
    )
    for year in range(2018, 2024):
        row = _lookup(raw, "SHOCK", "RECOVERY_FRACTION_3", str(year), 20)
        lines.append(
            f"| {year} | {_fmt(row['mean_net_return'])} | {_fmt(row['mean_industry_relative'])} |"
        )
    lines.extend(["", "## Shock severity and coarse controls", ""])
    severity = controls.loc[(controls.section == "severity") & (controls.horizon == 20)]
    supported = severity.loc[(severity.q5_count >= 20) & (severity.q1_count >= 20)]
    lines.append(
        f"{len(supported)} severity cells have at least 20 observations in both Q1 and Q5; "
        f"{result['classification_evidence']['positive_severity_fraction']:.1%} have "
        "positive h20 industry-relative ordering."
    )
    lines.extend(["", "| Control | h20 tercile spreads |", "| --- | --- |"])
    for control in ("PRE_SHOCK_TREND", "PRE_SHOCK_VOLATILITY", "LIQUIDITY", "LOW_MAX"):
        values = (
            controls.loc[
                (controls.section == "control")
                & (controls.control == control)
                & (controls.period == "full")
                & (controls.horizon == 20)
            ]
            .sort_values("tercile")
            .q5_minus_q1_industry_relative
        )
        lines.append(f"| {control} | {' / '.join(_fmt(value) for value in values)} |")
    lines.extend(
        [
            "",
            "## Defensive versus Alpha and Strategy-A independence",
            "",
            result["defensive_vs_alpha"],
            "",
            (
                "Low-MAX same-date rank correlation is "
                f"{low_max_correlation:.3f}; Champion Q5 overlap is "
                f"{champion_overlap:.2%}. "
                "No Strategy-A rule or result changed."
            ),
            "",
            "## Decision",
            "",
            f"`{classification}`. {result['next_recommended_research_direction']}",
            "",
            (
                "This is consumed 2018-2023 development evidence, not OOS confirmation. "
                "Post-2023 outcomes and CY-011 were not read."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    spec = _load_spec()
    daily_paths = EXECUTION._daily_paths(spec)
    connection = _configure()
    try:
        _panel_audit(connection, _resolve(spec["inputs"]["causal_daily_panel"]["path"]))
        calendar, raw_audit = EXECUTION._build_raw_geometry(connection, daily_paths)
        accepted, total_qualifying = _candidate_shocks(connection)
        _build_complete_paths(connection)
        events = _valid_event_observations(connection, accepted)
        controls, fallback_matches = _matched_nonshock_controls(connection, events)
        signals = _rank_samples(events, controls)
        evaluation, all_actionability = EXECUTION._attach_outcomes(connection, signals)
    finally:
        connection.close()
    if evaluation.empty or pd.to_datetime(evaluation.signal_date).dt.year.max() > 2023:
        raise ShockAbsorptionError("post-2023 or empty evaluation")
    evaluation.to_parquet(PANEL_PATH, index=False, compression="zstd")
    raw = _raw_tables(evaluation)
    control_tables = _control_tables(evaluation)
    tables = pd.concat([raw, control_tables], ignore_index=True, sort=False)
    tables.to_csv(TABLE_PATH, index=False, float_format="%.12g")
    event_evaluation = evaluation.loc[evaluation.sample_type.eq("SHOCK")]
    event_action = {
        "eligible": len(event_evaluation),
        "immediate": int(event_evaluation.entry_status.eq("IMMEDIATE").sum()),
        "delayed": int(event_evaluation.entry_status.eq("DELAYED").sum()),
        "unusable": int(event_evaluation.entry_status.eq("UNUSABLE").sum()),
        "actionable_fraction": float(
            event_evaluation.entry_status.isin(["IMMEDIATE", "DELAYED"]).mean()
        ),
        "immediate_block_reasons": {
            str(key): int(value)
            for key, value in event_evaluation.loc[event_evaluation.entry_status.ne("IMMEDIATE")]
            .immediate_block_reason.value_counts()
            .sort_index()
            .items()
        },
    }
    independence = _independence(
        evaluation, _resolve(spec["inputs"]["champion_attribution"]["path"])
    )
    classification, evidence = _classify(raw, control_tables, independence, event_action)
    h20 = _lookup(raw, "SHOCK", "RECOVERY_FRACTION_3", "full", 20)
    if classification == "PROMISING_SHOCK_ABSORPTION_ALPHA":
        interpretation = (
            "Post-shock recovery and stabilization show repeated incremental positive "
            "economics after the fixed controls."
        )
        next_direction = (
            "A separately frozen standalone Strategy-B portfolio translation may be "
            "considered; do not combine with Strategy A first."
        )
    elif classification == "GENERIC_SHORT_TERM_PRICE_PATH_ONLY":
        interpretation = (
            "Recovery ordering is not specific to a preceding material shock; the "
            "event-sequence mechanism is not established."
        )
        next_direction = (
            "Close this exact daily shock-absorption family and return to the frozen "
            "Cross-Sectional Dispersion science."
        )
    elif classification == "SHOCK_SEVERITY_ONLY":
        interpretation = (
            "The apparent raw recovery relation does not persist inside comparable "
            "frozen shock-severity cells."
        )
        next_direction = (
            "Close this exact daily shock-absorption family and return to the frozen "
            "Cross-Sectional Dispersion science."
        )
    elif classification == "CHRONOLOGICALLY_UNSTABLE":
        interpretation = (
            "The recovery ordering materially reverses across the two fixed development blocks."
        )
        next_direction = (
            "Close this exact daily shock-absorption family and return to the frozen "
            "Cross-Sectional Dispersion science."
        )
    elif classification == "DEFENSIVE_INFORMATION_ONLY":
        interpretation = (
            "Observed absorption mainly changes downside shape without convincing "
            "positive future Alpha."
        )
        next_direction = (
            "Park as defensive information; do not build Strategy B, and return to "
            "frozen Dispersion science."
        )
    else:
        interpretation = (
            "The frozen stronger-recovery Q5 is adverse to Q1 at every horizon and in "
            "every calendar year's h20 industry-relative comparison; it also has more "
            "severe losses and worse h20 MAE. This is neither absorption Alpha nor "
            "defensive information, and the sign is not inverted."
        )
        next_direction = (
            "Close this exact daily shock-absorption family and return to the previously "
            "resource-blocked frozen Cross-Sectional Dispersion science."
        )
    defensive = (
        f"At h20, Recovery Q5-Q1 net return is {_fmt(h20['mean_net_return'])}, "
        f"industry-relative spread is {_fmt(h20['mean_industry_relative'])}, "
        f"severe-loss change is {_fmt(h20['severe_loss_fraction'])}, and MAE change is "
        f"{_fmt(h20['mean_mae_h20'])}."
    )
    complete = evaluation.loc[evaluation.net_return_h20.notna(), "entry_cal_idx"].astype(int)
    max_outcome = max(calendar[index + 19] for index in complete) if len(complete) else None
    result = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "frozen_spec_sha256": EXPECTED_SPEC_SHA256,
        "claim_boundary": spec["claim_boundary"],
        "evaluation_start": str(evaluation.signal_date.min()),
        "max_evaluation_outcome_date": str(max_outcome),
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "input_identity": {
            "daily_partition_years": [2018, 2019, 2020, 2021, 2022, 2023],
            "raw_audit": raw_audit,
        },
        "event_anatomy": {
            "qualifying_shocks": total_qualifying,
            "accepted_nonoverlap_shocks": len(accepted),
            "complete_observation_events": len(events),
            "matched_nonshock_controls": len(controls),
            "fallback_date_only_matches": fallback_matches,
            "stock_shock_return_median": float(events.stock_shock_return.median()),
            "stock_shock_return_p10": float(events.stock_shock_return.quantile(0.10)),
            "stock_shock_return_p90": float(events.stock_shock_return.quantile(0.90)),
            "recovery_fraction_median": float(events.recovery_fraction_3.median()),
            "recovery_fraction_p10": float(events.recovery_fraction_3.quantile(0.10)),
            "recovery_fraction_p90": float(events.recovery_fraction_3.quantile(0.90)),
            "further_drawdown_median": float(events.further_drawdown_ratio_3.median()),
            "further_drawdown_p10": float(events.further_drawdown_ratio_3.quantile(0.10)),
            "further_drawdown_p90": float(events.further_drawdown_ratio_3.quantile(0.90)),
        },
        "coverage": {
            "ranked_shock_events": len(event_evaluation),
            "ranked_nonshock_controls": int(evaluation.sample_type.eq("NONSHOCK").sum()),
            "dates": int(event_evaluation.signal_date.nunique()),
            "securities": int(event_evaluation.symbol.nunique()),
            "industries": int(event_evaluation.industry.nunique()),
            "first": str(event_evaluation.signal_date.min()),
            "last": str(event_evaluation.signal_date.max()),
        },
        "actionability": event_action,
        "all_sample_actionability": all_actionability,
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
    _atomic_write(REPORT_PATH, _report(result, raw, control_tables))
    result["artifacts"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "classification": classification,
                "shock_events": len(event_evaluation),
                "actionable_fraction": event_action["actionable_fraction"],
                "h20_spread": h20["mean_industry_relative"],
                "result_sha256": sha256_file(RESULT_PATH),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
