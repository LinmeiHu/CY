# CY 筹码重建极速化交接文档

> 用途：直接交给主 session 执行。本文只处理筹码重建性能，不重新审核已确认的数据，不修改策略语义，不启动年度、全市场或回测任务。

## 1. 结论

当前慢点已经定位，不是电脑必须重启，也不是 20 股一周验证本身慢，而是长历史触发了当前实现的渐近热点：

- 单股剖析约 36 秒，其中迁移核心约 21 秒、输出编码约 10.4 秒。
- 单股出现约 1.52 亿次 Python 调用。
- 主要重复为逐筹码格 Python 对象操作、逐日老化与字典归并、三模型重复查找，以及每天重复排序和构造输出字典。

现有代码已经具备以下能力，禁止重新实现或重新论证：

- `PreparedMinutePath`：同一股票同一天的分钟路径可供三模型共享。
- 均匀、处置效应、活跃/黏性三种卖方模型。
- T+1、UNKNOWN_COST、公司行动、质量守恒。
- 按股票多进程、动态任务分块。
- 20 日检查点、日算子/源数据回放、相邻年份状态续接。

最快且风险最小的方案是：**保留公开接口和模型规则，用紧凑数组替换热循环中的 Python lot/list/dict；将三种模型分别化简到它们真正需要的充分统计量；用 Numba 编译分钟迁移内核；输出按列批量编码。**

当前环境已安装 `numba 0.61.0`。旧 NumPy/Python 路径保留为小样本正确性 oracle，不再作为全量运行后端。

## 2. 严格范围

本轮只允许修改：

- `src/cyq_game/chip/migration_v2.py`
- 必要时新增一个私有数值内核文件，例如 `src/cyq_game/chip/_migration_kernel.py`
- `scripts/build_real_chip_year.py` 中的状态编码、批量输出和计时
- 与上述改动直接相关的测试
- `pyproject.toml` 中明确声明性能依赖（若正式运行路径依赖 Numba）

本轮禁止：

- 重新盘点、下载、修补或审核日线、分钟线、行业、流通股本和公司行动数据。
- 修改筹码模型规则、参数、价格网格、卖方假设、公司行动语义或策略生命周期。
- 再造第四套筹码模型或通用框架。
- 启动一年、2018–2026、全市场特征生成或任何回测。
- 用降低精度、删掉三模型、缩短历史、丢弃 UNKNOWN_COST、弱化守恒来换速度。
- 每个小改动都跑完整软件门禁。

## 3. 必须保持不变的语义

1. 原始未复权 OHLC、成交量和换手事实不可改写。
2. `CYQK_pre` 是当日成交迁移前库存；当日新增筹码不得在当天再次卖出。
3. 公司行动在生效日对库存、成本、现金和价格坐标一致变换；不得拿复权价格替代库存事件。
4. UNKNOWN_COST 单独保存，只能被后续真实成交逐步替换。
5. 三种卖方模型都必须保留，输出中央估计和模型分歧。
6. 股票状态是跨日连续状态。下一日必须直接承接上一日 post-state；相邻年份必须承接上一年终态，禁止每年重新从 2018 年计算。
7. 筹码质量和血缘账本必须守恒；不得通过归一化掩盖误差。
8. 每条结果继续携带 `decision_at`、`available_at`、输入 `snapshot_id`、模型版本和当前存储版本。

公司行动坐标专项校验保留 `605507` 在 `2026-05-29` 的已知送转样例。

## 4. 目标数据结构：稀疏 SoA，而不是 Python 对象

热循环内部不再维护 `_WorkingLot` 对象列表。每个模型维护一个按稳定键排序的稀疏 Struct-of-Arrays：

```text
local_id            uint32
cost_bucket_id      int32
holding_days        uint16       # 上限仍沿用现有定义
sensitivity_id      uint8        # neutral / active / sticky
shares              float64
acquisition_cost    float64       # UNKNOWN 用独立 mask/池，不用 NaN 参与 hazard
economic_break_even float64
initial_units       float64
cash_dividend       float64
unknown_mask        bool
```

要求：

