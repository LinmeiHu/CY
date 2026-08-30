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

## MKT-MIN-001-B — invalid required attempt at the exact RAM guard

The first required run stopped before accepting an output when process peak RSS
reached 3,227,631,616 bytes, exactly 6,406,144 bytes above the 3 GiB ceiling.
The first differing resource state was annual causal context retained with
audit-only columns after its daily/minute eligibility flags were already known.
The scientific input, population, descriptors, and gates were unchanged.

## MKT-MIN-001-C — memory-reduced exact retry

CY-006 and CY-008 eligibility is now computed before their join; only symbol,
date, ST status, eligibility, and bound selection lineage survive into the
annual context. A repeated representative run preserves the same descriptor and
opening values while lowering peak RSS below 1.9 GiB. Two reduced-context runs
have panel hash `fcc04aec73da783328926ff882491a4a7ac4efffea06acb6cb7a106d338dc0b0`
and opening hash `9093a928e0bb47d0548e4b8b855e7f30c91837875035d1267efb7598553ab360`.
Required scale then passes at 2,896,543,744 bytes peak RSS and 407.55 seconds. No
ceiling was relaxed.

## HAB-CHX-001-A — invalid combined-panel serialization

The frozen association calculations completed in memory, but the first output
attempt renamed `entry_signal_date` while retaining the state join's existing
`trade_date`, creating duplicate labels in the completed-cycle projection.
Pandas stopped at concatenation and no result was accepted. The projection now
selects `entry_signal_date` before renaming it. A regression test asserts unique
panel columns and the unchanged 1,337 + 819 + 280 row decomposition. No input,
sample, endpoint, gate, or estimate changed.

## MKT-RISK-001-A — invalid over-strict runner abort

The first frozen run constructed the daily panel in memory and then stopped the
entire experiment because `CHINEXT_BOARD / ALL_STATUS / 2021-05-17` retained
827 of 838 coordinates, or 0.9868735 below the frozen 0.99 group/date gate.
The first invalid rows were 11 ST securities whose registered 5% limit geometry
did not enclose their completed close. No source fact was repaired, no tolerance
was introduced, and no result artifact was accepted.

The scientific contract already says an affected representation may be marked
missing on inadequate coordinate coverage. The corrected runner therefore
keeps the 0.99 threshold unchanged, marks that exact group/date `view_valid=false`,
and records all 603 core rows outside their registered limits. It does not alter
CY-006 market-rule facts. All other eligible group/dates pass the frozen gate.

## MKT-MIN-PATH-001 — invalid availability declaration

The bound-input test stopped before trajectory construction because every
required-scale trajectory row carries `available_at=15:30`, while the new spec
incorrectly declared 15:00. The latest included minute remains the completed
15:00 bar; the derived market artifact becomes available at 15:30 under the
original MKT-MIN-001 contract. No feature/result artifact was accepted.

MKT-MIN-PATH-002 inherits the exact `bf7e05dc...` scientific design and changes
only derived-artifact availability plus output identity. No timestamp is moved
earlier, no post-15:00 minute is read, and no descriptor/operator/gate changes.

## MKT-INDRS-GEO-001 — invalid nested causal warm-up eligibility

The bound-input audit passed all six hashes, accepted-role identities, 10,696
keys, and 15:00 timestamps, then stopped before geometry because the frozen
general raw coverage period included an accepted control that is itself built
from two causal rolling percentiles. The leadership/discovery imbalance has no
2019 values and only 107 observations/group in 2020. Its own PIT percentile has
a second warm-up and only 89 observations/group in 2022. No panel, correlation,
joint reconstruction, or result was accepted.

MKT-INDRS-GEO-002 inherits spec `33b0f114...` and changes only eligible years
for this nested control and the corresponding fixed-control joint intersection.
The 95% coverage, 150-observation cell, pairwise, and joint thresholds are not
lowered; the control is not deleted or replaced.

## MKT-VOL-TRANS-001 — invalid direction-habitat PIT support

The frozen input, key, timestamp, population, and t+25 response-shift audits
passed. The run then stopped before any output was accepted because one block-A
direction-habitat PIT cell within a separate view/denominator retained 123
complete observations against the unchanged 150 minimum. No result is cited.

MKT-VOL-TRANS-002 inherits scientific spec `21145136...` and changes only the
direction-modifier grouping. It pools all four governed views within each
index/denominator, retains both denominators and all six indices, and performs
the complete support audit before correlations. The 150/120 cell gates,
habitat splits, response, controls, blocks, and claims are unchanged.
