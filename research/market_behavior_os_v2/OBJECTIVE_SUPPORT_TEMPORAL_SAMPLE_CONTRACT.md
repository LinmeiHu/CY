# Objective support temporal-sample contract

Frozen before MKT-SUPPORT-DYN-DATA-001 accesses any newly selected QD-004 row.
MKT-SUPPORT-GEO-001 established fixed-control external distinctness for recovery
speed and recovery-volume intensity only. It did not establish support defense,
temporal recurrence, prediction, or usefulness.

## Scientific question

Can a larger strategy-independent, calendar-distributed sample provide enough
objective-level repeated-test and recovery observations to preregister a
temporal-process experiment without selecting dates or symbols from minute
behavior?

This is a data/sample contract. Passing does not freeze a recovery trajectory or
authorize an outcome test.

## Calendar-only block selection

For each year 2018--2023:

1. take all registered exchange sessions from March 1 through November 30;
2. for block index `i` in zero-based `0..7`, select endpoint at zero-based index
   `floor((2*i+1)*N/16)` in that year's window;
3. form the block from the endpoint and the four immediately preceding
   registered exchange sessions;
4. require all eight blocks to contain five distinct consecutive exchange
   sessions and to be mutually nonoverlapping.

The exact endpoints are frozen in the experiment spec. This produces 48 broad,
approximately evenly spaced blocks without examining QD-004, price-level tests,
recovery, volume, strategy events, or outcomes. The March start preserves ample
history for the 40-session causal-coordinate challenge.

## Eligibility-only symbol selection

For every year, block, and governed view `ALL_A`, `SH_A`, `SZ_A`, and
`CHINEXT_BOARD`, candidates must be `coordinate_eligible` on all five block
sessions. Select exactly ten symbols by ascending:

`SHA256(MKT-SUPPORT-DYN-DATA-001|MARKET|year|block_id|view|symbol)`.

Ties break lexicographically by symbol. Selection reads only the governed
calendar and CY-006 daily/action coordinate. Minute completeness, prices,
support tests, recovery, volume, strategy membership, and outcomes are
prohibited. Cross-view duplicate security-dates retain separate cohort
identities but share one raw-minute audit.

The frozen daily-only feasibility audit gives:

- 1,920 five-session sequences;
- 9,600 cohort rows;
- 9,575 unique security-sessions;
- minimum complete candidates in any block/view: 625;
- 38 naturally selected unique supported-action sessions, with at least three
  in every year.

These counts are input/sample identities, not minute-behavior evidence.

## Inherited PIT and source-role contract

- Prior objective levels are exact 10/20/40-session causal action-coordinate
  daily lows through t-1; L20 remains primary.
- CY-006 supplies the causal scale. Every observed QD-004 minute OHLC remains
  unchanged except multiplication by that scale.
- Independent daily/minute close disagreement is retained; no equality,
  tolerance, rounding, substitution, clipping, or repair is allowed.
- Require the exact 241-bar auction/continuous/lunch/close grid, positive finite
  mapped OHLC, complete CY-008 lineage/reconciliation, and valid limit geometry.
- Rights, blocking, unresolved, late, conflicting, unsupported, or nonpositive
  action bridges fail closed.
- Completed descriptors are available at 15:30 Asia/Shanghai. No same-session
  action or use of a minute after a decision timestamp is permitted.
- All registered content hashes and full daily population gates pass before
  sample construction or raw-minute access.

## Sample-adequacy gates for the next map

After the data contract passes, minute behavior may be counted but not selected
or estimated. A later temporal map is permitted only if the primary continuous
L20 definition provides:

- at least 120 sequences with tests on at least two of five sessions;
- at least 50 such sequences in each fixed block 2018--2020 and 2021--2023;
- at least 15 such sequences in each year;
- at least 100 sequences with at least two recovered tested sessions having
  defined recovery speed and recovery-volume intensity;
- at least 40 such recovered sequences in each fixed temporal block.

Ten-/40-session levels, auction inclusion, near-touch bands, cross-view
duplicates, or reduced floors cannot rescue a failure. Counts determine only
whether a separate temporal representation may be frozen; they are not process
estimates.

## Resource envelope

- Planned unique raw rows: exactly 9,575 x 241 = 2,307,575.
- One Python process; annual partition/date/symbol/column pruning; no raw
  materialization or duplicate dataset.
- Content verification and compressed source reads: 20 GiB ceiling.
- Peak process RSS: 3 GiB hard ceiling; system memory headroom: at least 8 GiB.
- Temporary disk: 1 GiB; durable outputs: 100 MiB.
- Wall clock: 10 minutes. Stop and reassess rather than relax science.

The frozen host check showed 349 GiB free disk and more than 8 GiB immediately
free memory before execution.

## Required outputs and boundary

Persist the selected sample, coordinate/source audit, population audit, minute
support-count audit, result, and report. Execute twice and require byte-identical
outputs. Independently test the calendar endpoint operator, hash ordering,
cross-view identity conservation, and count-only boundary.

No future value, future return, strategy/outcome field, post-2023 partition, or
CY-011 may be read. Passing establishes only an adequate bounded PIT-B sample
for a later objective-recovery temporal representation map. It establishes no
support, defense, strengthening, weakening, failure process, prediction,
habitat, timing, execution, or strategy.
