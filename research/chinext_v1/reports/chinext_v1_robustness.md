# ChinNext V1 robustness validation

> **EXPLORATORY / CURRENT-SURVIVOR / NON-PIT / SURVIVORSHIP-BIASED**
>
> This report post-processes the frozen full-survivor execution and NAV ledgers.
> It regenerates no signal, changes no fill, selects no parameter and extends no date.

## Frozen scope

- DATE_RANGE: `2024-01-02 .. 2025-12-31`
- BASELINE_STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- BASELINE_EXECUTION_LEDGER_SHA256: `f3a83a9e974776f34477c952b1bf4c26f22a5ef00879adfc77cd6188f9eec9d5`
- BASELINE_NAV_SHA256: `82c71b6824bf4058181c88dbaa626f989e2651912aab3777d4d5ffdce096e8ea`
- COMPLETED_ROUND_TRIPS: `111`

## Cost sensitivity — fixed fills

| Scenario | Total return | Annualized | Max drawdown | Extra cost |
|---|---:|---:|---:|---:|
| 10bps_per_side | 105.2422% | 43.6891% | -26.2272% | 0.00 |
| 20bps_per_side | 101.5950% | 42.3961% | -27.0999% | 36,472.28 |
| 30bps_per_side | 97.9478% | 41.0915% | -27.9763% | 72,944.56 |
| 50bps_per_side | 90.6533% | 38.4459% | -29.7402% | 145,889.11 |
| 10bps_per_side_plus_5bps_sell_stamp | 104.3545% | 43.3754% | -26.4589% | 8,876.67 |

The baseline already deducts 10bps on every filled side. Higher-cost paths subtract
only incremental cost from the same fixed executions and never regenerate signals,
orders or quantities. Local research contracts explicitly specify 5bps sell-side
stamp duty, shown as a separate scenario; it is not retroactively inserted into the
frozen baseline. Slippage remains unresolved as a ChinNext-specific realized model.

## Round-trip concentration

| Cut | Share of all positive round-trip P&L | Portfolio return excluding best trades |
|---|---:|---:|
| Top 1 | 13.2763% | 83.5856% |
| Top 5 | 40.9643% | 38.4203% |
| Top 10 | 62.3049% | 3.6092% |
| Top 20 | 84.2544% | -32.1953% |
| Top 50 | 100.0000% | — |

- MEAN_ROUND_TRIP_RETURN: `7.7312%`
- MEDIAN_ROUND_TRIP_RETURN: `-1.0750%`

Exclusion returns subtract selected completed-cycle P&L from final portfolio P&L;
all other realized P&L and the ten ending positions remain unchanged.

## Winner distribution

| Round-trip return bucket | Count | P&L contribution |
|---|---:|---:|
| > +50% | 8 | 853,365.84 |
| +20% ~ +50% | 10 | 457,415.57 |
| +10% ~ +20% | 9 | 200,178.64 |
| 0 ~ +10% | 22 | 120,261.47 |
| -10% ~ 0 | 46 | -341,217.39 |
| -20% ~ -10% | 15 | -299,388.83 |
| < -20% | 1 | -51,462.69 |

## Benchmark comparison

| Benchmark | Total return | Annualized | Max drawdown | Volatility | Sharpe rf=0 |
|---|---:|---:|---:|---:|---:|
| 399102.SZ 创业板综 | 55.5918% | 24.9645% | -25.9260% | 33.9235% | 0.8254 |
| 399006.SZ 创业板指 | 72.5920% | 31.6709% | -29.1369% | 34.3017% | 0.9706 |

- STRATEGY_EXCESS_TOTAL_VS_399102: `49.6504%`
- STRATEGY_EXCESS_ANNUALIZED_VS_399102: `18.7246%`
- STRATEGY_EXCESS_TOTAL_VS_399006: `32.6503%`
- STRATEGY_EXCESS_ANNUALIZED_VS_399006: `12.0182%`

`399102.SZ` is the exact frozen QMT series. `399006.SZ` is exact `sz399006 / 创业板指`
from registered frozen QD-003 and is used only as an ex-post comparator, never as a
strategy input or fallback.

## Exposure-aware diagnostic

- RETURN_WHILE_INVESTED: `114.4221%`
- RETURN_WHILE_FLAT: `-4.2812%`
- AVERAGE_INVESTED_RATIO: `40.3915%`
- 399102_RETURN_DURING_STRATEGY_FLAT_DAYS: `-10.6384%`
- 399102_RETURN_DURING_STRATEGY_INVESTED_DAYS: `74.1147%`
- INVESTED_DAYS / FLAT_DAYS: `256 / 228`

The diagnostic classifies each close-to-close return by end-of-day holdings. An
open exit can therefore contribute to a day that finishes flat; this is intentional
and stated rather than silently reassigning return.

## Year split

| Year | Cost scenario | Strategy return | Max drawdown | 399102 return | Excess | 399006 return | Excess |
|---|---|---:|---:|---:|---:|---:|---:|
| 2024 | 10bps_per_side | 49.0494% | -23.5423% | 10.8229% | 38.2265% | 15.3926% | 33.6568% |
| 2024 | 20bps_per_side | 48.0522% | -23.8948% | 10.8229% | 37.2293% | 15.3926% | 32.6596% |
| 2024 | 30bps_per_side | 47.0549% | -24.2487% | 10.8229% | 36.2320% | 15.3926% | 31.6623% |
| 2024 | 50bps_per_side | 45.0604% | -24.9611% | 10.8229% | 34.2375% | 15.3926% | 29.6678% |
| 2024 | 10bps_per_side_plus_5bps_sell_stamp | 48.7877% | -23.6450% | 10.8229% | 37.9648% | 15.3926% | 33.3952% |
| 2025 | 10bps_per_side | 37.7008% | -10.1769% | 40.3968% | -2.6960% | 49.5694% | -11.8686% |
| 2025 | 20bps_per_side | 36.1648% | -10.6897% | 40.3968% | -4.2319% | 49.5694% | -13.4045% |
| 2025 | 30bps_per_side | 34.6081% | -11.2112% | 40.3968% | -5.7887% | 49.5694% | -14.9613% |
| 2025 | 50bps_per_side | 31.4303% | -12.2807% | 40.3968% | -8.9665% | 49.5694% | -18.1391% |
| 2025 | 10bps_per_side_plus_5bps_sell_stamp | 37.3464% | -10.3253% | 40.3968% | -3.0504% | 49.5694% | -12.2230% |

## Interpretation

- ROBUSTNESS_RESULT: **FRAGILE**

Cost sensitivity is mild relative to the headline return, but concentration and
benchmark/exposure diagnostics determine whether that headline is genuinely broad.
No result here is a formal PIT performance claim.
