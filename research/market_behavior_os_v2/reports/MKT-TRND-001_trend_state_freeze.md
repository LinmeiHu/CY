# MKT-TRND-001 strategy-independent trend-state freeze

## Contract result

- Status: `PASS_STRATEGY_INDEPENDENT_TREND_REPRESENTATION_FREEZE`
- Research window: `2010-06-01` through `2023-12-29`.
- Indices: 6; rows: 19,569.
- Source OHLC rows failed closed: 21.
- Strategy outcomes, trades, future returns, MFE, MAE, exits, and duration fields read: **none**.
- Minimal nonredundant roles: `direction`.

## Representation gates

| Role | Primary | Raw coverage | Worst neighbor median rho | PIT expanding | PIT 3y pct | PIT robust z | Relative | Gate | Minimal panel |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| direction | `direction_return_60` | 0.998 | 0.779 | 0.998 | 0.998 | 0.998 | 0.995 | PASS | ACCEPT |
| quality | `quality_efficiency_60` | 0.973 | 0.534 | 0.975 | 0.975 | 0.975 | 0.971 | FAIL | construction_gate_failed |
| age | `age_same_side_ma60` | 0.974 | 0.523 | 0.975 | 0.975 | 0.975 | 0.971 | FAIL | construction_gate_failed |
| transition | `transition_20_vs_60` | 0.997 | 0.626 | 0.996 | 0.996 | 0.996 | 0.994 | FAIL | construction_gate_failed |
| strength | `strength_abs_ma60` | 0.974 | 0.820 | 0.975 | 0.975 | 0.975 | 0.971 | FAIL | construction_gate_failed |
| alignment | `alignment_20_60_120` | 0.958 | 0.876 | 0.960 | 0.960 | 0.795 | 0.960 | FAIL | construction_gate_failed |

## Interpretation boundary

This experiment freezes representations of the market itself. It does not show that any state predicts returns or that any strategy belongs in a state. Roles excluded for construction instability, coverage, or redundancy cannot be advertised as independent dimensions from this construction.

The absolute values remain primary. Causal PIT percentiles/z-scores and same-date cross-index ranks are separate coordinates, not replacements for absolute state.

Quality, age, and transition fail their fixed neighboring-horizon stability gates. Strength and alignment pass neighboring stability but miss the exact raw-coverage gate after strict source-row quarantine; they are data-contract-limited, not mechanistically rejected. Alignment's discrete primary also has zero rolling MAD often enough that robust-z coverage is 0.795, correctly remaining missing.

The audit quarantines 21 exact OHLC ordering violations. It applies no tolerance even where the mismatch is 0.001, because the source does not establish which OHLC coordinate is correct.

## Reproducibility

- Spec SHA-256: `865b5d22c439c1741a299fd40bc0e3a352701bf73b616199b91cda5c374a3608`
- QD-003 manifest SHA-256: `d847419443b2563c1904790f986ef8980dc37d688318fadb3858b3251d84972f`
- Panel SHA-256: `fd933284bec590b5dee15549b176db973bebc07c8ee71edab64249c9b2e26e5a`

## Appendix: quarantined source rows

| Index | Date | Open | High | Low | Close | Reason |
|---|---|---:|---:|---:|---:|---|
| csi000852 | 2016-08-11 | 8647.115000 | 8667.246000 | 8532.329000 | 8531.691000 | OHLC_INVARIANT_FAILED |
| csi000905 | 2016-08-11 | 6304.777000 | 6318.977000 | 6226.358000 | 6226.312000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2012-04-10 | 9682.830000 | 9795.967000 | 9516.891000 | 9795.968000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2012-06-13 | 9835.405000 | 9950.045000 | 9795.055000 | 9950.046000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2015-12-15 | 12412.460000 | 12553.790000 | 12412.470000 | 12495.250000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2016-01-18 | 9807.248000 | 10273.590000 | 9807.249000 | 10155.960000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2016-01-21 | 10207.420000 | 10475.510000 | 9975.975000 | 9975.974000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2016-02-04 | 9667.907000 | 9844.020000 | 9667.908000 | 9793.069000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2016-02-15 | 9385.524000 | 9725.182000 | 9385.525000 | 9668.845000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2016-03-14 | 9466.419000 | 9763.365000 | 9466.420000 | 9665.130000 | OHLC_INVARIANT_FAILED |
| sz399001 | 2016-04-13 | 10599.210000 | 10810.410000 | 10599.220000 | 10684.920000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2015-12-03 | 2622.486000 | 2710.808000 | 2622.487000 | 2708.123000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2015-12-17 | 2784.970000 | 2835.701000 | 2784.971000 | 2835.701000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2015-12-28 | 2809.519000 | 2823.749000 | 2735.486000 | 2735.485000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2016-01-18 | 2074.858000 | 2206.836000 | 2074.859000 | 2174.934000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2016-02-05 | 2127.347000 | 2141.556000 | 2096.987000 | 2096.986000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2016-03-07 | 1935.093000 | 1995.937000 | 1935.094000 | 1953.332000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2016-03-14 | 1962.105000 | 2048.498000 | 1962.106000 | 2023.128000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2016-03-30 | 2172.741000 | 2248.784000 | 2172.742000 | 2248.783000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2016-04-07 | 2310.923000 | 2316.630000 | 2248.685000 | 2248.684000 | OHLC_INVARIANT_FAILED |
| sz399006 | 2016-04-13 | 2278.522000 | 2330.056000 | 2278.523000 | 2294.015000 | OHLC_INVARIANT_FAILED |
