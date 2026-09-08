# UNIFIED OPPORTUNITY RANKING + RISK ALLOCATION V1
# 五策略统一机会池 + 风险定仓 + 最终组合研究
#
# 这是当前五策略项目的核心架构研究。
#
# 五套冻结策略已经能够连续运行到 2026：
#
# ATRDR
# MCB
# OGR
# IFCGR
# SMV6
#
# 不重新开发策略。
# 不重新实现五套回测。
#
# AUTHORITATIVE_CONTINUOUS_PROTOCOL_V1
# 及已有连续物理账户
# 是唯一 source of truth。
#
# 本任务要验证的核心假说：
#
# H1:
# 资本不应该预先按“策略”切成固定 sleeve。
#
# H2:
# 所有策略应该共享一个最高 100% gross 的统一资金池，
# 当前合法机会根据 decision-time 可知信息竞争资本。
#
# H3:
# Ranking 只决定“谁优先”，
# Risk Engine 决定“它最多能拿多少”。
#
# H4:
# 100% 是 maximum gross，
# 不是 mandatory gross。
#
# 没有足够好的机会时必须允许持有现金。
#
# H5:
# 如果 Unified Opportunity Portfolio
# 无法稳定优于 Native，
# 则关闭该架构研究，保留 Native。
#
# 最终必须回答：
#
# 1. 五策略的机会能否放进一个统一经济比较体系？
# 2. opportunity-level ranking 是否真的有预测增量？
# 3. 风险定仓是否比固定 strategy budget 更合理？
# 4. 是否可以取消策略层资本上限？
# 5. 怎样控制单票、family、tail 和 liquidity 风险？
# 6. Unified Pool 是否真正改善整个物理账户？
#
# 研究必须执行到底。
# 不允许因为旧派生 CSV/cache 有问题就停止；
# 从 authoritative replay 修复派生层后继续。

────────────────────────────────────────
0. ENVIRONMENT
────────────────────────────────────────

Continue ONLY in:

/Users/linmei/Documents/CY-worktrees/five-strategy-capital-admission-v1

Branch:

research/five-strategy-capital-admission-v1

Expected starting HEAD:

139aca07316449ee63a6d9ae45e18bd8af7d129d

or a later descendant.

Do NOT create another branch/worktree.

First:

pwd
git branch --show-current
git rev-parse HEAD
git status --short --branch

Then continue autonomously.

────────────────────────────────────────
1. AUTHORITATIVE SYSTEM
────────────────────────────────────────

The five existing continuous backtests already exist.

DO NOT:

rebuild them as separate research strategies
replace their signal generators
replace exits
replace execution semantics
reconstruct actual funded trades from old derived tables

Use the existing authoritative replay as the source of:

signals / intents
actual fills
positions
corporate actions
native exits
cash
NAV
callback state
execution timing

Period:

2018-01-01
through
2026-09-04

2026 is YTD.

────────────────────────────────────────
2. FIRST REPAIR ONLY THE DERIVED RESEARCH LAYER
────────────────────────────────────────

Known inherited research-layer errors exist.

Repair them by adding instrumentation/export hooks to the EXISTING
authoritative replay.

Do not build a second strategy engine.

A legal capital-demand opportunity is ONLY:

NEW EXPOSURE
or
INCREASED EXPOSURE

Do NOT count:

sell
reduction
exit
partial exit
stop exit
corporate action
cash release
mark-to-market

as opportunity.

Create a causal PRE-FUNDING log immediately before physical funding.

For each increase request record:

strategy
route
symbol

signal_at
decision_at

desired_before
desired_after

requested_increase_notional

native strategy score / rank / strength
ONLY IF that variable already exists in the frozen strategy at decision time

all other already-existing decision-time strategy-native metadata

Do not invent new signal features yet.

────────────────────────────────────────
3. CAUSAL CAPITAL STATE
────────────────────────────────────────

At the exact event immediately BEFORE every exposure-increase funding decision,
record:

cash_before_event
NAV_before_event
long_market_value_before_event
gross_before_event
gross_headroom_before_event
fees_reserve
legally_fundable_cash

