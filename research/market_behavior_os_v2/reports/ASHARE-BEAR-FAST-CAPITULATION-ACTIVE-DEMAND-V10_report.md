# ASHARE-BEAR-FAST-CAPITULATION-ACTIVE-DEMAND-V10

## Classification

`FULL_HISTORY_HISTORICAL_CANDIDATE_REQUIRES_NEW_FUTURE_CHALLENGE`

This is a non-gap, long-only reversal lane. It is not a deployment claim. The 2022–2023 outcomes had already been observed during the broader research process, so they are reported as post-observation robustness evidence only. Repository 2024+ data were not opened for this experiment.

## Economic sequence and causal regime routing

The strategy distinguishes market states at the completed signal close. In a causal broad `BEAR` state, it looks for the first active-demand ignition after a fast individual liquidation. It trades only when all-market positive-ret20 breadth is above its value five completed market sessions earlier. In `BULL` and `TRANSITION` states it holds cash.

The stock must satisfy the exact frozen OAI signal and must also have fallen at least 8% over the ten completed sessions ending immediately before the signal. This extra condition separates fast capitulation from a slow grinding decline. Entry is at the first legal open after the signal; no signal fills on its own bar.

## Frozen simple rule

1. Causal broad market state is `BEAR` at the completed signal close.
2. Completed market positive-ret20 breadth is above its value five completed market sessions earlier.
3. Exact OAI: ret20 <= -10%, signal return >= +5%, close above the prior-five-session high, at least normal twenty-session turnover, close location >= 70%, and no upper-limit close.
4. The ten-session return ending immediately before the signal is <= -8%.
5. Enter next legal open; take +20%, otherwise exit after H60 at the next legal open; 40 bp round-trip costs.

Capacity is K75 per 50/50 board sleeve, at most twenty new positions per sleeve/date. Same-date ranking uses only completed signal-bar close location, then turnover ratio. Unused capital remains cash; there is no leverage or cross-sleeve transfer.

## Results

| Year | Accepted trades | Mean net trade | Portfolio return |
|---:|---:|---:|---:|
| 2014 | 2 | +4.41% | +0.06% |
| 2015 | 52 | +15.48% | +5.17% |
| 2016 | 59 | +7.85% | +3.45% |
| 2017 | 32 | +4.86% | +0.95% |
| 2018 | 146 | +1.52% | +0.85% |
| 2019 | 5 | +12.39% | +0.63% |
| 2020 | 38 | +8.41% | +2.48% |
| 2021 | 85 | +3.01% | +1.83% |
| 2022* | 110 | +9.09% | +6.24% |
| 2023* | 18 | +6.88% | +1.06% |

`*` Post-observation robustness diagnostic, not pristine validation.

Capacity-accepted completed trades are 547, or 54.7 per year on average. Mean/median net trade returns are +6.24%/+19.60%; win rate is 63.80%; severe_loss10 is 19.20%. All ten annual trade means are positive.

The candidate is not entirely explained by the best signal dates: there are 133 distinct signal dates, the five best dates contribute 30.94% of positive trade PnL, and the mean remains +3.82% after removing every trade from those five dates. Date-equal mean is lower at +2.49%, so systemic-date clustering remains an explicit limitation.

The primary 1/75-per-position portfolio produces 24.98% total return, 2.26% CAGR, -6.04% MaxDD, 0.672 Sharpe, and 5.96% average utilization. The trade edge therefore clears the requested signal-level hurdle, but capital efficiency remains modest because opportunities are state-dependent and the selected translation can hold for sixty sessions.

## Translation comparison

The exact previously registered T10/H20 translation was reproduced with zero differences against all authoritative 2014–2021 rows. It retained 551 capacity-accepted trades and +3.43% average net return, but fell to +1.85% after removing the best five signal dates and produced only 1.09% CAGR. It is rejected in favor of the slower T20/H60 translation.

## Causal audit

- The regime and current breadth use only the completed signal session.
- The comparison breadth observation is five completed market sessions earlier.
- `prior10_return` ends on the completed session before the signal.
- Same-date ranking uses only completed signal-bar fields.
- Entry occurs strictly after the signal; T+1, suspension, limit and QD-010 semantics are unchanged.
- No future trough, final low, later market classification, or post-entry outcome determines signal identity.
- All causal timestamp, cash, capacity and duplicate-position audit counts are zero.
- Repository 2024+ data were not opened.

## Frozen visual audit

A 30-page chart book was generated after the rule was frozen. It takes the worst, median and best accepted trade from each year where possible (two trades in 2014, plus one extra interior 2018 case), and marks the 120-session pre-signal history, prior-ten-session fast-decline window, signal, entry, exit, +20% target and causal market breadth. The charts are diagnostic and did not alter the rule.

`output/pdf/ASHARE_BEAR_FAST_CAPITULATION_ACTIVE_DEMAND_V10_30_TRADE_AUDIT.pdf`

SHA256: `256c615851c3a56bd9a351f4c05f8de21c27f6fef53794e61e41a8ac8358e976`

## Decision

The requested historical target is met at the capacity-accepted trade level: average frequency is above fifty per year, average net return is above 3%, every annual mean is positive, 2023 is positive, and the result remains above 3% after removing the five best signal dates. Because later-period outcomes were already observed while developing the lane, the correct next action is to freeze the rule and wait for one genuinely new future challenge rather than tune it further on 2014–2023.
