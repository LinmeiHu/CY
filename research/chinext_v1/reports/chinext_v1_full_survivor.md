# ChinNext V1 full current-survivor exploratory replay

> **CURRENT SURVIVOR UNIVERSE / NOT POINT-IN-TIME / SURVIVORSHIP BIASED / NOT VALID FOR FINAL PERFORMANCE CLAIMS**
>
> This is an exploratory current-survivor replay, not a PIT backtest and not valid
> for final historical performance claims. All strategy parameters are frozen.

## Universe and data coverage

- UNIVERSE: current-survivor manifest, NON-PIT, SURVIVORSHIP BIASED
- DATE_RANGE: `2024-01-02 .. 2025-12-31`
- RAW_UNIVERSE_COUNT: `1398`
- DATA_FOUND_COUNT: `1388`
- HISTORY_VALID_COUNT: `1361`
- LIQUIDITY_VALID_COUNT: `1314`
- FINAL_ELIGIBLE_COUNT: `1314` symbols eligible on at least one day
- AVERAGE_DAILY_FINAL_ELIGIBLE: `692.40`
- FAILURE_REASON_COUNTS: `{"insufficient_history": 27, "known_risk_warning_without_any_eligible_day": 0, "missing_data": 10, "other_daily_validity_failure": 0, "turnover_failure": 47}`
- DAILY_FAIL_CLOSED_REASON_COUNTS: `{"insufficient_or_noncontiguous_history": 29159, "invalid_price_or_volume": 761, "known_risk_warning": 12646, "missing_daily_row": 21313, "suspended_or_not_tradable": 3, "turnover20_below_threshold": 278332}`
- KNOWN_RISK_WARNING_SYMBOL_COUNT: `56` (ever observed `is_st=true`; complete taxonomy remains unverified)
- MARKET_GATE_ACTIVE: `YES`, exact `399102.SZ`, no fallback

RS percentiles are computed each day over the complete basic-eligible cross section
from the full manifest universe, never over breakout candidates or the prior sample.
Coverage counts mean a symbol passed the named gate on at least one replay day;
daily counts are reported separately and every failure remains fail closed.

