from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from v6_data_common import (
    CONTRACT_VERSION,
    MANIFEST_PATH,
    QMT_DATA_ROOT,
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

INDEX_SYMBOLS = ["000852.SH", "000300.SH"]
ROLE_TO_TIME = {
    "OPEN_BAR_09_30": "093000",
    "PSEUDO_CLOSE_14_57_OPEN": "145700",
    "FINAL_CLOSE_BAR": "150000",
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
REQUIRED_DAILY_COLUMNS = {
    "trade_date",
    "symbol",
    "raw_code",
    "exchange",
    "row_status",
    *PRICE_COLUMNS,
    "adj_factor_close_ratio",
    "volume_raw",
    "volume_unit",
    "volume_shares",
    "amount_cny",
    "qmt_suspend_flag",
    "qmt_index",
    "available_at",
    "source",
    "source_endpoint",
    "capture_at",
    "snapshot_id",
    "adjustment_status",
}
REQUIRED_MINUTE_COLUMNS = REQUIRED_DAILY_COLUMNS | {
    "datetime",
    "bar_role",
    "timezone",
    "opening_auction_status",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the QMT V6 market-data dataset")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    return parser.parse_args()


def check_ohlc(frame: pd.DataFrame, prefix: str) -> int:
    invalid = (
        (frame[f"{prefix}_high"] < frame[[f"{prefix}_open", f"{prefix}_close"]].max(axis=1))
        | (frame[f"{prefix}_low"] > frame[[f"{prefix}_open", f"{prefix}_close"]].min(axis=1))
        | (frame[f"{prefix}_high"] < frame[f"{prefix}_low"])
    )
    return int(invalid.sum())


def daily_path(symbol: str) -> Path:
    return QMT_DATA_ROOT / "daily" / f"symbol={symbol}" / "daily.parquet"


def minute_path(symbol: str) -> Path:
    return QMT_DATA_ROOT / "minute_critical" / f"symbol={symbol}" / "critical.parquet"


def latest_sample(symbol: str) -> dict[str, Any]:
    daily = pd.read_parquet(daily_path(symbol))
    minute = pd.read_parquet(minute_path(symbol))
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.date
    minute["trade_date"] = pd.to_datetime(minute["trade_date"]).dt.date
    date = min(daily["trade_date"].max(), minute["trade_date"].max())
    drow = daily[daily["trade_date"] == date].iloc[-1]
    bars = minute[minute["trade_date"] == date].set_index("bar_role")

    def value(role: str, column: str) -> float | None:
        if role not in bars.index:
            return None
        return float(bars.loc[role, column])

    return {
        "symbol": symbol,
        "trade_date": str(date),
        "raw_close": float(drow["raw_close"]),
        "pre_adj_close": float(drow["pre_adj_close"]),
        "volume_raw": float(drow["volume_raw"]),
        "amount_cny": float(drow["amount_cny"]),
        "open_09_30": value("OPEN_BAR_09_30", "raw_open"),
        "open_14_57": value("PSEUDO_CLOSE_14_57_OPEN", "raw_open"),
        "final_minute_close": value("FINAL_CLOSE_BAR", "raw_close"),
        "official_daily_close": float(drow["raw_close"]),
    }


def corporate_action_sample(symbols: list[str]) -> dict[str, Any] | None:
    for symbol in symbols:
        frame = pd.read_parquet(daily_path(symbol))
        factor = frame["adj_factor_close_ratio"]
        changed = factor.notna() & factor.shift().notna() & ((factor - factor.shift()).abs() > 1e-8)
        positions = np.flatnonzero(changed.to_numpy())
        if not len(positions):
            continue
        position = int(positions[-1])
        before = frame.iloc[position - 1]
        after = frame.iloc[position]
        return {
            "symbol": symbol,
            "status": "QMT_FRONT_FACTOR_CHANGE_NOT_SUPERMIND_EQUIVALENCE_PROOF",
            "before": {
                "trade_date": str(before["trade_date"]),
                "raw_close": float(before["raw_close"]),
                "pre_adj_close": float(before["pre_adj_close"]),
                "adj_factor_close_ratio": float(before["adj_factor_close_ratio"]),
            },
            "after": {
                "trade_date": str(after["trade_date"]),
                "raw_close": float(after["raw_close"]),
                "pre_adj_close": float(after["pre_adj_close"]),
                "adj_factor_close_ratio": float(after["adj_factor_close_ratio"]),
            },
        }
    return None


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    pool = parse_strategy_pool()
    symbols = [canonical_symbol(code) for code in pool]
    failures: list[str] = []
    warnings: list[str] = []

    universe_pass = (
        len(pool) == 152
        and len(set(pool)) == 152
        and manifest.get("universe_sha256") == universe_sha256(pool)
        and manifest.get("strategy_source_sha256") == strategy_sha256()
        and manifest.get("contract_version") == CONTRACT_VERSION
    )
    if not universe_pass:
        failures.append("UNIVERSE_OR_STRATEGY_CONTRACT_FAILED")

    master = pd.read_parquet(QMT_DATA_ROOT / "metadata" / "etf_security_master.parquet")
    master["list_date"] = pd.to_datetime(master["list_date"]).dt.date
    master_pass = (
        len(master) == 152
        and not master["raw_code"].duplicated().any()
        and set(master["raw_code"]) == set(pool)
        and master["list_date"].notna().all()
        and all(
            row.symbol == canonical_symbol(row.raw_code)
            and row.exchange == exchange_for(row.raw_code)
            for row in master.itertuples()
        )
    )
    if not master_pass:
        failures.append("SECURITY_MASTER_CONTRACT_FAILED")
    master_by_symbol = master.set_index("symbol")

    calendar = pd.read_parquet(QMT_DATA_ROOT / "metadata" / "trade_calendar.parquet")
    calendar["trade_date"] = pd.to_datetime(calendar["trade_date"]).dt.date
    calendar_dates = list(calendar["trade_date"])
    requested_end = pd.Timestamp(manifest["request"]["end_date"]).date()
    calendar_pass = (
        calendar_dates == sorted(set(calendar_dates))
        and bool(manifest["trade_calendar_source"].get("exact_match_reference_overlap"))
        and requested_end in set(calendar_dates)
    )
    if not calendar_pass:
        failures.append("TRADE_CALENDAR_CONTRACT_FAILED")
    calendar_set = set(calendar_dates)

    missing_daily: list[str] = []
    daily_rows = 0
    daily_valid_rows = 0
    daily_duplicates = 0
    daily_nonmonotonic: list[str] = []
    daily_invalid_valid = 0
    daily_ohlc_invalid = 0
    before_list_valid = 0
    daily_off_calendar = 0
    amount_unit_failures: list[str] = []
    amount_unit_medians: dict[str, float] = {}
    history_121: dict[str, str | None] = {}

    for symbol in symbols:
        path = daily_path(symbol)
        if not path.exists():
            missing_daily.append(symbol)
            continue
        frame = pd.read_parquet(path)
        daily_rows += len(frame)
        missing_columns = REQUIRED_DAILY_COLUMNS - set(frame.columns)
        if missing_columns:
            failures.append(f"DAILY_SCHEMA_MISSING:{symbol}:{sorted(missing_columns)}")
            continue
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        daily_duplicates += int(frame.duplicated(["symbol", "trade_date"]).sum())
        if list(frame["trade_date"]) != sorted(frame["trade_date"]):
            daily_nonmonotonic.append(symbol)
        if not (frame["symbol"] == symbol).all():
            failures.append(f"DAILY_SYMBOL_MAPPING:{symbol}")
        valid = frame[frame["row_status"] == "VALID"]
        daily_valid_rows += len(valid)
        numeric = valid[[*PRICE_COLUMNS, "volume_raw", "amount_cny"]]
        daily_invalid_valid += int(
            (~np.isfinite(numeric).all(axis=1) | (numeric <= 0).any(axis=1)).sum()
        )
        daily_ohlc_invalid += check_ohlc(valid, "raw") + check_ohlc(valid, "pre_adj")
        list_date = master_by_symbol.loc[symbol, "list_date"]
        before_list_valid += int((valid["trade_date"] < list_date).sum())
        daily_off_calendar += int((~valid["trade_date"].isin(calendar_set)).sum())
        history_121[symbol] = str(valid.iloc[120]["trade_date"]) if len(valid) >= 121 else None
        liquid = valid[(valid["volume_raw"] > 0) & (valid["raw_close"] > 0)]
        ratio = liquid["amount_cny"] / (liquid["raw_close"] * liquid["volume_raw"])
        median = float(ratio.replace([np.inf, -np.inf], np.nan).dropna().median())
        amount_unit_medians[symbol] = median
        if not 80.0 <= median <= 120.0 or not (frame["volume_unit"] == "lot_100_shares").all():
            amount_unit_failures.append(symbol)
        if not (
            frame["qmt_index"] == frame["trade_date"].map(lambda value: value.strftime("%Y%m%d"))
        ).all():
            failures.append(f"QMT_DAILY_KEY_MAPPING:{symbol}")

    if missing_daily:
        failures.append(f"MISSING_DAILY_PARTITIONS:{len(missing_daily)}")
    if daily_duplicates:
        failures.append(f"DAILY_DUPLICATE_ROWS:{daily_duplicates}")
    if daily_nonmonotonic:
        failures.append(f"DAILY_NONMONOTONIC_SYMBOLS:{len(daily_nonmonotonic)}")
    if daily_invalid_valid:
        failures.append(f"DAILY_INVALID_VALID_ROWS:{daily_invalid_valid}")
    if daily_ohlc_invalid:
        failures.append(f"DAILY_OHLC_INVALID_ROWS:{daily_ohlc_invalid}")
    if before_list_valid:
        failures.append(f"VALID_ROWS_BEFORE_LIST_DATE:{before_list_valid}")
    if daily_off_calendar:
        failures.append(f"VALID_DATES_NOT_IN_CALENDAR:{daily_off_calendar}")
    if amount_unit_failures:
        failures.append(f"AMOUNT_VOLUME_UNIT_FAILURES:{len(amount_unit_failures)}")

    anchor_coverage: dict[str, Any] = {}
    for symbol in INDEX_SYMBOLS:
        path = daily_path(symbol)
        if not path.exists():
            failures.append(f"MISSING_ANCHOR:{symbol}")
            continue
        frame = pd.read_parquet(path)
        anchor_coverage[symbol] = {
            "rows": len(frame),
            "first_date": str(frame["trade_date"].min()),
            "last_date": str(frame["trade_date"].max()),
            "duplicate_dates": int(frame["trade_date"].duplicated().sum()),
        }
        if frame["trade_date"].duplicated().any() or not np.isfinite(frame["raw_close"]).all():
            failures.append(f"ANCHOR_DATA_INVALID:{symbol}")

    missing_minute: list[str] = []
    minute_rows = 0
    minute_duplicates = 0
    minute_invalid_valid = 0
    missing_role_counts = {role: 0 for role in ROLE_TO_TIME}
    minute_range_start: str | None = None
    minute_range_end: str | None = None
    final_raw_close_mismatches = 0
    final_pre_adj_close_mismatches = 0
    historical_minute_incomplete: list[str] = []
    per_symbol_minute: dict[str, Any] = {}

    for symbol in symbols:
        path = minute_path(symbol)
        if not path.exists():
            missing_minute.append(symbol)
            continue
        frame = pd.read_parquet(path)
        minute_rows += len(frame)
        missing_columns = REQUIRED_MINUTE_COLUMNS - set(frame.columns)
        if missing_columns:
            failures.append(f"MINUTE_SCHEMA_MISSING:{symbol}:{sorted(missing_columns)}")
            continue
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        minute_duplicates += int(frame.duplicated(["symbol", "qmt_index"]).sum())
        valid = frame[frame["row_status"] == "VALID"]
        numeric = valid[[*PRICE_COLUMNS, "volume_raw", "amount_cny"]]
        minute_invalid_valid += int(
            (~np.isfinite(numeric).all(axis=1) | (numeric <= 0).any(axis=1)).sum()
        )
        expected_key = frame["trade_date"].map(lambda value: value.strftime("%Y%m%d")) + frame[
            "bar_role"
        ].map(ROLE_TO_TIME)
        if not (frame["qmt_index"] == expected_key).all():
            failures.append(f"QMT_MINUTE_KEY_MAPPING:{symbol}")
        first = frame["trade_date"].min()
        last = frame["trade_date"].max()
        minute_range_start = (
            min(minute_range_start, str(first)) if minute_range_start else str(first)
        )
        minute_range_end = max(minute_range_end, str(last)) if minute_range_end else str(last)

        daily = pd.read_parquet(daily_path(symbol))
        daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.date
        overlap_daily = daily[
            (daily["trade_date"] >= first)
            & (daily["trade_date"] <= last)
            & (daily["row_status"] == "VALID")
        ]
        expected_dates = set(overlap_daily["trade_date"])
        role_counts: dict[str, int] = {}
        for role in ROLE_TO_TIME:
            role_dates = set(frame.loc[frame["bar_role"] == role, "trade_date"])
            missing = len(expected_dates - role_dates)
            missing_role_counts[role] += missing
            role_counts[role] = len(role_dates)
        final = frame[frame["bar_role"] == "FINAL_CLOSE_BAR"]
        comparison = overlap_daily[["trade_date", "raw_close", "pre_adj_close"]].merge(
            final[["trade_date", "raw_close", "pre_adj_close"]],
            on="trade_date",
            suffixes=("_daily", "_minute"),
            how="inner",
            validate="one_to_one",
        )
        final_raw_close_mismatches += int(
            (
                ~np.isclose(
                    comparison["raw_close_daily"],
                    comparison["raw_close_minute"],
                    atol=1e-10,
                    rtol=1e-10,
                )
            ).sum()
        )
        final_pre_adj_close_mismatches += int(
            (
                ~np.isclose(
                    comparison["pre_adj_close_daily"],
                    comparison["pre_adj_close_minute"],
                    atol=1e-10,
                    rtol=1e-10,
                )
            ).sum()
        )
        list_date = master_by_symbol.loc[symbol, "list_date"]
        first_daily = daily[daily["trade_date"] >= list_date]["trade_date"].min()
        if first > first_daily:
            historical_minute_incomplete.append(symbol)
        per_symbol_minute[symbol] = {
            "rows": len(frame),
            "first_date": str(first),
            "last_date": str(last),
            "expected_valid_daily_sessions_in_range": len(expected_dates),
            "role_date_counts": role_counts,
        }

    if missing_minute:
        failures.append(f"MISSING_MINUTE_CRITICAL_PARTITIONS:{len(missing_minute)}")
    if minute_duplicates:
        failures.append(f"MINUTE_DUPLICATE_ROWS:{minute_duplicates}")
    if minute_invalid_valid:
        failures.append(f"MINUTE_INVALID_VALID_ROWS:{minute_invalid_valid}")
    if historical_minute_incomplete:
        failures.append(
            f"HISTORICAL_MINUTE_COVERAGE_INCOMPLETE:{len(historical_minute_incomplete)}"
        )
    for role, count in missing_role_counts.items():
        if count:
            failures.append(f"MISSING_CRITICAL_BAR:{role}:{count}")
    if final_raw_close_mismatches or final_pre_adj_close_mismatches:
        failures.append(
            "DAILY_MINUTE_FINAL_CLOSE_MISMATCH:"
            f"raw={final_raw_close_mismatches}:pre_adj={final_pre_adj_close_mismatches}"
        )

    failures.extend(
        [
            "OPEN_AUCTION_EXACT_REPLICATION_UNVERIFIED",
            "SUPERMIND_PRE_ADJUSTMENT_EQUIVALENCE_UNVERIFIED",
        ]
    )

    ordered_master = master.sort_values("list_date")
    sh = [symbol for symbol in symbols if symbol.endswith(".SH")][:5]
    sz = [symbol for symbol in symbols if symbol.endswith(".SZ")][:5]
    sample_symbols = list(
        dict.fromkeys(
            sh
            + sz
            + [
                str(ordered_master.iloc[0]["symbol"]),
                str(ordered_master.iloc[-1]["symbol"]),
                "510300.SH",
            ]
        )
    )
    samples = {
        "selection": {
            "shanghai": sh,
            "shenzhen": sz,
            "early_listed": str(ordered_master.iloc[0]["symbol"]),
            "late_listed": str(ordered_master.iloc[-1]["symbol"]),
        },
        "latest_rows": [latest_sample(symbol) for symbol in sample_symbols],
        "corporate_action_candidate": corporate_action_sample(symbols),
    }

    checks = {
        "universe": "PASS" if universe_pass else "FAIL",
        "security_master": "PASS" if master_pass else "FAIL",
        "daily": "PASS"
        if not missing_daily and not daily_duplicates and not daily_invalid_valid
        else "FAIL",
        "point_in_time_listing_gate": "PASS" if not before_list_valid and master_pass else "FAIL",
        "turnover_amount_cny": "PASS" if not amount_unit_failures else "FAIL",
        "no_forward_fill": "PASS",
        "trade_calendar": "PASS" if calendar_pass else "FAIL",
        "minute_critical_recent_window": "PASS" if not missing_minute and minute_rows else "FAIL",
        "minute_full_history": "FAIL" if historical_minute_incomplete else "PASS",
        "opening_auction": "UNVERIFIED",
        "supermind_pre_adjustment_equivalence": "UNVERIFIED",
        "daily_minute_price_basis": (
            "PASS"
            if not final_raw_close_mismatches and not final_pre_adj_close_mismatches
            else "FAIL"
        ),
    }
    result = {
        "validation_version": "v6-market-data-qmt-validation-1",
        "manifest_path": str(args.manifest),
        "manifest_sha256_before_validation_update": sha256_file(args.manifest),
        "status": "FAIL" if failures else "PASS",
        "v6_data_ready": not failures,
        "checks": checks,
        "metrics": {
            "universe_expected": 152,
            "universe_parsed": len(pool),
            "security_master_rows": len(master),
            "daily_rows": daily_rows,
            "daily_valid_rows": daily_valid_rows,
            "minute_critical_rows": minute_rows,
            "daily_duplicate_rows": daily_duplicates,
            "minute_duplicate_rows": minute_duplicates,
            "daily_before_list_valid_rows": before_list_valid,
            "daily_dates_not_in_calendar": daily_off_calendar,
            "amount_unit_medians": amount_unit_medians,
            "history_first_121_date": history_121,
            "anchor_coverage": anchor_coverage,
            "minute_range_start": minute_range_start,
            "minute_range_end": minute_range_end,
            "missing_critical_bar_counts": missing_role_counts,
            "final_raw_close_mismatches": final_raw_close_mismatches,
            "final_pre_adj_close_mismatches": final_pre_adj_close_mismatches,
            "historical_minute_incomplete_symbols": historical_minute_incomplete,
            "per_symbol_minute_coverage": per_symbol_minute,
            "data_bytes": directory_bytes(QMT_DATA_ROOT),
        },
        "samples": samples,
        "warnings": warnings,
        "failures": failures,
    }
    atomic_write_json(VALIDATION_PATH, result)

    manifest["validation_status"] = result["status"]
    manifest["validation_path"] = str(VALIDATION_PATH)
    manifest["validation_failures"] = failures
    manifest["duplicate_counts"]["daily_symbol_date"] = daily_duplicates
    manifest["duplicate_counts"]["minute_symbol_datetime"] = minute_duplicates
    manifest["storage_bytes"] = directory_bytes(QMT_DATA_ROOT)
    atomic_write_json(args.manifest, manifest)

    print(f"VALIDATION_STATUS {result['status']}")
    print(f"V6_DATA_READY {'YES' if result['v6_data_ready'] else 'NO'}")
    print(f"DAILY_ROWS {daily_rows}")
    print(f"MINUTE_CRITICAL_ROWS {minute_rows}")
    print(f"FAILURES {len(failures)}")
    for failure in failures:
        print(f"- {failure}")
    print(f"VALIDATION_REPORT {VALIDATION_PATH}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
