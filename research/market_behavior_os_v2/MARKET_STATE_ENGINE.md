# Strategy-independent Market State Engine

The engine describes the market without fitting state boundaries to any strategy
return. Initial dimensions are:

| Dimension | Absolute coordinate | PIT-normalized coordinate | Relative coordinate | Evidence status |
|---|---|---|---|---|
| Trend | 60-session log direction frozen; strength/quality/age/alignment/transition attempted | direction has causal expanding/rolling percentiles and robust z-score | direction has contemporaneous six-index rank | DIRECTION_FROZEN_OTHER_ROLES_NOT_FROZEN |
| Breadth | eligible fractions, depth, diffusion, divergence | causal history within comparable coverage | industry/style participation contrasts when governed | PARTIAL_PRIOR_EVIDENCE |
| Volatility | realized/downside/range volatility and term structure | causal volatility context | cross-index/industry comparison | CONSTRUCTION_PENDING |
| Liquidity | amount/turnover level, concentration, shock/recovery | causal history | cross-sectional comparison with stable units | CONSTRUCTION_PENDING |
| Dispersion/correlation | cross-security and cross-industry spread/co-movement | causal history | segment contrasts | CONSTRUCTION_PENDING |
| Leadership/style | concentration, persistence, diffusion, failure | causal history | industry/index contrasts | CONSTRUCTION_PENDING |
| Risk appetite | observable tail participation and speculative demand proxies | causal history | segment contrasts | REPRESENTATION_PENDING |
| State transition | onset, acceleration, deterioration, reversal, dwell time | causal transition rarity | synchronized versus idiosyncratic transition | CONSTRUCTION_PENDING |

## Construction gates

1. exact registered inputs and frozen snapshots;
2. completed-bar availability and explicit `decision_at`;
3. no strategy outcome or trade field;
4. economically distinct representations rather than parameter clones;
5. adequate causal history, coverage, and year/block continuity;
6. neighboring-horizon stability without exact-window optimization;
7. redundancy report before compression;
8. immutable feature artifact before any strategy association.

The engine will initially emit continuous dimensions and transparent diagnostic
states. Discrete habitats are not frozen until transition stability and external
strategy-independent meaning are demonstrated.

## MKT-TRND-001 boundary

The accepted direction role is a market descriptor, not a forecast. Fixed
quality, age, and transition representations were horizon-unstable. Strength and
alignment were limited by strict source-row quarantine and are neither accepted
nor mechanistically rejected. No discrete trend habitat is authorized.
