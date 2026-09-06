#!/usr/bin/env python3
"""Independently validate and seal an exchange-announcement staging capture.

This validator deliberately does not authorize the data for research or
backtests.  It proves only that the current SSE/SZSE metadata snapshot is a
complete, internally conserved copy of the query responses recorded by the
collector.  The source is still limited PIT-B: historical revision history is
incomplete and announcement documents have not been captured.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import stat
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
collector = importlib.import_module(
    "research.market_behavior_os_v2.scripts.fetch_exchange_issuer_announcements_v1"
)

VALIDATOR_ID = "CY-EXCHANGE-ISSUER-ANNOUNCEMENT-SEALER-V1"
AUDIT_VALIDATION_NAME = "audit_validation.json"
ASSET_MANIFEST_NAME = "asset_manifest.json"
SNAPSHOT_INVENTORY_COLUMNS = [
    "query_id",
    "page",
    "raw_body_path",
    "raw_body_sha256",
    "record_count",
]


class SealError(RuntimeError):
    """Fail closed when any captured byte, record, or lineage field diverges."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SealError(message)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SealError(f"invalid {label}: {path}") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def _strict_bool(value: Any, expected: bool, label: str) -> None:
    _require(isinstance(value, bool) and value is expected, f"{label} must be {expected}")


def _integer(value: Any, label: str) -> int:
    _require(not isinstance(value, bool) and not pd.isna(value), f"{label} is missing")
    try:
        result = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SealError(f"{label} is not an integer: {value!r}") from exc
    _require(math.isfinite(numeric) and numeric == result, f"{label} is not an integer")
    return result


def _optional_integer(value: Any, label: str) -> int | None:
    if value is None or pd.isna(value):
        return None
    return _integer(value, label)


def _string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    _require(isinstance(value, str), f"{label} must be a string")
    _require(allow_empty or bool(value), f"{label} must not be empty")
    return value


def _parse_json_column(value: Any, label: str) -> Any:
    text = _string(value, label)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SealError(f"{label} is not valid JSON") from exc
    _require(
        collector.canonical_json(parsed) == text,
        f"{label} is not in collector canonical form",
    )
    return parsed


def _safe_internal_path(root: Path, raw_value: Any, label: str) -> tuple[str, Path]:
    value = _string(raw_value, label)
    pure = PurePosixPath(value)
    _require(not pure.is_absolute(), f"{label} must be relative to the asset root")
    _require(
        value == pure.as_posix()
        and bool(pure.parts)
        and all(part not in ("", ".", "..") for part in pure.parts),
        f"{label} is not a canonical relative path: {value!r}",
    )
    path = root.joinpath(*pure.parts)
    root_resolved = root.resolve(strict=True)
    try:
        path.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise SealError(f"{label} escapes the asset root: {value!r}") from exc
    current = root
    for part in pure.parts:
        current = current / part
        _require(not current.is_symlink(), f"{label} traverses a symlink: {value!r}")
    return value, path


def _file_facts(path: Path, label: str) -> tuple[str, int]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    return collector.sha256_file(path), path.stat().st_size


def _require_exact_columns(frame: pd.DataFrame, expected: Sequence[str], label: str) -> None:
    actual = list(frame.columns)
    _require(actual == list(expected), f"{label} columns drifted: {actual}")


def _timestamp(value: Any, label: str, *, timezone_required: bool = False) -> pd.Timestamp:
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise SealError(f"invalid timestamp in {label}: {value!r}") from exc
    _require(not pd.isna(result), f"missing timestamp in {label}")
    if timezone_required:
        _require(result.tzinfo is not None, f"{label} must preserve a timezone")
    return result


def _compare_normalized_row(
    expected: Mapping[str, Any], actual: Mapping[str, Any], announcement_key: str
) -> None:
    timestamp_columns = {"published_at", "available_at", "source_query_date"}
    integer_columns = {"query_year", "query_page"}
    boolean_columns = {"revision_history_complete", "strict_pit_eligible", "hard_valid"}
    for column in collector.ANNOUNCEMENT_COLUMNS:
        left = expected[column]
        right = actual[column]
        label = f"announcement {announcement_key} column {column}"
        if column in timestamp_columns:
            same = _timestamp(left, label) == _timestamp(right, label)
        elif column in integer_columns:
            same = _integer(left, label) == _integer(right, label)
        elif column in boolean_columns:
            same = isinstance(right, bool) and right is left
        else:
            same = isinstance(right, str) and right == left
        _require(same, f"announcement row mismatch at {announcement_key}.{column}")


