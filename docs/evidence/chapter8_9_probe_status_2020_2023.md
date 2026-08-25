# Chapter 8/9 probe status — 2020–2023

## Frozen parameter 231: 2024–2026 holdout attribution

Parameter 231 was frozen after the 2020–2023 probe. The 2024–2026 results below use the identical rules and are validation only; 2026 is incomplete as of 2026-08-22.

| Period | Signals | Mean net return |
|---|---:|---:|
| 2020–2023 probe | 779 | -0.07% |
| 2024–2026 holdout | 914 | +0.18% |

Holdout attribution under the corrected executable B6 rule: B4 has 574 trades, B5_SM 243, B6 73, with small B1–B3 samples. B6 is negative in the holdout and therefore remains a failed candidate pending structural review. By year, the aggregate result is not evidence of stable cross-cycle alpha; it points to market-regime and stock/industry heterogeneity that must be tested without using the holdout for tuning.

This is an interim, research-only status report. Parameter 231 is a frequency-controlled probe candidate, not a promoted strategy. The B6 implementation was corrected before these figures: it now uses the audited reclaim candidate plus executable confirmation (p90, prior-break, concentration and volume).

## Current evidence

The strict state-machine run uses the registered v2 daily/chip feature assets, exact daily/feature snapshot joins, next-session entry, and the current cost model. It contains all six buy labels in the SQL source, but the present output is an exit-selected trade table; it is not yet the independent candidate-exit table required for final attribution.

The independent event audit shows approximately 2,342 distinct buy events across 2020–2023, or about 585 per year. The sector-gated parameter 105 produces 788 parameter-row trades, approximately 197 per year before independent de-duplication, and has mean net return about -0.20% with a win rate about 41.2%. This meets the frequency target but fails the quality objective.

By board in the current independent-event evidence:

| Board | Signal | Events | Mean net return | Win rate |
|---|---:|---:|---:|---:|
| Main board | B1 | 503 | -0.38% | 37.0% |
| Main board | B2_SM | 260 | -1.43% | 29.2% |
| Main board | B4 | 489 | -0.38% | 37.2% |
| Main board | B5_SM | 309 | -0.01% | 40.8% |
| ChiNext | B1 | 279 | -0.93% | 30.8% |
| ChiNext | B2_SM | 114 | -1.13% | 29.8% |
| ChiNext | B4 | 241 | -0.80% | 37.8% |
| ChiNext | B5_SM | 93 | -0.05% | 51.6% |

B3 and B6 are too sparse for inference in this implementation. B6 has one probe event. These are implementation/definition coverage failures, not evidence of profitability.

A staged coverage query explains why this must be audited before parameter tuning. A relaxed B3 core (two peaks, rising p50/primary peak, close reclaiming p50) has 2,679 rows; 547 retain the base-retention condition, 285 also pass the prior-break stage, 141 pass the corrected market regime condition, and 138 are executable next session. A relaxed B6 reclaim core has 167,561 rows; 23,922 retain the base-retention condition, 17,877 pass the volume stage, 8,547 pass the corrected market regime condition, and 8,453 are executable next session, before the remaining B6 requirements (60-day low relation, 5-day reclaim, peak prominence, and sector gate). Thus the one observed B6 trade is not evidence that B6 is intrinsically rare; the full conjunction is over-constrained and needs an independent full-rule audit. The earlier zero-market result was a diagnostic bug caused by comparing a stock close with an index price; it is corrected here and in the audit output.

## Interpretation

The result currently rejects the claim that parameter tightening alone creates an edge. The next required experiment is structural: export every independent S1–S6 candidate before CASE priority, then compare candidate-level forward outcomes and realized exits. S1/S2 overlap heavily in the selected-exit table, so current sell-label averages are not causal attribution.

No holdout conclusion is drawn from these probe results. Parameters and rule changes must be frozen before the 2024–2026 validation.

An independent exit-candidate scan is now available at `data/audit/chapter8_9_independent_exit_candidates_v01.csv`. It rescans every post-entry bar rather than trusting the selected `first_exit`. On the current strict-entry scope, candidate counts and mean entry-to-candidate returns are: S1 79,969 / -3.24%, S2 193,570 / -0.68%, S3 9,097 / -8.61%, S4 31,409 / +1.94%, S5 7,676 / -9.87%, and S6 97,686 / -8.09%. Five-day returns after the candidate date are positive for 47.8%, 45.1%, 48.1%, 44.9%, 50.4%, and 49.3% respectively. These are candidate-level diagnostics over entries present in the state-machine output, not an unbiased portfolio result; rule-isolated first-trigger backtests and board/industry/cycle breakdown remain required.

## Rule-isolated exit counterfactual

The rule-isolated backtest gives each S rule its own first-trigger exit, while retaining STOP and TIME60 as protective competitors. This removes the main attribution problem in which a rule is credited or blamed only because another CASE branch fired first.

