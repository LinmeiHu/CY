# 五策略失败机制语义预检 V2

旧版原文及哈希保留在外接盘 prior_source。以下继承真实冻结入场逻辑；结构解释都是待检验假说。

## ATRDR_BULL

- **ECONOMIC_SEQUENCE / Cause**：个股在正向市场状态中出现参与度扩张与价格点火；行业广度变化提供局部需求背景。
- **CAUSAL_BACKGROUND / State**：市场与行业状态均来自信号日完成收盘，`feature_latest_timestamp <= decision_at`。
- **STATE_VARIABLES**：market regime、industry breadth delta、ret60、turnover ratio、信号日 coordinate OHLC。
- **EVENT_FORMATION_TIME / CONFIRMATION_TRIGGER**：信号日 15:00 形成并确认 `SIMPLE_BULL_PARTICIPATION_IGNITION`。
- **ENTRY_TIME**：其后首个合法开盘，禁止同 bar 入场。
- **NATIVE_EXIT / OUTCOME_START_TIME**：15% target 或 H15 time exit；Outcome 从 entry 后开始。
- **ECONOMIC_FAILURE_INTERPRETATION**：入场后重新跌破确认日低点，表示点火没有守住已经确认的需求结构；长时间仍低于 entry 表示未 follow through。
- **AVAILABLE_STRUCTURAL_ANCHORS**：信号日 `coord_low`；不新造指标。
- **POSSIBLE_SEMANTIC_AMBIGUITIES**：旧版盘中 stop-first 假设已停用。本轮新增政策仅收盘观察、次日开盘执行；原生目标已在开盘可成交时优先。
- **CHOSEN_TIME_ANCHORS**：completed close → next legal open entry → T+1 后可执行 stop。

- **POSSIBLE_FAILURE_MECHANISMS**：H1持续失守且收盘恢复不足；H2亏损、下跌量能代理偏高且三日恢复为负。SMV6先检验已有退出后残余，不直接继承股票假说。
- **RIVAL_EXPLANATIONS**：点火后回撤可能是正常换手；原确认日低点并非有特殊价值的承接边界。
- **V2 CHOSEN_TIME_ANCHORS**：完成收盘16:00观察；下一合法开盘尝试；首次触发锁定重试，原生退出先发生则服从原生退出。日线最低价不作为成交证明；不使用同bar高点激活后低点触发。

## ATRDR_FAST_BEAR

- **ECONOMIC_SEQUENCE / Cause**：急跌/恐慌后的主动需求点火，押注快速修复而非趋势延续。
- **CAUSAL_BACKGROUND / State**：Bear worsening regime、prior10 loss、close location、turnover 与局部行业相对状态均在信号收盘可见。
- **STATE_VARIABLES**：market regime、prior10 return、signal low、prior20 low、turnover、coordinate lineage。
- **EVENT_FORMATION_TIME / CONFIRMATION_TRIGGER**：capitulation signal 完成收盘时确认。
- **ENTRY_TIME**：其后首个合法开盘。
- **NATIVE_EXIT / OUTCOME_START_TIME**：10% target 或 H20 time exit；Outcome 从 entry 后开始。
- **ECONOMIC_FAILURE_INTERPRETATION**：信号低点再次失守可能意味着需求接管失败；但成功修复前重测低点本来就可能常见，因此 tight stop 必须接受 winner-MAE 约束。
- **AVAILABLE_STRUCTURAL_ANCHORS**：冻结的 signal-day `coord_low`。
- **POSSIBLE_SEMANTIC_AMBIGUITIES**：不从日线高低推断盘中新增止损；同开盘已可成交的原生目标优先。
- **CHOSEN_TIME_ANCHORS**：completed close → next legal open → T+1。

- **POSSIBLE_FAILURE_MECHANISMS**：H1持续失守且收盘恢复不足；H2亏损、下跌量能代理偏高且三日恢复为负。SMV6先检验已有退出后残余，不直接继承股票假说。
- **RIVAL_EXPLANATIONS**：放量下跌可能接近恐慌释放终点，失守后即卖可能放弃修复。
- **V2 CHOSEN_TIME_ANCHORS**：完成收盘16:00观察；下一合法开盘尝试；首次触发锁定重试，原生退出先发生则服从原生退出。日线最低价不作为成交证明；不使用同bar高点激活后低点触发。

## ATRDR_SLOW_BEAR

- **ECONOMIC_SEQUENCE / Cause**：慢速供给衰竭、下行成交收缩与修复接管。
- **CAUSAL_BACKGROUND / State**：Bear stabilizing regime 与 last5/previous5 downside turnover 在信号收盘完成。
- **STATE_VARIABLES**：last5_low、previous5_low、turnover contraction、exact prior20 return、market medians。
- **EVENT_FORMATION_TIME / CONFIRMATION_TRIGGER**：slow-supply takeover signal 完成收盘时确认。
- **ENTRY_TIME**：其后首个合法开盘。
- **NATIVE_EXIT / OUTCOME_START_TIME**：10% target 或 H20 time exit；Outcome 从 entry 后开始。
- **ECONOMIC_FAILURE_INTERPRETATION**：重新失去已观察到的 last5 supply floor，才是结构失败；正常噪声内回撤不自动等于失败。
- **AVAILABLE_STRUCTURAL_ANCHORS**：冻结 `last5_low`，另保留 signal low 仅作描述。
- **POSSIBLE_SEMANTIC_AMBIGUITIES**：coordinate lineage 与日内顺序；发生 lineage break 时不制造可交易 stop。
- **CHOSEN_TIME_ANCHORS**：completed close → next legal open → T+1。

