# MKT-INDRS-001 industry leadership and relative-strength representation

## Boundary

- Status: `COMPLETE_8_OF_11_ROLES_PASS_7_MINIMAL`
- Source: 6,155,390 CY-006 rows; output 10,696 group/date rows.
- PIT industry labels, exact leave-one-out medians, and serial construction only.
- Failed MA diffusion fields, future returns, strategy outcomes, and CY-011 read: **none**.
- Representation stability is not future persistence, selection alpha, sector-rotation usefulness, or a strategy rule.
- Minimal roles: `industry_positive_participation_1d, industry_return_dispersion_1d, winner_industry_diffusion20, industry_rank_rotation20, stock_industry_rs_dispersion20, stock_industry_rs_tail_balance20, stock_industry_rs_concentration20`.

## Role gates

| Role | Coverage | Worst neighbor rho | Denominator rho | Gate | Minimal disposition |
|---|---:|---:|---:|---|---|
| `industry_positive_participation_1d` | 1.000 | 0.988 | 0.999 | PASS | ACCEPT |
| `industry_return_depth_1d` | 1.000 | 0.991 | 0.999 | PASS | redundant_with:industry_positive_participation_1d |
| `industry_return_dispersion_1d` | 1.000 | 0.894 | 0.989 | PASS | ACCEPT |
| `industry_market_rs_depth20` | 1.000 | 0.660 | 0.967 | FAIL | representation_gate_failed |
| `industry_leadership_concentration20` | 0.945 | 0.990 | 0.998 | FAIL | representation_gate_failed |
| `winner_industry_diffusion20` | 1.000 | 0.837 | 0.992 | PASS | ACCEPT |
| `industry_leadership_persistence20` | 1.000 | 0.540 | 0.894 | FAIL | representation_gate_failed |
| `industry_rank_rotation20` | 1.000 | 0.985 | 0.990 | PASS | ACCEPT |
| `stock_industry_rs_dispersion20` | 1.000 | 0.961 | 0.999 | PASS | ACCEPT |
| `stock_industry_rs_tail_balance20` | 1.000 | 0.920 | 0.994 | PASS | ACCEPT |
| `stock_industry_rs_concentration20` | 1.000 | 0.946 | 0.997 | PASS | ACCEPT |

## Reproducibility

- Spec SHA-256: `e49f209806c25cafb1c78c5730fbfe07b0c83690fc14bc1a677c8d303d38836d`
- Panel SHA-256: `c9e8d44935261256c1f3a6246026ba2ff0a02d3373386771fe58182ad3baeaf4`
- Leave-one-out audit rows: 1,988; maximum exact difference 0.0.
