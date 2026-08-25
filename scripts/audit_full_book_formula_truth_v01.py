#!/usr/bin/env python3
"""Read-only audit of the causal chip fields used by the full-book probe.

This script deliberately reports field semantics instead of silently treating
the current implementation as the book's notation.  It is safe to run before
or after a research scan: it only reads registered research inputs and writes
an append-only audit result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/full_book_research_2020_2023_v01.yaml"


def sql_path(path: str) -> str:
    return path.replace("'", "''")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def scalar(con: duckdb.DuckDBPyConnection, query: str) -> Any:
    return con.execute(query).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--base", type=Path, default=None)
    ap.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/audit/formula_truth_2020_2023_v01",
    )
    args = ap.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("config root must be a mapping")
    feature_glob = ROOT / str(config["feature_asset"])
    base = args.base
    if base is None:
        candidates = sorted(
            (ROOT / "data/audit").glob(
                "full_book_b_s_grid_2020_2023_v02_boundaryfix_20260822/base_*.parquet"
            )
        )
        if not candidates:
            raise FileNotFoundError("no cached causal base parquet found")
        base = candidates[-1]
    if not feature_glob.parent.parent.exists():
        raise FileNotFoundError(feature_glob)
    if not base.exists():
        raise FileNotFoundError(base)

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    feature = sql_path(str(feature_glob))
    base_sql = sql_path(str(base))
    con = duckdb.connect()
    con.execute("PRAGMA enable_progress_bar=false")
    try:
        feature_cols = [row[0] for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{feature}', union_by_name=true)"
        ).fetchall()]
        base_cols = [row[0] for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{base_sql}')"
        ).fetchall()]
        required_feature = {
            "symbol", "trade_date", "available_at", "daily_snapshot_id", "minute_snapshot_id", "state_version",
            "mass_sum", "p01", "p10", "p50", "p90", "p99", "peaks_json",
            "concentration_20", "base_retention",
        }
        required_base = {
            "symbol", "trade_date", "decision_at", "bar_decision_at",
            "feature_available_at", "daily_snapshot_id", "snapshot_id", "entry_date",
            "entry_open", "prev_p90", "prev_peak1_center",
        }
        missing_feature = sorted(required_feature - set(feature_cols))
        missing_base = sorted(required_base - set(base_cols))
        if missing_feature or missing_base:
            raise RuntimeError(
                f"required schema missing: feature={missing_feature}, base={missing_base}"
            )

        checks: dict[str, Any] = {
            "feature_rows": int(scalar(con, f"SELECT count(*) FROM read_parquet('{feature}', union_by_name=true)")),
            "base_rows": int(scalar(con, f"SELECT count(*) FROM read_parquet('{base_sql}')")),
            "feature_range": [
                str(scalar(con, f"SELECT min(trade_date) FROM read_parquet('{feature}', union_by_name=true)")),
                str(scalar(con, f"SELECT max(trade_date) FROM read_parquet('{feature}', union_by_name=true)")),
            ],
            "base_range": [
                str(scalar(con, f"SELECT min(trade_date) FROM read_parquet('{base_sql}')")),
                str(scalar(con, f"SELECT max(trade_date) FROM read_parquet('{base_sql}')")),
            ],
            "feature_schema": feature_cols,
            "base_schema": base_cols,
            "missing_feature_columns": missing_feature,
            "missing_base_columns": missing_base,
        }
        feature_checks = con.execute(f"""
          SELECT
            min(mass_sum) AS min_mass_sum,
            max(mass_sum) AS max_mass_sum,
            count(*) FILTER (WHERE mass_sum IS NULL) AS null_mass_sum,
            count(*) FILTER (WHERE abs(mass_sum-1.0)>1e-8) AS mass_not_conserved,
            count(*) FILTER (WHERE NOT (p01<=p10 AND p10<=p50 AND p50<=p90 AND p90<=p99)) AS quantile_order_violations,
            count(*) FILTER (WHERE concentration_20 IS NULL OR concentration_20<-1e-8 OR concentration_20>1+1e-8) AS concentration_range_violations,
            count(*) FILTER (WHERE base_retention IS NULL OR base_retention<0 OR base_retention>1) AS retention_range_violations,
            count(*) FILTER (WHERE available_at IS NULL OR daily_snapshot_id IS NULL
                              OR minute_snapshot_id IS NULL OR state_version IS NULL) AS missing_lineage
          FROM read_parquet('{feature}', union_by_name=true)
        """).fetchone()
        feature_names = [x[0] for x in con.description]
        checks["feature_integrity"] = dict(zip(feature_names, feature_checks, strict=True))
        strict_checks = con.execute(f"""
          SELECT
            count(*) AS strict_rows,
            min(mass_sum) AS min_mass_sum,
            max(mass_sum) AS max_mass_sum,
            count(*) FILTER (WHERE mass_sum IS NULL) AS null_mass_sum,
            count(*) FILTER (WHERE abs(mass_sum-1.0)>1e-8) AS mass_not_conserved,
            count(*) FILTER (WHERE NOT (p01<=p10 AND p10<=p50 AND p50<=p90 AND p90<=p99)) AS quantile_order_violations,
            count(*) FILTER (WHERE concentration_20 IS NULL OR concentration_20<-1e-8 OR concentration_20>1+1e-8) AS concentration_range_violations,
            count(*) FILTER (WHERE base_retention IS NULL OR base_retention<0 OR base_retention>1) AS retention_range_violations,
            count(*) FILTER (WHERE available_at IS NULL OR daily_snapshot_id IS NULL
                              OR minute_snapshot_id IS NULL OR state_version IS NULL) AS missing_lineage
          FROM read_parquet('{feature}', union_by_name=true)
          WHERE strict_sample AND chip_input_valid AND daily_hard_valid
            AND minute_hard_valid AND state_chain_valid
        """).fetchone()
        strict_names = [x[0] for x in con.description]
        checks["strict_feature_integrity"] = dict(zip(strict_names, strict_checks, strict=True))
        checks["feature_field_semantics"] = {
            "p10_p90": "quantile probabilities 0.10/0.90 in current implementation; not book I90 Q05/Q95",
            "book_i90": "not currently materialized as a named field",
            "book_i70": "not currently materialized as a named field",
            "concentration_20": "maximum mass in any multiplicative price window [p, 1.2p]; custom feature, not book I90 width",
            "peaks_json": "Gaussian-smoothed local maxima sorted by peak mass; index 0 is dominant mass peak, not guaranteed highest-price peak",
            "base_retention": "current mass retained in the initial fixed p10-p90 band; not a dynamic low-cost retention band",
        }
        base_checks = con.execute(f"""
          SELECT
            count(*) FILTER (WHERE decision_at < bar_decision_at) AS decision_before_bar,
            count(*) FILTER (WHERE decision_at < feature_available_at) AS decision_before_feature,
            count(*) FILTER (WHERE daily_snapshot_id <> snapshot_id) AS snapshot_mismatch,
            count(*) FILTER (WHERE entry_date IS NOT NULL AND entry_date<=trade_date) AS same_bar_or_past_fill,
            count(*) FILTER (WHERE entry_date IS NOT NULL AND entry_open IS NULL) AS missing_next_open,
            count(*) FILTER (WHERE trade_date BETWEEN DATE '2020-01-02' AND DATE '2023-12-29'
                              AND (decision_at IS NULL OR feature_available_at IS NULL)) AS missing_timing,
            min(decision_at-bar_decision_at) AS min_decision_lag,
            max(decision_at-bar_decision_at) AS max_decision_lag
          FROM read_parquet('{base_sql}')
        """).fetchone()
        base_names = [x[0] for x in con.description]
        checks["base_timing_integrity"] = dict(zip(base_names, base_checks, strict=True))
        checks["base_field_semantics"] = {
            "decision_at": "greatest(daily bar decision_at, causal chip feature available_at)",
            "entry_date_entry_open": "lead trading date/open; signal bar cannot fill inside itself",
            "prev_p90_prev_peak1_center": "lagged features, but their economic meaning inherits the current p10/p90 and mass-ranked peak definitions",
        }
        checks["status"] = "PASS" if not missing_feature and not missing_base and all(
            int(value or 0) == 0
            for group in (checks["strict_feature_integrity"], checks["base_timing_integrity"])
            for key, value in group.items()
            if key.endswith(("violations", "mismatch", "fill", "timing", "lineage"))
        ) else "FAIL"
    finally:
        con.close()

    result = {
        "audit_id": "CYQ-FORMULA-TRUTH-2020-2023-V01",
        "generated_at": datetime.now(UTC).isoformat(),
        "config": str(args.config.resolve()),
        "config_sha256": sha256_file(args.config),
        "feature_input": str(feature_glob.resolve()),
        "base_input": str(base.resolve()),
        "read_only": True,
        "checks": checks,
    }
    result_path = output / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    ledger = ROOT / "data/audit/experiment_ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "event_id": f"CYQ-FORMULA-TRUTH-2020-2023-V01-{sha256_file(args.config)[:12]}",
            "event_type": "FORMULA_TRUTH_AUDIT",
            "at": datetime.now(UTC).isoformat(),
            "status": checks["status"],
            "read_only": True,
            "output": str(result_path.resolve()),
        }, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    print(json.dumps({"status": checks["status"], "output": str(result_path)}, ensure_ascii=False))
    return 0 if checks["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
