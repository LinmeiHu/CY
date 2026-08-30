# Market hypothesis ledger

## MKT-H-001 — independent multidimensional trend state

- Status: `PARTIAL_REPRESENTATION_SUPPORT`.
- Claim tested: direction, strength, quality, age, alignment, and transition can
  each be frozen as stable strategy-independent market roles.
- Experiment: MKT-TRND-001, six registered indices, 2010-06-01..2023-12-29,
  no outcomes.
- Result: direction passes. Quality, age, and transition fail fixed
  neighboring-horizon stability. Strength and alignment pass neighbor stability
  but fail exact coverage after 21 OHLC rows are quarantined.
- Scope: one descriptor role is frozen; no predictive or habitat claim exists.
- Next attack: diversify into breadth before considering a fresh, structurally
  different trend representation or independent source.

## MKT-H-002 — independent breadth state

- Status: `PARTIAL_REPRESENTATION_SUPPORT`.
- Claim: participation level, depth, acceleration, divergence, diffusion, and
  leadership concentration can be represented on market dates without strategy
  selection and without collapsing to accepted trend direction.
- Result: MKT-BRTH-002 freezes net new-high/new-low discovery and leadership
  concentration across four governed views and two denominators. Current
  participation, depth, momentum, acceleration, industry diffusion, divergence,
  and transition definitions fail fixed neighboring stability. These are exact
  representation failures, not family rejection.
- Boundary: no forecast, usefulness, strategy, or habitat claim.

## MKT-H-003 — correlation/liquidity panic state

- Status: `PARTIAL_REPRESENTATION_SUPPORT_PANIC_UNTESTED`.
- Claim: synchronized correlation and liquidity shock form an observable market
  process distinct from ordinary volatility expansion.
- Result: MKT-CLQ-001 freezes co-movement, directional synchronization,
  liquidity activity, turnover level, and amount concentration. Participation
  and industry diffusion are redundant with activity; fixed liquidity change is
  horizon-unstable.
- Boundary: no correlation x liquidity interaction, shock, panic, recovery,
  impairment, reversal, or strategy-return claim was tested.

## MKT-H-004 — trend/breadth state geometry

- Status: `SUPPORTED_REPRESENTATION_GEOMETRY`.
- Result: all three nonredundancy gates pass across 24 index/view pairs. Median
  direction/discovery rho is 0.489; median direction/concentration rho is -0.360;
  median discovery/concentration partial rank after direction is -0.490.
- Boundary: contemporaneous geometry only. The zero discovery boundary is
  occupancy-imbalanced and not a validated habitat boundary.

## MKT-H-005 — leader failure representation

- Status: `LEVEL_IMBALANCE_SUPPORTED_TRANSITIONS_NOT_FROZEN`.
- Claim: concentration decay and discovery deterioration can be represented as
  distinct contemporaneous processes rather than inferred from concentration
  level.
- Boundary: representation quality precedes any future path, short, reversal,
  breakout-veto, or strategy association.
- Result: the level imbalance passes. Concentration decay and discovery
  deterioration fail neighboring-definition stability, so no joint leader-
  failure transition is formed.

## MKT-H-006 — multidimensional volatility state

- Status: `PARTIAL_REPRESENTATION_SUPPORT`.
- Result: realized volatility, intraday range, volatility-mass concentration,
  and volatility change freeze. Downside volatility and dispersion are stable
  but redundant; term structure and downside-mass share fail.
- Boundary: no contraction/expansion usefulness, panic, habitat, or strategy
  claim exists.

## MKT-H-007 — market-wide five-day intraday state

- Status: `LEVEL_REPRESENTATIONS_SUPPORTED_EXACT_TRAJECTORIES_FAIL`.
- Result: AUDIT-MKT-MIN-001 passes exact PIT/session/reconciliation/descriptor
  readiness on 240 trajectories and 1,200 sessions across 2018-2023/four views.
- Result: required scale freezes 32 same-session levels; selloff-duration and
  auction-gap levels fail. All exact five-day OLS slopes fail fixed 3-day/
  endpoint shape-neighbor stability, so no five-day trajectory role freezes.
- Boundary: representation support is not a supply/demand mechanism, usefulness,
  habitat, or signal. The broader trajectory family remains open.

## HAB-H-001 — CHINEXT V1 direction/discovery habitat association

- Status: `EXPLORATORY_ASSOCIATION_PARTIAL_NO_RULE`.
- Claim: frozen market direction and new-high/new-low discovery may describe
  variation in the observed V1 opportunity process or completed-cycle payoff.
- Experiment: HAB-CHX-001, 2018-07-03..2023-12-29, two mechanisms only.
- Result: direction and discovery each associate with evaluated, candidate, and
  selected daily counts. Partial A/B evidence survives for evaluated/candidate
  counts; the fixed A+B interaction passes only those two formation endpoints.
- Result: event/candidate selected rates fall as opportunity density rises,
  consistent with finite vacancies rather than market rejection. Direction
  associates with more-negative MAE. Discovery associates with MFE>=20%
  opportunity, but not incrementally after direction under the strict gate;
  within-opportunity conversion fails.
