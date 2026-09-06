#!/usr/bin/env python3
# ruff: noqa: E501
"""Mechanical, spec-first roll-forward of the exact V10 and V17 rules.

Stage ``freeze`` reconstructs only the registered 2026 coordinate extension,
reproduces the already-consumed 2023/2024 identities, freezes all requested
new-period identities, and only then checks the already-consumed outcome and
capacity canaries.  Stage ``evaluate`` is the sole code path allowed to attach
new-period post-decision paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))
import run_ashare_bull_quiet_inventory_three_session_acceptance_v2 as acceptdev  # noqa: E402
import run_ashare_causal_bear_strong_bull_dual_engine_v17_challenge as v17c  # noqa: E402
import run_ashare_quiet_inventory_fast_repricing_v1 as qfast  # noqa: E402
import run_ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1 as coordext  # noqa: E402

OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-EXACT-V10-V17-ROLLFORWARD-2021-2026YTD-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
SPEC_SHA256 = "b2a350c0480a96a10f7cad725f4296da33a15ec76eabd9c7a07c941d811a9076"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

EXT_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_exact_v10_v17_rollforward_2021_2026ytd_v1")
STAGE_A = EXT_ROOT / "stage_a"
STAGE_B = EXT_ROOT / "stage_b"
DATA_END = pd.Timestamp("2026-09-04")
CANARY_OUTCOME_END = pd.Timestamp("2025-03-31")
TARGET = 0.20
HORIZON = 60
COST = 0.004

HIST_DAILY = Path(
    "/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
EXACT_DAILY = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "pit_daily_qd010_exact_2022_2026q1.parquet"
)
CY033_2026 = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-033-PIT-B-DAILY-2018-20260904-V1/daily/partition_year=2026/data_0.parquet"
)
FEATURES = qfast.FEATURES
REGIME = qfast.REGIME
V10_ACCEPTED = v17c.BEAR_ACCEPTED
V10_SKIPPED = v17c.BEAR_SKIPPED
V17_MARKET_2024 = v17c.MARKET_2024
V17_BULL_LEDGER = v17c.BULL_MOTHERS
V17_BULL_ACCEPTED = v17c.BULL_ACCEPTED
V17_BEAR_RAW_2024 = v17c.BEAR_RAW_2024
V17_BULL_OUTCOMES = v17c.BULL_OUTCOMES
V17_BEAR_RAW_OUTCOMES_2024 = v17c.BEAR_RAW_OUTCOMES_2024
V17_BEAR_ACCEPTED_2024 = v17c.BEAR_ACCEPTED_2024

ROLL_COLUMNS = """
  CAST(trade_date AS DATE) AS trade_date, cal_idx::BIGINT AS cal_idx,
  symbol, sleeve, open, high, low, close, turnover_fraction, is_st,
  causal_industry, trade_status, current_day_data_tradable,
  up_limit_price, down_limit_price, market_rule_valid,
  corporate_action_count, corporate_action_valid, corporate_action_blocking,
  hard_valid, available_at, decision_at, history_valid, current_valid,
  invalid_step_cum, coordinate_factor, coord_open, coord_high, coord_low,
  coord_close, prior_coord_close
