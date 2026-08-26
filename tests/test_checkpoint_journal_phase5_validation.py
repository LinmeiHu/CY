from __future__ import annotations

import importlib.util
import math
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "configs/v12_checkpoint_recompute_50_symbols_v1.txt"
EVIDENCE = ROOT / "data/validation/v12_checkpoint_recompute_50_v1"
SCRIPT = ROOT / "scripts/validate_checkpoint_journal_50symbol.py"
SPEC = importlib.util.spec_from_file_location("validate_checkpoint_journal_50symbol", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ValidationError = MODULE.ValidationError
read_sample_symbols = MODULE.read_sample_symbols
validate = MODULE.validate


def test_frozen_50_symbol_checkpoint_journal_evidence_passes_all_fixed_gates() -> None:
    summary = validate(SAMPLE, EVIDENCE)

    assert summary["status"] == "PASS"
    assert summary["sample"] == {
        "configured_symbols": 50,
        "completed_symbols": 50,
        "failed_symbols": 0,
        "missing_symbols": [],
        "duplicate_symbols": [],
        "unexpected_symbols": [],
    }
    assert summary["fixed_gates_total"] == 14
    assert summary["fixed_gates_passed"] == 14
    assert summary["fixed_gates_failed"] == 0
    assert summary["exactness"]["exact_mismatch_count"] == 0
    assert summary["exactness"]["daily_state_share_comparisons"] == 36_450
    assert summary["exactness"]["lifecycle_comparisons"] == 36_450
    assert summary["artifacts"]["checkpoint_files"] == 650
    assert summary["artifacts"]["journal_files"] == 50
    assert summary["artifacts"]["symbol_payload_bytes"] == 388_253_116
    assert summary["artifacts"]["root_bytes"] == 388_334_273

    capacity = summary["capacity"]
    assert capacity["not_a_population_confidence_interval"] is True
    assert capacity["cannot_pass_production_capacity"] is True
    raw_3941 = capacity["raw_checkpoint_journal_manifest_gib"]["3941"]
    assert math.isclose(raw_3941["low"], 26.598306925351107, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(raw_3941["point"], 28.500436435565355, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(raw_3941["high"], 30.4025659457796, rel_tol=0, abs_tol=1e-12)
    scenario_b = capacity["scenario_b_physical_compatibility_terminal_gib"]["5210"]
    assert scenario_b["point"] <= 45.0
    assert 45.0 < scenario_b["high"] < 50.0
    assert capacity["capacity_result"] == "TARGET_POINT_PASS_ENGINEERING_HIGH_WARNING"


def test_sample_symbol_contract_fails_closed_on_duplicate() -> None:
    symbols = SAMPLE.read_text(encoding="utf-8").splitlines()
    symbols[-1] = symbols[0]
    with tempfile.TemporaryDirectory(
        prefix="v12_checkpoint_journal_phase5_", dir="/tmp"
    ) as directory:
        duplicate = Path(directory) / "duplicate.txt"
        duplicate.write_text("\n".join(symbols) + "\n", encoding="utf-8")

        with pytest.raises(ValidationError, match="duplicate symbols"):
            read_sample_symbols(duplicate)
