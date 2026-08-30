#!/usr/bin/env python3
"""Final measured-resource retry of the block-batched sample audit."""

from __future__ import annotations

import importlib.util
import json
import warnings
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
PARENT_RUNNER = PROGRAM / "scripts/run_mkt_support_dyn_data_003.py"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DYN-DATA-004_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-004_sample.csv"
COORDINATE_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-004_coordinate_audit.csv"
POPULATION_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-004_population_audit.csv"
SUPPORT_COUNT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-004_support_count_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-004_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-DYN-DATA-004_audit.md"
EXPECTED_SPEC_SHA256 = "63c8a1f86dcf1e05e8f4284df3c1d9d2454c50dbc1f56e670b4a83090c35e6e2"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


retry003 = _load_module("run_mkt_support_dyn_data_003_parent", PARENT_RUNNER)
sha256_file = retry003.sha256_file
SupportTemporalSampleError = retry003.SupportTemporalSampleError
_parent_load_spec = retry003._load_spec
warnings.filterwarnings(
    "ignore",
    message="Downcasting object dtype arrays on .fillna.*",
    category=FutureWarning,
)


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportTemporalSampleError("004 control spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        control["status"]
        != "FROZEN_FINAL_EXACT_RESOURCE_RETRY_BEFORE_COMPLETE_MINUTE_AUDIT"
        or control["outcome_access"] is not False
    ):
        raise SupportTemporalSampleError("004 activation changed")
    for name, binding in control["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportTemporalSampleError(f"004 input identity mismatch: {name}")
    if (
        control["invalid_parent"]["outputs_accepted"] is not False
        or control["invalid_parent"]["adequacy_counts_inspected_or_accepted"] is not False
    ):
        raise SupportTemporalSampleError("004 invalid-parent boundary changed")
    rebound = retry003.SPEC_PATH
    retry003.SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DYN-DATA-003_spec.json"
    try:
        inherited = _parent_load_spec()
    finally:
        retry003.SPEC_PATH = rebound
    inherited["experiment_id"] = control["experiment_id"]
    inherited["status"] = control["status"]
    inherited["outputs"] = control["outputs"]
    inherited["claim_boundary"] = control["claim_boundary"]
    inherited["inputs"] = {**inherited["inputs"], **control["inputs"]}
    inherited["_retry4_control"] = control
    return inherited


def _capped_create_daily_coordinate_1_5_gib(
    spec: dict[str, Any], cy006_paths: dict[str, Path]
) -> Any:
    retry002 = retry003.retry002
    if retry002._active_temp_dir is None:
        raise SupportTemporalSampleError("004 disposable spill directory missing")
    duckdb_module = retry003.parent.data003.parent.parent.duckdb
    original_connect = duckdb_module.connect

    def capped_connect(*args: Any, **kwargs: Any) -> Any:
        connection = original_connect(*args, **kwargs)
        connection.execute("SET memory_limit='1.5GB'")
        connection.execute("SET temp_directory=?", [str(retry002._active_temp_dir)])
        return connection

    duckdb_module.connect = capped_connect
    try:
        connection = retry002._original_create_daily_coordinate(spec, cy006_paths)
    finally:
        duckdb_module.connect = original_connect
    retry002._record_spill()
    return retry002._TrackedConnection(connection)


def _render_report(result: dict[str, Any]) -> str:
    adequacy = result["sample_adequacy"]
    reference = result["reference_equivalence"]
    return "\n".join(
        [
            "# MKT-SUPPORT-DYN-DATA-004 temporal-sample audit",
            "",
            "## Result",
            "",
            f"- Status: `{result['status']}`",
            f"- Sequences/cohort rows/unique sessions: {result['sample_audit']['sequences']:,}/{result['sample_audit']['cohort_rows']:,}/{result['sample_audit']['unique_security_sessions']:,}.",
            f"- Repeated-tested sequences: {adequacy['repeated_test_sequences']}; recovered sequences: {adequacy['recovered_sequences']}.",
            f"- Repeated by block: {adequacy['repeated_test_sequences_by_temporal_block']}; recovered by block: {adequacy['recovered_sequences_by_temporal_block']}.",
            f"- First-block reference equivalence: {reference['cohort_rows']} rows, hash `{reference['reference_sha256']}`, exact equal.",
            "- The final 1.5-GiB daily-memory/block-batched resource contract completed without changing the sample or science.",
            "- Counts alone determine whether a later temporal map may be frozen. No process, payoff, or strategy estimate was constructed.",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Sample SHA-256: `{result['hashes']['sample_sha256']}`",
            f"- Coordinate audit SHA-256: `{result['hashes']['coordinate_audit_sha256']}`",
            f"- Support-count audit SHA-256: `{result['hashes']['support_count_audit_sha256']}`",
        ]
    ) + "\n"


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    original_load = retry003._load_spec
    original_spec_path = retry003.SPEC_PATH
    original_sample_path = retry003.SAMPLE_PATH
    original_coordinate_path = retry003.COORDINATE_AUDIT_PATH
    original_population_path = retry003.POPULATION_AUDIT_PATH
    original_support_count_path = retry003.SUPPORT_COUNT_PATH
    original_result_path = retry003.RESULT_PATH
    original_report_path = retry003.REPORT_PATH
    original_capped = retry003.retry002._capped_create_daily_coordinate
    retry003._load_spec = _load_spec
    retry003.SPEC_PATH = SPEC_PATH
    retry003.SAMPLE_PATH = SAMPLE_PATH
    retry003.COORDINATE_AUDIT_PATH = COORDINATE_AUDIT_PATH
    retry003.POPULATION_AUDIT_PATH = POPULATION_AUDIT_PATH
    retry003.SUPPORT_COUNT_PATH = SUPPORT_COUNT_PATH
    retry003.RESULT_PATH = RESULT_PATH
    retry003.REPORT_PATH = REPORT_PATH
    retry003.retry002._capped_create_daily_coordinate = (
        _capped_create_daily_coordinate_1_5_gib
    )
    try:
        result = retry003.run(verify_partition_content=verify_partition_content)
    finally:
        retry003._load_spec = original_load
        retry003.SPEC_PATH = original_spec_path
        retry003.SAMPLE_PATH = original_sample_path
        retry003.COORDINATE_AUDIT_PATH = original_coordinate_path
        retry003.POPULATION_AUDIT_PATH = original_population_path
        retry003.SUPPORT_COUNT_PATH = original_support_count_path
        retry003.RESULT_PATH = original_result_path
        retry003.REPORT_PATH = original_report_path
        retry003.retry002._capped_create_daily_coordinate = original_capped
    result["experiment_id"] = "MKT-SUPPORT-DYN-DATA-004"
    result["resource_retry"]["duckdb_memory_limit_gib"] = 1.5
    result["resource_retry"]["parent_003_complete_outputs_accepted"] = False
    result["hashes"]["spec_sha256"] = sha256_file(SPEC_PATH)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "sample_adequacy": completed["sample_adequacy"],
            },
            indent=2,
            sort_keys=True,
        )
    )
