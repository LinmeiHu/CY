from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = (
    REPO
    / "research/market_behavior_os_v2/scripts/"
    / "run_ashare_historical_opposite_sign_closed_family_audit_v1.py"
)
SPEC = importlib.util.spec_from_file_location("opposite_sign_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_frozen_family_inventory_and_classification_counts() -> None:
    MOD.validate_families(MOD.FAMILIES, REPO)
    counts: dict[str, int] = {}
    for row in MOD.FAMILIES:
        key = row["audit_classification"]
        counts[key] = counts.get(key, 0) + 1
    assert len(MOD.FAMILIES) == 28
    assert counts == {
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY": 8,
        "TRUE_NULL": 4,
        "STABLE_ADVERSE_ALREADY_USED": 5,
        "CHRONOLOGICALLY_UNSTABLE": 7,
        "SCIENTIFICALLY_UNRESOLVED": 4,
    }
    assert len(MOD.TOP_CANDIDATES) == 3


def test_inventory_deduplicates_experiment_ids() -> None:
    ids = MOD.inventory_experiment_ids(MOD.FAMILIES)
    assert ids == sorted(set(ids))
    assert len(ids) == 35
    assert set(MOD.REFERENCE_ONLY_EXPERIMENTS).issubset(ids)


def test_duplicate_family_and_missing_evidence_fail_closed() -> None:
    duplicate = [dict(MOD.FAMILIES[0]), dict(MOD.FAMILIES[0])]
    with pytest.raises(ValueError, match="duplicate family_id"):
        MOD.validate_families(duplicate, REPO)

    missing = [dict(MOD.FAMILIES[0])]
    missing[0]["evidence_paths"] = ["does/not/exist.md"]
    with pytest.raises(FileNotFoundError, match="missing evidence artifacts"):
        MOD.validate_families(missing, REPO)


def test_canonical_serialization_is_deterministic() -> None:
    value = {"z": 1, "a": [3, 2, 1]}
    assert MOD.canonical_json_bytes(value) == MOD.canonical_json_bytes(value)
    assert MOD.canonical_json_bytes(value).startswith(b'{\n  "a"')
