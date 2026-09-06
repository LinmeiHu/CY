#!/usr/bin/env python3
"""Frozen 2022-2024 validation for quiet-inventory fast repricing V1.

The contract hash below was fixed before any validation outcome was read. 2022
and 2023 candidate identity and market state come from frozen Stage-A assets.
The 2024 candidates and market state are rebuilt from the exact PIT daily asset
with the same causal windows and upstream universe. Signals fill no earlier than
the next legal open; limits, suspensions and coordinate lineage fail closed.
"""

from __future__ import annotations

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
EXPERIMENT = "ASHARE-QUIET-INVENTORY-FAST-REPRICING-V1"
FREEZE = ROOT / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "aa3ce0369a6e36f43f4d6bd599bb02b37f33076d775a685033ebd4fbab8200ab"

FEATURES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_information_repricing_long_translation_v2/"
    "stage_a/candidates_features_2014_2023_frozen.parquet"
)
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "pit_daily_qd010_exact_2022_2026q1.parquet"
)

OUTPUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_fast_repricing_v1/validation_2022_2024"
)
CANDIDATES = OUTPUT / "frozen_validation_candidates.parquet"
OUTCOMES = OUTPUT / "frozen_validation_outcomes.parquet"
MARKET_2024 = OUTPUT / "causal_market_regime_2024.parquet"
IDENTITY_AUDIT = OUTPUT / "pre_outcome_identity_audit.json"
RESULT = OUTPUT / "result.json"

VALIDATION_SIGNAL_YEARS = (2022, 2023, 2024)
OUTCOME_DATA_END = pd.Timestamp("2025-03-31")
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


