# Continuous volatility transition and habitat map

Frozen before MKT-VOL-TRANS-001 constructs a future volatility state. This is
a strategy-independent test of continuous contraction/expansion dynamics. It
does not discretize a trading regime or read market returns.

## Defensible inputs

MKT-VOL-001 freezes four daily-volatility roles: realized-volatility level,
intraday-range level, volatility concentration, and five-session change in
realized-volatility level. MKT-TRND-001 freezes trend direction representation
stability only, and MKT-BRTH-002 freezes new-high/new-low discovery breadth.
None has established strategy usefulness.

This study uses the volatility-change coordinate as the transition variable.
Realized-volatility level, range, and concentration are fixed current controls.
Direction and discovery are tested only as state modifiers after strictly
causal PIT normalization; they are not combined into a rule.

## Nonoverlapping transition response

Current `realized_volatility_change5` compares RV20 at t-5 and t. Its complete
source span is t-25 through t. The response is the same coordinate at t+25,
which compares RV20 at t+20 and t+25 and has source span t through t+25. The
two spans share only the completed endpoint t and no return interval.

The 25-session shift follows mechanically from the 20-session level window plus
the five-session transition window. No neighboring response horizon is searched.
Every twenty-fifth valid row is the fixed phase diagnostic.

## Baseline continuous transition edge

Current volatility change predicts its t+25 value after current realized-
volatility level, intraday range, and volatility concentration. The sign is not
assumed: positive would indicate recurrence and negative reversal. Discovery
block A fixes the observed sign; reused block B, PIT, relative coordinates, and
phase estimates must replicate it.

Raw/PIT estimates use all eight view/denominator groups. Relative-to-ALL_A
excludes ALL_A and pools by denominator; governed-view ranks include all four
views. The baseline edge may pass or fail independently of habitat modifiers.

## Fixed habitat modifiers

The modifier estimand is `rho_high - rho_low`, where each rho is the baseline
partial Spearman estimated within a causal-PIT habitat.

- Direction modifier: for each of six frozen indices and each volatility
  view/denominator group, split dates by that index's direction PIT coordinate.
  Aggregate the eight group differences within index, then across six indices.
- Discovery modifier: within each of eight volatility view/denominator groups,
  split by the matching view/denominator discovery-breadth PIT coordinate.

The primary broad split is PIT <=0.50 versus >0.50. The fixed shape neighbor is
PIT <=0.40 versus >=0.60. Raw transition/control coordinates are primary and
their causal-PIT coordinates are required replication. No raw zero boundary,
optimized threshold, joint Direction x Discovery cell, or favorable index/view
selection is allowed.

## Time and contamination boundary

Blocks are 2019-2021 and 2022-2023, requiring predictor and response inside the
same block. Both periods are reused elsewhere in the program, so evidence is
`REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION`. Passing still
requires independent future time. Post-2023 data and locked holdouts remain
unopened.

## Gates

Baseline edge:

- raw median absolute partial rho at least 0.10 in both blocks;
- the block-A sign replicated in block B and at least six of eight groups;
- block-B magnitude at least half block A;
- phase median absolute rho at least 0.08 with the same sign;
- PIT median absolute rho at least 0.08 with the same sign and six groups;
- both relative medians at least 0.05 with the same sign and both denominators;
- 150 raw/PIT and 450/600 pooled-relative minimum support.

Each habitat modifier independently requires:

- primary raw median absolute high-minus-low difference at least 0.10 in both
  blocks, same sign, and block-B magnitude at least half block A;
- sign support in at least four of six direction indices or six of eight
  discovery groups;
- primary PIT modifier absolute difference at least 0.08 with the raw sign;
- 40/60 neighbor raw and PIT absolute difference at least 0.08 with the primary
  sign in both blocks;
- minimum cell support 150 for the primary halves and 120 for neighbor tails.

Baseline, direction modification, and discovery modification stand or fail
separately. One cannot rescue another. No sign, coordinate, block, phase,
threshold, index, view, denominator, control deletion, or favorable subset can
replace a failed exact claim.

## Claim boundary

Passing establishes a reused-time continuous volatility state dynamic or
modifier only. It does not establish future market return, volatility trading
profit, timing, habitat fitness for a strategy, causality, execution, capacity,
or a rule. Strategy outcomes, future price returns, failed volatility/trend/
breadth roles, post-2023 data, and CY-011 are prohibited.
