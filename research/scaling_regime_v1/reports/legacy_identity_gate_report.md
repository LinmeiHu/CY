# CAPITAL SCALING REGIME ATTRIBUTION V1 — 身份门禁拒绝

TASK_STATUS: BLOCKED_ROLLFORWARD_IDENTITY_MISMATCH。经济归因、容量和路由资格研究未完成。不是“已完成全部研究”，也不是“没有稳定状态路由”的统计结论。

用户任务第 3 节明确规定："If any portfolio shown in the roll-forward differs from the frozen parent scaling rule: stop economic interpretation and report exact mismatch." 本次五个 Top 组合均触发此门禁，故在状态与收益联结前停止。未新增规则、阈值、策略、退出或融资，也未开启新的封存验证。

## 证据链与结论

父分支 research/five-strategy-capital-scaling-v1，父 HEAD `77128f86ff40673102f60860100d8504d801e2d2`。实际滚动图位于父工作区未提交的 `research/capital_scaling_v1/reports/continuous_rollforward_v2/研究报告.md`。其生产脚本和物理账户均已找到，不能说“源码不存在”。原文件路径、快照与哈希见 `evidence/source_inventory.json` 和 `input_manifest.json`。

- #1: OGR / confirmation_tag / G100。身份门禁 FAIL。
- #2: IFCGR / confirmation_tag / G100。身份门禁 FAIL。
- #3: OGR / independent / G100。身份门禁 FAIL。
- #4: IFCGR / independent / G100。身份门禁 FAIL。
- #5: OGR / independent / G75。身份门禁 FAIL。

五组都保留 2018–2021 CAGR 排名及对应 Gap、MCB 模式、gross 目标，使用同一 Full Book 引擎。直接比对各自 973 个历史日期的 NAV/cash/gross，均在绝对误差 1e-6 元内通过。冻结源文件和成本身份一致。共同截止日为 2026-09-04，2026 是 YTD。这些通过项不覆盖 2022 以后的初始化与运行时输入谓词。

### 1. 已证实：2022 边界协议改变

父经济契约的 `initial_states` 要求股票采用原生连续边界状态，SMV6 按每个父区间执行原生回调初始化。父 2022 年 SMV6 从 1,000,000 元、空仓以及重新初始化的 context 开始。

滚动生产器 `run_continuous_combinations.py` 仅调用一次 `replay(..., '2018-01-01', END, ...)`，沿用 2018 年初状态连续运行至 2026 年。它在 2022 年没有重新初始化 SMV6，缩放资金参照也来自这套连续 Native 的 timeline/home_before_funding。

以下为只读账户身份比对，`SMV6_initial_cash` 对比父 2022 初始现金与滚动 2021 年末现金；其余字段取 2022-01-04。单位元：

|Gap|字段|父账户|滚动账户|差额|
|---|---|---:|---:|---:|
|OGR|SMV6_nav|1,019,454.741403|1,260,255.978086|240,801.236683|
|OGR|SMV6_exposure|519,933.400000|0.000000|-519,933.400000|
|OGR|SMV6_initial_cash|1,000,000.000000|1,260,255.978086|260,255.978086|
|IFCGR|SMV6_nav|1,019,454.741403|1,260,255.978086|240,801.236683|
|IFCGR|SMV6_exposure|519,933.400000|0.000000|-519,933.400000|
|IFCGR|SMV6_initial_cash|1,000,000.000000|1,260,255.978086|260,255.978086|

父 SMV6 当日实际持仓约 519,933.40 元，滚动 Native 为零；因此差异包含回调状态和持仓路径，并非只把资金单位等比例改大。两种 Gap 结构都出现这一差异，且五个 Top 的缩放生产器均使用相应连续 Native 资金参照。

连续运行可以是合理的另一个实验，历史原生区间初始化也不应被错误恢复成“每年强制清仓”。本审计不宣称连续账户本身经济上错误，更没有计算该差异究竟解释多少 2024/2026 损失。这里证实的是它不等于本次指定的父边界协议，不能静默合并两类结果。

股票请求对照另有 6 行：OGR/IFCGR 两个独立 Native 账户的 ATRDR、MCB、Gap 在父 2022–2023 全部请求身份及金额仍对齐，最大金额差低于 1e-6 元。不能把 SMV6 问题扩大为“所有原生信号或股票定仓都变了”。详见 `native_request_comparison.csv`。

