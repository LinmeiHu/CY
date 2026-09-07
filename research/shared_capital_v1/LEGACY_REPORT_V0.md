# 五策略共享资金 V1：执行前阻塞证据

TASK_STATUS = PARTIAL_COMPLETE

当前交付是冻结合同、可执行原始输入审计和经过测试的政策算术；历史共享账户尚未实现。历史回放完成数为 **0/48**（每段 24 个）。没有 P0 对账通过记录，不能解释共享资金收益。

## 已证实的首个外部数据阻塞

配置中的 IFCGR 原始公告路由表共 285347 行；可用时间从 2013-08-23 17:33:05 到 2022-01-01 00:00:00。
恰好处于 2022-01-01 边界的记录为 218 行；此后至 2023 年末记录为 0 行。
这不证明 2022–2023 没有风险公告，而是所给原始事实覆盖不足。不能将空事实匹配默认为发行人过滤通过。

源码也存在对应限制：OGR 信号母体与 V27 限定 2017–2021，V28/V28R1/V28R2 读取 2018–2021 分区；IFCGR 查询明确要求 causal_available_at < 2022-01-01。精确源码行见 output/source_boundary_evidence.csv。
现有 exit-risk 的 2022–2023 IFCGR 分支读取配置项 ifcgr_cy065_trades（fixed_trades.parquet）；该表没有在本任务中用作机会源。其是否完整覆盖未获资机会未被证明。
OGR 的 replay_portfolio 虽支持后续 account_start/account_end，但这只扩展账户窗口，不能扩展上游信号与事实覆盖。

## 独立的未完成工程

2018–2021 不受上述后段数据缺口直接阻塞，但尚未完成独立初始化的 P0、五个原生策略机会适配器、实际持仓回调、单一物理账户与虚拟份额核算及历史回放。
这里没有把这些工程欠项称为数据缺失，也没有把政策函数单测称为历史回放成功。恢复后应先完成 P0 对账，再推进该段场景。

## 已冻结的资本语义

四个活跃策略各 100 万，总额 400 万。股票原生账户归一化资金可线性缩放，保留 MAIN/CHINEXT 内部初始 50/50 和分数原生份额；SMV6 原生为 100 万、100 股整手。
这是一套原生执行语义的研究计价，尚未证明分数股票份额对应交易所可执行持仓。股票每侧 0.002 复合费用；SMV6 佣金 0.0002、每侧滑点 0.0008、50% 分钟量限制。所有退出为 NATIVE_ONLY。
HOME_BUDGET 仅取独立 P0；共享盈亏不进入其递归。政策哈希在任何收益回放之前冻结。

## 十二项研究结论的当前证据状态

1. STRUCTURAL_IDLE：NOT_ESTIMABLE，缺少完整原生未获资机会审计。
2. SEGMENTATION_IDLE：NOT_ESTIMABLE，不能由持仓低利用率推断。
3. 新增获资机会数：NOT_ESTIMABLE；未运行，不记为零。
4. 共享交易盈亏：NOT_ESTIMABLE。
5. P1 收益是否仅来自更高暴露：NOT_ESTIMABLE。
6. P2 Demand 拥挤控制：仅政策上限算术已测试，历史效果 NOT_ESTIMABLE。
7. P3 尾部风险/效率：状态机已测试，历史 frontier NOT_ESTIMABLE。
8. MCB 资本角色：EVIDENCE_INSUFFICIENT。
9. Gap 选择：EVIDENCE_INSUFFICIENT。
10. 合格共享政策：EVIDENCE_INSUFFICIENT，不能据此得出共享政策无效。
11. BASE_ENTITLEMENT_SHORTFALL：NOT_ESTIMABLE。
12. 最差回撤归因：NOT_ESTIMABLE。

两段的 CAGR、MaxDD、CVaR、平均暴露、获资率、capital-days、共享交易数/盈亏及相对 P0 变化均未计算；没有伪造零值或空结果表。scenario_run_status.csv 是执行状态清单，**不是 scenario_segment_results.csv 的替代品**。

## 继续执行所需

需要覆盖 2022–2023 决策前 120 天窗口的可追溯 IFCGR 原始公告路由、对应 SSE/SZSE 标题与 PIT-B 覆盖清单；并需要能够在本仓库研究目录内调用的完整 Gap 后段机会生成入口。
允许研究目录适配原生函数并不自动解决缺失公告历史；恢复后必须验证机会总体及 P0，再执行原定 48 个段场景。不得使用已接受交易补齐。

冻结源码/config/manifests/original_sources 字节在本次执行前后核对；已实际读取的独立原始文件进行前后 SHA256 核对。未读取的大型目录未声明全量哈希通过。
测试结果与具体覆盖范围见 output/focused_test_results.json（若已生成）。没有生产资金配置更改，没有 push；不把局部实现提交为已完成研究。
