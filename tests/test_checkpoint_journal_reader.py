from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from cyq_game.chip.checkpoint_journal_reader import (
    CheckpointJournalReadError,
    CheckpointJournalReader,
    DependencyCatalog,
    DependencyRecord,
    ReplayStep,
    derive_economic_bucket,
)
from cyq_game.chip.checkpoint_journal_writer import sha256_file
from cyq_game.chip.checkpoint_journal_contract import ContractError
from cyq_game.chip.journal_codec import JournalDay, decode_journal

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"


def _bundle(symbol: str) -> tuple[str, tuple[JournalDay, ...], dict[tuple[str, object], object]]:
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    rows: list[JournalDay] = []
    oracle: dict[tuple[str, object], object] = {}
    for part in manifest["parts"]:
        relative = part["relative_path"]
        if part["kind"] != "journal" or not relative.startswith(f"symbol={symbol}/"):
            continue
        logical = decode_journal((BUNDLE / relative).read_bytes())
        rows.extend(logical.rows)
        for row in logical.rows:
            oracle[(symbol, row.trading_date)] = row.model_digests
    return manifest["replay_parameter_manifest_digest"], tuple(rows), oracle


def _catalog(rows: tuple[JournalDay, ...]) -> DependencyCatalog:
    records = []
    seen = set()
    for row in rows:
        for reference in row.dependency_references:
            key = (
                reference.dependency_class,
                reference.asset_id,
                reference.snapshot_id,
            )
            if key in seen:
                continue
            seen.add(key)
            records.append(
                DependencyRecord(
                    dependency_class=reference.dependency_class,
                    asset_id=reference.asset_id,
                    snapshot_id=reference.snapshot_id,
                    content_digest=reference.content_digest,
                    inventory_digest=reference.inventory_digest,
                )
            )
    return DependencyCatalog(tuple(records))


class _OracleBackend:
    def __init__(self, oracle: dict[tuple[str, object], object], *, corrupt: bool = False) -> None:
        self.oracle = oracle
        self.corrupt = corrupt

    def restore_checkpoint(self, checkpoint: object) -> dict[str, object]:
        return {"symbol": checkpoint.symbol, "checkpoint": checkpoint}

    def advance_day(self, state: dict[str, object], row: JournalDay) -> ReplayStep:
        digests = self.oracle[(str(state["symbol"]), row.trading_date)]
        if self.corrupt:
            first = replace(digests[0], post_state_digest="0" * 64)
            digests = (first, *digests[1:])
        return ReplayStep(
            state={**state, "trading_date": row.trading_date},
            model_digests=digests,
        )


def test_reader_restores_opening_and_arbitrary_day_and_fails_on_replay_mismatch() -> None:
    digest, rows, oracle = _bundle("002260.SZ")
    reader = CheckpointJournalReader(
        BUNDLE,
        replay_parameter_manifest_digest=digest,
        dependency_catalog=_catalog(rows),
    )
    opening = reader.restore(
        "002260.SZ", rows[0].trading_date, backend=_OracleBackend(oracle)
    )
    assert opening.replayed_dates == ()
    target = rows[36].trading_date
    restored = reader.restore("002260.SZ", target, backend=_OracleBackend(oracle))
    assert restored.trading_date == target
    assert restored.model_digests == oracle[("002260.SZ", target)]
    with pytest.raises(CheckpointJournalReadError, match="state digest mismatch"):
        reader.restore("002260.SZ", target, backend=_OracleBackend(oracle, corrupt=True))


def test_reader_fails_closed_for_missing_and_mismatched_dependencies() -> None:
    digest, rows, oracle = _bundle("002260.SZ")
    target = rows[1].trading_date
    missing = CheckpointJournalReader(
        BUNDLE,
        replay_parameter_manifest_digest=digest,
        dependency_catalog=DependencyCatalog(()),
    )
    with pytest.raises(CheckpointJournalReadError, match="dependency is missing"):
        missing.restore("002260.SZ", target, backend=_OracleBackend(oracle))
    first = rows[0].dependency_references[0]
    bad = DependencyRecord(
        dependency_class=first.dependency_class,
        asset_id=first.asset_id,
        snapshot_id=first.snapshot_id,
        content_digest="0" * 64,
        inventory_digest=first.inventory_digest,
    )
    mismatched = CheckpointJournalReader(
        BUNDLE,
        replay_parameter_manifest_digest=digest,
        dependency_catalog=DependencyCatalog((bad,)),
    )
    with pytest.raises(CheckpointJournalReadError, match="digest mismatch"):
        mismatched.restore("002260.SZ", rows[0].trading_date, backend=_OracleBackend(oracle))


def test_reader_fails_closed_for_parameter_and_unknown_root_version() -> None:
    digest, rows, _ = _bundle("002260.SZ")
    with pytest.raises(CheckpointJournalReadError, match="parameter manifest mismatch"):
        CheckpointJournalReader(
            BUNDLE,
            replay_parameter_manifest_digest="0" * 64,
            dependency_catalog=_catalog(rows),
        )
    temp = Path(tempfile.mkdtemp(prefix="v12_checkpoint_journal_phase3_", dir="/tmp"))
    try:
        manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
        manifest["artifact_version"] = "unknown-version"
        (temp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(CheckpointJournalReadError, match="unknown or mixed"):
            CheckpointJournalReader(
                temp,
                replay_parameter_manifest_digest=digest,
                dependency_catalog=_catalog(rows),
            )
    finally:
        shutil.rmtree(temp)


def test_reader_fails_closed_for_mixed_index_version() -> None:
    digest, rows, _ = _bundle("002260.SZ")
    temp = Path(tempfile.mkdtemp(prefix="v12_checkpoint_journal_phase3_", dir="/tmp"))
    copied = temp / "bundle"
    try:
        shutil.copytree(BUNDLE, copied, copy_function=os.link)
        manifest_path = copied / "manifest.json"
        manifest_path.unlink()
        shutil.copy2(BUNDLE / "manifest.json", manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        index_path = copied / manifest["index_path"]
        index_path.unlink()
        shutil.copy2(BUNDLE / manifest["index_path"], index_path)
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["rows"][0]["storage_version"] = "unknown-mixed-storage"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        manifest["index_sha256"] = sha256_file(index_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ContractError, match="version|digest"):
            CheckpointJournalReader(
                copied,
                replay_parameter_manifest_digest=digest,
                dependency_catalog=_catalog(rows),
            )
    finally:
        shutil.rmtree(temp)


def test_canonical_economic_bits_have_one_frozen_deterministic_derivation() -> None:
    bits = 4618404864918200488
    assert derive_economic_bucket(
        bits, coordinate_version="causal-economic-price-v2"
    ) == 715
    assert derive_economic_bucket(
        bits, coordinate_version="causal-economic-price-v2"
    ) == 715
    with pytest.raises(CheckpointJournalReadError, match="coordinate version"):
        derive_economic_bucket(bits, coordinate_version="unknown")
