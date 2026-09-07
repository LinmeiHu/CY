# 统一调度与账户 V0.6

stock_p0 (ATRDR/MCB)、gap_p0 (OGR/IFCGR)、smv6_physical 均已调用 shared_account.scheduler.run_streams。流产生原生检查点，回调执行时读取实际资金/持仓并提交原生意图，不使用已接受交易作为生产入口。stock/gap 的 stream_only 与 SMV6 callback_stream 可绑定同一个 PhysicalAccount，common_p0_v06 提供四个 P0 启动入口。

按 timestamp → phase → strategy → identity 稳定调度。phase 为边界、公司行动、准备、已触发退出、SMV6 原生开盘回调、其他入场、信号、收盘。股票开盘 09:30/原生目标收盘 15:00，Gap 保留原始 minute bar_end_time，SMV6 保留 before_trading、09:30、14:57 信号及 15:00 尾卖。SMV6 原生开盘 callback 内有先卖后买及成员重置排序，为保留此资金反馈将其作为不可拆的原生批次；P0 下不跨袖融资。此安排未完成跨策略全退出/全入场阶段的共享政策验收，不能据此开放 P1/P2/P3。

真实股票/Gap适配器的四袖合成夹具与单独 SMV6 全段回放分别验证接线。公司行动只实现显式转换的 RECORD_DATE、ACCOUNTING_EFFECTIVE_DATE、SHARE_ARRIVAL_DATE、TRADABLE_DATE，记录日期没有自动变成到账日期。原持仓卖出后，已确认待到账权利保留独立 lot；arrival 后仍可不可卖；tradable 转换才允许出售。该引擎只接受外部逐时点明确证据，600622 的空日期没有接入合成规则。

账户对实际 physical positions 与 virtual lots 分别计算数量和 marked NAV；pending quantity 单独核对；P&L 按已实现及剩余成本独立核验。数量容差 1e-8，NAV/现金/P&L 容差 1e-6。拒绝负现金、非法数量、NaN/inf、缺失/重复交易日；P0 保留各袖现金及 home right，单袖不能借其他袖现金。继承持仓的区间 P&L 以边界市值起算，原始成本另存，不影响原生退出。

仍未闭合的工程：股票是 native coordinate units，Gap 是 raw price/shares，同证券混用必须先证明数量和现金公司行动表示一致；现在冲突会在成交前拒绝，不能把不同价格单位相加后宣称物理持仓通过。SMV6 原生开盘批次的全退出/全入场分阶段共享整合、四套共同 P0 的完整独立多层对账仍未完成。当前实际四套 P0 都在初始状态门前停止，尚无共同账户历史运行。工程欠项与 600622/603368 数据欠项分别列示。
