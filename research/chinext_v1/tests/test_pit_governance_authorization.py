from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from cyq_game.data import (
    DataActivationError,
    DataAssetRegistry,
    DataPurpose,
    InputSnapshotManifest,
)

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
AUTHORIZATION_ID = "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1"
MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_pit_master_manifest.json"
DAILY_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
SECURITY_MASTER = ROOT / "research/chinext_v1/data/pit_2024_2025/security_master.parquet"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
CONSUMER = ROOT / "research/chinext_v1/scripts/run_chinext_v1_smoke.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def exact_request() -> dict[str, object]:
    return {
        "purpose": DataPurpose.CHINEXT_PIT_B_RESEARCH,
        "manifest_path": MANIFEST,
        "manifest_sha256": sha256_file(MANIFEST),
        "artifacts": {
            "daily_membership": (DAILY_MEMBERSHIP, sha256_file(DAILY_MEMBERSHIP)),
            "security_master": (SECURITY_MASTER, sha256_file(SECURITY_MASTER)),
        },
        "start": date(2024, 1, 2),
        "end": date(2025, 12, 31),
        "dependency_asset_id": "QD-007",
        "consumer_path": CONSUMER,
        "strategy_path": STRATEGY,
        "strategy_sha256": sha256_file(STRATEGY),
        "current_survivor_fallback": False,
    }


def test_exact_bounded_chinext_authorization_passes() -> None:
    registry = DataAssetRegistry.load(REGISTRY)
    authorization = registry.authorize_bounded_research(AUTHORIZATION_ID, **exact_request())
    assert authorization.purpose is DataPurpose.CHINEXT_PIT_B_RESEARCH
    assert authorization.asset_id == "CY-027"
    assert authorization.dependency_asset_id == "QD-007"
    assert registry.assets["QD-007"].status == "DISCOVERY_ONLY"
    assert not authorization.record_level_available_at_available


def test_wrong_manifest_hash_fails_closed() -> None:
    request = exact_request()
    request["manifest_sha256"] = "0" * 64
    with pytest.raises(DataActivationError, match="manifest hash mismatch"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTHORIZATION_ID, **request)


def test_different_date_range_fails_closed() -> None:
    request = exact_request()
    request["end"] = date(2026, 1, 2)
    with pytest.raises(DataActivationError, match="date range mismatch"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTHORIZATION_ID, **request)


def test_different_artifact_fails_closed() -> None:
    request = exact_request()
    request["artifacts"] = {
        "daily_membership": (SECURITY_MASTER, sha256_file(SECURITY_MASTER)),
        "security_master": (SECURITY_MASTER, sha256_file(SECURITY_MASTER)),
    }
    with pytest.raises(DataActivationError, match="artifact path mismatch"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTHORIZATION_ID, **request)


def test_missing_authorization_fails_closed() -> None:
    with pytest.raises(DataActivationError, match="missing bounded research authorization"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(
            "MISSING-AUTHORIZATION", **exact_request()
        )


def test_purpose_mismatch_fails_closed() -> None:
    request = exact_request()
    request["purpose"] = DataPurpose.CAUSAL_RESEARCH
    with pytest.raises(DataActivationError, match="purpose mismatch"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTHORIZATION_ID, **request)


def test_current_survivor_fallback_fails_closed() -> None:
    request = exact_request()
    request["current_survivor_fallback"] = True
    with pytest.raises(DataActivationError, match="current-survivor fallback is forbidden"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTHORIZATION_ID, **request)


def test_qd007_use_outside_bounded_chinext_scope_fails_closed(tmp_path: Path) -> None:
    request = exact_request()
    request["consumer_path"] = tmp_path / "other_project_replay.py"
    with pytest.raises(DataActivationError, match="outside bounded research scope"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTHORIZATION_ID, **request)


def test_generic_input_manifest_cannot_bypass_bounded_authorization(
    tmp_path: Path,
) -> None:
    registry = DataAssetRegistry.load(REGISTRY)
    audits = {
        name: {"status": "PASS", "evidence": str(MANIFEST)}
        for name in ("coverage", "duplicates", "time_travel", "consistency", "cross_table")
    }
    manifest_path = tmp_path / "generic-bypass.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_id": "GENERIC-BYPASS-ATTEMPT",
                "registry_id": registry.registry_id,
                "registry_sha256": registry.sha256,
                "purpose": "CHINEXT_PIT_B_RESEARCH",
                "hard_valid": True,
                "scope": {"start": "2024-01-02", "end": "2025-12-31"},
                "bindings": [
                    {
                        "role": "daily_membership",
                        "asset_id": "CY-027",
                        "path": str(DAILY_MEMBERSHIP),
                        "source": "bounded fixture",
                        "snapshot_id": sha256_file(DAILY_MEMBERSHIP),
                        "available_at_policy": "bounded PIT-B effective dates",
                        "sha256": sha256_file(DAILY_MEMBERSHIP),
                    }
                ],
                "audits": audits,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(DataActivationError, match="generic input binding is forbidden"):
        InputSnapshotManifest.load(manifest_path, registry=registry)