- `shares`、质量守恒和公司行动计算继续使用 `float64`。
- 数组在正常交易日保持稳定键有序；不要每天构造对象、字符串、tuple 或 dict。
- 持有期老化使用一次向量操作：`age = min(age + 1, max_age)`。
- 正常日只有达到持有期上限的单元格可能发生归并；只归并这些单元格。
- 公司行动导致成本桶重映射时才进行全量稳定排序与 `reduceat` 归并。
- 当日买入先按目标成本桶和敏感度聚合，作为独立的 `new_today` 数组；卖方迁移完成后才追加到 post-state。
- 仅在公开 API、检查点或调试输出边界物化 `InventoryCell`；分钟热循环禁止物化。

不要改成覆盖全价格空间的巨大 dense cube。跨八年存在送转和宽价格范围，稀疏有序数组更稳妥，也不会把内存压力转成 swap。

## 5. 最快的精确迁移算法

### 5.1 每日只准备一次输入

分钟数据只转换一次为连续数组：

```text
minute_price[m]
minute_transfer_shares[m]
buyer_bucket[m]
```

同时一次性生成当日买方聚合结果。三个卖方模型共享这些数组、公司行动结果和前一日库存视图，禁止各自重新解析 DataFrame、日期、价格桶或快照标识。

### 5.2 均匀卖方模型：一个标量

均匀模型中所有前日合格库存的卖出倾向相同，所以分钟级逐单元格循环可精确化简为：

```text
eligible = sum(previous_shares)
sold = min(sum(minute_transfer_shares), eligible)
retention = 1 - sold / eligible
post_previous_shares = previous_shares * retention
```

这与逐分钟等比例扣减等价；当日新增库存不进入 `eligible`。复杂度从 `O(minutes × cells)` 降为 `O(minutes + cells)`。

### 5.3 活跃/黏性模型：三个池

该模型的 hazard 只依赖敏感度，不依赖成本和持有期。因此先汇总 neutral、active、sticky 三组前日可卖库存，使用 240 分钟路径只更新三个标量池，并在组耗尽时执行现有 water-filling 规则：

```text
remaining_by_sensitivity[3]
```

得到三个日留存率后，只对原数组乘一次。复杂度为 `O(minutes × 3 + cells)`，不得继续逐分钟扫描所有筹码格。

### 5.4 处置效应模型：唯一 hazard 组

处置效应 hazard 依赖分钟价格和现有定义中的 acquisition cost。先对 acquisition cost 完全相同的单元格分组；UNKNOWN_COST 为单独一组。对唯一 cost 组运行分钟路径和精确 water-filling，得到组留存率，再一次性映射回所有单元格。

若同成本组数量接近单元格数量，也不得退回 Python 循环；分钟 × cost-group 的循环必须在一个 Numba `@njit(cache=True, nogil=True)` 内核里完成。内核直接接收连续 `float64`/整数数组，内部复用预分配工作区，不在每分钟分配临时数组。

复杂度从 Python 的 `O(minutes × cells)` 变为编译后的 `O(minutes × unique_cost_groups + cells)`。不能通过价格近似分桶改变当前 acquisition-cost hazard；只有完全相同的 hazard key 才可共享。

### 5.5 T+1 的实现方式

卖方内核只接收 `previous_eligible_state`。`new_today` 永远不传给卖方内核：

```text
previous post-state
    -> 次日老化/公司行动
    -> 三模型卖方留存
    -> 追加当日买方聚合
    -> current post-state
```

这样 T+1 是数据流结构保证，而不是事后检查修正。

### 5.6 公司行动

公司行动日先对 previous-state 做向量化坐标变换，再进入卖方内核：

- 现金分红更新 `economic_break_even` 和现金账本，不改写原始 OHLC。
- 送转/拆并股更新 shares、acquisition cost、break-even 和 cost bucket。
- 配股、解禁或流通股本变化按现有事件规则进入库存。
- 事件后执行一次稳定排序和归并；非事件日不得重复做这一步。

## 6. 老化、血缘和锚点复用

底层每日库存仍与策略生命周期分离。本轮不在重建阶段创建策略锚点。

每日迁移需要保存的核心是：

- 稳定 cell/local id。
- 前日单元格到当日单元格的留存与目标映射。
- 当日新增质量。
- 定期完整检查点。

同一卖方模型中，同组留存率只计算一次。血缘追踪通过“源 cell × 留存率 × destination id”回放，不要为每个未来策略参数复制每日筹码库存。

策略锚点缓存键仍应是：

