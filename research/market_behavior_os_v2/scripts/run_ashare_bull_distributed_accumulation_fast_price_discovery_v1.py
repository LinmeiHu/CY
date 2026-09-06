#!/usr/bin/env python3
"""Development replay for fast price discovery after distributed accumulation."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import run_ashare_bull_distributed_accumulation_chart_rules_v3 as parent


EXPERIMENT = "ASHARE-BULL-DISTRIBUTED-ACCUMULATION-FAST-PRICE-DISCOVERY-V1"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
SOURCE_ROOT = (
    DATA_ROOT
    / "ashare_bull_distributed_accumulation_chart_rules_v3"
    / "development_2014_2020"
)
PANEL = SOURCE_ROOT / "causal_rule_panel.parquet"
PATHS = SOURCE_ROOT / "future_paths.parquet"
EXPECTED_INPUT_HASHES = {
    PANEL: "c9d46433fa18d87307cc2105ca6ee1e157a5160b1ebe7ab015be3f174379f114",
    PATHS: "c814ce76f61c4ec1d6dcd4fce30ec9ab649ac9f914bf629b1a6b966f53d61eb0",
}
OUTPUT_ROOT = DATA_ROOT / "ashare_bull_distributed_accumulation_fast_price_discovery_v1"
OUTCOMES = OUTPUT_ROOT / "development_2014_2020_outcomes.parquet"
RESULT = OUTPUT_ROOT / "development_2014_2020_result.json"
TARGET_RETURN = 0.10
HORIZON = 20
ROUND_TRIP_COST = 0.004


class ResearchError(RuntimeError):
    """Fail closed on identity, lineage, or executable chronology."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        temporary,
        compression="zstd",
    )
    os.replace(temporary, path)


def atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_INPUT_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        digest = sha256(path)
        actual[str(path)] = digest
        if digest != expected:
            raise ResearchError(f"input drift: {path}: {digest} != {expected}")
    return actual


def common(candidate: Any, status: str) -> dict[str, Any]:
    return {
        "event_id": candidate.event_id,
        "symbol": candidate.symbol,
        "sleeve": candidate.sleeve,
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "status": status,
    }


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    if not bool(candidate.pre_confirmation_pass):
        return common(candidate, "REJECTED_PRE_CONFIRMATION")
    lineage = float(candidate.invalid_step_cum)
    confirmation_pool = path.loc[
        path.cal_idx.gt(candidate.signal_cal_idx)
        & path.cal_idx.le(candidate.signal_cal_idx + 3)
    ]
    confirmation = next(
        (
            row
            for row in confirmation_pool.itertuples(index=False)
            if float(row.invalid_step_cum) == lineage
            and parent.legal(row)
            and np.isfinite(float(row.coord_close))
            and float(row.coord_close) > 0
        ),
        None,
    )
    if confirmation is None:
        return common(candidate, "NO_LEGAL_CONFIRMATION")
    confirmation_common = {
        **common(candidate, "REJECTED_ACCEPTANCE"),
        "confirmation_date": pd.Timestamp(confirmation.trade_date),
        "confirmation_cal_idx": int(confirmation.cal_idx),
        "confirmation_close": float(confirmation.coord_close),
    }
    if float(confirmation.coord_close) < float(candidate.coord_close):
        return confirmation_common
    entry = next(
        (
            row
            for row in path.loc[
                path.cal_idx.gt(confirmation.cal_idx)
                & path.cal_idx.le(confirmation.cal_idx + 3)
            ].itertuples(index=False)
            if float(row.invalid_step_cum) == lineage and parent.buyable(row)
        ),
        None,
    )
    if entry is None:
        return {**confirmation_common, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    entry_common = {
        **confirmation_common,
        "status": "INCOMPLETE_PATH",
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    target = entry_price * (1.0 + TARGET_RETURN)
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if (
            not np.isfinite(float(row.invalid_step_cum))
            or float(row.invalid_step_cum) != lineage
        ):
            return {
                **entry_common,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if (
            parent.legal(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_price = target
            exit_reason = "TARGET_10"
        elif int(row.cal_idx) > entry_idx + HORIZON and parent.sellable_open(row):
            exit_price = float(row.coord_open)
            exit_reason = "H20_TIME_STOP"
        else:
            continue
        gross_return = exit_price / entry_price - 1.0
        return {
            **entry_common,
            "status": "COMPLETED",
            "exit_date": pd.Timestamp(row.trade_date),
            "exit_cal_idx": int(row.cal_idx),
            "exit_price": float(exit_price),
            "exit_reason": exit_reason,
            "holding_sessions": int(row.cal_idx) - entry_idx,
            "gross_return": float(gross_return),
            "net_return": float(gross_return - ROUND_TRIP_COST),
        }
    return entry_common


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    if complete.empty:
        return {
            "completed": 0,
            "mean_net_return": None,
            "median_net_return": None,
            "mean_holding_sessions": None,
            "target_hit_rate": None,
            "severe_loss_rate": None,
        }
    return {
        "completed": int(len(complete)),
        "mean_net_return": float(complete.net_return.mean()),
        "median_net_return": float(complete.net_return.median()),
        "mean_holding_sessions": float(complete.holding_sessions.mean()),
        "target_hit_rate": float(complete.exit_reason.eq("TARGET_10").mean()),
        "severe_loss_rate": float(complete.net_return.le(-0.10).mean()),
    }


def run() -> dict[str, Any]:
    hashes = verify_inputs()
    panel = pd.read_parquet(PANEL)
    paths = pd.read_parquet(PATHS)
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    for column in ("trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    if panel.event_id.duplicated().any() or panel.signal_date.max() > pd.Timestamp(
        "2020-12-31"
    ):
        raise ResearchError("invalid development identity population")
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
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "confirmation_at_or_before_signal": int(
            complete.confirmation_cal_idx.le(complete.signal_cal_idx).sum()
        ),
        "entry_at_or_before_confirmation": int(
            complete.entry_cal_idx.le(complete.confirmation_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(
            complete.exit_cal_idx.le(complete.entry_cal_idx).sum()
        ),
    }
    if any(chronology.values()):
        raise ResearchError(f"chronology failure: {chronology}")
    atomic_parquet(outcomes, OUTCOMES)
    pooled = metrics(outcomes)
    annual = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    user_gates = {
        "mean_completed_signals_per_year_gt_50": pooled["completed"] / 7 > 50,
        "mean_net_return_ge_4pct": pooled["mean_net_return"] is not None
        and pooled["mean_net_return"] >= 0.04,
        "mean_holding_sessions_lt_15": pooled["mean_holding_sessions"] is not None
        and pooled["mean_holding_sessions"] < 15,
    }
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "USER_TARGET_TRANSLATION_DEVELOPMENT_REPLAY",
        "development_signal_period": "2014-01-01 through 2020-12-31",
        "parent_rules_changed": False,
        "translation": "+10 percent gross target / H20 / 40 bps round trip",
        "mother_signals": int(len(outcomes)),
        "status_counts": outcomes.status.value_counts().sort_index().to_dict(),
        "pooled": pooled,
        "annual": annual,
        "mean_completed_signals_per_year": pooled["completed"] / 7,
        "user_gates": user_gates,
        "all_user_gates_pass": bool(all(user_gates.values())),
        "chronology": chronology,
        "2021_plus_signal_or_outcome_read": "NO",
        "input_hashes_sha256": hashes,
    }
    result["outcomes_sha256"] = sha256(OUTCOMES)
    atomic_json(result, RESULT)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