The pre-run strategy-module SHA256 was
`dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
and is unchanged. Changes to the smoke runner are accounting labels and the explicit
full-universe selection mode only; the frozen configuration is identical.

## Signals and execution

- PRICE_STRUCTURE_SIGNAL_COUNT: `1324`
- MINVOL_PASS_COUNT: `1175`
- BREAKOUT_VOLUME_SHADOW_PASS_COUNT: `1102`
- FINAL_ENTRY_CANDIDATE_COUNT: `1175`
- BUY_EXECUTION_COUNT: `261`
- ENTRY_BUY_EXECUTION_COUNT: `121`
- REBALANCE_BUY_LEG_COUNT: `140`
- SELL_EXECUTION_COUNT: `214`
- COMPLETED_ROUND_TRIP_COUNT: `111`
- REBALANCE_SELL_LEG_COUNT: `103`
- T1_BLOCKED_EXIT_COUNT: `11`
- FAILED_OPEN_EXECUTION_COUNT: `0`
- SAME_DAY_FILL_COUNT: `0`

Completed round trips are full position lifecycles. Partial CAP/SET resize sells are
reported separately and are not counted as completed trades.

## Cost and performance

> **PERFORMANCE BEFORE REALISTIC COSTS** — the frozen replay applies its original
> fixed 10 bps per filled side, but does not separately model stamp duty, slippage,
> open-auction queueing or market impact.

- COMMISSION/COST: fixed 10 bps per filled side (same as smoke)
- SLIPPAGE: none separately modeled
- STAMP_DUTY: none separately modeled
- TOTAL_RETURN: `105.2422%`
- ANNUALIZED_RETURN: `43.6891%`
- MAX_DRAWDOWN: `-26.2272%`
- VOLATILITY: `30.0192%` annualized daily NAV volatility
- SHARPE: `1.3490988068959484` (daily arithmetic return, 244 sessions, zero risk-free rate)
- WIN_RATE: `44.1441%` completed round trips
- AVERAGE_TRADE_RETURN: `7.7312%`
- MEDIAN_TRADE_RETURN: `-1.0750%`
- PROFIT_FACTOR: `2.357021792682277` (completed-cycle realized gains / absolute realized losses)
- TURNOVER: `26.3511x` total traded notional / average NAV

The fixed 10 bps cost is not a full realistic A-share cost model. Results omit
separate stamp duty, slippage, queueing impact and market impact.

## Exposure

- AVERAGE_HOLDINGS: `4.052`
- MEDIAN_HOLDINGS: `1.000`
- MAX_HOLDINGS: `10`
- AVERAGE_INVESTED_RATIO: `40.3915%`
- MEDIAN_INVESTED_RATIO: `10.0757%`
- PERCENT_DAYS_FULLY_INVESTED: `28.4536%` (`invested_ratio >= 95%`)
- PERCENT_DAYS_FLAT: `47.2165%` (`holdings == 0`)

## Year by year

| Year | Return | Max drawdown | Round trips | Win rate | Avg invested | Avg holdings |
|---|---:|---:|---:|---:|---:|---:|
| 2024 | 49.0494% | -23.5423% | 38 | 31.5789% | 23.5884% | 2.364 |
| 2025 | 37.7008% | -10.1769% | 73 | 50.6849% | 57.1254% | 5.733 |

## Monthly exposure diagnostics

| Month | Avg holdings | Avg invested | New entries |
|---|---:|---:|---:|
| 2024-01 | 0.000 | 0.00% | 0 |
| 2024-02 | 0.000 | 0.00% | 0 |
| 2024-03 | 0.952 | 8.94% | 2 |
| 2024-04 | 0.350 | 3.52% | 4 |
| 2024-05 | 6.400 | 63.62% | 7 |
| 2024-06 | 0.000 | 0.00% | 0 |
| 2024-07 | 0.000 | 0.00% | 0 |
| 2024-08 | 0.000 | 0.00% | 0 |
| 2024-09 | 2.105 | 20.89% | 11 |
| 2024-10 | 9.944 | 99.04% | 0 |
| 2024-11 | 5.143 | 52.59% | 0 |
| 2024-12 | 4.091 | 40.62% | 14 |
| 2025-01 | 0.111 | 1.07% | 1 |
| 2025-02 | 6.944 | 69.28% | 10 |
| 2025-03 | 6.429 | 64.73% | 4 |
| 2025-04 | 0.143 | 1.44% | 1 |
| 2025-05 | 2.263 | 22.19% | 5 |
| 2025-06 | 7.850 | 78.18% | 21 |
| 2025-07 | 10.000 | 99.65% | 5 |
| 2025-08 | 10.000 | 99.40% | 3 |
| 2025-09 | 9.955 | 99.13% | 9 |
| 2025-10 | 2.706 | 26.91% | 4 |
| 2025-11 | 4.650 | 46.40% | 8 |
| 2025-12 | 5.652 | 56.31% | 12 |

## 50-symbol versus full survivor

| Metric | 50-symbol | Full-survivor |
|---|---:|---:|
| entry_candidates | 37 | 1175 |
| completed_round_trips | 25 | 111 |
| average_holdings | 1.1093 | 4.0515 |
| average_invested_ratio | 11.2026% | 40.3915% |
| total_return | 19.6955% | 105.2422% |
| annualized_return | 9.4867% | 43.6891% |
| max_drawdown | -6.1811% | -26.2272% |
| win_rate | 44.0000% | 44.1441% |
| turnover | 5.5890 | 26.3511 |

This comparison isolates the effect of using the full daily eligible cross section;
it does not remove current-survivor bias.

## Entry and P&L concentration

### Top 20 symbols by entry count

| Rank | Symbol | Entries |
|---:|---|---:|
| 1 | 300003.SZ | 2 |
| 2 | 300035.SZ | 2 |
| 3 | 300054.SZ | 2 |
| 4 | 300092.SZ | 2 |
| 5 | 300138.SZ | 2 |
| 6 | 300285.SZ | 2 |
| 7 | 300357.SZ | 2 |
| 8 | 300479.SZ | 2 |
| 9 | 300487.SZ | 2 |
| 10 | 300627.SZ | 2 |
| 11 | 300733.SZ | 2 |
| 12 | 300770.SZ | 2 |
| 13 | 301048.SZ | 2 |
| 14 | 301096.SZ | 2 |
| 15 | 301213.SZ | 2 |
| 16 | 301301.SZ | 2 |
| 17 | 301498.SZ | 2 |
| 18 | 300001.SZ | 1 |
| 19 | 300009.SZ | 1 |
| 20 | 300014.SZ | 1 |

### Top 20 symbols by P&L contribution

| Rank | Symbol | P&L |
|---:|---|---:|
| 1 | 300377.SZ | 216,566.15 |
| 2 | 300497.SZ | 129,486.71 |
| 3 | 300033.SZ | 118,387.69 |
| 4 | 300437.SZ | 109,502.11 |
| 5 | 300803.SZ | 94,276.47 |
| 6 | 300348.SZ | 84,388.96 |
| 7 | 301165.SZ | 74,354.74 |
| 8 | 301093.SZ | 70,089.30 |
| 9 | 300779.SZ | 66,690.95 |
| 10 | 301141.SZ | 52,587.45 |
| 11 | 300699.SZ | 51,949.49 |
| 12 | 300128.SZ | 51,213.73 |
| 13 | 300324.SZ | 49,544.01 |
| 14 | 301387.SZ | 49,002.97 |
| 15 | 300490.SZ | 47,352.06 |
| 16 | 300457.SZ | 42,546.34 |
| 17 | 300763.SZ | 30,839.56 |
| 18 | 300459.SZ | 30,001.43 |
| 19 | 300182.SZ | 27,105.71 |
| 20 | 300938.SZ | 26,245.02 |

### Bottom 20 symbols by P&L contribution

| Rank | Symbol | P&L |
|---:|---|---:|
| 1 | 301096.SZ | -47,311.75 |
| 2 | 301048.SZ | -35,449.98 |
| 3 | 300479.SZ | -32,129.23 |
| 4 | 300945.SZ | -29,089.93 |
| 5 | 300987.SZ | -26,436.42 |
| 6 | 300632.SZ | -22,387.05 |
| 7 | 300551.SZ | -20,808.33 |
| 8 | 300371.SZ | -19,043.21 |
| 9 | 300770.SZ | -18,902.10 |
| 10 | 300758.SZ | -18,374.43 |
| 11 | 300404.SZ | -18,096.08 |
| 12 | 300494.SZ | -17,353.03 |
| 13 | 300285.SZ | -16,906.19 |
| 14 | 300971.SZ | -16,710.58 |
| 15 | 301217.SZ | -16,295.18 |
| 16 | 300788.SZ | -15,600.38 |
| 17 | 300947.SZ | -15,538.22 |
| 18 | 300327.SZ | -15,059.22 |
| 19 | 301182.SZ | -14,077.13 |
| 20 | 300346.SZ | -14,064.20 |

- TOP20_PNL_CONCENTRATION: `82.7207%` of all positive symbol P&L

P&L contribution includes realized sell-leg P&L and marked unrealized P&L for
ending positions. It is an attribution diagnostic, not a PIT performance claim.

## Research decision

- FULL_SURVIVOR_RESULT: **MIXED**

The classification combines signal breadth, exposure, concentration, both yearly
results, drawdown and execution correctness. It never changes strategy parameters.
