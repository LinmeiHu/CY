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
| Intraday level | 32 same-session path/VWAP/pressure/volatility/volume representations pass; 23 direct nonredundant roles at 0.85 | causal expanding/trailing percentiles and robust z after 504 observations | ALL_A/SH_A/SZ_A/CHINEXT_BOARD contrasts | LEVELS_FROZEN_USEFULNESS_UNTESTED |
| Five-day intraday trajectory | minute realized-volatility ordinal progression freezes; all exact OLS slopes and the other 35 non-slope roles fail | survivor has causal expanding/trailing percentiles and robust z | governed-view contrasts | ONE_EXTERNALLY_DISTINCT_ROLE_USEFULNESS_UNTESTED |
| Leadership/style | concentration, persistence, diffusion, failure | causal history | industry/index contrasts | CONSTRUCTION_PENDING |
| Risk appetite | signed limit-relative central direction plus separate upside/downside extreme participation frozen; seven manifestations redundant and tail balance deterministic | causal expanding/trailing percentiles and robust z | governed-view contrasts | THREE_ROLES_FROZEN_USEFULNESS_UNTESTED |
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

MKT-SHOCK-001 subsequently freezes two direction-neutral continuous
coordinates: synchronization pressure and joint synchronization/activity stress.
They are stable across fixed smooth/weakest-link shapes, 10/20/60 activity
levels, denominators, views/years, and are nonredundant with frozen volatility.

The exact episode does not freeze. A 0.90 all-component onset occurs zero or one
time per group; strict-neighbor event match is zero, episode-state overlap is
unstable, and no activity-dry-up event occurs. High continuous stress is not a
shock onset, `RELIEF` is not price recovery, and panic remains unrepresented
without a negative-direction coordinate.

## MKT-LDR-001, MKT-VOL-001, and minute boundary

The fixed concentration-decay and discovery-deterioration transitions do not
freeze, so no leader-failure geometry exists. The causal leadership/discovery
level imbalance freezes but is contextual state only.

Realized volatility, intraday range, volatility concentration, and volatility
change freeze as nonredundant roles. This does not establish contraction,
expansion, panic, or payoff behavior.

MKT-MIN-001 required scale covers 1,457 dates and full governed cross-sections.
Thirty-two same-session descriptor levels pass exact coverage, definition,
denominator, portability, and year-cell gates; selloff duration and the auction
gap fail. These are market-state levels, not demand/supply mechanisms.

All 34 exact five-day OLS trajectories fail because their fixed last-three-
session neighbor is unstable even though p40/p50/p60 aggregation is stable. No
trajectory role may be rescued with the best horizon. Non-slope shapes and the
broader minute families remain underexplored.

## HAB-CHX-001 boundary

The engine's direction and discovery coordinates now have one exploratory
association study against an existing strategy. They describe denser observed
CHINEXT V1 opportunity formation, including distinct partial association for
evaluated/candidate counts. This does not convert either representation into a
general trading signal or strategy-habitat predictor.

The A+B interaction survives only for daily formation counts, not admissions or
payoff. Direction's payoff association is more-negative MAE; discovery's is
MFE>=20% opportunity without strict incremental or conversion support. Final
return, right-tail, false-breakout, and severe-loss primaries fail. Discrete
habitats remain unfrozen.

## MKT-RISK-001 boundary

All eleven preregistered same-session signed representations pass fixed
definition, denominator, coverage, year, PIT, and relative-coordinate gates.
The registered-limit coordinate is exact on 5,035,742 of 5,036,345 causal core
rows. Six hundred three out-of-bound rows fail closed; one CHINEXT/ALL_STATUS
group/date falls below 99% and is missing rather than repaired.

Outcome-blind compression retains three roles: cross-sectional central
direction, upside extreme participation, and downside extreme participation.
Ordinary signed participation, tail depth, same-day mass concentration, and
industry diffusion are central-direction manifestations at the frozen 0.85
edge. Tail balance is stable but deterministically equals upside minus downside
extreme participation, so it adds no independent mechanism. No role is redundant
with frozen breadth or volatility. This is signed state representation, not a
panic process, habitat, forecast, or trading signal.

## MKT-DSTRESS-001 boundary

The tested weakest-link combination of synchronization pressure and signed
extreme participation does not freeze. Downside/upside coverage, denominator,
year, and single-input/volatility nonredundancy pass, but the arithmetic-shape
neighbors are 0.691 and 0.646 versus the fixed 0.70 gate. Favorable geometric
and 50/90-definition neighbors cannot rescue either primary.

The 0.80 entry/0.50 reset recurring processes also fail. Downside has only 1-4
onsets per group in one year; upside has 0-8 in at most two years. Strict onset,
state overlap, dwell/relief, and activity support fail. The engine therefore
retains the signed and synchronization primitives separately and emits no
directional interaction, onset, panic, or activity-modified process.

## MKT-MIN-PATH-002 boundary

The corrected 15:30-available exact retry freezes one of 36 non-slope roles:
minute-realized-volatility ordinal progression. It is stable across two broad
ordinal definitions and p40/p60 aggregation, portable across denominators and
view/year cells, and distinct from its same-session minute-volatility level.

No selling-pressure, demand, VWAP, path, or volume trajectory freezes, and no
signed reversal or curvature freezes. The accepted ordinal role is a path-shape
coordinate only. External redundancy with daily volatility remains to be tested
before it can be treated as a distinct state mechanism; usefulness remains
untested regardless of that result.

MKT-MIN-VOL-GEO-002 clears that external redundancy question. Pairwise median
absolute associations are at most 0.249 and joint five-control adjusted rank R2
is 0.195 median/0.223 maximum. The engine may retain the path as a separate
continuous coordinate. It may not yet emit discrete contraction/expansion
states: definition-neighbor state agreement, recurrence, dwell, and transition
support remain untested.

MKT-MIN-VOL-STATE-001 then rejects exact discrete states. Although primary
rising/falling/flat labels recur and have completed-run support, the two
accepted ordinal definitions produce low state agreement and transition
matrices separated by total variation 0.469/0.611. The daily-level context is
also early-year warm-up-limited and later-cell sparse. The engine retains only
the continuous path coordinate and emits no volatility path state or process.

MKT-MIN-VOL-RESP-002 finds no incremental temporal meaning for that continuous
coordinate. Five-session partial-rank response is about -0.02 in both temporal
blocks and fixed non-overlap is also near zero; one-session response flips sign
and three-session response weakens. Raw negative association is explained by
current-volatility controls. The engine retains a descriptive coordinate only,
with no continuation/reversal or usefulness annotation.
