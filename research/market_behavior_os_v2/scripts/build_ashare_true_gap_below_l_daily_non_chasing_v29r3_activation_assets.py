#!/usr/bin/env python3
"""Build metadata-only CY-040/CY-041 activation wrappers for V29R3.

This builder never parses a Parquet row.  The Stage-A mode binds the exact
registered CY-033 2022-2024 partitions and frozen V28R2 selected identity.
The Stage-B mode first verifies the completed V29R3 Stage-A freeze and only
then resolves and hashes the pre-existing outcome/execution sources.

The builder is intentionally not an authorization.  Its outputs must be
registered with distinct one-to-one bounded authorizations before the runner
may consume either wrapper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
PREREGISTRATION = (
    OS_ROOT / "experiments/ASHARE-TRUE-GAP-BELOW-L-DAILY-NON-CHASING-V29R3_preregistration.json"
)
EXPECTED_PREREGISTRATION_SHA256 = "33595c6c163ef65a65298f1a2751b105e9d1ada149f7ec6f834385cd68fcb15d"
RUNNER = (
    OS_ROOT / "scripts/run_ashare_true_gap_below_l_daily_non_chasing_v29r3_validation_2022_2024.py"
)
REGISTRY = ROOT / "configs/data_asset_registry.json"
PARENT_IDENTITY_FREEZE = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2-"
    "VALIDATION-2022-2024_identity_freeze.json"
)
EXPECTED_PARENT_IDENTITY_FREEZE_SHA256 = (
    "8b61ca22a211d91be01c3da7669e1412ef201bc8ca0440ac052b804d0397f39c"
)
PARENT_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_v28r2_validation_2022_2024/"
    "diagnostic_2022_2024/orderly_demand_selected_entries.parquet"
)
EXPECTED_PARENT_SELECTED_SHA256 = "c439ea1a74e7d1f865cf187fadca3834e8d8963537eeab9230e4f3981db14c23"

CY033_ASSET_ID = "CY-033"
CY040_ASSET_ID = "CY-040"
CY040_AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-DAILY-NON-CHASING-V29R3-STAGE-A-2022-2024-V1"
CY040_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/CY-040-DAILY-NON-CHASING-V29R3-STAGE-A-2022-2024-V1"
)
CY041_ASSET_ID = "CY-041"
CY041_AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-DAILY-NON-CHASING-V29R3-STAGE-B-2022-2024-V1"
CY041_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/CY-041-DAILY-NON-CHASING-V29R3-STAGE-B-2022-2024-V1"
)
VALIDATION_YEARS = (2022, 2023, 2024)
CROSS_SECTION_SEMANTICS = {
    "definition": "CONDITIONAL_OBSERVED_ROWS_IN_EXACT_REGISTERED_CY033_PARTITION",
    "current_universe_or_constituent_filter_applied": False,
    "historical_security_master_completeness_verified": False,
    "survivorship_free_claim_allowed": False,
    "full_a_share_population_claim_allowed": False,
    "limitation": (
        "QD-007 is not materialized, so CY-033 row inventory cannot be certified complete "
        "against a date-effective historical security master."
    ),
}


class ActivationBuildError(RuntimeError):
    """Fail closed on a source, ordering, or identity mismatch."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ActivationBuildError(f"JSON root must be an object: {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _fingerprint(path: Path, role: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise ActivationBuildError(f"missing bound file: {path}")
    result: dict[str, Any] = {"path": str(path), "sha256": sha256(path)}
    if role is not None:
        result["role"] = role
    return result


def _verify_frozen_protocol() -> None:
    if not PREREGISTRATION.is_file() or sha256(PREREGISTRATION) != EXPECTED_PREREGISTRATION_SHA256:
        raise ActivationBuildError("V29R3 preregistration drift")
    if PREREGISTRATION.stat().st_mode & 0o222:
        raise ActivationBuildError("V29R3 preregistration is not read-only")
    if not RUNNER.is_file():
        raise ActivationBuildError("V29R3 runner is missing")
    if (
        not PARENT_IDENTITY_FREEZE.is_file()
        or sha256(PARENT_IDENTITY_FREEZE) != EXPECTED_PARENT_IDENTITY_FREEZE_SHA256
    ):
        raise ActivationBuildError("V28R2 validation identity freeze drift")


def _exact_asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any]:
    matches = [item for item in registry.get("assets", []) if item.get("asset_id") == asset_id]
    if len(matches) != 1:
        raise ActivationBuildError(f"registered asset must resolve once: {asset_id}")
    return matches[0]


def _assert_new_asset_id(registry: dict[str, Any], asset_id: str) -> None:
    if any(item.get("asset_id") == asset_id for item in registry.get("assets", [])):
        raise ActivationBuildError(
            f"{asset_id} is already registered; immutable wrapper rebuild is prohibited"
        )


def _assert_new_authorization_id(registry: dict[str, Any], authorization_id: str) -> None:
    if any(
        item.get("authorization_id") == authorization_id
        for item in registry.get("bounded_authorizations", [])
        if isinstance(item, dict)
    ):
        raise ActivationBuildError(
            f"{authorization_id} is already registered; wrapper rebuild is prohibited"
        )


def resolve_cy033_partition_bindings(registry: dict[str, Any]) -> list[dict[str, Any]]:
    asset = _exact_asset(registry, CY033_ASSET_ID)
    root = Path(str(asset.get("location", "")))
    lineage = asset.get("lineage", {})
    manifest_path = Path(str(lineage.get("manifest_path", "")))
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("physical_state") != "MATERIALIZED"
        or lineage.get("record_available_at") is not True
        or lineage.get("record_snapshot_id") is not True
        or not manifest_path.is_file()
        or sha256(manifest_path) != lineage.get("manifest_sha256")
    ):
        raise ActivationBuildError("CY-033 is not an exact active PIT-B dependency")
    manifest = _json(manifest_path)
    if manifest.get("asset_id") != CY033_ASSET_ID or manifest.get("status") != "PASS":
        raise ActivationBuildError("CY-033 manifest is not PASS")
    listed = {
        str(item.get("path")): item.get("sha256")
        for item in manifest.get("files", [])
        if isinstance(item, dict)
    }
    bindings: list[dict[str, Any]] = []
    for year in VALIDATION_YEARS:
        relative = f"daily/partition_year={year}/data_0.parquet"
        path = root / relative
        expected = listed.get(relative)
        if not path.is_file() or not expected or sha256(path) != expected:
            raise ActivationBuildError(f"CY-033 exact partition drift: {year}")
        bindings.append(
            {
                "year": year,
                "path": str(path),
                "sha256": expected,
                "source_asset_id": CY033_ASSET_ID,
                "row_content_parsed_by_builder": False,
            }
        )
    return bindings


