# Formation-depth downside propagation topology map

Frozen after MKT-FORMDEPTH-ATTR-001 and before constructing any membership-
resolved future response. The question is whether the attributed aggregate
formation-depth tail-risk association is localized in the securities that formed
the same-day objective crossings or also propagates to the exact noncrossing
market cohort.

## Fixed state and membership

- State: exact `breakout_formation_depth20` and its existing causal PIT-3y
  percentile.
- Crossing membership: the exact security-level `cross20` flag already used to
  construct that state: mapped current high strictly above the strictly prior L20
  mapped-high level.
- Noncrossing membership: every other security in the exact date/view/denominator
  L20 anchor cohort.
- Membership is fixed at t. Future prices, status, membership, and survival cannot
  redefine either arm.

The crossing and noncrossing arms must be disjoint and exhaust both the anchor
cohort and the original complete-five-session response cohort. The broad response
must reproduce MKT-BREAKOUT-ECON-DATA-001 before an arm is interpreted.

## Fixed response

Use the identical action-coordinate fixed-five-session cohort and h=1/3/5
security responses from the accepted economic-response contract. For each arm and
horizon report only:

- equal-weight mean terminal security log return;
- equal-weight mean security adverse log excursion;
- security count and deterministic sum used by the mean.

Adverse h=3 is primary. Adverse h=1/h=5 are mandatory neighbors. Terminal means
are diagnostic only: they may distinguish adverse path from terminal reversal but
cannot independently promote a topology or strategy. No secondary quantile,
alternate lookback, crossing threshold, or future membership rule is allowed.

## Economic channels

After the response domain passes, estimate three predeclared series separately:

1. `CROSSER_DOWNSIDE`: formation depth versus the crossing arm's future adverse
   mean;
2. `NONCROSSER_DOWNSIDE`: formation depth versus the noncrossing arm's future
   adverse mean;
3. `CROSSER_MINUS_NONCROSSER`: crossing adverse mean minus noncrossing adverse
   mean on the same date.

The noncrossing arm is the propagation test. The crossing arm is the localized
channel test. The paired difference is required before the word *localized* may
be used. The two arms are not pooled and their overlapping dates are paired, not
treated as independent observations.

## Fixed controls and clocks

Every economic estimate uses the five MKT-FORMDEPTH-ATTR-001 controls without
selection: causal discovery breadth, causal realized volatility, accepted central
direction, market median open-close return, and market median intraday range. The
joint information clock remains 15:30 after the completed event session. Future
response begins t+1. This experiment is explanatory and cannot backdate the
minute-derived controls into an entry predictor.

Use the existing PIT <=0.20 and >=0.80 state tails, the same 2018--2020 and
2021--2023 blocks, 2020--2023 causal-PIT years and leave-one-year-out challenges,
and the same h=3/h=5 nonoverlap phases. No tail, year, horizon, control, or arm may
be selected after response values are seen.

## Channel gates and classification

Each crossing or noncrossing channel passes only if its adverse response has:

- h=3 median PIT partial rho <=-0.10 across the eight cells;
- the negative sign in at least six cells;
- both fixed block medians <=-0.05;
- negative medians in all four PIT-supported years and all four leave-one-year-
  out estimates;
- negative h=1 and h=5 medians;
- negative sign in at least two of three h=3 and four of five h=5 phases;
- median controlled PIT high-minus-low residual gap <=-0.0025.

The paired crossing-minus-noncrossing channel is a direct localization contrast
and uses deliberately smaller but fixed boundaries: h=3 median partial rho
<=-0.05, at least six negative cells, both block medians negative, h=1/h=5 not
positive, and median controlled PIT-tail residual gap <=-0.0010.

Classifications are exhaustive:

- both arms pass: `CROSSER_AND_NONCROSSER_DOWNSIDE_PROPAGATION`;
- crossing and paired-localization pass while noncrossing fails:
  `LOCALIZED_CROSSER_DOWNSIDE_TOPOLOGY`;
- noncrossing passes while crossing fails:
  `NONCROSSER_DOWNSIDE_PROPAGATION_ONLY`;
- crossing passes but paired localization fails:
  `CROSSER_CHANNEL_WITHOUT_LOCALIZATION`;
- neither arm passes: `AGGREGATE_RESPONSE_NOT_MEMBERSHIP_RESOLVED`.

If both arms pass but the paired contrast also passes, the result is still *both
arms*: relative severity does not erase broad propagation. Terminal-return
diagnostics cannot rescue any failed downside classification.

Passing remains an association topology, not causality, a tradeable portfolio,
an entry predictor, a habitat, a veto, or a strategy. HAB-CHX-FORMDEPTH-001 remains
closed. Post-2023 data, strategy outcomes, and CY-011 remain prohibited.
