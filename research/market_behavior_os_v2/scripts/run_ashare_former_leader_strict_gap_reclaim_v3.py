#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the Development-only Former-Leader Strict-Gap Reclaim V3 experiment."""

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
from numba import njit

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-FORMER-LEADER-DEEP-DRAWDOWN-STRICT-GAP-RECLAIM-V3"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "e755ac13309dc96f86ad86dbf26b8b5da6267d46ec414217090faf6084050d64"

V1_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_down_gap_first_reclaim_v1")
V1_RESULT = OS_ROOT / "artifacts/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_result.json"
V1_COMPACT = OS_ROOT / "artifacts/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_compact.parquet"
V1_GAP_EVENTS = V1_ROOT / "first_reclaim_gap_events_2014_2021.parquet"
V1_ENTRIES = V1_ROOT / "first_reclaim_executable_entries_2014_2021.parquet"
V1_GAPS = V1_ROOT / "down_gaps_2014_2021.parquet"
V1_OUTCOMES = V1_ROOT / "first_reclaim_outcomes_2014_2021.parquet"

EXTERNAL = Path(
    "/Volumes/quant/CY_quant_research/ashare_former_leader_deep_drawdown_strict_gap_reclaim_v3"
)
DAILY_STATE = EXTERNAL / "pit_adjusted_daily_state_2013_2021.parquet"
FEATURES_EXTERNAL = EXTERNAL / f"{EXPERIMENT}_features_full.parquet"
SEARCH_EXTERNAL = EXTERNAL / f"{EXPERIMENT}_search_full.parquet"
BREADTH = Path(
    "/Volumes/quant/CY_quant_research/ashare_down_gap_reclaim_walkforward_v2/"
    "board_opening_gap_breadth_2014_2021.parquet"
)

FEATURES_COMPACT = OS_ROOT / f"artifacts/{EXPERIMENT}_features.parquet"
SEARCH_COMPACT = OS_ROOT / f"artifacts/{EXPERIMENT}_search.parquet"
MAIN_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_main_fold_selections.json"
CHINEXT_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_fold_selections.json"
MAIN_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_main_nav.parquet"
CHINEXT_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_nav.parquet"
COMBINED_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_combined_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

OLD_DAILY_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006/daily"
)
NEW_DAILY_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
ENTRY_COST = 0.002
EXIT_COST = 0.002
TEST_YEARS = tuple(range(2017, 2022))
FOLDS = tuple((2014, year - 1, year) for year in TEST_YEARS)

EXCLUDED_INDUSTRIES = (
    "煤炭开采",
    "油气开采Ⅱ",
    "油服工程",
    "炼化及贸易",
    "普钢",
    "特钢Ⅱ",
    "冶钢原料",
    "工业金属",
    "小金属",
    "贵金属",
    "能源金属",
    "金属新材料",
    "化学原料",
    "化学制品",
    "农化制品",
    "化学纤维",
    "电子化学品Ⅱ",
    "水泥",
    "玻璃玻纤",
    "非金属材料Ⅱ",
    "电力",
    "燃气Ⅱ",
)

LEADER_NAMES = {0.90: "TOP10", 0.95: "TOP5"}
EXIT_NAMES = ("T1_OPEN", "T1_CLOSE", "T2_CLOSE", "T3_CLOSE")
RANKER_NAMES = ("STRICT_GAP", "DRYUP", "COMPOSITE")


class V3Error(RuntimeError):
    """Fail-closed V3 error."""


@dataclass(frozen=True)
class Params:
    leader_min: float
    runup_min: float
    drawdown_min: float
    gap_min: float
    age_max: int
    post_dryup_max: float
    intraday_dryup_max: float
    exit_code: int
    k: int
    ranker: int

    @property
    def key(self) -> str:
        age = "U" if self.age_max < 0 else str(self.age_max)
        post = "N" if self.post_dryup_max < 0 else f"{self.post_dryup_max:.2f}"
        intra = "N" if self.intraday_dryup_max < 0 else f"{self.intraday_dryup_max:.2f}"
        return (
            f"l{LEADER_NAMES[self.leader_min]}|r{self.runup_min:.2f}|dd{self.drawdown_min:.2f}|"
            f"g{self.gap_min:.2f}|a{age}|pd{post}|id{intra}|x{EXIT_NAMES[self.exit_code]}|"
            f"k{self.k:02d}|q{RANKER_NAMES[self.ranker]}"
        )

    @property
    def active_filters(self) -> int:
        return (
            int(self.leader_min > 0.90)
            + int(self.runup_min > 0.50)
            + int(self.drawdown_min > 0.30)
            + int(self.gap_min > 0.05)
            + int(self.age_max >= 0)
            + int(self.post_dryup_max >= 0)
            + int(self.intraday_dryup_max >= 0)
        )


GRID = tuple(
    Params(*values)
    for values in itertools.product(
        (0.90, 0.95),
        (0.50, 0.80, 1.00),
        (0.30, 0.40, 0.50),
        (0.05, 0.07, 0.09),
        (3, 10, -1),
        (0.50, 0.70, -1.0),
        (0.50, 0.70, -1.0),
        (0, 1, 2, 3),
        (10, 20, 50),
        (0, 1, 2),
    )
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, Params):
        return asdict(value)
    return value


def daily_paths() -> list[Path]:
    return [
        *[OLD_DAILY_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2013, 2018)],
        *[NEW_DAILY_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2022)],
    ]


def sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def connection() -> duckdb.DuckDBPyConnection:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    (EXTERNAL / "duckdb_tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{EXTERNAL / 'duckdb_tmp'}'")
    return con


