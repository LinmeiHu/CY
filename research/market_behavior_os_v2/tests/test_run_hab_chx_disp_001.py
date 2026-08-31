from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_hab_chx_disp_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_hab_chx_disp_001_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_post_discovery_contract_preserves_consumed_only_boundary() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert "inspected before" in spec["honesty_boundary"]
    assert spec["expected_complete_rows"] == {
        "DAILY_PROCESS": 815,
        "EVALUATED_EVENT": 515,
        "COMPLETED_CYCLE": 192,
    }
    assert spec["descriptive_boundaries"]["cluster_bootstrap_seed"] == 20260831
    prohibited = "|".join(spec["prohibited"])
    assert "CHINEXT V1 rule" in prohibited
    assert "post-2023" in prohibited
    assert "CY-011" in prohibited


def test_completed_archaeology_has_no_setup_or_rule_transfer() -> None:
    result_path = PROGRAM / "artifacts/HAB-CHX-DISP-001_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["classification"] == (
        "NO_CHINEXT_SETUP_TRANSFER_ADVERSE_PAYOFF_EXPLORE_ASSOCIATION"
    )
    assert result["interpretation"]["setup_transfer"] is False
    assert result["interpretation"]["adverse_payoff_supported"] is True
    assert result["interpretation"]["chinext_rule_change"] is False
    assert result["interpretation"]["dispersion_relative_value_candidate_changed"] is False
    assert result["strategy_outcomes_newly_consumed"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
