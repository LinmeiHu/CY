"""Render compact Chinese research report from verified result tables."""
import json
from pathlib import Path
import pandas as pd
from run_closure import HERE,sha,write_json

def table(frame,cols,percent=()):
    d=frame[cols].copy()
    for c in d:
        if c in percent:d[c]=d[c].map(lambda x:'NA' if pd.isna(x) else f'{100*x:.3f}%')
        elif pd.api.types.is_numeric_dtype(d[c]):d[c]=d[c].map(lambda x:'NA' if pd.isna(x) else f'{x:.3f}')
    return d.to_markdown(index=False)

def run():
    s=pd.read_csv(HERE/'smv6_account_comparison.csv');p=pd.read_csv(HERE/'portfolio_exit_overlay_comparison.csv')
    stock=pd.read_csv(HERE/'retained_stock_account_comparison.csv');m=pd.read_csv(HERE/'five_strategy_exit_decision_matrix.csv')
    a=pd.read_csv(HERE/'smv6_native_trade_anatomy.csv');identity=json.loads((HERE/'baseline_identity.json').read_text())
    audit=pd.read_csv(HERE/'smv6_execution_audit.csv');integrity=json.loads((HERE/'integrity_validation.json').read_text())
    periods=s.loc[s.period.isin(['2018_2021','2022_2023'])]
    lines=['# 五策略退出风险 Closure V2','',
    '本轮完成四个 SMV6 固定候选的实际账户重放、四套股票既有结果复用，以及 24 组四袖套组合比较。生产策略全部维持原生退出。MCB Profit Protection 是本轮最值得优先 shadow 观察的账户/组合候选；OGR、IFCGR ATR×1 只保留有限观察；SMV6 ATR×1 保留有明显阶段差异的 shadow；拒绝将 ATRDR Fast 5% 纳入主方案。',
    '', 'TASK_STATUS: PARTIAL_COMPLETE。这里的限制是原生早期两日净值缺失，早期及全历史部分账户风险指标无法估计，以及既有 ATRDR 源链隔离导致组合结论仅为条件性历史研究。四个合法 SMV6 候选、两段组合及五策略裁决均已实际算完；没有用替代净值冒充补齐。',
    '', '## 证据与执行口径','',
    '- 当前代码树直接执行冻结 SMV6 源码，源码 SHA256 `7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33`。权威 standalone 元数据为 779 策略事件、1081 执行事件、3260 账户日；旧外接目录的 769 事件版本被明确排除。',
    f'- 只重放已授权的 2013-04-01 至 2023-12-29：源码生成 {identity["authorized_prefix_strategy_events"]} 个策略事件、{identity["authorized_prefix_days"]} 个账户日，与权威封存前缀一致。3260 日延伸到 2026-08-28，后段只核对既有元数据与文件哈希，未读取后段结果。golden 事件不参与生产执行。',
    '- SMV6：100 股整手、2bp commission、单侧 8bp slippage、50% 分钟成交量上限。标签 `LOCAL_END_TO_END_REPRODUCIBLE_PLATFORM_EQUIVALENCE_UNVERIFIED`；未声称原生 SuperMind 等价。',
    '- 原有股票账户为冻结 normalized 模型，单侧 0.2% 成本，保留原先仓位/顺序/容量；OGR 和 IFCGR 内部主板/创业板各 0.5。没有把股票分数份额模型伪装成 SMV6 整手经纪商执行。IFCGR 读取自己的重放账本，未复制 OGR 指标。',
    '- 候选合同先落盘冻结，SHA256 `'+sha(HERE/'smv6_exit_candidate_contract.json')+'`。直接复用 `state_v2.policy_mask / causal_features / entry_atr`。ATR 为入场前 21 个连续有效日算出的 20 日平均 TR。Profit Protection 精确定义为 MFE≥5% 且当前收益≤0。',
    '- 触发只用 16:00 已完成日线。下一交易日按冻结 OPEN_BAR_09_30 已完成条的参考价执行，承认此本地语义不是已证实的真实集合竞价；跳空用实际参考价，不用阈值价。新增退出保守 T+1，失败锁存重试，部分成交保留剩余库存。原生更早退出优先，同时开盘原生卖出优先归因。',
    '- 新增 overlay 与原生合计不能重复消耗同一股票同一分钟容量。风险待退出股票只在该次开盘抑制冲突买单；后续合法原生信号继续，包括再次买入同 ETF，无新 cooldown。现金留在本袖套，新增交易收益已纳入 NAV。',
    '- 所有数据均属于已消费历史。2018–2021 / 2022–2023 独立列示，OGR/IFCGR 2022 年重置，其余连续账户在各比较段从前一日 NAV 重基并保留既有持仓；重基不是重新从空仓运行。无新封存验证、无新规则、无视觉 lane、无权重优化。',
    '- ATRDR 的 Bull/Slow 源前缀缺陷仍标记 `QUARANTINED_PRODUCTION_PREFIX_DEFECT`。本轮依照指示复用、不改冻结源链，所有组合均继承此限制。IFCGR 保留 PIT-B 公告修订/删除历史不完整限制。',
    '', '## SMV6：原生损失结构','',
    f'共 {len(a)} 个原生完整 position episodes，2018–2021 为 44 笔、2022–2023 为 21 笔，全部授权历史内无未平仓期末库存。最差三笔净收益为 −6.82%、−6.25%、−5.73%，对应 MFE 约 1.23%、0.03%、0.08%，主要表现为入场后低 MFE 的持续走弱，不能概括成“大赚后的回吐”。没有原生净亏损超过 10% 的 episode。',
    '原生退出原因包含市场周线/紧急退出、自身 MA40 退出，以及成交未完成后的重试。日线低点不能证明本可按阈值成交；成交量约束下多次部分卖出会拉长完整 episode。所附 anatomy 给出这些真实退出原因，不据此增加参数，也不声称所有损失都由 MA 规则太慢造成。',
    '',table(a.nsmallest(5,'net_return'),['episode_id','holding_days','net_return','MAE','MFE','entry_ATR'],['net_return','MAE','MFE']),
    '', 'Anatomy 的价格 MFE/MAE 以第一笔真实成交价为基准；episode 净收益则包含所有加减仓现金流和费用，两者不能机械相减作归因。开盘退出日不使用之后的日线高低点；跳空字段是价格路径算术和，不是现金收益加法分解。capital-days 为持仓日末市值之和，close 卖完当天余额为零。',
    '', '## SMV6：四候选账户结果','',
    table(periods,['candidate','period','trades','added_trades','worst_trade','CAGR','MaxDD','CVaR5','worst_month','worst_quarter'],['worst_trade','CAGR','MaxDD','CVaR5','worst_month','worst_quarter']),
    '', '四个定义均可合法映射，缺失有效前置 ATR 或当日字段时逐 episode/day 禁止推断触发。5% 固定止损在前段恶化最大回撤，且两段最差单笔均可能更差。3% 的后段回撤改善伴随较大收益代价，前段最差月/季明显恶化。Profit Protection 前段几乎无实质效果，后段虽减回撤却损失收益。ATR×1 前段收益和最差月/季变差，后段风险与收益一起改善，因此仅保留 shadow，不按后段表现调参数或宣称跨期稳健。',
    '', '### 持仓时间与实际资金再用','',
    table(periods,['candidate','period','closed_trades','avg_holding_days','common_native_holding_days','common_holding_days','capital_weighted_holding_days','added_trades','added_trade_realized_pnl'],['added_trade_realized_pnl']),
    '', '持仓天数统一为交易日序号差（不含入场日），仅对该区间内已完成的入场 cohort 统计；未完成单另计右截尾，不偷看下一段退出。capital-weighted 以 episode 累计投入现金加权，包括原生加仓。共同交易只比较同 ETF/入场日且两账户都已结束的 episode。新增 episode 按身份差集识别，可能包含退出后同 ETF 再入场，不能都解释为“仅因现金不足解除”。',
    '新增交易 PnL/期初 NAV 是账户反馈的一个可核对组成项，已在 CAGR 中体现，不能再把资金释放天数乘假定年化叠加。SMV6 ATR×1 全授权历史新增7个 episode，合计实际 PnL 为 −14,933.66 元（100万元初始账户），说明释放现金后交易并不保证盈利。完整期末差异由共同 episode PnL 变化、新增 episode PnL、消失 episode PnL 三项对账；共同项包含数量与再平衡变化，未强行拆出不可识别的纯资金释放 alpha。见 `smv6_cashflow_decomposition.csv` 和 `smv6_released_capital_trades.csv`。',
    '', '### 早期与全授权历史','',
    table(s.loc[s.period.isin(['EARLY_2013_2017','ALL_AUTHORIZED'])],['candidate','period','trades','closed_trades','total_return','CAGR','missing_nav_days','avg_holding_days'],['total_return','CAGR']),
    '', '2015-04-13 / 2015-04-14 是权威原生账本已有缺失，不作前向填充、线性插值或当作现金。早期和全历史的 MaxDD/CVaR、恢复与资本占用等需要完整路径的表项保留 NA；端点有效，所以总收益和 CAGR 正常计算。逐笔结果、真实现金流水、两段完整窗口指标也可计算。官方 anatomy 对缺失标价 episode 的 capital-days 留 NA 并给出缺失计数；外接盘原始 episode 中间表的对应原始和仅代表已知标价，不能拿它当完整资本占用。',
    '', '## 四套股票既有结果复用','',
    table(stock,['strategy','period','variant','trades','CAGR','MaxDD','CVaR5','worst_month','worst_quarter','avg_holding_days'],['CAGR','MaxDD','CVaR5','worst_month','worst_quarter']),
    '', 'MCB：2018–2021 CAGR 约付出 0.422 个百分点，MaxDD 改善约 0.855 个百分点；2022–2023 CAGR 增加约 0.183 个百分点，MaxDD 改善约 0.437 个百分点。这个共同窗口结果不能抹掉旧 2014–2023 全历史约 0.891 个百分点 CAGR 代价。新增交易与原先释放资金分解仍保留在输入证据中。',
    'OGR/IFCGR：两段独立账户的损失幅度、CVaR 和持仓占用有同方向改善，但账户层绝对改善较小，不能据此保证组合尾部更好。ATRDR Fast 5% 在全历史账户最大回撤略差，本轮两个子段可能不同，不允许挑出有利子段就推翻既定诊断定位。',
    '', '## 四袖套组合：初始等额，各自独立复利','',
    'A = ATRDR + MCB + OGR + SMV6；B 用 IFCGR 替换 OGR。每段各袖套期初单位净值为 1，Q(t)=0.25Σq_i(t)，现金和敞口按同一比例合成。禁止每日等权收益平均、跨袖套资金搬运、借款或把闲置资金放大再投。',
    '',table(p,['portfolio','period','variant','CAGR','MaxDD','CVaR5','worst_month','worst_quarter'],['CAGR','MaxDD','CVaR5','worst_month','worst_quarter']),
    '', '组合 A 前段 ALL_RETAINED 相对 ALL_NATIVE：CAGR 约 7.843%→7.449%，MaxDD 约 3.749%→3.660%；后段 CAGR 约 4.064%→4.179%，MaxDD 约 2.311%→2.129%。B 同方向。联合方案并非无成本稳健优于原生：前段 MCB 单独介入已有更好的收益/回撤取舍，加入 GAP 与 SMV6 会消耗收益并抵消部分尾部好处。',
    'MCB 单独介入在两段均改善组合 MaxDD/CVaR，前段最差季度改善较明显；后段最差月份却稍差，仍不是全指标支配。GAP ATR×1 单独介入在前段略增组合 MaxDD、月/季损失，后段 MaxDD 几乎不变、CVaR略差，因此不能称“两段组合均改善”。SMV6 ATR×1 后段主要改善 CVaR/月度，组合 MaxDD 并未下降；前段收益和最差季度变差。',
    '', '全部 total return、worst rolling 21-day、最差月/季、Sharpe、最长回撤期、回撤低谷至恢复天数、恢复右截尾、平均现金/敞口、turnover/costs 见完整 CSV。CAGR 使用声明的自然日窗口长度/365.25，可能与前报告按实际首末交易日年化有细小差异；不改变经济账本。CVaR 为最差 ceil(5%×N) 日收益均值；Sharpe=日均值/样本标准差×√252、无风险利率0；turnover 是双向成交额/比较段期初 NAV 的累计值，未年化；costs 包含显式费用与 SMV6 滑点成本。',
    '恢复时间从窗口最大回撤低谷算至再创窗口高点；没有恢复则 NA 并置 recovery_censored。最长回撤时长包含尚未结束的尾部。组合最差十日贡献按 0.25×Δq_i/Q(t−1) 计算，可逐日精确加总，见 `portfolio_worst_days.csv`。',
    '', '## 校验与复跑','',
    f'- 不变性检查 {integrity["checks"]} 项，差异 {len(integrity["mismatches"])}；原冻结策略/原始输入/父研究和视觉研究封存哈希保持。',
    '- 原生及四候选重复重放，35 个核心输出的规范化内容哈希逐一比较；结果见 `determinism.json`。规范化浮点为 12 位有效数字，身份/事件次序/账户行数不做近似。',
    '- 相关测试见 `validation.txt`：源码生产与 reference 隔离、合同先冻、PIT、跳空、整手、成本、容量、现金、部分成交、再入场、现金分解、家族互斥、非每日再平衡、两段隔离及确定性。',
    '- 无负现金、可观察账户时点无 gross>NAV。两日缺失标价明确保留，不能把可观察时点检查称为补齐了缺失时点。',
    '- 复跑命令见 `REPRODUCTION_COMMANDS.md`。大账本和授权原始行快照在外接盘；Git 仅存研究代码、合同、输入身份、紧凑表格、测试和报告。未 push。',
    '', '## 最终十问','',
    '1. **SMV6 大亏是什么路径？** 最差三笔都是低 MFE 后走弱，自身/市场退出及受容量限制的卖出重试共同构成最终路径；不是主要由高浮盈回吐造成。不能从事后路径证明早期信号可预测。',
    '2. **哪些候选合法？** 四个已有定义均可执行；ATR 或有效日线缺失时对该状态 fail closed。没有新阈值、理想止损价或日内 low 推断。',
    '3. **SMV6 是否新增退出？** 生产 KEEP_NATIVE；ATR×1 为 SHADOW_OBSERVATION，其余三个 REJECT。前后段风险收益取舍不同，不改冻结规则。',
    '4. **OGR ATR×1 两段账户和组合都值得吗？** 两段账户同方向改善，成本较低；组合未稳定改善，仅 SHADOW_OBSERVATION，不获组合推广结论。',
    '5. **IFCGR 继承是否同方向？** 是，分别读取 IFCGR 自己的两段账本；2022–2023 指标相同是实际重放结果，非复制。仍受 PIT-B 限制，SHADOW_OBSERVATION。',
    '6. **MCB 的代价值得吗？** 本轮共同窗口和组合最支持它继续观察：两段 MaxDD/CVaR 均改善，前段付出收益、后段收益增加。但全历史收益代价与后段最差月稍差仍存在；优先 SHADOW_OBSERVATION，不立即生产修改。',
    '7. **为什么拒绝 ATRDR Fast 5%？** 路线持仓缩短未稳定传导成全账户风险改善，收益有代价，源链仍隔离；只保留拒绝理由的诊断对照，不进首选联合方案。',
    '8. **五套最终状态？** ATRDR=KEEP_NATIVE / Fast5 REJECT；MCB=KEEP_NATIVE + Profit SHADOW_OBSERVATION；OGR=KEEP_NATIVE + ATR1 SHADOW_OBSERVATION；IFCGR=KEEP_NATIVE + 继承 ATR1 SHADOW_OBSERVATION；SMV6=KEEP_NATIVE + ATR1 SHADOW_OBSERVATION。',
    '9. **联合候选改善组合吗？** 两段 MaxDD/CVaR改善但改善来自不同组合，前段联合方案比 MCB 单独方案更昂贵，后段更有利；不是全指标或跨期无条件支配，不能把作用重复记功。',
    '10. **下一步改冻结策略吗？** 不。现阶段只进入 shadow forward observation，优先 MCB；保留对 GAP、SMV6 的有限观察，先恢复原生缺失标价/闭合 ATRDR 源链，再谈冻结规则变更。无 `PROPOSE_FROZEN_RULE_CHANGE_PENDING_FORWARD_EVIDENCE` 的正式推广。','']
    (HERE/'REPORT.md').write_text('\n'.join(lines))
    print('REPORT generated')

if __name__=='__main__':run()
