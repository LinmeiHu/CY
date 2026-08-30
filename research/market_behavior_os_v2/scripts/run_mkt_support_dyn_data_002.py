#!/usr/bin/env python3
"""Exact scientific retry of the objective-recovery temporal sample audit."""

from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import psutil


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
PARENT_RUNNER = PROGRAM / "scripts/run_mkt_support_dyn_data_001.py"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DYN-DATA-002_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-002_sample.csv"
COORDINATE_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-002_coordinate_audit.csv"
POPULATION_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-002_population_audit.csv"
SUPPORT_COUNT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-002_support_count_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-DYN-DATA-002_audit.md"
EXPECTED_SPEC_SHA256 = "2bcf7cbff24fd3be5a405a4051af942de396c65445296a5849acd9a77587cfc9"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


parent = _load_module("run_mkt_support_dyn_data_001_parent", PARENT_RUNNER)
sha256_file = parent.sha256_file
SupportTemporalSampleError = parent.SupportTemporalSampleError
_parent_load_spec = parent._load_spec
_original_create_daily_coordinate = parent.data003.parent.parent._create_daily_coordinate
_active_temp_dir: Path | None = None
_maximum_live_spill_bytes = 0


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _record_spill() -> None:
    global _maximum_live_spill_bytes
    if _active_temp_dir is not None:
        _maximum_live_spill_bytes = max(
            _maximum_live_spill_bytes, _directory_bytes(_active_temp_dir)
        )


class _TrackedConnection:
    def __init__(self, connection: Any):
        self._connection = connection

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        result = self._connection.execute(*args, **kwargs)
        _record_spill()
        return result

    def register(self, *args: Any, **kwargs: Any) -> Any:
        result = self._connection.register(*args, **kwargs)
        _record_spill()
        return result

    def close(self) -> None:
        _record_spill()
        self._connection.close()
        if _active_temp_dir is not None and _active_temp_dir.exists():
            shutil.rmtree(_active_temp_dir)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportTemporalSampleError("002 control spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        control["status"]
        != "FROZEN_EXACT_SCIENTIFIC_RETRY_BEFORE_RAW_MINUTE_ACCESS"
        or control["outcome_access"] is not False
    ):
        raise SupportTemporalSampleError("002 activation changed")
    for name, binding in control["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportTemporalSampleError(f"002 input identity mismatch: {name}")
    if (
        control["invalid_parent"]["outputs_accepted"] is not False
        or control["invalid_parent"]["minute_rows_read"] != 0
    ):
        raise SupportTemporalSampleError("invalid-parent boundary changed")
    rebound_spec_path = parent.SPEC_PATH
    parent.SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DYN-DATA-001_spec.json"
    try:
        inherited = _parent_load_spec()
    finally:
        parent.SPEC_PATH = rebound_spec_path
    inherited["experiment_id"] = control["experiment_id"]
    inherited["status"] = control["status"]
    inherited["outputs"] = control["outputs"]
    inherited["claim_boundary"] = control["claim_boundary"]
    inherited["resource_budget"] = dict(inherited["resource_budget"])
    inherited["resource_budget"]["temporary_disk_ceiling_gib"] = control[
        "only_changes"
    ]["disposable_spill_ceiling_gib"]
    inherited["inputs"] = {
        **inherited["inputs"],
        **control["inputs"],
    }
    inherited["_retry_control"] = control
    return inherited


def _capped_create_daily_coordinate(
    spec: dict[str, Any], cy006_paths: dict[str, Path]
) -> Any:
    if _active_temp_dir is None:
        raise SupportTemporalSampleError("002 disposable spill directory missing")
    duckdb_module = parent.data003.parent.parent.duckdb
    original_connect = duckdb_module.connect

    def capped_connect(*args: Any, **kwargs: Any) -> Any:
        connection = original_connect(*args, **kwargs)
        connection.execute("SET memory_limit='2GB'")
        connection.execute("SET temp_directory=?", [str(_active_temp_dir)])
        return connection

    duckdb_module.connect = capped_connect
    try:
        connection = _original_create_daily_coordinate(spec, cy006_paths)
    finally:
        duckdb_module.connect = original_connect
    _record_spill()
    return _TrackedConnection(connection)


def _render_report(result: dict[str, Any]) -> str:
    adequacy = result["sample_adequacy"]
    return "\n".join(
        [
            "# MKT-SUPPORT-DYN-DATA-002 temporal-sample audit",
            "",
            "## Result",
            "",
            f"- Status: `{result['status']}`",
            f"- Sequences/cohort rows/unique sessions: {result['sample_audit']['sequences']:,}/{result['sample_audit']['cohort_rows']:,}/{result['sample_audit']['unique_security_sessions']:,}.",
            f"- Repeated-tested sequences: {adequacy['repeated_test_sequences']}; recovered sequences: {adequacy['recovered_sequences']}.",
            f"- Repeated by block: {adequacy['repeated_test_sequences_by_temporal_block']}; recovered by block: {adequacy['recovered_sequences_by_temporal_block']}.",
            "- The exact 001 science ran under the frozen one-thread/2-GiB-memory/10-GiB-disposable-spill envelope.",
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
    global _active_temp_dir, _maximum_live_spill_bytes
    _maximum_live_spill_bytes = 0
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    disk = psutil.disk_usage(ROOT)
    if disk.free / disk.total < control["unchanged_resource_gates"][
        "minimum_disk_headroom_fraction"
    ]:
        raise SupportTemporalSampleError("disk headroom floor breached")
    with tempfile.TemporaryDirectory(prefix="mkt-support-dyn-data-002-") as temp_dir:
        _active_temp_dir = Path(temp_dir)
        parent._load_spec = _load_spec
        parent.data003.parent.parent._create_daily_coordinate = _capped_create_daily_coordinate
        parent.SPEC_PATH = SPEC_PATH
        parent.SAMPLE_PATH = SAMPLE_PATH
        parent.COORDINATE_AUDIT_PATH = COORDINATE_AUDIT_PATH
        parent.POPULATION_AUDIT_PATH = POPULATION_AUDIT_PATH
        parent.SUPPORT_COUNT_PATH = SUPPORT_COUNT_PATH
        parent.RESULT_PATH = RESULT_PATH
        parent.REPORT_PATH = REPORT_PATH
        try:
            result = parent.run(verify_partition_content=verify_partition_content)
        finally:
            parent.data003.parent.parent._create_daily_coordinate = (
                _original_create_daily_coordinate
            )
            _active_temp_dir = None
    ceiling = control["only_changes"]["disposable_spill_ceiling_gib"] * 2**30
    if _maximum_live_spill_bytes > ceiling:
        raise SupportTemporalSampleError("002 disposable spill ceiling breached")
    result["experiment_id"] = "MKT-SUPPORT-DYN-DATA-002"
    result["resource_retry"] = {
        "exact_scientific_inheritance": True,
        "duckdb_threads": 1,
        "duckdb_memory_limit_gib": 2,
        "disposable_spill_below_10_gib": True,
        "spill_removed_before_minute_access": True,
        "parent_minute_rows_read": 0,
    }
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
