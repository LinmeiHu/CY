from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from v6_data_common import (
    CONTRACT_VERSION,
    DATA_ROOT,
    MANIFEST_PATH,
    VALIDATION_PATH,
    atomic_write_json,
    canonical_symbol,
    directory_bytes,
    exchange_for,
    parse_strategy_pool,
    sha256_file,
    strategy_sha256,
    universe_sha256,
)

REQUIRED_DAILY_COLUMNS = {
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
}
PRICE_COLUMNS = [
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "pre_adj_open",
    "pre_adj_high",
    "pre_adj_low",
    "pre_adj_close",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the isolated V6 market data")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    return parser.parse_args()


def read_daily(symbol: str) -> pd.DataFrame:
    path = DATA_ROOT / "daily" / f"symbol={symbol}" / "daily.parquet"
    return pd.read_parquet(path)


def raw_provider_key_count(raw_code: str, basis: str) -> tuple[int, set[str]]:
    path = DATA_ROOT / "raw" / "etf_daily" / raw_code / f"{basis}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    data = payload.get("data") or {}
    lines = data.get("klines") or []
    dates = [line.split(",", 1)[0] for line in lines]
    return len(dates), set(dates)


def check_ohlc(frame: pd.DataFrame, prefix: str) -> int:
    open_column = f"{prefix}_open"
    high_column = f"{prefix}_high"
    low_column = f"{prefix}_low"
    close_column = f"{prefix}_close"
    invalid = (
        (frame[high_column] < frame[[open_column, close_column]].max(axis=1))
        | (frame[low_column] > frame[[open_column, close_column]].min(axis=1))
        | (frame[high_column] < frame[low_column])
    )
    return int(invalid.sum())


def sample_daily_row(symbol: str) -> dict[str, Any]:
    path = DATA_ROOT / "daily" / f"symbol={symbol}" / "daily.parquet"
    if not path.exists():
        return {"symbol": symbol, "status": "MISSING_DAILY_PARTITION"}
    frame = pd.read_parquet(path)
    valid = frame[frame["row_status"] == "VALID"]
    if valid.empty:
        return {"symbol": symbol, "status": "NO_VALID_DAILY_ROW"}
    row = valid.iloc[-1]
    return {
        "symbol": symbol,
        "trade_date": str(row["trade_date"]),
        "raw_close": float(row["raw_close"]),
        "pre_adj_close": float(row["pre_adj_close"]),
        "volume_raw": float(row["volume_raw"]),
        "volume_shares": float(row["volume_shares"]),
        "amount_cny": float(row["amount_cny"]),
        "open_09_30": None,
        "open_14_57": None,
        "final_minute_close": None,
        "official_daily_close": float(row["raw_close"]),
        "minute_status": "MISSING_HISTORICAL_SOURCE",
    }


def sample_index_row(symbol: str) -> dict[str, Any]:
    path = DATA_ROOT / "daily_indices" / f"symbol={symbol}" / "daily.parquet"
    if not path.exists():
        return {"symbol": symbol, "status": "MISSING"}
    frame = pd.read_parquet(path)
    row = frame.iloc[-1]
    return {
        "symbol": symbol,
        "trade_date": str(row["trade_date"]),
        "raw_close": float(row["close"]),
        "volume": float(row["volume"]),
        "amount_cny": None,
        "status": "DAILY_ONLY",
    }


def corporate_action_sample(pool: list[str]) -> dict[str, Any] | None:
    for raw_code in pool:
        symbol = canonical_symbol(raw_code)
        path = DATA_ROOT / "daily" / f"symbol={symbol}" / "daily.parquet"
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        factor = frame["adj_factor_close_ratio"]
        change = factor.notna() & factor.shift().notna() & ((factor - factor.shift()).abs() > 1e-8)
        indices = np.flatnonzero(change.to_numpy())
        if len(indices) == 0:
            continue
        index = int(indices[-1])
        before = frame.iloc[index - 1]
        after = frame.iloc[index]
        return {
            "symbol": symbol,
            "status": "PROVIDER_QFQ_FACTOR_CHANGE_NOT_OFFICIAL_EVENT_PROOF",
            "before": {
                "trade_date": str(before["trade_date"]),
                "raw_close": float(before["raw_close"]),
                "pre_adj_close": float(before["pre_adj_close"]),
                "factor": float(before["adj_factor_close_ratio"]),
            },
            "after": {
                "trade_date": str(after["trade_date"]),
                "raw_close": float(after["raw_close"]),
                "pre_adj_close": float(after["pre_adj_close"]),
                "factor": float(after["adj_factor_close_ratio"]),
            },
        }
    return None


def main() -> int:
    args = parse_args()
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    pool = parse_strategy_pool()
    expected_symbols = [canonical_symbol(code) for code in pool]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    universe_pass = len(pool) == 152 and len(set(pool)) == 152
    universe_pass &= all(exchange_for(code) in {"SH", "SZ"} for code in pool)
    universe_pass &= manifest.get("universe_sha256") == universe_sha256(pool)
    if not universe_pass:
        failures.append("UNIVERSE_CONTRACT_FAILED")
    if manifest.get("strategy_source_sha256") != strategy_sha256():
        failures.append("STRATEGY_SOURCE_HASH_MISMATCH")
    if manifest.get("contract_version") != CONTRACT_VERSION:
        failures.append("CONTRACT_VERSION_MISMATCH")

    master_path = DATA_ROOT / "metadata" / "etf_security_master.parquet"
    master = pd.read_parquet(master_path)
    master["list_date"] = pd.to_datetime(master["list_date"]).dt.date
    master_unique = not master["raw_code"].duplicated().any()
    master_complete = set(master["raw_code"]) == set(pool) and len(master) == 152
    master_mapping = all(
        row.symbol == canonical_symbol(row.raw_code)
        and row.exchange == exchange_for(row.raw_code)
        and row.security_type == "ETF"
        for row in master.itertuples()
    )
    master_dates = master["list_date"].notna().all()
    if not all([master_unique, master_complete, master_mapping, master_dates]):
        failures.append("SECURITY_MASTER_CONTRACT_FAILED")

    calendar_path = DATA_ROOT / "metadata" / "trade_calendar.parquet"
    calendar = pd.read_parquet(calendar_path)
    calendar["trade_date"] = pd.to_datetime(calendar["trade_date"]).dt.date
    calendar_dates = list(calendar["trade_date"])
    calendar_pass = (
        len(calendar_dates) == len(set(calendar_dates))
        and calendar_dates == sorted(calendar_dates)
        and bool(manifest["trade_calendar_source"]["exact_match_through_end_date"])
    )
    if not calendar_pass:
        failures.append("TRADE_CALENDAR_CONTRACT_FAILED")
    calendar_set = set(calendar_dates)
    requested_end = pd.Timestamp(manifest["request"]["end_date"]).date()

    master_by_code = master.set_index("raw_code")
    missing_partitions: list[str] = []
    daily_duplicate_rows = 0
    daily_nonmonotonic_symbols: list[str] = []
    daily_nonfinite_valid_rows = 0
    daily_ohlc_invalid_rows = 0
    daily_before_list_valid_rows = 0
    daily_dates_not_in_calendar = 0
    provider_key_mismatches = 0
    forward_fill_insertions = 0
    amount_unit_medians: dict[str, float] = {}
    amount_unit_failures: list[str] = []
    history_121: dict[str, str | None] = {}
    missing_session_counts: dict[str, int] = {}
    total_rows = 0
    total_valid_rows = 0

    for raw_code, symbol in zip(pool, expected_symbols, strict=True):
        path = DATA_ROOT / "daily" / f"symbol={symbol}" / "daily.parquet"
        if not path.exists():
            missing_partitions.append(symbol)
            continue
        frame = pd.read_parquet(path)
        total_rows += len(frame)
        missing_columns = REQUIRED_DAILY_COLUMNS - set(frame.columns)
        if missing_columns:
            failures.append(f"DAILY_SCHEMA_MISSING:{symbol}:{sorted(missing_columns)}")
            continue
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        duplicate_count = int(frame.duplicated(["symbol", "trade_date"]).sum())
        daily_duplicate_rows += duplicate_count
        if list(frame["trade_date"]) != sorted(frame["trade_date"]):
            daily_nonmonotonic_symbols.append(symbol)
        if not (frame["symbol"] == symbol).all() or not (frame["raw_code"] == raw_code).all():
            failures.append(f"DAILY_SYMBOL_MAPPING:{symbol}")
        valid = frame[frame["row_status"] == "VALID"]
        total_valid_rows += len(valid)
        valid_numeric_columns = [*PRICE_COLUMNS, "volume_raw", "amount_cny"]
        finite = np.isfinite(valid[valid_numeric_columns]).all(axis=1)
        positive = (valid[valid_numeric_columns] > 0).all(axis=1)
        daily_nonfinite_valid_rows += int((~finite | ~positive).sum())
        daily_ohlc_invalid_rows += check_ohlc(valid, "raw") + check_ohlc(valid, "pre_adj")
        list_date = master_by_code.loc[raw_code, "list_date"]
        daily_before_list_valid_rows += int((valid["trade_date"] < list_date).sum())
        daily_dates_not_in_calendar += int((~valid["trade_date"].isin(calendar_set)).sum())

        raw_count, raw_dates = raw_provider_key_count(raw_code, "raw")
        qfq_count, qfq_dates = raw_provider_key_count(raw_code, "qfq")
        normalized_dates = {str(item) for item in frame["trade_date"]}
        if len(frame) != len(raw_dates | qfq_dates) or normalized_dates != raw_dates | qfq_dates:
            provider_key_mismatches += 1
        inserted = normalized_dates - (raw_dates | qfq_dates)
        forward_fill_insertions += len(inserted)
        if raw_count != len(raw_dates) or qfq_count != len(qfq_dates):
            failures.append(f"PROVIDER_DUPLICATE_DATE:{symbol}")

        eligible_calendar = {item for item in calendar_set if list_date <= item <= requested_end}
        missing_session_counts[symbol] = len(eligible_calendar - set(frame["trade_date"]))
        history_121[symbol] = str(valid.iloc[120]["trade_date"]) if len(valid) >= 121 else None

        liquid = valid[(valid["volume_raw"] > 0) & (valid["raw_close"] > 0)]
        if not liquid.empty:
            ratio = liquid["amount_cny"] / (liquid["raw_close"] * liquid["volume_raw"])
            median = float(ratio.replace([np.inf, -np.inf], np.nan).dropna().median())
            amount_unit_medians[symbol] = median
            if not 80.0 <= median <= 120.0:
                amount_unit_failures.append(symbol)

    if missing_partitions:
        failures.append(f"MISSING_DAILY_PARTITIONS:{len(missing_partitions)}")
    if daily_duplicate_rows:
        failures.append(f"DAILY_DUPLICATE_ROWS:{daily_duplicate_rows}")
    if daily_nonmonotonic_symbols:
        failures.append(f"DAILY_NONMONOTONIC_SYMBOLS:{len(daily_nonmonotonic_symbols)}")
    if daily_nonfinite_valid_rows:
        failures.append(f"DAILY_INVALID_VALID_ROWS:{daily_nonfinite_valid_rows}")
    if daily_ohlc_invalid_rows:
        failures.append(f"DAILY_OHLC_INVALID_ROWS:{daily_ohlc_invalid_rows}")
    if daily_before_list_valid_rows:
        failures.append(f"VALID_ROWS_BEFORE_LIST_DATE:{daily_before_list_valid_rows}")
    if daily_dates_not_in_calendar:
        failures.append(f"VALID_DATES_NOT_IN_CALENDAR:{daily_dates_not_in_calendar}")
    if provider_key_mismatches:
        failures.append(f"PROVIDER_NORMALIZED_KEY_MISMATCH:{provider_key_mismatches}")
    if forward_fill_insertions:
        failures.append(f"FORWARD_FILL_INSERTIONS:{forward_fill_insertions}")
    if amount_unit_failures:
        failures.append(f"AMOUNT_VOLUME_UNIT_FAILURES:{len(amount_unit_failures)}")

    anchor_coverage: dict[str, Any] = {}
    for symbol in ["000852.SH", "000300.SH"]:
        path = DATA_ROOT / "daily_indices" / f"symbol={symbol}" / "daily.parquet"
        if not path.exists():
            failures.append(f"MISSING_ANCHOR:{symbol}")
            anchor_coverage[symbol] = {"rows": 0}
            continue
        frame = pd.read_parquet(path)
        anchor_coverage[symbol] = {
            "rows": len(frame),
            "first_date": str(frame["trade_date"].min()),
            "last_date": str(frame["trade_date"].max()),
            "duplicate_dates": int(frame["trade_date"].duplicated().sum()),
        }
        if frame["trade_date"].duplicated().any() or not np.isfinite(frame["close"]).all():
            failures.append(f"ANCHOR_DATA_INVALID:{symbol}")
    if "510300.SH" in missing_partitions:
        failures.append("MISSING_EXIT_ANCHOR:510300.SH")

    # Minute and adjustment gates intentionally fail closed in this partial build.
    minute_rows = 0
    minute_critical_coverage = {
        "09_30_open": {"covered": 0, "expected": total_valid_rows, "status": "MISSING"},
        "14_57_open": {"covered": 0, "expected": total_valid_rows, "status": "MISSING"},
        "final_close": {"covered": 0, "expected": total_valid_rows, "status": "MISSING"},
        "opening_auction": {"covered": 0, "expected": total_valid_rows, "status": "MISSING"},
    }
    failures.extend(
        [
            "HISTORICAL_MINUTE_DATA_MISSING",
            "OPEN_AUCTION_DATA_MISSING",
            "DAILY_MINUTE_PRICE_BASIS_UNVERIFIED",
            "SUPERMIND_PRE_ADJUSTMENT_EQUIVALENCE_UNVERIFIED",
        ]
    )

    present_symbols = set(expected_symbols) - set(missing_partitions)
    sh_samples = [
        canonical_symbol(code)
        for code in pool
        if exchange_for(code) == "SH" and canonical_symbol(code) in present_symbols
    ][:5]
    sz_samples = [
        canonical_symbol(code)
        for code in pool
        if exchange_for(code) == "SZ" and canonical_symbol(code) in present_symbols
    ][:5]
    ordered_master = master.sort_values("list_date")
    early_symbol = str(ordered_master.iloc[0]["symbol"])
    late_symbol = str(ordered_master.iloc[-1]["symbol"])
    sample_symbols = list(
        dict.fromkeys(sh_samples + sz_samples + [early_symbol, late_symbol, "510300.SH"])
    )
    samples = {
        "selection": {
            "shanghai": sh_samples,
            "shenzhen": sz_samples,
            "early_listed": early_symbol,
            "late_listed": late_symbol,
        },
        "etf_latest_rows": [sample_daily_row(symbol) for symbol in sample_symbols],
        "indices_latest_rows": [sample_index_row("000852.SH"), sample_index_row("000300.SH")],
        "corporate_action_candidate": corporate_action_sample(pool),
    }

    metrics.update(
        {
            "universe_expected": 152,
            "universe_parsed": len(pool),
            "security_master_rows": len(master),
            "daily_rows": int(total_rows),
            "daily_valid_rows": int(total_valid_rows),
            "minute_rows": minute_rows,
            "missing_daily_partitions": missing_partitions,
            "daily_duplicate_rows": daily_duplicate_rows,
            "daily_nonmonotonic_symbols": daily_nonmonotonic_symbols,
            "daily_nonfinite_valid_rows": daily_nonfinite_valid_rows,
            "daily_ohlc_invalid_rows": daily_ohlc_invalid_rows,
            "daily_before_list_valid_rows": daily_before_list_valid_rows,
            "daily_dates_not_in_calendar": daily_dates_not_in_calendar,
            "provider_normalized_key_mismatches": provider_key_mismatches,
            "forward_fill_insertions": forward_fill_insertions,
            "amount_unit_median_ratio_cny_per_close_volume_native": amount_unit_medians,
            "amount_unit_failures": amount_unit_failures,
            "history_first_121_date": history_121,
            "missing_or_suspended_unresolved_sessions": missing_session_counts,
            "anchor_coverage": anchor_coverage,
            "minute_critical_coverage": minute_critical_coverage,
            "calendar_rows": len(calendar),
            "calendar_valid": calendar_pass,
            "data_bytes": directory_bytes(DATA_ROOT),
        }
    )

    readiness = False
    result = {
        "validation_version": "v6-market-data-validation-1",
        "manifest_path": str(args.manifest),
        "manifest_sha256_before_validation_update": sha256_file(args.manifest),
        "status": "FAIL" if failures else "PASS",
        "v6_data_ready": readiness,
        "checks": {
            "universe": "PASS" if universe_pass else "FAIL",
            "security_master": (
                "PASS"
                if all([master_unique, master_complete, master_mapping, master_dates])
                else "FAIL"
            ),
            "daily": "PASS" if not any("DAILY" in item for item in failures) else "FAIL",
            "point_in_time_listing_gate": (
                "PASS" if daily_before_list_valid_rows == 0 and master_dates else "FAIL"
            ),
            "turnover_amount_cny": "PASS" if not amount_unit_failures else "FAIL",
            "no_forward_fill": "PASS" if forward_fill_insertions == 0 else "FAIL",
            "trade_calendar": "PASS" if calendar_pass else "FAIL",
            "minute": "FAIL",
            "opening_auction": "FAIL",
            "supermind_pre_adjustment_equivalence": "UNVERIFIED",
            "daily_minute_price_basis": "UNVERIFIED",
        },
        "metrics": metrics,
        "samples": samples,
        "warnings": warnings,
        "failures": failures,
    }
    atomic_write_json(VALIDATION_PATH, result)

    manifest["validation_status"] = result["status"]
    manifest["validation_path"] = str(VALIDATION_PATH)
    manifest["validation_failures"] = failures
    manifest["duplicate_counts"]["daily_symbol_date"] = daily_duplicate_rows
    manifest["missing_counts"]["daily_symbol_partitions"] = len(missing_partitions)
    manifest["missing_counts"]["minute_symbol_partitions"] = len(pool)
    manifest["storage_bytes"] = directory_bytes(DATA_ROOT)
    atomic_write_json(args.manifest, manifest)

    print(f"VALIDATION_STATUS {result['status']}")
    print(f"V6_DATA_READY {'YES' if readiness else 'NO'}")
    print(f"DAILY_ROWS {total_rows}")
    print(f"MINUTE_ROWS {minute_rows}")
    print(f"DUPLICATE_ROWS {daily_duplicate_rows}")
    print(f"FORWARD_FILL_INSERTIONS {forward_fill_insertions}")
    print(f"FAILURES {len(failures)}")
    for failure in failures:
        print(f"- {failure}")
    print(f"VALIDATION_REPORT {VALIDATION_PATH}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
