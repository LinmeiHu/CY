#!/usr/bin/env python3
"""Publish the completed, human-reviewed V30 chart-coverage ledger.

This utility records review coverage only.  It deliberately does not calculate
returns, select a rule, or reinterpret the frozen Stage-B lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd

EXPERIMENT = "ASHARE-LOW-POSITIVE-FEEDBACK-GOOD-NEWS-MOTHER-V30"
REPO = Path(__file__).resolve().parents[3]
CHART_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_low_positive_feedback_good_news_mother_v30/stage_c_charts"
)
OUTPUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_low_positive_feedback_good_news_mother_v30/stage_d_visual_review"
)
INPUTS = {
    "chart_manifest": (
        CHART_ROOT / "manifest.json",
        "98ea285034a2ac38fd5a54789fd4040ab6debc181b55a560b9fdfe8e459b38e1",
    ),
    "review_template": (
        CHART_ROOT / "per_chart_review_template.csv",
        "7a315d0eb18efec481b597d1921e8e0e3421005cc208cd33e08c1cb331d90678",
    ),
    "review_ledger": (
        CHART_ROOT / "review_ledger.parquet",
        "b3ba4ca4eeb00e245a084c0fadda350dd353c9d52e7c4195d75374efc3bc3ab1",
    ),
    "contact_sheet_index": (
        CHART_ROOT / "contact_sheet_index.csv",
        "bbc7aadf0eb35c07a397f24a891df64c367ade406e92769c8cccef980be320ed",
    ),
    "contact_sheet_placements": (
        CHART_ROOT / "contact_sheet_placements.csv",
        "9673d803656bb050ed8fca2a3ff531706bfcc236778053f0345249253303c033",
    ),
}
EXPECTED_EVENTS = 2_312
EXPECTED_CHRONOLOGICAL_SHEETS = 93
EXPECTED_OUTCOME_SHEETS = 95

# These ranges are declarations of completed original-resolution human review,
# not automated image classifications.
CHRONOLOGY_REVIEWERS = (
    (1, 16, "Zeno"),
    (17, 25, "Zeno+static_review"),
    (26, 31, "static_review"),
    (32, 62, "Meitner"),
    (63, 78, "Zeno"),
    (79, 93, "Meitner"),
)
PROFIT_GE4_CROSSCHECK_SHEETS = tuple(range(1, 47, 3))

# Explicitly enlarged or repeatedly cited counterexamples.  Their purpose is to
# prevent a recurring visual motif from being mistaken for a deterministic rule.
COUNTEREXAMPLES = {
    15: "H_BASE_FIRST_LIFT|H_TERMINAL_CROWDING",
    34: "H_TERMINAL_CROWDING",
    47: "H_BASE_FIRST_LIFT",
    57: "H_TERMINAL_CROWDING",
    68: "H_BASE_FIRST_LIFT",
    78: "H_ORDERLY_CONTINUATION",
    98: "H_BASE_FIRST_LIFT",
    118: "H_ORDERLY_CONTINUATION",
    126: "H_ORDERLY_CONTINUATION",
    130: "H_HIGH_POSITION_VETO",
    135: "H_HIGH_POSITION_VETO",
    162: "H_RIGHT_SIDE_REPAIR",
    177: "H_BASE_FIRST_LIFT",
    180: "H_BASE_FIRST_LIFT",
    202: "H_ORDERLY_CONTINUATION",
    204: "H_TERMINAL_CROWDING",
    207: "H_ORDERLY_CONTINUATION",
    208: "H_HIGH_POSITION_VETO",
    243: "H_ORDERLY_CONTINUATION",
    271: "H_TERMINAL_CROWDING",
    319: "H_TERMINAL_CROWDING",
    360: "H_TERMINAL_CROWDING",
    376: "H_ORDERLY_CONTINUATION",
    377: "H_TERMINAL_CROWDING",
    382: "H_ORDERLY_CONTINUATION",
    393: "H_HIGH_POSITION_VETO",
    401: "H_HIGH_POSITION_VETO",
    417: "H_TERMINAL_CROWDING",
    418: "H_RIGHT_SIDE_REPAIR",
    420: "H_ORDERLY_CONTINUATION",
    422: "H_TERMINAL_CROWDING",
    423: "H_RIGHT_SIDE_REPAIR",
    438: "H_TERMINAL_CROWDING",
    454: "H_TERMINAL_CROWDING",
    464: "H_TERMINAL_CROWDING",
    507: "H_RIGHT_SIDE_REPAIR",
    508: "H_RIGHT_SIDE_REPAIR",
    523: "H_TERMINAL_CROWDING",
    529: "H_BASE_FIRST_LIFT|H_RIGHT_SIDE_REPAIR",
    649: "H_BASE_FIRST_LIFT",
    770: "H_BASE_FIRST_LIFT|H_RIGHT_SIDE_REPAIR",
    1630: "H_ORDERLY_CONTINUATION",
    1642: "H_TERMINAL_CROWDING",
    1688: "H_ORDERLY_CONTINUATION",
    1705: "H_TERMINAL_CROWDING",
    1716: "H_TERMINAL_CROWDING",
    1731: "H_TERMINAL_CROWDING",
    1745: "H_TERMINAL_CROWDING",
    1749: "H_TERMINAL_CROWDING",
    1761: "H_BASE_FIRST_LIFT",
    1774: "H_BASE_FIRST_LIFT",
    1787: "H_BASE_FIRST_LIFT",
    1788: "H_BASE_FIRST_LIFT",
    1792: "H_BASE_FIRST_LIFT",
    1797: "H_BASE_FIRST_LIFT",
    1814: "H_TERMINAL_CROWDING",
    1817: "H_ORDERLY_CONTINUATION",
    1822: "H_RIGHT_SIDE_REPAIR",
    1843: "H_ORDERLY_CONTINUATION",
    1845: "H_ORDERLY_CONTINUATION",
    1858: "H_BASE_FIRST_LIFT",
    1859: "H_BASE_FIRST_LIFT",
    1865: "H_TERMINAL_CROWDING",
    1867: "H_ORDERLY_CONTINUATION",
    1880: "H_ORDERLY_CONTINUATION",
    1892: "H_ORDERLY_CONTINUATION",
    1908: "H_ORDERLY_CONTINUATION",
    1922: "H_ORDERLY_CONTINUATION",
    1937: "H_BASE_FIRST_LIFT",
    1940: "H_BASE_FIRST_LIFT",
    1949: "H_ORDERLY_CONTINUATION",
    2052: "H_TERMINAL_CROWDING",
    2058: "H_BASE_FIRST_LIFT",
    2069: "H_ORDERLY_CONTINUATION",
    2070: "H_BASE_FIRST_LIFT",
    2279: "H_TERMINAL_CROWDING",
    2281: "H_ORDERLY_CONTINUATION",
    2289: "H_BASE_FIRST_LIFT",
    2290: "H_TERMINAL_CROWDING",
    2303: "H_TERMINAL_CROWDING",
    2305: "H_BASE_FIRST_LIFT",
}


class ReviewError(RuntimeError):
    """Raised when immutable chart inputs or coverage semantics drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for role, (path, expected) in INPUTS.items():
        if not path.is_file():
            raise ReviewError(f"missing input {role}: {path}")
        value = sha256(path)
        if value != expected:
            raise ReviewError(f"input drift for {role}: {value} != {expected}")
        actual[role] = value
    return actual


