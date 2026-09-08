# PORTFOLIO CLOSURE DATA REPAIR + AUTOMATIC RESUME
#
# 当前不是新研究任务。
#
# FIVE STRATEGY PORTFOLIO CLOSURE V1 的研究设计保持不变。
# 当前唯一工作：
#
# 1. 修复已确认的 opportunity 语义错误；
# 2. 实现真实 independent shadow-native lifecycle replay；
# 3. 重建 causal decision-time capital state / capital conflict；
# 4. 完成输入验收；
# 5. 验收 PASS 后自动冻结原 portfolio-closure contract；
# 6. 自动继续并完成既定联合资本配置研究。
#
# 不允许修完数据后再次停下来等待用户 Prompt。
#
# 除非发现新的、会改变账户经济身份的真实 blocker，
# 否则必须一直执行到最终 portfolio decision。

Work ONLY in:

/Users/linmei/Documents/CY-worktrees/five-strategy-capital-admission-v1

Branch:

research/five-strategy-capital-admission-v1

Expected current HEAD:

139aca07316449ee63a6d9ae45e18bd8af7d129d

or a later descendant.

Do NOT create another branch/worktree.

Do NOT restart research from scratch.

Read first:

research/portfolio_closure_v1/REPORT.md
research/portfolio_closure_v1/output/opportunity_semantic_errors.csv
research/portfolio_closure_v1/REPRODUCTION_COMMANDS.md

Also read the already recovered SMV6 provenance artifacts
and authoritative continuous-account artifacts.

First print:

ENVIRONMENT_VALID
BRANCH
START_HEAD
WORKTREE_STATUS

Then continue autonomously.

────────────────────────────────────────
1. DO NOT CHANGE THE RESEARCH QUESTION
────────────────────────────────────────

The final research question remains:

Given the five already-working frozen strategies:

ATRDR
MCB
OGR
IFCGR
SMV6

what fixed, causal, executable capital-budget structure produces the best robust
whole-account return / drawdown / tail / capital-efficiency tradeoff?

Do NOT reopen:

signal-priority prediction
regime routing
new alpha
new exits
new universes
adaptive support lines
Full Book normalization

The intended portfolio experiment remains:

ENTRY_ONLY_FIXED_BUDGET_MULTIPLIERS
+
CAUSAL_PRO_RATA_RATIONING_WHEN_CASH_SCARCE

with coarse joint multiplier search.

────────────────────────────────────────
2. REPAIR A — DEFINE AN OPPORTUNITY CORRECTLY
────────────────────────────────────────

The previous mixed stream incorrectly included 24 actual reduction fills.

Create one strict semantic contract.

A PRE-CAPITAL OPPORTUNITY is ONLY an event that can causally create
NEW OR INCREASED economic exposure.

Allowed opportunity types:

NEW_ENTRY_REQUEST
EXPOSURE_INCREASE_REQUEST

Not opportunities:

REDUCE_POSITION
PARTIAL_SELL
FULL_EXIT
STOP_EXIT
NATIVE_EXIT
CORPORATE_ACTION_ONLY
REBALANCE_REDUCTION
CASH_RELEASE
MARK_TO_MARKET_CHANGE

A reduction/sell is an account state transition,
not a new capital-demand opportunity.

Create:

research/portfolio_closure_v1/contracts/opportunity_semantics_v2.json

Before using outcomes, freeze:

- opportunity definition
- increase/decrease classification
- lineage rules
- decision timestamp
- funding timestamp
- capital-state timestamp semantics

Compute SHA256.

────────────────────────────────────────
3. REBUILD THE PRE-CAPITAL OPPORTUNITY STREAM
────────────────────────────────────────

Rebuild from authoritative PRE-FUNDING intents / desired-position transitions.

Do NOT derive opportunities from fills.

For each event calculate:

previous_desired_exposure
new_desired_exposure
delta_desired_exposure

Classification:

delta > 0:
    EXPOSURE_INCREASE

delta < 0:
    EXPOSURE_REDUCTION

delta == 0:
    NO_CAPITAL_CHANGE

Only EXPOSURE_INCREASE enters the opportunity population.

Preserve reductions/exits in a separate state-transition table.

Create:

output/precapital_opportunities_v2.csv.gz
output/non_opportunity_state_transitions.csv.gz

Required opportunity fields:

opportunity_id
economic_opportunity_id
strategy
route
symbol

signal_at
decision_at

desired_before
desired_after
requested_increase_notional

native_account_id

eligibility_source
producer_source

actual_funded_notional
actual_fill_notional

actual_funding_status

Do not count an exit and a later entry as the same event.

