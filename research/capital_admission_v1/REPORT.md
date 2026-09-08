# Causal Capital Admission Closure V1

## FINAL_DECISION

BLOCKED_REQUIRED_PRECAPITAL_SOURCE_UNAVAILABLE

## Gate A

覆盖矩阵包含 63 个 strategy-year 单元；失败 3 个。

SMV6 在 2024、2025、2026 YTD 的连续 Native fills 存在，但已注册的 callback pre-capital producer 只到 2023。fills 是资金准入后的结果，不能倒推 legal opportunity population，因此不能把这些年份称为无信号，也不能继续 Gate B–H。

IFCGR 的 canonical Native `ifcgr_intents.parquet` 覆盖到 2026-08-03，已纳入覆盖核对；其 PIT-B 来源等级沿用上游，不升级。

## 阻断边界

任务在 Gate A 按硬规则停止：`BLOCKED_REQUIRED_PRECAPITAL_SOURCE_UNAVAILABLE`。未生成 economic dedup、shadow lifecycle、capital conflict、priority map、account shared-cash replay 或 marginal capacity 结果，避免在输入不闭合时发表伪结论。

详见 `output/strategy_year_coverage_reconciliation.csv` 与 `output/required_precapital_source_trace.csv`。