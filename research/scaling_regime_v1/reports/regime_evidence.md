# 事前状态与增量缩放收益

下述叙述以 OGR／MCB independent 为明确数值参照；完整 CSV 覆盖四种结构，未重新选择 Top。2026 为截至 9 月 4 日的 YTD。金额差为各账户实际净值变化之差，包含此前累积资金和路径差异。

| state_family   | state                 | block                  |   independent_dates |   incremental_pnl |   incremental_return_sum |   pnl_ex_top5_events |    capital_days |
|:---------------|:----------------------|:-----------------------|--------------------:|------------------:|-------------------------:|---------------------:|----------------:|
| market_regime  | BEAR                  | CONFIRMATION           |                 192 |       240263.0586 |                   0.0236 |         -149148.0232 |  383182110.4685 |
| market_regime  | BEAR                  | DISCOVERY              |                 425 |       680251.0070 |                   0.1052 |           84297.7139 |  472649278.4107 |
| market_regime  | BEAR                  | ROLLFORWARD_DIAGNOSTIC |                 256 |     -1015127.2357 |                  -0.1079 |        -1629996.9673 |  435743253.0885 |
| market_regime  | BULL                  | CONFIRMATION           |                  97 |       -45616.8475 |                  -0.0068 |         -137801.7302 |   -7957016.2303 |
| market_regime  | BULL                  | DISCOVERY              |                 228 |      -243099.5856 |                  -0.0523 |         -435246.7235 |  -33434723.3830 |
| market_regime  | BULL                  | ROLLFORWARD_DIAGNOSTIC |                 175 |      -771013.6132 |                  -0.0960 |         -989258.2945 | -225168625.4105 |
| market_regime  | TRANSITION            | CONFIRMATION           |                 195 |       509217.7436 |                   0.0521 |          -85500.0715 |  208573593.9887 |
| market_regime  | TRANSITION            | DISCOVERY              |                 320 |       653757.1468 |                   0.0982 |          119841.6964 |  178766589.9973 |
| market_regime  | TRANSITION            | ROLLFORWARD_DIAGNOSTIC |                 218 |      -501620.4919 |                  -0.0585 |         -878451.4945 |   49939185.7195 |
| breadth_bucket | MAJORITY_POSITIVE_20D | CONFIRMATION           |                 205 |       110609.4349 |                   0.0043 |         -114952.8962 |   76753985.5746 |
| breadth_bucket | MAJORITY_POSITIVE_20D | DISCOVERY              |                 421 |       -23997.2280 |                  -0.0248 |         -347087.4136 |   11280409.2317 |
| breadth_bucket | MAJORITY_POSITIVE_20D | ROLLFORWARD_DIAGNOSTIC |                 311 |     -1472899.6427 |                  -0.1779 |        -1801294.7796 | -302722543.9335 |
| breadth_bucket | MINORITY_POSITIVE_20D | CONFIRMATION           |                 279 |       593254.5199 |                   0.0646 |          -87074.2417 |  507044702.6522 |
| breadth_bucket | MINORITY_POSITIVE_20D | DISCOVERY              |                 552 |      1114905.7961 |                   0.1759 |          337337.1034 |  606700735.7933 |
| breadth_bucket | MINORITY_POSITIVE_20D | ROLLFORWARD_DIAGNOSTIC |                 338 |      -814861.6981 |                  -0.0845 |        -1502421.1174 |  563236357.3311 |

## 信号日期与事件分布

