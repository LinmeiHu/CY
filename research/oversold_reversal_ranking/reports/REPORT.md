# A-share Oversold Reversal Ranking V1 — Final Report

## ENVIRONMENT

- Worktree: `/Users/linmei/Documents/CY-oversold-reversal-ranking`
- Branch: `research/oversold-reversal-ranking-v1`
- Starting HEAD: `2e5383aff4e76e9c70baf44d48627ce86cac75c3`
- Starting status: clean
- Ending HEAD: the research checkpoint commit containing this report; its SHA is reported in
  the final handoff.
- Scope: all created files are confined to `research/oversold_reversal_ranking/`; predecessor
  artifacts are unchanged.

## PREDECESSOR FINDING

Volume Exhaustion Bottom V1's threshold dry-up failed. V2's continuous dry-up also failed
after date/depth/distance/liquidity matching, daily ranking, PIT-industry control, and
20-session event de-duplication. This study therefore treats volume exhaustion as closed and
investigates the ordinary oversold mean-reversion carrier exposed by those negative results.

## DATA

- Authority: registered `CY-006`, snapshot `CYQ-PIT-B-DAILY-2018-2026-V2`; all nine frozen
  Parquet partition hashes were verified in the final run.
- Raw coverage: 2018-01-02 to 2026-08-12, 9,421,907 rows, 5,682 historical symbols, and
  9,063,454 hard-valid rows. Aggregate time-travel violations: zero.
- Universe/chronology: the predecessor's hard-valid historical universe, clean 60-session
  lineage, corporate-action-safe reference-price chain, and next-legal-open entry are reused.
  Signal features stop at date-t close; outcomes begin at the next listed legal open.
- Benchmark: causal compounded 20-session return of the equal-weight eligible CY-006 panel.
- Industry: the PIT industry attached to each historical row and a causal equal-weight return
  for that industry.
- Limitations: PIT-B rather than strict PIT-A action revision history; the benchmark is a
  research aggregate, not a tradable index; no announcement/fundamental shock classifier,
  costs, minute/L2 fills, or portfolio construction.

## OVERSOLD UNIVERSE

LOW is exactly the predecessor definition: causal adjusted-close drawdown from the trailing
60-session high <= -15%; adjusted close no more than 5% above the trailing 60-session adjusted
intraday low; at least 120 valid trading sessions; 20-session median amount >= CNY 10 million;
and a hard-valid, trading, non-ST signal row with clean required lineage. This report additionally
requires legal entry and a complete 20-session outcome path.

- Complete observations: 867,577
- Securities: 5,154
- Signal dates: 1,562, from 2020-01-02 to 2026-07-15
- Fixed 20-trading-session de-duplicated events: 58,499
- PIT industries represented: 128

## VARIABLE DEFINITIONS

- **Drawdown depth:** `depth_score = -drawdown_60`; larger is deeper.
- **Crash speed:** `-causal adjusted Ret10 / -drawdown_60`; larger means more of the current
  peak drawdown accumulated in the last ten sessions (fast crash rather than slow bleed).
- **Broad-market-relative decline:** stock causal Ret20 minus causal equal-weight market Ret20;
  larger means less stock-specific underperformance and thus a more systematic decline.
- **PIT-industry-relative decline:** stock causal Ret20 minus its historical PIT-industry Ret20;
  same orientation. It is supporting, not the primary matrix.
- **Distance to recent low:** adjusted close / causal 60-session adjusted intraday low - 1;
  zero is directly at the low. `near_low_score` reverses this so larger means nearer.
- **Depth regions:** moderate (-20%,-15%], deep (-30%,-20%], very deep (-40%,-30%], and
  extreme <= -40%. Crash/relative terciles are formed separately inside each depth region.
- **Outcomes:** gross Ret5/Ret10/Ret20 from next legal open; MFE20/MAE20 use adjusted intraday
  extremes over the same path.

## DRAWDOWN DEPTH RESULTS

