# 已执行的复现流程

入口位于本任务独立工作树。全部命令只使用已登记2018–2023数据；不得自行扩大输入目录或年份。`common.py`显式固定外部产物目录，不依赖调用者当前目录猜测数据位置。

```bash
cd /Users/linmei/Documents/CY-worktrees/minervini-ashare-clean-ascent-20260908
bash research/minervini_ashare_clean_ascent/reproduce.sh verify
```

verify先只读核验artifact_manifest的输入、源码和冻结产物，随后运行语义测试、原始前缀/完整横截面测试，再实际重复执行全部62个账户。每个账户的NAV、trades、orders、audit、open_positions重新序列化到临时目录，与当前正式identity逐项比较SHA256；不覆盖原账户产物，不更新预期哈希来掩盖差异。重复执行只算核验，不增加情景数或历史复用数。

从已核验共同量价缓存重做账户与分析：

```bash
bash research/minervini_ashare_clean_ascent/reproduce.sh cached
```

从六个原始年度分区重建量价缓存，然后执行同一流程：

```bash
bash research/minervini_ashare_clean_ascent/reproduce.sh full
```

full和cached会重写本任务自己的派生缓存/账户；首次结果与各次修错前产物已单独保存于五个provisional归档。全量特征单进程运行，DuckDB限制单线程、3GB工作内存；原始数据与公共虚拟环境只读。检查日志区分实际执行阶段与命令说明；交付时的完整阶段及cached/verify实际结果见logs和manifest.json，不把写出命令本身算作执行成功。

前置资产：CY-006六个年度文件及原manifest；QD-010公司行动已登记文件；已完成shared-capital官方到账日期事实；本任务action_backfill.csv及发行人PDF原件。缺少必要事实立即失败，不降级为猜测，不自动读取封存区间。首次补齐已完成，正常复现不联网下载。五策略比较只读five_strategy_source_index所列历史NAV；缺少对齐产物不得替代成0相关或擅自重跑五策略。

运行环境：计算解释器`/Users/linmei/Documents/CY/.venv/bin/python`；精确运行库版本见runtime_versions.json。图形使用单独的外接盘plot_runtime，不修改公共环境，版本见同文件。原始数据不打入Git，发布的是可执行源码、合同、摘要和完整哈希索引；仅克隆仓库而没有本地授权数据不能凭空复现。

`finalize.py`从真实订单和审计流水独立重建现金；`supplement.py`从股数流独立重建每日市值与期末股数，审计合法报价、申报量和CAP10预算。统计归因排除公司行动的简化事件子集，与保留公司行动的真实账户明确分开。`write_report.py`仅读取最终核验表生成中文报告，不做排名训练或参数选择。

提交和推送事实不使用提交内自引用哈希。最终`END_HEAD`、`COMMIT`、远端核验值保存在外部`publication_status.json`并在交付消息给出，Git内manifest指向该记录。不会声称“尚未push”已经push成功。
