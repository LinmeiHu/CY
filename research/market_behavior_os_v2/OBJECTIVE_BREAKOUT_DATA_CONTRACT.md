# Objective breakout coordinate and event-support contract

Frozen before MKT-BREAKOUT-DATA-001 constructs a prior-high coordinate or reads
new raw-minute values for this frontier. The representation map fixes the
science; this experiment asks only whether its event domains are available in
the already governed bounded sample.

## Immutable sample and source inheritance

- Reuse exactly the MKT-SUPPORT-DYN-DATA-004 sample: 1,920 sequences, 9,600
  cohort rows, and 9,575 unique security-sessions over the 48 fixed calendar
  blocks in 2018--2023.
- Preserve all cohort identities, four market views, relative days, block/year
  definitions, and the five-session selection order. No minute value, crossing,
  reference level, strategy field, or outcome may affect selection.
- Bind the exact registered CY-006, QD-004, CY-008, QD-010, calendar, registry,
  minute-adapter, and parent sample artifacts by content hash.
- Use only the six already bound 2018--2023 partitions. CY-011 and post-2023
  partitions remain unopened.

## Exact prior-high coordinate

Construct the same CY-006 causal close chain already accepted by the support
program. For every valid daily row:

`coordinate_high = coordinate_close * raw_daily_high / raw_daily_close`.

For each target t:

- `resistance_high10` is the maximum coordinate high over t-10..t-1;
- `resistance_high20` is the maximum coordinate high over t-20..t-1;
- `resistance_high40` is the maximum coordinate high over t-40..t-1.

All 41 current/prior rows and 40 coordinate steps must be consecutive,
hard-valid, action-valid, finite, positive, and causally available. Current t is
excluded from every reference. The inherited no-rights/no-blocking action scope
does not change.

For all 9,575 unique targets, `coordinate_close`, raw daily close, coordinate
scale, snapshot identity, support L10/L20/L40 values, and eligibility must match
the immutable 004 coordinate audit exactly under round-trip binary parsing.
This is a protected-coordinate equivalence gate. Any first disagreement stops
the experiment; no tolerance, rounding, rescaling, or row deletion is allowed.

## Minute and event semantics

- QD-004 raw/unadjusted OHLCV and amount are mapped by the exact target scale
  `coordinate_close / raw_daily_close`.
- CY-008 must retain the exact 241-row complete-session, source-resolution,
  unit, OHLC, volume/amount, snapshot, and 15:30 availability gates.
- Primary event: at least one of the 240 continuous mapped highs at
  09:31..11:30 or 13:01..15:00 is strictly greater than L20.
- Fixed count challenges: L10 continuous, L40 continuous, and L20 including the
  separate 09:30 auction row.
- First crossing is the first qualifying bar on that exact clock. Equality is
  not a crossing. No near-touch band exists.
- Closing states are strict above, exact equal, or strict below the unchanged
  within-session level.
- `remaining_bars` counts bars strictly after the crossing bar. A +k horizon is
  count-eligible only when at least k bars remain. No return or path estimate is
  computed here.
- A close loss occurs when any post-cross close is strictly below the level. A
  reacquisition occurs only if a later close is strictly above it. This audit
  counts eligibility only; it does not compute depth, speed, return, dwell,
  VWAP, volume intensity, direction, or usefulness.

## Frozen count gates

Primary L20 continuous support requires all of:

- at least 360 crossing cohort sessions total;
- at least 120 in each fixed temporal block A=2018--2020 and B=2021--2023;
- at least 30 in every year;
- at least 120 `CROSS_CLOSE_ABOVE` and 120 `CROSS_CLOSE_BELOW` sessions total,
  with at least 40 of each in both temporal blocks and 10 of each in every year;
- at least 240 crossings with 60 bars remaining, 80 in each block, and 20 in
  every year. The +5/+15/+30 counts are reported but have no weaker substitute
  role if +60 fails;
- at least 80 loss-and-reacquisition sessions total, 25 in each block, and five
  in every year for that conditional role to advance. Failure of only this last
  gate defers reacquisition while the other session roles may advance.

Every governed market view must contain at least 50 primary crossing cohort
sessions total and at least five in every year. Because view samples overlap,
these are portability-support audits, not independent cross-sectional evidence.

Each L10/L40 continuous neighbor and L20 auction challenge must have at least
240 crossing cohort sessions total, 80 per fixed block, 20 per year, and 80 in
each close-above/close-below arm total. A neighbor cannot rescue failed L20
continuous primary support.

Report, without gating or exclusion:

- exact-equality closing states;
- auction-only versus continuous crossings;
- first-cross position and remaining-bar count distributions;
- up-limit/down-limit contacts;
- action rows;
- cohort and unique-session counts by horizon, year, block, and view;
- sequences with zero, one, and two-or-more crossing sessions.

No descriptor direction, correlation, trajectory, transition probability,
economic outcome, or subgroup performance may be estimated.

## Orthogonal reconstruction and deterministic output

Select five primary crossing unique sessions by smallest
SHA-256(`MKT-BREAKOUT-DATA-001|symbol|trade_date`). A scalar implementation must
independently reconstruct daily coordinate highs over the exact prior 20
sessions, their maximum, the mapped minute highs, strict first crossing,
closing state, and remaining bars. It may not call the vectorized event helper.
All scalar values and indices must match exactly.

Execute twice and require byte-identical sample, coordinate/event audit, count
audit, result, and report outputs.

## Resource envelope

- One process and one DuckDB thread.
- Daily-coordinate memory limit: 1.5 GiB, using an isolated disposable spill
  directory capped at 10 GiB and removed before raw-minute reads.
- Raw-minute batches: fixed `(target_year, block_id)` groups, released before
  the next group.
- Planned complete raw rows: exactly 2,307,575; compressed-read ceiling 20 GiB.
- Peak RSS ceiling 3 GiB; system available-memory floor 8 GiB between batches.
- Wall-clock ceiling ten minutes; durable output ceiling 100 MiB.
- Preserve at least 25% filesystem headroom. No raw-minute materialization or
  duplicate raw dataset.

The first 2018 block must also reproduce the same vectorized output through a
single-block reference path before full block-batched execution. Any resource
breach or reference disagreement stops rather than changing the sample.

## Claim boundary

Passing establishes bounded PIT-B prior-high coordinate and event-domain
feasibility only. It establishes no stable acceptance representation, recurring
process, breakout quality, overhead supply, demand, prediction, habitat,
incrementality, entry timing, execution, payoff, or strategy. A failed exact
gate may not be rescued by a different lookback, threshold, clock, date, view,
sample, tolerance, or favorable state pooling.
