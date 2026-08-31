# Objective-crossing economic-response map

Frozen before any future return or downside relationship is estimated. This map
moves seven already-supported completed-session market representations from
descriptive geometry to a falsifiable economic-response question. It does not
create a signal, habitat, exposure rule, or CHINEXT V1 overlay.

## Seven fixed market-state representations

The tested objects are the seven roles in the immutable minimal panel from
MKT-BREAKOUT-DIFF-001, in this order:

| role | exact L20 absolute field | fixed economic meaning | absolute domain |
|---|---|---|---|
| formation participation | `breakout_formation_participation20` | fraction of eligible securities whose mapped daily high strictly exceeds their strictly prior 20-session mapped-high level | [0, 1] |
| formation depth | `breakout_formation_depth20` | mean proportional excess of mapped high over that prior-high level among crossing securities | [0, +inf) |
| closing acceptance | `breakout_closing_acceptance20` | fraction of crossing securities closing strictly above the crossed level; equality is neutral | [0, 1] |
| closing rejection depth | `breakout_closing_rejection_depth20` | mean proportional prior-high-to-close shortfall among crossing securities, floored only by its defining max with zero | [0, +inf) |
| formation diffusion | `breakout_formation_diffusion20` | similarity of included-industry event share to included-industry eligible share | [0, 1] |
| formation leadership concentration | `breakout_formation_leadership_top3_20` | top-three share of positive industry excess event mass | [0, 1] |
| stock/industry divergence | `breakout_stock_industry_divergence20` | stock-weighted formation participation minus equal-industry formation participation | [-1, 1] |

Every security-level objective crossing underlying these aggregates remains a
strict crossing of a mapped high above an objective, strictly prior L20 high.
L10/L40 were neighboring-definition stability challenges and are not outcome
alternatives. Equal-industry formation is excluded because the parent experiment
compressed it as redundant with formation participation. No failed change,
acceleration, selling-absorption, or rally-distribution object enters this study.

## Cross-year state coordinates

All seven raw ratios retain the same formula, unit, population contract, and
numerical meaning across 2018--2023. They are therefore **A: absolute and
cross-year comparable** within the frozen view/denominator population. Raw values
are reported and their continuous economic association is audited year by year.

The primary comparable regime coordinate is the existing
`<absolute_field>_pit_3y_pct`: a causal percentile over at most 756 observations,
including the current completed observation, with at least 504 valid historical
observations. It is **B: PIT-historically normalized**. Its numerical meaning is
the current state's position in the information available through t; it is not an
absolute raw magnitude. No full-year or future rank is allowed.

The existing `relative_to_all` and `relative_view_rank_pct` fields are **C:
relative/cross-sectional** coordinates. They remain lineage/audit fields only in
the primary economic test. They cannot define a crossing or rescue a failed raw or
PIT result. ALL_A relative-to-all is mechanically zero and is never estimated.

## Exact market-state levels and directions

Three fixed PIT state levels have separate purposes:

- 0.50 is the sole transition boundary;
- <=0.20 is the low-state distributional tail;
- >=0.80 is the high-state distributional tail.

These are not separately calibrated by role, view, denominator, or year. A value
equal to 0.50 belongs to the high side. An **UP** raw crossing occurs when the
immediately prior valid exchange-session PIT value is below 0.50 and the current
value is at least 0.50. A **DOWN** raw crossing is the reverse. Direction is never
pooled during estimation.

A de-clustered UP episode requires the current observation at or above 0.50 and
all five immediately preceding exchange-session observations below 0.50. A
de-clustered DOWN episode requires the current observation below 0.50 and all five
preceding observations at or above 0.50. Any missing member of the six-observation
sequence makes the episode ineligible. This first-crossing-after-five-opposite-
sessions rule is the minimum fixed refractory construction: two episodes of the
same role/group cannot be less than six sessions apart and therefore cannot share
the frozen five-session future horizon. Raw crossings, episodes, and matched
episodes are all reported by year.

Cross-role events may occur on the same date because the roles have distinct
semantics. They are never pooled into an inflated event count or combined score.

## Level effect versus incremental transition effect

The level question is primary and uses every eligible completed state date:

1. continuous Spearman association of raw and PIT state with each response;
2. fixed PIT high-minus-low contrast, `PIT >= 0.80` minus `PIT <= 0.20`;
3. response distributions within the high and low states.

The transition question is separate. Each de-clustered episode is compared with
up to three deterministic noncrossing controls from the same role, market view,
denominator, event year, current side of 0.50, and future-response domain. Controls
must be within 0.05 of the event's current PIT value, must not cross at t, and must
be at least five sessions from any raw crossing of that role/group. The three
nearest PIT values are selected, ties by earlier date; a control cannot repeat
within one event but may serve different events. An episode without a control is
reported but not estimated. The event-minus-mean-control response is the fixed
incremental crossing estimand.