────────────────────────────────────────
4. RECONCILE OPPORTUNITY COUNTS TO AUTHORITATIVE ACCOUNTS
────────────────────────────────────────

For every:

strategy × year

report:

increase opportunities
reduction transitions
actual BUY / exposure-increase fills
actual SELL / reduction fills

and reconciliation.

Create:

output/opportunity_semantic_reconciliation.csv

Hard requirements:

- all actual exposure-increasing Native BUYs have upstream opportunity provenance;
- reduction fills never appear as opportunity rows;
- SMV6 recovered 2024–2026 provenance remains matched;
- IFCGR coverage remains closed.

Do not require every opportunity to produce a fill.

Unfunded/rejected opportunities must remain.

────────────────────────────────────────
5. REPAIR B — REAL SHADOW NATIVE LIFECYCLE
────────────────────────────────────────

The previous shadow table is invalid for lifecycle research because it did not
independently replay legal opportunities and MFE/MAE remained empty.

Implement an ACTUAL independent opportunity replay.

For every legal pre-capital exposure-increase opportunity:

clone only the causal strategy state required at decision_at.

Then fund that opportunity with a standard research notional
without changing the frozen strategy rule.

From that point onward execute:

native entry timing
native position semantics
native exit logic
native stop/state logic
corporate actions
fees
lot rules
execution timing

until native capital release.

Do NOT use portfolio future funding decisions to determine the shadow exit.

Do NOT replace native exits with fixed horizon exits.

────────────────────────────────────────
6. SHADOW RESEARCH NOTIONAL
────────────────────────────────────────

Use a standardized notional solely to make opportunity outcomes comparable.

Prefer:

the strategy's actual Native requested notional normalized to a fixed base

OR

a standard 1,000,000 CNY research account if that is already the established
route-only convention.

Choose ONE semantic method before reading outcomes.

Freeze it in the contract.

Returns / MFE / MAE must not depend on arbitrary account wealth scaling
except where real native execution constraints make that unavoidable.

Report the chosen convention explicitly.

────────────────────────────────────────
7. SHADOW LIFECYCLE PATH
────────────────────────────────────────

For every opportunity produce a true marked economic P&L path from:

entry
through
native exit

including where applicable:

price changes
cash dividends
share conversions
corporate-action inventory
fees
quantity changes

Required:

entry_at
exit_at
exit_reason

entry_notional

native_realized_return
native_realized_pnl

holding_days
capital_days

pre_exit_MFE
pre_exit_MAE

time_to_MFE
time_to_MAE

peak_unrealized_return

giveback_from_peak_to_exit

max_underwater_duration

open_at_2026_cutoff

MFE / MAE must NOT be NA for normally observable completed opportunities.

If price-path data is genuinely missing for individual events,
mark the precise missing-data reason.

Do not silently emit blanket NA columns.

Create:

output/shadow_native_lifecycle_v2.csv.gz

────────────────────────────────────────
8. FUNDED TRADE IDENTITY IS THE SHADOW REPLAY TEST
────────────────────────────────────────

For every opportunity that the authoritative Native account actually funded,
the independent shadow replay must reproduce Native economics
under equivalent notional semantics.

Compare:

entry timestamp
exit timestamp
exit reason

return

corporate-action sequence

fees

P&L normalized to common notional

Create:

output/shadow_native_identity_v2.csv

Hard gate:

completed funded opportunities must reconcile within registered tolerance.

If not:

do not continue.

But identify and fix replay semantics first;
do not immediately declare generic BLOCKED.

────────────────────────────────────────
9. RIGHT-CENSORING
────────────────────────────────────────

If an opportunity remains open at:

2026-09-04

do NOT invent an exit.

Set:

open_at_cutoff = TRUE

Use its marked NAV path for account reconciliation.

Exclude it only from metrics requiring a completed native trade,
while retaining it for capital occupancy / exposure calculations.

────────────────────────────────────────
10. REPAIR C — CAUSAL PHYSICAL CAPITAL STATE
────────────────────────────────────────

Discard the previous conflict table as an economic input.

It used:

end-of-day cash

and treated:

holding market value

as if it were available funding capacity.

Both semantics are invalid.

Rebuild capital state from the authoritative physical-account event timeline.

For every decision event record state IMMEDIATELY BEFORE that event:

decision_at

cash_before_event
NAV_before_event
long_market_value_before_event
gross_before_event

gross_limit_notional
gross_headroom_before_event

fees_reserve

actual_cash_fundable
actual_gross_fundable

legal_fundable_notional

The available capital for a new long request is bounded by:

cash actually available before the event

AND

remaining legal gross headroom

