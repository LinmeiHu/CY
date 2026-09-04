# ASHARE-TRUE-GAP-BELOW-L-FAILURE-EXIT-V8

## Development

`FAILURE_EXIT_DEVELOPMENT_FAILED`

|Lane|Executable/year|Accepted trades|Mean|Median|Severe10|Failure exits|Positive years|
|---|---:|---:|---:|---:|---:|---:|---:|
|X0_H20_BASELINE|158.2|509|2.25%|4.14%|11.98%|0|5/5|
|X1_SWING_LOW_BREAK|158.2|535|1.44%|2.79%|8.97%|209|4/5|
|X2_NO_PROGRESS_D3|158.2|551|1.63%|-0.07%|6.17%|225|5/5|
|X3_NO_PROGRESS_D5|158.2|544|1.78%|1.56%|8.46%|192|5/5|
|X4_SWING_LOW_OR_D3|158.2|554|1.36%|-0.77%|4.51%|297|5/5|

The 2022-2023 rule-specific failure-exit returns were not opened.

## Governance

- Stage A constructed completed-daily-bar trigger clocks only.
- Every replacement fill is the next authoritative legal sell open and obeys T+1.
- Signal admission, entry, target, costs, K20 sleeves, and H20 terminal exit are unchanged.
- Later data are used only to manage and complete trades formed by the frozen cutoff.
- No post-2023 signal, feature, threshold, or selection is permitted.
