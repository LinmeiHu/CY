# CHINEXT V1 market-regime attribution — final report

Research date: 2026-08-30  
Authoritative branch: `research/chinext-v1`  
Starting HEAD: `e361aa9fb98756becc09c76dd88552533f3762fe`  
Final research outcome: **C — market regime is useful for explaining V1, but the evidence is insufficient for a trading overlay.** This has a D-style qualification—breadth is the one clearly useful market dimension—and an F-style data qualification—all historical inputs are bounded PIT-B, not strict archival PIT-A.

## Executive verdict

CHINEXT V1 is a right-tail strategy. Its good and bad years are distinguished first by whether admitted entries can produce large favorable paths and rare super-winners, and second by whether ordinary trades are good enough to avoid consuming those gains. They are not distinguished primarily by the frequency of severe losses, the annual label, or a simple continuous market-trend measure.

The strongest causal market-state evidence is cross-sectional breadth at the completed entry-signal close. Higher and improving breadth is associated with larger MFE, more MFE>=20% opportunities, and fewer false breakouts. That relationship survives eight leave-one-year-out sign checks, within-year ranks, fixed trend controls, year effects, and four or five of five fixed trend strata. It is an opportunity-set relationship, not a downside-risk or exit-efficiency relationship.

The evidence does not support a V1-R. The single eligible candidate—half-size new entries when raw `breadth_above_ma20 < 0.40`, full size otherwise, and zero risk on missing required breadth—failed its preregistered bad-environment and neighboring-definition gates. Phase 8/9 then rejected it on yearly, rolling, expanding-prefix, no-refit LOYO, exposure-normalized, neighboring-threshold, cost, and coverage-frequency diagnostics. Only implementation integrity and limited right-tail sacrifice passed. Frozen V1 therefore remains authoritative, with no production regime overlay.

The research did not fail because the overlay was difficult to implement. It was implemented causally and exactly: all three control replays match the frozen V1 economics and projected ledgers; there are zero same-day fills, timestamp failures, target-weight mismatches, or signal/rank/exit changes. It failed because the economic benefit was not stable or large enough.

## Scope, evidence grade, and non-claims

This report reconciles three independent authoritative V1 blocks:

| Block | Evaluation dates | Total return | Max DD | Completed cycles | Lineage |
|---|---|---:|---:|---:|---|
| EXTENDED | 2018-01-02..2021-12-31 | 64.82% | -20.76% | 194 | bounded effective-state PIT-B |
| HOLDOUT O0 | 2022-01-04..2023-12-29 | -15.52% | -19.34% | 94 | bounded reconstructed PIT-B |
| DEVELOPMENT | 2024-01-02..2025-12-31 | 105.24% | -26.23% | 111 | bounded reconstructed PIT-B |

The blocks start from independent capital. They are never chained into an eight-year NAV. Trades may be pooled only with block lineage. The authoritative strategy SHA-256 is `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`; its stock signals, ranking, exits, T+1, limits, trading status, corporate actions, costs, no-replacement semantics, and NAV definition were not changed.

Every regime feature is formed from information available at the completed close `t` and can affect only a later causally valid execution. The feature library reconciles the exact V1 `basic_eligible` denominator on 1,942/1,942 sessions. Nevertheless, the correct evidence label is **bounded PIT-B**, not strict archival PIT-A: supplier revision vintages and record-level historical availability are not available for every source.

All 2018-2025 outcomes had already been viewed before the new candidate was designed. Preregistration controls analysis flexibility, but it cannot recreate untouched OOS. Rolling, expanding, and LOYO results are stability/resampling diagnostics, not future OOS. The pre-existing name “HOLDOUT O0” applies to an earlier frozen V1 baseline experiment; it is not untouched OOS for the later V1-R rule.

## FACT

### Baseline identity and exact execution

