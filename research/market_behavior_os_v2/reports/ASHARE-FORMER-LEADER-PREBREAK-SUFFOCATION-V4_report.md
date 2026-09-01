# ASHARE-FORMER-LEADER-PREBREAK-SUFFOCATION-V4

**Verdict: `PREBREAK_SUFFOCATION_DESCRIPTIVE_ONLY`**

V4 is an internal chronological pseudo-OOS mechanism experiment designed after earlier 2014--2021 research. Validation 2022--2023 and Final OOS 2024+ remain sealed and unread.

## Population and corrected feature

V3 source gap events: 3,746; outcome-blind collapsed executable entries: 3,734; valid PreBreakDryup: 3,734; valid compression: 3,734.

PreBreakDryup distribution: `{'observations': 3734, 'mean': 1.168163093391371, 'std': 2.5682617985442375, 'min': 0.005403302579913886, 'p01': 0.036281861448609155, 'p10': 0.4403106681657495, 'p25': 0.6660631147494089, 'median': 0.9036460206678332, 'p75': 1.2768421884187993, 'p90': 1.8041882069417576, 'p99': 5.025994703944616, 'max': 118.3737471867967}`

## Fixed dry-up bins

| Bin | N | Event T1-open | Date-equal T1-open | Median | Positive | T1-close | T2-close | T3-close | MFE1 | MAE1 | MFE3 | MAE3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| <=0.30 | 288 | 3.178% | -2.184% | 3.123% | 60.211% | 6.789% | 9.954% | 10.047% | 10.045% | 0.649% | 18.514% | -1.986% |
| (0.30,0.50] | 166 | 0.784% | -0.020% | 0.631% | 53.939% | 0.883% | 2.229% | 2.991% | 6.458% | -3.044% | 11.594% | -7.225% |
| (0.50,0.70] | 614 | 1.260% | -0.215% | 0.575% | 53.105% | 0.510% | 1.853% | 3.998% | 6.485% | -2.961% | 11.604% | -7.069% |
| (0.70,1.00] | 1,091 | 0.776% | -0.845% | 1.176% | 58.349% | 0.546% | 1.017% | 2.947% | 6.050% | -3.141% | 11.272% | -7.273% |
| >1.00 | 1,575 | 1.112% | -0.857% | 1.329% | 57.999% | 1.302% | 1.544% | 2.694% | 6.336% | -3.231% | 11.772% | -6.631% |

### Fixed extreme-bin contrasts

| Population | Low/High N | Event low-high | Date-equal low-high |
|---|---:|---:|---:|
| All | 288/1575 | 2.066% | -1.327% |
| Main | 255/1192 | 2.935% | -0.958% |
| ChiNext | 33/383 | -5.103% | -3.509% |
| Same-day reclaim | 178/1380 | 2.667% | -0.981% |
| Later reclaim | 110/195 | 1.468% | -1.373% |

### Year-by-year <=0.30 minus >1.00

| Year | Low/High N | Event low-high | Date-equal low-high |
|---:|---:|---:|---:|
| 2014 | 8/17 | -1.145% | -0.612% |
| 2015 | 191/1050 | 4.870% | 0.059% |
| 2016 | 13/123 | -6.111% | -2.327% |
| 2017 | 10/23 | -1.426% | -1.950% |
| 2018 | 13/105 | -2.926% | -2.042% |
| 2019 | 24/77 | -4.290% | -4.847% |
| 2020 | 20/102 | -3.744% | -3.522% |
| 2021 | 9/78 | 5.160% | 4.429% |

## Same-date stock-level incrementality

### MAIN

Eligible board-dates/events: 57/2,211. Daily Spearman mean/median/positive fraction: 0.1041/0.0828/54.4%. Date-equal low/high/low-minus-high T1-open: 0.963%/-0.058%/1.022%.

### CHINEXT

Eligible board-dates/events: 33/616. Daily Spearman mean/median/positive fraction: -0.0370/0.0333/54.5%. Date-equal low/high/low-minus-high T1-open: -0.565%/-0.369%/-0.196%.

### Fixed-effect diagnostic

- MAIN: 2,211 observations/57 dates; standardized Dryup coefficient 0.000135; `HIGHER_IS_BETTER_OR_NULL`; within-date R2 0.0164.
- CHINEXT: 616 observations/33 dates; standardized Dryup coefficient -0.000329; `LOWER_IS_BETTER`; within-date R2 0.0069.

## Progressive compression diagnostic

