#!/usr/bin/env python3
"""Freeze V31 Phase-2 visual outcome attribution without testing any rule.

This publisher consumes only frozen chart metadata, the immutable Phase-1
signal-time ledger, and human Phase-2 annotations.  It never opens Stage-B
returns/outcomes or decodes charts.  Outcome buckets come exclusively from the
already-frozen Stage-C placement/template metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

EXPERIMENT = "ASHARE-INDUSTRY-RESIDUAL-SERIAL-PHASE-CHANGE-MOTHER-V31"
REPO = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO / "research/market_behavior_os_v2/experiments"
EXTERNAL_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_industry_residual_serial_phase_change_mother_v31"
)
CHART_ROOT = EXTERNAL_ROOT / "stage_c_charts"
PHASE1_ROOT = EXTERNAL_ROOT / "stage_d_phase1_chronology_review"
OUTPUT = EXTERNAL_ROOT / "stage_d_phase2_outcome_review"

EXPECTED_EVENTS = 1_602
EXPECTED_OUTCOME_SHEETS = 66
EXPECTED_BUCKET_COUNTS = {
    "PROFIT_GE_4PCT": 815,
    "PROFIT_0_TO_4PCT": 113,
    "LOSS_0_TO_10PCT": 421,
    "SEVERE_LOSS": 245,
    "NO_COMPLETED_TRADE": 8,
}
EXPECTED_BUCKET_SHEETS = {
    "PROFIT_GE_4PCT": 33,
    "PROFIT_0_TO_4PCT": 5,
    "LOSS_0_TO_10PCT": 17,
    "SEVERE_LOSS": 10,
    "NO_COMPLETED_TRADE": 1,
}
BUCKETS = tuple(EXPECTED_BUCKET_COUNTS)
PHASE1_CATEGORIES = (
    "BASE_OR_COMPRESSION",
    "ORDERLY_ADVANCE",
    "MATURE_EXTENDED_HIGH",
    "VOLATILE_TOPPING",
    "DOWNTREND_OR_REPAIR",
    "STRUCTURAL_BREAKDOWN",
    "NONE_CLEAR",
)
PROFIT_PATH_LABELS = (
    "FAST_ACCEPTANCE",
    "SLOW_ACCEPTANCE",
    "CHOP_THEN_ACCEPTANCE",
    "OTHER_WIN_PATH",
)
LOSS_PATH_LABELS = (
    "EARLY_REJECTION",
    "LATE_REJECTION",
    "CHOP_THEN_LOSS",
    "OTHER_LOSS_PATH",
)
NO_INDIVIDUAL_PATH_LABEL = "NOT_INDIVIDUALLY_CODED_IN_PHASE2_ANNOTATION"

STAGE_C_MANIFEST = CHART_ROOT / "manifest.json"
OUTCOME_TEMPLATE = CHART_ROOT / "outcome_review_template.csv"
PLACEMENTS = CHART_ROOT / "contact_sheet_placements.csv"
SHEET_INDEX = CHART_ROOT / "contact_sheet_index.csv"
PHASE1_MANIFEST = PHASE1_ROOT / "manifest.json"
PHASE1_LEDGER_CSV = PHASE1_ROOT / "chronology_review_ledger.csv"
PHASE1_LEDGER_PARQUET = PHASE1_ROOT / "chronology_review_ledger.parquet"

PROFIT_1 = EXPERIMENTS / "ASHARE-V31_phase2_annotations_profit_ge4_0001_0016.json"
PROFIT_2 = EXPERIMENTS / "ASHARE-V31_phase2_annotations_profit_ge4_0017_0033.json"
LOSS = EXPERIMENTS / "ASHARE-V31_phase2_annotations_loss_0001_0017.json"
ROOT_OUTCOMES = EXPERIMENTS / "ASHARE-V31_phase2_annotations_root_outcomes.json"

INPUTS = {
    "stage_c_manifest": (
        STAGE_C_MANIFEST,
        "b8dd9ef51a1dec86205a9ce856cfafe87cd650b54835cf1f2943fbcf30624c25",
    ),
    "outcome_review_template": (
        OUTCOME_TEMPLATE,
        "4178d89667622ebd9c89abed57ca4df35267130793490bcecc7cfebb591d56e2",
    ),
    "contact_sheet_placements": (
        PLACEMENTS,
        "c7f8e9339241cbbd74c746009e2086411b8a935c67f7e8263d61a115581d06df",
    ),
    "contact_sheet_index": (
        SHEET_INDEX,
        "b8cd98cca7e14a2480afb4103ffa53100928d4bc961cdc283052ddb29e1ebfd1",
    ),
    "phase1_manifest": (
        PHASE1_MANIFEST,
        "453e3268ca0dc979064772575eec6f6f974fc657fcc81396f966c9455cd7d40a",
    ),
    "phase1_ledger_csv": (
        PHASE1_LEDGER_CSV,
        "6cde4b72b3b7016d9be7a1a47fed40f7a0de5c4fb5ca2297e5bc6cccfe7081ff",
    ),
    "phase1_ledger_parquet": (
        PHASE1_LEDGER_PARQUET,
        "4d9830ee2e799840dcf44b49c8dd202da9c4d05df97413fd876ec89809abafd4",
    ),
    "phase2_profit_ge4_0001_0016": (
        PROFIT_1,
        "07c4eab5a7df5103ff765faeefae210a123830be5b119b2375a72db8229d4da6",
    ),
    "phase2_profit_ge4_0017_0033": (
        PROFIT_2,
        "6edd25e8188b8144c8f6600bed1052ed05f0c94f34fe9058ea92b323f4429593",
    ),
    "phase2_loss_0001_0017": (
        LOSS,
        "66fead7840f8aa07a4c3abef3772ca1980130b3abfc0a943661167ed321d6440",
    ),
    "phase2_root_outcomes": (
        ROOT_OUTCOMES,
        "dd223120266abf708f94b6c0f3b9b26f39b1b6aceb79c14cdefa18a15ab67b7d",
    ),
}

OUTCOME_TEMPLATE_COLUMNS = (
    "event_id",
    "chart_number",
    "outcome_bucket",
    "outcome_group_reviewed",
    "post_signal_attribution",
    "profit_loss_group_observation",
    "counterexample_flag",
    "counterexample_to_motif_ids",
    "outcome_reviewer",
    "reviewer_notes",
    "post_signal_used_as_predictor",
)
PLACEMENT_COLUMNS = (
    "collection",
    "sheet_path",
    "sheet_number",
    "slot",
    "event_id",
    "chart_number",
    "outcome_bucket",
)
SHEET_INDEX_COLUMNS = (
    "collection",
    "sheet_path",
    "sheet_number",
    "charts",
    "first_chart",
    "last_chart",
    "sheet_sha256",
)
PHASE1_COLUMNS = (
    "event_id",
    "chart_number",
    "symbol",
    "signal_date",
    "causal_industry",
    "chronology_sheet",
    "slot",
    "chronology_reviewed",
    "signal_time_trend_structure",
    "signal_time_level_location",
    "signal_time_turnover_structure",
    "signal_candle_structure",
    "signal_time_pattern_note",
    "chronology_reviewer",
    "post_signal_used_as_predictor",
)

SOURCE_REVIEWERS = {
    PROFIT_1.name: "blind_reviewer_James",
    PROFIT_2.name: "blind_reviewer_Avicenna",
    LOSS.name: "blind_reviewer_Tesla",
    ROOT_OUTCOMES.name: "primary_reviewer",
}


class FreezeError(RuntimeError):
    """Raised when a frozen input, review boundary, or coverage contract drifts."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FreezeError(f"{label} must be a JSON object")
    return value


