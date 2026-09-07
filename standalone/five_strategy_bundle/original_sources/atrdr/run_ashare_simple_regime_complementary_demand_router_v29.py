#!/usr/bin/env python3
"""Five-group bull-mechanism distillation plus unchanged V27 Bear routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_causal_regime_complementary_mechanism_router_v28 as v28  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-SIMPLE-REGIME-COMPLEMENTARY-DEMAND-ROUTER-V29"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
FREEZE = OS_ROOT / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

EXT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_simple_regime_complementary_demand_router_v29"
)
RAW_CANDIDATES = EXT / "stage_a/raw_simple_bull_candidates.parquet"
CANDIDATES = EXT / "stage_a/simple_bull_candidates.parquet"
OUTCOME_SHARDS = EXT / "stage_b/outcome_shards"
OUTCOMES = EXT / "stage_b/simple_bull_outcomes.parquet"
SOURCE_UNION = EXT / "stage_b/source_completed_trades.parquet"
DAILY_PATHS = EXT / "stage_b/daily_paths.parquet"
ACCEPTED = EXT / "stage_b/accepted_trades.parquet"
SKIPPED = EXT / "stage_b/capacity_skips.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

DAILY_HIST = v28.DAILY_HIST
DAILY_POST = v28.DAILY_POST_COMPACT
V28_FROZEN_SOURCE = v28.SOURCE_UNION
DATA_END = pd.Timestamp("2026-09-04")
FULL_YEARS = tuple(range(2014, 2026))
TARGET = 0.15
HORIZON = 15
ENTRY_COST = 0.002
EXIT_COST = 0.002
BATCH_SYMBOLS = 160

EXPECTED = {
    "daily_hist": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "daily_post": "0ed55ccef40815ab057fdc500ce73af69bf4a71878fabf7a6895c98192c715af",
    "v28_runner": "46a5ad7bdc2f6114487969d4124e4496bba15b9937e983f7dc43dfe3dcf4b0d0",
    "v28_frozen_source": "f3cb511657745245a5c62c8cc5c264f56c2faa97096b39cd470d79271d929841",
}


class ResearchError(RuntimeError):
    """Fail closed on causal, identity, execution, or lineage drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ids_sha256(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def connection() -> duckdb.DuckDBPyConnection:
    temp = EXT / "duckdb_tmp"
    temp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temp.as_posix()}'")
    return con


def verify_static_inputs() -> dict[str, str]:
    observed = {
        "daily_hist": sha256(DAILY_HIST),
        "daily_post": sha256(DAILY_POST),
        "v28_runner": sha256(Path(v28.__file__)),
        "v28_frozen_source": sha256(V28_FROZEN_SOURCE),
    }
    drift = {key: [EXPECTED[key], value] for key, value in observed.items() if value != EXPECTED[key]}
    if drift:
        raise ResearchError(f"static input drift: {drift}")
    # Verify the exact source definitions even though the immutable trade rows
    # are consumed from the V28 Stage-A copy rather than a rewritten Parquet.
    source_blobs = {
        "v27_runner": v28.bytes_sha256(
            v28.git_blob(
                v28.V27_COMMIT,
                "research/market_behavior_os_v2/scripts/"
                "run_ashare_causal_market_regime_substrategy_router_v27.py",
            )
        ),
        "v27_contract": v28.bytes_sha256(
            v28.git_blob(
                v28.V27_COMMIT,
                "research/market_behavior_os_v2/experiments/"
                "ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-V27_contract.json",
            )
        ),
    }
    if source_blobs != {
        "v27_runner": "e44b83efff24356a328d485b0d54623578cfb74a63e495e6a3fef976e219c05a",
        "v27_contract": "8fdaf43e7d0f44cb5607fb1a37d4a12fefbf43cb1ededf334bc5bf474f0a20a7",
    }:
        raise ResearchError(f"V27 source Git blob drift: {source_blobs}")
    return {**observed, **{f"git_blob:{key}": value for key, value in source_blobs.items()}}


