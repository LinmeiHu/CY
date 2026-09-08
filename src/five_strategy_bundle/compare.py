from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import duckdb

from .io import _sql_path, sha256


def compare_parquet(
    actual: Path,
    golden: Path,
    identity: Iterable[str],
    values: Iterable[str] = (),
    *,
    atol: float = 0.0,
) -> dict[str, object]:
    keys = list(identity)
    values = list(values)
    if not keys:
        return {"status": "FAIL", "first_difference": "missing primary key definition"}
    fields = [*keys, *values]
    quoted = {column: '"' + column.replace('"', '""') + '"' for column in fields}
    key_sql = ",".join(quoted[column] for column in keys)
    field_sql = ",".join(quoted[column] for column in fields)
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE VIEW actual AS SELECT {field_sql} "
            f"FROM read_parquet('{_sql_path(actual)}')"
        )
        con.execute(
            f"CREATE VIEW golden AS SELECT {field_sql} "
            f"FROM read_parquet('{_sql_path(golden)}')"
        )
        actual_rows = con.execute("SELECT count(*) FROM actual").fetchone()[0]
        golden_rows = con.execute("SELECT count(*) FROM golden").fetchone()[0]
        null_predicate = " OR ".join(f'{quoted[key]} IS NULL' for key in keys)
        for name in ("actual", "golden"):
            nulls = con.execute(f"SELECT count(*) FROM {name} WHERE {null_predicate}").fetchone()[0]
            duplicate_groups = con.execute(
                f"SELECT count(*) FROM (SELECT {key_sql} FROM {name} GROUP BY {key_sql} HAVING count(*)>1)"
            ).fetchone()[0]
            if nulls or duplicate_groups:
                return {"new_row_count": actual_rows, "golden_row_count": golden_rows,
                        "status": "FAIL", "first_difference": f"{name}: null keys={nulls}, duplicate key groups={duplicate_groups}"}
        if actual_rows != golden_rows:
            return {"new_row_count": actual_rows, "golden_row_count": golden_rows,
                    "status": "FAIL", "first_difference": "row count mismatch"}
        matches = con.execute(
            f"SELECT count(*) FROM actual a JOIN golden g USING({key_sql})"
        ).fetchone()[0]
        missing = con.execute(
            f"SELECT count(*) FROM golden g ANTI JOIN actual a USING({key_sql})"
        ).fetchone()[0]
        extra = con.execute(
            f"SELECT count(*) FROM actual a ANTI JOIN golden g USING({key_sql})"
        ).fetchone()[0]
        types = {
            row[0]: str(row[1]).upper()
            for row in con.execute("DESCRIBE actual").fetchall()
        }
        numeric = {
            column for column in values
            if any(types[column].startswith(prefix) for prefix in (
                "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
                "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT",
                "FLOAT", "DOUBLE", "DECIMAL",
            ))
        }
        terms = []
        for column in values:
            name = quoted[column]
            exact = f'a.{name} IS NOT DISTINCT FROM g.{name}'
            if column in numeric and atol:
                terms.append(
                    f"(NOT ({exact}) AND (a.{name} IS NULL OR g.{name} IS NULL "
                    f"OR abs(CAST(a.{name} AS DOUBLE)-"
                    f"CAST(g.{name} AS DOUBLE))>{atol}))"
                )
            else:
                terms.append(f"NOT ({exact})")
        predicates = " OR ".join(terms) or "FALSE"
        mismatch = con.execute(
            f"SELECT count(*) FROM actual a JOIN golden g USING({key_sql}) WHERE {predicates}"
        ).fetchone()[0]
        order_sql = ",".join(
            f'coalesce(a.{quoted[key]},g.{quoted[key]})' for key in keys
        )
        first = con.execute(
            f"SELECT coalesce(a.{quoted[keys[0]]},g.{quoted[keys[0]]}) AS first_key "
            f"FROM actual a FULL JOIN golden g USING({key_sql}) "
            f"WHERE a.{quoted[keys[0]]} IS NULL OR g.{quoted[keys[0]]} IS NULL OR {predicates} "
            f"ORDER BY {order_sql} LIMIT 1"
        ).fetchone()
        deltas = [
            con.execute(
                f'SELECT max(abs(CAST(a.{quoted[column]} AS DOUBLE)-CAST(g.{quoted[column]} AS DOUBLE))) '
                f'FROM actual a JOIN golden g USING({key_sql})'
            ).fetchone()[0]
            for column in numeric
        ]
    finally:
        con.close()
    return {
        "new_row_count": actual_rows,
        "golden_row_count": golden_rows,
        "identity_match_count": matches,
        "missing_count": missing,
        "extra_count": extra,
        "value_mismatch_count": mismatch,
        "first_difference": None if first is None else str(first[0]),
        "new_sha256": sha256(actual),
        "golden_sha256": sha256(golden),
        "absolute_tolerance": atol,
        "max_abs_delta": max((float(value) for value in deltas if value is not None), default=0.0),
        "status": "PASS" if not (missing or extra or mismatch) and matches == actual_rows == golden_rows else "FAIL",
    }
