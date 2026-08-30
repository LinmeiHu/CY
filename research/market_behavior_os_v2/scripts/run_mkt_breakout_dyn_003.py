#!/usr/bin/env python3
"""Execute the output-schema-only deterministic retry of breakout dynamics."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-DYN-003_spec.json"
EXPECTED_SPEC_SHA256 = "9cc7883f92d2980c3ac9488d85f9324d079355a28814333008ed116b44295d35"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


retry002 = _load_module(
    "run_mkt_breakout_dyn_002_for_output_retry",
    PROGRAM / "scripts/run_mkt_breakout_dyn_002.py",
)
base = retry002.base
_retry002_load_spec = retry002._load_spec
_retry002_load_parent_panel = retry002._load_parent_panel
_retry002_report = retry002._report


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    if base._sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise base.BreakoutDynamicsError("output-control spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        control["status"] != "FROZEN_BEFORE_DETERMINISTIC_RETRY"
        or not control["unchanged_science"]
        or control["revealed_002_estimates_used_to_change_science"]
    ):
        raise base.BreakoutDynamicsError("output-control activation changed")
    binding = control["scientific_control_parent"]
    path = _resolve(binding["path"])
    if not path.is_file() or base._sha256_file(path) != binding["sha256"]:
        raise base.BreakoutDynamicsError("002 control identity mismatch")
    effective, parent_result = _retry002_load_spec()
    effective = copy.deepcopy(effective)
    effective["experiment_id"] = control["experiment_id"]
    effective["outputs"] = control["output_corrections"]["outputs"]
    return effective, parent_result


def _report(result: dict[str, Any]) -> str:
    return _retry002_report(result).replace("MKT-BREAKOUT-DYN-002", "MKT-BREAKOUT-DYN-003")


def main() -> None:
    base.SPEC_PATH = SPEC_PATH
    base.PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-003_trajectory_panel.csv"
    base.STABILITY_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-003_stability_audit.csv"
    base.COUPLING_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-003_coupling_audit.csv"
    base.RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-003_result.json"
    base.REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-DYN-003_dynamics.md"
    base._load_spec = _load_spec
    base._load_parent_panel = _retry002_load_parent_panel
    base._report = _report
    base.RUNNER_DEPENDENCIES = {
        "scientific_runner": base._sha256_file(PROGRAM / "scripts/run_mkt_breakout_dyn_001.py"),
        "time_coordinate_runner": base._sha256_file(
            PROGRAM / "scripts/run_mkt_breakout_dyn_002.py"
        ),
    }
    base.__file__ = __file__
    base.main()


if __name__ == "__main__":
    main()
