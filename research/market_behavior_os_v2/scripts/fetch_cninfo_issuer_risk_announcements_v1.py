#!/usr/bin/env python3
"""Capture a frozen CNINFO issuer-risk announcement metadata snapshot."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
SOURCE = "CNINFO_OFFICIAL_HISTORICAL_ANNOUNCEMENT_QUERY"
ASSET_ID = "CY-034-CNINFO-ISSUER-RISK-ANNOUNCEMENTS-2018-2021-V1"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_KEYWORDS = (
    "风险警示",
    "违规担保",
    "资金占用整改",
    "资金占用事项",
    "资金占用风险",
    "立案调查",
    "行政处罚决定",
    "无法表示意见",
    "否定意见内部控制",
    "保留意见审计报告",
)
TAG_RE = re.compile(r"<[^>]+>")


class CaptureError(RuntimeError):
    """Fail closed on source, pagination, schema, or identity anomalies."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", str(value)))).strip()


def causal_times(raw_milliseconds: int) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    if raw_milliseconds is None or int(raw_milliseconds) <= 0:
        raise CaptureError("missing announcementTime")
    aware = pd.to_datetime(int(raw_milliseconds), unit="ms", utc=True).tz_convert(SHANGHAI)
    local = aware.tz_localize(None)
    if local == local.normalize():
        return (
            local,
            local + pd.Timedelta(days=1),
            "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY",
        )
    return local, local, "SOURCE_SECOND"


def symbol_from_code(code: str) -> str:
    value = str(code).zfill(6)
    if value.startswith("6"):
        return f"{value}.SH"
    if value.startswith(("0", "3")):
        return f"{value}.SZ"
    if value.startswith(("4", "8")):
        return f"{value}.BJ"
    return f"{value}.UNKNOWN"


def request_payload(keyword: str, start: str, end: str, page: int) -> dict[str, str]:
    return {
        "pageNum": str(page),
        "pageSize": "30",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": "",
        "searchkey": keyword,
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{start}~{end}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }


def expected_pages(total: int, page_size: int = 30) -> int:
    return (int(total) + page_size - 1) // page_size


