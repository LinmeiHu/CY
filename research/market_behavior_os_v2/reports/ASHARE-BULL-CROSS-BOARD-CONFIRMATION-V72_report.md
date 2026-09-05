# ASHARE-BULL-CROSS-BOARD-CONFIRMATION-V72

`V72_CONFIDENT_CROSS_BOARD_QUALITY_PROFILE`

V72 leaves every V65 stock, industry, market, entry, target, exit, cost and portfolio semantic unchanged. It adds one categorical confirmation: at the completed signal close, both Main and ChiNext must contain at least one independently qualified V65 signal.

## Scientific 2014-2023

|Year|Trades|Mean net|Median net|Date-equal|Win|Severe10|Mean hold|Portfolio return|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|2014|94|4.51%|4.87%|4.98%|65.96%|1.06%|16.85|6.85%|
|2015|81|8.50%|10.33%|9.58%|82.72%|0.00%|17.48|12.48%|
|2016|72|3.12%|1.29%|2.63%|63.89%|2.78%|15.06|3.90%|
|2017|84|3.71%|2.46%|2.63%|64.29%|1.19%|14.65|5.12%|
|2018|70|1.52%|-0.10%|-0.06%|50.00%|4.29%|14.59|1.89%|
|2019|170|5.58%|6.43%|5.36%|66.47%|4.12%|12.45|14.76%|
|2020|151|3.70%|3.49%|5.05%|57.62%|11.26%|12.52|11.13%|
|2021|91|4.34%|4.24%|4.58%|64.84%|4.40%|13.18|6.71%|
|2022|72|1.91%|1.32%|1.62%|58.33%|11.11%|14.21|2.00%|
|2023|136|2.55%|0.82%|3.00%|55.15%|2.94%|14.02|5.67%|

## Economic interpretation

A single-board burst can be a local theme rotation. Simultaneous qualified pressure breaks on Main and ChiNext are a PIT market-state confirmation that demand is diffusing across listing regimes. This is not a stock chart filter and does not use future breadth.

## V65 comparison

V72 accepts 1021 trades (102.1 per year), with 4.06% mean, 3.49% median, 62.68% win rate, 4.60% severe-loss10 and 14.17 mean holding sessions.
Portfolio CAGR is 7.10%, MaxDD -5.13%, and Sharpe 1.409.
The V72-minus-V65 capacity-trade mean difference is 0.51%; signal-date cluster-bootstrap 95% CI [0.06%, 1.00%]. Severe-loss10 changes by -1.09%, with 95% CI [-2.30%, -0.02%].
V72 is a quality profile, not a replacement for V65 when maximum signal coverage and absolute CAGR are the primary objective. The signals overlap by construction and must not be double-counted as independent strategies.

## Outcome-blind chart audit

Thirty charts (15 confirmed and 15 single-board controls) end at the signal close and show stock candles, turnover, market return/breadth and industry return/breadth. They are stored under `/Volumes/quant/CY_quant_research/bull_cross_board_confirmation_v72/stage_a/blind_charts`. No manual chart exclusion changed the rule.

## Post-observation diagnostic

The 2024-current sample was already exposed and is not pristine confirmation.

|Year|Trades|Mean net|Date-equal|Portfolio return|
|---:|---:|---:|---:|---:|
|2024|121|5.04%|1.44%|10.33%|
|2025|160|1.53%|1.92%|3.79%|
|2026|87|4.36%|3.17%|6.55%|

## Optimization stopping decision

Uniform wider targets, early-lane quality plus wider target, steady-diffusion additions, and structural failure exits were not promoted. Their improvement was insignificant, chronologically weak, or obtained by cutting normal bull-market retests. V65 should not be tuned further on already observed years. Preserve V65 for coverage and V72 as its higher-quality deployment profile.

Audit: `{"all_accepted_cost_identity_violation_count": 0, "all_accepted_duplicate_event_count": 0, "all_entry_after_three_session_window_count": 0, "all_max_k_violation_count": 0, "all_negative_cash_count": 0, "all_signal_bar_fill_count": 0, "all_t1_same_day_exit_count": 0, "availability_after_decision_count": 0, "cross_board_gate_violation_count": 0, "cross_board_state_after_decision_count": 0, "decision_not_signal_close_count": 0, "development_accepted_cost_identity_violation_count": 0, "development_accepted_duplicate_event_count": 0, "development_entry_after_three_session_window_count": 0, "development_signal_bar_fill_count": 0, "development_t1_same_day_exit_count": 0, "duplicate_event_count": 0, "duplicate_source_event_count": 0, "entry_target_exit_changed_count": 0, "feature_after_decision_count": 0, "hard_valid_false_count": 0, "max_k_violation_count": 0, "missing_chinext_confirmation_count": 0, "missing_main_confirmation_count": 0, "negative_cash_count": 0, "post_2023_candidate_count": 0, "post_2023_used_for_gate_definition_count": 0, "post_accepted_cost_identity_violation_count": 0, "post_accepted_duplicate_event_count": 0, "post_availability_after_decision_count": 0, "post_cross_board_gate_violation_count": 0, "post_cross_board_state_after_decision_count": 0, "post_entry_after_three_session_window_count": 0, "post_feature_after_decision_count": 0, "post_max_k_violation_count": 0, "post_negative_cash_count": 0, "post_signal_bar_fill_count": 0, "post_t1_same_day_exit_count": 0, "scientific_accepted_cost_identity_violation_count": 0, "scientific_accepted_duplicate_event_count": 0, "scientific_entry_after_three_session_window_count": 0, "scientific_signal_bar_fill_count": 0, "scientific_t1_same_day_exit_count": 0, "source_outcome_semantics_changed_count": 0}`.
