#!/usr/bin/env python3
# ruff: noqa: E501
"""Build and evaluate frozen Stage B for A-share Tail-to-Open LightGBM V1."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
import os
import resource
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import psutil
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_stage_a_spec.json"
FEATURE_PATH = PROGRAM / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_feature_manifest.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_stage_b_result.json"
BUILD_AUDIT_PATH = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_build_only_audit.json"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_stage_b_summary.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-TAIL-OPEN-LGBM-V1_stage_b_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1")
RAW_ROOT = EXTERNAL_ROOT / "raw_features"
EXTENDED_DAILY_ROOT = EXTERNAL_ROOT / "pit_daily_2013_2023_cy006" / "daily"
EXTENDED_EXECUTION_ROOT = EXTERNAL_ROOT / "pit_execution_2013_2017_cy006"
DAILY_CONTRACT = EXTERNAL_ROOT / "daily_contract_2013_2023.parquet"
RAW_ENRICHED = EXTERNAL_ROOT / "raw_features_2013_2023.parquet"
PANEL_PATH = EXTERNAL_ROOT / "model_panel_2013_2023.parquet"
PREDICTION_PATH = EXTERNAL_ROOT / "stage_b_predictions.parquet"
MODEL_ROOT = EXTERNAL_ROOT / "models"
TEMP_ROOT = EXTERNAL_ROOT / "tmp"

EXPECTED_STAGE_A_COMMIT = "28726ddc82"
EXPECTED_SPEC_SHA256 = "fa551965e2d3a51d55b5c8543da2f7bb9babfd1cbefe4002b5c207785759ad67"
EXPECTED_FEATURE_SHA256 = "a1d33981620289dd9090210cca281500ea09584abd797cdc556a515b8f78858e"
YEARS = tuple(range(2013, 2024))
COST = 0.002
SEED = 20260901
RAM_FLOOR_BYTES = 8 * (1 << 30)
RSS_CEILING_BYTES = 8 * (1 << 30)


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CORE = _load_module(
    "tail_open_lgbm_core", Path(__file__).with_name("ashare_tail_open_lgbm_v1_core.py")
)
ADAPTER = _load_module(
    "tail_open_minute_adapter", Path(__file__).with_name("vectorized_market_minute_adapter.py")
)


class StageBError(RuntimeError):
    """Fail-closed Stage-B error."""


def _normalized_trade_dates(table: pa.Table) -> set[date]:
    return {
        pd.Timestamp(value).date() for value in table["trade_date"].to_pylist() if value is not None
    }


def _all_null_columns(
    connection: duckdb.DuckDBPyConnection, path: Path, columns: list[str]
) -> list[str]:
    expressions = ",".join(f'count("{column}")' for column in columns)
    counts = connection.execute(
        f"SELECT {expressions} FROM read_parquet(?)", [str(path)]
    ).fetchone()
    return [column for column, count in zip(columns, counts, strict=True) if count == 0]


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


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _resource_gate() -> None:
    available = psutil.virtual_memory().available
    if available < RAM_FLOOR_BYTES:
        raise StageBError(f"system RAM below 8-GiB floor: {available}")
    rss = _max_rss_bytes()
    if rss > RSS_CEILING_BYTES:
        raise StageBError(f"process RSS above 8-GiB ceiling: {rss}")


def _load_contracts() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise StageBError("Stage-A spec hash changed")
    if sha256_file(FEATURE_PATH) != EXPECTED_FEATURE_SHA256:
        raise StageBError("feature manifest hash changed")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    feature_manifest = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    if spec["final_oos_governance"]["status"] != "LOCKED_UNREAD":
        raise StageBError("final OOS is not locked")
    features = [item["name"] for item in feature_manifest["features"]]
    if len(features) != 59 or len(set(features)) != 59:
        raise StageBError("feature dictionary changed")
    for record in spec["input_contracts"].values():
        raw_path = record.get("path", record.get("manifest"))
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise StageBError(f"contract identity changed: {path}")
    return spec, feature_manifest, features


def _inventory_paths(
    spec: dict[str, Any],
) -> tuple[dict[str, Path], dict[str, Path], dict[str, Path]]:
    raw_inventory = Path(spec["input_contracts"]["QD-004-2013-2023"]["manifest"])
    daily_inventory = Path(spec["input_contracts"]["CY-006"]["manifest"])
    minute_inventory = Path(spec["input_contracts"]["CY-008"]["manifest"])
    raw_required = [f"bars/{year}_day_parquet_none.parquet" for year in YEARS]
    registered_daily = ADAPTER.inventory_files(
        daily_inventory,
        [f"partition_year={year}/data_0.parquet" for year in range(2018, 2024)],
    )
    daily_paths = {
        f"partition_year={year}/data_0.parquet": (
            EXTENDED_DAILY_ROOT / f"partition_year={year}" / "data_0.parquet"
            if year < 2018
            else registered_daily[f"partition_year={year}/data_0.parquet"]
        )
        for year in YEARS
    }
    registered_execution = ADAPTER.inventory_files(
        minute_inventory,
        [f"execution_5m/partition_year={year}/data_0.parquet" for year in range(2018, 2024)],
    )
    minute_paths = {
        f"execution_5m/partition_year={year}/data_0.parquet": (
            EXTENDED_EXECUTION_ROOT / "execution_5m" / f"partition_year={year}" / "data_0.parquet"
            if year < 2018
            else registered_execution[f"execution_5m/partition_year={year}/data_0.parquet"]
        )
        for year in YEARS
    }
    if not all(path.is_file() for path in [*daily_paths.values(), *minute_paths.values()]):
        raise StageBError("extended daily/minute contract is incomplete")
    return (
        ADAPTER.inventory_files(raw_inventory, raw_required),
        daily_paths,
        minute_paths,
    )


def verify_source_content(spec: dict[str, Any]) -> dict[str, str]:
    raw_inventory = Path(spec["input_contracts"]["QD-004-2013-2023"]["manifest"])
    minute_inventory = Path(spec["input_contracts"]["CY-008"]["manifest"])
    raw_required = [f"bars/{year}_day_parquet_none.parquet" for year in YEARS]
    ADAPTER.verify_inventory_hashes(raw_inventory, raw_required)
    ADAPTER.verify_inventory_hashes(
        minute_inventory,
        [f"execution_5m/partition_year={year}/data_0.parquet" for year in range(2018, 2024)],
    )
    extension_record = spec["input_contracts"]["chronology_extension_audit"]
    extension_path = Path(extension_record["path"])
    if not extension_path.is_absolute():
        extension_path = ROOT / extension_path
    extension = json.loads(extension_path.read_text(encoding="utf-8"))
    for item in extension["pre_2018_generated_contract_hashes"]:
        year = int(item["year"])
        daily_path = EXTENDED_DAILY_ROOT / f"partition_year={year}" / "data_0.parquet"
        execution_path = (
            EXTENDED_EXECUTION_ROOT
            / "execution_5m"
            / f"partition_year={year}"
            / "data_0.parquet"
        )
        if sha256_file(daily_path) != item["daily_sha256"]:
            raise StageBError(f"extended daily content changed: {year}")
        if sha256_file(execution_path) != item["execution_sha256"]:
            raise StageBError(f"extended execution content changed: {year}")
    return {
        "QD-004": sha256_file(raw_inventory),
        "extended_daily_audit": sha256_file(EXTENDED_DAILY_ROOT.parent / "audit.json"),
        "chronology_extension_audit": sha256_file(extension_path),
        "CY-008": sha256_file(minute_inventory),
    }


def verify_frozen_materializations(spec: dict[str, Any]) -> dict[str, str]:
    record = spec["input_contracts"]["chronology_extension_audit"]
    audit_path = Path(record["path"])
    if not audit_path.is_absolute():
        audit_path = ROOT / audit_path
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    expected = {
        "daily_contract": DAILY_CONTRACT,
        "same_clock_raw_features": RAW_ENRICHED,
        "model_panel": PANEL_PATH,
    }
    verified: dict[str, str] = {}
    for name, path in expected.items():
        observed = sha256_file(path)
        if observed != audit["artifacts"][name]["sha256"]:
            raise StageBError(f"frozen materialization changed: {name}")
        verified[name] = observed
    return verified


def _calendar(daily_path: Path, year: int) -> list[pd.Timestamp]:
    frame = pq.read_table(daily_path, columns=["trade_date"], use_threads=False).to_pandas()
    dates = sorted(pd.to_datetime(frame.trade_date, errors="raise").drop_duplicates())
    expected = {
        2013: 238,
        2014: 245,
        2015: 244,
        2016: 244,
        2017: 244,
        2018: 243,
        2019: 244,
        2020: 243,
        2021: 243,
        2022: 242,
        2023: 242,
    }
    if len(dates) != expected[year]:
        raise StageBError(f"calendar changed for {year}: {len(dates)}")
    return dates


def build_raw_feature_shards(
    raw_paths: dict[str, Path], daily_paths: dict[str, Path]
) -> dict[str, Any]:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    yearly: list[dict[str, Any]] = []
    for year in YEARS:
        _resource_gate()
        relative = f"bars/{year}_day_parquet_none.parquet"
        daily_relative = f"partition_year={year}/data_0.parquet"
        output = RAW_ROOT / f"year={year}.parquet"
        stale_temporary = next(RAW_ROOT.glob(f".{output.name}.*.tmp"), None)
        if stale_temporary is not None:
            stale_temporary.unlink()
        date_root = RAW_ROOT / f"year={year}_dates"
        date_root.mkdir(parents=True, exist_ok=True)
        valid_sessions = 0
        started = time.perf_counter()
        calendar = _calendar(daily_paths[daily_relative], year)
        for index, trade_date in enumerate(calendar):
            _resource_gate()
            date_output = date_root / f"date={trade_date.date().isoformat()}.parquet"
            if date_output.is_file():
                existing = pq.read_table(
                    date_output,
                    columns=["trade_date"],
                    use_threads=False,
                )
                observed_dates = _normalized_trade_dates(existing)
                if observed_dates != {trade_date.date()}:
                    raise StageBError(f"resumable date shard identity changed: {date_output}")
                valid_sessions += existing.num_rows
            else:
                raw = ADAPTER.read_raw_table(raw_paths[relative], [trade_date.date()])
                frame, audit = CORE.extract_raw_day(raw)
                table = pa.Table.from_pandas(frame, preserve_index=False)
                temporary = date_output.with_name(f".{date_output.name}.{os.getpid()}.tmp")
                pq.write_table(
                    table,
                    temporary,
                    compression="zstd",
                    use_dictionary=["symbol"],
                    row_group_size=len(table),
                )
                os.replace(temporary, date_output)
                valid_sessions += audit["valid_sessions"]
                del raw, frame, table
                gc.collect()
                pa.default_memory_pool().release_unused()
            if index % 25 == 0:
                print(
                    json.dumps(
                        {
                            "stage": "raw_features",
                            "year": year,
                            "date": trade_date.date().isoformat(),
                            "dates_complete": index + 1,
                            "valid_sessions": valid_sessions,
                            "rss_bytes": _max_rss_bytes(),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
        date_paths = sorted(date_root.glob("date=*.parquet"))
        if len(date_paths) != len(calendar):
            raise StageBError(f"resumable date shard coverage changed: {year}")
        connection = _duckdb()
        output_temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        quoted_temporary = output_temporary.as_posix().replace("'", "''")
        connection.execute(
            f"COPY (SELECT * FROM read_parquet($paths,union_by_name=true) "
            f"ORDER BY trade_date,symbol) TO '{quoted_temporary}' "
            "(FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)",
            {"paths": [str(path) for path in date_paths]},
        )
        connection.close()
        os.replace(output_temporary, output)
        yearly.append(
            {
                "year": year,
                "valid_sessions": valid_sessions,
                "wall_seconds": time.perf_counter() - started,
                "path": str(output),
                "sha256": sha256_file(output),
            }
        )
    return {"years": yearly, "total_valid_sessions": sum(item["valid_sessions"] for item in yearly)}


def _duckdb() -> duckdb.DuckDBPyConnection:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='6GB'")
    connection.execute(f"SET temp_directory='{TEMP_ROOT.as_posix()}'")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def build_daily_contract(daily_paths: dict[str, Path]) -> dict[str, Any]:
    paths = [str(daily_paths[f"partition_year={year}/data_0.parquet"]) for year in YEARS]
    connection = _duckdb()
    quoted_output = DAILY_CONTRACT.as_posix().replace("'", "''")
    query = """
    WITH daily AS (
      SELECT * FROM read_parquet($paths,union_by_name=true)
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-29'
    ), calendar AS (
      SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
      FROM (SELECT DISTINCT trade_date FROM daily)
    ), base AS (
      SELECT d.*,c.cal_idx,
        (d.hard_valid IS TRUE AND d.bar_valid IS TRUE
         AND d.trading_state_valid IS TRUE AND d.industry_valid IS TRUE
         AND d.float_valid IS TRUE AND d.corporate_action_valid IS TRUE
         AND d.market_valid IS TRUE AND d.market_rule_valid IS TRUE
         AND d.historical_identity_valid IS TRUE
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.open>0 AND d.high>=greatest(d.open,d.close)
         AND d.low<=least(d.open,d.close) AND d.close>0 AND d.amount>0) history_valid,
        lag(d.close) OVER w AS previous_close,
        lag(c.cal_idx) OVER w AS previous_cal_idx
      FROM daily d JOIN calendar c USING(trade_date)
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
        ELSE NULL END AS step_log_return,
        sum(coalesce(corporate_action_count,0)) OVER w AS cumulative_action_count,
        sum(CASE WHEN coalesce(corporate_action_count,0)>0
          AND corporate_action_valid IS TRUE AND corporate_action_blocking IS FALSE
          AND corporate_action_available_date IS NOT NULL
          AND corporate_action_available_date<=trade_date
          AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)=1
          AND coalesce(cash_per_share,0)>=0
          THEN coalesce(cash_per_share,0) ELSE 0 END) OVER w AS cumulative_action_cash,
        sum(CASE WHEN coalesce(corporate_action_count,0)>0 AND NOT (
          corporate_action_valid IS TRUE AND corporate_action_blocking IS FALSE
          AND corporate_action_available_date IS NOT NULL
          AND corporate_action_available_date<=trade_date
          AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)=1
          AND coalesce(cash_per_share,0)>=0)
          THEN corporate_action_count ELSE 0 END) OVER w AS cumulative_unsupported_action_count,
        (hard_valid IS TRUE AND trade_status=1
         AND current_day_data_tradable IS TRUE AND sell_blocked_open IS FALSE
         AND corporate_action_blocking IS FALSE AND open>0) legal_sell_open
      FROM base WINDOW w AS (
        PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      )
    ), rolled AS (
      SELECT *,
        lag(step_log_return,1) OVER w AS prior_ret_1,
        sum(step_log_return) OVER w5 AS prior_ret_5,
        sum(step_log_return) OVER w10 AS prior_ret_10,
        sum(step_log_return) OVER w20 AS prior_ret_20,
        sum(step_log_return) OVER w60 AS prior_ret_60,
        stddev_samp(step_log_return) OVER w5 AS prior_vol_5,
        stddev_samp(step_log_return) OVER w20 AS prior_vol_20,
        stddev_samp(step_log_return) OVER w60 AS prior_vol_60,
        sqrt(avg(CASE WHEN step_log_return<0 THEN step_log_return*step_log_return ELSE 0 END) OVER w20) AS prior_downside_vol_20,
        max(step_log_return) OVER w20 AS prior_max_ret_20,
        min(step_log_return) OVER w20 AS prior_min_ret_20,
        skewness(step_log_return) OVER w20 AS prior_skew_20,
        ln(avg(amount) FILTER (WHERE history_valid) OVER w20) AS prior_log_amount_mean_20,
        avg(amount) FILTER (WHERE history_valid) OVER w5
          /avg(amount) FILTER (WHERE history_valid) OVER w20-1 AS prior_amount_ratio_5_20,
        avg(turnover_fraction) FILTER (WHERE history_valid) OVER w20 AS prior_turnover_mean_20,
        count(step_log_return) OVER w5 AS count_ret_5,
        count(step_log_return) OVER w10 AS count_ret_10,
        count(step_log_return) OVER w20 AS count_ret_20,
        count(step_log_return) OVER w60 AS count_ret_60,
        count(amount) FILTER (WHERE history_valid) OVER w20 AS count_amount_20,
        avg(amount) FILTER (WHERE history_valid) OVER w20 AS prior_amount_mean_20,
        min(CASE WHEN legal_sell_open THEN cal_idx END) OVER (
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
        ) AS next_legal_cal_idx
      FROM steps
      WINDOW
        w AS (PARTITION BY symbol ORDER BY trade_date),
        w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        w10 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
        w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
    )
    SELECT r.trade_date,r.symbol,r.cal_idx,r.previous_close,r.industry,
      r.source_notice_date,r.industry_valid,r.snapshot_id,r.corporate_action_blocking,
      r.corporate_action_count,r.rights_ratio,r.share_multiplier,r.cash_per_share,
      r.open,r.low,r.trade_status,r.current_day_data_tradable,r.sell_blocked_open,r.hard_valid,
      r.prior_ret_1,r.prior_ret_5,r.prior_ret_10,r.prior_ret_20,r.prior_ret_60,
      r.prior_vol_5,r.prior_vol_20,r.prior_vol_60,r.prior_downside_vol_20,
      r.prior_max_ret_20,r.prior_min_ret_20,r.prior_skew_20,
      r.prior_log_amount_mean_20,r.prior_amount_ratio_5_20,r.prior_turnover_mean_20,
      r.count_ret_5,r.count_ret_10,r.count_ret_20,r.count_ret_60,r.count_amount_20,
      r.prior_amount_mean_20,r.next_legal_cal_idx,
      x.trade_date AS exit_date,x.open AS exit_open,x.cal_idx AS exit_cal_idx,
      x.cumulative_action_count-r.cumulative_action_count AS holding_action_count,
      x.cumulative_action_cash-r.cumulative_action_cash AS holding_action_cash,
      x.cumulative_unsupported_action_count-r.cumulative_unsupported_action_count
        AS holding_unsupported_action_count
    FROM rolled r LEFT JOIN steps x
      ON x.symbol=r.symbol AND x.cal_idx=r.next_legal_cal_idx
    ORDER BY r.trade_date,r.symbol
    """
    connection.execute(
        f"COPY ({query}) TO '{quoted_output}' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)",
        {"paths": paths},
    )
    audit = connection.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((year(exit_date)>=2024)::INTEGER) FROM read_parquet(?)""",
        [str(DAILY_CONTRACT)],
    ).fetchone()
    connection.close()
    if int(audit[4]) != 0:
        raise StageBError("post-2023 security exit entered daily contract")
    return {
        "rows": int(audit[0]),
        "symbols": int(audit[1]),
        "first": str(audit[2]),
        "last": str(audit[3]),
        "sha256": sha256_file(DAILY_CONTRACT),
    }