Existing long market value is NOT cash.

Later sells cannot fund earlier requests.

Different timestamps process chronologically.

Exact same-timestamp requests are simultaneous.

No daily-close backward contamination.

Create:

output/causal_precapital_state.csv.gz

────────────────────────────────────────
4. ACTUAL FUNDED OPPORTUNITIES
────────────────────────────────────────

For opportunities actually funded:

DO NOT shadow replay them.

Use the authoritative real lifecycle directly:

entry
position path
corporate actions
fees
native exit
realized P&L

Derive:

native_realized_return
native_realized_pnl

holding_days
capital_days

pre_exit_MFE
pre_exit_MAE

time_to_MFE
time_to_MAE

peak_unrealized_return
giveback_from_peak

max_underwater_duration

exit_reason

These must come from the actual economic holding path,
not naive exit_price / entry_price where corporate actions alter economics.

────────────────────────────────────────
5. UNFUNDED LEGAL OPPORTUNITIES
────────────────────────────────────────

ONLY legal opportunities that did not receive actual funding require
Shadow Native replay.

For those:

call the SAME frozen strategy machinery.

Use:

same entry rule
same native exit
same corporate-action accounting
same execution timing
same costs

Do not implement a second strategy.

The shadow replay exists only to answer:

"What would this legal opportunity have done if it had received normal
research capital?"

Right-censor opportunities still open at 2026-09-04.

────────────────────────────────────────
6. P0 RECONCILIATION GATE
────────────────────────────────────────

Before any ranking/risk research:

replay P0 using the instrumented authoritative scheduler.

It must reproduce authoritative continuous Native:

fills
cash
positions
gross
NAV
fees

Also require:

every authoritative exposure-increasing BUY has an upstream request;

no reduction event appears as opportunity;

SMV6 2024–2026 provenance remains complete;

IFCGR 2024–2026 coverage remains complete.

If an OLD derived CSV is wrong:
replace/regenerate that derived output and continue.

Only stop if the authoritative replay itself cannot be reconciled.

────────────────────────────────────────
7. ECONOMIC OPPORTUNITY LINEAGE
────────────────────────────────────────

Do not assume every strategy-labelled row is an independent economic opportunity.

Resolve lineage.

Especially:

ATRDR Bull ↔ MCB

OGR ↔ IFCGR

Do not deduplicate only because date+symbol match.

Use producer lineage / parent event identity.

Where supported:

Bull-type opportunity:
    MCB_confirmed = YES/NO

OGR parent opportunity:
    IFCGR_pass = YES/NO

Create:

output/economic_opportunity_master_v2.csv.gz

Capital demand must count ECONOMIC opportunities,
not duplicate strategy labels.

────────────────────────────────────────
8. THE PRIMARY UNIT OF RESEARCH
────────────────────────────────────────

The primary unit is now:

ECONOMIC OPPORTUNITY

not:

strategy CAGR

and not:

Ret1 / Ret3 / Ret5 / Ret10 / Ret20.

Main outcome is its own Native lifecycle.

For each opportunity maintain:

strategy/family
native decision-time metadata
native lifecycle return
tail path
capital occupancy
liquidity
actual funding outcome

────────────────────────────────────────
9. SIGNAL / OPPORTUNITY QUALITY
────────────────────────────────────────

For:

ATRDR Bull
ATRDR Fast Bear
ATRDR Slow Bear
MCB-confirmed Bull-type opportunities
non-MCB Bull-type opportunities
OGR
IFCGR-pass/reject subsets
SMV6

report:

opportunity count
independent decision dates

native lifecycle return:
mean
median
p10
p25
p75
p90

positive fraction
profit factor

pre-exit MAE:
median
p10/worst-decile

pre-exit MFE:
median
p75
p90

holding days
capital days

giveback

top-event concentration
top-symbol concentration

by:

2018–2021
2022–2023
2024–2026 YTD

Do not rank strategies by CAGR.

────────────────────────────────────────
10. BUILD ONLY DECISION-TIME OPPORTUNITY FEATURES
────────────────────────────────────────

