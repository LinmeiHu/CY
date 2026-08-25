# CYQ-GAME 当前会话交接（2026-08-24）

> 这是下一会话的当前事实源。先读 `/Users/linmei/Documents/CY/AGENTS.md`，再读本文。
> 不要重新审核已经确认的数据，不要重新设计底层三模型，不要启动重复任务。

## 1. 当前目标

当前只推进到 G3 前的数据准备：为 2020 年主板、创业板幸存者样本生成精确筹码策略特征，然后完成资产冻结、注册、一次软件门禁和 2020 年局部回归。

当前禁止：

- 不运行 2020–2023 参数研究。
- 不运行 2024–2026 重封验证。
- 不运行任何多年或组合回测。
- 不重新下载日线、分钟线、流通股本、行业或公司行动。
- 不重复实现 T+1、UNKNOWN_COST、三卖方模型、血缘追踪或压缩格式。

## 2. 正在运行的任务

截至 `2026-08-24 00:03:03 CST`：

- 目标股票：3,736 只。
- 已完成特征分片：1,321 只。
- 活跃主进程：PID 9786（外层 `uv` PID 9777）。
- 工作进程：10 个，均存活；当时子进程 CPU 合计约 668%。
- 临时残留文件：0。
- 任务没有停止；打印日志每完成 100 只才更新一次。

正在生成的不是日线、不是筹码库存，也不是回测，而是从已经完成的 v11 三模型筹码库存中提取 2020 年逐日策略特征：平均成本、p01/p10/p50/p90/p99、主峰、主导筹码带、ASR、CBW、集中度、峰数量、已知成本比例和三模型分歧。

完整启动命令如下，**进程仍存活时绝对不要再执行**：

```bash
cd /Users/linmei/Documents/CY
uv run python scripts/build_exact_10stock_overlay.py \
  --output data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/features \
  --symbols-file data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/symbols.txt \
  --primary-root data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/lineage \
  --secondary-root data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/lineage \
  --exact-start 2020-01-02 \
  --exact-end 2020-12-31 \
  --feature-start-year 2018 \
  --feature-end-year 2020 \
  --workers 10
```

### 2.1 新会话第一步：只检查，不重启

```bash
cd /Users/linmei/Documents/CY

ps -Ao pid,ppid,%cpu,%mem,rss,etime,state,command \
  | rg 'build_exact_10stock_overlay.py|multiprocessing.spawn' \
  | rg -v 'rg '

find data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/features/_exact_parts \
  -type f -name '*.parquet' ! -name '*.tmp.parquet' 2>/dev/null \
  | wc -l
```

- 若进程存在：继续等待，只报告动态分片数和失败信息。
- 若进程不存在且分片少于 3,736：才用上面的原命令断点续跑。
- 脚本启动时会识别已经存在且 schema 正确的单股分片，因此已完成股票不会重算。
- 不要同时启动第二个同输出目录任务；两个任务会争抢相同目标文件。

## 3. 已经完成且禁止重做的工作

### 3.1 2020 年筹码库存覆盖

- 2020 年仍在研究范围的主板、创业板股票：3,738 只。
- 精确 v11 筹码库存已覆盖：3,736 只，覆盖率 99.946%。
- 唯一未纳入的两只：`300894.SZ`、`605155.SH`。
- 两只都只在 2020 年最后/上市日存在单条日线，没有前态；原因码应保持为 `IPO_SINGLE_DAY_NO_PRIOR_STATE`，不应伪造筹码历史。
- 退市股票按用户要求暂不处理，明确接受幸存者偏差。

最终统一血缘目录：

```text
/Users/linmei/Documents/CY/data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/lineage/year=2020/parts
```

该目录有 3,736 个单股 Parquet。它由 3,714 个本轮新建文件和 22 个已注册、字节复用的精确文件组成；使用硬链接，未重复占用磁盘块。

股票清单：

```text
/Users/linmei/Documents/CY/data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/symbols.txt
```

### 3.2 已修复的确定性错误

以下错误已经修复，不要再次从头诊断：

1. 上市前没有流通股本时错误初始化：现在从第一条正流通股本记录初始化，之前日期不构造库存。
2. 公司行动后零保留率 destination `KeyError`：零质量目标不再进入迁移映射；`300729.SZ`、`300748.SZ` 已定向重建并通过。
3. `603733.SH` 在 2020-08-05 的成交量大于当时可见流通股本：
   - 原始日线和分钟成交量不改写；
   - 研究迁移算子按当日可见流通股本封顶，并保留 `TURNOVER_CAPPED_AT_FLOAT`；
   - 该记录只能是 B 级研究，不冒充严格 PIT-A；
   - T+1 同日再卖仍为 0，质量守恒误差为 0。
4. fallback 分支曾绕过已经缩放的 `PreparedMinutePath`：现已统一使用准备后的分钟路径。
5. 零经济质量回放除零和零目标迁移错误已修复。

主要代码：

