# Objective support temporal-sample contract V2

Frozen before MKT-SUPPORT-DYN-DATA-002 accesses a newly selected QD-004 row.
This is an exact scientific retry of MKT-SUPPORT-DYN-DATA-001 after a measured
resource-envelope failure. No calendar, date, symbol, coordinate, level,
descriptor, adequacy floor, prohibited input, or claim changes.

## Invalid parent boundary

MKT-SUPPORT-DYN-DATA-001 verified every bound input and constructed the exact
daily coordinate, population, calendar blocks, 9,600-row sample, and 9,575
target coordinates. It stopped at the resource guard before the first QD-004
minute read.

The uncapped exact DuckDB construction reached 11,135,991,808 bytes peak RSS and
left 7,738,458,112 bytes system memory available while live. It violated both
the frozen 3-GiB process ceiling and 8-GiB headroom floor. Releasing the
connection cannot erase a lifetime peak and therefore cannot validate 001.

A same-SQL engineering measurement with DuckDB `memory_limit='2GB'` reached
2,698,985,472 bytes peak RSS and left 12,885,016,576 bytes available. It used
8,787,951,616 bytes of live disposable spill. Thus it passes the unchanged RSS
and memory-headroom rules but not 001's 1-GiB temporary-disk ceiling.

No minute value, level test, recovery observation, adequacy count, process
estimate, future field, strategy field, or CY-011 was read in either attempt.

## Exact retry correction

MKT-SUPPORT-DYN-DATA-002 inherits the complete
`OBJECTIVE_SUPPORT_TEMPORAL_SAMPLE_CONTRACT.md` and 001 scientific spec. The
only permitted changes are:

- DuckDB daily-coordinate execution uses one thread and a 2-GiB memory limit;
- spill is isolated in one newly created disposable directory;
- live spill may not exceed 10 GiB;
- the directory must be removed after the daily connection closes and before
  annual QD-004 minute reads begin;
- result/output identities use MKT-SUPPORT-DYN-DATA-002.

The 10-GiB cap provides 1.82 GiB above the measured spill while consuming less
than 3% of the prefreeze 349-GiB free disk. At least 25% disk headroom remains.
No raw dataset or permanent intermediate is materialized.

## Unchanged scientific and safety gates

- Exact 48 calendar blocks, 1,920 sequences, 9,600 cohort rows, 9,575 unique
  sessions, and hash ordering.
- CY-006-only selection; exact causal action coordinate; QD-004 observed OHLC;
  CY-008 lineage/reconciliation; no source equality or tolerance.
- L20 primary, L10/L40 neighbors, no near-touch threshold, exact 241-bar grid,
  and completed-session 15:30 availability.
- Count-only minimums: 120 repeated-tested sequences, 50 per temporal block,
  15 per year; 100 twice-recovered sequences and 40 per temporal block.
- Peak RSS 3 GiB, system headroom 8 GiB, compressed read 20 GiB, durable output
  100 MiB, and wall time ten minutes.
- Two byte-identical complete runs. No process estimator, future value, outcome,
  strategy field, post-2023 data, or CY-011.

Passing remains sample/data adequacy only. It establishes no support, defense,
recovery progression, prediction, payoff, habitat, timing, or strategy.
