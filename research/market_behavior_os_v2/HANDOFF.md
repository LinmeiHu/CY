# Market Behavior Research OS V2 handoff

Updated 2026-08-31.

## Latest checkpoint: MKT-BREAKOUT-ECON-001

The frozen economic estimator completes twice with identical panel `314a5d39...`,
level audit `658542de...`, year audit `dd03d9e7...`, episode audit `1f34aedf...`,
transition audit `ec31207b...`, placebo `3174f37d...`, conditional audit
`e573e4b0...`, result `0aa68e75...`, and report `2015cbf6...`.

Formation depth is the sole supported market state, specifically a downside/
tail-risk level. Its h=3 high-minus-low adverse-excursion effect is -0.011116;
PIT/raw rho are -0.1805/-0.1838. All cells, raw/PIT years, leave-one-year-out,
neighbor horizons, and nonoverlap phases retain the negative sign. Placebo q is
0.008706 and fixed-control partial rho is -0.1399 in the same direction in all
eight cells and both blocks. Terminal return does not pass.

Closing rejection depth is not promoted: its unconditioned downside result is
portable but control-adjusted rho falls to -0.0652 below the frozen floor. The
other five roles miss economic size/rho. All up/down transition effects remain
not estimable under the original episode support floor, not zero.

The next action is a new, separately frozen formation-depth x CHINEXT V1 habitat
study using already-consumed pre-2024 strategy evidence. Test opportunity,
failure, realization, and right-tail endpoints incrementally at candidate/trade
level where possible. Do not optimize CAGR, choose a state threshold, modify V1,
read post-2023 data, or open CY-011.

## Latest checkpoint: MKT-BREAKOUT-ECON-DATA-001

The next-frontier economic-response map `ef8ccea2...` and final data contract
`1b3a058a...` are frozen. They fix all seven parent L20 roles, causal PIT-3y 0.50
up/down crossings, a five-opposite-session episode rule, PIT 0.20/0.80 level
tails, same-level local matching, 1/3/5 horizons with h=3 primary, annual/block/
leave-one-year-out/nonoverlap evaluation, two fixed controls, and a 200-shift
temporal null. No threshold, direction, horizon, caliper, or null may change after
outcomes are seen.

MKT-BREAKOUT-ECON-DATA-001 passes the exact response-domain gates twice with
byte-identical panel `aaf67e12...`, count audit `5770d29d...`, scalar audit
`9c961c92...`, result `2bae2c9a...`, and report `ea877c8a...`. The panel has
11,296 complete cells, minimum cohort retention 0.973090, 203 minimum dates per
view/denominator/year, and no response after 2023-12-29. Five scalar cases across
15 coordinate/response fields are exact.

The first implementation correctly stopped on a dropped temporary coordinate
table, then on a 1.5-GiB five-way-join plan. The final runner retains the exact
accepted coordinate table, narrows it, and processes one future step and one event
year at a time without changing science. A later conservation diagnostic found
only 2.8e-16 mapped-low ULP violations when raw low equaled close. Before any
economic estimate, the formula was made operationally exact as
`C * (low / close)` and independently scalar-reconstructed; no clipping or
tolerance was introduced.

No relationship between a state and a response has yet been measured. The next
action is the separately frozen MKT-BREAKOUT-ECON-001 estimator. Do not inspect a
favorable direction informally, change the fixed gate, use strategy outcomes, or
open CY-011.

## V2.1 resume identity

- Exact starting checkpoint: `6ee0fb87cf611db8a5f79eb581e23ce92f82cff8`.
- Branch/worktree/ancestry/exclusivity checks passed before work.
- CY-011 and all strategy outcomes remain unopened.

## What changed?

The active program was corrected from CHINEXT-centered optimization to
market-first research. CHINEXT V1 and SuperMind V6 are preserved as seed cases.
The global architecture now separates market hypotheses, strategy archaeology,
and strategy invention.

## What is known?

Seed research supplies qualified breadth/opportunity, right-tail, false-breakout,
and early-path evidence plus many exact negative results. None is yet a general
strategy-independent market engine. The five-day minute audit establishes data
feasibility only for a CHINEXT-conditioned event sample.

## What is not known?

No leader-failure, panic-process, or market-wide intraday mechanism is frozen.
Volatility has representation support but no usefulness evidence. No strategy x
habitat matrix cell is evidence-populated. No new
strategy mechanism has crossed the prototype threshold.

## What was constructed?

MKT-TRND-001 completed outcome-blind on 19,569 rows from six registered indices.
It established representation stability, not strategy usefulness. The tested
60-session log direction passed the neighboring-horizon representation-stability
gate: its worst 40/80-neighbor median within-index Spearman is 0.779, raw coverage
is 0.998, and its absolute, causal PIT, and relative coordinates are available.
It has not been established as a trading signal or strategy-habitat predictor.
Two successful runs are byte-identical.

Quality, age, and transition failed fixed neighboring-horizon stability. Strength
and alignment passed neighbor stability but missed exact coverage because 21
source OHLC ordering violations were failed closed and contaminated their rolling
windows. The tested quality, age, and transition representations failed; their
broader research families are not rejected. Strength and alignment remain
data-contract-limited and unresolved. Do not relabel these results as mechanism
failures, and do not rescue a role by selecting a better-looking exact window.

## What else was constructed?

MKT-BRTH-002 completed the strategy-independent breadth construction on 6,155,390
CY-006 rows. Net new-high/new-low participation and leadership concentration are
the only two frozen roles. Exact participation, depth, momentum, acceleration,
industry diffusion, divergence, and crossing representations failed neighboring-
definition stability; do not tune their windows or reject their broader families.

MKT-GEO-001 then used only frozen direction and breadth descriptors. Direction
versus discovery has median Spearman 0.489 (maximum absolute 0.571); direction
versus leadership concentration is -0.360 (maximum absolute 0.408); discovery
versus concentration after direction has median partial rank -0.490 (maximum
absolute 0.530). All nonredundancy gates pass. No future return or strategy field
was read. The absolute zero discovery boundary is occupancy-imbalanced—negative
direction plus positive discovery is common—so the quadrant map is descriptive,
not a frozen habitat classifier.

MKT-CLQ-001 then constructed eight outcome-blind correlation/liquidity concepts.
Co-movement, directional synchronization, own-history-relative liquidity
activity, turnover level, and amount concentration are stable and mutually
nonredundant at 0.85. Liquidity participation and industry diffusion are stable
but redundant with activity. Five-session liquidity change fails its 3/10-session
neighbor gate. The failure does not reject the transition family.

The source unit audit covers 5,814,399 eligible rows and proves positive amount,
finite nonnegative turnover, `turnover_fraction == turnover_pct / 100` to machine
precision, and no registered amount beyond three decimals. Exact decimal ledger
addition conserves every disjoint amount partition. Two runs are byte-identical.

MKT-LDR-001 next found that concentration decay and discovery deterioration fail
fixed definition/horizon stability, so it did not form joint leader-failure
geometry. Only causal leadership-versus-discovery level imbalance freezes, and
that is not a failure transition.

MKT-VOL-001 freezes four nonredundant volatility roles: realized level, intraday
range, squared-return-mass concentration, and volatility change. Downside level
and dispersion are stable but redundant; term structure and downside-mass share
fail their fixed neighbor gates. No panic or volatility usefulness claim exists.

AUDIT-MKT-MIN-001 then passes a deterministic strategy-independent minute sample:
240 trajectories, 1,200 exact five-day sessions, six years, four views, 289,200
mapped raw rows, zero opening-window difference, and zero five-minute
volume/amount conservation difference. Two flat sessions and one lock on each
limit side are retained.

## Minute scale blocker resolution

The `STOP_UNSAFE_MARKET_MINUTE_REPRESENTATION_SCALE` blocker is resolved. The
scientific contract retains all 1,457 pre-2024 exchange dates, the full eligible
ALL_A/SH_A/SZ_A/CHINEXT_BOARD cross-section, both denominators, 34 descriptors,
and the 504-observation PIT gate. No 50-name proxy or CHINEXT event substitution
is used.

The adapter reads one date at a time through Parquet date predicates and only
the governed columns. It validates the 09:30 auction, 09:31..11:30 and
13:01..15:00 grid, raw adjustment, OHLC/units, missing bars, timestamps, causal
CY-006/CY-008 lineage, and exact five-minute mass conservation. Complete 241-row
sessions are reshaped and all security descriptors are computed with NumPy
across sessions, without a Python loop over minute rows or securities.

Tiny and all 1,200 accepted reference sessions pass. Maximum descriptor
difference is `4.99933427988708e-13`; opening-window and volume/amount
conservation differences are zero; 17 causal corporate-action sessions are
retained. Two small runs have identical descriptor hash `05b0a966...` and
opening hash `0a8d4586...`.

The predeclared 2020-02-03..2020-02-28 full-market stage processed 18,201,043
raw rows, 75,442 complete raw sessions, and 71,481 final causal sessions in about
eight seconds. Its minimum view cross-section is 753 and minimum descriptor
coverage 0.99933. The first required attempt correctly stopped 6.4 MB above the
3 GiB peak-RSS ceiling. Removing audit-only annual context columns without
changing scientific values reduced representative RSS below 1.9 GiB; two current
panel hashes are `fcc04aec...` and opening hashes remain `9093a928...`.

Required scale then passed in 407.55 seconds at 2,896,543,744 bytes peak RSS. It
processed 1,473,342,173 SH/SZ raw rows, 6,060,257 complete sessions, and
5,814,290 final causal sessions into 11,656 daily and 11,624 five-day market
rows. Minimum descriptor coverage is 0.9669; exact conservation remains zero.

Thirty-two same-session level representations freeze. Selloff-duration and
auction-gap levels fail cross-sectional-neighbor stability. Redundancy at 0.85
leaves 23 direct nonredundant level roles across price path, VWAP, selling,
buying, volatility, and volume path. These are state descriptors only.

All exact five-day OLS-slope representations fail their fixed last-three/
endpoint shape-neighbor gate; worst correlations range 0.288-0.514. No five-day
trajectory role, selling-exhaustion mechanism, demand-strengthening mechanism,
or strategy is frozen. The broader intraday and non-slope trajectory families
remain underexplored.

