#!/usr/bin/env python3
"""Freeze the outcome-blind V31 chronology review before outcomes are opened.

The annotations consumed here were produced by human review of masked contact
sheets.  This script deliberately does not read the Stage-B outcome ledger or
any full/post-signal chart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

EXPERIMENT = "ASHARE-INDUSTRY-RESIDUAL-SERIAL-PHASE-CHANGE-MOTHER-V31"
REPO = Path(__file__).resolve().parents[3]
CHART_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_industry_residual_serial_phase_change_mother_v31/stage_c_charts"
)
OUTPUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_industry_residual_serial_phase_change_mother_v31/"
    "stage_d_phase1_chronology_review"
)
ANNOTATION_FILES = (
    REPO
    / "research/market_behavior_os_v2/experiments/"
    "ASHARE-V31_phase1_annotations_sheets_0001_0016.json",
    REPO
    / "research/market_behavior_os_v2/experiments/"
    "ASHARE-V31_phase1_annotations_sheets_0017_0032.json",
    REPO
    / "research/market_behavior_os_v2/experiments/"
    "ASHARE-V31_phase1_annotations_sheets_0033_0048.json",
    REPO
    / "research/market_behavior_os_v2/experiments/"
    "ASHARE-V31_phase1_annotations_sheets_0049_0065.json",
)
INPUTS = {
    "chart_manifest": (
        CHART_ROOT / "manifest.json",
        "b8dd9ef51a1dec86205a9ce856cfafe87cd650b54835cf1f2943fbcf30624c25",
    ),
    "chronology_review_template": (
        CHART_ROOT / "chronology_review_template.csv",
        "3228360574429ddab22d4416e3f0079750d6a27b43b9a27f0a7e14aaaa75703a",
    ),
    "contact_sheet_placements": (
        CHART_ROOT / "contact_sheet_placements.csv",
        "c7f8e9339241cbbd74c746009e2086411b8a935c67f7e8263d61a115581d06df",
    ),
    "contact_sheet_index": (
        CHART_ROOT / "contact_sheet_index.csv",
        "b8cd98cca7e14a2480afb4103ffa53100928d4bc961cdc283052ddb29e1ebfd1",
    ),
}
EXPECTED_EVENTS = 1_602
EXPECTED_SHEETS = 65
CATEGORIES = (
    "BASE_OR_COMPRESSION",
    "ORDERLY_ADVANCE",
    "MATURE_EXTENDED_HIGH",
    "VOLATILE_TOPPING",
    "DOWNTREND_OR_REPAIR",
    "STRUCTURAL_BREAKDOWN",
    "NONE_CLEAR",
)


class FreezeError(RuntimeError):
    """Raised when frozen chart inputs or blind-review coverage drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for role, (path, expected) in INPUTS.items():
        if not path.is_file():
            raise FreezeError(f"missing input {role}: {path}")
        actual = sha256(path)
        if actual != expected:
            raise FreezeError(f"input drift for {role}: {actual} != {expected}")
        hashes[role] = actual
    for path in ANNOTATION_FILES:
        if not path.is_file():
            raise FreezeError(f"missing annotation: {path}")
        hashes[f"annotation:{path.name}"] = sha256(path)
    return hashes


def reviewer(sheet_number: int) -> str:
    if 1 <= sheet_number <= 16:
        return "blind_reviewer_James"
    if 17 <= sheet_number <= 32:
        return "blind_reviewer_Avicenna"
    if 33 <= sheet_number <= 48:
        return "blind_reviewer_Tesla"
    if 49 <= sheet_number <= 65:
        return "primary_blind_reviewer"
    raise FreezeError(f"unexpected sheet number: {sheet_number}")


