# Phase 7 — simple V1-R raw-breadth exposure candidate

EXP-P7-003 decision: `REJECT_OR_RETAIN_EXPLANATORY_ONLY`. This is outcome-consumed candidate evidence, not untouched OOS or production authorization.

## Control identity

- EXTENDED_2018_2021: `PASS` — all six frozen identity/economic checks passed: `True`.
- HOLDOUT_O0_2022_2023: `PASS` — all six frozen identity/economic checks passed: `True`.
- DEVELOPMENT_2024_2025: `PASS` — all six frozen identity/economic checks passed: `True`.

## Block metrics

| Block | Arm | Return | Max DD | Avg invested | Trades | Winner20 | Ex-best20 | Top20 capture |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| EXTENDED_2018_2021 | C0_ALL_ONE_CONTROL | 64.82% | -20.76% | 24.90% | 194 | 17 | -50.16% | nan% |
| EXTENDED_2018_2021 | A40_HALF_PRIMARY | 46.69% | -21.67% | 21.74% | 175 | 15 | -47.88% | 78.24% |
| EXTENDED_2018_2021 | N30_HALF_NEIGHBOR | 52.64% | -20.63% | 22.54% | 175 | 15 | -46.04% | 82.63% |
| EXTENDED_2018_2021 | N50_HALF_NEIGHBOR | 48.20% | -21.33% | 20.94% | 175 | 15 | -47.33% | 79.18% |
| EXTENDED_2018_2021 | Z40_ZERO_SEVERITY | 35.78% | -23.69% | 20.84% | 156 | 13 | -50.52% | 67.71% |
| HOLDOUT_O0_2022_2023 | C0_ALL_ONE_CONTROL | -15.52% | -19.34% | 17.84% | 94 | 4 | -33.74% | nan% |
| HOLDOUT_O0_2022_2023 | A40_HALF_PRIMARY | -15.36% | -19.20% | 17.79% | 94 | 4 | -33.60% | 100.08% |
| HOLDOUT_O0_2022_2023 | N30_HALF_NEIGHBOR | -15.52% | -19.34% | 17.84% | 94 | 4 | -33.74% | 100.00% |
| HOLDOUT_O0_2022_2023 | N50_HALF_NEIGHBOR | -13.33% | -17.98% | 17.17% | 94 | 4 | -31.25% | 98.30% |
| HOLDOUT_O0_2022_2023 | Z40_ZERO_SEVERITY | -15.22% | -19.06% | 17.75% | 92 | 4 | -33.46% | 100.08% |
| DEVELOPMENT_2024_2025 | C0_ALL_ONE_CONTROL | 105.24% | -26.23% | 40.39% | 111 | 18 | -32.20% | nan% |
| DEVELOPMENT_2024_2025 | A40_HALF_PRIMARY | 101.88% | -26.23% | 39.06% | 111 | 18 | -35.23% | 99.76% |
| DEVELOPMENT_2024_2025 | N30_HALF_NEIGHBOR | 105.67% | -26.23% | 40.04% | 111 | 18 | -31.58% | 99.86% |
| DEVELOPMENT_2024_2025 | N50_HALF_NEIGHBOR | 95.51% | -25.91% | 34.42% | 111 | 18 | -35.44% | 95.24% |
| DEVELOPMENT_2024_2025 | Z40_ZERO_SEVERITY | 100.79% | -26.23% | 37.50% | 107 | 18 | -36.80% | 100.11% |

## Promotion gates

- Bad-environment gate: `False`
- Non-worse drawdown blocks: `2/3`
- Baseline >=20% winner-entry retention: `94.87%`
- Baseline Top-20 positive-P&L capture: `90.64%`
- Ex-best20 improvement blocks: `2/3`
- Neighbor stability: `False`

## Interpretation boundary

The overlay changes only the target weight assigned to a newly selected V1 member. Missing breadth creates zero new risk and reserves the no-replacement slot. The three NAV blocks remain independent. A Phase 7 promotion would authorize robustness/falsification only, never deployment.

## Exit adaptation

Rejected. Phase 6 found no incremental conversion/capture evidence after fixed path/year/exit controls, so all V1 exits remain frozen.
