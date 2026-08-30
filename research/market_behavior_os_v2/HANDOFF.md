# Market Behavior Research OS V2 handoff

Updated 2026-08-31.

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