For ranking, allowed information must already exist at decision time.

Preferred feature set:

A. strategy / route identity

B. native strategy score/rank/strength,
ONLY if already part of frozen strategy logic

C. MCB confirmation flag

D. IFCGR pass flag

E. existing decision-time liquidity / tradability information

F. existing holding/account context if causal

Do NOT add:

future returns
future MFE/MAE
year label
future market state
new technical indicators
new support/resistance
new ML feature library

No new alpha engineering.

────────────────────────────────────────
11. CROSS-STRATEGY SCORE CALIBRATION
────────────────────────────────────────

Raw native scores from different strategies are NOT directly comparable.

Example:

ATRDR score 0.8
SMV6 score 0.7

must NOT automatically imply ATRDR > SMV6.

Build a common economic calibration using DISCOVERY data only:

2018–2021.

For each strategy/route:

if a frozen native ranking/score exists:

split that native score into a SMALL number of monotonic buckets:

maximum 5 buckets.

Do not optimize bucket edges on outcomes.

Prefer equal-count quantile buckets.

If no native score exists:

use the strategy/route prior as one bucket.

For every bucket estimate:

median Native lifecycle return

trimmed mean Native lifecycle return

median capital-days

left-tail loss:
CVaR10 or worst-decile mean

sample count

These estimates form the cross-strategy opportunity calibration.

Do not use 2022+ to fit them.

────────────────────────────────────────
12. PREDECLARE A SMALL SET OF RANKING RULES
────────────────────────────────────────

Do NOT run dozens of formulas.

Test only THREE ranking architectures.

R0 — NO_RANKING

All acceptable opportunities have equal priority.
If capital is scarce:
pro-rata by risk-adjusted requested size.

R1 — ECONOMIC_VALUE

Rank by discovery-period:

median Native lifecycle return
/
median capital-days

using the opportunity's frozen strategy/score bucket.

R2 — RISK_ADJUSTED_ECONOMIC_VALUE

Rank by:

(median Native lifecycle return / median capital-days)
/
max(abs(discovery CVaR10), conservative risk floor)

Do not tune formula coefficients.

The risk floor must be frozen before validation.

Do not use 2022+ outcomes to choose the formula.

────────────────────────────────────────
13. QUALITY THRESHOLD / CASH OPTIONALITY
────────────────────────────────────────

100% gross is a CEILING,
not a target.

An opportunity may receive capital only if its discovery-calibrated
economic value is positive.

For R2:
risk-adjusted economic value must also be > 0.

No opportunity is purchased merely to use cash.

If no qualifying opportunities exist:

hold cash.

Do not optimize a more aggressive threshold.

────────────────────────────────────────
14. RISK MODEL — MAIN IDEA
────────────────────────────────────────

Ranking chooses:

WHO GETS CAPITAL FIRST.

Risk engine determines:

HOW MUCH EACH OPPORTUNITY MAY RECEIVE.

No strategy-level capital cap in the Unified Pool experiment.

Any strategy may theoretically consume nearly all account capital
IF it has enough separate qualifying opportunities and all risk constraints pass.

But no single opportunity may automatically consume the account.

────────────────────────────────────────
15. EX-ANTE OPPORTUNITY TAIL RISK
────────────────────────────────────────

For each discovery calibration bucket estimate:

TAIL_LOSS_ESTIMATE

using:

absolute CVaR10 of Native lifecycle return.

To reduce unstable low-risk estimates:

conservative_tail_loss
=
max(
bucket_CVaR10_abs,
parent_strategy_or_route_CVaR10_abs,
minimum_risk_floor
)

Freeze this rule using discovery only.

If sample size in a bucket < 30 completed independent opportunities:

fall back to parent strategy/route estimate.

If parent sample is also insufficient:

mark opportunity:

RISK_ESTIMATE_INSUFFICIENT

and limit it to Native requested notional only;
do not allow aggressive risk scaling.

────────────────────────────────────────
16. RISK CONTRIBUTION
────────────────────────────────────────

Define estimated opportunity tail-risk contribution:

