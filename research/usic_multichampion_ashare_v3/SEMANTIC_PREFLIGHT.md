# 每路线语义核验

本文件展开冻结主文/SPEC与事前JSON的语义，未改变数值规则。机制均为待检验解释。完整信号的known_at/confirmation_at统一为T收盘；原输入中的known_at表示背景/父状态时间，保存在canonical_signal_timeline.parquet的background_known_at，不能将其解释为当日触发或当日低点已提前可知。

## D00

ECONOMIC_SEQUENCE：成熟长期趋势→普通突破。

CAUSAL_BACKGROUND：继承LONG_TT及RS。

STATE_VARIABLES：30日上涨与30日整理，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：T收盘越过此前上沿。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：无新增形态识别。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D01

ECONOMIC_SEQUENCE：成熟长期趋势→动态收缩→突破。

CAUSAL_BACKGROUND：同D00，加入已确认摆动收缩。

STATE_VARIABLES：拐点2日确认、VCP守卫，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：T收盘突破；排序RS/VCP。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：收缩准入与排名同时变化。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D02

ECONOMIC_SEQUENCE：渐进上涨→动态收缩→突破。

CAUSAL_BACKGROUND：同D01，加入此前路径分数。

STATE_VARIABLES：前上涨窗口与Path；不读T未来，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：与D01相同候选触发，只改变排序。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：RS/VCP/Path并非三份独立alpha。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D03

ECONOMIC_SEQUENCE：强EMA状态→历史峰值后回调→收复。

CAUSAL_BACKGROUND：EMA9>21>50、前日RS60。

STATE_VARIABLES：p为T-20至T-3历史最高；ATR在T-21冻结，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：T收盘越过q最高与EMA9。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：峰值p不是p当日已确认买点；当日低点用于T收盘S0。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D04

ECONOMIC_SEQUENCE：D03回调→检查已有经济价格锚是否重合。

CAUSAL_BACKGROUND：完全继承D03，再检查真实成交AVWAP。

STATE_VARIABLES：锚b必须早于p且已突破其此前20日高点，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：仅同一D03触发日加AVWAP资格。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：缺锚与不符合距离分开；只有完整锚子样本谈增量。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D05

ECONOMIC_SEQUENCE：此前突破→回调到旧阻力与EMA21附近→反弹。

CAUSAL_BACKGROUND：上升EMA21/50与RS60。

STATE_VARIABLES：b为T-30至T-6最近已发生突破，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：T收盘超过旧水平、q高点及EMA21。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：使用过去支撑价格，不宣称观察到主力行为。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D06

ECONOMIC_SEQUENCE：低点偏离→已反弹→五日横盘→早期收复。

CAUSAL_BACKGROUND：不要求长期200日成熟趋势。

STATE_VARIABLES：历史低l、先发生反弹、后五日区间，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：T收盘超过区间及EMA10/20。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：低点当天不可知为未来拐点；全部背景到T-1已发生。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D07

ECONOMIC_SEQUENCE：D06父信号→延续→第一次EMA20回测→确认。

CAUSAL_BACKGROUND：每个父事件独立20日到期。

STATE_VARIABLES：第一次回测固定，父S0永久失效，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：回测后5日内首个收复信号。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：失败后不能再选更漂亮回测，父事件不重置。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D08

ECONOMIC_SEQUENCE：D06父信号→先延续→较晚十日底部→突破。

CAUSAL_BACKGROUND：父事件16至60日且持续未破S0。

STATE_VARIABLES：延续必须早于T-10；后五日比前五日窄，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：T收盘越过十日上沿及EMA。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：每父触发后至少10个新交易日，不后验重定阶段。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## D09

ECONOMIC_SEQUENCE：成熟整理→尚未突破时提前参与。

CAUSAL_BACKGROUND：此前D02背景，无D02突破触发。

STATE_VARIABLES：首次有效整理的10日U/S0/A固定episode，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：T收盘在U-.3A至U、阳线且低点守结构。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：未突破/没成交/失效都留存，实际高于U成交另标记。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## H01

ECONOMIC_SEQUENCE：D02父突破→延续→第一次回调→收复。

CAUSAL_BACKGROUND：每父信号15日独立时钟。

STATE_VARIABLES：延续先发生，随后第一次回测，5日确认，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：T收盘超过q高点与EMA9。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：不回头强势股不能从父事件分母消失。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。

## H02

ECONOMIC_SEQUENCE：D05相同机会→用突破前路径重新排序。

CAUSAL_BACKGROUND：候选、限价、退出完全同D05。

STATE_VARIABLES：只用b前30个交易日路径，保存父ID、冻结U/S0/A、到期与失效状态。

EVENT_FORMATION_TIME：背景最迟T-1可见；历史anchor仅表示价格发生日。

CONFIRMATION_TRIGGER：触发完全同D05。

ENTRY_TIME：确认后下一市场交易日开盘；DELAY1为T+2同冻结限价。

OUTCOME_START_TIME：实际成交之后；入场日为e=0，未成交单独记状态。

POSSIBLE_SEMANTIC_AMBIGUITIES：无正收益贡献时Path中性.5，不静默删除候选。

CHOSEN_TIME_ANCHORS：市场日历，不压缩停牌；背景/确认/下单/成交分栏；E10=e+10开盘，EST只于收盘确认后下一合法开盘退出。