HAB-CHX-001 then completed on 1,337 common state dates, 819 evaluated events,
638 admissible candidates, and 280 selected/completed cycles with zero same-bar
fills. Two runs are byte-identical: panel `922920fd...`, result `5bb39c2a...`,
report `7b0c05b5...`.

A and B associate with opportunity density; partial A/B and fixed A+B evidence
survive only for evaluated/candidate counts. Falling selected rates reflect
finite vacancies under denser flow. Direction associates with more-negative
MAE. Discovery associates with MFE>=20% opportunity, but not strict B-given-A or
conversion. Final return, right-tail, false-breakout, severe-loss, and every A+B
payoff primary fail. No rule, predictor, causal mechanism, or archetype freezes.

SYNTH-MKT-007 selects MKT-SHOCK-001 next. Build the outcome-blind correlation/
liquidity shock-and-recovery Representation Map and frozen spec before testing.
Do not tune the rejected five-session liquidity-change window, read strategy
outcomes, or open CY-011.

MKT-SHOCK-001 is now complete. Synchronization pressure and the continuous
weakest-link joint stress score freeze; joint-score neighbor rhos are
0.794-0.954, ALL_STATUS/NON_ST median rho is 0.999, and the roles are not
volatility-redundant. Two runs are byte-identical: panel `bba55a5a...`, result
`29eb55a5...`, report `9b51ec9c...`.

The exact episode fails without rescue. It has zero or one onset per group,
strict onset match zero, unstable/undefined stress-relief/dwell neighbors, and
zero activity-dry-up observations. It establishes no onset, recovery, panic,
reversal, or usefulness claim.

SYNTH-MKT-008 selects MKT-RISK-001 next: a strategy-independent directional
tail/risk-appetite Representation Map. Use registered return/limit/industry
facts, preserve absolute/PIT/relative coordinates, and test redundancy against
breadth/volatility. Do not combine it with stress or read outcomes until its own
representations freeze.

MKT-RISK-001 was frozen before construction under spec `7b5303c3...`. Its map
keeps positive and negative participation/tails separate, uses registered
5%/10%/20% limit geometry, and binds only accepted breadth/volatility roles as
redundancy controls. The construction subsequently completed as recorded below.

MKT-RISK-001 is now complete. It uses 5,035,742 exact registered-limit
coordinates from 5,036,345 causal core rows. The 603 out-of-bound rows are not
repaired; one CHINEXT/ALL_STATUS group/date misses the unchanged 99% gate and is
missing. Every one of the eleven preregistered roles passes its own stability
gate. Compression leaves central direction plus separate upside and downside
extreme participation. Tail balance is retained as a coordinate but excluded as
the deterministic difference of the two tail primitives. No external breadth/
volatility redundancy reaches 0.85.

Two final runs are byte-identical: panel `fe7436e...`, result `4fdfd600...`,
and report `b69b2b2e...`; four targeted tests pass. The first over-strict runner
abort is invalid and separately recorded.

SYNTH-MKT-009 selects MKT-DSTRESS-001. Build and freeze a Directional
Synchronization/Stress Process Map before testing. Use only frozen risk and
stress coordinates, preserve upside/downside primitives, keep liquidity
activity an explicit modifier, and do not reuse the rejected all-three sparse
episode as a primary. No outcomes, strategy fields, or CY-011 are permitted.

MKT-DSTRESS-001 is complete and byte-identical across two runs: panel
`c3fe91ec...`, result `c00f8eed...`, report `27a092cd...`; four targeted tests
pass. Both continuous sides fail only after their full gates: the arithmetic
aggregation neighbor is 0.691 downside and 0.646 upside. The exact process also
fails with 1-4 downside onsets in one year and 0-8 upside onsets across at most
two years, plus failed strict/state/dwell/activity support. No directional
interaction, elevated process, activity modifier, panic, or strategy claim
freezes. Do not substitute geometric aggregation or lower thresholds.

SYNTH-MKT-010 selects MKT-MIN-PATH-001. Freeze a structurally distinct non-slope
five-day intraday Process Map before construction. Reuse the exact required-
scale trajectory artifact, avoid a raw-minute rescan, and test monotonicity,
reversal, and curvature shapes without promoting endpoint/OLS3 neighbors as an
OLS5 rescue. Outcomes, strategy fields, and CY-011 remain prohibited.

MKT-MIN-PATH-001 is frozen before construction under spec `bf7e05dc...`. It
binds exact daily hash `bdbb3cb9...` and trajectory hash `89d3e33b...`, selects
12 descriptors and three operators before testing, and forbids raw-minute
rescans plus every OLS/endpoint/precomputed-shape field. Execute twice and keep
all 36 attempts in the ledger; no favorable descriptor/operator may rescue
another.

The MKT-MIN-PATH-001 input audit invalidated that preregistration before
construction: derived trajectories are available at 15:30, not 15:00. The
latest included minute is still the completed 15:00 bar. MKT-MIN-PATH-002 is
frozen under control spec `161b4bb7...`, inheriting scientific design
`bf7e05dc...` unchanged and correcting only availability/output identity.

MKT-MIN-PATH-002 completed on 11,624 group/date rows. Exactly one of 36 roles
freezes: `minute_realized_volatility__ordinal_progression`. It passes complete
raw/PIT/relative coverage, definition-neighbor rhos 0.779/0.711,
aggregation-neighbor rhos 0.889/0.868, denominator rho 0.968, and every
view/year nondegeneracy gate. Its median same-session-level rho is only 0.246.
Every signed-reversal and curvature role fails, as do the other eleven ordinal
progressions. No failed descriptor/operator may be rescued.

Two runs are byte-identical: panel `d0a396a9...`, result `a21b56ea...`, report
`f6ef7331...`; four targeted tests pass. No raw minute row, OLS/endpoint/
precomputed shape, outcome, strategy field, or CY-011 was read. This establishes
one stable five-day path representation only—not contraction/expansion,
supply/demand, prediction, habitat fitness, or a trading signal.

SYNTH-MKT-011 selects MKT-MIN-VOL-GEO-001. Freeze an outcome-blind geometry
study of the sole accepted path role against accepted same-session minute and
daily volatility coordinates. The purpose is redundancy/mechanism separation
before usefulness. Do not add any failed path role or read outcomes.

## Human decision required?

No. Continue map-first with MKT-MIN-VOL-GEO-001. CY-011 remains unopened.

The map and spec `d1f67d05...` are now frozen before construction. The study
binds exact path panel `d0a396a9...` and volatility panel `f7361284...`, expects
10,696 common rows/1,337 per group, and fixes the joint decision timestamp at
15:30. It tests five controls without importing any failed role. Execute twice,
verify exact artifact hashes, and classify only state-coordinate redundancy.

The first construction stopped before any correlation: 2019 PIT fields are
correctly missing during the frozen 504-observation warm-up, and 2020 daily-
control PIT cells have only 102-107 observations in the audited group. The
unchanged gate is 150. MKT-MIN-VOL-GEO-001 is invalid, with no result artifact.

MKT-MIN-VOL-GEO-002 control spec `b556472d...` is frozen. It changes only the
coordinate-specific year eligibility—raw 2019-2023, complete PIT 2021-2023,
relative 2019-2023—and retains all scientific roles, hashes, population,
thresholds, 15:30 availability, and prohibitions. Execute the exact retry.

MKT-MIN-VOL-GEO-002 is complete. The target is pairwise distinct from all five
controls across every available absolute/PIT/relative view. Median absolute raw
rho is 0.249 against the Day -1 minute level and at most 0.238 against the four
daily controls. The five controls jointly reconstruct 0.195 median adjusted
rank R2 (0.223 maximum), well below 0.70/0.85. Two runs are byte-identical:
panel `8cbe07f0...`, result `8bc15644...`, report `163e14ac...`; five tests pass.

Treat this only as a distinct path coordinate. Next freeze
MKT-MIN-VOL-STATE-001 to test sign-state agreement with the two accepted
ordinal neighbors, recurrence across views/years, dwell, transitions, and
outcome-blind geometry with frozen daily volatility level. Do not access future
returns or strategy outcomes. Human input is not required; CY-011 stays unopened.

MKT-MIN-VOL-STATE-001 is frozen before result under spec `bf3c5e7a...`. Exact
sign/zero states are tested against both accepted ordinal definitions, with
fixed recurrence, agreement, run/dwell, transition-matrix, and daily-level
context gates. Dwell and transitions are post-state attribution only. Execute
twice; do not relabel a favorable subset as contraction/expansion.

MKT-MIN-VOL-STATE-001 fails exactly. Primary state recurrence and dwell support
pass, but definition-neighbor kappa is 0.425/0.275, macro-Jaccard 0.423/0.305,
and transition total variation 0.469/0.611. The fixed expanding-PIT level
context is also warm-up-limited in 2019-2020 and occupancy-sparse later. Two
runs are byte-identical: panel `d2b23700...`, result `296170ee...`, report
`49a884b5...`; five targeted tests pass.

Keep the continuous path; reject exact sign states and all discrete process/
contraction labels. Next freeze MKT-MIN-VOL-RESP-001: a strategy-independent,
continuous association with future 1/3/5-session minute-volatility change,
incremental to fixed current volatility controls and with confirmation time
untouched before specification. No market-return or strategy outcome is needed.

MKT-MIN-VOL-RESP-001 is frozen before forward construction under spec
`595f2ec5...`. It binds geometry panel `8cbe07f0...` and daily minute panel
`bdbb3cb9...`; h=5 is primary, h=1/3 mandatory neighbors; 2019-2021 is discovery
and 2022-2023 untouched confirmation. Partial rank after five fixed controls and
fixed phase-zero h=5 non-overlap are primary evidence. Execute twice without
reading price returns, strategy outcomes, raw minutes, or CY-011.

Pre-result tests found the valid 2020-02-03 minute-volatility median is exactly
zero in all eight groups, so RESP-001's log ratio had an undeclared domain case.
It is invalid before response construction; confirmation remains unread.
MKT-MIN-VOL-RESP-002 control spec `9ef7a0b2...` is frozen. It makes only affected
log responses/control values missing, forbids epsilon/clipping/imputation, and
keeps every coverage/effect/sign/validation gate unchanged. Execute the exact
retry twice.

