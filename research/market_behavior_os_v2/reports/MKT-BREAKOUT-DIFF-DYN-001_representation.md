# MKT-BREAKOUT-DIFF-DYN-001 historical temporal representations

## Result

- Status: `COMPLETE_0_OF_14_REPRESENTATIONS_PASS_0_MINIMAL`
- Panel: 11,336 rows, 2018-03-06..2023-12-29.
- Construction-pass roles: 0/14; minimal direct roles: 0.
- Inputs stop at each completed 15:00 close. Future state, outcomes, strategy fields, raw security/minute data, post-2023 data, and CY-011 were not read.
- Stable historical shape is not persistence, prediction, habitat, or strategy usefulness.

## Fixed gates

| Role | Full neighbor | Block neighbor | Phase neighbor | ST rho | Level rho | External max rho/R2 | Disposition |
|---|---:|---:|---:|---:|---:|---:|---|
| formation_participation__change | 0.557 | 0.544 | 0.584 | 0.999 | 0.463 | 0.642/0.527 | representation_gate_failed |
| formation_participation__acceleration | -0.041 | -0.074 | -0.043 | 0.999 | 0.213 | 0.667/0.464 | representation_gate_failed |
| formation_depth__change | 0.520 | 0.498 | 0.502 | 0.997 | 0.467 | 0.391/0.154 | representation_gate_failed |
| formation_depth__acceleration | -0.103 | -0.116 | -0.105 | 0.997 | 0.238 | 0.334/0.123 | representation_gate_failed |
| closing_acceptance__change | 0.475 | 0.475 | 0.490 | 0.998 | 0.688 | 0.583/0.327 | representation_gate_failed |
| closing_acceptance__acceleration | -0.182 | -0.187 | -0.191 | 0.998 | 0.393 | 0.578/0.335 | representation_gate_failed |
| closing_rejection_depth__change | 0.460 | 0.449 | 0.445 | 0.998 | 0.660 | 0.704/0.494 | representation_gate_failed |
| closing_rejection_depth__acceleration | -0.137 | -0.137 | -0.151 | 0.998 | 0.406 | 0.703/0.487 | representation_gate_failed |
| formation_diffusion__change | 0.580 | 0.576 | 0.602 | 0.995 | 0.470 | 0.614/0.509 | representation_gate_failed |
| formation_diffusion__acceleration | -0.071 | -0.080 | -0.041 | 0.995 | 0.164 | 0.597/0.446 | representation_gate_failed |
| formation_leadership_concentration__change | 0.505 | 0.496 | 0.524 | 0.992 | 0.627 | 0.208/0.052 | representation_gate_failed |
| formation_leadership_concentration__acceleration | -0.135 | -0.151 | -0.133 | 0.992 | 0.341 | 0.250/0.061 | representation_gate_failed |
| stock_industry_divergence__change | 0.528 | 0.523 | 0.513 | 0.976 | 0.574 | 0.290/0.070 | representation_gate_failed |
| stock_industry_divergence__acceleration | -0.085 | -0.106 | -0.095 | 0.977 | 0.267 | 0.374/0.125 | representation_gate_failed |

## Reproducibility

- Spec SHA-256: `3c095e17a76b19cbc82fece8dc458cc3e16bc02c859175bf83f7a7c1b8416d14`
- Runner SHA-256: `d0163fc48e8d1a2074bcc71f7182314e724dab456e1fbb42d630a26fadc12ca4`
- Panel SHA-256: `909aa755d2fc136b19be683b633a50112ef98ef03f754bf3c2f7abcbc082619a`
- Stability audit SHA-256: `0c7ad93bb26b38025049ff85893d060585c3f87f80681b184eb5b7f5ab40d131`
- External audit SHA-256: `3e8d3238e651a0704ac2d9eaf5b93bb07d082ad6d693fdd217c8fdf66ec1bfb7`
- Five independently reconstructed scalar operators match exactly.