def feature_sql() -> str:
    fields = """
      CAST(trade_date AS DATE) AS trade_date, cal_idx, symbol, sleeve,
      open, high, low, close, volume, amount, turnover_fraction, is_st,
      causal_industry, trade_status, current_day_data_tradable,
      up_limit_price, down_limit_price, market_rule_valid,
      corporate_action_count, corporate_action_valid, corporate_action_blocking,
      industry_valid, historical_identity_valid, hard_valid,
      available_at, decision_at, history_valid, current_valid,
      invalid_step_cum, coordinate_factor,
      coord_open, coord_high, coord_low, coord_close, prior_coord_close
    """
    return f"""
    WITH d AS (
      SELECT {fields} FROM read_parquet('{DAILY_HIST.as_posix()}')
      WHERE trade_date<=DATE '2023-12-31'
      UNION ALL BY NAME
      SELECT {fields} FROM read_parquet('{DAILY_POST.as_posix()}')
      WHERE trade_date>=DATE '2024-01-01'
    ), a0 AS (
      SELECT *,
        lag(coord_close,20) OVER w AS lag20_close_exact,
        lag(coord_close,60) OVER w AS lag60_close_exact
      FROM d
      WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
    ), v0 AS (
      SELECT *,
        max(coord_high) OVER w20 AS prior20_high,
        avg(turnover_fraction) OVER w20 AS prior20_turnover,
        sum((round(close*100)=round(up_limit_price*100))::INTEGER)
          OVER w20 AS prior20_limitups
      FROM a0
      WHERE current_valid
      WINDOW w20 AS (
        PARTITION BY symbol ORDER BY trade_date
        ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      )
    ), base AS (
      SELECT *,
        coord_close/nullif(lag20_close_exact,0)-1 AS ret20,
        coord_close/nullif(lag60_close_exact,0)-1 AS ret60,
        coord_close/nullif(prior_coord_close,0)-1 AS step_return,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location,
        turnover_fraction/nullif(prior20_turnover,0) AS turnover_ratio
      FROM v0
      WHERE hard_valid AND NOT is_st
    ), market_state AS (
      SELECT trade_date,
        count(*) AS market_n,
        avg((ret20>0)::INTEGER) AS market_breadth20,
        max(available_at) AS market_latest_source_timestamp
      FROM base GROUP BY trade_date
    ), industry_state0 AS (
      SELECT trade_date,causal_industry,
        count(*) AS industry_n,
        median(ret20) AS industry20,
        avg((ret20>0)::INTEGER) AS industry_breadth20,
        max(available_at) AS industry_latest_source_timestamp
      FROM base
      WHERE causal_industry IS NOT NULL
      GROUP BY trade_date,causal_industry
    ), industry_state AS (
      SELECT *,
        lag(industry_breadth20,5) OVER (
          PARTITION BY causal_industry ORDER BY trade_date
        ) AS industry_breadth20_lag5
      FROM industry_state0
    ), feature AS (
      SELECT b.*,m.market_n,m.market_breadth20,m.market_latest_source_timestamp,
        i.industry_n,i.industry20,i.industry_breadth20,
        i.industry_breadth20_lag5,i.industry_latest_source_timestamp,
        i.industry_breadth20-i.industry_breadth20_lag5 AS industry_breadth20_delta5
      FROM base b
      JOIN market_state m USING(trade_date)
      JOIN industry_state i USING(trade_date,causal_industry)
    )
    SELECT *,trade_date AS signal_date,
      greatest(decision_at,market_latest_source_timestamp,industry_latest_source_timestamp)
        AS feature_latest_timestamp
    FROM feature
    WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2026-09-04'
      AND hard_valid AND history_valid AND current_valid
      AND current_day_data_tradable AND trade_status=1
      AND market_rule_valid AND corporate_action_valid AND NOT corporate_action_blocking
      AND coalesce(corporate_action_count,0)=0
      AND industry_valid AND historical_identity_valid
      AND available_at<=decision_at
      AND market_latest_source_timestamp<=decision_at
      AND industry_latest_source_timestamp<=decision_at
      AND round(close*100)<round(up_limit_price*100)
      AND market_breadth20>=0.65
      AND industry20>0.03
      AND industry_breadth20>0.60
      AND industry_breadth20_delta5>=0.25
      AND ret60 BETWEEN 0.00 AND 0.15
      AND prior20_limitups=0
      AND coord_close>prior20_high
      AND step_return BETWEEN 0.02 AND 0.06
      AND close_location>=0.70
      AND turnover_ratio BETWEEN 1.50 AND 4.00
    ORDER BY symbol,cal_idx
    """


