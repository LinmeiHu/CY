# A-share Oversold Reversal Ranking V3 — Causal t0 Risk Report

## ENVIRONMENT

- Worktree: `/Users/linmei/Documents/CY-oversold-reversal-ranking`
- Branch: `research/oversold-reversal-ranking-v1`
- Starting HEAD: `7fad7e716a051f96abb75c278d3f35b5195b4175`
- Ending HEAD: the V3 checkpoint commit containing this report; its SHA is reported in the
  final handoff.
- Initial status: clean. Final status after checkpoint: clean.
- Scope: every created file is inside `research/oversold_reversal_ranking/`; authoritative V1
  and V2 artifacts are unchanged.

## PREDECESSOR FINDINGS

V1 = `DEPTH_ONLY`. Drawdown depth carried oversold mean reversion, while crash speed and
market/PIT-industry attribution failed incremental return ranking.

V2 = `RISK_FILTER_ONLY`. Immediate entry preserved more return than waiting for the frozen
reversal pattern, but future no-trigger events were materially dangerous. V3 therefore asks
whether a minority of falling knives can be identified from t0-close price state. It predicts
risk rather than searches for return enhancement or another trigger.

## FROZEN CARRIER

The carrier is the exact V2 primary carrier: exact V1 LOW plus causal 60-session adjusted-close
drawdown `<= -30%`. An event is the first carrier observation after no carrier observation in
the prior 20 trading rows. V2's legal next-open entry and clean 25-session validity rules are
unchanged.

- V2 cohort: 22,543 events, 4,836 securities, 2020-01-02 through 2026-07-08.
- Valid V3 cohort: 22,357 events, 4,835 securities, the same date range, and 128 PIT industries.
- Exact difference: 186 events have a zero-range t0 bar, so close location is undefined and
  fails closed. There are no other feature-availability exclusions.
- The causal daily score universe averages 675.83 contemporaneous deep observations (range
  1 to 3,085); it is formed before event and future-outcome filtering.

## PRIMARY RISK OUTCOME

The primary label is the exact V2 immediate-entry condition `MAE20 <= -10%`. MAE20 starts at
the next legal-session open after t0 and uses the adjusted intraday lows through t0+20. It is
not a terminal-loss label and its threshold was not changed after outcome inspection.

Valid V3 baseline:

- Mean/median MAE20: -10.85% / -8.33%.
- Severe-MAE incidence: 42.14% (9,422 events).
- Mean/median Ret20: +4.37% / +2.73%.
- No-trigger incidence: 14.04% (3,139 events).
- Mean MFE20: +14.95%.

## FROZEN t0 FEATURES

These variables and orientations were frozen in `v3_risk_methodology.md` before the broad
outcome-bearing run.

1. Close-location danger = `1 - (close-low)/(high-low)`; higher means a close nearer the t0
   low. A zero-range day is unavailable.
2. Current-day loss danger = `-(close/preclose-1)`; higher means a worse t0 daily shock.
3. Five-session negative-day persistence = the number of negative reference-price sessions
   in t0-4 through t0; higher means more persistent selling.
4. Adverse-gap danger = `-(open/preclose-1)`; higher means a worse overnight repricing into t0.

No future trigger, trigger lag, future CLV, MAE, MFE, or return enters any feature.

## INDIVIDUAL FEATURE RESULTS

Q1 is safest and Q5 most dangerous by the frozen orientation. Returns, excursions, and rates
are percentages.

### Close-location danger

| Q | N | Mean MAE | Median MAE | Severe MAE | Mean R20 | Median R20 | Positive R20 | No trigger | MFE20 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4,472 | -11.25 | -9.07 | 45.84 | 3.17 | 1.65 | 54.65 | 13.75 | 14.42 |
| 2 | 4,472 | -10.67 | -8.58 | 43.27 | 3.16 | 1.50 | 54.83 | 13.33 | 13.86 |
| 3 | 4,471 | -11.09 | -8.16 | 42.25 | 3.61 | 2.00 | 56.86 | 15.39 | 14.17 |
| 4 | 4,471 | -11.15 | -8.39 | 42.59 | 3.94 | 2.60 | 57.82 | 15.59 | 14.34 |
| 5 | 4,471 | -10.09 | -7.75 | 36.77 | 7.96 | 6.53 | 66.96 | 12.14 | 17.95 |