- One frozen V1 configuration is shared across all three blocks.
- All nine authoritative NAV/event/execution hashes match their frozen reports.
- Phase 7 ran 3 blocks × 5 predeclared arms. Each all-one control passed six exact checks: execution hash, projected event hash, projected NAV hash, total return, max drawdown, and completed cycles.
- The outer candidate hook changes only the target weight assigned to a newly selected member. The weight remains sticky through that member lifetime. It does not change the strategy file, selected set, ranking, or exit rules.
- Phase 8/9 rehashed all 15 candidate ledgers. Across 6,797 filled executions and 1,938 filled new buys it found zero same-day fills, feature-timestamp failures, first-applicable-date failures, new-buy target mismatches, missing-feature candidate buys, overlay-identity failures, or signal/rank/exit changes.

### Yearly outcomes

| Year | Return | Max DD | Trades | Win rate | Mean / median trade | >=20% winners | <=-10% losses | Median MFE | Avg exposure |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | -3.78% | -4.65% | 11 | 18.18% | -3.47% / -3.47% | 0.00% | 9.09% | 2.76% | 2.88% |
| 2019 | 23.49% | -10.21% | 47 | 48.94% | 3.98% / -0.30% | 8.51% | 6.38% | 5.98% | 30.13% |
| 2020 | 5.27% | -20.76% | 74 | 47.30% | 1.66% / -0.32% | 9.46% | 16.22% | 9.41% | 33.74% |
| 2021 | 31.78% | -11.73% | 62 | 45.16% | 5.15% / -1.00% | 9.68% | 9.68% | 6.10% | 32.83% |
| 2022 | -17.29% | -17.96% | 37 | 13.51% | -4.89% / -5.12% | 0.00% | 13.51% | 3.35% | 10.74% |
| 2023 | 2.14% | -15.07% | 57 | 33.33% | 0.44% / -2.10% | 7.02% | 1.75% | 4.87% | 24.93% |
| 2024 | 49.05% | -23.54% | 38 | 31.58% | 15.11% / -2.62% | 26.32% | 18.42% | 6.37% | 23.59% |
| 2025 | 37.70% | -10.18% | 73 | 50.68% | 3.89% / 0.48% | 10.96% | 12.33% | 10.88% | 57.13% |

The yearly return rank has descriptive Spearman rho 0.970 with >=20% winner frequency, 0.929 with mean trade return, 0.862 with >=50% winner frequency, and 0.786 with median MFE. It is only 0.333 with severe-loss frequency. These eight-point correlations are decomposition evidence, not a fitted forecasting model.

### Tail concentration

- The 39 cycles returning at least 20% contribute 73.6% of all positive realized P&L.
- The 15 cycles returning at least 50% contribute 45.6% of positive P&L.
- The global top 20 cycles contribute 55.1% of positive P&L.
- Annual Top-5 positive-P&L shares range from 43.5% to 100%.
- Ex-best-5 annual return is negative in seven of eight years; 2025 is the only positive year at +7.50%.
- The profitable 2018-2021 and 2024-2025 blocks still have negative median trades. Good aggregate performance does not imply a good typical trade.

### Loss and failure archetypes

- There are 213 fixed false breakouts, with mean return -6.5%, median holding period 7 sessions, and aggregate realized P&L of -1.81m.
- There are 44 severe losses (`<= -10%`), with aggregate realized P&L of -0.83m.
- Only two cycles are extreme losses (`<= -20%`).
- Severe-loss frequency is not a sufficient bad-regime definition. 2024 has the highest annual severe-loss rate but the highest annual return because six >=50% winners dominate; 2023 has very few severe losses but only a 2.14% gain.

### Data availability

The frozen feature artifact contains 93 market-state features over 1,942 sessions:

| Family | Feature count | Minimum daily coverage |
|---|---:|---:|
| Breadth | 16 | 84.96% |
| Dispersion / cross-sectional volatility | 26 | 90.53% |
| Index trend / liquidity | 20 | 100.00% |
| Liquidity / participation | 5 | 84.96% |
| Risk appetite | 7 | 90.53% |
| Rotation / persistence | 7 | 88.21% |
| Observed style-relative index spreads | 4 | 100.00% |
| Volatility | 8 | 100.00% |

