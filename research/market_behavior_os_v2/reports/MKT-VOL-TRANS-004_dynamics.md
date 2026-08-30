# MKT-VOL-TRANS-004 continuous volatility transition

## Boundary

- Status: `COMPLETE_0_OF_3_TRANSITION_CLAIMS_PASS`
- Evidence label: `REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION`.
- Response: t+25 five-session RV20 change; current/response complete source spans share no return interval.
- Future price returns, strategy fields, failed roles, post-2023 data, and CY-011 read: **none**.
- State dynamics/modifiers are not strategy habitats, timing, causality, or rules.

## Baseline

| Raw A | Raw B | PIT A | PIT B | Phase A | Phase B | Gate |
|---:|---:|---:|---:|---:|---:|---|
| 0.051 | 0.094 | 0.111 | 0.088 | 0.158 | -0.275 | FAIL |

## Habitat modifiers

| Modifier | Primary raw A | Primary raw B | Primary PIT A | Primary PIT B | Neighbor raw A | Neighbor raw B | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| `direction` | 0.004 | 0.340 | 0.101 | 0.345 | 0.025 | 0.330 | FAIL |
| `discovery` | 0.194 | 0.064 | 0.192 | 0.075 | 0.228 | 0.101 | FAIL |

## Reproducibility

- Spec SHA-256: `21145136eeb09369b755aad7fca591dcd280e3577159d7c65c5c1362bdacbb43`
- Panel SHA-256: `cfc44d72fbfa1a62fc7db2cafa0efba1ca1dec1cb6bbc44b66d689d9cd9f3c1a`
