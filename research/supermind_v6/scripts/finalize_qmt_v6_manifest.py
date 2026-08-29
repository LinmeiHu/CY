from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from v6_data_common import (
    CONTRACT_VERSION,
    DATA_ROOT,
    MANIFEST_PATH,
    QMT_DATA_ROOT,
    RESEARCH_ROOT,
    STRATEGY_PATH,
    atomic_write_json,
    canonical_symbol,
    directory_bytes,
    parse_strategy_pool,
    sha256_file,
    strategy_sha256,
    universe_sha256,
)

TZ = ZoneInfo("Asia/Shanghai")
INDEX_SYMBOLS = ["000852.SH", "000300.SH"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize the QMT V6 market-data manifest")
    parser.add_argument("--end-date", required=True, help="YYYYMMDD")
    return parser.parse_args()


def copy_governed_metadata() -> None:
    target = QMT_DATA_ROOT / "metadata"
    target.mkdir(parents=True, exist_ok=True)
    master_source = DATA_ROOT / "metadata" / "etf_security_master.parquet"
    if not master_source.exists():
        raise FileNotFoundError(master_source)
    shutil.copy2(master_source, target / "etf_security_master.parquet")

    qmt_calendar = target / "trade_calendar_qmt.parquet"
    if not qmt_calendar.exists():
        raise FileNotFoundError(qmt_calendar)
    shutil.copy2(qmt_calendar, target / "trade_calendar.parquet")

    reference_calendar = DATA_ROOT / "metadata" / "trade_calendar.parquet"
    if reference_calendar.exists():
        shutil.copy2(reference_calendar, target / "trade_calendar_reference.parquet")


def partition_coverage(path: Path) -> dict[str, object]:
    frame = pd.read_parquet(path)
    valid = frame[frame["row_status"] == "VALID"]
    item: dict[str, object] = {
        "rows": len(frame),
        "valid_rows": len(valid),
        "first_date": str(frame["trade_date"].min()) if len(frame) else None,
        "last_date": str(frame["trade_date"].max()) if len(frame) else None,
        "partition_path": str(path.relative_to(RESEARCH_ROOT)),
        "partition_bytes": path.stat().st_size,
        "partition_sha256": sha256_file(path),
    }
    if path.name == "daily.parquet":
        item["first_121_date"] = str(valid.iloc[120]["trade_date"]) if len(valid) >= 121 else None
    else:
        item["bar_role_counts"] = {
            str(key): int(value) for key, value in frame["bar_role"].value_counts().items()
        }
    return item


def main() -> int:
    args = parse_args()
    end_date = datetime.strptime(args.end_date, "%Y%m%d").date()
    copy_governed_metadata()

    pool = parse_strategy_pool()
    symbols = [canonical_symbol(code) for code in pool]
    daily_coverage: dict[str, dict[str, object]] = {}
    minute_coverage: dict[str, dict[str, object]] = {}
    missing_daily: list[str] = []
    missing_minute: list[str] = []
    for symbol in symbols + INDEX_SYMBOLS:
        path = QMT_DATA_ROOT / "daily" / f"symbol={symbol}" / "daily.parquet"
        if path.exists():
            daily_coverage[symbol] = partition_coverage(path)
        else:
            missing_daily.append(symbol)
    for symbol in symbols:
        path = QMT_DATA_ROOT / "minute_critical" / f"symbol={symbol}" / "critical.parquet"
        if path.exists():
            minute_coverage[symbol] = partition_coverage(path)
        else:
            missing_minute.append(symbol)

    sample_daily = next(iter(daily_coverage))
    sample_minute = next(iter(minute_coverage), None)
    daily_schema = list(
        pd.read_parquet(
            QMT_DATA_ROOT / "daily" / f"symbol={sample_daily}" / "daily.parquet"
        ).columns
    )
    minute_schema = (
        list(
            pd.read_parquet(
                QMT_DATA_ROOT / "minute_critical" / f"symbol={sample_minute}" / "critical.parquet"
            ).columns
        )
        if sample_minute
        else []
    )

    calendar_path = QMT_DATA_ROOT / "metadata" / "trade_calendar.parquet"
    calendar = pd.read_parquet(calendar_path)
    calendar["trade_date"] = pd.to_datetime(calendar["trade_date"]).dt.date
    calendar = calendar[calendar["trade_date"] <= end_date]
    reference_path = QMT_DATA_ROOT / "metadata" / "trade_calendar_reference.parquet"
    reference = pd.read_parquet(reference_path)
    reference["trade_date"] = pd.to_datetime(reference["trade_date"]).dt.date
    overlap_start = max(calendar["trade_date"].min(), reference["trade_date"].min())
    overlap_end = min(calendar["trade_date"].max(), reference["trade_date"].max())
    qmt_overlap = set(
        calendar.loc[calendar["trade_date"].between(overlap_start, overlap_end), "trade_date"]
    )
    reference_overlap = set(
        reference.loc[reference["trade_date"].between(overlap_start, overlap_end), "trade_date"]
    )
    calendar_source = {
        "provider": "QMT XtData get_trading_calendar(SH)",
        "reference_provider": "Sina via AkShare plus local quant-calendar audit",
        "reference_path": str(reference_path),
        "reference_overlap_start": str(overlap_start),
        "reference_overlap_end": str(overlap_end),
        "exact_match_reference_overlap": qmt_overlap == reference_overlap,
        "covers_requested_end": end_date in set(calendar["trade_date"]),
        "rows": len(calendar),
        "first_date": str(calendar["trade_date"].min()),
        "last_date": str(calendar["trade_date"].max()),
        "partition_sha256": sha256_file(calendar_path),
    }

    etf_daily = {symbol: daily_coverage[symbol] for symbol in symbols if symbol in daily_coverage}
    date_starts = [str(item["first_date"]) for item in etf_daily.values()]
    date_ends = [str(item["last_date"]) for item in etf_daily.values()]
    minute_starts = [str(item["first_date"]) for item in minute_coverage.values()]
    minute_ends = [str(item["last_date"]) for item in minute_coverage.values()]
    manifest = {
        "dataset_version": "v6-market-data-qmt-v1",
        "contract_version": CONTRACT_VERSION,
        "created_at": datetime.now(TZ).isoformat(),
        "provider": {
            "etf_daily": "QMT XtData via Guojin MiniQmt",
            "index_daily": "QMT XtData via Guojin MiniQmt",
            "minute_critical": "QMT XtData 1m via Guojin MiniQmt",
            "security_master": "Shanghai Stock Exchange + Shenzhen Stock Exchange",
            "trade_calendar": "QMT XtData; Sina/local-calendar overlap cross-check",
        },
        "provider_version": {
            "qmt_client": "2.0.8.300",
            "xtdata_server_tag": "sp3",
            "xtdata_server_version": "1.0",
            "python": "3.11.9",
            "pandas": "2.2.3",
            "pyarrow": "17.0.0",
        },
        "provider_limitations": [
            "QMT historical 1m response begins around 2025-08-27 despite a 1990 start request",
            "QMT proprietary cache is external to the research artifact and has no "
            "immutable response hash",
        ],
        "request": {"start_date": "19900101", "end_date": args.end_date},
        "strategy_source_path": str(STRATEGY_PATH.relative_to(RESEARCH_ROOT.parent.parent)),
        "strategy_source_sha256": strategy_sha256(),
        "universe_count": len(pool),
        "universe_sha256": universe_sha256(pool),
        "symbols_expected": symbols,
        "symbols_present": sorted(etf_daily),
        "date_start": min(date_starts) if date_starts else None,
        "date_end": max(date_ends) if date_ends else None,
        "minute_date_start": min(minute_starts) if minute_starts else None,
        "minute_date_end": max(minute_ends) if minute_ends else None,
        "daily_rows": sum(int(item["rows"]) for item in etf_daily.values()),
        "daily_valid_rows": sum(int(item["valid_rows"]) for item in etf_daily.values()),
        "index_daily_rows": sum(
            int(daily_coverage[symbol]["rows"])
            for symbol in INDEX_SYMBOLS
            if symbol in daily_coverage
        ),
        "minute_rows": sum(int(item["rows"]) for item in minute_coverage.values()),
        "minute_dataset_scope": "critical_execution_bars_only_09_30_14_57_15_00",
        "full_minute_rows_exported": 0,
        "daily_schema": daily_schema,
        "minute_schema": minute_schema,
        "adjustment_method": (
            "QMT dividend_type=none retained beside dividend_type=front for daily and 1m; "
            "SuperMind fq=pre equivalence unverified"
        ),
        "timezone": "Asia/Shanghai",
        "trade_calendar_source": calendar_source,
        "missing_counts": {
            "daily_symbol_partitions": len([item for item in missing_daily if item in symbols]),
            "index_daily_partitions": len(
                [item for item in missing_daily if item in INDEX_SYMBOLS]
            ),
            "minute_critical_symbol_partitions": len(missing_minute),
            "opening_auction_symbol_partitions": len(symbols),
        },
        "duplicate_counts": {"universe_codes": len(pool) - len(set(pool))},
        "storage_bytes": directory_bytes(QMT_DATA_ROOT),
        "per_symbol_date_coverage": etf_daily,
        "index_date_coverage": {
            symbol: daily_coverage[symbol] for symbol in INDEX_SYMBOLS if symbol in daily_coverage
        },
        "per_symbol_minute_critical_coverage": minute_coverage,
        "validation_status": "NOT_RUN",
    }
    atomic_write_json(MANIFEST_PATH, manifest)
    print(f"DAILY_ROWS {manifest['daily_rows']}")
    print(f"INDEX_DAILY_ROWS {manifest['index_daily_rows']}")
    print(f"MINUTE_CRITICAL_ROWS {manifest['minute_rows']}")
    print(f"MISSING_DAILY {len(missing_daily)}")
    print(f"MISSING_MINUTE {len(missing_minute)}")
    print(f"MANIFEST {MANIFEST_PATH}")
    return 0 if not missing_daily and not missing_minute else 2


if __name__ == "__main__":
    raise SystemExit(main())