- `/Users/linmei/Documents/CY/scripts/build_real_chip_year.py`
- `/Users/linmei/Documents/CY/src/cyq_game/strategy/chip_lineage.py`
- `/Users/linmei/Documents/CY/scripts/build_exact_10stock_overlay.py`
- `/Users/linmei/Documents/CY/tests/test_real_chip_storage.py`
- `/Users/linmei/Documents/CY/tests/test_chip_lineage_resolver.py`

### 3.3 性能和内存改造已经完成

不要再回到“每股大对象、全市场一次装入内存、重新压缩”的旧路径：

- 底层库存已经是 v11 紧凑算子日志。
- 特征生成按股票独立分片，可断点续跑。
- 父进程不再保存全市场 `list[dict]`。
- 当前使用 10 个股票级进程；同一股票内日期仍顺序推进。
- DuckDB 合并阶段限制 8 GiB，并关闭插入顺序保留。
- `chip_lineage.py` 已优化 local-id 老化、排序键、单目标迁移和零保留弧。
- 单股 profiler 中 `_advance` 从约 8.78 秒降到约 4.94 秒，总 profile 从约 11.57 秒降到约 7.56 秒。

Mac 为 10 核、32 GiB。最近一次检查整机 CPU 空闲率为 0%；不要仅因单个 Python 进程不足 100% 就盲目增加 worker。进程在同时做 Parquet 读取、解压和 Python 计算；若系统已有 0% idle，更多 worker 只会增加内存压缩和磁盘争用。

### 3.4 已完成测试证据

已完成的定向证据：

- 20 股 2020 年 smoke：`panel_rows=4860`、覆盖率 `0.9578189`、`eligible_rows=3028`、`label_rows=4140`、`signals=2`、`events=82`，退出码 0。
- 筹码状态与存储相关 42 项测试通过。
- 血缘解析器 5 项定向测试通过。
- 相关修改的 ruff 定向检查通过。

20 股命令曾成功执行：

```bash
uv run cyq-game strategy validate \
  --stage year \
  --config configs/markup_retest_week20_v1.yaml \
  --threads 10 \
  --no-reuse
```

这些是之前阶段证据，不代表本轮所有未提交代码已经完成最终软件门禁。

## 4. 当前数据语义

- 原始日线 OHLC、成交量和换手保持未复权事实，不被筹码重建覆盖。
- 公司行动在生效日作为库存/价格坐标事件处理。
- `CYQK_pre` 是当日成交迁移前库存。
- 当日新增筹码不能当日卖出，T+1 由数据流保证。
- `UNKNOWN_COST` 单独保留，只能被后续真实成交逐步替换。
- 三个卖方模型为 `UNIFORM`、`DISPOSITION`、`ACTIVE_STICKY`；输出中位中央估计和模型区间。
- 这些模型是不可观测卖方来源的假说，不是真实庄家账户识别。
- 当前资产等级只能是 `B_RESEARCH_ONLY`，不能用于严格 PIT-A 或实盘声明。
- `603733.SH` 的迁移封顶属于因果研究近似，必须保留质量原因码。

## 5. 当前任务完成后的最短顺序

### 5.1 确认特征生成完整

正常完成后应出现：

```text
data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/features/exact_features.parquet
data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/features/year=2018/data.parquet
data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/features/year=2019/data.parquet
data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/features/year=2020/data.parquet
```

成功合并后 `_exact_parts` 会被脚本删除。若 3,736 个分片已齐但最终合并阶段失败，直接重跑同一命令；它只会继续合并，不应重算单股分片。

只做一次必要检查：

```bash
uv run python - <<'PY'
import duckdb

p = 'data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/features/exact_features.parquet'
con = duckdb.connect()
print(con.execute(f'''SELECT
  count(*) AS rows,
  count(DISTINCT symbol) AS symbols,
  min(trade_date) AS start_date,
  max(trade_date) AS end_date,
  count(*) FILTER (
    WHERE research_valid AND (
      model_spread_cost_p50 IS NULL OR
      model_spread_cost_p90 IS NULL OR
      model_spread_main_peak IS NULL
    )
  ) AS missing_spread
FROM read_parquet('{p}')''').fetchone())
print(con.execute(f'''SELECT count(*) FROM (
  SELECT symbol, trade_date, count(*) AS n
  FROM read_parquet('{p}')
  GROUP BY symbol, trade_date
  HAVING n <> 1
)''').fetchone())
PY
```

门禁：`symbols=3736`、重复键 `0`、`missing_spread=0`。不要为了得到固定总行数补上市前或退市后的空白。

### 5.2 冻结 manifest

`scripts/freeze_exact10_asset.py` 目前只接受 `--symbols`，下一会话应只做一个小改动：增加 `--symbols-file`，读取方式与 `build_exact_10stock_overlay.py` 相同。不要把 3,736 个股票直接展开到命令行，也不要另建冻结框架。

建议资产编号：

- 精确特征：`CY-017`
- 精确血缘：`CY-018`

建议命令：

