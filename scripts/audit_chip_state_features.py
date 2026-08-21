#!/usr/bin/env python3
"""Audit one frozen chip-state feature build with a single joined scan."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from cyq_game.config import load_config

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/processed/chip_state_features_2018_2026_v1"
DEFAULT_OUTPUT = ROOT / "data/audit/cyq_chip_state_features_gate.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research.yaml")
    parser.add_argument("--threads", type=int, default=10)
    args = parser.parse_args()

    manifest = _load(args.input / "manifest.json")
    expected_buckets = int(manifest["buckets"])
    completions = sorted(args.input.glob("bucket=*/complete.json"))
    completion_values = [_load(path) for path in completions]
    physical = {
        "expected_buckets": expected_buckets,
        "completed_buckets": len(completions),
        "temporary_files": len(list(args.input.glob("bucket=*/*.tmp.parquet"))),
        "completion_rows": sum(int(item["rows"]) for item in completion_values),
        "completion_strict_rows": sum(
            int(item["strict_rows"]) for item in completion_values
        ),
    }

    output_glob = str(args.input / "bucket=*/data.parquet").replace("'", "''")
    source_glob = str(args.input / "_staging/rows/bucket=*/*.parquet").replace("'", "''")
    warmup_days = load_config(args.config).chip.warmup_days
    connection = duckdb.connect()
    connection.execute(f"PRAGMA threads={max(1, args.threads)}")
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW output AS SELECT * FROM read_parquet('{output_glob}')"
    )
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW source AS SELECT * FROM read_parquet('{source_glob}')"
    )
    aggregate = connection.execute(
        f"""
        SELECT
          count(*) AS rows,
          count(DISTINCT (symbol, trade_date)) AS distinct_keys,
          count(*) FILTER (WHERE strict_sample) AS strict_rows,
          count(*) FILTER (WHERE chip_input_valid) AS chip_valid_rows,
          count(*) FILTER (
            WHERE chip_input_valid
              AND (mass_sum IS NULL OR abs(mass_sum - 1.0) > 1e-9)
          ) AS mass_failures,
          max(abs(mass_sum - 1.0)) FILTER (WHERE chip_input_valid) AS max_mass_error,
          count(*) FILTER (
            WHERE strict_sample != (
              daily_hard_valid AND minute_hard_valid AND state_chain_valid
              AND warmup_count >= {warmup_days}
            )
          ) AS strict_logic_failures,
          count(*) FILTER (
            WHERE strict_sample AND (
              available_at IS NULL OR available_at < trade_date + INTERVAL 15 HOUR
            )
          ) AS availability_before_close,
          count(DISTINCT state_version) AS state_versions,
          count(DISTINCT config_sha256) AS config_versions,
          count(DISTINCT code_sha256) AS code_versions
        FROM output
        """
    ).fetchone()
    columns = [item[0] for item in connection.description]
    metrics = dict(zip(columns, aggregate, strict=True))
    metrics["max_mass_error"] = float(metrics["max_mass_error"] or 0.0)

    joined = connection.execute(
        """
        SELECT
          count(*) FILTER (WHERE o.symbol IS NULL) AS source_missing_output,
          count(*) FILTER (
            WHERE o.symbol IS NOT NULL AND (
              o.daily_snapshot_id IS DISTINCT FROM s.daily_snapshot_id OR
              o.minute_snapshot_id IS DISTINCT FROM s.minute_snapshot_id
            )
          ) AS snapshot_mismatches,
          count(*) FILTER (
            WHERE o.symbol IS NOT NULL AND (
              o.available_at < s.daily_available_at OR
              (o.minute_hard_valid AND o.available_at < s.minute_available_at)
            )
          ) AS availability_failures
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

    checks = {
        "all_buckets_complete": physical["completed_buckets"] == expected_buckets,
        "no_temporary_files": physical["temporary_files"] == 0,
        "manifest_rows_match": metrics["rows"] == int(manifest["rows"]),
        "completion_rows_match": metrics["rows"] == physical["completion_rows"],
        "manifest_strict_rows_match": metrics["strict_rows"]
        == int(manifest["strict_rows"]),
        "completion_strict_rows_match": metrics["strict_rows"]
        == physical["completion_strict_rows"],
        "unique_keys": metrics["rows"] == metrics["distinct_keys"],
        "source_has_exactly_one_output": metrics["source_missing_output"] == 0
        and metrics["output_missing_source"] == 0,
        "snapshots_preserved": metrics["snapshot_mismatches"] == 0,
        "availability_is_causal": metrics["availability_failures"] == 0
        and metrics["availability_before_close"] == 0,
        "chip_mass_conserved": metrics["mass_failures"] == 0,
        "strict_sample_gate_exact": metrics["strict_logic_failures"] == 0,
        "single_version": metrics["state_versions"] == 1
        and metrics["config_versions"] == 1
        and metrics["code_versions"] == 1,
    }
    passed = all(checks.values())
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "input": str(args.input.resolve()),
        "manifest": str((args.input / "manifest.json").resolve()),
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
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
