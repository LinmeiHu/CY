# MKT-BREAKOUT-DYN-003 repeated-event dynamics

## Result

- Status: `COMPLETE_REPRESENTATION_PASS_NO_COMMON_DIRECTION`
- Representation-passing roles: continuation30_log_return, rejection_depth, below_level_close_fraction, loss_episode_count, reacquisition_bars, post_cross_cumulative_vwap_acceptance_fraction, post_cross_activity_ratio.
- Common-direction roles: none.
- Residual minimal roles: continuation30_log_return, rejection_depth, below_level_close_fraction, loss_episode_count, reacquisition_bars, post_cross_cumulative_vwap_acceptance_fraction, post_cross_activity_ratio.
- Rates use actual market-session gaps across qualifying crossing days; non-crossing days are absent, never zero-filled.
- Every source value is post-cross attribution. The complete trajectory is available only at 15:30 on its last included day.
- No future return, outcome, strategy field, post-2023 partition, raw minute row, or CY-011 was read.

## Role decisions

| Role | Status | Endpoint trajectories | Three-plus-event trajectories |
|---|---|---:|---:|
| continuation30_log_return | REPRESENTATION_PASS_NO_COMMON_DIRECTION | 250 | 108 |
| rejection_depth | REPRESENTATION_PASS_NO_COMMON_DIRECTION | 250 | 108 |
| below_level_close_fraction | REPRESENTATION_PASS_NO_COMMON_DIRECTION | 250 | 108 |
| loss_episode_count | REPRESENTATION_PASS_NO_COMMON_DIRECTION | 250 | 108 |
| reacquisition_bars | REPRESENTATION_PASS_NO_COMMON_DIRECTION | 171 | 58 |
| post_cross_cumulative_vwap_acceptance_fraction | REPRESENTATION_PASS_NO_COMMON_DIRECTION | 250 | 108 |
| post_cross_activity_ratio | REPRESENTATION_PASS_NO_COMMON_DIRECTION | 250 | 108 |

## Boundary

A stable or direction-annotated trajectory is not favorable acceptance, prediction, habitat usefulness, or a trading rule. Residual compression is not a latent score or synergy claim.

## Reproducibility

- Spec SHA-256: `9cc7883f92d2980c3ac9488d85f9324d079355a28814333008ed116b44295d35`
- Runner SHA-256: `6417d075e6faf58298a5a1daa44c7d93365e01a7eb4064d7293e1d224af4211f`
- Trajectory SHA-256: `e5b424752c7f9f794456bc1e80e2e7ccdf3f329db03ee0d22d2021029aa5a999`
- Stability SHA-256: `0f10b7d0d6a97c2510f054e2125273a4ba8a3627fbc3b49d67f82fd29eec511e`
- Coupling SHA-256: `5356784310455175ba94babe4df46418d2a7ea174f675fcf11a06e94f67d4d2a`
