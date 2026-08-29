"""Input-only regression locks for the ChinNext V1 extended replay wrapper."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "research/chinext_v1/scripts/run_chinext_v1_extended_replay.py"
SPEC = ROOT / "research/chinext_v1/specs/chinext_v1_extended_replay_preregistration.json"


def load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chinext_v1_extended_replay", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transient_extended_inputs_are_complete_and_nonpersistent(tmp_path: Path) -> None:
    runner = load_runner()
    manifest = runner.materialize_transient_inputs(tmp_path)
    assert manifest["persistent_duplicate_daily_store"] is False
    assert manifest["panel"]["warmup_rows"] == 120642
    assert manifest["panel"]["target_rows"] == 803907
    assert manifest["membership"]["rows"] == 803527
    assert manifest["membership"]["date_count"] == 973
    assert manifest["membership"]["unique_symbols"] == 1097
    assert (
        manifest["membership"]["earliest_safe_use_semantics"]
        == "PRIOR_SESSION_STATE_AVAILABLE_ON_NEXT_QD003_SESSION"
    )
    assert manifest["target_direct_fail_closed_overlay"]
    assert len(manifest["canonical_sha256"]) == 64
    assert (tmp_path / "daily_membership.parquet").is_file()
    assert all(
        (tmp_path / item["relative_path"]).is_file()
        for item in manifest["panel"]["partitions"]
    )


def test_transient_input_build_is_byte_deterministic(tmp_path: Path) -> None:
    runner = load_runner()
    first = runner.materialize_transient_inputs(tmp_path / "first")
    second = runner.materialize_transient_inputs(tmp_path / "second")
    assert first == second


def test_formal_replay_contract_is_frozen_before_performance(tmp_path: Path) -> None:
    runner = load_runner()
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    prepared = runner.materialize_transient_inputs(tmp_path)
    assert spec["status"] == "FROZEN_BEFORE_FIRST_VIEW_REPLAY"
    assert spec["first_view_execution_count"] == 1
    assert spec["strategy_sha256"] == hashlib.sha256(runner.STRATEGY.read_bytes()).hexdigest()
    assert spec["runner_sha256"] == hashlib.sha256(RUNNER.read_bytes()).hexdigest()
    runner.validate_prepared_manifest(prepared, spec)
    assert spec["sample_chronology"]["2022_2025"] == "REVISION_HOLDBACK_NOT_USED_FOR_V2_SELECTION"
