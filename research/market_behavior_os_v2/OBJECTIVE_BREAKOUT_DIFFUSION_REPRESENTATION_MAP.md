# Objective breakout formation and diffusion representation map

Frozen before MKT-BREAKOUT-DIFF-DATA-001 constructs the full-market prior-high
population or inspects any full-market crossing count. This is an outcome-blind,
strategy-independent market-breadth family. It establishes representation quality
before any process, prediction, habitat, trading, or payoff question.

## Scientific question

How broadly does the eligible A-share market create objective prior-high crossing
opportunities during a completed session, how deeply do those opportunities cross,
how often are they accepted or rejected at the close, and are formation and
acceptance diffuse across industries or concentrated in a narrow leadership set?

The unit is a completed date x governed market view x denominator. Security-level
events are ingredients of a market state, not candidate trades. No event is called
successful, favorable, demand-driven, or executable.

## Non-duplication boundary

MKT-BRTH-002's accepted discovery coordinate is close-based net participation at
an inclusive 40/60/80-session high minus low. The present family is different:

- its event is `current coordinate high > maximum strictly prior coordinate high`;
- its primary reference is 20 completed sessions, with 10/40 fixed neighbors;
- it retains all crossers, including those closing equal to or below the level;
- it separates formation incidence, crossing depth, closing state, and industry
  distribution;
- it has no new-low subtraction, within-year rank, V1 membership, or outcome.

The accepted MKT-BRTH-002 discovery and positive-return leadership-concentration
coordinates are mandatory external controls. If the new roles are reconstructable
from them, the result is compression, not a renamed discovery.

## Causal coordinate and eligible population

For security `i` on completed session `t`, use the already accepted CY-006 causal
action-aware continuous close `C_i,t`. Raw official daily high and close are `H_i,t`
and `D_i,t`:

`H*_i,t = C_i,t * H_i,t / D_i,t`.

For `h` in {10,20,40}, the objective level is:

`R_i,t,h = max(H*_i,t-k for k=1..h)`.

The current session is excluded. Every current/prior row and coordinate step in the
41-session core must be consecutive, hard-valid, action-valid, finite, positive,
causally available, and nonblocking. Rights participation remains outside the
accepted coordinate scope. Current rows must be trading, data-tradable, and have
positive volume. Any unknown required fact fails closed.

The crossing and close states are:

- `X_i,t,h = 1[H*_i,t > R_i,t,h]`;
- `A_i,t,h = 1[X=1 and C_i,t > R_i,t,h]`;
- `E_i,t,h = 1[X=1 and C_i,t = R_i,t,h]`;
- `J_i,t,h = 1[X=1 and C_i,t < R_i,t,h]`.

Equality is neutral and is never reassigned. `X=A+E+J` must conserve exactly.
These are completed-session facts first available at 15:00 Asia/Shanghai and can
only affect a later action. Daily high does not reveal continuous-auction crossing
time; no entry timing or same-session use is permitted.

## Governed views and denominators

- `ALL_A`: `.SH` and `.SZ` A-share observations;
- `SH_A`: `.SH` observations;
- `SZ_A`: `.SZ` observations;
- `CHINEXT_BOARD`: historically valid `.SZ` codes beginning `300` or `301`;
- primary denominator `ALL_STATUS` retains ST securities;
- fixed sensitivity denominator `NON_ST` requires current `is_st=false`.

There is no liquidity threshold, strategy membership, selected-event cohort,
current-survivor list, or current index-membership substitution. These exchange and
board views are portability replications, not constituent-index breadth.

## Industry contract

Industry is usable only when `industry_valid=true`, the label is nonempty, and
`source_notice_date <= trade_date`. For each date/view/denominator:

- at least 80% of eligible securities must have a causal industry;
- an included industry must have at least five eligible members;
- at least ten industries must pass the member gate;
- formation-distribution roles require at least five event-bearing industries;
- acceptance-distribution roles require at least five accepted-event industries.

Failure makes the affected industry role missing. It never triggers a fallback
industry, row deletion, favorable pooling, or denominator change.

## Level representation roles

All ratios and proportions are absolute, dimensionless, and semantically identical
across 2018--2023. L20 is primary; L10/L40 are fixed neighboring definitions.

| Role | Primary absolute representation | Economic distinction |
|---|---|---|
| Formation participation | `sum(X_h) / eligible_count` | Frequency of objective high-crossing opportunities |
| Formation depth | mean of `H*/R_h - 1` among `X_h=1` | Conditional crossing magnitude, not frequency |
| Closing acceptance | `sum(A_h) / sum(X_h)` | Conditional fraction retaining the level at close |
| Closing rejection depth | mean of `max(R_h/C - 1,0)` among `X_h=1` | Conditional magnitude below the level, not rejection count |
| Equal-industry formation | equal-weight mean of within-industry `sum(X_h)/eligible_i` | Participation of the typical included industry |
| Formation diffusion | `1 - 0.5 * sum_i abs(event_share_i - eligible_share_i)` | Similarity of event distribution to the eligible industry base |
| Acceptance diffusion | `1 - 0.5 * sum_i abs(accepted_share_i - event_share_i)` | Whether close acceptance is distributed like formation opportunities |
| Formation leadership concentration | top-k share of positive excess event mass `max(X_i - p*eligible_i,0)` | Narrow industry leadership beyond eligible-size expectation |
| Acceptance leadership concentration | top-k share of positive excess accepted mass `max(A_i - q*X_i,0)` | Narrow industry conversion beyond event-opportunity expectation |
| Stock/industry divergence | stock-weighted formation participation minus equal-industry formation | Whether large industries dominate the event state |

