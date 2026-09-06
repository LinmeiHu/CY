# ASHARE-EXACT-V10-V17-ROLLFORWARD-2021-2026YTD-V1

Mechanical exact-rule roll-forward only. No parameter, market-state, target, horizon, cost, or capacity change was made.

Data end: `2026-09-04`. V10 mature-2026 signal cutoff: `2026-06-05`; V17 bull mother cutoff: `2026-06-02`.

## V10 exact BEAR engine

|Signal year|Frozen|Completed|Mean net|Median net|Win|Severe <=-10%|Target hit|Gate|
|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
|2024|237|237|11.77%|19.60%|79.32%|14.77%|73.00%|PASS|
|2025|44|44|15.00%|19.60%|88.64%|6.82%|84.09%|FAIL|
|2026|10|10|3.35%|19.60%|60.00%|30.00%|60.00%|FAIL|

2024 is the unchanged, already-consumed frozen V17 BEAR output; it was not rebuilt or optimized.

## V17 exact dual engine

|Signal year|Frozen|Completed|Mean net|Median net|Win|Severe <=-10%|Target hit|Gate|
|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
|2021|92|92|2.87%|2.31%|55.43%|23.91%|42.39%|FAIL|
|2025|119|119|9.63%|19.60%|72.27%|10.08%|60.50%|PASS|
|2026|66|66|-6.17%|-13.15%|31.82%|56.06%|28.79%|FAIL|

## Governance

The 2023/2024 overlap canary had to reproduce identity, execution returns, and capacity before any requested new-period outcome path was attached. 2026 is mature YTD only, not a full-year claim. CY033 is PIT-B, so this is not relabeled strict PIT-A confirmation.

The legacy V17 development contract said each year >50, while its old runner implemented pooled trades divided by seven >50. This report applies the user's explicit per-year gate without rewriting the historical verdict.
