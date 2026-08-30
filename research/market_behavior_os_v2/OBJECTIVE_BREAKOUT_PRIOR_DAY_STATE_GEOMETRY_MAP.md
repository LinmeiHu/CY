# Objective breakout prior-day market-state geometry map

Frozen before the prior-state join, role/date aggregation, or any association
estimate is constructed.

## Question and boundary

Do accepted market-state primitives known at the strictly prior close condition
the next session's strategy-independent objective prior-high post-cross paths?

This is a cross-scale temporal behavior study:

`PRIOR-CLOSE MARKET STATE -> NEXT-SESSION OBJECTIVE CROSSING PATH`

It is not a trading rule, payoff study, CHINEXT study, causal claim, or proof of
strategy habitat. The response is a completed same-session post-cross
observation. It may be analyzed only after that response's defining bar; it is
never an entry predictor at the crossing timestamp in this experiment.

## Frozen state primitives

Only representations already accepted before this map may enter:

1. `A`: 60-session index log direction from MKT-TRND-001.
2. `B1`: 60-session net new-high/new-low participation from MKT-BRTH-002.
3. `B2`: top-10 positive-return leadership concentration from MKT-BRTH-002.

MKT-TRND-001 established representation stability only, not usefulness. Trend
quality, age, transition, strength, and alignment are prohibited. Every failed
breadth role is prohibited. A, B1, and B2 stay separate; the fixed joint model
tests incremental state geometry, not a Trend x Breadth rule or synergy.

## Prior-day PIT contract

- For event date `t`, use the immediately preceding governed market trading
  date common to the accepted trend and breadth panels.
- Every state row must have `available_at <= prior_date 15:00 Asia/Shanghai`,
  strictly earlier than event date `t`.
- Breadth uses the event's exact governed `market_view` and `ALL_STATUS`
  denominator. No view may be substituted.
- Direction is evaluated separately for all six frozen broad indices. The six
  estimates are portability replications, not six independent copies pooled to
  inflate sample size and not an ex-post index mapping.
- Event responses use primary L20 continuous MKT-BREAKOUT-001 roles only.
- No raw minute row is reread. No future session, return, payoff, strategy field,
  post-2023 row, or CY-011 may enter.

## Three state coordinate systems

Every edge must survive all three already-constructed coordinate systems:

| Coordinate | Direction | Discovery | Concentration |
|---|---|---|---|
| absolute | `direction_return_60` | `breadth_net_new_high_low60` | `leadership_positive_mass_top10` |
| causal PIT | 3-year percentile | 3-year percentile | 3-year percentile |
| contemporaneous relative | six-index rank percentile | four-view rank percentile | four-view rank percentile |

Absolute coordinates preserve cross-year semantic units. PIT coordinates use
strictly prior history already embedded in the frozen panels. Relative ranks
are same-date cross-sectional context and are never substituted for absolute
state. Missing/nondegenerate coordinates fail closed.

## Response unit and generic controls

The statistical unit is one `event_date x market_view x role` cell. Aggregate
all qualifying security events in that cell by the median. Record security-
event count, physical-session count, response median, and medians of the role's
unchanged generic controls. This prevents several securities exposed to the
same market state from being treated as independent state observations.

The seven response roles and their role-specific controls are inherited exactly
from MKT-BREAKOUT-001:

- 30-bar continuation;
- rejection depth;
- below-level dwell;
- loss-episode count;
- conditional reacquisition bars;
- cumulative-VWAP acceptance;
- post-cross activity.

The three compressed same-session roles remain prohibited. No composite
acceptance score is allowed.

## Primitive-edge estimands

For each response role, coordinate system, fixed temporal block, index, and
market view, estimate rank-partial Spearman association:

- `A | generic controls + B1 + B2`;
- `B1 | generic controls + A + B2`;
- `B2 | generic controls + A + B1`.

An edge passes only if raw, PIT, and relative versions all meet unchanged
support, effect, sign-replication, and year-portability gates. A favorable
index, view, role, coordinate, block, or year cannot rescue another. All 21
role/primitive edges remain in the ledger.

## Fixed joint increment

For each role, index, coordinate, and block, compare rank-regression adjusted R2:

- `BASELINE`: fixed generic controls;
- `A+B1+B2`: fixed controls plus all three state primitives.

The joint increment is descriptive evidence that the three accepted state
coordinates jointly condition the response beyond generic path geometry. It is
not an interaction term, synergy, gate, classifier, score, forecast, or strategy
habitat. No thresholded state bins are tested.

## Falsifiers

Fail an edge or joint claim when any frozen join, PIT, coverage, nondegeneracy,
block, coordinate, sign, year, scalar, determinism, or resource gate fails. Do
not:

- use same-day closing state as if known before the event;
- choose one index as the preferred market proxy after reveal;
- pool security rows as independent market-state samples;
- switch breadth denominator or view;
- drop another state primitive from a partial edge;
- remove a generic control;
- tune an effect threshold or state boundary;
- select a favorable role or coordinate;
- infer order flow, participant identity, payoff, execution, or strategy value.

## Possible conclusions

- `PRIMITIVE_EDGE_PASS`: one prior-day primitive conditions one next-session
  path role across every frozen coordinate and replication gate.
- `JOINT_INCREMENT_PASS`: A+B1+B2 add fixed rank geometry beyond controls; this
  is not synergy or a rule.
- `NO_PORTABLE_STATE_CONDITIONING`: no edge/joint claim passes. Stable breakout
  representations remain descriptive and the branch is deprioritized.

Any passing relation is consumed exploratory pre-2024 behavior evidence. A
later untouched temporal response and then separately preregistered payoff/
execution study would still be required before an archetype can activate.