MKT-MIN-VOL-RESP-002 is complete and fails. Primary h=5 partial rho is only
-0.017 in discovery and -0.015 in untouched confirmation; fixed non-overlap is
-0.005/-0.019. h=1 flips from +0.033 to -0.092 and h=3 weakens from +0.060 to
+0.010. Raw negative associations are not incremental after the five controls.
Two runs are byte-identical: panel `f0ca6162...`, result `e9f1245c...`, report
`fb89e0c1...`; five tests pass.

Do not rescue a horizon, raw association, group, or state. Retain the continuous
path as descriptive only. SYNTH-MKT-014 moves to MKT-INDRS-001 map-first:
industry leadership/diffusion/persistence/rotation plus stock-versus-industry
and industry-versus-market relative strength, without reproducing the failed
MA20 industry-diffusion representation or reading outcomes/CY-011.

MKT-INDRS-001 is frozen before construction under spec `e49f2098...`. It binds
the exact six CY-006 partitions and accepted 120-step action-aware core, causal
industry membership, five-member/80%/ten-industry gates, eleven distinct roles,
exact leave-one-out industry medians, fixed neighbors, three coordinate
families, external breadth controls, and serial determinism. No MA20 diffusion
clone, outcome, strategy field, or CY-011 may enter.

## Industry/relative-strength result

MKT-INDRS-001 completed on 10,696 view/denominator/date rows from 2018-07-03 to
2023-12-29. Valid output rows have 100% causal industry mapping and at least 37
included industries. An independent bounded audit reconstructs 1,988 exact
other-member medians with maximum difference zero. Two complete serial runs are
byte-identical: panel `c9e8d449...`, result `578d9dba...`, and report
`60ed7ef7...`; ten focused breadth/industry tests pass.

Eight roles pass: equal-industry positive participation, equal-industry return
depth, industry return dispersion, winner-industry diffusion, rank rotation,
and three leave-one-out stock/industry residual roles (dispersion, tail balance,
and positive-mass concentration). Return depth correlates 0.980 with positive
participation, so the minimal panel retains participation and six other roles.

Three exact roles fail without rescue. Industry-vs-market depth has a weakest
neighbor rho of 0.660. Positive-mass industry leadership concentration has only
0.945 minimum definable coverage because an all-nonpositive industry cross-
section has zero positive-mass denominator. Top-set persistence has weakest
neighbor rho 0.540 and ALL_STATUS/NON_ST median rho 0.895. Do not select a
favorable mean/quantile, top-k, lag, denominator, view, or year; do not impute a
zero denominator.

Absolute coordinates retain same-session economic meaning across years. Causal
expanding/trailing percentiles and robust z-scores are constructed only after
the frozen 504-observation history. Relative coordinates preserve governed-view
differences/ranks separately; stock-versus-industry residuals use exact leave-
one-out medians, never inclusive industry context. These are state
representations, not temporal persistence, alpha, timing, habitat, or strategy
evidence.

SYNTH-MKT-015 answers both mandatory questions. Major unstudied behavior still
includes broader-engine redundancy of the seven roles, their future temporal
meaning, size/style leadership, objective support/acceptance, accumulation/
distribution, and portable multi-strategy habitats. No genuinely new archetype
emerged: industry rotation and relative-strength leadership remain search-space
candidates because no future process, trigger, execution, exit, capacity, or
outcome evidence exists.

The highest-information-value next question is MKT-INDRS-GEO-001: outcome-blind,
role-specific geometry against accepted direction, breadth, correlation/
liquidity, volatility, risk-appetite, and leadership controls. Freeze that map
and spec before construction, then test pairwise redundancy and conservative
joint rank reconstruction. Temporal outcomes, strategy fields, failed industry
roles, failed MA20 fields, and CY-011 remain prohibited.

That map and spec are now frozen under SHA-256 `33b0f114...`. The seven control
sets contain at most three accepted economic alternatives each and are not a
search pool. Raw/relative cells use 2019-2023; complete causal-PIT cells use
2021-2023; all keep the 150-observation gate and the full 10,696-row key set.
Pairwise median absolute Spearman must remain below 0.85, while fixed-control
joint rank reconstruction must remain below 0.70 median and 0.85 maximum
adjusted R2 in every eligible coordinate family. Execute twice and preserve any
redundancy as latent-mechanism evidence rather than a failed source role.

The MKT-INDRS-GEO-001 coverage audit invalidated the first preregistration
before any geometry. The accepted leadership/discovery-imbalance control is
itself built after a 504-observation causal-percentile warm-up: it has no 2019
values and only 107/group in 2020. Its own PIT percentile imposes a second
warm-up and has only 89/group in 2022. No 001 output artifact exists.

MKT-INDRS-GEO-002 is frozen under control spec `7b91844c...`, inheriting the
exact scientific design `33b0f114...`. Only the nested control's eligible years
change: raw/relative 2021-2023 and PIT 2023, with winner-diffusion joint models
using the fixed-control intersection. No gate is lowered and no control is
dropped. Execute the retry twice.

MKT-INDRS-GEO-002 completed on the unchanged 10,696-row population. Five roles
remain direct engine coordinates: industry return dispersion, winner-industry
diffusion, rank rotation, stock/industry residual tail balance, and residual
positive-mass concentration. Their largest pairwise median absolute rhos are
0.568, 0.193, 0.203, 0.485, and 0.345; their largest joint median adjusted rank
R2 values are 0.350, 0.038, 0.045, 0.294, and 0.188.

Equal-industry participation is a central-direction manifestation (raw/PIT rho
0.978/0.976; joint adjusted rank R2 0.958/0.952). Leave-one-out residual
dispersion is jointly reconstructable from co-movement and volatility (PIT
0.773; relative-to-ALL_A 0.757). Preserve both as representation evidence but
do not count them as direct mechanisms or remove controls to promote them.

Two final runs are byte-identical: panel `7954dc81...`, result `9b3eaa0d...`,
report `bba6a6ae...`; sixteen focused tests pass. No future value, market
return, strategy outcome, failed industry role, failed MA field, or CY-011 was
read. This establishes contemporaneous engine compression only.

SYNTH-MKT-016 again answers the mandatory questions. Recurring temporal
leadership migration, future residual-tail meaning, size/style leadership,
support/acceptance, accumulation/distribution, and portable multi-strategy
habitats remain unstudied. No new archetype emerges: distinct winner diffusion
and rank rotation still lack future direction, trigger, execution, exit,
capacity, and return evidence.

Next freeze MKT-INDRS-DYN-001. Its narrow outcome-blind temporal graph should
test current winner diffusion and rank rotation against next nonoverlapping
five-session leadership states after fixed current controls, with discovery and
untouched-confirmation blocks, purged overlap handling, response availability,
effect/sign replication, and no-rescue rules declared before future values are
constructed.

That temporal map and spec are now frozen under SHA-256 `b1266eed...` before
any future value is shifted. The exact edges are rotation persistence,
winner-diffusion to next-block rotation, and rotation to five-session winner-
diffusion change. Each uses three fixed current controls. Discovery is
2019-2021 and confirmation is untouched 2022-2023; predictor and t+5 response
must both lie in the block. Raw/PIT/relative replication, group sign support,
phase-zero nonoverlap, minimum effect, and no-rescue gates are fixed. Execute
twice without market returns, stock selection, strategies, or CY-011.

MKT-INDRS-DYN-001 completed with one of three exact edges. Rotation persistence
passes every gate: raw partial rho 0.250 discovery/0.221 untouched confirmation,
PIT 0.216/0.244, and phase-zero 0.220/0.161; all eight raw/PIT and both relative
groups support the positive sign. Diffusion-to-rotation collapses from 0.246 to
0.008 confirmation. Rotation-to-diffusion change reverses from 0.033 to -0.235.
Both cross-edges are rejected without favorable-block rescue.

Two runs are byte-identical: panel `3aba96f1...`, result `10930928...`, report
`ed31dc93...`; sixteen focused tests pass. The 2022-2023 confirmation block is
now consumed for these exact edges, not for any future replication definition.
No market/stock return, selection, strategy, failed role, or CY-011 was read.

SYNTH-MKT-017 finds no new archetype. Immediate rotation clustering is a
supported state edge, but adjacent blocks share the rank snapshot at t and the
20-session return ranks are smooth. Next freeze MKT-INDRS-ROT-001 with exactly
three falsifications: delayed t+10 primary rotation with no shared endpoint,
next-block Kendall persistence, and next-block mean-rank-displacement
persistence. Require all; do not add horizons or outcomes.

## Human decision required?

No. No S1-S12 STOP is active. Continue autonomously with MKT-INDRS-ROT-001
frozen execution; CY-011 remains locked and unopened.

## MKT-INDRS-ROT-001 frozen continuation

The delayed/alternate-definition falsification map and spec are frozen under
SHA-256 `1af3e49717f5055deb2b7ac6bc95e191b6eaee749fc477d646997acac176610e`
before any new response is shifted. Execute only delayed t+10 Spearman,
next-block Kendall, and next-block displacement persistence; every replication
must pass. Use the same three current controls and exact raw/PIT/relative gates.

MKT-INDRS-DYN-001 already consumed both 2019-2021 and 2022-2023, and the new
hypotheses were generated afterward. Label every estimate
`CONSUMED_EXPLORATORY_FALSIFICATION_NOT_CONFIRMATION`; a pass still requires
independent future time. Do not read post-2023 data, market/stock returns,
strategy fields, failed roles, or CY-011.

## MKT-INDRS-ROT-001 result and next frontier

The all-required falsification fails. Delayed non-shared-endpoint Spearman has
raw partial rho 0.023/-0.111, PIT 0.052/-0.071, and phase 0.051/-0.089 in the
two consumed blocks. Adjacent Kendall and displacement pass at raw 0.262/0.212
and 0.266/0.207, but cannot rescue the delayed reversal. Two runs are
byte-identical: panel `37043081...`, result `fe536b7e...`, report `744727e9...`.

Do not add another rotation horizon, block, definition, control deletion, or
favorable subset. Immediate adjacent clustering remains descriptive; the broad
rotation-persistence mechanism and any rotation archetype are not established.
Next continue map-first with MKT-INDRS-TAIL-DYN-001 on residual tail balance and
concentration. Freeze a small state-only graph and its controls before shifting
future values. Market/stock returns, strategies, post-2023 data, and CY-011
remain prohibited.

