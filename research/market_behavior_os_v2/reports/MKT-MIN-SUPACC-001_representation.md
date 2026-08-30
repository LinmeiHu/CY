# MKT-MIN-SUPACC-001 same-session intraday mechanisms

## Boundary

- Status: `COMPLETE_1_OF_3_MINIMAL_MECHANISMS`
- Source: frozen required-scale daily minute panel; no raw minute rescan.
- Availability: 15:30 Asia/Shanghai after the completed 15:00 bar.
- Future values, strategy outcomes, failed paths, post-2023 data, and CY-011 read: **none**.
- Scores are OHLCV-derived state representations, not cross-day support, participant accumulation, prediction, or rules.

## Mechanism gates

| Mechanism | Shape worst | LOO worst | p40/p60 worst | Denominator rho | External max rho | Representation | External | Minimal |
|---|---:|---:|---:|---:|---:|---|---|---|
| `vwap_defense_recovery` | 0.892 | 0.894 | 0.965 | 0.998 | 0.764 | PASS | PASS | YES |
| `late_vwap_acceptance` | 0.966 | 0.947 | 0.988 | 1.000 | 0.833 | PASS | FAIL | NO |
| `price_volume_demand_balance` | 0.982 | 0.957 | 0.993 | 0.999 | 0.914 | PASS | FAIL | NO |

## Reproducibility

- Spec SHA-256: `fcdc9d359a153ba473543ee7ccfabb6f7ed68a4c37fca34a5a2b3e4f60be9435`
- Panel SHA-256: `b08abaabfea3fff9c5de716963ad0cd079d54884c63ab994f2b56c1448cb10c2`