Fixed <=0.50 minus >1.00 event/date-equal T1-open: 1.972%/0.840%. Same-date Spearman means Main/ChiNext: 0.0311/-0.1115. Adds information: `False`.

## Fixed subgroup extreme-bin contrasts

| Family | Sleeve | Group | Event low-high | Date-equal low-high |
|---|---|---|---:|---:|
| gap_size | MAIN | 5-7% | 1.173% | 0.675% |
| gap_size | MAIN | 7-9% | 1.249% | -3.842% |
| gap_size | MAIN | >=9% | 3.387% | 0.343% |
| gap_size | CHINEXT | 5-7% | -2.121% | -1.536% |
| gap_size | CHINEXT | 7-9% | -4.716% | -4.772% |
| gap_size | CHINEXT | >=9% | -6.424% | -4.724% |
| drawdown | MAIN | 30-40% | -2.023% | -1.181% |
| drawdown | MAIN | 40-50% | 2.808% | 0.459% |
| drawdown | MAIN | >=50% | 6.085% | 0.936% |
| drawdown | CHINEXT | 30-40% | -6.511% | -5.950% |
| drawdown | CHINEXT | 40-50% | -9.288% | -7.540% |
| drawdown | CHINEXT | >=50% | -2.010% | -1.147% |
| panic_breadth | MAIN | below Q75 | -0.436% | -1.276% |
| panic_breadth | MAIN | Q75-Q90 | 1.696% | -1.461% |
| panic_breadth | MAIN | >=Q90 | 5.301% | -0.354% |
| panic_breadth | CHINEXT | below Q75 | -10.113% | -9.675% |
| panic_breadth | CHINEXT | Q75-Q90 | -4.902% | -5.596% |
| panic_breadth | CHINEXT | >=Q90 | -4.123% | -1.688% |

## Internal fixed K=20 chronology

### MAIN

| Test | BASE | Suffocation | Difference | BASE DD | Suffocation DD | BASE/Suff trades |
|---:|---:|---:|---:|---:|---:|---:|
| 2017 | -4.549% | -4.549% | 0.000% | -5.551% | -5.551% | 44/44 |
| 2018 | -11.844% | -11.844% | 0.000% | -12.190% | -12.190% | 99/99 |
| 2019 | -10.238% | -10.238% | -0.000% | -11.650% | -11.650% | 129/129 |
| 2020 | 3.271% | 2.970% | -0.301% | -4.758% | -4.758% | 163/163 |
| 2021 | -3.309% | -3.310% | -0.000% | -3.783% | -3.783% | 96/96 |

Stitched BASE/Suffocation/incremental: -24.580%/-24.800%/-0.220%; Sharpe increment -0.025; MaxDD increment -0.217%.

### CHINEXT

| Test | BASE | Suffocation | Difference | BASE DD | Suffocation DD | BASE/Suff trades |
|---:|---:|---:|---:|---:|---:|---:|
| 2017 | -1.424% | -1.424% | 0.000% | -1.822% | -1.822% | 13/13 |
| 2018 | -6.125% | -6.125% | -0.000% | -8.419% | -8.418% | 77/77 |
| 2019 | 0.280% | 0.280% | 0.000% | -1.443% | -1.443% | 37/37 |
| 2020 | 9.373% | 9.541% | 0.168% | -1.415% | -1.415% | 78/78 |
| 2021 | -4.066% | -4.065% | 0.000% | -4.496% | -4.496% | 67/67 |

Stitched BASE/Suffocation/incremental: -2.631%/-2.481%/0.149%; Sharpe increment 0.011; MaxDD increment 0.000%.

## Interpretation

Pooled support: `False`; same-date support: `True`; chronological support: `False`.

Corrected dry-up has partial descriptive evidence, but stock-level and forward allocation evidence are not jointly stable enough for a strategy claim.

Audit: `{'prebreak_dryup_uses_reclaim_or_post_reclaim_session_count': 0, 'prebreak_dryup_uses_future_volume_count': 0, 'prebreak_compression_uses_future_volume_count': 0, 'post_trigger_volume_used_count': 0, 'test_year_used_in_own_chronological_rule_count': 0, 'post_2021_outcome_read_count': 0, 'cross_board_contamination_count': 0, 'duplicate_position_entry_count': 0, 'max_concurrent_positions_violation_count': 0, 'negative_cash_or_leverage_violation_count': 0, 'validation_opened': False, 'final_oos_opened': False}`

Next action: Close V4 without opening Validation or tuning the representation; do not launch V5 unless genuinely independent evidence appears.
