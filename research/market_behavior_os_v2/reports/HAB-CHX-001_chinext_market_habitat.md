# HAB-CHX-001 CHINEXT V1 market-habitat association

Decision: `EXPLORATORY_OPPORTUNITY_AND_PAYOFF_HABITAT_ASSOCIATION`.

This is exploratory association using already-consumed outcomes. It is not a causal mechanism, trading signal, habitat gate, or strategy authorization.

## Population and PIT boundary

- Common valid completed-close market dates: 1337 (2018-07-03..2023-12-29).
- Evaluated events / candidates / selected admissions / completed cycles: 819 / 638 / 280 / 280.
- Every completed cycle entered strictly after its signal-date close; all selected additions reconcile one-to-one.
- 2024-2025 is absent because the frozen state panels end in 2023. No proxy or backfill was used.
- A zero daily opportunity count is the observed V1 engine process, not pure latent-pattern incidence; exit-branch suppression and no qualifying structure are not separable in the event ledger.

## Frozen-coordinate continuous evidence

| Sample | Endpoint | Coordinate | N | Rho | 90% cluster CI | Early | Late | Same-sign years | Gate |
|---|---|---|---:|---:|---|---:|---:|---:|---|
| daily_process | evaluated_count | A | 1337 | 0.287 | [0.248, 0.324] | 0.301 | 0.287 | 6/6 | PASS |
| daily_process | evaluated_count | B | 1337 | 0.273 | [0.232, 0.313] | 0.309 | 0.291 | 6/6 | PASS |
| daily_process | evaluated_count | A_given_B | 1337 | 0.178 | [0.138, 0.218] | 0.142 | 0.217 | 6/6 | PASS |
| daily_process | evaluated_count | B_given_A | 1337 | 0.153 | [0.107, 0.197] | 0.160 | 0.222 | 5/6 | PASS |
| daily_process | candidate_count | A | 1337 | 0.291 | [0.252, 0.329] | 0.330 | 0.286 | 6/6 | PASS |
| daily_process | candidate_count | B | 1337 | 0.257 | [0.217, 0.299] | 0.309 | 0.282 | 6/6 | PASS |
| daily_process | candidate_count | A_given_B | 1337 | 0.192 | [0.152, 0.233] | 0.181 | 0.218 | 6/6 | PASS |
| daily_process | candidate_count | B_given_A | 1337 | 0.131 | [0.087, 0.173] | 0.137 | 0.212 | 6/6 | PASS |
| daily_process | selected_count | A | 1337 | 0.151 | [0.113, 0.190] | 0.161 | 0.146 | 5/6 | PASS |
| daily_process | selected_count | B | 1337 | 0.154 | [0.111, 0.194] | 0.155 | 0.181 | 6/6 | PASS |
| daily_process | selected_count | A_given_B | 1337 | 0.085 | [0.044, 0.123] | 0.081 | 0.096 | 4/6 | FAIL |
| daily_process | selected_count | B_given_A | 1337 | 0.090 | [0.048, 0.132] | 0.070 | 0.145 | 6/6 | FAIL |
| event_conversion | admissible_candidate | A | 819 | 0.111 | [0.048, 0.171] | 0.202 | 0.094 | 5/5 | PASS |
| event_conversion | admissible_candidate | B | 819 | 0.049 | [-0.010, 0.109] | 0.156 | 0.035 | 5/5 | FAIL |
| event_conversion | admissible_candidate | A_given_B | 819 | 0.101 | [0.043, 0.160] | 0.134 | 0.088 | 5/5 | PASS |
| event_conversion | admissible_candidate | B_given_A | 819 | -0.017 | [-0.076, 0.041] | 0.032 | 0.010 | 2/5 | FAIL |
| event_conversion | selected_admission | A | 819 | -0.157 | [-0.249, -0.068] | -0.316 | -0.101 | 5/5 | PASS |
| event_conversion | selected_admission | B | 819 | -0.123 | [-0.213, -0.029] | -0.238 | -0.085 | 4/5 | PASS |
| event_conversion | selected_admission | A_given_B | 819 | -0.107 | [-0.197, -0.016] | -0.218 | -0.082 | 5/5 | PASS |
| event_conversion | selected_admission | B_given_A | 819 | -0.041 | [-0.128, 0.045] | -0.043 | -0.060 | 3/5 | FAIL |
| candidate_selection | selected_admission | A | 638 | -0.248 | [-0.351, -0.135] | -0.498 | -0.162 | 5/5 | PASS |
| candidate_selection | selected_admission | B | 638 | -0.171 | [-0.285, -0.063] | -0.370 | -0.115 | 4/5 | PASS |
| candidate_selection | selected_admission | A_given_B | 638 | -0.185 | [-0.294, -0.078] | -0.366 | -0.137 | 5/5 | PASS |
| candidate_selection | selected_admission | B_given_A | 638 | -0.036 | [-0.143, 0.071] | -0.069 | -0.075 | 3/5 | FAIL |
| completed_cycle | round_trip_return | A | 280 | -0.148 | [-0.254, -0.030] | -0.400 | -0.042 | 4/5 | FAIL |
| completed_cycle | round_trip_return | B | 280 | -0.018 | [-0.146, 0.094] | -0.178 | 0.050 | 3/5 | FAIL |
| completed_cycle | round_trip_return | A_given_B | 280 | -0.156 | [-0.268, -0.037] | -0.364 | -0.061 | 4/5 | PASS |
| completed_cycle | round_trip_return | B_given_A | 280 | 0.054 | [-0.074, 0.172] | 0.016 | 0.067 | 3/5 | FAIL |
| completed_cycle | mfe | A | 280 | 0.122 | [0.011, 0.243] | 0.007 | 0.078 | 3/5 | FAIL |
| completed_cycle | mfe | B | 280 | 0.187 | [0.079, 0.294] | 0.258 | -0.031 | 3/5 | FAIL |
| completed_cycle | mfe | A_given_B | 280 | 0.044 | [-0.068, 0.162] | -0.137 | 0.093 | 3/5 | FAIL |
| completed_cycle | mfe | B_given_A | 280 | 0.150 | [0.039, 0.258] | 0.290 | -0.059 | 3/5 | FAIL |
| completed_cycle | mae | A | 280 | -0.198 | [-0.311, -0.089] | -0.419 | -0.066 | 4/5 | PASS |
| completed_cycle | mae | B | 280 | -0.129 | [-0.256, -0.008] | -0.343 | 0.042 | 2/5 | FAIL |
| completed_cycle | mae | A_given_B | 280 | -0.158 | [-0.269, -0.053] | -0.309 | -0.084 | 4/5 | PASS |
| completed_cycle | mae | B_given_A | 280 | -0.047 | [-0.176, 0.073] | -0.179 | 0.066 | 3/5 | FAIL |
| completed_cycle | winner20 | A | 280 | 0.022 | [-0.062, 0.111] | -0.141 | 0.121 | 2/5 | FAIL |
| completed_cycle | winner20 | B | 280 | 0.127 | [0.047, 0.203] | 0.020 | 0.174 | 3/5 | FAIL |
| completed_cycle | winner20 | A_given_B | 280 | -0.039 | [-0.146, 0.069] | -0.171 | 0.071 | 2/5 | FAIL |
| completed_cycle | winner20 | B_given_A | 280 | 0.131 | [0.029, 0.218] | 0.100 | 0.144 | 4/5 | PASS |
| completed_cycle | winner50 | A | 280 | -0.006 | [-0.090, 0.086] | -0.181 | 0.115 | 1/5 | FAIL |
| completed_cycle | winner50 | B | 280 | 0.043 | [-0.029, 0.112] | 0.054 | 0.087 | 2/5 | FAIL |
| completed_cycle | winner50 | A_given_B | 280 | -0.029 | [-0.129, 0.082] | -0.236 | 0.093 | 2/5 | FAIL |
| completed_cycle | winner50 | B_given_A | 280 | 0.051 | [-0.046, 0.149] | 0.163 | 0.053 | 3/5 | FAIL |
| completed_cycle | severe_loss10 | A | 280 | 0.173 | [0.071, 0.272] | 0.331 | 0.007 | 4/5 | FAIL |
| completed_cycle | severe_loss10 | B | 280 | 0.140 | [0.035, 0.242] | 0.320 | -0.077 | 2/5 | FAIL |
| completed_cycle | severe_loss10 | A_given_B | 280 | 0.125 | [0.038, 0.207] | 0.214 | 0.033 | 4/5 | FAIL |
| completed_cycle | severe_loss10 | B_given_A | 280 | 0.072 | [-0.013, 0.153] | 0.195 | -0.084 | 2/5 | FAIL |
| completed_cycle | extreme_loss20 | A | 280 | 0.071 | [NA, NA] | 0.077 | NA | 1/5 | FAIL |
| completed_cycle | extreme_loss20 | B | 280 | 0.091 | [NA, NA] | 0.112 | NA | 1/5 | FAIL |
| completed_cycle | extreme_loss20 | A_given_B | 280 | 0.035 | [-0.070, 0.076] | 0.027 | 0.093 | 2/5 | FAIL |
| completed_cycle | extreme_loss20 | B_given_A | 280 | 0.066 | [-0.073, 0.117] | 0.086 | NA | 2/5 | FAIL |
| completed_cycle | false_breakout | A | 280 | -0.011 | [-0.121, 0.094] | 0.149 | -0.007 | 2/5 | FAIL |
| completed_cycle | false_breakout | B | 280 | -0.092 | [-0.200, 0.023] | -0.023 | -0.040 | 1/5 | FAIL |
| completed_cycle | false_breakout | A_given_B | 280 | 0.033 | [-0.079, 0.138] | 0.182 | 0.006 | 3/5 | FAIL |
| completed_cycle | false_breakout | B_given_A | 280 | -0.097 | [-0.203, 0.020] | -0.108 | -0.040 | 2/5 | FAIL |
| completed_cycle | opportunity20 | A | 280 | 0.065 | [-0.036, 0.177] | -0.050 | 0.088 | 3/5 | FAIL |
| completed_cycle | opportunity20 | B | 280 | 0.190 | [0.074, 0.299] | 0.212 | 0.079 | 4/5 | PASS |
| completed_cycle | opportunity20 | A_given_B | 280 | -0.021 | [-0.134, 0.087] | -0.176 | 0.067 | 3/5 | FAIL |
| completed_cycle | opportunity20 | B_given_A | 280 | 0.180 | [0.061, 0.287] | 0.269 | 0.055 | 3/5 | FAIL |
| completed_cycle | giveback_from_peak | A | 280 | 0.297 | [0.184, 0.404] | 0.398 | 0.159 | 3/5 | FAIL |
| completed_cycle | giveback_from_peak | B | 280 | 0.297 | [0.179, 0.408] | 0.561 | -0.045 | 3/5 | FAIL |
| completed_cycle | giveback_from_peak | A_given_B | 280 | 0.193 | [0.088, 0.299] | 0.179 | 0.183 | 4/5 | PASS |
| completed_cycle | giveback_from_peak | B_given_A | 280 | 0.193 | [0.077, 0.310] | 0.460 | -0.101 | 3/5 | FAIL |
| opportunity20_conversion | conversion20 | A | 53 | -0.061 | [-0.272, 0.172] | -0.304 | 0.245 | 0/0 | FAIL |
| opportunity20_conversion | conversion20 | B | 53 | -0.034 | [-0.232, 0.204] | -0.324 | 0.444 | 0/0 | FAIL |
| opportunity20_conversion | conversion20 | A_given_B | 53 | -0.051 | [-0.272, 0.196] | -0.162 | 0.168 | 0/0 | FAIL |
| opportunity20_conversion | conversion20 | B_given_A | 53 | -0.009 | [-0.229, 0.210] | -0.200 | 0.412 | 0/0 | FAIL |

