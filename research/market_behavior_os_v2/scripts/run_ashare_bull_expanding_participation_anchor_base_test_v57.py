#!/usr/bin/env python3
"""Run the frozen V57 expanding-participation anchor-base test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import run_ashare_bull_anchor_cost_first_dry_pullback_v56 as engine


EXPERIMENT = "ASHARE-BULL-EXPANDING-PARTICIPATION-ANCHOR-BASE-TEST-V57"
ROOT = Path("/Volumes/quant/CY_quant_research/bull_expanding_participation_anchor_base_test_v57")
OS = Path(__file__).resolve().parent.parent


def configure() -> None:
    engine.EXPERIMENT = EXPERIMENT
    engine.ROOT = ROOT
    engine.CANDIDATES = ROOT / "stage_a/candidates.parquet"
    engine.DEV_OUTCOMES = ROOT / "stage_b/development_outcomes.parquet"
    engine.PROFILE_TABLE = ROOT / "stage_b/development_profile_table.parquet"
    engine.PROFILE_FREEZE = ROOT / "stage_b/profile_freeze.json"
    engine.FORWARD_OUTCOMES = ROOT / "stage_b/forward_outcomes.parquet"
    engine.ACCEPTED = ROOT / "stage_b/portfolio_accepted.parquet"
    engine.SKIPPED = ROOT / "stage_b/portfolio_skipped.parquet"
    engine.NAV = ROOT / "stage_b/portfolio_nav.parquet"
    engine.RESULT = OS / "artifacts" / f"{EXPERIMENT}_result.json"
    engine.CONTRACT = OS / "experiments" / f"{EXPERIMENT}_contract.json"
    engine.SPEC = OS / "experiments" / f"{EXPERIMENT}_spec.json"
    engine.FREEZE = OS / "artifacts" / f"{EXPERIMENT}_stage_a_freeze.json"


def run() -> dict:
    configure()
    result = engine.run()
    labels = {
        "ANCHOR_COST_FIRST_DRY_PULLBACK_DEVELOPMENT_FAILED": "EXPANDING_PARTICIPATION_ANCHOR_BASE_TEST_DEVELOPMENT_FAILED",
        "ANCHOR_COST_FIRST_DRY_PULLBACK_EDGE": "EXPANDING_PARTICIPATION_ANCHOR_BASE_TEST_EDGE",
        "ANCHOR_COST_FIRST_DRY_PULLBACK_FAILED_FORWARD_OR_TARGET": "EXPANDING_PARTICIPATION_ANCHOR_BASE_TEST_FAILED_FORWARD_OR_TARGET",
    }
    result["verdict"] = labels.get(result["verdict"], result["verdict"])
    engine.core.write_json(engine.RESULT, result)
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
