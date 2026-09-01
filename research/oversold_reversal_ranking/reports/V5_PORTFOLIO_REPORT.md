# A-share Deep Oversold Portfolio V5 — Final Report

## ENVIRONMENT

- Worktree: `/Users/linmei/Documents/CY-oversold-reversal-ranking`
- Branch: `research/oversold-reversal-ranking-v1`
- Starting HEAD: `29906643e7ea9c0426d3c4ca7faf23e94fbd02d8`
- Ending HEAD: the V5 checkpoint commit containing this report; its SHA is reported in the
  final handoff.
- Initial status: clean. Final status after checkpoint: clean.
- Scope: all new files are confined to `research/oversold_reversal_ranking/`; authoritative
  V1-V4 artifacts are unchanged.

## PREDECESSOR FINDINGS

- V1 = `DEPTH_ONLY`: large causal drawdown is the mean-reversion carrier.
- V2 = `RISK_FILTER_ONLY`: waiting reduces downside but sacrifices early rebound.
- V3 = `SIZING_SIGNAL_ONLY`: the t0 score predicts diffuse downside risk, not a clean veto.
- V4 = `SIZING_SURVIVES`: frozen event-level risk sizing improved equal-capital allocation.

V5 is portfolio realization rather than signal discovery. It holds the carrier, continuous
score, relative sizing slope, 20-session horizon, and opportunity stream fixed while forcing
all signals to share one finite pool of cash.

## FROZEN STRATEGY CONTRACT

- Carrier: exact V1 LOW plus causal 60-session adjusted-close drawdown `<= -30%`.
- Event: first carrier observation after no carrier observation in the prior 20 security
  trading rows.
- Signal and entry: t0 close, then the inherited next listed legal open.
- Holding/exit: stay invested through t0+20 close, completing 20 holding sessions, then sell
  at the first legal open on or after t0+21. A blocked sale is carried forward.
- Price coordinate: inherited causal close/preclose total-return chain;
  `adjusted_open = adjusted_close * open / close`; lots hold normalized adjusted units.
- New-entry tranche: at most 5% of opening pre-entry NAV each day, independently; unused
  budget remains cash and is never carried forward.
- Cash: initial NAV 1.0, zero interest, no borrowing, leverage, shorting, minimum order, or
  integer-lot approximation.
- Risk score: unchanged V3 equal average of four contemporaneous deep-carrier danger ranks.
- Relative map Q1-Q5: `1.25 / 1.125 / 1.00 / 0.875 / 0.75`, normalized only among that
  entry date's executable signals. Equal Size splits the identical tranche evenly.
- Base costs: buy 8 bps; sell 18 bps before 2023-08-28 and 13 bps thereafter. The one stress
  doubles commission/slippage while retaining historical stamp duty.

## CAUSAL SIZING DEPLOYMENT

V4 pooled quintiles were descriptive and non-deployable. V5 maps each continuous score to
the empirical distribution of valid event scores from dates strictly before t. Same-date
signals share the same untouched prior distribution. Empirical-CDF boundaries at 20/40/60/80%
create Q1-Q5. Fewer than 250 prior scores invokes neutral Q3 weight 1.0.

- Warm-up events: 284; first post-warm-up signal: 2020-03-19.
- Causal Q1-Q5 counts: 4,849 / 4,422 / 4,704 / 4,082 / 4,300.
- All-event causal versus descriptive exact bucket agreement: 89.32%; mean absolute shift
  0.112 buckets; only 0.52% shift by two or more; raw-weight correlation 0.9705.
- Post-warm-up agreement: 90.25%; no event shifts by two or more; weight correlation 0.9772.

The causal translation closely preserves V4's descriptive map. Later sizing failure is not
explained by an unstable deployment bridge.

## PORTFOLIO ENGINE

Each day the engine marks existing lots at adjusted open, records opening NAV, executes legal
exits and costs, makes exit cash available, caps new gross notional at 5% of opening NAV and
available cash, proportionally scales for buy costs, allocates all executable signals, then
marks all open lots at adjusted close. Close NAV always equals cash plus market value.

The registered CY-006 open block controls are used for entry and exit. Twenty-one exits were
delayed by an open sell block; the median delay over all trades was zero and maximum delay six
sessions. The only event extending past the predecessor's +25 outcome window was carried to
its next legal open rather than silently dropped. No order-book, impact, or auction fill model
is fabricated.

## COHORT / SIGNAL FLOW

