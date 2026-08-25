#!/usr/bin/env python3
"""Audit the immutable BaoStock discovery snapshots without activating them."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import duckdb


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--calendar", required=True)
    p.add_argument("--input", required=True, nargs="+")
    p.add_argument("--output", required=True)
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end", default="2017-12-31")
    ns = p.parse_args()
    roots = [Path(x).resolve() for x in ns.input]
    con = duckdb.connect()
    expected = [r[0].strftime("%Y-%m-%d") for r in con.execute(
        "select trade_date from read_parquet(?) where trade_date between ? and ? order by trade_date",
        [ns.calendar, ns.start, ns.end]).fetchall()]
    # Snapshots may be sharded by year or retry run; recurse while keeping the
    # first root's file authoritative and never silently replacing it.
    files = {}
    for root in roots:
        for x in sorted(root.rglob("snapshot_*.json")):
            files.setdefault(x.stem.removeprefix("snapshot_"), x)
    annual = defaultdict(lambda: {"expected": 0, "present": 0, "success": 0, "rows": 0, "duplicate_codes": 0})
    errors = []
    hashes = Counter()
    for day in expected:
        year = day[:4]
        a = annual[year]
        a["expected"] += 1
        path = files.get(day)
        if path is None:
            continue
        a["present"] += 1
        try:
            raw = path.read_bytes()
            body = json.loads(raw)
            meta, rows = body["metadata"], body["rows"]
            if meta.get("error_code") != "0":
                errors.append({"date": day, "reason": meta.get("error_msg", "source error")})
                continue
            expected_hash = meta.get("sha256")
            unsigned = dict(meta)
            unsigned.pop("sha256", None)
            canonical = {"metadata": unsigned, "rows": rows}
            canonical_raw = (json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            if expected_hash != hashlib.sha256(canonical_raw).hexdigest():
                errors.append({"date": day, "reason": "sha256 mismatch"})
                continue
            codes = [r.get("code") for r in rows]
            dup = len(codes) - len(set(codes))
            a["success"] += 1
            a["rows"] += len(rows)
            a["duplicate_codes"] += dup
            hashes[meta["sha256"]] += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({"date": day, "reason": f"invalid snapshot: {exc}"})
    for year, a in annual.items():
        a["research_ready"] = (
            a["expected"] == a["present"] == a["success"]
            and a["duplicate_codes"] == 0
            and not any(e["date"].startswith(year) for e in errors)
        )
    report = {
        "asset_id": "QD-007",
        "status": "DISCOVERY_ONLY",
        "requested_start": ns.start,
        "requested_end": ns.end,
        "expected_dates": len(expected),
        "present_dates": sum(a["present"] for a in annual.values()),
        "errors": errors,
        "annual": dict(sorted(annual.items())),
        "note": "This report does not activate the asset; registry and cross-table PIT gates remain required.",
    }
    out = Path(ns.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"expected_dates": len(expected), "present_dates": report["present_dates"], "annual": report["annual"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
