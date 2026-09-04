# Industry-Consensus Q1 industry d5 exit V1

Status: `INDUSTRY_D5_EXIT_SCREEN_FAILED`.

This is a post-hoc development repair generated from the consumed temporal-transfer anatomy and the failed entry-veto result. It is not confirmation.

## Frozen rule

After the fifth completed holding-session close, exit the same-industry pair at the next legal open only when its PIT industry's compounded d5 equal-weight return is nonpositive. Otherwise keep the exact h20 exit.

## Sequential screen

| Block | Triggered / continued dates | Triggered / continued h20 mean | Spread | Severe triggered / continued |
|---|---:|---:|---:|---:|
| 2018-2020 | 18 / 29 | -3.849% / 7.485% | 11.335% | 25.00% / 1.72% |
| 2021-2023 | 20 / 24 | 0.487% / 7.825% | 7.339% | 10.00% / 6.25% |

Screen passed: `False`.

The frozen gate failed, so no dynamic-exit portfolio replay was run.
No alternate checkpoint, threshold, stock stop, or rescue was tested.

## Governance

The runner read only 2018--2023 market outcomes. 2024--2025 remain consumed diagnostic history and were not replayed. No 2026 market outcome or CY-011 was read.