### 2. 已证实谓词替换；效果等价性未证实

冻结 `mcb.build_v53` 需要 `d.industry_snapshot_id IS NOT NULL`。滚动 `build_rollforward_inputs.py:mcb_screens` 通过 `corrected_function` 改成 `d.causal_industry IS NOT NULL`。已读取 Parquet schema 验证：滚动合并面板有 causal_industry，没有 industry_snapshot_id。

行业名称存在不证明对应时点行业快照有可验证身份。两谓词在逻辑上不同；2018–2023 信号集合相等也不能证明新数据中的资格条件等价。这里没有断言替换已经改变某一笔后续信号或造成某个收益差，结论是原资格谓词改变且新窗口等价性未证。恢复身份需要逐时快照映射或明确冻结新的数据资格协议，不能靠相同股票总数或相同 Python 文件哈希消除这个差异。

## 停止范围

本次未运行年度损益分解、逐策略/路线/证券归因、Full Book 后续收益归因、Entry Only 重放、状态分桶收益、leave-year、router 或 G25 容量。`router_results.csv` 不生成；其他尚未计算的经济 CSV 也不写虚构数字或空壳 PASS。

`NO_STABLE_SCALING_REGIME_ROUTER` 与 `REGIME_EFFECT_EXISTS_BUT_NOT_ACTIONABLE` 都需要经济证据，当前均不能下结论。ROUTER_CANDIDATE_STATUS 为 NOT_EVALUATED_IDENTITY_GATE；G25 容量为 NOT_RUN_IDENTITY_GATE，既不是容量通过也不是已证明缺少成交额数据。

## 16 个问题的处理

1. 2024 亏损主要是 Native alpha 弱化还是缩放放大？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

2. 2026 YTD 亏损主要来自哪一项？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

3. 2025 为何产生大量缩放收益？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

4. 2024 哪个策略和路线主导损失？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

5. 2026 哪个策略和路线主导损失？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

6. 2025 哪个策略和路线主导利润？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

7. 各年 Full Book 调仓帮助还是伤害？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

8. 2024/2026 是否类似 2018–2023 已有坏状态？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

9. 2025 是否类似以前的好状态？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

10. 哪些事前状态解释增量缩放 P&L？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

11. 发现期与确认期方向是否稳定？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

12. 是否存在简单 Native/G25 路由器？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

13. 目前为什么不能给出路由决策？

父契约与滚动图的初始化协议不同，MCB 运行时资格谓词也被替换；尚未进入状态归因，不能判定有或没有稳定路由器。

14. 当前规模的 G25 容量是否可信？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

15. 哪个策略构成 G25 主要容量负担？

NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。

16. 下一步研究优先级是什么？

先确定并冻结连续账户的权威协议，补足 MCB 行业快照证据，再重建全部 Native/G25 及必要机制对照。之后才是归因、容量与路由资格；本次没有新 alpha 依据。

## 冻结、测试与复现

状态契约在任何状态条件收益分析之前冻结；本次身份审计已看过父年度报告，因此后续只能声称事后诊断，不能称新封存验证。契约 SHA256：`9e3465f8c2a6234767353ee33486f4c8357bfc3d7b4081ba1a9830c8acf2dda4`。

当前 766 个输入/来源文件全部哈希通过，覆盖 413 条父登记输入、136 个父缓存及 26 个冻结策略身份文件；多个角色可能指向同一文件，不能把角色数量相加当独立文件数。对未提交滚动来源只绑定观察到的字节；这不追认其为封存生产者。所有受 Git 跟踪的修改仅位于本工作树的 `research/scaling_regime_v1`；父回归测试另使用 Git 已忽略的 `research/shared_capital_v1/cache` 只读来源软链接。

测试结果见 `output/test_results.json`；确定性复跑见 `output/determinism.csv`。测试通过表示门禁能正确拒绝不一致账户，不表示被拒绝的经济研究通过。`requirement_test_coverage.csv` 明确列出 42 个任务章节与 18 个测试要求中哪些未运行，避免用身份测试冒充 P&L/容量测试。

复跑命令：`PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.scaling_regime_v1.audit`。身份拒绝预期返回 2；返回 2 不是执行故障或测试失败。报告入口：`PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.scaling_regime_v1.build_report`。精确步骤见 `REPRODUCTION_COMMANDS.md`。