def verify_inputs() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for role, (path, expected) in INPUTS.items():
        if not path.is_file():
            raise FreezeError(f"missing bound input {role}: {path}")
        actual = sha256(path)
        if actual != expected:
            raise FreezeError(f"input drift for {role}: {actual} != {expected}")
        hashes[role] = actual
    return hashes


def validate_manifests(hashes: dict[str, str]) -> None:
    stage_c = load_json(STAGE_C_MANIFEST, "Stage-C manifest")
    if (
        stage_c.get("experiment") != EXPERIMENT
        or stage_c.get("events") != EXPECTED_EVENTS
        or stage_c.get("outcome_contact_sheets") != EXPECTED_OUTCOME_SHEETS
        or stage_c.get("outcome_group_coverage_exactly_once") is not True
        or stage_c.get("outcome_bucket_counts") != EXPECTED_BUCKET_COUNTS
        or stage_c.get("outcome_review_template_sha256")
        != hashes["outcome_review_template"]
        or stage_c.get("contact_sheet_placements_sha256")
        != hashes["contact_sheet_placements"]
        or stage_c.get("contact_sheet_index_sha256") != hashes["contact_sheet_index"]
        or stage_c.get("outcome_attachment_performed") is not False
        or stage_c.get("candidate_reselection_performed") is not False
        or stage_c.get("rule_aggregation_performed") is not False
        or stage_c.get("rule_search_performed") is not False
        or stage_c.get("portfolio_replay_performed") is not False
        or stage_c.get("post_signal_used_as_predictor") is not False
        or stage_c.get("post_2020_row_read") is not False
    ):
        raise FreezeError("Stage-C manifest semantics drift")

    phase1 = load_json(PHASE1_MANIFEST, "Phase-1 manifest")
    if (
        phase1.get("experiment") != EXPERIMENT
        or phase1.get("stage") != "PHASE1_OUTCOME_BLIND_CHRONOLOGY_REVIEW_FROZEN"
        or phase1.get("events") != EXPECTED_EVENTS
        or phase1.get("chronology_sheets") != 65
        or phase1.get("coverage_exactly_once") is not True
        or phase1.get("outcome_sheets_opened_before_freeze") is not False
        or phase1.get("post_signal_used_as_predictor") is not False
        or phase1.get("chronology_review_ledger_csv_sha256")
        != hashes["phase1_ledger_csv"]
        or phase1.get("chronology_review_ledger_parquet_sha256")
        != hashes["phase1_ledger_parquet"]
        or phase1.get("next_step")
        != "PHASE2_OUTCOME_ATTRIBUTION_ONLY_PHASE1_IMMUTABLE"
    ):
        raise FreezeError("Phase-1 manifest semantics drift")


