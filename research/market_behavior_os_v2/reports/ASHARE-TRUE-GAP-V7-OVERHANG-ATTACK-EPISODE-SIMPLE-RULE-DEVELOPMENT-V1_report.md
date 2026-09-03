# ASHARE-TRUE-GAP-V7-OVERHANG-ATTACK-EPISODE-SIMPLE-RULE-DEVELOPMENT-V1

## Outcome

**Verdict: V7_NO_SIMPLE_EDGE**

The scientific verdict uses only purged expanding 2017-H1 through 2021-H2 outer tests. The 2022–2023 section is explicitly post-observation and did not alter semantics, thresholds, selection, or verdict.

## Frozen identities

- V6 semantic source: `2705011d21792acfea34c6fe07819aa1a9e6dd91247bc27e66616749cc3ee162`
- V7 spec: `1206bab1d21d81315a97046e535981183ebfcf002ed721a7c707dbd710045ae1`
- Feature contract: `b5dfa9962352252e74ba54f1602f4ad2c2309c4b8ec422733b8b8b2c4641c683`
- Attack contract: `e02edd577b89e7344c70fb46f972f0d4b71b8b577904fcee34ce6f578d45ad5f`
- Rule space: `3da4275a98fb7ffd72c88c8c13f754098705571e36b3a18f64d7def2ccbfdcfa`
- Exit space: `01da840bef2c03827039424f4ed7a62478e73464b602e33ca8ff6800870b656d`

## V6 to V7 reconciliation

- Frozen gaps / prior L0 rows / completed policy rows: 629 / 633 / 632.
- CORE / BOUNDARY source rows: 593 / 40; unique gaps: 590 / 39.
- Predecessor K10 completed trades / capacity skips: 509 / 110.
- Gaps with repeated predecessor timestamps: 4; separate mapped attacks: 4.
- Prior rows inside ATTACK_1 / ATTACK_2 / outside: 469 / 100 / 64.
- Eventual U only after original reset: 692.
- Prior entry timestamps more than 1 / 3 / 5 sessions after causal first contact: 261 / 181 / 147.
- Corporate-action fail-closed paths — events / attacks / entry keys / policy rows: 4 / 1 / 14 / 264.
- Board split MAIN / ChiNext: 351 / 282; duplicate event-date entries: 0.
- Top-10 formation-date / re-entry-date concentration: 29.86% / 14.38%.
- Frozen predecessor entry mix: `{
  "ABS_1P0+C4_HOLD15": 242,
  "ABS_2P0+C4_HOLD15": 125,
  "GAP_50+C3_HOLD5": 113,
  "GAP_50+C4_HOLD15": 106,
  "GAP_50+C5_SECOND_RECLAIM": 47
}`.

## Development lanes — combined K10

| Procedure | Lane | Signals | Attacks | Entries | Trades | Mean | Median | Win | U hit | Clean10 | Failed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEPLOYMENT_GATED_WF | L5_FULL_SIMPLE_RULE | 64 | 64 | 64 | 64 | -2.39% | 1.69% | 59.38% | 46.88% | 45.31% | 29.69% |
| DEPLOYMENT_GATED_WF | L6_ONE_RETRY_INCREMENT | 4 | 4 | 4 | 4 | -6.97% | -7.42% | 25.00% | 25.00% | 25.00% | 25.00% |
| FORCED_CHOICE_WF | L0_ATTACK_BASELINE | 1436 | 1436 | 1436 | 861 | -0.84% | 0.90% | 57.26% | 32.17% | 31.48% | 35.31% |
| FORCED_CHOICE_WF | L1_LOW_OVERHANG | 394 | 394 | 394 | 355 | -1.69% | 0.82% | 56.34% | 36.34% | 34.93% | 32.39% |
| FORCED_CHOICE_WF | L2_LOW_OVERHANG_ENVIRONMENT | 358 | 358 | 358 | 319 | -1.82% | 0.72% | 54.86% | 33.54% | 33.23% | 33.54% |
| FORCED_CHOICE_WF | L3_ATTACK_ACCEPTANCE | 80 | 80 | 80 | 80 | -3.01% | 1.56% | 56.25% | 43.75% | 42.50% | 35.00% |
| FORCED_CHOICE_WF | L4_FAILURE_EXIT | 1439 | 1439 | 1439 | 904 | -0.93% | 0.76% | 56.19% | 31.75% | 31.08% | 35.51% |
| FORCED_CHOICE_WF | L5_FULL_SIMPLE_RULE | 89 | 89 | 89 | 89 | -2.87% | 1.58% | 57.30% | 43.82% | 42.70% | 33.71% |
| FORCED_CHOICE_WF | L6_ONE_RETRY_INCREMENT | 9 | 9 | 9 | 9 | -2.57% | 1.35% | 55.56% | 44.44% | 44.44% | 22.22% |

