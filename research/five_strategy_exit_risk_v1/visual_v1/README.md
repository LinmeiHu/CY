# 20260907_visual_v1_01

先读[风险与现金复用结论](RISK_REPORT.md)，再读[视觉发现结论](VISUAL_REPORT.md)。[反例复核](risk_counterexample_review.md)说明留下的保护缺口；[运行状态](RUN_STATE.md)记录实际命令与边界。

本目录是父V2研究的增量，复用其代码、同版机会、合法执行状态及账户基线，没有另建策略平台。父V2的71个研究产物及冻结代码/配置保持原哈希；外接盘父数据也保留。大型新产物位于：

`/Volumes/quant/CY_quant_research/five_strategy_exit_risk_v1/20260907_visual_v1_01`

## 可执行复跑

从当前仓库根目录运行，需已挂载`/Volumes/quant`以及父V2清单中的本地依赖。依赖为现有Python环境的pandas、NumPy、DuckDB、scikit-learn、matplotlib、Pillow和pytest；没有新增下载。

```sh
PYTHONPATH=src /opt/anaconda3/bin/python3 -m pytest -q tests/unit research/five_strategy_exit_risk_v1/test_v2.py research/five_strategy_exit_risk_v1/visual_v1/test_visual.py research/five_strategy_exit_risk_v1/visual_v1/test_risk_review.py
/opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/visual_v1/quantify.py
/opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/visual_v1/risk_review.py
/opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/visual_v1/risk_finish.py --summary-only
/opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/visual_v1/deliver.py
```

账户脚本先验证可复用引擎产物与当前完整源机会一致，再复算共同日历指标、资金分解和无融资审计。`--resume`只用于继续同一规格的已校验中断运行。收益统一按实际买卖现金和公司行动入账计算；净值仅在完全空仓后延伸现金到共同终点，不填补持仓期间的缺失值。

图像与历史观察的再现需区别：`packets.py render`可从已封存payload重画图；`galleries.py`可重画发现段解剖图；`error_analysis.py`和`--complete`重画冻结模型误差图；`risk_finish.py`重画已定简单政策反例。**这些命令不能复现一个“首次未知结果”的人类/模型观察过程。** 实际首次观察记录与揭晓顺序由CSV、审计日志和冻结哈希保存。不要再次运行`prepare`或`reveal`覆盖封存案例，不要以重跑观察冒充新的盲验证。

## 主要文件

- `visual_exposure_manifest.csv`：图像暴露、未来/结果可见性、实际查看时间及哈希。
- `visual_case_manifest.csv`：匿名案例、完整路径与只读错误/反例条目、固定尺度裁剪统计。
- `visual_motif_hypotheses.csv`、`visual_feature_representations.csv`：结构化观察、支持与反例、最多1–3个计算表示。
- `visual_hypothesis_freeze.json`：看新后段个案之前的假说、代码和暴露记录冻结。
- `visual_admission.csv`、`visual_incremental_information.csv`：视觉增量信息检验；不能作为简单止损的必要验收门槛。
- `risk_preference_contract.json`、`risk_account_selection.csv`、`risk_candidates.json`：用户风险目标、发现段代表选取、最终研究候选及隔离方案。
- `risk_event_screen.csv`、`risk_account_comparison.csv`、`risk_account_frontier.csv`：事件网格、完整账户成本与风险前沿。
- `risk_cash_reuse_decomposition.csv`、`risk_funding_reason_summary.csv`：现金/名额复用、数量变化及真实新增/取消交易。
- `risk_no_financing_audit.csv`：20组账户、40个板块资金分支逐事件审计。
- `completion_manifest.json`：依赖不变性、测试、交付文件与外接盘哈希索引。

新产物的读取范围不超过2023年末。OGR/IFCGR两段独立初始化，ATRDR/MCB连续账户的后段承接前段状态。SMV6保持既有实际回调执行；IFCGR继承OGR，不作为另一份独立证据。

本轮没有修改冻结生产规则、增加实盘授权、构造新入场或共享资金池，也没有开启新的post-2023验证。ATRDR生产完成过滤的已证实缺陷继续隔离，其候选不能进入无条件shortlist。
