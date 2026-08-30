# Full-market objective-breakout diffusion dynamics map

Frozen before MKT-BREAKOUT-DIFF-DYN-001 constructs any temporal estimate. The
study asks whether the seven accepted completed-session breakout-diffusion
levels support stable historical change and acceleration representations. It
does not test future recurrence, market or strategy payoff, a breakout regime,
or usefulness.

## Parent state and semantic boundary

MKT-BREAKOUT-DIFF-001 retains seven direct levels: formation participation,
conditional crossing depth, closing acceptance, closing rejection depth,
formation-industry diffusion, formation-leadership concentration, and
stock/industry formation divergence. All are available only after the completed
15:00 close. Equal-industry formation was compressed into participation.
Acceptance-industry diffusion and concentration failed the frozen L40 ChiNext
domain and remain barred.

The level panel is the only breakout input. No security rows, minute bars,
future observations, strategy fields, post-2023 rows, or CY-011 may be read.
Historical temporal descriptors formed at t may use only rows at or before t.

## Interpretable operators

For each accepted level `x`, use fixed exchange-session positions within each
market-view/denominator group. Missing source values propagate; sessions are
never compressed around a missing observation.

### Historical change

The primary endpoint rate is

`change5(t) = (x(t) - x(t-5)) / 5`.

Fixed definition challenges are:

- endpoint rates over 3 and 10 sessions;
- OLS slope over the six values t-5 through t;
- Theil--Sen median pair slope over the same six values.

These are broad neighboring horizons and economically interpretable shape
operators, not searched windows. A role must survive every challenge; a
favorable neighbor cannot replace the primary.

### Historical acceleration

The primary adjacent-block slope change is

`acceleration5(t) = change5(t) - change5(t-5)`.

Its two component change intervals do not overlap and share only the completed
endpoint t-5. Fixed challenges are the analogous adjacent-block 3- and
10-session slope changes plus the difference between recent and prior OLS
slopes and between recent and prior Theil--Sen slopes. OLS/Theil--Sen blocks
share only their boundary value. No continuous state is discretized.

## Coordinates and representation gates

Preserve three views of every primary temporal role:

1. absolute cross-year-comparable operator values;
2. strictly causal expanding/trailing-756 percentile and trailing robust-z
   coordinates after 504 valid historical observations;
3. same-date relative-to-ALL_A values and governed-view ranks.

Representation quality is conjunctive: minimum raw coverage; stable association
with all fixed operator/horizon neighbors; ALL_STATUS/NON_ST stability;
nondegenerate view-year cells with adequate support; expected causal-PIT and
relative coverage; and semantic finiteness. The family is compressed only
after role-specific gates pass.

## Level and generic-breadth alternatives

Historical change or acceleration must not be accepted merely because it is an
endpoint level. Each primary is checked against its own completed-session level.

MKT-BRTH-002 discovery breadth and leadership concentration are fixed external
alternatives. Apply the identical primary change or acceleration operator to
those two accepted levels, then test raw, causal-PIT, and relative cells. No
control may be deleted. Pairwise absolute Spearman and joint adjusted rank R2
must remain below frozen redundancy boundaries.

Internal redundancy is evaluated on ALL_A/ALL_STATUS primaries. Priority is
change before acceleration within each parent role, followed by the parent
level priority already frozen by MKT-BREAKOUT-DIFF-001. Connected-looking
coordinates are not automatically called a latent mechanism; only the minimal
nonredundant representation panel is retained.

## Time, robustness, and claim boundary

The panel spans 2018-03-06 through 2023-12-29. Stability is assessed over fixed
calendar years and two reused descriptive blocks, 2018-2020 and 2021-2023.
Those blocks do not constitute confirmation. A phase diagnostic recomputes
neighbor association on every fifth eligible primary row, reducing overlap;
it is a representation challenge, not a future-response estimate.

Passing establishes only that a historical change or acceleration coordinate
is reproducibly representable from completed market state and is not reduced to
the fixed alternatives. It establishes no persistence/reversal, future state,
forecast, favorable habitat, demand/supply mechanism, trigger, veto, timing,
execution, payoff, capacity, or strategy archetype.
