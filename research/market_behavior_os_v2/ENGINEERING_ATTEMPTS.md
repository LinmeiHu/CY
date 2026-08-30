# Engineering-attempt ledger

## MKT-TRND-001-A — invalid before feature construction

- Frozen QD-003 manifest and all six source-file hashes passed.
- `pandas.read_parquet` delegated to PyArrow's dataset reader.
- The first immutable source raised `OSError: Repetition level histogram size
  mismatch` before a DataFrame or feature existed.
- No outcome is permitted by the experiment and none was read. No scientific
  result or artifact was produced.

## MKT-TRND-001-B — invalid input audit

The adapter uses DuckDB's Parquet reader with the frozen `trade_date <=
2023-12-31` predicate. This reader was separately probed against the first source
and returned the expected bounded date/count tuple. The first complete audit then
found one `csi000852` row (2016-08-11) with close 8531.691 below its recorded low
8532.329. The attempt stopped before feature acceptance.

## MKT-TRND-001-C — exact scientific retry with frozen fail-closed semantics

The MKT-TRND-001 spec already requires an unknown or invalid input to become
missing and fail closed. The adapter records the abnormal row, marks it
`source_hard_valid=false`, and sets all four OHLC fields to missing because the
source cannot establish which coordinate is wrong. Exact rolling windows that
touch the row therefore remain missing. No normalization, clipping, correction,
or relaxed OHLC tolerance is used.
