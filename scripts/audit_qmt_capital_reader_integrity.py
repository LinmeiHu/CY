#!/usr/bin/env python3
"""Record reader-level integrity evidence for the frozen QMT capital source."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--path", required=True)
    p.add_argument("--output", required=True)
    ns = p.parse_args()
    path = Path(ns.path)
    result: dict[str, object] = {"path": str(path), "generated_at": datetime.now(UTC).isoformat()}
    result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        con = duckdb.connect()
        result["duckdb"] = {"status": "PASS", "rows": con.execute("select count(*) from read_parquet(?)", [str(path)]).fetchone()[0]}
    except Exception as exc:
        result["duckdb"] = {"status": "FAIL", "error": str(exc)}
    try:
        result["pyarrow"] = {"status": "PASS", "rows": pq.ParquetFile(path).metadata.num_rows}
    except Exception as exc:
        result["pyarrow"] = {"status": "FAIL", "error": str(exc)}
    result["research_policy"] = "DuckDB read is the audited adapter; pyarrow incompatibility is recorded and source is never overwritten."
    out = Path(ns.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
