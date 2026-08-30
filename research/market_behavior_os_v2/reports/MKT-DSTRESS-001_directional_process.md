# MKT-DSTRESS-001 directional synchronization/stress process

## Boundary

- Status: `COMPLETE_DOWNSIDE_CONTINUOUS_FAIL_UPSIDE_CONTINUOUS_FAIL`
- Common panel: 10,696 rows, 2018-07-03..2023-12-29.
- Failed MKT-SHOCK episode fields, future returns, strategy outcomes, and CY-011 read: **none**.
- `ELEVATED` is a process label, not panic, speculation, recovery, or usefulness.

## Side-specific gates

| Side | Observations/group | Worst score-neighbor rho | ST rho | Max single-input/vol rho | Continuous | Recurring process | Activity modifier |
|---|---:|---:|---:|---:|---|---|---|
| downside | 814 | 0.691 | 0.959 | 0.742 | FAIL | FAIL | FAIL |
| upside | 814 | 0.646 | 0.981 | 0.639 | FAIL | FAIL | FAIL |

## Process interpretation

- downside: primary onsets/group 1..4, years/group 1..1; gate components `{'coverage': True, 'neighbors': False, 'denominator': True, 'year_nondegenerate': True, 'single_input_and_volatility_nonredundancy': True, 'onset_sample': False, 'onset_neighbor': False, 'state': False, 'dwell_and_relief': False, 'high_activity_sample': False, 'high_activity_neighbor': False}`.
- upside: primary onsets/group 0..8, years/group 0..2; gate components `{'coverage': True, 'neighbors': False, 'denominator': True, 'year_nondegenerate': True, 'single_input_and_volatility_nonredundancy': True, 'onset_sample': False, 'onset_neighbor': False, 'state': False, 'dwell_and_relief': False, 'high_activity_sample': False, 'high_activity_neighbor': False}`.
- Directional balance is retained only as the exact difference of the two side scores; it is not a third mechanism.

## Reproducibility

- Spec SHA-256: `63093a0abdd8a44374b9b0c1a066130774131df7c17e7b85cb55cb697ca305d2`
- Shock panel SHA-256: `bba55a5ab23a252b73d7b85edb39d53404284d1c3c1ca4388b0dd4cd1b1889eb`
- Risk panel SHA-256: `fe7436e26d616455c7ce897eb70d53749e9185285082453549d338afe53009b1`
- Output panel SHA-256: `c3fe91ec332e560b972ee263c1c6076b771a083f84c325664970b48ecfbfc02a`
