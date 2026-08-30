# MKT-MIN-001 market intraday representation freeze

Decision: `COMPLETE_LEVEL_REPRESENTATIONS_FROZEN_FIVE_DAY_TRAJECTORY_PRIMARIES_FAIL`.

## Boundary

- Required raw rows: 1,473,342,173.
- Final causal security-sessions: 5,814,290.
- Daily / five-day market rows: 11,656 / 11,624.
- Strategy membership, outcomes, future returns, post-entry paths, and CY-011 read: **none**.
- This freezes representation quality only; it establishes no supply/demand mechanism, habitat, forecast, or strategy.

## Representation gates

| Descriptor | Family | Level neighbor | Trajectory aggregation | Trajectory shape | ST sensitivity | Level | Trajectory | Level minimal | Trajectory minimal |
|---|---|---:|---:|---:|---:|---|---|---|---|
| open_close_log_return | price_path | 0.995 | 0.997 | 0.427 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| morning_log_return | price_path | 0.992 | 0.995 | 0.409 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| afternoon_log_return | price_path | 0.996 | 0.996 | 0.404 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| final30_log_return | price_path | 0.969 | 0.981 | 0.440 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| high_time_fraction | price_path | 0.951 | 0.938 | 0.379 | 1.000 | PASS | FAIL | redundant_with:open_close_log_return | trajectory_gate_failed |
| low_time_fraction | price_path | 0.942 | 0.898 | 0.438 | 0.999 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| close_location | price_path | 0.998 | 0.996 | 0.445 | 1.000 | PASS | FAIL | redundant_with:open_close_log_return | trajectory_gate_failed |
| signed_directional_efficiency | price_path | 0.997 | 0.998 | 0.439 | 1.000 | PASS | FAIL | redundant_with:open_close_log_return | trajectory_gate_failed |
| path_r2 | price_path | 0.996 | 0.992 | 0.416 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| close_vs_vwap_log | vwap_structure | 0.997 | 0.998 | 0.419 | 1.000 | PASS | FAIL | redundant_with:open_close_log_return | trajectory_gate_failed |
| time_above_vwap_fraction | vwap_structure | 0.988 | 0.984 | 0.417 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| volume_above_vwap_fraction | vwap_structure | 0.988 | 0.990 | 0.425 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| vwap_halfday_log_slope | vwap_structure | 0.997 | 0.998 | 0.418 | 1.000 | PASS | FAIL | redundant_with:open_close_log_return | trajectory_gate_failed |
| vwap_recovery_count | vwap_structure | 0.925 | 0.922 | 0.428 | 0.993 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| longest_below_vwap_fraction | vwap_structure | 0.974 | 0.970 | 0.410 | 0.999 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| late_vwap_acceptance_fraction | vwap_structure | 0.970 | 0.963 | 0.448 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| downside_excursion | selling_pressure | 0.995 | 0.997 | 0.444 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| downside_realized_volatility | selling_pressure | 0.995 | 0.995 | 0.496 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| down_minute_volume_share | selling_pressure | 0.992 | 0.994 | 0.451 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| selloff_duration_fraction | selling_pressure | 0.545 | 0.351 | 0.388 | 0.906 | FAIL | FAIL | level_gate_failed | trajectory_gate_failed |
| recovery_speed_30bar | selling_pressure | 0.959 | 0.943 | 0.424 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| upside_excursion | buying_pressure | 0.990 | 0.993 | 0.434 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| up_minute_volume_share | buying_pressure | 0.992 | 0.991 | 0.438 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| positive_minute_fraction | buying_pressure | 0.981 | 0.964 | 0.454 | 0.986 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| new_intraday_high_fraction | buying_pressure | 0.956 | 0.957 | 0.413 | 0.995 | PASS | FAIL | redundant_with:morning_log_return | trajectory_gate_failed |
| intraday_log_range | volatility_oscillation | 0.994 | 0.994 | 0.469 | 1.000 | PASS | FAIL | redundant_with:downside_realized_volatility | trajectory_gate_failed |
| minute_realized_volatility | volatility_oscillation | 0.994 | 0.994 | 0.514 | 1.000 | PASS | FAIL | redundant_with:downside_realized_volatility | trajectory_gate_failed |
| vwap_deviation_std | volatility_oscillation | 0.993 | 0.994 | 0.445 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| vwap_crossing_fraction | volatility_oscillation | 0.967 | 0.965 | 0.427 | 0.996 | PASS | FAIL | redundant_with:vwap_recovery_count | trajectory_gate_failed |
| opening30_volume_share | volume_path | 0.995 | 0.993 | 0.425 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| afternoon_volume_share | volume_path | 0.995 | 0.994 | 0.409 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| closing30_volume_share | volume_path | 0.995 | 0.995 | 0.419 | 1.000 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| minute_volume_concentration | volume_path | 0.986 | 0.983 | 0.454 | 0.999 | PASS | FAIL | ACCEPT | trajectory_gate_failed |
| auction_to_continuous_open_log_return | auction_relation | 0.474 | 0.428 | 0.288 | 0.976 | FAIL | FAIL | level_gate_failed | trajectory_gate_failed |

