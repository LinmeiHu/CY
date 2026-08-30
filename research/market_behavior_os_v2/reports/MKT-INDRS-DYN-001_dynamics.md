# MKT-INDRS-DYN-001 industry leadership dynamics

## Boundary

- Status: `COMPLETE_1_OF_3_TEMPORAL_EDGES_PASS`
- Future market state read: next-block rank rotation and five-session winner-diffusion change only.
- Market/stock returns, selection outcomes, strategy fields, failed roles, failed MA fields, and CY-011 read: **none**.
- Any passing edge is a state dynamic, not return prediction, timing, habitat, causality, or a rule.

## Temporal edges

| Edge | Raw discovery rho | Raw confirmation rho | PIT discovery rho | PIT confirmation rho | Phase-zero discovery rho | Phase-zero confirmation rho | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| `rotation_persistence` | 0.250 | 0.221 | 0.216 | 0.244 | 0.220 | 0.161 | PASS |
| `diffusion_to_rotation` | 0.246 | 0.008 | 0.248 | 0.041 | 0.311 | -0.002 | FAIL |
| `rotation_to_diffusion_change` | 0.033 | -0.235 | 0.021 | -0.163 | 0.002 | -0.268 | FAIL |

## Reproducibility

- Spec SHA-256: `b1266eed922e974b08b4a4a29bc01e574a09f0e2b7ecb0fe044210c39c3f1fdf`
- Panel SHA-256: `3aba96f1ba0748342eb22efccb71c8b9ed494f9664e29cc20a6753232bdd8e0e`
