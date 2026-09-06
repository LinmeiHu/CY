# ASHARE-BULL-QUIET-INVENTORY-INDUSTRY-ACCEPTANCE-V1

`BULL_QUIET_INVENTORY_MECHANISM_FAILS_TARGET`

## Frozen mechanism

Trade the frozen quiet-inventory executable information breakout only when the completed-close broad market state is BULL. The bounded selector may add only the frozen PIT industry conditions. BEAR and TRANSITION hold cash. This is not downward-gap repair.

Selected rule: `BULL_INDUSTRY_MAJORITY`. Selected translation: `T10_H20_NO_STOP`.

## Full capacity-constrained result

|Trades|Per year|Mean net|Median net|Win|Severe10|Mean hold|Total return|MaxDD|Sharpe|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|672|67.20|2.42%|9.60%|62.95%|11.01%|13.85|31.76%|-4.82%|0.843|

## Annual trade evidence

|Year|Trades|Mean|Median|Win|Severe10|Mean hold|
|---:|---:|---:|---:|---:|---:|---:|
|2014|68|1.12%|4.28%|55.88%|17.65%|16.82|
|2015|82|7.01%|9.60%|92.68%|6.10%|9.80|
|2016|35|-0.96%|-2.26%|40.00%|11.43%|17.91|
|2017|27|1.04%|-0.35%|48.15%|3.70%|17.59|
|2018|2|-15.86%|-15.86%|0.00%|50.00%|21.00|
|2019|71|2.77%|9.60%|66.20%|15.49%|13.42|
|2020|145|3.74%|9.60%|67.59%|8.28%|12.14|
|2021|65|-0.00%|0.67%|50.77%|16.92%|15.29|
|2022|54|1.42%|9.60%|59.26%|14.81%|13.52|
|2023|123|1.60%|3.78%|58.54%|7.32%|14.48|

## Causality and concentration

Gate: `{"2022_positive": true, "2023_positive": true, "accepted_trades_per_year_gt_50": true, "confirmation_each_year_positive": false, "mean_ex_best5_positive": true, "mean_holding_le_15": true, "mean_net_ge_3pct": false, "top5_positive_pnl_share_le_25pct": true}`.

Concentration: `{"mean_excluding_best_five_signal_dates": 0.01849445419518232, "signal_date_count": 299, "top_five_signal_date_positive_pnl_share": 0.17929392755850856, "top_signal_date_trade_share": 0.02976190476190476}`.

All market and industry state is known by the completed signal close; entry is later. 2014-2021 outcomes reproduce the authoritative source before the same engine is extended to 2022-2023. Post-2023 rows are used only to close pre-2024 trades.
