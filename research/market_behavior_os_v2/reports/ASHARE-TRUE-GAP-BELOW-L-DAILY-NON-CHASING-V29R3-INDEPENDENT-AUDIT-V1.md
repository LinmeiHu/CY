# V29R3 独立审计：注册行截面、授权链与固定阈值邻域

审计结论：保留已经冻结的 2% 规则，不依据已消费开发结果改成 3%；但当前不能启动验证。`CY-040`、`CY-041` 及两份专用授权尚不存在，且两阶段 runner 还必须解决 scoped registry identity、Stage-B 精确身份、结果源延迟访问和一次性执行问题。

本审计只读取既有 2018–2021 开发 outcomes/特征和 2018–2021 CY-033 分区。没有读取任何 2022+ Parquet/结果行，也没有运行 Stage A/B；对 2022–2024 只核对了 prereg、注册 manifest 哈希和父级 identity freeze 元数据。

## 1. 截面与 PIT 结论

CY-033 可以合规用作“exact registered-row cross-section”：在每个信号日，对该精确注册分区中实际存在、且满足 hard-valid、可交易、`trade_status=1`、`available_at/decision_at <= signal decision_at`、snapshot 非空、价格正且有限的所有行做不加权中位数；不得再用当前股票名单、当前指数成分、行业、板块、流动性、ST、涨跌方向或结果筛选。

但它不能被表述为“完整 A 股全市场”或“已证明无幸存者偏差”。QD-007 日期有效证券主表仍未物化；CY-033 的 `historical_identity_valid` 只能处理已知代码别名，无法证明源 bar inventory 没漏掉后来退市或更名证券。准确措辞应是：

> Unweighted median of all eligible rows physically present in the exact registered CY-033 partition (conditional observed-row cross-section). No current-universe or constituent-list filter is applied. Completeness against a date-effective security master is unverified because QD-007 is unavailable.

`current_survivor_fallback_allowed=false` 只能表示“禁止用当前名单补或筛”，不能解释成“已经证明不存在源层幸存者偏差”。如果 prereg 中 `full_market/no current-survivor` 被理解为总体完整性，Stage A 必须阻断；如果按它的可执行定义 “every row present in CY-033” 理解，则可以继续，但 CY-040、冻结文件和最终报告都必须携带上述限制。

开发期复核提供了一个有用的等价性检查：56 个信号日共有 214,066 个注册行、197,782 个严格 eligible 行，每日 eligible 数为 3,033–4,356，中位数 3,378.5。旧特征生成器的字面筛选少写了若干显式条件，但在这些开发信号日上，旧/严格筛选的行集合、中位数和 2% 信号分类均零差异；所有 `(symbol, trade_date)` 键也唯一。因此历史结果没有因为这处代码表述差异而改变，但新 runner 必须直接实现 prereg 的严格版本。

## 2. signal return、缺失与公司行动

`raw close / raw preclose - 1` 在已完成信号收盘时可知，开发期 355 行与冻结特征逐行算术一致，没有缺失/不合格信号行，也没有信号日公司行动。该定义因使用 raw 坐标，会让市场截面含有公司行动的机械价格变化：56 个信号日的 eligible 截面里有 530 个公司行动行；描述性排除这些行时，中位数最大仅变化 1.24bp，且没有改变任何 2% 分类。由于 prereg 明确锁死 raw 算法，这应作为经济限制披露，不能在验证时临时改成复权收益或排除公司行动。

缺失处理本身是 fail-closed：信号行缺失/重复/不合格即拒绝，市场行不合格则从截面排除，整日没有 eligible 行则拒绝，不允许补零或插补。runner 还必须明确做到：

- 市场截面存在任何重复 `(symbol, trade_date)` 时整日失败，不能让重复行改变权重。
- 每个信号分别以其 Asia/Shanghai 决策时刻检查所有市场行，不能只比较市场行自己的 `available_at <= decision_at`。
- 所有 120 个父级身份都输出且只有一个选择/拒绝原因，selected + rejected 必须精确守恒。
- 逐日报告 eligible 数和占比。prereg 没有冻结最低覆盖阈值，所以低但非零的覆盖只能披露，不能看到结果后新增 veto。

## 3. 与 V28R2 执行的绑定

父级 identity freeze SHA `8b61ca22…`、selected SHA `c439ea1a…` 与 prereg 一致；父级冻结 runner SHA 和当前文件 SHA 都是 `ed6365bd…`。这足以固定 120 个父级信号（其中 108 个声明为 executable）的来源身份，但不等于 Stage B 已经完整绑定。

CY-041/Stage-B 授权还必须在 Stage A 验证后绑定：精确的 V28R2 validation outcome 和所有 execution-daily 源；V29R3 runner 及全部传递性 replay helper；A67/H20/no-stop、每边 20bp、Main/ChiNext 各 K80；以及 Stage-A freeze、selected cohort 和 exact join 字段。结果联接不能只核对 `gap_id`，还应逐笔精确核对 symbol、signal/entry 时间、entry status/cal_idx、raw/coordinate 价格与因子、invalid-step、涨停价以及 T+1/跨期/涨停布尔量。任何 signal/entry/exit 超过 2024-12-31 都必须失败。

