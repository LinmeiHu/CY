# A-share Tail-to-Open LightGBM V1 — Development-only translation diagnostic

Classification: `ML_OPPORTUNITY_CONDITIONALITY`.

Only the accepted 2018–2021 OOF prediction artifact was read. No model was fit or scored; 2022–2023 Validation and 2024–2026 Final OOS remain unread.

## Fixed upper tails (pooled)

| Tail | Gross | Net | Universe excess | Break-even round-trip cost | Coverage |
|---|---:|---:|---:|---:|---:|
| top_20pct | 0.029% | -0.371% | 0.147% | 0.036% | 99.91% |
| top_10pct | 0.037% | -0.362% | 0.156% | 0.045% | 99.90% |
| top_5pct | 0.043% | -0.356% | 0.161% | 0.050% | 99.90% |
| top_2pct | 0.045% | -0.354% | 0.164% | 0.053% | 99.89% |
| top_1pct | 0.053% | -0.346% | 0.171% | 0.059% | 99.87% |

## Pooled 20-bucket score curve

| Bucket (low→high) | Observations | Gross | Net | Universe excess | Coverage |
|---|---:|---:|---:|---:|---:|
| 1 | 96,015 | -1.434% | -1.827% | -1.309% | 80.40% |
| 2 | 95,512 | -0.450% | -0.848% | -0.330% | 92.78% |
| 3 | 95,577 | -0.263% | -0.661% | -0.144% | 97.58% |
| 4 | 95,473 | -0.173% | -0.572% | -0.054% | 98.96% |
| 5 | 95,530 | -0.126% | -0.525% | -0.007% | 99.44% |
| 6 | 95,617 | -0.098% | -0.497% | 0.021% | 99.61% |
| 7 | 95,565 | -0.073% | -0.472% | 0.046% | 99.74% |
| 8 | 95,481 | -0.053% | -0.451% | 0.066% | 99.78% |
| 9 | 95,613 | -0.043% | -0.442% | 0.076% | 99.81% |
| 10 | 95,325 | -0.033% | -0.432% | 0.085% | 99.80% |
| 11 | 95,779 | -0.019% | -0.418% | 0.099% | 99.82% |
| 12 | 95,462 | -0.012% | -0.411% | 0.107% | 99.87% |
| 13 | 95,632 | -0.011% | -0.410% | 0.107% | 99.85% |
| 14 | 95,509 | 0.001% | -0.399% | 0.119% | 99.90% |
| 15 | 95,483 | 0.011% | -0.388% | 0.130% | 99.88% |
| 16 | 95,569 | 0.006% | -0.393% | 0.125% | 99.90% |
| 17 | 95,624 | 0.018% | -0.381% | 0.136% | 99.92% |
| 18 | 95,521 | 0.022% | -0.377% | 0.141% | 99.90% |
| 19 | 95,568 | 0.032% | -0.368% | 0.150% | 99.90% |
| 20 | 95,097 | 0.043% | -0.356% | 0.162% | 99.90% |

## Chronological fixed tails

| Year | Top 20% gross / net | Top 10% gross / net | Top 5% gross / net | Top 2% gross / net | Top 1% gross / net |
|---|---:|---:|---:|---:|---:|
| 2018 | -0.051% / -0.450% | -0.045% / -0.444% | -0.040% / -0.439% | -0.038% / -0.437% | -0.030% / -0.429% |
| 2019 | 0.095% / -0.304% | 0.104% / -0.296% | 0.111% / -0.289% | 0.110% / -0.290% | 0.138% / -0.261% |
| 2020 | 0.024% / -0.376% | 0.036% / -0.363% | 0.043% / -0.356% | 0.044% / -0.355% | 0.046% / -0.353% |
| 2021 | 0.046% / -0.353% | 0.054% / -0.345% | 0.057% / -0.342% | 0.065% / -0.335% | 0.057% / -0.342% |

Score-shape classification: `BOTH_SIDES`. Opportunity classification: `STRONG_OPPORTUNITY_CONDITIONALITY`.

`severe_loss10` is explicitly unavailable: the accepted OOF artifact retains terminal labels but not the complete intraholding low path. It was not reconstructed from Validation-era raw paths.