Q1 is shallowest and Q5 deepest. All figures other than N/range are percentages.

| Q | Drawdown range | N | Mean R5 | Median R5 | Hit R5 | Mean R10 | Median R10 | Hit R10 | Mean R20 | Median R20 | Hit R20 | MFE20 | MAE20 | P90 R20 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | -15.0% to -18.1% | 173,516 | 0.07 | -0.08 | 48.73 | 0.15 | -0.17 | 48.66 | 0.79 | 0.00 | 49.94 | 8.99 | -7.58 | 13.01 |
| 2 | -18.1% to -21.4% | 173,516 | 0.07 | -0.10 | 48.77 | 0.16 | -0.16 | 48.84 | 0.97 | 0.00 | 50.18 | 9.73 | -8.10 | 14.13 |
| 3 | -21.4% to -25.3% | 173,515 | 0.12 | -0.06 | 49.20 | 0.21 | -0.12 | 49.18 | 1.07 | 0.02 | 50.20 | 10.52 | -8.71 | 15.09 |
| 4 | -25.3% to -30.7% | 173,515 | 0.11 | -0.05 | 49.30 | 0.28 | -0.15 | 49.11 | 1.42 | 0.26 | 50.90 | 11.59 | -9.52 | 16.62 |
| 5 | -30.7% to -89.0% | 173,515 | 0.79 | 0.23 | 51.24 | 1.89 | 0.50 | 52.12 | 3.67 | 1.68 | 55.07 | 15.10 | -10.73 | 23.10 |

The pooled curve is ordered at Ret20 and accelerates in Q5. Mean, median, and hit rate all
improve there, so the result is not only a few large winners, although the expanding P90 and
MFE show meaningful right-tail contribution. Risk also rises: mean MAE worsens from -7.58% to
-10.73%.

The economic extreme region (<= -40%, N=39,616) does **not** fail: mean/median Ret20 are
7.74%/4.70%, hit rate 61.76%, MFE20 20.10%, and MAE20 -11.19%. De-duplicated extreme events
(N=1,267) retain 6.53% mean, 4.33% median, and 61.80% hit rate. V1 therefore finds no
price-only extreme-drawdown exclusion frontier.

## DRAWDOWN × CRASH SPEED

T1/T2/T3 mean Slow/Medium/Fast. These are complete pooled matrices, not matched daily spreads.

| Depth | Speed | N | Mean R5 | Mean R10 | Mean R20 | Median R20 | Hit R20 | MFE20 | MAE20 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Moderate | Slow | 91,916 | -0.08% | 0.13% | 0.67% | 0.00% | 49.82% | 9.02% | -7.16% |
| Moderate | Medium | 91,916 | 0.03% | 0.16% | 0.68% | -0.13% | 49.31% | 8.93% | -7.61% |
| Moderate | Fast | 91,916 | 0.26% | 0.19% | 1.20% | 0.29% | 51.11% | 9.72% | -8.43% |
| Deep | Slow | 133,852 | 0.10% | 0.30% | 0.84% | -0.10% | 49.50% | 10.56% | -8.07% |
| Deep | Medium | 133,852 | 0.17% | 0.25% | 0.95% | -0.06% | 49.63% | 10.45% | -8.72% |
| Deep | Fast | 133,852 | 0.05% | 0.11% | 1.76% | 0.58% | 52.09% | 11.40% | -10.00% |
| Very deep | Slow | 50,219 | 0.31% | 0.55% | 1.39% | 0.00% | 49.89% | 12.84% | -9.44% |
| Very deep | Medium | 50,219 | 0.22% | 0.16% | 1.51% | 0.19% | 50.56% | 12.60% | -10.48% |
| Very deep | Fast | 50,219 | 0.26% | 1.77% | 4.27% | 2.88% | 58.33% | 14.98% | -11.67% |
| Extreme | Slow | 13,206 | 0.69% | 1.20% | 2.61% | 1.07% | 53.27% | 15.57% | -10.30% |
| Extreme | Medium | 13,205 | 0.60% | 1.38% | 3.65% | 2.02% | 55.77% | 16.30% | -12.01% |
| Extreme | Fast | 13,205 | 6.37% | 13.27% | 16.97% | 14.25% | 76.25% | 28.43% | -11.25% |

