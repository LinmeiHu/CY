# ASHARE-PANIC-GAP-DOWN-FULL-ABSORPTION-REVERSAL-V1

## Verdict

`SIMPLE_TRADE_LEVEL_EDGE_WITH_CAPACITY_CONCENTRATION`

This independent lane satisfies the requested event-level research gate over 2014–2023: 840 completed trades, 84.0 per year on average, and +4.70% mean net return after 40 bp round-trip costs. All ten calendar-year trade means are positive. It is not a collapse-gap repair, true-gap fill, limit-up chase, or machine-learning strategy.

The result is not yet an unconditional deployment verdict. Half of all completed trades occur on the five busiest signal dates. A frozen K10-per-board replay accepts 446 trades and earns +2.34% per accepted trade, +5.03% CAGR, with -15.31% maximum drawdown. Capacity therefore dilutes the event-level result materially.

## Economic sequence and simple rule

The mechanism is an observable transfer of inventory after forced selling:

1. The stock has lost at least 10% over the preceding 20 completed sessions.
2. The current session opens at least 1% below the preceding close and makes a new five-session low.
3. Completed-session turnover is at least the preceding 20-session mean.
4. Despite the shock, the completed close is at or above the preceding session high and lies in the upper 30% of the current range.
5. The stock is fully tradable, non-ST, hard-valid, and not closed at its upper price limit. The preceding 20 market sessions are contiguous, tradable, and coordinate-valid.

Only the first event for a symbol within the frozen 20-session cooldown is retained. All conditions are known at the signal-session close.

Entry is the first legal executable open strictly after the signal, no later than the third subsequent market session. Exit is a known-at-entry +10% target from the first sellable session, otherwise the first legal open after 20 completed trading sessions. Round-trip cost is 40 bp. A-share T+1, suspension, price-limit, and corporate-action coordinate rules remain binding.

## Chronology

- Semantic/selection block: 2014–2018.
- Chronological confirmation: 2019–2021.
- Frozen validation: 2022–2023.
- Repository 2024+ data opened: **NO**.

The four frozen profiles were H10, H20, T10/H20 without a failure stop, and T10/H20 with a signal-low failure stop. Selection used only the equal-year 2014–2018 score. `T10_H20_NO_STOP` was selected before 2019–2021 confirmation and before 2022–2023 validation.

## Event-level results

| Year | Completed trades | Mean net |
|---:|---:|---:|
| 2014 | 11 | +5.68% |
| 2015 | 67 | +4.89% |
| 2016 | 70 | +1.33% |
| 2017 | 28 | +0.54% |
| 2018 | 147 | +6.92% |
| 2019 | 134 | +3.75% |
| 2020 | 94 | +5.52% |
| 2021 | 67 | +2.76% |
| 2022 | 200 | +6.09% |
| 2023 | 22 | +0.60% |
| **2014–2023** | **840** | **+4.70%** |

Combined median net return is +9.60%, win rate 77.98%, +10% target realization 66.19%, severe-loss10 7.74%, and mean holding 12.14 market-session indices. Main Board contributes 597 trades at +4.51%; ChiNext contributes 243 at +5.20%.

The event-level threshold is passed by the ten-year aggregate, not by requiring every individual year to exceed +3%. The weakest years are still positive, but 2017 and 2023 are economically thin.

## Concentration and portfolio reality

There are 231 unique signal dates. The five busiest dates contain 50.0% of trades: the strategy often identifies a cross-sectional inventory-transfer episode after a market-wide sell-off rather than 840 independent timing opportunities. Excluding those five dates, mean net return falls to +2.41%; signal-date-equal mean is +1.65%.

The frozen K10-per-board, 50/50-sleeve replay has:

- 446 accepted trades and 394 capacity skips;
- +2.34% accepted-trade mean and +9.56% median;
- +63.32% total return and +5.03% CAGR;
- -15.31% maximum drawdown and 0.614 Sharpe;
- 7 positive calendar years out of 10;
- 11.87% average capital utilization.

This is profitable overall, but it does not preserve the requested +3% trade mean after realistic K10 capacity. The correct interpretation is a validated simple event-level edge with a meaningful, unresolved allocation problem.

## Causality and implementation audit

All 858 frozen Development/Validation candidate identities were joined back to the authoritative daily PIT source and checked mechanically.

- Missing daily identity: 0.
- Required-condition failures: 0.
- `available_at > decision_at`: 0.
- Signal-date fill: 0.
- Exit at or before entry/T+1 violation: 0.
- Unknown exit reason: 0.
- Target-price mismatch: 0.
- 40 bp net-cost mismatch: 0.
- Post-2023 signal or exit: 0.
- Repository 2024+ data opened: **NO**.

No detector field uses a future trough, later recovery, future target hit, or post-signal classification. A long calendar gap between entry and exit can occur when the security is suspended; the H20 clock counts completed executable sessions rather than pretending a fill occurred during suspension.

## Frozen artifacts

- Contract SHA256: `bb3bd8bcc0a81b0f242a125b1b2df40ab505d2e4aa5e32b01e5a1a04e63714a7`
- Development candidate SHA256: `c4d4d5a4feef587d6ec5ea4f69b39f0992e4cb758bd1336c4740f1bde173dd85`
- Development outcomes SHA256: `c13281f9702f6b89831a514810f281745637819e5860fda36810c1bfb548496f`
- Validation candidate SHA256: `791dec7f430fb8d2fdee22e77f77745b908f87fac3b9754f0a09c9a2a2f3464f`
- Validation outcomes SHA256: `44474f1a5e88c0a747b65daa2fd9356a18e7fcd7aa34ff93c7734ad8fad95130`

The large candidate, outcome, chart, and portfolio artifacts remain under `/Volumes/quant/CY_quant_research/ashare_panic_gap_down_full_absorption_reversal_v1`. The repository stores only the compact contract, result, and report.
