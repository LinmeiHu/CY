#!/usr/bin/env python3
# ruff: noqa: E501
"""Build an outcome-blind first-investable-reclaim Stage A through 2021 only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-FIRST-INVESTABLE-RECLAIM-V29R4"
DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)
DEVELOPMENT_END = pd.Timestamp("2021-12-31")

PREREG = OS_ROOT / f"experiments/{EXPERIMENT}_preregistration.json"
STAGE_A_FREEZE = OS_ROOT / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}-STAGE-A_report.md"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_first_investable_reclaim_v29r4"
)
STAGE_A_ROOT = EXT_ROOT / "development_stage_a"
DAILY_LINEAGE = STAGE_A_ROOT / "gap_daily_lineage.parquet"
GAP_AUDIT = STAGE_A_ROOT / "gap_selection_audit.parquet"
SELECTED_SIGNALS = STAGE_A_ROOT / "first_investable_reclaim_signals.parquet"

V13_ENTRIES = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_first_reversal_v13/"
    "prior_high_reversal/development/entries.parquet"
)
V13_STAGE_A_FREEZE = (
    OS_ROOT
    / "artifacts/ASHARE-TRUE-GAP-BELOW-L-FIRST-REVERSAL-V13_stage_a_freeze.json"
)
V27_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_fresh_capitulation_snapback_v27/"
    "development/fresh_snapback_selected_entries.parquet"
)
V28_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_liquidity_trap_guard_v28/"
    "development/liquidity_guard_selected_entries.parquet"
)
V28R1_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_demand_not_locked_v28r1/"
    "development/demand_not_locked_selected_entries.parquet"
)
V28R2_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_orderly_demand_v28r2/"
    "development/orderly_demand_selected_entries.parquet"
)

PARENT_FREEZE_BINDINGS = (
    (
        "v27_selected",
        "v27_stage_a_freeze",
        "ASHARE-TRUE-GAP-BELOW-L-FRESH-CAPITULATION-SNAPBACK-V27",
        ("periods", "DEVELOPMENT", "selected_entries_sha256"),
    ),
    (
        "v28_selected",
        "v28_stage_a_freeze",
        "ASHARE-TRUE-GAP-BELOW-L-LIQUIDITY-TRAP-GUARD-V28",
        ("development", "selected_entries_sha256"),
    ),
    (
        "v28r1_selected",
        "v28r1_stage_a_freeze",
        "ASHARE-TRUE-GAP-BELOW-L-DEMAND-NOT-LOCKED-V28R1",
        ("development", "selected_entries_sha256"),
    ),
    (
        "v28r2_selected",
        "v28r2_stage_a_freeze",
        "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2",
        ("development", "selected_entries_sha256"),
    ),
)

REGISTRY = ROOT / "configs/data_asset_registry.json"
CY033_ROOT = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-033-PIT-B-DAILY-2018-20260904-V1"
)

MIN_GAP_AGE = 10
MAX_GAP_AGE = 14
MIN_PRIOR_PEAK_TO_GAP = 20
MIN_MAX_DEPTH = 0.10
MIN_CURRENT_DEPTH = 0.05
MIN_RECOVERY_FROM_LOW20 = 0.03
MIN_REBOUND_FROM_POST_GAP_LOW_OVER_L = 0.05
MIN_LOW20_AGE = 1
MAX_LOW20_AGE = 10
PRIOR_WINDOW = 20
MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS = 1
MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN = 2.0
LIMIT_TOLERANCE_CNY = 0.006

DAILY_COLUMNS = [
    "trade_date",
    "decision_at",
    "decision_timezone",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "trade_status",
    "is_st",
    "up_limit_price",
    "down_limit_price",
    "current_day_data_tradable",
    "industry",
    "corporate_action_count",
    "corporate_action_blocking",
    "share_multiplier",
    "cash_per_share",
    "bar_valid",
    "trading_state_valid",
    "industry_valid",
    "corporate_action_valid",
    "market_rule_valid",
    "hard_valid",
    "available_at",
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "industry_snapshot_id",
    "corporate_action_snapshot_id",
]

class V29R4Error(RuntimeError):
    """Fail closed on chronology, lineage, identity, or source drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def publish_no_replace(staged: Path, target: Path) -> None:
    """Atomically publish one same-filesystem file without overwriting."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise V29R4Error(f"refusing to overwrite existing artifact: {target}")
    os.link(staged, target)
    staged.unlink()


def cy033_path(year: int) -> Path:
    return CY033_ROOT / f"daily/partition_year={year}/data_0.parquet"


def _nonempty(value: Any) -> bool:
    return bool(pd.notna(value) and str(value).strip())


def _finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return bool(math.isfinite(number) and number > 0)


def _price_ticks(value: Any) -> int:
    if not _finite_positive(value):
        return -1
    return math.floor(float(value) * 100.0 + 0.5 + 1e-6)


def _is_true(value: Any) -> bool:
    return bool(pd.notna(value) and bool(value))


def _row_lineage_valid(row: pd.Series, asof: pd.Timestamp) -> bool:
    required_true = (
        "bar_valid",
        "trading_state_valid",
        "industry_valid",
        "corporate_action_valid",
        "market_rule_valid",
        "hard_valid",
    )
    if not all(_is_true(row.get(column)) for column in required_true):
        return False
    if str(row.get("decision_timezone", "")) != "Asia/Shanghai":
        return False
    if not all(
        _nonempty(row.get(column))
        for column in (
            "snapshot_id",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "corporate_action_snapshot_id",
        )
    ):
        return False
    available_at = pd.to_datetime(row.get("available_at"), errors="coerce")
    decision_at = pd.to_datetime(row.get("decision_at"), errors="coerce")
    return bool(
        pd.notna(available_at)
        and pd.notna(decision_at)
        and available_at <= decision_at
        and available_at <= asof
        and decision_at <= asof
    )


def _action_free(row: pd.Series) -> bool:
    count = pd.to_numeric(
        pd.Series([row.get("corporate_action_count")]), errors="coerce"
    ).iloc[0]
    multiplier = pd.to_numeric(
        pd.Series([row.get("share_multiplier")]), errors="coerce"
    ).iloc[0]
    cash = pd.to_numeric(
        pd.Series([row.get("cash_per_share")]), errors="coerce"
    ).iloc[0]
    blocking = row.get("corporate_action_blocking")
    return bool(
        pd.notna(count)
        and float(count) == 0.0
        and pd.notna(blocking)
        and not bool(blocking)
        and pd.notna(multiplier)
        and abs(float(multiplier) - 1.0) <= 1e-12
        and pd.notna(cash)
        and abs(float(cash)) <= 1e-12
    )


def _one_price_limit_down(row: pd.Series) -> bool:
    values = [row.get(column) for column in ("open", "high", "low", "close")]
    limit = row.get("down_limit_price")
    if not _finite_positive(limit) or not all(_finite_positive(value) for value in values):
        return False
    return bool(
        all(
            math.isclose(float(value), float(limit), rel_tol=0.0, abs_tol=LIMIT_TOLERANCE_CNY)
            for value in values
        )
    )


def _history_lineage_valid(frame: pd.DataFrame, asof: pd.Timestamp) -> bool:
    if frame.empty:
        return False
    return all(_row_lineage_valid(row, asof) for _, row in frame.iterrows())


def _amount_feature(
    group: pd.DataFrame,
    current_index: int,
    signal_time: pd.Timestamp,
) -> tuple[dict[str, Any], list[int]]:
    before = group.iloc[:current_index]
    traded = before.loc[before.trade_status.eq(1)].tail(PRIOR_WINDOW)
    used_indices = list(traded.index.astype(int))
    unknown_between = 0
    between = pd.DataFrame()
    if len(traded) == PRIOR_WINDOW:
        start_date = traded.trade_date.iloc[0]
        between = before.loc[before.trade_date.ge(start_date)]
        used_indices = sorted(set(used_indices) | set(between.index.astype(int)))
        unknown_between = int((~between.trade_status.isin([0, 1])).sum())
    amounts = pd.to_numeric(traded.amount, errors="coerce")
    complete = bool(
        len(traded) == PRIOR_WINDOW
        and unknown_between == 0
        and _history_lineage_valid(traded, signal_time)
        and _history_lineage_valid(between, signal_time)
        and np.isfinite(amounts.to_numpy(dtype=float)).all()
        and amounts.gt(0).all()
    )
    median = float(amounts.median()) if complete else math.nan
    return (
        {
            "prior20_completed_trading_sessions": len(traded),
            "prior20_unknown_trading_state_rows": unknown_between,
            "prior20_amount_history_complete": complete,
            "prior20_median_amount": median,
        },
        used_indices,
    )


def evaluate_signal_bar(
    gap: pd.Series,
    group: pd.DataFrame,
    gap_index: int,
    current_index: int,
) -> tuple[dict[str, Any], dict[str, list[int]]]:
    current = group.loc[current_index]
    previous = group.loc[current_index - 1]
    signal_time = pd.Timestamp(current.decision_at)
    path = group.loc[gap_index + 1 : current_index]
    rolling20 = group.loc[current_index - 19 : current_index]
    prior20 = group.loc[current_index - PRIOR_WINDOW : current_index - 1]
    roles = {
        "V13_ROLLING20": list(rolling20.index.astype(int)),
        "V28_PRIOR20_LIMIT": list(prior20.index.astype(int)),
    }
    amount_feature, amount_indices = _amount_feature(group, current_index, signal_time)
    roles["V28R2_PRIOR20_AMOUNT"] = amount_indices

    raw_l = float(gap.L) / float(gap.coordinate_factor)
    path_lows = pd.to_numeric(path.low, errors="coerce")
    rolling_lows = pd.to_numeric(rolling20.low, errors="coerce")
    coordinate_action_free = bool(
        all(_action_free(row) for _, row in rolling20.iterrows())
        and all(_action_free(row) for _, row in path.iterrows())
    )
    prices_complete = bool(
        len(rolling20) == PRIOR_WINDOW
        and np.isfinite(path_lows.to_numpy(dtype=float)).all()
        and path_lows.gt(0).all()
        and np.isfinite(rolling_lows.to_numpy(dtype=float)).all()
        and rolling_lows.gt(0).all()
        and _finite_positive(current.close)
        and _finite_positive(previous.high)
        and _history_lineage_valid(rolling20, signal_time)
        and coordinate_action_free
    )
    max_depth = (
        1.0 - float(path_lows.min()) / raw_l
        if prices_complete
        else math.nan
    )
    current_depth = (
        1.0 - float(current.close) / raw_l
        if prices_complete
        else math.nan
    )
    if prices_complete:
        rolling_low_ticks = np.asarray(
            [_price_ticks(value) for value in rolling_lows], dtype=np.int64
        )
        lowest_tick = int(rolling_low_ticks.min())
        low20_offset = int(np.flatnonzero(rolling_low_ticks == lowest_tick)[-1])
        low20_raw = float(rolling_lows.iloc[low20_offset])
    else:
        low20_offset = -1
        low20_raw = math.nan
    days_since_low20 = (
        len(rolling20) - 1 - low20_offset
        if prices_complete
        else -1
    )
    recovery = (
        float(current.close) / low20_raw - 1.0
        if prices_complete
        else math.nan
    )
    rebound = max_depth - current_depth if prices_complete else math.nan

    current_lineage = _row_lineage_valid(current, signal_time)
    current_state = bool(
        current_lineage
        and _is_true(current.current_day_data_tradable)
        and float(current.trade_status) == 1.0
        and current.is_st is not pd.NA
        and pd.notna(current.is_st)
        and not bool(current.is_st)
        and _action_free(current)
    )
    prior_high_raw_tick_break = bool(
        _price_ticks(current.close) > _price_ticks(previous.high)
    )
    v13_gate = bool(
        prices_complete
        and max_depth >= MIN_MAX_DEPTH
        and current_depth >= MIN_CURRENT_DEPTH
        and MIN_LOW20_AGE <= days_since_low20 <= MAX_LOW20_AGE
        and recovery >= MIN_RECOVERY_FROM_LOW20
        and prior_high_raw_tick_break
    )
    v27_gate = bool(
        v13_gate
        and int(gap.pre_peak_to_gap_sessions) >= MIN_PRIOR_PEAK_TO_GAP
        and int(current_index - gap_index) <= MAX_GAP_AGE
        and rebound >= MIN_REBOUND_FROM_POST_GAP_LOW_OVER_L
    )
    prior_limit_history_valid = bool(
        len(prior20) == PRIOR_WINDOW and _history_lineage_valid(prior20, signal_time)
    )
    prior_limit_count = (
        int(sum(_one_price_limit_down(row) for _, row in prior20.iterrows()))
        if prior_limit_history_valid
        else -1
    )
    v28_gate = bool(
        v27_gate
        and current_state
        and prior_limit_history_valid
        and prior_limit_count <= MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS
    )
    unlocked_gate = bool(
        v28_gate
        and _finite_positive(current.up_limit_price)
        and float(current.close) < float(current.up_limit_price) - LIMIT_TOLERANCE_CNY
    )
    signal_amount = pd.to_numeric(pd.Series([current.amount]), errors="coerce").iloc[0]
    amount_ratio = (
        float(signal_amount) / float(amount_feature["prior20_median_amount"])
        if unlocked_gate
        and _finite_positive(signal_amount)
        and bool(amount_feature["prior20_amount_history_complete"])
        and _finite_positive(amount_feature["prior20_median_amount"])
        else math.nan
    )
    orderly_gate = bool(
        unlocked_gate
        and _finite_positive(signal_amount)
        and bool(amount_feature["prior20_amount_history_complete"])
        and math.isfinite(amount_ratio)
        and amount_ratio <= MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN
    )
    record = {
        "gap_age": int(current_index - gap_index),
        "signal_date": pd.Timestamp(current.trade_date).normalize(),
        "signal_time": signal_time,
        "max_depth": max_depth,
        "current_depth": current_depth,
        "rebound_from_post_gap_low_over_l": rebound,
        "days_since_low20": days_since_low20,
        "low20_raw": low20_raw,
        "recovery_from_low20": recovery,
        "coordinate_window_action_free": coordinate_action_free,
        "prior_high_raw_tick_break": prior_high_raw_tick_break,
        "v13_trigger_identity_source": "CY033_ACTION_FREE_RAW_TICK_REARM",
        "v13_prior_high_reversal_gate": v13_gate,
        "v27_final_gate": v27_gate,
        "prior20_one_price_limit_down_count": prior_limit_count,
        "v28_prior20_history_valid": prior_limit_history_valid,
        "v28_state_gate": v28_gate,
        "v28r1_not_locked_gate": unlocked_gate,
        "signal_raw_close": float(current.close) if _finite_positive(current.close) else math.nan,
        "signal_up_limit_price": float(current.up_limit_price) if _finite_positive(current.up_limit_price) else math.nan,
        "signal_raw_amount": float(signal_amount) if _finite_positive(signal_amount) else math.nan,
        **amount_feature,
        "signal_amount_to_prior20_median": amount_ratio,
        "v28r2_orderly_amount_gate": orderly_gate,
        "first_investable_reclaim_gate": orderly_gate,
        "signal_industry": current.industry,
        "signal_available_at": current.available_at,
        "signal_decision_at": current.decision_at,
        "signal_snapshot_id": current.snapshot_id,
        "signal_daily_snapshot_id": current.daily_snapshot_id,
        "signal_trading_state_snapshot_id": current.trading_state_snapshot_id,
        "signal_industry_snapshot_id": current.industry_snapshot_id,
        "signal_corporate_action_snapshot_id": current.corporate_action_snapshot_id,
        "signal_feature_uses_post_signal_information": False,
    }
    return record, roles


def select_first_investable_for_gap(
    gap: pd.Series,
    symbol_daily: pd.DataFrame,
) -> tuple[dict[str, Any] | None, dict[str, Any], pd.DataFrame]:
    """Return the first completed bar satisfying the final composite signal."""
    group = symbol_daily.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    group.index = np.arange(len(group), dtype=int)
    gap_date = pd.Timestamp(gap.gap_date).normalize()
    audit: dict[str, Any] = {
        "gap_id": str(gap.gap_id),
        "symbol": str(gap.symbol),
        "gap_date": gap_date,
        "old_signal_date": pd.Timestamp(gap.signal_date).normalize(),
        "selected": False,
        "selection_status": "NO_FINAL_QUALITY_RECLAIM",
        "selection_failure_class": "NO_FINAL_QUALITY_RECLAIM",
        "bars_scanned": 0,
        "v13_trigger_bars": 0,
        "v27_gate_bars": 0,
        "v28_gate_bars": 0,
        "unlocked_gate_bars": 0,
        "orderly_gate_bars": 0,
        "coordinate_action_barrier_bars": 0,
        "old_signal_coordinate_window_action_free": None,
        "old_signal_prior_high_raw_tick_break": None,
        "old_signal_uniform_final_gate": None,
    }
    accessed: dict[int, set[str]] = defaultdict(set)

    if gap_date < pd.Timestamp("2018-01-01"):
        audit["selection_status"] = "GAP_BEFORE_CY033_BOUND"
        audit["selection_failure_class"] = "REGISTERED_COVERAGE_BOUND"
        return None, audit, pd.DataFrame()
    matches = group.index[group.trade_date.eq(gap_date)].tolist()
    if len(matches) != 1:
        audit["selection_status"] = "MISSING_OR_DUPLICATE_GAP_DATE"
        audit["selection_failure_class"] = "REGISTERED_LINEAGE_INVALID"
        return None, audit, pd.DataFrame()
    gap_index = int(matches[0])
    accessed[gap_index].add("GAP_IDENTITY")
    gap_row = group.loc[gap_index]
    gap_asof = pd.Timestamp(gap_row.decision_at)
    raw_l = float(gap.L) / float(gap.coordinate_factor)
    if not _row_lineage_valid(gap_row, gap_asof):
        audit["selection_status"] = "GAP_REGISTERED_LINEAGE_INVALID"
        audit["selection_failure_class"] = "REGISTERED_LINEAGE_INVALID"
        lineage = _lineage_frame(gap, group, accessed)
        return None, audit, lineage
    if not _action_free(gap_row):
        audit["selection_status"] = "GAP_ACTION_COORDINATE_BARRIER"
        audit["selection_failure_class"] = "ACTION_COORDINATE_BARRIER"
        lineage = _lineage_frame(gap, group, accessed)
        return None, audit, lineage
    if _price_ticks(gap_row.high) != _price_ticks(raw_l):
        audit["selection_status"] = "GAP_RAW_IDENTITY_MISMATCH"
        audit["selection_failure_class"] = "FROZEN_GAP_IDENTITY_MISMATCH"
        lineage = _lineage_frame(gap, group, accessed)
        return None, audit, lineage
    if int(gap.pre_peak_to_gap_sessions) < MIN_PRIOR_PEAK_TO_GAP:
        audit["selection_status"] = "M20_FAILED"
        audit["selection_failure_class"] = "M20"
        lineage = _lineage_frame(gap, group, accessed)
        return None, audit, lineage

    selected: dict[str, Any] | None = None
    for current_index in range(gap_index + 1, min(len(group), gap_index + MAX_GAP_AGE + 1)):
        current = group.loc[current_index]
        accessed[current_index].add("POST_GAP_PATH")
        audit["bars_scanned"] += 1
        current_asof = pd.Timestamp(current.decision_at)
        if not _row_lineage_valid(current, current_asof):
            audit["selection_status"] = "PATH_REGISTERED_LINEAGE_BREAK"
            audit["selection_failure_class"] = "REGISTERED_LINEAGE_INVALID"
            break
        if not _action_free(current):
            audit["selection_status"] = "PATH_ACTION_COORDINATE_BARRIER"
            audit["selection_failure_class"] = "ACTION_COORDINATE_BARRIER"
            break
        if _price_ticks(current.high) >= _price_ticks(raw_l):
            audit["selection_status"] = "L_TOUCHED_BEFORE_FINAL_RECLAIM"
            audit["selection_failure_class"] = "L_TOUCH"
            break
        gap_age = current_index - gap_index
        if gap_age < MIN_GAP_AGE or current_index < PRIOR_WINDOW:
            continue
        record, roles = evaluate_signal_bar(gap, group, gap_index, current_index)
        if (
            pd.Timestamp(current.trade_date).normalize()
            == pd.Timestamp(gap.signal_date).normalize()
        ):
            audit["old_signal_coordinate_window_action_free"] = record[
                "coordinate_window_action_free"
            ]
            audit["old_signal_prior_high_raw_tick_break"] = record[
                "prior_high_raw_tick_break"
            ]
            audit["old_signal_uniform_final_gate"] = record[
                "first_investable_reclaim_gate"
            ]
        for role, indices in roles.items():
            for index in indices:
                accessed[int(index)].add(role)
        for counter, gate in (
            (
                "coordinate_action_barrier_bars",
                not record["coordinate_window_action_free"],
            ),
            ("v13_trigger_bars", record["v13_prior_high_reversal_gate"]),
            ("v27_gate_bars", record["v27_final_gate"]),
            ("v28_gate_bars", record["v28_state_gate"]),
            ("unlocked_gate_bars", record["v28r1_not_locked_gate"]),
            ("orderly_gate_bars", record["v28r2_orderly_amount_gate"]),
        ):
            audit[counter] += int(bool(gate))
        if record["first_investable_reclaim_gate"]:
            selected = {
                **gap.to_dict(),
                **record,
                "old_signal_date": pd.Timestamp(gap.signal_date).normalize(),
                "old_signal_time": pd.Timestamp(gap.signal_time),
                "signal_is_later_than_old_first_reversal": bool(
                    pd.Timestamp(record["signal_time"]) > pd.Timestamp(gap.signal_time)
                ),
            }
            audit["selected"] = True
            audit["selection_status"] = "SELECTED_FIRST_FINAL_QUALITY_RECLAIM"
            audit["selection_failure_class"] = "NONE"
            audit["new_signal_date"] = record["signal_date"]
            audit["new_signal_lag_sessions"] = int(
                record["gap_age"] - int(gap.gap_age)
            )
            break

    if (
        selected is None
        and audit["selection_failure_class"] == "NO_FINAL_QUALITY_RECLAIM"
        and audit["coordinate_action_barrier_bars"] > 0
    ):
        audit["selection_failure_class"] = "ACTION_COORDINATE_BARRIER"
    lineage = _lineage_frame(gap, group, accessed)
    return selected, audit, lineage


def _lineage_frame(
    gap: pd.Series,
    group: pd.DataFrame,
    accessed: dict[int, set[str]],
) -> pd.DataFrame:
    if not accessed:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for index in sorted(accessed):
        row = group.loc[index]
        rows.append(
            {
                "gap_id": str(gap.gap_id),
                "symbol": str(gap.symbol),
                "source_trade_date": pd.Timestamp(row.trade_date).normalize(),
                "lineage_roles": "|".join(sorted(accessed[index])),
                **{column: row.get(column) for column in DAILY_COLUMNS if column != "symbol"},
            }
        )
    return pd.DataFrame.from_records(rows)


def attach_recovery_audit(
    audit: pd.DataFrame,
    selected: pd.DataFrame,
    parent: pd.DataFrame,
    old_stage_ids: dict[str, set[str]],
) -> pd.DataFrame:
    result = audit.copy()
    parent_by_id = parent.set_index(parent.gap_id.astype(str), drop=False)
    selected_ids = set(selected.gap_id.astype(str)) if not selected.empty else set()
    classifications: list[dict[str, Any]] = []
    for gap_id in result.gap_id.astype(str):
        old = parent_by_id.loc[gap_id]
        audit_row = result.loc[result.gap_id.astype(str).eq(gap_id)].iloc[0]
        old_m20 = bool(int(old.pre_peak_to_gap_sessions) >= MIN_PRIOR_PEAK_TO_GAP)
        old_f14 = bool(int(old.gap_age) <= MAX_GAP_AGE)
        old_r5 = bool(float(old.max_depth) - float(old.current_depth) >= MIN_REBOUND_FROM_POST_GAP_LOW_OVER_L)
        if gap_id not in old_stage_ids["v27"]:
            failures = [
                name
                for name, passed in (("M20", old_m20), ("F14", old_f14), ("R5", old_r5))
                if not passed
            ]
            old_first_failure = "+".join(failures) if failures else "V27_IDENTITY_OTHER"
        elif gap_id not in old_stage_ids["v28"]:
            old_first_failure = "V28_LIQUIDITY_OR_ST"
        elif gap_id not in old_stage_ids["v28r1"]:
            old_first_failure = "V28R1_LOCKED_UP_LIMIT"
        elif gap_id not in old_stage_ids["v28r2"]:
            old_first_failure = "V28R2_AMOUNT_GT_2X"
        else:
            old_first_failure = "OLD_V28R2_RETAINED"
        if gap_id not in old_stage_ids["v28r2"]:
            old_v28r2_retention_status = "NOT_IN_OLD_V28R2"
        elif gap_id in selected_ids:
            old_v28r2_retention_status = "OLD_SIGNAL_RETAINED"
        elif audit_row.get("selection_failure_class") == "REGISTERED_LINEAGE_INVALID":
            old_v28r2_retention_status = (
                "OLD_SIGNAL_DROPPED_FOR_LATENT_LINEAGE_DEFECT"
            )
        elif audit_row.get("selection_failure_class") == "ACTION_COORDINATE_BARRIER":
            old_v28r2_retention_status = (
                "OLD_SIGNAL_DROPPED_FOR_CROSS_ACTION_COORDINATE_DEFECT"
            )
        elif (
            audit_row.get("selection_failure_class") == "L_TOUCH"
            or audit_row.get("old_signal_prior_high_raw_tick_break") is False
        ):
            old_v28r2_retention_status = (
                "OLD_SIGNAL_DROPPED_FOR_UNIFORM_RAW_TICK_REPRODUCTION"
            )
        else:
            old_v28r2_retention_status = "OLD_SIGNAL_MISSING_SEMANTIC_DIVERGENCE"
        classifications.append(
            {
                "gap_id": gap_id,
                "old_m20_gate": old_m20,
                "old_f14_gate": old_f14,
                "old_r5_gate": old_r5,
                "old_v27_selected": gap_id in old_stage_ids["v27"],
                "old_v28_selected": gap_id in old_stage_ids["v28"],
                "old_v28r1_selected": gap_id in old_stage_ids["v28r1"],
                "old_v28r2_selected": gap_id in old_stage_ids["v28r2"],
                "old_first_failure": old_first_failure,
                "new_signal_selected": gap_id in selected_ids,
                "recovered_beyond_old_v28r2": (
                    gap_id in selected_ids and gap_id not in old_stage_ids["v28r2"]
                ),
                "old_v28r2_retention_status": old_v28r2_retention_status,
            }
        )
    return result.merge(
        pd.DataFrame.from_records(classifications),
        on="gap_id",
        how="left",
        validate="one_to_one",
    )


def load_parent() -> pd.DataFrame:
    columns = [
        "gap_id",
        "symbol",
        "board",
        "gap_date",
        "cal_idx",
        "gap_seq",
        "invalid_step_cum",
        "coordinate_factor",
        "L",
        "U",
        "W",
        "gap_width_pct",
        "pre_gap_inside_touch_sessions",
        "pre_gap_corridor_touch_sessions",
        "pre_peak_to_gap_sessions",
        "pre_gap_drawdown_from_120d_peak",
        "signal_date",
        "signal_time",
        "gap_age",
        "max_depth",
        "current_depth",
    ]
    projected = ",".join(f'"{column}"' for column in columns)
    with duckdb.connect() as con:
        frame = con.execute(
            f"""
            SELECT {projected}
            FROM read_parquet(?)
            WHERE signal_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
            """,
            [str(V13_ENTRIES)],
        ).fetchdf()
    for column in ("gap_date", "signal_date", "signal_time"):
        frame[column] = pd.to_datetime(frame[column])
    frame = frame.sort_values(["gap_date", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if len(frame) != 850 or frame.empty or frame.gap_id.duplicated().any():
        raise V29R4Error("frozen V13 2018-2021 gap identity mismatch")
    if not frame.board.isin(["MAIN", "CHINEXT"]).all():
        raise V29R4Error("unexpected board in frozen V13 parent")
    return frame


def load_old_stage_ids() -> dict[str, set[str]]:
    paths = {
        "v27": V27_SELECTED,
        "v28": V28_SELECTED,
        "v28r1": V28R1_SELECTED,
        "v28r2": V28R2_SELECTED,
    }
    result: dict[str, set[str]] = {}
    for name, path in paths.items():
        with duckdb.connect() as con:
            frame = con.execute(
                """
                SELECT gap_id,signal_date
                FROM read_parquet(?)
                WHERE signal_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
                """,
                [str(path)],
            ).fetchdf()
        frame["signal_date"] = pd.to_datetime(frame.signal_date)
        if frame.gap_id.duplicated().any():
            raise V29R4Error(f"duplicate gap identity in {name}")
        result[name] = set(frame.gap_id.astype(str))
    return result


def load_cy033(symbols: list[str]) -> pd.DataFrame:
    symbol_frame = pd.DataFrame({"symbol": sorted(set(symbols))})
    paths = [str(cy033_path(year)) for year in DEVELOPMENT_YEARS]
    con = duckdb.connect()
    con.register("wanted_symbols", symbol_frame)
    columns = ",".join(f"d.{column}" for column in DAILY_COLUMNS)
    frame = con.execute(
        f"""
        SELECT {columns}
        FROM read_parquet(?, union_by_name=true) d
        JOIN wanted_symbols s USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
        ORDER BY d.symbol,d.trade_date
        """,
        [paths],
    ).fetchdf()
    con.close()
    for column in ("trade_date", "decision_at", "available_at"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.duplicated(["symbol", "trade_date"]).any():
        raise V29R4Error("CY033 selected-symbol slice identity failure")
    if frame.trade_date.max() > DEVELOPMENT_END:
        raise V29R4Error("post-2021 CY033 row opened")
    return frame


def _registry_asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any]:
    matches = [item for item in registry.get("assets", []) if item.get("asset_id") == asset_id]
    if len(matches) != 1:
        raise V29R4Error(f"{asset_id} must resolve exactly once in registry")
    return matches[0]


def verify_sources(prereg: dict[str, Any]) -> dict[str, str]:
    if prereg.get("experiment") != EXPERIMENT or prereg.get("stage") != "DEVELOPMENT_STAGE_A_ONLY":
        raise V29R4Error("wrong or non-Stage-A preregistration")
    if prereg.get("development") != ["2018-01-01", "2021-12-31"]:
        raise V29R4Error("preregistration development boundary drift")
    expected_runner = prereg.get("runner_sha256")
    if not expected_runner or sha256(Path(__file__)) != expected_runner:
        raise V29R4Error("runner hash differs from preregistration")
    source_identity = prereg["source_identity"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    cy033_asset = _registry_asset(registry, "CY-033")
    if normalized_json_sha256(cy033_asset) != source_identity["cy033"]["registry_asset_normalized_sha256"]:
        raise V29R4Error("CY033 registry identity drift")
    cy033_lineage = cy033_asset.get("lineage", {})
    expected_manifest = CY033_ROOT / "asset_manifest.json"
    if (
        cy033_asset.get("status") != "RESEARCH_CONDITIONAL"
        or cy033_asset.get("physical_state") != "MATERIALIZED"
        or Path(str(cy033_asset.get("location"))) != CY033_ROOT
        or cy033_lineage.get("record_available_at") is not True
        or cy033_lineage.get("record_snapshot_id") is not True
        or Path(str(cy033_lineage.get("manifest_path", ""))) != expected_manifest
    ):
        raise V29R4Error("CY033 registry state not authorized for bounded research")

    verified: dict[str, str] = {
        "preregistration": sha256(PREREG),
        "runner": sha256(Path(__file__)),
    }
    for name, value in source_identity["parent_artifacts"].items():
        path = Path(value["path"])
        if not path.is_file() or sha256(path) != value["sha256"]:
            raise V29R4Error(f"parent artifact drift: {name}")
        verified[name] = value["sha256"]

    for selected_name, freeze_name, experiment, hash_path in PARENT_FREEZE_BINDINGS:
        selected_identity = source_identity["parent_artifacts"].get(selected_name)
        freeze_identity = source_identity["parent_artifacts"].get(freeze_name)
        if selected_identity is None or freeze_identity is None:
            raise V29R4Error(f"incomplete parent freeze binding: {selected_name}")
        freeze_payload = json.loads(
            Path(freeze_identity["path"]).read_text(encoding="utf-8")
        )
        if freeze_payload.get("experiment") != experiment:
            raise V29R4Error(f"wrong parent freeze experiment: {freeze_name}")
        frozen_selected_hash: Any = freeze_payload
        for key in hash_path:
            if not isinstance(frozen_selected_hash, dict) or key not in frozen_selected_hash:
                raise V29R4Error(f"parent freeze lacks selected hash: {freeze_name}")
            frozen_selected_hash = frozen_selected_hash[key]
        if frozen_selected_hash != selected_identity["sha256"]:
            raise V29R4Error(
                f"selected parquet is not the claimed frozen parent output: {selected_name}"
            )

    cy033_manifest = Path(str(cy033_lineage.get("manifest_path", "")))
    if not cy033_manifest.is_file() or sha256(cy033_manifest) != source_identity["cy033"]["manifest_sha256"]:
        raise V29R4Error("CY033 manifest drift")
    manifest = json.loads(cy033_manifest.read_text(encoding="utf-8"))
    if manifest.get("asset_id") != "CY-033" or manifest.get("status") != "PASS":
        raise V29R4Error("CY033 manifest identity or status failed")
    listed = {item.get("path"): item for item in manifest.get("files", [])}
    for year in DEVELOPMENT_YEARS:
        expected = source_identity["cy033"]["partitions"][str(year)]
        path = cy033_path(year)
        relative = str(path.relative_to(CY033_ROOT))
        if listed.get(relative, {}).get("sha256") != expected["sha256"]:
            raise V29R4Error(f"CY033 manifest partition mismatch: {year}")
        if not path.is_file() or path.stat().st_size != expected["size"] or sha256(path) != expected["sha256"]:
            raise V29R4Error(f"CY033 partition drift: {year}")
        verified[f"cy033_{year}"] = expected["sha256"]

    return verified


def audit_parent_daily_binding(
    parent: pd.DataFrame,
    daily: pd.DataFrame,
) -> dict[str, Any]:
    groups = {
        str(symbol): group.set_index("trade_date", drop=False)
        for symbol, group in daily.groupby("symbol", sort=False)
    }
    gap_in_scope = 0
    gap_bound = 0
    gap_raw_tick_identity = 0
    signal_bound = 0
    signal_decision_match = 0
    signal_lineage_valid = 0
    for gap in parent.itertuples(index=False):
        group = groups.get(str(gap.symbol))
        gap_date = pd.Timestamp(gap.gap_date).normalize()
        signal_date = pd.Timestamp(gap.signal_date).normalize()
        if gap_date >= pd.Timestamp("2018-01-01"):
            gap_in_scope += 1
            gap_rows = pd.DataFrame() if group is None else group.loc[[gap_date]] if gap_date in group.index else pd.DataFrame()
            if len(gap_rows) == 1:
                gap_bound += 1
                gap_row = gap_rows.iloc[0]
                raw_l = float(gap.L) / float(gap.coordinate_factor)
                gap_raw_tick_identity += int(
                    _price_ticks(gap_row.high) == _price_ticks(raw_l)
                )
        signal_rows = pd.DataFrame() if group is None else group.loc[[signal_date]] if signal_date in group.index else pd.DataFrame()
        if len(signal_rows) != 1:
            continue
        signal_bound += 1
        signal_row = signal_rows.iloc[0]
        signal_time = pd.Timestamp(gap.signal_time)
        signal_decision_match += int(pd.Timestamp(signal_row.decision_at) == signal_time)
        signal_lineage_valid += int(_row_lineage_valid(signal_row, signal_time))
    return {
        "parent_rows": len(parent),
        "gap_rows_in_cy033_scope": gap_in_scope,
        "gap_rows_bound_one_to_one": gap_bound,
        "gap_raw_tick_identity_matches": gap_raw_tick_identity,
        "signal_rows_bound_one_to_one": signal_bound,
        "signal_decision_timestamp_matches": signal_decision_match,
        "signal_lineage_valid": signal_lineage_valid,
        "post_2021_daily_rows": int(daily.trade_date.gt(DEVELOPMENT_END).sum()),
    }


def build_signal_cohort(
    parent: pd.DataFrame,
    daily: pd.DataFrame,
    old_stage_ids: dict[str, set[str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    groups = {
        str(symbol): group.reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }
    selected_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    lineage_frames: list[pd.DataFrame] = []
    for gap in parent.itertuples(index=False):
        group = groups.get(str(gap.symbol))
        if group is None:
            audit_rows.append(
                {
                    "gap_id": str(gap.gap_id),
                    "symbol": str(gap.symbol),
                    "gap_date": pd.Timestamp(gap.gap_date),
                    "old_signal_date": pd.Timestamp(gap.signal_date),
                    "selected": False,
                    "selection_status": "SYMBOL_ABSENT_FROM_CY033",
                    "selection_failure_class": "REGISTERED_LINEAGE_INVALID",
                }
            )
            continue
        selected, audit, lineage = select_first_investable_for_gap(
            pd.Series(gap._asdict()), group
        )
        audit_rows.append(audit)
        if selected is not None:
            selected_rows.append(selected)
        if not lineage.empty:
            lineage_frames.append(lineage)
    selected_frame = pd.DataFrame.from_records(selected_rows)
    if selected_frame.empty or selected_frame.gap_id.duplicated().any():
        raise V29R4Error("first-investable-reclaim signal identity failure")
    selected_frame = selected_frame.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    if pd.to_datetime(selected_frame.signal_date).gt(DEVELOPMENT_END).any():
        raise V29R4Error("post-2021 signal row opened")
    audit_frame = attach_recovery_audit(
        pd.DataFrame.from_records(audit_rows),
        selected_frame,
        parent,
        old_stage_ids,
    )
    lineage_frame = pd.concat(lineage_frames, ignore_index=True)
    if lineage_frame.empty or lineage_frame.duplicated(
        ["gap_id", "source_trade_date"]
    ).any():
        raise V29R4Error("daily lineage identity failure")
    if pd.to_datetime(lineage_frame.source_trade_date).gt(DEVELOPMENT_END).any():
        raise V29R4Error("post-2021 daily lineage row opened")
    return selected_frame, audit_frame, lineage_frame


def summarize(
    parent: pd.DataFrame,
    selected: pd.DataFrame,
    audit: pd.DataFrame,
    lineage: pd.DataFrame,
    old_stage_ids: dict[str, set[str]],
    parent_binding: dict[str, Any],
) -> dict[str, Any]:
    selected_year = pd.to_datetime(selected.signal_date).dt.year
    by_year: dict[str, Any] = {}
    for year in DEVELOPMENT_YEARS:
        signal_mask = selected_year.eq(year)
        by_year[str(year)] = {
            "parent_gaps": int(pd.to_datetime(parent.signal_date).dt.year.eq(year).sum()),
            "selected_signals": int(signal_mask.sum()),
            "selected_signal_dates": int(selected.loc[signal_mask, "signal_date"].nunique()),
            "later_than_old_first_reversal": int(
                selected.loc[signal_mask, "signal_is_later_than_old_first_reversal"].sum()
            ),
        }
    recovered = audit.loc[audit.recovered_beyond_old_v28r2.eq(True)]
    recovered_by_source = recovered.old_first_failure.value_counts().astype(int).to_dict()
    old_ids = old_stage_ids["v28r2"]
    new_ids = set(selected.gap_id.astype(str))
    missing_old = sorted(old_ids - new_ids)
    retention = audit.old_v28r2_retention_status.value_counts().astype(int).to_dict()
    reproducible_old = set(
        audit.loc[
            audit.old_v28r2_selected.eq(True)
            & audit.old_signal_uniform_final_gate.eq(True),
            "gap_id",
        ].astype(str)
    )
    missing_reproducible = sorted(reproducible_old - new_ids)
    permitted_drop_statuses = {
        "OLD_SIGNAL_DROPPED_FOR_LATENT_LINEAGE_DEFECT",
        "OLD_SIGNAL_DROPPED_FOR_CROSS_ACTION_COORDINATE_DEFECT",
        "OLD_SIGNAL_DROPPED_FOR_UNIFORM_RAW_TICK_REPRODUCTION",
    }
    unexplained_old_missing = sorted(
        audit.loc[
            audit.gap_id.astype(str).isin(missing_old)
            & ~audit.old_v28r2_retention_status.isin(permitted_drop_statuses),
            "gap_id",
        ].astype(str)
    )
    return {
        "parent_gaps": len(parent),
        "selected_signals": len(selected),
        "selected_signal_dates": int(selected.signal_date.nunique()),
        "later_than_old_first_reversal": int(selected.signal_is_later_than_old_first_reversal.sum()),
        "by_signal_year": by_year,
        "old_v28r2_signals": len(old_ids),
        "old_v28r2_missing_from_new": len(missing_old),
        "old_v28r2_missing_gap_ids": missing_old,
        "old_v28r2_retention_status": retention,
        "uniform_rule_reproducible_old_v28r2": len(reproducible_old),
        "uniform_rule_reproducible_old_missing_from_new": len(missing_reproducible),
        "uniform_rule_reproducible_old_missing_gap_ids": missing_reproducible,
        "unexplained_old_v28r2_missing": len(unexplained_old_missing),
        "unexplained_old_v28r2_missing_gap_ids": unexplained_old_missing,
        "recovered_beyond_old_v28r2": len(recovered),
        "recovered_by_old_first_failure": recovered_by_source,
        "gap_selection_status": audit.selection_status.value_counts().astype(int).to_dict(),
        "lineage_rows": len(lineage),
        "lineage_missing_snapshot_id": int((~lineage.snapshot_id.map(_nonempty)).sum()),
        "lineage_missing_daily_snapshot_id": int((~lineage.daily_snapshot_id.map(_nonempty)).sum()),
        "lineage_missing_industry_snapshot_id": int((~lineage.industry_snapshot_id.map(_nonempty)).sum()),
        "post_2021_signal_count": int(pd.to_datetime(selected.signal_date).gt(DEVELOPMENT_END).sum()),
        "parent_daily_binding": parent_binding,
        "execution_identity_status": "NOT_CONSTRUCTED_IN_DAILY_STAGE_A",
        "execution_count": None,
        "execution_blocker": (
            "Requires a separately preregistered CY008 execution stage; raw QD004, "
            "same-day CY033 state, and fabricated per-record snapshots are prohibited."
        ),
    }


def render_report(
    summary: dict[str, Any],
    source_hashes: dict[str, str],
    path: Path = REPORT,
) -> None:
    lines = [
        f"# {EXPERIMENT} Stage A",
        "",
        "Outcome-blind development identity construction only. No return, outcome, portfolio, or post-2021 row was opened.",
        "",
        "## Counts",
        "",
        f"Parent gaps: {summary['parent_gaps']}; selected signals: {summary['selected_signals']} on {summary['selected_signal_dates']} dates.",
        "",
        "|Signal year|Parent gaps|Selected|Signal dates|Later than old first reversal|",
        "|---:|---:|---:|---:|---:|",
    ]
    for year in DEVELOPMENT_YEARS:
        item = summary["by_signal_year"][str(year)]
        lines.append(
            f"|{year}|{item['parent_gaps']}|{item['selected_signals']}|{item['selected_signal_dates']}|{item['later_than_old_first_reversal']}|"
        )
    lines += [
        "",
        "## Recovery relative to frozen V28R2",
        "",
        f"Old V28R2 signals: {summary['old_v28r2_signals']}; retained under the uniform governed rule: {summary['old_v28r2_signals'] - summary['old_v28r2_missing_from_new']}; old signals rejected for declared lineage/action/raw-tick defects: {summary['old_v28r2_missing_from_new']}; unexplained old-signal losses: {summary['unexplained_old_v28r2_missing']}; newly recovered: {summary['recovered_beyond_old_v28r2']}.",
        "",
        f"Recovered sources: `{json.dumps(summary['recovered_by_old_first_failure'], sort_keys=True)}`.",
        f"Old-signal reproduction status: `{json.dumps(summary['old_v28r2_retention_status'], sort_keys=True)}`.",
        "",
        "## Governance",
        "",
        f"Lineage rows: {summary['lineage_rows']}; missing snapshot/daily snapshot/industry snapshot: {summary['lineage_missing_snapshot_id']} / {summary['lineage_missing_daily_snapshot_id']} / {summary['lineage_missing_industry_snapshot_id']}.",
        f"Post-2021 signal rows: {summary['post_2021_signal_count']}.",
        f"Execution: {summary['execution_identity_status']}. {summary['execution_blocker']}",
        "",
        f"Source identities: `{json.dumps(source_hashes, sort_keys=True)}`.",
        "",
        "No Stage B exists in this runner.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_dry_run() -> dict[str, Any]:
    """Compute signal counts without writing or opening any execution/outcome input."""
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    source_hashes = verify_sources(prereg)
    parent = load_parent()
    old_stage_ids = load_old_stage_ids()
    daily = load_cy033(parent.symbol.astype(str).unique().tolist())
    parent_binding = audit_parent_daily_binding(parent, daily)
    selected, audit, lineage = build_signal_cohort(parent, daily, old_stage_ids)
    summary = summarize(
        parent,
        selected,
        audit,
        lineage,
        old_stage_ids,
        parent_binding,
    )
    return {
        "experiment": EXPERIMENT,
        "mode": "READ_ONLY_DEVELOPMENT_SIGNAL_DRY_RUN",
        "summary": summary,
        "source_hashes": source_hashes,
        "artifacts_written": False,
        "execution_or_outcomes_opened": False,
        "post_2021_rows_opened": False,
    }


def run_stage_a() -> dict[str, Any]:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if prereg.get("stage_a_authorized") is not True:
        raise V29R4Error("Stage A has not passed final governance authorization")
    existing = [path for path in (STAGE_A_ROOT, STAGE_A_FREEZE, REPORT) if path.exists()]
    abandoned_staging = (
        sorted(EXT_ROOT.glob(f".{STAGE_A_ROOT.name}.staging-*"))
        if EXT_ROOT.exists()
        else []
    )
    if existing or abandoned_staging:
        paths = existing + abandoned_staging
        raise V29R4Error(
            "refusing Stage-A overwrite or automatic recovery of a partial bundle: "
            + ",".join(str(path) for path in paths)
        )
    source_hashes = verify_sources(prereg)
    parent = load_parent()
    old_stage_ids = load_old_stage_ids()
    daily = load_cy033(parent.symbol.astype(str).unique().tolist())
    parent_binding = audit_parent_daily_binding(parent, daily)
    if (
        parent_binding["gap_rows_bound_one_to_one"]
        != parent_binding["gap_rows_in_cy033_scope"]
        or parent_binding["gap_raw_tick_identity_matches"]
        != parent_binding["gap_rows_in_cy033_scope"]
        or parent_binding["signal_rows_bound_one_to_one"] != len(parent)
        or parent_binding["signal_decision_timestamp_matches"] != len(parent)
        or parent_binding["signal_lineage_valid"] != len(parent)
        or parent_binding["post_2021_daily_rows"] != 0
    ):
        raise V29R4Error("frozen V13 to CY033 parent binding failed")
    selected_frame, audit_frame, lineage_frame = build_signal_cohort(
        parent,
        daily,
        old_stage_ids,
    )
    summary = summarize(
        parent,
        selected_frame,
        audit_frame,
        lineage_frame,
        old_stage_ids,
        parent_binding,
    )
    if summary["uniform_rule_reproducible_old_missing_from_new"] != 0:
        raise V29R4Error(
            "composite-first selector failed to conserve uniformly reproducible old signals: "
            + ",".join(
                summary["uniform_rule_reproducible_old_missing_gap_ids"][:10]
            )
        )
    if summary["unexplained_old_v28r2_missing"] != 0:
        raise V29R4Error(
            "old V28R2 signals were lost outside the preregistered governance defects: "
            + ",".join(summary["unexplained_old_v28r2_missing_gap_ids"][:10])
        )
    if any(
        summary[key] != 0
        for key in (
            "lineage_missing_snapshot_id",
            "lineage_missing_daily_snapshot_id",
            "lineage_missing_industry_snapshot_id",
            "post_2021_signal_count",
        )
    ):
        raise V29R4Error("Stage-A governance invariant failed")

    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    stage_tmp = EXT_ROOT / f".{STAGE_A_ROOT.name}.staging-{os.getpid()}"
    report_tmp = REPORT.with_name(REPORT.name + f".staging-{os.getpid()}")
    freeze_tmp = STAGE_A_FREEZE.with_name(
        STAGE_A_FREEZE.name + f".staging-{os.getpid()}"
    )
    if stage_tmp.exists() or report_tmp.exists() or freeze_tmp.exists():
        raise V29R4Error("unique Stage-A staging target already exists")
    stage_tmp.mkdir()
    staged_lineage = stage_tmp / DAILY_LINEAGE.name
    staged_audit = stage_tmp / GAP_AUDIT.name
    staged_selected = stage_tmp / SELECTED_SIGNALS.name
    write_parquet(lineage_frame, staged_lineage)
    write_parquet(audit_frame, staged_audit)
    write_parquet(selected_frame, staged_selected)
    output_hashes = {
        "daily_lineage": sha256(staged_lineage),
        "gap_audit": sha256(staged_audit),
        "selected_signals": sha256(staged_selected),
    }
    render_report(summary, source_hashes, report_tmp)
    output_hashes["report"] = sha256(report_tmp)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_STAGE_A_IDENTITY_FREEZE_BEFORE_ANY_OUTCOME_ACCESS",
        "preregistration_sha256": sha256(PREREG),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "output_hashes": output_hashes,
        "summary": summary,
        "outcomes_opened": "NO",
        "return_fields_read": "NO",
        "portfolio_replay_run": "NO",
        "post_2021_rows_opened": "NO",
        "stage_b_exists": False,
    }
    for path in (staged_lineage, staged_audit, staged_selected, report_tmp):
        os.chmod(path, 0o444)
    os.rename(stage_tmp, STAGE_A_ROOT)
    publish_no_replace(report_tmp, REPORT)
    write_json(freeze_tmp, freeze)
    os.chmod(freeze_tmp, 0o444)
    publish_no_replace(freeze_tmp, STAGE_A_FREEZE)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V29R4Error("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    if (
        freeze.get("stage")
        != "DEVELOPMENT_STAGE_A_IDENTITY_FREEZE_BEFORE_ANY_OUTCOME_ACCESS"
        or freeze.get("outcomes_opened") != "NO"
        or freeze.get("return_fields_read") != "NO"
        or freeze.get("portfolio_replay_run") != "NO"
        or freeze.get("post_2021_rows_opened") != "NO"
        or freeze.get("stage_b_exists") is not False
    ):
        raise V29R4Error("Stage-A freeze governance flags drifted")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    source_hashes = verify_sources(prereg)
    artifact_paths = {
        "daily_lineage": DAILY_LINEAGE,
        "gap_audit": GAP_AUDIT,
        "selected_signals": SELECTED_SIGNALS,
        "report": REPORT,
        "freeze": STAGE_A_FREEZE,
    }
    missing = [str(path) for path in artifact_paths.values() if not path.is_file()]
    if missing:
        raise V29R4Error("Stage-A artifact missing: " + ",".join(missing))
    wrong_modes = {
        name: oct(path.stat().st_mode & 0o777)
        for name, path in artifact_paths.items()
        if path.stat().st_mode & 0o777 != 0o444
    }
    if wrong_modes:
        raise V29R4Error(f"Stage-A artifact is not sealed read-only: {wrong_modes}")
    checks = {
        "preregistration_sha256": sha256(PREREG),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "output_hashes": {
            "daily_lineage": sha256(DAILY_LINEAGE),
            "gap_audit": sha256(GAP_AUDIT),
            "selected_signals": sha256(SELECTED_SIGNALS),
            "report": sha256(REPORT),
        },
    }
    drift = {key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value}
    if drift:
        raise V29R4Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "summary": freeze["summary"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("dry-run", "stage-a", "verify"),
        default="dry-run",
    )
    args = parser.parse_args()
    if args.mode == "dry-run":
        payload = run_dry_run()
    elif args.mode == "stage-a":
        payload = run_stage_a()
    else:
        payload = verify_stage_a()
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
