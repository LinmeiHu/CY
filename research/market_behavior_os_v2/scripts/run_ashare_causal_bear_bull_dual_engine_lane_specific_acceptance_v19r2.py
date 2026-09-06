#!/usr/bin/env python3
"""Replay the frozen V19 mother with lane-specific chart semantics."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-CAUSAL-BEAR-BULL-DUAL-ENGINE-LANE-SPECIFIC-ACCEPTANCE-V19R2"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "33ed12d58b2eef36cf6940f91485d4b1da05553a4f7f6bd8c75d3a9fe019440b"
BASE_RUNNER = (
    OS_ROOT / "scripts/run_ashare_causal_bear_bull_dual_engine_chart_rule_compression_v19r1.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
OUTPUT_ROOT = DATA_ROOT / "ashare_causal_bear_bull_dual_engine_lane_specific_acceptance_v19r2"
OUTCOMES = OUTPUT_ROOT / "development_2014_2020_outcomes.parquet"
DECISIONS = OUTPUT_ROOT / "development_2014_2020_decision_ledger.parquet"
RESULT = OUTPUT_ROOT / "result.json"
ROUND_TRIP_COST = 0.004


class ResearchError(RuntimeError):
    """Fail closed on identity, causal timing, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_base() -> Any:
    spec = importlib.util.spec_from_file_location("v19r1_base", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise ResearchError("cannot import frozen V19R1 runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay_bull(base: Any, candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.signal_lineage)
    common = {
        "chart_event_id": str(candidate.chart_event_id),
        "source_event_id": str(candidate.source_event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "engine": str(candidate.engine),
        "admission_lane": str(candidate.admission_lane),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "signal_coord_close": float(candidate.signal_coord_close),
        "structural_level": float(candidate.structural_level),
        "expected_market_regime": "BULL",
        "target_return": 0.15,
        "horizon_sessions": 15,
        "route_semantics": "SIGNAL_CLOSE_CAUSAL_BULL",
    }
    confirmations = path.loc[path.cal_idx.eq(signal_idx + 1)]
    if len(confirmations) != 1:
        return {**common, "accepted": False, "status": "NO_IMMEDIATE_CONFIRMATION_BAR"}
    confirmation = confirmations.iloc[0]
    threshold = float(candidate.structural_level)
    if candidate.admission_lane == "IDIOSYNCRATIC_INFORMATION_JUMP":
        threshold = max(threshold, float(candidate.signal_coord_close))
    confirmation_payload = {
        "confirmation_date": pd.Timestamp(confirmation.trade_date),
        "confirmation_cal_idx": int(confirmation.cal_idx),
        "confirmation_coord_close": float(confirmation.coord_close),
        "confirmation_threshold": threshold,
        "confirmation_close_to_structure": float(confirmation.coord_close) / threshold - 1.0,
        "confirmation_market_regime": confirmation.market_regime,
    }
    if (
        not np.isfinite(float(confirmation.invalid_step_cum))
        or float(confirmation.invalid_step_cum) != lineage
    ):
        return {
            **common,
            **confirmation_payload,
            "accepted": False,
            "status": "CONFIRMATION_LINEAGE_CHANGE",
        }
    if not base.legal_observation(confirmation):
        return {
            **common,
            **confirmation_payload,
            "accepted": False,
            "status": "INVALID_IMMEDIATE_CONFIRMATION_BAR",
        }
    accepted = float(confirmation.coord_close) >= threshold
    if not accepted:
        return {
            **common,
            **confirmation_payload,
            "accepted": False,
            "status": "REJECTED_STRUCTURE_NOT_ACCEPTED",
        }

    entry_pool = path.loc[
        path.invalid_step_cum.eq(lineage)
        & path.cal_idx.gt(signal_idx + 1)
        & path.cal_idx.le(signal_idx + 4)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if base.buyable_open(row)), None)
    if entry is None:
        return {**common, **confirmation_payload, "accepted": True, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target_price = entry_price * 1.15
    pending_time_exit = False
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                **confirmation_payload,
                "accepted": True,
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "entry_price": entry_price,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if pending_time_exit and base.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H15_TIME_STOP"
            break
        if (
            base.legal_observation(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            exit_row = row
            exit_price = target_price
            exit_reason = "TARGET_15"
            break
        if base.legal_observation(row) and int(row.cal_idx) >= entry_idx + 15:
            pending_time_exit = True
    if exit_row is None:
        return {
            **common,
            **confirmation_payload,
            "accepted": True,
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": entry_idx,
            "entry_price": entry_price,
            "status": "INCOMPLETE_PATH",
        }
    gross = float(exit_price) / entry_price - 1.0
    return {
        **common,
        **confirmation_payload,
        "accepted": True,
        "status": "COMPLETED",
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def reuse_bear(candidate: Any) -> dict[str, Any]:
    if pd.isna(candidate.entry_cal_idx) or pd.isna(candidate.exit_cal_idx):
        raise ResearchError(f"frozen BEAR mother is incomplete: {candidate.chart_event_id}")
    return {
        "chart_event_id": str(candidate.chart_event_id),
        "source_event_id": str(candidate.source_event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "engine": str(candidate.engine),
        "admission_lane": str(candidate.admission_lane),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "signal_coord_close": float(candidate.signal_coord_close),
        "structural_level": float(candidate.structural_level),
        "expected_market_regime": "BEAR",
        "target_return": 0.10,
        "horizon_sessions": 20,
        "route_semantics": "SIGNAL_CLOSE_CAUSAL_BEAR_MOTHER_IS_CONFIRMATION",
        "confirmation_date": pd.NaT,
        "confirmation_cal_idx": np.nan,
        "confirmation_coord_close": np.nan,
        "confirmation_threshold": np.nan,
        "confirmation_close_to_structure": np.nan,
        "confirmation_market_regime": None,
        "accepted": True,
        "status": "COMPLETED",
        "entry_date": pd.Timestamp(candidate.entry_date),
        "entry_cal_idx": int(candidate.entry_cal_idx),
        "entry_price": float(candidate.entry_price),
        "exit_date": pd.Timestamp(candidate.exit_date),
        "exit_cal_idx": int(candidate.exit_cal_idx),
        "exit_price": float(candidate.exit_price),
        "exit_reason": str(candidate.exit_reason),
        "holding_sessions": int(candidate.holding_sessions),
        "gross_return": float(candidate.gross_return),
        "net_return": float(candidate.net_return),
    }


def compact_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")]
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "mother_signals": len(frame),
        "completed": len(completed),
        "signal_dates": int(completed.signal_date.nunique()),
        "mean_net": float(values.mean()) if len(completed) else None,
        "median_net": float(values.median()) if len(completed) else None,
        "win_rate": float(values.gt(0).mean()) if len(completed) else None,
        "severe10": float(values.le(-0.10).mean()) if len(completed) else None,
        "target_hit": float(completed.exit_reason.str.startswith("TARGET_").mean())
        if len(completed)
        else None,
        "mean_holding_sessions": float(completed.holding_sessions.mean())
        if len(completed)
        else None,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    if sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("freeze identity drift")
    base = load_base()
    source_hashes = base.verify_inputs()
    mother = base.load_mother()
    original = pd.read_parquet(base.MOTHER)[
        [
            "chart_event_id",
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
        ]
    ]
    mother = mother.merge(
        original,
        on="chart_event_id",
        how="left",
        validate="one_to_one",
    )
    paths = base.load_paths(mother.loc[mother.engine.eq("BULL_CONTINUATION")])
    groups = {key: part for key, part in paths.groupby("chart_event_id", sort=False)}
    rows = []
    for candidate in mother.itertuples(index=False):
        if candidate.engine == "BEAR_REPAIR":
            rows.append(reuse_bear(candidate))
        else:
            rows.append(
                replay_bull(
                    base, candidate, groups.get(str(candidate.chart_event_id), pd.DataFrame())
                )
            )
    outcomes = pd.DataFrame(rows)
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    if len(outcomes) != 840 or outcomes.chart_event_id.nunique() != 840:
        raise ResearchError("mother identity mismatch")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "entry_at_or_before_signal": int(
            completed.entry_cal_idx.le(completed.signal_cal_idx).sum()
        ),
        "bull_entry_at_or_before_confirmation": int(
            completed.loc[completed.engine.eq("BULL_CONTINUATION"), "entry_cal_idx"]
            .le(completed.loc[completed.engine.eq("BULL_CONTINUATION"), "confirmation_cal_idx"])
            .sum()
        ),
        "exit_at_or_before_entry": int(completed.exit_cal_idx.le(completed.entry_cal_idx).sum()),
    }
    if any(chronology.values()):
        raise ResearchError(f"chronology failure: {chronology}")
    yearly = {
        str(year): compact_metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    pooled = compact_metrics(outcomes)
    gates = {
        "completed_gt_50_each_year": all(item["completed"] > 50 for item in yearly.values()),
        "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None and pooled["mean_net"] > 0.04,
    }
    base.write_parquet(outcomes, OUTCOMES)
    decision_columns = [
        "chart_event_id",
        "source_event_id",
        "symbol",
        "sleeve",
        "engine",
        "admission_lane",
        "signal_date",
        "signal_cal_idx",
        "route_semantics",
        "confirmation_date",
        "confirmation_cal_idx",
        "confirmation_coord_close",
        "confirmation_threshold",
        "accepted",
        "status",
    ]
    base.write_parquet(outcomes.reindex(columns=decision_columns), DECISIONS)
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "CONSUMED_2014_2020_POST_CHART_SEMANTIC_CORRECTION",
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "base_source_hashes": source_hashes,
        "pooled": pooled,
        "annual": yearly,
        "by_engine": {
            str(key): compact_metrics(part) for key, part in outcomes.groupby("engine", sort=True)
        },
        "by_admission_lane": {
            str(key): compact_metrics(part)
            for key, part in outcomes.groupby("admission_lane", sort=True)
        },
        "gates": gates,
        "later_2022_2024_open_authorized": all(gates.values()),
        "chronology_audit": chronology,
        "status_counts": {
            str(k): int(v)
            for k, v in outcomes.status.value_counts(dropna=False).sort_index().items()
        },
        "2021_outcome_read": "NO",
        "2022_2024_outcome_read": "NO",
        "future_market_state_used": False,
        "outcomes_sha256": sha256(OUTCOMES),
        "decisions_sha256": sha256(DECISIONS),
        "runner_sha256": sha256(Path(__file__)),
        "verdict": "V19R2_GATE_PASS" if all(gates.values()) else "V19R2_GATE_FAIL",
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
