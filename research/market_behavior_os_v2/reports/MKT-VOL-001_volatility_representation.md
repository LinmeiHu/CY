# MKT-VOL-001 volatility representation freeze

## Boundary

- Status: `COMPLETE_STRATEGY_INDEPENDENT_VOLATILITY_REPRESENTATION_FREEZE`
- Output: 10,696 daily view/denominator rows.
- Strategy membership, outcomes, future paths, and CY-011 read: **none**.
- This establishes representation quality only, not panic, contraction/expansion usefulness, a habitat, or a strategy.
- Minimal nonredundant roles: `realized_volatility, intraday_range, volatility_concentration, volatility_change`.

## Representation gates

| Concept | Min coverage | Worst neighbor median rho | ST sensitivity rho | PIT coverage | Gate | Minimal panel |
|---|---:|---:|---:|---:|---|---|
| realized_volatility | 1.000 | 0.878 | 1.000 | 1.000 | PASS | ACCEPT |
| downside_volatility | 1.000 | 0.732 | 1.000 | 1.000 | PASS | redundant_with:realized_volatility |
| intraday_range | 1.000 | 0.914 | 1.000 | 1.000 | PASS | ACCEPT |
| term_structure | 1.000 | 0.634 | 1.000 | 1.000 | FAIL | construction_gate_failed |
| dispersion | 1.000 | 0.917 | 1.000 | 1.000 | PASS | redundant_with:intraday_range |
| downside_mass_share | 1.000 | 0.694 | 1.000 | 1.000 | FAIL | construction_gate_failed |
| volatility_concentration | 1.000 | 0.982 | 0.999 | 1.000 | PASS | ACCEPT |
| volatility_change | 1.000 | 0.755 | 0.999 | 1.000 | PASS | ACCEPT |

Outcome-blind components at absolute Spearman 0.85: `[['downside_volatility', 'realized_volatility'], ['dispersion', 'intraday_range'], ['term_structure'], ['downside_mass_share'], ['volatility_concentration'], ['volatility_change']]`.

Failed fixed representations leave their broader families open.

## Reproducibility

- Spec SHA-256: `bf2976e8c818ff57b38c16a4f4c23395a90367f7e9c9bea5314da824ee04ffad`
- Panel SHA-256: `f736128419bdd632444c70e12233b08823130ffccffffcd68a9f69f7330040dc`