```text
(symbol, anchor_date, current_date, seller_model_version)
```

不同参数若产生相同锚点可以共享追踪；锚点日期不同不得错误复用。本轮只保证底层算子足以支持该追踪，不实现或改造策略状态机。

## 7. 输出编码必须从 10.4 秒降下来

当前每日 `dict -> sort -> list -> Arrow` 路径应替换为：

1. 状态数组始终按数值键稳定有序。
2. 按 `cost_bucket_id` 使用 `reduceat`/连续段聚合一次得到价格分布。
3. p10/p50/p90、均价、主峰、集中度、ASR 等从同一个累计质量数组一次性计算。
4. 同一日同一模型的排序结果、累计和与峰值索引只生成一次，供所有输出字段共享。
5. 为一个 symbol/task 预分配列式 buffer，批量构造 Arrow Table；不要逐行构造大型 Python dict。
6. 只在既定 20 日间隔、首日、末日及公司行动必要点写完整检查点；普通日继续写紧凑算子/回放定位。
7. Parquet 继续使用现有压缩与 schema；本轮不通过删除底层信息压缩磁盘。

目标是输出编码占总耗时不超过 20%。

## 8. 并行方式

- 并行单位只按股票/股票小块；同一股票的日期必须顺序推进。
- 不得把同一股票的不同年份并行，因为后一年依赖前一年终态。
- 每个 worker 连续处理若干股票，减少进程启动和 JIT 初始化开销。
- Numba 内核本身不使用 `parallel=True`；外层已有多进程，避免双重并行和内存带宽争抢。
- 启动 worker 前设置 BLAS/OMP 线程数为 1，避免每个进程再开线程。
- 用 4、6、8、10 个 worker 做固定基准，选择“吞吐最高且无 swap”的数量，不以 CPU 100% 作为唯一目标。
- 相邻年份必须通过现有 resume 机制读取上一年精确终态；源文件和 staging 未变化时不得重复预热和重复 staging。
- 动态任务块继续使用现有 `--symbols-per-task`，只根据基准调整尾部负载，不重写调度器。

如果出现 swap、内存压力红色或压缩内存持续增长，先减少 worker；重启电脑不是算法的一部分。只有实测 CPU 频率因温度持续大幅下降时，散热才是次要处理项。

## 9. 实施顺序

### P0：冻结基准，不改数据

使用固定的 20 股一周样本和固定的 100 股一年样本。记录：

- wall time、CPU time、峰值 RSS、输出大小。
- migration、state canonicalization、output encoding 各自耗时。
- Python call count。
- 股票日吞吐量。

JIT 首次编译时间单独记录，不计入稳态吞吐；先预热一个极小样本，再正式计时。

### P1：只替换迁移热内核

1. 在现有 `DailyMigrationEngine` 后面增加私有 packed backend，不新增第二套公开规则。
2. 先实现均匀标量路径和活跃/黏性三池路径。
3. 再实现处置效应 Numba cost-group 路径。
4. 旧路径保留为测试 oracle；生产 builder 显式使用 fast backend。
5. 对 20 股一周逐日逐模型对比 old/new，不先改输出格式。

### P2：替换状态老化与归并

1. `_WorkingLot` 只留在边界，日循环改用稀疏 SoA。
2. 老化向量化，正常日避免全量排序。
3. 买方一次聚合，三模型共享买方价格桶结果。
4. 公司行动日才全量重映射和归并。
5. 再跑 20 股一周一致性与 profiler。

### P3：列式批量输出

1. 消除逐行大型 dict 和重复 profile 排序。
2. 预分配列 buffer，按 symbol/task 批量写 Arrow/Parquet。
3. 保持当前 schema、storage version 和回放能力。
4. 再跑 20 股一周和 100 股一年基准。

### P4：只做必要门禁

定向门禁通过后，阶段末只跑一次：

```bash
pytest -q
ruff check .
mypy src/
```

本轮不得在 P0–P3 中间反复跑完整软件门禁。

## 10. 正确性门禁

20 股一周必须同时通过：