def build_candidates() -> tuple[pd.DataFrame, dict[str, Any]]:
    RAW_CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = connection()
    con.execute(
        f"COPY ({feature_sql()}) TO '{RAW_CANDIDATES.as_posix()}' "
        "(FORMAT PARQUET,COMPRESSION ZSTD)"
    )
    con.close()
    raw = pd.read_parquet(RAW_CANDIDATES)
    for column in (
        "trade_date",
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
        "industry_latest_source_timestamp",
        "feature_latest_timestamp",
    ):
        raw[column] = pd.to_datetime(raw[column])
    kept: list[int] = []
    last: dict[str, int] = {}
    for row in raw.sort_values(["symbol", "cal_idx"], kind="mergesort").itertuples():
        previous = last.get(str(row.symbol), -(10**9))
        if int(row.cal_idx) - previous >= 21:
            kept.append(int(row.Index))
            last[str(row.symbol)] = int(row.cal_idx)
    candidates = raw.loc[kept].copy()
    candidates["event_id"] = (
        "V29B|"
        + candidates.signal_date.dt.strftime("%Y%m%d")
        + "|"
        + candidates.symbol.astype(str)
    )
    candidates["lane"] = "SIMPLE_BULL_PARTICIPATION_IGNITION"
    candidates = candidates.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(
        drop=True
    )
    audit = {
        "raw_candidate_count": int(len(raw)),
        "cooled_candidate_count": int(len(candidates)),
        "duplicate_event_count": int(candidates.event_id.duplicated().sum()),
        "feature_after_decision_count": int(
            candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()
        ),
        "available_after_decision_count": int(
            candidates.available_at.gt(candidates.decision_at).sum()
        ),
        "post_data_end_candidate_count": int(candidates.signal_date.gt(DATA_END).sum()),
        "cooldown_violation_count": int(
            (
                candidates.sort_values(["symbol", "cal_idx"])
                .groupby("symbol")
                .cal_idx.diff()
                .dropna()
                .lt(21)
            ).sum()
        ),
    }
    if any(audit[key] for key in audit if key.endswith("count") and key not in {"raw_candidate_count", "cooled_candidate_count"}):
        raise ResearchError(f"Stage-A candidate audit failed: {audit}")
    write_parquet(candidates, CANDIDATES)
    return candidates, audit