The frozen danger direction fails: a close pinned nearest the t0 low is safer and rebounds
more in Q5. Close location alone is not a falling-knife veto.

### Current-day loss danger

| Q | N | Mean MAE | Median MAE | Severe MAE | Mean R20 | Median R20 | Positive R20 | No trigger | MFE20 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4,472 | -9.98 | -7.98 | 39.49 | 1.22 | 0.00 | 49.98 | 16.21 | 12.27 |
| 2 | 4,472 | -10.47 | -8.40 | 42.29 | 1.61 | 0.26 | 51.03 | 14.47 | 12.47 |
| 3 | 4,471 | -10.91 | -8.79 | 44.67 | 2.29 | 1.11 | 53.48 | 14.87 | 13.47 |
| 4 | 4,471 | -12.34 | -9.62 | 48.65 | 4.92 | 3.55 | 61.22 | 12.88 | 15.50 |
| 5 | 4,471 | -10.56 | -7.66 | 35.63 | 11.79 | 11.41 | 75.42 | 11.76 | 21.03 |

Risk worsens through Q4 but reverses sharply in the most extreme loss bucket. Extreme t0 loss
is rebound-rich, so this feature is not monotonic.

### Five-session negative-day persistence

| Q | Negative days | N | Mean MAE | Median MAE | Severe MAE | Mean R20 | Median R20 | Positive R20 | No trigger | MFE20 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0-1 | 50 | -9.51 | -7.37 | 40.00 | 3.30 | 1.94 | 58.00 | 20.00 | 15.06 |
| 2 | 2 | 1,258 | -10.31 | -8.18 | 40.78 | 3.31 | 1.20 | 54.21 | 17.73 | 14.56 |
| 3 | 3 | 6,542 | -10.73 | -8.29 | 41.44 | 3.31 | 1.38 | 54.26 | 16.83 | 14.24 |
| 4 | 4 | 9,928 | -10.67 | -8.30 | 41.91 | 4.01 | 2.59 | 58.15 | 13.81 | 14.56 |
| 5 | 5 | 4,579 | -11.58 | -8.51 | 44.05 | 6.95 | 5.80 | 65.15 | 9.48 | 16.91 |

Persistence has the clearest individual severe-MAE direction, but Q1 is tiny, continuous MAE
is not perfectly ordered, and no-trigger incidence moves the other way.

### Adverse-gap danger

| Q | N | Mean MAE | Median MAE | Severe MAE | Mean R20 | Median R20 | Positive R20 | No trigger | MFE20 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4,472 | -11.32 | -8.43 | 42.91 | 3.48 | 1.97 | 56.24 | 14.56 | 14.18 |
| 2 | 4,472 | -11.17 | -8.78 | 44.28 | 2.72 | 1.17 | 53.89 | 15.00 | 13.34 |
| 3 | 4,471 | -11.21 | -8.81 | 44.91 | 2.87 | 1.29 | 53.32 | 14.20 | 13.70 |
| 4 | 4,471 | -11.13 | -8.59 | 44.20 | 3.73 | 1.93 | 56.83 | 15.10 | 14.94 |
| 5 | 4,471 | -9.42 | -7.43 | 34.42 | 9.03 | 7.87 | 70.83 | 11.34 | 18.59 |

The most adverse gap bucket is safer and rebound-rich. Gap danger also fails individually.

## COMPOSITE RISK SCORE

Each feature is transformed into its same-date percentile rank among all contemporaneous
causally valid deep observations. All ranks have higher = more dangerous. The frozen score is:

`risk_score = (CLV rank + daily-loss rank + persistence rank + adverse-gap rank) / 4`.

Weights are equal and no outcome was used to fit or drop a component.

