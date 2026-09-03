# Champion candlestick rule discovery V1--V3

Updated 2026-09-03.

## Executive conclusion

No candlestick entry or exit rule earned incorporation into the frozen Industry
Diffusion + Weekly Low-MAX champion. The existing champion remains unchanged at
the authoritative 2018--2023 development result: 16.34% annualized return,
122.43% total return, -25.77% maximum drawdown, and 0.731 daily Sharpe.

The repeated result is economically informative: price-path failure rules do
identify risk and reduce severe-loss incidence, but the champion's losing paths
also contain enough later recovery that fixed early, middle, late, and
cohort-synchronous exits lower expected payoff. Entry-time candle shapes overlap
too heavily between winners and losers to provide a stable admission rule.

This is consumed-development, post-hoc visual discovery. It is not independent
confirmation. Post-2023 outcomes and CY-011 were not read.

## Chart review protocol

The review used corporate-action-consistent daily coordinates and the frozen
champion trade ledger. Each panel displays 40 sessions before the signal and up
to 25 after it, with red up-candles, green down-candles, relative amount, and
signal/entry/exit markers. No future bar was used in an entry rule; checkpoint
exits execute at the next legal sellable open.

- Round 1: every 2018--2019 trade, 730 charts on 37 sheets.
- Round 2: every 2020 trade, 478 charts on 26 sheets.
- Total individually inspected: 1,208 charts on 63 sheets.
- Outcome strata: 2018--2019 had 116 severe losses, 258 normal losses, 220
  normal wins, and 136 extreme wins; 2020 had 75, 144, 134, and 125.

The visual summaries were frozen before each subsequent outcome aggregation.

## Repeated visual structure

1. Severe losers often entered near a local or rounded rebound peak and later
   lost the signal low or MA10/MA20. This appearance was real but not sufficient:
   many eventual winners temporarily showed the same failure.
2. Winners often emerged from tight bases, shallow pullbacks, or the start of a
   reversal and then stayed above rising short averages. Some strong winners
   began below MA20, invalidating a simple above-MA admission rule.
3. The cleanest winner/loser separation appeared after entry, not on the signal
   candle. Unfortunately, fixed d3/d5/d10/d15 exits monetized the separation too
   early and forfeited rebound convexity.
4. Losses and wins visibly clustered by signal date. That motivated the final
   cohort-synchronous test; the effect was not stable through 2020--2021.

## Iteration 1 -- entry candles and early exits

Six exact rules were frozen after the 2018--2019 review and pruned on 2020.

| Rule | 2018--2019 payoff delta | 2020 payoff delta | Severe-loss improvement, 2018--2019 / 2020 | Decision |
|---|---:|---:|---:|---|
| Admission: >=5% above MA20 and r5 >=2% | +0.031 pp | +0.078 pp | +1.801 / +1.777 pp | Too small; gate failed |
| Admission: ATR20 >=4% and signal body >=1% | +0.592 pp | -0.086 pp | +2.588 / +0.924 pp | Sign reversed |
| d3 close below signal low | -0.363 pp | -0.907 pp | +5.616 / +5.230 pp | Return adverse |
| d3 close below MA10 | -0.315 pp | -1.217 pp | +7.123 / +6.695 pp | Return adverse |
| d3 return <= -3% | -0.224 pp | -0.969 pp | +4.110 / +3.766 pp | Return adverse |
| d5 close below signal low | -0.208 pp | -0.437 pp | +5.068 / +5.021 pp | Return adverse |

No rule survived, so 2021--2023 was not opened for this family.

## Iteration 2 -- middle and late lifecycle exits

Five d10/d15 rules were frozen after all 2018--2020 charts were reviewed. The
generation period was 2018--2020; 2021 was a boundary-purged pruning period.

| Rule | 2018--2020 payoff delta | 2021 payoff delta | Severe-loss improvement, generation / prune | Decision |
|---|---:|---:|---:|---|
| d10 nonpositive and below MA10 | -0.220 pp | -0.415 pp | +3.560 / +2.727 pp | Return adverse |
| d10 below signal low | -0.254 pp | -0.295 pp | +3.311 / +2.500 pp | Return adverse |
| d10 run-up >=8%, then >=5% off peak | -0.455 pp | +0.159 pp | +1.738 / +2.727 pp | Generation adverse; prune effect too small |
| d15 nonpositive and below MA10 | -0.049 pp | -0.168 pp | +0.828 / +2.045 pp | Return adverse |
| d15 run-up >=10%, then >=7% off peak | -0.202 pp | -0.014 pp | +0.414 / +2.045 pp | Return adverse |

No rule survived; fixed 2022--2023 validation remained unopened.

## Iteration 3 -- synchronized cohort failure

One two-checkpoint translation was frozen: exit the remaining cohort after the
d5 close if at least 70% of executed names were below their own signal low;
otherwise exit after d10 if cohort median close-from-entry was at most -3%.
Execution was the next legal sellable open.

| Generation block | Triggered cohorts / trades | Payoff delta | Severe-loss improvement | Decision |
|---|---:|---:|---:|---|
| 2018--2019 | 24 / 240 | +0.009 pp | +1.781 pp | Economically negligible |
| 2020--2021 | 26 / 260 | -0.323 pp | +2.694 pp | Sign reversed |

The generation gate failed. Therefore 2022--2023 stayed unopened and no full
portfolio replay was authorized.

## Final rule decision

- Add no new buy rule.
- Add no fixed candlestick stop or profit-protection rule.
- Add no cohort-synchronous candlestick exit.
- Preserve all exact rejected definitions so they are not recycled with nearby
  thresholds.
- Keep the frozen champion unchanged. Its 16.34% annualized development result
  is the honest current answer; this study did not improve it.

Candlestick paths remain useful for explanation and risk monitoring, but the
tested rules do not earn deployment. The next high-value research capital should
return to a genuinely different Alpha source--currently frozen cross-sectional
dispersion science--rather than continue threshold-mining this champion's
entry/exit charts.

## Reproducibility

- Frozen visual protocol: `ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V1_spec.json`
- Round-1 rules: `ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V1_round1_rules.json`
- Frozen lifecycle protocol: `ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V2_spec.json`
- Frozen cohort protocol: `ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V3_spec.json`
- Chart generator and descriptors: `run_ashare_champion_candlestick_rule_discovery_v1.py`
- Screens: `screen_ashare_champion_candlestick_rules_v1.py`,
  `screen_ashare_champion_candlestick_rules_v2.py`, and
  `screen_ashare_champion_candlestick_rules_v3.py`
- External chart root:
  `/Volumes/quant/CY_quant_research/champion_candlestick_rule_discovery_v1/`
