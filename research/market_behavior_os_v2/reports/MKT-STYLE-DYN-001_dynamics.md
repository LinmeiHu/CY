# MKT-STYLE-DYN-001 circulating-size transition dynamics

## Boundary

- Status: `COMPLETE_STATE_DYNAMIC_FAIL`
- State dynamic gate pass: `False`
- Passing process label: `NONE`
- Both temporal blocks reuse pre-2024 data; neither is fresh confirmation.
- Future market payoff, stock selection, strategy outcomes, post-2023 data, and CY-011 read: **none**.

## Primary and challenges

| Task | Block A median partial rho | Block B median partial rho |
|---|---:|---:|
| `primary_raw_h5` | 0.179 | 0.053 |
| `primary_pit_h5` | 0.181 | 0.055 |
| `primary_relative_to_all_h5` | 0.077 | 0.187 |
| `primary_relative_rank_h5` | 0.022 | 0.188 |
| `neighbor_raw_h3` | 0.148 | 0.058 |
| `neighbor_raw_h10` | 0.130 | 0.049 |
| `phase_zero_primary_raw_h5` | 0.181 | -0.078 |

## Gate summary

- Passed checks: 35/43.
- Failed checks: `["primary_raw_block_b_effect", "primary_raw_block_b_magnitude", "phase_zero_primary_raw_h5:block_b_reused:sign", "phase_zero_primary_raw_h5:block_b_reused:sign_support", "primary_pit_h5:block_b_reused:effect", "primary_relative_rank_h5:block_a_reused:effect", "neighbor_raw_h3:block_b_reused:effect", "neighbor_raw_h10:block_b_reused:effect"]`

## Reproducibility

- Spec SHA-256: `150de73b4a6c3c56027d61e63791636ede2c75e9e57785f7981263290a53a3e7`
- Panel SHA-256: `067d16578205dfcddc5a94d161232fdc27d451c09dd89a8c370a61f23fb4aa2b`
