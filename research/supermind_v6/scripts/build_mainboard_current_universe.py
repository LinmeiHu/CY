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
    "research/supermind_v6/manifests/mainboard_current_survivor_universe.json"
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
        master["board"].eq("MAIN")
        & master["status"].eq("listed")
        & (
            (
                master["exchange"].eq("SH")
                & master["symbol"].astype(str).str.fullmatch(r"(?:600|601|603|605)\d{3}")
            )
            | (
                master["exchange"].eq("SZ")
                & master["symbol"].astype(str).str.fullmatch(r"(?:000|001|002|003)\d{3}")
            )
        )
    ].copy()
    selected = selected.sort_values(["exchange", "symbol"]).reset_index(drop=True)
    if selected["symbol"].duplicated().any() or selected.empty:
        raise ValueError("invalid Shanghai/Shenzhen main-board current-survivor universe")
    records = [
        {
            "symbol": f"{row.symbol}.{row.exchange}",
            "raw_code": str(row.symbol),
            "exchange": str(row.exchange),
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
        "universe_version": "v6-mainboard-current-survivor-1",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_master": str(args.master),
        "source_master_sha256": sha256_file(args.master),
        "selection": (
            "board=MAIN, status=listed; SH prefixes 600/601/603/605 and "
            "SZ prefixes 000/001/002/003"
        ),
        "point_in_time_status": "NON_PIT_CURRENT_SURVIVOR",
        "symbol_count": len(records),
        "exchange_counts": {
            str(key): int(value)
            for key, value in selected["exchange"].value_counts().sort_index().items()
        },
        "symbols": [record["symbol"] for record in records],
        "records": records,
    }
    atomic_json(args.output, payload)
    print(f"MAINBOARD_SYMBOLS {len(records)}")
    print(f"EXCHANGE_COUNTS {payload['exchange_counts']}")
    print(f"OUTPUT {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
