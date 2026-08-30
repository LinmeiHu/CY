from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_style_data_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_style_data_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
audit = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(audit)


def test_frozen_spec_and_input_identities() -> None:
    spec = audit._load_spec()
    assert audit.sha256_file(audit.SPEC_PATH) == audit.EXPECTED_SPEC_SHA256
    observed = audit._verify_file_inputs(spec)
    assert observed == {name: item["sha256"] for name, item in spec["inputs"].items()}


def test_registry_preserves_circulating_vs_free_float_distinction() -> None:
    spec = audit._load_spec()
    assets = audit._registry_assets(spec)
    assert "circulating shares" in assets["CY-006"]["schema_and_units"].lower()
    assert "freeFloatCapital" not in assets["CY-006"]["schema_and_units"]
    assert "freeFloatCapital" in assets["QD-009"]["schema_and_units"]


def test_turnover_unit_helper() -> None:
    assert audit.turnover_matches(10.0, 100.0, 0.1, 1e-12)
    assert not audit.turnover_matches(10.0, 100.0, 10.0, 1e-12)
    assert not audit.turnover_matches(10.0, 0.0, 0.1, 1e-12)


def test_completed_artifact_boundaries_when_present() -> None:
    if not audit.RESULT_PATH.exists():
        return
    result = json.loads(audit.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["representation_claim"] == "NONE"
    assert result["usefulness_claim"] == "NONE"
    assert result["total_market_cap_claim"] == "NONE"
    assert result["true_free_float_cap_claim"] == "NONE"
    assert result["future_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