- Frozen valid events: 22,357 across 4,835 securities.
- Signal dates: 1,228, from 2020-01-02 through 2026-07-08.
- Entry/portfolio dates: 2020-01-03 through the final legal exit on 2026-08-06.
- Actual entries and exits: 22,357 in every portfolio.
- Invalid entry prices: zero; overlapping same-security skips: zero; zero-cash misses: zero.
- Base-cost cash constraint: 38 entry days for Equal and 36 for Risk-Aware; the 5% tranche
  bound, rather than cash, binds on the other 1,190 and 1,192 signal dates.

Daily signal counts:

| Signals at entry open | Trading days | Entered events | Mean Equal position / opening NAV |
|---:|---:|---:|---:|
| 0 | 369 | 0 | — |
| 1 | 197 | 197 | 4.992% |
| 2-5 | 435 | 1,365 | 1.591% |
| 6-20 | 385 | 4,153 | 0.463% |
| >20 | 211 | 16,642 | 0.063% |

The maximum is 674 signals on 2024-02-06. Cluster dilution is therefore economically large,
not a corner case.

## EQUAL SIZE PORTFOLIO

| Metric | Gross | Net base-cost |
|---|---:|---:|
| Ending NAV / cumulative return | 1.0016 / +0.16% | 0.8653 / -13.47% |
| CAGR | +0.03% | -2.26% |
| Annualized volatility | 23.32% | 23.34% |
| Maximum drawdown | -44.35% | -49.32% |
| Sharpe-like / Calmar | 0.118 / 0.001 | 0.019 / -0.046 |
| Average exposure / cash | 76.74% / 23.26% | 76.80% / 23.20% |
| Average / maximum positions | 280.1 / 3,354 | 280.1 / 3,354 |
| Annualized two-sided turnover | 19.34x | 19.36x |

The frozen Alpha does not survive. Even before costs, 6.34 years of capital competition
produce only +0.16% cumulative return with a -44.35% drawdown.

## RISK-AWARE PORTFOLIO

| Metric | Gross | Net base-cost |
|---|---:|---:|
| Ending NAV / cumulative return | 0.9944 / -0.56% | 0.8591 / -14.09% |
| CAGR | -0.09% | -2.37% |
| Annualized volatility | 23.35% | 23.36% |
| Maximum drawdown | -44.39% | -49.36% |
| Sharpe-like / Calmar | 0.114 / -0.002 | 0.015 / -0.048 |
| Average exposure / cash | 76.74% / 23.26% | 76.80% / 23.20% |
| Average / maximum positions | 280.1 / 3,354 | 280.1 / 3,354 |
| Annualized two-sided turnover | 19.35x | 19.37x |

## PRIMARY COMPARISON

The central NET comparison is:

| Metric | Equal Size | Risk-Aware | Risk minus Equal |
|---|---:|---:|---:|
| Ending NAV | 0.8653 | 0.8591 | -0.0062 |
| Cumulative return | -13.47% | -14.09% | -0.62 pp |
| CAGR | -2.26% | -2.37% | -0.11 pp |
| Volatility | 23.34% | 23.36% | +0.03 pp |
| Maximum drawdown | -49.32% | -49.36% | -0.04 pp |
| Sharpe-like | 0.019 | 0.015 | -0.005 |
| Average exposure | 76.80% | 76.80% | effectively 0 |
| Average positions | 280.1 | 280.1 | 0 |
| Total proportional cost | 0.1300 | 0.1299 | effectively 0 |

Answer 1: deep-oversold event Alpha does **not** survive the frozen finite-capital portfolio.
Answer 2: frozen risk-aware sizing does **not** add portfolio value; it slightly worsens every
primary return/risk-efficiency measure at the same exposure and participation.

## CAPITAL COMPETITION

The executable event-equal mean gross return remains +4.32%, but the mean of each entry
date's cross-sectional return is only +0.26%. Weighting by actual Equal gross entry capital
reduces the mean gross trade return to +0.0028%. The gap is the decisive bridge from event
study to portfolio:

- 74.44% of events occur on the 211 days with more than 20 signals;
- each date receives at most one 5% tranche regardless of whether it has 1 or 674 signals;
- cluster events that dominate event arithmetic receive tiny per-name capital;
- sparse dates can give one stock nearly the whole 5% tranche; and
- actual total gross entry notional turns over 58.40 normalized NAV units, yet earns only
  0.0016 gross NAV profit.

