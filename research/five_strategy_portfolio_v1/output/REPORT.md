# 五策略经济增量、共同风险与固定资金配置研究 V1

## 一页决策摘要

研究状态：`COMPLETE`。主比较窗口为 **2018-01-02 至 2021-12-15（961 个共同交易日）**；由 OGR/IFCGR 的有效账户覆盖决定。组合类型严格为 `HISTORICAL_SLEEVE_NAV_COMPOSITE`。

| 问题 | 结论 |
| --- | --- |
| MCB_INCREMENT | **REDUNDANT_EXPOSURE | CAPITAL_INEFFICIENT** — qualified key overlap=1890/1904 MCB; MCB_unique=14; P1-R1 return=-0.069407; P2-R2 return=-0.069407; P1-R1 MDD=0.004015; P1-R1 utilization=-0.028875 |
| GAP_VARIANT | **OGR CORE_CANDIDATE | IFCGR INSUFFICIENT_EVIDENCE** — IFCGR rejects=8; avoided_negative=0; missed_winner=8; substitute fills=0; P2-P1 return=-0.001248 |
| BEAR_OGR_RELATIONSHIP | **INSUFFICIENT_EVIDENCE** — see route-specific exact/date/near/holding overlaps in family_analysis.csv |
| SMV6_DIVERSIFICATION | **RETURN_COMPLEMENT_CANDIDATE | DIFFICULTY_DIVERSIFICATION_INSUFFICIENT_EVIDENCE** — SMV6 mean on stock worst5%=-0.004605; tail_n=48; P1 minus leave-cash return=0.062805; MDD=-0.006117 |
| FAMILY_STRUCTURE | **ATRDR+MCB_BULL_CONFIRMATION | OGR+IFCGR_GAP | SMV6_ETF_ROTATION; BEAR-vs-OGR boundary unresolved** — mechanism labels with event, holding and account diagnostics |
| PRIMARY_RESEARCH_CANDIDATE | **R1** — R1 Sharpe=1.6402, return=0.4184, MDD=-0.0409; P1 Sharpe=1.6021, return=0.3490, MDD=-0.0368 |

## 主组合与预算对照

| 组合 | 累计收益 | CAGR | 最大回撤 | Sharpe | 最差5%日均值 | 平均资金利用率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| P1 | 34.90% | 7.87% | -3.68% | 1.602 | -0.75% | 12.41% |
| P2 | 34.77% | 7.85% | -3.69% | 1.596 | -0.75% | 12.41% |
| R1 | 41.84% | 9.25% | -4.09% | 1.640 | -0.86% | 15.29% |
| R2 | 41.71% | 9.23% | -4.09% | 1.635 | -0.86% | 15.30% |

P1 = 25% ATRDR + 25% MCB + 25% OGR + 25% SMV6；P2 用 IFCGR 替代 OGR。R1/R2 将 MCB 的25%预算交给 ATRDR。初始预算固定、子账户独立复利、不再平衡、不互借现金。

## 删除留现金与成本压力

### P1

| 对照 | 累计收益差（主组合-对照） | 最大回撤差 | Sharpe差 |
| --- | ---: | ---: | ---: |
| P1_WITHOUT_ATRDR_LEAVE_CASH | 16.40% | -0.84% | 0.202 |
| P1_WITHOUT_MCB_LEAVE_CASH | 9.46% | -0.86% | 0.019 |
| P1_WITHOUT_OGR_LEAVE_CASH | 2.75% | 0.08% | 0.117 |
| P1_WITHOUT_SMV6_LEAVE_CASH | 6.28% | -0.61% | -0.055 |

额外每次成交20bp的固定路径压力后：累计收益 30.48%（相对主结果 -4.42%），现金不足标记日合计 48。这不是重新执行现金约束回放。
### P2

| 对照 | 累计收益差（主组合-对照） | 最大回撤差 | Sharpe差 |
| --- | ---: | ---: | ---: |
| P2_WITHOUT_ATRDR_LEAVE_CASH | 16.40% | -0.84% | 0.206 |
| P2_WITHOUT_MCB_LEAVE_CASH | 9.46% | -0.86% | 0.021 |
| P2_WITHOUT_IFCGR_LEAVE_CASH | 2.63% | 0.07% | 0.111 |
| P2_WITHOUT_SMV6_LEAVE_CASH | 6.28% | -0.61% | -0.053 |

额外每次成交20bp的固定路径压力后：累计收益 30.36%（相对主结果 -4.41%），现金不足标记日合计 48。这不是重新执行现金约束回放。

## 证据解释

- `family_analysis.csv` 分开给出 ATRDR Bull/MCB 的共有与独有事件、OGR/IFCGR 否决、Bear/OGR 路线诊断，以及 SMV6 在股票参照最差日和前三个非重叠回撤阶段的结果。事件层百分比没有加总成资金金额。
- `profit_concentration.csv` 列出每个可精确归因股票策略最赚钱的五个信号日与五只证券；分母是全部正向成交利润，不用接近零的净利润。OGR/IFCGR 的现金分红计入已实现利润。SMV6 因部分卖出/再平衡无法形成无歧义的单事件利润，保持 NA。
- `risk_and_capital.csv` 保留全部策略对的全日/双方持仓相关性、双向最差5%条件收益、实际亏损天数、共同负收益与共同持仓样本数。零方差与缺失持仓返回 NA。最差5%采用收益升序、日期升序的确定性前 ceil(5%×N) 条。
- ATRDR 的历史、2024–2025、2026 三段独立初始化。后两段只在单段概况出现，未拼接、未参与受 OGR 限定的主组合。
- SMV6 只用有成本、整手、现金约束的本地封箱 NAV；原生 SuperMind 等价仍未验证。IFCGR 始终保持 PIT-B 标签。MCB/OAI 行为重建 provenance 没有升级。

## 局限与使用边界

这份结果可复现但不等于可投资，也不是独立前向验证。统一券商账户的整手、最低费用、同证券合并、公共现金池、容量和真实成交没有被证明；两个子账户持有同一证券仍按各自归属计账。旧研究已消费历史没有被包装成新 OOS。

## 唯一下一步建议

只将 **R1** 带入严格冻结、同口径的前向纸面执行：保留四个独立子账户和原始订单归属，先验证统一券商环境下的可成交性、整手/最低费用、同证券总敞口与实际现金占用；本轮不继续扫描权重。

## 复跑

```bash
PYTHONPATH=src /opt/anaconda3/bin/python research/five_strategy_portfolio_v1/run_five_strategy_portfolio_v1.py \
  --input-config research/five_strategy_portfolio_v1/input_config.json \
  --output-root research/five_strategy_portfolio_v1/output \
  --signal-start 2018-01-01 --signal-end 2026-08-03 --as-of 2026-08-03 --stage all
```
