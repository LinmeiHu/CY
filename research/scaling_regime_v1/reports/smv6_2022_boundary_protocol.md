# SMV6 2022 边界协议

结论：RESEARCH_SEGMENT_ONLY。冻结策略没有 2022-01-01 或年度 init 规则。`smv6.py:_run_callbacks` 和 `smv6_physical.py:callback_stream` 均在一次运行的日历循环之前调用 init；`native_states_v06.py:109–117` 为两个研究区间各创建一次平台，这才导致第二次初始化。连续运行必须携带所有状态。

`smv6_frozen.py:168` 初始化 prev_trade_date=None；651–669 的 is_new_trading_week 对 None 返回 False，否则比较 W-FRI 周。725–806 在 before_trading 更新 prev_trade_date 之前计算市场条件；1825–1879 仅进行策略原生每日队列重置。全年重置没有源码依据。

原始回调实跑结果（元；逐阶段完整 context、desired 与 pending 在 output/smv6_boundary_state.csv 和 trace.json）：

|协议|阶段|cash|NAV|gross|positions|
|---|---|---:|---:|---:|---|
|segmented|BEFORE_PREPARE|1000000.000000|1000000.000000|0.000000|{}|
|segmented|AFTER_CLOSE|499521.341403|1019454.741403|519933.400000|{"159865.SZ": 554300}|
|continuous|BEFORE_PREPARE|1260255.978086|1260255.978086|0.000000|{}|
|continuous|AFTER_CLOSE|1260255.978086|1260255.978086|0.000000|{}|

连续账户带入 2021-12-31 的 prev_trade_date，1 月 4 日是新交易周。HS300 ETF 前收 4.589 低于 MA20 4.6199，weekly_exit=True；日紧急阈值 4.5275 尚未触发。周退出使 entry_permission=False。分段 prev_trade_date=None 导致 weekly_exit=False，而 CSI1000 的 entry gate 为 True，于是 desired=['159865.SZ']，CAP50_SET 买入 554,300 股，收盘持仓 519,933.40。

分类：现金 260,255.978086 元差为 SEGMENT_RESET_EFFECT；周边界与许可差为 CALLBACK_STATE_EFFECT；后续订单/持仓差为 EXECUTION_STATE_EFFECT。开盘前两边均空仓，因此 POSITION_CARRY_EFFECT 在此边界为零；注册历史数据相同，RANKING_HISTORY_EFFECT 为零。不存在 UNKNOWN，也不把合法连续状态定性为 BUG。逐日运行与旧连续 Native/父分段参考最大 NAV 误差分别为 4.66e-10 元/0。

这些结果只解释 2022-01-04 的状态，不声称解释任何后续年度盈亏。local SMV6 仍未证明原生 SuperMind 平台完全等价。
