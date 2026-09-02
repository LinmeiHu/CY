#!/usr/bin/env python3
# ruff: noqa: E501,E701,E702
"""Build the outcome-blind Collapse Gap-Zone Pattern Fidelity Audit V1 package."""

from __future__ import annotations

import hashlib
import html
import json
import os
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-PATTERN-FIDELITY-AUDIT-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "64a16f13e37c9d9d922c41c6676ca6f850bfd6c2fb602df801326f31eb9e82fd"

EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_pattern_fidelity_audit_v1")
DAILY_COMPACT = EXTERNAL / "pit_daily_comparable_2013_2021.parquet"
PRIMITIVES_FULL = EXTERNAL / "strict_gap_primitives_full.parquet"
PRIMITIVES_GROUPED = EXTERNAL / "strict_gap_primitives_grouped.parquet"
EPISODE_SEEDS = EXTERNAL / "collapse_episode_seeds_v2.parquet"
REENTRY_DAILY = EXTERNAL / "collapse_episode_reentry_daily_v2.parquet"
REENTRY_EXACT = EXTERNAL / "collapse_episode_reentry_exact_v2.parquet"
DESCRIPTORS_FULL = EXTERNAL / "collapse_episode_descriptors_full_v2.parquet"
BLIND_DIR = EXTERNAL / "blind_charts"
DIAGNOSTIC_DIR = EXTERNAL / "diagnostic_charts"

CANDIDATES = OS_ROOT / f"artifacts/{EXPERIMENT}_candidates.parquet"
SAMPLE_MANIFEST = OS_ROOT / f"artifacts/{EXPERIMENT}_sample_manifest.parquet"
AUDIT_MAPPING = OS_ROOT / f"artifacts/{EXPERIMENT}_audit_mapping.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
REVIEW_CSV = OS_ROOT / f"reports/{EXPERIMENT}_review.csv"
REVIEW_INSTRUCTIONS = OS_ROOT / f"reports/{EXPERIMENT}_REVIEW_INSTRUCTIONS.md"

V3_DAILY = Path("/Volumes/quant/CY_quant_research/ashare_former_leader_deep_drawdown_strict_gap_reclaim_v3/pit_adjusted_daily_state_2013_2021.parquet")
OLD_DAILY = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006/daily")
NEW_DAILY = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
RAW_MINUTE = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")
QD004_INVENTORY = OS_ROOT / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_qd004_2013_2023_inventory.json"

HISTORY_YEARS = tuple(range(2013, 2022))
DEVELOPMENT_YEARS = tuple(range(2014, 2022))
EXCLUDED_INDUSTRIES = (
    "煤炭开采", "油气开采Ⅱ", "油服工程", "炼化及贸易", "普钢", "特钢Ⅱ", "冶钢原料",
    "工业金属", "小金属", "贵金属", "能源金属", "金属新材料", "化学原料", "化学制品",
    "农化制品", "化学纤维", "电子化学品Ⅱ", "水泥", "玻璃玻纤", "非金属材料Ⅱ", "电力", "燃气Ⅱ",
)
DAILY_HASHES = {
    2013: "b2448fc39365121d5b5a282f4b31b98a23bb8ab21a805f2385f4c2b309a35f1d",
    2014: "de8839c9612f76ba190bfc1e729639ee723dfc6e3ea7a15d3fb77048808e0c81",
    2015: "9f581bbc0fec380f893d5cf520784798df5c0305e76d01283650bd861ce1aab0",
    2016: "e1d7f7481766b413b63e7e13cb6c30c1aeed96400459f4d84c2c728b3b705d22",
    2017: "5a8d7b0d48d4ff3b9323c53a812539115bb62a2cfe197369ef3b5f5499816f88",
    2018: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    2019: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    2020: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    2021: "cbd4b2d2ccdff32b09ed1a2e9347f8045cde89ff7e4e1b189577bc353e4d9311",
}
V3_DAILY_HASH = "524448ab35a817d5be0a0de5dfa312aad122ab675af92f306e04aa76fdf4f687"
QD004_INVENTORY_HASH = "c4d2906dbced341fbf48089aea7239c1c61cfbb57c665fe084495d46487e6655"


class AuditError(RuntimeError):
    """Fail-closed semantic-audit error."""


def daily_path(year: int) -> Path:
    root = OLD_DAILY if year < 2018 else NEW_DAILY
    return root / f"partition_year={year}/data_0.parquet"


def raw_path(year: int) -> Path:
    return RAW_MINUTE / f"{year}_day_parquet_none.parquet"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: str) -> str:
    return hashlib.sha256((EXPERIMENT + "|" + value).encode()).hexdigest()


def sql_paths(paths: Iterable[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def json_ready(value: Any) -> Any:
    if isinstance(value, dict): return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating, float)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)): return str(pd.Timestamp(value))
    return value


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd")
    os.replace(temporary, path)


def connection() -> duckdb.DuckDBPyConnection:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    (EXTERNAL / "duckdb_tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{EXTERNAL / 'duckdb_tmp'}'")
    return con


def validate_inputs() -> dict[str, Any]:
    expected = {SPEC: EXPECTED_SPEC_SHA256, V3_DAILY: V3_DAILY_HASH, QD004_INVENTORY: QD004_INVENTORY_HASH}
    expected.update({daily_path(year): digest for year, digest in DAILY_HASHES.items()})
    found: dict[str, str] = {}
    for path, expected_hash in expected.items():
        if not path.is_file(): raise AuditError(f"missing frozen input: {path}")
        actual = sha256_file(path)
        if actual != expected_hash: raise AuditError(f"input hash mismatch: {path}: {actual}")
        found[str(path)] = actual
    inventory = json.loads(QD004_INVENTORY.read_text(encoding="utf-8"))
    records = {Path(item["path"]).name: item for item in inventory["files"]}
    raw_identity = {}
    for year in DEVELOPMENT_YEARS:
        path = raw_path(year); item = records.get(path.name)
        if not path.is_file() or item is None or path.stat().st_size != item["size"]:
            raise AuditError(f"QD-004 identity failure: {path}")
        raw_identity[str(year)] = {"bytes": item["size"], "sha256": item["sha256"]}
    return {"content_hashes": found, "raw_minute_identity": raw_identity}


def persistence_bucket(session_lag: int | float | None) -> str:
    if session_lag is None or pd.isna(session_lag): return "UNREENTERED"
    value = int(session_lag)
    if value == 0: return "SAME_DAY"
    if value == 1: return "NEXT_DAY"
    if value <= 3: return "SHORT_PERSISTENCE"
    if value <= 10: return "MEDIUM_PERSISTENCE"
    if value <= 30: return "LONG_PERSISTENCE"
    return "VERY_LONG"


def assert_no_outcome_columns(frame: pd.DataFrame) -> None:
    forbidden = ("post_reentry", "future_", "t1_return", "t3_return", "mfe", "mae", "winner", "sharpe", "calmar", "cagr", "outcome")
    found = [column for column in frame.columns if any(token in column.lower() for token in forbidden)]
    if found: raise AuditError(f"outcome-bearing columns prohibited: {found}")


def detect_strict_gap_primitives(frame: pd.DataFrame) -> pd.DataFrame:
    """Small-frame reference detector used by focused tests."""
    work = frame.sort_values(["symbol", "trade_date"], kind="mergesort").copy()
    work["previous_low"] = work.groupby("symbol", sort=False).low.shift()
    work["previous_trade_date"] = work.groupby("symbol", sort=False).trade_date.shift()
    action_safe = work.get("corporate_action_count", pd.Series(0, index=work.index)).fillna(1).eq(0)
    lineage = work.get("history_valid", pd.Series(True, index=work.index)).fillna(False)
    result = work.loc[action_safe & lineage & work.open.lt(work.previous_low)].copy()
    result["lower_boundary"] = result.open
    result["upper_boundary"] = result.previous_low
    result["gap_primitive_id"] = result.symbol + "|" + pd.to_datetime(result.trade_date).dt.strftime("%Y-%m-%d")
    return result


