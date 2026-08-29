# SuperMind V6 frozen ETF strategy - annual hybrid signal quality

Continuous replay: 2020-01-01..2026-08-28

| Year | Entry trades | Completed | Mean P&L | Median P&L | Win rate | 5d mean | 20d mean | 60d mean |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 19 | 19 | 4.85% | 6.29% | 57.89% | 0.46% | 6.90% | 4.37% |
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
