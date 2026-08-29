# ChinNext V1 Phase 5 — extra-entry path decomposition

> Offline frozen-episode attribution only. Formal replay executions: **0**.
> No entry, exit, NAV, holding path, PIT artifact, or strategy semantic was changed.

## Frozen identity

- STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- PIT_MANIFEST_DIGEST: `8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7`
- PHASE3_SPEC_SHA256: `530a5cabddf5afbef86f3fd433a6be35a36973bf3f7662944267a3bec97f160c`
- PHASE4_SPEC_SHA256: `6823ac96d9f93922e64f71e2b7dd0048ca522f7c280b9d4388534e8c77563509`
- FORMAL_REPLAY_EXECUTIONS: `0`
- PIT_REBUILT: `NO`
- CURRENT_SURVIVOR_FALLBACK: `NO`

## Extra-trade distribution

| Cohort | Selected | Completed | Win rate | Median return | Mean return | Skewness | Excess kurtosis | Total P&L |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A2_MINUS_B60_RAW | 212 | 203 | 30.0493% | -2.4463% | -0.3590% | 3.2989 | 14.3718 | -128,419.90 |
| M2_MINUS_B60_MATCHED | 85 | 80 | 36.2500% | -3.1694% | 1.6276% | 3.7346 | 18.3569 | 98,757.30 |
| A3_MINUS_FULL40_RAW | 215 | 205 | 35.1220% | -4.9943% | 3.3699% | 2.4866 | 8.3213 | 668,344.05 |
| M3_MINUS_FULL40_MATCHED | 120 | 110 | 35.4545% | -6.2492% | 7.2567% | 3.1330 | 13.1637 | 685,673.70 |

Full p10/p25/p50/p75/p90/p95, standard deviation, payoff ratio, profit factor,
and holding-period distribution are in the machine-readable summary.

## Right-tail separation

- ENTRY_FEATURE_SEPARATION: **MODERATE**; median absolute Cliff's delta `0.1821`.
- POST_ENTRY_PATH_SEPARATION: **STRONG**; median absolute Cliff's delta `0.7704`.
- NEXT_RESEARCH_DIRECTION: **EXIT_HOLDING_PATH**.

Entry comparisons use only frozen signal-day information. Path comparisons are
post-entry attribution and make no predictive-causality claim.

## Crowd-out economic attribution

| Module deletion | Crowded baseline winners | Baseline winner P&L | Unique blocking extras | Blocking-extra P&L | Blocker win rate | Blocker median | Blocker mean | Blocker extra-Top20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B60 | 12 | 627,079.53 | 32 | 255,347.10 | 62.5000% | 1.4091% | 6.7801% | 11 |
| FULL40 | 19 | 1,157,808.97 | 65 | 1,171,751.11 | 49.2308% | -0.3565% | 16.0560% | 16 |

All multi-blocker observations are `CROWDOUT_SET`. Aggregate observed values are
**NOT_A_PORTFOLIO_COUNTERFACTUAL**; no one-for-one replacement outcome is fabricated.

## M3 alternative right tail

- M3 Top20/A0 Top20 exact episode overlap: `0/20`.
- M3 Top20 total P&L: `1,822,531.14`.
- Regime assessment: **DIFFERENT_RIGHT_TAIL_REGIME**.
- Exit-reason separability: **PARTIALLY_OBSERVED**.

The complete M3 Top20 identities and A0/M3 entry/path feature comparisons are in
the JSON summary.

### M3 Top20 trades

