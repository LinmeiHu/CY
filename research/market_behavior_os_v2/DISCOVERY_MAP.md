# Lean discovery map

Updated 2026-08-31. This is the compact exploration-funnel view. Detailed
lineage remains in the experiment registry, frozen specs, result artifacts, and
engine ledgers.

## Ranked candidate pool

| Rank | Family | Economic role and current effect | Funnel status | Cheapest useful next decision |
|---:|---|---|---|---|
| 1 | Stock-level RS acceleration overextension | Excluding new candidates with PIT `r20-r120 >= 0.20` improves return by 1.95/6.79 pp, drawdown by 2.05/6.15 pp, and Sharpe by 0.127/0.337 across the two consumed blocks | `PROMISING_ADMISSION_COMPONENT`; fixed and unchanged, but not independently confirmed | Separately quarantined confirmation only; no threshold, lookback, or combination search |
| 2 | Turnover / cross-industry dispersion | Opportunity-width habitat. Turnover-to-width PIT rho 0.5016 and fixed-control partial rho 0.2128; dispersion h3 partial rho 0.2228 and high-low width gap 2.80 percentage points | `ROBUSTNESS`, ranking translation `PARKED_RESOURCE` | Use only a materially different bounded implementation/resource contract; do not rescue either failed builder or infer PnL from width |
| 3 | Liquidity activity / continuation | h5 continuation partial rho 0.1466, 8/8 cells, positive in both blocks; CHINEXT trade screen had higher mean but materially worse severe-loss incidence in the high state | `PROMISING_MARKET_BEHAVIOR`, `PARKED_CHINEXT_TRANSLATION` | Revisit only for an independently motivated exposure or liquidity-capacity decision |
| 4 | Five-day minute-volatility progression | High state reduces drawdown and improves Sharpe as a 5%-versus-10% risk budget, but its matched-cost development return benefit is only +0.27 pp at 20 bps/side and -2.41 pp at 30 bps/side | `DOWNGRADED_COST_SENSITIVE_RISK_OVERLAY`; not a current strategy candidate | Preserve the mechanism as risk-control evidence; do not optimize threshold/exposure or repeat cost stress |
| 5 | Downside-extreme participation / reversal | Market h5 reversal partial rho 0.0823. Fixed low-state CHINEXT admission veto improved the later block but reduced 2018-2021 return by 11.30 percentage points | `PARKED_REGIME_DEPENDENT_CHINEXT_TRANSLATION`; market family remains `PROMISING` | Test only as habitat for an independently discovered reversal strategy, not another V1 threshold |
| 6 | Leadership concentration / fragility | h3 downside partial rho -0.1321 in the market screen; the CHINEXT trade screen had the opposite favorable return ordering | `PROMISING_MARKET_BEHAVIOR`, `REJECTED_AS_CHINEXT_VETO` | Test a portfolio-concentration/capacity role rather than a generic admission veto |
| 7 | New-high/new-low breadth / exhaustion | h5 partial rho -0.1315 after fixed controls; CHINEXT high-state veto reversed across coarse blocks | `PROMISING_MARKET_BEHAVIOR`, `REJECTED_AS_CHINEXT_VETO` | Leave parked until a distinct exhaustion/mean-reversion archetype exists |

There is now one fixed executable **promising admission component**, not a
validated strategy: the RS-acceleration overextension veto. The minute-volatility
half-gross overlay is downgraded after its predeclared matched-cost stress. Both
use repeatedly consumed 2018--2023 history. The external post-2023 boundary is
contaminated by an inventory incident, so neither mechanism may be confirmed on
that material.

## Fast-screen casualties

| Candidate | Decision |
|---|---|
| VWAP defense/recovery state | Rejected for the CHINEXT trade translation: the accepted coordinate had effectively no low tail and only two high-state completed cycles |
| Joint stress state | Parked: only 62 supported completed cycles, all in the later coarse block |
| Realized-volatility level | Rejected: favorable early high-state result reversed in the later block, whose high state had only two cycles |
| Small-versus-large participation | Rejected: high-state ordering reversed across coarse blocks |
| Day-3/Day-5 CHINEXT path | Remains rejected as a simple executable translation; do not reopen without a new strategy need |
| Formation depth | Parked after extensive research and no CHINEXT V1 habitat transfer |
| Breakout-volume confirmation | Rejected: pass did not outperform fail in either useful sense |
| RS score floor | Parked promising: high score outperformed low in both blocks, but the low-tail episode ordering reversed materially |
| Box width and direction efficiency | Rejected/mixed across coarse blocks |
| Minimum-volume location and ratio | Rejected as mixed or weak |
| Exit reason / realized holding duration | Descriptive attribution only; no PIT exit predictor or rule was promoted |
| Current-candidate multivariate ranking | Four equal-weight bundles, fixed ridge, and a depth-2 tree all failed the two-block replay gate. Ridge cut 2022--2023 Top-1 severe losses from 25.6% to 12.8% but worsened the development severe-loss rate from 16.7% to 20.8% |
| Coarse individual-exit variants | MA20x2, MA30x1, MA20x1, and MA40x1 were screened on 53/28 exact two-leg cycles. None improved mean return by the fixed amount in both blocks; no exit replay was run |

