#!/usr/bin/env python3
"""Freeze the V34R1 outcome-blind anonymous Phase-1 annotation ledger."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

EXPERIMENT = "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34R1"
SPEC_ID = "ASHARE-V34R1-PHASE1-ANONYMOUS-LEDGER-FREEZE-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC_REL = "research/market_behavior_os_v2/experiments/ASHARE-V34R1_phase1_ledger_freeze_spec.json"
FINALIZER_REL = (
    "research/market_behavior_os_v2/scripts/"
    "finalize_ashare_cash_distribution_realized_payout_quality_mother_v34r1_phase1.py"
)
SPEC = REPO / SPEC_REL
OUTPUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_cash_distribution_realized_payout_quality_mother_v34r1/"
    "stage_d_phase1_anonymous_review"
)
CORPUS = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_cash_distribution_realized_payout_quality_mother_v34r1/"
    "stage_c_phase1_anonymous_charts"
)
EXPECTED_EVENTS = 1_483
EXPECTED_SHEETS = 60
CHARTS_PER_SHEET = 25
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
OPAQUE_ID_PATTERN = re.compile(r"B-[0-9a-f]{20}")

PUBLIC_INDEX_COLUMNS = (
    "chart_number",
    "blind_chart_id",
    "blind_chart_path",
    "blind_chart_sha256",
    "sheet_number",
    "slot",
)
PLACEMENT_COLUMNS = ("sheet_number", "slot", "chart_number", "blind_chart_id")
AXES = ("primary_morphology", "market_tape", "signal_candle", "turnover_state")
AXIS_LABELS = {
    "primary_morphology": (
        "BASE_COMPRESSION",
        "ORDERLY_UPTREND",
        "EXTENDED_OR_SPIKE",
        "DOWNTREND_OR_BREAKDOWN",
        "CHOPPY_NO_STRUCTURE",
    ),
    "market_tape": ("BROAD_UP", "BROAD_DOWN", "MIXED_TRANSITION"),
    "signal_candle": ("STRONG_CLOSE", "WEAK_CLOSE", "NEUTRAL"),
    "turnover_state": (
        "DRY_OR_CONTRACTING",
        "SURGE_OR_EXPANDING",
        "NORMAL_MIXED",
    ),
}
ANNOTATION_FIELDS = ("chart_number", *AXES, "evidence", "reviewer")
LEDGER_FIELDS = (*PUBLIC_INDEX_COLUMNS, *AXES, "evidence", "reviewer")

EXPECTED_PUBLIC_PATHS = {
    "chart_corpus_manifest": str(CORPUS / "manifest.json"),
    "blind_index": str(CORPUS / "blind_index.csv"),
    "contact_sheet_placements": str(CORPUS / "contact_sheet_placements.csv"),
    "annotation_schema": (
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_anonymous_annotation_schema.json"
    ),
}
EXPECTED_SEGMENTS = (
    (
        "bacon_0001_0500",
        1,
        500,
        "Bacon",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_annotations_bacon_0001_0500.json",
    ),
    (
        "blind_consensus_0501_0525",
        501,
        525,
        "PHASE1_BLIND_CONSENSUS",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_annotations_consensus_0501_0525.json",
    ),
    (
        "bacon_0526_0750",
        526,
        750,
        "Bacon",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_annotations_bacon_0526_0750.json",
    ),
    (
        "galileo_0751_1000",
        751,
        1_000,
        "Galileo",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_annotations_galileo_0751_1000.json",
    ),
    (
        "templateaudit_corrected_1001_1483",
        1_001,
        1_483,
        "TemplateAuditCorrectedSignalBar",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_annotations_templateaudit_corrected_1001_1483.json",
    ),
)
EXPECTED_SUPPORT = (
    (
        "blind_consensus_protocol_0501_0525",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_0501_0525_consensus_protocol.json",
    ),
    (
        "corrected_axis_reliability_decision",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_axis_reliability_decision.json",
    ),
    (
        "templateaudit_signal_bar_correction_receipt",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_templateaudit_signal_bar_correction_receipt.md",
    ),
)
EXPECTED_EXCLUDED = (
    (
        "superseded_root_primary_0501_0525",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_annotations_root_0501_0525.json",
        "blind_consensus_0501_0525",
    ),
    (
        "superseded_templateaudit_main_1001_1483",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_annotations_nested_1001_1483.json",
        "templateaudit_corrected_1001_1483",
    ),
    (
        "superseded_templateaudit_calibration_0001_0025",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V34R1_phase1_calibration_templateaudit_0001_0025.json",
        "corrected_axis_reliability_decision",
    ),
)


class FreezeError(RuntimeError):
    """Fail closed on public-contract, annotation, or publication drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FreezeError(f"cannot hash authorized input {path}: {exc}") from exc
    return digest.hexdigest()