```bash
uv run python scripts/freeze_exact10_asset.py \
  --root data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11 \
  --symbols-file data/registered_inputs/CY-017-MARKUP-RETEST-MAIN-CHINEXT-2020-V11/symbols.txt \
  --feature-years 2018 2019 2020 \
  --lineage-years 2020 \
  --feature-manifest-id CY-017-MAIN-CHINEXT-2020-FEATURES-V11-20260824 \
  --lineage-manifest-id CY-018-MAIN-CHINEXT-2020-LINEAGE-V11-20260824 \
  --coverage-start 2018-01-02 \
  --coverage-end 2020-12-31
```

manifest 必须记录原始未复权价格、因果公司行动、T+1、B 级研究、三卖方模型和精确文件哈希。最终 component assets 要包含实际使用的日线、分钟、公司行动、流通股本和被复用的已注册小样本血缘；不要静默替换来源。

### 5.3 注册资产

仅在两个 manifest 成功生成后，把 `CY-017` 和 `CY-018` 写入：

```text
/Users/linmei/Documents/CY/configs/data_asset_registry.json
```

要求：

- `status=RESEARCH_CONDITIONAL`
- `pit_grade=B`
- 允许用途只到 2020 主板/创业板局部回归
- 阻止 PIT-A、实盘、2021+ 和未声明股票用途
- 特征资产绑定血缘资产，缺一即失败
- manifest 路径和 SHA-256 必须准确

### 5.4 新建 2020 全市场配置

从 `configs/markup_retest_week20_v1.yaml` 最小复制一份，例如：

```text
configs/markup_retest_main_chinext_2020_v1.yaml
```

只替换：

- `chip_feature_asset_id: CY-017`
- `chip_lineage_asset_id: CY-018`
- 两个资产路径
- 输出路径
- `year` 阶段为 `2020-01-02` 至 `2020-12-31`

year 阶段可以不列 3,736 个 symbols，让面板从注册范围取交集；若运行路径必须显式限制，再给策略 stage 配置增加一个最小的 `symbols_file` 读取功能。不要把长股票列表复制进 YAML。

### 5.5 一次完整软件门禁

所有本轮代码修改完成后只跑一次：

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src/
```

记录三个退出码。不要在每个小修改后重复跑完整门禁。

### 5.6 只跑 2020 年局部回归

```bash
uv run cyq-game strategy validate \
  --stage year \
  --config configs/markup_retest_main_chinext_2020_v1.yaml \
  --threads 10 \
  --no-reuse
```

只报告：

- 主板、创业板每日有效覆盖率，门槛 95%。
- 总股票数、有效股票数和唯一排除原因码。
- 信号数量和生命周期事件数量。
- 是否存在静默丢弃。
- wall time、CPU 利用率和主要热点。

如果 2020 局部回归失败，先针对唯一失败原因修复；不要跳到 2020–2023 或回测。

## 6. 不要被旧文档带回循环

- `docs/CHIP_REBUILD_FAST_ALGORITHM_HANDOFF.md` 是早期性能改造建议，不是当前执行状态。三模型、T+1、UNKNOWN_COST、紧凑存储、多进程和断点续跑已经存在，不要照它从 P0 重新实现。
- `docs/CHIP_STATE_REBUILD_V2_DESIGN.md` 是设计背景，不是待办清单。
- `docs/MARKUP_RETEST_10STOCK_DIAGNOSTIC_20260823.md` 是十股诊断证据；它说明策略语义修过哪些问题，但不能替代 2020 全市场局部回归。
- 不要重新做 BaoStock/QMT 数据盘点、行业补齐、退市股处理或旧的 3,621/477/262 缺口审计。
- 不要在当前阶段继续压缩库存文件；当前用户接受七年筹码数据总量约 250 GB，优先保证计算速度。

## 7. 工作区与 Git

- 当前分支：`main`
- 当前 HEAD：`61a310c Add one-week coverage labels and reduce audit output`
- 远端：`origin/main` 同一提交。
- 工作区有大量未提交修改和未跟踪文件，其中既有本轮改动，也可能有用户先前工作。
- 禁止 `git reset --hard`、`git clean`、覆盖式 checkout 或批量删除。
- 在没有逐文件确认前不要提交全部工作区。

当前关键未跟踪文件包括策略目录、筹码 v2/v11 实现、构建脚本、测试和诊断文档；不能因为未被 Git 跟踪就当作临时垃圾。

## 8. 给下一会话的可复制指令

```text
阅读 /Users/linmei/Documents/CY/AGENTS.md 和
/Users/linmei/Documents/CY/docs/CURRENT_SESSION_HANDOFF_20260824.md。
先检查现有 build_exact_10stock_overlay.py 进程和 _exact_parts 分片数；进程存在时禁止启动重复任务。
接管当前 2020 年 3736 只主板/创业板股票精确筹码特征生成。完成后按交接文档顺序：
最小验证 -> 给 freeze_exact10_asset.py 增加 symbols-file -> 冻结 CY-017/CY-018 -> 注册资产 ->
新建 2020 全市场配置 -> 一次 pytest/ruff/mypy -> 仅运行 2020 年局部回归。
不要重新审核数据，不要重建三模型，不要重新压缩，不要启动 2020–2023、多年或组合回测。
每次只汇报做了什么、当前进度、失败原因和下一步；不要重复已完成工作。
```
