#!/usr/bin/env python3
"""Run the measured-RSS-only retry of the own/shared stratum data domain."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
PARENT_RUNNER = PROGRAM / "scripts/run_mkt_formdepth_own_data_001.py"
PARENT_SPEC = PROGRAM / "experiments/MKT-FORMDEPTH-OWN-DATA-001_spec.json"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-OWN-DATA-002_spec.json"
EXPECTED_SPEC_SHA256 = "d200a440976b6ae70aa6091887853071af0e1c76718d491cff1c6437260a8d4a"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


base = _load_module("run_mkt_formdepth_own_data_001_parent", PARENT_RUNNER)
_parent_load_spec = base._load_spec
_parent_report = base._report


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if base.sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise base.OwnSharedDataError("002 control spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        control["status"]
        != "FROZEN_EXACT_RESOURCE_RETRY_BEFORE_OWN_SHARED_STRATUM_RESPONSE_CONSTRUCTION"
        or control["invalid_parent"]["outputs_accepted"] is not False
        or control["invalid_parent"]["association_or_adequacy_inspected"] is not False
    ):
        raise base.OwnSharedDataError("002 activation boundary changed")
    for name, binding in control["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or base.sha256_file(path) != binding["sha256"]:
            raise base.OwnSharedDataError(f"002 input identity mismatch: {name}")
    active_spec_path = base.SPEC_PATH
    base.SPEC_PATH = PARENT_SPEC
    try:
        inherited = _parent_load_spec()
    finally:
        base.SPEC_PATH = active_spec_path
    effective = copy.deepcopy(inherited)
    effective["experiment_id"] = control["experiment_id"]
    effective["status"] = control["status"]
    effective["outputs"] = control["outputs"]
    effective["claim_boundary"] = control["claim_boundary"]
    effective["resource_budget"]["peak_rss_ceiling_gib"] = control[
        "only_changes"
    ]["peak_rss_ceiling_gib_to"]
    effective["_resource_retry_control"] = control
    return effective


def _report(result: dict[str, Any]) -> str:
    return _parent_report(result).replace(
        "MKT-FORMDEPTH-OWN-DATA-001", "MKT-FORMDEPTH-OWN-DATA-002"
    )


def main() -> None:
    base.SPEC_PATH = SPEC_PATH
    base.PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-002_panel.csv"
    base.COUNT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-002_count_audit.csv"
    base.SCALAR_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-002_scalar_audit.csv"
    base.RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-002_result.json"
    base.TELEMETRY_PATH = (
        PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-002_resource_telemetry.csv"
    )
    base.REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-OWN-DATA-002_audit.md"
    base._load_spec = _load_spec
    base._report = _report
    base.__file__ = __file__
    base.main()


if __name__ == "__main__":
    main()
