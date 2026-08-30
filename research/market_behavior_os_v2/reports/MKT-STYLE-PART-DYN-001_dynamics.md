# MKT-STYLE-PART-DYN-001 size-participation precursor

## Boundary

- Status: `COMPLETE_PRECURSOR_FAIL`
- Precursor gate pass: `False`
- Passing direction label: `NONE`
- Both temporal blocks reuse pre-2024 data; neither is fresh confirmation.
- Future payoff, stock selection, strategy outcomes, additional edges, post-2023 data, and CY-011 read: **none**.

## Primary and challenges

| Task | Block A median partial rho | Block B median partial rho |
|---|---:|---:|
| `primary_raw` | 0.032 | -0.033 |
| `primary_pit` | 0.032 | -0.036 |
| `primary_relative_to_all` | 0.010 | -0.036 |
| `primary_relative_rank` | -0.013 | 0.014 |
| `neighbor_raw__size_positive_participation_small20_large20` | 0.033 | -0.027 |
| `neighbor_raw__size_positive_participation_small40_large40` | 0.033 | -0.036 |
| `phase_zero_primary_raw` | 0.147 | 0.099 |

## Gate summary

- Passed checks: 18/43.
- Failed checks: `["primary_raw_block_a_effect", "primary_raw_block_b_effect", "primary_raw_block_b_sign", "primary_raw_block_b_sign_support", "primary_pit:block_a_reused:effect", "primary_pit:block_b_reused:effect", "primary_pit:block_b_reused:sign", "primary_pit:block_b_reused:sign_support", "primary_relative_to_all:block_a_reused:effect", "primary_relative_to_all:block_a_reused:sign_support", "primary_relative_to_all:block_b_reused:effect", "primary_relative_to_all:block_b_reused:sign", "primary_relative_to_all:block_b_reused:sign_support", "primary_relative_rank:block_a_reused:effect", "primary_relative_rank:block_a_reused:sign", "primary_relative_rank:block_a_reused:sign_support", "primary_relative_rank:block_b_reused:effect", "neighbor_raw__size_positive_participation_small20_large20:block_a_reused:effect", "neighbor_raw__size_positive_participation_small20_large20:block_b_reused:effect", "neighbor_raw__size_positive_participation_small20_large20:block_b_reused:sign", "neighbor_raw__size_positive_participation_small20_large20:block_b_reused:sign_support", "neighbor_raw__size_positive_participation_small40_large40:block_a_reused:effect", "neighbor_raw__size_positive_participation_small40_large40:block_b_reused:effect", "neighbor_raw__size_positive_participation_small40_large40:block_b_reused:sign", "neighbor_raw__size_positive_participation_small40_large40:block_b_reused:sign_support"]`

## Reproducibility

- Spec SHA-256: `5cffae1f3e2a74ae3eb1db53041a4bf93f0ea79ef17ec52c31f5984c95d9fc42`
- Panel SHA-256: `601bbcfc9ece8b7753a7af0792a94d5ef96a7ed9e53fb45e096b6c643d96deb3`
