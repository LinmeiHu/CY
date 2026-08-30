# MKT-MIN-DEF-DYN-001 VWAP defense/recovery state dynamics

## Boundary

- Status: `COMPLETE_STATE_DYNAMIC_FAIL`
- Future field read: accepted VWAP defense/recovery state only.
- Future price return, volatility, industry/stock state, strategy fields, raw minutes, failed roles, post-2023 data, and CY-011 read: **none**.
- Both blocks are reused exploratory evidence, not untouched confirmation.
- A pass would be a state dynamic only, not support, accumulation, prediction, timing, habitat, causality, or a rule.

## Primary and neighboring horizons

| Horizon | Block A unadjusted | Block A partial | Block B unadjusted | Block B partial |
|---:|---:|---:|---:|---:|
| 1 | -0.044 | -0.035 | -0.016 | 0.005 |
| 3 | -0.027 | 0.004 | -0.006 | -0.058 |
| 5 | -0.029 | 0.024 | 0.065 | 0.046 |

## H=1 shape and relative challenges

| Challenge | Block A partial | Block B partial |
|---|---:|---:|
| `h1_shape__vwap_defense_recovery__median__aligned_median` | -0.024 | -0.025 |
| `h1_shape__vwap_defense_recovery__median__aligned_geometric_mean` | -0.060 | 0.041 |
| `h1_shape__vwap_defense_recovery__p40__aligned_mean` | -0.044 | 0.003 |
| `h1_shape__vwap_defense_recovery__p60__aligned_mean` | -0.049 | 0.013 |
| `h1_relative_to_all` | 0.008 | -0.009 |
| `h1_relative_rank` | -0.004 | -0.007 |

## Frozen decision

- Learned block-A sign: `-1`
- All-required state dynamic gate: `FAIL`
- Failed checks: `h1_block_a_effect, h1_block_b_effect, h1_block_b_sign, h1_block_b_sign_support, h1_block_b_magnitude, h1_shape__vwap_defense_recovery__median__aligned_median:block_a_reused_exploration:effect, h1_shape__vwap_defense_recovery__median__aligned_median:block_b_reused_validation:effect, h1_shape__vwap_defense_recovery__median__aligned_geometric_mean:block_a_reused_exploration:effect, h1_shape__vwap_defense_recovery__median__aligned_geometric_mean:block_b_reused_validation:effect, h1_shape__vwap_defense_recovery__median__aligned_geometric_mean:block_b_reused_validation:sign, h1_shape__vwap_defense_recovery__median__aligned_geometric_mean:block_b_reused_validation:sign_support, h1_shape__vwap_defense_recovery__p40__aligned_mean:block_a_reused_exploration:effect, h1_shape__vwap_defense_recovery__p40__aligned_mean:block_b_reused_validation:effect, h1_shape__vwap_defense_recovery__p40__aligned_mean:block_b_reused_validation:sign, h1_shape__vwap_defense_recovery__p40__aligned_mean:block_b_reused_validation:sign_support, h1_shape__vwap_defense_recovery__p60__aligned_mean:block_a_reused_exploration:effect, h1_shape__vwap_defense_recovery__p60__aligned_mean:block_b_reused_validation:effect, h1_shape__vwap_defense_recovery__p60__aligned_mean:block_b_reused_validation:sign, h1_shape__vwap_defense_recovery__p60__aligned_mean:block_b_reused_validation:sign_support, h1_relative_to_all:block_a_reused_exploration:effect, h1_relative_to_all:block_a_reused_exploration:sign, h1_relative_to_all:block_a_reused_exploration:sign_support, h1_relative_to_all:block_b_reused_validation:effect, h1_relative_to_all:block_b_reused_validation:sign_support, h1_relative_rank:block_a_reused_exploration:effect, h1_relative_rank:block_a_reused_exploration:sign_support, h1_relative_rank:block_b_reused_validation:effect, h1_relative_rank:block_b_reused_validation:sign_support, absolute_primary_h3:block_a_reused_exploration:effect, absolute_primary_h3:block_a_reused_exploration:sign, absolute_primary_h3:block_a_reused_exploration:sign_support, absolute_primary_h5:block_a_reused_exploration:effect, absolute_primary_h5:block_a_reused_exploration:sign, absolute_primary_h5:block_a_reused_exploration:sign_support, absolute_primary_h5:block_b_reused_validation:effect, absolute_primary_h5:block_b_reused_validation:sign, absolute_primary_h5:block_b_reused_validation:sign_support`

## Reproducibility

- Spec SHA-256: `b53452c922eff99ac9d8a367dc905b00b08335beec337e8507144b686423ecee`
- Panel SHA-256: `bfb22ae163aa68c2fc61a69ba49a749b923b269c99bcbab503591903a940f85b`