- **POSSIBLE_FAILURE_MECHANISMS**：H1持续失守且收盘恢复不足；H2亏损、下跌量能代理偏高且三日恢复为负。SMV6先检验已有退出后残余，不直接继承股票假说。
- **RIVAL_EXPLANATIONS**：低量可能代表无人交易而非供给枯竭；跌破last5低点也可能是正常二次探底。
- **V2 CHOSEN_TIME_ANCHORS**：完成收盘16:00观察；下一合法开盘尝试；首次触发锁定重试，原生退出先发生则服从原生退出。日线最低价不作为成交证明；不使用同bar高点激活后低点触发。

## MCB

- **ECONOMIC_SEQUENCE / Cause**：个股参与度扩张后，由主板/创业板同日确认降低孤立点火风险。
- **CAUSAL_BACKGROUND / State**：市场、行业与 cross-board count 均来自同一完成收盘。
- **STATE_VARIABLES**：cross-board confirmation、industry breadth、stock-minus-industry return、turnover expansion、signal coordinate low。
- **EVENT_FORMATION_TIME / CONFIRMATION_TRIGGER**：V72 confirmation 在信号日 15:00 完成。
- **ENTRY_TIME**：其后最多三日内首个合法开盘。
- **NATIVE_EXIT / OUTCOME_START_TIME**：15% target 或 H15 time exit；Outcome 从 entry 后开始。
- **ECONOMIC_FAILURE_INTERPRETATION**：跌回确认日低点以下表示跨板确认仍未转化为持续需求；若失败尾部已被 confirmation 大幅过滤，stop 可能没有增量价值。
- **AVAILABLE_STRUCTURAL_ANCHORS**：冻结 V72 signal `coord_low`。
- **POSSIBLE_SEMANTIC_AMBIGUITIES**：旧版 stop-first 不用于本轮；仅比较同一收盘观察/次开执行契约。
- **CHOSEN_TIME_ANCHORS**：confirmation close → next legal open → T+1。

- **POSSIBLE_FAILURE_MECHANISMS**：H1持续失守且收盘恢复不足；H2亏损、下跌量能代理偏高且三日恢复为负。SMV6先检验已有退出后残余，不直接继承股票假说。
- **RIVAL_EXPLANATIONS**：跨板确认可能已过滤失败，新增状态只是重述当前亏损；紧退出会中断随后修复。
- **V2 CHOSEN_TIME_ANCHORS**：完成收盘16:00观察；下一合法开盘尝试；首次触发锁定重试，原生退出先发生则服从原生退出。日线最低价不作为成交证明；不使用同bar高点激活后低点触发。

## OGR

- **ECONOMIC_SEQUENCE / Cause**：真实向下 gap 后形成首个 reversal，随后出现新鲜、非流动性陷阱、非封板且有序成交的 gap-repair 条件。
- **CAUSAL_BACKGROUND / State**：gap geometry、swing low、L/U、VAP 与 amount gate 的 source timestamps 均不晚于 signal decision。
- **STATE_VARIABLES**：L、U、W、swing_low、gap age/depth、recovery、liquidity guard、orderly amount。
- **EVENT_FORMATION_TIME / CONFIRMATION_TRIGGER**：signal close 完成 first reversal 与 V28R2 gates。
- **ENTRY_TIME**：信号后首个真实可买一分钟开盘。
- **NATIVE_EXIT / OUTCOME_START_TIME**：pre-L repair target、H20 或 corporate-action risk exit；Outcome 从 entry minute 后开始。
- **ECONOMIC_FAILURE_INTERPRETATION**：重新失去 reversal swing low 表示修复结构失败，比任意百分比损失更贴合经济故事。
- **AVAILABLE_STRUCTURAL_ANCHORS**：冻结 `swing_low`；L 仅作路径背景，不作为 V1 第二套结构参数。
- **POSSIBLE_SEMANTIC_AMBIGUITIES**：新增退出不使用同分钟高低顺序；原生目标在下一开盘已可成交时优先，其余原生分钟顺序沿用冻结输出。
- **CHOSEN_TIME_ANCHORS**：completed-close signal → next executable minute entry → T+1 minute execution。

