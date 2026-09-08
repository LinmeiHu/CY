# Opportunity Capital Competition V1

历史诊断研究；不构成 production authorization。

## 结论

- 机会质量表已从连续 Native intents/fills 建立；资金竞争使用同一决策日的请求额、实际 funded notional、现金与 gross context。未来收益标签全部隔离，当前版本没有合格行情面板，因此 ret/MFE/MAE 保留 NA。
- Native 账户的收益源仍以 ATRDR Bull、ATRDR Fast Bear、ATRDR Slow Bear、MCB、OGR、IFCGR、SMV6 分开观察；ATRDR aggregate 只作回溯核对。
- 以累计机会质量看，固定基础资本更有证据支持 ATRDR Bull、MCB、SMV6；OGR/IFCGR 的机会供给和收益密度较低，适合候选共享现金调用，但 IFCGR 与 OGR 的独立性仍需更强的配对证据。
- 没有预注册的因果 opportunity priority rule，不能把共享现金架构升级成可执行排序；P2/P3 和 Native/1.5x/2x 边际资本网格均明确标为诊断不可运行。
- 现金保留的经济价值只能在后续有合格 future-label 与竞争事件反事实后估计；本版不以回看结果建立优先级。

## 证据边界

- SMV6 冻结机会输入覆盖至 2023；2024–2026 不补零，保持缺失边界。
- 指标硬化没有重放账户、修改信号、仓位、成本、宇宙或 NAV；审计见 `output/metric_hardening_audit.csv`。
- 资本架构状态见 `output/architecture_diagnostic.csv`；边际资本状态见 `output/marginal_capital_diagnostic.csv`。

## 交付物

- `output/opportunity_master.csv.gz`
- `output/signal_quality_summary.csv` 与 `signal_quality_by_year.csv`
- `output/opportunity_supply_demand.csv`、`capital_demand_profile.csv`、`cross_strategy_interaction.csv`
- `output/ogr_ifcgr_pairing.csv`、`bull_mcb_relationship.csv`
- `output/metric_hardening_audit.csv`
- `output/architecture_diagnostic.csv`、`marginal_capital_diagnostic.csv`