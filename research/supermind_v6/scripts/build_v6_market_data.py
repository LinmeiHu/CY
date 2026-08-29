from __future__ import annotations

import argparse
import io
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import akshare as ak
import numpy as np
import pandas as pd
import requests
from v6_data_common import (
    CONTRACT_VERSION,
    DATA_ROOT,
    MANIFEST_PATH,
    RESEARCH_ROOT,
    STRATEGY_PATH,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_parquet,
    canonical_json_bytes,
    canonical_symbol,
    directory_bytes,
    exchange_for,
    parse_strategy_pool,
    sha256_bytes,
    sha256_file,
    strategy_sha256,
    universe_sha256,
)

TZ = ZoneInfo("Asia/Shanghai")
EASTMONEY_DAILY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
SSE_MASTER_URL = "https://query.sse.com.cn/commonSoaQuery.do"
SZSE_MASTER_URL = "https://fund.szse.cn/api/report/ShowReport"
LOCAL_CALENDAR = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the isolated V6 daily data subset")
    parser.add_argument("--end-date", required=True, help="last complete session, YYYYMMDD")
    parser.add_argument(
        "--start-date",
        default="19900101",
        help="provider request lower bound; listing rules still apply",
    )
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--retry-delay", type=float, default=0.75)
    parser.add_argument("--force", action="store_true", help="refresh matching raw snapshots")
    parser.add_argument(
        "--daily-cache-only",
        action="store_true",
        help="rebuild only ETF partitions with valid cached raw and qfq responses",
    )
    return parser.parse_args()


def capture_timestamp() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def completed_bar_available_at(value: date) -> str:
    next_midnight = datetime.combine(value + timedelta(days=1), datetime.min.time(), tzinfo=TZ)
    return next_midnight.isoformat()


def request_bytes(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str] | None,
    retries: int,
    retry_delay: float,
) -> tuple[bytes, str]:
    errors: list[str] = []
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            return response.content, response.url
        except requests.RequestException as exc:
            errors.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")
            if attempt + 1 < retries:
                time.sleep(retry_delay * (2**attempt))
    raise RuntimeError("; ".join(errors))


def request_identity(url: str, params: dict[str, str]) -> str:
    return sha256_bytes(canonical_json_bytes({"url": url, "params": params}))


