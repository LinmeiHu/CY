# ASHARE-MORNING-DEMAND-OVERNIGHT-SUPPLY-ACCEPTANCE-V6

## Signal captured

An industry-demand event that survives the overnight release of inventory and
remains accepted through the first 30 completed minutes of D1.  Entry is the
actual 10:01 open, strictly after the 10:00 decision bar.

## Frozen V6 results

|Entry year|Signals|Trades|Mean net|Median net|Win|Target 8|Severe10|
|---:|---:|---:|---:|---:|---:|---:|---:|
|2014|43|43|0.88%|0.05%|51.16%|23.26%|0.00%|
|2015|78|77|1.39%|0.95%|53.25%|35.06%|2.60%|
|2016|57|57|-0.51%|-1.39%|33.33%|12.28%|0.00%|
|2017|30|30|-0.70%|-1.17%|26.67%|6.67%|0.00%|
|2018|61|60|-0.11%|-1.27%|38.33%|10.00%|0.00%|
|2019|105|105|0.12%|-1.08%|43.81%|8.57%|0.00%|
|2020|167|165|-0.34%|-0.72%|41.21%|15.15%|2.42%|
|2021|158|157|-0.17%|-1.44%|40.13%|19.75%|0.64%|
|2022|148|145|-0.49%|-1.34%|37.93%|11.03%|0.00%|
|2023|147|146|-0.98%|-1.34%|30.82%|4.79%|0.68%|
|2024|149|147|0.68%|-1.23%|41.50%|19.73%|0.00%|
|2025|147|147|0.39%|-0.47%|47.62%|18.37%|1.36%|
|2026|127|124|0.01%|-1.22%|37.90%|15.32%|0.00%|

2014--2025 full years: 1279 completed trades,
-0.03% mean,
-1.13% median, and
0.78% severe-loss10.

2024--2026 YTD post-observation diagnostic:
418 completed trades,
0.38% mean and
-1.05% median.

## Goal gate

`{"all_required_pass": false, "average_completed_signals_per_full_year": 106.58333333333333, "average_completed_signals_per_full_year_gt50": true, "date_equal_mean_net_gt0": false, "every_full_year_mean_positive": false, "pooled_mean_net_gt2": false, "pooled_median_net_gt0": false, "recent_block_mean_positive": true, "severe10_lt10": true}`

No model was fit and no V6 rule was changed after its outcomes were attached.
The 2024--2026 rows are not pristine OOS because their parent calendar outcomes
had already been observed elsewhere in the research program.
