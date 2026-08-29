#!/usr/bin/env python3
"""Execute the committed full ChinNext V1 Gate D PIT input validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
SRC = ROOT / "src"
for import_root in (str(SCRIPTS), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

import run_chinext_v1_gate_c as gate_c  # noqa: E402

SPEC_RELATIVE = Path("research/chinext_v1/specs/chinext_v1_gate_d_preregistration.json")
SPEC = ROOT / SPEC_RELATIVE
RESULT = ROOT / "research/chinext_v1/reports/chinext_v1_gate_d_result.json"
REPORT = ROOT / "research/chinext_v1/reports/chinext_v1_gate_d_result.md"
CONSUMER = Path(__file__).resolve()
GATE_D_REPAIR_COUNT = 3


class GateDError(RuntimeError):
    """Raised before Gate D can consume an unbound or malformed input."""


def sha256_file(path: Path) -> str:
    return gate_c.sha256_file(path)


def canonical_bytes(payload: object) -> bytes:
    return gate_c.canonical_bytes(payload)


def resolve_path(raw: str) -> Path:
    return gate_c.resolve_path(raw)


def atomic_write(path: Path, payload: bytes) -> None:
    gate_c.atomic_write(path, payload)


def load_spec() -> dict[str, Any]:
    payload = json.loads(SPEC.read_text(encoding="utf-8"))
    if payload.get("spec_id") != "CHINEXT-V1-GATE-D-FULL-PIT-VALIDATION-V1":
        raise GateDError("unexpected Gate D spec identity")
    if payload.get("status") != "FROZEN_BEFORE_GATE_D_EXECUTION":
        raise GateDError("Gate D spec is not frozen before execution")
    committed = subprocess.run(
        ["git", "show", f"HEAD:{SPEC_RELATIVE.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if committed != SPEC.read_bytes():
        raise GateDError("working Gate D spec differs from the committed spec")
    return payload


def spec_commit() -> str:
    return subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", SPEC_RELATIVE.as_posix()],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_bindings(spec: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    try:
        own_hashes = gate_c.validate_input_hashes(spec)
        gate_c_spec = gate_c.load_spec()
        inherited_hashes = gate_c.validate_input_hashes(gate_c_spec)
        authorization = gate_c.authorize_historical_state(gate_c_spec)
    except (gate_c.GateCError, OSError, ValueError) as exc:
        raise GateDError(f"Gate D input binding failed: {exc}") from exc
    gate_c_result_path = resolve_path(spec["input_bindings"]["gate_c_result"]["path"])
    gate_c_result = json.loads(gate_c_result_path.read_text(encoding="utf-8"))
    if gate_c_result.get("gate_c_result") != "PASS":
        raise GateDError("committed Gate C prerequisite is not PASS")
    if authorization.authorization_id != spec["authorization"]["historical_state_authorization_id"]:
        raise GateDError("Gate D historical-state authorization identity mismatch")
    return {**own_hashes, **{f"gate_c.{key}": value for key, value in inherited_hashes.items()}}, gate_c_spec


def sql_count(connection: duckdb.DuckDBPyConnection, query: str, parameters: list[Any]) -> int:
    return int(connection.execute(query, parameters).fetchone()[0])


def create_full_views(
    connection: duckdb.DuckDBPyConnection,
    gate_c_spec: dict[str, Any],
) -> dict[str, Any]:
    bindings = gate_c_spec["input_bindings"]
    daily = resolve_path(bindings["historical_state_daily"]["path"])
    master = resolve_path(bindings["historical_state_security_master"]["path"])
    events = json.loads(resolve_path(bindings["official_events"]["path"]).read_text(encoding="utf-8"))
    alias_map = gate_c.derive_alias_map(connection, master, events, date(2021, 12, 31))
    reverse_alias = {historical: physical for physical, historical in alias_map.items()}
    alias_frame = pd.DataFrame(
        [
            {"canonical_symbol": canonical, "physical_symbol": physical}
            for canonical, physical in sorted(reverse_alias.items())
        ],
        columns=["canonical_symbol", "physical_symbol"],
    )
    connection.register("gate_d_alias_input", alias_frame)
    connection.execute(
        """
        CREATE TEMP TABLE gate_d_state AS
        SELECT h.trade_date,
               h.symbol AS canonical_symbol,
               coalesce(a.physical_symbol, h.symbol) AS physical_symbol,
               h.listed_trading_days,
               h.trade_status AS authorized_trade_status,
               h.full_day_suspended,
               h.risk_warning,
               h.risk_warning_type,
               h.volume_raw,
               h.amount_raw,
               h.earliest_safe_use_date,
               h.authorization_class
        FROM read_parquet(?) h
        LEFT JOIN gate_d_alias_input a ON h.symbol=a.canonical_symbol
        WHERE h.trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
        ORDER BY h.trade_date, h.symbol
        """,
        [str(daily)],
    )
    connection.execute(
        """
        CREATE TEMP TABLE gate_d_warmup_state AS
        SELECT h.trade_date,
               h.symbol AS canonical_symbol,
               coalesce(a.physical_symbol, h.symbol) AS physical_symbol,
               h.listed_trading_days,
               h.trade_status AS authorized_trade_status,
               h.full_day_suspended,
               h.risk_warning,
               h.risk_warning_type,
               h.volume_raw,
               h.amount_raw,
               h.earliest_safe_use_date,
               h.authorization_class
        FROM read_parquet(?) h
        LEFT JOIN gate_d_alias_input a ON h.symbol=a.canonical_symbol
        WHERE h.trade_date BETWEEN DATE '2017-04-12' AND DATE '2017-12-29'
        ORDER BY h.trade_date, h.symbol
        """,
        [str(daily)],
    )
    cy006_paths = [resolve_path(item["path"]) for item in bindings["cy006_partitions"]]
    connection.execute(
        """
        CREATE TEMP TABLE gate_d_cy006 AS
        SELECT trade_date, symbol AS physical_symbol,
               open, high, low, close, preclose, volume, amount,
               trade_status, is_st, up_limit_price, down_limit_price,
               buy_blocked_open, sell_blocked_open, bar_valid, trading_state_valid,
               corporate_action_valid, market_rule_valid, historical_identity_valid,
               hard_valid, current_day_data_tradable, available_at, snapshot_id,
               corporate_action_count, corporate_action_ids, corporate_action_blocking,
               corporate_action_problems, corporate_action_available_date,
               share_multiplier, cash_per_share, rights_ratio, rights_price
        FROM read_parquet(?)
        WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
          AND regexp_matches(symbol, '^(300|301|302)')
        ORDER BY trade_date, symbol
        """,
        [[str(path) for path in cy006_paths]],
    )
    return {
        "daily": daily,
        "master": master,
        "events": events,
        "alias_map": alias_map,
        "reverse_alias": reverse_alias,
        "cy006_paths": cy006_paths,
    }


def prepare_warmup_prices(
    connection: duckdb.DuckDBPyConnection,
    gate_c_spec: dict[str, Any],
) -> dict[str, Any]:
    inventory_path = resolve_path(gate_c_spec["input_bindings"]["qd001_manifest"]["path"])
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = {str(item["path"]): item for item in inventory["files"]}
    physical_symbols = [row[0] for row in connection.execute(
        "SELECT DISTINCT physical_symbol FROM gate_d_warmup_state ORDER BY physical_symbol"
    ).fetchall()]
    required_paths: list[Path] = []
    hash_failures: list[str] = []
    for symbol in physical_symbols:
        relative = f"{str(symbol).split('.')[0]}.none.parquet"
        record = records.get(relative)
        if record is None:
            hash_failures.append(f"inventory missing {relative}")
            continue
        path = Path(inventory["root"]) / relative
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            hash_failures.append(str(path))
            continue
        required_paths.append(path)
    if hash_failures:
        raise GateDError("required QD-001 warmup file hash failure: " + "; ".join(hash_failures))
    connection.execute(
        """
        CREATE TEMP TABLE gate_d_warmup_prices AS
        SELECT CAST(trade_date AS DATE) AS trade_date,
               CASE
                 WHEN upper(symbol) LIKE '%.SZ' THEN upper(symbol)
                 ELSE upper(symbol) || '.SZ'
               END AS physical_symbol,
               open, high, low, close, preclose, volume, amount
        FROM read_parquet(?)
        WHERE CAST(trade_date AS DATE) BETWEEN DATE '2017-04-12' AND DATE '2017-12-29'
        ORDER BY trade_date, physical_symbol
        """,
        [[str(path) for path in required_paths]],
    )
    return {
        "required_file_count": len(required_paths),
        "required_file_hash_failure_count": 0,
        "required_physical_symbol_count": len(physical_symbols),
    }


def encode_value(value: Any) -> bytes:
    if value is None:
        return b"<NULL>"
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value).isoformat().encode("utf-8")
    if isinstance(value, bool):
        return b"1" if value else b"0"
    if isinstance(value, float):
        if math.isnan(value):
            return b"<NAN>"
        if math.isinf(value):
            return b"<INF>" if value > 0 else b"<-INF>"
        return format(value, ".17g").encode("ascii")
    return str(value).encode("utf-8")


def hash_query(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: list[Any] | None = None,
) -> tuple[str, int]:
    cursor = connection.execute(query, parameters or [])
    digest = hashlib.sha256()
    row_count = 0
    while True:
        rows = cursor.fetchmany(10_000)
        if not rows:
            break
        for row in rows:
            for value in row:
                encoded = encode_value(value)
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
            digest.update(b"\xffROW\x00")
            row_count += 1
    return digest.hexdigest(), row_count


TARGET_LOGICAL_QUERY = """
SELECT h.trade_date, h.canonical_symbol, h.physical_symbol,
       h.listed_trading_days, h.authorized_trade_status,
       h.full_day_suspended, h.risk_warning, h.risk_warning_type,
       h.earliest_safe_use_date, h.authorization_class,
       c.open, c.high, c.low, c.close, c.preclose, c.volume, c.amount,
       c.trade_status, c.is_st, c.up_limit_price, c.down_limit_price,
       c.buy_blocked_open, c.sell_blocked_open, c.bar_valid,
       c.trading_state_valid, c.corporate_action_valid, c.market_rule_valid,
       c.hard_valid, c.current_day_data_tradable, c.available_at, c.snapshot_id,
       c.corporate_action_count, c.corporate_action_ids,
       c.corporate_action_blocking, c.corporate_action_available_date,
       c.share_multiplier, c.cash_per_share, c.rights_ratio, c.rights_price