The MKT-INDRS-TAIL-DYN-001 map and spec are now frozen under SHA-256
`56a83827c7ba0bea69d611f6d0ec8778a3364cb2c14d62d444e230d839fb5bca`
before future states are shifted. Execute exactly four positive t+20 edges:
two nonoverlapping self-persistence edges and both directional cross-edges.
Use the response role's fixed broad controls; cross-edges also control its
current state. Self-processes stand separately and coupling requires both
cross-edges.

Both time blocks are reused pre-2024 exploratory evidence, not untouched
confirmation. Preserve the 20-session phase stride, all coordinate/support/
sign gates, and the no-rescue rule. Do not read returns, future security
identities, strategy fields, rejected roles/edges, post-2023 data, or CY-011.

## MKT-INDRS-TAIL-DYN-001 result and frontier pivot

Zero of four exact t+20 edges passes. Tail-balance persistence is raw
0.102/0.055 but PIT -0.049/-0.058. Residual-concentration persistence decays
from raw 0.234 to 0.061 and PIT 0.309 to -0.020. Concentration->tail balance
reverses 0.186 to -0.265; tail balance->concentration reverses 0.109 to -0.218.
No self-process or coupled process freezes.

Two runs are byte-identical: panel `4d4fc15a...`, result `2e24894a...`, report
`965e17a0...`. Preserve the stable same-session coordinates, but do not tune the
t+20 horizon, choose a favorable coordinate/block, or form an industry/relative-
strength archetype. Next map MKT-VOL-TRANS-001: continuous daily-volatility
contraction/expansion transition architecture conditional on accepted direction
and discovery breadth, outcome-blind and before any strategy study. CY-011
remains locked.

MKT-VOL-TRANS-001 is now frozen under SHA-256
`21145136eeb09369b755aad7fca591dcd280e3577159d7c65c5c1362bdacbb43`
before shifting future volatility state. Use exactly the t+25 response; its
complete source span shares no return interval with the current transition.
Estimate the baseline after three fixed current-volatility controls in all four
coordinate systems.

Test direction and discovery modifiers only through the frozen causal-PIT
50/50 primary split and 40/60 shape neighbor, in raw and PIT transition
coordinates. Preserve all six direction indices and all eight discovery groups;
do not select a favorable habitat. Baseline and modifiers stand independently.
Both blocks are reused exploratory evidence, never confirmation. Future price
returns, strategy fields, failed roles, post-2023 data, and CY-011 are forbidden.

MKT-VOL-TRANS-001 is invalid before accepted estimation: one block-A direction
PIT cell had 123 observations versus the unchanged 150 gate. No 001 output
artifact exists and no effect may be cited.

MKT-VOL-TRANS-002 is frozen under control-spec SHA-256
`e04c720b8980be9bd69e01e442ee09db86ab1fab6b89d5ae0093f57f31a8138f`,
inheriting scientific spec `21145136...`. Only direction grouping changes:
pool all four governed views within each index/denominator, take the two-
denominator median per index, then summarize all six indices. Discovery remains
eight matching cells. Run every support audit before correlations. No threshold,
split, horizon, control, block, or claim is changed.

MKT-VOL-TRANS-002 is also invalid before accepted estimation: its complete
audit found a block-A discovery raw cell with 127 observations versus 150. No
002 output exists.

MKT-VOL-TRANS-003 is frozen under control-spec SHA-256
`a90dd17f7ae861a4627e9f6ccd2c78ba5edcade7393e2f4af6281249057e73e1`.
Direction retains all-view pooling within index/denominator. Discovery pools
both denominators within each view, retains all four views, and uses three-of-
four sign support, preserving 75%. Run the full support audit before any
correlation. All scientific semantics and gates remain inherited from
`21145136...`.

MKT-VOL-TRANS-003 completed support and estimation but failed report
serialization on a hash-key alias. Its partial files are unaccepted and no 003
effect was inspected or cited.

MKT-VOL-TRANS-004 is frozen under SHA-256
`e2859b62539f12c5112bd3bbb845c7d47695fbfd104bd3f126552ba231ccc9cb`.
It inherits scientific spec `21145136...` and final control spec `a90dd17f...`.
Only expose the existing scientific hash as `hashes.spec_sha256` and write 004
outputs. Rerun the exact estimator twice; no research decision or gate changes.

MKT-VOL-TRANS-004 completes with zero of three claims. Baseline raw partial rho
is 0.051/0.094; relative signs conflict and block-B phase is -0.275. Direction
modification is 0.004/0.340 raw, so block A fails. Discovery modification is
0.194/0.064 raw and 0.192/0.075 PIT, so block B fails. No favorable block,
coordinate, or 40/60 neighbor rescues a primary.

Two runs are byte-identical: panel `cfc44d72...`, result `498173ac...`, report
`33794b78...`. Preserve daily-volatility representation evidence but do not
tune the transition horizon or habitat split. Next map MKT-MIN-SUPACC-001 using
only frozen same-session market minute levels to represent objective support
defense, VWAP acceptance, and accumulation/demand. Do not reuse rejected OLS,
ordinal, reversal, or curvature paths; do not read outcomes or CY-011.

MKT-MIN-SUPACC-001 is now frozen under SHA-256
`fcdc9d359a153ba473543ee7ccfabb6f7ed68a4c37fca34a5a2b3e4f60be9435`
before constructing mechanism scores. Use only the 12 fixed accepted components
and three controls from the required-scale daily panel. Preserve 15:30 derived
availability, causal 756/504 percentiles, fixed signs, mean primary,
median/geometric and four leave-one-out neighbors, p40/p60 definitions, PIT/
relative coordinates, and external/joint redundancy gates.

Do not read raw minutes, future values, outcomes, failed level/path fields, or
CY-011. Do not call these cross-day support/resistance or participant
accumulation. Execute twice and compress redundant passing mechanisms only in
the frozen priority order.

MKT-MIN-SUPACC-001 completes with one of three minimal engine dimensions. All
three composites pass their internal construction, aggregation, leave-one-out,
p40/p60, denominator, coverage, and coordinate gates. Internal stability alone
does not establish a causal mechanism.

Only `vwap_defense_recovery` passes external geometry: maximum pairwise PIT rho
0.764; joint adjusted R2 0.588 median/0.607 maximum in PIT and 0.109/0.111 in
relative space. `late_vwap_acceptance` is jointly reconstructable at the frozen
PIT boundary (0.701 median adjusted R2). `price_volume_demand_balance` is mostly
open-to-close return (PIT rho 0.914; joint adjusted R2 0.916). Preserve both as
descriptive manifestations, but do not count them as independent mechanisms.

Two runs are byte-identical: panel `b08abaab...`, result `b09808a9...`, report
`e070f9a9...`; five focused tests pass. The accepted coordinate is a completed-
session, 15:30-available representation only. Do not call it cross-day support,
participant accumulation, supply exhaustion, future persistence, a signal, or
a strategy habitat.

SYNTH-MKT-021 selects MKT-MIN-DEF-DYN-001 map-first. Test the temporal meaning
of the sole distinct same-session defense/recovery coordinate using future
market-state values only, with nonoverlap, controls, fixed horizons/blocks, and
no favorable-coordinate rescue frozen before shifting. Do not read future
price returns, strategy fields, raw minute rows, failed roles, post-2023 data,
or CY-011.

MKT-MIN-DEF-DYN-001 is frozen under spec SHA-256
`b53452c922eff99ac9d8a367dc905b00b08335beec337e8507144b686423ecee`
before future shifting. The primary asks whether the exact accepted score at t
predicts the same state at t+1 after current open-to-close return, downside
realized volatility, and minute-volume concentration. h=3 and h=5 are fixed
non-rescuing neighbors.

At h=1 also challenge median/geometric aggregation, p40/p60 cross sections,
relative-to-ALL_A, and governed-view relative rank. Use the fixed 2020-2021 and
2022-2023 reused blocks; learn sign in block A and require replication in block
B. All gates are conjunctive. Do not reinterpret either block as untouched
confirmation or use an unadjusted estimate to rescue the partial estimator.

The source minute/PIT contract and 15:30 availability remain inherited. Read
only future values of the accepted dimensionless defense/recovery state. Future
price return, future volatility/industry/stock state, strategy fields, failed
roles, raw minutes, post-2023 data, and CY-011 remain forbidden. Execute twice.

MKT-MIN-DEF-DYN-001 completes with `COMPLETE_STATE_DYNAMIC_FAIL`. The h=1
primary is -0.035 partial rho in reused 2020-2021 and +0.005 in reused
2022-2023; its unadjusted values are -0.044/-0.016. The effect, sign,
cross-block magnitude, and sign-support gates fail.

h=3 is 0.004/-0.058 and h=5 is 0.024/0.046. Neither can rescue h=1 and neither
forms an all-block delayed dynamic. All four h=1 aggregation/cross-section
challenges miss the fixed effect gate in at least one block; relative-to-ALL_A
is 0.008/-0.009 and relative rank -0.004/-0.007. All support/nondegeneracy audits
passed before correlations.

Two executions are byte-identical: panel `bfb22ae1...`, result `77812c79...`,
report `823bc6bd...`; six focused tests pass. Preserve VWAP defense/recovery as
a same-session representation only. Do not tune horizon, choose a shape, infer
cross-day support/accumulation, or construct a signal.

SYNTH-MKT-022 selects MKT-STYLE-001 data-contract/map-first. Determine whether
registered PIT daily data can support strategy-independent size/style
participation, leadership concentration, diffusion, divergence, and transition
representations. Fail closed on unclear market-cap/free-float/industry lineage.
Do not combine style with Trend/Breadth or read strategy outcomes before a
defensible representation exists.

MKT-STYLE-DATA-001 is frozen under SHA-256
`506c24bcdd498162b3d44faa3008aa54ddf9a4132606b5da9a890240e224484b`
before calculating circulating market value. Bind exact CY-006/QD-009 registry,
audit, manifest, and six 2018-2023 partition identities. Audit every
hard-valid component and float-lineage date before accepting the product.

The only candidate coordinate is raw completed close times causal
`circulating_shares`. Call it circulating market value, never total market cap,
true free-float cap, or enterprise value. QD-009 `freeFloatCapital` is not
exposed by CY-006 and must not be joined separately. Enforce 15:00 availability,
turnover unit consistency, population minimums, and the frozen no-rescue rule.
No future/adjusted price, strategy field, post-2023 data, or CY-011 may enter.

