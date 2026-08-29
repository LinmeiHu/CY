from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from cyq_game.data import DataActivationError, DataAssetRegistry, DataPurpose


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
AUTH_ID = "CYQ-AUTH-CHINEXT-V1-PIT-B-HOLDOUT-2022-2023-V1"
MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_pit_holdout_2022_2023_master_manifest.json"
DAILY = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/daily_membership.parquet"
MASTER = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/security_master.parquet"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
CONSUMER = ROOT / "research/chinext_v1/scripts/run_chinext_v1_smoke.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request() -> dict[str, object]:
    return {
        "purpose": DataPurpose.CHINEXT_V1_TEMPORAL_HOLDOUT_VALIDATION,
        "manifest_path": MANIFEST,
        "manifest_sha256": digest(MANIFEST),
        "artifacts": {"daily_membership": (DAILY, digest(DAILY)), "security_master": (MASTER, digest(MASTER))},
        "start": date(2022, 1, 4),
        "end": date(2023, 12, 29),
        "dependency_asset_id": "QD-007",
        "consumer_path": CONSUMER,
        "strategy_path": STRATEGY,
        "strategy_sha256": digest(STRATEGY),
        "current_survivor_fallback": False,
    }


def test_exact_holdout_authorization_passes_and_binds_two_arms():
    registry = DataAssetRegistry.load(REGISTRY)
    auth = registry.authorize_bounded_research(AUTH_ID, **request())
    assert auth.asset_id == "CY-028"
    assert auth.purpose is DataPurpose.CHINEXT_V1_TEMPORAL_HOLDOUT_VALIDATION
    raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = next(x for x in raw["bounded_authorizations"] if x["authorization_id"] == AUTH_ID)
    assert entry["authorized_arms"] == ["O0_BASELINE", "O1_WINNER_HOLD"]
    assert entry["frozen_mechanism"] == {
        "phase8_spec_sha256": "805dc365f5cac89d8114d2ca320d02d3e0a2934bc920566297db310d43ee3d7c",
        "winner_min_holding_sessions": 20,
        "winner_min_current_return": 0.2,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("manifest_sha256", "0" * 64, "manifest hash mismatch"),
        ("strategy_sha256", "0" * 64, "strategy hash mismatch"),
        ("current_survivor_fallback", True, "current-survivor fallback is forbidden"),
    ],
)
def test_authorization_fails_closed_for_identity_mutations(field, value, message):
    r = request(); r[field] = value
    with pytest.raises(DataActivationError, match=message):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTH_ID, **r)


def test_authorization_fails_closed_for_date_purpose_consumer_and_rebuilt_artifact():
    for field, value, message in [
        ("end", date(2024, 1, 2), "date range mismatch"),
        ("purpose", DataPurpose.CAUSAL_RESEARCH, "purpose mismatch"),
        ("consumer_path", ROOT / "other_project/replay.py", "outside bounded research scope"),
    ]:
        r = request(); r[field] = value
        with pytest.raises(DataActivationError, match=message):
            DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTH_ID, **r)
    r = request(); r["artifacts"] = {"daily_membership": (DAILY, "0" * 64), "security_master": (MASTER, digest(MASTER))}
    with pytest.raises(DataActivationError, match="artifact hash mismatch"):
        DataAssetRegistry.load(REGISTRY).authorize_bounded_research(AUTH_ID, **r)


def test_only_two_arms_and_phase8_spec_are_frozen():
    raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = next(x for x in raw["bounded_authorizations"] if x["authorization_id"] == AUTH_ID)
    assert set(entry["authorized_arms"]) == {"O0_BASELINE", "O1_WINNER_HOLD"}
    assert "O2" not in entry["authorized_arms"]
    assert entry["frozen_mechanism"]["phase8_spec_sha256"] != "0" * 64
    assert entry["scope"] == {"project": "research/chinext_v1", "start": "2022-01-04", "end": "2023-12-29"}