def _validate_normalized_time_semantics(
    normalized: Mapping[str, Any], spec: collector.QuerySpec
) -> None:
    key = normalized["announcement_key"]
    source_query_date = _timestamp(
        normalized["source_query_date"], f"{key} source_query_date"
    )
    _require(
        source_query_date == source_query_date.normalize(),
        f"source_query_date is not a normalized calendar date for {key}",
    )
    _require(
        pd.Timestamp(spec.start) <= source_query_date <= pd.Timestamp(spec.end),
        f"source_query_date lies outside query interval for {key}",
    )
    published_at = _timestamp(normalized["published_at"], f"{key} published_at")
    available_at = _timestamp(normalized["available_at"], f"{key} available_at")
    if spec.exchange == "SSE":
        _require(
            normalized["source_query_date_field"] == "SSEDATE",
            f"SSE source_query_date_field drifted for {key}",
        )
        _require(
            normalized["source_publication_field"] == "ADDDATE"
            and normalized["precision"] == "SOURCE_SECOND",
            f"SSE ADDDATE precision contract drifted for {key}",
        )
        _require(
            published_at == available_at,
            f"SSE ADDDATE must control published_at and available_at for {key}",
        )
    else:
        _require(
            normalized["source_query_date_field"] == "publishTime"
            and normalized["source_publication_field"] == "publishTime",
            f"SZSE publishTime query-date contract drifted for {key}",
        )
        _require(
            published_at.normalize() == source_query_date,
            f"SZSE source_query_date differs from publishTime date for {key}",
        )


def _validate_source_declarations(root: Path, source_manifest: Mapping[str, Any]) -> Path:
    _require(source_manifest.get("asset_id") == collector.ASSET_ID, "source asset_id drifted")
    _require(source_manifest.get("status") == "STAGING", "source status is not STAGING")
    _strict_bool(source_manifest.get("staging"), True, "source staging")
    _strict_bool(source_manifest.get("backtest_authorized"), False, "source backtest_authorized")
    _strict_bool(
        source_manifest.get("strict_archival_pit_ready"),
        False,
        "source strict_archival_pit_ready",
    )
    _strict_bool(source_manifest.get("metadata_only"), True, "source metadata_only")
    _strict_bool(source_manifest.get("documents_downloaded"), False, "source documents_downloaded")
    activation_gates = source_manifest.get("activation_gates")
    _require(isinstance(activation_gates, dict), "source activation_gates are missing")
    for key, expected in (
        ("pagination_reported_totals_equal_raw_record_appearances", True),
        ("canonical_count_equals_raw_record_appearances", True),
        ("source_query_dates_within_requested_intervals", True),
        ("SSE_ADDDATE_second_precision_validated", True),
        ("source_keys_unique_within_each_query", True),
        ("normalized_announcement_keys_unique", True),
        ("all_raw_pages_preserved_and_hashed", True),
        ("documents_captured_and_hashed", False),
        ("taxonomy_frozen", False),
        ("registry_entry_and_validator_pass", False),
        ("separate_experiment_protocol_frozen_before_outcomes", False),
    ):
        _strict_bool(activation_gates.get(key), expected, f"source activation_gates.{key}")
    location = Path(_string(source_manifest.get("location"), "source location"))
    _require(location.resolve() == root.resolve(), "source manifest location does not match root")
    universe = Path(_string(source_manifest.get("universe_source"), "source universe_source"))
    _require(universe.is_absolute(), "source universe_source must be absolute for sealing")
    _require(universe.is_file() and not universe.is_symlink(), "universe file is missing or unsafe")
    return universe


