from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from cyq_game.chip.checkpoint_journal_writer import activate_production_bundle
from cyq_game.data.registry import (
    CheckpointJournalRegistration,
    DataActivationError,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def test_dependency_bindings_reverse_references_and_active_gc_fail_closed() -> None:
    temp = Path(tempfile.mkdtemp(prefix="v12_checkpoint_journal_phase4_", dir="/tmp"))
    output = temp / "year=2020"
    try:
        activate_production_bundle(SOURCE, output)
        path = output / "dependency_registry.json"
        registration = CheckpointJournalRegistration.load(path)
        roles = {item.role for item in registration.dependencies}
        assert {
            "daily_input",
            "minute_input",
            "corporate_action_input",
            "replay_parameter_manifest",
            "feature",
            "terminal_compatibility",
        } <= roles
        assert registration.active is True
        for dependency in registration.dependencies:
            assert dependency.immutable is True
            assert dependency.pinned is True
            with pytest.raises(DataActivationError, match="prevents dependency GC"):
                registration.assert_dependency_gc_allowed(dependency.key)
        assert registration.release_order() == (
            "DEACTIVATE_BUNDLE",
            "REMOVE_REVERSE_REFERENCES",
            "RELEASE_DEPENDENCY_PINS",
        )

        corrupt = json.loads(path.read_text(encoding="utf-8"))
        corrupt["reverse_references"].pop(next(iter(corrupt["reverse_references"])))
        digest_payload = dict(corrupt)
        digest_payload.pop("registry_digest")
        corrupt["registry_digest"] = _digest(digest_payload)
        path.write_text(json.dumps(corrupt), encoding="utf-8")
        with pytest.raises(DataActivationError, match="reverse references are corrupt"):
            CheckpointJournalRegistration.load(path)
    finally:
        shutil.rmtree(temp)