- Rejections: no absolute primary gate passes for completed-cycle return,
  winner20/50, false breakout, severe/extreme loss, or conversion20. No A+B
  payoff synergy exists.
- Boundary: all outcomes are consumed; this is exploratory association and can
  neither establish causality nor authorize a strategy rule or archetype.

## MKT-H-008 — correlation/liquidity shock-and-relief process

- Status: `CONTINUOUS_SCORES_SUPPORTED_EXACT_EPISODE_FAIL`.
- Result: direction-neutral synchronization pressure and joint synchronization/
  activity stress score pass fixed aggregation/activity-horizon, denominator,
  coverage, year, and volatility-redundancy gates.
- Result: the exact 0.90 onset / 0.50 reset state machine fails. It produces
  zero or one onset per group, no activity-dry-up observations, zero strict-
  threshold onset match, and unstable/undefined stress, relief, dwell, and
  impairment neighbors.
- Boundary: no onset, dwell, relief, impairment, panic, price recovery,
  forecast, habitat, or strategy claim freezes. Do not lower the threshold or
  replace the primary with the permissive neighbor. The broader process family
  remains open under structurally different representations.

## MKT-H-009 — directional-tail and risk-appetite state

- Status: `REPRESENTATION_SUPPORTED_THREE_NONREDUNDANT_ROLES`.
- Claim: same-session positive/negative participation, signed tail depth,
  limit-relative extreme participation, directional industry diffusion, tail
  concentration, and asymmetry can be represented independently of strategy
  outcomes.
- Contract: MKT-RISK-001 uses actual registered date-effective limit geometry,
  fixed symmetric thresholds/quantiles, causal PIT and governed-view relative
  coordinates, and frozen breadth/volatility redundancy controls.
- Boundary: no panic, forecast, habitat, interaction, or strategy claim; no
  MKT-SHOCK-001 score enters construction.
- Result: all 11 exact primaries pass coverage, fixed neighbors, denominator,
  year, PIT, and relative-coordinate gates. Central direction absorbs ordinary
  participation, tail depth, concentration, and industry diffusion at the 0.85
  edge. Upside and downside extreme participation remain separate from central
  direction and from each other. Tail balance is stable but is the deterministic
  difference of those two primitives, so it is not a fourth mechanism.
- External result: no accepted or stable role reaches 0.85 median absolute
  Spearman with frozen breadth discovery/leadership or volatility controls; the
  largest value is 0.664.

## MKT-H-010 — directional synchronization/stress process

- Status: `EXACT_CONTINUOUS_AND_PROCESS_REPRESENTATIONS_FAIL`.
- Claim: direction-neutral synchronization plus separate downside/upside extreme
  breadth can form stable recurring elevated processes.
- Result: both sides pass coverage, denominator, year, and single-input/
  volatility nonredundancy. Geometric and 50/90-definition neighbors are strong,
  but the frozen arithmetic neighbor is only 0.691 downside and 0.646 upside,
  below 0.70. Neither continuous primary freezes.
- Result: primary 0.80/0.50 episodes are also sparse. Downside produces 1-4
  onsets per group in one year; upside 0-8 across zero to two years. Strict
  matching, state overlap, dwell/relief, and high-activity support fail.
- Boundary: no continuous directional-synchronization role, onset, dwell,
  relief, high-activity modifier, panic, speculation, forecast, or strategy
  claim. Do not replace weakest-link with the geometric neighbor or lower event
  thresholds. The broader directional-process family remains open.

## MKT-H-011 — non-slope five-day market intraday paths

- Status: `ONE_OF_THIRTY_SIX_REPRESENTATIONS_SUPPORTED`.
- Claim: ordinal progression, signed reversal, and curvature can provide stable
  five-day representations not reducible to exact OLS/endpoint clones.
- Contract: 12 preregistered descriptors x three fixed operators from Day -5
  through Day -1; median primary with p40/p60 aggregation neighbors; absolute,
  causal PIT, and governed-view relative coordinates; no raw-minute rescan,
  outcome, strategy field, or favorable operator substitution.
- Result: only `minute_realized_volatility__ordinal_progression` passes. Its
  weakest definition neighbor is 0.711 and it is not same-session-level
  redundant (median absolute rho 0.246). All other progression roles and all
  reversal/curvature roles fail the fixed representation gate.
- Boundary: the survivor is not yet established as contraction, expansion,
  supply/demand, a transition mechanism, habitat, forecast, or trading signal.
  The broader failed descriptor families remain open only under structurally
  different representations, not favorable window/operator selection.

## MKT-H-012 — external geometry of the minute-volatility path

- Status: `DISTINCT_CONTEMPORANEOUS_PATH_COORDINATE`.
- Claim: the accepted minute-realized-volatility ordinal progression may add a
  state coordinate beyond its Day -1 level and accepted daily volatility level,
  range, concentration, and change.
