# ASHARE-FORMER-LEADER-FORMATION-PANIC-STRICT-GAP-RECLAIM-V5

## Development verdict

**NO_FORMATION_PANIC_INTERACTION_EDGE**

V5 correctly anchors market panic to each strict gap's formation date. Reclaim-date breadth is retained only as a transition diagnostic and never enters eligibility, calibration, or selection. The 2017–2021 folds are internal chronological pseudo-OOS evidence; Validation and Final OOS remain sealed.

## Formation-panic contract

- Frozen spec SHA-256: `5c3e37833a4ba92492a3b688f216bbe9ad732f1ee992c5cf49a1e3b96ecc7938`
- Calibration: independent Main/ChiNext Q75 and Q90 values from unique source-population gap dates in TRAIN only.
- Search: 576 configurations per board per fold; 5,760 board/fold rows in total.
- Selector: maximum TRAIN Calmar after the 60-total/10-recent completed-trade gate and frozen tie-breaks.

## MAIN

| Test | Selected | Q75 / Q90 | Train Calmar | Full | No panic | Panic increment | Broad same panic | Structure increment | Trades |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2017 | `l95|r0.80|dd0.30|g0.09|aU|pNONE|xT1_LEGAL_OPEN|k50` | 2.68% / 22.99% | 1.486 | -0.09% | -0.09% | 0.00% | N/A | N/A | 8 |
| 2018 | `l95|r0.50|dd0.30|g0.09|aU|pNONE|xT1_LEGAL_OPEN|k50` | 1.85% / 10.50% | 1.020 | -1.26% | -1.26% | -0.00% | N/A | N/A | 19 |
| 2019 | `l95|r0.50|dd0.40|g0.09|aU|pNONE|xT1_LEGAL_OPEN|k50` | 1.81% / 7.54% | 0.968 | 0.28% | 0.28% | -0.00% | N/A | N/A | 10 |
| 2020 | `l95|r0.50|dd0.40|g0.09|aU|pNONE|xT1_LEGAL_OPEN|k50` | 1.42% / 4.74% | 0.812 | 0.44% | 0.44% | 0.00% | N/A | N/A | 33 |
| 2021 | `l95|r0.80|dd0.40|g0.09|aU|pQ75|xT1_LEGAL_OPEN|k50` | 1.23% / 4.20% | 0.729 | -0.01% | -0.23% | 0.22% | 0.36% | -0.37% | 1 |

Stitched: total -0.65%, CAGR -0.13%, MaxDD -1.43%, Sharpe -0.204, Calmar -0.091, trades 71. Baseline total: -8.63%; excluding 2020: -1.08%.

Yearly returns: `{"2017": -0.0009223444603987385, "2018": -0.012580449816142592, "2019": 0.0028116104373290263, "2020": 0.004379505305650344, "2021": -9.687032117844385e-05}`. Ex-best-day -1.24%; ex-best-five-days -2.39%. 2017–2019 -1.07%; 2020 0.44%; 2021 -0.01%.

Baseline: total -8.63%, CAGR -1.78%, MaxDD -12.79%, Sharpe -0.543, Calmar -0.139, trades 253; yearly `{"2017": -0.015738203086471447, "2018": -0.06463480436059388, "2019": -0.042620857980050664, "2020": 0.0486068658982326, "2021": -0.011359296844977385}`.

Formation dates: `{"unique_dates": 47, "max_trades_one_date": 11, "top1_positive_pnl_share": 0.27341929564968004, "top5_positive_pnl_share": 0.641530089887688, "top1pct_positive_pnl_share": 0.27341929564968004}`. Reclaim dates: `{"unique_dates": 51, "max_trades_one_date": 12, "top1_positive_pnl_share": 0.3075090734604812, "top5_positive_pnl_share": 0.6142914689534563, "top1pct_positive_pnl_share": 0.3075090734604812}`.

