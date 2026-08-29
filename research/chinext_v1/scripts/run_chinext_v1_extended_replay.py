#!/usr/bin/env python3
"""Prepare or execute the preregistered ChinNext V1 2018-2021 replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
from collections import defaultdict
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
SRC = ROOT / "src"
for import_root in (str(SCRIPTS), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

import run_chinext_v1_gate_c as gate_c  # noqa: E402
import run_chinext_v1_gate_d as gate_d  # noqa: E402
from run_chinext_v1_full_survivor import (  # noqa: E402
    INITIAL_CASH,
    performance_extensions,
    read_jsonl,
    year_metrics,
)
from run_chinext_v1_pit_replay import concentration, reconstruct_round_trips  # noqa: E402
from run_chinext_v1_smoke import run as run_engine  # noqa: E402

START = date(2018, 1, 2)
END = date(2021, 12, 31)
WARMUP_START = date(2017, 4, 12)
WARMUP_END = date(2017, 12, 29)
REPLAY_SPEC_RELATIVE = Path(
    "research/chinext_v1/specs/chinext_v1_extended_replay_preregistration.json"
)
REPLAY_SPEC = ROOT / REPLAY_SPEC_RELATIVE
GATE_D_RESULT = ROOT / "research/chinext_v1/reports/chinext_v1_gate_d_result.json"
DEFAULT_SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_extended_replay_summary.json"
DEFAULT_REPORT = ROOT / "research/chinext_v1/reports/chinext_v1_extended_replay.md"
DEFAULT_MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_extended_replay_artifact_manifest.json"
DEFAULT_OUTPUT = ROOT / "research/chinext_v1/output/chinext_v1_extended_2018_2021"
MARKET = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
CALENDAR = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet")
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
CONSUMER = Path(__file__).resolve()


class ExtendedReplayError(RuntimeError):
    """Raised when the extended replay cannot honor its frozen input contract."""


def sha256_file(path: Path) -> str:
    return gate_c.sha256_file(path)


def canonical_bytes(payload: object) -> bytes:
    return gate_c.canonical_bytes(payload)


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def finite(value: Any, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return default
    return converted if math.isfinite(converted) else default


def load_gate_d() -> tuple[dict[str, Any], dict[str, Any]]:
    gate_d_spec = gate_d.load_spec()
    gate_d_result = json.loads(GATE_D_RESULT.read_text(encoding="utf-8"))
    if gate_d_result.get("gate_d_result") != "PASS":
        raise ExtendedReplayError("Gate D prerequisite is not PASS")
    if gate_d_result.get("safe_to_run_extended_history_strategy_replay") != "YES":
        raise ExtendedReplayError("Gate D did not authorize extended replay")
    if gate_d_result.get("strategy_input_requirement_matrix_status") != "PASS":
        raise ExtendedReplayError("strategy input requirement matrix is not PASS")
    return gate_d_spec, gate_d_result


def next_state_session(
    connection: duckdb.DuckDBPyConnection,
    physical_symbol: str,
    boundary: date,
    *,
    warmup: bool,
) -> date | None:
    table = "gate_d_warmup_state" if warmup else "gate_d_state"
    return connection.execute(
        f"SELECT min(trade_date) FROM {table} WHERE physical_symbol=? AND trade_date>=?",
        [physical_symbol, boundary],
    ).fetchone()[0]


def build_warmup_actions(
    connection: duckdb.DuckDBPyConnection,
    gate_c_spec: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    bindings = gate_c_spec["input_bindings"]
    distributions = gate_c.resolve_path(bindings["qd010_distributions"]["path"])
    rights = gate_c.resolve_path(bindings["qd010_rights"]["path"])
    supported = connection.execute(
        """
        SELECT event_id, symbol, known_at, effective_date, event_type,
               share_multiplier, cash_per_share_gross
        FROM read_parquet(?)
        WHERE regexp_matches(symbol, '^(300|301|302)')
          AND effective_date BETWEEN DATE '2017-04-12' AND DATE '2017-12-29'
          AND known_at IS NOT NULL AND known_at<=effective_date
          AND source_terms_complete=true
          AND coalesce(rights_subscription_ratio,0)=0
        ORDER BY effective_date,symbol,event_id
        """,
        [str(distributions)],
    ).fetchall()
    unresolved = connection.execute(
        """
        SELECT event_id, symbol, known_at, effective_date,
               execution_timing_unresolved_reason
        FROM read_parquet(?)
        WHERE regexp_matches(symbol, '^(300|301|302)')
          AND known_at BETWEEN DATE '2017-04-12' AND DATE '2017-12-29'
          AND source_terms_complete=false
        ORDER BY known_at,symbol,event_id
        """,
        [str(distributions)],
    ).fetchall()
    rights_rows = connection.execute(
        """
        SELECT event_id, symbol, known_at, effective_date,
               rights_subscription_ratio, rights_subscription_price
        FROM read_parquet(?)
        WHERE regexp_matches(symbol, '^(300|301|302)')
          AND coalesce(effective_date,known_at) BETWEEN DATE '2017-04-12' AND DATE '2017-12-29'
        ORDER BY coalesce(effective_date,known_at),symbol,event_id
        """,
        [str(rights)],
    ).fetchall()
    grouped: dict[tuple[date, str], dict[str, Any]] = {}

    def action(day: date, physical_symbol: str) -> dict[str, Any]:
        return grouped.setdefault(
            (day, physical_symbol),
            {
                "trade_date": day,
                "physical_symbol": physical_symbol,
                "event_ids": [],
                "known_dates": [],
                "share_multiplier": 1.0,
                "cash_per_share": 0.0,
                "rights_ratio": 0.0,
                "rights_price": 0.0,
                "blocking": False,
                "problems": [],
            },
        )

    supported_used = 0
    for event_id, raw_symbol, known_at, effective_date, _, multiplier, cash in supported:
        physical = f"{raw_symbol}.SZ"
        effective = pd.Timestamp(effective_date).date()
        if next_state_session(connection, physical, effective, warmup=True) != effective:
            continue
        row = action(effective, physical)
        row["event_ids"].append(str(event_id))
        row["known_dates"].append(pd.Timestamp(known_at).date())
        row["share_multiplier"] *= finite(multiplier, 1.0)
        row["cash_per_share"] += finite(cash, 0.0)
        supported_used += 1

    blocking_used = 0
    for event_id, raw_symbol, known_at, effective_date, reason in unresolved:
        physical = f"{raw_symbol}.SZ"
        known = pd.Timestamp(known_at).date()
        effective = None if pd.isna(effective_date) else pd.Timestamp(effective_date).date()
        boundary = max(known, effective) if effective is not None else known
        safe = next_state_session(connection, physical, boundary, warmup=True)
        if safe is None:
            continue
        row = action(safe, physical)
        row["event_ids"].append(str(event_id))
        row["known_dates"].append(known)
        row["blocking"] = True
        row["problems"].append(str(reason or "unresolved_distribution"))
        blocking_used += 1
    for event_id, raw_symbol, known_at, effective_date, ratio, price in rights_rows:
        physical = f"{raw_symbol}.SZ"
        known = pd.Timestamp(known_at).date()
        effective = None if pd.isna(effective_date) else pd.Timestamp(effective_date).date()
        boundary = max(known, effective) if effective is not None else known
        safe = next_state_session(connection, physical, boundary, warmup=True)
        if safe is None:
            continue
        row = action(safe, physical)
        row["event_ids"].append(str(event_id))
        row["known_dates"].append(known)
        row["rights_ratio"] = finite(ratio, 0.0)
        row["rights_price"] = finite(price, 0.0)
        row["blocking"] = True
        row["problems"].append("rights_participation_execution_unresolved")
        blocking_used += 1

    output: list[dict[str, Any]] = []
    for _, row in sorted(grouped.items()):
        output.append(
            {
                "trade_date": row["trade_date"],
                "physical_symbol": row["physical_symbol"],
                "corporate_action_count": len(row["event_ids"]),
                "corporate_action_ids": "|".join(sorted(row["event_ids"])),
                "corporate_action_blocking": bool(row["blocking"]),
                "corporate_action_problems": (
                    "|".join(sorted(set(row["problems"]))) if row["problems"] else None
                ),
                "corporate_action_available_date": max(row["known_dates"]),
                "share_multiplier": float(row["share_multiplier"]),
                "cash_per_share": float(row["cash_per_share"]),
                "rights_ratio": float(row["rights_ratio"]),
                "rights_price": float(row["rights_price"]),
            }
        )
    frame = pd.DataFrame(
        output,
        columns=[
            "trade_date",
            "physical_symbol",
            "corporate_action_count",
            "corporate_action_ids",
            "corporate_action_blocking",
            "corporate_action_problems",
            "corporate_action_available_date",
            "share_multiplier",
            "cash_per_share",
            "rights_ratio",
            "rights_price",
        ],
    )
    return frame, {
        "supported_action_count": supported_used,
        "blocking_action_count": blocking_used,
        "action_session_count": len(frame),
    }


def build_target_overlay(gate_d_result: dict[str, Any]) -> pd.DataFrame:
    rows = gate_d_result["corporate_actions"]["direct_fail_closed_overlay"]
    return pd.DataFrame(
        [
            {
                "trade_date": date.fromisoformat(row["safe_session"]),
                "physical_symbol": row["physical_symbol"],
                "event_id": row["event_id"],
                "known_at": date.fromisoformat(row["known_at"]),
                "reason": row["reason"],
            }
            for row in rows
        ],
        columns=["trade_date", "physical_symbol", "event_id", "known_at", "reason"],
    )


def materialize_transient_inputs(output_root: Path) -> dict[str, Any]:
    gate_d_spec, gate_d_result = load_gate_d()
    gate_c_spec = gate_c.load_spec()
    gate_c.validate_input_hashes(gate_c_spec)
    connection = duckdb.connect()
    context = gate_d.create_full_views(connection, gate_c_spec)
    warmup_files = gate_d.prepare_warmup_prices(connection, gate_c_spec)
    warmup_actions, warmup_action_counts = build_warmup_actions(connection, gate_c_spec)
    target_overlay = build_target_overlay(gate_d_result)
    connection.register("extended_warmup_actions", warmup_actions)
    connection.register("extended_target_overlay", target_overlay)
    connection.execute(
        """
        CREATE TEMP TABLE extended_warmup_panel AS
        SELECT h.trade_date, h.canonical_symbol AS symbol,
               p.open, p.high, p.low, p.close, p.preclose, p.volume, p.amount,
               CAST(h.authorized_trade_status AS INTEGER) AS trade_status,
               h.risk_warning AS is_st,
               CAST(NULL AS DOUBLE) AS up_limit_price,
               CAST(NULL AS DOUBLE) AS down_limit_price,
               false AS buy_blocked_open, false AS sell_blocked_open,
               (p.close IS NOT NULL AND isfinite(p.close) AND p.close>0
                AND p.volume IS NOT NULL AND isfinite(p.volume) AND p.volume>0
                AND p.amount IS NOT NULL AND isfinite(p.amount) AND p.amount>=0) AS bar_valid,
               true AS trading_state_valid,
               coalesce(NOT a.corporate_action_blocking, true) AS corporate_action_valid,
               true AS market_rule_valid,
               true AS historical_identity_valid,
               (CAST(h.authorized_trade_status AS INTEGER)=1
                AND NOT h.risk_warning AND NOT h.full_day_suspended
                AND p.close IS NOT NULL AND isfinite(p.close) AND p.close>0
                AND p.volume IS NOT NULL AND isfinite(p.volume) AND p.volume>0
                AND p.amount IS NOT NULL AND isfinite(p.amount) AND p.amount>=0
                AND coalesce(NOT a.corporate_action_blocking, true)) AS hard_valid,
               (CAST(h.authorized_trade_status AS INTEGER)=1
                AND NOT h.full_day_suspended
                AND p.open IS NOT NULL AND isfinite(p.open) AND p.open>0) AS current_day_data_tradable,
               CAST(h.trade_date AS TIMESTAMP) + INTERVAL 15 HOUR AS available_at,
               'QD001-NONE-20260820' AS snapshot_id,
               coalesce(a.corporate_action_count,0) AS corporate_action_count,
               a.corporate_action_ids,
               coalesce(a.corporate_action_blocking,false) AS corporate_action_blocking,
               a.corporate_action_problems,
               coalesce(a.corporate_action_available_date,h.trade_date) AS corporate_action_available_date,
               coalesce(a.share_multiplier,1.0) AS share_multiplier,
               coalesce(a.cash_per_share,0.0) AS cash_per_share,
               coalesce(a.rights_ratio,0.0) AS rights_ratio,
               coalesce(a.rights_price,0.0) AS rights_price
        FROM gate_d_warmup_state h
        LEFT JOIN gate_d_warmup_prices p
          ON h.trade_date=p.trade_date AND h.physical_symbol=p.physical_symbol
        LEFT JOIN extended_warmup_actions a
          ON h.trade_date=a.trade_date AND h.physical_symbol=a.physical_symbol
        ORDER BY h.trade_date,h.canonical_symbol
        """
    )
    cy006_paths = [str(path) for path in context["cy006_paths"]]
    connection.execute(
        """
        CREATE TEMP TABLE extended_cy006 AS
        SELECT *, symbol AS physical_symbol
        FROM read_parquet(?)
        WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
          AND regexp_matches(symbol,'^(300|301|302)')
        """,
        [cy006_paths],
    )
    connection.execute(
        """
        CREATE TEMP TABLE extended_target_panel AS
        SELECT h.trade_date, h.canonical_symbol AS symbol,
               c.open, c.high, c.low, c.close, c.preclose, c.volume, c.amount,
               CAST(h.authorized_trade_status AS INTEGER) AS trade_status,
               h.risk_warning AS is_st,
               c.up_limit_price, c.down_limit_price,
               c.buy_blocked_open, c.sell_blocked_open,
               c.bar_valid, c.trading_state_valid,
               CASE WHEN o.event_id IS NOT NULL THEN false ELSE c.corporate_action_valid END
                 AS corporate_action_valid,
               c.market_rule_valid,
               true AS historical_identity_valid,
               CASE
                 WHEN o.event_id IS NOT NULL OR h.risk_warning OR h.full_day_suspended THEN false
                 WHEN h.canonical_symbol<>h.physical_symbol
                      AND c.invalid_reasons='HISTORICAL_SYMBOL_ALIAS_NOT_PIT_SAFE'
                   THEN c.bar_valid AND c.trading_state_valid AND c.corporate_action_valid
                        AND c.market_rule_valid AND c.current_day_data_tradable
                 ELSE c.hard_valid
               END AS hard_valid,
               (c.current_day_data_tradable AND NOT h.full_day_suspended)
                 AS current_day_data_tradable,
               c.available_at, c.snapshot_id,
               CASE WHEN o.event_id IS NOT NULL THEN 1 ELSE c.corporate_action_count END
                 AS corporate_action_count,
               CASE WHEN o.event_id IS NOT NULL THEN o.event_id ELSE c.corporate_action_ids END
                 AS corporate_action_ids,
               CASE WHEN o.event_id IS NOT NULL THEN true ELSE c.corporate_action_blocking END
                 AS corporate_action_blocking,
               CASE WHEN o.event_id IS NOT NULL THEN o.reason ELSE c.corporate_action_problems END
                 AS corporate_action_problems,
               CASE WHEN o.event_id IS NOT NULL THEN o.known_at ELSE c.corporate_action_available_date END
                 AS corporate_action_available_date,
               CASE WHEN o.event_id IS NOT NULL THEN 1.0 ELSE c.share_multiplier END
                 AS share_multiplier,
               CASE WHEN o.event_id IS NOT NULL THEN 0.0 ELSE c.cash_per_share END
                 AS cash_per_share,
               CASE WHEN o.event_id IS NOT NULL THEN 0.0 ELSE c.rights_ratio END
                 AS rights_ratio,
               CASE WHEN o.event_id IS NOT NULL THEN 0.0 ELSE c.rights_price END
                 AS rights_price
        FROM gate_d_state h
        JOIN extended_cy006 c
          ON h.trade_date=c.trade_date AND h.physical_symbol=c.physical_symbol
        LEFT JOIN extended_target_overlay o
          ON h.trade_date=o.trade_date AND h.physical_symbol=o.physical_symbol
        ORDER BY h.trade_date,h.canonical_symbol
        """
    )
    overlay_mismatch = connection.execute(
        """
        SELECT count(*) FROM extended_target_overlay o
        LEFT JOIN extended_target_panel p
          ON o.trade_date=p.trade_date AND o.physical_symbol=(
            SELECT physical_symbol FROM gate_d_state s
            WHERE s.trade_date=p.trade_date AND s.canonical_symbol=p.symbol
          )
        WHERE p.symbol IS NULL OR p.corporate_action_blocking IS NOT TRUE
           OR p.corporate_action_valid IS NOT FALSE OR p.hard_valid IS NOT FALSE
        """
    ).fetchone()[0]
    if overlay_mismatch:
        raise ExtendedReplayError("target fail-closed corporate-action overlay mismatch")
    connection.execute(
        """
        CREATE TEMP TABLE extended_membership AS
        SELECT earliest_safe_use_date AS trade_date,
               canonical_symbol AS symbol,
               listed_trading_days,
               'B_RECONSTRUCTED' AS pit_grade
        FROM (
          SELECT * FROM gate_d_warmup_state
          UNION ALL BY NAME
          SELECT * FROM gate_d_state
        )
        WHERE earliest_safe_use_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
        ORDER BY trade_date,symbol
        """
    )
    membership_stats = connection.execute(
        """
        SELECT count(*),count(DISTINCT trade_date),count(DISTINCT symbol),
               count(*)-count(DISTINCT (trade_date,symbol)),min(trade_date),max(trade_date)
        FROM extended_membership
        """
    ).fetchone()
    expected_membership_stats = (803527, 973, 1097, 0, START, END)
    if membership_stats != expected_membership_stats:
        raise ExtendedReplayError(f"safe membership cardinality mismatch: {membership_stats}")
    panel_stats = connection.execute(
        """
        SELECT
          (SELECT count(*) FROM extended_warmup_panel),
          (SELECT count(*) FROM extended_target_panel),
          (SELECT count(*) FROM extended_warmup_panel WHERE hard_valid),
          (SELECT count(*) FROM extended_target_panel WHERE hard_valid),
          (SELECT count(*) FROM extended_warmup_panel WHERE corporate_action_blocking),
          (SELECT count(*) FROM extended_target_panel WHERE corporate_action_blocking)
        """
    ).fetchone()
    if panel_stats[0] != 120642 or panel_stats[1] != 803907:
        raise ExtendedReplayError(f"transient panel row count mismatch: {panel_stats[:2]}")

    output_root.mkdir(parents=True, exist_ok=True)
    membership_path = output_root / "daily_membership.parquet"
    connection.execute(
        f"COPY extended_membership TO '{sql_path(membership_path)}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )
    partitions: list[dict[str, Any]] = []
    for year in range(2018, 2022):
        directory = output_root / f"partition_year={year}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "data_0.parquet"
        if year == 2018:
            query = (
                "SELECT * FROM extended_warmup_panel UNION ALL "
                "SELECT * FROM extended_target_panel WHERE year(trade_date)=2018 "
                "ORDER BY trade_date,symbol"
            )
        else:
            query = (
                f"SELECT * FROM extended_target_panel WHERE year(trade_date)={year} "
                "ORDER BY trade_date,symbol"
            )
        connection.execute(
            f"COPY ({query}) TO '{sql_path(path)}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
        )
        rows = int(connection.execute(f"SELECT count(*) FROM ({query})").fetchone()[0])
        partitions.append(
            {"year": year, "rows": rows, "sha256": sha256_file(path), "relative_path": f"partition_year={year}/data_0.parquet"}
        )
    manifest = {
        "alias_map": context["alias_map"],
        "gate_d_combined_logical_sha256": gate_d_result["logical_materialization"][
            "combined_sha256"
        ],
        "membership": {
            "date_count": int(membership_stats[1]),
            "earliest_safe_use_semantics": "PRIOR_SESSION_STATE_AVAILABLE_ON_NEXT_QD003_SESSION",
            "rows": int(membership_stats[0]),
            "sha256": sha256_file(membership_path),
            "unique_symbols": int(membership_stats[2]),
        },
        "panel": {
            "partitions": partitions,
            "target_hard_valid_rows": int(panel_stats[3]),
            "target_rows": int(panel_stats[1]),
            "target_blocking_action_rows": int(panel_stats[5]),
            "warmup_hard_valid_rows": int(panel_stats[2]),
            "warmup_rows": int(panel_stats[0]),
            "warmup_blocking_action_rows": int(panel_stats[4]),
        },
        "persistent_duplicate_daily_store": False,
        "qd001_warmup": warmup_files,
        "source_date_range": [WARMUP_START.isoformat(), END.isoformat()],
        "target_date_range": [START.isoformat(), END.isoformat()],
        "target_direct_fail_closed_overlay": gate_d_result["corporate_actions"][
            "direct_fail_closed_overlay"
        ],
        "warmup_actions": warmup_action_counts,
    }
    manifest["canonical_sha256"] = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    connection.close()
    return manifest


def load_replay_spec() -> dict[str, Any]:
    payload = json.loads(REPLAY_SPEC.read_text(encoding="utf-8"))
    if payload.get("spec_id") != "CHINEXT-V1-EXTENDED-REPLAY-2018-2021-V1":
        raise ExtendedReplayError("unexpected replay spec identity")
    if payload.get("status") != "FROZEN_BEFORE_FIRST_VIEW_REPLAY":
        raise ExtendedReplayError("formal replay spec is not frozen")
    committed = subprocess.run(
        ["git", "show", f"HEAD:{REPLAY_SPEC_RELATIVE.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if committed != REPLAY_SPEC.read_bytes():
        raise ExtendedReplayError("working replay spec differs from committed bytes")
    spec_commit = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", REPLAY_SPEC_RELATIVE.as_posix()],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not spec_commit:
        raise ExtendedReplayError("formal replay spec has no committed history")
    for name, binding in payload["input_bindings"].items():
        path = gate_c.resolve_path(binding["path"])
        if not path.is_file():
            raise ExtendedReplayError(f"formal replay input missing: {name}: {path}")
        if sha256_file(path) != binding["sha256"]:
            raise ExtendedReplayError(f"formal replay input hash mismatch: {name}: {path}")
    if payload["strategy_sha256"] != sha256_file(STRATEGY):
        raise ExtendedReplayError("frozen V1 strategy hash mismatch")
    if payload["runner_sha256"] != sha256_file(CONSUMER):
        raise ExtendedReplayError("formal replay runner hash mismatch")
    if payload["gate_d_result_sha256"] != sha256_file(GATE_D_RESULT):
        raise ExtendedReplayError("Gate D result hash mismatch")
    payload["_resolved_spec_commit"] = spec_commit
    return payload


def validate_prepared_manifest(manifest: dict[str, Any], spec: dict[str, Any]) -> None:
    expected = spec["transient_input_contract"]
    actual = {
        "canonical_sha256": manifest["canonical_sha256"],
        "membership_rows": manifest["membership"]["rows"],
        "membership_sha256": manifest["membership"]["sha256"],
        "membership_symbols": manifest["membership"]["unique_symbols"],
        "partition_hashes": {
            str(item["year"]): item["sha256"] for item in manifest["panel"]["partitions"]
        },
        "target_rows": manifest["panel"]["target_rows"],
        "warmup_rows": manifest["panel"]["warmup_rows"],
    }
    if actual != expected:
        raise ExtendedReplayError(f"transient replay input contract mismatch: {actual}")


def annual_metrics(nav: list[dict[str, Any]], trips: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    previous_close = INITIAL_CASH
    for year in range(2018, 2022):
        result[str(year)] = year_metrics(nav, trips, year, previous_close)
        year_rows = [row for row in nav if str(row["trade_date"]).startswith(str(year))]
        previous_close = float(year_rows[-1]["nav"])
    return result


def build_formal_summary(
    engine_summary_path: Path,
    prepared: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    summary = json.loads(engine_summary_path.read_text(encoding="utf-8"))
    if summary["configuration"] != spec["strategy_configuration"]:
        raise ExtendedReplayError("engine strategy configuration differs from frozen replay spec")
    execution_contract = spec["execution_semantics"]
    if summary["execution"]["transaction_cost_bps_per_side"] != execution_contract[
        "transaction_cost_bps_per_filled_side"
    ]:
        raise ExtendedReplayError("engine transaction cost differs from frozen replay spec")
    if summary["execution"]["board_lot"] != execution_contract["board_lot_shares"]:
        raise ExtendedReplayError("engine board lot differs from frozen replay spec")
    if summary["execution"]["rank_replacement"] != execution_contract["rank_replacement"]:
        raise ExtendedReplayError("engine rank replacement differs from frozen replay spec")
    executions = read_jsonl(summary["audit"]["execution_ledger"])
    nav = read_jsonl(summary["audit"]["daily_nav"])
    trips = reconstruct_round_trips(executions)
    if summary["execution"]["completed_round_trip_count"] != len(trips):
        raise ExtendedReplayError("completed round-trip count mismatch")
    same_day = sum(
        row.get("status") == "FILLED" and row["signal_date"] == row["execution_date"]
        for row in executions
    )
    if same_day:
        raise ExtendedReplayError("same-day fill detected")
    if summary["audit"]["stale_held_valuation_count"]:
        raise ExtendedReplayError("stale held valuation detected")
    extended = performance_extensions(nav)
    summary["portfolio"].update(extended)
    summary["execution"].update(
        {
            "commission_model": "fixed 10 bps per filled side",
            "slippage_model": "NONE_SEPARATELY_MODELED",
            "stamp_duty_model": "NONE_SEPARATELY_MODELED",
        }
    )
    summary["pnl_concentration"] = concentration(
        trips, float(summary["portfolio"]["total_return"])
    )
    summary["year_by_year"] = annual_metrics(nav, trips)
    summary["formal_replay"] = {
        "execution_count": 1,
        "label": "PREREGISTERED_EXTENDED_HISTORY_VALIDATION",
        "sample_status_after_run": "CONSUMED_PREREGISTERED_EXTENDED_HISTORY_VALIDATION",
        "strategy_sha256": spec["strategy_sha256"],
        "replay_spec_commit": spec["_resolved_spec_commit"],
        "replay_spec_sha256": sha256_file(REPLAY_SPEC),
        "runner_sha256": spec["runner_sha256"],
        "gate_d_result_sha256": spec["gate_d_result_sha256"],
        "input_manifest": prepared,
        "strict_pit_a": False,
        "authorization_class": "BOUNDED_EFFECTIVE_STATE_PIT_B",
        "date_range": [START.isoformat(), END.isoformat()],
        "warmup_start": WARMUP_START.isoformat(),
        "performance_generated_before_preregistration": False,
        "same_day_fill_count": same_day,
    }
    return summary


def write_report(path: Path, summary: dict[str, Any]) -> None:
    p = summary["portfolio"]
    c = summary["pnl_concentration"]
    years = summary["year_by_year"]
    lines = [
        "# ChinNext V1 — preregistered 2018–2021 extended-history replay",
        "",
        "> PREREGISTERED_EXTENDED_HISTORY_VALIDATION / BOUNDED PIT-B / NOT STRICT PIT-A",
        "",
        f"- STRATEGY_SHA256: `{summary['formal_replay']['strategy_sha256']}`",
        f"- REPLAY_SPEC_COMMIT: `{summary['formal_replay']['replay_spec_commit']}`",
        "- FORMAL_REPLAY_EXECUTION_COUNT: `1`",
        "- 2018_2021_SAMPLE_STATUS: `CONSUMED_PREREGISTERED_EXTENDED_HISTORY_VALIDATION`",
        "",
        "## Frozen metrics",
        "",
        f"- TOTAL_RETURN: `{p['total_return']:.6%}`",
        f"- MAX_DRAWDOWN: `{p['max_drawdown']:.6%}`",
        f"- TRADES: `{summary['execution']['completed_round_trip_count']}`",
        f"- WIN_RATE: `{p['win_rate']:.6%}`",
        f"- MEDIAN_TRADE: `{p['median_trade_return']:.6%}`",
        f"- MEAN_TRADE: `{p['average_trade_return']:.6%}`",
        f"- TOP20_PNL_CONCENTRATION: `{c['top20_positive_pnl_concentration']:.6%}`",
        f"- RETURN_EX_BEST20: `{c['return_ex_best20']:.6%}`",
        f"- 2018_TOTAL_RETURN: `{years['2018']['return']:.6%}`",
        f"- 2019_TOTAL_RETURN: `{years['2019']['return']:.6%}`",
        f"- 2020_TOTAL_RETURN: `{years['2020']['return']:.6%}`",
        f"- 2021_TOTAL_RETURN: `{years['2021']['return']:.6%}`",
        "",
        "The replay reuses the frozen V1 signal, portfolio, next-open, T+1, limit, cost, and corporate-action semantics. Historical identity/state is overlaid from the exact CY-029 artifact; physical 302132.SZ source rows are mapped to canonical 300114.SZ from official data, and unresolved events remain fail-closed.",
        "",
    ]
    gate_c.atomic_write(path, "\n".join(lines).encode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    cli = parse_args()
    with tempfile.TemporaryDirectory(prefix="chinext-v1-extended-input-") as temporary:
        input_root = Path(temporary)
        prepared = materialize_transient_inputs(input_root)
        if cli.prepare_only:
            print(canonical_bytes(prepared).decode("utf-8"), end="")
            return 0
        spec = load_replay_spec()
        validate_prepared_manifest(prepared, spec)
        cli.output_dir.mkdir(parents=True, exist_ok=True)
        engine_summary = cli.output_dir / "engine_summary.json"
        engine_report = cli.output_dir / "engine_report.md"
        args = argparse.Namespace(
            start=START,
            end=END,
            sample_size=10_000,
            full_survivor=True,
            initial_cash=INITIAL_CASH,
            pit_membership=input_root / "daily_membership.parquet",
            daily_root=input_root,
            market=MARKET,
            calendar=CALENDAR,
            summary=engine_summary,
            report=engine_report,
            output_dir=cli.output_dir,
            warmup_start=WARMUP_START,
        )
        run_engine(args)
        first = build_formal_summary(engine_summary, prepared, spec)
        second = build_formal_summary(engine_summary, prepared, spec)
        if canonical_bytes(first) != canonical_bytes(second):
            raise ExtendedReplayError("ledger-derived formal summary is not deterministic")
        first["formal_replay"]["ledger_summary_determinism"] = "PASS_BYTE_IDENTICAL"
        gate_c.atomic_write(cli.summary, canonical_bytes(first))
        write_report(cli.report, first)
        artifact_manifest = {
            "artifact_id": "CHINEXT-V1-EXTENDED-FIRST-VIEW-2018-2021-V1",
            "annual_summary_embedded": True,
            "date_range": [START.isoformat(), END.isoformat()],
            "formal_replay_execution_count": 1,
            "input_manifest_canonical_sha256": prepared["canonical_sha256"],
            "label": "PREREGISTERED_EXTENDED_HISTORY_VALIDATION",
            "sample_status": "CONSUMED_PREREGISTERED_EXTENDED_HISTORY_VALIDATION",
            "strategy_sha256": spec["strategy_sha256"],
            "files": {
                "daily_nav": {
                    "path": first["audit"]["daily_nav"],
                    "sha256": sha256_file(Path(first["audit"]["daily_nav"])),
                },
                "event_ledger": {
                    "path": first["audit"]["event_ledger"],
                    "sha256": sha256_file(Path(first["audit"]["event_ledger"])),
                },
                "execution_ledger": {
                    "path": first["audit"]["execution_ledger"],
                    "sha256": sha256_file(Path(first["audit"]["execution_ledger"])),
                },
                "report": {"path": str(cli.report), "sha256": sha256_file(cli.report)},
                "summary": {"path": str(cli.summary), "sha256": sha256_file(cli.summary)},
            },
        }
        gate_c.atomic_write(cli.manifest, canonical_bytes(artifact_manifest))
        print(
            json.dumps(
                {
                    "label": artifact_manifest["label"],
                    "total_return": first["portfolio"]["total_return"],
                    "max_drawdown": first["portfolio"]["max_drawdown"],
                    "trades": first["execution"]["completed_round_trip_count"],
                    "sample_status": artifact_manifest["sample_status"],
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