def stage_a_manifest_payload(registry: dict[str, Any]) -> dict[str, Any]:
    """Build the CY-040 payload; callers decide whether to materialize it."""
    _verify_frozen_protocol()
    _assert_new_asset_id(registry, CY040_ASSET_ID)
    _assert_new_authorization_id(registry, CY040_AUTHORIZATION_ID)
    if not PARENT_SELECTED.is_file() or sha256(PARENT_SELECTED) != EXPECTED_PARENT_SELECTED_SHA256:
        raise ActivationBuildError("V28R2 validation selected identity drift")
    cy033 = _exact_asset(registry, CY033_ASSET_ID)
    return {
        "asset_id": CY040_ASSET_ID,
        "status": "PASS",
        "stage": "OUTCOME_BLIND_STAGE_A_INPUT_WRAPPER",
        "authorization_id": CY040_AUTHORIZATION_ID,
        "description": (
            "Metadata-only wrapper over exact CY-033 2022-2024 partitions and the "
            "frozen V28R2 validation selected identity for V29R3 Stage A."
        ),
        "coverage": {"start": "2022-01-01", "end": "2024-12-31", "years": list(VALIDATION_YEARS)},
        "dependency_asset": {
            "asset_id": CY033_ASSET_ID,
            "registered_manifest": cy033.get("lineage", {}).get("manifest_path"),
            "registered_manifest_sha256": cy033.get("lineage", {}).get("manifest_sha256"),
        },
        "cross_section_semantics": CROSS_SECTION_SEMANTICS,
        "daily_partitions": resolve_cy033_partition_bindings(registry),
        "parent_identity_freeze": _fingerprint(PARENT_IDENTITY_FREEZE),
        "parent_selected_identity": _fingerprint(PARENT_SELECTED),
        "preregistration": _fingerprint(PREREGISTRATION),
        "runner": _fingerprint(RUNNER),
        "asset_builder": _fingerprint(Path(__file__)),
        "outcome_paths_resolved": False,
        "title_paths_resolved": False,
        "outcome_or_title_content_embedded": False,
        "parquet_row_content_parsed_by_builder": False,
        "allowed_use": "one outcome-blind V29R3 Stage-A signal-close feature/cohort freeze",
        "blocked_uses": [
            "outcome, exit, target, portfolio, NAV or result access",
            "issuer announcement/title access or issuer veto inheritance",
            "any 2025-or-later row or partition",
            "any strategy or threshold other than the exact bound V29R3 preregistration",
        ],
    }