Top-10 next-year neighborhoods: `{"2017": {"count": 10, "median_return": -0.0017052411201639028, "best_return": 0.0, "worst_return": -0.0075584096909796505, "fraction_profitable": 0.0, "returns": [-0.0009223444603987385, -0.002488137779929067, -0.006120484228110179, -0.0075584096909796505, 0.0, -0.0002538451612902337, -0.0009223444603987385, -0.0002538451612902337, -0.006120484228110179, -0.002488137779929067]}, "2018": {"count": 10, "median_return": -0.009319026517374707, "best_return": -0.0019324378931534492, "worst_return": -0.03136429367683258, "fraction_profitable": 0.0, "returns": [-0.012580449816142258, -0.010976395862879462, -0.012580449816142258, -0.010976395862879462, -0.006717590746471047, -0.007661657171869951, -0.0036691650991906855, -0.0019324378931534492, -0.03136429367683258, -0.007370153343993602]}, "2019": {"count": 10, "median_return": 0.00220925364506408, "best_return": 0.003916277925854805, "worst_return": -0.005126112348769585, "fraction_profitable": 0.6, "returns": [0.0028116104373292483, 0.0028116104373292483, 0.0034427306551185755, 0.0034427306551185755, -0.005126112348769585, -0.00398673467517241, -0.004930959000244206, -0.0037913578275975413, 0.0016068968527989114, 0.003916277925854805]}, "2020": {"count": 10, "median_return": 0.012794442312011878, "best_return": 0.030706835545594835, "worst_return": 0.0043795053056499, "fraction_profitable": 1.0, "returns": [0.0043795053056499, 0.0043795053056499, 0.011342237548049194, 0.012794442312011878, 0.030417830386165745, 0.029941517062227696, 0.011342237548049194, 0.012794442312011878, 0.030706835545594835, 0.0302303886282691]}, "2021": {"count": 10, "median_return": -9.687032117844385e-05, "best_return": 0.00025877930605511246, "worst_return": -0.006347884135768478, "fraction_profitable": 0.1, "returns": [-9.687032117844385e-05, -9.687032117844385e-05, -0.002271664564290732, 0.0, 0.0, 0.00025877930605511246, -0.006347884135768478, -9.687032117844385e-05, -9.687032117844385e-05, -0.002271664564290732]}}`.

Parameter stability: `{"panic": ["NONE", "NONE", "NONE", "NONE", "Q75"], "leader": [0.95, 0.95, 0.95, 0.95, 0.95], "runup": [0.8, 0.5, 0.5, 0.5, 0.8], "drawdown": [0.3, 0.3, 0.4, 0.4, 0.4], "gap": [0.09, 0.09, 0.09, 0.09, 0.09], "age": [-1, -1, -1, -1, -1], "q75": [0.026831036983321246, 0.01846486001074258, 0.018127458768545462, 0.014176632191338074, 0.012284568462314127], "q90": [0.22988275207237618, 0.10496107632115424, 0.07539657452817776, 0.04744112757062924, 0.0420373665480427]}`.

V4 Dryup diagnostic: `{"le_0_5": {"trades": 15, "pnl": -0.0018543618904464376, "mean_net_return": -0.006140906345172562, "win_rate": 0.5333333333333333}, "gt_0_5": {"trades": 56, "pnl": -0.0046268343192561335, "mean_net_return": -0.0040433692745938405, "win_rate": 0.5}, "missing": {"trades": 0, "pnl": 0.0, "mean_net_return": null, "win_rate": null}}`. ST diagnostic: `{"st": {"trades": 0, "pnl": 0.0, "mean_net_return": null, "win_rate": null}, "non_st": {"trades": 71, "pnl": -0.006481196209702571, "mean_net_return": -0.004486510909223148, "win_rate": 0.5070422535211268}}`. Board verdict: `NO_FORMATION_PANIC_INTERACTION_EDGE`.

## CHINEXT

