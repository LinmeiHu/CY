# 入场选择协议与 P0 校准纠偏交接

状态：`ACTION_REQUIRED`
优先级：研究结论阻断项；在完成本文件要求前，禁止冻结最终参数、访问 2023 最终留出期、生成可执行 EdgeCard、进行 Kelly 仓位授权或作出可交易收益声明。

## 给另一个 Codex 任务的直接指令（可整段复制）

```text
请先完整阅读：
1. /Users/linmei/Documents/CY/AGENTS.md
2. /Users/linmei/Documents/CY/docs/ENTRY_SELECTION_AND_P0_CORRECTION_HANDOFF_20260824.md

把本文件列出的“入场选择协议失效”和“P0 伪 OOS 校准”加入当前 Goal 的最高优先级，并严格按文档顺序纠正。

如果 run_markup_retest_exact_exit_lattice.py 仍在运行：不要中断，让它完成并保留全部产物；但把结果标为 DIAGNOSTIC_ONLY，不得据此冻结这两组入场参数。完成后暂停所有 2023 留出期、最终冻结、概率校准、EdgeCard 和仓位下游。

不要覆盖、删除、移动或改写现有 entry_frequency.json、exact-exit 结果和 trials/events.jsonl。用追加式 ledger 事件和新的 review/protocol manifest 宣告旧入场 shortlist 不再具备正式选择资格。新代码必须 fail closed：只有频率 PASS 的旧产物不能再进入最终冻结。

在查看其余 79 组参数的收益前，先追加登记新的 ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2，写清样本充分性方法、精确成交口径、净收益指标、风险门槛、参数邻域门槛、排序规则、2023 访问锁和 NO_TRADE 规则。不得看完结果再调门槛。

移除“每年信号 100–200、三年平均 120–180”作为入场优劣硬门禁。年度信号数保留为诊断；样本不足返回 INSUFFICIENT_EVIDENCE；信号过多只有在组合容量、并发暴露、成交冲击或尾部风险门槛失败时才淘汰。

所有 81 组入场参数都必须获得可比较的开发期经济评价；不能只计算旧频率门禁选出的 2 组。收益评价必须使用真实下一可成交窗口、精确 5 分钟成交、费用/滑点/冲击、阻塞退出和完整交易闭环。2020–2022 已被反复查看，只能称 development / walk-forward evidence，不能重新命名为未触碰 OOS；2023 仍保持一次性最终留出期。

参数稳健性必须基于经济表现邻域，而不是频率邻域。至少要求一个直接相邻入场参数也通过同一经济门禁；候选最好属于不少于 3 个网格点的连通正收益平台。没有稳健连通区域时输出 NO_TRADE / NO_ROBUST_ENTRY_REGION，禁止强行选一个孤立最优点。

同时修复 src/cyq_game/data/pit_b_store.py 的 P0：训练期统计不得标 out_of_sample=True；fallback 必须 out_of_sample=False；calibration_error 必须来自真正后续未参与拟合的预测与标签，报告实际 ECE/Brier 并比较基准；先在完整连续交易序列上构造 5 个交易日后的标签，再过滤训练原点，禁止对稀疏 train_dates 直接 LEAD(close, 5)。校准不合格或证据不足必须阻断 Kelly/EdgeCard。

完成后先跑定向测试，再在没有其他满载计算进程时一次性运行 pytest -q、ruff check .、mypy src/。最终汇报必须给出：旧产物隔离证据、新协议 ledger 事件、81 组经济评价覆盖、参数连通区域、NO_TRADE 对照、P0 校准真实 OOS 证据、2023 未访问证明，以及 PASS 或 NO_TRADE 结论。不要为了得到 PASS 改门槛。
```

## 一、必须立即纠正的结论

当前 `entry_frequency.json` 只能证明 2/81 组参数满足人为设定的信号数量区间，不能证明这两组收益更好，也不能证明其参数稳健。现有正式 shortlist 应被判定为：

