#!/usr/bin/env python3
"""Freeze an allowlisted subset of a directory as a SHA-256 file inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_files(root: Path, patterns: list[str]) -> list[Path]:
    selected: set[Path] = set()
    for pattern in patterns:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError(f"pattern must be relative and contained: {pattern}")
        selected.update(path.resolve() for path in root.glob(pattern) if path.is_file())
    files = sorted(selected)
    if not files:
        raise ValueError("patterns selected no files")
    for path in files:
        if not path.is_relative_to(root):
            raise ValueError(f"selected path escapes root: {path}")
    return files


def freeze(root: Path, patterns: list[str], output: Path, workers: int) -> str:
    root = root.expanduser().resolve()
    output = output.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"root is not a directory: {root}")
    if output.is_relative_to(root):
        raise ValueError("output must be outside the frozen root")
    files = select_files(root, patterns)
    print(f"FREEZE root={root} files={len(files)} workers={workers}", flush=True)

    entries: list[dict[str, str | int]] = []
    checkpoint = max(1, len(files) // 10)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, digest in enumerate(pool.map(sha256_file, files), start=1):
            path = files[index - 1]
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": digest,
                }
            )
            if index % checkpoint == 0 or index == len(files):
                print(f"PROGRESS {index}/{len(files)}", flush=True)

    payload = {"schema_version": 1, "root": str(root), "files": entries}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, output)
    digest = sha256_file(output)
    print(f"PASS inventory={output} sha256={digest}", flush=True)
    return digest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--pattern", required=True, action="append")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        print("FAIL workers must be positive")
        return 2
    try:
        freeze(args.root, args.pattern, args.output, args.workers)
    except (OSError, ValueError) as exc:
        print(f"FAIL {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
