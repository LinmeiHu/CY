# SIXTH ALPHA DISCOVERY V1
# Visual-First Uncovered-Market Alpha Discovery
#
# Goal:
# Discover a genuinely new sixth alpha family that is NOT merely:
#
# - another ATRDR Bull / MCB Demand variant,
# - another ATRDR Bear reversal,
# - another OGR / IFCGR gap-repair variant,
# - another SMV6 ETF rotation variant.
#
# The existing five strategies are NOT the research target.
# They are:
#
# 1. a coverage map of already-exploited economic mechanisms;
# 2. a control group;
# 3. the final portfolio benchmark.
#
# The central research question is:
#
# "Among stocks and dates not economically covered by the existing five
# strategies, are there recurring, decision-time-observable market paths
# that predict persistent future alpha and can improve the five-strategy
# portfolio?"
#
# This is NOT:
#
# "Try RS20/60/120 and declare success/failure."
#
# This is a mechanism-discovery project:
#
# coverage map
# -> uncovered winners/controls
# -> blinded candlestick visual discovery
# -> visual semantic codebook
# -> quantitative formalization
# -> response surfaces
# -> negative controls
# -> mechanism selection
# -> minimal strategy V1
# -> 2022 bear stress
# -> 2023 confirmation
# -> 2024-current persistence
# -> portfolio incrementality
#
# Run autonomously to completion.
#
# Do not ask the user to invent the next hypothesis.
# Do not stop because an old derived artifact is missing.
# Trace authoritative sources and continue.
#
# Keep infrastructure lightweight.
# The purpose is market research, not building another large framework.

────────────────────────────────────────
0. ENVIRONMENT / NEW RESEARCH LANE
────────────────────────────────────────

Repository:

/Users/linmei/Documents/CY

Authoritative parent research line:

research/five-strategy-capital-admission-v1

Use the latest CLEAN parent HEAD that contains:

AUTHORITATIVE_CONTINUOUS_PROTOCOL_V1
the frozen five-strategy implementations
the corrected five-strategy opportunity/replay infrastructure
the current continuous 2018–2026 data identity

Do not assume a stale hard-coded SHA.
Record:

BASE_BRANCH
BASE_HEAD
REMOTE_HEAD

Create or reuse:

BRANCH:
research/sixth-alpha-visual-discovery-v1

WORKTREE:
/Users/linmei/Documents/CY-worktrees/sixth-alpha-visual-discovery-v1

If the branch/worktree already exists:
reconcile it read-only first and continue.

Never modify the authoritative parent worktree.

At start run:

pwd
git branch --show-current
git rev-parse HEAD
git status --short --branch
git remote -v

Record:

ENVIRONMENT_VALID
BASE_HEAD
START_HEAD

────────────────────────────────────────
1. LARGE ARTIFACT STORAGE
────────────────────────────────────────

Large visual and panel artifacts should NOT live in Git.

First verify the actual external research disk mount read-only.

Preferred large-artifact root:

/Volumes/quant/CY_quant_research/sixth_alpha_visual_discovery_v1/

Use it for:

full panels
candlestick PNGs
contact sheets
large parquet datasets
temporary caches
shape vectors / embeddings
large intermediate results

Keep in Git only:

code
contracts
small CSV summaries
sample manifests
codebooks
small representative figures
reports
hash manifests

If the external disk is unavailable:
do not silently write hundreds of GB to the internal disk.
Use existing small local artifacts where possible and report the exact blocker.

────────────────────────────────────────
2. FROZEN EXISTING STRATEGIES
────────────────────────────────────────

Existing strategies:

ATRDR
MCB
OGR
IFCGR
SMV6

They are frozen controls.

DO NOT modify:

alpha
thresholds
rankings
universes
native exits
execution semantics
corporate-action accounting

The five strategies are used only to determine:

EXISTING_ALPHA_COVERAGE

and later:

PORTFOLIO_INCREMENTALITY.

SMV6 is an ETF strategy and remains:

LOCAL_NATIVE_CALLBACK_REPLAY;
NATIVE_SUPERMIND_EQUIVALENCE_UNVERIFIED.

Do not upgrade that claim.

────────────────────────────────────────
3. TIME PROTOCOL — HARD RULE
────────────────────────────────────────

Use exactly:

DISCOVERY:
2018-01-01 through 2021-12-31

BEAR_STRESS_VALIDATION:
2022-01-01 through 2022-12-31

SECOND_CONFIRMATION:
2023-01-01 through 2023-12-31

PERSISTENCE:
2024-01-01 through latest authoritative available date
(currently expected through 2026-09-04 or later if the authoritative
dataset has already advanced consistently)

Permissions:

2018–2021:
may discover visual semantics,
create quantitative expressions,
study response surfaces,
choose mechanism candidates,
design V1 strategy rules.

2022:
NO NEW FEATURES.
NO NEW VISUAL SEMANTICS.
NO PARAMETER CHANGES.
NO EXIT CHANGES.
NO SCORE CHANGES.

2023:
same frozen rules.

2024-current:
same frozen rules.
Only persistence diagnosis.

2024+ may tell us whether the phenomenon persisted,
weakened, migrated, became regime-dependent, or collapsed.

It may NOT be used to rescue V1.

────────────────────────────────────────
4. HARD DISCOVERY FREEZE BEFORE 2022
────────────────────────────────────────

Before ANY 2022 outcome is inspected:

create:

research/sixth_alpha_visual_discovery_v1/
    discovery_freeze/

containing:

