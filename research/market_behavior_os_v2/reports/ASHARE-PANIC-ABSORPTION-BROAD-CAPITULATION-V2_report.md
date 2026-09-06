# ASHARE-PANIC-ABSORPTION-BROAD-CAPITULATION-V2

`EVENT_ENGINE_PASSES_FRESH_2025_BUT_IS_NOT_A_STANDALONE_STRATEGY`

> 2025新鲜延伸确认了这条规则捕捉到的“恐慌后库存转移”具有经济含义，但同时暴露出信号高度同日聚集。它保留为稀疏事件引擎，不能被包装成全年稳定、每天可用的独立策略。

## Simple strategy

1. After a 20-session loss of at least 10%, require a >=1% gap-down to a new five-session low.
2. Require same-day turnover at least its prior-20 mean and a close above the prior high in the top 30% of the daily range.
3. Admit only when at least two independent stocks show this same completed-session absorption event.
4. Buy the first legal open in the next three market sessions; sell at +10% or the next legal open after H20; no failure stop; 40 bp round trip.

All signal and cluster information is known at the completed signal close. No future-function market state is used.

## Development 2014-2020

Completed 465 (66.4/year); mean 5.31%; median 9.60%; mean holding 12.43 sessions; severe10 6.24%.

## Challenge 2022-2024

Completed 330 (110.0/year); mean 6.89%; median 9.60%; mean holding 7.70 sessions; severe10 4.85%.

|Year|Signals|Completed|Mean net|Median net|Win|Severe10|Target hit|
|---:|---:|---:|---:|---:|---:|---:|---:|
|2022|180|176|7.06%|9.60%|89.20%|4.55%|81.82%|
|2023|11|8|-5.20%|-7.23%|25.00%|12.50%|0.00%|
|2024|147|146|7.34%|9.60%|89.73%|4.79%|88.36%|

2023只有8笔完整交易且平均-5.20%，因此即使2022-2024合并收益很好，也不能把它解释为逐年稳定策略。

## Fresh 2025 extension

规则、入场、出场和成本在读取任何2025候选或收益前冻结；2025不使用牛市标签，也没有事后救援。

|Signals|Completed|Mean net|Median net|Mean holding|Win|Severe10|Target hit|
|---:|---:|---:|---:|---:|---:|---:|---:|
|361|356|7.84%|9.60%|12.00日|94.66%|0.28%|75.84%|

原始用户门槛在2025单年全部通过。不过，356笔完整交易中329笔形成于2025-04-09，占92.42%；全年只有9个独立信号日。最大事件日之外的27笔平均+6.21%，按信号日等权平均+6.53%，说明结果不完全由单日收益偶然性造成，但频数主要代表同一市场事件的横截面广度，而不是356次独立机会。

事后容量诊断按信号日成交额只保留每天前10只，2025仍有37笔、平均+6.89%、平均持有10.65日；该检查只回答大事件时能否选出较易成交的有限篮子，不属于冻结验证，也不能补足全年频率。

## Cross-history interpretation

在已评价的2014-2020、2022-2025共11个信号年中，合计1151笔完整交易，单笔平均+6.55%、平均持有10.94日，按股票笔数折算104.6笔/年；但总共只有86个独立信号日，按信号日等权平均仅+2.64%。2017接近零、2023为负，进一步说明它是市场恐慌事件引擎，不是常态选股引擎。

最短经济解释只有三句话：先有持续下跌和跳空创新低，代表库存被迫甩卖；随后放量收复前高并收在日内高位，代表当日供给被真实需求吃掉；多个股票同日出现，才说明冲击具有市场层面的可修复性。这里的“需求”和“库存转移”只是OHLCV可检验假说，不是对真实账户身份的断言。

## Scientific status

The chart-derived rule is post-hoc to consumed 2014-2021 charts. The 2022-2023 rows were already consumed by the mother experiment and are reused as a robustness block, not untouched validation. The original challenge opened only 2024; at that point no 2025 signal was read and 2025 rows were used only to complete pre-2025 positions. A separate freeze was subsequently written before reading any 2025 candidate or outcome, after which 2025-01-01 through 2025-12-31 was opened once. That extension is reproducible from:

- Freeze: `../experiments/ASHARE-PANIC-ABSORPTION-BROAD-CAPITULATION-V2-2025-EXTENSION_freeze.json`
- Runner: `../scripts/run_ashare_panic_absorption_broad_capitulation_v2_fresh_2025.py`
- Result: `/Volumes/quant/CY_quant_research/ashare_panic_absorption_broad_capitulation_v2/fresh_2025/result.json`

Final disposition: retain as a capped event sleeve; reject as a standalone solution to the user's frequency requirement. The steady-bull engine remains unresolved. Daily low-volume rules are retired; the next independent lane is causal minute price-volume recovery/acceptance, with T+1 entry and without order-book or participant-identity claims.
