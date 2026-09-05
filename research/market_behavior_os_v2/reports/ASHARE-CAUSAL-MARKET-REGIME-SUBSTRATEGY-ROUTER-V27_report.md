# ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-V27

## Verdict

`CAUSAL_MARKET_REGIME_SUBSTRATEGY_ROUTER_HISTORICAL_GOAL_MET`

The completed-close market router materially improves the prior two-state V18
result.  Under shared sleeve capacity, daily entry caps, one active position
per symbol, T+1, legal-entry/exit, and 40 bp round-trip cost semantics, V27 has
1,213 completed trades over 2014-2023 (121.3 per year), +4.49% mean net trade,
73.45% win rate, 7.01% severe-loss10, and 13.30 mean holding sessions.

This is a retrospective Development result.  The 2021-2023 outcomes had been
observed in predecessor research and are reported as a post-observation
chronological challenge, not as pristine external Validation evidence.

## Economic routing contract

The market state is known at the security signal close.  It uses the causal PIT
market panel and compares completed 20-session and 60-session market-median
returns.

| Market substate | Causal condition | Frozen mechanism |
|---|---|---|
| Bear worsening | BEAR and median ret20 < median ret60 | Fast capitulation active demand, T10/H20 |
| Bear stabilizing, mild | BEAR and median ret20 >= median ret60 and median ret60 > -5% | Slow supply exhaustion, T10/H20 |
| Bear stabilizing, deep | Same acceleration but median ret60 <= -5% | Slow supply exhaustion only if stock ret20 <= -15% or last-five-session downside turnover <= 1% |
| Bull accelerating | BULL and median ret20 >= median ret60 | Delayed supply contraction, T10/H20 |
| Bull decelerating | BULL and median ret20 < median ret60 | Quiet-inventory continuation, T15/H15 |
| Transition | TRANSITION | Cash |

The deep-Bear gate has direct economic meaning.  A broad rebound inside a deep
market drawdown is not sufficient by itself: the stock must either have gone
through its own material washout or show very little recent turnover on down
sessions, indicating that fresh selling has contracted.

## Development-only bounded choice

Five interpretable deep-Bear alternatives were compared using 2014-2020 only.
Eligibility required at least 500 completed Development trades and at least six
positive Development calendar years.  The selector then used mean net return,
signal-date-equal return, severe-loss10, and simplicity in that order.

| Candidate | Trades | Mean net | Date-equal mean | Severe10 | Positive years | Eligible |
|---|---:|---:|---:|---:|---:|---|
| No additional gate | 1,451 | +5.11% | +1.86% | 5.10% | 6/7 | Yes |
| Deep market requires stock ret20 <= -15% | 409 | +5.99% | +2.85% | 4.65% | 5/7 | No |
| Deep market requires downside turnover <= 1% | 504 | +5.76% | +2.73% | 3.57% | 7/7 | Yes |
| Deep market requires both | 129 | +5.87% | +3.72% | 3.88% | 6/7 | No |
| Deep market requires either | 784 | +5.86% | +2.39% | 4.08% | 7/7 | **Selected** |

No 2021-2023 row participates in this selection.

## Results

| Year | Trades | Mean net trade | Portfolio return | Mean holding |
|---:|---:|---:|---:|---:|
| 2014 | 57 | +2.23% | +1.66% | 15.91 |
| 2015 | 129 | +7.74% | +10.08% | 11.24 |
| 2016 | 102 | +1.32% | +0.52% | 13.42 |
| 2017 | 71 | +1.91% | -0.06% | 17.23 |
| 2018 | 259 | +6.03% | +7.64% | 12.89 |
| 2019 | 28 | +3.83% | +1.41% | 14.14 |
| 2020 | 163 | +3.69% | +4.67% | 13.24 |
| 2021 | 108 | +4.49% | +4.44% | 13.71 |
| 2022 | 173 | +5.07% | +6.41% | 12.60 |
| 2023 | 123 | +3.39% | +2.88% | 13.30 |

Development 2014-2020 has 809 trades, +4.53% mean net trade, +9.60%
median net trade, 74.17% win rate, and 8.03% severe-loss10.  The
post-observation 2021-2023 challenge has 404 trades, +4.40% mean net trade,
+9.60% median, 72.03% win rate, and 4.95% severe-loss10.

The full chronological portfolio ends at 1.4688 NAV: +46.88% total return,
3.92% CAGR, -3.31% max drawdown, 1.386 Sharpe, and 5.77% average capital
utilization.  Low utilization explains why portfolio CAGR is much smaller than
the event-weighted trade return.

## Capacity and concentration

There are 1,630 routed raw completed trades.  Shared execution accepts 1,213
and skips 417: 413 from the per-sleeve daily-entry cap of 20 and four because
the symbol already has an active position.  Maximum active positions are 64 in
one sleeve during selection and 108 across both sleeves in the NAV replay.

The accepted population contains 1,007 unique symbols and 373 signal dates.
The top ten symbols account for 2.72% of trades.  Mean return remains +4.42%
after removing the five best signal dates.  Signal-date-equal mean return is
+2.91%, lower than the event-weighted mean because high-signal dates receive
less weight.

## Causality and implementation audit

- Market-state source after security decision: 0.
- Slow-lane feature source after its decision: 0.
- Slow-lane market source after its decision: 0.
- 2021-2023 rows used in candidate selection: 0.
- Signal/exit rows after 2023 included: 0.
- Same-symbol same-date duplicate identities: 0.
- Entry at or before signal: 0.
- Illegal entry executions: 0.
- Illegal target executions: 0.
- Illegal open exits: 0.
- Corporate-action coordinate-lineage violations: 0.
- T+1 same-day exits: 0.
- Overlapping active positions in the same symbol: 0.
- Negative cash: 0.
- Security outcomes reconstructed in V27: no; frozen ledgers only.

The runner initially failed closed when the slow-source Development ledger was
found to contain both BEAR and TRANSITION rows.  The valid implementation first
requires the frozen base market state to be BEAR and only then applies the
20-versus-60-session substate.  No accepted V27 result was produced before this
correction.

## Interpretation and stopping rule

The result supports the user's economic diagnosis: one generic bull/bear switch
is too coarse.  The market state should select the mechanism, while the stock
setup still has to express the matching supply-demand structure.

The historical aggregate goal is met, and 2021, 2022, and 2023 each exceed +3%
mean net trade after shared capacity.  However, not every earlier year exceeds
+3% individually: 2014, 2016, and 2017 are lower, and the 2017 portfolio return
is slightly negative.  Therefore this is not evidence that every regime/year
is solved.  Further changes based on the already-seen 2021-2023 outcomes would
be post-hoc rescue.  The defensible next step is to freeze V27 and evaluate it
prospectively rather than continue tuning those years.

## Artifacts

Large deterministic artifacts are stored under:

`/Volumes/quant/CY_quant_research/ashare_causal_market_regime_substrategy_router_v27`

The external result hash is:

`d50ea992529a2a202d8d17ed7eb5dc0908291224a74948616aa84a39fcf65537`

Targeted deterministic tests: `4 passed`.
