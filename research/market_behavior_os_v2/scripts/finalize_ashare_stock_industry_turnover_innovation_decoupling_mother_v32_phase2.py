#!/usr/bin/env python3
"""Freeze V32 Phase-2 anonymous path annotations and categorical diagnostics.

Inputs are limited to the frozen anonymous Phase-1 ledger, a public anonymous
Phase-2 chart index/placement pair, its manifest, and schema-conforming human
annotations.  No security identity, numeric return, or upstream performance
artifact has a loader in this module.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

EXPERIMENT = "ASHARE-STOCK-INDUSTRY-TURNOVER-INNOVATION-DECOUPLING-MOTHER-V32"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"
SCHEMA = EXP / "ASHARE-V32_phase2_post_path_annotation_schema.json"
PHASE1_DRIFT_FREEZE = EXP / "ASHARE-V32_phase1_reviewer_drift_freeze.json"

OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_stock_industry_turnover_innovation_decoupling_mother_v32"
)
PHASE1_ROOT = OUTPUT_ROOT / "stage_d_phase1_anonymous_review"
PHASE1_LEDGER = PHASE1_ROOT / "phase1_annotation_ledger.csv"
PHASE1_MANIFEST = PHASE1_ROOT / "manifest.json"
OUTPUT = OUTPUT_ROOT / "stage_f_phase2_review_frozen"

EXPECTED_EVENTS = 1_781
MIN_SUPPORT_PER_SIDE = 25
MAX_EVIDENCE_CHARS = 240
MAX_REVIEWER_CHARS = 80
EXPECTED_SCHEMA_SHA256 = "f4aaade524dac4a85a79f4b8fda03c00451267e915b4c77973b0110539eda603"
EXPECTED_PHASE1_LEDGER_SHA256 = (
    "1835c4d0eec87a736e9f9f639ea6aafa281aef0f0ee96a2ddd0de8a0c4b29140"
)
EXPECTED_PHASE1_MANIFEST_SHA256 = (
    "bd820935d8b1f492896364d7da9b7de1c9543bf5ef08add5b68c6c145ac02bee"
)
EXPECTED_DRIFT_FREEZE_SHA256 = (
    "9b1dadba17f1ae1b219a887e29bced13a0ddc304a2ebe40eb954ccd5e39d3850"
)

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
BLIND_ID_PATTERN = re.compile(r"B-[0-9a-f]{20}")

LABELS = (
    "BASE_COMPRESSION",
    "ORDERLY_PRICE_DISCOVERY",
    "HIGH_TURNOVER_LOW_PRICE_DISPLACEMENT",
    "MATURE_EXTENSION_OR_TERMINAL_SPIKE",
    "DOWNTREND_OR_BREAKDOWN",
)
ANALYSIS_LABELS = (*LABELS, "NONE_CLEAR")
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

PHASE1_LEDGER_FIELDS = (
    "chart_number",
    "blind_chart_id",
    "blind_chart_path",
    "blind_chart_sha256",
    "sheet_number",
    "slot",
    *LABELS,
    "NONE_CLEAR",
    "evidence",
    "reviewer",
)
PHASE2_INDEX_FIELDS = (
    "chart_number",
    "blind_chart_id",
    "full_chart_path",
    "full_chart_sha256",
    "outcome_bucket",
)
PLACEMENT_FIELDS = (
    "outcome_bucket",
    "sheet_path",
    "sheet_number",
    "slot",
    "chart_number",
    "blind_chart_id",
)
SHEET_INDEX_FIELDS = (
    "outcome_bucket",
    "sheet_path",
    "sheet_number",
    "charts",
    "first_chart",
    "last_chart",
    "sheet_sha256",
)
ANNOTATION_FIELDS = (
    "chart_number",
    "blind_chart_id",
    "outcome_bucket",
    "post_path_label",
    "evidence",
    "reviewer",
    "phase1_labels_modified",
    "post_signal_used_as_predictor",
)
MERGED_LEDGER_FIELDS = (
    "chart_number",
    "blind_chart_id",
    *LABELS,
    "NONE_CLEAR",
    "phase1_evidence",
    "phase1_reviewer",
    "outcome_bucket",
    "post_path_label",
    "phase2_evidence",
    "phase2_reviewer",
    "phase1_labels_modified",
    "post_signal_used_as_predictor",
)
DIAGNOSTIC_FIELDS = (
    "label",
    "phase1_reviewer",
    "pre_outcome_usage_decision",
    "true_n",
    "false_n",
    "minimum_support_per_side",
    "eligible_each_side_ge_25",
    "profit_ge4_true_n",
    "profit_ge4_false_n",
    "profit_ge4_true_rate",
    "profit_ge4_false_rate",
    "profit_ge4_delta_true_minus_false",
    "severe_loss_true_n",
    "severe_loss_false_n",
    "severe_loss_true_rate",
    "severe_loss_false_rate",
    "severe_loss_delta_true_minus_false",
)

MANIFEST_BOOLEAN_CONTRACT = {
    "anonymous_identity_coverage_exactly_once": True,
    "outcome_group_coverage_exactly_once": True,
    "phase1_labels_modified": False,
    "post_signal_used_as_predictor": False,
    "rule_aggregation_performed": False,
    "portfolio_replay_performed": False,
    "post_2020_row_read": False,
}
MANIFEST_HASH_FIELDS = (
    "phase2_chart_index_sha256",
    "outcome_sheet_placements_sha256",
    "outcome_sheet_index_sha256",
    "phase2_review_template_sha256",
    "phase1_annotation_ledger_sha256",
    "phase1_annotation_manifest_sha256",
    "phase1_reviewer_drift_freeze_sha256",
    "phase2_annotation_schema_sha256",
)


class FreezeError(RuntimeError):
    """Fail closed on anonymous-input, annotation, or publication drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise FreezeError(f"{label} is not one lowercase SHA-256 digest")
    return value


