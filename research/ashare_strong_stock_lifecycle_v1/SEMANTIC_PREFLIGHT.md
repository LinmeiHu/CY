# 强势股生命周期 V1：语义预检

## 经济序列与时间锚点

`Leadership(t-5)` → `Pressure(t)` → `Resilience(t)` → `Repair(t+1..t+5)` → `Outcome(t+5+1..t+5+20)`。

所有日线字段在相应交易日收盘后才可见；事件研究的 Outcome 统一从分类完成日 `t+5` 的下一交易日开始计量。它不是同 bar 成交或账户回测。

| 项目 | 定义与可用性 |
|---|---|
| Cause | 市场或 PIT 行业过去 5 日的标准化下行压力 |
| State | 过去 60 日相对强度、行业共振、已估计的过去 60 日 beta |
| Trigger | t 日收盘确认 Pressure；只保留 t-5 日已经成立的 Leadership |
| Resilience | t 日实际收益减去 t-1 前 60 日估计的市场/行业预期收益 |
| Repair | t 后第 1--5 日内，残差为正且收盘重回 t 日收盘之上；仅用于 t+5 时的分组 |
| Outcome | t+5 后的 5/10/20 sessions，且永远晚于 Repair 分类 |

## 禁止的倒填与处理

没有用未来高点确认过往低点；Pressure 不由未来 Repair 定义；没有 Repair 的压力事件保留在 G2 分母；样本结束不足完整 Outcome 的行标记 truncation 后排除该 horizon；行业为每日 PIT 历史映射，未知和 `hard_valid=false` 行不参与。没有使用今日概念名单、公告或分钟数据。

## 已选择的固定表示

宽准入为当日全市场 Ret60 横截面百分位不低于 70%，并要求行业当日已知。这是事件采样边界而非经结果选择的交易阈值；邻近 60--70% 区间单列作敏感性诊断。Pressure 是过去五日市场或 leave-one-out 行业收益低于各自过去 60 日五日收益的 -1 z-score。不存在阈值网格。
