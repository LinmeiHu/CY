#!/usr/bin/env python3
"""Replay the frozen causal-state target for stale-resistance breakouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_ashare_stale_annual_resistance_chart_compressed_rules_v4 as v4


EXPERIMENT = "ASHARE-STALE-ANNUAL-RESISTANCE-CAUSAL-STATE-TARGET-V5"
REPO = Path(__file__).resolve().parents[3]
FREEZE = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "f2ee17f59d37d4204cfee0518924a98588dfc6578fd82010c912b18ff7f5df1c"
OUTPUT_ROOT = (
    v4.DATA_ROOT
    / "ashare_stale_annual_resistance_causal_state_target_v5"
    / "development_2014_2020"
)
REPLAY = OUTPUT_ROOT / "event_replay.parquet"
ANNUAL = OUTPUT_ROOT / "annual_metrics.csv"
RESULT = OUTPUT_ROOT / "result.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.cal_idx)
    lineage = float(candidate.invalid_step_cum)
    state = str(candidate.market_regime)
    if state not in {"BULL", "BEAR", "TRANSITION"}:
        return {
            "event_id": str(candidate.event_id),
            "symbol": str(candidate.symbol),
            "sleeve": str(candidate.sleeve),
            "signal_date": pd.Timestamp(candidate.signal_date),
            "signal_year": int(pd.Timestamp(candidate.signal_date).year),
            "status": "INVALID_MARKET_STATE",
        }
    target_return = 0.20 if state == "BULL" else 0.10
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_year": int(pd.Timestamp(candidate.signal_date).year),
        "signal_cal_idx": signal_idx,
        "market_regime": state,
        "market_state_source_timestamp": pd.Timestamp(candidate.market_latest_source_timestamp),
        "target_return": target_return,
    }
    same_lineage = path.loc[path.invalid_step_cum.eq(lineage)]
    entry_pool = same_lineage.loc[
        same_lineage.cal_idx.gt(signal_idx) & same_lineage.cal_idx.le(signal_idx + 3)
    ]
    entry = next((row for row in entry_pool.itertuples(index=False) if v4.buyable_open(row)), None)
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}

    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * (1.0 + target_return)
    pending_time_exit = False
    exit_row: Any | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    invalid = False
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending_time_exit and v4.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H60_TIME_STOP"
            break
        if (
            v4.legal_observation(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_20" if state == "BULL" else "TARGET_10"
            break
        if v4.legal_observation(row) and int(row.cal_idx) >= entry_idx + v4.HORIZON:
            pending_time_exit = True
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {**base, **entry_payload, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"}
    if exit_row is None:
        return {**base, **entry_payload, "status": "INCOMPLETE_BY_2021_END"}
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
        "net_return": gross - v4.COST,
    }


def replay(candidates: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    path_map = {key: part for key, part in paths.groupby("event_id", sort=False)}
    return pd.DataFrame(
        [
            replay_one(candidate, path_map.get(str(candidate.event_id), pd.DataFrame()))
            for candidate in candidates.itertuples(index=False)
        ]
    ).sort_values(["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort")


def run() -> dict[str, Any]:
    if not FREEZE.is_file() or sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise v4.ResearchError("V5 frozen specification drift")
    source_hashes = v4.verify_inputs()
    candidates, frozen_baseline, paths = v4.load_inputs()
    baseline = v4.replay(candidates, paths, structural_exit=False)
    reproduction = v4.validate_baseline(baseline, frozen_baseline)
    routed = replay(candidates, paths)
    v4.write_parquet(routed, REPLAY)

    annual_rows: list[dict[str, Any]] = []
    for year in v4.EXPECTED_ANNUAL:
        baseline_metrics = v4.metrics(baseline.loc[baseline.signal_year.eq(year)])
        routed_metrics = v4.metrics(routed.loc[routed.signal_year.eq(year)])
        annual_rows.append(
            {
                "year": year,
                **{f"baseline_{key}": value for key, value in baseline_metrics.items() if key != "exit_reasons"},
                **{f"routed_{key}": value for key, value in routed_metrics.items() if key != "exit_reasons"},
                "mean_net_delta": routed_metrics["mean_net"] - baseline_metrics["mean_net"],
                "severe_loss_rate_delta": routed_metrics["severe_loss_rate"] - baseline_metrics["severe_loss_rate"],
            }
        )
    annual = pd.DataFrame(annual_rows)
    ANNUAL.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL, index=False, float_format="%.10g")
    baseline_metrics = v4.metrics(baseline)
    routed_metrics = v4.metrics(routed)
    by_state = {
        state: v4.metrics(part)
        for state, part in routed.groupby("market_regime", sort=True)
    }
    each_year_count_pass = bool(annual.routed_signals.gt(50).all())
    pooled_mean_pass = bool(float(routed_metrics["mean_net"]) > 0.04)
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_DEVELOPMENT_CHART_RULE_COMPRESSION_NOT_INDEPENDENT_CONFIRMATION",
        "freeze_sha256": sha256(FREEZE),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "baseline_reproduction": reproduction,
        "baseline": baseline_metrics,
        "routed": routed_metrics,
        "routed_by_signal_market_state": by_state,
        "annual": annual.to_dict("records"),
        "deltas": {
            "mean_net": routed_metrics["mean_net"] - baseline_metrics["mean_net"],
            "median_net": routed_metrics["median_net"] - baseline_metrics["median_net"],
            "severe_loss_rate": routed_metrics["severe_loss_rate"] - baseline_metrics["severe_loss_rate"],
            "mean_holding_sessions": routed_metrics["mean_holding_sessions"] - baseline_metrics["mean_holding_sessions"],
        },
        "development_gate": {
            "each_2014_2020_year_signal_count_gt_50": each_year_count_pass,
            "pooled_completed_mean_net_gt_4pct": pooled_mean_pass,
            "pass": each_year_count_pass and pooled_mean_pass,
        },
        "causality_audit": {
            "market_state_source_after_signal_decision": int(
                candidates.market_latest_source_timestamp.gt(candidates.decision_at).sum()
            ),
            "max_signal_date": str(candidates.signal_date.max().date()),
            "max_replay_source_date": str(paths.trade_date.max().date()),
            "2022_2024_signal_or_outcome_read": False,
        },
        "event_replay_sha256": sha256(REPLAY),
        "annual_metrics_sha256": sha256(ANNUAL),
    }
    v4.write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-result", action="store_true")
    args = parser.parse_args()
    result = run()
    if args.print_result:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