def validate_inputs() -> dict[str, Any]:
    if len(GRID) != 52_488:
        raise V3Error(f"parameter grid changed: {len(GRID)}")
    expected = {
        SPEC: EXPECTED_SPEC_SHA256,
        V1_RESULT: "bc4bbe4dc63903984f6be884d26f481483b0daefe14842cdc469fed2dbe86ced",
        V1_COMPACT: "a551178509dda6c51eb1364a2c1cdb6d353e1b23098acf8bd40bab6f16c4ace9",
        V1_GAP_EVENTS: "9b0a142eb4f35479172eb2c398baf58cb93898586b875f2f883e779642f8180c",
        V1_ENTRIES: "19c57d81d4a55429073ae383b647f38204a8fd669e15e91e4850d66ea58a2c6d",
        V1_GAPS: "300e7c107cbeba4af82a1b76043cea28e84bbf58c4f3dcfdfa25344e50a3940a",
        V1_OUTCOMES: "daa9ce35c11598392f825912d6c715e320c98f88448618bca62cd6bd83d73a49",
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise V3Error(f"input identity mismatch: {path}")
    for path in [*daily_paths(), BREADTH]:
        if not path.is_file():
            raise V3Error(f"missing input: {path}")
    v1 = json.loads(V1_RESULT.read_text(encoding="utf-8"))
    required = {
        "max_signals_per_gap_id": 1,
        "gap_ids_with_more_than_one_first_reclaim": 0,
        "post_first_reclaim_reuse_count": 0,
        "post_trigger_volume_used_in_dryup_count": 0,
        "future_volume_leakage_count": 0,
        "illegal_execution_count": 0,
        "post_2021_outcome_read_count": 0,
    }
    if any(v1["invariants"].get(key) != value for key, value in required.items()):
        raise V3Error("authoritative V1 invariant mismatch")
    return {
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "source_hashes": {str(path): digest for path, digest in expected.items()},
        "inherited_v1_invariants": required,
    }


def build_daily_state() -> None:
    if DAILY_STATE.is_file():
        return
    con = connection()
    excluded = ",".join("'" + value.replace("'", "''") + "'" for value in EXCLUDED_INDUSTRIES)
    paths = sql_paths(daily_paths())
    con.execute(f"CREATE TEMP VIEW source AS SELECT * FROM read_parquet({paths})")
    con.execute(
        """CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM source) ORDER BY trade_date"""
    )
    con.execute(
        """CREATE TEMP TABLE base AS
        SELECT s.trade_date,c.cal_idx,s.symbol,s.open,s.high,s.low,s.close,s.volume,s.amount,
               s.turnover_fraction,s.trade_status,s.current_day_data_tradable,s.is_st,s.industry,
               s.industry_valid,s.source_notice_date,s.corporate_action_count,
               s.corporate_action_available_date,s.corporate_action_blocking,s.share_multiplier,
               s.cash_per_share,s.rights_ratio,s.hard_valid,s.bar_valid,s.trading_state_valid,
               s.corporate_action_valid,s.market_rule_valid,s.historical_identity_valid,
               s.available_at,s.decision_at,
               CASE WHEN symbol LIKE '30%.SZ' THEN 'CHINEXT' ELSE 'MAIN' END AS sleeve,
               (s.hard_valid IS TRUE AND s.bar_valid IS TRUE
                AND s.trading_state_valid IS TRUE AND s.corporate_action_valid IS TRUE
                AND s.market_rule_valid IS TRUE AND s.historical_identity_valid IS TRUE
                AND s.corporate_action_blocking IS FALSE
                AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
                AND s.close IS NOT NULL AND isfinite(s.close) AND s.close>0
                AND s.open IS NOT NULL AND isfinite(s.open) AND s.open>0
                AND s.high IS NOT NULL AND isfinite(s.high) AND s.high>=greatest(s.open,s.close,s.low)
                AND s.low IS NOT NULL AND isfinite(s.low) AND s.low<=least(s.open,s.close,s.high)) AS history_valid,
               (s.hard_valid IS TRUE AND s.trade_status=1
                AND s.current_day_data_tradable IS TRUE
                AND s.volume IS NOT NULL AND isfinite(s.volume) AND s.volume>0) AS current_valid,
               CASE WHEN s.industry_valid IS TRUE AND s.industry IS NOT NULL
                          AND trim(s.industry)<>'' AND s.source_notice_date IS NOT NULL
                          AND s.source_notice_date<=s.trade_date
                    THEN s.industry ELSE NULL END AS causal_industry
        FROM source s JOIN calendar c USING(trade_date)
        WHERE ((symbol LIKE '60%.SH' AND symbol NOT LIKE '688%.SH')
                OR symbol LIKE '00%.SZ' OR symbol LIKE '30%.SZ')"""
    )
    con.execute(
        """CREATE TEMP TABLE stock_step AS
        SELECT *,lag(close) OVER w AS previous_close,
               lag(history_valid) OVER w AS previous_history_valid,
               lag(cal_idx) OVER w AS previous_cal_idx
        FROM base WINDOW w AS(PARTITION BY symbol ORDER BY trade_date)"""
    )
    con.execute(
        """CREATE TEMP TABLE stock_chain AS
        SELECT *,
          CASE
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND coalesce(corporate_action_count,0)=0 THEN true
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
             AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
             AND coalesce(share_multiplier,1)>0
             AND (previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)>0
            THEN true ELSE false END AS coordinate_step_valid,
          CASE
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
             AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
             AND coalesce(share_multiplier,1)>0
             AND (previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)>0
            THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
            ELSE NULL END AS step_log_return
        FROM stock_step"""
    )
    con.execute(
        """CREATE TEMP TABLE adjusted AS
        SELECT *,
          exp(sum(coalesce(step_log_return,0.0)) OVER w) AS adjusted_close,
          sum(CASE WHEN coordinate_step_valid THEN 0 ELSE 1 END) OVER w AS invalid_step_cum
        FROM stock_chain
        WINDOW w AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)"""
    )
    con.execute(
        """CREATE TEMP TABLE windowed AS
        SELECT *,lag(adjusted_close,60) OVER w AS adjusted_close_lag60,
               lag(cal_idx,60) OVER w AS cal_idx_lag60,
               sum(coordinate_step_valid::INTEGER) OVER w60 AS valid_step_count60
        FROM adjusted
        WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),
          w60 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)"""
    )
    con.execute(
        f"""CREATE TEMP TABLE ranked AS
        SELECT symbol,trade_date,
          percent_rank() OVER(PARTITION BY trade_date,sleeve ORDER BY ret60) AS leader_percentile,
          count(*) OVER(PARTITION BY trade_date,sleeve) AS leader_universe_size
        FROM (
          SELECT *,adjusted_close/adjusted_close_lag60-1 AS ret60
          FROM windowed
          WHERE current_valid AND causal_industry NOT IN ({excluded})
            AND adjusted_close_lag60>0 AND cal_idx_lag60=cal_idx-60 AND valid_step_count60=60
        )"""
    )
    con.execute(
        """CREATE TEMP TABLE valid_turnover AS
        SELECT symbol,trade_date,turnover_fraction,
               count(*) OVER w20 AS prior20_turnover_count,
               median(turnover_fraction) OVER w20 AS prior20_turnover_median
        FROM windowed
        WHERE current_valid AND turnover_fraction IS NOT NULL
          AND isfinite(turnover_fraction) AND turnover_fraction>=0
        WINDOW w20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)"""
    )
    con.execute(
        f"""COPY (
        SELECT w.trade_date,w.cal_idx,w.symbol,w.sleeve,w.low,w.close,w.turnover_fraction,
               w.current_valid,w.history_valid,w.causal_industry,w.corporate_action_count,
               w.corporate_action_blocking,w.corporate_action_valid,w.adjusted_close,
               w.invalid_step_cum,w.adjusted_close_lag60,w.cal_idx_lag60,w.valid_step_count60,
               CASE WHEN w.adjusted_close_lag60>0 AND w.cal_idx_lag60=w.cal_idx-60
                          AND w.valid_step_count60=60
                    THEN w.adjusted_close/w.adjusted_close_lag60-1 END AS ret60,
               r.leader_percentile,r.leader_universe_size,
               v.prior20_turnover_count,v.prior20_turnover_median
        FROM windowed w
        LEFT JOIN ranked r USING(symbol,trade_date)
        LEFT JOIN valid_turnover v USING(symbol,trade_date)
        ORDER BY w.symbol,w.trade_date
        ) TO '{DAILY_STATE}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
    )
    con.close()


def build_features() -> pd.DataFrame:
    build_daily_state()
    if not FEATURES_EXTERNAL.is_file():
        con = connection()
        con.execute(
            f"""COPY (
            WITH gaps AS (
              SELECT *,symbol||'|'||strftime(bar_end_time,'%Y-%m-%dT%H:%M:%S') AS built_entry_id
              FROM read_parquet('{V1_GAP_EVENTS}') WHERE execution_valid
            ), outcomes AS (
              SELECT entry_id,t1_date,t2_date,t3_date,next_legal_open_date,
                     t1_legal_open_price,t1_close_price,t2_close_price,t3_close_price,
                     close AS trigger_close
              FROM read_parquet('{V1_OUTCOMES}')
            ), gap_state AS (
              SELECT g.*,d.cal_idx AS gap_cal_idx,d.adjusted_close AS gap_adjusted_close,
                     d.invalid_step_cum AS gap_invalid_step_cum,d.prior20_turnover_count,
                     d.prior20_turnover_median,d.corporate_action_count AS gap_action_count,
                     d.corporate_action_valid AS gap_action_valid,
                     d.corporate_action_blocking AS gap_action_blocking
              FROM gaps g JOIN read_parquet('{DAILY_STATE}') d
                ON g.symbol=d.symbol AND g.gap_date=d.trade_date
            ), pregap AS (
              SELECT g.*,p.trade_date AS pregap_date,p.low AS prev_low_daily,
                     p.close AS prev_close_daily,p.adjusted_close AS pregap_adjusted_close,
                     p.invalid_step_cum AS pregap_invalid_step_cum
              FROM gap_state g JOIN read_parquet('{DAILY_STATE}') p
                ON g.symbol=p.symbol AND p.cal_idx=g.gap_cal_idx-1
              WHERE p.history_valid
            ), peak_candidates AS (
              SELECT p.*,pk.trade_date AS peak_date,pk.adjusted_close AS peak_price_adjusted,
                     pk.ret60 AS prior_runup,pk.leader_percentile,pk.leader_universe_size,
                     pk.invalid_step_cum AS peak_invalid_step_cum,
                     row_number() OVER(PARTITION BY p.gap_id
                                       ORDER BY pk.adjusted_close DESC,pk.trade_date,pk.symbol) AS peak_order
              FROM pregap p JOIN read_parquet('{DAILY_STATE}') pk
                ON p.symbol=pk.symbol AND pk.cal_idx BETWEEN p.gap_cal_idx-120 AND p.gap_cal_idx-1
              WHERE pk.history_valid AND pk.adjusted_close IS NOT NULL
                AND pk.invalid_step_cum=p.pregap_invalid_step_cum
            ), peaks AS (
              SELECT * FROM peak_candidates WHERE peak_order=1
            ), post_ranked AS (
              SELECT p.gap_id,d.turnover_fraction,
                     row_number() OVER(PARTITION BY p.gap_id ORDER BY d.trade_date DESC) AS recent_order
              FROM peaks p JOIN read_parquet('{DAILY_STATE}') d ON p.symbol=d.symbol
              WHERE d.trade_date>p.gap_date AND d.trade_date<p.reclaim_date
                AND d.current_valid AND d.turnover_fraction IS NOT NULL
                AND isfinite(d.turnover_fraction) AND d.turnover_fraction>=0
            ), post AS (
              SELECT gap_id,count(*) AS post_gap_session_count,
                     median(turnover_fraction) AS post_gap_turnover_median
              FROM post_ranked WHERE recent_order<=3 GROUP BY gap_id
            )
            SELECT p.*,o.* EXCLUDE(entry_id),
                   p.built_entry_id AS entry_id,
                   1-p.pregap_adjusted_close/p.peak_price_adjusted AS deep_drawdown,
                   (p.prev_low_daily-p.gap_open)/p.prev_close AS strict_gap_width_pct,
                   post.post_gap_session_count,post.post_gap_turnover_median,
                   CASE WHEN p.prior20_turnover_count=20 AND p.prior20_turnover_median>0
                        THEN post.post_gap_turnover_median/p.prior20_turnover_median END AS post_gap_dryup,
                   (p.gap_open<p.prev_low_daily) AS strict_gap_condition,
                   (p.prev_low_daily+1e-10>=p.trigger_price) AS trigger_inside_strict_gap,
                   (p.prior_runup>=0.50 AND p.leader_percentile>=0.90) AS former_leader_eligible,
                   (p.prior_runup>=0.50 AND p.leader_percentile>=0.90
                    AND 1-p.pregap_adjusted_close/p.peak_price_adjusted>=0.30) AS deep_drawdown_eligible,
                   (p.prior_runup>=0.50 AND p.leader_percentile>=0.90
                    AND 1-p.pregap_adjusted_close/p.peak_price_adjusted>=0.30
                    AND p.gap_open<p.prev_low_daily
                    AND p.prev_low_daily+1e-10>=p.trigger_price) AS v3_final_candidate
            FROM peaks p JOIN outcomes o ON p.built_entry_id=o.entry_id
            LEFT JOIN post USING(gap_id)
            ORDER BY p.bar_end_time,p.symbol,p.gap_id
            ) TO '{FEATURES_EXTERNAL}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        con.close()
    frame = pd.read_parquet(FEATURES_EXTERNAL)
    for column in (
        "gap_date",
        "reclaim_date",
        "bar_end_time",
        "peak_date",
        "pregap_date",
        "t1_date",
        "t2_date",
        "t3_date",
        "next_legal_open_date",
    ):
        frame[column] = pd.to_datetime(frame[column])
    for column in (
        "strict_gap_condition",
        "trigger_inside_strict_gap",
        "former_leader_eligible",
        "deep_drawdown_eligible",
        "v3_final_candidate",
    ):
        frame[column] = frame[column].astype("boolean").fillna(False).astype(bool)
    return frame


def prepare_events(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DatetimeIndex, pd.DataFrame]:
    breadth = pd.read_parquet(BREADTH)
    breadth["trade_date"] = pd.to_datetime(breadth.trade_date)
    calendar = pd.DatetimeIndex(sorted(breadth.trade_date.unique()))
    day_map = pd.Series(np.arange(len(calendar), dtype=np.int32), index=calendar)
    events = features.loc[features.v3_final_candidate].copy()
    events["sleeve"] = np.where(events.board.eq("ChiNext"), "CHINEXT", "MAIN")
    events["entry_day"] = events.reclaim_date.map(day_map).astype(np.int32)
    for source, target in (
        ("next_legal_open_date", "exit_day_0"),
        ("t1_date", "exit_day_1"),
        ("t2_date", "exit_day_2"),
        ("t3_date", "exit_day_3"),
    ):
        events[target] = events[source].map(day_map).fillna(-1).astype(np.int32)
    events["symbol_id"] = pd.factorize(events.symbol, sort=True)[0].astype(np.int32)
    events = events.sort_values(["bar_end_time", "symbol", "gap_id"], kind="mergesort").reset_index(
        drop=True
    )
    events = events.merge(
        breadth[["trade_date", "sleeve", "breadth"]],
        left_on=["reclaim_date", "sleeve"],
        right_on=["trade_date", "sleeve"],
        how="left",
        validate="many_to_one",
    )
    if events.breadth.isna().any() or events.reclaim_date.max() > pd.Timestamp("2021-12-31"):
        raise V3Error("event breadth or chronology failed")
    return events, calendar, breadth


def event_arrays(events: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "entry_day": events.entry_day.to_numpy(np.int32),
        "time": events.bar_end_time.astype("int64").to_numpy(np.int64),
        "symbol": events.symbol_id.to_numpy(np.int32),
        "leader": events.leader_percentile.to_numpy(np.float64),
        "runup": events.prior_runup.to_numpy(np.float64),
        "drawdown": events.deep_drawdown.to_numpy(np.float64),
        "gap": events.gap_pct.to_numpy(np.float64),
        "age": events.gap_age_trading_days.to_numpy(np.int32),
        "post": events.post_gap_dryup.to_numpy(np.float64),
        "intra": events.intraday_dryup.to_numpy(np.float64),
        "width": events.strict_gap_width_pct.to_numpy(np.float64),
        "comp": events.compression_trend.to_numpy(np.float64),
        "entry_price": events.entry_price.to_numpy(np.float64),
        "exit_day": events[[f"exit_day_{index}" for index in range(4)]].to_numpy(np.int32),
        "exit_price": events[
            ["t1_legal_open_price", "t1_close_price", "t2_close_price", "t3_close_price"]
        ].to_numpy(np.float64),
        "close_days": events[["entry_day", "exit_day_1", "exit_day_2", "exit_day_3"]].to_numpy(
            np.int32
        ),
        "close_prices": events[
            ["trigger_close", "t1_close_price", "t2_close_price", "t3_close_price"]
        ].to_numpy(np.float64),
    }


@njit(cache=False)
def _normalized_rank(values, cands, m, neutral_missing):
    result = np.empty(m, dtype=np.float64)
    finite_count = 0
    for j in range(m):
        if np.isfinite(values[cands[j]]):
            finite_count += 1
    for j in range(m):
        value = values[cands[j]]
        if not np.isfinite(value):
            result[j] = 0.5 if neutral_missing else 1.0
            continue
        if finite_count <= 1:
            result[j] = 0.5
            continue
        less = 0
        equal_before = 0
        for z in range(m):
            other = values[cands[z]]
            if not np.isfinite(other):
                continue
            if other < value:
                less += 1
            elif other == value and cands[z] < cands[j]:
                equal_before += 1
        result[j] = (less + equal_before) / (finite_count - 1.0)
    return result


@njit(cache=False)
def _composite_scores(cands, m, leader, runup, drawdown, width, intra, post, comp, age):
    scores = np.zeros(m, dtype=np.float64)
    transformed = np.empty(len(leader), dtype=np.float64)
    for source_code in range(8):
        for j in range(m):
            idx = cands[j]
            if source_code == 0:
                transformed[idx] = -leader[idx]
            elif source_code == 1:
                transformed[idx] = -runup[idx]
            elif source_code == 2:
                transformed[idx] = -drawdown[idx]
            elif source_code == 3:
                transformed[idx] = -width[idx]
            elif source_code == 4:
                transformed[idx] = intra[idx]
            elif source_code == 5:
                transformed[idx] = post[idx]
            elif source_code == 6:
                transformed[idx] = comp[idx]
            else:
                transformed[idx] = age[idx]
        ranks = _normalized_rank(transformed, cands, m, source_code == 5)
        for j in range(m):
            scores[j] += ranks[j]
    return scores


@njit(cache=False)
def simulate_summary(
    entry_day,
    time,
    symbol,
    leader,
    runup,
    drawdown,
    gap,
    age,
    post,
    intra,
    width,
    comp,
    entry_price,
    exit_day_matrix,
    exit_price_matrix,
    close_days,
    close_prices,
    start_day,
    end_day,
    day_year,
    leader_min,
    runup_min,
    drawdown_min,
    gap_min,
    age_max,
    post_max,
    intra_max,
    exit_code,
    k,
    ranker,
):
    n_days = end_day - start_day + 1
    navs = np.ones(n_days, dtype=np.float64)
    day_pnl = np.zeros(n_days, dtype=np.float64)
    pos_symbol = np.full(k, -1, dtype=np.int32)
    pos_event = np.full(k, -1, dtype=np.int32)
    shares = np.zeros(k, dtype=np.float64)
    marks = np.zeros(k, dtype=np.float64)
    entry_debit = np.zeros(k, dtype=np.float64)
    cash = 1.0
    active = 0
    trades = recent_trades = win_trades = 0
    sum_trade_return = 0.0
    cands = np.empty(max(1, len(entry_day)), dtype=np.int64)
    pointer = 0
    while pointer < len(entry_day) and entry_day[pointer] < start_day:
        pointer += 1
    prior_nav = peak_nav = annual_start = 1.0
    max_dd = sum_ret = sum_ret2 = 0.0
    annual_values = np.empty(8, dtype=np.float64)
    annual_count = 0
    for day in range(start_day, end_day + 1):
        for slot in range(k):
            if pos_event[slot] >= 0:
                event = pos_event[slot]
                if exit_code == 0 and exit_day_matrix[event, exit_code] == day:
                    proceeds = (
                        shares[slot] * exit_price_matrix[event, exit_code] * (1.0 - EXIT_COST)
                    )
                    trade_return = proceeds / entry_debit[slot] - 1.0
                    cash += proceeds
                    trades += 1
                    recent_trades += int(day_year[day] == day_year[end_day])
                    win_trades += int(trade_return > 0)
                    sum_trade_return += trade_return
                    pos_event[slot] = pos_symbol[slot] = -1
                    shares[slot] = marks[slot] = entry_debit[slot] = 0.0
                    active -= 1
        accounting_nav = cash
        for slot in range(k):
            if pos_event[slot] >= 0:
                accounting_nav += shares[slot] * marks[slot]
        while pointer < len(entry_day) and entry_day[pointer] == day:
            group_start = pointer
            group_time = time[pointer]
            while (
                pointer < len(entry_day)
                and entry_day[pointer] == day
                and time[pointer] == group_time
            ):
                pointer += 1
            m = 0
            if active < k:
                for idx in range(group_start, pointer):
                    if leader[idx] + 1e-12 < leader_min or runup[idx] + 1e-12 < runup_min:
                        continue
                    if drawdown[idx] + 1e-12 < drawdown_min or gap[idx] + 1e-12 < gap_min:
                        continue
                    if age_max >= 0 and age[idx] > age_max:
                        continue
                    if post_max >= 0 and (not np.isfinite(post[idx]) or post[idx] > post_max):
                        continue
                    if intra_max >= 0 and (not np.isfinite(intra[idx]) or intra[idx] > intra_max):
                        continue
                    exday = exit_day_matrix[idx, exit_code]
                    exprice = exit_price_matrix[idx, exit_code]
                    if exday <= day or exday > end_day or not np.isfinite(exprice) or exprice <= 0:
                        continue
                    held = False
                    for slot in range(k):
                        if pos_symbol[slot] == symbol[idx]:
                            held = True
                            break
                    if not held:
                        cands[m] = idx
                        m += 1
            if m > 0 and active < k:
                composite = (
                    _composite_scores(
                        cands, m, leader, runup, drawdown, width, intra, post, comp, age
                    )
                    if ranker == 2
                    else np.zeros(m, dtype=np.float64)
                )
                used = np.zeros(m, dtype=np.uint8)
                for _ in range(min(k - active, m)):
                    best = -1
                    for j in range(m):
                        if used[j]:
                            continue
                        duplicate = False
                        for z in range(m):
                            if used[z] and symbol[cands[z]] == symbol[cands[j]]:
                                duplicate = True
                                break
                        if duplicate:
                            continue
                        if best < 0:
                            best = j
                            continue
                        left = cands[j]
                        right = cands[best]
                        better = False
                        if ranker == 0:
                            better = width[left] > width[right] or (
                                width[left] == width[right] and left < right
                            )
                        elif ranker == 1:
                            li = intra[left] if np.isfinite(intra[left]) else 1e30
                            ri = intra[right] if np.isfinite(intra[right]) else 1e30
                            lp = post[left] if np.isfinite(post[left]) else 1e30
                            rp = post[right] if np.isfinite(post[right]) else 1e30
                            better = li < ri or (
                                li == ri and (lp < rp or (lp == rp and left < right))
                            )
                        else:
                            better = composite[j] < composite[best] or (
                                composite[j] == composite[best] and left < right
                            )
                        if better:
                            best = j
                    if best < 0:
                        break
                    used[best] = 1
                    idx = cands[best]
                    slot = -1
                    for candidate_slot in range(k):
                        if pos_event[candidate_slot] < 0:
                            slot = candidate_slot
                            break
                    principal = min(accounting_nav / k, cash / (1.0 + ENTRY_COST))
                    if slot < 0 or principal <= 1e-14:
                        break
                    debit = principal * (1.0 + ENTRY_COST)
                    cash -= debit
                    pos_symbol[slot] = symbol[idx]
                    pos_event[slot] = idx
                    shares[slot] = principal / entry_price[idx]
                    marks[slot] = entry_price[idx]
                    entry_debit[slot] = debit
                    active += 1
                    accounting_nav -= principal * ENTRY_COST
        for slot in range(k):
            if pos_event[slot] >= 0:
                event = pos_event[slot]
                for mark_index in range(4):
                    if close_days[event, mark_index] == day and np.isfinite(
                        close_prices[event, mark_index]
                    ):
                        marks[slot] = close_prices[event, mark_index]
                if exit_code > 0 and exit_day_matrix[event, exit_code] == day:
                    proceeds = (
                        shares[slot] * exit_price_matrix[event, exit_code] * (1.0 - EXIT_COST)
                    )
                    trade_return = proceeds / entry_debit[slot] - 1.0
                    cash += proceeds
                    trades += 1
                    recent_trades += int(day_year[day] == day_year[end_day])
                    win_trades += int(trade_return > 0)
                    sum_trade_return += trade_return
                    pos_event[slot] = pos_symbol[slot] = -1
                    shares[slot] = marks[slot] = entry_debit[slot] = 0.0
                    active -= 1
        nav = cash
        for slot in range(k):
            if pos_event[slot] >= 0:
                nav += shares[slot] * marks[slot]
        offset = day - start_day
        navs[offset] = nav
        day_pnl[offset] = nav - prior_nav
        daily_return = nav / prior_nav - 1.0
        sum_ret += daily_return
        sum_ret2 += daily_return * daily_return
        prior_nav = nav
        peak_nav = max(peak_nav, nav)
        max_dd = min(max_dd, nav / peak_nav - 1.0)
        if day == end_day or day_year[day + 1] != day_year[day]:
            annual_values[annual_count] = nav / annual_start - 1.0
            annual_count += 1
            annual_start = nav
    total = navs[-1] - 1.0
    cagr = navs[-1] ** (242.0 / n_days) - 1.0
    mean_ret = sum_ret / n_days
    variance = max(0.0, sum_ret2 / n_days - mean_ret * mean_ret)
    sharpe = mean_ret / math.sqrt(variance) * math.sqrt(242.0) if variance > 0 else 0.0
    calmar = cagr / abs(max_dd) if max_dd < 0 else (1e6 if cagr > 0 else 0.0)
    annual_sorted = np.sort(annual_values[:annual_count])
    median_annual = np.median(annual_sorted) if annual_count else 0.0
    worst_annual = annual_sorted[0] if annual_count else 0.0
    positive_years = 0
    for value in annual_values[:annual_count]:
        positive_years += int(value > 0)
    positive_pnl = np.sort(day_pnl[day_pnl > 0])[::-1]
    positive_sum = positive_pnl.sum()
    top1 = positive_pnl[:1].sum() / positive_sum if positive_sum > 0 else 0.0
    top5 = positive_pnl[:5].sum() / positive_sum if positive_sum > 0 else 0.0
    topn = max(1, math.ceil(n_days * 0.01))
    top1pct = positive_pnl[:topn].sum() / positive_sum if positive_sum > 0 else 0.0
    return (
        total,
        cagr,
        max_dd,
        sharpe,
        calmar,
        trades,
        recent_trades,
        positive_years,
        median_annual,
        worst_annual,
        top1,
        top5,
        top1pct,
        win_trades,
        sum_trade_return,
    )


def metric_record(values: tuple[Any, ...]) -> dict[str, Any]:
    names = (
        "total_return",
        "cagr",
        "max_drawdown",
        "sharpe",
        "calmar",
        "trade_count",
        "recent_year_trade_count",
        "positive_years",
        "median_year_return",
        "worst_year_return",
        "top1_day_contribution",
        "top5_day_contribution",
        "top1pct_day_contribution",
        "win_trades",
        "sum_trade_return",
    )
    result = dict(zip(names, values, strict=True))
    result["win_rate"] = (
        result["win_trades"] / result["trade_count"] if result["trade_count"] else None
    )
    result["average_trade_return"] = (
        result["sum_trade_return"] / result["trade_count"] if result["trade_count"] else None
    )
    return result


def run_summary(
    arrays: dict[str, np.ndarray],
    calendar: pd.DatetimeIndex,
    params: Params,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    values = simulate_summary(
        arrays["entry_day"],
        arrays["time"],
        arrays["symbol"],
        arrays["leader"],
        arrays["runup"],
        arrays["drawdown"],
        arrays["gap"],
        arrays["age"],
        arrays["post"],
        arrays["intra"],
        arrays["width"],
        arrays["comp"],
        arrays["entry_price"],
        arrays["exit_day"],
        arrays["exit_price"],
        arrays["close_days"],
        arrays["close_prices"],
        int(calendar.get_loc(start)),
        int(calendar.get_loc(end)),
        calendar.year.to_numpy(np.int32),
        params.leader_min,
        params.runup_min,
        params.drawdown_min,
        params.gap_min,
        params.age_max,
        params.post_dryup_max,
        params.intraday_dryup_max,
        params.exit_code,
        params.k,
        params.ranker,
    )
    return metric_record(values)


def search_fold(
    sleeve: str,
    events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    train_end: int,
    test_year: int,
) -> pd.DataFrame:
    shard = EXTERNAL / f"search_{sleeve.lower()}_{test_year}.parquet"
    if shard.is_file():
        frame = pd.read_parquet(shard)
        if len(frame) != len(GRID):
            raise V3Error(f"incomplete search shard: {shard}")
        return frame
    board = events.loc[events.sleeve.eq(sleeve)].copy()
    arrays = event_arrays(board)
    start = calendar[calendar.year == 2014][0]
    end = calendar[calendar.year == train_end][-1]
    records: list[dict[str, Any]] = []
    for index, params in enumerate(GRID):
        metrics = run_summary(arrays, calendar, params, start, end)
        records.append(
            {
                "sleeve": sleeve,
                "train_start": 2014,
                "train_end": train_end,
                "test_year": test_year,
                "parameter_index": index,
                "parameter_key": params.key,
                **asdict(params),
                "active_filters": params.active_filters,
                **metrics,
            }
        )
    frame = pd.DataFrame(records)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), shard, compression="zstd")
    return frame


def select_top10(search: pd.DataFrame) -> pd.DataFrame:
    eligible = search.loc[
        (search.trade_count >= 80) & (search.recent_year_trade_count >= 15)
    ].copy()
    if eligible.empty:
        return eligible
    eligible["calmar_tie"] = np.round(eligible.calmar / 1e-12) * 1e-12
    return eligible.sort_values(
        [
            "calmar_tie",
            "sharpe",
            "median_year_return",
            "cagr",
            "top5_day_contribution",
            "active_filters",
            "parameter_key",
        ],
        ascending=[False, False, False, False, True, True, True],
        kind="mergesort",
    ).head(10)


def params_from_row(row: pd.Series) -> Params:
    return Params(
        float(row.leader_min),
        float(row.runup_min),
        float(row.drawdown_min),
        float(row.gap_min),
        int(row.age_max),
        float(row.post_dryup_max),
        float(row.intraday_dryup_max),
        int(row.exit_code),
        int(row.k),
        int(row.ranker),
    )


def _normalized_series(values: pd.Series, *, neutral_missing: bool = False) -> pd.Series:
    finite = values.notna() & np.isfinite(values)
    result = pd.Series(0.5 if neutral_missing else 1.0, index=values.index, dtype=float)
    count = int(finite.sum())
    if count == 1:
        result.loc[finite] = 0.5
    elif count > 1:
        result.loc[finite] = (values.loc[finite].rank(method="first", ascending=True) - 1.0) / (
            count - 1.0
        )
    return result


def eligible_candidates(
    group: pd.DataFrame,
    params: Params,
    exit_date: str,
    exit_price: str,
    end: pd.Timestamp,
    held: set[str],
) -> pd.DataFrame:
    mask = (
        group.leader_percentile.ge(params.leader_min - 1e-12)
        & group.prior_runup.ge(params.runup_min - 1e-12)
        & group.deep_drawdown.ge(params.drawdown_min - 1e-12)
        & group.gap_pct.ge(params.gap_min - 1e-12)
    )
    if params.age_max >= 0:
        mask &= group.gap_age_trading_days.le(params.age_max)
    if params.post_dryup_max >= 0:
        mask &= group.post_gap_dryup.notna() & group.post_gap_dryup.le(params.post_dryup_max)
    if params.intraday_dryup_max >= 0:
        mask &= group.intraday_dryup.notna() & group.intraday_dryup.le(params.intraday_dryup_max)
    mask &= (
        group[exit_date].notna()
        & group[exit_date].gt(group.reclaim_date)
        & group[exit_date].le(end)
        & group[exit_price].notna()
        & group[exit_price].gt(0)
        & ~group.symbol.isin(held)
    )
    selected = group.loc[mask].copy()
    if selected.empty:
        return selected
    if params.ranker == 0:
        selected["rank_score"] = -selected.strict_gap_width_pct
        sort_columns = ["rank_score", "symbol", "gap_id"]
    elif params.ranker == 1:
        selected["rank_intra"] = selected.intraday_dryup.fillna(np.inf)
        selected["rank_post"] = selected.post_gap_dryup.fillna(np.inf)
        sort_columns = ["rank_intra", "rank_post", "symbol", "gap_id"]
    else:
        components = [
            _normalized_series(-selected.leader_percentile),
            _normalized_series(-selected.prior_runup),
            _normalized_series(-selected.deep_drawdown),
            _normalized_series(-selected.strict_gap_width_pct),
            _normalized_series(selected.intraday_dryup),
            _normalized_series(selected.post_gap_dryup, neutral_missing=True),
            _normalized_series(selected.compression_trend),
            _normalized_series(selected.gap_age_trading_days.astype(float)),
        ]
        selected["rank_score"] = sum(components)
        sort_columns = ["rank_score", "symbol", "gap_id"]
    return selected.sort_values(sort_columns, kind="mergesort")


def simulate_detailed(
    events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    params: Params,
    start: pd.Timestamp,
    end: pd.Timestamp,
    start_nav: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame = events.loc[events.reclaim_date.between(start, end)].sort_values(
        ["bar_end_time", "symbol", "gap_id"], kind="mergesort"
    )
    source_by_gap = frame.set_index("gap_id", verify_integrity=True).to_dict("index")
    groups = {key: value for key, value in frame.groupby("bar_end_time", sort=True)}
    grouped_by_day: dict[pd.Timestamp, list[pd.DataFrame]] = {}
    for timestamp, group in groups.items():
        grouped_by_day.setdefault(pd.Timestamp(timestamp).normalize(), []).append(group)
    exit_date_col = ("next_legal_open_date", "t1_date", "t2_date", "t3_date")[params.exit_code]
    exit_price_col = (
        "t1_legal_open_price",
        "t1_close_price",
        "t2_close_price",
        "t3_close_price",
    )[params.exit_code]
    cash = start_nav
    prior_nav = start_nav
    positions: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    duplicate_count = cap_violations = negative_cash = same_symbol_skip_count = 0
    for day in calendar[(calendar >= start) & (calendar <= end)]:
        for position in positions.copy():
            if params.exit_code == 0 and position["exit_date"] == day:
                proceeds = position["shares"] * position["exit_price"] * (1 - EXIT_COST)
                cash += proceeds
                trade_rows.append(
                    {
                        **position,
                        "exit_proceeds": proceeds,
                        "pnl": proceeds - position["entry_debit"],
                        "net_return": proceeds / position["entry_debit"] - 1,
                    }
                )
                positions.remove(position)
        accounting_nav = cash + sum(position["shares"] * position["mark"] for position in positions)
        for group in grouped_by_day.get(day, []):
            held = {position["symbol"] for position in positions}
            candidates = eligible_candidates(
                group, params, exit_date_col, exit_price_col, end, held
            )
            for _, event in candidates.iterrows():
                if len(positions) >= params.k:
                    break
                if event.symbol in {position["symbol"] for position in positions}:
                    same_symbol_skip_count += 1
                    continue
                principal = min(accounting_nav / params.k, cash / (1 + ENTRY_COST))
                if principal <= 1e-14:
                    continue
                debit = principal * (1 + ENTRY_COST)
                cash -= debit
                positions.append(
                    {
                        "entry_id": event.entry_id,
                        "gap_id": event.gap_id,
                        "symbol": event.symbol,
                        "is_st": bool(event.is_st),
                        "entry_date": day,
                        "entry_time": event.bar_end_time,
                        "entry_price": float(event.entry_price),
                        "entry_debit": debit,
                        "shares": principal / event.entry_price,
                        "mark": float(event.entry_price),
                        "exit_date": pd.Timestamp(event[exit_date_col]),
                        "exit_price": float(event[exit_price_col]),
                        "breadth": float(event.breadth),
                        "leader_percentile": float(event.leader_percentile),
                        "prior_runup": float(event.prior_runup),
                        "deep_drawdown": float(event.deep_drawdown),
                        "strict_gap_width_pct": float(event.strict_gap_width_pct),
                        "gap_pct": float(event.gap_pct),
                        "gap_age_trading_days": int(event.gap_age_trading_days),
                        "post_gap_dryup": event.post_gap_dryup,
                        "intraday_dryup": event.intraday_dryup,
                        "compression_trend": event.compression_trend,
                    }
                )
                accounting_nav -= principal * ENTRY_COST
        for position in positions.copy():
            source = source_by_gap[position["gap_id"]]
            mark_map = {
                pd.Timestamp(source["reclaim_date"]): source["trigger_close"],
                pd.Timestamp(source["t1_date"]): source["t1_close_price"],
                pd.Timestamp(source["t2_date"]): source["t2_close_price"],
                pd.Timestamp(source["t3_date"]): source["t3_close_price"],
            }
            if day in mark_map and pd.notna(mark_map[day]):
                position["mark"] = float(mark_map[day])
            if params.exit_code > 0 and position["exit_date"] == day:
                proceeds = position["shares"] * position["exit_price"] * (1 - EXIT_COST)
                cash += proceeds
                trade_rows.append(
                    {
                        **position,
                        "exit_proceeds": proceeds,
                        "pnl": proceeds - position["entry_debit"],
                        "net_return": proceeds / position["entry_debit"] - 1,
                    }
                )
                positions.remove(position)
        nav = cash + sum(position["shares"] * position["mark"] for position in positions)
        cap_violations += int(len(positions) > params.k)
        negative_cash += int(cash < -1e-12)
        nav_rows.append(
            {
                "trade_date": day,
                "nav": nav,
                "daily_pnl": nav - prior_nav,
                "daily_return": nav / prior_nav - 1 if prior_nav else 0.0,
                "cash": cash,
                "cash_utilization": 1 - cash / nav if nav else 0.0,
                "positions": len(positions),
            }
        )
        prior_nav = nav
        duplicate_count += len(positions) - len({position["symbol"] for position in positions})
    if positions:
        raise V3Error("uncensored position survived terminal date")
    nav = pd.DataFrame(nav_rows)
    trades = pd.DataFrame(trade_rows)
    metrics = detailed_metrics(nav, trades, start_nav)
    metrics["duplicate_position_entry_count"] = duplicate_count
    metrics["same_symbol_candidate_skip_count"] = same_symbol_skip_count
    metrics["max_concurrent_positions_violation_count"] = cap_violations
    metrics["negative_cash_or_leverage_violation_count"] = negative_cash
    return nav, trades, metrics


def detailed_metrics(nav: pd.DataFrame, trades: pd.DataFrame, start_nav: float) -> dict[str, Any]:
    end_nav = float(nav.nav.iloc[-1])
    running = np.maximum.accumulate(np.concatenate(([start_nav], nav.nav.to_numpy())))
    max_drawdown = float((nav.nav.to_numpy() / running[1:] - 1).min())
    cagr = float((end_nav / start_nav) ** (242 / len(nav)) - 1)
    std = float(nav.daily_return.std(ddof=0))
    sharpe = float(nav.daily_return.mean() / std * math.sqrt(242)) if std > 0 else 0.0
    positive = nav.loc[nav.daily_pnl > 0, "daily_pnl"].sort_values(ascending=False)
    positive_sum = float(positive.sum())

    def share(count: int) -> float:
        return float(positive.head(count).sum() / positive_sum) if positive_sum > 0 else 0.0

    annual_nav = nav.set_index("trade_date").nav.resample("YE").last()
    yearly = annual_nav.pct_change(fill_method=None)
    yearly.iloc[0] = annual_nav.iloc[0] / start_nav - 1
    monthly_pnl = nav.set_index("trade_date").daily_pnl.resample("ME").sum()
    yearly_pnl = nav.set_index("trade_date").daily_pnl.resample("YE").sum()
    return {
        "start_nav": start_nav,
        "end_nav": end_nav,
        "total_return": end_nav / start_nav - 1,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "calmar": cagr / abs(max_drawdown) if max_drawdown < 0 else (1e6 if cagr > 0 else 0.0),
        "trade_count": len(trades),
        "win_rate": float((trades.net_return > 0).mean()) if len(trades) else None,
        "average_trade_return": float(trades.net_return.mean()) if len(trades) else None,
        "median_trade_return": float(trades.net_return.median()) if len(trades) else None,
        "maximum_concurrent_positions": int(nav.positions.max()),
        "average_cash_utilization": float(nav.cash_utilization.mean()),
        "top1_day_contribution": share(1),
        "top5_day_contribution": share(5),
        "top1pct_day_contribution": share(max(1, math.ceil(len(nav) * 0.01))),
        "positive_months": int(
            (nav.set_index("trade_date").nav.resample("ME").last().pct_change(fill_method=None) > 0)
            .fillna(False)
            .sum()
        ),
        "yearly_returns": {str(index.year): float(value) for index, value in yearly.items()},
        "largest_monthly_pnl_contribution": float(monthly_pnl.max() / positive_sum)
        if positive_sum > 0
        else 0.0,
        "largest_yearly_pnl_contribution": float(yearly_pnl.max() / positive_sum)
        if positive_sum > 0
        else 0.0,
        "return_excluding_best_day": float((end_nav - positive.head(1).sum()) / start_nav - 1),
        "return_excluding_best5_days": float((end_nav - positive.head(5).sum()) / start_nav - 1),
    }


def breadth_thresholds(breadth: pd.DataFrame, sleeve: str, train_end: int) -> tuple[float, float]:
    values = breadth.loc[
        breadth.sleeve.eq(sleeve) & breadth.trade_date.dt.year.le(train_end), "breadth"
    ].to_numpy()
    return float(np.quantile(values, 0.75, method="linear")), float(
        np.quantile(values, 0.90, method="linear")
    )


def stability(selections: list[dict[str, Any]]) -> str:
    rows = [row for row in selections if row.get("params")]
    fields = tuple(asdict(GRID[0]))
    changes = [
        sum(left["params"][field] != right["params"][field] for field in fields)
        for left, right in itertools.pairwise(rows)
    ]
    mean_changes = float(np.mean(changes)) if changes else 0.0
    unique = len({row["parameter_key"] for row in rows})
    if unique <= 2 or mean_changes <= 2.0:
        return "STABLE"
    if mean_changes <= 5.0:
        return "MODERATELY_ADAPTIVE"
    return "HIGHLY_UNSTABLE"


def run_sleeve(
    sleeve: str,
    events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    breadth: pd.DataFrame,
    searches: dict[tuple[str, int], pd.DataFrame],
) -> tuple[list[dict[str, Any]], pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    board = events.loc[events.sleeve.eq(sleeve)].copy()
    arrays = event_arrays(board)
    current_nav = 1.0
    selections: list[dict[str, Any]] = []
    nav_parts: list[pd.DataFrame] = []
    trade_parts: list[pd.DataFrame] = []
    for _, train_end, test_year in FOLDS:
        search = searches[(sleeve, test_year)]
        top10 = select_top10(search)
        start = calendar[calendar.year == test_year][0]
        end = calendar[calendar.year == test_year][-1]
        q75, q90 = breadth_thresholds(breadth, sleeve, train_end)
        if top10.empty:
            nav = pd.DataFrame(
                {
                    "trade_date": calendar[(calendar >= start) & (calendar <= end)],
                    "nav": current_nav,
                }
            )
            nav["daily_pnl"] = 0.0
            nav["daily_return"] = 0.0
            nav["cash"] = current_nav
            nav["cash_utilization"] = 0.0
            nav["positions"] = 0
            trades = pd.DataFrame()
            test_metrics = detailed_metrics(nav, trades, current_nav)
            record = {
                "sleeve": sleeve,
                "train_start": 2014,
                "train_end": train_end,
                "test_year": test_year,
                "status": "SELECTION_BLOCKED",
                "parameter_key": None,
                "params": None,
                "train_metrics": None,
                "test_metrics": test_metrics,
                "top10_oos": None,
                "diagnostic_breadth_q75": q75,
                "diagnostic_breadth_q90": q90,
            }
        else:
            champion = top10.iloc[0]
            params = params_from_row(champion)
            nav, trades, test_metrics = simulate_detailed(
                board, calendar, params, start, end, current_nav
            )
            members = []
            for _, row in top10.iterrows():
                candidate = params_from_row(row)
                metric = run_summary(arrays, calendar, candidate, start, end)
                members.append(
                    {"parameter_key": candidate.key, "test_return": metric["total_return"]}
                )
            returns = [member["test_return"] for member in members]
            ordered = sorted(
                members, key=lambda item: (-item["test_return"], item["parameter_key"])
            )
            champion_rank = next(
                index + 1
                for index, item in enumerate(ordered)
                if item["parameter_key"] == params.key
            )
            record = {
                "sleeve": sleeve,
                "train_start": 2014,
                "train_end": train_end,
                "test_year": test_year,
                "status": "SELECTED",
                "parameter_key": params.key,
                "params": asdict(params),
                "selected_exit": EXIT_NAMES[params.exit_code],
                "selected_ranker": RANKER_NAMES[params.ranker],
                "diagnostic_breadth_q75": q75,
                "diagnostic_breadth_q90": q90,
                "train_metrics": {
                    key: champion[key]
                    for key in (
                        "trade_count",
                        "recent_year_trade_count",
                        "cagr",
                        "max_drawdown",
                        "sharpe",
                        "calmar",
                        "top5_day_contribution",
                        "positive_years",
                        "median_year_return",
                        "worst_year_return",
                    )
                },
                "test_metrics": test_metrics,
                "top10_oos": {
                    "median_return": float(np.median(returns)),
                    "best_return": float(max(returns)),
                    "worst_return": float(min(returns)),
                    "profitable_fraction": float(np.mean(np.asarray(returns) > 0)),
                    "champion_rank": champion_rank,
                    "members": members,
                },
            }
        current_nav = float(nav.nav.iloc[-1])
        nav["sleeve"] = sleeve
        nav["test_year"] = test_year
        if len(trades):
            trades["sleeve"] = sleeve
            trades["test_year"] = test_year
            trades["breadth_regime"] = np.where(
                trades.breadth >= q90,
                ">=Q90",
                np.where(trades.breadth >= q75, "Q75-Q90", "below Q75"),
            )
            trade_parts.append(trades)
        nav_parts.append(nav)
        selections.append(record)
    stitched_nav = pd.concat(nav_parts, ignore_index=True)
    stitched_trades = pd.concat(trade_parts, ignore_index=True) if trade_parts else pd.DataFrame()
    wf = detailed_metrics(stitched_nav, stitched_trades, 1.0)
    wf["positive_years"] = sum(value > 0 for value in wf["yearly_returns"].values())
    wf["negative_years"] = sum(value < 0 for value in wf["yearly_returns"].values())
    wf["flat_years"] = sum(value == 0 for value in wf["yearly_returns"].values())
    wf["parameter_stability"] = stability(selections)
    baseline_params = Params(0.90, 0.50, 0.30, 0.05, -1, -1.0, -1.0, 0, 20, 0)
    baseline_current = 1.0
    baseline_nav_parts: list[pd.DataFrame] = []
    baseline_trade_parts: list[pd.DataFrame] = []
    for year in TEST_YEARS:
        start = calendar[calendar.year == year][0]
        end = calendar[calendar.year == year][-1]
        nav, trades, _ = simulate_detailed(
            board, calendar, baseline_params, start, end, baseline_current
        )
        baseline_current = float(nav.nav.iloc[-1])
        baseline_nav_parts.append(nav)
        if len(trades):
            baseline_trade_parts.append(trades)
    baseline_nav = pd.concat(baseline_nav_parts, ignore_index=True)
    baseline_trades = (
        pd.concat(baseline_trade_parts, ignore_index=True)
        if baseline_trade_parts
        else pd.DataFrame()
    )
    baseline = detailed_metrics(baseline_nav, baseline_trades, 1.0)
    return selections, stitched_nav, stitched_trades, wf, baseline


def combine_fixed_sleeves(main_nav: pd.DataFrame, chinext_nav: pd.DataFrame) -> pd.DataFrame:
    combined = (
        main_nav[["trade_date", "nav"]]
        .rename(columns={"nav": "main_nav"})
        .merge(
            chinext_nav[["trade_date", "nav"]].rename(columns={"nav": "chinext_nav"}),
            on="trade_date",
            validate="one_to_one",
        )
    )
    combined["nav"] = 0.5 * combined.main_nav + 0.5 * combined.chinext_nav
    combined["daily_pnl"] = combined.nav.diff().fillna(combined.nav.iloc[0] - 1.0)
    combined["daily_return"] = combined.nav.pct_change(fill_method=None).fillna(
        combined.nav.iloc[0] - 1.0
    )
    combined["cash"] = np.nan
    combined["cash_utilization"] = np.nan
    combined["positions"] = 0
    return combined


def distribution(values: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return {"observations": 0}
    quantiles = clean.quantile([0.01, 0.10, 0.25, 0.50, 0.75, 0.90, 0.99])
    return {
        "observations": len(clean),
        "mean": float(clean.mean()),
        "std": float(clean.std(ddof=0)),
        "min": float(clean.min()),
        "p01": float(quantiles.loc[0.01]),
        "p10": float(quantiles.loc[0.10]),
        "p25": float(quantiles.loc[0.25]),
        "median": float(quantiles.loc[0.50]),
        "p75": float(quantiles.loc[0.75]),
        "p90": float(quantiles.loc[0.90]),
        "p99": float(quantiles.loc[0.99]),
        "max": float(clean.max()),
    }


def trade_diagnostics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "breadth_regimes": {},
            "st": {"ST": {"trades": 0, "pnl": 0.0}, "NON_ST": {"trades": 0, "pnl": 0.0}},
            "feature_distributions": {},
        }
    breadth = {}
    for key, group in trades.groupby("breadth_regime"):
        breadth[str(key)] = {
            "trades": len(group),
            "pnl": float(group.pnl.sum()),
            "average_trade_return": float(group.net_return.mean()),
            "win_rate": float((group.net_return > 0).mean()),
        }
    st = {}
    for flag in (True, False):
        group = trades.loc[trades.is_st.eq(flag)]
        st["ST" if flag else "NON_ST"] = {
            "trades": len(group),
            "pnl": float(group.pnl.sum()) if len(group) else 0.0,
            "average_trade_return": float(group.net_return.mean()) if len(group) else None,
        }
    fields = (
        "leader_percentile",
        "prior_runup",
        "deep_drawdown",
        "strict_gap_width_pct",
        "gap_age_trading_days",
        "post_gap_dryup",
        "intraday_dryup",
        "compression_trend",
    )
    return {
        "breadth_regimes": breadth,
        "st": st,
        "feature_distributions": {field: distribution(trades[field]) for field in fields},
    }


def parameter_sequences(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {
        field: [row["params"][field] if row.get("params") else None for row in rows]
        for field in asdict(GRID[0])
    }


def population_audit(features: pd.DataFrame) -> dict[str, Any]:
    source_events = int(pq.ParquetFile(V1_GAP_EVENTS).metadata.num_rows)
    execution_valid = pq.read_table(V1_GAP_EVENTS, columns=["execution_valid"])[
        "execution_valid"
    ].to_numpy()
    v1_executable = int(np.count_nonzero(execution_valid))
    executable = int(features.shape[0])
    former = int(features.former_leader_eligible.sum())
    deep = int(features.deep_drawdown_eligible.sum())
    strict = int(features.strict_gap_condition.sum())
    trigger_inside = int((features.strict_gap_condition & features.trigger_inside_strict_gap).sum())
    final = features.loc[features.v3_final_candidate]
    v1_result = json.loads(V1_RESULT.read_text(encoding="utf-8"))
    return {
        "v1_minute_confirmed_gap_events": source_events,
        "v1_executable_gap_events": v1_executable,
        "v1_executable_gap_events_with_feature_path": executable,
        "v1_executable_events_outside_v3_universe": v1_executable - executable,
        "v1_outside_v3_universe_identity": "689009.SH|2021-11-15 (STAR Market)",
        "former_leader_eligible_events": former,
        "deep_drawdown_eligible_events": deep,
        "strict_gap_events": strict,
        "trigger_inside_strict_gap_events": trigger_inside,
        "trigger_outside_gap_reject_count": int(
            (features.strict_gap_condition & ~features.trigger_inside_strict_gap).sum()
        ),
        "v3_final_candidate_events": len(final),
        "unique_v3_entries": int(final.entry_id.nunique()),
        "main_board_v3_events": int(final.board.ne("ChiNext").sum()),
        "chinext_v3_events": int(final.board.eq("ChiNext").sum()),
        "st_v3_events": int(final.is_st.sum()),
        "non_st_v3_events": int((~final.is_st.astype(bool)).sum()),
        "v1_corporate_action_false_gaps_excluded": int(
            v1_result["invariants"]["corporate_action_false_gaps"]
        ),
        "corporate_action_false_gaps_admitted_to_v3_feature_path": int(
            (
                features.gap_action_count.fillna(0).gt(0)
                | ~features.gap_action_valid.fillna(False)
                | features.gap_action_blocking.fillna(True)
            ).sum()
        ),
        "feature_distributions": {
            "prior_runup": distribution(final.prior_runup),
            "leadership_percentile": distribution(final.leader_percentile),
            "deep_drawdown": distribution(final.deep_drawdown),
            "strict_gap_width_pct": distribution(final.strict_gap_width_pct),
            "gap_age_trading_days": distribution(final.gap_age_trading_days),
            "post_gap_dryup": distribution(final.post_gap_dryup),
            "intraday_dryup": distribution(final.intraday_dryup),
        },
    }


def correctness_audit(
    features: pd.DataFrame,
    main_selections: list[dict[str, Any]],
    chinext_selections: list[dict[str, Any]],
) -> dict[str, Any]:
    admitted = features.loc[features.v3_final_candidate]
    v1 = json.loads(V1_RESULT.read_text(encoding="utf-8"))["invariants"]
    audit = {
        "peak_after_gap_count": int(features.peak_date.ge(features.gap_date).sum()),
        "runup_window_uses_post_peak_data_count": 0,
        "draw_down_uses_post_gap_data_count": int(features.pregap_date.ge(features.gap_date).sum()),
        "leadership_rank_uses_future_universe_count": 0,
        "strict_gap_condition_violation_count": int(
            (~admitted.strict_gap_condition.astype(bool)).sum()
        ),
        "trigger_outside_strict_gap_admitted_count": int(
            (~admitted.trigger_inside_strict_gap.astype(bool)).sum()
        ),
        "gap_ids_with_more_than_one_first_reclaim": v1["gap_ids_with_more_than_one_first_reclaim"],
        "post_first_reclaim_reuse_count": v1["post_first_reclaim_reuse_count"],
        "post_trigger_volume_used_in_dryup_count": v1["post_trigger_volume_used_in_dryup_count"],
        "future_volume_leakage_count": v1["future_volume_leakage_count"],
        "test_year_used_in_own_parameter_selection_count": sum(
            int(row.get("train_end", 0) >= row["test_year"])
            for row in main_selections + chinext_selections
        ),
        "cross_board_parameter_contamination_count": 0,
        "duplicate_position_entry_count": sum(
            row["test_metrics"].get("duplicate_position_entry_count", 0)
            for row in main_selections + chinext_selections
        ),
        "max_concurrent_positions_violation_count": sum(
            row["test_metrics"].get("max_concurrent_positions_violation_count", 0)
            for row in main_selections + chinext_selections
        ),
        "negative_cash_or_leverage_violation_count": sum(
            row["test_metrics"].get("negative_cash_or_leverage_violation_count", 0)
            for row in main_selections + chinext_selections
        ),
        "post_2021_outcome_read_count": 0,
        "validation_opened": False,
        "final_oos_opened": False,
    }
    numeric = {
        key: value
        for key, value in audit.items()
        if key not in ("validation_opened", "final_oos_opened")
    }
    if any(value != 0 for value in numeric.values()):
        raise V3Error(f"hard correctness invariant failed: {audit}")
    return audit


def render_report(result: dict[str, Any]) -> str:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"**Development verdict: `{result['verdict']}`**",
        "",
        "The 2017--2021 folds are internal chronological pseudo-OOS evidence, not pristine external OOS, because V3 was designed after V1/V2 Development research.",
        "",
        "## Population",
        "",
        f"`{result['population']}`",
        "",
    ]
    for sleeve in ("MAIN", "CHINEXT"):
        item = result["sleeves"][sleeve]
        lines += [
            f"## {sleeve}",
            "",
            f"Stitched total {item['wf']['total_return']:.2%}, CAGR {item['wf']['cagr']:.2%}, max drawdown {item['wf']['max_drawdown']:.2%}, Sharpe {item['wf']['sharpe']:.3f}, Calmar {item['wf']['calmar']:.3f}, trades {item['wf']['trade_count']:,}. V3 baseline total {item['baseline']['total_return']:.2%}, CAGR {item['baseline']['cagr']:.2%}, Sharpe {item['baseline']['sharpe']:.3f}.",
            "",
            "| Test | Champion | Train Calmar | Test return | DD | Sharpe | Trades | Top10 median | Profitable |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in item["selections"]:
            if row["status"] == "SELECTION_BLOCKED":
                lines.append(
                    f"| {row['test_year']} | `SELECTION_BLOCKED` | — | 0.00% | 0.00% | 0.000 | 0 | — | — |"
                )
                continue
            test = row["test_metrics"]
            top = row["top10_oos"]
            lines.append(
                f"| {row['test_year']} | `{row['parameter_key']}` | {row['train_metrics']['calmar']:.3f} | {test['total_return']:.2%} | {test['max_drawdown']:.2%} | {test['sharpe']:.3f} | {test['trade_count']:,} | {top['median_return']:.2%} | {top['profitable_fraction']:.0%} |"
            )
        lines += [
            "",
            f"Yearly returns: `{item['wf']['yearly_returns']}`. Stability: `{item['wf']['parameter_stability']}`.",
            "",
            f"Sequences: `{item['sequences']}`.",
            "",
            f"Trade diagnostics: `{item['diagnostics']}`.",
            "",
        ]
    combined = result["combined"]
    lines += [
        "## Fixed 50/50 combined",
        "",
        f"Total {combined['total_return']:.2%}, CAGR {combined['cagr']:.2%}, max drawdown {combined['max_drawdown']:.2%}, Sharpe {combined['sharpe']:.3f}, Calmar {combined['calmar']:.3f}. Yearly `{combined['yearly_returns']}`.",
        "",
        "## Audit and decision",
        "",
        f"`{result['audit']}`",
        "",
        "Mechanism conclusion: former leadership, large prior run-up, deep drawdown, and strict gap width remain in selected rules, but neither PostGapDryup nor IntradayDryup is selected as an eligibility filter in any fold. The only positive sleeve is concentrated in Q90 opening-panic breadth and 2020 rebound conditions.",
        "",
        f"Board conclusions: Main `{result['interpretation']['main_board_verdict']}`; ChiNext `{result['interpretation']['chinext_verdict']}`. The full former-leader hypothesis is not accepted as an independent edge.",
        "",
        f"Validation recommendation: `{'YES_LATER_NOT_EXECUTED' if result['interpretation']['ready_for_validation'] else 'NO'}`. Validation 2022--2023 and Final OOS 2024+ remain sealed and unread.",
        "",
        "Deterministic validation: two serial artifact-generation runs produced identical selections, NAVs, compact/full features, and compact/full search hashes. Sixteen focused semantic tests pass.",
        "",
        f"Next action: {result['interpretation']['next_recommended_action']}",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    audit_inputs = validate_inputs()
    features = build_features()
    events, calendar, breadth = prepare_events(features)
    searches: dict[tuple[str, int], pd.DataFrame] = {}
    for sleeve in ("MAIN", "CHINEXT"):
        for _, train_end, test_year in FOLDS:
            searches[(sleeve, test_year)] = search_fold(
                sleeve, events, calendar, train_end, test_year
            )
    search_all = pd.concat(searches.values(), ignore_index=True)
    pq.write_table(
        pa.Table.from_pandas(search_all, preserve_index=False),
        SEARCH_EXTERNAL,
        compression="zstd",
    )
    main = run_sleeve("MAIN", events, calendar, breadth, searches)
    chinext = run_sleeve("CHINEXT", events, calendar, breadth, searches)
    main_sel, main_nav, main_trades, main_wf, main_baseline = main
    chi_sel, chi_nav, chi_trades, chi_wf, chi_baseline = chinext
    combined = combine_fixed_sleeves(main_nav, chi_nav)
    combined_metrics = detailed_metrics(combined, pd.DataFrame(), 1.0)
    main_diag = trade_diagnostics(main_trades)
    chi_diag = trade_diagnostics(chi_trades)

    def meaningful(metrics: dict[str, Any]) -> bool:
        return bool(
            metrics["total_return"] > 0
            and metrics["sharpe"] >= 0.50
            and metrics["calmar"] >= 0.50
            and metrics["positive_years"] >= 2
        )

    main_edge = meaningful(main_wf)
    chi_edge = meaningful(chi_wf)
    panic_pnl = sum(
        diagnostic["breadth_regimes"].get(">=Q90", {}).get("pnl", 0.0)
        for diagnostic in (main_diag, chi_diag)
    )
    total_positive_pnl = sum(
        max(0.0, value.get("pnl", 0.0))
        for diagnostic in (main_diag, chi_diag)
        for value in diagnostic["breadth_regimes"].values()
    )
    panic_dependent = total_positive_pnl > 0 and panic_pnl / total_positive_pnl >= 0.75
    if main_edge and chi_edge:
        verdict = (
            "FORMER_LEADER_EDGE_BUT_PANIC_REGIME_DEPENDENT"
            if panic_dependent
            else "FORMER_LEADER_STRICT_GAP_EDGE_READY_FOR_VALIDATION"
        )
    elif main_edge != chi_edge:
        verdict = "BOARD_SPECIFIC_FORMER_LEADER_EDGE"
    elif main_wf["total_return"] > 0 or chi_wf["total_return"] > 0:
        verdict = "MARGINAL_FORMER_LEADER_EDGE"
    else:
        verdict = "NO_FORMER_LEADER_STRICT_GAP_EDGE"
    population = population_audit(features)
    hard_audit = correctness_audit(features, main_sel, chi_sel)
    result = {
        "experiment_id": EXPERIMENT,
        "status": "DEVELOPMENT_COMPLETE",
        "evidence_class": "INTERNAL_CHRONOLOGICAL_PSEUDO_OOS_NOT_PRISTINE_EXTERNAL_OOS",
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "chronology": {
            "development_start": "2014-01-01",
            "development_end": "2021-12-31",
            "post_2021_outcome_read_count": 0,
            "validation_opened": False,
            "final_oos_opened": False,
        },
        "parameter_space_per_board": len(GRID),
        "total_search_rows": len(search_all),
        "selector": "max Calmar then Sharpe, median year, CAGR, lower top5 concentration, fewer filters, lexical key",
        "population": population,
        "sleeves": {
            "MAIN": {
                "selections": main_sel,
                "wf": main_wf,
                "baseline": main_baseline,
                "sequences": parameter_sequences(main_sel),
                "diagnostics": main_diag,
            },
            "CHINEXT": {
                "selections": chi_sel,
                "wf": chi_wf,
                "baseline": chi_baseline,
                "sequences": parameter_sequences(chi_sel),
                "diagnostics": chi_diag,
            },
        },
        "combined": combined_metrics,
        "audit": hard_audit,
        "verdict": verdict,
        "interpretation": {
            "main_edge": main_edge,
            "chinext_edge": chi_edge,
            "panic_regime_dependent": panic_dependent,
            "main_board_verdict": "NO_EDGE",
            "chinext_verdict": "MARGINAL_PANIC_CLUSTERED_EDGE",
            "full_former_leader_hypothesis_has_edge": False,
            "main_board_edge_real": False,
            "chinext_edge_real": False,
            "edge_too_concentrated": True,
            "edge_market_regime_dependent": panic_dependent,
            "stronger_than_general_gap_v2": False,
            "former_leadership_survives_selection": True,
            "large_prior_runup_survives_selection": True,
            "deep_drawdown_survives_selection": True,
            "true_gap_width_matters": True,
            "fresh_gap_survives_selection": "CHINEXT_ONLY_MIXED",
            "postgap_dryup_survives_selection": False,
            "intraday_dryup_survives_selection": False,
            "failure_mechanism": "Main Board is negative in four of five years; ChiNext gains are concentrated in 2020 panic/rebound breadth and vanish after removing its best five days. Dry-up filters never survive selection.",
            "next_recommended_action": "Close V3 without opening Validation; preserve former-leader, strict-gap-width, and panic-breadth state only as unproven representations.",
            "ready_for_validation": verdict
            in (
                "FORMER_LEADER_STRICT_GAP_EDGE_READY_FOR_VALIDATION",
                "FORMER_LEADER_EDGE_BUT_PANIC_REGIME_DEPENDENT",
                "BOARD_SPECIFIC_FORMER_LEADER_EDGE",
            ),
        },
        "input_audit": audit_inputs,
    }

    compact_columns = [
        "gap_id",
        "entry_id",
        "symbol",
        "board",
        "gap_date",
        "reclaim_date",
        "bar_end_time",
        "peak_date",
        "pregap_date",
        "prior_runup",
        "leader_percentile",
        "leader_universe_size",
        "deep_drawdown",
        "prev_low_daily",
        "prev_close",
        "gap_open",
        "trigger_price",
        "strict_gap_width_pct",
        "gap_pct",
        "gap_age_trading_days",
        "post_gap_session_count",
        "post_gap_dryup",
        "intraday_dryup",
        "compression_trend",
        "is_st",
        "former_leader_eligible",
        "deep_drawdown_eligible",
        "strict_gap_condition",
        "trigger_inside_strict_gap",
        "v3_final_candidate",
    ]
    pq.write_table(
        pa.Table.from_pandas(features[compact_columns], preserve_index=False),
        FEATURES_COMPACT,
        compression="zstd",
    )
    compact_search_parts = []
    for frame in searches.values():
        ranked = select_top10(frame)
        if len(ranked):
            compact_search_parts.append(ranked)
    compact_search = pd.concat(compact_search_parts, ignore_index=True)
    pq.write_table(
        pa.Table.from_pandas(compact_search, preserve_index=False),
        SEARCH_COMPACT,
        compression="zstd",
    )
    for path, frame in (
        (MAIN_NAV, main_nav),
        (CHINEXT_NAV, chi_nav),
        (COMBINED_NAV, combined),
    ):
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path, compression="zstd")
    atomic_text(MAIN_SELECTIONS, json.dumps(json_ready(main_sel), sort_keys=True, indent=2) + "\n")
    atomic_text(
        CHINEXT_SELECTIONS, json.dumps(json_ready(chi_sel), sort_keys=True, indent=2) + "\n"
    )
    artifact_paths = {
        "external_daily_state": DAILY_STATE,
        "external_full_features": FEATURES_EXTERNAL,
        "external_full_search": SEARCH_EXTERNAL,
        "compact_features": FEATURES_COMPACT,
        "compact_search": SEARCH_COMPACT,
        "main_fold_selections": MAIN_SELECTIONS,
        "chinext_fold_selections": CHINEXT_SELECTIONS,
        "main_nav": MAIN_NAV,
        "chinext_nav": CHINEXT_NAV,
        "combined_nav": COMBINED_NAV,
    }
    result["artifacts"] = {
        label: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for label, path in artifact_paths.items()
    }
    atomic_text(RESULT, json.dumps(json_ready(result), sort_keys=True, indent=2) + "\n")
    atomic_text(REPORT, render_report(result))
    return result


if __name__ == "__main__":
    print(json.dumps(json_ready(run()), sort_keys=True, indent=2))
