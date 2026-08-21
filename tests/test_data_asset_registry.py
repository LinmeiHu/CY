from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_validator() -> ModuleType:
    path = ROOT / "scripts" / "validate_data_registry.py"
    spec = importlib.util.spec_from_file_location("validate_data_registry", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_data_asset_registry_schema_is_valid() -> None:
    validator = load_validator()
    registry = validator.load_registry(ROOT / "configs" / "data_asset_registry.json")
    errors = validator.validate_registry(registry, verify_paths=False, verify_hashes=False)
    assert errors == []


def test_unregistered_or_unsafe_statuses_are_not_input_capable() -> None:
    validator = load_validator()
    registry = validator.load_registry(ROOT / "configs" / "data_asset_registry.json")
    unsafe = {"QA_ONLY", "DISCOVERY_ONLY", "DEMO_ONLY", "GENERATED_OUTPUT", "UNAVAILABLE"}
    assert unsafe.isdisjoint(validator.INPUT_CAPABLE_STATUS)
    gate = registry["global_gate"]
    assert isinstance(gate["backtest_authorized"], bool)
    assert not gate["backtest_authorized"] or (
        gate["free_causal_research_ready"] or gate["strict_archival_pit_ready"]
    )