No event is lost to overlap or zero cash, and only 34 gross entry dates are cash constrained.
The failure is not missed participation. It is that independent-event weighting implicitly
allocated much more aggregate capital to high-count episodes than the fixed daily risk budget.

The five largest clusters contain 544-674 signals, concentrated in 2022-04-26, February 2024,
and 2025-04-08. Their actual day tranche was only 2.8%-3.7% of NAV when cash constrained,
leaving individual weights around 0.007%-0.009% of NAV.

## TRANSACTION COSTS

| Policy | Gross ending NAV | Net ending NAV | Base-cost NAV drag | Net CAGR | Stress ending NAV | Stress CAGR |
|---|---:|---:|---:|---:|---:|---:|
| Equal | 1.0016 | 0.8653 | -0.1363 | -2.26% | 0.7843 | -3.76% |
| Risk-Aware | 0.9944 | 0.8591 | -0.1354 | -2.37% | 0.7788 | -3.87% |

Equal pays 0.1300 normalized NAV in base proportional costs. That is about 80 times its tiny
gross portfolio profit; the stress increases total loss to -21.57%. Costs materially threaten
the strategy, but they are not the first cause: zero-cost Equal is already economically flat.
The proportional model omits the RMB 5 minimum because NAV is normalized and does not claim
broker-specific precision.

## YEARLY RESULTS

| Year | Equal NET | Risk-Aware NET | Risk minus Equal |
|---:|---:|---:|---:|
| 2020 | -3.40% | -3.25% | +0.14 pp |
| 2021 | +8.65% | +8.99% | +0.35 pp |
| 2022 | -21.54% | -21.59% | -0.05 pp |
| 2023 | +5.65% | +5.22% | -0.43 pp |
| 2024 | -11.18% | -11.46% | -0.27 pp |
| 2025 | +21.20% | +20.51% | -0.69 pp |
| 2026 through 08-06 | -7.61% | -7.46% | +0.15 pp |

Equal is positive in only three of seven supported calendar years. Risk-Aware wins three and
loses four, with no stable incremental advantage.

## TIME BLOCKS

| Period | Policy | Cumulative | CAGR | Max DD | Sharpe-like | Exposure | Cost |
|---|---|---:|---:|---:|---:|---:|---:|
| 2018-2020 (observed 2020) | Equal | -3.40% | -3.53% | -16.62% | -0.098 | 66.52% | 0.0206 |
| 2018-2020 (observed 2020) | Risk | -3.25% | -3.38% | -16.34% | -0.091 | 66.52% | 0.0206 |
| 2021-2023 | Equal | -9.94% | -3.56% | -34.62% | -0.057 | 85.93% | 0.0703 |
| 2021-2023 | Risk | -10.08% | -3.62% | -34.56% | -0.059 | 85.93% | 0.0705 |
| 2024-2026 | Equal | -0.54% | -0.22% | -33.94% | 0.125 | 70.18% | 0.0390 |
| 2024-2026 | Risk | -1.25% | -0.50% | -34.07% | 0.114 | 70.18% | 0.0388 |

Every Equal block loses money net. Portfolio failure is not confined to one isolated regime.

## DRAWDOWN EPISODES

The dominant Equal NET episode peaks on 2020-07-14, troughs on 2024-02-05 at -49.32%, and
does not recover by 2026-08-06. Risk-Aware reaches -49.36% over the same interval. Smaller
2020 episodes are -9.37% (recovered 2020-02-21) and -6.78% (recovered 2020-06-01); Risk-Aware
is unchanged or slightly worse. Sizing does not control the portfolio's main drawdown.

## EXPOSURE / CASH

Average Equal NET exposure is 76.80%, with 23.20% cash, but exposure varies sharply with the
event stream. The strategy is an episodic, crisis-heavy contrarian sleeve rather than a
continuously invested portfolio. Mean concurrent positions are 280, but the maximum is 3,354
because hundreds of signals can arrive together. Idle cash contributes to low capital use in
quiet periods; crash-day tranche dilution prevents the event count from lifting exposure
without bound.

## RISK-AWARE CAPITAL ATTRIBUTION

