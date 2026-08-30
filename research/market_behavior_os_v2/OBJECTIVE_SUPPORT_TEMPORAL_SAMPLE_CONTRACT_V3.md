# Objective support temporal-sample contract V3

Frozen before MKT-SUPPORT-DYN-DATA-003 executes a complete minute audit. This is
an exact scientific retry of the frozen 001 sample and 002 resource correction.
Only minute-read batching changes.

## Invalid 002 boundary and first differing state

MKT-SUPPORT-DYN-DATA-002 passes input identities, capped daily construction,
population, calendar, sample, target coordinates, and disposable-spill cleanup.
It then exceeds the unchanged 3-GiB lifetime process-RSS ceiling during the
first annual minute phase. No output was written and no adequacy count or
process estimate was inspected or accepted.

The first resource divergence is the raw-table population. The 2018 sample has
1,595 exact target security-sessions, or 384,395 required raw rows. The annual
adapter receives independent lists of 40 dates and selected symbols, so its
predicate reads every existing date-symbol combination in that Cartesian
superset: 2,849,825 rows. A separate 1-GiB daily-memory measurement then reaches
4,344,119,296 bytes peak RSS. This is batching over-read, not a scientific
sample, coordinate, or descriptor failure.

## Exact block-batched correction

MKT-SUPPORT-DYN-DATA-003 inherits every calendar, symbol, coordinate, source,
descriptor, adequacy, prohibited-input, and claim field from 001 and every
2-GiB-memory/10-GiB-disposable-spill correction from 002.

The sole additional change is:

- group targets by frozen `(target_year, block_id)`;
- read the same annual QD-004 partition once per five-session block request;
- each request contains exactly the unique sequence symbols for those five
  dates, all of which are required on every date;
- validate and release each block table before the next block;
- require exactly 241 rows per unique target session and exactly 2,307,575 raw
  rows over the complete run.

No date, symbol, security-session, minute, or descriptor is removed. Partition,
column, session-grid, CY-008, action-coordinate, and availability semantics are
unchanged.

## Mandatory reference equivalence

Before the complete 48-block audit, run both the annual parent reader and the
block-batched reader on the frozen first 2018 block only. Because the reference
slice contains one block, both must return identical sorted cohort audit rows
for every source diagnostic, mapped coordinate, tested flag, recovery
completion, recovery speed, and recovery-volume intensity. Require byte-stable
canonical-frame hashes and exact row/key equality. A disagreement stops before
required scale.

## Unchanged resource and scientific boundaries

- DuckDB one thread, 2-GiB memory, 10-GiB isolated disposable spill removed
  before minute access.
- 3-GiB peak RSS, 8-GiB system headroom, 20-GiB compressed input reads,
  100-MiB durable outputs, ten-minute wall time, and 25% disk headroom.
- Exact 48 blocks, 1,920 sequences, 9,600 cohort rows, 9,575 unique sessions,
  38 selected action sessions, L20 primary/L10-L40 neighbors, no near touch.
- Count-only adequacy floors remain 120 repeated-tested sequences with 50 per
  block and 15 per year; 100 twice-recovered sequences with 40 per block.
- Two complete byte-identical runs; no temporal process estimate, future value,
  outcome, strategy field, post-2023 data, or CY-011.

Passing remains data/sample adequacy only, not evidence of support defense,
recovery progression, prediction, payoff, habitat, timing, or a strategy.