| Q | Score range | N | Mean MAE | Median MAE | Severe MAE | Mean R20 | Median R20 | Positive R20 | No trigger | MFE20 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.000-0.377 | 4,472 | -10.49 | -7.52 | 37.90 | 6.47 | 4.96 | 64.27 | 10.62 | 15.95 |
| 2 | 0.377-0.480 | 4,472 | -10.57 | -8.04 | 40.00 | 5.36 | 3.48 | 60.53 | 12.14 | 15.50 |
| 3 | 0.480-0.570 | 4,471 | -10.69 | -8.26 | 41.83 | 4.77 | 3.16 | 59.38 | 13.40 | 15.09 |
| 4 | 0.570-0.673 | 4,471 | -11.24 | -8.83 | 45.25 | 3.09 | 1.46 | 54.48 | 14.67 | 14.32 |
| 5 | 0.673-1.000 | 4,471 | -11.27 | -9.09 | 45.74 | 2.14 | 0.83 | 52.45 | 19.37 | 13.89 |

Unlike the raw individual features, the contemporaneously normalized equal-weight score has
an ordered severe-MAE, median-MAE, return, and no-trigger gradient. Mean MAE weakens broadly,
although most of its Q1-Q5 change occurs by Q4.

## SEVERE-RISK SEPARATION

Composite Q5 minus Q1:

- Severe-MAE incidence: +7.84 percentage points.
- Mean MAE20: -0.78 points; median MAE20: -1.57 points.
- No-trigger incidence: +8.75 points.
- Mean Ret20: -4.33 points.

The score predicts risk and lower expected return, but the continuous mean-MAE separation is
modest relative to the 42.14% baseline severe incidence.

## CONDITIONAL / MATCHED RESULTS

Within 628 calendar-date x fixed drawdown-depth cells (18,848 event assignments), high-minus-
low risk terciles show +3.61 points of severe-MAE incidence, -0.45 points of mean MAE, +1.98
points of no-trigger incidence, and -0.44 points of Ret20. Thus the pooled sign survives time
and depth conditioning, but it is not broad across every cell: only 39.65% of cells have a
strictly positive severe-rate spread, while 57.48% have worse mean MAE.

Across V2 liquidity thirds, Q5-Q1 severe spreads are +9.95, +7.08, and +9.01 points; mean-MAE
spreads are -1.26, -0.84, and -1.28 points. The score is not an illiquidity proxy. Within-PIT-
industry normalization leaves +8.37 points severe incidence, -0.93 points mean MAE, and +8.59
points no-trigger separation across 128 industries. Main Board, ChiNext, and STAR all retain
positive severe-risk separation (+7.68, +5.96, and +9.14 points). No BSE event survives.

## RISK CAPTURE

These fixed full-sample fractions are descriptive, not deployable score thresholds.

| Highest risk | N | Severe events captured | No-trigger events captured | Severe incidence | Mean MAE | Mean R20 |
|---:|---:|---:|---:|---:|---:|---:|
| 10% | 2,236 | 10.89% | 14.24% | 45.89% | -11.33% | 1.73% |
| 20% | 4,472 | 21.72% | 27.62% | 45.75% | -11.27% | 2.14% |
| 30% | 6,708 | 32.66% | 38.29% | 45.87% | -11.31% | 2.32% |

No-trigger risk is meaningfully concentrated, but severe-MAE capture is only slightly above
the fraction excluded. This is weak support for a hard veto.

## VETO POLICY TABLE

Skipped events earn 0% cash in full-cohort opportunity returns. Retained-trade metrics are
reported separately.

| Policy | Participation | Full-cohort R20 | Retained mean R20 | Retained median R20 | Retained MAE | Retained severe MAE | Severe avoided | Winners skipped |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BUY ALL | 100.00% | 4.37% | 4.37% | 2.73% | -10.85% | 42.14% | 0 | 0 |
| VETO TOP 10% | 90.00% | 4.19% | 4.66% | 2.97% | -10.80% | 41.73% | 1,026 | 1,134 |
| VETO TOP 20% | 80.00% | 3.94% | 4.92% | 3.25% | -10.75% | 41.24% | 2,046 | 2,345 |
| VETO TOP 30% | 70.00% | 3.67% | 5.24% | 3.55% | -10.65% | 40.55% | 3,077 | 3,544 |

