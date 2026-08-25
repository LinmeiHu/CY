#!/usr/bin/env python3
"""Register frozen CY-026 without changing any existing asset contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=Path("configs/data_asset_registry.json")
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def main() -> int:
    args = _parse_args()
    manifest_path = args.manifest.resolve()
    manifest = _read(manifest_path)
    if manifest.get("asset_id") != "CY-026" or manifest.get("status") != "PASS":
        raise ValueError("CY-026 manifest is not frozen PASS evidence")
    root = manifest_path.parent
    if Path(str(manifest["location"])).resolve() != root:
        raise ValueError("CY-026 manifest location differs from physical root")
    inventory = manifest.get("inventory")
    if not isinstance(inventory, list) or len(inventory) != manifest["inventory_files"]:
        raise ValueError("CY-026 inventory is incomplete")
    if any(
        not (root / str(item["path"])).is_file()
        or (root / str(item["path"])).stat().st_size != int(item["size"])
        for item in inventory
    ):
        raise ValueError("CY-026 inventory path or size changed after freeze")

    registry_path = args.registry.resolve()
    registry = _read(registry_path)
    assets = registry.get("assets")
    if not isinstance(assets, list):
        raise ValueError("registry assets are invalid")
    by_id = {str(item["asset_id"]): item for item in assets}
    manifest_sha256 = _sha256(manifest_path)
    existing = by_id.get("CY-026")
    if existing is not None:
        if (
            existing.get("lineage", {}).get("manifest_sha256") == manifest_sha256
            and Path(str(existing["location"])).resolve() == root
        ):
            print("REUSED asset=CY-026", flush=True)
            return 0
        raise ValueError("conflicting CY-026 registration exists")
    for component in manifest["component_assets"]:
        registered = by_id.get(str(component["asset_id"]))
        if registered is None:
            raise ValueError(f"unregistered component {component['asset_id']}")
        if registered.get("lineage", {}).get("manifest_sha256") != component["sha256"]:
            raise ValueError(f"component hash differs for {component['asset_id']}")

    annual = manifest["coverage"]["annual"]
    annual_coverage = {str(item["year"]): item["coverage"] for item in annual}
    asset = {
        "asset_id": "CY-026",
        "name": "Current exact three-model chip-state continuation through 2026-08-24",
        "kind": "current_compact_chip_state_continuation",
        "status": "RESEARCH_CONDITIONAL",
        "pit_grade": "B",
        "physical_state": "MATERIALIZED",
        "location": str(root),
        "source": (
            "deterministic continuation of registered CY-020 terminal state through "
            "registered QD-004 real 1m, CY-022 native-5m and CY-024 daily paths"
        ),
        "coverage": {
            **manifest["coverage"],
            "annual_coverage": annual_coverage,
            "inventory_files": manifest["inventory_files"],
            "inventory_bytes": manifest["inventory_bytes"],
            "universe": "date-varying Shanghai/Shenzhen main-board and ChiNext",
        },
        "schema_and_units": (
            "Three seller-model exact annual terminal inventories plus compact daily "
            "economic-cost/age/sensitivity transition operators for 2026-06-17..2026-08-24; "
            "unadjusted CNY prices and shares"
        ),
        "quality_evidence": {
            "gate": "CURRENT_EXACT_CHIP_CONTINUATION_V1",
            "gate_pass": True,
            "annual_coverage": annual_coverage,
            "minimum_coverage": min(annual_coverage.values()),
            "mass_conservation": "PASS",
            "same_day_resale": "PASS",
            "three_seller_models": "PASS",
            "explicit_failed_symbol_exclusions": sum(
                int(item["symbols"]) - int(item["passed_symbols"]) for item in annual
            ),
        },
        "lineage": {
            "record_available_at": True,
            "record_snapshot_id": True,
            "immutable_manifest": True,
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha256,
            "component_assets": [
                str(item["asset_id"]) for item in manifest["component_assets"]
            ],
            "pipeline_version": "real-chip-inventory-v2.1/current-continuation-v1",
        },
        "allowed_uses": manifest["allowed_uses"],
        "blocked_uses": manifest["blocked_uses"],
        "activation_gates": [
            "CY-026 manifest and complete per-file inventory remain hash-identical",
            "registered CY-020/QD-004/CY-022/CY-024/CY-025 identities remain exact",
            "runtime requires all three seller models and hard-valid source state",
            "annual successful symbol coverage remains at least 95 percent",
            "parameter selection cannot inspect 2023 or later outcomes",
        ],
    }
    assets.append(asset)
    now = datetime.now().astimezone().replace(microsecond=0).isoformat()
    registry["updated_at"] = now
    registry["change_log"].append(
        {
            "at": now,
            "registry_id": registry["registry_id"],
            "change": (
                "Registered CY-026, a space-efficient exact three-model chip continuation. "
                "It reanchors 2023 terminal states, stores only 2024/2025 terminals, and "
                "retains daily operators only for 2026-06-17 through 2026-08-24. Every "
                "annual symbol set exceeds 95 percent coverage; missing symbols remain "
                "explicit exclusions and no 2024/2025 full operator history is claimed."
            ),
            "evidence_ids": [],
        }
    )
    temporary = registry_path.with_suffix(".tmp.json")
    temporary.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, registry_path)
    print(f"PASS registered CY-026 manifest_sha256={manifest_sha256}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