FROZEN_MECHANISM_SPEC.json
FROZEN_VISUAL_CODEBOOK.json
FROZEN_FEATURE_SPEC.json
FROZEN_SCORE_SPEC.json
FROZEN_ENTRY_SPEC.json
FROZEN_EXIT_SPEC.json
FROZEN_PORTFOLIO_VESSEL.json
discovery_freeze_manifest.sha256
DISCOVERY_FREEZE.md

Then commit:

research: freeze sixth alpha discovery v1

Record the commit SHA.

After that commit:

those files are IMMUTABLE for the remainder of this V1 study.

If 2022/2023/2024+ reveal a better idea:
record it as:

V2_FUTURE_HYPOTHESIS

Do NOT alter V1.

Proceed autonomously after freezing.
No user approval is required between stages.

────────────────────────────────────────
5. RESEARCH UNIVERSE
────────────────────────────────────────

V1 stock discovery universe:

MAIN + CHINEXT

Use the same PIT security identity, tradability and corporate-action
infrastructure already registered in the repository where applicable.

Do NOT silently add:

STAR
Beijing Exchange
new ETF universe
new ST rules
new listing-age rules

This is a V1 comparability choice, not a permanent statement that other
boards have no alpha.

SMV6 is NOT used to mark individual stocks as covered.
It is used as an account / market-state context variable.

────────────────────────────────────────
6. SEMANTIC PREFLIGHT
────────────────────────────────────────

Before creating alpha features, write:

research/sixth_alpha_visual_discovery_v1/
    SEMANTIC_PREFLIGHT.md

For each research concept explicitly separate:

CAUSAL_BACKGROUND
STATE_VARIABLE
EVENT_FORMATION_TIME
CONFIRMATION_TRIGGER
ENTRY_TIME
OUTCOME_START_TIME
POSSIBLE_OUTCOME
POSSIBLE_SEMANTIC_AMBIGUITY

Do NOT translate words such as:

clean trend
relative strength
support
compression
breakout
pullback

directly into formulas yet.

First define what they mean economically and when they exist.

────────────────────────────────────────
7. BUILD THE FIVE-STRATEGY COVERAGE MAP
────────────────────────────────────────

Construct a causal stock-date panel:

date × stock

for 2018 through the current authoritative endpoint.

For every completed decision date record whether,
AT THAT TIME,
the stock generated an economic opportunity from:

ATRDR_BULL
ATRDR_FAST_BEAR
ATRDR_SLOW_BEAR
MCB
OGR
IFCGR

Preserve economic lineage.

Do not double count:

OGR / IFCGR parent gap events

or other known parent/child strategy relationships.

Important semantic rule:

NOT FUNDED
does NOT mean
NOT COVERED.

If an existing strategy legally generated an economic opportunity
but the account did not fund it,
that stock/date is still EXISTING_ALPHA_COVERED.

Primary research state:

UNCOVERED_STOCK_DATE

means:

none of the existing stock strategy families generated a legal
economic opportunity for that stock/date.

Also attach causal market context:

market state
breadth / participation
industry
market cap if registered PIT data exists
liquidity
recent volatility
recent returns
existing account gross
existing account cash
active existing strategy/family exposures

Do not add future information.

Create:

coverage/five_strategy_coverage_map.parquet

and compact summary:

coverage/coverage_summary.csv

────────────────────────────────────────
8. BUILD THE UNCOVERED MARKET PANEL
────────────────────────────────────────

For UNCOVERED_STOCK_DATE observations,
construct a discovery research panel.

Decision information must stop at completed date t.

Primary future RESEARCH LABELS:

20-session forward:
market-relative return
industry-relative return

40-session forward:
market-relative return
industry-relative return

60-session forward:
market-relative return
industry-relative return

Also diagnostic:

5d
10d

and path diagnostics:

MFE
MAE
future drawdown path

These are outcome labels for discovery only.

They are NOT final holding-period rules.

Use legal later prices only.
Right-censor incomplete endpoint observations.

────────────────────────────────────────
9. DEFINE PERSISTENT FUTURE OUTCOME SCORE
────────────────────────────────────────

Do not choose winners from one arbitrary Ret20 threshold.

For discovery sampling only,
construct a simple rank-aggregation outcome score.

Primary:

PERSISTENT_EXCESS_SCORE

based on the median cross-sectional percentile rank of:

industry-relative Ret20
industry-relative Ret40
industry-relative Ret60

computed within causal comparable date populations.

Market-relative versions remain diagnostics.

Do not optimize weights.

Use:

equal contribution / median rank aggregation.

For visual sampling:

WINNER:
top 15% PERSISTENT_EXCESS_SCORE

NEUTRAL:
45–55%

LOSER:
bottom 15%

Also require that Winner/Loser identity is not caused by only one
extreme horizon when feasible:

Winner should have at least 2/3 primary horizons above the
same-date 70th percentile.

Loser should have at least 2/3 below the 30th percentile.

These thresholds are only for creating contrastive visual discovery samples.
They are NOT strategy thresholds.

────────────────────────────────────────
10. MATCH WINNER / NEUTRAL / LOSER CONTROLS
────────────────────────────────────────

Create matched triplets.

For each Winner find:

one Neutral
one Loser

preferably matched on:

same decision date
same PIT industry

and close in:

log market cap
ADV20 / liquidity
prior 60d return
prior 20d return
realized volatility 60d

Use simple nearest-neighbor matching with predeclared standardized distance.

Do NOT build propensity-score machinery.

