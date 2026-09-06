# Phase 7 — Robustness and Falsification

OC-EXP-P7-001: **PASS** as a completed audit. The strategy-design gate is **FAIL**.

## Neighboring definitions

| Family | Threshold | N | breadth rho | Year + / - | LOYO + / - |
|---|---:|---:|---:|---:|---:|
| opportunity | 0.15 | 387 | 0.231 | 7 / 0 | 8 / 0 |
| right_tail_terminal | 0.15 | 387 | 0.153 | 6 / 0 | 8 / 0 |
| opportunity | 0.20 | 387 | 0.196 | 7 / 0 | 8 / 0 |
| right_tail_terminal | 0.20 | 387 | 0.138 | 5 / 1 | 8 / 0 |
| opportunity | 0.25 | 387 | 0.169 | 6 / 0 | 8 / 0 |
| right_tail_terminal | 0.25 | 387 | 0.128 | 5 / 1 | 8 / 0 |
| extreme_opportunity | 0.40 | 387 | 0.121 | 6 / 0 | 8 / 0 |
| extreme_opportunity | 0.50 | 387 | 0.109 | 6 / 0 | 8 / 0 |
| extreme_opportunity | 0.60 | 387 | 0.073 | 4 / 1 | 8 / 0 |
| severe_loss | -0.08 | 387 | 0.109 | 3 / 5 | 8 / 0 |
| severe_loss | -0.10 | 387 | 0.088 | 4 / 3 | 8 / 0 |
| severe_loss | -0.12 | 387 | 0.071 | 2 / 3 | 8 / 0 |
| false_breakout | 0.08 | 387 | -0.129 | 3 / 5 | 0 / 8 |
| false_breakout | 0.10 | 387 | -0.113 | 3 / 5 | 0 / 8 |
| false_breakout | 0.12 | 387 | -0.095 | 4 / 4 | 0 / 8 |

Across 135 causal entry-feature neighboring-definition tests, `0` pass the combined gate. Across 27 Breadth x stock-feature interactions, `0` pass.

## Rolling signs

| Relation | Positive | Negative | Valid |
|---|---:|---:|---:|
| breadth_mfe | 13 | 0 | 13 |
| breadth_opportunity20 | 13 | 0 | 13 |
| breadth_terminal_return | 9 | 4 | 13 |
| breadth_capture | 7 | 4 | 11 |

## Extreme-trade sensitivity

| Relation | Remove 0 | Remove 1 | Remove 5 | Remove 10 | Remove 20 |
|---|---:|---:|---:|---:|---:|
| breadth_mfe_remove_top_mfe | 0.245 | 0.245 | 0.247 | 0.236 | 0.231 |
| breadth_terminal_remove_top_abs_pnl | 0.022 | 0.021 | 0.022 | 0.006 | -0.016 |
| rs_mfe_remove_top_mfe | 0.137 | 0.131 | 0.126 | 0.109 | 0.103 |
| box_terminal_remove_top_abs_pnl | -0.104 | -0.111 | -0.105 | -0.109 | -0.114 |
| breadth_capture_remove_top_mfe | 0.130 | 0.130 | 0.126 | 0.142 | 0.121 |

## Strategy-design gate

- Breadth exposure overlay: frozen A40 rejected.
- Causal stock selection: 0/54 primary, 0/135 neighboring, and 0/27 interaction tests pass the full gate.
- Path-based exits: economic leakage is large but the strongest fields are future outcomes; executable ablations are mixed and winner-hold fails OOS.
- PIT/coverage: 399/399 trade lineage, no imputation, 387/399 entry-breadth coverage, 81/84 opportunity-breadth coverage, and 398/399 post-exit20 coverage.

**No minimum candidate is authorized.** The robust result is explanatory: breadth supplies opportunities, while conversion leakage has no decision-time structure that passes the full gate.