| Procedure | Lane | Severe8 | Severe10 | CVaR5 | Mean hold | Median hold | CAGR | MaxDD | Sharpe | Calmar |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEPLOYMENT_GATED_WF | L5_FULL_SIMPLE_RULE | 28.12% | 23.44% | -26.73% | 11.1875 | 13.5000 | -1.55% | -7.94% | -0.6176 | -0.1949 |
| DEPLOYMENT_GATED_WF | L6_ONE_RETRY_INCREMENT | 50.00% | 50.00% | -15.68% | 15.5000 | 20.0000 | -0.28% | -1.38% | -0.5029 | -0.2015 |
| FORCED_CHOICE_WF | L0_ATTACK_BASELINE | 25.20% | 20.33% | -24.35% | 14.2811 | 20.0000 | -7.11% | -38.88% | -0.3904 | -0.1828 |
| FORCED_CHOICE_WF | L1_LOW_OVERHANG | 27.61% | 22.54% | -25.96% | 13.5887 | 20.0000 | -6.15% | -30.18% | -0.6830 | -0.2037 |
| FORCED_CHOICE_WF | L2_LOW_OVERHANG_ENVIRONMENT | 28.21% | 22.88% | -26.40% | 14.0972 | 20.0000 | -5.91% | -29.41% | -0.6881 | -0.2011 |
| FORCED_CHOICE_WF | L3_ATTACK_ACCEPTANCE | 31.25% | 23.75% | -26.73% | 12.1000 | 20.0000 | -2.44% | -12.04% | -0.8105 | -0.2029 |
| FORCED_CHOICE_WF | L4_FAILURE_EXIT | 23.34% | 18.81% | -23.80% | 12.7898 | 20.0000 | -7.78% | -40.00% | -0.4467 | -0.1945 |
| FORCED_CHOICE_WF | L5_FULL_SIMPLE_RULE | 30.34% | 23.60% | -25.70% | 11.9438 | 20.0000 | -2.59% | -12.70% | -0.8185 | -0.2039 |
| FORCED_CHOICE_WF | L6_ONE_RETRY_INCREMENT | 22.22% | 22.22% | -15.68% | 12.2222 | 20.0000 | -0.23% | -1.44% | -0.3058 | -0.1599 |

## Primary L5 board breakdown — K10

| Procedure | Board | Trades | Mean | Median | Win | Severe10 | CAGR | MaxDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| DEPLOYMENT_GATED_WF | CHINEXT | 41 | -2.73% | 1.69% | 58.54% | 24.39% | -2.27% | -12.05% |
| DEPLOYMENT_GATED_WF | COMBINED | 64 | -2.39% | 1.69% | 59.38% | 23.44% | -1.55% | -7.94% |
| DEPLOYMENT_GATED_WF | MAIN | 23 | -1.79% | 2.26% | 60.87% | 21.74% | -0.85% | -7.60% |
| FORCED_CHOICE_WF | CHINEXT | 45 | -2.99% | 1.69% | 57.78% | 24.44% | -2.72% | -13.34% |
| FORCED_CHOICE_WF | COMBINED | 89 | -2.87% | 1.58% | 57.30% | 23.60% | -2.59% | -12.70% |
| FORCED_CHOICE_WF | MAIN | 44 | -2.75% | 1.22% | 56.82% | 22.73% | -2.46% | -14.99% |

