# A-share post-hoc large-cap dominance V1

## Boundary

The direction was generated after the 2018--2020 canonical small-cap test failed. The frozen 2021--2023 check is sequential development validation, not OOS confirmation. Post-2023 outcomes and CY-011 were not read.

## Fixed validation

- Q5 mean net h20: -1.055%
- Q5 minus Q1: -1.216%
- Monotonic large-cap steps: 0/4
- Every frozen requirement passed: `False`

| Period | Q | N | Mean net | Median net | Win rate | Severe loss |
|---|---:|---:|---:|---:|---:|---:|
| validation_2021_2023 | 1 | 18,813 | 0.161% | -1.684% | 43.67% | 18.88% |
| validation_2021_2023 | 2 | 18,758 | 0.042% | -1.783% | 43.27% | 18.62% |
| validation_2021_2023 | 3 | 18,782 | -0.183% | -1.786% | 42.55% | 18.53% |
| validation_2021_2023 | 4 | 18,778 | -0.482% | -1.886% | 41.70% | 17.83% |
| validation_2021_2023 | 5 | 18,786 | -1.055% | -1.958% | 40.72% | 17.37% |
| year_2021 | 1 | 5,785 | 1.610% | -0.828% | 46.71% | 16.23% |
| year_2021 | 2 | 5,760 | 1.820% | -0.675% | 47.76% | 15.99% |
| year_2021 | 3 | 5,765 | 1.856% | -0.246% | 48.79% | 16.88% |
| year_2021 | 4 | 5,758 | 1.501% | -0.384% | 48.52% | 16.29% |
| year_2021 | 5 | 5,755 | -0.158% | -1.572% | 43.27% | 18.77% |
| year_2022 | 1 | 6,780 | -1.259% | -2.980% | 39.65% | 25.29% |
| year_2022 | 2 | 6,752 | -1.142% | -2.656% | 40.60% | 24.32% |
| year_2022 | 3 | 6,761 | -1.454% | -2.813% | 39.82% | 24.38% |
| year_2022 | 4 | 6,768 | -1.739% | -2.917% | 38.73% | 23.02% |
| year_2022 | 5 | 6,772 | -1.521% | -2.319% | 40.08% | 19.62% |
| year_2023 | 1 | 6,248 | 0.361% | -1.129% | 45.21% | 14.36% |
| year_2023 | 2 | 6,246 | -0.319% | -1.812% | 42.01% | 14.89% |
| year_2023 | 3 | 6,256 | -0.687% | -2.000% | 39.75% | 13.73% |
| year_2023 | 4 | 6,252 | -0.949% | -2.177% | 38.63% | 13.64% |
| year_2023 | 5 | 6,259 | -1.374% | -1.976% | 39.06% | 13.66% |

## Frozen executable translation

Validation failed; no portfolio replay was run and the local family is closed.

## Decision

The post-hoc large-cap direction failed at least one frozen validation requirement. No portfolio or neighboring cutoff was tested.

## Reproducibility

- Spec SHA-256: `d47a36a377aae6f516ad488c44632b5d509c067080f110b14ec8b2f1cc1c99c5`
- Bucket table SHA-256: `5faeab850f83586e62d861126db70a4212177900e191820d362870ef27c3cc5b`