def verify_hash(path: Path, expected: str, label: str) -> str:
    expected = require_sha256(expected, f"expected {label} hash")
    if not path.is_file():
        raise FreezeError(f"missing {label}: {path}")
    actual = sha256(path)
    if actual != expected:
        raise FreezeError(f"{label} hash drift: {actual} != {expected}")
    return actual


def strict_json(path: Path, label: str) -> Any:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise FreezeError(f"duplicate JSON keys in {label}: {duplicates}")
        return dict(pairs)

    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read {label} {path}: {exc}") from exc


def parse_positive_integer(value: Any, label: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise FreezeError(f"{label} is not a canonical positive integer: {value!r}")
    return int(value)


def parse_csv_boolean(value: Any, label: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise FreezeError(f"{label} must be exactly true or false")


def require_blind_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or BLIND_ID_PATTERN.fullmatch(value) is None:
        raise FreezeError(f"{label} is not an opaque V32 blind chart ID")
    return value


def require_short_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise FreezeError(f"{label} must be a string")
    if value != value.strip() or not value or len(value) > maximum:
        raise FreezeError(f"{label} must be nonempty, trimmed, and <= {maximum} characters")
    if "\n" in value or "\r" in value or any(ord(character) < 32 for character in value):
        raise FreezeError(f"{label} must be one printable line")
    return value


def require_relative_path(value: Any, label: str, suffix: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value or "\\" in value:
        raise FreezeError(f"{label} is not a canonical relative POSIX path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts or parsed.suffix.lower() != suffix:
        raise FreezeError(f"{label} is not a safe relative {suffix} path")
    return value


def resolve_corpus_file(root: Path, relative: str, label: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FreezeError(f"{label} resolves outside the Phase-2 corpus") from exc
    if not candidate.is_file():
        raise FreezeError(f"missing {label}: {candidate}")
    return candidate


def read_exact_csv(
    path: Path, expected_fields: tuple[str, ...], label: str
) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != expected_fields:
                raise FreezeError(
                    f"{label} columns must be exactly and in order {expected_fields}"
                )
            rows: list[dict[str, str]] = []
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    raise FreezeError(f"malformed {label} row at line {line_number}")
                rows.append(row)
            return rows
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FreezeError(f"cannot read {label} {path}: {exc}") from exc


def require_exact_coverage(rows: list[dict[str, Any]], label: str) -> None:
    numbers = [int(row["chart_number"]) for row in rows]
    blind_ids = [str(row["blind_chart_id"]) for row in rows]
    if len(rows) != EXPECTED_EVENTS or sorted(numbers) != list(range(1, EXPECTED_EVENTS + 1)):
        raise FreezeError(f"{label} chart coverage is not exactly 1..1781")
    if len(set(blind_ids)) != EXPECTED_EVENTS:
        raise FreezeError(f"{label} blind_chart_id coverage is not exactly once")


def load_phase1_anchors() -> tuple[list[dict[str, Any]], dict[str, str]]:
    hashes = {
        "phase1_annotation_ledger": verify_hash(
            PHASE1_LEDGER, EXPECTED_PHASE1_LEDGER_SHA256, "Phase-1 ledger"
        ),
        "phase1_manifest": verify_hash(
            PHASE1_MANIFEST, EXPECTED_PHASE1_MANIFEST_SHA256, "Phase-1 manifest"
        ),
        "phase1_reviewer_drift_freeze": verify_hash(
            PHASE1_DRIFT_FREEZE,
            EXPECTED_DRIFT_FREEZE_SHA256,
            "Phase-1 reviewer-drift freeze",
        ),
        "phase2_annotation_schema": verify_hash(
            SCHEMA, EXPECTED_SCHEMA_SHA256, "Phase-2 annotation schema"
        ),
    }

    manifest = strict_json(PHASE1_MANIFEST, "Phase-1 manifest")
    if (
        not isinstance(manifest, dict)
        or manifest.get("experiment") != EXPERIMENT
        or manifest.get("events") != EXPECTED_EVENTS
        or manifest.get("coverage_exactly_once") is not True
        or manifest.get("ledger_sha256") != EXPECTED_PHASE1_LEDGER_SHA256
        or manifest.get("outcomes_read") is not False
        or manifest.get("returns_aggregated") is not False
        or manifest.get("post_signal_used_as_predictor") is not False
    ):
        raise FreezeError("Phase-1 manifest semantic contract drift")

    drift = strict_json(PHASE1_DRIFT_FREEZE, "Phase-1 reviewer-drift freeze")
    decisions = drift.get("pre_outcome_usage_decisions", {}) if isinstance(drift, dict) else {}
    expected_decisions = {
        "BASE_COMPRESSION": "POOLED_UNUSABLE",
        "HIGH_TURNOVER_LOW_PRICE_DISPLACEMENT": "POOLED_UNUSABLE",
        "NONE_CLEAR": "DESCRIPTIVE_ONLY",
        "ORDERLY_PRICE_DISCOVERY": "ELIGIBLE_WITH_REVIEWER_GUARDS",
        "MATURE_EXTENSION_OR_TERMINAL_SPIKE": "ELIGIBLE_WITH_REVIEWER_GUARDS",
        "DOWNTREND_OR_BREAKDOWN": "ELIGIBLE_WITH_REVIEWER_GUARDS",
    }
    if (
        not isinstance(drift, dict)
        or drift.get("experiment") != EXPERIMENT
        or drift.get("decision_locked_before_outcome_attachment") is not True
        or drift.get("inputs", {}).get("phase1_annotation_ledger", {}).get("sha256")
        != EXPECTED_PHASE1_LEDGER_SHA256
        or drift.get("inputs", {}).get("phase1_manifest", {}).get("sha256")
        != EXPECTED_PHASE1_MANIFEST_SHA256
        or {
            label: decisions.get(label, {}).get("decision")
            for label in ANALYSIS_LABELS
        }
        != expected_decisions
    ):
        raise FreezeError("Phase-1 reviewer-drift decision contract drift")
    for label in (
        "ORDERLY_PRICE_DISCOVERY",
        "MATURE_EXTENSION_OR_TERMINAL_SPIKE",
        "DOWNTREND_OR_BREAKDOWN",
    ):
        if decisions[label].get("required_guards") != [
            "REVIEWER_STRATIFIED_AGGREGATION",
            "WITHIN_REVIEWER_DIRECTION_CONSISTENCY",
        ]:
            raise FreezeError(f"reviewer guard drift for {label}")

    raw_rows = read_exact_csv(PHASE1_LEDGER, PHASE1_LEDGER_FIELDS, "Phase-1 ledger")
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(raw_rows, start=2):
        chart_number = parse_positive_integer(
            raw["chart_number"], f"Phase-1 line {line_number} chart_number"
        )
        blind_id = require_blind_id(
            raw["blind_chart_id"], f"Phase-1 line {line_number} blind_chart_id"
        )
        labels = {
            label: parse_csv_boolean(raw[label], f"Phase-1 line {line_number} {label}")
            for label in ANALYSIS_LABELS
        }
        if labels["NONE_CLEAR"] is not (not any(labels[label] for label in LABELS)):
            raise FreezeError(f"Phase-1 NONE_CLEAR derivation drift at chart {chart_number}")
        rows.append(
            {
                "chart_number": chart_number,
                "blind_chart_id": blind_id,
                **labels,
                "phase1_evidence": require_short_text(
                    raw["evidence"], f"Phase-1 line {line_number} evidence", MAX_EVIDENCE_CHARS
                ),
                "phase1_reviewer": require_short_text(
                    raw["reviewer"], f"Phase-1 line {line_number} reviewer", MAX_REVIEWER_CHARS
                ),
            }
        )
    require_exact_coverage(rows, "Phase-1 ledger")
    return sorted(rows, key=lambda row: row["chart_number"]), hashes


def validate_phase2_manifest(
    path: Path,
    expected_hash: str,
    index_hash: str,
    placements_hash: str,
) -> tuple[dict[str, Any], str]:
    actual_hash = verify_hash(path, expected_hash, "Phase-2 manifest")
    manifest = strict_json(path, "Phase-2 manifest")
    if not isinstance(manifest, dict):
        raise FreezeError("Phase-2 manifest must be one JSON object")
    if manifest.get("experiment") != EXPERIMENT or manifest.get("events") != EXPECTED_EVENTS:
        raise FreezeError("Phase-2 manifest experiment/event contract drift")
    for key, expected in MANIFEST_BOOLEAN_CONTRACT.items():
        if manifest.get(key) is not expected:
            raise FreezeError(f"Phase-2 manifest semantic drift: {key}")
    for key in MANIFEST_HASH_FIELDS:
        require_sha256(manifest.get(key), f"Phase-2 manifest {key}")
    expected_manifest_hashes = {
        "phase2_chart_index_sha256": index_hash,
        "outcome_sheet_placements_sha256": placements_hash,
        "phase1_annotation_ledger_sha256": EXPECTED_PHASE1_LEDGER_SHA256,
        "phase1_annotation_manifest_sha256": EXPECTED_PHASE1_MANIFEST_SHA256,
        "phase1_reviewer_drift_freeze_sha256": EXPECTED_DRIFT_FREEZE_SHA256,
        "phase2_annotation_schema_sha256": EXPECTED_SCHEMA_SHA256,
    }
    for key, expected in expected_manifest_hashes.items():
        if manifest.get(key) != expected:
            raise FreezeError(f"Phase-2 manifest hash binding drift: {key}")
    return manifest, actual_hash


def load_phase2_index(path: Path, expected_hash: str) -> tuple[list[dict[str, Any]], str]:
    if path.name != "phase2_chart_index.csv":
        raise FreezeError("Phase-2 index input must be named phase2_chart_index.csv")
    actual_hash = verify_hash(path, expected_hash, "Phase-2 chart index")
    raw_rows = read_exact_csv(path, PHASE2_INDEX_FIELDS, "Phase-2 chart index")
    rows: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for line_number, raw in enumerate(raw_rows, start=2):
        chart_number = parse_positive_integer(
            raw["chart_number"], f"Phase-2 index line {line_number} chart_number"
        )
        blind_id = require_blind_id(
            raw["blind_chart_id"], f"Phase-2 index line {line_number} blind_chart_id"
        )
        chart_path = require_relative_path(
            raw["full_chart_path"], f"Phase-2 index line {line_number} full_chart_path", ".png"
        )
        if chart_path in seen_paths:
            raise FreezeError(f"duplicate Phase-2 chart path at line {line_number}")
        seen_paths.add(chart_path)
        bucket = raw["outcome_bucket"]
        if bucket not in OUTCOME_BUCKETS:
            raise FreezeError(f"invalid outcome bucket at Phase-2 index line {line_number}")
        rows.append(
            {
                "chart_number": chart_number,
                "blind_chart_id": blind_id,
                "outcome_bucket": bucket,
                "full_chart_path": chart_path,
                "full_chart_sha256": require_sha256(
                    raw["full_chart_sha256"],
                    f"Phase-2 index line {line_number} full_chart_sha256",
                ),
            }
        )
    require_exact_coverage(rows, "Phase-2 chart index")
    return sorted(rows, key=lambda row: row["chart_number"]), actual_hash


def validate_full_chart_files(
    corpus_root: Path, index_rows: list[dict[str, Any]]
) -> dict[Path, str]:
    hashes: dict[Path, str] = {}
    for row in index_rows:
        chart_number = row["chart_number"]
        chart_path = resolve_corpus_file(
            corpus_root,
            row["full_chart_path"],
            f"Phase-2 full chart for chart_number {chart_number}",
        )
        expected = row["full_chart_sha256"]
        actual = sha256(chart_path)
        if actual != expected:
            raise FreezeError(
                f"Phase-2 full-chart hash drift at chart_number {chart_number}: "
                f"{actual} != {expected}"
            )
        hashes[chart_path] = actual
    if len(hashes) != EXPECTED_EVENTS:
        raise FreezeError("Phase-2 full-chart file coverage is not exactly once")
    return hashes


def load_placements(
    path: Path,
    expected_hash: str,
    index_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    if path.name != "outcome_sheet_placements.csv":
        raise FreezeError("placement input must be named outcome_sheet_placements.csv")
    actual_hash = verify_hash(path, expected_hash, "Phase-2 outcome-sheet placements")
    raw_rows = read_exact_csv(path, PLACEMENT_FIELDS, "Phase-2 outcome-sheet placements")
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(raw_rows, start=2):
        bucket = raw["outcome_bucket"]
        if bucket not in OUTCOME_BUCKETS:
            raise FreezeError(f"invalid placement outcome bucket at line {line_number}")
        rows.append(
            {
                "outcome_bucket": bucket,
                "sheet_path": require_relative_path(
                    raw["sheet_path"], f"placement line {line_number} sheet_path", ".jpg"
                ),
                "sheet_number": parse_positive_integer(
                    raw["sheet_number"], f"placement line {line_number} sheet_number"
                ),
                "slot": parse_positive_integer(
                    raw["slot"], f"placement line {line_number} slot"
                ),
                "chart_number": parse_positive_integer(
                    raw["chart_number"], f"placement line {line_number} chart_number"
                ),
                "blind_chart_id": require_blind_id(
                    raw["blind_chart_id"], f"placement line {line_number} blind_chart_id"
                ),
            }
        )
    require_exact_coverage(rows, "Phase-2 placements")

    expected = {
        (row["chart_number"], row["blind_chart_id"]): row["outcome_bucket"]
        for row in index_rows
    }
    observed = {
        (row["chart_number"], row["blind_chart_id"]): row["outcome_bucket"]
        for row in rows
    }
    if observed != expected:
        raise FreezeError("placement identities/buckets do not equal the Phase-2 index")

    pages: dict[tuple[str, int], list[dict[str, Any]]] = {}
    path_to_page: dict[str, tuple[str, int]] = {}
    for row in rows:
        page_key = (row["outcome_bucket"], row["sheet_number"])
        pages.setdefault(page_key, []).append(row)
        prior = path_to_page.setdefault(row["sheet_path"], page_key)
        if prior != page_key:
            raise FreezeError("one sheet path maps to multiple bucket/pages")
    for page_key, page_rows in pages.items():
        paths = {row["sheet_path"] for row in page_rows}
        slots = sorted(row["slot"] for row in page_rows)
        if len(paths) != 1 or not 1 <= len(page_rows) <= 25:
            raise FreezeError(f"invalid placement page shape: {page_key}")
        if slots != list(range(1, len(page_rows) + 1)):
            raise FreezeError(f"noncontiguous placement slots: {page_key}")
    return sorted(rows, key=lambda row: row["chart_number"]), actual_hash


def load_and_validate_sheet_index(
    corpus_root: Path,
    expected_hash: str,
    placements: list[dict[str, Any]],
    phase2_manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], Path, str, dict[Path, str]]:
    sheet_index_path = resolve_corpus_file(
        corpus_root,
        "outcome_sheet_index.csv",
        "Phase-2 outcome-sheet index",
    )
    actual_index_hash = verify_hash(
        sheet_index_path,
        expected_hash,
        "Phase-2 outcome-sheet index",
    )
    raw_rows = read_exact_csv(
        sheet_index_path, SHEET_INDEX_FIELDS, "Phase-2 outcome-sheet index"
    )
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(raw_rows, start=2):
        bucket = raw["outcome_bucket"]
        if bucket not in OUTCOME_BUCKETS:
            raise FreezeError(f"invalid sheet-index outcome bucket at line {line_number}")
        charts = parse_positive_integer(raw["charts"], f"sheet-index line {line_number} charts")
        if charts > 25:
            raise FreezeError(f"sheet-index chart count exceeds 25 at line {line_number}")
        rows.append(
            {
                "outcome_bucket": bucket,
                "sheet_path": require_relative_path(
                    raw["sheet_path"], f"sheet-index line {line_number} sheet_path", ".jpg"
                ),
                "sheet_number": parse_positive_integer(
                    raw["sheet_number"], f"sheet-index line {line_number} sheet_number"
                ),
                "charts": charts,
                "first_chart": parse_positive_integer(
                    raw["first_chart"], f"sheet-index line {line_number} first_chart"
                ),
                "last_chart": parse_positive_integer(
                    raw["last_chart"], f"sheet-index line {line_number} last_chart"
                ),
                "sheet_sha256": require_sha256(
                    raw["sheet_sha256"], f"sheet-index line {line_number} sheet_sha256"
                ),
            }
        )

    placement_pages: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for placement in placements:
        key = (placement["outcome_bucket"], placement["sheet_path"])
        placement_pages.setdefault(key, []).append(placement)
    indexed_pages = {(row["outcome_bucket"], row["sheet_path"]): row for row in rows}
    if len(indexed_pages) != len(rows) or set(indexed_pages) != set(placement_pages):
        raise FreezeError("sheet-index pages do not exactly equal placement pages")

    page_keys = {(row["outcome_bucket"], row["sheet_number"]) for row in rows}
    if len(page_keys) != len(rows):
        raise FreezeError("duplicate outcome-bucket/sheet-number in sheet index")
    sheet_hashes: dict[Path, str] = {}
    for key, row in indexed_pages.items():
        page = placement_pages[key]
        page_sheet_numbers = {item["sheet_number"] for item in page}
        if page_sheet_numbers != {row["sheet_number"]}:
            raise FreezeError(f"placement/sheet-index page-number drift: {key}")
        if (
            len(page) != row["charts"]
            or min(item["chart_number"] for item in page) != row["first_chart"]
            or max(item["chart_number"] for item in page) != row["last_chart"]
        ):
            raise FreezeError(f"placement/sheet-index chart coverage drift: {key}")
        sheet_path = resolve_corpus_file(
            corpus_root, row["sheet_path"], f"Phase-2 outcome sheet {key}"
        )
        actual = sha256(sheet_path)
        if actual != row["sheet_sha256"]:
            raise FreezeError(
                f"Phase-2 outcome-sheet hash drift for {key}: "
                f"{actual} != {row['sheet_sha256']}"
            )
        sheet_hashes[sheet_path] = actual
    if len(sheet_hashes) != len(rows):
        raise FreezeError("Phase-2 sheet files are not unique")

    manifest_sheet_count = phase2_manifest.get("outcome_contact_sheets")
    manifest_page_counts = phase2_manifest.get("outcome_bucket_page_counts")
    observed_page_counts = {
        bucket: sum(row["outcome_bucket"] == bucket for row in rows)
        for bucket in OUTCOME_BUCKETS
    }
    if manifest_sheet_count != len(rows) or manifest_page_counts != observed_page_counts:
        raise FreezeError("Phase-2 manifest/sheet-index page-count drift")
    return rows, sheet_index_path, actual_index_hash, sheet_hashes


def validate_cross_input_identity(
    phase1_rows: list[dict[str, Any]], index_rows: list[dict[str, Any]]
) -> None:
    phase1_keys = [
        (row["chart_number"], row["blind_chart_id"]) for row in phase1_rows
    ]
    phase2_keys = [
        (row["chart_number"], row["blind_chart_id"]) for row in index_rows
    ]
    if phase1_keys != phase2_keys:
        raise FreezeError("Phase-2 anonymous keys do not exactly equal frozen Phase-1 keys")


def load_annotations(
    paths: list[Path], index_rows: list[dict[str, Any]]
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    if not paths:
        raise FreezeError("at least one Phase-2 annotation JSON is required")
    resolved = [path.resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise FreezeError("the same Phase-2 annotation file was supplied more than once")
    index_by_number = {row["chart_number"]: row for row in index_rows}
    annotations: dict[int, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for path in sorted(paths, key=lambda item: str(item.resolve())):
        if not path.is_file() or path.suffix.lower() != ".json":
            raise FreezeError(f"annotation input is not one JSON file: {path}")
        source_hash = sha256(path)
        raw = strict_json(path, "Phase-2 annotation")
        if not isinstance(raw, list) or not raw:
            raise FreezeError(f"annotation file must be one nonempty JSON array: {path}")
        for position, item in enumerate(raw, start=1):
            if not isinstance(item, dict) or set(item) != set(ANNOTATION_FIELDS):
                raise FreezeError(
                    f"annotation {path}:{position} fields must be exactly {ANNOTATION_FIELDS}"
                )
            chart_number = item["chart_number"]
            if type(chart_number) is not int or not 1 <= chart_number <= EXPECTED_EVENTS:
                raise FreezeError(f"invalid chart_number at {path}:{position}")
            if chart_number in annotations:
                raise FreezeError(f"chart_number {chart_number} was annotated more than once")
            blind_id = require_blind_id(
                item["blind_chart_id"], f"annotation {path}:{position} blind_chart_id"
            )
            bucket = item["outcome_bucket"]
            if bucket not in OUTCOME_BUCKETS:
                raise FreezeError(f"invalid outcome_bucket at {path}:{position}")
            post_path_label = item["post_path_label"]
            if post_path_label not in POST_PATH_LABELS:
                raise FreezeError(f"invalid post_path_label at {path}:{position}")
            if item["phase1_labels_modified"] is not False:
                raise FreezeError(f"Phase-1 labels were marked modified at {path}:{position}")
            if item["post_signal_used_as_predictor"] is not False:
                raise FreezeError(f"post-signal predictor use at {path}:{position}")
            expected = index_by_number[chart_number]
            if blind_id != expected["blind_chart_id"] or bucket != expected["outcome_bucket"]:
                raise FreezeError(f"annotation/index identity or bucket drift at {path}:{position}")
            if (bucket == "NO_COMPLETED_TRADE") != (
                post_path_label == "NO_COMPLETED_TRADE"
            ):
                raise FreezeError(
                    f"NO_COMPLETED_TRADE bucket/path-label mismatch at {path}:{position}"
                )
            annotations[chart_number] = {
                "chart_number": chart_number,
                "blind_chart_id": blind_id,
                "outcome_bucket": bucket,
                "post_path_label": post_path_label,
                "phase2_evidence": require_short_text(
                    item["evidence"], f"annotation {path}:{position} evidence", MAX_EVIDENCE_CHARS
                ),
                "phase2_reviewer": require_short_text(
                    item["reviewer"], f"annotation {path}:{position} reviewer", MAX_REVIEWER_CHARS
                ),
                "phase1_labels_modified": False,
                "post_signal_used_as_predictor": False,
            }
        sources.append(
            {"path": str(path.resolve()), "sha256": source_hash, "rows": len(raw)}
        )
    if set(annotations) != set(range(1, EXPECTED_EVENTS + 1)):
        missing = sorted(set(range(1, EXPECTED_EVENTS + 1)) - set(annotations))
        raise FreezeError(
            "Phase-2 annotation coverage is not exactly 1..1781; "
            f"missing={missing[:20]}"
        )
    return annotations, sources


def merge_ledgers(
    phase1_rows: list[dict[str, Any]], annotations: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase1 in phase1_rows:
        phase2 = annotations[phase1["chart_number"]]
        rows.append(
            {
                "chart_number": phase1["chart_number"],
                "blind_chart_id": phase1["blind_chart_id"],
                **{label: phase1[label] for label in ANALYSIS_LABELS},
                "phase1_evidence": phase1["phase1_evidence"],
                "phase1_reviewer": phase1["phase1_reviewer"],
                "outcome_bucket": phase2["outcome_bucket"],
                "post_path_label": phase2["post_path_label"],
                "phase2_evidence": phase2["phase2_evidence"],
                "phase2_reviewer": phase2["phase2_reviewer"],
                "phase1_labels_modified": False,
                "post_signal_used_as_predictor": False,
            }
        )
    require_exact_coverage(rows, "merged anonymous ledger")
    return rows


def safe_rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def rate_text(value: float | None) -> str:
    return "" if value is None else f"{value:.12f}"


def build_diagnostics(
    ledger: list[dict[str, Any]], usage_decisions: dict[str, str]
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    reviewers = sorted({str(row["phase1_reviewer"]) for row in ledger})
    for label in ANALYSIS_LABELS:
        for reviewer in reviewers:
            block = [
                row
                for row in ledger
                if row["phase1_reviewer"] == reviewer
                and row["outcome_bucket"] != "NO_COMPLETED_TRADE"
            ]
            true_rows = [row for row in block if row[label]]
            false_rows = [row for row in block if not row[label]]
            true_n, false_n = len(true_rows), len(false_rows)
            profit_true = sum(row["outcome_bucket"] == "PROFIT_GE_4PCT" for row in true_rows)
            profit_false = sum(row["outcome_bucket"] == "PROFIT_GE_4PCT" for row in false_rows)
            severe_true = sum(row["outcome_bucket"] == "SEVERE_LOSS" for row in true_rows)
            severe_false = sum(row["outcome_bucket"] == "SEVERE_LOSS" for row in false_rows)
            profit_true_rate = safe_rate(profit_true, true_n)
            profit_false_rate = safe_rate(profit_false, false_n)
            severe_true_rate = safe_rate(severe_true, true_n)
            severe_false_rate = safe_rate(severe_false, false_n)
            diagnostics.append(
                {
                    "label": label,
                    "phase1_reviewer": reviewer,
                    "pre_outcome_usage_decision": usage_decisions[label],
                    "true_n": true_n,
                    "false_n": false_n,
                    "minimum_support_per_side": MIN_SUPPORT_PER_SIDE,
                    "eligible_each_side_ge_25": (
                        true_n >= MIN_SUPPORT_PER_SIDE and false_n >= MIN_SUPPORT_PER_SIDE
                    ),
                    "profit_ge4_true_n": profit_true,
                    "profit_ge4_false_n": profit_false,
                    "profit_ge4_true_rate": profit_true_rate,
                    "profit_ge4_false_rate": profit_false_rate,
                    "profit_ge4_delta_true_minus_false": (
                        None
                        if profit_true_rate is None or profit_false_rate is None
                        else profit_true_rate - profit_false_rate
                    ),
                    "severe_loss_true_n": severe_true,
                    "severe_loss_false_n": severe_false,
                    "severe_loss_true_rate": severe_true_rate,
                    "severe_loss_false_rate": severe_false_rate,
                    "severe_loss_delta_true_minus_false": (
                        None
                        if severe_true_rate is None or severe_false_rate is None
                        else severe_true_rate - severe_false_rate
                    ),
                }
            )
    return diagnostics


def write_csv(rows: list[dict[str, Any]], fields: tuple[str, ...], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            serialized: dict[str, Any] = {}
            for field in fields:
                value = row[field]
                if isinstance(value, bool):
                    serialized[field] = "true" if value else "false"
                elif field.endswith("_rate") or "_delta_" in field:
                    serialized[field] = rate_text(value)
                else:
                    serialized[field] = value
            writer.writerow(serialized)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def verify_unchanged(input_hashes: dict[Path, str]) -> None:
    for path, expected in input_hashes.items():
        if sha256(path) != expected:
            raise FreezeError(f"input changed during finalization: {path}")


def finalize(
    phase2_manifest_path: Path,
    expected_phase2_manifest_sha256: str,
    phase2_index_path: Path,
    expected_phase2_index_sha256: str,
    placements_path: Path,
    expected_placements_sha256: str,
    annotation_paths: list[Path],
) -> dict[str, Any]:
    if OUTPUT.exists():
        raise FreezeError(f"refusing to overwrite frozen Phase-2 output: {OUTPUT}")
    phase1_rows, fixed_hashes = load_phase1_anchors()
    corpus_root = phase2_manifest_path.parent.resolve()
    if phase2_index_path.resolve() != (corpus_root / "phase2_chart_index.csv").resolve():
        raise FreezeError("Phase-2 chart index is not the manifest-sibling canonical file")
    if placements_path.resolve() != (
        corpus_root / "outcome_sheet_placements.csv"
    ).resolve():
        raise FreezeError("Phase-2 placements are not the manifest-sibling canonical file")
    index_rows, index_hash = load_phase2_index(
        phase2_index_path, expected_phase2_index_sha256
    )
    placements, placements_hash = load_placements(
        placements_path, expected_placements_sha256, index_rows
    )
    phase2_manifest, manifest_hash = validate_phase2_manifest(
        phase2_manifest_path,
        expected_phase2_manifest_sha256,
        index_hash,
        placements_hash,
    )
    observed_bucket_counts = {
        bucket: sum(row["outcome_bucket"] == bucket for row in index_rows)
        for bucket in OUTCOME_BUCKETS
    }
    if (
        phase2_manifest.get("individual_full_charts") != EXPECTED_EVENTS
        or phase2_manifest.get("outcome_bucket_counts_discovered_after_authorized_read")
        != observed_bucket_counts
    ):
        raise FreezeError("Phase-2 manifest/chart-index count drift")
    chart_hashes = validate_full_chart_files(corpus_root, index_rows)
    sheet_rows, sheet_index_path, sheet_index_hash, sheet_hashes = (
        load_and_validate_sheet_index(
            corpus_root,
            phase2_manifest["outcome_sheet_index_sha256"],
            placements,
            phase2_manifest,
        )
    )
    del placements, sheet_rows  # Validation-only inputs are not published.
    validate_cross_input_identity(phase1_rows, index_rows)
    annotations, annotation_sources = load_annotations(annotation_paths, index_rows)
    ledger = merge_ledgers(phase1_rows, annotations)

    drift = strict_json(PHASE1_DRIFT_FREEZE, "Phase-1 reviewer-drift freeze")
    usage_decisions = {
        label: drift["pre_outcome_usage_decisions"][label]["decision"]
        for label in ANALYSIS_LABELS
    }
    diagnostics = build_diagnostics(ledger, usage_decisions)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v32_phase2_review.staging.", dir=OUTPUT.parent))
    try:
        ledger_path = staging / "phase2_merged_anonymous_ledger.csv"
        diagnostics_path = staging / "phase1_label_x_outcome_by_reviewer_block.csv"
        summary_path = staging / "summary.json"
        manifest_path = staging / "manifest.json"

        write_csv(ledger, MERGED_LEDGER_FIELDS, ledger_path)
        write_csv(diagnostics, DIAGNOSTIC_FIELDS, diagnostics_path)
        summary = {
            "experiment": EXPERIMENT,
            "stage": "STAGE_F_PHASE2_ANONYMOUS_REVIEW_FROZEN",
            "events": EXPECTED_EVENTS,
            "anonymous_coverage_exactly_once": True,
            "outcome_bucket_counts": {
                bucket: sum(row["outcome_bucket"] == bucket for row in ledger)
                for bucket in OUTCOME_BUCKETS
            },
            "post_path_label_counts": {
                label: sum(row["post_path_label"] == label for row in ledger)
                for label in POST_PATH_LABELS
            },
            "phase1_reviewer_counts": dict(
                sorted(Counter(row["phase1_reviewer"] for row in ledger).items())
            ),
            "phase2_reviewer_counts": dict(
                sorted(Counter(row["phase2_reviewer"] for row in ledger).items())
            ),
            "analysis_labels": list(ANALYSIS_LABELS),
            "pre_outcome_usage_decisions": usage_decisions,
            "reviewer_stratified_only": True,
            "minimum_support_per_true_false_side": MIN_SUPPORT_PER_SIDE,
            "diagnostic_rows": len(diagnostics),
            "diagnostic_eligible_rows": sum(
                row["eligible_each_side_ge_25"] for row in diagnostics
            ),
            "full_chart_files_hash_verified": len(chart_hashes),
            "outcome_sheet_files_hash_verified": len(sheet_hashes),
            "categorical_endpoints_only": ["PROFIT_GE_4PCT", "SEVERE_LOSS"],
            "phase1_labels_modified": False,
            "post_signal_used_as_predictor": False,
            "security_identity_read_or_published": False,
            "numeric_return_field_read_or_aggregated": False,
            "rule_promotion_or_search_performed": False,
            "portfolio_replay_performed": False,
        }
        write_json(summary_path, summary)

        output_hashes = {
            ledger_path.name: sha256(ledger_path),
            diagnostics_path.name: sha256(diagnostics_path),
            summary_path.name: sha256(summary_path),
        }
        publication_manifest = {
            "experiment": EXPERIMENT,
            "stage": "STAGE_F_PHASE2_ANONYMOUS_REVIEW_FROZEN",
            "events": EXPECTED_EVENTS,
            "inputs": {
                "phase2_manifest": {
                    "path": str(phase2_manifest_path.resolve()),
                    "sha256": manifest_hash,
                },
                "phase2_chart_index": {
                    "path": str(phase2_index_path.resolve()),
                    "sha256": index_hash,
                },
                "outcome_sheet_placements": {
                    "path": str(placements_path.resolve()),
                    "sha256": placements_hash,
                },
                "outcome_sheet_index": {
                    "path": str(sheet_index_path.resolve()),
                    "sha256": sheet_index_hash,
                },
                "phase1_annotation_ledger": {
                    "path": str(PHASE1_LEDGER.resolve()),
                    "sha256": EXPECTED_PHASE1_LEDGER_SHA256,
                },
                "phase1_manifest": {
                    "path": str(PHASE1_MANIFEST.resolve()),
                    "sha256": EXPECTED_PHASE1_MANIFEST_SHA256,
                },
                "phase1_reviewer_drift_freeze": {
                    "path": str(PHASE1_DRIFT_FREEZE.resolve()),
                    "sha256": EXPECTED_DRIFT_FREEZE_SHA256,
                },
                "phase2_annotation_schema": {
                    "path": str(SCHEMA.resolve()),
                    "sha256": EXPECTED_SCHEMA_SHA256,
                },
            },
            "phase2_corpus_manifest_bindings": {
                key: phase2_manifest[key] for key in MANIFEST_HASH_FIELDS
            },
            "annotation_sources": annotation_sources,
            "finalizer": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256(Path(__file__).resolve()),
            },
            "outputs": output_hashes,
            "governance": {
                "anonymous_identity_coverage_exactly_once": True,
                "outcome_group_coverage_exactly_once": True,
                "full_chart_files_hash_verified": len(chart_hashes),
                "outcome_sheet_files_hash_verified": len(sheet_hashes),
                "phase1_labels_modified": False,
                "post_signal_used_as_predictor": False,
                "numeric_return_field_read_or_aggregated": False,
                "security_identity_read_or_published": False,
                "rule_aggregation_performed": False,
                "rule_promotion_or_search_performed": False,
                "portfolio_replay_performed": False,
                "post_2020_row_read": False,
                "publication_atomic": True,
                "overwrite_refused": True,
            },
        }
        write_json(manifest_path, publication_manifest)

        input_hashes = {
            PHASE1_LEDGER: fixed_hashes["phase1_annotation_ledger"],
            PHASE1_MANIFEST: fixed_hashes["phase1_manifest"],
            PHASE1_DRIFT_FREEZE: fixed_hashes["phase1_reviewer_drift_freeze"],
            SCHEMA: fixed_hashes["phase2_annotation_schema"],
            phase2_manifest_path: manifest_hash,
            phase2_index_path: index_hash,
            placements_path: placements_hash,
            sheet_index_path: sheet_index_hash,
            **chart_hashes,
            **sheet_hashes,
            **{Path(source["path"]): source["sha256"] for source in annotation_sources},
        }
        verify_unchanged(input_hashes)
        if OUTPUT.exists():
            raise FreezeError(f"Phase-2 output appeared during construction: {OUTPUT}")
        staging.rename(OUTPUT)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "output": str(OUTPUT),
        "events": EXPECTED_EVENTS,
        "merged_ledger_sha256": output_hashes[ledger_path.name],
        "diagnostics_sha256": output_hashes[diagnostics_path.name],
        "summary_sha256": output_hashes[summary_path.name],
        "manifest_sha256": sha256(OUTPUT / "manifest.json"),
        "phase1_labels_modified": False,
        "post_signal_used_as_predictor": False,
        "numeric_return_field_read_or_aggregated": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase2-manifest", required=True, type=Path)
    parser.add_argument("--phase2-manifest-sha256", required=True)
    parser.add_argument("--phase2-index", required=True, type=Path)
    parser.add_argument("--phase2-index-sha256", required=True)
    parser.add_argument("--phase2-placements", required=True, type=Path)
    parser.add_argument("--phase2-placements-sha256", required=True)
    parser.add_argument("annotations", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = finalize(
        args.phase2_manifest,
        args.phase2_manifest_sha256,
        args.phase2_index,
        args.phase2_index_sha256,
        args.phase2_placements,
        args.phase2_placements_sha256,
        args.annotations,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