| state_family   | state                 | block                  |   decisions |   independent_original_signal_dates |   root_events |   median_event_contribution |   mean_event_contribution |   positive_event_fraction |
|:---------------|:----------------------|:-----------------------|------------:|------------------------------------:|--------------:|----------------------------:|--------------------------:|--------------------------:|
| market_regime  | BEAR                  | CONFIRMATION           |         137 |                                  83 |           380 |                     31.1241 |                  632.2712 |                    0.5316 |
| market_regime  | BEAR                  | DISCOVERY              |         546 |                                 184 |           930 |                    -86.5289 |                  731.4527 |                    0.4022 |
| market_regime  | BEAR                  | ROLLFORWARD_DIAGNOSTIC |         265 |                                 126 |           573 |                      6.0255 |                -1771.6008 |                    0.5044 |
| market_regime  | BULL                  | CONFIRMATION           |          70 |                                  72 |           439 |                    308.7500 |                 -103.9108 |                    0.5923 |
| market_regime  | BULL                  | DISCOVERY              |         211 |                                 152 |          1124 |                   -200.4187 |                 -216.2808 |                    0.4413 |
| market_regime  | BULL                  | ROLLFORWARD_DIAGNOSTIC |         186 |                                 117 |           947 |                    -53.4528 |                 -814.1643 |                    0.4805 |
| market_regime  | TRANSITION            | CONFIRMATION           |         161 |                                 117 |           545 |                   -203.1131 |                  934.3445 |                    0.3578 |
| market_regime  | TRANSITION            | DISCOVERY              |         328 |                                 206 |          1177 |                    -50.4793 |                  555.4436 |                    0.4571 |
| market_regime  | TRANSITION            | ROLLFORWARD_DIAGNOSTIC |         225 |                                 154 |           975 |                   -221.7761 |                 -514.4826 |                    0.3733 |
| breadth_bucket | MAJORITY_POSITIVE_20D | CONFIRMATION           |         193 |                                 126 |           696 |                     25.1182 |                  158.9216 |                    0.5101 |
| breadth_bucket | MAJORITY_POSITIVE_20D | DISCOVERY              |         471 |                                 229 |          1538 |                   -196.4230 |                  -15.6029 |                    0.4148 |
| breadth_bucket | MAJORITY_POSITIVE_20D | ROLLFORWARD_DIAGNOSTIC |         377 |                                 174 |          1273 |                   -350.3905 |                -1157.0304 |                    0.4226 |
| breadth_bucket | MINORITY_POSITIVE_20D | CONFIRMATION           |         175 |                                  99 |           463 |                     -6.2447 |                 1281.3273 |                    0.4924 |
| breadth_bucket | MINORITY_POSITIVE_20D | DISCOVERY              |         614 |                                 201 |           970 |                    -72.0766 |                 1149.3874 |                    0.4258 |
| breadth_bucket | MINORITY_POSITIVE_20D | ROLLFORWARD_DIAGNOSTIC |         299 |                                 150 |           675 |                     42.4002 |                -1207.2025 |                    0.5215 |

原始信号日期按贡献根事件的实际决策时间统计，包含跨期延续的持仓信号；与每日盈亏观察日期分开报告。

## 留年与事件集中度

| gap   | mcb_mode    | target   | mechanic                | state_family   | state                 |   discovery_pnl |   confirmation_pnl |   diagnostic_pnl | all_blocks_unit_return_increment_positive   | all_leave_year_directions_positive   | both_historical_blocks_positive_ex_top5   | both_historical_blocks_positive_ex_best5_dates   | numerical_stability_gate   | qualification                         |
|:------|:------------|:---------|:------------------------|:---------------|:----------------------|----------------:|-------------------:|-----------------:|:--------------------------------------------|:-------------------------------------|:------------------------------------------|:-------------------------------------------------|:---------------------------|:--------------------------------------|
| OGR   | independent | G25      | FULL_BOOK_NORMALIZATION | market_regime  | BEAR                  |     680251.0070 |        240263.0586 |    -1015127.2357 | False                                       | False                                | False                                     | False                                            | FAIL                       | FAIL_STABILITY_OR_EVENT_CONCENTRATION |
| OGR   | independent | G25      | FULL_BOOK_NORMALIZATION | market_regime  | BULL                  |    -243099.5856 |        -45616.8475 |     -771013.6132 | False                                       | False                                | False                                     | False                                            | FAIL                       | FAIL_STABILITY_OR_EVENT_CONCENTRATION |
| OGR   | independent | G25      | FULL_BOOK_NORMALIZATION | market_regime  | TRANSITION            |     653757.1468 |        509217.7436 |     -501620.4919 | False                                       | True                                 | False                                     | False                                            | FAIL                       | FAIL_STABILITY_OR_EVENT_CONCENTRATION |
| OGR   | independent | G25      | FULL_BOOK_NORMALIZATION | breadth_bucket | MAJORITY_POSITIVE_20D |     -23997.2280 |        110609.4349 |    -1472899.6427 | False                                       | False                                | False                                     | False                                            | FAIL                       | FAIL_STABILITY_OR_EVENT_CONCENTRATION |
| OGR   | independent | G25      | FULL_BOOK_NORMALIZATION | breadth_bucket | MINORITY_POSITIVE_20D |    1114905.7961 |        593254.5199 |     -814861.6981 | False                                       | True                                 | False                                     | False                                            | FAIL                       | FAIL_STABILITY_OR_EVENT_CONCENTRATION |

状态只使用决策前已完成信息。波动率、流动性、账户回撤和 Demand 暴露只给连续相关性，不新增高低阈值。状态条件金额是实际 daily scaled−native 差额，每个交易日每个状态族只计一次；它不是一个尚未运行的状态路由账户收益。资金天数使用完成时点持仓并精确切分日历、状态和终止边界。incremental_return_sum 是每日收益率差的算术和，只作单位净值方向核查，不是状态子账户的复合收益率。

ROUTER_CANDIDATE_STATUS: NO_STABLE_SCALING_REGIME_ROUTER

两类一维状态共 20 个 G25 结构/状态检验；没有二维或迟滞救援调参。若未满足条件，不生成虚构 router_results.csv。
