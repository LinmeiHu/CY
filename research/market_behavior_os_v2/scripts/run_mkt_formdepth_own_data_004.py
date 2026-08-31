#!/usr/bin/env python3
"""Run the exact structural-right-censor retry for own/shared data."""

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
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-OWN-DATA-004_spec.json"
EXPECTED_SPEC_SHA256 = "bb9b3b8854a282de1f6ac5cf97b2de9351077410b51f185dea0a1dcc9d6e8bce"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


base = _load_module("run_mkt_formdepth_own_data_001_for_retry4", PARENT_RUNNER)
_parent_load_spec = base._load_spec
_parent_report = base._report


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if base.sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise base.OwnSharedDataError("004 control spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        control["status"]
        != "FROZEN_EXACT_STRUCTURAL_RIGHT_CENSOR_RETRY_BEFORE_OUTPUT"
        or control["invalid_parent"]["outputs_accepted"] is not False
        or control["invalid_parent"]["association_or_adequacy_inspected"] is not False
        or control["diagnosed_domain"]["structurally_right_censored_date_cells"]
        != 36
    ):
        raise base.OwnSharedDataError("004 activation boundary changed")
    for name, binding in control["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or base.sha256_file(path) != binding["sha256"]:
            raise base.OwnSharedDataError(f"004 input identity mismatch: {name}")
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
    effective["_right_censor_retry_control"] = control
    return effective


def _report(result: dict[str, Any]) -> str:
    return _parent_report(result).replace(
        "MKT-FORMDEPTH-OWN-DATA-001", "MKT-FORMDEPTH-OWN-DATA-004"
    )


def main() -> None:
    base.SPEC_PATH = SPEC_PATH
    base.PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-004_panel.csv"
    base.COUNT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-004_count_audit.csv"
    base.SCALAR_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-004_scalar_audit.csv"
    base.RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-004_result.json"
    base.TELEMETRY_PATH = (
        PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-004_resource_telemetry.csv"
    )
    base.REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-OWN-DATA-004_audit.md"
    base._load_spec = _load_spec
    base._report = _report
    base.__file__ = __file__
    base.main()


if __name__ == "__main__":
    main()
