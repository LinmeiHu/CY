#!/usr/bin/env python3
"""Run the one frozen post-chart rule compression for BULL distributed accumulation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-BULL-DISTRIBUTED-ACCUMULATION-CHART-RULES-V3"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "9a201c35c4f2dd7c88a6d1e957a7235e6ca4b5718bc3b72df624ba0f950b0787"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
PARENT_ROOT = (
    DATA_ROOT
    / "ashare_bull_distributed_accumulation_12m_chart_discovery_v2"
    / "development_2014_2020"
)
PARENT_CANDIDATES = PARENT_ROOT / "candidates_frozen.parquet"
DAILY = (
    DATA_ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
EXPECTED_INPUT_HASHES = {
    PARENT_CANDIDATES: "6ba8527303c69c29a6fff74aefc4823e57195a7358489da68fedbb5d62a564f5",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
}
OUTPUT_ROOT = (
    DATA_ROOT / "ashare_bull_distributed_accumulation_chart_rules_v3" / "development_2014_2020"
)
STATE_PANEL = OUTPUT_ROOT / "causal_rule_panel.parquet"
PATHS = OUTPUT_ROOT / "future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"
ROUND_TRIP_COST = 0.004


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT history, or executable chronology."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT_ROOT / "duckdb_tmp"
    temp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temp.as_posix()}'")
    return con


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    con = connection()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def verify_inputs() -> dict[str, str]:
    expected = {FREEZE: EXPECTED_FREEZE_SHA256, **EXPECTED_INPUT_HASHES}
    actual: dict[str, str] = {}
    for path, expected_hash in expected.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual_hash = sha256(path)
        actual[str(path)] = actual_hash
        if actual_hash != expected_hash:
            raise ResearchError(f"frozen input drift: {path}: {actual_hash} != {expected_hash}")
    return actual


def build_rule_panel() -> pd.DataFrame:
    candidates = pd.read_parquet(PARENT_CANDIDATES)
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    if candidates.empty or candidates.event_id.duplicated().any():
        raise ResearchError("empty or duplicate frozen mother identity")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered development")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("stock input available after mother decision")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("market input available after mother decision")
    candidates["same_date_mother_count"] = candidates.groupby("signal_date")["event_id"].transform(
        "size"
    )

    con = connection()
    con.register(
        "events",
        candidates[["event_id", "symbol", "signal_cal_idx", "invalid_step_cum"]],
    )
    prior = con.execute(
        f"""
        SELECT e.event_id,
          count(*) AS prior126_rows,
          min(d.cal_idx) AS prior126_min_cal_idx,
          max(d.cal_idx) AS prior126_max_cal_idx,
          min(d.invalid_step_cum) AS prior126_lineage_min,
          max(d.invalid_step_cum) AS prior126_lineage_max,
          bool_and(
            d.hard_valid AND d.market_rule_valid AND d.corporate_action_valid
            AND NOT d.corporate_action_blocking
            AND coalesce(d.corporate_action_count,0)=0
            AND d.available_at<=d.decision_at
            AND d.coord_high>0
          ) AS prior126_valid,
          max(d.coord_high) AS prior126_coord_high
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON d.symbol=e.symbol
         AND d.cal_idx BETWEEN e.signal_cal_idx-126 AND e.signal_cal_idx-1
        GROUP BY e.event_id
        """
    ).fetch_df()
    con.close()
    panel = candidates.merge(prior, on="event_id", how="left", validate="one_to_one")
    required = [
        "prior126_rows",
        "prior126_min_cal_idx",
        "prior126_max_cal_idx",
        "prior126_lineage_min",
        "prior126_lineage_max",
        "prior126_valid",
        "prior126_coord_high",
    ]
    if panel[required].isna().any().any():
        raise ResearchError("missing prior-126 history aggregation")
    panel["rule_history_valid"] = (
        panel.prior126_rows.eq(126)
        & panel.prior126_min_cal_idx.eq(panel.signal_cal_idx - 126)
        & panel.prior126_max_cal_idx.eq(panel.signal_cal_idx - 1)
        & panel.prior126_lineage_min.eq(panel.invalid_step_cum)
        & panel.prior126_lineage_max.eq(panel.invalid_step_cum)
        & panel.prior126_valid.astype(bool)
    )
    panel["rule_clear_target_corridor"] = panel.coord_close.gt(
        panel.prior126_coord_high
    ) | panel.prior126_coord_high.ge(panel.coord_close * 1.15)
    panel["rule_market_strengthening"] = (1.0 + panel.market_median_ret20).pow(3).ge(
        1.0 + panel.market_median_ret60
    ) & panel.market_positive_ret20_share.ge(panel.market_positive_ret60_share)
    panel["rule_crowding_supported"] = panel.market_positive_ret60_share.ge(
        0.80
    ) | panel.same_date_mother_count.le(25)
    panel["pre_confirmation_pass"] = (
        panel.rule_history_valid
        & panel.rule_clear_target_corridor
        & panel.rule_market_strengthening
        & panel.rule_crowding_supported
    )
    panel = panel.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort").reset_index(
        drop=True
    )
    return panel


def build_paths(panel: pd.DataFrame) -> pd.DataFrame:
    con = connection()
    con.register("events", panel[["event_id", "symbol", "signal_cal_idx"]])
    query = f"""
      SELECT e.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.invalid_step_cum,
        d.coordinate_factor,d.trade_status,d.current_day_data_tradable,d.current_valid,
        d.market_rule_valid,d.corporate_action_count,d.corporate_action_valid,
        d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price,
        d.available_at,d.decision_at
      FROM events e JOIN read_parquet('{DAILY.as_posix()}') d
        ON e.symbol=d.symbol AND d.cal_idx>e.signal_cal_idx
       AND d.cal_idx<=e.signal_cal_idx+110
      WHERE d.trade_date<=DATE '2021-12-31'
      ORDER BY e.event_id,d.cal_idx
    """
    con.execute(f"COPY ({query}) TO '{PATHS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    paths = con.execute(
        f"SELECT * FROM read_parquet('{PATHS.as_posix()}') ORDER BY event_id,cal_idx"
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    return paths


def legal(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.open,
        row.coord_open,
        row.coordinate_factor,
        row.available_at,
        row.decision_at,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.current_valid
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and int(row.corporate_action_count) == 0
        and row.hard_valid
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and pd.Timestamp(row.available_at) <= pd.Timestamp(row.decision_at)
    )


def buyable(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    common = {
        "event_id": candidate.event_id,
        "symbol": candidate.symbol,
        "sleeve": candidate.sleeve,
        "signal_date": candidate.signal_date,
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "same_date_mother_count": int(candidate.same_date_mother_count),
        "rule_history_valid": bool(candidate.rule_history_valid),
        "rule_clear_target_corridor": bool(candidate.rule_clear_target_corridor),
        "rule_market_strengthening": bool(candidate.rule_market_strengthening),
        "rule_crowding_supported": bool(candidate.rule_crowding_supported),
        "pre_confirmation_pass": bool(candidate.pre_confirmation_pass),
    }
    if not candidate.pre_confirmation_pass:
        return {**common, "status": "REJECTED_PRE_CONFIRMATION"}
    lineage = float(candidate.invalid_step_cum)
    confirmation_pool = path.loc[
        path.cal_idx.gt(candidate.signal_cal_idx) & path.cal_idx.le(candidate.signal_cal_idx + 3)
    ]
    confirmation = next(
        (
            row
            for row in confirmation_pool.itertuples(index=False)
            if float(row.invalid_step_cum) == lineage
            and legal(row)
            and np.isfinite(float(row.coord_close))
            and float(row.coord_close) > 0
        ),
        None,
    )
    if confirmation is None:
        return {**common, "status": "NO_LEGAL_CONFIRMATION"}
    confirmation_common = {
        **common,
        "confirmation_date": pd.Timestamp(confirmation.trade_date),
        "confirmation_cal_idx": int(confirmation.cal_idx),
        "confirmation_close": float(confirmation.coord_close),
    }
    if float(confirmation.coord_close) < float(candidate.coord_close):
        return {**confirmation_common, "status": "REJECTED_ACCEPTANCE"}
    confirmation_idx = int(confirmation.cal_idx)
    entry_pool = path.loc[path.cal_idx.gt(confirmation_idx) & path.cal_idx.le(confirmation_idx + 3)]
    entry = next(
        (
            row
            for row in entry_pool.itertuples(index=False)
            if float(row.invalid_step_cum) == lineage and buyable(row)
        ),
        None,
    )
    if entry is None:
        return {**confirmation_common, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target_price = entry_price * 1.15
    entry_common = {
        **confirmation_common,
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    exit_row = None
    exit_price = math.nan
    exit_reason = None
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {**entry_common, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"}
        if (
            legal(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            exit_row = row
            exit_price = target_price
            exit_reason = "TARGET_15"
            break
        if int(row.cal_idx) > entry_idx + 30 and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H30_TIME_STOP"
            break
    if exit_row is None:
        return {**entry_common, "status": "INCOMPLETE_PATH"}
    gross = exit_price / entry_price - 1.0
    return {
        **entry_common,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    accepted = frame.loc[~frame.status.isin(["REJECTED_PRE_CONFIRMATION", "REJECTED_ACCEPTANCE"])]
    complete = frame.loc[frame.status.eq("COMPLETED")]
    values = pd.to_numeric(complete.net_return, errors="coerce")
    return {
        "accepted_signals": len(accepted),
        "completed": len(complete),
        "signal_dates": int(complete.signal_date.nunique()),
        "symbols": int(complete.symbol.nunique()),
        "mean_net": None if complete.empty else float(values.mean()),
        "median_net": None if complete.empty else float(values.median()),
        "positive_rate": None if complete.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if complete.empty else float(values.ge(0.04).mean()),
        "severe10": None if complete.empty else float(values.le(-0.10).mean()),
        "target_hit": None
        if complete.empty
        else float(complete.exit_reason.eq("TARGET_15").mean()),
        "mean_holding_sessions": None
        if complete.empty
        else float(complete.holding_sessions.mean()),
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    panel = build_rule_panel()
    write_parquet(panel, STATE_PANEL)
    paths = build_paths(panel)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            replay_one(candidate, groups.get(candidate.event_id, pd.DataFrame()))
            for candidate in panel.itertuples(index=False)
        ]
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    for column in ("confirmation_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(outcomes) != len(panel) or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome identity mismatch")
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "confirmation_at_or_before_signal": int(
            complete.confirmation_cal_idx.le(complete.signal_cal_idx).sum()
        ),
        "entry_at_or_before_confirmation": int(
            complete.entry_cal_idx.le(complete.confirmation_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(complete.exit_cal_idx.le(complete.entry_cal_idx).sum()),
    }
    if any(chronology.values()):
        raise ResearchError(f"chronology failure: {chronology}")
    if not complete.empty and complete.exit_date.max() > pd.Timestamp("2021-12-31"):
        raise ResearchError("post-2021 outcome entered development")
    write_parquet(outcomes, OUTCOMES)
    by_year = {
        str(int(year)): metrics(part)
        for year, part in outcomes.groupby(outcomes.signal_date.dt.year, sort=True)
    }
    year_gate = {
        year: bool(
            values["completed"] > 50
            and values["mean_net"] is not None
            and values["mean_net"] > 0.04
            and values["median_net"] is not None
            and values["median_net"] > 0
            and values["severe10"] is not None
            and values["severe10"] <= 0.20
        )
        for year, values in by_year.items()
    }
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_CHART_RULE_DEVELOPMENT_TEST",
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "source_hashes": source_hashes,
        "mother_signals": len(panel),
        "rule_pass_counts": {
            "history_valid": int(panel.rule_history_valid.sum()),
            "clear_target_corridor": int(panel.rule_clear_target_corridor.sum()),
            "market_strengthening": int(panel.rule_market_strengthening.sum()),
            "crowding_supported": int(panel.rule_crowding_supported.sum()),
            "pre_confirmation_pass": int(panel.pre_confirmation_pass.sum()),
        },
        "status_counts": {
            str(key): int(value)
            for key, value in outcomes.status.value_counts(dropna=False).sort_index().items()
        },
        "overall": metrics(outcomes),
        "by_signal_year": by_year,
        "year_gate": year_gate,
        "development_gate_pass": bool(year_gate and all(year_gate.values())),
        "chronology": chronology,
        "maximum_signal_date": str(panel.signal_date.max().date()),
        "maximum_outcome_date": None if complete.empty else str(complete.exit_date.max().date()),
        "2021_signal_used": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "post_2024_read": "NO",
        "future_market_function": False,
        "rescue_experiment": "PROHIBITED",
        "state_panel_sha256": sha256(STATE_PANEL),
        "paths_sha256": sha256(PATHS),
        "outcomes_sha256": sha256(OUTCOMES),
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return payload


if __name__ == "__main__":
    run()
