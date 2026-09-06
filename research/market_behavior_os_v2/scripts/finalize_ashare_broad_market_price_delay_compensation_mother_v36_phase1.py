#!/usr/bin/env python3
"""Freeze the outcome-blind V36 Phase-1 anonymous annotation ledger."""

from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

EXPERIMENT = "ASHARE-BROAD-MARKET-PRICE-DELAY-COMPENSATION-MOTHER-V36"
SPEC_ID = "ASHARE-V36-PHASE1-ANONYMOUS-LEDGER-FREEZE-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC_REL = "research/market_behavior_os_v2/experiments/ASHARE-V36_phase1_ledger_freeze_spec.json"
FINALIZER_REL = (
    "research/market_behavior_os_v2/scripts/"
    "finalize_ashare_broad_market_price_delay_compensation_mother_v36_phase1.py"
)
SPEC = REPO / SPEC_REL
CORPUS = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_broad_market_price_delay_compensation_mother_v36/"
    "stage_c_phase1_anonymous_charts"
)
OUTPUT = CORPUS.parent / "stage_d_phase1_anonymous_review"
EXPECTED_EVENTS = 531
EXPECTED_SHEETS = 22
CHARTS_PER_SHEET = 25
SHA256_RE = re.compile(r"[0-9a-f]{64}")
OPAQUE_ID_RE = re.compile(r"B-[0-9a-f]{20}")

INDEX_COLUMNS = (
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
    "turnover_state": ("DRY_OR_CONTRACTING", "SURGE_OR_EXPANDING", "NORMAL_MIXED"),
}
ANNOTATION_FIELDS = ("chart_number", *AXES, "evidence", "reviewer")
LEDGER_FIELDS = (*INDEX_COLUMNS, *AXES, "evidence", "reviewer")