## Executable translations

| Experiment | Fixed decision | 2018-2021 return delta | 2022-2023 return delta | Promotion result |
|---|---|---:|---:|---|
| `HAB-CHX-DOWNREV-STRAT-001` | At t close, block new admissions when downside-extreme participation PIT <= 0.20 | -11.30 pp | +10.23 pp | Failed return improvement in both blocks; `PARKED_REGIME_DEPENDENT` |
| `HAB-CHX-MINVOLPATH-STRAT-001` | At t 15:30, block next-open admissions when five-day minute-volatility progression PIT >= 0.80 | +18.05 pp | +0.87 pp | Failed severe-loss reduction in both blocks; `PARKED_NEAR_MISS` |
| `HAB-CHX-DECISION-BATCH-001 / RS_ACCEL_OVEREXTENSION_VETO` | At t close, exclude a new candidate when PIT `r20-r120 >= 0.20` | +1.95 pp | +6.79 pp | Passed every fixed gate; `DEVELOPMENT_STRATEGY_CANDIDATE` |
| `HAB-CHX-DECISION-BATCH-001 / MINVOL_HIGH_HALF_GROSS` | At t 15:30, target 5% per selected holding when minute-volatility progression PIT >= 0.80, otherwise 10% | +1.76 pp | +6.19 pp | Passed every fixed gate; `DEVELOPMENT_RISK_CANDIDATE` |
| `HAB-CHX-RANK-MODEL-001` | Same-date Top-1 allocation using four fixed bundles, ridge alpha 10, or a depth-2 tree | no candidate passed | no candidate passed | `NO_RANKING_MODEL_CLEARED_PREDECLARED_REPLAY_GATE`; no portfolio replay |
| `HAB-CHX-EXIT-SCREEN-001` | Earlier individual exits from four fixed MA/confirmation rules | screen only | screen only | `EXIT_REMAINS_UNRESOLVED`; no portfolio replay |
| `HAB-CHX-MINVOL-COST-001` | Re-run baseline and half-gross overlay at matched 20/30 bps per side | +0.27/-2.41 pp | +5.71/+4.81 pp | `DOWNGRADED_COST_SENSITIVE_RISK_OVERLAY` because development benefit is immaterial then negative |

All executable translations and matched-cost controls preserve next-session-open execution, T+1
sellability, trading status, price limits, corporate actions, and costs. The new
selection arm preserves ranking among admitted candidates and all existing
positions/exits; the exposure arm preserves exact completed-cycle identity and
changes target weights only. Both periods are consumed discovery history, not
untouched OOS. No post-2023 row or CY-011 input entered the experiments.

## Resource frontier

`MKT-DISP-RANK-001` was retried under its unchanged frozen contract after RAM
recovered. It stopped at the 12-GiB temporary-spill ceiling before an output was
accepted. Exact year-batched `MKT-DISP-RANK-002` then stopped at the unchanged
1.5-GiB process peak-RSS ceiling. Both panels/results are absent. Two bounded
implementations have now failed different resource guards, so this translation
is `PARKED_RESOURCE`; there is no third rescue in this discovery batch.

The earlier 7.21/7.32-GiB messages refer to `psutil.virtual_memory().available`
(system-available RAM), not filesystem free space. Repository, output, and
temporary paths are on `/dev/disk3s5` at `/System/Volumes/Data`, with about
347 GiB free at reconciliation.

## State and mechanism boundaries

- Trend direction has neighboring-horizon representation stability only. No
  trend representation is an established signal or habitat predictor. Broader
  trend quality, age, and transition families remain open; strength/alignment
  remain data-contract-limited.
- Breadth discovery and leadership concentration are stable, distinct state
  coordinates. Economic screens are exploratory and do not establish a
  Trend x Breadth rule.
- Dispersion predicts two-sided opportunity-set widening: controlled p90 rises,
  p10 falls, and the controlled market mean is flat. Capturable ranking, costs,
  capacity, and portfolio payoff are unresolved.

What market behavior are we still not studying? Independent stability of the
stock-level overextension effect; security/industry-relative direction inside
widening dispersion; signal-time stock-level intraday supply, demand, support,
and acceptance mechanisms beyond daily engine summaries; full rebalanced-position
exit paths; true order flow; and stable broader trend quality/age/transition.

