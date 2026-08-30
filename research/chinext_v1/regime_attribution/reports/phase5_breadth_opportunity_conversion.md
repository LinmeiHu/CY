# Phase 5 — breadth opportunity, conversion, path, and exit attribution

EXP-P5-001 uses the 399 frozen completed cycles and entry-close PIT features only. It does not replay V1, use post-exit prices, choose a breadth threshold, or simulate an overlay.

## Mechanism verdict

`AMBIGUOUS_BOTH_OPPORTUNITY_AND_CONVERSION_ASSOCIATED`. Breadth entry-opportunity support is `True`; breadth conversion support within MFE>=20% opportunities is `True`. Exit-lineage comparisons remain descriptive because no counterfactual post-exit path is available.

## Continuous/LOYO attribution

| Endpoint | Sample | N | Breadth rho | LOYO same sign |
|---|---|---:|---:|---:|
| mfe | all | 383 | 0.218 | 8/8 |
| opportunity20 | all | 383 | 0.188 | 8/8 |
| opportunity50 | all | 383 | 0.116 | 8/8 |
| round_trip_return | all | 383 | 0.073 | 8/8 |
| mae | all | 383 | -0.018 | 5/8 |
| false_breakout | all | 383 | -0.147 | 8/8 |
| severe_loss | all | 383 | 0.036 | 7/8 |
| extreme_loss | all | 383 | 0.030 | 8/8 |
| return_5d | all | 284 | 0.043 | 7/8 |
| return_10d | all | 183 | 0.038 | 7/8 |
| return_20d | all | 86 | 0.223 | 8/8 |
| conversion20_within_opportunity | opportunity20 | 80 | 0.035 | 6/8 |
| capture_ratio_opportunity20 | opportunity20 | 80 | 0.149 | 8/8 |
| giveback_from_peak | opportunity20 | 80 | -0.113 | 8/8 |
| conversion50_within_opportunity | opportunity50 | 30 | 0.059 | 6/8 |

## Coarse feature-only breadth terciles

| Breadth | N | MFE mean | Return mean | Opportunity20 | Converted20 | False breakout | Severe loss |
|---|---:|---:|---:|---:|---:|---:|---:|
| LOW | 129 | 0.078 | -0.020 | 0.101 | 0.023 | 0.659 | 0.101 |
| MIDDLE | 127 | 0.170 | 0.033 | 0.228 | 0.110 | 0.504 | 0.110 |
| HIGH | 127 | 0.243 | 0.074 | 0.299 | 0.150 | 0.449 | 0.126 |

## Opportunity conversion

| Opportunity | Count | Converted | Conversion rate |
|---|---:|---:|---:|
| MFE>=20% | 84 | 39 | 0.464 |
| MFE>=50% | 32 | 15 | 0.469 |

The conversion denominator is fixed by MFE, not selected from breadth. `capture_ratio` is reported only for MFE>=20% cycles and is never clipped. Early 5/10/20-session returns remain missing when the actual frozen holding path ended earlier.

## Exit lineage

| Exit reason | N | Opportunity20 | Converted20 within opportunity | Median MFE | Median return | Median giveback |
|---|---:|---:|---:|---:|---:|---:|
| INDIVIDUAL_MA30_X2_AND_SET_REMOVAL | 95 | 16 | 0.125 | 0.062 | -0.061 | 0.095 |
| MARKET_EMERGENCY_X0.96 | 14 | 7 | 0.286 | 0.210 | 0.018 | 0.166 |
| MARKET_MA20_X2 | 283 | 58 | 0.603 | 0.061 | -0.007 | 0.058 |
| SET_REMOVAL | 7 | 3 | 0.000 | 0.094 | -0.055 | 0.176 |

## Interpretation boundary

Breadth can be called an entry-opportunity descriptor only if its MFE/opportunity association survives the frozen LOYO gate. Conversion and exit results say whether that opportunity is harvested; they do not prove an exit caused the observed return. Calendar cohorts are descriptive diagnostics, never year/quarter parameters.

## Strategy candidate

None in Phase 5. This mechanism experiment does not authorize a gate, exposure overlay, or exit adaptation.
