from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from cyq_game.data import DataActivationError, DataAssetRegistry, DataPurpose

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / "configs/data_asset_registry.json"
WORK = ROOT / "research/chinext_v1"
STRATEGY = WORK / "strategy/chinext_v1_exploratory.py"
FEATURES = WORK / "regime_attribution/artifacts/daily_regime_features.parquet"
SPEC = WORK / "regime_attribution/experiments/EXP-P7-003_spec.json"
RUNNER = WORK / "scripts/run_chinext_v1_smoke.py"
MATERIALIZER = WORK / "scripts/run_chinext_v1_extended_replay.py"
CANDIDATE_WRAPPER = WORK / "regime_attribution/scripts/run_phase7_v1r_candidate.py"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


CASES = {
    "CYQ-AUTH-CHINEXT-V1R-P7-2017-2021-V1": {
        "manifest": WORK / "reports/chinext_v1_free_historical_state_manifest.json",
        "artifacts": {
            "daily_historical_state": WORK / "data/pit_free_2017_2021/normalized/daily_historical_state.parquet",
            "security_master": WORK / "data/pit_free_2017_2021/normalized/security_master.parquet",
            "regime_features": FEATURES,
            "phase7_spec": SPEC,
            "overlay_runner": RUNNER,
            "candidate_wrapper": CANDIDATE_WRAPPER,
            "extended_materializer": MATERIALIZER,
        },
        "start": date(2017, 4, 12),
        "end": date(2021, 12, 31),
        "asset_id": "CY-030",
    },
    "CYQ-AUTH-CHINEXT-V1R-P7-2022-2023-V1": {
        "manifest": WORK / "reports/chinext_v1_pit_holdout_2022_2023_master_manifest.json",
        "artifacts": {
            "daily_membership": WORK / "data/pit_holdout_2022_2023/daily_membership.parquet",
            "security_master": WORK / "data/pit_holdout_2022_2023/security_master.parquet",
            "regime_features": FEATURES,
            "phase7_spec": SPEC,
            "overlay_runner": RUNNER,
            "candidate_wrapper": CANDIDATE_WRAPPER,
        },
        "start": date(2022, 1, 4),
        "end": date(2023, 12, 29),
        "asset_id": "CY-031",
    },
    "CYQ-AUTH-CHINEXT-V1R-P7-2024-2025-V1": {
        "manifest": WORK / "reports/chinext_v1_pit_master_manifest.json",
        "artifacts": {
            "daily_membership": WORK / "data/pit_2024_2025/daily_membership.parquet",
            "security_master": WORK / "data/pit_2024_2025/security_master.parquet",
            "regime_features": FEATURES,
            "phase7_spec": SPEC,
            "overlay_runner": RUNNER,
            "candidate_wrapper": CANDIDATE_WRAPPER,
        },
        "start": date(2024, 1, 2),
        "end": date(2025, 12, 31),
        "asset_id": "CY-032",
    },
}


def request(case: dict[str, object]) -> dict[str, object]:
    manifest = case["manifest"]
    assert isinstance(manifest, Path)
    artifacts = case["artifacts"]
    assert isinstance(artifacts, dict)
    return {
        "purpose": DataPurpose.CHINEXT_PIT_B_RESEARCH,
        "manifest_path": manifest,
        "manifest_sha256": sha256_file(manifest),
        "artifacts": {
            role: (path, sha256_file(path)) for role, path in artifacts.items()
        },
        "start": case["start"],
        "end": case["end"],
        "dependency_asset_id": "QD-007",
        "consumer_path": WORK / "regime_attribution/scripts/run_phase7_v1r_candidate.py",
        "strategy_path": STRATEGY,
        "strategy_sha256": sha256_file(STRATEGY),
        "current_survivor_fallback": False,
    }


@pytest.mark.parametrize("authorization_id", sorted(CASES))
def test_exact_phase7_authorization_passes(authorization_id: str) -> None:
    case = CASES[authorization_id]
    authorization = DataAssetRegistry.load(REGISTRY).authorize_bounded_research(
        authorization_id, **request(case)
    )
    assert authorization.asset_id == case["asset_id"]
    assert authorization.purpose is DataPurpose.CHINEXT_PIT_B_RESEARCH


def test_phase7_authorization_rejects_stale_spec_hash() -> None:
    authorization_id = "CYQ-AUTH-CHINEXT-V1R-P7-2024-2025-V1"
    args = request(CASES[authorization_id])
    artifacts = dict(args["artifacts"])
    artifacts["phase7_spec"] = (SPEC, "0" * 64)
    args["artifacts"] = artifacts
    with pytest.raises(DataActivationError, match="artifact hash mismatch"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(
            authorization_id, **args
        )
