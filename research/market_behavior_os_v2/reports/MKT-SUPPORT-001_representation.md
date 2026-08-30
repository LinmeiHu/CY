# MKT-SUPPORT-001 objective support representation

## Result

- Status: `COMPLETE_REPRESENTATIONS_FROZEN`
- Primary continuous 20-session tests: 117 market rows.
- Conditional recovery trajectories: `NOT_ESTIMABLE_SUPPORT` on 29 sequences versus 30 required.
- Retained direct session roles: signed_test_geometry, recovery_speed, recovery_amplitude, recovery_volume_intensity.
- PIT historical normalization is unavailable from isolated blocks and was not fabricated.
- This is representation quality only; no touch is called defense and no payoff, habitat, timing, or strategy field was read.

## Session roles

| Role | Pre-redundancy | Final status |
|---|---:|---|
| `signed_test_geometry` | PASS | `RETAINED` |
| `time_beyond_level` | FAIL | `FAILED_PRE_REDUNDANCY_GATES` |
| `test_recurrence` | FAIL | `FAILED_PRE_REDUNDANCY_GATES` |
| `closing_level_state` | PASS | `REDUNDANT` |
| `recovery_speed` | PASS | `RETAINED` |
| `recovery_amplitude` | PASS | `RETAINED` |
| `recovery_volume_intensity` | PASS | `RETAINED` |

## Five-day trajectory roles

| Role | Ordinal coverage | Slope/endpoint rho | Slope/ordinal rho | Result |
|---|---:|---:|---:|---|
| `signed_test_geometry` | 240 | 0.9742119920997069 | 0.9122427819979952 | PASS |
| `time_beyond_level` | 60 | 0.733630729974082 | 0.8381427117748959 | FAIL |
| `test_recurrence` | 64 | 0.8853038727892728 | 0.8813233360385905 | FAIL |
| `closing_level_state` | 240 | 0.9613335133133877 | 0.9183188594965042 | PASS |

## Reproducibility

- Spec SHA-256: `4c58431daa1a21268eedcb8d6ebc306aadfb4aac89f8c9218e956fc91e36bef4`
- Session panel SHA-256: `501194a74e30c523d100ac76edc8a4984821523a23063e89a441834e4194b23e`
- Trajectory panel SHA-256: `668005f76c383a4dc8ae9e9735f25c328a54a7ebf950482a82c430e0291bfae0`