The pooled answer appears to be yes: Fast minus Slow Ret20 expands from +0.53 percentage
points in moderate to +14.37 points in extreme drawdowns. The raw de-duplicated matrix also
shows positive Fast-minus-Slow spreads in all four regions (+1.73, +3.42, +4.81, +9.48
points). However, the date × depth matched incremental spread is -0.18 points in all
observations and **-0.62 points** in de-duplicated events; mean daily Ret20 rho is -0.0130.
Thus the attractive pooled matrix is a time/depth/event-selection association, not reliable
same-day stock-ranking evidence.

## DRAWDOWN × RELATIVE DECLINE

T1/T2/T3 mean Idiosyncratic/Mixed/Systematic market-relative decline.

| Depth | Attribution | N | Mean R5 | Mean R10 | Mean R20 | Median R20 | Hit R20 | MFE20 | MAE20 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Moderate | Idiosyncratic | 91,916 | -0.16% | -0.09% | 0.07% | -0.69% | 46.73% | 8.65% | -7.63% |
| Moderate | Mixed | 91,916 | 0.05% | 0.29% | 0.90% | 0.07% | 50.32% | 9.24% | -7.57% |
| Moderate | Systematic | 91,916 | 0.33% | 0.27% | 1.57% | 0.68% | 53.19% | 9.77% | -8.01% |
| Deep | Idiosyncratic | 133,852 | -0.16% | -0.27% | -0.19% | -1.13% | 45.63% | 10.03% | -9.21% |
| Deep | Mixed | 133,852 | 0.02% | 0.19% | 1.19% | 0.05% | 50.21% | 10.76% | -8.82% |
| Deep | Systematic | 133,852 | 0.46% | 0.74% | 2.54% | 1.29% | 55.38% | 11.62% | -8.76% |
| Very deep | Idiosyncratic | 50,219 | -0.01% | -0.05% | 0.80% | -0.46% | 48.54% | 12.49% | -10.70% |
| Very deep | Mixed | 50,219 | -0.14% | 0.39% | 1.98% | 0.50% | 51.58% | 13.12% | -10.74% |
| Very deep | Systematic | 50,219 | 0.93% | 2.14% | 4.39% | 2.75% | 58.66% | 14.82% | -10.14% |
| Extreme | Idiosyncratic | 13,206 | 2.40% | 3.78% | 5.80% | 2.78% | 57.57% | 19.07% | -11.16% |
| Extreme | Mixed | 13,205 | 2.32% | 5.24% | 7.57% | 4.62% | 61.09% | 20.05% | -11.60% |
| Extreme | Systematic | 13,205 | 2.93% | 6.83% | 9.86% | 6.90% | 66.63% | 21.19% | -10.80% |

The pooled matrix again supports the economic story, with Systematic-minus-Idiosyncratic
Ret20 spreads of +1.50, +2.73, +3.59, and +4.06 points across depth regions. Yet the primary
date × depth matched spread is -0.09 points, the de-duplicated matched spread is -0.08 points,
and mean daily Ret20 rho is effectively zero (+0.0002). PIT-industry-relative decline is the
best supporting variable, but adds only +0.11 points in matched observations and reverses to
-0.13 points after de-duplication. Market/industry-driven decline therefore does not meet the
incremental standard.

## THREE-AXIS INTERACTION

This check uses the deeper half and only outer axis terciles.

