"""Regression locks for the preregistered ChinNext V1 Gate C pilot."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "research/chinext_v1/scripts/run_chinext_v1_gate_c.py"


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chinext_v1_gate_c_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_c_exact_committed_spec_passes_without_performance() -> None:
    runner = load_runner()
    result = runner.finalize_determinism(runner.build_result(), runner.build_result())
    assert result["gate_c_result"] == "PASS"
    assert result["counts"] == {
        "authorization_violation_count": 0,
        "determinism_mismatch_count": 0,
        "hash_failure_count": 0,
        "required_invariant_mismatch_count": 0,
        "required_unknown_state_count": 0,
    }
    assert not any(result["execution_firewall"].values())
    assert len(result["invariant_checks"]) == 15
    assert all(item["status"] == "PASS" for item in result["invariant_checks"])


def test_gate_c_canonical_result_is_deterministic() -> None:
    runner = load_runner()
    assert runner.canonical_bytes(runner.build_result()) == runner.canonical_bytes(
        runner.build_result()
    )


def test_gate_c_rejects_changed_bound_input_before_reading_it() -> None:
    runner = load_runner()
    spec = runner.load_spec()
    spec["input_bindings"]["historical_state_daily"]["sha256"] = "0" * 64
    with pytest.raises(runner.GateCError, match="frozen input hash failure"):
        runner.validate_input_hashes(spec)
