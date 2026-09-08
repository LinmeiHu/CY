# Full Book 与 Entry Only

下述叙述以 OGR／MCB independent 为明确数值参照；完整 CSV 覆盖四种结构，未重新选择 Top。2026 为截至 9 月 4 日的 YTD。金额差为各账户实际净值变化之差，包含此前累积资金和路径差异。

|   year | target   |   annual_return_full_book |   annual_return_entry_only |   MaxDD_full_book |   MaxDD_entry_only |   full_book_minus_entry_only_pnl | interpretation                    |
|-------:|:---------|--------------------------:|---------------------------:|------------------:|-------------------:|---------------------------------:|:----------------------------------|
|   2022 | G25      |                    0.0775 |                     0.0699 |            0.0440 |             0.0900 |                      123795.8943 | SAME_ANNUAL_PNL_DIRECTION         |
|   2023 | G25      |                    0.0881 |                     0.0645 |            0.0362 |             0.0293 |                      268963.5320 | SAME_ANNUAL_PNL_DIRECTION         |
|   2024 | G25      |                   -0.0161 |                     0.1817 |            0.0913 |             0.0979 |                    -1615085.7888 | MECHANISM_DEPENDENT_REGIME_EFFECT |
|   2025 | G25      |                    0.1105 |                     0.1551 |            0.0323 |             0.0298 |                     -460254.5359 | SAME_ANNUAL_PNL_DIRECTION         |
|   2026 | G25      |                   -0.0205 |                     0.0361 |            0.1180 |             0.0909 |                     -605603.7538 | MECHANISM_DEPENDENT_REGIME_EFFECT |
|   2022 | G100     |                    0.2997 |                     0.2484 |            0.1738 |             0.3272 |                     4549604.4528 | SAME_ANNUAL_PNL_DIRECTION         |
|   2023 | G100     |                    0.3447 |                     0.2741 |            0.1399 |             0.1154 |                     7224298.3324 | SAME_ANNUAL_PNL_DIRECTION         |
|   2024 | G100     |                   -0.0961 |                     0.7719 |            0.3533 |             0.3870 |                   -22275784.4789 | MECHANISM_DEPENDENT_REGIME_EFFECT |
|   2025 | G100     |                    0.4910 |                     0.2310 |            0.1191 |             0.1309 |                    11661289.6153 | SAME_ANNUAL_PNL_DIRECTION         |
|   2026 | G100     |                   -0.0983 |                     0.2567 |            0.3897 |             0.2876 |                   -19136761.7570 | MECHANISM_DEPENDENT_REGIME_EFFECT |

共同输入是原始 precapital 信号、Native 参考请求、报价及初始状态；实际持仓路径会影响 ACTIVE_SYMBOL/MAX_K/native_failures，因此准入后的 intents 不要求机械相等，共同事件的信号时间、价格、参考请求金额和经济定义已逐项核对。Full Book 的实际持仓再分配会改变后续现金、仓位及复利路径，年度对照体现整条机制路径的差异。不能把差值解读为只在当年启停一次再平衡的因果效应。Entry Only 的年内符号改善也不自动满足风险或容量要求。逐笔前向结果区分实际买入批次和减仓价格反事实；重叠窗口不相加。