| Crash | Attribution | N | Mean R5 | Mean R10 | Mean R20 | Median R20 | Hit R20 | MFE20 | MAE20 | P90 R20 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fast | Idiosyncratic | 67,332 | 0.44% | 0.65% | 1.69% | -0.05% | 49.75% | 12.75% | -10.36% | 19.01% |
| Fast | Systematic | 33,918 | 1.46% | 4.33% | 8.00% | 6.33% | 67.74% | 17.41% | -11.83% | 27.73% |
| Slow | Idiosyncratic | 36,489 | -0.14% | -0.09% | 0.08% | -0.84% | 46.92% | 11.15% | -9.33% | 15.28% |
| Slow | Systematic | 57,725 | 0.72% | 1.06% | 2.27% | 0.84% | 53.24% | 12.77% | -8.44% | 17.60% |

Fast + Systematic is the strongest pooled region and Slow + Idiosyncratic the weakest. The
same descriptive ordering survives de-duplication (7.68% versus 0.27% mean Ret20; 6.81%
versus -0.89% median). It is nevertheless not promoted as a ranking frontier because both
component variables fail date-matched incrementality and daily rank tests. The 3D result is
a useful description of clustered episodes, not independent stock-selection evidence.

## DAILY CROSS-SECTIONAL RESULTS

All variables are oriented so positive rho is the hypothesized direction. Each row uses 1,507
dates with at least ten complete LOW observations.

| Variable | Horizon | Mean rho | Median rho | Expected-sign days |
|---|---:|---:|---:|---:|
| Depth | R5 | -0.0006 | -0.0099 | 47.58% |
| Depth | R10 | -0.0016 | -0.0023 | 49.57% |
| Depth | R20 | -0.0101 | -0.0177 | 45.72% |
| Crash speed | R5 | -0.0191 | -0.0136 | 45.99% |
| Crash speed | R10 | -0.0239 | -0.0124 | 46.78% |
| Crash speed | R20 | -0.0130 | -0.0079 | 46.52% |
| Market-systematic | R5 | 0.0018 | 0.0028 | 51.03% |
| Market-systematic | R10 | 0.0018 | 0.0041 | 50.83% |
| Market-systematic | R20 | 0.0002 | 0.0036 | 51.16% |

Pooled depth mean reversion is not equivalent to a daily opportunity rank. Depth and crash
speed have slightly adverse daily relationships; market attribution is indistinguishable
from zero. PIT-industry-relative Ret20 rho is only +0.0090 with 52.62% expected-sign days.

## INCREMENTALITY

Spreads are equal-weight top-minus-bottom terciles within date × depth-region cells (minimum
N=9), so they answer whether the variable adds information beyond depth and calendar date.

| Variable | Cells | R5 spread | R10 spread | R20 spread | Median R20 spread | Hit spread |
|---|---:|---:|---:|---:|---:|---:|
| Crash speed | 4,888 | -0.19% | -0.34% | -0.18% | -0.16% | -1.13 pp |
| Market-systematic | 4,888 | 0.11% | 0.09% | -0.09% | -0.09% | -0.58 pp |
| PIT-industry-systematic | 4,888 | 0.06% | 0.05% | 0.11% | 0.16% | 0.55 pp |
| Near recent low | 4,888 | -0.11% | -0.16% | -0.14% | 0.01% | -0.51 pp |

On de-duplicated events, R20 spreads are -0.62%, -0.08%, -0.13%, and -0.74%, respectively.
Crash speed does not add beyond depth; broad relative decline does not add; the small industry
result fails de-duplication; and proximity to the low is a pooled state effect rather than an
incremental rank. No candidate has a credible independent contribution.

## DE-DUPLICATION

- Depth survives: deepest-minus-shallowest quintile mean Ret20 is +2.89 points in all
  observations and +3.08 points in the 58,499-event sample. De-duplicated Q5 median Ret20 is
  1.97% versus 0.00% in Q1.
- Raw crash and relative matrices retain attractive outer-cell spreads after de-duplication,
  as does the descriptive Fast + Systematic interaction.
- The stricter within-date/depth event comparison rejects those interpretations: crash speed
  is -0.62 points, market attribution -0.08, and industry attribution -0.13 at Ret20.

