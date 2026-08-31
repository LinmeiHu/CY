#!/usr/bin/env python3
"""Run the exact right-censoring implementation retry for own/shared data."""

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
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-OWN-DATA-003_spec.json"
EXPECTED_SPEC_SHA256 = "16e86ab7e0df9463e8027d6c5ebb17a21f21769a9464288491a3895d026726d5"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


base = _load_module("run_mkt_formdepth_own_data_001_for_retry3", PARENT_RUNNER)
_parent_load_spec = base._load_spec
_parent_report = base._report


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if base.sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise base.OwnSharedDataError("003 control spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        control["status"]
        != "FROZEN_EXACT_RIGHT_CENSORING_IMPLEMENTATION_RETRY_BEFORE_OUTPUT"
        or control["invalid_parent"]["outputs_accepted"] is not False
        or control["invalid_parent"]["association_or_adequacy_inspected"] is not False
        or control["diagnosed_first_difference"]["unbound_right_censored_date_cells"]
        != 36
    ):
        raise base.OwnSharedDataError("003 activation boundary changed")
    for name, binding in control["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or base.sha256_file(path) != binding["sha256"]:
            raise base.OwnSharedDataError(f"003 input identity mismatch: {name}")
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
    effective["resource_budget"]["peak_rss_ceiling_gib"] = 3.0
    effective["_implementation_retry_control"] = control
    return effective


def _report(result: dict[str, Any]) -> str:
    return _parent_report(result).replace(
        "MKT-FORMDEPTH-OWN-DATA-001", "MKT-FORMDEPTH-OWN-DATA-003"
    )


def main() -> None:
    base.SPEC_PATH = SPEC_PATH
    base.PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-003_panel.csv"
    base.COUNT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-003_count_audit.csv"
    base.SCALAR_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-003_scalar_audit.csv"
    base.RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-003_result.json"
    base.TELEMETRY_PATH = (
        PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-003_resource_telemetry.csv"
    )
    base.REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-OWN-DATA-003_audit.md"
    base._load_spec = _load_spec
    base._report = _report
    base.__file__ = __file__
    base.main()


if __name__ == "__main__":
    main()
