# 连续滚动回测 V2

本次输出位于 `/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2`；发布图表和指标位于本项目 `reports/continuous_rollforward_v2` 与 `output/continuous_rollforward_v2`。

组合截止 2026-09-04，完整股票状态面板的最后日期。SMV6 独立连续账户及两指数源截止 2026-09-07。所有策略均重新扫描到各自输入截止日；最后产生信号的日期另行记录，不用信号日期代替数据覆盖日期。

## 复算顺序

从项目根目录运行，设置 `PYTHONPATH=.:src`，使用已安装 pandas、DuckDB、NumPy、Matplotlib 的 Python。

1. Windows/QMT 日线和关键分钟数据通过原 `export_v6_from_qmt.py` 导出到本项目 `qmt_delta`；股票补充分钟和两指数由 `export_rollforward_qmt.py` 按 `stock_minute_request.json` 导出到 `qmt_stock_delta`。这些脚本只读取/下载行情。
2. `build_rollforward_inputs.py --stage daily`：验证历史/后续原始面板重叠与原 3,725 个股票标的，生成独立日线。
3. `correct_rollforward_facts.py`：按官方公告修正 002759.SZ 的 ST 起始日和价格限制，重建受影响坐标；原登记输入不修改。
4. `build_rollforward_inputs.py --stage atrdr`、`--stage mcb`：重建信号。
5. 同一脚本依次运行 `--stage atrdr-entries`、`--stage mcb-entries`、`--stage atrdr-account`、`--stage mcb-account`。账户阶段补全两笔官方公司行动日期，保留原登记经济条款。
6. 同一脚本 `--stage ogr-candidates`：扫描原始日线候选。`build_gap_rollforward.py --stage signals` 补齐年度分钟分区后运行 VAP 和原 V28R2 门槛；`--stage outcomes` 重建进入与退出记录。
7. `build_ifcgr_rollforward.py`：验证所有新父信号在官方公告捕获窗口内，重做原 V2 分类和 120 日否决。
8. `build_smv6_rollforward.py`：验证新旧价位重叠，延长原 ETF 数据和可执行性记录，运行连续原始回调。
9. `run_continuous_combinations.py --gap OGR` 与 `--gap IFCGR`：从原验证的 2018 年初状态运行两个原生连续组合，保存资金需求与资金基准。没有在 2022 年或 2024 年重置。
10. `build_rollforward_quotes.py`：生成资金缩放所需的稀疏真实行情。当前补充股票集共 73 只，含近期潜在持仓、未完成原始进入和 OGR 分钟历史需求。
11. `run_continuous_combinations.py` 的五组参数：`--gap OGR --target G100 --mode confirmation_tag`；`--gap IFCGR --target G100 --mode confirmation_tag`；`--gap OGR --target G100 --mode independent`；`--gap IFCGR --target G100 --mode independent`；`--gap OGR --target G75 --mode independent`。
12. `export_continuous_top5.py`：要求五套完整账户全部存在并通过门槛，核对原 2018–2021 年历史前缀，然后导出图表及 2022 年以后年度指标。

行情补齐需在对应信号/成交/报价阶段之前完成；不要使用旧的拼接收益导出器。`--stage all` 不是本次带官方事实修正的完整复算入口，按上面的依赖顺序执行。

## 验证

`PYTHONPATH=.:src:research/capital_scaling_v1/tools python -m unittest research/capital_scaling_v1/tools/test_rollforward_reporting.py`

此外输出保留原生和资金缩放账户历史前缀对账、完整交易日期与现金/持仓约束检查、原股票池内 OGR 信号身份对账、分钟/日线对照，以及官方事实 PDF 的 SHA256。账户是研究执行账户；IFCGR 保持 PIT-B 等级，SMV6 保持本地执行平台边界。