Cross-sectional features fail closed below 100 eligible names; 184 dates are null rather than imputed. Raw MA20 breadth coverage is 53.5% in 2018 and 75.6% in 2022, below the frozen Phase 8 >=80% per-year gate. Growth/value, true PIT market-cap style, high/low-beta style, fund flow, sentiment, and a governed cyclical-sector mapping are unavailable. Observed 399102-versus-index return spreads are not substitutes for those missing families.

## EVIDENCE

### 1. Why years differ

The first-order decomposition is the combination of right-tail availability and ordinary-path quality:

- **2018:** almost no exposure, no >=20% winner, median MFE 2.76%, and negative mean/median trade. The loss is small because activity is small, not because admitted trades are good.
- **2019:** near-49% win rate plus four >=20% winners and a >=50% bucket worth 160k. The top five generate 72.7% of positive P&L; ex-best5 return is already -2.38%.
- **2020:** a similar win rate to 2019 but no >=50% winner, many severe losses, and much larger drawdown. Seven 20–50% winners are largely offset by ordinary and severe losses.
- **2021:** a negative median trade but a 526.6k >=50% bucket. Rare super-winners dominate.
- **2022:** the clearest opportunity failure—13.5% win rate, no >=20% winner, median MFE 3.35%, and negative ordinary trades. Low exposure limits the number of trades but does not make expectancy positive.
- **2023:** four >=20% winners rescue otherwise weak ordinary economics; severe losses are rare, so “loss avoidance” alone cannot explain the low return.
- **2024:** a narrow super-winner year. Six >=50% cycles produce 614.4k despite a 31.6% win rate, negative median trade, and high severe-loss rate.
- **2025:** the broadest good year. Win rate exceeds 50%, median trade is positive, exposure is high, and return remains +7.50% after removing the best five cycles.

The explanation is therefore not one-dimensional. A year can be good because a few very large paths overwhelm a weak median (2021, 2024), or because the broader distribution improves (2025). A year is bad when favorable paths are scarce and ordinary losses are not offset (especially 2022). Severe losses amplify some years, notably 2020, but do not define the regime by themselves.

### 2. Univariate regime attribution

All 399 completed cycles join causally to their entry-signal-date feature row; there are zero missing joins or same-day fills. The preregistered family results are:

| Hypothesis family | Result | Main evidence |
|---|---|---|
| Continuous trend / persistence beyond V1's MA20 gate | Rejected | no primary feature passes magnitude, direction, within-year, and LOYO gates |
| Breadth | Supported with qualification | 3/5 primary features survive; strongest MFE effects are stable 8/8 LOYO |
| Rotation / leadership persistence | Rejected, contradictory | turnover/overlap signs oppose the hypothesized fast-rotation failure story |
| Dispersion / right-tail strength | Ambiguous | only `cross_sectional_return20_right_tail_ge20` survives |
| Volatility | Ambiguous | no monotone sign was preregistered; no interaction was authorized |

For the three surviving breadth features:

| Feature | >=20% winner rho | MFE rho | MFE LOYO |
|---|---:|---:|---:|
| `breadth_above_ma20` | 0.140 | 0.211 | 8/8 |
| `breadth_positive_return20` | 0.073 | 0.101 | 8/8 |
| `breadth_above_ma20_change20` | 0.154 | 0.203 | 8/8 |

Breadth state flips are a useful falsification: their >=20% winner sign is opposite the preregistered persistence story. This prevents converting “some breadth statistics correlate” into a broad claim that all stable breadth measures form a regime gate.

### 3. Meaningful conditional analysis

Phase 4 did not enumerate interactions or build a classifier. It tested only the three breadth variables supported in Phase 3 against three frozen trend controls, entry-year effects, eight LOYO panels, and five fixed trend strata.

| Breadth feature | Partial MFE rho | Same-sign LOYO | Positive trend strata |
|---|---:|---:|---:|
| `breadth_above_ma20` | 0.183 | 8/8 | 5/5 |
| `breadth_positive_return20` | 0.164 | 8/8 | 4/5 |
| `breadth_above_ma20_change20` | 0.205 | 8/8 | 5/5 |

This is the strongest interaction/state evidence in the project: breadth adds entry-opportunity information conditional on coarse trend state. It does not justify naming a hindsight “risk-on” class, and it does not show that a threshold improves a portfolio.

