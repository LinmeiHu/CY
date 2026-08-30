# Market Behavior Research OS V2 handoff

Updated 2026-08-30.

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

## Human decision required?

No. Continue with MKT-DSTRESS-001 map-first outcome-blind directional-process
research. CY-011 remains unopened.

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