FROM gate_d_state h
LEFT JOIN gate_d_cy006 c
  ON h.trade_date=c.trade_date AND h.physical_symbol=c.physical_symbol
ORDER BY h.trade_date, h.canonical_symbol
"""

WARMUP_LOGICAL_QUERY = """
SELECT h.trade_date, h.canonical_symbol, h.physical_symbol,
       h.listed_trading_days, h.authorized_trade_status,
       h.full_day_suspended, h.risk_warning, h.risk_warning_type,
       h.earliest_safe_use_date, h.authorization_class,
       p.open, p.high, p.low, p.close, p.preclose, p.volume, p.amount
FROM gate_d_warmup_state h
LEFT JOIN gate_d_warmup_prices p
  ON h.trade_date=p.trade_date AND h.physical_symbol=p.physical_symbol
ORDER BY h.trade_date, h.canonical_symbol
"""


def validate_corporate_actions(
    connection: duckdb.DuckDBPyConnection,
    gate_c_spec: dict[str, Any],
    gate_d_spec: dict[str, Any],
) -> dict[str, Any]:
    bindings = gate_c_spec["input_bindings"]
    distribution_path = resolve_path(bindings["qd010_distributions"]["path"])
    rights_path = resolve_path(bindings["qd010_rights"]["path"])
    distribution_rows = connection.execute(
        """
        SELECT event_id, symbol, known_at, effective_date, event_type,
               source_terms_complete, share_multiplier, cash_per_share_gross
        FROM read_parquet(?)
        WHERE regexp_matches(symbol, '^(300|301|302)')
          AND effective_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
        ORDER BY event_id
        """,
        [str(distribution_path)],
    ).fetchall()
    rights_rows = connection.execute(
        """
        SELECT event_id, symbol, known_at, effective_date, event_type,
               source_terms_complete, rights_subscription_ratio,
               rights_subscription_price
        FROM read_parquet(?)
        WHERE regexp_matches(symbol, '^(300|301|302)')
          AND effective_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
        ORDER BY event_id
        """,
        [str(rights_path)],
    ).fetchall()
    unresolved_rows = connection.execute(
        """
        SELECT event_id, symbol, known_at, effective_date, event_type,
               source_terms_complete, resolution_status,
               execution_timing_unresolved_reason
        FROM read_parquet(?)
        WHERE regexp_matches(symbol, '^(300|301|302)')
          AND known_at BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
          AND effective_date IS NULL
          AND source_terms_complete=false
          AND resolution_status='explicit_unreconciled'
        ORDER BY event_id
        """,
        [str(distribution_path)],
    ).fetchall()
    expected = gate_d_spec["corporate_action_validation"]
    source_ids = {str(row[0]) for row in distribution_rows + rights_rows + unresolved_rows}
    duplicate_source_count = (
        len(distribution_rows) + len(rights_rows) + len(unresolved_rows) - len(source_ids)
    )
    cy006_rows = connection.execute(
        """
        SELECT trade_date, physical_symbol, corporate_action_count,
               corporate_action_ids, corporate_action_blocking,
               corporate_action_valid, corporate_action_available_date,
               corporate_action_problems
        FROM gate_d_cy006 WHERE corporate_action_count > 0
        ORDER BY trade_date, physical_symbol
        """
    ).fetchall()
    cy006_ids: set[str] = set()
    for row in cy006_rows:
        ids = [] if row[3] is None else [item for item in str(row[3]).split("|") if item]
        if len(ids) != int(row[2]):
            raise GateDError(f"CY-006 corporate-action count/ID mismatch: {row[:4]}")
        cy006_ids.update(ids)
    cy006_by_id = {
        event_id: row
        for row in cy006_rows
        for event_id in ([] if row[3] is None else str(row[3]).split("|"))
        if event_id
    }
    direct_fail_closed_overlay: list[dict[str, str]] = []
    unresolved_fail_closed_failure_count = 0
    for row in unresolved_rows:
        event_id = str(row[0])
        physical_symbol = f"{row[1]}.SZ"
        known_at = pd.Timestamp(row[2]).date()
        cy006_row = cy006_by_id.get(event_id)
        if cy006_row is not None:
            valid_marker = (
                cy006_row[4] is True
                and cy006_row[5] is False
                and "missing_effective_date" in str(cy006_row[7])
                and pd.Timestamp(cy006_row[6]).date() >= known_at
            )
            unresolved_fail_closed_failure_count += int(not valid_marker)
            continue
        safe_session = connection.execute(
            """
            SELECT min(trade_date) FROM gate_d_state
            WHERE physical_symbol=? AND trade_date>=?
            """,
            [physical_symbol, known_at],
        ).fetchone()[0]
        if safe_session is None:
            unresolved_fail_closed_failure_count += 1
            continue
        direct_fail_closed_overlay.append(
            {
                "event_id": event_id,
                "physical_symbol": physical_symbol,
                "known_at": known_at.isoformat(),
                "safe_session": safe_session.isoformat(),
                "reason": "missing_effective_date",
            }
        )
    direct_overlay_ids = {row["event_id"] for row in direct_fail_closed_overlay}
    missing_ids = sorted(source_ids - cy006_ids - direct_overlay_ids)
    extra_ids = sorted(cy006_ids - source_ids)
    malformed_distribution_count = sum(
        row[2] is None
        or row[3] is None
        or row[5] is not True
        or row[6] is None
        or float(row[6]) <= 0
        for row in distribution_rows
    )
    malformed_rights_count = sum(
        row[2] is None
        or row[3] is None
        or row[5] is not True
        or row[6] is None
        or row[7] is None
        for row in rights_rows
    )
    failure_count = (
        duplicate_source_count
        + len(missing_ids)
        + len(extra_ids)
        + malformed_distribution_count
        + malformed_rights_count
        + unresolved_fail_closed_failure_count
        + int(len(distribution_rows) != expected["expected_target_qd010_distribution_events"])
        + int(len(rights_rows) != expected["expected_target_qd010_rights_events"])
    )
    event_hash = hashlib.sha256(
        "".join(f"{event_id}\n" for event_id in sorted(source_ids)).encode("utf-8")
    ).hexdigest()
    overlay_hash = hashlib.sha256(canonical_bytes(direct_fail_closed_overlay)).hexdigest()
    return {
        "corporate_action_failure_count": failure_count,
        "cy006_action_event_id_count": len(cy006_ids),
        "cy006_blocking_row_count": sum(bool(row[4]) for row in cy006_rows),
        "cy006_invalid_action_row_count": sum(row[5] is not True for row in cy006_rows),
        "distribution_event_count": len(distribution_rows),
        "duplicate_source_event_count": duplicate_source_count,
        "event_id_set_sha256": event_hash,
        "direct_fail_closed_overlay": direct_fail_closed_overlay,
        "direct_fail_closed_overlay_sha256": overlay_hash,
        "extra_cy006_event_ids": extra_ids,
        "malformed_distribution_count": malformed_distribution_count,
        "malformed_rights_count": malformed_rights_count,
        "missing_cy006_event_ids": missing_ids,
        "rights_event_count": len(rights_rows),
        "rights_participation": "FAIL_CLOSED_EXECUTION_UNRESOLVED",
        "unresolved_fail_closed_event_count": len(unresolved_rows),
        "unresolved_fail_closed_event_ids": [str(row[0]) for row in unresolved_rows],
        "unresolved_fail_closed_failure_count": unresolved_fail_closed_failure_count,
    }


def strategy_input_matrix(
    spec: dict[str, Any],
    *,
    metrics: dict[str, int],
    market_coverage_ok: bool,
    corporate_actions: dict[str, Any],
) -> tuple[list[dict[str, str]], str]:
    rows: list[dict[str, str]] = []
    for requirement in spec["strategy_input_requirements"]:
        name = requirement["input"]
        coverage = "PASS"
        if name in {"raw unadjusted close history", "raw volume history", "raw amount"}:
            coverage = "PASS" if metrics["price_input_missing_count"] == 0 else "FAIL"
        elif name in {
            "historical GEM identity and listed trading age",
            "NORMAL/ST/STAR_ST state",
            "full-session suspension",
        }:
            coverage = (
                "PASS"
                if metrics["required_state_missing_count"] == 0
                and metrics["state_unknown_count"] == 0
                and metrics["state_conflict_count"] == 0
                else "FAIL"
            )
        elif name == "corporate-action event terms and causal coordinates":
            coverage = (
                "PASS" if corporate_actions["corporate_action_failure_count"] == 0 else "FAIL"
            )
        elif name == "trading calendar":
            coverage = "PASS" if metrics["calendar_mismatch_count"] == 0 else "FAIL"
        elif name == "399102.SZ market close":
            coverage = "PASS" if market_coverage_ok else "FAIL"
        elif name == "next-session open, T+1, tradability, and open-limit state":
            coverage = "PASS" if metrics["price_input_missing_count"] == 0 else "FAIL"
        rows.append(
            {
                "strategy_input": name,
                "source": requirement["authorization"],
                "lookback": requirement["lookback"],
                "earliest_required_date": requirement["earliest_required_date"],
                "coverage_status": coverage,
                "authorization_status": "PASS_BOUNDED_PIT_B",
                "fail_closed_status": "PASS",
            }
        )
    status = "PASS" if all(row["coverage_status"] == "PASS" for row in rows) else "FAIL"
    return rows, status


def build_result() -> dict[str, Any]:
    spec = load_spec()
    verified_hashes, gate_c_spec = validate_bindings(spec)
    connection = duckdb.connect()
    context = create_full_views(connection, gate_c_spec)
    warmup_files = prepare_warmup_prices(connection, gate_c_spec)
    expected = spec["expected_full_scope_metrics"]
    master = context["master"]
    calendar = resolve_path(gate_c_spec["input_bindings"]["qd003_calendar"]["path"])

    target_rows, target_dates, target_symbols, suspensions = connection.execute(
        """
        SELECT count(*), count(DISTINCT trade_date), count(DISTINCT canonical_symbol),
               count(*) FILTER (WHERE full_day_suspended)
        FROM gate_d_state
        """
    ).fetchone()
    duplicate_state_keys = sql_count(
        connection,
        "SELECT count(*) FROM (SELECT trade_date,canonical_symbol,count(*) n FROM gate_d_state GROUP BY 1,2 HAVING n<>1)",
        [],
    )
    state_unknown_count = sql_count(
        connection,
        """
        SELECT count(*) FROM gate_d_state
        WHERE canonical_symbol IS NULL OR physical_symbol IS NULL
           OR listed_trading_days IS NULL OR listed_trading_days < 1
           OR authorized_trade_status NOT IN ('0','1')
           OR full_day_suspended IS NULL OR risk_warning IS NULL
           OR risk_warning_type NOT IN ('NORMAL','ST','STAR_ST')
           OR earliest_safe_use_date IS NULL OR earliest_safe_use_date <= trade_date
           OR authorization_class <> 'BOUNDED_EFFECTIVE_STATE_PIT_B'
        """,
        [],
    )
    expected_state_delta = sql_count(
        connection,
        """
        WITH calendar AS (
          SELECT DISTINCT CAST(trade_date AS DATE) trade_date FROM read_parquet(?)
          WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
        ), expected_keys AS (
          SELECT c.trade_date, m.symbol canonical_symbol
          FROM calendar c CROSS JOIN read_parquet(?) m
          WHERE c.trade_date >= m.list_date
            AND (m.out_date IS NULL OR c.trade_date <= m.out_date)
        ), missing AS (
          SELECT * FROM expected_keys EXCEPT SELECT trade_date,canonical_symbol FROM gate_d_state
        ), extra AS (
          SELECT trade_date,canonical_symbol FROM gate_d_state EXCEPT SELECT * FROM expected_keys
        )
        SELECT (SELECT count(*) FROM missing) + (SELECT count(*) FROM extra)
        """,
        [str(calendar), str(master)],
    )
    boundary_mismatch_rows = sql_count(
        connection,
        """
        SELECT count(*) FROM gate_d_state s JOIN read_parquet(?) m ON s.canonical_symbol=m.symbol
        WHERE s.trade_date < m.list_date OR (m.out_date IS NOT NULL AND s.trade_date > m.out_date)
        """,
        [str(master)],
    )
    invalid_identity_rows = sql_count(
        connection,
        """
        SELECT count(*) FROM gate_d_state
        WHERE NOT regexp_matches(canonical_symbol, '^(300|301)[0-9]{3}\\.SZ$')
           OR canonical_symbol='302132.SZ'
        """,
        [],
    )

    target_join = connection.execute(
        """
        SELECT
          count(*) FILTER (WHERE c.physical_symbol IS NULL),
          count(*) FILTER (
            WHERE c.physical_symbol IS NULL OR (
              NOT h.full_day_suspended AND (
                c.open IS NULL OR NOT isfinite(c.open) OR c.open<=0 OR
                c.high IS NULL OR NOT isfinite(c.high) OR c.high<=0 OR
                c.low IS NULL OR NOT isfinite(c.low) OR c.low<=0 OR
                c.close IS NULL OR NOT isfinite(c.close) OR c.close<=0 OR
                c.volume IS NULL OR NOT isfinite(c.volume) OR c.volume<=0 OR
                c.amount IS NULL OR NOT isfinite(c.amount) OR c.amount<0
              )
            )
          ),
          count(*) FILTER (
            WHERE c.physical_symbol IS NOT NULL AND (
              h.full_day_suspended <> (c.trade_status=0) OR
              h.risk_warning <> c.is_st
            )
          ),
          count(*) FILTER (
            WHERE c.physical_symbol IS NOT NULL AND
              (c.trade_status IS NULL OR c.is_st IS NULL OR c.available_at IS NULL OR c.snapshot_id IS NULL)
          )
        FROM gate_d_state h LEFT JOIN gate_d_cy006 c
          ON h.trade_date=c.trade_date AND h.physical_symbol=c.physical_symbol
        """
    ).fetchone()
    target_missing_rows, target_price_invalid, state_conflict_count, cy006_unknown = map(int, target_join)

    warmup_join = connection.execute(
        """
        SELECT
          count(*) FILTER (WHERE p.physical_symbol IS NULL),
          count(*) FILTER (
            WHERE p.physical_symbol IS NULL OR (
              NOT h.full_day_suspended AND (
                p.open IS NULL OR NOT isfinite(p.open) OR p.open<=0 OR
                p.high IS NULL OR NOT isfinite(p.high) OR p.high<=0 OR
                p.low IS NULL OR NOT isfinite(p.low) OR p.low<=0 OR
                p.close IS NULL OR NOT isfinite(p.close) OR p.close<=0 OR
                p.volume IS NULL OR NOT isfinite(p.volume) OR p.volume<=0 OR
                p.amount IS NULL OR NOT isfinite(p.amount) OR p.amount<0
              )
            )
          )
        FROM gate_d_warmup_state h LEFT JOIN gate_d_warmup_prices p
          ON h.trade_date=p.trade_date AND h.physical_symbol=p.physical_symbol
        """
    ).fetchone()
    warmup_missing_rows, warmup_price_invalid = map(int, warmup_join)

    target_calendar_mismatch = sql_count(
        connection,
        """
        WITH expected AS (
          SELECT DISTINCT CAST(trade_date AS DATE) trade_date FROM read_parquet(?)
          WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
        ), actual AS (SELECT DISTINCT trade_date FROM gate_d_state),
        delta AS ((SELECT * FROM expected EXCEPT SELECT * FROM actual)
                  UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected))
        SELECT count(*) FROM delta
        """,
        [str(calendar)],
    )
    warmup_calendar_mismatch = sql_count(
        connection,
        """
        WITH expected AS (
          SELECT DISTINCT CAST(trade_date AS DATE) trade_date FROM read_parquet(?)
          WHERE trade_date BETWEEN DATE '2017-04-12' AND DATE '2017-12-29'
        ), actual AS (SELECT DISTINCT trade_date FROM gate_d_warmup_state),
        delta AS ((SELECT * FROM expected EXCEPT SELECT * FROM actual)
                  UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected))
        SELECT count(*) FROM delta
        """,
        [str(calendar)],
    )
    calendar_mismatch_count = target_calendar_mismatch + warmup_calendar_mismatch

    target_non_survivors = sql_count(
        connection,
        """
        SELECT count(DISTINCT s.canonical_symbol) FROM gate_d_state s
        JOIN read_parquet(?) m ON s.canonical_symbol=m.symbol
        WHERE m.identity_status='HISTORICAL_NON_SURVIVOR'
        """,
        [str(master)],
    )
    new_listings, delistings = connection.execute(
        """
        SELECT count(*) FILTER (WHERE list_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'),
               count(*) FILTER (WHERE out_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31')
        FROM read_parquet(?)
        """,
        [str(master)],
    ).fetchone()
    manifest = json.loads(
        resolve_path(gate_c_spec["input_bindings"]["historical_state_manifest"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    st_intervals = sum(item["risk_warning_type"] == "ST" for item in manifest["risk_warning"]["intervals"])
    star_intervals = sum(
        item["risk_warning_type"] == "STAR_ST" for item in manifest["risk_warning"]["intervals"]
    )
    removals = len(context["events"]["validation_events"])

    corporate_actions = validate_corporate_actions(connection, gate_c_spec, spec)

    target_hash_1, target_hash_rows_1 = hash_query(connection, TARGET_LOGICAL_QUERY)
    warmup_hash_1, warmup_hash_rows_1 = hash_query(connection, WARMUP_LOGICAL_QUERY)
    target_hash_2, target_hash_rows_2 = hash_query(connection, TARGET_LOGICAL_QUERY)
    warmup_hash_2, warmup_hash_rows_2 = hash_query(connection, WARMUP_LOGICAL_QUERY)
    combined_1 = hashlib.sha256(
        f"{target_hash_1}\n{warmup_hash_1}\n{corporate_actions['event_id_set_sha256']}\n{corporate_actions['direct_fail_closed_overlay_sha256']}\n".encode(
            "utf-8"
        )
    ).hexdigest()
    combined_2 = hashlib.sha256(
        f"{target_hash_2}\n{warmup_hash_2}\n{corporate_actions['event_id_set_sha256']}\n{corporate_actions['direct_fail_closed_overlay_sha256']}\n".encode(
            "utf-8"
        )
    ).hexdigest()
    determinism_mismatch_count = int(
        target_hash_1 != target_hash_2
        or warmup_hash_1 != warmup_hash_2
        or combined_1 != combined_2
        or target_hash_rows_1 != target_hash_rows_2
        or warmup_hash_rows_1 != warmup_hash_rows_2
    )

    market = pd.read_csv(resolve_path(spec["input_bindings"]["market_anchor_399102"]["path"]), dtype={"trade_date": str})
    market_dates = set(pd.to_datetime(market["trade_date"], format="%Y%m%d").dt.date)
    required_market_dates = {
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT CAST(trade_date AS DATE) FROM read_parquet(?)
            WHERE trade_date BETWEEN DATE '2017-12-01' AND DATE '2021-12-31'
            """,
            [str(calendar)],
        ).fetchall()
    }
    market_coverage_ok = required_market_dates <= market_dates

    price_input_missing_count = target_price_invalid + warmup_price_invalid
    required_state_missing_count = duplicate_state_keys + expected_state_delta
    universe_mismatch_count = (
        boundary_mismatch_rows
        + invalid_identity_rows
        + int(int(target_rows) != expected["target_daily_state_rows"])
        + int(int(target_dates) != expected["trading_dates_validated"])
        + int(int(target_symbols) != expected["historical_symbols_ever_seen"])
        + int(int(target_non_survivors) != expected["non_survivors_retained"])
        + int(int(new_listings) != expected["new_listings_captured"])
        + int(int(delistings) != expected["delistings_captured"])
    )
    metrics = {
        "alias_normalizations_applied": len(context["alias_map"]),
        "authorized_foundation_historical_symbols": int(
            manifest["counts"]["historical_symbols_ever_seen"]
        ),
        "authorization_failure_count": 0,
        "calendar_mismatch_count": calendar_mismatch_count,
        "corporate_action_failure_count": corporate_actions["corporate_action_failure_count"],
        "delistings_captured": int(delistings),
        "determinism_mismatch_count": determinism_mismatch_count,
        "hash_failure_count": 0,
        "historical_gem_symbols_ever_seen": int(target_symbols),
        "historical_symbols_ever_seen": int(target_symbols),
        "new_listings_captured": int(new_listings),
        "non_survivors_retained": int(target_non_survivors),
        "price_input_missing_count": price_input_missing_count,
        "required_state_missing_count": required_state_missing_count,
        "risk_warning_removals_captured_validation_only": removals,
        "star_st_intervals_captured": star_intervals,
        "state_conflict_count": state_conflict_count,
        "state_unknown_count": state_unknown_count + cy006_unknown,
        "st_intervals_captured": st_intervals,
        "suspension_sessions_captured": int(suspensions),
        "target_daily_state_rows": int(target_rows),
        "trading_dates_validated": int(target_dates),
        "universe_mismatch_count": universe_mismatch_count,
    }
    matrix, matrix_status = strategy_input_matrix(
        spec,
        metrics=metrics,
        market_coverage_ok=market_coverage_ok,
        corporate_actions=corporate_actions,
    )
    zero_rule = spec["zero_tolerance_pass_rule"]
    zero_rule_pass = all(metrics[key] == value for key, value in zero_rule.items())
    expected_metrics_pass = all(metrics.get(key) == value for key, value in expected.items())
    gate_d_result = "PASS" if zero_rule_pass and expected_metrics_pass and matrix_status == "PASS" else "FAIL"
    result: dict[str, Any] = {
        "authorization": spec["authorization"],
        "corporate_actions": corporate_actions,
        "execution_firewall": spec["execution_firewall"],
        "expected_metrics_match": expected_metrics_pass,
        "gate_d_result": gate_d_result,
        "gate_d_repair_count": GATE_D_REPAIR_COUNT,
        "input_hashes_verified": len(verified_hashes),
        "logical_materialization": {
            "combined_sha256": combined_1,
            "deterministic": determinism_mismatch_count == 0,
            "persistent_duplicate_daily_store": False,
            "target_rows": target_hash_rows_1,
            "target_sha256": target_hash_1,
            "warmup_rows": warmup_hash_rows_1,
            "warmup_sha256": warmup_hash_1,
        },
        "market_anchor": {
            "coverage_status": "PASS" if market_coverage_ok else "FAIL",
            "missing_required_sessions": len(required_market_dates - market_dates),
        },
        "metrics": metrics,
        "prerequisites": spec["prerequisites"],
        "safe_to_run_extended_history_strategy_replay": "YES" if gate_d_result == "PASS" else "NO",
        "spec_commit": spec_commit(),
        "spec_id": spec["spec_id"],
        "spec_sha256": sha256_file(SPEC),
        "strategy_input_requirement_matrix": matrix,
        "strategy_input_requirement_matrix_status": matrix_status,
        "warmup": {
            **warmup_files,
            "logical_rows": warmup_hash_rows_1,
            "missing_price_rows": warmup_missing_rows,
            "normal_session_invalid_price_rows": warmup_price_invalid - warmup_missing_rows,
        },
        "target_join": {
            "logical_rows": target_hash_rows_1,
            "missing_cy006_rows": target_missing_rows,
            "normal_session_invalid_price_rows": target_price_invalid - target_missing_rows,
        },
        "zero_tolerance_pass": zero_rule_pass,
    }
    connection.close()
    return result


