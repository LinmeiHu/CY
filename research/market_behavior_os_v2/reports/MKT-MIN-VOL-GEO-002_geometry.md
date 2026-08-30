# MKT-MIN-VOL-GEO-002 outcome-blind minute-volatility geometry

## Boundary

- Status: `COMPLETE_DISTINCT_PATH_COORDINATE`
- Common rows: 10,696; 2018-07-03..2023-12-29.
- Geometry availability/decision time: 15:30 Asia/Shanghai after the completed 15:00 minute bar; no action created.
- Raw minutes, failed representations, outcomes, strategy fields, and CY-011 read: **none**.
- Distinctness is contemporaneous state geometry, not contraction/expansion, usefulness, prediction, habitat fitness, or causality.

## Pairwise geometry

| Control | Coordinate | Median absolute rho | Maximum absolute rho | Median <0.85 |
|---|---|---:|---:|---|
| `minute_level` | raw | 0.249 | 0.281 | PASS |
| `daily_realized_level` | raw | 0.011 | 0.018 | PASS |
| `daily_realized_level` | pit | 0.178 | 0.288 | PASS |
| `daily_realized_level` | relative_to_all | 0.028 | 0.029 | PASS |
| `daily_realized_level` | relative_rank | 0.037 | 0.046 | PASS |
| `daily_intraday_range` | raw | 0.076 | 0.098 | PASS |
| `daily_intraday_range` | pit | 0.118 | 0.156 | PASS |
| `daily_intraday_range` | relative_to_all | 0.018 | 0.020 | PASS |
| `daily_intraday_range` | relative_rank | 0.024 | 0.031 | PASS |
| `daily_volatility_concentration` | raw | 0.238 | 0.268 | PASS |
| `daily_volatility_concentration` | pit | 0.119 | 0.229 | PASS |
| `daily_volatility_concentration` | relative_to_all | 0.002 | 0.004 | PASS |
| `daily_volatility_concentration` | relative_rank | 0.002 | 0.004 | PASS |
| `daily_volatility_change` | raw | 0.065 | 0.075 | PASS |
| `daily_volatility_change` | pit | 0.038 | 0.096 | PASS |
| `daily_volatility_change` | relative_to_all | 0.012 | 0.017 | PASS |
| `daily_volatility_change` | relative_rank | 0.013 | 0.017 | PASS |

## Joint raw-rank reconstruction

- Median adjusted R-squared: 0.195 (gate <0.70: PASS).
- Maximum adjusted R-squared: 0.223 (gate <0.85: PASS).

## Reproducibility

- Spec SHA-256: `b556472dc456a1d9faefda98a6de01751d9254816bf283e5c2abd7a1c50024c4`
- Path panel SHA-256: `d0a396a9d3788074b483522f81b1f24ea4d6eab339c058f6839e86bb7a589ec0`
- Volatility panel SHA-256: `f736128419bdd632444c70e12233b08823130ffccffffcd68a9f69f7330040dc`
- Output panel SHA-256: `8cbe07f000f39edfc4f79849fbeb66022f2d334c4d465f72b8ba7e15e8df48ed`