def run_stage_a() -> dict[str, Any]:
    inputs = verify_static_inputs()
    candidates, audit = build_candidates()
    freeze = {
        "experiment": EXPERIMENT,
        "status": "FROZEN_BEFORE_EXPANDED_BULL_OUTCOMES",
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "input_hashes": inputs,
        "raw_candidate_sha256": sha256(RAW_CANDIDATES),
        "candidate_sha256": sha256(CANDIDATES),
        "candidate_count": int(len(candidates)),
        "annual_candidate_count": {
            str(int(year)): int(value)
            for year, value in candidates.groupby(candidates.signal_date.dt.year).size().items()
        },
        "audit": audit,
        "expanded_bull_outcomes_opened": False,
        "rule_search_run": False,
    }
    write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not FREEZE.exists() or not CANDIDATES.exists():
        raise ResearchError("Stage A missing")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    inputs = verify_static_inputs()
    expected = {
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "raw_candidate_sha256": sha256(RAW_CANDIDATES),
        "input_hashes": inputs,
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in expected.items()
        if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def legal_state(row: pd.Series, lineage: float) -> bool:
    required = (
        "hard_valid",
        "history_valid",
        "current_valid",
        "corporate_action_valid",
        "current_day_data_tradable",
        "market_rule_valid",
    )
    if any(pd.isna(row.get(name)) or not bool(row.get(name)) for name in required):
        return False
    if pd.isna(row.get("corporate_action_blocking")) or bool(row.corporate_action_blocking):
        return False
    if pd.isna(row.get("trade_status")) or int(row.trade_status) != 1:
        return False
    if pd.isna(row.get("invalid_step_cum")):
        return False
    return float(row.invalid_step_cum) == lineage


def legal_buy(row: pd.Series, lineage: float) -> bool:
    return legal_state(row, lineage) and round(float(row.open) * 100) < round(
        float(row.up_limit_price) * 100
    )


def legal_sell_open(row: pd.Series, lineage: float) -> bool:
    return legal_state(row, lineage) and round(float(row.open) * 100) > round(
        float(row.down_limit_price) * 100
    )


def load_trade_daily(symbols: list[str]) -> pd.DataFrame:
    registry = pd.DataFrame({"symbol": sorted(set(symbols))})
    con = connection()
    con.register("registry", registry)
    fields = """
      CAST(trade_date AS DATE) AS trade_date,cal_idx,symbol,open,high,low,close,
      trade_status,current_day_data_tradable,up_limit_price,down_limit_price,
      market_rule_valid,corporate_action_valid,corporate_action_blocking,
      history_valid,current_valid,hard_valid,invalid_step_cum,
      coord_open,coord_high,coord_low,coord_close
    """
    frame = con.execute(
        f"""
        WITH d AS (
          SELECT {fields} FROM read_parquet('{DAILY_HIST.as_posix()}')
          WHERE trade_date<=DATE '2023-12-31'
          UNION ALL BY NAME
          SELECT {fields} FROM read_parquet('{DAILY_POST.as_posix()}')
          WHERE trade_date>=DATE '2024-01-01'
        )
        SELECT d.* FROM d JOIN registry USING(symbol)
        ORDER BY symbol,cal_idx
        """
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def build_outcome_batch(candidates: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    groups = {
        str(symbol): part.sort_values("cal_idx").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        part = groups.get(str(event.symbol))
        if part is None:
            raise ResearchError(f"missing daily symbol: {event.symbol}")
        signal_positions = np.flatnonzero(
            part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy()
        )
        if len(signal_positions) != 1:
            raise ResearchError(f"missing signal day: {event.event_id}")
        signal_pos = int(signal_positions[0])
        lineage = float(event.invalid_step_cum)
        base = {
            "event_id": event.event_id,
            "symbol": event.symbol,
            "sleeve": event.sleeve,
            "signal_date": event.signal_date,
            "signal_cal_idx": int(event.cal_idx),
            "profile": "T15_H15_NO_STOP",
        }
        entry_pos = None
        for pos in range(signal_pos + 1, len(part)):
            row = part.iloc[pos]
            if int(row.cal_idx) > int(event.cal_idx) + 3:
                break
            if legal_buy(row, lineage):
                entry_pos = pos
                break
        if entry_pos is None:
            rows.append({**base, "status": "NO_LEGAL_ENTRY"})
            continue
        entry = part.iloc[entry_pos]
        entry_price = float(entry.coord_open)
        horizon_idx = int(entry.cal_idx) + HORIZON
        target_price = entry_price * (1 + TARGET)
        target_choice: tuple[int, float] | None = None
        decision_pos = None
        for pos in range(entry_pos + 1, len(part)):
            row = part.iloc[pos]
            state_valid = legal_state(row, lineage)
            if state_valid and float(row.coord_high) >= target_price:
                target_choice = (pos, target_price)
                break
            if int(row.cal_idx) >= horizon_idx and state_valid:
                decision_pos = pos
                break
        if target_choice is not None:
            exit_pos, exit_price = target_choice
            exit_reason = "TARGET_15"
            exit_decision_idx = int(entry.cal_idx)
        else:
            if decision_pos is None:
                rows.append(
                    {
                        **base,
                        "status": "INCOMPLETE_OUTCOME_TAIL",
                        "entry_date": entry.trade_date,
                        "entry_cal_idx": int(entry.cal_idx),
                        "entry_price": entry_price,
                    }
                )
                continue
            exit_pos = None
            for pos in range(decision_pos + 1, len(part)):
                if legal_sell_open(part.iloc[pos], lineage):
                    exit_pos = pos
                    break
            if exit_pos is None:
                rows.append(
                    {
                        **base,
                        "status": "INCOMPLETE_OUTCOME_TAIL",
                        "entry_date": entry.trade_date,
                        "entry_cal_idx": int(entry.cal_idx),
                        "entry_price": entry_price,
                    }
                )
                continue
            exit_price = float(part.iloc[exit_pos].coord_open)
            exit_reason = "H15_TIME_STOP"
            exit_decision_idx = int(part.iloc[decision_pos].cal_idx)
        exit_row = part.iloc[exit_pos]
        if part.iloc[entry_pos : exit_pos + 1].invalid_step_cum.ne(lineage).any():
            rows.append(
                {
                    **base,
                    "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                    "entry_date": entry.trade_date,
                    "entry_cal_idx": int(entry.cal_idx),
                    "entry_price": entry_price,
                }
            )
            continue
        gross = exit_price / entry_price - 1
        rows.append(
            {
                **base,
                "status": "COMPLETED",
                "entry_date": entry.trade_date,
                "entry_cal_idx": int(entry.cal_idx),
                "entry_price": entry_price,
                "exit_date": exit_row.trade_date,
                "exit_cal_idx": int(exit_row.cal_idx),
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "exit_decision_cal_idx": exit_decision_idx,
                "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
                "gross_return": gross,
                "net_return": gross - ENTRY_COST - EXIT_COST,
            }
        )
    frame = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame


def build_outcomes(candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    OUTCOME_SHARDS.mkdir(parents=True, exist_ok=True)
    symbols = sorted(candidates.symbol.astype(str).unique())
    shard_paths: list[Path] = []
    for batch_number, start in enumerate(range(0, len(symbols), BATCH_SYMBOLS)):
        batch_symbols = symbols[start : start + BATCH_SYMBOLS]
        batch = candidates.loc[candidates.symbol.astype(str).isin(batch_symbols)].copy()
        expected_ids = sorted(batch.event_id.astype(str))
        event_hash = ids_sha256(expected_ids)
        shard = OUTCOME_SHARDS / f"batch_{batch_number:03d}.parquet"
        manifest = OUTCOME_SHARDS / f"batch_{batch_number:03d}.json"
        if shard.exists() and manifest.exists():
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            observed = pd.read_parquet(shard, columns=["event_id"])
            if (
                payload.get("event_ids_sha256") == event_hash
                and sorted(observed.event_id.astype(str)) == expected_ids
            ):
                shard_paths.append(shard)
                continue
            raise ResearchError(f"existing outcome shard identity drift: {shard}")
        daily = load_trade_daily(batch_symbols)
        outcomes = build_outcome_batch(batch, daily)
        if sorted(outcomes.event_id.astype(str)) != expected_ids:
            raise ResearchError(f"outcome batch identity mismatch: {batch_number}")
        write_parquet(outcomes, shard)
        write_json(
            manifest,
            {
                "batch": batch_number,
                "symbol_count": len(batch_symbols),
                "event_count": len(batch),
                "event_ids_sha256": event_hash,
                "outcome_sha256": sha256(shard),
            },
        )
        shard_paths.append(shard)
    outcomes = pd.concat([pd.read_parquet(path) for path in shard_paths], ignore_index=True)
    outcomes = outcomes.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(
        drop=True
    )
    write_parquet(outcomes, OUTCOMES)
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    audit = {
        "candidate_outcome_identity_mismatch_count": int(
            len(set(candidates.event_id) ^ set(outcomes.event_id))
        ),
        "signal_bar_fill_count": int(
            (outcomes.entry_date.notna() & outcomes.entry_date.le(outcomes.signal_date)).sum()
        ),
        "t1_same_day_exit_count": int(
            completed.exit_cal_idx.le(completed.entry_cal_idx).sum()
        ),
        "cost_identity_violation_count": int(
            (completed.net_return - (completed.gross_return - 0.004)).abs().gt(1e-11).sum()
        ),
    }
    if any(audit.values()):
        raise ResearchError(f"outcome audit failed: {audit}")
    return outcomes, audit


def v65_overlap_reproduction(outcomes: pd.DataFrame) -> dict[str, int]:
    v65, _statuses = v28.load_v65()
    v65["signal_date"] = pd.to_datetime(v65.signal_date)
    joined = outcomes.merge(
        v65,
        on=["symbol", "signal_date"],
        how="inner",
        suffixes=("_v29", "_v65"),
        validate="one_to_one",
    )
    joined = joined.loc[joined.status_v29.eq("COMPLETED")]
    categorical = sum(
        int(
            joined[f"{name}_v29"].astype("string").ne(
                joined[f"{name}_v65"].astype("string")
            ).sum()
        )
        for name in ("entry_date", "exit_date", "exit_reason")
    )
    numeric = sum(
        int(
            (~np.isclose(
                pd.to_numeric(joined[f"{name}_v29"], errors="coerce"),
                pd.to_numeric(joined[f"{name}_v65"], errors="coerce"),
                rtol=0,
                atol=1e-11,
                equal_nan=True,
            )).sum()
        )
        for name in ("entry_price", "exit_price", "gross_return", "net_return")
    )
    return {
        "overlap_completed_rows": int(len(joined)),
        "overlap_categorical_mismatch_count": int(categorical),
        "overlap_numeric_mismatch_count": int(numeric),
    }


def assemble_union(
    outcomes: pd.DataFrame, candidates: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    fields = [
        "event_id",
        "lane",
        "industry_breadth20_delta5",
        "ret60",
        "turnover_ratio",
        "feature_latest_timestamp",
        "decision_at",
        "available_at",
        "invalid_step_cum",
    ]
    bull = outcomes.loc[outcomes.status.eq("COMPLETED")].merge(
        candidates[fields], on="event_id", how="left", validate="one_to_one"
    )
    bull["source"] = "V29_SIMPLE_BULL"
    bull["source_event_id"] = bull.event_id.astype(str)
    bull["event_id"] = "V29|BULL|" + bull.source_event_id
    bull["source_rank1"] = bull.industry_breadth20_delta5.astype(float)
    bull["source_rank2"] = -bull.ret60.astype(float)
    bull["source_rank3"] = bull.turnover_ratio.astype(float)
    bear = pd.read_parquet(V28_FROZEN_SOURCE)
    bear = bear.loc[bear.source.eq("V27_BEAR")].copy()
    if len(bear) != 2044:
        raise ResearchError(f"frozen V27 Bear row count drift: {len(bear)}")
    bear["event_id"] = bear.event_id.str.replace("V28|V27|", "V29|V27|", regex=False)
    frame = pd.concat([bear, bull], ignore_index=True, sort=False)
    frame = v28.parse_dates(frame)
    frame = frame.sort_values(
        ["signal_date", "sleeve", "source", "source_rank1", "source_rank2", "source_rank3", "event_id"],
        ascending=[True, True, True, False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    frame["source_rank_order"] = frame.groupby(
        ["signal_date", "sleeve", "source"], sort=False
    ).cumcount()
    overlap = bear[["symbol", "signal_date"]].merge(
        bull[["symbol", "signal_date"]].drop_duplicates(), on=["symbol", "signal_date"]
    )
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "same_source_symbol_signal_duplicate_count": int(
            frame.duplicated(["source", "symbol", "signal_date"]).sum()
        ),
        "cross_source_symbol_signal_overlap_count": int(len(overlap)),
        "entry_at_or_before_signal_count": int(frame.entry_date.le(frame.signal_date).sum()),
        "exit_at_or_before_entry_count": int(frame.exit_date.le(frame.entry_date).sum()),
        "feature_after_decision_count": int(
            bull.feature_latest_timestamp.gt(bull.decision_at).sum()
        ),
    }
    if any(audit.values()):
        raise ResearchError(f"union audit failed: {audit}")
    write_parquet(frame, SOURCE_UNION)
    return frame, audit


def shared_replay(trades: pd.DataFrame):
    old = (v28.DAILY_PATHS, v28.ACCEPTED, v28.SKIPPED, v28.NAV)
    try:
        v28.DAILY_PATHS = DAILY_PATHS
        v28.ACCEPTED = ACCEPTED
        v28.SKIPPED = SKIPPED
        v28.NAV = NAV
        paths, dates, path_audit = v28.load_daily_paths(trades)
        accepted, skipped, nav, replay_audit = v28.replay_shared_portfolio(
            trades, paths, dates
        )
    finally:
        v28.DAILY_PATHS, v28.ACCEPTED, v28.SKIPPED, v28.NAV = old
    return accepted, skipped, nav, paths, {**path_audit, **replay_audit}


def render_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        "V29 compresses the bull mechanism to five semantic condition groups and leaves the two V27 Bear routes unchanged. No threshold alternative was searched after expanded outcomes were opened.",
        "",
        "| Year | Trades | Mean net | Median net | Win | Severe10 | Date-equal | Portfolio |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in sorted(result["annual_trade"], key=int):
        item = result["annual_trade"][year]
        port = result["annual_portfolio"][year]["return"]
        lines.append(
            f"| {year} | {item['trades']} | {item['mean_net']:.2%} | {item['median_net']:.2%} | "
            f"{item['win_rate']:.2%} | {item['severe_loss10']:.2%} | "
            f"{item['signal_date_equal_mean']:.2%} | {port:.2%} |"
        )
    lines.extend(
        [
            "",
            f"Verdict: **{result['verdict']}**",
            "",
            "This remains iterative, multiple-testing-exposed research. Passing would establish a simpler historical candidate, not untouched external validation.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_stage_b() -> dict[str, Any]:
    freeze = verify_stage_a()
    candidates = v28.parse_dates(pd.read_parquet(CANDIDATES))
    outcomes, outcome_audit = build_outcomes(candidates)
    reproduction = v65_overlap_reproduction(outcomes)
    if reproduction["overlap_categorical_mismatch_count"] or reproduction["overlap_numeric_mismatch_count"]:
        raise ResearchError(f"V65 overlap reproduction failed: {reproduction}")
    trades, union_audit = assemble_union(outcomes, candidates)
    accepted, skipped, nav, paths, replay_audit = shared_replay(trades)
    execution = v28.execution_audit(accepted, paths)
    if any(execution.values()):
        raise ResearchError(f"execution audit failed: {execution}")
    annual = {
        str(int(year)): v28.trade_summary(part)
        for year, part in accepted.groupby(accepted.signal_date.dt.year, sort=True)
    }
    full = accepted.loc[accepted.signal_date.dt.year.isin(FULL_YEARS)]
    fresh = accepted.loc[accepted.signal_date.dt.year.eq(2026)]
    full_summary = v28.trade_summary(full)
    fresh_summary = v28.trade_summary(fresh)
    goal = {
        "average_trades_per_full_year": float(len(full) / len(FULL_YEARS)),
        "average_trades_per_full_year_gt_50": len(full) / len(FULL_YEARS) > 50,
        "pooled_mean_net_gt_2pct": full_summary["mean_net"] > 0.02,
        "each_full_year_mean_positive": all(annual[str(year)]["mean_net"] > 0 for year in FULL_YEARS),
        "fresh_2026_ytd_mean_positive": fresh_summary["mean_net"] > 0,
        "signal_date_equal_mean_positive": full_summary["signal_date_equal_mean"] > 0,
    }
    goal["passed"] = all(value for key, value in goal.items() if key != "average_trades_per_full_year")
    result = {
        "experiment": EXPERIMENT,
        "verdict": (
            "V29_SIMPLE_CAUSAL_NUMERICAL_GOAL_MET"
            if goal["passed"]
            else "V29_SIMPLIFICATION_FAILED"
        ),
        "evidence_label": "ITERATIVE_MECHANISM_DISTILLATION_NOT_PRISTINE_VALIDATION",
        "stage_a": freeze,
        "outcome_status": outcomes.status.value_counts().astype(int).to_dict(),
        "raw_source_completed": int(len(trades)),
        "accepted_completed": int(len(accepted)),
        "capacity_skips": int(len(skipped)),
        "full_years_2014_2025": full_summary,
        "fresh_2026_ytd": fresh_summary,
        "annual_trade": annual,
        "source": {
            str(name): v28.trade_summary(part)
            for name, part in accepted.groupby("source", sort=True)
        },
        "lane": {
            str(name): v28.trade_summary(part)
            for name, part in accepted.groupby("lane", sort=True)
        },
        "board": {
            str(name): v28.trade_summary(part)
            for name, part in accepted.groupby("sleeve", sort=True)
        },
        "portfolio": v28.portfolio_summary(nav),
        "annual_portfolio": v28.annual_portfolio(nav),
        "concentration": v28.concentration(accepted),
        "goal": goal,
        "audit": {
            **outcome_audit,
            **reproduction,
            **union_audit,
            **replay_audit,
            **execution,
            "threshold_search_after_outcome_open_count": 0,
            "rule_change_after_outcome_open_count": 0,
            "source_bear_rule_change_count": 0,
        },
        "hashes": {
            "contract": sha256(CONTRACT),
            "runner": sha256(Path(__file__)),
            "candidates": sha256(CANDIDATES),
            "outcomes": sha256(OUTCOMES),
            "source_union": sha256(SOURCE_UNION),
            "accepted": sha256(ACCEPTED),
            "skipped": sha256(SKIPPED),
            "nav": sha256(NAV),
        },
    }
    write_json(RESULT, result)
    render_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("stage-a", "stage-b", "all", "verify"), default="all")
    args = parser.parse_args()
    if args.stage in {"stage-a", "all"}:
        print(json.dumps({"stage_a": run_stage_a()}, indent=2, default=str))
    if args.stage in {"stage-b", "all"}:
        print(json.dumps({"stage_b": run_stage_b()}, indent=2, default=str))
    if args.stage == "verify":
        print(json.dumps({"verified": verify_stage_a()}, indent=2, default=str))


if __name__ == "__main__":
    main()
