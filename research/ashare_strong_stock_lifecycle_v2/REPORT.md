# A股原生强势股生命周期 V2

## 裁决：STRONG_STOCK_LIFECYCLE_V2_NOT_SUPPORTED

本轮使用 V1 已形成的 85,966 个事件身份和授权 CY-006 PIT-B 日线缓存；动态 peer 成功覆盖 85,168 个事件，首次 episode pressure 为 62,353 个。2020--2023 是已消费开发样本，2018--2019 仅 warmup，绝非 OOS、独立验证或生产证据。

## 主要结果

- Dynamic co-movement peer 的 trailing synchrony 明显高于静态 PIT 行业基准：平均 leader-peer correlation 0.746 对静态行业 basket 0.391，coverage 0.986；平均 peer 行业数 13.1、board 数 2.5。这支持它作为“共同交易群”表示，等级只到 L2 机制线索，不代表收益信号。
- Episode resilience 没有稳定的未来增量。simple resilience pooled Q5-Q1=-0.357%，residual resilience pooled Q5-Q1=-0.189%；年度 high-minus-low 在 2020--2023 分别见 `annual_stability.csv`，方向反转，且 residual 控制回归仍缺少独立 prior drawdown、volatility、float market cap 和显式 market-state，因此不能升级为 L2/L3。
- Common landmark 的 early re-acceleration 没有优于 resilience-only：simple/residual 两个版本的 G3 均低于 G2；G4 full repair 也未提供额外增量。所有 outcome 均从 L=P+4 后的 L+1 开始，未倒填 late repair。
- Supply absorption 未运行。resilience 没有达到稳定的 L2 机制门槛，继续构造 score 会变成条件救援。

## V1 叙事更新

静态行业失败可由题材跨行业解释；动态 peer 确实更接近共同同步群，但“更像共同交易群”没有转化成稳定的 leader second-leg 预测。V1 的单日 resilience 弱线索在完整 episode 和 common landmark 下没有升级；Repair、limit-up/turnover 主变量仍关闭。

## 账户与后续

没有运行现金账户、past-only 或 forward shadow；这是显式 account gate closure，不是缺失回测。当前 price/volume lifecycle family 的研究优先级应降低，保留 dynamic peer 的描述性证据和 resilience 诊断记录。

## 数据边界

授权输入缺少独立 prior-drawdown、volatility、float-market-cap 和 explicit-market-state 字段；本报告不以已有字段静默替代它们。

## 最终问题逐项回答

1. V1 静态行业可能失败，因为实际题材资金可以跨传统行业；V2 的动态 peer 证据支持这一表示层解释。
2. 是。动态 peer 平均同步相关性约 0.746，静态行业 basket 约 0.391，动态覆盖约 0.986；它更接近共同交易群，但只是表示质量结论。
3. 有意义的地方是识别了可重复的共同压力 episode（62,353 个首次 pressure 事件，平均 pressure z 约 -1.50）；它没有证明 second-leg 收益预测力。
4. 没有稳定信息。simple resilience 的 pooled Q5-Q1 为 -0.386%，residual resilience 为 -0.223%；年度方向反转。
5. 未证实超出 RS、beta、volatility、liquidity、size。partial OLS 仍缺少 prior drawdown、独立 volatility、float market cap 和 explicit market state，不能把残差系数当增量确认。
6. 没有。simple resilience 的 G3 比 G2 低约 0.223 个百分点；residual 版本也低约 0.025 个百分点。
7. 没有。G4 full repair 的 simple 后 10 日均值约 -0.406%，低于 G2 的约 +0.295%；residual G4 约 -0.408%，低于 G2 的约 +0.304%。
8. 未运行。Resilience 未达到稳定 L2，故没有为了挽救假说构造 absorption score。
9. 2020/2021/2022/2023 的 resilience high-minus-low：simple 为 +0.262%、-0.255%、-0.425%、-0.434%；residual 为 +0.670%、+0.013%、-0.549%、-0.248%。
10. 未运行 past-only；没有可通过门槛的预测性 L2 机制。
11. 事件分布不由单一股票主导（resilience 高组覆盖约 4,679--4,688 只股票、939 个独立日期），但这不抵消年度反转和 G3/G4 失败。
12. 真正被否定/关闭的是 V1 静态行业升级、单日 resilience 交易化、Full Repair、limit-up/turnover 主变量；V2 dynamic peer 只保留为描述性机制线索。
13. V1 的 resilience 弱线索没有被完整 episode 加强；得到加强的是“传统行业不是共同题材资金的充分表示”这一结构解释。
14. Dynamic peer 表示为 L2 mechanism clue；resilience、early re-acceleration 和 full repair 均为 L0 predictive signal；整个可交易 lifecycle family 裁决为 `STRONG_STOCK_LIFECYCLE_V2_NOT_SUPPORTED`。
15. 不值得账户研究。L3 development-candidate 门槛未达到。
16. 不值得 forward shadow；没有生成 `FORWARD_SHADOW_SPEC.json`。
17. 是。当前 price/volume Strong-Stock Lifecycle family 的研究优先级应降低；保留 dynamic peer 的描述性证据，不继续在同一开发样本上做条件或参数救援。
