#!/usr/bin/env python3
"""Unchanged-rule 2025 extension for broad panic absorption V2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import run_ashare_panic_absorption_broad_capitulation_v2 as parent


EXPERIMENT = "ASHARE-PANIC-ABSORPTION-BROAD-CAPITULATION-V2-2025-EXTENSION"
REPO = Path(__file__).resolve().parents[3]
FREEZE = (
    REPO
    / "research/market_behavior_os_v2/experiments/"
    "ASHARE-PANIC-ABSORPTION-BROAD-CAPITULATION-V2-2025-EXTENSION_freeze.json"
)
EXPECTED_FREEZE_SHA256 = "7128cb23ffb2fea248fa03f3349151985d9b4a5638a5b849dbe63bb39bb3c105"
OUTPUT_ROOT = (
    Path("/Volumes/quant/CY_quant_research")
    / "ashare_panic_absorption_broad_capitulation_v2"
    / "fresh_2025"
)
RAW = OUTPUT_ROOT / "raw_candidates.parquet"
SELECTED = OUTPUT_ROOT / "selected_candidates.parquet"
PATHS = OUTPUT_ROOT / "future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"


def build_candidates() -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect()
    high = con.execute(
        parent.candidate_query(parent.CURRENT_DAILY, "2024-10-01", "2025-12-31")
    ).fetchdf()
    con.close()
    frozen = parent.apply_cooldown(high)
    frozen = frozen.loc[frozen.signal_date.dt.year.eq(2025)].copy()
    frozen["same_date_signal_count"] = frozen.groupby("signal_date")[
        "event_id"
    ].transform("size")
    selected = frozen.loc[frozen.same_date_signal_count.ge(2)].copy()
    for frame in (frozen, selected):
        if frame.event_id.duplicated().any():
            raise parent.ExperimentError("duplicate 2025 event identity")
        if pd.to_datetime(frame.available_at).gt(pd.to_datetime(frame.decision_at)).any():
            raise parent.ExperimentError("2025 feature available after decision")
    return frozen.reset_index(drop=True), selected.reset_index(drop=True)


def build_paths(candidates: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.register(
        "candidate_ids",
        candidates[
            [
                "event_id",
                "symbol",
                "sleeve",
                "signal_date",
                "cal_idx",
                "invalid_step_cum",
            ]
        ],
    )
    frame = con.execute(
        f"""
        SELECT c.event_id,c.symbol,c.sleeve,c.signal_date,
          c.cal_idx AS signal_cal_idx,
          c.invalid_step_cum AS signal_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM candidate_ids c
        JOIN read_parquet('{parent.CURRENT_DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.cal_idx
        WHERE d.trade_date<=DATE '2026-03-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def concentration(outcomes: pd.DataFrame) -> dict[str, Any]:
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    grouped = (
        complete.groupby("signal_date", as_index=False)
        .agg(signals=("event_id", "size"), mean_net=("net_return", "mean"))
        .sort_values(["signals", "signal_date"], ascending=[False, True])
        .reset_index(drop=True)
    )
    if grouped.empty:
        return {}
    largest = pd.Timestamp(grouped.iloc[0].signal_date)
    without = complete.loc[complete.signal_date.ne(largest)]
    return {
        "distinct_signal_dates": int(len(grouped)),
        "largest_signal_date": str(largest.date()),
        "maximum_signals_on_one_date": int(grouped.iloc[0].signals),
        "largest_date_share": float(grouped.iloc[0].signals / len(complete)),
        "signal_date_equal_weight_mean_net": float(grouped.mean_net.mean()),
        "mean_net_excluding_largest_date": None
        if without.empty
        else float(without.net_return.mean()),
        "top_dates": grouped.head(10).to_dict("records"),
    }


def run() -> dict[str, Any]:
    if parent.sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise parent.ExperimentError("2025 extension freeze hash drift")
    if parent.sha256(parent.CURRENT_DAILY) != (
        "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9"
    ):
        raise parent.ExperimentError("exact daily input drift")
    raw, selected = build_candidates()
    paths = build_paths(selected)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            parent.replay_one(candidate, groups.get(candidate.event_id, pd.DataFrame()))
            for candidate in selected.itertuples(index=False)
        ]
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    for column in ("entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "entry_at_or_before_signal": int(
            complete.entry_cal_idx.le(complete.signal_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(
            complete.exit_cal_idx.le(complete.entry_cal_idx).sum()
        ),
    }
    if any(chronology.values()):
        raise parent.ExperimentError(f"2025 chronology failure: {chronology}")
    parent.write_parquet(raw, RAW)
    parent.write_parquet(selected, SELECTED)
    parent.write_parquet(paths, PATHS)
    parent.write_parquet(outcomes, OUTCOMES)
    pooled = parent.metrics(outcomes)
    by_month = {
        str(month): parent.metrics(part)
        for month, part in outcomes.groupby(
            outcomes.signal_date.dt.to_period("M"), sort=True
        )
    }
    gates = {
        "completed_signals_gt_50": pooled["completed"] > 50,
        "mean_net_ge_4pct": pooled["mean_net"] is not None
        and pooled["mean_net"] >= 0.04,
        "mean_holding_lt_15": pooled["mean_holding"] is not None
        and pooled["mean_holding"] < 15,
    }
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "UNCHANGED_RULE_2025_TEMPORAL_EXTENSION",
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "raw_candidates": int(len(raw)),
        "selected_candidates": int(len(selected)),
        "pooled": pooled,
        "by_signal_month": by_month,
        "concentration": concentration(outcomes),
        "status_counts": outcomes.status.value_counts().sort_index().to_dict(),
        "gates": gates,
        "all_user_gates_pass": bool(all(gates.values())),
        "chronology": chronology,
        "future_market_function": False,
        "no_rescue": True,
        "input_hashes_sha256": {
            "freeze": EXPECTED_FREEZE_SHA256,
            "exact_daily": parent.sha256(parent.CURRENT_DAILY),
        },
        "output_hashes_sha256": {
            "raw": parent.sha256(RAW),
            "selected": parent.sha256(SELECTED),
            "paths": parent.sha256(PATHS),
            "outcomes": parent.sha256(OUTCOMES),
        },
    }
    parent.write_json(RESULT, result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
