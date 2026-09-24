# OGR 2026-09-17 至 2026-09-23 信号增量检查

状态：`TWO_NEW_DAILY_CANDIDATES_REJECTED_BY_V13_VAP`。9 月 24 日尚未收盘，因此仅计算到 9 月 23 日。用户已要求停止使用 QMT；本次补缺未调用 QMT 服务。此检查是 OGR 冻结规则的增量诊断，没有修改既有 9 月 16 日结果或策略参数。

冻结股票池 3,725 只。采用 Baostock 原始不复权日线做日线初筛，构建 PIT-B 输入。9 月 17、18、21、22、23 日共取得 18,565 个股票日，其中 17,855 日通过硬质量门槛。其余 12 只在 9 月 16 日以前已停止出现日线记录，没有在新增区间填零。原 9 月 7 至 16 日的 8 个 V13 候选均在新计算中保留。

新增区间有 10 个 V13 原始候选，其中 2 个通过 V27 及 V28/V28R1/V28R2 日线质量筛选：

| 股票 | 信号日期 | 缺口日期 | 缺口年龄 | 状态 |
| --- | --- | --- | ---: | --- |
| 600363.SH | 2026-09-18 | 2026-08-31 | 14 | V13 VAP 拒绝 |
| 603137.SH | 2026-09-18 | 2026-09-02 | 12 | V13 VAP 拒绝 |

分钟 VAP 是正式 OGR 入选的必要条件。已利用现有冻结规范档案、公开分钟数据及公开逐笔成交重建两股缺口前各 120×241 根记录，运行冻结的 `attach_v13_vap`，两股均未通过。`600363.SH` 的 inside/corridor 密度为 1.665833/2.136068，`603137.SH` 为 1.708478/1.567907；两项上限均为 1。因此本次增量的两个日线候选均**不是正式 OGR 信号**。源头与逐日对账见 `NON_QMT_MINUTE_RECOVERY.md`、`public_minute_source_manifest.json`、`public_minute_daily_reconciliation.csv` 和 `public_vap_metrics.csv`。

本机确有覆盖到 9 月 14 日及之后的日线，但未发现这两股都覆盖到该日的本地 1 分钟序列；本次只读取逐笔缺失行组，现有缓存不重复下载。公开逐笔与日线最大量额差异约 0.46%，未强行调整成交。Baostock 日线尚未完成独立来源重叠核验，9 月 17 日以后的公司行动事实尚未刷新。因此结论严格限于**本次日线输入下的两只新增候选**，不能称为全市场原生数据最终封印。

可审阅记录：`candidate_status.csv`、`status.json`、`stock_data_audit.json`。大体量原始输入保存在本目录 `cache/`，由 `.gitignore` 排除；哈希记录在 `status.json`。

冻结 VAP 复现命令：`PYTHONPATH=.:src:/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830/src python research/unified_opportunity_risk_v1/ogr_signal_check_20260924/recover_public_minutes.py`；随后对 `select_v28r2.parquet` 与 `cache/daily_with_snapshot.parquet` 调用 `ogr.attach_v13_vap(..., cache/public_minutes, cache/public_vap)`。本次输出 `cache/public_vap/v13_signals.parquet` 为 0 行。
