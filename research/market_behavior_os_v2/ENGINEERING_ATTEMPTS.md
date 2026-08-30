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

## MKT-BRTH-AUDIT-001-A — invalid query adapter

An outcome-blind CY-006 inventory query attempted to bind a prepared list
parameter inside `CREATE VIEW ... read_parquet(?)`. DuckDB rejected the prepared
parameter before reading a feature or producing an estimate. The corrected audit
used the relation API over the same six exact partitions.

## MKT-BRTH-001 — invalid nondeterministic construction

Three four-thread executions produced different panel hashes:
`a9c03bef...`, `55b388ca...`, and `ab9e8288...`. The first differing state found
by an in-memory prefix comparison was `SZ_A / ALL_STATUS / 2019-01-07`:
`leadership_positive_mass_top10` was `0.714247616791` versus
`0.714247616792`. Eight columns differed. The raw floating difference was about
`1e-12`, but it changed causal percentile ranks and one near-tied relative view
rank by `0.375`. Headline role selection happened to agree, but none of the
MKT-BRTH-001 results is accepted as evidence.

## MKT-BRTH-002 — deterministic scientific retry

MKT-BRTH-002 inherits the exact MKT-BRTH-001 scientific spec SHA
`d9199943...`. DuckDB aggregation is fixed to one thread. Inputs, universes,
formulas, horizons, coordinates, gates, and usefulness prohibitions are unchanged.

## MKT-CLQ-001-A — invalid query adapter

The first frozen construction attempt completed the source and liquidity-unit
audits, then DuckDB rejected an ambiguous `cal_idx` reference in the exact
own-amount-window join. It stopped before a daily panel or representation result
existed. The adapter now uses explicit qualified equality joins; the frozen
inputs, formulas, horizons, gates, and usefulness prohibitions are unchanged.

## MKT-CLQ-001-B — invalid exact-conservation audit

The qualified-join retry reached the daily liquidity ledger and failed the exact
identity between total amount and the disjoint below/at-or-above-top-decile
partitions. No tolerance, rounding, normalization, or result acceptance was
used. The adapter was instrumented to report the first differing state/value
before any arithmetic change is considered.

The first difference was `ALL_A / ALL_STATUS / 2018-07-03`: binary total
`332975086708.91986`, disjoint partition total `332975086708.92004`, difference
`-0.00018310546875`. A separate frozen-source audit found zero values different
from their three-decimal representation. The retry therefore uses exact
`DECIMAL(38,3)` addition after verifying that scale; it does not round source
values or relax conservation.

## MKT-MIN-001-A — vectorized scale gate passes

The frozen adapter uses annual partition selection, Parquet date/symbol
predicates, governed-column reads, and one-date batches. It validates group keys
and the exact 241-row auction/continuous/lunch grid, then reshapes complete
sessions and calculates the 34 frozen NumPy descriptors across all securities at
once. Python does not loop over minute rows or security sessions.

Tiny and 1,200-session reference gates pass. The worst descriptor difference is
`4.99933427988708e-13`, both opening-window runs match exactly, and derived
five-minute volume/amount conservation differences are zero. Two small runs have
identical descriptor/opening hashes.

The frozen 20-date representative test processes 18,201,043 rows and 71,481
final sessions in about eight seconds. Two market-panel hashes are
`ee274ca0c1cb2cd2c6fdd6427d01546aeebecee8e1c1c5c444e3af81a01d390c`;
two opening hashes are
`9093a928e0bb47d0548e4b8b855e7f30c91837875035d1267efb7598553ab360`.
Peak RSS remains below the 3 GiB hard ceiling. This is the accepted architecture
for required scale; it is not scientific representation evidence.