def validate_stage_c_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    template = pd.read_csv(OUTCOME_TEMPLATE)
    placements = pd.read_csv(PLACEMENTS)
    sheet_index = pd.read_csv(SHEET_INDEX)
    if tuple(template.columns) != OUTCOME_TEMPLATE_COLUMNS:
        raise FreezeError("outcome-review template schema drift")
    if tuple(placements.columns) != PLACEMENT_COLUMNS:
        raise FreezeError("contact-sheet placement schema drift")
    if tuple(sheet_index.columns) != SHEET_INDEX_COLUMNS:
        raise FreezeError("contact-sheet index schema drift")
    if len(template) != EXPECTED_EVENTS:
        raise FreezeError("outcome-review template event count drift")
    if template["event_id"].duplicated().any() or template["chart_number"].duplicated().any():
        raise FreezeError("outcome-review template is not one row per event/chart")
    if template["outcome_group_reviewed"].astype(bool).any():
        raise FreezeError("Stage-C template was populated before Phase-2 freeze")
    if template["post_signal_used_as_predictor"].astype(bool).any():
        raise FreezeError("Stage-C template permits post-signal prediction")
    placeholder_columns = (
        "post_signal_attribution",
        "profit_loss_group_observation",
        "counterexample_flag",
        "counterexample_to_motif_ids",
        "outcome_reviewer",
        "reviewer_notes",
    )
    if template[list(placeholder_columns)].notna().any().any():
        raise FreezeError("Stage-C outcome-review placeholders are no longer empty")

    grouped = placements.loc[placements["collection"] == "outcome_group"].copy()
    sheets = sheet_index.loc[sheet_index["collection"] == "outcome_group"].copy()
    if len(grouped) != EXPECTED_EVENTS or len(sheets) != EXPECTED_OUTCOME_SHEETS:
        raise FreezeError("Stage-C outcome placement/sheet count drift")
    if grouped["event_id"].duplicated().any() or grouped["chart_number"].duplicated().any():
        raise FreezeError("Stage-C outcome placement does not cover events exactly once")
    observed_counts = grouped["outcome_bucket"].value_counts().to_dict()
    if observed_counts != EXPECTED_BUCKET_COUNTS:
        raise FreezeError(f"outcome bucket count drift: {observed_counts}")
    observed_pages = (
        grouped[["outcome_bucket", "sheet_number"]].drop_duplicates().groupby(
            "outcome_bucket"
        )["sheet_number"].count()
    )
    if observed_pages.to_dict() != EXPECTED_BUCKET_SHEETS:
        raise FreezeError(f"outcome sheet-count drift: {observed_pages.to_dict()}")

    expected_page_keys = {
        (bucket, sheet)
        for bucket, sheet_count in EXPECTED_BUCKET_SHEETS.items()
        for sheet in range(1, sheet_count + 1)
    }
    actual_page_keys = set(
        grouped[["outcome_bucket", "sheet_number"]].itertuples(index=False, name=None)
    )
    if actual_page_keys != expected_page_keys:
        raise FreezeError("outcome sheet numbering is not contiguous within each bucket")
    if sheets["sheet_path"].duplicated().any():
        raise FreezeError("duplicate outcome sheet in Stage-C index")

    indexed_by_path = sheets.set_index("sheet_path", verify_integrity=True)
    if set(grouped["sheet_path"]) != set(indexed_by_path.index):
        raise FreezeError("placement/index outcome-sheet set mismatch")
    outcome_root = (CHART_ROOT / "outcome_sheets").resolve()
    for sheet_path, page in grouped.groupby("sheet_path", sort=True):
        page = page.sort_values("slot")
        if page["outcome_bucket"].nunique() != 1 or page["sheet_number"].nunique() != 1:
            raise FreezeError(f"mixed bucket or sheet number in {sheet_path}")
        if page["slot"].astype(int).tolist() != list(range(1, len(page) + 1)):
            raise FreezeError(f"non-contiguous slots in {sheet_path}")
        row = indexed_by_path.loc[sheet_path]
        if (
            int(row["sheet_number"]) != int(page["sheet_number"].iloc[0])
            or int(row["charts"]) != len(page)
            or int(row["first_chart"]) != int(page["chart_number"].min())
            or int(row["last_chart"]) != int(page["chart_number"].max())
        ):
            raise FreezeError(f"placement/index metadata mismatch for {sheet_path}")
        image_path = Path(sheet_path).resolve()
        if not image_path.is_relative_to(outcome_root):
            raise FreezeError(f"outcome sheet escapes frozen Stage-C root: {image_path}")
        if not image_path.is_file() or sha256(image_path) != str(row["sheet_sha256"]):
            raise FreezeError(f"outcome sheet hash drift: {image_path}")

    template_keys = template[["event_id", "chart_number", "outcome_bucket"]].sort_values(
        "chart_number"
    )
    placement_keys = grouped[["event_id", "chart_number", "outcome_bucket"]].sort_values(
        "chart_number"
    )
    pd.testing.assert_frame_equal(
        template_keys.reset_index(drop=True),
        placement_keys.reset_index(drop=True),
        check_dtype=False,
    )
    return template, grouped


