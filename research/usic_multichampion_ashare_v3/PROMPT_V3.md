# Codex / Astra 自主研究任务 V3
# 近年 USIC 冠军方法的 A 股迁移：多入口、状态适配、真实现金与受控融合

版本：2026-09-08 / V3
任务性质：历史研究、必要实现、相关错误修复、可复现结果与正常提交；不是实盘交易授权。
方法标签：CHAMPION_INSPIRED_MECHANICAL_A_SHARE_PROXIES_NOT_REPLICATIONS

请完整阅读本文件。实际执行，不要只写计划，不要停在环境审计、合同冻结、样本生成或单元测试。用户允许较长运行时间，目标是做完整、多方案、可解释的研究，而不是尽快交一个漂亮的最高收益。

## 0. 研究范围与证据边界

核心问题：不同交易阶段的入口——成熟趋势收缩突破、强势股回调、早期转强、突破前参与——在 A 股真实现金账户下分别是否成立？哪些组合具有净增量，哪些只是重复持有同一批强势股票？市场环境、公开催化、行业、退出与分步建仓分别贡献什么？

本轮预登记：216个核心账户情景，最多72个数据条件性情景，最多8个既有五策略影子组合情景，上限296个情景槽位。它们不是296个独立假说或独立验证。全部配置先登记；亏损、不好看、信号少，都不是事后删掉情景的理由。真正无样本、数据硬阻塞、权限不足或精确重复，分别报告，不强行凑数。

旧V1/V2最多70个情景属于历史证据账本，不计入本轮296个。可以精确验证后复用其中与本轮配置相同的结果，但不得把旧运行改称本轮新运行，也不得强制重跑全部旧70个。源码修复导致旧结果无效时，另作纠错回放并列入修正账本。仅有相同信号还不够复用账户结果；现金、成本、容量、退出、区间、数据和引擎版本也须一致。

本文件自包含：附录A逐字保留V2全文，里面又含V1全文；附录仅负责被明确引用的旧定义和通用安全要求。V3主文对本轮分支、研究范围、情景数、执行先后和新定义具有优先权。附录中“只做20个”“只做70个”“不研究其他入口”的旧范围，不限制本轮明确授权的新实验。不要把附录当成三个同时启动的任务。

所有新增数字、窗口、指标、仓位规则，除明确标注原作者公开事实外，都是本轮事前设定的机械代理，不是冠军本人精确交易规则，不是最佳参数。年度比赛成绩不构成本代理的收益目标、回测验收条件或实盘承诺。

最高部署结论为 SHADOW_ONLY。不得真实下单，不改五策略生产逻辑、不换生产参数、不打开新的sealed validation、不使用非公开消息、不推断或配合操纵交易。

## 1. 已核验的比赛事实及来源分层

以下为已完成年度的股票组结果，不是所有资产组统一冠军。主办方于不同年份对百万以上组也使用Money Manager Verified Ratings名称。

| 年份 | 100万美元以下股票组第一 | 100万美元以上股票组第一 | 结果来源 |
|---|---|---|---|
| 2025 | Martin Luk，+969.8% | Law Wai-Sum / J Law，+252.3% | R25 |
| 2024 | Judy Lai，+449.1% | J Law，+353.9% | R24 |
| 2023 | Goverdhan Gajjala，+805.1% | Tanmay Khandelwal，+129% | R23 |
| 2022 | Afzal Lokhandwala，+447% | Sam Bhatia，+13.5% | R22 |
| 2021 | Pavel P. Sterba，+222.3% | Mark Minervini，+334.8% | R21 |
| 2020 | Oliver Kell，+941.1% | George Tkaczuk，+119.1% | R20 |

截至本文件核验日2026-09-08，官网展示的2026榜单为截至7月31日的七个月成绩，不是年度冠军。不要把2026暂时领先者称为2026全年冠军。

Afzal在2023年为该股票组第二名，不能写成连续两年夺冠。Judy在2024另一个账户/组别的273.8%第二名，不能与449.1%冠军混写。

比赛允许外国参赛者和外国股票；股票组也不能理解为只做美国现货、无杠杆、只做多。官网明确允许做空、杠杆及部分其他交易。因而比赛收益不可以直接与本轮A股无杠杆账户比较。增强成长组允许的期货/买入期权表现，不按现货A股方法硬迁移。年度排名也不等于公开了完整逐日净值、最大回撤、逐笔交易及所有实际规则。

方法证据分三层：
1. 一手全文：本人署名/确认的文章、访谈文字、本人网站公开体系；只取实际可读内容。
2. 原始访谈发布页/节目简介/公开视频标题：可确认公开方法方向，不能假称已逐秒听完或拥有完整字幕。
3. 我们的研究代理：以下精确定义绝大多数属于此层，必须与1、2分开。

Judy Lai、Pavel P. Sterba、Sam Bhatia的冠军成绩已核实，但本轮未取得足够完整、可独立机械化的本人规则；不因关联人物、网文或职业背景而杜撰三套新策略。其证据缺口留在SOURCE_REGISTER，不阻塞已具备方向依据的其他路线。

## 2. 执行环境：独立工作树，保护并行研究

只读定位线索：
- 主仓库 /Users/linmei/Documents/CY，预期origin LinmeiHu/CY。
- /Users/linmei/Documents/CY-worktrees/ 下可能有V1/V2、五策略相关工作树。
- /Users/linmei/Documents/CY-supermind-v6-autonomous-20260830。
- /Users/linmei/Documents/CY-oversold-reversal-ranking。
- 建议本轮分支 research/usic-multichampion-ashare-v3。
- 建议本轮工作树 /Users/linmei/Documents/CY-worktrees/usic-multichampion-ashare-v3-20260908。
- 本轮小型代码/spec/report目录 research/usic_multichampion_ashare_v3/。

核验repo/origin/HEAD/status/worktree list/AGENTS.md、相关运行进程、既有数据模块和可用磁盘。选择有证据的BASE_HEAD，不机械使用对话中的旧commit。可以自行创建或恢复本轮分支，无需为已明确授权的正常实现选择重复询问用户。

禁止reset --hard、git clean、强制切换/推送、替用户stash无关文件、结束其他任务进程、修改运行中的V1/V2或五策略工作树。共享原始数据只读；缓存和输出按任务/hash命名隔离，采用原子写入。

历史数据权限依据项目现有台账，不因新冠军、新分支或别的任务用过就自动扩大。封存区间保持封存；权限不明的部分隔离。已看过历史不能重新叫独立验证。

大件优先放实际发现并验证可写的外接盘；不得假设卷名。代码、配置、来源、manifest、报告、小摘要放Git。不可顺手做全仓库重构、另建通用平台、下载全网新闻。先复用现有日线/分钟/PIT公告/财务/交易引擎，仅补本任务所需部分。

## 3. 查重、预检与修错

先查旧研究的真实定义与结果，而不是只搜策略名字。至少覆盖：普通突破、RS、Low-MAX、低波动、VCP、路径、均线回踩、第一次收复、深跌反转、尾盘/隔夜、分钟旗形、行业同步共振、市场广度、事件策略以及五策略信号。

每条新增路线记录 EXACT_DUPLICATE / PARTIAL_OVERLAP / DISTINCT_QUESTION，列明股票池、时间尺度、事件形成、交易时点、退出、对照和证据路径。旧失败不因换名被救活；旧问题相近也不能草率否决所有不同时间顺序的实验。

对每条路线写不超过一页的Semantic Preflight：
ECONOMIC_SEQUENCE、CAUSAL_BACKGROUND、STATE_VARIABLES、EVENT_FORMATION_TIME、CONFIRMATION_TRIGGER、ENTRY_TIME、OUTCOME_START_TIME、POSSIBLE_SEMANTIC_AMBIGUITIES、CHOSEN_TIME_ANCHORS。

Cause是待检验机制；不能用K线标签冒充已经观察到“主力吸筹/震仓”。State、Trigger、Outcome严格区分。不要把趋势早期转强强制套上成熟200日多头模板；不要把“尚未突破”的提前参与同时要求成“已经突破”。

必要纠错应实际修复并补回归测试，保留旧产物和失效范围。修bug带来的收益变化单列，不归功于冠军融合。正式读取大样本收益前冻结本轮spec、源码版本、数据manifest和全部情景；之后非bug修正规则不得改动。确有语义矛盾时先在不看结果的阶段修订并留痕，不能假装原定义一直如此。

## 4. 共同样本、时间与标准化

