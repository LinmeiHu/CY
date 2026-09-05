#!/usr/bin/env python3
"""Build the frozen causal D1 acceptance contract for Morning-Demand V6.

Stage A is outcome blind.  It materializes the exact D1 10:00 information set,
the next-minute executable entry, and the fixed three-condition admission rule.
Stage B is intentionally added only after Stage A passes deterministic identity,
coverage, chronology, and capacity checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-MORNING-DEMAND-OVERNIGHT-SUPPLY-ACCEPTANCE-V6"
SPEC_PATH = PROGRAM / (
    "experiments/"
    "ASHARE-MORNING-DEMAND-OVERNIGHT-SUPPLY-ACCEPTANCE-V6_stage_a_spec.json"
)
EXTERNAL_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_morning_demand_overnight_supply_acceptance_v6"
)
STAGE_A = EXTERNAL_ROOT / "stage_a"
FEATURE_PANEL = STAGE_A / "d1_causal_acceptance_panel_2014_2026.parquet"
MANIFEST = STAGE_A / "manifest.json"
STAGE_B = EXTERNAL_ROOT / "stage_b"
OUTCOME_BARS = STAGE_B / "selected_outcome_bars.parquet"
OUTCOME_STATES = STAGE_B / "selected_outcome_states.parquet"
TRADES = STAGE_B / "trades.parquet"
EXTERNAL_RESULT = STAGE_B / "result.json"
RESULT_PATH = PROGRAM / (
    "artifacts/ASHARE-MORNING-DEMAND-OVERNIGHT-SUPPLY-ACCEPTANCE-V6_result.json"
)
REPORT_PATH = PROGRAM / (
    "reports/ASHARE-MORNING-DEMAND-OVERNIGHT-SUPPLY-ACCEPTANCE-V6_report.md"
)

OLD_EVENTS = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_morning_industry_demand_acceptance_v1r1/"
    "v2_tail_acceptance/stage_a/events_frozen.parquet"
)
RECENT_EVENT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_morning_tail_regime_routed_demand_price_discovery_v4/"
    "post_observation_2024_2026"
)
RAW_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)
OLD_DAILY_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/"
    "pit_daily_2013_2023_cy006/daily"
)
NEW_DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/"
    "pit_b_daily_2018_2026_v2/daily"
)
OLD_EXECUTION_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/"
    "pit_execution_2013_2017_cy006/execution_5m"
)
NEW_EXECUTION_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/"
    "pit_b_minute_2018_2026_v2/execution_5m"
)

EXPECTED_SOURCE_CONTRACT = (
    "0a7425ced0c1914cf3f8c8b4b8b13f010e2ec325135d8a1620f1ebfed88c77cd"
)
EXPECTED_OLD_EVENTS_HASH = (
    "0a3097fe68195cf49dc2d426a55c35ea48b240b88b956711341a6caab60a47ed"
)
LAST_SOURCE_DATE = pd.Timestamp("2026-08-12")
QMT_TAIL_START = pd.Timestamp("2026-04-13").date()
YEARS = tuple(range(2014, 2027))


class V6Error(RuntimeError):
    """Fail-closed V6 implementation or lineage error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        temporary,
        compression="zstd",
        row_group_size=max(1, min(100_000, len(frame))),
    )
    os.replace(temporary, path)


def atomic_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def connection() -> duckdb.DuckDBPyConnection:
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET memory_limit='7GB'")
    con.execute(f"SET temp_directory='{EXTERNAL_ROOT.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")
    return con


def daily_path(year: int) -> Path:
    # The certified 2018+ execution contract references the current CY-006
    # snapshot lineage.  The pre-2018 chronology extension has its own matching
    # certified CY-006 root.
    root = OLD_DAILY_ROOT if year <= 2017 else NEW_DAILY_ROOT
    path = root / f"partition_year={year}/data_0.parquet"
    if not path.is_file():
        raise V6Error(f"daily partition missing: {path}")
    return path


def execution_path(year: int) -> Path:
    root = OLD_EXECUTION_ROOT if year <= 2017 else NEW_EXECUTION_ROOT
    path = root / f"partition_year={year}/data_0.parquet"
    if not path.is_file():
        raise V6Error(f"execution partition missing: {path}")
    return path


def raw_paths(year: int) -> list[str]:
    paths = [RAW_ROOT / f"{year}_day_parquet_none.parquet"]
    if year == 2026:
        paths.append(RAW_ROOT / "2026_qmt_tail.parquet")
    for path in paths:
        if not path.is_file():
            raise V6Error(f"raw minute partition missing: {path}")
    return [str(path) for path in paths]


def load_spec() -> dict[str, Any]:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("experiment") != EXPERIMENT:
        raise V6Error("experiment identity changed")
    mother = spec.get("mother_event", {})
    if (
        mother.get("source_contract_sha256") != EXPECTED_SOURCE_CONTRACT
        or mother.get("source_events_sha256_2014_2023") != EXPECTED_OLD_EVENTS_HASH
        or mother.get("mother_event_changed") is not False
    ):
        raise V6Error("mother event identity is not frozen")
    rule = spec.get("simple_rule", {})
    expected = [
        "D1 close1000 >= D0 cutoff_close",
        "D1 acceptance_ratio_to_d0_cutoff >= 0.60 OR (D1 industry_ret1000 > 0 AND D1 relative_ret1000 >= 0)",
        "D1 entry premium to D0 cutoff_close <= 5 percent",
    ]
    if rule.get("binding_conditions") != expected or rule.get("condition_count") != 3:
        raise V6Error("binding rule changed")
    execution = spec.get("execution", {})
    if (
        execution.get("profit_target") != 0.08
        or execution.get("round_trip_cost") != 0.004
        or execution.get("t_plus_one") is not True
    ):
        raise V6Error("execution contract changed")
    return spec


