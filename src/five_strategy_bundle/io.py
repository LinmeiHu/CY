from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .errors import ReproductionError


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_input_config(path: Path, *, required=None, prefix=None) -> dict[str, Path]:
    path = path.expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    selected = raw["inputs"]
    if required is not None:
        absent = set(required) - set(selected)
        if absent:
            raise ReproductionError("missing configured input keys: " + ", ".join(sorted(absent)))
        selected = {k: selected[k] for k in required}
    if prefix is not None:
        selected = {k: v for k, v in selected.items() if k.startswith(prefix)}
    inputs = {}
    for name, value in selected.items():
        value = Path(value).expanduser()
        inputs[name] = (value if value.is_absolute() else path.parent / value).resolve()
    missing = [f"{name}: {value}" for name, value in inputs.items() if not value.exists()]
    if missing:
        raise ReproductionError("missing configured input(s): " + "; ".join(missing))
    return inputs


def read_parquet(path: Path, sql: str = "SELECT * FROM source") -> pd.DataFrame:
    con = duckdb.connect()
    try:
        con.execute(f"CREATE VIEW source AS SELECT * FROM read_parquet('{_sql_path(path)}')")
        return con.execute(sql).fetchdf()
    finally:
        con.close()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    con = duckdb.connect()
    try:
        con.register("frame", frame)
        con.execute(f"COPY frame TO '{_sql_path(temp)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        con.close()
    temp.replace(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")
