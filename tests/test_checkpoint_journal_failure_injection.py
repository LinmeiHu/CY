from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_checkpoint_journal_hardening.py"
SPEC = importlib.util.spec_from_file_location("validate_checkpoint_journal_hardening", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_all_fixed_faults_fail_closed_without_silent_repair() -> None:
    summary = MODULE.run_validation(
        MODULE.DEFAULT_SOURCE,
        MODULE.DEFAULT_PHASE5,
        MODULE.DEFAULT_CONTRACT,
    )

    assert summary["status"] == "PASS"
    assert summary["fixed_faults_total"] == 18
    assert summary["fixed_faults_passed"] == 18
    assert tuple(item["fault"] for item in summary["faults"]) == MODULE.FIXED_FAULTS
    assert all(item["status"] == "PASS_FAIL_CLOSED" for item in summary["faults"])
    assert all(item["silent_repair"] is False for item in summary["faults"])
    reverse = next(
        item for item in summary["faults"] if item["fault"] == "reverse-reference corruption"
    )
    assert len(reverse["variants"]) == 6
    assert summary["fixed_gates_total"] == 11
    assert summary["fixed_gates_passed"] == 11
    assert summary["fixed_gates_failed"] == 0
