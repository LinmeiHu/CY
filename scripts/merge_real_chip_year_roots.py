#!/usr/bin/env python3
"""Merge disjoint exact-chip year roots with verified hard links."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _summary_identity(root: Path) -> dict[str, Any]:
    summary = root / "summary.json"
    if not summary.is_file():
        raise FileNotFoundError(f"source summary is missing: {summary}")
    return {
        "root": str(root),
        "summary_path": str(summary),
        "summary_sha256": _sha256(summary),
    }


def _link_inventory(source: Path, temp: Path, kind: str) -> set[str]:
    symbols: set[str] = set()
    for path in sorted((source / kind).glob("bucket=*/*.parquet")):
        relative = path.relative_to(source)
        target = temp / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        symbol = path.stem.replace("_SH", ".SH").replace("_SZ", ".SZ")
        if target.exists():
            if target.stat().st_size != path.stat().st_size or _sha256(target) != _sha256(path):
                raise RuntimeError(f"conflicting duplicate chip file: {relative}")
        else:
            os.link(path, target)
        symbols.add(symbol)
    return symbols


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--expected-files", type=int, required=True)
    parser.add_argument(
        "--excluded-symbol",
        action="append",
        default=[],
        metavar="SYMBOL=REASON",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    sources = [source.resolve() for source in args.source]
    existing_summary = output / "summary.json"
    if existing_summary.is_file():
        payload = json.loads(existing_summary.read_text(encoding="utf-8"))
        if payload.get("status") == "PASS" and payload.get("files") == args.expected_files:
            print(json.dumps(payload, sort_keys=True))
            return 0
        raise RuntimeError(f"existing merged output is incompatible: {output}")
    if output.exists():
        raise RuntimeError(f"output exists without a reusable PASS summary: {output}")

    excluded: dict[str, str] = {}
    for item in args.excluded_symbol:
        symbol, separator, reason = item.partition("=")
        if not separator or not symbol or not reason:
            parser.error("--excluded-symbol must use SYMBOL=REASON")
        excluded[symbol] = reason

    temp = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    try:
        part_symbols: set[str] = set()
        terminal_symbols: set[str] = set()
        for source in sources:
            part_symbols.update(_link_inventory(source, temp, "parts"))
            terminal_symbols.update(_link_inventory(source, temp, "terminal"))
        if part_symbols != terminal_symbols:
            raise RuntimeError(
                "merged part/terminal symbol sets differ: "
                f"parts_only={sorted(part_symbols - terminal_symbols)[:5]} "
                f"terminal_only={sorted(terminal_symbols - part_symbols)[:5]}"
            )
        if len(part_symbols) != args.expected_files:
            raise RuntimeError(
                f"expected {args.expected_files} symbols, found {len(part_symbols)}"
            )
        payload = {
            "status": "PASS",
            "created_at": datetime.now(UTC).isoformat(),
            "year": args.year,
            "storage_version": "chip-operator-log-v11",
            "model_version": "real-chip-inventory-v2.1",
            "files": len(part_symbols),
            "symbols": len(part_symbols),
            "part_terminal_sets_equal": True,
            "merge_mode": "verified_hard_links",
            "sources": [_summary_identity(source) for source in sources],
            "excluded_symbols": excluded,
        }
        (temp / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        temp.replace(output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
