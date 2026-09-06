# Phase 8 — robustness and overfitting audit

EXP-P8P9-001 robustness verdict: `FAIL_NOT_ROBUST`.

This audit used only the 15 hash-frozen EXP-P7-003 ledgers. It ran no strategy replay, threshold fit, arm selection, or NAV chaining. All 2018-2025 outcomes are consumed; rolling, expanding, and LOYO results are resampling diagnostics, not untouched OOS.

## Gate summary

| Component | Pass | Key evidence |
|---|---:|---|
| Yearly stability | False | +/−/neutral years: 3/3/2 |
| Rolling 126/252 | False | positive-fraction gate requires 2/3 blocks at each horizon |
| Expanding prefixes | False | positive prefixes 2/8 |
| LOYO, no refit | False | 8 omitted-year panels |
| Regime frequency | False | causal state coverage and both-state frequency |
| Neighbor definitions | False | fixed 0.30/0.50 falsification arms |
| Exposure normalization | False | non-worse blocks 2/3 |
| Right-tail retention | True | inherited frozen winner/top-20 gate |
| Cost sensitivity | False | ledger-notional diagnostic, not an endogenous replay |
| PIT/execution | True | exact ledger and causal timestamp audit |

## Calendar-year active returns

| Year | Candidate | V1 | Delta | DD delta (+ better) |
|---:|---:|---:|---:|---:|
| 2018 | -1.16% | -3.78% | 2.62% | 2.93% |
| 2019 | 8.52% | 23.49% | -14.97% | -0.00% |
| 2020 | 3.36% | 5.27% | -1.91% | -0.41% |
| 2021 | 32.32% | 31.78% | 0.54% | 0.56% |
| 2022 | -17.29% | -17.29% | 0.00% | 0.00% |
| 2023 | 2.33% | 2.14% | 0.20% | 0.15% |
| 2024 | 49.05% | 49.05% | 0.00% | 0.00% |
| 2025 | 35.44% | 37.70% | -2.26% | 0.00% |

## Rolling windows

| Block | Sessions | Windows | Positive | Median active | Mean active |
|---|---:|---:|---:|---:|---:|
| DEVELOPMENT_2024_2025 | 126 | 359 | 13.6% | 0.00% | -0.07% |
| DEVELOPMENT_2024_2025 | 252 | 233 | 21.0% | 0.00% | -0.14% |
| EXTENDED_2018_2021 | 126 | 847 | 47.0% | -0.22% | -2.16% |
| EXTENDED_2018_2021 | 252 | 721 | 24.7% | -3.78% | -5.59% |
| HOLDOUT_O0_2022_2023 | 126 | 358 | 28.8% | 0.00% | 0.05% |
| HOLDOUT_O0_2022_2023 | 252 | 232 | 44.4% | 0.00% | 0.08% |

## Exposure, tails, and costs

The primary retains 94.87% of baseline >=20% winner entries and 90.64% of baseline Top-20 positive P&L. Exposure-normalized return is non-worse in 2/3 blocks. The only materially degraded block is 2018-2021; reduced turnover cannot close its return gap even in the fixed 50 bps ledger-notional sensitivity.

## OOS boundary

No untouched OOS exists for this newly designed rule. There is no trained model to refit in LOYO, so the eight leave-one-year-out panels omit years only from the arithmetic annual-delta summary. Walk-forward selection is therefore not feasible and is not claimed. The earlier 2022-2023 label describes a frozen V1 baseline block, not untouched OOS for V1-R.