- **POSSIBLE_FAILURE_MECHANISMS**：H1持续失守且收盘恢复不足；H2亏损、下跌量能代理偏高且三日恢复为负。SMV6先检验已有退出后残余，不直接继承股票假说。
- **RIVAL_EXPLANATIONS**：gap-repair本就允许重测低点；从既有高目标提前卖出可能系统性损害期望值。
- **V2 CHOSEN_TIME_ANCHORS**：完成收盘16:00观察；下一合法开盘尝试；首次触发锁定重试，原生退出先发生则服从原生退出。日线最低价不作为成交证明；不使用同bar高点激活后低点触发。

## IFCGR shadow inheritance

- **ECONOMIC_SEQUENCE / Cause/State/Trigger/Outcome**：与 OGR 相同，issuer-fact cooldown 只在 entry 前过滤母候选。
- **NATIVE_EXIT**：沿用 OGR。
- **ECONOMIC_FAILURE_INTERPRETATION**：不再优化 stop；仅继承 OGR 最终 shortlist，检验 issuer filter 与 exit 是互补、冗余还是共同有害。
- **AVAILABLE_STRUCTURAL_ANCHORS / CHOSEN_TIME_ANCHORS**：完全继承 OGR，不增加参数。
- **POSSIBLE_SEMANTIC_AMBIGUITIES**：PIT-B issuer enumeration 的 revision/deletion history 不完整，必须保留证据标签。

- **POSSIBLE_FAILURE_MECHANISMS**：H1持续失守且收盘恢复不足；H2亏损、下跌量能代理偏高且三日恢复为负。SMV6先检验已有退出后残余，不直接继承股票假说。
- **RIVAL_EXPLANATIONS**：issuer过滤与新增退出可能打在相同事件上，不能算两份独立验证。
- **V2 CHOSEN_TIME_ANCHORS**：完成收盘16:00观察；下一合法开盘尝试；首次触发锁定重试，原生退出先发生则服从原生退出。日线最低价不作为成交证明；不使用同bar高点激活后低点触发。

## SMV6

- **ECONOMIC_SEQUENCE / Cause**：ETF B60 breakout + FULL40 compression + MINVOLLOC30，通过 CSI1000 MA15 entry gate 后构建最多五只 ETF 的 CAP50_SET。
- **CAUSAL_BACKGROUND / State**：候选日线历史只到当前决策前；entry 与 exit market anchors 分离。
- **STATE_VARIABLES**：ETF MA20 entry、MA40x2 own exit、HS300 MA20 weekly exit、2% daily emergency exit、membership state。
- **EVENT_FORMATION_TIME / CONFIRMATION_TRIGGER**：completed close 形成 pending desired；次日 open 执行。
- **ENTRY_TIME**：09:30 registered executable bar。
- **NATIVE_EXIT / OUTCOME_START_TIME**：14:57 形成 MA40/market exit，15:00 close 执行或次日 open retry；Outcome 从实际 fill 后开始。
- **ECONOMIC_FAILURE_INTERPRETATION**：先判断现有 exits 后的残余损失究竟是单 ETF 突发尾部、市场共振、MA 慢响应、不可交易 gap，还是普通趋势噪声。
- **AVAILABLE_STRUCTURAL_ANCHORS**：现有 MA40、HS300 MA20 与 emergency buffer；V1 不新增结构指标。
- **POSSIBLE_SEMANTIC_AMBIGUITIES**：本地语义 replay 不等同 SuperMind 原生成交；ETF T+0/T+1 不统一假设。
- **CHOSEN_TIME_ANCHORS**：completed close signal → registered next-open execution；先做 `RESIDUAL_LOSS_ATTRIBUTION`，仅出现 `SINGLE_POSITION_DOWNTAIL_HEADROOM` 才打开 hard-stop scan。

- **POSSIBLE_FAILURE_MECHANISMS**：H1持续失守且收盘恢复不足；H2亏损、下跌量能代理偏高且三日恢复为负。SMV6先检验已有退出后残余，不直接继承股票假说。
- **RIVAL_EXPLANATIONS**：个体亏损也可能由共同市场退出造成，新增个体状态对真实现金路径未必有增量。
- **V2 CHOSEN_TIME_ANCHORS**：完成收盘16:00观察；下一合法开盘尝试；首次触发锁定重试，原生退出先发生则服从原生退出。日线最低价不作为成交证明；不使用同bar高点激活后低点触发。

## 本轮实际执行约束

研究特征共11个代表（价格6、扩展5），每条最多11个。未引入行业/市场重新聚合，避免父市场口径混用；成交量仅称价格成交量代理。
MCB/Bull共用证券和信号日簇，分路线报告但不将两者当作独立验证。IFCGR继承OGR，不搜索独立规则。
原生股票账户用冻结归一化份额；不是可按任意本金转换的整手账户。新增退出为显式日线收盘/次开模拟；开盘深度未知限制保留。
任务窗口与候选预算见 research_contract.json；旧版“按实际交易信号日60/40”尚未实际冻结/运行，V2沿用前序已消费的development/post-observation日历边界。
发现段所有结果也视为已消费。当前基线ATRDR COMPLETED过滤缺陷单列，不能把修正诊断称生产基线未变。