def load_phase1_ledger(template: pd.DataFrame) -> pd.DataFrame:
    phase1_csv = pd.read_csv(PHASE1_LEDGER_CSV)
    phase1 = pd.read_parquet(PHASE1_LEDGER_PARQUET)
    if tuple(phase1.columns) != PHASE1_COLUMNS or tuple(phase1_csv.columns) != PHASE1_COLUMNS:
        raise FreezeError("Phase-1 ledger schema drift")
    pd.testing.assert_frame_equal(phase1_csv, phase1, check_dtype=False)
    if len(phase1) != EXPECTED_EVENTS:
        raise FreezeError("Phase-1 event count drift")
    if phase1["event_id"].duplicated().any() or phase1["chart_number"].duplicated().any():
        raise FreezeError("Phase-1 ledger is not one row per event/chart")
    if not phase1["chronology_reviewed"].astype(bool).all():
        raise FreezeError("Phase-1 contains an unreviewed chronology row")
    if phase1["post_signal_used_as_predictor"].astype(bool).any():
        raise FreezeError("Phase-1 contains post-signal predictor use")
    if not set(phase1["signal_time_trend_structure"]).issubset(PHASE1_CATEGORIES):
        raise FreezeError("Phase-1 trend taxonomy drift")
    if phase1[list(PHASE1_COLUMNS)].isna().any().any():
        raise FreezeError("Phase-1 immutable ledger contains missing values")
    phase1_keys = phase1[["event_id", "chart_number"]].sort_values("chart_number")
    template_keys = template[["event_id", "chart_number"]].sort_values("chart_number")
    pd.testing.assert_frame_equal(
        phase1_keys.reset_index(drop=True),
        template_keys.reset_index(drop=True),
        check_dtype=False,
    )
    return phase1.sort_values("chart_number").reset_index(drop=True)


def original_resolution_certified(raw: dict[str, Any], label: str) -> None:
    certification = raw.get("original_resolution_certification")
    if not isinstance(certification, dict):
        raise FreezeError(f"missing original-resolution certification in {label}")
    detail = certification.get("view_image_detail", certification.get("view_detail"))
    reviewed = certification.get(
        "every_occupied_cell_viewed",
        certification.get("all_occupied_cells_viewed"),
    )
    rules = certification.get(
        "rules_extracted_or_tested",
        certification.get("rules_derived_or_tested"),
    )
    if (
        detail != "original"
        or reviewed is not True
        or certification.get("phase1_labels_modified") is not False
        or rules is not False
    ):
        raise FreezeError(f"visual-review certification drift in {label}")


def counterexample_notes(
    values: Any, occupied: list[int], source: str, sheet_key: str
) -> dict[int, str]:
    if not isinstance(values, list):
        raise FreezeError(f"counterexamples must be a list: {source}:{sheet_key}")
    occupied_set = set(occupied)
    notes: defaultdict[int, list[str]] = defaultdict(list)
    for value in values:
        if isinstance(value, dict):
            if set(value) != {"chart_number", "note"}:
                raise FreezeError(f"counterexample schema drift: {source}:{sheet_key}")
            chart_numbers = [int(value["chart_number"])]
            note = str(value["note"])
        elif isinstance(value, str):
            note = value
            chart_numbers = sorted(
                {int(token) for token in re.findall(r"\d+", value)}.intersection(occupied_set)
            )
        else:
            raise FreezeError(f"invalid counterexample: {source}:{sheet_key}")
        for chart_number in chart_numbers:
            if chart_number not in occupied_set:
                raise FreezeError(
                    f"counterexample chart not on page: {source}:{sheet_key}:{chart_number}"
                )
            notes[chart_number].append(note)
    return {
        chart_number: " | ".join(dict.fromkeys(chart_notes))
        for chart_number, chart_notes in notes.items()
    }


