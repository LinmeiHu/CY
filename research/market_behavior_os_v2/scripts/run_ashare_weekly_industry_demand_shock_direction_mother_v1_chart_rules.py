#!/usr/bin/env python3
"""Evaluate the frozen chart-compressed rules without threshold rescue."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-WEEKLY-INDUSTRY-DEMAND-SHOCK-DIRECTION-MOTHER-V1-CHART-RULES"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-WEEKLY-INDUSTRY-DEMAND-SHOCK-DIRECTION-MOTHER-V1_chart_rules_freeze.json"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
SOURCE_ROOT = DATA_ROOT / "ashare_weekly_industry_demand_shock_direction_mother_v1"
LEDGER = SOURCE_ROOT / "stage_c_charts/review_ledger.parquet"
OUTPUT_ROOT = SOURCE_ROOT / "stage_d_chart_rules"
RULE_TABLE = OUTPUT_ROOT / "rule_events.parquet"
RESULT = OUTPUT_ROOT / "result.json"
EXPECTED_HASHES = {
    SPEC: "ff4bec2b79cd458a46d384facae3f3d7b081922bd35430245e41af35e0015191",
    LEDGER: "f0175f8f8c1fb5492d6c1a8cec073ebd25731aed95019bca45bcdd776ded8f46",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity or evaluation drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": int(len(frame)),
        "completed": int(len(completed)),
        "signal_dates": int(completed.signal_date.nunique()),
        "symbols": int(completed.symbol.nunique()),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "positive_rate": None if completed.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if completed.empty else float(values.ge(0.04).mean()),
        "severe10": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_10").mean()),
    }


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    frame = pd.read_parquet(LEDGER)
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if len(frame) != 590 or frame.event_id.duplicated().any():
        raise ResearchError("chart-ledger event identity drift")
    if frame.signal_year.max() > 2020:
        raise ResearchError("post-2020 signal entered development aggregation")
    required = [
        "market_regime", "market_median_ret20", "market_median_ret60",
        "market_positive_ret20_share", "market_positive_ret60_share",
        "direction_lane", "ret20", "ret60", "pre126_position",
        "close_location", "signal_turnover_ratio",
    ]
    if frame[required].isna().any().any():
        raise ResearchError("a frozen chart-rule input is missing")

    frame["market_return_acceleration"] = (
        frame.market_median_ret20 - frame.market_median_ret60
    )
    frame["market_breadth_acceleration"] = (
        frame.market_positive_ret20_share - frame.market_positive_ret60_share
    )
    frame["r1_non_bear_core"] = frame.market_regime.ne("BEAR")
    frame["r2_causal_bear_repair"] = (
        frame.market_return_acceleration.gt(0)
        & frame.market_breadth_acceleration.gt(0)
    )
    frame["r3_low_inventory_price_discovery_exception"] = (
        frame.direction_lane.eq("CONTINUATION")
        & frame.ret20.gt(frame.ret60)
        & frame.pre126_position.le(0.50)
        & frame.close_location.ge(0.50)
    )
    frame["r4_weak_industry_stock_resilience_exception"] = (
        frame.direction_lane.eq("REVERSAL")
        & frame.ret20.ge(0)
        & frame.pre126_position.le(0.70)
        & frame.close_location.ge(0.50)
    )
    mature_spike = (
        frame.pre126_position.ge(0.95)
        & frame.ret20.ge(0.20)
        & frame.signal_turnover_ratio.ge(1.50)
    )
    falling_knife = (
        frame.ret20.lt(frame.ret60)
        & frame.ret20.lt(0)
        & frame.market_return_acceleration.le(0)
        & frame.market_breadth_acceleration.le(0)
    )
    frame["r5_structural_trap_veto"] = mature_spike | falling_knife
    frame["admitted"] = (
        frame[
            [
                "r1_non_bear_core",
                "r2_causal_bear_repair",
                "r3_low_inventory_price_discovery_exception",
                "r4_weak_industry_stock_resilience_exception",
            ]
        ].any(axis=1)
        & ~frame.r5_structural_trap_veto
    )
    selected = frame.loc[frame.admitted].copy()

    yearly = {
        str(int(year)): metrics(part)
        for year, part in selected.groupby("signal_year", sort=True)
    }
    expected_years = {str(year) for year in range(2014, 2021)}
    if set(yearly) != expected_years:
        raise ResearchError("one or more frozen development years disappeared")
    yearly_gate = {
        year: bool(row["completed"] > 50 and row["mean_net"] > 0.04)
        for year, row in yearly.items()
    }
    pass_gate = bool(all(yearly_gate.values()))
    if pass_gate:
        disposition = "DEVELOPMENT_GATE_PASSED_LATER_PERIOD_AUTHORIZED"
        next_step = "Freeze an immutable 2022-2024 validation contract before reading it."
    else:
        disposition = "CLOSED_DEVELOPMENT_GATE_FAILED_NO_THRESHOLD_RESCUE"
        next_step = (
            "Do not read 2022-2024 for this formulation; switch to a new "
            "economically distinct high-recall mother hypothesis."
        )

    compact_columns = [
        "event_id", "symbol", "causal_industry", "direction_lane", "signal_date",
        "signal_year", "market_regime", "market_return_acceleration",
        "market_breadth_acceleration", "ret20", "ret60", "pre126_position",
        "close_location", "signal_turnover_ratio", "r1_non_bear_core",
        "r2_causal_bear_repair", "r3_low_inventory_price_discovery_exception",
        "r4_weak_industry_stock_resilience_exception", "r5_structural_trap_veto",
        "admitted", "status", "entry_date", "exit_date", "exit_reason",
        "holding_sessions", "net_return", "outcome_bucket",
    ]
    write_parquet(frame[compact_columns], RULE_TABLE)
    payload = {
        "experiment": EXPERIMENT,
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "rule_table_sha256": sha256(RULE_TABLE),
        "all_590_charts_reviewed_before_rule_freeze": True,
        "rule_count": 5,
        "unfiltered": metrics(frame),
        "selected": metrics(selected),
        "selected_by_lane": {
            str(lane): metrics(part)
            for lane, part in selected.groupby("direction_lane", sort=True)
        },
        "selected_by_market_regime": {
            str(regime): metrics(part)
            for regime, part in selected.groupby("market_regime", sort=True)
        },
        "selected_by_year": yearly,
        "per_year_gate": yearly_gate,
        "complete_development_gate_passed": pass_gate,
        "disposition": disposition,
        "post_2021_06_rule_discovery_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "future_market_function": False,
        "future_industry_function": False,
        "next_step": next_step,
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
