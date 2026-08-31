# Formation-depth own-security versus shared-date attribution map

Frozen after MKT-FORMDEPTH-IMMED-001 and before constructing any stratum response
or estimating an own/shared association. The accepted market formation-depth
state is the equal-weight mean of each exact L20 crosser's own high overshoot.
This map asks whether future downside is associated with each security's own
overshoot, a shared same-date formation environment, or both.

## Exact predictor membership

Use the accepted action coordinate and exact `cross20` membership at completed
session t. For each crosser:

`OWN_DEPTH20_i = coordinate_high_i / resistance_high20_i - 1`.

Within each exact date/view/denominator cell, order anchor crossers by
`(OWN_DEPTH20_i, symbol)` and assign deterministic `NTILE(5)` strata. Symbol is
only an exact tie-break. All five strata are retained and reported; no stratum
may be selected after results. The five anchor strata are disjoint and exhaust
the original crossing count.

Membership and stratum are fixed using all eligible anchor crossers at t. Future
response completeness, closing state, survival, future trough, and future price
may not define or re-rank a stratum. A cell is eligible only with at least 25
anchor crossers, ensuring at least five anchors per stratum.

For stratum q define completed-session predictors:

- `OWN_STRATUM_DEPTH_q`: mean `OWN_DEPTH20_i` within q;
- `OTHER_STRATA_DEPTH_q`: mean `OWN_DEPTH20_i` in the other four strata;
- `RELATIVE_DEPTH_q`: own-stratum mean minus other-strata mean.

The five stratum counts must exhaust the exact bound crossing population, and a
deterministic symbol/own-depth ledger must prove that the same security-level
multiset enters the strata. Depth sums/counts define a new deterministic
decomposition; they are not required to be bitwise identical to the historical
unordered floating aggregate. The immutable original state remains bound by
hash and any binary aggregation difference is reported rather than hidden with a
tolerance. `OTHER_STRATA_DEPTH_q` excludes every member whose response enters
stratum q and is therefore the primary shared-date coordinate. It receives
the same causal 756-observation rolling percentile with 504 finite observations
required before a PIT value. Own-stratum depth receives an identical causal PIT
coordinate as a mandatory control. Relative depth is descriptive only.

## Exact response construction

Use the already-accepted complete-five-session action-coordinate response. Within
each fixed anchor stratum retain count, deterministic sum, and equal-weight mean
for:

- adverse log excursion at h=1,3,5;
- terminal log return at h=1,3,5 as diagnostic only.

Adverse h=3 is primary and h=1/h=5 mandatory neighbors. Response starts t+1.
Each stratum must retain at least 85% of its anchors for a complete response cell.
No missing member is replaced, and no stratum is recomputed among survivors.

## Channel A: own-security overextension

For every complete date/cell/horizon, calculate the Spearman association across
the five ordered stratum means between own-stratum depth and adverse response.
The date-level association is then summarized across dates; dates are the
effective observations. A stable negative association means progressively deeper
own overshoot is followed by progressively worse own adverse path within the same
market date.

Channel A passes only if h=3 median date association is <=-0.30, at least six of
eight cell medians are negative, both fixed block medians are <=-0.10, all
2020--2023 supported-year and leave-one-year-out medians are negative, and h=1
and h=5 medians are negative. No closing arm, stratum, date, or horizon may be
selected to rescue it.

## Channel B: shared-date formation environment

For each q separately, estimate the PIT partial-rank association of
`OTHER_STRATA_DEPTH_q` with q's adverse response. Mandatory controls are q's own
depth PIT coordinate plus the unchanged five MKT-FORMDEPTH-ATTR-001 controls:
discovery breadth, realized volatility, central direction, market open-close
return, and market intraday range.

A stratum shared channel passes only with median h=3 partial rho <=-0.10, at least
six negative cells, both blocks <=-0.05, all supported years and leave-one-year-
out estimates negative, h=1/h=5 negative, at least two of three h=3 and four of
five h=5 nonoverlap phases negative, and controlled PIT high-minus-low residual
gap <=-0.0025. All five strata are evaluated. A broad shared-date channel requires
at least four of five strata to pass; one to three passing strata remain
`SHARED_CHANNEL_NOT_BROAD` and cannot be selected as a favorable subgroup.

## Exhaustive classification

- own and at least four shared strata pass:
  `OWN_AND_BROAD_SHARED_FORMATION_DOWNSIDE`;
- own fails and at least four shared strata pass:
  `BROAD_SHARED_FORMATION_ENVIRONMENT_ONLY`;
- own passes and fewer than four shared strata pass:
  `OWN_OVERSHOOT_CHANNEL_ONLY`;
- both fail: `OWN_SHARED_ATTRIBUTION_NOT_RESOLVED`.

Individual stratum results remain visible even when broad classification fails.
They do not authorize industry, size, liquidity, closing-arm, or market-state
selection. Those require a later separately frozen question if this decomposition
leaves material uncertainty.

Passing establishes pre-2024 association topology only. It is not causality, a
security score, a short signal, a veto, a stop, an entry clock, execution, habitat,
or strategy. Future fields remain attribution only. V1, strategy outcomes,
post-2023 data, and CY-011 remain closed.
