# SuperMind V6 frozen ETF strategy - annual hybrid signal quality

Continuous replay: 2010-01-01..2026-08-28

| Year | Entry trades | Completed | Mean P&L | Median P&L | Win rate | 5d mean | 20d mean | 60d mean |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2010 | 0 | 0 | NA | NA | NA | NA | NA | NA |
| 2011 | 0 | 0 | NA | NA | NA | NA | NA | NA |
| 2012 | 0 | 0 | NA | NA | NA | NA | NA | NA |
| 2013 | 2 | 2 | -2.74% | -2.74% | 0.00% | 0.69% | -9.23% | -7.63% |
| 2014 | 1 | 1 | 1.06% | 1.06% | 100.00% | 4.79% | 2.85% | 19.56% |
| 2015 | 1 | 1 | 37.61% | 37.61% | 100.00% | 3.97% | 21.28% | 76.86% |
| 2016 | 8 | 8 | -0.63% | -1.58% | 37.50% | -0.13% | 1.25% | 0.38% |
| 2017 | 7 | 7 | 0.67% | 0.28% | 57.14% | 0.63% | 0.88% | -0.50% |
| 2018 | 1 | 1 | 4.61% | 4.61% | 100.00% | 4.00% | -8.53% | -14.51% |
| 2019 | 15 | 15 | 3.25% | -0.50% | 46.67% | 0.05% | 3.17% | 3.22% |
| 2020 | 16 | 16 | 6.31% | 7.45% | 68.75% | 0.63% | 9.39% | 6.92% |
| 2021 | 12 | 12 | 0.91% | 0.62% | 58.33% | 0.71% | 0.70% | -4.97% |
| 2022 | 6 | 6 | 3.34% | 3.96% | 83.33% | 0.47% | 3.67% | -2.50% |
| 2023 | 15 | 15 | 2.36% | 1.19% | 66.67% | 0.99% | 1.40% | -0.81% |
| 2024 | 16 | 16 | 10.31% | 0.80% | 56.25% | 10.84% | 12.20% | 12.63% |
| 2025 | 38 | 38 | 5.75% | 2.66% | 71.05% | 0.55% | 3.72% | 8.06% |
| 2026 | 12 | 12 | 4.31% | 0.09% | 50.00% | 1.36% | 3.68% | 1.66% |

## Interpretation boundary

- frozen V6 functions and 152-ETF pool are unchanged, but this is a local shadow replay rather than a native SuperMind backtest
- QMT exact 1m overrides local exact 1m; local raw prices use QMT daily front-adjustment factors
- QMT front adjustment is not proven equivalent to SuperMind fq=pre
- opening-auction and set_execution(close) matching semantics remain unverified
- fees, slippage, cash, partial fills, and exact order return semantics are simplified/not simulated
- missing or nonpositive-volume critical bars fail closed
- 000852.SH 14:57 intraday history before 2025-08-27 is unavailable; this entry anchor snapshot fails closed, while the 510300 exit anchor remains exact-1m
