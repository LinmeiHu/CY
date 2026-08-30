# MKT-GEO-001 outcome-blind Trend × Breadth state geometry

## Boundary

- Status: `COMPLETE_OUTCOME_BLIND_STATE_GEOMETRY`
- Geometry rows: 32,088; 6 indices × 4 market views; 2018-07-03..2023-12-29.
- Strategy outcomes, future returns, trading rules, and CY-011 read: **none**.
- This describes contemporaneous redundancy, occupancy, dwell, and transitions. It does not establish usefulness, prediction, habitat fitness, or causality.

## Continuous geometry

| Relationship | Median | Maximum absolute across 24 pairs | Nonredundancy gate |
|---|---:|---:|---|
| direction vs new-high/new-low discovery | 0.489 | 0.571 | PASS |
| direction vs leadership concentration | -0.360 | 0.408 | PASS |
| discovery vs concentration, controlling direction | -0.490 | 0.530 | PASS |

## Absolute-sign state occupancy

| State | Observations |
|---|---:|
| NEGATIVE__BALANCED | 1,163 |
| NEGATIVE__BREAKDOWN | 4,725 |
| NEGATIVE__EXPANSION | 11,248 |
| POSITIVE__BALANCED | 445 |
| POSITIVE__BREAKDOWN | 1,779 |
| POSITIVE__EXPANSION | 12,728 |

State counts repeat dates across the 24 index/view geometry pairs and are not independent samples. Sparse states remain visible; no state boundary was optimized or merged.

## Reproducibility

- Spec SHA-256: `d364e52bbc5762cb335640a9a4e89b63614afb533b46b2c0c976c69282b6bf3b`
- Geometry panel SHA-256: `2c98865a60f40b634e90f7751bfcaa0d90feca6cf484fdc58b945c39ca203c99`
