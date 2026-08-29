# ChinNext V1 Phase 3 — pre-registered module ablation

> Six arms were frozen before results and executed once in the specified A0–A5
> order. This is module removal/isolation, not parameter optimization.

## Frozen identity

- ABLATION_SPEC_SHA256: `530a5cabddf5afbef86f3fd433a6be35a36973bf3f7662944267a3bec97f160c`
- ABLATION_SPEC_FROZEN_BEFORE_RESULTS: `YES`
- STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- PIT_MANIFEST_DIGEST: `8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7`
- AUTHORIZATION_ID: `CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1`
- DATE_RANGE: `2024-01-02 .. 2025-12-31`
- FORMAL_REPLAY_EXECUTIONS: `6`
- PIT_REBUILT: `NO`
- CURRENT_SURVIVOR_FALLBACK: `NO`

## Arm results

| Arm | Total return | Max DD | Trades | Win rate | Top20 conc. | Return ex best20 | Baseline Top20 captured | Sep-2024 P&L | Avg invested | Label |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A0_BASELINE | 105.2422% | -26.2272% | 111 | 44.1441% | 84.2544% | -32.1953% | 20/20 | 706,394.41 | 40.3915% | REFERENCE |
| A1_MINUS_MINVOL | 88.4439% | -24.6860% | 125 | 40.0000% | 85.7426% | -58.1301% | 15/20 | 780,468.91 | 42.1293% | CLEARLY_HELPFUL |
| A2_MINUS_B60 | 42.7426% | -22.2107% | 239 | 33.0544% | 78.4880% | -67.0186% | 7/20 | 654,710.20 | 54.3718% | RISK_FILTERING |
| A3_MINUS_FULL40 | 133.7522% | -32.2766% | 207 | 35.7488% | 65.8564% | -72.2847% | 1/20 | 687,357.61 | 58.5199% | RISK_FILTERING |
| A4_NO_RS_SELECTION_CONTROL | 103.1124% | -24.0293% | 114 | 41.2281% | 85.9984% | -37.3763% | 16/20 | 706,394.41 | 40.4746% | INCONCLUSIVE |
| A5_MINUS_MARKET_ENTRY_GATE | 105.4069% | -25.9903% | 113 | 44.2478% | 84.0222% | -31.7325% | 20/20 | 706,394.41 | 40.4433% | REDUNDANT_IN_THIS_SAMPLE |

### Extended uniform metrics

| Arm | Annualized | Median trade | Mean trade | 2024 return | 2025 return | Top1 conc. | Top5 conc. | Top10 conc. | Sharpe rf=0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A0_BASELINE | 43.6891% | -1.0750% | 7.7312% | 49.0494% | 37.7008% | 13.2763% | 40.9643% | 62.3049% | 1.3491 |
| A1_MINUS_MINVOL | 37.6348% | -3.2711% | 6.5577% | 56.1540% | 20.6783% | 13.0176% | 39.6367% | 63.6193% | 1.1669 |
| A2_MINUS_B60 | 19.6507% | -2.3189% | 2.0243% | 44.3734% | -1.1296% | 13.6151% | 37.7616% | 58.1312% | 0.7385 |
| A3_MINUS_FULL40 | 53.4270% | -4.9101% | 4.5075% | 28.7586% | 81.5430% | 6.0057% | 25.3984% | 42.3137% | 1.1444 |
| A4_NO_RS_SELECTION_CONTROL | 42.9354% | -1.3590% | 7.2851% | 50.2554% | 35.1781% | 13.2568% | 41.9647% | 62.7678% | 1.3371 |
| A5_MINUS_MARKET_ENTRY_GATE | 43.7472% | -1.0750% | 7.6240% | 49.0520% | 37.8089% | 13.2685% | 40.7784% | 62.0830% | 1.3509 |

## Deltas versus A0

| Arm | Return Δpp | MaxDD Δpp | Trades Δ | Top20 conc. Δpp | Ex-best20 Δpp | Top20 capture Δ | Candidate events Δ | Selected entries Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A1_MINUS_MINVOL | -16.7983 | 1.5412 | 14 | 1.4882 | -25.9348 | -5 | 141 | 14 |
| A2_MINUS_B60 | -62.4997 | 4.0165 | 128 | -5.7664 | -34.8233 | -13 | 11431 | 128 |
| A3_MINUS_FULL40 | 28.5100 | -6.0494 | 96 | -18.3979 | -40.0894 | -19 | 13591 | 96 |
| A4_NO_RS_SELECTION_CONTROL | -2.1298 | 2.1979 | 3 | 1.7440 | -5.1810 | -4 | -8 | 3 |
| A5_MINUS_MARKET_ENTRY_GATE | 0.1647 | 0.2369 | 2 | -0.2321 | 0.4628 | 0 | -1 | 2 |

Percentage-point deltas use the frozen definitions in the pre-registration spec.
Drawdown delta below zero means the ablation arm suffered a worse drawdown.

## Opportunity set, exposure, and September-2024 cohort

