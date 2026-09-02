# ASHARE-COLLAPSE-GAP-ZONE-STRATEGY-DEVELOPMENT-V1

Frozen spec SHA-256: `e0846c4464f82b65dc7cad99a13bcfdf3666001338225727b9544220f74bfcd8`

## Development verdict

**MARGINAL_ZONE_STRATEGY_EDGE**

## MAIN

Selected sequence: `['E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20', 'E1_FIRST_ACCEPT|FULL|F2_NO_FAILURE_STOP|T20', 'E1_FIRST_ACCEPT|FULL|F2_NO_FAILURE_STOP|T20', 'E1_FIRST_ACCEPT|P75|F2_NO_FAILURE_STOP|T20', 'E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20']`
Stability: **MODERATELY_ADAPTIVE**

| Test year | Selected | Test return | Trades |
|---:|---|---:|---:|
| 2017 | `E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20` | -1.6026% | 37 |
| 2018 | `E1_FIRST_ACCEPT|FULL|F2_NO_FAILURE_STOP|T20` | 3.6027% | 31 |
| 2019 | `E1_FIRST_ACCEPT|FULL|F2_NO_FAILURE_STOP|T20` | 0.9491% | 61 |
| 2020 | `E1_FIRST_ACCEPT|P75|F2_NO_FAILURE_STOP|T20` | -6.2660% | 96 |
| 2021 | `E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20` | -0.4575% | 89 |

Stitched: total -3.9797%, CAGR -0.8374%, MaxDD -12.8340%, Sharpe -0.145, Calmar -0.065.
Baseline total return: -16.7223%. Top-5 neighborhood median -0.4575%, profitable fraction 44.0%.
Selection frequencies: entry Counter({'E1_FIRST_ACCEPT': 3, 'E4_SECOND_RECLAIM': 2}); target Counter({'FULL': 4, 'P75': 1}); failure Counter({'F2_NO_FAILURE_STOP': 5}); stop Counter({'T20': 5}).
Concentration: ex-2020 2.4392%; ex-best-day -5.5493%; ex-best-five-days -11.1524%.

## CHINEXT

Selected sequence: `['SELECTION_BLOCKED', 'E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20', 'E2_QUARTER_ACCEPT|FULL|F2_NO_FAILURE_STOP|T20', 'E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20', 'E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20']`
Stability: **MODERATELY_ADAPTIVE**

| Test year | Selected | Test return | Trades |
|---:|---|---:|---:|
| 2017 | `SELECTION_BLOCKED` | 0.0000% | 0 |
| 2018 | `E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20` | 1.8286% | 13 |
| 2019 | `E2_QUARTER_ACCEPT|FULL|F2_NO_FAILURE_STOP|T20` | -0.1385% | 37 |
| 2020 | `E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20` | -0.7586% | 60 |
| 2021 | `E4_SECOND_RECLAIM|FULL|F2_NO_FAILURE_STOP|T20` | 6.5912% | 51 |

Stitched: total 7.5677%, CAGR 1.5220%, MaxDD -5.3800%, Sharpe 0.405, Calmar 0.283.
Baseline total return: -11.9953%. Top-5 neighborhood median 0.0721%, profitable fraction 55.0%.
Selection frequencies: entry Counter({'E4_SECOND_RECLAIM': 3, 'E2_QUARTER_ACCEPT': 1}); target Counter({'FULL': 4}); failure Counter({'F2_NO_FAILURE_STOP': 4}); stop Counter({'T20': 4}).
Concentration: ex-2020 8.3900%; ex-best-day 5.7184%; ex-best-five-days 0.9455%.

## Fixed 50/50 combined

Total 1.7940%; CAGR 0.3689%; MaxDD -7.4529%; Sharpe 0.122; Calmar 0.049.

## Translation diagnostics

SECOND_RECLAIM is repeatedly selected (Main 2/5, ChiNext 3/4 eligible folds), but its next-year sign is mixed; it does not robustly solve first-entry rejection. QUARTER_ACCEPT appears once and is slightly negative next year; HALF_ACCEPT is never selected. F2 NO_FAILURE_STOP and T20 are selected in every eligible fold, while FULL is selected in eight of nine folds. The evidence therefore favors tolerating rejection and allowing structural traversal time over cutting the first daily loss of zone, but that translation remains only marginal at portfolio level.

## Correctness audit

Audit counters: `{'pattern_detector_changed_count': 0, 'test_year_used_in_own_selection_count': 0, 'cross_board_selection_contamination_count': 0, 'entry_uses_future_bar_count': 0, 't1_same_day_sell_violation_count': 0, 'duplicate_position_count': 0, 'max_k_violation_count': 0, 'negative_cash_or_leverage_count': 0, 'post_2021_outcome_read_count': 0}`. QD-010 audit: `{'registered_relevant_events': 2783, 'risk_events': 666, 'cash_only_events': 2117, 'selected_forced_exits': 3, 'selected_blocked_positions': 0, 'risk_blocked_candidate_rows': 144}`. All selection used TRAIN only; boards were selected independently; all entries used the next legal minute; T+1 same-day sales, duplicate positions, K violations, leverage, and post-2021 reads were audited fail-closed.

## Research semantic postmortem

The early line treated a local single-day gap and Open×1.01 as the concept; these were semantic mismatches. Same-day reclaims were also incorrectly allowed to stand for a persistent collapse layer, and generic high-return stocks replaced true former leaders. Formation-panic evidence remains specific to formation, not reclaim. The corrected V3 detector and Outcome Discovery remain informative about structural traversal, while old fixed T+1-open/T+3-close failures and immediate-first-entry failures must not be generalized to all zone-based translations. The robust surviving insight is that eventual traversal and immediate acceptance are distinct economic objects; T+1, PIT lineage, suspension, limits, and corporate actions remain mandatory in every version.
