# MKT-INDRS-ROT-001 rotation-persistence falsification

## Boundary

- Status: `COMPLETE_ROTATION_PERSISTENCE_FAILS_FALSIFICATION_2_OF_3_PASS`
- Evidence label: `CONSUMED_EXPLORATORY_FALSIFICATION_NOT_CONFIRMATION`.
- Both 2019-2021 and 2022-2023 were already consumed before these post-result hypotheses.
- Market/stock returns, selection outcomes, strategy fields, failed roles, post-2023 data, and CY-011 read: **none**.
- Passing all three would remain exploratory state-process support, not confirmation, usefulness, causality, or a rule.

## Fixed replications

| Replication | Raw block A | Raw block B | PIT block A | PIT block B | Phase block A | Phase block B | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| `delayed_spearman_persistence` | 0.023 | -0.111 | 0.052 | -0.071 | 0.051 | -0.089 | FAIL |
| `kendall_next_block_persistence` | 0.262 | 0.212 | 0.242 | 0.235 | 0.233 | 0.145 | PASS |
| `displacement_next_block_persistence` | 0.266 | 0.207 | 0.264 | 0.229 | 0.238 | 0.154 | PASS |

## Reproducibility

- Spec SHA-256: `1af3e49717f5055deb2b7ac6bc95e191b6eaee749fc477d646997acac176610e`
- Panel SHA-256: `37043081bc43ac15880740753bbe04173d16424e3b1e78ebd28bb057e874d499`