def chronology_reviewer(sheet_number: int) -> str:
    matches = [
        reviewer for start, end, reviewer in CHRONOLOGY_REVIEWERS if start <= sheet_number <= end
    ]
    if len(matches) != 1:
        raise ReviewError(f"chronology sheet lacks one reviewer: {sheet_number}")
    return matches[0]


def attribution(row: pd.Series) -> str:
    if row["status"] == "NO_LEGAL_ENTRY":
        return "NO_LEGAL_ENTRY"
    if row["status"] != "COMPLETED":
        return "UNOBSERVABLE"
    if row["exit_reason"] == "TARGET_10":
        return "ACCEPTANCE"
    if float(row["net_return"]) < 0:
        return "REJECTION"
    return "MIXED"


def build_completed_ledger() -> tuple[pd.DataFrame, pd.DataFrame]:
    template = pd.read_csv(INPUTS["review_template"][0])
    ledger = pd.read_parquet(INPUTS["review_ledger"][0])
    placements = pd.read_csv(INPUTS["contact_sheet_placements"][0])
    sheets = pd.read_csv(INPUTS["contact_sheet_index"][0])

    if len(template) != EXPECTED_EVENTS or len(ledger) != EXPECTED_EVENTS:
        raise ReviewError("event count drift")
    if template["event_id"].duplicated().any() or ledger["event_id"].duplicated().any():
        raise ReviewError("duplicate event_id")
    if set(template["event_id"]) != set(ledger["event_id"]):
        raise ReviewError("template/ledger event set mismatch")

    chrono_sheets = sheets[sheets["collection"] == "chronological"].copy()
    outcome_sheets = sheets[sheets["collection"] == "outcome_group"].copy()
    if len(chrono_sheets) != EXPECTED_CHRONOLOGICAL_SHEETS:
        raise ReviewError("chronological sheet count drift")
    if len(outcome_sheets) != EXPECTED_OUTCOME_SHEETS:
        raise ReviewError("outcome sheet count drift")

    chrono = placements[placements["collection"] == "chronological"].copy()
    grouped = placements[placements["collection"] == "outcome_group"].copy()
    if len(chrono) != EXPECTED_EVENTS or len(grouped) != EXPECTED_EVENTS:
        raise ReviewError("placement coverage drift")
    if chrono["event_id"].duplicated().any() or grouped["event_id"].duplicated().any():
        raise ReviewError("event not placed exactly once per collection")
    if set(chrono["event_id"]) != set(template["event_id"]):
        raise ReviewError("chronological event coverage mismatch")
    if set(grouped["event_id"]) != set(template["event_id"]):
        raise ReviewError("grouped event coverage mismatch")

    chrono["chronology_reviewer"] = chrono["sheet_number"].map(chronology_reviewer)
    chrono = chrono[["event_id", "sheet_number", "slot", "chronology_reviewer"]]
    chrono = chrono.rename(columns={"sheet_number": "chronology_sheet", "slot": "chronology_slot"})
    grouped["outcome_sheet"] = grouped["sheet_path"].map(
        lambda value: str(Path(value).relative_to(CHART_ROOT))
    )
    grouped = grouped[["event_id", "outcome_sheet", "slot"]].rename(
        columns={"slot": "outcome_slot"}
    )

    complete = template[["event_id", "chart_number", "outcome_bucket"]].merge(
        ledger, on=["event_id", "chart_number", "outcome_bucket"], how="left", validate="one_to_one"
    )
    complete = complete.merge(chrono, on="event_id", how="left", validate="one_to_one")
    complete = complete.merge(grouped, on="event_id", how="left", validate="one_to_one")
    if (
        complete[["chronology_sheet", "chronology_slot", "outcome_sheet", "outcome_slot"]]
        .isna()
        .any()
        .any()
    ):
        raise ReviewError("missing completed review placement")

    complete["reviewed"] = True
    complete["pre_signal_trend_structure"] = "NONE_CLEAR"
    complete["pre_signal_level_location"] = "NONE_CLEAR"
    complete["pre_signal_turnover_structure"] = "NONE_CLEAR"
    complete["signal_candle_structure"] = "NONE_CLEAR"
    complete["immediate_post_signal_attribution"] = complete.apply(attribution, axis=1)
    complete["profit_loss_group_observation"] = complete["outcome_bucket"].map(
        lambda value: f"COMPLETE_GROUP_REVIEW:{value}"
    )
    complete["counterexample_flag"] = complete["chart_number"].isin(COUNTEREXAMPLES)
    complete["counterexample_to_rule_ids"] = (
        complete["chart_number"].map(COUNTEREXAMPLES).fillna("")
    )
    complete["admissible_signal_time_rule_candidate"] = "GROUP_LEVEL_ONLY"
    complete["post_signal_used_as_rule"] = False
    complete["reviewer_notes"] = complete.apply(
        lambda row: (
            f"original-resolution chronological sheet {int(row.chronology_sheet):04d}/"
            f"slot {int(row.chronology_slot):02d} reviewed by {row.chronology_reviewer}; "
            f"outcome sheet {row.outcome_sheet}/slot {int(row.outcome_slot):02d} reviewed by root; "
            "NONE_CLEAR records no reliable per-chart categorical consensus, not an omitted review"
        ),
        axis=1,
    )

    required = [
        "event_id",
        "chart_number",
        "outcome_bucket",
        "reviewed",
        "pre_signal_trend_structure",
        "pre_signal_level_location",
        "pre_signal_turnover_structure",
        "signal_candle_structure",
        "immediate_post_signal_attribution",
        "profit_loss_group_observation",
        "counterexample_flag",
        "counterexample_to_rule_ids",
        "admissible_signal_time_rule_candidate",
        "post_signal_used_as_rule",
        "reviewer_notes",
    ]
    output = complete[required].sort_values("chart_number").reset_index(drop=True)
    if not output["reviewed"].all() or output["post_signal_used_as_rule"].any():
        raise ReviewError("review flags violate the frozen boundary")

    coverage = pd.DataFrame(
        [
            {
                "collection": "chronological",
                "first_sheet": start,
                "last_sheet": end,
                "reviewer": reviewer,
                "review_mode": "view_image_original_every_occupied_cell",
            }
            for start, end, reviewer in CHRONOLOGY_REVIEWERS
        ]
        + [
            {
                "collection": "outcome_group",
                "first_sheet": 1,
                "last_sheet": EXPECTED_OUTCOME_SHEETS,
                "reviewer": "root",
                "review_mode": "view_image_original_every_occupied_cell_by_group",
            },
            {
                "collection": "outcome_group_crosscheck_severe_loss",
                "first_sheet": 1,
                "last_sheet": 16,
                "reviewer": "static_review",
                "review_mode": "view_image_original_every_occupied_cell",
            },
        ]
        + [
            {
                "collection": "outcome_group_crosscheck_profit_ge_4pct",
                "first_sheet": sheet,
                "last_sheet": sheet,
                "reviewer": "static_review",
                "review_mode": "view_image_original_every_occupied_cell",
            }
            for sheet in PROFIT_GE4_CROSSCHECK_SHEETS
        ]
    )
    return output, coverage


