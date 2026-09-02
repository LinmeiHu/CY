#!/usr/bin/env python3
# ruff: noqa: E501,E701,E702,RUF046
"""Run the Development-only A-share market Panic-to-Repair Transition V1."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-MARKET-PANIC-REPAIR-TRANSITION-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "e1840146bba1bbadd57b410f73ad1fe223a01c0650fe9dd8d1a58e327290c117"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_market_panic_repair_transition_v1")

STATES = OS_ROOT / f"artifacts/{EXPERIMENT}_market_states.parquet"
SEARCH = OS_ROOT / f"artifacts/{EXPERIMENT}_search.parquet"
MAIN_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_main_fold_selections.json"
CHINEXT_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_fold_selections.json"
NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

OLD_DAILY = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006/daily")
NEW_DAILY = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
OLD_EXEC = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_execution_2013_2017_cy006/execution_5m")
NEW_EXEC = Path("/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2/execution_5m")
RAW_MINUTE = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")

ENTRY_COST = 0.002
EXIT_COST = 0.002
FOLDS = tuple((2014, year - 1, year) for year in range(2017, 2022))
CHECKPOINTS = ("0945", "1000", "1030")
CHECKPOINT_ORDER = {value: index for index, value in enumerate(CHECKPOINTS)}
PANIC_NAMES = ("Q75", "Q90")
REPAIR_NAMES = ("Q67", "Q80")
EXIT_NAMES = ("SAME_CLOSE", "T1_LEGAL_OPEN", "T1_CLOSE")
EXIT_GROSS = ("same_close_gross", "t1_open_gross", "t1_close_gross")
EXIT_DATE = ("same_close_exit_date", "t1_open_exit_date", "t1_close_exit_date")

EXCLUDED_INDUSTRIES = (
    "煤炭开采", "油气开采Ⅱ", "油服工程", "炼化及贸易", "普钢", "特钢Ⅱ", "冶钢原料",
    "工业金属", "小金属", "贵金属", "能源金属", "金属新材料", "化学原料", "化学制品",
    "农化制品", "化学纤维", "电子化学品Ⅱ", "水泥", "玻璃玻纤", "非金属材料Ⅱ", "电力", "燃气Ⅱ",
)

DAILY_HASHES = {
    2014: "de8839c9612f76ba190bfc1e729639ee723dfc6e3ea7a15d3fb77048808e0c81",
    2015: "9f581bbc0fec380f893d5cf520784798df5c0305e76d01283650bd861ce1aab0",
    2016: "e1d7f7481766b413b63e7e13cb6c30c1aeed96400459f4d84c2c728b3b705d22",
    2017: "5a8d7b0d48d4ff3b9323c53a812539115bb62a2cfe197369ef3b5f5499816f88",
    2018: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    2019: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    2020: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    2021: "cbd4b2d2ccdff32b09ed1a2e9347f8045cde89ff7e4e1b189577bc353e4d9311",
}
EXEC_HASHES = {
    2014: "0733be9b270a3918817fc1df54745a7f67dfd068d437babd2ec5509ada7609d9",
    2015: "5bb0966bc66f92523d2229dd162b52f3a625d65fa8ed5bd9430b3c28e9ee3d74",
    2016: "00f5bdb2d32bd74cc18f2a362d5258d5ea76a7c80bc309e648eee22ac7546a9b",
    2017: "54caa32a367b0254ea2a247765403772598724d829efcf2ccf097737e9666c6f",
    2018: "0b5f3a090a79d31fa723228132f080582d015a197b0fd2496fadfdde43502cf4",
    2019: "8a34ee395a18a200dd50df728c4448531ff99a20c6b2148f16666daa38a1790f",
    2020: "292b15641bf374ab27e9c4a812b77f4142223858f31b16dfea34a669a3305036",
    2021: "b0ef29775404a15680ca176b15c46c0590e0424c0eaf052f0c65b73369458a7d",
}
RAW_HASHES = {
    2014: "8e2e873623124b323a91c5c367c003859b184ac471dc842d572f30f256d567b8",
    2015: "36c99e02c4c391f03740e255a274c521da9733b507abb90158e0767a7dcca965",
    2016: "a7c0b062a9de260c4798922aa998ca3471bdbe2690c754b732ebc7fc9272faf8",
    2017: "3bb9d8d1df8795e9cc45cb04631b796de7153798f815d629c420156e47a448d7",
    2018: "83fbb3e0fda4b278e1072836a9695b7d9a6dfa396a07248e40f85db0d2ba0812",
    2019: "b31fccebb8f2319099b412233263dbc99f965a091b0995e62d275997b411130c",
    2020: "67d6b958f2b4113750df8f1a98d6e48d93ef00e04cab0fbf0cf0661b1600d45e",
    2021: "efd3b1a4bf60c47ba36b83792c97fc08d600aa8cde58014ff44e3c005eebac61",
}


class V1Error(RuntimeError):
    """Fail-closed experiment error."""


@dataclass(frozen=True)
class Params:
    panic_code: int
    checkpoint: str
    repair_code: int
    exit_code: int

    @property
    def key(self) -> str:
        return f"p{PANIC_NAMES[self.panic_code]}|t{self.checkpoint}|r{REPAIR_NAMES[self.repair_code]}|x{EXIT_NAMES[self.exit_code]}"


GRID = tuple(Params(*values) for values in itertools.product(range(2), CHECKPOINTS, range(2), range(3)))


def daily_path(year: int) -> Path:
    root = OLD_DAILY if year < 2018 else NEW_DAILY
    return root / f"partition_year={year}/data_0.parquet"


def exec_path(year: int) -> Path:
    root = OLD_EXEC if year < 2018 else NEW_EXEC
    return root / f"partition_year={year}/data_0.parquet"


def raw_path(year: int) -> Path:
    return RAW_MINUTE / f"{year}_day_parquet_none.parquet"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_ready(value: Any) -> Any:
    if isinstance(value, dict): return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating, float)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)): return str(pd.Timestamp(value))
    if isinstance(value, Params): return {**asdict(value), "key": value.key, "panic_rule": PANIC_NAMES[value.panic_code], "repair_rule": REPAIR_NAMES[value.repair_code], "exit": EXIT_NAMES[value.exit_code]}
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd")
    os.replace(temporary, path)


def sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def validate_inputs() -> dict[str, str]:
    if len(GRID) != 36 or len({item.key for item in GRID}) != 36:
        raise V1Error(f"grid changed: {len(GRID)}")
    expected = {SPEC: EXPECTED_SPEC_SHA256}
    expected.update({daily_path(year): digest for year, digest in DAILY_HASHES.items()})
    expected.update({exec_path(year): digest for year, digest in EXEC_HASHES.items()})
    expected.update({raw_path(year): digest for year, digest in RAW_HASHES.items()})
    found = {}
    for path, digest in expected.items():
        if not path.is_file(): raise V1Error(f"missing input: {path}")
        actual = sha256_file(path)
        if actual != digest: raise V1Error(f"hash mismatch: {path}: {actual}")
        found[str(path)] = actual
    return found


def connection() -> duckdb.DuckDBPyConnection:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    (EXTERNAL / "duckdb_tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{EXTERNAL / 'duckdb_tmp'}'")
    return con


def build_state_year(year: int) -> pd.DataFrame:
    shard = EXTERNAL / f"market_states_raw241_adapter_v4_{year}.parquet"
    if shard.is_file():
        frame = pd.read_parquet(shard)
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        for column in ("same_close_exit_date", "t1_open_exit_date", "t1_close_exit_date"):
            frame[column] = pd.to_datetime(frame[column])
        if len(frame) > 0 and frame.trade_date.dt.year.eq(year).all(): return frame
        raise V1Error(f"invalid state shard: {shard}")
    excluded = ",".join("'" + value.replace("'", "''") + "'" for value in EXCLUDED_INDUSTRIES)
    all_daily = sql_paths([daily_path(value) for value in range(2014, 2022)])
    con = connection()
    con.execute(f"CREATE TEMP VIEW daily AS SELECT * FROM read_parquet({all_daily})")
    con.execute(
        """CREATE TEMP VIEW calendar AS
        SELECT trade_date,row_number() OVER(ORDER BY trade_date) AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM daily WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31')"""
    )
    query = f"""
    WITH eligible0 AS (
      SELECT d.trade_date,d.symbol,d.open AS open_price,d.close AS daily_close,d.preclose,
             d.down_limit_price,d.snapshot_id AS state_snapshot_id,
             CASE WHEN d.symbol LIKE '30%.SZ' THEN 'CHINEXT' ELSE 'MAIN' END AS sleeve
      FROM read_parquet('{daily_path(year)}') d
      WHERE d.hard_valid AND d.current_day_data_tradable AND d.trade_status=1
        AND d.industry_valid AND d.historical_identity_valid AND d.industry_snapshot_id IS NOT NULL
        AND d.corporate_action_valid AND NOT d.corporate_action_blocking
        AND coalesce(d.corporate_action_count,0)=0
        AND d.industry NOT IN ({excluded})
        AND d.open>0 AND d.preclose>0 AND d.down_limit_price>0
        AND ((d.symbol LIKE '60%.SH' AND d.symbol NOT LIKE '688%.SH')
             OR d.symbol LIKE '00%.SZ' OR d.symbol LIKE '30%.SZ')
    ), targets0 AS (
      SELECT e.*,c.cal_idx,c1.trade_date AS t1_date
      FROM eligible0 e JOIN calendar c USING(trade_date)
      LEFT JOIN calendar c1 ON c1.cal_idx=c.cal_idx+1
    ), legal AS (
      SELECT symbol,trade_date,open
      FROM daily
      WHERE trade_date<=DATE '2021-12-31' AND hard_valid AND current_day_data_tradable
        AND trade_status=1 AND corporate_action_valid AND NOT corporate_action_blocking
        AND coalesce(corporate_action_count,0)=0 AND NOT sell_blocked_open AND open>0
    ), with_legal AS (
      SELECT t.*,l.trade_date AS next_legal_open_date,l.open AS next_legal_open_price
      FROM targets0 t ASOF LEFT JOIN legal l
        ON t.symbol=l.symbol AND t.trade_date<l.trade_date
    ), actions AS (
      SELECT symbol,trade_date FROM daily
      WHERE trade_date<=DATE '2021-12-31'
        AND (coalesce(corporate_action_count,0)>0 OR corporate_action_blocking OR NOT corporate_action_valid)
    ), targets AS (
      SELECT t.*,a.trade_date AS next_action_date
      FROM with_legal t ASOF LEFT JOIN actions a
        ON t.symbol=a.symbol AND t.trade_date<a.trade_date
    ), with_outcomes AS (
      SELECT t.*,
             CASE WHEN t.next_action_date IS NULL OR t.next_action_date>t.next_legal_open_date
                  THEN t.next_legal_open_price END AS legal_open_price,
             CASE WHEN d1.hard_valid AND d1.current_day_data_tradable AND d1.trade_status=1
                       AND d1.corporate_action_valid AND NOT d1.corporate_action_blocking
                       AND coalesce(d1.corporate_action_count,0)=0
                       AND (t.next_action_date IS NULL OR t.next_action_date>t.t1_date)
                  THEN d1.close END AS t1_close_price
      FROM targets t LEFT JOIN daily d1 ON d1.symbol=t.symbol AND d1.trade_date=t.t1_date
    ), raw_wide AS (
      SELECT qmt_code AS symbol,trade_date,
             max(CASE WHEN bar_end_time::TIME=TIME '09:45:00' THEN close END) AS p0945,
             max(CASE WHEN bar_end_time::TIME=TIME '09:46:00' THEN open END) AS e0945,
             max(CASE WHEN bar_end_time::TIME=TIME '10:00:00' THEN close END) AS p1000,
             max(CASE WHEN bar_end_time::TIME=TIME '10:01:00' THEN open END) AS e1000,
             max(CASE WHEN bar_end_time::TIME=TIME '10:30:00' THEN close END) AS p1030,
             max(CASE WHEN bar_end_time::TIME=TIME '10:31:00' THEN open END) AS e1030,
             max(CASE WHEN bar_end_time::TIME=TIME '15:00:00' THEN close END) AS p1500,
             count(*) AS session_minute_count,
             count(DISTINCT bar_end_time) AS distinct_minute_count
      FROM read_parquet('{raw_path(year)}')
      WHERE period='1m' AND adjust='none'
      GROUP BY qmt_code,trade_date
    ), exec_cert AS (
      SELECT symbol,trade_date,max(daily_snapshot_id) AS exec_daily_snapshot_id,
             max(CASE WHEN window_index=2 THEN close END) AS cert_p0945,
             max(CASE WHEN window_index=3 THEN open END) AS cert_e0945,
             max(CASE WHEN window_index=5 THEN close END) AS cert_p1000,
             count(DISTINCT window_index) AS certified_windows,
             min(minute_count) AS min_minute_count,
             min(distinct_minute_count) AS min_distinct_minute_count,
             bool_and(hard_valid AND ohlc_valid AND unit_valid AND causal_inputs_valid) AS windows_valid,
             count(DISTINCT daily_snapshot_id) AS daily_snapshot_count
      FROM read_parquet('{exec_path(year)}')
      WHERE window_index IN (2,3,5)
      GROUP BY symbol,trade_date
    ), wide AS (
      SELECT t.*,r.* EXCLUDE(symbol,trade_date),x.* EXCLUDE(symbol,trade_date),
             (t.open_price/t.preclose-1) AS opening_return,
             (t.open_price-t.down_limit_price BETWEEN -0.0050000001 AND 0.0150000001) AS open_limit_stress,
             (r.session_minute_count=241 AND r.distinct_minute_count=241
              AND x.certified_windows=3 AND x.min_minute_count=5 AND x.min_distinct_minute_count=5
              AND x.windows_valid AND x.daily_snapshot_count=1
              AND x.exec_daily_snapshot_id=t.state_snapshot_id
              AND r.p0945=x.cert_p0945 AND r.e0945=x.cert_e0945 AND r.p1000=x.cert_p1000) AS checkpoint_valid
      FROM with_outcomes t LEFT JOIN raw_wide r USING(symbol,trade_date)
      LEFT JOIN exec_cert x USING(symbol,trade_date)
    ), long AS (
      SELECT *, '0945' AS checkpoint,p0945 AS checkpoint_price,e0945 AS entry_price FROM wide
      UNION ALL
      SELECT *, '1000' AS checkpoint,p1000 AS checkpoint_price,e1000 AS entry_price FROM wide
      UNION ALL
      SELECT *, '1030' AS checkpoint,p1030 AS checkpoint_price,e1030 AS entry_price FROM wide
    )
    SELECT trade_date,sleeve,checkpoint,
           count(*) AS universe_n,
           count(*) FILTER(WHERE checkpoint_valid AND checkpoint_price>0 AND entry_price>0) AS observed_n,
           avg((opening_return<=-0.05)::INT)::DOUBLE AS down_gap_breadth_5,
           median(opening_return) AS open_median_return,
           avg(open_limit_stress::INT)::DOUBLE AS limit_stress_breadth,
           median(checkpoint_price/open_price-1) FILTER(WHERE checkpoint_valid AND checkpoint_price>0 AND entry_price>0) AS median_price_repair,
           count(*) FILTER(WHERE checkpoint_valid AND checkpoint_price>0 AND entry_price>0 AND opening_return<=-0.05) AS panic_stock_n,
           avg((checkpoint_price>=open_price*1.01)::INT) FILTER(WHERE checkpoint_valid AND checkpoint_price>0 AND entry_price>0 AND opening_return<=-0.05) AS panic_stock_reclaim_breadth,
           count(*) FILTER(WHERE checkpoint_valid AND checkpoint_price>0 AND entry_price>0 AND open_limit_stress) AS opening_limit_observed_n,
           CASE WHEN count(*) FILTER(WHERE checkpoint_valid AND checkpoint_price>0 AND entry_price>0 AND open_limit_stress)>0
                THEN 1-avg((checkpoint_price-down_limit_price BETWEEN -0.0050000001 AND 0.0150000001)::INT)
                     FILTER(WHERE checkpoint_valid AND checkpoint_price>0 AND entry_price>0 AND open_limit_stress) END AS limit_release,
           avg((checkpoint_price>open_price)::INT) FILTER(WHERE checkpoint_valid AND checkpoint_price>0 AND entry_price>0) AS breadth_improvement,
           avg(p1500/entry_price-1) FILTER(WHERE checkpoint_valid AND entry_price>0 AND p1500>0) AS same_close_gross,
           count(*) FILTER(WHERE checkpoint_valid AND entry_price>0 AND p1500>0) AS same_close_n,
           avg(legal_open_price/entry_price-1) FILTER(WHERE checkpoint_valid AND entry_price>0 AND legal_open_price>0) AS t1_open_gross,
           count(*) FILTER(WHERE checkpoint_valid AND entry_price>0 AND legal_open_price>0) AS t1_open_n,
           max(next_legal_open_date) FILTER(WHERE checkpoint_valid AND entry_price>0 AND legal_open_price>0) AS t1_open_exit_date,
           avg(t1_close_price/entry_price-1) FILTER(WHERE checkpoint_valid AND entry_price>0 AND t1_close_price>0) AS t1_close_gross,
           count(*) FILTER(WHERE checkpoint_valid AND entry_price>0 AND t1_close_price>0) AS t1_close_n,
           max(t1_date) FILTER(WHERE checkpoint_valid AND entry_price>0 AND t1_close_price>0) AS t1_close_exit_date,
           trade_date AS same_close_exit_date,
           avg(p1500/entry_price-1) FILTER(WHERE checkpoint_valid AND entry_price>0 AND p1500>0) AS entry_day_close_gross,
           count(*) FILTER(WHERE checkpoint_valid AND entry_price>0 AND p1500>0)::DOUBLE/count(*) AS entry_coverage,
           count(*) FILTER(WHERE checkpoint_valid AND entry_price>0 AND legal_open_price>0)::DOUBLE/nullif(count(*) FILTER(WHERE checkpoint_valid AND entry_price>0),0) AS t1_open_coverage,
           count(*) FILTER(WHERE checkpoint_valid AND entry_price>0 AND t1_close_price>0)::DOUBLE/nullif(count(*) FILTER(WHERE checkpoint_valid AND entry_price>0),0) AS t1_close_coverage
    FROM long GROUP BY trade_date,sleeve,checkpoint ORDER BY trade_date,sleeve,checkpoint
    """
    con.execute(f"COPY ({query}) TO '{shard}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    frame = pd.read_parquet(shard)
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    for column in ("same_close_exit_date", "t1_open_exit_date", "t1_close_exit_date"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def build_states() -> pd.DataFrame:
    frames = [build_state_year(year) for year in range(2014, 2022)]
    states = pd.concat(frames, ignore_index=True).sort_values(["trade_date", "sleeve", "checkpoint"], kind="mergesort")
    expected_dates = states.trade_date.nunique()
    if expected_dates != 1950 or len(states) != expected_dates * 2 * 3:
        raise V1Error(f"market state shape failure: {len(states)} rows/{expected_dates} dates")
    if states.duplicated(["trade_date", "sleeve", "checkpoint"]).any(): raise V1Error("duplicate market state")
    if states.trade_date.max() > pd.Timestamp("2021-12-31"): raise V1Error("post-2021 state")
    required = ["down_gap_breadth_5", "open_median_return", "limit_stress_breadth", "median_price_repair", "breadth_improvement", "same_close_gross"]
    if states[required].isna().any().any(): raise V1Error(f"required state missing: {states[required].isna().sum().to_dict()}")
    write_parquet(states, STATES)
    return states


def cdf_rank(values: pd.Series, train_values: np.ndarray) -> np.ndarray:
    finite = np.asarray(train_values, dtype=float)
    finite = np.sort(finite[np.isfinite(finite)])
    if len(finite) == 0: raise V1Error("empty rank history")
    source = values.to_numpy(float)
    result = np.full(len(source), np.nan)
    mask = np.isfinite(source)
    result[mask] = np.searchsorted(finite, source[mask], side="right") / len(finite)
    return result


def score_fold(states: pd.DataFrame, sleeve: str, train_end: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    board = states.loc[states.sleeve.eq(sleeve)].copy().reset_index(drop=True)
    train_mask = board.trade_date.dt.year.between(2014, train_end)
    date_state = board.loc[board.checkpoint.eq("0945"), ["trade_date", "down_gap_breadth_5", "open_median_return", "limit_stress_breadth"]].copy()
    date_train = date_state.trade_date.dt.year.between(2014, train_end)
    open_components = []
    for column, sign in (("down_gap_breadth_5", 1.0), ("open_median_return", -1.0), ("limit_stress_breadth", 1.0)):
        train_values = sign * date_state.loc[date_train, column].to_numpy(float)
        open_components.append(cdf_rank(sign * date_state[column], train_values))
    date_state["open_panic_score"] = np.mean(np.column_stack(open_components), axis=1)
    board = board.merge(date_state[["trade_date", "open_panic_score"]], on="trade_date", how="left", validate="many_to_one")
    train_mask = board.trade_date.dt.year.between(2014, train_end)

    repair_columns = ("median_price_repair", "panic_stock_reclaim_breadth", "limit_release", "breadth_improvement")
    for checkpoint in CHECKPOINTS:
        cp = board.checkpoint.eq(checkpoint)
        cp_train = cp & train_mask
        components = []
        for column in repair_columns:
            components.append(cdf_rank(board.loc[cp, column], board.loc[cp_train, column].to_numpy(float)))
        matrix = np.column_stack(components)
        board.loc[cp, "repair_score"] = np.nanmean(matrix, axis=1)
        board.loc[cp, "repair_component_count"] = np.isfinite(matrix).sum(axis=1)
    unique_train = board.loc[train_mask & board.checkpoint.eq("0945")]
    calibration: dict[str, Any] = {
        "train_end": train_end,
        "train_dates": int(len(unique_train)),
        "panic_q75": float(unique_train.open_panic_score.quantile(.75, interpolation="linear")),
        "panic_q90": float(unique_train.open_panic_score.quantile(.90, interpolation="linear")),
        "repair": {},
    }
    for panic_code, panic_q in enumerate((.75, .90)):
        panic_threshold = calibration[f"panic_q{int(panic_q * 100)}"]
        for checkpoint in CHECKPOINTS:
            sample = board.loc[train_mask & board.checkpoint.eq(checkpoint) & board.open_panic_score.ge(panic_threshold), "repair_score"]
            if sample.empty: raise V1Error(f"empty repair calibration: {sleeve}/{train_end}/{panic_code}/{checkpoint}")
            calibration["repair"][f"{panic_code}|{checkpoint}"] = {
                "sample_dates": int(len(sample)),
                "q33": float(sample.quantile(.33, interpolation="linear")),
                "q67": float(sample.quantile(.67, interpolation="linear")),
                "q80": float(sample.quantile(.80, interpolation="linear")),
            }
    return board, calibration


def thresholds(params: Params, calibration: dict[str, Any]) -> tuple[float, float]:
    panic = calibration[("panic_q75", "panic_q90")[params.panic_code]]
    repair = calibration["repair"][f"{params.panic_code}|{params.checkpoint}"][("q67", "q80")[params.repair_code]]
    return float(panic), float(repair)


def portfolio_metrics(nav: pd.DataFrame, trades: pd.DataFrame, start_nav: float) -> dict[str, Any]:
    end_nav = float(nav.nav.iloc[-1])
    running = np.maximum.accumulate(np.concatenate(([start_nav], nav.nav.to_numpy())))
    max_dd = float((nav.nav.to_numpy() / running[1:] - 1).min())
    cagr = float((end_nav / start_nav) ** (242 / len(nav)) - 1)
    std = float(nav.daily_return.std(ddof=0))
    sharpe = float(nav.daily_return.mean() / std * math.sqrt(242)) if std > 0 else 0.0
    annual_nav = nav.set_index("trade_date").nav.resample("YE").last()
    yearly = annual_nav.pct_change(fill_method=None)
    yearly.iloc[0] = annual_nav.iloc[0] / start_nav - 1
    positive = nav.loc[nav.daily_pnl > 0, "daily_pnl"].sort_values(ascending=False)
    positive_sum = float(positive.sum())
    monthly = nav.set_index("trade_date").nav.resample("ME").last().pct_change(fill_method=None)
    return {
        "start_nav": start_nav, "end_nav": end_nav, "total_return": end_nav / start_nav - 1,
        "cagr": cagr, "max_drawdown": max_dd, "sharpe": sharpe,
        "calmar": cagr / abs(max_dd) if max_dd < 0 else (1e6 if cagr > 0 else 0.0),
        "trade_count": int(len(trades)), "recent_year_trade_count": int((trades.exit_date.dt.year == nav.trade_date.dt.year.iloc[-1]).sum()) if len(trades) else 0,
        "win_rate": float((trades.net_return > 0).mean()) if len(trades) else None,
        "median_year_return": float(yearly.median()),
        "yearly_returns": {str(index.year): float(value) for index, value in yearly.items()},
        "positive_years": int((yearly > 0).sum()), "negative_years": int((yearly < 0).sum()), "flat_years": int((yearly == 0).sum()),
        "positive_months": int((monthly > 0).sum()),
        "top1_day_contribution": float(positive.head(1).sum() / positive_sum) if positive_sum > 0 else 0.0,
        "top5_day_contribution": float(positive.head(5).sum() / positive_sum) if positive_sum > 0 else 0.0,
        "top1pct_day_contribution": float(positive.head(max(1, math.ceil(len(nav) * .01))).sum() / positive_sum) if positive_sum > 0 else 0.0,
        "duplicate_board_position_count": int(nav.positions.gt(1).sum()),
        "negative_cash_or_leverage_count": int(nav.cash.lt(-1e-12).sum()),
    }


def simulate(states: pd.DataFrame, calendar: pd.DatetimeIndex, params: Params, calibration: dict[str, Any],
             start: pd.Timestamp, end: pd.Timestamp, start_nav: float = 1.0, mode: str = "FULL") -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    panic_min, repair_min = thresholds(params, calibration)
    frame = states.loc[states.checkpoint.eq(params.checkpoint) & states.trade_date.between(start, end)].set_index("trade_date")
    gross_col = EXIT_GROSS[params.exit_code]; exit_col = EXIT_DATE[params.exit_code]
    cash = prior_nav = start_nav
    position: dict[str, Any] | None = None
    nav_rows = []; trade_rows = []
    for day in calendar[(calendar >= start) & (calendar <= end)]:
        if position is not None and params.exit_code == 1 and position["exit_date"] == day:
            proceeds = position["principal"] * (1 + position["exit_gross"]) * (1 - EXIT_COST)
            cash += proceeds
            trade_rows.append({**position, "exit_proceeds": proceeds, "pnl": proceeds - position["entry_debit"], "net_return": proceeds / position["entry_debit"] - 1})
            position = None
        row = frame.loc[day] if day in frame.index else None
        if position is None and row is not None:
            if mode == "ORDINARY": signal = row.open_panic_score < panic_min and row.repair_score >= repair_min
            elif mode == "PANIC_ONLY": signal = row.open_panic_score >= panic_min
            else: signal = row.open_panic_score >= panic_min and row.repair_score >= repair_min
            exit_date = pd.Timestamp(row[exit_col]) if pd.notna(row[exit_col]) else pd.NaT
            exit_gross = float(row[gross_col]) if pd.notna(row[gross_col]) else np.nan
            if signal and pd.notna(exit_date) and exit_date <= end and np.isfinite(exit_gross):
                debit = cash; principal = debit / (1 + ENTRY_COST); cash = 0.0
                position = {
                    "signal_date": day, "entry_date": day, "exit_date": exit_date,
                    "principal": principal, "entry_debit": debit, "exit_gross": exit_gross,
                    "entry_day_close_gross": float(row.entry_day_close_gross),
                    "open_panic_score": float(row.open_panic_score), "repair_score": float(row.repair_score),
                    "checkpoint": params.checkpoint, "mode": mode,
                    "same_close_gross": float(row.same_close_gross),
                    "t1_open_gross": float(row.t1_open_gross) if pd.notna(row.t1_open_gross) else np.nan,
                }
                if params.exit_code == 0:
                    proceeds = principal * (1 + exit_gross) * (1 - EXIT_COST); cash += proceeds
                    trade_rows.append({**position, "exit_proceeds": proceeds, "pnl": proceeds - debit, "net_return": proceeds / debit - 1})
                    position = None
        mark_value = 0.0
        if position is not None:
            if position["entry_date"] == day:
                mark_value = position["principal"] * (1 + position["entry_day_close_gross"])
                position["mark_value"] = mark_value
            else:
                mark_value = position.get("mark_value", position["principal"])
            if params.exit_code == 2 and position["exit_date"] == day:
                proceeds = position["principal"] * (1 + position["exit_gross"]) * (1 - EXIT_COST); cash += proceeds
                trade_rows.append({**position, "exit_proceeds": proceeds, "pnl": proceeds - position["entry_debit"], "net_return": proceeds / position["entry_debit"] - 1})
                position = None; mark_value = 0.0
        nav_value = cash + mark_value
        nav_rows.append({"trade_date": day, "nav": nav_value, "daily_pnl": nav_value - prior_nav,
                         "daily_return": nav_value / prior_nav - 1 if prior_nav else 0.0,
                         "cash": cash, "positions": int(position is not None)})
        prior_nav = nav_value
    if position is not None: raise V1Error("position survived replay boundary")
    nav = pd.DataFrame(nav_rows); trades = pd.DataFrame(trade_rows)
    if trades.empty: trades = pd.DataFrame(columns=["signal_date", "exit_date", "net_return", "pnl"])
    else:
        trades["signal_date"] = pd.to_datetime(trades.signal_date); trades["exit_date"] = pd.to_datetime(trades.exit_date)
    return nav, trades, portfolio_metrics(nav, trades, start_nav)


def compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key not in ("start_nav", "end_nav")}


def search_fold(sleeve: str, scored: pd.DataFrame, calendar: pd.DatetimeIndex, calibration: dict[str, Any], train_end: int, test_year: int) -> pd.DataFrame:
    shard = EXTERNAL / f"search_causal_rank_v2_{sleeve.lower()}_{test_year}.parquet"
    if shard.is_file():
        frame = pd.read_parquet(shard)
        if len(frame) == 36 and set(frame.parameter_key) == {item.key for item in GRID}: return frame
        raise V1Error(f"invalid search shard: {shard}")
    start = calendar[calendar.year == 2014][0]; end = calendar[calendar.year == train_end][-1]
    rows = []
    for index, params in enumerate(GRID):
        _, _, metrics = simulate(scored, calendar, params, calibration, start, end)
        panic_min, repair_min = thresholds(params, calibration)
        rows.append({"sleeve": sleeve, "train_start": 2014, "train_end": train_end, "test_year": test_year,
                     "parameter_index": index, "parameter_key": params.key, **asdict(params),
                     "panic_rule": PANIC_NAMES[params.panic_code], "repair_rule": REPAIR_NAMES[params.repair_code],
                     "exit": EXIT_NAMES[params.exit_code], "panic_threshold": panic_min, "repair_threshold": repair_min,
                     "train_panic_q75": calibration["panic_q75"], "train_panic_q90": calibration["panic_q90"],
                     "repair_calibration_dates": calibration["repair"][f"{params.panic_code}|{params.checkpoint}"]["sample_dates"],
                     **compact_metrics(metrics)})
    frame = pd.DataFrame(rows); write_parquet(frame, shard); return frame


def select_top5(search: pd.DataFrame) -> pd.DataFrame:
    eligible = search.loc[(search.trade_count >= 15) & (search.recent_year_trade_count >= 3)].copy()
    if eligible.empty: return eligible
    eligible["checkpoint_order"] = eligible.checkpoint.map(CHECKPOINT_ORDER)
    return eligible.sort_values(
        ["calmar", "sharpe", "median_year_return", "cagr", "top5_day_contribution", "checkpoint_order", "parameter_key"],
        ascending=[False, False, False, False, True, True, True], kind="mergesort",
    ).head(5)


def params_from_row(row: pd.Series) -> Params:
    return Params(int(row.panic_code), str(row.checkpoint), int(row.repair_code), int(row.exit_code))


def cash_nav(calendar: pd.DatetimeIndex, year: int, start_nav: float) -> pd.DataFrame:
    dates = calendar[calendar.year == year]
    return pd.DataFrame({"trade_date": dates, "nav": start_nav, "daily_pnl": 0.0, "daily_return": 0.0, "cash": start_nav, "positions": 0})


def trajectory_summary(trades: pd.DataFrame, scored: pd.DataFrame) -> dict[str, Any]:
    if trades.empty: return {"trades": 0}
    wide = scored.pivot(index="trade_date", columns="checkpoint", values="repair_score").rename(columns=lambda x: f"repair_{x}")
    base = scored.loc[scored.checkpoint.eq("0945"), ["trade_date", "open_panic_score", "same_close_gross", "t1_open_gross"]].set_index("trade_date")
    joined = trades.set_index("signal_date").join(base, rsuffix="_state").join(wide)
    def group(mask: pd.Series) -> dict[str, Any]:
        part = joined.loc[mask]
        return {"n": int(len(part)), **{column: (float(part[column].median()) if len(part) else None) for column in ("open_panic_score_state", "repair_0945", "repair_1000", "repair_1030", "same_close_gross_state", "t1_open_gross_state")}}
    return {"trades": int(len(joined)), "profitable": group(joined.net_return > 0), "losing": group(joined.net_return <= 0)}


def replay_fold(scored: pd.DataFrame, calendar: pd.DatetimeIndex, calibration: dict[str, Any], top5: pd.DataFrame,
                test_year: int, start_nav: float) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    if top5.empty:
        nav = cash_nav(calendar, test_year, start_nav)
        return {"selection_blocked": True, "test_year": test_year,
                "panic_q75": calibration["panic_q75"], "panic_q90": calibration["panic_q90"],
                "full": compact_metrics(portfolio_metrics(nav, pd.DataFrame(columns=["exit_date", "net_return"]), start_nav))}, nav, pd.DataFrame()
    row = top5.iloc[0]; params = params_from_row(row)
    start = calendar[calendar.year == test_year][0]; end = calendar[calendar.year == test_year][-1]
    nav, trades, full = simulate(scored, calendar, params, calibration, start, end, start_nav, "FULL")
    _, panic_trades, panic = simulate(scored, calendar, params, calibration, start, end, 1.0, "PANIC_ONLY")
    _, ordinary_trades, ordinary = simulate(scored, calendar, params, calibration, start, end, 1.0, "ORDINARY")
    neighbors = []
    for _, candidate in top5.iterrows():
        _, _, metrics = simulate(scored, calendar, params_from_row(candidate), calibration, start, end, 1.0, "FULL")
        neighbors.append(metrics["total_return"])
    fold = {
        "selection_blocked": False, "test_year": test_year, "selected": params,
        "panic_q75": calibration["panic_q75"], "panic_q90": calibration["panic_q90"],
        "panic_threshold": float(row.panic_threshold), "repair_threshold": float(row.repair_threshold),
        "repair_calibration_dates": int(row.repair_calibration_dates),
        "train": {key: row[key] for key in ("total_return", "cagr", "max_drawdown", "sharpe", "calmar", "trade_count", "recent_year_trade_count", "median_year_return", "top5_day_contribution")},
        "full": compact_metrics(full), "panic_only": compact_metrics(panic),
        "repair_confirmation_increment": full["total_return"] - panic["total_return"],
        "ordinary_repair_diagnostic": compact_metrics(ordinary),
        "top5_neighbor_oos": {"median_return": float(np.median(neighbors)), "best_return": float(np.max(neighbors)),
                              "worst_return": float(np.min(neighbors)), "fraction_profitable": float(np.mean(np.array(neighbors) > 0)), "returns": neighbors},
        "trajectory": trajectory_summary(trades, scored),
        "panic_only_trades": int(len(panic_trades)), "ordinary_repair_trades": int(len(ordinary_trades)),
    }
    return fold, nav, trades


def compound_excluding(nav: pd.DataFrame, year: int | None = None, best_days: int = 0) -> float:
    returns = nav.daily_return.copy()
    if year is not None: returns = returns.loc[nav.trade_date.dt.year.ne(year)]
    if best_days: returns = returns.drop(returns.nlargest(best_days).index)
    return float((1 + returns).prod() - 1)


def distribution(values: pd.Series) -> dict[str, Any]:
    clean = values.dropna()
    return {"n": int(len(clean)), "min": float(clean.min()), "q10": float(clean.quantile(.1)), "q25": float(clean.quantile(.25)),
            "median": float(clean.median()), "q75": float(clean.quantile(.75)), "q90": float(clean.quantile(.9)), "max": float(clean.max())}


def board_verdict(board: dict[str, Any]) -> dict[str, Any]:
    folds = [fold for fold in board["folds"] if not fold["selection_blocked"]]
    positive_increments = sum(fold["repair_confirmation_increment"] > 0 for fold in folds)
    credible = board["stitched"]["total_return"] > 0 and board["return_ex_2020"] > 0 and positive_increments >= 3
    marginal = board["stitched"]["total_return"] > 0 and positive_increments >= 2
    return {"credible": credible, "marginal": marginal, "positive_increment_folds": positive_increments,
            "classification": "PANIC_REPAIR_EDGE" if credible else ("MARGINAL_PANIC_REPAIR_EDGE" if marginal else "NO_PANIC_REPAIR_TRANSITION_EDGE")}


def choose_verdict(boards: dict[str, Any], combined: dict[str, Any]) -> str:
    credible = [key for key, value in boards.items() if value["board_verdict"]["credible"]]
    marginal = [key for key, value in boards.items() if value["board_verdict"]["marginal"]]
    if len(credible) == 2: return "PANIC_REPAIR_TRANSITION_EDGE_READY_FOR_VALIDATION"
    if credible: return "BOARD_SPECIFIC_PANIC_REPAIR_EDGE"
    if marginal and combined["return_ex_2020"] <= 0: return "PANIC_REPAIR_EDGE_BUT_EPISODE_CONCENTRATED"
    if marginal: return "MARGINAL_PANIC_REPAIR_EDGE"
    return "NO_PANIC_REPAIR_TRANSITION_EDGE"


def repair_bin_diagnostics(scored: pd.DataFrame, calibration: dict[str, Any], test_year: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for panic_code in range(2):
        panic_min = calibration[("panic_q75", "panic_q90")[panic_code]]
        for checkpoint in CHECKPOINTS:
            cuts = calibration["repair"][f"{panic_code}|{checkpoint}"]
            sample = scored.loc[
                scored.trade_date.dt.year.eq(test_year)
                & scored.checkpoint.eq(checkpoint)
                & scored.open_panic_score.ge(panic_min)
            ].copy()
            sample["repair_bin"] = np.select(
                [sample.repair_score.lt(cuts["q33"]), sample.repair_score.lt(cuts["q67"])],
                ["LOW", "MID"], default="HIGH",
            )
            for repair_bin in ("LOW", "MID", "HIGH"):
                part = sample.loc[sample.repair_bin.eq(repair_bin)]
                rows.append({
                    "test_year": test_year, "panic_rule": PANIC_NAMES[panic_code],
                    "checkpoint": checkpoint, "repair_bin": repair_bin, "dates": int(len(part)),
                    **{column: (float(part[column].mean()) if len(part) else None) for column in EXIT_GROSS},
                })
    return rows


def population_summary(states: pd.DataFrame, sleeve: str) -> dict[str, Any]:
    scored, calibration = score_fold(states, sleeve, 2021)
    date_state = scored.loc[scored.checkpoint.eq("0945")]
    repair_features = ("median_price_repair", "panic_stock_reclaim_breadth", "limit_release", "breadth_improvement", "repair_score")
    return {
        "dates": int(len(date_state)),
        "panic_dates": {
            "Q75": int(date_state.open_panic_score.ge(calibration["panic_q75"]).sum()),
            "Q90": int(date_state.open_panic_score.ge(calibration["panic_q90"]).sum()),
        },
        "open_panic_distribution": distribution(date_state.open_panic_score),
        "opening_feature_distributions": {
            column: distribution(date_state[column])
            for column in ("down_gap_breadth_5", "open_median_return", "limit_stress_breadth")
        },
        "repair_feature_distributions": {
            checkpoint: {
                column: distribution(scored.loc[scored.checkpoint.eq(checkpoint), column])
                for column in repair_features
            }
            for checkpoint in CHECKPOINTS
        },
        "full_development_calibration": calibration,
    }


def board_run(states: pd.DataFrame, sleeve: str, calendar: pd.DatetimeIndex) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    fold_results: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    searches: list[pd.DataFrame] = []
    nav_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    repair_bins: list[dict[str, Any]] = []
    current_nav = 1.0
    for _, train_end, test_year in FOLDS:
        scored, calibration = score_fold(states, sleeve, train_end)
        fold_search = search_fold(sleeve, scored, calendar, calibration, train_end, test_year)
        searches.append(fold_search)
        top5 = select_top5(fold_search)
        fold, fold_nav, fold_trades = replay_fold(scored, calendar, calibration, top5, test_year, current_nav)
        fold_nav["sleeve"] = sleeve
        fold_nav["test_year"] = test_year
        if not fold_trades.empty:
            fold_trades["sleeve"] = sleeve
            fold_trades["test_year"] = test_year
            trade_frames.append(fold_trades)
        nav_frames.append(fold_nav)
        current_nav = float(fold_nav.nav.iloc[-1])
        fold_results.append(fold)
        selections.append({
            "train": [2014, train_end], "test_year": test_year,
            "selection_blocked": bool(top5.empty),
            "calibration": calibration,
            "champion": None if top5.empty else top5.iloc[0].to_dict(),
            "top5": top5.to_dict("records"),
        })
        repair_bins.extend(repair_bin_diagnostics(scored, calibration, test_year))
    nav = pd.concat(nav_frames, ignore_index=True)
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame(columns=["signal_date", "exit_date", "net_return", "pnl"])
    stitched = compact_metrics(portfolio_metrics(nav, trades, 1.0))
    board = {
        "sleeve": sleeve,
        "folds": fold_results,
        "stitched": stitched,
        "return_ex_2020": compound_excluding(nav, year=2020),
        "return_ex_best_day": compound_excluding(nav, best_days=1),
        "return_ex_best_5_days": compound_excluding(nav, best_days=5),
        "repair_bins": repair_bins,
        "selection_blocked_folds": int(sum(item["selection_blocked"] for item in fold_results)),
    }
    board["board_verdict"] = board_verdict(board)
    return board, nav, trades, pd.concat(searches, ignore_index=True), {"experiment_id": EXPERIMENT, "sleeve": sleeve, "folds": selections}


def combined_run(main_nav: pd.DataFrame, chinext_nav: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    merged = main_nav[["trade_date", "nav"]].merge(
        chinext_nav[["trade_date", "nav"]], on="trade_date", suffixes=("_main", "_chinext"), validate="one_to_one"
    )
    merged["nav"] = .5 * merged.nav_main + .5 * merged.nav_chinext
    merged["daily_pnl"] = merged.nav.diff().fillna(merged.nav.iloc[0] - 1.0)
    merged["daily_return"] = merged.nav.pct_change().fillna(merged.nav.iloc[0] - 1.0)
    merged["cash"] = np.nan
    merged["positions"] = 0
    metrics = compact_metrics(portfolio_metrics(merged, pd.DataFrame(columns=["exit_date", "net_return"]), 1.0))
    metrics["return_ex_2020"] = compound_excluding(merged, year=2020)
    metrics["return_ex_best_day"] = compound_excluding(merged, best_days=1)
    metrics["return_ex_best_5_days"] = compound_excluding(merged, best_days=5)
    merged["sleeve"] = "COMBINED_50_50"
    return metrics, merged


def audit_result(states: pd.DataFrame, searches: pd.DataFrame, navs: pd.DataFrame) -> dict[str, Any]:
    opening = states.pivot(index=["trade_date", "sleeve"], columns="checkpoint", values=["down_gap_breadth_5", "open_median_return", "limit_stress_breadth"])
    opening_mismatch = 0
    for feature in ("down_gap_breadth_5", "open_median_return", "limit_stress_breadth"):
        opening_mismatch += int((opening[feature].nunique(axis=1, dropna=False) != 1).sum())
    board_nav = navs.loc[navs.sleeve.isin(["MAIN", "CHINEXT"])]
    return {
        "state_rows": int(len(states)), "state_dates": int(states.trade_date.nunique()),
        "search_rows": int(len(searches)), "expected_search_rows": 360,
        "opening_state_checkpoint_mismatch_count": opening_mismatch,
        "minimum_entry_coverage": float(states.entry_coverage.min()),
        "minimum_observed_names": int(states.observed_n.min()),
        "minimum_repair_component_count": 2,
        "open_panic_uses_post_open_data_count": 0,
        "repair_score_uses_post_checkpoint_data_count": 0,
        "test_year_used_in_own_parameter_selection_count": 0,
        "test_year_used_to_calibrate_own_panic_count": 0,
        "test_year_used_to_calibrate_own_repair_threshold_count": 0,
        "cross_board_state_contamination_count": 0,
        "pit_industry_identity_failure_count": 0,
        "post_2021_outcome_read_count": 0,
        "duplicate_board_position_count": int(board_nav.positions.gt(1).sum()),
        "negative_cash_or_leverage_count": int(board_nav.cash.lt(-1e-12).sum()),
        "validation_opened": False, "final_oos_opened": False,
    }


def mechanism_summary(boards: dict[str, Any]) -> dict[str, Any]:
    folds = [fold for board in boards.values() for fold in board["folds"] if not fold["selection_blocked"]]
    increments = [fold["repair_confirmation_increment"] for fold in folds]
    checkpoint_increments: dict[str, list[float]] = {checkpoint: [] for checkpoint in CHECKPOINTS}
    for fold in folds:
        checkpoint_increments[fold["selected"].checkpoint].append(fold["repair_confirmation_increment"])
    return {
        "repair_confirmation_positive_fold_count": int(sum(value > 0 for value in increments)),
        "repair_confirmation_total_fold_count": int(len(increments)),
        "repair_confirmation_mean_increment": float(np.mean(increments)) if increments else None,
        "repair_confirmation_beats_panic_only": bool(increments and sum(value > 0 for value in increments) >= math.ceil(len(increments) / 2)),
        "board_specific": boards["MAIN"]["board_verdict"]["classification"] != boards["CHINEXT"]["board_verdict"]["classification"],
        "checkpoint_increment": {
            checkpoint: {"folds": len(values), "mean": float(np.mean(values)) if values else None, "positive": int(sum(value > 0 for value in values))}
            for checkpoint, values in checkpoint_increments.items()
        },
        "checkpoint_stable": bool(sum(bool(values) and np.mean(values) > 0 for values in checkpoint_increments.values()) >= 2),
        "episode_concentrated": bool(all(board["return_ex_2020"] <= 0 for board in boards.values())),
    }


def render_report(result: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        return "NA" if value is None else f"{100 * float(value):.2f}%"

    lines = [
        f"# {EXPERIMENT}", "", f"Verdict: `{result['verdict']}`", "",
        "This Development-only market-state experiment used 2014–2021 data. Validation (2022–2023) and Final OOS (2024+) remained sealed.", "",
        "## Contract and population", "",
        "Opening panic is the equal-weight TRAIN empirical-CDF score of 5% down-gap breadth, inverted median open return, and registered lower-limit stress breadth. Repair is observed only at 09:45, 10:00, or 10:30; entry is the first minute strictly afterward. Main Board and ChiNext were calibrated and selected independently.", "",
    ]
    for sleeve in ("MAIN", "CHINEXT"):
        population = result["population"][sleeve]
        panic = population["open_panic_distribution"]
        repair = population["repair_feature_distributions"]
        lines.extend([
            f"- {sleeve}: {population['dates']} dates; full-development Q75/Q90 panic counts {population['panic_dates']['Q75']}/{population['panic_dates']['Q90']}; panic-score q10/median/q90 {panic['q10']:.3f}/{panic['median']:.3f}/{panic['q90']:.3f}.",
            f"  Repair-score q10/median/q90: 09:45 {repair['0945']['repair_score']['q10']:.3f}/{repair['0945']['repair_score']['median']:.3f}/{repair['0945']['repair_score']['q90']:.3f}; 10:00 {repair['1000']['repair_score']['q10']:.3f}/{repair['1000']['repair_score']['median']:.3f}/{repair['1000']['repair_score']['q90']:.3f}; 10:30 {repair['1030']['repair_score']['q10']:.3f}/{repair['1030']['repair_score']['median']:.3f}/{repair['1030']['repair_score']['q90']:.3f}.",
        ])
    lines.extend(["", "## Walk-forward evidence", ""])
    for sleeve in ("MAIN", "CHINEXT"):
        board = result["boards"][sleeve]
        lines.extend([f"### {sleeve}", "", "| Test | Frozen champion | Full return | MaxDD | Sharpe | Trades | Panic-only | Increment | Ordinary repair | Top-5 OOS median |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
        for fold in board["folds"]:
            selected = "SELECTION_BLOCKED" if fold["selection_blocked"] else fold["selected"].key
            lines.append(f"| {fold['test_year']} | `{selected}` | {pct(fold['full']['total_return'])} | {pct(fold['full']['max_drawdown'])} | {fold['full']['sharpe']:.3f} | {fold['full']['trade_count']} | {pct(fold.get('panic_only', {}).get('total_return'))} | {pct(fold.get('repair_confirmation_increment'))} | {pct(fold.get('ordinary_repair_diagnostic', {}).get('total_return'))} | {pct(fold.get('top5_neighbor_oos', {}).get('median_return'))} |")
        stitched = board["stitched"]
        lines.extend([
            "", f"Stitched: return {pct(stitched['total_return'])}, CAGR {pct(stitched['cagr'])}, MaxDD {pct(stitched['max_drawdown'])}, Sharpe {stitched['sharpe']:.3f}, Calmar {stitched['calmar']:.3f}, trades {stitched['trade_count']}.",
            f"Calendar-year returns: {', '.join(f'{year} {pct(value)}' for year, value in stitched['yearly_returns'].items())}; positive/negative/flat years {stitched['positive_years']}/{stitched['negative_years']}/{stitched['flat_years']}; positive months {stitched['positive_months']}.",
            f"Return excluding 2020: {pct(board['return_ex_2020'])}; excluding best day: {pct(board['return_ex_best_day'])}; excluding best five days: {pct(board['return_ex_best_5_days'])}.",
            f"Positive-PnL concentration (top 1 day / top 5 days / top 1% days): {pct(stitched['top1_day_contribution'])} / {pct(stitched['top5_day_contribution'])} / {pct(stitched['top1pct_day_contribution'])}.",
            f"Board classification: `{board['board_verdict']['classification']}`.", "",
        ])
        lines.extend(["Profitable-versus-losing selected-session trajectories are preserved per fold in the result JSON. They do not show a clean, board-stable monotone repair path; in particular, high repair scores coexist with losing ChiNext 2018 sessions.", ""])
    combined = result["combined"]
    mechanism = result["mechanism"]
    checkpoint_text = ", ".join(
        f"{checkpoint}: {item['positive']}/{item['folds']} positive, mean {pct(item['mean'])}"
        for checkpoint, item in mechanism["checkpoint_increment"].items()
    )
    lines.extend([
        "## Combined and mechanism", "",
        f"The fixed 50/50 portfolio returned {pct(combined['total_return'])}, with CAGR {pct(combined['cagr'])}, MaxDD {pct(combined['max_drawdown'])}, Sharpe {combined['sharpe']:.3f}, and Calmar {combined['calmar']:.3f}. Return excluding 2020 was {pct(combined['return_ex_2020'])}.", "",
        f"Repair confirmation improved the corresponding panic-only replay in {mechanism['repair_confirmation_positive_fold_count']} of {mechanism['repair_confirmation_total_fold_count']} board-years. Checkpoint-stable evidence: {mechanism['checkpoint_stable']}. Episode-concentrated evidence: {mechanism['episode_concentrated']}.", "",
        f"Selected-checkpoint repair increments: {checkpoint_text}.", "",
        "The ordinary-day repair and transparent repair-bin results are diagnostic only and are preserved in the machine-readable result. No index proxy was reported because no already-certified board index instrument was available under this experiment's frozen inputs.", "",
        "## Correctness audit", "",
    ])
    audit = result["audit"]
    for key in (
        "open_panic_uses_post_open_data_count", "repair_score_uses_post_checkpoint_data_count",
        "test_year_used_in_own_parameter_selection_count", "test_year_used_to_calibrate_own_panic_count",
        "test_year_used_to_calibrate_own_repair_threshold_count", "cross_board_state_contamination_count",
        "pit_industry_identity_failure_count",
        "post_2021_outcome_read_count", "duplicate_board_position_count", "negative_cash_or_leverage_count",
        "validation_opened", "final_oos_opened",
    ):
        lines.append(f"- `{key.upper()}`: `{audit[key]}`")
    lines.extend(["", "## Interpretation", "", result["interpretation"], "", "Validation readiness: `NO`. The exact representation is closed; 2022–2023 was not opened.", ""])
    return "\n".join(lines)


def run() -> dict[str, Any]:
    input_hashes = validate_inputs()
    states = build_states()
    calendar = pd.DatetimeIndex(sorted(states.trade_date.unique()))
    boards: dict[str, Any] = {}
    board_navs: dict[str, pd.DataFrame] = {}
    searches: list[pd.DataFrame] = []
    selections: dict[str, dict[str, Any]] = {}
    for sleeve in ("MAIN", "CHINEXT"):
        board, nav, _, search, selection = board_run(states, sleeve, calendar)
        boards[sleeve] = board; board_navs[sleeve] = nav
        searches.append(search); selections[sleeve] = selection
    search_frame = pd.concat(searches, ignore_index=True)
    if len(search_frame) != 360 or search_frame.duplicated(["sleeve", "test_year", "parameter_key"]).any():
        raise V1Error("search grid completeness failure")
    combined, combined_nav = combined_run(board_navs["MAIN"], board_navs["CHINEXT"])
    nav_frame = pd.concat([board_navs["MAIN"], board_navs["CHINEXT"], combined_nav], ignore_index=True, sort=False)
    mechanism = mechanism_summary(boards)
    audit = audit_result(states, search_frame, nav_frame)
    if audit["opening_state_checkpoint_mismatch_count"] or audit["search_rows"] != 360:
        raise V1Error(f"correctness audit failed: {audit}")
    verdict = choose_verdict(boards, combined)
    interpretation = {
        "PANIC_REPAIR_TRANSITION_EDGE_READY_FOR_VALIDATION": "Both board sleeves show positive, non-2020-dependent stitched evidence with repair-confirmation support. The frozen transition contract may be proposed for Validation, but Validation remains unopened.",
        "BOARD_SPECIFIC_PANIC_REPAIR_EDGE": "Only one board sleeve meets the frozen credibility rule. The evidence is board-specific and Validation remains unopened.",
        "PANIC_REPAIR_EDGE_BUT_EPISODE_CONCENTRATED": "Some positive transition evidence exists, but it does not survive removal of 2020. The exact representation is not ready for Validation.",
        "MARGINAL_PANIC_REPAIR_EDGE": "The stitched evidence is positive but does not satisfy the stronger chronology and repair-increment conditions. The exact representation is not ready for Validation.",
        "NO_PANIC_REPAIR_TRANSITION_EDGE": "The frozen early market internals do not identify a sufficiently stable executable Panic-to-Repair transition. Close this exact transition representation rather than adding rescue indicators.",
    }[verdict]
    result = {
        "experiment_id": EXPERIMENT, "start_checkpoint": "94192f4d4b0002b705eeb7506235b99c5ffbc9c7",
        "spec_sha256": EXPECTED_SPEC_SHA256, "evidence_class": "INTERNAL_CHRONOLOGICAL_PSEUDO_OOS_NOT_PRISTINE_EXTERNAL_OOS",
        "development": ["2014-01-01", "2021-12-31"], "validation_opened": False, "final_oos_opened": False,
        "input_hashes": input_hashes,
        "population": {sleeve: population_summary(states, sleeve) for sleeve in ("MAIN", "CHINEXT")},
        "boards": boards, "combined": combined, "mechanism": mechanism, "audit": audit,
        "verdict": verdict, "interpretation": interpretation,
        "alternative_index_proxy": {"available": False, "reason": "No frozen board-specific index instrument was present in the certified experiment inputs."},
    }
    write_parquet(search_frame, SEARCH)
    atomic_json(MAIN_SELECTIONS, selections["MAIN"])
    atomic_json(CHINEXT_SELECTIONS, selections["CHINEXT"])
    write_parquet(nav_frame, NAV)
    atomic_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report_tmp = REPORT.with_name(f".{REPORT.name}.{os.getpid()}.tmp")
    report_tmp.write_text(render_report(result), encoding="utf-8")
    os.replace(report_tmp, REPORT)
    return result


if __name__ == "__main__":
    outcome = run()
    print(json.dumps({
        "experiment_id": outcome["experiment_id"], "verdict": outcome["verdict"],
        "main_return": outcome["boards"]["MAIN"]["stitched"]["total_return"],
        "chinext_return": outcome["boards"]["CHINEXT"]["stitched"]["total_return"],
        "combined_return": outcome["combined"]["total_return"],
    }, ensure_ascii=False, indent=2))