## Primary L5 K sensitivity — combined

| Procedure | K | Trades | CAGR | MaxDD | Sharpe | Utilization | Capacity skips | Worst day | Top security share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DEPLOYMENT_GATED_WF | 5 | 64 | -3.12% | -15.47% | -0.6139 | 5.61% | 0 | -3.52% | 3.12% |
| DEPLOYMENT_GATED_WF | 10 | 64 | -1.55% | -7.94% | -0.6176 | 2.81% | 0 | -1.75% | 3.12% |
| DEPLOYMENT_GATED_WF | 20 | 64 | -0.77% | -4.02% | -0.6193 | 1.41% | 0 | -0.87% | 3.12% |
| FORCED_CHOICE_WF | 5 | 89 | -5.23% | -24.26% | -0.8095 | 8.52% | 0 | -3.57% | 2.25% |
| FORCED_CHOICE_WF | 10 | 89 | -2.59% | -12.70% | -0.8185 | 4.21% | 0 | -1.76% | 2.25% |
| FORCED_CHOICE_WF | 20 | 89 | -1.29% | -6.49% | -0.8227 | 2.10% | 0 | -0.87% | 2.25% |

## Primary L5 chronology

| Half-year | Forced-choice L5 | Deployment-gated L5 |
|---|---:|---:|
| 2017H1 | -1.10% | 0.04% |
| 2017H2 | -0.89% | -0.96% |
| 2018H1 | -0.82% | -0.84% |
| 2018H2 | -5.50% | -2.39% |
| 2019H1 | -0.05% | 0.51% |
| 2019H2 | -0.63% | -0.03% |
| 2020H1 | -1.13% | -1.39% |
| 2020H2 | 0.87% | 0.85% |
| 2021H1 | -1.86% | -1.81% |
| 2021H2 | -1.76% | -1.69% |

| Year | Forced-choice L5 | Deployment-gated L5 |
|---|---:|---:|
| 2017 | -1.98% | -0.92% |
| 2018 | -6.27% | -3.20% |
| 2019 | -0.69% | 0.48% |
| 2020 | -0.27% | -0.55% |
| 2021 | -3.59% | -3.47% |

## Frozen outer selections

