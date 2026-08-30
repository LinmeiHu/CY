#!/usr/bin/env python3
"""Block-batched exact retry of the objective-recovery sample audit."""

from __future__ import annotations

import copy
import gc
import hashlib
import importlib.util
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd
import psutil


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
PARENT_RUNNER = PROGRAM / "scripts/run_mkt_support_dyn_data_002.py"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DYN-DATA-003_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-003_sample.csv"
COORDINATE_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-003_coordinate_audit.csv"
POPULATION_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-003_population_audit.csv"
SUPPORT_COUNT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-003_support_count_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-003_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-DYN-DATA-003_audit.md"
EXPECTED_SPEC_SHA256 = "e8045eb3953f17c08e8e7324f0ea1f10e11c4c4206c16c591f65fca129824a68"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


retry002 = _load_module("run_mkt_support_dyn_data_002_parent", PARENT_RUNNER)
parent = retry002.parent
sha256_file = parent.sha256_file
SupportTemporalSampleError = parent.SupportTemporalSampleError
_parent_audit_minutes_and_recovery = parent.audit_minutes_and_recovery


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportTemporalSampleError("003 control spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        control["status"]
        != "FROZEN_EXACT_BLOCK_BATCH_RETRY_BEFORE_COMPLETE_MINUTE_AUDIT"
        or control["outcome_access"] is not False
    ):
        raise SupportTemporalSampleError("003 activation changed")
    for name, binding in control["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportTemporalSampleError(f"003 input identity mismatch: {name}")
    if (
        control["invalid_parent"]["outputs_accepted"] is not False
        or control["invalid_parent"]["adequacy_counts_inspected_or_accepted"] is not False
    ):
        raise SupportTemporalSampleError("003 invalid-parent boundary changed")
    inherited = retry002._load_spec()
    inherited["experiment_id"] = control["experiment_id"]
    inherited["status"] = control["status"]
    inherited["outputs"] = control["outputs"]
    inherited["claim_boundary"] = control["claim_boundary"]
    inherited["inputs"] = {**inherited["inputs"], **control["inputs"]}
    inherited["_retry3_control"] = control
    return inherited


def _batch_spec(spec: dict[str, Any], batch_sample: pd.DataFrame) -> dict[str, Any]:
    batch = copy.deepcopy(spec)
    batch["sample"] = dict(batch["sample"])
    batch["sample"]["expected_cohort_rows"] = len(batch_sample)
    batch["sample"]["expected_unique_security_sessions"] = len(
        batch_sample[["symbol", "trade_date"]].drop_duplicates()
    )
    return batch


def _block_audit(
    spec: dict[str, Any],
    sample: pd.DataFrame,
    coordinates: pd.DataFrame,
    partitions: dict[str, dict[str, Path]],
    started: float,
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for (year, block_id), batch_sample in sample.groupby(
        ["target_year", "block_id"], sort=True
    ):
        if batch_sample["trade_date"].nunique() != 5:
            raise SupportTemporalSampleError(f"003 batch date count changed: {year}:{block_id}")
        keys = batch_sample[["symbol", "trade_date"]].drop_duplicates()
        batch_coordinates = coordinates.merge(
            keys, on=["symbol", "trade_date"], validate="one_to_one"
        )
        piece = _parent_audit_minutes_and_recovery(
            _batch_spec(spec, batch_sample),
            batch_sample,
            batch_coordinates,
            partitions,
            started,
        )
        pieces.append(piece)
        del piece, batch_coordinates, keys
        gc.collect()
        parent._resource_guard(spec, started)
    output = pd.concat(pieces, ignore_index=True).sort_values("audit_id").reset_index(drop=True)
    if len(output) != spec["sample"]["expected_cohort_rows"]:
        raise SupportTemporalSampleError("003 complete cohort row count changed")
    if len(output[["symbol", "trade_date"]].drop_duplicates()) != spec["sample"][
        "expected_unique_security_sessions"
    ]:
        raise SupportTemporalSampleError("003 complete unique-session count changed")
    expected_raw = (
        spec["sample"]["expected_unique_security_sessions"]
        * spec["coordinate_and_minute_contract"]["rows_per_session"]
    )
    if (
        spec["sample"]["expected_cohort_rows"] == 9600
        and expected_raw
        != spec["_retry3_control"]["only_change"]["exact_expected_complete_raw_rows"]
    ):
        raise SupportTemporalSampleError("003 raw-row conservation changed")
    return output


def _canonical_frame_hash(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values("audit_id").reset_index(drop=True)
    payload = ordered.to_csv(
        index=False, float_format="%.17g", lineterminator="\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_first_block_equivalence(
    spec: dict[str, Any],
    sample: pd.DataFrame,
    coordinates: pd.DataFrame,
    partitions: dict[str, dict[str, Path]],
    started: float,
) -> dict[str, Any]:
    control = spec["_retry3_control"]["reference_equivalence"]
    mask = sample["target_year"].eq(control["year"]) & sample["block_id"].eq(
        control["block_id"]
    )
    reference_sample = sample.loc[mask].copy()
    keys = reference_sample[["symbol", "trade_date"]].drop_duplicates()
    reference_coordinates = coordinates.merge(
        keys, on=["symbol", "trade_date"], validate="one_to_one"
    )
    reference = _parent_audit_minutes_and_recovery(
        _batch_spec(spec, reference_sample),
        reference_sample,
        reference_coordinates,
        partitions,
        started,
    )
    candidate = _block_audit(
        _batch_spec(spec, reference_sample),
        reference_sample,
        reference_coordinates,
        partitions,
        started,
    )
    try:
        pd.testing.assert_frame_equal(
            reference.sort_values("audit_id").reset_index(drop=True),
            candidate.sort_values("audit_id").reset_index(drop=True),
            check_exact=True,
            check_dtype=True,
        )
    except AssertionError as exc:
        raise SupportTemporalSampleError("003 first-block reference disagreement") from exc
    reference_hash = _canonical_frame_hash(reference)
    candidate_hash = _canonical_frame_hash(candidate)
    if reference_hash != candidate_hash:
        raise SupportTemporalSampleError("003 first-block canonical hash disagreement")
    result = {
        "year": int(control["year"]),
        "block_id": int(control["block_id"]),
        "cohort_rows": len(reference),
        "unique_sessions": len(reference[["symbol", "trade_date"]].drop_duplicates()),
        "reference_sha256": reference_hash,
        "candidate_sha256": candidate_hash,
        "exact_equal": True,
    }
    del reference, candidate, reference_sample, reference_coordinates, keys
    gc.collect()
    parent._resource_guard(spec, started)
    return result


def _render_report(result: dict[str, Any]) -> str:
    adequacy = result["sample_adequacy"]
    reference = result["reference_equivalence"]
    return "\n".join(
        [
            "# MKT-SUPPORT-DYN-DATA-003 temporal-sample audit",
            "",
            "## Result",
            "",
            f"- Status: `{result['status']}`",
            f"- Sequences/cohort rows/unique sessions: {result['sample_audit']['sequences']:,}/{result['sample_audit']['cohort_rows']:,}/{result['sample_audit']['unique_security_sessions']:,}.",
            f"- Repeated-tested sequences: {adequacy['repeated_test_sequences']}; recovered sequences: {adequacy['recovered_sequences']}.",
            f"- Repeated by block: {adequacy['repeated_test_sequences_by_temporal_block']}; recovered by block: {adequacy['recovered_sequences_by_temporal_block']}.",
            f"- First-block reference equivalence: {reference['cohort_rows']} rows, hash `{reference['reference_sha256']}`, exact equal.",
            "- Complete block-batched raw-row conservation is 2,307,575. No process, payoff, or strategy estimate was constructed.",
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
    retry002._maximum_live_spill_bytes = 0
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    disk = psutil.disk_usage(ROOT)
    if disk.free / disk.total < 0.25:
        raise SupportTemporalSampleError("003 disk headroom floor breached")
    with tempfile.TemporaryDirectory(prefix="mkt-support-dyn-data-003-") as temp_dir:
        retry002._active_temp_dir = Path(temp_dir)
        parent._load_spec = _load_spec
        parent.audit_minutes_and_recovery = _block_audit
        parent.data003.parent.parent._create_daily_coordinate = (
            retry002._capped_create_daily_coordinate
        )
        parent.SPEC_PATH = SPEC_PATH
        parent.SAMPLE_PATH = SAMPLE_PATH
        parent.COORDINATE_AUDIT_PATH = COORDINATE_AUDIT_PATH
        parent.POPULATION_AUDIT_PATH = POPULATION_AUDIT_PATH
        parent.SUPPORT_COUNT_PATH = SUPPORT_COUNT_PATH
        parent.RESULT_PATH = RESULT_PATH
        parent.REPORT_PATH = REPORT_PATH

        original_block_audit = parent.audit_minutes_and_recovery
        original_run = parent.run
        reference_result: dict[str, Any] = {}

        def audited_block_runner(
            spec: dict[str, Any],
            sample: pd.DataFrame,
            coordinates: pd.DataFrame,
            partitions: dict[str, dict[str, Path]],
            started: float,
        ) -> pd.DataFrame:
            nonlocal reference_result
            reference_result = validate_first_block_equivalence(
                spec, sample, coordinates, partitions, started
            )
            return _block_audit(spec, sample, coordinates, partitions, started)

        parent.audit_minutes_and_recovery = audited_block_runner
        try:
            result = original_run(verify_partition_content=verify_partition_content)
        finally:
            parent.audit_minutes_and_recovery = _parent_audit_minutes_and_recovery
            parent.data003.parent.parent._create_daily_coordinate = (
                retry002._original_create_daily_coordinate
            )
            retry002._active_temp_dir = None
    ceiling = 10 * 2**30
    if retry002._maximum_live_spill_bytes > ceiling:
        raise SupportTemporalSampleError("003 disposable spill ceiling breached")
    result["experiment_id"] = "MKT-SUPPORT-DYN-DATA-003"
    result["reference_equivalence"] = reference_result
    result["resource_retry"] = {
        "exact_scientific_inheritance": True,
        "duckdb_threads": 1,
        "duckdb_memory_limit_gib": 2,
        "disposable_spill_below_10_gib": True,
        "spill_removed_before_minute_access": True,
        "minute_batch_keys": ["target_year", "block_id"],
        "complete_raw_minute_rows": 2307575,
        "parent_002_complete_outputs_accepted": False,
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
