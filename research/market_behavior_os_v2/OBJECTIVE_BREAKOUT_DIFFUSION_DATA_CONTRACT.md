# Objective breakout formation and diffusion data contract

Frozen before MKT-BREAKOUT-DIFF-DATA-001 constructs the full-market coordinate or
inspects crossing counts. The representation map fixes the scientific semantics;
this contract establishes only whether the governed daily population can support it.

## Registered input and immutable boundary

- Asset: CY-006 daily PIT-B causal research table v2.
- Exact registered inventory: six partitions for 2018--2023 only.
- Source rows expected: 6,155,390 with zero duplicate symbol/date keys, zero
  `available_at > decision_at`, and zero hard-valid OHLC failures.
- Registry, inventory, six partition hashes, representation map, accepted
  MKT-BREAKOUT-DATA-001 coordinate/event audit, and MKT-BRTH-002 panel/result are
  immutable inputs bound by SHA-256 in the experiment spec.
- QD-004, CY-008, strategy artifacts, post-2023 partitions, and CY-011 are not read.

Unknown or changed identity fails closed. No file discovery, partition fallback, or
unregistered substitute is permitted.

## PIT and coordinate semantics

- Observation/decision timestamp: completed official daily bar at 15:00
  Asia/Shanghai.
- Required source gate: `available_at <= decision_at`.
- First possible action: a later causally valid session; this experiment creates no
  action or signal.
- Preserve source `snapshot_id`; the output state is available at the completed
  close.
- Construct the exact supported-action continuous-close chain already accepted by
  MKT-SUPPORT-DATA-003 and MKT-BREAKOUT-DATA-001.
- Require all 41 current/prior rows, 40 coordinate steps, daily OHLC, action facts,
  and exchange-calendar positions to be valid and consecutive.
- Current mapped high is `coordinate_close * raw_high / raw_close`; each prior-high
  level is the maximum mapped high over strictly prior 10/20/40 rows.

No future-adjustment factor, vendor-adjusted field, normalization, clipping,
rounding, tolerance, chain repair, rights-action assumption, or raw/coordinate
substitution is allowed.

## Full-market population

Construct every causally eligible 2018--2023 security-date, then expand to the four
fixed views and ALL_STATUS/NON_ST denominators in the representation map. The first
40 source exchange dates are coordinate warm-up and do not enter the output.

Daily population floors are unchanged from the accepted support/breadth contracts:

- ALL_A: 1,000;
- SH_A: 400;
- SZ_A: 400;
- CHINEXT_BOARD: 200.

Every date/view/denominator cell must pass. NON_ST must be a subset of ALL_STATUS;
SH_A and SZ_A must partition ALL_A; CHINEXT_BOARD must be a subset of SZ_A.

## Count-only feasibility audit

The data experiment may report only aggregate support facts by horizon, year, view,
and denominator:

- eligible, crossing, close-above/equal/below counts;
- total crossing depth sum and close-below depth sum for conservation only, without
  publishing daily role estimates or correlations;
- industry mapping coverage, included industries, event-bearing industries,
  accepted-event industries, and days meeting the frozen industry domains;
- number of date/view/denominator cells where each later role is defined;
- coordinate/action validity and exact-equality cases.

It may not compute PIT normalization, relative ranks, neighboring-definition
correlations, redundancy, trajectories, transition rates, state bins, forecasts, or
economic outcomes.

## Prefrozen adequacy gates

For each of L10/L20/L40 and both denominators:

- at least 95% of the 1,417 post-warm-up dates in each market view must have a valid
  population cell;
- every view-year must contain at least 150 valid cells and at least 2,000 L20
  crossing security-events in aggregate;
- every view-year must contain at least 500 L20 close-above and 500 L20 close-below
  events;
- nonindustry L20 formation/depth/acceptance/rejection roles must be defined on at
  least 95% of valid date cells in every view;
- industry mapping must pass on at least 90% of valid L20 date cells in every view;
- formation-distribution domains must pass on at least 90% of valid date cells in
  every view;
- acceptance-distribution domains must pass on at least 85% of valid date cells in
  every view;
- every view-year must contain at least 150 defined industry-role observations.

L10/L40 are conjunctive feasibility challenges, not rescue alternatives. A failed
L20 primary cannot be replaced by a neighboring horizon, another view, or a pooled
denominator.

## Protected-coordinate replication

Join the full-market coordinate to the immutable 9,575 unique target rows in
MKT-BREAKOUT-DATA-001. Require exact binary equality for:

- raw daily close;
- coordinate close and coordinate scale;
- resistance_high10/20/40;
- coordinate eligibility and snapshot identity.

The accepted target audit contains minute-defined continuous crossing states; the
daily experiment does not compare those events because an official daily high also
contains auction information. It replicates only the protected daily coordinate.

Select five unique L20 daily crossings by smallest SHA-256 of
`MKT-BREAKOUT-DIFF-DATA-001|symbol|trade_date`. A scalar source-row calculation must
independently reconstruct the 40 coordinate steps, three strictly prior levels,
current mapped high/close, crossing, closing state, and depth values. It may not call
the aggregate daily event helper. Exact binary equality is required where identical
operations are specified; no tolerance may be introduced to rescue a mismatch.

## Determinism and resource envelope

- One Python process and one DuckDB thread.
- DuckDB memory limit 1.5 GiB.
- Isolated disposable spill capped at 10 GiB and removed after completion.
- Process peak RSS ceiling 3 GiB and system available-memory floor 8 GiB before the
  full build.
- Source compressed-read ceiling 20 GiB; six partitions are read once through the
  governed projection.
- Wall-clock ceiling ten minutes and durable-output ceiling 100 MiB.
- Durable outputs contain only aggregate count audit, result JSON, and report; no
  full security-level table or raw-data copy is materialized.
- Preserve at least 25% disk headroom.

Execute twice and require byte-identical count audit, result, and report. Runtime
seconds, temporary paths, and host-volatility fields are not serialized.

## Claim boundary

Passing establishes only daily PIT-B coordinate/population/domain feasibility for a
later separately frozen representation experiment. It establishes no stable breadth
role, discovery mechanism, breakout quality, acceptance process, demand, forecast,
habitat, timing, execution, economic usefulness, or strategy. A failed gate may not
be rescued by changing a horizon, threshold, industry floor, denominator, date range,
or population after counts are observed.