estimated_tail_risk_i
=
allocated_notional_i / NAV
×
conservative_tail_loss_i

This is an estimated loss contribution,
not a stop-loss.

Do NOT alter Native exits.

────────────────────────────────────────
17. NATIVE-RISK ANCHOR
────────────────────────────────────────

Do not invent arbitrary portfolio risk budgets from scratch.

Using 2018–2021 authoritative Native account,
calculate the empirical distribution of PRE-TRADE estimated:

single-opportunity tail-risk contribution

same-security total tail-risk contribution

economic-family total tail-risk contribution

whole-account total estimated tail-risk

Freeze the Native discovery-period reference levels.

Create:

output/native_risk_footprint.csv

────────────────────────────────────────
18. RISK-BUDGET PROFILES
────────────────────────────────────────

Test only FOUR risk profiles,
all anchored to the Native discovery-period risk footprint:

RP75:
0.75 × Native reference risk budget

RP100:
1.00 × Native reference risk budget

RP125:
1.25 × Native reference risk budget

RP150:
1.50 × Native reference risk budget

Do not optimize fine increments.

Gross must always remain <= 100%.

These multipliers scale RISK BUDGET,
not strategy capital budgets.

────────────────────────────────────────
19. HARD DEFENSE-IN-DEPTH LIMITS
────────────────────────────────────────

Risk estimates can be wrong.

Therefore retain hard constraints independent of ranking.

A. TOTAL GROSS

<= 100%

B. CASH

>= 0

C. NO LEVERAGE

D. SINGLE SECURITY

A security may not exceed BOTH:

1. its risk-contribution cap;
2. a hard notional concentration cap.

Research only these discovery-predeclared hard single-security ceilings:

10%
15%
20% NAV

Do not use finer values.

E. LIQUIDITY

No allocation may exceed a capacity ceiling that is inconsistent with
existing validated liquidity data.

Use capacity only where registered data is reliable.

Do not invent market impact.

────────────────────────────────────────
20. ECONOMIC FAMILY RISK
────────────────────────────────────────

Use source/economic lineage,
not arbitrary correlation clustering.

At minimum track:

DEMAND:
ATRDR Bull + MCB-related exposure

ATRDR_BEAR:
ATRDR Fast Bear + Slow Bear

GAP:
OGR / IFCGR

ETF:
SMV6

If later lineage proves a different classification,
document it before outcome-bearing portfolio search.

Do not make clusters by looking at future returns.

Family risk contribution is the sum of estimated opportunity tail risks
inside the active family.

Family budget is anchored to Native discovery risk footprint
and multiplied by RP75/RP100/RP125/RP150.

No strategy-level budget.

────────────────────────────────────────
21. SAME SECURITY / DUPLICATE EXPOSURE
────────────────────────────────────────

If multiple strategy engines request the same security at the same causal time:

do NOT treat them as independent diversification.

Aggregate same-security economic exposure for:

single-security risk
gross
liquidity

If lineage shows the requests represent the same underlying economic opportunity,
deduplicate before capital demand.

If economically distinct but same security:
retain attribution labels,
but aggregate physical position/risk.

────────────────────────────────────────
22. LIQUIDITY RISK
────────────────────────────────────────

For stocks use where available:

order notional / daily amount
order notional / ADV20

For SMV6 preserve validated execution-window minute-volume semantics.

Liquidity does NOT rank alpha quality.

It only caps executable notional.

Do not modify historical Native account for missing denominators.

For new Unified Pool portfolios:

if reliable denominator is unavailable,
apply the conservative Native executable notional ceiling
rather than inventing capacity.

────────────────────────────────────────
23. UNIFIED ALLOCATION ALGORITHM
────────────────────────────────────────

At every causal decision timestamp:

1. collect all legal EXPOSURE-INCREASE opportunities;

2. resolve economic duplicates / lineage;

3. map each opportunity to discovery-frozen quality bucket;

4. estimate:
   economic value
   tail risk
   expected capital occupancy;

5. discard opportunities failing the minimum positive-value threshold;

6. rank remaining opportunities according to R0/R1/R2;