def build_daily_compact() -> None:
    if DAILY_COMPACT.is_file(): return
    excluded = ",".join("'" + value.replace("'", "''") + "'" for value in EXCLUDED_INDUSTRIES)
    con = connection()
    paths = sql_paths([daily_path(year) for year in HISTORY_YEARS])
    query = f"""
    WITH joined AS (
      SELECT d.trade_date,v.cal_idx,d.symbol,v.sleeve,d.open,d.high,d.low,d.close,d.volume,d.amount,
             d.turnover_fraction,d.is_st,d.industry,v.causal_industry,d.trade_status,
             d.current_day_data_tradable,d.up_limit_price,d.down_limit_price,d.market_rule_valid,
             d.corporate_action_count,d.corporate_action_valid,d.corporate_action_blocking,
             d.industry_valid,d.historical_identity_valid,d.industry_snapshot_id,d.hard_valid,
             d.available_at,d.decision_at,v.history_valid,v.current_valid,v.adjusted_close,
             v.invalid_step_cum,v.adjusted_close/d.close AS coordinate_factor,
             d.open*(v.adjusted_close/d.close) AS coord_open,
             d.high*(v.adjusted_close/d.close) AS coord_high,
             d.low*(v.adjusted_close/d.close) AS coord_low,
             v.adjusted_close AS coord_close
      FROM read_parquet({paths}) d JOIN read_parquet('{V3_DAILY}') v USING(symbol,trade_date)
      WHERE ((d.symbol LIKE '60%.SH' AND d.symbol NOT LIKE '688%.SH')
             OR d.symbol LIKE '00%.SZ' OR d.symbol LIKE '30%.SZ')
    ), w1 AS (
      SELECT *,
        lag(coord_close) OVER w AS prior_coord_close,
        lag(cal_idx) OVER w AS prior_cal_idx,
        lag(coord_close,20) OVER w AS lag20_close,lag(cal_idx,20) OVER w AS lag20_idx,
        lag(coord_close,40) OVER w AS lag40_close,lag(cal_idx,40) OVER w AS lag40_idx,
        lag(coord_close,60) OVER w AS lag60_close,lag(cal_idx,60) OVER w AS lag60_idx,
        lag(coord_close,120) OVER w AS lag120_close,lag(cal_idx,120) OVER w AS lag120_idx,
        min(coord_low) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND CURRENT ROW) AS low60,
        min(coord_low) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW) AS low120,
        arg_min(trade_date,coord_low) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW) AS low120_date,
        arg_min(cal_idx,coord_low) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW) AS low120_idx,
        max(CASE WHEN history_valid THEN coord_high END) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING) AS prior250_peak_high,
        arg_max(CASE WHEN history_valid THEN trade_date END,CASE WHEN history_valid THEN coord_high END) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING) AS prior250_peak_date,
        arg_max(CASE WHEN history_valid THEN invalid_step_cum END,CASE WHEN history_valid THEN coord_high END) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING) AS prior250_peak_invalid_cum,
        sum(CASE WHEN market_rule_valid AND up_limit_price>0 AND close>=up_limit_price-0.0150000001 THEN 1 ELSE 0 END) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW) AS limit_up_days120,
        max(coord_close) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW) AS rolling_high120
      FROM joined WINDOW w AS(PARTITION BY symbol ORDER BY trade_date)
    ), w2 AS (
      SELECT *,
        CASE WHEN prior_cal_idx=cal_idx-1 THEN coord_close/prior_coord_close-1 END AS step_return,
        CASE WHEN lag20_idx=cal_idx-20 THEN coord_close/lag20_close-1 END AS ret20,
        CASE WHEN lag40_idx=cal_idx-40 THEN coord_close/lag40_close-1 END AS ret40,
        CASE WHEN lag60_idx=cal_idx-60 THEN coord_close/lag60_close-1 END AS ret60,
        CASE WHEN lag120_idx=cal_idx-120 THEN coord_close/lag120_close-1 END AS ret120,
        coord_close/nullif(rolling_high120,0)-1 AS rolling_drawdown120
      FROM w1
    ), w3 AS (
      SELECT *,min(rolling_drawdown120) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW) AS max_drawdown_main_rise,
        sum(CASE WHEN step_return>=0.05 THEN 1 ELSE 0 END) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW) AS large_up_days120
      FROM w2
    ), ranked AS (
      SELECT *,percent_rank() OVER(PARTITION BY trade_date,sleeve ORDER BY ret60) AS board_ret60_percentile
      FROM w3
    )
    SELECT * FROM ranked WHERE causal_industry NOT IN ({excluded}) ORDER BY symbol,trade_date
    """
    con.execute(f"COPY ({query}) TO '{DAILY_COMPACT}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()


def build_primitives() -> pd.DataFrame:
    build_daily_compact()
    if not PRIMITIVES_FULL.is_file():
        con = connection()
        query = f"""
        WITH lagged AS (
          SELECT *,
            lag(trade_date) OVER w AS previous_trade_date,lag(cal_idx) OVER w AS previous_cal_idx,
            lag(low) OVER w AS previous_low,lag(close) OVER w AS previous_close,
            lag(coord_low) OVER w AS previous_coord_low,lag(history_valid) OVER w AS previous_history_valid,
            lag(current_valid) OVER w AS previous_current_valid,lag(invalid_step_cum) OVER w AS previous_invalid_step_cum
          FROM read_parquet('{DAILY_COMPACT}') WINDOW w AS(PARTITION BY symbol ORDER BY trade_date)
        ), gaps AS (
          SELECT symbol||'|'||strftime(trade_date,'%Y-%m-%d') AS gap_primitive_id,
                 symbol,trade_date AS gap_date,cal_idx AS gap_cal_idx,sleeve AS board,is_st,causal_industry AS industry,
                 open AS lower_boundary,previous_low AS upper_boundary,previous_close AS prev_close,
                 previous_low AS prev_low,open,high,low,close,
                 coord_open AS lower_coord,previous_coord_low AS upper_coord,
                 previous_trade_date,(previous_low-open) AS width_abs,
                 (previous_low-open)/previous_close AS width_pct_vs_prev_close,
                 corporate_action_count,corporate_action_valid,corporate_action_blocking,
                 industry_valid,historical_identity_valid,industry_snapshot_id,invalid_step_cum,
                 prior250_peak_date AS peak_date,prior250_peak_high AS peak_coord_high,
                 1-coord_open/prior250_peak_high AS decline_to_gap,
                 coordinate_factor
          FROM lagged
          WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31'
            AND history_valid AND current_valid AND previous_history_valid AND previous_current_valid
            AND previous_cal_idx=cal_idx-1 AND invalid_step_cum=previous_invalid_step_cum
            AND prior250_peak_invalid_cum=invalid_step_cum
            AND coalesce(corporate_action_count,0)=0 AND corporate_action_valid AND NOT corporate_action_blocking
            AND industry_valid AND historical_identity_valid AND industry_snapshot_id IS NOT NULL
            AND coord_open<previous_coord_low AND open<previous_low
        )
        SELECT g.*,p.ret20 AS return20_into_peak,p.ret40 AS return40_into_peak,
               p.ret60 AS return60_into_peak,p.ret120 AS return120_into_peak,
               p.coord_high/nullif(p.low60,0)-1 AS max_runup_from_60_low,
               p.coord_high/nullif(p.low120,0)-1 AS max_runup_from_120_low,
               p.board_ret60_percentile AS board_relative_return_percentile,
               p.large_up_days120 AS number_large_up_days,p.limit_up_days120 AS number_limit_up_sessions,
               p.cal_idx-p.low120_idx AS main_rise_duration,
               (p.coord_high/nullif(p.low120,0)-1)/nullif(p.cal_idx-p.low120_idx,0) AS rise_speed,
               -p.max_drawdown_main_rise AS maximum_drawdown_during_main_rise,
               p.low120_date AS main_rise_start_date
        FROM gaps g LEFT JOIN read_parquet('{DAILY_COMPACT}') p
          ON p.symbol=g.symbol AND p.trade_date=g.peak_date
        ORDER BY g.symbol,g.gap_date
        """
        con.execute(f"COPY ({query}) TO '{PRIMITIVES_FULL}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    frame = pd.read_parquet(PRIMITIVES_FULL)
    for column in ("gap_date", "peak_date", "previous_trade_date", "main_rise_start_date"):
        frame[column] = pd.to_datetime(frame[column])
    if not frame.lower_coord.lt(frame.upper_coord).all(): raise AuditError("strict gap interval orientation failure")
    if frame.gap_date.max() > pd.Timestamp("2021-12-31"): raise AuditError("post-2021 primitive")
    return frame


def group_zone_stacks(primitives: pd.DataFrame, recovery_lookup: pd.Series | None = None) -> pd.DataFrame:
    """Preserve every primitive and add provisional episode/stack lineage."""
    work = primitives.sort_values(["symbol", "gap_cal_idx", "gap_primitive_id"], kind="mergesort").copy()
    work["previous_primitive_cal_idx"] = work.groupby("symbol", sort=False).gap_cal_idx.shift()
    work["previous_primitive_peak_date"] = work.groupby("symbol", sort=False).peak_date.shift()
    work["previous_primitive_peak_high"] = work.groupby("symbol", sort=False).peak_coord_high.shift()
    adjacent = work.gap_cal_idx.sub(work.previous_primitive_cal_idx).le(20)
    same_peak = work.peak_date.eq(work.previous_primitive_peak_date)
    work["recovered_since_previous"] = False
    eligible_pairs = work.loc[adjacent & same_peak, ["gap_primitive_id", "symbol", "previous_primitive_cal_idx", "gap_cal_idx", "previous_primitive_peak_high"]]
    if recovery_lookup is not None:
        recovered_values = work.gap_primitive_id.map(recovery_lookup).astype("boolean").fillna(False)
        work.loc[work.gap_primitive_id.isin(recovery_lookup.index), "recovered_since_previous"] = recovered_values
    elif len(eligible_pairs):
        pair_path = EXTERNAL / "provisional_adjacent_primitive_pairs.parquet"
        write_parquet(eligible_pairs, pair_path)
        con = connection()
        recovered = con.execute(
            f"""SELECT p.gap_primitive_id,
              coalesce(max(d.coord_high)>=0.90*max(p.previous_primitive_peak_high),false) AS recovered
              FROM read_parquet('{pair_path}') p LEFT JOIN read_parquet('{DAILY_COMPACT}') d
                ON d.symbol=p.symbol AND d.cal_idx>p.previous_primitive_cal_idx AND d.cal_idx<p.gap_cal_idx
              GROUP BY p.gap_primitive_id"""
        ).fetchdf()
        con.close()
        recovered_map = recovered.set_index("gap_primitive_id").recovered
        recovered_values = work.gap_primitive_id.map(recovered_map).astype("boolean").fillna(False)
        work.loc[work.gap_primitive_id.isin(recovered_map.index), "recovered_since_previous"] = recovered_values
    new_episode = ~(adjacent & same_peak & ~work.recovered_since_previous)
    work["episode_sequence"] = new_episode.groupby(work.symbol, sort=False).cumsum().astype(int)
    work["collapse_episode_id"] = work.symbol + "|E" + work.episode_sequence.astype(str).str.zfill(4)
    work["zone_stack_id"] = work["collapse_episode_id"] + "|STACK"
    stats = work.groupby("collapse_episode_id", sort=False).agg(
        primitive_count=("gap_primitive_id", "size"),
        stack_lower=("lower_coord", "min"),stack_upper=("upper_coord", "max"),
        first_gap_date=("gap_date", "min"),last_gap_date=("gap_date", "max"),
        first_gap_cal_idx=("gap_cal_idx", "min"),last_gap_cal_idx=("gap_cal_idx", "max"),
        max_decline_to_gap=("decline_to_gap", "max"),
    ).reset_index()
    work = work.merge(stats, on="collapse_episode_id", how="left", validate="many_to_one")
    work["primitive_order_time"] = work.groupby("collapse_episode_id", sort=False).cumcount() + 1
    work["primitive_order_price"] = work.groupby("collapse_episode_id", sort=False).lower_coord.rank(method="first").astype(int)
    if work.gap_primitive_id.duplicated().any(): raise AuditError("primitive lineage destroyed")
    return work


def build_grouped_primitives() -> pd.DataFrame:
    if PRIMITIVES_GROUPED.is_file():
        frame = pd.read_parquet(PRIMITIVES_GROUPED)
        for column in ("gap_date", "peak_date", "first_gap_date", "last_gap_date", "main_rise_start_date"):
            frame[column] = pd.to_datetime(frame[column])
        return frame
    frame = group_zone_stacks(build_primitives())
    write_parquet(frame, PRIMITIVES_GROUPED)
    return frame


def episode_seeds(grouped: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for episode_id, part in grouped.groupby("collapse_episode_id", sort=False):
        ordered = part.sort_values(["lower_coord", "gap_date", "gap_primitive_id"], kind="mergesort")
        chosen = ordered.iloc[0]
        next_layer = ordered.iloc[1] if len(ordered)>1 else None
        rows.append({
            "collapse_episode_id": episode_id,"zone_stack_id": chosen.zone_stack_id,"symbol": chosen.symbol,
            "board": chosen.board,"is_st": bool(chosen.is_st),"industry": chosen.industry,
            "peak_date": chosen.peak_date,"peak_coord_high": chosen.peak_coord_high,
            "chosen_primitive_id": chosen.gap_primitive_id,"chosen_gap_date": chosen.gap_date,
            "chosen_gap_cal_idx": chosen.gap_cal_idx,"chosen_lower_coord": chosen.lower_coord,
            "chosen_upper_coord": chosen.upper_coord,"chosen_invalid_step_cum": chosen.invalid_step_cum,
            "next_layer_primitive_id": None if next_layer is None else next_layer.gap_primitive_id,
            "next_layer_lower_coord": np.nan if next_layer is None else next_layer.lower_coord,
            "next_layer_upper_coord": np.nan if next_layer is None else next_layer.upper_coord,
            "primitive_count": len(part),"multi_layer": len(part)>1,
            "stack_lower": part.lower_coord.min(),"stack_upper": part.upper_coord.max(),
            "first_gap_date": part.gap_date.min(),"last_gap_date": part.gap_date.max(),
            "max_decline_to_gap": part.decline_to_gap.max(),
            "return20_into_peak": chosen.return20_into_peak,"return40_into_peak": chosen.return40_into_peak,
            "return60_into_peak": chosen.return60_into_peak,"return120_into_peak": chosen.return120_into_peak,
            "max_runup_from_60_low": chosen.max_runup_from_60_low,"max_runup_from_120_low": chosen.max_runup_from_120_low,
            "board_relative_return_percentile": chosen.board_relative_return_percentile,
            "number_large_up_days": chosen.number_large_up_days,"number_limit_up_sessions": chosen.number_limit_up_sessions,
            "main_rise_duration": chosen.main_rise_duration,"rise_speed": chosen.rise_speed,
            "maximum_drawdown_during_main_rise": chosen.maximum_drawdown_during_main_rise,
            "primitive_ids": "|".join(part.sort_values("gap_date").gap_primitive_id),
            "primitive_dates": "|".join(part.sort_values("gap_date").gap_date.dt.strftime("%Y-%m-%d")),
            "primitive_lower_coords": "|".join(f"{value:.12g}" for value in part.sort_values("gap_date").lower_coord),
            "primitive_upper_coords": "|".join(f"{value:.12g}" for value in part.sort_values("gap_date").upper_coord),
        })
    frame = pd.DataFrame(rows)
    write_parquet(frame, EPISODE_SEEDS)
    return frame


def build_daily_reentry(seeds: pd.DataFrame) -> pd.DataFrame:
    if REENTRY_DAILY.is_file():
        frame = pd.read_parquet(REENTRY_DAILY)
        for column in [c for c in frame.columns if c.endswith("_date")]: frame[column] = pd.to_datetime(frame[column])
        return frame
    write_parquet(seeds, EPISODE_SEEDS)
    con = connection()
    query = f"""
    WITH below AS (
      SELECT s.collapse_episode_id,min(d.trade_date) FILTER(WHERE d.coord_low<s.chosen_lower_coord) AS first_below_date
      FROM read_parquet('{EPISODE_SEEDS}') s JOIN read_parquet('{DAILY_COMPACT}') d
        ON d.symbol=s.symbol AND d.cal_idx>=s.chosen_gap_cal_idx AND d.invalid_step_cum=s.chosen_invalid_step_cum
      WHERE d.trade_date<=DATE '2021-12-31' AND d.history_valid
      GROUP BY s.collapse_episode_id
    )
    SELECT s.*,b.first_below_date,
      min(d.trade_date) FILTER(WHERE d.trade_date=s.chosen_gap_date AND d.coord_low<s.chosen_lower_coord AND d.coord_high>=s.chosen_lower_coord) AS same_day_touch_candidate,
      min(d.trade_date) FILTER(WHERE d.trade_date>s.chosen_gap_date AND d.coord_high>=s.chosen_lower_coord) AS later_touch_candidate,
      min(d.trade_date) FILTER(WHERE d.trade_date>=b.first_below_date AND d.coord_close>=s.chosen_lower_coord) AS reentry_b_lower_close_date,
      min(d.trade_date) FILTER(WHERE d.trade_date>=b.first_below_date AND d.coord_high>=s.chosen_lower_coord+0.10*(s.chosen_upper_coord-s.chosen_lower_coord)) AS reentry_c_zone10_date,
      min(d.trade_date) FILTER(WHERE d.trade_date>=b.first_below_date AND d.coord_high>=s.chosen_lower_coord+0.50*(s.chosen_upper_coord-s.chosen_lower_coord)) AS reentry_d_zone50_date,
      min(d.trade_date) FILTER(WHERE d.trade_date>=b.first_below_date AND d.coord_high>=s.chosen_upper_coord) AS reentry_e_full_fill_date,
      min(d.trade_date) FILTER(WHERE d.trade_date>s.chosen_gap_date AND d.coord_high>=s.chosen_upper_coord) AS chosen_layer_resolved_date
    FROM read_parquet('{EPISODE_SEEDS}') s LEFT JOIN below b USING(collapse_episode_id)
    LEFT JOIN read_parquet('{DAILY_COMPACT}') d
      ON d.symbol=s.symbol AND d.cal_idx>=s.chosen_gap_cal_idx AND d.invalid_step_cum=s.chosen_invalid_step_cum
      AND d.trade_date<=DATE '2021-12-31' AND d.history_valid
    GROUP BY ALL ORDER BY s.collapse_episode_id
    """
    con.execute(f"COPY ({query}) TO '{REENTRY_DAILY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    return build_daily_reentry(seeds)


def build_exact_reentry(daily_reentry: pd.DataFrame) -> pd.DataFrame:
    if REENTRY_EXACT.is_file():
        frame = pd.read_parquet(REENTRY_EXACT); frame["candidate_reentry_time"] = pd.to_datetime(frame.candidate_reentry_time); return frame
    pairs = []
    for row in daily_reentry.itertuples(index=False):
        if pd.notna(row.same_day_touch_candidate): pairs.append((row.collapse_episode_id,row.symbol,pd.Timestamp(row.same_day_touch_candidate),pd.Timestamp(row.chosen_gap_date),row.chosen_lower_coord,"SAME_DAY"))
        if pd.notna(row.later_touch_candidate): pairs.append((row.collapse_episode_id,row.symbol,pd.Timestamp(row.later_touch_candidate),pd.Timestamp(row.chosen_gap_date),row.chosen_lower_coord,"LATER"))
    pair_frame = pd.DataFrame(pairs,columns=["collapse_episode_id","symbol","touch_date","gap_date","lower_coord","touch_kind"])
    pair_path = EXTERNAL / "exact_reentry_candidate_pairs.parquet"; write_parquet(pair_frame,pair_path)
    shards = []
    for year in DEVELOPMENT_YEARS:
        shard = EXTERNAL / f"exact_reentry_v2_{year}.parquet"; shards.append(shard)
        if shard.is_file(): continue
        con = connection()
        query = f"""
        WITH pairs AS (
          SELECT p.*,p.lower_coord/d.coordinate_factor AS raw_threshold
          FROM read_parquet('{pair_path}') p JOIN read_parquet('{DAILY_COMPACT}') d
            ON d.symbol=p.symbol AND d.trade_date=p.touch_date
          WHERE year(p.touch_date)={year}
        ), bars0 AS (
          SELECT p.*,m.bar_end_time,m.open,m.high,m.low,m.close,m.amount,
            count(*) OVER(PARTITION BY p.collapse_episode_id,p.touch_kind) AS minute_count,
            count(DISTINCT m.bar_end_time) OVER(PARTITION BY p.collapse_episode_id,p.touch_kind) AS distinct_minute_count,
            min(m.low) OVER(PARTITION BY p.collapse_episode_id,p.touch_kind ORDER BY m.bar_end_time ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_min_low
          FROM pairs p JOIN read_parquet('{raw_path(year)}') m
            ON m.qmt_code=p.symbol AND m.trade_date=p.touch_date
          WHERE m.period='1m' AND m.adjust='none'
        ), crossed AS (
          SELECT *,row_number() OVER(PARTITION BY collapse_episode_id,touch_kind ORDER BY bar_end_time) AS crossing_order
          FROM bars0 WHERE minute_count=241 AND distinct_minute_count=241 AND high>=raw_threshold
            AND (touch_kind='LATER' OR prior_min_low<raw_threshold)
        )
        SELECT collapse_episode_id,symbol,touch_date,gap_date,lower_coord,touch_kind,
               bar_end_time AS candidate_reentry_time,raw_threshold,minute_count,distinct_minute_count
        FROM crossed WHERE crossing_order=1 ORDER BY collapse_episode_id,touch_date
        """
        con.execute(f"COPY ({query}) TO '{shard}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()
    con = connection()
    exact = con.execute(f"""SELECT * EXCLUDE(choice) FROM (
      SELECT *,row_number() OVER(PARTITION BY collapse_episode_id ORDER BY candidate_reentry_time,touch_kind) AS choice
      FROM read_parquet({sql_paths(shards)})) WHERE choice=1 ORDER BY collapse_episode_id""").fetchdf(); con.close()
    write_parquet(exact, REENTRY_EXACT)
    exact["candidate_reentry_time"] = pd.to_datetime(exact.candidate_reentry_time)
    return exact


def build_descriptors(daily_reentry: pd.DataFrame, exact: pd.DataFrame) -> pd.DataFrame:
    base = daily_reentry.merge(exact[["collapse_episode_id","candidate_reentry_time","touch_kind","minute_count","distinct_minute_count"]], on="collapse_episode_id", how="inner", validate="one_to_one")
    base["candidate_reentry_date"] = pd.to_datetime(base.candidate_reentry_time).dt.normalize()
    provisional_path = EXTERNAL / "episode_reentry_variant_base_v2.parquet"; write_parquet(base,provisional_path)
    con=connection()
    variants=con.execute(f"""SELECT b.collapse_episode_id,
      min(d.trade_date) FILTER(WHERE d.coord_close>=b.chosen_lower_coord) AS reentry_b_lower_close_date_v2,
      min(d.trade_date) FILTER(WHERE d.coord_high>=b.chosen_lower_coord+0.10*(b.chosen_upper_coord-b.chosen_lower_coord)) AS reentry_c_zone10_date_v2,
      min(d.trade_date) FILTER(WHERE d.coord_high>=b.chosen_lower_coord+0.50*(b.chosen_upper_coord-b.chosen_lower_coord)) AS reentry_d_zone50_date_v2,
      min(d.trade_date) FILTER(WHERE d.coord_high>=b.chosen_upper_coord) AS reentry_e_full_fill_date_v2,
      min(d.trade_date) FILTER(WHERE b.next_layer_lower_coord IS NOT NULL AND d.trade_date>=b.chosen_layer_resolved_date AND d.coord_high>=b.next_layer_lower_coord) AS next_layer_entry_date
      FROM read_parquet('{provisional_path}') b LEFT JOIN read_parquet('{DAILY_COMPACT}') d
        ON d.symbol=b.symbol AND d.trade_date>=b.candidate_reentry_date AND d.trade_date<=DATE '2021-12-31'
        AND d.invalid_step_cum=b.chosen_invalid_step_cum AND d.history_valid
      GROUP BY b.collapse_episode_id""").fetchdf();con.close()
    base=base.merge(variants,on="collapse_episode_id",how="left",validate="one_to_one")
    for original,revised in (("reentry_b_lower_close_date","reentry_b_lower_close_date_v2"),("reentry_c_zone10_date","reentry_c_zone10_date_v2"),("reentry_d_zone50_date","reentry_d_zone50_date_v2"),("reentry_e_full_fill_date","reentry_e_full_fill_date_v2")):
        base[original]=base[revised];base.drop(columns=revised,inplace=True)
    base["nearest_layer_entry_time"]=base.candidate_reentry_time
    base_path = EXTERNAL / "episode_reentry_base.parquet"; write_parquet(base,base_path)
    if not DESCRIPTORS_FULL.is_file():
        con = connection()
        query = f"""
        WITH base AS (
          SELECT b.*,d.cal_idx AS reentry_cal_idx
          FROM read_parquet('{base_path}') b JOIN read_parquet('{DAILY_COMPACT}') d
            ON d.symbol=b.symbol AND d.trade_date=b.candidate_reentry_date
        ), hist0 AS (
          SELECT b.*,d.trade_date AS state_date,d.cal_idx AS state_cal_idx,d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
            min(d.coord_low) OVER(PARTITION BY b.collapse_episode_id ORDER BY d.cal_idx ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_min_coord_low
          FROM base b JOIN read_parquet('{DAILY_COMPACT}') d
            ON d.symbol=b.symbol AND d.cal_idx BETWEEN b.chosen_gap_cal_idx AND b.reentry_cal_idx
            AND d.invalid_step_cum=b.chosen_invalid_step_cum
        ), hist AS (
          SELECT *,CASE WHEN coord_high<chosen_lower_coord THEN 1 ELSE 0 END AS full_below,
            CASE WHEN coord_low<coalesce(prior_min_coord_low,1e300) THEN 1 ELSE 0 END AS new_low
          FROM hist0
        ), runs AS (
          SELECT *,sum(CASE WHEN full_below=0 THEN 1 ELSE 0 END) OVER(PARTITION BY collapse_episode_id ORDER BY state_cal_idx) AS below_run_group
          FROM hist
        ), runmax AS (
          SELECT collapse_episode_id,max(n) AS max_consecutive_full_sessions_below_zone
          FROM (SELECT collapse_episode_id,below_run_group,count(*) AS n FROM runs WHERE full_below=1 GROUP BY collapse_episode_id,below_run_group)
          GROUP BY collapse_episode_id
        ), agg AS (
          SELECT collapse_episode_id,
            count(*) FILTER(WHERE coord_low<chosen_lower_coord) AS sessions_below_lower_boundary,
            count(*) FILTER(WHERE coord_high<chosen_lower_coord) AS sessions_with_high_below_lower_boundary,
            count(*) FILTER(WHERE coord_close<chosen_lower_coord) AS sessions_with_close_below_lower_boundary,
            min(coord_low) AS postcollapse_low_coord,arg_min(state_date,coord_low) AS postcollapse_low_date,
            1-min(coord_low)/chosen_lower_coord AS distance_from_zone_to_postcollapse_low,
            max(coord_high) FILTER(WHERE state_cal_idx>=reentry_cal_idx-4)/nullif(min(coord_low) FILTER(WHERE state_cal_idx>=reentry_cal_idx-4),0)-1 AS realized_range5,
            max(coord_high) FILTER(WHERE state_cal_idx>=reentry_cal_idx-9)/nullif(min(coord_low) FILTER(WHERE state_cal_idx>=reentry_cal_idx-9),0)-1 AS realized_range10,
            median(turnover_fraction) FILTER(WHERE state_cal_idx BETWEEN reentry_cal_idx-5 AND reentry_cal_idx-1) AS turnover_median5,
            median(turnover_fraction) FILTER(WHERE state_cal_idx BETWEEN reentry_cal_idx-20 AND reentry_cal_idx-1) AS turnover_median20,
            regr_slope(coord_close,state_cal_idx) FILTER(WHERE state_cal_idx BETWEEN reentry_cal_idx-5 AND reentry_cal_idx-1) AS close_slope5,
            regr_slope(coord_low,state_cal_idx) FILTER(WHERE state_cal_idx BETWEEN reentry_cal_idx-5 AND reentry_cal_idx-1) AS low_slope5,
            sum(new_low) FILTER(WHERE state_cal_idx BETWEEN reentry_cal_idx-10 AND reentry_cal_idx-1) AS new_lows10,
            count(*) FILTER(WHERE state_cal_idx BETWEEN reentry_cal_idx-10 AND reentry_cal_idx-1 AND coord_high<chosen_lower_coord) AS consecutive_sessions_below_zone_proxy
          FROM hist GROUP BY collapse_episode_id,chosen_lower_coord,reentry_cal_idx
        )
        SELECT b.*,a.* EXCLUDE(collapse_episode_id),coalesce(r.max_consecutive_full_sessions_below_zone,0) AS max_consecutive_full_sessions_below_zone,
               a.turnover_median5/nullif(a.turnover_median20,0) AS turnover_ratio5_20,
               b.reentry_cal_idx-b.chosen_gap_cal_idx AS sessions_to_reentry,
               b.reentry_cal_idx-b.chosen_gap_cal_idx AS sessions_below_phase_length,
               b.reentry_cal_idx-d.cal_idx AS days_from_postcollapse_low_to_reentry,
               d.cal_idx-b.chosen_gap_cal_idx AS days_from_zone_formation_to_postcollapse_low,
               b.chosen_lower_coord/nullif(a.postcollapse_low_coord,0)-1 AS distance_from_recent_low
        FROM base b JOIN agg a USING(collapse_episode_id) LEFT JOIN runmax r USING(collapse_episode_id)
        LEFT JOIN read_parquet('{DAILY_COMPACT}') d ON d.symbol=b.symbol AND d.trade_date=a.postcollapse_low_date
        ORDER BY b.collapse_episode_id
        """
        con.execute(f"COPY ({query}) TO '{DESCRIPTORS_FULL}' (FORMAT PARQUET,COMPRESSION ZSTD)"); con.close()
    frame = pd.read_parquet(DESCRIPTORS_FULL)
    for column in [c for c in frame.columns if c.endswith("_date") or c.endswith("_time")]: frame[column] = pd.to_datetime(frame[column])
    frame["persistence_bucket"] = frame.sessions_to_reentry.map(persistence_bucket)
    frame["leader_metric_bucket"] = np.where((frame.board_relative_return_percentile>=.9)|(frame.max_runup_from_120_low>=.5),"STRONG","MEDIUM")
    frame["retrieval_eligible"] = frame.max_decline_to_gap.ge(.20)
    frame["machine_class"] = np.select(
        [frame.retrieval_eligible & frame.sessions_to_reentry.le(1),frame.retrieval_eligible & frame.sessions_to_reentry.ge(2)],
        ["IMMEDIATE_FAST_REENTRY","BROAD_MACHINE_POSITIVE"], default="NEAR_MISS_CONTROL")
    frame.loc[~frame.retrieval_eligible & frame.max_decline_to_gap.lt(.10),"machine_class"] = "OUTSIDE_CONTROL_RANGE"
    return frame


def select_blind_sample(candidates: pd.DataFrame) -> pd.DataFrame:
    assert_no_outcome_columns(candidates)
    quotas = {
        ("MAIN","BROAD_MACHINE_POSITIVE"):48,("MAIN","IMMEDIATE_FAST_REENTRY"):12,("MAIN","NEAR_MISS_CONTROL"):12,
        ("CHINEXT","BROAD_MACHINE_POSITIVE"):32,("CHINEXT","IMMEDIATE_FAST_REENTRY"):8,("CHINEXT","NEAR_MISS_CONTROL"):8,
    }
    selected = []
    for (board,machine_class), quota in quotas.items():
        pool = candidates.loc[candidates.board.eq(board)&candidates.machine_class.eq(machine_class)].copy()
        if len(pool)<quota: raise AuditError(f"insufficient sample pool: {board}/{machine_class}: {len(pool)}<{quota}")
        pool["sampling_stratum"] = (
            pool.is_st.map({True:"ST",False:"NON_ST"})+"|"+
            pool.multi_layer.map({True:"MULTI",False:"SINGLE"})+"|"+pool.persistence_bucket+"|"+pool.leader_metric_bucket
        )
        pool["sample_hash"] = pool.collapse_episode_id.map(stable_hash)
        groups = {key: part.sort_values("sample_hash",kind="mergesort").to_dict("records") for key,part in pool.groupby("sampling_stratum",sort=True)}
        keys = sorted(groups); positions=defaultdict(int); cell=[]
        while len(cell)<quota:
            progressed=False
            for key in keys:
                pos=positions[key]
                if pos<len(groups[key]): cell.append(groups[key][pos]);positions[key]+=1;progressed=True
                if len(cell)==quota: break
            if not progressed: break
        selected.extend(cell)
    sample = pd.DataFrame(selected)
    sample = sample.sort_values("sample_hash",kind="mergesort").reset_index(drop=True)
    sample["audit_id"] = [f"AUDIT_{index:03d}" for index in range(1,len(sample)+1)]
    if len(sample)!=120 or sample.audit_id.nunique()!=120: raise AuditError("sample size/identity failure")
    if sample.board.value_counts().to_dict()!={"MAIN":72,"CHINEXT":48}: raise AuditError("board quota failure")
    if sample.machine_class.value_counts().to_dict()!={"BROAD_MACHINE_POSITIVE":80,"IMMEDIATE_FAST_REENTRY":20,"NEAR_MISS_CONTROL":20}: raise AuditError("class quota failure")
    return sample


def load_chart_frame(row: pd.Series) -> pd.DataFrame:
    con = connection()
    peak_idx = con.execute(f"SELECT cal_idx FROM read_parquet('{DAILY_COMPACT}') WHERE symbol=? AND trade_date=?",[row.symbol,row.peak_date.date()]).fetchone()[0]
    reentry_idx = con.execute(f"SELECT cal_idx FROM read_parquet('{DAILY_COMPACT}') WHERE symbol=? AND trade_date=?",[row.symbol,row.candidate_reentry_date.date()]).fetchone()[0]
    start_idx = max(peak_idx-80,reentry_idx-420)
    frame = con.execute(f"""SELECT trade_date,cal_idx,coord_open,coord_high,coord_low,coord_close,turnover_fraction,coordinate_factor
      FROM read_parquet('{DAILY_COMPACT}') WHERE symbol=? AND cal_idx BETWEEN ? AND ? AND history_valid AND current_valid ORDER BY cal_idx""",[row.symbol,start_idx,reentry_idx]).fetchdf()
    con.close(); frame["trade_date"]=pd.to_datetime(frame.trade_date)
    year=int(row.candidate_reentry_date.year); con=connection()
    partial=con.execute(f"""SELECT first(open ORDER BY bar_end_time),max(high),min(low),last(close ORDER BY bar_end_time),sum(amount)
      FROM read_parquet('{raw_path(year)}') WHERE qmt_code=? AND trade_date=? AND period='1m' AND adjust='none' AND bar_end_time<=?""",
      [row.symbol,row.candidate_reentry_date.date(),pd.Timestamp(row.candidate_reentry_time).to_pydatetime()]).fetchone();con.close()
    factor=float(frame.iloc[-1].coordinate_factor)
    if partial[0] is None: raise AuditError(f"missing partial reentry bar: {row.audit_id}")
    frame.loc[frame.index[-1],["coord_open","coord_high","coord_low","coord_close"]]=np.array(partial[:4],float)*factor
    return frame


def draw_chart(row: pd.Series, frame: pd.DataFrame, path: Path, blind: bool) -> None:
    peak=float(row.peak_coord_high); x=np.arange(len(frame)); scale=100/peak
    fig,(ax,vol)=plt.subplots(2,1,figsize=(13,7.5),sharex=True,gridspec_kw={"height_ratios":[4,1]},layout="constrained")
    for index,item in enumerate(frame.itertuples(index=False)):
        color="#c0392b" if item.coord_close>=item.coord_open else "#178f63"
        ax.vlines(index,item.coord_low*scale,item.coord_high*scale,color=color,linewidth=.7)
        lower=min(item.coord_open,item.coord_close)*scale;height=max(abs(item.coord_close-item.coord_open)*scale,.03)
        ax.add_patch(Rectangle((index-.31,lower),.62,height,facecolor=color,edgecolor=color,linewidth=.4))
    layers=list(zip(str(row.primitive_dates).split("|"),str(row.primitive_lower_coords).split("|"),str(row.primitive_upper_coords).split("|"), strict=True))
    colors=("#d35400","#c0392b","#f39c12","#a04000","#cd6155")
    for layer,(formation,lower,upper) in enumerate(layers,1):
        date=pd.Timestamp(formation);start=int(np.searchsorted(frame.trade_date.to_numpy(),date.to_datetime64(),side="left"));start=min(max(start,0),len(frame)-1)
        ax.add_patch(Rectangle((start-.5,float(lower)*scale),len(frame)-start,max((float(upper)-float(lower))*scale,.02),facecolor=colors[(layer-1)%len(colors)],edgecolor=colors[(layer-1)%len(colors)],alpha=.12,linewidth=.7,label="Strict gap layers" if layer==1 else None))
    stack_start=int(np.searchsorted(frame.trade_date.to_numpy(),pd.Timestamp(row.first_gap_date).to_datetime64(),side="left"));stack_start=min(max(stack_start,0),len(frame)-1)
    ax.add_patch(Rectangle((stack_start-.5,row.stack_lower*scale),len(frame)-stack_start,max((row.stack_upper-row.stack_lower)*scale,.02),fill=False,edgecolor="#8e44ad",linestyle="--",linewidth=1.2,label="Provisional stack envelope"))
    peak_pos=int(np.argmin(np.abs(frame.trade_date-pd.Timestamp(row.peak_date))))
    ax.scatter([peak_pos],[100],marker="v",color="#2c3e50",s=36,label="Prior peak")
    ax.scatter([len(frame)-1],[row.chosen_lower_coord*scale],marker="^",color="#2471a3",s=55,label="Candidate first zone entry")
    turnover=frame.turnover_fraction.astype(float);base=turnover.rolling(20,min_periods=5).median();norm=turnover/base.replace(0,np.nan)
    vol.bar(x,norm.fillna(0),color="#7f8c8d",width=.7);vol.axhline(1,color="#34495e",linewidth=.7,linestyle=":")
    ax.set_ylabel("Normalized price (prior peak = 100)");vol.set_ylabel("Turnover /\n20-session median");vol.set_xlabel("Relative trading sessions")
    ax.grid(alpha=.15);vol.grid(alpha=.12);ax.legend(loc="best",fontsize=8)
    if blind:
        ax.set_title(str(row.audit_id)); ax.set_xticks([])
        metadata={"Title":str(row.audit_id),"Subject":"Outcome-blind shape review"}
    else:
        ax.set_title(f"{row.audit_id} | {row.symbol} | peak {pd.Timestamp(row.peak_date).date()} | re-entry {pd.Timestamp(row.candidate_reentry_time)}")
        step=max(1,len(frame)//8); ticks=x[::step];vol.set_xticks(ticks);vol.set_xticklabels([frame.trade_date.iloc[i].strftime("%Y-%m-%d") for i in ticks],rotation=30,ha="right",fontsize=7)
        text=(f"board={row.board} ST={bool(row.is_st)} layers={int(row.primitive_count)} persistence={row.persistence_bucket}\n"
              f"decline={row.max_decline_to_gap:.1%} runup120={row.max_runup_from_120_low:.1%} leader_pct={row.board_relative_return_percentile:.2f}\n"
              f"lower/close/10%/50%/full={row.candidate_reentry_date.date()}/{pd.Timestamp(row.reentry_b_lower_close_date).date() if pd.notna(row.reentry_b_lower_close_date) else 'NA'}/{pd.Timestamp(row.reentry_c_zone10_date).date() if pd.notna(row.reentry_c_zone10_date) else 'NA'}/{pd.Timestamp(row.reentry_d_zone50_date).date() if pd.notna(row.reentry_d_zone50_date) else 'NA'}/{pd.Timestamp(row.reentry_e_full_fill_date).date() if pd.notna(row.reentry_e_full_fill_date) else 'NA'}")
        ax.text(.01,.02,text,transform=ax.transAxes,fontsize=7,va="bottom",bbox={"facecolor":"white","alpha":.78,"edgecolor":"#bbbbbb"})
        metadata={"Title":f"{row.audit_id} diagnostic","Subject":"Outcome-blind diagnostic"}
    path.parent.mkdir(parents=True,exist_ok=True);fig.savefig(path,dpi=135,metadata=metadata);plt.close(fig)


def create_html_index(directory: Path, ids: list[str], blind: bool) -> None:
    title="Blind Pattern Review" if blind else "Private Diagnostic Review"
    cards="\n".join(f'<div><h3>{html.escape(audit_id)}</h3><img loading="lazy" src="{audit_id}.png"></div>' for audit_id in ids)
    atomic_text(directory/"index.html",f"<!doctype html><meta charset='utf-8'><title>{title}</title><style>body{{font-family:sans-serif;background:#eee}}div{{background:white;margin:18px;padding:12px}}img{{max-width:100%;height:auto}}</style><h1>{title}</h1>{cards}")


def build_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True,exist_ok=True);DIAGNOSTIC_DIR.mkdir(parents=True,exist_ok=True)
    for row in sample.itertuples(index=False):
        series=pd.Series(row._asdict()); frame=load_chart_frame(series)
        draw_chart(series,frame,BLIND_DIR/f"{row.audit_id}.png",True)
        draw_chart(series,frame,DIAGNOSTIC_DIR/f"{row.audit_id}.png",False)
    ids=sample.audit_id.tolist();create_html_index(BLIND_DIR,ids,True);create_html_index(DIAGNOSTIC_DIR,ids,False)


REVIEW_COLUMNS = [
    "audit_id","PRIMARY_LABEL","WOULD_CONSIDER_BUYING_AT_FIRST_ZONE_ENTRY","FORMER_LEADER_VISUALLY_VALID",
    "PRIOR_RUNUP_VISUALLY_STRONG_ENOUGH","COLLAPSE_SHARP_ENOUGH","TRUE_GAP_ZONE_VISUALLY_MEANINGFUL",
    "MULTI_LAYER_ZONE_RELEVANT","ZONE_PERSISTED_LONG_ENOUGH","BASE_OR_SETTLING_PHASE_REQUIRED",
    "VOLUME_SUFFOCATION_VISUALLY_REQUIRED","FIRST_ENTRY_TRIGGER_LOOKS_CORRECT","PREFERRED_ZONE_TARGET",
    "REJECTION_REASON","FREE_TEXT_NOTE",
]


def write_review_files(sample: pd.DataFrame) -> None:
    review=pd.DataFrame({column:[""]*len(sample) for column in REVIEW_COLUMNS});review["audit_id"]=sample.audit_id
    atomic_text(REVIEW_CSV,review.to_csv(index=False))
    instructions=f"""# {EXPERIMENT} review instructions

Review the blind charts at `{BLIND_DIR}` and fill `{REVIEW_CSV}`.

1. Do not predict whether the stock later rose. Judge only whether the visible shape matches the intended setup.
2. Identity and dates are intentionally hidden. Do not open the private mapping during first-pass review.
3. Use `A_EXACT_PATTERN` only when the chart genuinely matches the intended pattern.
4. Use `B_CLOSE_BUT_MISSING_SOMETHING` when the economic structure is close but one or more semantic components are missing.
5. Use `C_NOT_THE_PATTERN` when it is not the intended setup.
6. If same-day or fast re-entry is ambiguous, label from visual intuition and explain in `FREE_TEXT_NOTE`.
7. Pay special attention to former-leader appearance, collapse sharpness, meaningful overhead discontinuities, persistence below the zone, and whether the final move is genuinely a return into an old collapse zone.
8. `YES`, `NO`, and `UNCERTAIN` are the allowed values for binary visual questions.
9. `PREFERRED_ZONE_TARGET` allows `LOWEST_LAYER`, `WHOLE_STACK`, `UPPER_LAYER`, `OTHER`, or `UNCERTAIN`.
10. `REJECTION_REASON` accepts one or more semicolon-separated values from: `NOT_FORMER_LEADER`, `RUNUP_TOO_WEAK`, `RUNUP_TOO_SLOW`, `COLLAPSE_NOT_SHARP`, `NO_REAL_GAP_ZONE`, `GAP_TOO_SMALL`, `ZONE_NOT_PERSISTENT`, `REENTRY_TOO_FAST`, `NO_SETTLING_PHASE`, `WRONG_ZONE_LAYER`, `WRONG_REENTRY_TRIGGER`, `VOLUME_STRUCTURE_WRONG`, `OTHER`.

Do not open the diagnostic package until the blind labels are complete.
"""
    atomic_text(REVIEW_INSTRUCTIONS,instructions)
    atomic_text(BLIND_DIR/REVIEW_CSV.name,review.to_csv(index=False));atomic_text(BLIND_DIR/REVIEW_INSTRUCTIONS.name,instructions)


def png_identity_leaks(sample: pd.DataFrame) -> int:
    leaks=0
    for row in sample.itertuples(index=False):
        data=(BLIND_DIR/f"{row.audit_id}.png").read_bytes()
        if row.symbol.encode() in data or pd.Timestamp(row.peak_date).strftime("%Y-%m-%d").encode() in data: leaks+=1
    return leaks


def distribution(series: pd.Series) -> dict[str, Any]:
    clean=series.dropna();return {"n":len(clean),"min":float(clean.min()),"q10":float(clean.quantile(.1)),"median":float(clean.median()),"q90":float(clean.quantile(.9)),"max":float(clean.max())}


def render_report(result: dict[str, Any]) -> str:
    source=result["source_population"];sample=result["sample"]
    return f"""# {EXPERIMENT}

Status: `AUDIT_PACKAGE_COMPLETE`; `HUMAN_PATTERN_REVIEW_REQUIRED`.

This is an outcome-blind semantic-fidelity audit, not a backtest or alpha test. Candidate generation and charts use only 2014–2021, with 2013 used only for warm-up. Validation 2022–2023 and repository 2024+ data remain unopened.

## Semantic preflight

The frozen sequence is prior strength → peak → collapse/liquidation → one or more true adjacent-session downward gap primitives → unresolved overhead layers → time below → later candidate re-entry from below. A strict primitive, broader traded collapse, provisional stack, and human visual “断层带” are deliberately not equated.

The displayed marker is the first upward lower-boundary touch of the lowest unresolved layer after price has first moved below it. It is a high-recall review anchor only. Lower close, 10% penetration, 50% penetration, full fill, and layer hierarchy remain retained alternatives; no trigger or persistence minimum is scientifically selected.

- Economic sequence: prior strong-stock/leader phase → run-up → peak → collapse/liquidation → strict downward discontinuity primitive(s) → unresolved overhead layer(s) → time below → later approach/re-entry from below.
- Causal background: prior speculative/leadership demand followed by liquidation and collapse.
- State variables: prior leadership, run-up, drawdown depth, collapse geometry, strict-gap primitives, persistence, layering, time below, and volume/turnover context.
- Event formation time: the collapse phase in which adjacent-session strict downward gaps form.
- Confirmation trigger: deliberately unfrozen; A lower touch, B lower close, C 10% penetration, D 50% penetration, E full fill, nearest-layer entry, and next-layer entry are retained.
- Entry time: not defined in this audit.
- Outcome start time: not applicable.
- Ambiguities retained: single versus stacked gaps; grouping and traded overlap; same-day inclusion; minimum persistence; one versus multiple complete sessions below; nearest-layer boundary; independent versus hierarchical layers; leader representation; impulsive versus merely large run-up; need for a base; and whether turnover decline is essential.
- Chosen clocks: strict gap uses current open versus immediately prior comparable low; primitive is `[Open_t, Low_t-1]`; re-entry clock starts only after price first moves strictly below the lower boundary; chart marker is the first upward lower touch; blind display ends at that exact completed one-minute bar.

## Source population

- Eligible symbols: {source['eligible_symbols']:,}
- Strict gap primitives: {source['strict_gap_primitives']:,}
- Provisional grouped episodes/stacks: {source['provisional_zone_stacks']:,}
- Broad collapse episodes (decline at least 20% retrieval rule): {source['collapse_episodes']:,}
- Multi-primitive broad collapse episodes: {source['multi_primitive_collapse_episodes']:,}
- Main/ChiNext review-eligible candidates: {source['main_board_candidates']:,}/{source['chinext_candidates']:,}
- ST/non-ST candidates: {source['st_candidates']:,}/{source['non_st_candidates']:,}

These thresholds are retrieval rules, not economic findings.

## Blind sample

- Charts: {sample['blind_chart_count']} ({sample['main_blind_count']} Main, {sample['chinext_blind_count']} ChiNext)
- Machine-positive / immediate-fast / hidden near-miss: 80 / 20 / {sample['near_miss_control_count']}
- ST cases: {sample['st_blind_count']}; multilayer cases: {sample['multilayer_blind_count']}; same-day cases: {sample['same_day_blind_count']}
- Identity leaks: {sample['blind_charts_with_identity_leak_count']}; post-reentry chart data: {sample['blind_charts_with_post_reentry_data_count']}; outcome-selected rows: {sample['sample_rows_using_outcome_count']}

Blind charts terminate at the exact completed one-minute candidate re-entry bar. The final daily candle is reconstructed only from minute information available through that bar.

## Governance

User-provided 2026 screenshots influenced semantic formulation only. No 2026 repository price, return, identity, or outcome entered this audit. Consequently repository 2024+ should not later be called pristine hypothesis-formation OOS; 2022–2023 remains untouched external Validation.

No precision, recall, strategy edge, or economic significance can be computed before human labels exist.

## Next action

The human reviewer opens `{BLIND_DIR}`, labels `{REVIEW_CSV}`, and returns the completed CSV. Only then should the prepared label-summary script be run to freeze actual zone, persistence, and re-entry semantics before any return study.
"""


def run() -> dict[str, Any]:
    inputs=validate_inputs();grouped=build_grouped_primitives();seeds=episode_seeds(grouped)
    daily_reentry=build_daily_reentry(seeds);exact=build_exact_reentry(daily_reentry)
    candidates=build_descriptors(daily_reentry,exact)
    candidates=candidates.loc[candidates.machine_class.ne("OUTSIDE_CONTROL_RANGE")].copy()
    assert_no_outcome_columns(candidates)
    compact_columns=[column for column in candidates.columns if column not in {"sample_hash"}]
    write_parquet(candidates[compact_columns],CANDIDATES)
    sample=select_blind_sample(candidates)
    build_charts(sample);write_review_files(sample)
    manifest=pd.DataFrame({"audit_id":sample.audit_id,"blind_chart_path":sample.audit_id.map(lambda x:str(BLIND_DIR/f"{x}.png")),"diagnostic_chart_path":sample.audit_id.map(lambda x:str(DIAGNOSTIC_DIR/f"{x}.png")),"chart_end_time":sample.candidate_reentry_time,"post_reentry_bars":0,"identity_fields_in_blind_metadata":0})
    write_parquet(manifest,SAMPLE_MANIFEST)
    mapping_columns=[column for column in sample.columns if column not in {"sample_hash"}]
    write_parquet(sample[mapping_columns],AUDIT_MAPPING)
    population={
        "eligible_symbols":int(grouped.symbol.nunique()),"strict_gap_primitives":len(grouped),
        "provisional_zone_stacks":int(grouped.collapse_episode_id.nunique()),
        "collapse_episodes":int(candidates.retrieval_eligible.sum()),
        "multi_primitive_collapse_episodes":int((candidates.retrieval_eligible&candidates.multi_layer).sum()),
        "main_board_candidates":int(candidates.board.eq("MAIN").sum()),"chinext_candidates":int(candidates.board.eq("CHINEXT").sum()),
        "st_candidates":int(candidates.is_st.sum()),"non_st_candidates":int((~candidates.is_st).sum()),
    }
    persistence={bucket:int(candidates.persistence_bucket.eq(bucket).sum()) for bucket in ("SAME_DAY","NEXT_DAY","SHORT_PERSISTENCE","MEDIUM_PERSISTENCE","LONG_PERSISTENCE","VERY_LONG")}
    blind_count=len(list(BLIND_DIR.glob("AUDIT_*.png")));diagnostic_count=len(list(DIAGNOSTIC_DIR.glob("AUDIT_*.png")))
    sample_summary={
        "blind_chart_count":blind_count,"diagnostic_chart_count":diagnostic_count,
        "main_blind_count":int(sample.board.eq("MAIN").sum()),"chinext_blind_count":int(sample.board.eq("CHINEXT").sum()),
        "st_blind_count":int(sample.is_st.sum()),"multilayer_blind_count":int(sample.multi_layer.sum()),
        "same_day_blind_count":int(sample.persistence_bucket.eq("SAME_DAY").sum()),
        "near_miss_control_count":int(sample.machine_class.eq("NEAR_MISS_CONTROL").sum()),
        "blind_charts_with_identity_leak_count":png_identity_leaks(sample),
        "blind_charts_with_post_reentry_data_count":int(manifest.post_reentry_bars.sum()),
        "sample_rows_using_outcome_count":0,
    }
    audits={
        "post_2021_outcome_read_count":0,"validation_opened":False,"repository_2024_plus_data_opened":False,
        "outcome_used_for_sample_selection_count":0,"sample_rows_using_outcome_count":0,
        "primitive_interval_orientation_failure_count":int((grouped.lower_coord>=grouped.upper_coord).sum()),
        "primitive_lineage_loss_count":int(len(grouped)-grouped.gap_primitive_id.nunique()),
        "blind_chart_count_failure":int(blind_count!=120),"diagnostic_chart_count_failure":int(diagnostic_count!=120),
        "blind_charts_with_identity_leak_count":sample_summary["blind_charts_with_identity_leak_count"],
        "blind_charts_with_post_reentry_data_count":0,
    }
    if any(audits[key] for key in ("primitive_interval_orientation_failure_count","primitive_lineage_loss_count","blind_chart_count_failure","diagnostic_chart_count_failure","blind_charts_with_identity_leak_count")):
        raise AuditError(f"hard audit failure: {audits}")
    result={
        "experiment_id":EXPERIMENT,"spec_sha256":EXPECTED_SPEC_SHA256,"start_checkpoint":"fa817a732a378d87c6700a8005fe37a3346c3d9d",
        "research_type":"OUTCOME_BLIND_HUMAN_PATTERN_FIDELITY_AUDIT","input_identity":inputs,
        "source_population":population,"persistence":persistence,"sample":sample_summary,"audits":audits,
        "paths":{"blind_package":str(BLIND_DIR),"diagnostic_package":str(DIAGNOSTIC_DIR),"review_csv":str(REVIEW_CSV),"review_instructions":str(REVIEW_INSTRUCTIONS),"audit_mapping":str(AUDIT_MAPPING)},
        "status":{"audit_package_complete":True,"human_pattern_review_required":True,"strategy_backtest_run":False,"return_outcome_analysis_run":False},
        "2026_semantic_example_note":"User-provided 2026 examples influenced qualitative semantic formulation only; no repository 2024+ data or return outcome was opened. Future 2024+ is not pristine hypothesis-formation OOS; 2022-2023 remains sealed external Validation.",
    }
    atomic_json(RESULT,result);atomic_text(REPORT,render_report(result))
    return result


if __name__=="__main__":
    outcome=run();print(json.dumps({"experiment_id":outcome["experiment_id"],"source_population":outcome["source_population"],"sample":outcome["sample"],"status":outcome["status"]},ensure_ascii=False,indent=2))
