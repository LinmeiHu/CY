# Objective-crosser closing-state response data contract

Frozen with the closing-state topology map before constructing or inspecting an
accepted/rejected future response. It inherits the exact DATA-002 action-
coordinate, partition, fixed-cohort, broad-binding, deterministic-ledger, scalar,
resource, and no-tolerance semantics.

## Immutable inputs

- exact MKT-FORMDEPTH-PROP-DATA-002 panel/result and its bound CY-006 partition
  identities;
- exact MKT-FORMDEPTH-PROP-001 result activating the crossing arm only;
- exact MKT-BREAKOUT-DIFF-001 predictor counts;
- exact accepted supported-action coordinate builder and DATA-002 response helper;
- exact closing-state topology map.

Changed hashes, source activation, partitions, keys, snapshots, date range, or
runner dependencies fail closed. No alternative source, file discovery, raw-price
fallback, adjusted vendor field, post-2023 partition, QD-004, CY-008, strategy
artifact, or CY-011 access is allowed.

## Exact arm conservation

At t, within the exact crossing anchor `X_t`, define accepted `A_t`, rejected
`R_t`, and exact-equality `E_t`. Within the exact complete response crossing arm
`X*_t`, define `A*_t`, `R*_t`, and `E*_t` with the same t membership.

For every date/view/denominator require integer equality:

- `|A_t| + |R_t| + |E_t| = |X_t|`;
- `|A*_t| + |R*_t| + |E*_t| = |X*_t|`;
- each anchor arm count equals immutable predictor `close_above_count20`,
  `close_below_count20`, and `close_equal_count20`;
- the crossing totals equal immutable DATA-002 crossing counts.

No equality reassignment, normalization, imputation, future status/membership,
replacement security, rounding, clipping, or tolerance may repair failure.

## Response and support

For each arm and h in exactly {1,3,5}, retain count, deterministic sum, and mean
of terminal log return and adverse log excursion. Reuse `C * (raw_low/raw_close)`
with the ratio first and the same complete five supported-action steps.

A closing-topology-complete cell requires accepted and rejected response retention
>=0.90. Minimum accepted response counts are 5/2/3/1 for
ALL_A/SH_A/SZ_A/CHINEXT_BOARD; minimum rejected counts are 8/1/3/1. Every
view/denominator/year must retain at least 150 cells. Later five-control analysis
requires at least 6,000 rows and 750/cell. Equality has no response-count floor
and is never economically estimated.

The output data experiment may report only lineage, exact arm counts/retention,
finite sums/means, support by cell-year, and 15 scalar cases (five accepted, five
rejected, five equality where available) reconstructing membership and response
fields. If five equality cases are unavailable globally, all available equality
cases are reported and the equality shortage does not affect primary-arm
adequacy; accepted and rejected must each have five exact cases.

It may not estimate state/arm association, paired effect, favorable closing arm,
classification, strategy outcome, or rule. Two full runs must reproduce every
new artifact byte-for-byte.

## Resource and claim boundary

Use one Python process/thread, 1.5 GiB DuckDB, 3 GiB RSS, 8 GiB headroom, 10 GiB
spill, 20 GiB reads, 20 minutes, 100 MiB durable output, and no security-level
durable table. Passing establishes only a valid accepted/rejected/equality
response domain. It establishes no closing-state mechanism, reversal, prediction,
causality, execution, habitat, payoff, or strategy.
