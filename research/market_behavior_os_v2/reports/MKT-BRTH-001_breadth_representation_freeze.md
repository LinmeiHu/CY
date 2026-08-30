# MKT-BRTH-001 strategy-independent breadth representation freeze

> **INVALID EVIDENCE:** parallel floating aggregation was not byte
> deterministic. Three panel hashes differed. The displayed construction is
> preserved only as an engineering audit and must not be cited. MKT-BRTH-002 is
> the exact deterministic scientific retry.

## Construction boundary

- Status: `COMPLETE_STRATEGY_INDEPENDENT_BREADTH_REPRESENTATION_FREEZE`
- Source: 6,155,390 CY-006 rows, 2018-01-02..2023-12-29.
- Output: 10,696 daily view/denominator rows across 4 governed views.
- CHINEXT membership, strategy outcomes, trades, future returns, and CY-011 read: **none**.
- This is representation-quality evidence, not economic usefulness or a habitat/strategy claim.
- Minimal nonredundant roles: `new_high_low, leadership_concentration`.

## Representation gates

| Concept | Primary | Min coverage | Worst neighbor median rho | ST sensitivity rho | PIT coverage | Relative coverage | Gate | Minimal panel |
|---|---|---:|---:|---:|---:|---:|---|---|
| participation | `breadth_above_ma20` | 1.000 | 0.668 | 1.000 | 1.000 | 1.000 | FAIL | construction_gate_failed |
| depth | `breadth_median_distance_ma20` | 1.000 | 0.679 | 1.000 | 1.000 | 1.000 | FAIL | construction_gate_failed |
| new_high_low | `breadth_net_new_high_low60` | 1.000 | 0.969 | 0.986 | 1.000 | 1.000 | PASS | ACCEPT |
| momentum | `breadth_momentum_balance5` | 1.000 | 0.608 | 1.000 | 1.000 | 1.000 | FAIL | construction_gate_failed |
| industry_diffusion | `industry_diffusion_ma20` | 1.000 | 0.664 | 0.999 | 1.000 | 1.000 | FAIL | construction_gate_failed |
| leadership_concentration | `leadership_positive_mass_top10` | 1.000 | 0.998 | 1.000 | 1.000 | 1.000 | PASS | ACCEPT |
| divergence | `breadth_industry_divergence_ma20` | 1.000 | 0.504 | 0.995 | 1.000 | 1.000 | FAIL | construction_gate_failed |
| acceleration | `breadth_participation_acceleration5` | 1.000 | 0.044 | 1.000 | 1.000 | 1.000 | FAIL | construction_gate_failed |
| transition | `breadth_net_crossing_ma20_5` | 1.000 | 0.641 | 1.000 | 1.000 | 1.000 | FAIL | construction_gate_failed |

## Outcome-blind latent components

Absolute-Spearman connected components at 0.85: `[['depth', 'divergence', 'industry_diffusion', 'participation'], ['new_high_low'], ['momentum', 'transition'], ['leadership_concentration'], ['acceleration']]`.

These components diagnose redundant manifestations; they do not prove a causal latent factor. Exact constituent-index breadth remains unavailable because historical constituent membership is not registered. SH/SZ/ChiNext-board views are portability diagnostics, not index-constituent breadth.

## Reproducibility

- Spec SHA-256: `d91999433840bdd583e899a609dcb4cac50ae3a95a1d8dbcbd1fe18a11f6127b`
- CY-006 manifest SHA-256: `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`
- Panel SHA-256: `ab9e82880981f240150877600a3e34f525a180a274fb7375cbd2dec2e926ea08`