| Rank | Symbol | Entry signal | P&L | Return | RS | B60 margin | FULL40: box/MA-disp/eff/vol | MINVOL: loc/ratio | Hold | MFE | MAE | Exit reason |
|---:|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---|
| 1 | 300377.SZ | 2024-09-25 | 222,361.37 | 239.0445% | 0.9389 | 7.4128% | 0.3030 / 0.0784 / 0.1871 / 0.9978 | 0.0437 / 0.3071 | 33 | 381.6121% | -2.3016% | MARKET_MA20_X2 |
| 2 | 301345.SZ | 2025-06-24 | 149,891.70 | 90.9511% | 0.9503 | 2.4048% | 0.6639 / 0.2640 / 0.5703 / 1.0038 | 0.0569 / 0.2902 | 74 | 107.0117% | -5.2454% | MARKET_MA20_X2 |
| 3 | 300380.SZ | 2024-09-24 | 149,405.82 | 159.2580% | 0.9495 | 10.1947% | 0.2473 / 0.0580 / 0.0800 / 0.7047 | 0.0000 / 0.4503 | 34 | 251.6671% | -3.8520% | MARKET_MA20_X2 |
| 4 | 301292.SZ | 2025-11-06 | 132,420.88 | 81.0989% | 0.9797 | 6.0690% | 1.0354 / 0.2944 / 0.2505 / 1.3903 | 0.0092 / 0.1577 | 7 | 96.0521% | -5.0729% | MARKET_MA20_X2 |
| 5 | 300085.SZ | 2024-09-24 | 119,230.61 | 128.1761% | 0.9872 | 20.0303% | 0.6726 / 0.2097 / 0.4648 / 1.8736 | 0.0736 / 0.2282 | 33 | 243.1486% | -5.2600% | MARKET_MA20_X2 |
| 6 | 300153.SZ | 2025-02-17 | 114,546.70 | 63.3493% | 0.9905 | 12.0510% | 1.4720 / 0.1696 / 0.2978 / 1.2824 | 0.0046 / 0.4602 | 25 | 91.0989% | -8.2576% | MARKET_MA20_X2 |
| 7 | 300436.SZ | 2025-07-16 | 106,521.77 | 56.5708% | 0.9882 | 16.5473% | 1.2740 / 0.4523 / 0.4408 / 1.4545 | 0.0147 / 0.3564 | 35 | 120.3554% | -5.1800% | SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT |
| 8 | 301209.SZ | 2025-04-25 | 86,819.93 | 52.1183% | 0.9968 | 0.8759% | 1.1393 / 0.3788 / 0.5203 / 1.4794 | 0.0841 / 0.2646 | 20 | 68.0028% | -0.5897% | MARKET_MA20_X2 |
| 9 | 300641.SZ | 2024-04-26 | 78,851.44 | 83.1637% | 1.0000 | 3.2028% | 2.6399 / 0.9448 / 0.6447 / 1.2278 | 0.0231 / 0.0985 | 17 | 89.3063% | -0.3024% | MARKET_MA20_X2 |
| 10 | 300204.SZ | 2025-05-29 | 78,559.03 | 41.0945% | 0.9942 | 20.0000% | 2.0622 / 0.4960 / 0.5755 / 1.1201 | 0.3032 / 0.3916 | 15 | 71.9172% | -4.6171% | MARKET_MA20_X2 |
| 11 | 301489.SZ | 2025-08-13 | 70,470.91 | 45.0941% | 0.9962 | 5.8255% | 1.6746 / 0.6421 / 0.6210 / 1.5096 | 0.0000 / 0.4333 | 38 | 81.6654% | -3.7476% | MARKET_MA20_X2 |
| 12 | 300548.SZ | 2025-07-16 | 69,169.57 | 45.4552% | 0.9657 | 8.7186% | 0.6873 / 0.1677 / 0.4516 / 1.2324 | 0.1029 / 0.5815 | 51 | 88.7645% | -0.2622% | SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT |
| 13 | 300663.SZ | 2024-09-24 | 65,923.34 | 70.6322% | 0.9199 | 9.3777% | 0.2961 / 0.1056 / 0.2020 / 1.2651 | 0.0149 / 0.1222 | 33 | 133.5174% | -1.3685% | SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT |
| 14 | 300561.SZ | 2024-09-24 | 63,450.27 | 53.7223% | 0.9788 | 9.6552% | 0.4531 / 0.2041 / 0.2409 / 1.4144 | 0.0641 / 0.1915 | 34 | 138.1676% | -2.1993% | MARKET_MA20_X2 |
| 15 | 300255.SZ | 2025-05-29 | 62,930.60 | 36.1244% | 0.9731 | 15.6015% | 0.9114 / 0.2038 / 0.4018 / 1.1008 | 0.0687 / 0.2712 | 15 | 58.9203% | -4.9329% | MARKET_MA20_X2 |
| 16 | 300310.SZ | 2024-09-24 | 52,701.60 | 38.5187% | 0.9537 | 1.4652% | 0.5424 / 0.0942 / 0.2580 / 1.4850 | 0.0000 / 0.1605 | 34 | 100.2911% | -1.7170% | MARKET_MA20_X2 |
| 17 | 300718.SZ | 2025-02-06 | 52,556.07 | 32.2110% | 0.9992 | 12.8818% | 2.0801 / 0.5403 / 0.4378 / 1.0719 | 0.0137 / 0.1447 | 32 | 75.7913% | -2.1753% | MARKET_MA20_X2 |
| 18 | 300180.SZ | 2024-09-25 | 49,539.56 | 53.0270% | 0.9569 | 13.3333% | 0.2605 / 0.0169 / 0.1012 / 0.6883 | 0.0323 / 0.1533 | 32 | 124.6773% | -3.8217% | SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT |
| 19 | 300399.SZ | 2024-09-24 | 49,496.17 | 43.3644% | 0.9644 | 3.0374% | 0.4759 / 0.1192 / 0.2038 / 0.6904 | 0.0194 / 0.3275 | 34 | 108.3593% | -6.8846% | MARKET_MA20_X2 |
| 20 | 300333.SZ | 2024-09-24 | 47,683.79 | 37.9233% | 0.9518 | 7.5200% | 0.4205 / 0.0641 / 0.1876 / 0.5916 | 0.0054 / 0.2497 | 34 | 115.2239% | -7.5995% | MARKET_MA20_X2 |

