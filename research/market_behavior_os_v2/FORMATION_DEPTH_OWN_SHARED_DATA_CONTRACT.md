# Formation-depth own/shared response data contract

Frozen with the own/shared map before any stratum response construction. This
experiment establishes only whether the exact anchor strata and their already-
accepted future responses can be constructed and conserved.

## Sources and clocks

- Daily facts: exact registered CY-006 2018--2023 partitions already bound by the
  accepted formation-depth response builders.
- Anchor coordinate and response coordinate: exact accepted PATH-DATA-001 code
  and action semantics; no formula, operation order, or future horizon changes.
- Predictor panel: exact MKT-BREAKOUT-DIFF-001 market formation-depth panel.
- Joint predictor availability: completed session t at 15:30 Asia/Shanghai.
- Response: next exchange session through fixed h=5, never a predictor.
- Raw minute inputs QD-004/CY-008 are prohibited.

Every source hash and accepted predecessor classification must pass before a
query is created. `hard_valid`, `available_at`, `snapshot_id`, action-chain,
trading-calendar, suspension, and fixed-cohort rules remain unchanged.

## Construction order

1. Reconstruct exact event anchors and own depth.
2. Expand the four governed views and two denominators.
3. On all t crossers, assign deterministic five-way anchor strata by own depth
   and symbol.
4. Separately construct the accepted future complete-response cohort.
5. Left-join responses to immutable anchor strata by exact symbol/date.
6. Aggregate anchor depth and response count/sum/mean for all five strata.
7. Derive other-four-strata depth by exact count/sum subtraction.
8. Attach causal PIT coordinates only after absolute stratum construction.

No response value or completeness flag may enter steps 1--3.

## Exact conservation

For every date/view/denominator:

- five stratum anchor counts sum exactly to the bound crossing anchor count;
- a deterministic symbol/own-depth ledger proves that the five strata exhaust
  the same exact anchor-security multiset;
- five depth sums reconstruct the new deterministic total numerator and mean;
- each stratum response count is <= its immutable anchor count;
- five stratum response counts sum exactly to the bound crossing response count;
- each response mean equals its deterministic sum/count;
- other count equals total anchor count minus own-stratum anchor count;
- other depth sum equals total depth sum minus own-stratum depth sum;
- relative depth equals own mean minus other mean without normalization/clipping;
- h=1/3/5 dates and `available_at` match the bound response panel.

Exact integer, membership-ledger, response, and within-build floating identities
are required. The historical bound mean came from an unordered aggregate and is
retained side by side, not used as a cross-query binary identity. Any binary
difference is reported without a pass tolerance. No rounding, clipping,
normalization, or favorable omission may hide a mismatch.

## Adequacy gates

- exact output key is date/view/denominator/stratum;
- five rows per eligible date/cell;
- at least 25 anchor crossers per eligible cell;
- at least five anchor crossers per stratum;
- at least 85% response retention in every complete stratum cell;
- at least 100 complete dates in every view/denominator/year;
- causal PIT values require 504 finite observations in the trailing 756 positions;
- at least 6,000 later rows across all five strata after PIT and six mandatory
  controls, with at least 700 per stratum;
- five deterministic security cases per stratum reconstruct anchor assignment,
  own depth, and h=1/3/5 responses exactly.

If support fails, the economic experiment is not activated. Floors, number of
strata, tie rule, response horizon, coordinate, or control requirements cannot
be changed inside this experiment.

## Resource contract

Single DuckDB process/thread; 1.5-GiB DuckDB memory; 1.5-GiB process RSS ceiling
under the V2.3 initial envelope; 8-GiB system headroom; 10-GiB temporary spill;
20-GiB compressed read; 20-minute wall clock; 150-MiB durable output; no durable
security-level response table; two byte-identical complete runs.

The data result cannot estimate an own/shared association, choose a stratum,
classify a channel, use a future field as predictor, access strategy outcomes,
open post-2023 data, or read CY-011.
