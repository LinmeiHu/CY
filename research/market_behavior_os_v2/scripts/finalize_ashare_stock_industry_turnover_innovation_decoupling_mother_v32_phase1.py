#!/usr/bin/env python3
"""Merge and freeze only anonymous V32 Phase-1 signal-time annotations.

The only research-data input is the public anonymous ``blind_index.csv``.
Annotation inputs contain an opaque chart number, five boolean morphology
labels, short signal-time evidence, and a reviewer.  This module has no path,
schema, or loader for event identities, Stage-B results, future paths, or
outcomes.
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
SCHEMA = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-V32_phase1_anonymous_annotation_schema.json"
)
EXPECTED_SCHEMA_SHA256 = "0b2aa65e71d460439149e80538d0d317bcce8b6f1d2c43a4168c928321402c43"
OUTPUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_stock_industry_turnover_innovation_decoupling_mother_v32/"
    "stage_d_phase1_anonymous_review"
)

EXPECTED_EVENTS = 1_781
CHARTS_PER_SHEET = 25
EXPECTED_SHEETS = 72
MAX_EVIDENCE_CHARS = 240
MAX_REVIEWER_CHARS = 80
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")

PUBLIC_INDEX_COLUMNS = (
    "chart_number",
    "blind_chart_id",
    "blind_chart_path",
    "blind_chart_sha256",
    "sheet_number",
    "slot",
)
LABELS = (
    "BASE_COMPRESSION",
    "ORDERLY_PRICE_DISCOVERY",
    "HIGH_TURNOVER_LOW_PRICE_DISPLACEMENT",
    "MATURE_EXTENSION_OR_TERMINAL_SPIKE",
    "DOWNTREND_OR_BREAKDOWN",
)
ANNOTATION_FIELDS = ("chart_number", *LABELS, "evidence", "reviewer")
LEDGER_FIELDS = (
    *PUBLIC_INDEX_COLUMNS,
    *LABELS,
    "NONE_CLEAR",
    "evidence",
    "reviewer",
)


class FreezeError(RuntimeError):
    """Fail closed on anonymous-input, annotation, or publication drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha256(value: str, label: str) -> str:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise FreezeError(f"{label} is not one lowercase SHA-256 digest")
    return value


