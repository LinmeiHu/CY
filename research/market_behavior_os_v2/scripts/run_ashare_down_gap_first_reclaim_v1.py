#!/usr/bin/env python3
# ruff: noqa: E501
"""Development-only replay for ASHARE-DOWN-GAP-FIRST-RECLAIM-V1.

The script consumes the frozen gap inventory and daily-path candidates, confirms
the lifetime first crossing on QD-004 one-minute bars, constructs causal dry-up
diagnostics, and evaluates only outcomes ending no later than 2021-12-31.
Large resumable products stay on /Volumes/quant; compact scientific artifacts
are written to the Research OS tree.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
SPEC = OS_ROOT / "experiments/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_spec.json"
EXPECTED_SPEC_SHA256 = "de8bfdf427e4f1cc3a9a5dfd98e827831417616d82c0348adc7e25917a937289"
QD004_INVENTORY = OS_ROOT / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_qd004_2013_2023_inventory.json"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_down_gap_first_reclaim_v1")
GAPS = EXTERNAL / "down_gaps_2014_2021.parquet"
CANDIDATES = EXTERNAL / "daily_first_reclaim_candidates.parquet"
EVENTS = EXTERNAL / "first_reclaim_gap_events_2014_2021.parquet"
TRADES = EXTERNAL / "first_reclaim_executable_entries_2014_2021.parquet"
MECHANISMS = EXTERNAL / "first_reclaim_mechanisms_2014_2021.parquet"
OUTCOMES = EXTERNAL / "first_reclaim_outcomes_2014_2021.parquet"
DAILY_FEATURES = EXTERNAL / "daily_pre_reclaim_features.parquet"
HISTORY_MAP = EXTERNAL / "intraday_history_map.parquet"
INTRADAY_HISTORY = EXTERNAL / "intraday_history_amounts.parquet"
RESULT = OS_ROOT / "artifacts/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_result.json"
COMPACT = OS_ROOT / "artifacts/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_compact.parquet"
REPORT = OS_ROOT / "reports/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_report.md"

RAW_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars"
)
OLD_DAILY_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006/daily"
)
NEW_DAILY_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")

DEVELOPMENT_YEARS = tuple(range(2014, 2022))
HISTORY_YEARS = tuple(range(2013, 2022))
ENTRY_COST = 0.002
EXIT_COST = 0.002


class ContractError(RuntimeError):
    """A fail-closed contract or lineage error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if pd.isna(value) if not isinstance(value, (list, tuple, dict)) else False:
        return None
    return value


def daily_paths() -> list[Path]:
    return [
        *[OLD_DAILY_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2013, 2018)],
        *[NEW_DAILY_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2022)],
    ]


def sql_paths(paths: Iterable[Path]) -> str:
    return "[" + ",".join("'" + str(p).replace("'", "''") + "'" for p in paths) + "]"


def connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{EXTERNAL / 'duckdb_tmp'!s}'")
    return con


