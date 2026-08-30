# MKT-BREAKOUT-DIFF-001 full-market representation

## Result

- Status: `COMPLETE_SUPPORTED_LEVEL_REPRESENTATION_GEOMETRY`
- Daily rows: 11,336; eligible ALL_A/ALL_STATUS security-dates: 5,550,255.
- Failed L40 ChiNext acceptance-industry roles remain unestimated and excluded.
- Construction-pass roles: `formation_participation, formation_depth, closing_acceptance, closing_rejection_depth, equal_industry_formation, formation_diffusion, formation_leadership_concentration, stock_industry_divergence`.
- Externally distinct roles: `formation_participation, formation_depth, closing_acceptance, closing_rejection_depth, equal_industry_formation, formation_diffusion, formation_leadership_concentration, stock_industry_divergence`.
- Final minimal direct roles: `formation_participation, formation_depth, closing_acceptance, closing_rejection_depth, formation_diffusion, formation_leadership_concentration, stock_industry_divergence`.
- This is representation/geometry evidence only; no transition, outcome, habitat, timing, execution, or strategy claim is permitted.

## Fixed role gates

| Role | Min coverage | Worst neighbor rho | ST rho | PIT coverage | Relative coverage | Construction | External | Final |
|---|---:|---:|---:|---:|---:|---|---|---|
| formation_participation | 1.000 | 0.891 | 0.999 | 1.000 | 1.000 | PASS | PASS | RETAIN |
| formation_depth | 1.000 | 0.864 | 0.998 | 1.000 | 1.000 | PASS | PASS | RETAIN |
| closing_acceptance | 1.000 | 0.916 | 0.998 | 1.000 | 1.000 | PASS | PASS | RETAIN |
| closing_rejection_depth | 1.000 | 0.930 | 0.998 | 1.000 | 1.000 | PASS | PASS | RETAIN |
| equal_industry_formation | 0.992 | 0.889 | 0.999 | 0.999 | 1.000 | PASS | PASS | internally_redundant_with:formation_participation |
| formation_diffusion | 0.992 | 0.863 | 0.997 | 0.999 | 1.000 | PASS | PASS | RETAIN |
| formation_leadership_concentration | 0.992 | 0.728 | 0.992 | 0.999 | 1.000 | PASS | PASS | RETAIN |
| stock_industry_divergence | 0.992 | 0.841 | 0.981 | 0.999 | 1.000 | PASS | PASS | RETAIN |

## Reproducibility

- Spec SHA-256: `9a7d63ebbab4d23e9fee955748c23b1112aa370aa725e1eb24c83f998dd0aa27`
- Runner SHA-256: `c09c6d2d2aac5bb58c333b4c46ea27ad19774ce147d68f8eb1fb6a90a9bd2530`
- Panel SHA-256: `99fd26ee6973c338e8df803e44434bc0ad6498dfefee518d9c51bc4c605d4d11`
- Stability audit SHA-256: `d47e82a20e12c1a2873e8119db93c015e0cbc9ac085de84d0580fc4b7b6fe394`
- External geometry SHA-256: `37ca992f8fab43c3b3f06c874b3fa2b3b8589a18b00f9b123c8d2a9e4227bb5a`
