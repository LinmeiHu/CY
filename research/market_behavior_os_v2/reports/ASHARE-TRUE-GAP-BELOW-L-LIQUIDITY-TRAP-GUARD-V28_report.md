# ASHARE-TRUE-GAP-BELOW-L-LIQUIDITY-TRAP-GUARD-V28

## Fixed rule

Keep V27 M20/F14/R5 and its exact A67/H20/no-stop/K80 execution. At the completed signal close, require registered CY033 hard-valid non-ST state and no more than one one-price limit-down in the preceding 20 completed sessions.

Economic meaning: one isolated limit-down may be capitulation; repeated one-price limit-downs are rationed selling, so low printed volume is not evidence that supply is exhausted.

## Development: 2018-2021

Accepted 278 (69.50/year), mean 6.02%, median 6.81%, win 88.85%, severe loss <=-10% 4.32%, average holding 9.40 sessions.

|Signal year|Trades|Mean net|Median net|Win|<=-10%|Avg hold|
|---:|---:|---:|---:|---:|---:|---:|
|2018|213|6.59%|7.46%|92.02%|3.76%|9.03|
|2019|27|5.24%|4.37%|85.19%|0.00%|10.37|
|2020|13|2.28%|5.34%|69.23%|15.38%|14.85|
|2021|25|3.94%|4.75%|76.00%|8.00%|8.68|

Selector passed: **True**. Checks: `{"accepted_trades_per_year_gt_50": true, "average_holding_sessions_lt_15": true, "each_signal_year_has_trades": true, "each_signal_year_mean_positive": true, "mean_net_ge_4pct": true}`.

## Locked diagnostic: 2022-2024

Accepted 114 (38.00/year), mean 7.05%, median 6.57%, win 85.09%, severe loss <=-10% 7.02%, average holding 9.36 sessions.

|Signal year|Trades|Mean net|Median net|Win|<=-10%|Avg hold|
|---:|---:|---:|---:|---:|---:|---:|
|2022|38|6.20%|6.33%|84.21%|5.26%|11.63|
|2023|12|4.12%|2.01%|66.67%|8.33%|14.17|
|2024|64|8.10%|7.90%|89.06%|7.81%|7.11|

This later period is a locked diagnostic for the new guard, not pristine external validation, because parent V27 itself was selected after observing 2017-2023.
