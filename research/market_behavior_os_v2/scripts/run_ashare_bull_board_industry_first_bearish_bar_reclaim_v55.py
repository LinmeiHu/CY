#!/usr/bin/env python3
"""Evaluate the frozen V55 first bearish-bar reclaim contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import run_ashare_bull_board_rotation_low_overhang_pressure_release_v54 as core  # noqa: E402


EXPERIMENT = "ASHARE-BULL-BOARD-INDUSTRY-FIRST-BEARISH-BAR-RECLAIM-V55"
ROOT = Path("/Volumes/quant/CY_quant_research/bull_board_industry_first_bearish_bar_reclaim_v55")
PROFILES = {
    "T15_H8_X0": {"target": 0.15, "horizon": 8, "failure": False},
    "T15_H12_X0": {"target": 0.15, "horizon": 12, "failure": False},
    "T20_H8_X0": {"target": 0.20, "horizon": 8, "failure": False},
    "T20_H12_X0": {"target": 0.20, "horizon": 12, "failure": False},
    "T15_H8_X1": {"target": 0.15, "horizon": 8, "failure": True},
    "T15_H12_X1": {"target": 0.15, "horizon": 12, "failure": True},
    "T20_H8_X1": {"target": 0.20, "horizon": 8, "failure": True},
    "T20_H12_X1": {"target": 0.20, "horizon": 12, "failure": True},
}


def configure() -> None:
    core.EXPERIMENT = EXPERIMENT
    core.ROOT = ROOT
    core.CANDIDATES = ROOT / "stage_a/candidates.parquet"
    core.DEV_OUTCOMES = ROOT / "stage_b/development_outcomes.parquet"
    core.PROFILE_TABLE = ROOT / "stage_b/development_profile_table.parquet"
    core.PROFILE_FREEZE = ROOT / "stage_b/profile_freeze.json"
    core.FORWARD_OUTCOMES = ROOT / "stage_b/forward_outcomes.parquet"
    core.ACCEPTED = ROOT / "stage_b/portfolio_accepted.parquet"
    core.SKIPPED = ROOT / "stage_b/portfolio_skipped.parquet"
    core.NAV = ROOT / "stage_b/portfolio_nav.parquet"
    core.RESULT = HERE.parent / "artifacts" / f"{EXPERIMENT}_result.json"
    core.CONTRACT = HERE.parent / "experiments" / f"{EXPERIMENT}_contract.json"
    core.SPEC = HERE.parent / "experiments" / f"{EXPERIMENT}_spec.json"
    core.FREEZE = HERE.parent / "artifacts" / f"{EXPERIMENT}_stage_a_freeze.json"
    core.PROFILES = PROFILES


def run() -> dict:
    configure()
    # Map the frozen V55 ranking and failure-floor fields onto the generic exact
    # execution engine without changing candidate identity or outcome semantics.
    original_reader = core.v1.read_parquet_duckdb

    def reader(path: Path) -> pd.DataFrame:
        frame = original_reader(path)
        if Path(path) == core.CANDIDATES:
            frame = frame.copy()
            frame["overhead_share"] = -frame["industry_breadth20"].astype(float)
            frame["industry_minus_market20"] = frame["impulse_efficiency"].astype(float)
            frame["trigger_turnover_ratio"] = frame["demand_vs_pullback"].astype(float)
        return frame

    core.v1.read_parquet_duckdb = reader
    try:
        result = core.run()
    finally:
        core.v1.read_parquet_duckdb = original_reader
    labels = {
        "BOARD_ROTATION_LOW_OVERHANG_PRESSURE_RELEASE_DEVELOPMENT_FAILED": "FIRST_BEARISH_BAR_RECLAIM_DEVELOPMENT_FAILED",
        "BOARD_ROTATION_LOW_OVERHANG_PRESSURE_RELEASE_EDGE": "FIRST_BEARISH_BAR_RECLAIM_EDGE",
        "BOARD_ROTATION_LOW_OVERHANG_PRESSURE_RELEASE_FAILED_FORWARD_OR_TARGET": "FIRST_BEARISH_BAR_RECLAIM_FAILED_FORWARD_OR_TARGET",
    }
    result["verdict"] = labels.get(result["verdict"], result["verdict"])
    core.write_json(core.RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("choose --run")
    print(json.dumps(run(), indent=2, default=str))


if __name__ == "__main__":
    main()
