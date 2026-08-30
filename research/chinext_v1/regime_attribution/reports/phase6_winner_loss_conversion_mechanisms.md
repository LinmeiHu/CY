# Phase 6 — winner/loss archetypes and conversion incrementality

EXP-P6-001 consumes only the frozen Phase 5 mechanism table. It performs no replay, threshold search, overlay simulation, post-exit extension, or causal exit counterfactual.

## Mechanism verdict

`SUPPORTED_ENTRY_OPPORTUNITY_PRIMARY_WITH_QUALIFICATION`. Breadth is not a supported downside gate; Phase 5's frozen severe-loss rho is 0.036 with only one negative LOYO estimate.

## Fixed archetypes

| Archetype | N | Breadth median | MFE mean | Return mean | P&L sum | Positive-P&L capture | Holding median |
|---|---:|---:|---:|---:|---:|---:|---:|
| all_cycles | 399 | 0.500 | 0.165 | 0.032 | 1432156 | 1.000 | 9.0 |
| winner20 | 39 | 0.654 | 0.868 | 0.536 | 2487134 | 0.736 | 29.0 |
| winner50 | 15 | 0.654 | 1.396 | 0.893 | 1540131 | 0.456 | 34.0 |
| annual_top10_pnl | 80 | 0.646 | 0.513 | 0.292 | 2798431 | 0.841 | 21.5 |
| annual_top20_pnl | 151 | 0.567 | 0.332 | 0.171 | 3150360 | 0.963 | 15.0 |
| global_top10_pnl | 10 | 0.654 | 1.605 | 1.013 | 1206236 | 0.357 | 34.0 |
| global_top20_pnl | 20 | 0.650 | 1.197 | 0.766 | 1862950 | 0.551 | 33.5 |
| failed_opportunity20 | 45 | 0.646 | 0.302 | 0.083 | 493575 | 0.150 | 23.0 |
| lost_opportunity20 | 6 | 0.582 | 0.238 | -0.017 | -13066 | 0.000 | 19.5 |
| false_breakout | 213 | 0.432 | 0.035 | -0.065 | -1809331 | 0.000 | 7.0 |
| severe_loss | 44 | 0.573 | 0.039 | -0.133 | -834398 | 0.000 | 7.0 |
| extreme_loss | 2 | 0.610 | 0.021 | -0.228 | -76865 | 0.000 | 4.0 |

Archetypes overlap by construction. Annual Top-N uses exit execution year and deterministic P&L/trade-ID ordering; global Top-N spans the three independently funded baseline blocks and is descriptive only.

## Fixed controlled conversion model

Complete MFE>=20% opportunity cycles: 80.

| Endpoint | Partial rho | P-value | Expected-sign LOYO | Pass |
|---|---:|---:|---:|---|
| capture_ratio_opportunity20 | -0.028 | 0.803 | 2/8 | NO |
| conversion20_within_opportunity | -0.068 | 0.547 | 0/8 | NO |
| giveback_from_peak | -0.088 | 0.435 | 7/8 | NO |

The identical design ranks breadth, MFE, holding duration, and time-to-MFE fraction, then controls entry-year and canonical-exit-reason fixed effects. Binary conversion remains binary. No alternate design was tried.

## Interpretation boundary

A surviving partial association would show residual conversion/capture information, not that an exit rule caused the return. A failure supports entry opportunity as primary only with qualification because all years are outcome-consumed and the controlled sample is small.

## Strategy candidate

None in Phase 6. The experiment does not authorize a gate, exposure rule, or exit adaptation.