Trend×volatility, breadth×volatility, style, liquidity, and broader rotation combinations were not searched. The Phase 3 evidence did not authorize them, and several needed data families lack governed PIT lineage. Avoiding those interactions is part of the result, not missing optimization work.

### 4. Regime × entry opportunity and cohort

The feature-only breadth composite uses equal-weight within-year ranks of the three Phase 4 survivors for attribution only; it is not deployable and was never used by the candidate. Among 383 complete cycles:

| Breadth tercile | Mean MFE | Mean return | MFE>=20% | Realized>=20% | False breakout | Severe loss |
|---|---:|---:|---:|---:|---:|---:|
| Low | 7.8% | -2.0% | 10.1% | 2.3% | 65.9% | 10.1% |
| Middle | 17.0% | 3.3% | 22.8% | 11.0% | 50.4% | 11.0% |
| High | 24.3% | 7.4% | 29.9% | 15.0% | 44.9% | 12.6% |

Continuous breadth has rho 0.218 with MFE, 0.188 with MFE>=20% opportunity, and -0.147 with false breakout, all 8/8 LOYO in the expected direction. Terminal round-trip return is much weaker at 0.073. MAE is -0.018 and severe-loss association is +0.036, so high breadth is not a downside gate.

Fixed winner/loss archetypes reinforce the mechanism. Winner20 and winner50 cycles have median breadth rank 0.654, while false breakouts have 0.432. Global top-20 cycles have median 0.650. This says broad participation is more common when V1 can access a right tail; it does not mean every high-breadth entry wins or every low-breadth entry should be blocked.

### 5. Regime × holding path and exit

There are 84 MFE>=20% opportunities, of which 39 realize >=20%; there are 32 MFE>=50% opportunities, of which 15 realize >=50%. Raw breadth associations within the opportunity set are weak for binary conversion (rho 0.035), modest for capture ratio (0.149), and negative for giveback (-0.113).

The one preregistered controlled design uses the 80 complete MFE>=20% opportunities and controls ranked MFE, holding duration, time-to-MFE fraction, entry year, and canonical exit reason:

| Endpoint | Breadth partial rho | Expected-sign LOYO | Result |
|---|---:|---:|---|
| Capture ratio | -0.028 | 2/8 | fail |
| Realized>=20% conversion | -0.068 | 0/8 | fail |
| Giveback from peak | -0.088 | 7/8 | fail magnitude gate |

All 15 >=50% winners exit through the frozen market-MA20 lineage, have a median holding period of 34 sessions, and reach MFE late—the median time-to-MFE fraction is 0.79. This describes how large winners develop; it does not prove an extension rule would improve them.

Exit-lineage conversion differences are descriptive. MFE>=20% conversion is 60.3% for market-MA20 exits versus 12.5% for the combined individual-MA30/set-removal lineage, but no counterfactual post-exit path was read. The earlier winner-hold adaptation already failed its 2022-2023 OOS test. Together, those facts reject exit adaptation as an evidence-supported V1-R component.

### 6. Exposure efficiency and the V1-R candidate

The only eligible candidate was frozen before portfolio results:

- input: raw `breadth_above_ma20` at completed signal close `t`;
- primary rule: half normal new-entry target when breadth `< 0.40`, normal target otherwise;
- missing required input: zero new risk and retain the no-replacement slot;
- existing positions: target remains sticky until member exit;
- frozen neighbors: 0.30 and 0.50 with the same half-size multiplier;
- severity boundary: zero-size below 0.40;
- stock signal, selected set, ranking, exits, fill rules, costs, and corporate-action ledger: unchanged;
- no threshold or multiplier optimization and no year-specific parameter.

The primary results versus exact V1 controls are:

| Block | V1 return | A40 return | V1 / A40 DD | V1 / A40 avg exposure | Winner20 retained | Top-20 P&L capture |
|---|---:|---:|---:|---:|---:|---:|
| 2018-2021 | 64.82% | 46.69% | -20.76% / -21.67% | 24.90% / 21.74% | 88.24% | 78.24% |
| 2022-2023 | -15.52% | -15.36% | -19.34% / -19.20% | 17.84% / 17.79% | 100.00% | 100.08% |
| 2024-2025 | 105.24% | 101.88% | -26.23% / -26.23% | 40.39% / 39.06% | 100.00% | 99.76% |