def load_annotations() -> dict[str, dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = {}
    for path in ANNOTATION_FILES:
        raw = json.loads(path.read_text(encoding="utf-8"))
        overlap = set(pages).intersection(raw)
        if overlap:
            raise FreezeError(f"duplicate annotation pages: {sorted(overlap)}")
        pages.update(raw)
    expected_keys = {f"{sheet:04d}" for sheet in range(1, EXPECTED_SHEETS + 1)}
    if set(pages) != expected_keys:
        raise FreezeError(
            f"annotation page coverage drift: missing={sorted(expected_keys - set(pages))}, "
            f"extra={sorted(set(pages) - expected_keys)}"
        )
    return pages


def validate_and_flatten_annotations(
    pages: dict[str, dict[str, Any]], placements: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    page_summary: list[dict[str, Any]] = []
    for key in sorted(pages):
        sheet_number = int(key)
        page = pages[key]
        if set(page["categories"]) != set(CATEGORIES):
            raise FreezeError(f"category schema drift on sheet {key}")
        actual_numbers: list[int] = []
        label_by_number: dict[int, str] = {}
        for category in CATEGORIES:
            numbers = [int(value) for value in page["categories"][category]]
            actual_numbers.extend(numbers)
            for chart_number in numbers:
                if chart_number in label_by_number:
                    raise FreezeError(f"duplicate chart {chart_number} on sheet {key}")
                label_by_number[chart_number] = category

        sheet_rows = placements.loc[placements["sheet_number"] == sheet_number]
        expected_numbers = sorted(sheet_rows["chart_number"].astype(int).tolist())
        if sorted(actual_numbers) != expected_numbers:
            raise FreezeError(
                f"chart coverage drift on sheet {key}: "
                f"expected={expected_numbers}, actual={sorted(actual_numbers)}"
            )
        if int(page["start"]) != expected_numbers[0] or int(page["end"]) != expected_numbers[-1]:
            raise FreezeError(f"declared boundary drift on sheet {key}")
        counts = Counter(label_by_number.values())
        page_summary.append(
            {
                "sheet_number": sheet_number,
                "start": expected_numbers[0],
                "end": expected_numbers[-1],
                "charts": len(expected_numbers),
                "reviewer": reviewer(sheet_number),
                "dominant": page["dominant"],
                "category_counts": {category: counts.get(category, 0) for category in CATEGORIES},
                "signal_time_note": page["signal_time_note"],
            }
        )
        for chart_number, category in label_by_number.items():
            records.append(
                {
                    "chart_number": chart_number,
                    "chronology_sheet": sheet_number,
                    "signal_time_trend_structure": category,
                    "signal_time_pattern_note": page["signal_time_note"],
                    "chronology_reviewer": reviewer(sheet_number),
                }
            )
    flat = pd.DataFrame.from_records(records).sort_values("chart_number").reset_index(drop=True)
    if len(flat) != EXPECTED_EVENTS or flat["chart_number"].duplicated().any():
        raise FreezeError("flattened annotation coverage drift")
    return flat, page_summary


def build_review() -> tuple[pd.DataFrame, dict[str, Any], dict[str, str]]:
    source_hashes = verify_inputs()
    template = pd.read_csv(INPUTS["chronology_review_template"][0])
    placements = pd.read_csv(INPUTS["contact_sheet_placements"][0])
    sheet_index = pd.read_csv(INPUTS["contact_sheet_index"][0])
    if len(template) != EXPECTED_EVENTS or template["event_id"].duplicated().any():
        raise FreezeError("chronology template event coverage drift")

    chronology = placements.loc[
        placements["collection"] == "chronological_masked",
        ["event_id", "chart_number", "sheet_number", "slot"],
    ].copy()
    if len(chronology) != EXPECTED_EVENTS or chronology["event_id"].duplicated().any():
        raise FreezeError("chronology placement coverage drift")
    sheets = sheet_index.loc[sheet_index["collection"] == "chronological_masked"].copy()
    if len(sheets) != EXPECTED_SHEETS:
        raise FreezeError("chronology sheet count drift")
    if set(chronology["event_id"]) != set(template["event_id"]):
        raise FreezeError("template/placement event-set mismatch")

    pages = load_annotations()
    annotations, page_summary = validate_and_flatten_annotations(pages, chronology)
    review = template[
        ["event_id", "chart_number", "symbol", "signal_date", "causal_industry"]
    ].merge(chronology, on=["event_id", "chart_number"], how="left", validate="one_to_one")
    review = review.merge(annotations, on="chart_number", how="left", validate="one_to_one")
    if review.isna().any().any():
        missing = review.columns[review.isna().any()].tolist()
        raise FreezeError(f"missing phase-one review fields: {missing}")
    if not (review["sheet_number"] == review["chronology_sheet"]).all():
        raise FreezeError("annotation/placement sheet mismatch")
    review = (
        review.drop(columns=["sheet_number"])
        .sort_values("chart_number")
        .reset_index(drop=True)
    )
    review["chronology_reviewed"] = True
    review["signal_time_level_location"] = "NOT_SEPARATELY_CODED_IN_BLIND_PASS"
    review["signal_time_turnover_structure"] = "NOT_SEPARATELY_CODED_IN_BLIND_PASS"
    review["signal_candle_structure"] = "NOT_SEPARATELY_CODED_IN_BLIND_PASS"
    review["post_signal_used_as_predictor"] = False
    review = review[
        [
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
        ]
    ]
    if review["signal_date"].astype(str).max() > "2020-06-30":
        raise FreezeError("post-development signal entered blind-review ledger")
    if review["post_signal_used_as_predictor"].any():
        raise FreezeError("post-signal information entered phase-one labels")

    counts = review["signal_time_trend_structure"].value_counts().to_dict()
    summary = {
        "experiment": EXPERIMENT,
        "stage": "PHASE1_OUTCOME_BLIND_CHRONOLOGY_REVIEW_FROZEN",
        "events": len(review),
        "chronology_sheets": len(sheets),
        "coverage_exactly_once": True,
        "masked_post_signal_region": True,
        "outcome_sheets_opened_before_freeze": False,
        "outcome_columns_read_for_annotation": False,
        "post_signal_used_as_predictor": False,
        "maximum_signal_date": str(review["signal_date"].astype(str).max()),
        "category_counts": {category: int(counts.get(category, 0)) for category in CATEGORIES},
        "reviewers": {
            "sheets_0001_0016": "blind_reviewer_James",
            "sheets_0017_0032": "blind_reviewer_Avicenna",
            "sheets_0033_0048": "blind_reviewer_Tesla",
            "sheets_0049_0065": "primary_blind_reviewer",
        },
        "page_summary": page_summary,
        "recurring_signal_time_motifs": [
            "OLD_PEAK_TO_LONG_DECAY_OR_STRUCTURAL_BREAK",
            "QUIET_LOW_BASE_TO_ABRUPT_SIGNAL_TIME_EXPANSION",
            "ORDERLY_HIGHER_LOW_MULTI_LEG_ADVANCE",
            "MATURE_MARKUP_TO_VOLATILE_TOP_OR_BREAK",
            "DEEP_U_OR_W_REPAIR_BELOW_PRIOR_MAJOR_HIGH",
        ],
        "calendar_clustering_visible_before_outcomes": True,
        "next_step": "OPEN_FROZEN_OUTCOME_SHEETS_FOR_ATTRIBUTION_WITHOUT_REWRITING_PHASE1",
        "source_hashes": source_hashes,
    }
    return review, summary, source_hashes


def write_outputs(review: pd.DataFrame, summary: dict[str, Any]) -> dict[str, Any]:
    if OUTPUT.exists():
        raise FreezeError(f"refusing to overwrite frozen output: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v31-phase1-", dir=OUTPUT.parent) as tmp_name:
        tmp = Path(tmp_name)
        csv_path = tmp / "chronology_review_ledger.csv"
        parquet_path = tmp / "chronology_review_ledger.parquet"
        summary_path = tmp / "phase1_summary.json"
        manifest_path = tmp / "manifest.json"
        review.to_csv(csv_path, index=False, lineterminator="\n")
        review.to_parquet(parquet_path, index=False)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest = {
            "experiment": EXPERIMENT,
            "stage": "PHASE1_OUTCOME_BLIND_CHRONOLOGY_REVIEW_FROZEN",
            "events": len(review),
            "chronology_sheets": EXPECTED_SHEETS,
            "coverage_exactly_once": True,
            "outcome_sheets_opened_before_freeze": False,
            "post_signal_used_as_predictor": False,
            "frozen_local_date": "2026-09-05",
            "chronology_review_ledger_csv_sha256": sha256(csv_path),
            "chronology_review_ledger_parquet_sha256": sha256(parquet_path),
            "phase1_summary_sha256": sha256(summary_path),
            "annotation_hashes": {
                path.name: sha256(path) for path in ANNOTATION_FILES
            },
            "next_step": "PHASE2_OUTCOME_ATTRIBUTION_ONLY_PHASE1_IMMUTABLE",
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(OUTPUT)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-inputs", action="store_true")
    args = parser.parse_args()
    review, summary, hashes = build_review()
    if args.verify_inputs:
        print(
            json.dumps(
                {
                    "verified": True,
                    "events": len(review),
                    "category_counts": summary["category_counts"],
                    "source_hashes": hashes,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return
    manifest = write_outputs(review, summary)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
