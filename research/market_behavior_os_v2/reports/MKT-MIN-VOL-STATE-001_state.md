# MKT-MIN-VOL-STATE-001 ordinal path states

## Boundary

- Status: `COMPLETE_EXACT_STATE_ARCHITECTURE_FAIL`
- Rows: 10,696; 2018-07-03..2023-12-29.
- Current state is available at 15:30; dwell/transitions are later post-state attribution, never entry predictors.
- Raw minutes, failed representations, future returns, strategy outcomes, and CY-011 read: **none**.
- Rising/falling/flat are ordinal path labels, not economic expansion/contraction or trading states.

## Core gates

- Valid group/year cells: FAIL.
- Primary state recurrence: PASS.
- Nine-cell path-by-level recurrence: FAIL.
- Completed-run/dwell support: PASS.

## Definition-neighbor state agreement

| Neighbor | Median kappa | Minimum kappa | Median macro Jaccard | Minimum macro Jaccard | Gate |
|---|---:|---:|---:|---:|---|
| `neighbor_all_pairs` | 0.425 | 0.404 | 0.423 | 0.407 | FAIL |
| `neighbor_rank_time` | 0.275 | 0.266 | 0.305 | 0.300 | FAIL |

## Transition stability

| Neighbor | Median total variation | Maximum total variation | Gate |
|---|---:|---:|---|
| `neighbor_all_pairs` | 0.469 | 0.479 | FAIL |
| `neighbor_rank_time` | 0.611 | 0.623 | FAIL |

## Reproducibility

- Spec SHA-256: `bf3c5e7aa5443148a35d2afe2c3588e7b206c6d96b4f22d5cd074bb42b5f27f5`
- Output panel SHA-256: `d2b23700c9f81145192ced8c956784e2fd2bc822187f11082558b029dbbaa3f7`
