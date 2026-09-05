# ASHARE-BULL-CHINEXT-BREADTH70-INDUSTRY-IGNITION-V63

`BULL_CHINEXT_BREADTH70_INDUSTRY_IGNITION_TARGET_MET`

Evidence label: `ITERATIVE_2014_2023_RESEARCH_NOT_PRISTINE_VALIDATION`.

|Year|Trades|Mean net|Median net|Win|Severe10|Mean hold|
|---:|---:|---:|---:|---:|---:|---:|
|2014|82|3.24%|4.36%|62.20%|4.88%|14.682926829268293|
|2015|39|10.64%|14.60%|84.62%|0.00%|12.743589743589743|
|2016|40|4.52%|3.82%|67.50%|2.50%|14.05|
|2017|49|3.42%|2.32%|65.31%|4.08%|14.26530612244898|
|2018|56|0.08%|-1.23%|37.50%|14.29%|14.357142857142858|
|2019|108|6.04%|10.73%|72.22%|6.48%|11.842592592592593|
|2020|91|4.15%|8.61%|61.54%|12.09%|12.098901098901099|
|2021|41|3.53%|0.76%|51.22%|2.44%|12.341463414634147|
|2022|48|1.19%|0.77%|56.25%|16.67%|14.5|
|2023|68|0.18%|-1.42%|44.12%|8.82%|14.323529411764707|

Gate: `{"2021_2023_each_positive": true, "capacity_accepted_completed_gt_500": true, "mean_excluding_best5_dates_positive": true, "mean_holding_lt_15": true, "mean_net_gt_3pct": true, "top5_date_positive_pnl_share_le_25pct": true}`.

The rule is independent of collapse-gap repair. It uses a breadth-70 market risk-appetite state, a PIT industry breadth ignition, and a controlled first 20-session pressure break in ChiNext.

## Subsequent concentration diagnosis

The encoded pooled gate passes, but V63 is not retained as the final strategy. In 2023 it has only 12 signal dates; signal-date-equal mean is -0.740%, and mean after excluding the five best 2023 signal dates is -2.934%. This exposed the economic weakness of treating high 20-session breadth alone as a complete bull-state definition. V64 therefore requires medium-term 60-session participation and is a separately frozen iterative Development rule rather than a post-hoc alteration of V63.