This local design controls current state level without a flexible predictive
model. No alternate caliper, number of controls, polynomial, threshold, or pooled
direction can rescue a result.

## Response family and scientific interpretations

The initial family is exactly 1, 3, and 5 later exchange sessions. Session 3 is
the primary horizon; sessions 1 and 5 are mandatory neighboring-horizon
challenges, not search alternatives. The terminal-return and downside-path
families have equal standing:

- return meaning: directional follow-through or reversal;
- downside meaning: path-risk reduction or amplification even when terminal
  return is unchanged.

For each state/direction the analysis reports overall, 2018--2023 event-year,
2018--2020 versus 2021--2023 blocks, and six leave-one-year-out estimates. The
daily level series also receives fixed nonoverlap phase audits for each horizon;
episodes are already separated beyond the maximum horizon. No year-specific
threshold is allowed.

## Primary and secondary response summaries

Primary date-level outcomes are equal-weight action-coordinate constituent-cohort
terminal mean log return and equal-weight mean constituent adverse log excursion.
Secondary summaries are terminal median, positive-return fraction, terminal p10
and p90, adverse median and p10, and the temporal distribution of every primary
estimate (mean, median, positive probability, p10, p90). Rare right/left tails are
therefore visible but cannot make a mean-only result pass.

## Minimum controls and null

Controls are not inspected until the unconditioned level/transition result is
classified. Only two already-frozen causal coordinates may enter a fixed rank-
linear residual audit:

- discovery breadth: `breadth_net_new_high_low60_pit_3y_pct`;
- realized-volatility level: `realized_volatility_median20_pit_3y_pct`.

No variable selection or large multivariate model is allowed. A result entirely
absorbed by these controls is not an independent market state.

The null is 200 deterministic within-year circular shifts of each complete PIT
series by an offset from 20 through `n-20`, seeded from experiment/role/group/year.
After each shift, high/low states, raw crossings, de-clustered episodes, and local
matches are reconstructed exactly. This preserves the state distribution and
most serial structure while breaking its calendar alignment with later response.
An empirical two-sided p-value uses `(1 + exceedances) / 201`; Benjamini-Hochberg
q=0.10 is applied across the seven preregistered roles separately for level and
transition families. No alternative null may rescue a failed role.

## Prefrozen economic gate

A role first becomes a level or transition candidate only when the unconditioned
session-3 effect is economically nontrivial:

- absolute median high-minus-low or matched event-control terminal mean log-return
  effect >=0.0025; or
- absolute corresponding adverse-excursion effect >=0.0025; and
- absolute median cell Spearman rho >=0.10 for a level candidate.

The sign must agree in at least six of eight view/denominator cells, both
2018--2020 and 2021--2023 must share it, at least four of six event years must
share it, every leave-one-year-out estimate must share it, and sessions 1 and 5
must not reverse it. The relevant null q-value must be <=0.10. A transition
direction additionally requires at least 25 matched episodes in six of eight
cells and at least five matched episodes in five of six years. Counts measure
cells separately; claims never add overlapping view/denominator events as if
independent.

For daily overlapping level outcomes, the session-3 sign must agree in at least
two of three nonoverlap phases and the session-5 sign in at least four of five.
Failure of a neighboring horizon, portability, episode, nonoverlap, or placebo
gate cannot be repaired by changing the primary horizon or state threshold.

Role classification is deterministic:

- `TRANSITION_INCREMENTAL_RESPONSE`: at least one direction passes the matched
  transition gate beyond level;
- `LEVEL_ECONOMIC_RESPONSE`: terminal-return level gate passes but transition does
  not;
- `TAIL_RISK_RESPONSE`: downside level gate passes while terminal-return level
  gate does not;
- `CONDITIONAL_RESPONSE`: a primary candidate also survives the fixed two-control
  residual audit; this is an additional flag, not a weaker rescue class;
- `UNSTABLE_ECONOMIC_RESPONSE`: economic-size gate passes but portability,
  neighboring-horizon, nonoverlap, or null gate fails;
- `NO_ECONOMIC_RESPONSE`: adequate domain exists but neither economic-size gate is
  reached;
- `DESCRIPTIVE_ONLY`: retained scientific tier for every role with no reproducible
  economic response after the complete gate.

Passing does not establish causality, execution, a strategy habitat, or a trading
rule. If no role passes, all seven remain stable descriptive representations and
the threshold family is closed without rescue. If one passes, a separately frozen
CHINEXT V1 habitat experiment may open; CY-011 remains locked.
