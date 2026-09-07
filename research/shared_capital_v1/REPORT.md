# 五策略共享资金：V0.5 因果基线与输入闭合

TASK_STATUS = PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE

共同 P0 未通过，实际共享场景仍为 **0/48**。本次已经实际重建五策略所需父信号/事实和独立账户诊断；这不等于共同 P0，也不等于共享账户已经完成。没有生成堵塞场景的零收益表，没有 P1/P2/P3 收益结论。

## 已确认与修复

ATRDR 原始父信号的真实行情截断探针（三条 Bull/Fast/Slow 路径）及同重置条件旧过滤差额已保存于 atrdr_actual_prefix_probes.csv / atrdr_legacy_baseline_difference.csv。前段最后有效日差额为 +61.1152626，后段差额仅约 1.25e-8；这是控制比较，不是封存连续 NAV 的替代。

ATRDR Bull 和 slow Bear 在历史账户母体前依赖最终 COMPLETED；研究修正路径按已发生 entry 建立身份，保留未完成/后续失效的历史入场。微型真实执行路径的截断/延长回归已验证入场、意图、现金、持仓和 NAV 前缀不变；不能据此宣称整条历史链已闭合。

SMV6 原本可在缺开盘 mark 时使用当日未来 close，且开盘分钟 close 尚未完成。研究适配器改用已知 OPEN_BAR open，无合法开盘持仓 mark 时不提交该笔订单。冻结策略源码完全未改，历史前缀回放分别核对 730/242 个账户日、241/44 个事件。保持 LOCAL_END_TO_END_REPRODUCIBLE_PLATFORM_EQUIVALENCE_UNVERIFIED。

比较层现在拒绝 actual/golden 重复键、空键、行数/cardinality 不一致和缺少必需层；生产 reproduce 命令必需比较失败会非零退出，生成后不再以 FULL 作为验证结论。GENERATION_STATUS、COMPARISON_STATUS、CAUSAL_VALIDATION_STATUS、ACCOUNT_VALIDATION_STATUS 分列。冻结清单中仅 compare.py / reproduce.py 两个非经济基础设施源码改变，旧 SHA 与新 SHA 保存在 contracts/validation_repair_receipt.json；旧封存参考在 START_HEAD 和注册 baseline_root 中保留。

融资审计拒绝 NaN/inf、非法 NAV、重复日期和缺失账户方程；无独立交易日历时返回 UNKNOWN。物理账户核验每次成交/资金变动的有限值、现金、持仓数量及权益归因。当前接通五策略独立诊断账户，SMV6 原生回调的真实物理成交可回写状态，两段与本地修正基线 NAV 最大差约 1.4e-9；共同调度器尚未接通。

## 原生连续初始状态

用户已确认：按原生连续状态重建，缺失到账状态保持阻塞。连续探针实际结果：

```csv
strategy,period,boundary,native_origin,mode,status,first_blocker,last_valid_date,last_valid_nav,last_valid_cash,last_known_open_lots,funded_entries_before_block,boundary_nav,boundary_cash,boundary_holdings,qualification
ATRDR,2018_2021,2018-01-01,2014-01-01,NATIVE_CONTINUOUS,ACCOUNTING_BLOCKED,ACTIVE_COORDINATE_LINEAGE_CHANGE:2017-06-30:V29|BULL|V29B|20170623|600622.SH: native outcome abort is not an executable exit,2017-06-29,1529327.0603134474,994166.9567880213,19,667,,,,last known state is not a valid boundary snapshot after unresolved action
ATRDR,2022_2023,2022-01-01,2014-01-01,NATIVE_CONTINUOUS,ACCOUNTING_BLOCKED,ACTIVE_COORDINATE_LINEAGE_CHANGE:2017-06-30:V29|BULL|V29B|20170623|600622.SH: native outcome abort is not an executable exit,2017-06-29,1529327.0603134474,994166.9567880213,19,667,,,,last known state is not a valid boundary snapshot after unresolved action
MCB,2018_2021,2018-01-01,2014-01-01,NATIVE_CONTINUOUS,NATIVE_BOUNDARY_RECONSTRUCTED_REFERENCE_COMPARISON_PENDING,ACTIVE_COORDINATE_LINEAGE_CHANGE:2020-06-24:V72|V65|MEDIUM_PARTICIPATION|V53-20200617-603368.SH: native outcome abort is not an executable exit,2020-06-23,1551037.3619623156,484168.8529590373,39,655,1312987.896579233,1312987.896579233,{},last known state is not a valid boundary snapshot after unresolved action
MCB,2022_2023,2022-01-01,2014-01-01,NATIVE_CONTINUOUS,ACCOUNTING_BLOCKED,ACTIVE_COORDINATE_LINEAGE_CHANGE:2020-06-24:V72|V65|MEDIUM_PARTICIPATION|V53-20200617-603368.SH: native outcome abort is not an executable exit,2020-06-23,1551037.3619623156,484168.8529590373,39,655,,,,last known state is not a valid boundary snapshot after unresolved action
```

ATRDR 在 2017-06-30 持有 600622.SH 时即遇到转增 30% 而 share_credit_date 缺失，早于两个待验收区间；不能构造其 2018/2022 边界。MCB 2018 边界能够重建，但 2020-06-24 后续路径阻塞，2022 边界不可达。这两个区间的共同 P0 都不能用重置空仓替代。

## 空仓诊断中的账户阻塞

ATRDR 前段持有 600195.SH，2019-07-16 发生每 10 股转增 4 股；MCB 前段持有 603368.SH，2020-06-24 同类转增。注册 distributions 原表 share_credit_date 均为空、execution_timing_resolved=False、execution_unresolved_reason 包含 missing_share_credit_date。市场输入在对应日将 corporate_action_valid 设为 False，并改变 invalid_step_cum。不能删去此前入场，也不能把新复权坐标当作已经到账可卖股份，更不能临时新增提前卖出规则。本次保留真实持仓并明确停机；相应最终 NAV 是缺失值，不是零。证据见 active_coordinate_*_evidence.csv。

