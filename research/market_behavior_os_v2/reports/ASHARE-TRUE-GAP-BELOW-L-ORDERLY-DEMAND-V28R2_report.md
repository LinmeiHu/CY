# ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2

Frozen addition to V28R1: signal-day raw amount must be no more than 2.0 times the median raw amount of the 20 completed trading sessions strictly before the signal. The signal session is excluded from its own baseline.

Economic meaning: a regained cost zone should show orderly, two-sided demand. An extreme value burst can be a crowded terminal scramble, leaving the next legal entry to pay for demand already spent.

Every signal and history row comes from registered CY033, must be hard-valid, hash-bound, and available by the signal decision. Missing history, nonpositive amount, unknown trading state, or missing lineage rejects the signal.

## Development 2018-2021

Stage A retained 370 of 397 V28R1 signals before outcomes were opened.

Exact K80 accepted 255 (63.75/year), mean 6.68%, median 6.85%, win 90.98%, severe10 2.35%, average hold 9.01 sessions.

|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|
|---:|---:|---:|---:|---:|---:|---:|
|2018|198|7.14%|7.49%|93.43%|2.02%|8.71|
|2019|23|5.27%|5.61%|86.96%|0.00%|10.70|
|2020|10|6.02%|6.31%|80.00%|0.00%|13.00|
|2021|24|4.44%|5.10%|79.17%|8.33%|8.17|

Development passed: **True**.

No post-2021 entries or outcomes were read, no later identity was built, and no diagnostic authorization was created.
