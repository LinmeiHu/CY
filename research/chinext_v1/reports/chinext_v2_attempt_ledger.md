# ChinNext V2 — mechanism attempt ledger

> 2018–2021 in-sample mechanism research. 2022–2025 was not used for candidate selection.

| Attempt | Change | Return | Max DD | Trades | Median | Mean | Top20 concentration | Ex-best20 | 2018 | 2019 | 2020 | 2021 | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| V2-A001 | r120 ≥ median | 64.23% | -15.05% | 133 | -0.34% | 4.01% | 80.04% | -33.51% | -0.82% | 17.33% | 13.17% | 24.71% | REJECTED_PRIMARY |
| V2-A002 | r20/r60/r120 ≥ median | 72.23% | -15.06% | 102 | 0.15% | 5.79% | 85.60% | -26.38% | -0.43% | 19.36% | 12.54% | 28.77% | REJECTED_PRIMARY |
| V2-A003 | completed-close cycle loss ≤ -10%; next eligible open exit | 60.02% | -21.23% | 197 | -1.36% | 2.78% | 72.75% | -50.51% | -3.78% | 24.46% | 0.18% | 33.40% | REJECTED_PRIMARY |

Both HYP-001 candidates improve several failure metrics and two calendar years, but both increase top-20 positive-P&L concentration above the frozen V1 value of 73.52%. The preregistration explicitly forbids accepting a more lottery-like candidate merely because total return improves.

The HYP-002 candidate is causally valid: all 13 loss-budget signals execute as full exits on later eligible opens, with zero same-day fills and zero 2022+ executions. It nevertheless increases severe-loss cycles from 22 to 26, worsens severe-loss P&L from -413,236.91 to -433,148.09, worsens total negative P&L, median trade, return ex-best20, and max drawdown, and lowers total return. Better concentration plus stronger 2019 and 2021 cannot override those frozen failures.

Final status: `NO_DEFENSIBLE_V2_CANDIDATE`. No threshold search, grid search, or 2022–2025 candidate-selection run was performed. HYP-003 has no uniquely identified causal intervention, so the stopping rule applies. V1 remains the frozen baseline; no V2 strategy or revision-holdback preregistration is created.
