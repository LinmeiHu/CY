# CYQ-GAME 产物清单

盘点时间：2026-08-21。此清单只记录权威入口和冻结边界，不复制大型文件哈希；精确输入指纹以 inventory、activation manifest 和运行 manifest 为准。

| 类别 | 权威路径 | 状态/用途 |
|---|---|---|
| 工程约束 | `/Users/linmei/Documents/CY/AGENTS.md` | 22 条强制不变量 |
| 执行计划 | `/Users/linmei/Downloads/workspace/quant/docs/CYQ_GAME_EXECUTION_PLAN.md` | 阶段与门禁来源；PIT-A 延期边界服从用户后续明确指令 |
| 设计规格 | `/Users/linmei/Downloads/CYQ-GAME_V5.2_最终统一设计与工程规格.pdf` | 主规格，35 页 |
| 理论材料 | `/Users/linmei/Downloads/筹码分布_从成本迁移到交易决策_六本经典去冗余重构版.pdf` | 模型边界和可证伪要求，57 页 |
| 研究规格 | `/Users/linmei/Downloads/基于《筹码分布》与《股市博弈论》的 Codex 可实现量化交易系统研究与工程规格.docx` | 研究、回测与工程要求 |
| 源代码 | `src/cyq_game/` | 数据、筹码、状态、博弈、组合、执行、回测模块 |
| 构建脚本 | `scripts/build_daily_pit_b_dataset.py` | 日线 PIT-B 构建；未在 G0 运行 |
| 构建脚本 | `scripts/build_minute_pit_b.py` | 分钟 PIT-B 构建；未在 G0 运行 |
| 数据审计脚本 | `scripts/validate_data_registry.py` | 注册表验证；允许在数据门禁阶段运行 |
| 回测/报告脚本 | `scripts/run_backtest.py`, `scripts/run_robustness.py`, `scripts/build_*report*` | G0–G10 禁止运行 |
| 测试 | `tests/` | 单元、PIT、守恒、执行、重放和端到端软件测试 |
| 数据注册表 | `configs/data_asset_registry.json` | 数据授权和资产状态入口 |
| 日线 V2 输入 | `data/processed/pit_b_daily_2018_2026_v2/` | 2018–2026 PIT-B 因果研究输入；9,421,907 行 |
| 日线 V2 inventory | `data/input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json` | 冻结输入与审计证据 |
| 分钟 V2 输入 | `data/processed/pit_b_minute_2018_2026_v2/` | 日级分钟证据与执行窗口输入 |
| 分钟 V2 inventory | `data/input_inventories/CY-008-pit-b-minute-v2-2018-2026-20260821.json` | 冻结输入与年度审计证据 |
| 分钟跨年门禁 | `data/audit/CY-008-minute-pit-b-cross-year-gate.json` | 跨年连续性和一致性证据 |
| 联合激活快照 | `data/input_snapshots/CYQ-PIT-B-DAILY-MINUTE-CHIP-2018-2026-20260821-R4.json` | 当前日线/分钟/冻结筹码特征联合授权入口；严格 PIT-A=false |
| 旧日线 V1 | `data/processed/pit_b_daily_2018_2026_v1/` | 历史研究参考，不得替代 V2 当前基线 |
| 旧回测 | `runs/pitb-final-all-20200102-20260812-u1/` | 失败实验，追加保留 |
| 旧回测 | `runs/pitb-final-all-20200102-20260812-u2/` | 中止实验，追加保留 |
| 旧回测 | `runs/pitb-final-all-20200102-20260812-u3/` | 完成但经济晋级失败；非严格研究参考 |
| 旧基线冻结 | `docs/cyq_game_research_baseline_freeze.md` | 旧运行路径、哈希和非严格原因 |
| 需求追踪 | `docs/cyq_game_requirement_matrix.md` | 统一 MUST/SHOULD/RESEARCH 追踪入口 |
| 实验账本 | `data/audit/experiment_ledger.jsonl` | 追加式实验、留出访问和迁移事件入口 |

## 当前授权边界

- 可用于首版：QMT/quant 日线、1 分钟线、停牌/昨收、历史流通股本，配合最终公司行动、版本化交易规则和可用板块证据形成 PIT-B 因果研究输入。
- 当前禁止：把当前快照回填为历史事实、声称真实庄家账户、L2 队列/逐笔委托模拟、严格 PIT-A 声明、实盘券商下单。
- 基本面分支在无可靠 PIT 输入时必须省略，不得把缺失当作零分。
- 复杂板块 alpha 在历史成分证据不足时不参与下单；必要的 leave-one-out 市场/板块证据仍须通过数据门禁。
