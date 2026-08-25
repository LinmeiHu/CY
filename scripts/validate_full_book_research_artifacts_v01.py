#!/usr/bin/env python3
"""Fail-closed validation for the 2020-2023 full-book research artifacts.

This validator separates three questions that must not be conflated:

1. Are the persisted artifacts complete and temporally safe?
2. Do the strict chip-state integrity checks pass?
3. Does the current feature implementation faithfully represent the book?

The third question is intentionally allowed to remain conditional.  A
passing mass/timing audit is not evidence that a proxy feature is the book's
definition.  The validator writes an auditable result and exits non-zero only
for hard artifact or integrity failures.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PARAMETER_COUNT = 1_944
EXPECTED_BATCH_COUNT = 81
EXPECTED_SIGNAL_END = date(2023, 12, 29)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def check(name: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def read_candidate_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--grid",
        type=Path,
        default=ROOT / "data/audit/full_book_b_s_grid_2020_2023_v02_boundaryfix_20260822",
    )
    parser.add_argument(
        "--formula",
        type=Path,
        default=ROOT / "data/audit/formula_truth_2020_2023_v01/result.json",
    )
    parser.add_argument(
        "--strict-exit",
        type=Path,
        default=ROOT / "data/audit/exit_semantics_2020_2023_v02_s5confirm/result.json",
    )
    parser.add_argument(
        "--warning-exit",
        type=Path,
        default=ROOT / "data/audit/exit_semantics_warning_2020_2023_v02_s5confirm/result.json",
    )
    parser.add_argument(
        "--comparison",
        type=Path,
        default=ROOT / "data/audit/exit_semantics_comparison_s5fix_2020_2023_v01/candidate_comparison.csv",
    )
    parser.add_argument(
        "--partial",
        type=Path,
        default=ROOT / "data/audit/partial_reduction_2020_2023_v02_s5confirm/result.json",
    )
    parser.add_argument(
        "--portfolio",
        type=Path,
        default=ROOT / "data/audit/portfolio_2020_2023_v02_s5confirm/result.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/audit/full_book_quality_gate_2020_2023_v01/result.json",
    )
    args = parser.parse_args()

    grid_dir = args.grid
    grid_result = load_json(grid_dir / "result.json")
    grid_manifest = load_json(grid_dir / "run_manifest.json")
    formula = load_json(args.formula)
    strict_exit = load_json(args.strict_exit)
    warning_exit = load_json(args.warning_exit)
    partial = load_json(args.partial)
    portfolio = load_json(args.portfolio)

    batch_files = sorted(grid_dir.glob("batch_*.parquet"))
    parquet_glob = str(grid_dir / "batch_*.parquet").replace("'", "''")
    con = duckdb.connect()
    grid_stats = con.execute(
        f"""SELECT count(DISTINCT param_id), count(*), min(signal_date), max(signal_date),
                   count(*) FILTER (WHERE signal_date > DATE '2023-12-29'),
                   count(*) FILTER (WHERE sample_group NOT IN ('DISCOVERY_2020_2022', 'TIMEOUT_2023'))
            FROM read_parquet('{parquet_glob}')"""
    ).fetchone()
    con.close()
    distinct_params, event_rows, min_signal, max_signal, future_rows, bad_groups = grid_stats

    formula_checks = formula["checks"]
    strict_integrity = formula_checks["strict_feature_integrity"]
    timing = formula_checks["base_timing_integrity"]
    expected_hash = grid_result.get("config_sha256")
    config_path = Path(grid_result["config"])
    config_hash = sha256_file(config_path) if config_path.exists() else None

    hard_checks = [
        check("grid_batch_count", len(batch_files) == EXPECTED_BATCH_COUNT, len(batch_files)),
        check("grid_parameter_count", distinct_params == EXPECTED_PARAMETER_COUNT, distinct_params),
        check("grid_signal_rows_nonempty", event_rows > 0, event_rows),
        check("grid_signal_date_lower_bound", str(min_signal) == "2020-01-02", str(min_signal)),
        check("grid_signal_date_upper_bound", max_signal <= EXPECTED_SIGNAL_END, str(max_signal)),
        check("grid_no_future_signal_rows", future_rows == 0, future_rows),
        check("grid_sample_groups", bad_groups == 0, bad_groups),
        check("grid_holdout_not_accessed", grid_result.get("holdout_accessed") is False, grid_result.get("holdout_accessed")),
        check("grid_manifest_holdout_not_accessed", grid_manifest.get("holdout_accessed") is False, grid_manifest.get("holdout_accessed")),
        check("config_hash_matches", config_hash == expected_hash, {"actual": config_hash, "recorded": expected_hash}),
        check("formula_mass_conserved", strict_integrity["mass_not_conserved"] == 0, strict_integrity["mass_not_conserved"]),
        check("formula_mass_not_null", strict_integrity["null_mass_sum"] == 0, strict_integrity["null_mass_sum"]),
        check("formula_quantiles_ordered", strict_integrity["quantile_order_violations"] == 0, strict_integrity["quantile_order_violations"]),
        check("formula_concentration_range", strict_integrity["concentration_range_violations"] == 0, strict_integrity["concentration_range_violations"]),
        check("formula_retention_range", strict_integrity["retention_range_violations"] == 0, strict_integrity["retention_range_violations"]),
        check("formula_lineage_complete", strict_integrity["missing_lineage"] == 0, strict_integrity["missing_lineage"]),
        check("timing_decision_before_bar", timing["decision_before_bar"] == 0, timing["decision_before_bar"]),
        check("timing_decision_before_feature", timing["decision_before_feature"] == 0, timing["decision_before_feature"]),
        check("timing_snapshot_match", timing["snapshot_mismatch"] == 0, timing["snapshot_mismatch"]),
        check("timing_no_same_bar_fill", timing["same_bar_or_past_fill"] == 0, timing["same_bar_or_past_fill"]),
        check("timing_next_open_present", timing["missing_next_open"] == 0, timing["missing_next_open"]),
        check("strict_exit_complete", strict_exit.get("status") == "COMPLETE", strict_exit.get("status")),
        check("warning_exit_complete", warning_exit.get("status") == "COMPLETE", warning_exit.get("status")),
        check("strict_exit_holdout_not_accessed", strict_exit.get("holdout_accessed") is False, strict_exit.get("holdout_accessed")),
        check("warning_exit_holdout_not_accessed", warning_exit.get("holdout_accessed") is False, warning_exit.get("holdout_accessed")),
        check("partial_holdout_not_accessed", partial.get("holdout_accessed") is False, partial.get("holdout_accessed")),
        check("portfolio_holdout_not_accessed", portfolio.get("holdout_accessed") is False, portfolio.get("holdout_accessed")),
    ]

    comparison_rows = read_candidate_rows(args.comparison)
    eligible_rows = [
        row for row in comparison_rows
        if row.get("every_year_rate_eligible", "").lower() == "true"
    ]
    stable_positive_rows = [
        row for row in eligible_rows
        if float(row["discovery_mean"]) > 0.0 and float(row["timeout_mean"]) > 0.0
    ]
    portfolio_summary = args.portfolio.parent / "portfolio_summary.csv"
    portfolio_rows = read_candidate_rows(portfolio_summary)
    portfolio_returns = [float(row["total_return"]) for row in portfolio_rows]
    evidence_checks = [
        check("no_stable_positive_candidate", not stable_positive_rows, len(stable_positive_rows)),
        check("portfolio_best_return_not_positive", max(portfolio_returns) < 0.0, max(portfolio_returns)),
        check("target_band_comparison_rows_present", len(eligible_rows) > 0, len(eligible_rows)),
    ]

    semantic_gaps = formula_checks.get("feature_field_semantics", {})
    result = {
        "audit_id": "CYQ-FULL-BOOK-QUALITY-GATE-2020-2023-V01",
        "config": str(config_path),
        "config_sha256": config_hash,
        "inputs": {
            "grid": str(grid_dir),
            "formula": str(args.formula),
            "strict_exit": str(args.strict_exit),
            "warning_exit": str(args.warning_exit),
            "comparison": str(args.comparison),
            "partial": str(args.partial),
            "portfolio": str(args.portfolio),
        },
        "hard_checks": hard_checks,
        "evidence_checks": evidence_checks,
        "semantic_fidelity": {
            "status": "INCOMPLETE_CONDITIONAL",
            "reason": "The strict integrity/timing checks pass, but several book-defined chip fields are still proxies or absent.",
            "gaps": semantic_gaps,
        },
        "summary": {
            "hard_checks_passed": all(item["passed"] for item in hard_checks),
            "evidence_checks_passed": all(item["passed"] for item in evidence_checks),
            "eligible_candidate_count": len(eligible_rows),
            "stable_positive_candidate_count": len(stable_positive_rows),
            "portfolio_best_total_return": max(portfolio_returns),
            "strict_feature_rows": strict_integrity["strict_rows"],
            "event_rows": event_rows,
            "parameter_count": distinct_params,
            "batch_count": len(batch_files),
            "promotion_status": "BLOCKED_PENDING_SEMANTIC_REIMPLEMENTATION_AND_OOS_VALIDATION",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")

    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["summary"]["hard_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