- 行数、日期、股票、模型集合一致。
- `CYQK_pre`/post 的 T+1 关系一致，当日新增筹码同日再卖为 0。
- 每日三模型筹码质量、UNKNOWN_COST、现金和公司行动账本守恒。
- old/new 的卖出量、模型库存和核心筹码指标在现有数值容差内一致；不得仅比较最终一日。
- 公司行动前后价格坐标一致，包括 `605507` 的已知样例。
- 1 worker 与最终选定 worker 数在 canonical sort 后结果一致。
- 现有相关测试继续通过；此前的 28 个定向测试不得退化。

允许因为浮点运算顺序变化出现容差内差异，不要求 Parquet 二进制字节完全相同；但原因码、有效性、日期、模型、质量守恒和事件语义必须相同。

## 11. 性能门禁

先完成 100 股 × 1 年固定基准，达到以下条件才允许主 session 提议扩大：

- 稳态总耗时目标 `<= 60 秒`，硬门禁 `<= 120 秒`。
- 相比当前实现，Python call count 至少降低 95%。
- 输出编码占总耗时 `<= 20%`。
- 峰值内存不触发 swap；10 worker 总 RSS 不超过物理内存的 70%。
- 20 股一周正确性门禁全部 PASS。

若未达到 120 秒，禁止启动年度任务，按 profiler 只处理第一热点：

- migration 仍占 >60%：检查是否仍在 Python 层逐分钟/逐 cell，或 Numba 内核是否 object mode。
- canonicalization 占 >20%：检查是否每天全排序、重算稳定 id 或构造 dict。
- output 占 >20%：检查是否仍逐行 dict、重复排序或重复序列化。
- CPU 利用率低且 I/O wait 高：修 staging/批量写，不增加 worker。
- RSS/压缩内存增长：减小 task chunk 或 worker 数，不继续堆并发。

## 12. 全量耗时估算公式

不能再用“20 股一周 3.884 秒”线性外推，因为它没有覆盖长期状态膨胀和年度输出。必须使用通过门禁后的 100 股一年稳态基准：

```text
stock_day_rate = processed_stock_days / benchmark_wall_seconds
estimated_seconds = total_target_stock_days / stock_day_rate
estimated_seconds *= 1.15  # staging、长尾和年度边界余量
```

同时报告 4/6/8/10 worker 的实测吞吐，不用理论核数推算。只有 P4 全部通过后，主 session 才能给出 2018–2026 的可信 ETA；本文不授权启动该任务。

## 13. 主 session 必须交付的证据

1. 修改文件路径及说明。
2. old/new 20 股一周逐日对比文件。
3. 100 股一年 before/after benchmark JSON。
4. before/after profiler，至少列出 migration、canonicalization、encoding、I/O。
5. 1 worker 与选定 worker 数的一致性结果。
6. `pytest -q`、`ruff check .`、`mypy src/` 的命令、退出码和 PASS/FAIL。
7. 基于实测股票日吞吐计算的全量 ETA。
8. 明确声明没有重新审核数据、没有启动年度全市场生成、没有运行回测。

## 14. 可直接复制给主 session 的执行指令

```text
阅读 docs/CHIP_REBUILD_FAST_ALGORITHM_HANDOFF.md，并严格按 P0→P4 执行。

本轮只优化现有筹码重建链路。禁止重新审核、下载或修补已经确认的数据；禁止修改策略；禁止启动年度、2018–2026、全市场生成和任何回测。现有 PreparedMinutePath、三模型、多进程、检查点和 resume 能力不得重复实现。

先冻结 20 股一周和 100 股一年基准。用稀疏 SoA 替代热循环中的 Python lot/list/dict；均匀模型化简为一个日留存率；活跃/黏性模型只运行三个敏感度池；处置效应按完全相同 hazard key 分组并在 Numba nopython 内核中执行分钟 water-filling；当日买入独立保存以结构保证 T+1；公司行动只在事件日重映射。随后把每日输出改为一次 profile 聚合和列式批量编码。

每完成一个性能阶段只跑相关定向测试和 profiler，不反复跑完整门禁。只有 20 股一周逐日正确性全部 PASS，且 100 股一年 <=120 秒、目标 <=60 秒、无 swap，才运行一次 pytest -q、ruff check .、mypy src/。若基准未达门禁，只根据 profiler 修第一热点，不得扩大任务。

完成后提交：修改路径、old/new 对比、before/after profiler、100 股一年基准、内存与 worker 扫描、所有命令退出码，以及按实测股票日吞吐计算的全量 ETA。不要启动全量。
```
