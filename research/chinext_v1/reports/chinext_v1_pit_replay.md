# ChinNext V1 — frozen PIT-B replay

> **FORMAL BOUNDED PIT-B RESEARCH / NOT STRICT ARCHIVAL PIT-A**

## Frozen run identity

- AUTHORIZATION_ID: `CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1`
- AUTHORIZATION_VALID: `YES`
- QD007_GLOBAL_STATUS: `DISCOVERY_ONLY`; globally upgraded: `NO`
- ONLY_MATERIAL_DIFFERENCE_FROM_CURRENT_SURVIVOR_BASELINE: `PIT universe membership`
- CURRENT_SURVIVOR_USED_FOR_TRADING: `NO`
- DATE_RANGE: `2024-01-02 .. 2025-12-31` (`485` sessions)
- STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- PIT_MANIFEST_SHA256: `8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7`
- PIT_REBUILT: `NO`
- COST: fixed `10 bps/side`; separate stamp duty: `NONE` (matches frozen comparator)

The existing replay's signals, configuration, next-open execution, T+1/limit
checks, corporate-action handling, accounting and ledgers are reused. The only
decision-input change is replacing the static current-survivor pool with the
authorized date-specific PIT membership and its frozen listing-session age.

## Performance

- PIT_TOTAL_RETURN: `105.2422%`
- PIT_ANNUALIZED_RETURN: `43.6891%`
- PIT_MAX_DRAWDOWN: `-26.2272%`
- VOLATILITY: `30.0192%`
- SHARPE_RF0: `1.3491`
- TRADE_COUNT: `111` completed round trips
- WIN_RATE: `44.1441%`
- MEDIAN_TRADE_RETURN: `-1.0750%`
- MEAN_TRADE_RETURN: `7.7312%`
- 2024_RETURN: `49.0494%`
- 2025_RETURN: `37.7008%`
- PIT_TOP10_PNL_CONCENTRATION: `62.3049%`
- PIT_TOP20_PNL_CONCENTRATION: `84.2544%`
- RETURN_EX_BEST10: `3.6092%` — still profitable
- RETURN_EX_BEST20: `-32.1953%` — not profitable

Concentration is the share of all positive completed-round-trip P&L, matching the
frozen current-survivor robustness comparator. Return exclusions subtract those
completed-cycle P&Ls from final portfolio return; ending marked positions remain.

## Exact frozen comparison

| Metric | PIT | Current survivor | Delta (pp) | Relative change |
|---|---:|---:|---:|---:|
| Total return | 105.2422% | 105.2422% | 0.0000 | 0.0000% |
| Max drawdown | -26.2272% | -26.2272% | 0.0000 | -0.0000% |
| Top20 concentration | 84.2544% | 84.2544% | -0.0000 | -0.0001% |

- **FACT:** With universe membership as the only material change, the measured
  return treatment effect is `0.0000` percentage points.
- **INFERENCE:** This is a PIT/universe-treatment effect; it is not proof that every
  basis point is caused by one single survivorship-bias mechanism.

## Historical non-survivor attribution

- HISTORICAL_NON_SURVIVOR_SYMBOL_COUNT: `16`
- SELECTED_COUNT: `0`
- TRADE_COUNT: `0` completed cycles
- TOTAL_PNL: `0.00` (realized plus ending mark, if any)
- TOTAL_RETURN_CONTRIBUTION: `0.0000%`
- DELISTED_HISTORICAL_SECURITIES_SELECTED: `0`
- DELISTED_HISTORICAL_TRADES: `0`
- DELISTED_HISTORICAL_PNL: `0.00`
- FUTURE_LISTED_EXCLUSION_COUNT: `81`

**FACT:** `delisted` is assigned only where the frozen security master has an
explicit `out_date`. **UNRESOLVED:** the remaining current-pool exclusions cannot
be reliably separated into later ST versus other exclusion causes. The
future-listed count measures static current-survivor universe membership before
true listing, not actual fills; missing history may still have blocked a signal.

## Top 20 completed trades by P&L

