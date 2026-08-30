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
| Industry/relative strength | industry return dispersion, winner-industry diffusion, rank rotation, stock/industry residual tail balance, and residual concentration are externally distinct; participation and residual dispersion compress into existing dimensions | causal expanding/trailing percentiles and robust z | governed-view contrasts and exact stock-versus-industry residuals | FIVE_DIRECT_ENGINE_ROLES_TEMPORAL_MEANING_UNTESTED |
| Circulating size/style | positive participation balance, winner diffusion, positive-mass concentration, size-curve divergence, and leadership transition are externally distinct; size structure compresses into activity/risk ordering | causal trailing percentiles and robust z | relative-to-ALL_A plus corrected same-date four-view ranks | FIVE_DIRECT_ENGINE_ROLES_TEMPORAL_MEANING_UNTESTED |
| Objective-level recovery | conditional recovery speed and recovery-volume intensity survive fixed generic daily/minute controls; signed level geometry, recovery amplitude, and level slopes compress | unavailable from isolated sampled weeks | raw conditional observations only; sparse within-date ranks prohibited | TWO_CONDITIONAL_OBSERVATIONS_DISTINCT_TEMPORAL_PROCESS_UNTESTED |
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

## MKT-INDRS-001 boundary

Eight of eleven industry/relative-strength primaries pass their frozen gates.
Equal-industry return depth is a redundant participation manifestation, leaving
seven internally nonredundant roles: equal-industry positive participation,
industry return dispersion, winner-industry diffusion, rank rotation, and
leave-one-out stock/industry residual dispersion, tail balance, and positive-
mass concentration.

Industry-vs-market depth fails its fixed neighboring definitions; industry
positive-mass leadership concentration lacks the required definable coverage;
and top-set persistence fails neighbor and denominator stability. The engine
does not substitute a favorable threshold, view, year, or denominator. The
seven survivors remain provisional engine dimensions until role-specific
geometry against accepted direction, breadth, correlation/liquidity,
volatility, risk-appetite, and leadership controls is frozen. No temporal or
strategy interpretation is attached.

MKT-INDRS-GEO-002 completes that compression. Equal-industry participation is
pairwise redundant with broad central direction, while stock/industry residual
dispersion is jointly reconstructable from co-movement and volatility. The
engine retains five direct coordinates: industry return dispersion, winner-
industry diffusion, rank rotation, residual tail balance, and residual
concentration. No transition or future annotation is attached; representation
distinctness is not temporal meaning.

MKT-INDRS-DYN-001 adds one provisional temporal annotation: five-session rank
rotation persists into the immediately following block across raw, PIT,
relative, temporal, group-sign, and phase-zero gates. Winner diffusion neither
replicates as a precursor to rotation nor as a response to rotation. The engine
retains no diffusion/rotation cross-process. Rotation persistence remains
provisional until delayed non-shared-endpoint and alternate-definition
falsification; it has no return or strategy meaning.

## MKT-STYLE-001 and MKT-STYLE-GEO-002 boundary

Six circulating-size roles survive internal compression, but corrected external
geometry retains only five as direct engine coordinates: positive participation
balance, winner diffusion, positive-mass concentration, size-curve divergence,
and leadership transition. Size structure shares the exact four-view ordering
of turnover, liquidity concentration, and realized volatility and is retained
only as a descriptive manifestation.

The five direct roles are contemporaneous market-state coordinates. None has a
future annotation, size-premium interpretation, habitat, or strategy meaning.
The stable transition coordinate may enter a separately frozen outcome-blind
future-state process test; the failed 10/20/40 leadership level may not be
revived or selected as a favorable horizon.

MKT-STYLE-DYN-001 does not add a temporal annotation. The accepted transition's
raw/PIT self-edge weakens sharply in the later reused block, its 3/10 definitions
also decay, and phase-zero reverses. Favorable relative behavior is not a
portable process. The engine retains all five contemporaneous coordinates but
emits no size persistence, reversal, rotation, or habitat state.

MKT-STYLE-PART-DYN-001 also fails. Current size positive participation has near-
zero full-sample partial association with future accepted T5 and reverses across
reused blocks; both tail definitions and both relative views fail. A favorable
phase-only sample is not a state process. The engine closes this exact style
temporal branch and retains contemporaneous size roles without future meaning.

## MKT-SUPPORT-001 and MKT-SUPPORT-GEO-001 boundary

The causal prior-low/minute coordinate passes, but external compression retains
only conditional recovery speed and recovery-volume intensity as distinct from
fixed generic daily and minute path/activity controls. Signed geometry and its
slope are daily-low-distance manifestations; closing-state slope is daily-close
geometry; recovery amplitude is jointly generic range/close-location/return.

The two survivors are completed-session observations available at 15:30. They
have no causal historical normalization and the existing sample supplies only
29 repeated-tested sequences. The engine therefore emits no support-defense,
recovery-progression, failure, habitat, timing, or strategy state. A larger
calendar/CY-006-selected sample must be frozen before minute outcomes are read.

MKT-SUPPORT-DYN-DATA-004 replaces that support limitation with an exact,
outcome-blind calendar/CY-006-selected sample: 315 sequences have repeated tests
and 269 have at least two completed recoveries, with every fixed year/block floor
passing. This changes feasibility only. The engine still emits no recovery
direction, defense, deterioration, transition, habitat, timing, or strategy
state until a separately frozen temporal map survives its process gates.

MKT-SUPPORT-DYN-001 adds two completed-history coordinates: recovery-speed
endpoint rate and recovery-volume-intensity endpoint rate. Both survive fixed
shape, L10/L40, auction, and generic-path geometry. They have no causal
historical or promotable relative coordinates, and only 100/269 sequences have
three or more recovered days.

