# Reusable security-session minute primitive design

Decision: `ACCEPT_ARRAY241_PLUS_EXPLICIT_SESSION_LEDGER_FOR_DIRECTOR_REVIEW`.

This is an infrastructure result, not a minute representation, mechanism,
economic-usefulness result, or strategy result. No cache was published.

## Source and physical-layout findings

The activated lineage is already sufficient for a governed build:

- QD-004 is a 40 GiB raw/unadjusted A-share minute lake. Its activated
  2018--2026 inventory contains nine annual day files plus a 2026 QMT tail.
  The 2018--2023 annual files contain 1,486,577,999 rows in 12,800 Parquet row
  groups. Physical row groups are primarily symbol-clustered, so a date filter
  does not obtain ideal date pruning from the source layout.
- CY-006 is a 439 MiB causal daily PIT-B table with row-level availability,
  snapshot, action, trading-state, limit, and hard-valid context.
- CY-008 is a 3.1 GiB causal minute-derived table. It already proves exact
  daily-session completeness and six opening 5-minute execution windows, but it
  does not preserve the full 241-bar raw path. Its 2018--2023 audits contain
  6,114,413 daily rows and 5,814,333 hard-valid rows.
- The accepted vector adapter processed 1,473,342,173 raw rows in 407.55 seconds
  with peak RSS 2.90 GiB. This is direct evidence that the cache build is
  feasible; repeated scientific families should not repay that scan cost.

Exact input and accepted-code hashes are recorded in `result.json`.

## PIT and market-session semantics

The cache must inherit, without reinterpretation:

- `bar_end_time` is a completed, naive Asia/Shanghai local bar-end timestamp.
- Position 0 is the separate 09:30 auction row. Positions 1--120 are
  09:31..11:30. Positions 121--240 are 13:01..15:00. Lunch rows are forbidden.
- Prices are raw/unadjusted; volume is shares; amount is CNY.
- A complete session primitive is available at 15:30. It is prohibited for a
  decision earlier than that time and can never support a fill inside the same
  bar or session.
- Suspended, incomplete, duplicate, anomalous, invalid-OHLC, unit-invalid,
  unreconciled, lineage-mismatched, and hard-invalid sessions fail closed.
- Limit prices and trading state come from bound CY-006/CY-008 context. The
  cache makes no queue, hidden-liquidity, or participant-intent claim.
- Raw prices cannot be compared across sessions. Corporate-action-aware
  cross-day work must join a separately validated causal coordinate. No qfq,
  future adjustment, daily-price substitution, rounding, or equality tolerance
  is allowed.

## Minimum cache: two mandatory tables

### 1. `session_ledger`

One row for every in-scope CY-006/CY-008 security-session key, including invalid
keys. Minimum fields:

`symbol`, `trade_date`, `feature_available_at`, `grid_id`, `price_basis`,
`volume_unit`, `amount_unit`, `source_resolution_minutes`, `minute_count`,
`distinct_minute_count`, CY-006/CY-008 snapshot IDs, QD-004 partition identity,
CY-006/CY-008 hard-valid flags, session/OHLC/unit/volume/amount validity,
trading state, limit prices, market-rule validity, corporate-action validity and
blocking, `primitive_present`, and exact invalid reasons.

This ledger is mandatory: a primitive-table miss alone must never be interpreted
as suspension, nonmembership, or valid absence.

### 2. `session_primitives`

One row only for a ledger key that passes every required gate. Minimum fields:

- the ledger key and immutable lineage IDs;
- six `fixed_size_list<double>[241]` arrays: raw open, high, low, close, volume,
  amount;
- `grid_id=CN_A_1M_END_V1_241` and `feature_available_at=15:30`.

Minute timestamps are not repeated because their complete ordered vector is
defined exactly by the versioned grid ID. Arrays remain binary double; no
float32 conversion or rounding is allowed. Descriptor columns, five-day
trajectories, support levels, breakout flags, and outcomes are deliberately
absent.

The benchmark's segmented auction-plus-240-array option is more visually
explicit but 2.4% larger. The selected 241-array design remains semantically
explicit because grid position 0 is frozen as auction and the grid contract is
validated on ingestion and reading.

