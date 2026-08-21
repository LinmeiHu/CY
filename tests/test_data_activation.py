from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from cyq_game.data import (
    DataActivationError,
    DataAssetRegistry,
    DataOperation,
    InputSnapshotManifest,
    PITStore,
)
from cyq_game.domain import Bar


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_registry(
    root: Path,
    *,
    asset_status: str,
    pit_grade: str = "B",
    causal_ready: bool = False,
    backtest_authorized: bool = False,
) -> tuple[Path, Path]:
    data_dir = root / "registered"
    data_dir.mkdir()
    data_path = data_dir / "bars.csv"
    data_path.write_text("symbol,trade_date\n000001.SZ,2024-01-02\n", encoding="utf-8")
    registry_path = root / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "registry_id": "TEST-REGISTRY-1",
                "global_gate": {
                    "strict_archival_pit_ready": False,
                    "free_causal_research_ready": causal_ready,
                    "backtest_authorized": backtest_authorized,
                },
                "assets": [
                    {
                        "asset_id": "TEST-001",
                        "name": "activation fixture",
                        "kind": "market_bars_daily",
                        "status": asset_status,
                        "pit_grade": pit_grade,
                        "physical_state": "MATERIALIZED",
                        "location": str(data_dir),
                        "source": "test fixture",
                        "lineage": {},
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return registry_path, data_path


def _write_manifest(
    root: Path,
    *,
    registry: DataAssetRegistry,
    data_path: Path,
    purpose: str,
    hard_valid: bool,
    role: str = "daily_bars",
    audit_status: str = "PASS",
) -> Path:
    audits = {
        name: {
            "status": audit_status,
            "evidence": f"tests/evidence/{name}.json" if audit_status == "PASS" else "",
        }
        for name in (
            "coverage",
            "duplicates",
            "time_travel",
            "consistency",
            "cross_table",
        )
    }
    payload: dict[str, Any] = {
        "manifest_id": f"TEST-SNAPSHOT-{purpose}",
        "registry_id": registry.registry_id,
        "registry_sha256": registry.sha256,
        "purpose": purpose,
        "hard_valid": hard_valid,
        "scope": {"start": "2024-01-01", "end": "2024-03-31"},
        "bindings": [
            {
                "role": role,
                "asset_id": "TEST-001",
                "path": str(data_path),
                "source": "frozen-test-source",
                "snapshot_id": "snapshot-2024q1",
                "available_at_policy": "explicit record timestamp",
                "sha256": _sha256(data_path),
            }
        ],
        "audits": audits,
    }
    manifest_path = root / f"manifest-{purpose.lower()}.json"
    manifest_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return manifest_path


def _write_inventory(
    root: Path,
    *,
    bound_root: Path,
    files: tuple[Path, ...],
    inventory_root: Path | None = None,
) -> Path:
    inventory_path = root / "file-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "root": str(inventory_root or bound_root),
                "files": [
                    {
                        "path": path.relative_to(bound_root).as_posix(),
                        "size": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                    for path in files
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return inventory_path


def _convert_binding_to_directory(
    manifest_path: Path,
    *,
    data_path: Path,
    inventory_path: Path,
) -> None:
    payload: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    binding = payload["bindings"][0]
    binding["path"] = str(data_path.parent)
    binding.pop("sha256")
    binding["inventory_manifest"] = str(inventory_path)
    binding["inventory_sha256"] = _sha256(inventory_path)
    manifest_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_software_test_requires_explicit_authorization_and_frozen_range(
    tmp_path: Path,
) -> None:
    registry_path, data_path = _write_registry(tmp_path, asset_status="DEMO_ONLY")
    registry = DataAssetRegistry.load(registry_path)
    manifest_path = _write_manifest(
        tmp_path,
        registry=registry,
        data_path=data_path,
        purpose="SOFTWARE_TEST",
        hard_valid=True,
    )
    manifest = InputSnapshotManifest.load(manifest_path, registry=registry)

    with pytest.raises(DataActivationError, match="explicit software_test"):
        manifest.authorize(DataOperation.INGEST, registry=registry)

    authorization = manifest.authorize(
        DataOperation.STATE_GENERATION,
        registry=registry,
        software_test=True,
    )
    assert authorization.scope_start == date(2024, 1, 1)
    assert authorization.scope_end == date(2024, 3, 31)
    manifest.require_range(date(2024, 2, 1), date(2024, 2, 29))
    manifest.require_range(date(2024, 1, 1), date(2024, 3, 31), exact=True)
    with pytest.raises(DataActivationError, match="exactly match"):
        manifest.require_range(date(2024, 2, 1), date(2024, 2, 29), exact=True)
    with pytest.raises(DataActivationError, match="outside"):
        manifest.require_range(date(2023, 12, 31), date(2024, 2, 29))


def test_file_tampering_invalidates_the_input_snapshot(tmp_path: Path) -> None:
    registry_path, data_path = _write_registry(tmp_path, asset_status="DEMO_ONLY")
    registry = DataAssetRegistry.load(registry_path)
    manifest_path = _write_manifest(
        tmp_path,
        registry=registry,
        data_path=data_path,
        purpose="SOFTWARE_TEST",
        hard_valid=True,
    )
    InputSnapshotManifest.load(manifest_path, registry=registry)

    data_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(DataActivationError, match="file hash mismatch"):
        InputSnapshotManifest.load(manifest_path, registry=registry)


def test_directory_inventory_rehashes_each_selected_file(tmp_path: Path) -> None:
    registry_path, data_path = _write_registry(tmp_path, asset_status="DEMO_ONLY")
    registry = DataAssetRegistry.load(registry_path)
    manifest_path = _write_manifest(
        tmp_path,
        registry=registry,
        data_path=data_path,
        purpose="SOFTWARE_TEST",
        hard_valid=True,
    )
    inventory_path = _write_inventory(
        tmp_path,
        bound_root=data_path.parent,
        files=(data_path,),
    )
    _convert_binding_to_directory(
        manifest_path,
        data_path=data_path,
        inventory_path=inventory_path,
    )
    manifest = InputSnapshotManifest.load(manifest_path, registry=registry)
    binding = manifest.binding("daily_bars")

    assert binding.verify_file(data_path) == data_path.resolve()
    original_size = data_path.stat().st_size
    data_path.write_bytes(b"x" * original_size)
    with pytest.raises(DataActivationError, match="selected file hash mismatch"):
        binding.verify_file(data_path)


def test_directory_inventory_rejects_an_unlisted_file(tmp_path: Path) -> None:
    registry_path, data_path = _write_registry(tmp_path, asset_status="DEMO_ONLY")
    unlisted_path = data_path.parent / "unlisted.parquet"
    unlisted_path.write_bytes(b"not frozen")
    registry = DataAssetRegistry.load(registry_path)
    manifest_path = _write_manifest(
        tmp_path,
        registry=registry,
        data_path=data_path,
        purpose="SOFTWARE_TEST",
        hard_valid=True,
    )
    inventory_path = _write_inventory(
        tmp_path,
        bound_root=data_path.parent,
        files=(data_path,),
    )
    _convert_binding_to_directory(
        manifest_path,
        data_path=data_path,
        inventory_path=inventory_path,
    )
    binding = InputSnapshotManifest.load(
        manifest_path,
        registry=registry,
    ).binding("daily_bars")

    with pytest.raises(DataActivationError, match="absent from inventory"):
        binding.verify_file(unlisted_path)


def test_directory_inventory_root_must_equal_the_bound_directory(
    tmp_path: Path,
) -> None:
    registry_path, data_path = _write_registry(tmp_path, asset_status="DEMO_ONLY")
    registry = DataAssetRegistry.load(registry_path)
    manifest_path = _write_manifest(
        tmp_path,
        registry=registry,
        data_path=data_path,
        purpose="SOFTWARE_TEST",
        hard_valid=True,
    )
    inventory_path = _write_inventory(
        tmp_path,
        bound_root=data_path.parent,
        files=(data_path,),
        inventory_root=tmp_path,
    )
    _convert_binding_to_directory(
        manifest_path,
        data_path=data_path,
        inventory_path=inventory_path,
    )

    with pytest.raises(DataActivationError, match="file inventory root mismatch"):
        InputSnapshotManifest.load(manifest_path, registry=registry)


def test_data_preparation_can_ingest_but_cannot_generate_state(tmp_path: Path) -> None:
    registry_path, data_path = _write_registry(
        tmp_path, asset_status="RESEARCH_CONDITIONAL"
    )
    registry = DataAssetRegistry.load(registry_path)
    manifest_path = _write_manifest(
        tmp_path,
        registry=registry,
        data_path=data_path,
        purpose="DATA_PREPARATION",
        hard_valid=False,
        audit_status="NOT_RUN",
    )
    manifest = InputSnapshotManifest.load(manifest_path, registry=registry)

    manifest.authorize(DataOperation.INGEST, registry=registry)
    with pytest.raises(DataActivationError, match="DATA_PREPARATION cannot authorize"):
        manifest.authorize(DataOperation.STATE_GENERATION, registry=registry)


def test_research_state_is_blocked_while_the_global_data_gate_is_closed(
    tmp_path: Path,
) -> None:
    registry_path, data_path = _write_registry(
        tmp_path,
        asset_status="RESEARCH_CONDITIONAL",
        causal_ready=False,
    )
    registry = DataAssetRegistry.load(registry_path)
    manifest_path = _write_manifest(
        tmp_path,
        registry=registry,
        data_path=data_path,
        purpose="CAUSAL_RESEARCH",
        hard_valid=True,
    )
    manifest = InputSnapshotManifest.load(manifest_path, registry=registry)

    manifest.authorize(DataOperation.INGEST, registry=registry)
    with pytest.raises(DataActivationError, match="free_causal_research_ready=false"):
        manifest.authorize(DataOperation.STATE_GENERATION, registry=registry)


def test_qa_only_assets_cannot_drive_software_test_strategy_state(
    tmp_path: Path,
) -> None:
    registry_path, data_path = _write_registry(tmp_path, asset_status="QA_ONLY")
    registry = DataAssetRegistry.load(registry_path)
    manifest_path = _write_manifest(
        tmp_path,
        registry=registry,
        data_path=data_path,
        purpose="SOFTWARE_TEST",
        hard_valid=True,
        role="alternative_price_qa",
    )
    manifest = InputSnapshotManifest.load(manifest_path, registry=registry)

    manifest.authorize(
        DataOperation.INGEST,
        registry=registry,
        software_test=True,
    )
    with pytest.raises(DataActivationError, match="cannot drive strategy execution"):
        manifest.authorize(
            DataOperation.STATE_GENERATION,
            registry=registry,
            software_test=True,
        )


def test_pit_store_identity_is_idempotent_and_cannot_be_rebound(tmp_path: Path) -> None:
    store = PITStore(tmp_path / "pit.sqlite3")
    store.initialize()
    bound_at = datetime(2024, 4, 1, tzinfo=UTC)
    identity = store.bind_input_manifest(
        registry_id="registry-1",
        registry_sha256="a" * 64,
        input_manifest_id="manifest-1",
        input_manifest_sha256="b" * 64,
        purpose="SOFTWARE_TEST",
        hard_valid=True,
        run_id="run-1",
        bound_at=bound_at,
    )
    repeated = store.bind_input_manifest(
        registry_id="registry-1",
        registry_sha256="a" * 64,
        input_manifest_id="manifest-1",
        input_manifest_sha256="b" * 64,
        purpose="SOFTWARE_TEST",
        hard_valid=True,
        run_id="run-1",
        bound_at=bound_at,
    )
    assert identity == repeated

    with pytest.raises(ValueError, match="different input snapshot"):
        store.bind_input_manifest(
            registry_id="registry-1",
            registry_sha256="a" * 64,
            input_manifest_id="manifest-2",
            input_manifest_sha256="c" * 64,
            purpose="SOFTWARE_TEST",
            hard_valid=True,
            run_id="run-2",
            bound_at=bound_at,
        )

    with pytest.raises(ValueError, match="not COMPLETE"):
        store.require_input_manifest(
            registry_id="registry-1",
            registry_sha256="a" * 64,
            input_manifest_id="manifest-1",
            input_manifest_sha256="b" * 64,
        )
    complete = store.complete_input_manifest(
        input_manifest_id="manifest-1",
        input_manifest_sha256="b" * 64,
        completed_at=datetime(2024, 4, 1, 1, tzinfo=UTC),
    )
    assert complete.status == "COMPLETE"
    assert store.require_input_manifest(
        registry_id="registry-1",
        registry_sha256="a" * 64,
        input_manifest_id="manifest-1",
        input_manifest_sha256="b" * 64,
    ) == complete


def test_nonempty_legacy_store_cannot_be_retroactively_blessed(tmp_path: Path) -> None:
    store = PITStore(tmp_path / "legacy.sqlite3")
    store.initialize()
    event_time = datetime(2024, 1, 2, 15, tzinfo=UTC)
    store.ingest_bars(
        [
            Bar(
                symbol="000001.SZ",
                trade_date=date(2024, 1, 2),
                open=10.0,
                high=10.5,
                low=9.9,
                close=10.2,
                volume=1_000.0,
                amount=10_200.0,
                free_float_shares=1_000_000.0,
                available_at=event_time,
            )
        ],
        source="legacy-test",
        snapshot_id="legacy",
        run_id="legacy-run",
    )

    with pytest.raises(ValueError, match="cannot bind a non-empty legacy PIT store"):
        store.bind_input_manifest(
            registry_id="registry-1",
            registry_sha256="a" * 64,
            input_manifest_id="manifest-1",
            input_manifest_sha256="b" * 64,
            purpose="SOFTWARE_TEST",
            hard_valid=True,
            run_id="run-1",
            bound_at=datetime(2024, 4, 1, tzinfo=UTC),
        )