"""


class RollforwardError(RuntimeError):
    """Fail closed on any identity, lineage, canary, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(json_ready(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    connection = duckdb.connect()
    connection.register("frame_to_write", frame)
    connection.execute(
        f"COPY frame_to_write TO '{temporary.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()
    os.replace(temporary, path)


def read_spec_and_verify_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    if not SPEC.is_file() or sha256(SPEC) != SPEC_SHA256:
        raise RollforwardError("frozen roll-forward spec missing or drifted")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    actual: dict[str, str] = {}
    for role, record in spec["bound_inputs"].items():
        path = Path(record["path"])
        if not path.is_file():
            raise RollforwardError(f"missing bound input {role}: {path}")
        value = sha256(path)
        if value != record["sha256"]:
            raise RollforwardError(
                f"bound input drift {role}: expected {record['sha256']} got {value}"
            )
        actual[role] = value
    return spec, actual


def connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads=8")
    con.execute("SET memory_limit='12GB'")
    return con


def load_seed_state(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    frame = con.execute(
        f"""
        WITH last_row AS (
          SELECT symbol,coordinate_factor,invalid_step_cum,current_valid
          FROM read_parquet('{EXACT_DAILY.as_posix()}')
          WHERE trade_date<=DATE '2025-12-31'
          QUALIFY row_number() OVER(PARTITION BY symbol ORDER BY trade_date DESC)=1
        ), last_valid AS (
          SELECT symbol,close,coord_close
          FROM read_parquet('{EXACT_DAILY.as_posix()}')
          WHERE trade_date<=DATE '2025-12-31' AND current_valid
          QUALIFY row_number() OVER(PARTITION BY symbol ORDER BY trade_date DESC)=1
        )
        SELECT l.symbol,l.coordinate_factor AS factor,l.invalid_step_cum,
          l.current_valid AS previous_current_valid,
          v.close AS last_valid_raw_close,
          v.coord_close AS last_valid_coordinate_close
        FROM last_row l LEFT JOIN last_valid v USING(symbol)
        ORDER BY l.symbol
        """
    ).fetch_df()
    return {
        str(row.symbol): {
            "factor": float(row.factor),
            "invalid_step_cum": float(row.invalid_step_cum),
            "previous_current_valid": bool(row.previous_current_valid),
            "last_valid_raw_close": float(row.last_valid_raw_close),
            "last_valid_coordinate_close": float(row.last_valid_coordinate_close),
        }
        for row in frame.itertuples(index=False)
    }


def load_cy033_2026(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = con.execute(
        f"""
        SELECT CAST(trade_date AS DATE) AS trade_date,decision_at,symbol,
          open,high,low,close,volume,amount,turnover_fraction,trade_status,is_st,
          up_limit_price,down_limit_price,industry,corporate_action_count,
          corporate_action_valid,corporate_action_blocking,share_multiplier,
          cash_per_share,rights_ratio,rights_price,market_rule_valid,
          industry_valid,historical_identity_valid,hard_valid,
          current_day_data_tradable,available_at
        FROM read_parquet('{CY033_2026.as_posix()}')
        WHERE trade_date BETWEEN DATE '2026-01-01' AND DATE '2026-09-04'
          AND substr(symbol,1,3) IN
            ('000','001','002','003','300','301','302','600','601','603','605')
        ORDER BY symbol,trade_date
        """
    ).fetch_df()
    if frame.empty or pd.Timestamp(frame.trade_date.max()) != DATA_END:
        raise RollforwardError("CY033 2026 source does not reach frozen data end")
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def build_coordinate_tail(stage: Path) -> tuple[Path, dict[str, Any]]:
    con = connection()
    seeds = load_seed_state(con)
    raw = load_cy033_2026(con)
    authoritative_calendar = con.execute(
        f"""
        SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date,cal_idx::BIGINT AS cal_idx
        FROM read_parquet('{EXACT_DAILY.as_posix()}')
        WHERE trade_date BETWEEN DATE '2026-01-01' AND DATE '2026-03-31'
        ORDER BY trade_date
        """
    ).fetch_df()
    con.close()
    authoritative_calendar["trade_date"] = pd.to_datetime(authoritative_calendar.trade_date)
    dates = pd.DataFrame(
        {"trade_date": pd.to_datetime(raw.trade_date.drop_duplicates()).sort_values()}
    ).reset_index(drop=True)
    calendar = dates.merge(
        authoritative_calendar, on="trade_date", how="left", validate="one_to_one"
    )
    future = calendar.trade_date.gt(pd.Timestamp("2026-03-31"))
    start_idx = int(authoritative_calendar.cal_idx.max()) + 1
    calendar.loc[future, "cal_idx"] = np.arange(
        start_idx, start_idx + int(future.sum()), dtype=np.int64
    )
    if calendar.cal_idx.isna().any():
        raise RollforwardError("CY033 calendar disagrees with accepted 2026Q1 calendar")
    calendar["cal_idx"] = calendar.cal_idx.astype(np.int64)
    try:
        rebuilt = coordext.reconstruct_qd010_coordinate(raw, seeds, calendar)
    except Exception as exc:
        raise RollforwardError(f"QD010 coordinate extension failed: {exc}") from exc

    con = connection()
    con.register("rebuilt_2026", rebuilt)
    comparison = con.execute(
        f"""
        SELECT count(*) AS joined_rows,
          count(*) FILTER(WHERE r.symbol IS NULL) AS missing_rows,
          max(abs(a.coordinate_factor-r.coordinate_factor)) AS max_factor_diff,
          max(abs(a.coord_open-r.coord_open)) AS max_open_diff,
          max(abs(a.coord_high-r.coord_high)) AS max_high_diff,
          max(abs(a.coord_low-r.coord_low)) AS max_low_diff,
          max(abs(a.coord_close-r.coord_close)) AS max_close_diff,
          count(*) FILTER(WHERE a.invalid_step_cum!=r.invalid_step_cum) AS invalid_mismatch,
          count(*) FILTER(WHERE a.current_valid!=r.current_valid) AS current_mismatch,
          count(*) FILTER(WHERE a.history_valid!=r.history_valid) AS history_mismatch,
          count(*) FILTER(WHERE a.cal_idx!=r.cal_idx) AS calendar_mismatch
        FROM read_parquet('{EXACT_DAILY.as_posix()}') a
        LEFT JOIN rebuilt_2026 r USING(symbol,trade_date)
        WHERE a.trade_date BETWEEN DATE '2026-01-01' AND DATE '2026-03-31'
        """
    ).fetchone()
    con.close()
    keys = [
        "joined_rows",
        "missing_rows",
        "max_factor_diff",
        "max_open_diff",
        "max_high_diff",
        "max_low_diff",
        "max_close_diff",
        "invalid_mismatch",
        "current_mismatch",
        "history_mismatch",
        "calendar_mismatch",
    ]
    audit = dict(zip(keys, comparison, strict=True))
    blocking_counts = (
        audit["missing_rows"],
        audit["invalid_mismatch"],
        audit["current_mismatch"],
        audit["history_mismatch"],
        audit["calendar_mismatch"],
    )
    numeric = [
        audit["max_factor_diff"],
        audit["max_open_diff"],
        audit["max_high_diff"],
        audit["max_low_diff"],
        audit["max_close_diff"],
    ]
    if any(int(value) for value in blocking_counts) or any(
        value is None or not np.isfinite(float(value)) or float(value) > 1e-10 for value in numeric
    ):
        raise RollforwardError(f"2026Q1 coordinate canary failed: {audit}")
    tail = rebuilt.loc[rebuilt.trade_date.gt(pd.Timestamp("2026-03-31"))].copy()
    if tail.empty or tail.trade_date.max() != DATA_END:
        raise RollforwardError("reconstructed tail coverage incomplete")
    path = stage / "coordinate_tail_20260401_20260904.parquet"
    write_parquet(tail, path)
    audit["tail_rows"] = len(tail)
    audit["tail_min_date"] = str(tail.trade_date.min().date())
    audit["tail_max_date"] = str(tail.trade_date.max().date())
    audit["tail_sha256"] = sha256(path)
    return path, audit


def register_roll_daily(con: duckdb.DuckDBPyConnection, tail: Path) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW roll_daily AS
        SELECT {ROLL_COLUMNS} FROM read_parquet('{HIST_DAILY.as_posix()}')
          WHERE trade_date<DATE '2022-01-01'
        UNION ALL BY NAME
        SELECT {ROLL_COLUMNS} FROM read_parquet('{EXACT_DAILY.as_posix()}')
          WHERE trade_date BETWEEN DATE '2022-01-01' AND DATE '2026-03-31'
        UNION ALL BY NAME
        SELECT {ROLL_COLUMNS} FROM read_parquet('{tail.as_posix()}')
          WHERE trade_date BETWEEN DATE '2026-04-01' AND DATE '2026-09-04'
        """
    )
    duplicate_count = con.execute(
        """
        SELECT count(*) FROM (
          SELECT symbol,trade_date,count(*) AS n FROM roll_daily
          GROUP BY symbol,trade_date HAVING count(*)!=1
        )
        """
    ).fetchone()[0]
    if duplicate_count:
        raise RollforwardError(f"rolling daily duplicate identity: {duplicate_count}")


def feature_ctes() -> str:
    excluded = qfast.quoted_industries()
    return f"""
    WITH source AS (
      SELECT * FROM roll_daily
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '2026-09-04'
        AND sleeve IN ('MAIN','CHINEXT')
        AND causal_industry NOT IN ({excluded})
    ), window_one AS (
      SELECT *,
        lag(coord_close) OVER symbol_window AS lag1_close,
        lag(cal_idx) OVER symbol_window AS lag1_idx,
        lag(invalid_step_cum,60) OVER symbol_window AS lag60_invalid_step_cum,
        lag(coord_close,20) OVER symbol_window AS lag20_close,
        lag(cal_idx,20) OVER symbol_window AS lag20_idx,
        lag(coord_close,60) OVER symbol_window AS lag60_close,
        lag(cal_idx,60) OVER symbol_window AS lag60_idx,
        count(*) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) AS prior60_n,
        bool_and(history_valid) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) AS prior60_valid,
        max(coord_high) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 40 PRECEDING AND 1 PRECEDING) AS platform_high,
        min(coord_low) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 40 PRECEDING AND 1 PRECEDING) AS platform_low,
        avg(turnover_fraction) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS avg_to20,
        avg(turnover_fraction) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 21 PRECEDING) AS avg_to_old
      FROM source
      WINDOW symbol_window AS(PARTITION BY symbol ORDER BY trade_date)
    ), window_two AS (
      SELECT *,
        CASE WHEN lag1_idx=cal_idx-1 THEN coord_close/nullif(lag1_close,0)-1 END AS step_return,
        CASE WHEN lag20_idx=cal_idx-20 THEN coord_close/nullif(lag20_close,0)-1 END AS ret20,
        CASE WHEN lag60_idx=cal_idx-60 THEN coord_close/nullif(lag60_close,0)-1 END AS ret60
      FROM window_one
    ), featured AS (
      SELECT *,
        sum(CASE WHEN step_return>=0.05 THEN 1 ELSE 0 END) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW) AS large_up_days120,
        platform_high/nullif(platform_low,0)-1 AS platform_width,
        avg_to20/nullif(avg_to_old,0) AS turnover_contraction,
        coord_open/nullif(lag1_close,0)-1 AS open_gap,
        turnover_fraction/nullif(avg_to20,0) AS turnover_expansion,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location
      FROM window_two
    )
    """


def build_market(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = con.execute(
        feature_ctes()
        + """
        SELECT CAST(trade_date AS DATE) AS trade_date,
          median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL) AS market_median_ret20,
          avg((ret20>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL) AS market_positive_ret20_share,
          median(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL) AS market_median_ret60,
          avg((ret60>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL) AS market_positive_ret60_share,
          max(available_at) FILTER(WHERE current_valid AND NOT is_st) AS latest_source_timestamp
        FROM featured
        WHERE trade_date BETWEEN DATE '2023-01-01' AND DATE '2026-09-04'
        GROUP BY trade_date ORDER BY trade_date
        """
    ).fetch_df()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return v17c.label_market(frame)


def compare_market_canary(con: duckdb.DuckDBPyConnection, market: pd.DataFrame) -> dict[str, Any]:
    audits: dict[str, Any] = {}
    for year, path in ((2023, REGIME), (2024, V17_MARKET_2024)):
        current = market.loc[market.trade_date.dt.year.eq(year)].copy()
        frozen = con.execute(
            f"SELECT * FROM read_parquet('{path.as_posix()}') ORDER BY trade_date"
        ).fetch_df()
        frozen["trade_date"] = pd.to_datetime(frozen.trade_date)
        frozen = frozen.loc[frozen.trade_date.dt.year.eq(year)].copy()
        frozen["strong_bull"] = (
            frozen.market_regime.eq("BULL")
            & frozen.market_median_ret60.ge(0.05)
            & frozen.market_positive_ret60_share.ge(0.60)
        )
        merged = current.merge(
            frozen,
            on="trade_date",
            suffixes=("_current", "_frozen"),
            how="outer",
            indicator=True,
            validate="one_to_one",
        )
        if not merged._merge.eq("both").all():
            raise RollforwardError(f"market date identity canary failed for {year}")
        label_mismatch = int(
            merged.market_regime_current.ne(merged.market_regime_frozen).sum()
            + merged.strong_bull_current.ne(merged.strong_bull_frozen).sum()
        )
        diffs = {}
        for column in (
            "market_median_ret20",
            "market_positive_ret20_share",
            "market_median_ret60",
            "market_positive_ret60_share",
        ):
            diffs[column] = float(
                (merged[f"{column}_current"] - merged[f"{column}_frozen"]).abs().max()
            )
        # The accepted V17 challenge canary froze exact state labels and exact
        # medians for 2023; it recorded, but did not gate on, the two breadth
        # fractions because the later compact's historical member coverage is
        # not byte-identical.  For 2024 all four values came from the same
        # accepted asset and therefore remain exact gates.
        blocking_numeric = (
            ("market_median_ret20", "market_median_ret60") if year == 2023 else tuple(diffs)
        )
        if label_mismatch or any(diffs[name] > 1e-12 for name in blocking_numeric):
            raise RollforwardError(
                f"market state/numeric canary failed for {year}: labels={label_mismatch}, {diffs}"
            )
        audits[str(year)] = {
            "dates": len(merged),
            "label_mismatch": label_mismatch,
            "max_abs_differences": diffs,
        }
    return audits


def historical_bull_mothers(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = con.execute(
        f"""
        SELECT f.event_id,f.symbol,f.sleeve,CAST(f.signal_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,f.invalid_step_cum AS signal_invalid_step_cum,
          f.platform_high,r.latest_source_timestamp AS state_source_timestamp,
          'FROZEN_HISTORICAL_MOTHER' AS candidate_source
        FROM read_parquet('{FEATURES.as_posix()}') f
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON CAST(f.signal_date AS DATE)=CAST(r.trade_date AS DATE)
        WHERE year(f.signal_date) IN (2021,2023)
          AND r.market_regime='BULL'
          AND r.market_median_ret60>=0.05
          AND r.market_positive_ret60_share>=0.60
        ORDER BY signal_date,f.symbol
        """
    ).fetch_df()
    return frame


def current_bull_mothers(con: duckdb.DuckDBPyConnection, market: pd.DataFrame) -> pd.DataFrame:
    con.register("market_roll", market)
    frame = con.execute(
        feature_ctes()
        + f"""
        SELECT 'QIG-' || strftime(f.trade_date,'%Y%m%d') || '-' || f.symbol AS event_id,
          f.symbol,f.sleeve,CAST(f.trade_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,f.invalid_step_cum AS signal_invalid_step_cum,
          f.platform_high,m.latest_source_timestamp AS state_source_timestamp,
          'EXACT_ROLLFORWARD_MOTHER' AS candidate_source
        FROM featured f JOIN market_roll m
          ON CAST(f.trade_date AS DATE)=CAST(m.trade_date AS DATE)
        WHERE year(f.trade_date) IN (2024,2025,2026)
          AND {qfast.mother_condition()}
          AND m.strong_bull
        ORDER BY signal_date,f.symbol
        """
    ).fetch_df()
    return frame


def audit_identity(
    current: pd.DataFrame,
    frozen: pd.DataFrame,
    label: str,
    numeric_columns: tuple[str, ...] = (),
    exact_columns: tuple[str, ...] = (),
) -> dict[str, Any]:
    current = current.copy()
    frozen = frozen.copy()
    left_ids = set(current.event_id.astype(str))
    right_ids = set(frozen.event_id.astype(str))
    if left_ids != right_ids:
        raise RollforwardError(
            f"{label} identity canary failed: missing={len(right_ids - left_ids)} "
            f"extra={len(left_ids - right_ids)}"
        )
    columns = ["event_id", *numeric_columns, *exact_columns]
    merged = current[columns].merge(
        frozen[columns], on="event_id", suffixes=("_current", "_frozen"), validate="one_to_one"
    )
    max_diffs: dict[str, float] = {}
    for column in numeric_columns:
        value = float(
            (
                pd.to_numeric(merged[f"{column}_current"], errors="coerce")
                - pd.to_numeric(merged[f"{column}_frozen"], errors="coerce")
            )
            .abs()
            .max()
        )
        max_diffs[column] = value
        if not np.isfinite(value) or value > 1e-12:
            raise RollforwardError(f"{label} numeric canary failed {column}: {value}")
    exact_mismatch: dict[str, int] = {}
    for column in exact_columns:
        left = merged[f"{column}_current"]
        right = merged[f"{column}_frozen"]
        if "date" in column or "timestamp" in column:
            left = pd.to_datetime(left)
            right = pd.to_datetime(right)
        count = int((~(left.eq(right) | (left.isna() & right.isna()))).sum())
        exact_mismatch[column] = count
        if count:
            raise RollforwardError(f"{label} exact canary failed {column}: {count}")
    return {
        "events": len(current),
        "missing": 0,
        "extra": 0,
        "max_abs_differences": max_diffs,
        "exact_mismatches": exact_mismatch,
    }


def freeze_acceptances(
    con: duckdb.DuckDBPyConnection, mothers: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = mothers.copy()
    work["signal_date"] = pd.to_datetime(work.signal_date)
    work["path_end"] = np.where(
        work.signal_date.dt.year.isin([2023, 2024]),
        pd.Timestamp("2024-12-31"),
        DATA_END,
    )
    con.register(
        "bull_mother_work",
        work[["event_id", "symbol", "signal_cal_idx", "path_end"]],
    )
    paths = con.execute(
        """
        SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price
        FROM bull_mother_work c JOIN roll_daily d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
         AND d.trade_date<=CAST(c.path_end AS DATE)
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    ledger = pd.DataFrame(
        [
            v17c.freeze_acceptance_one(row, groups.get(str(row.event_id), pd.DataFrame()))
            for row in mothers.itertuples(index=False)
        ]
    )
    ledger["signal_date"] = pd.to_datetime(ledger.signal_date)
    accepted = ledger.loc[ledger.acceptance_status.eq("ACCEPTED")].copy()
    return ledger, accepted.reset_index(drop=True)


def oai_query() -> str:
    excluded = qfast.quoted_industries()
    return f"""
    WITH source AS (
      SELECT * FROM roll_daily
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '2026-09-04'
        AND sleeve IN ('MAIN','CHINEXT')
        AND causal_industry NOT IN ({excluded})
    ), windows AS (
      SELECT *,
        lag(coord_close,20) OVER w AS lag20_close_x,
        lag(cal_idx,20) OVER w AS lag20_idx_x,
        lag(invalid_step_cum,20) OVER w AS lag20_invalid_x,
        lag(coord_close,10) OVER w AS lag10_close_x,
        max(coord_high) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS prior5_high_x,
        avg(turnover_fraction) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS avg_to20_x,
        count(*) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS prior20_n_x,
        bool_and(history_valid) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS prior20_valid_x
      FROM source WINDOW w AS(PARTITION BY symbol ORDER BY trade_date)
    ), featured AS (
      SELECT *,coord_close/nullif(lag20_close_x,0)-1 AS ret20_x,
        coord_close/nullif(prior_coord_close,0)-1 AS step_return_x,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location_x,
        turnover_fraction/nullif(avg_to20_x,0) AS turnover_ratio_x,
        prior_coord_close/nullif(lag10_close_x,0)-1 AS prior10_return_x
      FROM windows WHERE year(trade_date) BETWEEN 2023 AND 2026
    )
    SELECT symbol,sleeve,CAST(trade_date AS DATE) AS signal_date,cal_idx,
      invalid_step_cum,available_at,decision_at,step_return_x,close_location_x,
      turnover_ratio_x,prior10_return_x
    FROM featured
    WHERE hard_valid AND history_valid AND current_valid
      AND current_day_data_tradable AND market_rule_valid
      AND corporate_action_valid AND NOT corporate_action_blocking AND NOT is_st
      AND prior20_n_x=20 AND prior20_valid_x
      AND cal_idx-lag20_idx_x=20 AND invalid_step_cum=lag20_invalid_x
      AND ret20_x<=-0.10 AND step_return_x>=0.05
      AND coord_close>prior5_high_x AND turnover_ratio_x>=1.0
      AND close_location_x>=0.70 AND round(close*100)<round(up_limit_price*100)
    ORDER BY symbol,cal_idx
    """


def build_bear_candidates(con: duckdb.DuckDBPyConnection, market: pd.DataFrame) -> pd.DataFrame:
    high_recall = con.execute(oai_query()).fetch_df()
    high_recall["signal_date"] = pd.to_datetime(high_recall.signal_date)
    base = v17c.apply_cooldown(high_recall)
    base = base.merge(
        market[
            [
                "trade_date",
                "market_regime",
                "market_positive_ret20_share",
                "positive_ret20_share_lag5",
                "latest_source_timestamp",
            ]
        ],
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    )
    selected = base.loc[
        base.market_regime.eq("BEAR")
        & base.market_positive_ret20_share.gt(base.positive_ret20_share_lag5)
        & base.prior10_return_x.le(-0.08)
    ].copy()
    selected = selected.rename(
        columns={
            "cal_idx": "signal_cal_idx",
            "invalid_step_cum": "signal_invalid_step_cum",
            "close_location_x": "rank_close_location",
            "turnover_ratio_x": "rank_turnover_ratio",
            "latest_source_timestamp": "state_source_timestamp",
        }
    )
    selected["signal_date"] = pd.to_datetime(selected.signal_date)
    if selected.state_source_timestamp.gt(selected.signal_date + pd.Timedelta(hours=15)).any():
        raise RollforwardError("bear state source is after signal decision")
    return selected.sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def max_calendar_and_cutoffs(
    con: duckdb.DuckDBPyConnection,
) -> tuple[int, dict[str, Any]]:
    maximum = int(
        con.execute(
            "SELECT max(cal_idx) FROM roll_daily WHERE trade_date<=DATE '2026-09-04'"
        ).fetchone()[0]
    )
    cutoffs: dict[str, Any] = {"data_end_cal_idx": maximum}
    for name, lag in (("v10", 64), ("v17_bull", 67)):
        idx = maximum - lag
        date = con.execute(
            f"SELECT max(trade_date) FROM roll_daily WHERE cal_idx={idx}"
        ).fetchone()[0]
        if date is None:
            raise RollforwardError(f"missing global maturity cutoff for {name}")
        cutoffs[f"{name}_mature_signal_cal_idx"] = idx
        cutoffs[f"{name}_mature_signal_date"] = str(pd.Timestamp(date).date())
    return maximum, cutoffs


def replay_one(candidate: Any, path: pd.DataFrame, bear: bool, end_label: str) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.signal_invalid_step_cum)
    decision_idx = signal_idx if bear else int(candidate.acceptance_decision_cal_idx)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "decision_cal_idx": decision_idx,
        "engine": "BEAR_FAST_CAPITULATION_ACTIVE_DEMAND"
        if bear
        else "STRONG_BULL_QUIET_INVENTORY_ACCEPTANCE",
    }
    same_lineage = path.loc[path.invalid_step_cum.eq(lineage)]
    entry_pool = same_lineage.loc[
        same_lineage.cal_idx.gt(decision_idx) & same_lineage.cal_idx.le(decision_idx + 3)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if acceptdev.buyable_open(row)), None)
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * (1.0 + TARGET)
    pending = False
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    invalid = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending and acceptdev.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H60_TIME_STOP"
            break
        if (
            acceptdev.legal_observation(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_20"
            break
        if acceptdev.legal_observation(row) and int(row.cal_idx) >= entry_idx + HORIZON:
            pending = True
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {**base, **entry_payload, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"}
    if exit_row is None:
        return {**base, **entry_payload, "status": f"INCOMPLETE_BY_{end_label}"}
    gross = float(exit_price) / entry_price - 1.0
    return {
        **base,
        **entry_payload,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - COST,
    }


def replay_candidates(
    con: duckdb.DuckDBPyConnection,
    candidates: pd.DataFrame,
    bear: bool,
    outcome_end: pd.Timestamp,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    con.register("replay_candidates_frame", candidates[["event_id", "symbol", "signal_cal_idx"]])
    paths = con.execute(
        f"""
        SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price
        FROM replay_candidates_frame c JOIN roll_daily d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
        WHERE d.trade_date<=DATE '{outcome_end:%Y-%m-%d}'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    records: list[dict[str, Any]] = []
    for candidate in candidates.itertuples(index=False):
        record = replay_one(
            candidate,
            groups.get(str(candidate.event_id), pd.DataFrame()),
            bear,
            outcome_end.strftime("%Y_%m_%d"),
        )
        if bear:
            record["rank_close_location"] = float(candidate.rank_close_location)
            record["rank_turnover_ratio"] = float(candidate.rank_turnover_ratio)
        records.append(record)
    return pd.DataFrame(records)


def standardize_frozen_v10(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["rank_close_location"] = pd.to_numeric(result.close_location_x, errors="coerce")
    result["rank_turnover_ratio"] = pd.to_numeric(result.turnover_ratio_x, errors="coerce")
    for column in ("signal_date", "entry_date", "exit_date"):
        result[column] = pd.to_datetime(result[column])
    return result


def outcome_audit(current: pd.DataFrame, frozen: pd.DataFrame, label: str) -> dict[str, Any]:
    return audit_identity(
        current,
        frozen,
        label,
        numeric_columns=("entry_price", "exit_price", "gross_return", "net_return"),
        exact_columns=(
            "status",
            "entry_date",
            "exit_date",
            "exit_reason",
            "entry_cal_idx",
            "exit_cal_idx",
        ),
    )


def already_consumed_canaries(
    con: duckdb.DuckDBPyConnection,
    bull_accepted: pd.DataFrame,
    bear_candidates: pd.DataFrame,
) -> dict[str, Any]:
    audits: dict[str, Any] = {}
    frozen_v10 = standardize_frozen_v10(
        con.execute(
            f"SELECT * FROM read_parquet(['{V10_ACCEPTED.as_posix()}',"
            f"'{V10_SKIPPED.as_posix()}'], union_by_name=true)"
        ).fetch_df()
    )
    frozen_v10_accepted = standardize_frozen_v10(
        con.execute(f"SELECT * FROM read_parquet('{V10_ACCEPTED.as_posix()}')").fetch_df()
    )
    recomputed_accepted, _ = v17c.apply_bear_capacity(frozen_v10)
    audits["v10_capacity_2023"] = audit_identity(
        recomputed_accepted.loc[recomputed_accepted.signal_date.dt.year.eq(2023)],
        frozen_v10_accepted.loc[frozen_v10_accepted.signal_date.dt.year.eq(2023)],
        "V10 capacity 2023",
    )

    for year in (2023, 2024):
        bear = bear_candidates.loc[bear_candidates.signal_date.dt.year.eq(year)].copy()
        current_bear = replay_candidates(con, bear, True, CANARY_OUTCOME_END)
        if year == 2023:
            frozen_bear = frozen_v10.loc[frozen_v10.signal_date.dt.year.eq(2023)].copy()
        else:
            frozen_bear = con.execute(
                f"SELECT * FROM read_parquet('{V17_BEAR_RAW_OUTCOMES_2024.as_posix()}')"
            ).fetch_df()
            for column in ("signal_date", "entry_date", "exit_date"):
                frozen_bear[column] = pd.to_datetime(frozen_bear[column])
        audits[f"v10_outcome_{year}"] = outcome_audit(
            current_bear, frozen_bear, f"V10 raw outcome {year}"
        )
        if year == 2024:
            accepted, _ = v17c.apply_bear_capacity(current_bear)
            frozen_accepted = con.execute(
                f"SELECT * FROM read_parquet('{V17_BEAR_ACCEPTED_2024.as_posix()}')"
            ).fetch_df()
            audits["v10_capacity_2024"] = audit_identity(
                accepted, frozen_accepted, "V10 capacity 2024"
            )

    frozen_bull = con.execute(
        f"SELECT * FROM read_parquet('{V17_BULL_OUTCOMES.as_posix()}')"
    ).fetch_df()
    for column in ("signal_date", "entry_date", "exit_date"):
        frozen_bull[column] = pd.to_datetime(frozen_bull[column])
    for year in (2023, 2024):
        candidates = bull_accepted.loc[bull_accepted.signal_date.dt.year.eq(year)].copy()
        current = replay_candidates(con, candidates, False, CANARY_OUTCOME_END)
        expected = frozen_bull.loc[frozen_bull.signal_date.dt.year.eq(year)].copy()
        audits[f"v17_bull_outcome_{year}"] = outcome_audit(
            current, expected, f"V17 bull outcome {year}"
        )
    return audits


def run_freeze() -> dict[str, Any]:
    if STAGE_A.exists() or STAGE_B.exists():
        raise RollforwardError("canonical output already exists; no overwrite allowed")
    _spec, source_hashes = read_spec_and_verify_inputs()
    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = EXT_ROOT / f".stage_a.{os.getpid()}.staging"
    if staging.exists():
        raise RollforwardError(f"staging path already exists: {staging}")
    staging.mkdir()
    tail, coordinate_audit = build_coordinate_tail(staging)
    con = connection()
    register_roll_daily(con, tail)
    market = build_market(con)
    market_audit = compare_market_canary(con, market)

    historical = historical_bull_mothers(con)
    current = current_bull_mothers(con, market)
    mothers = pd.concat([historical, current], ignore_index=True)
    mothers["signal_date"] = pd.to_datetime(mothers.signal_date)
    mothers = mothers.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
    if mothers.event_id.duplicated().any():
        raise RollforwardError("duplicate bull mother identity")
    bull_ledger, bull_accepted = freeze_acceptances(con, mothers)

    frozen_bull_ledger = con.execute(
        f"SELECT * FROM read_parquet('{V17_BULL_LEDGER.as_posix()}')"
    ).fetch_df()
    frozen_bull_accepted = con.execute(
        f"SELECT * FROM read_parquet('{V17_BULL_ACCEPTED.as_posix()}')"
    ).fetch_df()
    bull_identity_audit: dict[str, Any] = {}
    for year in (2023, 2024):
        curr_ledger = bull_ledger.loc[bull_ledger.signal_date.dt.year.eq(year)]
        ref_ledger = frozen_bull_ledger.loc[
            pd.to_datetime(frozen_bull_ledger.signal_date).dt.year.eq(year)
        ]
        bull_identity_audit[f"ledger_{year}"] = audit_identity(
            curr_ledger,
            ref_ledger,
            f"bull acceptance ledger {year}",
            numeric_columns=("platform_high", "observation_3_close_to_platform"),
            exact_columns=(
                "signal_date",
                "signal_cal_idx",
                "signal_invalid_step_cum",
                "acceptance_status",
                "acceptance_decision_date",
                "acceptance_decision_cal_idx",
            ),
        )
        curr_acc = bull_accepted.loc[bull_accepted.signal_date.dt.year.eq(year)]
        ref_acc = frozen_bull_accepted.loc[
            pd.to_datetime(frozen_bull_accepted.signal_date).dt.year.eq(year)
        ]
        bull_identity_audit[f"accepted_{year}"] = audit_identity(
            curr_acc, ref_acc, f"bull accepted identity {year}"
        )

    bear_candidates = build_bear_candidates(con, market)
    frozen_v10_all = con.execute(
        f"SELECT event_id FROM read_parquet(['{V10_ACCEPTED.as_posix()}','{V10_SKIPPED.as_posix()}']) WHERE year(signal_date)=2023"
    ).fetch_df()
    frozen_bear_2024 = con.execute(
        f"SELECT * FROM read_parquet('{V17_BEAR_RAW_2024.as_posix()}')"
    ).fetch_df()
    bear_identity_audit = {
        "2023": audit_identity(
            bear_candidates.loc[bear_candidates.signal_date.dt.year.eq(2023)],
            frozen_v10_all,
            "V10 raw identity 2023",
        ),
        "2024": audit_identity(
            bear_candidates.loc[bear_candidates.signal_date.dt.year.eq(2024)],
            frozen_bear_2024,
            "V10 raw identity 2024",
            numeric_columns=("rank_close_location", "rank_turnover_ratio"),
            exact_columns=("signal_date", "signal_cal_idx", "signal_invalid_step_cum"),
        ),
    }

    _, cutoffs = max_calendar_and_cutoffs(con)
    target_bear = bear_candidates.loc[
        bear_candidates.signal_date.dt.year.eq(2025)
        | (
            bear_candidates.signal_date.dt.year.eq(2026)
            & bear_candidates.signal_cal_idx.le(cutoffs["v10_mature_signal_cal_idx"])
        )
    ].copy()
    target_bull_ledger = bull_ledger.loc[
        bull_ledger.signal_date.dt.year.isin([2021, 2025])
        | (
            bull_ledger.signal_date.dt.year.eq(2026)
            & bull_ledger.signal_cal_idx.le(cutoffs["v17_bull_mature_signal_cal_idx"])
        )
    ].copy()
    target_bull_accepted = target_bull_ledger.loc[
        target_bull_ledger.acceptance_status.eq("ACCEPTED")
    ].copy()
    market_path = staging / "causal_market_2023_2026.parquet"
    bear_path = staging / "v10_candidates_2025_2026mature.parquet"
    bull_ledger_path = staging / "v17_bull_ledger_2021_2025_2026mature.parquet"
    bull_accepted_path = staging / "v17_bull_accepted_2021_2025_2026mature.parquet"
    write_parquet(market, market_path)
    write_parquet(target_bear, bear_path)
    write_parquet(target_bull_ledger, bull_ledger_path)
    write_parquet(target_bull_accepted, bull_accepted_path)

    pre_canary = {
        "experiment": EXPERIMENT,
        "stage": "IDENTITY_FROZEN_BEFORE_ANY_NEW_PERIOD_OUTCOME_READ",
        "spec_sha256": SPEC_SHA256,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "coordinate_tail_sha256": sha256(tail),
        "market_sha256": sha256(market_path),
        "v10_candidates_sha256": sha256(bear_path),
        "v17_bull_ledger_sha256": sha256(bull_ledger_path),
        "v17_bull_accepted_sha256": sha256(bull_accepted_path),
        "new_period_post_decision_path_read": "NO",
        "new_period_return_read": "NO",
    }
    pre_canary_path = staging / "identity_precanary_freeze.json"
    write_json(pre_canary_path, pre_canary)

    # Only already-consumed 2023/2024 outcome artifacts are opened below.
    outcome_canaries = already_consumed_canaries(con, bull_accepted, bear_candidates)
    con.close()
    freeze = {
        **pre_canary,
        "stage": "EXACT_IDENTITY_AND_ALREADY_CONSUMED_CANARY_FREEZE",
        "identity_precanary_freeze_sha256": sha256(pre_canary_path),
        "coordinate_reproduction_audit": coordinate_audit,
        "market_canary": market_audit,
        "bull_identity_canary": bull_identity_audit,
        "bear_identity_canary": bear_identity_audit,
        "already_consumed_outcome_and_capacity_canary": outcome_canaries,
        "maturity_cutoffs": cutoffs,
        "target_identity_counts": {
            "v10": {
                str(year): int(target_bear.signal_date.dt.year.eq(year).sum())
                for year in (2025, 2026)
            },
            "v17_bull_mothers": {
                str(year): int(target_bull_ledger.signal_date.dt.year.eq(year).sum())
                for year in (2021, 2025, 2026)
            },
            "v17_bull_accepted": {
                str(year): int(target_bull_accepted.signal_date.dt.year.eq(year).sum())
                for year in (2021, 2025, 2026)
            },
        },
        "new_period_post_decision_path_read": "NO",
        "new_period_return_read": "NO",
        "canary_outcomes_role": "PREVIOUSLY_CONSUMED_REPRODUCTION_ONLY",
    }
    write_json(staging / "identity_freeze.json", freeze)
    os.replace(staging, STAGE_A)
    return freeze


def verify_stage_a() -> tuple[dict[str, Any], Path]:
    if not STAGE_A.is_dir():
        raise RollforwardError("missing Stage-A identity freeze")
    freeze_path = STAGE_A / "identity_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    read_spec_and_verify_inputs()
    current = {
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "coordinate_tail_sha256": sha256(STAGE_A / "coordinate_tail_20260401_20260904.parquet"),
        "market_sha256": sha256(STAGE_A / "causal_market_2023_2026.parquet"),
        "v10_candidates_sha256": sha256(STAGE_A / "v10_candidates_2025_2026mature.parquet"),
        "v17_bull_ledger_sha256": sha256(STAGE_A / "v17_bull_ledger_2021_2025_2026mature.parquet"),
        "v17_bull_accepted_sha256": sha256(
            STAGE_A / "v17_bull_accepted_2021_2025_2026mature.parquet"
        ),
    }
    drift = {
        key: {"frozen": freeze.get(key), "current": value}
        for key, value in current.items()
        if freeze.get(key) != value
    }
    if drift:
        raise RollforwardError(f"Stage-A freeze drift: {drift}")
    if freeze.get("new_period_post_decision_path_read") != "NO":
        raise RollforwardError("Stage-A outcome-blind claim is not intact")
    return freeze, STAGE_A / "coordinate_tail_20260401_20260904.parquet"


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "all_frozen_signals": len(frame),
        "completed": len(completed),
        "incomplete_or_unfilled": int(len(frame) - len(completed)),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "win_rate": None if completed.empty else float(values.gt(0).mean()),
        "severe_loss_rate": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit_rate": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_20").mean()),
        "mean_holding_sessions": None
        if completed.empty
        else float(completed.holding_sessions.mean()),
        "decision_dates": int(completed.signal_date.nunique()),
    }


def yearly(frame: pd.DataFrame, years: tuple[int, ...]) -> dict[str, Any]:
    work = frame.copy()
    work["signal_date"] = pd.to_datetime(work.signal_date)
    return {str(year): metrics(work.loc[work.signal_date.dt.year.eq(year)]) for year in years}


def gate(year_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        year: {
            "completed_gt_50": item["completed"] > 50,
            "mean_net_gt_4pct": item["mean_net"] is not None and item["mean_net"] > 0.04,
            "passes_both": item["completed"] > 50
            and item["mean_net"] is not None
            and item["mean_net"] > 0.04,
        }
        for year, item in year_metrics.items()
    }


def render_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        "Mechanical exact-rule roll-forward only. No parameter, market-state, target, horizon, cost, or capacity change was made.",
        "",
        f"Data end: `{result['data_end']}`. V10 mature-2026 signal cutoff: `{result['maturity_cutoffs']['v10_mature_signal_date']}`; V17 bull mother cutoff: `{result['maturity_cutoffs']['v17_bull_mature_signal_date']}`.",
        "",
        "## V10 exact BEAR engine",
        "",
        "|Signal year|Frozen|Completed|Mean net|Median net|Win|Severe <=-10%|Target hit|Gate|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for year, item in result["v10_yearly"].items():
        check = result["v10_user_gate"][year]
        lines.append(
            f"|{year}|{item['all_frozen_signals']}|{item['completed']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|{item['win_rate']:.2%}|{item['severe_loss_rate']:.2%}|{item['target_hit_rate']:.2%}|{'PASS' if check['passes_both'] else 'FAIL'}|"
        )
    lines += [
        "",
        "2024 is the unchanged, already-consumed frozen V17 BEAR output; it was not rebuilt or optimized.",
        "",
        "## V17 exact dual engine",
        "",
        "|Signal year|Frozen|Completed|Mean net|Median net|Win|Severe <=-10%|Target hit|Gate|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for year, item in result["v17_yearly"].items():
        check = result["v17_user_gate"][year]
        lines.append(
            f"|{year}|{item['all_frozen_signals']}|{item['completed']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|{item['win_rate']:.2%}|{item['severe_loss_rate']:.2%}|{item['target_hit_rate']:.2%}|{'PASS' if check['passes_both'] else 'FAIL'}|"
        )
    lines += [
        "",
        "## Governance",
        "",
        "The 2023/2024 overlap canary had to reproduce identity, execution returns, and capacity before any requested new-period outcome path was attached. 2026 is mature YTD only, not a full-year claim. CY033 is PIT-B, so this is not relabeled strict PIT-A confirmation.",
        "",
        "The legacy V17 development contract said each year >50, while its old runner implemented pooled trades divided by seven >50. This report applies the user's explicit per-year gate without rewriting the historical verdict.",
        "",
    ]
    write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_name(f".{REPORT.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    os.replace(temporary, REPORT)


def run_evaluate() -> dict[str, Any]:
    if STAGE_B.exists():
        raise RollforwardError("canonical Stage-B output already exists; no overwrite")
    freeze, tail = verify_stage_a()
    staging = EXT_ROOT / f".stage_b.{os.getpid()}.staging"
    if staging.exists():
        raise RollforwardError(f"staging path already exists: {staging}")
    staging.mkdir()
    con = connection()
    register_roll_daily(con, tail)
    bear_candidates = con.execute(
        f"SELECT * FROM read_parquet('{(STAGE_A / 'v10_candidates_2025_2026mature.parquet').as_posix()}')"
    ).fetch_df()
    bear_candidates["signal_date"] = pd.to_datetime(bear_candidates.signal_date)
    bull_candidates = con.execute(
        f"SELECT * FROM read_parquet('{(STAGE_A / 'v17_bull_accepted_2021_2025_2026mature.parquet').as_posix()}')"
    ).fetch_df()
    bull_candidates["signal_date"] = pd.to_datetime(bull_candidates.signal_date)

    # This is the first requested-new-period post-decision path attachment.
    bear_raw = replay_candidates(con, bear_candidates, True, DATA_END)
    bull_outcomes = replay_candidates(con, bull_candidates, False, DATA_END)

    frozen_2024_raw = con.execute(
        f"SELECT * FROM read_parquet('{V17_BEAR_RAW_OUTCOMES_2024.as_posix()}')"
    ).fetch_df()
    frozen_2024_raw["signal_date"] = pd.to_datetime(frozen_2024_raw.signal_date)
    rolling_capacity_input = pd.concat([frozen_2024_raw, bear_raw], ignore_index=True)
    accepted_roll, skipped_roll = v17c.apply_bear_capacity(rolling_capacity_input)
    frozen_2024_accepted = con.execute(
        f"SELECT * FROM read_parquet('{V17_BEAR_ACCEPTED_2024.as_posix()}')"
    ).fetch_df()
    capacity_roll_canary = audit_identity(
        accepted_roll.loc[pd.to_datetime(accepted_roll.signal_date).dt.year.eq(2024)],
        frozen_2024_accepted,
        "rolling capacity retained frozen 2024",
    )
    new_bear_accepted = accepted_roll.loc[
        pd.to_datetime(accepted_roll.signal_date).dt.year.isin([2025, 2026])
    ].copy()
    new_bear_skipped = skipped_roll.loc[
        pd.to_datetime(skipped_roll.signal_date).dt.year.isin([2025, 2026])
    ].copy()

    v10_2024 = con.execute(
        f"SELECT * FROM read_parquet('{V17_BEAR_ACCEPTED_2024.as_posix()}')"
    ).fetch_df()
    v10_2024["signal_date"] = pd.to_datetime(v10_2024.signal_date)
    v10_roll = pd.concat([v10_2024, new_bear_accepted], ignore_index=True)
    v10_roll["signal_date"] = pd.to_datetime(v10_roll.signal_date)

    v10_hist_2021 = con.execute(
        f"""
        SELECT event_id,symbol,sleeve,signal_date,entry_date,entry_cal_idx,entry_price,
          exit_date,exit_cal_idx,exit_price,exit_reason,holding_sessions,gross_return,
          net_return,status,'BEAR_FAST_CAPITULATION_ACTIVE_DEMAND' AS engine
        FROM read_parquet('{V10_ACCEPTED.as_posix()}')
        WHERE year(signal_date)=2021 AND status='COMPLETED'
        """
    ).fetch_df()
    bull_completed = bull_outcomes.loc[bull_outcomes.status.eq("COMPLETED")].copy()
    bear_new_common = new_bear_accepted.copy()
    bear_new_common["engine"] = "BEAR_FAST_CAPITULATION_ACTIVE_DEMAND"
    common = [
        "event_id",
        "symbol",
        "sleeve",
        "signal_date",
        "entry_date",
        "entry_cal_idx",
        "entry_price",
        "exit_date",
        "exit_cal_idx",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "gross_return",
        "net_return",
        "status",
        "engine",
    ]
    v17_roll = pd.concat(
        [v10_hist_2021[common], bear_new_common[common], bull_completed[common]],
        ignore_index=True,
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        v17_roll[column] = pd.to_datetime(v17_roll[column])
    if v17_roll.event_id.duplicated().any():
        raise RollforwardError("duplicate V17 roll-forward event identity")
    if v17_roll.entry_date.le(v17_roll.signal_date).any():
        raise RollforwardError("same-bar or pre-signal fill entered V17 ledger")
    if v17_roll.exit_cal_idx.le(v17_roll.entry_cal_idx).any():
        raise RollforwardError("exit at or before entry entered V17 ledger")
    con.close()

    paths = {
        "v10_raw": staging / "v10_raw_outcomes_2025_2026mature.parquet",
        "v10_accepted": staging / "v10_capacity_accepted_2025_2026mature.parquet",
        "v10_skipped": staging / "v10_capacity_skipped_2025_2026mature.parquet",
        "v17_bull": staging / "v17_bull_outcomes_2021_2025_2026mature.parquet",
        "v10_roll": staging / "v10_2024_2026mature_ledger.parquet",
        "v17_roll": staging / "v17_2021_2025_2026mature_ledger.parquet",
    }
    frames = {
        "v10_raw": bear_raw,
        "v10_accepted": new_bear_accepted,
        "v10_skipped": new_bear_skipped,
        "v17_bull": bull_outcomes,
        "v10_roll": v10_roll,
        "v17_roll": v17_roll,
    }
    for name, path in paths.items():
        write_parquet(frames[name], path)

    v10_yearly = yearly(v10_roll, (2024, 2025, 2026))
    v17_yearly = yearly(v17_roll, (2021, 2025, 2026))
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "MECHANICAL_POST_OBSERVATION_ROLLFORWARD",
        "spec_sha256": SPEC_SHA256,
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A / "identity_freeze.json"),
        "data_end": str(DATA_END.date()),
        "maturity_cutoffs": freeze["maturity_cutoffs"],
        "canary_status": "PASS",
        "rolling_capacity_2024_canary": capacity_roll_canary,
        "v10_yearly": v10_yearly,
        "v10_user_gate": gate(v10_yearly),
        "v17_yearly": v17_yearly,
        "v17_user_gate": gate(v17_yearly),
        "v17_engine_yearly": {
            str(year): {
                engine: metrics(part)
                for engine, part in v17_roll.loc[v17_roll.signal_date.dt.year.eq(year)].groupby(
                    "engine", sort=True
                )
            }
            for year in (2021, 2025, 2026)
        },
        "new_outcome_read_after_identity_freeze": True,
        "2026_full_year_claim": False,
        "strict_pit_a_claim": False,
        "legacy_v17_gate_mismatch_preserved": True,
        "external_output_hashes": {name: sha256(path) for name, path in paths.items()},
    }
    write_json(staging / "result.json", result)
    result["external_result_sha256"] = sha256(staging / "result.json")
    write_json(staging / "manifest.json", result)
    os.replace(staging, STAGE_B)
    render_report(result)
    return {
        **result,
        "repo_result_sha256": sha256(RESULT),
        "repo_report_sha256": sha256(REPORT),
        "external_manifest_sha256": sha256(STAGE_B / "manifest.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("freeze", "evaluate"), required=True)
    args = parser.parse_args()
    payload = run_freeze() if args.stage == "freeze" else run_evaluate()
    print(json.dumps(json_ready(payload), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
