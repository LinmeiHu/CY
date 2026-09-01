# A-share Oversold Reversal Ranking V4 — Risk-Aware Sizing Report

## ENVIRONMENT

- Worktree: `/Users/linmei/Documents/CY-oversold-reversal-ranking`
- Branch: `research/oversold-reversal-ranking-v1`
- Starting HEAD: `98b7a383f4f51f2f84093e2ff41bfeef9d21d0b0`
- Ending HEAD: the V4 checkpoint commit containing this report; its SHA is reported in the
  final handoff.
- Initial status: clean. Final status after checkpoint: clean.
- Scope: all created files are confined to `research/oversold_reversal_ranking/`; authoritative
  V1, V2, and V3 artifacts are unchanged.

## PREDECESSOR FINDINGS

- V1 = `DEPTH_ONLY`: deep drawdown is the oversold mean-reversion carrier.
- V2 = `RISK_FILTER_ONLY`: waiting for right-side reversal reduces downside but forfeits too
  much left-side rebound.
- V3 = `SIZING_SIGNAL_ONLY`: the t0 composite predicts diffuse downside risk, but high-risk
  events remain positive expectation and cannot support a hard veto.

V4 changes only event position size. It tests whether the same average event capital can be
distributed more intelligently, not whether lower exposure mechanically lowers risk.

## FROZEN CARRIER AND SCORE

The exact carrier is V1 LOW plus causal 60-session adjusted-close drawdown `<= -30%`. The
event is the first carrier observation after no carrier observation in the prior 20 trading
rows. V2/V3 next-legal-open entry, Ret5/10/20, MFE20, MAE20, clean-path, and severe-MAE
semantics are unchanged.

V4 reuses all 22,357 valid V3 events across 4,835 securities, 128 PIT industries, and
2020-01-02 through 2026-07-08. There is no additional V4 exclusion.

The imported V3 score is exactly:

`(CLV-danger rank + daily-loss rank + negative-day-persistence rank + gap-danger rank) / 4`.

Each component rank uses all contemporaneous causally valid deep-carrier observations and
only information known by that date's close. Ranking occurs before event and future-outcome
filters, so the continuous score is causally available in an end-of-day batch. Higher score is
more dangerous. The pooled V3 quintile boundaries are full-sample descriptive assignments,
however; V4 is not a production-ready threshold policy.

## FROZEN SIZING POLICIES

| V3 risk quintile | Equal size | Primary raw | Primary normalized | Conservative |
|---:|---:|---:|---:|---:|
| Q1 safest | 1.000 | 1.250 | 1.249979 | 1.00 |
| Q2 | 1.000 | 1.125 | 1.124981 | 0.95 |
| Q3 | 1.000 | 1.000 | 0.999983 | 0.90 |
| Q4 | 1.000 | 0.875 | 0.874985 | 0.80 |
| Q5 riskiest | 1.000 | 0.750 | 0.749987 | 0.70 |

The primary raw mean is `1.0000167733`; dividing by it makes the cohort-weighted primary mean
exactly 1.0 algebraically (observed floating mean `1.0000000000001`). All events retain
positive allocation. The conservative map is not normalized and averages 0.870009.

Capital Ret, MFE, and MAE equal position weight times the inherited underlying outcome. The
underlying severe-event label remains `MAE20 <= -10%` and is unaffected by size. The separate
capital-severe label is `weight * MAE20 <= -10%`. Return/downside efficiency is mean weighted
Ret20 divided by the absolute mean capital MAE20.

## PRIMARY EQUAL-CAPITAL COMPARISON

