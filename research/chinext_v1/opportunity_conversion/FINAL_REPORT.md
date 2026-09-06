# CHINEXT V1 Opportunity-to-P&L Conversion — Final Report

## Final decision

**Formal decision: D — breadth explains opportunity, but conversion has no
decision-time predictive structure that passes the strategy-design gate.**

Authoritative CHINEXT V1 is unchanged. No V2 or minimum candidate is
authorized.

The largest observed economic leakage is best classified as **G: an
interaction**:

- false-positive/admission drag outside the right-tail opportunity set; and
- post-peak giveback/holding-path mismatch inside trades that do generate MFE.

The largest single static ceiling is excessive post-MFE giveback, but it is a
hindsight ceiling. The actionable conclusion is therefore **H: current
evidence does not contain sufficiently stable, exploitable improvement space**.

This distinction is essential: a large economic loss ceiling is not the same
thing as a causal, tradable repair.

## Scope and correctness boundary

The study inherits the frozen regime-attribution Outcome C and the rejected
A40 overlay. No breadth exposure threshold was searched.

- Strategy SHA256:
  `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- Three independent blocks: 2018-2021, 2022-2023 O0, and 2024-2025.
- Completed-cycle population: 399/399.
- In-hold path rows: 5,551.
- Entry breadth coverage: 387/399; missing values fail closed.
- Opportunity20 breadth coverage: 81/84.
- Candidate universe: 1,821 final candidate events; fixed-horizon20 coverage
  1,812/1,821.
- Strict post-exit20 coverage: 398/399.
- All history remains bounded PIT-B, not strict PIT-A. There is no untouched
  evaluation block for a newly invented rule.

Entry/exit lineage, capital, P&L, terminal return, MFE, MAE, timing,
corporate-action coordinates, and nine causal entry features reconcile to the
frozen artifacts at `1e-12` tolerance. Exit-session paths use only actual exit
execution. No missing input is imputed.

## Complete conversion chain

| Chain stage | What the evidence says | Leakage or boundary |
|---|---|---|
| Market Opportunity | Breadth is a strong continuous descriptor of 20-day cross-sectional right-tail frequency (`rho 0.756`), p90-p10 spread (`0.308`), and standard deviation (`0.264`); all are 8/8 yearly and 8/8 LOYO. | Breadth describes a wider/right-tailed opportunity distribution, not a uniform return lift. |
| Entry Selection | Breadth raises daily candidate count (`rho 0.215`) and candidate rate (`0.233`), but only 5/8 yearly signs agree. Selected fixed-horizon candidates are modestly better than unselected ones. | There is substantial false-positive admission, but little evidence that V1 systematically chooses the wrong stock when an alternative exists. |
| MFE Generation | Breadth->selected-trade MFE is `rho 0.245`; opportunity15/20/25 and extreme40/50 stay positive across neighbors and LOYO. All 13 rolling MFE and opportunity20 windows are positive. | Opportunity is a plateau/tail effect. MFE p90 is non-monotone and terminal median remains negative in every breadth quintile. |
| Holding Path | Higher breadth is associated with later relative MFE timing, not faster MFE. Large winners often peak late. | Early peaks leave more time for giveback; a static shorter hold would also truncate the late right tail. |
| MFE Capture | 52 MFE20-50 trades have median capture `33.6%` and only `17.3%` retain terminal return >=20%. Thirty-two MFE>=50 trades have median capture `58.4%`; 30/32 retain >=20%, but only 15/32 retain >=50%. | Leakage is concentrated in medium-large opportunities and post-peak exposure. The strongest path variables are hindsight outcomes. |
| Terminal P&L | Opportunity20 trades contribute `+2.981m`; the other 315 completed trades contribute `-1.549m`, producing total realized P&L `+1.432m`. | Breadth raises both right-tail availability and dispersion while failing to suppress enough ordinary failures/severe losses or stabilize capture. |

## 1. What does breadth actually change?

Breadth changes three things.

First, it describes the market-wide opportunity distribution. On 1,758
covered sessions, higher breadth coincides with more 20-day cross-sectional
right-tail observations and wider return dispersion. This relationship is
uniformly positive across years and LOYO.

Second, it moderately increases V1 candidate supply. Across the three blocks,
1,145 sessions permit candidate evaluation, producing 1,821 final candidate
events and 409 selected entries including ten terminal-open cycles. Candidate
count/rate rise with breadth, but the yearly sign is only 5 positive versus 3
negative. Supply is not the most stable part of the mechanism.

Third, it improves selected-trade opportunity availability. Within-year
breadth quintiles show:

| Breadth quintile | MFE median | MFE p90 | Opp20 | Opp50 | Terminal median |
|---:|---:|---:|---:|---:|---:|
| 1 | 5.41% | 19.86% | 10.26% | 1.28% | -2.12% |
| 2 | 4.55% | 16.38% | 9.59% | 2.74% | -2.61% |
| 3 | 7.37% | 67.26% | 27.16% | 17.28% | -2.11% |
| 4 | 7.14% | 42.44% | 28.17% | 9.86% | -2.10% |
| 5 | 10.83% | 38.55% | 28.57% | 8.33% | -1.31% |

The economically correct reading is a Q3-Q5 opportunity plateau with a
fatter, unstable tail—not a monotone terminal-return gradient and not a new
breadth threshold.

## 2. How does right-tail opportunity form?

Right-tail opportunity is mainly a market-distribution phenomenon.

When more CHINEXT members are above MA20, the cross-section also contains more
20-day right-tail returns and wider dispersion. V1's existing filters then
admit more candidates and its selected trades encounter more MFE. The
relationship survives opportunity thresholds of 15%, 20%, and 25%, extreme
opportunity thresholds of 40%, 50%, and 60% with weakening magnitude, all
13 rolling windows, and removal of the top 1/5/10/20 MFE trades.

It is not primarily created by a stable stock-level winner signature. Among
the nine causal V1 features, the strongest breadth/year-controlled effects are
small: RS->MFE `0.137`, RS->right-tail `0.116`, and RS->false-breakout `-0.102`.
None passes multiplicity plus yearly/LOYO gates. Across the full candidate
pool, RS->fixed-horizon MFE20 is only `0.047`, with 4 positive and 4 negative
year signs.

The right tail is therefore available before it is reliably identifiable.

## 3. Where does V1 lose opportunity?

There are two different leakage locations.

### Outside generated opportunity: false-positive admission

- 213/399 completed trades are inherited false breakouts.
- Their realized P&L is `-1.809m`.
- 44 trades are severe losses with P&L `-0.834m`; 42/44 overlap the false-
  breakout class.
- All 315 trades below MFE20 contribute `-1.549m` in aggregate.

This is genuine entry/admission drag, but not established stock-ranking
failure. The 1,821-candidate audit shows selected candidates have Opp20 25.9%
versus 23.3% for unselected, and close20>=20% 13.7% versus 10.2%. On days with
both types, selected candidates have `+3.19%` mean day-centered MFE20 versus
`-1.02%` for unselected.

Only 30 of 259 selection days contain an executable, covered alternative
candidate. On those competitive days, V1 captures the hindsight best-MFE20
candidate 43.3% of the time, a top-3 candidate 70.0% of the time, and has 3.07%
median best-candidate regret. Ranking inefficiency exists on this narrow
surface, but most false-positive entries cannot be repaired by simply choosing
another same-day candidate.

### After generated opportunity: giveback and holding mismatch

- 84 trades reach MFE20; 39 finish at or above 20% and 45 do not.
- Of the 45 nonconversions, 39 still finish positive and together contribute
  `+0.494m`; only six finish nonpositive.
- Peak-to-exit distance has `rho -0.477` with capture after controlling MFE and
  year. Later MFE, hence fewer remaining giveback sessions, is associated with
  better capture.
- Opportunity20 nonconversions have +6.25% median post-exit close return at 20
  sessions, so some continuation remains after exit.

This is monetization leakage, but a large part is the cost of retaining late
winners. All prior terminal >=50% winners exit through the market-MA20 family,
and the right tail tends to peak late. A blanket earlier exit would remove
giveback and right-tail formation together.

## 4. How much is selection versus exit?

The amounts below are diagnostic ceilings, not additive counterfactual NAVs.

| Surface | Diagnostic amount | Interpretation |
|---|---:|---|
| Actual completed-trade P&L | +1.432m | Exact frozen ledger total |
| Opportunity20 P&L | +2.981m | Exact disjoint contribution from 84 trades |
| Non-opportunity P&L | -1.549m | Exact disjoint contribution from 315 trades |
| Perfect terminal-sign selection ceiling | 1.946m | Hindsight removal of every nonpositive trade |
| False-breakout avoidance ceiling | 1.809m | Hindsight removal; no replacement/vacancy path |
| Severe-loss avoidance ceiling | 0.834m | Mostly overlaps false breakouts |
| Opportunity20 peak-close giveback ceiling | 2.243m | Initial-capital, hindsight close-peak oracle |
| Opportunity20 MFE-high giveback ceiling | 2.870m | Unexecutable intraday-high oracle |

The peak-close exit ceiling is numerically larger than the false-breakout
ceiling, so excessive giveback is the largest single static loss surface. It
does not prove exit is the best repair.

Executable counterfactuals say the opposite:

| Frozen replay | Total-return delta | Temporal behavior |
|---|---:|---|
| Disable individual exit, 2024-2025 | -10.56 pp | 2024 +3.05 pp; 2025 -9.71 pp |
| Disable market exit, 2024-2025 | -13.52 pp | 2024 +15.61 pp; 2025 -21.26 pp |
| Winner hold, development | +9.51 pp | 2024 +11.44 pp; 2025 -3.89 pp |
| Winner hold, 2022-2023 OOS | -1.91 pp | unchanged in 2022, negative in 2023; two activations |

The defensible attribution is therefore an interaction, not a unique causal
percentage: entry/admission creates a large negative pool, while the exit
policy exchanges giveback for continued access to late right-tail outcomes.

## 5. Which variables are genuinely stable?

### Stable explanatory variables

- continuous breadth -> market cross-sectional right-tail frequency and
  dispersion;
- continuous breadth -> selected-trade MFE/opportunity availability;
- peak-to-exit distance, post-peak decay, and holding-path mean return ->
  realized capture/giveback;
- candidate count -> best available fixed-horizon opportunity, partly as an
  order-statistic/sample-size effect.

The first two are causal market context at entry. The path variables are
stable outcome descriptors only.

### Stable enough to describe, not to trade

- RS has weak positive opportunity association, but fails effect/multiplicity
  and candidate-pool yearly gates.
- Wider boxes have a small negative terminal-return association (`rho -0.104`)
  that survives extreme removals, but fails the frozen 54-test family and has
  no sufficient continuous separation.
- Breadth conditional on MFE has small capture/giveback correlations, but
  yearly and rolling signs are mixed.
- Post-exit continuation has positive median in four years and negative median
  in four years.

No stock-level feature, Breadth x stock feature, or causal exit rule is stable
enough to trade.

## 6. Which hypotheses were falsified?

- Stable causal entry separation was falsified: 0/54 primary, 0/135
  neighboring-definition, and 0/27 Breadth x stock-feature tests pass the full
  gate.
- The hypothesis that stronger breadth shortens time-to-MFE was falsified;
  relative MFE timing moves later.
- The hypothesis that earlier peaks improve capture was falsified; earlier
  peaks leave more giveback time in the observed policy.
- Simple exit-family removal was falsified by lower total return and opposite
  year effects.
- Development winner-hold generalization was falsified in 2022-2023 OOS.
- Breadth->terminal return was falsified as a stable continuous relationship:
  2-year/3-year rolling signs are 9 positive and 4 negative, and rho changes
  from `0.022` to `-0.016` after removing the 20 largest absolute-P&L trades.
- A renewed breadth exposure overlay remains falsified by the frozen A40
  evidence.

## 7. Is there a tradable improvement?

**No.**

The decision-time breadth variable explains supply and opportunity but its
overlay already failed yearly, rolling, LOYO, neighboring, exposure, cost, and
coverage gates. The nine decision-time stock features do not identify winners
or false positives robustly. The strongest monetization variables are future
path outcomes. The simplest executable exit candidates have mixed years or
failed OOS.

Top-N sensitivity reinforces the problem. The best 20 positive trades account
for 55.1% of positive P&L; fixed-ledger P&L becomes `-0.431m` after removing
them. A modification that slightly reduces right-tail access can therefore
erase the entire apparent improvement.

## 8. What is the minimum sufficient next-generation candidate?

None is authorized. There is no minimum sufficient modification supported by
this evidence.

Specifically:

- no breadth exposure multiplier;
- no RS/box/volume entry threshold;
- no winner-hold or blanket delayed exit;
- no rule derived from time-to-MFE, peak distance, decay, or post-exit return;
- no combined entry/exit rule.

Creating any of these now would convert descriptive hindsight into a strategy
and violate the research contract.

## 9. What should V1 study next?

The next study should seek a genuinely new decision-time conversion mechanism,
not another breadth threshold.

Priority order:

1. Freeze a future untouched evaluation period before analysis. Current
   2018-2025 outcomes are consumed.
2. Study early post-entry state at fixed causal checkpoints such as session 5
   or 10: realized continuation, adverse excursion, volume/RS persistence, and
   market-state change known at that checkpoint versus subsequent capture and
   giveback. Do not use eventual MFE/peak location as a feature.
3. If selection is revisited, restrict it to genuinely competitive candidate
   days and replay exact capacity, fill, exit, and vacancy feedback. The present
   fixed-horizon oracle shows only 30 such historical days, so this is a narrow
   research surface.
4. Require the same yearly, LOYO, neighboring-definition, extreme-trade,
   cost/exposure, and OOS gates before any candidate is named.

Until such evidence exists, authoritative CHINEXT V1 should remain unchanged
and this research line should stop at explanation.

## Final synthesis

Breadth is an **opportunity-supply and dispersion state**, not a P&L state.
It increases the number of candidates, the probability of MFE, and the
availability of extreme right-tail paths. V1's terminal P&L then depends on two
hard problems breadth does not solve: excluding numerous low-MFE false
positives and retaining enough of late, concentrated winners without paying
unpredictable giveback.

Those leakages are economically large but are not stably identifiable at their
decision times. The correct result is **Decision D, no V2**.

