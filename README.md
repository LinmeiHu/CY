# CYQ-GAME V5

一个遵守点时（PIT）因果边界的 A 股现金多头研究与仿真系统。系统按以下方向单向传递事实，解释层不能回写筹码事实：

```text
PIT data -> chip cost state -> market/sector/T0-T9 state
         -> participant hypotheses + EdgeCard + scenarios
         -> Q(action) vs NO_TRADE -> risk/size -> versioned plan
         -> A-share execution simulator -> append-only audit/replay
```

这不是“看图猜庄家”的程序。参与者标签只是假设；T0–T9 只描述状态；任何 EdgeCard 缺失、情景模糊、风险触发或不可成交都会 fail closed 到 `NO_TRADE`。

## Data baseline

CYQ-GAME 的唯一数据输入白名单是 [`configs/data_asset_registry.json`](configs/data_asset_registry.json)，人读清单见 [`docs/data-asset-registry.md`](docs/data-asset-registry.md)。登记不等于激活：每次操作还必须提交符合 [`configs/input_snapshot_manifest.schema.json`](configs/input_snapshot_manifest.schema.json) 的冻结输入快照，契约见 [`docs/input-snapshot-manifest.md`](docs/input-snapshot-manifest.md)。新发现或发生变化的数据必须先登记来源、覆盖、字段/单位、PIT 等级、`available_at`、`snapshot_id`、哈希、质量证据和激活门禁；禁止运行时发现、静默替换或把当前快照回填成历史事实。

QMT 是行情、分钟/Tick、历史流通股本、停牌状态和实时可成交性的主源；CNINFO 补最终公司行动及公告时间，交易所规则以少量版本化事实派生。2020 年前分钟数据已经登记并保留，但首个研究版只使用日线链路。完整能力边界和实现顺序见 [`docs/data-first-implementable-system.md`](docs/data-first-implementable-system.md)。

CY-003 已物化为 2018-01-02 至 2026-08-12 的 PIT-B 日线表：9,421,907 行中 9,065,778 行 `hard_valid=true`，覆盖、重复、时间穿越、一致性和跨表审计均 PASS。研究只对精确绑定的 [`CYQ-PIT-B-DAILY-2018-2026-20260820-R2.json`](data/input_snapshots/CYQ-PIT-B-DAILY-2018-2026-20260820-R2.json) 放行；任何路径、哈希、用途或日期范围变化都会失败关闭。该版本是 B 级因果研究数据，`strict_archival_pit_ready=false`，不能表述为严格 PIT-A 归档证明。

校验注册表和输入激活状态：

```bash
.venv/bin/python scripts/validate_data_registry.py
.venv/bin/cyq-game data-status \
  --registry configs/data_asset_registry.json \
  --input-manifest data/input_snapshots/CYQ-PIT-B-DAILY-2018-2026-20260820-R2.json
```

实现版已按“一标的短样本 -> 10 标的两年回归 -> 全市场短样本 -> 2020–2026 全量”完成验收及确定性重放。最终证据、退出码、绩效和延期边界见 [`docs/pit-b-final-validation.md`](docs/pit-b-final-validation.md)。最终策略收益为负，因此工程验收 PASS，但策略晋级 FAIL；不得把该结果用于实盘或通过继续查看最终留出集来调参。

## Software verification

开发环境可运行不触发回测的软件单元测试和静态检查。合成数据只有在显式 `SOFTWARE_TEST` 输入清单授权后才能用于机制测试，不产生可引用的绩效结论。

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src/
```

`configs/paper.yaml` 只会生成模拟订单。真实交易默认关闭，且本仓库没有内置券商适配器；这是刻意的安全边界。架构、数据契约、验收矩阵和运维步骤见 [docs](docs/architecture.md)。

## Scope

- 已完成的软件构件：revision-aware PIT 存储、五类数据审计、六域 as-of 联结、`hard_valid` 状态入口、守恒筹码引擎、市场/PIT 板块 LOO/T0–T9/独立风险状态、EdgeCard/NO_TRADE/成本后 Q/分数 Kelly、A 股成交仿真、公司行动账本、walk-forward、追加式事件链与确定性重放。
- 已完成的数据范围：QMT 未复权日线、交易状态、指数、按公告时间可得的历史流通股本、CNINFO 最终公司行动、PIT 行业成员和版本化交易规则进入 CY-003；2000–2026 年 1 分钟数据已登记但未接入首轮日线策略。
- 当前研究结论：冻结的 PIT-B 全市场 2020–2026 回测与重放完成，但经济指标不满足晋级要求；结果是可复现的失败实验，不是可部署策略。
- 后续扩展接口：逐笔供应商、第三方 CYQ、行情/财报厂商和只读账户快照适配器、券商适配器。
- 延期但不阻塞本版：严格 PIT-A 公告版本链、完整历史名称/ST 官方证明、分钟/Tick 策略、复杂板块 alpha、HMM/参与者生态和实盘交易。
- 明确不做：宣称识别真实账户、在未校准概率上使用 Kelly、同 bar 成交、自动发送真实订单、绕过审计或市场规则。

真实数据接入采用规范化 CSV 契约；每条记录必须保留 `available_at`、`source`、`snapshot_id` 和 `revision_id`。基本面缺失不会被零值填充，审计或持续经营风险会独立覆盖所有做多信号。完整字段、故障处置和晋级条件见 [运维手册](docs/operator-runbook.md) 与 [需求追踪表](docs/requirements-traceability.md)。