EXPECTED_PUBLIC = {
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
        "galileo_0001_0200",
        1,
        200,
        "Galileo",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V36_phase1_annotations_galileo_0001_0200.json",
    ),
    (
        "bacon_0201_0400",
        201,
        400,
        "Bacon",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V36_phase1_annotations_bacon_0201_0400.json",
    ),
    (
        "templateaudit_0401_0531",
        401,
        531,
        "TemplateAudit",
        "research/market_behavior_os_v2/experiments/"
        "ASHARE-V36_phase1_annotations_templateaudit_0401_0531.json",
    ),
)
RELIABILITY_REL = (
    "research/market_behavior_os_v2/experiments/ASHARE-V36_phase1_axis_reliability_decision.json"
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
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        duplicates = sorted(
            key for key, count in Counter(key for key, _ in pairs).items() if count > 1
        )
        if duplicates:
            raise FreezeError(f"duplicate JSON keys in {path}: {duplicates}")
        return dict(pairs)

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read authorized JSON {path}: {exc}") from exc


def require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise FreezeError(f"{label} is not one lowercase SHA-256 digest")
    return value


def repo_path(value: Any, expected: str, label: str) -> Path:
    if value != expected:
        raise FreezeError(f"{label} path drift: {value!r} != {expected!r}")
    parsed = PurePosixPath(expected)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise FreezeError(f"{label} must be repository-relative")
    return REPO.joinpath(*parsed.parts)


def exact_keys(value: Any, keys: tuple[str, ...], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise FreezeError(f"{label} must contain exactly {keys}")
    return value


def verify_hash(path: Path, expected: str, label: str) -> None:
    actual = sha256(path)
    if actual != expected:
        raise FreezeError(f"{label} hash drift: {actual} != {expected}")


def load_spec() -> dict[str, Any]:
    spec = exact_keys(
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
            "axis_reliability_decision",
            "output",
            "statistics_policy",
            "phase2_constraints",
            "prohibited",
        ),
        "freeze spec",
    )
    if (
        spec["spec_id"] != SPEC_ID
        or spec["experiment"] != EXPERIMENT
        or spec["stage"] != "PHASE1_ANONYMOUS_LEDGER_FREEZE"
        or spec["expected_events"] != EXPECTED_EVENTS
        or spec["expected_sheets"] != EXPECTED_SHEETS
    ):
        raise FreezeError("freeze spec identity or coverage drift")
    finalizer = exact_keys(spec["finalizer"], ("path", "sha256"), "finalizer")
    repo_path(finalizer["path"], FINALIZER_REL, "finalizer")
    verify_hash(Path(__file__), require_hash(finalizer["sha256"], "finalizer hash"), "finalizer")

    public = exact_keys(spec["public_anonymous_inputs"], tuple(EXPECTED_PUBLIC), "public inputs")
    for role, expected_path in EXPECTED_PUBLIC.items():
        keys = (
            ("path", "sha256", "columns")
            if role in {"blind_index", "contact_sheet_placements"}
            else ("path", "sha256")
        )
        item = exact_keys(public[role], keys, role)
        if role == "annotation_schema":
            repo_path(item["path"], expected_path, role)
        elif item["path"] != expected_path:
            raise FreezeError(f"{role} path drift")
        require_hash(item["sha256"], f"{role} hash")
    if tuple(public["blind_index"]["columns"]) != INDEX_COLUMNS:
        raise FreezeError("blind-index column contract drift")
    if tuple(public["contact_sheet_placements"]["columns"]) != PLACEMENT_COLUMNS:
        raise FreezeError("placement column contract drift")

    segments = spec["primary_annotation_segments"]
    if not isinstance(segments, list) or len(segments) != len(EXPECTED_SEGMENTS):
        raise FreezeError("annotation segment count drift")
    for item, expected in zip(segments, EXPECTED_SEGMENTS, strict=True):
        exact_keys(
            item, ("segment_id", "start", "end", "rows", "reviewer", "path", "sha256"), "segment"
        )
        segment_id, start, end, reviewer, path = expected
        if (item["segment_id"], item["start"], item["end"], item["rows"], item["reviewer"]) != (
            segment_id,
            start,
            end,
            end - start + 1,
            reviewer,
        ):
            raise FreezeError(f"annotation segment drift: {segment_id}")
        repo_path(item["path"], path, segment_id)
        require_hash(item["sha256"], f"{segment_id} hash")

    reliability = exact_keys(
        spec["axis_reliability_decision"], ("path", "sha256", "ledger_input"), "reliability binding"
    )
    repo_path(reliability["path"], RELIABILITY_REL, "axis reliability decision")
    require_hash(reliability["sha256"], "axis reliability hash")
    if reliability["ledger_input"] is not False:
        raise FreezeError("axis reliability decision cannot be a label source")

    output = exact_keys(
        spec["output"], ("directory", "ledger_file", "manifest_file", "no_overwrite"), "output"
    )
    if output != {
        "directory": str(OUTPUT),
        "ledger_file": "phase1_annotation_ledger.csv",
        "manifest_file": "manifest.json",
        "no_overwrite": True,
    }:
        raise FreezeError("output contract drift")
    if spec["statistics_policy"] != {
        "label_counts_only": True,
        "reviewer_drift_only": True,
        "rule_aggregation": False,
        "returns": False,
    }:
        raise FreezeError("statistics policy drift")
    return spec


def validate_schema(path: Path) -> None:
    schema = strict_json(path)
    try:
        item = schema["items"]
        properties = item["properties"]
    except (KeyError, TypeError) as exc:
        raise FreezeError("annotation schema structure drift") from exc
    if item.get("additionalProperties") is not False or set(item.get("required", ())) != set(
        ANNOTATION_FIELDS
    ):
        raise FreezeError("annotation schema field contract drift")
    for axis in AXES:
        if tuple(properties[axis].get("enum", ())) != AXIS_LABELS[axis]:
            raise FreezeError(f"annotation schema enum drift: {axis}")


def read_csv(path: Path, columns: tuple[str, ...], label: str) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != columns:
                raise FreezeError(f"{label} public-column contract drift")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise FreezeError(f"cannot read {label}: {exc}") from exc
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise FreezeError(f"malformed {label} row")
    return rows


def positive_int(value: str, label: str) -> int:
    if re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise FreezeError(f"{label} is not a canonical positive integer")
    return int(value)


def validate_corpus(public: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = strict_json(Path(public["chart_corpus_manifest"]["path"]))
    if (
        manifest.get("experiment") != EXPERIMENT
        or manifest.get("stage") != "PHASE1_ANONYMOUS_CAUSAL_VISUAL_REVIEW_CORPUS"
        or manifest.get("events") != EXPECTED_EVENTS
        or manifest.get("individual_anonymous_charts") != EXPECTED_EVENTS
        or manifest.get("anonymous_contact_sheets") != EXPECTED_SHEETS
        or manifest.get("maximum_source_date") != "2020-12-31"
        or manifest.get("phase1_window_relative_global_sessions") != [-126, 0]
    ):
        raise FreezeError("public chart-corpus identity, coverage, or date drift")
    false_flags = (
        "identity_crosswalk_persisted",
        "identity_exposed_to_reviewer",
        "identity_mapping_persisted",
        "outcome_grouping_performed",
        "portfolio_replay_performed",
        "post_2020_row_read",
        "post_signal_row_read",
        "rule_aggregation_performed",
        "stage_b_artifact_path_declared",
        "stage_b_artifact_statted_hashed_opened_or_parsed",
    )
    if any(manifest.get(flag) is not False for flag in false_flags):
        raise FreezeError("public chart-corpus blindness assertion drift")
    if manifest.get("blind_index_sha256") != public["blind_index"]["sha256"]:
        raise FreezeError("manifest/blind-index binding drift")
    if (
        manifest.get("contact_sheet_placements_sha256")
        != public["contact_sheet_placements"]["sha256"]
    ):
        raise FreezeError("manifest/placement binding drift")
    if manifest.get("annotation_schema_sha256") != public["annotation_schema"]["sha256"]:
        raise FreezeError("manifest/schema binding drift")

    raw = read_csv(Path(public["blind_index"]["path"]), INDEX_COLUMNS, "blind index")
    if len(raw) != EXPECTED_EVENTS:
        raise FreezeError("blind-index row count drift")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for expected_number, row in enumerate(raw, start=1):
        number = positive_int(row["chart_number"], "chart number")
        sheet = positive_int(row["sheet_number"], "sheet number")
        slot = positive_int(row["slot"], "slot")
        blind_id = row["blind_chart_id"]
        if (
            number != expected_number
            or OPAQUE_ID_RE.fullmatch(blind_id) is None
            or blind_id in seen_ids
        ):
            raise FreezeError(f"blind identity/order drift at chart {expected_number}")
        seen_ids.add(blind_id)
        expected_sheet = (number - 1) // CHARTS_PER_SHEET + 1
        expected_slot = (number - 1) % CHARTS_PER_SHEET + 1
        chart_rel = PurePosixPath(row["blind_chart_path"])
        if (
            (sheet, slot) != (expected_sheet, expected_slot)
            or chart_rel.is_absolute()
            or ".." in chart_rel.parts
            or chart_rel.name != f"{blind_id}.png"
        ):
            raise FreezeError(f"blind path/placement drift at chart {number}")
        chart_hash = require_hash(row["blind_chart_sha256"], f"chart {number} hash")
        verify_hash(CORPUS.joinpath(*chart_rel.parts), chart_hash, f"chart {number}")
        rows.append(
            {
                "chart_number": number,
                "blind_chart_id": blind_id,
                "blind_chart_path": row["blind_chart_path"],
                "blind_chart_sha256": chart_hash,
                "sheet_number": sheet,
                "slot": slot,
            }
        )
    if max(row["sheet_number"] for row in rows) != EXPECTED_SHEETS:
        raise FreezeError("sheet coverage drift")

    placements = read_csv(
        Path(public["contact_sheet_placements"]["path"]), PLACEMENT_COLUMNS, "placements"
    )
    if len(placements) != EXPECTED_EVENTS:
        raise FreezeError("placement row count drift")
    for number, (placement, blind) in enumerate(zip(placements, rows, strict=True), start=1):
        expected = {
            "sheet_number": str(blind["sheet_number"]),
            "slot": str(blind["slot"]),
            "chart_number": str(number),
            "blind_chart_id": blind["blind_chart_id"],
        }
        if placement != expected:
            raise FreezeError(f"placement/index mismatch at chart {number}")
    return rows


def validate_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise FreezeError(f"{label} must be nonempty, trimmed, and <= {maximum} characters")
    if "\n" in value or "\r" in value or any(ord(character) < 32 for character in value):
        raise FreezeError(f"{label} must be one printable line")
    return value


def load_annotations(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    annotations: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for item in spec["primary_annotation_segments"]:
        path = repo_path(item["path"], item["path"], item["segment_id"])
        raw = strict_json(path)
        if not isinstance(raw, list) or len(raw) != item["rows"]:
            raise FreezeError(f"row count drift: {item['segment_id']}")
        for expected_number, row in zip(range(item["start"], item["end"] + 1), raw, strict=True):
            if not isinstance(row, dict) or set(row) != set(ANNOTATION_FIELDS):
                raise FreezeError(f"annotation field drift at chart {expected_number}")
            if type(row["chart_number"]) is not int or row["chart_number"] != expected_number:
                raise FreezeError(f"annotation order drift at chart {expected_number}")
            if row["reviewer"] != item["reviewer"]:
                raise FreezeError(f"reviewer drift at chart {expected_number}")
            for axis in AXES:
                if row[axis] not in AXIS_LABELS[axis]:
                    raise FreezeError(f"invalid {axis} at chart {expected_number}")
            validate_text(row["evidence"], f"chart {expected_number} evidence", 240)
            validate_text(row["reviewer"], f"chart {expected_number} reviewer", 80)
            annotations.append(dict(row))
        sources.append(dict(item))
    if [row["chart_number"] for row in annotations] != list(range(1, EXPECTED_EVENTS + 1)):
        raise FreezeError("primary annotation coverage is not exactly 1..531")
    return annotations, sources


def validate_reliability(path: Path) -> dict[str, Any]:
    decision = strict_json(path)
    if (
        decision.get("experiment") != EXPERIMENT
        or decision.get("stage") != "PHASE1_OUTCOME_BLIND_AXIS_RELIABILITY"
        or decision.get("status") != "FROZEN_BEFORE_ANY_OUTCOME_CONTRACT_OR_ATTRIBUTION"
        or decision.get("eligible_discovery_prompt_axes") != ["primary_morphology", "market_tape"]
        or decision.get("descriptive_only_axes") != ["signal_candle", "turnover_state"]
    ):
        raise FreezeError("axis reliability decision drift")
    for item in decision.get("inputs", []):
        source = repo_path(
            item.get("path"), item.get("path"), f"calibration {item.get('reviewer')}"
        )
        verify_hash(
            source, require_hash(item.get("sha256"), "calibration hash"), "calibration input"
        )
    return decision


def label_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    overall = {
        axis: {label: sum(row[axis] == label for row in rows) for label in AXIS_LABELS[axis]}
        for axis in AXES
    }
    by_reviewer: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["reviewer"]].append(row)
    for reviewer, group in sorted(grouped.items()):
        by_reviewer[reviewer] = {
            "n": len(group),
            "counts": {
                axis: {
                    label: sum(row[axis] == label for row in group) for label in AXIS_LABELS[axis]
                }
                for axis in AXES
            },
        }
    return {
        "global_axis_label_counts": overall,
        "reviewer_axis_label_counts": by_reviewer,
        "semantics": (
            "Descriptive counts only; no labels were changed and no outcomes, "
            "identities, rules, or returns were read or computed."
        ),
    }


def atomic_publish_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    rename_exclusive = getattr(libc, "renamex_np", None)
    if rename_exclusive is None:
        raise FreezeError("atomic exclusive directory rename is unavailable")
    rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename_exclusive.restype = ctypes.c_int
    if rename_exclusive(os.fsencode(source), os.fsencode(destination), 0x00000004):
        error = ctypes.get_errno()
        raise FreezeError(f"atomic no-overwrite publication failed: {os.strerror(error)}")


def finalize() -> dict[str, Any]:
    spec = load_spec()
    public = spec["public_anonymous_inputs"]
    bindings: list[tuple[Path, str, str]] = [(SPEC, sha256(SPEC), "freeze spec")]
    for role, item in public.items():
        path = (
            repo_path(item["path"], item["path"], role)
            if role == "annotation_schema"
            else Path(item["path"])
        )
        verify_hash(path, item["sha256"], role)
        bindings.append((path, item["sha256"], role))
    for item in spec["primary_annotation_segments"]:
        path = repo_path(item["path"], item["path"], item["segment_id"])
        verify_hash(path, item["sha256"], item["segment_id"])
        bindings.append((path, item["sha256"], item["segment_id"]))
    reliability_item = spec["axis_reliability_decision"]
    reliability_path = repo_path(
        reliability_item["path"], RELIABILITY_REL, "axis reliability decision"
    )
    verify_hash(reliability_path, reliability_item["sha256"], "axis reliability decision")
    bindings.extend(
        [
            (reliability_path, reliability_item["sha256"], "axis reliability decision"),
            (Path(__file__), spec["finalizer"]["sha256"], "finalizer"),
        ]
    )

    validate_schema(
        repo_path(
            public["annotation_schema"]["path"], EXPECTED_PUBLIC["annotation_schema"], "schema"
        )
    )
    blind_rows = validate_corpus(public)
    annotations, sources = load_annotations(spec)
    reliability = validate_reliability(reliability_path)
    ledger = [
        {**blind, **annotation} for blind, annotation in zip(blind_rows, annotations, strict=True)
    ]
    if any(set(row) != set(LEDGER_FIELDS) for row in ledger):
        raise FreezeError("ledger field contract drift")

    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FreezeError(f"refusing to overwrite frozen Phase-1 output: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v36_phase1_review.staging.", dir=OUTPUT.parent))
    try:
        ledger_path = staging / "phase1_annotation_ledger.csv"
        with ledger_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows({field: row[field] for field in LEDGER_FIELDS} for row in ledger)
        manifest = {
            "experiment": EXPERIMENT,
            "stage": "PHASE1_ANONYMOUS_SIGNAL_TIME_ANNOTATIONS_FROZEN",
            "status": "FROZEN_OUTCOME_BLIND",
            "events": EXPECTED_EVENTS,
            "coverage_exactly_once": True,
            "deterministic_sort": "chart_number ascending, exactly 1..531",
            "freeze_spec": {"path": SPEC_REL, "sha256": sha256(SPEC)},
            "finalizer": {"path": FINALIZER_REL, "sha256": sha256(Path(__file__))},
            "public_anonymous_corpus": {
                "chart_corpus_manifest": public["chart_corpus_manifest"],
                "blind_index": public["blind_index"],
                "contact_sheet_placements": public["contact_sheet_placements"],
                "annotation_schema": public["annotation_schema"],
                "window_relative_global_sessions": [-126, 0],
                "maximum_source_date": "2020-12-31",
            },
            "primary_annotation_segments": sources,
            "axis_reliability_decision": reliability_item,
            "eligible_discovery_prompt_axes": reliability["eligible_discovery_prompt_axes"],
            "descriptive_only_axes": reliability["descriptive_only_axes"],
            "ledger": {
                "file": ledger_path.name,
                "sha256": sha256(ledger_path),
                "rows": EXPECTED_EVENTS,
                "columns": list(LEDGER_FIELDS),
            },
            "descriptive_label_statistics": label_statistics(ledger),
            "phase2_constraints": spec["phase2_constraints"],
            "governance": {
                "identity_mapping_read": False,
                "identity_crosswalk_read": False,
                "stage_b_path_declared": False,
                "stage_b_artifact_statted_hashed_opened_or_parsed": False,
                "outcomes_read": False,
                "post_signal_rows_read": False,
                "post_2020_rows_read": False,
                "returns_aggregated": False,
                "rule_aggregation_performed": False,
                "labels_modified_by_finalizer": False,
                "signal_candle_rule_use_permitted": False,
                "turnover_state_rule_use_permitted": False,
            },
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for path, expected, label in bindings:
            verify_hash(path, expected, f"{label} changed during finalization")
        atomic_publish_no_replace(staging, OUTPUT)
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
