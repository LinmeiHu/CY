# Strategy-independent Market State Engine

The engine describes the market without fitting state boundaries to any strategy
return. Initial dimensions are:

| Dimension | Absolute coordinate | PIT-normalized coordinate | Relative coordinate | Evidence status |
|---|---|---|---|---|
| Trend | 60-session log direction frozen; strength/quality/age/alignment/transition attempted | direction has causal expanding/rolling percentiles and robust z-score | direction has contemporaneous six-index rank | DIRECTION_FROZEN_OTHER_ROLES_NOT_FROZEN |
| Breadth | net 60-session new-high/new-low participation and top-decile positive-return leadership concentration frozen; fixed 40/80 and top5/top20 neighbors stable | both roles have expanding/trailing causal percentiles and robust z | ALL_A/SH_A/SZ_A/CHINEXT_BOARD relative views; exact constituent-index breadth unavailable | TWO_ROLES_FROZEN_OTHER_TESTED_REPRESENTATIONS_NOT_FROZEN |
| Volatility | realized level, intraday range, squared-return-mass concentration, and change frozen; downside level/dispersion redundant; term structure/asymmetry unstable | causal percentiles and robust z | governed-view contrasts | FOUR_ROLES_FROZEN_USEFULNESS_UNTESTED |
| Liquidity | own-history-relative activity, turnover level, and amount concentration frozen; participation/diffusion compressed into activity; fixed change unstable | causal percentiles and robust z | governed-view contrasts with audited units | THREE_ROLES_FROZEN_TRANSITION_NOT_FROZEN |
| Dispersion/correlation | leave-one-out 20-session co-movement and 5-session directional synchronization frozen | causal percentiles and robust z | governed-view contrasts | TWO_ROLES_FROZEN_PANIC_PROCESS_UNTESTED |
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

## MKT-BRTH-002 and MKT-GEO-001 boundary

Two breadth descriptor roles are representation-stable, not useful signals.
Participation/depth/diffusion form one highly redundant cluster but their exact
long neighbors fail stability. Momentum/crossing form another cluster whose exact
neighbors also fail. Acceleration and divergence are unstable as tested.

Trend direction and both accepted breadth roles are contemporaneously
nonredundant under MKT-GEO-001. This permits continued state-process research but
does not authorize discrete habitats or strategy association. The sign-based
discovery geometry is occupancy-imbalanced and remains diagnostic only.

## MKT-CLQ-001 boundary

Co-movement, directional synchronization, liquidity activity, turnover level,
and amount concentration are stable nonredundant descriptor roles. Liquidity
participation and industry diffusion collapse into activity at the frozen 0.85
redundancy edge. The exact liquidity-change representation is horizon-unstable.
No combination is a panic state, recovery process, impairment marker, habitat,
or signal.

## MKT-LDR-001, MKT-VOL-001, and minute boundary

The fixed concentration-decay and discovery-deterioration transitions do not
freeze, so no leader-failure geometry exists. The causal leadership/discovery
level imbalance freezes but is contextual state only.

Realized volatility, intraday range, volatility concentration, and volatility
change freeze as nonredundant roles. This does not establish contraction,
expansion, panic, or payoff behavior.

Market-wide five-day minute data pass a bounded cross-year/view readiness audit.
No minute market-state role is frozen because the readiness sample has only six
market dates and cannot supply 504 causal historical observations per view.