```text
DIAGNOSTIC_ONLY
FORMAL_SELECTION_ELIGIBLE = false
reason = ENTRY_FREQUENCY_GATE_HAS_NO_ECONOMIC_OR_ADJACENCY_VALIDITY
```

当前精确出场任务可以继续跑完，因为它不调用 P0 校准函数，且保留其结果有助于诊断；但它只覆盖 2 个旧频率候选，不能作为最终入场参数选择证据。

## 二、已经验证的证据

### 2.1 相邻稳健性没有成为硬门禁

`src/cyq_game/strategy/research.py` 的当前实现：

- 第 631–638 行只检查每年信号数与三年平均数；
- 第 644–658 行计算 `adjacent_frequency_passes`；
- 第 659 行只根据频率区间写 `PASS/FAIL`；
- 第 664–671 行仅把相邻通过数用于排序。

因此，`adjacent_frequency_passes=0` 不会阻止候选进入 shortlist。两个现有候选的该值均为 0。

### 2.2 两个“孤立通过点”主要由硬边界制造

现有两个候选：

| 参数 ID | 2020 | 2021 | 2022 | 年均 | 相邻频率通过数 |
|---|---:|---:|---:|---:|---:|
| `e3cf6dbc57eeb26f` | 163 | 171 | 105 | 146.33 | 0 |
| `476558c3bcb51cf2` | 192 | 199 | 113 | 168.00 | 0 |

直接相邻点显示参数响应并非必然断裂：

- 第一组只把 `breakout_buffer_atr` 从 0 调到 0.25，信号变为 `135/142/82`，年均 `119.67`；它因 2022 少于 100、年均仅比 120 少 0.33 而失败。
- 第二组只把 `breakout_buffer_atr` 从 0.25 调到 0.50，信号变为 `149/139/85`，年均 `124.33`；它仅因 2022 少于 100 而失败。
- 第二组只把 `max_retest_depth_atr` 从 1.0 调到 0.5，同样得到 `135/142/82`。

这说明当前“孤岛”至少部分是 `[100, 200]` 和 `[120, 180]` 的不连续截断造成的，不能解释为邻居经济表现更差。

### 2.3 原始年度信号数不能代表策略质量

81 组参数的年度信号数横截面中位数为：

- 2020：108；
- 2021：78；
- 2022：38。

年度机会数量明显不恒定。策略已经有大盘、板块、可交易状态和 `NO_TRADE` 条件；坏环境少交易可能是正确行为。强制每个自然年达到同一最低信号数，会奖励坏环境过度交易；好环境超过固定上限也不天然表示质量差。

仓库中未找到 `100–200/年`、`120–180/年均` 的统计功效、资金容量或经济依据。这些值目前只能视为工程常数，不能作为正式选择标准。

### 2.4 79 组被淘汰参数没有精确收益证据

`scripts/run_markup_retest_exact_exit_lattice.py` 明确要求旧 shortlist 必须恰好包含 2 个候选，再扩展为 `2 × 9 = 18` 组出场试验。其余 79 组未进入精确 5 分钟收益评价。

因此现有流程无法回答：被频率门禁删除的参数中，是否存在净收益更高、回撤更低或邻域更稳定的组合。

## 三、旧产物的正确处置

### 3.1 不允许破坏审计链

必须保留原文件和哈希：

- `output/markup_retest_main_chinext_2020_2023_v1/validation/development/e8b4e5e6938f/entry_frequency.json`
- 当前 exact-exit 输出（完成后）；
- `output/markup_retest_main_chinext_2020_2023_v1/trials/events.jsonl`

禁止覆盖旧 `PASS`、删除试验或把旧文件静默替换为新定义。

### 3.2 追加失效声明

建议新增：

- ledger 事件：`ENTRY_SELECTION_PROTOCOL_INVALIDATED`；
- ledger 事件：`ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2`；
- review manifest：
  `output/markup_retest_main_chinext_2020_2023_v1/validation/development/e8b4e5e6938f/entry_selection_protocol_review_v2.json`。

