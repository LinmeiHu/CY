from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from zipfile import ZipFile

import duckdb
import numpy as np
import pandas as pd
from v6_data_common import (
    QMT_DATA_ROOT,
    RESEARCH_ROOT,
    atomic_write_json,
    atomic_write_parquet,
    canonical_symbol,
    parse_strategy_pool,
    sha256_file,
    strategy_sha256,
)

OLD_ROOT = Path(
    "/Users/linmei/Downloads/2010-2025/1分钟/ETF1分钟历史行情_2010-2025/ETF数据"
)
NEW_ROOT = Path("/Users/linmei/Downloads/2026/ETF1分钟历史行情_2026/ETF数据")
ANCHOR_5M_ROOT = RESEARCH_ROOT / "data" / "market_data_qmt_anchor_5m_v1"
OUTPUT_ROOT = RESEARCH_ROOT / "data" / "market_data_hybrid_etf_v1"
SUMMARY_PATH = RESEARCH_ROOT / "manifests" / "v6_hybrid_critical_history_summary.json"
START = date(2020, 1, 1)
END = date(2026, 8, 28)
ROLE_TIMES = {
    "09:30:00": "OPEN_BAR_09_30",
    "14:57:00": "PSEUDO_CLOSE_14_57_OPEN",
    "15:00:00": "FINAL_CLOSE_BAR",
}
PRICE_COLUMNS = ["open", "high", "low", "close"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-root", type=Path, default=OLD_ROOT)
    parser.add_argument("--new-root", type=Path, default=NEW_ROOT)
    parser.add_argument("--qmt-root", type=Path, default=QMT_DATA_ROOT)
    parser.add_argument("--anchor-5m-root", type=Path, default=ANCHOR_5M_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parser.add_argument("--symbols", nargs="+")
    return parser.parse_args()


def qmt_daily_path(root: Path, symbol: str) -> Path:
    return root / "daily" / f"symbol={symbol}" / "daily.parquet"


def qmt_minute_path(root: Path, symbol: str) -> Path:
    return root / "minute_critical" / f"symbol={symbol}" / "critical.parquet"


def output_minute_path(root: Path, symbol: str) -> Path:
    return root / "minute_critical" / f"symbol={symbol}" / "critical.parquet"


def read_local_member(payload: bytes) -> pd.DataFrame:
    temporary_name: str | None = None
    try:
        with NamedTemporaryFile(suffix=".parquet", delete=False) as handle:
            handle.write(payload)
            temporary_name = handle.name
        relation = duckdb.sql(
            """
            SELECT
                ts_code,
                freq,
                trade_time,
                open,
                high,
                low,
                close,
                vol,
                amount,
                strftime(trade_time, '%H:%M:%S') AS local_time
            FROM read_parquet(?)
            WHERE strftime(trade_time, '%H:%M:%S') IN ('09:30:00', '14:57:00', '15:00:00')
            ORDER BY trade_time
            """,
            params=[temporary_name],
        )
        return relation.df()
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def load_daily(root: Path, symbol: str, start: date, end: date) -> pd.DataFrame:
    frame = pd.read_parquet(qmt_daily_path(root, symbol))
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame = frame[frame["trade_date"].between(start, end)].copy()
    if frame["trade_date"].duplicated().any():
        raise ValueError(f"duplicate QMT daily date: {symbol}")
    return frame.set_index("trade_date").sort_index()


def local_status(frame: pd.DataFrame) -> pd.Series:
    prices = frame[[f"raw_{column}" for column in PRICE_COLUMNS]]
    finite = np.isfinite(prices).all(axis=1)
    positive = prices.gt(0).all(axis=1)
    finite_flow = np.isfinite(frame[["volume_raw", "amount_cny"]]).all(axis=1)
    status = pd.Series("VALID", index=frame.index, dtype="object")
    status.loc[~finite | ~positive | ~finite_flow] = "NONFINITE"
    no_flow = frame["volume_raw"].le(0) | frame["amount_cny"].le(0)
    status.loc[finite & positive & finite_flow & no_flow] = "NONPOSITIVE_VOLUME"
    return status


def normalize_local(
    frame: pd.DataFrame,
    *,
    symbol: str,
    daily: pd.DataFrame,
    archive: Path,
    archive_sha256: str,
    member: str,
    capture_at: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    if frame.empty:
        return frame, {
            "missing_daily_factor": 0,
            "opening_daily_mismatch_diagnostic": 0,
            "final_close_reconciliation_mismatch": 0,
        }
    frame = frame.copy()
    timestamps = pd.to_datetime(frame["trade_time"], utc=True).dt.tz_convert("Asia/Shanghai")
    frame["trade_date"] = timestamps.dt.date
    frame["datetime"] = timestamps.map(lambda value: value.isoformat())
    frame["symbol"] = symbol
    frame["raw_code"] = symbol.split(".")[0]
    frame["exchange"] = symbol.split(".")[1]
    frame["bar_role"] = frame["local_time"].map(ROLE_TIMES)
    for column in PRICE_COLUMNS:
        frame[f"raw_{column}"] = pd.to_numeric(frame[column], errors="coerce")
    frame["volume_raw"] = pd.to_numeric(frame["vol"], errors="coerce") / 100.0
    frame["volume_shares"] = pd.to_numeric(frame["vol"], errors="coerce")
    frame["amount_cny"] = pd.to_numeric(frame["amount"], errors="coerce")

    factors = daily["adj_factor_close_ratio"].to_dict()
    frame["adj_factor_close_ratio"] = frame["trade_date"].map(factors)
    missing_factor = frame["adj_factor_close_ratio"].isna()
    for column in PRICE_COLUMNS:
        frame[f"pre_adj_{column}"] = (
            frame[f"raw_{column}"] * frame["adj_factor_close_ratio"]
        )
    frame["row_status"] = local_status(frame)
    frame.loc[missing_factor, "row_status"] = "MISSING_QMT_DAILY_FACTOR"

    daily_open = frame["trade_date"].map(daily["raw_open"].to_dict())
    daily_close = frame["trade_date"].map(daily["raw_close"].to_dict())
    opening_mismatch = frame["bar_role"].eq("OPEN_BAR_09_30") & ~np.isclose(
        frame["raw_open"], daily_open, rtol=0.0, atol=1e-8, equal_nan=False
    )
    close_mismatch = (
        frame["bar_role"].eq("FINAL_CLOSE_BAR")
        & daily_close.notna()
        & ~np.isclose(
            frame["raw_close"], daily_close, rtol=0.0, atol=1e-8, equal_nan=False
        )
    )
    frame["opening_daily_mismatch_diagnostic"] = opening_mismatch
    frame["final_close_reconciliation_mismatch"] = close_mismatch
    frame.loc[close_mismatch, "row_status"] = "DAILY_RECONCILIATION_MISMATCH"

    frame["volume_unit"] = "lot_100_shares"
    frame["timezone"] = "Asia/Shanghai"
    frame["source"] = "local ETF 1m ZIP fallback"
    frame["source_kind"] = "LOCAL_ZIP_EXACT_1M"
    frame["source_priority"] = 10
    frame["source_archive"] = str(archive)
    frame["source_archive_sha256"] = archive_sha256
    frame["source_member"] = member
    frame["capture_at"] = capture_at
    frame["snapshot_id"] = f"local-etf-1m-{archive_sha256[:16]}"
    frame["available_at"] = frame["datetime"]
    frame["adjustment_status"] = "QMT daily front factor applied to local raw 1m price"
    frame["opening_auction_status"] = "09:30 1m bar; exact auction semantics unverified"
    keep = [
        "trade_date",
        "datetime",
        "symbol",
        "raw_code",
        "exchange",
        "bar_role",
        "row_status",
        *[f"raw_{column}" for column in PRICE_COLUMNS],
        *[f"pre_adj_{column}" for column in PRICE_COLUMNS],
        "adj_factor_close_ratio",
        "volume_raw",
        "volume_shares",
        "volume_unit",
        "amount_cny",
        "timezone",
        "source",
        "source_kind",
        "source_priority",
        "source_archive",
        "source_archive_sha256",
        "source_member",
        "capture_at",
        "snapshot_id",
        "available_at",
        "adjustment_status",
        "opening_auction_status",
        "opening_daily_mismatch_diagnostic",
        "final_close_reconciliation_mismatch",
    ]
    return frame[keep], {
        "missing_daily_factor": int(missing_factor.sum()),
        "opening_daily_mismatch_diagnostic": int(opening_mismatch.sum()),
        "final_close_reconciliation_mismatch": int(close_mismatch.sum()),
    }


def load_local(
    *,
    symbol: str,
    daily: pd.DataFrame,
    old_root: Path,
    new_root: Path,
    start: date,
    end: date,
    capture_at: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames = []
    lineage = []
    counters = {
        "missing_daily_factor": 0,
        "opening_daily_mismatch_diagnostic": 0,
        "final_close_reconciliation_mismatch": 0,
    }
    for root, years in [(old_root, range(start.year, min(end.year, 2025) + 1)), (new_root, [2026])]:
        archive = root / f"{symbol}.zip"
        selected_years = [year for year in years if start.year <= year <= end.year]
        if not archive.exists() or not selected_years:
            continue
        archive_sha256 = sha256_file(archive)
        with ZipFile(archive) as zip_file:
            names = set(zip_file.namelist())
            for year in selected_years:
                member = f"{year}/{symbol}.parquet"
                if member not in names:
                    continue
                raw = read_local_member(zip_file.read(member))
                normalized, item_counters = normalize_local(
                    raw,
                    symbol=symbol,
                    daily=daily,
                    archive=archive,
                    archive_sha256=archive_sha256,
                    member=member,
                    capture_at=capture_at,
                )
                frames.append(normalized)
                lineage.append(
                    {
                        "archive": str(archive),
                        "archive_sha256": archive_sha256,
                        "member": member,
                        "rows": len(normalized),
                    }
                )
                for key, value in item_counters.items():
                    counters[key] += value
    output = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return output, {"lineage": lineage, **counters}


def normalize_qmt(frame: pd.DataFrame, *, source_kind: str, source_priority: int) -> pd.DataFrame:
    frame = frame.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
    frame["source_kind"] = source_kind
    frame["source_priority"] = source_priority
    if "source_archive" not in frame:
        frame["source_archive"] = None
    if "source_archive_sha256" not in frame:
        frame["source_archive_sha256"] = None
    if "source_member" not in frame:
        frame["source_member"] = None
    return frame


def load_qmt_exact(root: Path, symbol: str, start: date, end: date) -> pd.DataFrame:
    path = qmt_minute_path(root, symbol)
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    frame = normalize_qmt(frame, source_kind="QMT_EXACT_1M", source_priority=30)
    return frame[frame["trade_date"].between(start, end)].copy()


def load_anchor_fallback(root: Path, start: date, end: date) -> pd.DataFrame:
    path = qmt_minute_path(root, "000852.SH")
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    frame = normalize_qmt(frame, source_kind="QMT_5M_ANCHOR_FALLBACK", source_priority=20)
    return frame[frame["trade_date"].between(start, end)].copy()


def merge_sources(frames: list[pd.DataFrame], symbol: str) -> pd.DataFrame:
    available = [frame for frame in frames if not frame.empty]
    if not available:
        return pd.DataFrame()
    combined = pd.concat(available, ignore_index=True, sort=False)
    combined = combined.sort_values(
        ["trade_date", "bar_role", "source_priority"], kind="stable"
    )
    combined = combined.drop_duplicates(["trade_date", "bar_role"], keep="last")
    if combined.duplicated(["trade_date", "bar_role"]).any():
        raise ValueError(f"duplicate hybrid critical role: {symbol}")
    return combined.sort_values(["trade_date", "bar_role"]).reset_index(drop=True)


def build_availability(
    *,
    symbols: list[str],
    daily_map: dict[str, pd.DataFrame],
    minute_map: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    roles = {
        "OPEN_BAR_09_30": "executable_09_30",
        "PSEUDO_CLOSE_14_57_OPEN": "tail_signal_available_14_57",
        "FINAL_CLOSE_BAR": "executable_15_00",
    }
    rows = []
    for symbol in symbols:
        daily = daily_map[symbol]
        expected = daily[daily["row_status"].eq("VALID")].reset_index()[["trade_date"]]
        expected["symbol"] = symbol
        minute = minute_map.get(symbol, pd.DataFrame())
        for role, column in roles.items():
            if minute.empty:
                expected[column] = False
                continue
            selected = minute[minute["bar_role"].eq(role)][["trade_date", "row_status"]].copy()
            if selected["trade_date"].duplicated().any():
                raise ValueError(f"duplicate availability source: {symbol} {role}")
            selected[column] = selected["row_status"].eq("VALID")
            expected = expected.merge(selected[["trade_date", column]], on="trade_date", how="left")
            expected[column] = expected[column].eq(True)
        rows.append(expected)
    return pd.concat(rows, ignore_index=True).sort_values(["trade_date", "symbol"])


def main() -> int:
    args = parse_args()
    pool = [canonical_symbol(code) for code in parse_strategy_pool()]
    requested = list(args.symbols or pool)
    unsupported = sorted(set(requested) - set(pool))
    if unsupported:
        raise ValueError(f"symbols outside frozen pool: {unsupported}")
    capture_at = datetime.now().astimezone().isoformat()
    all_symbols = [*requested, "000852.SH"]
    daily_map = {
        symbol: load_daily(args.qmt_root, symbol, args.start, args.end)
        for symbol in all_symbols
    }
    minute_map: dict[str, pd.DataFrame] = {}
    summary: dict[str, Any] = {
        "build_version": "v6-hybrid-critical-history-1",
        "generated_at": capture_at,
        "window_start": args.start.isoformat(),
        "window_end": args.end.isoformat(),
        "strategy_source_sha256": strategy_sha256(),
        "source_priority": ["QMT_EXACT_1M", "QMT_5M_ANCHOR_FALLBACK", "LOCAL_ZIP_EXACT_1M"],
        "local_parquet_reader": "DuckDB (PyArrow 19 raised repetition-level histogram errors)",
        "symbols": {},
    }
    for index, symbol in enumerate(requested, start=1):
        print(f"BUILD {index}/{len(requested)} {symbol}", flush=True)
        local, local_meta = load_local(
            symbol=symbol,
            daily=daily_map[symbol],
            old_root=args.old_root,
            new_root=args.new_root,
            start=args.start,
            end=args.end,
            capture_at=capture_at,
        )
        qmt = load_qmt_exact(args.qmt_root, symbol, args.start, args.end)
        hybrid = merge_sources([local, qmt], symbol)
        if hybrid.empty:
            raise ValueError(f"no critical data for {symbol}")
        path = output_minute_path(args.output, symbol)
        atomic_write_parquet(hybrid, path)
        minute_map[symbol] = hybrid
        summary["symbols"][symbol] = {
            "rows": len(hybrid),
            "valid_rows": int(hybrid["row_status"].eq("VALID").sum()),
            "first_date": str(hybrid["trade_date"].min()),
            "last_date": str(hybrid["trade_date"].max()),
            "source_counts": {
                str(key): int(value)
                for key, value in hybrid["source_kind"].value_counts().items()
            },
            "partition_sha256": sha256_file(path),
            "local": local_meta,
        }

    anchor_local = load_anchor_fallback(args.anchor_5m_root, args.start, args.end)
    anchor_qmt = load_qmt_exact(args.qmt_root, "000852.SH", args.start, args.end)
    anchor = merge_sources([anchor_local, anchor_qmt], "000852.SH")
    anchor_path = output_minute_path(args.output, "000852.SH")
    atomic_write_parquet(anchor, anchor_path)
    minute_map["000852.SH"] = anchor
    summary["symbols"]["000852.SH"] = {
        "rows": len(anchor),
        "valid_rows": int(anchor["row_status"].eq("VALID").sum()) if not anchor.empty else 0,
        "first_date": str(anchor["trade_date"].min()) if not anchor.empty else None,
        "last_date": str(anchor["trade_date"].max()) if not anchor.empty else None,
        "source_counts": {
            str(key): int(value)
            for key, value in (
                anchor["source_kind"].value_counts().items() if not anchor.empty else []
            )
        },
        "partition_sha256": sha256_file(anchor_path),
        "limitation": (
            "QMT index intraday retention starts 2025-08-27; older 14:57 "
            "entry-anchor snapshots fail closed"
        ),
    }

    availability = build_availability(
        symbols=all_symbols,
        daily_map=daily_map,
        minute_map=minute_map,
    )
    availability_path = args.output / "execution_availability" / "critical_execution.parquet"
    atomic_write_parquet(availability, availability_path)
    summary["availability"] = {
        "rows": len(availability),
        "path": str(availability_path),
        "sha256": sha256_file(availability_path),
        "counts": {
            column: int(availability[column].sum())
            for column in [
                "executable_09_30",
                "tail_signal_available_14_57",
                "executable_15_00",
            ]
        },
    }
    summary["totals"] = {
        "hybrid_rows": int(sum(item["rows"] for item in summary["symbols"].values())),
        "source_counts": {},
        "local_opening_daily_mismatch_diagnostic": int(
            sum(
                item.get("local", {}).get("opening_daily_mismatch_diagnostic", 0)
                for item in summary["symbols"].values()
            )
        ),
        "local_final_close_reconciliation_mismatch": int(
            sum(
                item.get("local", {}).get("final_close_reconciliation_mismatch", 0)
                for item in summary["symbols"].values()
            )
        ),
        "local_missing_daily_factor": int(
            sum(
                item.get("local", {}).get("missing_daily_factor", 0)
                for item in summary["symbols"].values()
            )
        ),
    }
    for item in summary["symbols"].values():
        for source, count in item["source_counts"].items():
            summary["totals"]["source_counts"][source] = (
                summary["totals"]["source_counts"].get(source, 0) + count
            )
    atomic_write_json(args.summary, summary)
    print(f"HYBRID_ROWS {summary['totals']['hybrid_rows']}")
    print(f"SOURCE_COUNTS {json.dumps(summary['totals']['source_counts'], sort_keys=True)}")
    print(f"AVAILABILITY {availability_path}")
    print(f"SUMMARY {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