独立工程欠项仍存在：共同初始状态、跨价格单位的实际持仓转换、SMV6 共享成交回调、独立 P0 HOME_BUDGET 全检查点路径和完整调度器。后段股票原生账户虽对账通过，这些工程欠项仍阻止 2022–2023 的 24 个共同场景。本报告没有把工程欠项称为数据缺失。

## IFCGR 输入缺口已找到合法候选并完成父窗口核验

原配置路由 285347 行，止于 2022-01-01，这个事实仍成立。但沿既有 CY-065/CY-063 清单找到 CY-062 原始官方公告路由：149545 行，2022–2023 有 49967 行。新重建 OGR 后段 50 个父信号的发行人及 120 天窗口全部被注册来源覆盖；原分类器重跑为 50 kept / 0 rejected。前段 370 父信号为 362 kept / 8 rejected。这里的 0 rejected 是有事实来源支持的分类结果，与缺数据时默认为无风险完全不同。

IFCGR_2022_2023_DATA_STATUS = AVAILABLE_PIT_B_VERIFIED_PARENT_WINDOWS

保留 PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE。只读取 <=2023 的事实窗口；没有读取 accepted trades 来补机会，没有读取 post-2023 投资结果。来源审计、schema、时间范围、逐文件哈希和 50 个窗口见 ifcgr_data_coverage.csv / ifcgr_parent_window_coverage.csv / issuer_source_hashes.json。

## 独立账户实际结果，不能当成共同 P0

以下初始现金 100 万是冻结归一化研究计价，股票/Gap 为 NORMALIZED_RESEARCH_ACCOUNT，SMV6 为 LOCAL_PLATFORM_APPROXIMATION。没有声称乘以 100 万便得到实盘可执行账户。股票保留分板 50/50、原生 K/日容量/排序/费用；Gap 保留原生目标和退出。独立诊断采用 flat reset，仅为控制实验。用户已明确选择原生连续状态，缺失到账状态保持阻塞；单独的 contracts/initial_state_v05.json 覆盖旧初始化条款而保留旧政策文件字节。连续路径从 2014 年实际重放，证据见 native_initial_state_probe.csv；无法越过阻塞构造 2018/2022 边界现金、持仓或 HOME_BUDGET。

```csv
strategy,period,funded_count,final_nav,max_abs_nav_diff,status
ATRDR,2018_2021,397,,8.381903171539307e-09,ACCOUNTING_BLOCKED
ATRDR,2022_2023,441,1161075.2379726074,1.3271346688270569e-08,NATIVE_ACCOUNT_RECONCILED
MCB,2018_2021,325,,6.752088665962219e-09,ACCOUNTING_BLOCKED
MCB,2022_2023,206,1077980.036148977,7.566995918750763e-09,NATIVE_ACCOUNT_RECONCILED
OGR,2018_2021,255,1110169.4677651073,3.492459654808044e-09,PASS
OGR,2022_2023,45,1007359.4066154052,2.91038304567337e-09,PASS
IFCGR,2018_2021,248,1105177.2081431411,3.841705620288849e-09,PASS
IFCGR,2022_2023,45,1007359.4066154052,2.91038304567337e-09,PASS
SMV6,2018_2021,77,1260255.9780863535,1.3969838619232178e-09,NATIVE_PHYSICAL_ACCOUNT_RECONCILED
SMV6,2022_2023,32,1103922.0770485734,6.984919309616089e-10,NATIVE_PHYSICAL_ACCOUNT_RECONCILED
```

SMV6 相同 reset 条件下的旧执行控制末值为 1242160.7330112131 / 1107900.8681746258，修正后为 1260255.978086352 / 1103922.0770485739，差额 +18095.245075139 / -3978.791126052。旧执行控制不是跨段连续封存 NAV 的替代目标；原始 LEGACY_SEALED_REFERENCE 仍为注册 baseline_root，CAUSAL_CORRECTED_BASELINE 单独保存，不向旧数值强行拟合。

OGR/IFCGR 独立固定账户资本拒绝数为 0；状态/容量拒绝仍按原生规则记录。这不能推出共同账户没有资金分割，也不能把闲置现金全部称为可共享空间。共同 STRUCTURAL_IDLE、SEGMENTATION_IDLE、GLOBAL_DEMAND_CONFLICT、共享交易盈亏、基础权利饥饿及风险可接受性均 NOT_ESTIMABLE。

P1 仍仅诊断，MaxDD_shared <= MaxDD_P0 + 0.50pp 的规则和原政策 hash 完全未改。没有最佳政策、资金角色或 Gap 优劣判断。

## 验证与重跑

聚焦及现有单元测试：{'passed': 79, 'failed': 0, 'scope': 'focused tests plus existing unit suite, not full scenario acceptance'}。33 项需求覆盖逐项区分原语测试、独立账户验证、整链待验证和未接通工程；不以测试数量冒充全验收。哈希和独立诊断重跑结果见 input_hash_verification.csv / final_input_hash_verification.csv / deterministic_baseline_rerun.csv / smv6_physical_deterministic_rerun.csv / frozen_hash_verification.csv。本次最终复核 339 个已消费输入哈希一致；股票/Gap 8 条 NAV 重跑一致，SMV6 10 份物理账户层重跑一致。没有推送。

精确命令及退出码见 REPRODUCTION_COMMANDS.md；完整闭合命令在共同门未通过时返回 2。所有生成文件在本工作区，缓存和日志不提交，紧凑证据及真实机会流提交。
