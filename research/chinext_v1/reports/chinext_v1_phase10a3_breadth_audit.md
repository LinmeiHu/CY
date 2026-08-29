# ChinNext V1 Phase 10A3 — PIT market breadth descriptive audit

This is a zero-replay descriptive artifact. No strategy, NAV, trade or PIT builder was executed.

- FORMAL_REPLAY_EXECUTIONS: `0`
- FEATURE_SPEC_SHA256: `5326df01bfb87bdc17311e9614f37fcc73f0998e30c7f50bc8b1b6275c67b347`
- BREADTH_GOVERNANCE_STATUS: `EXISTING_AUTHORIZATION_REUSED`
- DAILY_DATE_COUNT: `969`; member range `1090..1393`

## Coverage
| Feature | Days below 95% coverage |
|---|---:|
| above_ma20_breadth | 12 |
| above_ma60_breadth | 391 |
| positive_20d_momentum_breadth | 1 |
| positive_60d_momentum_breadth | 254 |
| b60_breakout_breadth | 400 |
| cross_sectional_median_20d_return | 1 |
| cross_sectional_median_close_vs_ma20 | 12 |

## Selected entry-day descriptive statistics
| Year | Entries | Median breadth above MA20 | Median positive 20d momentum | Median B60 breakout |
|---:|---:|---:|---:|---:|
| 2022 | 37 | 0.720353982300885 | 0.6636771300448431 | None |
| 2023 | 57 | 0.5864719446579554 | 0.4800332778702163 | 0.03442879499217527 |
| 2024 | 38 | 0.6778774289985052 | 0.5995475113122172 | 0.019534184823441023 |
| 2025 | 73 | 0.5952732644017725 | 0.577485380116959 | 0.020029673590504452 |

## Governance dependencies
| Asset | ID | Coverage | PIT/authorization |
|---|---|---|---|
| development_daily_pit_membership | CY-027 | 2024-01-02..2025-12-31 | B_RECONSTRUCTED / CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1 |
| holdout_daily_pit_membership | CY-028 | 2022-01-04..2023-12-29 | B_RECONSTRUCTED / CYQ-AUTH-CHINEXT-V1-PIT-B-HOLDOUT-2022-2023-V1 |
| daily_security_prices | CY-006 | 2018-01-01..2026-08-12 | B_CAUSAL_RESEARCH / same bounded PIT source contracts |
| trade_calendar | QD-003 | 2006-04-20..2026-08-14 | completed calendar / existing local calendar |

## Findings
Breadth values are calculated from exact PIT member denominators and invalidated when coverage is below 95%. Development/OOS, within-year, frozen temporal-matched and blocked-period summaries are descriptive only; no feature threshold or admission rule was selected.

Temporal matched evidence reuses the frozen Phase 10A2 identities: `33/33` usable pairs. Within-year RT20 counts are 2022:2, 2023:9, 2024:11, 2025:20; 2022 is explicitly insufficient for strong inference when applicable.

The frozen 2024-09 descriptive cohort contains `10` entries; it is not promoted to a rule. 2022 loser versus 2024-25 right-tail distributions are reported in the summary and overlap is not treated as causal evidence.

The evidence is classified **PARTIALLY** within-period and **MODERATE** in strength. Incrementality over the frozen index-feature evidence is **INCONCLUSIVE**. No candidate family is promoted and the next direction is **MORE_REGIME_DIAGNOSTICS_REQUIRED**.

## Governance
Existing bounded PIT authorizations are reused solely for a derived descriptive artifact. No registry authorization was broadened, no current-survivor fallback or download was used, and formal replay/trade/NAV counts are all zero.
