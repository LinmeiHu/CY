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

SYNTH-MKT-006 selects HAB-CHX-001 next: a strictly exploratory Strategy x Market
Habitat study using only frozen trend direction and breadth discovery as the two
initial mechanisms. It must report baseline/A/B/A+B, right-tail and severe-loss
behavior, temporal stability, and continuous effects without optimizing a rule.

Do not populate strategy x habitat outcomes from MKT-GEO-001, and do not return
automatically to CHINEXT minute-feature screening.

## Human decision required?

No. Continue with the preregistered HAB-CHX-001 association study. CHINEXT
outcomes are already consumed and must remain exploratory; CY-011 remains
unopened.
