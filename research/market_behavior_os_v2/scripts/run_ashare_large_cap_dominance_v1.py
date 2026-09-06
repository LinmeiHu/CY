#!/usr/bin/env python3
"""Validate the frozen post-hoc large-cap-dominance hypothesis."""

from __future__ import annotations

import json
import math
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_ashare_small_cap_premium_v1 as base  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-LARGE-CAP-DOMINANCE-V1_spec.json"
TABLE_PATH = PROGRAM / "artifacts/ASHARE-LARGE-CAP-DOMINANCE-V1_bucket_table.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-LARGE-CAP-DOMINANCE-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-LARGE-CAP-DOMINANCE-V1_report.md"
EXPECTED_SPEC_SHA256 = "d47a36a377aae6f516ad488c44632b5d509c067080f110b14ec8b2f1cc1c99c5"
VALIDATION_START = date(2021, 1, 1)
END = date(2023, 12, 29)


class LargeCapDominanceError(RuntimeError):
    """Fail-closed large-cap validation error."""


def _load_spec() -> dict[str, Any]:
    if base.sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise LargeCapDominanceError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_FIXED_VALIDATION_OUTCOME_ACCESS":
        raise LargeCapDominanceError("spec is not frozen")
    for binding in spec["inputs"].values():
        path = base._resolve(binding["path"])
        if not path.is_file() or base.sha256_file(path) != binding["sha256"]:
            raise LargeCapDominanceError(f"bound input changed: {path}")
    prior = json.loads(base._resolve(spec["inputs"]["small_cap_result"]["path"]).read_text())
    observed = prior["generation"]["statistics"]["generation_2018_2020"]
    frozen = spec["frozen_generation_evidence"]
    if not math.isclose(
        observed["q5_mean"] - observed["q1_mean"], frozen["q5_minus_q1"], abs_tol=1e-14
    ):
        raise LargeCapDominanceError("generation evidence changed")
    return spec


