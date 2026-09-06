#!/usr/bin/env python3
"""Re-run recoverable stock-strategy layers into the isolated reproduction root."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "research/market_behavior_os_v2/scripts"
DEFAULT_OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research/five_strategy_reproduction_v1")
MATCHED_REGISTRY = Path(
    "/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830/configs/data_asset_registry.json"
)


def ensure_isolated(output_root: Path) -> Path:
    resolved = output_root.resolve()
    allowed = DEFAULT_OUTPUT_ROOT.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ValueError(f"output must stay below the reproduction root: {allowed}")
    return resolved


def run_ogr(output_root: Path) -> dict[str, object]:
    from research.market_behavior_os_v2.scripts import (
        run_ashare_true_gap_below_l_orderly_demand_v28r2 as runner,
    )

    target = output_root / "ogr"
    runner.EXT_ROOT = target
    runner.v28.CY033_REGISTRY = MATCHED_REGISTRY
    runner.CONTRACT = target / "metadata/contract.json"
    runner.SPEC = target / "metadata/spec.json"
    runner.STAGE_A_FREEZE = target / "metadata/stage_a_freeze.json"
    runner.DEVELOPMENT_RESULT = target / "metadata/development_result.json"
    runner.REPORT = target / "metadata/report.md"
    return {"stage_a": runner.run_stage_a(), "development": runner.run_development()}


def run_mcb(output_root: Path) -> dict[str, object]:
    sys.path.insert(0, str(SCRIPTS))
    import run_ashare_bull_cross_board_confirmation_v72 as runner

    target = output_root / "mcb"
    runner.EXT = target
    mapping = {
        "CANDIDATES": "stage_a/candidates.parquet",
        "BLIND_INDEX": "stage_a/blind_index.csv",
        "BLIND_DIR": "stage_a/blind_charts",
        "DEV_OUTCOMES": "stage_b/development_outcomes.parquet",
        "FORWARD_OUTCOMES": "stage_b/forward_outcomes.parquet",
        "DEV_ACCEPTED": "stage_b/development_accepted.parquet",
        "DEV_SKIPPED": "stage_b/development_skipped.parquet",
        "DEV_NAV": "stage_b/development_nav.parquet",
        "ACCEPTED": "stage_b/combined_accepted.parquet",
        "SKIPPED": "stage_b/combined_skipped.parquet",
        "NAV": "stage_b/combined_nav.parquet",
        "FREEZE": "metadata/stage_a_freeze.json",
        "RESULT": "metadata/result.json",
        "REPORT": "metadata/report.md",
    }
    for name, relative in mapping.items():
        setattr(runner, name, target / relative)
    return {"stage_a": runner.run_stage_a(), "stage_b": runner.run_stage_b()}


def run_atrdr(output_root: Path) -> dict[str, object]:
    sys.path.insert(0, str(SCRIPTS))
    import run_ashare_simple_regime_complementary_demand_router_v29 as runner

    target = output_root / "atrdr"
    runner.EXT = target
    mapping = {
        "RAW_CANDIDATES": "stage_a/raw_simple_bull_candidates.parquet",
        "CANDIDATES": "stage_a/simple_bull_candidates.parquet",
        "OUTCOME_SHARDS": "stage_b/outcome_shards",
        "OUTCOMES": "stage_b/simple_bull_outcomes.parquet",
        "SOURCE_UNION": "stage_b/source_completed_trades.parquet",
        "DAILY_PATHS": "stage_b/daily_paths.parquet",
        "ACCEPTED": "stage_b/accepted_trades.parquet",
        "SKIPPED": "stage_b/capacity_skips.parquet",
        "NAV": "stage_b/portfolio_nav.parquet",
        "FREEZE": "metadata/stage_a_freeze.json",
    }
    for name, relative in mapping.items():
        setattr(runner, name, target / relative)
    stage_a = runner.run_stage_a()
    candidates = runner.v28.parse_dates(runner.pd.read_parquet(runner.CANDIDATES))
    outcomes, outcome_audit = runner.build_outcomes(candidates)
    bear_compat = target / "bear_source_compat.parquet"
    if not bear_compat.is_file():
        raise FileNotFoundError(
            "read-only DuckDB compatibility copy of the frozen V28 Bear input is missing: "
            f"{bear_compat}"
        )
    runner.V28_FROZEN_SOURCE = bear_compat
    trades, union_audit = runner.assemble_union(outcomes, candidates)
    accepted, skipped, nav, paths, replay_audit = runner.shared_replay(trades)
    execution_audit = runner.v28.execution_audit(accepted, paths)
    audits = {**outcome_audit, **union_audit, **replay_audit, **execution_audit}
    if any(audits.values()):
        raise runner.ResearchError(f"ATRDR audit failed: {audits}")
    return {
        "stage_a": stage_a,
        "outcomes": len(outcomes),
        "union": len(trades),
        "accepted": len(accepted),
        "skipped": len(skipped),
        "nav_rows": len(nav),
        "audit": audits,
        "bear_parent": "FROZEN_V28_COMPATIBILITY_COPY",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strategy", choices=("ogr", "mcb", "atrdr"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = ensure_isolated(args.output_root)
    result = {"ogr": run_ogr, "mcb": run_mcb, "atrdr": run_atrdr}[args.strategy](output_root)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
