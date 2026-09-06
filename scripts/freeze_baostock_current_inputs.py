#!/usr/bin/env python3
"""Audit and freeze bounded BaoStock market or industry inputs.

The freezer is intentionally separate from registry admission.  It copies only
the collector's immutable final inventory, produces a strict quality report,
and writes an asset manifest whose hash can then be reviewed and registered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _copy_market_inventory(source: Path, output: Path) -> dict[str, Any]:
    source_manifest_path = source / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("status") != "PASS":
        raise ValueError("market collector manifest did not pass")
    inventory = source_manifest.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("market collector inventory is empty")
    for item in inventory:
        relative = Path(str(item["path"]))
        source_path = source / relative
        if (
            not source_path.is_file()
            or source_path.stat().st_size != int(item["bytes"])
            or _sha256(source_path) != item["sha256"]
        ):
            raise ValueError(f"collector inventory mismatch: {source_path}")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
    shutil.copy2(source_manifest_path, output / "manifest.json")
    return source_manifest


def _market_quality(root: Path, start: date, end: date) -> dict[str, Any]:
    daily = root / "raw_daily.parquet"
    minute = root / "raw_5m.parquet"
    connection = duckdb.connect()
    try:
        row = connection.execute(
            """
            WITH d AS (
              SELECT code, CAST(date AS DATE) trade_date,
                     TRY_CAST(tradestatus AS INTEGER) = 1 AS active,
                     TRY_CAST(volume AS DOUBLE) AS daily_volume,
                     TRY_CAST(amount AS DOUBLE) AS daily_amount
              FROM read_parquet(?)
              WHERE CAST(date AS DATE) BETWEEN ? AND ?
            ), m AS (
              SELECT code, CAST(date AS DATE) trade_date, COUNT(*) bars,
                     MIN(SUBSTR(time, 9, 6)) first_bar,
                     MAX(SUBSTR(time, 9, 6)) last_bar,
                     SUM(TRY_CAST(volume AS DOUBLE)) minute_volume,
                     SUM(TRY_CAST(amount AS DOUBLE)) minute_amount,
                     COUNT(*) FILTER (WHERE TRY_CAST(open AS DOUBLE) <= 0
                                       OR TRY_CAST(high AS DOUBLE) <= 0
                                       OR TRY_CAST(low AS DOUBLE) <= 0
                                       OR TRY_CAST(close AS DOUBLE) <= 0) zero_ohlc
              FROM read_parquet(?)
              WHERE CAST(date AS DATE) BETWEEN ? AND ?
              GROUP BY code, CAST(date AS DATE)
            ), q AS (
              SELECT d.*, m.* EXCLUDE(code, trade_date),
                     COALESCE(ABS(m.minute_volume-d.daily_volume)
                       / NULLIF(ABS(d.daily_volume),0), 0) volume_error,
                     COALESCE(ABS(m.minute_amount-d.daily_amount)
                       / NULLIF(ABS(d.daily_amount),0), 0) amount_error,
                     (m.bars=48 AND m.first_bar='093500' AND m.last_bar='150000')
                       AS complete_session
              FROM d LEFT JOIN m USING(code, trade_date)
            )
            SELECT COUNT(*), COUNT(*) FILTER (WHERE active),
                   COUNT(*) FILTER (WHERE NOT active),
                   COUNT(*) FILTER (WHERE active AND complete_session),
                   COUNT(*) FILTER (WHERE active AND volume_error > 0.001),
                   COUNT(*) FILTER (WHERE active AND amount_error > 0.001),
                   COUNT(*) FILTER (WHERE active AND COALESCE(zero_ohlc,0) > 0),
                   COUNT(*) FILTER (WHERE active AND complete_session
                     AND volume_error <= 0.001 AND amount_error <= 0.001
                     AND COALESCE(zero_ohlc,0)=0),
                   MAX(volume_error), MAX(amount_error),
                   COUNT(*) FILTER (WHERE active AND bars IS NULL)
            FROM q
            """,
            [str(daily), start, end, str(minute), start, end],
        ).fetchone()
        daily_stats = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT code), "
            "COUNT(*)-COUNT(DISTINCT (code,date)) FROM read_parquet(?)",
            [str(daily)],
        ).fetchone()
        minute_stats = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT code), COUNT(DISTINCT (code,date)), "
            "COUNT(*) FILTER (WHERE n=48), COUNT(*)-COUNT(DISTINCT (code,date,time)), "
            "MIN(SUBSTR(time,9,6)), MAX(SUBSTR(time,9,6)), SUM(zero_ohlc) FROM ("
            "SELECT *, COUNT(*) OVER(PARTITION BY code,date) n, "
            "CASE WHEN TRY_CAST(open AS DOUBLE)<=0 OR TRY_CAST(high AS DOUBLE)<=0 "
            "OR TRY_CAST(low AS DOUBLE)<=0 OR TRY_CAST(close AS DOUBLE)<=0 "
            "THEN 1 ELSE 0 END zero_ohlc FROM read_parquet(?))",
            [str(minute)],
        ).fetchone()
    finally:
        connection.close()
    assert row is not None and daily_stats is not None and minute_stats is not None
    active = int(row[1])
    fully_valid = int(row[7])
    ratio = fully_valid / active if active else 0.0
    index_files = sorted((root / "index_daily").glob("*.parquet"))
    index_rows = []
    connection = duckdb.connect()
    try:
        for path in index_files:
            index_rows.append(
                int(connection.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0])
            )
    finally:
        connection.close()
    trade_dates = len(json.loads((root / "manifest.json").read_text())["coverage"]["trade_dates"])
    checks = {
        "daily_unique": int(daily_stats[2]) == 0,
        "minute_unique": int(minute_stats[4]) == 0,
        "active_complete_5m_session_ratio_at_least_95pct": (
            int(row[3]) / active >= 0.95 if active else False
        ),
        "active_volume_reconciles_at_0_1pct": int(row[4]) == 0,
        "active_amount_reconciles_at_0_1pct": int(row[5]) == 0,
        "active_fully_valid_ratio_at_least_95pct": ratio >= 0.95,
        "six_indices_complete": len(index_files) == 6
        and all(value == trade_dates for value in index_rows),
    }
    return {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "gate": f"BAOSTOCK_MARKET_DELTA_{start:%Y%m%d}_{end:%Y%m%d}_V1",
        "scope": {"start": start, "end": end, "trade_dates": trade_dates},
        "daily": {
            "rows": int(daily_stats[0]),
            "symbols": int(daily_stats[1]),
            "active_symbol_days": active,
            "suspended_symbol_days": int(row[2]),
            "duplicate_symbol_date_keys": int(daily_stats[2]),
        },
        "minute_5m": {
            "rows": int(minute_stats[0]),
            "symbols": int(minute_stats[1]),
            "symbol_days": int(minute_stats[2]),
            "complete_48_bar_symbol_days": int(minute_stats[3] // 48),
            "duplicate_symbol_date_time_keys": int(minute_stats[4]),
            "first_bar_time": minute_stats[5],
            "last_bar_time": minute_stats[6],
            "zero_ohlc_rows": int(minute_stats[7] or 0),
        },
        "cross_table": {
            "active_symbol_days_with_complete_session": int(row[3]),
            "active_volume_reconciliation_failures_at_0_1pct": int(row[4]),
            "active_amount_reconciliation_failures_at_0_1pct": int(row[5]),
            "maximum_volume_relative_error": row[8],
            "maximum_amount_relative_error": row[9],
            "active_missing_minute_symbol_days": int(row[10]),
        },
        "row_quality": {
            "active_fully_valid_symbol_days": fully_valid,
            "active_fully_valid_ratio": ratio,
            "active_zero_ohlc_symbol_days": int(row[6]),
        },
        "checks": checks,
        "decision": (
            "PASS_FOR_REGISTRATION_AND_CONDITIONAL_DERIVATION"
            if all(checks.values())
            else "FAIL_CLOSED"
        ),
    }


def _freeze_market(args: argparse.Namespace, output: Path) -> dict[str, Any]:
    source_manifest = _copy_market_inventory(args.source, output)
    quality = _market_quality(output, args.start, args.end)
    _write_json(output / "quality_report.json", quality)
    if quality["status"] != "PASS":
        raise RuntimeError("market quality gate failed closed")
    source_sha = _sha256(output / "manifest.json")
    hashes = {
        "acquisition_manifest_sha256": source_sha,
        "quality_report_sha256": _sha256(output / "quality_report.json"),
        "raw_daily_sha256": _sha256(output / "raw_daily.parquet"),
        "raw_5m_sha256": _sha256(output / "raw_5m.parquet"),
    }
    source_kind = str(source_manifest.get("kind", "baostock_unadjusted_market_delta"))
    is_sina = source_kind == "sina_unadjusted_market_delta"
    snapshot = ("sina-market-delta-" if is_sina else "baostock-market-delta-") + hashlib.sha256(
        _canonical(hashes).encode()
    ).hexdigest()
    source_coverage = source_manifest["coverage"]
    return {
        "schema_version": 1,
        "status": "PASS",
        "asset_id": args.asset_id,
        "kind": source_kind,
        "pit_grade": "B_RESEARCH_ONLY",
        "snapshot_id": snapshot,
        "location": str(output),
        "captured_at": source_manifest["created_at"],
        "coverage": {
            "start": args.start,
            "end": args.end,
            "trade_dates": len(source_coverage["trade_dates"]),
            "symbols_requested": source_coverage["symbols_requested"],
            "symbols_succeeded": source_coverage["symbols_succeeded"],
            "symbol_coverage": source_coverage["symbol_coverage"],
            "daily_rows": quality["daily"]["rows"],
            "daily_symbols": quality["daily"]["symbols"],
            "minute_5m_rows": quality["minute_5m"]["rows"],
            "minute_5m_symbols": quality["minute_5m"]["symbols"],
            "active_symbol_days": quality["daily"]["active_symbol_days"],
            "active_fully_valid_symbol_days": quality["row_quality"]["active_fully_valid_symbol_days"],
            "active_fully_valid_ratio": quality["row_quality"]["active_fully_valid_ratio"],
            "indices": 6,
        },
        "schema_and_units": {
            "price_basis": "unadjusted",
            "price": "CNY per share",
            "volume": "shares",
            "amount": "CNY",
            "daily_availability": "after the completed trade date close",
            "minute_resolution": "native 5m",
            "minute_availability": "actual completed BaoStock bar timestamp",
        },
        "hashes": hashes,
        "quality_evidence": quality,
        "cross_provider_evidence": source_manifest.get("cross_provider_evidence"),
        "lineage": {
            "source": (
                "Sina native-5m K-line responses with BaoStock date-effective "
                "universe/index snapshots"
                if is_sina
                else "BaoStock 00.9.30 query_history_k_data_plus/query_all_stock/query_trade_dates"
            ),
            "immutable_acquisition_manifest": "manifest.json",
            "quality_report": "quality_report.json",
            "collector": str(
                (
                    Path(__file__).parent
                    / (
                        "fetch_sina_market_delta.py"
                        if is_sina
                        else "fetch_baostock_market_delta.py"
                    )
                ).resolve()
            ),
        },
        "allowed_uses": [
            f"conditional causal normalization for {args.start} through {args.end}",
            "daily market/trading-state and native 5-minute volume-at-price derivation",
        ],
        "blocked_uses": [
            "strict PIT-A, live trading, sizing or performance claims",
            "fabricating 1-minute rows from native 5-minute responses",
            "use before registry admission or from a failed row",
        ],
        "activation_gates": [
            "asset, acquisition and quality manifest hashes remain exact",
            "record-level available_at and snapshot_id are attached during normalization",
            "minute data remains at its real 5-minute resolution",
            "industry, float, corporate action and cross-table joins fail closed",
            "active hard-valid coverage remains at least 95 percent",
        ],
    }


def _freeze_industry(args: argparse.Namespace, output: Path) -> dict[str, Any]:
    data_source = args.source / "industry_daily.parquet"
    manifest_source = args.source / "industry_daily.manifest.json"
    payload = json.loads(manifest_source.read_text(encoding="utf-8"))
    if payload.get("status") != "pass" or payload.get("failures"):
        raise ValueError("industry collector did not pass without request failures")
    shutil.copy2(data_source, output / data_source.name)
    shutil.copy2(manifest_source, output / manifest_source.name)
    connection = duckdb.connect()
    try:
        row = connection.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT symbol), COUNT(DISTINCT decision_date),
                   COUNT(*)-COUNT(DISTINCT (symbol,decision_date)),
                   COUNT(*) FILTER (WHERE CAST(source_update_date AS DATE)
                                          >= CAST(decision_date AS DATE)),
                   MIN(CAST(decision_date AS DATE)), MAX(CAST(decision_date AS DATE))
            FROM read_parquet(?)
            """,
            [str(output / data_source.name)],
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    checks = {
        "duplicate_symbol_decision_date_keys": int(row[3]) == 0,
        "source_update_strictly_before_decision": int(row[4]) == 0,
        "request_failures": len(payload["failures"]) == 0,
    }
    quality = {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "gate": f"BAOSTOCK_INDUSTRY_{args.start:%Y%m%d}_{args.end:%Y%m%d}_V1",
        "coverage": {
            "requested_start": args.start,
            "requested_end": args.end,
            "requested_trade_dates": len(payload["requested_dates"]),
            "materialized_rows": int(row[0]),
            "materialized_dates": int(row[2]),
            "symbols": int(row[1]),
            "materialized_start": row[5],
            "materialized_end": row[6],
            "date_policy": "source_update_date < decision_date",
        },
        "checks": checks,
        "decision": (
            "PASS_FOR_REGISTRATION_AND_CONDITIONAL_ASOF_JOIN"
            if all(checks.values())
            else "FAIL_CLOSED"
        ),
    }
    _write_json(output / "quality_report.json", quality)
    if quality["status"] != "PASS":
        raise RuntimeError("industry quality gate failed closed")
    hashes = {
        "data_sha256": _sha256(output / data_source.name),
        "source_manifest_sha256": _sha256(output / manifest_source.name),
        "quality_report_sha256": _sha256(output / "quality_report.json"),
    }
    snapshot = "baostock-industry-" + hashlib.sha256(
        _canonical(hashes).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "status": "PASS",
        "asset_id": args.asset_id,
        "kind": "date_effective_industry_supplement",
        "pit_grade": "B_RESEARCH_ONLY",
        "snapshot_id": snapshot,
        "location": str(output),
        "captured_at": payload["captured_at"],
        "coverage": quality["coverage"],
        "schema_and_units": "symbol, decision_date, CSRC industry, source_update_date, capture available_at, snapshot_id and exact response hash",
        "hashes": hashes,
        "quality_evidence": quality,
        "lineage": {
            "source": "BaoStock query_stock_industry(date=decision_date)",
            "record_available_at": True,
            "record_snapshot_id": True,
            "immutable_source_manifest": manifest_source.name,
            "quality_report": "quality_report.json",
            "collector": str((Path(__file__).parent / "supplement_missing_industry_baostock.py").resolve()),
        },
        "allowed_uses": [
            f"conditional PIT-B industry as-of joins for {args.start} through {args.end}",
        ],
        "blocked_uses": [
            "same-day update use or current-membership backfill before source_update_date",
            "strict PIT-A, live trading or standalone alpha claims",
        ],
        "activation_gates": [
            "asset, source and quality manifest hashes remain exact",
            "source_update_date remains strictly before decision_date",
            "missing dates use only an earlier causal row and never a later snapshot",
            "UNKNOWN or missing membership fails closed",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("market", "industry"), required=True)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.end < args.start:
        raise ValueError("end must not precede start")
    args.source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True)
    try:
        manifest = (
            _freeze_market(args, output)
            if args.kind == "market"
            else _freeze_industry(args, output)
        )
        manifest["created_at"] = datetime.now(UTC).isoformat()
        manifest_path = output / "asset_manifest.json"
        _write_json(manifest_path, manifest)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "asset_manifest": str(manifest_path),
                    "asset_manifest_sha256": _sha256(manifest_path),
                    "snapshot_id": manifest["snapshot_id"],
                    "coverage": manifest["coverage"],
                },
                ensure_ascii=False,
                default=str,
            )
        )
        return 0
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
