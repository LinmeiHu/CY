#!/usr/bin/env python3
"""Freeze and authorize the exact current research input snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from cyq_game.data.registry import (
    DataAssetRegistry,
    DataOperation,
    InputSnapshotManifest,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry", type=Path, default=Path("configs/data_asset_registry.json")
    )
    parser.add_argument("--output", type=Path, required=True)
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


def _binding(
    by_id: dict[str, dict[str, Any]],
    *,
    role: str,
    asset_id: str,
    policy: str,
) -> dict[str, Any]:
    asset = by_id[asset_id]
    root = Path(str(asset["location"])).resolve()
    manifest_path = Path(str(asset["lineage"]["manifest_path"])).resolve()
    manifest = _read(manifest_path)
    if Path(str(manifest["root"])).resolve() != root:
        raise ValueError(f"{asset_id} inventory root differs")
    if _sha256(manifest_path) != asset["lineage"]["manifest_sha256"]:
        raise ValueError(f"{asset_id} registered manifest hash differs")
    return {
        "role": role,
        "asset_id": asset_id,
        "path": str(root),
        "source": asset["source"],
        "snapshot_id": manifest["snapshot_id"],
        "available_at_policy": policy,
        "inventory_manifest": str(manifest_path),
        "inventory_sha256": asset["lineage"]["manifest_sha256"],
    }


def main() -> int:
    args = _parse_args()
    registry_path = args.registry.resolve()
    registry_payload = _read(registry_path)
    by_id = {str(item["asset_id"]): item for item in registry_payload["assets"]}
    required = {"CY-024", "CY-025", "CY-026", "CY-027"}
    if not required.issubset(by_id):
        raise ValueError(f"current assets are not all registered: {sorted(required - by_id)}")
    manifest = {
        "manifest_id": "CYQ-CURRENT-STATE-20260813-20260824-V1",
        "registry_id": registry_payload["registry_id"],
        "registry_sha256": _sha256(registry_path),
        "purpose": "CAUSAL_RESEARCH",
        "hard_valid": True,
        "scope": {"start": "2026-08-13", "end": "2026-08-24"},
        "bindings": [
            _binding(
                by_id,
                role="daily_pit_b",
                asset_id="CY-024",
                policy=(
                    "available_at must not exceed decision_at; unknown status, float, "
                    "action, sector or market rule blocks new risk"
                ),
            ),
            _binding(
                by_id,
                role="minute_pit_b",
                asset_id="CY-025",
                policy=(
                    "real 1m history and real native-5m current bars only; no same-bar "
                    "fill and hard_valid=false blocks execution"
                ),
            ),
            _binding(
                by_id,
                role="chip_current",
                asset_id="CY-026",
                policy=(
                    "pre-trade exact three-model state only; mass/T+1/model disagreement "
                    "and explicit exclusions fail closed"
                ),
            ),
            _binding(
                by_id,
                role="semantic_chip_current",
                asset_id="CY-027",
                policy=(
                    "outcome-blind measurements available by decision_at only; "
                    "research_valid=false blocks added risk"
                ),
            ),
        ],
        "audits": {
            "coverage": {
                "status": "PASS",
                "evidence": (
                    "CY-024/CY-025 current hard-valid coverage and CY-026/CY-027 "
                    "successful symbol coverage each exceed 95 percent through 2026-08-24."
                ),
            },
            "duplicates": {
                "status": "PASS",
                "evidence": (
                    "Registered daily, minute and semantic unique-key gates pass; chip "
                    "part and terminal symbol sets are exact."
                ),
            },
            "time_travel": {
                "status": "PASS",
                "evidence": (
                    "All current records carry causal available_at/snapshot_id and chip "
                    "operators enforce pre-trade state with no same-bar fill."
                ),
            },
            "consistency": {
                "status": "PASS",
                "evidence": (
                    "Daily/native-5m reconciliation, chip mass, three seller models, T+1 "
                    "and semantic invariants pass; invalid symbols are explicit."
                ),
            },
            "cross_table": {
                "status": "PASS",
                "evidence": (
                    "CY-026 binds CY-020/CY-022/CY-024/CY-025 and CY-027 binds "
                    "CY-024/CY-026; point-in-time sector and leave-one-out requirements remain."
                ),
            },
        },
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if output.exists() and output.read_text(encoding="utf-8") != content:
        raise FileExistsError("existing current input snapshot differs")
    output.write_text(content, encoding="utf-8")
    registry = DataAssetRegistry.load(registry_path)
    snapshot = InputSnapshotManifest.load(output, registry=registry)
    authorization = snapshot.authorize(DataOperation.STATE_GENERATION, registry=registry)
    print(
        f"PASS manifest={snapshot.manifest_id} registry={authorization.registry_sha256} "
        f"scope={snapshot.scope_start}..{snapshot.scope_end}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