def _resolve_stage_b_source_paths_after_stage_a_verification() -> dict[str, Path]:
    """This function must not be called until runner.verify_stage_a_freeze passes."""
    from research.market_behavior_os_v2.scripts import (
        run_ashare_true_gap_below_l_orderly_demand_v28r2_validation_2022_2024 as parent,
    )

    return {
        "v28r2_validation_outcomes": parent.LANE_ROOT / "outcomes.parquet",
        "portfolio_daily_old": v28_daily_path(),
        "portfolio_daily_later": v28_later_daily_path(),
    }


def v28_daily_path() -> Path:
    from research.market_behavior_os_v2.scripts import (
        run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
    )

    return Path(v28.replay.source_paths("POST_OBSERVATION_DIAGNOSTIC")["outcome_daily"])


def v28_later_daily_path() -> Path:
    from research.market_behavior_os_v2.scripts import (
        run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
    )

    return Path(v28.V27_LATER_DAILY)


def stage_b_manifest_payload(registry: dict[str, Any]) -> dict[str, Any]:
    """Build CY-041 only after a complete Stage-A verification."""
    _verify_frozen_protocol()
    _assert_new_asset_id(registry, CY041_ASSET_ID)
    _assert_new_authorization_id(registry, CY041_AUTHORIZATION_ID)
    from research.market_behavior_os_v2.scripts import (
        run_ashare_true_gap_below_l_daily_non_chasing_v29r3_validation_2022_2024 as runner,
    )

    # Ordering invariant: no Stage-B source path is even resolved before this returns.
    stage_a = runner.verify_stage_a_freeze()
    source_paths = _resolve_stage_b_source_paths_after_stage_a_verification()
    sources = [_fingerprint(path, role=role) for role, path in sorted(source_paths.items())]
    return {
        "asset_id": CY041_ASSET_ID,
        "status": "PASS",
        "stage": "STAGE_B_FIXED_COHORT_ACTIVATION_WRAPPER",
        "authorization_id": CY041_AUTHORIZATION_ID,
        "description": (
            "Metadata-only activation wrapper binding the already-verified V29R3 "
            "Stage-A cohort to exact pre-existing outcome and portfolio-daily files."
        ),
        "coverage": {"start": "2022-01-01", "end": "2024-12-31", "years": list(VALIDATION_YEARS)},
        "dependency_asset_id": CY040_ASSET_ID,
        "stage_a_freeze": _fingerprint(runner.STAGE_A_FREEZE),
        "stage_a_selected": _fingerprint(runner.STAGE_A_SELECTED),
        "stage_b_sources": sources,
        "preregistration": _fingerprint(PREREGISTRATION),
        "runner": _fingerprint(RUNNER),
        "asset_builder": _fingerprint(Path(__file__)),
        "stage_a_verified_before_source_resolution": True,
        "stage_a_freeze_sha256_seen": stage_a["freeze_sha256"],
        "outcome_content_parsed_by_builder": False,
        "outcome_or_title_content_embedded": False,
        "parquet_row_content_parsed_by_builder": False,
        "allowed_use": "one fixed-cohort V29R3 2022-2024 Stage-B outcome attachment and K80 replay",
        "blocked_uses": [
            "any use before exact Stage-A freeze verification",
            "any second validation run, tuning, rescue or cohort change",
            "issuer announcement/title access",
            "any materialized 2025-or-later row",
        ],
    }


def _materialize(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    if root.exists():
        raise ActivationBuildError(f"immutable activation wrapper already exists: {root}")
    manifest_path = root / "asset_manifest.json"
    audit_path = root / "activation_audit.json"
    _atomic_json(manifest_path, payload)
    audit = {
        "asset_id": payload["asset_id"],
        "status": "PASS",
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "preregistration_sha256": sha256(PREREGISTRATION),
        "runner_sha256": sha256(RUNNER),
        "asset_builder_sha256": sha256(Path(__file__)),
        "parquet_row_content_parsed": False,
        "outcome_or_title_content_parsed": False,
        "registration_authorization_created": False,
    }
    _atomic_json(audit_path, audit)
    manifest_path.chmod(0o444)
    audit_path.chmod(0o444)
    return audit


def build_stage_a() -> dict[str, Any]:
    registry = _json(REGISTRY)
    return _materialize(stage_a_manifest_payload(registry), CY040_ROOT)


def build_stage_b() -> dict[str, Any]:
    registry = _json(REGISTRY)
    return _materialize(stage_b_manifest_payload(registry), CY041_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("a", "b"))
    args = parser.parse_args()
    payload = build_stage_a() if args.stage == "a" else build_stage_b()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
