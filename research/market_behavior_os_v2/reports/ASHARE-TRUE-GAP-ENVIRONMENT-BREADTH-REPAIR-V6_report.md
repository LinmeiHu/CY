# ASHARE-TRUE-GAP-ENVIRONMENT-BREADTH-REPAIR-V6

## Result

`ENVIRONMENT_BREADTH_REPAIR_POST_OBSERVATION_FAILED`

Selected rule: `BOARD_MA5_BREADTH_RISING_AND_INDUSTRY_RET5_POS`.

|Period|Signals|Signals/year|Trades|Event mean|Portfolio mean|Median|Severe10|Total return|MaxDD|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|Development 2017–2021|303|60.6|228|3.34%|3.14%|4.88%|10.09%|18.98%|-4.61%|
|Post-observation 2022–2023|40|20.0|37|4.32%|4.32%|4.27%|5.41%|4.10%|-1.16%|

## Development rule trace

|Rule|Signals/year|Portfolio mean|Median|Severe10|Positive years|
|---|---:|---:|---:|---:|---:|
|BOARD_RET5_POS_AND_INDUSTRY_RET5_POS|83.2|3.78%|5.25%|8.30%|5/5|
|BOARD_MA5_MAJORITY_AND_INDUSTRY_RET5_POS|72.6|3.56%|5.13%|9.35%|5/5|
|BOARD_MA5_BREADTH_RISING_AND_INDUSTRY_RET5_POS|60.6|3.14%|4.88%|10.09%|5/5|

## Governance

- Every environment feature ends at the signal close and uses continuous, valid QD-010 coordinates.
- Missing industry or breadth inputs fail closed.
- 2022–2023 is post-observation diagnostic evidence, not pristine validation.
- No post-2023 signal or feature row was opened.
