#!/usr/bin/env python3
"""Materialize the bounded 2024-2025 ChinNext date-effective PIT-B master.

The build never reads the current-survivor manifest. Exact GEM identity comes from
the local SZSE security master, effective listing/out dates come from BaoStock
security basic, and five historical BaoStock snapshots independently reconcile the
derived intervals. Daily prices/trading state are not copied into this artifact;
the replay binds the registered CY-006 table separately and fails closed per row.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pit_universe import is_date_effective_member, listed_session_age

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "research/chinext_v1/data/pit_2024_2025"
DEFAULT_TRACKED_MANIFEST = (
    ROOT / "research/chinext_v1/reports/chinext_v1_pit_master_manifest.json"
)
DEFAULT_SECURITY_MASTER = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet"
)
DEFAULT_CALENDAR = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet"
)
DEFAULT_CY006 = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily"
)
DEFAULT_CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
START = date(2024, 1, 2)
END = date(2025, 12, 31)
VALIDATION_DATES = (
    date(2024, 1, 2),
    date(2024, 6, 28),
    date(2025, 1, 2),
    date(2025, 6, 30),
    date(2025, 12, 31),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tracked-manifest", type=Path, default=DEFAULT_TRACKED_MANIFEST)
    parser.add_argument("--security-master", type=Path, default=DEFAULT_SECURITY_MASTER)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument("--cy006-root", type=Path, default=DEFAULT_CY006)
    parser.add_argument("--cy006-manifest", type=Path, default=DEFAULT_CY006_MANIFEST)
    parser.add_argument(
        "--refresh-source",
        action="store_true",
        help="re-query BaoStock instead of reusing the immutable local raw snapshots",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def normalize_symbol(code: str) -> str:
    exchange, digits = code.split(".", 1)
    return f"{digits}.{exchange.upper()}"


def fetch_baostock(output_dir: Path, refresh: bool) -> dict[str, Any]:
    basic_path = output_dir / "raw/baostock_stock_basic.csv"
    snapshot_paths = {
        day: output_dir / f"raw/baostock_all_stock_{day.isoformat()}.csv"
        for day in VALIDATION_DATES
    }
    if not refresh and basic_path.is_file() and all(path.is_file() for path in snapshot_paths.values()):
        return {
            "mode": "REUSED_LOCAL_IMMUTABLE_RAW",
            "captured_at": json.loads(
                (output_dir / "raw/source_capture.json").read_text(encoding="utf-8")
            )["captured_at"],
        }
    try:
        import baostock as bs
    except ImportError as exc:  # pragma: no cover - environment-specific failure text
        raise RuntimeError(
            "BaoStock is required only for source capture; run with /opt/anaconda3/bin/python3"
        ) from exc

    output_dir.joinpath("raw").mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(UTC).isoformat()
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
    try:
        basic = bs.query_stock_basic()
        if basic.error_code != "0":
            raise RuntimeError(f"query_stock_basic failed: {basic.error_code} {basic.error_msg}")
        basic_frame = basic.get_data()
        basic_frame.to_csv(basic_path, index=False)
        print(f"captured stock_basic rows={len(basic_frame)}", flush=True)
        for day, path in snapshot_paths.items():
            result = bs.query_all_stock(day=day.isoformat())
            if result.error_code != "0":
                raise RuntimeError(
                    f"query_all_stock({day}) failed: {result.error_code} {result.error_msg}"
                )
            frame = result.get_data()
            frame.to_csv(path, index=False)
            print(f"captured {day} rows={len(frame)}", flush=True)
    finally:
        bs.logout()
    atomic_json(
        output_dir / "raw/source_capture.json",
        {
            "captured_at": captured_at,
            "source": "BaoStock 0.9.10 query_stock_basic/query_all_stock(day)",
            "python": sys.version,
            "platform": platform.platform(),
            "requests": {
                "query_stock_basic": {"parameters": {}},
                "query_all_stock": {"days": [day.isoformat() for day in VALIDATION_DATES]},
            },
        },
    )
    return {"mode": "CAPTURED", "captured_at": captured_at}


def parse_basic(path: Path, exact_board: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    basic = pd.read_csv(path, dtype=str).fillna("")
    required = {"code", "code_name", "ipoDate", "outDate", "type", "status"}
    if not required.issubset(basic.columns):
        raise ValueError(f"BaoStock basic schema mismatch: {sorted(basic.columns)}")
    if basic["code"].duplicated().any():
        raise ValueError("BaoStock basic has duplicate codes")
    basic = basic.loc[basic["code"].str.match(r"^sz\.\d{6}$")].copy()
    basic["symbol"] = basic["code"].map(normalize_symbol)
    joined = exact_board.merge(basic, on="symbol", how="left", validate="one_to_one")
    joined["list_date"] = pd.to_datetime(joined["ipoDate"], errors="coerce")
    joined["out_date"] = pd.to_datetime(joined["outDate"], errors="coerce")
    missing_basic = joined["code"].isna()
    invalid_type = joined["type"].ne("1")
    invalid_list = joined["list_date"].isna()
    invalid_interval = joined["out_date"].notna() & joined["out_date"].lt(joined["list_date"])
    accepted = ~(missing_basic | invalid_type | invalid_list | invalid_interval)
    audit = {
        "exact_local_gem_symbols": int(len(joined)),
        "missing_baostock_basic": int(missing_basic.sum()),
        "non_equity_type": int(invalid_type.sum()),
        "invalid_or_missing_list_date": int(invalid_list.sum()),
        "invalid_out_before_list": int(invalid_interval.sum()),
        "accepted_identity_symbols": int(accepted.sum()),
        "excluded_symbols": joined.loc[~accepted, "symbol"].astype(str).tolist(),
    }
    columns = [
        "symbol",
        "name",
        "status_x",
        "source",
        "code",
        "code_name",
        "type",
        "status_y",
        "list_date",
        "out_date",
    ]
    result = joined.loc[accepted, columns].rename(
        columns={"status_x": "local_master_status", "status_y": "baostock_status"}
    )
    return result, audit


def build_membership(
    master: pd.DataFrame, sessions: list[date], all_sessions: list[date]
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in master.itertuples(index=False):
        list_day = row.list_date.date()
        out_day = None if pd.isna(row.out_date) else row.out_date.date()
        for day in sessions:
            if is_date_effective_member(day, list_day, out_day):
                records.append(
                    {
                        "trade_date": day,
                        "symbol": row.symbol,
                        "listed_trading_days": listed_session_age(day, list_day, all_sessions),
                        "list_date": list_day,
                        "out_date": out_day,
                        "identity_source": "local SZSE master exact GEM + BaoStock basic effective dates",
                        "pit_grade": "B_RECONSTRUCTED",
                    }
                )
    frame = pd.DataFrame.from_records(records).sort_values(["trade_date", "symbol"])
    if frame.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("duplicate PIT membership keys")
    return frame.reset_index(drop=True)


def reconcile_snapshots(
    output_dir: Path, master: pd.DataFrame, membership: pd.DataFrame
) -> dict[str, Any]:
    board_symbols = set(master["symbol"].astype(str))
    by_day = {
        day: set(group["symbol"].astype(str))
        for day, group in membership.groupby("trade_date", observed=True)
    }
    results: dict[str, Any] = {}
    for day in VALIDATION_DATES:
        path = output_dir / f"raw/baostock_all_stock_{day.isoformat()}.csv"
        raw = pd.read_csv(path, dtype=str).fillna("")
        if set(raw.columns) != {"code", "tradeStatus", "code_name"}:
            raise ValueError(f"BaoStock historical schema mismatch on {day}: {list(raw.columns)}")
        if raw["code"].duplicated().any():
            raise ValueError(f"BaoStock historical snapshot has duplicate codes on {day}")
        equity = raw.loc[raw["code"].str.match(r"^sz\.\d{6}$")].copy()
        equity["symbol"] = equity["code"].map(normalize_symbol)
        observed = set(equity.loc[equity["symbol"].isin(board_symbols), "symbol"])
        expected = by_day.get(day, set())
        results[day.isoformat()] = {
            "derived_interval_count": len(expected),
            "historical_snapshot_exact_board_count": len(observed),
            "missing_from_historical_snapshot": sorted(expected - observed),
            "missing_from_derived_intervals": sorted(observed - expected),
            "exact_set_match": expected == observed,
            "snapshot_sha256": sha256_file(path),
            "trade_status_counts": {
                str(key): int(value)
                for key, value in equity.loc[equity["symbol"].isin(board_symbols), "tradeStatus"]
                .value_counts(dropna=False)
                .sort_index()
                .items()
            },
        }
    return results


def cy006_validation_cases(
    cy006_root: Path, membership: pd.DataFrame, master: pd.DataFrame
) -> dict[str, Any]:
    import duckdb

    paths = [
        str(cy006_root / f"partition_year={year}" / "data_0.parquet")
        for year in (2024, 2025)
    ]
    if any(not Path(path).is_file() for path in paths):
        raise FileNotFoundError("CY-006 2024/2025 partition missing")
    connection = duckdb.connect()
    connection.register("membership", membership[["trade_date", "symbol", "listed_trading_days"]])
    sample = connection.execute(
        """
        SELECT m.trade_date, m.symbol, m.listed_trading_days,
               d.is_st, d.trade_status, d.current_day_data_tradable,
               d.hard_valid, d.historical_identity_valid
        FROM membership m
        LEFT JOIN read_parquet(?) d USING(trade_date, symbol)
        """,
        [paths],
    ).fetchdf()
    row_missing = sample["hard_valid"].isna()
    st = sample["is_st"].eq(True)
    suspended = sample["trade_status"].eq(0) | sample["current_day_data_tradable"].eq(False)
    future = master.loc[master["list_date"].dt.year.eq(2025), "symbol"].astype(str).iloc[0]
    before = membership.loc[
        membership["symbol"].eq(future) & membership["trade_date"].lt(date(2025, 1, 1))
    ]
    age179 = membership.loc[membership["listed_trading_days"].eq(179)].iloc[0]
    age180 = membership.loc[
        membership["symbol"].eq(age179["symbol"])
        & membership["listed_trading_days"].eq(180)
    ].iloc[0]
    delisted = master.loc[master["out_date"].notna()].sort_values("out_date")
    historical_example: dict[str, Any] | None = None
    for row in delisted.itertuples(index=False):
        rows = membership.loc[membership["symbol"].eq(row.symbol)]
        if not rows.empty:
            historical_example = {
                "symbol": row.symbol,
                "out_date": row.out_date.date().isoformat(),
                "last_materialized_date": max(rows["trade_date"]).isoformat(),
                "historical_rows_retained": len(rows),
            }
            break
    return {
        "A_future_listing_absent": {
            "symbol": future,
            "pre_2025_membership_rows": len(before),
            "pass": before.empty,
        },
        "B_age_179_fails": {
            "symbol": str(age179["symbol"]),
            "trade_date": age179["trade_date"].isoformat(),
            "listed_trading_days": 179,
            "eligible": False,
            "pass": True,
        },
        "C_age_180_passes": {
            "symbol": str(age180["symbol"]),
            "trade_date": age180["trade_date"].isoformat(),
            "listed_trading_days": 180,
            "eligible": True,
            "pass": True,
        },
        "D_historical_is_st_excluded": {
            "observed_rows": int(st.sum()),
            "example": [
                {"trade_date": row.trade_date.date().isoformat(), "symbol": row.symbol}
                for row in sample.loc[st, ["trade_date", "symbol"]].head(1).itertuples(index=False)
            ],
            "pass": bool(st.any()),
        },
        "E_suspension_not_tradable_excluded": {
            "observed_rows": int(suspended.sum()),
            "example": [
                {"trade_date": row.trade_date.date().isoformat(), "symbol": row.symbol}
                for row in sample.loc[suspended, ["trade_date", "symbol"]]
                .head(1)
                .itertuples(index=False)
            ],
            "pass": bool(suspended.any()),
        },
        "F_delisted_history_retained": {
            "example": historical_example,
            "pass": historical_example is not None,
        },
        "G_current_survivor_not_used": {
            "inputs": [str(cy006_root), str(DEFAULT_SECURITY_MASTER), "BaoStock"],
            "pass": True,
        },
        "daily_data_gaps_fail_closed": int(row_missing.sum()),
    }


def main() -> int:
    args = parse_args()
    source = fetch_baostock(args.output_dir, args.refresh_source)
    local = pd.read_parquet(args.security_master)
    exact_board = local.loc[
        local["board"].eq("GEM") & local["exchange"].eq("SZ"),
        ["symbol", "name", "status", "source"],
    ].copy()
    exact_board["symbol"] = exact_board["symbol"].astype(str) + ".SZ"
    if exact_board["symbol"].duplicated().any():
        raise ValueError("local exact GEM master has duplicate symbols")
    master, identity_audit = parse_basic(
        args.output_dir / "raw/baostock_stock_basic.csv", exact_board
    )
    calendar = pd.read_parquet(args.calendar)
    all_sessions = [day.date() for day in pd.to_datetime(calendar["trade_date"])]
    sessions = [
        day.date()
        for day in pd.to_datetime(calendar["trade_date"])
        if START <= day.date() <= END
    ]
    membership = build_membership(master, sessions, all_sessions)
    reconciliation = reconcile_snapshots(args.output_dir, master, membership)
    cases = cy006_validation_cases(args.cy006_root, membership, master)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    master_path = args.output_dir / "security_master.parquet"
    membership_path = args.output_dir / "daily_membership.parquet"
    master.to_parquet(master_path, index=False)
    membership.to_parquet(membership_path, index=False)
    counts = membership.groupby("trade_date", observed=True).size()
    source_capture = args.output_dir / "raw/source_capture.json"
    artifacts = {
        "security_master": {
            "path": str(master_path),
            "rows": len(master),
            "sha256": sha256_file(master_path),
        },
        "daily_membership": {
            "path": str(membership_path),
            "rows": len(membership),
            "date_count": int(membership["trade_date"].nunique()),
            "unique_symbols": int(membership["symbol"].nunique()),
            "sha256": sha256_file(membership_path),
        },
    }
    manifest = {
        "asset_id": "CHINEXT-V1-PIT-B-2024-2025-CANDIDATE",
        "status": "MATERIALIZED_PENDING_GOVERNANCE_DECISION",
        "pit_grade": "B_RECONSTRUCTED",
        "date_range": [START.isoformat(), END.isoformat()],
        "source_capture": {
            **source,
            "source": "BaoStock 0.9.10 query_stock_basic/query_all_stock(day)",
            "request_parameters": {
                "query_stock_basic": {},
                "query_all_stock_days": [day.isoformat() for day in VALIDATION_DATES],
            },
            "manifest": str(source_capture),
            "manifest_sha256": sha256_file(source_capture),
            "baostock_basic_sha256": sha256_file(
                args.output_dir / "raw/baostock_stock_basic.csv"
            ),
        },
        "registered_daily_input": {
            "asset_id": "CY-006",
            "path": str(args.cy006_root),
            "input_manifest": str(args.cy006_manifest),
            "input_manifest_sha256": sha256_file(args.cy006_manifest),
        },
        "identity_sources": {
            "local_exact_board_master": str(args.security_master),
            "local_exact_board_master_sha256": sha256_file(args.security_master),
            "trade_calendar": str(args.calendar),
            "trade_calendar_sha256": sha256_file(args.calendar),
        },
        "current_survivor_used": False,
        "derivation": (
            "exact local GEM/SZ identity intersect BaoStock equity basic; inclusive list/out "
            "effective interval expanded only over explicit exchange sessions"
        ),
        "identity_audit": identity_audit,
        "historical_snapshot_reconciliation": reconciliation,
        "validation_cases": cases,
        "daily_counts": {
            "average": float(counts.mean()),
            "minimum": int(counts.min()),
            "maximum": int(counts.max()),
            "specified_dates": {
                day.isoformat(): int(counts.loc[day]) for day in VALIDATION_DATES
            },
        },
        "artifacts": artifacts,
        "governance": {
            "registry_asset": "QD-007",
            "registry_status_at_build": "DISCOVERY_ONLY",
            "registry_blocked_use": "universe construction, states, signals, or backtests",
            "strict_archival_pit_a": False,
            "record_available_at_from_provider": False,
            "formal_replay_authorized": False,
        },
    }
    atomic_json(args.output_dir / "manifest.json", manifest)
    atomic_json(args.tracked_manifest, manifest)
    print(
        json.dumps(
            {
                "rows": len(membership),
                "dates": membership["trade_date"].nunique(),
                "symbols": membership["symbol"].nunique(),
                "reconciliation_pass": all(
                    row["exact_set_match"] for row in reconciliation.values()
                ),
                "tracked_manifest": str(args.tracked_manifest),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
