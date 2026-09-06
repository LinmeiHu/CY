# 五策略源码恢复与逐层复现报告（2026-09-06）

## 结论

本轮不是审计计划，已经完成源码导出、历史源码寻回、实际特征/候选/信号/成交/账户/日净值计算和逐层对账。任务总状态为 **PARTIAL_COMPLETE**：五个策略的登记源码都已找到且关键入口哈希匹配；从可用冻结中间层到成交和净值的五条路线均已实际重放；但 OGR、IFCGR、MCB 和 ATRDR 的若干更早父链没有全部从基础数据重新生产，SMV6 也没有取得原生 SuperMind 回测等价性，因此不能宣称“五条路线均从基础数据完全闭合”。

旧账本只用于逐字段、逐值和哈希对账。所有新输出都写入：

`/Volumes/quant/CY_quant_research/five_strategy_reproduction_v1`

既有冻结合同、封存目录和旧输出没有被改写。

## 本地 HEAD 与源码恢复

- 本轮开始 HEAD：`a740489df7022f2caeec19d7fd61cd4b18900f63`。
- 分支：`codex/five-strategy-integration-20260906`。
- 没有 reset、checkout 回退或覆盖此前未 push 工作。
- 按恢复包原命令运行 `recover_sources.py`，导出 6 个历史源码快照，共导出 12,844 个文件条目。
- 导出器返回 `IDENTITY_CHECKS_INCOMPLETE`，原因不是源码缺失，而是 ATRDR 的身份记录在声明的 `c12a7f...` 提交中尚不存在；同一入口源码字节已在相关历史、本地工作树和后续提交中找到。
- 五个登记入口/策略源码哈希全部匹配，详见 `inputs_manifest.json` 和 `SOURCE_MANIFEST.md`。

## 五策略逐层状态

|策略|源码/哈希|基础或父链|候选/信号|成交|持仓/现金/日净值|总状态|
|---|---|---|---|---|---|---|
|OGR|PASS|FAIL：V28R1 及更早父链未重跑|PASS：397 父候选附加特征，保留 370|PASS：355 完整 outcome，255 接受|PASS：无负现金/杠杆，净值逐值一致|REPRODUCIBLE_FROM_FROZEN_INTERMEDIATE|
|IFCGR|PASS|FAIL：仍依赖冻结 OGR 父候选；PIT-B|PASS：CY-063 Stage-A 内存确定性验证，选择 186|PASS：170 outcome，168 接受|PASS：3393 日净值行，物理哈希与登记旧结果一致|REPRODUCIBLE_FROM_FROZEN_INTERMEDIATE|
|MCB|PASS|FAIL：V65/V64/V53 生产链未重跑|PASS：2383 V65 候选中确认 1904|PASS：1021 接受|PASS：2397 日净值行，无负现金，净值逐值一致|REPRODUCIBLE_FROM_FROZEN_INTERMEDIATE|
|ATRDR|PASS|PARTIAL：Bull 从基础 PIT 日线；Fast/Slow Bear 从 V27 冻结中间层|Bull PASS：4361；Bear FAIL（父链）|PASS：6379 联合 outcome，2898 接受|PASS：3080 日净值行，无负现金，净值逐值一致|PARTIAL_ROUTE_CLOSURE|
|SMV6|PASS|PASS：QMT 日线与关键分钟线重放；原生平台等价性未验证|PASS：779 事件|PASS：150 买入、150 卖出，期末空仓|影子账本哈希一致；新增现金语义现金非负|SHADOW_EXACT_AND_LOCAL_CASH_REPLAY_COMPLETE|

以上 `PASS` 的精确定义和未闭合项分别保存在 `status/*.json`、`source_chain.csv` 和 `first_differences.csv`；没有把“从冻结中间层可复现”升级成“全父链可复现”。

## 第一处差异

