# ASHARE-TRUE-GAP-BELOW-L-EARLY-REPAIR-V4R1-CAUSAL-REPLAY

## Conclusion

`V4R1_CORRECTION_INVALIDATES_V4_CANDIDATE`

This is an implementation-correction replay of the unchanged V4 economic rule. The old V4 final-challenge proposal is withdrawn. Post-cutoff data were used only to resolve positions formed from pre-cutoff signals.

## Corrected evidence

|Period|Selected|Eligible entries|Complete outcomes|Annual entries|Mean net|Median net|Severe10|Total return|MaxDD|Sharpe|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|DEVELOPMENT|820|791|791|158.2|2.25%|4.14%|11.98%|31.73%|-8.65%|0.867|
|POST_OBSERVATION_DIAGNOSTIC|136|129|129|64.5|1.85%|3.52%|14.73%|5.73%|-5.37%|0.733|

## Repair audit

- Both periods use the same direct first-MA5 constructor.
- Every selected symbol is registered in period-local execution assets.
- Every evaluation-eligible executable entry conserves into exactly one outcome.
- No fixed-end completeness filter is applied; every executable entry must conserve into one outcome.
- Target realization is disabled after a coordinate-lineage break; raw-share H20/risk exit remains mandatory.
- 2022-2023 is a post-observation diagnostic, not external validation.

## Goal checks

- development_frequency_40_to_80: `False`
- development_mean_net_ge_3pct: `False`
- development_median_positive: `True`
- development_severe10_le_15pct: `True`
- diagnostic_frequency_40_to_80: `True`
- diagnostic_mean_net_ge_3pct: `False`
- diagnostic_median_positive: `True`
- diagnostic_severe10_le_15pct: `True`

## Governance

Post-cutoff signal/feature/selection data opened: **NO**.

Repository 2024+ data opened: **YES — authorized trade-resolution tail only**.