| Fold | Board | Overhang | Environment | Entry | RNT | Exit | H | Retry | Gate |
|---|---|---|---|---|---:|---|---:|---|---|
| 2017H1 | CHINEXT | VACUUM_Q50_RATIO_Q50 | NONE | Z25+HOLD15_80 | 2.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | CASH |
| 2017H1 | MAIN | RATIO_Q30 | NONE | Z0+RETEST_RECLAIM | 2.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2017H2 | CHINEXT | VACUUM_Q50_RATIO_Q50 | NONE | Z25+HOLD15_80 | 1.50% | X0_NO_FAILURE_EXIT | 20 | R1_ONE_RETRY | DEPLOY |
| 2017H2 | MAIN | VACUUM_Q70 | NONE | Z50+HOLD15_80 | 2.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | CASH |
| 2018H1 | CHINEXT | INSIDE_Q30 | NONE | Z25+CLOSE | 2.00% | X4_NO_PROGRESS_D3 | 20 | R1_ONE_RETRY | DEPLOY |
| 2018H1 | MAIN | RATIO_Q30 | NONE | Z25+HOLD15_80 | 2.00% | X0_NO_FAILURE_EXIT | 20 | R1_ONE_RETRY | DEPLOY |
| 2018H2 | CHINEXT | RATIO_Q30 | BREADTH_REPAIR | Z25+CLOSE | 2.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2018H2 | MAIN | LGBM_DISTILLED_LEAF | NONE | Z0+HOLD5_80 | 2.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | CASH |
| 2019H1 | CHINEXT | RATIO_Q30 | BREADTH_REPAIR | Z25+HOLD15_80 | 1.50% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2019H1 | MAIN | RATIO_Q30 | APPROACH_QUALITY | Z50+HOLD5_80 | 2.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2019H2 | CHINEXT | RATIO_Q30 | BREADTH_REPAIR | Z25+CLOSE | 2.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2019H2 | MAIN | TREE_SINGLE_LEAF | NONE | Z25+RETEST_RECLAIM | 1.00% | X0_NO_FAILURE_EXIT | 20 | R1_ONE_RETRY | CASH |
| 2020H1 | CHINEXT | RATIO_Q30 | NONE | Z25+HOLD15_80 | 2.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2020H1 | MAIN | TREE_SINGLE_LEAF | NONE | Z25+RETEST_RECLAIM | 1.00% | X0_NO_FAILURE_EXIT | 20 | R1_ONE_RETRY | DEPLOY |
| 2020H2 | CHINEXT | RATIO_Q30 | BREADTH_REPAIR | Z25+HOLD15_80 | 1.50% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2020H2 | MAIN | LGBM_DISTILLED_LEAF | BREADTH_REPAIR | Z25+CLOSE | 1.50% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | CASH |
| 2021H1 | CHINEXT | RATIO_Q30 | BREADTH_REPAIR | Z0+HOLD15_80 | 1.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2021H1 | MAIN | TREE_SINGLE_LEAF | NONE | Z0+HOLD15_60 | 1.50% | X0_NO_FAILURE_EXIT | 10 | R1_ONE_RETRY | DEPLOY |
| 2021H2 | CHINEXT | RATIO_Q30 | BREADTH_REPAIR | Z0+HOLD15_80 | 1.00% | X0_NO_FAILURE_EXIT | 20 | R0_NO_RETRY | DEPLOY |
| 2021H2 | MAIN | TREE_SINGLE_LEAF | NONE | Z25+HOLD15_60 | 1.50% | X0_NO_FAILURE_EXIT | 5 | R0_NO_RETRY | DEPLOY |

## Direct and matched evidence

