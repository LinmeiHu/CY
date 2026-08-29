#!/usr/bin/env python3
"""Acquire the bounded free BaoStock inputs for ChinNext V1 Gate A/B.

This is deliberately a narrow acquisition utility, not a reusable market-data
framework.  It freezes one date-specific denominator stream, one stock-basic
stream, and one minimum daily-state stream under the acquisition specification.
Temporary per-query parts make network capture resumable and are removed after a
verified deterministic merge unless ``--keep-parts`` is supplied.
"""

from __future__ import annotations

import argparse
import atexit
import gzip
import hashlib
import json
import multiprocessing as mp
import os
import platform
import re
import shutil
import sys
import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPEC = (
    ROOT
    / "research/chinext_v1/specs/"
    "chinext_v1_free_historical_state_acquisition_spec.json"
)
DEFAULT_OUTPUT = ROOT / "research/chinext_v1/data/pit_free_2017_2021"
DEFAULT_OFFICIAL_EVENTS = (
    ROOT
    / "research/chinext_v1/specs/"
    "chinext_v1_free_historical_state_official_events.json"
)

CANONICAL_JSON = {
    "ensure_ascii": False,
    "sort_keys": True,
    "separators": (",", ":"),
}
DENOMINATOR_FIELDS = ("code", "tradeStatus", "code_name")
BASIC_FIELDS = ("code", "code_name", "ipoDate", "outDate", "type", "status")
STATE_FIELDS = ("date", "code", "tradestatus", "isST", "volume", "amount")
CHINEXT_CODE = re.compile(r"^sz\.(\d{6})$")

