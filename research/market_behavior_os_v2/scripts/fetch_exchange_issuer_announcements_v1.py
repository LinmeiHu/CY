#!/usr/bin/env python3
"""Capture official SSE/SZSE issuer-announcement metadata with raw-page lineage.

The output is deliberately a staging asset.  It contains official metadata and
the exact API response pages, but it does not download announcement documents
and it is not authorized for backtests.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd

try:
    import requests
except ModuleNotFoundError as exc:
    if exc.name != "requests":
        raise
    requests = None

SZSE_ENDPOINT = "https://www.szse.cn/api/disc/announcement/annList"
SSE_ENDPOINT = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
SZSE_PAGE_SIZE = 50
SSE_PAGE_SIZE = 100
SOURCE_NAME = "SSE_SZSE_OFFICIAL_ISSUER_ANNOUNCEMENT_APIS"
ASSET_ID = "CY-EXCHANGE-ISSUER-ANNOUNCEMENT-METADATA-V1"
SHANGHAI = ZoneInfo("Asia/Shanghai")
TAG_RE = re.compile(r"<[^>]+>")
SYMBOL_RE = re.compile(r"^(\d{6})\.(SH|SZ)$")


class CaptureError(RuntimeError):
    """Fail closed on request, schema, pagination, or identity anomalies."""


def require_requests() -> Any:
    """Return the optional HTTP dependency or fail before any network action."""

    if requests is None:
        raise CaptureError(
            "HTTP capture requires the optional 'requests' package; offline "
            "normalize/hash/seal/validate operations remain available"
        )
    return requests


@dataclass(frozen=True)
class QuerySpec:
    exchange: str
    symbol: str
    code: str
    start: str
    end: str
    year: int

    @property
    def query_id(self) -> str:
        return f"{self.exchange}-{self.code}-{self.year}"

    @property
    def page_size(self) -> int:
        return SZSE_PAGE_SIZE if self.exchange == "SZSE" else SSE_PAGE_SIZE


@dataclass(frozen=True)
class FetchedPage:
    body: bytes
    method: str
    url: str
    params: Mapping[str, Any] | None
    json_body: Mapping[str, Any] | None
    request_headers: Mapping[str, str]
    response_headers: Mapping[str, str]
    status_code: int
    retrieved_at: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def normalize_title(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", str(value or "")))).strip()


def validate_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


def normalize_symbol(value: Any) -> str:
    raw = str(value).strip().upper()
    if re.fullmatch(r"\d{6}", raw):
        if raw.startswith("6"):
            raw = f"{raw}.SH"
        elif raw.startswith(("0", "3")):
            raw = f"{raw}.SZ"
    match = SYMBOL_RE.fullmatch(raw)
    if not match:
        raise CaptureError(f"unsupported or malformed SSE/SZSE symbol: {value!r}")
    return raw


def causal_times(raw_value: Any) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    """Map source publication metadata to a conservative causal timestamp."""

    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        raise CaptureError("missing source publication time")
    try:
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            numeric = int(raw_value)
            unit = "ms" if abs(numeric) >= 10**11 else "s"
            aware = pd.to_datetime(numeric, unit=unit, utc=True).tz_convert(SHANGHAI)
            local = aware.tz_localize(None)
        else:
            parsed = pd.Timestamp(str(raw_value).strip())
            if parsed.tzinfo is not None:
                local = parsed.tz_convert(SHANGHAI).tz_localize(None)
            else:
                local = parsed
    except (TypeError, ValueError, OverflowError) as exc:
        raise CaptureError(f"invalid source publication time: {raw_value!r}") from exc
    if pd.isna(local):
        raise CaptureError(f"invalid source publication time: {raw_value!r}")
    local = pd.Timestamp(local)
    if local == local.normalize():
        return local, local + pd.Timedelta(days=1), "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"
    return local, local, "SOURCE_SECOND"


def exact_source_second(raw_value: Any, field: str) -> pd.Timestamp:
    """Parse a source timestamp that must carry time-to-the-second information."""

    if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
        raise CaptureError(f"missing {field}")
    if isinstance(raw_value, str):
        raw_text = raw_value.strip()
        if not re.search(r"(?:T|\s)\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$", raw_text):
            raise CaptureError(f"{field} must have source-second precision: {raw_value!r}")
    try:
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            numeric = int(raw_value)
            unit = "ms" if abs(numeric) >= 10**11 else "s"
            parsed = pd.to_datetime(numeric, unit=unit, utc=True).tz_convert(SHANGHAI)
        else:
            parsed = pd.Timestamp(str(raw_value).strip())
            if parsed.tzinfo is not None:
                parsed = parsed.tz_convert(SHANGHAI)
        if parsed.tzinfo is not None:
            parsed = parsed.tz_localize(None)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CaptureError(f"invalid {field}: {raw_value!r}") from exc
    if pd.isna(parsed):
        raise CaptureError(f"invalid {field}: {raw_value!r}")
    return pd.Timestamp(parsed)


def exact_source_date(raw_value: Any, field: str) -> pd.Timestamp:
    """Parse an official date field without borrowing semantics from another field."""

    raw_text = str(raw_value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_text):
        raise CaptureError(f"{field} must be an exact source date: {raw_value!r}")
    try:
        return pd.Timestamp(datetime.strptime(raw_text, "%Y-%m-%d").date())
    except ValueError as exc:
        raise CaptureError(f"invalid {field}: {raw_value!r}") from exc


def expected_pages(total: int, page_size: int) -> int:
    if total < 0 or page_size <= 0:
        raise CaptureError(f"invalid pagination values: {total=} {page_size=}")
    return math.ceil(total / page_size)


def build_request(
    exchange: str,
    code: str,
    start: str,
    end: str,
    page: int,
    *,
    cache_buster: str,
) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None, dict[str, str]]:
    user_agent = "Mozilla/5.0 (compatible; CYQ official metadata capture/1.0)"
    if exchange == "SZSE":
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.szse.cn",
            "Referer": f"https://www.szse.cn/disclosure/listed/notice/index.html?stock={code}",
            "User-Agent": user_agent,
            "X-Requested-With": "XMLHttpRequest",
        }
        body = {
            "pageSize": SZSE_PAGE_SIZE,
            "pageNum": page,
            "stock": [code],
            "channelCode": ["listedNotice_disc"],
            "seDate": [start, end],
        }
        return "POST", SZSE_ENDPOINT, {"random": cache_buster}, body, headers
    if exchange == "SSE":
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": (
                "https://www.sse.com.cn/assortment/stock/list/info/announcement/"
                f"index.shtml?productId={code}"
            ),
            "User-Agent": user_agent,
        }
        params: dict[str, Any] = {
            "isPagination": "true",
            "productId": code,
            "keyWord": "",
            "securityType": "0101",
            "reportType2": "",
            "reportType": "",
            "beginDate": start,
            "endDate": end,
            "pageHelp.pageSize": SSE_PAGE_SIZE,
            "pageHelp.pageCount": 50,
            "pageHelp.pageNo": page,
            "pageHelp.beginPage": page,
            "pageHelp.cacheSize": 1,
            "pageHelp.endPage": page,
            "_": cache_buster,
        }
        return "GET", SSE_ENDPOINT, params, None, headers
    raise CaptureError(f"unsupported exchange: {exchange}")


def _decode_object(body: bytes, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError(f"invalid JSON response for {context}") from exc
    if not isinstance(payload, dict):
        raise CaptureError(f"non-object JSON response for {context}")
    return payload


def fetch_page(
    session: Any,
    spec: QuerySpec,
    page: int,
    *,
    retries: int,
    timeout: float,
) -> FetchedPage:
    http = require_requests()
    last_error: Exception | None = None
    for attempt in range(retries):
        cache_buster = str(int(time.time() * 1000))
        method, url, params, json_body, headers = build_request(
            spec.exchange,
            spec.code,
            spec.start,
            spec.end,
            page,
            cache_buster=cache_buster,
        )
        try:
            response = session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=timeout,
            )
            retrieved_at = datetime.now(UTC).isoformat()
            response.raise_for_status()
            _decode_object(response.content, f"{spec.query_id} page {page}")
            return FetchedPage(
                body=response.content,
                method=method,
                url=url,
                params=params,
                json_body=json_body,
                request_headers=headers,
                response_headers=dict(response.headers),
                status_code=int(response.status_code),
                retrieved_at=retrieved_at,
            )
        except (http.RequestException, CaptureError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(0.5 * (attempt + 1))
    raise CaptureError(
        f"request failed after {retries} attempts for {spec.query_id} page {page}: {last_error}"
    )


def parse_page(
    exchange: str,
    body: bytes,
) -> tuple[int, int | None, list[dict[str, Any]]]:
    payload = _decode_object(body, exchange)
    if exchange == "SZSE":
        if "announceCount" not in payload or "data" not in payload:
            raise CaptureError("SZSE response missing announceCount/data")
        total = int(payload["announceCount"])
        records = payload["data"] or []
        reported_pages = None
    elif exchange == "SSE":
        page_help = payload.get("pageHelp")
        if not isinstance(page_help, dict) or "total" not in page_help or "data" not in page_help:
            raise CaptureError("SSE response missing pageHelp.total/data")
        total = int(page_help["total"])
        records = page_help["data"] or []
        raw_page_count = page_help.get("pageCount")
        reported_pages = int(raw_page_count) if raw_page_count not in (None, "") else None
    else:
        raise CaptureError(f"unsupported exchange: {exchange}")
    if total < 0 or not isinstance(records, list) or not all(isinstance(x, dict) for x in records):
        raise CaptureError(f"invalid {exchange} total/data schema")
    return total, reported_pages, records


def _szse_security(record: Mapping[str, Any], expected_code: str) -> tuple[str, str]:
    raw = record.get("secCode")
    raw_names = record.get("secName")
    parallel_names = raw_names if isinstance(raw_names, list) else []
    candidates: list[tuple[str, str]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if isinstance(item, dict):
                candidates.append(
                    (
                        str(item.get("code") or item.get("secCode") or "").strip(),
                        normalize_title(item.get("name") or item.get("secName") or ""),
                    )
                )
            else:
                parallel_name = parallel_names[index] if index < len(parallel_names) else ""
                candidates.append((str(item).strip(), normalize_title(parallel_name)))
    elif isinstance(raw, dict):
        candidates.append(
            (
                str(raw.get("code") or raw.get("secCode") or "").strip(),
                normalize_title(raw.get("name") or raw.get("secName") or ""),
            )
        )
    elif raw is not None:
        candidates.append((str(raw).strip(), ""))
    for code, name in candidates:
        if code == expected_code:
            return code, name
    raise CaptureError(f"SZSE record does not contain queried security {expected_code}")


def source_record_key(exchange: str, record: Mapping[str, Any]) -> str:
    if exchange == "SZSE":
        value = str(record.get("annId") or "").strip()
        if not value:
            raise CaptureError("SZSE record missing annId")
        return value
    if exchange == "SSE":
        explicit = str(record.get("BULLETIN_ID") or record.get("bulletinId") or "").strip()
        url = str(record.get("URL") or "").strip()
        value = explicit or url
        if not value:
            raise CaptureError("SSE record missing bulletin identity and URL")
        return value
    raise CaptureError(f"unsupported exchange: {exchange}")


def _document_url(exchange: str, raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if not value:
        raise CaptureError(f"{exchange} record missing document URL")
    if value.startswith(("https://", "http://")):
        return value
    if exchange == "SZSE":
        if not value.startswith("/"):
            value = f"/{value}"
        if value.startswith("/download/"):
            return f"https://disc.static.szse.cn{value}"
        return f"https://disc.static.szse.cn/download{value}"
    return urljoin("https://www.sse.com.cn/", value)


def normalize_record(
    spec: QuerySpec,
    record: Mapping[str, Any],
    *,
    page: int,
    raw_body_path: str,
    raw_body_sha256: str,
    retrieved_at: str,
) -> dict[str, Any]:
    record_key = source_record_key(spec.exchange, record)
    if spec.exchange == "SZSE":
        code, embedded_name = _szse_security(record, spec.code)
        title = normalize_title(record.get("title"))
        time_field = "publishTime"
        raw_time = record.get(time_field)
        document_url = _document_url(spec.exchange, record.get("attachPath"))
        raw_name = record.get("secName")
        fallback_name = "" if isinstance(raw_name, list) else normalize_title(raw_name)
        security_name = embedded_name or fallback_name
        announcement_id = f"SZSE-{record_key}"
        published_at, available_at, precision = causal_times(raw_time)
        source_query_date_field = "publishTime"
        source_query_date = published_at.normalize()
    else:
        code = str(record.get("SECURITY_CODE") or "").strip()
        if code != spec.code:
            raise CaptureError(f"SSE record security mismatch: {code!r} != {spec.code!r}")
        title = normalize_title(record.get("TITLE"))
        time_field = "ADDDATE"
        raw_time = record.get(time_field)
        document_url = _document_url(spec.exchange, record.get("URL"))
        security_name = normalize_title(record.get("SECURITY_NAME"))
        digest = sha256_bytes(record_key.encode("utf-8"))
        announcement_id = f"SSE-{digest}"
        published_at = exact_source_second(raw_time, "ADDDATE")
        available_at = published_at
        precision = "SOURCE_SECOND"
        source_query_date_field = "SSEDATE"
        source_query_date = exact_source_date(record.get("SSEDATE"), "SSEDATE")
    if not (
        date.fromisoformat(spec.start)
        <= source_query_date.date()
        <= date.fromisoformat(spec.end)
    ):
        raise CaptureError(
            f"source query date outside query interval for {spec.query_id}: "
            f"{source_query_date.date()} from {source_query_date_field}"
        )
    if not title:
        raise CaptureError(f"empty title for {spec.query_id} {record_key}")
    raw_record_json = canonical_json(record)
    announcement_key = f"{announcement_id}|{spec.symbol}"
    return {
        "announcement_key": announcement_key,
        "announcement_id": announcement_id,
        "source_record_key": record_key,
        "symbol": spec.symbol,
        "security_code": code,
        "security_name": security_name,
        "title": title,
        "published_at": published_at,
        "available_at": available_at,
        "precision": precision,
        "document_url": document_url,
        "exchange": spec.exchange,
        "source": SOURCE_NAME,
        "source_endpoint": SZSE_ENDPOINT if spec.exchange == "SZSE" else SSE_ENDPOINT,
        "source_publication_field": time_field,
        "source_publication_value": str(raw_time),
        "source_query_date_field": source_query_date_field,
        "source_query_date": source_query_date,
        "query_id": spec.query_id,
        "query_year": spec.year,
        "query_page": page,
        "retrieved_at": retrieved_at,
        "raw_body_path": raw_body_path,
        "raw_body_sha256": raw_body_sha256,
        "raw_record_sha256": sha256_bytes(raw_record_json.encode("utf-8")),
        "revision_history_complete": False,
        "strict_pit_eligible": False,
        "hard_valid": True,
    }


def _page_row(
    spec: QuerySpec,
    page: int,
    fetched: FetchedPage,
    *,
    raw_body_path: str,
    raw_body_sha256: str,
    total: int,
    reported_pages: int | None,
    record_count: int,
) -> dict[str, Any]:
    return {
        "query_id": spec.query_id,
        "exchange": spec.exchange,
        "symbol": spec.symbol,
        "security_code": spec.code,
        "query_year": spec.year,
        "query_start": spec.start,
        "query_end": spec.end,
        "page": page,
        "page_size": spec.page_size,
        "reported_total": total,
        "reported_page_count": reported_pages,
        "record_count": record_count,
        "request_method": fetched.method,
        "request_url": fetched.url,
        "request_params_json": canonical_json(fetched.params or {}),
        "request_body_json": canonical_json(fetched.json_body or {}),
        "request_headers_json": canonical_json(dict(fetched.request_headers)),
        "response_headers_json": canonical_json(dict(fetched.response_headers)),
        "retrieved_at": fetched.retrieved_at,
        "http_status": fetched.status_code,
        "raw_body_path": raw_body_path,
        "raw_body_sha256": raw_body_sha256,
        "raw_body_bytes": len(fetched.body),
    }


def capture_query(
    spec: QuerySpec,
    raw_root: Path,
    *,
    retries: int,
    timeout: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    page_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_appearance_count = 0
    work_parent = raw_root / ".query_work"
    work_parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=f"{spec.query_id}-", dir=work_parent))
    final_query_dir = raw_root / spec.exchange.lower() / spec.code / str(spec.year)
    try:
        http = require_requests()
        with http.Session() as session:
            first = fetch_page(session, spec, 1, retries=retries, timeout=timeout)
            first_total, first_reported_pages, first_records = parse_page(
                spec.exchange, first.body
            )
            page_count = expected_pages(first_total, spec.page_size)
            if first_reported_pages is not None:
                allowed = {page_count} if first_total else {0, 1}
                if first_reported_pages not in allowed:
                    raise CaptureError(
                        f"reported page count mismatch for {spec.query_id}: "
                        f"{first_reported_pages} not in {sorted(allowed)}"
                    )
            request_page_count = max(1, page_count)
            for page in range(1, request_page_count + 1):
                fetched = first if page == 1 else fetch_page(
                    session, spec, page, retries=retries, timeout=timeout
                )
                total, reported_pages, records = (
                    (first_total, first_reported_pages, first_records)
                    if page == 1
                    else parse_page(spec.exchange, fetched.body)
                )
                if total != first_total:
                    raise CaptureError(
                        f"source total changed during pagination for {spec.query_id}: "
                        f"{total} != {first_total}"
                    )
                if reported_pages is not None and first_reported_pages is not None:
                    if reported_pages != first_reported_pages:
                        raise CaptureError(f"source page count changed for {spec.query_id}")
                if len(records) > spec.page_size:
                    raise CaptureError(f"oversized page for {spec.query_id} page {page}")
                raw_sha = sha256_bytes(fetched.body)
                relative_path = (
                    Path("raw")
                    / spec.exchange.lower()
                    / spec.code
                    / str(spec.year)
                    / f"page_{page:04d}.json"
                )
                (work_dir / f"page_{page:04d}.json").write_bytes(fetched.body)
                for record in records:
                    key = source_record_key(spec.exchange, record)
                    if key in seen:
                        raise CaptureError(
                            f"duplicate source record within {spec.query_id}: {key}"
                        )
                    seen.add(key)
                    raw_appearance_count += 1
                    rows.append(
                        normalize_record(
                            spec,
                            record,
                            page=page,
                            raw_body_path=str(relative_path),
                            raw_body_sha256=raw_sha,
                            retrieved_at=fetched.retrieved_at,
                        )
                    )
                page_rows.append(
                    _page_row(
                        spec,
                        page,
                        fetched,
                        raw_body_path=str(relative_path),
                        raw_body_sha256=raw_sha,
                        total=total,
                        reported_pages=reported_pages,
                        record_count=len(records),
                    )
                )
        if (
            raw_appearance_count != first_total
            or len(seen) != first_total
            or len(rows) != raw_appearance_count
        ):
            raise CaptureError(
                f"pagination conservation failed for {spec.query_id}: "
                f"reported={first_total} raw_appearances={raw_appearance_count} "
                f"unique={len(seen)} canonical={len(rows)}"
            )
        if final_query_dir.exists():
            raise CaptureError(f"query output collision: {final_query_dir}")
        final_query_dir.parent.mkdir(parents=True, exist_ok=True)
        work_dir.replace(final_query_dir)
    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir)
    return {
        "spec": spec,
        "rows": rows,
        "page_rows": page_rows,
        "reported_total": first_total,
        "captured_raw_record_appearances": raw_appearance_count,
        "unique_source_keys": len(seen),
        "canonical_rows": len(rows),
    }


def load_universe(path: Path) -> list[str]:
    if not path.exists():
        raise CaptureError(f"universe parquet does not exist: {path}")
    frame = pd.read_parquet(path, columns=["symbol"])
    if "symbol" not in frame.columns or frame.empty:
        raise CaptureError("universe parquet must contain non-empty symbol column")
    if frame.symbol.isna().any():
        raise CaptureError("universe contains missing symbols")
    symbols = sorted({normalize_symbol(value) for value in frame.symbol.tolist()})
    return symbols


def build_query_specs(symbols: list[str], start: str, end: str) -> list[QuerySpec]:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if end_date < start_date:
        raise CaptureError("end date precedes start date")
    specs: list[QuerySpec] = []
    for symbol in symbols:
        match = SYMBOL_RE.fullmatch(symbol)
        if match is None:
            raise CaptureError(f"malformed normalized symbol: {symbol}")
        code, suffix = match.groups()
        exchange = "SSE" if suffix == "SH" else "SZSE"
        for year in range(start_date.year, end_date.year + 1):
            query_start = max(start_date, date(year, 1, 1))
            query_end = min(end_date, date(year, 12, 31))
            specs.append(
                QuerySpec(
                    exchange=exchange,
                    symbol=symbol,
                    code=code,
                    start=query_start.isoformat(),
                    end=query_end.isoformat(),
                    year=year,
                )
            )
    return specs


ANNOUNCEMENT_COLUMNS = [
    "announcement_key",
    "announcement_id",
    "source_record_key",
    "symbol",
    "security_code",
    "security_name",
    "title",
    "published_at",
    "available_at",
    "precision",
    "document_url",
    "exchange",
    "source",
    "source_endpoint",
    "source_publication_field",
    "source_publication_value",
    "source_query_date_field",
    "source_query_date",
    "query_id",
    "query_year",
    "query_page",
    "retrieved_at",
    "raw_body_path",
    "raw_body_sha256",
    "raw_record_sha256",
    "revision_history_complete",
    "strict_pit_eligible",
    "hard_valid",
]


REQUEST_PAGE_COLUMNS = [
    "query_id",
    "exchange",
    "symbol",
    "security_code",
    "query_year",
    "query_start",
    "query_end",
    "page",
    "page_size",
    "reported_total",
    "reported_page_count",
    "record_count",
    "request_method",
    "request_url",
    "request_params_json",
    "request_body_json",
    "request_headers_json",
    "response_headers_json",
    "retrieved_at",
    "http_status",
    "raw_body_path",
    "raw_body_sha256",
    "raw_body_bytes",
]


def run_capture(
    universe_parquet: Path,
    output_root: Path,
    start: str,
    end: str,
    *,
    workers: int = 4,
    retries: int = 4,
    timeout: float = 30.0,
) -> dict[str, Any]:
    start = validate_date(start)
    end = validate_date(end)
    if end < start:
        raise CaptureError("end date precedes start date")
    if workers <= 0 or retries <= 0 or timeout <= 0:
        raise CaptureError("workers, retries, and timeout must be positive")
    if output_root.exists() and not output_root.is_dir():
        raise CaptureError(f"capture root is not a directory: {output_root}")
    if output_root.exists() and any(output_root.iterdir()):
        raise CaptureError(f"refusing to overwrite non-empty capture root: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    capture_root = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.staging-", dir=output_root.parent)
    )
    raw_root = capture_root / "raw"
    symbols = load_universe(universe_parquet)
    specs = build_query_specs(symbols, start, end)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                capture_query,
                spec,
                raw_root,
                retries=retries,
                timeout=timeout,
            ): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                if isinstance(exc, CaptureError):
                    raise
                raise CaptureError(f"capture failed for {spec.query_id}: {exc}") from exc
    results.sort(key=lambda item: item["spec"].query_id)
    row_values = [row for result in results for row in result["rows"]]
    page_values = [row for result in results for row in result["page_rows"]]
    announcements = pd.DataFrame(row_values, columns=ANNOUNCEMENT_COLUMNS)
    request_pages = pd.DataFrame(page_values, columns=REQUEST_PAGE_COLUMNS)
    for column in ("published_at", "available_at", "source_query_date"):
        announcements[column] = pd.to_datetime(announcements[column])
    if not announcements.empty:
        duplicated = announcements.announcement_key.duplicated(keep=False)
        if duplicated.any():
            keys = announcements.loc[duplicated, "announcement_key"].unique().tolist()[:10]
            raise CaptureError(f"duplicate normalized announcement keys across queries: {keys}")
        if not bool(announcements.hard_valid.all()):
            raise CaptureError("normalized announcement contains hard-invalid rows")
        announcements = announcements.sort_values(
            ["available_at", "symbol", "announcement_id"], kind="mergesort"
        ).reset_index(drop=True)
    if request_pages.duplicated(["query_id", "page"]).any():
        raise CaptureError("duplicate request page lineage keys")
    request_pages = request_pages.sort_values(
        ["query_id", "page"], kind="mergesort"
    ).reset_index(drop=True)
    reported_total = sum(int(result["reported_total"]) for result in results)
    captured_raw_total = sum(
        int(result["captured_raw_record_appearances"]) for result in results
    )
    unique_total = sum(int(result["unique_source_keys"]) for result in results)
    canonical_total = sum(int(result["canonical_rows"]) for result in results)
    if not (
        reported_total
        == captured_raw_total
        == unique_total
        == canonical_total
        == len(announcements)
    ):
        raise CaptureError(
            "global conservation failed: "
            f"reported={reported_total} raw_appearances={captured_raw_total} "
            f"unique_within_queries={unique_total} canonical={canonical_total} "
            f"normalized={len(announcements)}"
        )
    inventory = request_pages[
        [
            "query_id",
            "page",
            "raw_body_path",
            "raw_body_sha256",
            "record_count",
        ]
    ].to_dict("records")
    snapshot_id = f"exchange-announcement-{sha256_bytes(canonical_json(inventory).encode('utf-8'))}"
    announcements.insert(0, "snapshot_id", snapshot_id)
    work_parent = raw_root / ".query_work"
    if work_parent.exists():
        work_parent.rmdir()
    announcements_path = capture_root / "announcements.parquet"
    request_pages_path = capture_root / "request_pages.parquet"
    announcements.to_parquet(announcements_path, index=False, compression="zstd")
    request_pages.to_parquet(request_pages_path, index=False, compression="zstd")
    query_audit = [
        {
            "query_id": result["spec"].query_id,
            "exchange": result["spec"].exchange,
            "symbol": result["spec"].symbol,
            "start": result["spec"].start,
            "end": result["spec"].end,
            "reported_total": result["reported_total"],
            "captured_raw_record_appearances": result[
                "captured_raw_record_appearances"
            ],
            "unique_source_keys": result["unique_source_keys"],
            "canonical_rows": result["canonical_rows"],
            "pages": len(result["page_rows"]),
            "raw_appearances_conserve": (
                result["reported_total"]
                == result["captured_raw_record_appearances"]
                == result["unique_source_keys"]
                == result["canonical_rows"]
            ),
        }
        for result in results
    ]
    audit = {
        "asset_id": ASSET_ID,
        "status": "PASS",
        "snapshot_id": snapshot_id,
        "capture_start": start,
        "capture_end": end,
        "universe_symbols": len(symbols),
        "symbol_year_queries": len(specs),
        "request_pages": len(request_pages),
        "reported_records": reported_total,
        "captured_raw_record_appearances": captured_raw_total,
        "unique_source_keys_within_queries": unique_total,
        "canonical_announcements": canonical_total,
        "unique_announcement_keys": int(announcements.announcement_key.nunique()),
        "date_only_conservative_rows": int(
            announcements.precision.eq("SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY").sum()
        ),
        "available_before_published_rows": int(
            announcements.available_at.lt(announcements.published_at).sum()
        ),
        "all_query_raw_appearances_conserve": all(
            row["raw_appearances_conserve"] for row in query_audit
        ),
        "sse_available_before_query_date_rows": int(
            announcements.loc[announcements.exchange.eq("SSE"), "available_at"].lt(
                announcements.loc[
                    announcements.exchange.eq("SSE"), "source_query_date"
                ]
            ).sum()
        ),
        "sse_available_on_query_date_rows": int(
            announcements.loc[announcements.exchange.eq("SSE"), "available_at"]
            .dt.normalize()
            .eq(
                announcements.loc[
                    announcements.exchange.eq("SSE"), "source_query_date"
                ]
            )
            .sum()
        ),
        "sse_available_after_query_date_rows": int(
            announcements.loc[announcements.exchange.eq("SSE"), "available_at"]
            .dt.normalize()
            .gt(
                announcements.loc[
                    announcements.exchange.eq("SSE"), "source_query_date"
                ]
            )
            .sum()
        ),
        "metadata_only": True,
        "documents_downloaded": 0,
        "queries": query_audit,
    }
    if (
        not audit["all_query_raw_appearances_conserve"]
        or audit["available_before_published_rows"] != 0
        or audit["unique_announcement_keys"] != canonical_total
    ):
        raise CaptureError(f"final audit failed: {audit}")
    audit_path = capture_root / "audit.json"
    write_json(audit_path, audit)
    raw_files = sorted((capture_root / "raw").rglob("*.json"))
    manifest = {
        "asset_id": ASSET_ID,
        "name": "Official SSE/SZSE issuer announcement metadata staging snapshot",
        "kind": "issuer_announcement_metadata_staging",
        "status": "STAGING",
        "staging": True,
        "backtest_authorized": False,
        "strict_archival_pit_ready": False,
        "metadata_only": True,
        "documents_downloaded": False,
        "location": str(output_root),
        "snapshot_id": snapshot_id,
        "coverage": {"start": start, "end": end},
        "universe_source": str(universe_parquet),
        "source": SOURCE_NAME,
        "source_endpoints": {"SZSE": SZSE_ENDPOINT, "SSE": SSE_ENDPOINT},
        "query_grain": "symbol x natural year",
        "record_counts": {
            "reported_raw_record_appearances": reported_total,
            "captured_raw_record_appearances": captured_raw_total,
            "canonical_announcements": canonical_total,
        },
        "source_field_semantics": {
            "SSE": {
                "query_membership_date": "SSEDATE; must lie inside the requested interval",
                "published_and_available_at": (
                    "ADDDATE at mandatory source-second precision; it can precede or "
                    "follow SSEDATE because late-added/backfilled records retain their "
                    "official query/display date"
                ),
                "ordering": (
                    "no ordering or maximum-gap constraint between ADDDATE and SSEDATE; "
                    "the fields have independent official semantics"
                ),
            },
            "SZSE": {
                "query_membership_date": "calendar date derived from publishTime",
                "published_and_available_at": (
                    "publishTime; date-only/midnight values become available next day"
                ),
            },
        },
        "causality": {
            "SSE_ADDDATE": "available at the mandatory official source second",
            "SSE_SSEDATE": "query membership only; never substitutes for available_at",
            "SZSE_intraday_publishTime": "available at the official source second",
            "SZSE_date_only_or_midnight_publishTime": "available next calendar day",
            "unknown_or_invalid_time": "fail closed",
        },
        "lineage": {
            "every_successful_response_body_preserved": True,
            "request_headers_and_parameters_preserved": True,
            "response_headers_and_retrieved_at_preserved": True,
            "raw_body_sha256_preserved": True,
            "raw_record_sha256_preserved": True,
        },
        "limitations": [
            "metadata only; referenced announcement documents have not been downloaded",
            "historical API retrieval does not prove complete source revision history",
            (
                "SSE ADDDATE can precede or follow SSEDATE, including late-added/backfilled "
                "records; SSEDATE controls query membership while ADDDATE alone controls "
                "availability"
            ),
            "this staging snapshot is not registered or authorized for backtests",
        ],
        "blocked_uses": [
            "backtesting, model fitting, signal gating, execution, or sizing",
            "claiming document contents from title metadata alone",
            "assuming absence in this snapshot proves absence of issuer risk",
        ],
        "hashes": {
            "universe_parquet": sha256_file(universe_parquet),
            "announcements_parquet": sha256_file(announcements_path),
            "request_pages_parquet": sha256_file(request_pages_path),
            "audit_json": sha256_file(audit_path),
            "raw_page_inventory_sha256": sha256_bytes(canonical_json(inventory).encode("utf-8")),
        },
        "raw_page_files": len(raw_files),
        "activation_gates": {
            "pagination_reported_totals_equal_raw_record_appearances": True,
            "canonical_count_equals_raw_record_appearances": True,
            "source_query_dates_within_requested_intervals": True,
            "SSE_ADDDATE_second_precision_validated": True,
            "source_keys_unique_within_each_query": True,
            "normalized_announcement_keys_unique": True,
            "all_raw_pages_preserved_and_hashed": True,
            "documents_captured_and_hashed": False,
            "taxonomy_frozen": False,
            "registry_entry_and_validator_pass": False,
            "separate_experiment_protocol_frozen_before_outcomes": False,
        },
    }
    manifest_path = capture_root / "source_manifest.json"
    write_json(manifest_path, manifest)
    if output_root.exists():
        output_root.rmdir()
    capture_root.replace(output_root)
    return {"manifest": manifest, "audit": audit}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Run with the repository/system Python environment that provides requests "
            "and a pandas Parquet engine; the minimal project .venv may not include requests."
        ),
    )
    parser.add_argument("--universe-parquet", type=Path, required=True)
    parser.add_argument("--start", type=validate_date, required=True)
    parser.add_argument("--end", type=validate_date, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    result = run_capture(
        args.universe_parquet,
        args.output_root,
        args.start,
        args.end,
        workers=args.workers,
        retries=args.retries,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