def enrich_raw_history() -> dict[str, Any]:
    paths = [str(RAW_ROOT / f"year={year}.parquet") for year in YEARS]
    if not all(Path(path).is_file() for path in paths):
        raise StageBError("raw feature shards are incomplete")
    connection = _duckdb()
    quoted_output = RAW_ENRICHED.as_posix().replace("'", "''")
    query = """
    SELECT *,
      amount_1425/avg(amount_1425) OVER (
        PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      )-1 AS amount_surprise_1425,
      count(amount_1425) OVER (
        PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS amount_history_count_20
    FROM read_parquet($paths,union_by_name=true)
    ORDER BY trade_date,symbol
    """
    connection.execute(
        f"COPY ({query}) TO '{quoted_output}' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)",
        {"paths": paths},
    )
    audit = connection.execute(
        "SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date) FROM read_parquet(?)",
        [str(RAW_ENRICHED)],
    ).fetchone()
    connection.close()
    return {
        "rows": int(audit[0]),
        "symbols": int(audit[1]),
        "first": str(audit[2]),
        "last": str(audit[3]),
        "sha256": sha256_file(RAW_ENRICHED),
    }


def build_model_panel(minute_paths: dict[str, Path], features: list[str]) -> dict[str, Any]:
    execution_paths = [
        str(minute_paths[f"execution_5m/partition_year={year}/data_0.parquet"]) for year in YEARS
    ]
    connection = _duckdb()
    quoted_output = PANEL_PATH.as_posix().replace("'", "''")
    query = """
    WITH execution AS (
      SELECT symbol,trade_date,available_at,trade_status,is_st,up_limit_price,
        down_limit_price,market_rule_id,hard_valid,snapshot_id,daily_snapshot_id
      FROM read_parquet($execution_paths,union_by_name=true) WHERE window_index=0
    ), joined AS (
      SELECT r.* EXCLUDE(ret_prevclose_to_1425),d.* EXCLUDE(symbol,trade_date),
        e.available_at AS state_available_at,e.trade_status AS state_trade_status,
        e.is_st AS state_is_st,e.up_limit_price,e.down_limit_price,e.market_rule_id,
        e.hard_valid AS state_hard_valid,e.snapshot_id AS state_snapshot_id,
        e.daily_snapshot_id AS state_daily_snapshot_id,
        ln(r.raw_open/d.previous_close) AS open_gap,
        ln(r.cutoff_close/d.previous_close) AS ret_prevclose_to_1425,
        (r.trade_date>=DATE '2014-01-01'
         AND d.count_ret_5=5 AND d.count_ret_10=10 AND d.count_ret_20=20
         AND d.count_ret_60=60 AND d.count_amount_20=20
         AND r.amount_history_count_20=20 AND d.prior_amount_mean_20>=50000000
         AND e.hard_valid IS TRUE AND e.available_at<=CAST(r.trade_date AS TIMESTAMP)+INTERVAL '14 hours 25 minutes'
         AND e.daily_snapshot_id=d.snapshot_id
         AND e.trade_status=1 AND e.is_st IS FALSE
         AND d.industry_valid IS TRUE AND d.source_notice_date<r.trade_date
         AND d.industry IS NOT NULL AND d.industry<>''
         AND d.previous_close>0 AND d.corporate_action_blocking IS FALSE
         AND coalesce(d.rights_ratio,0)=0) AS signal_eligible,
        (r.entry_volume>0 AND r.entry_amount>0 AND r.entry_vwap>0
         AND round(r.entry_low*100)<=round(e.up_limit_price*100)-1) AS entry_executable
      FROM read_parquet($raw_path) r
      JOIN read_parquet($daily_path) d USING(symbol,trade_date)
      JOIN execution e USING(symbol,trade_date)
    ), stats AS (
      SELECT *,
        count(*) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date) AS market_n,
        sum(ret_prevclose_to_1425) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date) AS market_sum,
        sum(ret_prevclose_to_1425*ret_prevclose_to_1425) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date) AS market_sumsq,
        sum((ret_prevclose_to_1425>0)::INTEGER) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date) AS market_up,
        median(amount_surprise_1425) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date) AS market_activity_surprise_1425,
        count(*) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date,industry) AS industry_n,
        sum(ret_prevclose_to_1425) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date,industry) AS industry_sum,
        sum(ret_prevclose_to_1425*ret_prevclose_to_1425) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date,industry) AS industry_sumsq,
        sum((ret_prevclose_to_1425>0)::INTEGER) FILTER (WHERE signal_eligible) OVER (PARTITION BY trade_date,industry) AS industry_up,
        rank() OVER (PARTITION BY trade_date ORDER BY CASE WHEN signal_eligible THEN ret_prevclose_to_1425 END NULLS LAST) AS return_rank,
        rank() OVER (PARTITION BY trade_date ORDER BY CASE WHEN signal_eligible THEN cutoff_vs_vwap_1425 END NULLS LAST) AS vwap_rank
      FROM joined
    ), contextual AS (
      SELECT *,
        market_sum/market_n AS market_return_1425,
        market_up::DOUBLE/market_n AS market_breadth_1425,
        sqrt(greatest((market_sumsq-market_sum*market_sum/market_n)/(market_n-1),0)) AS market_dispersion_1425,
        (industry_sum-ret_prevclose_to_1425)/(industry_n-1) AS industry_return_1425,
        (industry_up-(ret_prevclose_to_1425>0)::INTEGER)::DOUBLE/(industry_n-1) AS industry_breadth_1425,
        sqrt(greatest(((industry_sumsq-ret_prevclose_to_1425*ret_prevclose_to_1425)
          -(industry_sum-ret_prevclose_to_1425)*(industry_sum-ret_prevclose_to_1425)/(industry_n-1))/(industry_n-2),0)) AS industry_dispersion_1425,
        ret_prevclose_to_1425-market_sum/market_n AS residual_vs_market_1425,
        ret_prevclose_to_1425-(industry_sum-ret_prevclose_to_1425)/(industry_n-1) AS residual_vs_industry_1425,
        (return_rank-1)::DOUBLE/(market_n-1) AS rank_return_1425,
        (vwap_rank-1)::DOUBLE/(market_n-1) AS rank_vwap_position_1425,
        CASE WHEN entry_executable AND exit_date IS NOT NULL
          AND holding_unsupported_action_count=0
          THEN (exit_open*(1-0.002)+holding_action_cash)/(entry_vwap*(1+0.002))-1
          ELSE NULL END AS label_net,
        CASE WHEN entry_executable AND exit_date IS NOT NULL
          AND holding_unsupported_action_count=0
          THEN (exit_open+holding_action_cash)/entry_vwap-1 ELSE NULL END AS label_gross,
        (entry_executable AND exit_date IS NOT NULL
          AND holding_unsupported_action_count=0) AS label_valid
      FROM stats WHERE market_n>=100 AND industry_n>=3
    ) SELECT * FROM contextual ORDER BY trade_date,symbol
    """
    connection.execute(
        f"COPY ({query}) TO '{quoted_output}' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)",
        {
            "execution_paths": execution_paths,
            "raw_path": str(RAW_ENRICHED),
            "daily_path": str(DAILY_CONTRACT),
        },
    )
    available = {
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(PANEL_PATH)]
        ).fetchall()
    }
    missing = sorted(set(features) - available)
    if missing:
        raise StageBError(f"model panel missing features: {missing}")
    all_null = _all_null_columns(connection, PANEL_PATH, features)
    if all_null:
        raise StageBError(f"model panel has all-null features: {all_null}")
    audit = connection.execute(
        """SELECT count(*),sum(signal_eligible::INTEGER),sum(label_valid::INTEGER),
        count(DISTINCT symbol),count(DISTINCT trade_date),min(trade_date),max(trade_date),
        sum((year(trade_date)>=2024)::INTEGER) FROM read_parquet(?)""",
        [str(PANEL_PATH)],
    ).fetchone()
    connection.close()
    if int(audit[7]) != 0:
        raise StageBError("post-2023 security row entered model panel")
    return {
        "rows": int(audit[0]),
        "signal_eligible_rows": int(audit[1]),
        "label_valid_rows": int(audit[2]),
        "symbols": int(audit[3]),
        "dates": int(audit[4]),
        "first": str(audit[5]),
        "last": str(audit[6]),
        "sha256": sha256_file(PANEL_PATH),
    }