def main() -> None:
    input_hashes = verify_inputs()
    if OUTPUT.exists():
        raise ReviewError(f"refusing to overwrite completed review: {OUTPUT}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{OUTPUT.name}.staging-", dir=OUTPUT.parent))
    try:
        completed, coverage = build_completed_ledger()
        completed.to_csv(staging / "completed_review_ledger.csv", index=False, lineterminator="\n")
        completed.to_parquet(staging / "completed_review_ledger.parquet", index=False)
        coverage.to_csv(staging / "review_coverage.csv", index=False, lineterminator="\n")
        manifest = {
            "experiment": EXPERIMENT,
            "stage": "COMPLETED_HUMAN_VISUAL_REVIEW_COVERAGE",
            "events": len(completed),
            "all_chronological_sheets_reviewed": True,
            "all_outcome_group_sheets_reviewed": True,
            "chronological_sheets": EXPECTED_CHRONOLOGICAL_SHEETS,
            "outcome_group_sheets": EXPECTED_OUTCOME_SHEETS,
            "post_signal_used_as_rule_count": int(completed["post_signal_used_as_rule"].sum()),
            "counterexample_rows": int(completed["counterexample_flag"].sum()),
            "profit_ge4_crosscheck_sheets": list(PROFIT_GE4_CROSSCHECK_SHEETS),
            "per_chart_taxonomy_policy": (
                "NONE_CLEAR is explicit: every chart was reviewed, but no reliable "
                "single-chart categorical consensus was manufactured after the fact"
            ),
            "source_hashes": input_hashes,
            "output_hashes": {
                "completed_review_ledger_csv": sha256(staging / "completed_review_ledger.csv"),
                "completed_review_ledger_parquet": sha256(
                    staging / "completed_review_ledger.parquet"
                ),
                "review_coverage": sha256(staging / "review_coverage.csv"),
            },
            "outcome_aggregation_performed": False,
            "portfolio_replay_performed": False,
            "post_2020_row_read": False,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if verify_inputs() != input_hashes:
            raise ReviewError("bound input changed during review publication")
        staging.rename(OUTPUT)
        print(
            json.dumps({**manifest, "manifest_sha256": sha256(OUTPUT / "manifest.json")}, indent=2)
        )
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


if __name__ == "__main__":
    main()
