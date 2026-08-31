# Objective-crossing economic-response data contract

Frozen with the economic-response map before constructing or inspecting any
future return or downside value. This contract permits only reused pre-2024 market
behavior outcomes and does not authorize strategy outcomes, post-2023 data, or
CY-011.

## Immutable inputs

- Predictor panel: exact MKT-BREAKOUT-DIFF-001 panel/result. Only the seven fixed
  L20 raw fields, their existing causal PIT 3-year percentiles, identifiers, and
  lineage fields may be read.
- Market response source: registered CY-006 daily PIT-B causal table, exactly its
  six hashed 2018--2023 partitions.
- Coordinate algorithm: byte-semantic staged supported-action chain accepted by
  MKT-SUPPORT-DATA-003 and MKT-BREAKOUT-DIFF-DATA-001.
- Later conditional controls: exact MKT-BRTH-002 and MKT-VOL-001 panels/results;
  they are not read in the count-only response build.

Changed hashes, registry activation, partition identity, source keys, source date
range, or PIT lineage fail closed. No file discovery, data fallback, adjusted
vendor field, QD-004, CY-008, post-2023 partition, strategy artifact, or CY-011 is
allowed.

## Clock and observability

The state at event date t is available only after the completed official daily bar
at 15:00 Asia/Shanghai, with `available_at <= decision_at`. The response begins on
the next exchange session t+1. A session-h response is observable only after the
official close of t+h. No bar-t fill, entry price, auction inference, execution,
T+1 sale, limit-fill, tradability, or strategy-return claim is made.

Future daily bars are authorized solely as response variables after the contract
is frozen. Predictor construction remains strictly through t. Every output row
preserves predictor snapshot identity and explicit response-available timestamps.

## Fixed anchor population and missing-data rule

The anchor cohort for each date/view/denominator is the exact causally eligible
L20 population that generated MKT-BREAKOUT-DIFF-001 at t. View membership and
ALL_STATUS/NON_ST membership are fixed at t; future ST status is never used to
select outcomes.

A security has a response only if each of the five immediately subsequent
exchange sessions exists and has a valid consecutive supported-action coordinate
step, valid OHLC, causal corporate-action facts available by that future session,
and finite positive coordinate close and mapped low. This one complete-five-
session cohort is used for all 1/3/5 outcomes so horizon comparisons do not change
constituents. Suspensions are not automatically discarded: they remain only when
the governed history/coordinate row is valid; no volume or invented fill is
required after t. Rights-action or unknown-action steps fail closed.

No imputation, forward fill, normalized mass, clipping, rounding, tolerance,
delisting-return invention, raw-price substitution, or shorter-horizon rescue is
allowed. The final five 2023 exchange dates cannot have a complete in-contract
five-session response and are explicitly ineligible. Earlier event dates may have
responses crossing a calendar-year boundary; attribution remains to the event
year. No response may extend beyond 2023-12-29.

Each eligible response cell must retain at least 95% of its anchor securities and
must still exceed the frozen view floor (ALL_A 1,000; SH_A 400; SZ_A 400;
CHINEXT_BOARD 200). Every view/denominator/year must retain at least 150 dates. A
failure stops the economic experiment; another cohort definition may not rescue
it.

## Exact action-coordinate response series

Let `C_i,t` be the accepted continuous coordinate close of anchor security i. For
future exchange-session offset k, let `C_i,t+k` be its coordinate close and
`L_i,t+k = C_i,t+k * (raw_low_i,t+k / raw_close_i,t+k)` its mapped low. The
ratio is evaluated first so an exact raw `low == close` remains exactly equal in
the coordinate; this is not clipping or a tolerance.

For the fixed complete-five-session cohort `I_t`:

- security terminal log return is `r_i,h = log(C_i,t+h / C_i,t)`;
- security adverse log excursion is
  `a_i,h = min_{k=1..h} log(L_i,t+k / C_i,t)`;
- primary broad-market terminal return is `mean_i(r_i,h)`;
- primary broad-market downside response is `mean_i(a_i,h)`.

The downside metric is a cross-sectional mean of constituent adverse excursions,
not a synchronously tradable index low. It deliberately uses only daily-bar lows
and makes no intraday timestamp claim. More negative values mean worse downside.

For h in exactly {1,3,5}, secondary outputs are terminal median, positive-return
fraction, terminal p10/p90, adverse median, adverse p10, and cohort count. Quantiles
are deterministic linear empirical quantiles. No capital weighting, rebalance,
fees, cash, benchmark subtraction, or index substitution is used.

## Outcome-panel construction audit only

The first data experiment may construct the date/view/denominator response panel
and report:

- source/key/time/action-coordinate audits;
- predictor key/snapshot identity;
- anchor and complete-response counts and retention by date/view/denominator/year;
- exact response availability and maximum consumed date;
- finite/domain/conservation checks;
- five deterministic scalar coordinate/return/downside reconstructions;
- response values only in the durable panel.

It may not join a state value to a response value in an estimator, sort outcomes by
state, calculate a state/outcome correlation, form high/low states or crossing
episodes, inspect favorable directions, run controls/placebos, or classify a role.
The runner does not print response values or serialize outcome summaries. This
separates response-domain validity from economic inference.

## Overlap and later estimation

The response panel keeps all eligible dates. The scientific experiment must apply
the map's fixed nonoverlap phases to daily level inference. The five-opposite-side
episode rule already prevents within-role episode overlap through h=5. Cross-role
or nested-view overlap is retained but never treated as independent evidence.

## Determinism and resources

- one Python process, one DuckDB thread, 1.5 GiB DuckDB memory limit;
- 10 GiB isolated disposable spill ceiling, 3 GiB process peak RSS ceiling, and
  8 GiB preflight system-memory headroom;
- six compressed input partitions under 20 GiB, 20-minute wall-clock ceiling,
  100 MiB durable-output ceiling, and at least 25% filesystem headroom;
- no security-level durable output or raw source copy;
- two independent executions must produce byte-identical panel, count audit,
  result, and report.

Runtime seconds, temporary paths, and host-volatility measurements are not
serialized. Five scalar cases are selected by the smallest SHA-256 of
`MKT-BREAKOUT-ECON-DATA-001|symbol|trade_date` among complete response securities
and independently reconstruct all five future steps and h=1/3/5 outputs without
calling the aggregate helper. Exact equality is required for identically ordered
operations; no tolerance can repair a mismatch.

## Claim boundary

Passing establishes only a bounded, PIT-governed, action-coordinate broad-market
response domain for a separately frozen economic-response experiment. It does not
establish prediction, causality, a useful level, an incremental crossing, market
habitat, timing, execution, payoff, or strategy usefulness.