def write_report(result: dict[str, Any]) -> None:
    metric_lines = [
        f"- {key.upper()}: `{value}`" for key, value in result["metrics"].items()
    ]
    matrix_lines = [
        "| Strategy input | Source/authorization | Lookback | Earliest | Coverage | Fail closed |",
        "|---|---|---|---|---|---|",
    ]
    matrix_lines.extend(
        "| {strategy_input} | {source} | {lookback} | {earliest_required_date} | {coverage_status} | {fail_closed_status} |".format(
            **row
        )
        for row in result["strategy_input_requirement_matrix"]
    )
    lines = [
        "# ChinNext V1 — Gate D full PIT input validation",
        "",
        "> Full bounded input/materialization correctness only. No strategy signal, trade, NAV, or performance was generated.",
        "",
        f"- GATE_D: `{result['gate_d_result']}`",
        f"- GATE_D_REPAIR_COUNT: `{result['gate_d_repair_count']}`",
        f"- SPEC_SHA256: `{result['spec_sha256']}`",
        f"- SPEC_COMMIT: `{result['spec_commit']}`",
        f"- STRATEGY_INPUT_REQUIREMENT_MATRIX_STATUS: `{result['strategy_input_requirement_matrix_status']}`",
        f"- SAFE_TO_RUN_EXTENDED_HISTORY_STRATEGY_REPLAY: `{result['safe_to_run_extended_history_strategy_replay']}`",
        "- STRICT_PIT_A: `NO`",
        "",
        "## Full-scope metrics",
        "",
        *metric_lines,
        "",
        "## Deterministic logical materialization",
        "",
        f"- TARGET_ROWS: `{result['logical_materialization']['target_rows']}`",
        f"- TARGET_SHA256: `{result['logical_materialization']['target_sha256']}`",
        f"- WARMUP_ROWS: `{result['logical_materialization']['warmup_rows']}`",
        f"- WARMUP_SHA256: `{result['logical_materialization']['warmup_sha256']}`",
        f"- COMBINED_SHA256: `{result['logical_materialization']['combined_sha256']}`",
        f"- DETERMINISTIC: `{'PASS_LOGICAL_HASH_IDENTICAL' if result['logical_materialization']['deterministic'] else 'FAIL'}`",
        "- PERSISTENT_DUPLICATE_DAILY_STORE: `NO`",
        "",
        "## Strategy input requirement matrix",
        "",
        *matrix_lines,
        "",
        "Explicitly unsupported rights participation remains fail-closed. The historical-state alias overlay is data-driven and only normalizes the official 302132.SZ physical projection to 300114.SZ inside the bounded pre-2025 interval.",
        "",
    ]
    atomic_write(REPORT, "\n".join(lines).encode("utf-8"))


def main() -> int:
    result = build_result()
    atomic_write(RESULT, canonical_bytes(result))
    write_report(result)
    print(
        json.dumps(
            {
                "gate_d": result["gate_d_result"],
                "safe_to_run_extended_history_strategy_replay": result[
                    "safe_to_run_extended_history_strategy_replay"
                ],
                **{key: result["metrics"][key] for key in result["metrics"] if key.endswith("_count")},
            },
            sort_keys=True,
        )
    )
    return 0 if result["gate_d_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
