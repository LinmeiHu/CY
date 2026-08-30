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