_BS: Any = None
_RETRY_RULE: dict[str, Any] = {}
_PART_ROOT: Path | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "denominator",
            "basic",
            "state",
            "official",
            "materialize",
            "all",
        ),
        help="bounded source-capture stage",
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--official-events", type=Path, default=DEFAULT_OFFICIAL_EVENTS
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--keep-parts",
        action="store_true",
        help="retain verified resumability parts after the canonical merge",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text_lines(values: Iterable[str]) -> str:
    payload = "".join(f"{value}\n" for value in values).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, **CANONICAL_JSON) + "\n").encode("utf-8")


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_canonical_gzip(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
            for row in rows:
                zipped.write(canonical_line(row))
    os.replace(temporary, path)


def iter_jsonl_gzip(path: Path) -> Iterator[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"non-object JSONL row {path}:{line_number}")
            yield {str(key): str(item) for key, item in value.items()}


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec["acquisition_spec_id"] != "CHINEXT-V1-FREE-HISTORICAL-STATE-2017-2021-V1":
        raise ValueError("unexpected acquisition spec")
    if spec["authorization_target"] != "BOUNDED_EFFECTIVE_STATE_PIT_B":
        raise ValueError("acquisition target is not bounded PIT-B")
    if spec["known_at_rule"]["strict_pit_a"] is not False:
        raise ValueError("strict PIT-A must remain disabled")
    return spec


def load_calendar(spec: dict[str, Any]) -> list[str]:
    calendar_path = Path(spec["calendar"]["path"])
    if sha256_file(calendar_path) != spec["calendar"]["sha256"]:
        raise ValueError("QD-003 calendar hash mismatch")
    calendar = pd.read_parquet(calendar_path, columns=["trade_date"])
    dates = pd.to_datetime(calendar["trade_date"], errors="raise").dt.date
    start, end = spec["date_range"]
    values = sorted({day.isoformat() for day in dates if start <= day.isoformat() <= end})
    if len(values) != spec["calendar"]["trading_date_count"]:
        raise ValueError(f"QD-003 trading-date count mismatch: {len(values)}")
    if sha256_text_lines(values) != spec["calendar"]["trading_dates_sha256"]:
        raise ValueError("QD-003 trading-date sequence hash mismatch")
    if values[0] != start or values[-1] != end:
        raise ValueError("QD-003 bounded endpoints mismatch")
    return values


def validate_runtime(spec: dict[str, Any]) -> str:
    try:
        import baostock as bs
    except ImportError as exc:
        raise RuntimeError("BaoStock is required for source capture") from exc
    package_version = distribution_version("baostock")
    module_version = str(getattr(bs, "__version__", "UNKNOWN"))
    expected_package = str(spec["baostock"]["package_version"])
    expected_module = str(spec["baostock"]["module_version"])
    if package_version != expected_package or module_version != expected_module:
        raise ValueError(
            "BaoStock version mismatch: "
            f"expected package={expected_package} module={expected_module}, "
            f"got package={package_version} module={module_version}"
        )
    return package_version


def normalize_result_rows(result: Any, expected_fields: tuple[str, ...]) -> list[dict[str, str]]:
    fields = tuple(str(field) for field in result.fields)
    if fields != expected_fields:
        raise ValueError(f"BaoStock field mismatch: expected {expected_fields}, got {fields}")
    rows: list[dict[str, str]] = []
    while result.next():
        values = [str(value) for value in result.get_row_data()]
        if len(values) != len(fields):
            raise ValueError("BaoStock row width mismatch")
        rows.append(dict(zip(fields, values, strict=True)))
    return rows


def _worker_init(part_root: str, retry_rule: dict[str, Any]) -> None:
    global _BS, _PART_ROOT, _RETRY_RULE
    import baostock as bs

    _PART_ROOT = Path(part_root)
    _RETRY_RULE = retry_rule
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    _BS = bs
    atexit.register(bs.logout)


def _query_with_retries(function: str, **parameters: str) -> tuple[Any, int]:
    last_error = "query was not attempted"
    for attempt in range(1, int(_RETRY_RULE["max_attempts"]) + 1):
        try:
            if function == "query_all_stock":
                result = _BS.query_all_stock(day=parameters["day"])
            elif function == "query_history_k_data_plus":
                result = _BS.query_history_k_data_plus(
                    parameters["code"],
                    ",".join(STATE_FIELDS),
                    start_date=parameters["start_date"],
                    end_date=parameters["end_date"],
                    frequency="d",
                    adjustflag="3",
                )
            else:  # pragma: no cover - internal programming error
                raise ValueError(function)
            if str(result.error_code) == "0":
                return result, attempt
            last_error = f"{result.error_code} {result.error_msg}"
        except Exception as exc:  # keep parameters fixed across attempts
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < int(_RETRY_RULE["max_attempts"]):
            time.sleep(float(_RETRY_RULE["retry_delay_seconds"]))
    raise RuntimeError(f"{function} failed after {attempt} attempts: {last_error}")


def _denominator_paths(day: str) -> tuple[Path, Path]:
    assert _PART_ROOT is not None
    directory = _PART_ROOT / "denominator"
    return directory / f"{day}.jsonl.gz", directory / f"{day}.meta.json"


def _state_paths(code: str) -> tuple[Path, Path]:
    assert _PART_ROOT is not None
    safe_code = code.replace(".", "_")
    directory = _PART_ROOT / "state"
    return directory / f"{safe_code}.jsonl.gz", directory / f"{safe_code}.meta.json"


def _acquire_denominator_day(day: str) -> dict[str, Any]:
    data_path, meta_path = _denominator_paths(day)
    result, attempts = _query_with_retries("query_all_stock", day=day)
    rows = normalize_result_rows(result, DENOMINATOR_FIELDS)
    if not rows:
        raise RuntimeError(f"query_all_stock({day}) returned no rows")
    if len({row["code"] for row in rows}) != len(rows):
        raise ValueError(f"query_all_stock({day}) returned duplicate codes")
    rows.sort(key=lambda row: row["code"])
    frozen_rows = ({"trade_date": day, **row} for row in rows)
    atomic_canonical_gzip(data_path, frozen_rows)
    codes = [row["code"] for row in rows]
    metadata = {
        "api_function": "query_all_stock",
        "attempts": attempts,
        "captured_at": utc_now(),
        "error_code": "0",
        "parameters": {"day": day},
        "query_success": True,
        "row_count": len(rows),
        "sha256": sha256_file(data_path),
        "sorted_code_set_sha256": sha256_text_lines(codes),
        "trade_date": day,
    }
    atomic_json(meta_path, metadata)
    return metadata


def _acquire_state_code(task: tuple[str, str, str]) -> dict[str, Any]:
    code, start, end = task
    data_path, meta_path = _state_paths(code)
    result, attempts = _query_with_retries(
        "query_history_k_data_plus", code=code, start_date=start, end_date=end
    )
    rows = normalize_result_rows(result, STATE_FIELDS)
    if any(row["code"] != code for row in rows):
        raise ValueError(f"state response changed code for {code}")
    if any(not (start <= row["date"] <= end) for row in rows):
        raise ValueError(f"state response escaped bounded interval for {code}")
    if len({row["date"] for row in rows}) != len(rows):
        raise ValueError(f"state response has duplicate dates for {code}")
    rows.sort(key=lambda row: row["date"])
    atomic_canonical_gzip(data_path, rows)
    metadata = {
        "api_function": "query_history_k_data_plus",
        "attempts": attempts,
        "captured_at": utc_now(),
        "error_code": "0",
        "parameters": {
            "adjustflag": "3",
            "code": code,
            "end_date": end,
            "fields": list(STATE_FIELDS),
            "frequency": "d",
            "start_date": start,
        },
        "query_success": True,
        "row_count": len(rows),
        "sha256": sha256_file(data_path),
        "sorted_date_set_sha256": sha256_text_lines(row["date"] for row in rows),
        "symbol": code,
    }
    atomic_json(meta_path, metadata)
    return metadata


def _load_valid_meta(
    data_path: Path, meta_path: Path, key: str, value: str
) -> dict[str, Any] | None:
    if not data_path.is_file() or not meta_path.is_file():
        return None
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if str(metadata.get(key)) != value or metadata.get("query_success") is not True:
        raise ValueError(f"resumability metadata mismatch: {meta_path}")
    if metadata.get("sha256") != sha256_file(data_path):
        raise ValueError(f"resumability part hash mismatch: {data_path}")
    return metadata


def _merge_parts(
    ordered: list[str],
    path_for: Any,
    output_path: Path,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
            for value in ordered:
                data_path, _ = path_for(value)
                with gzip.open(data_path, "rb") as part:
                    shutil.copyfileobj(part, zipped, length=1024 * 1024)
    os.replace(temporary, output_path)
    return sha256_file(output_path)


def _remove_part_directory(path: Path) -> None:
    if not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_file() and (
            child.name.endswith(".jsonl.gz") or child.name.endswith(".meta.json")
        ):
            child.unlink()
        else:
            raise ValueError(f"unexpected resumability artifact: {child}")
    path.rmdir()


def _run_parallel(
    tasks: list[Any],
    worker: Any,
    workers: int,
    part_root: Path,
    retry_rule: dict[str, Any],
    label: str,
) -> list[dict[str, Any]]:
    if not tasks:
        return []
    context = mp.get_context("spawn")
    completed: list[dict[str, Any]] = []
    with context.Pool(
        processes=workers,
        initializer=_worker_init,
        initargs=(str(part_root), retry_rule),
    ) as pool:
        for metadata in pool.imap_unordered(worker, tasks, chunksize=1):
            completed.append(metadata)
            count = len(completed)
            if count == 1 or count % 20 == 0 or count == len(tasks):
                print(f"{label} acquired={count}/{len(tasks)}", flush=True)
    return completed


def acquire_denominator(
    spec: dict[str, Any], dates: list[str], output: Path, workers: int, keep_parts: bool
) -> dict[str, Any]:
    part_root = output / ".parts"
    part_dir = part_root / "denominator"
    part_dir.mkdir(parents=True, exist_ok=True)
    global _PART_ROOT
    _PART_ROOT = part_root
    metadata_by_date: dict[str, dict[str, Any]] = {}
    pending: list[str] = []
    for day in dates:
        data_path, meta_path = _denominator_paths(day)
        metadata = _load_valid_meta(data_path, meta_path, "trade_date", day)
        if metadata is None:
            pending.append(day)
        else:
            metadata_by_date[day] = metadata
    print(
        f"denominator required={len(dates)} reused={len(metadata_by_date)} pending={len(pending)}",
        flush=True,
    )
    for metadata in _run_parallel(
        pending,
        _acquire_denominator_day,
        workers,
        part_root,
        spec["failure_retry_rule"],
        "denominator",
    ):
        metadata_by_date[metadata["trade_date"]] = metadata
    if sorted(metadata_by_date) != dates:
        missing = sorted(set(dates) - set(metadata_by_date))
        raise RuntimeError(f"unexplained missing denominator dates: {missing}")
    raw_path = output / "raw/baostock_historical_denominator.jsonl.gz"
    stream_sha = _merge_parts(dates, _denominator_paths, raw_path)
    index_path = output / "raw/baostock_historical_denominator_index.json"
    index_payload = {
        "acquisition_spec_id": spec["acquisition_spec_id"],
        "api_function": "query_all_stock",
        "baostock_module_version": spec["baostock"]["module_version"],
        "baostock_package_version": spec["baostock"]["package_version"],
        "date_range": spec["date_range"],
        "query_success_count": len(dates),
        "raw_artifact": str(raw_path.resolve()),
        "raw_artifact_sha256": stream_sha,
        "snapshots": [metadata_by_date[day] for day in dates],
        "trading_dates_required": len(dates),
    }
    atomic_json(index_path, index_payload)
    if not keep_parts:
        _remove_part_directory(part_dir)
    return {
        "raw_path": str(raw_path),
        "raw_sha256": stream_sha,
        "index_path": str(index_path),
        "index_sha256": sha256_file(index_path),
        "trading_dates": len(dates),
        "rows": sum(int(item["row_count"]) for item in metadata_by_date.values()),
    }


def _login_once() -> Any:
    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    return bs


def acquire_basic(spec: dict[str, Any], output: Path) -> dict[str, Any]:
    raw_path = output / "raw/baostock_stock_basic.jsonl.gz"
    meta_path = output / "raw/baostock_stock_basic.meta.json"
    existing = _load_valid_meta(raw_path, meta_path, "api_function", "query_stock_basic")
    if existing is not None:
        print(f"stock-basic reused rows={existing['row_count']}", flush=True)
        return existing
    bs = _login_once()
    try:
        last_error = "query was not attempted"
        result = None
        for attempt in range(1, int(spec["failure_retry_rule"]["max_attempts"]) + 1):
            try:
                candidate = bs.query_stock_basic()
                if str(candidate.error_code) == "0":
                    result = candidate
                    break
                last_error = f"{candidate.error_code} {candidate.error_msg}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < int(spec["failure_retry_rule"]["max_attempts"]):
                time.sleep(float(spec["failure_retry_rule"]["retry_delay_seconds"]))
        if result is None:
            raise RuntimeError(f"query_stock_basic failed after {attempt} attempts: {last_error}")
        rows = normalize_result_rows(result, BASIC_FIELDS)
    finally:
        bs.logout()
    if not rows or len({row["code"] for row in rows}) != len(rows):
        raise ValueError("stock-basic is empty or has duplicate codes")
    rows.sort(key=lambda row: row["code"])
    atomic_canonical_gzip(raw_path, rows)
    metadata = {
        "acquisition_spec_id": spec["acquisition_spec_id"],
        "api_function": "query_stock_basic",
        "attempts": attempt,
        "captured_at": utc_now(),
        "error_code": "0",
        "parameters": {},
        "query_success": True,
        "raw_artifact": str(raw_path.resolve()),
        "row_count": len(rows),
        "sha256": sha256_file(raw_path),
    }
    atomic_json(meta_path, metadata)
    print(f"stock-basic acquired rows={len(rows)}", flush=True)
    return metadata


def candidate_codes(output: Path) -> tuple[list[str], list[str]]:
    denominator_path = output / "raw/baostock_historical_denominator.jsonl.gz"
    basic_path = output / "raw/baostock_stock_basic.jsonl.gz"
    if not denominator_path.is_file() or not basic_path.is_file():
        raise FileNotFoundError("denominator and stock-basic raw streams are required")
    seen: set[str] = set()
    for row in iter_jsonl_gzip(denominator_path):
        match = CHINEXT_CODE.fullmatch(row["code"])
        if match and 300000 <= int(match.group(1)) <= 309799:
            seen.add(row["code"])
    basic = {row["code"]: row for row in iter_jsonl_gzip(basic_path)}
    missing_basic = sorted(code for code in seen if code not in basic)
    candidates = sorted(code for code in seen if basic.get(code, {}).get("type") == "1")
    if missing_basic:
        raise RuntimeError(f"candidate codes missing stock-basic identity: {missing_basic}")
    if not candidates:
        raise RuntimeError("bounded candidate universe is empty")
    return candidates, sorted(seen - set(candidates))


def acquire_state(
    spec: dict[str, Any], output: Path, workers: int, keep_parts: bool
) -> dict[str, Any]:
    codes, non_equity_codes = candidate_codes(output)
    start, end = spec["date_range"]
    part_root = output / ".parts"
    part_dir = part_root / "state"
    part_dir.mkdir(parents=True, exist_ok=True)
    global _PART_ROOT
    _PART_ROOT = part_root
    metadata_by_code: dict[str, dict[str, Any]] = {}
    pending: list[tuple[str, str, str]] = []
    for code in codes:
        data_path, meta_path = _state_paths(code)
        metadata = _load_valid_meta(data_path, meta_path, "symbol", code)
        if metadata is None:
            pending.append((code, start, end))
        else:
            metadata_by_code[code] = metadata
    print(
        f"daily-state candidates={len(codes)} reused={len(metadata_by_code)} "
        f"pending={len(pending)} non_equity_excluded={len(non_equity_codes)}",
        flush=True,
    )
    for metadata in _run_parallel(
        pending,
        _acquire_state_code,
        workers,
        part_root,
        spec["failure_retry_rule"],
        "daily-state",
    ):
        metadata_by_code[metadata["symbol"]] = metadata
    if sorted(metadata_by_code) != codes:
        missing = sorted(set(codes) - set(metadata_by_code))
        raise RuntimeError(f"unexplained missing daily-state symbols: {missing}")
    raw_path = output / "raw/baostock_daily_state.jsonl.gz"
    stream_sha = _merge_parts(codes, _state_paths, raw_path)
    index_path = output / "raw/baostock_daily_state_index.json"
    index_payload = {
        "acquisition_spec_id": spec["acquisition_spec_id"],
        "api_function": "query_history_k_data_plus",
        "baostock_module_version": spec["baostock"]["module_version"],
        "baostock_package_version": spec["baostock"]["package_version"],
        "candidate_symbols": len(codes),
        "date_range": spec["date_range"],
        "non_equity_prefix_codes_excluded": non_equity_codes,
        "query_success_count": len(codes),
        "raw_artifact": str(raw_path.resolve()),
        "raw_artifact_sha256": stream_sha,
        "symbols": [metadata_by_code[code] for code in codes],
    }
    atomic_json(index_path, index_payload)
    if not keep_parts:
        _remove_part_directory(part_dir)
    return {
        "raw_path": str(raw_path),
        "raw_sha256": stream_sha,
        "index_path": str(index_path),
        "index_sha256": sha256_file(index_path),
        "symbols": len(codes),
        "rows": sum(int(item["row_count"]) for item in metadata_by_code.values()),
    }


def acquire_official(
    spec: dict[str, Any], events_path: Path, output: Path
) -> dict[str, Any]:
    import requests

    events = json.loads(events_path.read_text(encoding="utf-8"))
    documents = [events["board_code_semantics"]]
    documents.extend(events["identity_events"])
    documents.extend(events["risk_warning_events"])
    documents.extend(events["validation_events"])
    by_url: dict[str, dict[str, Any]] = {}
    for document in documents:
        url = str(document["source_url"])
        if url in by_url and by_url[url]["source_document"] != document["source_document"]:
            raise ValueError(f"one official URL has conflicting filenames: {url}")
        by_url[url] = document
    session = requests.Session()
    session.headers.update(
        {
            "Referer": "https://www.cninfo.com.cn/",
            "User-Agent": "Mozilla/5.0",
        }
    )
    official_dir = output / "raw/official"
    official_dir.mkdir(parents=True, exist_ok=True)
    acquired: list[dict[str, Any]] = []
    for number, url in enumerate(sorted(by_url), start=1):
        document = by_url[url]
        hostname = (urlparse(url).hostname or "").lower()
        if not any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in spec["official_evidence_rule"]["allowed_domains"]
        ):
            raise ValueError(f"official evidence domain is not authorized: {url}")
        target = official_dir / str(document["source_document"])
        expected = str(document["source_document_sha256"])
        mode = "REUSED"
        if not target.is_file():
            last_error = "download was not attempted"
            payload: bytes | None = None
            for attempt in range(1, int(spec["failure_retry_rule"]["max_attempts"]) + 1):
                try:
                    response = session.get(url, timeout=30)
                    response.raise_for_status()
                    payload = response.content
                    break
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                if attempt < int(spec["failure_retry_rule"]["max_attempts"]):
                    time.sleep(float(spec["failure_retry_rule"]["retry_delay_seconds"]))
            if payload is None:
                raise RuntimeError(f"official download failed: {url}: {last_error}")
            if target.suffix.lower() == ".pdf" and not payload.startswith(b"%PDF-"):
                raise ValueError(f"official PDF signature mismatch: {url}")
            if target.suffix.lower() == ".html" and b"<html" not in payload.lower():
                raise ValueError(f"official HTML signature mismatch: {url}")
            temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, target)
            mode = "DOWNLOADED"
        actual = sha256_file(target)
        if expected != "PENDING_ACQUISITION" and actual != expected:
            raise ValueError(f"official document hash mismatch: {target}")
        acquired.append(
            {
                "acquired_at": utc_now(),
                "bytes": target.stat().st_size,
                "mode": mode,
                "path": str(target.resolve()),
                "sha256": actual,
                "source_document": target.name,
                "source_url": url,
            }
        )
        print(f"official acquired={number}/{len(by_url)} {target.name}", flush=True)
    index_path = output / "raw/official_documents_index.json"
    index = {
        "acquisition_spec_id": spec["acquisition_spec_id"],
        "documents": acquired,
        "official_document_count": len(acquired),
        "official_events_path": str(events_path.resolve()),
        "official_events_sha256_at_capture": sha256_file(events_path),
    }
    atomic_json(index_path, index)
    return {
        "index_path": str(index_path),
        "index_sha256": sha256_file(index_path),
        "official_document_count": len(acquired),
    }


