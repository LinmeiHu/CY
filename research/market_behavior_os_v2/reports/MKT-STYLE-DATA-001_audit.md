# MKT-STYLE-DATA-001 circulating-size data audit

## Decision

- Status: `COMPLETE_DATA_CONTRACT_PASS`
- Data-contract gate: `PASS`
- Accepted semantic label if passing: `circulating_market_value_cny`.
- Total market cap, true free-float cap, enterprise value, growth/value, and beta claim: **none**.
- Future values, strategy outcomes, post-2023 data, and CY-011 read: **none**.

## Row/PIT audit

- Rows: 6,155,390; dates: 2018-01-02..2023-12-29.
- Duplicate/time-travel rows: 0/0.
- Component/lineage/size failures: 0/0/0.
- Turnover-unit/decision-time failures: 0/0.
- Circulating value CNY min/median/max: 218800000.000/4041608907.520/3267370477800.000.

## Population eligibility

| Group | Dates | Minimum | Required | Fail-closed dates | Eligible fraction |
|---|---:|---:|---:|---:|---:|
| `ALL_A:ALL_STATUS` | 1457 | 2984 | 1000 | 0 | 1.000 |
| `ALL_A:NON_ST` | 1457 | 2939 | 1000 | 0 | 1.000 |
| `CHINEXT_BOARD:ALL_STATUS` | 1457 | 618 | 200 | 0 | 1.000 |
| `CHINEXT_BOARD:NON_ST` | 1457 | 618 | 200 | 0 | 1.000 |
| `SH_A:ALL_STATUS` | 1457 | 1227 | 400 | 0 | 1.000 |
| `SH_A:NON_ST` | 1457 | 1200 | 400 | 0 | 1.000 |
| `SZ_A:ALL_STATUS` | 1457 | 1756 | 400 | 0 | 1.000 |
| `SZ_A:NON_ST` | 1457 | 1739 | 400 | 0 | 1.000 |

Failed hard gates: `none`.

## Reproducibility

- Spec SHA-256: `506c24bcdd498162b3d44faa3008aa54ddf9a4132606b5da9a890240e224484b`
- CY-006 manifest SHA-256: `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`
