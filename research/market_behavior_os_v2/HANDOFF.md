# Market Behavior Research OS V2 handoff

Updated 2026-08-30.

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

## Why work stopped

The next ranked task is a true market-state five-day minute representation. Six
sampled market dates cannot meet the 504-observation causal normalization gate.
A defensible date/cross-section expansion under the current rowwise adapter
would exceed 100 million raw minute rows and violate the frozen no-full-market-
build resource policy. `STOP.md` records the genuine
`STOP_UNSAFE_MARKET_MINUTE_REPRESENTATION_SCALE` boundary. Resume only with a
reviewed vectorized/partition-pruned adapter and frozen resource budget; do not
weaken the gate or substitute CHINEXT events.

Do not populate strategy x habitat outcomes from MKT-GEO-001, and do not return
automatically to CHINEXT minute-feature screening.

## Human decision required?

Yes, but it is an engineering/resource decision rather than a scientific label:
authorize and review the vectorized market-minute aggregation budget before the
next representation freeze. CY-011 and all outcomes remain unopened.
