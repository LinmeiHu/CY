# Same-session VWAP defense/recovery temporal-meaning map

Frozen before MKT-MIN-DEF-DYN-001 creates any future-state field. The purpose
is to learn whether the sole externally distinct MKT-MIN-SUPACC-001 coordinate
has repeatable state dynamics. It does not test price return or a strategy.

## Inherited minute/PIT contract

The input is the frozen MKT-MIN-SUPACC-001 panel, not raw minute data. Its source
contract defines timestamps as completed Asia/Shanghai bar ends; the grid is the
09:30 auction row plus 09:31--11:30 and 13:01--15:00 continuous bars; prices are
raw/unadjusted; volume is shares and amount is CNY; the lunch boundary, expected
grid, suspensions/missing rows, volume/amount conservation, raw-adjustment
semantics, and PIT cutoff already passed exact fail-closed gates. Session-derived
states are available only at 15:30. There is no same-bar action.

No corporate-action-adjusted cross-day price is used. The response is a future
value of a dimensionless, causal-percentile-based state, not a price comparison.
The raw-minute source, abnormal/missing bars rejected by the inherited contract,
and unregistered substitutions remain inaccessible.

## Fixed estimand

The primary predictor is
`vwap_defense_recovery__median__aligned_mean` at completed session t. The response
is the exact same coordinate at t+h, shifted within market view and denominator
along the governed exchange calendar. Predictor and response dates must both be
inside the same temporal block.

The primary horizon is the next exchange session, h=1. Natural neighboring
horizons h=3 and h=5 are fixed before estimation. They test decay/portability;
they are not alternative primaries and cannot rescue h=1.

Current-session causal-PIT controls are fixed as median open-to-close return,
downside realized volatility, and minute-volume concentration. This asks whether
defense/recovery has temporal information beyond the same daily geometry used
for external compression. No control may be deleted after results.

## Coordinates and shape challenges

The primary absolute coordinate is already a mean of four causally normalized,
sign-aligned components. Fixed h=1 challenges are:

- aligned-component median and geometric-mean aggregators;
- p40 and p60 cross-sectional definitions under aligned mean;
- relative-to-ALL_A, with each control constructed by subtracting its same-date,
  same-denominator ALL_A causal percentile;
- governed-view relative rank, using the persisted control relative ranks.

Leave-one-component-out scores are not reopened as separate temporal claims;
their representation stability already passed. A favorable component subset is
forbidden.

## Blocks, estimation, and gates

Block A is 2020-2021 and block B is 2022-2023. Both are reused exploratory time,
not untouched confirmation. The sign is learned from block A and must replicate
in block B. Partial Spearman is estimated by rank-residualizing predictor and
response on the three fixed current controls plus an intercept.

The h=1 primary requires in both blocks: at least 150 complete observations per
each of eight view/denominator groups, median absolute partial rho at least 0.10,
and at least six of eight group signs aligned with the block-A sign. Block-B
magnitude must be at least half block A.

Every fixed h=1 aggregation/cross-section challenge requires median absolute
partial rho at least 0.08 in each block, the block-A sign in both blocks, and six
of eight aligned group signs. Relative-to-ALL_A requires at least five of six
non-ALL_A view/denominator signs and median absolute rho 0.05 in both blocks.
Relative rank is pooled by denominator and requires both denominator signs and
median absolute rho 0.05 in both blocks.

Each h=3 and h=5 absolute primary requires median absolute partial rho at least
0.05, six of eight aligned signs, and the h=1 block-A sign in both blocks. All
requirements are conjunctive. No horizon, block, coordinate, view, denominator,
sign, control deletion, or favorable subset can rescue a failure.

## Claim boundary

Passing would establish only a replicating outcome-blind same-session state
dynamic. It would not establish cross-day support/resistance, participant
accumulation, causality, price-return prediction, volatility prediction, habitat
fitness, entry timing, execution, exit, capacity, or a strategy archetype.
Future price/volatility/industry/stock states, strategy fields, failed roles,
raw minutes, post-2023 data, and CY-011 are prohibited.