If exact industry matching is impossible for a small cell:
use the nearest registered parent industry and flag it.

Do not repeatedly sample the same stock within heavily overlapping
120-day windows unless needed.

Create:

visual/winner_control_triplets.csv

Include matching-quality diagnostics.

────────────────────────────────────────
11. VISUAL SAMPLE DESIGN
────────────────────────────────────────

Target:

240 matched triplets
= 720 charts

Discovery years:

2018
2019
2020
2021

Target approximately:

60 triplets per year.

Within each year,
stratify across market participation:

LOW
MID
HIGH

using a simple causal participation measure derived from already registered
breadth data.

Do not optimize participation thresholds on future returns.

Prefer broad thirds / natural quantile groups.

This visual sample size is a cap, not a target to exceed.

Do not inspect thousands of images one-by-one.

────────────────────────────────────────
12. CAUSAL CANDLESTICK GENERATION
────────────────────────────────────────

For every sample create a standardized chart ending at decision date t.

Primary visual:

120 completed trading sessions ending at t.

Also provide a compact:

250-session context strip.

Primary image contains:

OHLC candlesticks
volume
the decision boundary T

Do NOT show:

future candles
future outcome
winner/neutral/loser label
stock ticker
actual future return
actual calendar year if avoidable

Use blind IDs:

CASE_000001
...

X-axis should preferably be:

T-120 ... T

not calendar dates.

Normalize price scale for cross-stock visual comparability
while preserving OHLC geometry.

Volume should use a comparable normalization such as ratio to trailing median
or ADV, using only information available by t.

Corporate-action handling must be causal.

Do NOT use future-adjusted price information created by corporate actions
that were not known/effective by t.

If the registered dataset already supplies a PIT-safe adjusted coordinate:
use it and document identity.

────────────────────────────────────────
13. BLINDING IMPLEMENTATION
────────────────────────────────────────

Generate the visual sample and secret outcome map programmatically.

Write:

visual/sealed_outcome_map.parquet

Do NOT print or inspect its contents in model-visible output.

Create blind filenames and randomized contact-sheet order.

The model should inspect blind images FIRST.

Only after visual labels are written and hashed may outcome identity be opened.

Record:

visual/blinding_manifest.json

The same model wrote the code,
so perfect human-style blinding is impossible.

The goal is operational blindness:

do not load or print individual outcome mappings into the reasoning context
before labels are committed.

────────────────────────────────────────
14. CONTACT SHEETS — TOKEN-EFFICIENT VISUAL RESEARCH
────────────────────────────────────────

Create 4 × 4 contact sheets:

16 charts per sheet.

Randomize blind IDs across sheets.

720 charts ≈ 45 primary contact sheets.

Do NOT show matched triplets next to each other by default.

Only open individual high-resolution charts for:

ambiguous cases
representative archetypes
counterexamples

Target no more than roughly 10–15% individual zoom-ins.

────────────────────────────────────────
15. VISUAL DISCOVERY ROUND 1 — OPEN CODING
────────────────────────────────────────

Use approximately:

60 matched triplets
= 180 blind charts

balanced across:

2018–2021
LOW/MID/HIGH participation.

Do NOT use a predefined technical-analysis checklist as the answer.

Open-code recurring visual structure.

Look for things such as, but do not assume they are correct:

path continuity
trend aging
persistent higher highs/lows
shallow vs deep pullbacks
pullback duration
breakout retention
failed breakout
wick / rejection pressure
volatility contraction
volume asymmetry
price compression
slow accumulation
single-day spike dependence
climax behavior
natural support scale
relative-price smoothness
other unexpected patterns

Do not convert these to trade rules yet.

Create:

visual/open_coding_notes.md
visual/open_coding_raw_labels.csv

────────────────────────────────────────
16. FREEZE VISUAL CODEBOOK
────────────────────────────────────────

From repeated open-coding themes,
create a compact visual semantic codebook.

Target:

8–15 dimensions maximum.

For every dimension record:

name
economic meaning
what +2 looks like
what +1 looks like
what 0 looks like
what -1 looks like
what -2 looks like
possible ambiguity
possible overlap with other dimensions

Do not keep dimensions that cannot be judged consistently.

Write:

visual/visual_codebook_v1.json

Do not tune this using the remaining outcome labels.

────────────────────────────────────────
17. VISUAL DISCOVERY ROUND 2 — FORMAL BLIND LABELING
────────────────────────────────────────

Use the remaining approximately:

540 blind charts.

Score frozen visual dimensions using:

-2
-1
0
+1
+2

or NA if genuinely not judgeable.

Do not force a score.

Write:

visual/formal_visual_labels.csv

Before opening outcomes:
hash the labels file.

────────────────────────────────────────
18. VISUAL REPEATABILITY
────────────────────────────────────────

Randomly duplicate ~15% of formal images under new blind IDs.

Do not identify them as duplicates during labeling.

Measure within-dimension repeatability.

Report:

exact agreement
within-1 agreement
rank correlation where meaningful

Do not build a publication-grade psychometric system.

This is a practical reliability check.

Dimensions with clearly poor repeatability should not become core alpha variables.

Create:

visual/visual_repeatability.csv

────────────────────────────────────────
19. OPEN THE VISUAL OUTCOMES
────────────────────────────────────────

Only now read:

sealed_outcome_map.parquet

Join blind labels to:

WINNER
NEUTRAL
LOSER

and continuous future outcomes.

For every visual semantic report:

winner mean / distribution
neutral
loser

by:

2018
2019
2020
2021

