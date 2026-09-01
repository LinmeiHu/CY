from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_champion_anatomy_cycle_016.py"
)
RESULT = (
    ROOT
    / "research/market_behavior_os_v2/artifacts/"
    "ASHARE-CHAMPION-ANATOMY-CYCLE-016_result.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("champion_anatomy_cycle_016_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_is_diagnostic_and_freezes_strategy() -> None:
    spec = _module()._load_spec()
    assert spec["champion"]["changes_authorized"] is False
    assert "Top-10" in spec["champion"]["breadth"]
    assert "20-session" in spec["champion"]["holding"]
    assert spec["champion"]["cost_per_side"] == 0.002
    assert spec["track_a_lifecycle"]["checkpoints"] == [1, 3, 5, 10, 15, 20]


def test_accepted_result_reproduces_champion_and_authorizes_no_change() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    champion = result["champion_identity"]
    assert abs(champion["total_return"] - 1.224346371517719) < 1e-12
    assert abs(champion["daily_sharpe"] - 0.7314535145871504) < 1e-12
    assert champion["completed_trades"] == 2625
    assert result["alpha_lifecycle"]["classification"] == "FULL_HORIZON_PERSISTENT"
    assert result["rank_anatomy"]["classification"] == "BREADTH_ECONOMICALLY_SUPPORTED"
    assert result["opportunity_richness"]["authorized"] is False
    assert result["industry_thesis_persistence"]["authorized"] is False
    assert result["structural_decision"] == "NO_CHAMPION_MODIFICATION_RETURN_TO_INDEPENDENT_ALPHA"
    assert result["final_classification"] == "CONCENTRATED_BUT_ECONOMICALLY_MEANINGFUL"


def test_boundaries_keep_quarantine_and_prohibit_strategy_replays() -> None:
    boundaries = json.loads(RESULT.read_text(encoding="utf-8"))["boundaries"]
    assert boundaries == {
        "cy011_read": False,
        "exit_replay": False,
        "new_alpha_discovery": False,
        "oos_claim": False,
        "post_2023_read": False,
        "strategy_changed": False,
        "top_n_replay": False,
    }