A is the absolute 60-session CHINEXT-index log direction. B is the absolute CHINEXT-board net new-high/new-low fraction. Partial rows residualize ranked coordinate and endpoint on the other ranked coordinate. They are not additional mechanisms.

## BASELINE / A / B / A+B

| Sample | Endpoint | Adj-R2 A | Adj-R2 B | Adj-R2 A+B | Increment | Interaction 90% CI | Gate |
|---|---|---:|---:|---:|---:|---|---|
| daily_process | evaluated_count | 0.057 | 0.023 | 0.067 | 0.011 | [0.007, 0.063] | PASS |
| daily_process | candidate_count | 0.056 | 0.022 | 0.068 | 0.012 | [0.008, 0.062] | PASS |
| daily_process | selected_count | 0.015 | 0.009 | 0.017 | 0.002 | [-0.008, 0.011] | FAIL |
| event_conversion | admissible_candidate | 0.013 | 0.005 | 0.013 | -0.000 | [0.001, 0.031] | FAIL |
| event_conversion | selected_admission | 0.024 | 0.005 | 0.026 | 0.002 | [-0.042, 0.011] | FAIL |
| candidate_selection | selected_admission | 0.060 | 0.014 | 0.064 | 0.004 | [-0.048, 0.009] | FAIL |
| completed_cycle | round_trip_return | 0.002 | -0.003 | 0.033 | 0.031 | [-0.052, -0.019] | FAIL |
| completed_cycle | mfe | -0.002 | 0.005 | 0.013 | 0.008 | [-0.057, -0.013] | FAIL |
| completed_cycle | mae | 0.049 | 0.008 | 0.083 | 0.034 | [-0.013, -0.002] | FAIL |
| completed_cycle | winner20 | -0.003 | -0.004 | 0.011 | 0.014 | [-0.075, -0.023] | FAIL |
| completed_cycle | winner50 | -0.004 | -0.003 | -0.002 | 0.001 | [-0.034, -0.004] | FAIL |
| completed_cycle | severe_loss10 | 0.031 | 0.022 | 0.084 | 0.053 | [0.024, 0.101] | FAIL |
| completed_cycle | extreme_loss20 | 0.001 | 0.000 | -0.005 | -0.005 | [-0.004, 0.004] | FAIL |
| completed_cycle | false_breakout | -0.004 | 0.009 | 0.013 | 0.004 | [-0.000, 0.123] | FAIL |
| completed_cycle | opportunity20 | 0.001 | 0.021 | 0.032 | 0.011 | [-0.107, -0.021] | FAIL |
| completed_cycle | giveback_from_peak | 0.046 | 0.037 | 0.057 | 0.011 | [-0.010, 0.011] | FAIL |
| opportunity20_conversion | conversion20 | -0.016 | 0.022 | 0.069 | 0.048 | [-0.407, -0.090] | FAIL |