after accounting for fees / lot semantics.

Existing long market value is NOT available cash.

No borrowing against holdings.

No negative cash.

────────────────────────────────────────
11. SAME-DAY EVENT ORDER
────────────────────────────────────────

Preserve actual causal event order.

Do NOT use one daily snapshot for all decisions.

If events occur at:

09:35
10:10
14:25
close
etc.

each event must see only state produced by events completed before it.

If multiple requests share the exact same causal decision timestamp:

treat them as simultaneous for pro-rata funding.

If timestamps differ:

process chronologically.

A later sell may release cash for later requests.

A later sell may NOT fund an earlier request.

Add prefix-invariance tests.

────────────────────────────────────────
12. CAPITAL RELEASE
────────────────────────────────────────

On:

partial reduction
full exit
dividend cash credit
other legitimate cash-credit events

update physical cash at the actual causal timestamp.

Cash becomes fundable only after the event is legally effective.

Pending corporate-action shares are not cash.

Unsettled/non-tradable inventory is not cash.

────────────────────────────────────────
13. TRUE CAPITAL CONFLICT
────────────────────────────────────────

Now recompute capital conflict.

At every causal decision timestamp:

sum distinct legal exposure-increase requests.

Use:

actual_cash_fundable
actual_gross_fundable

to determine whether requests are constrained.

Do not double-count economic variants if lineage says one underlying request.

Do not count exits/reductions as demand.

Create:

output/capital_conflict_timeline_v2.csv
output/capital_conflict_summary_v2.csv

For each constrained event report:

requested
fundable
shortfall

which strategies requested

what was funded

what was partially funded

what was rejected for capital reasons

Separate:

NO_CASH
GROSS_LIMIT
LOT_OR_FEE_SHORTFALL
STRATEGY_NATIVE_RESTRICTION
EXECUTION_FAILURE
OTHER

Only the first three are portfolio-capital scarcity.

────────────────────────────────────────
14. CAPITAL-STATE IDENTITY TEST
────────────────────────────────────────

Replay P0 Native from this event-driven scheduler.

It must reproduce authoritative physical Native:

cash
positions
fills
NAV
gross

through the full continuous period.

Hard requirement:

P0_RECONCILIATION = PASS

before any multiplier experiment.

This single test is the authoritative validation of the repaired scheduler.

────────────────────────────────────────
15. INPUT ACCEPTANCE GATE
────────────────────────────────────────

Only after Sections 2–14 PASS may the portfolio-closure experiment start.

Required status:

OPPORTUNITY_SEMANTICS: PASS
SHADOW_NATIVE_REPLAY: PASS
CAPITAL_STATE_CAUSALITY: PASS
P0_NATIVE_RECONCILIATION: PASS
SMV6_POST2023_COVERAGE: PASS
IFCGR_POST2023_COVERAGE: PASS

Then freeze:

five_strategy_portfolio_closure_v1.json

using the experiment design already specified.

Do NOT change research hypotheses based on repaired outcomes.

────────────────────────────────────────
16. THEN AUTOMATICALLY RUN THE EXISTING PORTFOLIO CLOSURE
────────────────────────────────────────

Do NOT stop and request another Prompt.

Execute the already specified portfolio program:

A. opportunity economics

B. strategy relationship / tail overlap

C. OGR vs IFCGR final Gap decision

D. MCB incremental portfolio value after ATRDR

E. valid Native subsets

F. leave-one-strategy-out

G. joint fixed-budget multiplier grid

H. discovery Pareto frontier

I. frozen candidates

J. 2022–2023 historical confirmation

K. 2024–2026 post-hoc rollforward diagnostic

L. strategy capital-response curves

M. ATRDR route attribution

N. finalist cost stress

O. finalist concentration stress

P. leave-year diagnostic

Q. finalist capacity

R. final portfolio decision

Do not substitute a partial diagnostic for this list.

────────────────────────────────────────
17. PORTFOLIO UNITS
────────────────────────────────────────

Use:

ATRDR
MCB
Gap
SMV6

where Gap variant is:

NONE
OGR
IFCGR

Do not independently optimize ATRDR Bull/Fast/Slow.

They remain attribution routes.

Do not simultaneously fund OGR and IFCGR duplicates as separate sleeves.

────────────────────────────────────────
18. PORTFOLIO FUNDING
────────────────────────────────────────

Use:

ENTRY_ONLY_FIXED_BUDGET_MULTIPLIER

For each strategy:

new requested notional
=
Native exposure-increase request
×
fixed multiplier

Existing positions are NOT resized when unrelated new opportunities arrive.

Native reductions/exits continue unchanged.

