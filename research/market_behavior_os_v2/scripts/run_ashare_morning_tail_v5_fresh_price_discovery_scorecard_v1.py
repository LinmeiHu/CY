#!/usr/bin/env python3
"""Build and audit the frozen Morning-Tail V5 simple scorecard.

The runner deliberately separates causal feature materialization from outcome
attachment.  Stage A contains no return, exit, or holding-period fields.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / (
    "experiments/"
    "ASHARE-MORNING-TAIL-V5-FRESH-PRICE-DISCOVERY-SCORECARD-V1_stage_a_spec.json"
)
RESULT_PATH = PROGRAM / (
    "artifacts/ASHARE-MORNING-TAIL-V5-FRESH-PRICE-DISCOVERY-SCORECARD-V1_result.json"
)
REPORT_PATH = PROGRAM / (
    "reports/ASHARE-MORNING-TAIL-V5-FRESH-PRICE-DISCOVERY-SCORECARD-V1_report.md"
)
EXTERNAL_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_morning_tail_v5_fresh_price_discovery_scorecard_v1"
)
STAGE_A = EXTERNAL_ROOT / "stage_a"
STAGE_B = EXTERNAL_ROOT / "stage_b"
FEATURE_PANEL = STAGE_A / "causal_feature_panel_2014_2026.parquet"
RECENT_FEATURES = STAGE_A / "recent_features_2024_2026.parquet"
RECENT_RAW_CACHE = STAGE_A / "recent_raw_features_2024_2026.parquet"
MARKET_CONTEXT = STAGE_A / "market_context_2024_2026.parquet"
SELECTED_TRADES = STAGE_B / "selected_trades.parquet"
STAGE_A_MANIFEST = STAGE_A / "manifest.json"
EXTERNAL_RESULT = STAGE_B / "result.json"

V4_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_morning_tail_regime_routed_demand_price_discovery_v4"
)
V4_DEV = V4_ROOT / "stage_b_development/trades.parquet"
V4_CHALLENGE = V4_ROOT / "stage_c_challenge/trades.parquet"
V4_RECENT = V4_ROOT / "post_observation_2024_2026/trades_2024_2026.parquet"
TAIL_EVENTS = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_morning_industry_demand_acceptance_v1r1/"
    "v2_tail_acceptance/stage_a/events_frozen.parquet"
)
MODEL_PANEL = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/"
    "model_panel_2013_2023.parquet"
)
RAW_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)
DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/"
    "pit_b_daily_2018_2026_v2/daily"
)
EXECUTION_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/"
    "pit_b_minute_2018_2026_v2/execution_5m"
)

EXPERIMENT = "ASHARE-MORNING-TAIL-V5-FRESH-PRICE-DISCOVERY-SCORECARD-V1"
YEARS_RECENT = (2024, 2025, 2026)
QMT_TAIL_START = pd.Timestamp("2026-04-13").date()
EXPECTED_PARENT_HASH = "f4f33eca5c01e29dfdfc2b782ba91b943a14d8c763cbcdcbdcdd79686e98a029"


class V5Error(RuntimeError):
    """Fail-closed V5 implementation error."""


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise V5Error(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_module(
    "morning_tail_v5_tail_core", Path(__file__).with_name("ashare_tail_open_lgbm_v1_core.py")
)
ADAPTER = _load_module(
    "morning_tail_v5_minute_adapter",
    Path(__file__).with_name("vectorized_market_minute_adapter.py"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_spec() -> dict[str, Any]:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("experiment") != EXPERIMENT:
        raise V5Error("experiment identity changed")
    parent = spec.get("parent_contract", {})
    if parent.get("sha256") != EXPECTED_PARENT_HASH or parent.get("identity_changed") is not False:
        raise V5Error("parent V4 identity is not frozen")
    scorecard = spec.get("fixed_scorecard", {})
    if scorecard.get("minimum_true_conditions") != 2:
        raise V5Error("scorecard threshold changed")
    definitions = [item.get("definition") for item in scorecard.get("conditions", [])]
    expected = [
        "prior_ret_10 <= 0",
        "path_efficiency_1425 >= 0.20",
        "afternoon_amount_fraction_1425 >= 0.30",
        "market_dispersion_1425 >= 0.03",
    ]
    if definitions != expected:
        raise V5Error("scorecard conditions changed")
    return spec


def _connection() -> duckdb.DuckDBPyConnection:
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='6GB'")
    connection.execute(f"SET temp_directory='{EXTERNAL_ROOT.as_posix()}'")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        temporary,
        compression="zstd",
        row_group_size=max(1, min(100_000, len(frame))),
    )
    os.replace(temporary, path)


def _atomic_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def score_conditions(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply only the four frozen, completed-information conditions."""
    required = {
        "prior_ret_10",
        "path_efficiency_1425",
        "afternoon_amount_fraction_1425",
        "market_dispersion_1425",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise V5Error(f"scorecard features missing: {missing}")
    result = frame.copy()
    result["recently_unextended"] = result["prior_ret_10"] <= 0.0
    result["directionally_efficient"] = result["path_efficiency_1425"] >= 0.20
    result["afternoon_participation"] = (
        result["afternoon_amount_fraction_1425"] >= 0.30
    )
    result["cross_sectional_opportunity"] = result["market_dispersion_1425"] >= 0.03
    flags = [
        "recently_unextended",
        "directionally_efficient",
        "afternoon_participation",
        "cross_sectional_opportunity",
    ]
    result["scorecard_count"] = result[flags].astype(np.int8).sum(axis=1)
    result["admitted"] = result["scorecard_count"] >= 2
    return result


def _old_causal_features() -> pd.DataFrame:
    connection = _connection()
    query = """
    WITH identities AS (
      SELECT event_id,symbol,trade_date,signal_year,sleeve,route,entry_at,entry_coord
      FROM read_parquet(?)
      UNION ALL BY NAME
      SELECT event_id,symbol,trade_date,signal_year,sleeve,route,entry_at,entry_coord
      FROM read_parquet(?)
    ), tails AS (
      SELECT symbol,trade_date,morning_low_coord,industry_ret1000,
        close1000,cutoff_close
      FROM read_parquet(?)
    ), panel AS (
      SELECT symbol,trade_date,prior_ret_10,path_efficiency_1425,
        afternoon_amount_fraction_1425,market_dispersion_1425,
        market_return_1425,market_breadth_1425,industry_return_1425,
        industry_breadth_1425
      FROM read_parquet(?)
    )
    SELECT i.*,t.morning_low_coord,t.industry_ret1000,t.close1000,t.cutoff_close,
      p.* EXCLUDE(symbol,trade_date),
      CAST(i.trade_date AS TIMESTAMP)+INTERVAL '14 hours 25 minutes' AS feature_available_at
    FROM identities i
    JOIN tails t USING(symbol,trade_date)
    JOIN panel p USING(symbol,trade_date)
    ORDER BY i.trade_date,i.symbol
    """
    frame = connection.execute(
        query, [str(V4_DEV), str(V4_CHALLENGE), str(TAIL_EVENTS), str(MODEL_PANEL)]
    ).df()
    connection.close()
    if len(frame) != 1668 or frame["event_id"].duplicated().any():
        raise V5Error("2014-2023 V4 identity reconciliation changed")
    return frame


def _recent_identities() -> pd.DataFrame:
    connection = _connection()
    frame = connection.execute(
        """SELECT event_id,symbol,trade_date,signal_year,sleeve,route,entry_at,
        entry_coord,morning_low_coord,industry_ret1000,close1000,cutoff_close
        FROM read_parquet(?) ORDER BY trade_date,symbol""",
        [str(V4_RECENT)],
    ).df()
    connection.close()
    if len(frame) != 714 or frame["event_id"].duplicated().any():
        raise V5Error("2024-2026 V4 identity reconciliation changed")
    return frame


def _recent_raw_features(identities: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if RECENT_RAW_CACHE.is_file():
        cached = pq.read_table(RECENT_RAW_CACHE).to_pandas()
        expected = identities[["symbol", "trade_date"]].copy()
        expected["trade_date"] = pd.to_datetime(expected["trade_date"])
        observed = cached[["symbol", "trade_date"]].copy()
        observed["trade_date"] = pd.to_datetime(observed["trade_date"])
        if (
            len(cached) == len(expected)
            and not cached.duplicated(["symbol", "trade_date"]).any()
            and expected.merge(observed, on=["symbol", "trade_date"], how="outer", indicator=True)[
                "_merge"
            ].eq("both").all()
        ):
            return cached, {"cache_reused": True, "rows": int(len(cached))}
        raise V5Error("recent raw feature cache identity changed")
    pieces: list[pd.DataFrame] = []
    audits: dict[str, Any] = {}
    for year in YEARS_RECENT:
        keys = identities.loc[identities["signal_year"] == year, ["symbol", "trade_date"]].copy()
        if keys.empty:
            continue
        keys["trade_date"] = pd.to_datetime(keys["trade_date"])
        source_symbols = sorted({value.split(".")[0] for value in keys["symbol"]})
        dates = sorted(pd.Timestamp(value).date() for value in keys["trade_date"].unique())
        raw_tables: list[pa.Table] = []
        day_dates = dates if year != 2026 else [value for value in dates if value < QMT_TAIL_START]
        if day_dates:
            raw_tables.append(
                ADAPTER.read_raw_table(
                    RAW_ROOT / f"{year}_day_parquet_none.parquet",
                    day_dates,
                    source_symbols=source_symbols,
                )
            )
        if year == 2026:
            tail_dates = [value for value in dates if value >= QMT_TAIL_START]
            if tail_dates:
                raw_tables.append(
                    ADAPTER.read_raw_table(
                        RAW_ROOT / "2026_qmt_tail.parquet",
                        tail_dates,
                        source_symbols=source_symbols,
                    )
                )
        if len(raw_tables) > 1:
            raw = pa.concat_tables(raw_tables).sort_by(
                [
                    ("symbol", "ascending"),
                    ("exchange", "ascending"),
                    ("trade_date", "ascending"),
                    ("bar_end_time", "ascending"),
                ]
            )
        else:
            raw = raw_tables[0]
        features, audit = CORE.extract_raw_day(raw)
        selected = keys.merge(features, on=["symbol", "trade_date"], how="left", validate="one_to_one")
        required = ["path_efficiency_1425", "afternoon_amount_fraction_1425"]
        if selected[required].isna().any().any():
            failures = selected.loc[selected[required].isna().any(axis=1), ["symbol", "trade_date"]]
            raise V5Error(f"candidate raw feature missing in {year}: {len(failures)}")
        pieces.append(selected[["symbol", "trade_date", *required]])
        audits[str(year)] = {
            **audit,
            "candidate_keys": int(len(keys)),
            "candidate_symbols": int(keys["symbol"].nunique()),
            "candidate_dates": int(keys["trade_date"].nunique()),
        }
    frame = pd.concat(pieces, ignore_index=True)
    if len(frame) != len(identities):
        raise V5Error("recent raw feature row count changed")
    _atomic_parquet(frame, RECENT_RAW_CACHE)
    return frame, audits


def _recent_daily_and_market_context(
    identities: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    daily_pieces: list[pd.DataFrame] = []
    context_pieces: list[pd.DataFrame] = []
    year_audits: dict[str, Any] = {}
    for year in YEARS_RECENT:
        daily_cache = STAGE_A / f"candidate_daily_features_{year}.parquet"
        context_cache = STAGE_A / f"market_context_{year}.parquet"
        if daily_cache.is_file() and context_cache.is_file():
            daily = pq.read_table(daily_cache).to_pandas()
            context = pq.read_table(context_cache).to_pandas()
            expected_rows = int(identities["signal_year"].eq(year).sum())
            if len(daily) != expected_rows or daily.duplicated(["symbol", "trade_date"]).any():
                raise V5Error(f"daily feature cache identity changed: {year}")
            daily_pieces.append(daily)
            context_pieces.append(context)
            year_audits[str(year)] = {
                "cache_reused": True,
                "candidate_rows": int(len(daily)),
                "market_dates": int(context["trade_date"].nunique()),
                "minimum_market_n": int(context["market_n"].min()),
                "maximum_market_n": int(context["market_n"].max()),
                "eligible_rows": int(context["market_n"].sum()),
            }
            continue
        daily_paths = [
            str(DAILY_ROOT / f"partition_year={value}/data_0.parquet")
            for value in (year - 1, year)
        ]
        execution_paths = [
            str(EXECUTION_ROOT / f"partition_year={year}/data_0.parquet")
        ]
        raw_paths = [str(RAW_ROOT / f"{year}_day_parquet_none.parquet")]
        if year == 2026:
            raw_paths.append(str(RAW_ROOT / "2026_qmt_tail.parquet"))
        candidate_keys = identities.loc[
            identities["signal_year"].eq(year), ["symbol", "trade_date"]
        ].copy()
        candidate_keys["trade_date"] = pd.to_datetime(candidate_keys["trade_date"])
        connection = _connection()
        connection.execute("SET threads=2")
        connection.register("candidate_keys", candidate_keys)
        connection.execute(
            """
            CREATE TEMP TABLE rolled_current AS
            WITH calendar AS (
              SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 AS cal_idx
              FROM (SELECT DISTINCT trade_date FROM read_parquet($daily_paths,union_by_name=true))
            ), base AS (
              SELECT d.*,c.cal_idx,
                lag(d.close) OVER w AS previous_close,
                lag(c.cal_idx) OVER w AS previous_cal_idx,
                (d.hard_valid IS TRUE AND d.bar_valid IS TRUE
                 AND d.trading_state_valid IS TRUE AND d.industry_valid IS TRUE
                 AND d.float_valid IS TRUE AND d.corporate_action_valid IS TRUE
                 AND d.market_valid IS TRUE AND d.market_rule_valid IS TRUE
                 AND d.historical_identity_valid IS TRUE
                 AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
                 AND d.close>0 AND d.amount>0) AS history_valid
              FROM read_parquet($daily_paths,union_by_name=true) d JOIN calendar c USING(trade_date)
              WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
            ), steps AS (
              SELECT *,CASE
                WHEN history_valid AND lag(history_valid) OVER w
                 AND cal_idx-previous_cal_idx=1 AND coalesce(corporate_action_count,0)=0
                THEN ln(close/previous_close)
                WHEN history_valid AND lag(history_valid) OVER w
                 AND cal_idx-previous_cal_idx=1 AND corporate_action_count>0
                 AND corporate_action_available_date IS NOT NULL
                 AND corporate_action_available_date<=trade_date
                 AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
                 AND previous_close-coalesce(cash_per_share,0)>0
                THEN ln(close/((previous_close-coalesce(cash_per_share,0))/share_multiplier))
                ELSE NULL END AS step_log_return
              FROM base WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
            ), rolled AS (
              SELECT *,sum(step_log_return) OVER w10 AS prior_ret_10,
                count(step_log_return) OVER w10 AS count_ret_10,
                count(step_log_return) OVER w60 AS count_ret_60,
                count(amount) FILTER(WHERE history_valid) OVER w20 AS count_amount_20,
                avg(amount) FILTER(WHERE history_valid) OVER w20 AS prior_amount_mean_20
              FROM steps
              WINDOW
                w10 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
                w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
                w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
            ) SELECT * FROM rolled WHERE year(trade_date)=$target_year
            """,
            {"daily_paths": daily_paths, "target_year": year},
        )
        connection.execute(
            """
            CREATE TEMP TABLE minute_session AS
            SELECT qmt_code AS qmt_symbol,trade_date,count(*) AS minute_count,
              count(DISTINCT bar_end_time) AS distinct_minute_count,
              max(close) FILTER(WHERE hour(bar_end_time)=14 AND minute(bar_end_time)=25)
                AS cutoff_close
            FROM read_parquet($raw_paths,union_by_name=true)
            WHERE period='1m' AND adjust='none' AND exchange IN ('SH','SZ')
            GROUP BY qmt_code,trade_date
            """,
            {"raw_paths": raw_paths},
        )
        connection.execute(
            """
            CREATE TEMP TABLE eligible_current AS
            WITH execution AS (
              SELECT symbol,trade_date,available_at,hard_valid,is_st,daily_snapshot_id
              FROM read_parquet($execution_paths,union_by_name=true) WHERE window_index=0
            )
            SELECT r.trade_date,r.symbol,r.prior_ret_10,
              ln(m.cutoff_close/r.previous_close) AS return_1425
            FROM rolled_current r
            JOIN minute_session m ON m.qmt_symbol=r.symbol AND m.trade_date=r.trade_date
            JOIN execution e ON e.symbol=r.symbol AND e.trade_date=r.trade_date
            WHERE r.count_ret_10=10 AND r.count_ret_60=60 AND r.count_amount_20=20
              AND r.prior_amount_mean_20>=50000000
              AND r.hard_valid IS TRUE AND r.trade_status=1 AND r.is_st IS FALSE
              AND r.industry_valid IS TRUE AND r.source_notice_date<r.trade_date
              AND r.industry IS NOT NULL AND r.industry<>''
              AND r.previous_close>0 AND r.corporate_action_blocking IS FALSE
              AND coalesce(r.rights_ratio,0)=0
              AND m.minute_count=241 AND m.distinct_minute_count=241 AND m.cutoff_close>0
              AND e.hard_valid IS TRUE AND e.is_st IS FALSE
              AND e.available_at<=CAST(r.trade_date AS TIMESTAMP)+INTERVAL '14 hours 25 minutes'
              AND e.daily_snapshot_id=r.snapshot_id
            """,
            {"execution_paths": execution_paths},
        )
        context = connection.execute(
            """SELECT trade_date,count(*) AS market_n,
            stddev_samp(return_1425) AS market_dispersion_1425,
            avg(return_1425) AS market_return_1425,
            avg((return_1425>0)::INTEGER) AS market_breadth_1425
            FROM eligible_current GROUP BY trade_date ORDER BY trade_date"""
        ).df()
        daily = connection.execute(
            """SELECT c.symbol,c.trade_date,r.prior_ret_10
            FROM candidate_keys c LEFT JOIN rolled_current r USING(symbol,trade_date)
            ORDER BY c.trade_date,c.symbol"""
        ).df()
        eligible_audit = connection.execute(
            """SELECT count(*),count(DISTINCT symbol),count(DISTINCT trade_date)
            FROM eligible_current"""
        ).fetchone()
        connection.close()
        daily_pieces.append(daily)
        context_pieces.append(context)
        _atomic_parquet(daily, daily_cache)
        _atomic_parquet(context, context_cache)
        year_audits[str(year)] = {
            "eligible_rows": int(eligible_audit[0]),
            "eligible_symbols": int(eligible_audit[1]),
            "market_dates": int(eligible_audit[2]),
            "minimum_market_n": int(context["market_n"].min()),
            "maximum_market_n": int(context["market_n"].max()),
        }
    daily = pd.concat(daily_pieces, ignore_index=True)
    context = pd.concat(context_pieces, ignore_index=True).sort_values("trade_date")
    audits = {
        "years": year_audits,
        "eligible_rows": int(sum(item["eligible_rows"] for item in year_audits.values())),
        "market_dates": int(context["trade_date"].nunique()),
        "minimum_market_n": int(context["market_n"].min()),
        "maximum_market_n": int(context["market_n"].max()),
    }
    return daily, context, audits


def build_stage_a() -> dict[str, Any]:
    spec = load_spec()
    STAGE_A.mkdir(parents=True, exist_ok=True)
    old = _old_causal_features()
    recent_identities = _recent_identities()
    recent_raw, raw_audit = _recent_raw_features(recent_identities)
    recent_daily, context, context_audit = _recent_daily_and_market_context(recent_identities)
    recent = recent_identities.merge(
        recent_raw, on=["symbol", "trade_date"], how="left", validate="one_to_one"
    )
    recent = recent.merge(
        recent_daily, on=["symbol", "trade_date"], how="left", validate="many_to_one"
    )
    recent = recent.merge(context, on="trade_date", how="left", validate="many_to_one")
    recent["market_breadth_1425"] = recent["market_breadth_1425"]
    recent["industry_return_1425"] = np.nan
    recent["industry_breadth_1425"] = np.nan
    recent["feature_available_at"] = pd.to_datetime(recent["trade_date"]) + pd.Timedelta(
        hours=14, minutes=25
    )
    required = [
        "prior_ret_10",
        "path_efficiency_1425",
        "afternoon_amount_fraction_1425",
        "market_dispersion_1425",
    ]
    if recent[required].isna().any().any():
        missing = recent.loc[recent[required].isna().any(axis=1), ["symbol", "trade_date", *required]]
        raise V5Error(f"recent required feature fail-closed count: {len(missing)}")
    columns = list(old.columns)
    missing_columns = sorted(set(columns) - set(recent.columns))
    if missing_columns:
        raise V5Error(f"recent panel columns missing: {missing_columns}")
    combined = pd.concat([old, recent[columns]], ignore_index=True)
    combined = score_conditions(combined)
    forbidden = {"net_return", "label_net", "exit_date", "exit_reason", "holding_sessions"}
    if forbidden & set(combined.columns):
        raise V5Error("outcome column entered Stage A")
    if (pd.to_datetime(combined["feature_available_at"]) > pd.to_datetime(combined["entry_at"])).any():
        raise V5Error("feature timestamp exceeds executable entry")
    if combined["event_id"].duplicated().any() or len(combined) != 2382:
        raise V5Error("combined V4 event identity changed")
    _atomic_parquet(recent, RECENT_FEATURES)
    _atomic_parquet(context, MARKET_CONTEXT)
    _atomic_parquet(combined.sort_values(["trade_date", "symbol"]), FEATURE_PANEL)
    manifest = {
        "experiment": EXPERIMENT,
        "stage": "A",
        "spec_sha256": sha256_file(SPEC_PATH),
        "canonical_spec_sha256": _canonical_sha256(spec),
        "rows": int(len(combined)),
        "old_rows": int(len(old)),
        "recent_rows": int(len(recent)),
        "admitted_rows": int(combined["admitted"].sum()),
        "feature_available_after_entry_count": 0,
        "outcome_column_count": 0,
        "required_feature_missing_count": 0,
        "raw_audit": raw_audit,
        "context_audit": context_audit,
        "hashes": {
            "causal_feature_panel": sha256_file(FEATURE_PANEL),
            "recent_features": sha256_file(RECENT_FEATURES),
            "market_context": sha256_file(MARKET_CONTEXT),
        },
    }
    _atomic_json(manifest, STAGE_A_MANIFEST)
    return manifest


def _summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "trades": 0,
            "mean_net": None,
            "median_net": None,
            "date_equal_mean_net": None,
            "win_rate": None,
            "severe10": None,
            "target_hit": None,
            "mean_holding_sessions": None,
        }
    return {
        "trades": int(len(frame)),
        "dates": int(frame["trade_date"].nunique()),
        "symbols": int(frame["symbol"].nunique()),
        "mean_net": float(frame["net_return"].mean()),
        "median_net": float(frame["net_return"].median()),
        "date_equal_mean_net": float(frame.groupby("trade_date")["net_return"].mean().mean()),
        "win_rate": float((frame["net_return"] > 0).mean()),
        "severe10": float((frame["net_return"] <= -0.10).mean()),
        "target_hit": float(frame["exit_reason"].eq("TARGET_15").mean()),
        "mean_holding_sessions": float(frame["holding_sessions"].mean()),
    }


def evaluate_stage_b() -> dict[str, Any]:
    load_spec()
    if not STAGE_A_MANIFEST.is_file() or not FEATURE_PANEL.is_file():
        raise V5Error("Stage A freeze is missing")
    manifest = json.loads(STAGE_A_MANIFEST.read_text(encoding="utf-8"))
    if manifest["hashes"]["causal_feature_panel"] != sha256_file(FEATURE_PANEL):
        raise V5Error("Stage A feature identity changed")
    connection = _connection()
    outcomes = connection.execute(
        """WITH source AS (
          SELECT event_id,exit_date,exit_coord,exit_reason,holding_sessions,status,
            action_lineage_fail_closed,net_return FROM read_parquet(?)
          UNION ALL BY NAME
          SELECT event_id,exit_date,exit_coord,exit_reason,holding_sessions,status,
            action_lineage_fail_closed,net_return FROM read_parquet(?)
          UNION ALL BY NAME
          SELECT event_id,exit_date,exit_coord,exit_reason,holding_sessions,status,
            action_lineage_fail_closed,net_return FROM read_parquet(?)
        ) SELECT * FROM source""",
        [str(V4_DEV), str(V4_CHALLENGE), str(V4_RECENT)],
    ).df()
    connection.close()
    features = pq.read_table(FEATURE_PANEL).to_pandas()
    joined = features.merge(outcomes, on="event_id", how="left", validate="one_to_one")
    complete = joined.loc[
        joined["status"].eq("COMPLETE") & ~joined["action_lineage_fail_closed"].fillna(True)
    ].copy()
    selected = complete.loc[complete["admitted"]].copy()
    _atomic_parquet(selected.sort_values(["trade_date", "symbol"]), SELECTED_TRADES)
    annual = {
        str(int(year)): _summary(group)
        for year, group in selected.groupby("signal_year", sort=True)
    }
    baseline_annual = {
        str(int(year)): _summary(group)
        for year, group in complete.groupby("signal_year", sort=True)
    }
    blocks = {
        "development_2014_2020": _summary(selected.loc[selected["signal_year"] <= 2020]),
        "challenge_2021_2023": _summary(
            selected.loc[selected["signal_year"].between(2021, 2023)]
        ),
        "post_observation_2024_2026_ytd": _summary(selected.loc[selected["signal_year"] >= 2024]),
        "full_2014_2025": _summary(selected.loc[selected["signal_year"] <= 2025]),
        "all_complete_2014_2026_ytd": _summary(selected),
    }
    by_score = {
        str(int(score)): _summary(group)
        for score, group in complete.groupby("scorecard_count", sort=True)
    }
    by_route = {
        str(route): _summary(group) for route, group in selected.groupby("route", sort=True)
    }
    by_sleeve = {
        str(sleeve): _summary(group) for sleeve, group in selected.groupby("sleeve", sort=True)
    }
    exit_reasons = {
        str(reason): _summary(group)
        for reason, group in selected.groupby("exit_reason", sort=True)
    }
    full_years = selected.loc[selected["signal_year"] <= 2025]
    full_year_count = int(full_years["signal_year"].nunique())
    full_summary = blocks["full_2014_2025"]
    goal = {
        "average_completed_signals_per_full_year": float(len(full_years) / full_year_count),
        "average_completed_signals_per_full_year_gt50": bool(len(full_years) / full_year_count > 50),
        "pooled_mean_net_gt2": bool(full_summary["mean_net"] > 0.02),
        "pooled_median_net_gt0": bool(full_summary["median_net"] > 0),
        "date_equal_mean_net_gt0": bool(full_summary["date_equal_mean_net"] > 0),
        "severe10_lt10": bool(full_summary["severe10"] < 0.10),
        "every_full_year_mean_positive": bool(
            all(annual[str(year)]["mean_net"] > 0 for year in range(2014, 2026))
        ),
    }
    goal["all_required_pass"] = bool(all(value for key, value in goal.items() if key != "average_completed_signals_per_full_year"))
    result = {
        "experiment": EXPERIMENT,
        "spec_sha256": sha256_file(SPEC_PATH),
        "stage_a_feature_sha256": sha256_file(FEATURE_PANEL),
        "selected_trades_sha256": sha256_file(SELECTED_TRADES),
        "parent_rule_changed": False,
        "scorecard_changed_after_recent_feature_open": False,
        "model_fit_run": False,
        "annual": annual,
        "baseline_annual": baseline_annual,
        "blocks": blocks,
        "by_score": by_score,
        "by_route": by_route,
        "by_sleeve": by_sleeve,
        "exit_reasons": exit_reasons,
        "goal": goal,
        "audit": {
            "feature_available_after_entry_count": int(
                (pd.to_datetime(joined["feature_available_at"]) > pd.to_datetime(joined["entry_at"])).sum()
            ),
            "missing_required_feature_count": int(
                joined[
                    [
                        "prior_ret_10",
                        "path_efficiency_1425",
                        "afternoon_amount_fraction_1425",
                        "market_dispersion_1425",
                    ]
                ]
                .isna()
                .any(axis=1)
                .sum()
            ),
            "duplicate_event_count": int(joined["event_id"].duplicated().sum()),
            "post_2026_08_12_signal_count": int(
                (pd.to_datetime(joined["trade_date"]) > pd.Timestamp("2026-08-12")).sum()
            ),
            "right_censored_count": int(joined["status"].ne("COMPLETE").sum()),
            "parent_identity_rows": int(len(joined)),
            "complete_rows": int(len(complete)),
            "selected_complete_rows": int(len(selected)),
        },
        "scientific_warning": "2024-2026 V4 calendar outcomes had already been viewed before this feature relationship test; results are post-observation robustness diagnostics, not pristine external OOS.",
    }
    if any(result["audit"][key] for key in [
        "feature_available_after_entry_count",
        "missing_required_feature_count",
        "duplicate_event_count",
        "post_2026_08_12_signal_count",
    ]):
        raise V5Error(f"Stage B audit failed: {result['audit']}")
    _atomic_json(result, EXTERNAL_RESULT)
    _atomic_json(result, RESULT_PATH)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for year in sorted(annual, key=int):
        item = annual[year]
        rows.append(
            f"|{year}|{item['trades']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|"
            f"{item['win_rate']:.2%}|{item['severe10']:.2%}|"
        )
    report = f"""# {EXPERIMENT}

## Economic signal

Fresh price discovery following an industry-confirmed morning demand impulse.  The
fixed scorecard requires any two of: non-positive prior ten-session return,
directionally efficient 09:31--14:25 path, at least 30% afternoon participation,
and at least 3% same-clock market return dispersion.

## Frozen-scorecard results

|Year|Trades|Mean net|Median net|Win|Severe10|
|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

Development 2014--2020: {blocks['development_2014_2020']['trades']} trades,
{blocks['development_2014_2020']['mean_net']:.2%} mean and
{blocks['development_2014_2020']['median_net']:.2%} median.

Previously observed challenge 2021--2023: {blocks['challenge_2021_2023']['trades']}
trades, {blocks['challenge_2021_2023']['mean_net']:.2%} mean and
{blocks['challenge_2021_2023']['median_net']:.2%} median.

Post-observation 2024--2026 YTD diagnostic:
{blocks['post_observation_2024_2026_ytd']['trades']} trades,
{blocks['post_observation_2024_2026_ytd']['mean_net']:.2%} mean and
{blocks['post_observation_2024_2026_ytd']['median_net']:.2%} median.

## Goal gate

`{json.dumps(goal, ensure_ascii=False, sort_keys=True)}`

No model was fit.  The parent signal, entry, target, failure exit, H20 stop, and
40 bp cost were not changed.  The 2024--2026 result is not pristine OOS because
the parent V4 calendar outcomes had already been viewed.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["a", "b", "all"], default="all")
    args = parser.parse_args()
    if args.stage in {"a", "all"}:
        print(json.dumps(build_stage_a(), indent=2, sort_keys=True))
    if args.stage in {"b", "all"}:
        print(json.dumps(evaluate_stage_b(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
