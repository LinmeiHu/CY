#!/usr/bin/env python3
"""Resolve known share distributions from the causal ex-date reference price.

The output is a small PIT-B research overlay.  It never edits raw daily bars or
the frozen CNINFO snapshot and it never upgrades strict PIT eligibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from cyq_game.data.corporate_actions import resolve_distribution_reference_price

TZ = ZoneInfo("Asia/Shanghai")
VERSION = "preclose-action-resolution-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def _snapshot_id(row: dict[str, object]) -> str:
    identity = "|".join(
        (
            VERSION,
            str(row["event_id"]),
            str(row["symbol"]),
            str(row["trade_date"]),
            str(row["daily_snapshot_id"]),
            str(row["row_hash"]),
            str(row.get("float_snapshot_id") or ""),
        )
    )
    return f"{VERSION}:{hashlib.sha256(identity.encode()).hexdigest()}"


def build_overlay(
    *,
    daily_root: Path,
    distributions_path: Path,
    output: Path,
    symbols: tuple[str, ...],
    start: date,
    end: date,
) -> dict[str, object]:
    if not symbols:
        raise ValueError("at least one symbol is required")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    daily_files = [
        daily_root / f"partition_year={year}" / "data_0.parquet"
        for year in range(start.year, end.year + 1)
    ]
    missing = [path for path in (*daily_files, distributions_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing action-resolution inputs: {missing[:3]}")
    symbol_sql = ",".join("'" + symbol.replace("'", "''") + "'" for symbol in symbols)
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            WITH daily AS (
                SELECT *,
                    lag(close) OVER (
                        PARTITION BY symbol ORDER BY trade_date
                    ) AS previous_close,
                    lag(circulating_shares) OVER (
                        PARTITION BY symbol ORDER BY trade_date
                    ) AS previous_circulating_shares
                FROM read_parquet({_sql_paths(daily_files)}, union_by_name=true)
                WHERE symbol IN ({symbol_sql})
                  AND trade_date BETWEEN DATE '{start.isoformat()}' AND DATE '{end.isoformat()}'
            )
            SELECT
                d.symbol, d.trade_date, d.decision_at, d.previous_close,
                d.preclose AS observed_preclose, d.daily_snapshot_id,
                d.previous_circulating_shares,
                d.corporate_action_available_date,
                r.event_id, r.known_at, r.effective_date,
                r.share_multiplier, r.cash_per_share_gross,
                r.source_terms_complete, r.row_hash, r.revision_id,
                r.source, r.vintage_id
            FROM daily d
            INNER JOIN read_parquet('{str(distributions_path).replace("'", "''")}') r
              ON split_part(d.symbol, '.', 1) = r.symbol
             AND d.trade_date = CAST(r.effective_date AS DATE)
             AND strpos(coalesce(d.corporate_action_ids, ''), r.event_id) > 0
            WHERE d.corporate_action_blocking
              AND r.known_at <= d.decision_at
              AND r.source_terms_complete
              AND r.share_multiplier > 1.0
            ORDER BY d.symbol, d.trade_date, r.event_id
            """
        ).fetchdf().to_dict("records")
        daily_float_rows = con.execute(
            f"""
            SELECT symbol, trade_date, circulating_shares, float_snapshot_id
            FROM read_parquet({_sql_paths(daily_files)}, union_by_name=true)
            WHERE symbol IN ({symbol_sql})
              AND trade_date BETWEEN DATE '{start.isoformat()}' AND DATE '{end.isoformat()}'
            ORDER BY symbol, trade_date
            """
        ).fetchdf().to_dict("records")
    finally:
        con.close()

    key_counts: dict[tuple[str, date], int] = {}
    for row in rows:
        key = (str(row["symbol"]), row["trade_date"])
        key_counts[key] = key_counts.get(key, 0) + 1
    duplicates = sorted(key for key, count in key_counts.items() if count != 1)
    if duplicates:
        raise ValueError(f"ambiguous action rows: {duplicates[:3]}")

    resolved_actions: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    for row in rows:
        result = resolve_distribution_reference_price(
            previous_close=float(row["previous_close"]),
            observed_preclose=float(row["observed_preclose"]),
            share_multiplier=float(row["share_multiplier"]),
            cash_per_pre_action_share=float(row["cash_per_share_gross"] or 0.0),
        )
        evidence = {
            "symbol": str(row["symbol"]),
            "trade_date": row["trade_date"],
            "event_id": str(row["event_id"]),
            "known_at": row["known_at"],
            "effective_date": row["effective_date"],
            "share_multiplier": float(row["share_multiplier"]),
            "cash_per_share": float(row["cash_per_share_gross"] or 0.0),
            "previous_close": float(row["previous_close"]),
            "observed_preclose": result.observed_preclose,
            "expected_preclose": result.expected_preclose,
            "absolute_error": result.absolute_error,
            "tolerance": result.tolerance,
            "resolution_available_at": datetime.combine(
                row["trade_date"], time(9, 0), tzinfo=TZ
            ),
            "corporate_action_available_date": row[
                "corporate_action_available_date"
            ],
            "source": str(row["source"]),
            "source_vintage_id": str(row["vintage_id"]),
            "source_revision_id": str(row["revision_id"]),
            "daily_snapshot_id": str(row["daily_snapshot_id"]),
            "strict_pit_eligible": False,
            "pit_grade": "B_RESEARCH_ONLY",
            "resolution_basis": "KNOWN_CNINFO_TERMS_MATCH_QMT_PRECLOSE_RESET",
        }
        evidence["snapshot_id"] = _snapshot_id({**row, **evidence})
        evidence["expected_post_circulating_shares"] = (
            float(row["previous_circulating_shares"])
            * float(row["share_multiplier"])
        )
        (resolved_actions if result.matched else rejected).append(evidence)

    if rejected:
        examples = [
            (item["symbol"], str(item["trade_date"]), item["absolute_error"])
            for item in rejected[:3]
        ]
        raise ValueError(f"reference-price mismatch: {examples}")
    if not resolved_actions:
        raise ValueError("no corporate actions were resolved")

    daily_by_symbol: dict[str, list[dict[str, object]]] = {}
    for row in daily_float_rows:
        daily_by_symbol.setdefault(str(row["symbol"]), []).append(row)
    overlay_rows: list[dict[str, object]] = []
    for action in resolved_actions:
        symbol = str(action["symbol"])
        action_day = action["trade_date"]
        expected_float = float(action["expected_post_circulating_shares"])
        bridge_days = 0
        caught_up = False
        for daily in daily_by_symbol[symbol]:
            day = daily["trade_date"]
            if day < action_day:
                continue
            observed_float = float(daily["circulating_shares"])
            matched_float = abs(observed_float - expected_float) <= max(
                1.0, expected_float * 0.005
            )
            if day > action_day and matched_float:
                caught_up = True
                break
            if bridge_days >= 20:
                break
            apply_action = day == action_day
            row = {
                **action,
                "trade_date": day,
                "action_trade_date": action_day,
                "apply_action": apply_action,
                "share_multiplier": (
                    float(action["share_multiplier"]) if apply_action else 1.0
                ),
                "cash_per_share": (
                    float(action["cash_per_share"]) if apply_action else 0.0
                ),
                "observed_circulating_shares": observed_float,
                "circulating_shares_override": expected_float,
                "float_snapshot_id": str(daily["float_snapshot_id"]),
            }
            row["snapshot_id"] = _snapshot_id(
                {
                    **row,
                    "daily_snapshot_id": action["daily_snapshot_id"],
                    "row_hash": action["source_revision_id"],
                }
            )
            overlay_rows.append(row)
            bridge_days += 1
        if not caught_up:
            raise ValueError(
                f"circulating shares did not reflect {action['event_id']} within 20 days"
            )

    overlay_keys = [(str(row["symbol"]), row["trade_date"]) for row in overlay_rows]
    if len(overlay_keys) != len(set(overlay_keys)):
        raise ValueError("overlapping action/float bridge rows")

    output.mkdir(parents=True)
    data_path = output / "data.parquet"
    pq.write_table(
        pa.Table.from_pylist(overlay_rows),
        data_path,
        compression="zstd",
    )
    manifest = {
        "version": VERSION,
        "status": "PASS",
        "research_only": True,
        "strict_pit_eligible": False,
        "symbols": list(symbols),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "actions": len(resolved_actions),
        "rows": len(overlay_rows),
        "float_bridge_rows": sum(not bool(item["apply_action"]) for item in overlay_rows),
        "duplicate_keys": 0,
        "max_reference_price_error": max(
            float(item["absolute_error"]) for item in resolved_actions
        ),
        "data_path": str(data_path.resolve()),
        "data_sha256": _sha256(data_path),
        "inputs": [
            {"path": str(path.resolve()), "sha256": _sha256(path)}
            for path in (*daily_files, distributions_path)
        ],
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-root", type=Path, required=True)
    parser.add_argument("--distributions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    manifest = build_overlay(
        daily_root=args.daily_root,
        distributions_path=args.distributions,
        output=args.output,
        symbols=tuple(args.symbols),
        start=args.start,
        end=args.end,
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