Opportunity-level medians are 2.73%, 1.16%, 0%, and 0%; opportunity positive-event rates are
58.22%, 53.15%, 47.73%, and 42.37%. Conditioning only on retained trades makes returns look
better, but that is not the fair policy comparison.

## ALPHA RETENTION

- Top-10% veto retains 96.04% of baseline expected return while reducing retained severe-MAE
  incidence by only 0.42 points and participation by 10 points.
- Top-20% veto retains 90.20% of Alpha while reducing severe incidence by 0.90 points and
  participation by 20 points.
- Top-30% veto retains 84.05% of Alpha while reducing severe incidence by 1.60 points and
  participation by 30 points.

The return retained is high, but risk reduction per opportunity forfeited is too small to
justify exclusion.

## SKIPPED EVENTS

| Highest risk | Mean R20 | Median R20 | Severe MAE | Positive R20 | All >=10% winners skipped | All severe events avoided | Mean MFE |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10% | 1.73% | 0.35% | 45.89% | 50.72% | 8.05% | 10.89% | 13.62% |
| 20% | 2.14% | 0.83% | 45.75% | 52.44% | 16.53% | 21.72% | 13.88% |
| 30% | 2.32% | 0.91% | 45.87% | 52.83% | 25.21% | 32.66% | 14.01% |

Skipped events are a mixture: they are more dangerous than average, yet remain positive-
expectation and contain many winners. They are not a clean bad-trade cohort.

## SIMPLE BASELINE COMPARISON

The simplest constituent, close-location danger, has Q5-Q1 severe-MAE separation of -9.07
points, mean-MAE separation of +1.16 points, and no-trigger separation of -1.61 points—the
opposite of the frozen danger hypothesis. The composite produces +7.84, -0.78, and +8.75
points respectively. Composite normalization and combination are therefore necessary for the
observed risk signal, although they still do not create a useful hard veto.

## TIME STABILITY

| Period | N | Q5-Q1 severe MAE | Q5-Q1 mean MAE | Top-20 severe capture | Baseline R20 | Top-20 veto R20 |
|---|---:|---:|---:|---:|---:|---:|
| 2020 | 2,242 | +6.32 pp | -1.48 pp | 20.43% | 1.02% | 0.93% |
| 2021-2023 | 9,145 | +10.22 pp | -1.37 pp | 23.12% | 3.45% | 2.97% |
| 2024-2026 | 10,970 | +12.44 pp | -1.97 pp | 22.19% | 5.81% | 5.36% |

The Q5-Q1 direction is stable and strengthens in later periods. Yet top-20 severe-event
capture remains close to its 20% selection rate in every block, confirming weak veto
concentration rather than a one-regime failure.

## ECONOMIC INTERPRETATION

Evidence supports a relative, composite state rather than a standalone candle rule. Events
that are simultaneously more unresolved than same-date deep-oversold peers across close
location, current shock, persistence, and gap have worse subsequent downside, fewer terminal
winners, and substantially more future no-trigger outcomes. Raw extremes in close location,
daily loss, and gap are themselves rebound-rich, so no individual mechanism should be claimed.

The score appears to describe unresolved cross-sectional selling pressure, but high-risk
events still retain positive mean return and large rebound optionality. The evidence supports
reducing exposure intensity, not declaring those opportunities uninvestable.

## VERDICT

`SIZING_SIGNAL_ONLY`

The causal t0 score has an ordered, time-stable downside/no-trigger gradient that survives
drawdown, liquidity, and PIT-industry checks. A hard veto fails economically: severe events
are barely more concentrated than the skipped fraction, retained risk improves only modestly,
and skipped events remain positive-expectation with many winners. The score merits future
position-sizing research, not outright exclusion.

## SINGLE NEXT STEP

Lock the frozen V3 score and run one focused V4 on **causal position sizing** that preserves
deep-oversold participation while reducing exposure to high-risk events. Do not execute it
automatically and do not reopen feature or carrier selection.
