# ChinNext V1 Phase 11A — PIT industry exposure and right-tail concentration

Zero-replay descriptive attribution of frozen OOS and development trades. No strategy, trade, NAV, PIT or universe rebuild was executed.

- PHASE11A_SPEC_SHA256: `62c0bb6ea94275d65da46fd86619fdc20e59a02d9fa06ee8e1747dda8140cb9e`
- INDUSTRY_GOVERNANCE_STATUS: `PIT_AUTHORIZED_EXISTING`
- PRIMARY_INDUSTRY_TAXONOMY: `CY-006 / QD-008 Eastmoney disclosure chronology`
- CYCLICAL_MAPPING_STATUS: `NOT_AVAILABLE`

## Coverage
| Year | Trades | Mapped | Unmapped | Coverage |
|---:|---:|---:|---:|---:|
| 2022 | 37 | 37 | 0 | 100.00% |
| 2023 | 57 | 57 | 0 | 100.00% |
| 2024 | 38 | 38 | 0 | 100.00% |
| 2025 | 73 | 73 | 0 | 100.00% |

## Concentration
Development frozen Top20 mapped industry distribution: `{"专业服务": 1, "光伏设备": 1, "化学制药": 1, "医疗器械": 1, "影视院线": 1, "游戏Ⅱ": 1, "环境治理": 2, "生物制品": 1, "电池": 2, "电网设备": 1, "计算机设备": 1, "软件开发": 4, "通信服务": 1, "通信设备": 1, "金属新材料": 1}`
2024-09 cohort (`10` trades) distribution: `{"塑料": 1, "影视院线": 1, "游戏Ⅱ": 1, "电池": 1, "计算机设备": 1, "软件开发": 4, "通信服务": 1}`

## Findings
Industry mapping is causal only when the CY-006 source notice precedes the entry signal date; unmapped rows remain visible. Right-tail industry concentration is classified PARTIALLY, while industry mix and same-industry regime effects remain INCONCLUSIVE/WEAKLY explanatory. No energy or cyclical exclusion is supported because no authorized cyclical mapping exists.

Sector-weight/cap diagnostics are not asserted because frozen daily NAV lacks position-to-industry identity; no counterfactual cap NAV was run.

Next direction: **MORE_INDUSTRY_DIAGNOSTICS_REQUIRED**. This phase does not propose an exclusion or cap.
