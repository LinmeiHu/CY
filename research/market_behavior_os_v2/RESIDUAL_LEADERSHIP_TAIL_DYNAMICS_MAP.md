# Residual leadership tail dynamics map

Frozen before MKT-INDRS-TAIL-DYN-001 shifts any future state. This is an
outcome-blind temporal study of two accepted direct Market State Engine
coordinates. It is not a stock-return, selection, habitat, or strategy test.

## Question and economic separation

MKT-INDRS-GEO-002 leaves two distinct within-industry residual shapes:

- `stock_industry_rs_tail_balance20`: p90 plus p10 of each stock's 20-session
  return minus the exact leave-one-out industry median. It measures whether the
  leader tail outweighs the laggard tail after industry context is removed.
- `stock_industry_rs_concentration20`: the top-decile share of positive
  residual-return mass. It measures whether positive stock leadership within
  industries is concentrated in relatively few names.

Contemporaneous distinctness does not imply temporal persistence or coupling.
This experiment asks whether either shape recurs after its 20-session return
window has rolled completely forward, and whether one current shape precedes
the other after controlling for the response's current state.

## Fixed nonoverlapping response horizon

All responses are the same coordinate exactly 20 exchange sessions later. A
current residual is based on the t-20 to t return interval; its t+20 response is
based on t to t+20. The intervals share only the completed close at t and no
return interval. The horizon is fixed by the source representation's economic
window, not selected from alternatives. Every-twentieth valid predictor rows
form the phase diagnostic.

## Fixed temporal graph

1. `tail_balance_nonoverlap_persistence`: current residual tail balance ->
   future residual tail balance.
2. `concentration_nonoverlap_persistence`: current residual concentration ->
   future residual concentration.
3. `concentration_to_future_tail_balance`: current residual concentration ->
   future residual tail balance, controlling current residual tail balance.
4. `tail_balance_to_future_concentration`: current residual tail balance ->
   future residual concentration, controlling current residual concentration.

All signs are fixed positive. A self-edge establishes only its own recurring
state process. A bidirectional tail/concentration process requires both cross-
edges; neither self-edge nor one favorable cross-edge rescues the other.

## Fixed controls

Tail-balance responses retain the exact broad signed-risk alternatives from
MKT-INDRS-GEO-002: central signed direction, upside-extreme participation, and
downside-extreme participation. Concentration responses retain broad leadership
concentration, amount concentration, and volatility concentration. Cross-edges
also control the response role's current coordinate. No stepwise selection,
control deletion, or common master pool is allowed.

Partial Spearman is estimated separately in raw, causal trailing-three-year
PIT-percentile, same-date view-minus-ALL_A, and same-date governed-view rank
coordinates. Raw/PIT use all eight view/denominator groups. Relative estimates
pool by denominator, excluding ALL_A for view-minus-ALL_A.

## Time and contamination boundary

The fixed blocks are 2019-2021 and 2022-2023, requiring predictor and response
inside the same block. These pre-2024 periods have been used elsewhere in the
program, so neither is called untouched confirmation. Evidence is labeled
`REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION`; independent future
time remains required even if an edge passes. No post-2023 partition or locked
holdout is opened.

## Gates and no-rescue rule

Each edge independently requires:

- positive raw median partial rho at least 0.10 in both blocks;
- at least six of eight positive raw groups in both blocks;
- block-B raw magnitude at least half block A;
- positive every-twentieth-session raw median at least 0.08 in both blocks;
- positive PIT median at least 0.08 and six of eight positive groups;
- both relative-coordinate medians at least 0.05 with both denominator groups
  positive;
- unchanged support of 150 per raw/PIT group and 450/600 per pooled relative
  group.

No response, edge, coordinate, block, phase, view, denominator, control
deletion, or favorable subset can replace a failed exact edge. Failure rejects
only that temporal representation, not the stable same-session coordinate or
the broader residual-leadership family.

## Claim boundary

Passing establishes reused-time exploratory state dynamics only. It does not
establish future stock or market return, persistence of named securities,
selection alpha, timing, causality, execution, capacity, habitat fitness, or a
strategy. Market/industry/stock returns, strategy outcomes, failed roles,
failed MA industry fields, post-2023 data, and CY-011 are prohibited.