Here `p=sum_i X_i/sum_i eligible_i`, `q=sum_i A_i/sum_i X_i`, and all industry
shares use only included industries. Concentration primary is top three industries;
top one and top five are fixed breadth neighbors. A zero positive-excess denominator
is missing, not zero. Formation/acceptance diffusion uses total-variation similarity
and remains in [0,1] up to binary floating arithmetic.

The following exact identities are descriptive and cannot become extra mechanisms:

- unconditional accepted participation = formation participation x closing acceptance;
- conditional close-below share is `1 - acceptance - equality_share`;
- net accepted-minus-rejected participation is a composite of the same counts;
- formation leadership concentration and diffusion may be redundant manifestations.

## Coordinate systems

For every primary level role that passes construction:

1. **Absolute:** the raw dimensionless value above; this is primary and
   cross-year comparable.
2. **Strict PIT historical:** within view/denominator expanding percentile,
   trailing-756-session percentile, and trailing-756-session median/MAD robust z,
   all including only observations available through t and requiring 504 valid
   prior/current observations. Zero MAD is missing.
3. **Relative:** same-date value minus ALL_A and percentile rank among at least
   three available governed views. Relative values never replace absolute state.

No within-year rank, full-sample normalization, backfill, or future observation is
permitted.

## Representation-quality and latent-mechanism gates

MKT-BREAKOUT-DIFF-DATA-001 is count/lineage/resource feasibility only. If it
passes, a separate frozen representation experiment must require:

- raw role coverage at least 95% for nonindustry roles and 90% for industry roles;
- at least 150 nonmissing observations in every eligible view-year cell and
  nonzero within-cell variation;
- L20 versus each L10/L40 neighboring-definition median Spearman across views at
  least 0.70;
- ALL_STATUS versus NON_ST median Spearman across views at least 0.90;
- absolute semantic bounds and exact count identities;
- expected causal PIT coverage after the 504-observation warm-up;
- exchange/board portability without constituent-index claims;
- complete internal pairwise redundancy and deterministic components at absolute
  Spearman 0.85;
- role-specific external geometry against MKT-BRTH-002 discovery breadth and
  leadership concentration, using both pairwise absolute Spearman 0.85 and joint
  adjusted rank-R2 0.70 boundaries.

Minimal-role priority is:

`formation_participation, formation_depth, closing_acceptance,
closing_rejection_depth, equal_industry_formation, formation_diffusion,
acceptance_diffusion, formation_leadership_concentration,
acceptance_leadership_concentration, stock_industry_divergence`.

A passing later role is compressed when an earlier retained role crosses the fixed
internal boundary. External reconstructability removes direct-mechanism status even
if internal construction is stable. Controls cannot be deleted after results.

## Momentum, acceleration, divergence, and transitions

Level quality precedes temporal research. Only retained direct level roles may enter
a separately frozen dynamic map. Candidate broad, non-mined operators are:

- five-session change, with three/ten-session fixed shape neighbors;
- five-session second difference, with three/ten-session fixed neighbors;
- actual-session endpoint rate, challenged by OLS and Theil--Sen direction;
- transitions between high/low causal-PIT regions only if stable continuous geometry
  first justifies fixed boundaries.

No transition estimate, state threshold, or process label is allowed in the data or
level-representation experiment. The failure of MKT-BRTH-001's exact MA20
acceleration/crossing definitions remains authoritative and is not reopened by
renaming them.

## Falsification and claim boundary

- Reconstruct all 9,575 immutable MKT-BREAKOUT-DATA-001 target coordinates exactly
  as a protected-coordinate replication before accepting the full-market build.
- Independently reconstruct at least five hash-selected L20 events from source
  rows without calling the aggregate event implementation.
- Verify exact `X=A+E+J`, view nesting, denominator nesting, industry mass, bounds,
  and date conservation.
- Execute every accepted stage twice with byte-identical durable outputs.
- Strategy fields, future returns/volatility, candidate membership, MFE, MAE, P&L,
  post-2023 partitions, QD-004 minute paths, and CY-011 are prohibited.
- OHLCV cannot identify orders, aggressors, absorption, accumulation, distribution,
  overhead-supply depletion, or causal demand.

Passing establishes only a stable market-state representation. It does not establish
a recurring process, forecast, strategy habitat, entry trigger, failure veto,
economic usefulness, causal mechanism, or new strategy archetype.
