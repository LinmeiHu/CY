#!/usr/bin/env python3
"""Run final pre-response support amendment for dispersion-rank direction."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-DISP-RANK-005_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-005_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-005_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-DISP-RANK-005_industry_rank.md"
BASE_PATH = PROGRAM / "scripts/run_mkt_disp_rank_004.py"
EXPECTED_SPEC_SHA256 = "7fb0be1c519eb30e69e5c6aaf05d792439d0eb70c4640e20cbeda5e63e848b1c"


class FinalDispersionSupportError(RuntimeError):
    """Fail-closed final dispersion support amendment error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise FinalDispersionSupportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


BASE = _load_module("mkt_disp_rank_004_for_005", BASE_PATH)


def _load_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise FinalDispersionSupportError("final support spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_FINAL_SUPPORT_AMENDMENT_BEFORE_RESPONSE_SUMMARIES":
        raise FinalDispersionSupportError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise FinalDispersionSupportError(f"bound input changed: {name}")
    amended = json.loads(
        _resolve(spec["inputs"]["amended_spec"]["path"]).read_text(encoding="utf-8")
    )
    return spec, amended


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def run() -> dict[str, Any]:
    spec, amended = _load_spec()
    resource_spec = BASE.RESOURCE._load_spec()
    preflight = BASE.RESOURCE._resource_preflight(resource_spec)
    retry, scientific, industry_spec, industry_runner, rank = (
        BASE.RESOURCE.BASE._load_spec()
    )
    effective = BASE.RESOURCE._effective_scientific(scientific, resource_spec)
    effective["support"]["minimum_high_state_rows_per_cell_year"] = spec[
        "only_change"
    ]["minimum_high_state_rows_per_supported_cell_year"]
    scratch = Path(resource_spec["resource_contract"]["scratch_root"])
    previous_tempdir = tempfile.tempdir
    previous_builder = BASE.RESOURCE.BASE._create_rank_security_for_year
    tempfile.tempdir = str(scratch)
    BASE.RESOURCE.BASE._create_rank_security_for_year = (
        BASE.RESOURCE._create_rank_security_for_year_explicit_group
    )
    try:
        daily, telemetry = BASE.RESOURCE.BASE._build_daily_batched(
            retry, effective, industry_spec, industry_runner, rank
        )
    finally:
        tempfile.tempdir = previous_tempdir
        BASE.RESOURCE.BASE._create_rank_security_for_year = previous_builder
    panel, result = BASE._analyze_high_only(daily, effective, amended, rank)
    result["experiment_id"] = spec["experiment_id"]
    result["status"] = "COMPLETE_FINAL_SUPPORT_AMENDMENT"
    result["annual_support_amendment"] = spec["only_change"]
    result["no_further_support_amendment"] = True
    result["resource_preflight"] = preflight
    result["resource_contract"] = resource_spec["resource_contract"]
    result["engineering"] = telemetry
    panel_csv = panel.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    if len(panel_csv.encode("utf-8")) > int(
        resource_spec["resource_contract"]["durable_output_ceiling_mib"] * 2**20
    ):
        raise FinalDispersionSupportError("durable output ceiling breached")
    _atomic_write(PANEL_PATH, panel_csv)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
    }
    report = BASE._render(result).replace("MKT-DISP-RANK-004", "MKT-DISP-RANK-005")
    report += (
        "\nThe minimum annual high-state support is 15 dates rather than the "
        "original 20. This was the final support-only amendment, frozen before any "
        "response summary was available; it limits confidence in the thin 2023 "
        "cell-year and cannot be relaxed again.\n"
    )
    _atomic_write(REPORT_PATH, report)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(rank._clean(result), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True, default=str))