Aggregated across blocks, it retains 94.87% of baseline >=20% winner entries and 90.64% of baseline Top-20 positive P&L. It improves ex-best20 in 2/3 blocks and has non-worse drawdown in 2/3. Those are real positives. They are insufficient because the frozen bad-environment gate fails: 2022 remains exactly -17.29%, and the 0.30 neighbor also fails to improve it. The 0.50 neighbor looks better in 2022-2023 but is a predeclared sensitivity arm, not an admissible result-selected replacement.

## INTERPRETATION

### V1's economic mechanism

V1 already conditions entry on the market being above its MA20 and selects individual breakouts/relative strength. Among those admitted entries, broad cross-sectional participation determines whether the market offers enough room for a favorable excursion. That is why breadth can add to the binary trend gate even though continuous trend strength itself does not pass.

The regime channel is mainly:

`broad participation -> more favorable excursion / more right-tail opportunities -> occasional large realized winners`

and, in weak participation:

`narrow participation -> fewer favorable paths / more false breakouts -> ordinary losses are not offset`

The arrow from MFE opportunity to realized capture is much less clearly regime-driven. Exit reason, holding duration, and path timing explain the raw conversion association; breadth adds no controlled conversion evidence. Severe losses also do not fall with high breadth. This is why a seemingly reasonable exposure overlay can fail even when the attribution is real: an opportunity descriptor is not automatically a profitable sizing rule.

### Coarse market states

The evidence supports a descriptive continuum rather than a deployable classifier:

- **Broad opportunity state:** a larger share of eligible stocks is above MA20, 20-day breadth participation is stronger, and/or breadth has improved. V1 entries have larger MFE and fewer false breakouts. Right-tail winners are more available, but severe-loss risk is not lower.
- **Narrow/false-breakout state:** participation is low. V1 entries often fail to develop favorable paths, and many become short-lived false breakouts. This is most relevant to entry opportunity, not to stop placement or exit timing.
- **Unresolved state dimensions:** volatility, a single cross-sectional right-tail-strength feature, style, liquidity, and risk appetite may refine the opportunity state, but current evidence is ambiguous or governed data are unavailable.

Calling these “risk-on/risk-off” would imply more precision and completeness than the evidence supports. No state label is used as a strategy input.

### Why lower exposure did not solve bad years

The candidate lowers average invested exposure in all three blocks and turnover/cost in all three. Yet exposure-normalized return is materially worse in 2018-2021 (-0.456 relative), only trivially better in the other two blocks, and the max drawdown is worse in 2018-2021 and unchanged in 2024-2025. Pooled descriptive active beta is -0.016, while annualized linear active alpha is -1.61%. The candidate helps on index-down days on average but hurts more on index-up days; it does not establish value distinct from reduced beta/exposure.

This is the critical distinction between “takes less risk” and “uses regime information efficiently.” V1-R needed the latter and demonstrated only the former in parts of the sample.

## HYPOTHESIS

The following hypotheses remain supported, with their stated limits:

1. **H-001:** annual V1 differences are dominated by right-tail frequency/magnitude and favorable-path availability more than by the median trade alone.
2. **H-002:** bad years combine right-tail scarcity with poor ordinary path quality; severe-loss frequency alone is insufficient.
3. **H-004:** broad participation incrementally describes favorable MFE/opportunity among entries already admitted by V1, after fixed trend controls. It is not a downside or deployable gate.
4. **H-008:** market state mainly affects entry opportunity and top-winner availability. Controlled evidence does not support an additional exit-conversion channel.
5. **H-010:** current regime evidence is explanatory only. No coarse, stable PIT overlay survives the complete audit.

## FAILED HYPOTHESIS

