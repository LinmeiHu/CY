# Phase 3 — preregistered univariate regime attribution

EXP-P3-002 joined the frozen Phase 2 completed-close features to the 399 authoritative cycles on entry signal date. This is exploratory mechanism evidence over already-consumed 2018-2025 outcomes, not untouched OOS evidence and not a strategy experiment.

## Causal and sample audit

- Joined completed cycles: `399`; missing joins: `0`
- Causal timestamp failures: `0`; same-day fills: `0`
- Frozen market-MA20 entry-gate failures: `0`
- Features tested: `93`; feature/outcome estimates: `930`; BH q<=0.10: `214` (descriptive only)
- Missing features and early continuation horizons were deleted pairwise; nothing was imputed or set to zero.

## Preregistered family verdicts

| Family | Verdict | Surviving primary features |
|---|---|---|
| H-003_trend_persistence | REJECTED_BY_PREREGISTERED_UNIVARIATE_FALSIFICATION | none |
| H-004_breadth | SUPPORTED_FOR_FURTHER_CONDITIONAL_TESTING | breadth_above_ma20, breadth_positive_return20, breadth_above_ma20_change20 |
| H-005_rotation_persistence | REJECTED_BY_PREREGISTERED_UNIVARIATE_FALSIFICATION | none |
| H-006_dispersion_tail | AMBIGUOUS_SINGLE_FEATURE_SURVIVOR | cross_sectional_return20_right_tail_ge20 |
| H-007_volatility | AMBIGUOUS_UNIVARIATE_NO_SIGN_PREREGISTERED | none |

A feature survives only if either its >=20% winner or MFE Spearman effect has |rho|>=0.10, matches the preregistered sign, agrees with the pooled within-year rank sign, keeps that sign in at least 7/8 leave-one-year-out estimates, and has no >=50% winner effect of |rho|>=0.10 in the opposite direction. A family needs at least two surviving primary features. Volatility had no monotone sign preregistered, so this phase cannot support H-007 or authorize an interaction by itself.

## Primary feature diagnostics

| Feature | Family | Exp sign | RT20 rho | Within-year RT20 | RT20 LOYO | MFE rho | Within-year MFE | MFE LOYO | Survives |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| index_return_60d | H-003_trend_persistence | 1 | -0.066 | -0.074 | 7/8 | 0.017 | -0.020 | 4/8 | NO |
| index_close_to_ma60 | H-003_trend_persistence | 1 | -0.006 | -0.003 | 5/8 | 0.082 | 0.076 | 8/8 | NO |
| index_ma20_slope_5d | H-003_trend_persistence | 1 | -0.042 | -0.008 | 7/8 | 0.033 | 0.023 | 7/8 | NO |
| index_above_ma20_fraction20 | H-003_trend_persistence | 1 | -0.075 | -0.067 | 7/8 | -0.044 | -0.092 | 6/8 | NO |
| index_above_ma20_state_flips20 | H-003_trend_persistence | -1 | 0.032 | -0.020 | 7/8 | -0.057 | -0.087 | 8/8 | NO |
| breadth_above_ma20 | H-004_breadth | 1 | 0.140 | 0.150 | 8/8 | 0.211 | 0.232 | 8/8 | YES |
| breadth_above_ma60 | H-004_breadth | 1 | -0.015 | 0.020 | 6/8 | 0.033 | 0.080 | 6/8 | NO |
| breadth_positive_return20 | H-004_breadth | 1 | 0.073 | 0.083 | 8/8 | 0.101 | 0.108 | 8/8 | YES |
| breadth_above_ma20_change20 | H-004_breadth | 1 | 0.154 | 0.112 | 8/8 | 0.203 | 0.200 | 8/8 | YES |
| breadth_above_ma20_state_flips20 | H-004_breadth | -1 | 0.173 | 0.147 | 8/8 | 0.143 | 0.121 | 8/8 | NO |
| ret20_cross_sectional_rank_stability5 | H-005_rotation_persistence | 1 | 0.004 | 0.022 | 6/8 | 0.075 | 0.099 | 8/8 | NO |
| ret20_top_decile_overlap5 | H-005_rotation_persistence | 1 | -0.156 | -0.146 | 8/8 | -0.040 | -0.082 | 7/8 | NO |
| leadership_turnover5 | H-005_rotation_persistence | -1 | 0.156 | 0.143 | 8/8 | 0.040 | 0.071 | 7/8 | NO |
| ret5_current_vs_prior5_cross_sectional_correlation | H-005_rotation_persistence | 1 | -0.100 | -0.078 | 8/8 | -0.038 | -0.073 | 7/8 | NO |
| cross_sectional_return20_p90 | H-006_dispersion_tail | 1 | 0.043 | 0.081 | 8/8 | 0.098 | 0.108 | 8/8 | NO |
| cross_sectional_return20_p90_p10_spread | H-006_dispersion_tail | 1 | 0.012 | 0.068 | 6/8 | 0.070 | 0.089 | 8/8 | NO |
| cross_sectional_return20_skewness | H-006_dispersion_tail | 1 | -0.020 | -0.105 | 8/8 | 0.010 | -0.105 | 4/8 | NO |
| cross_sectional_return20_right_tail_ge20 | H-006_dispersion_tail | 1 | 0.046 | 0.089 | 8/8 | 0.111 | 0.117 | 8/8 | YES |
| cross_sectional_return20_left_tail_le_neg20 | H-006_dispersion_tail | -1 | 0.007 | -0.037 | 6/8 | -0.081 | -0.079 | 8/8 | NO |
| index_realized_vol20 | H-007_volatility | 0 | 0.013 | -0.057 | 5/8 | 0.032 | -0.010 | 7/8 | NO |
| index_vol20_to_vol60 | H-007_volatility | 0 | 0.094 | 0.085 | 8/8 | 0.106 | 0.099 | 8/8 | NO |
| cross_sectional_return20_std | H-007_volatility | 0 | -0.022 | -0.067 | 6/8 | 0.061 | -0.006 | 8/8 | NO |
| index_atr20_to_close | H-007_volatility | 0 | -0.020 | -0.100 | 6/8 | -0.005 | -0.052 | 3/8 | NO |

