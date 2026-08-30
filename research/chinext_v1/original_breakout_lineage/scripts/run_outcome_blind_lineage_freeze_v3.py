#!/usr/bin/env python3
"""EXP-OBL-003 outcome-blind freeze with feasible every-year presence gate."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_outcome_blind_lineage_freeze as base  # noqa: E402
import run_outcome_blind_lineage_freeze_v2 as v2  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-003_spec.json"
FEATURE_TABLE = WORK / "artifacts/formation_features_v3.csv"
ASSIGNMENT_TABLE = WORK / "artifacts/lineage_assignments_v3.csv"
AUDIT_JSON = WORK / "artifacts/EXP-OBL-003_audit.json"
FREEZE_MANIFEST = WORK / "lineage_freezes/LINEAGE-OBL-003.json"
REPORT = WORK / "reports/EXP-OBL-003_outcome_blind_lineage_freeze.md"


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-003":
        raise base.LineageFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_REVEAL":
        raise base.LineageFreezeError("experiment is not frozen before outcome reveal")
    if spec.get("outcome_access") is not False:
        raise base.LineageFreezeError("outcome access prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = base.resolve_path(binding["path"])
        if not path.is_file():
            raise base.LineageFreezeError(f"missing bound input: {role}: {path}")
        actual = base.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise base.LineageFreezeError(f"frozen input mismatch: {mismatches}")
    base.phase2.validate_inputs()
    return spec, identities


def main() -> None:
    # Reuse the clean OBL-002 implementation while rebinding every mutable identity
    # to fresh OBL-003 paths. The scientific construction stays in frozen base code.
    v2.SPEC = SPEC
    v2.FEATURE_TABLE = FEATURE_TABLE
    v2.ASSIGNMENT_TABLE = ASSIGNMENT_TABLE
    v2.AUDIT_JSON = AUDIT_JSON
    v2.FREEZE_MANIFEST = FREEZE_MANIFEST
    v2.REPORT = REPORT
    v2.validate_spec_and_inputs = validate_spec_and_inputs
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        v2.main()

    audit = json.loads(AUDIT_JSON.read_text(encoding="utf-8"))
    assignment_sha = base.sha256_file(ASSIGNMENT_TABLE)
    freeze_id = f"LINEAGE-OBL-003-{assignment_sha[:16].upper()}"
    old_freeze_id = audit["lineage_freeze_id"]
    audit["experiment_id"] = "EXP-OBL-003"
    audit["lineage_freeze_id"] = freeze_id
    base.atomic_write(
        AUDIT_JSON,
        json.dumps(base.clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
    )

    manifest = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    manifest.update(
        {
            "experiment_id": "EXP-OBL-003",
            "lineage_freeze_id": freeze_id,
            "spec_path": str(SPEC.relative_to(ROOT)),
            "spec_sha256": base.sha256_file(SPEC),
            "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
            "runner_sha256": base.sha256_file(Path(__file__).resolve()),
            "audit_sha256": base.sha256_file(AUDIT_JSON),
        }
    )
    base.atomic_write(
        FREEZE_MANIFEST,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    report = REPORT.read_text(encoding="utf-8")
    report = report.replace("EXP-OBL-002", "EXP-OBL-003").replace(
        old_freeze_id, freeze_id
    )
    base.atomic_write(REPORT, report)
    print(json.dumps(base.clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