and pooled discovery.

Also show monotonicity:

semantic score -2 → +2

vs:

future industry-relative Ret20/40/60
persistent excess score
MFE
MAE

Do not select a dimension because one single year is spectacular.

────────────────────────────────────────
20. OPTIONAL UNSUPERVISED SHAPE DISCOVERY
────────────────────────────────────────

This is secondary and must not delay the main visual study.

Do NOT download or train a large new vision model just for this task.

Preferred lightweight path:

standardize causal OHLCV / relative-price sequences
using only T-120:T

build numeric shape vectors

then use:

PCA
+
simple clustering

Future outcomes must NOT enter clustering.

Only after clusters are frozen,
compare outcome distributions.

If a suitable local frozen image encoder already exists and is cheap:
it may be used as a secondary diagnostic.

Do not make a black-box image cluster the final trading rule.

Create:

shape_discovery/cluster_map.csv
shape_discovery/cluster_outcomes.csv
shape_discovery/representative_cases/

────────────────────────────────────────
21. QUANTITATIVE FORMALIZATION
────────────────────────────────────────

Only visual semantics that show:

reasonable repeatability
AND
economic outcome separation

may proceed.

For each surviving semantic concept,
create 2–3 reasonable algebraic expressions.

Maximum 3.

Example only:

PATH_CLEANLINESS might be represented by:

A.
net displacement / total path length

B.
trend regression fit / directional efficiency

C.
fraction of movement aligned with dominant trend

Do not assume these exact formulas are correct.

RELATIVE_PERSISTENCE might have:

cumulative relative return
fraction of positive relative days
relative trend slope

PULLBACK_QUALITY might have:

depth
duration
recovery speed

The purpose is:

different reasonable measurements of the SAME economic concept.

Do not declare the concept dead because one formula fails.

────────────────────────────────────────
22. COARSE TIME SCALES ONLY
────────────────────────────────────────

Do NOT scan dozens of windows.

Use only a few economically distinct time scales.

Default starting scales:

20
60
120 sessions

If the visual evidence clearly indicates another natural scale,
document the reason before testing it.

Do not run:

41,42,43,...89

parameter mining.

We are looking for broad response stability.

────────────────────────────────────────
23. RESPONSE SURFACES
────────────────────────────────────────

For each quantitative semantic:

show quintile / decile response where sample size allows.

Primary goal:

monotonic or economically coherent gradients.

Also inspect 2D surfaces for a SMALL number of pairs suggested by the
visual evidence, for example:

cleanliness × relative persistence
cleanliness × participation
pullback quality × trend persistence

Maximum:

6 primary 2D surfaces.

Do not search hundreds of interactions.

We want a broad surface,
not one magical cell.

Create:

quant/response_surfaces/

and:

quant/semantic_response_summary.csv

────────────────────────────────────────
24. NEGATIVE CONTROLS
────────────────────────────────────────

Every promising mechanism must face:

A. RANDOM SAME-DATE CONTROL

B. MATCHED MOMENTUM CONTROL

C. MATCHED SIZE / LIQUIDITY / VOLATILITY CONTROL

D. INDUSTRY CONTROL

E. EXISTING-STRATEGY CONTROL

At minimum control for:

market beta / broad market direction
industry
prior 20/60/120 return
size
liquidity
realized volatility

Use simple cross-sectional residualization / stratification.

Do not build a giant factor model.

Ask:

Does the candidate semantic still have incremental outcome ordering
after standard momentum and style exposure are accounted for?

If not:

label:

STANDARD_FACTOR_REDISCOVERED

not "new alpha".

────────────────────────────────────────
25. EXISTING STRATEGY NEAR-MISS AUDIT
────────────────────────────────────────

A new mechanism can fail to trigger an existing strategy yet still be only
a threshold-near-miss version of it.

Where available, compare candidates against decision-time native variables from:

ATRDR Bull
MCB
OGR / IFCGR

Measure:

same-date overlap
same-symbol overlap
holding overlap
economic-family overlap

and if native score/distance exists:

distance to existing admission threshold.

Ask:

Is this genuinely new,
or just:

ATRDR_BULL_NEAR_MISS
MCB_NEAR_MISS
GAP_NEAR_MISS?

Do not create a sixth strategy from a trivial threshold relaxation.

────────────────────────────────────────
26. DISCOVERY REGIME STRATIFICATION
────────────────────────────────────────

Within 2018–2021,
every promising mechanism must also be inspected under causal market states.

Use broad predeclared states such as:

UP
SIDEWAYS / MIXED
DOWN
STRESS

and participation:

LOW
MID
HIGH

Use only information known by t.

Do NOT demand positive absolute return in every state.

A valid result may look like:

UP:
Top rank +8%, bottom +1%

DOWN:
Top rank -2%, bottom -14%

That still indicates strong relative alpha.

Separate:

ALPHA RANKING VALIDITY

from:

MARKET BETA.

────────────────────────────────────────
27. DISCOVERY ITERATION LIMIT
────────────────────────────────────────

Discovery allows only TWO substantive research rounds.

ROUND 1:
visual discovery / codebook.

ROUND 2:
quantitative formalization of already-discovered semantics.

After that:
freeze.

Do not continue adding:

new indicators
new filters
new windows
new thresholds

until the historical curve looks good.

────────────────────────────────────────
28. SELECT MAXIMUM THREE ECONOMIC MECHANISMS
────────────────────────────────────────

At the end of discovery,
retain at most:

3

mechanism candidates.

They must represent meaningfully different economic stories.

