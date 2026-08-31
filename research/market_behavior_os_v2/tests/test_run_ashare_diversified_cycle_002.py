from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPT = PROGRAM / "scripts/run_ashare_diversified_cycle_002.py"
RESULT = PROGRAM / "artifacts/ASHARE-DIVERSIFIED-CYCLE-002_result.json"
MODULE_SPEC = importlib.util.spec_from_file_location("ashare_diversified_cycle", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = MODULE
MODULE_SPEC.loader.exec_module(MODULE)


def test_frozen_translation_and_second_batch_contract() -> None:
    spec = MODULE._load_spec()
    assert spec["track_a"]["single_translation"]["leading_industries"] == 3
    assert spec["track_a"]["single_translation"]["securities_per_industry"] == 5
    assert spec["track_a"]["alpha_frozen"]["holding_sessions"] == 20
    assert len(spec["track_b_families"]) == 7
    assert spec["track_b_promotion"]["maximum_families"] == 2
    assert spec["shared_contract"]["research_end"] == "2023-12-29"


def test_result_preserves_fail_closed_execution_boundary() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["track_a"]["status"] == "PARKED"
    assert result["track_a"]["diversified_portfolio"]["status"] == "BLOCKED_DATA_CONTRACT"
    assert result["track_a"]["diversified_portfolio"][
        "partial_equity_is_not_strategy_economics"
    ]
    assert result["track_b_promoted"] == [
        "industry_diffusion_20",
        "low_idiosyncratic_volatility_20",
    ]
    assert all(row["status"] == "BLOCKED_DATA_CONTRACT" for row in result["track_b_replays"])
    assert all(row["partial_equity_is_not_strategy_economics"] for row in result["track_b_replays"])
    assert result["boundaries"]["post_2023_read"] is False
    assert result["boundaries"]["cy011_read"] is False
