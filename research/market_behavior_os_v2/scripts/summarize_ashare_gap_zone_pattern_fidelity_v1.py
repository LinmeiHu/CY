#!/usr/bin/env python3
# ruff: noqa: E501
"""Summarize returned human labels for the gap-zone fidelity audit; never reads returns."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-PATTERN-FIDELITY-AUDIT-V1"
DEFAULT_REVIEW = OS_ROOT / f"reports/{EXPERIMENT}_review.csv"
DEFAULT_MAPPING = OS_ROOT / f"artifacts/{EXPERIMENT}_audit_mapping.parquet"
DEFAULT_OUTPUT = OS_ROOT / f"reports/{EXPERIMENT}_human_label_summary.md"

PRIMARY = {"A_EXACT_PATTERN", "B_CLOSE_BUT_MISSING_SOMETHING", "C_NOT_THE_PATTERN"}
YES_NO_UNCERTAIN = {"YES", "NO", "UNCERTAIN"}
TARGETS = {"LOWEST_LAYER", "WHOLE_STACK", "UPPER_LAYER", "OTHER", "UNCERTAIN"}


def rate_table(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    return frame.groupby(column, dropna=False).PRIMARY_LABEL.agg(
        cases="size", exact=lambda values: values.eq("A_EXACT_PATTERN").sum()
    ).assign(exact_rate=lambda value: value.exact / value.cases).reset_index()


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    return frame.to_markdown(index=False)


def validate(review: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    if review.audit_id.duplicated().any() or set(review.audit_id) != set(mapping.audit_id):
        raise ValueError("review IDs do not match the frozen 120-case mapping")
    labels = review.PRIMARY_LABEL.fillna("").str.strip()
    if labels.eq("").any():
        raise ValueError(f"human review incomplete: {int(labels.eq('').sum())} PRIMARY_LABEL values blank")
    invalid = sorted(set(labels) - PRIMARY)
    if invalid:
        raise ValueError(f"invalid PRIMARY_LABEL values: {invalid}")
    binary_columns = [
        "WOULD_CONSIDER_BUYING_AT_FIRST_ZONE_ENTRY", "FORMER_LEADER_VISUALLY_VALID",
        "PRIOR_RUNUP_VISUALLY_STRONG_ENOUGH", "COLLAPSE_SHARP_ENOUGH",
        "TRUE_GAP_ZONE_VISUALLY_MEANINGFUL", "MULTI_LAYER_ZONE_RELEVANT",
        "ZONE_PERSISTED_LONG_ENOUGH", "BASE_OR_SETTLING_PHASE_REQUIRED",
        "VOLUME_SUFFOCATION_VISUALLY_REQUIRED", "FIRST_ENTRY_TRIGGER_LOOKS_CORRECT",
    ]
    for column in binary_columns:
        values = set(review[column].fillna("").str.strip()) - {""}
        if not values <= YES_NO_UNCERTAIN:
            raise ValueError(f"invalid {column}: {sorted(values-YES_NO_UNCERTAIN)}")
    targets = set(review.PREFERRED_ZONE_TARGET.fillna("").str.strip()) - {""}
    if not targets <= TARGETS:
        raise ValueError(f"invalid PREFERRED_ZONE_TARGET: {sorted(targets-TARGETS)}")
    return mapping.merge(review, on="audit_id", how="inner", validate="one_to_one")


def summarize(frame: pd.DataFrame) -> str:
    label_counts = frame.PRIMARY_LABEL.value_counts().reindex(sorted(PRIMARY), fill_value=0).rename_axis("label").reset_index(name="cases")
    label_counts["proportion"] = label_counts.cases / len(frame)
    rejection = (
        frame.REJECTION_REASON.fillna("").str.split(";").explode().str.strip().loc[lambda values: values.ne("")]
        .value_counts().rename_axis("reason").reset_index(name="count")
    )
    variants = {
        "LOWER_TOUCH": "candidate_reentry_date",
        "LOWER_CLOSE": "reentry_b_lower_close_date",
        "ZONE_10PCT": "reentry_c_zone10_date",
        "ZONE_50PCT": "reentry_d_zone50_date",
        "FULL_FILL": "reentry_e_full_fill_date",
        "NEXT_LAYER": "next_layer_entry_date",
    }
    exact = frame.loc[frame.PRIMARY_LABEL.eq("A_EXACT_PATTERN")].copy()
    variant_rows = []
    for name, column in variants.items():
        available = exact[column].notna()
        aligned = available & pd.to_datetime(exact[column]).dt.normalize().eq(pd.to_datetime(exact.candidate_reentry_date).dt.normalize())
        variant_rows.append({"semantic": name, "A_cases_available": int(available.sum()), "same_day_as_review_marker": int(aligned.sum()), "alignment_rate": float(aligned.sum()/available.sum()) if available.any() else None})
    lines = [
        f"# {EXPERIMENT} human-label summary", "",
        "This summary uses human shape labels and frozen pre-reentry descriptors only. It contains no return analysis.", "",
        "## A/B/C proportions", "", markdown_table(label_counts), "",
        "## Exact-pattern rate by hidden machine stratum", "", markdown_table(rate_table(frame, "machine_class")), "",
        "## Persistence", "", markdown_table(rate_table(frame, "persistence_bucket")), "",
        "## Single versus multilayer", "", markdown_table(rate_table(frame.assign(layer_type=frame.multi_layer.map({True:"MULTILAYER",False:"SINGLE"})), "layer_type")), "",
        "## Board", "", markdown_table(rate_table(frame, "board")), "",
        "## ST status", "", markdown_table(rate_table(frame.assign(st_type=frame.is_st.map({True:"ST",False:"NON_ST"})), "st_type")), "",
        "## Provisional former-leader bucket", "", markdown_table(rate_table(frame, "leader_metric_bucket")), "",
        "## Re-entry semantic alignment inside A labels", "", markdown_table(pd.DataFrame(variant_rows)), "",
        "## Preferred zone target", "", markdown_table(frame.PREFERRED_ZONE_TARGET.value_counts(dropna=False).rename_axis("target").reset_index(name="count")), "",
        "## Rejection reasons", "", markdown_table(rejection), "",
        "## Human gate", "",
        "Use these labels to freeze the actual former-leader, persistence, stack, and re-entry semantics before any return study. Do not optimize the detector against future returns.", "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-csv", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    review = pd.read_csv(args.review_csv, dtype=str, keep_default_na=False)
    if review.PRIMARY_LABEL.fillna("").str.strip().eq("").all():
        print("HUMAN_PATTERN_REVIEW_REQUIRED: review CSV contains no labels; no summary written")
        return
    mapping = pd.read_parquet(args.mapping)
    frame = validate(review, mapping)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(summarize(frame), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