| Test | Selected | Q75 / Q90 | Train Calmar | Full | No panic | Panic increment | Broad same panic | Structure increment | Trades |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2017 | `l90|r0.50|dd0.30|g0.09|a3|pNONE|xT1_LEGAL_OPEN|k20` | 14.91% / 50.07% | 1.073 | -0.64% | -0.64% | 0.00% | N/A | N/A | 4 |
| 2018 | BLOCKED | 13.02% / 48.22% | N/A | 0.00% | N/A | N/A | N/A | N/A | 0 |
| 2019 | `l90|r0.50|dd0.30|g0.09|a3|pNONE|xT1_LEGAL_OPEN|k20` | 8.11% / 30.30% | 0.609 | 0.02% | 0.02% | 0.00% | N/A | N/A | 10 |
| 2020 | `l90|r0.50|dd0.30|g0.09|a3|pNONE|xT1_LEGAL_OPEN|k20` | 4.82% / 26.05% | 0.506 | 4.43% | 4.43% | 0.00% | N/A | N/A | 39 |
| 2021 | `l95|r0.50|dd0.30|g0.09|a3|pQ90|xT1_LEGAL_OPEN|k50` | 4.41% / 26.31% | 0.668 | 0.00% | -0.58% | 0.58% | 0.00% | 0.00% | 0 |

Stitched: total 3.78%, CAGR 0.74%, MaxDD -1.33%, Sharpe 0.371, Calmar 0.557, trades 53. Baseline total: 0.64%; excluding 2020: -0.62%.

Yearly returns: `{"2017": -0.006419123097844648, "2018": 0.0, "2019": 0.00019722436250546593, "2020": 0.04426374723772164, "2021": 0.0}`. Ex-best-day -0.31%; ex-best-five-days -3.23%. 2017–2019 -0.62%; 2020 4.43%; 2021 0.00%.

Baseline: total 0.64%, CAGR 0.13%, MaxDD -3.20%, Sharpe 0.065, Calmar 0.040, trades 136; yearly `{"2017": -0.0090456580275462, "2018": -0.006544667028181794, "2019": -0.0028417016228783343, "2020": 0.051541722019565084, "2021": -0.025014543051597116}`.

Formation dates: `{"unique_dates": 26, "max_trades_one_date": 20, "top1_positive_pnl_share": 0.5505914937449147, "top5_positive_pnl_share": 0.8987219150770426, "top1pct_positive_pnl_share": 0.5505914937449147}`. Reclaim dates: `{"unique_dates": 27, "max_trades_one_date": 20, "top1_positive_pnl_share": 0.5371732410265682, "top5_positive_pnl_share": 0.87681951026872, "top1pct_positive_pnl_share": 0.5371732410265682}`.

Top-10 next-year neighborhoods: `{"2017": {"count": 10, "median_return": 0.0, "best_return": 0.0, "worst_return": -0.006419123097844648, "fraction_profitable": 0.0, "returns": [-0.006419123097844648, 0.0, -0.006419123097844648, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}, "2018": null, "2019": {"count": 10, "median_return": 9.786321704718937e-05, "best_return": 0.008124403982686212, "worst_return": -0.009252568083431778, "fraction_profitable": 0.6, "returns": [0.0001972243625052439, 0.0001972243625052439, 9.786321704718937e-05, -0.009252568083431778, -0.0037003086870565083, 9.786321704718937e-05, -0.009252568083431778, -0.0037003086870565083, 0.008124403982686212, 0.008124403982686212]}, "2020": {"count": 10, "median_return": 0.08136628092649767, "best_return": 0.11614095837533411, "worst_return": 0.017038016149349966, "fraction_profitable": 1.0, "returns": [0.044263747237721196, 0.041097472418349934, 0.01827345264749214, 0.017038016149349966, 0.11614095837533411, 0.1137623362410567, 0.11048744891883144, 0.11172581123798797, 0.10812087505016899, 0.054611686802826354]}, "2021": {"count": 10, "median_return": 0.0, "best_return": 0.0, "worst_return": 0.0, "fraction_profitable": 0.0, "returns": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}}`.