def _daily_ic(frame: pd.DataFrame, score: str) -> pd.Series:
    def correlation(group: pd.DataFrame) -> float:
        valid = group[[score, "label_net"]].dropna()
        if len(valid) < 20 or valid[score].nunique() < 2 or valid.label_net.nunique() < 2:
            return np.nan
        return float(spearmanr(valid[score], valid.label_net).statistic)

    return frame.groupby("trade_date", sort=True).apply(correlation, include_groups=False).dropna()


def _top10_daily(frame: pd.DataFrame, score: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for trade_date, group in frame.groupby("trade_date", sort=True):
        ranked = (
            group.loc[group[score].notna()]
            .sort_values([score, "symbol"], ascending=[False, True])
            .head(10)
        )
        returns = np.where(ranked.label_valid, ranked.label_net.fillna(0.0), 0.0)
        rows.append(
            {
                "trade_date": trade_date,
                "planned": len(ranked),
                "executed": int(ranked.label_valid.sum()),
                "net_return": float(np.sum(returns) / 10),
                "gross_return": float(
                    np.sum(np.where(ranked.label_valid, ranked.label_gross.fillna(0.0), 0.0)) / 10
                ),
            }
        )
    return pd.DataFrame(rows)


def _metrics(frame: pd.DataFrame, score: str, label: str) -> dict[str, Any]:
    ic = _daily_ic(frame.loc[frame.label_valid], score)
    top = _top10_daily(frame, score)
    annual_ic = {str(year): float(values.mean()) for year, values in ic.groupby(ic.index.year)}
    annual_net = {
        str(year): float(values.net_return.mean())
        for year, values in top.groupby(pd.to_datetime(top.trade_date).dt.year)
    }
    return {
        "model": label,
        "decision_dates": int(frame.trade_date.nunique()),
        "label_rows": int(frame.label_valid.sum()),
        "mean_daily_rank_ic": float(ic.mean()),
        "median_daily_rank_ic": float(ic.median()),
        "annual_rank_ic": annual_ic,
        "top10_mean_net_return": float(top.net_return.mean()),
        "top10_mean_gross_return": float(top.gross_return.mean()),
        "top10_entry_execution_fraction": float(top.executed.sum() / top.planned.sum()),
        "annual_top10_net_return": annual_net,
    }


def _inner_split(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(pd.to_datetime(train.trade_date).drop_duplicates())
    if len(dates) <= 252:
        raise StageBError("insufficient dates for inner early stopping")
    inner_start = pd.Timestamp(dates[-126])
    inner = train.loc[pd.to_datetime(train.trade_date).ge(inner_start)].copy()
    core = train.loc[
        pd.to_datetime(train.trade_date).lt(inner_start)
        & pd.to_datetime(train.exit_date).lt(inner_start)
    ].copy()
    final_core_date = pd.to_datetime(core.trade_date).max()
    core = core.loc[pd.to_datetime(core.trade_date).ne(final_core_date)]
    if core.empty or inner.empty:
        raise StageBError("inner split is empty")
    return core, inner


def run_models(spec: dict[str, Any], features: list[str]) -> dict[str, Any]:
    columns = [
        "trade_date",
        "exit_date",
        "symbol",
        "industry",
        "signal_eligible",
        "entry_executable",
        "label_valid",
        "label_net",
        "label_gross",
        "ret_prevclose_to_1425",
        "ret_1301_1425",
        "cutoff_vs_vwap_1425",
        "residual_vs_industry_1425",
        *features,
    ]
    columns = list(dict.fromkeys(columns))
    panel = pq.read_table(PANEL_PATH, columns=columns, use_threads=False).to_pandas()
    panel["trade_date"] = pd.to_datetime(panel.trade_date, errors="raise")
    panel["exit_date"] = pd.to_datetime(panel.exit_date, errors="coerce")
    panel = (
        panel.loc[panel.signal_eligible]
        .sort_values(["trade_date", "symbol"])
        .reset_index(drop=True)
    )
    if panel.trade_date.max().year >= 2024:
        raise StageBError("post-2023 row entered modeling")
    predictions: list[pd.DataFrame] = []
    profile_metrics: list[dict[str, Any]] = []
    folds = CORE.frozen_development_folds()
    profiles = spec["models"]["lightgbm_profiles"]

    ridge_predictions: list[pd.DataFrame] = []
    lgb_predictions: dict[str, list[pd.DataFrame]] = {profile["name"]: [] for profile in profiles}
    for fold_index, fold in enumerate(folds):
        train_mask = CORE.purged_training_mask(panel.trade_date, panel.exit_date, fold)
        train = panel.loc[train_mask & panel.label_valid].copy()
        predict = panel.loc[
            panel.trade_date.ge(fold.predict_start) & panel.trade_date.le(fold.predict_end)
        ].copy()
        if train.empty or predict.empty:
            raise StageBError(f"empty outer fold {fold_index}")
        ridge = CORE.ridge_pipeline(10.0)
        ridge.fit(train[features], train.label_net)
        ridge_frame = predict[
            [
                "trade_date",
                "exit_date",
                "symbol",
                "industry",
                "entry_executable",
                "label_valid",
                "label_net",
                "label_gross",
            ]
        ].copy()
        ridge_frame["score"] = ridge.predict(predict[features])
        ridge_frame["model"] = "ridge"
        ridge_frame["fold"] = fold_index
        ridge_predictions.append(ridge_frame)

        core_train, inner = _inner_split(train)
        for profile in profiles:
            early = CORE.lightgbm_model(profile, SEED + fold_index)
            early.fit(
                core_train[features],
                core_train.label_net,
                eval_set=[(inner[features], inner.label_net)],
                callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)],
            )
            best_iteration = int(early.best_iteration_ or 2000)
            model = CORE.lightgbm_model(profile, SEED + fold_index, best_iteration)
            model.fit(train[features], train.label_net)
            predicted = predict[
                [
                    "trade_date",
                    "exit_date",
                    "symbol",
                    "industry",
                    "entry_executable",
                    "label_valid",
                    "label_net",
                    "label_gross",
                ]
            ].copy()
            predicted["score"] = model.predict(predict[features])
            predicted["model"] = profile["name"]
            predicted["fold"] = fold_index
            predicted["best_iteration"] = best_iteration
            lgb_predictions[profile["name"]].append(predicted)
            model_path = MODEL_ROOT / f"development_fold{fold_index}_{profile['name']}.txt"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model.booster_.save_model(model_path)

    ridge_oof = pd.concat(ridge_predictions, ignore_index=True)
    predictions.append(ridge_oof)
    profile_metrics.append(_metrics(ridge_oof, "score", "ridge"))
    for profile in profiles:
        name = profile["name"]
        frame = pd.concat(lgb_predictions[name], ignore_index=True)
        predictions.append(frame)
        profile_metrics.append(_metrics(frame, "score", name))

    development = panel.loc[panel.trade_date.between("2018-01-01", "2021-12-31")].copy()
    baselines = {
        "rank_ret_prevclose_to_1425": "ret_prevclose_to_1425",
        "rank_ret_1301_1425": "ret_1301_1425",
        "rank_cutoff_vs_vwap_1425": "cutoff_vs_vwap_1425",
        "rank_residual_vs_industry_1425": "residual_vs_industry_1425",
    }
    baseline_metrics = [_metrics(development, column, name) for name, column in baselines.items()]
    universe_daily = development.loc[development.label_valid].groupby("trade_date").label_net.mean()
    universe = {
        "model": "eligible_universe_equal_weight",
        "decision_dates": int(universe_daily.index.nunique()),
        "mean_net_return": float(universe_daily.mean()),
    }

    lightgbm_metrics = [row for row in profile_metrics if row["model"] != "ridge"]
    selected = sorted(
        lightgbm_metrics,
        key=lambda row: (
            -row["mean_daily_rank_ic"],
            [p["name"] for p in profiles].index(row["model"]),
        ),
    )[0]
    selected_name = selected["model"]
    annual = selected["annual_rank_ic"]
    gates = {
        "positive_mean_rank_ic": selected["mean_daily_rank_ic"] > 0,
        "nonnegative_each_2018_2021_rank_ic": all(
            annual.get(str(year), -math.inf) >= 0 for year in range(2018, 2022)
        ),
        "positive_top10_net": selected["top10_mean_net_return"] > 0,
        "top10_beats_universe": selected["top10_mean_net_return"] > universe["mean_net_return"],
        "entry_execution_fraction": selected["top10_entry_execution_fraction"] >= 0.90,
    }
    development_pass = all(gates.values())
    validation_result: dict[str, Any] | None = None

    if development_pass:
        train = panel.loc[
            panel.trade_date.between("2014-01-01", "2021-12-31") & panel.label_valid
        ].copy()
        validation = panel.loc[panel.trade_date.between("2022-01-04", "2023-12-29")].copy()
        core_train, inner = _inner_split(train)
        profile = next(item for item in profiles if item["name"] == selected_name)
        early = CORE.lightgbm_model(profile, SEED)
        early.fit(
            core_train[features],
            core_train.label_net,
            eval_set=[(inner[features], inner.label_net)],
            callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)],
        )
        best_iteration = int(early.best_iteration_ or 2000)
        model = CORE.lightgbm_model(profile, SEED, best_iteration)
        model.fit(train[features], train.label_net)
        validation_prediction = validation[
            [
                "trade_date",
                "exit_date",
                "symbol",
                "industry",
                "entry_executable",
                "label_valid",
                "label_net",
                "label_gross",
            ]
        ].copy()
        validation_prediction["score"] = model.predict(validation[features])
        validation_prediction["model"] = selected_name
        validation_prediction["fold"] = 4
        validation_prediction["best_iteration"] = best_iteration
        predictions.append(validation_prediction)
        lightgbm_validation = _metrics(validation_prediction, "score", selected_name)

        ridge = CORE.ridge_pipeline(10.0)
        ridge.fit(train[features], train.label_net)
        ridge_validation = validation_prediction.drop(
            columns=["score", "model", "best_iteration"]
        ).copy()
        ridge_validation["score"] = ridge.predict(validation[features])
        ridge_validation["model"] = "ridge"
        predictions.append(ridge_validation)
        ridge_validation_metrics = _metrics(ridge_validation, "score", "ridge")
        validation_baselines = [
            _metrics(validation, column, name) for name, column in baselines.items()
        ]
        best_simple = max(validation_baselines, key=lambda row: row["mean_daily_rank_ic"])
        validation_universe_daily = (
            validation.loc[validation.label_valid].groupby("trade_date").label_net.mean()
        )
        validation_universe_mean = float(validation_universe_daily.mean())
        annual_val = lightgbm_validation["annual_rank_ic"]
        concentration = validation_prediction.loc[validation_prediction.label_valid].copy()
        concentration["positive_pnl"] = concentration.label_net.clip(lower=0)
        total_positive = concentration.positive_pnl.sum()
        top_dates = concentration.groupby("trade_date").positive_pnl.sum().nlargest(10).sum()
        top_security = concentration.groupby("symbol").positive_pnl.sum().max()
        top_industry = concentration.groupby("industry").positive_pnl.sum().max()
        no_majority = (
            total_positive > 0 and max(top_dates, top_security, top_industry) < 0.5 * total_positive
        )
        validation_gates = {
            "rank_ic_at_least_001": lightgbm_validation["mean_daily_rank_ic"] >= 0.01,
            "nonnegative_2022_rank_ic": annual_val.get("2022", -math.inf) >= 0,
            "nonnegative_2023_rank_ic": annual_val.get("2023", -math.inf) >= 0,
            "rank_ic_beats_ridge_0005": lightgbm_validation["mean_daily_rank_ic"]
            - ridge_validation_metrics["mean_daily_rank_ic"]
            >= 0.005,
            "rank_ic_beats_simple_0005": lightgbm_validation["mean_daily_rank_ic"]
            - best_simple["mean_daily_rank_ic"]
            >= 0.005,
            "positive_top10_net": lightgbm_validation["top10_mean_net_return"] > 0,
            "top10_incremental_0005": lightgbm_validation["top10_mean_net_return"]
            - max(
                validation_universe_mean,
                ridge_validation_metrics["top10_mean_net_return"],
                best_simple["top10_mean_net_return"],
            )
            >= 0.0005,
            "nonnegative_2022_top10": lightgbm_validation["annual_top10_net_return"].get(
                "2022", -math.inf
            )
            >= 0,
            "nonnegative_2023_top10": lightgbm_validation["annual_top10_net_return"].get(
                "2023", -math.inf
            )
            >= 0,
            "entry_execution_fraction": lightgbm_validation["top10_entry_execution_fraction"]
            >= 0.90,
            "not_majority_concentrated": no_majority,
        }
        validation_result = {
            "lightgbm": lightgbm_validation,
            "ridge": ridge_validation_metrics,
            "simple_baselines": validation_baselines,
            "best_simple": best_simple["model"],
            "eligible_universe_mean_net": validation_universe_mean,
            "gates": validation_gates,
            "passed": all(validation_gates.values()),
        }

    prediction_frame = pd.concat(predictions, ignore_index=True)
    prediction_frame.to_parquet(PREDICTION_PATH, index=False, compression="zstd")
    if not development_pass:
        if selected["mean_daily_rank_ic"] <= 0:
            classification = "ML_NO_CROSS_SECTIONAL_SIGNAL"
        elif any(annual.get(str(year), 0) < 0 for year in range(2018, 2022)):
            classification = "ML_CHRONOLOGICALLY_UNSTABLE"
        elif selected["top10_mean_net_return"] <= 0:
            classification = "ML_EXECUTION_FAILURE"
        else:
            classification = "ML_NO_INCREMENTAL_VALUE"
    elif validation_result is not None and not validation_result["passed"]:
        classification = "ML_VALIDATION_FAILURE"
    else:
        classification = "ML_PROMISING_BUT_MIXED"
    return {
        "classification": classification,
        "development": {
            "profile_metrics": profile_metrics,
            "simple_baselines": baseline_metrics,
            "eligible_universe": universe,
            "selected_profile": selected_name,
            "gates": gates,
            "passed": development_pass,
        },
        "validation": validation_result,
        "final_oos_authorized": bool(validation_result and validation_result["passed"]),
        "prediction_sha256": sha256_file(PREDICTION_PATH),
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
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def render(result: dict[str, Any]) -> str:
    development = result["modeling"]["development"]
    selected = next(
        row
        for row in development["profile_metrics"]
        if row["model"] == development["selected_profile"]
    )
    lines = [
        "# A-share Tail-to-Open LightGBM V1 — Stage B",
        "",
        "## CLASSIFICATION",
        "",
        f"`{result['classification']}`",
        "",
        "## DEVELOPMENT",
        "",
        "| Model | Mean rank IC | Top-10 net | Entry execution |",
        "|---|---:|---:|---:|",
    ]
    for row in development["profile_metrics"]:
        lines.append(
            f"| {row['model']} | {row['mean_daily_rank_ic']:.4f} | "
            f"{row['top10_mean_net_return']:.3%} | {row['top10_entry_execution_fraction']:.2%} |"
        )
    lines.extend(
        [
            "",
            f"Selected profile: `{development['selected_profile']}`. Development gate: "
            f"`{'PASS' if development['passed'] else 'FAIL'}`.",
            "",
            f"Selected annual rank IC: `{selected['annual_rank_ic']}`.",
            "",
        ]
    )
    if result["modeling"]["validation"] is None:
        lines.extend(
            [
                "## VALIDATION",
                "",
                "Not opened because the frozen development gate failed.",
                "",
            ]
        )
    else:
        validation = result["modeling"]["validation"]
        lines.extend(
            [
                "## VALIDATION",
                "",
                f"Validation gate: `{'PASS' if validation['passed'] else 'FAIL'}`.",
                f"LightGBM rank IC `{validation['lightgbm']['mean_daily_rank_ic']:.4f}`; "
                f"Top-10 net `{validation['lightgbm']['top10_mean_net_return']:.3%}`.",
                "",
            ]
        )
    lines.extend(
        [
            "## FINAL OOS",
            "",
            "Final OOS remains `LOCKED_UNREAD`. No 2024--2026 security row, feature, label,",
            "prediction, or portfolio outcome was read in Stage B.",
            "",
        ]
    )
    return "\n".join(lines)


def run_build_only(verify: bool) -> dict[str, Any]:
    spec, _, features = _load_contracts()
    raw_paths, daily_paths, minute_paths = _inventory_paths(spec)
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    source_hashes = verify_source_content(spec) if verify else {"verified": False}
    build_audit = {
        "raw": build_raw_feature_shards(raw_paths, daily_paths),
        "daily": build_daily_contract(daily_paths),
        "raw_enriched": enrich_raw_history(),
        "panel": build_model_panel(minute_paths, features),
    }
    materialization_hashes = verify_frozen_materializations(spec)
    result = {
        "experiment_id": "ASHARE-TAIL-OPEN-LGBM-V1",
        "stage": "CHRONOLOGY_EXTENSION_BUILD_ONLY",
        "source_hashes": source_hashes,
        "materialization_hashes": materialization_hashes,
        "build_audit": build_audit,
        "boundaries": {
            "ridge_fit": False,
            "lightgbm_fit": False,
            "model_performance_read": False,
            "post_2023_security_rows_read": False,
            "final_oos_opened": False,
            "cy011_read": False,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "feature_manifest_sha256": sha256_file(FEATURE_PATH),
            "daily_contract_sha256": sha256_file(DAILY_CONTRACT),
            "raw_enriched_sha256": sha256_file(RAW_ENRICHED),
            "panel_sha256": sha256_file(PANEL_PATH),
        },
        "resources": {"peak_rss_bytes": _max_rss_bytes()},
    }
    clean = _clean(result)
    _atomic_write(BUILD_AUDIT_PATH, json.dumps(clean, indent=2, sort_keys=True) + "\n")
    return clean


def run(build: bool, verify: bool) -> dict[str, Any]:
    spec, _, features = _load_contracts()
    raw_paths, daily_paths, minute_paths = _inventory_paths(spec)
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    source_hashes = verify_source_content(spec) if verify else {"verified": False}
    build_audit: dict[str, Any] = {}
    if build:
        build_audit["raw"] = build_raw_feature_shards(raw_paths, daily_paths)
        build_audit["daily"] = build_daily_contract(daily_paths)
        build_audit["raw_enriched"] = enrich_raw_history()
        build_audit["panel"] = build_model_panel(minute_paths, features)
    for path in (DAILY_CONTRACT, RAW_ENRICHED, PANEL_PATH):
        if not path.is_file():
            raise StageBError(f"required Stage-B materialization missing: {path}")
    verify_frozen_materializations(spec)
    modeling = run_models(spec, features)
    result = {
        "experiment_id": "ASHARE-TAIL-OPEN-LGBM-V1",
        "stage": "B",
        "classification": modeling["classification"],
        "source_hashes": source_hashes,
        "build_audit": build_audit,
        "modeling": modeling,
        "boundaries": {
            "post_2023_security_rows_read": False,
            "final_oos_opened": False,
            "final_oos_authorized": modeling["final_oos_authorized"],
            "prior_families_reopened": False,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "feature_manifest_sha256": sha256_file(FEATURE_PATH),
            "daily_contract_sha256": sha256_file(DAILY_CONTRACT),
            "raw_enriched_sha256": sha256_file(RAW_ENRICHED),
            "panel_sha256": sha256_file(PANEL_PATH),
        },
        "resources": {"peak_rss_bytes": _max_rss_bytes()},
    }
    clean = _clean(result)
    _atomic_write(RESULT_PATH, json.dumps(clean, indent=2, sort_keys=True) + "\n")
    summary_rows = clean["modeling"]["development"]["profile_metrics"]
    pd.DataFrame(summary_rows).to_csv(SUMMARY_PATH, index=False, lineterminator="\n")
    _atomic_write(REPORT_PATH, render(clean))
    return clean


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--verify-inputs", action="store_true")
    args = parser.parse_args()
    if args.build_only:
        if args.build:
            parser.error("--build-only and --build are mutually exclusive")
        result = run_build_only(args.verify_inputs)
        print(json.dumps({"stage": result["stage"], "boundaries": result["boundaries"]}))
        return
    result = run(args.build, args.verify_inputs)
    print(
        json.dumps(
            {"classification": result["classification"], "boundaries": result["boundaries"]},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
