# ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2-VALIDATION-2022-2024

This is the one-way temporal diagnostic of the rule frozen on 2018-2021. The 2022-2024 result is descriptive and did not change the rule.

Rule: retain every V28R1 condition and require signal-day CY033 raw amount to be no more than 2.0 times the median amount of the 20 completed trading sessions strictly before the signal. Every feature row remains hard-valid and available by decision time.

## Frozen identity

Before outcomes were opened, Stage A retained 120 of 125 V28R1 signals; 108 had frozen executable entries.

## 2022-2024 exact K80 diagnostic

Accepted 106 (35.33/year), mean 7.24%, median 6.72%, win 86.79%, target hit 71.70%, severe10 5.66%, CVaR5 -15.13%, worst -19.40%, average/median hold 9.10/5.50 sessions.

|Signal year|Trades|Mean|Median|Win|Target hit|Severe10|CVaR5|Worst|Avg hold|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|2022|35|6.88%|6.40%|85.71%|62.86%|2.86%|-11.03%|-15.71%|11.66|
|2023|9|1.73%|2.13%|77.78%|33.33%|0.00%|-4.48%|-4.48%|11.89|
|2024|62|8.24%|8.17%|88.71%|82.26%|8.06%|-15.95%|-19.40%|7.26|

Descriptive goals: frequency >50/year **False**; mean ≥4% **True**; average hold <15 **True**.

Exit reasons: {"CORPORATE_ACTION_RISK": 5, "H20_TIME_STOP": 25, "PRE_L_TARGET": 76}.

Execution is unchanged: entry strictly after the completed signal, A67 target below L, H20 time stop, no failure stop, 20bp cost per side, and Main/ChiNext K80 per sleeve.

Maximum data date used was 2024-08-30. No 2025-or-later data were opened.

This is a frozen-rule temporal diagnostic, not a pristine external validation of the retrospective V27/V28/V28R1 ancestry, and it must not be used to revise V28R2.