- Vacuum-score outer-test quintile mean net returns: `{
  "Q1": 0.008066670956255165,
  "Q2": 0.0017243703121983583,
  "Q3": -0.005845315299346522,
  "Q4": -0.00905753067780332,
  "Q5": -0.014182244055877664
}`.
- Five preregistered outer-test two-dimensional surface summaries: `[
  {
    "best_fixed_cell": {
      "bucket_x": 3,
      "bucket_y": 3,
      "mean_net_return": 0.1365356041208709,
      "observations": 15
    },
    "cells": 9,
    "positive_cells": 5,
    "variable_x": "breadth_recovery",
    "variable_y": "stock_minus_industry_return_10d",
    "worst_fixed_cell": {
      "bucket_x": 1,
      "bucket_y": 3,
      "mean_net_return": -0.021875785415431864,
      "observations": 383
    }
  },
  {
    "best_fixed_cell": {
      "bucket_x": 1,
      "bucket_y": 2,
      "mean_net_return": 0.01570487352164121,
      "observations": 34
    },
    "cells": 9,
    "positive_cells": 5,
    "variable_x": "overhang_support_ratio",
    "variable_y": "acceptance_ratio_l_15",
    "worst_fixed_cell": {
      "bucket_x": 1,
      "bucket_y": 1,
      "mean_net_return": -0.01944553894058411,
      "observations": 83
    }
  },
  {
    "best_fixed_cell": {
      "bucket_x": 3,
      "bucket_y": 3,
      "mean_net_return": -0.0036305842018504327,
      "observations": 1436
    },
    "cells": 1,
    "positive_cells": 0,
    "variable_x": "prior_attack_count",
    "variable_y": "failed_l_test_count",
    "worst_fixed_cell": {
      "bucket_x": 3,
      "bucket_y": 3,
      "mean_net_return": -0.0036305842018504327,
      "observations": 1436
    }
  },
  {
    "best_fixed_cell": {
      "bucket_x": 3,
      "bucket_y": 1,
      "mean_net_return": 0.016615480630644188,
      "observations": 7
    },
    "cells": 9,
    "positive_cells": 3,
    "variable_x": "remaining_net_target_at_entry",
    "variable_y": "structural_stop_distance",
    "worst_fixed_cell": {
      "bucket_x": 2,
      "bucket_y": 3,
      "mean_net_return": -0.02811591553809858,
      "observations": 67
    }
  },
  {
    "best_fixed_cell": {
      "bucket_x": 1,
      "bucket_y": 3,
      "mean_net_return": 0.00925510586120663,
      "observations": 188
    },
    "cells": 9,
    "positive_cells": 3,
    "variable_x": "vacuum_score",
    "variable_y": "progress_per_turnover",
    "worst_fixed_cell": {
      "bucket_x": 3,
      "bucket_y": 2,
      "mean_net_return": -0.017937385821267,
      "observations": 158
    }
  }
]`. Best/worst cells are descriptive only and were not promoted into rules.
- Matched/FWL summaries: `[
  {
    "board": "CHINEXT",
    "date_equal_mean": -0.16774691358024693,
    "mean_fwl_effect": -0.22846142338027586,
    "outcome": "attack_success",
    "positive_folds": 5
  },
  {
    "board": "CHINEXT",
    "date_equal_mean": -0.05689418558173539,
    "mean_fwl_effect": 0.07721155949295914,
    "outcome": "net_return",
    "positive_folds": 2
  },
  {
    "board": "CHINEXT",
    "date_equal_mean": 0.07962962962962963,
    "mean_fwl_effect": -0.12776168532521498,
    "outcome": "severe_loss10",
    "positive_folds": 5
  },
  {
    "board": "COMBINED",
    "date_equal_mean": -0.015230414446480342,
    "mean_fwl_effect": -0.02876541217275542,
    "outcome": "attack_success",
    "positive_folds": 6
  },
  {
    "board": "COMBINED",
    "date_equal_mean": -0.01827954698541526,
    "mean_fwl_effect": -0.031007042695994535,
    "outcome": "net_return",
    "positive_folds": 4
  },
  {
    "board": "COMBINED",
    "date_equal_mean": 0.07015939411465727,
    "mean_fwl_effect": 0.09767610748572539,
    "outcome": "severe_loss10",
    "positive_folds": 6
  },
  {
    "board": "MAIN",
    "date_equal_mean": -0.06405752791832914,
    "mean_fwl_effect": -0.13881396455370185,
    "outcome": "attack_success",
    "positive_folds": 5
  },
  {
    "board": "MAIN",
    "date_equal_mean": -0.023398847558377015,
    "mean_fwl_effect": -0.025499157342535172,
    "outcome": "net_return",
    "positive_folds": 5
  },
  {
    "board": "MAIN",
    "date_equal_mean": 0.14924268513771555,
    "mean_fwl_effect": 0.14846641936590044,
    "outcome": "severe_loss10",
    "positive_folds": 8
  }
]`.
- Model ceiling summaries: `[
  {
    "mean_auc": 0.5839749277312892,
    "mean_prediction_std": 0.1338939534214727,
    "mean_top30_utility": -0.038719702798603615,
    "median_auc": 0.5667714828883534,
    "method": "LIGHTGBM_CEILING"
  },
  {
    "mean_auc": 0.49976711900119375,
    "mean_prediction_std": 0.15118477211367087,
    "mean_top30_utility": -0.054374670171496754,
    "median_auc": 0.5009057971014492,
    "method": "MONOTONE_SCORECARD"
  },
  {
    "mean_auc": 0.5009584302979858,
    "mean_prediction_std": 0.12942565427795658,
    "mean_top30_utility": -0.045275785929721125,
    "median_auc": 0.5,
    "method": "RULEFIT_LITE"
  },
  {
    "mean_auc": 0.575817872052421,
    "mean_prediction_std": 0.15914002261339244,
    "mean_top30_utility": -0.04417325876336869,
    "median_auc": 0.5955587985328324,
    "method": "SHALLOW_DECISION_TREE"
  },
  {
    "mean_auc": 0.5860636964961594,
    "mean_prediction_std": 0.11969355627380165,
    "mean_top30_utility": -0.0209025033377088,
    "median_auc": 0.5935116029979929,
    "method": "SPARSE_LOGISTIC"
  }
]`. Raw model scores were never deployable.

