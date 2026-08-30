# Objective support external geometry map

Frozen before MKT-SUPPORT-GEO-001 constructs any control. MKT-SUPPORT-001
established internal representation quality only. This experiment asks whether
the four surviving session roles and two stable five-day shapes add a genuinely
support-specific observation beyond ordinary daily and intraday path geometry.

## Fixed roles and matched alternatives

| Frozen role | Domain | Fixed alternatives |
|---|---|---|
| Signed test geometry | all 1,200 market sessions | official daily low versus L20; official daily close versus L20; continuous-session time of low |
| Conditional recovery speed | tested and recovered sessions | continuous time of low; close location in range; minute realized volatility |
| Conditional recovery amplitude | tested sessions | official daily range/close; continuous close location; continuous open-to-close return |
| Conditional recovery-volume intensity | tested and recovered sessions | continuous minute-volume Herfindahl; opening-30-minute volume share; closing-30-minute volume share; time of low |
| Five-day signed-geometry slope | all 240 sequences | official daily-low/L20 slope; official daily-close/L20 slope; minute intraday-range slope |
| Five-day closing-level-state slope | all 240 sequences | official daily-close/L20 slope; official daily-low/L20 slope; minute open-to-close-return slope |

No control is selected from observed correlation. All are fixed by economic role.
Do not delete a highly explanatory control to preserve a support label.

## Control semantics

- Official daily low distance: causal-coordinate daily low divided by prior L20,
  minus one.
- Official daily close distance: causal-coordinate daily close divided by prior
  L20, minus one.
- Daily range: `(daily high-daily low)/daily close` from CY-006.
- Continuous open-to-close return: QD-004 15:00 close / 09:31 open minus one.
- Continuous close location: `(15:00 close-min low)/(max high-min low)`;
  zero-range sessions remain undefined and fail required support.
- Time of low: first minimum-low bar index divided by 239.
- Minute realized volatility: square root of summed squared log close changes.
- Volume Herfindahl: sum of squared continuous minute-volume shares.
- Opening/closing 30-minute shares: first/last 30 continuous bars divided by
  total continuous volume.

Daily controls use CY-006 official values. Minute controls use QD-004 observed
values. Cross-source close disagreement is retained and no value is substituted.

Trajectory controls use the same frozen five-day slope operator as the target.
No endpoint, ordinal, 3-day, or alternative horizon can rescue a failed slope
geometry.

## Coordinate and domain architecture

- Unconditional session roles: raw absolute and same-date/view relative-rank
  coordinates are both required.
- Conditional session roles: raw tested/recovered domains only. Within-date ranks
  are not constructed from sparse, selected subsets.
- Trajectory roles: raw absolute and within-year/view ranks over ten sequences
  are both required.
- PIT historical coordinates remain unavailable from isolated five-day blocks.

Conditional blocks are fixed as 2018--2020 and 2021--2023. Each must contain at
least 30 complete observations for a conditional role. Unconditional session
cells require 50 rows in every year/view; trajectory cells require ten sequences
in every year/view.

## External distinctness gates

All estimators operate on average-tie ranks.

For unconditional session and trajectory coordinates:

1. every target/control pair has global absolute Spearman below 0.85;
2. median within-year/view absolute Spearman is below 0.85;
3. joint adjusted rank R-squared is below 0.70 globally;
4. maximum within-year/view adjusted rank R-squared is below 0.85.

For conditional raw domains:

1. every target/control pair is below absolute Spearman 0.85 in the full sample
   and both fixed blocks;
2. joint adjusted rank R-squared is below 0.70 full sample and below 0.85 in each
   block;
3. both blocks pass the 30-observation and nondegeneracy gates.

Every fixed coordinate/domain is conjunctive. A favorable raw, relative, block,
view, or role cannot rescue another failure. Pairwise and joint evidence are
both required.

## Interpretation

- Redundancy with daily low/close distance means a minute support role is a
  daily price-level manifestation, not incremental minute structure.
- Redundancy with range/close-location/return means a recovery role is generic
  intraday path geometry, not evidence of objective support defense.
- Distinctness means only that the role is not reconstructed by these fixed
  alternatives. It does not establish defense, temporal recurrence, prediction,
  payoff, timing, habitat, or a strategy.
- OHLCV cannot reveal buyer initiative, seller identity, absorption, queues, or
  participant intent.

No future value, strategy/outcome field, post-2023 data, or CY-011 may enter.