## 4. CY-040/CY-041 两阶段授权漏洞

当前 registry 中 `CY-040`、`CY-041`、Stage-A auth、Stage-B auth 均为零条，因此现状天然 fail-closed。注册前需要解决以下问题：

1. Stage B 必须在 Stage A 之后才注册，所以 Stage A freeze 不能冻结整个 registry 文件哈希；否则添加 CY-041 本身就会令 Stage A 失效。应冻结 CY-040 asset entry、Stage-A auth entry 的规范化值哈希和全部 bound fingerprints；Stage B 对它们做 scoped identity 比较，再独立核对 CY-041/auth。
2. prereg 指定了 Stage-A auth ID，却没有锁死 Stage-A purpose、CY-041 asset ID、Stage-B auth ID 和 Stage-B purpose。应在 Stage A 前用只涉及治理身份、不改变规则的 addendum 固定这些常量，runner 只能接受完全一致的记录，不能接受“兼容”的通用授权。
3. 通用 registry validator 尚不支持 V29R3 purpose；`RECORD_LEVEL_AVAILABLE_AT_PURPOSES` 也只有两种 issuer-risk purpose，且通用校验器不会校验阶段顺序、专用 flags、精确 artifact role 集合或一次性运行语义。注册前必须增加专用 validator contract，runner 仍须自行做完全相等检查。
4. 若 CY-040 只是指向三个完整 CY-033 年分区，它的 outcome-blind 性质只是程序纪律，不是信息隔离。优先把 CY-040 做成不可变的行/列缩减资产：只含父级信号日期和计算同期截面所需列。最低限度也要绑定经过审阅的显式安全列投影及 exact same-date predicate。
5. Stage A/B 必须分开调用，不能提供默认 `all` 模式。Stage B 在完整验证 Stage A 和两份 scoped auth 前不得解析、hash、打开或汇总 outcome path；测试应用 trap accessor 证明任一前置失败都不会触碰结果源。
6. “one fixed Stage-B run” 不能只靠可修改的 registry 文本声明。需要 absent-output 前置检查、结果访问前独占创建的 authorization-consumption receipt，以及独占、原子发布到独立输出根。

## 5. 固定阈值邻域 exact K80

以下只是在同一批已消费 2018–2021 的 355 笔 executable V28R2 outcomes 上，保持 A67/H20/no-stop/40bp 和 Main/ChiNext 各 K80 不变的敏感性检查。它不能用于重新选阈值。

|阈值|候选|K80 接受|年均接受|mean|win|severe10|平均持有|unique dates|date-equal mean|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|0%|44|44|11.00|7.139%|95.45%|0.00%|9.25|15|5.438%|
|1%|188|170|42.50|7.201%|97.06%|0.00%|7.38|26|5.567%|
|2%|265|202|50.50|7.278%|96.53%|0.50%|7.53|35|5.304%|
|3%|320|232|58.00|6.945%|93.53%|0.86%|8.55|44|4.214%|
|4%|341|247|61.75|6.717%|91.90%|2.02%|8.90|50|4.449%|

2% 对 3% 的逐年 accepted 为 `169/16/7/10` 对 `185/20/9/18`；逐年 mean 为 `7.5815%/4.8565%/8.2380%/5.3435%` 对 `7.5087%/4.4044%/6.5201%/4.1920%`。

去掉最大信号簇 2018-10-26 后重新跑容量：2% 为 139 笔、34.75/年、mean 6.878%、平均持有 7.68、34 个日期、date-equal mean 5.220%、severe10 0.72%；3% 为 179 笔、44.75/年、mean 6.271%、平均持有 8.64、43 个日期、date-equal mean 4.116%、severe10 1.12%。

因此，2% 不是收益曲线的悬崖点：1%→2%→3% 的整体收益变化平滑，2% 边界 ±10bp 只有 13 个候选，且没有候选精确等于 2%。真正 knife-edge 的是事后频率目标：2% 仅以 50.5/年跨过门槛，并高度依赖 2018-10-26。3% 虽增加样本数和日期覆盖，却在 mean、date-equal mean、胜率/尾损和持有上都更弱，去簇后仍不到 50/年；它不是支配性的“稳健版本”。

## 最终意见

保留 SHA `33595c6c…` 的 2% prereg，并继续明确其 post-hoc、集中度和 registered-row universe 限制；不要基于本次已消费开发结果退休 2%、改冻 3%。在 CY-040/CY-041、专用 purpose/validator、scoped identity、延迟结果访问、exact join 和一次性执行全部就绪前，不得运行任何验证阶段。

本审计没有修改 prereg、registry、核心策略代码或既有冻结产物；只新增本报告和配套机器 JSON。
