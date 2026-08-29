# ChinNext V1 winner concentration and signal attribution

> Offline descriptive attribution of the frozen Phase 1B trades. No strategy
> replay, new trade, NAV recomputation, parameter change, or PIT rebuild occurred.

## Frozen identity

- STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- PIT_MANIFEST_DIGEST: `8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7`
- PHASE1B_SUMMARY_SHA256: `10c9a10860dfaef5ee621a5e98741a9b0f881be247e8115cd524d9098a66d6af`
- AUTHORIZATION_ID: `CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1`
- DATE_RANGE: `2024-01-02 .. 2025-12-31`
- TRADE_COUNT: `111`
- FORMAL_REPLAY_EXECUTIONS_THIS_PHASE: `0`

## Concentration

- TOP1_PNL_CONCENTRATION: `13.2763%`
- TOP5_PNL_CONCENTRATION: `40.9643%`
- TOP10_PNL_CONCENTRATION: `62.3049%`
- TOP20_PNL_CONCENTRATION: `84.2544%`
- RETURN_EX_BEST10: `3.6092%`
- RETURN_EX_BEST20: `-32.1953%`
- POSITIVE_PNL_HHI: `0.052985`
- POSITIVE_TRADE_PNL_GINI: `0.594135`
- SIGNED_TRADE_PNL_GINI: `UNRESOLVED` (ordinary Gini is unstable for signed P&L)
- TOP20_UNIQUE_SYMBOLS: `20`
- TOP20_REPEATED_SYMBOLS: `{}`
- TOP20_EXIT_YEAR_DISTRIBUTION: `{"2024": 9, "2025": 11}`

Concentration uses the same denominator as Phase 1B: all positive completed-cycle
P&L. The Top20 identity and order exactly match the frozen Phase 1B report.

## Right-tail profile

- MEDIAN_RETURN: `-1.0750%`
- MEAN_RETURN: `7.7312%`
- STANDARD_DEVIATION: `31.6520%`
- SKEWNESS: `4.0729`
- EXCESS_KURTOSIS: `22.2042`
- WIN_RATE: `44.1441%`
- AVERAGE_WINNER: `26.3516%`
- AVERAGE_LOSER: `-6.9849%`
- MEDIAN_WINNER: `12.9894%`
- MEDIAN_LOSER: `-6.1792%`
- WINNER_LOSER_PAYOFF_RATIO: `3.7727`
- PROFIT_FACTOR: `2.3570`

**FACT:** Positive skew, a mean far above the median, sub-50% win rate and a
winner/loser payoff ratio above one describe a right-tailed return distribution.
**INFERENCE:** This profile is consistent with trend-following; the attribution
does not establish that any module caused it.

## Group comparison

Cells are `median / mean / [p25, p75]`. GROUP_A is P&L ranks 1–10, GROUP_B
ranks 11–20, and GROUP_C ranks 21–111.