1. **H-003 — continuous trend/persistence:** rejected within entries already conditioned on V1's MA20 gate. None of the five primary trend variables passes the preregistered full gate.
2. **H-005 — leadership persistence/fast rotation:** rejected with contradictory signs. Top-decile overlap and leadership turnover move opposite the proposed mechanism.
3. **H-009 — simple raw-breadth exposure V1-R:** rejected. It fails Phase 7 bad-environment/neighbor gates and Phase 8 temporal, rolling, expanding, LOYO, exposure-normalized, neighbor, cost, and coverage-frequency gates.
4. **Winner-hold exit adaptation:** rejected by prior 2022-2023 OOS evidence and not revived by Phase 6 path analysis.
5. **Breadth as a severe-loss gate:** rejected. High breadth does not reduce severe-loss frequency, and 2024 directly contradicts that simplification.

The dispersion/right-tail hypothesis H-006 and volatility interaction hypothesis H-007 are ambiguous, not rejected. A single dispersion feature survives; volatility had no preregistered monotone sign and therefore did not authorize an interaction search.

## STRATEGY CANDIDATE

### Candidate tested

`A40_HALF_PRIMARY` is a research candidate only. It is causally implementable and simple, but it is rejected. The final action is:

> Keep frozen CHINEXT V1 unchanged. Do not deploy a breadth exposure, entry, or exit overlay from this research.

There is no recommended V1-R parameter. In particular:

- do not replace 0.40 with the apparently better 0.50 holdout neighbor;
- do not combine breadth with an untested trend/volatility/style classifier;
- do not treat missing breadth as proof of a weak regime;
- do not introduce an exit extension based on late winner MFE;
- do not tune thresholds by year or full-sample CAGR.

Raw breadth can be retained as a research/monitoring diagnostic, clearly separate from execution, until future evidence exists.

### Robustness and falsification result

| Audit | Result | Evidence |
|---|---|---|
| Yearly stability | Fail | active return positive/negative/neutral in 3/3/2 years |
| 126-session rolling | Fail | positive-window fraction 13.6%..47.0%; no block reaches 60% |
| 252-session rolling | Fail | positive-window fraction 21.0%..44.4%; no block reaches 60% |
| Within-block expanding prefixes | Fail | 2/8 positive |
| LOYO, no refit | Fail | mean annual active return negative in all 8 omitted-year panels |
| Regime frequency/coverage | Fail | valid raw breadth only 53.5% in 2018 and 75.6% in 2022 |
| Neighbor definitions | Fail | 0.30 fails 2022; definition effects vary by year |
| Exposure normalization | Fail | 2/3 non-worse, but 2018-2021 degrades by 0.456 |
| Right-tail retention | Pass | 94.87% winner-entry retention; 90.64% Top-20 P&L capture |
| Cost sensitivity | Fail | only 1/3 blocks positive at 0/10/25/50 bps ledger-notional scenarios |
| PIT/execution implementation | Pass | exact controls and zero causal/execution defects |

The 0/25/50 bps scenarios are non-endogenous ledger-notional adjustments, not cash/share-path replays. They are sufficient to show that plausible saved costs do not close the large 2018-2021 deficit, but they are not exact alternative-cost backtests.

### Ten active failure challenges

| # | Challenge | Final answer |
|---:|---|---|
| 1 | Is it only market-beta timing? | Non-beta value is not established; pooled active alpha is negative and active beta is lower. |
| 2 | Is drawdown lower only because exposure is lower? | Exposure reduction is a material confound; exposure-normalized robustness fails. |
| 3 | Does it sacrifice future true winners? | Sacrifice is limited but nonzero: ~5.1% of winner20 entries and ~9.4% of Top-20 positive P&L are lost. |
| 4 | Do only one or two years support it? | Support is not broad: 3 positive, 3 negative, and 2 neutral annual deltas. |
| 5 | Is it threshold mining? | The primary was preregistered and not mined, but the relationship is threshold-sensitive. |
| 6 | Does it depend on extreme trades? | V1 remains Top-N dependent; the overlay does not resolve that dependence. |
| 7 | Is the regime stably identifiable? | Both states appear when valid, but 2018/2022 coverage gaps fail the usability gate. |
| 8 | Is there a realistic PIT implementation defect? | No ledger-level defect was found; PIT-B lineage and market-impact limits still cap claims. |
| 9 | Does a neighboring definition erase the relation? | Yes. Neighboring results change by year and the frozen neighbor gate fails. |
| 10 | Does complexity exceed practical benefit? | The rule is simple, but even its small complexity is not justified by the benefit. |

