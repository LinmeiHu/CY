# Semantic Preflight

所有策略统一约束：`available_at <= decision_at`；截至日后退出、原因、MAE/MFE不进入结果。Cause/State/Trigger/Outcome 是描述层，不构造新择时规则。

## MCB
ECONOMIC_SEQUENCE：跨板确认后的突破需求；CAUSAL_BACKGROUND：收盘完成的市场/行业状态；STATE_VARIABLES：市场与行业20/60日强弱、广度和个股相对强度；EVENT_FORMATION_TIME：信号日收盘；CONFIRMATION_TRIGGER：冻结 V72 跨板确认；ENTRY_TIME：下一合法交易日开盘；OUTCOME_START_TIME：成交后；POSSIBLE_SEMANTIC_AMBIGUITIES：V53 行为重建 provenance 不等于原始源码；CHOSEN_TIME_ANCHORS：signal_date 收盘决策、entry_date 开盘成交。

## OGR
ECONOMIC_SEQUENCE：历史缺口下方供给释放后的有序需求修复；CAUSAL_BACKGROUND：PIT 日线、分钟、成交额与公司行动；STATE_VARIABLES：缺口区间、VAP 密度、回升、流动性与成交额；EVENT_FORMATION_TIME：信号日15:00；CONFIRMATION_TRIGGER：V28R2 有序成交额门；ENTRY_TIME：信号后首个合法分钟开盘；OUTCOME_START_TIME：成交后；POSSIBLE_SEMANTIC_AMBIGUITIES：事件回报与80槽位账户回报不是同一量；CHOSEN_TIME_ANCHORS：signal_time、entry_time、exit_time。

## IFCGR
ECONOMIC_SEQUENCE：OGR 机会叠加发行人事实冷却；CAUSAL_BACKGROUND：同轮 OGR 父候选及当时可得官方公告；STATE_VARIABLES：开放风险事实及冷却窗口；EVENT_FORMATION_TIME：沿用 OGR；CONFIRMATION_TRIGGER：PIT-B keep/reject；ENTRY_TIME/OUTCOME_START_TIME：沿用 OGR 反事实和执行；POSSIBLE_SEMANTIC_AMBIGUITIES：官方当前枚举缺少完整修订/删除历史，永久保持 PIT-B；CHOSEN_TIME_ANCHORS：公告 causal_available_at 不晚于 OGR decision_at。

## ATRDR（Bull / Fast Bear / Slow Bear）
ECONOMIC_SEQUENCE：市场状态路由后分别捕捉牛市参与扩散、熊市快速投降和慢速供给衰竭；CAUSAL_BACKGROUND：完成收盘的市场状态与 PIT 日线；STATE_VARIABLES：市场20/60日中位收益、广度、个股/行业趋势、换手与库存代理；EVENT_FORMATION_TIME：信号日收盘；CONFIRMATION_TRIGGER：冻结路由与仲裁；ENTRY_TIME：下一合法开盘；OUTCOME_START_TIME：成交后；POSSIBLE_SEMANTIC_AMBIGUITIES：历史、2024–2025、2026账户独立初始化，不能连接；OAI 与 post-2023 行为重建 provenance 保留；CHOSEN_TIME_ANCHORS：各段自身 signal/entry/exit，组合只用连续历史段。

## SMV6
ECONOMIC_SEQUENCE：ETF 压缩后点火并按冻结回调调仓；CAUSAL_BACKGROUND：QMT 日线、关键分钟和成交可用性；STATE_VARIABLES：冻结回调内部状态、现金、整手和持仓；EVENT_FORMATION_TIME：before_trading/signal；CONFIRMATION_TRIGGER：冻结 callback；ENTRY_TIME：本地平台 open/close fill；OUTCOME_START_TIME：本地成交后；POSSIBLE_SEMANTIC_AMBIGUITIES：本地现金整手语义不等于原生 SuperMind 券商等价；CHOSEN_TIME_ANCHORS：local_execution_events 与每日账户，截至日切断后续事件。
