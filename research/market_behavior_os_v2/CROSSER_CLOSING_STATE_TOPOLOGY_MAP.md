# Objective-crosser closing-state response topology map

Frozen after MKT-FORMDEPTH-PROP-001 and before constructing any closing-arm future
response. The question is whether formation-depth downside among objective
crossers is confined to same-day closing rejection or also survives among
crossings that close accepted above the crossed L20 level.

## Exact membership

Start from the exact `cross20` security arm that carries the accepted localized
adverse-path topology. Partition it using the same t action coordinate and the
same strictly prior L20 mapped-high level:

- `ACCEPTED`: coordinate close strictly above the crossed level;
- `REJECTED`: coordinate close strictly below the crossed level;
- `EQUAL`: coordinate close exactly equal to the crossed level.

The three arms are disjoint and must exhaust every crossing anchor and every
complete-response crossing security. Equality is neutral, retained in the count
and conservation audit, and never reassigned to the favorable arm. It is too
sparse for economic estimation and cannot rescue either primary arm.

Membership is fixed at t. Future prices, status, membership, survival, or
reacquisition cannot redefine an arm. The exact crossing and broad response
domains remain bound by their immutable hashes.

## Response and controls

Use the identical action-coordinate complete-five-session cohort and h=1/3/5
terminal/adverse security responses. Each accepted/rejected/equal arm retains
count, deterministic sum, and equal-weight mean.

Adverse h=3 is primary for accepted and rejected arms. Adverse h=1/h=5 are
mandatory neighbors. Terminal mean is diagnostic-only and cannot promote a
closing-state topology. This experiment does not scan secondary quantiles,
lookbacks, thresholds, or response horizons.

All economic estimates use the same five fixed controls: causal discovery
breadth, causal realized volatility, central direction, median open-close return,
and median intraday range. The joint information clock is 15:30 and response
begins t+1. Controls cannot be backdated into an entry signal.

## Fixed channels and gates

Estimate separately:

1. `ACCEPTED_CROSSER_DOWNSIDE`;
2. `REJECTED_CROSSER_DOWNSIDE`;
3. paired `REJECTED_MINUS_ACCEPTED` on the same date.

Each primary arm passes only with the same PROP-001 gates: median h=3 PIT partial
rho <=-0.10, at least six negative cells, both block medians <=-0.05, every
2020--2023 year and leave-one-year-out negative, h=1/h=5 negative, at least two
of three h=3 and four of five h=5 phases negative, and controlled PIT-tail
residual gap <=-0.0025.

The paired rejected-minus-accepted localization contrast passes at median h=3
partial rho <=-0.05, at least six negative cells, both block medians negative,
h=1/h=5 nonpositive, and controlled tail residual gap <=-0.0010.

Classifications are exhaustive and ordered:

- both arms pass: `ACCEPTED_AND_REJECTED_CROSSER_DOWNSIDE`;
- rejected and paired pass while accepted fails:
  `CLOSING_REJECTION_LOCALIZED_DOWNSIDE`;
- accepted passes while rejected fails: `CLOSING_ACCEPTANCE_DOWNSIDE_ONLY`;
- rejected passes but paired fails:
  `REJECTED_CHANNEL_WITHOUT_CLOSING_LOCALIZATION`;
- neither arm passes: `CROSSER_DOWNSIDE_NOT_CLOSING_STATE_RESOLVED`.

If both arms pass, relative severity cannot erase accepted-arm risk. Equality is
always descriptive. Terminal diagnostics cannot rescue a downside failure.

Passing is membership-resolved market association, not causal proof, terminal
reversal, a trigger, an entry predictor, a habitat, or a strategy rule. V1 remains
closed. Strategy outcomes, post-2023 data, and CY-011 are prohibited.