The nested OLS/LPM comparison is a fixed association diagnostic, not an executable fitted predictor. No failed model is rescued by a new boundary or link function.

## Interpretation

Direction and discovery each have stable positive association with evaluated, candidate, and selected counts. Their partial-rank associations remain positive for evaluated and candidate counts. The fixed A+B interaction passes only for those two daily formation counts; it fails selected counts and every payoff endpoint.

Conditional on an evaluated event or admissible candidate, selected-admission rates fall as state strength rises. This is consistent with opportunity density meeting a finite-vacancy, maximum-ten-position strategy architecture; it is not evidence that the market state rejects demand or that fewer admissions would improve returns. The breadth selection-rate association does not survive the strict B-given-A gate.

Payoff separation is narrow. Higher direction associates with more-negative MAE (A rho -0.198; A-given-B rho -0.158), so it is not a defensive habitat result. Discovery breadth associates with MFE>=20% opportunity (B rho 0.190), but its B-given-A gate and the conversion20 gate fail. No absolute primary gate passes for completed-cycle return, winner20, winner50, false breakout, severe loss, extreme loss, or within-opportunity conversion. Opportunity incidence is not harvested-edge evidence.

## Fixed economic sign cells

| Cell | Dates | Events | Candidates/event | Selected/event | Cycles | Mean return | Winner20 | False breakout | Severe loss |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NEITHER | 320 | 49 | 81.63% | 61.22% | 30 | -1.42% | 0.00% | 63.33% | 6.67% |
| A_ONLY | 119 | 41 | 78.05% | 43.90% | 18 INSUFFICIENT | 0.24% | 0.00% | 38.89% | 5.56% |
| B_ONLY | 383 | 163 | 65.03% | 34.97% | 57 | 5.77% | 10.53% | 54.39% | 7.02% |
| A_AND_B | 515 | 566 | 81.27% | 30.92% | 175 | 0.99% | 8.57% | 53.71% | 11.43% |

