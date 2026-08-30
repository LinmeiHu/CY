#!/usr/bin/env python3
"""Execute the control-only time-coordinate retry of breakout dynamics."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-DYN-002_spec.json"
PARENT_SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-DYN-001_spec.json"
EXPECTED_SPEC_SHA256 = "973b6ecf89d12a10701f13e89233458d802d5ea25c24504135140c6758d8c209"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


base = _load_module(
    "run_mkt_breakout_dyn_001_for_control_retry",
    PROGRAM / "scripts/run_mkt_breakout_dyn_001.py",
)
_base_load_spec = base._load_spec
_base_load_parent_panel = base._load_parent_panel
_base_report = base._report


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    if base._sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise base.BreakoutDynamicsError("control spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        control["status"] != "FROZEN_BEFORE_ROLE_SPECIFIC_TRAJECTORY_COUNTS_OR_ESTIMATES"
        or not control["unchanged_science"]
        or control["role_specific_estimates_inspected_before_freeze"]
    ):
        raise base.BreakoutDynamicsError("control activation changed")
    for name in ["scientific_parent_spec", "control_correction_map"]:
        binding = control[name]
        path = _resolve(binding["path"])
        if not path.is_file() or base._sha256_file(path) != binding["sha256"]:
            raise base.BreakoutDynamicsError(f"control input identity mismatch: {name}")
    active_spec_path = base.SPEC_PATH
    base.SPEC_PATH = PARENT_SPEC_PATH
    try:
        parent_spec, parent_result = _base_load_spec()
    finally:
        base.SPEC_PATH = active_spec_path
    effective = copy.deepcopy(parent_spec)
    effective["experiment_id"] = control["experiment_id"]
    effective["population"]["event_time"] = control["overrides"]["event_time"]
    effective["population"]["required_sequence_time_grid"] = control["overrides"][
        "required_sequence_time_grid"
    ]
    effective["inputs"]["temporal_dynamics_map"] = control["control_correction_map"]
    effective["outputs"] = control["overrides"]["outputs"]
    return effective, parent_result


def _load_parent_panel(spec: dict[str, Any], parent: dict[str, Any]) -> pd.DataFrame:
    source = _base_load_parent_panel(spec, parent)
    allowed = set(spec["population"]["required_sequence_time_grid"])
    if not set(source["relative_day"].astype(int)).issubset(allowed):
        raise base.BreakoutDynamicsError("relative-day time domain changed")
    selection_unique = source.groupby("sequence_id")["market_sequence_rank"].nunique()
    if not bool(selection_unique.eq(1).all()):
        first = str(selection_unique.loc[~selection_unique.eq(1)].index[0])
        raise base.BreakoutDynamicsError(f"selection ordinal changed within sequence: {first}")
    corrected = source.copy()
    corrected["market_sequence_rank"] = corrected["relative_day"].astype(int)
    return corrected


def _report(result: dict[str, Any]) -> str:
    return _base_report(result).replace("MKT-BREAKOUT-DYN-001", "MKT-BREAKOUT-DYN-002")


def main() -> None:
    base.SPEC_PATH = SPEC_PATH
    base.PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-002_trajectory_panel.csv"
    base.STABILITY_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-002_stability_audit.csv"
    base.COUPLING_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-002_coupling_audit.csv"
    base.RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-002_result.json"
    base.REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-DYN-002_dynamics.md"
    base._load_spec = _load_spec
    base._load_parent_panel = _load_parent_panel
    base._report = _report
    base.__file__ = __file__
    base.main()


if __name__ == "__main__":
    main()
