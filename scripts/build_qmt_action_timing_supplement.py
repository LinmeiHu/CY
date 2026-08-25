#!/usr/bin/env python3
"""Audit QMT Capital effective dates against frozen corporate actions.

This produces an audit supplement only.  It never changes ``hard_valid`` and
is deliberately not consumed by the state or backtest pipelines.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

import duckdb


def _day(value: object) -> date | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return None
    text = text[:10].replace("/", "-")
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def build(capital: Path, actions: Path, symbol: str | None, output: Path, available_at: str, snapshot_id: str) -> int:
    connection = duckdb.connect()
    capital_sql = "select * from read_parquet(?)"
    capital_args: list[object] = [str(capital)]
    if symbol:
        capital_sql += " where qmt_code = ?"
        capital_args.append(symbol)
    capital_all = connection.execute(capital_sql, capital_args).fetchdf().to_dict("records")
    capital_by_code: dict[str, list[dict[str, object]]] = {}
    for row in capital_all:
        capital_by_code.setdefault(str(row.get("qmt_code")), []).append(row)
    action_sql = "select * from read_parquet(?)"
    action_args: list[object] = [str(actions)]
    if symbol:
        action_sql += " where lpad(cast(symbol as varchar), 6, '0') = ?"
        action_args.append(symbol[:6])
    action_rows = connection.execute(action_sql, action_args).fetchdf().to_dict("records")
    rows: list[dict[str, object]] = []
    for action in action_rows:
        code = str(action.get("symbol", "")).zfill(6)
        candidates = [(qmt_code, items) for qmt_code, items in capital_by_code.items() if qmt_code[:6] == code]
        if symbol:
            candidates = [(symbol, capital_by_code.get(symbol, []))]
        for qmt_code, capital_rows in candidates:
            rows.extend(_match_action(action, qmt_code, capital_rows, available_at, snapshot_id))
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["symbol", "status", "available_at", "snapshot_id"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"rows={len(rows)} output={output}")
    return 0 if rows else 2


def _match_action(action: dict[str, object], symbol: str, capital_rows: list[dict[str, object]], available_at: str, snapshot_id: str) -> list[dict[str, object]]:
    if not capital_rows:
        return []
    effective = _day(action.get("effective_date"))
    if effective is None:
        return []
    matches = [r for r in capital_rows if _day(r.get("m_timetag")) == effective]
    if not matches:
        return []
    current = matches[-1]
    previous = None
    for candidate in capital_rows:
        d = _day(candidate.get("m_timetag"))
        if d is not None and d < effective:
            previous = candidate
    old_cap = _number(previous.get("circulating_capital")) if previous else None
    new_cap = _number(current.get("circulating_capital"))
    factor = new_cap / old_cap if old_cap and new_cap else None
    expected = _number(action.get("share_multiplier"))
    factor_match = factor is not None and expected is not None and abs(factor - expected) <= 0.005
    return [{
        "symbol": symbol,
        "action_id": action.get("event_id", ""),
        "effective_date": effective.isoformat(),
        "announcement_date": _day(action.get("announcement_date")),
        "known_at": action.get("known_at", ""),
        "qmt_execution_date": _day(current.get("m_timetag")),
        "qmt_announcement_date": _day(current.get("m_anntime")),
        "previous_circulating_shares": old_cap,
        "new_circulating_shares": new_cap,
        "qmt_share_factor": factor,
        "cninfo_share_multiplier": expected,
        "capital_factor_matches_action": factor_match,
        "qmt_execution_date_confirmed": True,
        "research_resolvable": bool(factor_match),
        "strict_resolution_candidate": False,
        "resolution_basis": "QMT Capital m_timetag matches CNINFO effective_date and share factor",
        "available_at": available_at,
        "snapshot_id": snapshot_id,
    }]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--symbol")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--available-at", required=True)
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()
    return build(args.capital, args.actions, args.symbol, args.output, args.available_at, args.snapshot_id)


if __name__ == "__main__":
    raise SystemExit(main())
