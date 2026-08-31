# Lean discovery map

Updated 2026-08-31. This is the compact exploration-funnel view. Detailed
lineage remains in the experiment registry, frozen specs, result artifacts, and
engine ledgers.

## Ranked candidate pool

| Rank | Family | Economic role and current effect | Funnel status | Cheapest useful next decision |
|---:|---|---|---|---|
| 1 | Stock-level RS acceleration overextension | Excluding new candidates with PIT `r20-r120 >= 0.20` improves return by 1.95/6.79 pp, drawdown by 2.05/6.15 pp, and Sharpe by 0.127/0.337 across the two consumed blocks | `DEVELOPMENT_STRATEGY_CANDIDATE`; all fixed replay gates pass | Independent, separately quarantined confirmation; no threshold neighbor or combination search |
| 2 | Five-day minute-volatility progression | High state is useful as a risk budget rather than an admission veto. Fixed 15:30 5%-versus-10% target weights improve return by 1.76/6.19 pp and drawdown by 5.30/5.74 pp while retaining all cycles | `DEVELOPMENT_RISK_CANDIDATE`; all fixed replay gates pass | Independent confirmation plus turnover/cost stress; keep the earlier admission veto parked |
| 3 | Turnover / cross-industry dispersion | Opportunity-width habitat. Turnover-to-width PIT rho 0.5016 and fixed-control partial rho 0.2128; dispersion h3 partial rho 0.2228 and high-low width gap 2.80 percentage points | `ROBUSTNESS`, ranking translation `PARKED_RESOURCE` | Run the already-frozen PIT industry-rank test only under a materially different bounded implementation/resource envelope; do not infer PnL from width |
| 4 | Downside-extreme participation / reversal | Market h5 reversal partial rho 0.0823. Fixed low-state CHINEXT admission veto improved the later block but reduced 2018-2021 return by 11.30 percentage points | `PARKED_REGIME_DEPENDENT_CHINEXT_TRANSLATION`; market family remains `PROMISING` | Test only as habitat for an independently discovered reversal strategy, not another V1 threshold |
| 5 | Liquidity activity / continuation | h5 continuation partial rho 0.1466, 8/8 cells, positive in both blocks; CHINEXT trade screen had higher mean but materially worse severe-loss incidence in the high state | `PROMISING_MARKET_BEHAVIOR`, `PARKED_CHINEXT_TRANSLATION` | Revisit only for an independently motivated exposure or liquidity-capacity decision |
| 6 | Leadership concentration / fragility | h3 downside partial rho -0.1321 in the market screen; the CHINEXT trade screen had the opposite favorable return ordering | `PROMISING_MARKET_BEHAVIOR`, `REJECTED_AS_CHINEXT_VETO` | Test a portfolio-concentration/capacity role rather than a generic admission veto |
| 7 | New-high/new-low breadth / exhaustion | h5 partial rho -0.1315 after fixed controls; CHINEXT high-state veto reversed across coarse blocks | `PROMISING_MARKET_BEHAVIOR`, `REJECTED_AS_CHINEXT_VETO` | Leave parked until a distinct exhaustion/mean-reversion archetype exists |

There are now two simple executable **development candidates**, not validated
strategies. Both passed their fixed economic replay gates on repeatedly consumed
2018--2023 history. The external post-2023 boundary is contaminated by an
inventory incident, so neither candidate may be called confirmed or tested on
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

## Executable translations

| Experiment | Fixed decision | 2018-2021 return delta | 2022-2023 return delta | Promotion result |
|---|---|---:|---:|---|
| `HAB-CHX-DOWNREV-STRAT-001` | At t close, block new admissions when downside-extreme participation PIT <= 0.20 | -11.30 pp | +10.23 pp | Failed return improvement in both blocks; `PARKED_REGIME_DEPENDENT` |
| `HAB-CHX-MINVOLPATH-STRAT-001` | At t 15:30, block next-open admissions when five-day minute-volatility progression PIT >= 0.80 | +18.05 pp | +0.87 pp | Failed severe-loss reduction in both blocks; `PARKED_NEAR_MISS` |
| `HAB-CHX-DECISION-BATCH-001 / RS_ACCEL_OVEREXTENSION_VETO` | At t close, exclude a new candidate when PIT `r20-r120 >= 0.20` | +1.95 pp | +6.79 pp | Passed every fixed gate; `DEVELOPMENT_STRATEGY_CANDIDATE` |
| `HAB-CHX-DECISION-BATCH-001 / MINVOL_HIGH_HALF_GROSS` | At t 15:30, target 5% per selected holding when minute-volatility progression PIT >= 0.80, otherwise 10% | +1.76 pp | +6.19 pp | Passed every fixed gate; `DEVELOPMENT_RISK_CANDIDATE` |

All four translations preserve existing next-session-open execution, T+1
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
stock-level overextension effect, interactions between rank acceleration and
market participation, executable exit/holding-period mismatch, security- and
industry-level rank direction inside widening dispersion, true order flow, and
stable representations of broader trend quality/age/transition.

Has any discovered mechanism implied a genuinely new strategy archetype? The
dispersion/relative-value family remains genuinely new but resource-parked. The
RS-acceleration result is a new stock-selection mechanism inside the existing
breakout seed, while minute-volatility progression now supports a defensive
exposure overlay. Neither is independently validated or authorized for live use.
