# CYQ-GAME 统一需求矩阵

本矩阵把三份设计材料与 `AGENTS.md` 的重复约束归一化；`MUST` 是首版不可绕过的硬要求，`SHOULD` 是验收质量要求，`RESEARCH` 不阻塞 PIT-B 首版。状态含义：`VERIFIED`=代码和测试/冻结证据齐全，`IMPLEMENTED`=已有代码但尚待当前数据/阶段证据，`PARTIAL`=仅在 PIT-B 边界成立，`DEFERRED`=明确不进入首版。

| ID | 来源（页/节） | 归一化要求 | 级别 | 模块/符号 | 测试 | 运行证据 | 状态 |
|---|---|---|---|---|---|---|---|
| RQ-001 | AGENTS 1；V5.2 p7–8 | 所有事实带 `available_at`、`snapshot_id`，决策不得读取未来 | MUST | `data.pit`, `data.pit_b_store` | `test_pit.py`, `test_asof_join.py`, `test_pit_b_store.py` | 日线/分钟 V2 inventory 与 activation manifest | VERIFIED |
| RQ-002 | AGENTS 2；V5.2 p8；研究规格§硬不变量 | t bar 信号不得在 t bar 成交；`CYQK_pre` 使用交易前筹码 | MUST | `backtest.engine`, `chip.features`, `execution.simulator` | `test_e2e.py`, `test_execution.py`, `test_features.py` | 当前仅软件证据；新回测待 G10 后 | IMPLEMENTED |
| RQ-003 | AGENTS 3；V5.2 p9–10；六本 p44 | 筹码质量与交易/经济/潜在账本必须精确守恒，禁止归一化掩盖错误 | MUST | `chip.core`, `chip.ledgers` | `test_chip.py`, `test_ledgers.py`, `test_corporate_actions.py` | 单元测试 | VERIFIED |
| RQ-004 | AGENTS 4；V5.2 p13–14 | T0–T9 多标签、市场周期可多类，独立风险状态拥有否决权 | MUST | `state.classifier`, `state.strict` | `test_states.py`, `test_decision.py` | 单元测试 | VERIFIED |
| RQ-005 | AGENTS 5；V5.2 p11–13 | 板块成员必须 PIT，板块特征必须 leave-one-out | MUST | `data.pit`, `backtest.engine` | `test_pit.py`, `test_states.py`, `test_e2e.py` | PIT-B V2 审计；严格官方历史链未完备 | PARTIAL |
| RQ-006 | AGENTS 6；V5.2 p4/p7 | 流通股本、公司行动、交易状态或规则未知时 `hard_valid=false` 并禁止新增风险 | MUST | `data.validity`, `data.audit`, `backtest.engine` | `test_validity.py`, `test_data_audit.py`, `test_corporate_actions.py` | 日线/分钟 V2 hard-valid 审计 | VERIFIED |
| RQ-007 | AGENTS 7；V5.2 p13/p17–18 | 状态概率仅过滤不平滑；仓位概率必须样本外校准 | MUST | `state.classifier`, `portfolio.sizing` | `test_states.py`, `test_portfolio.py`, `test_walkforward.py` | 新策略 OOS 证据待后续阶段 | IMPLEMENTED |
| RQ-008 | AGENTS 8/21；V5.2 p4/p27 | 实验、失败、留出访问、覆盖和操作事件只追加不改写 | MUST | `data.events`, `data.pit.AppendOnlyLedger` | `test_events.py`, `test_governance.py` | `data/audit/experiment_ledger.jsonl` | VERIFIED |
| RQ-009 | AGENTS 9；V5.2 p24/p29 | 状态、订单、事件重放和对账必须幂等、确定性 | MUST | `data.events`, `execution.reconciliation`, `cli` | `test_events.py`, `test_account_reconciliation.py`, `test_e2e.py` | 旧 U3 replay 仅作参考；新证据待后续 | IMPLEMENTED |
| RQ-010 | AGENTS 10；V5.2 p4 | 实盘默认关闭，账户不一致触发 kill switch | MUST | `config`, `execution.reconciliation` | `test_config.py`, `test_account_reconciliation.py` | 配置与测试 | VERIFIED |
| RQ-011 | AGENTS 11；V5.2 p29 | 发布必须支持代码/schema、挂单和组合状态回滚 | SHOULD | `execution.plans`, `execution.reconciliation`, operator runbook | `test_plans.py`, `test_account_reconciliation.py` | 实盘发布延期 | PARTIAL |
| RQ-012 | AGENTS 12；V5.2 p28–29 | `pytest -q`、`ruff check .`、`mypy src/` 全部通过 | MUST | 全仓 | 全测试 | 每阶段重新记录退出码 | IMPLEMENTED |
| RQ-013 | AGENTS 13；V5.2 p14 | 状态不是订单；交易必须绑定 `StrategyFamily` 和完整 `EdgeCard` | MUST | `game.decision.EdgeCard`, `execution.plans` | `test_decision.py`, `test_plans.py` | 单元测试 | VERIFIED |
| RQ-014 | AGENTS 14；V5.2 p14；六本 p15/p56 | 参与者状态只能是可证伪潜变量，禁止声称识别真实账户/庄家 | MUST | `game.decision` | `test_decision.py` | 文档与类型边界 | VERIFIED |
| RQ-015 | AGENTS 15；V5.2 p17–21 | `NO_TRADE` 是一等动作并与所有活动作比较 | MUST | `game.decision` | `test_decision.py` | 单元测试 | VERIFIED |
| RQ-016 | AGENTS 16；V5.2 p17–19；六本 p2/p31 | `Q(action)` 纳入费用、滑点、冲击、反身性和退出受阻尾损 | MUST | `game.decision`, `execution.simulator` | `test_decision.py`, `test_execution.py` | 新回测成本压力待后续 | IMPLEMENTED |
| RQ-017 | AGENTS 17；V5.2 p15–16 | 数据质量与可观测性独立；高质量不能覆盖解释歧义 | MUST | `game.decision`, `domain` | `test_decision.py` | 单元测试 | VERIFIED |
| RQ-018 | AGENTS 18；V5.2 p18 | Kelly 仅用 OOS 校准概率且始终分数化并受容量约束 | MUST | `portfolio.sizing` | `test_portfolio.py` | 新策略校准待后续 | IMPLEMENTED |
| RQ-019 | AGENTS 19；V5.2 p20；六本 p26 | 加仓要求后验改善和更高保护止损；禁止仅因下跌摊低成本 | MUST | `execution.plans` | `test_plans.py` | 单元测试 | VERIFIED |
| RQ-020 | AGENTS 20；V5.2 p20 | 每个 `TradePlan` 版本化；论点变化必须新建计划 | MUST | `execution.plans.TradePlan` | `test_plans.py` | 单元测试 | VERIFIED |
| RQ-021 | AGENTS 22；V5.2 p22 | 探针交易必须是真实合法订单；禁止幌骗、洗售和操纵信号 | MUST | `execution.plans`, live-disabled boundary | `test_plans.py`, `test_config.py` | 实盘关闭 | VERIFIED |
| RQ-022 | V5.2 p9–10；六本 p5/p9/p14 | 筹码是带记忆和误差的成本状态估计；支持 uniform/cohort、价格网格、迁移与峰值 | MUST | `chip.core`, `chip.features` | `test_chip.py`, `test_features.py`, `test_chip_peak_equivalence.py` | 单元与等价性测试 | VERIFIED |
| RQ-023 | V5.2 p9–10；研究规格§公司行动 | 公司行动按可得时间进入，显式记录现金/拆并股/解禁及成本基础 | MUST | `chip.ledgers`, `data.pit` | `test_corporate_actions.py`, `test_ledgers.py` | PIT-B 最终事实；完整修订链延期 | PARTIAL |
| RQ-024 | V5.2 p11–16；六本 p21–24/p29 | 市场、板块、筹码迁移、收益来源、替代解释和尾部风险共同构成 Evidence DAG | MUST | `state.classifier`, `game.decision` | `test_states.py`, `test_decision.py` | 新策略运行证据待后续 | IMPLEMENTED |
| RQ-025 | V5.2 p20/p22；六本 p2/p31 | 执行遵守 T+1、停牌、涨跌停、手数、流动性、部分成交与阻塞退出 | MUST | `execution.simulator`, `data.validity` | `test_execution.py`, `test_validity.py` | PIT-B 交易状态/规则输入 | VERIFIED |
| RQ-026 | V5.2 p24/p26–29 | 每次运行绑定配置、代码、输入快照和输出哈希，可重放、可审计 | MUST | `data.events`, `cli`, manifests | `test_events.py`, `test_data_activation.py`, `test_e2e.py` | 旧 U3 manifest/replay；新运行待后续 | IMPLEMENTED |
| RQ-027 | 研究规格§回测/消融/压力 | 先短样本、再局部回归、最后全量；使用 walk-forward、成本/容量压力和消融，禁止反复窥视留出集 | MUST | `backtest.walkforward`, `backtest.robustness`, `backtest.diagnostics` | `test_walkforward.py`, `test_robustness.py`, `test_diagnostics.py` | 禁止在 G10 前运行 | IMPLEMENTED |
| RQ-028 | 用户数据边界；研究规格§基准 | QMT/quant 是行情、分钟/Tick、资本、停牌和实时状态主源；补充源不能用当前快照伪造历史 | MUST | 数据构建脚本、`data.pit_b_store` | `test_quant_adapter.py`, `test_data_audit.py` | 日线/分钟 V2 inventories | VERIFIED |
| RQ-029 | 用户首版范围；V5.2 p7 | 1 分钟数据用于开收盘结构、VWAP、量能、实现波动和下一交易窗口成交证据，不允许同分钟未来信息 | MUST | `data.pit_b_store`, `backtest.engine` | `test_pit_b_store.py`, `test_e2e.py` | 分钟 V2 inventory/cross-year gate | IMPLEMENTED |
| RQ-030 | 用户首版范围；研究规格§数据缺失 | 基本面无可靠 PIT 数据时整条分支省略，不得把缺失当零分 | MUST | `fundamentals`, `backtest.engine` | `test_fundamentals.py`, `test_e2e.py` | 当前基本面 discovery-only | VERIFIED |
| RQ-031 | 用户延期边界；V5.2 p33–35 | 严格 PIT-A 需完整公告修订链、官方历史板块/ST/规则证明；不得由 PIT-B 冒充 | RESEARCH | 数据注册表与激活 manifest | `test_data_asset_registry.py`, `test_data_activation.py` | strict archival PIT=false | DEFERRED |
| RQ-032 | 用户延期边界；六本 p15/p56 | L2 队列/逐笔委托、真实账户识别、复杂 HMM、实盘交易不进入首版关键路径 | RESEARCH | 无首版实现授权 | `test_config.py` | 明确延期 | DEFERRED |

## 去重覆盖说明

- AGENTS 1–22 均由 RQ-001 至 RQ-021 覆盖，其中重复的追加式审计要求合并在 RQ-008。
- V5.2 的完整硬不变量由 RQ-001 至 RQ-027 覆盖；工程清单中与这些条目重复的表述不另建空壳需求。
- 六本经典材料作为模型边界、交易约束和可证伪性来源，不把叙事性内容误列为可执行规则。
- 研究规格中的参数搜索、压力测试和晋级要求归入 RQ-027；只有 G10 数据和软件门禁完成后才能产生运行证据。