Do not keep 3 minor variants of the same score.

Possible examples ONLY:

CLEAN_RELATIVE_STRENGTH
SLOW_PERSISTENT_TREND
COMPRESSION_CONTINUATION

The actual mechanisms must come from the evidence.

For each create:

mechanisms/<name>/MECHANISM_CARD.md

including:

economic story
visual evidence
quantitative evidence
negative controls
opportunity supply
relation to existing five strategies
known weaknesses

────────────────────────────────────────
29. MECHANISM DISCOVERY QUALIFICATION
────────────────────────────────────────

A mechanism may proceed to Strategy V1 only if:

1. visual semantics are reasonably repeatable;

2. at least two reasonable quantitative expressions support the same
   directional economic effect;

3. discovery-year results are not driven by only one year;

4. response surfaces show a broad structure rather than a single optimized cell;

5. standard momentum / industry / style controls do not fully explain it;

6. it is not simply an existing-strategy near miss;

7. opportunity supply is large enough to plausibly matter to the portfolio
   OR edge is unusually strong and independent.

Do not use p-value threshold hunting as the primary gate.

Prefer:

effect size
monotonicity
year consistency
economic plausibility
portfolio relevance

────────────────────────────────────────
30. BUILD MINIMAL STRATEGY V1
────────────────────────────────────────

For each surviving mechanism,
build ONE minimal Strategy V1.

Maximum:

3–5 core state variables.

Prefer:

simple percentile/rank aggregation
or equal-weight rank sum.

Do NOT optimize arbitrary weights.

The score must naturally rank candidates cross-sectionally.

Avoid a pure YES/NO strategy if ranking is possible.

Entry timing:

signal state formed using completed day t information

entry:
next legal tradable execution point
using existing causal daily execution semantics where applicable.

No lookahead.

────────────────────────────────────────
31. ADMISSION / TOP-K
────────────────────────────────────────

Do not scan many K values.

Test only a coarse set such as:

Top 5
Top 10
Top 20

or equivalent percentiles if daily universe size makes that more stable.

We are looking for a plateau.

If:

Top5 ≈ Top10 ≈ Top20

good.

If only:

Top13

would work,
reject as fragile.

Choose the center of the stable region,
not the highest historical CAGR.

────────────────────────────────────────
32. NATIVE EXIT DISCOVERY
────────────────────────────────────────

Forward Ret20/40/60 were research labels,
not exits.

First inspect discovery-period:

alpha decay
time-to-MFE
time-to-MAE
state decay

Then test at most:

3 simple exit concepts.

One should be:

STATE_DECAY_EXIT

consistent with the mechanism.

One may be:

SIMPLE_TREND_INVALIDATION

One may be:

FIXED_HORIZON_CONTROL

The fixed horizon is only a control.

Prefer a simple causal state-decay exit if supported.

No complex exit optimization.

────────────────────────────────────────
33. NEUTRAL RESEARCH POSITION SIZING
────────────────────────────────────────

Do not optimize sizing in this task.

Use a simple non-leveraged research vessel.

For standalone Strategy V1:

max total gross = 100%
cash >= 0
no leverage
max single stock = 5% NAV
max active positions = 20

Do not rebalance old positions merely because NAV changes.

New entries receive up to the neutral 5% target,
subject to:

available cash
legal execution
existing same-security exposure

Native exit controls removal.

These are neutral research-account rules,
not claimed optimal sizing.

────────────────────────────────────────
34. DISCOVERY ACCOUNT RESULTS
────────────────────────────────────────

For each Strategy V1 report 2018–2021:

CAGR
MaxDD
CVaR5
Sharpe

average gross
P95 gross
cash ratio

trades
independent signal dates
average active names

holding days
capital days
P&L per capital-day

winner fraction
profit factor

top-5 events
top-5 stocks
top-5 days concentration

capacity diagnostics where available

Also report ranking monotonicity.

Do not select the final mechanism from CAGR alone.

────────────────────────────────────────
35. FREEZE DISCOVERY
────────────────────────────────────────

Now choose:

0–3 V1 candidates.

Freeze every rule.

Write all freeze artifacts described in Section 4.

Hash them.

Run tests.

Commit:

research: freeze sixth alpha discovery v1

Only after the commit succeeds:

OPEN 2022.

────────────────────────────────────────
36. 2022 — BEAR STRESS CHALLENGE
────────────────────────────────────────

Run frozen V1 unchanged through 2022.

Do NOT recalibrate anything.

Report separately:

absolute return

market-relative return
industry-relative return

CAGR
MaxDD
CVaR
Sharpe

rank monotonicity
Top-vs-Bottom spread

MFE
MAE

signal supply
average gross
cash

worst drawdown episodes

overlap with the worst existing-five-strategy dates

Possible interpretation labels:

BEAR_STRESS_PASS
RELATIVE_ALPHA_SURVIVES
ABSOLUTE_LOSS_BUT_RANK_VALID
WEAKENED
FAIL_DIRECTION
COLLAPSED

A strategy does NOT fail merely because absolute 2022 return is negative.

If its high-ranked opportunities materially outperform its controls
during a severe down market,
that is meaningful evidence.

No changes after 2022.

────────────────────────────────────────
37. 2023 — SECOND CONFIRMATION
────────────────────────────────────────

Run exactly the same frozen V1 through 2023.

Report the same mechanism and strategy metrics.

Ask:

Did the phenomenon survive outside the 2022 bear environment?

Classify:

CONFIRMED_GENERAL
CONFIRMED_BEAR_SPECIFIC
WEAKENED
FAIL_DIRECTION
COLLAPSED

No tuning.

────────────────────────────────────────
38. 2024-CURRENT — PERSISTENCE TEST
────────────────────────────────────────

Run unchanged for:

2024
2025
2026 YTD / latest year

and combined 2024-current.

This is explicitly:

PERSISTENCE_TEST

not new feature discovery.

Evaluate separately:

A. MECHANISM

Does the semantic response surface still exist?

B. RANKING

Does Top still beat Bottom?

C. SUPPLY

Did opportunity density change?

D. STRATEGY

Did the frozen Native lifecycle remain investable?

E. PORTFOLIO

Did incremental contribution remain?

Classify:

PERSISTENT
WEAKENED_BUT_PRESENT
REGIME_DEPENDENT
MIGRATED
COLLAPSED

Do not modify V1.

────────────────────────────────────────
39. IMPORTANT: DISTINGUISH ALPHA FAILURE FROM IMPLEMENTATION FAILURE
────────────────────────────────────────

Example:

If 2026 Strategy CAGR is poor,
but:

high score still beats low score,
and semantic response surface remains,

then do NOT label:

ALPHA_COLLAPSED.

Investigate whether the issue is:

opportunity supply
position occupancy
exit
concentration
account implementation

Report:

MECHANISM_STATUS
STRATEGY_IMPLEMENTATION_STATUS

separately.

────────────────────────────────────────
40. PORTFOLIO TEST 1 — IDLE CAPITAL OVERLAY
────────────────────────────────────────

Only Strategy V1 candidates that survive 2022 and 2023 proceed.

Use the existing authoritative five-strategy Native physical account.

Do NOT change the five existing strategies.

Existing Native opportunities retain priority.

The sixth strategy may use ONLY capital that would otherwise remain unused.

Meaning:

existing Native funding happens first.

Then new strategy requests may use remaining causal cash.

No leverage.

gross <= 100%.

Existing five-strategy positions are never reduced to fund the sixth strategy.

This answers:

"Can the new alpha convert structural idle cash into incremental return
without hurting existing alpha?"

Compare:

FIVE_NATIVE

vs

FIVE_NATIVE_PLUS_NEW_ALPHA_IDLE_ONLY

Report:

incremental CAGR
incremental P&L
MaxDD
CVaR
Sharpe
average gross
cash ratio
capital-days
incremental P&L per capital-day
worst-month impact
worst-five-strategy-day impact
concentration
costs

────────────────────────────────────────
41. PORTFOLIO TEST 2 — UNIFIED COMPETITION
────────────────────────────────────────

Only if IDLE_ONLY shows meaningful positive incremental value.

Then allow the new strategy to enter a unified opportunity competition.

Reuse the current causal unified-pool infrastructure where possible.

Do NOT invent a new allocator.

The existing five-strategy Candidate-B style economic calibration may be used
as a reference architecture,
but adding a sixth strategy requires discovery-only calibration for the
new opportunity family.

All cross-strategy calibration must use only 2018–2021.

Do not use 2022+ to recalibrate.

Compare:

FIVE_NATIVE

FIVE_NATIVE_PLUS_NEW_ALPHA_IDLE_ONLY

UNIFIED_FIVE_REFERENCE

UNIFIED_SIX_WITH_NEW_ALPHA

Ask:

Does the sixth strategy deserve capital even when capital is scarce?

────────────────────────────────────────
42. NEW ALPHA ECONOMIC TIER
────────────────────────────────────────

Classify surviving strategy:

TIER_1_CAPITAL_COMPETING_ALPHA

= deserves capital against existing five opportunities

or:

TIER_2_IDLE_CAPITAL_ALPHA

= adds value when cash is idle,
but should not displace existing opportunities

or:

NO_PORTFOLIO_INCREMENT

This is more informative than standalone CAGR.

────────────────────────────────────────
43. PORTFOLIO FRONTIER
────────────────────────────────────────

For final candidates,
build historical risk frontiers at:

MaxDD <= 5%
<= 8%
<= 10%
<= 15%

Compare:

existing five Native
new strategy standalone
idle-capital overlay
unified-six candidate

Report:

CAGR
MaxDD
CVaR
Sharpe
average gross
cash ratio
single-name concentration
strategy/family concentration

The sixth alpha succeeds only if it moves the practical portfolio frontier
outward or provides a clearly valuable diversification role.

────────────────────────────────────────
44. TAIL-DAY ORTHOGONALITY
────────────────────────────────────────

Do not rely only on correlation.

Identify existing-five worst:

5% daily return dates

and worst:

5 drawdown episodes.

Measure sixth-strategy:

return
exposure
active-signal quality

during those periods.

A strategy with lower standalone CAGR but strong behavior when existing
strategies suffer may be highly valuable.

Report:

portfolio/tail_day_orthogonality.csv

────────────────────────────────────────
45. COST / CAPACITY
────────────────────────────────────────

Final candidates only.

Use:

base registered cost
1.5x cost
2x cost

No signal retuning.

For stocks report where available:

order notional / daily amount
order notional / lagged ADV20

p50
p75
p90
p95
p99
max

Do not invent a market-impact model.

If capacity is not modeled:
state that clearly.

────────────────────────────────────────
46. FAILURE TAXONOMY
────────────────────────────────────────

Never write merely:

STRATEGY_FAILED.

Use the most precise label.

Possible final mechanism states:

NO_VISUAL_STRUCTURE
VISUAL_STRUCTURE_NOT_REPEATABLE
VISUAL_STRUCTURE_NOT_QUANTIFIABLE
STANDARD_FACTOR_REDISCOVERED
DUPLICATES_EXISTING_DEMAND_ALPHA
DUPLICATES_EXISTING_REVERSAL_ALPHA
DUPLICATES_EXISTING_GAP_ALPHA
MECHANISM_FOUND_BUT_TOO_SPARSE
MECHANISM_CONFIRMED_NOT_INVESTABLE
STRATEGY_WORKS_NO_PORTFOLIO_INCREMENT
NEW_ALPHA_IDLE_ONLY
NEW_ALPHA_CAPITAL_COMPETING
NEW_ALPHA_PERSISTENT

A formula failure is not mechanism failure.

A strategy implementation failure is not automatically alpha failure.

────────────────────────────────────────
47. FAMILY CLOSURE RULE
────────────────────────────────────────

Close an entire proposed mechanism family ONLY if:

multiple reasonable visual definitions
AND
multiple reasonable quantitative definitions
AND
multiple discovery years

all fail to support the economic story.

Do not close a family because:

one threshold failed
one window failed
one formula failed
one year was bad

────────────────────────────────────────
48. REQUIRED DIRECTORY
────────────────────────────────────────

Create:

research/sixth_alpha_visual_discovery_v1/

with:

SEMANTIC_PREFLIGHT.md
REPORT.md
REPRODUCTION_COMMANDS.md
input_manifest.json

coverage/
    coverage_summary.csv

visual/
    winner_control_triplets.csv
    blinding_manifest.json
    visual_codebook_v1.json
    open_coding_notes.md
    open_coding_raw_labels.csv
    formal_visual_labels.csv
    visual_repeatability.csv

shape_discovery/
    cluster_map.csv
    cluster_outcomes.csv

quant/
    semantic_response_summary.csv
    negative_controls.csv
    existing_strategy_near_miss.csv
    discovery_regime_results.csv

mechanisms/
    <mechanism_A>/
    <mechanism_B>/
    <mechanism_C>/

discovery_freeze/
    FROZEN_MECHANISM_SPEC.json
    FROZEN_VISUAL_CODEBOOK.json
    FROZEN_FEATURE_SPEC.json
    FROZEN_SCORE_SPEC.json
    FROZEN_ENTRY_SPEC.json
    FROZEN_EXIT_SPEC.json
    FROZEN_PORTFOLIO_VESSEL.json
    discovery_freeze_manifest.sha256
    DISCOVERY_FREEZE.md

validation/
    bear_stress_2022.csv
    confirmation_2023.csv

persistence/
    persistence_2024.csv
    persistence_2025.csv
    persistence_2026_ytd.csv
    persistence_summary.csv

portfolio/
    standalone_results.csv
    idle_capital_overlay.csv
    unified_six_results.csv
    portfolio_frontier.csv
    tail_day_orthogonality.csv
    cost_stress.csv
    capacity.csv

output/
    test_results.json
    requirement_coverage.csv
    output_manifest.sha256

Large files should live under the external artifact root
and be referenced by manifests/hashes.

────────────────────────────────────────
49. ESSENTIAL TESTS ONLY
────────────────────────────────────────

Do not spend most of the task building tests.

But the following are mandatory:

1. frozen five strategies unchanged

2. coverage map uses decision-time opportunities,
   not future funded outcomes

3. NOT_FUNDED is not misclassified as UNCOVERED

4. charts contain no future candles

5. chart corporate-action coordinates are PIT-safe

6. sealed visual outcome map is not opened before visual labels are frozen

7. sample construction is deterministic from a frozen seed

8. no 2022+ data enters discovery features / formulas / thresholds

9. discovery freeze files are unchanged during 2022+ runs

10. 2022, 2023, 2024+ use identical frozen strategy spec

11. no leverage

12. cash >= 0

13. gross <= 100%

14. existing five Native trades are unchanged in IDLE_ONLY overlay

15. deterministic rerun of at least:
    one discovery sample build,
    one strategy account,
    one overlay account

16. registered input hashes remain unchanged

Do not create dozens of low-value unit tests merely to increase test count.

────────────────────────────────────────
50. RESEARCH STYLE
────────────────────────────────────────

Maintain independent judgment.

Do not mechanically convert user phrases into formulas.

Do not assume:

relative strength is the answer
clean path is the answer
MA support is the answer
low participation is the answer

These are hypotheses.

Let evidence decide.

Actively search for unexpected visual structures.

If the best new mechanism is something not anticipated in this prompt:
document it and pursue it if it satisfies the same scientific constraints.

────────────────────────────────────────
51. DO NOT OVER-ENGINEER
────────────────────────────────────────

This task is about discovering alpha.

Do not build:

a new generic backtest framework
a new research operating system
a complicated feature store
a large ML platform
a new portfolio engine

Reuse existing authoritative infrastructure.

Spend effort on:

market examples
visual understanding
mechanism evidence
strategy behavior
portfolio incrementality

not framework complexity.

────────────────────────────────────────
52. DO NOT USE COMPLEX ML FIRST
────────────────────────────────────────

Do not start with:

LightGBM
XGBoost
deep neural network
vision classifier

First establish:

visual semantic structure
continuous response surfaces
simple ranking relationships

If a stable phenomenon exists but a simple combination is insufficient,
a later V2 may use modest ML.

V1 should stay interpretable.

────────────────────────────────────────
53. FINAL REPORT MUST ANSWER
────────────────────────────────────────