- Result: all five controls pass the fixed 0.85 pairwise-distinctness gate in
  every available absolute, causal-PIT, and relative view. The largest median
  absolute association is 0.249. Joint raw-rank reconstruction by all five
  controls is 0.195 median adjusted R2 and 0.223 maximum, passing 0.70/0.85.
- Boundary: distinctness does not establish contraction/expansion, recurrence,
  transition stability, prediction, strategy usefulness, habitat, or causality.
  Those claims require separate frozen tests.

## MKT-H-013 — exact minute-volatility ordinal states

- Status: `EXACT_DISCRETE_STATE_ARCHITECTURE_FAIL`.
- Result: primary rising/falling/flat states recur in every required group/year
  and completed-run/dwell gates pass. However all-pairs/rank-time neighbor state
  agreement is only kappa 0.425/0.275 and macro-Jaccard 0.423/0.305; transition
  total variation is 0.469/0.611. All fail their fixed gates.
- Context limitation: the daily realized-volatility expanding percentile has no
  2019 coverage, only 107 observations/group in 2020, and sparse 20/80 cells in
  later years, so the nine-cell path-by-level geometry also fails.
- Boundary: the continuous path representation and its external distinctness
  remain valid. No exact sign state, dwell process, transition process,
  contraction/expansion label, usefulness, habitat, or strategy rule freezes.

## MKT-H-014 — continuous path future-volatility response

- Status: `NO_REPLICATING_INCREMENTAL_RESPONSE`.
- Result: the primary h=5 partial-rank association after five fixed controls is
  -0.017 in 2019-2021 discovery and -0.015 in untouched 2022-2023 confirmation,
  versus the 0.10 gate. Fixed phase-zero non-overlap is -0.005/-0.019 versus
  0.08. Primary group sign support is 5/8 and 6/8.
- Neighbors: h=1 changes sign (+0.033 to -0.092); h=3 weakens (+0.060 to
  +0.010). Raw associations are negative but are absorbed by current-volatility
  controls and have no incremental claim.
- Boundary: no volatility continuation/reversal mechanism, forecast, market-
  return meaning, strategy usefulness, or archetype. The continuous coordinate
  remains descriptive and exact states remain rejected.

## MKT-H-015 — industry leadership, rotation, and relative-strength state

- Status: `EIGHT_REPRESENTATIONS_SUPPORTED_SEVEN_MINIMAL`.
- Contract: MKT-INDRS-001 uses the exact action-aware 120-session CY-006 core,
  causal industry labels, five-member groups, 80% mapping and ten-industry
  gates, equal-industry aggregation, exact other-member medians, fixed
  neighbors, absolute/PIT/relative coordinates, and serial execution. It reads
  neither the failed MA20 industry fields nor outcomes, strategy fields, or
  CY-011.
- Result: equal-industry positive participation, equal-industry return depth,
  industry return dispersion, winner-industry diffusion, rank rotation, and
  all three leave-one-out stock/industry residual roles pass. Return depth is
  redundant with positive participation at absolute Spearman 0.980, leaving
  seven minimal coordinates.
- Rejections: industry-vs-market depth fails its neighbor gate at 0.660;
  positive-mass leadership concentration misses raw coverage at 0.945 because
  the positive-mass denominator is sometimes zero; top-set persistence fails
  neighbor stability at 0.540 and denominator stability at 0.895. Definitions,
  thresholds, views, and favorable subsets do not rescue them.
- Audit: all valid view/date rows have 100% causal industry mapping, at least 37
  included industries, and exact leave-one-out reconstruction on 1,988 sampled
  rows with zero difference. Two full serial runs are byte-identical.
- Boundary: these are same-session state representations. No future leadership
  persistence, rotation timing, stock-selection alpha, market-return meaning,
  habitat fitness, strategy usefulness, or industry-rotation archetype is
  established. Broader failed families remain open only under structurally
  different definitions.

## MKT-H-016 — external engine geometry of industry/relative-strength roles

- Status: `FIVE_DISTINCT_ENGINE_COORDINATES`.
- Result: equal-industry positive participation is a broad central-direction
  manifestation: median raw/PIT absolute Spearman with signed limit utilization
  is 0.978/0.976, and joint adjusted rank R2 is 0.958/0.952. It is removed from
  the direct engine panel but remains valid participation evidence.
- Result: leave-one-out stock/industry residual dispersion is not pairwise over
  the 0.85 edge, but its fixed co-movement/volatility controls jointly explain
  0.773 median adjusted rank R2 in PIT space and 0.757 in relative-to-ALL_A
  space. It is jointly reconstructable, not a separate mechanism.
- Result: industry return dispersion, winner-industry diffusion, rank rotation,
  residual tail balance, and residual positive-mass concentration pass every
  raw/PIT/relative pairwise and joint gate. Their largest pairwise median
  absolute rhos are 0.568, 0.193, 0.203, 0.485, and 0.345 respectively.
- Boundary: contemporaneous distinctness establishes no future transition,
  persistence, market return, selection alpha, habitat, timing, causality, or
  strategy. The five roles require temporal-process evidence before any
  relative-strength or industry-rotation archetype decision.