7. allocate from highest rank downward,
subject to:

   opportunity risk budget
   same-security risk cap
   economic-family risk cap
   hard single-security notional cap
   liquidity cap
   available cash
   gross <= 100%

8. if multiple opportunities have exact equal rank/timestamp:
   deterministic pro-rata allocation;

9. stop allocating when:
   no remaining qualifying opportunity
   OR
   cash/gross/risk budget is exhausted;

10. remaining capital stays cash.

Existing positions are NEVER resized merely because a new opportunity appears.

Native reductions/exits remain unchanged.

────────────────────────────────────────
24. DO NOT FORCE FULL INVESTMENT
────────────────────────────────────────

This is a hard semantic rule.

Examples:

one strong OGR stock signal
≠
100% OGR position.

If its risk/security cap permits only 8%:
allocate 8%.

If ten independent high-quality SMV6 opportunities jointly satisfy risk limits:
SMV6 may occupy a much larger fraction,
potentially approaching the account gross ceiling.

The strategy itself has no fixed sleeve limit.

Opportunity/risk constraints determine capital.

────────────────────────────────────────
25. PORTFOLIO ARCHITECTURES TO COMPARE
────────────────────────────────────────

Do NOT compare only one new system.

Required architectures:

P0_NATIVE

Exact authoritative Native baseline.

P1_UNIFIED_RISK_ONLY

Unified capital pool.
NO predictive ranking.
Use R0.
Risk-based sizing and caps only.

This isolates the value of the Risk Engine.

P2_UNIFIED_RANKING

Unified pool.
R1 or R2 ranking.
Same risk constraints.

This isolates ranking incrementality.

P3_UNIFIED_RANKING_FAMILY_RISK

Unified ranking
+
economic-family risk budgets
+
single-security/liquidity defense.

This is the complete architecture.

Also retain any already-authoritative fixed-budget portfolio result
ONLY as a reference benchmark if it can be reconciled without new engineering.

Do not delay the task to rebuild an old invalid fixed-budget study.

────────────────────────────────────────
26. DISCOVERY
────────────────────────────────────────

Use ONLY:

2018-01-01
through
2021-12-31

for:

quality calibration
score buckets
tail-risk estimates
Native risk footprint
risk budget references
ranking-rule discovery
hard-cap candidate evaluation

This is discovery/in-sample research.

Do not claim validation.

────────────────────────────────────────
27. FREEZE CANDIDATES
────────────────────────────────────────

The total search space must remain small.

Candidate dimensions:

Ranking:
R0 / R1 / R2

Risk profile:
RP75 / RP100 / RP125 / RP150

single-security hard cap:
10% / 15% / 20%

family risk:
OFF / ON

This is a maximum theoretical grid of 72 configurations.

Do not add more dimensions.

Do not add thresholds after viewing outcomes.

Run all valid configurations on the actual physical account.

────────────────────────────────────────
28. DISCOVERY METRICS
────────────────────────────────────────

For each architecture/configuration report:

CAGR
MaxDD
CVaR5
Sharpe

average gross
P95 gross
cash ratio

fees
turnover

worst month

max single-security exposure

max family exposure

estimated tail-risk budget utilization

opportunity count
funded opportunity count
rejected-for-quality count
rejected-for-risk count
rejected-for-liquidity count

top-5 day concentration
top-5 event concentration
top-5 symbol concentration

Do not maximize gross.

────────────────────────────────────────
29. PARETO FRONTIER
────────────────────────────────────────

Build discovery Pareto frontier using:

higher CAGR

lower MaxDD

lower CVaR5

higher Sharpe

lower concentration

Do NOT include average gross as something that must be maximized.

Cash is allowed to be valuable.

Create:

output/unified_discovery_pareto.csv

────────────────────────────────────────
30. FREEZE VALIDATION CANDIDATES
────────────────────────────────────────

Freeze:

P0 Native

plus up to:

3 candidates under <=5% discovery MaxDD

3 candidates under <=8%

3 candidates under <=10%

3 candidates under <=15%

Require candidates to be economically distinct.

Do not choose 12 near-identical parameter variants.

