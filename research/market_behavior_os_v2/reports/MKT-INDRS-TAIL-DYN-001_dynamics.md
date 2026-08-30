# MKT-INDRS-TAIL-DYN-001 residual leadership dynamics

## Boundary

- Status: `COMPLETE_0_OF_4_EXACT_EDGES_PASS`
- Evidence label: `REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION`.
- Future values are t+20 residual tail-balance/concentration states only.
- Market/industry/stock returns, named-security futures, strategies, failed roles, post-2023 data, and CY-011 read: **none**.
- Passing is exploratory state-process evidence, not confirmation, selection alpha, timing, causality, habitat, or a rule.

## Fixed temporal edges

| Edge | Raw block A | Raw block B | PIT block A | PIT block B | Phase block A | Phase block B | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| `tail_balance_nonoverlap_persistence` | 0.102 | 0.055 | -0.049 | -0.058 | 0.011 | 0.111 | FAIL |
| `concentration_nonoverlap_persistence` | 0.234 | 0.061 | 0.309 | -0.020 | 0.333 | 0.290 | FAIL |
| `concentration_to_future_tail_balance` | 0.186 | -0.265 | 0.164 | -0.220 | 0.155 | -0.164 | FAIL |
| `tail_balance_to_future_concentration` | 0.109 | -0.218 | 0.081 | -0.154 | 0.122 | -0.374 | FAIL |

## Process classification

- Tail-balance state process: `False`
- Residual-concentration state process: `False`
- Coupled tail/concentration process: `False`

## Reproducibility

- Spec SHA-256: `56a83827c7ba0bea69d611f6d0ec8778a3364cb2c14d62d444e230d839fb5bca`
- Panel SHA-256: `4d4fc15a01136a1b4e42af9c264aa76b8f853b51fb72920a5f87ac6ef81082e5`
