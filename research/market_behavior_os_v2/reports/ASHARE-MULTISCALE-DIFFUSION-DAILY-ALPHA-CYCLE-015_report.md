# A-share multi-timescale Industry Diffusion and daily-alpha Cycle 015

## Boundary and frozen design

Cycle 015 starts from `2a2d307ec5` and uses consumed 2018--2023 development
history only. Post-2023 outcomes and CY-011 remain unread. The Industry
Diffusion state, prior-20-session Low-MAX definition, 20-session cohort life,
next-open execution, 20/30/40-bps-per-side costs, T+1, limits, suspensions, and
QD-010 corporate-action semantics are unchanged.

Only two architectures were allowed:

1. frozen weekly Industry Diffusion plus frozen weekly Low-MAX selection;
2. the same weekly industry state and industry counts, with exact Low-MAX stock
   preferences refreshed after each completed daily close and replacements at
   the next legal open.

Daily refresh is slot preserving. It does not liquidate or rebalance the whole
portfolio. If a daily industry cross-section has too few quality-valid names,
incumbents fill the missing slots; no quality-missing new name is introduced.

## Track A: representation and churn

The causal daily panel contains 3,009,296 security-dates, 4,798 symbols, and
1,337 dates. It creates 52,600 desired schedule rows. Comparable initial daily
cohorts reproduce the exact weekly Low-MAX selections.

Daily Low-MAX ranks are persistent but not inert: mean/median one-session rank
autocorrelation is 0.947/1.000, mean selection overlap is 87.60%, and 12.40% of
preferred slots change per transition. There are 4,898 requested preferred-name
changes across 1,329 decision days; only 148 days request no change. The median
preferred-name episode lasts five sessions and the mean lasts 6.99.

The replacement-minus-rejected return half-life is economically null and
nonportable. Across 4,343 complete pairs, net differences are +0.001% at h1,
-0.063% at h3, and +0.052% at h5. Early/late h3 is -0.126%/-0.012%; h5 reverses
from -0.052% to +0.138%. Classification: `NONPORTABLE_DAILY_CHURN`.

## Track A: matched executable economics

| Cost per side | Weekly Low-MAX total | Daily refresh total | Delta | Daily annualized | Daily DD | Daily Sharpe | Daily turnover |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 bps | +122.43% | +49.24% | -73.19 pp | +7.88% | -27.57% | 0.432 | 488.82x |
| 30 bps | +95.22% | +2.74% | -92.48 pp | +0.51% | -28.62% | 0.144 | 398.54x |
| 40 bps | +71.34% | -29.22% | -100.56 pp | -6.33% | -38.20% | -0.144 | 328.63x |

At 20 bps, daily refresh executes 4,841 of 4,918 requested replacements
(98.43%), completes 7,466 trades, and raises turnover by 278.30x initial capital
relative to weekly Low-MAX. It improves the severe-trade rate by 8.66 percentage
points and leaves industry HHI essentially unchanged, but loses 73.19 percentage
points of total return and 0.299 Sharpe. P10 capacity remains CNY86.6m, 77.95%
of the weekly estimate. At 40 bps, total return and Sharpe are negative.

Only capacity, drawdown-tolerance, severe-loss, and concentration gates pass.
Return, Sharpe, Calmar, high-cost resilience, and return per incremental turnover
fail. Final classification: `DAILY_REFRESH_DEGRADES_STRATEGY`. The frozen weekly
Industry Diffusion plus weekly Low-MAX architecture remains preferred; no daily
refresh rule is admitted.

## Track B: daily h1--h5 discovery

All screens use next-open entry, 20 bps per side, and same-date nearest controls
on daily return, log prior amount, r20, and range ratio, within PIT industry
where available.

| Hypothesis | Complete pairs | h3 event-control | Early / late | h5 severe improvement | Classification |
|---|---:|---:|---:|---:|---|
| Gapless range acceptance | 17,628 | +0.111% | +0.029% / +0.153% | +0.573 pp | `PROMISING_DAILY_INFORMATION` |
| Compression-release acceptance | 2,383 | +0.254% | +0.193% / +0.293% | +0.252 pp | `PROMISING_DAILY_INFORMATION` |
| Overnight/intraday alignment | 33,876 | +0.138% | +0.273% / +0.004% | -0.664 pp | `PROMISING_DAILY_INFORMATION` |
| Broad-industry nonleader acceptance | 125,925 | -0.056% | -0.208% / +0.058% | +1.704 pp | `CHRONOLOGICALLY_MIXED` |
| Industry-shock recovery confirmation | 38,478 | +0.113% | +0.196% / +0.054% | +0.951 pp | `PROMISING_DAILY_INFORMATION` |

No hypothesis clears the frozen promotion rule requiring at least +0.25% h3,
positive early and late effects, and at least +1.00 percentage point h5 severe-
loss improvement, alongside breadth and execution coverage. Compression release
meets the return floor by a narrow margin but not the severe-loss floor. No
Track B executable replay or combination is authorized.

## Research conclusion

`NO DAILY ARCHITECTURE OR NEW DAILY STRATEGY CANDIDATE.` Daily Low-MAX refresh
adds large executable churn without a stable short-horizon replacement edge and
destroys the weekly architecture's cost-adjusted economics. Several daily path
hypotheses contain weak descriptive information, but none earns portfolio
translation under the frozen gates.

What market behavior are we still not studying? Governed order-book/queue
pressure, investor-flow identity, borrow-feasible relative value,
immutable-vintage PIT fundamentals, and genuinely independent confirmation.

Has any discovered mechanism implied a genuinely new strategy archetype? No.
The daily findings are weak path-quality diagnostics, and the multi-timescale
test reinforces slow weekly selection rather than creating a new archetype.

The next research capital should leave daily summary-OHLCV neighbors and move
to a bounded data contract that unlocks multiple genuinely independent
mechanisms. Preserve weekly Industry Diffusion plus weekly Low-MAX unchanged.