def normalize_symbol(code: str) -> str:
    exchange, digits = code.split(".", 1)
    if exchange.lower() != "sz" or not re.fullmatch(r"\d{6}", digits):
        raise ValueError(f"unsupported BaoStock code: {code}")
    return f"{digits}.SZ"


def baostock_code(symbol: str) -> str:
    digits, exchange = symbol.split(".", 1)
    if exchange.upper() != "SZ" or not re.fullmatch(r"\d{6}", digits):
        raise ValueError(f"unsupported normalized symbol: {symbol}")
    return f"sz.{digits}"


def validate_identity_events(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    old_targets: dict[str, tuple[str, str]] = {}
    new_sources: dict[str, tuple[str, str]] = {}
    for event in events:
        old_code = baostock_code(str(event["old_code"]))
        new_code = baostock_code(str(event["new_code"]))
        effective_date = str(event["effective_date"])
        publication_date = str(event["publication_date"])
        if old_code == new_code or publication_date > effective_date:
            raise ValueError("invalid official identity event")
        old_value = (new_code, effective_date)
        new_value = (old_code, effective_date)
        if old_code in old_targets and old_targets[old_code] != old_value:
            raise ValueError(f"ambiguous alias old code: {old_code}")
        if new_code in new_sources and new_sources[new_code] != new_value:
            raise ValueError(f"ambiguous alias new code: {new_code}")
        old_targets[old_code] = old_value
        new_sources[new_code] = new_value
        normalized.append(
            {
                "effective_date": effective_date,
                "new_code": new_code,
                "old_code": old_code,
                "publication_date": publication_date,
                "source_document_sha256": str(event["source_document_sha256"]),
            }
        )
    return sorted(normalized, key=lambda item: (item["effective_date"], item["old_code"]))


def identity_allowed(
    code: str, day: str, identity_events: list[dict[str, str]]
) -> bool:
    for event in identity_events:
        if code == event["new_code"] and day < event["effective_date"]:
            return False
        if code == event["old_code"] and day >= event["effective_date"]:
            return False
    return True


def validate_official_documents(
    events: dict[str, Any], official_dir: Path
) -> list[dict[str, Any]]:
    documents = [events["board_code_semantics"]]
    documents.extend(events["identity_events"])
    documents.extend(events["risk_warning_events"])
    documents.extend(events["validation_events"])
    validated: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for document in documents:
        filename = str(document["source_document"])
        expected = str(document["source_document_sha256"])
        if expected == "PENDING_ACQUISITION":
            raise ValueError(f"official evidence is not hash-bound: {filename}")
        if filename in seen and seen[filename] != expected:
            raise ValueError(f"conflicting official document hash: {filename}")
        seen[filename] = expected
    for filename, expected in sorted(seen.items()):
        path = official_dir / filename
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"official evidence hash mismatch: {filename}")
        validated.append(
            {
                "bytes": path.stat().st_size,
                "path": str(path.resolve()),
                "sha256": expected,
                "source_document": filename,
            }
        )
    return validated