MKT-STYLE-DATA-001 completes with `COMPLETE_DATA_CONTRACT_PASS`. The exact
6,155,390-row source has zero duplicate, time-travel, hard-valid component,
float-lineage, circulating-value, turnover-unit, or decision-time failures.
Every view/denominator clears its population floor on all 1,457 dates.

Circulating market value is CNY 218.8 million minimum, CNY 4.042 billion median,
and CNY 3.267 trillion maximum. Two runs are byte-identical: result
`a03954d6...`, report `7c1511fd...`; four focused tests pass. Preserve the
semantic boundary: this is circulating-market-value size only, not total cap,
true free-float cap, enterprise value, growth/value, or beta.

SYNTH-MKT-023 selects MKT-STYLE-001 deep representation mapping before
construction. Separate size participation, small/large leadership, diffusion,
concentration, divergence, and transitions; retain absolute, causal-PIT, and
relative views. Use lagged size membership for current return attribution and
avoid current-close sort leakage. Freeze neighboring bucket/horizon definitions,
coverage, portability, redundancy, and no-rescue gates before estimates.

MKT-STYLE-001 is frozen under SHA-256
`a32ca8fcdb6080beb97f4226a891c44270a46e9d0a4818d4132501fdc1a808a3`
before constructing buckets or roles. Attribute t returns using exact t-1
circulating-size ranks; current-close assignment is prohibited. Use 30/70
primary tails with 20/80 and 40/60 neighbors, three equal buckets for
diffusion/concentration, and five for curve divergence.

Construct all eight roles separately and preserve raw, causal-PIT/robust-z,
relative-to-ALL_A, and governed-view rank coordinates. Apply 95% coverage, 0.70
neighbor, 0.90 denominator, 150-observation year-cell, and 0.85 fixed-priority
compression gates exactly. Execute twice. Do not read future values, strategy
outcomes, total/free-float cap substitutes, post-2023 data, or CY-011.

MKT-STYLE-001 completes with six minimal roles: size structure, positive
participation balance, winner diffusion, positive-mass concentration, size-
curve divergence, and leadership transition. Every accepted role passes raw
coverage, neighboring-definition, denominator, year-cell, causal-PIT/robust-z,
and relative-coordinate gates.

One-day return spread is stable but compressed into participation balance at
rho 0.903. Twenty-day leadership fails the fixed 10/20/40 horizon family: its
10-day neighbor has median rho 0.683 and 40-day 0.634. Do not select 10/20/40,
retune the horizon, or count the one-day spread separately.

Two valid single-thread runs are byte-identical: panel `5ed52618...`, result
`134dc205...`, report `4da04ee0...`; five focused tests pass. The earlier empty-
small-bucket partial run and multithreaded 1e-15 hash divergence are invalid
engineering attempts and provide no research evidence.

SYNTH-MKT-024 selects MKT-STYLE-GEO-001 map-first. Before temporal or economic
usefulness, test each of the six size roles against role-specific accepted
market direction, breadth, volatility, liquidity/co-movement, and leadership
alternatives. Freeze pairwise and fixed-control joint reconstruction in raw/PIT
and relative space; do not remove a control to promote a size role or combine
roles into a trading rule.

MKT-STYLE-GEO-001 is frozen under SHA-256
`2bf960c60d5fffcb98bb9442c2d05eb91859b91002baf69eab69b2b98bb6d7c8`
before correlations or regressions. Preserve the exact role-specific three-
control sets from the map. Every control is an accepted representation or a
direct industry coordinate surviving prior external compression.

Complete all 2021-2023 raw/PIT/relative group-year support and nondegeneracy
audits first. Then apply pairwise rho <0.85 and joint rank reconstruction below
0.70 median/0.85 maximum in all four coordinates. Do not delete a control,
select a coordinate/view/year, or use a failed/duplicated size role. Execute
twice without future values, strategy outcomes, post-2023 data, or CY-011.

The MKT-STYLE-GEO-001 support audit stopped before estimates. The relative-rank
coordinate is defined across the four views on each date, but 001 audited it as
a time series inside one view. The first cell, size structure in
ALL_A/ALL_STATUS/2021, contained 243 complete observations but constant ranks:
size 0.75, turnover 0.50, and realized volatility 0.50. The unchanged
nondegeneracy rule correctly failed closed. No 001 output artifact exists and
this is not evidence against any size role.

MKT-STYLE-GEO-002 is frozen under SHA-256
`9860c89319122a920bef848f08d92a8882cf9f644f5a8174768e297c73f7e36a`.
It inherits every role, control, input identity, year, threshold, coordinate,
prohibition, and claim boundary. The only correction estimates relative rank
across the four same-date views: require 150 complete, cross-sectionally
nondegenerate dates per denominator/year; summarize daily cross-view Spearman;
and use date-demeaned joint within-R2. Execute the exact retry twice. No future
value, strategy outcome, post-2023 data, or CY-011 may enter.

MKT-STYLE-GEO-002 completes on 10,696 rows. Five roles remain direct engine
coordinates: positive participation balance, winner diffusion, positive-mass
concentration, size-curve divergence, and leadership transition. Their largest
joint median/maximum adjusted rank R2 values are respectively 0.185/0.226,
0.026/0.061, 0.025/0.028, 0.219/0.278, and 0.057/0.062. Largest pairwise median
absolute rho is 0.800, arising from the coarse four-view rank coordinate.

Size structure fails conjunctive external distinctness. Across governed views,
its rank ordering is identical to turnover, liquidity amount concentration, and
realized volatility: pairwise rho 1.000 for all three and joint adjusted within-
R2 1.000. Preserve it as a stable descriptive manifestation, not a direct
mechanism. Minimum corrected rank support is 240 dates versus the unchanged 150
gate.

Two final runs are byte-identical: panel `a55fa57c...`, result `4294a7bd...`,
report `50d78e23...`; ten focused tests pass. No future value, strategy outcome,
failed role, post-2023 field, or CY-011 was read. SYNTH-MKT-026 selects
MKT-STYLE-DYN-001 map-first: test whether the accepted five-session leadership-
transition coordinate has a replicating nonoverlapping future state dynamic,
with 3/10-session definitions as fixed neighbors. Freeze all responses,
controls, blocks, phase samples, coordinates, and gates before shifting a future
state. Do not read market payoff or form a size-rotation rule.

MKT-STYLE-DYN-001 is frozen under SHA-256
`150de73b4a6c3c56027d61e63791636ede2c75e9e57785f7981263290a53a3e7`
before any future-state shift. The accepted five-session transition and its
t+5 response use disjoint daily size-return components. Three/ten-session raw
transition definitions are fixed non-rescuing neighbors.

Partial-rank estimators use only current positive participation, size-curve
divergence, and realized-volatility change. Preserve raw/PIT/relative-to-ALL_A,
corrected date-fixed-effect four-view ranks, reused 2021 versus 2022--2023
blocks, phase-zero sampling, effect/sign/support gates, and the all-required
rule. Execute twice without future market payoff, stock selection, strategy
outcomes, failed size roles, post-2023 data, or CY-011.

MKT-STYLE-DYN-001 completes with `COMPLETE_STATE_DYNAMIC_FAIL`. The primary raw
partial rho is 0.179 in reused 2021 and only 0.053 in reused 2022--2023; PIT is
0.181/0.055. Raw three-session and ten-session definitions decay from
0.148/0.130 to 0.058/0.049. The primary phase-zero sample reverses from +0.181
to -0.078.

Relative-to-ALL_A rises from 0.077 to 0.187 and corrected relative rank from
0.022 to 0.188, but the all-required design forbids favorable-coordinate rescue.
Thirty-five of 43 checks pass; all support/nondegeneracy gates pass first. No
recurrence or reversal label freezes.

Two runs are byte-identical: panel `067d1657...`, result `9405263f...`, report
`101dc3de...`; five focused tests pass. No future market payoff, stock selection,
strategy outcome, failed size predictor, post-2023 field, or CY-011 was read.
SYNTH-MKT-027 selects one bounded map-first precursor edge before leaving the
style frontier: accepted current positive-participation balance to future
accepted T5, controlling current T5 and fixed current market/size state. Do not
add another edge or interpret the failed self-process as a size-rotation rule.

MKT-STYLE-PART-DYN-001 is frozen under SHA-256
`5cffae1f3e2a74ae3eb1db53041a4bf93f0ea79ef17ec52c31f5984c95d9fc42`
before response construction. The single primary is current accepted small30-
minus-large30 positive participation to future accepted T5. Small20/large20 and
small40/large40 are raw predictor-definition challenges only.

Control exactly current T5, current size-curve divergence, and current broad
central direction. Preserve reused 2021 versus 2022--2023 blocks, all four
primary coordinates, corrected date-fixed-effect rank estimation, phase-zero
sampling, and the frozen effect/sign/support architecture. Execute twice. Do not
add diffusion/concentration edges, read payoff or strategy outcomes, use post-
2023 data, or open CY-011.

MKT-STYLE-PART-DYN-001 completes with `COMPLETE_PRECURSOR_FAIL`. Primary raw is
+0.032/-0.033 across reused blocks; PIT +0.032/-0.036; relative-to-ALL_A
+0.010/-0.036; corrected rank -0.013/+0.014. Both raw tail-definition neighbors
are about +0.033 in block A and reverse to -0.027/-0.036 in block B.

Phase-zero is +0.147/+0.099, but it is a non-rescuing sparse phase diagnostic:
the full primary misses effect and sign gates, and every definition/coordinate
challenge fails. Eighteen of 43 checks pass; all support and nondegeneracy gates
pass before estimates. No precursor freezes.

Two runs are byte-identical: panel `601bbcfc...`, result `da197687...`, report
`d3d6cd27...`; five focused tests pass. No future payoff, stock selection,
strategy outcome, additional edge, failed size predictor, post-2023 field, or
CY-011 was read. Close the exact style temporal branch without another edge or
horizon. SYNTH-MKT-028 selects MKT-SUPPORT-DATA-001 map-first: establish exact
PIT, corporate-action-coordinate, prior-level, minute-timestamp, and support-
test feasibility before defining any market-wide objective support defense.