def _validate_request_shape(row: Mapping[str, Any], spec: collector.QuerySpec, page: int) -> None:
    labels = {
        "query_id": spec.query_id,
        "exchange": spec.exchange,
        "symbol": spec.symbol,
        "security_code": spec.code,
        "query_year": spec.year,
        "query_start": spec.start,
        "query_end": spec.end,
        "page": page,
        "page_size": spec.page_size,
    }
    for column, expected in labels.items():
        value = row[column]
        if isinstance(expected, int):
            value = _integer(value, f"{spec.query_id} page {page} {column}")
        _require(
            value == expected,
            f"request lineage mismatch at {spec.query_id} page {page} {column}",
        )
    params = _parse_json_column(
        row["request_params_json"], f"{spec.query_id} page {page} request_params_json"
    )
    body = _parse_json_column(
        row["request_body_json"], f"{spec.query_id} page {page} request_body_json"
    )
    headers = _parse_json_column(
        row["request_headers_json"], f"{spec.query_id} page {page} request_headers_json"
    )
    response_headers = _parse_json_column(
        row["response_headers_json"],
        f"{spec.query_id} page {page} response_headers_json",
    )
    _require(isinstance(params, dict), "request params must be an object")
    _require(isinstance(body, dict), "request body must be an object")
    _require(isinstance(headers, dict), "request headers must be an object")
    _require(isinstance(response_headers, dict), "response headers must be an object")
    if spec.exchange == "SZSE":
        cache_buster = str(params.get("random", ""))
    else:
        cache_buster = str(params.get("_", ""))
    _require(bool(cache_buster), f"missing cache buster for {spec.query_id} page {page}")
    method, url, expected_params, expected_body, expected_headers = collector.build_request(
        spec.exchange,
        spec.code,
        spec.start,
        spec.end,
        page,
        cache_buster=cache_buster,
    )
    _require(row["request_method"] == method, "request method drifted")
    _require(row["request_url"] == url, "request URL drifted")
    _require(params == (expected_params or {}), "request parameters drifted")
    _require(body == (expected_body or {}), "request body drifted")
    _require(headers == expected_headers, "request headers drifted")
    _require(_integer(row["http_status"], "http_status") == 200, "HTTP status is not 200")
    _timestamp(row["retrieved_at"], "retrieved_at", timezone_required=True)