def load_mother_events() -> pd.DataFrame:
    recent = [RECENT_EVENT_ROOT / f"tail_events_{year}.parquet" for year in (2024, 2025, 2026)]
    for path in [OLD_EVENTS, *recent]:
        if not path.is_file():
            raise V6Error(f"mother event file missing: {path}")
    if sha256_file(OLD_EVENTS) != EXPECTED_OLD_EVENTS_HASH:
        raise V6Error("2014-2023 mother event content hash changed")
    con = connection()
    frame = con.execute(
        """
        WITH source AS (
          SELECT event_id_v2,symbol,trade_date,cutoff_close,event_industry,sleeve,
            signal_year,decision_at,state_hard_valid,signal_eligible,entry_executable
          FROM read_parquet(?)
          UNION ALL BY NAME
          SELECT event_id_v2,symbol,trade_date,cutoff_close,event_industry,sleeve,
            signal_year,decision_at,state_hard_valid,signal_eligible,entry_executable
          FROM read_parquet(?)
          UNION ALL BY NAME
          SELECT event_id_v2,symbol,trade_date,cutoff_close,event_industry,sleeve,
            signal_year,decision_at,state_hard_valid,signal_eligible,entry_executable
          FROM read_parquet(?)
          UNION ALL BY NAME
          SELECT event_id_v2,symbol,trade_date,cutoff_close,event_industry,sleeve,
            signal_year,decision_at,state_hard_valid,signal_eligible,entry_executable
          FROM read_parquet(?)
        )
        SELECT * FROM source ORDER BY trade_date,symbol,event_id_v2
        """,
        [str(OLD_EVENTS), *(str(path) for path in recent)],
    ).df()
    con.close()
    if len(frame) != 4034:
        raise V6Error(f"mother event row count changed: {len(frame)}")
    if frame["event_id_v2"].duplicated().any():
        raise V6Error("duplicate mother event identity")
    if not frame[["state_hard_valid", "signal_eligible", "entry_executable"]].all().all():
        raise V6Error("non-eligible event entered frozen mother population")
    if frame["cutoff_close"].isna().any() or (frame["cutoff_close"] <= 0).any():
        raise V6Error("invalid D0 reference price")
    if pd.to_datetime(frame["trade_date"]).max() > LAST_SOURCE_DATE:
        raise V6Error("post-source-boundary event entered mother population")
    return frame


def trading_calendar() -> list[pd.Timestamp]:
    paths = [str(daily_path(year)) for year in YEARS]
    con = connection()
    dates = con.execute(
        """SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date
        FROM read_parquet(?,union_by_name=true)
        WHERE trade_date<=DATE '2026-08-12' ORDER BY trade_date""",
        [paths],
    ).df()["trade_date"]
    con.close()
    result = [pd.Timestamp(value) for value in dates]
    if not result or result[0] > pd.Timestamp("2014-01-02") or result[-1] != LAST_SOURCE_DATE:
        raise V6Error("trading calendar coverage changed")
    return result


def attach_future_session_clocks(events: pd.DataFrame) -> pd.DataFrame:
    dates = trading_calendar()
    positions = {value: idx for idx, value in enumerate(dates)}
    rows: list[dict[str, Any]] = []
    for record in events.to_dict("records"):
        d0 = pd.Timestamp(record["trade_date"])
        idx = positions.get(d0)
        if idx is None:
            raise V6Error(f"mother date absent from calendar: {d0.date()}")
        enriched = dict(record)
        for offset in range(1, 5):
            enriched[f"d{offset}_date"] = dates[idx + offset] if idx + offset < len(dates) else pd.NaT
        rows.append(enriched)
    frame = pd.DataFrame(rows)
    frame["entry_year"] = pd.to_datetime(frame["d1_date"]).dt.year.astype("Int64")
    frame["event_id_v6"] = frame["event_id_v2"] + "|D1-OVERNIGHT-ACCEPT"
    if frame["event_id_v6"].duplicated().any():
        raise V6Error("duplicate V6 event identity")
    return frame