| Feature | GROUP_A median / mean / [p25,p75] | GROUP_B median / mean / [p25,p75] | GROUP_C median / mean / [p25,p75] |
|---|---:|---:|---:|
| mom20 | 0.191815 / 0.18778 / [0.137751, 0.221235] | 0.113185 / 0.127081 / [0.0733138, 0.166478] | 0.140687 / 0.151 / [0.0954335, 0.189917] |
| mom60 | 0.174948 / 0.17677 / [0.108115, 0.212397] | 0.223074 / 0.203534 / [0.133741, 0.268197] | 0.202609 / 0.237203 / [0.0975988, 0.329622] |
| mom120 | 0.0902069 / 0.280562 / [0.00961591, 0.439389] | 0.0115478 / 0.0445994 / [-0.198533, 0.294286] | 0.268008 / 0.281469 / [0.0849023, 0.423115] |
| r20 | 0.869126 / 0.809112 / [0.827717, 0.901832] | 0.746551 / 0.72014 / [0.596765, 0.786225] | 0.803158 / 0.766502 / [0.711637, 0.885337] |
| r60 | 0.796576 / 0.776238 / [0.682814, 0.857754] | 0.711475 / 0.725122 / [0.657127, 0.794147] | 0.704246 / 0.682552 / [0.583693, 0.807405] |
| r120 | 0.719895 / 0.700947 / [0.6213, 0.832275] | 0.451038 / 0.474304 / [0.331307, 0.646153] | 0.602426 / 0.606369 / [0.471166, 0.776913] |
| final_rs_score | 0.788185 / 0.760226 / [0.673, 0.841784] | 0.676333 / 0.64888 / [0.601583, 0.718787] | 0.675654 / 0.676487 / [0.582162, 0.780801] |
| b60_breakout_margin | 0.041392 / 0.0600504 / [0.0198144, 0.0852474] | 0.0136623 / 0.0268929 / [0.0113821, 0.0177277] | 0.0243243 / 0.0482289 / [0.0100554, 0.0725769] |
| box_width | 0.169807 / 0.164125 / [0.135875, 0.19347] | 0.141727 / 0.140957 / [0.131949, 0.15651] | 0.165414 / 0.160587 / [0.145821, 0.182667] |
| ma_dispersion | 0.0383938 / 0.0390403 / [0.0292977, 0.0496934] | 0.0318055 / 0.0376259 / [0.0218499, 0.0555039] | 0.0360556 / 0.0380377 / [0.0279893, 0.0478373] |
| direction_efficiency | 0.0890882 / 0.11119 / [0.061058, 0.122904] | 0.109253 / 0.111608 / [0.0700961, 0.137959] | 0.103093 / 0.114555 / [0.0468119, 0.15367] |
| vol_ratio_10_60 | 0.692127 / 0.658537 / [0.633341, 0.718577] | 0.734333 / 0.715136 / [0.70769, 0.750927] | 0.687093 / 0.667935 / [0.591683, 0.766256] |
| minvol_location | 0.124882 / 0.153989 / [0.0817421, 0.241172] | 0.101838 / 0.117797 / [0.0467808, 0.168889] | 0.152174 / 0.179551 / [0.0761218, 0.269143] |
| minimum_volume_ratio | 0.515638 / 0.468406 / [0.359793, 0.584032] | 0.4774 / 0.451944 / [0.420627, 0.503822] | 0.467606 / 0.466822 / [0.425082, 0.537574] |
| turnover20_mean | 1.80664e+08 / 2.35033e+08 / [1.3361e+08, 3.0112e+08] | 2.43982e+08 / 3.36041e+08 / [1.94645e+08, 2.91129e+08] | 1.65541e+08 / 2.65664e+08 / [1.21549e+08, 2.69176e+08] |
| holding_trading_days | 34 / 33.5 / [16, 34] | 33 / 28.8 / [26.25, 34] | 10 / 13.4176 / [7, 17] |
| MFE | 0.907607 / 1.35889 / [0.744271, 1.65145] | 0.554075 / 0.580616 / [0.436633, 0.682929] | 0.0634328 / 0.101643 / [0.0310207, 0.124009] |
| MAE | -0.0156351 / -0.0267523 / [-0.0451578, -0.0108924] | -0.00695321 / -0.00767195 / [-0.0121909, -0.00428295] | -0.0584192 / -0.0668299 / [-0.097747, -0.0271224] |
| giveback_from_peak | 0.338082 / 0.388069 / [0.138857, 0.533864] | 0.273326 / 0.233593 / [0.207453, 0.322529] | 0.0813842 / 0.0923945 / [0.0522143, 0.116977] |

## What distinguishes Top20?

| Feature | Top20 median | Remaining 91 median | Top20 mean | Remaining mean |
|---|---:|---:|---:|---:|
| final_rs_score | 0.690183 | 0.675654 | 0.704553 | 0.676487 |
| B60 breakout margin | 1.8078% | 2.4324% | 4.3472% | 4.8229% |
| box width | 14.8393% | 16.5414% | 15.2541% | 16.0587% |
| MA dispersion | 3.3683% | 3.6056% | 3.8333% | 3.8038% |
| direction efficiency | 0.0976 | 0.1031 | 0.1114 | 0.1146 |
| vol10/vol60 | 0.7173 | 0.6871 | 0.6868 | 0.6679 |
| MINVOL location | 0.1195 | 0.1522 | 0.1359 | 0.1796 |
| minimum-volume ratio | 0.4863 | 0.4676 | 0.4602 | 0.4668 |
| holding trading days | 33.5 | 10.0 | 31.15 | 13.42 |
| MFE | 71.8763% | 6.3433% | 96.9755% | 10.1643% |
| MAE | -1.1144% | -5.8419% | -1.7212% | -6.6830% |
| giveback from peak | 28.0681% | 8.1384% | 31.0831% | 9.2395% |

