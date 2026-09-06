#!/usr/bin/env python3
"""Freeze the V34R1 Phase-2A anonymous attribution-review ledger.

``--verify-static-contract`` checks only constants embedded in this repository
script.  It does not stat, hash, open, or parse any external artifact or any
annotation slice.

``--run`` reads exactly three fixed anonymous annotation slices plus the
anonymous Phase-2A chart index and its 915 individual PNGs.  It never reads a
Phase-1 ledger, a Stage-B artifact, an identity mapping, or a numeric return,
and it performs no rule construction or aggregation.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

EXPERIMENT = "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34R1"
STAGE = "PHASE2A_ANONYMOUS_ATTRIBUTION_REVIEW_FROZEN"
REPO = Path(__file__).resolve().parents[3]
FINALIZER_REL = (
    "research/market_behavior_os_v2/scripts/"
    "finalize_ashare_cash_distribution_realized_payout_quality_mother_v34r1_phase2a.py"
)

ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_cash_distribution_realized_payout_quality_mother_v34r1"
)
ANONYMOUS_CHART_ROOT = ROOT / "stage_e_phase2a_2018_2019_outcome_attribution"
ANONYMOUS_CHART_INDEX = ANONYMOUS_CHART_ROOT / "phase2a_chart_index.csv"
INDIVIDUAL_CHART_ROOT = ANONYMOUS_CHART_ROOT / "individual_attribution_charts"
OUTPUT = ROOT / "stage_f_phase2a_anonymous_review"

EXPECTED_EVENTS = 915
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
OPAQUE_ID_PATTERN = re.compile(r"B-[0-9a-f]{20}")
POSITIVE_INTEGER_PATTERN = re.compile(r"[1-9][0-9]*")

INDEX_FIELDS = (
    "chart_number",
    "blind_chart_id",
    "full_chart_path",
    "full_chart_sha256",
    "outcome_bucket",
)
ANNOTATION_FIELDS = (
    "chart_number",
    "blind_chart_id",
    "outcome_bucket",
    "post_path_label",
    "evidence",
    "reviewer",
    "phase1_labels_modified",
    "signal_candle_used_for_rule",
    "post_signal_used_as_predictor",
)
FALSE_GOVERNANCE_FIELDS = (
    "phase1_labels_modified",
    "signal_candle_used_for_rule",
    "post_signal_used_as_predictor",
)
OUTCOME_BUCKETS = (
    "PROFIT_GE_4PCT",
    "PROFIT_0_TO_4PCT",
    "LOSS_0_TO_10PCT",
    "SEVERE_LOSS",
    "NO_COMPLETED_TRADE",
)
POST_PATH_LABELS = (
    "IMMEDIATE_ACCEPTANCE",
    "DELAYED_ACCEPTANCE",
    "EARLY_REJECTION",
    "LATE_REJECTION",
    "CHOP_OR_AMBIGUOUS",
    "NO_COMPLETED_TRADE",
)

# start/end are one-based row positions after the anonymous chart index has
# been verified to be in strictly ascending chart_number order.  They are not
# assumptions that the underlying chart_number values are contiguous.
SLICE_SPECS = (
    (
        "galileo_slice_0001_0305",
        1,
        305,
        "Galileo-phase2a",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase2a_annotations_galileo_slice_0001_0305.json",
    ),
    (
        "bacon_slice_0306_0610",
        306,
        610,
        "Bacon-phase2a",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase2a_annotations_bacon_slice_0306_0610.json",
    ),
    (
        "templateaudit_slice_0611_0915",
        611,
        915,
        "TemplateAudit",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase2a_annotations_templateaudit_slice_0611_0915.json",
    ),
)


class FreezeError(RuntimeError):
    """Fail closed on anonymous input, schema, hash, or publication drift."""


def sha256_file(path: Path, label: str, *, reject_symlink: bool = True) -> str:
    if reject_symlink and path.is_symlink():
        raise FreezeError(f"{label} must not be a symbolic link: {path}")
    if not path.is_file():
        raise FreezeError(f"missing regular file for {label}: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FreezeError(f"cannot hash {label} at {path}: {exc}") from exc
    return digest.hexdigest()


def strict_json(path: Path, label: str) -> Any:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise FreezeError(f"duplicate JSON keys in {label}: {duplicates}")
        return dict(pairs)

    if path.is_symlink():
        raise FreezeError(f"{label} must not be a symbolic link: {path}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read {label} at {path}: {exc}") from exc


def require_exact_keys(value: Any, expected: Iterable[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise FreezeError(f"{label} must contain exactly {tuple(expected)}")
    return value


def require_text(value: Any, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or not value.isprintable()
        or "\n" in value
        or "\r" in value
    ):
        raise FreezeError(f"{label} must be one trimmed printable line <= {maximum} chars")
    return value


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise FreezeError(f"{label} must be one lowercase SHA-256 digest")
    return value


def repo_input(relative_path: str, label: str) -> Path:
    if relative_path.startswith("/") or ".." in Path(relative_path).parts:
        raise FreezeError(f"{label} must be one fixed repository-relative path")
    return REPO.joinpath(*Path(relative_path).parts)


def validate_static_contract() -> dict[str, Any]:
    expected_ranges = [(1, 305), (306, 610), (611, 915)]
    actual_ranges = [(start, end) for _, start, end, _, _ in SLICE_SPECS]
    if actual_ranges != expected_ranges:
        raise FreezeError("fixed anonymous slice row-position ranges drift")
    if sum(end - start + 1 for _, start, end, _, _ in SLICE_SPECS) != EXPECTED_EVENTS:
        raise FreezeError("fixed anonymous slices do not cover exactly 915 row positions")
    if [reviewer for _, _, _, reviewer, _ in SLICE_SPECS] != [
        "Galileo-phase2a",
        "Bacon-phase2a",
        "TemplateAudit",
    ]:
        raise FreezeError("fixed reviewer-by-slice contract drift")
    if len(ANNOTATION_FIELDS) != 9 or tuple(FALSE_GOVERNANCE_FIELDS) != (
        "phase1_labels_modified",
        "signal_candle_used_for_rule",
        "post_signal_used_as_predictor",
    ):
        raise FreezeError("exact nine-field annotation schema drift")
    if len(set(OUTCOME_BUCKETS)) != len(OUTCOME_BUCKETS) or len(
        set(POST_PATH_LABELS)
    ) != len(POST_PATH_LABELS):
        raise FreezeError("anonymous label enumeration contains duplicates")
    if ANONYMOUS_CHART_INDEX.parent != ANONYMOUS_CHART_ROOT:
        raise FreezeError("anonymous chart-index location drift")
    if INDIVIDUAL_CHART_ROOT.parent != ANONYMOUS_CHART_ROOT:
        raise FreezeError("individual-chart location drift")
    if OUTPUT.parent != ROOT or OUTPUT.name != "stage_f_phase2a_anonymous_review":
        raise FreezeError("exclusive output location drift")
    if tuple(path for *_, path in SLICE_SPECS) != (
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase2a_annotations_galileo_slice_0001_0305.json",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase2a_annotations_bacon_slice_0306_0610.json",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase2a_annotations_templateaudit_slice_0611_0915.json",
    ):
        raise FreezeError("fixed annotation-slice paths drift")
    return {
        "status": "STATIC_CONTRACT_PASS",
        "experiment": EXPERIMENT,
        "expected_events": EXPECTED_EVENTS,
        "annotation_fields": list(ANNOTATION_FIELDS),
        "reviewer_slices": [
            {
                "slice_id": slice_id,
                "row_positions": [start, end],
                "reviewer": reviewer,
                "path": path,
            }
            for slice_id, start, end, reviewer, path in SLICE_SPECS
        ],
        "external_files_touched": False,
        "annotation_slices_touched": False,
    }


def load_anonymous_index() -> tuple[list[dict[str, Any]], str]:
    index_hash = sha256_file(ANONYMOUS_CHART_INDEX, "anonymous chart index")
    if ANONYMOUS_CHART_INDEX.is_symlink():
        raise FreezeError("anonymous chart index must not be a symbolic link")
    try:
        with ANONYMOUS_CHART_INDEX.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != INDEX_FIELDS:
                raise FreezeError(
                    f"anonymous chart-index header must be exactly {INDEX_FIELDS}"
                )
            rows: list[dict[str, Any]] = []
            for line_number, raw in enumerate(reader, start=2):
                if set(raw) != set(INDEX_FIELDS) or any(
                    raw[field] is None for field in INDEX_FIELDS
                ):
                    raise FreezeError(f"chart-index field drift at line {line_number}")
                values = {field: raw[field] for field in INDEX_FIELDS}
                if any(value != value.strip() or not value for value in values.values()):
                    raise FreezeError(f"blank or untrimmed chart-index value at line {line_number}")
                chart_text = values["chart_number"]
                if POSITIVE_INTEGER_PATTERN.fullmatch(chart_text) is None:
                    raise FreezeError(f"invalid chart_number at index line {line_number}")
                chart_number = int(chart_text)
                blind_chart_id = values["blind_chart_id"]
                if OPAQUE_ID_PATTERN.fullmatch(blind_chart_id) is None:
                    raise FreezeError(f"invalid anonymous id at index line {line_number}")
                expected_path = f"individual_attribution_charts/{blind_chart_id}.png"
                if values["full_chart_path"] != expected_path:
                    raise FreezeError(f"individual-chart path drift at index line {line_number}")
                chart_hash = require_sha256(
                    values["full_chart_sha256"],
                    f"individual-chart hash at index line {line_number}",
                )
                outcome_bucket = values["outcome_bucket"]
                if outcome_bucket not in OUTCOME_BUCKETS:
                    raise FreezeError(f"invalid outcome bucket at index line {line_number}")
                rows.append(
                    {
                        "chart_number": chart_number,
                        "blind_chart_id": blind_chart_id,
                        "full_chart_path": expected_path,
                        "full_chart_sha256": chart_hash,
                        "outcome_bucket": outcome_bucket,
                    }
                )
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FreezeError(f"cannot read anonymous chart index: {exc}") from exc

    chart_numbers = [row["chart_number"] for row in rows]
    blind_ids = [row["blind_chart_id"] for row in rows]
    chart_paths = [row["full_chart_path"] for row in rows]
    if len(rows) != EXPECTED_EVENTS:
        raise FreezeError(f"anonymous chart index has {len(rows)} rows, expected 915")
    if chart_numbers != sorted(chart_numbers) or len(set(chart_numbers)) != EXPECTED_EVENTS:
        raise FreezeError("anonymous chart index is not unique ascending chart_number order")
    if len(set(blind_ids)) != EXPECTED_EVENTS or len(set(chart_paths)) != EXPECTED_EVENTS:
        raise FreezeError("anonymous chart id/path coverage is not unique")
    return rows, index_hash


def validate_evidence(value: Any, chart_number: int) -> str:
    evidence = require_text(value, f"chart {chart_number} evidence", 1_000)
    if "%" in evidence or re.search(r"\b(?:pct|percent|net[_ -]?return)\b", evidence, re.I):
        raise FreezeError(f"numeric-return language leaked into chart {chart_number} evidence")
    return evidence


def load_annotation_slice(
    slice_spec: tuple[str, int, int, str, str],
    index_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    slice_id, start, end, reviewer, relative_path = slice_spec
    path = repo_input(relative_path, slice_id)
    slice_hash = sha256_file(path, slice_id)
    value = strict_json(path, slice_id)
    if not isinstance(value, list):
        raise FreezeError(f"{slice_id} root must be a JSON array")
    expected_rows = index_rows[start - 1 : end]
    if len(value) != len(expected_rows):
        raise FreezeError(
            f"{slice_id} has {len(value)} rows, expected {len(expected_rows)}"
        )

    annotations: list[dict[str, Any]] = []
    for row_position, (raw, expected) in enumerate(
        zip(value, expected_rows, strict=True), start=start
    ):
        annotation = require_exact_keys(
            raw, ANNOTATION_FIELDS, f"{slice_id} row position {row_position}"
        )
        if type(annotation["chart_number"]) is not int:
            raise FreezeError(f"non-integer chart_number at {slice_id} row {row_position}")
        for field in ("chart_number", "blind_chart_id", "outcome_bucket"):
            if annotation[field] != expected[field]:
                raise FreezeError(
                    f"{slice_id} row {row_position} {field} does not match chart index"
                )
        if annotation["post_path_label"] not in POST_PATH_LABELS:
            raise FreezeError(
                f"invalid post_path_label at chart {annotation['chart_number']}"
            )
        if (annotation["outcome_bucket"] == "NO_COMPLETED_TRADE") != (
            annotation["post_path_label"] == "NO_COMPLETED_TRADE"
        ):
            raise FreezeError(
                f"NO_COMPLETED_TRADE label/bucket mismatch at chart {annotation['chart_number']}"
            )
        validate_evidence(annotation["evidence"], annotation["chart_number"])
        if annotation["reviewer"] != reviewer:
            raise FreezeError(
                f"reviewer drift in {slice_id} at chart {annotation['chart_number']}"
            )
        for field in FALSE_GOVERNANCE_FIELDS:
            if annotation[field] is not False:
                raise FreezeError(
                    f"{field} must be the JSON boolean false at chart "
                    f"{annotation['chart_number']}"
                )
        annotations.append({field: annotation[field] for field in ANNOTATION_FIELDS})

    return annotations, {
        "slice_id": slice_id,
        "row_positions": [start, end],
        "rows": len(annotations),
        "reviewer": reviewer,
        "path": relative_path,
        "sha256": slice_hash,
    }


def chart_binding_digest(index_rows: list[dict[str, Any]]) -> str:
    payload = [
        {field: row[field] for field in INDEX_FIELDS}
        for row in index_rows
    ]
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_individual_pngs(index_rows: list[dict[str, Any]]) -> str:
    for row in index_rows:
        path = INDIVIDUAL_CHART_ROOT / f"{row['blind_chart_id']}.png"
        actual = sha256_file(path, f"individual chart {row['chart_number']}")
        if actual != row["full_chart_sha256"]:
            raise FreezeError(
                f"individual PNG hash drift at chart {row['chart_number']}: "
                f"{actual} != {row['full_chart_sha256']}"
            )
    return chart_binding_digest(index_rows)


def descriptive_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "post_path_label_counts": {
            label: sum(row["post_path_label"] == label for row in rows)
            for label in POST_PATH_LABELS
        },
        "outcome_bucket_counts": {
            bucket: sum(row["outcome_bucket"] == bucket for row in rows)
            for bucket in OUTCOME_BUCKETS
        },
        "reviewer_counts": {
            reviewer: sum(row["reviewer"] == reviewer for row in rows)
            for reviewer in ("Galileo-phase2a", "Bacon-phase2a", "TemplateAudit")
        },
        "semantics": (
            "Counts are anonymous inventory checks only; no association, return, "
            "threshold, predicate, or executable rule was computed."
        ),
    }


def write_json_exclusive(path: Path, value: Any) -> None:
    encoded = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise FreezeError(f"cannot exclusively write {path}: {exc}") from exc


def fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise FreezeError(f"cannot fsync staging directory {path}: {exc}") from exc


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory while rejecting every existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename_exclusive = getattr(libc, "renamex_np", None)
    if rename_exclusive is None:
        raise FreezeError("atomic exclusive directory rename is unavailable")
    rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename_exclusive.restype = ctypes.c_int
    rename_excl = 0x00000004  # Darwin RENAME_EXCL.
    if rename_exclusive(os.fsencode(source), os.fsencode(destination), rename_excl):
        error = ctypes.get_errno()
        raise FreezeError(
            f"atomic no-overwrite publication failed: {os.strerror(error)}"
        )


def reverify_before_publish(
    index_rows: list[dict[str, Any]],
    index_hash: str,
    slice_sources: list[dict[str, Any]],
    finalizer_hash: str,
    chart_digest: str,
) -> None:
    if sha256_file(ANONYMOUS_CHART_INDEX, "anonymous chart index changed") != index_hash:
        raise FreezeError("anonymous chart index changed during finalization")
    for source in slice_sources:
        path = repo_input(source["path"], source["slice_id"])
        if sha256_file(path, f"{source['slice_id']} changed") != source["sha256"]:
            raise FreezeError(f"{source['slice_id']} changed during finalization")
    if sha256_file(Path(__file__), "finalizer", reject_symlink=False) != finalizer_hash:
        raise FreezeError("finalizer changed during execution")
    if verify_individual_pngs(index_rows) != chart_digest:
        raise FreezeError("anonymous individual-chart binding changed")


def finalize() -> dict[str, Any]:
    validate_static_contract()
    index_rows, index_hash = load_anonymous_index()

    annotations: list[dict[str, Any]] = []
    slice_sources: list[dict[str, Any]] = []
    for slice_spec in SLICE_SPECS:
        rows, source = load_annotation_slice(slice_spec, index_rows)
        annotations.extend(rows)
        slice_sources.append(source)

    if len(annotations) != EXPECTED_EVENTS:
        raise FreezeError("merged annotation ledger does not contain exactly 915 rows")
    annotation_chart_numbers = [row["chart_number"] for row in annotations]
    index_chart_numbers = [row["chart_number"] for row in index_rows]
    if annotation_chart_numbers != index_chart_numbers:
        raise FreezeError("merged annotation order does not exactly match chart index")
    if len(set(annotation_chart_numbers)) != EXPECTED_EVENTS:
        raise FreezeError("merged annotations do not cover every chart exactly once")
    if any(set(row) != set(ANNOTATION_FIELDS) for row in annotations):
        raise FreezeError("merged annotation nine-field schema drift")

    chart_digest = verify_individual_pngs(index_rows)
    finalizer_hash = sha256_file(Path(__file__), "finalizer", reject_symlink=False)

    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FreezeError(f"refusing to overwrite frozen Phase-2A output: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{OUTPUT.name}.staging-", dir=OUTPUT.parent)
    )
    try:
        ledger_path = staging / "phase2a_annotation_ledger.json"
        manifest_path = staging / "manifest.json"
        write_json_exclusive(ledger_path, annotations)
        manifest = {
            "experiment": EXPERIMENT,
            "stage": STAGE,
            "status": "FROZEN_ANONYMOUS_REVIEW_ONLY",
            "events": EXPECTED_EVENTS,
            "coverage_exactly_once": True,
            "deterministic_sort": (
                "phase2a_chart_index.csv chart_number ascending; slice row positions "
                "0001-0305, 0306-0610, and 0611-0915"
            ),
            "finalizer": {"path": FINALIZER_REL, "sha256": finalizer_hash},
            "anonymous_chart_index": {
                "path": str(ANONYMOUS_CHART_INDEX),
                "sha256": index_hash,
                "rows": EXPECTED_EVENTS,
                "columns": list(INDEX_FIELDS),
            },
            "individual_anonymous_pngs": {
                "directory": str(INDIVIDUAL_CHART_ROOT),
                "count": EXPECTED_EVENTS,
                "every_index_declared_sha256_verified": True,
                "ordered_index_binding_sha256": chart_digest,
            },
            "annotation_slices": slice_sources,
            "ledger": {
                "file": ledger_path.name,
                "sha256": sha256_file(
                    ledger_path, "staged annotation ledger", reject_symlink=False
                ),
                "rows": EXPECTED_EVENTS,
                "exact_fields": list(ANNOTATION_FIELDS),
            },
            "descriptive_inventory_counts": descriptive_counts(annotations),
            "governance": {
                "phase1_ledger_read": False,
                "stage_b_artifact_read": False,
                "identity_mapping_read": False,
                "identity_crosswalk_read": False,
                "numeric_return_read": False,
                "numeric_return_persisted": False,
                "rule_generated": False,
                "rule_aggregation_performed": False,
                "phase1_labels_modified": False,
                "signal_candle_used_for_rule": False,
                "post_signal_used_as_predictor": False,
            },
        }
        write_json_exclusive(manifest_path, manifest)
        fsync_directory(staging)

        reverify_before_publish(
            index_rows,
            index_hash,
            slice_sources,
            finalizer_hash,
            chart_digest,
        )
        if OUTPUT.exists() or OUTPUT.is_symlink():
            raise FreezeError(f"Phase-2A output appeared during construction: {OUTPUT}")
        atomic_publish_no_replace(staging, OUTPUT)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "status": "FROZEN_ANONYMOUS_REVIEW_ONLY",
        "output": str(OUTPUT),
        "events": EXPECTED_EVENTS,
        "ledger_sha256": manifest["ledger"]["sha256"],
        "manifest_sha256": sha256_file(
            OUTPUT / "manifest.json", "published manifest", reject_symlink=False
        ),
        "phase1_ledger_read": False,
        "stage_b_artifact_read": False,
        "identity_mapping_read": False,
        "numeric_return_read": False,
        "rule_generated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-static-contract", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    result = validate_static_contract() if args.verify_static_contract else finalize()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