| Rank | Symbol | Entry signal | Entry execution | Exit execution | P&L | Return |
|---:|---|---|---|---|---:|---:|
| 1 | 300377.SZ | 2024-09-24 | 2024-09-25 | 2024-11-19 | 216,566.15 | 226.6962% |
| 2 | 300497.SZ | 2025-11-06 | 2025-11-07 | 2025-11-18 | 129,486.71 | 78.0818% |
| 3 | 300033.SZ | 2024-09-24 | 2024-09-25 | 2024-11-19 | 118,387.69 | 124.7462% |
| 4 | 300437.SZ | 2025-11-06 | 2025-11-07 | 2025-11-18 | 109,502.11 | 64.9338% |
| 5 | 300803.SZ | 2024-09-24 | 2024-09-25 | 2024-11-19 | 94,276.47 | 95.6340% |
| 6 | 300348.SZ | 2024-09-24 | 2024-09-25 | 2024-11-19 | 84,388.96 | 88.5646% |
| 7 | 301165.SZ | 2025-06-24 | 2025-06-25 | 2025-10-09 | 74,354.74 | 46.9366% |
| 8 | 301093.SZ | 2025-06-23 | 2025-06-24 | 2025-10-15 | 70,089.30 | 40.2699% |
| 9 | 300779.SZ | 2025-02-12 | 2025-02-13 | 2025-03-25 | 66,690.95 | 45.3227% |
| 10 | 301141.SZ | 2025-06-04 | 2025-06-05 | 2025-06-23 | 52,587.45 | 34.2694% |
| 11 | 300128.SZ | 2024-09-25 | 2024-09-26 | 2024-11-19 | 51,213.73 | 53.6250% |
| 12 | 300324.SZ | 2024-09-24 | 2024-09-25 | 2024-11-19 | 49,544.01 | 51.7725% |
| 13 | 300490.SZ | 2025-09-25 | 2025-09-26 | 2025-10-15 | 47,352.06 | 26.8634% |
| 14 | 300457.SZ | 2025-08-28 | 2025-08-29 | 2025-10-15 | 42,546.34 | 23.6979% |
| 15 | 300763.SZ | 2025-08-29 | 2025-09-01 | 2025-10-15 | 30,839.56 | 18.9448% |
| 16 | 300459.SZ | 2024-09-25 | 2024-09-26 | 2024-11-19 | 30,001.43 | 25.1544% |
| 17 | 300357.SZ | 2025-07-16 | 2025-07-17 | 2025-09-22 | 28,256.10 | 19.0522% |
| 18 | 300182.SZ | 2024-09-24 | 2024-09-25 | 2024-11-19 | 27,105.71 | 22.0232% |
| 19 | 300938.SZ | 2025-10-29 | 2025-10-30 | 2025-11-18 | 26,245.02 | 15.3608% |
| 20 | 300442.SZ | 2024-09-24 | 2024-09-25 | 2024-11-19 | 24,940.63 | 20.6102% |

The standard execution ledger also preserves prices, shares, notional, target
weight, reason, costs, T+1 status and failed executions. It is the authoritative
leg-level audit trail; this table aggregates completed position cycles only.

## Bias assessment

- BIAS_ASSESSMENT: **WINNER_CONCENTRATED**

Classification rules were frozen before inspecting the formal result: a return
drop of at least 25 percentage points is survivorship-sensitive; Top20 above 75%
or non-positive return without the best 20 is winner-concentrated; both is mixed.
No strategy parameter or execution rule is changed in response to this result.

## Correctness audit

- SAME_DAY_FILL_COUNT: `0`
- STALE_HELD_VALUATION_COUNT: `0`
- CURRENT_SURVIVOR_FALLBACK: `NO`
- EXECUTION_LEDGER: `/Users/linmei/Documents/CY-supermind-v6/research/chinext_v1/output/chinext_v1_pit_replay/execution_ledger.jsonl` (`f3a83a9e974776f34477c952b1bf4c26f22a5ef00879adfc77cd6188f9eec9d5`)
- DAILY_NAV: `/Users/linmei/Documents/CY-supermind-v6/research/chinext_v1/output/chinext_v1_pit_replay/daily_nav.jsonl` (`a1b8399c7f199a76ae6e891bbd690de16a3312d2cc548c77d552f2531adcc071`)