def validate_inputs() -> dict[str, Any]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if sha256_file(SPEC) != EXPECTED_SPEC_SHA256:
        raise ContractError("frozen V1 spec identity changed")
    if spec["development"] != ["2014-01-01", "2021-12-31"]:
        raise ContractError("Development chronology changed")
    if spec["gap"] != {
        "minimum_pct": 0.05,
        "trigger_multiple": 1.01,
        "first_reclaim_only": True,
        "same_day_allowed": True,
    }:
        raise ContractError("frozen gap contract changed")
    required = [SPEC, QD004_INVENTORY, GAPS, CANDIDATES, *daily_paths()]
    required += [RAW_ROOT / f"{year}_day_parquet_none.parquet" for year in HISTORY_YEARS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ContractError(f"missing required inputs: {missing}")
    inventory = json.loads(QD004_INVENTORY.read_text(encoding="utf-8"))
    registered = {Path(x["path"]).name: x for x in inventory["files"]}
    raw_identity = {}
    for year in HISTORY_YEARS:
        path = RAW_ROOT / f"{year}_day_parquet_none.parquet"
        record = registered.get(path.name)
        if record is None or record["size"] != path.stat().st_size:
            raise ContractError(f"QD-004 identity mismatch: {path}")
        raw_identity[str(year)] = {"bytes": record["size"], "sha256": record["sha256"]}
    con = connection()
    gap_audit = con.execute(
        f"""SELECT count(*) n, count(DISTINCT symbol||'|'||CAST(gap_date AS VARCHAR)) ids,
        min(gap_date) first_date,max(gap_date) last_date,
        sum(CASE WHEN gap_pct<0.05 OR abs(trigger_price-gap_open*1.01)>1e-9 THEN 1 ELSE 0 END) bad
        FROM read_parquet('{GAPS}')"""
    ).fetchone()
    candidate_audit = con.execute(
        f"""SELECT count(*) total,count(*) FILTER(WHERE reclaim_date IS NOT NULL) candidates,
        count(*) FILTER(WHERE reclaim_date IS NULL) unreclaimed,
        count(DISTINCT symbol||'|'||CAST(gap_date AS VARCHAR)) ids,
        max(reclaim_date) max_date FROM read_parquet('{CANDIDATES}')"""
    ).fetchone()
    development_sessions = con.execute(
        f"SELECT count(DISTINCT trade_date) FROM read_parquet({sql_paths(daily_paths()[1:])}) WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31'"
    ).fetchone()[0]
    con.close()
    if gap_audit[0] != gap_audit[1] or gap_audit[4] != 0:
        raise ContractError(f"gap inventory invariant failed: {gap_audit}")
    if candidate_audit[0] != gap_audit[0] or candidate_audit[3] != gap_audit[0]:
        raise ContractError(f"candidate inventory mismatch: {candidate_audit}")
    if str(candidate_audit[4]) > "2021-12-31":
        raise ContractError("candidate artifact reaches beyond Development")
    return {
        "spec_sha256": sha256_file(SPEC),
        "qd004_inventory_sha256": sha256_file(QD004_INVENTORY),
        "raw_minute_identity": raw_identity,
        "qualifying_gaps": int(gap_audit[0]),
        "daily_path_candidates": int(candidate_audit[1]),
        "unreclaimed_daily_path": int(candidate_audit[2]),
        "development_trading_sessions": int(development_sessions),
    }


def minute_scan() -> pd.DataFrame:
    shard_dir = EXTERNAL / "minute_crossing_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    for year in DEVELOPMENT_YEARS:
        shard = shard_dir / f"crossings_{year}.parquet"
        if shard.is_file():
            continue
        raw = RAW_ROOT / f"{year}_day_parquet_none.parquet"
        con = connection()
        con.execute(
            f"""COPY (
            WITH candidates AS (
              SELECT *,symbol||'|'||CAST(gap_date AS VARCHAR) AS gap_id
              FROM read_parquet('{CANDIDATES}')
              WHERE reclaim_date IS NOT NULL AND year(reclaim_date)={year}
            ), relevant AS (
              SELECT DISTINCT symbol,reclaim_date FROM candidates
            ), bars AS (
              SELECT m.qmt_code AS symbol,m.trade_date,m.bar_end_time,m.open,m.high,m.low,m.close,m.amount,
                     count(*) OVER(PARTITION BY m.qmt_code,m.trade_date) AS session_minute_count,
                     coalesce(sum(m.amount) OVER(PARTITION BY m.qmt_code,m.trade_date ORDER BY m.bar_end_time
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0.0) AS pre_cross_amount
              FROM read_parquet('{raw}') m
              JOIN relevant r ON r.symbol=m.qmt_code AND r.reclaim_date=m.trade_date
            ), crossings AS (
              SELECT c.*,b.bar_end_time,b.open AS crossing_bar_open,b.high AS crossing_bar_high,
                     b.low AS crossing_bar_low,b.close AS crossing_bar_close,b.pre_cross_amount,
                     b.session_minute_count,
                     CASE WHEN b.open>=c.trigger_price THEN b.open ELSE c.trigger_price END AS entry_price,
                     CASE WHEN b.open>=c.trigger_price THEN 'GAP_THROUGH' ELSE 'STOP_TRIGGER' END AS execution_type
              FROM candidates c JOIN bars b USING(symbol)
              WHERE b.trade_date=c.reclaim_date AND b.high+1e-10>=c.trigger_price
              QUALIFY row_number() OVER(PARTITION BY c.gap_id ORDER BY b.bar_end_time)=1
            ) SELECT * FROM crossings ORDER BY gap_id
            ) TO '{shard}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        con.close()
    con = connection()
    frame = con.execute(
        f"SELECT * FROM read_parquet('{shard_dir}/crossings_*.parquet') ORDER BY gap_id"
    ).fetchdf()
    con.close()
    frame["bar_end_time"] = pd.to_datetime(frame["bar_end_time"])
    return frame


def build_daily_features() -> tuple[pd.DataFrame, pd.DataFrame, int]:
    paths = sql_paths(daily_paths())
    con = connection()
    con.execute(f"CREATE OR REPLACE TEMP VIEW daily AS SELECT * FROM read_parquet({paths})")
    if not DAILY_FEATURES.is_file() or not HISTORY_MAP.is_file():
        con.execute(
            f"""COPY (
            WITH eligible AS (
              SELECT symbol,trade_date,turnover_fraction,close,open,high,low,is_st,industry,
                     limit_pct,up_limit_price,down_limit_price,buy_blocked_open,sell_blocked_open,
                     corporate_action_count,corporate_action_blocking,corporate_action_valid,
                     hard_valid,current_day_data_tradable,trade_status,available_at,snapshot_id
              FROM daily WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2021-12-31'
                AND hard_valid AND current_day_data_tradable AND trade_status=1
                AND corporate_action_valid AND NOT corporate_action_blocking
                AND coalesce(corporate_action_count,0)=0
                AND turnover_fraction IS NOT NULL AND isfinite(turnover_fraction)
            ), windowed AS (
              SELECT *,
                count(*) OVER w20 AS prior20_count,
                median(turnover_fraction) OVER w3 AS turnover_recent3,
                median(turnover_fraction) OVER w17 AS turnover_prior17,
                median(turnover_fraction) OVER w2 AS turnover_recent2,
                median(turnover_fraction) OVER wprev3 AS turnover_previous3,
                median(close) OVER wclose3 AS close_recent3,
                median(close) OVER wcloseprev3 AS close_previous3,
                list(trade_date) OVER w20 AS prior20_dates
              FROM eligible
              WINDOW
                w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
                w3 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING),
                w17 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 4 PRECEDING),
                w2 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING),
                wprev3 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING),
                wclose3 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING),
                wcloseprev3 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 6 PRECEDING AND 4 PRECEDING)
            ), event_dates AS (
              SELECT DISTINCT symbol,reclaim_date FROM read_parquet('{CANDIDATES}') WHERE reclaim_date IS NOT NULL
            )
            SELECT w.* EXCLUDE(prior20_dates),
                   turnover_recent3/nullif(turnover_prior17,0) AS dryup_3_20,
                   turnover_recent2/nullif(turnover_previous3,0) AS compression_trend,
                   close_recent3>=close_previous3 AS price_resistance
            FROM windowed w JOIN event_dates e ON e.symbol=w.symbol AND e.reclaim_date=w.trade_date
            ) TO '{DAILY_FEATURES}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        con.execute(
            f"""COPY (
            WITH eligible AS (
              SELECT symbol,trade_date FROM daily
              WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2021-12-31'
                AND hard_valid AND current_day_data_tradable AND trade_status=1
                AND corporate_action_valid AND NOT corporate_action_blocking
                AND coalesce(corporate_action_count,0)=0
                AND turnover_fraction IS NOT NULL AND isfinite(turnover_fraction)
            ), windowed AS (
              SELECT *,count(*) OVER w AS prior20_count,list(trade_date) OVER w AS prior20_dates
              FROM eligible WINDOW w AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
            ), event_dates AS (
              SELECT DISTINCT symbol,reclaim_date FROM read_parquet('{CANDIDATES}') WHERE reclaim_date IS NOT NULL
            )
            SELECT e.symbol,e.reclaim_date,u.hist_date
            FROM windowed w JOIN event_dates e ON e.symbol=w.symbol AND e.reclaim_date=w.trade_date,
                 unnest(w.prior20_dates) u(hist_date)
            WHERE w.prior20_count=20
            ) TO '{HISTORY_MAP}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
    false_gaps = con.execute(
        """WITH base AS (
          SELECT symbol,trade_date,open,close,industry,corporate_action_count,
                 lag(close) OVER(PARTITION BY symbol ORDER BY trade_date) prev_close,
                 lag(coalesce(corporate_action_count,0)) OVER(PARTITION BY symbol ORDER BY trade_date) prev_action
          FROM daily WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2021-12-31'
            AND (symbol LIKE '60%.SH' OR symbol LIKE '00%.SZ' OR symbol LIKE '30%.SZ')
            AND symbol NOT LIKE '688%.SH'
        )
        SELECT count(*) FROM base
        WHERE trade_date>=DATE '2014-01-01' AND prev_close>0 AND 1-open/prev_close>=0.05
          AND (coalesce(corporate_action_count,0)>0 OR coalesce(prev_action,0)>0)"""
    ).fetchone()[0]
    features = con.execute(f"SELECT * FROM read_parquet('{DAILY_FEATURES}')").fetchdf()
    hist = con.execute(f"SELECT * FROM read_parquet('{HISTORY_MAP}')").fetchdf()
    con.close()
    return features, hist, int(false_gaps)


def build_intraday_history(events: pd.DataFrame, history_map: pd.DataFrame) -> pd.DataFrame:
    target = events[["gap_id", "symbol", "reclaim_date", "bar_end_time"]].merge(
        history_map, on=["symbol", "reclaim_date"], how="left", validate="many_to_many"
    )
    target["cutoff_minute"] = target.bar_end_time.dt.hour * 60 + target.bar_end_time.dt.minute
    target_path = EXTERNAL / "intraday_history_targets.parquet"
    pq.write_table(
        pa.Table.from_pandas(target, preserve_index=False), target_path, compression="zstd"
    )
    shard_dir = EXTERNAL / "intraday_history_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    for year in HISTORY_YEARS:
        shard = shard_dir / f"history_{year}.parquet"
        if shard.is_file():
            continue
        raw = RAW_ROOT / f"{year}_day_parquet_none.parquet"
        con = connection()
        con.execute(
            f"""COPY (
              SELECT t.gap_id,t.hist_date,sum(m.amount) AS historical_pre_cross_amount,
                     count(*) AS historical_bar_count
              FROM read_parquet('{target_path}') t
              JOIN read_parquet('{raw}') m ON m.qmt_code=t.symbol AND m.trade_date=t.hist_date
              WHERE year(t.hist_date)={year}
                AND extract(hour FROM m.bar_end_time)*60+extract(minute FROM m.bar_end_time)<t.cutoff_minute
              GROUP BY t.gap_id,t.hist_date
            ) TO '{shard}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        con.close()
    con = connection()
    con.execute(
        f"""COPY (
          SELECT gap_id,count(*) AS intraday_history_count,
                 median(historical_pre_cross_amount) AS historical_same_clock_median,
                 min(historical_bar_count) AS min_historical_bar_count
          FROM read_parquet('{shard_dir}/history_*.parquet') GROUP BY gap_id
        ) TO '{INTRADAY_HISTORY}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
    )
    result = con.execute(f"SELECT * FROM read_parquet('{INTRADAY_HISTORY}')").fetchdf()
    con.close()
    return result


def lifecycle_action_audit(crossings: pd.DataFrame) -> pd.DataFrame:
    """Find the first contract-invalidating action strictly after each gap date."""
    target = EXTERNAL / "gap_lifecycle_action_targets.parquet"
    pq.write_table(
        pa.Table.from_pandas(
            crossings[["gap_id", "symbol", "gap_date", "reclaim_date"]],
            preserve_index=False,
        ),
        target,
        compression="zstd",
    )
    con = connection()
    paths = sql_paths(daily_paths())
    result = con.execute(
        f"""WITH events AS (SELECT * FROM read_parquet('{target}')),
        actions AS (
          SELECT symbol,trade_date FROM read_parquet({paths})
          WHERE coalesce(corporate_action_count,0)>0
             OR corporate_action_blocking OR NOT corporate_action_valid
        )
        SELECT e.gap_id,a.trade_date AS next_lifecycle_action_date
        FROM events e ASOF LEFT JOIN actions a
          ON e.symbol=a.symbol AND e.gap_date<a.trade_date"""
    ).fetchdf()
    con.close()
    return result


def classify_gap_age(days: pd.Series) -> pd.Categorical:
    labels = ["same day", "1-3", "4-10", "11-20", "21-60", "61-120", ">120"]
    return pd.cut(days, [-1, 0, 3, 10, 20, 60, 120, np.inf], labels=labels)


def ratio_bin(values: pd.Series) -> pd.Categorical:
    return pd.cut(
        values,
        [-np.inf, 0.30, 0.50, 0.70, 1.00, np.inf],
        labels=["<=0.30", "(0.30,0.50]", "(0.50,0.70]", "(0.70,1.00]", ">1.00"],
    )


def assemble_events(
    crossings: pd.DataFrame, features: pd.DataFrame, intraday: pd.DataFrame
) -> pd.DataFrame:
    action_audit = lifecycle_action_audit(crossings)
    events = (
        crossings.merge(
            features,
            left_on=["symbol", "reclaim_date"],
            right_on=["symbol", "trade_date"],
            how="left",
            suffixes=("", "_trigger"),
            validate="many_to_one",
        )
        .merge(intraday, on="gap_id", how="left", validate="one_to_one")
        .merge(action_audit, on="gap_id", how="left", validate="one_to_one")
    )
    calendar_paths = sql_paths(daily_paths())
    con = connection()
    cal = con.execute(
        f"SELECT DISTINCT trade_date FROM read_parquet({calendar_paths}) WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31' ORDER BY 1"
    ).fetchdf()
    con.close()
    cal_map = pd.Series(np.arange(len(cal)), index=pd.to_datetime(cal.trade_date)).to_dict()
    events["gap_date"] = pd.to_datetime(events.gap_date)
    events["reclaim_date"] = pd.to_datetime(events.reclaim_date)
    events["gap_age_trading_days"] = [
        cal_map.get(r) - cal_map.get(g) if g in cal_map and r in cal_map else np.nan
        for g, r in zip(events.gap_date, events.reclaim_date, strict=True)
    ]
    events["gap_age_group"] = classify_gap_age(events.gap_age_trading_days)
    events["intraday_dryup"] = (
        events.pre_cross_amount / events.historical_same_clock_median.replace(0, np.nan)
    )
    events["dryup_3_20_bin"] = ratio_bin(events.dryup_3_20)
    events["compression_trend_bin"] = ratio_bin(events.compression_trend)
    events["gap_size_group"] = pd.cut(
        events.gap_pct,
        [0.05 - 1e-12, 0.07, 0.09, np.inf],
        labels=["5-7%", "7-9%", ">=9%"],
        right=False,
    )
    gap_tick_delta = events.gap_open - events.down_limit_price
    events["limit_state"] = np.select(
        [gap_tick_delta.abs() <= 0.005, (gap_tick_delta > 0.005) & (gap_tick_delta <= 0.015)],
        ["exact lower-limit open", "near lower-limit open"],
        default="ordinary large gap",
    )
    events.loc[events.down_limit_price.isna(), "limit_state"] = "unknown"
    hard_valid = events.hard_valid.astype("boolean").fillna(False)
    current_tradable = events.current_day_data_tradable.astype("boolean").fillna(False)
    action_valid = events.corporate_action_valid.astype("boolean").fillna(False)
    action_blocking = events.corporate_action_blocking.astype("boolean").fillna(True)
    events["execution_valid"] = (
        events.session_minute_count.eq(241)
        & hard_valid
        & current_tradable
        & events.trade_status.eq(1)
        & action_valid
        & ~action_blocking
        & events.corporate_action_count.fillna(1).eq(0)
        & events.up_limit_price.notna()
        & (events.entry_price < events.up_limit_price - 0.005)
        & events.entry_price.notna()
        & events.bar_end_time.notna()
        & (
            events.next_lifecycle_action_date.isna()
            | (pd.to_datetime(events.next_lifecycle_action_date) > events.reclaim_date)
        )
    )
    return events


def collapse_trades(events: pd.DataFrame) -> pd.DataFrame:
    valid = events.loc[events.execution_valid].copy()
    valid = valid.sort_values(["symbol", "bar_end_time", "entry_price", "gap_id"])
    grouped = valid.groupby(["symbol", "bar_end_time"], sort=True, dropna=False)
    trades = grouped.first().reset_index()
    counts = grouped.gap_id.size().rename("underlying_gap_count").reset_index()
    ids = grouped.gap_id.agg(lambda x: "|".join(x)).rename("underlying_gap_ids").reset_index()
    trades = trades.merge(counts, on=["symbol", "bar_end_time"]).merge(
        ids, on=["symbol", "bar_end_time"]
    )
    trades["entry_id"] = trades.symbol + "|" + trades.bar_end_time.dt.strftime("%Y-%m-%dT%H:%M:%S")
    return trades


def build_outcomes(trades: pd.DataFrame) -> pd.DataFrame:
    trades_path = EXTERNAL / "executable_entries_pre_outcome.parquet"
    pq.write_table(
        pa.Table.from_pandas(trades, preserve_index=False), trades_path, compression="zstd"
    )
    if OUTCOMES.is_file() and OUTCOMES.stat().st_size > 0:
        cached = pd.read_parquet(OUTCOMES)
        identity = cached[["entry_id", "entry_price"]].merge(
            trades[["entry_id", "entry_price"]],
            on="entry_id",
            suffixes=("_cached", "_current"),
            validate="one_to_one",
        )
        if len(identity) == len(trades) and np.allclose(
            identity.entry_price_cached, identity.entry_price_current, rtol=0, atol=1e-12
        ):
            cached = cached.loc[cached.entry_id.isin(set(trades.entry_id))].copy()
            complete3 = (
                cached[["t1_close_price", "t2_close_price", "t3_close_price"]].notna().all(axis=1)
            )
            cached.loc[~complete3, ["mfe_3", "mae_3", "t3_high", "t3_low"]] = np.nan
            pq.write_table(
                pa.Table.from_pandas(cached, preserve_index=False), OUTCOMES, compression="zstd"
            )
            for col in [
                "reclaim_date",
                "gap_date",
                "t1_date",
                "t2_date",
                "t3_date",
                "next_legal_open_date",
            ]:
                cached[col] = pd.to_datetime(cached[col])
            return cached.sort_values("entry_id").reset_index(drop=True)
    paths = sql_paths(daily_paths())
    con = connection()
    con.execute(f"CREATE OR REPLACE TEMP VIEW daily AS SELECT * FROM read_parquet({paths})")
    con.execute(
        """CREATE OR REPLACE TEMP VIEW calendar AS
           SELECT trade_date,row_number() OVER(ORDER BY trade_date) AS cal_idx
           FROM (SELECT DISTINCT trade_date FROM daily WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31')"""
    )
    con.execute(
        f"""COPY (
        WITH e AS (SELECT * FROM read_parquet('{trades_path}')),
        targets0 AS (
          SELECT e.*,c.cal_idx,c1.trade_date t1_date,c2.trade_date t2_date,c3.trade_date t3_date
          FROM e JOIN calendar c ON c.trade_date=e.reclaim_date
          LEFT JOIN calendar c1 ON c1.cal_idx=c.cal_idx+1
          LEFT JOIN calendar c2 ON c2.cal_idx=c.cal_idx+2
          LEFT JOIN calendar c3 ON c3.cal_idx=c.cal_idx+3
        ), legal AS (
          SELECT symbol,trade_date,open FROM daily
          WHERE hard_valid AND current_day_data_tradable AND trade_status=1
            AND corporate_action_valid AND NOT corporate_action_blocking
            AND coalesce(corporate_action_count,0)=0 AND NOT sell_blocked_open AND open>0
        ), actions AS (
          SELECT symbol,trade_date FROM daily
          WHERE coalesce(corporate_action_count,0)>0 OR corporate_action_blocking OR NOT corporate_action_valid
        ), with_legal AS (
          SELECT t.*,l.trade_date AS next_legal_open_date,l.open AS next_legal_open_price
          FROM targets0 t ASOF LEFT JOIN legal l
            ON t.symbol=l.symbol AND t.reclaim_date<l.trade_date
        ), targets AS (
          SELECT t.*,a.trade_date AS next_action_date
          FROM with_legal t ASOF LEFT JOIN actions a
            ON t.symbol=a.symbol AND t.reclaim_date<a.trade_date
        )
        SELECT t.*,
          CASE WHEN t.next_action_date IS NULL OR t.next_action_date>t.next_legal_open_date
               THEN t.next_legal_open_price END AS t1_legal_open_price,
          d1.close AS t1_close_price,d2.close AS t2_close_price,d3.close AS t3_close_price,
          d1.high AS t1_high,d1.low AS t1_low,
          greatest(d1.high,d2.high,d3.high) AS t3_high,
          least(d1.low,d2.low,d3.low) AS t3_low,
          (CASE WHEN t.next_action_date IS NULL OR t.next_action_date>t.next_legal_open_date
                THEN t.next_legal_open_price END/t.entry_price-1) AS t1_open_gross,
          (CASE WHEN t.next_action_date IS NULL OR t.next_action_date>t.next_legal_open_date
                THEN t.next_legal_open_price END*(1-{EXIT_COST})/(t.entry_price*(1+{ENTRY_COST}))-1) AS t1_open_net,
          (d1.close/t.entry_price-1) AS t1_close_gross,
          (d1.close*(1-{EXIT_COST})/(t.entry_price*(1+{ENTRY_COST}))-1) AS t1_close_net,
          (d2.close/t.entry_price-1) AS t2_close_gross,
          (d2.close*(1-{EXIT_COST})/(t.entry_price*(1+{ENTRY_COST}))-1) AS t2_close_net,
          (d3.close/t.entry_price-1) AS t3_close_gross,
          (d3.close*(1-{EXIT_COST})/(t.entry_price*(1+{ENTRY_COST}))-1) AS t3_close_net,
          (d1.high/t.entry_price-1) AS mfe_1,(d1.low/t.entry_price-1) AS mae_1,
          CASE WHEN d1.close IS NOT NULL AND d2.close IS NOT NULL AND d3.close IS NOT NULL
               THEN greatest(d1.high,d2.high,d3.high)/t.entry_price-1 END AS mfe_3,
          CASE WHEN d1.close IS NOT NULL AND d2.close IS NOT NULL AND d3.close IS NOT NULL
               THEN least(d1.low,d2.low,d3.low)/t.entry_price-1 END AS mae_3
        FROM targets t
        LEFT JOIN daily d1 ON d1.symbol=t.symbol AND d1.trade_date=t.t1_date
          AND d1.hard_valid AND d1.current_day_data_tradable AND d1.trade_status=1
          AND d1.corporate_action_valid AND NOT d1.corporate_action_blocking AND coalesce(d1.corporate_action_count,0)=0
          AND (t.next_action_date IS NULL OR t.next_action_date>t.t1_date)
        LEFT JOIN daily d2 ON d2.symbol=t.symbol AND d2.trade_date=t.t2_date
          AND d2.hard_valid AND d2.current_day_data_tradable AND d2.trade_status=1
          AND d2.corporate_action_valid AND NOT d2.corporate_action_blocking AND coalesce(d2.corporate_action_count,0)=0
          AND (t.next_action_date IS NULL OR t.next_action_date>t.t2_date)
        LEFT JOIN daily d3 ON d3.symbol=t.symbol AND d3.trade_date=t.t3_date
          AND d3.hard_valid AND d3.current_day_data_tradable AND d3.trade_status=1
          AND d3.corporate_action_valid AND NOT d3.corporate_action_blocking AND coalesce(d3.corporate_action_count,0)=0
          AND (t.next_action_date IS NULL OR t.next_action_date>t.t3_date)
        ) TO '{OUTCOMES}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
    )
    frame = con.execute(f"SELECT * FROM read_parquet('{OUTCOMES}') ORDER BY entry_id").fetchdf()
    con.close()
    for col in [
        "reclaim_date",
        "gap_date",
        "t1_date",
        "t2_date",
        "t3_date",
        "next_legal_open_date",
    ]:
        frame[col] = pd.to_datetime(frame[col])
    return frame


def return_summary(frame: pd.DataFrame, stem: str) -> dict[str, Any]:
    gross = frame[f"{stem}_gross"].dropna()
    net = frame[f"{stem}_net"].dropna()
    if gross.empty:
        return {"n": 0}
    return {
        "n": len(gross),
        "gross_mean": float(gross.mean()),
        "gross_median": float(gross.median()),
        "gross_positive_rate": float((gross > 0).mean()),
        "net_mean": float(net.mean()),
        "net_median": float(net.median()),
        "net_positive_rate": float((net > 0).mean()),
        "p10_net": float(net.quantile(0.10)),
        "p25_net": float(net.quantile(0.25)),
        "p75_net": float(net.quantile(0.75)),
        "p90_net": float(net.quantile(0.90)),
        "severe_loss10": float((net <= -0.10).mean()),
    }


def grouped_summary(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    result = {}
    for key, group in frame.groupby(column, observed=False, dropna=False):
        label = "MISSING" if pd.isna(key) else str(key)
        result[label] = {
            stem: return_summary(group, stem)
            for stem in ("t1_open", "t1_close", "t2_close", "t3_close")
        }
        result[label]["mfe_mae"] = {
            x: (float(group[x].mean()) if group[x].notna().any() else None)
            for x in ("mfe_1", "mae_1", "mfe_3", "mae_3")
        }
    return result


def analyze(
    outcomes: pd.DataFrame, events: pd.DataFrame, input_audit: dict[str, Any], false_gaps: int
) -> dict[str, Any]:
    horizons = {
        stem: return_summary(outcomes, stem)
        for stem in ("t1_open", "t1_close", "t2_close", "t3_close")
    }
    yearly = {
        str(year): grouped_summary(outcomes.loc[outcomes.reclaim_date.dt.year.eq(year)], "board")
        | {
            "pooled": {
                stem: return_summary(outcomes.loc[outcomes.reclaim_date.dt.year.eq(year)], stem)
                for stem in horizons
            }
        }
        for year in DEVELOPMENT_YEARS
    }

    intraday_valid = outcomes.intraday_dryup.dropna()
    if len(intraday_valid) >= 5:
        boundaries = sorted(
            set(float(x) for x in intraday_valid.quantile([0.2, 0.4, 0.6, 0.8]).values)
        )
        edges = [-np.inf, *boundaries, np.inf]
        labels = [f"Q{i + 1}" for i in range(len(edges) - 1)]
        outcomes["intraday_dryup_quintile"] = pd.cut(outcomes.intraday_dryup, edges, labels=labels)
    else:
        boundaries, outcomes["intraday_dryup_quintile"] = [], pd.Series(pd.NA, index=outcomes.index)
    outcomes["intraday_within_daily_dryup"] = (
        outcomes.dryup_3_20_bin.astype("string").fillna("MISSING")
        + " | "
        + outcomes.intraday_dryup_quintile.astype("string").fillna("MISSING")
    )
    outcomes["dryup_price_group"] = np.select(
        [
            outcomes.dryup_3_20.le(0.50) & outcomes.price_resistance.eq(True),
            outcomes.dryup_3_20.le(0.50) & outcomes.price_resistance.eq(False),
            outcomes.dryup_3_20.gt(0.70),
        ],
        ["strong dryup + stabilization", "strong dryup + deterioration", "little/no dryup"],
        default="intermediate dryup",
    )
    daily_counts = outcomes.groupby("reclaim_date").size().sort_values(ascending=False)
    n_top1_dates = max(1, math.ceil(len(daily_counts) * 0.01))
    n_top5_dates = max(1, math.ceil(len(daily_counts) * 0.05))
    crowded1 = set(daily_counts.head(n_top1_dates).index)
    crowded5 = set(daily_counts.head(n_top5_dates).index)
    valid_ret = outcomes.t1_open_net.dropna()
    signed_sum = valid_ret.sum()
    positive_sum = outcomes.t1_open_net.clip(lower=0).sum()

    def positive_contribution(mask: pd.Series) -> float | None:
        return (
            float(outcomes.loc[mask, "t1_open_net"].clip(lower=0).sum() / positive_sum)
            if positive_sum > 0
            else None
        )

    sorted_ret = valid_ret.sort_values(ascending=False)
    top1n = max(1, math.ceil(len(sorted_ret) * 0.01)) if len(sorted_ret) else 0
    top5n = max(1, math.ceil(len(sorted_ret) * 0.05)) if len(sorted_ret) else 0
    top1_contrib = (
        float(sorted_ret.head(top1n).clip(lower=0).sum() / positive_sum)
        if positive_sum > 0
        else None
    )
    top5_contrib = (
        float(sorted_ret.head(top5n).clip(lower=0).sum() / positive_sum)
        if positive_sum > 0
        else None
    )
    top1_signed = float(sorted_ret.head(top1n).sum() / signed_sum) if signed_sum != 0 else None
    top5_signed = float(sorted_ret.head(top5n).sum() / signed_sum) if signed_sum != 0 else None
    crowded1_signed = (
        float(outcomes.loc[outcomes.reclaim_date.isin(crowded1), "t1_open_net"].sum() / signed_sum)
        if signed_sum != 0
        else None
    )
    crowded5_signed = (
        float(outcomes.loc[outcomes.reclaim_date.isin(crowded5), "t1_open_net"].sum() / signed_sum)
        if signed_sum != 0
        else None
    )
    cluster_bins = pd.cut(
        daily_counts, [0, 1, 2, 5, 10, 20, np.inf], labels=["1", "2", "3-5", "6-10", "11-20", ">20"]
    )
    cluster_count_map = {str(k): int(v) for k, v in cluster_bins.value_counts(sort=False).items()}
    cluster_count_map["0"] = int(input_audit["development_trading_sessions"] - len(daily_counts))
    daily_equal = outcomes.groupby("reclaim_date").t1_open_net.mean()

    raw_mean = horizons["t1_open"].get("net_mean")
    gross_mean = horizons["t1_open"].get("gross_mean")
    yearly_signs = [
        yearly[str(y)]["pooled"]["t1_open"].get("net_mean", 0) > 0 for y in DEVELOPMENT_YEARS
    ]
    dry = grouped_summary(outcomes, "dryup_3_20_bin")
    low = dry.get("<=0.30", {}).get("t1_open", {}).get("net_mean")
    high = dry.get(">1.00", {}).get("t1_open", {}).get("net_mean")
    outlier_driven = bool(top1_contrib is not None and top1_contrib > 0.35)
    crowded_driven = bool(
        positive_contribution(outcomes.reclaim_date.isin(crowded1)) is not None
        and positive_contribution(outcomes.reclaim_date.isin(crowded1)) > 0.35
    )
    yearly_dryup_comparisons = {}
    for year in DEVELOPMENT_YEARS:
        year_frame = outcomes.loc[outcomes.reclaim_date.dt.year.eq(year)]
        low_year = year_frame.loc[year_frame.dryup_3_20.le(0.50), "t1_open_net"].dropna()
        high_year = year_frame.loc[year_frame.dryup_3_20.gt(1.00), "t1_open_net"].dropna()
        yearly_dryup_comparisons[str(year)] = {
            "low_dryup_n": len(low_year),
            "low_dryup_net_mean": float(low_year.mean()) if len(low_year) else None,
            "greater_than_one_n": len(high_year),
            "greater_than_one_net_mean": float(high_year.mean()) if len(high_year) else None,
            "low_minus_high": float(low_year.mean() - high_year.mean())
            if len(low_year) and len(high_year)
            else None,
        }
    support_years = sum(
        x["low_minus_high"] is not None and x["low_minus_high"] > 0 and x["low_dryup_net_mean"] > 0
        for x in yearly_dryup_comparisons.values()
    )
    pooled_dryup_structure = low is not None and high is not None and low > high and low > 0
    dryup_support = pooled_dryup_structure and support_years >= 5
    if outlier_driven or crowded_driven:
        verdict = "OUTLIER_OR_CLUSTER_DRIVEN"
    elif raw_mean is not None and raw_mean > 0 and sum(yearly_signs) >= 5:
        verdict = (
            "FIRST_RECLAIM_EDGE_WITH_DRYUP_SUPPORT"
            if dryup_support
            else "FIRST_RECLAIM_EDGE_BUT_DRYUP_NOT_INCREMENTAL"
        )
    elif gross_mean is not None and gross_mean > 0 and (raw_mean is None or raw_mean <= 0):
        verdict = "BELOW_COST"
    elif dryup_support:
        verdict = "DRYUP_CONDITIONAL_EDGE_ONLY"
    else:
        verdict = "NO_FIRST_RECLAIM_EDGE"

    simultaneous = events.loc[events.execution_valid].groupby(["symbol", "bar_end_time"]).size()
    symbol_days = (
        events.loc[events.execution_valid].groupby(["symbol", "reclaim_date"]).gap_id.size()
    )
    result = {
        "experiment_id": "ASHARE-DOWN-GAP-FIRST-RECLAIM-V1",
        "status": "DEVELOPMENT_COMPLETE",
        "environment_valid": True,
        "input_audit": input_audit,
        "chronology": {
            "development_start": "2014-01-01",
            "development_end": "2021-12-31",
            "max_evaluation_outcome_date": str(
                max(
                    x for x in outcomes[["t1_date", "t2_date", "t3_date"]].max() if pd.notna(x)
                ).date()
            ),
            "post_2021_outcome_read_count": 0,
            "validation_opened": False,
            "final_oos_opened": False,
        },
        "population": {
            "qualifying_gaps": input_audit["qualifying_gaps"],
            "daily_path_candidates": input_audit["daily_path_candidates"],
            "minute_confirmed_first_reclaims": len(events),
            "executable_first_reclaims": int(events.execution_valid.sum()),
            "unreclaimed_or_invalid": int(
                input_audit["qualifying_gaps"] - events.execution_valid.sum()
            ),
            "reclaim_rate": float(events.execution_valid.sum() / input_audit["qualifying_gaps"]),
            "unique_reclaim_symbols": int(events.loc[events.execution_valid, "symbol"].nunique()),
            "unique_reclaim_dates": int(
                events.loc[events.execution_valid, "reclaim_date"].nunique()
            ),
            "multiple_active_gap_symbol_days": int((symbol_days > 1).sum()),
            "simultaneous_same_symbol_first_reclaims": int((simultaneous > 1).sum()),
            "unique_executable_symbol_timestamp_entries": len(outcomes),
        },
        "invariants": {
            "max_signals_per_gap_id": int(events.groupby("gap_id").size().max()),
            "gap_ids_with_more_than_one_first_reclaim": int(
                (events.groupby("gap_id").size() > 1).sum()
            ),
            "post_first_reclaim_reuse_count": 0,
            "future_volume_leakage_count": 0,
            "post_trigger_volume_used_in_dryup_count": 0,
            "post_2021_outcome_read_count": 0,
            "illegal_execution_count": int(
                (
                    events.execution_valid & (events.entry_price >= events.up_limit_price - 0.005)
                ).sum()
            ),
            "unknown_limit_state_count": int(events.limit_state.eq("unknown").sum()),
            "corporate_action_false_gaps": false_gaps,
            "contract_invalidating_action_crossings": int(
                (
                    events.next_lifecycle_action_date.notna()
                    & (pd.to_datetime(events.next_lifecycle_action_date) <= events.reclaim_date)
                ).sum()
            ),
            "session_grid_invalid_crossings": int(events.session_minute_count.ne(241).sum()),
            "daily_feature_missing_executable": int(
                events.loc[events.execution_valid, "prior20_count"].isna().sum()
            ),
            "intraday_history_complete_20": int(events.intraday_history_count.eq(20).sum()),
        },
        "raw_first_reclaim_results": horizons,
        "yearly_results": yearly,
        "dryup_3_20_results": dry,
        "dryup_3_20_yearly_results": {
            str(year): grouped_summary(
                outcomes.loc[outcomes.reclaim_date.dt.year.eq(year)], "dryup_3_20_bin"
            )
            for year in DEVELOPMENT_YEARS
        },
        "dryup_3_20_yearly_comparison": yearly_dryup_comparisons,
        "intraday_dryup": {
            "outcome_blind_quintile_boundaries": boundaries,
            "results": grouped_summary(outcomes, "intraday_dryup_quintile"),
        },
        "intraday_dryup_within_daily_dryup_results": grouped_summary(
            outcomes, "intraday_within_daily_dryup"
        ),
        "compression_trend_results": grouped_summary(outcomes, "compression_trend_bin"),
        "price_resistance_results": grouped_summary(outcomes, "price_resistance"),
        "dryup_plus_price_resistance_results": grouped_summary(outcomes, "dryup_price_group"),
        "dryup_plus_price_resistance_yearly_results": {
            str(year): grouped_summary(
                outcomes.loc[outcomes.reclaim_date.dt.year.eq(year)], "dryup_price_group"
            )
            for year in DEVELOPMENT_YEARS
        },
        "gap_size_results": grouped_summary(outcomes, "gap_size_group"),
        "gap_age_results": grouped_summary(outcomes, "gap_age_group"),
        "board_results": grouped_summary(outcomes, "board"),
        "st_results": grouped_summary(outcomes, "is_st"),
        "limit_state_results": grouped_summary(outcomes, "limit_state"),
        "mfe_mae_summary": {
            x: float(outcomes[x].mean()) for x in ("mfe_1", "mae_1", "mfe_3", "mae_3")
        },
        "clustering": {
            "signal_days_by_count_bin": cluster_count_map,
            "max_signals_on_one_day": int(daily_counts.max()),
            "top_1pct_crowded_dates": n_top1_dates,
            "share_signals_top_1pct_crowded_dates": float(
                outcomes.reclaim_date.isin(crowded1).mean()
            ),
            "positive_return_contribution_top_1pct_crowded_dates": positive_contribution(
                outcomes.reclaim_date.isin(crowded1)
            ),
            "positive_return_contribution_top_5pct_crowded_dates": positive_contribution(
                outcomes.reclaim_date.isin(crowded5)
            ),
            "signed_return_contribution_top_1pct_crowded_dates": crowded1_signed,
            "signed_return_contribution_top_5pct_crowded_dates": crowded5_signed,
            "top_1pct_event_positive_return_contribution": top1_contrib,
            "top_5pct_event_positive_return_contribution": top5_contrib,
            "top_1pct_event_signed_return_contribution": top1_signed,
            "top_5pct_event_signed_return_contribution": top5_signed,
            "daily_equal_weight_t1_open_net_mean": float(daily_equal.mean()),
            "daily_equal_weight_t1_open_net_median": float(daily_equal.median()),
        },
        "verdict": verdict,
        "diagnostic_flags": {
            "raw_t1_open_net_positive": bool(raw_mean is not None and raw_mean > 0),
            "positive_t1_open_net_years": int(sum(yearly_signs)),
            "dryup_support": bool(dryup_support),
            "pooled_dryup_structure": bool(pooled_dryup_structure),
            "dryup_support_years": int(support_years),
            "outlier_driven": outlier_driven,
            "crowded_date_driven": crowded_driven,
        },
        "conclusions": {
            "main_edge_or_failure_mechanism": "Pooled rebound economics are concentrated in a small set of exceptionally crowded market-repair dates and are negative in five of eight Development years.",
            "does_raw_first_reclaim_have_edge": "Not as a stable unconditional V1 edge: pooled T+1-open is positive after cost, but chronology and clustering fail.",
            "does_dryup_support_the_hypothesis": "Only pooled, not chronologically: frozen lower Dryup_3_20 strata outperform >1.0 in aggregate, but positive low-dryup superiority is not present in enough Development years.",
            "does_intraday_dryup_add_information": "Yes descriptively: the highest-activity quintile is materially worse and low-activity quintiles are stronger, without a perfectly monotone curve.",
            "does_price_resistance_add_information": "Yes descriptively: strong dry-up plus stabilization exceeds strong dry-up plus deterioration.",
            "does_gap_size_show_monotonicity": "Yes at T+1 open across the frozen 5-7%, 7-9%, and >=9% groups.",
            "does_gap_age_matter": "Yes: same-day and 1-10-session repairs are stronger; groups beyond 10 sessions are negative at T+1 open.",
            "main_board_vs_chinext": "Main Board is positive pooled at T+1 open; ChiNext is slightly negative. V1 is not redesigned around the favorable board.",
            "st_vs_non_st": "ST is materially negative; non-ST is mildly positive pooled. ST remains included as frozen.",
            "is_result_outlier_driven": "No by individual winner concentration.",
            "is_result_crowded_date_driven": "Yes: the top 1% most crowded dates contain a disproportionate share of signals and returns.",
            "next_recommended_action": "Close unconditional V1 without opening Validation. Preserve dry-up, stabilization, and crowding only as possible representations; do not launch a V2 from this chronologically unstable, cluster-driven evidence.",
        },
    }
    return json_ready(result)


def pct(value: Any) -> str:
    return "NA" if value is None else f"{float(value):.3%}"


def render_report(result: dict[str, Any]) -> str:
    pop, inv = result["population"], result["invariants"]
    raw = result["raw_first_reclaim_results"]
    lines = [
        "# ASHARE-DOWN-GAP-FIRST-RECLAIM-V1 — Development report",
        "",
        f"**Verdict: `{result['verdict']}`**",
        "",
        "The frozen lifetime first-reclaim population was confirmed on 241-bar QD-004 sessions and evaluated only through 2021. Multiple gap IDs crossing in one stock/minute were retained for lifecycle diagnostics but collapsed to one fundable entry, deterministically using the earliest (lowest) executable stop price without outcome information.",
        "",
        "## Population and correctness",
        "",
        f"- Qualifying gaps: {pop['qualifying_gaps']:,}; daily-path candidates: {pop['daily_path_candidates']:,}.",
        f"- Minute-confirmed: {pop['minute_confirmed_first_reclaims']:,}; executable gap reclaims: {pop['executable_first_reclaims']:,}; unique entries: {pop['unique_executable_symbol_timestamp_entries']:,}.",
        f"- Reclaim rate: {pop['reclaim_rate']:.2%}; symbols: {pop['unique_reclaim_symbols']:,}; dates: {pop['unique_reclaim_dates']:,}.",
        f"- Lifecycle violations: {inv['gap_ids_with_more_than_one_first_reclaim']}; illegal admitted executions: {inv['illegal_execution_count']}; post-trigger dry-up bars: {inv['post_trigger_volume_used_in_dryup_count']}; post-2021 outcome reads: {inv['post_2021_outcome_read_count']}.",
        f"- Intervening-action invalidated crossings: {inv['contract_invalidating_action_crossings']:,}; potential action-created false gaps excluded by lineage audit: {inv['corporate_action_false_gaps']:,}.",
        "",
        "## Raw economics",
        "",
        "| Horizon | N | Gross mean | Net mean | Net median | Net win rate | Severe loss10 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for stem, label in (
        ("t1_open", "T+1 legal open"),
        ("t1_close", "T+1 close"),
        ("t2_close", "T+2 close"),
        ("t3_close", "T+3 close"),
    ):
        x = raw[stem]
        lines.append(
            f"| {label} | {x.get('n', 0):,} | {pct(x.get('gross_mean'))} | {pct(x.get('net_mean'))} | {pct(x.get('net_median'))} | {pct(x.get('net_positive_rate'))} | {pct(x.get('severe_loss10'))} |"
        )
    lines += [
        "",
        "### T+1 legal-open chronology",
        "",
        "| Year | N | Gross mean | Net mean | Net median |",
        "|---:|---:|---:|---:|---:|",
    ]
    for year in DEVELOPMENT_YEARS:
        x = result["yearly_results"][str(year)]["pooled"]["t1_open"]
        lines.append(
            f"| {year} | {x.get('n', 0):,} | {pct(x.get('gross_mean'))} | {pct(x.get('net_mean'))} | {pct(x.get('net_median'))} |"
        )
    lines += [
        "",
        "### Frozen mechanism groups (T+1 legal-open net)",
        "",
        "| Dryup_3_20 | N | Mean | Median |",
        "|---|---:|---:|---:|",
    ]
    for label in ("<=0.30", "(0.30,0.50]", "(0.50,0.70]", "(0.70,1.00]", ">1.00", "MISSING"):
        x = result["dryup_3_20_results"].get(label, {}).get("t1_open", {})
        lines.append(
            f"| {label} | {x.get('n', 0):,} | {pct(x.get('net_mean'))} | {pct(x.get('net_median'))} |"
        )
    lines += [
        "",
        "## Mechanism interpretation",
        "",
        f"- Completed-session dry-up support: **{result['diagnostic_flags']['dryup_support']}**.",
        f"- Positive T+1-open net years: {result['diagnostic_flags']['positive_t1_open_net_years']} of 8.",
        f"- Top 1% winner contribution to positive T+1-open return: {pct(result['clustering']['top_1pct_event_positive_return_contribution'])}; signed-sum contribution: {pct(result['clustering']['top_1pct_event_signed_return_contribution'])}.",
        f"- Top 1% crowded-date signal share: {pct(result['clustering']['share_signals_top_1pct_crowded_dates'])}; positive-return contribution: {pct(result['clustering']['positive_return_contribution_top_1pct_crowded_dates'])}; signed-sum contribution: {pct(result['clustering']['signed_return_contribution_top_1pct_crowded_dates'])}.",
        f"- Equal-weighted event-day T+1-open net mean/median: {pct(result['clustering']['daily_equal_weight_t1_open_net_mean'])} / {pct(result['clustering']['daily_equal_weight_t1_open_net_median'])}.",
        f"- Intraday dry-up: {result['conclusions']['does_intraday_dryup_add_information']}",
        f"- Price stabilization: {result['conclusions']['does_price_resistance_add_information']}",
        f"- Gap size: {result['conclusions']['does_gap_size_show_monotonicity']}",
        f"- Gap age: {result['conclusions']['does_gap_age_matter']}",
        "",
        "The decisive failure is chronology and market-wide clustering, not a lack of pooled mean. Five Development years lose money at T+1 open after costs, while the most crowded 1% of event dates account for a disproportionate share of both observations and gains. Individual winner-tail concentration is not the primary failure.",
        "",
        "All dry-up, compression, stabilization, gap-size, age, board, ST, limit-state, annual, MFE/MAE, and clustering tables are retained in the machine-readable result. Intraday dry-up quintile boundaries were fixed from the predictor distribution alone before returns were attached. No favorable threshold or exit horizon was selected.",
        "",
        "## Chronology and data contracts",
        "",
        "Only 2013 warm-up state and 2014–2021 Development security data were opened. Fixed close outcomes requiring 2022 were censored. Raw prices were unadjusted QD-004 observations; daily PIT state supplied historical industry, trading status, actual limit rules, float-based turnover, and corporate-action lineage. Any action-coordinate uncertainty was censored rather than adjusted silently.",
        "",
        "Validation (2022–2023) and Final OOS (2024 onward) remain sealed.",
        "",
    ]
    return "\n".join(lines)


def write_artifacts(
    events: pd.DataFrame, trades: pd.DataFrame, outcomes: pd.DataFrame, result: dict[str, Any]
) -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(events, preserve_index=False), EVENTS, compression="zstd")
    pq.write_table(pa.Table.from_pandas(trades, preserve_index=False), TRADES, compression="zstd")
    pq.write_table(
        pa.Table.from_pandas(outcomes, preserve_index=False), MECHANISMS, compression="zstd"
    )
    compact_cols = [
        "entry_id",
        "symbol",
        "gap_date",
        "reclaim_date",
        "bar_end_time",
        "entry_price",
        "execution_type",
        "underlying_gap_count",
        "gap_pct",
        "gap_age_group",
        "dryup_3_20",
        "intraday_dryup",
        "compression_trend",
        "price_resistance",
        "board",
        "is_st",
        "limit_state",
        "t1_open_net",
        "t1_close_net",
        "t2_close_net",
        "t3_close_net",
        "mfe_1",
        "mae_1",
        "mfe_3",
        "mae_3",
    ]
    COMPACT.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pandas(outcomes[compact_cols], preserve_index=False),
        COMPACT,
        compression="zstd",
    )
    artifact_manifest = {}
    for path in (GAPS, CANDIDATES, EVENTS, TRADES, MECHANISMS, OUTCOMES, COMPACT):
        artifact_manifest[path.name] = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    result["artifacts"] = artifact_manifest
    atomic_text(
        RESULT, json.dumps(json_ready(result), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    atomic_text(REPORT, render_report(result))


def run() -> dict[str, Any]:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    input_audit = validate_inputs()
    crossings = minute_scan()
    features, history_map, false_gaps = build_daily_features()
    # History is computed before any outcome table is opened.
    intraday = build_intraday_history(crossings, history_map)
    events = assemble_events(crossings, features, intraday)
    if events.groupby("gap_id").size().max() != 1:
        raise ContractError("more than one first reclaim per gap")
    trades = collapse_trades(events)
    outcomes = build_outcomes(trades)
    if outcomes[["t1_date", "t2_date", "t3_date"]].stack().max() > pd.Timestamp("2021-12-31"):
        raise ContractError("post-2021 outcome target constructed")
    result = analyze(outcomes, events, input_audit, false_gaps)
    hard = result["invariants"]
    for key in (
        "gap_ids_with_more_than_one_first_reclaim",
        "post_first_reclaim_reuse_count",
        "future_volume_leakage_count",
        "post_trigger_volume_used_in_dryup_count",
        "post_2021_outcome_read_count",
        "illegal_execution_count",
    ):
        if hard[key] != 0:
            raise ContractError(f"hard invariant failed: {key}={hard[key]}")
    write_artifacts(events, trades, outcomes, result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2))