| Metric | Equal size | Risk-aware size | Difference |
|---|---:|---:|---:|
| Events | 22,357 | 22,357 | 0 |
| Mean position weight | 1.000000 | 1.000000 | effectively 0 |
| Mean weighted Ret5 | 1.08% | 1.19% | +0.11 pp |
| Mean weighted Ret10 | 2.22% | 2.43% | +0.21 pp |
| Mean weighted Ret20 | 4.37% | 4.64% | +0.27 pp |
| Total weighted Ret20 | 976.19 | 1,037.32 | +61.13 |
| Median weighted Ret20 | 2.73% | 2.62% | -0.11 pp |
| Mean capital MAE20 | -10.85% | -10.79% | +0.06 pp |
| Median capital MAE20 | -8.33% | -8.13% | +0.20 pp |
| Q10 capital MAE20 | -24.18% | -24.01% | +0.18 pp |
| Q25 capital MAE20 | -15.04% | -14.67% | +0.37 pp |
| Mean capital MFE20 | 14.95% | 15.08% | +0.13 pp |
| Underlying severe-event rate | 42.14% | 42.14% | unchanged |
| Capital-severe loss rate | 42.14% | 41.08% | -1.06 pp |
| Return/downside efficiency | 0.4024 | 0.4298 | +6.81% relative |

The anti-triviality test passes: average capital is unchanged. Expected return and capital MFE
improve, mean/median/tail capital MAE improve modestly, and capital-severe loss falls. The
slightly lower weighted median Ret20 is the main aggregate tradeoff.

## CAPITAL ALLOCATION

These are shares of total event notional. Mean group weight is capital retained relative to
the equal-size weight of 1.0.

| Future outcome group | Equal capital share | Primary capital share | Change | Primary mean weight |
|---|---:|---:|---:|---:|
| Underlying severe MAE | 42.14% | 41.62% | -0.52 pp | 0.9876 |
| Underlying non-severe | 57.86% | 58.38% | +0.52 pp | 1.0090 |
| V2 no trigger | 14.04% | 13.54% | -0.50 pp | 0.9643 |
| Positive Ret20 | 58.22% | 58.97% | +0.74 pp | 1.0127 |
| Large winner Ret20 >=10% | 30.33% | 31.01% | +0.69 pp | 1.0227 |
| Losing Ret20 | 41.78% | 41.03% | -0.74 pp | 0.9822 |

Sizing does not prevent any falling knife. It reallocates 1.24% less notional per eventual
severe event and 3.57% less per future no-trigger event, while increasing average notional to
positive events and large winners. Loser exposure falls more than winner exposure.

## QUINTILE CONTRIBUTIONS

Contributions divide each quintile's weighted sum by the full 22,357-event cohort, so they
reconcile to the aggregate weighted mean.

| V3 Q | N | Raw mean R20 | Raw mean MAE | Raw severe MAE | Primary weight | Capital share | R20 contribution | MAE contribution |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Q1 | 4,472 | 6.47% | -10.49% | 37.90% | 1.249979 | 25.00% | 1.62% | -2.62% |
| Q2 | 4,472 | 5.36% | -10.57% | 40.00% | 1.124981 | 22.50% | 1.21% | -2.38% |
| Q3 | 4,471 | 4.77% | -10.69% | 41.83% | 0.999983 | 20.00% | 0.95% | -2.14% |
| Q4 | 4,471 | 3.09% | -11.24% | 45.25% | 0.874985 | 17.50% | 0.54% | -1.97% |
| Q5 | 4,471 | 2.14% | -11.27% | 45.74% | 0.749987 | 15.00% | 0.32% | -1.69% |

The frozen V3 score happens to order both risk and raw mean return in this cohort. V4 does not
claim the score was designed for return; it simply reports that the fixed allocation shifts
capital toward groups that realized higher returns and somewhat lower risk.

## CONSERVATIVE OVERLAY

This view deliberately reduces exposure and cannot prove sizing skill.

| Metric | Equal size | Conservative overlay |
|---|---:|---:|
| Mean exposure | 1.0000 | 0.8700 |
| Mean weighted Ret20 | 4.37% | 3.97% |
| Median weighted Ret20 | 2.73% | 2.32% |
| Mean capital MAE20 | -10.85% | -9.41% |
| Q10 capital MAE20 | -24.18% | -20.99% |
| Capital-severe loss rate | 42.14% | 35.42% |
| Return/downside efficiency | 0.4024 | 0.4216 |

The overlay retains 90.82% of equal-size mean return at 87.00% mean exposure. A uniform
87.00% scale would mechanically produce 3.80% mean Ret20 and -9.44% mean capital MAE; the
risk-conditioned overlay reaches 3.97% and -9.41%, adding +0.17 return points and +0.03 MAE
points beyond uniform scaling. Most absolute risk reduction nevertheless comes from trading
less.

