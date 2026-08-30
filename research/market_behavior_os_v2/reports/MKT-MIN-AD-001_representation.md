# MKT-MIN-AD-001 intraday absorption/distribution falsification

## Boundary

- Status: `COMPLETE_1_OF_2_MINIMAL_REPRESENTATIONS`
- Source: frozen daily minute descriptors available at 15:30; raw minute rows were not reopened.
- Labels are OHLCV effort-versus-result hypotheses, not participant intent or cross-day processes.
- Future values, strategy outcomes, post-2023 data, and CY-011 read: **none**.

## Fixed gates

| Hypothesis | Shape | LOO | p40/p60 | Denominator | External rho | PIT R2 | Relative R2 | Minimal |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| selling_effort_absorption | 0.718 | 0.502 | 0.854 | 0.991 | NA | NA | NA | NO |
| rally_effort_distribution | 0.895 | 0.774 | 0.975 | 0.999 | 0.792 | 0.649 | 0.161 | YES |

## Reproducibility

- Spec SHA-256: `311391c7ae487f3a041a2c31ed9d209cd730dc7de919305dcaeba6de7c0d2506`
- Runner SHA-256: `0b12f66a05ca69b61bd3afb1d7a1f91ec6d1334045bc022533f9562bcc6ab6cd`
- Panel SHA-256: `e78856ea6e912d04c9356bf5d53d53c4098f33f8a5dae08c94a09341a0e80614`