| Causal Q | Events | Risk allocation | Mean gross trade return | Mean net trade return | Net P&L | Severe-capital share | No-trigger-capital share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| Q1 | 4,849 | 14.94% | 6.23% | 5.98% | +0.0215 | 13.45% | 13.16% |
| Q2 | 4,422 | 15.39% | 5.24% | 5.00% | +0.0580 | 13.38% | 12.79% |
| Q3 | 4,704 | 19.85% | 4.58% | 4.33% | -0.0122 | 19.30% | 21.23% |
| Q4 | 4,082 | 19.04% | 3.07% | 2.83% | -0.0895 | 20.01% | 17.72% |
| Q5 | 4,300 | 30.79% | 2.12% | 1.88% | -0.1188 | 33.86% | 35.11% |

Across all actual entry notional, Risk-Aware reduces future severe-event capital from 42.48%
to 42.29%, no-trigger capital from 21.56% to 21.41%, and V4-path capital MAE from -10.03% to
-10.01%. It also shifts 3.78 allocation points away from Q5 and 2.37 points toward Q1.
Those small risk improvements do not overcome timing and compounding: net ending NAV is 0.62
points worse than Equal. Q5 still has the largest capital share because it occurs on relatively
sparse/high-budget dates; within-date sizing cannot neutralize the opportunity-time mix.

## CONCENTRATION

| Metric | Equal NET | Risk-Aware NET |
|---|---:|---:|
| Average largest-position weight | 4.68% | 4.71% |
| Maximum largest-position weight | 7.95% | 7.95% |
| Average top-5 concentration | 17.44% | 17.67% |
| Maximum top-5 concentration | 28.38% | 28.38% |

There are no concentration caps in V5. Risk-Aware slightly increases average top-5
concentration without improving drawdown.

## REALIZED HOLDING RETURNS

For both base-cost portfolios, the underlying executed lots have 4.08% mean and 2.40% median
net return, 57.40% positive rate, -12.98% Q10, +23.14% Q90, and average proportional cost
0.240% of entry notional. Equal and Risk-Aware trade-return distributions are identical
because size changes dollars, not each stock path. Their very positive event statistics can
coexist with poor NAV because event counts, dates, and deployed notionals receive radically
different weights.

## V4 BRIDGE

All 22,357 Equal events execute. V4 event Ret20 averages +4.366%; V5's open-executable gross
outcome averages +4.319%. The mean translation cost is only -0.047 points, median difference
is effectively zero, mean absolute difference is 0.829 points, and correlation is 0.9943.
Thus V5 faithfully preserves predecessor stock-path Alpha. Portfolio collapse comes after
that bridge, through capital competition and costs—not from a hidden endpoint substitution.

## LIMITATIONS

- CY-006 is certified PIT-B research data, not strict archival PIT-A.
- Entry and exit use reliable daily open block controls, not auction queues or order-book
  fill probability.
- Slippage and fees are proportional approximations; no market impact or account-size
  capacity model is claimed.
- Normalized fractional adjusted units avoid meaningless lot rounding at NAV 1.0.
- No single reliable tradable benchmark was essentially free under the frozen execution
  contract, so V5 does not add an ad hoc benchmark.
- The fixed 5% daily tranche deliberately denies extra aggregate risk to 674-signal crash
  days. That is the experiment's capital contract, not proof that every alternative risk
  budget fails.

## ECONOMIC INTERPRETATION

Deep-oversold mean reversion is real as an event-weighted phenomenon but is not investable
under this frozen finite-capital realization. Its apparent abundance is highly clustered:
independent event arithmetic implicitly gives crash episodes hundreds of units of capital,
whereas a no-leverage portfolio grants each date one bounded tranche. Once dates and actual
capital replace events as the unit of account, gross return is effectively zero and normal
proportional trading costs dominate.

The V3/V4 risk score still orders executed stock outcomes and causally shifts money away from
the riskiest bucket. The magnitude is too small, and within-date allocation cannot correct
the much larger between-date cluster weighting. Continued portfolio complexity is therefore
not justified under the V5 capital contract.

## VERDICT

`EVENT_ALPHA_COLLAPSES`

Equal Size produces only +0.16% gross cumulative return and -13.47% net, with -49.32% maximum
drawdown. Risk-Aware is slightly worse at -14.09% net and supplies no consistent efficiency
gain. The result is fully reconciled with V1-V4: executable event returns survive, but their
event-weighted Alpha does not survive daily capital competition, and costs finish the collapse.

## SINGLE NEXT STEP

Run one outcome-blind **clustered-signal capital-allocation study** that preserves the frozen
carrier and score, and tests whether a preregistered event-count-aware risk budget can overcome
the entry-date dilution identified by V5 before transaction costs. Do not start new factor,
score, or threshold research.
