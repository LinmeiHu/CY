from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
ROLLFORWARD_PURPOSE = "ASHARE_ISSUER_FACT_V29R2_ROLLFORWARD_2022_2026"
ROLLFORWARD_AUTHORIZATION_ID = "TEST-AUTH-V29R2-ROLLFORWARD"


def load_validator() -> ModuleType:
    path = ROOT / "scripts" / "validate_data_registry.py"
    spec = importlib.util.spec_from_file_location("validate_data_registry", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_data_asset_registry_schema_is_valid() -> None:
    validator = load_validator()
    registry = validator.load_registry(ROOT / "configs" / "data_asset_registry.json")
    errors = validator.validate_registry(registry, verify_paths=False, verify_hashes=False)
    assert errors == []


def test_unregistered_or_unsafe_statuses_are_not_input_capable() -> None:
    validator = load_validator()
    registry = validator.load_registry(ROOT / "configs" / "data_asset_registry.json")
    unsafe = {"QA_ONLY", "DISCOVERY_ONLY", "DEMO_ONLY", "GENERATED_OUTPUT", "UNAVAILABLE"}
    assert unsafe.isdisjoint(validator.INPUT_CAPABLE_STATUS)
    gate = registry["global_gate"]
    assert isinstance(gate["backtest_authorized"], bool)
    assert not gate["backtest_authorized"] or (
        gate["free_causal_research_ready"] or gate["strict_archival_pit_ready"]
    )


def test_registered_bounded_purposes_are_supported() -> None:
    validator = load_validator()
    registry = validator.load_registry(ROOT / "configs" / "data_asset_registry.json")
    registered = {item["purpose"] for item in registry["bounded_authorizations"]}
    assert registered <= validator.SUPPORTED_BOUNDED_PURPOSES


def test_record_level_available_at_is_only_allowed_for_explicit_purposes() -> None:
    validator = load_validator()
    assert validator.RECORD_LEVEL_AVAILABLE_AT_PURPOSES == {
        "ASHARE_DAILY_NON_CHASING_V29R3_VALIDATION_STAGE_A",
        ROLLFORWARD_PURPOSE,
        "ASHARE_ISSUER_FACT_V29R2_DEVELOPMENT_SELECTOR_REPLAY",
        "ASHARE_ISSUER_RISK_V29R1_DEVELOPMENT_SELECTOR_REPLAY",
    }
    assert validator.RECORD_LEVEL_AVAILABLE_AT_PURPOSES <= (
        validator.SUPPORTED_BOUNDED_PURPOSES
    )


def _validate_rollforward_authorization(
    validator: ModuleType,
    *,
    record_level_available_at_available: bool,
) -> list[str]:
    fingerprint = {"path": "ignored", "sha256": "0" * 64}
    assets = {
        "CY-062": {
            "status": "RESEARCH_CONDITIONAL",
            "lineage": {"bounded_authorization_id": ROLLFORWARD_AUTHORIZATION_ID},
        },
        "CY-033": {"status": "RESEARCH_CONDITIONAL"},
    }
    authorizations = [
        {
            "authorization_id": ROLLFORWARD_AUTHORIZATION_ID,
            "purpose": ROLLFORWARD_PURPOSE,
            "asset_id": "CY-062",
            "dependency_asset_id": "CY-033",
            "dependency_status": "RESEARCH_CONDITIONAL",
            "scope": {
                "project": "research/market_behavior_os_v2",
                "start": "2022-01-01",
                "end": "2026-09-04",
            },
            "bound_manifest": fingerprint,
            "bound_artifacts": [{"role": "activation_audit", **fingerprint}],
            "bound_strategy": fingerprint,
            "current_survivor_fallback_allowed": False,
            "record_level_available_at_available": (
                record_level_available_at_available
            ),
            "allowed_uses": ["frozen V29R1/R2 rollforward diagnostic"],
            "blocked_uses": ["parameter selection"],
            "known_limitations": ["PIT-B announcement enumeration"],
        }
    ]
    errors: list[str] = []
    validator._validate_bounded_authorizations(
        authorizations,
        assets=assets,
        errors=errors,
        verify_paths=False,
        verify_hashes=False,
    )
    return errors


def test_rollforward_purpose_accepts_record_level_available_at() -> None:
    validator = load_validator()
    assert ROLLFORWARD_PURPOSE in validator.SUPPORTED_BOUNDED_PURPOSES
    assert _validate_rollforward_authorization(
        validator,
        record_level_available_at_available=True,
    ) == []


def test_rollforward_purpose_rejects_missing_record_level_available_at() -> None:
    validator = load_validator()
    errors = _validate_rollforward_authorization(
        validator,
        record_level_available_at_available=False,
    )
    assert errors == [
        f"{ROLLFORWARD_AUTHORIZATION_ID}: record-level available_at must be True "
        f"for purpose {ROLLFORWARD_PURPOSE!r}"
    ]