These are descriptive associations, not causal effects or threshold recommendations.

### A–G descriptive answers

**A. RS — modest separation, not a complete explanation.** Top20 final-RS median
was `0.6902` versus `0.6757` for the remaining trades; their median cross-section
percentile was `0.7770` versus `0.7396`. GROUP_A was clearly stronger
(`0.7882` median score), but GROUP_B (`0.6763`) was effectively level with
GROUP_C. **FACT:** high RS characterized the largest ten more than ranks 11–20.
**INFERENCE:** RS alone does not explain the full Top20 concentration.

**B. B60 — no stronger-margin pattern.** Top20 median breakout margin was
`1.8078%`, below the remainder's `2.4324%`; means were `4.3472%` and `4.8229%`.
**FACT:** the large winners were not systematically the entries farthest above
their previous 60-close high. This does not test whether B60 itself is necessary.

**C. FULL40 — mixed and mostly weak separation.** Top20 box width was somewhat
tighter (`14.8393%` median versus `16.5414%`), but MA dispersion (`3.3683%`
versus `3.6056%`) and direction efficiency (`0.0976` versus `0.1031`) were close.
Top20 vol10/vol60 was slightly higher, not more compressed (`0.7173` versus
`0.6871`). **INFERENCE:** only box width shows a modest descriptive compression
difference; the FULL40 submetrics do not jointly form a strong separator.

**D. MINVOL — location modestly lower; ratio indistinguishable.** Top20 median
location was `0.1195` versus `0.1522`, while minimum-volume ratio was `0.4863`
versus `0.4676`. **FACT:** the ratio is nevertheless a real hard filter in the
frozen strategy. **INFERENCE:** among trades already passing MINVOL, its ratio
has almost no descriptive power for identifying Top20.

**E. Holding path — dominant observed separation.** Top20 median holding time was
`33.5` sessions versus `10.0`; MFE was `71.8763%` versus `6.3433%`; MAE was
`-1.1144%` versus `-5.8419%`. Giveback was larger, not smaller (`28.0681%`
versus `8.1384%`), because the winners first accumulated much larger gains.
**FACT:** post-entry trend persistence and favorable excursion separate the
groups by far more than any measured entry feature. **INFERENCE:** the baseline's
right tail is associated with allowing a small set of positions to persist; this
does not establish that changing an exit would improve results.

**F. Time and symbol concentration.** Top20 contains `20` distinct symbols and no
repeat contributor. Exit-year distribution is `9` in 2024 and `11` in 2025, so
it is not a one-year-only result. However, `9/20` entered in September 2024
(`7` on 2024-09-24 and `2` on 2024-09-25), establishing meaningful cohort/time
concentration. The remaining entry-month counts were 2025-02:1, 2025-06:3,
2025-07:1, 2025-08:2, 2025-09:1, 2025-10:1 and 2025-11:2.

**G. Modules with little descriptive separation.** B60 breakout margin,
minimum-volume ratio, MA dispersion and direction efficiency were all close or
moved in the opposite direction from a simple “more is better” story. These are
the clearest `CANDIDATE_FOR_PHASE3_ABLATION` modules/submodules, but Phase 2 does
not show that they are useless and does not select replacement thresholds.

## Exact exit-reason attribution

| Exact exit reason | Trades | Win rate | Median return | Mean return | Total P&L | Median hold | Mean hold |
|---|---:|---:|---:|---:|---:|---:|---:|
| MARKET_MA20_X2 | 77 | 48.0519% | -0.1526% | 11.9043% | 1,050,977.00 | 11.0 | 14.95 |
| SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT | 34 | 35.2941% | -5.0508% | -1.7196% | -111,824.39 | 17.0 | 20.38 |

Exit reasons remain ledger-exact; no different semantics are merged.

`MARKET_MA20_X2` accounted for `18/20` Top20 trades and `1,271,764.28` of their
P&L. Across all trades it produced `1,050,977.00` net P&L, versus `-111,824.39`
for `SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT`. **FACT:** market-exit trades contain
the realized right tail. **UNRESOLVED:** the generic second ledger reason cannot
be reliably decomposed after the fact into individual MA30 exits versus other
set-change mechanics without changing the frozen ledger's reason semantics.