Has any discovered mechanism implied a genuinely new strategy archetype? No new
archetype emerged in this cycle. Dispersion/relative value remains the only
genuinely new, resource-parked archetype. RS acceleration remains a selection
mechanism inside the existing breakout seed; minute-volatility progression is
useful risk-state evidence but its fixed sizing translation is cost-sensitive.
Neither is independently validated or authorized for live use.

## Independent A-share family batch

ASHARE-INDEP-FUNNEL-001 screened seven frozen standalone families on one
shared PIT panel. All years are consumed development history.

| Rank | Exact family | Natural response | Full net excess vs date control | Chronology | Current decision |
|---:|---|---:|---:|---|---|
| 1 | PIT industry rotation | h20 | +1.003% | +1.396% / +0.661%; 4/6 years positive | `NEAR_MISS_RISK_GATE`; severe disadvantage +2.497 pp vs +2.000 pp maximum |
| 2 | Failed-breakdown recovery | h5 | +0.004% | -0.025% / +0.023% | `NULL_STANDALONE_SCREEN` |
| 3 | Short reversal | h5 | -0.275% | negative in both blocks | `REJECT_EXACT_FORMULATION` |
| 4 | Compression breakout | h20 | -0.048% | -0.506% / +0.276% | `PARK_MIXED_CHRONOLOGY` |
| 5 | Positive demand-volume shock | h5 | -0.840% | negative in both blocks | `REJECT_EXACT_FORMULATION` |
| 6 | Medium momentum | h20 | -2.259% | negative in both blocks | `REJECT_EXACT_FORMULATION` |
| 7 | Objective breakout continuation | h20 | -2.710% | negative in both blocks | `REJECT_EXACT_FORMULATION` |

No family passes every promotion gate, so there is no executable replay. The
next frontier is risk-first industry diversification under a separately frozen
translation, not threshold/horizon/habitat rescue.

## Industry translation plus independent batch 002

| Family | Cheap-screen result | Executable decision |
|---|---|---|
| Fixed 3x5 industry rotation | -0.335% full; -1.039% late; +8.365 pp severe disadvantage | `PARKED`; replay also contract-blocked |
| Industry diffusion h20 | +1.254% full; +1.035%/+1.444% blocks; 4 positive years | `PROMISING_SCREEN_MECHANISM`; replay blocked |
| Low idiosyncratic volatility h20 | +0.794% full; +0.389%/+1.144% blocks; 5 positive years | `PROMISING_SCREEN_MECHANISM`; replay blocked |
| Stock-industry residual strength | -3.598% full and worse severe loss | Reject exact formulation |
| Negative-gap recovery | -0.812% full h5, both blocks negative | Reject exact formulation |
| Limit-up aftermath | -0.881% full h5, both blocks negative | Reject exact formulation |
| Price-volume disagreement | -0.084% full, early negative, severe gate fails | Park null/mixed formulation |
| Lower-wick demand rejection | -0.321% full h5, both blocks negative | Reject exact formulation |

Industry diffusion and low idiosyncratic volatility are distinct roles:
within-industry participation and stock-specific defensive risk. Their cheap
effects survive chronology; executability is unresolved rather than failed.

## Corporate-action-repaired frozen replays

| Family | Full portfolio economics | Final status |
|---|---|---|
| Industry diffusion h20 | +54.64% total; -29.10% DD; 0.440 Sharpe; 18.46% severe; 165.52x turnover | `PROMISING_BUT_MIXED`; return survives, risk gates fail |
| Low idiosyncratic volatility h20 | +15.73% total; -29.11% DD; 0.239 Sharpe; 6.09% severe; 142.22x turnover | `PROMISING_BUT_MIXED`; defensive role survives, Sharpe gate fails |

The execution blocker is resolved for these paths. Neither mixed result permits
parameter rescue or a strategy-candidate claim.

## Stock-level intraday plus independent batch 004

| Family | Frozen cheap-screen result | Final decision |
|---|---|---|
| Quiet VWAP acceptance | +0.0886% h5 full; +0.1067%/+0.0729% blocks; severe advantage 0.288 pp | Screen survivor; portfolio `BLOCKED_DATA_CONTRACT` on prolonged suspension |
| VWAP acceptance | -0.2175% h5; both blocks negative; severe disadvantage +5.114 pp | Reject exact formulation |
| Closing acceptance | -0.4178% h5; both blocks negative | Reject exact formulation |
| Opening-weakness recovery | -0.2869% h5; both blocks negative | Reject exact formulation |
| Late-volume-confirmed demand | -0.4629% h5; both blocks negative | Reject exact formulation |
| Intraday-volatility contraction | -0.2821% h5; both blocks negative | Reject exact formulation; does not reopen overlay |
| Relative intraday strength | -0.2774% h5; both blocks negative | Reject exact formulation |
| Industry Diffusion Acceleration | +0.9662% h20; +0.7287%/+1.1705% blocks; severe advantage 3.483 pp | `PROMISING_BUT_MIXED`; replay +13.10%, -32.66% DD, 0.217 Sharpe, 16.20% severe |
| Industry Leadership Acceleration | +0.5363% h20; +0.6126%/+0.4709% blocks; severe disadvantage 1.525 pp | `COMPLEMENTARY_INFORMATION`; no replay |
| Residual mean reversion h5 | +0.0402%; -0.2059%/+0.2531% blocks; downside fails | `CONDITIONAL_INFORMATION`; no replay |
| Liquidity recovery | -0.1119% h5; both blocks negative | Reject exact formulation |
| Down-market resilience | -0.8385% h5; both blocks negative; severe disadvantage +14.329 pp | Reject exact formulation |

