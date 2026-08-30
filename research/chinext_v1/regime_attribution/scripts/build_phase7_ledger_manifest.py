#!/usr/bin/env python3
"""Build an outcome-blind identity manifest for the frozen EXP-P7-003 ledgers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
INPUT_ROOT = WORK / "output/phase7_v1r"
OUTPUT = WORK / "artifacts/v1r_candidate_ledger_manifest.json"

BLOCKS = [
    "EXTENDED_2018_2021",
    "HOLDOUT_O0_2022_2023",
    "DEVELOPMENT_2024_2025",
]
ARMS = [
    "C0_ALL_ONE_CONTROL",
    "A40_HALF_PRIMARY",
    "N30_HALF_NEIGHBOR",
    "N50_HALF_NEIGHBOR",
    "Z40_ZERO_SEVERITY",
]
FILES = [
    "engine_summary.json",
    "engine_report.md",
    "event_ledger.jsonl",
    "execution_ledger.jsonl",
    "daily_nav.jsonl",
]


class ManifestError(RuntimeError):
    """Raised when the Phase 7 output surface is incomplete or unexpected."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl_identity(path: Path) -> dict[str, Any]:
    count = 0
    dates: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            count += 1
            for field in ("trade_date", "signal_date", "execution_date"):
                value = row.get(field)
                if value is not None:
                    dates.append(str(value))
    return {
        "row_count": count,
        "minimum_date_field": min(dates) if dates else None,
        "maximum_date_field": max(dates) if dates else None,
    }


def build_manifest() -> dict[str, Any]:
    expected_directories = {
        INPUT_ROOT / block / arm for block in BLOCKS for arm in ARMS
    }
    actual_directories = {
        path for path in INPUT_ROOT.glob("*/*") if path.is_dir()
    }
    if actual_directories != expected_directories:
        raise ManifestError(
            "unexpected Phase 7 arm directories: "
            f"missing={sorted(map(str, expected_directories - actual_directories))}, "
            f"extra={sorted(map(str, actual_directories - expected_directories))}"
        )

    ledgers: list[dict[str, Any]] = []
    for block in BLOCKS:
        for arm in ARMS:
            directory = INPUT_ROOT / block / arm
            actual_files = {path.name for path in directory.iterdir() if path.is_file()}
            if actual_files != set(FILES):
                raise ManifestError(
                    f"unexpected files for {block}/{arm}: {sorted(actual_files)}"
                )
            summary_path = directory / "engine_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            overlay = summary.get("entry_weight_overlay")
            if not isinstance(overlay, dict) or not isinstance(
                overlay.get("identity"), dict
            ):
                raise ManifestError(f"missing overlay identity for {block}/{arm}")
            identity = overlay["identity"]
            if identity.get("block") != block or identity.get("arm") != arm:
                raise ManifestError(f"overlay identity mismatch for {block}/{arm}")

            files: dict[str, Any] = {}
            for name in FILES:
                path = directory / name
                item: dict[str, Any] = {
                    "path": str(path.relative_to(ROOT)),
                    "sha256": sha256_file(path),
                    "byte_count": path.stat().st_size,
                }
                if name.endswith(".jsonl"):
                    item.update(jsonl_identity(path))
                files[name] = item
            ledgers.append(
                {
                    "block": block,
                    "arm": arm,
                    "overlay_identity": identity,
                    "files": files,
                }
            )

    return {
        "manifest_id": "CHINEXT-V1R-P7-FROZEN-LEDGER-MANIFEST-V1",
        "experiment_id": "EXP-P7-003",
        "purpose": "OUTCOME_BLIND_IDENTITY_BINDING_FOR_PHASE8_9",
        "builder_sha256": sha256_file(Path(__file__).resolve()),
        "ledger_count": len(ledgers),
        "blocks": BLOCKS,
        "arms": ARMS,
        "ledgers": ledgers,
    }


def main() -> None:
    payload = build_manifest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(OUTPUT)
    print(f"wrote {OUTPUT}")
    print(f"sha256={sha256_file(OUTPUT)}")


if __name__ == "__main__":
    main()