## MINVOL implementation fact

`minimum_volume_ratio <= 0.70` is a **hard filter**, not shadow-only. Frozen code
sets `passed = location_passed and ratio_passed`, and the candidate path requires
`minimum.passed`.

## Holding-excursion method

MFE uses observable daily highs and MAE daily lows after the entry open; peak and
trough use closes. The exit session contributes only the actual exit open, so no
post-exit high/low/close is consumed. Cash dividends and share multipliers are
carried forward in the underlying total-return path. Realized return and P&L remain
the frozen engine's completed-cycle values. Later rebalance cash flows do not alter
this underlying-path diagnostic.

## Frozen Top20

| Rank | Symbol | Entry signal | Exit execution | P&L | Return | Hold days |
|---:|---|---|---|---:|---:|---:|
| 1 | 300377.SZ | 2024-09-24 | 2024-11-19 | 216,566.15 | 226.6962% | 34 |
| 2 | 300497.SZ | 2025-11-06 | 2025-11-18 | 129,486.71 | 78.0818% | 7 |
| 3 | 300033.SZ | 2024-09-24 | 2024-11-19 | 118,387.69 | 124.7462% | 34 |
| 4 | 300437.SZ | 2025-11-06 | 2025-11-18 | 109,502.11 | 64.9338% | 7 |
| 5 | 300803.SZ | 2024-09-24 | 2024-11-19 | 94,276.47 | 95.6340% | 34 |
| 6 | 300348.SZ | 2024-09-24 | 2024-11-19 | 84,388.96 | 88.5646% | 34 |
| 7 | 301165.SZ | 2025-06-24 | 2025-10-09 | 74,354.74 | 46.9366% | 70 |
| 8 | 301093.SZ | 2025-06-23 | 2025-10-15 | 70,089.30 | 40.2699% | 75 |
| 9 | 300779.SZ | 2025-02-12 | 2025-03-25 | 66,690.95 | 45.3227% | 28 |
| 10 | 301141.SZ | 2025-06-04 | 2025-06-23 | 52,587.45 | 34.2694% | 12 |
| 11 | 300128.SZ | 2024-09-25 | 2024-11-19 | 51,213.73 | 53.6250% | 33 |
| 12 | 300324.SZ | 2024-09-24 | 2024-11-19 | 49,544.01 | 51.7725% | 34 |
| 13 | 300490.SZ | 2025-09-25 | 2025-10-15 | 47,352.06 | 26.8634% | 7 |
| 14 | 300457.SZ | 2025-08-28 | 2025-10-15 | 42,546.34 | 23.6979% | 27 |
| 15 | 300763.SZ | 2025-08-29 | 2025-10-15 | 30,839.56 | 18.9448% | 26 |
| 16 | 300459.SZ | 2024-09-25 | 2024-11-19 | 30,001.43 | 25.1544% | 33 |
| 17 | 300357.SZ | 2025-07-16 | 2025-09-22 | 28,256.10 | 19.0522% | 47 |
| 18 | 300182.SZ | 2024-09-24 | 2024-11-19 | 27,105.71 | 22.0232% | 34 |
| 19 | 300938.SZ | 2025-10-29 | 2025-11-18 | 26,245.02 | 15.3608% | 13 |
| 20 | 300442.SZ | 2024-09-24 | 2024-11-19 | 24,940.63 | 20.6102% | 34 |

## Phase 3 pre-registration candidates — not run

1. `BASELINE`
2. `minus MINVOL` — candidate because the passing-trade ratio barely separates groups
3. `minus B60` — candidate because breakout margin does not separate Top20
4. `minus FULL40` — isolate the mixed compression evidence
5. `no-RS-selection control` — isolate the modest aggregate RS separation
6. `minus market entry gate` — isolate cohort/timing exposure

This is a candidate list only. A final matrix must be frozen before any ablation
result is run; Phase 2 performs no ablation or parameter search.

## Unresolved

- Industry/sector concentration: no already-authorized classification input identified.
- Signed-P&L ordinary Gini: unstable for samples containing losses; positive-trade Gini is reported instead.
- Holding MFE/MAE measures the underlying first-entry path, not a cash-flow-weighted IRR for later top-ups/reductions.
- `SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT` cannot be split into finer exit causes from the frozen ledger alone.