def strict_json(path: Path) -> Any:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise FreezeError(f"duplicate JSON keys in {path}: {duplicates}")
        return dict(pairs)

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read authorized JSON {path}: {exc}") from exc


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise FreezeError(f"{label} must be one lowercase SHA-256 digest")
    return value


def require_exact_keys(value: Any, expected: Iterable[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise FreezeError(f"{label} must contain exactly {tuple(expected)}")
    return value


def repo_path(value: Any, expected: str, label: str) -> Path:
    if value != expected:
        raise FreezeError(f"{label} path drift: {value!r} != {expected!r}")
    parsed = PurePosixPath(expected)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise FreezeError(f"{label} must be one repository-relative path")
    return REPO.joinpath(*parsed.parts)


def absolute_path(value: Any, expected: str, label: str) -> Path:
    if value != expected:
        raise FreezeError(f"{label} path drift: {value!r} != {expected!r}")
    return Path(expected)


def load_and_validate_spec() -> dict[str, Any]:
    spec = require_exact_keys(
        strict_json(SPEC),
        (
            "spec_id",
            "experiment",
            "stage",
            "expected_events",
            "expected_sheets",
            "finalizer",
            "public_anonymous_inputs",
            "primary_annotation_segments",
            "supporting_contracts",
            "excluded_superseded",
            "output",
            "statistics_policy",
            "phase2_constraints",
            "prohibited",
        ),
        "freeze spec",
    )
    if spec["spec_id"] != SPEC_ID or spec["experiment"] != EXPERIMENT:
        raise FreezeError("freeze spec identity drift")
    if spec["stage"] != "PHASE1_ANONYMOUS_LEDGER_FREEZE":
        raise FreezeError("freeze spec stage drift")
    if spec["expected_events"] != EXPECTED_EVENTS or spec["expected_sheets"] != EXPECTED_SHEETS:
        raise FreezeError("freeze spec coverage drift")

    finalizer = require_exact_keys(spec["finalizer"], ("path", "sha256"), "finalizer binding")
    repo_path(finalizer["path"], FINALIZER_REL, "finalizer")
    if sha256(Path(__file__)) != require_sha256(finalizer["sha256"], "finalizer hash"):
        raise FreezeError("finalizer identity drift")

    public = require_exact_keys(
        spec["public_anonymous_inputs"], EXPECTED_PUBLIC_PATHS, "public input bindings"
    )
    for role, expected_path in EXPECTED_PUBLIC_PATHS.items():
        extra = (
            ("path", "sha256", "columns")
            if role in {"blind_index", "contact_sheet_placements"}
            else ("path", "sha256")
        )
        item = require_exact_keys(public[role], extra, f"public input {role}")
        if role == "annotation_schema":
            repo_path(item["path"], expected_path, role)
        else:
            absolute_path(item["path"], expected_path, role)
        require_sha256(item["sha256"], f"{role} hash")
    if tuple(public["blind_index"]["columns"]) != PUBLIC_INDEX_COLUMNS:
        raise FreezeError("blind-index public-column contract drift")
    if tuple(public["contact_sheet_placements"]["columns"]) != PLACEMENT_COLUMNS:
        raise FreezeError("placement public-column contract drift")

    segments = spec["primary_annotation_segments"]
    if not isinstance(segments, list) or len(segments) != len(EXPECTED_SEGMENTS):
        raise FreezeError("primary annotation segment count drift")
    for item, expected in zip(segments, EXPECTED_SEGMENTS, strict=True):
        item = require_exact_keys(
            item,
            ("segment_id", "start", "end", "rows", "reviewer", "path", "sha256"),
            "primary annotation segment",
        )
        segment_id, start, end, reviewer, expected_path = expected
        if (
            item["segment_id"],
            item["start"],
            item["end"],
            item["rows"],
            item["reviewer"],
        ) != (segment_id, start, end, end - start + 1, reviewer):
            raise FreezeError(f"primary segment contract drift for {segment_id}")
        repo_path(item["path"], expected_path, segment_id)
        require_sha256(item["sha256"], f"{segment_id} hash")

    supporting = spec["supporting_contracts"]
    if not isinstance(supporting, list) or len(supporting) != len(EXPECTED_SUPPORT):
        raise FreezeError("supporting-contract count drift")
    for item, expected in zip(supporting, EXPECTED_SUPPORT, strict=True):
        item = require_exact_keys(
            item, ("role", "path", "sha256", "ledger_input"), "supporting contract"
        )
        role, expected_path = expected
        if item["role"] != role or item["ledger_input"] is not False:
            raise FreezeError(f"supporting-contract role drift for {role}")
        repo_path(item["path"], expected_path, role)
        require_sha256(item["sha256"], f"{role} hash")

    excluded = spec["excluded_superseded"]
    if not isinstance(excluded, list) or len(excluded) != len(EXPECTED_EXCLUDED):
        raise FreezeError("excluded/superseded count drift")
    for item, expected in zip(excluded, EXPECTED_EXCLUDED, strict=True):
        item = require_exact_keys(
            item,
            ("role", "path", "sha256", "ledger_input", "superseded_by"),
            "excluded/superseded binding",
        )
        role, expected_path, superseded_by = expected
        if (
            item["role"] != role
            or item["ledger_input"] is not False
            or item["superseded_by"] != superseded_by
        ):
            raise FreezeError(f"excluded/superseded contract drift for {role}")
        repo_path(item["path"], expected_path, role)
        require_sha256(item["sha256"], f"{role} hash")

    output = require_exact_keys(
        spec["output"],
        ("directory", "ledger_file", "manifest_file", "no_overwrite"),
        "output contract",
    )
    absolute_path(output["directory"], str(OUTPUT), "output directory")
    if output != {
        "directory": str(OUTPUT),
        "ledger_file": "phase1_annotation_ledger.csv",
        "manifest_file": "manifest.json",
        "no_overwrite": True,
    }:
        raise FreezeError("output contract drift")
    policy = require_exact_keys(
        spec["statistics_policy"],
        ("label_counts_only", "reviewer_drift_only", "rule_aggregation", "returns"),
        "statistics policy",
    )
    if policy != {
        "label_counts_only": True,
        "reviewer_drift_only": True,
        "rule_aggregation": False,
        "returns": False,
    }:
        raise FreezeError("statistics policy drift")
    return spec


def csv_header_gate(path: Path, expected: tuple[str, ...], label: str) -> None:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle), None)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FreezeError(f"cannot read public header for {label}: {exc}") from exc
    if tuple(header or ()) != expected:
        raise FreezeError(f"{label} is not the exact public anonymous column contract")