Parameter stability: `{"panic": ["NONE", "BLOCKED", "NONE", "NONE", "Q90"], "leader": [0.9, null, 0.9, 0.9, 0.95], "runup": [0.5, null, 0.5, 0.5, 0.5], "drawdown": [0.3, null, 0.3, 0.3, 0.3], "gap": [0.09, null, 0.09, 0.09, 0.09], "age": [3, null, 3, 3, 3], "q75": [0.14906985252729935, 0.13023788913468629, 0.08110655821462875, 0.04822555800537619, 0.04410443877379713], "q90": [0.5006914310237948, 0.48218414967416434, 0.30304878048780487, 0.26049265450861225, 0.26309542137512715]}`.

V4 Dryup diagnostic: `{"le_0_5": {"trades": 8, "pnl": -0.0014121747398232881, "mean_net_return": -0.0032685102270136046, "win_rate": 0.625}, "gt_0_5": {"trades": 45, "pnl": 0.03917729664355046, "mean_net_return": 0.017484798937258548, "win_rate": 0.6666666666666666}, "missing": {"trades": 0, "pnl": 0.0, "mean_net_return": null, "win_rate": null}}`. ST diagnostic: `{"st": {"trades": 0, "pnl": 0.0, "mean_net_return": null, "win_rate": null}, "non_st": {"trades": 53, "pnl": 0.037765121903727175, "mean_net_return": 0.014352223969066526, "win_rate": 0.660377358490566}}`. Board verdict: `NO_FORMATION_PANIC_INTERACTION_EDGE`.

## Fixed 50/50 combined portfolio

Total 1.56%, CAGR 0.31%, MaxDD -1.02%, Sharpe 0.268, Calmar 0.302; excluding 2020 -0.85%.

Yearly returns: `{"2017": -0.0036707337791217487, "2018": -0.006307576588420072, "2019": 0.0014997486428989237, "2020": 0.02436682251049116, "2021": -4.738246962820991e-05}`.

## Diagnostics

- Main panic sequence: `NONE → NONE → NONE → NONE → Q75`.
- ChiNext panic sequence: `NONE → BLOCKED → NONE → NONE → Q90`.
- Main formation→reclaim transition: `{"trades": 71, "successful_trades": 36, "median_formation_percentile": 0.6697247706422018, "median_reclaim_percentile": 0.5381944444444444, "median_gap_age": 0.0, "successful_median_formation_percentile": 0.9046203987730062, "successful_median_reclaim_percentile": 0.6064332751730737, "fraction_reclaim_percentile_below_formation": 0.22535211267605634, "successful_fraction_reclaim_percentile_below_formation": 0.2222222222222222}`.
- ChiNext formation→reclaim transition: `{"trades": 53, "successful_trades": 35, "median_formation_percentile": 0.8629032258064516, "median_reclaim_percentile": 0.49193548387096775, "median_gap_age": 0.0, "successful_median_formation_percentile": 0.9539473684210527, "successful_median_reclaim_percentile": 0.9539473684210527, "fraction_reclaim_percentile_below_formation": 0.1509433962264151, "successful_fraction_reclaim_percentile_below_formation": 0.05714285714285714}`.

## Hard audit

- `formation_panic_date_mismatch_count`: `0`
- `reclaim_date_panic_used_for_eligibility_count`: `0`
- `test_year_used_in_own_parameter_selection_count`: `0`
- `test_year_used_to_calibrate_own_formation_panic_count`: `0`
- `post_2021_outcome_read_count`: `0`
- `post_signal_feature_leakage_count`: `0`
- `cross_board_parameter_contamination_count`: `0`
- `cross_board_formation_panic_calibration_count`: `0`
- `gap_ids_with_more_than_one_first_reclaim`: `0`
- `post_first_reclaim_reuse_count`: `0`
- `strict_gap_condition_violation_count`: `0`
- `trigger_outside_strict_gap_admitted_count`: `0`
- `duplicate_position_entry_count`: `0`
- `max_concurrent_positions_violation_count`: `0`
- `negative_cash_or_leverage_violation_count`: `0`
- `validation_opened`: `False`
- `final_oos_opened`: `False`

## Decision

The corrected formation-time panic interaction does not establish a robust Development edge. Close this exact former-leader + deep-drawdown + strict-gap + first-reclaim stock-level strategy family. The next frontier is **MARKET PANIC → REPAIR TRANSITION TIMING**.