def add_annotated_page(
    *,
    records: list[dict[str, Any]],
    page_records: list[dict[str, Any]],
    seen_pages: set[tuple[str, int]],
    placement_pages: dict[tuple[str, int], pd.DataFrame],
    bucket: str,
    sheet_key: str,
    occupied_values: Any,
    path_values: dict[str, Any] | None,
    path_labels: tuple[str, ...] | None,
    counterexamples: Any,
    pre_shape_note: str,
    page_summary: str,
    reviewer: str,
    source: Path,
) -> None:
    sheet_number = int(sheet_key)
    page_key = (bucket, sheet_number)
    if page_key in seen_pages:
        raise FreezeError(f"duplicate Phase-2 page annotation: {page_key}")
    if page_key not in placement_pages:
        raise FreezeError(f"annotation page absent from placements: {page_key}")
    page = placement_pages[page_key]
    expected_numbers = page["chart_number"].astype(int).tolist()
    if not isinstance(occupied_values, list):
        raise FreezeError(f"occupied charts must be a list: {source.name}:{sheet_key}")
    occupied = [int(value) for value in occupied_values]
    if occupied != expected_numbers:
        raise FreezeError(
            f"annotation/placement chart drift: {source.name}:{sheet_key}: "
            f"expected={expected_numbers}, actual={occupied}"
        )
    if len(occupied) != len(set(occupied)):
        raise FreezeError(f"duplicate occupied chart: {source.name}:{sheet_key}")

    label_by_chart: dict[int, str] = {}
    if path_labels is not None:
        if not isinstance(path_values, dict) or set(path_values) != set(path_labels):
            raise FreezeError(f"path-label schema drift: {source.name}:{sheet_key}")
        for path_label in path_labels:
            values = path_values[path_label]
            if not isinstance(values, list):
                raise FreezeError(f"path label is not a list: {source.name}:{sheet_key}")
            for value in values:
                chart_number = int(value)
                if chart_number in label_by_chart:
                    raise FreezeError(
                        f"duplicate path label for chart {chart_number}: {source.name}:{sheet_key}"
                    )
                label_by_chart[chart_number] = path_label
        if set(label_by_chart) != set(occupied):
            raise FreezeError(f"path-label coverage drift: {source.name}:{sheet_key}")
    else:
        if path_values is not None:
            raise FreezeError(f"unexpected path labels: {source.name}:{sheet_key}")
        label_by_chart = {number: NO_INDIVIDUAL_PATH_LABEL for number in occupied}

    counterexample_by_chart = counterexample_notes(
        counterexamples, occupied, source.name, sheet_key
    )
    path_counts = Counter(label_by_chart.values())
    page_records.append(
        {
            "outcome_bucket": bucket,
            "outcome_sheet_number": sheet_number,
            "reviewer": reviewer,
            "annotation_source": source.name,
            "occupied_cells": len(occupied),
            "visual_path_counts": dict(sorted(path_counts.items())),
            "counterexample_cells": len(counterexample_by_chart),
            "pre_shape_note": pre_shape_note,
            "page_summary": page_summary,
        }
    )
    page_by_chart = page.set_index("chart_number", verify_integrity=True)
    for chart_number in occupied:
        placement = page_by_chart.loc[chart_number]
        note = counterexample_by_chart.get(chart_number, "")
        records.append(
            {
                "event_id": placement["event_id"],
                "chart_number": chart_number,
                "outcome_bucket": bucket,
                "outcome_sheet_number": sheet_number,
                "outcome_slot": int(placement["slot"]),
                "outcome_sheet_path": str(
                    Path(placement["sheet_path"]).resolve().relative_to(CHART_ROOT.resolve())
                ),
                "phase2_outcome_reviewed": True,
                "visual_path_label_available": path_labels is not None,
                "visual_path_label": label_by_chart[chart_number],
                "outcome_reviewer": reviewer,
                "counterexample_flag": chart_number in counterexample_by_chart,
                "counterexample_note": note,
                "phase2_pre_shape_note": pre_shape_note,
                "phase2_page_summary": page_summary,
                "phase2_annotation_source": source.name,
            }
        )
    seen_pages.add(page_key)


def page_map(raw: dict[str, Any], source: Path) -> dict[str, dict[str, Any]]:
    pages = raw.get("sheets")
    if not isinstance(pages, dict) or not all(isinstance(page, dict) for page in pages.values()):
        raise FreezeError(f"invalid sheet mapping in {source.name}")
    return pages


def validate_declared_totals(
    raw: dict[str, Any], labels: tuple[str, ...], computed: Counter[str], source: Path
) -> None:
    totals = raw.get("totals")
    if not isinstance(totals, dict):
        raise FreezeError(f"missing declared totals in {source.name}")
    for label in labels:
        if int(totals.get(label, -1)) != computed[label]:
            raise FreezeError(f"declared path total drift: {source.name}:{label}")