普通沪深A股，历史时点ST/*ST排除，ETF、B股不进入此股票研究；其他市场仅在已有合法完整数据与明确新增授权时另列，不静默混入。保留退市股票和历史身份，不能用今日名单回填。所有D/H核心版本遵守V2的基本历史覆盖：在T−31已有252个交易日的必要历史。因此本轮不覆盖全部次新/IPO行情，不声称完整复制冠军的所有机会。

T为完整收盘后决策日，q=T−1。交易日偏移使用市场交易日历，不将停牌日删去后压缩窗口。最低限度共同字段：历史OHLC、成交股数与成交金额、公司行动/复权桥、上市/退市/ST/停牌、历史板块、市场指数及交易规则表。

特征可以使用T收盘来确认触发，但原有结构、锚点、支撑水平必须在此前可见；日线信号最早T+1执行。指数和股票时区统一到Asia/Shanghai；不能把日期默认成00:00可用。分钟按bar结束时点可见，不使用未结束bar。

价格特征可用连续复权坐标，实际下单必须映射回当时未复权价格。金额、股数、复权系数需维度一致，尤其AVWAP不可将后复权价、未调整股数、累计原始金额随意混加。交易所得、分红、拆并股等通过实际账本处理，不把价格复权收益再重复记现金。

EMA(n)：alpha=2/(n+1)，用前n个已知收盘均值初始化，再递归；预热充分，不因分块重新初始化。ATR20：Wilder方法、真实昨收、事前定义。V2继承版本保持其既有精确定义；若与新增模块初始化不同，明确区别而非无声改变旧信号。

非继承路线的RS60：q收盘过去60交易日总价格收益的同日同交易制度板块百分位；RS20类似。价格路径分数复用V2的平均回撤负担与上涨贡献集中度，但只在各路线声明的“此前上涨”窗口计算。全市场/板块rank在同日完整可用集合上计算，禁止分块局部排名。

所有波动尺度A/A0必须为正且单位一致，缺失历史不得以0替代。信号同股票去重。D00–D02原信号流保留V2行为；D03–D09及H信号的同一冻结setup只发第一次合格触发，不因后续上涨不断补发。每个setup保存formation_at、known_at、anchor、expiry、invalidated_at。持仓中再次出现同股票信号通常忽略，只有明确的加仓模块例外。D07/D08/H01的多个父事件各自维护状态，不能用新父事件静默重置旧事件；同股票同日出现多个同路线子信号时，选formation_at最早的父事件，再以父事件ID破同分，不能看未来收益择父事件。

数据资格按覆盖和时间正确性确定，不得依据利润。缺少金额数据时D04单独标记BLOCKED_AVWAP_INPUT，仍跑其他核心量价路线；这是核心槽位未完成，不能冒称216全完成，也不能用典型价格乘量冒充真实AVWAP。

## 5. 十二个预先固定的日线策略/对照

### D00 / D01 / D02：成熟趋势的三个继承对照

- D00 = V2 N1：LONG_TT + 普通强势突破，RS排序。
- D01 = V2 N3：LONG_TT + 动态VCP，RS/VCP排序。
- D02 = V2 N4：LONG_TT + 动态VCP + 前段渐进路径；为原主融合版。

A/W/F窗口、T−31固定ATR、严格as-of拐点、Guard、U、最高买价、排名等，逐项按附录V2执行，不换短窗口。D00是必要对照，不宣称新策略。

增量问题：D01−D00说明所测VCP方案整体差异；D02−D01说明加入路径后的差异。Guard导致入选集合不同，应做共同支持/匹配诊断，不能称纯因果效应。

### D03：Martin Luk启发的“强势股回调后恢复”

公开依据：本人客座文章描述EMA强度分组、行业关注及下一次回调参与；精确定义以下均为本轮代理。

状态截止q：
- EMA9(q)>EMA21(q)>EMA50(q)，EMA21(q)>EMA21(q−5)，Cq>EMA50(q)，RS60(q)>=0.70。
- 预形成波动A=ATR20(T−21)，固定用于本次事件；A>0。
- p为[T−20,T−3]内最高H所在日，等高取最早日。设P=Hp；要求p之后至q至少2日。
- 从p至q的低点与P之差，在[1A,3A]内；Cq<P。
- q日低价Lq<=EMA21(q)+0.25A；Cq>=EMA21(q)−0.5A。这里只观测靠近均线与恢复条件，不预先称“承接成功”。

T触发：CT>Hq且CT>EMA9(T)。
- 冻结入场参考B=Hq；最高买价L=B+0.5A；结构线S0=min(Lp...LT)−0.1A，T收盘后才可使用LT。
- 按0.5*RS60+0.5*“回调深度/A较小”的当日百分位排序，越高优先。
- 一个p对应一个setup；第一次合格触发后该setup结束；首次触发后未成交不反复追单。

### D04：D03 + 固定锚点AVWAP合流

这是附加机制测试，不声称复制Martin公开访谈中所有AVWAP锚法。
- 对D03每个setup，在[T−60,p−1]寻找最近一次b满足Cb>max(Hb−20...Hb−1)。b当日即可确认。
- 锚点固定为b，不挑使历史盈利最大的高低点，不在q后回改。没有锚点的候选标记NO_VALID_ANCHOR。
- AVWAP(b,q)=b至q累计实际成交金额/累计实际成交股数，在统一公司行动坐标中计算。对每个历史成交日须用当时可得公司行动转换至同一每股单位，分子/分母的转换应有手算样例与量纲测试；仅掌握日线加权价而无法一致转换的跨行动事件标记缺失，不凭当代复权因子回填。
- 加入两条件：|AVWAP(b,q)−EMA21(q)|<=0.5A，且Cq>=AVWAP(b,q)−0.25A。
- 其余触发、排序、最高买价、退出全部同D03。

对D03另给出“锚点存在且数据完整”的匹配子样本事件诊断；不能把数据有无本身当AVWAP增量。实际主账户仍报告全部D03与受限D04各自表现、机会数量和现金使用。

### D05：J Law META启发的“事前支撑重合区”

公开方向为多种价格结构/趋势/支撑信息结合；不声称下面阈值是其META原公式。
- q时EMA21>EMA50，EMA21较5日前上升，Cq>EMA50，RS60>=0.70。
- A=ATR20(T−21)。在[T−30,T−6]找最近一次已确认20日高点突破b，B=max(Hb−20...Hb−1)。B在b时固定，视为此前突破水平。
- q时|B−EMA21(q)|<=0.5A，|Cq−B|<=0.75A，Lq<=B+0.25A。
- T收盘高于Hq、B及EMA21(T)。
- L=max(B,EMA21(q),Hq)+0.5A；S0=min(LT−5...LT)−0.1A。
- 排序：0.5RS60+0.5支撑重合紧密度百分位，紧密度原量=|B−EMA21(q)|/A，越低越好。
- 同一b只接受第一次满足条件的setup触发。

必须分清不同来源的信息。两条几乎相同的均线不能被包装成两个独立优势；本代理使用历史突破水平与平滑价格趋势，不是三个均线相加就叫多重优势。

### D06：Oliver Kell启发的“早期转强 / Wedge Pop代理”

不强制LONG_TT，也不强制站上200日线，否则会先排除要研究的早期阶段。
- A=ATR20(T−21)。l为[T−20,T−6]最低L所在日，等低取最早；要求Cl<EMA20(l)−A。
- 从l+1至T−6至少出现一个收盘>=Ll+A，代表先有反弹，而不是直接买下跌最低点。
- F=[T−5,T−1]，宽度maxH−minL<=2A，minL(F)>=Ll。
- q时|EMA10−EMA20|<=0.75A，Cq<=max(EMA10,EMA20)+0.5A。
- T收盘同时高于F最高价U、EMA10(T)、EMA20(T)。
- L=U+0.5A；S0=minL(F)−0.1A；排序RS20。
- 以l为事件键，仅首个合格触发；不把l称为事前已知最低点，只是在T时选择过去窗口的已发生低点，绝不回到l买入。

本代理不包含所有目测楔形/多周期语义，应明确标签EARLY_RESTART_PROXY，不能宣称复刻完整Wedge Pop。

### D07：D06后的第一次EMA回测恢复

以当时实际产生的D06信号b作为父事件，不要求父订单曾成交，不能只从后来赚钱的父事件取样。
- 使用父事件冻结的A、S0。观察b+1到b+20；只有先出现C>=EMA20+A，才进入“等待第一次回测”状态。
- 之后首日v满足Lv<=EMA20(v)+0.25A，记为第一次回测；v至少为b+2。
- 到v后第5日以内，首个T满足CT>HT−1且CT>EMA10(T)触发。父事件以来若收盘<S0则失效，不再用同一父事件寻找第二次“第一次”。
- L=HT−1+0.5A；新结构线=min(Lv...LT)−0.1A；排名RS20(T−1)。
- 20日期满、确认期满、触发一次或失效后该父事件结束。

这与D03的成熟趋势回调是不同时间顺序。不能因为都碰均线就合并，也不能未经对照就当作独立收益源。

### D08：Kell启发的后续Base n' Break

- 存在D06父事件b，距离T为16至60个交易日，b后无收盘跌破父S0。
- q时Cq>EMA10(q)>EMA20(q)，EMA20较5日前上升。
- b至T−11的最高收盘，至少比Cb高2个父事件A；先有明确延续，再讨论第二次整理。
- 最近10日F=[T−10,T−1]宽度<=3A，最后5日宽度小于前5日宽度。
- Cq>=max(H[T−30,T−11])−A。
- CT>maxH(F)=U；L=U+0.5A；S0=minL(F)−0.1A；排序RS60。
- 同父事件的同一10日整理只取首次；已触发后须经历至少10个新交易日才可生成下一整理，不连续每日追认。

### D09：Afzal启发的“突破前靠近枢轴参与”日线代理

Afzal公开体系包含突破前参与、价量结构和临近收盘决策。这里仍是日线后验确认、次日执行，不冒充真正尾盘交易。
- 使用D02在T−1已具备的LONG_TT、VCP Guard与Path/VCP排名，窗口不变。
- 不使用D02的“CT>U”触发；替代为U−0.3A0<=CT<=U、CT>OT、LT>=minL(F)。
- 次日最高买价L=U+0.1A0，S0=minL(F)−0.1A0。
- 其余排名同D02。若实际成交时已经高于U，标记CROSSED_BEFORE_FILL，不把实际已追入说成突破前低吸。

必要事件配对：从每个首次有效整理建立U/S0/A0固定的10日观察episode，对“提前参与”和“等首次收盘>U”分别记账；未突破、未成交、失效都保留。不能只在后来成功突破的样本上比较提前买入。该事件诊断不冒充新增完整现金账户回放。

### H01：Minervini收缩确认 → Luk式第一次回调

以D02全部信号作为父事件，b时不买；在随后15交易日等待第一次回调。
- 先出现b之后收盘>=Cb+0.5A0；之后首日v出现Lv<=max(Ub,EMA21(v))+0.25A0。
- 收盘不得跌破父S0；v后5日内首个CT>HT−1且CT>EMA9(T)触发。
- L=HT−1+0.5A0，S0=min(Lv...LT)−0.1A0；排序使用父D02分数与当日RS60各一半。
- 逾期、父结构失效、已触发则终止；不允许事后从多个回踩中挑最漂亮的一个。

重点回答：少追高是否真的改善收益/风险，还是主要错过不回头的强势股。父事件中未回调者必须进入机会损失统计。

### H02：J Law支撑重合 + 前段渐进上涨路径

与D05同样的候选、触发、订单上限、退出，只改变排序：
- 前段路径只计算在D05父突破b之前的30个交易日[b−30,b−1]；不含回调期和T。
- H02分数=0.5*D05原分数+0.5*该前段PathScore。该窗口无正收益贡献、导致集中度分母为0时，整项PathScore取中性0.5并标记NO_POSITIVE_PATH_SUPPORT；不因加排序指标而静默删掉D05候选。
- 不额外加入VCP、大盘过滤或量能条件。

这样能单独检查“到达支撑之前的上涨过程”是否有增量，而不是把所有冠军名词AND到一起。

## 6. 两种退出：入场与持有方式分开评估

E10：入场交易日e记0，e+10开盘安排退出；没有结构止损，用于入场基线。期间风险必须完整展示，不能只报10日终值。它是研究基线，不是推荐直接实盘部署。

EST：所有版本在T收盘已冻结S0。自入场日收盘开始，若C<=S0，下一可合法成交时点退出；持有满5交易日以后，若C<SMA10，同样下一开盘退出。没有触发则最迟e+40开盘退出。D00–D02沿用V2对应结构线；新增版本用各自S0。

已触发的卖出订单遇停牌/跌停/无流动性应持续待执行，不因之后反弹而删除。不能以收盘确认规则冒充盘中价格止损。不能保证S0对应的百分比就是实际最大损失。新买入或新加仓的lot按T+1分别处理。

卖出规则本轮不追加第三、第四种“最佳止盈”，不根据最好交易的MFE挑顶。加速与放量只保留诊断，不事后改成全体卖出信号。

## 7. 三种现金模式：必须先看尽可能投入的结果

研究初始资金统一100万元人民币，不增加外部资金，现金利息基线为0。任何时点现金>=0，总多头市值<=账户净资产；不得融资、做空、杠杆ETF、期货期权或预支尚未实现的收益。

C_MAX：最多10个不同证券，按信号优先级分配当时可合法使用现金，尽可能部署。对当前可容纳的n个新候选，先等分可用现金，在订单提交前，依据当时已知的容量、费用、合法股数限制，将受限候选剩余预算向其余原候选再等分，至没有可再分配容量，最多按入选候选数轮；合法取整后的零头按固定排名分配可买的最小单位。不依据实际开盘未成交结果追溯重分配，不临时改变排名。不强制卖掉旧持仓给更高分新信号腾挪。

C_10：最多10个不同证券，每笔新初始买入目标不超过决策时账户NAV的10%，按排名依次使用现金。持仓涨到超过10%不机械再平衡；不自动补足低于10%的仓位。

C_ONE：最多持有1个不同证券，空仓时把可用现金尽可能分配给第一名；未到既定退出不因新排名换股。它是“单票集中现金投入”的研究压力情景，不是实盘推荐。交易容量不足、订单价超限或其他明确风险模块约束时不能假称已满仓。

资金规则应精确读秒：收盘后为下一开盘预提交的买单，不得提前花同一集合竞价里尚未卖出股票的所得款。若实际引擎明确支持卖出成交后再发出新买单，使用后续时点和真实后续价格，不能同时仍按开盘价成交。日内可用卖出款与银行可取现金不同，不人为冻结一整天，也不提前透支。

入场默认订单有效期只到目标开盘撮合结束，未成交即撤，不拿后来最低价补成交。股票/板块最小申报、步长、费用、税、限价、tick、停牌、除权等用对应历史规则，不统一假设100股或统一涨跌停幅度。

若同一证券被多路线选择，在组合中只有一个物理持仓，可保留多策略虚拟标签，但不能重复赚一份同样交易收益；不允许两份名义资金买出超过实有现金的仓位。

## 8. 成交证据与成本压力

优先复用经过审计的历史执行引擎。信号成交价不是随意使用T收盘；买价必须<=事前L且在合法区间。开盘低于支撑的限价买单也可能成交，不能使用开盘以后才知道的坏形态悄悄取消。真实支持的盘前撤单条件必须有明确时间戳，否则只做事后分组。

有历史开盘竞价/首分钟成交证据时，按既有可信容量、滑点与排队规则回放。只有日线OHLC时，可以运行明确标为DAILY_OPEN_MODEL的保守执行代理，但不能宣称已验证真实竞价可成交；至少限制每笔名义额不超过此前20日成交额中位数的0.5%，全股票组合累计同向订单共享该容量。该日量上限只是容量保护，不能证明开盘有同样深度。

日线代理若开盘恰在涨停价，买入一律视为未成交；开盘恰在跌停价，卖出先视为延期。不要因为后来打开涨跌停就追溯为开盘已成交。没有成交/价格证据的情况保留订单失败原因，不能用“理应成交”填补。

基准费用优先用仓库已验证的历史税费与佣金假设并留档；确无既有佣金约定，可在读取结果前冻结佣金3bp、每笔最低5元，买卖双向另加10bp价格滑点，法定税费按历史生效日计。滑点不得把限价买单算到L以上，超过限价视为不成交。佣金/滑点是研究假设而非用户真实券商费率。

COST2：相同信号与可见信息，佣金假设、最低佣金和模拟滑点加倍；法定税费仍用真实历史税率。不得宣称法定税也真的加倍。

DELAY1：信号和特征冻结，入场推迟一个市场交易日至T+2开盘，仍用原L，不看T+1后来结果重新筛选。退出E10从实际成交日起计。保留延迟期间的失效和高开信息作诊断，但不补设事后取消规则。若原本T+1未成交，延迟情景仍按同一原始信号独立决定，不只挑原本成交的赢家。

新上证交易规则2026-07-06生效且有继续暂缓条款；不把2026规则套回全部历史，不把尚未实施条款视为可用。应核对沪深各历史版本并记录有效期。官方依据见RULES_SSE26。

## 9. 两个市场环境模块：独立于选股和退出

只使用仓库已授权、可靠的同一宽基市场序列M；优先既有全A市场表示，其次固定中证全指，不能依据收益择指数。冻结后全版本一致。缺失不可静默换为当天最有利指数。

定义（所有日线T信号统一使用q=T−1收盘，即t=q；分钟T信号也使用上一交易日收盘）：
BULL：M>=SMA60且SMA60>=其20日前值。
BEAR：M<SMA60且SMA60<其20日前值。
TRANSITION：其余。

G_DOWN：BEAR禁止新开仓，其余不限制；不强制平旧仓，不重写退出。这是V2市场否决思想的单独检验。

G_RAMP：从25%新开仓总敞口目标开始；上一日为BULL则目标增加25个百分点，BEAR降到0，其余减25个百分点且不低于0，目标不高于100%。只约束本次新买入可用额=max(0,目标*NAV−现有多头市值)，不强制卖出已有持仓。日期t的信息只影响之后订单。它是事前定义的渐进暴露代理，不是任何冠军本人精确仓位表。

只在D02、D03、D06、H02上分别加入G_DOWN/G_RAMP，均使用E10与三现金模式，24个情景。主矩阵相同策略无overlay是基线。不能同时再加入行业或选股过滤掩盖增量。

要报告与无过滤版相比的已参与/错失机会、实际仓位、市场暴露、现金拖累、风险下降与收益代价。用仓位机械降低解释得了的改善，不能全归为预测大盘成功。过去项目的breadth/conversion结论作为查重证据，不因冠军喜好而推翻。

## 10. 风险预算与一次盈利加仓：不是越跌越买

在D02、D03、D06、H02上，使用EST和三现金模式分别跑R_ONCE、R_STAGE，共24个情景；与主矩阵相同EST版本比较。预算是计划风险度量，不保证最大亏损。

共同规则：给订单的单位计划风险r=max(L−S0,0.5A)，避免极窄结构线产生近乎无限仓位；A为事件冻结ATR。L<=S0视为不合格，不能靠abs把方向错误掩盖。组合所有未退出lot的“入场成本至S0”计划预算加本次订单预算不得超过决策NAV的2%，单股票不得超过1%；同时受C_MAX/C_10/C_ONE现金与集中度约束。已有lot占用按股数*max(实际入场价−S0,0.5A)保存，未卖出前不因浮盈释放；新单按L预留、成交后按实际价回写。该预算衡量投入本金的事前风险，不包含已经产生的浮盈回吐，必须另报按当前市价到S0计算的风险敞口。

R_ONCE：首次入场按最多1%NAV/r确定数量，再受可用现金、模式上限、容量、合法股数与费用约束；不加仓。

R_STAGE：初始最多0.5%NAV/r。持有至少3个交易日、尚未发出退出指令时，若当日收盘>=初始实际买价+初始R，且此前3日宽度<=A、当日收盘>此前3日最高价，允许下一开盘一次加仓。初始R=初始实际买价−S0，必须>0。
- 加仓参考Uadd=此前3日最高价，Ladd=Uadd+0.5A。
- 加仓数量<=初始股数的一半，新增计划预算<=0.5%当时NAV；新增投入必须通过组合2%、单股票1%、现金/容量/模式上限。C_10下加仓后的预计该股票市值不得超过当时NAV的10%；C_ONE仍只允许原股票。价格波动导致已有头寸超过某预算上限时，只禁止进一步增加，不额外强平，不改变EST。
- S0不因为浮盈自动上抬来释放虚假的风险额度，全部lot仍按共同EST退出；40日最长持有从首次入场日起算。
- 加仓订单触发时已有或同次优先退出信号，则退出优先、取消加仓。新lot单独T+1，不能买入当天随旧仓一并假设卖出。
- 只加一次，不向下摊平，不增加杠杆，不把纸面浮盈当已收到现金。

R_ONCE与R_STAGE最大预设预算相同，差异是投入时序和触发，不宣称二者实际暴露永远完全相同。记录每个预算是否绑定、未能加仓原因、收益来自原仓还是加仓、加仓后尾部损失。若某现金模式下几乎没有可加资金，明确给出“模块在该模式不活跃”，不制造结果。

## 11. 四种组合政策：先保持方法独立，再融合资本

组合基础只用四个代表入口，避免给同一血统多分几票：
B= D02成熟突破；P= D03成熟趋势回调；R= D06早期转强；A= D09提前参与。

四者当日信号均按各自候选集合分数转为百分位，只有1个候选时取0.5。以当前有效新信号为候选，不用未来实现收益给策略打分。一个股票可有多个标签，但只接受一份物理订单。

P0_POOL：四路线共享现金，候选按其当日最高单路线百分位排序，平分时依次按已触发路线数、证券代码排序。多个标签并不等于独立确认；报告该选择规则的机会数偏差。

P1_BALANCED：仍共享现金，不为空路线保留闲置配额。每选择一个新候选，先找当前“虚拟归属已持仓市值+本轮已预分配额”最小的路线，再在其当日未占用候选中选最高分。多标签股票归属当次选中路线；同证券其他标签不再下单。路线同额时B/P/R/A固定顺序，选完一个后更新预分配并循环。C_ONE下只是空仓时选择路线/首名，不允许多持仓。

P2_PHASE：仅改变候选优先顺序，不另加市场清仓或仓位门槛。上一已知市场状态为BULL时路线次序B/P/A/R；TRANSITION为R/P/B/A；BEAR为P/R/B/A。先按路线优先，再按路线内分数，去重后照现金模式执行。这个顺序是事前假说，不是已验证结论；市场过滤作用由第9节另测。

P3_CORROBORATE：只接受今天有新信号、且截至今天最近5个交易日有至少两个不同入口家族发过信号的股票。B/P/R/A各算一类；VCP、VCP+Path不能算两个。旧信号如果其冻结结构已被已知收盘破坏或超期，不算确认。按家族数、今天最高分、证券代码排序；由今天最高分的有效信号提供L/S0/事件A；同分固定B/P/R/A。

P0–P3各跑三现金模式×E10/EST，24个情景。各订单共享资金和执行容量；不加杠杆、不允许同股票在四本账里各赚一遍。同日优先级、归属及退出管理在读收益前冻结。

必须给出各入口信号/股票/持仓日期/行业/收益相关与极端亏损共现，而不只相关系数。如果四条都在同一天押同一行业，明确“多个入口但不构成充分分散”。P1有效也不自动说明平均分配优于其他长期方案。

## 12. 六个条件性模块：合格才运行，但不能挑收益决定

每模块12个账户情景：基线/增强两臂×三现金模式×两种预定退出，共最多72。基线严格使用增强版相同覆盖、日期、预先数据资格；两个版本是否触发的差异保留，不能事后用增强版成交名单筛基线。

Q1 公告催化：D02基线 vs D02+最近20交易日首次公开的正向事件资格，退出E10/EST。
- 正向类别只用现有可靠PIT事件字典：业绩预增/扭亏、明确重大合同、重大资产重组方案、公司回购方案；分类细则和否定/终止/更正优先级在不看收益前固定。
- 这些是“宣布了某种事件”的标签，不等于事实一定兑现。不能将所有公告都叫利好。
- 截止q已公开，发布时间缺只有日期时保守顺延到下一交易日可用。未知覆盖不是无消息。存在后续修订保留版本，不用修订文本倒填。

Q2 已公布业绩：D02基线 vs D02排序加入20%最新可得单季度营收/利润同比增长分数，退出E10/EST。
- 正基数、可比口径同比可数值排名；亏损/扭亏分组，不把负基数百分比当超高速增长。
- 财报真实首次公布时间、季度累计拆分、重述版本严格PIT。不得用今天整理好的财报数据回到旧时间。
- 主配对集合只包括两项同比均可比且净利润基期>0的股票；不可比亏损/扭亏组仅作资格漏斗诊断，不临时创造填充值或新增策略。
- 仅是Tanmay/Minervini公开成长性思想的可观察部分，不声称自动度量了管理层可信度、市场空间或完整BEST。

Q3 真正尾盘提前参与：同一14:25信息集产生的D09式候选，比较次日开盘 vs 当日14:30以后首个可执行窗口，退出E10/EST。
- 所有此前结构仍截止T−1，触发仅用T当日截至14:25已结束bar构造的O/H/L/当前价，代替D09的当日OHLC；不可使用收盘价、全天成交量或14:25以后行情挑样本。
- 14:30起至14:35前，用逐分钟可见的合法成交和冻结限价/股数进行一次订单尝试。若仅有分钟OHLC，按保守成交模型并明确等级，不伪造盘口排队。
- 两臂同一冻结L和信号，不在次日臂重新看T收盘补确认。14:25临时量不能直接和历史全天量比较。
- 当日买入不得当日止损卖出。E10/EST持有计数从各自实际买入日开始；另外分解共同时钟退出的事件收益差异，不能把多持有一天误解释为入场改善。
- 此模块改变了时钟，不声称是Afzal本人逐条尾盘公式。

Q4 Gajjala日内动量启发的隔夜延续：不是复制原日内策略。
- 信息截止T 14:25，执行统一T 14:30–14:35首个可执行窗口；退场E1=e+1开盘或E3=e+3开盘，两种都按T+1合法处理。
- 用上一日ATR20=A。09:30至11:30的净涨幅>=1A，上午最高价较开盘>=1.5A，作为共同“上午冲击”资格；不硬选涨停/买不到的股票。
- BASE：该共同资格，14:25价格仍>=上午冲击从开盘到最高价的一半高度，且<=上午高点+0.5A。
- ENHANCED：BASE之外，最近30个已结束1分钟bar形成区间，宽度<=0.75A，最低价>=上午最高价−1A；其前15分钟区间宽度>后15分钟；14:25价格高于截至14:20结束的前25根bar最高价，同时不高于其上沿+0.5A。
- 两臂相同L=上午高点+0.5A，排序“截至14:25的开盘收益/A”同日百分位。股票池/分钟完整性匹配。
- 价格冲击和整理用不同时间段，午休不制造零成交bar。不是在同一根bar同时知道最高、最低并选最有利成交。
- 不引入已有库存做T，不开融券，不把T+0午后止损改成T+1却保留原风险宣称。

Q5 行业领导力：D02基线 vs 加20%行业RS60排名分数的D02，退出E10/EST。
- 历史行业分类、行业指数或成分构建必须当时可得；行业回报构建需排除本股票贡献或至少报告自包含影响，避免把自己涨幅又计为行业优势。
- 不用今天概念板块/热门题材名单回填；个股和行业涨幅作用分开。

Q6 公开事件锚定的回调：D03匹配基线 vs D03+公告锚定AVWAP合流，退出E10/EST。
- 两臂共同资格：q之前5至40个交易日内存在Q1合格事件且覆盖/金额/股数完整。
- 锚点为事件首次公开以后第一个完整交易日，不回溯公告前低点；若盘中发布，锚定下一完整交易日。多事件取最近，不根据后续表现择锚。
- 增强条件与D04相同，将价格突破锚b替换为事件锚；其他完全同D03。
- 与D04区别是经济锚点，不声称二者必然独立；分别报告重叠和差异。

数据gate最低要求：可靠时间戳或明确保守顺延、对照相同覆盖、无法用后验结果决定缺失、至少能识别“不存在”与“没数据”。分钟模块要有完整午休/session/14:25结束语义与复权桥。条件不合格，写NOT_RUN_DATA_GATE及具体缺口，不污染日线主线，不把模块算作完成。

## 13. 八个既有五策略影子组合情景（可选）

仅当原五策略冻结版本、真实账户引擎、样本权限与权威基线均已可复现时启用，不在本任务中重建或修改整个五策略系统。

I0：原五策略冻结资金方案，100万元，真实重放基线。
I1/I2/I3/I4：分别给D02、D03、D06、P1固定初始10%资金袖套，原五策略90%。
I5/I6/I7：分别给D02、D03、D06固定初始20%袖套，原五策略80%。
原五策略若原生包含ETF等既有工具，保持其冻结范围，不能因本轮新候选限普通股票而擅自删旧工具。新增袖套统一C_10+EST；袖套的10%单笔上限相对该袖套NAV，不相对整个账户NAV。两个部分独立复利、无借款、无日常再平衡；同一物理证券通过虚拟lot记录归属、共同实际容量和T+1。不能把两条历史NAV线简单加权代替缩小本金后的整手/费用/可执行回放。

I0基线不能伪称已复现，原五策略基线不可靠则八个全部标记BLOCKED_EXISTING_ACCOUNT_BASELINE。它们是影子对比，不改真实生产配置；不能用加入新策略后的历史最优权重重配五个旧策略。10%/20%是预登记幅度，不按结果继续扫描。

## 14. 情景矩阵与真实计数

核心A：12策略（D00–D09、H01、H02）×3现金×2退出=72。
核心B：同12策略×3现金×2压力（COST2/DELAY1），统一E10=72。
核心C：4策略（D02、D03、D06、H02）×3现金×2市场模块，统一E10=24。
核心D：同4策略×3现金×2风险投入方式，统一EST=24。
核心E：4组合政策×3现金×2退出=24。
核心合计216。
条件Q：6模块×2臂×3现金×2各自指定退出=72。
五策略I：8个固定账户=8。
本轮槽位上限296。旧V1/V2证据另册，不叠加成“366次独立验证”。

压缩成本的方法是共享信号/指标缓存、精确复用、断点续算，不是暗中删情景或删亏损年份。某些槽位实际生成相同交易是允许的，应标记行为等价，而不是把它们当独立支持证据。

运行状态至少区分：PLANNED_NOT_EXECUTED / RUNNING / COMPLETED_NEW / VERIFIED_REUSE / EXACT_DUPLICATE_EVIDENCE / NOT_RUN_DATA_GATE / BLOCKED_PERMISSION / BLOCKED_INPUT / INVALIDATED_BY_BUG / NO_ELIGIBLE_SIGNAL。

NO_ELIGIBLE_SIGNAL若真正完成全期扫描和现金账户回放，可记录零交易、全现金NAV完成；只猜信号少不算。提交作业、创建配置、产生一个日志行都不算完成。

## 15. 分析：不是只找最高收益的一行

第一层事件：触发数、可成交率、实际入场后1/3/5/10/20/40日收益的可适用诊断、首次不利变动、MFE/MAE、失败类型。必须区分信号前、信号到买入、买入后三段收益；最大浮盈不是实际赚到的钱。

第二层账户：完整逐日NAV、CAGR、最大回撤及持续时长、年度/月度收益、波动与回撤恢复、平均/最高暴露、空仓天数、资金利用率、集中度、成交成本、换手、盈亏比、胜率、尾部单笔和连续亏损。没有一条可靠指标可代替所有其他风险。

第三层增量：
- VCP/Path对普通趋势突破；AVWAP对同覆盖回调；META路径排序对META；早期转强与成熟趋势是否只是不同市场beta；提前买与确认买必须包含全部episode。
- 对此前累计涨幅、最大单日涨幅、波动率、beta、市值/流动性、行业等做匹配分层或简单预登记回归，不一下训练巨大模型。
- 同日、同时间段比较，区分admission/排序/成交价/持有时间/资金利用率的作用。
- 如果新规则改善主要来自增加现金/降低仓位，要明确；反过来C_ONE高回撤高收益也不能仅凭收益被列成最佳可用方案。

第四层稳健性：全部预授权年份、板块、既有开发/后验时间块、市场状态都展示；不按结果划分有利边界。每条路线给出年份贡献、最佳5个交易日/最佳5个股票贡献，标记集中性，不机械要求删掉所有大赢家还保持原收益。

跨日相关与同日共振不能当独立交易数。对预登记配对差异可使用20交易日块的成对bootstrap，固定种子、1000次，给出不确定区间；样本不足就说明，不用“显著/不显著”替代经济大小。多情景完整登记，不能从296个最大值宣称独立统计发现。未经真正独立未来样本，最高仅探索性影子证据。已有封存验证不因为本轮需要而打开。

没有事后冠军加赛：不得把最高收益的20个变体再拿去调参数；不追加随机窗口网格、基于全期拟合的动态权重或大规模机器学习。运行很多次不等于证据很强。

最终至少给四种结果视角，而非一个总冠军：
1. 纯收益上界/集中风险视角；2. 收益—回撤可接受性视角；3. 相对简单基线的净增量视角；4. 真实成交与容量可实施性视角。

任何收益改善都需回答是否值得占用组合资本。独立策略正收益不等于对既有五策略有增益；多名冠军共享一个因子也不等于多源alpha。

## 16. 实际执行顺序与资源适配

阶段1：只读环境/权限/旧实验与来源核验，冻结定义、情景manifest和最小共同数据契约。验证：所有296槽位ID唯一，核心216，条件72，I8；时间轴无相互矛盾。

阶段2：复用数据与引擎、实现必要模块、局部小样本测试。验证：截断数据前缀不变、单线程/分块一致、拐点known_at正确、原始价格/复权桥、T+1/限价/费用/持仓/现金对账。失败先修，不能产出明知错误的大规模结果。

阶段3：先跑A核心72账户，同时在独立I/O队列审计Q数据资格；不要等全部新闻/财报数据完美才跑日线。随后B/C/D/E全部预登记情景，无论第一阶段赚赔都执行，除真实阻塞/精确重复。

阶段4：运行通过数据gate的Q模块及通过账户gate的I模块。阶段5：统计、交叉对账、报告、真实复现、提交/推送。

各阶段是调度顺序，不是允许只完成前两步就停。持续写checkpoint，长任务自动恢复已完成分片，不因上下文压缩重新下载或重跑已验证结果。不要承诺无法估计的完成时刻。

先识别可用CPU、RAM、外接盘速度、已有任务占用；并发自适应。优先按日期/股票分块一次生成共用特征，再多账户重放；全市场rank必须在合并完整日截面后做。内存吃紧时减workers、缩chunk、流式写列式文件，不缩股票池、不截去坏年份、不偷改样本权限。

网络/依赖/路径问题可修则自行解决并继续；付费购买、申请交易权限、读取新封存样本、破坏其他进程不在授权中。无关数据缺口只阻塞相应模块。大样本生成仍需检查真实行数/日期覆盖/哈希，不把空文件当成功。

## 17. 必须通过的测试与审计样例

- Prefix invariance：同一截止日，仅输入该日前数据，信号/锚点/分数必须等于完整历史到该日输出；随机抽样并覆盖拐点确认、公告修订、财报重述。
- 至少验证上涨趋势、早期未站上长期均线、没有回调、回调失效、连续同日多信号、无锚点、金额单位错误、停牌与陈旧价、涨跌停、跨除权日、同次卖买不可预支、费用导致不足一手、C_ONE只能一只、加仓lot不可当日卖、延期卖出不得遗忘。
- 状态机不可挑未来：D07首次回测失败后不得重选；H01没有回踩的父事件不得消失；D09没有突破的提前买入仍计损益。
- 对随机和边界样本输出decision_at、known_at、entry_at、source timestamp与决定字段，人工抽查；不只查看最终收益最高的图。
- 现金+持仓市值与NAV逐日恒等，交易数量/费用/现金变化可对账；同股票同一容量不得被多个虚拟策略重复使用。
- 单线程与分块/并发生成相同排序与成交；平分处理固定，重跑结果确定。
- 小型已知手算账户与现有可靠基线先过账，再全历史；核心结果抽取部分日期和完整代表情景实际重新运行复现。

## 18. 交付物、裁决与最终状态

保持文件结构轻便：
SPEC.md、SOURCE_REGISTER.json、SCENARIO_MANIFEST.json、REPORT.md、scenario_summary.csv、VERDICT.json、RUN_CHECKPOINT.json；大信号/订单/成交/逐日NAV/统计结果放实际外接盘并在manifest保存路径与hash。不要让报告只剩几十个难懂英文状态码。

REPORT.md必须有普通中文的策略解释、12入口/对照结果、3资金模式、2退出、4组合政策、Q数据与结果、I可行性、错误修复影响、缺口及最终推荐。附全部情景表，不只前十名。真实执行命令写已验证的命令，不写未经运行的理想命令。

每路线分别给：ALREADY_COVERED / NO_INCREMENTAL_EDGE / COMPONENT_ONLY / POSITIVE_EXPLORATORY_EVIDENCE / INSUFFICIENT_EVIDENCE；执行结论FEASIBLE_UNDER_STATED_ASSUMPTIONS / EXECUTION_FRAGILE / NOT_ASSESSABLE；部署REJECT / SHADOW_ONLY / NOT_ASSESSABLE。

需要关闭的是本轮确切机械定义，不泛化为“某冠军无效”。需要保留的是可核查的具体机制和执行条件，不是最高回测收益对应的人名。没有明显赢家也必须完成矩阵、解释失败，不无限试到盈利为止。

提交仅本任务相关小文件，检查密钥、隐私、大件和无关修改。确认现有远程/身份/凭据允许后正常提交与push本分支；不force push。不能假称已提交/已推送。

最终状态块：
ENVIRONMENT_VALID:
REPO / BRANCH / BASE_HEAD / START_HEAD / END_HEAD:
TASK_STATUS:
METHOD_LABEL: CHAMPION_INSPIRED_MECHANICAL_A_SHARE_PROXIES_NOT_REPLICATIONS
CHAMPIONS_RESULTS_VERIFIED_THROUGH: 2025_FINAL
CURRENT_YEAR_STATUS: 2026_INTERIM_NOT_CHAMPIONS
SAMPLE_PERMISSION_STATUS / HISTORY_ACTUALLY_USED:
NEW_SEALED_VALIDATION_OPENED: NO
RUNNING_V1_V2_OR_FIVE_STRATEGIES_DISTURBED: NO
FROZEN_PRODUCTION_STRATEGIES_MODIFIED: NO
CORE_SLOTS: 216
DATA_CONDITIONAL_SLOTS_MAX: 72
FIVE_STRATEGY_INTEGRATION_SLOTS_MAX: 8
NEWLY_EXECUTED / VERIFIED_REUSED / ZERO_SIGNAL_REPLAYED:
EXACT_DUPLICATE_EVIDENCE / NOT_RUN_WITH_REASON / INVALIDATED_BY_BUG:
LEGACY_EVIDENCE_REUSED_SEPARATELY:
TEMPORAL_LEAKAGE_CHECK / CASH_AND_LOT_ACCOUNTING_CHECK:
EXECUTION_EVIDENCE_GRADE / Q1_TO_Q6_GATES / I_GATE:
RESEARCH_VERDICT / EXECUTION_VERDICT / DEPLOYMENT_VERDICT:
BEST_RETURN_CASE / BEST_RISK_TRADEOFF_CASE / BEST_INCREMENTAL_CASE:
REMAINING_LIMITATIONS:
REPORT_PATH / REPRODUCE_COMMAND / TESTS_ACTUALLY_RUN:
COMMIT / PUSH:

现在开始连续推进。常规可解决的问题自行处理，真正阻塞准确报告；不得以“Prompt已阅读/研究计划已完成/测试通过”替代实际研究。

## 19. 来源登记与方法声明

下面仅列可核验出处和简短方法方向，不复制付费内容或完整访谈。视频来源仅在本次工具实际可见标题/发布页/简介的范围内使用，不能宣称已获取全部字幕。网页改变或失效时保留本轮核验记录，不从营销二手文章补造精确原法。

**[R25] 主办方2025年度最终结果**

来源：https://www.businesswire.com/news/home/20260202090143/en/Multiple-World-Records-Set-in-International-Investing-Competition

可支持：Martin Luk 969.8%；J Law 252.3%，连续第二年百万以上股票组第一。

访问层级：FULL_TEXT。边界：年度账户成绩，不是公开完整策略和日净值；不要与增强成长组混淆。

**[R24] 主办方2024年度最终结果**

来源：https://www.businesswire.com/news/home/20250127956815/en/2024-United-States-Investing-Championship-Final-Results

可支持：Judy Lai 449.1%；J Law 353.9%，分别为两个股票组第一。

访问层级：FULL_TEXT。边界：Judy另一个组别273.8%为第二；不能混写。

**[R23] 主办方2023年度最终结果**

来源：https://www.businesswire.com/news/home/20240126217806/en/United-States-Investing-Championship-2023-Final-Results

可支持：Goverdhan Gajjala 805.1%；Tanmay Khandelwal 129%；Afzal 500.2%为第二。

访问层级：FULL_TEXT。边界：区分股票与增强成长组，成绩不能证明A股代理。

**[R22] 主办方2022年度最终结果**

来源：https://www.businesswire.com/news/home/20230125005300/en/United-States-Investing-Championship-2022-Final-Standings

可支持：Afzal Lokhandwala 447%；Sam Bhatia 13.5%，分别为两个股票组第一。

访问层级：FULL_TEXT。边界：没有公开Sam的完整机械策略。

**[R21] 主办方2021年度最终结果**

来源：https://www.businesswire.com/news/home/20220124005241/en/2021-United-States-Investing-Championship-Winners-Minervini-Smashes-Record

可支持：Pavel P. Sterba 222.3%；Mark Minervini 334.8%；公告也提到Minervini 1997第一。

访问层级：FULL_TEXT。边界：当前V3没有新增Pavel专属公式。

**[R20] 主办方2020年度最终结果**

来源：https://www.businesswire.com/news/home/20210125005140/en/U.S.-Investing-Championship-2020-Final-Standings

可支持：Oliver Kell 941.1%；George Tkaczuk 119.1%。

访问层级：FULL_TEXT。边界：不同资金组成绩不可忽略约束直接比较。

**[CURRENT26] 主办方首页与2026中期榜单**

来源：https://financial-competitions.com/

可支持：核验时显示截至2026-07-31七个月成绩；官网说明股票组可做多、做空、杠杆、外国股票等。

访问层级：FULL_TEXT。边界：动态页面；2026没有全年最终冠军，本研究不追逐暂时领先者。

**[CONTEST_RULES] 主办方比赛规则**

来源：https://financial-competitions.com/rules

可支持：股票/增强成长与账户级别分组，外国参赛及外国股票，指定账户与对账单核验。

访问层级：FULL_TEXT。边界：规则可变；股票组也不等于无杠杆现金做多。

**[LUK_ESSAY] Martin Luk本人确认的客座文章**

来源：https://tradingresourcehub.substack.com/p/martin-luk-283-usic-2024-key-lessons

可支持：EMA强弱分组、关注行业中新增强势股、等待下一次回调、风险与减少过度交易。

访问层级：FULL_TEXT。边界：2025-02-01文章讨论2024经历；不是2025夺冠全年每一笔交易说明。

**[LUK_INTERVIEW26] Martin Luk夺冠后原始访谈发布页**

来源：https://www.youtube.com/watch?v=VKNEJA5r8zw

可支持：原始访谈主题明确为回调交易方法。

访问层级：TITLE_AND_DESCRIPTION_ONLY。边界：本次未取得完整字幕；不得声称听完全文或归纳全部原法。

**[LUK_AVWAP] 原访谈方发布的AVWAP片段**

来源：https://www.youtube.com/shorts/Vy7K5x5ctoQ?vl=en

可支持：可确认其公开内容涉及锚定VWAP。

访问层级：TITLE_AND_DESCRIPTION_ONLY。边界：不能据此确定唯一锚点；D04和Q6的锚定方式是本轮代理。

**[JLAW_TEXT] J Law署名问答**

来源：https://traderlion.com/profile/j-law/11-lessons-from-j-law/

可支持：按市场与公司情况调整持有方式、考察趋势和支撑信息、回调参与、比赛杠杆与日常风险偏好的区别。

访问层级：FULL_TEXT。边界：公开原则不是全部META精确公式，原人的做空/杠杆不迁移。

**[JLAW_META] J Law本人趋势线与多重优势教学**

来源：https://www.youtube.com/watch?v=zbb09zSKYts

可支持：其本人公开讲解趋势线及多重优势进场方向。

访问层级：TITLE_AND_DESCRIPTION_ONLY。边界：本次未取得完整字幕；D05用历史突破水平+EMA是我们固定的代理。

**[KELL_CYCLE] Oliver Kell署名价格循环讲解**

来源：https://traderlion.com/technical-analysis/chart-patterns/cycle-of-price-action-by-oliver-kell/

可支持：早期转强、EMA回测、后续整理突破分阶段，使用10/20EMA等。

访问层级：FULL_TEXT。边界：目测多周期结构不能被简单代理完整复制；不采用营销成功率或因果宣称。

**[KELL_OWN] Oliver Kell本人周线评论**

来源：https://weeklieswatch.substack.com/p/holding-weekly-moving-averages

可支持：本人使用Wedge Pop及EMA Crossback等阶段概念。

访问层级：FULL_TEXT。边界：具体市场案例不作为代理训练标签，不等于所有周期均有效。

**[AFZAL_SYSTEM] Afzal本人网站公开体系大纲**

来源：https://afzallokhandwala.com/system/

可支持：价量波段、突破前参与、临近收盘决策及分步加仓等方向。

访问层级：FULL_TEXT_OF_PUBLIC_OUTLINE。边界：大纲不是付费规则全文；不虚构TRP公式，不照搬杠杆或期货做空。

**[TANMAY_INTERVIEW] Tanmay原始访谈发布方介绍**

来源：https://www.elearnmarkets.com/face2face/details/investing-championship-trading-strategies-revealed

可支持：投资研究结合成长潜力、业绩、可靠性与相对强度。

访问层级：PUBLISHER_SUMMARY_ONLY。边界：摘要不是逐字稿且含“首位印度冠军”等不可靠泛称；冠军以主办方为准，不复制该泛称。

**[TANMAY_FIRM] TwoX当前方法说明**

来源：https://twoxcapital.com/

可支持：当前公开描述包括基本面与催化方向。

访问层级：PUBLIC_PAGE。边界：当前基金/产品不等于2023比赛账户的完整原始策略，不反推当年规则。

**[GAJJALA_INTERVIEW] Gajjala原始日内交易访谈**

来源：https://open.spotify.com/episode/0nLtjYtu7LJC42lpLFEfwG

可支持：访谈主题为2023冠军的日内交易入场。

访问层级：TITLE_AND_EPISODE_METADATA_ONLY。边界：本次未完整读取字幕/音频；Q4旗形阈值为本轮独立假说，不声称原公式。

**[GAJJALA_WEBINAR] Gajjala原始交易讲座**

来源：https://www.youtube.com/watch?v=CI7mNvEQyms

可支持：提供原始教学入口供后续核对。

访问层级：TITLE_AND_DESCRIPTION_ONLY。边界：不从无法读取的内容推断精确参数。

**[TKACZUK_METHOD] George Tkaczuk作者方法介绍**

来源：https://tradersexclusive.com/george_tkaczuk/

可支持：增长股票与市场走弱时增加现金的管理方向。

访问层级：FULL_TEXT。边界：原介绍还包含反向ETF；本任务不迁移反向ETF，不把G_RAMP写成本人仓位公式。

**[MINERVINI_BOOK] Minervini著作的出版社目录**

来源：https://www.mheducation.com/highered/mhp/product/trade-like-stock-market-wizard-how-achieve-super-performance-stocks-any-market.html

可支持：趋势、行业、催化、经营表现、盈利质量与风险管理等内容。

访问层级：PUBLIC_DESCRIPTION_PREVIOUS_V2。边界：V2机械定义是研究代理；非书籍全部规则代码化。

**[MINERVINI_INTERVIEW] Minervini原始访谈文字稿**

来源：https://seekingalpha.com/article/4425132-stock-trader-mark-minervini-and-market-strategist-ben-laidler-join-alpha-trader-podcast-transcript

可支持：由左向右收紧和接近明确失效位置参与的方向。

访问层级：TEXT_PREVIOUS_V2。边界：继承自V2来源核验；运行时可复核，但不因网页失效乱改冻结V2。

**[RULES_SSE26] 上交所2026交易规则发布及生效通知**

来源：https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml

可支持：2026-07-06生效、部分条款继续暂缓；需使用对应日期真实制度。

访问层级：NOTICE_FULL_TEXT_AND_INDEXED_RULE_EXCERPTS。边界：通知不是全部历史制度表；执行时须核对正文附件、暂缓附件及历史版本。

**[STAR_LOTS] 上交所科创板申报数量官方投教**

来源：https://edu.sse.com.cn/tib/ysptj/c/4869120.shtml

可支持：科创板申报单位不应统一硬编码为100股整手，须核对具体制度。

访问层级：FULL_TEXT。边界：历史2019说明；当前与其他板块仍以对应时期有效规则为准。

## 20. 文件校验与附录使用

附录A的V2原文件SHA256：f47df85cdd6e098d4a355dda2940c3e6fef749d935a64fb6225387c6fadef0ee
附录A按原始文本保留；来源核验后的V3新结论、样本边界和任务范围以上方主文为准。请不要再次启动附录中的旧工作树或要求旧任务停止。

### 预登记情景ID索引（全部状态为PLANNED_NOT_EXECUTED）

这是配置登记，不是已经回测完成的结果。结构化研究包内另含等价JSON清单。

| ID | 信号/政策 | 资金 | 退出 | 压力/模块/分臂 | 资格 |
|---|---|---|---|---|---|
| A_D00_C_MAX_E10 | D00 | C_MAX | E10 | BASE | CORE |
| A_D00_C_MAX_EST | D00 | C_MAX | EST | BASE | CORE |
| A_D00_C_10_E10 | D00 | C_10 | E10 | BASE | CORE |
| A_D00_C_10_EST | D00 | C_10 | EST | BASE | CORE |
| A_D00_C_ONE_E10 | D00 | C_ONE | E10 | BASE | CORE |
| A_D00_C_ONE_EST | D00 | C_ONE | EST | BASE | CORE |
| A_D01_C_MAX_E10 | D01 | C_MAX | E10 | BASE | CORE |
| A_D01_C_MAX_EST | D01 | C_MAX | EST | BASE | CORE |
| A_D01_C_10_E10 | D01 | C_10 | E10 | BASE | CORE |
| A_D01_C_10_EST | D01 | C_10 | EST | BASE | CORE |
| A_D01_C_ONE_E10 | D01 | C_ONE | E10 | BASE | CORE |
| A_D01_C_ONE_EST | D01 | C_ONE | EST | BASE | CORE |
| A_D02_C_MAX_E10 | D02 | C_MAX | E10 | BASE | CORE |
| A_D02_C_MAX_EST | D02 | C_MAX | EST | BASE | CORE |
| A_D02_C_10_E10 | D02 | C_10 | E10 | BASE | CORE |
| A_D02_C_10_EST | D02 | C_10 | EST | BASE | CORE |
| A_D02_C_ONE_E10 | D02 | C_ONE | E10 | BASE | CORE |
| A_D02_C_ONE_EST | D02 | C_ONE | EST | BASE | CORE |
| A_D03_C_MAX_E10 | D03 | C_MAX | E10 | BASE | CORE |
| A_D03_C_MAX_EST | D03 | C_MAX | EST | BASE | CORE |
| A_D03_C_10_E10 | D03 | C_10 | E10 | BASE | CORE |
| A_D03_C_10_EST | D03 | C_10 | EST | BASE | CORE |
| A_D03_C_ONE_E10 | D03 | C_ONE | E10 | BASE | CORE |
| A_D03_C_ONE_EST | D03 | C_ONE | EST | BASE | CORE |
| A_D04_C_MAX_E10 | D04 | C_MAX | E10 | BASE | CORE |
| A_D04_C_MAX_EST | D04 | C_MAX | EST | BASE | CORE |
| A_D04_C_10_E10 | D04 | C_10 | E10 | BASE | CORE |
| A_D04_C_10_EST | D04 | C_10 | EST | BASE | CORE |
| A_D04_C_ONE_E10 | D04 | C_ONE | E10 | BASE | CORE |
| A_D04_C_ONE_EST | D04 | C_ONE | EST | BASE | CORE |
| A_D05_C_MAX_E10 | D05 | C_MAX | E10 | BASE | CORE |
| A_D05_C_MAX_EST | D05 | C_MAX | EST | BASE | CORE |
| A_D05_C_10_E10 | D05 | C_10 | E10 | BASE | CORE |
| A_D05_C_10_EST | D05 | C_10 | EST | BASE | CORE |
| A_D05_C_ONE_E10 | D05 | C_ONE | E10 | BASE | CORE |
| A_D05_C_ONE_EST | D05 | C_ONE | EST | BASE | CORE |
| A_D06_C_MAX_E10 | D06 | C_MAX | E10 | BASE | CORE |
| A_D06_C_MAX_EST | D06 | C_MAX | EST | BASE | CORE |
| A_D06_C_10_E10 | D06 | C_10 | E10 | BASE | CORE |
| A_D06_C_10_EST | D06 | C_10 | EST | BASE | CORE |
| A_D06_C_ONE_E10 | D06 | C_ONE | E10 | BASE | CORE |
| A_D06_C_ONE_EST | D06 | C_ONE | EST | BASE | CORE |
| A_D07_C_MAX_E10 | D07 | C_MAX | E10 | BASE | CORE |
| A_D07_C_MAX_EST | D07 | C_MAX | EST | BASE | CORE |
| A_D07_C_10_E10 | D07 | C_10 | E10 | BASE | CORE |
| A_D07_C_10_EST | D07 | C_10 | EST | BASE | CORE |
| A_D07_C_ONE_E10 | D07 | C_ONE | E10 | BASE | CORE |
| A_D07_C_ONE_EST | D07 | C_ONE | EST | BASE | CORE |
| A_D08_C_MAX_E10 | D08 | C_MAX | E10 | BASE | CORE |
| A_D08_C_MAX_EST | D08 | C_MAX | EST | BASE | CORE |
| A_D08_C_10_E10 | D08 | C_10 | E10 | BASE | CORE |
| A_D08_C_10_EST | D08 | C_10 | EST | BASE | CORE |
| A_D08_C_ONE_E10 | D08 | C_ONE | E10 | BASE | CORE |
| A_D08_C_ONE_EST | D08 | C_ONE | EST | BASE | CORE |
| A_D09_C_MAX_E10 | D09 | C_MAX | E10 | BASE | CORE |
| A_D09_C_MAX_EST | D09 | C_MAX | EST | BASE | CORE |
| A_D09_C_10_E10 | D09 | C_10 | E10 | BASE | CORE |
| A_D09_C_10_EST | D09 | C_10 | EST | BASE | CORE |
| A_D09_C_ONE_E10 | D09 | C_ONE | E10 | BASE | CORE |
| A_D09_C_ONE_EST | D09 | C_ONE | EST | BASE | CORE |
| A_H01_C_MAX_E10 | H01 | C_MAX | E10 | BASE | CORE |
| A_H01_C_MAX_EST | H01 | C_MAX | EST | BASE | CORE |
| A_H01_C_10_E10 | H01 | C_10 | E10 | BASE | CORE |
| A_H01_C_10_EST | H01 | C_10 | EST | BASE | CORE |
| A_H01_C_ONE_E10 | H01 | C_ONE | E10 | BASE | CORE |
| A_H01_C_ONE_EST | H01 | C_ONE | EST | BASE | CORE |
| A_H02_C_MAX_E10 | H02 | C_MAX | E10 | BASE | CORE |
| A_H02_C_MAX_EST | H02 | C_MAX | EST | BASE | CORE |
| A_H02_C_10_E10 | H02 | C_10 | E10 | BASE | CORE |
| A_H02_C_10_EST | H02 | C_10 | EST | BASE | CORE |
| A_H02_C_ONE_E10 | H02 | C_ONE | E10 | BASE | CORE |
| A_H02_C_ONE_EST | H02 | C_ONE | EST | BASE | CORE |
| B_D00_C_MAX_COST2 | D00 | C_MAX | E10 | COST2 | CORE |
| B_D00_C_MAX_DELAY1 | D00 | C_MAX | E10 | DELAY1 | CORE |
| B_D00_C_10_COST2 | D00 | C_10 | E10 | COST2 | CORE |
| B_D00_C_10_DELAY1 | D00 | C_10 | E10 | DELAY1 | CORE |
| B_D00_C_ONE_COST2 | D00 | C_ONE | E10 | COST2 | CORE |
| B_D00_C_ONE_DELAY1 | D00 | C_ONE | E10 | DELAY1 | CORE |
| B_D01_C_MAX_COST2 | D01 | C_MAX | E10 | COST2 | CORE |
| B_D01_C_MAX_DELAY1 | D01 | C_MAX | E10 | DELAY1 | CORE |
| B_D01_C_10_COST2 | D01 | C_10 | E10 | COST2 | CORE |
| B_D01_C_10_DELAY1 | D01 | C_10 | E10 | DELAY1 | CORE |
| B_D01_C_ONE_COST2 | D01 | C_ONE | E10 | COST2 | CORE |
| B_D01_C_ONE_DELAY1 | D01 | C_ONE | E10 | DELAY1 | CORE |
| B_D02_C_MAX_COST2 | D02 | C_MAX | E10 | COST2 | CORE |
| B_D02_C_MAX_DELAY1 | D02 | C_MAX | E10 | DELAY1 | CORE |
| B_D02_C_10_COST2 | D02 | C_10 | E10 | COST2 | CORE |
| B_D02_C_10_DELAY1 | D02 | C_10 | E10 | DELAY1 | CORE |
| B_D02_C_ONE_COST2 | D02 | C_ONE | E10 | COST2 | CORE |
| B_D02_C_ONE_DELAY1 | D02 | C_ONE | E10 | DELAY1 | CORE |
| B_D03_C_MAX_COST2 | D03 | C_MAX | E10 | COST2 | CORE |
| B_D03_C_MAX_DELAY1 | D03 | C_MAX | E10 | DELAY1 | CORE |
| B_D03_C_10_COST2 | D03 | C_10 | E10 | COST2 | CORE |
| B_D03_C_10_DELAY1 | D03 | C_10 | E10 | DELAY1 | CORE |
| B_D03_C_ONE_COST2 | D03 | C_ONE | E10 | COST2 | CORE |
| B_D03_C_ONE_DELAY1 | D03 | C_ONE | E10 | DELAY1 | CORE |
| B_D04_C_MAX_COST2 | D04 | C_MAX | E10 | COST2 | CORE |
| B_D04_C_MAX_DELAY1 | D04 | C_MAX | E10 | DELAY1 | CORE |
| B_D04_C_10_COST2 | D04 | C_10 | E10 | COST2 | CORE |
| B_D04_C_10_DELAY1 | D04 | C_10 | E10 | DELAY1 | CORE |
| B_D04_C_ONE_COST2 | D04 | C_ONE | E10 | COST2 | CORE |
| B_D04_C_ONE_DELAY1 | D04 | C_ONE | E10 | DELAY1 | CORE |
| B_D05_C_MAX_COST2 | D05 | C_MAX | E10 | COST2 | CORE |
| B_D05_C_MAX_DELAY1 | D05 | C_MAX | E10 | DELAY1 | CORE |
| B_D05_C_10_COST2 | D05 | C_10 | E10 | COST2 | CORE |
| B_D05_C_10_DELAY1 | D05 | C_10 | E10 | DELAY1 | CORE |
| B_D05_C_ONE_COST2 | D05 | C_ONE | E10 | COST2 | CORE |
| B_D05_C_ONE_DELAY1 | D05 | C_ONE | E10 | DELAY1 | CORE |
| B_D06_C_MAX_COST2 | D06 | C_MAX | E10 | COST2 | CORE |
| B_D06_C_MAX_DELAY1 | D06 | C_MAX | E10 | DELAY1 | CORE |
| B_D06_C_10_COST2 | D06 | C_10 | E10 | COST2 | CORE |
| B_D06_C_10_DELAY1 | D06 | C_10 | E10 | DELAY1 | CORE |
| B_D06_C_ONE_COST2 | D06 | C_ONE | E10 | COST2 | CORE |
| B_D06_C_ONE_DELAY1 | D06 | C_ONE | E10 | DELAY1 | CORE |
| B_D07_C_MAX_COST2 | D07 | C_MAX | E10 | COST2 | CORE |
| B_D07_C_MAX_DELAY1 | D07 | C_MAX | E10 | DELAY1 | CORE |
| B_D07_C_10_COST2 | D07 | C_10 | E10 | COST2 | CORE |
| B_D07_C_10_DELAY1 | D07 | C_10 | E10 | DELAY1 | CORE |
| B_D07_C_ONE_COST2 | D07 | C_ONE | E10 | COST2 | CORE |
| B_D07_C_ONE_DELAY1 | D07 | C_ONE | E10 | DELAY1 | CORE |
| B_D08_C_MAX_COST2 | D08 | C_MAX | E10 | COST2 | CORE |
| B_D08_C_MAX_DELAY1 | D08 | C_MAX | E10 | DELAY1 | CORE |
| B_D08_C_10_COST2 | D08 | C_10 | E10 | COST2 | CORE |
| B_D08_C_10_DELAY1 | D08 | C_10 | E10 | DELAY1 | CORE |
| B_D08_C_ONE_COST2 | D08 | C_ONE | E10 | COST2 | CORE |
| B_D08_C_ONE_DELAY1 | D08 | C_ONE | E10 | DELAY1 | CORE |
| B_D09_C_MAX_COST2 | D09 | C_MAX | E10 | COST2 | CORE |
| B_D09_C_MAX_DELAY1 | D09 | C_MAX | E10 | DELAY1 | CORE |
| B_D09_C_10_COST2 | D09 | C_10 | E10 | COST2 | CORE |
| B_D09_C_10_DELAY1 | D09 | C_10 | E10 | DELAY1 | CORE |
| B_D09_C_ONE_COST2 | D09 | C_ONE | E10 | COST2 | CORE |
| B_D09_C_ONE_DELAY1 | D09 | C_ONE | E10 | DELAY1 | CORE |
| B_H01_C_MAX_COST2 | H01 | C_MAX | E10 | COST2 | CORE |
| B_H01_C_MAX_DELAY1 | H01 | C_MAX | E10 | DELAY1 | CORE |
| B_H01_C_10_COST2 | H01 | C_10 | E10 | COST2 | CORE |
| B_H01_C_10_DELAY1 | H01 | C_10 | E10 | DELAY1 | CORE |
| B_H01_C_ONE_COST2 | H01 | C_ONE | E10 | COST2 | CORE |
| B_H01_C_ONE_DELAY1 | H01 | C_ONE | E10 | DELAY1 | CORE |
| B_H02_C_MAX_COST2 | H02 | C_MAX | E10 | COST2 | CORE |
| B_H02_C_MAX_DELAY1 | H02 | C_MAX | E10 | DELAY1 | CORE |
| B_H02_C_10_COST2 | H02 | C_10 | E10 | COST2 | CORE |
| B_H02_C_10_DELAY1 | H02 | C_10 | E10 | DELAY1 | CORE |
| B_H02_C_ONE_COST2 | H02 | C_ONE | E10 | COST2 | CORE |
| B_H02_C_ONE_DELAY1 | H02 | C_ONE | E10 | DELAY1 | CORE |
| C_D02_C_MAX_G_DOWN | D02 | C_MAX | E10 | G_DOWN | CORE |
| C_D02_C_MAX_G_RAMP | D02 | C_MAX | E10 | G_RAMP | CORE |
| C_D02_C_10_G_DOWN | D02 | C_10 | E10 | G_DOWN | CORE |
| C_D02_C_10_G_RAMP | D02 | C_10 | E10 | G_RAMP | CORE |
| C_D02_C_ONE_G_DOWN | D02 | C_ONE | E10 | G_DOWN | CORE |
| C_D02_C_ONE_G_RAMP | D02 | C_ONE | E10 | G_RAMP | CORE |
| C_D03_C_MAX_G_DOWN | D03 | C_MAX | E10 | G_DOWN | CORE |
| C_D03_C_MAX_G_RAMP | D03 | C_MAX | E10 | G_RAMP | CORE |
| C_D03_C_10_G_DOWN | D03 | C_10 | E10 | G_DOWN | CORE |
| C_D03_C_10_G_RAMP | D03 | C_10 | E10 | G_RAMP | CORE |
| C_D03_C_ONE_G_DOWN | D03 | C_ONE | E10 | G_DOWN | CORE |
| C_D03_C_ONE_G_RAMP | D03 | C_ONE | E10 | G_RAMP | CORE |
| C_D06_C_MAX_G_DOWN | D06 | C_MAX | E10 | G_DOWN | CORE |
| C_D06_C_MAX_G_RAMP | D06 | C_MAX | E10 | G_RAMP | CORE |
| C_D06_C_10_G_DOWN | D06 | C_10 | E10 | G_DOWN | CORE |
| C_D06_C_10_G_RAMP | D06 | C_10 | E10 | G_RAMP | CORE |
| C_D06_C_ONE_G_DOWN | D06 | C_ONE | E10 | G_DOWN | CORE |
| C_D06_C_ONE_G_RAMP | D06 | C_ONE | E10 | G_RAMP | CORE |
| C_H02_C_MAX_G_DOWN | H02 | C_MAX | E10 | G_DOWN | CORE |
| C_H02_C_MAX_G_RAMP | H02 | C_MAX | E10 | G_RAMP | CORE |
| C_H02_C_10_G_DOWN | H02 | C_10 | E10 | G_DOWN | CORE |
| C_H02_C_10_G_RAMP | H02 | C_10 | E10 | G_RAMP | CORE |
| C_H02_C_ONE_G_DOWN | H02 | C_ONE | E10 | G_DOWN | CORE |
| C_H02_C_ONE_G_RAMP | H02 | C_ONE | E10 | G_RAMP | CORE |
| D_D02_C_MAX_R_ONCE | D02 | C_MAX | EST | R_ONCE | CORE |
| D_D02_C_MAX_R_STAGE | D02 | C_MAX | EST | R_STAGE | CORE |
| D_D02_C_10_R_ONCE | D02 | C_10 | EST | R_ONCE | CORE |
| D_D02_C_10_R_STAGE | D02 | C_10 | EST | R_STAGE | CORE |
| D_D02_C_ONE_R_ONCE | D02 | C_ONE | EST | R_ONCE | CORE |
| D_D02_C_ONE_R_STAGE | D02 | C_ONE | EST | R_STAGE | CORE |
| D_D03_C_MAX_R_ONCE | D03 | C_MAX | EST | R_ONCE | CORE |
| D_D03_C_MAX_R_STAGE | D03 | C_MAX | EST | R_STAGE | CORE |
| D_D03_C_10_R_ONCE | D03 | C_10 | EST | R_ONCE | CORE |
| D_D03_C_10_R_STAGE | D03 | C_10 | EST | R_STAGE | CORE |
| D_D03_C_ONE_R_ONCE | D03 | C_ONE | EST | R_ONCE | CORE |
| D_D03_C_ONE_R_STAGE | D03 | C_ONE | EST | R_STAGE | CORE |
| D_D06_C_MAX_R_ONCE | D06 | C_MAX | EST | R_ONCE | CORE |
| D_D06_C_MAX_R_STAGE | D06 | C_MAX | EST | R_STAGE | CORE |
| D_D06_C_10_R_ONCE | D06 | C_10 | EST | R_ONCE | CORE |
| D_D06_C_10_R_STAGE | D06 | C_10 | EST | R_STAGE | CORE |
| D_D06_C_ONE_R_ONCE | D06 | C_ONE | EST | R_ONCE | CORE |
| D_D06_C_ONE_R_STAGE | D06 | C_ONE | EST | R_STAGE | CORE |
| D_H02_C_MAX_R_ONCE | H02 | C_MAX | EST | R_ONCE | CORE |
| D_H02_C_MAX_R_STAGE | H02 | C_MAX | EST | R_STAGE | CORE |
| D_H02_C_10_R_ONCE | H02 | C_10 | EST | R_ONCE | CORE |
| D_H02_C_10_R_STAGE | H02 | C_10 | EST | R_STAGE | CORE |
| D_H02_C_ONE_R_ONCE | H02 | C_ONE | EST | R_ONCE | CORE |
| D_H02_C_ONE_R_STAGE | H02 | C_ONE | EST | R_STAGE | CORE |
| E_P0_POOL_C_MAX_E10 | P0_POOL | C_MAX | E10 | BASE | CORE |
| E_P0_POOL_C_MAX_EST | P0_POOL | C_MAX | EST | BASE | CORE |
| E_P0_POOL_C_10_E10 | P0_POOL | C_10 | E10 | BASE | CORE |
| E_P0_POOL_C_10_EST | P0_POOL | C_10 | EST | BASE | CORE |
| E_P0_POOL_C_ONE_E10 | P0_POOL | C_ONE | E10 | BASE | CORE |
| E_P0_POOL_C_ONE_EST | P0_POOL | C_ONE | EST | BASE | CORE |
| E_P1_BALANCED_C_MAX_E10 | P1_BALANCED | C_MAX | E10 | BASE | CORE |
| E_P1_BALANCED_C_MAX_EST | P1_BALANCED | C_MAX | EST | BASE | CORE |
| E_P1_BALANCED_C_10_E10 | P1_BALANCED | C_10 | E10 | BASE | CORE |
| E_P1_BALANCED_C_10_EST | P1_BALANCED | C_10 | EST | BASE | CORE |
| E_P1_BALANCED_C_ONE_E10 | P1_BALANCED | C_ONE | E10 | BASE | CORE |
| E_P1_BALANCED_C_ONE_EST | P1_BALANCED | C_ONE | EST | BASE | CORE |
| E_P2_PHASE_C_MAX_E10 | P2_PHASE | C_MAX | E10 | BASE | CORE |
| E_P2_PHASE_C_MAX_EST | P2_PHASE | C_MAX | EST | BASE | CORE |
| E_P2_PHASE_C_10_E10 | P2_PHASE | C_10 | E10 | BASE | CORE |
| E_P2_PHASE_C_10_EST | P2_PHASE | C_10 | EST | BASE | CORE |
| E_P2_PHASE_C_ONE_E10 | P2_PHASE | C_ONE | E10 | BASE | CORE |
| E_P2_PHASE_C_ONE_EST | P2_PHASE | C_ONE | EST | BASE | CORE |
| E_P3_CORROBORATE_C_MAX_E10 | P3_CORROBORATE | C_MAX | E10 | BASE | CORE |
| E_P3_CORROBORATE_C_MAX_EST | P3_CORROBORATE | C_MAX | EST | BASE | CORE |
| E_P3_CORROBORATE_C_10_E10 | P3_CORROBORATE | C_10 | E10 | BASE | CORE |
| E_P3_CORROBORATE_C_10_EST | P3_CORROBORATE | C_10 | EST | BASE | CORE |
| E_P3_CORROBORATE_C_ONE_E10 | P3_CORROBORATE | C_ONE | E10 | BASE | CORE |
| E_P3_CORROBORATE_C_ONE_EST | P3_CORROBORATE | C_ONE | EST | BASE | CORE |
| Q1_BASE_C_MAX_E10 | D02 | C_MAX | E10 | Q1 | PIT_CATALYST |
| Q1_BASE_C_MAX_EST | D02 | C_MAX | EST | Q1 | PIT_CATALYST |
| Q1_BASE_C_10_E10 | D02 | C_10 | E10 | Q1 | PIT_CATALYST |
| Q1_BASE_C_10_EST | D02 | C_10 | EST | Q1 | PIT_CATALYST |
| Q1_BASE_C_ONE_E10 | D02 | C_ONE | E10 | Q1 | PIT_CATALYST |
| Q1_BASE_C_ONE_EST | D02 | C_ONE | EST | Q1 | PIT_CATALYST |
| Q1_ENHANCED_C_MAX_E10 | D02 | C_MAX | E10 | Q1/ENHANCED | PIT_CATALYST |
| Q1_ENHANCED_C_MAX_EST | D02 | C_MAX | EST | Q1/ENHANCED | PIT_CATALYST |
| Q1_ENHANCED_C_10_E10 | D02 | C_10 | E10 | Q1/ENHANCED | PIT_CATALYST |
| Q1_ENHANCED_C_10_EST | D02 | C_10 | EST | Q1/ENHANCED | PIT_CATALYST |
| Q1_ENHANCED_C_ONE_E10 | D02 | C_ONE | E10 | Q1/ENHANCED | PIT_CATALYST |
| Q1_ENHANCED_C_ONE_EST | D02 | C_ONE | EST | Q1/ENHANCED | PIT_CATALYST |
| Q2_BASE_C_MAX_E10 | D02 | C_MAX | E10 | Q2 | PIT_FUNDAMENTALS |
| Q2_BASE_C_MAX_EST | D02 | C_MAX | EST | Q2 | PIT_FUNDAMENTALS |
| Q2_BASE_C_10_E10 | D02 | C_10 | E10 | Q2 | PIT_FUNDAMENTALS |
| Q2_BASE_C_10_EST | D02 | C_10 | EST | Q2 | PIT_FUNDAMENTALS |
| Q2_BASE_C_ONE_E10 | D02 | C_ONE | E10 | Q2 | PIT_FUNDAMENTALS |
| Q2_BASE_C_ONE_EST | D02 | C_ONE | EST | Q2 | PIT_FUNDAMENTALS |
| Q2_ENHANCED_C_MAX_E10 | D02 | C_MAX | E10 | Q2/ENHANCED | PIT_FUNDAMENTALS |
| Q2_ENHANCED_C_MAX_EST | D02 | C_MAX | EST | Q2/ENHANCED | PIT_FUNDAMENTALS |
| Q2_ENHANCED_C_10_E10 | D02 | C_10 | E10 | Q2/ENHANCED | PIT_FUNDAMENTALS |
| Q2_ENHANCED_C_10_EST | D02 | C_10 | EST | Q2/ENHANCED | PIT_FUNDAMENTALS |
| Q2_ENHANCED_C_ONE_E10 | D02 | C_ONE | E10 | Q2/ENHANCED | PIT_FUNDAMENTALS |
| Q2_ENHANCED_C_ONE_EST | D02 | C_ONE | EST | Q2/ENHANCED | PIT_FUNDAMENTALS |
| Q3_BASE_C_MAX_E10 | D09_1425 | C_MAX | E10 | Q3 | MINUTE_TAIL |
| Q3_BASE_C_MAX_EST | D09_1425 | C_MAX | EST | Q3 | MINUTE_TAIL |
| Q3_BASE_C_10_E10 | D09_1425 | C_10 | E10 | Q3 | MINUTE_TAIL |
| Q3_BASE_C_10_EST | D09_1425 | C_10 | EST | Q3 | MINUTE_TAIL |
| Q3_BASE_C_ONE_E10 | D09_1425 | C_ONE | E10 | Q3 | MINUTE_TAIL |
| Q3_BASE_C_ONE_EST | D09_1425 | C_ONE | EST | Q3 | MINUTE_TAIL |
| Q3_ENHANCED_C_MAX_E10 | D09_1425 | C_MAX | E10 | Q3/ENHANCED | MINUTE_TAIL |
| Q3_ENHANCED_C_MAX_EST | D09_1425 | C_MAX | EST | Q3/ENHANCED | MINUTE_TAIL |
| Q3_ENHANCED_C_10_E10 | D09_1425 | C_10 | E10 | Q3/ENHANCED | MINUTE_TAIL |
| Q3_ENHANCED_C_10_EST | D09_1425 | C_10 | EST | Q3/ENHANCED | MINUTE_TAIL |
| Q3_ENHANCED_C_ONE_E10 | D09_1425 | C_ONE | E10 | Q3/ENHANCED | MINUTE_TAIL |
| Q3_ENHANCED_C_ONE_EST | D09_1425 | C_ONE | EST | Q3/ENHANCED | MINUTE_TAIL |
| Q4_BASE_C_MAX_E1 | INTRADAY_IMPULSE_OVERNIGHT | C_MAX | E1 | Q4 | MINUTE_INTRADAY |
| Q4_BASE_C_MAX_E3 | INTRADAY_IMPULSE_OVERNIGHT | C_MAX | E3 | Q4 | MINUTE_INTRADAY |
| Q4_BASE_C_10_E1 | INTRADAY_IMPULSE_OVERNIGHT | C_10 | E1 | Q4 | MINUTE_INTRADAY |
| Q4_BASE_C_10_E3 | INTRADAY_IMPULSE_OVERNIGHT | C_10 | E3 | Q4 | MINUTE_INTRADAY |
| Q4_BASE_C_ONE_E1 | INTRADAY_IMPULSE_OVERNIGHT | C_ONE | E1 | Q4 | MINUTE_INTRADAY |
| Q4_BASE_C_ONE_E3 | INTRADAY_IMPULSE_OVERNIGHT | C_ONE | E3 | Q4 | MINUTE_INTRADAY |
| Q4_ENHANCED_C_MAX_E1 | INTRADAY_IMPULSE_OVERNIGHT | C_MAX | E1 | Q4/ENHANCED | MINUTE_INTRADAY |
| Q4_ENHANCED_C_MAX_E3 | INTRADAY_IMPULSE_OVERNIGHT | C_MAX | E3 | Q4/ENHANCED | MINUTE_INTRADAY |
| Q4_ENHANCED_C_10_E1 | INTRADAY_IMPULSE_OVERNIGHT | C_10 | E1 | Q4/ENHANCED | MINUTE_INTRADAY |
| Q4_ENHANCED_C_10_E3 | INTRADAY_IMPULSE_OVERNIGHT | C_10 | E3 | Q4/ENHANCED | MINUTE_INTRADAY |
| Q4_ENHANCED_C_ONE_E1 | INTRADAY_IMPULSE_OVERNIGHT | C_ONE | E1 | Q4/ENHANCED | MINUTE_INTRADAY |
| Q4_ENHANCED_C_ONE_E3 | INTRADAY_IMPULSE_OVERNIGHT | C_ONE | E3 | Q4/ENHANCED | MINUTE_INTRADAY |
| Q5_BASE_C_MAX_E10 | D02 | C_MAX | E10 | Q5 | PIT_INDUSTRY |
| Q5_BASE_C_MAX_EST | D02 | C_MAX | EST | Q5 | PIT_INDUSTRY |
| Q5_BASE_C_10_E10 | D02 | C_10 | E10 | Q5 | PIT_INDUSTRY |
| Q5_BASE_C_10_EST | D02 | C_10 | EST | Q5 | PIT_INDUSTRY |
| Q5_BASE_C_ONE_E10 | D02 | C_ONE | E10 | Q5 | PIT_INDUSTRY |
| Q5_BASE_C_ONE_EST | D02 | C_ONE | EST | Q5 | PIT_INDUSTRY |
| Q5_ENHANCED_C_MAX_E10 | D02 | C_MAX | E10 | Q5/ENHANCED | PIT_INDUSTRY |
| Q5_ENHANCED_C_MAX_EST | D02 | C_MAX | EST | Q5/ENHANCED | PIT_INDUSTRY |
| Q5_ENHANCED_C_10_E10 | D02 | C_10 | E10 | Q5/ENHANCED | PIT_INDUSTRY |
| Q5_ENHANCED_C_10_EST | D02 | C_10 | EST | Q5/ENHANCED | PIT_INDUSTRY |
| Q5_ENHANCED_C_ONE_E10 | D02 | C_ONE | E10 | Q5/ENHANCED | PIT_INDUSTRY |
| Q5_ENHANCED_C_ONE_EST | D02 | C_ONE | EST | Q5/ENHANCED | PIT_INDUSTRY |
| Q6_BASE_C_MAX_E10 | D03 | C_MAX | E10 | Q6 | PIT_EVENT_AVWAP |
| Q6_BASE_C_MAX_EST | D03 | C_MAX | EST | Q6 | PIT_EVENT_AVWAP |
| Q6_BASE_C_10_E10 | D03 | C_10 | E10 | Q6 | PIT_EVENT_AVWAP |
| Q6_BASE_C_10_EST | D03 | C_10 | EST | Q6 | PIT_EVENT_AVWAP |
| Q6_BASE_C_ONE_E10 | D03 | C_ONE | E10 | Q6 | PIT_EVENT_AVWAP |
| Q6_BASE_C_ONE_EST | D03 | C_ONE | EST | Q6 | PIT_EVENT_AVWAP |
| Q6_ENHANCED_C_MAX_E10 | D03 | C_MAX | E10 | Q6/ENHANCED | PIT_EVENT_AVWAP |
| Q6_ENHANCED_C_MAX_EST | D03 | C_MAX | EST | Q6/ENHANCED | PIT_EVENT_AVWAP |
| Q6_ENHANCED_C_10_E10 | D03 | C_10 | E10 | Q6/ENHANCED | PIT_EVENT_AVWAP |
| Q6_ENHANCED_C_10_EST | D03 | C_10 | EST | Q6/ENHANCED | PIT_EVENT_AVWAP |
| Q6_ENHANCED_C_ONE_E10 | D03 | C_ONE | E10 | Q6/ENHANCED | PIT_EVENT_AVWAP |
| Q6_ENHANCED_C_ONE_EST | D03 | C_ONE | EST | Q6/ENHANCED | PIT_EVENT_AVWAP |
| I0_BASELINE | FROZEN_FIVE_STRATEGIES | NATIVE | NATIVE | BASE; 新袖套0% | EXISTING_ACCOUNT_BASELINE |
| I1_D02_10PCT | D02 | SLEEVE_C_10 | EST | BASE; 新袖套10% | EXISTING_ACCOUNT_BASELINE |
| I2_D03_10PCT | D03 | SLEEVE_C_10 | EST | BASE; 新袖套10% | EXISTING_ACCOUNT_BASELINE |
| I3_D06_10PCT | D06 | SLEEVE_C_10 | EST | BASE; 新袖套10% | EXISTING_ACCOUNT_BASELINE |
| I4_P1_BALANCED_10PCT | P1_BALANCED | SLEEVE_C_10 | EST | BASE; 新袖套10% | EXISTING_ACCOUNT_BASELINE |
| I5_D02_20PCT | D02 | SLEEVE_C_10 | EST | BASE; 新袖套20% | EXISTING_ACCOUNT_BASELINE |
| I6_D03_20PCT | D03 | SLEEVE_C_10 | EST | BASE; 新袖套20% | EXISTING_ACCOUNT_BASELINE |
| I7_D06_20PCT | D06 | SLEEVE_C_10 | EST | BASE; 新袖套20% | EXISTING_ACCOUNT_BASELINE |


---
# 附录A：V2原始任务全文（含其V1附录，仅供定义继承与证据复用）

# Codex / Astra 自主研究任务 V2
# Minervini 启发的 A 股趋势—收缩—突破策略：与“渐进走强”研究的受控融合

版本：2026-09-08 / V2
授权范围：历史研究、必要实现与相关错误修复、测试、落盘、正常提交与推送。不是实盘交易授权。

请完整阅读本文件，然后实际执行。不要只给计划，不要停在环境审计、合同冻结或单元测试。

## 0. 唯一主问题与执行边界

主问题：在真实 A 股现金账户与历史交易制度下，Minervini 启发的趋势模板、逐轮收缩结构，与前段渐进上涨路径结合，是否提供超出普通强势突破、相对强度、Low-MAX、低波动和市场/行业共同走势的可交易增量？

A 股适配必须检验而非预设：
- 大盘回落期间的相对抗跌，是否是有用信息，还是低 beta / 低波动的另一种表达？
- 大盘状态是否应该限制新开仓，还是仅解释机会数量？
- 价格逐轮收缩之外，成交量变化是否还有增量？
- 有可靠历史时点数据时，行业领导力、公司公开催化、已公布业绩增长，是否分别改善选股？
- 在不虚构买入日止损能力的前提下，较长持有赢家的退出方式是否改善可实现收益？

不预设“A 股没有投资价值”或“所有行情由庄家控制”。本任务可以只研究几天到几周的交易收益，但不能因此排除真实基本面信息，也不能用无法验证的主力意图解释一切。

禁止用日线量价直接标注“庄家已吸筹完成 / 洗盘结束 / 即将拉升 / 正在出货”。使用可观测状态、时间戳和可反驳的假说。禁止非公开信息交易、诱导交易、操纵行情或真实下单。

本任务研究的是 MINERVINI_INSPIRED_MECHANICAL_A_SHARE_PROXY，不是宣称完整复制本人 SEPA、VCP 目测判断、选股判断、盘中执行和仓位管理。

完成口径：58 个必需情景（含原 V1 的20个），以及最多12个有数据资格才运行的条件性情景，共最多70个。计数规则见第10节。少量可复用历史结果须验证一致性并单列，不能冒充本轮新运行。

## 1. 与旧 Prompt 的关系：保留旧证据，独立扩展

本文件是自包含的 V2 任务。附录 A 完整保留 V1 原文，作为旧策略定义和旧20个情景的冻结对照合同。

优先级：本文件 V2 主文负责环境、执行顺序、总情景数、新模块及最终汇报；附录 A 负责旧 V1 的具体策略/执行/资金/分析定义。附录中的旧分支名、仅研究20个情景、禁止任何退出扩展，仅适用于其原始 V1 任务，不阻止本文件明确限定的新实验。

不能把附录 A 当第二个独立任务，另开一个互相抢资源的进程。不能改写旧 V1 定义、覆盖旧结果，然后继续使用原来的实验编号。

若 V1 已经在运行：读取 checkpoint，保护原进程/工作树，等待其自然产出或安全复用已完成缓存；不要杀进程，不争用同一写入文件，不切换其分支。
若 V1 已完成：仅当输入区间、数据版本、策略定义、执行引擎、成本和配置一致且产物可核验时复用。报告 VERIFIED_REUSE，并记录来源。
若发现真实会计/时间/成交 bug：保留旧产物，明确标记失效范围，用 correction run 重跑受影响情景；不能把修 bug 的收益变化归功于新策略。

旧文 SHA256：906b8fbf29d474f24ccd9179a88595d698ab19c4c9e00923539dd4a955fc4d71
旧文文件名：Codex_Astra_渐进走强_高位整理_完整研究Prompt.md

## 2. 环境与权限：独立工作树，不碰五策略生产线

定位线索，不是当前 Git 事实：
- /Users/linmei/Documents/CY，预期 origin 为 LinmeiHu/CY。
- /Users/linmei/Documents/CY-supermind-v6-autonomous-20260830。
- /Users/linmei/Documents/CY-oversold-reversal-ranking。
- V1 建议分支 research/clean-ascent-consolidation-v1。
- V2 建议分支 research/minervini-ashare-clean-ascent-v2。
- V2 建议工作树 /Users/linmei/Documents/CY-worktrees/minervini-ashare-clean-ascent-20260908。
- V2 研究目录 research/minervini_ashare_clean_ascent/。

只读核验 repo、origin、branch、HEAD、status、worktree list、AGENTS.md、正在运行的有关任务及可复用模块。选择真实可追溯的 BASE_HEAD，解释原因。确认身份后可以自行创建/恢复本任务独立分支和工作树，无须为常规实现选择反复询问用户。

禁止 reset --hard、git clean、强制 checkout、强推、替用户 stash 无关修改。禁止切换或修改正在运行的五策略工作树。只改本任务所需代码；不得进行全仓库整理和顺手重构。

样本权限继承项目台账，不因“融合 Minervini”“换分支”或“别的策略用过”而自动获得新权限。不得打开新的 sealed validation。已看过的年份不能重新宣称独立验证。
对权限不明的区间隔离，继续已获准区间。不得用封存数据的结果或价格走势决定是否启用它。

## 3. 查重与语义预检：不把旧失败换名重跑

只读查阅与以下内容真正相关的旧研究：普通突破/动量、Low-MAX、低波动、相对强度、RS加速过滤、路径质量、支撑保持、市场广度、下行韧性、冲击恢复、行业共振、深跌反转。

对每个新增模块记录 EXACT_DUPLICATE / PARTIAL_OVERLAP / NEW_TESTABLE_QUESTION，附股票池、时间尺度、确认时点、执行方式、对照和证据路径。

禁止两种错误：
- 仅因为旧实验出现“突破”“恢复”“韧性”等字眼就关闭所有相关家族。
- 仅改变名称、窗口或加入名人标签就宣布是新机制。

尤其核对项目中“breadth 能解释机会，但不一定改善 conversion”的证据。市场影响存在，不等于择时规则必然改善账户收益。旧研究若已精确拒绝相同的相对抗跌表示，复用其证据或列为必要控制；不要偷偷做 threshold rescue。

正式读取本轮结果前，写简短 Semantic Preflight：
ECONOMIC_SEQUENCE / CAUSAL_BACKGROUND / STATE_VARIABLES / EVENT_FORMATION_TIME / CONFIRMATION_TRIGGER / ENTRY_TIME / OUTCOME_START_TIME / POSSIBLE_SEMANTIC_AMBIGUITIES / CHOSEN_TIME_ANCHORS。

核心顺序：
已形成的上涨与领导力 → 形成整理及多轮回撤 → 整理右侧收紧 → 突破确认 → 合法可执行入场 → 事后收益。

Cause 不可直接观察；State、Trigger、Outcome 必须分开。公告的首次公开时点与价格形态形成时点也必须分开，不得把后来公布的消息当成此前吸筹的已知原因。

## 4. 新增 N 系列的共同样本与时间轴

旧 V1 保持30日上涨＋5日整理不变。N系列增加较长整理窗口，不能将 N 与旧 V1 的差异全部归于某一个指标。

N 系列在交易日 T 收盘后决策：
- A：T−60 至 T−31，共30个交易日的前段收益，起点参考收盘价为 T−61。
- W：T−30 至 T−1，共30个交易日的整理/收缩形成窗口。
- F：T−5 至 T−1，W 的最后5个交易日，为右侧紧凑区。
- 波动尺度 A0：在 T−31 已知的20日ATR，整个 W 内固定。
- 信号：T 日收盘价高于 F 的最高价 U。
- 入场：T+1 开盘的预先提交限价订单；执行规则见第8节。
- 主退出：买入交易日索引 e，在 e+10 开盘安排退出。

除突破确认、明确声明的突破日成交量外，特征截止 T−1。前段 Path 只能使用 A，不得把 W 和 T 的表现倒算进“此前上涨很干净”。

股票池复用可靠历史普通 A 股池，排除信号时 ST/*ST，不包含 ETF。保留退市证券和历史状态。各板块/交易制度单列。
所有 N 版本，包括不使用趋势模板的 N0，使用同一基础历史覆盖要求：在 T−31 已具备252个交易日所需历史，并有完整的 A/W 输入。因此本轮不涵盖所有次新股，不可声称复制 Minervini 的 IPO 交易。

基础强势候选：A 段累计收益为正，位于同日同交易制度板块的前30%。所有横截面百分位在完整同日组中计算，不因分块只在局部股票子集排序。

在读取收益前冻结 N 系列共同的量价及市场数据可用集合。若某增强模块因真实缺失必须缩小覆盖，对应基线也必须使用相同覆盖；不得拿缺失较少的子集增强版与完整 N4 直接归因比较。优先在主矩阵生成前解决共同覆盖，真实大面积缺失则标记相关模块受阻，不为凑足情景伪造数据或隐瞒删样本。

真实停牌、陈旧报价、无成交和数据缺失须区分。不能把停牌日删除后把30日窗口压缩成30根有成交的K线；也不能把停牌的平线当成波动收缩。

## 5. 趋势模板：长期参考与中周期对照，不预设短周期更适合 A 股

### 5.1 LONG_TT 机械参考

在 q=T−31 和 q=T−1 两个时点均检查：
1. Cq > SMA50q > SMA150q > SMA200q。
2. SMA200q > SMA200(q−20)。这是“一月整体方向向上”的固定代理，不要求每天单调上升。
3. Cq ≥ 1.30 × 过去252交易日最低价。
4. Cq ≥ 0.75 × 过去252交易日最高价。
5. 过去252日收益在同日同板块基础历史股票池的百分位 ≥ 0.70。

第5项是自己计算的 RS_PROXY_252，不是 IBD 的专有 Relative Strength Rating，更不是 RSI。不得冒称精确复现商业评级。
均线是简单移动平均。52周用252交易日近似；高低价和收益采用一致且无未来公司行动污染的口径。

本模板是事先冻结的文献启发机械参考，不是对完整 SEPA 的复刻。若核查原始来源发现不同表述，记录差异；不能看过结果后替换阈值。

### 5.2 MEDIUM_TT 唯一周期适配对照

仅将上述均线三元组从50/150/200改为20/60/120，并将慢均线向上条件改为 SMA120q > SMA120(q−20)。其余252日高低价、RS代理、股票池、两个评估锚点及交易规则均不变。

这仅检验较短均线响应是否有帮助。不能据“A股投机”就断言必须把全部窗口缩短，也不额外扫10/30/60、30/90/180等组合。

## 6. Path、VCP 与成交量：形态定义不能偷换

### 6.1 PathScore

继承 V1 的 P1 回撤负担、P2 前三大上涨日贡献集中度公式，但只计算 N 系列自己的 A 窗口。
两个低值方向百分位得分等权，得到 PathScore。
RSScore 为 A 段累计收益的同日同板块百分位。

### 6.2 动态 VCP：先识别已经确认的回撤腿

“最近几天ATR低”“布林带窄”不等于 VCP。必须区别静态安静与逐轮回撤变浅。

为避免目测和未来函数，本轮固定使用简单的2左＋2右局部拐点法：
- 局部高/低点中心日为 k，其确认时间是 k+2 收盘。
- 只有 k−2 和 k+2 都在 W 内、且确认时间不晚于 T−1 的拐点可用。
- 并列极值取窗口中最早发生者，规则固定。若同一根日线同时被识别为高点和低点，不能凭日线推断盘中顺序；将该根标为歧义并跳过该根的两个拐点。
- 按发生日期组成交替高低点序列。连续同类点保留更极端者；并列保留较早者。用当时可见的序列做 as-of 快照，不能把后来更新的最终序列倒灌给旧信号。
- 每个“高点→随后低点”是一个完整回撤腿，二者都必须已确认。
- 固定取 W 内最近至多3个完整回撤腿，不寻找最漂亮的子段。至少需要2个完整腿。
- 每条腿 D_j=(H_high_j−L_low_j)/H_high_j，且 D_j>0。
- 若最后已确认低点之后又出现更低价而新低点尚未确认，当前形态视为仍在形成，不可继续沿用旧低点冒充末次收缩底。

VCP_GUARD：至少2个上述完整腿，按时间 D1>D2（有第三个时还须 D2>D3），且末段 F 不含停牌、零成交或 H=L 的单价平线。必须输出每条腿的起止、确认时点、深度和不合格原因。

这是一种受控的日线 VCP 代理，会遗漏某些人工认可的形态；不能因效果不好就换一种拐点算法现场救活，也不能宣称它覆盖所有 VCP。

对合格结构计算：
- V1：末次回撤深度 / 首次回撤深度，越低越好。
- V2：F 的最高价−最低价，再除以 A0，越低越好。
- V3：max(0, W 最高价−F 最低价)/A0，越低越好，描述右侧维持高位。

在同日同板块的合格结构中，将三个低值方向百分位等权，得 VCPScore。VCP不合格不是缺失数据，而是形态未满足；N3/N4等明确要求 VCP_GUARD 的版本不准入。

同时保留静态波动与前段收益等控制，防止把低波动本身当成动态收缩增量。没有形成逐轮收缩的普通突破仍保留在 N0/N1/N2 对照中。

### 6.3 VolumeScore：独立增量，不贴“吸筹完成”标签

量价主实验不以缩量作为所有版本的必要条件。只在 N8/N9 增加量能排序。

Q1：F 的日成交量中位数 / W 前20日成交量中位数；再除以同日同板块对应比值的中位数，用来消除全市场一起缩量的一部分影响。越低得分越高。
Q2：T 日成交量 / T−20至T−1 的日成交量中位数；再用同日同板块的相同比值中位数归一化。越高得分越高。
VolumeScore = 0.5×Q1低值方向百分位 + 0.5×Q2高值方向百分位。

注意：除以同日同板块的一个正数常量不会改变该组内百分位排名。上述市场归一化只服务于跨日状态诊断，不得冒称它额外改变了组内排序或已经完成完整的市场中性化；全市场同步量能变化的影响仍需通过日期分层和对照检验。

T日量只能在收盘后用于排名，不得用来预知 T 日盘中突破。成交量需处理拆合股等口径；优先复用可信历史量能/换手实现，无可靠流通股历史时不伪造换手率。
缺量数据不填0制造“极致缩量”。必须单列一字涨跌停造成的价格/成交受约束、报价陈旧和流动性枯竭，不能将其解释成正常供给收缩。

## 7. A 股市场环境：解释、选股、择时三个作用分开

### 7.1 市场基准与相对抗跌 MRScore

优先复用已有可信、历史可用的全A宽基日收益序列；在读结果前冻结唯一基准。若没有，允许用前一日历史股票池形成可追溯等权市场序列，但须处理停牌和退市并记录重建方法。不能用今天的指数成分回填历史。

用截至 T−31 的前120个交易日估计个股对市场日收益的简单 OLS beta（含截距），在 W 中冻结。W 内市场收益<0的交易日为“市场下跌日”，不能用个股未来最差日挑观察窗口。

Resilience = 这些下跌日中 r_i,s − beta_pre×r_market,s 的中位数。
MRScore 为其同日同板块百分位，越高得分越高。下跌日不足5天则 MRScore=0.5并标记 LOW_SUPPORT，不把没有接受市场压力检验的股票当成高抗跌。
若 beta 输入不足或市场方差无效，显式标记；不得用0冒充可靠估计。N6/N9应在一致可用覆盖上回放并说明覆盖限制，不能删掉难年份。

MRScore 只是市场条件下的残差表现，不证明主力控盘。必须检查它是否被 beta、波动率、此前收益或交易不活跃解释。不得在本任务里扩展成新的下跌恢复特征家族。

### 7.2 MarketGate：只控制新开仓的唯一事前规则

在 T−1 判断：
DOWN_MARKET = 市场指数收盘价<SMA60，且 SMA60<SMA60的20个交易日前值。
MarketGate = NOT DOWN_MARKET。

N7/N9中 MarketGate=False 只停止该日新开仓，不强制卖出已有持仓。持仓仍按该情景的冻结退出。
这是待检验的宽松下行环境否决，不是声称它已能择时。不得看到反弹被错过再加入另一套底部确认规则。

广度只作事前状态分层和归因：例如全池高于MA20的比例及其变化，优先复用已有可信表示；本轮不新增广度交易阈值。

必须分开回答：市场状态改变了候选数量、改变了入场后每笔收益，还是只通过减少持仓降低回撤。资金利用率更低不自动等于改进，不能事后加杠杆拉齐。

## 8. 入场、成交与资金：继承严格现金账本

主入场复用 V1 的 T+1 开盘预先限价执行：
U=max(H in F)，L=U+0.5×A0。L锚定突破前的整理上沿，不能随 T 日涨幅抬高。

只有合法且可核验的开盘成交、含滑点的价格≤L时才可成交；不以当日最低价补成交、不假设涨停排队必定买到。按最小报价单位、实际板块申报单位、费用与事前可知容量向下取量。

重要：预先提交的普通买入限价只规定最高买价，因此低开回整理区内也可能成交。本轮所有主版本一致承认这一点并单列损益。不得在知道开盘低于U后，假装事前订单不存在。
未来若要“先确认开盘/前5分钟仍强，再买”，必须建立确认后真实时点的执行模块；本轮不把它偷偷塞进同一个开盘成交模型。结论必须明确目前是收盘信号后的开盘代理，不是本人盘中突破执行。

制度必须按证券×日期还原：T+1可卖限制、涨跌幅/有效报价、最小申报量、IPO例外、停复牌、风险警示、公司行动、退市与历史费用。不得将2026年现行规则套回2018年；不得全板块硬编码100股整手。

联网可用时核验当时有效交易所规则和暂缓实施条文；联网不可用时用已验证本地制度表，不凭记忆改规则。2026-07-06的上交所规则变更是检查线索，不是默认所有附件条款均已生效。

沿用 V1 两种真实现金模式：
- MAX_DEPLOYABLE：最多10只，在真实现金、合法容量、名额和既定候选下，尽可能部署资金；候选很少时允许高集中，仅作为压力研究。
- CAP10：最多10只，每笔新建仓预算不超过下单决策时净值10%，受真实现金约束，不自动再平衡。

两种固定现金模式并未复刻本人根据交易反馈逐步提高/降低总敞口的 progressive exposure，也未复刻浮盈加仓。该区别须在最终报告明确说明；本轮不再加入第三套动态仓位状态机，防止同时改变选股、退出和资金导致无法归因。

初始100万元只是统一研究尺度。禁止融资/杠杆、负现金、虚拟重复本金、向下补仓、假设先卖后买却同时拿同一个开盘成交价。预先开盘订单不得使用同次竞价尚未实现的卖出收入；卖出实际完成后可用现金与可取现金须区别，不能错误冻结整天已可用的卖出款。
没有可靠串行执行能力时保持统一、保守的只用事前现金模型，并报告该限制，不美化为全资金效率。

## 9. 固定的10个 N 主版本

全部使用第4节共同时间轴、共同基础候选、相同成本/持有期/执行模型。

| 版本 | 趋势资格 | 形态资格 | 排序或附加条件 |
|---|---|---|---|
| N0 | 不加模板 | 无VCP要求 | RSScore |
| N1 | LONG_TT | 无VCP要求 | RSScore |
| N2 | LONG_TT | 无VCP要求 | 0.5 RS + 0.5 Path |
| N3 | LONG_TT | VCP_GUARD | 0.5 RS + 0.5 VCP |
| N4 | LONG_TT | VCP_GUARD | 0.5 RS + 0.25 Path + 0.25 VCP |
| N5 | MEDIUM_TT | VCP_GUARD | 与N4相同 |
| N6 | LONG_TT | VCP_GUARD | 0.8 N4Score + 0.2 MRScore |
| N7 | LONG_TT | VCP_GUARD | N4Score，且MarketGate允许新开仓 |
| N8 | LONG_TT | VCP_GUARD | 0.8 N4Score + 0.2 VolumeScore |
| N9 | LONG_TT | VCP_GUARD | 0.6 N4Score + 0.2 MRScore + 0.2 VolumeScore，且MarketGate允许 |

N4是主研究组合；N9是事前固定的A股市场/量能组合，不是看结果挑模块拼装的“最优策略”。N5是唯一均线周期迁移对照。

N0→N1检验模板的筛选作用；N1/N2/N3/N4辨别路径、收缩与组合；N4→N6/N7/N8辨别市场相对表现、入场环境与成交量；N4→N9检验这些固定模块一起使用的结果。

模板与VCP的某些对照同时改变准入和排序，报告必须明确；不能将所有收益变化归为纯排序增量。输出准入前后的完整漏斗与拒绝候选结果。

对并列分数用固定证券代码顺序，不能用未来表现、样本结局或后来流动性破同分。

## 10. 一次性执行矩阵：58必需＋最多12条件性

### G0：旧 V1 对照，20个

完整执行或验证复用附录 A 的原20个情景。策略、窗口和旧退出不变。
前缀 OLD_，与新 N 系列分开保存，不能把新30+30窗口结果填进旧30+5的行。

### G1：新增主实验，20个

N0至N9 × MAX_DEPLOYABLE/CAP10，共20个。主成本、T+1开盘、e+10退出。

### G2：成本压力，6个

N1/N4/N9 × 两种资金模式，费用和滑点假设总体提高到基础的2倍，其余不变。法定费率本身没变，这是压力假设。

### G3：执行延迟，6个

N1/N4/N9 × 两种资金模式，计划入场延到T+2开盘。原信号、分数、U、L冻结，不用T+1结果重排。持有期从实际入场重新计数。

### G4：独立的日线结构/趋势退出，6个

N1/N4/N9 × 两种资金模式。不改入场、排序和资金，只把主固定10日退出替换为以下冻结代理：
- 入场前固定结构线 S0=min(Low in F)−0.1×A0。
- 从买入日e收盘开始观察，若收盘价≤S0，则下一交易日开盘尝试卖出。
- 当已持有交易日差 s−e≥5，若当日收盘价<SMA10_s，则下一交易日开盘尝试卖出。
- 未触发前两项，最长在e+40开盘安排退出。
- 一旦发出卖出意图，遇停牌/跌停无法成交则持续排队/延期，不因反弹撤销已有退出意图；按可信执行证据处理。

这是 CLOSE_CONFIRMED_STRUCTURE_TREND_EXIT_PROXY，不是即时硬止损，不是本人原生退出，也不是承诺损失≤某百分比。日内碰线但收回未触发的情况、买入日不可卖、次日跳空和延期损失必须单列。
本组用于避免“只用固定10日持有评价趋势交易系统”的片面性；同时明确更长持有期是一个改动，不把这部分增益归于新入场信息。
只研究这一个退出代理，不搜索止损率/均线/持有期限，不加浮盈金字塔加仓，更不改现有五策略的原生退出。

G0至G4合计：20+20+6+6+6=58。

### G5：数据资格通过后，最多12个

三个模块：INDUSTRY / CATALYST / FUNDAMENTALS。
每个模块在自己预先确定的PIT可靠覆盖区间和同一股票覆盖集合内，运行：
N4匹配基线 / N4+该模块 × 两种资金模式，共4个。三个模块最多12个。

不能把只在2020年前有公告数据的增强策略与全历史N4直接比较。每个模块都需匹配基线，匹配条件只能由数据资格决定，不能由未来收益决定。

核心必须58个；条件性0/4/8/12个，最多70个。是否启用只能由数据权限、历史覆盖、时点完整性和可核验字段决定，不看哪一段盈利再启用。

若某模块或整个问题被旧结果精确覆盖，允许核验复用或列 EVIDENCE_REUSED/ALREADY_COVERED，不为了凑数计算假数据。真实硬阻塞或无授权区间则记录受影响情景，不假称已完成。

每个情景必须有固定ID、配置哈希、数据标识、实际执行/复用状态、输出路径和账户净值。已生成配置/已提交批处理/通过单测不等于完成。

## 11. 条件性模块的准确含义

### 11.1 INDUSTRY：行业强势，不用今天的热门概念回填

只用可靠历史时点行业归属或当时已公开的概念成员。没有PIT概念历史就不用概念标签，不让大模型凭今天知识补历史主题。

默认模块仅使用行业：计算T−1可得的行业60日收益相对市场的强度，个股所在行业的计算尽量剔除该股自身贡献；用同日行业横截面百分位得 IndustryScore。
N4增强分数 = 0.8 N4Score + 0.2 IndustryScore。

不把行业分数同时用于个股强弱、重复加权。记录行业集中度；行业缺失不能自动当成弱行业。

### 11.2 CATALYST：只用已公开、可定位时点的公司事件

启用前核查公告路由、首次发布时间、证券映射、历史覆盖及修订版本；尤其防止把只覆盖到某年/某日的公告表当成全部年份“无事件”。

固定截止 T−1 收盘；仅看此前20个交易日首次公开的公司正式事件。选择结构化、可审计类别：业绩预增/扭亏预告、正式重大订单/合同、已披露并购重组方案、正式回购方案。公司宣传、传闻、事后复盘文章不算。
CatalystScore=是否存在至少一项上述事件（0或1）。这只是候选催化存在性，不是正收益标签，不将任何类别预设为必涨。
N4增强分数 = 0.8 N4Score + 0.2 CatalystScore。

数据覆盖必须支持“没有符合事件”与“没有抓到数据”的区分。只有公告日期而没有时刻时，不把公告回填到当天开盘：最早按下一交易日可用的保守规则，再按本模块截止时点判断。
首次披露和随后修订分别保留；同一事件转载不多次计数。分类规则在读收益前冻结，结果出来后不删掉表现差的事件类别。

必须输出：公告前、公告后至突破、突破至实际买入、实际买入后的收益分段。前两段不能记作本策略利润。
未经正式公开的信息永远不作为信号，不能研究或承诺“提前知道主力将发布消息”。

### 11.3 FUNDAMENTALS：不做便宜股估值，但允许业绩领导力

不硬加低市盈率/高股息筛选。检验的是已公布经营增长，不是长期估值信仰。
用T−1之前已公开、当时版本的最近可用单季度营业收入同比与归母净利润同比。累计季度数据转单季度时，要保证参与相减的全部财报在当时已经公开。
默认GrowthScore：两个同比增长率的同日同板块百分位等权。
净利润同比的基期≤0或无法有意义比较的样本单列为不可直接比较的扭亏/亏损组；不人为塞入极大增长率。
N4增强分数 = 0.8 N4Score + 0.2 GrowthScore。

本模块使用事前已知、两项均可比的固定覆盖集合做匹配基线；必须说明这会排除部分扭亏/尚未盈利公司，不可宣称检验了全部基本面催化。
严禁按报告期末日期让财报提前可见，严禁使用后来修订的财报/一致预期数据库最终值冒充当时值。
没有可信PIT业绩表则记 NOT_RUN_DATA_GATE，不另建庞大财务/NLP平台，也不阻塞量价主实验。

## 12. 分析顺序与成功标准

### 12.1 先报告现实能否交易

完整漏斗：股票池→强势候选→趋势模板→收缩资格→突破信号→资金/名额/容量→订单→成交→计划退出→真实退出。
分开记录涨停买不到、超限价、低开回区间内成交、停牌、资金被旧持仓占用、跌停卖不出和末期未平仓。不能只分析成交赢家。

主事件收益从真实可执行买入开始，固定10日为主；5/20日、MFE/MAE、公告前涨幅等只作预先登记诊断，不能择优改主期限。

### 12.2 检查增量是否真实存在

固定的小型归因/分层，至少控制：此前30/60/252日收益、最大单日涨幅、实现波动、beta、事前成交额/流动性，以及同日共同市场影响。市值/行业只在PIT可靠时纳入。

对动态VCP还需比较相近静态整理宽度的样本：不能把“末段窄”与“逐轮收缩”的作用混为一谈。
对市场相对抗跌要检查 beta/低波动解释；对量能要检查整体市场缩量解释；对消息要检查此前已经大涨与覆盖选择偏差。

使用可解释的匹配/分组或固定回归即可，不训练新的排名模型，不造因子研究平台。
N1/N2/N3/N4不是严格同样本的完整因子实验，须分别报告准入效应与被准入集合内的排序结果，不宣称仅凭N4最好就证明统计交互或因果。

### 12.3 账户收益优先于漂亮形态

每情景：净累计收益、CAGR、最大回撤及日期、日波动/Sharpe口径、逐年结果、换手、平均与高分位仓位、实际现金闲置原因、平均持有期、成交数、单股/行业集中度、费用、滑点、计划与实际退出间隔。

明确区分：事件有收益、账户可赚钱、相对普通基线有增量、已有因子之外有增量、与五策略组合有价值。这五层不能互相替代。

MAX_DEPLOYABLE须先呈现，不只展示低仓位低回撤版；也必须展示CAP10，不能只靠单股全仓讲成功故事。不允许事后加杠杆做风险对齐。
计划结构风险不是最大损失承诺：输出预算股数×max(0,L−S0)及其净值占比，与真实尾部亏损比较，尤其展示买入日/隔夜/连续跌停造成的超计划损失。

### 12.4 不稳定性、成本与集中度

跨获准年份/板块/市场状态检查方向和经济规模；用连续日期块估计成对净值差的不确定性，不把重叠交易当独立样本。
报告最佳股票/日期/年份贡献及敏感性，不仅发表赢家；同时不机械要求“删掉所有大赢家还必须赚钱”。
成本/延迟/退出三组回答不同问题，不能混为一项胜率。若收益都发生在买不到的涨停/跳空阶段，结论是执行不可捕获，不是策略有效。

所有版本都是同一段历史的多个研究尝试，70个情景不是70次独立验证。没有获准未读验证集，最高只能给研究/影子候选级结论。

### 12.5 与既有五策略的关系

仅使用已有、可信且有权限的净值/交易产物做轻量相关性、共同亏损日期、同股和同日重叠分析。没有对齐产物就记 NOT_ASSESSED。
不能把N系列当作现有某一个策略的“原版”或自动替换生产配置，尤其注意与已有低波动突破/动量策略的暴露重叠。
不重跑整套五策略，不改冻结退出，不把加权净值冒充真实共享资金账户结果。

## 13. 最小必要测试与资源适配

先复用数据读取、日历、公司行动、费用、执行和账户引擎。新增薄的特征/策略适配层。不要构建通用平台、插件框架、复杂Agent编排或新数据湖。

必要测试：
- 截断在T−1的拐点快照与“完整数据按as-of重放”一致；改动T之后数据不改变已发信号。
- 高低点确认滞后、并列/双极值歧义、连续同类拐点、未确认新低、少于两腿均正确。
- 简单低波动平线不误标为有多轮回撤的VCP；停牌/一字线不会冒充供给收缩。
- Path与W分离；A0冻结；RS_PROXY不是RSI；横截面排名完整。
- 公告/业绩首次可用时间滞后正确，缺失不能等同于无事件。
- T+1、申报量、涨跌停、滑点、超限价、低开成交、公司行动、延期退出、期末未平仓正确。
- 多订单现金/费用预留、整股/整手规则、同次竞价卖款不可提前花、不重复开仓，逐日账本对平。
- 固定10日与趋势退出各自日期正确，买入日不虚构可卖，结构线不是实际成交保证。
- 不跨封存边界补持有期或财务/新闻结果。

先合成用例和少量人工可核对日期，再全量。核心错误要修并重跑受影响结果，不能只在报告里免责声明。

数据与计算：
- 优先复用日线和已有分钟数据。默认不下载全市场多年分钟；必要时只核验候选成交日。
- 一次生成共同候选/特征缓存，多情景复用，只分别计算真实账户路径。
- 大数据/中间产物放经只读识别且验证可写的外接盘；不能假定某个/Volumes路径存在。代码/配置/摘要留Git。
- 按当前CPU、内存、其他任务负载动态调worker、批次和缓存；资源不足先减少并发、流式处理，不偷删股票/年份。
- 利用已有授权数据源/凭据补齐必要字段，不购买服务、不泄露密钥、不打开封存区间。
- 无关报告缺失、缺PIT新闻/行业等只阻塞对应条件性实验，不得让全部量价实验停在“环境已审计”。

运行中简短报告真实样本覆盖、完成情景数、已修错误和硬阻塞。不要连续几轮只报告“即将开始”。

## 14. 结论、交付、提交与推送

输出要回答：
1. 原V1与Minervini启发的新时间结构各有什么证据？不能把窗口变化误归为模板作用。
2. LONG_TT是否有增量？MEDIUM_TT是否真更适合本样本，还是只是覆盖不同股票？
3. Path、动态VCP及其组合是否超出普通强势/低波动/Low-MAX？
4. 大盘抗跌信息、大盘新开仓限制、量能分别有无作用？固定合并N9是否更好？
5. 已公开催化、行业、业绩数据够不够？经过匹配对照是否有增量？
6. 真实现金打满与单笔10%上限的收益、回撤、利用率和集中风险各如何？
7. 日线结构/趋势退出改善了什么、牺牲了什么，是否被T+1/跳空/延期卖出破坏？
8. 是否值得保留影子候选，和已有五策略是否可能高度重复？

不要为了选出冠军版本忽略绝对负收益。N4失败而N5/N9在某年偶然好，不等于主假说被验证；可以描述差异，但不现场改规则并称独立成功。

结论维度：
RESEARCH_VERDICT：ALREADY_COVERED / NO_INCREMENTAL_EDGE / COMPONENT_ONLY / JOINT_EDGE_RESEARCH_ONLY / INSUFFICIENT_EVIDENCE。
EXECUTION_VERDICT：FEASIBLE_UNDER_STATED_ASSUMPTIONS / EXECUTION_FRAGILE / NOT_ASSESSABLE。
DEPLOYMENT_VERDICT：REJECT / SHADOW_ONLY / NOT_ASSESSABLE。

最高SHADOW_ONLY，不自动实盘。对于失败，只关闭本次确切定义/组合，不扩大为“所有VCP都无效”；也不允许小改阈值无限救活。

精简产物：
- SPEC.md（冻结经济顺序、变量/时间、样本权限、来源、场景清单）。
- REPORT.md（普通中文结论、对照表、增量/执行/资金/失败机制）。
- manifest.json与scenario_summary.csv（全部70个预登记位置，未启用也写原因）。
- 足够追溯的信号、拐点、订单、成交、逐日NAV索引和哈希；大件放外接盘。
- 实际运行验证过的复现命令与测试日志。

提交仅本任务改动，检查密钥/大件/无关文件。远程身份和凭据已确认且网络允许时正常push本任务分支，不force push。失败如实记录，不声称已推送。

最终状态至少包括：
ENVIRONMENT_VALID:
REPO:
BRANCH:
BASE_HEAD:
START_HEAD:
END_HEAD:
TASK_STATUS:
V1_SOURCE_STATUS:
V1_RESULTS_REUSED_AND_VERIFIED:
SAMPLE_PERMISSION_STATUS:
HISTORY_ACTUALLY_USED:
NEW_SEALED_VALIDATION_OPENED: NO
FROZEN_FIVE_STRATEGIES_MODIFIED: NO
METHOD_LABEL: MINERVINI_INSPIRED_MECHANICAL_A_SHARE_PROXY
CORE_SCENARIOS_EXPECTED: 58
CONDITIONAL_SCENARIOS_MAX: 12
SCENARIOS_NEWLY_EXECUTED:
SCENARIOS_VERIFIED_REUSED:
SCENARIOS_NOT_RUN_WITH_REASON:
SCENARIOS_INVALIDATED_BY_BUG:
VCP_PIVOT_ASOF_CHECK:
TEMPORAL_LEAKAGE_CHECK:
PORTFOLIO_ACCOUNTING_CHECK:
EXECUTION_EVIDENCE_GRADE:
INDUSTRY_DATA_GATE:
CATALYST_DATA_GATE:
FUNDAMENTALS_DATA_GATE:
RESEARCH_VERDICT:
EXECUTION_VERDICT:
DEPLOYMENT_VERDICT:
FIVE_STRATEGY_COMPARISON_STATUS:
REPORT_PATH:
REPRODUCE_COMMAND:
TESTS_ACTUALLY_RUN:
UNRESOLVED_ISSUES:
COMMIT:
PUSH:

从只读环境核验开始，连续执行到本轮实际研究结束。除真实硬阻塞或可核验精确重复外，不以“研究方案已完成”作为任务结束。

## 15. 来源与事实边界（核验日期2026-09-08）

以下是方法和制度的阅读依据，不是本候选已被验证的证据。引用时只简短转述，不复制书籍章节或长篇访谈。

[S1] U.S. Investing Championship主办方发布的2021年结果：Minervini在100万美元以上股票组收益334.8%，并注明1997年也获第一。不能改称所有组别/全部资产/长期年化均为此数。
`https://www.businesswire.com/news/home/20220124005241/en/2021-United-States-Investing-Championship-Winners-Minervini-Smashes-Record`

[S2] Minervini本人业务网站简介：1997年155%和2021年334.8%的说明。
`https://minerviniselect.com/about.php`

[S3] McGraw Hill出版页面：Trade Like a Stock Market Wizard，包含SEPA、趋势、行业与催化、基本面、盈利质量和风险管理等目录。出版社宣传语不是独立业绩保证。
`https://www.mheducation.com/highered/mhp/product/trade-like-stock-market-wizard-how-achieve-super-performance-stocks-any-market.html`

[S4] 2021-05-06 Alpha Trader访谈原始文字稿：本人解释由左到右收紧、接近失效位置参与，也讨论基本面与催化因公司类别而异。不是所有实现细节的精确代码合同。
`https://seekingalpha.com/article/4425132-stock-trader-mark-minervini-and-market-strategist-ben-laidler-join-alpha-trader-podcast-transcript`

[S5] 上交所2026年交易规则及生效/暂缓实施附件；历史回放仍需历史版本。
`https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml`

[S6] 上交所2026-04-24规则修订说明，2026-07-06实施，包括主板风险警示股涨跌幅调整等。
`https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml`

[S7] HKEX股票互联互通官方FAQ，含2026-07-06更新项目。用于交叉核验沪深市场的公开交易约束，不把北向交易的账户/结算规则误套到内地普通现金账户。
`https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/Stock-Connect/Getting-Started/Information-Booklet-and-FAQ/FAQ/FAQ_Cn.pdf`

[S8] 证监会2024-02-05披露的操纵市场案例，证明某些操纵行为确实存在，不证明全部股票走势可归于一个庄家。
`https://www.csrc.gov.cn/csrc/c100200/c7465512/content.shtml`

[S9] 上交所上市公司分红数据。不能把市场中存在投机/操纵直接推成所有企业权益价值为零。
`https://www.sse.com.cn/market/stockdata/dividends/dividend/`

---

# 附录 A：V1 原始冻结合同（完整保留）

以下仅用于旧20个对照情景及通用安全/账本要求。总任务、环境分支和新模块授权以上方V2主文为准；不要把附录单独当作另一次启动指令。

# A股“渐进走强 → 高位紧凑整理 → 再次启动”独立研究任务

你是本任务的研究负责人和实现者。请直接在本地 CY 项目中完成研究，不要只给方案、写合同或搭框架。需要实际生成样本、运行回测、分析结果、落盘可复现产物，并在条件允许时提交和推送。

这是一次自主研究授权，不是实盘交易授权。不得下真实订单，不得修改或替换既有生产策略，不得打开新的封存验证集。

## 0. 目标与完成标准

核心问题：
在此前累计涨幅相近的股票中，“上涨贡献更分散、回撤负担更低，随后在高位收敛”的组合，是否在再次突破、并以真实可执行价格入场后，具有超出普通强势突破及已知因子的增量收益？

不要预设答案为正。不能把“主力洗盘”“连续小涨必然大涨”“跌得越深越该重仓”当作已知事实。

本轮只研究这一个主假说及必要对照，不扩展到深坑抄底、连板接力、新退出系统、机器学习平台或五策略共享资金改造。

正常完成标准：
1. 核对旧实验覆盖范围，确认本次是否真的有未覆盖的问题。
2. 明确时间语义、样本使用权限和实际可用数据。
3. 用小规模执行测试验证账本，然后实际跑完预先固定的20个账户情景。
4. 完成增量归因、可交易性分析、分期稳定性分析和失败解释。
5. 保存代码、配置、结果、运行日志索引和复现命令；提交本任务自己的文件。

不能用“已生成配置”“单元测试通过”“批处理已提交”替代“账户实际回放完成”。
如果旧研究已精确覆盖，允许复用证据并关闭重复问题；如果存在无法绕过的硬阻塞，必须报告已完成部分、真实回放数及阻塞证据，不得假称完成。

## 1. 环境：独立工作树，保护现有研究

以下仅是定位线索，不是当前 Git 事实：
- 主仓库候选：/Users/linmei/Documents/CY
- 既有研究工作树候选：/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830
- 深跌研究工作树候选：/Users/linmei/Documents/CY-oversold-reversal-ranking
- 预期 CY origin：LinmeiHu/CY
- 建议新分支：research/clean-ascent-consolidation-v1
- 建议新工作树：/Users/linmei/Documents/CY-worktrees/clean-ascent-consolidation-20260908
- 建议研究目录：research/clean_ascent_consolidation/

先只读核验实际 repo、origin、HEAD、branch、git status、worktree list，以及可复用的数据/执行模块。
选择包含所需稳定模块的、可追溯的实际提交作为基线，记录 BASE_HEAD 和理由；不要机械使用对话里的旧提交。

确认仓库身份后，你可以自行建立新分支和独立工作树，无须为常规分支创建再次询问。
如果同名分支已属于本任务，先检查现有 checkpoint 并恢复；若同名路径属于别的任务，使用不冲突的后缀。

禁止切换或覆盖正在运行的五策略工作树；禁止 reset --hard、clean、强制 checkout、强推或替用户 stash 无关修改。
先读 AGENTS.md 及相关模块约定。只修改本任务需要的文件；不顺手重构全仓库。

## 2. 样本权限与旧研究查重

先读研究台账、样本读取记录、冻结合同、关闭报告及相关实现。
历史记录提示检查：普通动量/突破、相对强度、Low-MAX、低波动、路径质量、趋势内回调、支撑保持、冲击恢复、深跌反转与断层回补。
这些只是检索线索，不能凭名称判断“已经做过”或“从未做过”。

用一张小表记录：旧实验的股票池、时间窗口、特征、触发、入场、退出、对照、结论、证据路径，以及本次真正不同的地方。
区分：
- EXACT_DUPLICATE：定义和检验问题已被精确覆盖，优先复用结果，不换名救活。
- PARTIAL_OVERLAP：已有单项或相似研究，但完整时间序列/条件组合尚未覆盖，继续本轮小实验。
- NEW_TESTABLE_QUESTION：有清楚、尚未检验的问题，继续。

不要因出现“突破”“恢复”等相同词语就提前停止；也不要把换窗口、换名称当成新机制。
这一阶段限于解决查重和权限，不开展无关历史考古。

本次不授权打开新的封存验证集。
逐段标明历史数据是已用于探索、允许的后续检验、还是封存/权限不明。已看过的区间不能重新包装为独立验证；其他策略使用过某段数据，也不自动等于本候选获准使用。
2018–2021、2022–2023可作为查找既有授权的线索，不可只凭本段文字认定权限。
覆盖所有经核实允许、且执行数据可信的历史；不能为了漂亮结果跳过亏损年份。
权限不明确的区间先隔离，继续处理已确认区间；不得因此把整个可做任务停在文档阶段。
可以检查元数据确认数据覆盖，禁止为决定是否打开封存区间而先看其价格结果或标签。

## 3. 经济故事与时间语义

正式读取本轮结果标签前，落盘简短 Semantic Preflight，写清：
ECONOMIC_SEQUENCE、CAUSAL_BACKGROUND、STATE_VARIABLES、EVENT_FORMATION_TIME、CONFIRMATION_TRIGGER、ENTRY_TIME、OUTCOME_START_TIME、POSSIBLE_SEMANTIC_AMBIGUITIES、CHOSEN_TIME_ANCHORS。

经济故事仅作为假说：
前段渐进上涨可能对应持续重新定价；之后高位收敛可能意味着短期价格能维持在较高位置；再次突破提供入场确认。
我们观察的是价格与成交状态，不是直接观察到“主力吸筹”或“洗盘”。

严格区分：
- Cause：真正订单需求/信息变化通常不能由日线直接识别，不伪造因果标签。
- State：已经形成的上涨路径，以及随后形成的整理状态。
- Trigger：整理完成后，收盘突破此前区间上沿。
- Outcome：实际可执行入场之后的收益与风险。

主窗口固定为：
- 前段上涨：T−35至T−6的30个交易日收益，参考起点收盘价为T−36。
- 后段整理：T−5至T−1，共5个交易日。
- 突破确认：T日收盘后。
- 主入场：T+1开盘执行时点。
- 主持有期：实际买入日起，经过10个交易日的开盘到开盘持有期。
  即买入交易日索引为e，在e+10的开盘安排退出；例如T+1买入，正常在T+11开盘退出。

使用交易所交易日索引，不能压缩个股停牌日后假装它连续交易。
信号特征除T日触发条件外均截止T−1；波动尺度在整理开始之前冻结。
不能用T日大涨改善前段路径评分；不能用后来的阶段高低点定义当时的位置。

## 4. 股票池、特征与四种排名

优先复用本仓已有、历史时点可还原的A股普通股票研究池和基础可交易性规则。
不把ETF与股票混在同一事件池。各板块交易制度按实际日期处理。
若缺少基础股票池合同，使用明确记录的简化口径：历史全部普通A股、上市至少120个交易日、信号时非ST/*ST、所需价格与状态历史完整，并具有可核验的成交和交易状态数据。
这不是要求永远排除ST；只是本轮不额外建立ST交易研究分支。
保留退市和历史失效证券；不能倒用今天的存续股票名单。

基础候选：
- 前段30日累计收益为正。
- 同期涨幅位于对应交易制度板块的前30%。
- 后续满足相同的突破和执行规则。

第一版只使用以下四个形态描述，不扩展指标库：

P1 回撤负担：
对前段每一天s，计算1−C_s/max(C_u)，其中u只能取前段起始参考日到s的已发生日期；然后对30天取平均。越低，路径中的回撤越浅或越短。

P2 上涨贡献集中度：
以前段每日对数收益计算，“最大的3个正收益日之和 / 全部正收益日之和”。越低，上涨贡献越分散。
没有足够有效数据或分母无效的样本显式处理，不填0伪造最优分数。

C1 整理宽度：
(max H − min L) / ATR20_pre，其中最高最低仅来自整理窗口。
ATR20_pre固定为整理开始前最后一个交易日的20日ATR；优先复用已有ATR实现并记录算法。

C2 高位保持：
max(0, 前段最高价 − 整理期最低价) / ATR20_pre。
前段最高价只能来自已结束的前段窗口。越低，整理期距离前段高位越近。

四个指标全部采用“数值低对应更高分”的方向。
在同日、同板块的基础强势候选中做百分位排名，再筛选突破事件。对不足以稳定排名的小组设明确、非结果驱动的回退方式；不得按结果选择分组。

PathScore = 两个路径百分位得分的等权平均。
ConsolidationScore = 两个整理百分位得分的等权平均。
RSScore = 前段收益的同日同板块百分位得分，涨幅高得分高。

固定四个版本：
- B0：Score = RSScore。普通强势突破对照，不重新优化旧突破策略。
- P：Score = 0.5×RSScore + 0.5×PathScore。
- C：Score = 0.5×RSScore + 0.5×ConsolidationScore。
- PC：Score = 0.5×RSScore + 0.25×PathScore + 0.25×ConsolidationScore。

这组权重只是事先固定的比较设计，不代表最优。
四个版本必须使用相同的原始候选、信号、执行、成本和资金机制，只改变排序。
并列用稳定的证券代码顺序解决，不使用未来表现破同分。
不加量比阈值，不搜索几十个形态指标，不训练复杂模型。
成交量先用于可交易性、容量及事先定义的归因控制，而不是“洗盘确认”。

## 5. 信号、限价与真实执行

整理上沿U = 整理窗口内最高价。
主信号：T日收盘价严格高于U，且满足统一股票池和基础候选条件。
不要求事后证明它是某一大行情的首次突破；不依据后续是否大涨筛选事件。

关键限价：
T日收盘后冻结最高接受买价 L = U + 0.5×ATR20_pre，并按证券报价单位处理。
注意：锚定事前整理上沿U，而不是T日已经涨高的收盘价。
这用于研究“不追离整理区间过远的位置”，不是宣称0.5倍ATR最优。

T+1只研究开盘执行：
- 无合法开盘成交条件、停牌、无法核验的涨停排队等，按明确保守规则不成交。
- 含滑点的可执行买价高于L，不成交。
- 没有开盘成交，不拿当天盘中最低价补出一笔成交；本次剩余订单撤销。
- 不虚构“日线最低价碰到了限价，所以一定买得到”。
- 有可靠竞价/局部分钟数据时复用；只有日线时明确记录开盘成交假设及其局限。

退出不优化：
正常在e+10开盘退出；遇停牌、无法成交的跌停等顺延到下一合法成交机会。
不能用设定止损价截断无法卖出的损失。本轮不加入“连涨离场”“放量急跌卖出”或移动止损。
固定持有是研究基线，不是直接实盘部署的风险方案。

执行账本至少正确处理：
- 历史日期对应的交易制度、最小交易单位、费用和价格限制。
- 真实现金、买卖费用、滑点、适用的回转交易限制及证券持仓。
- 公司行动与未复权成交价；复权特征价格不得直接充当真实成交价。
- 缺失行情、停牌、退市与延期退出，不能删掉困难交易美化结果。
- 期末未平仓按可信价格标记并报告；禁止为了完整持有期读取封存区间。

复用已有可信成本表；无法核验的成本项应记录为假设，做压力测试，不能冒称已完全还原。
容量约束只使用下单时可知的信息。不得用T+1全天成交量决定T+1开盘订单大小。
只有历史日均成交额容量代理时，明确它不等于真实开盘可成交量，输出执行可信等级。

主版预先提交的限价只规定买价上限。因此次日低开回到整理区间内仍可能成交，必须单列这类成交的占比和损益；不得看到开盘低于U后，事后取消已经按开盘价应成交的订单。若未来研究要增加开盘状态确认，需要另设真实的确认后成交时点，本轮不偷偷增加。

不要求为本任务下载全市场多年分钟数据。先复用日线执行模块，必要时只对候选日期做局部核验。

## 6. 两种资金模式：先看可用资金充分部署，再看仓位上限

初始资金统一设为100万元，仅是研究尺度，不是对用户账户规模的判断。
四个版本各自运行独立的单一物理现金账户。不能把每天的候选收益均值当组合净值。
禁止融资、杠杆、负现金和事后现金修正；禁止向下补仓。
同一股票持仓期间不重复开新仓，新的同股信号仍记录为被占用机会。

A. MAX_DEPLOYABLE
最多同时持有10只股票。
在下单时的真实可用现金、空余名额和容量范围内，尽可能部署现金；按排名选取可新开仓股票，在入选股票之间等分当次可用预算。
不额外设置单只10%的初始仓位上限。因此候选很少时，允许单股高度集中，但只作为研究情景，不作为实盘建议。
不得为了补足10只而降低既定候选要求。

B. CAP10
最多同时持有10只股票。
每笔新买入预算不超过下单决策时账户净值的10%，同时受真实现金和容量约束。
候选不足、现金不足、名额不足或订单不成交时留现金；不借钱凑仓位。
持仓自然涨到超过10%不自动再平衡；本轮不增加再平衡规则。

两者都必须：
- 按限价和费用预留预算，整手向下取整，不能先超买再缩回。
- 未成交释放的资金按冻结执行流程处理，不凭事后开盘结果假装预先提交过另一笔订单。
- 开盘竞价订单只能使用提交时真实可用资金，不能把同一次竞价中尚未成交的卖出收入提前用于买入。
- 若既有执行模块支持可证明的串行卖出后买入，应记录真实成交时点；不能让两笔订单都用同一开盘价却假装已经先卖后买。
- 不强制卖出旧持仓给新信号让路，不给正在持有的股票随意追加资金。

MAX_DEPLOYABLE是“在上述约束下尽可能使用现金”，不是保证时时100%仓位，也不是数学上的最高收益上界。
必须报告实际仓位和现金闲置原因，不能以名字代替资金利用率证据。

## 7. 固定实验矩阵：20个实际账户回放

先冻结配置与实验清单，再运行本轮收益分析。不得看完结果新增有利组合。

G1 主实验，8个：
B0 / P / C / PC × MAX_DEPLOYABLE / CAP10。
窗口30+5，持有10个交易日，基础成本，T+1开盘执行。

G2 成本压力，4个：
B0 / PC × 两种资金模式。
除交易成本和滑点总体提高到基础假设的2倍外，其余与主实验一致。
这是压力情景，不是声称真实法定费率变成2倍。

G3 执行延迟，4个：
B0 / PC × 两种资金模式。
将原信号的计划入场由T+1开盘延到T+2开盘；信号、评分、原限价均冻结，不利用T+1走势重新挑选。
按真实下单时的现金与合法成交条件执行；持有期从实际入场日重新计数。
不成交就是不成交，不仅把已成交交易的收益窗口机械后移。

G4 邻域检查，4个：
窗口20+3、40+8，各运行B0和PC，均用CAP10、基础成本和T+1执行。
除前段和整理窗口外，其余定义、0.5倍ATR限价、权重、ATR20和10日持有期不变；时间锚点相应平移。
这些不是寻找最优窗口。若30+5主假说失败，邻域偶然盈利不能用于宣布主假说成功。

总计20个。
正常情况下应完成全部20个再下结论；不要看到第一个负结果就停止，也不要因一个盈利结果继续无边界调参。
按实验ID记录是否真正运行、输入哈希、配置哈希、开始结束时间及输出路径。
重用交易路径或缓存可以，但每个账户结果必须由其真实配置计算，不得复制数字冒充独立执行。

## 8. 分析：形态增量、实际收益、组合价值分开回答

### 8.1 事件层
保留全部原始信号和订单状态，分别统计：候选数、信号数、因价格放弃、停牌/限制、容量不足、资金不足、持仓占用、实际成交。
不能只留下成交赢家，也不能把没买到的上涨收益记到账户里。
主结果是实际可执行入场后的10日收益；5日、20日收益及持有期间最大有利/不利变动仅是预先声明的诊断，不据此择优改持有期。
未完整覆盖观察期的事件单列，不能穿越样本权限边界补标签。
原始重复信号保留；另做固定10交易日去重的事件诊断，去重不能取决于是否盈利。账户层始终按真实持仓占用处理。

### 8.2 增量归因
至少回答：
1. 是否仅仅筛到了此前涨幅更大的股票？
2. 是否仅仅换一种方法表达低波动、Low-MAX或较好的流动性？
3. 路径与整理都各自有信息，还是只有其中一项有信息？
4. 两项叠加的收益是否只是排序变化，还是有额外的条件组合信息？

采用小而可解释的固定对照/分组或回归，不搭新因子平台。
必要控制包括前段累计收益、前段实现波动、最大单日收益和事前成交额；市值和行业仅在已有PIT数据可靠时使用，缺失则明确限制，不为本次另建大数据工程。
控制共同日期/板块影响。事前变量与事后结果严格分开。
可以报告路径高/低×整理高/低的四组结果及交互差异；PC最好不自动等于存在统计交互，更不等于证明因果。
模型或回归只作固定归因诊断，不回头用于训练新排名。

### 8.3 账户层
每个情景至少报告：
累计净收益、CAGR、最大回撤及日期、波动率、Sharpe（口径明确）、换手、平均/高分位资金利用率、平均持有期、成交笔数、延期退出笔数、单股及行业集中度、费用和滑点负担。
给出逐年及已授权时间分段结果。
对同资金模式下B0与其他版本做成对比较，不能只横向挑各自最好年份。
同时看绝对净收益和相对基线的增量，不以“比亏得更多的基线少亏”宣布可投资。

检查收益是否被少数股票/日期/年份主导；报告最大贡献者及剔除后的敏感性，不把删大赢家作为唯一机械淘汰标准。
区分事件收益好但资金拥堵、买不到、现金闲置、集中风险太高等不同原因。
资金利用率差异必须解释；不得通过事后加杠杆把低仓位版本放大后冒充真实收益。

### 8.4 不确定性与验证身份
有足够数据时，对B0与PC的日收益差做按连续日期块重采样的简洁区间估计，保持两者时间对齐。
不能把重叠持有期交易当完全独立样本；不启动大规模统计显著性筛选平台。
所有主实验、压力、邻域、诊断都记录在尝试清单中，不能只发表赢家。
没有真正未读且获准使用的区间，就明确本轮仍是研究证据，不能宣称已通过独立验证。

### 8.5 与既有五策略的关系
仅在已有可信、区间获准使用的净值/交易产物可以直接复用时，做轻量比较：日收益相关性、共同下跌日期、同日信号和同股持仓区间重叠。
没有对齐来源时记NOT_ASSESSED，不为此重跑全部五策略，也不碰其冻结退出和共享资金实现。
不能仅凭低相关就断言新策略值得加入；不得用简单加权净值冒充新的物理共享资金账户结果。

## 9. 最小必要测试与实现要求

优先复用现有数据读取、交易日历、价格处理、费用和账户引擎。只在必要位置增加薄的策略适配层。
不要先构建研究操作系统、通用注册中心、插件框架或复杂调度平台。

至少验证以下关键行为：
- 改动T日以后数据，不改变T日信号、评分和限价。
- 涨跌停、停牌、超过限价时，不伪造成交。
- 费用/整手/多订单同时出现时，不产生负现金或重复花钱。
- 同场开盘卖出资金不被提前用于买入。
- 持仓占用、10日退出日期和延期退出计算正确。
- 公司行动不制造假突破、假收益或重复分红。
- 未完成持有期和封存区间不会被偷偷补标签。
- 单笔账本、现金、持仓市值和总净值能逐日对账。

先用可人工核对的合成用例及少量真实日期做执行冒烟测试，再跑全量。
不必为无关模块补齐测试；但任何核心会计、时间泄漏或成交错误必须修复并重跑受影响实验。
不要只改报告掩盖代码问题。

## 10. 自主执行与资源适配

允许自行读取文件、创建本任务数据缓存、运行测试和研究、修复相关bug、分批执行及恢复checkpoint。
发现可解决的数据路径、内存、依赖或资源问题，先尝试最简单且不改变研究问题的修复，不要立刻停工等用户。
在已有获授权的数据源和凭据范围内，可以补齐必要日线、交易状态和公司行动数据，不购买新服务、不泄露凭据、不扩展到未经授权的样本。没有既有默认值的次要执行参数，在读结果前选择可解释的保守值并记录，不为每个常规实现选择再次询问。

先清点已有日线数据和缓存，尽量一次读取、多情景复用。
大文件、原始数据、中间产物和大型交易账本优先放外接硬盘；先只读识别真实挂载路径、可写状态与空间，不能假定某个/Volumes路径存在。
代码、配置、报告和小型摘要留Git；外部产物在仓内保留路径索引和哈希。

基于当前可用内存、CPU和其他任务负载自适应并行，不固定霸占全部核心。
内存压力下优先减少worker、分年份/日期批处理、流式写入和复用缓存。
横截面排名必须在完整的同日组内计算，不能因分块而只在局部股票子集中排名。
资源适配不得偷偷缩小股票池、截短亏损年份、改成随机子样本后仍称全量。
确需缩小授权范围或数据范围时，先明确原因和偏差，区分部分研究与全量完成。

只在遇到真正硬阻塞时停止受影响部分，例如：没有任何可确认授权的区间、核心执行数据无法可信还原、无法消除泄漏、无法建立现金自洽账本。
封存区间不得为排障打开。无关报告缺失、行业标签缺失、次要统计不稳等不应阻止已可完成的主实验。

运行中给出简短实际进展：样本覆盖、已完成情景数、发现和修复的问题、当前阻塞。
不要连续几轮只汇报“准备完成”“即将开始”。

## 11. 结论规则

不得以某一窗口/某一年/某一资金配置表现最好为依据偷换主结论。
至少分开给出研究结论与投资可用性结论。

研究结论可使用：
- ALREADY_COVERED：旧证据已精确覆盖，无需重复。
- NO_INCREMENTAL_EDGE：未发现超出基线/已知因素的有用增量。
- PATH_ONLY：支持路径部分，不支持完整组合假说。
- CONSOLIDATION_ONLY：支持整理部分，不支持完整组合假说。
- JOINT_EDGE_RESEARCH_ONLY：完整组合有研究层面增量，但不等于实盘通过。
- INSUFFICIENT_EVIDENCE：数据、样本量或执行可信度不足以判断。

投资可用性可使用：
- REJECT_FOR_DEPLOYMENT。
- EXECUTION_FRAGILE。
- SHADOW_CANDIDATE_ONLY。
- NOT_ASSESSABLE。

如果PC绝对收益为负，即使超过B0，也不能称可投资。
如果PC改善被已有因素解释，不包装为全新alpha。
如果信号收益主要发生在实际入场前，应明确“看起来能解释图形，但该入场方式捕捉不到”。
如果仅MAX_DEPLOYABLE高集中情景好、CAP10不好，必须揭示其集中风险和资金驱动，不给出泛化成功结论。
如果主假说失败而某个邻域好，只能作为已观察的探索结果，不现场改规则再宣布验证通过。
本轮无论结果多好，最高只升级为影子候选，不改现有五策略，不自动实盘。

## 12. 落盘、提交与最终回答

保持产物精简，至少有：
- SPEC.md：经济语义、冻结定义、样本权限、实验清单及执行假设。
- REPORT.md：核心结果、增量归因、失败解释、数据和执行局限。
- manifest.json：代码/数据/配置标识、授权区间、实际运行状态、产物索引。
- scenario_summary.csv：20个情景逐行列出，未运行也保留并解释。
- 逐日净值、信号/订单/成交审计与必要日志：可放外接盘，仓内保留可追溯索引。
- 实際执行并验证过的复现命令，不写无法运行的示例命令冒充。

报告至少给出：主结果对照表、资金利用率对照、分期表现，以及事前固定或随机抽取的成功与失败案例。
图例只能作解释，不能替代全量统计；有图时应同时包含未成功、未成交和执行困难案例，不能只选漂亮走势。

只提交本任务自己的代码、配置、报告和小型摘要，检查暂存内容不含密钥、大数据和无关文件。
在已有GitHub凭据、remote已确认且允许正常网络访问的情况下，推送本任务分支；不得force push。
推送失败时保留本地提交，记录真实错误。不得声称已推送。

最终先给普通中文结论，回答：
1. 这条完整思路是否值得继续，依据是什么？
2. 路径、整理、二者组合分别贡献了什么？
3. 资金尽可能部署与单笔10%上限，收益/回撤/利用率分别怎样？
4. 扣费、延迟、邻域和已知因子对照后，还剩多少证据？
5. 是否提供了与既有五策略不同的信息，哪些仍未核实？
6. 下一步只给一个建议：关闭、补一个明确缺口，或进入影子跟踪；不要罗列一堆新策略。

然后附真实状态：
ENVIRONMENT_VALID:
REPO:
BRANCH:
BASE_HEAD:
START_HEAD:
END_HEAD:
TASK_STATUS:
SAMPLE_PERMISSION_STATUS:
HISTORY_ACTUALLY_USED:
NEW_SEALED_VALIDATION_OPENED: NO
FROZEN_STRATEGIES_MODIFIED: NO
REPLAY_SCENARIOS_EXPECTED: 20
REPLAY_SCENARIOS_ACTUALLY_COMPLETED:
TEMPORAL_LEAKAGE_CHECK:
PORTFOLIO_ACCOUNTING_CHECK:
EXECUTION_EVIDENCE_GRADE:
RESEARCH_VERDICT:
INVESTABILITY_VERDICT:
FIVE_STRATEGY_COMPARISON_STATUS:
REPORT_PATH:
REPRODUCE_COMMAND:
TESTS_ACTUALLY_RUN:
UNRESOLVED_ISSUES:
COMMIT:
PUSH:

立即从只读环境核验与旧研究查重开始，然后连续推进到实际研究结束。除真实权限/数据/执行硬阻塞或精确重复证据外，不要把“研究设计完成”当作本任务结束。