### A0 Top20 vs M3 Top20 medians

| Feature | A0 Top20 | M3 Top20 |
|---|---:|---:|
| final_rs_score | 0.690183 | 0.975968 |
| b60_breakout_margin | 0.0180778 | 0.0904814 |
| box_width | 0.148393 | 0.679949 |
| ma_dispersion | 0.0336829 | 0.203971 |
| direction_efficiency | 0.0976411 | 0.349819 |
| vol_ratio_10_60 | 0.717258 | 1.23009 |
| minvol_location | 0.119524 | 0.0212433 |
| minimum_volume_ratio | 0.48629 | 0.267909 |
| holding_trading_days | 33.5 | 33 |
| MFE | 0.644926 | 1.03651 |
| MAE | -0.0121322 | -0.0383684 |

## September 2024

| Arm | Trades | Win rate | Median return | Mean return | Total P&L | Top20 count | MFE median | MAE median | Holding median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A0_BASELINE | 10 | 100.0000% | 52.6988% | 71.9640% | 706,394.41 | 9 | 95.8636% | -0.7325% | 34.0 |
| M2_MINUS_B60_MATCHED | 10 | 100.0000% | 45.1151% | 67.0015% | 671,437.76 | 9 | 83.4525% | -1.3570% | 34.0 |
| M3_MINUS_FULL40_MATCHED | 10 | 100.0000% | 53.3746% | 85.1701% | 854,430.77 | 9 | 129.0974% | -3.8368% | 34.0 |

Assessment: **POST_ENTRY_MARKET_PATH_UNUSUALLY_FAVORABLE**. Details and
entry-feature medians are frozen in the JSON output.

## Findings

- **Entry features — DESCRIPTIVE_ASSOCIATION:** Across four extra cohorts, entry-feature separation is MODERATE (median absolute Cliff's delta 0.1821). B60 breakout margin is directionally higher for Top20 extras in all four cohorts, while RS and most shape-feature directions are not stable across cohorts.
- **Post-entry path — DESCRIPTIVE_ASSOCIATION:** Post-entry path separation is STRONG (median absolute Cliff's delta 0.7704); MFE, days-to-MFE, and holding period separate strongly and consistently in all four cohorts; these are outcomes, not entry-time predictors.
- **B60 crowd-out — FACT:** 12 frozen baseline winners are linked to 32 unique B60 extras with observed total P&L 255,347.10, versus associated baseline winner P&L 627,079.53; not a portfolio counterfactual.
- **FULL40 crowd-out — FACT:** 19 frozen baseline winners are linked to 65 unique FULL40 extras with observed total P&L 1,171,751.11, close to associated baseline winner P&L 1,157,808.97; 16 blockers are their own extra-Top20. This is alternative-right-tail replacement, not a portfolio counterfactual.
- **M3 — FACT:** M3 Top20 has 0/20 exact episode overlap with A0 Top20: DIFFERENT_RIGHT_TAIL_REGIME.
- **September 2024 — DESCRIPTIVE_ASSOCIATION:** September-2024 assessment: POST_ENTRY_MARKET_PATH_UNUSUALLY_FAVORABLE; no counterfactual NAV was rebuilt.

All claims are labeled `FACT`, `DESCRIPTIVE_ASSOCIATION`, or `UNRESOLVED` in the
machine-readable findings. No predictive model or threshold search was run.
