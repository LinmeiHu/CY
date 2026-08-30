# MKT-STYLE-001 circulating-size representation

## Boundary

- Status: `COMPLETE_6_OF_8_MINIMAL_ROLES`
- Bucket assignment: exact t-1 circulating-market-value rank; no current-close sort.
- Total-cap, true-free-float, growth/value, beta, future, strategy, post-2023, and CY-011 fields read: **none**.
- Any passing role is a representation only, not a small-cap premium, timing signal, habitat, or rule.

## Role diagnostics

| Role | Min coverage | Worst neighbor rho | Denominator rho | PIT | Relative | Gate |
|---|---:|---:|---:|---:|---:|---|
| `size_structure` | 1.000 | 0.944 | 0.995 | 1.000 | 1.000 | PASS |
| `positive_participation_balance` | 0.999 | 0.988 | 0.997 | 1.000 | 1.000 | PASS |
| `size_leadership_1d` | 0.999 | 0.986 | 0.997 | 1.000 | 1.000 | PASS |
| `size_leadership_20d` | 0.986 | 0.634 | 0.997 | 1.000 | 1.000 | FAIL |
| `winner_diffusion` | 0.999 | 0.725 | 0.973 | 1.000 | 1.000 | PASS |
| `positive_mass_concentration` | 0.999 | 0.960 | 0.983 | 1.000 | 1.000 | PASS |
| `size_curve_divergence` | 0.999 | 0.879 | 0.992 | 1.000 | 1.000 | PASS |
| `leadership_transition` | 0.983 | 0.723 | 0.997 | 1.000 | 1.000 | PASS |

## Fixed-priority compression

- Accepted roles: `size_structure, positive_participation_balance, winner_diffusion, positive_mass_concentration, size_curve_divergence, leadership_transition`
- Excluded roles: `{"size_leadership_1d": "redundant_with:positive_participation_balance", "size_leadership_20d": "construction_gate_failed"}`

## Reproducibility

- Spec SHA-256: `a32ca8fcdb6080beb97f4226a891c44270a46e9d0a4818d4132501fdc1a808a3`
- Panel SHA-256: `5ed526187d71cb0c719a98ba99fcba368ea6dc53b6ad097efbebb5bb1f2863ad`
