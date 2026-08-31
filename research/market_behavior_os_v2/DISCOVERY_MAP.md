# Lean discovery map

Updated 2026-08-31. This is the compact exploration-funnel view. Detailed
lineage remains in the experiment registry, frozen specs, result artifacts, and
engine ledgers.

## Ranked candidate pool

| Rank | Family | Economic role and current effect | Funnel status | Cheapest useful next decision |
|---:|---|---|---|---|
| 1 | Turnover / cross-industry dispersion | Opportunity-width habitat. Turnover-to-width PIT rho 0.5016 and fixed-control partial rho 0.2128; dispersion h3 partial rho 0.2228 and high-low width gap 2.80 percentage points | `ROBUSTNESS`, ranking translation `PARKED_RESOURCE` | Run the already-frozen PIT industry-rank test only under a materially different bounded implementation/resource envelope; do not infer PnL from width |
| 2 | Five-day minute-volatility progression | High state was adverse in both coarse CHINEXT trade blocks. Fixed 15:30 veto improved return and drawdown in both engine blocks, but later severe-loss incidence rose 6.38% to 6.74% and concentration worsened | `PARKED_NEAR_MISS`, not a strategy candidate | No threshold rescue; revisit only for a genuinely different strategy decision or independent data |
| 3 | Downside-extreme participation / reversal | Market h5 reversal partial rho 0.0823. Fixed low-state CHINEXT admission veto improved the later block but reduced 2018-2021 return by 11.30 percentage points | `PARKED_REGIME_DEPENDENT_CHINEXT_TRANSLATION`; market family remains `PROMISING` | Test only as habitat for an independently discovered reversal strategy, not another V1 threshold |
| 4 | Liquidity activity / continuation | h5 continuation partial rho 0.1466, 8/8 cells, positive in both blocks; CHINEXT trade screen had higher mean but materially worse severe-loss incidence in the high state | `PROMISING_MARKET_BEHAVIOR`, `PARKED_CHINEXT_TRANSLATION` | A broad risk-on exposure translation, if an engine supports it without threshold search |
| 5 | Leadership concentration / fragility | h3 downside partial rho -0.1321 in the market screen; the CHINEXT trade screen had the opposite favorable return ordering | `PROMISING_MARKET_BEHAVIOR`, `REJECTED_AS_CHINEXT_VETO` | Test a portfolio-concentration/capacity role rather than a generic admission veto |
| 6 | New-high/new-low breadth / exhaustion | h5 partial rho -0.1315 after fixed controls; CHINEXT high-state veto reversed across coarse blocks | `PROMISING_MARKET_BEHAVIOR`, `REJECTED_AS_CHINEXT_VETO` | Leave parked until a distinct exhaustion/mean-reversion archetype exists |
| 7 | Co-movement / opportunity compression | Raw effect was large (-0.3576) but failed the chronological screen | `PARKED` | No rescue absent new data or a concrete diversification decision |

There is currently no simple executable strategy candidate. The two fixed
CHINEXT translations both completed under the existing engine and both failed
their predeclared economic promotion rule.

## Fast-screen casualties

| Candidate | Decision |
|---|---|
| VWAP defense/recovery state | Rejected for the CHINEXT trade translation: the accepted coordinate had effectively no low tail and only two high-state completed cycles |
| Joint stress state | Parked: only 62 supported completed cycles, all in the later coarse block |
| Realized-volatility level | Rejected: favorable early high-state result reversed in the later block, whose high state had only two cycles |
| Small-versus-large participation | Rejected: high-state ordering reversed across coarse blocks |
| Day-3/Day-5 CHINEXT path | Remains rejected as a simple executable translation; do not reopen without a new strategy need |
| Formation depth | Parked after extensive research and no CHINEXT V1 habitat transfer |

## Executable translations

| Experiment | Fixed decision | 2018-2021 return delta | 2022-2023 return delta | Promotion result |
|---|---|---:|---:|---|
| `HAB-CHX-DOWNREV-STRAT-001` | At t close, block new admissions when downside-extreme participation PIT <= 0.20 | -11.30 pp | +10.23 pp | Failed return improvement in both blocks; `PARKED_REGIME_DEPENDENT` |
| `HAB-CHX-MINVOLPATH-STRAT-001` | At t 15:30, block next-open admissions when five-day minute-volatility progression PIT >= 0.80 | +18.05 pp | +0.87 pp | Failed severe-loss reduction in both blocks; `PARKED_NEAR_MISS` |

Both preserve existing next-session-open execution, T+1 sellability, trading
status, price limits, corporate actions, costs, exits, and allowed-date ranking.
Both periods are consumed discovery history for these new rules, not untouched
OOS. No post-2023 or CY-011 data was read.

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

What market behavior are we still not studying? Security- and industry-level
rank direction inside widening dispersion, entry/exit and holding-period
mismatch, broad-market exposure sizing under liquidity activity, true order
flow, and stable representations of broader trend quality/age/transition.

Has any discovered mechanism implied a genuinely new strategy archetype? Yes:
dispersion persistence still implies a cross-sectional relative-value research
archetype. It remains a candidate family, not an executable strategy. Neither
new admission veto became a strategy candidate.