def load_phase2_annotations(
    placements: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    placement_pages = {
        (str(bucket), int(sheet_number)): page.sort_values("slot").reset_index(drop=True)
        for (bucket, sheet_number), page in placements.groupby(
            ["outcome_bucket", "sheet_number"], sort=True
        )
    }
    expected_pages = set(placement_pages)
    records: list[dict[str, Any]] = []
    pages_out: list[dict[str, Any]] = []
    seen_pages: set[tuple[str, int]] = set()

    profit_1 = load_json(PROFIT_1, PROFIT_1.name)
    original_resolution_certified(profit_1, PROFIT_1.name)
    profit_1_pages = page_map(profit_1, PROFIT_1)
    if (
        profit_1.get("bucket") != "PROFIT_GE_4PCT"
        or profit_1.get("reviewed_cells") != 400
        or set(profit_1_pages) != {f"{sheet:04d}" for sheet in range(1, 17)}
    ):
        raise FreezeError(f"top-level coverage drift in {PROFIT_1.name}")
    profit_1_counts: Counter[str] = Counter()
    for sheet_key, page in sorted(profit_1_pages.items()):
        paths = page.get("path_labels")
        if not isinstance(paths, dict):
            raise FreezeError(f"nested path labels missing: {PROFIT_1.name}:{sheet_key}")
        profit_1_counts.update(
            {path_label: len(paths.get(path_label, [])) for path_label in PROFIT_PATH_LABELS}
        )
        if int(page.get("occupied_count", -1)) != len(page.get("occupied_chart_numbers", [])):
            raise FreezeError(f"occupied count drift: {PROFIT_1.name}:{sheet_key}")
        pre_shape_counts = page.get("pre_shape_counts")
        if pre_shape_counts is not None and (
            not isinstance(pre_shape_counts, dict)
            or set(pre_shape_counts) != set(PHASE1_CATEGORIES)
            or sum(int(value) for value in pre_shape_counts.values())
            != int(page["occupied_count"])
        ):
            raise FreezeError(f"pre-shape count drift: {PROFIT_1.name}:{sheet_key}")
        add_annotated_page(
            records=records,
            page_records=pages_out,
            seen_pages=seen_pages,
            placement_pages=placement_pages,
            bucket="PROFIT_GE_4PCT",
            sheet_key=sheet_key,
            occupied_values=page.get("occupied_chart_numbers"),
            path_values=paths,
            path_labels=PROFIT_PATH_LABELS,
            counterexamples=page.get("counterexamples"),
            pre_shape_note=str(page.get("pre_shape_note", "")),
            page_summary=str(page.get("page_summary", "")),
            reviewer=SOURCE_REVIEWERS[PROFIT_1.name],
            source=PROFIT_1,
        )
    validate_declared_totals(profit_1, PROFIT_PATH_LABELS, profit_1_counts, PROFIT_1)

    profit_2 = load_json(PROFIT_2, PROFIT_2.name)
    original_resolution_certified(profit_2, PROFIT_2.name)
    profit_2_pages = page_map(profit_2, PROFIT_2)
    if (
        profit_2.get("bucket") != "PROFIT_GE_4PCT"
        or profit_2.get("reviewed_cells") != 415
        or set(profit_2_pages) != {f"{sheet:04d}" for sheet in range(17, 34)}
    ):
        raise FreezeError(f"top-level coverage drift in {PROFIT_2.name}")
    profit_2_counts: Counter[str] = Counter()
    for sheet_key, page in sorted(profit_2_pages.items()):
        paths = {label: page.get(label) for label in PROFIT_PATH_LABELS}
        profit_2_counts.update(
            {path_label: len(paths.get(path_label, [])) for path_label in PROFIT_PATH_LABELS}
        )
        add_annotated_page(
            records=records,
            page_records=pages_out,
            seen_pages=seen_pages,
            placement_pages=placement_pages,
            bucket="PROFIT_GE_4PCT",
            sheet_key=sheet_key,
            occupied_values=page.get("occupied_chart_numbers"),
            path_values=paths,
            path_labels=PROFIT_PATH_LABELS,
            counterexamples=page.get("counterexamples"),
            pre_shape_note=str(page.get("pre_shape_note", "")),
            page_summary=str(page.get("page_summary", "")),
            reviewer=SOURCE_REVIEWERS[PROFIT_2.name],
            source=PROFIT_2,
        )
    validate_declared_totals(profit_2, PROFIT_PATH_LABELS, profit_2_counts, PROFIT_2)

    loss = load_json(LOSS, LOSS.name)
    original_resolution_certified(loss, LOSS.name)
    loss_pages = page_map(loss, LOSS)
    if (
        str(loss.get("bucket", "")).upper() != "LOSS_0_TO_10PCT"
        or loss.get("reviewed_cells") != 421
        or set(loss.get("path_labels", [])) != set(LOSS_PATH_LABELS)
        or set(loss_pages) != {f"{sheet:04d}" for sheet in range(1, 18)}
    ):
        raise FreezeError(f"top-level coverage drift in {LOSS.name}")
    loss_counts: Counter[str] = Counter()
    for sheet_key, page in sorted(loss_pages.items()):
        paths = {label: page.get(label) for label in LOSS_PATH_LABELS}
        loss_counts.update(
            {path_label: len(paths.get(path_label, [])) for path_label in LOSS_PATH_LABELS}
        )
        add_annotated_page(
            records=records,
            page_records=pages_out,
            seen_pages=seen_pages,
            placement_pages=placement_pages,
            bucket="LOSS_0_TO_10PCT",
            sheet_key=sheet_key,
            occupied_values=page.get("occupied"),
            path_values=paths,
            path_labels=LOSS_PATH_LABELS,
            counterexamples=page.get("counterexamples"),
            pre_shape_note=str(page.get("pre_shape_note", "")),
            page_summary=str(page.get("page_summary", "")),
            reviewer=SOURCE_REVIEWERS[LOSS.name],
            source=LOSS,
        )
    validate_declared_totals(loss, LOSS_PATH_LABELS, loss_counts, LOSS)

    root = load_json(ROOT_OUTCOMES, ROOT_OUTCOMES.name)
    root_buckets = root.get("buckets")
    root_aggregate = root.get("aggregate")
    root_certification = root.get("certification")
    expected_root_buckets = {
        "PROFIT_0_TO_4PCT",
        "SEVERE_LOSS",
        "NO_COMPLETED_TRADE",
    }
    if (
        root.get("experiment") != EXPERIMENT
        or root.get("review_phase") != "PHASE2_OUTCOME_GROUP_VISUAL_ATTRIBUTION"
        or root.get("reviewer") != SOURCE_REVIEWERS[ROOT_OUTCOMES.name]
        or not isinstance(root_buckets, dict)
        or set(root_buckets) != expected_root_buckets
        or not isinstance(root_aggregate, dict)
        or root_aggregate.get("reviewed_cells") != 366
        or root_aggregate.get("reviewed_sheets") != 16
        or root_aggregate.get("rule_compression_performed") is not False
        or root_aggregate.get("phase1_labels_modified") is not False
        or root_aggregate.get("post_signal_used_as_predictor") is not False
        or not isinstance(root_certification, dict)
        or root_certification.get("original_resolution") is not True
        or root_certification.get("every_occupied_cell_reviewed") is not True
        or root_certification.get("outcome_groups_opened_only_after_phase1_freeze") is not True
    ):
        raise FreezeError(f"review-boundary semantics drift in {ROOT_OUTCOMES.name}")
    for bucket in sorted(expected_root_buckets):
        group = root_buckets[bucket]
        sheet_mapping = group.get("sheets")
        expected_keys = {
            f"{sheet:04d}" for sheet in range(1, EXPECTED_BUCKET_SHEETS[bucket] + 1)
        }
        if (
            not isinstance(sheet_mapping, dict)
            or set(sheet_mapping) != expected_keys
            or int(group.get("reviewed_cells", -1)) != EXPECTED_BUCKET_COUNTS[bucket]
        ):
            raise FreezeError(f"root annotation coverage drift for {bucket}")
        for sheet_key, occupied in sorted(sheet_mapping.items()):
            add_annotated_page(
                records=records,
                page_records=pages_out,
                seen_pages=seen_pages,
                placement_pages=placement_pages,
                bucket=bucket,
                sheet_key=sheet_key,
                occupied_values=occupied,
                path_values=None,
                path_labels=None,
                counterexamples=[],
                pre_shape_note=str(group.get("counterexample_observation", "")),
                page_summary=str(group.get("bucket_observation", "")),
                reviewer=SOURCE_REVIEWERS[ROOT_OUTCOMES.name],
                source=ROOT_OUTCOMES,
            )

    if seen_pages != expected_pages:
        missing = sorted(expected_pages - seen_pages)
        extra = sorted(seen_pages - expected_pages)
        raise FreezeError(f"Phase-2 page coverage drift: missing={missing}, extra={extra}")
    annotations = pd.DataFrame.from_records(records).sort_values("chart_number")
    annotations = annotations.reset_index(drop=True)
    if len(annotations) != EXPECTED_EVENTS:
        raise FreezeError("Phase-2 annotation event count drift")
    if annotations["event_id"].duplicated().any() or annotations["chart_number"].duplicated().any():
        raise FreezeError("Phase-2 annotations do not cover every event exactly once")
    if annotations["outcome_bucket"].value_counts().to_dict() != EXPECTED_BUCKET_COUNTS:
        raise FreezeError("Phase-2 annotation bucket count drift")
    return annotations, pages_out


def nested_counts(frame: pd.DataFrame, row: str, column: str) -> dict[str, dict[str, int]]:
    table = pd.crosstab(frame[row], frame[column])
    return {
        str(row_value): {
            str(column_value): int(table.loc[row_value, column_value])
            for column_value in table.columns
        }
        for row_value in table.index
    }


def build_review() -> tuple[pd.DataFrame, dict[str, Any], dict[str, str]]:
    source_hashes = verify_inputs()
    validate_manifests(source_hashes)
    template, placements = validate_stage_c_tables()
    phase1 = load_phase1_ledger(template)
    annotations, page_summaries = load_phase2_annotations(placements)

    review = phase1.merge(
        annotations,
        on=["event_id", "chart_number"],
        how="left",
        validate="one_to_one",
    ).sort_values("chart_number")
    review = review.reset_index(drop=True)
    if review.isna().any().any():
        missing = review.columns[review.isna().any()].tolist()
        raise FreezeError(f"missing Phase-2 review values: {missing}")
    pd.testing.assert_frame_equal(
        review[list(PHASE1_COLUMNS)],
        phase1[list(PHASE1_COLUMNS)],
        check_dtype=False,
    )
    if not review["phase2_outcome_reviewed"].astype(bool).all():
        raise FreezeError("Phase-2 contains an unreviewed event")
    if review["post_signal_used_as_predictor"].astype(bool).any():
        raise FreezeError("post-signal information entered predictor columns")
    if review["outcome_bucket"].value_counts().to_dict() != EXPECTED_BUCKET_COUNTS:
        raise FreezeError("completed review bucket coverage drift")

    output_columns = [
        *PHASE1_COLUMNS,
        "outcome_bucket",
        "outcome_sheet_number",
        "outcome_slot",
        "outcome_sheet_path",
        "phase2_outcome_reviewed",
        "visual_path_label_available",
        "visual_path_label",
        "outcome_reviewer",
        "counterexample_flag",
        "counterexample_note",
        "phase2_pre_shape_note",
        "phase2_page_summary",
        "phase2_annotation_source",
    ]
    review = review[output_columns]

    shape_by_bucket = pd.crosstab(
        review["signal_time_trend_structure"], review["outcome_bucket"]
    ).reindex(index=PHASE1_CATEGORIES, columns=BUCKETS, fill_value=0)
    path_counts = nested_counts(review, "outcome_bucket", "visual_path_label")
    summary = {
        "experiment": EXPERIMENT,
        "stage": "PHASE2_OUTCOME_VISUAL_ATTRIBUTION_FROZEN",
        "events": len(review),
        "outcome_buckets": len(BUCKETS),
        "outcome_sheets": len(page_summaries),
        "coverage_exactly_once": True,
        "phase1_labels_immutable": True,
        "phase1_ledger_csv_sha256": source_hashes["phase1_ledger_csv"],
        "outcome_bucket_counts": {
            bucket: int((review["outcome_bucket"] == bucket).sum()) for bucket in BUCKETS
        },
        "signal_time_shape_by_outcome_bucket": {
            category: {
                bucket: int(shape_by_bucket.loc[category, bucket]) for bucket in BUCKETS
            }
            for category in PHASE1_CATEGORIES
        },
        "descriptive_visual_path_counts": path_counts,
        "counterexample_counts": {
            bucket: int(
                review.loc[review["outcome_bucket"] == bucket, "counterexample_flag"].sum()
            )
            for bucket in BUCKETS
        },
        "reviewer_counts": {
            str(key): int(value)
            for key, value in review["outcome_reviewer"].value_counts().items()
        },
        "page_summaries": page_summaries,
        "allowed_aggregations": [
            "SIGNAL_TIME_SHAPE_X_OUTCOME_BUCKET_COUNTS",
            "DESCRIPTIVE_VISUAL_PATH_COUNTS",
        ],
        "actual_return_or_outcome_value_columns_read": False,
        "rule_aggregation_performed": False,
        "rule_extraction_performed": False,
        "rule_testing_performed": False,
        "portfolio_replay_performed": False,
        "phase1_labels_modified": False,
        "post_signal_used_as_predictor": False,
        "source_hashes": source_hashes,
    }
    return review, summary, source_hashes


def write_outputs(
    review: pd.DataFrame, summary: dict[str, Any], source_hashes: dict[str, str]
) -> dict[str, Any]:
    if OUTPUT.exists():
        raise FreezeError(f"refusing to overwrite frozen Phase-2 output: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{OUTPUT.name}.staging-", dir=OUTPUT.parent))
    try:
        csv_path = staging / "phase2_outcome_review_ledger.csv"
        parquet_path = staging / "phase2_outcome_review_ledger.parquet"
        summary_path = staging / "phase2_summary.json"
        manifest_path = staging / "manifest.json"
        review.to_csv(csv_path, index=False, lineterminator="\n")
        review.to_parquet(parquet_path, index=False)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output_hashes = {
            "phase2_outcome_review_ledger_csv": sha256(csv_path),
            "phase2_outcome_review_ledger_parquet": sha256(parquet_path),
            "phase2_summary": sha256(summary_path),
        }
        manifest = {
            "experiment": EXPERIMENT,
            "stage": "PHASE2_OUTCOME_VISUAL_ATTRIBUTION_FROZEN",
            "events": EXPECTED_EVENTS,
            "outcome_buckets": len(BUCKETS),
            "outcome_sheets": EXPECTED_OUTCOME_SHEETS,
            "coverage_exactly_once": True,
            "phase1_labels_immutable": True,
            "phase1_ledger_csv_sha256": source_hashes["phase1_ledger_csv"],
            "source_hashes": source_hashes,
            "output_hashes": output_hashes,
            "allowed_aggregations": [
                "SIGNAL_TIME_SHAPE_X_OUTCOME_BUCKET_COUNTS",
                "DESCRIPTIVE_VISUAL_PATH_COUNTS",
            ],
            "actual_return_or_outcome_value_columns_read": False,
            "rule_aggregation_performed": False,
            "rule_extraction_performed": False,
            "rule_testing_performed": False,
            "portfolio_replay_performed": False,
            "phase1_labels_modified": False,
            "post_signal_used_as_predictor": False,
            "frozen_local_date": "2026-09-05",
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if verify_inputs() != source_hashes:
            raise FreezeError("a bound input changed during Phase-2 publication")
        if OUTPUT.exists():
            raise FreezeError(f"refusing publication race overwrite: {OUTPUT}")
        staging.rename(OUTPUT)
        return {
            **manifest,
            "manifest_sha256": sha256(OUTPUT / "manifest.json"),
            "output": str(OUTPUT),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-inputs",
        action="store_true",
        help="validate frozen inputs and coverage without publishing",
    )
    args = parser.parse_args()
    review, summary, source_hashes = build_review()
    if args.verify_inputs:
        print(
            json.dumps(
                {
                    "verified": True,
                    "events": len(review),
                    "outcome_sheets": summary["outcome_sheets"],
                    "outcome_bucket_counts": summary["outcome_bucket_counts"],
                    "source_hashes": source_hashes,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return
    manifest = write_outputs(review, summary, source_hashes)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
