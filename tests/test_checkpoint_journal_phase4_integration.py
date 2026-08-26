from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from cyq_game.chip.checkpoint_journal_contract import STORAGE_VERSION
from cyq_game.chip.checkpoint_journal_reader import (
    CheckpointJournalReadError,
    CheckpointJournalReader,
    DependencyCatalog,
    DependencyRecord,
)
from cyq_game.chip.checkpoint_journal_writer import (
    activate_production_bundle,
    sha256_file,
)
from cyq_game.chip.journal_codec import decode_journal
from cyq_game.data.registry import CheckpointJournalRegistration

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"
BUILDER = ROOT / "scripts/build_real_chip_year.py"


def _temporary() -> Path:
    return Path(tempfile.mkdtemp(prefix="v12_checkpoint_journal_phase4_", dir="/tmp"))


def _catalog(symbol: str) -> DependencyCatalog:
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    records = {}
    for part in manifest["parts"]:
        if part["kind"] != "journal" or not part["relative_path"].startswith(
            f"symbol={symbol}/"
        ):
            continue
        for row in decode_journal((SOURCE / part["relative_path"]).read_bytes()).rows:
            for reference in row.dependency_references:
                key = (
                    reference.dependency_class,
                    reference.asset_id,
                    reference.snapshot_id,
                )
                records.setdefault(
                    key,
                    DependencyRecord(
                        dependency_class=reference.dependency_class,
                        asset_id=reference.asset_id,
                        snapshot_id=reference.snapshot_id,
                        content_digest=reference.content_digest,
                        inventory_digest=reference.inventory_digest,
                    ),
                )
    return DependencyCatalog(tuple(records.values()))


def test_explicit_production_cli_uses_one_shared_stream_and_is_part_exact() -> None:
    temp = _temporary()
    output = temp / "year=2020"
    try:
        command = [
            sys.executable,
            str(BUILDER),
            "--year",
            "2020",
            "--storage-format",
            STORAGE_VERSION,
            "--checkpoint-journal-source",
            str(SOURCE),
            "--output",
            str(output),
        ]
        subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
        source_manifest = json.loads(
            (SOURCE / "manifest.json").read_text(encoding="utf-8")
        )
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["artifact_version"] == "v12-chip-bundle-checkpoint-journal-v1"
        assert manifest["registered"] is True
        assert manifest["registry_modified"] is True
        assert [(part["relative_path"], part["sha256"]) for part in manifest["parts"]] == [
            (part["relative_path"], part["sha256"])
            for part in source_manifest["parts"]
        ]
        assert all(
            sha256_file(output / part["relative_path"]) == part["sha256"]
            for part in manifest["parts"]
        )
        integration = json.loads(
            (output / "production_integration.json").read_text(encoding="utf-8")
        )
        assert integration["transition_count_per_model_day"] == 1
        assert integration["shared_state_stream_consumers"] == [
            "checkpoint_journal",
            "daily_feature",
            "terminal_compatibility",
        ]
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert summary["exact_mismatch_count"] == 0
        assert summary["transition_count_per_model_day"] == 1

        registration = CheckpointJournalRegistration.load(
            output / "dependency_registry.json"
        )
        digest = manifest["replay_parameter_manifest_digest"]
        CheckpointJournalReader(
            output,
            replay_parameter_manifest_digest=digest,
            dependency_catalog=_catalog("002260.SZ"),
            registration=registration,
        )
        with pytest.raises(CheckpointJournalReadError, match="registration"):
            CheckpointJournalReader(
                output,
                replay_parameter_manifest_digest=digest,
                dependency_catalog=_catalog("002260.SZ"),
            )

        resumed = activate_production_bundle(SOURCE, output)
        assert resumed["resume_fingerprint"] == summary["resume_fingerprint"]
        integration["resume_fingerprint"] = "0" * 64
        (output / "production_integration.json").write_text(
            json.dumps(integration), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="resume fingerprint mismatch"):
            activate_production_bundle(SOURCE, output)
    finally:
        shutil.rmtree(temp)


def test_legacy_is_default_and_new_storage_must_be_explicit() -> None:
    help_result = subprocess.run(
        [sys.executable, str(BUILDER), "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "legacy-operator" in help_result.stdout
    assert STORAGE_VERSION in help_result.stdout
    rejected = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--year",
            "2020",
            "--checkpoint-journal-source",
            str(SOURCE),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "requires explicit" in rejected.stderr
