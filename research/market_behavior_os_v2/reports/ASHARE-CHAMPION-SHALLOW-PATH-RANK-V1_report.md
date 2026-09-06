# Champion shallow price-volume-path rank V1

Status: `GENERATION_FAILED`.

## Generated transparent rule

- `gap_return <= -0.0030145275` at node 0
- `activity_ratio <= 1.5774268` at node 1
- `diffusion_score <= 0.87228259` at node 4

Used split features: activity_ratio, diffusion_score, gap_return. The tree has depth at most two and no validation outcome was read.

## Generation screen

Top-3 mean 2.767% versus all-ten 2.108%; improvement 0.659%; selected median 1.710%; severe-loss improvement 3.017%.

All generation gates pass: `False`.

This is in-sample rule generation on consumed 2018-2020 history. A separate hash-bound experiment is required before 2021-2023 validation or executable replay. Post-2023 outcomes and CY-011 were not read.
