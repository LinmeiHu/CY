# ASHARE-CAUSAL-BULL-BEAR-DUAL-MECHANISM-SHORT-V16

`DUAL_REGIME_HISTORICAL_TRADE_LEVEL_GOAL_MET`

## Economic contract

The strategy uses the causal market state known at each completed signal-session close.

- **BEAR:** broad 20/60-session medians and breadth are non-positive, but 20-session breadth is improving versus five completed sessions earlier. Trade the frozen fast-capitulation active-demand signal: prior ten-session return at most -8%, then the exact OAI demand ignition. Capacity rank favors stronger stock-versus-industry recovery, stronger close versus the prior ten-session high, and a stronger signal close.
- **BULL:** broad 20/60-session medians and breadth are positive. Trade the exact delayed supply-contraction sequence: non-extended three-session demand impulse, immediate low-turnover inside day, then the first tick-strict completed close above the inside-day high within five sessions.
- **TRANSITION:** hold cash.

Both lanes enter at the next legal open, target +10%, otherwise exit at the next legal open after H20, and charge 40 bp round trip. Market state is never defined by a future index return.

## Historical result, 2014–2023

| Metric | Result |
|---|---:|
| Completed trades | 806 |
| Average trades/year | 80.6 |
| Mean net trade | +3.176% |
| Median net trade | +9.600% |
| Win rate | 70.47% |
| Target hit | 62.66% |
| Severe loss <= -10% | 12.53% |
| Average holding | 12.86 sessions |
| Signal dates | 315 |
| Signal-date-equal mean | +2.141% |
| Top-five dates / positive PnL | 21.44% |
| Mean excluding best five dates | +2.198% |

The shared-capacity replay accepted all 806 completed trades. Maximum active positions during selection were 40, below K75 per sleeve; there were no daily-cap skips.

## Annual trade evidence

| Year | Trades | Mean net | Avg hold |
|---|---:|---:|---:|
| 2014 | 56 | +2.71% | 12.91 |
| 2015 | 135 | +6.36% | 10.71 |
| 2016 | 66 | -0.15% | 11.95 |
| 2017 | 35 | +1.81% | 18.43 |
| 2018 | 149 | +3.19% | 15.05 |
| 2019 | 21 | +5.21% | 10.52 |
| 2020 | 72 | +2.73% | 12.89 |
| 2021 | 115 | +1.62% | 12.78 |
| 2022 | 127 | +3.74% | 11.57 |
| 2023 | 30 | +1.74% | 14.27 |

The pooled goal is met, but this is not a claim that every calendar year exceeds 3%. The weak 2016 result and the 2017 average holding above 15 sessions remain visible limitations. Every year from 2019 through 2023 has a positive mean trade return.

## Portfolio

The portfolio uses separate 50% Main Board and 50% ChiNext sleeves, a 10% sleeve-NAV entry-date cohort budget, a 2.5% sleeve-NAV per-name cap, no leverage, and no cross-sleeve transfer.

- Total return: +21.17%
- CAGR: +1.94%
- Max drawdown: -4.00%
- Sharpe: 0.860
- Average capital utilization: 4.06%
- 2017 portfolio return: -0.79%; all other calendar years are positive.

Portfolio efficiency remains low because the signal is episodic and capital mostly stays in cash. The result is a historical strategy candidate, not a deployment claim.

## Causal and execution audit

All required counts are zero:

- signal feature or market-regime timestamp after the signal decision;
- missing capacity-rank input;
- bull setup at/after signal or trigger beyond five sessions;
- earlier valid tick-strict bull breakout;
- entry at/before signal or same-day exit;
- illegal limit-state entry, target, or open exit;
- corporate-action coordinate-lineage violation;
- duplicate event or simultaneous same-symbol position;
- negative cash, leverage, or open position at the end;
- post-2023 signal or outcome access.

Two apparent earlier bull breakouts were machine-epsilon differences in adjusted coordinates. The raw prices were exactly equal to the setup high (14.30 versus 14.30 and 23.27 versus 23.27), so the tick-strict earlier-breakout count is zero.

## Governance and limitations

The BEAR ranking was selected on 2014–2020. The BULL T10/H20 translation was selected on 2014–2018 and checked on 2019–2021 before its 2022–2023 diagnostic was opened. No 2022–2023 observation changed either lane or the combination rule.

The BULL lane alone deteriorated in 2022 and 2023; the combined strategy remains positive because the independently frozen BEAR mechanism dominates those years. This is disclosed rather than treated as proof that the BULL lane is independently validated. Also, 2022–2023 were observed in predecessor work, so a genuinely new future period is still required for external confirmation.

Large ledgers and NAV remain under `/Volumes/quant/CY_quant_research/ashare_causal_bull_bear_dual_mechanism_short_v16`.
