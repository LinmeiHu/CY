#!/usr/bin/env python3
"""Register frozen CY-027 without broadening older semantic protocols."""

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
    if manifest.get("asset_id") != "CY-027" or manifest.get("status") != "PASS":
        raise ValueError("CY-027 manifest is not frozen PASS evidence")
    root = manifest_path.parent
    if Path(str(manifest["location"])).resolve() != root:
        raise ValueError("CY-027 manifest location differs from physical root")
    manifest_sha256 = _sha256(manifest_path)
    registry_path = args.registry.resolve()
    registry = _read(registry_path)
    assets = registry.get("assets")
    if not isinstance(assets, list):
        raise ValueError("registry assets are invalid")
    by_id = {str(item["asset_id"]): item for item in assets}
    existing = by_id.get("CY-027")
    if existing is not None:
        if (
            existing.get("lineage", {}).get("manifest_sha256") == manifest_sha256
            and Path(str(existing["location"])).resolve() == root
        ):
            print("REUSED asset=CY-027", flush=True)
            return 0
        raise ValueError("conflicting CY-027 registration exists")
    for component in manifest["component_assets"]:
        registered = by_id.get(str(component["asset_id"]))
        if registered is None:
            raise ValueError(f"unregistered component {component['asset_id']}")
        if registered.get("lineage", {}).get("manifest_sha256") != component["sha256"]:
            raise ValueError(f"component hash differs for {component['asset_id']}")

    coverage = manifest["coverage"]
    asset = {
        "asset_id": "CY-027",
        "name": "Current exact and semantic chip features through 2026-08-24",
        "kind": "current_exact_and_semantic_chip_feature_delta",
        "status": "RESEARCH_CONDITIONAL",
        "pit_grade": "B",
        "physical_state": "MATERIALIZED",
        "location": str(root),
        "source": (
            "deterministic outcome-blind exact P50/dominant-band plus semantic "
            "Q05/Q15/Q85/Q95, peak and model-spread measurement from registered "
            "CY-026 operators and CY-024 closes"
        ),
        "coverage": {
            **coverage,
            "universe": "CY-026 successful current main-board and ChiNext symbol-days",
        },
        "schema_and_units": (
            "One pre-trade symbol/day row with three-model median semantic cost bands, "
            "profit/overhang mass, price-ordered peaks, model min/max/spread, causal "
            "available_at and snapshot_id; prices are unadjusted CNY"
        ),
        "quality_evidence": {
            "gate": "CURRENT_SEMANTIC_EXACT_CHIP_DELTA_V1",
            "gate_pass": True,
            "rows": coverage["rows"],
            "symbols": coverage["symbols"],
            "measurement_valid_ratio": coverage["measurement_valid_ratio"],
            "checks": manifest["checks"],
            "outcomes_observed": False,
        },
        "lineage": {
            "record_available_at": True,
            "record_snapshot_id": True,
            "immutable_manifest": True,
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha256,
            "component_assets": ["CY-024", "CY-026"],
            "pipeline_version": "current-semantic-chip-delta-v1",
        },
        "allowed_uses": manifest["allowed_uses"],
        "blocked_uses": manifest["blocked_uses"],
        "activation_gates": [
            "CY-027 manifest and all three inventory files remain hash-identical",
            "registered CY-024 and CY-026 component identities remain exact",
            "combined exact/semantic measurement-valid coverage remains at least 95 percent",
            "available_at, unique-key and semantic invariant gates remain passing",
            "2023 or later outcomes remain unavailable to parameter selection",
        ],
    }
    assets.append(asset)
    now = datetime.now().astimezone().replace(microsecond=0).isoformat()
    registry["updated_at"] = now
    registry["global_gate"]["as_of"] = "2026-08-25"
    registry["global_gate"]["reason"] = (
        "CY-024/CY-025 extend the registered daily and real minute/native-5m PIT-B "
        "inputs through 2026-08-24; CY-026/CY-027 add exact current chip state and "
        "outcome-blind semantic features above 95 percent coverage. Authorization "
        "requires a new exact input snapshot, individual invalid rows fail closed, "
        "and strict archival PIT-A remains unavailable."
    )
    registry["change_log"].append(
        {
            "at": now,
            "registry_id": registry["registry_id"],
            "change": (
                "Registered CY-027, the outcome-blind current exact-chip semantic delta "
                "for 2026-06-17 through 2026-08-24. It preserves the frozen older semantic "
                "assets, binds CY-024/CY-026, passes causal and semantic gates, and is "
                "blocked from retrospective parameter selection and live sizing."
            ),
            "evidence_ids": [],
        }
    )
    temporary = registry_path.with_suffix(".tmp.json")
    temporary.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, registry_path)
    print(f"PASS registered CY-027 manifest_sha256={manifest_sha256}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
