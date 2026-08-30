# MKT-SHOCK-001 direction-neutral shock/relief representation

Decision: `CONTINUOUS_STRESS_SCORES_FROZEN_EXACT_EPISODE_REPRESENTATION_FAIL`.

## Boundary

- Output rows: 10696; normalized rows per group: 815..815.
- Strategy fields, future returns, post-decision paths, and CY-011 read: **none**.
- Rejected raw liquidity-activity change3/5/10 columns read: **none**.
- The process is direction-neutral. `RELIEF` is falling synchronization/activity stress, not price recovery; activity dry-up is not proven impairment.

## Role gates

| Role | Gate | Minimal disposition |
|---|---|---|
| synchronization_pressure | PASS | ACCEPT |
| joint_stress_score | PASS | ACCEPT |
| shock_onset | FAIL | representation_gate_failed |
| stress_dwell | FAIL | representation_gate_failed |
| stress_relief | FAIL | representation_gate_failed |
| activity_impairment | FAIL | representation_gate_failed |

## Continuous score stability

| Neighbor | Median within-group rho |
|---|---:|
| joint geometric | 0.933 |
| joint arithmetic | 0.794 |
| joint activity10 | 0.954 |
| joint activity60 | 0.938 |
| synchronization geometric | 0.978 |
| synchronization arithmetic | 0.934 |

ALL_STATUS/NON_ST median joint-score rho: 0.999.

## Episode robustness

| Threshold neighbor | Onset match min/median | STRESS Jaccard min/median | RELIEF Jaccard min/median | Dwell rho median | Relief rho median | Impairment Jaccard min/median |
|---|---|---|---|---:|---:|---|
| permissive | 1.000/1.000 | 0.000/0.000 | 0.000/0.067 | NA | NA | NA/NA |
| strict | 0.000/0.000 | NA/NA | 0.000/0.000 | NA | NA | NA/NA |

## Group event audit

| Group | Coverage | Normalized N | Onsets | Onset years | Dry-up observations | Dry-up years |
|---|---:|---:|---:|---:|---:|---:|
| ALL_A:ALL_STATUS | 0.977 | 815 | 1 | 1 | 0 | 0 |
| ALL_A:NON_ST | 0.977 | 815 | 1 | 1 | 0 | 0 |
| CHINEXT_BOARD:ALL_STATUS | 0.977 | 815 | 1 | 1 | 0 | 0 |
| CHINEXT_BOARD:NON_ST | 0.977 | 815 | 1 | 1 | 0 | 0 |
| SH_A:ALL_STATUS | 0.977 | 815 | 0 | 0 | 0 | 0 |
| SH_A:NON_ST | 0.977 | 815 | 0 | 0 | 0 | 0 |
| SZ_A:ALL_STATUS | 0.977 | 815 | 0 | 0 | 0 | 0 |
| SZ_A:NON_ST | 0.977 | 815 | 0 | 0 | 0 | 0 |

The exact episode representation fails first on event support: primary onsets range from zero to one per group versus the frozen minimum of eight across three years. Strict-threshold onset matching is zero; STRESS/RELIEF agreement and dwell/relief correlations are absent or below gate. No activity-dry-up observation occurs. These are sparse/unstable exact-state failures, not permission to lower the threshold after seeing the result.

## Volatility redundancy

Outcome-blind absolute-Spearman components at 0.85, including volatility controls: `[['activity_impairment'], ['intraday_range'], ['joint_stress_score'], ['shock_onset'], ['stress_dwell'], ['stress_relief'], ['synchronization_pressure'], ['volatility_change'], ['volatility_concentration'], ['volatility_level']]`.

Minimal nonredundant passing process roles: `synchronization_pressure, joint_stress_score`.

A same-date correlation with volatility is redundancy evidence only. It is not panic, causality, or forecasting evidence.

## Interpretation boundary

A passed continuous score means the joint historical-rank representation is stable across fixed shapes, activity horizons, denominators, and years. Episode roles must pass their own event/state/dwell/relief/dry-up gates and cannot inherit score acceptance.

No result can be called panic because the representation contains no frozen negative-direction coordinate. No result can be called price recovery because it reads no later price path. Strategy usefulness remains untested.

## Reproducibility

- Spec SHA-256: `9fb559c5d4a59f8fc83b6b7408edfc6534125edb9e4badfd6f8c3e3dccfe5fe3`.
- CLQ panel SHA-256: `d45993ceb0a1d28d23ff9c7f10552890f82629f4d63b729a9bd73a9101a6e573`.
- Volatility panel SHA-256: `f736128419bdd632444c70e12233b08823130ffccffffcd68a9f69f7330040dc`.
- Output panel SHA-256: `bba55a5ab23a252b73d7b85edb39d53404284d1c3c1ca4388b0dd4cd1b1889eb`.