These cells use the predeclared zero boundaries for economic legibility only. A_ONLY has fewer than 20 cycles and is explicitly insufficient. MKT-GEO-001 already warned that the discovery-zero boundary is occupancy-imbalanced; no cell is an action rule. B_ONLY's positive mean is paired with 0.994 top-20 positive-PnL concentration, so it is not broad payoff support.

## Breadth denominator sensitivity

The NON_ST breadth coordinate is reported only as a neighboring-denominator sensitivity. It cannot replace the ALL_STATUS primary. Full results are preserved in the JSON artifact.

## Matrix completeness and limitations

Observed opportunity generation, admission conversion, completed-cycle return, right-tail, and severe-failure behavior are measurable. Habitat-specific counterfactual NAV, drawdown, turnover, execution-cost impact, and capacity are not identified by this zero-replay association and remain unpopulated. Positive-PnL concentration is descriptive and the strategy remains right-tail dependent.

The two state coordinates may describe association but cannot prove that changing exposure or admission would improve results. Existing outcomes are fully consumed; independent future time is still required for confirmation.

## Synthesis checkpoint

**What market behavior are we still not studying?** Recurring correlation/liquidity shock recovery, non-slope intraday transitions, action-safe support/acceptance, accumulation/distribution falsification, and multi-strategy habitat portability remain open.

**Has any discovered mechanism implied a genuinely new strategy archetype?** No. This experiment concerns one existing breakout seed and has no new trigger, veto, exit, recurring opportunity process independent of V1, or validated capacity profile.

## Reproducibility

- Spec SHA-256: `c17f8ea89cee61dc1ede89722bde38d0710c2a254b15e972fb19bd9664305a38`.
- Panel SHA-256: `922920fdd0f1d81391825b2084971b22b044536754604590c62a2b4d98f9afde`.
- Result evidence uses 2000 deterministic cluster resamples with seed 20260830.