## Outcome-blind compression

Minimal nonredundant same-session level roles: `open_close_log_return, morning_log_return, afternoon_log_return, final30_log_return, low_time_fraction, path_r2, time_above_vwap_fraction, volume_above_vwap_fraction, vwap_recovery_count, longest_below_vwap_fraction, late_vwap_acceptance_fraction, downside_excursion, downside_realized_volatility, down_minute_volume_share, recovery_speed_30bar, upside_excursion, up_minute_volume_share, positive_minute_fraction, vwap_deviation_std, opening30_volume_share, afternoon_volume_share, closing30_volume_share, minute_volume_concentration`.

Minimal nonredundant five-day trajectory roles: `NONE`.

Same-session level absolute-Spearman components at 0.85: `[['afternoon_log_return', 'close_location', 'close_vs_vwap_log', 'high_time_fraction', 'late_vwap_acceptance_fraction', 'low_time_fraction', 'morning_log_return', 'new_intraday_high_fraction', 'open_close_log_return', 'signed_directional_efficiency', 'upside_excursion', 'vwap_halfday_log_slope'], ['afternoon_volume_share'], ['auction_to_continuous_open_log_return'], ['closing30_volume_share'], ['down_minute_volume_share'], ['downside_excursion'], ['downside_realized_volatility', 'intraday_log_range', 'minute_realized_volatility', 'vwap_deviation_std'], ['final30_log_return'], ['longest_below_vwap_fraction'], ['minute_volume_concentration'], ['opening30_volume_share'], ['path_r2'], ['positive_minute_fraction'], ['recovery_speed_30bar'], ['selloff_duration_fraction'], ['time_above_vwap_fraction'], ['up_minute_volume_share'], ['volume_above_vwap_fraction'], ['vwap_crossing_fraction', 'vwap_recovery_count']]`.

Five-day trajectory absolute-Spearman components at 0.85: `[['afternoon_log_return', 'close_location', 'close_vs_vwap_log', 'down_minute_volume_share', 'downside_excursion', 'late_vwap_acceptance_fraction', 'morning_log_return', 'new_intraday_high_fraction', 'open_close_log_return', 'signed_directional_efficiency', 'up_minute_volume_share', 'upside_excursion', 'vwap_halfday_log_slope'], ['afternoon_volume_share'], ['auction_to_continuous_open_log_return'], ['closing30_volume_share'], ['downside_realized_volatility', 'intraday_log_range', 'minute_realized_volatility', 'vwap_deviation_std'], ['final30_log_return'], ['high_time_fraction'], ['longest_below_vwap_fraction'], ['low_time_fraction'], ['minute_volume_concentration'], ['opening30_volume_share'], ['path_r2'], ['positive_minute_fraction'], ['recovery_speed_30bar'], ['selloff_duration_fraction'], ['time_above_vwap_fraction'], ['volume_above_vwap_fraction'], ['vwap_crossing_fraction', 'vwap_recovery_count']]`.

Components diagnose redundant manifestations only. They do not prove latent causal mechanisms. Failed exact trajectories remain representation failures; their broader economic families remain open.

## PIT and portability

Every group has 1453 five-day observations. Causal expanding/trailing percentiles and robust z-scores begin only at observation 504; post-warm-up percentile coverage is 1.000. Absolute p40/median/p60 values remain primary, with separate view-minus-ALL_A and view-rank coordinates.

## Unavailable concepts

Objective cross-day support/resistance defense and breakout-line acceptance remain unavailable because no action-safe cross-day raw minute level is registered. OHLCV cannot identify aggressor side, absorption, queues, hidden liquidity, or participants.

## Reproducibility

- Daily input SHA-256: `bdbb3cb9b603514f4fab5783fb6c807f42c91e15388d2f6bb6f9418be6c4a701`.
- Trajectory panel SHA-256: `89d3e33bfc3eb64d91fe05e6f66f988af1890bf6e04c13b14f933dbf75eeb626`.
- Analysis spec SHA-256: `358e358f3daef94bd8e2f42d60f38672f4f450db368494e0291465cb384bde9a`.
