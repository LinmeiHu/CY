# Fixed parameter 231 attribution — 2020–2023

This is a diagnostic report for the executable state-machine output, not a
promotion decision. Entries use the corrected B6 rule, next-session fills,
registered PIT inputs, and exact daily/feature snapshot matching.

## Aggregate

The probe contains 779 signals, approximately 194.8 per year. The mean net
return is -0.07%. The trade table has 776 rows with an exit candidate; the
remaining rows must remain in portfolio-level accounting rather than being
silently dropped.

The sample is dominated by B4 (505 entries), followed by B5_SM (177) and B6
(73). B1–B3 are too sparse for standalone claims. B6 is not validated: its
probe mean is approximately +0.13%, while the frozen 2024–2026 holdout mean is
approximately -0.57%.

## Board and year

B4 is positive in MainBoard only in 2021 and 2023, and negative in 2020 and
2022. ChiNext B4 is positive in 2020 and negative in 2021–2023. This is strong
regime dependence, not a stable board-independent edge.

## Exit attribution

For B4, S2_CONC is the dominant selected exit (375 trades, mean -0.32%), while
S1_STRUCT has 87 trades and mean +1.61%. S6_SPACE is -2.52% and STOP is
-11.41%. B5_SM is less negative: S1 +0.59% and S2 +0.31%, but the medians are
near zero or negative. B6 has 44 S2 exits at +0.24%, but 6 STOP exits at
-10.34% and is not yet reliable.

Post-entry path diagnostics show that many B4 S1/S2 exits are followed by
substantial recovery, so a structural exit can be early. The same evidence
does not justify removing the protective stop: STOP cases are infrequent but
deeply negative, indicating genuine entry failures or blocked-exit tail risk.

## Industry and concentration

The weakest industries with at least five trades by total contribution are
automotive components, medical devices, consumer electronics, securities, and
chemical pharmaceuticals. The strongest groups include power, construction
machinery, communications services, computer equipment, and optical displays,
but several have small samples and cannot be treated as transferable edges.

The table contains 505 distinct stocks and 776 exited trades. Stocks appearing
at least five times contribute about -6.0 percentage points, versus about
-52.4 percentage points for all exited trades. Therefore repeated names do not
explain the full result, and the apparent positive/negative industry groups
must be tested with leave-one-stock-out and year/board stability checks.

## Current conclusion

The data support a real sell-point problem for some B4/B5 paths, especially
early concentration/structure exits. They do not support the claim that
loosening exits alone fixes the strategy. The next required experiment is a
pre-registered exit redesign that separates recovery-tolerant exits from
hard-failure exits, then reruns the complete 2020–2023 probe and untouched
2024–2026 holdout with all six buy and six sell labels retained.
# 2026-08-22 卖出敏感性复核（2020–2023，仅探测集）

在固定 231 买入队列上重新运行了 3 个止损阈值（8%、10%、12%）× 3 个结构确认窗口（当日、连续 2 日、连续 3 日）× 2 个优先级。结果再次确认：把 S1–S6 普遍延迟确认并不能解决震仓问题；以 B4 为例，`STOP_FIRST` 下 8% 止损的平均净收益由当日确认的 -0.163% 变为连续 2 日 -0.658%、连续 3 日 -1.715%，10% 止损对应 -0.158%、-0.507%、-1.744%。

随后运行了预注册的 `S1S2_GRACE` 变体：S5、止损、S3/S4/S6 立即退出，仅要求 S1 或 S2 连续 3 个交易日成立才退出。其探测集结果仍弱于基线：B4 在 8%/10%/12% 止损下分别为 -0.885%/-0.908%/-0.877%，而对应的当日结构基线约为 -0.163%/-0.158%/-0.158%。这否定了“只给 S1/S2 统一三日宽限”作为当前卖出改进方案；它不能被带入 holdout。下一轮应转向逐类退出归因和“重新站回主峰/成本带取消退出”的明确状态机，而不是继续机械增加等待天数。

这不是“卖得太快”这一单一解释可以覆盖的现象。下一步应只对 S1/S2 这类可能恢复的结构恶化设置恢复窗口，同时保留 S5（跳空/大阴线穿越主峰）和止损的硬退出；S3/S4/S6 仍须单独检验，不能整体延迟。该变体在进入 2024–2026 holdout 前必须先在本探测集预注册、完成逐笔和板块/年份拆分。