## SIMPLE BASELINE COMPARISON

Applying the same normalized primary weights to V3's frozen close-location quintile lowers
mean Ret20 from 4.37% to 4.11%, worsens mean capital MAE from -10.85% to -10.90%, and reduces
efficiency from 0.4024 to 0.3769. It also increases severe-event capital share to 42.61% and
no-trigger share to 14.06%. The V3 composite is materially better than its simplest constituent
for allocation; complexity earns its place in this descriptive comparison.

## TIME STABILITY

The 2018-2020 label contains observed 2020 events only because inherited eligibility begins in
2020. The globally frozen map is not re-normalized inside periods, so period mean exposure can
differ from 1 even though the full-cohort mean is exactly 1.

| Period | Primary mean weight | Equal R20 | Primary R20 | Equal capital MAE | Primary capital MAE | Equal/primary efficiency | Equal/primary severe capital share |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2018-2020 | 0.9854 | 1.02% | 1.08% | -8.61% | -8.39% | 0.1185 / 0.1289 | 35.59% / 35.10% |
| 2021-2023 | 0.9798 | 3.45% | 3.49% | -8.76% | -8.50% | 0.3942 / 0.4105 | 35.80% / 35.17% |
| 2024-2026 | 1.0198 | 5.81% | 6.33% | -13.05% | -13.20% | 0.4453 / 0.4793 | 48.77% / 48.07% |

Return, Q10 capital MAE, efficiency, severe-capital share, and no-trigger-capital share improve
in every block. Mean capital MAE improves in the first two blocks but worsens 0.15 points in
2024-2026 because the fixed global map allocates 1.98% more average event notional there. The
result is directionally stable but not uniformly better on every metric.

## LIQUIDITY / INDUSTRY SANITY

Across least-, middle-, and most-liquid thirds, return/downside efficiency improves from
0.4196 to 0.4400, 0.4353 to 0.4654, and 0.3547 to 0.3841. Severe-event capital share falls by
0.44, 0.47, and 0.67 points. Mean capital MAE worsens in the first two buckets because their
mean weights rise to 1.0316 and 1.0127, but improves in the most-liquid bucket where mean
weight is 0.9602. The effect is not an illiquidity-only artifact.

Among 96 PIT industries with at least 50 events, 84.38% have positive weighted-return
difference, 56.25% improve mean capital MAE, 83.33% improve efficiency, and 75.00% reduce
severe-event capital share. The largest industry is 4.62% of events. No one PIT industry drives
the aggregate result.

## LIMITATIONS

- This is event-level arithmetic, not a daily portfolio NAV simulation. Signals and 20-session
  holding paths overlap.
- Same average event weight does not impose same invested capital on every date. Simultaneous
  capital competition, cash constraints, and opportunity ranking remain unresolved.
- V3's continuous score is t0-causal, but the pooled quintile boundaries used here are
  full-sample descriptive thresholds requiring deployable validation.
- Transaction costs, slippage, impact, turnover, industry limits, and portfolio concentration
  are not modeled.
- Underlying severe-event incidence remains 42.14%; sizing changes capital exposure, not the
  stock paths themselves.

## ECONOMIC INTERPRETATION

The V3 score deserves to control event-level capital in this falsification. With unchanged
average capital, the frozen monotonic map improves expected weighted return, downside
efficiency, tail capital MAE, and allocation away from severe/no-trigger events while preserving
and slightly increasing capital allocated to future winners. Improvements in mean capital MAE
and severe-capital concentration are modest, so this is evidence for sizing—not evidence that
falling-knife risk has been solved.

## VERDICT

`SIZING_SURVIVES`

Most pre-specified success conditions hold under equal average exposure: return is not damaged,
capital downside improves, less capital reaches severe and no-trigger events, winner exposure
is preserved, efficiency improves in every broad period and liquidity bucket, and PIT-industry
results are broad. The modest magnitude and event-level design require a real portfolio test
before any production claim.

## SINGLE NEXT STEP

Freeze the carrier, V3 risk score, and V4 sizing map, then run the first true
**overlapping-position portfolio backtest with realistic capital competition and transaction
costs**. Do not execute it automatically.
