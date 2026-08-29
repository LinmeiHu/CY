# SuperMind V6 longest single-signal quality

Every BUY_SIGNAL and TAIL_SELL_SIGNAL is equally weighted; portfolio sizing and holding P&L are ignored.
Positive SELL quality means the underlying fell after the sell signal.

## Buy signals

| Year | Signals | Evaluable | 1d mean | 5d mean | 20d mean | 60d mean | 20d win |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2010 | 0 | 0 | NA | NA | NA | NA | NA |
| 2011 | 0 | 0 | NA | NA | NA | NA | NA |
| 2012 | 0 | 0 | NA | NA | NA | NA | NA |
| 2013 | 2 | 2 | -0.75% | +0.69% | -9.23% | -7.63% | 50.00% |
| 2014 | 1 | 1 | +0.24% | +4.79% | +2.85% | +19.56% | 100.00% |
| 2015 | 1 | 1 | -0.02% | +3.97% | +21.28% | +76.86% | 100.00% |
| 2016 | 8 | 8 | +0.13% | -0.13% | +1.25% | +0.38% | 62.50% |
| 2017 | 8 | 7 | +0.33% | +0.63% | +0.88% | -0.50% | 57.14% |
| 2018 | 1 | 1 | +1.53% | +4.00% | -8.53% | -14.51% | 0.00% |
| 2019 | 15 | 15 | +0.73% | +0.05% | +3.17% | +3.22% | 66.67% |
| 2020 | 16 | 16 | +0.51% | +0.63% | +9.39% | +6.92% | 75.00% |
| 2021 | 15 | 12 | +0.72% | +0.71% | +0.70% | -4.97% | 50.00% |
| 2022 | 7 | 6 | +0.11% | +0.47% | +3.67% | -2.50% | 83.33% |
| 2023 | 16 | 15 | +0.24% | +0.99% | +1.40% | -0.81% | 66.67% |
| 2024 | 16 | 16 | +2.14% | +10.84% | +12.20% | +12.63% | 68.75% |
| 2025 | 39 | 38 | -0.19% | +0.55% | +3.72% | +8.06% | 71.05% |
| 2026 | 12 | 12 | +1.17% | +1.36% | +3.68% | +1.66% | 50.00% |

## Sell signals

| Year | Signals | Evaluable | 1d avoided | 5d avoided | 20d avoided | 60d avoided | 20d correct |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2010 | 0 | 0 | NA | NA | NA | NA | NA |
| 2011 | 0 | 0 | NA | NA | NA | NA | NA |
| 2012 | 0 | 0 | NA | NA | NA | NA | NA |
| 2013 | 2 | 2 | +0.85% | +0.33% | +8.27% | +4.88% | 100.00% |
| 2014 | 0 | 0 | NA | NA | NA | NA | NA |
| 2015 | 2 | 2 | -4.24% | -11.19% | -26.87% | -31.21% | 0.00% |
| 2016 | 8 | 8 | +0.57% | +1.81% | -0.25% | -2.76% | 50.00% |
| 2017 | 7 | 7 | +0.09% | -1.13% | +0.12% | +2.94% | 42.86% |
| 2018 | 1 | 1 | -1.34% | +12.40% | +8.75% | +15.31% | 100.00% |
| 2019 | 10 | 10 | +0.44% | +0.27% | -0.65% | -4.75% | 40.00% |
| 2020 | 17 | 17 | +2.67% | -2.92% | -4.14% | -4.41% | 11.76% |
| 2021 | 16 | 16 | -0.37% | -1.14% | +2.20% | +6.86% | 75.00% |
| 2022 | 6 | 6 | -0.27% | +0.97% | +3.90% | +9.48% | 100.00% |
| 2023 | 15 | 15 | +0.54% | +2.50% | +5.09% | +4.16% | 80.00% |
| 2024 | 16 | 16 | -1.56% | -3.69% | -2.60% | +1.48% | 50.00% |
| 2025 | 29 | 29 | -0.28% | -0.15% | -0.78% | -5.35% | 44.83% |
| 2026 | 17 | 17 | -0.82% | -0.63% | -4.58% | +5.16% | 35.29% |

## Boundary

- BUY is evaluated from the exact next 09:30 critical-bar reference price.
- SELL is evaluated from the exact 14:57 signal reference price; positive quality means avoided loss.
- Missing or invalid critical prices are UNAVAILABLE and excluded from averages, never replaced by daily prices.
- No portfolio weight, cash, position count, rebalance weight, or holding-period exit pairing is used.
- Signals still come from the frozen strategy state machine; this does not invent daily signals while a name is already held.