失效事件至少记录：旧 snapshot ID、配置哈希、代码版本、发现时间、两个 `adjacent_frequency_passes=0`、阈值无依据、79 组无经济评价、旧 exact-exit 仅作诊断、2023 是否访问。

新的下游加载器必须要求 `ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2` 的合格 manifest；只有旧 `entry_frequency.json: PASS` 时必须 fail closed。

## 四、新的入场选择协议

### 4.1 第一层：数据、成交和容量可行性（不按收益挑参数）

保留以下硬门禁：

- 所有输入在 `decision_at` 可得，snapshot/hash/注册资产一致；
- 信号形成后只能在下一合法可成交窗口成交；
- 精确 5 分钟入场成交率和交易闭环率达到预先登记的要求；
- 费用、滑点、冲击和阻塞退出完整计入；
- 筹码质量、公司行动、流通盘、交易状态未知时阻断风险；
- 组合并发、行业暴露、市场冲击和退出容量不过载。

取消以下经济选择硬门禁：

- 每个自然年必须 100–200 个信号；
- 三年平均必须 120–180 个信号。

年度信号数、市场状态内信号率、每 1 万个 eligible stock-days 的信号率仍应保存，但只作诊断。

样本不足不得写成普通 `FAIL`，应写成 `INSUFFICIENT_EVIDENCE`。有效样本要求必须在查看其余 79 组收益前，根据最小经济意义效应、交易相关性和置信区间精度完成并登记功效分析；禁止看完结果再决定最小样本数。

### 4.2 第二层：开发期经济证据

所有 81 组入场参数必须使用同一口径评价。为控制计算量，可以复用当前单次面板扫描、共享精确血缘缓存和共享 5 分钟成交窗口，但不能因计算成本只评价旧 2 组。

主要评价指标应至少包括：

- 单笔净收益均值和中位数；
- 截尾净收益；
- 盈亏比与胜率（只作分解，不能单独排名）；
- 事件序列最大回撤；
- 阻塞退出尾部损失；
- 入场成交率、闭环率、持仓时间和并发暴露；
- 按因果可知的大盘/板块状态分层结果；
- 按交易日或周做 block bootstrap 的净期望置信区间；
- 与 `NO_TRADE`、无条件 eligible 基线的比较。

不能用总利润直接排名，因为总利润会机械偏向信号更多的参数。主要经济门禁应基于净期望及其不确定性，门槛必须在运行其余 79 组前追加登记。

2020–2022 已被反复探索，只能称为 `DEVELOPMENT` 或 `WALK_FORWARD_DEVELOPMENT_EVIDENCE`。任何时序折叠都必须 purge 标签窗口并保留 embargo，但不能借走步回放把已看过的年份重新宣传为真正未触碰 OOS。

### 4.3 第三层：参数经济邻域

把 `adjacent_frequency_passes` 从正式选择逻辑中移除，改为经济邻域：

```text
adjacent_economic_passes >= 1
```

推荐更强要求：候选属于至少 3 个网格点组成的连通经济合格区域。邻接仍定义为四个入场维度中仅一个维度移动一档。

如果原始 3 档网格没有形成连通正收益区域：

1. 不得选择孤立最高点；
2. 先输出 `NO_ROBUST_ENTRY_REGION`；
3. 只在可能的平台附近增加连续参数中点并增量计算；
4. `setup_score_min` 是 5 个布尔分量之和，只能以 0.2 的有效步长变化，禁止加入 0.7、0.9 等不会改变信号的伪档位；
5. 新档位必须按参数哈希增量缓存，不能重跑所有旧组合。

### 4.4 选择结果允许为 NO_TRADE

新协议最终只能产生两类合法结果：

- `PASS`：存在经济合格且邻域稳健的参数区域；
- `NO_TRADE`：不存在稳健区域或证据不足。

禁止为了得到候选而放宽门槛。年度表现可以有好坏，不再要求每个自然年平均收益都大于 0；但必须通过预先登记的总体置信下界、回撤、尾部损失和容量门槛。年份和市场状态结果用于解释脆弱性，不应用日历边界替代风险约束。