Within each band:

Pareto-valid first.

Then prefer:

Sharpe
then CAGR

subject to concentration validity.

Freeze before opening 2022–2023 results.

────────────────────────────────────────
31. VALIDATION 2022–2023
────────────────────────────────────────

Run frozen candidates unchanged.

Do not:

recalibrate buckets
change ranking
change risk budgets
change family definitions
change security cap

Report:

return
CAGR
MaxDD
CVaR
Sharpe
cash ratio
average gross
worst month
concentration

Validation status:

PASS
MARGINAL
FAIL

A candidate that materially improves discovery but collapses in 2022–23
must not be rescued.

────────────────────────────────────────
32. POST-HOC 2024–2026 DIAGNOSTIC
────────────────────────────────────────

For validation survivors run unchanged:

2024
2025
2026 YTD

We have already seen these years.

Label:

POST_HOC_ROLLFORWARD_DIAGNOSTIC

Do not tune anything.

Report separately.

If a candidate catastrophically fails here:
do not recommend it for shadow.

────────────────────────────────────────
33. DOES RANKING ACTUALLY ADD VALUE?
────────────────────────────────────────

This is mandatory.

Compare matched risk settings:

P1 RISK_ONLY
vs
P2/P3 RANKING

Same:

risk profile
security cap
family cap where applicable

Measure incremental:

P&L
CAGR
MaxDD
CVaR
Sharpe

quality of funded opportunities

quality of rejected opportunities

capital-days

If ranking does not add stable value beyond Risk Engine:

verdict:

RANKING_NOT_INCREMENTAL

Then final architecture should use neutral/pro-rata risk allocation
rather than a predictive ranking model.

Do NOT force ranking to survive.

────────────────────────────────────────
34. DOES THE RISK ENGINE ACTUALLY ADD VALUE?
────────────────────────────────────────

Compare:

P0 Native

vs

P1 Unified Risk Only

Main question:

Does risk-based opportunity sizing improve:

tail losses
MaxDD
CVaR
concentration

without destroying returns?

If Risk Engine itself fails:

do not keep P2/P3 merely because ranking looked good.

────────────────────────────────────────
35. CAN A SINGLE STRATEGY NATURALLY OCCUPY MOST OF THE BOOK?
────────────────────────────────────────

For every candidate calculate daily capital attribution:

ATRDR share
MCB share
Gap share
SMV6 share
cash

Report distributions:

p50
p75
p90
p95
max

A strategy is allowed to exceed:

25%
50%
75%

if its active opportunities pass all risk constraints.

Count days where each strategy exceeds these levels.

This is diagnostic.

Do not impose a strategy cap simply because the share looks high.

Instead inspect:

tail risk
single-security concentration
family concentration
liquidity

during those episodes.

────────────────────────────────────────
36. EXTREME 100%-ELIGIBILITY TEST
────────────────────────────────────────

Explicitly verify:

There is NO hard strategy sleeve cap.

For each strategy identify historical dates where,
under the Unified system,
it would be the dominant source of qualifying opportunities.

Ask:

Could this strategy legally consume:

>50%
>75%
approach 100%

while still satisfying:

single-security risk
family risk
liquidity
gross
cash constraints?

Report why it could or could not.

Do NOT force any strategy to reach 100%.

This tests the architecture semantics.

────────────────────────────────────────
37. RISK EPISODE ATTRIBUTION
────────────────────────────────────────

For each finalist identify worst 5 drawdown episodes.

Report:

peak
trough
recovery

active opportunities

strategy contribution

family contribution

single-security contribution

estimated tail-risk budget before drawdown

actual realized loss

liquidity state

Ranking rank at entry

Ask:

Did the Risk Engine underestimate a family/security?

Did ranking select poor opportunities?

Or was the loss within expected tail budget?

Create:

output/finalist_risk_episode_attribution.csv

────────────────────────────────────────
38. MODEL-RISK CHECK
────────────────────────────────────────

Tail estimates can be wrong.

For finalists compare:

estimated pre-trade tail risk

vs

subsequent realized Native lifecycle loss.

