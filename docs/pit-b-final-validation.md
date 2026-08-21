# CYQ-GAME PIT-B 最终验收记录

> 冻结声明：本文记录的是旧版 PIT-B 研究基线，不是当前系统完成证明、严格 PIT-A 证明或策略晋级证明。权威冻结边界见 `docs/cyq_game_research_baseline_freeze.md`；后续不得覆盖原运行目录。

验收日期：2026-08-21（Asia/Shanghai）

## 最终结论

| 项目 | 结论 | 解释 |
|---|---|---|
| 数据与工程链路 | PASS | 冻结输入、PIT 联结、五类审计、`hard_valid`、状态/决策/执行、事件链和重放均完成 |
| 2020–2026 全市场验收 | PASS | 指定 R2 输入和固定配置运行完成，命令退出码 0 |
| 确定性重放 | PASS | 139,519 个事件、终态和全部受管产物哈希一致，退出码 0 |
| 策略经济晋级 | FAIL | 总收益、Sharpe、Sortino、Calmar 和 profit factor 为负或低于晋级要求 |
| 严格 PIT-A 归档 | NOT READY | 当前是 PIT-B 因果研究版，完整历史公告版本链和官方历史证明仍延期 |
| 实盘 | DISABLED | 本仓库没有实时券商下单通路；失败研究结果不得部署 |

这意味着“基于现有免费/QMT 数据可实现的首版系统”已经完整交付并得到可复现结论，但策略本身没有通过晋级。负结果按追加式实验保留，不能删除、改写或以继续查看最终留出集的方式调参。

## 冻结数据证据

- PIT-B 仓：[`../data/processed/pit_b_daily_2018_2026_v1/audit.json`](../data/processed/pit_b_daily_2018_2026_v1/audit.json)
- 输入 inventory：[`../data/input_inventories/CY-003-pit-b-daily-2018-2026-20260820.json`](../data/input_inventories/CY-003-pit-b-daily-2018-2026-20260820.json)
- 激活 manifest：[`../data/input_snapshots/CYQ-PIT-B-DAILY-2018-2026-20260820-R2.json`](../data/input_snapshots/CYQ-PIT-B-DAILY-2018-2026-20260820-R2.json)
- 数据注册表：[`../configs/data_asset_registry.json`](../configs/data_asset_registry.json)
- CY-003 inventory SHA-256：`69d4005a3d709c87eaffbdb1ca927cd87d4c18f77819e4c90decee8e65138aff`
- R2 manifest SHA-256：`9d89535b4a33e47f10f0d62cb1b0cb9c5a9b4b55c8ae9f8682253a92b1852034`
- 覆盖：2018-01-02 至 2026-08-12，5,682 个证券，9 个年度 Parquet 分区，共 9,421,907 行。
- `hard_valid=true`：9,065,778 行（96.2202%）；无效 356,129 行保留原因码并禁止新增风险。
- 覆盖、重复、时间穿越、一致性和跨表审计均为 PASS，`issue_count=0`。
- 注册表状态：`free_causal_research_ready=true`、`backtest_authorized=true`、`strict_archival_pit_ready=false`。

## 分阶段执行证据

| 阶段 | 运行目录 | 范围 | 结果 |
|---|---|---|---|
| V1 单标的短样本 | [`../runs/pitb-short-000001-20240102-20240628-r3`](../runs/pitb-short-000001-20240102-20240628-r3) | 000001.SZ，2024 年开发样本 | 完成；94 个决策、4 个成交；重放 PASS |
| V2 局部回归 | [`../runs/pitb-regression-10x-20220104-20231229-r3`](../runs/pitb-regression-10x-20220104-20231229-r3) | 10 标的，2022–2023 | 完成；49 个成交；重放 PASS |
| V1 全市场短样本 | [`../runs/pitb-all-short-20240102-20240329-u1`](../runs/pitb-all-short-20240102-20240329-u1) | 全市场，2024 年短区间 | 完成；230,786 个决策、316 个成交；重放 PASS |
| V3 最终全量 | [`../runs/pitb-final-all-20200102-20260812-u3`](../runs/pitb-final-all-20200102-20260812-u3) | 全市场，2020-01-02 至 2026-08-12 | 完成；退出码 0；重放 PASS |

所有运行使用 2018-01-02 开始的历史预热形成筹码状态。短样本和局部回归先验证机制；只有这些阶段通过后才启动最终全量。

## 最终运行命令与退出码

```bash
.venv/bin/cyq-game backtest \
  --config configs/research_pit_b_final.yaml \
  --registry configs/data_asset_registry.json \
  --input-manifest data/input_snapshots/CYQ-PIT-B-DAILY-2018-2026-20260820-R2.json \
  --history-start 2018-01-02 \
  --start 2020-01-02 \
  --end 2026-08-12 \
  --run-id pitb-final-all-20200102-20260812-u3 \
  --walk-forward \
  --access-final-holdout
```

- 退出码：`0`
- 运行时间：12,248 秒，约 3 小时 24 分钟
- 状态：`COMPLETE`
- 评估区间：2020-01-02 至 2026-08-12
- 历史预热起点：2018-01-02
- 证券数：5,682
- 决策记录：7,425,502
- 事件摘要：`5ad56104d4e74da8ff1e86d5dd7a721ff2c2bd346543fa77662782069f70f96e`

确定性重放：

```bash
.venv/bin/cyq-game replay \
  --config configs/research_pit_b_final.yaml \
  --run-id pitb-final-all-20200102-20260812-u3 \
  --deterministic
```