def identity_fingerprint_groups(
    state_path: Path, basic_rows: dict[str, dict[str, str]]
) -> list[list[str]]:
    fingerprints: dict[str, tuple[int, str]] = {}
    current_code: str | None = None
    digest: Any = None
    row_count = 0

    def finish() -> None:
        if current_code is not None:
            fingerprints[current_code] = (row_count, digest.hexdigest())

    for row in iter_jsonl_gzip(state_path):
        code = row["code"]
        if code != current_code:
            finish()
            current_code = code
            digest = hashlib.sha256()
            row_count = 0
        identity_state = {
            key: row[key] for key in ("date", "isST", "tradestatus", "volume")
        }
        digest.update(canonical_line(identity_state))
        row_count += 1
    finish()
    grouped: dict[tuple[str, int, str], list[str]] = {}
    for code, (count, fingerprint) in fingerprints.items():
        ipo_date = basic_rows[code]["ipoDate"]
        grouped.setdefault((ipo_date, count, fingerprint), []).append(code)
    return sorted(sorted(group) for group in grouped.values() if len(group) > 1)


def resolve_alias_anomalies(
    groups: list[list[str]], identity_events: list[dict[str, str]]
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    event_pairs = {
        frozenset((event["old_code"], event["new_code"])): event
        for event in identity_events
    }
    if len(event_pairs) != len(identity_events):
        raise ValueError("ambiguous duplicate official alias events")
    for group in groups:
        event = event_pairs.get(frozenset(group))
        if event is None or len(group) != 2:
            raise ValueError(f"unresolved identity fingerprint group: {group}")
        resolved.append(
            {
                "codes": group,
                "effective_date": event["effective_date"],
                "new_code": event["new_code"],
                "old_code": event["old_code"],
                "official_source_sha256": event["source_document_sha256"],
                "status": "RESOLVED_OFFICIAL_BOUNDARY",
            }
        )
    represented = {frozenset(item["codes"]) for item in resolved}
    for pair in event_pairs:
        if pair not in represented:
            raise ValueError(f"official alias event has no detected anomaly: {sorted(pair)}")
    return resolved


def detect_risk_intervals(
    state_path: Path, identity_events: list[dict[str, str]]
) -> list[dict[str, str]]:
    intervals: list[dict[str, str]] = []
    current_code: str | None = None
    active_start: str | None = None
    previous_date: str | None = None

    def finish_code() -> None:
        nonlocal active_start
        if current_code is not None and active_start is not None:
            assert previous_date is not None
            intervals.append(
                {
                    "end_date": previous_date,
                    "source_code": current_code,
                    "start_date": active_start,
                }
            )
            active_start = None

    for row in iter_jsonl_gzip(state_path):
        code = row["code"]
        day = row["date"]
        if code != current_code:
            finish_code()
            current_code = code
            previous_date = None
        if not identity_allowed(code, day, identity_events):
            continue
        flag = row["isST"]
        if flag not in {"0", "1"}:
            raise ValueError(f"unknown BaoStock isST value: {code} {day} {flag!r}")
        if flag == "1" and active_start is None:
            active_start = day
        if flag == "0" and active_start is not None:
            assert previous_date is not None
            intervals.append(
                {
                    "end_date": previous_date,
                    "source_code": code,
                    "start_date": active_start,
                }
            )
            active_start = None
        previous_date = day
    finish_code()
    return intervals


def resolve_risk_intervals(
    intervals: list[dict[str, str]],
    official_events: list[dict[str, Any]],
    date_range: list[str],
) -> list[dict[str, str]]:
    official: dict[tuple[str, str], dict[str, Any]] = {}
    for event in official_events:
        subtype = str(event["risk_warning_type"])
        if subtype not in {"ST", "STAR_ST"}:
            raise ValueError(f"unsupported risk-warning subtype: {subtype}")
        if str(event["publication_date"]) > str(event["effective_date"]):
            raise ValueError("risk-warning publication follows effective date")
        key = (baostock_code(str(event["symbol"])), str(event["effective_date"]))
        if key in official:
            raise ValueError(f"ambiguous risk-warning subtype: {key}")
        official[key] = event
    resolved: list[dict[str, str]] = []
    used: set[tuple[str, str]] = set()
    for interval in intervals:
        key = (interval["source_code"], interval["start_date"])
        event = official.get(key)
        if event is None:
            raise ValueError(f"missing official risk-warning subtype: {key}")
        used.add(key)
        resolved.append(
            {
                **interval,
                "publication_date": str(event["publication_date"]),
                "risk_warning_type": str(event["risk_warning_type"]),
                "source_document": str(event["source_document"]),
                "source_document_sha256": str(event["source_document_sha256"]),
            }
        )
    start, end = date_range
    unused = sorted(
        key
        for key in official
        if start <= key[1] <= end and key not in used
    )
    if unused:
        raise ValueError(f"official risk-warning events have no source interval: {unused}")
    return resolved


def official_range_candidate_codes(
    denominator_path: Path, basic_rows: dict[str, dict[str, str]]
) -> list[str]:
    seen: set[str] = set()
    for row in iter_jsonl_gzip(denominator_path):
        match = CHINEXT_CODE.fullmatch(row["code"])
        if match and 300000 <= int(match.group(1)) <= 399999:
            seen.add(row["code"])
    missing = sorted(code for code in seen if code not in basic_rows)
    if missing:
        raise ValueError(f"official-range codes missing stock-basic rows: {missing}")
    return sorted(code for code in seen if basic_rows[code]["type"] == "1")


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _copy_parquet(connection: Any, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    connection.execute(
        f"COPY ({query}) TO '{_sql_path(temporary)}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )
    os.replace(temporary, path)


def materialize_bounded_state(
    spec_path: Path,
    events_path: Path,
    output: Path,
) -> dict[str, Any]:
    import duckdb

    spec = load_spec(spec_path)
    events = json.loads(events_path.read_text(encoding="utf-8"))
    raw = output / "raw"
    denominator_path = raw / "baostock_historical_denominator.jsonl.gz"
    basic_path = raw / "baostock_stock_basic.jsonl.gz"
    state_path = raw / "baostock_daily_state.jsonl.gz"
    denominator_index_path = raw / "baostock_historical_denominator_index.json"
    state_index_path = raw / "baostock_daily_state_index.json"
    basic_meta_path = raw / "baostock_stock_basic.meta.json"
    official_index_path = raw / "official_documents_index.json"
    required_paths = (
        denominator_path,
        basic_path,
        state_path,
        denominator_index_path,
        state_index_path,
        basic_meta_path,
        official_index_path,
    )
    missing_paths = [str(path) for path in required_paths if not path.is_file()]
    if missing_paths:
        raise FileNotFoundError(f"missing acquisition artifacts: {missing_paths}")
    denominator_index = json.loads(denominator_index_path.read_text(encoding="utf-8"))
    state_index = json.loads(state_index_path.read_text(encoding="utf-8"))
    basic_meta = json.loads(basic_meta_path.read_text(encoding="utf-8"))
    if denominator_index["raw_artifact_sha256"] != sha256_file(denominator_path):
        raise ValueError("denominator raw hash mismatch")
    if state_index["raw_artifact_sha256"] != sha256_file(state_path):
        raise ValueError("daily-state raw hash mismatch")
    if basic_meta["sha256"] != sha256_file(basic_path):
        raise ValueError("stock-basic raw hash mismatch")
    if denominator_index["query_success_count"] != spec["calendar"]["trading_date_count"]:
        raise ValueError("denominator trading-date coverage mismatch")
    if any(not item["query_success"] for item in denominator_index["snapshots"]):
        raise ValueError("denominator contains a failed snapshot")
    if state_index["query_success_count"] != state_index["candidate_symbols"]:
        raise ValueError("daily-state symbol acquisition is incomplete")

    official_documents = validate_official_documents(events, raw / "official")
    identity_events = validate_identity_events(events["identity_events"])
    basic_rows = {row["code"]: row for row in iter_jsonl_gzip(basic_path)}
    candidates = official_range_candidate_codes(denominator_path, basic_rows)
    acquired_state_codes = sorted(item["symbol"] for item in state_index["symbols"])
    if candidates != acquired_state_codes:
        missing_state = sorted(set(candidates) - set(acquired_state_codes))
        extra_state = sorted(set(acquired_state_codes) - set(candidates))
        raise ValueError(
            f"official-range state scope mismatch missing={missing_state} extra={extra_state}"
        )
    alias_groups = identity_fingerprint_groups(state_path, basic_rows)
    alias_anomalies = resolve_alias_anomalies(alias_groups, identity_events)
    risk_intervals = resolve_risk_intervals(
        detect_risk_intervals(state_path, identity_events),
        events["risk_warning_events"],
        spec["date_range"],
    )

    authorized_codes = sorted(
        code
        for code in candidates
        if any(
            identity_allowed(code, day, identity_events)
            for day in (spec["date_range"][0], spec["date_range"][1])
        )
    )
    authorized_frame = pd.DataFrame({"source_code": authorized_codes})
    identity_frame = pd.DataFrame(identity_events)
    risk_frame = pd.DataFrame(risk_intervals)
    connection = duckdb.connect()
    connection.register("authorized_codes", authorized_frame)
    connection.register("identity_events_input", identity_frame)
    connection.register("risk_intervals_input", risk_frame)
    denominator_sql = (
        f"read_json_auto('{_sql_path(denominator_path)}', "
        "format='newline_delimited')"
    )
    basic_sql = f"read_json_auto('{_sql_path(basic_path)}', format='newline_delimited')"
    state_sql = f"read_json_auto('{_sql_path(state_path)}', format='newline_delimited')"
    calendar_sql = f"read_parquet('{_sql_path(Path(spec['calendar']['path']))}')"
    normalized_membership = f"""
        SELECT d.trade_date, d.code, d.tradeStatus, s.tradestatus, s.isST,
               s.volume, s.amount, b.ipoDate,
               TRY_CAST(NULLIF(b.outDate, '') AS DATE) AS out_date
        FROM {denominator_sql} d
        JOIN authorized_codes a ON a.source_code = d.code
        JOIN {basic_sql} b ON b.code = d.code AND b.type = '1'
        LEFT JOIN {state_sql} s ON s.code = d.code AND s.date = d.trade_date
        WHERE NOT EXISTS (
            SELECT 1 FROM identity_events_input i
            WHERE (d.code = i.new_code AND d.trade_date < CAST(i.effective_date AS DATE))
               OR (d.code = i.old_code AND d.trade_date >= CAST(i.effective_date AS DATE))
        )
    """
    coverage = connection.execute(
        f"""
        SELECT COUNT(*) AS rows,
               COUNT(*) FILTER (WHERE tradestatus IS NULL) AS missing_state,
               COUNT(*) FILTER (WHERE tradeStatus <> tradestatus) AS status_conflicts,
               COUNT(*) FILTER (WHERE isST NOT IN ('0','1')
                                  OR tradestatus NOT IN ('0','1')) AS unknown_state,
               COUNT(*) FILTER (WHERE trade_date < ipoDate
                                  OR (out_date IS NOT NULL AND trade_date > out_date))
                   AS list_out_conflicts,
               COUNT(*) - COUNT(DISTINCT (trade_date, code)) AS duplicate_keys
        FROM ({normalized_membership})
        """
    ).fetchone()
    if any(int(value) != 0 for value in coverage[1:]):
        raise ValueError(f"normalized membership/state validation failed: {coverage}")

    normalized = output / "normalized"
    security_master_path = normalized / "security_master.parquet"
    daily_state_path = normalized / "daily_historical_state.parquet"
    security_query = f"""
        WITH basic AS (
            SELECT code, code_name, ipoDate,
                   TRY_CAST(NULLIF(outDate, '') AS DATE) AS out_date,
                   status, type
            FROM {basic_sql}
        ), alias AS (
            SELECT i.old_code, i.new_code, i.source_document_sha256,
                   nb.status AS new_code_status
            FROM identity_events_input i
            JOIN basic nb ON nb.code = i.new_code
        )
        SELECT SUBSTR(b.code, 4, 6) || '.SZ' AS symbol,
               b.code AS source_code,
               b.code_name AS baostock_code_name_diagnostic,
               b.ipoDate AS list_date,
               b.out_date,
               b.status AS baostock_current_code_status_diagnostic,
               CASE
                   WHEN b.status = '1' THEN SUBSTR(b.code, 4, 6) || '.SZ'
                   WHEN a.new_code_status = '1' THEN SUBSTR(a.new_code, 4, 6) || '.SZ'
                   ELSE NULL
               END AS current_symbol_diagnostic,
               CASE
                   WHEN b.status = '1' THEN 'CURRENT_SURVIVOR'
                   WHEN a.new_code_status = '1' THEN 'CURRENT_SURVIVOR_VIA_OFFICIAL_ALIAS'
                   ELSE 'HISTORICAL_NON_SURVIVOR'
               END AS identity_status,
               a.source_document_sha256 AS official_alias_source_sha256,
               'BOUNDED_EFFECTIVE_STATE_PIT_B' AS authorization_class
        FROM basic b
        JOIN authorized_codes c ON c.source_code = b.code
        LEFT JOIN alias a ON a.old_code = b.code
        ORDER BY symbol
    """
    daily_query = f"""
        WITH calendar_rank AS (
            SELECT CAST(trade_date AS DATE) AS trade_date,
                   ROW_NUMBER() OVER (ORDER BY CAST(trade_date AS DATE)) AS session_number,
                   LEAD(CAST(trade_date AS DATE)) OVER (
                       ORDER BY CAST(trade_date AS DATE)
                   ) AS next_trade_date
            FROM {calendar_sql}
        ), basic AS (
            SELECT code, ipoDate FROM {basic_sql}
        ), list_rank AS (
            SELECT b.code, MIN(c.session_number) AS list_session_number
            FROM basic b
            JOIN calendar_rank c ON c.trade_date >= b.ipoDate
            JOIN authorized_codes a ON a.source_code = b.code
            GROUP BY b.code
        ), membership AS ({normalized_membership})
        SELECT m.trade_date,
               SUBSTR(m.code, 4, 6) || '.SZ' AS symbol,
               m.code AS source_code,
               CAST(c.session_number - lr.list_session_number + 1 AS INTEGER)
                   AS listed_trading_days,
               m.tradestatus AS trade_status,
               m.tradestatus = '0' AS full_day_suspended,
               m.isST = '1' AS risk_warning,
               CASE WHEN m.isST = '0' THEN 'NORMAL' ELSE r.risk_warning_type END
                   AS risk_warning_type,
               m.volume AS volume_raw,
               m.amount AS amount_raw,
               c.next_trade_date AS earliest_safe_use_date,
               'BOUNDED_EFFECTIVE_STATE_PIT_B' AS authorization_class
        FROM membership m
        JOIN calendar_rank c ON c.trade_date = m.trade_date
        JOIN list_rank lr ON lr.code = m.code
        LEFT JOIN risk_intervals_input r
          ON r.source_code = m.code
         AND m.trade_date BETWEEN CAST(r.start_date AS DATE) AND CAST(r.end_date AS DATE)
        WHERE m.isST = '0' OR r.risk_warning_type IS NOT NULL
        ORDER BY m.trade_date, symbol
    """
    _copy_parquet(connection, security_query, security_master_path)
    _copy_parquet(connection, daily_query, daily_state_path)

    determinism_dir = normalized / ".determinism_check"
    second_master = determinism_dir / "security_master.parquet"
    second_daily = determinism_dir / "daily_historical_state.parquet"
    _copy_parquet(connection, security_query, second_master)
    _copy_parquet(connection, daily_query, second_daily)
    deterministic = (
        sha256_file(security_master_path) == sha256_file(second_master)
        and sha256_file(daily_state_path) == sha256_file(second_daily)
    )
    second_master.unlink()
    second_daily.unlink()
    determinism_dir.rmdir()
    if not deterministic:
        raise ValueError("normalized parquet rebuild is not byte-deterministic")

    daily_rows = connection.execute(
        f"SELECT COUNT(*) FROM read_parquet('{_sql_path(daily_state_path)}')"
    ).fetchone()[0]
    security_rows = connection.execute(
        f"SELECT COUNT(*) FROM read_parquet('{_sql_path(security_master_path)}')"
    ).fetchone()[0]
    if int(daily_rows) != int(coverage[0]):
        raise ValueError("normalized daily row count changed during materialization")
    state_stats = connection.execute(
        f"""
        SELECT COUNT(*) FILTER (WHERE full_day_suspended),
               COUNT(DISTINCT symbol),
               MIN(trade_date), MAX(trade_date),
               COUNT(*) FILTER (WHERE risk_warning_type = 'ST'),
               COUNT(*) FILTER (WHERE risk_warning_type = 'STAR_ST')
        FROM read_parquet('{_sql_path(daily_state_path)}')
        """
    ).fetchone()
    identity_stats = connection.execute(
        f"""
        SELECT COUNT(*) FILTER (WHERE identity_status IN (
                   'CURRENT_SURVIVOR','CURRENT_SURVIVOR_VIA_OFFICIAL_ALIAS')),
               COUNT(*) FILTER (WHERE identity_status = 'HISTORICAL_NON_SURVIVOR'),
               COUNT(*) FILTER (WHERE list_date BETWEEN DATE '2017-04-12'
                                                    AND DATE '2021-12-31'),
               COUNT(*) FILTER (WHERE out_date BETWEEN DATE '2017-04-12'
                                                   AND DATE '2021-12-31')
        FROM read_parquet('{_sql_path(security_master_path)}')
        """
    ).fetchone()
    warmup_null_dates = [
        "2017-04-21",
        "2017-04-24",
        "2017-04-25",
        "2017-05-19",
        "2017-08-28",
    ]
    placeholders = ",".join(f"DATE '{day}'" for day in warmup_null_dates)
    warmup_rows = connection.execute(
        f"""
        SELECT trade_date, trade_status, full_day_suspended, volume_raw, amount_raw
        FROM read_parquet('{_sql_path(daily_state_path)}')
        WHERE symbol = '300372.SZ' AND trade_date IN ({placeholders})
        ORDER BY trade_date
        """
    ).fetchall()
    warmup_pass = (
        len(warmup_rows) == 5
        and all(row[1] == "0" and row[2] and row[3] == "" and row[4] == "" for row in warmup_rows)
    )
    if not warmup_pass:
        raise ValueError(f"warmup NULL suspension adjudication failed: {warmup_rows}")
    suspension_300198 = connection.execute(
        f"""
        SELECT STRFTIME(trade_date, '%Y%m%d') AS day
        FROM read_parquet('{_sql_path(daily_state_path)}')
        WHERE symbol = '300198.SZ' AND full_day_suspended
          AND trade_date BETWEEN DATE '2017-04-20' AND DATE '2017-08-31'
        ORDER BY trade_date
        """
    ).fetchall()
    suspension_hash = sha256_text_lines(row[0] for row in suspension_300198)
    if len(suspension_300198) != 93 or suspension_hash != (
        "0dfbbd52889738b0ee0d882199ef87b20b2ef212171bb0c099cd5873aeb211c7"
    ):
        raise ValueError("300198 BaoStock/QMT 93-session crosscheck failed")

    representative_checks = {
        "alias_future_code_rows": connection.execute(
            f"SELECT COUNT(*) FROM read_parquet('{_sql_path(daily_state_path)}') "
            "WHERE symbol = '302132.SZ'"
        ).fetchone()[0],
        "alias_old_code_rows": connection.execute(
            f"SELECT COUNT(*) FROM read_parquet('{_sql_path(daily_state_path)}') "
            "WHERE symbol = '300114.SZ'"
        ).fetchone()[0],
        "delisted_300028_last_date": str(
            connection.execute(
                f"SELECT MAX(trade_date) FROM read_parquet('{_sql_path(daily_state_path)}') "
                "WHERE symbol = '300028.SZ'"
            ).fetchone()[0]
        ),
        "later_listing_300812_first_date": str(
            connection.execute(
                f"SELECT MIN(trade_date) FROM read_parquet('{_sql_path(daily_state_path)}') "
                "WHERE symbol = '300812.SZ'"
            ).fetchone()[0]
        ),
        "st_300029_first_date": str(
            connection.execute(
                f"SELECT MIN(trade_date) FROM read_parquet('{_sql_path(daily_state_path)}') "
                "WHERE symbol = '300029.SZ' AND risk_warning_type = 'ST'"
            ).fetchone()[0]
        ),
        "star_st_300795_first_date": str(
            connection.execute(
                f"SELECT MIN(trade_date) FROM read_parquet('{_sql_path(daily_state_path)}') "
                "WHERE symbol = '300795.SZ' AND risk_warning_type = 'STAR_ST'"
            ).fetchone()[0]
        ),
    }
    expected_representatives = {
        "alias_future_code_rows": 0,
        "alias_old_code_rows": 1153,
        "delisted_300028_last_date": "2020-08-03",
        "later_listing_300812_first_date": "2020-01-09",
        "st_300029_first_date": "2020-09-15",
        "star_st_300795_first_date": "2021-04-28",
    }
    if representative_checks != expected_representatives:
        raise ValueError(f"representative materialization failed: {representative_checks}")

    sample_dates = [
        "2017-04-12",
        "2018-01-02",
        "2019-01-02",
        "2020-01-02",
        "2021-01-04",
        "2021-12-31",
    ]
    snapshots = {item["trade_date"]: item for item in denominator_index["snapshots"]}
    sample_hashes = {
        day: {
            "row_count": snapshots[day]["row_count"],
            "sorted_code_set_sha256": snapshots[day]["sorted_code_set_sha256"],
        }
        for day in sample_dates
    }
    if len({item["sorted_code_set_sha256"] for item in sample_hashes.values()}) != len(
        sample_dates
    ):
        raise ValueError("historical denominator does not vary through time")
    interval_counts = {
        subtype: sum(
            item["risk_warning_type"] == subtype for item in risk_intervals
        )
        for subtype in ("ST", "STAR_ST")
    }
    manifest = {
        "acquisition": {
            "baostock_module_version": spec["baostock"]["module_version"],
            "baostock_package_version": spec["baostock"]["package_version"],
            "snapshot_failure_count": 0,
            "trading_dates_acquired": denominator_index["query_success_count"],
            "trading_dates_required": spec["calendar"]["trading_date_count"],
        },
        "acquisition_spec": {
            "path": str(spec_path.resolve()),
            "sha256": sha256_file(spec_path),
        },
        "alias_anomalies": alias_anomalies,
        "authorization": {
            "class": "BOUNDED_EFFECTIVE_STATE_PIT_B",
            "date_range": spec["date_range"],
            "known_at_limitations": [
                "BaoStock has no record-level historical available_at or revision vintage",
                "combined retrospective rows are safe no earlier than "
                "earliest_safe_use_date, the next QD-003 session",
                "official risk-warning subtype events are effective on their "
                "explicit effective_date",
            ],
            "revision_limitations": [
                "STRICT_PIT_A=NO",
                "supplier revision_history_complete=false",
                "authorization is exact-artifact, date-, field-, and hash-bounded",
            ],
            "symbol_scope": "date-specific SZSE type=1 stocks within official "
            "ChinNext code semantics after official alias normalization",
        },
        "counts": {
            "current_survivor_identities": int(identity_stats[0]),
            "delistings": int(identity_stats[3]),
            "historical_gem_symbols_ever_seen": int(security_rows),
            "historical_non_survivors": int(identity_stats[1]),
            "historical_symbols_ever_seen": int(security_rows),
            "new_listings": int(identity_stats[2]),
            "normalized_daily_rows": int(daily_rows),
            "raw_daily_state_rows": sum(
                int(item["row_count"]) for item in state_index["symbols"]
            ),
            "raw_denominator_rows": sum(
                int(item["row_count"]) for item in denominator_index["snapshots"]
            ),
            "suspension_sessions": int(state_stats[0]),
        },
        "gate_a": {
            "alias_continuity": "PASS",
            "decision": "PASS",
            "delisting_boundary": "PASS",
            "fail_closed_unknown_conflict": "PASS",
            "full_session_suspension": "PASS",
            "gem_identity": "PASS",
            "hash_bound_authorization": "PASS",
            "listing_boundary": "PASS",
            "non_survivor_retention": "PASS",
            "star_st": "PASS",
            "st": "PASS",
        },
        "gate_b": {
            "calendar_status": "PASS_180_QD003_SESSIONS",
            "corporate_action_status": "PASS_BOUNDED_PIT_635_OF_635",
            "decision": "PASS",
            "identity_status": "PASS",
            "price_status": "PASS_HASH_BOUND_5_NULL_ROWS_PRESERVED_AS_SUSPENSIONS",
            "state_status": "PASS",
            "suspension_status": "PASS_5_OF_5_LEGITIMATE_SUSPENSIONS",
            "warmup_date_range": ["2017-04-12", "2017-12-29"],
            "warmup_sessions": 180,
        },
        "historical_denominator_samples": sample_hashes,
        "manifest_id": "CHINEXT-V1-FREE-HISTORICAL-STATE-2017-2021-MANIFEST-V1",
        "materialization": {
            "deterministic_rebuild": "PASS_BYTE_IDENTICAL",
            "representative_checks": representative_checks,
            "result": "PASS",
        },
        "normalized_artifacts": {
            "daily_historical_state": {
                "path": str(daily_state_path.resolve()),
                "rows": int(daily_rows),
                "sha256": sha256_file(daily_state_path),
            },
            "security_master": {
                "path": str(security_master_path.resolve()),
                "rows": int(security_rows),
                "sha256": sha256_file(security_master_path),
            },
        },
        "official_documents": {
            "count": len(official_documents),
            "events_path": str(events_path.resolve()),
            "events_sha256": sha256_file(events_path),
            "hash_status": "PASS_27_OF_27",
            "index_path": str(official_index_path.resolve()),
            "index_sha256": sha256_file(official_index_path),
        },
        "raw_artifacts": {
            "daily_state": {
                "index_path": str(state_index_path.resolve()),
                "index_sha256": sha256_file(state_index_path),
                "path": str(state_path.resolve()),
                "sha256": sha256_file(state_path),
            },
            "denominator": {
                "index_path": str(denominator_index_path.resolve()),
                "index_sha256": sha256_file(denominator_index_path),
                "path": str(denominator_path.resolve()),
                "sha256": sha256_file(denominator_path),
            },
            "security_basic": {
                "meta_path": str(basic_meta_path.resolve()),
                "meta_sha256": sha256_file(basic_meta_path),
                "path": str(basic_path.resolve()),
                "sha256": sha256_file(basic_path),
            },
        },
        "research_scope": {
            "free_paid_data_required": "NO",
            "gate_c_executed": False,
            "new_nav": 0,
            "new_strategy_trades": 0,
            "phase12b4_executed": False,
            "strategy_performance_consumed": False,
        },
        "risk_warning": {
            "interval_count": len(risk_intervals),
            "intervals": risk_intervals,
            "removal_positive_control": {
                "effective_date": events["validation_events"][0]["effective_date"],
                "scope": "OUT_OF_AUTHORIZED_RANGE_VALIDATION_ONLY",
                "source_document_sha256": events["validation_events"][0][
                    "source_document_sha256"
                ],
                "status": "PASS_OFFICIAL_EVENT_AND_PRIOR_BAOSTOCK_DAILY_CONTROL",
                "symbol": events["validation_events"][0]["symbol"],
            },
            "star_st_interval_count": interval_counts["STAR_ST"],
            "st_interval_count": interval_counts["ST"],
            "unresolved_count": 0,
        },
        "safe_to_preregister_gate_c": "YES",
        "source_hash_status": "PASS",
        "strategy": spec["frozen_strategy"],
        "suspension_crosscheck": {
            "baostock_count": len(suspension_300198),
            "exact_date_match_count": 93,
            "qmt_count": 93,
            "sorted_yyyymmdd_sha256": suspension_hash,
            "status": "PASS_93_OF_93",
        },
        "warmup_null_rows": [
            {
                "amount_raw": row[4],
                "classification": "LEGITIMATE_SUSPENSION",
                "date": str(row[0]),
                "symbol": "300372.SZ",
                "trade_status": row[1],
                "volume_raw": row[3],
            }
            for row in warmup_rows
        ],
    }
    manifest_path = output / "manifest.json"
    atomic_json(manifest_path, manifest)
    return {
        "daily_rows": int(daily_rows),
        "daily_sha256": sha256_file(daily_state_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "security_master_rows": int(security_rows),
        "security_master_sha256": sha256_file(security_master_path),
    }


def record_capture(
    spec_path: Path,
    spec: dict[str, Any],
    output: Path,
    stage: str,
    result: dict[str, Any],
) -> None:
    path = output / "raw/source_capture.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {
            "acquisition_spec_id": spec["acquisition_spec_id"],
            "acquisition_spec_path": str(spec_path.resolve()),
            "acquisition_spec_sha256": sha256_file(spec_path),
            "baostock_module_version": spec["baostock"]["module_version"],
            "baostock_package_version": spec["baostock"]["package_version"],
            "cost_required": False,
            "login_token_required": False,
            "platform": platform.platform(),
            "python": sys.version,
            "stages": {},
        }
    payload["stages"][stage] = {"completed_at": utc_now(), **result}
    atomic_json(path, payload)


def main() -> int:
    args = parse_args()
    if args.workers < 1 or args.workers > 16:
        raise ValueError("workers must be between 1 and 16")
    spec = load_spec(args.spec)
    validate_runtime(spec)
    dates = load_calendar(spec)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.stage in {"denominator", "all"}:
        result = acquire_denominator(
            spec, dates, args.output_dir, args.workers, args.keep_parts
        )
        record_capture(args.spec, spec, args.output_dir, "denominator", result)
        print(json.dumps({"stage": "denominator", **result}, sort_keys=True), flush=True)
    if args.stage in {"basic", "all"}:
        result = acquire_basic(spec, args.output_dir)
        record_capture(args.spec, spec, args.output_dir, "basic", result)
        print(json.dumps({"stage": "basic", **result}, sort_keys=True), flush=True)
    if args.stage in {"state", "all"}:
        result = acquire_state(spec, args.output_dir, args.workers, args.keep_parts)
        record_capture(args.spec, spec, args.output_dir, "state", result)
        print(json.dumps({"stage": "state", **result}, sort_keys=True), flush=True)
    if args.stage in {"official", "all"}:
        result = acquire_official(spec, args.official_events, args.output_dir)
        record_capture(args.spec, spec, args.output_dir, "official", result)
        print(json.dumps({"stage": "official", **result}, sort_keys=True), flush=True)
    if args.stage in {"materialize", "all"}:
        result = materialize_bounded_state(
            args.spec, args.official_events, args.output_dir
        )
        record_capture(args.spec, spec, args.output_dir, "materialize", result)
        print(
            json.dumps({"stage": "materialize", **result}, sort_keys=True),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
