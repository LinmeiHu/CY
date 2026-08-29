# SuperMind V6 unlimited-capital independent trade quality

Each ETF can carry one independent trade. There is no portfolio holding limit, capital budget, position weight, or cross-symbol cash competition.
Entry and exit conditions, signal timing, and fail-closed execution references are inherited from the frozen V6 strategy.

| Entry year | Trades | Completed | Open | Win rate | Mean | Median | P10 | P90 | Avg win | Avg loss | Profit factor | Mean hold | Median hold |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2010 | 0 | 0 | 0 | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA |
| 2011 | 0 | 0 | 0 | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA |
| 2012 | 0 | 0 | 0 | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA |
| 2013 | 2 | 2 | 0 | 0.0% | -2.74% | -2.74% | -3.22% | -2.26% | NA | -2.74% | NA | 9.50 | 9.50 |
| 2014 | 1 | 1 | 0 | 100.0% | +1.06% | +1.06% | +1.06% | +1.06% | +1.06% | NA | NA | 35.00 | 35.00 |
| 2015 | 1 | 1 | 0 | 100.0% | +37.61% | +37.61% | +37.61% | +37.61% | +37.61% | NA | NA | 51.00 | 51.00 |
| 2016 | 8 | 8 | 0 | 37.5% | -0.63% | -1.58% | -3.18% | +2.62% | +2.33% | -2.41% | 0.58 | 17.75 | 17.00 |
| 2017 | 7 | 7 | 0 | 57.1% | +0.67% | +0.28% | -1.68% | +3.53% | +2.26% | -1.44% | 2.09 | 15.86 | 15.00 |
| 2018 | 1 | 1 | 0 | 100.0% | +4.61% | +4.61% | +4.61% | +4.61% | +4.61% | NA | NA | 14.00 | 14.00 |
| 2019 | 19 | 19 | 0 | 36.8% | +2.01% | -1.27% | -3.00% | +10.24% | +9.46% | -2.35% | 2.35 | 21.95 | 23.00 |
| 2020 | 29 | 29 | 0 | 62.1% | +6.33% | +6.46% | -5.73% | +18.18% | +12.31% | -3.46% | 5.82 | 17.55 | 18.00 |
| 2021 | 14 | 14 | 0 | 50.0% | +0.25% | -0.21% | -3.35% | +4.08% | +3.00% | -2.49% | 1.20 | 10.07 | 9.50 |
| 2022 | 9 | 9 | 0 | 66.7% | +1.39% | +2.76% | -3.10% | +5.06% | +3.71% | -3.25% | 2.28 | 19.56 | 22.00 |
| 2023 | 42 | 42 | 0 | 59.5% | +1.36% | +1.06% | -2.63% | +5.11% | +3.23% | -1.40% | 3.40 | 11.95 | 13.00 |
| 2024 | 36 | 36 | 0 | 27.8% | +3.36% | -1.03% | -4.37% | +26.80% | +17.60% | -2.12% | 3.19 | 11.94 | 13.00 |
| 2025 | 158 | 158 | 0 | 61.4% | +3.23% | +1.45% | -2.50% | +10.41% | +6.33% | -1.70% | 5.91 | 15.44 | 15.00 |
| 2026 | 40 | 40 | 0 | 57.5% | +2.62% | +0.89% | -2.83% | +10.03% | +6.24% | -2.27% | 3.72 | 10.25 | 12.00 |

## Semantics

- Unlimited capital removes max_holdings=5, full-portfolio scan suppression, CAP50_SET weights, and cross-symbol cash competition.
- All ETFs passing the frozen CSI1000 gate, eligibility, B60, FULL40, MINVOLLOC30, and RS-availability checks are bought at the exact next 09:30 executable reference.
- One independent trade per ETF may be open at a time; after exit, the ETF may generate another trade.
- Exits preserve the frozen next-open and 14:57/final-close market and own-MA40x2 rules.
- Missing/invalid critical bars produce no-fill and are retried only through the original continuing signal state; no daily-price substitution is used.
- Fees, slippage, lot rounding, and native SuperMind order-return semantics remain unverified/not simulated.
- The frozen 152-ETF pool creates survivor bias in early years.
