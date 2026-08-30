# MKT-SUPPORT-GEO-001 external geometry

## Result

- Status: `COMPLETE_EXTERNAL_GEOMETRY`
- Direct support-specific coordinates: recovery_speed, recovery_volume_intensity.
- Daily/minute source roles remain distinct; no close substitution or sparse conditional rank was used.
- This is external representation geometry only, not support defense, temporal recurrence, prediction, payoff, habitat, timing, or strategy evidence.

| Role | Domain | Result |
|---|---|---|
| `signed_test_geometry` | `all_market_sessions` | REDUNDANT |
| `recovery_speed` | `tested_recovered_sessions` | PASS |
| `recovery_amplitude` | `tested_sessions` | REDUNDANT |
| `recovery_volume_intensity` | `tested_recovered_sessions` | PASS |
| `signed_test_geometry_trajectory` | `all_market_sequences` | REDUNDANT |
| `closing_level_state_trajectory` | `all_market_sequences` | REDUNDANT |

## Reproducibility

- Spec SHA-256: `c828ed0e73a652ff6979067712fbd293e43f553e4dd3683e358db06504552ba1`
- Session panel SHA-256: `6b44079e7be07d39ae6ae902096351536fed364d0f0244487d83acedbfb90cc9`
- Trajectory panel SHA-256: `34348e118782d259e77778926ee8257fb27b83dfa29a3644f39195e8248ff94a`
