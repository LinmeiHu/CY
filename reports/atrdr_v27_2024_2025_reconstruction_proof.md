# ATRDR V27 2024-2025 reconstruction proof

Status: **FAIL — exact population closure is not yet achieved.** This file records the bounded reconstruction actually run; it is not a FULL claim.

## Frozen rule evidence

- V27 contract SHA256: `8fdaf43e7d0f44cb5607fb1a37d4a12fefbf43cb1ededf334bc5bf474f0a20a7`.
- Fast mother rule: the outcome-blind OAI specification already proven on the complete 2014-2023 interval (3,433/3,433 identities).
- Slow mother rule: exact recovered producer SHA256 `4c4992e333c9f7931ca84454e1f71742cf49bcfa8ff333ba8876cc202f351870`.
- Router semantics: BEAR worsening uses Fast when `market_median_ret20 < market_median_ret60`; BEAR stabilizing uses Slow when `market_median_ret20 >= market_median_ret60`, plus the frozen deep-market gate.
- No return, exit, PnL, or other outcome field was used to choose a threshold.

## Inputs and time anchors

The run used the QD-010 exact daily panel from 2022 through the 2026Q1 exit tail. Required columns include symbol, trade date/calendar index, completed-close `decision_at`/`available_at`, coordinate OHLC, turnover, validity/lineage flags, industry identity, trading state, and limit prices. Market state is anchored at the completed signal close; entry and all outcome evaluation begin strictly after the signal session.

Fast thresholds are: prior 20-session return at most -10%, signal return at least +5%, break above prior-five high, turnover ratio at least 1.0, close location at least 0.70, 20-session per-symbol cooldown, BEAR state, five-session breadth improvement, and prior-ten return at most -8%. Slow thresholds are: prior-20 return at most -8%, non-lower last-five low, declining downside turnover, signal return 2%-7%, close location at least 0.75, break above prior-five high, turnover expansion 1.0-2.5, 20-session cooldown, and the frozen deep-market either gate.

## Population comparison

- Market calendar identity: 485/485 dates.
- Rebuilding market values directly from the compact downstream daily panel is not equivalent: 483 ret20 values, 484 ret60 values, and 17 regime labels differ. This compact panel is therefore not accepted as the missing market producer's zero point.
- With the frozen non-outcome market values used only for comparison isolation, the reconstructed Slow population is exact: 674 new / 674 golden, missing 0, extra 0.
- With the same comparison isolation, Fast route output is 161 new / 151 golden, missing 0, extra 10. First extra: `OAI-20240129-300835.SZ`.
- Bull-accelerating and Bull-decelerating post-2023 source generation are not yet wired into production.

First difference: the market-feature producer value for `2024-01-02`; downstream Fast first identity difference is `OAI-20240129-300835.SZ`.

Conclusion: this missing producer remains unaccepted. Frozen candidates are never read by production.