| Arm | Candidate events | Selected entries | Trades | Avg holdings | Avg invested | Sep trades | Sep positive-P&L share | Sep Top20 | P&L ex Sep cohort |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A0_BASELINE | 1175 | 121 | 111 | 4.052 | 40.3915% | 10 | 43.3046% | 9 | 232,758.20 |
| A1_MINUS_MINVOL | 1316 | 135 | 125 | 4.229 | 42.1293% | 10 | 45.6557% | 9 | 50,475.17 |
| A2_MINUS_B60 | 12606 | 249 | 239 | 5.474 | 54.3718% | 15 | 48.1604% | 9 | -278,393.05 |
| A3_MINUS_FULL40 | 14766 | 217 | 207 | 5.913 | 58.5199% | 16 | 22.8551% | 4 | 171,967.02 |
| A4_NO_RS_SELECTION_CONTROL | 1167 | 124 | 114 | 4.062 | 40.4746% | 10 | 43.2411% | 9 | 212,296.25 |
| A5_MINUS_MARKET_ENTRY_GATE | 1174 | 123 | 113 | 4.058 | 40.4433% | 10 | 43.2792% | 9 | 234,235.30 |

`RETURN_EXCLUDING_2024_09_ENTRY_COHORT` is **UNRESOLVED** for every arm: removing
realized trade cash flows does not reconstruct a valid counterfactual portfolio
NAV because capital availability and later sizing would change. The table reports
the pre-registered auditable completed-cycle P&L diagnostic instead.

## Winner capture and creation

| Arm | Baseline Top10 captured | Baseline Top20 captured | Same-symbol unrelated | Arm Top20 baseline overlap | Arm Top20 new trades | Arm Top20 P&L |
|---|---:|---:|---:|---:|---:|---:|
| A0_BASELINE | 10/10 | 20/20 | 0 | 20 | 0 | 1,374,375.12 |
| A1_MINUS_MINVOL | 9/10 | 15/20 | 0 | 15 | 5 | 1,465,740.24 |
| A2_MINUS_B60 | 5/10 | 7/20 | 3 | 7 | 13 | 1,097,611.73 |
| A3_MINUS_FULL40 | 1/10 | 1/20 | 6 | 1 | 19 | 2,060,369.32 |
| A4_NO_RS_SELECTION_CONTROL | 8/10 | 16/20 | 1 | 16 | 4 | 1,404,886.37 |
| A5_MINUS_MARKET_ENTRY_GATE | 10/10 | 20/20 | 0 | 20 | 0 | 1,371,394.35 |

Capture requires the exact `(symbol, entry_signal_date)` episode. Trading the same
symbol at another date is shown separately and never counted as capture.

## Pre-registered interpretation

- MOST_HELPFUL_MODULE: **B60**
- MOST_REDUNDANT_MODULE: **MARKET_ENTRY_GATE**
- MODULE_WITH_LARGEST_RISK_CONTROL_EFFECT: **FULL40**
- MODULE_WITH_LARGEST_WINNER_CAPTURE_EFFECT: **FULL40**

Labels apply the multi-metric rules frozen in the spec. A higher return caused by
more candidates, trades, or exposure is not by itself evidence that a module is
harmful. All conclusions remain sample-specific descriptive ablation evidence.

## Phase 3 findings

- **MINVOL:** Removing MINVOL added 141 candidate events and 14 completed trades, but reduced return by 16.7983pp, worsened return-ex-best20 by 25.9348pp, and captured only 15/20 baseline winner episodes.
- **B60:** Removing B60 expanded candidates by 11,431, trades by 128, and average exposure by 13.9804pp; return fell 62.4997pp and baseline winner capture fell to 7/20 despite a 4.0165pp shallower max drawdown.
- **FULL40:** Removing FULL40 raised return by 28.5100pp but expanded candidates by 13,591 and exposure by 18.1285pp, worsened max drawdown by 6.0494pp and return-ex-best20 by 40.0894pp, and retained only 1/20 baseline winners.
- **RS selection:** The deterministic no-RS control kept opportunity and exposure near A0, returned 2.1298pp less, and retained 16/20 baseline winner episodes; the pre-registered multi-metric result is INCONCLUSIVE.
- **Market entry gate:** Removing only the market entry gate changed return by +0.1647pp, max drawdown by +0.2369pp, exposure by +0.0519pp, and retained all 20 baseline winner episodes; it is REDUNDANT_IN_THIS_SAMPLE.
- **2024-09 cohort:** A0 has 10 September-entry completed cycles, 706,394.41 P&L, 43.3046% of positive P&L, and 9/20 arm winners. A1/A2/A4/A5 preserve strong cohort dependence. A3 reduces the share to 22.8551% and 4/20 only while replacing the opportunity set, exposure, and 19/20 baseline winners. Counterfactual portfolio return excluding the cohort remains UNRESOLVED.

## Execution correctness

- A0 execution ledger reproduces Phase 1B byte-for-byte: `YES`
- A0 daily NAV reproduces Phase 1B byte-for-byte: `YES`
- Same-day fills across all arms: `0`
- Stale held valuations across all arms: `0`
- Transaction cost: fixed `10 bps/side` in all arms
- Position and exit semantics: identical in all arms

## Next research question — not run

Perform an exposure-matched decomposition of any high-opportunity-set arms, with
the complete control matrix frozen before execution. Exit ablation remains out of
scope until ledger reasons can distinguish individual MA exits from other set
changes.
