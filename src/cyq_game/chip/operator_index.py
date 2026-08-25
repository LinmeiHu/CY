"""Immutable symbol locator for compact chip operator logs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

INDEX_SCHEMA = pa.schema(
    [
        ("symbol", pa.string()), ("year", pa.int32()), ("bucket", pa.int32()),
        ("path", pa.string()), ("start_date", pa.date32()), ("end_date", pa.date32()),
        ("checkpoint_dates", pa.list_(pa.date32())), ("row_groups", pa.int32()),
        ("file_size", pa.int64()), ("sha256", pa.string()),
    ]
)


def build_operator_symbol_index(root: Path) -> Path:
    rows: list[tuple[object, ...]] = []
    paths = tuple(root.glob("parts/bucket=*/*.parquet")) + tuple(
        root.glob("year=*/parts/bucket=*/*.parquet")
    )
    for path in sorted(paths):
        parquet = pq.ParquetFile(path)
        table = parquet.read(columns=["symbol", "trade_date", "checkpoint_local_ids"])
        symbols = table["symbol"].unique()
        if len(symbols) != 1:
            raise ValueError(f"operator part does not contain exactly one symbol: {path}")
        dates = table["trade_date"].combine_chunks()
        checkpoints = table["checkpoint_local_ids"].combine_chunks()
        date_values = [dates[index].as_py() for index in range(len(dates))]
        checkpoint_dates = sorted(
            {date_values[index] for index in range(len(dates)) if len(checkpoints[index]) > 0}
        )
        symbol = str(symbols[0].as_py())
        rows.append(
            (symbol, min(date_values).year, int(path.parent.name.split("=", 1)[1]),
             str(path.relative_to(root)), min(date_values), max(date_values), checkpoint_dates,
             parquet.num_row_groups, path.stat().st_size, _sha256(path))
        )
    target = root / "operator_symbol_index.parquet"
    arrays = [
        pa.array([row[index] for row in rows], type=field.type)
        for index, field in enumerate(INDEX_SCHEMA)
    ]
    pq.write_table(pa.Table.from_arrays(arrays, schema=INDEX_SCHEMA), target,
                   compression="zstd", use_dictionary=True)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
