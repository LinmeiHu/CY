from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_checkpoint_journal_hardening.py"
SPEC = importlib.util.spec_from_file_location(
    "validate_checkpoint_journal_hardening_capacity", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_capacity_workspace_fallback_and_rss_gates_are_explicit() -> None:
    report = MODULE.capacity_and_resource_report(
        MODULE.DEFAULT_PHASE5,
        MODULE.DEFAULT_CONTRACT,
        MODULE.DEFAULT_SOURCE / "summary.json",
        temporary_incremental_bytes_3symbol=1_000_000,
        existing_workspace_occupied_bytes=2_000_000,
        disk_free_bytes=100 * MODULE.GIB,
        available_memory_bytes=16 * MODULE.GIB,
        requested_workers=10,
    )

    assert report["fallback_rows"] == 0
    assert report["fallback_bytes"] == 0
    assert report["projected_point_gib"] <= 45
    assert report["projected_high_gib"] < 50
    assert report["workspace_preflight"] == "PASS"
    assert report["rss_preflight"] == "PASS"
    assert 1 <= report["authorized_workers"] <= 10


def test_workspace_preflight_fails_closed_when_free_space_is_insufficient() -> None:
    with pytest.raises(MODULE.HardeningError, match="insufficient free bytes"):
        MODULE.capacity_and_resource_report(
            MODULE.DEFAULT_PHASE5,
            MODULE.DEFAULT_CONTRACT,
            MODULE.DEFAULT_SOURCE / "summary.json",
            temporary_incremental_bytes_3symbol=1_000_000,
            existing_workspace_occupied_bytes=0,
            disk_free_bytes=1,
            available_memory_bytes=16 * MODULE.GIB,
            requested_workers=1,
        )


def test_capacity_overflow_fails_closed() -> None:
    with pytest.raises(MODULE.HardeningError, match="exceeds target"):
        MODULE.enforce_capacity(50.1, 50.1, 45.0, 50.0)
