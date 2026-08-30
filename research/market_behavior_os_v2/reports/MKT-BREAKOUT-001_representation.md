# MKT-BREAKOUT-001 same-session representation

## Result

- Status: `COMPLETE_REPRESENTATION_PASS`
- Internally stable roles: continuation30_log_return, follow_through_excursion, rejection_depth, below_level_close_fraction, loss_episode_count, reacquisition_bars, closing_acceptance_margin, post_cross_cumulative_vwap_acceptance_fraction, post_cross_activity_ratio, above_level_close_episode_count.
- Externally distinct before role compression: continuation30_log_return, rejection_depth, below_level_close_fraction, loss_episode_count, reacquisition_bars, post_cross_cumulative_vwap_acceptance_fraction, post_cross_activity_ratio, above_level_close_episode_count.
- Minimal retained roles: continuation30_log_return, rejection_depth, below_level_close_fraction, loss_episode_count, reacquisition_bars, post_cross_cumulative_vwap_acceptance_fraction, post_cross_activity_ratio.
- Absolute values use unchanged semantics across 2018--2023. The 48 isolated blocks do not support PIT historical normalization or a full contemporaneous relative rank.
- Every +5/+15/+30/+60 and end-of-session value is post-cross attribution available only after its completed bar; the full artifact is available at 15:30.
- No future return, outcome, strategy field, post-2023 partition, or CY-011 was read. Representation quality is not breakout usefulness.

## Role decisions

| Role | Status | Domain rows |
|---|---|---:|
| continuation30_log_return | REPRESENTATION_PASS_DISTINCT | 899 |
| follow_through_excursion | REPRESENTATION_PASS_EXTERNAL_REDUNDANT | 899 |
| rejection_depth | REPRESENTATION_PASS_DISTINCT | 899 |
| below_level_close_fraction | REPRESENTATION_PASS_DISTINCT | 899 |
| loss_episode_count | REPRESENTATION_PASS_DISTINCT | 899 |
| reacquisition_bars | REPRESENTATION_PASS_DISTINCT | 641 |
| closing_acceptance_margin | REPRESENTATION_PASS_EXTERNAL_REDUNDANT | 964 |
| post_cross_cumulative_vwap_acceptance_fraction | REPRESENTATION_PASS_DISTINCT | 899 |
| post_cross_activity_ratio | REPRESENTATION_PASS_DISTINCT | 899 |
| above_level_close_episode_count | REPRESENTATION_PASS_ROLE_REDUNDANT | 899 |

## Reproducibility

- Spec SHA-256: `f314165c8cfaefe9cb0ba761dc8ced6884abd192d36481a8d740f2c0a592821f`
- Runner SHA-256: `ce1ea4e67f7cda80541c4d8b3a34d056ecb83d564dba5ff2809a239a9a3891d6`
- Panel SHA-256: `e67ac766ac8ad63b6f95309e08a70cf5d0daca3450159adc45de99ef2faa1b99`
- Stability SHA-256: `044fb279f9fc9386b069cae9f59ec23ec0592bf94330b693909f8907cfe515af`
- Geometry SHA-256: `56cf578c147b34944ae95d3906aff0c84a632dac9073a9ef5e5919bafd2c3f01`