## Strongest preregistered descriptive associations

These rankings are reports, not selection rules.

| Endpoint | Feature | Spearman rho | BH q | Direction stable |
|---|---|---:|---:|---|
| >=20% winner | breadth_above_ma20_state_flips20 | 0.173 | 0.009 | YES |
| >=20% winner | leadership_turnover5 | 0.156 | 0.017 | YES |
| >=20% winner | ret20_top_decile_overlap5 | -0.156 | 0.017 | YES |
| >=20% winner | breadth_above_ma20_change20 | 0.154 | 0.018 | YES |
| >=20% winner | breadth_above_ma20 | 0.140 | 0.034 | YES |
| MFE | breadth_above_ma20 | 0.211 | 0.001 | YES |
| MFE | breadth_above_ma20_change20 | 0.203 | 0.002 | YES |
| MFE | breadth_above_ma20_state_flips20 | 0.143 | 0.032 | YES |
| MFE | cross_sectional_return20_right_tail_ge20 | 0.111 | 0.113 | YES |
| MFE | index_vol20_to_vol60 | 0.106 | 0.125 | YES |

## Falsification and limits

- Every estimate includes within-entry-year ranks, eight LOYO estimates, entry-year and baseline-block views, and a global ex-best-five-P&L return sensitivity where applicable.
- All actual entries are already conditioned on the binary 399102-above-MA20 gate. The analysis distinguishes continuous gate strength among admitted entries; it does not compare entries with forbidden non-entry days.
- Pooled quintiles are fixed from feature values only and include all outcomes. They diagnose shape and monotonicity but do not define a threshold.
- BH q-values address the reported 93-feature screen, but dependence, small tail-event counts, PIT-B lineage, and already-consumed outcomes cap evidentiary strength.
- No interaction, overlay, entry gate, exposure rule, exit rule, or year parameter was tested or authorized in Phase 3.

## Phase verdict

At least one preregistered family passed the univariate stability gate and may proceed only to a narrow, evidence-supported conditional test. This is not strategy authorization.

Detailed result artifact SHA-256: `d06d7af4384ea651495900683fe6dccd3db3518204d37e56aa0e0cbe5e3ac813`