The six negative Track-A results apply only to their frozen CY008 summary
representations after fixed daily controls; they do not reject broader support,
absorption, or acceptance research families. No raw minute sequence or exact
minute-window search was run.

## External-prior and internal cycle 005

| Track | Frozen family | Full net excess | Chronology | Decision |
|---|---|---:|---|---|
| External | JT 12-1 momentum | -5.183% h120 | -0.588% / -8.919% | `ADVERSE_LONG_LEG_FORMULATION` |
| External | 52-week high | -4.597% h120 | +0.381% / -8.661% | `CHRONOLOGICALLY_MIXED` |
| External | Industry momentum | +0.250% h120 | +0.919% / -0.303% | `CHRONOLOGICALLY_MIXED`; severe +26.161 pp |
| External | Negative prior-month MAX | -1.185% h20 | -2.229% / -0.474% | `ADVERSE_LONG_LEG_FORMULATION` |
| External | Five-day intraday reversal | -0.070% h5 | -0.192% / +0.011% | `CHRONOLOGICALLY_MIXED` |
| Internal | Chip cost concentration | -1.023% h20 | -1.734% / -0.546% | `ADVERSE_EXACT_FORMULATION` |
| Internal | Chip overhang clearance | -1.955% h20 | -2.336% / -1.691% | `ADVERSE_EXACT_FORMULATION` |
| Internal | Chip support density | -0.729% h20 | -1.455% / -0.239% | `ADVERSE_EXACT_FORMULATION` |
| Combination | MAX + low idio | -0.822% h20 | -2.181% / +0.108% | `COMPLEXITY_NOT_EARNED` |
| Combination | Diffusion acceleration + low idio | +0.341% h20 | -0.226% / +0.717% | `COMPLEXITY_NOT_EARNED`; worse than baseline |

All exact screen families have broad coverage and at least 90% next-open
executability, but none passes every economic/risk/chronology gate. Therefore no
full replay is run and gross/net portfolio performance, turnover, and capacity
are not inferred. Amihud, BAB, pairs, residual momentum, and price-limit delayed
discovery retain their explicit deferred/conflict/unavailable/already-adverse
statuses rather than being silently adapted.

What market behavior are we still not studying? Registered PIT fundamentals,
borrow-feasible short legs and relative-value execution, true order-book flow,
and independent post-development confirmation.

Has any discovered mechanism implied a genuinely new strategy archetype? No.

## PIT fundamental readiness and fallback cycle 006

Fundamental alpha remains unopened rather than rejected. The only local broad
statement candidate is a current-provider snapshot without historical revisions;
registered `QD-011` explicitly blocks alpha. Canonical value, profitability,
investment, quality, accrual, growth, and quality-value families therefore have
status `PIT_FUNDAMENTAL_DATA_BLOCKED_NOT_TESTED`.

| Frozen fallback family | Gross / net h20 excess | Early / late | Severe disadvantage | Ordering | Decision |
|---|---:|---:|---:|---|---|
| Left-tail stability 60 | -0.429% / -0.426% | -1.435% / +0.263% | -15.974 pp | Top 0.232%, middle 1.671%, bottom -0.522% | `CHRONOLOGICALLY_MIXED`; defensive diagnostic only |
| Overnight information stability 60 | +0.084% / +0.083% | +0.202% / +0.002% | +0.366 pp | Top 0.754%, middle 1.319%, bottom 0.912% | `ECONOMICALLY_NULL`; no monotonic ordering |
| Trading continuity 60 | -0.040% / -0.040% | +0.555% / -0.450% | -2.422 pp | Top 0.642%, middle 1.298%, bottom 0.291% | `CHRONOLOGICALLY_MIXED` |

No family reaches replay, no combination is legal, and no portfolio economics
are inferred.

What market behavior are we still not studying? Archival PIT fundamentals,
borrow-feasible relative value, order-book flow, and independent post-development
confirmation.

Has any discovered mechanism implied a genuinely new strategy archetype? No.
