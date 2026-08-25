#!/usr/bin/env python3
"""Assemble verified annual exact-chip roots into one partitioned lineage root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _symbol(path: Path) -> str:
    code, exchange = path.stem.rsplit("_", 1)
    return f"{code}.{exchange}"


def _parse_year_root(value: str) -> tuple[int, Path]:
    raw_year, separator, raw_root = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("year root must use YEAR=PATH")
    try:
        year = int(raw_year)
    except ValueError as error:
        raise argparse.ArgumentTypeError("year must be an integer") from error
    return year, Path(raw_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--year-root",
        action="append",
        type=_parse_year_root,
        required=True,
        metavar="YEAR=PATH",
    )
    args = parser.parse_args()
    year_roots = dict(args.year_root)
    if len(year_roots) != len(args.year_root):
        parser.error("year roots must be unique")

    output = args.output.resolve()
    temporary = output.with_name(f".{output.name}.assembling")
    if output.exists() or temporary.exists():
        raise RuntimeError(f"output or temporary path already exists: {output}")
    temporary.mkdir(parents=True)

    symbols_by_year: dict[str, list[str]] = {}
    all_symbols: set[str] = set()
    sources: list[dict[str, Any]] = []
    try:
        for year, raw_root in sorted(year_roots.items()):
            root = raw_root.resolve()
            summary_path = root / "summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if summary.get("status") != "PASS" or summary.get("year") != year:
                raise RuntimeError(f"annual merge summary is not PASS for {year}: {root}")
            if not summary.get("part_terminal_sets_equal"):
                raise RuntimeError(f"annual part/terminal sets differ for {year}: {root}")

            part_paths = sorted(root.glob("parts/bucket=*/*.parquet"))
            terminal_paths = sorted(root.glob("terminal/bucket=*/*.parquet"))
            part_symbols = {_symbol(path) for path in part_paths}
            terminal_symbols = {_symbol(path) for path in terminal_paths}
            if part_symbols != terminal_symbols or len(part_paths) != len(part_symbols):
                raise RuntimeError(f"annual file inventory differs for {year}: {root}")
            if len(part_paths) != int(summary["files"]):
                raise RuntimeError(f"annual file count differs from summary for {year}: {root}")

            for source in part_paths:
                relative = source.relative_to(root / "parts")
                target = temporary / f"year={year}" / "parts" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(source, target)

            ordered_symbols = sorted(part_symbols)
            symbols_by_year[str(year)] = ordered_symbols
            all_symbols.update(ordered_symbols)
            sources.append(
                {
                    "year": year,
                    "root": str(root),
                    "files": len(part_paths),
                    "excluded_symbols": summary.get("excluded_symbols", {}),
                    "summary_path": str(summary_path),
                    "summary_sha256": _sha256(summary_path),
                }
            )

        ordered_all = sorted(all_symbols)
        (temporary / "symbols.txt").write_text(
            "".join(f"{symbol}\n" for symbol in ordered_all), encoding="utf-8"
        )
        (temporary / "symbols_by_year.json").write_text(
            json.dumps(symbols_by_year, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        assembly = {
            "status": "PASS",
            "created_at": datetime.now(UTC).isoformat(),
            "merge_mode": "verified_hard_links",
            "storage_version": "chip-operator-log-v11",
            "model_version": "real-chip-inventory-v2.1",
            "years": sorted(year_roots),
            "symbols": len(ordered_all),
            "symbols_by_year": {
                year: len(symbols) for year, symbols in symbols_by_year.items()
            },
            "sources": sources,
        }
        (temporary / "assembly.json").write_text(
            json.dumps(assembly, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    print(json.dumps(assembly, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