def verify_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256(path)
    if actual != expected:
        raise FreezeError(f"{label} hash drift: {actual} != {expected}")
    return actual


def parse_positive_integer(value: Any, label: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise FreezeError(f"{label} is not a canonical positive integer")
    return int(value)


def load_schema(path: Path) -> dict[str, tuple[str, ...]]:
    schema = strict_json(path)
    try:
        properties = schema["items"]["properties"]
        required = tuple(schema["items"]["required"])
    except (KeyError, TypeError) as exc:
        raise FreezeError("annotation schema structure drift") from exc
    if (
        set(required) != set(ANNOTATION_FIELDS)
        or schema["items"].get("additionalProperties") is not False
    ):
        raise FreezeError("annotation schema field contract drift")
    for axis in AXES:
        if tuple(properties[axis].get("enum", ())) != AXIS_LABELS[axis]:
            raise FreezeError(f"annotation schema enum drift for {axis}")
    return AXIS_LABELS


def validate_public_corpus_manifest(
    manifest_path: Path,
    public: dict[str, Any],
) -> dict[str, Any]:
    manifest = strict_json(manifest_path)
    expected_false = (
        "identity_crosswalk_persisted",
        "identity_exposed_to_reviewer",
        "identity_mapping_persisted",
        "outcome_artifact_hashed",
        "outcome_artifact_opened_or_parsed",
        "outcome_artifact_statted",
        "outcome_grouping_performed",
        "portfolio_replay_performed",
        "post_2020_row_read",
        "post_signal_row_read",
        "rule_aggregation_performed",
    )
    if manifest.get("experiment") != EXPERIMENT or manifest.get("events") != EXPECTED_EVENTS:
        raise FreezeError("public chart-corpus manifest identity/coverage drift")
    if manifest.get("stage") != "PHASE1_ANONYMOUS_CAUSAL_VISUAL_REVIEW_CORPUS":
        raise FreezeError("public chart-corpus stage drift")
    if any(manifest.get(key) is not False for key in expected_false):
        raise FreezeError("public chart-corpus blindness assertion drift")
    if manifest.get("full_chart_generated") is not False:
        raise FreezeError("public chart corpus unexpectedly contains full charts")
    if manifest.get("phase1_window_relative_global_sessions") != [-126, 0]:
        raise FreezeError("public chart-corpus signal-time window drift")
    if manifest.get("maximum_source_date") != "2020-12-01":
        raise FreezeError("public chart-corpus maximum source date drift")
    if manifest.get("blind_index_sha256") != public["blind_index"]["sha256"]:
        raise FreezeError("chart-corpus manifest blind-index binding drift")
    if (
        manifest.get("contact_sheet_placements_sha256")
        != public["contact_sheet_placements"]["sha256"]
    ):
        raise FreezeError("chart-corpus manifest placement binding drift")
    if manifest.get("annotation_schema_sha256") != public["annotation_schema"]["sha256"]:
        raise FreezeError("chart-corpus manifest annotation-schema binding drift")
    return manifest


def load_blind_index(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PUBLIC_INDEX_COLUMNS:
            raise FreezeError("blind-index columns changed after public header gate")
        for line_number, raw in enumerate(reader, start=2):
            if None in raw or any(value is None for value in raw.values()):
                raise FreezeError(f"malformed blind-index row at line {line_number}")
            number = parse_positive_integer(raw["chart_number"], f"blind-index line {line_number}")
            sheet = parse_positive_integer(
                raw["sheet_number"], f"blind-index line {line_number} sheet"
            )
            slot = parse_positive_integer(raw["slot"], f"blind-index line {line_number} slot")
            blind_id = raw["blind_chart_id"]
            if OPAQUE_ID_PATTERN.fullmatch(blind_id) is None:
                raise FreezeError(f"non-opaque blind ID at line {line_number}")
            parsed = PurePosixPath(raw["blind_chart_path"])
            if parsed.is_absolute() or ".." in parsed.parts or parsed.name != f"{blind_id}.png":
                raise FreezeError(f"non-public blind chart path at line {line_number}")
            require_sha256(raw["blind_chart_sha256"], f"blind-index line {line_number} chart hash")
            rows.append(
                {
                    "chart_number": number,
                    "blind_chart_id": blind_id,
                    "blind_chart_path": raw["blind_chart_path"],
                    "blind_chart_sha256": raw["blind_chart_sha256"],
                    "sheet_number": sheet,
                    "slot": slot,
                }
            )
    if len(rows) != EXPECTED_EVENTS or [row["chart_number"] for row in rows] != list(
        range(1, EXPECTED_EVENTS + 1)
    ):
        raise FreezeError("blind-index coverage/order is not exactly 1..1483")
    if len({row["blind_chart_id"] for row in rows}) != EXPECTED_EVENTS:
        raise FreezeError("blind IDs are not unique")
    if len({row["blind_chart_path"] for row in rows}) != EXPECTED_EVENTS:
        raise FreezeError("blind chart paths are not unique")
    for row in rows:
        expected_sheet = (row["chart_number"] - 1) // CHARTS_PER_SHEET + 1
        expected_slot = (row["chart_number"] - 1) % CHARTS_PER_SHEET + 1
        if (row["sheet_number"], row["slot"]) != (expected_sheet, expected_slot):
            raise FreezeError(f"noncanonical blind placement for chart {row['chart_number']}")
    if max(row["sheet_number"] for row in rows) != EXPECTED_SHEETS:
        raise FreezeError("blind-index sheet coverage drift")
    return rows


def validate_placements(path: Path, blind_rows: list[dict[str, Any]]) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PLACEMENT_COLUMNS:
            raise FreezeError("placement columns changed after public header gate")
        rows = list(reader)
    if len(rows) != EXPECTED_EVENTS:
        raise FreezeError("placement row count drift")
    for number, (placement, blind) in enumerate(
        zip(rows, blind_rows, strict=True), start=1
    ):
        expected = {
            "sheet_number": str(blind["sheet_number"]),
            "slot": str(blind["slot"]),
            "chart_number": str(number),
            "blind_chart_id": blind["blind_chart_id"],
        }
        if placement != expected:
            raise FreezeError(f"placement/blind-index mismatch at chart {number}")


def validate_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise FreezeError(f"{label} must be nonempty, trimmed, and <= {maximum} characters")
    if "\n" in value or "\r" in value or any(ord(character) < 32 for character in value):
        raise FreezeError(f"{label} must be one printable line")
    return value


def load_segment(item: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = repo_path(item["path"], item["path"], item["segment_id"])
    raw = strict_json(path)
    if not isinstance(raw, list) or len(raw) != item["rows"]:
        raise FreezeError(f"annotation row count drift for {item['segment_id']}")
    rows: list[dict[str, Any]] = []
    for expected_number, annotation in zip(
        range(item["start"], item["end"] + 1), raw, strict=True
    ):
        if not isinstance(annotation, dict) or set(annotation) != set(ANNOTATION_FIELDS):
            raise FreezeError(f"annotation field drift in {item['segment_id']}")
        if (
            type(annotation["chart_number"]) is not int
            or annotation["chart_number"] != expected_number
        ):
            raise FreezeError(f"annotation chart order drift in {item['segment_id']}")
        for axis in AXES:
            if annotation[axis] not in AXIS_LABELS[axis]:
                raise FreezeError(f"invalid {axis} at chart {expected_number}")
        validate_text(annotation["evidence"], f"chart {expected_number} evidence", 240)
        reviewer = validate_text(annotation["reviewer"], f"chart {expected_number} reviewer", 80)
        if reviewer != item["reviewer"]:
            raise FreezeError(
                f"reviewer drift inside {item['segment_id']} at chart {expected_number}"
            )
        rows.append(dict(annotation))
    return rows, {
        "segment_id": item["segment_id"],
        "start": item["start"],
        "end": item["end"],
        "rows": item["rows"],
        "reviewer": item["reviewer"],
        "path": item["path"],
        "sha256": item["sha256"],
    }


def build_ledger(
    blind_rows: list[dict[str, Any]], annotations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(annotations) != EXPECTED_EVENTS or [row["chart_number"] for row in annotations] != list(
        range(1, EXPECTED_EVENTS + 1)
    ):
        raise FreezeError("primary annotation coverage is not exactly 1..1483")
    ledger = [
        {**blind, **annotation}
        for blind, annotation in zip(blind_rows, annotations, strict=True)
    ]
    if any(set(row) != set(LEDGER_FIELDS) for row in ledger):
        raise FreezeError("ledger field contract drift")
    return ledger


def write_ledger(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row[field] for field in LEDGER_FIELDS} for row in rows)


def axis_rates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    return {
        axis: {
            label: {
                "count": sum(row[axis] == label for row in rows),
                "rate": round(sum(row[axis] == label for row in rows) / total, 12),
            }
            for label in AXIS_LABELS[axis]
        }
        for axis in AXES
    }


def drift_ranges(units: list[dict[str, Any]], unit_key: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for axis in AXES:
        result[axis] = {}
        for label in AXIS_LABELS[axis]:
            rates = sorted(
                ((unit["axis_rates"][axis][label]["rate"], unit[unit_key]) for unit in units),
                key=lambda pair: (pair[0], pair[1]),
            )
            minimum_rate, minimum_unit = rates[0]
            maximum_rate, maximum_unit = rates[-1]
            result[axis][label] = {
                "minimum_unit": minimum_unit,
                "minimum_rate": minimum_rate,
                "maximum_unit": maximum_unit,
                "maximum_rate": maximum_rate,
                "max_minus_min_percentage_points": round((maximum_rate - minimum_rate) * 100, 10),
            }
    return result


def descriptive_statistics(
    ledger: list[dict[str, Any]],
    segment_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    global_counts = {
        axis: {label: sum(row[axis] == label for row in ledger) for label in AXIS_LABELS[axis]}
        for axis in AXES
    }
    chunks: list[dict[str, Any]] = []
    for source in segment_sources:
        rows = ledger[source["start"] - 1 : source["end"]]
        chunks.append(
            {
                "segment_id": source["segment_id"],
                "reviewer": source["reviewer"],
                "n": len(rows),
                "axis_rates": axis_rates(rows),
            }
        )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ledger:
        grouped[row["reviewer"]].append(row)
    reviewers = [
        {
            "reviewer": reviewer,
            "n": len(rows),
            "axis_rates": axis_rates(rows),
        }
        for reviewer, rows in sorted(grouped.items())
    ]
    return {
        "global_axis_label_counts": global_counts,
        "primary_chunk_axis_rates": chunks,
        "reviewer_axis_rates": reviewers,
        "max_min_drift": {
            "across_primary_chunks": drift_ranges(chunks, "segment_id"),
            "across_reviewer_groups": drift_ranges(reviewers, "reviewer"),
        },
        "semantics": (
            "Counts and rates are descriptive only. Opaque chart order is approximately "
            "randomized; "
            "no label was changed and no rule or return was computed from reviewer drift."
        ),
    }


def finalize() -> dict[str, Any]:
    spec = load_and_validate_spec()
    public = spec["public_anonymous_inputs"]
    blind_path = absolute_path(
        public["blind_index"]["path"], EXPECTED_PUBLIC_PATHS["blind_index"], "blind index"
    )
    placement_path = absolute_path(
        public["contact_sheet_placements"]["path"],
        EXPECTED_PUBLIC_PATHS["contact_sheet_placements"],
        "contact-sheet placements",
    )

    # This public-column gate deliberately precedes every stat/hash/full read of blind_index.csv.
    csv_header_gate(blind_path, PUBLIC_INDEX_COLUMNS, "blind_index.csv")
    csv_header_gate(placement_path, PLACEMENT_COLUMNS, "contact_sheet_placements.csv")

    bindings: list[tuple[Path, str, str]] = [(SPEC, sha256(SPEC), "freeze spec")]
    public_paths: dict[str, Path] = {}
    for role, item in public.items():
        path = (
            repo_path(item["path"], item["path"], role)
            if role == "annotation_schema"
            else Path(item["path"])
        )
        verify_hash(path, item["sha256"], role)
        public_paths[role] = path
        bindings.append((path, item["sha256"], role))
    bindings.append((Path(__file__), spec["finalizer"]["sha256"], "finalizer"))

    for group_name in (
        "primary_annotation_segments",
        "supporting_contracts",
        "excluded_superseded",
    ):
        for item in spec[group_name]:
            label = item["segment_id"] if "segment_id" in item else item["role"]
            path = repo_path(item["path"], item["path"], label)
            verify_hash(path, item["sha256"], label)
            bindings.append((path, item["sha256"], label))

    load_schema(public_paths["annotation_schema"])
    corpus_manifest = validate_public_corpus_manifest(public_paths["chart_corpus_manifest"], public)
    blind_rows = load_blind_index(blind_path)
    validate_placements(placement_path, blind_rows)

    annotations: list[dict[str, Any]] = []
    segment_sources: list[dict[str, Any]] = []
    for item in spec["primary_annotation_segments"]:
        rows, source = load_segment(item)
        annotations.extend(rows)
        segment_sources.append(source)
    ledger = build_ledger(blind_rows, annotations)
    statistics = descriptive_statistics(ledger, segment_sources)

    if OUTPUT.exists():
        raise FreezeError(f"refusing to overwrite frozen Phase-1 output: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v34r1_phase1_review.staging.", dir=OUTPUT.parent))
    try:
        ledger_path = staging / "phase1_annotation_ledger.csv"
        manifest_path = staging / "manifest.json"
        write_ledger(ledger, ledger_path)
        manifest = {
            "experiment": EXPERIMENT,
            "stage": "PHASE1_ANONYMOUS_SIGNAL_TIME_ANNOTATIONS_FROZEN",
            "status": "FROZEN_OUTCOME_BLIND",
            "events": EXPECTED_EVENTS,
            "coverage_exactly_once": True,
            "deterministic_sort": "chart_number ascending, exactly 1..1483",
            "freeze_spec": {"path": SPEC_REL, "sha256": sha256(SPEC)},
            "finalizer": {"path": FINALIZER_REL, "sha256": sha256(Path(__file__))},
            "public_anonymous_corpus": {
                "chart_corpus_manifest": public["chart_corpus_manifest"],
                "blind_index": public["blind_index"],
                "contact_sheet_placements": public["contact_sheet_placements"],
                "annotation_schema": public["annotation_schema"],
                "blind_order_sha256": corpus_manifest["blind_order_sha256"],
                "window_relative_global_sessions": [-126, 0],
                "maximum_source_date": "2020-12-01",
            },
            "primary_annotation_segments": segment_sources,
            "supporting_contracts": spec["supporting_contracts"],
            "excluded_superseded": spec["excluded_superseded"],
            "ledger": {
                "file": ledger_path.name,
                "sha256": sha256(ledger_path),
                "rows": EXPECTED_EVENTS,
                "columns": list(LEDGER_FIELDS),
            },
            "descriptive_label_statistics": statistics,
            "phase2_constraints": spec["phase2_constraints"],
            "governance": {
                "identity_mapping_read": False,
                "identity_crosswalk_read": False,
                "stage_b_result_read": False,
                "future_paths_read": False,
                "outcomes_read": False,
                "post_signal_rows_read": False,
                "returns_aggregated": False,
                "rule_aggregation_performed": False,
                "labels_modified_by_finalizer": False,
                "signal_candle_rule_use_permitted": False,
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for path, expected_hash, label in bindings:
            verify_hash(path, expected_hash, f"{label} changed during finalization")
        if OUTPUT.exists():
            raise FreezeError(f"Phase-1 output appeared during construction: {OUTPUT}")
        staging.rename(OUTPUT)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "output": str(OUTPUT),
        "events": EXPECTED_EVENTS,
        "ledger_sha256": manifest["ledger"]["sha256"],
        "manifest_sha256": sha256(OUTPUT / "manifest.json"),
        "outcomes_read": False,
        "rule_aggregation_performed": False,
    }


def main() -> None:
    print(json.dumps(finalize(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