def parse_positive_integer(value: Any, label: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise FreezeError(f"{label} is not a canonical positive integer: {value!r}")
    return int(value)


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
        raise FreezeError(f"cannot read annotation JSON {path}: {exc}") from exc


def validate_short_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise FreezeError(f"{label} must be a string")
    if value != value.strip() or not value or len(value) > maximum:
        raise FreezeError(f"{label} must be nonempty, trimmed, and <= {maximum} characters")
    if "\n" in value or "\r" in value or any(ord(character) < 32 for character in value):
        raise FreezeError(f"{label} must be one printable line")
    return value


def load_blind_index(path: Path, expected_sha256: str) -> tuple[list[dict[str, Any]], str]:
    expected_sha256 = require_sha256(expected_sha256, "blind-index hash")
    if not path.is_file() or path.name != "blind_index.csv":
        raise FreezeError(f"public input must be a file named blind_index.csv: {path}")
    actual_sha256 = sha256(path)
    if actual_sha256 != expected_sha256:
        raise FreezeError(
            f"blind-index hash drift: {actual_sha256} != {expected_sha256}"
        )

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PUBLIC_INDEX_COLUMNS:
            raise FreezeError(
                "blind_index.csv must contain exactly these ordered anonymous columns: "
                f"{PUBLIC_INDEX_COLUMNS}"
            )
        for line_number, raw in enumerate(reader, start=2):
            if None in raw or any(value is None for value in raw.values()):
                raise FreezeError(f"malformed blind-index row at line {line_number}")
            chart_number = parse_positive_integer(
                raw["chart_number"], f"blind-index line {line_number} chart_number"
            )
            sheet_number = parse_positive_integer(
                raw["sheet_number"], f"blind-index line {line_number} sheet_number"
            )
            slot = parse_positive_integer(raw["slot"], f"blind-index line {line_number} slot")
            blind_chart_id = raw["blind_chart_id"]
            if OPAQUE_ID_PATTERN.fullmatch(blind_chart_id) is None:
                raise FreezeError(f"non-opaque blind_chart_id at line {line_number}")
            blind_chart_path = raw["blind_chart_path"]
            parsed_path = PurePosixPath(blind_chart_path)
            if (
                parsed_path.is_absolute()
                or ".." in parsed_path.parts
                or parsed_path.name != f"{blind_chart_id}.png"
            ):
                raise FreezeError(
                    "blind chart path must be a relative <blind_chart_id>.png "
                    f"at line {line_number}"
                )
            blind_chart_sha256 = require_sha256(
                raw["blind_chart_sha256"], f"blind-index line {line_number} chart hash"
            )
            rows.append(
                {
                    "chart_number": chart_number,
                    "blind_chart_id": blind_chart_id,
                    "blind_chart_path": blind_chart_path,
                    "blind_chart_sha256": blind_chart_sha256,
                    "sheet_number": sheet_number,
                    "slot": slot,
                }
            )

    expected_numbers = list(range(1, EXPECTED_EVENTS + 1))
    actual_numbers = sorted(row["chart_number"] for row in rows)
    if len(rows) != EXPECTED_EVENTS or actual_numbers != expected_numbers:
        raise FreezeError("blind-index chart_number coverage is not exactly 1..1781")
    if len({row["blind_chart_id"] for row in rows}) != EXPECTED_EVENTS:
        raise FreezeError("blind-index opaque chart IDs are not unique")
    if len({row["blind_chart_path"] for row in rows}) != EXPECTED_EVENTS:
        raise FreezeError("blind-index chart paths are not unique")
    if len({(row["sheet_number"], row["slot"]) for row in rows}) != EXPECTED_EVENTS:
        raise FreezeError("blind-index sheet/slot placements are not unique")
    for row in rows:
        expected_sheet = (row["chart_number"] - 1) // CHARTS_PER_SHEET + 1
        expected_slot = (row["chart_number"] - 1) % CHARTS_PER_SHEET + 1
        if row["sheet_number"] != expected_sheet or row["slot"] != expected_slot:
            raise FreezeError(
                f"noncanonical sheet/slot placement for chart {row['chart_number']}"
            )
    if max(row["sheet_number"] for row in rows) != EXPECTED_SHEETS:
        raise FreezeError("blind-index sheet coverage is not exactly 72 pages")
    return sorted(rows, key=lambda row: row["chart_number"]), actual_sha256


def load_annotations(paths: list[Path]) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    if not paths:
        raise FreezeError("at least one annotation JSON file is required")
    resolved = [path.resolve() for path in paths]
    if len(set(resolved)) != len(resolved):
        raise FreezeError("the same annotation file was supplied more than once")

    annotations: dict[int, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for path in sorted(paths, key=lambda item: str(item.resolve())):
        if not path.is_file() or path.suffix.lower() != ".json":
            raise FreezeError(f"annotation input is not one JSON file: {path}")
        source_sha256 = sha256(path)
        raw = strict_json(path)
        if not isinstance(raw, list) or not raw:
            raise FreezeError(f"annotation file must be one nonempty JSON array: {path}")
        source_rows = 0
        for position, item in enumerate(raw, start=1):
            if not isinstance(item, dict) or set(item) != set(ANNOTATION_FIELDS):
                raise FreezeError(
                    f"annotation {path}:{position} must contain exactly {ANNOTATION_FIELDS}"
                )
            chart_number = item["chart_number"]
            if type(chart_number) is not int or not 1 <= chart_number <= EXPECTED_EVENTS:
                raise FreezeError(f"invalid chart_number at {path}:{position}")
            if chart_number in annotations:
                raise FreezeError(f"chart_number {chart_number} was annotated more than once")
            labels: dict[str, bool] = {}
            for label in LABELS:
                value = item[label]
                if type(value) is not bool:
                    raise FreezeError(f"{path}:{position} {label} must be a JSON boolean")
                labels[label] = value
            evidence = validate_short_text(
                item["evidence"], f"{path}:{position} evidence", MAX_EVIDENCE_CHARS
            )
            reviewer = validate_short_text(
                item["reviewer"], f"{path}:{position} reviewer", MAX_REVIEWER_CHARS
            )
            annotations[chart_number] = {
                "chart_number": chart_number,
                **labels,
                "NONE_CLEAR": not any(labels.values()),
                "evidence": evidence,
                "reviewer": reviewer,
            }
            source_rows += 1
        sources.append(
            {
                "path": str(path.resolve()),
                "sha256": source_sha256,
                "rows": source_rows,
            }
        )

    expected_numbers = set(range(1, EXPECTED_EVENTS + 1))
    actual_numbers = set(annotations)
    if actual_numbers != expected_numbers:
        raise FreezeError(
            "annotation coverage drift: "
            f"missing={sorted(expected_numbers - actual_numbers)[:20]}, "
            f"extra={sorted(actual_numbers - expected_numbers)[:20]}"
        )
    return annotations, sources


def build_ledger(
    blind_rows: list[dict[str, Any]], annotations: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    ledger = [
        {**blind_row, **annotations[blind_row["chart_number"]]}
        for blind_row in blind_rows
    ]
    ledger.sort(key=lambda row: row["chart_number"])
    if [row["chart_number"] for row in ledger] != list(range(1, EXPECTED_EVENTS + 1)):
        raise FreezeError("final ledger is not deterministically sorted 1..1781")
    for row in ledger:
        expected_none_clear = not any(row[label] for label in LABELS)
        if row["NONE_CLEAR"] is not expected_none_clear:
            raise FreezeError(f"NONE_CLEAR derivation drift for chart {row['chart_number']}")
    return ledger


def write_ledger(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            serialized = dict(row)
            for label in (*LABELS, "NONE_CLEAR"):
                serialized[label] = "true" if row[label] else "false"
            writer.writerow({field: serialized[field] for field in LEDGER_FIELDS})


def verify_unchanged(
    blind_index: Path,
    blind_index_sha256: str,
    annotation_sources: list[dict[str, Any]],
) -> None:
    if sha256(SCHEMA) != EXPECTED_SCHEMA_SHA256:
        raise FreezeError("annotation schema changed during finalization")
    if sha256(blind_index) != blind_index_sha256:
        raise FreezeError("blind index changed during finalization")
    for source in annotation_sources:
        if sha256(Path(source["path"])) != source["sha256"]:
            raise FreezeError(f"annotation changed during finalization: {source['path']}")


def finalize(
    blind_index: Path,
    expected_blind_index_sha256: str,
    paths: list[Path],
) -> dict[str, Any]:
    if sha256(SCHEMA) != EXPECTED_SCHEMA_SHA256:
        raise FreezeError("V32 anonymous annotation schema identity drift")
    blind_rows, blind_index_sha256 = load_blind_index(
        blind_index, expected_blind_index_sha256
    )
    annotations, annotation_sources = load_annotations(paths)
    ledger = build_ledger(blind_rows, annotations)

    if OUTPUT.exists():
        raise FreezeError(f"refusing to overwrite frozen Phase-1 output: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".v32_phase1_review.staging.", dir=OUTPUT.parent))
    try:
        ledger_path = staging / "phase1_annotation_ledger.csv"
        manifest_path = staging / "manifest.json"
        write_ledger(ledger, ledger_path)
        label_counts = {label: sum(bool(row[label]) for row in ledger) for label in LABELS}
        manifest = {
            "experiment": EXPERIMENT,
            "stage": "PHASE1_ANONYMOUS_SIGNAL_TIME_ANNOTATIONS_FROZEN",
            "events": EXPECTED_EVENTS,
            "coverage_exactly_once": True,
            "deterministic_sort": "chart_number ascending, exactly 1..1781",
            "public_blind_index": {
                "path": str(blind_index.resolve()),
                "sha256": blind_index_sha256,
                "columns": list(PUBLIC_INDEX_COLUMNS),
            },
            "annotation_schema": {
                "path": str(SCHEMA.resolve()),
                "sha256": EXPECTED_SCHEMA_SHA256,
            },
            "finalizer": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256(Path(__file__).resolve()),
            },
            "annotation_sources": annotation_sources,
            "labels": list(LABELS),
            "labels_are_nonexclusive": True,
            "none_clear_derivation": "true if and only if all five labels are false",
            "label_counts": label_counts,
            "none_clear_count": sum(bool(row["NONE_CLEAR"]) for row in ledger),
            "evidence_max_characters": MAX_EVIDENCE_CHARS,
            "ledger_file": ledger_path.name,
            "ledger_sha256": sha256(ledger_path),
            "identity_mapping_read": False,
            "stage_b_result_read": False,
            "future_paths_read": False,
            "outcomes_read": False,
            "returns_aggregated": False,
            "post_signal_used_as_predictor": False,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify_unchanged(blind_index, blind_index_sha256, annotation_sources)
        if OUTPUT.exists():
            raise FreezeError(f"Phase-1 output appeared during construction: {OUTPUT}")
        staging.rename(OUTPUT)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    result = {
        "output": str(OUTPUT),
        "events": EXPECTED_EVENTS,
        "ledger_sha256": manifest["ledger_sha256"],
        "manifest_sha256": sha256(OUTPUT / "manifest.json"),
        "outcomes_read": False,
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blind-index", required=True, type=Path)
    parser.add_argument("--blind-index-sha256", required=True)
    parser.add_argument("annotations", nargs="+", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = finalize(args.blind_index, args.blind_index_sha256, args.annotations)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
