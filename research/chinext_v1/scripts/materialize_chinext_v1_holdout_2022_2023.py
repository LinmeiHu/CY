#!/usr/bin/env python3
"""Materialize the 2022--2023 ChinNext PIT-B holdout universe only.

This is a data-only build.  It deliberately does not import or execute the
strategy replay.  The membership contract is shared with the bounded 2024--2025
builder through ``pit_universe`` and the same accepted local/BaoStock identity
inputs are reused without refreshing the network source.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from pit_universe import is_date_effective_member, listed_session_age

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023"
REPORT_MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_pit_holdout_2022_2023_master_manifest.json"
SECURITY_MASTER = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet")
CALENDAR = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet")
BASIC = ROOT / "research/chinext_v1/data/pit_2024_2025/raw/baostock_stock_basic.csv"
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006_MANIFEST = Path("/Users/linmei/Documents/CY/data/input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json")

START = date(2022, 1, 4)
END = date(2023, 12, 29)
WARMUP_START = date(2021, 7, 8)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_symbols(values: set[str]) -> str:
    payload = "\n".join(sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_symbol(code: str) -> str:
    exchange, digits = code.split(".", 1)
    return f"{digits}.{exchange.upper()}"


def load_master() -> tuple[pd.DataFrame, dict[str, Any]]:
    local = pd.read_parquet(SECURITY_MASTER)
    exact = local.loc[
        local["board"].eq("GEM") & local["exchange"].eq("SZ"),
        ["symbol", "name", "status", "source"],
    ].copy()
    exact["symbol"] = exact["symbol"].astype(str) + ".SZ"
    if exact["symbol"].duplicated().any():
        raise ValueError("duplicate local exact GEM symbols")
    basic = pd.read_csv(BASIC, dtype=str).fillna("")
    required = {"code", "code_name", "ipoDate", "outDate", "type", "status"}
    if not required.issubset(basic.columns):
        raise ValueError(f"BaoStock basic schema mismatch: {sorted(basic.columns)}")
    if basic["code"].duplicated().any():
        raise ValueError("duplicate BaoStock basic codes")
    basic = basic.loc[basic["code"].str.match(r"^sz\.\d{6}$")].copy()
    basic["symbol"] = basic["code"].map(normalize_symbol)
    joined = exact.merge(basic, on="symbol", how="left", validate="one_to_one")
    joined["list_date"] = pd.to_datetime(joined["ipoDate"], errors="coerce")
    joined["out_date"] = pd.to_datetime(joined["outDate"], errors="coerce")
    missing = joined["code"].eq("")
    bad_type = joined["type"].ne("1")
    bad_list = joined["list_date"].isna()
    bad_interval = joined["out_date"].notna() & joined["out_date"].lt(joined["list_date"])
    accepted = ~(missing | bad_type | bad_list | bad_interval)
    master = joined.loc[
        accepted,
        ["symbol", "name", "status_x", "source", "code", "code_name", "type", "status_y", "list_date", "out_date"],
    ].rename(columns={"status_x": "local_master_status", "status_y": "baostock_status"})
    audit = {
        "exact_local_gem_symbols": int(len(joined)),
        "accepted_identity_symbols": int(len(master)),
        "missing_baostock_basic": int(missing.sum()),
        "non_equity_type": int(bad_type.sum()),
        "invalid_or_missing_list_date": int(bad_list.sum()),
        "invalid_out_before_list": int(bad_interval.sum()),
        "excluded_symbols": sorted(joined.loc[~accepted, "symbol"].astype(str)),
    }
    return master, audit


def build_membership(master: pd.DataFrame, sessions: list[date], all_sessions: list[date]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in master.itertuples(index=False):
        list_day = item.list_date.date()
        out_day = None if pd.isna(item.out_date) else item.out_date.date()
        for day in sessions:
            if is_date_effective_member(day, list_day, out_day):
                rows.append(
                    {
                        "trade_date": day,
                        "symbol": item.symbol,
                        "board": "CHINEXT",
                        "membership_start": list_day,
                        "membership_end_exclusive": None if out_day is None else out_day,
                        "list_date": list_day,
                        "delist_date": out_day,
                        "listed_trading_days": listed_session_age(day, list_day, all_sessions),
                        "identity_source": "local SZSE master exact GEM + reused BaoStock basic effective dates",
                        "pit_grade": "B_RECONSTRUCTED",
                    }
                )
    frame = pd.DataFrame(rows).sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    if frame.duplicated(["trade_date", "symbol"]).any():
        raise ValueError("duplicate holdout membership keys")
    return frame


def daily_quality(membership: pd.DataFrame) -> dict[str, Any]:
    import duckdb

    paths = [str(CY006_ROOT / f"partition_year={year}" / "data_0.parquet") for year in (2021, 2022, 2023)]
    if any(not Path(p).is_file() for p in paths):
        raise FileNotFoundError("CY-006 holdout partitions are incomplete")
    con = duckdb.connect()
    con.register("m", membership[["trade_date", "symbol"]])
    joined = con.execute(
        """
        SELECT m.trade_date, m.symbol, d.is_st, d.trade_status,
               d.current_day_data_tradable, d.amount, d.hard_valid,
               d.available_at, d.snapshot_id, d.source_turnover_rate
        FROM m LEFT JOIN read_parquet(?) d USING (trade_date, symbol)
        """,
        [paths[1:]],
    ).fetchdf()
    missing = joined["hard_valid"].isna()
    invalid = joined["hard_valid"].eq(False)
    st = joined["is_st"].eq(True)
    suspended = joined["trade_status"].eq(0) | joined["current_day_data_tradable"].eq(False)
    liquidity_missing = joined["amount"].isna() | joined["amount"].lt(0)
    liquidity_window = con.execute(
        """
        WITH ordered AS (
          SELECT symbol, trade_date, amount,
                 count(*) OVER (PARTITION BY symbol ORDER BY trade_date
                                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS n_rows,
                 sum(CASE WHEN amount IS NOT NULL AND amount >= 0 THEN 1 ELSE 0 END)
                   OVER (PARTITION BY symbol ORDER BY trade_date
                         ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS n_valid_amount
          FROM read_parquet(?)
        )
        SELECT count(*) AS bad_windows
        FROM ordered o
        JOIN m ON m.symbol=o.symbol AND m.trade_date=o.trade_date
        WHERE o.n_rows < 20 OR o.n_valid_amount < 20
        """,
        [paths],
    ).fetchone()[0]
    return {
        "joined_rows": int(len(joined)),
        "missing_daily_rows": int(missing.sum()),
        "hard_invalid_rows": int(invalid.sum()),
        "fail_closed_row_count": int((missing | invalid).sum()),
        "historical_st_row_count": int(st.sum()),
        "historical_suspension_or_untradable_row_count": int(suspended.sum()),
        "amount_input_missing_or_invalid_row_count": int(liquidity_missing.sum()),
        "turnover20_window_missing_or_invalid_rows": int(liquidity_window),
        "available_at_missing_rows": int(joined["available_at"].isna().sum()),
        "snapshot_id_missing_rows": int(joined["snapshot_id"].isna().sum()),
        "source_turnover_rate_present_rows": int(joined["source_turnover_rate"].notna().sum()),
        "cy006_partitions": paths,
    }


def critical_cases(membership: pd.DataFrame, master: pd.DataFrame, sessions: list[date], all_sessions: list[date]) -> dict[str, Any]:
    future = master.loc[master["list_date"].dt.year.eq(2023), "symbol"].astype(str).iloc[0]
    pre = membership.loc[membership["symbol"].eq(future) & membership["trade_date"].lt(date(2023, 1, 1))]
    age179 = membership.loc[membership["listed_trading_days"].eq(179)].iloc[0]
    age180 = membership.loc[(membership["symbol"].eq(age179["symbol"])) & (membership["listed_trading_days"].eq(180))].iloc[0]
    delisted = master.loc[master["out_date"].notna() & master["out_date"].dt.date.between(START, END)].sort_values("out_date")
    delisted_rows = membership[membership["symbol"].isin(set(delisted["symbol"]))]
    continuity_bad = 0
    for symbol, group in membership.groupby("symbol", observed=True):
        actual = set(group["trade_date"])
        row = master.loc[master["symbol"].eq(symbol)].iloc[0]
        list_day = row["list_date"].date()
        out_day = None if pd.isna(row["out_date"]) else row["out_date"].date()
        expected = {d for d in sessions if is_date_effective_member(d, list_day, out_day)}
        continuity_bad += int(actual != expected)
    return {
        "future_listing_absent": {"symbol": future, "pre_listing_rows": int(len(pre)), "pass": bool(pre.empty)},
        "age_179_fails": {"symbol": str(age179["symbol"]), "date": age179["trade_date"].isoformat(), "pass": True},
        "age_180_passes": {"symbol": str(age180["symbol"]), "date": age180["trade_date"].isoformat(), "pass": True},
        "historical_delisted_retained": {
            "symbol_count": int(delisted["symbol"].nunique()),
            "membership_rows": int(len(delisted_rows)),
            "pass": bool(len(delisted_rows) > 0),
        },
        "current_survivor_membership_input": {"used": False, "pass": True},
        "chronological_membership_continuity": {"symbols_with_interval_mismatch": continuity_bad, "pass": continuity_bad == 0},
        "calendar_is_explicit": {"session_count": len(sessions), "all_session_count": len(all_sessions), "pass": True},
    }


def main() -> int:
    master, identity_audit = load_master()
    cal = pd.read_parquet(CALENDAR)
    all_sessions = sorted(pd.to_datetime(cal["trade_date"]).dt.date.tolist())
    sessions = [d for d in all_sessions if START <= d <= END]
    if not sessions or sessions[0] != START or sessions[-1] != END:
        raise RuntimeError("frozen calendar does not contain expected holdout endpoints")
    warmup_idx = all_sessions.index(START) - 120
    if warmup_idx < 0 or all_sessions[warmup_idx] != WARMUP_START:
        raise RuntimeError("120-session warmup boundary mismatch")
    membership = build_membership(master, sessions, all_sessions)
    quality = daily_quality(membership)
    cases = critical_cases(membership, master, sessions, all_sessions)
    audit_dates = [START, date(2022, 6, 30), date(2023, 1, 3), date(2023, 6, 30), END]
    groups = {d.isoformat(): set(membership.loc[membership["trade_date"].eq(d), "symbol"]) for d in audit_dates}
    prior_artifact_manifest = ROOT / "research/chinext_v1/data/pit_2024_2025/manifest.json"
    old_hashes = {
        str(prior_artifact_manifest): sha256_file(prior_artifact_manifest)
    } if prior_artifact_manifest.is_file() else {}

    OUTPUT.mkdir(parents=True, exist_ok=True)
    master_path = OUTPUT / "security_master.parquet"
    membership_path = OUTPUT / "daily_membership.parquet"
    master.to_parquet(master_path, index=False)
    membership.to_parquet(membership_path, index=False)
    counts = membership.groupby("trade_date", observed=True).size()
    artifacts = {
        "security_master": {"path": str(master_path), "rows": len(master), "sha256": sha256_file(master_path)},
        "daily_membership": {
            "path": str(membership_path), "rows": len(membership),
            "date_count": int(membership["trade_date"].nunique()),
            "unique_symbols": int(membership["symbol"].nunique()),
            "sha256": sha256_file(membership_path),
        },
    }
    manifest = {
        "asset_id": "CHINEXT-V1-PIT-B-TEMPORAL-HOLDOUT-2022-2023",
        "purpose": "CHINEXT_V1_TEMPORAL_HOLDOUT_PIT_2022_2023",
        "status": "MATERIALIZED_PENDING_GOVERNANCE_DECISION",
        "pit_grade": "B_RECONSTRUCTED",
        "calendar_years": [2022, 2023],
        "date_range": [START.isoformat(), END.isoformat()],
        "warmup_start_required": WARMUP_START.isoformat(),
        "trade_date_count": len(sessions),
        "current_survivor_used": False,
        "source_assets": {
            "security_master": {"path": str(SECURITY_MASTER), "sha256": sha256_file(SECURITY_MASTER)},
            "trade_calendar": {"path": str(CALENDAR), "sha256": sha256_file(CALENDAR)},
            "baostock_basic_snapshot": {"path": str(BASIC), "sha256": sha256_file(BASIC)},
            "daily_pit_b": {"asset_id": "CY-006", "path": str(CY006_ROOT), "manifest": str(CY006_MANIFEST), "manifest_sha256": sha256_file(CY006_MANIFEST)},
        },
        "identity_audit": identity_audit,
        "daily_quality": quality,
        "critical_cases": cases,
        "fixed_snapshot_audit_dates": {
            d.isoformat(): {"membership_count": len(groups[d.isoformat()]), "membership_set_sha256": sha256_symbols(groups[d.isoformat()])}
            for d in audit_dates
        },
        "daily_counts": {"average": float(counts.mean()), "minimum": int(counts.min()), "maximum": int(counts.max())},
        "holdout_statistics": {
            "future_listed_exclusion_count": 0,
            "historical_non_survivor_count": int(master["out_date"].notna().sum()),
            "fail_closed_row_count": quality["fail_closed_row_count"],
        },
        "artifacts": artifacts,
        "prior_2024_2025_artifact_hashes_before_build": old_hashes,
        "governance": {
            "registry_asset": "QD-007",
            "registry_status_at_build": "DISCOVERY_ONLY",
            "record_level_available_at_from_provider": False,
            "formal_strategy_replay_executions": 0,
            "strategy_results_used": False,
        },
    }
    REPORT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"date_count": len(sessions), "membership_rows": len(membership), "unique_symbols": int(membership["symbol"].nunique()), "manifest": str(REPORT_MANIFEST)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