def _validate_capture(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    source_path = root / "source_manifest.json"
    audit_path = root / "audit.json"
    announcements_path = root / "announcements.parquet"
    pages_path = root / "request_pages.parquet"
    source_manifest = _read_json_object(source_path, "source_manifest.json")
    audit = _read_json_object(audit_path, "audit.json")
    universe_path = _validate_source_declarations(root, source_manifest)
    for path, label in (
        (announcements_path, "announcements.parquet"),
        (pages_path, "request_pages.parquet"),
    ):
        _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}")
    try:
        announcements = pd.read_parquet(announcements_path)
        request_pages = pd.read_parquet(pages_path)
    except Exception as exc:
        raise SealError("unable to read capture parquet tables") from exc
    _require_exact_columns(
        announcements,
        ["snapshot_id", *collector.ANNOUNCEMENT_COLUMNS],
        "announcements.parquet",
    )
    _require_exact_columns(request_pages, collector.REQUEST_PAGE_COLUMNS, "request_pages.parquet")
    _require(not request_pages.empty, "request_pages.parquet is empty")
    _require(
        not request_pages.duplicated(["query_id", "page"]).any(),
        "duplicate query/page lineage rows",
    )

    hashes = source_manifest.get("hashes")
    _require(isinstance(hashes, dict), "source manifest hashes are missing")
    source_hash_expectations = {
        "universe_parquet": universe_path,
        "announcements_parquet": announcements_path,
        "request_pages_parquet": pages_path,
        "audit_json": audit_path,
    }
    for key, path in source_hash_expectations.items():
        actual_sha, _ = _file_facts(path, key)
        _require(hashes.get(key) == actual_sha, f"source manifest hash mismatch for {key}")

    coverage = source_manifest.get("coverage")
    _require(isinstance(coverage, dict), "source coverage is missing")
    start = collector.validate_date(_string(coverage.get("start"), "coverage start"))
    end = collector.validate_date(_string(coverage.get("end"), "coverage end"))
    _require(start <= end, "source coverage end precedes start")
    symbols = collector.load_universe(universe_path)
    expected_specs = {
        spec.query_id: spec for spec in collector.build_query_specs(symbols, start, end)
    }

    page_records = request_pages.sort_values(["query_id", "page"], kind="mergesort").to_dict(
        "records"
    )
    original_page_order = [
        (_string(row["query_id"], "query_id"), _integer(row["page"], "page"))
        for row in request_pages.to_dict("records")
    ]
    sorted_page_order = [
        (row["query_id"], _integer(row["page"], "page")) for row in page_records
    ]
    _require(original_page_order == sorted_page_order, "request page table ordering drifted")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    referenced_raw: set[str] = set()
    raw_page_rows: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, Any]] = []
    query_audit: list[dict[str, Any]] = []
    for row in page_records:
        query_id = _string(row["query_id"], "query_id")
        grouped[query_id].append(row)
    _require(
        set(grouped) == set(expected_specs),
        "captured query set does not match universe/coverage",
    )

    for query_id in sorted(expected_specs):
        spec = expected_specs[query_id]
        rows = grouped[query_id]
        page_numbers = [_integer(row["page"], f"{query_id} page") for row in rows]
        _require(
            page_numbers == list(range(1, len(rows) + 1)),
            f"non-contiguous pages for {query_id}: {page_numbers}",
        )
        first_total: int | None = None
        first_reported_pages: int | None = None
        seen_source_keys: set[str] = set()
        raw_appearance_count = 0
        for row, page in zip(rows, page_numbers, strict=True):
            _validate_request_shape(row, spec, page)
            raw_relative, raw_path = _safe_internal_path(
                root, row["raw_body_path"], f"{query_id} page {page} raw_body_path"
            )
            expected_raw_relative = (
                f"raw/{spec.exchange.lower()}/{spec.code}/{spec.year}/page_{page:04d}.json"
            )
            _require(
                raw_relative == expected_raw_relative,
                f"raw page path drifted for {query_id} page {page}",
            )
            _require(raw_relative not in referenced_raw, f"raw page reused: {raw_relative}")
            referenced_raw.add(raw_relative)
            raw_sha, raw_bytes = _file_facts(raw_path, f"raw page {raw_relative}")
            _require(row["raw_body_sha256"] == raw_sha, f"raw SHA mismatch: {raw_relative}")
            _require(
                _integer(row["raw_body_bytes"], f"{raw_relative} raw_body_bytes") == raw_bytes,
                f"raw byte count mismatch: {raw_relative}",
            )
            body = raw_path.read_bytes()
            try:
                total, reported_pages, records = collector.parse_page(spec.exchange, body)
            except collector.CaptureError as exc:
                raise SealError(f"raw page cannot be reparsed: {raw_relative}") from exc
            row_total = _integer(row["reported_total"], f"{raw_relative} reported_total")
            row_reported_pages = _optional_integer(
                row["reported_page_count"], f"{raw_relative} reported_page_count"
            )
            _require(total == row_total, f"reported total drift at {raw_relative}")
            _require(
                reported_pages == row_reported_pages,
                f"reported page count drift at {raw_relative}",
            )
            _require(
                len(records) == _integer(row["record_count"], f"{raw_relative} record_count"),
                f"record count drift at {raw_relative}",
            )
            _require(len(records) <= spec.page_size, f"oversized raw page: {raw_relative}")
            if first_total is None:
                first_total = total
                first_reported_pages = reported_pages
            _require(total == first_total, f"reported total changes within {query_id}")
            _require(
                reported_pages == first_reported_pages,
                f"reported page count changes within {query_id}",
            )
            for record in records:
                try:
                    key = collector.source_record_key(spec.exchange, record)
                    normalized = collector.normalize_record(
                        spec,
                        record,
                        page=page,
                        raw_body_path=raw_relative,
                        raw_body_sha256=raw_sha,
                        retrieved_at=_string(row["retrieved_at"], "retrieved_at"),
                    )
                except collector.CaptureError as exc:
                    raise SealError(f"raw record normalization failed in {raw_relative}") from exc
                _validate_normalized_time_semantics(normalized, spec)
                _require(
                    key not in seen_source_keys,
                    f"duplicate source key within {query_id}: {key}",
                )
                seen_source_keys.add(key)
                normalized_rows.append(normalized)
            raw_appearance_count += len(records)
            raw_page_rows.append(
                {
                    "query_id": query_id,
                    "page": page,
                    "path": raw_relative,
                    "sha256": raw_sha,
                    "bytes": raw_bytes,
                }
            )
        _require(first_total is not None, f"query has no page: {query_id}")
        expected_page_count = max(1, collector.expected_pages(first_total, spec.page_size))
        _require(len(rows) == expected_page_count, f"page count does not conserve for {query_id}")
        if first_reported_pages is not None:
            allowed = {expected_page_count} if first_total else {0, 1}
            _require(
                first_reported_pages in allowed,
                f"source-reported page count is invalid for {query_id}",
            )
        _require(
            raw_appearance_count == first_total == len(seen_source_keys),
            f"raw-record conservation failed for {query_id}",
        )
        query_audit.append(
            {
                "query_id": query_id,
                "exchange": spec.exchange,
                "symbol": spec.symbol,
                "start": spec.start,
                "end": spec.end,
                "reported_total": first_total,
                "captured_raw_record_appearances": raw_appearance_count,
                "unique_source_keys": len(seen_source_keys),
                "canonical_rows": raw_appearance_count,
                "pages": len(rows),
                "raw_appearances_conserve": True,
            }
        )

    raw_root = root / "raw"
    _require(raw_root.is_dir() and not raw_root.is_symlink(), "raw directory is missing or unsafe")
    actual_raw: set[str] = set()
    for candidate in raw_root.rglob("*"):
        _require(not candidate.is_symlink(), f"symlink found under raw/: {candidate}")
        if candidate.is_file():
            actual_raw.add(candidate.relative_to(root).as_posix())
    missing_raw = sorted(referenced_raw - actual_raw)
    extra_raw = sorted(actual_raw - referenced_raw)
    _require(not missing_raw, f"missing raw pages: {missing_raw[:10]}")
    _require(not extra_raw, f"extra raw pages: {extra_raw[:10]}")

    _require(
        not announcements.duplicated("announcement_key").any(),
        "duplicate normalized announcement keys",
    )
    _require(
        len(announcements) == len(normalized_rows),
        "announcement table record count differs from reparsed raw records",
    )
    actual_by_key = {
        _string(row["announcement_key"], "announcement_key"): row
        for row in announcements.to_dict("records")
    }
    expected_by_key = {row["announcement_key"]: row for row in normalized_rows}
    _require(
        len(expected_by_key) == len(normalized_rows),
        "duplicate normalized keys produced from raw pages",
    )
    _require(
        set(actual_by_key) == set(expected_by_key),
        "announcement identities differ between raw pages and table",
    )
    for key in sorted(expected_by_key):
        _compare_normalized_row(expected_by_key[key], actual_by_key[key], key)
    expected_order = (
        pd.DataFrame(normalized_rows, columns=collector.ANNOUNCEMENT_COLUMNS)
        .sort_values(["available_at", "symbol", "announcement_id"], kind="mergesort")
        .announcement_key.tolist()
        if normalized_rows
        else []
    )
    _require(
        announcements.announcement_key.tolist() == expected_order,
        "announcement table ordering drifted",
    )

    inventory_frame = request_pages.sort_values(["query_id", "page"], kind="mergesort")[
        SNAPSHOT_INVENTORY_COLUMNS
    ]
    snapshot_inventory = inventory_frame.to_dict("records")
    inventory_digest = collector.sha256_bytes(
        collector.canonical_json(snapshot_inventory).encode("utf-8")
    )
    snapshot_id = f"exchange-announcement-{inventory_digest}"
    _require(
        source_manifest.get("snapshot_id") == snapshot_id,
        "source manifest snapshot_id does not match raw-page inventory",
    )
    _require(
        hashes.get("raw_page_inventory_sha256") == inventory_digest,
        "source raw-page inventory digest drifted",
    )
    _require(
        _integer(source_manifest.get("raw_page_files"), "source raw_page_files")
        == len(referenced_raw),
        "source raw_page_files count drifted",
    )
    raw_record_appearances = len(normalized_rows)
    source_record_counts = source_manifest.get("record_counts")
    _require(isinstance(source_record_counts, dict), "source record_counts are missing")
    expected_source_record_counts = {
        "reported_raw_record_appearances": raw_record_appearances,
        "captured_raw_record_appearances": raw_record_appearances,
        "canonical_announcements": len(normalized_rows),
    }
    for key, expected in expected_source_record_counts.items():
        _require(
            _integer(source_record_counts.get(key), f"source record_counts.{key}") == expected,
            f"source record_counts drifted: {key}",
        )
    source_field_semantics = source_manifest.get("source_field_semantics")
    _require(isinstance(source_field_semantics, dict), "source field semantics are missing")
    _require(
        isinstance(source_field_semantics.get("SSE"), dict)
        and isinstance(source_field_semantics.get("SZSE"), dict),
        "source field semantics must declare SSE and SZSE",
    )
    if len(announcements):
        _require(
            announcements["snapshot_id"].notna().all()
            and announcements["snapshot_id"].eq(snapshot_id).all(),
            "announcement snapshot_id drifted",
        )
        for column, expected in (
            ("revision_history_complete", False),
            ("strict_pit_eligible", False),
            ("hard_valid", True),
        ):
            values = announcements[column].tolist()
            _require(
                all(isinstance(value, bool) and value is expected for value in values),
                f"announcement {column} contract drifted",
            )

    _require(audit.get("asset_id") == collector.ASSET_ID, "audit asset_id drifted")
    _require(audit.get("status") == "PASS", "collector audit is not PASS")
    _require(audit.get("snapshot_id") == snapshot_id, "audit snapshot_id drifted")
    expected_audit_fields = {
        "capture_start": start,
        "capture_end": end,
        "universe_symbols": len(symbols),
        "symbol_year_queries": len(expected_specs),
        "request_pages": len(request_pages),
        "reported_records": raw_record_appearances,
        "captured_raw_record_appearances": raw_record_appearances,
        "unique_source_keys_within_queries": raw_record_appearances,
        "canonical_announcements": len(normalized_rows),
        "unique_announcement_keys": len(expected_by_key),
        "date_only_conservative_rows": int(
            announcements["precision"].eq("SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY").sum()
        ),
        "available_before_published_rows": int(
            pd.to_datetime(announcements["available_at"])
            .lt(pd.to_datetime(announcements["published_at"]))
            .sum()
        ),
        "sse_available_before_query_date_rows": int(
            announcements.loc[announcements.exchange.eq("SSE"), "available_at"]
            .lt(
                announcements.loc[
                    announcements.exchange.eq("SSE"), "source_query_date"
                ]
            )
            .sum()
        ),
        "sse_available_on_query_date_rows": int(
            pd.to_datetime(
                announcements.loc[
                    announcements.exchange.eq("SSE"), "available_at"
                ]
            )
            .dt.normalize()
            .eq(
                pd.to_datetime(
                    announcements.loc[
                        announcements.exchange.eq("SSE"), "source_query_date"
                    ]
                )
            )
            .sum()
        ),
        "sse_available_after_query_date_rows": int(
            pd.to_datetime(
                announcements.loc[
                    announcements.exchange.eq("SSE"), "available_at"
                ]
            )
            .dt.normalize()
            .gt(
                pd.to_datetime(
                    announcements.loc[
                        announcements.exchange.eq("SSE"), "source_query_date"
                    ]
                )
            )
            .sum()
        ),
        "documents_downloaded": 0,
    }
    for key, expected in expected_audit_fields.items():
        actual = audit.get(key)
        if isinstance(expected, int):
            actual = _integer(actual, f"audit {key}")
        _require(actual == expected, f"audit field drifted: {key}")
    _strict_bool(
        audit.get("all_query_raw_appearances_conserve"),
        True,
        "audit all_query_raw_appearances_conserve",
    )
    _strict_bool(audit.get("metadata_only"), True, "audit metadata_only")
    _require(
        collector.canonical_json(audit.get("queries")) == collector.canonical_json(query_audit),
        "per-query audit drifted",
    )
    _require(expected_audit_fields["available_before_published_rows"] == 0, "causality violation")

    return {
        "root": root,
        "snapshot_id": snapshot_id,
        "source_manifest": source_manifest,
        "universe_path": universe_path,
        "source_path": source_path,
        "audit_path": audit_path,
        "announcements_path": announcements_path,
        "pages_path": pages_path,
        "raw_pages": sorted(raw_page_rows, key=lambda row: (row["query_id"], row["page"])),
        "counts": {
            "universe_symbols": len(symbols),
            "queries": len(expected_specs),
            "raw_pages": len(raw_page_rows),
            "raw_record_appearances": raw_record_appearances,
            "canonical_announcements": len(normalized_rows),
        },
    }