## Tiny benchmark

Frozen date: 2020-02-03, already in MKT-MIN-001's representative ladder.
Selection: first 128
`SHA256(WORKER-MINUTE-001|2020-02-03|symbol)` hard-valid sessions. No outcome
field was accessed.

| Layout | Rows | Bytes | Bytes/session | Write seconds | Read seconds |
|---|---:|---:|---:|---:|---:|
| raw long 241 | 30,848 | 200,552 | 1,566.81 | 0.0067 | 0.0023 |
| fixed arrays 241 | 128 | 177,508 | 1,386.78 | 0.0042 | 0.0016 |
| auction scalars + arrays 240 | 128 | 181,820 | 1,420.47 | 0.0039 | 0.0014 |

The fixed-array file is 11.5% smaller than the tiny long-form comparator. The
benchmark peak RSS was 754 MiB with one thread. These tiny cached-read timings
are layout sanity evidence only, not a full-build throughput claim.

## Partition and resource plan

Recommended physical layout:

`snapshot=<immutable-build-id>/session_ledger/year=YYYY/month=MM/part.parquet`

`snapshot=<immutable-build-id>/session_primitives/year=YYYY/month=MM/part.parquet`

Within each file sort `trade_date,symbol`; start a Parquet row group at each
date boundary, with a maximum around 4,096 sessions. This preserves full-market
date pruning, keeps the file count near 72 for 2018--2023, and remains tolerable
for a small security set over five dates. Do not add symbol buckets until a
measured query workload demonstrates a need.

At 1,386.78 benchmark bytes per valid session, primitive arrays project to 7.51
GiB for 2018--2023 and 11.66 GiB for all 9,024,309 activated hard-valid
2018--2026 sessions. Allow 8.5 GiB and 12.8 GiB respectively after the ledger,
manifest, and conservative overhead. Current disk free space was about 347 GiB.

One pre-2024 consumer avoids up to 1,486,577,999 raw QD-004 rows. Reuse families
include same-session representation maps, five-day trajectory construction,
objective support/defense, objective breakout acceptance, and consumed
winner/failure archaeology. Five such consumers avoid about 7.43 billion raw
row visits.

The accepted full-scale adapter rate implies roughly 6.8 minutes for the raw
read/validation/descriptor workload. Budget 10--15 minutes for a single-writer
pre-2024 cache build after adding lossless serialization and manifests; this is
a planning interval, not a measured full build. Start with one process, one
Arrow thread, and thread-library caps of one. Expected peak RSS is under 4 GiB;
abort above the Director's current RAM/swap guard.

## Single-writer atomic publication

1. Director freezes a build spec with exact registry, manifest, code, grid, date
   scope, schema, partition, and resource identities.
2. Acquire an exclusive snapshot-specific writer lock. Never allow two raw
   QD-004 scanners.
3. Build into `.staging/<build-id>.<pid>` on the same filesystem. Write monthly
   ledger and primitive files to temporary names, close/fsync, hash, validate,
   then rename within staging.
4. Enforce exact key uniqueness, ledger coverage, primitive-to-ledger one-to-one
   inclusion, 241-grid, numeric, unit, lineage, availability, snapshot-binding,
   action/trading-state, and deterministic replay gates.
5. Write a manifest last with every relative path, byte size, SHA-256, row count,
   min/max date, source hashes, code/spec hashes, resource telemetry, and rejected
   counts/reasons. Rebuild a tiny and one-month challenge twice and require
   byte-identical outputs.
6. Atomically rename the complete staging directory to immutable
   `snapshot=<build-id>`. Never overwrite a snapshot.
7. Only the Director may atomically replace a small current-pointer manifest
   after independent QA. Readers bind the immutable snapshot ID, not a mutable
   path.

## Claim boundary and recommendation

Approve the schema and a frozen build specification, but do not yet claim an
economic minute mechanism. The cache only removes repeated physical scans while
making invalid/missing sessions and source lineage explicit. A build should be
scheduled only when no other raw-minute scanner is active and current swap is
stable; the observed machine already had 2.39 GiB swap in use, so concurrency
must remain one for the build.