MKT-SUPPORT-DATA-001 is frozen under SHA-256
`3d86cb04a1bfaecbcc43621115edf8a3838d7bd19e717e53c07e9360469e426a`
before new QD-004 access. It binds exact registry/calendar/QD-004/CY-006/CY-008/
QD-010 identities, the accepted 1,200-session minute sample, and the established
action-coordinate/minute-adapter implementations.

Audit prior 10/20/40 adjusted daily lows through t-1 and map the exact raw t
minute path into the same causal cash/share coordinate. Rights, blocking or
unresolved actions, invalid chain steps, incomplete grids, daily/minute close
disagreement, time travel, and population shortfalls all fail closed. Add exactly
five hash-selected supported action sessions per year without inspecting minute
behavior. The output is data feasibility only, available at 15:30; no support,
recovery, accumulation, payoff, strategy, or CY-011 claim is allowed.

MKT-SUPPORT-DATA-001 is invalid before minute-coordinate construction. Full
partition hashes passed first, as did all 11,336 full-population cells with a
minimum margin of 426. The first target failure is `603232.SH` on 2019-06-10:
the blocking/hard-invalid 2019-05-30 action row leaves only 40/41 valid history
rows and 38/40 valid coordinate steps.

Thirty-seven of the reused accepted sessions are coordinate-ineligible. Seventeen
are recent listings with fewer than 41 available rows; twenty span an invalid or
blocking action row. The failures cover eight symbols and occur 5/5/7/20 times
in 2019/2021/2022/2023. The frozen no-replacement rule stopped the audit before
reading QD-004 rows, so no output artifact or scientific estimate exists. This
is a sample-contract failure, not evidence against the causal coordinate or
support-defense family. The exact retry must preselect complete five-session
cohorts from CY-006 coordinate eligibility only, preserving fixed dates/views,
hash ordering, action challenges, full-population gates, and all no-rescue
boundaries before any minute access.

MKT-SUPPORT-DATA-002 is now frozen under SHA-256
`79ec5129deddb2add59731a44bfa40b95bcbad827022bc61440f1b778b7ff689`.
It preserves the six exact date blocks/four views and preselects ten complete
five-session symbol sequences per year/view using only CY-006 eligibility and a
fixed hash. It preserves the independent five-action/year challenge and every
coordinate, minute, lineage, population, availability, no-rescue, prohibited-
input, and claim gate. Execute before constructing a support representation.

MKT-SUPPORT-DATA-002 is invalid at the first source-close equality gate. The
first row is `000090.SZ`/2018-06-08: QD-004 stores 8.520000457763672 while CY-006
stores 8.52. A complete target diagnostic found 1,161 bitwise and 39 exact-cent
differences among 1,225 unique sessions; all cent differences are 2018 Shanghai,
with a seven-cent maximum. No 002 output exists.

This is not a minute-grid, action-coordinate, or lineage failure. CY-008 does
not promise equality between the independent minute final bar and official
daily close; it promises internal minute OHLC and volume/amount reconciliation.
The causal scale `coordinate_close/daily_close` can map every observed QD-004
bar without substituting its final close. Freeze that source-role correction as
003, retain disagreement diagnostics, and do not add a tolerance or replace a
sample row.

MKT-SUPPORT-DATA-003 is frozen under SHA-256
`7a734dd94bd61f2bc52578c6a8706edde637b23d3f5636b4877b7e13ca931b6f`.
It inherits the exact 002 sample and every non-equality gate. CY-006 supplies
`coordinate_close/daily_close`; every QD-004 OHLC is multiplied by that scale
without substitution, rounding, clipping, or a forced final-close identity.
Complete binary/cent/raw-difference diagnostics are mandatory but do not select
or alter rows. Execute twice before any support representation claim.

MKT-SUPPORT-DATA-003 passes the complete contract. It audits 1,230 cohort rows
covering 1,225 unique sessions, exactly 30 supported actions, and 11,336/11,336
population cells with minimum margin 426. There are zero mapped-price,
nonfinite, rights, or blocking-action failures. It observes 118 primary level
tests, but this count has no defense or usefulness meaning.

Source disagreement remains visible: 1,161 binary and 39 exact-cent close
mismatches, with a seven-cent maximum; all cent mismatches are 2018. Two full
content-verified runs are byte-identical: sample `c1eb0cbc...`, coordinate
`ef08a242...`, population `823aebae...`, result `072fa454...`, report
`29bb9d29...`. Fifteen focused tests pass. The next frontier is map-first
MKT-SUPPORT-001 representation quality, not payoff: distinguish opportunity,
penetration, duration, recovery speed/volume, closing recovery, repeated tests,
and five-session trajectories with fixed 10/20/40 neighbors.

MKT-SUPPORT-001 is frozen under SHA-256
`4c58431daa1a21268eedcb8d6ebc306aadfb4aac89f8c9218e956fc91e36bef4`.
It distinguishes opportunity/penetration, duration, recurrence, closing state,
and conditional recovery speed/amplitude/volume. Primary continuous-session
20-day levels face 10/40-level and auction-inclusive challenges. Five-day slopes
face endpoint/ordinal shapes; repeated-test frequency is separate. The known 29
conditional recovery sequences cannot pass the unchanged 30-sequence floor and
cannot be rescued by near-touch bands or neighbor definitions. Execute twice;
no payoff or support-defense claim is permitted.

MKT-SUPPORT-001 completes with four direct session roles: signed test geometry,
conditional recovery speed, recovery amplitude, and recovery-volume intensity.
Primary support is 117 tested market rows, including 104 recoveries and 13
nonrecoveries. Time-below and test recurrence fail cross-level/auction cell
gates. Closing level state passes but compresses into signed geometry at rho
0.947 globally/0.904 median cell.

Signed-geometry and closing-state five-day trajectories pass all fixed shape
gates; time-below/recurrence fail ordinal coverage. Conditional recovery
trajectory is not estimated at 29 versus the unchanged 30-sequence floor. Five
distinct manual cases match all seven independently reconstructed fields.

Two runs are identical: session `501194a7...`, trajectory `668005f7...`, result
`cbb3f3a6...`, report `41a99062...`; five tests pass. This is representation
quality only. Next map role-specific external controls for daily support
distance/range/close location and ordinary minute path/volatility/activity to
determine which roles are genuinely support-specific.

MKT-SUPPORT-GEO-001 is frozen under SHA-256
`c828ed0e73a652ff6979067712fbd293e43f553e4dd3683e358db06504552ba1`.
Each role has fixed daily/minute alternatives and unchanged domains. Raw and
relative geometry are required for unconditional roles; conditional roles use
raw full plus 2018--2020/2021--2023 blocks with 30-row floors. Pairwise rho
0.85 and joint adjusted-rank R2 0.70 full/0.85 maximum are strict boundaries.
Execute twice without deleting controls or reading future/payoff fields.

MKT-SUPPORT-GEO-001 completes and retains only recovery speed and recovery-
volume intensity as externally distinct conditional observations. Their full
adjusted rank R2 values against all fixed generic controls are -0.029 and 0.152;
maximum fixed-block values are -0.004 and 0.373. All pairwise gates pass.

Signed test geometry and its five-day slope collapse almost exactly into
official daily-low distance and its slope. Closing-state slope collapses into
official daily-close-distance slope. Recovery amplitude is jointly reconstructed
by daily range, minute close location, and minute return (full/block adjusted R2
0.903/0.921/0.892). Do not delete controls or count these as direct minute
support mechanisms.

Two complete content-verified runs are byte-identical: session `6b44079e...`,
trajectory `34348e11...`, result `ba3fbfd3...`, report `b60512eb...`; ten focused
support/geometry tests pass. This establishes fixed-control external geometry
only. It does not establish defense, temporal recurrence, prediction, payoff,
timing, habitat, or a strategy, and no future field or CY-011 was read.

SYNTH-MKT-033 deepens only the two surviving recovery roles. The next action is
map-first MKT-SUPPORT-DYN-DATA-001: freeze a larger calendar-distributed sample
selected from CY-006 coordinate eligibility only, before minute behavior is
read. It must support a falsifiable repeated-test/recovery dynamic without using
the current 29-sequence shortfall, near-touch bands, favorable dates, strategy
events, or outcome selection.

MKT-SUPPORT-DYN-DATA-001 is frozen under SHA-256
`cb6559ee585eef7fc147c1036bbd0cc81d4a8634b8d2aca339cfa10358a9b02d`.
Its 48 five-session blocks are selected solely by a March--November calendar
quantile operator; ten complete CY-006-eligible symbols per block/view are then
hash-selected. The immutable sample has 1,920 sequences, 9,600 cohort rows,
9,575 unique security-sessions, minimum 625 candidates per cell, and 38 selected
supported-action sessions before minute access.

Sample adequacy requires at least 120 repeated-tested sequences, 50 per fixed
temporal block and 15 per year; at least 100 must have two defined recovered
days, including 40 per block. Count only—no process estimate is allowed. The
planned 2,307,575 minute rows must stay below 20 GiB compressed reads, 3 GiB RSS,
8 GiB system headroom, 100 MiB durable output, and ten minutes. Execute twice;
no date/symbol/level/auction/near-touch/support-floor rescue is permitted.

MKT-SUPPORT-DYN-DATA-001 stops before its first newly selected QD-004 row. The
exact daily-coordinate build peaks at 11,135,991,808 bytes RSS with only
7,738,458,112 bytes headroom, violating 3 GiB/8 GiB. Exact SQL under a 2-GiB
DuckDB memory limit peaks at 2,698,985,472 bytes and preserves
12,885,016,576 bytes headroom, but its 8,787,951,616-byte live spill violates
001's 1-GiB temp cap. No 001 output or minute-derived count exists.

MKT-SUPPORT-DYN-DATA-002 is frozen under SHA-256
`2bcf7cbff24fd3be5a405a4051af942de396c65445296a5849acd9a77587cfc9`.
It inherits every 001 scientific identity and changes only the exact-SQL engine
to one thread/2-GiB memory plus a 10-GiB isolated disposable-spill cap. Spill
must be removed before QD-004 access. Execute twice; 3-GiB RSS, 8-GiB headroom,
20-GiB compressed read, 100-MiB durable output, and ten-minute limits remain.

MKT-SUPPORT-DYN-DATA-002 passes the capped daily phase but fails the 3-GiB
lifetime RSS guard during its first annual minute phase. The annual predicate
materializes 2,849,825 rows for 1,595 exact 2018 target sessions (384,395
required rows). A bounded diagnostic peaks at 4,344,119,296 bytes. No complete
002 output, support count, or process estimate is accepted.

