from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from v6_data_common import (
    MANIFEST_DIR,
    QMT_DATA_ROOT,
    REPO_ROOT,
    atomic_write_json,
    atomic_write_parquet,
    canonical_symbol,
    parse_strategy_pool,
    sha256_file,
    strategy_sha256,
)

DEFAULT_EVALUATION_START = date(2025, 8, 28)
BOUNDARY_DATE = date(2025, 8, 27)
OUTPUT_PATH = QMT_DATA_ROOT / "execution_availability" / "critical_execution.parquet"
MANIFEST_PATH = MANIFEST_DIR / "v6_open_execution_availability.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build fail-closed 09:30 execution availability for frozen V6"
    )
    parser.add_argument(
        "--evaluation-start",
        type=date.fromisoformat,
        default=DEFAULT_EVALUATION_START,
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument(
        "--market-anchors",
        nargs="*",
        default=[],
        help="optional non-ETF symbols needed only for shadow market-state evaluation",
    )
    return parser.parse_args()


def daily_path(symbol: str) -> Path:
    return QMT_DATA_ROOT / "daily" / f"symbol={symbol}" / "daily.parquet"


def minute_path(symbol: str) -> Path:
    return QMT_DATA_ROOT / "minute_critical" / f"symbol={symbol}" / "critical.parquet"


def normalize_dates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date
    return result


def role_frame(
    minute: pd.DataFrame,
    *,
    role: str,
    prefix: str,
    price_columns: tuple[str, str],
) -> pd.DataFrame:
    selected = minute[minute["bar_role"].eq(role)].copy()
    raw_price, adjusted_price = price_columns
    selected = selected[
        [
            "trade_date",
            raw_price,
            adjusted_price,
            "row_status",
            "datetime",
            "available_at",
            "snapshot_id",
        ]
    ].rename(
        columns={
            raw_price: f"{prefix}_raw_price",
            adjusted_price: f"{prefix}_pre_adj_price",
            "row_status": f"{prefix}_row_status",
            "datetime": f"{prefix}_bar_datetime",
            "available_at": f"{prefix}_bar_available_at",
            "snapshot_id": f"{prefix}_bar_snapshot_id",
        }
    )
    if selected["trade_date"].duplicated().any():
        raise ValueError(f"duplicate {role} rows")
    return selected


def build_symbol_availability(
    symbol: str,
    daily: pd.DataFrame,
    minute: pd.DataFrame,
    *,
    evaluation_start: date,
    partition_sha256: str,
) -> pd.DataFrame:
    daily = normalize_dates(daily)
    minute = normalize_dates(minute)
    if minute.empty:
        raise ValueError(f"empty critical-minute partition: {symbol}")

    minute_start = minute["trade_date"].min()
    minute_end = minute["trade_date"].max()
    start = max(evaluation_start, minute_start)
    expected = daily[
        daily["row_status"].eq("VALID")
        & daily["trade_date"].between(start, minute_end)
    ][["trade_date"]].drop_duplicates()
    expected["symbol"] = symbol

    opens = role_frame(
        minute,
        role="OPEN_BAR_09_30",
        prefix="open",
        price_columns=("raw_open", "pre_adj_open"),
    )
    signals = role_frame(
        minute,
        role="PSEUDO_CLOSE_14_57_OPEN",
        prefix="signal",
        price_columns=("raw_open", "pre_adj_open"),
    )
    closes = role_frame(
        minute,
        role="FINAL_CLOSE_BAR",
        prefix="close",
        price_columns=("raw_close", "pre_adj_close"),
    )
    result = expected.merge(opens, on="trade_date", how="left", validate="one_to_one")
    result = result.merge(signals, on="trade_date", how="left", validate="one_to_one")
    result = result.merge(closes, on="trade_date", how="left", validate="one_to_one")
    result["raw_open"] = result["open_raw_price"]
    result["pre_adj_open"] = result["open_pre_adj_price"]
    result["observed_09_30"] = result["open_bar_datetime"].notna()
    result["valid_09_30"] = result["observed_09_30"] & result["open_row_status"].eq(
        "VALID"
    )
    result["executable_09_30"] = result["valid_09_30"]
    result["execution_status"] = "MISSING_09_30_BAR"
    result.loc[result["observed_09_30"], "execution_status"] = "OBSERVED_INVALID_09_30_BAR"
    result.loc[result["valid_09_30"], "execution_status"] = "OBSERVED_VALID_09_30_BAR"
    result["primary_execution_policy"] = result["executable_09_30"].map(
        {
            True: "SUBMIT_TO_ENGINE_PRICE_SEMANTICS_UNVERIFIED",
            False: "NO_FILL_RETRY_NEXT_SESSION",
        }
    )
    result["sensitivity_execution_policy"] = result["executable_09_30"].map(
        {
            True: "NOT_NEEDED",
            False: "FIRST_REAL_BAR_AFTER_09_30_DIAGNOSTIC_ONLY",
        }
    )
    result["observed_14_57"] = result["signal_bar_datetime"].notna()
    result["valid_14_57"] = result["observed_14_57"] & result["signal_row_status"].eq(
        "VALID"
    )
    result["tail_signal_available_14_57"] = result["valid_14_57"]
    result["tail_signal_policy"] = result["tail_signal_available_14_57"].map(
        {
            True: "EVALUATE_FROZEN_14_57_SIGNAL",
            False: "NO_INTRADAY_TAIL_SIGNAL_WAIT_FOR_OFFICIAL_DAILY_CLOSE",
        }
    )
    result["observed_15_00"] = result["close_bar_datetime"].notna()
    result["valid_15_00"] = result["observed_15_00"] & result["close_row_status"].eq(
        "VALID"
    )
    result["executable_15_00"] = result["valid_15_00"]
    result["close_execution_policy"] = result["executable_15_00"].map(
        {
            True: "SUBMIT_TO_ENGINE_CLOSE_SEMANTICS_UNVERIFIED",
            False: "NO_FILL_RETRY_NEXT_SESSION",
        }
    )
    result["synthetic_price_used"] = False
    result["decision_at"] = result["trade_date"].map(
        lambda value: f"{value.isoformat()}T09:30:00+08:00"
    )
    result["unavailability_known_at"] = result["decision_at"].where(
        ~result["executable_09_30"]
    )
    result["source_partition_sha256"] = partition_sha256
    result["source"] = "QMT critical-minute partition; no forward fill"
    result["exact_supermind_fill_semantics"] = "UNVERIFIED"

    unavailable = ~result["executable_09_30"]
    result.loc[unavailable, ["raw_open", "pre_adj_open"]] = float("nan")
    if result.loc[unavailable, ["raw_open", "pre_adj_open"]].notna().any(axis=None):
        raise AssertionError("unavailable 09:30 rows must never receive execution prices")

    signal_unavailable = ~result["tail_signal_available_14_57"]
    result.loc[
        signal_unavailable,
        ["signal_raw_price", "signal_pre_adj_price"],
    ] = float("nan")
    close_unavailable = ~result["executable_15_00"]
    result.loc[
        close_unavailable,
        ["close_raw_price", "close_pre_adj_price"],
    ] = float("nan")

    return result.sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def build_all(
    evaluation_start: date,
    market_anchors: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    market_anchors = market_anchors or []
    etf_symbols = [canonical_symbol(code) for code in parse_strategy_pool()]
    symbols = [*etf_symbols, *[symbol for symbol in market_anchors if symbol not in etf_symbols]]
    frames: list[pd.DataFrame] = []
    boundary_missing = 0

    for symbol in symbols:
        dpath = daily_path(symbol)
        mpath = minute_path(symbol)
        daily = pd.read_parquet(dpath)
        minute = pd.read_parquet(mpath)
        frames.append(
            build_symbol_availability(
                symbol,
                daily,
                minute,
                evaluation_start=evaluation_start,
                partition_sha256=sha256_file(mpath),
            )
        )

        daily = normalize_dates(daily)
        minute = normalize_dates(minute)
        has_boundary_daily = bool(
            (
                daily["trade_date"].eq(BOUNDARY_DATE)
                & daily["row_status"].eq("VALID")
            ).any()
        )
        has_boundary_open = bool(
            (
                minute["trade_date"].eq(BOUNDARY_DATE)
                & minute["bar_role"].eq("OPEN_BAR_09_30")
            ).any()
        )
        boundary_missing += int(has_boundary_daily and not has_boundary_open)

    output = pd.concat(frames, ignore_index=True).sort_values(
        ["trade_date", "symbol"]
    ).reset_index(drop=True)
    missing = output[~output["observed_09_30"]]
    invalid = output[output["observed_09_30"] & ~output["valid_09_30"]]
    unavailable = output[~output["executable_09_30"]]
    missing_counts = Counter(missing["symbol"])
    invalid_counts = Counter(invalid["symbol"])
    unavailable_counts = Counter(unavailable["symbol"])
    observed = int(output["observed_09_30"].sum())
    executable = int(output["executable_09_30"].sum())
    signal_available = int(output["tail_signal_available_14_57"].sum())
    close_executable = int(output["executable_15_00"].sum())
    total = len(output)
    manifest: dict[str, Any] = {
        "availability_version": "v6-open-execution-availability-1",
        "strategy_source_sha256": strategy_sha256(),
        "evaluation_start": evaluation_start.isoformat(),
        "evaluation_end": str(output["trade_date"].max()),
        "symbols_expected": len(symbols),
        "etf_symbols_expected": len(etf_symbols),
        "market_anchor_symbols": market_anchors,
        "symbols_present": int(output["symbol"].nunique()),
        "expected_symbol_sessions": total,
        "observed_09_30_symbol_sessions": observed,
        "missing_09_30_symbol_sessions": total - observed,
        "observed_09_30_rate": observed / total,
        "invalid_09_30_symbol_sessions": len(invalid),
        "executable_09_30_symbol_sessions": executable,
        "unavailable_09_30_symbol_sessions": total - executable,
        "executable_09_30_rate": executable / total,
        "tail_signal_available_14_57_symbol_sessions": signal_available,
        "tail_signal_unavailable_14_57_symbol_sessions": total - signal_available,
        "tail_signal_available_14_57_rate": signal_available / total,
        "executable_15_00_symbol_sessions": close_executable,
        "unavailable_15_00_symbol_sessions": total - close_executable,
        "executable_15_00_rate": close_executable / total,
        "boundary_date_excluded": BOUNDARY_DATE.isoformat(),
        "boundary_missing_09_30_excluded": boundary_missing,
        "missing_by_symbol": dict(sorted(missing_counts.items())),
        "invalid_by_symbol": dict(sorted(invalid_counts.items())),
        "unavailable_by_symbol": dict(sorted(unavailable_counts.items())),
        "missing_symbol_dates": [
            {"symbol": row.symbol, "trade_date": str(row.trade_date)}
            for row in missing[["symbol", "trade_date"]].itertuples(index=False)
        ],
        "invalid_symbol_dates": [
            {"symbol": row.symbol, "trade_date": str(row.trade_date)}
            for row in invalid[["symbol", "trade_date"]].itertuples(index=False)
        ],
        "primary_execution_policy": (
            "MISSING_OR_INVALID_09_30_BAR => NO_FILL_RETRY_NEXT_SESSION"
        ),
        "tail_signal_policy": (
            "MISSING_OR_INVALID_14_57_BAR => "
            "NO_INTRADAY_TAIL_SIGNAL_WAIT_FOR_OFFICIAL_DAILY_CLOSE"
        ),
        "close_execution_policy": (
            "MISSING_OR_INVALID_15_00_BAR => NO_FILL_RETRY_NEXT_SESSION"
        ),
        "sensitivity_execution_policy": (
            "FIRST_REAL_BAR_AFTER_09_30_DIAGNOSTIC_ONLY; never silently substituted"
        ),
        "synthetic_price_used": False,
        "data_ready_for_fail_closed_limited_window_replay": True,
        "exact_supermind_replication_ready": False,
        "exact_replication_blocker": "09:30 fallback engine fill semantics remain unverified",
    }
    return output, manifest


def main() -> int:
    args = parse_args()
    availability, manifest = build_all(args.evaluation_start, args.market_anchors)
    atomic_write_parquet(availability, args.output)
    manifest["output_path"] = args.output.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    manifest["output_sha256"] = sha256_file(args.output)
    atomic_write_json(args.manifest, manifest)
    print(f"OPEN_AVAILABILITY_ROWS {len(availability)}")
    print(f"MISSING_09_30 {manifest['missing_09_30_symbol_sessions']}")
    print(f"INVALID_09_30 {manifest['invalid_09_30_symbol_sessions']}")
    print(f"UNAVAILABLE_09_30 {manifest['unavailable_09_30_symbol_sessions']}")
    print(
        "UNAVAILABLE_14_57 "
        f"{manifest['tail_signal_unavailable_14_57_symbol_sessions']}"
    )
    print(f"UNAVAILABLE_15_00 {manifest['unavailable_15_00_symbol_sessions']}")
    print(f"BOUNDARY_MISSING_EXCLUDED {manifest['boundary_missing_09_30_excluded']}")
    print("SYNTHETIC_PRICE_USED NO")
    print("FAIL_CLOSED_LIMITED_WINDOW_READY YES")
    print("EXACT_SUPERMIND_REPLICATION_READY NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