- Full TRAIN/outer-test univariate and surface metrics are in `/Volumes/quant/CY_quant_research/ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1/direct_analysis.parquet`; full matched results are in `/Volumes/quant/CY_quant_research/ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1/matched_analysis.parquet`.

## Stability adjudication

- Checks: `{
  "at_least_100_trades": false,
  "both_boards_nonnegative": false,
  "near_positive_ex_best_five": false,
  "no_catastrophic_full_year": true,
  "positive_attack_date_equal": false,
  "positive_ex_best_day": false,
  "positive_half_years_at_least_6": false,
  "positive_mean": false,
  "positive_median": true,
  "positive_years_at_least_4": false,
  "severe10_materially_improved": false
}`.
- Attack-date-equal mean: -2.34%.
- Boundary baseline diagnostic: `{
  "chinext": {
    "clean_success_10": 0.2777777777777778,
    "cvar5": -0.22686494243087588,
    "economic_utility": -0.03749831990257358,
    "failed_attack": 0.3148148148148148,
    "mean_net_return": 0.007874668583601597,
    "median_net_return": 0.008133326232487081,
    "retention": 1.0,
    "severe_loss10": 0.18518518518518517,
    "severe_loss8": 0.2222222222222222,
    "trade_path_calmar": 0.17193124969498644,
    "trades": 54,
    "true_win_rate": 0.6111111111111112,
    "u_hit": 0.2962962962962963
  },
  "combined": {
    "clean_success_10": 0.3553299492385787,
    "cvar5": -0.2613228969930622,
    "economic_utility": -0.05666880859259835,
    "failed_attack": 0.2639593908629442,
    "mean_net_return": -0.004404229193985909,
    "median_net_return": 0.011148166354653766,
    "retention": 1.0,
    "severe_loss10": 0.17258883248730963,
    "severe_loss8": 0.20812182741116753,
    "trade_path_calmar": -0.09267008171424483,
    "trades": 197,
    "true_win_rate": 0.6548223350253807,
    "u_hit": 0.3604060913705584
  },
  "main": {
    "clean_success_10": 0.38461538461538464,
    "cvar5": -0.2658422805161672,
    "economic_utility": -0.06220947187057407,
    "failed_attack": 0.24475524475524477,
    "mean_net_return": -0.00904101576734063,
    "median_net_return": 0.011185248550518612,
    "retention": 1.0,
    "severe_loss10": 0.16783216783216784,
    "severe_loss8": 0.20279720279720279,
    "trade_path_calmar": -0.14258677936441522,
    "trades": 143,
    "true_win_rate": 0.6713286713286714,
    "u_hit": 0.38461538461538464
  }
}`.

## High-overhang diagnostic (not mixed into Vacuum Repair)

- Summary: `{
  "attacks": 562,
  "mean_current_attack_success": 0.6779359430604982,
  "mean_eventual_u_after_failed": 0.2277580071174377,
  "mean_failed_attack": 0.31316725978647686,
  "mean_turnover_to_attack_end": 0.07518988336901998
}`.
- ATTACK_1 / ATTACK_2 current-success: 67.41% / 76.00%.
- Separate absorption-breakout lane justified: NO.

## 2022–2023 POST-OBSERVATION ROBUSTNESS DIAGNOSTIC

| Period | Trades | Mean | Median | Win | U hit | Clean10 | Severe10 | Return | MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 3 | 29.60% | 11.56% | 66.67% | 0.00% | 0.00% | 33.33% | 3.56% | -1.44% |
| 2022-2023 | 4 | 19.15% | 0.49% | 50.00% | 0.00% | 0.00% | 50.00% | 3.70% | -2.15% |
| 2023 | 1 | -12.20% | -12.20% | 0.00% | 0.00% | 0.00% | 100.00% | 0.14% | -0.80% |

