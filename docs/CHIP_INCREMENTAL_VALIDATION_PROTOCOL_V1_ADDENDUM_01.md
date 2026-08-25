# 筹码增量价值协议 V1 勘误 01：纯价格量候选定义

状态：`PREREGISTERED_CORRECTION_BEFORE_OUTCOMES`。

本勘误不修改原协议的样本期、结果、效应门槛、统计检验、顺序预算或停止规则。
它只消除“价格重新获得支撑”和“突破幅度”的实现歧义。勘误登记前没有读取本研究线
的收益结果、标签或 2023 数据。

## 发现的问题

旧 `MARKUP_RETEST` 面板中的 `structure_support` 取价格阻力与前一日筹码带上沿的
较大值。因此该面板现成的 `support_regained` 与 `breakout_excess_atr` 含筹码字段，
不能用于原协议第 4 节要求的纯价格量候选。复用这两个字段会把筹码先写入对照组，
形成循环论证。

## 唯一允许的纯价格量实现

候选生成只读取注册资产 `CY-006` 的 2018--2022 年分区，且只投影原始 OHLCV、
成交额、换手、交易状态、公司行动、点时行业、市场指数、`available_at` 与
`snapshot_id`。禁止读取旧策略面板中的任何筹码或筹码派生列。

对每只股票、每个决策日 `t`：

1. 先用当日已生效公司行动的 `preclose / previous_raw_close` 因子建立仅向前累积的
   价格坐标；原始 OHLC 不覆盖。
2. `price_resistance_t` 固定为 `t-60 ... t-1` 的最高价，不包含决策日。
3. `ATR14_t` 为截至 `t` 的 14 日真实波幅；信号在收盘后形成，故可用当日值。
4. `daily_breakout_excess_t = (close_t - price_resistance_t) / ATR14_t`。
5. 在 `t-10 ... t-1` 中选择 `daily_breakout_excess` 最大的交易日为突破日；要求该值
   至少 `0.25`。对应日的 `price_resistance` 是本次回踩锚点。
6. 当日最低价触及 `anchor_resistance + 0.25 * ATR14_t` 以下，同时收盘不低于
   `anchor_resistance - 0.25 * ATR14_t`，才记为 `support_regained=true`。这使事件
   同时包含先前突破和随后回踩收复，而不是把当日新高误称为回踩。
7. 大盘和点时行业收益均由 `CY-006` 原始收益计算。行业收益严格 leave-one-out；
   行业未知、同行不足或时间不可用均 fail closed。20 日大盘收益高于/低于 2% 分为
   `RISK_ON/RISK_OFF`，行业 LOO 20 日收益高于/低于 2% 分为 `STRONG/WEAK`。
8. 只保留 `hard_valid=true`、`available_at <= decision_at`、当日可交易、无公司行动
   阻塞、大盘非 `RISK_OFF`、行业非 `WEAK` 的 2020--2022 行。
9. 按时间先后贪心选择；同一股票两次入选的股票交易日序号至少相隔 20，且每个
   ISO 周最多一次。该去重不读取收益。

`0.25 ATR`、60 日阻力、1--10 日回踩窗、20 日冷却和 ±2% 状态阈值均在首次收益
读取前固定；不得根据结果修改。若这一更严格且无筹码污染的候选样本不足，终点是
`INSUFFICIENT_EVIDENCE`，不能回退到含筹码的旧面板字段。