## UNRESOLVED

1. **Untouched OOS:** no 2018-2025 period is untouched for the newly designed candidate. A genuinely future sample is required.
2. **PIT grade:** strict archival PIT-A membership/revision lineage remains unavailable. The current framework is causally strict inside bounded PIT-B inputs.
3. **Data families:** true PIT growth/value, market-cap style, high/low beta, fund flow, sentiment, and governed cyclical classification remain unavailable. They cannot be silently replaced.
4. **Dispersion and volatility:** one right-tail dispersion feature is promising but insufficient; volatility interaction evidence is absent, not negative.
5. **Residual entry quality:** breadth explains opportunity but not enough terminal conversion. A future predeclared interaction with a genuinely causal entry-quality variable may be valuable, but current data do not authorize one.
6. **Execution realism:** the model enforces next-open, T+1, limits, tradability, lots, costs, and corporate actions, but not order-book queue, endogenous impact, or realized slippage.
7. **Causal exits:** observed exit-lineage differences are not counterfactual exit effects. No post-exit path was used.

The highest-value next experiment is not another 2018-2025 threshold. It is one of:

- freeze the existing breadth-opportunity hypothesis and evaluate it prospectively on future untouched PIT-A-quality data; or
- register one genuinely PIT missing data family, define one economic hypothesis before outcomes, and test whether it adds to breadth without designing a strategy.

## Final answers to the ten required questions

### 1. Why does V1 perform differently across years?

Because the supply and magnitude of favorable right-tail paths change, and ordinary trade quality changes with them. Good years have enough >=20%/50% winners to overcome a usually negative median trade; bad years lack those winners and accumulate false breakouts/ordinary losses. Severe-loss frequency and exposure alone do not explain the ordering.

### 2. What are the most important market-regime variables?

Breadth level and breadth improvement: the fraction of eligible stocks above MA20, the fraction with positive 20-day returns, and the 20-day change in MA20 breadth. They add MFE/opportunity information after fixed trend controls. A 20-day cross-sectional right-tail-strength fraction is a secondary, ambiguous lead.

### 3. Which variables are not useful?

Continuous index trend/persistence adds no robust primary information among entries already admitted by V1's MA20 gate. The proposed leadership-persistence/fast-rotation story is contradicted. Breadth is not useful as a severe-loss or exit-conversion gate. Volatility, style, liquidity, risk appetite, and broader dispersion are either ambiguous, completeness-only screens, or unavailable under required PIT governance—not proven useless in general.

### 4. In what environment do V1 right-tail winners appear?

They appear more often when participation is broad and improving. Winner20/winner50 and global top-20 cycles have high breadth ranks (~0.65), high-breadth entries have roughly three times the MFE>=20% opportunity rate of low-breadth entries, and false breakouts are less common. The relation is probabilistic and descriptive, not a threshold rule.

### 5. Why are bad regimes bad?

They mostly fail to create favorable excursions. Low-breadth entries have low MFE, a 65.9% false-breakout rate, and negative mean return. Losses are not offset by a right tail. Some bad periods also have severe losses, but high severe-loss frequency can coexist with excellent returns when super-winners are present.

### 6. Is V1-R worth building now?

No. Regime attribution is useful, but the tested simple overlay is not robust, no exit/entry adaptation is supported, the entire historical sample is outcome-consumed, and strict PIT-A/future OOS evidence is absent.

### 7. What is the simplest recommended V1-R?

None. The recommended trading specification is the frozen V1 without a regime overlay. The A40 half-size rule may remain a rejected research artifact, not a deployment candidate.

### 8. What did the candidate improve and sacrifice relative to V1?

