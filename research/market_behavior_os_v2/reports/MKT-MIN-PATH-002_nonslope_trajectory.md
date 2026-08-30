# MKT-MIN-PATH-002 non-slope five-day intraday trajectories

## Boundary

- Status: `COMPLETE_1_OF_36_REPRESENTATIONS_PASS_1_MINIMAL`
- Output: 11,624 rows, 2018-01-08..2023-12-29.
- Raw minute rows, OLS/endpoint/precomputed-shape fields, outcomes, strategy fields, and CY-011 read: **none**.
- Stable shapes are trajectory descriptors, not supply/demand mechanisms or usefulness.

## Operator results

| Operator | Attempted | Representation pass | Minimal accepted |
|---|---:|---:|---:|
| ordinal_progression | 12 | 1 | 1 |
| signed_reversal | 12 | 0 | 0 |
| curvature | 12 | 0 | 0 |

Minimal nonredundant roles: `minute_realized_volatility__ordinal_progression`.

## Role gates

| Role | Worst definition rho | Worst aggregation rho | ST rho | Level rho | Gate | Disposition |
|---|---:|---:|---:|---:|---|---|
| `downside_excursion__ordinal_progression` | 0.548 | 0.902 | 0.985 | 0.375 | FAIL | representation_gate_failed |
| `downside_excursion__signed_reversal` | 0.316 | 0.960 | 0.993 | 0.295 | FAIL | representation_gate_failed |
| `downside_excursion__curvature` | 0.426 | 0.997 | 1.000 | 0.335 | FAIL | representation_gate_failed |
| `down_minute_volume_share__ordinal_progression` | 0.585 | 0.892 | 0.988 | 0.410 | FAIL | representation_gate_failed |
| `down_minute_volume_share__signed_reversal` | 0.288 | 0.944 | 0.985 | 0.288 | FAIL | representation_gate_failed |
| `down_minute_volume_share__curvature` | 0.354 | 0.995 | 1.000 | 0.310 | FAIL | representation_gate_failed |
| `longest_below_vwap_fraction__ordinal_progression` | 0.522 | 0.778 | 0.980 | 0.371 | FAIL | representation_gate_failed |
| `longest_below_vwap_fraction__signed_reversal` | 0.230 | 0.891 | 0.984 | 0.337 | FAIL | representation_gate_failed |
| `longest_below_vwap_fraction__curvature` | 0.335 | 0.977 | 0.999 | 0.395 | FAIL | representation_gate_failed |
| `recovery_speed_30bar__ordinal_progression` | 0.596 | 0.646 | 0.978 | 0.404 | FAIL | representation_gate_failed |
| `recovery_speed_30bar__signed_reversal` | 0.339 | 0.832 | 0.990 | 0.263 | FAIL | representation_gate_failed |
| `recovery_speed_30bar__curvature` | 0.436 | 0.941 | 1.000 | 0.328 | FAIL | representation_gate_failed |
| `late_vwap_acceptance_fraction__ordinal_progression` | 0.602 | 0.879 | 0.994 | 0.486 | FAIL | representation_gate_failed |
| `late_vwap_acceptance_fraction__signed_reversal` | 0.312 | 0.914 | 0.996 | 0.398 | FAIL | representation_gate_failed |
| `late_vwap_acceptance_fraction__curvature` | 0.288 | 0.965 | 1.000 | 0.366 | FAIL | representation_gate_failed |
| `close_location__ordinal_progression` | 0.524 | 0.939 | 0.990 | 0.430 | FAIL | representation_gate_failed |
| `close_location__signed_reversal` | 0.235 | 0.974 | 0.996 | 0.339 | FAIL | representation_gate_failed |
| `close_location__curvature` | 0.306 | 0.997 | 1.000 | 0.371 | FAIL | representation_gate_failed |
| `positive_minute_fraction__ordinal_progression` | 0.667 | 0.845 | 0.907 | 0.196 | FAIL | representation_gate_failed |
| `positive_minute_fraction__signed_reversal` | 0.281 | 0.872 | 0.907 | 0.139 | FAIL | representation_gate_failed |
| `positive_minute_fraction__curvature` | 0.377 | 0.964 | 0.979 | 0.163 | FAIL | representation_gate_failed |
| `new_intraday_high_fraction__ordinal_progression` | 0.652 | 0.885 | 0.982 | 0.464 | FAIL | representation_gate_failed |
| `new_intraday_high_fraction__signed_reversal` | 0.311 | 0.896 | 0.983 | 0.329 | FAIL | representation_gate_failed |
| `new_intraday_high_fraction__curvature` | 0.421 | 0.961 | 0.995 | 0.363 | FAIL | representation_gate_failed |
| `intraday_log_range__ordinal_progression` | 0.644 | 0.861 | 0.985 | 0.281 | FAIL | representation_gate_failed |
| `intraday_log_range__signed_reversal` | 0.361 | 0.941 | 0.989 | 0.165 | FAIL | representation_gate_failed |
| `intraday_log_range__curvature` | 0.516 | 0.994 | 1.000 | 0.246 | FAIL | representation_gate_failed |
| `minute_realized_volatility__ordinal_progression` | 0.711 | 0.868 | 0.968 | 0.246 | PASS | ACCEPT |
| `minute_realized_volatility__signed_reversal` | 0.437 | 0.928 | 0.984 | 0.081 | FAIL | representation_gate_failed |
| `minute_realized_volatility__curvature` | 0.560 | 0.992 | 1.000 | 0.151 | FAIL | representation_gate_failed |
| `vwap_deviation_std__ordinal_progression` | 0.596 | 0.873 | 0.979 | 0.300 | FAIL | representation_gate_failed |
| `vwap_deviation_std__signed_reversal` | 0.288 | 0.940 | 0.992 | 0.192 | FAIL | representation_gate_failed |
| `vwap_deviation_std__curvature` | 0.466 | 0.994 | 1.000 | 0.271 | FAIL | representation_gate_failed |
| `minute_volume_concentration__ordinal_progression` | 0.581 | 0.789 | 0.957 | 0.281 | FAIL | representation_gate_failed |
| `minute_volume_concentration__signed_reversal` | 0.311 | 0.898 | 0.972 | 0.180 | FAIL | representation_gate_failed |
| `minute_volume_concentration__curvature` | 0.443 | 0.981 | 0.999 | 0.217 | FAIL | representation_gate_failed |

## Reproducibility

- Spec SHA-256: `161b4bb79795e525940eb6d69d581db22ec1500a025b39b6bd586066ac6bf70c`
- Daily input SHA-256: `bdbb3cb9b603514f4fab5783fb6c807f42c91e15388d2f6bb6f9418be6c4a701`
- Source trajectory SHA-256: `89d3e33bfc3eb64d91fe05e6f66f988af1890bf6e04c13b14f933dbf75eeb626`
- Output panel SHA-256: `d0a396a9d3788074b483522f81b1f24ea4d6eab339c058f6839e86bb7a589ec0`