def _summaries(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    periods = {"validation_2021_2023": (VALIDATION_START, END)}
    periods.update(
        {f"year_{year}": (date(year, 1, 1), date(year, 12, 31)) for year in range(2021, 2024)}
    )
    tables: list[pd.DataFrame] = []
    stats: dict[str, Any] = {}
    for name, (start, end) in periods.items():
        table = base._bucket_table(base._period_panel(panel, start, end), name)
        tables.append(table)
        indexed = table.set_index("size_quintile")
        means = [float(indexed.loc[index, "mean_net_return"]) for index in range(1, 6)]
        stats[name] = {
            "q1_mean": means[0],
            "q5_mean": means[-1],
            "q5_minus_q1": means[-1] - means[0],
            "favorable_large_cap_adjacent_steps": sum(
                means[index] < means[index + 1] for index in range(4)
            ),
            "q1_severe_loss": float(indexed.loc[1, "severe_loss_fraction"]),
            "q5_severe_loss": float(indexed.loc[5, "severe_loss_fraction"]),
            "q5_median": float(indexed.loc[5, "median_net_return"]),
            "q5_positive_fraction": float(indexed.loc[5, "positive_fraction"]),
            "decision_dates": int(indexed.decision_dates.min()),
            "entry_execution_coverage": float(indexed.entry_execution_coverage.min()),
        }
    return pd.concat(tables, ignore_index=True), stats


def _render(result: dict[str, Any]) -> str:
    full = result["validation"]["statistics"]["validation_2021_2023"]
    lines = [
        "# A-share post-hoc large-cap dominance V1",
        "",
        "## Boundary",
        "",
        (
            "The direction was generated after the 2018--2020 canonical small-cap test "
            "failed. The frozen 2021--2023 check is sequential development validation, "
            "not OOS confirmation. Post-2023 outcomes and CY-011 were not read."
        ),
        "",
        "## Fixed validation",
        "",
        f"- Q5 mean net h20: {full['q5_mean']:.3%}",
        f"- Q5 minus Q1: {full['q5_minus_q1']:.3%}",
        f"- Monotonic large-cap steps: {full['favorable_large_cap_adjacent_steps']}/4",
        f"- Every frozen requirement passed: `{result['validation']['passed']}`",
        "",
        "| Period | Q | N | Mean net | Median net | Win rate | Severe loss |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["bucket_records"]:
        lines.append(
            f"| {row['period']} | {row['size_quintile']} | {row['N']:,} | "
            f"{row['mean_net_return']:.3%} | {row['median_net_return']:.3%} | "
            f"{row['positive_fraction']:.2%} | {row['severe_loss_fraction']:.2%} |"
        )
    lines.extend(["", "## Frozen executable translation", ""])
    if result["replay"] is None:
        lines.append(
            "Validation failed; no portfolio replay was run and the local family is closed."
        )
    else:
        replay = result["replay"]
        lines.extend(
            [
                (
                    "Equal-weight the largest size decile every 20 sessions; "
                    "next-open entry and h20 next-legal-open exit."
                ),
                "",
                f"- Annualized return: {replay['annualized_return']:.2%}",
                f"- Maximum drawdown: {replay['maximum_drawdown']:.2%}",
                f"- Total return: {replay['total_return']:.2%}",
                f"- Daily Sharpe: {replay['daily_sharpe']:.3f}",
                f"- Entries: {replay['entries']:,}",
                f"- Return target met: `{replay['target_annualized_met']}`",
                f"- Drawdown target met: `{replay['target_drawdown_met']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            result["interpretation"],
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Bucket table SHA-256: `{result['hashes']['bucket_table_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    base_spec = json.loads(base.SPEC_PATH.read_text(encoding="utf-8"))
    paths, identity = base._validate_input(base_spec)
    with tempfile.TemporaryDirectory(prefix="ashare-large-cap-") as temporary:
        signals, calendar, input_audit = base._build_signal_panel(paths, Path(temporary))
    validation_signals = base._period_panel(signals, VALIDATION_START, END)
    rows = base._query_path_rows(
        paths, base._path_links(validation_signals, calendar, base.HORIZON)
    )
    panel = base._attach_outcomes(
        validation_signals,
        rows,
        spec["fixed_validation"]["cost_per_side_bps"] / 10000.0,
    )
    bucket_table, statistics = _summaries(panel)
    full = statistics["validation_2021_2023"]
    requirements = spec["fixed_validation"]["all_required"]
    checks = {
        "q5_mean_positive": full["q5_mean"] > 0,
        "q5_minus_q1_positive": full["q5_minus_q1"] > 0,
        "each_year_spread_positive": all(
            statistics[f"year_{year}"]["q5_minus_q1"] > 0 for year in (2021, 2022, 2023)
        ),
        "q5_severe_loss_no_worse": full["q5_severe_loss"] <= full["q1_severe_loss"],
        "adjacent_steps": full["favorable_large_cap_adjacent_steps"]
        >= requirements["minimum_favorable_adjacent_steps"],
    }
    passed = all(checks.values())
    base._atomic_write(
        TABLE_PATH,
        bucket_table.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    replay = None
    if passed:
        selected = signals.loc[signals.size_decile.eq(10)].copy()
        replay_rows = base._query_path_rows(
            paths, base._path_links(selected, calendar, base.HORIZON + 21)
        )
        replay = base._replay(
            selected,
            replay_rows,
            calendar,
            {
                "executable_translation": spec["executable_translation"],
                "success_target": spec["success_target"],
            },
        )
    if not passed:
        classification = "FIXED_VALIDATION_FAILED_LARGE_CAP_FAMILY_CLOSED"
        interpretation = (
            "The post-hoc large-cap direction failed at least one frozen validation "
            "requirement. No portfolio or neighboring cutoff was tested."
        )
    elif replay and replay["target_annualized_met"] and replay["target_drawdown_met"]:
        classification = "USER_OPTIMIZATION_TARGET_MET"
        interpretation = (
            "The frozen post-hoc large-cap engine met both user portfolio objectives "
            "on consumed development history."
        )
    else:
        classification = "DEVELOPMENT_ALPHA_TARGET_NOT_MET"
        interpretation = (
            "The large-cap relation survived the fixed development validation but its "
            "single executable translation did not meet both user objectives."
        )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "classification": classification,
        "hypothesis_origin": spec["hypothesis_origin"],
        "claim_boundary": spec["claim_boundary"],
        "input_identity": identity,
        "input_audit": input_audit,
        "validation": {"passed": passed, "checks": checks, "statistics": statistics},
        "replay": replay,
        "bucket_records": [base._clean(row) for row in bucket_table.to_dict("records")],
        "interpretation": interpretation,
        "boundaries": {"post_2023_read": False, "cy011_read": False, "oos_claim": False},
        "hashes": {
            "spec_sha256": base.sha256_file(SPEC_PATH),
            "bucket_table_sha256": base.sha256_file(TABLE_PATH),
        },
    }
    base._atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["report_sha256"] = base.sha256_file(REPORT_PATH)
    base._atomic_write(
        RESULT_PATH, json.dumps(base._clean(result), indent=2, sort_keys=True) + "\n"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(base._clean(run()), indent=2, sort_keys=True))