MKT-SUPPORT-DYN-DATA-003 is frozen under SHA-256
`e8045eb3953f17c08e8e7324f0ea1f10e11c4c4206c16c591f65fca129824a68`.
It retains every 001/002 scientific and resource value and changes only the
minute read to exact five-session `(year, block_id)` batches. It requires
2,307,575 total raw rows and exact canonical-frame equivalence between parent
and candidate readers on 2018 block 1 before complete scale. Execute twice.

MKT-SUPPORT-DYN-DATA-003 still fails the 3-GiB lifetime RSS guard because the
inherited 2-GiB daily phase leaves too little margin for a block allocation. It
produces no complete output or accepted count. The exact 1.5-GiB measurement
plus first block records 2,144,124,928 bytes peak RSS, 12,700,811,264 bytes
available memory, and 9,155,805,184 bytes live spill.

MKT-SUPPORT-DYN-DATA-004 is frozen under SHA-256
`63c8a1f86dcf1e05e8f4284df3c1d9d2454c50dbc1f56e670b4a83090c35e6e2`.
It changes only the daily DuckDB memory limit from 2 to 1.5 GiB and inherits all
003 batching/reference and 001/002 scientific/resource gates. No further
resource rescue is allowed. Execute twice if the first complete run passes.

MKT-SUPPORT-DYN-DATA-004 passes. Reference and candidate calculations on the
first 2018 block are exactly equal at hash `5e0eaeba...`; all 48 blocks then
conserve exactly 2,307,575 raw rows. The audit covers 1,920 sequences, 9,600
cohort rows, 9,575 unique sessions, 38 naturally selected supported actions,
and 11,336/11,336 population cells.

Count-only adequacy passes with 315 repeated-tested sequences (133/182 fixed
blocks and 60/33/40/49/75/58 by year) and 269 twice-recovered sequences
(107/162 and 40/30/37/39/70/53). No trajectory/process estimate was built.
Two runs are byte-identical: sample `5a2ac522...`, coordinate `fb881921...`,
population `823aebae...`, counts `d00f1ec0...`, result `604f8640...`, report
`48f5eb5b...`; 30 focused tests pass.

SYNTH-MKT-034 selects MKT-SUPPORT-DYN-001 map-first. It must distinguish
recovery-speed progression, recovery-volume-intensity progression, their
within-sequence coupling, and recovered-to-failed/restored transitions. Freeze
L10/L20/L40, auction, shape, block, support, and no-rescue gates before
reconstructing raw minutes. No return, payoff, timing, strategy, or CY-011.

MKT-SUPPORT-DYN-001 is now frozen under spec `2abeaff2...` and representation
map `8d50cd08...`, before any temporal estimate. Endpoint rate is primary;
OLS/Theil--Sen, L10/L40, auction, generic-path controls, blocks/years, and five
independent scalar cases are fixed challenges. Recovery completion is a separate
R/F endpoint-state relation with strict arm support.

Execute next. Passing representation quality is not common directional behavior;
passing a process gate is not support defense, usefulness, habitat, or a rule.
Rolling prior-low definitions are not claimed to be one unchanged price level.
PIT historical and promotable relative coordinates remain unavailable, and
OHLCV cannot support buyer/seller or absorption language.

MKT-SUPPORT-DYN-001 completes reproducibly. Both absolute endpoint-rate roles
pass shape, L10/L40, auction, and external geometry, but neither has a common
direction. Speed has zero block medians; activity has -0.144/-0.014 medians with
near-even signs and mixed years. The raw timing/activity rho -0.380 vanishes to
-0.005 after fixed controls and reverses by block (-0.010/+0.025), rejecting a
shared process under the frozen gate.

Completion state is not estimable at its arm floor: first-R/F is 276/39, block F
is 21/18, and annual F counts include 2/2/3. Risk-difference intervals cross
zero and annual signs split. Only 16/192 conditional cells contain five
trajectories, so no relative state is promoted. Five scalar cases and two full
runs reproduce exactly; hashes are session `7484e947...`, trajectory
`80d6c63c...`, transition `0bddbd5e...`, stability `b1c321ab...`, result
`dfde86c9...`, report `66fff13e...`.

SYNTH-MKT-035 selects one final semantic falsifier before leaving this temporal
branch: freeze a count-only MKT-SUPPORT-LVL-DATA-001 audit of whether all tested
days in a sequence share the exact same binary L20 coordinate. No tolerance,
near-touch band, direction estimate, process rescue, payoff, or strategy field.

MKT-SUPPORT-LVL-DATA-001 is frozen under spec `cfd6cde6...` and contract
`63ba8b17...`. Execute next using only bound durable artifacts. It requires exact
binary equality across every tested day, all four fixed level/path views, and
unchanged total/block/year count floors. Zero raw partitions, trajectory values,
direction estimates, correlations, outcomes, strategy fields, or CY-011.

MKT-SUPPORT-LVL-DATA-001 fails: primary unchanged-L20 repeated/twice-recovered
counts are only 7/7, with blocks 3/4 and zero cases in 2019 and 2023. L10 is 9/7,
L40 5/5, and L20 auction 7/7; every fixed gate fails. This shows the accepted
rolling-level trajectories usually follow successive objective lows, not repeated
defense of one unchanged price.

Two runs reproduce exactly: count `0174c5ce...`, result `7ee82869...`, report
`8e1caf61...`; five scalar cases and three focused tests pass. SYNTH-MKT-036
deprioritizes the exact objective-support temporal branch while retaining its two
descriptive coordinates. Next: build an objective prior-high breakout acceptance/
rejection representation and PIT data map before computing any breakout path.

The objective breakout representation map is now frozen under SHA-256
`0b3363e4...`, with the data contract `721517cd...` and
MKT-BREAKOUT-DATA-001 spec `db3d0cfa...` fixed before prior-high construction or
crossing counts. It uses causal prior daily highs at L10/L20/L40, strict
crossing, continuous/auction clocks, neutral close-above/equal/below states,
explicit +5/+15/+30/+60 censoring, and conditional loss/reacquisition support.
Full-session descriptors are first available at 15:30; post-cross bars are
attribution, never predictors at the first-cross time.

MKT-BREAKOUT-DATA-001 passes every count gate. The primary has 964 cohort
crossings (957 unique), 474/490 by fixed block, 464 close-above, one equal, 499
close-below, 899 with 60 remaining bars, and 641 loss/reacquisition cases. All
years, governed views, L10/L40, and auction challenges pass. The 9,575 parent
coordinates match exactly and five scalar cases independently reconstruct the
level/event facts.

Two executions are byte-identical: coordinate/event `1eaeed29...`, counts
`59e74964...`, result `b21244e9...`, report `574163ef...`; three focused tests
pass. Exact raw rows are 2,307,575 and durable output is 4.74 MB. This is event-
domain feasibility only. No continuation, rejection depth, dwell, VWAP,
activity, trajectory, outcome, strategy, post-2023 partition, or CY-011 was
read. Next freeze MKT-BREAKOUT-001 for same-session representation stability,
L10/L40 and auction portability, generic-path compression, and scalar
replication before constructing any post-cross magnitude.

MKT-BREAKOUT-001 is now complete under frozen spec `f314165c...`. Every one of
the ten predeclared roles passes its internal definition and shape gates. Fixed
external controls remove follow-through excursion (daily-high-margin rho
0.980) and closing acceptance margin (daily close-geometry adjusted R2 0.772).
Above-level close episodes compress into loss episodes at rho 0.963.

The retained minimal set is 30-bar continuation, rejection depth, below-level
dwell, loss episodes, conditional reacquisition speed, cumulative-VWAP
acceptance, and post-cross activity. Treat these as seven distinct observables,
not seven proven mechanisms. Domains are 899 full-60-bar events and 641
reacquisitions. Five scalar cases reproduce with maximum aggregate difference
`8.67e-19`; two runs are byte-identical: panel `e67ac766...`, stability
`044fb279...`, geometry `56cf578c...`, result `c56d57af...`, report
`6d74b504...`. Three focused tests and lint pass.

The first construction attempt was invalid before artifact acceptance because
the runner treated a valid leading zero-volume auction as if cumulative VWAP
had to exist before the event. The first case was `000972.SZ` on 2018-03-16;
crossing occurs at 09:37 after positive volume begins at 09:31. The corrected
adapter requires positive cumulative volume only from first crossing onward
and leaves earlier VWAP undefined. No row, event, formula, gate, or estimate
changed.

SYNTH-MKT-038 selects a map-first temporal study of the retained observations.
Freeze role-specific repeated-event support, actual inter-event gaps, temporal
operators, generic controls, blocks/years, and no-rescue gates before estimating
direction or coupling. Do not infer a breakout/failed-breakout process, revive
the three compressed roles, use post-cross values as first-cross predictors,
read outcomes, modify CHINEXT V1, or open CY-011.

The temporal map `f41204fc...` and MKT-BREAKOUT-DYN-001 spec `09f29ecf...`
were frozen before any role-specific trajectory count or sign. The first run
stopped before estimates: `market_sequence_rank` is the constant symbol-
selection ordinal, not time. The first differing sequence had two crossing days
at the same ordinal 2. The V2 control map `3b8f77c8...` and 002 spec
`973b6ecf...` change only event time to frozen `relative_day` (-5 through -1).

The first 002 wrapper call failed before estimates because its active spec path
was redirected too early. After the adapter correction, 002 produced estimates
but could not satisfy byte reproducibility because result JSON included dynamic
elapsed seconds and bound only the wrapper, not the imported scientific runner.
Those 002 outputs are unaccepted. The output-only 003 spec `9cc7883f...` removes
dynamic timing, records all runner hashes, and changes no science.

MKT-BREAKOUT-DYN-003 passes representation for all seven roles but finds no
common direction. Unconditional roles have 250 endpoint/108 three-plus-event
trajectories; reacquisition has 171/58. Continuation intervals cross zero,
rejection reverses by block, four roles have zero/incompatible medians, and
VWAP acceptance fails block-A interval/sign-fraction gates despite a negative
late block. No strengthening/weakening process is emitted.