- **OGR**：冻结结果登记的 registry SHA 为 `d53eea...`，在 refs、reflog、相关 worktree 和未提交文件中未找到该字节；找到的 CY-033 合法本地登记来自 `c5e3ec...`，registry SHA 为 `29e0c4...`。CY-033 manifest 与所用分区均通过哈希核验，后续 370 信号、255 接受成交和净值一致，但登记输入字节身份不能报 PASS。
- **IFCGR**：当前集成工作树的旧 validator 在进入 CY-065 检查前就拒绝当前 registry。转到入口源码哈希完全相同、validator/registry 配套的 `c5e3ec...` 历史工作树后，outer-freeze 验证通过；未重复运行一次性封存 Stage-B CLI。
- **MCB**：第一处未重建层为 V65 候选相对 V64/V53/基础输入的生产；V72 从 V65 候选起的选择、成交、账户和净值均已重放。
- **ATRDR**：身份记录在声明的 `c12a7f...` 不存在，首次出现在 `30de1d650a968cd6859eb2c7621bab4b731977aa`；策略入口本身哈希匹配。数据路线第一处缺口是 V27 Fast/Slow Bear，尤其 Slow Bear 的 supply mother。
- **SMV6**：100 股整手现金语义相对旧分数份额影子账本的首个单位净值差异在 2013-05-22：旧值 `0.9984101748807632`，新值 `0.9984106275917066`。首次受现金约束的买单在 2020-06-19，`159901.SZ` 请求 104800 股、成交 77100 股。

## SMV6 现金约束结果

冻结回调影子重放产生 779 个事件，事件 Parquet SHA-256 为 `00237162cfe7d829c6af9010cc20c5d584facd136fb5a29d7c2fc62b23ae4781`，与旧输出完全相同。由新事件重新生成的影子日净值 SHA-256 为 `2ca5153bd035d46dd8d7f727eafafbf4077a50a6c03420d4e2c54ddedefc9475`，同样完全相同；它忠实复现了旧语义的 31 个负现金日、最低现金权重 -5.1782% 和最高总暴露 105.1782%。

新增 `replay_smv6_cash_constrained.py` 没有修改冻结策略，只替换本地订单/账户语义：100 股整手、现金上限、减仓先于加仓、失败退出保留状态并重试。零费率运行结果：

- 初始现金：1,000,000 元；期末净值：5,214,760.5086 元，单位净值 5.2147605086。
- 最低现金：16.4086 元；最高总暴露率：99.9995279%；期末持仓为空。
- 事件类型计数与影子回放核心事件一致。
- 这是 `LOCAL_SEMANTICS_REPLAY`，不是原生 SuperMind 等价性证明；手续费参数默认为 0，本轮结果也固定为 0。

## 数据与执行约束

- 策略均保持原冻结 decision/availability 语义；未知关键 lineage 仍然 fail closed。
- 没有允许信号 bar 内成交；T+1、交易状态、涨跌停、公司行为和坐标 lineage 的原检查未放宽。
- 组合重放的负现金、杠杆、同 bar 成交等审计项均为 0；SMV6 旧影子账本的负现金仅作为被复现的旧语义缺陷展示，新现金语义未继承它。
- 旧版嵌套 Parquet 中有文件不能被 PyArrow 19 直接读取，使用 DuckDB 1.5.2 做只读兼容解析/对账。时间戳 us/ns 差异在逻辑比较前规范化，没有放宽数值容差。

## 测试与交付边界

聚焦测试覆盖现金不足拒单、部分成交、2→3 标的调仓的减仓先行、失败卖出状态保留与次日重试，共 2 项。可重跑命令见 `REPRODUCTION_COMMANDS.md`。

真正的源码交付 ZIP 会直接包含恢复出的 `.py` 文件，而不是只包含路径或审计表；快照归属与压缩包哈希见 `SOURCE_MANIFEST.md`。本报告的 `PARTIAL_COMPLETE` 是对父链与原生平台边界的保守结论，不影响已实际完成的后续分层重放证据。
