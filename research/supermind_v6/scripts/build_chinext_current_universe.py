from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

DEFAULT_MASTER = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet"
)
DEFAULT_OUTPUT = Path(
    "research/supermind_v6/manifests/chinext_current_survivor_universe.json"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    master = pd.read_parquet(args.master)
    selected = master[
        master["exchange"].eq("SZ")
        & master["board"].eq("GEM")
        & master["status"].eq("listed")
        & master["symbol"].astype(str).str.fullmatch(r"(?:300|301)\d{3}")
    ].copy()
    selected = selected.sort_values("symbol").reset_index(drop=True)
    if selected["symbol"].duplicated().any() or selected.empty:
        raise ValueError("invalid ChiNext current-survivor universe")
    records = [
        {
            "symbol": f"{row.symbol}.SZ",
            "raw_code": str(row.symbol),
            "name": str(row.name),
            "master_list_date": (
                None if pd.isna(row.list_date) else row.list_date.date().isoformat()
            ),
            "master_delist_date": (
                None if pd.isna(row.delist_date) else row.delist_date.date().isoformat()
            ),
        }
        for row in selected.itertuples(index=False)
    ]
    payload = {
        "universe_version": "v6-chinext-current-survivor-1",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_master": str(args.master),
        "source_master_sha256": sha256_file(args.master),
        "selection": "exchange=SZ, board=GEM, status=listed, raw code starts 300/301",
        "point_in_time_status": "NON_PIT_CURRENT_SURVIVOR; most legacy list_date values are absent",
        "symbol_count": len(records),
        "symbols": [record["symbol"] for record in records],
        "records": records,
    }
    atomic_json(args.output, payload)
    print(f"CHINEXT_SYMBOLS {len(records)}")
    print(f"OUTPUT {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