class ValidationError(RuntimeError):
    """Fail-closed validation error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
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


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        temporary,
        compression="zstd",
    )
    os.replace(temporary, path)


def quoted_industries() -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in EXCLUDED_INDUSTRIES)


def connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads=8")
    con.execute("SET memory_limit='12GB'")
    return con


def feature_ctes() -> str:
    excluded = quoted_industries()
    return f"""
    WITH source AS (
      SELECT *
      FROM read_parquet('{DAILY.as_posix()}')
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '2024-12-31'
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
        count(*) OVER(
          PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS prior60_n,
        bool_and(history_valid) OVER(
          PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS prior60_valid,
        max(coord_high) OVER(
          PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 40 PRECEDING AND 1 PRECEDING
        ) AS platform_high,
        min(coord_low) OVER(
          PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 40 PRECEDING AND 1 PRECEDING
        ) AS platform_low,
        avg(turnover_fraction) OVER(
          PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_to20,
        avg(turnover_fraction) OVER(
          PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 60 PRECEDING AND 21 PRECEDING
        ) AS avg_to_old
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
        sum(CASE WHEN step_return>=0.05 THEN 1 ELSE 0 END) OVER(
          PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 120 PRECEDING AND CURRENT ROW
        ) AS large_up_days120,
        platform_high/nullif(platform_low,0)-1 AS platform_width,
        avg_to20/nullif(avg_to_old,0) AS turnover_contraction,
        coord_open/nullif(lag1_close,0)-1 AS open_gap,
        turnover_fraction/nullif(avg_to20,0) AS turnover_expansion,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location
      FROM window_two
    )
    """


def mother_condition() -> str:
    return """
      NOT is_st
      AND current_valid
      AND prior60_n=60
      AND prior60_valid
      AND lag60_invalid_step_cum=invalid_step_cum
      AND platform_width<=0.30
      AND avg_to20<=avg_to_old
      AND open_gap BETWEEN 0.01 AND 0.08
      AND coord_close>platform_high
      AND turnover_expansion>=1.50
      AND close_location>=0.70
      AND round(close*100)<round(up_limit_price*100)
    """


def build_2024_market(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    query = feature_ctes() + """
    SELECT
      CAST(trade_date AS DATE) AS trade_date,
      median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
        AS market_median_ret20,
      avg((ret20>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
        AS market_positive_ret20_share,
      median(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
        AS market_median_ret60,
      avg((ret60>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
        AS market_positive_ret60_share,
      count(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL) AS n20,
      count(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL) AS n60,
      max(available_at) FILTER(WHERE current_valid AND NOT is_st) AS latest_source_timestamp,
      CASE
        WHEN market_median_ret20>0 AND market_positive_ret20_share>0.50
         AND market_median_ret60>0 AND market_positive_ret60_share>0.50 THEN 'BULL'
        WHEN market_median_ret20<=0 AND market_positive_ret20_share<=0.50
         AND market_median_ret60<=0 AND market_positive_ret60_share<=0.50 THEN 'BEAR'
        ELSE 'TRANSITION'
      END AS market_regime
    FROM featured
    WHERE year(trade_date)=2024
    GROUP BY trade_date
    ORDER BY trade_date
    """
    frame = con.execute(query).fetchdf()
    if len(frame) != 242:
        raise ValidationError(f"unexpected 2024 market-session count: {len(frame)}")
    return frame


def identity_audit(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE rebuilt_mother_2023 AS "
        + feature_ctes()
        + f"""
        SELECT symbol,CAST(trade_date AS DATE) AS signal_date
        FROM featured
        WHERE year(trade_date)=2023 AND {mother_condition()}
        """
    )
    comparison = con.execute(
        f"""
        WITH frozen AS (
          SELECT symbol,CAST(signal_date AS DATE) AS signal_date
          FROM read_parquet('{FEATURES.as_posix()}')
          WHERE year(signal_date)=2023
        ), rebuilt_only AS (
          SELECT * FROM rebuilt_mother_2023 EXCEPT SELECT * FROM frozen
        ), frozen_only AS (
          SELECT * FROM frozen EXCEPT SELECT * FROM rebuilt_mother_2023
        )
        SELECT
          (SELECT count(*) FROM frozen) AS frozen_count,
          (SELECT count(*) FROM rebuilt_mother_2023) AS rebuilt_count,
          (SELECT count(*) FROM rebuilt_only) AS rebuilt_only,
          (SELECT count(*) FROM frozen_only) AS frozen_only
        """
    ).fetchone()
    frozen_only_rows = con.execute(
        f"""
        SELECT f.symbol,CAST(f.signal_date AS DATE) AS signal_date,
          f.coord_close-f.platform_high AS frozen_close_minus_high
        FROM read_parquet('{FEATURES.as_posix()}') f
        WHERE year(f.signal_date)=2023
          AND (f.symbol,CAST(f.signal_date AS DATE)) NOT IN (
            SELECT symbol,signal_date FROM rebuilt_mother_2023
          )
        ORDER BY signal_date,symbol
        """
    ).fetchdf()
    audit = {
        "frozen_2023_count": comparison[0],
        "rebuilt_2023_count": comparison[1],
        "rebuilt_only": comparison[2],
        "frozen_only": comparison[3],
        "frozen_only_rows": frozen_only_rows.to_dict("records"),
        "interpretation": (
            "The two misses are equality-at-tick cases admitted by a 4.44e-16 coordinate "
            "arithmetic difference in the older frozen asset. The one extra is an exact "
            "1% opening-gap boundary represented 8.67e-18 above the threshold in the newer "
            "asset. Literal frozen comparisons remain unchanged and no tolerance is added."
        ),
        "validation_outcomes_read": False,
    }
    if comparison[2] != 1 or comparison[3] != 2:
        raise ValidationError(f"unexpected mother-identity audit: {audit}")
    return audit


def build_candidates(con: duckdb.DuckDBPyConnection, market_2024: pd.DataFrame) -> pd.DataFrame:
    con.register("market_2024_frame", market_2024)
    historical = con.execute(
        f"""
        SELECT
          f.event_id,f.symbol,f.sleeve,CAST(f.signal_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,f.invalid_step_cum AS signal_invalid_step_cum,
          f.large_up_days120,f.platform_width,f.turnover_contraction,
          f.open_gap,f.turnover_expansion,f.close_location,f.causal_industry,
          r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
          r.market_median_ret60,r.market_positive_ret60_share,
          'FROZEN_2022_2023_IDENTITY' AS candidate_source
        FROM read_parquet('{FEATURES.as_posix()}') f
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON CAST(f.signal_date AS DATE)=r.trade_date
        WHERE year(f.signal_date) IN (2022,2023)
          AND r.market_regime='BULL'
          AND r.market_median_ret60 BETWEEN 0.025 AND 0.18
          AND f.large_up_days120<=9
        ORDER BY signal_date,f.symbol
        """
    ).fetchdf()
    current = con.execute(
        feature_ctes()
        + f"""
        SELECT
          '{EXPERIMENT}|' || f.symbol || '|' || strftime(f.trade_date,'%Y-%m-%d') AS event_id,
          f.symbol,f.sleeve,CAST(f.trade_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,f.invalid_step_cum AS signal_invalid_step_cum,
          f.large_up_days120,f.platform_width,f.turnover_contraction,
          f.open_gap,f.turnover_expansion,f.close_location,f.causal_industry,
          m.market_regime,m.market_median_ret20,m.market_positive_ret20_share,
          m.market_median_ret60,m.market_positive_ret60_share,
          'EXACT_PIT_2024_REBUILD' AS candidate_source
        FROM featured f
        JOIN market_2024_frame m ON CAST(f.trade_date AS DATE)=m.trade_date
        WHERE year(f.trade_date)=2024
          AND {mother_condition()}
          AND m.market_regime='BULL'
          AND m.market_median_ret60 BETWEEN 0.025 AND 0.18
          AND f.large_up_days120<=9
        ORDER BY signal_date,f.symbol
        """
    ).fetchdf()
    frame = pd.concat([historical, current], ignore_index=True)
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    frame = frame.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
    if frame.event_id.duplicated().any():
        raise ValidationError("duplicate validation event_id")
    if set(frame.signal_date.dt.year.unique()) - set(VALIDATION_SIGNAL_YEARS):
        raise ValidationError("candidate outside validation signal years")
    required = (
        "event_id",
        "symbol",
        "signal_date",
        "signal_cal_idx",
        "signal_invalid_step_cum",
        "market_median_ret60",
        "large_up_days120",
    )
    if frame[list(required)].isna().any().any():
        raise ValidationError("unknown required candidate lineage")
    return frame.reset_index(drop=True)


def legal_state(row: pd.Series) -> bool:
    required = (
        "trade_status",
        "current_day_data_tradable",
        "market_rule_valid",
        "corporate_action_valid",
        "corporate_action_blocking",
        "hard_valid",
    )
    if any(pd.isna(row.get(field)) for field in required):
        return False
    return bool(
        int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
    )


def buyable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    if not legal_state(row) or not all(np.isfinite(float(value)) for value in values):
        return False
    return bool(
        float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    if not legal_state(row) or not all(np.isfinite(float(value)) for value in values):
        return False
    return bool(
        float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def replay_one(candidate: pd.Series, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    signal_invalid = float(candidate.signal_invalid_step_cum)
    base = {
        "event_id": candidate.event_id,
        "symbol": candidate.symbol,
        "sleeve": candidate.sleeve,
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "candidate_source": candidate.candidate_source,
    }
    if path.empty:
        return {**base, "status": "NO_FUTURE_PATH_THROUGH_2025_03_31"}
    entry_pool = path.loc[path.cal_idx.le(signal_idx + 3)]
    entry_pool = entry_pool.loc[entry_pool.invalid_step_cum.eq(signal_invalid)]
    entry_row = next((row for _, row in entry_pool.iterrows() if buyable_open(row)), None)
    if entry_row is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}

    entry_idx = int(entry_row.cal_idx)
    entry_price = float(entry_row.coord_open)
    target_price = entry_price * 1.10
    pending_reason: str | None = None
    decision_idx: int | None = None
    exit_payload: dict[str, Any] | None = None
    censored = False

    future = path.loc[path.cal_idx.gt(entry_idx)].sort_values("cal_idx")
    for _, row in future.iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != signal_invalid:
            censored = True
            break
        if pending_reason is not None and sellable_open(row):
            exit_payload = {
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": float(row.coord_open),
                "exit_reason": pending_reason,
                "exit_decision_cal_idx": decision_idx,
            }
            break
        if legal_state(row) and np.isfinite(float(row.coord_high)) and float(row.coord_high) >= target_price:
            exit_payload = {
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": target_price,
                "exit_reason": "TARGET_10",
                "exit_decision_cal_idx": entry_idx,
            }
            break
        if legal_state(row) and np.isfinite(float(row.coord_close)) and int(row.cal_idx) >= entry_idx + 20:
            pending_reason = "H20_TIME_STOP"
            decision_idx = int(row.cal_idx)

    entry = {
        "entry_date": pd.Timestamp(entry_row.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if censored:
        return {**base, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY", **entry}
    if exit_payload is None:
        return {**base, "status": "INCOMPLETE_BY_2025_03_31", **entry}

    gross = float(exit_payload["exit_price"]) / entry_price - 1.0
    result = {
        **base,
        "status": "COMPLETED",
        **entry,
        **exit_payload,
        "holding_sessions": int(exit_payload["exit_cal_idx"]) - entry_idx,
        "gross_return": gross,
        "net_return": gross - 0.004,
    }
    if result["entry_cal_idx"] <= result["signal_cal_idx"]:
        raise ValidationError("same-bar or pre-signal fill")
    if result["exit_cal_idx"] <= result["entry_cal_idx"]:
        raise ValidationError("non-positive holding interval")
    return result


def replay(con: duckdb.DuckDBPyConnection, candidates: pd.DataFrame) -> pd.DataFrame:
    con.register("validation_candidates", candidates)
    path = con.execute(
        f"""
        SELECT
          c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price
        FROM validation_candidates c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
        WHERE d.trade_date<=DATE '{OUTCOME_DATA_END:%Y-%m-%d}'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetchdf()
    groups = {event_id: part for event_id, part in path.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, groups.get(candidate.event_id, pd.DataFrame()))
        for _, candidate in candidates.iterrows()
    ]
    frame = pd.DataFrame(rows)
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    for column in ("entry_date", "exit_date"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort").reset_index(drop=True)


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    returns = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": int(len(frame)),
        "completed_trades": int(len(completed)),
        "completion_rate": None if frame.empty else float(len(completed) / len(frame)),
        "mean_net_return": None if completed.empty else float(returns.mean()),
        "median_net_return": None if completed.empty else float(returns.median()),
        "win_rate": None if completed.empty else float(returns.gt(0).mean()),
        "target_hit_rate": None if completed.empty else float(completed.exit_reason.eq("TARGET_10").mean()),
        "severe_loss_10pct_rate": None if completed.empty else float(returns.le(-0.10).mean()),
        "mean_holding_sessions": None if completed.empty else float(completed.holding_sessions.mean()),
        "status_counts": frame.status.value_counts(dropna=False).to_dict(),
    }


def run() -> dict[str, Any]:
    for path in (FREEZE, FEATURES, REGIME, DAILY):
        if not path.is_file():
            raise ValidationError(f"missing required input: {path}")
    freeze_hash = sha256(FREEZE)
    if freeze_hash != EXPECTED_FREEZE_SHA256:
        raise ValidationError(f"freeze hash changed: {freeze_hash}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    con = connection()
    audit = identity_audit(con)
    atomic_json(IDENTITY_AUDIT, audit)
    market_2024 = build_2024_market(con)
    candidates = build_candidates(con, market_2024)
    atomic_parquet(market_2024, MARKET_2024)
    atomic_parquet(candidates, CANDIDATES)
    outcomes = replay(con, candidates)
    con.close()
    atomic_parquet(outcomes, OUTCOMES)

    annual = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in VALIDATION_SIGNAL_YEARS
    }
    pooled = metrics(outcomes)
    mean_signals_per_year = float(len(outcomes) / len(VALIDATION_SIGNAL_YEARS))
    completed_per_year = float(
        outcomes.status.eq("COMPLETED").sum() / len(VALIDATION_SIGNAL_YEARS)
    )
    result = {
        "experiment": EXPERIMENT,
        "status": "FROZEN_VALIDATION_COMPLETE",
        "freeze_sha256": freeze_hash,
        "chronology": {
            "development_signal_end": "2021-12-31",
            "validation_signal_years": list(VALIDATION_SIGNAL_YEARS),
            "outcome_tail_end_for_late_2024_signals": str(OUTCOME_DATA_END.date()),
            "threshold_changes_after_validation_open": False,
        },
        "pre_outcome_identity_audit": audit,
        "pooled": pooled,
        "annual": annual,
        "mean_signals_per_year": mean_signals_per_year,
        "mean_completed_trades_per_year": completed_per_year,
        "user_gates_on_frozen_validation": {
            "mean_signals_per_year_strictly_above_50": mean_signals_per_year > 50,
            "mean_net_return_at_least_4pct": (
                pooled["mean_net_return"] is not None and pooled["mean_net_return"] >= 0.04
            ),
            "mean_holding_sessions_strictly_below_15": (
                pooled["mean_holding_sessions"] is not None
                and pooled["mean_holding_sessions"] < 15
            ),
        },
        "input_hashes_sha256": {
            "freeze": freeze_hash,
            "frozen_candidate_features": sha256(FEATURES),
            "frozen_market_regime": sha256(REGIME),
            "exact_daily_2022_2026q1": sha256(DAILY),
        },
        "output_hashes_sha256": {
            "candidates": sha256(CANDIDATES),
            "outcomes": sha256(OUTCOMES),
            "market_2024": sha256(MARKET_2024),
            "identity_audit": sha256(IDENTITY_AUDIT),
        },
    }
    atomic_json(RESULT, result)
    return result


if __name__ == "__main__":
    print(json.dumps(json_ready(run()), ensure_ascii=False, indent=2))
