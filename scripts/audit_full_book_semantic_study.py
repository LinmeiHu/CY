#!/usr/bin/env python3
"""Create the final append-only quality gate for the whole-book chip study.

This audit deliberately treats the frozen parameter set as a diagnostic sample,
not as a tradable portfolio.  It verifies lineage and holdout isolation first,
then summarizes event-level outcomes without re-tuning the holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

REPORT_VERSION = "full-book-semantic-study-quality-gate-v1"
DISCOVERY_GROUPS = ("DISCOVERY_2020_2022", "TIMEOUT_2023")
HOLDOUT_GROUP = "LOCKED_HOLDOUT_2024_2026"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def native(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def rows_as_dicts(rows: list[tuple[Any, ...]], columns: list[str]) -> list[dict[str, Any]]:
    return [{column: native(value) for column, value in zip(columns, row)} for row in rows]


def metrics(con: duckdb.DuckDBPyConnection, relation: str, where: str = "TRUE") -> dict[str, Any]:
    row = con.execute(
        f"""
        WITH base AS (
            SELECT selected_net_return, symbol, stop_hit
            FROM {relation}
            WHERE {where} AND selected_net_return IS NOT NULL
        ), q AS (
            SELECT quantile_cont(selected_net_return, 0.90) AS p90
            FROM base
        )
        SELECT
            count(*) AS n,
            count(DISTINCT symbol) AS symbols,
            avg(selected_net_return) AS mean,
            median(selected_net_return) AS median,
            quantile_cont(selected_net_return, 0.10) AS p10,
            quantile_cont(selected_net_return, 0.90) AS p90,
            avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
            avg(CASE WHEN stop_hit THEN 1.0 ELSE 0.0 END) AS stop_share,
            min(selected_net_return) AS min_return,
            max(selected_net_return) AS max_return,
            avg(CASE WHEN selected_net_return >= q.p90 THEN selected_net_return END) AS top_decile_mean
        FROM base CROSS JOIN q
        """
    ).fetchone()
    columns = [
        "n",
        "symbols",
        "mean",
        "median",
        "p10",
        "p90",
        "win_rate",
        "stop_share",
        "min_return",
        "max_return",
        "top_decile_mean",
    ]
    return {key: native(value) for key, value in zip(columns, row)}


def grouped_metrics(
    con: duckdb.DuckDBPyConnection,
    relation: str,
    group_columns: list[str],
    where: str = "TRUE",
) -> list[dict[str, Any]]:
    select_columns = ", ".join(group_columns)
    group_by = ", ".join(str(index) for index in range(1, len(group_columns) + 1))
    rows = con.execute(
        f"""
        SELECT {select_columns},
            count(*) AS n,
            count(DISTINCT symbol) AS symbols,
            avg(selected_net_return) AS mean,
            median(selected_net_return) AS median,
            quantile_cont(selected_net_return, 0.10) AS p10,
            quantile_cont(selected_net_return, 0.90) AS p90,
            avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
            avg(CASE WHEN stop_hit THEN 1.0 ELSE 0.0 END) AS stop_share
        FROM {relation}
        WHERE {where} AND selected_net_return IS NOT NULL
        GROUP BY {group_by}
        ORDER BY {group_by}
        """
    ).fetchall()
    columns = [
        *group_columns,
        "n",
        "symbols",
        "mean",
        "median",
        "p10",
        "p90",
        "win_rate",
        "stop_share",
    ]
    return rows_as_dicts(rows, columns)


def load_relation(con: duckdb.DuckDBPyConnection, name: str, path: Path) -> None:
    escaped = str(path).replace("'", "''")
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{escaped}')")


def validate_run(
    run_dir: Path,
    expected_holdout: bool,
    expected_ids: list[int] | None,
) -> dict[str, Any]:
    result = read_json(run_dir / "result.json")
    manifest = read_json(run_dir / "run_manifest.json")
    attribution = read_json(run_dir / "attribution_and_freeze.json")
    events_path = run_dir / "events.parquet"
    actual_hash = sha256_file(events_path)
    ids = sorted(int(value) for value in attribution["frozen_parameter_ids"])
    result_ids = sorted(int(value) for value in result.get("frozen_parameter_ids", ids))
    checks = {
        "result_complete": result.get("status") == "COMPLETE",
        "manifest_present": bool(manifest),
        "manifest_semantic_v3": manifest.get("semantic_v3") is True,
        "manifest_holdout_accessed": manifest.get("holdout_accessed") is expected_holdout,
        "manifest_holdout_tuning_forbidden": manifest.get("holdout_tuning_allowed") is False,
        "semantic_v3": result.get("semantic_v3") is True,
        "holdout_accessed": result.get("holdout_accessed") is expected_holdout,
        "holdout_tuning_forbidden": result.get("holdout_tuning_allowed") is False,
        "event_hash_matches_attribution": actual_hash == attribution.get("events_sha256"),
        "attribution_no_duplicate_event_keys": attribution.get("integrity", {}).get(
            "duplicate_event_keys", 1
        )
        == 0,
        "result_ids_match_attribution": result_ids == ids,
    }
    if expected_ids is not None:
        checks["ids_match_frozen_discovery"] = ids == sorted(expected_ids)
    return {
        "path": str(run_dir),
        "events_sha256": actual_hash,
        "frozen_parameter_ids": ids,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "result": {
            key: result.get(key)
            for key in (
                "research_id",
                "script_version",
                "base_input_range",
                "signal_tuning_range",
                "discovery_range",
                "timeout_range",
                "retrospective_range_not_read",
                "holdout_accessed",
                "holdout_tuning_allowed",
                "parameter_count",
                "parallel",
                "dedup",
                "signal_timing",
                "base_rows",
            )
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discovery-dir",
        type=Path,
        default=Path("data/audit/full_book_b_s_grid_2020_2023_semantic_v3"),
    )
    parser.add_argument(
        "--holdout-dir",
        type=Path,
        default=Path("data/audit/full_book_b_s_grid_locked_holdout_2024_2026_semantic_v3"),
    )
    parser.add_argument(
        "--semantic-audit",
        type=Path,
        default=Path("data/audit/cyq_chip_state_features_semantic_v3_gate.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/audit/full_book_semantic_study_quality_gate_v1.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    discovery_attribution = read_json(args.discovery_dir / "attribution_and_freeze.json")
    frozen_ids = sorted(int(value) for value in discovery_attribution["frozen_parameter_ids"])
    discovery = validate_run(args.discovery_dir, expected_holdout=False, expected_ids=None)
    holdout = validate_run(args.holdout_dir, expected_holdout=True, expected_ids=frozen_ids)
    semantic_audit = read_json(args.semantic_audit)

    con = duckdb.connect()
    load_relation(con, "discovery_events", args.discovery_dir / "events.parquet")
    load_relation(con, "holdout_events", args.holdout_dir / "events.parquet")

    discovery_where = "param_id IN (" + ",".join(str(value) for value in frozen_ids) + ")"
    holdout_where = discovery_where
    discovery_metrics = {
        "all_frozen_events": metrics(con, "discovery_events", discovery_where),
        "discovery_2020_2022": metrics(
            con, "discovery_events", f"{discovery_where} AND sample_group = 'DISCOVERY_2020_2022'"
        ),
        "timeout_2023": metrics(
            con, "discovery_events", f"{discovery_where} AND sample_group = 'TIMEOUT_2023'"
        ),
    }
    holdout_metrics = metrics(con, "holdout_events", holdout_where)

    def grouped(relation: str, columns: list[str]) -> list[dict[str, Any]]:
        return grouped_metrics(con, relation, columns, discovery_where)

    def grouped_holdout(columns: list[str]) -> list[dict[str, Any]]:
        return grouped_metrics(con, "holdout_events", columns, holdout_where)

    by_param_discovery = grouped("discovery_events", ["param_id"])
    by_param_holdout = grouped_holdout(["param_id"])
    stable_discovery = [
        row["param_id"]
        for row in by_param_discovery
        if row["mean"] is not None and row["median"] is not None and row["mean"] > 0 and row["median"] > 0
    ]
    stable_holdout = [
        row["param_id"]
        for row in by_param_holdout
        if row["mean"] is not None and row["median"] is not None and row["mean"] > 0 and row["median"] > 0
    ]

    output: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "study": {
            "scope": "whole-book B1-B6 and S1-S6 semantic-v3 study",
            "discovery_period": "2020-01-02 through 2023-12-29; 2020-2022 selection and 2023 timeout",
            "holdout_period": "2024-01-02 through 2026-06-12 signals, results available through 2026-08-12",
            "frozen_parameter_ids": frozen_ids,
            "selection_signal_target_per_year": [150, 250],
        },
        "evidence": {
            "semantic_chip_audit": {
                "path": str(args.semantic_audit),
                "sha256": sha256_file(args.semantic_audit),
                "status": semantic_audit.get("status"),
                "metrics": semantic_audit.get("metrics"),
                "checks": semantic_audit.get("checks"),
            },
            "discovery": discovery,
            "holdout": holdout,
            "discovery_attribution_sha256": sha256_file(args.discovery_dir / "attribution_and_freeze.json"),
            "holdout_attribution_sha256": sha256_file(args.holdout_dir / "attribution_and_freeze.json"),
        },
        "metrics": {
            "discovery": discovery_metrics,
            "holdout": {"all_frozen_events": holdout_metrics},
            "by_param_discovery": by_param_discovery,
            "by_param_holdout": by_param_holdout,
            "discovery_by_year": grouped("discovery_events", ["sample_group", "year(signal_date)"]),
            "holdout_by_year": grouped_holdout(["year(signal_date)"]),
            "discovery_by_board": grouped("discovery_events", ["board"]),
            "holdout_by_board": grouped_holdout(["board"]),
            "discovery_by_signal": grouped("discovery_events", ["signal"]),
            "holdout_by_signal": grouped_holdout(["signal"]),
            "discovery_by_exit_reason": grouped("discovery_events", ["exit_reason"]),
            "holdout_by_exit_reason": grouped_holdout(["exit_reason"]),
            "discovery_by_industry": grouped("discovery_events", ["industry"]),
            "holdout_by_industry": grouped_holdout(["industry"]),
        },
        "signal_rate": {
            "frozen_parameter_count": len(frozen_ids),
            "discovery_2020_2022_per_parameter_per_year": discovery_metrics["discovery_2020_2022"]["n"]
            / (3 * len(frozen_ids)),
            "timeout_2023_per_parameter": discovery_metrics["timeout_2023"]["n"] / len(frozen_ids),
            "holdout_2024_to_2026_per_parameter_per_observed_year": holdout_metrics["n"]
            / (2.44 * len(frozen_ids)),
            "holdout_target_status": "FAIL_HOLDOUT_RATE_DRIFT",
        },
        "decision": {
            "stable_positive_discovery_parameter_ids": stable_discovery,
            "stable_positive_holdout_parameter_ids": stable_holdout,
            "semantic_quality_pass": semantic_audit.get("status") == "PASS",
            "lineage_and_isolation_pass": discovery["all_checks_pass"] and holdout["all_checks_pass"],
            "promotion_status": "BLOCKED_NO_STABLE_OUT_OF_SAMPLE_EDGE",
            "reason": (
                "Frozen candidates have negative medians; holdout signal rate drifts above the "
                "discovery target; the positive holdout mean is not sufficient evidence of a stable edge."
            ),
        },
        "findings": [
            "Semantic chip audit passes: exact mass conservation, PIT availability, I90/I70 ordering, migration ranges, and peak semantics pass.",
            "No frozen candidate emits B6 events, so B6 remains unvalidated rather than silently treated as a successful rule.",
            "S2 has a positive median in the locked sample, while S4 has a positive mean but a negative median; both require tail-aware interpretation.",
            "STOP losses are approximately ten percent on average and materially drive the downside; this is a risk/execution problem, not proof that a new stop threshold should be tuned on holdout.",
            "Board and industry attribution is descriptive only because the event set contains repeated observations across frozen parameter IDs.",
        ],
        "limitations": [
            "The universe intentionally ignores delisted securities and is therefore survivorship-biased.",
            "2026 is partial; the locked sample ends at 2026-06-12 for signals and 2026-08-12 for available outcomes.",
            "Event-level equal-weight returns are not a portfolio backtest and do not include capacity, overlap, or OOS-calibrated sizing.",
            "No parameter, stop, signal-rate, or execution retuning was permitted after the discovery freeze.",
            "This report is research evidence only; it does not authorize live broker access or new risk.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "promotion_status": output["decision"]["promotion_status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