| Period | Board | Signals | Trades | Mean | Median | Win | Severe10 | Return |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2022 | CHINEXT | 0 | 0 | — | — | — | — | 0.00% |
| 2022 | COMBINED | 3 | 3 | 29.60% | 11.56% | 66.67% | 33.33% | 3.56% |
| 2022 | MAIN | 3 | 3 | 29.60% | 11.56% | 66.67% | 33.33% | 7.12% |
| 2022-2023 | CHINEXT | 0 | 0 | — | — | — | — | 0.00% |
| 2022-2023 | COMBINED | 4 | 4 | 19.15% | 0.49% | 50.00% | 50.00% | 3.70% |
| 2022-2023 | MAIN | 4 | 4 | 19.15% | 0.49% | 50.00% | 50.00% | 7.41% |
| 2023 | CHINEXT | 0 | 0 | — | — | — | — | 0.00% |
| 2023 | COMBINED | 1 | 1 | -12.20% | -12.20% | 0.00% | 100.00% | 0.14% |
| 2023 | MAIN | 1 | 1 | -12.20% | -12.20% | 0.00% | 100.00% | 0.27% |

The frozen final policy selected R0_NO_RETRY, so ATTACK_2 contribution is exactly zero in this post-observation diagnostic.

These numbers are not scientific evidence and were not used in the verdict.

## Representative chart audit

- 89 charts; index: `/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830/research/market_behavior_os_v2/artifacts/ASHARE-TRUE-GAP-V7-OVERHANG-ATTACK-EPISODE-SIMPLE-RULE-DEVELOPMENT-V1_chart_index.csv`; external images/PDFs: `/Volumes/quant/CY_quant_research/ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1/representative_charts`.

## Audit

```json
{
  "ATTACK_STARTED_BEFORE_PRIOR_ATTACK_END_COUNT": 0,
  "CORPORATE_ACTION_COORDINATE_VIOLATION_COUNT": 0,
  "CROSS_SLEEVE_TRANSFER_COUNT": 0,
  "DUPLICATE_POSITION_COUNT": 0,
  "ENTRY_USES_FUTURE_BAR_COUNT": 0,
  "EXIT_ADDED_AFTER_OUTCOME_OPEN_COUNT": 0,
  "FEATURE_ADDED_AFTER_OUTCOME_OPEN_COUNT": 0,
  "FEATURE_USES_POST_DECISION_INFORMATION_COUNT": 0,
  "LATER_SUCCESS_CREDITED_TO_EARLIER_ATTACK_COUNT": 0,
  "MAX_K_VIOLATION_COUNT": 0,
  "NEGATIVE_CASH_OR_LEVERAGE_COUNT": 0,
  "POST_2021_SCIENTIFIC_EVIDENCE_ACCEPTED": "NO",
  "PURGE_EMBARGO_VIOLATION_COUNT": 0,
  "REPOSITORY_2024_PLUS_DATA_OPENED": "NO",
  "RULE_ADDED_AFTER_OUTCOME_OPEN_COUNT": 0,
  "SAME_GAP_SPLIT_ACROSS_FOLDS_COUNT": 0,
  "SEMANTIC_CHANGE_AFTER_OUTCOME_OPEN_COUNT": 0,
  "STOP_EXECUTED_AT_IMPOSSIBLE_PRICE_COUNT": 0,
  "T1_SAME_DAY_EXIT_COUNT": 0,
  "TEST_HALF_USED_IN_OWN_SELECTION_COUNT": 0,
  "V6_EVENT_IDENTITY_CHANGED_COUNT": 0
}
```

## Final interpretation

- Positive causal simple strategy created: NO.
- Stable enough for one sealed 2024+ challenge: NO.
- 2024+ repository data opened: NO.
- Next action: do not open 2024+; retain useful representations or close this primary lane according to the verdict.
