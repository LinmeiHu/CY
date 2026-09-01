#!/usr/bin/env python3
"""Reconcile the revised Cycle-019 scope without recomputing inspected outcomes."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = (
    PROGRAM / "experiments/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_reconciliation_spec.json"
)
RESULT_PATH = (
    PROGRAM / "artifacts/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_reconciliation_result.json"
)
REPORT_PATH = (
    PROGRAM / "reports/ASHARE-CHAMPION-APPLICABILITY-MAP-CYCLE-019_reconciliation_report.md"
)
EXPECTED_SPEC_SHA256 = "e8a3685fb4eaddf56e6d2da0b9bad06534cb4434f83dec558d584d6802ead964"
AUTHORIZED_MAP = "ABSOLUTE_MARKET_STATE_X_SYNCHRONIZATION"
DIMENSIONS = (
    "ABSOLUTE_MARKET_STATE",
    "CROSS_SECTIONAL_DISPERSION",
    "SYNCHRONIZATION",
    "INDUSTRY_PERSISTENCE",
)


class ReconciliationError(RuntimeError):
    """Fail-closed revised-scope reconciliation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ReconciliationError("reconciliation spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "POST_OUTCOME_SCOPE_RECONCILIATION_NOT_PREREGISTRATION":
        raise ReconciliationError("reconciliation provenance boundary changed")
    for role, binding in spec["bound_original_evidence"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ReconciliationError(f"bound original evidence changed: {role}")
    boundary = spec["scientific_boundary"]
    if not boundary["original_outcomes_already_inspected"]:
        raise ReconciliationError("cannot represent this reconciliation as preregistered")
    if any(
        boundary[key]
        for key in (
            "new_feature_or_outcome_computation",
            "new_threshold_or_map_search",
            "original_frozen_spec_modified",
            "original_evidence_modified",
            "deployment_rule_authorized",
            "champion_change_authorized",
        )
    ):
        raise ReconciliationError("reconciliation exceeds revised diagnostic scope")
    return spec


def _fmt(value: float | None) -> str:
    return "NA" if value is None or not math.isfinite(value) else f"{value:.2%}"


def _single_rows(original: dict[str, Any], translation: dict[str, str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    rows = original["single_dimension_rows"]
    for dimension in DIMENSIONS:
        full = {
            row["state"]: row
            for row in rows
            if row["dimension"] == dimension and row["period"] == "full"
        }
        decision = original["single_dimension_decisions"][dimension]
        output.append(
            {
                "dimension": dimension,
                "low_dates": full["LOW"]["decision_dates"],
                "medium_dates": full["MEDIUM"]["decision_dates"],
                "high_dates": full["HIGH"]["decision_dates"],
                "low_payoff": full["LOW"]["mean_cohort_payoff"],
                "medium_payoff": full["MEDIUM"]["mean_cohort_payoff"],
                "high_payoff": full["HIGH"]["mean_cohort_payoff"],
                "early_favorable_spread": decision["block_deltas"]["early"],
                "late_favorable_spread": decision["block_deltas"]["late"],
                "classification": translation.get(
                    decision["classification"], decision["classification"]
                ),
                "yearly_distribution": decision["yearly_distribution"],
            }
        )
    return output


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Cycle 019 — revised-scope applicability-map reconciliation",
        "",
        "## Scientific provenance",
        "",
        (
            "The revised user contract arrived after the original Cycle-019 outcomes had "
            "already been inspected and committed. This document is therefore a post-outcome "
            "scope reconciliation, not a new preregistration or independent experiment. The "
            "original frozen spec and evidence remain immutable and auditable."
        ),
        "",
        "## Executive conclusion",
        "",
        "The Champion's habitat is partially identifiable ex ante, but not deployment-grade.",
        "",
        f"Final revised classification: `{result['classification']}`.",
        "",
        "Absolute market state matters most; lower stock-sign synchronization adds weaker repeated information. The map partly distinguishes 2022-like synchronized weakness from 2023-like structural opportunity. Relative Alpha survives on negative absolute cohort dates. No deployment experiment is scientifically earned because 2018 is not captured by the same adverse structure.",
        "",
        "## Market-state definitions",
        "",
        "| Dimension | Exact causal definition | Lookback / timing | Bucketing | Coverage |",
        "|---|---|---|---|---:|",
    ]
    for dimension, definition in result["dimensions"].items():
        lines.append(
            f"| {dimension} | {definition['definition']} | {definition['horizon_sessions']} completed sessions at frozen weekly close | Expanding prior-only terciles after 20 prior observations | 263 dates |"
        )
    lines.extend(
        [
            "",
            "## Single-dimension maps",
            "",
            "| Dimension | LOW / MEDIUM / HIGH dates | LOW / MEDIUM / HIGH payoff | Early / late favorable spread | Classification |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in result["single_dimensions"]:
        lines.append(
            f"| {row['dimension']} | {row['low_dates']} / {row['medium_dates']} / {row['high_dates']} | "
            f"{_fmt(row['low_payoff'])} / {_fmt(row['medium_payoff'])} / {_fmt(row['high_payoff'])} | "
            f"{_fmt(row['early_favorable_spread'])} / {_fmt(row['late_favorable_spread'])} | `{row['classification']}` |"
        )
    lines.extend(
        [
            "",
            "Dispersion fails the revised coherence gate because its favorable spread reverses from early to late. Therefore Absolute State × Dispersion was not authorized for revised inference. The originally inspected Dispersion × Persistence map is likewise retired from revised inference.",
            "",
            "## Authorized two-dimensional map — Absolute State × Synchronization",
            "",
            "| Cell | Dates | Years | Early / late dates | Full / early / late payoff | Relative industry / broad | Support |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in result["authorized_map_rows"]:
        lines.append(
            f"| {row['first_state']}×{row['second_state']} | {row['decision_dates']} | {row['calendar_years']} | "
            f"{row['early_dates']} / {row['late_dates']} | {_fmt(row['mean_cohort_payoff'])} / "
            f"{_fmt(row['early_mean_cohort_payoff'])} / {_fmt(row['late_mean_cohort_payoff'])} | "
            f"{_fmt(row['relative_to_industry'])} / {_fmt(row['relative_to_broad'])} | {row['support']} |"
        )
    lines.extend(["", "## 2022 versus 2023 and 2018 secondary check", ""])
    for year in (2022, 2023, 2018):
        row = result["year_summary"][str(year)]
        lines.append(
            f"- {year}: {row['dominant_states']}; cohort payoff {_fmt(row['mean_cohort_payoff'])}; selected-industry d20 {_fmt(row['selected_industry_return'])}; relative industry/broad {_fmt(row['relative_to_industry'])}/{_fmt(row['relative_to_broad'])}."
        )
    lines.extend(
        [
            "",
            "2022 spent materially more decisions in LOW absolute state and HIGH synchronization than 2023, which was dominated by HIGH absolute state and LOW synchronization. 2018 is only a July-onward partial period and is dominated by MEDIUM absolute state, so it does not validate a common adverse habitat.",
            "",
            "## Absolute versus relative Champion value",
            "",
            f"Across {result['negative_cohort_diagnostics']['dates']} negative-payoff cohort dates, mean relative value remains {_fmt(result['negative_cohort_diagnostics']['relative_to_industry'])} versus selected industries and {_fmt(result['negative_cohort_diagnostics']['relative_to_broad'])} versus the broad proxy. Absolute long economics fail more often than relative selection Alpha.",
            "",
            "## Applicability classification",
            "",
            f"`{result['classification']}`.",
            "",
            "## Next research implication",
            "",
            "Do not run habitat-conditional deployment. Return capital to a second independent Alpha engine and strategy-diversification research. The frozen Dispersion Alpha question remains separate and unresolved.",
            "",
            "No champion rule, exposure, filter, threshold, feature, or outcome was recomputed or changed. Post-2023 outcomes and CY-011 remain unread.",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    original = json.loads(
        _resolve(spec["bound_original_evidence"]["original_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    placement = pd.read_csv(_resolve(spec["bound_original_evidence"]["original_placement"]["path"]))
    authorized_rows = [row for row in original["map_rows"] if row["map"] == AUTHORIZED_MAP]
    if len(authorized_rows) != 9:
        raise ReconciliationError("authorized original map is incomplete")
    translation = spec["taxonomy_translation"]
    single = _single_rows(original, translation)
    if (
        next(row for row in single if row["dimension"] == "CROSS_SECTIONAL_DISPERSION")[
            "classification"
        ]
        != "CHRONOLOGICALLY_UNSTABLE"
    ):
        raise ReconciliationError("dispersion unexpectedly passes the revised coherence gate")
    year_summary: dict[str, Any] = {}
    for year in (2018, 2022, 2023):
        original_year = original["year_placement_summary"][str(year)]
        year_summary[str(year)] = {
            **original_year,
            "selected_industry_return": (
                original_year["mean_cohort_payoff"] - original_year["relative_to_industry"]
            ),
            "authorized_map_cells": placement.loc[
                placement.year.eq(year)
                & placement.view.eq("map")
                & placement.name.eq(AUTHORIZED_MAP)
            ].to_dict(orient="records"),
        }
    final = original["final_diagnostics"]
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "classification": spec["final_classification"],
        "claim_boundary": spec["claim_boundary"],
        "provenance": spec["status"],
        "revised_user_contract_sha256": spec["revised_user_contract_sha256"],
        "original_evidence_commit": spec["actual_reconciliation_checkpoint"],
        "dimensions": original["dimensions"],
        "single_dimensions": single,
        "authorized_map": AUTHORIZED_MAP,
        "authorized_map_rows": authorized_rows,
        "conditional_map_not_authorized": spec["revised_scope"]["conditional_map_not_authorized"],
        "retired_original_map": spec["revised_scope"]["retired_original_map"],
        "year_summary": year_summary,
        "negative_cohort_diagnostics": {
            "dates": final["negative_cohort_dates"],
            "relative_to_industry": final["negative_cohort_relative_to_industry"],
            "relative_to_broad": final["negative_cohort_relative_to_broad"],
        },
        "boundaries": spec["scientific_boundary"],
        "post_2023_read": False,
        "cy011_read": False,
        "champion_changed": False,
        "deployment_replayed": False,
    }
    _atomic_write(REPORT_PATH, _render(result))
    result["artifacts"] = {
        REPORT_PATH.name: {
            "path": str(REPORT_PATH.relative_to(ROOT)),
            "sha256": sha256_file(REPORT_PATH),
        }
    }
    _atomic_write(RESULT_PATH, json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
