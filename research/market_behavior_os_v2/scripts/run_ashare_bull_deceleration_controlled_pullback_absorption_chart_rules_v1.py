#!/usr/bin/env python3
"""Evaluate one chart-derived, causally executable five-rule translation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-BULL-DECELERATION-CONTROLLED-PULLBACK-ABSORPTION-CHART-RULES-V1"
PARENT = "ASHARE-BULL-DECELERATION-CONTROLLED-PULLBACK-ABSORPTION-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
ROOT = DATA_ROOT / "ashare_bull_deceleration_controlled_pullback_absorption_mother_v1"
CANDIDATES = ROOT / "stage_a/candidates_frozen.parquet"
PATHS = ROOT / "stage_b/future_paths.parquet"
WINDOWS = ROOT / "stage_c_charts/chart_window_panel.parquet"
CHART_MANIFEST = ROOT / "stage_c_charts/manifest.json"
OUTPUT_ROOT = ROOT / "stage_d_chart_rules_v1"
EVENTS = OUTPUT_ROOT / "event_results.parquet"
RESULT = OUTPUT_ROOT / "result.json"
ROUND_TRIP_COST = 0.004
TARGET_RETURN = 0.10
HORIZON = 20
CONFIRMATION_SESSIONS = 3
ENTRY_SEARCH_SESSIONS = 3
MIN_PRE60_POSITION = 0.50
EXPECTED_HASHES = {
    CANDIDATES: "6559b250dd2dea34b6b9f23ff56f8011ca6f34f2dec34aa50014382c2f6cb8ec",
    PATHS: "0f0bbf7f5f16f152d8eb2d926aa6eb94ee19fe891fd7100c1690915b8050d47e",
    WINDOWS: "47810bb4d987b5e1f013d068814ff461f6664230d55de3758dd8d57b5218734e",
    CHART_MANIFEST: "2d5ddb7522ca9a3fd686069b432c6bb688dfd229102d86f884a922b6d114b2fa",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, causality, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    if not SPEC.is_file():
        raise ResearchError(f"missing frozen rule spec: {SPEC}")
    actual[str(SPEC)] = sha256(SPEC)
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def legal(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_count,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.open,
        row.coord_open,
        row.coordinate_factor,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid)
        and bool(row.market_rule_valid)
        and int(row.corporate_action_count) == 0
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
        and float(row.open) > 0
        and float(row.coord_open) > 0
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


def completed_close_valid(row: Any, lineage: float) -> bool:
    required = (
        row.invalid_step_cum,
        row.coord_close,
        row.current_valid,
        row.hard_valid,
        row.available_at,
        row.decision_at,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and float(row.invalid_step_cum) == lineage
        and bool(row.current_valid)
        and bool(row.hard_valid)
        and float(row.coord_close) > 0
        and pd.Timestamp(row.available_at) <= pd.Timestamp(row.decision_at)
    )


def pre60_position(frame: pd.DataFrame, signal_idx: int) -> float:
    prior = frame.loc[
        frame.cal_idx.lt(signal_idx)
        & frame.current_valid.fillna(False)
        & frame.hard_valid.fillna(False)
        & frame[["coord_high", "coord_low", "coord_close"]].notna().all(axis=1)
    ].sort_values("cal_idx", kind="mergesort").tail(60)
    if len(prior) != 60:
        return math.nan
    high = float(prior.coord_high.max())
    low = float(prior.coord_low.min())
    close = float(prior.iloc[-1].coord_close)
    return (close - low) / (high - low) if high > low else math.nan


def base_row(candidate: Any, position: float) -> dict[str, Any]:
    return {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_year": int(pd.Timestamp(candidate.signal_date).year),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "causal_industry": str(candidate.causal_industry),
        "market_regime": str(candidate.market_regime),
        "market_median_ret20": float(candidate.market_median_ret20),
        "market_median_ret60": float(candidate.market_median_ret60),
        "market_positive_ret20_share": float(candidate.market_positive_ret20_share),
        "market_positive_ret60_share": float(candidate.market_positive_ret60_share),
        "pre60_position": position,
        "mother_low": float(candidate.coord_low),
        "confirmation_level": float(candidate.prior10_high),
    }


def replay_one(
    candidate: Any, path: pd.DataFrame, window: pd.DataFrame
) -> dict[str, Any]:
    position = pre60_position(window, int(candidate.signal_cal_idx))
    common = base_row(candidate, position)
    if not np.isfinite(position):
        return {**common, "status": "INVALID_PRE60_HISTORY"}
    if position < MIN_PRE60_POSITION:
        return {**common, "status": "REJECTED_BROKEN_LEADER_STRUCTURE"}
    if path.empty:
        return {**common, "status": "MISSING_FUTURE_PATH"}
    lineage = float(candidate.invalid_step_cum)
    mother_low = float(candidate.coord_low)
    platform = float(candidate.prior10_high)
    confirmation = None
    confirmation_pool = path.loc[
        path.cal_idx.gt(candidate.signal_cal_idx)
        & path.cal_idx.le(candidate.signal_cal_idx + CONFIRMATION_SESSIONS)
    ].sort_values("cal_idx", kind="mergesort")
    for row in confirmation_pool.itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {**common, "status": "INVALID_COORDINATE_LINEAGE_BEFORE_CONFIRMATION"}
        if not completed_close_valid(row, lineage):
            continue
        if float(row.coord_close) < mother_low:
            return {**common, "status": "CANCELLED_MOTHER_LOW_FAILED_BEFORE_CONFIRMATION"}
        if float(row.coord_close) > platform:
            confirmation = row
            break
    if confirmation is None:
        return {**common, "status": "NO_DEMAND_CONFIRMATION"}
    confirmation_idx = int(confirmation.cal_idx)
    confirmation_date = pd.Timestamp(confirmation.trade_date)
    entry_pool = path.loc[
        path.cal_idx.gt(confirmation_idx)
        & path.cal_idx.le(confirmation_idx + ENTRY_SEARCH_SESSIONS)
    ].sort_values("cal_idx", kind="mergesort")
    entry = None
    for row in entry_pool.itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                "status": "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY",
                "confirmation_date": confirmation_date,
                "confirmation_cal_idx": confirmation_idx,
            }
        if buyable(row):
            entry = row
            break
    if entry is None:
        return {
            **common,
            "status": "NO_LEGAL_ENTRY_AFTER_CONFIRMATION",
            "confirmation_date": confirmation_date,
            "confirmation_cal_idx": confirmation_idx,
        }
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * (1 + TARGET_RETURN)
    pending_structure_exit = False
    stop_decision_date = pd.NaT
    for row in path.loc[path.cal_idx.gt(entry_idx)].sort_values(
        "cal_idx", kind="mergesort"
    ).itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                "confirmation_date": confirmation_date,
                "confirmation_cal_idx": confirmation_idx,
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "entry_price": entry_price,
            }
        if pending_structure_exit:
            if sellable_open(row):
                return completed_result(
                    common,
                    confirmation,
                    entry,
                    row,
                    float(row.coord_open),
                    "MOTHER_LOW_CLOSE_FAILURE",
                    stop_decision_date,
                )
            continue
        if legal(row) and np.isfinite(float(row.coord_high)) and float(row.coord_high) >= target:
            return completed_result(
                common, confirmation, entry, row, target, "TARGET_10", pd.NaT
            )
        if int(row.cal_idx) >= entry_idx + HORIZON and sellable_open(row):
            return completed_result(
                common,
                confirmation,
                entry,
                row,
                float(row.coord_open),
                "H20_TIME_STOP",
                pd.NaT,
            )
        if completed_close_valid(row, lineage) and float(row.coord_close) < mother_low:
            pending_structure_exit = True
            stop_decision_date = pd.Timestamp(row.trade_date)
    return {
        **common,
        "status": "INCOMPLETE_PATH",
        "confirmation_date": confirmation_date,
        "confirmation_cal_idx": confirmation_idx,
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }


def completed_result(
    common: dict[str, Any],
    confirmation: Any,
    entry: Any,
    exit_row: Any,
    exit_price: float,
    reason: str,
    stop_decision_date: pd.Timestamp,
) -> dict[str, Any]:
    entry_price = float(entry.coord_open)
    gross = exit_price / entry_price - 1
    return {
        **common,
        "status": "COMPLETED",
        "confirmation_date": pd.Timestamp(confirmation.trade_date),
        "confirmation_cal_idx": int(confirmation.cal_idx),
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": int(entry.cal_idx),
        "entry_price": entry_price,
        "stop_decision_date": stop_decision_date,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": reason,
        "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def aggregate(events: pd.DataFrame) -> dict[str, Any]:
    completed = events.loc[events.status.eq("COMPLETED")].copy()
    if completed.empty:
        raise ResearchError("chart-derived rules produced no completed events")
    annual: dict[str, dict[str, Any]] = {}
    for year in range(2014, 2021):
        part = completed.loc[completed.signal_year.eq(year)]
        annual[str(year)] = {
            "completed": int(len(part)),
            "signal_dates": int(part.signal_date.nunique()),
            "symbols": int(part.symbol.nunique()),
            "mean_net_return": float(part.net_return.mean()) if len(part) else None,
            "median_net_return": float(part.net_return.median()) if len(part) else None,
            "positive_rate": float(part.net_return.gt(0).mean()) if len(part) else None,
            "profit_ge_4pct_rate": float(part.net_return.ge(0.04).mean()) if len(part) else None,
            "severe_loss_rate": float(part.net_return.le(-0.10).mean()) if len(part) else None,
        }
    count_gate = all(item["completed"] >= 51 for item in annual.values())
    return_gate = all(
        item["mean_net_return"] is not None and item["mean_net_return"] > 0.04
        for item in annual.values()
    )
    return {
        "parent_candidates": int(len(events)),
        "status_counts": {
            str(key): int(value) for key, value in events.status.value_counts().items()
        },
        "completed": int(len(completed)),
        "signal_dates": int(completed.signal_date.nunique()),
        "symbols": int(completed.symbol.nunique()),
        "mean_net_return": float(completed.net_return.mean()),
        "median_net_return": float(completed.net_return.median()),
        "positive_rate": float(completed.net_return.gt(0).mean()),
        "profit_ge_4pct_rate": float(completed.net_return.ge(0.04).mean()),
        "severe_loss_rate": float(completed.net_return.le(-0.10).mean()),
        "exit_reason_counts": {
            str(key): int(value) for key, value in completed.exit_reason.value_counts().items()
        },
        "annual": annual,
        "annual_count_gate": count_gate,
        "annual_return_gate": return_gate,
        "development_gate_pass": bool(count_gate and return_gate),
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    paths = pd.read_parquet(PATHS)
    windows = pd.read_parquet(
        WINDOWS,
        columns=[
            "event_id",
            "trade_date",
            "cal_idx",
            "coord_high",
            "coord_low",
            "coord_close",
            "current_valid",
            "hard_valid",
        ],
    )
    for column in ("signal_date", "decision_at", "available_at", "market_latest_source_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    windows["trade_date"] = pd.to_datetime(windows["trade_date"])
    if len(candidates) != 1113 or candidates.event_id.duplicated().any():
        raise ResearchError("parent candidate identity drift")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered development evaluation")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("future market state entered candidate set")
    if candidates.market_regime.ne("BULL").any():
        raise ResearchError("non-BULL event entered frozen bull sleeve")
    path_groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    window_groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    rows = [
        replay_one(
            candidate,
            path_groups.get(str(candidate.event_id), pd.DataFrame()),
            window_groups.get(str(candidate.event_id), pd.DataFrame()),
        )
        for candidate in candidates.itertuples(index=False)
    ]
    events = pd.DataFrame(rows).sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(events) != len(candidates) or events.event_id.duplicated().any():
        raise ResearchError("event result identity drift")
    completed = events.loc[events.status.eq("COMPLETED")]
    if completed.entry_date.le(completed.confirmation_date).any():
        raise ResearchError("same-session confirmation fill detected")
    if completed.exit_date.le(completed.entry_date).any():
        raise ResearchError("T+1 exit ordering violated")
    if completed.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal opened")
    write_parquet(events, EVENTS)
    summary = aggregate(events)
    payload = {
        "experiment": EXPERIMENT,
        "parent": PARENT,
        "scientific_status": "CHART_DERIVED_CONSUMED_DEVELOPMENT_EVALUATION",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "events_sha256": sha256(EVENTS),
        "summary": summary,
        "all_1113_charts_reviewed_before_rule_freeze": "YES",
        "chronological_contact_sheets_reviewed": 124,
        "future_market_state_function": "NO",
        "same_session_fill": "NO",
        "post_2020_signal_read": "NO",
        "post_2021_signal_or_outcome_read": "NO",
        "post_2024_read": "NO",
        "open_2022_2024": "YES" if summary["development_gate_pass"] else "NO",
        "next_step": (
            "Open the frozen 2022-2024 validation only because every development gate passed."
            if summary["development_gate_pass"]
            else "Close this exact chart-rule translation without threshold rescue and move to a genuinely different market-explainable mother."
        ),
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
