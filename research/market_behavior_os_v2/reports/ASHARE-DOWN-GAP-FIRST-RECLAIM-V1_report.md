# ASHARE-DOWN-GAP-FIRST-RECLAIM-V1 — Development report

**Verdict: `OUTLIER_OR_CLUSTER_DRIVEN`**

The frozen lifetime first-reclaim population was confirmed on 241-bar QD-004 sessions and evaluated only through 2021. Multiple gap IDs crossing in one stock/minute were retained for lifecycle diagnostics but collapsed to one fundable entry, deterministically using the earliest (lowest) executable stop price without outcome information.

## Population and correctness

- Qualifying gaps: 41,541; daily-path candidates: 40,717.
- Minute-confirmed: 40,468; executable gap reclaims: 40,075; unique entries: 40,031.
- Reclaim rate: 96.47%; symbols: 3,307; dates: 1,856.
- Lifecycle violations: 0; illegal admitted executions: 0; post-trigger dry-up bars: 0; post-2021 outcome reads: 0.
- Intervening-action invalidated crossings: 390; potential action-created false gaps excluded by lineage audit: 4,769.

## Raw economics

| Horizon | N | Gross mean | Net mean | Net median | Net win rate | Severe loss10 |
|---|---:|---:|---:|---:|---:|---:|
| T+1 legal open | 39,887 | 0.612% | 0.210% | -0.056% | 49.593% | 6.456% |
| T+1 close | 39,558 | 1.132% | 0.728% | 0.262% | 51.474% | 12.266% |
| T+2 close | 39,185 | 1.501% | 1.096% | -0.011% | 49.943% | 13.275% |
| T+3 close | 38,712 | 2.185% | 1.777% | 0.554% | 52.028% | 16.909% |

### T+1 legal-open chronology

| Year | N | Gross mean | Net mean | Net median |
|---:|---:|---:|---:|---:|
| 2014 | 656 | -0.487% | -0.885% | -1.156% |
| 2015 | 14,543 | 1.479% | 1.074% | 0.755% |
| 2016 | 3,286 | 2.149% | 1.741% | 1.834% |
| 2017 | 1,392 | -1.646% | -2.039% | -1.918% |
| 2018 | 4,165 | -1.406% | -1.800% | -1.720% |
| 2019 | 3,354 | -1.242% | -1.636% | -1.727% |
| 2020 | 9,336 | 1.236% | 0.832% | 0.773% |
| 2021 | 3,155 | -0.980% | -1.375% | -1.416% |

### Frozen mechanism groups (T+1 legal-open net)

| Dryup_3_20 | N | Mean | Median |
|---|---:|---:|---:|
| <=0.30 | 1,548 | 1.021% | -0.650% |
| (0.30,0.50] | 1,506 | 1.154% | 0.108% |
| (0.50,0.70] | 4,762 | 0.594% | 0.422% |
| (0.70,1.00] | 9,821 | 0.429% | 0.489% |
| >1.00 | 21,923 | -0.044% | -0.346% |
| MISSING | 327 | -3.123% | -3.869% |

## Mechanism interpretation

- Completed-session dry-up support: **False**.
- Positive T+1-open net years: 3 of 8.
- Top 1% winner contribution to positive T+1-open return: 9.737%; signed-sum contribution: 123.455%.
- Top 1% crowded-date signal share: 42.132%; positive-return contribution: 64.221%; signed-sum contribution: 491.875%.
- Equal-weighted event-day T+1-open net mean/median: -1.526% / -1.432%.
- Intraday dry-up: Yes descriptively: the highest-activity quintile is materially worse and low-activity quintiles are stronger, without a perfectly monotone curve.
- Price stabilization: Yes descriptively: strong dry-up plus stabilization exceeds strong dry-up plus deterioration.
- Gap size: Yes at T+1 open across the frozen 5-7%, 7-9%, and >=9% groups.
- Gap age: Yes: same-day and 1-10-session repairs are stronger; groups beyond 10 sessions are negative at T+1 open.

The decisive failure is chronology and market-wide clustering, not a lack of pooled mean. Five Development years lose money at T+1 open after costs, while the most crowded 1% of event dates account for a disproportionate share of both observations and gains. Individual winner-tail concentration is not the primary failure.

All dry-up, compression, stabilization, gap-size, age, board, ST, limit-state, annual, MFE/MAE, and clustering tables are retained in the machine-readable result. Intraday dry-up quintile boundaries were fixed from the predictor distribution alone before returns were attached. No favorable threshold or exit horizon was selected.

## Chronology and data contracts

Only 2013 warm-up state and 2014–2021 Development security data were opened. Fixed close outcomes requiring 2022 were censored. Raw prices were unadjusted QD-004 observations; daily PIT state supplied historical industry, trading status, actual limit rules, float-based turnover, and corporate-action lineage. Any action-coordinate uncertainty was censored rather than adjusted silently.

Validation (2022–2023) and Final OOS (2024 onward) remain sealed.