────────────────────────────────────────
19. FIXED MULTIPLIER GRID
────────────────────────────────────────

Use only:

0.0
0.5
1.0
1.5
2.0

for:

ATRDR
MCB
selected Gap
SMV6

No finer optimization.

0 = exclude
0.5 = reduced
1 = Native
1.5 = moderate extra budget
2 = strong diagnostic budget

Run the FULL VALID JOINT GRID.

Do not optimize one strategy at a time and combine later.

────────────────────────────────────────
20. CASH SCARCITY FUNDING RULE
────────────────────────────────────────

The previous opportunity-ranking lane is CLOSED.

Do NOT predict which signal will win.

When simultaneous same-timestamp legal exposure-increase requests exceed
available causal physical capital:

use deterministic:

CAUSAL_PRO_RATA_RATIONING

based on requested notional.

For different timestamps:

chronological order.

This lets fixed strategy budgets be tested without introducing
an unvalidated forecasting model.

────────────────────────────────────────
21. DISCOVERY / CONFIRMATION / DIAGNOSTIC
────────────────────────────────────────

DISCOVERY:

2018–2021

Use joint portfolio grid.

CONFIRMATION:

2022–2023

Frozen candidates only.

POST-HOC DIAGNOSTIC:

2024
2025
2026 YTD

No tuning using post-2021 results.

────────────────────────────────────────
22. JOINT PORTFOLIO SEARCH
────────────────────────────────────────

For every valid capital vector:

ATRDR_multiplier
MCB_multiplier
Gap_variant
Gap_multiplier
SMV6_multiplier

run the REAL physical account.

Metrics:

CAGR
MaxDD
CVaR5
Sharpe

average gross
P95 gross
cash ratio

turnover
fees

worst month

max single-security exposure
max family exposure

top-5 day concentration
top-5 event concentration

Do not synthesize portfolio results by adding standalone sleeves.

────────────────────────────────────────
23. PARETO + RISK BANDS
────────────────────────────────────────

Construct non-dominated discovery frontier.

Then report robust candidates under discovery-period MaxDD bands:

<=5%
<=8%
<=10%
<=15%

For each band:

retain up to 3 economically distinct candidates.

Among non-dominated valid candidates:

prefer Sharpe,
then CAGR,

subject to concentration / causal-accounting validity.

Do not maximize gross utilization.

Cash is not automatically bad.

────────────────────────────────────────
24. CAPITAL RESPONSE
────────────────────────────────────────

Using the JOINT physical grid derive whole-account marginal effects for:

0 → 0.5
0.5 → 1
1 → 1.5
1.5 → 2

for each strategy.

Report:

incremental P&L
incremental capital-days

incremental MaxDD
incremental CVaR
incremental worst-month loss

incremental concentration

and displacement of other strategies.

This is how signal quality connects to portfolio capital.

────────────────────────────────────────
25. REQUIRED FINAL CAPITAL DECISION
────────────────────────────────────────

For each production strategy report:

ATRDR:
KEEP / REDUCE / NATIVE / INCREASE / EXCLUDE

MCB:
KEEP / REDUCE / NATIVE / INCREASE / EXCLUDE

Gap:
NONE / OGR / IFCGR

Gap capital:
REDUCE / NATIVE / INCREASE

SMV6:
KEEP / REDUCE / NATIVE / INCREASE / EXCLUDE

And give the exact finalist multiplier.

Do not hide behind generic role labels.

────────────────────────────────────────
26. ROBUSTNESS
────────────────────────────────────────

For finalists ONLY run:

1. cost stress:
   base
   1.5x cost
   2x cost

2. concentration:
   remove best 1 day
   best 5 days
   top 1 event
   top 5 events
   top 1 symbol
   top 5 symbols

3. leave-one-year:
   within 2018–2023
   do not retune

4. capacity:
   daily amount
   ADV20
   validated minute denominator where available

No need to capacity-test rejected grid cells.

────────────────────────────────────────
27. FINAL DECISION
────────────────────────────────────────

Allowed:

KEEP_CURRENT_NATIVE

SIMPLIFY_PORTFOLIO_KEEP_NATIVE_SIZING

FIXED_BUDGET_REALLOCATION_SHADOW_CANDIDATE

MULTIPLE_RISK_BAND_SHADOW_CANDIDATES

NO_ROBUST_PORTFOLIO_IMPROVEMENT

A non-Native portfolio may qualify only if:

- discovered using 2018–2021 only;
- survives 2022–2023 without tuning;
- does not catastrophically fail 2024–2026 diagnostic;
- improves whole-account risk-adjusted economics;
- is not merely higher gross;
- is not dominated by one year/day/event/symbol;
- capacity is not obviously impossible.