def fetch_page(
    session: requests.Session,
    keyword: str,
    start: str,
    end: str,
    page: int,
) -> requests.Response:
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
        "User-Agent": "Mozilla/5.0 (compatible; CYQ causal research capture/1.0)",
        "X-Requested-With": "XMLHttpRequest",
    }
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = session.post(
                ENDPOINT,
                data=request_payload(keyword, start, end, page),
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or "announcements" not in payload:
                raise CaptureError("CNINFO response schema missing announcements")
            return response
        except (requests.RequestException, ValueError, CaptureError) as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(0.5 * (attempt + 1))
    raise CaptureError(f"CNINFO request failed for {keyword=} {page=}: {last_error}")


def normalize_record(
    record: dict[str, Any],
    *,
    keyword: str,
    query_index: int,
    page: int,
    raw_response_sha256: str,
    fetched_at: str,
) -> dict[str, Any]:
    code = str(record.get("secCode") or "").strip()
    announcement_id = str(record.get("announcementId") or "").strip()
    title = normalize_title(str(record.get("announcementTitle") or ""))
    announcement_at, available_at, precision = causal_times(record.get("announcementTime"))
    adjunct_url = str(record.get("adjunctUrl") or "").lstrip("/")
    hard_valid = bool(
        re.fullmatch(r"\d{6}", code)
        and announcement_id
        and title
        and adjunct_url
        and available_at >= announcement_at
    )
    return {
        "announcement_id": announcement_id,
        "security_code": code,
        "symbol": symbol_from_code(code),
        "security_name": normalize_title(str(record.get("secName") or "")),
        "org_id": str(record.get("orgId") or ""),
        "announcement_title": title,
        "announcement_at": announcement_at,
        "available_at": available_at,
        "available_at_precision": precision,
        "adjunct_url": f"https://static.cninfo.com.cn/{adjunct_url}",
        "adjunct_size_kb": pd.to_numeric(record.get("adjunctSize"), errors="coerce"),
        "adjunct_type": str(record.get("adjunctType") or ""),
        "column_id": str(record.get("columnId") or ""),
        "page_column": str(record.get("pageColumn") or ""),
        "announcement_type": str(record.get("announcementType") or ""),
        "query_keyword": keyword,
        "query_index": query_index,
        "query_page": page,
        "raw_response_sha256": raw_response_sha256,
        "source": SOURCE,
        "source_endpoint": ENDPOINT,
        "fetched_at": fetched_at,
        "revision_history_complete": False,
        "strict_pit_eligible": False,
        "pit_grade": "B",
        "hard_valid": hard_valid,
    }


def validate_date(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return parsed.isoformat()


def run_capture(
    output_root: Path,
    start: str,
    end: str,
    keywords: tuple[str, ...],
) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise CaptureError(f"refusing to overwrite non-empty capture root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    raw_root = output_root / "raw"
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    raw_inventory: list[dict[str, Any]] = []
    query_audit: dict[str, Any] = {}
    with requests.Session() as session:
        for query_index, keyword in enumerate(keywords):
            first = fetch_page(session, keyword, start, end, 1)
            first_payload = first.json()
            total = int(first_payload.get("totalAnnouncement") or 0)
            # CNINFO's totalpages has returned a floor value for non-multiples of 30.
            # Bind pagination to the independently reported record count instead.
            total_pages = expected_pages(total)
            if total_pages < 0 or total_pages > 10000:
                raise CaptureError(f"implausible pagination for {keyword}: {total_pages}")
            seen_in_query: set[str] = set()
            query_records = 0
            for page in range(1, total_pages + 1):
                response = first if page == 1 else fetch_page(session, keyword, start, end, page)
                raw = response.content
                raw_sha = sha256_bytes(raw)
                raw_path = raw_root / f"query_{query_index:02d}" / f"page_{page:04d}.json"
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(raw)
                payload = response.json()
                page_total = int(payload.get("totalAnnouncement") or 0)
                if page_total != total:
                    raise CaptureError(
                        f"source changed during pagination for {keyword}: {page_total} != {total}"
                    )
                announcements = payload.get("announcements") or []
                if not isinstance(announcements, list):
                    raise CaptureError(f"announcements is not a list for {keyword} page {page}")
                raw_inventory.append(
                    {
                        "path": str(raw_path.relative_to(output_root)),
                        "sha256": raw_sha,
                        "bytes": len(raw),
                        "keyword": keyword,
                        "page": page,
                        "records": len(announcements),
                    }
                )
                for record in announcements:
                    item = normalize_record(
                        record,
                        keyword=keyword,
                        query_index=query_index,
                        page=page,
                        raw_response_sha256=raw_sha,
                        fetched_at=fetched_at,
                    )
                    if item["announcement_id"] in seen_in_query:
                        raise CaptureError(
                            f"duplicate announcement within query {keyword}: {item['announcement_id']}"
                        )
                    seen_in_query.add(item["announcement_id"])
                    rows.append(item)
                    query_records += 1
            if query_records != total:
                raise CaptureError(
                    f"pagination count mismatch for {keyword}: {query_records} != {total}"
                )
            query_audit[keyword] = {
                "total_announcements": total,
                "pages": total_pages,
                "captured_records": query_records,
            }
    hits = pd.DataFrame(rows)
    if hits.empty:
        raise CaptureError("empty issuer-risk announcement capture")
    if not bool(hits.hard_valid.all()):
        bad = hits.loc[~hits.hard_valid].head(10).to_dict("records")
        raise CaptureError(f"invalid normalized announcement rows: {bad}")
    identity_columns = [
        "security_code",
        "symbol",
        "security_name",
        "org_id",
        "announcement_title",
        "announcement_at",
        "available_at",
        "available_at_precision",
        "adjunct_url",
        "adjunct_size_kb",
        "adjunct_type",
        "column_id",
        "page_column",
        "announcement_type",
        "source",
        "source_endpoint",
        "fetched_at",
        "revision_history_complete",
        "strict_pit_eligible",
        "pit_grade",
        "hard_valid",
    ]
    disagreement = (
        hits.groupby("announcement_id", dropna=False)[identity_columns]
        .nunique(dropna=False)
        .gt(1)
        .any(axis=1)
    )
    if disagreement.any():
        raise CaptureError(
            f"cross-query identity disagreement: {disagreement.loc[disagreement].index.tolist()[:10]}"
        )
    announcements = hits.drop_duplicates("announcement_id", keep="first").copy()
    matched = hits.groupby("announcement_id").query_keyword.agg(
        lambda values: "|".join(sorted(set(map(str, values))))
    )
    announcements["matched_keywords"] = announcements.announcement_id.map(matched)
    announcements = announcements[
        ["announcement_id", *identity_columns, "matched_keywords"]
    ].sort_values(["available_at", "security_code", "announcement_id"], kind="mergesort")
    hits = hits.sort_values(
        ["query_index", "query_page", "announcement_id"], kind="mergesort"
    ).reset_index(drop=True)
    announcements = announcements.reset_index(drop=True)
    announcements_path = output_root / "announcements.parquet"
    hits_path = output_root / "query_hits.parquet"
    announcements.to_parquet(announcements_path, index=False, compression="zstd")
    hits.to_parquet(hits_path, index=False, compression="zstd")
    inventory_value = json.dumps(raw_inventory, ensure_ascii=False, sort_keys=True).encode("utf-8")
    snapshot_id = f"cninfo-issuer-risk-{sha256_bytes(inventory_value)}"
    audit = {
        "asset_id": ASSET_ID,
        "status": "PASS",
        "source": SOURCE,
        "capture_start": start,
        "capture_end": end,
        "fetched_at": fetched_at,
        "snapshot_id": snapshot_id,
        "queries": query_audit,
        "query_hit_rows": len(hits),
        "unique_announcements": len(announcements),
        "unique_securities": int(announcements.security_code.nunique()),
        "duplicate_query_hits": len(hits) - len(announcements),
        "hard_valid_rows": int(announcements.hard_valid.sum()),
        "date_only_available_at_rows": int(
            announcements.available_at_precision.eq(
                "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"
            ).sum()
        ),
        "source_time_after_available_count": int(
            announcements.announcement_at.gt(announcements.available_at).sum()
        ),
        "strict_pit_eligible_rows": int(announcements.strict_pit_eligible.sum()),
        "raw_response_files": len(raw_inventory),
    }
    if (
        audit["hard_valid_rows"] != audit["unique_announcements"]
        or audit["source_time_after_available_count"] != 0
        or audit["query_hit_rows"] != sum(v["captured_records"] for v in query_audit.values())
    ):
        raise CaptureError(f"capture audit failed: {audit}")
    write_json(output_root / "raw_inventory.json", raw_inventory)
    write_json(output_root / "audit.json", audit)
    manifest = {
        "asset_id": ASSET_ID,
        "name": "CNINFO issuer-risk announcement metadata snapshot 2018-2021",
        "kind": "issuer_risk_announcements_pit",
        "status": "PASS",
        "pit_grade": "B",
        "strict_archival_pit_ready": False,
        "backtest_authorized": False,
        "location": str(output_root),
        "snapshot_id": snapshot_id,
        "coverage": {"start": start, "end": end},
        "source": SOURCE,
        "source_endpoint": ENDPOINT,
        "schema_and_units": (
            "announcement_id, security_code/symbol, official title, announcement_at, "
            "causal available_at, source precision, official PDF URL, source response lineage"
        ),
        "causality": {
            "intraday_source_time": "available at the published source second",
            "midnight_source_time": "treated as date-only and available next calendar day",
            "future_event_use": False,
            "missing_or_invalid": "fail closed",
        },
        "allowed_uses": [
            "candidate-level causal research after registry activation",
            "issuer-risk event taxonomy development with outcome quarantine",
        ],
        "blocked_uses": [
            "strict PIT-A claims",
            "live execution or sizing",
            "assuming absence of a keyword hit proves absence of issuer risk",
            "use before registry admission and activation gates pass",
        ],
        "limitations": [
            "current historical query snapshot does not preserve complete source revision history",
            "keyword retrieval is not a complete financial-disclosure ontology",
            "titles require a separately frozen deterministic high-precision classifier",
        ],
        "hashes": {
            "announcements_parquet": sha256_file(announcements_path),
            "query_hits_parquet": sha256_file(hits_path),
            "raw_inventory_json": sha256_file(output_root / "raw_inventory.json"),
            "audit_json": sha256_file(output_root / "audit.json"),
        },
        "activation_gates": {
            "all_query_pages_preserved_and_hashed": True,
            "pagination_counts_conserve": True,
            "announcement_id_identity_consistent_across_queries": True,
            "all_rows_hard_valid": True,
            "date_only_timestamps_conservatively_delayed": True,
            "registry_entry_and_validator_pass": False,
            "separate_experiment_protocol_frozen_before_outcomes": False,
        },
    }
    write_json(output_root / "asset_manifest.json", manifest)
    return {"manifest": manifest, "audit": audit}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", type=validate_date, default="2018-01-01")
    parser.add_argument("--end", type=validate_date, default="2021-12-31")
    parser.add_argument("--keywords", nargs="*", default=list(DEFAULT_KEYWORDS))
    args = parser.parse_args()
    if args.end < args.start:
        raise CaptureError("end date precedes start date")
    result = run_capture(args.output_root, args.start, args.end, tuple(args.keywords))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