Repeated LOW rows are not the reason depth survives. They do help make pooled conditional
matrices look more rank-like than the same-date evidence supports.

## TIME STABILITY

The first block is 2020 only because the frozen predecessor signal evaluation begins in 2020.
Spreads are descriptive pooled spreads; rhos are daily Ret20 ranks.

| Period | Deep-Shallow R20 | Fast-Slow R20 | Systematic-Idio R20 | Days | Depth rho | Crash rho | Relative rho |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2020 | -1.03% | 1.84% | -0.30% | 223 | -0.0305 | 0.0096 | -0.0044 |
| 2021-2023 | 1.61% | 3.32% | 1.89% | 727 | -0.0074 | -0.0136 | -0.0060 |
| 2024-2026 | 3.06% | 5.15% | 3.99% | 557 | -0.0056 | -0.0214 | 0.0101 |

Depth's pooled spread is absent/reversed in 2020 and strengthens later. Pooled crash spreads
are positive in every block but daily crash rho is negative in the two larger later blocks.
Relative-decline pooled and daily signs also vary. There is no stable daily ranking frontier.

## LIQUIDITY / INDUSTRY CHECK

The pooled Fast-Slow Ret20 spread is +1.51%, +1.80%, and +1.99% from least- to most-liquid
date-relative terciles; Systematic-Idiosyncratic is +2.29%, +2.56%, and +2.82%. Thus pooled
associations are not confined to illiquid stocks. They still fail within-date incrementality.

After PIT-industry demeaning, mean daily Ret20 rho is -0.0031 for depth, -0.0063 for crash
speed, and -0.0005 for market attribution (1,504 valid days). Industry control does not reveal
a hidden rank signal.

Main Board, ChiNext, and STAR all have positive pooled mean Ret20 (1.55%, 1.56%, 1.92%). STAR's
median is -0.23% and hit rate 49.24%, making its mean more right-tail dependent. No BSE
observation survives the fixed complete-outcome eligibility, so no BSE claim is made.

## FAILURE MODES

- Deep-half Slow + Idiosyncratic observations have only 0.08% mean Ret20, -0.84% median, and
  46.92% hit rate; de-duplicated events are similarly weak (0.27%, -0.89%, 45.91%).
- Fast + Idiosyncratic has 1.69% mean but -0.05% median and a sub-50% hit rate, indicating
  right-tail dependence rather than uniformly better outcomes.
- Extreme drawdowns have higher rebound and higher adverse excursion; V1 has no fundamentals
  to distinguish genuine impairment from technical dislocation.
- All pooled structures are regime-sensitive, and attractive pooled cells can fail same-day
  ranking tests.

## ECONOMIC INTERPRETATION

**Evidence:** oversold mean reversion becomes economically larger in the deepest states and
survives 20-session event de-duplication. No proposed conditioning variable supplies positive,
stable date-matched and daily cross-sectional information beyond that state.

**Interpretation:** severe selloffs create rebound optionality, but much of the apparent
“fast/systematic dislocation” pattern reflects when and where oversold episodes cluster rather
than which oversold stock should be preferred on a given day.

**Speculation:** the missing discriminator may be event/fundamental impairment or causal
price-demand return after the oversold state forms. V1 does not test either and makes no claim
that they work.

## VERDICT

`DEPTH_ONLY`

Oversold mean reversion is credible in pooled and de-duplicated outcomes, with improving
typical as well as tail returns at greater depth. Crash speed, systematic versus idiosyncratic
decline, and distance to low do not add reliable daily ranking information once date and depth
are held comparable. The large pooled interaction is not sufficient evidence for a strategy.

## SINGLE NEXT STEP

Run one focused V2 on **causal price-reversal timing inside a frozen deep-oversold carrier**:
freeze the deep population first, test one economically defined price-only demand-return event,
and require date/depth-matched, de-duplicated, daily-rank, and broad-period survival. Do not
reopen volume dry-up or search multiple confirmation indicators.
