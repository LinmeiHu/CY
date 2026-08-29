#!/usr/bin/env python3
"""Execute the committed ChinNext V1 Gate C correctness pilot without performance."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
SRC = ROOT / "src"
for import_root in (str(SCRIPTS), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from chinext_v1_qd001_causal_adapter import (  # noqa: E402
    CausalCorporateActionError,
    rebase_history,
    validate_event,
    visible_events,
)
from cyq_game.data import DataActivationError, DataAssetRegistry, DataPurpose  # noqa: E402

SPEC_RELATIVE = Path("research/chinext_v1/specs/chinext_v1_gate_c_preregistration.json")
SPEC = ROOT / SPEC_RELATIVE
RESULT = ROOT / "research/chinext_v1/reports/chinext_v1_gate_c_result.json"
REPORT = ROOT / "research/chinext_v1/reports/chinext_v1_gate_c_result.md"
CONSUMER = Path(__file__).resolve()
GATE_C_REPAIR_COUNT = 3


class GateCError(RuntimeError):
    """Raised before consuming a Gate C input whose frozen identity is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_lines(values: list[str]) -> str:
    return hashlib.sha256("".join(f"{value}\n" for value in values).encode("utf-8")).hexdigest()


def canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=lambda value: value.isoformat()
            if isinstance(value, (date, pd.Timestamp))
            else str(value),
        )
        + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def load_spec() -> dict[str, Any]:
    payload = json.loads(SPEC.read_text(encoding="utf-8"))
    if payload.get("spec_id") != "CHINEXT-V1-GATE-C-BOUNDED-CORRECTNESS-PILOT-V1":
        raise GateCError("unexpected Gate C spec identity")
    if payload.get("status") != "FROZEN_BEFORE_PILOT_EXECUTION":
        raise GateCError("Gate C spec is not frozen before execution")
    committed = subprocess.run(
        ["git", "show", f"HEAD:{SPEC_RELATIVE.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if committed != SPEC.read_bytes():
        raise GateCError("working Gate C spec differs from the committed spec")
    return payload


def spec_commit() -> str:
    return subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", SPEC_RELATIVE.as_posix()],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def iter_bound_files(value: object) -> list[tuple[str, Path, str]]:
    found: list[tuple[str, Path, str]] = []

    def visit(node: object, label: str) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("path"), str) and isinstance(node.get("sha256"), str):
                found.append((label, resolve_path(node["path"]), str(node["sha256"])))
            for key, child in node.items():
                visit(child, f"{label}.{key}" if label else str(key))
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{label}[{index}]")

    visit(value, "")
    return found


def validate_input_hashes(spec: dict[str, Any]) -> dict[str, str]:
    actual: dict[str, str] = {}
    failures: list[str] = []
    for role, path, expected in iter_bound_files(spec["input_bindings"]):
        if not path.is_file():
            failures.append(f"{role}: missing {path}")
            continue
        digest = sha256_file(path)
        actual[role] = digest
        if digest != expected:
            failures.append(f"{role}: expected {expected}, got {digest}")
    if failures:
        raise GateCError("frozen input hash failure: " + "; ".join(failures))
    return actual


def authorize_historical_state(spec: dict[str, Any]) -> Any:
    bindings = spec["input_bindings"]
    registry_path = resolve_path(bindings["data_asset_registry"]["path"])
    registry = DataAssetRegistry.load(registry_path)
    authorization = spec["authorization"]
    manifest = bindings["historical_state_manifest"]
    daily = bindings["historical_state_daily"]
    master = bindings["historical_state_security_master"]
    strategy = bindings["frozen_strategy_reference"]
    return registry.authorize_bounded_research(
        authorization["authorization_id"],
        purpose=DataPurpose.CHINEXT_PIT_B_RESEARCH,
        manifest_path=resolve_path(manifest["path"]),
        manifest_sha256=manifest["sha256"],
        artifacts={
            "daily_historical_state": (resolve_path(daily["path"]), daily["sha256"]),
            "security_master": (resolve_path(master["path"]), master["sha256"]),
        },
        start=date.fromisoformat(authorization["authorized_date_range"][0]),
        end=date.fromisoformat(authorization["authorized_date_range"][1]),
        dependency_asset_id="QD-007",
        consumer_path=CONSUMER,
        strategy_path=resolve_path(strategy["path"]),
        strategy_sha256=strategy["sha256"],
        current_survivor_fallback=False,
    )


def expect_error(
    check_id: str,
    action: Callable[[], object],
    error_type: type[BaseException],
    required_text: str,
) -> dict[str, str]:
    try:
        action()
    except error_type as exc:
        if required_text not in str(exc):
            raise GateCError(
                f"{check_id} raised the expected type but wrong reason: {exc}"
            ) from exc
        return {"check_id": check_id, "status": "PASS_FAIL_CLOSED", "reason": str(exc)}
    raise GateCError(f"{check_id} did not fail closed")


def authorization_fail_closed_checks(spec: dict[str, Any]) -> list[dict[str, str]]:
    bindings = spec["input_bindings"]
    authorization = spec["authorization"]
    registry = DataAssetRegistry.load(resolve_path(bindings["data_asset_registry"]["path"]))
    manifest = bindings["historical_state_manifest"]
    daily = bindings["historical_state_daily"]
    master = bindings["historical_state_security_master"]
    strategy = bindings["frozen_strategy_reference"]
    base: dict[str, Any] = {
        "purpose": DataPurpose.CHINEXT_PIT_B_RESEARCH,
        "manifest_path": resolve_path(manifest["path"]),
        "manifest_sha256": manifest["sha256"],
        "artifacts": {
            "daily_historical_state": (resolve_path(daily["path"]), daily["sha256"]),
            "security_master": (resolve_path(master["path"]), master["sha256"]),
        },
        "start": date(2017, 4, 12),
        "end": date(2021, 12, 31),
        "dependency_asset_id": "QD-007",
        "consumer_path": CONSUMER,
        "strategy_path": resolve_path(strategy["path"]),
        "strategy_sha256": strategy["sha256"],
        "current_survivor_fallback": False,
    }

    def request(**changes: Any) -> Any:
        values = {**base, **changes}
        return registry.authorize_bounded_research(authorization["authorization_id"], **values)

    return [
        expect_error(
            "AUTH_BAD_HASH",
            lambda: request(manifest_sha256="0" * 64),
            DataActivationError,
            "manifest hash mismatch",
        ),
        expect_error(
            "AUTH_OUT_OF_RANGE",
            lambda: request(end=date(2022, 1, 4)),
            DataActivationError,
            "date range mismatch",
        ),
        expect_error(
            "AUTH_CURRENT_SURVIVOR_FALLBACK",
            lambda: request(current_survivor_fallback=True),
            DataActivationError,
            "current-survivor fallback is forbidden",
        ),
        expect_error(
            "AUTH_WRONG_CLASS",
            lambda: request(purpose=DataPurpose.CAUSAL_RESEARCH),
            DataActivationError,
            "purpose mismatch",
        ),
        expect_error(
            "AUTH_MISSING_REGISTRATION",
            lambda: registry.authorize_bounded_research("MISSING-GATE-C-AUTH", **base),
            DataActivationError,
            "missing bounded research authorization",
        ),
    ]


def case(spec: dict[str, Any], case_id: str) -> dict[str, Any]:
    matches = [item for item in spec["sample_design"]["cases"] if item["case_id"] == case_id]
    if len(matches) != 1:
        raise GateCError(f"missing or duplicate frozen case: {case_id}")
    return matches[0]


def official_document_check(spec: dict[str, Any]) -> dict[str, Any]:
    index_path = resolve_path(spec["input_bindings"]["official_document_index"]["path"])
    index = json.loads(index_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for document in index["documents"]:
        path = resolve_path(document["path"])
        if not path.is_file() or sha256_file(path) != document["sha256"]:
            failures.append(str(path))
    return {
        "document_count": len(index["documents"]),
        "failure_count": len(failures),
        "failures": failures,
        "status": "PASS" if not failures and len(index["documents"]) == 27 else "FAIL",
    }


def derive_alias_map(
    connection: duckdb.DuckDBPyConnection,
    master_path: Path,
    official_events: dict[str, Any],
    target_end: date,
) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT symbol, current_symbol_diagnostic, out_date,
               official_alias_source_sha256
        FROM read_parquet(?)
        WHERE official_alias_source_sha256 IS NOT NULL
          AND current_symbol_diagnostic IS NOT NULL
          AND current_symbol_diagnostic <> symbol
        ORDER BY symbol
        """,
        [str(master_path)],
    ).fetchall()
    event_by_pair = {
        (str(item["old_code"]), str(item["new_code"])): item
        for item in official_events["identity_events"]
    }
    result: dict[str, str] = {}
    for historical, current, boundary, source_hash in rows:
        event = event_by_pair.get((str(historical), str(current)))
        if event is None:
            raise GateCError(f"alias master row lacks official event: {historical}->{current}")
        effective = date.fromisoformat(str(event["effective_date"]))
        if boundary != effective or str(event["source_document_sha256"]) != str(source_hash):
            raise GateCError(f"alias master/event boundary mismatch: {historical}->{current}")
        if target_end >= effective:
            raise GateCError("Gate C target crosses an alias boundary unsupported by this overlay")
        if current in result:
            raise GateCError(f"ambiguous projected source symbol: {current}")
        result[str(current)] = str(historical)
    return result


def build_result(spec: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = load_spec() if spec is None else spec
    actual_hashes = validate_input_hashes(spec)
    authorization = authorize_historical_state(spec)
    auth_checks = authorization_fail_closed_checks(spec)
    bindings = spec["input_bindings"]
    daily = resolve_path(bindings["historical_state_daily"]["path"])
    master = resolve_path(bindings["historical_state_security_master"]["path"])
    manifest = json.loads(
        resolve_path(bindings["historical_state_manifest"]["path"]).read_text(encoding="utf-8")
    )
    events = json.loads(resolve_path(bindings["official_events"]["path"]).read_text(encoding="utf-8"))
    cy006_paths = [resolve_path(item["path"]) for item in bindings["cy006_partitions"]]
    connection = duckdb.connect()
    checks: list[dict[str, Any]] = []

    def record(invariant_id: str, passed: bool, details: Any) -> None:
        checks.append(
            {
                "invariant_id": invariant_id,
                "status": "PASS" if passed else "FAIL",
                "details": details,
            }
        )

    denominator = manifest["historical_denominator_samples"]
    denominator_hashes = [item["sorted_code_set_sha256"] for item in denominator.values()]
    record(
        "C-IDENTITY-001",
        len(denominator) == 6
        and len(set(denominator_hashes)) == 6
        and manifest["acquisition"]["trading_dates_acquired"] == 1153
        and manifest["acquisition"]["snapshot_failure_count"] == 0,
        {"sample_hashes": denominator_hashes, "trading_dates": 1153},
    )

    listing = case(spec, "C-CASE-NEW-LISTING")
    listing_rows = connection.execute(
        "SELECT trade_date, listed_trading_days FROM read_parquet(?) WHERE symbol=? ORDER BY trade_date",
        [str(daily), listing["symbol"]],
    ).fetchall()
    record(
        "C-IDENTITY-002",
        bool(listing_rows)
        and listing_rows[0] == (
            date.fromisoformat(listing["first_present_date"]),
            listing["expected_first_listed_trading_days"],
        )
        and not any(row[0] == date.fromisoformat(listing["absent_date"]) for row in listing_rows),
        {"first_row": listing_rows[0] if listing_rows else None},
    )

    delisting = case(spec, "C-CASE-DELISTING-NON-SURVIVOR")
    delisting_dates = connection.execute(
        "SELECT min(trade_date), max(trade_date) FROM read_parquet(?) WHERE symbol=?",
        [str(daily), delisting["symbol"]],
    ).fetchone()
    delisting_master = connection.execute(
        "SELECT out_date, identity_status FROM read_parquet(?) WHERE symbol=?",
        [str(master), delisting["symbol"]],
    ).fetchone()
    absent_count = connection.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE symbol=? AND trade_date=?",
        [str(daily), delisting["symbol"], delisting["absent_date"]],
    ).fetchone()[0]
    record(
        "C-IDENTITY-003",
        delisting_dates[1] == date.fromisoformat(delisting["last_present_date"])
        and delisting_master
        == (
            date.fromisoformat(delisting["last_present_date"]),
            delisting["expected_identity_status"],
        )
        and absent_count == 0,
        {"date_range": delisting_dates, "master": delisting_master},
    )

    non_survivor = case(spec, "C-CASE-NON-SURVIVOR-RETENTION")
    retained = {
        row[0]
        for row in connection.execute(
            "SELECT symbol FROM read_parquet(?) WHERE identity_status='HISTORICAL_NON_SURVIVOR'",
            [str(master)],
        ).fetchall()
    }
    record(
        "C-IDENTITY-004",
        len(retained) == non_survivor["expected_total_count"]
        and set(non_survivor["required_symbols"]) <= retained,
        {"count": len(retained), "required_symbols": non_survivor["required_symbols"]},
    )

    alias = case(spec, "C-CASE-ALIAS-NORMALIZATION")
    alias_map = derive_alias_map(connection, master, events, date(2021, 12, 31))
    old_rows, new_rows = connection.execute(
        """
        SELECT count(*) FILTER (WHERE symbol=?), count(*) FILTER (WHERE symbol=?)
        FROM read_parquet(?)
        """,
        [alias["old_code"], alias["new_code"], str(daily)],
    ).fetchone()
    cy006_alias_rows = connection.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE symbol=? AND trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'",
        [[str(path) for path in cy006_paths], alias["cy006_projected_source_symbol"]],
    ).fetchone()[0]
    cy006_old_rows = connection.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE symbol=? AND trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'",
        [[str(path) for path in cy006_paths], alias["old_code"]],
    ).fetchone()[0]
    alias_state_matches = connection.execute(
        """
        SELECT count(*)
        FROM read_parquet(?) c
        INNER JOIN read_parquet(?) h
          ON c.trade_date=h.trade_date AND h.symbol=?
        WHERE c.symbol=? AND c.trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
        """,
        [[str(path) for path in cy006_paths], str(daily), alias["old_code"], alias["new_code"]],
    ).fetchone()[0]
    record(
        "C-IDENTITY-005",
        alias_map == {alias["new_code"]: alias["old_code"]}
        and old_rows == alias["expected_authorized_old_code_rows"]
        and new_rows == alias["expected_authorized_new_code_rows"]
        and cy006_alias_rows == alias["expected_cy006_target_rows_mapped"]
        and cy006_old_rows == 0
        and alias_state_matches == cy006_alias_rows,
        {
            "alias_map": alias_map,
            "authorized_old_rows": old_rows,
            "authorized_new_rows": new_rows,
            "cy006_source_rows": cy006_alias_rows,
            "state_matches": alias_state_matches,
        },
    )

    st_case = case(spec, "C-CASE-ST")
    star_case = case(spec, "C-CASE-STAR-ST")
    risk_rows: dict[str, list[tuple[date, str]]] = {}
    for frozen in (st_case, star_case):
        risk_rows[frozen["case_id"]] = connection.execute(
            """
            SELECT trade_date, risk_warning_type FROM read_parquet(?)
            WHERE symbol=? AND trade_date IN (?, ?) ORDER BY trade_date
            """,
            [
                str(daily),
                frozen["symbol"],
                frozen["before"]["date"],
                frozen["effective"]["date"],
            ],
        ).fetchall()
    official_risk_keys = {
        (item["symbol"], item["effective_date"], item["risk_warning_type"])
        for item in events["risk_warning_events"]
    }
    expected_st = [
        (date.fromisoformat(st_case["before"]["date"]), st_case["before"]["risk_warning_type"]),
        (date.fromisoformat(st_case["effective"]["date"]), st_case["effective"]["risk_warning_type"]),
    ]
    expected_star = [
        (date.fromisoformat(star_case["before"]["date"]), star_case["before"]["risk_warning_type"]),
        (date.fromisoformat(star_case["effective"]["date"]), star_case["effective"]["risk_warning_type"]),
    ]
    record(
        "C-STATE-001",
        risk_rows[st_case["case_id"]] == expected_st
        and risk_rows[star_case["case_id"]] == expected_star
        and (
            st_case["symbol"],
            st_case["effective"]["date"],
            "ST",
        )
        in official_risk_keys
        and (
            star_case["symbol"],
            star_case["effective"]["date"],
            "STAR_ST",
        )
        in official_risk_keys
        and len(events["risk_warning_events"]) == 24
        and len(official_risk_keys) == 24,
        {"st": risk_rows[st_case["case_id"]], "star_st": risk_rows[star_case["case_id"]]},
    )

    removal = case(spec, "C-CASE-RISK-WARNING-REMOVAL")
    matching_removals = [
        item
        for item in events["validation_events"]
        if item.get("symbol") == removal["symbol"]
        and item.get("effective_date") == removal["effective_date"]
    ]
    out_of_range_rows = connection.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE trade_date > DATE '2021-12-31'",
        [str(daily)],
    ).fetchone()[0]
    record(
        "C-STATE-002",
        len(matching_removals) == 1
        and matching_removals[0]["authorization"]
        == "OUT_OF_RANGE_REMOVAL_POSITIVE_CONTROL_ONLY"
        and matching_removals[0]["source_document_sha256"]
        == removal["source_document_sha256"]
        and out_of_range_rows == 0,
        {"validation_event_count": len(matching_removals), "out_of_range_rows": out_of_range_rows},
    )

    unsafe_rows = connection.execute(
        "SELECT count(*) FROM read_parquet(?) WHERE earliest_safe_use_date IS NULL OR earliest_safe_use_date <= trade_date",
        [str(daily)],
    ).fetchone()[0]
    invalid_official_timing = sum(
        str(item["publication_date"]) > str(item["effective_date"])
        for item in events["risk_warning_events"]
    )
    record(
        "C-KNOWN-AT-001",
        unsafe_rows == 0 and invalid_official_timing == 0,
        {"unsafe_combined_rows": unsafe_rows, "invalid_official_event_timing": invalid_official_timing},
    )

    suspension = case(spec, "C-CASE-FULL-SESSION-SUSPENSION")
    suspension_dates = [
        row[0].strftime("%Y%m%d")
        for row in connection.execute(
            """
            SELECT trade_date FROM read_parquet(?)
            WHERE symbol=? AND full_day_suspended
              AND trade_date BETWEEN ? AND ? ORDER BY trade_date
            """,
            [str(daily), suspension["symbol"], *suspension["date_range"]],
        ).fetchall()
    ]
    record(
        "C-SUSPENSION-001",
        len(suspension_dates) == suspension["expected_count"]
        and sha256_lines(suspension_dates) == suspension["expected_sorted_yyyymmdd_sha256"]
        and manifest["suspension_crosscheck"]["status"] == "PASS_93_OF_93",
        {"count": len(suspension_dates), "sorted_yyyymmdd_sha256": sha256_lines(suspension_dates)},
    )

    warmup = case(spec, "C-CASE-WARMUP-SUSPENSION-NULLS")
    placeholders = ",".join("?" for _ in warmup["dates"])
    warmup_state = connection.execute(
        f"""
        SELECT trade_date, trade_status, full_day_suspended, volume_raw, amount_raw
        FROM read_parquet(?) WHERE symbol=? AND CAST(trade_date AS VARCHAR) IN ({placeholders})
        ORDER BY trade_date
        """,
        [str(daily), warmup["symbol"], *warmup["dates"]],
    ).fetchall()
    qd001_inventory = json.loads(
        resolve_path(bindings["qd001_manifest"]["path"]).read_text(encoding="utf-8")
    )
    qd001_record = next(
        item for item in qd001_inventory["files"] if item["path"] == "300372.none.parquet"
    )
    qd001_file = Path(qd001_inventory["root"]) / qd001_record["path"]
    qd001_rows = connection.execute(
        f"""
        SELECT CAST(trade_date AS DATE), open, high, low, close, volume, amount
        FROM read_parquet(?) WHERE CAST(trade_date AS VARCHAR) IN ({placeholders})
        ORDER BY trade_date
        """.replace("CAST(trade_date AS VARCHAR)", "CAST(CAST(trade_date AS DATE) AS VARCHAR)"),
        [str(qd001_file), *warmup["dates"]],
    ).fetchall()
    expected_state_tail = (
        warmup["expected_trade_status"],
        warmup["expected_full_day_suspended"],
        warmup["expected_volume_raw"],
        warmup["expected_amount_raw"],
    )
    record(
        "C-WARMUP-001",
        sha256_file(qd001_file) == qd001_record["sha256"]
        and len(warmup_state) == len(warmup["dates"])
        and all(row[1:] == expected_state_tail for row in warmup_state)
        and len(qd001_rows) == len(warmup["dates"])
        and all(row[-2:] == (None, None) for row in qd001_rows),
        {
            "state_rows": len(warmup_state),
            "qd001_rows": len(qd001_rows),
            "qd001_volume_amount_null_rows": sum(row[-2:] == (None, None) for row in qd001_rows),
            "raw_ohlc_preserved_but_not_tradable": True,
        },
    )

    corporate = case(spec, "C-CASE-CORPORATE-ACTION-BOUNDARY")
    distribution_path = resolve_path(bindings["qd010_distributions"]["path"])
    event_row = connection.execute(
        """
        SELECT symbol, known_at, effective_date, event_type, share_multiplier,
               cash_per_share_gross, rights_subscription_ratio, event_id
        FROM read_parquet(?) WHERE event_id=?
        """,
        [str(distribution_path), corporate["event_id"]],
    ).fetchone()
    if event_row is None:
        raise GateCError("frozen corporate-action event is missing")
    real_event = {
        "symbol": f"{event_row[0]}.SZ",
        "known_at": event_row[1].date(),
        "effective_date": event_row[2].date(),
        "event_type": event_row[3],
        "share_multiplier": event_row[4],
        "cash_per_share_gross": event_row[5],
        "rights_subscription_ratio": event_row[6],
        "event_id": event_row[7],
    }
    corporate_fail_closed = [
        expect_error(
            "CA_BEFORE_EFFECTIVE_DATE",
            lambda: validate_event(real_event, date(2018, 5, 15)),
            CausalCorporateActionError,
            "future corporate-action fact",
        )
    ]
    visible = validate_event(real_event, date(2018, 5, 16))
    rebased_price, rebased_volume = rebase_history([10.0], [100.0], real_event, date(2018, 5, 16))
    cy006_boundary_rows = connection.execute(
        """
        SELECT trade_date, close, corporate_action_count, corporate_action_ids,
               corporate_action_available_date, cash_per_share, share_multiplier,
               corporate_action_valid, corporate_action_blocking
        FROM read_parquet(?) WHERE symbol=?
          AND trade_date IN (DATE '2018-05-15', DATE '2018-05-16', DATE '2018-05-17')
        ORDER BY trade_date
        """,
        [[str(path) for path in cy006_paths], corporate["physical_source_symbol"]],
    ).fetchall()
    boundary_event_rows = [row for row in cy006_boundary_rows if row[2] == 1]
    record(
        "C-CA-001",
        visible["known_at"] == date.fromisoformat(corporate["known_at"])
        and visible["effective_date"] == date.fromisoformat(corporate["effective_date"])
        and len(boundary_event_rows) == 1
        and boundary_event_rows[0][0] == date.fromisoformat(corporate["effective_date"])
        and pd.Timestamp(boundary_event_rows[0][4]).date() <= boundary_event_rows[0][0],
        {"visible_event": visible, "cy006_boundary_rows": cy006_boundary_rows},
    )
    same_day_raw_close = float(boundary_event_rows[0][1])
    synthetic_sequence = [*rebased_price, same_day_raw_close]
    record(
        "C-CA-002",
        rebased_price == [9.95]
        and rebased_volume == [100.0]
        and synthetic_sequence[-1] == same_day_raw_close
        and len(cy006_boundary_rows) == 3
        and [row[2] for row in cy006_boundary_rows] == [0, 1, 0],
        {
            "rebased_prior_price": rebased_price,
            "rebased_prior_volume": rebased_volume,
            "same_day_raw_close": same_day_raw_close,
        },
    )

    rights = case(spec, "C-CASE-UNSUPPORTED-RIGHTS")
    rights_path = resolve_path(bindings["qd010_rights"]["path"])
    rights_row = connection.execute(
        """
        SELECT symbol, known_at, effective_date, rights_subscription_ratio,
               rights_subscription_price, event_id
        FROM read_parquet(?) WHERE event_id=?
        """,
        [str(rights_path), rights["event_id"]],
    ).fetchone()
    if rights_row is None:
        raise GateCError("frozen unsupported rights event is missing")
    rights_event = {
        "symbol": f"{rights_row[0]}.SZ",
        "known_at": rights_row[1].date(),
        "effective_date": rights_row[2].date(),
        "event_type": "rights",
        "share_multiplier": 1.0,
        "cash_per_share_gross": 0.0,
        "rights_subscription_ratio": rights_row[3],
        "event_id": rights_row[5],
    }
    corporate_fail_closed.extend(
        [
            expect_error(
                "CA_RIGHTS_PARTICIPATION",
                lambda: validate_event(rights_event, date(2018, 2, 9)),
                CausalCorporateActionError,
                "rights participation is execution-unresolved",
            ),
            expect_error(
                "CA_DUPLICATE_EVENT",
                lambda: visible_events([real_event, real_event], date(2018, 5, 16)),
                CausalCorporateActionError,
                "duplicate corporate-action identity",
            ),
            expect_error(
                "CA_UNSUPPORTED_EVENT",
                lambda: validate_event({**real_event, "event_type": "merger"}, date(2018, 5, 16)),
                CausalCorporateActionError,
                "unknown event type",
            ),
        ]
    )
    record(
        "C-CA-003",
        len(corporate_fail_closed) == 4
        and all(item["status"] == "PASS_FAIL_CLOSED" for item in corporate_fail_closed),
        corporate_fail_closed,
    )

    documents = official_document_check(spec)
    record(
        "C-AUTH-001",
        authorization.authorization_id == spec["authorization"]["authorization_id"]
        and authorization.record_level_available_at_available is False
        and len(auth_checks) == 5
        and all(item["status"] == "PASS_FAIL_CLOSED" for item in auth_checks)
        and documents["status"] == "PASS",
        {"authorization_checks": auth_checks, "official_documents": documents},
    )
    connection.close()

    mismatch_count = sum(item["status"] != "PASS" for item in checks)
    required_ids = {
        item["invariant_id"]
        for item in spec["frozen_invariants"]
        if item["invariant_id"] != "C-DETERMINISM-001"
    }
    executed_ids = {item["invariant_id"] for item in checks}
    missing_invariants = sorted(required_ids - executed_ids)
    if missing_invariants:
        mismatch_count += len(missing_invariants)
    result: dict[str, Any] = {
        "authorization": {
            "authorization_id": authorization.authorization_id,
            "class": spec["authorization"]["authorization_class"],
            "record_level_available_at_available": False,
            "revision_history_complete": False,
            "strict_pit_a": False,
        },
        "counts": {
            "authorization_violation_count": 0,
            "determinism_mismatch_count": 0,
            "hash_failure_count": 0,
            "required_invariant_mismatch_count": mismatch_count,
            "required_unknown_state_count": 0,
        },
        "execution_firewall": spec["execution_firewall"],
        "gate_c_result": "PENDING_DETERMINISM" if mismatch_count == 0 else "FAIL",
        "gate_c_repair_count": GATE_C_REPAIR_COUNT,
        "input_hashes_verified": len(actual_hashes),
        "invariant_checks": checks,
        "missing_invariants": missing_invariants,
        "official_documents": documents,
        "pilot_scope": spec["pilot_scope"],
        "spec_commit": spec_commit(),
        "spec_id": spec["spec_id"],
        "spec_sha256": sha256_file(SPEC),
        "runner_sha256": sha256_file(CONSUMER),
    }
    return result


def finalize_determinism(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    matched = canonical_bytes(first) == canonical_bytes(second)
    first["invariant_checks"].append(
        {
            "invariant_id": "C-DETERMINISM-001",
            "status": "PASS" if matched else "FAIL",
            "details": {
                "canonical_result": "PASS_BYTE_IDENTICAL" if matched else "FAIL_MISMATCH",
                "rebuilds": 2,
            },
        }
    )
    first["counts"]["determinism_mismatch_count"] = 0 if matched else 1
    first["gate_c_result"] = (
        "PASS"
        if matched
        and all(value == 0 for value in first["counts"].values())
        and not first["missing_invariants"]
        else "FAIL"
    )
    return first


def write_report(result: dict[str, Any]) -> None:
    lines = [
        "# ChinNext V1 — Gate C bounded correctness pilot",
        "",
        "> Input/materialization correctness only. No strategy signal, trade, NAV, or performance was generated.",
        "",
        f"- GATE_C: `{result['gate_c_result']}`",
        f"- SPEC_ID: `{result['spec_id']}`",
        f"- SPEC_SHA256: `{result['spec_sha256']}`",
        f"- SPEC_COMMIT: `{result['spec_commit']}`",
        f"- GATE_C_REPAIR_COUNT: `{result['gate_c_repair_count']}`",
        f"- AUTHORIZATION_CLASS: `{result['authorization']['class']}`",
        "- STRICT_PIT_A: `NO`",
        "- REVISION_HISTORY_COMPLETE: `NO`",
        f"- INPUT_HASHES_VERIFIED: `{result['input_hashes_verified']}`",
        "",
        "## Frozen invariant results",
        "",
        "| Invariant | Status |",
        "|---|---|",
    ]
    lines.extend(
        f"| {item['invariant_id']} | {item['status']} |" for item in result["invariant_checks"]
    )
    lines.extend(
        [
            "",
            "## Strict pass counts",
            "",
            *[f"- {key.upper()}: `{value}`" for key, value in result["counts"].items()],
            "",
            "The 302132.SZ physical-source projection is normalized to the official historical identity 300114.SZ for the bounded target period. The mapping is derived from the hash-bound security master and official alias event; it is not a source-code hardcode. Rights participation and all tested invalid authorization/event paths fail closed.",
            "",
        ]
    )
    atomic_write(REPORT, "\n".join(lines).encode("utf-8"))


def main() -> int:
    first = build_result()
    second = build_result()
    first = finalize_determinism(first, second)
    first_bytes = canonical_bytes(first)
    atomic_write(RESULT, first_bytes)
    write_report(first)
    print(
        json.dumps(
            {
                "gate_c": first["gate_c_result"],
                "spec_commit": first["spec_commit"],
                **first["counts"],
            },
            sort_keys=True,
        )
    )
    return 0 if first["gate_c_result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