It reduced exposure, turnover, and cost; modestly improved the 2022-2023 block, drawdown in 2/3 blocks, and ex-best20 in 2/3. It sacrificed 5.1% of baseline winner20 entries and 9.4% of baseline Top-20 positive P&L, lost 18.14 percentage points of return and worsened drawdown in 2018-2021, and lost 3.36 points in 2024-2025. Its benefits are not stable after exposure normalization or neighboring definitions.

### 9. Which conclusions are truly robust?

The baseline identity/execution reconciliation; the right-tail/year decomposition; breadth's positive MFE/opportunity and negative false-breakout associations with 8/8 LOYO signs; its incrementality after fixed trend controls; the absence of a severe-loss relationship; the controlled failure of breadth conversion/capture; the rejection of exit adaptation; and the candidate's temporal/neighbor robustness failure. Deployability is not robust because there is no untouched OOS or PIT-A history.

### 10. What is the most valuable next research?

Prospective confirmation on future untouched PIT-A-quality data, using the already frozen breadth-opportunity hypothesis without redesign. In parallel, acquire and register one missing causal style/liquidity/risk-appetite input and test one preregistered incremental mechanism. Do not run another threshold or combination search on 2018-2025.

## Reproducibility and artifact map

The durable research directory contains the fixed goal, contract, state, data audit, hypothesis ledger, experiment registry, all specs, scripts, machine artifacts, and phase reports. Key identities are:

| Artifact | SHA-256 |
|---|---|
| Frozen V1 strategy | `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a` |
| Daily regime feature library | `5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6` |
| EXP-P7-003 spec | `620dbbcbde02fe1dae1867a7237dfa23eee85ad3d87b8b80c28d491db387911e` |
| Phase 7 candidate result | `adec6fcb36848b5d3a2a560feeef87df8606f215c381d6a8f69b483482a662a8` |
| Phase 7 15-ledger manifest | `4cfcb8a339f43d096b18c01e267762f8070c5326d85c6a1955774876bbbb9fe5` |
| Phase 8/9 result | `8fd4532d8e183ce7ae8b5f59f94104d4e46b322cee4f96a3059f1135ffca02fe` |
| Phase 8 rolling CSV | `2d45bde3eed9f10a000aef37fe4c2cac867bd98e236ce9c5c7d227cdfe51debc` |
| Phase 8 temporal CSV | `3a391b0990784c078d5fc129c4f1ccf2e93ec4017e576e3c2ae0812fd2102f91` |

Formal invalidations are preserved: EXP-P3-001 and EXP-P4-001 bound superseded correctness revisions before execution; EXP-P7-001 had an incorrect warmup identity; EXP-P7-002 hit the exact legacy whole-registry hash gate before replay; the first Phase 7 control-projection attempt is isolated rather than deleted. None contaminates the final result.

Targeted validation completed during the research includes:

- baseline integrity: 8 passed;
- Phase 2/3: 9 passed;
- Phase 5/6: 10 passed;
- Phase 7 hook/authorization plus Phase 8/9: 12 passed in the final targeted selection;
- deterministic full derived reruns for Phases 2, 3, 5, and 6, plus the Phase 7 identity manifest and Phase 8/9 outputs. The 15 formal Phase 7 strategy replays were not repeated merely to recreate already hash-frozen ledgers.

No full repository test suite, full-market rebuild, current-survivor performance replay, or unregistered data fallback was used.

## Final research decision

**FACT:** V1's annual performance is highly right-tail dependent.  
**EVIDENCE:** broad participation robustly describes favorable entry paths beyond the existing trend gate.  
**INTERPRETATION:** regime mainly affects entry opportunity/top-winner availability, not severe-loss probability or exit conversion.  
**HYPOTHESIS:** breadth-opportunity is retained for future prospective testing.  
**FAILED HYPOTHESIS:** trend strength, rotation persistence, breadth downside gating, exit adaptation, and the tested exposure overlay do not pass.  
**STRATEGY CANDIDATE:** A40 is rejected; frozen V1 remains unchanged.  
**UNRESOLVED:** future untouched PIT-A evidence and governed missing data families.

This is a successful negative strategy result: the framework explains more of when V1 works without manufacturing a V1-R from the same consumed history.
