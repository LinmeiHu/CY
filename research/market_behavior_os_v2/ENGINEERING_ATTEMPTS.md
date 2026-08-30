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

## MKT-VOL-TRANS-002 — invalid discovery-habitat support

The direction grouping correction passed its complete support audit. Before any
correlation, the same audit then found a block-A discovery raw view/denominator
cell with 127 complete observations against 150. No 002 output or result was
accepted.

MKT-VOL-TRANS-003 keeps the direction correction and pools both governed
denominators within each discovery view. It retains all four views and changes
six-of-eight sign support to the equivalent three-of-four 75% proportion. Cell
thresholds, habitats, fields, controls, horizons, blocks, and claims remain
unchanged.

## MKT-VOL-TRANS-003 — invalid report hash-key serialization

The complete support audit passed and all frozen estimators ran. The report
renderer then requested `hashes.spec_sha256`, while the result stored the same
immutable parent identity as `hashes.scientific_spec_sha256`. Execution stopped
without a complete accepted output set. Partial 003 estimates were not inspected
or used for a research decision.

MKT-VOL-TRANS-004 changes only the result hash alias and output identity. The
scientific and final control specs, every estimate, and every gate are unchanged.

## MKT-SUPPORT-DATA-001 — invalid reused-sample coordinate coverage

The runner verified every frozen partition content hash and completed the full
daily population audit before target construction. All 11,336 population cells
pass with a minimum margin of 426. Target coverage then stopped on
`603232.SH`/2019-06-10 before QD-004 access: a blocking hard-invalid 2019-05-30
action row leaves 40/41 valid history rows and 38/40 valid coordinate steps.

The reused accepted cohort contains 37 such failures: 17 short listing histories
and 20 invalid/blocking action-history windows. The runner emitted no frozen
output. This is a scientific sample-contract mismatch, not an adapter or action-
coordinate implementation defect. Do not alter 001; freeze any eligibility-
aware sample as a new semantic experiment.

## MKT-SUPPORT-DATA-002 — invalid source-close equality

The eligibility-aware sample, partition hashes, population, coordinate, and
limit gates passed. The first QD-004 row then stopped at exact equality:
`000090.SZ`/2018-06-08 has 8.520000457763672 versus CY-006 8.52. No output was
written. A read-only complete-target diagnostic found 1,161 bitwise mismatches
and 39 integer-cent mismatches among 1,225 unique sessions; all 39 are 2018
Shanghai and the maximum difference is seven cents.

The registered CY-008 build validates internal minute OHLC, units, session
completeness, and volume/amount reconciliation; it never promises equality of
the minute final bar to CY-006 official daily close. This is a scientific source-
role error, not floating tolerance trouble alone. A corrected implementation
must preserve QD-004 prices and use CY-006 only to obtain the causal coordinate
scale. It must report exact close differences and never force equality.

## MKT-SUPPORT-001 — invalid overlapping manual case identities

The first complete construction passed scientific gates but the validation
casebook used the same eligible session for overlapping recovery/repeated-test
categories and another session for both no-test/action categories. The first
duplicate was `ACTION|2018|03|603727.SH|2018-06-15`. The resulting output set is
unaccepted even though estimates completed.

The minimal correction preserves all descriptors and gates and selects the
lexicographically first *unused* audit identity in the frozen category order. A
regression check requires five categories and five distinct identities. No
scientific value, threshold, sample row, or representation decision changes.

## MKT-SUPPORT-DYN-DATA-001 — invalid daily-coordinate resource envelope

The exact six-year DuckDB daily-coordinate construction completed sample and
target selection but reached 11,135,991,808 bytes peak RSS and only
7,738,458,112 bytes live system headroom. The frozen 3-GiB RSS and 8-GiB
headroom guards stopped execution before the first newly selected QD-004 row.

An exact-SQL 2-GiB-memory-limit measurement reduced peak RSS to 2,698,985,472
bytes and preserved 12,885,016,576 bytes headroom, but required 8,787,951,616
bytes live disposable spill, above 001's 1-GiB temporary ceiling. No 001 output
or minute-derived count is accepted. The separately frozen 002 retry changes
only the disposable spill ceiling and engine configuration; all science remains
identical.

## MKT-SUPPORT-DYN-DATA-002 — invalid annual minute Cartesian over-read

The exact 002 resource retry passes the daily phase under its measured cap and
removes spill before minute access. Its first annual QD-004 phase then breaches
the unchanged 3-GiB lifetime RSS ceiling. No complete output or adequacy count
is accepted.

The first differing population is explicit: 1,595 exact 2018 target sessions
require 384,395 rows, while independent annual date/symbol predicates
materialize 2,849,825 rows before the exact-pair merge. A separate 1-GiB daily
measurement plus that annual table peaks at 4,344,119,296 bytes. The 003 retry
must batch by the already frozen five-session block and prove reference
equivalence before complete scale; it may not shrink or replace the sample.

## MKT-SUPPORT-DYN-DATA-003 — invalid block-batch lifetime RSS margin

The block-batched retry still inherits a 2-GiB daily-coordinate memory limit.
Its daily lifetime peak plus the first reference/block allocation breaches the
unchanged 3-GiB RSS guard. No complete output or adequacy count is accepted.

A same-SQL 1.5-GiB daily-memory measurement plus the exact first block peaks at
2,144,124,928 bytes RSS, preserves 12,700,811,264 bytes available memory, and
uses 9,155,805,184 bytes live spill, all within existing ceilings. The 004 retry
changes only that engine memory setting. Further in-experiment resource rescue
is prohibited.

## MKT-STYLE-001 — invalid cumulative size-rank denominator

