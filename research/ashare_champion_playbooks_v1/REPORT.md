# A股冠军启发 Playbooks V1 — continuation final

## 裁决

`P3B_PRICE_VOLUME_EP_PROXY` 已第一次完成从正确冻结信号到最终 NAV 的完整经济回放，裁决为 **FULLY_TESTED_NEGATIVE**。它不是确认催化的 EP，也不是冠军私有方法复制。

BASE 使用 1,745 条信号、566 次成交、565 笔已平仓交易，期末一笔持仓按可观测收盘价计入 NAV。净收益 -57.27%，CAGR -19.82%，MaxDD -58.98%，PF 0.596，胜率 20.00%，平均盈利 +3.155R，平均亏损 -1.336R，期望 -0.437R。COST2 为 -60.11%，延迟一日为 -64.90%；结论未被成本或入场时钟反转。

## 关键判断

- 冠军式右尾确实存在：132 笔进入 winner state，最大 +48.80R；Top1/Top5/Top10 占毛盈利 15.17%/47.52%/59.25%。但赢家数量和总贡献不足以覆盖大量失败。
- 低胜率不是关闭理由；负期望才是。80% 交易亏损，234/77/33 笔分别亏损至少 1R/2R/3R，亏损 95 分位为 3.44R，最差 -9.67R。
- A股迁移摩擦显著：343 笔买入日已触及失效位而受 T+1 约束，528 笔最终成交价低于当时保护线；29 次跌停/状态延迟、4 次停牌延迟。
- planned-risk + winner management 显著保护资本但未创造 alpha。同一正确信号 Legacy C_MAX/TREND40 为 -91.58%、MaxDD -92.26%；Native 为 -57.27%、MaxDD -58.98%，平均利用率从 63.48% 降至 23.56%。
- 四个账户年收益均为负：2020 -26.81%、2021 -10.40%、2022 -13.08%、2023 -25.03%。因此不是单一年份造成的关闭。

## 上轮 blocker 与本轮解除

上轮 P1/P4 在公司行动账本首个缺失事实处停止；P2 被误概括为没有 14:25 基础；P3A 缺事件用途权限；P3B 又同时存在错误信号实现和非 native 账户。本轮确认分钟前缀 producer、cutoff 和尾盘执行证据已经合格，但 P2 专属 mini-base/同钟点量能 admission 尚未机械化；P3A 权限未解除。P1/P4 底层仍有 1,148 个未补股份到账事件（补 P3B 一条后），属于可复用数据缺口，不是几十条小补丁。

本轮解除 P3B：修正 open-gap 身份；补入 603301.SH 上交所实施公告中的 2020-06-09 新增流通股上市日；实现 0.5% 单仓 planned risk、2% 下单时 aggregate risk、15% 单名上限、结构失效、T+1 next-legal exit、+2R winner state、单调 10 日 trailing closing low、60 日 failsafe、R/MFE/MAE 和公司行动不变坐标。

## 20 个问题的直接答案

1. 上轮没有任何合格 primary account；原因如上。2. 本轮只完整解除 P3B。3. Champion Native Execution Layer 已实现并通过账户不变量。4. Native 将同信号亏损从 -91.58% 收窄至 -57.27%。5. 平均实际亏损 -1.336R。6. T+1/保护线穿越与延期数量见上。7. 有少数大 R winner，但不足。8–13. 胜率 20.00%，avg win +3.155R，avg loss -1.336R，expectancy -0.437R，PF 0.596，CAGR -19.82%，MaxDD -58.98%，利用率 23.56%。14. Native 明显优于 Legacy 但仍失败。15. 出现 low-win/high-payoff 形状，但不是正期望。16–17. 首个经济裁决是 P3B，`FULLY_TESTED_NEGATIVE`。18. P1/P2/P3A/P4 仍分别受 execution/minute/event/context 阻断。19. 主要失败来自 setup 的失败率和 winner scarcity，T+1 又把平均亏损推过 1R。20. 下一步最值钱的是完成 P2 专属 14:25 admission adapter；P3B exact proxy 应关闭，不做参数救援。

2020–2023 是已消费 development history，不是 OOS；没有打开 CY-011、2024+ 或发送真实订单。Pyramiding 未测试。