| Isolated rule | Trades | Mean net return | Median net return | Win rate | Same as current priority |
|---|---:|---:|---:|---:|---:|
| S1 | 15,369 | -0.92% | -2.29% | 36.0% | 28.6% |
| S2 | 15,467 | -0.44% | -0.93% | 39.1% | 82.0% |
| S3 | 12,707 | -4.46% | -8.74% | 18.1% | 6.2% |
| S4 | 14,661 | -1.39% | -2.67% | 24.4% | 20.8% |
| S5 | 12,832 | -4.43% | -8.64% | 17.5% | 5.7% |
| S6 | 13,936 | -3.39% | -5.26% | 17.7% | 10.7% |

The state-machine output has now been corrected to retain all independent entry events, including entries with no selected exit. In the 2020–2023 probe this is 15,751 parameter-row entries, of which 43 have no exit candidate; the independent exit scan and counterfactual replay were rerun after this correction. The counterfactual table still only contains entries for which the tested rule (or STOP/TIME60) actually produces a candidate, so it remains a rule-diagnostic rather than a complete portfolio result. It nevertheless gives a clear direction. S2 is the least damaging structural exit and is already the current priority in most of its isolated cases; S1 is more sensitive to shakeout exits; S3/S5/S6 should not be used as unconditional early exits without a separate confirmation or risk-only role. Board, industry, market-cycle, and profit/loss attribution remain required before freezing rules.

## Expanded parameter probe

The original 16 baseline parameter sets were retained and 32 additional combinations were tested using stricter chip-narrowing, breakout-volume, pullback-volume, confirmation-day, and sector-gate settings. The 2024–2026 holdout was not used for selection.

Among settings producing roughly 150–250 probe signals per year, `param_id=231` was best at 176.5 signals/year, with mean net return -0.088% and win rate 41.5%. The closest setting to 200 signals/year, `param_id=227`, produced 198.0 signals/year, mean net return -0.199%, and win rate 41.0%. Thus reducing signal count to about 200 did not restore positive expectancy.

This does not yet prove the chip-structure thesis invalid, because B1–B6/S1–S6 attribution, board/industry/cycle decomposition, realistic blocked-exit treatment, and frozen 2024–2026 validation remain unfinished. It does rule out “the only problem is loose parameters and too many signals” as a sufficient explanation.
## 固定候选参数 231 的归因复核

参数 231 是探测期内接近每年 200 个信号的候选（176.5 个/年，706 个信号）。这部分只用于 2020—2023 探测，不涉及 2024—2026 锁定验证。固定参数 231 的逐笔归因中实际出现的是 B1、B2_SM、B3、B4 和 B5_SM，B6 在该固定候选中没有可用样本；主要样本来自 B4（505）和 B5_SM（177）。因此，B6 虽然已有机械定义，但尚未获得统计验证，不能把“已实现”当作“已验证”。

按当前修正后的板块映射和逐笔数据看，B4 是主要来源：主板 B4 在 2020—2023 年平均净收益约为 −0.55%、+1.24%、−1.32%、+0.10%；创业板 B4 约为 +1.31%、−1.64%、−1.81%、−1.27%。结果明显受市场阶段影响，不能简单归因于银行股或某一个行业。

卖出原因复核显示，B4 主板中 S1_STRUCT 的平均净收益约 +2.37%，S2_CONC 约 −0.43%，S6_SPACE 约 −1.42%，STOP 约 −11.89%；创业板对应约 −0.30%、−0.10%、−3.30%、−10.74%。路径数据同时显示，B4 在 S1/S2 后仍有较高恢复空间，但 STOP 组的最大不利波动更深；这支持继续区分“过早结构退出”和“买入本身失效”，但不支持简单取消止损。

行业分组的固定参数结果也不能直接当作行业优势证明：多数行业样本不足，且 B4 在汽车零部件、医疗器械、一般零售等组出现较弱结果；光学光电子、电力等组相对较好。后续必须做按个股、年份、市场周期和行业的交叉稳定性检验，并对“银行/周期股剔除或单独建模”做预注册的对照实验，不能事后挑选。

### 卖出确认窗口的再检验

对固定参数 231 的 2020—2023 入口队列，重新执行 18 组卖出网格：止损 8%/10%/12%、结构条件当日确认/连续 2 日确认/连续 3 日确认，以及 STOP_FIRST/STRUCT_FIRST 两种冲突优先级。确认窗口现在按连续交易日逐日计算，不再只是参数标签。B4 的平均净收益在当日确认约 −0.16%，连续 2 日确认约 −0.54%，连续 3 日确认约 −1.74%；胜率约由 41.9% 降至 32.4% 和 26.5%。两种优先级结果相同，说明当前样本中结构条件与止损的同日冲突不是主要矛盾。这个结果暂时否定“统一延迟卖出即可解决震仓”的假设，但仍需在冻结完整规则后用 2024—2026 做锁定验证。
收益集中度也不支持把少数大赢家当作稳定 edge：固定参数逐笔样本中，B4 的 504 笔已退出交易平均约 −0.28%，去掉单笔最大盈利和最大亏损后约 −0.30%；B5_SM 的 175 笔平均约 +0.31%，去极值后约 +0.27%。因此后续比较参数时必须同时报告均值、中位数、去极值均值、最大回撤和按年份表现。