No residual compression passes. Rejection depth versus below-level dwell is the
nearest pair at -0.693 globally and -0.682/-0.657 by block, just below the fixed
global 0.70 boundary. Do not lower it. Five scalar cases are exact; two complete
runs are byte-identical: trajectory `e5b42475...`, stability `0f10b7d0...`,
coupling `53567843...`, result `1a735a25...`, report `001cca98...`. Eight focused
tests and lint pass; raw-minute reads are zero.

SYNTH-MKT-039 next requires a map, not estimates, for strictly prior-day accepted
trend/breadth conditioning of same-session breakout roles. Preserve trend
direction, breadth discovery, and leadership concentration as separate
primitives; use fixed generic controls and blocks; do not combine them into a
trading gate, read payoff, revive compressed roles, modify CHINEXT, or open
CY-011.

MKT-BREAKOUT-HAB-001 was frozen under map `c5235299...` and spec `066ed2e8...`.
It uses only prior-close accepted trend direction, breadth discovery, and
leadership concentration. Security responses are aggregated to date-view
medians, six indices are separate replications, and raw/PIT/relative coordinates
plus both temporal blocks are conjunctive. No state bin or trading gate exists.

The first runner attempt failed before counts because the projected breakout
frame lacked the derived frozen A/B label. Adding `target_year <= 2020 -> A`,
otherwise B, fixes only the adapter; a focused regression binds the two labels.

The final result has full support but no portable conditioning. Main roles each
retain 830 events/480 date-view cells and reacquisition 596/381. None of 21
primitive edges or seven joint increments passes. Strong-looking subsets fail:
rejection/concentration flips in absolute coordinates, misses PIT late-effect/
annual gates, and is weak relative; activity/concentration weakens from PIT
block A to B and reverses relative. Rejection's joint PIT increment collapses
from 0.116 to 0.002. Do not select any subset.

Two runs are byte-identical: panel `b94b7907...`, edge `e7e9a5c6...`, joint
`5ff4b8be...`, result `4149a17c...`, report `10fed166...`; five scalar cases are
exact and four focused tests pass. This closes only sampled path conditioning.

SYNTH-MKT-040 next requires a deep market-wide objective-breakout diffusion
map: full eligible-universe crossing participation, industry diffusion,
closing acceptance/rejection, and concentration must be constructed before
economic testing and compressed against accepted breadth/concentration. Do not
reuse the 10-symbol sample as a market breadth estimator, read payoff, tune a
lookback, modify CHINEXT, or open CY-011.

The full-market representation map/data contract were frozen under
`c7c307e0...`/`bc6cc64e...`, followed by count-only
MKT-BREAKOUT-DIFF-DATA-001 spec `c659f60d...`. The design uses the exact causal
action coordinate, strict daily-high crossing of strictly prior L10/L20/L40
highs, neutral close states, causal industries, four views, both denominators,
and later absolute/PIT/relative coordinates. It is distinct from MKT-BRTH-002's
inclusive close-based net new-high/new-low breadth and binds that discovery role
plus positive-return leadership concentration as external controls.

The first engineering execution stopped before artifacts at the first exact
coordinate difference, `000020.SZ` on 2019-08-29: a fused window plan returned
`0.7990230286113049` versus accepted `0.799023028611305`. The accepted staged
materialization order removes that one-ULP divergence. No tolerance, rounding,
coordinate formula, row, gate, or scientific role changed; all 9,575 protected
targets then match exactly.

The count audit covers 5,550,255 eligible A-share security-dates and 1,417
completed dates. L20 has 538,891 crossings, split 265,003/6,461/267,427 close
above/equal/below. All annual/view/denominator counts, formation-side industry
domains, coordinate/scalar checks, and resources pass. Five hash-selected daily
events reproduce all level, mapped-price, closing-state, and depth facts exactly.

The whole preregistered domain result is `COMPLETE_FULL_MARKET_DOMAIN_ADEQUACY_FAIL`
only because L40 CHINEXT acceptance-industry coverage is 0.8137/0.8109 versus
0.85. Preserve that failure: acceptance diffusion/concentration cannot advance
under the required neighbor set. The other supported roles may enter a separate
frozen representation experiment; this is a role-specific narrowing, not a
threshold, horizon, or population rescue.

Two runs are byte-identical: count `f94d2a38...`, result `e7c6dd8d...`, report
`884cf7e5...`. Three focused tests and lint pass; peak RSS is below 2.51 GB and
temporary use below 2.33 GB. No minute, outcome, strategy, post-2023, or CY-011
input was read. Next freeze and execute supported level representation quality,
including cross-year/definition/denominator stability and compression against
accepted breadth; do not estimate transitions or usefulness yet.

MKT-BREAKOUT-DIFF-001 was then frozen under `9a7d63eb...`, explicitly excluding
the two failed acceptance-industry roles. All eight supported roles pass raw,
causal-PIT, relative, L10/L40, year/view, denominator, semantic-bound, and fixed
external discovery/concentration gates. The maximum external pairwise rho/joint
R2 is 0.752/0.642 for formation participation, still below 0.85/0.70; every
other role has more margin.

Internal compression removes equal-industry formation because its ALL_A raw rho
with stock-weighted formation participation is 0.978. The Market State Engine
retains seven completed-session coordinates: formation participation, crossing
depth, closing acceptance, closing rejection depth, formation diffusion,
formation leadership concentration, and stock/industry divergence. These are
distinct observations, not seven mechanisms or a composite.

Two runs are byte-identical: panel `99fd26ee...`, stability `d47e82a2...`,
external `37ca992f...`, result `5e626f49...`, report `69603940...`. Five scalar
aggregate cases are exact; four focused tests and lint pass. Peak RSS stays
below 2.63 GB. No transition, future value, outcome, strategy field, minute
partition, post-2023 row, or CY-011 was read.

The next highest-information question is whether these seven levels have stable
broad temporal change/acceleration geometry after nonoverlap and accepted-
breadth-change controls. Build that map before estimates. Do not label a level
as momentum, improving acceptance, expanding opportunity, or a strategy habitat
until a separately frozen dynamic survives.

The temporal map `aaeaba05...` and MKT-BREAKOUT-DIFF-DYN-001 spec
`3c095e17...` were frozen before temporal estimates. They apply fixed 5-session
change and adjacent-block acceleration, 3/10-session and OLS/Theil--Sen
neighbors, 2018--2020/2021--2023 blocks, every-fifth-primary-row phase checks,
absolute/PIT/relative coordinates, and matched discovery/concentration dynamic
controls to all seven parent levels.

Zero of fourteen exact representations passes. Every change role misses the
0.70 neighboring-definition floor (worst full median rho 0.460--0.580), and
every acceleration role has an incompatible negative worst neighbor
(-0.182-- -0.041). Denominator stability is 0.976--0.999 and endpoint-level
correlations are below the redundancy boundary, but neither can rescue temporal
definition instability. Early-block PIT external-control cells have only
97/102 complete observations versus 150, so external distinctness is not
established either.

The parent-schema validator first stopped before estimates; the corrected
validator binds the actual immutable parent fields. A later deterministic rerun
found volatile peak RSS in result JSON. Removing only that telemetry yields two
byte-identical final runs: panel `909aa755...`, stability `0c7ad93b...`,
external `3e8d3238...`, result `a1108373...`, report `7b923c14...`. The 3-GiB
gate remains enforced. Four focused tests pass, five scalar cases are exact,
and no raw/future/outcome/CY-011 input was read.

The exact full-market breakout temporal branch is now closed without tuning.
Retain the seven levels as completed-session observations only. Next map a
strategy-independent same-session absorption/distribution falsification from
already accepted MKT-MIN-001 descriptors, explicitly separating selling/buying
effort from price response and compressing against accepted VWAP defense,
ordinary return, and activity. Do not reopen raw minute data or infer investor
intent.

The absorption/distribution map `52a36366...` and MKT-MIN-AD-001 spec
`311391c7...` were frozen before construction. Selling-effort absorption aligns
downside volume with shallow damage, fast recovery, and VWAP recovery. Rally-
effort distribution aligns upside volume with shallow upside response, weak
late VWAP acceptance, and weak final-30-minute return. These are falsifiable
OHLCV labels only.

Selling-effort absorption fails its fixed leave-one-out gate at worst median rho
0.502 versus 0.70. Rally-effort distribution passes: worst shape/leave-one-out/
p40-p60 rho 0.895/0.774/0.975 and denominator rho 0.999. Against open-close
return, downside volatility, volume concentration, and accepted VWAP defense,
its maximum pairwise median absolute rho is 0.792; joint PIT adjusted R2 is
0.649 median/0.655 maximum, and relative-rank R2 0.161/0.163. It remains one
same-session representation, not participant intent or a reversal process.

Two runs are byte-identical: panel `e78856ea...`, result `c5638d67...`, report
`5e6e3525...`; three focused tests pass. Next freeze contemporaneous geometry
against the seven full-market objective-crossing levels, particularly closing
acceptance/rejection, with return/VWAP alternatives retained. Do not read future
values or infer resistance, timing, payoff, or a rule.

The cross-family map `42a11915...` and MKT-MIN-AD-GEO-001 spec `f5018ec2...`
were frozen before correlations. All support gates pass at the later 15:30 joint
availability. No breakout role is pairwise redundant with rally distribution:
closing acceptance/rejection are highest at absolute rho 0.744/0.732 and all
others are at most 0.321.

The full fixed geometry nevertheless fails distinctness in block-A PIT. Nine
mandatory controls (seven breakout levels, open-close return, VWAP defense)
reconstruct the score at adjusted R2 0.756 median/0.761 maximum. Block-B PIT is
0.677/0.693 and relative coordinates are low, but cannot rescue the conjunctive
failure. The design did not preregister breakout incremental R2 beyond ordinary
alternatives, so do not attribute reconstruction specifically to resistance.

Two runs are byte-identical: panel `10410386...`, pairwise `8d167a9a...`, joint
`e2ef27e2...`, result `3aea7e4e...`, report `34fbe7f3...`; three tests pass.
Rally distribution remains representation evidence, not a direct engine
dimension or future-reversal mechanism.

Next build a data contract before any future-response estimate for the seven
stable objective-crossing levels: exact causal-coordinate 1/3/5-session broad
cross-sectional return/downside responses, nonoverlap, fixed controls/blocks,
and no trading claim. Do not use strategy outcomes or CY-011.
