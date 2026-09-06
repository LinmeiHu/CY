# 五策略边际价值与资金组合研究 V1

截至 2026-08-03；所有组合均为 `HISTORICAL_SLEEVE_NAV_COMPOSITE`，不是统一订单级回测。

## 核算结论

SMV6 shadow 账户有 282 个负现金日，最低现金 -0.169411，且最大 gross exposure 1.051782。现有资料没有可安全复用的状态回放以局部重放成交，故 `SMV6_ACCOUNTING_BLOCKED`；旧 shadow 曲线不进入主组合。A/B 仅给出 SMV6 的 25% 留现金的缩减版本，SMV6 边际贡献 `NOT_ESTIMABLE`。

## 直接回答

1. ATRDR 牛市路线和 MCB 的精确键匹配结果见 `pairwise_increment.csv`；它只识别同证券同信号日，不能声称穷尽经济事件。MCB 是 V65 的严格跨板确认质量配置，ATRDR 牛市路线不是其父子替代。
2. OGR/IFCGR 的保留、否决机会仅按可读取 2022--2024 账本键匹配描述；没有将父策略价格倒用于子策略。
3. ATRDR 两条熊市路线与 OGR 的共同日期/事件同样只以键匹配报告；共同亏损以 `overlap_and_risk.csv` 的日账户指标为准。
4. SMV6 账户不可用于无杠杆净收益主比较，不能据此主张改善股票策略困难阶段。
5. 每个已合格子账户相对留现金的固定权重删除对照在 `portfolio_comparison.csv`；SMV6 为 `NOT_ESTIMABLE`，非零贡献。

成本模型各自冻结且不完全一致（SMV6 为零费率 shadow），因此未混入 SMV6，也未做额外 20bp 压力（股票逐日成交额口径不统一）。最优先下一步：在不改变 SMV6 状态机的条件下，取得能重放候选、持仓和现金约束的原生执行账本。
