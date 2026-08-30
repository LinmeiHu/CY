from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_ldr_001.py"
SPEC = ROOT / "research/market_behavior_os_v2/experiments/MKT-LDR-001_spec.json"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_ldr_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
ldr = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(ldr)


def test_spec_is_outcome_blind_and_no_rescue() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    forbidden = " ".join(spec["forbidden_inputs"])
    assert "future returns" in forbidden
    assert "CY-011" in forbidden
    assert spec["gates"]["joint_deterioration_requires_both_transition_roles"] is True
    assert spec["gates"]["no_rescue"].startswith("A failed primary")


def test_frozen_breadth_inputs_match() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert ldr.sha256_file(ROOT / spec["input"]["breadth_panel_path"]) == spec["input"]["breadth_panel_sha256"]
    assert ldr.sha256_file(ROOT / spec["input"]["breadth_result_path"]) == spec["input"]["breadth_result_sha256"]


def test_roles_separate_level_imbalance_from_change() -> None:
    assert set(ldr.ROLE_MAP) == {
        "concentration_decay", "discovery_deterioration",
        "leadership_discovery_imbalance",
    }
    assert len(ldr.ROLE_MAP["concentration_decay"][1]) == 4
    assert len(ldr.ROLE_MAP["discovery_deterioration"][1]) == 4
