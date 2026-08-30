# Objective prior-high repeated-event temporal dynamics map

Frozen before any role-specific repeated-event count, rate, direction, or
coupling estimate is inspected.

## Scientific boundary

MKT-BREAKOUT-001 established seven stable completed-session observables. It did
not establish seven mechanisms, a favorable breakout state, a cross-session
process, a predictor, or usefulness. This map asks whether those observations
have defensible five-session repeated-event dynamics after preserving the exact
event and availability semantics.

The source sample is the immutable 48-block, 1,920-sequence calendar/CY-006-
selected cohort. A trajectory contains only days on which the same sequence's
security strictly crosses the specified causal rolling prior-high definition.
Non-crossing days remain absent events; they are never filled, interpolated, or
treated as zero. L10/L20/L40 describe successive rolling objective definitions,
not one unchanged physical resistance price.

## PIT and time semantics

- Every source role is post-cross attribution. It becomes available only after
  its defining completed bar; the full session row is available at 15:30 Asia/
  Shanghai.
- A trajectory through Day -1 is available only at 15:30 on Day -1. It cannot
  predict the first crossing or any earlier bar included in itself.
- Event order uses `market_sequence_rank`, the fixed market-session position in
  the five-session block. Endpoint rates divide by the actual rank gap between
  first and last qualifying event days.
- The experiment is PIT-B because archival record-level QD-004 availability is
  unavailable. No later session, outcome, strategy result, post-2023 partition,
  or CY-011 may enter.
- Absolute values retain unchanged 2018--2023 semantics. The isolated blocks do
  not support causal PIT historical normalization or a promotable same-date
  cross-sectional rank; neither is fabricated.

## Frozen role map

| Role | Economic observation | Direction remains neutral | Fixed same-event controls |
|---|---|---|---|
| `continuation30_log_return` | 30-bar post-cross continuation | positive or negative rate is not assumed favorable | crossing time, daily return, daily-high margin, minute volatility |
| `rejection_depth` | worst post-cross penetration below/near the level | a rising rate means less-deep rejection only algebraically | intraday range, close location, daily return, crossing time |
| `below_level_close_fraction` | dwell below the crossed level | falling is not called acceptance without process evidence | close location, daily return, crossing time, minute volatility |
| `loss_episode_count` | repeated loss of the crossed level | falling is not called strengthening without process evidence | minute volatility, intraday range, crossing time |
| `reacquisition_bars` | conditional repair time after a loss | defined only when loss then reacquisition occurs | crossing time, high time, minute volatility, close location |
| `post_cross_cumulative_vwap_acceptance_fraction` | post-cross closes above causal cumulative VWAP | not buyer initiative or accumulation | daily return, VWAP recovery count, below-VWAP duration, downside excursion, recovery speed |
| `post_cross_activity_ratio` | normalized post-cross activity | rising is not demand or conviction | volume concentration, closing-volume share, crossing time |

The three compressed MKT-BREAKOUT-001 roles are prohibited. Their trajectories
cannot be revived merely because a temporal transformation looks different.

## Temporal operators

For a role and definition, sort its finite qualifying event days by
`market_sequence_rank`.

1. **Primary endpoint rate:** `(last_value - first_value) /
   (last_rank - first_rank)` with at least two distinct event days.
2. **OLS challenge:** slope of value on market-session rank using at least three
   event days.
3. **Theil--Sen challenge:** median of all pairwise slopes using the same at
   least-three-event domain.

The endpoint rate is retained as a representation only if it agrees with both
shape challenges under the frozen correlation/sign gates. Two-point endpoint
rates are valid but are explicitly reported separately from the richer
three-plus-event domain. Exact day labels, event counts, rank spans, and first/
last values remain in the audit panel.

## Definition portability

- Primary: L20 continuous session.
- Level challenges: L10 and L40 continuous sessions.
- Clock challenge: L20 auction-inclusive session.
- Comparisons match only immutable `sequence_id` identities and never select a
  favorable view, year, or definition.
- Every role must pass all applicable support, nondegeneracy, shape, definition,
  clock, and external-geometry gates. A failed conditional role is not replaced
  by an unconditional proxy.

## Generic temporal geometry

For every role, construct endpoint rates for its already frozen generic
controls on exactly the same event days used by the target. External distinctness
requires all absolute pairwise Spearman correlations to remain below 0.85 and
rank-regression adjusted R2 to remain below 0.70 globally and 0.85 in both
fixed temporal blocks. Deleting a control is prohibited.

This separates event-role dynamics from ordinary changes in daily path,
crossing time, volatility, VWAP behavior, and volume distribution. It does not
turn a distinct coordinate into a mechanism.

## Common direction and compression

A role may receive a `COMMON_DIRECTION_PASS` annotation only when block A and B
endpoint-rate medians share one nonzero sign, both deterministic 95% bootstrap
median intervals exclude zero, both block nonzero-sign fractions are at least
0.60 in that direction, and at least five of six annual medians share the sign.
The direction is reported algebraically, never as favorable.

After representation gates, pairwise residual endpoint-rate correlations are
reported for the seven roles after their fixed control-rate regressions. A
pair may be compressed only at absolute residual Spearman at least 0.70
globally and at least 0.60 with the same sign in both blocks, with at least 50
matched trajectories globally and 20 per block. Lower associations are
descriptive and cannot create a latent score. No PCA, factor rotation, clustering
search, composite score, or threshold optimization is allowed.

## Falsifiers and no-rescue rules

Fail or mark a role not estimable when any frozen role-specific support,
nondegeneracy, shape, definition, clock, geometry, or scalar gate fails. Do not:

- lower a count floor after reveal;
- choose a favorable L10/L20/L40 definition, clock, view, year, or block;
- replace actual event-day gaps with compressed event order;
- interpolate non-crossing days or missing conditional reacquisitions;
- flip a role sign to manufacture common direction;
- remove generic controls;
- revive compressed same-session roles;
- call VWAP/activity OHLCV evidence order flow, demand, absorption, or supply;
- estimate return, payoff, habitat, entry, execution, or strategy usefulness.

## Possible conclusions

- `REPRESENTATION_PASS_COMMON_DIRECTION`: stable temporal coordinate plus a
  portable algebraic direction; still not usefulness.
- `REPRESENTATION_PASS_NO_COMMON_DIRECTION`: stable temporal coordinate without
  a recurring direction.
- `REPRESENTATION_FAIL`: exact temporal construction is not defensible.
- `NOT_ESTIMABLE_SUPPORT`: the role lacks its frozen repeated-event support.

Even a pass does not authorize a breakout or failed-breakout archetype. A later
nonoverlapping state-response and then separately frozen outcome/usefulness
study would still be required.