The first implementation used an ordered window for both row number and count.
The count was therefore cumulative, the first size-rank fraction was 0.5, and
every small tail was empty. Execution reached partial result writing but failed
before a complete report. The first differing state was
`size_rank_fraction`; partial roles and compression are unaccepted evidence.

The correction changes only the denominator to the full same-date/view/
denominator partition. A focused four-row regression test requires exact rank
fractions 0.125, 0.375, 0.625, and 0.875. Bucket boundaries, roles, gates, and
all scientific semantics are unchanged.

## MKT-STYLE-001 — invalid parallel floating reduction

After the rank correction, scientific decisions repeated but two executions
had different panel hashes. The first differing cell was
`size_return_spread1_small40_large40`, differing by about 1e-15 while keys and
decisions matched. No multithreaded artifact was accepted.

The final implementation fixes DuckDB to one thread, preserving full precision
instead of rounding away the discrepancy. Two subsequent complete executions
are byte-identical; no representation formula or gate changed.

## MKT-SUPPORT-DYN-001 — invalid default CSV float parsing

The first execution failed the parent descriptor-equivalence gate on two exact
boundary sessions. The first difference was 600162.SH on 2020-04-16: parent
`tested=False`, reconstructed `tested=True`. The default parser changed stored
coordinate scale `0.32403374497482107` down by one ULP, making mapped minimum low
equal rather than strictly greater than L20.

The correction uses pandas `float_precision="round_trip"` for the immutable
17-significant-digit coordinate artifact. A focused regression binds that exact
session and preserves `2 * scale > L20`. No price tolerance, rounding, level,
test rule, row, or scientific gate changed. Five focused tests and two complete
final executions pass byte-identically.

## MKT-BREAKOUT-001-A — invalid leading-auction VWAP requirement

The first full construction stopped before accepting an artifact at
`000972.SZ` on 2018-03-16 under `L20_AUCTION`. The 09:30 auction bar has zero
volume and amount, positive cumulative volume begins at 09:31, and the first
strict auction-inclusive crossing occurs at 09:37. Post-cross cumulative VWAP
is therefore fully defined, but the adapter incorrectly required positive
cumulative volume on every earlier path bar.

The corrected adapter leaves cumulative VWAP undefined while cumulative volume
is zero and requires positive cumulative volume only from the first crossing
onward. This is fail-closed and does not impute a price. The event population,
crossing clock, post-cross formula, sample, thresholds, gates, and claims are
unchanged. A focused regression covers the leading zero-volume case; three
tests and both final deterministic executions pass.

## MKT-BREAKOUT-DYN-001 — invalid selection ordinal as time

The frozen temporal map/spec declared `market_sequence_rank` as the event-time
coordinate. The first attempted trajectory stopped before any count or estimate:
`2018|01|ALL_A|02|600576.SH / L10_CONTINUOUS` crosses on 2018-03-12 and
2018-03-13, but both rows correctly retain selection ordinal 2. The field ranks
the hash-selected symbol inside its block/view and is constant through time.

The already frozen `relative_day` values -5 through -1 are the actual market-
session coordinate. MKT-BREAKOUT-DYN-002 changes only that declaration and
output identity. It retains the original bootstrap/scalar seed identity and all
roles, controls, gates, definitions, and prohibitions.

## MKT-BREAKOUT-DYN-002-A — invalid wrapper parent-spec path

The first 002 wrapper invocation redirected the imported module's active spec
path before calling its immutable 001 parent validator. The validator therefore
compared the 002 file with the expected 001 hash and stopped before reading the
panel or constructing an estimate. The wrapper now scopes the parent path only
during parent validation and restores the active output spec afterward. A
focused regression exercises this exact wrapped order.

## MKT-BREAKOUT-DYN-002-B — invalid nondeterministic output schema

The corrected 002 runner completed the frozen estimators, then output inspection
found `elapsed_seconds` serialized into result JSON. That field cannot be byte-
identical across runs. The wrapper hash also did not bind its imported scientific
runner. No 002 result is accepted as reproducible evidence.

MKT-BREAKOUT-DYN-003 changes only output identity: dynamic elapsed metadata is
removed and wrapper, time-coordinate, and scientific-runner hashes are recorded.
All revealed estimates, sample rows, roles, operators, seeds, controls, gates,
and decisions are unchanged. Two 003 runs are byte-identical.

## MKT-BREAKOUT-HAB-001-A — invalid missing derived block label

The first frozen runner attempt loaded and validated all bound parents, then
stopped before its first support count because the breakout input projection
retained `target_year` but not a materialized `temporal_block` column. The
scientific spec had already fixed A=2018--2020 and B=2021--2023.

The adapter now derives that exact label immediately after the primary L20
projection. A focused regression requires both A and B. No event, prior-state
date, role, coordinate, control, support floor, estimator, threshold, or claim
changed; no invalid-run output was accepted.

## MKT-BREAKOUT-DIFF-DATA-001-A — invalid fused-coordinate execution

The first full-market runner used one fused CTE for the protected cumulative
action coordinate. It stopped before any count artifact was accepted at the
first exact disagreement: `000020.SZ` on 2019-08-29 produced
`0.7990230286113049` instead of accepted `0.799023028611305`.

A direct diagnostic found that formulas and step log returns were identical,
but DuckDB's fused and accepted materialized window plans differed by one ULP
in the full cross-section. No tolerance, rounding, or coordinate change was
allowed. The runner now preserves the accepted materialization boundaries
(`base -> stepped -> chained -> continuous`) before the prior-high window,
then drops disposable stages. All 9,575 protected targets reproduce exactly;
the final two count runs are byte-identical and stay below every resource ceiling.