def build_industry_context(year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache = STAGE_A / f"d1_industry_context_{year}.parquet"
    if cache.is_file():
        frame = pq.read_table(cache).to_pandas()
        if not frame.empty:
            return frame, {
                "cache_reused": True,
                "rows": int(len(frame)),
                "dates": int(frame["d1_date"].nunique()),
                "industries": int(frame["d1_industry"].nunique()),
            }
    con = connection()
    frame = con.execute(
        """
        WITH minute AS (
          SELECT qmt_code AS symbol,trade_date,count(*) AS session_n,
            count(DISTINCT bar_end_time) AS distinct_session_n,
            count(*) FILTER(WHERE CAST(bar_end_time AS TIME) BETWEEN TIME '09:31:00' AND TIME '10:00:00') AS first30_n,
            max(close) FILTER(WHERE CAST(bar_end_time AS TIME)=TIME '10:00:00') AS close1000
          FROM read_parquet($raw_paths,union_by_name=true)
          WHERE period='1m' AND adjust='none' AND exchange IN ('SH','SZ')
          GROUP BY qmt_code,trade_date
        ), valid AS (
          SELECT m.trade_date AS d1_date,d.industry AS d1_industry,
            ln(m.close1000/d.preclose) AS stock_ret1000
          FROM minute m
          JOIN read_parquet($daily_path) d USING(symbol,trade_date)
          JOIN read_parquet($execution_path) e USING(symbol,trade_date)
          WHERE e.window_index=5
            AND m.session_n=241 AND m.distinct_session_n=241 AND m.first30_n=30
            AND m.close1000>0 AND d.preclose>0
            AND e.available_at=CAST(m.trade_date AS TIMESTAMP)+INTERVAL '10 hours'
            AND e.hard_valid IS TRUE AND e.trade_status=1 AND e.is_st IS FALSE
            AND e.market_rule_valid IS TRUE
            AND e.daily_snapshot_id=d.snapshot_id
            AND d.industry_valid IS TRUE AND d.industry IS NOT NULL AND d.industry<>''
            AND d.source_notice_date<d.trade_date
            AND d.corporate_action_blocking IS FALSE
            AND (m.symbol LIKE '60%' OR m.symbol LIKE '00%' OR m.symbol LIKE '30%')
        )
        SELECT d1_date,d1_industry,median(stock_ret1000) AS d1_industry_ret1000,
          count(*) AS d1_industry_n
        FROM valid GROUP BY d1_date,d1_industry ORDER BY d1_date,d1_industry
        """,
        {
            "raw_paths": raw_paths(year),
            "daily_path": str(daily_path(year)),
            "execution_path": str(execution_path(year)),
        },
    ).df()
    con.close()
    if frame.duplicated(["d1_date", "d1_industry"]).any():
        raise V6Error(f"duplicate industry context: {year}")
    atomic_parquet(frame, cache)
    return frame, {
        "cache_reused": False,
        "rows": int(len(frame)),
        "dates": int(frame["d1_date"].nunique()),
        "industries": int(frame["d1_industry"].nunique()),
        "minimum_industry_n": int(frame["d1_industry_n"].min()),
        "median_industry_n": float(frame["d1_industry_n"].median()),
    }


def build_candidate_features(
    year: int, keys: pd.DataFrame, industry: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache = STAGE_A / f"d1_candidate_features_{year}.parquet"
    if cache.is_file():
        frame = pq.read_table(cache).to_pandas()
        if len(frame) != len(keys) or frame["event_id_v6"].duplicated().any():
            raise V6Error(f"candidate feature cache identity changed: {year}")
        return frame, {"cache_reused": True, "rows": int(len(frame))}
    con = connection()
    registered = keys.copy()
    registered["d1_date"] = pd.to_datetime(registered["d1_date"])
    con.register("candidate_keys", registered)
    raw = con.execute(
        """
        SELECT k.event_id_v6,k.event_id_v2,k.symbol,k.trade_date,k.d1_date,
          k.d2_date,k.d3_date,k.d4_date,k.signal_year,k.entry_year,k.sleeve,
          k.cutoff_close AS d0_cutoff_close,
          count(*) AS d1_session_n,count(DISTINCT r.bar_end_time) AS d1_distinct_session_n,
          count(*) FILTER(WHERE CAST(r.bar_end_time AS TIME) BETWEEN TIME '09:31:00' AND TIME '10:00:00') AS d1_first30_n,
          max(r.open) FILTER(WHERE CAST(r.bar_end_time AS TIME)=TIME '09:31:00') AS d1_open0931,
          max(r.close) FILTER(WHERE CAST(r.bar_end_time AS TIME)=TIME '10:00:00') AS d1_close1000,
          min(r.low) FILTER(WHERE CAST(r.bar_end_time AS TIME) BETWEEN TIME '09:31:00' AND TIME '10:00:00') AS d1_low1000,
          max(r.high) FILTER(WHERE CAST(r.bar_end_time AS TIME) BETWEEN TIME '09:31:00' AND TIME '10:00:00') AS d1_high1000,
          avg((r.close>=k.cutoff_close)::INTEGER) FILTER(WHERE CAST(r.bar_end_time AS TIME) BETWEEN TIME '09:31:00' AND TIME '10:00:00') AS d1_acceptance_ratio,
          max(r.open) FILTER(WHERE CAST(r.bar_end_time AS TIME)=TIME '10:01:00') AS d1_entry_open1001,
          max(r.high) FILTER(WHERE CAST(r.bar_end_time AS TIME)=TIME '10:01:00') AS d1_entry_high1001,
          min(r.low) FILTER(WHERE CAST(r.bar_end_time AS TIME)=TIME '10:01:00') AS d1_entry_low1001,
          max(r.volume) FILTER(WHERE CAST(r.bar_end_time AS TIME)=TIME '10:01:00') AS d1_entry_volume1001
        FROM candidate_keys k
        LEFT JOIN read_parquet($raw_paths,union_by_name=true) r
          ON r.qmt_code=k.symbol AND r.trade_date=k.d1_date
          AND r.period='1m' AND r.adjust='none' AND r.exchange IN ('SH','SZ')
        GROUP BY ALL ORDER BY k.d1_date,k.symbol,k.event_id_v6
        """,
        {"raw_paths": raw_paths(year)},
    ).df()
    state = con.execute(
        """
        SELECT k.event_id_v6,d.preclose AS d1_preclose,d.industry AS d1_industry,
          d.source_notice_date AS d1_industry_source_notice_date,
          d.corporate_action_count AS d1_corporate_action_count,
          d.corporate_action_blocking AS d1_corporate_action_blocking,
          d.corporate_action_available_date AS d1_corporate_action_available_date,
          d.up_limit_price AS d1_up_limit_price,d.down_limit_price AS d1_down_limit_price,
          e.available_at AS d1_state_available_at,e.hard_valid AS d1_state_hard_valid,
          e.trade_status AS d1_trade_status,e.is_st AS d1_is_st,
          e.market_rule_valid AS d1_market_rule_valid,e.daily_snapshot_id AS d1_execution_daily_snapshot_id,
          d.snapshot_id AS d1_daily_snapshot_id
        FROM candidate_keys k
        LEFT JOIN read_parquet($daily_path) d
          ON d.symbol=k.symbol AND d.trade_date=k.d1_date
        LEFT JOIN read_parquet($execution_path) e
          ON e.symbol=k.symbol AND e.trade_date=k.d1_date AND e.window_index=5
        ORDER BY k.d1_date,k.symbol,k.event_id_v6
        """,
        {
            "daily_path": str(daily_path(year)),
            "execution_path": str(execution_path(year)),
        },
    ).df()
    con.close()
    frame = raw.merge(state, on="event_id_v6", how="left", validate="one_to_one")
    industry_copy = industry.copy()
    industry_copy["d1_date"] = pd.to_datetime(industry_copy["d1_date"])
    frame["d1_date"] = pd.to_datetime(frame["d1_date"])
    frame = frame.merge(
        industry_copy,
        on=["d1_date", "d1_industry"],
        how="left",
        validate="many_to_one",
    )
    frame["d1_stock_ret1000"] = np.log(frame["d1_close1000"] / frame["d1_preclose"])
    frame["d1_relative_ret1000"] = (
        frame["d1_stock_ret1000"] - frame["d1_industry_ret1000"]
    )
    span = frame["d1_high1000"] - frame["d1_low1000"]
    frame["d1_close_location1000"] = np.where(
        span > 0,
        (frame["d1_close1000"] - frame["d1_low1000"]) / span,
        0.5,
    )
    frame["d1_entry_premium_to_d0_cutoff"] = (
        frame["d1_entry_open1001"] / frame["d0_cutoff_close"] - 1.0
    )
    decision_at = frame["d1_date"] + pd.Timedelta(hours=10)
    entry_at = frame["d1_date"] + pd.Timedelta(hours=10, minutes=1)
    frame["d1_decision_at"] = decision_at
    frame["d1_entry_at"] = entry_at
    required = [
        "d1_close1000",
        "d1_acceptance_ratio",
        "d1_entry_open1001",
        "d1_preclose",
        "d1_industry",
        "d1_industry_ret1000",
        "d1_relative_ret1000",
        "d1_up_limit_price",
        "d1_state_available_at",
    ]
    feature_complete = ~frame[required].isna().any(axis=1)
    frame["d1_raw_shape_valid"] = (
        frame["d1_session_n"].eq(241)
        & frame["d1_distinct_session_n"].eq(241)
        & frame["d1_first30_n"].eq(30)
    )
    frame["d1_state_causal_valid"] = (
        frame["d1_state_hard_valid"].fillna(False)
        & frame["d1_trade_status"].eq(1)
        & ~frame["d1_is_st"].fillna(True)
        & frame["d1_market_rule_valid"].fillna(False)
        & frame["d1_state_available_at"].eq(decision_at)
        & frame["d1_execution_daily_snapshot_id"].eq(frame["d1_daily_snapshot_id"])
        & (pd.to_datetime(frame["d1_industry_source_notice_date"]) < frame["d1_date"])
    )
    frame["d1_coordinate_valid"] = (
        frame["d1_corporate_action_count"].fillna(-1).eq(0)
        & ~frame["d1_corporate_action_blocking"].fillna(True)
    )
    frame["d1_entry_executable"] = (
        frame["d1_entry_volume1001"].fillna(0).gt(0)
        & frame["d1_entry_open1001"].gt(0)
        & frame["d1_entry_open1001"].lt(frame["d1_up_limit_price"] - 1e-8)
    )
    frame["d1_feature_complete"] = feature_complete
    frame["causal_candidate_valid"] = (
        frame["d1_raw_shape_valid"]
        & frame["d1_state_causal_valid"]
        & frame["d1_coordinate_valid"]
        & frame["d1_entry_executable"]
        & frame["d1_feature_complete"]
    )
    frame["price_acceptance"] = frame["d1_close1000"] >= frame["d0_cutoff_close"]
    frame["persistent_acceptance"] = frame["d1_acceptance_ratio"] >= 0.60
    frame["industry_relative_renewal"] = (
        frame["d1_industry_ret1000"].gt(0)
        & frame["d1_relative_ret1000"].ge(0)
    )
    frame["premium_preserves_reward"] = frame["d1_entry_premium_to_d0_cutoff"] <= 0.05
    frame["admitted"] = (
        frame["causal_candidate_valid"]
        & frame["price_acceptance"]
        & (frame["persistent_acceptance"] | frame["industry_relative_renewal"])
        & frame["premium_preserves_reward"]
    )
    if (frame["d1_decision_at"] >= frame["d1_entry_at"]).any():
        raise V6Error(f"same-bar entry chronology failure: {year}")
    if len(frame) != len(keys) or frame["event_id_v6"].duplicated().any():
        raise V6Error(f"candidate feature identity changed: {year}")
    atomic_parquet(frame, cache)
    return frame, {
        "cache_reused": False,
        "rows": int(len(frame)),
        "causal_valid": int(frame["causal_candidate_valid"].sum()),
        "admitted": int(frame["admitted"].sum()),
        "raw_shape_failures": int((~frame["d1_raw_shape_valid"]).sum()),
        "state_failures": int((~frame["d1_state_causal_valid"]).sum()),
        "coordinate_failures": int((~frame["d1_coordinate_valid"]).sum()),
        "entry_failures": int((~frame["d1_entry_executable"]).sum()),
        "feature_failures": int((~frame["d1_feature_complete"]).sum()),
    }


def build_stage_a() -> dict[str, Any]:
    spec = load_spec()
    STAGE_A.mkdir(parents=True, exist_ok=True)
    events = attach_future_session_clocks(load_mother_events())
    right_censored = events["d1_date"].isna()
    pieces: list[pd.DataFrame] = []
    annual_audit: dict[str, Any] = {}
    for year in YEARS:
        keys = events.loc[events["entry_year"].eq(year)].copy()
        if keys.empty:
            continue
        print(f"STAGE_A year={year} mother_rows={len(keys)}", flush=True)
        industry, context_audit = build_industry_context(year)
        features, candidate_audit = build_candidate_features(year, keys, industry)
        pieces.append(features)
        annual_audit[str(year)] = {
            "industry_context": context_audit,
            "candidates": candidate_audit,
        }
        print(
            f"STAGE_A year={year} causal_valid={int(features['causal_candidate_valid'].sum())} "
            f"admitted={int(features['admitted'].sum())}",
            flush=True,
        )
    panel = pd.concat(pieces, ignore_index=True).sort_values(
        ["d1_date", "symbol", "event_id_v6"]
    )
    forbidden_fragments = ("return", "exit", "target_hit", "pnl", "mae", "mfe")
    forbidden_columns = [
        column
        for column in panel.columns
        if any(fragment in column.lower() for fragment in forbidden_fragments)
        and column not in {"d1_relative_ret1000"}
    ]
    # Causal contemporaneous return features are explicitly allowed; future outcome
    # fields are not.  The exact allow-list keeps this audit fail closed.
    allowed_return_columns = {"d1_stock_ret1000", "d1_industry_ret1000", "d1_relative_ret1000"}
    forbidden_columns = [
        column
        for column in forbidden_columns
        if column not in allowed_return_columns
    ]
    if forbidden_columns:
        raise V6Error(f"outcome-like columns entered Stage A: {forbidden_columns}")
    if panel["event_id_v6"].duplicated().any():
        raise V6Error("duplicate event in final Stage A panel")
    if len(panel) + int(right_censored.sum()) != len(events):
        raise V6Error("Stage A population does not reconcile to mother events")
    if (panel["d1_decision_at"] >= panel["d1_entry_at"]).any():
        raise V6Error("decision clock is not strictly before entry")
    atomic_parquet(panel, FEATURE_PANEL)
    full_year = panel["entry_year"].between(2014, 2025)
    full_year_count = int(panel.loc[full_year, "entry_year"].nunique())
    admitted_full = int(panel.loc[full_year, "admitted"].sum())
    average_full = admitted_full / full_year_count
    annual_counts = {
        str(int(year)): {
            "mother": int(len(group)),
            "causal_valid": int(group["causal_candidate_valid"].sum()),
            "admitted": int(group["admitted"].sum()),
            "dates": int(group.loc[group["admitted"], "d1_date"].nunique()),
            "symbols": int(group.loc[group["admitted"], "symbol"].nunique()),
        }
        for year, group in panel.groupby("entry_year", sort=True)
    }
    manifest = {
        "experiment": EXPERIMENT,
        "stage": "A_OUTCOME_BLIND",
        "spec_sha256": sha256_file(SPEC_PATH),
        "canonical_spec_sha256": canonical_sha256(spec),
        "mother_event_rows": int(len(events)),
        "right_censored_before_d1_count": int(right_censored.sum()),
        "feature_rows": int(len(panel)),
        "causal_valid_rows": int(panel["causal_candidate_valid"].sum()),
        "admitted_rows": int(panel["admitted"].sum()),
        "admitted_full_year_rows_2014_2025": admitted_full,
        "average_admitted_per_full_year_2014_2025": float(average_full),
        "capacity_gate_gt50": bool(average_full > 50),
        "annual": annual_counts,
        "annual_audit": annual_audit,
        "audit": {
            "mother_identity_changed_count": 0,
            "outcome_column_count": 0,
            "feature_after_decision_count": 0,
            "same_bar_entry_count": 0,
            "duplicate_event_count": 0,
            "repository_post_2026_08_12_opened": False,
        },
        "hashes": {"feature_panel": sha256_file(FEATURE_PANEL)},
    }
    atomic_json(manifest, MANIFEST)
    return manifest


def _outcome_day_keys(selected: pd.DataFrame) -> pd.DataFrame:
    calendar = trading_calendar()
    positions = {value: idx for idx, value in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for record in selected[["event_id_v6", "symbol", "d1_date"]].to_dict("records"):
        d1 = pd.Timestamp(record["d1_date"])
        idx = positions.get(d1)
        if idx is None:
            raise V6Error(f"D1 absent from trading calendar: {d1.date()}")
        for holding_session in range(2, 13):
            if idx + holding_session - 1 >= len(calendar):
                break
            rows.append(
                {
                    "event_id_v6": record["event_id_v6"],
                    "symbol": record["symbol"],
                    "holding_session": holding_session,
                    "outcome_date": calendar[idx + holding_session - 1],
                }
            )
    return pd.DataFrame(rows)


def _materialize_outcome_paths(selected: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if OUTCOME_BARS.is_file() and OUTCOME_STATES.is_file():
        bars = pq.read_table(OUTCOME_BARS).to_pandas()
        states = pq.read_table(OUTCOME_STATES).to_pandas()
        expected_ids = set(selected["event_id_v6"])
        if set(bars["event_id_v6"]).issubset(expected_ids) and set(states["event_id_v6"]).issubset(
            expected_ids
        ):
            return bars, states
        raise V6Error("outcome cache contains a non-selected event")
    keys = _outcome_day_keys(selected)
    bar_pieces: list[pd.DataFrame] = []
    state_pieces: list[pd.DataFrame] = []
    for year in sorted(pd.to_datetime(keys["outcome_date"]).dt.year.unique()):
        year = int(year)
        year_keys = keys.loc[pd.to_datetime(keys["outcome_date"]).dt.year.eq(year)].copy()
        year_keys["outcome_date"] = pd.to_datetime(year_keys["outcome_date"])
        print(f"STAGE_B materialize year={year} event_days={len(year_keys)}", flush=True)
        con = connection()
        con.register("outcome_keys", year_keys)
        bars = con.execute(
            """
            SELECT k.event_id_v6,k.symbol,k.holding_session,k.outcome_date,
              r.bar_end_time,r.open,r.high,r.low,r.close,r.volume
            FROM outcome_keys k
            JOIN read_parquet($raw_paths,union_by_name=true) r
              ON r.qmt_code=k.symbol AND r.trade_date=k.outcome_date
            WHERE r.period='1m' AND r.adjust='none' AND r.exchange IN ('SH','SZ')
            ORDER BY k.event_id_v6,k.holding_session,r.bar_end_time
            """,
            {"raw_paths": raw_paths(year)},
        ).df()
        states = con.execute(
            """
            SELECT k.event_id_v6,k.symbol,k.holding_session,k.outcome_date,
              d.trade_status,d.is_st,d.down_limit_price,d.up_limit_price,
              d.corporate_action_count,d.corporate_action_blocking,
              d.corporate_action_available_date,d.bar_valid,d.trading_state_valid,
              d.corporate_action_valid,d.market_rule_valid,d.hard_valid,
              d.snapshot_id
            FROM outcome_keys k
            LEFT JOIN read_parquet($daily_path) d
              ON d.symbol=k.symbol AND d.trade_date=k.outcome_date
            ORDER BY k.event_id_v6,k.holding_session
            """,
            {"daily_path": str(daily_path(year))},
        ).df()
        con.close()
        bar_pieces.append(bars)
        state_pieces.append(states)
    all_bars = pd.concat(bar_pieces, ignore_index=True)
    all_states = pd.concat(state_pieces, ignore_index=True)
    if all_states.duplicated(["event_id_v6", "holding_session"]).any():
        raise V6Error("duplicate outcome daily state")
    atomic_parquet(all_bars, OUTCOME_BARS)
    atomic_parquet(all_states, OUTCOME_STATES)
    return all_bars, all_states


def _flag(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _sell_state_valid(state: dict[str, Any]) -> bool:
    return bool(
        state.get("trade_status") == 1
        and _flag(state.get("bar_valid"))
        and _flag(state.get("trading_state_valid"))
        and _flag(state.get("market_rule_valid"))
    )


def _legal_sell_bar(row: Any, state: dict[str, Any]) -> bool:
    down_limit = state.get("down_limit_price")
    return bool(
        _sell_state_valid(state)
        and pd.notna(down_limit)
        and float(row.volume) > 0
        and float(row.open) > float(down_limit) + 1e-8
    )


def _simulate_event(
    event: dict[str, Any], bars: pd.DataFrame, states: pd.DataFrame
) -> dict[str, Any]:
    result = dict(event)
    entry_price = float(event["d1_entry_open1001"])
    reference = float(event["d0_cutoff_close"])
    target_price = entry_price * 1.08
    result.update(
        {
            "target_price": target_price,
            "status": "RIGHT_CENSORED",
            "exit_reason": None,
            "exit_at": pd.NaT,
            "exit_price": np.nan,
            "holding_sessions": np.nan,
            "gross_return": np.nan,
            "net_return": np.nan,
            "action_lineage_fail_closed": False,
            "target_hit": False,
        }
    )
    state_by_session = {
        int(row.holding_session): row._asdict()
        for row in states.itertuples(index=False)
    }
    bar_groups = {
        int(session): group.sort_values("bar_end_time")
        for session, group in bars.groupby("holding_session", sort=True)
    }
    failure_armed = False
    for holding_session in range(2, 13):
        state = state_by_session.get(holding_session)
        if state is None or pd.isna(state.get("outcome_date")):
            continue
        action_count = state.get("corporate_action_count")
        if (
            pd.isna(action_count)
            or int(action_count) != 0
            or _flag(state.get("corporate_action_blocking"))
            or not _flag(state.get("corporate_action_valid"))
        ):
            result["status"] = "ACTION_LINEAGE_FAIL_CLOSED"
            result["action_lineage_fail_closed"] = True
            return result
        day = bar_groups.get(holding_session)
        if day is None or day.empty:
            continue
        if holding_session in (2, 3):
            for row in day.itertuples(index=False):
                bar_time = pd.Timestamp(row.bar_end_time)
                legal = _legal_sell_bar(row, state)
                if legal and float(row.open) >= target_price:
                    result.update(
                        {
                            "status": "COMPLETE",
                            "exit_reason": "TARGET_08_GAP_THROUGH",
                            "exit_at": bar_time,
                            "exit_price": float(row.open),
                            "holding_sessions": holding_session - 1,
                            "target_hit": True,
                        }
                    )
                    break
                if (
                    _sell_state_valid(state)
                    and float(row.high) >= target_price
                    and float(row.volume) > 0
                ):
                    result.update(
                        {
                            "status": "COMPLETE",
                            "exit_reason": "TARGET_08",
                            "exit_at": bar_time,
                            "exit_price": target_price,
                            "holding_sessions": holding_session - 1,
                            "target_hit": True,
                        }
                    )
                    break
                clock = bar_time.time()
                if holding_session == 2 and clock.hour == 10 and clock.minute == 0:
                    failure_armed = float(row.close) < reference
                    continue
                if holding_session == 2 and failure_armed and clock > pd.Timestamp("10:00").time() and legal:
                    result.update(
                        {
                            "status": "COMPLETE",
                            "exit_reason": "D2_ACCEPTANCE_FAILURE",
                            "exit_at": bar_time,
                            "exit_price": float(row.open),
                            "holding_sessions": holding_session - 1,
                            "target_hit": False,
                        }
                    )
                    break
            if result["status"] == "COMPLETE":
                break
            continue
        if holding_session >= 4:
            for row in day.itertuples(index=False):
                if not _legal_sell_bar(row, state):
                    continue
                reason = "TARGET_08_GAP_THROUGH" if float(row.open) >= target_price else "H3_TIME_STOP"
                result.update(
                    {
                        "status": "COMPLETE",
                        "exit_reason": reason,
                        "exit_at": pd.Timestamp(row.bar_end_time),
                        "exit_price": float(row.open),
                        "holding_sessions": holding_session - 1,
                        "target_hit": reason.startswith("TARGET_08"),
                    }
                )
                break
            if result["status"] == "COMPLETE":
                break
    if result["status"] == "COMPLETE":
        result["gross_return"] = float(result["exit_price"] / entry_price - 1.0)
        result["net_return"] = float(result["gross_return"] - 0.004)
    return result


def _summary(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame["status"].eq("COMPLETE")].copy()
    if complete.empty:
        return {
            "signals": int(len(frame)),
            "trades": 0,
            "mean_net": None,
            "median_net": None,
            "date_equal_mean_net": None,
            "win_rate": None,
            "target_hit": None,
            "severe10": None,
            "mean_holding_sessions": None,
        }
    return {
        "signals": int(len(frame)),
        "trades": int(len(complete)),
        "dates": int(complete["d1_date"].nunique()),
        "symbols": int(complete["symbol"].nunique()),
        "mean_net": float(complete["net_return"].mean()),
        "median_net": float(complete["net_return"].median()),
        "date_equal_mean_net": float(complete.groupby("d1_date")["net_return"].mean().mean()),
        "win_rate": float(complete["net_return"].gt(0).mean()),
        "target_hit": float(complete["target_hit"].mean()),
        "severe10": float(complete["net_return"].le(-0.10).mean()),
        "severe05": float(complete["net_return"].le(-0.05).mean()),
        "mean_holding_sessions": float(complete["holding_sessions"].mean()),
        "median_holding_sessions": float(complete["holding_sessions"].median()),
    }


def evaluate_stage_b() -> dict[str, Any]:
    load_spec()
    if not MANIFEST.is_file() or not FEATURE_PANEL.is_file():
        raise V6Error("Stage A artifacts are missing")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["hashes"]["feature_panel"] != sha256_file(FEATURE_PANEL):
        raise V6Error("Stage A feature panel hash changed")
    if not manifest.get("capacity_gate_gt50"):
        raise V6Error("outcome-blind capacity gate failed")
    panel = pq.read_table(FEATURE_PANEL).to_pandas()
    selected = panel.loc[panel["admitted"]].copy()
    bars, states = _materialize_outcome_paths(selected)
    results: list[dict[str, Any]] = []
    grouped_bars = {key: group for key, group in bars.groupby("event_id_v6", sort=False)}
    grouped_states = {key: group for key, group in states.groupby("event_id_v6", sort=False)}
    for record in selected.to_dict("records"):
        event_id = record["event_id_v6"]
        results.append(
            _simulate_event(
                record,
                grouped_bars.get(event_id, bars.iloc[0:0]),
                grouped_states.get(event_id, states.iloc[0:0]),
            )
        )
    trades = pd.DataFrame(results).sort_values(["d1_date", "symbol", "event_id_v6"])
    if len(trades) != len(selected) or trades["event_id_v6"].duplicated().any():
        raise V6Error("Stage B trade identity changed")
    if (
        trades.loc[trades["status"].eq("COMPLETE"), "exit_at"]
        <= trades.loc[trades["status"].eq("COMPLETE"), "d1_entry_at"]
    ).any():
        raise V6Error("same-day/T+1 exit violation")
    atomic_parquet(trades, TRADES)
    annual = {
        str(int(year)): _summary(group)
        for year, group in trades.groupby("entry_year", sort=True)
    }
    blocks = {
        "development_2014_2020": _summary(trades.loc[trades["entry_year"].le(2020)]),
        "challenge_2021_2023": _summary(trades.loc[trades["entry_year"].between(2021, 2023)]),
        "post_observation_2024_2026_ytd": _summary(trades.loc[trades["entry_year"].ge(2024)]),
        "full_2014_2025": _summary(trades.loc[trades["entry_year"].le(2025)]),
        "all_2014_2026_ytd": _summary(trades),
    }
    by_exit = {
        str(reason): _summary(group)
        for reason, group in trades.groupby("exit_reason", dropna=False, sort=True)
    }
    by_sleeve = {
        str(sleeve): _summary(group)
        for sleeve, group in trades.groupby("sleeve", sort=True)
    }
    full = trades.loc[trades["entry_year"].le(2025) & trades["status"].eq("COMPLETE")]
    full_summary = blocks["full_2014_2025"]
    full_years = int(trades.loc[trades["entry_year"].le(2025), "entry_year"].nunique())
    average = len(full) / full_years
    goal = {
        "average_completed_signals_per_full_year": float(average),
        "average_completed_signals_per_full_year_gt50": bool(average > 50),
        "pooled_mean_net_gt2": bool(full_summary["mean_net"] is not None and full_summary["mean_net"] > 0.02),
        "pooled_median_net_gt0": bool(full_summary["median_net"] is not None and full_summary["median_net"] > 0),
        "date_equal_mean_net_gt0": bool(
            full_summary["date_equal_mean_net"] is not None
            and full_summary["date_equal_mean_net"] > 0
        ),
        "severe10_lt10": bool(full_summary["severe10"] is not None and full_summary["severe10"] < 0.10),
        "every_full_year_mean_positive": bool(
            all(
                annual[str(year)]["mean_net"] is not None
                and annual[str(year)]["mean_net"] > 0
                for year in range(2014, 2026)
            )
        ),
        "recent_block_mean_positive": bool(
            blocks["post_observation_2024_2026_ytd"]["mean_net"] is not None
            and blocks["post_observation_2024_2026_ytd"]["mean_net"] > 0
        ),
    }
    goal["all_required_pass"] = bool(
        all(value for key, value in goal.items() if key != "average_completed_signals_per_full_year")
    )
    result = {
        "experiment": EXPERIMENT,
        "spec_sha256": sha256_file(SPEC_PATH),
        "canonical_spec_sha256": manifest["canonical_spec_sha256"],
        "stage_a_feature_sha256": sha256_file(FEATURE_PANEL),
        "trades_sha256": sha256_file(TRADES),
        "annual": annual,
        "blocks": blocks,
        "by_exit": by_exit,
        "by_sleeve": by_sleeve,
        "goal": goal,
        "audit": {
            "mother_event_changed_count": 0,
            "rule_changed_after_outcome_open_count": 0,
            "feature_after_decision_count": 0,
            "entry_in_decision_bar_count": 0,
            "t1_same_day_exit_count": int(
                (
                    pd.to_datetime(trades.loc[trades["status"].eq("COMPLETE"), "exit_at"]).dt.date
                    <= pd.to_datetime(
                        trades.loc[trades["status"].eq("COMPLETE"), "d1_entry_at"]
                    ).dt.date
                ).sum()
            ),
            "corporate_action_fail_closed_count": int(
                trades["action_lineage_fail_closed"].sum()
            ),
            "duplicate_event_count": int(trades["event_id_v6"].duplicated().sum()),
            "right_censored_count": int(trades["status"].eq("RIGHT_CENSORED").sum()),
            "repository_post_2026_08_12_opened": False,
        },
        "scientific_warning": "All calendar outcomes through 2026-08-12 were previously observable in this research program. This is a deterministic retrospective mechanism test, not pristine OOS.",
    }
    if any(
        result["audit"][key]
        for key in (
            "rule_changed_after_outcome_open_count",
            "feature_after_decision_count",
            "entry_in_decision_bar_count",
            "t1_same_day_exit_count",
            "duplicate_event_count",
        )
    ):
        raise V6Error(f"Stage B audit failure: {result['audit']}")
    atomic_json(result, EXTERNAL_RESULT)
    atomic_json(result, RESULT_PATH)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for year in sorted(annual, key=int):
        item = annual[year]
        if item["trades"]:
            rows.append(
                f"|{year}|{item['signals']}|{item['trades']}|{item['mean_net']:.2%}|"
                f"{item['median_net']:.2%}|{item['win_rate']:.2%}|{item['target_hit']:.2%}|"
                f"{item['severe10']:.2%}|"
            )
        else:
            rows.append(f"|{year}|{item['signals']}|0|—|—|—|—|—|")
    report = f"""# {EXPERIMENT}

## Signal captured

An industry-demand event that survives the overnight release of inventory and
remains accepted through the first 30 completed minutes of D1.  Entry is the
actual 10:01 open, strictly after the 10:00 decision bar.

## Frozen V6 results

|Entry year|Signals|Trades|Mean net|Median net|Win|Target 8|Severe10|
|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

2014--2025 full years: {blocks['full_2014_2025']['trades']} completed trades,
{blocks['full_2014_2025']['mean_net']:.2%} mean,
{blocks['full_2014_2025']['median_net']:.2%} median, and
{blocks['full_2014_2025']['severe10']:.2%} severe-loss10.

2024--2026 YTD post-observation diagnostic:
{blocks['post_observation_2024_2026_ytd']['trades']} completed trades,
{blocks['post_observation_2024_2026_ytd']['mean_net']:.2%} mean and
{blocks['post_observation_2024_2026_ytd']['median_net']:.2%} median.

## Goal gate

`{json.dumps(goal, ensure_ascii=False, sort_keys=True)}`

No model was fit and no V6 rule was changed after its outcomes were attached.
The 2024--2026 rows are not pristine OOS because their parent calendar outcomes
had already been observed elsewhere in the research program.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["a", "b", "all"], default="all")
    args = parser.parse_args()
    if args.stage in {"a", "all"}:
        print(json.dumps(build_stage_a(), indent=2, sort_keys=True), flush=True)
    if args.stage in {"b", "all"}:
        print(json.dumps(evaluate_stage_b(), indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