No production authorization.

────────────────────────────────────────
28. DO NOT STOP FOR THESE REASONS
────────────────────────────────────────

Do NOT stop merely because:

one strategy is sparse;
one metric is inconvenient;
an old derived CSV is invalid;
a previous research output must be regenerated;
the joint grid takes longer than a summary calculation;
Native turns out strong;
one candidate fails;
a role is ambiguous.

Fix derived data from authoritative sources and continue.

Only stop if:

authoritative strategy/account identity itself cannot be reconstructed
or a required raw/registered source is genuinely unavailable.

If stopping:

name the exact missing source or identity failure.

────────────────────────────────────────
29. REQUIRED REPAIR OUTPUTS
────────────────────────────────────────

Create/update:

research/portfolio_closure_v1/output/

opportunity_semantic_reconciliation.csv
precapital_opportunities_v2.csv.gz
non_opportunity_state_transitions.csv.gz

shadow_native_lifecycle_v2.csv.gz
shadow_native_identity_v2.csv

capital_conflict_timeline_v2.csv
capital_conflict_summary_v2.csv

p0_native_reconciliation.csv

input_acceptance_v2.json

Then create all previously required portfolio closure outputs.

────────────────────────────────────────
30. TESTS
────────────────────────────────────────

At minimum add:

1. reduction fill cannot become opportunity
2. exit cannot create capital demand
3. increase intent creates opportunity
4. all Native BUYs reconcile upstream
5. shadow funded replay matches Native lifecycle
6. MFE/MAE populated for observable completed paths
7. corporate actions handled in path P&L
8. decision-time cash precedes decision
9. later sell cannot fund earlier buy
10. existing market value not counted as cash
11. gross headroom correct
12. simultaneous requests pro-rata correctly
13. chronological requests see updated causal state
14. P0 reproduces authoritative Native
15. cash never negative
16. gross never >100%
17. multiplier 1.0 preserves Native request
18. multiplier 0 creates no target entries
19. old positions not resized by new opportunity
20. discovery excludes 2022+
21. validation candidates frozen
22. deterministic rerun
23. input hashes unchanged

Retain inherited regression tests.

────────────────────────────────────────
31. FINAL RESPONSE
────────────────────────────────────────

Return first:

ENVIRONMENT_VALID:
BRANCH:
START_HEAD:
END_HEAD:
TASK_STATUS:

OPPORTUNITY_SEMANTICS_STATUS:
SHADOW_NATIVE_STATUS:
CAPITAL_STATE_CAUSALITY_STATUS:
P0_NATIVE_RECONCILIATION:

SMV6_COVERAGE:
IFCGR_COVERAGE:

Then:

LEGAL_PRECAPITAL_OPPORTUNITIES:
REDUCTION_ROWS_REMOVED:
SHADOW_COMPLETED_LIFECYCLES:
SHADOW_IDENTITY_MATCH_RATE:

TRUE_CAPITAL_CONFLICTS:
CONSTRAINED_CAPITAL_PCT:

Then the portfolio results:

GAP_VARIANT_DECISION:
MCB_ATRDR_RELATIONSHIP:

BEST_5PCT_DD_CANDIDATE:
BEST_8PCT_DD_CANDIDATE:
BEST_10PCT_DD_CANDIDATE:
BEST_15PCT_DD_CANDIDATE:

For each candidate:

ATRDR multiplier
MCB multiplier
Gap variant
Gap multiplier
SMV6 multiplier

2018–2021 metrics
2022–2023 metrics
2024
2025
2026YTD
full-period metrics

cost stress
concentration status
capacity status

Then:

ATRDR_CAPITAL_DECISION:
MCB_CAPITAL_DECISION:
GAP_CAPITAL_DECISION:
SMV6_CAPITAL_DECISION:

FINAL_RECOMMENDED_SHADOW_PORTFOLIO:

FINAL_DECISION:

RESEARCH_LANES_CLOSED:

NEXT_ACTION:

Do NOT answer that the next action is another historical portfolio study.

If a robust candidate exists:
freeze it and recommend forward shadow.

If not:
keep Native and close capital-allocation research.

Finally:

tests
hash verification
contract SHA256
output manifest
report path
rerun command
commit
remote HEAD
PUSH YES/NO

────────────────────────────────────────
32. GIT
────────────────────────────────────────

Run tests.
Verify hashes.
Verify deterministic outputs.
git status.

Commit normally.

Suggested commit:

research: repair portfolio semantics and close capital allocation

Normal push to current branch.

Never force push.