A. COVERAGE

What proportion of investable stock-date space is already economically covered
by the five strategies?

Where is uncovered space largest?

B. MISSED WINNERS

What kinds of winners are the existing five strategies systematically missing?

C. VISUAL SEMANTICS

Which visual structures repeatedly distinguish future winners from matched
neutral/loser controls?

D. QUANTITATIVE TRANSLATION

Which visual semantics survive multiple reasonable algebraic definitions?

E. INDEPENDENCE

Which survive standard momentum/style controls?

Which are genuinely different from ATRDR/MCB/OGR?

F. MARKET STATE

Where does the alpha strengthen or weaken?

G. DISCOVERY

Which mechanisms survive 2018–2021?

H. 2022

Did the mechanism survive a severe bear environment?

I. 2023

Did it survive a different market environment?

J. 2024-CURRENT

Is the mechanism:

PERSISTENT
WEAKENED
REGIME_DEPENDENT
MIGRATED
COLLAPSED?

K. STRATEGY

Can it form a causal executable Native lifecycle?

L. PORTFOLIO

Does it:

use structural idle capital productively?

improve risk-adjusted returns?

help during the five-strategy worst periods?

deserve capital when competing with existing strategies?

M. FINAL DECISION

Is there a real sixth strategy?

────────────────────────────────────────
54. FINAL DECISION OPTIONS
────────────────────────────────────────

Allowed top-level final decisions:

NO_NEW_MECHANISM_FOUND

MECHANISM_FOUND_NOT_INVESTABLE

NEW_ALPHA_FOUND_BUT_NO_PORTFOLIO_INCREMENT

NEW_ALPHA_IDLE_CAPITAL_CANDIDATE

NEW_ALPHA_CAPITAL_COMPETING_CANDIDATE

NEW_ALPHA_FORWARD_SHADOW_CANDIDATE

Do NOT authorize production trading in this task.

A successful candidate should be frozen for forward shadow.

────────────────────────────────────────
55. GIT CHECKPOINTS
────────────────────────────────────────

Suggested commits:

1.
research: build sixth-alpha coverage and visual discovery set

2.
research: freeze sixth-alpha discovery v1

THIS COMMIT MUST OCCUR BEFORE OPENING 2022.

3.
research: validate sixth-alpha across 2022-2026

4.
research: evaluate sixth-alpha portfolio incrementality

5.
research: finalize sixth-alpha discovery v1

Normal push only.

Never force push.

At end:

git status
git log -5 --oneline
git rev-parse HEAD
git rev-parse origin/research/sixth-alpha-visual-discovery-v1

Worktree must be clean.

────────────────────────────────────────
56. FINAL RESPONSE FORMAT
────────────────────────────────────────

Return:

ENVIRONMENT_VALID:
BASE_BRANCH:
BASE_HEAD:
BRANCH:
START_HEAD:
DISCOVERY_FREEZE_COMMIT:
END_HEAD:
PUSH:
WORKTREE_CLEAN:

FROZEN_EXISTING_STRATEGIES_MODIFIED: NO
NEW_VALIDATION_TUNING_AFTER_2021: NO

DISCOVERY_STOCK_DATES:
UNCOVERED_STOCK_DATES:
UNCOVERED_FRACTION:

VISUAL_TRIPLETS:
VISUAL_CHARTS:
CONTACT_SHEETS:
VISUAL_CODEBOOK_DIMENSIONS:
VISUAL_REPEATABILITY_STATUS:

MECHANISMS_DISCOVERED:

For each mechanism:

NAME:
ECONOMIC_STORY:
VISUAL_EVIDENCE:
QUANTITATIVE_EVIDENCE:
STANDARD_FACTOR_CONTROL:
EXISTING_STRATEGY_OVERLAP:
2018_RESULT:
2019_RESULT:
2020_RESULT:
2021_RESULT:

Then frozen Strategy V1:

CORE_FEATURES:
SCORE:
ENTRY:
EXIT:
TOP_K:
MAX_SINGLE_STOCK:
MAX_GROSS:

Then:

2022_BEAR_STRESS_RESULT:
2023_CONFIRMATION_RESULT:
2024_PERSISTENCE_RESULT:
2025_PERSISTENCE_RESULT:
2026_YTD_PERSISTENCE_RESULT:

MECHANISM_STATUS:
IMPLEMENTATION_STATUS:

Standalone:

CAGR:
MaxDD:
CVaR5:
Sharpe:
AVG_GROSS:
CASH_RATIO:
CAPITAL_DAY_EFFICIENCY:

Portfolio:

IDLE_CAPITAL_INCREMENTAL_CAGR:
IDLE_CAPITAL_DELTA_MaxDD:
IDLE_CAPITAL_DELTA_CVaR:
IDLE_CAPITAL_DELTA_AVG_GROSS:

UNIFIED_COMPETITION_RESULT:

TAIL_DAY_ORTHOGONALITY:

FINAL_PORTFOLIO_FRONTIER:

FINAL_DECISION:

If successful:

ALPHA_TIER:
TIER_1_CAPITAL_COMPETING
or
TIER_2_IDLE_CAPITAL

FORWARD_SHADOW_SPEC:

If unsuccessful:

EXACT_FAILURE_LAYER:
VISUAL
MECHANISM
INVESTABILITY
PORTFOLIO

and explain what was rejected and what was NOT rejected.

Finally list:

tests
input hashes
discovery freeze hash
report path
large artifact root
reproduction command
commits
remote HEAD