- 退出码：`0`
- 状态：`PASS`
- 事件数：139,519
- 检查：事件序列/摘要、最终现金、最终持仓、运行 ID、汇总终态和全部产物哈希均一致。
- 报告：[`../runs/pitb-final-all-20200102-20260812-u3/replay_report.json`](../runs/pitb-final-all-20200102-20260812-u3/replay_report.json)

## 最终绩效与执行诊断

| 指标 | 结果 |
|---|---:|
| 初始权益 | 10,000,000.00 |
| 最终权益 | 9,495,607.85 |
| 总收益 | -5.0439% |
| 年化收益 | -0.8113% |
| 年化波动 | 1.9874% |
| 最大回撤 | 8.8545% |
| Sharpe | -0.3999 |
| Sortino | -0.4497 |
| Calmar | -0.0916 |
| Profit factor | 0.9186 |
| 成交数 | 18,023 |
| 提交订单 | 18,030 |
| 执行拒绝 | 0 |
| 生成期拒绝 | 13,709 |
| 总成本 | 205,815.41 |
| 最大市场参与率 | 1.1083%（配置上限 5%） |
| 计划遵从率 | 1.0000 |

成本压力测试的总收益依次为：0.5 倍成本 -4.0148%、1.0 倍 -5.0439%、1.5 倍 -6.0730%、2.0 倍 -7.1021%。没有成交超过参与率上限的 80%。这些证据表明负结果不是由一次明显的成交上限违规造成，但也明确说明策略没有正的成本后优势。

最终运行显式访问了 2025-04-21 至 2026-08-12 的 320 个最终留出交易日，因此 `holdout_accessed=true`、`holdout_tainted=true`。访问发生在输入和配置冻结之后并写入事件链，适合作为一次最终评估；该区间今后不能再被声称为未见数据。

## 公司行动和守恒证据

- 公司行动按现金、拆并股、解禁顺序应用；信号使用交易前 `CYQK_pre`，不允许同 bar 成交。
- 发现 1 次分拆产生零碎股理论权益，总零碎权益 0.07276 股。
- 采用 `ACCOUNT_FLOOR_LARGEST_REMAINDER_NO_CASH_IN_LIEU`：账户层先计算理论股数，整数股按最大余数法分配到批次，不虚构现金补偿。
- 未解决成本基础为 0；筹码质量和账本守恒检查通过。
- 该零碎股规则是 PIT-B 研究近似，已在事件和汇总中显式标注，不冒充券商逐账户历史处理证明。

## 受管产物

最终运行的 [`manifest.json`](../runs/pitb-final-all-20200102-20260812-u3/manifest.json) 绑定配置、注册表、输入和以下产物：

| 产物 | SHA-256 |
|---|---|
| `decisions.jsonl` | `58b56840cdce7b8764db230830c7a65af75b235369a0806df4ba1f71e9db2229` |
| `equity.csv` | `281bf43f5dce2ea51cd2272498f4c2f604d848f485947a92cfa3839fc54d178a` |
| `research_diagnostics.json` | `3a4c046e5870bc94eaa9eab0799f7385eae4bfd57cc6e9f2f2b4f82738c081f1` |
| `summary.json` | `29bac3e2219919b8ddca91e77ac7f2cd9a77e7ab0e78b3b64d4c1120abe570ea` |
| `walk_forward.json` | `7ae49f038cf23eca9279eaab520ad30adbc181e0a77b81b253cf3309242f4df9` |

重放报告重新计算并验证这些哈希。最终目录约 15 GB，其中 `decisions.jsonl` 约 15.6 GB；这是逐决策因果审计证据，不应为节省空间而删除。

## 失败实验与修复记录

- `pitb-final-all-20200102-20260812-u1` 在 2022-06-10 因分拆零碎股触发失败关闭，退出码 2。该失败暴露了账户层公司行动分配缺口；修复后增加账户整数股/批次最大余数分配、成本基础和零碎权益审计。
- `pitb-final-all-20200102-20260812-u2` 在推进到 2023-02-09 后人工中止。原因是追加事件时每次重读完整哈希链，产生 O(n²) 开销；修复为首次完整校验后缓存尾部，外部文件变化时重新全链校验。45,460 事件基准由约 0.387 秒/次降至约 0.000071 秒/次缓存追加。
- 两个目录均按追加式失败实验保留；U3 使用新 run ID 从冻结输入重新开始，没有覆盖历史证据。

## 最终软件门禁

| 命令 | 退出码 | 证据 |
|---|---:|---|
| `.venv/bin/pytest -q` | 0 | 97 passed |
| `.venv/bin/ruff check .` | 0 | All checks passed |
| `.venv/bin/mypy src/` | 0 | Success: no issues found in 39 source files |
| `.venv/bin/python scripts/validate_data_registry.py --registry configs/data_asset_registry.json` | 0 | PASS；21 assets；研究授权 true、严格 PIT-A false |

## 明确延期边界

以下项目没有伪装成已完成，也不再阻塞 PIT-B 首版结论：

- 完整公司行动预案、修改、撤回到实施的历史公告版本链；
- 历史证券名称/ST 状态和历年交易规则的官方归档证明；
- 分钟/Tick 策略、L2 队列/逐笔委托模型；
- 复杂板块 alpha、HMM、真实参与者识别和实盘交易；
- PIT-A 全量复跑。

首版采用全市场 `uniform` 固定网格筹码估计器；`cohort` 年龄队列仅保留给小样本机制测试。板块历史证据不足时不让复杂板块模型参与下单；数据缺失或冲突统一 `NO_TRADE`。这些是由现有数据能力决定的有意边界，不是把不可实现设计留在关键路径上。