The engine adds no common direction or support-defense annotation. Speed block
medians are zero; activity directions are near-even and mixed by year. Raw
timing/activity coupling is control-explained, and completion-state dependence
is below its first-F support floor with nonportable intervals/signs. The exact
unchanged-level feasibility audit remains before any physical support process.

MKT-SUPPORT-LVL-DATA-001 finds only seven exact unchanged-L20 repeated-test
sequences; L10/L40 and auction neighbors also have only 5--9. The engine therefore
retains the two rolling-definition trajectory coordinates but explicitly does
not label them repeated support, defense, strengthening, or deterioration. No
same-level temporal state is emitted and this exact branch is deprioritized.

## MKT-BREAKOUT-DATA-001 boundary

The engine now has an audited event domain, not a breakout state. Objective
prior-high L10/L20/L40 coordinates use the accepted causal action chain and
strictly prior daily highs; mapped minute highs define strict crossings. The
primary L20 continuous domain supplies 964 cohort events with both closing arms,
899 full 60-bar opportunities, and 641 loss/reacquisition cases across both
blocks and all years/views. Neighbor and auction support pass.

No post-cross magnitude or latent score has yet passed representation quality.
The engine therefore emits no continuation, rejection, acceptance, demand,
overhead-supply, transition, habitat, timing, or strategy coordinate from this
audit. A separately frozen same-session experiment must first survive
definition stability and generic-path compression.

## MKT-BREAKOUT-001 boundary

The engine retains seven completed-session objective prior-high observables:
30-bar continuation, rejection depth, below-level dwell, loss episodes,
conditional reacquisition speed, cumulative-VWAP acceptance, and post-cross
activity. All survive fixed L10/L40, auction, shape, block/year, and generic-
path gates. Follow-through excursion and closing margin are external daily-path
manifestations; above-level episodes are loss-episode redundant.

These absolute coordinates are first available only after their defining bars,
with the complete session artifact at 15:30. The isolated sample cannot support
causal historical normalization or a full contemporaneous relative rank. The
engine emits no latent breakout state, temporal direction, resistance-role
reversal, predictor, habitat, usefulness, or strategy annotation until a
separately frozen repeated-event process survives.

## MKT-BREAKOUT-DYN-003 boundary

The engine retains actual-gap endpoint-rate coordinates for all seven accepted
breakout observations. OLS/Theil--Sen, L10/L40, auction, year/block, and fixed
generic temporal geometry pass. The unconditional roles have 250 repeated-event
trajectories and conditional reacquisition has 171.

The engine adds no common direction, composite, or process annotation. Every
common-direction gate fails and all seven residual roles remain separate; the
nearest rejection/dwell residual correlation misses its global compression
boundary. These coordinates remain completed-history descriptors available at
15:30 on their last included day. They have no causal PIT normalization,
relative state, predictor, habitat, usefulness, or strategy meaning.

## MKT-BREAKOUT-HAB-001 boundary

The engine adds no prior-day state annotation to any breakout role. All support
gates pass, but zero controlled trend/breadth primitive edges and zero fixed
joint increments replicate across absolute, PIT, relative, block, index/view,
and year gates. The favorable block/coordinate fragments are retained only in
the audit and cannot be selected as habitats.

The seven same-session and seven repeated-event coordinates remain descriptive.
No trend-conditioned, discovery-conditioned, concentration-conditioned, joint
state, interaction, gate, predictor, usefulness, or strategy annotation is
emitted.

## MKT-BREAKOUT-DIFF-001 boundary

The engine now retains seven full-market completed-session objective-crossing
level coordinates: formation participation, conditional crossing depth, closing
acceptance, closing rejection depth, formation-industry diffusion, formation-
leadership concentration, and stock/industry formation divergence. All have
absolute, causal PIT, and contemporaneous relative views and pass fixed L10/L40,
year/view, denominator, semantic-bound, and external discovery/concentration
gates. Equal-industry formation is compressed into participation at rho 0.978.

The L40 ChiNext acceptance-industry domain remains below its frozen floor, so
acceptance diffusion/concentration are not engine coordinates. The seven retained
levels are available only at the completed 15:00 close. The engine emits no
momentum, acceleration, transition, recurring breakout-opportunity process,
forecast, habitat, trigger, timing, usefulness, or strategy annotation.

## MKT-BREAKOUT-DIFF-DYN-001 boundary

The engine adds no temporal breakout-diffusion coordinate. Zero of fourteen
fixed 5-session change/acceleration roles passes neighboring 3/10-session and
OLS/Theil--Sen representation gates. High denominator agreement and low
endpoint-level redundancy do not rescue the failures; early-block causal-PIT
external-control support is also below its frozen floor.

The seven MKT-BREAKOUT-DIFF-001 levels remain completed-session observations.
They receive no strengthening/weakening, momentum, acceleration, transition,
recurrence, opportunity-process, forecast, habitat, usefulness, or strategy
annotation.

## MKT-MIN-AD-001 boundary

The engine retains one completed-session `rally_effort_distribution`
coordinate available at 15:30. It is an equal causal-percentile representation
of high upside-minute volume with shallow upside excursion, weak late VWAP
acceptance, and weak final-30-minute return. It passes component/aggregation/
quantile/denominator/year gates and remains below fixed return, volatility,
activity, and VWAP-defense redundancy boundaries.

The engine does not interpret the coordinate as participant distribution,
informed selling, resistance, future reversal, timing, usefulness, or strategy
state. `selling_effort_absorption` is not added because its leave-one-component-
out representation stability fails.
