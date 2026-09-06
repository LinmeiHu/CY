# A-share canonical small-cap premium V1

## Boundary

This is consumed 2018--2023 development research, not OOS confirmation. Post-2023 outcomes and CY-011 were not read.

## Sequential decision

- Generation: `False`
- Fixed validation opened: `False`
- Fixed validation passed: `None`
- Executable replay run: `False`

## Bucket anatomy

| Period | Q | N | Mean net | Median net | Win rate | Severe loss |
|---|---:|---:|---:|---:|---:|---:|
| generation_2018_2020 | 1 | 11,324 | -0.152% | -1.976% | 43.25% | 21.98% |
| generation_2018_2020 | 2 | 11,324 | 0.015% | -1.845% | 43.37% | 20.61% |
| generation_2018_2020 | 3 | 11,330 | 0.091% | -1.542% | 44.50% | 18.84% |
| generation_2018_2020 | 4 | 11,352 | 0.622% | -0.995% | 45.93% | 16.02% |
| generation_2018_2020 | 5 | 11,339 | 0.925% | -0.273% | 48.50% | 12.19% |
| generation_2018_2019 | 1 | 5,776 | -0.301% | -1.618% | 43.35% | 18.84% |
| generation_2018_2019 | 2 | 5,783 | 0.055% | -1.599% | 43.87% | 18.43% |
| generation_2018_2019 | 3 | 5,786 | 0.054% | -1.313% | 45.28% | 16.68% |
| generation_2018_2019 | 4 | 5,798 | 0.291% | -0.773% | 46.62% | 14.59% |
| generation_2018_2019 | 5 | 5,794 | 0.405% | -0.399% | 47.69% | 10.32% |
| generation_2020 | 1 | 5,548 | 0.003% | -2.390% | 43.15% | 25.25% |
| generation_2020 | 2 | 5,541 | -0.026% | -2.204% | 42.84% | 22.88% |
| generation_2020 | 3 | 5,544 | 0.129% | -1.830% | 43.69% | 21.10% |
| generation_2020 | 4 | 5,554 | 0.967% | -1.386% | 45.21% | 17.52% |
| generation_2020 | 5 | 5,545 | 1.469% | -0.176% | 49.34% | 14.14% |

## Executable translation

The frozen sequential gate failed, so no portfolio outcome was opened.

## Interpretation

The canonical small-cap premium failed its frozen generation gate. Validation and replay remained unread.

## Reproducibility

- Spec SHA-256: `2587418845f3c80baead66e86133d7978b34e0864fa28b6e91add54096b10c1c`
- Bucket table SHA-256: `369256e55fbcc21aadf56496d492176de3f492cd4626178496a209505ae31286`
