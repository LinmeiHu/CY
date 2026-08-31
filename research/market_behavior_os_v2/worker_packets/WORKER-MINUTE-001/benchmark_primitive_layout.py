#!/usr/bin/env python3
"""Tiny outcome-blind benchmark for a reusable security-session minute cache.

This is infrastructure evidence only.  It reads one date already frozen in
MKT-MIN-001, selects a deterministic 128-session hard-valid sample, writes
candidate files only to a caller-provided temporary directory, and publishes
no cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SAMPLE_DATE = pd.Timestamp("2020-02-03")
SAMPLE_SIZE = 128
EXPECTED_MINUTES = np.array(
    [
        9 * 60 + 30,
        *range(9 * 60 + 31, 11 * 60 + 31),
        *range(13 * 60 + 1, 15 * 60 + 1),
    ],
    dtype=np.int16,
)
QD004_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-004-2018-2026-20260820.json"
)
CY006_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY008_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-008-pit-b-minute-v2-2018-2026-20260821.json"
)
EXPECTED_MANIFEST_HASHES = {
    "qd004": "767298a88618f30d4cc6d5db8a7f609670f88ba32987de6a32994844ad75746c",
    "cy006": "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    "cy008": "5903149da5d8afe37fa18719d17e8a5726856d11e8441d25d51217b05d6adf9f",
}


class BenchmarkError(RuntimeError):
    """Fail-closed benchmark error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _inventory_file(manifest_path: Path, expected_hash: str, relative: str) -> tuple[Path, str]:
    if sha256_file(manifest_path) != expected_hash:
        raise BenchmarkError(f"manifest identity changed: {manifest_path.name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    indexed = {item["path"]: item for item in manifest["files"]}
    item = indexed.get(relative)
    if item is None:
        raise BenchmarkError(f"inventory entry missing: {relative}")
    path = Path(manifest["root"]) / relative
    if not path.is_file() or path.stat().st_size != int(item["size"]):
        raise BenchmarkError(f"inventory size gate failed: {relative}")
    return path, str(item["sha256"])


def _stable_order(symbol: str) -> str:
    return hashlib.sha256(f"WORKER-MINUTE-001|{SAMPLE_DATE.date()}|{symbol}".encode()).hexdigest()


def _read_and_validate() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    qd_path, qd_hash = _inventory_file(
        QD004_INVENTORY,
        EXPECTED_MANIFEST_HASHES["qd004"],
        "bars/2020_day_parquet_none.parquet",
    )
    cy6_path, _ = _inventory_file(
        CY006_INVENTORY,
        EXPECTED_MANIFEST_HASHES["cy006"],
        "partition_year=2020/data_0.parquet",
    )
    cy8_path, _ = _inventory_file(
        CY008_INVENTORY,
        EXPECTED_MANIFEST_HASHES["cy008"],
        "daily/partition_year=2020/data_0.parquet",
    )
    raw_columns = [
        "symbol",
        "exchange",
        "period",
        "adjust",
        "trade_date",
        "bar_end_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source",
    ]
    started = time.perf_counter()
    raw = pq.read_table(
        qd_path,
        columns=raw_columns,
        filters=[
            ("trade_date", "=", SAMPLE_DATE.date()),
            ("exchange", "in", ["SH", "SZ"]),
            ("period", "=", "1m"),
            ("adjust", "=", "none"),
        ],
        use_threads=False,
        pre_buffer=True,
    ).to_pandas()
    source_read_seconds = time.perf_counter() - started
    if raw.empty or raw[raw_columns].isna().any().any():
        raise BenchmarkError("raw sample empty or null")
    raw["trade_date"] = pd.to_datetime(raw.trade_date, errors="raise")
    raw["bar_end_time"] = pd.to_datetime(raw.bar_end_time, errors="raise")
    raw["symbol_suffixed"] = raw.symbol + np.where(raw.exchange.eq("SH"), ".SH", ".SZ")
    raw = raw.sort_values(["symbol_suffixed", "bar_end_time"]).reset_index(drop=True)

    predicate_rows = len(raw)
    valid_symbols: list[str] = []
    invalid_grid = 0
    for symbol, group in raw.groupby("symbol_suffixed", sort=True):
        minute_of_day = (
            group.bar_end_time.dt.hour.to_numpy() * 60 + group.bar_end_time.dt.minute.to_numpy()
        )
        numeric = group[["open", "high", "low", "close", "volume", "amount"]].to_numpy(float)
        grid_ok = (
            len(group) == 241
            and group.bar_end_time.nunique() == 241
            and np.array_equal(minute_of_day.astype(np.int16), EXPECTED_MINUTES)
            and group.bar_end_time.dt.date.eq(SAMPLE_DATE.date()).all()
        )
        numeric_ok = (
            np.isfinite(numeric).all()
            and (numeric[:, :4] > 0).all()
            and (numeric[:, 4:] >= 0).all()
            and (numeric[:, 1] >= np.maximum(numeric[:, 0], numeric[:, 3])).all()
            and (numeric[:, 2] <= np.minimum(numeric[:, 0], numeric[:, 3])).all()
        )
        if grid_ok and numeric_ok:
            valid_symbols.append(str(symbol))
        else:
            invalid_grid += 1

    filters = [("trade_date", "=", SAMPLE_DATE.date())]
    cy6 = pq.read_table(
        cy6_path,
        columns=[
            "symbol",
            "trade_date",
            "available_at",
            "decision_at",
            "snapshot_id",
            "hard_valid",
            "bar_valid",
            "trading_state_valid",
            "corporate_action_valid",
            "market_rule_valid",
            "historical_identity_valid",
            "corporate_action_blocking",
            "trade_status",
            "current_day_data_tradable",
            "close",
            "volume",
        ],
        filters=filters,
        use_threads=False,
    ).to_pandas()
    cy8 = pq.read_table(
        cy8_path,
        columns=[
            "symbol",
            "trade_date",
            "available_at",
            "snapshot_id",
            "daily_snapshot_id",
            "minute_count",
            "distinct_minute_count",
            "source_resolution_minutes",
            "session_complete",
            "ohlc_valid",
            "unit_valid",
            "volume_reconciled",
            "amount_reconciled",
            "daily_hard_valid",
            "hard_valid",
        ],
        filters=filters,
        use_threads=False,
    ).to_pandas()
    for frame in (cy6, cy8):
        frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    cy6_gate = (
        cy6.hard_valid.astype(bool)
        & cy6.bar_valid.astype(bool)
        & cy6.trading_state_valid.astype(bool)
        & cy6.corporate_action_valid.astype(bool)
        & cy6.market_rule_valid.astype(bool)
        & cy6.historical_identity_valid.astype(bool)
        & ~cy6.corporate_action_blocking.astype(bool)
        & (pd.to_datetime(cy6.available_at, utc=True) <= pd.to_datetime(cy6.decision_at, utc=True))
        & pd.to_numeric(cy6.close, errors="coerce").gt(0)
        & pd.to_numeric(cy6.volume, errors="coerce").gt(0)
        & pd.to_numeric(cy6.trade_status, errors="coerce").eq(1)
        & cy6.current_day_data_tradable.astype(bool)
    )
    expected_available = cy8.trade_date + pd.Timedelta(hours=15, minutes=30)
    cy8_gate = (
        pd.to_datetime(cy8.available_at).eq(expected_available)
        & cy8.minute_count.astype(int).eq(241)
        & cy8.distinct_minute_count.astype(int).eq(241)
        & cy8.source_resolution_minutes.astype(int).eq(1)
        & cy8.session_complete.astype(bool)
        & cy8.ohlc_valid.astype(bool)
        & cy8.unit_valid.astype(bool)
        & cy8.volume_reconciled.astype(bool)
        & cy8.amount_reconciled.astype(bool)
        & cy8.daily_hard_valid.astype(bool)
        & cy8.hard_valid.astype(bool)
    )
    cy6 = cy6.loc[cy6_gate, ["symbol", "snapshot_id"]].rename(
        columns={"snapshot_id": "cy006_snapshot_id"}
    )
    cy8 = cy8.loc[cy8_gate, ["symbol", "snapshot_id", "daily_snapshot_id"]].rename(
        columns={"snapshot_id": "cy008_snapshot_id"}
    )
    context = cy6.merge(cy8, on="symbol", validate="one_to_one")
    if not context.daily_snapshot_id.eq(context.cy006_snapshot_id).all():
        raise BenchmarkError("CY-006/CY-008 snapshot binding failed")
    eligible = sorted(set(valid_symbols).intersection(context.symbol), key=_stable_order)
    if len(eligible) < SAMPLE_SIZE:
        raise BenchmarkError("insufficient hard-valid sample")
    selected = eligible[:SAMPLE_SIZE]
    raw = raw.loc[raw.symbol_suffixed.isin(selected)].copy()
    context = (
        context.loc[context.symbol.isin(selected)].sort_values("symbol").reset_index(drop=True)
    )
    if len(raw) != SAMPLE_SIZE * 241 or len(context) != SAMPLE_SIZE:
        raise BenchmarkError("selected sample cardinality changed")
    return (
        raw,
        context,
        {
            "source_read_seconds": source_read_seconds,
            "source_predicate_rows": int(predicate_rows),
            "selected_raw_rows": len(raw),
            "source_sessions_before_selection": int(len(valid_symbols) + invalid_grid),
            "valid_grid_sessions_before_context": len(valid_symbols),
            "invalid_grid_or_numeric_sessions": int(invalid_grid),
            "sample_sessions": SAMPLE_SIZE,
            "qd004_partition_sha256": qd_hash,
        },
    )


def _fixed_list(values: list[list[float]], size: int) -> pa.Array:
    return pa.array(values, type=pa.list_(pa.float64(), size))


def _candidate_tables(
    raw: pd.DataFrame, context: pd.DataFrame, qd_hash: str
) -> dict[str, pa.Table]:
    groups = {
        symbol: group.sort_values("bar_end_time")
        for symbol, group in raw.groupby("symbol_suffixed")
    }
    symbols = sorted(groups)
    base: dict[str, object] = {
        "symbol": symbols,
        "trade_date": [SAMPLE_DATE.date()] * len(symbols),
        "feature_available_at": [SAMPLE_DATE.to_pydatetime().replace(hour=15, minute=30)]
        * len(symbols),
        "grid_id": ["CN_A_1M_END_V1_241"] * len(symbols),
        "price_basis": ["raw_unadjusted"] * len(symbols),
        "volume_unit": ["shares"] * len(symbols),
        "amount_unit": ["CNY"] * len(symbols),
        "qd004_partition_sha256": [qd_hash] * len(symbols),
    }
    aligned_context = context.set_index("symbol").loc[symbols]
    base["cy006_snapshot_id"] = aligned_context.cy006_snapshot_id.astype(str).tolist()
    base["cy008_snapshot_id"] = aligned_context.cy008_snapshot_id.astype(str).tolist()
    full_lists = {
        name: [groups[symbol][name].astype(float).tolist() for symbol in symbols]
        for name in ("open", "high", "low", "close", "volume", "amount")
    }
    array241 = pa.table(
        {
            **base,
            **{name: _fixed_list(values, 241) for name, values in full_lists.items()},
        }
    )
    segmented: dict[str, object] = dict(base)
    for name, values in full_lists.items():
        segmented[f"auction_{name}"] = [row[0] for row in values]
        segmented[f"continuous_{name}"] = _fixed_list([row[1:] for row in values], 240)
    array240 = pa.table(segmented)
    long = pa.Table.from_pandas(
        raw[
            [
                "symbol_suffixed",
                "trade_date",
                "bar_end_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "source",
            ]
        ].rename(columns={"symbol_suffixed": "symbol"}),
        preserve_index=False,
    )
    return {"long241": long, "array241": array241, "segmented240": array240}


def _max_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if __import__("sys").platform == "darwin" else value * 1024


def run(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=False)
    raw, context, audit = _read_and_validate()
    tables = _candidate_tables(raw, context, str(audit["qd004_partition_sha256"]))
    candidates: dict[str, object] = {}
    for name, table in tables.items():
        path = output_dir / f"{name}.parquet"
        started = time.perf_counter()
        pq.write_table(
            table,
            path,
            compression="zstd",
            compression_level=3,
            use_dictionary=True,
            write_statistics=True,
            row_group_size=4096,
        )
        write_seconds = time.perf_counter() - started
        read_started = time.perf_counter()
        reread = pq.read_table(path, use_threads=False)
        read_seconds = time.perf_counter() - read_started
        if reread.num_rows != table.num_rows or reread.schema != table.schema:
            raise BenchmarkError(f"round-trip schema/cardinality failed: {name}")
        candidates[name] = {
            "rows": int(table.num_rows),
            "columns": int(table.num_columns),
            "bytes": path.stat().st_size,
            "bytes_per_session": path.stat().st_size / SAMPLE_SIZE,
            "write_seconds": write_seconds,
            "read_seconds": read_seconds,
            "sha256": sha256_file(path),
        }
    return {
        "decision": "BENCHMARK_COMPLETE_NO_CACHE_PUBLISHED",
        "sample_date": SAMPLE_DATE.date().isoformat(),
        "sample_selection": "first 128 SHA256(WORKER-MINUTE-001|date|symbol) hard-valid sessions",
        "outcome_access": False,
        "audit": audit,
        "candidates": candidates,
        "peak_rss_bytes": _max_rss_bytes(),
        "thread_contract": "OMP/MKL/OPENBLAS/VECLIB/NUMEXPR=1; pyarrow use_threads=false",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    result = run(args.output_dir)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result:
        args.result.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
