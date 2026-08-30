# Objective support temporal-sample contract V4

Frozen before MKT-SUPPORT-DYN-DATA-004 executes the complete block-batched
minute audit. This is an exact scientific and batching retry of 003. Only the
DuckDB daily-coordinate memory limit changes.

## Invalid 003 boundary

MKT-SUPPORT-DYN-DATA-003 retains block batching but inherits 002's 2-GiB
DuckDB daily-memory setting. The daily phase peaks near the 3-GiB lifetime RSS
ceiling; the subsequent reference/block phase crosses that ceiling. Execution
stops without a complete output or an inspected/accepted adequacy count.

This does not reject block batching, the sample, coordinate, descriptor, or
recovery family. It demonstrates that the daily-phase lifetime peak needs more
margin before any Arrow block table is allocated.

## Frozen final resource correction

A same-SQL 1.5-GiB DuckDB measurement followed by the exact first 2018 block
produces:

- peak process RSS: 2,144,124,928 bytes;
- available system memory: 12,700,811,264 bytes;
- live disposable daily spill: 9,155,805,184 bytes;
- exact reference-block cohort rows: 200;
- exact reference-block unique sessions: 200.

All values pass the already frozen 3-GiB RSS, 8-GiB headroom, and 10-GiB binary
spill ceilings. MKT-SUPPORT-DYN-DATA-004 therefore changes only
`duckdb_memory_limit` from 2 GiB to 1.5 GiB.

## Exact inheritance

Every 001 sample/scientific identity, 002 disposable-spill rule, and 003
five-session block batching/reference-equivalence rule is unchanged. In
particular:

- 48 blocks, 1,920 sequences, 9,600 cohort rows, 9,575 unique sessions;
- 2,307,575 complete raw rows;
- exact causal action coordinate and distinct CY-006/QD-004 source roles;
- exact 241-bar grid and 15:30 availability;
- L20 primary, L10/L40 neighbors, no near-touch threshold;
- count-only adequacy floors and no process estimates;
- 20-GiB reads, 100-MiB durable output, ten-minute wall time, 25% disk headroom;
- two complete byte-identical runs;
- no future value, outcome, strategy field, post-2023 data, or CY-011.

No resource value may be relaxed further inside 004. A complete failure after
this measured correction triggers synthesis rather than another memory/batch
search. Passing remains data/sample adequacy only, not support defense,
recovery progression, prediction, payoff, habitat, timing, or a strategy.
