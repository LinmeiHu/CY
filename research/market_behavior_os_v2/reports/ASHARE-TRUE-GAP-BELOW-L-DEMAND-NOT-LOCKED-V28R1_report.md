# ASHARE-TRUE-GAP-BELOW-L-DEMAND-NOT-LOCKED-V28R1

Fixed addition to V28: reject a signal whose registered raw close is still at the signal-day up-limit price. The 0.006 CNY equality tolerance is inherited from the existing execution comparisons; no price threshold was searched.

Economic meaning: demand recapture must end with two-sided price discovery. A locked close reveals rationed buying and makes the next legal session an imbalance chase.

## Development 2018-2021

Accepted 267 (66.75/year), mean 6.49%, median 6.82%, win 90.26%, severe10 2.62%, average hold 9.23 sessions.

|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|
|---:|---:|---:|---:|---:|---:|---:|
|2018|204|7.17%|7.53%|93.63%|1.96%|8.80|
|2019|26|4.84%|4.36%|84.62%|0.00%|10.73|
|2020|12|3.70%|5.68%|75.00%|8.33%|14.33|
|2021|25|3.94%|4.75%|76.00%|8.00%|8.68|

Development passed: **True**.

## Locked diagnostic 2022-2024

Accepted 111 (37.00/year), mean 7.35%, median 6.72%, win 85.59%, severe10 6.31%, average hold 9.38 sessions.

|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|
|---:|---:|---:|---:|---:|---:|---:|
|2022|37|6.90%|6.40%|86.49%|2.70%|11.38|
|2023|12|4.12%|2.01%|66.67%|8.33%|14.17|
|2024|62|8.24%|8.17%|88.71%|8.06%|7.26|

This is not pristine external validation because V27/V28 are retrospective parents.
