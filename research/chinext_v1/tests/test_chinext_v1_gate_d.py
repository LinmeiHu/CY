"""Regression locks for the committed ChinNext V1 Gate D validation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "research/chinext_v1/scripts/run_chinext_v1_gate_d.py"
RESULT = ROOT / "research/chinext_v1/reports/chinext_v1_gate_d_result.json"


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chinext_v1_gate_d_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_d_frozen_result_passes_without_performance() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["gate_d_result"] == "PASS"
    assert result["safe_to_run_extended_history_strategy_replay"] == "YES"
    assert result["strategy_input_requirement_matrix_status"] == "PASS"
    assert result["zero_tolerance_pass"] is True
    assert not any(result["execution_firewall"].values())
    assert result["logical_materialization"]["deterministic"] is True


def test_gate_d_committed_spec_and_bound_hashes_are_exact() -> None:
    runner = load_runner()
    spec = runner.load_spec()
    hashes, _ = runner.validate_bindings(spec)
    assert hashes


def test_gate_d_rejects_changed_gate_c_result_hash() -> None:
    runner = load_runner()
    spec = runner.load_spec()
    spec["input_bindings"]["gate_c_result"]["sha256"] = "0" * 64
    with pytest.raises(runner.GateDError, match="input binding failed"):
        runner.validate_bindings(spec)
