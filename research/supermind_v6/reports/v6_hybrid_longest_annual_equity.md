# SuperMind V6 longest hybrid shadow equity

Window: 2010-01-01..2026-08-28

| Year | V6 return | Max DD | Volatility | Sharpe | CSI300 | CSI1000 | Avg exposure | Buy | Rebalance | Sell | No-fill |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2010 | +0.00% | +0.00% | +0.00% | NA | -11.51% | NA | 0.0% | 0 | 0 | 0 | 0 |
| 2011 | +0.00% | +0.00% | +0.00% | NA | -25.01% | NA | 0.0% | 0 | 0 | 0 | 0 |
| 2012 | +0.00% | +0.00% | +0.00% | NA | +7.55% | NA | 0.0% | 0 | 0 | 0 | 0 |
| 2013 | -2.73% | -3.73% | +2.92% | -0.96 | -7.65% | +19.75% | 4.0% | 2 | 0 | 2 | 0 |
| 2014 | +0.87% | -4.09% | +5.09% | 0.19 | +51.66% | +34.46% | 5.2% | 1 | 0 | 0 | 0 |
| 2015 | +18.41% | -4.66% | +8.07% | 2.14 | +5.58% | +76.10% | 13.7% | 1 | 0 | 2 | 1 |
| 2016 | -2.54% | -5.32% | +5.97% | -0.40 | -11.28% | -20.01% | 19.4% | 8 | 11 | 8 | 5 |
| 2017 | +2.77% | -5.83% | +6.29% | 0.47 | +21.78% | -17.35% | 21.9% | 7 | 8 | 7 | 3 |
| 2018 | +2.31% | -1.82% | +2.05% | 1.13 | -25.31% | -36.87% | 2.9% | 1 | 0 | 1 | 0 |
| 2019 | +14.07% | -10.36% | +15.41% | 0.93 | +36.07% | +25.67% | 37.3% | 15 | 17 | 10 | 0 |
| 2020 | +29.46% | -9.51% | +14.56% | 1.85 | +27.21% | +19.39% | 33.6% | 16 | 27 | 17 | 1 |
| 2021 | +6.39% | -6.66% | +11.00% | 0.62 | -5.20% | +20.52% | 21.4% | 12 | 15 | 16 | 3 |
| 2022 | +4.53% | -5.96% | +6.78% | 0.69 | -21.63% | -21.58% | 11.1% | 6 | 9 | 6 | 1 |
| 2023 | +6.78% | -10.97% | +13.36% | 0.56 | -11.38% | -6.28% | 21.3% | 15 | 8 | 15 | 1 |
| 2024 | +34.92% | -7.82% | +20.37% | 1.58 | +14.68% | +1.20% | 25.0% | 16 | 8 | 16 | 0 |
| 2025 | +35.16% | -7.42% | +14.59% | 2.15 | +17.66% | +27.49% | 54.8% | 38 | 43 | 33 | 4 |
| 2026 | +38.26% | -5.95% | +16.26% | 3.14 | -0.45% | +1.44% | 30.4% | 12 | 11 | 17 | 0 |

## Boundary

- 2010-2012 are cash-only because the frozen strategy requires CSI1000 entry-anchor history, which starts on 2013-04-01 in the registered QMT daily data.
- This reconstruction applies recorded shadow fills using fractional target weights and zero fees/slippage.
- Failed orders leave holdings unchanged. Cash constraints and native SuperMind order semantics remain unverified.
- Daily valuation uses QMT pre-adjusted closes; QMT-front versus SuperMind-fq=pre equivalence remains unverified.
- The frozen 152-ETF pool creates survivor bias in early years.