def _inventory_entry(
    role: str,
    path: Path,
    *,
    root: Path,
    storage_scope: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sha, size = _file_facts(path, role)
    if storage_scope == "ASSET_ROOT":
        rendered_path = path.relative_to(root).as_posix()
    else:
        rendered_path = str(path.resolve())
    result: dict[str, Any] = {
        "role": role,
        "storage_scope": storage_scope,
        "path": rendered_path,
        "sha256": sha,
        "bytes": size,
    }
    if extra:
        result.update(extra)
    return result


def _build_validation_audit(validated: Mapping[str, Any], validated_at: str) -> dict[str, Any]:
    return {
        "validator_id": VALIDATOR_ID,
        "status": "PASS",
        "validated_at": validated_at,
        "snapshot_id": validated["snapshot_id"],
        "pit_grade": "B",
        "revision_history_incomplete": True,
        "title_metadata_only": True,
        "registered": False,
        "backtest_authorized": False,
        "counts": dict(validated["counts"]),
        "checks": {
            "source_declares_staging": True,
            "source_declares_backtest_unauthorized": True,
            "source_file_hashes_match": True,
            "raw_page_inventory_exact": True,
            "raw_page_hashes_and_bytes_match": True,
            "every_page_reparsed": True,
            "page_numbers_contiguous": True,
            "reported_totals_and_page_counts_match": True,
            "per_query_records_conserve": True,
            "canonical_count_equals_raw_record_appearances": True,
            "source_query_dates_rebuilt_from_raw_records": True,
            "source_query_dates_within_requested_intervals": True,
            "SSE_ADDDATE_second_precision_validated": True,
            "raw_records_renormalize_exactly": True,
            "raw_record_hashes_recomputed": True,
            "snapshot_id_recomputed": True,
        },
        "limitations": [
            "limited PIT-B historical snapshot; source revision history is incomplete",
            "title metadata only; announcement documents are not part of this asset",
            (
                "SSEDATE controls official query membership while ADDDATE independently "
                "controls availability and can precede or follow SSEDATE"
            ),
            "not registered and not authorized for backtests, model fitting, or signal gating",
        ],
    }


def _expected_inventory(
    validated: Mapping[str, Any], audit_validation_path: Path
) -> list[dict[str, Any]]:
    root = validated["root"]
    entries = [
        _inventory_entry(
            "universe",
            validated["universe_path"],
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "source_manifest",
            validated["source_path"],
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "collector_audit",
            validated["audit_path"],
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "announcements_table",
            validated["announcements_path"],
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "request_pages_table",
            validated["pages_path"],
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "validation_audit",
            audit_validation_path,
            root=root,
            storage_scope="ASSET_ROOT",
        ),
    ]
    for raw in validated["raw_pages"]:
        _, path = _safe_internal_path(root, raw["path"], "raw inventory path")
        entries.append(
            _inventory_entry(
                "raw_page",
                path,
                root=root,
                storage_scope="ASSET_ROOT",
                extra={"query_id": raw["query_id"], "page": raw["page"]},
            )
        )
    return entries


def _build_asset_manifest(
    validated: Mapping[str, Any],
    audit_validation: Mapping[str, Any],
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "manifest_schema": "CY_IMMUTABLE_ASSET_MANIFEST_V1",
        "asset_id": collector.ASSET_ID,
        "status": "SEALED_STAGING",
        "immutable": True,
        "manifest_self_included": False,
        "staging": True,
        "registered": False,
        "backtest_authorized": False,
        "snapshot_id": validated["snapshot_id"],
        "sealed_at": audit_validation["validated_at"],
        "validator_id": VALIDATOR_ID,
        "location": str(validated["root"]),
        "pit": {
            "grade": "B",
            "revision_history_incomplete": True,
            "strict_archival_pit_ready": False,
        },
        "content": {
            "title_metadata_only": True,
            "announcement_documents_included": False,
        },
        "limitations": list(audit_validation["limitations"]),
        "inventory": inventory,
        "inventory_sha256": collector.sha256_bytes(
            collector.canonical_json(inventory).encode("utf-8")
        ),
    }


def _write_json_exclusive(path: Path, value: Mapping[str, Any], *, read_only: bool = False) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise SealError(f"refusing to overwrite existing seal file: {path}") from exc
    if read_only:
        path.chmod(0o444)


def seal_asset(output_root: Path) -> dict[str, Any]:
    """Validate a collector output and add a non-authorizing immutable seal."""

    root = output_root.resolve(strict=True)
    audit_validation_path = root / AUDIT_VALIDATION_NAME
    asset_manifest_path = root / ASSET_MANIFEST_NAME
    _require(
        not audit_validation_path.exists() and not asset_manifest_path.exists(),
        "seal files already exist; use validate mode",
    )
    validated = _validate_capture(root)
    validated_at = datetime.now(UTC).isoformat()
    audit_validation = _build_validation_audit(validated, validated_at)
    _write_json_exclusive(audit_validation_path, audit_validation)
    try:
        inventory = _expected_inventory(validated, audit_validation_path)
        asset_manifest = _build_asset_manifest(validated, audit_validation, inventory)
        _write_json_exclusive(asset_manifest_path, asset_manifest, read_only=True)
    except Exception:
        audit_validation_path.unlink(missing_ok=True)
        raise
    return {
        "status": "PASS",
        "snapshot_id": validated["snapshot_id"],
        "audit_validation": str(audit_validation_path),
        "asset_manifest": str(asset_manifest_path),
        "asset_manifest_sha256": collector.sha256_file(asset_manifest_path),
        "backtest_authorized": False,
    }


def validate_asset(output_root: Path) -> dict[str, Any]:
    """Revalidate the raw capture and every entry in an existing asset seal."""

    root = output_root.resolve(strict=True)
    validated = _validate_capture(root)
    audit_validation_path = root / AUDIT_VALIDATION_NAME
    asset_manifest_path = root / ASSET_MANIFEST_NAME
    audit_validation = _read_json_object(audit_validation_path, AUDIT_VALIDATION_NAME)
    asset_manifest = _read_json_object(asset_manifest_path, ASSET_MANIFEST_NAME)
    validated_at = _string(audit_validation.get("validated_at"), "validated_at")
    _timestamp(validated_at, "validated_at", timezone_required=True)
    expected_audit = _build_validation_audit(validated, validated_at)
    _require(
        collector.canonical_json(audit_validation) == collector.canonical_json(expected_audit),
        "audit_validation.json content drifted",
    )
    expected_inventory = _expected_inventory(validated, audit_validation_path)
    expected_manifest = _build_asset_manifest(validated, expected_audit, expected_inventory)
    _require(
        collector.canonical_json(asset_manifest) == collector.canonical_json(expected_manifest),
        "asset_manifest.json content or inventory drifted",
    )
    mode = stat.S_IMODE(asset_manifest_path.stat().st_mode)
    _require(mode & 0o222 == 0, "asset_manifest.json is not filesystem read-only")
    _require(
        all(entry.get("path") != ASSET_MANIFEST_NAME for entry in expected_inventory),
        "asset manifest must not include itself",
    )
    return {
        "status": "PASS",
        "snapshot_id": validated["snapshot_id"],
        "asset_manifest_sha256": collector.sha256_file(asset_manifest_path),
        "files_verified": len(expected_inventory),
        "backtest_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("seal", "validate"):
        child = subparsers.add_parser(mode)
        child.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = (
        seal_asset(args.output_root)
        if args.mode == "seal"
        else validate_asset(args.output_root)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