Report calibration by decile.

Flag:

RISK_UNDERESTIMATION

if actual left-tail systematically exceeds predicted risk.

Do NOT recalibrate using validation/diagnostic years.

This is diagnostic.

────────────────────────────────────────
39. CONCENTRATION ROBUSTNESS
────────────────────────────────────────

For finalists report:

remove best 1 day
remove best 5 days

remove top 1 event
remove top 5 events

remove top 1 symbol
remove top 5 symbols

Do not rerun allocation.

Diagnostic attribution only.

Flag excessive dependence.

────────────────────────────────────────
40. COST ROBUSTNESS
────────────────────────────────────────

Finalists only:

BASE COST
1.5x cost
2.0x cost

Do not alter signals or ranking.

Report:

return
CAGR
MaxDD
Sharpe
net P&L

────────────────────────────────────────
41. CAPACITY
────────────────────────────────────────

Finalists only.

Use registered liquidity data.

Report by strategy:

order / daily amount
order / ADV20

SMV6 / validated windows:
order / execution-window volume

p50
p75
p90
p95
p99
max

missing denominator count

Also descriptive:

1x account
2x
5x
10x

Do not claim those sizes are executable without impact model.

────────────────────────────────────────
42. FINAL PORTFOLIO DECISION
────────────────────────────────────────

Allowed final decisions:

KEEP_NATIVE

UNIFIED_RISK_ONLY_SHADOW_CANDIDATE

UNIFIED_RANKING_SHADOW_CANDIDATE

UNIFIED_RANKING_FAMILY_RISK_SHADOW_CANDIDATE

NO_ROBUST_UNIFIED_POOL_IMPROVEMENT

Ranking may fail while Risk Engine succeeds.

That is a valid result.

Do not force the most complex architecture.

────────────────────────────────────────
43. FINAL SYSTEM SPEC
────────────────────────────────────────

If a Unified architecture qualifies,
the report must freeze exactly:

ranking rule:
R0 / R1 / R2

risk profile:
RP75 / RP100 / RP125 / RP150

single-security hard cap:
10 / 15 / 20%

family-risk cap:
ON/OFF

quality threshold:
positive discovery-calibrated value only

total gross:
<=100%

cash:
>=0

strategy caps:
NONE

native exits:
UNCHANGED

liquidity rules:
exact registered rules used

Then state:

NO STRATEGY HAS A PREALLOCATED SLEEVE.

Capital is assigned to current qualifying opportunities.

────────────────────────────────────────
44. REQUIRED OUTPUTS
────────────────────────────────────────

Create:

research/unified_opportunity_risk_v1/

REPORT.md
REPRODUCTION_COMMANDS.md
input_manifest.json

contracts/
    unified_opportunity_risk_v1.json

output/
    p0_reconciliation.csv

    economic_opportunity_master_v2.csv.gz
    causal_precapital_state.csv.gz

    actual_funded_lifecycle.csv.gz
    unfunded_shadow_lifecycle.csv.gz

    native_opportunity_quality.csv

    discovery_quality_calibration.csv
    discovery_tail_risk_calibration.csv
    native_risk_footprint.csv

    unified_discovery_grid.csv
    unified_discovery_pareto.csv

    frozen_validation_candidates.csv
    validation_2022_2023.csv
    rollforward_2024_2026.csv

    ranking_incrementality.csv
    risk_engine_incrementality.csv

    daily_strategy_capital_share.csv.gz

    finalist_risk_episode_attribution.csv
    tail_risk_calibration_diagnostic.csv

    finalist_concentration_stress.csv
    finalist_cost_stress.csv
    finalist_capacity.csv

    final_architecture_comparison.csv
    final_system_spec.json

    requirement_test_coverage.csv
    output_manifest.sha256

────────────────────────────────────────
45. TESTS
────────────────────────────────────────

At minimum test:

1. existing five strategy engines unchanged
2. authoritative Native replay unchanged
3. no reduction counted as opportunity
4. every funded increase has upstream request
5. actual funded lifecycle comes from authoritative holdings
6. shadow only used for unfunded opportunities
7. no future data in ranking
8. no future data in tail-risk estimate
9. 2022+ never enters discovery calibration
10. native raw scores never compared across strategies without calibration
11. no strategy-level capital cap in Unified system
12. gross <=100%
13. cash >=0
14. no leverage
15. same-security risk aggregated
16. economic duplicate risk not double-counted
17. family risk correctly aggregated
18. later sale cannot fund earlier request
19. quality threshold may leave cash idle
20. ranking order deterministic
21. equal-rank allocation deterministic
22. native exits unchanged
23. existing positions not resized simply because new signal arrives
24. P0 exact reconciliation
25. validation candidates frozen
26. post-2023 results cannot modify parameters
27. deterministic rerun
28. input hashes unchanged

Retain relevant inherited regression tests.

────────────────────────────────────────
46. DO NOT STOP ON DERIVED-DATA ERRORS
────────────────────────────────────────

If an inherited research CSV/cache is wrong:

regenerate it from the authoritative replay.

Do not stop.

Only stop if:

the authoritative five-strategy replay itself cannot be reproduced
or a genuinely required registered raw input is unavailable.

If a specific architecture fails:
continue testing the remaining architectures.

Do not stop the entire task because one hypothesis fails.

────────────────────────────────────────
47. FINAL RESPONSE FORMAT
────────────────────────────────────────

Return:

ENVIRONMENT_VALID:
BRANCH:
START_HEAD:
END_HEAD:
TASK_STATUS:

FROZEN_STRATEGIES_MODIFIED: NO
NEW_ALPHA_ADDED: NO
NATIVE_EXITS_CHANGED: NO
STRATEGY_CAPS_IN_UNIFIED_POOL: NONE
MAX_TOTAL_GROSS: 100%
PUSH:

P0_RECONCILIATION:

LEGAL_ECONOMIC_OPPORTUNITIES:
ACTUAL_FUNDED_LIFECYCLES:
UNFUNDED_SHADOW_LIFECYCLES:

Then:

RISK_ENGINE_RESULT:
RANKING_INCREMENTALITY_RESULT:
FAMILY_RISK_RESULT:

BEST_5PCT_DD_ARCHITECTURE:
BEST_8PCT_DD_ARCHITECTURE:
BEST_10PCT_DD_ARCHITECTURE:
BEST_15PCT_DD_ARCHITECTURE:

For each finalist report:

architecture
ranking rule
risk profile
single-security cap
family-risk ON/OFF

2018–2021
2022–2023
2024
2025
2026 YTD
full period

CAGR
MaxDD
CVaR
Sharpe
average gross
cash ratio

max strategy capital share
max single security
max family exposure

cost stress
concentration
capacity

Then specifically:

ATRDR_MAX_CAPITAL_SHARE_OBSERVED:
MCB_MAX_CAPITAL_SHARE_OBSERVED:
GAP_MAX_CAPITAL_SHARE_OBSERVED:
SMV6_MAX_CAPITAL_SHARE_OBSERVED:

DAYS_ANY_SINGLE_STRATEGY_GT50:
DAYS_ANY_SINGLE_STRATEGY_GT75:

Then:

FINAL_DECISION:

FINAL_SYSTEM_SPEC:

RANKING_RULE:
RISK_PROFILE:
SINGLE_SECURITY_CAP:
FAMILY_RISK_CAP:
QUALITY_THRESHOLD:
STRATEGY_CAPS: NONE
TOTAL_GROSS_CAP: 100%
CASH_ALLOWED: YES

NEXT_ACTION:

If robust:
freeze for forward shadow.

If not:
KEEP_NATIVE and close this Unified Pool research.

Finally:

tests
input hashes
contract SHA256
manifest
report path
rerun command
commit
remote HEAD
PUSH YES/NO

────────────────────────────────────────
48. GIT
────────────────────────────────────────

At completion:

run tests
verify hashes
verify deterministic outputs
git status

Commit only this task and necessary research-layer instrumentation.

Suggested commit:

research: test unified opportunity risk allocation

Normal push to current branch.

Never force push.