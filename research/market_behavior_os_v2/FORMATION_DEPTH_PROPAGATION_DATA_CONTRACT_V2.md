# Formation-depth propagation response data contract V2

Frozen after MKT-FORMDEPTH-PROP-DATA-001 failed before accepting an arm artifact
or inspecting an arm/state association. It inherits the topology map and every
membership, coordinate, horizon, cohort, support, scalar, resource, and claim
boundary from `FORMATION_DEPTH_PROPAGATION_DATA_CONTRACT.md`, with one exact
audit correction described below.

## Diagnosed invalid audit

DATA-001 required the accepted broad floating means to be regenerated inside a
combined broad-plus-membership DuckDB process and compared bitwise with the bound
broad panel. The first difference was:

- 2018-03-06, ALL_A/ALL_STATUS, terminal mean h=1;
- combined-process value `-0.00605455421493459`;
- immutable bound value `-0.0060545542149345`;
- binary difference `-9.020562075079397e-17`.

All rows, formulas, coordinates, and counts were unchanged. Adding or planning a
second membership aggregation changed unordered binary floating summation. The
authoritative MKT-BREAKOUT-ECON-DATA-001 runner was then executed in a fresh
process and reproduced all five immutable artifacts byte-for-byte, including
panel hash `aaf67e128f490e0594a529a296f23bd3e0207e7e47a3a42f9a0ec988f2c4fbbe`.
The accepted broad domain is intact; cross-query floating aggregation is not an
identity ledger.

DATA-001 is `INVALID_CROSS_QUERY_BINARY_AGGREGATION_IDENTITY`. It accepted no
membership panel, count audit, scalar audit, result, response interpretation, or
classification. No arm values were printed or persisted.

## Corrected exact audit

DATA-002 binds the immutable broad panel/result by their existing hashes and does
not regenerate their floating means inside the membership process. It must still
reconstruct the exact action-coordinate security rows and satisfy, with integer
equality on every date/view/denominator:

- recomputed anchor count equals immutable `eligible_count20`;
- recomputed crossing count equals immutable `crossing_count20`;
- anchor crossing plus noncrossing count equals anchor count;
- complete-response crossing plus noncrossing count equals immutable broad
  response count.

Each arm's sum and mean is computed once from its exact fixed members in one
frozen deterministic query path. Two full DATA-002 runs must reproduce every arm
sum and mean byte-for-byte. Ten arm-balanced scalar cases must reconstruct exact
membership, coordinate, terminal, and adverse fields. This is a stronger valid
identity for the new objects than comparing two unordered binary reductions.

No tolerance, rounding, clipping, normalization, alternate summation, or
weighted-mean repair is introduced. DATA-002 makes no claim that independently
aggregated binary floating means conserve bitwise; the bound broad values remain
authoritative and unchanged.

## Inherited data and support boundary

All other V1 contract clauses remain exact:

- same six hashed 2018--2023 CY-006 partitions and accepted coordinate runner;
- exact `cross20` versus complement membership at t;
- fixed complete-five-session response cohort and h=1/3/5 terminal/adverse
  security formulas;
- no future membership/status selection;
- crossing retention >=0.90 and fixed crossing/noncrossing view floors;
- at least 150 topology-complete dates per view/denominator/year;
- later five-control support >=6,000 rows and >=750 per cell;
- one process/thread, 1.5/3/8/10/20 GiB memory/RSS/headroom/spill/read ceilings,
  20 minutes, 100 MiB durable output, and no security-level durable table;
- no state/arm association, favorable channel, classification, strategy outcome,
  post-2023 data, or CY-011 in the data experiment.

Passing DATA-002 remains response-domain adequacy only. It does not establish
localization, propagation, reversal, prediction, causality, habitat, execution,
payoff, or a strategy rule.
