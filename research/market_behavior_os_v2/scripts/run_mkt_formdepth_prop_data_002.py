#!/usr/bin/env python3
"""Run the frozen corrected formation-depth propagation response build."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
BASE_RUNNER = PROGRAM / "scripts/run_mkt_formdepth_prop_data_001.py"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-PROP-DATA-002_spec.json"
EXPECTED_SPEC_SHA256 = "8e3791ea0e08a7cc024e5b0086c82f0613f29bdfd04faa650b542a6ef4756215"


class CorrectedPropagationDataError(RuntimeError):
    """Fail-closed corrected response-domain error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_base_runner() -> Any:
    module_spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_prop_data_001_inherited", BASE_RUNNER
    )
    if module_spec is None or module_spec.loader is None:
        raise CorrectedPropagationDataError("cannot load inherited runner")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _effective_spec(base: Any) -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CorrectedPropagationDataError("corrected spec identity mismatch")
    correction = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        correction["status"] != "FROZEN_BEFORE_MEMBERSHIP_RESOLVED_RESPONSE_CONSTRUCTION"
        or correction["outcome_access"]
        != "FUTURE_PRE2024_MEMBERSHIP_RESOLVED_MARKET_RESPONSE_CONSTRUCTION_ONLY"
    ):
        raise CorrectedPropagationDataError("corrected activation boundary changed")
    for binding_name in ("inherits_scientific_spec", "correction_contract"):
        binding = correction[binding_name]
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CorrectedPropagationDataError(f"binding mismatch: {binding_name}")
    broad = correction["required_broad_bindings"]
    for kind in ("panel", "result"):
        path = _resolve(broad[f"{kind}_path"])
        if not path.is_file() or sha256_file(path) != broad[f"{kind}_sha256"]:
            raise CorrectedPropagationDataError(f"broad {kind} binding mismatch")
    if correction["invalid_predecessor"]["arm_artifact_accepted"]:
        raise CorrectedPropagationDataError("invalid predecessor boundary changed")
    if correction["invalid_predecessor"]["arm_association_inspected"]:
        raise CorrectedPropagationDataError("invalid predecessor outcome boundary changed")
    forbidden = "|".join(correction["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise CorrectedPropagationDataError("corrected prohibited boundary changed")

    inherited = base._load_spec()
    effective = copy.deepcopy(inherited)
    effective["experiment_id"] = correction["experiment_id"]
    effective["status"] = correction["status"]
    effective["outcome_access"] = correction["outcome_access"]
    effective["claim_boundary"] = correction["claim_boundary"]
    effective["broad_float_reproduction_mode"] = "IMMUTABLE_BOUND_PANEL_HASH"
    effective["entry_runner_path"] = str(Path(__file__).relative_to(ROOT))
    effective["inputs"]["correction_contract"] = correction["correction_contract"]
    effective["invalid_predecessor"] = correction["invalid_predecessor"]
    return effective


def main() -> None:
    base = _load_base_runner()
    effective = _effective_spec(base)
    base.SPEC_PATH = SPEC_PATH
    base.PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-002_panel.csv"
    base.COUNT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-002_count_audit.csv"
    base.SCALAR_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-002_scalar_audit.csv"
    base.RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-002_result.json"
    base.REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-PROP-DATA-002_audit.md"
    base.main(effective)


if __name__ == "__main__":
    main()