def cached_request(
    session: requests.Session,
    *,
    response_path: Path,
    url: str,
    params: dict[str, str],
    headers: dict[str, str] | None,
    retries: int,
    retry_delay: float,
    force: bool,
    network_enabled: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    metadata_path = response_path.with_suffix(response_path.suffix + ".request.json")
    identity = request_identity(url, params)
    if not force and response_path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        content = response_path.read_bytes()
        if metadata.get("request_identity") == identity and metadata.get(
            "response_sha256"
        ) == sha256_bytes(content):
            metadata["cache_hit"] = True
            return content, metadata

    if not network_enabled:
        raise FileNotFoundError(f"no valid cached response for {response_path}")

    content, resolved_url = request_bytes(
        session,
        url,
        params=params,
        headers=headers,
        retries=retries,
        retry_delay=retry_delay,
    )
    metadata = {
        "capture_at": capture_timestamp(),
        "request_identity": identity,
        "request_params": params,
        "requested_url": url,
        "resolved_url": resolved_url,
        "response_bytes": len(content),
        "response_sha256": sha256_bytes(content),
        "cache_hit": False,
    }
    atomic_write_bytes(response_path, content)
    atomic_write_json(metadata_path, metadata)
    return content, metadata


def build_security_master(
    session: requests.Session,
    pool: list[str],
    *,
    retries: int,
    retry_delay: float,
    force: bool,
    snapshot_id: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw_dir = DATA_ROOT / "raw" / "security_master"
    sse_params = {
        "isPagination": "true",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "pagecache": "false",
        "sqlId": "FUND_LIST",
        "fundType": "00",
        "subClass": "01,02,03,04,06,08,09,31,32,33,34,35,36,37,38",
    }
    sse_bytes, sse_meta = cached_request(
        session,
        response_path=raw_dir / "sse_fund_list.json",
        url=SSE_MASTER_URL,
        params=sse_params,
        headers={"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"},
        retries=retries,
        retry_delay=retry_delay,
        force=force,
    )
    sse_payload = json.loads(sse_bytes)
    sse_rows = sse_payload.get("result") or []

    szse_params = {
        "SHOWTYPE": "xlsx",
        "CATALOGID": "1000_lf",
        "TABKEY": "tab1",
        "random": "0.07610353191740105",
    }
    szse_bytes, szse_meta = cached_request(
        session,
        response_path=raw_dir / "szse_fund_list.xlsx",
        url=SZSE_MASTER_URL,
        params=szse_params,
        headers={
            "Referer": "https://fund.szse.cn/marketdata/fundslist/index.html",
            "User-Agent": "Mozilla/5.0",
        },
        retries=retries,
        retry_delay=retry_delay,
        force=force,
    )
    szse_frame = pd.read_excel(io.BytesIO(szse_bytes), engine="openpyxl", dtype={"基金代码": str})

    capture_at = capture_timestamp()
    normalized: list[dict[str, Any]] = []
    for item in sse_rows:
        raw_code = str(item.get("fundCode", "")).zfill(6)
        if raw_code not in pool:
            continue
        normalized.append(
            {
                "raw_code": raw_code,
                "symbol": canonical_symbol(raw_code),
                "exchange": "SH",
                "name": str(item.get("secNameFull") or item.get("fundAbbr") or ""),
                "list_date": pd.to_datetime(item.get("listingDate"), format="%Y%m%d").date(),
                "delist_date": pd.NaT,
                "security_type": "ETF",
                "status_as_of_capture": "listed",
                "list_date_source": "Shanghai Stock Exchange FUND_LIST",
                "source_endpoint": SSE_MASTER_URL,
                "capture_at": capture_at,
                "snapshot_id": snapshot_id,
            }
        )
    szse_frame["基金代码"] = szse_frame["基金代码"].astype(str).str.zfill(6)
    for _, item in szse_frame.iterrows():
        raw_code = item["基金代码"]
        if raw_code not in pool:
            continue
        normalized.append(
            {
                "raw_code": raw_code,
                "symbol": canonical_symbol(raw_code),
                "exchange": "SZ",
                "name": str(item.get("基金简称") or ""),
                "list_date": pd.to_datetime(item.get("上市日期")).date(),
                "delist_date": pd.NaT,
                "security_type": "ETF",
                "status_as_of_capture": "listed",
                "list_date_source": "Shenzhen Stock Exchange ETF fund list",
                "source_endpoint": SZSE_MASTER_URL,
                "capture_at": capture_at,
                "snapshot_id": snapshot_id,
            }
        )

    frame = pd.DataFrame(normalized).sort_values("raw_code").reset_index(drop=True)
    if frame["raw_code"].duplicated().any():
        duplicates = frame.loc[frame["raw_code"].duplicated(False), "raw_code"].tolist()
        raise ValueError(f"security master has duplicate pool codes: {duplicates}")
    missing = sorted(set(pool) - set(frame["raw_code"]))
    if missing:
        raise ValueError(f"security master missing pool codes: {missing}")
    atomic_write_parquet(frame, DATA_ROOT / "metadata" / "etf_security_master.parquet")
    source = {
        "sse": {key: value for key, value in sse_meta.items() if key != "request_params"},
        "szse": {key: value for key, value in szse_meta.items() if key != "request_params"},
    }
    return frame, source


def daily_params(raw_code: str, start_date: str, end_date: str, adjustment: str) -> dict[str, str]:
    market_id = "1" if exchange_for(raw_code) == "SH" else "0"
    return {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": adjustment,
        "beg": start_date,
        "end": end_date,
        "secid": f"{market_id}.{raw_code}",
    }


def parse_daily_payload(content: bytes, *, prefix: str) -> pd.DataFrame:
    payload = json.loads(content)
    data = payload.get("data")
    if not data or not data.get("klines"):
        return pd.DataFrame()
    rows = [item.split(",") for item in data["klines"]]
    if any(len(row) < 11 for row in rows):
        raise ValueError("Eastmoney kline response has fewer than 11 fields")
    frame = pd.DataFrame(
        [row[:11] for row in rows],
        columns=[
            "trade_date",
            "open",
            "close",
            "high",
            "low",
            "volume",
            "amount",
            "amplitude_pct",
            "change_pct",
            "change",
            "turnover_rate_pct",
        ],
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    for column in frame.columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.rename(columns={column: f"{prefix}_{column}" for column in frame.columns[1:]})


def normalize_daily(
    raw_code: str,
    raw_frame: pd.DataFrame,
    qfq_frame: pd.DataFrame,
    *,
    list_date: date,
    snapshot_id: str,
    raw_sha256: str,
    qfq_sha256: str,
) -> pd.DataFrame:
    if raw_frame.empty or qfq_frame.empty:
        return pd.DataFrame()
    frame = raw_frame.merge(qfq_frame, on="trade_date", how="outer", validate="one_to_one")
    frame = frame.sort_values("trade_date").reset_index(drop=True)
    frame.insert(1, "symbol", canonical_symbol(raw_code))
    frame.insert(2, "raw_code", raw_code)
    frame.insert(3, "exchange", exchange_for(raw_code))

    finite_columns = [
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "qfq_open",
        "qfq_high",
        "qfq_low",
        "qfq_close",
        "raw_volume",
        "raw_amount",
    ]
    finite = np.isfinite(frame[finite_columns]).all(axis=1)
    price_columns = [
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "qfq_open",
        "qfq_high",
        "qfq_low",
        "qfq_close",
    ]
    positive_price = (frame[price_columns] > 0).all(axis=1)
    before_listing = frame["trade_date"] < list_date
    nonpositive_volume = (frame["raw_volume"] <= 0) | (frame["raw_amount"] <= 0)
    frame["row_status"] = "VALID"
    frame.loc[~finite | ~positive_price, "row_status"] = "NONFINITE"
    frame.loc[finite & positive_price & nonpositive_volume, "row_status"] = "NONPOSITIVE_VOLUME"
    frame.loc[before_listing, "row_status"] = "NOT_LISTED"

    frame = frame.rename(
        columns={
            "qfq_open": "pre_adj_open",
            "qfq_high": "pre_adj_high",
            "qfq_low": "pre_adj_low",
            "qfq_close": "pre_adj_close",
            "raw_volume": "volume_raw",
            "raw_amount": "amount_cny",
        }
    )
    frame["adj_factor_close_ratio"] = frame["pre_adj_close"] / frame["raw_close"]
    frame["volume_unit"] = "lot_100_shares"
    frame["volume_shares"] = frame["volume_raw"] * 100.0
    frame["available_at"] = frame["trade_date"].map(completed_bar_available_at)
    frame["source"] = "Eastmoney ETF kline via direct AKShare-compatible endpoint"
    frame["snapshot_id"] = snapshot_id
    frame["source_raw_sha256"] = raw_sha256
    frame["source_qfq_sha256"] = qfq_sha256
    frame["adjustment_status"] = "provider_qfq_supermind_equivalence_unverified"
    keep = [
        "trade_date",
        "symbol",
        "raw_code",
        "exchange",
        "row_status",
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "pre_adj_open",
        "pre_adj_high",
        "pre_adj_low",
        "pre_adj_close",
        "adj_factor_close_ratio",
        "volume_raw",
        "volume_unit",
        "volume_shares",
        "amount_cny",
        "raw_turnover_rate_pct",
        "available_at",
        "source",
        "snapshot_id",
        "source_raw_sha256",
        "source_qfq_sha256",
        "adjustment_status",
    ]
    return frame[keep]


def build_etf_daily(
    session: requests.Session,
    pool: list[str],
    master: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    retries: int,
    retry_delay: float,
    force: bool,
    snapshot_id: str,
    network_enabled: bool,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    master_by_code = master.set_index("raw_code")
    coverage: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    raw_dir = DATA_ROOT / "raw" / "etf_daily"
    output_dir = DATA_ROOT / "daily"
    for index, raw_code in enumerate(pool, start=1):
        print(f"DAILY {index:03d}/{len(pool):03d} {raw_code}", flush=True)
        responses: dict[str, tuple[bytes, dict[str, Any]]] = {}
        try:
            for basis, adjustment in [("raw", "0"), ("qfq", "1")]:
                params = daily_params(raw_code, start_date, end_date, adjustment)
                responses[basis] = cached_request(
                    session,
                    response_path=raw_dir / raw_code / f"{basis}.json",
                    url=EASTMONEY_DAILY_URL,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0"},
                    retries=retries,
                    retry_delay=retry_delay,
                    force=force,
                    network_enabled=network_enabled,
                )
            raw_content, raw_meta = responses["raw"]
            qfq_content, qfq_meta = responses["qfq"]
            raw_frame = parse_daily_payload(raw_content, prefix="raw")
            qfq_frame = parse_daily_payload(qfq_content, prefix="qfq")
            list_date = pd.Timestamp(master_by_code.loc[raw_code, "list_date"]).date()
            normalized = normalize_daily(
                raw_code,
                raw_frame,
                qfq_frame,
                list_date=list_date,
                snapshot_id=snapshot_id,
                raw_sha256=raw_meta["response_sha256"],
                qfq_sha256=qfq_meta["response_sha256"],
            )
            if normalized.empty:
                raise ValueError("raw or qfq response is empty")
            output_path = output_dir / f"symbol={canonical_symbol(raw_code)}" / "daily.parquet"
            atomic_write_parquet(normalized, output_path)
            valid = normalized[normalized["row_status"] == "VALID"]
            coverage[canonical_symbol(raw_code)] = {
                "rows": len(normalized),
                "valid_rows": len(valid),
                "first_date": str(normalized["trade_date"].min()),
                "last_date": str(normalized["trade_date"].max()),
                "first_121_date": (
                    str(valid.iloc[120]["trade_date"]) if len(valid) >= 121 else None
                ),
                "partition_path": str(output_path.relative_to(RESEARCH_ROOT)),
                "partition_bytes": output_path.stat().st_size,
                "partition_sha256": sha256_file(output_path),
                "source_raw_sha256": raw_meta["response_sha256"],
                "source_qfq_sha256": qfq_meta["response_sha256"],
            }
        except Exception as exc:  # continue to make incompleteness explicit
            errors.append(
                {"raw_code": raw_code, "error_type": type(exc).__name__, "message": str(exc)}
            )
            coverage[canonical_symbol(raw_code)] = {
                "rows": 0,
                "valid_rows": 0,
                "first_date": None,
                "last_date": None,
                "first_121_date": None,
            }
            print(f"ERROR {raw_code}: {type(exc).__name__}: {exc}", flush=True)
    return coverage, errors


def build_calendar(end_date: date, snapshot_id: str) -> dict[str, Any]:
    provider = ak.tool_trade_date_hist_sina().copy()
    provider["trade_date"] = pd.to_datetime(provider["trade_date"]).dt.date
    provider = (
        provider[provider["trade_date"] <= end_date].drop_duplicates().sort_values("trade_date")
    )
    provider["is_trading_day"] = True
    provider["calendar_source"] = "Sina trade-date history via AkShare"
    provider["snapshot_id"] = snapshot_id

    local = pd.read_parquet(LOCAL_CALENDAR)
    local_dates = set(pd.to_datetime(local["trade_date"]).dt.date)
    provider_dates = set(provider["trade_date"])
    local_through_end = {item for item in local_dates if item <= end_date}
    exact_match = provider_dates == local_through_end
    path = DATA_ROOT / "metadata" / "trade_calendar.parquet"
    atomic_write_parquet(provider.reset_index(drop=True), path)
    return {
        "provider": "Sina via AkShare tool_trade_date_hist_sina",
        "local_cross_check_path": str(LOCAL_CALENDAR),
        "local_cross_check_sha256": sha256_file(LOCAL_CALENDAR),
        "exact_match_through_end_date": exact_match,
        "rows": len(provider),
        "first_date": str(provider["trade_date"].min()),
        "last_date": str(provider["trade_date"].max()),
        "partition_sha256": sha256_file(path),
    }


def build_indices(end_date: date, snapshot_id: str) -> tuple[dict[str, Any], list[str]]:
    output_dir = DATA_ROOT / "daily_indices"
    coverage: dict[str, Any] = {}
    errors: list[str] = []
    for symbol, provider_symbol, role in [
        ("000852.SH", "sh000852", "entry_anchor"),
        ("000300.SH", "sh000300", "benchmark"),
    ]:
        try:
            frame = ak.stock_zh_index_daily(symbol=provider_symbol).copy()
            frame["trade_date"] = pd.to_datetime(frame["date"]).dt.date
            frame = frame[frame["trade_date"] <= end_date].sort_values("trade_date")
            frame.insert(1, "symbol", symbol)
            frame["amount_cny"] = np.nan
            frame["available_at"] = frame["trade_date"].map(completed_bar_available_at)
            frame["source"] = "Sina index daily via AkShare"
            frame["snapshot_id"] = snapshot_id
            frame["series_role"] = role
            frame = frame[
                [
                    "trade_date",
                    "symbol",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount_cny",
                    "available_at",
                    "source",
                    "snapshot_id",
                    "series_role",
                ]
            ]
            path = output_dir / f"symbol={symbol}" / "daily.parquet"
            atomic_write_parquet(frame, path)
            coverage[symbol] = {
                "rows": len(frame),
                "first_date": str(frame["trade_date"].min()),
                "last_date": str(frame["trade_date"].max()),
                "partition_sha256": sha256_file(path),
                "partition_bytes": path.stat().st_size,
            }
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
    return coverage, errors


def main() -> int:
    args = parse_args()
    end_date = datetime.strptime(args.end_date, "%Y%m%d").date()
    datetime.strptime(args.start_date, "%Y%m%d")
    pool = parse_strategy_pool()
    if len(pool) != 152 or len(set(pool)) != 152:
        raise ValueError("frozen strategy pool must contain 152 unique codes")

    started_at = capture_timestamp()
    snapshot_id = f"v6-md-{datetime.now(TZ).strftime('%Y%m%dT%H%M%S%z')}"
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"SNAPSHOT {snapshot_id}", flush=True)
    print(f"TARGET {DATA_ROOT}", flush=True)
    print(f"ETF_POOL {len(pool)}", flush=True)

    session = requests.Session()
    master, master_sources = build_security_master(
        session,
        pool,
        retries=args.retries,
        retry_delay=args.retry_delay,
        force=args.force,
        snapshot_id=snapshot_id,
    )
    print(f"MASTER rows={len(master)}", flush=True)
    calendar = build_calendar(end_date, snapshot_id)
    print(
        f"CALENDAR rows={calendar['rows']} exact_local_match="
        f"{calendar['exact_match_through_end_date']}",
        flush=True,
    )
    daily_coverage, daily_errors = build_etf_daily(
        session,
        pool,
        master,
        start_date=args.start_date,
        end_date=args.end_date,
        retries=args.retries,
        retry_delay=args.retry_delay,
        force=args.force,
        snapshot_id=snapshot_id,
        network_enabled=not args.daily_cache_only,
    )
    index_coverage, index_errors = build_indices(end_date, snapshot_id)

    present = sorted(symbol for symbol, item in daily_coverage.items() if item["rows"] > 0)
    daily_rows = sum(int(item["rows"]) for item in daily_coverage.values())
    daily_valid_rows = sum(int(item["valid_rows"]) for item in daily_coverage.values())
    date_starts = [item["first_date"] for item in daily_coverage.values() if item["first_date"]]
    date_ends = [item["last_date"] for item in daily_coverage.values() if item["last_date"]]
    manifest = {
        "dataset_version": "v6-market-data-v1",
        "contract_version": CONTRACT_VERSION,
        "snapshot_id": snapshot_id,
        "created_at": started_at,
        "completed_at": capture_timestamp(),
        "provider": {
            "etf_daily": "Eastmoney direct AKShare-compatible ETF kline endpoint",
            "index_daily": "Sina via AkShare stock_zh_index_daily",
            "security_master": "Shanghai Stock Exchange + Shenzhen Stock Exchange",
            "trade_calendar": "Sina via AkShare; exact local-calendar cross-check",
        },
        "provider_version": {"akshare": ak.__version__, "endpoints": "captured per request"},
        "provider_sources": {"security_master": master_sources},
        "request": {"start_date": args.start_date, "end_date": args.end_date},
        "strategy_source_path": str(STRATEGY_PATH.relative_to(RESEARCH_ROOT.parent.parent)),
        "strategy_source_sha256": strategy_sha256(),
        "universe_count": len(pool),
        "universe_sha256": universe_sha256(pool),
        "symbols_expected": [canonical_symbol(code) for code in pool],
        "symbols_present": present,
        "date_start": min(date_starts) if date_starts else None,
        "date_end": max(date_ends) if date_ends else None,
        "daily_rows": daily_rows,
        "daily_valid_rows": daily_valid_rows,
        "minute_rows": 0,
        "daily_schema": [
            "trade_date",
            "symbol",
            "raw_code",
            "exchange",
            "row_status",
            "raw_open",
            "raw_high",
            "raw_low",
            "raw_close",
            "pre_adj_open",
            "pre_adj_high",
            "pre_adj_low",
            "pre_adj_close",
            "adj_factor_close_ratio",
            "volume_raw",
            "volume_unit",
            "volume_shares",
            "amount_cny",
            "available_at",
            "source",
            "snapshot_id",
        ],
        "minute_schema": [],
        "adjustment_method": "Eastmoney provider qfq retained beside raw; equivalence unverified",
        "timezone": "Asia/Shanghai",
        "trade_calendar_source": calendar,
        "missing_counts": {
            "daily_symbol_partitions": len(pool) - len(present),
            "minute_symbol_partitions": len(pool),
            "opening_auction_symbol_partitions": len(pool),
        },
        "duplicate_counts": {"universe_codes": len(pool) - len(set(pool))},
        "storage_bytes": directory_bytes(DATA_ROOT),
        "per_symbol_date_coverage": daily_coverage,
        "index_date_coverage": index_coverage,
        "build_errors": {"daily": daily_errors, "indices": index_errors},
        "validation_status": "NOT_RUN",
    }
    atomic_write_json(MANIFEST_PATH, manifest)
    print(f"DAILY_ROWS {daily_rows}", flush=True)
    print(f"DAILY_VALID_ROWS {daily_valid_rows}", flush=True)
    print("MINUTE_ROWS 0", flush=True)
    print(f"DATA_BYTES {manifest['storage_bytes']}", flush=True)
    print(f"MANIFEST {MANIFEST_PATH}", flush=True)
    print(f"BUILD_ERRORS {len(daily_errors) + len(index_errors)}", flush=True)
    return 0 if not daily_errors and not index_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