## 五、P0 伪 OOS 校准必须同步修复

文件：`src/cyq_game/data/pit_b_store.py`，函数：`calibrate_forecast`、`calibrate_forecasts`。

已知问题：

1. 在 `train_dates` 上统计胜率后直接写 `out_of_sample=True`；
2. fallback 也写 `out_of_sample=True`；
3. `calibration_error=min(0.20, abs(probability - 0.5) * 0.25)` 不是实际校准误差；
4. 对已经过滤成 `train_dates` 的稀疏行执行 `LEAD(close, 5)`，当日期不连续时含义不是未来第 5 个交易日；
5. 没有真正的后续预测评分、ECE/Brier 和基准比较，却可能向 Kelly/EdgeCard 传递 OOS 资格。

修复要求：

- 先在完整连续交易序列中生成因果 5 交易日标签，再筛选训练原点；
- 拟合期统计只能产生未校准预测，`out_of_sample=False`；
- 只有在严格更晚、标签窗口不重叠的评价折上完成评分，才允许 `out_of_sample=True`；
- ECE、Brier、基准 Brier 必须由实际预测与实际标签计算；
- 样本不足、单一类别或无评价折时 fallback 必须 `out_of_sample=False`；
- 校准模型不优于基准或 ECE 超限时阻断 EdgeCard/Kelly；
- 所有折必须记录训练结束、评价开始/结束、purge/embargo、样本数、snapshot 和代码哈希。

## 六、测试与验收门槛

### 6.1 必须新增的定向测试

- `adjacent_economic_passes=0` 时不得进入正式 shortlist；
- 年度信号数不均匀但经济证据合格时，不因原始计数被拒绝；
- 信号很多时，只有容量/暴露/冲击门禁失败才拒绝；
- 79 组均获得同口径经济评价或明确 `INSUFFICIENT_EVIDENCE`；
- 旧 `entry_frequency.json: PASS` 不能进入最终冻结；
- 旧 exact-exit 产物只能被诊断路径读取；
- 非连续 `train_dates` 的 5 日标签仍对应真实第 5 个交易日；
- 训练期结果不得标记 OOS；
- fallback 不得授权 Kelly；
- ECE/Brier 来自实际评价预测；
- 2023 未满足新协议和 P0 门禁时读取必须失败。

### 6.2 完成定义

以下全部成立才能解除阻断：

1. 旧 shortlist 和旧 exact-exit 已追加式标记为 `DIAGNOSTIC_ONLY`；
2. 新协议在查看其余 79 组收益前写入 ledger；
3. 81 组均有统一经济评价；
4. 参数选择依据经济邻域，而非年度频率区间；
5. P0 校准拥有真实后续评价折、实际 ECE/Brier 和 fail-closed fallback；
6. `pytest -q`、`ruff check .`、`mypy src/` 全部通过；
7. 2023 最终留出期此前未被新协议用于调参；
8. 冻结结果是稳健参数区域或明确 `NO_TRADE`，不能是被迫挑出的孤点。

## 七、最终汇报模板

另一个任务完成纠偏后，应按下列顺序汇报：

1. 当前运行进程和旧产物是否完整保留；
2. 追加的失效事件与新协议事件 ID；
3. 81 组参数经济评价覆盖率；
4. 样本充分性与容量定义；
5. 经济合格参数的连通区域及相邻点数量；
6. 净收益、置信区间、回撤、尾部损失和成交闭环；
7. P0 校准训练折/评价折、ECE/Brier、基准和 OOS 证明；
8. 2023 是否访问；
9. 最终结论：`PASS` 或 `NO_TRADE`；
10. 软件门禁结果与所有仍未解除的限制。

不得再使用“79 组失败、2 组通过”暗示参数收益优劣。准确措辞应为：“旧频率区间筛选留下 2 个诊断候选；该选择协议已失效，正式经济选择待 V2 完成。”
