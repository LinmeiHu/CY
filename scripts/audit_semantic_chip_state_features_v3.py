#!/usr/bin/env python3
"""Audit the whole-book semantic-v3 chip-state materialization."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/processed/chip_state_features_semantic_v3_2018_2026"
DEFAULT_OUTPUT = ROOT / "data/audit/cyq_chip_state_features_semantic_v3_gate.json"
EPS = 1e-9


def _scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threads", type=int, default=10)
    args = parser.parse_args()

    manifest_path = args.input / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    completions = sorted(args.input.glob("bucket=*/complete.json"))
    completion_values = [
        json.loads(path.read_text(encoding="utf-8")) for path in completions
    ]
    output_glob = str(args.input / "bucket=*/data.parquet").replace("'", "''")
    source_glob = str(args.input / "_staging/rows/bucket=*/*.parquet").replace(
        "'", "''"
    )
    connection = duckdb.connect()
    connection.execute(f"PRAGMA threads={max(1, args.threads)}")
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW output AS SELECT * FROM read_parquet('{output_glob}')"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW source AS SELECT * FROM read_parquet('{source_glob}')"
    )

    aggregate_row = connection.execute(
        f"""
        SELECT
          count(*) AS rows,
          count(DISTINCT (symbol, trade_date)) AS distinct_keys,
          count(*) FILTER (WHERE strict_sample) AS strict_rows,
          count(*) FILTER (WHERE semantic_version = 'semantic-v3') AS semantic_rows,
          count(DISTINCT state_version) AS state_versions,
          count(DISTINCT config_sha256) AS config_versions,
          count(DISTINCT code_sha256) AS code_versions,
          count(*) FILTER (WHERE chip_input_valid AND (mass_sum IS NULL OR abs(mass_sum - 1.0) > {EPS})) AS mass_failures,
          max(abs(mass_sum - 1.0)) FILTER (WHERE chip_input_valid) AS max_mass_error,
          count(*) FILTER (WHERE strict_sample != (
            daily_hard_valid AND (minute_hard_valid OR minute_requirement_waived)
            AND state_chain_valid AND warmup_count >= 60
          )) AS strict_logic_failures,
          count(*) FILTER (WHERE strict_sample AND (
            available_at IS NULL OR available_at < trade_date + INTERVAL 15 HOUR
          )) AS availability_before_close,
          count(*) FILTER (WHERE i90_lower IS NOT NULL AND i90_lower > i90_upper) AS i90_order_failures,
          count(*) FILTER (WHERE i70_lower IS NOT NULL AND i70_lower > i70_upper) AS i70_order_failures,
          count(*) FILTER (WHERE i90_lower IS NOT NULL AND (
            p05 IS NULL OR p95 IS NULL OR abs(p05 - i90_lower) > {EPS} OR abs(p95 - i90_upper) > {EPS}
          )) AS i90_quantile_failures,
          count(*) FILTER (WHERE i70_lower IS NOT NULL AND (
            p15 IS NULL OR p85 IS NULL OR abs(p15 - i70_lower) > {EPS} OR abs(p85 - i70_upper) > {EPS}
          )) AS i70_quantile_failures,
          count(*) FILTER (WHERE i90_lower IS NOT NULL AND (
            abs(i90_width_pct - (i90_upper / NULLIF(i90_lower, 0) - 1.0)) > {EPS}
          )) AS i90_width_failures,
          count(*) FILTER (WHERE i70_lower IS NOT NULL AND (
            abs(i70_width_pct - (i70_upper / NULLIF(i70_lower, 0) - 1.0)) > {EPS}
          )) AS i70_width_failures,
          count(*) FILTER (WHERE migration_mass IS NOT NULL AND (
            migration_mass < -{EPS} OR migration_mass > 1.0 + {EPS}
          )) AS migration_range_failures,
          count(*) FILTER (WHERE i90_base_retention IS NOT NULL AND (
            i90_base_retention < -{EPS} OR i90_base_retention > 1.0 + {EPS}
          )) AS i90_retention_range_failures,
          count(*) FILTER (WHERE i70_base_retention IS NOT NULL AND (
            i70_base_retention < -{EPS} OR i70_base_retention > 1.0 + {EPS}
          )) AS i70_retention_range_failures,
          count(*) FILTER (WHERE
            (peak_count IS NULL AND peaks_price_json IS NOT NULL)
            OR (peak_count IS NOT NULL AND (
              peaks_price_json IS NULL OR json_array_length(peaks_price_json) != peak_count
            ))
          ) AS peak_json_count_failures,
          count(*) FILTER (WHERE peak_count > 0 AND (
            main_peak_center IS NULL OR main_peak_mass IS NULL
            OR abs(main_peak_center - try_cast(json_extract_string(peaks_json, '$[0].center_price') AS DOUBLE)) > {EPS}
            OR abs(main_peak_mass - try_cast(json_extract_string(peaks_json, '$[0].mass') AS DOUBLE)) > {EPS}
          )) AS main_peak_failures,
          count(*) FILTER (WHERE i90_base_retention IS NOT NULL AND i90_base_retention > 1.0 + {EPS}) AS frozen_band_failures
        FROM output
        """
    ).fetchone()
    columns = [item[0] for item in connection.description]
    metrics: dict[str, Any] = dict(zip(columns, aggregate_row, strict=True))
    metrics["max_mass_error"] = float(metrics["max_mass_error"] or 0.0)

    joined = connection.execute(
        """
        SELECT
          count(*) FILTER (WHERE o.symbol IS NULL) AS source_missing_output,
          count(*) FILTER (WHERE o.symbol IS NOT NULL AND (
            o.daily_snapshot_id IS DISTINCT FROM s.daily_snapshot_id OR
            o.minute_snapshot_id IS DISTINCT FROM s.minute_snapshot_id
          )) AS snapshot_mismatches,
          count(*) FILTER (WHERE o.symbol IS NOT NULL AND (
            o.available_at < s.daily_available_at OR
            (o.minute_hard_valid AND o.available_at < s.minute_available_at) OR
            o.available_at > greatest(s.decision_at, o.available_at)
          )) AS derived_decision_failures
        FROM source s
        LEFT JOIN output o USING (symbol, trade_date)
        """
    ).fetchone()
    columns = [item[0] for item in connection.description]
    metrics.update(dict(zip(columns, joined, strict=True)))
    metrics["output_missing_source"] = _scalar(
        connection,
        """
        SELECT count(*) FROM output o
        ANTI JOIN source s USING (symbol, trade_date)
        """,
    )
    connection.close()

    physical = {
        "expected_buckets": int(manifest["buckets"]),
        "completed_buckets": len(completions),
        "temporary_files": len(list(args.input.glob("bucket=*/*.tmp.parquet"))),
        "completion_rows": sum(int(item["rows"]) for item in completion_values),
        "completion_strict_rows": sum(
            int(item["strict_rows"]) for item in completion_values
        ),
    }
    checks = {
        "all_buckets_complete": physical["completed_buckets"] == physical["expected_buckets"],
        "no_temporary_files": physical["temporary_files"] == 0,
        "manifest_rows_match": metrics["rows"] == int(manifest["rows"]),
        "completion_rows_match": metrics["rows"] == physical["completion_rows"],
        "strict_rows_match": metrics["strict_rows"] == int(manifest["strict_rows"]),
        "unique_keys": metrics["rows"] == metrics["distinct_keys"],
        "source_has_exactly_one_output": metrics["source_missing_output"] == 0
        and metrics["output_missing_source"] == 0,
        "snapshots_preserved": metrics["snapshot_mismatches"] == 0,
        "availability_is_causal": metrics["derived_decision_failures"] == 0
        and metrics["availability_before_close"] == 0,
        "chip_mass_conserved": metrics["mass_failures"] == 0,
        "strict_sample_gate_exact": metrics["strict_logic_failures"] == 0,
        "semantic_version_complete": metrics["semantic_rows"] == metrics["rows"]
        and metrics["state_versions"] == 1,
        "single_build_inputs": metrics["config_versions"] == 1
        and metrics["code_versions"] == 1,
        "quantile_intervals_exact": metrics["i90_order_failures"] == 0
        and metrics["i70_order_failures"] == 0
        and metrics["i90_quantile_failures"] == 0
        and metrics["i70_quantile_failures"] == 0,
        "interval_widths_exact": metrics["i90_width_failures"] == 0
        and metrics["i70_width_failures"] == 0,
        "migration_and_retention_ranges": metrics["migration_range_failures"] == 0
        and metrics["i90_retention_range_failures"] == 0
        and metrics["i70_retention_range_failures"] == 0,
        "peak_fields_consistent": metrics["peak_json_count_failures"] == 0
        and metrics["main_peak_failures"] == 0,
        "frozen_band_retention_bounded": metrics["frozen_band_failures"] == 0,
    }
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "input": str(args.input.resolve()),
        "manifest": str(manifest_path.resolve()),
        "physical": physical,
        "metrics": metrics,
        "checks": checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
