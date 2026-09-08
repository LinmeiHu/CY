"""Assemble the Chinese decision report from actual verified outputs."""
import json,datetime
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,log,dump,sha

def table(frame,percent=(),money=()):
    f=frame.copy()
    for c in f:
        if c in percent:f[c]=f[c].map(lambda x:f'{x*100:.2f}%' if pd.notna(x) else 'NA')
        elif c in money:f[c]=f[c].map(lambda x:f'{x:,.2f}' if pd.notna(x) else 'NA')
        else:f[c]=f[c].map(lambda x:'' if pd.isna(x) else f'{x:.4f}' if isinstance(x,float) else str(x))
    return '| '+' | '.join(map(str,f.columns))+' |\n| '+' | '.join(['---']*len(f.columns))+' |\n'+'\n'.join('| '+' | '.join(row)+' |' for row in f.to_numpy())+'\n'

def main():
    summary=pd.read_csv(HERE/'scenario_summary.csv');summary=summary[~summary.id.str.startswith(('MODULE_','REPEAT_'))].copy();ids=set(summary.id)
    summary['resolved_by']=[sid+'_CA' if sid+'_CA' in ids else '' for sid in summary.id]
    extra=[dict(id='MODULE_ANNOUNCEMENT_FINANCIAL',status='NOT_RUN_WITH_REASON',reason='公告精确用途授权/首发财务历史不合格；不解封',version_family='CONDITIONAL_NOT_ACCOUNT'),dict(id='MODULE_FIVE_STRATEGY',status='NOT_RUN_WITH_REASON',reason='400万元分数股权威基线与100万元合法股数口径不兼容；未整合',version_family='CONDITIONAL_NOT_ACCOUNT'),dict(id='MODULE_ETF_BASELINE',status='NOT_RUN_WITH_REASON',reason='本轮继承输入未绑定合格ETF账户所需历史行情/制度/费用；研究市场指数仅诊断',version_family='CONDITIONAL_NOT_ACCOUNT')]
    for sid in ['R1_S1_D08_C_10','PAST_ONLY_D08_C_10','FIX_A_D09_C_MAX_E10']:extra.append(dict(id='REPEAT_'+sid,status='VERIFIED_REPEAT',version_family='VERIFICATION_REPLAY',output=str(OUT/'verification'/(sid+'_manual' if sid.startswith('FIX_') else sid)),reason='实际全期重放，六份Parquet同hash'))
    summary=pd.concat([summary,pd.DataFrame(extra)],ignore_index=True);summary.to_csv(HERE/'scenario_summary.csv',index=False)
    good=summary[summary.status.isin(['COMPLETED','VERIFIED_REUSE'])].set_index('id')
    def select(names):return good.loc[names].reset_index()[['id','net_return','cagr','maxdd','mean_exposure','trades','profit_factor','max_single']]
    def sid(x):return x+'_CA' if x+'_CA' in good.index else x
    mainids=['A_H02_C_MAX_E10','A_H02_C_10_E10','A_D05_C_10_E10','A_D08_C_MAX_E10','A_D08_C_10_E10','A_H01_C_10_E10','R0_POOL_C_MAX','R0_POOL_C_10']
    mainids += [sid(x) for x in ['R1_S1_H02_C_MAX','R1_S1_H02_C_10','R1_S1_D08_C_MAX','R1_S1_D08_C_10','R1_LEVEL_D08_C_MAX','R1_LEVEL_D08_C_10','R4_LEVEL_D08_C_MAX','R4_LEVEL_D08_C_10']]
    def metric_table(names):return table(select(names),percent=['net_return','cagr','maxdd','mean_exposure','max_single'])
    pairs=pd.read_csv(HERE/'paired_comparison.csv');years=pd.read_csv(HERE/'annual.csv');stateyears=pd.read_csv(HERE/'strategy_state_year.csv');models=pd.read_csv(HERE/'state_vs_year.csv');rank=pd.read_csv(HERE/'ranking_diagnostic.csv');cash=pd.read_csv(HERE/'trade_cash_attribution.csv');score=pd.read_csv(HERE/'past_only_matched_score.csv')
    status=json.loads((HERE/'map_status.json').read_text());checks=json.loads((HERE/'FINAL_CHECKS.json').read_text());audit=json.loads((HERE/'attribution_status.json').read_text())
    report='''# USIC V4 市场状态路由与自适应研究结论

**独立判断：多策略路由为 NO_INCREMENTAL_EDGE；D08/C_10 简单新开仓开关为 CONDITIONAL_COMPONENT / KEEP_SHADOW；扩大资金、年度在线路由与 FULL_BOOK 不晋级。整体最高 SHADOW_ONLY。**

市场状态能描述部分差异，却不能充分解释2020/2021与2022/2023的变化。没有发现可推广到C_MAX、经过去信息重建仍胜出的状态路由。保留一个低优先级可验证假说：D08/C_10在广度低且不改善时暂停新开仓；这比原D08四年收益高约6.88个百分点，配对不确定区间仍跨零。不能将其称为新独立alpha、实盘方案或已完成五策略整合。

本轮已完成纠错、全十二入口地图、开关、同预算策略优先级、资金预算、已有持仓降风险、两个候选的成本/延迟/确认压力、一个年度过去信息重建及独立对账。没有打开CY-011或新的封存数据，没有真实下单，没有改生产或其他任务。

## 1. 范围、权限与可信起点

- 指定V3提交：`9f3c146939fd48759b113a74086164acfabcfae2`；本轮分支：`research/usic-market-router-v4`，从该提交新建隔离工作树。真实末端提交/远端状态见交付包外层 DELIVERY_STATUS.json，避免Git哈希自引用。
- 外接盘为真实挂载APFS卷 `/Volumes/quant`，初始余量约2.8TiB。完整输入、中间结果、账户及日志均在独立V4外接盘目录。V1/V2/V3、五策略源文件与任务未切换、未修改、未终止。
- 数据仅2018—2023：2018—2019暖机，2020—2023共970个账户交易日，5262个原始证券轴，支持板块和历史失效规则原样保留。PIT-B、开盘/分钟OHLC执行代理，不是PIT-A或竞价排队可复制证明。
- 已核对CY当前主工作树与V3后继工作树的资产/用途注册快照。CY-027已有其他策略2024—2025用途，CY-062已有其他策略2022—2026滚动用途；旧STATE里的“2024+未读”不是全项目最新事实。不能把2024+自封为独立OOS。本轮没有读取其行情或受限标题。2014—2020旧研究存在已消费记录，但未将未绑定的额外输入挪用到本任务。
- 五策略仍为400万元、原生分数股且未建全市场股票容量的权威基线，未发现本用途下兼容的100万元合法股数基线；整合不执行。公告/财务权限缺口只阻塞依赖模块。

38项继承行情/缓存哈希、原入口manifest、交接包全部文件哈希、市场指数一致性均已核验。原V3报告与源码包保留原哈希。`SAMPLE_PERMISSION_AUDIT.json`记录各注册快照差异。

## 2. 先纠错：影响真实，方向并不总是改善

D09有7146个episode，其中422个在首次突破后才发出advance，占原1843个信号22.90%；修复后1421个。最小修复增加首次突破尚未发生的条件，保留全部episode、原advance列及后续突破/失效事实。失效检查先于突破/提前参与；收盘等于U可提前参与，收盘大于U则禁止；不推断同日盘中高低顺序。合成反例及五只真实受影响证券的原函数重建均通过，非D09事件不变。

36个D09及P0/P1/P2/P3依赖账户被重放，并非252账户全部重跑。D09/C_MAX/E10由−67.05%变为−45.45%，C_10由−43.57%变为−49.04%；P3/C_ONE/EST由+292.62%变为+214.39%。原冠军仍集中且语义纠错后收益下降，不能作为通用组合政策。

Q3独立实现也有问题：1805个信号中，412个之前已有14:25收盘突破，393个之前已有日收盘突破，合并423个。修复只看当前决策前已完成的这些收盘观察，保留1382个信号；12个BASE/ENHANCED现金账户独立重放。Q4不受此信号修复影响。完整原值/修正值分别见 `d09_correction_impact.csv`、`q3_correction_impact.csv` 和情景表的恢复版本。

纠错及新路径触发了原V3未持有的公司行动，11次账户尝试先停在事实缺口。已核对4份发行人实施公告，补入688556、603916、603319、600845的实际新增股份上市日期；另建 `_CA` 恢复账户，保留原阻塞记录。未假定除权即能卖，也未解除公告alpha权限。

## 3. 全十二入口地图及年份反例

S0完全重现V3公式和T−1索引；S0_CURRENT仅把相同公式更新到信号T收盘。S1在读条件收益前登记：B60>=0.5 × B20(T)−B20(T−10)>0，四格只描述广度水平/变化。ST和停牌不因不能成交就从历史市场池消失；缺少所需均线历史的证券从分子分母同时排除并计数；UNKNOWN不开放新仓。连续趋势距离、广度、变化、回撤、波动另列，未搜索收益最优阈值。

''' + f"地图含{status['events']:,}个路线事件标签，{status['statuses']['MATURED']:,}个已成熟的标准化现金诊断；其余成交拒绝、未成熟及{status['statuses']['ACTION_DIAGNOSTIC_BLOCKED']}个局部公司行动诊断缺口逐项保留。标签数不是独立样本数，D05/H02与D01/D02共享底层候选。每事件10万元计划预算、合法股数、费用、T+1开盘、e+10下一合法开盘；涉及权益的诊断复用原账户引擎。独立事件预算从未相加成资金池。\n\n"
    report += table(pd.read_csv(HERE/'state_occupancy.csv'))
    report += '\n四格每年都有，但条件收益方向不稳定。以下是等信号日期权重的标准化现金收益，空格表示无支持，不用某年的名称定义状态：\n\n'
    y=stateyears[(stateyears.capital=='C_10')&(stateyears.state_definition=='S1')&stateyears.route.isin(['D08','H01','H02'])].pivot(index=['route','state'],columns='year',values='equal_date_return').reset_index();report+=table(y,percent=[2020,2021,2022,2023])
    report+='\nD08的线索更像成熟延续阶段：高广度不改善格在2020/2021/2022为正、2023为负；低广度修复格三年负。H01的低广度不改善格在2020/2021/2023为正而2022严重负，直接反驳“熊市岗位”的固定叙事。H02同一候选的日期均值更多随年份变化。解释性R²如下；不是因果识别或可部署预测：\n\n'
    report+=table(models[models.route.isin(['D06','D08','H01','H02'])][['route','dates','state_r2','year_r2','state_increment_given_year']],percent=['state_r2','year_r2','state_increment_given_year'])
    report+='''
地图A详见 strategy_state_map/year/board.csv：信号数、日期、连续状态段、合法成交率、日期权重收益、标准化投入PNL、实际账户PNL、胜率/PF、尾部、MFE/MAE、占资时间均保留。地图B见 holding_state_account_pnl.csv、holding_transition_pnl.csv：真实账户逐日PNL、信号状态到持有状态的迁移分开。逐lot标记及现金流有独立公司行动应收/税时序剩余项，见 holding_pnl_residual.csv；没有把事后坏日从净值删除。

同开盘时钟的全市场等权诊断见 market_beta_diagnostic.csv，行业/板块在历史归属下另列。研究指数不是ETF现金账户；不能凭它宣称可交易beta对照或已证明行业alpha。旧Market State Engine/Habitat仅部分机会生成和描述坐标有支持，未把其升级成已验证退出规则，也未重启已否决Formation Depth家族。

## 4. 排名与执行：哪些损失在市场标签之前就存在

排名只保留一行底层候选，用实际PathScore、原基础分数、原有收益/MAX/波动/beta/流动性/流通市值及板块/行业控制，日期固定效应只识别同日排序和交互，不识别市场状态主效应。全候选、静态前十、账户实际选到可准备订单位置、实际分到现金分别报告；没有训练新权重。

'''
    report+=table(rank[(rank.layer=='ALL')&(rank.term=='path_score')][['pair','n','dates','coefficient','ci_low','ci_high']],percent=['coefficient','ci_low','ci_high'])
    report+='''
H02与D05/C_10的真实净值差约35.69万元，主要是交易集合变化：共同交易权重约+1.31万元、H02独有交易约+12.15万元、未做D05独有交易约+24.31万元，期末/其他剩余约−2.08万元。相同事件贴两个标签的旧treated回归作废；修正后也不能把跨零区间叫“证明绝对无效”。

D08/C_MAX相对C_10少58.10万元，其中共同交易权重项约−55.53万元。满仓失败主要与较少机会时的大额配置及资金路径有关，不能用平均利用率线性放大C_10收益。C_MAX最高单票接近全仓，C_10仅约束新买入初始金额。

低开已经跌破冻结结构线不是主要统一解释：原C_10中D08为0笔；H01为2笔合计约−1.07万元；D06为2笔约−0.21万元；H02有1笔反而约+2.92万元。没有加入看完最终开盘才取消同次开盘交易的后验过滤。

D06原事件“10日收盘报价均值正”不能与账户直接相减；本轮已统一费用和e+10开盘，日期权重后的状态格大多为负。EST的结构/SMA10/MAX40退出分别列数与PNL，不将合成退出包失败解释为所有止损无效。延迟D08/C_10相对原版多26.48万元：246个共同完成事件的价格/退出/费用项约+36.56万元，同时135个独有及137个错失事件抵消部分改善，不能只归功于更好买入价。

所有金额分解为对称算术归因，资金再投入和交易选择有交互；它们不是唯一可加的纯因果贡献。详见 trade_cash_attribution.csv、execution.csv。

## 5. 主账户与可解释对照阶梯

所有收益都是100万元单一真实现金账本的四年净收益；年化另列。最大回撤保留负号。空仓零利息、借款和保证金为0，开盘卖出款不回填同次预承诺买单，冻结后失败单不追溯补买。多个策略标签在同一证券上只形成一个物理持仓。

'''+metric_table(mainids)
    report+='\n固定共享池由H02/D08/H01构成，H02与D05二选一不重复占资，路线内同日百分位比较、确定性同分处理。R2只在HIGH_NONIMPROVING优先D08，其余保持原排序；其资金目标、退出、开关与对应R0/R1完全相同：\n\n'
    report+=metric_table(['R1_S1_POOL_C_MAX','R2_PRIORITY_GATE_C_MAX','R2_PRIORITY_OPEN_C_MAX','R1_S1_POOL_C_10','R2_PRIORITY_GATE_C_10','R2_PRIORITY_OPEN_C_10','R4_S1_POOL_C_MAX','R4_S1_POOL_C_10'])
    report+='''
无开关时路由较静态池：C_10 +5.28个百分点，C_MAX −8.23个百分点；有相同S1开关时：C_10 +3.34、C_MAX −1.12个百分点。两模式及20日时间块区间不支持一致增量。停止该优先级分支，未继续softmax或为每年分配不同策略。

V3 G_DOWN仅关新仓，H02/C_MAX从44.70%降至17.34%；G_RAMP降至−15.25%。相对无开关，原基线独有交易PNL在对应算术分解中分别被错失约29.31万、58.96万元，旧仓仍可跨入弱状态。G_RAMP还把平均利用率降至约41.86%，未解决旧仓过渡；P2只在D02/D03/D06/D09内排序，不包含本轮重点路线，不能当作同预算三路线准入对照。S0_CURRENT/H02仅更新时点也不一致改善：C_MAX +24.81%，C_10 −11.39%。详见 old_gate_removed_opportunities.csv、state_occupancy.csv，不能用“旧指标粗”代替这些实际损益证据。

## 6. 资金预算、FULL_BOOK与必要压力

'''
    names=[f'FIXED_{b}_D08_{mode}' for mode in ['C_MAX','C_10'] for b in [25,50,75]]+[f'R3_HALF_D08_{mode}' for mode in ['C_MAX','C_10']]
    report+=metric_table(names)
    report+='''
固定预算是事前目标投入上限，不是事后暴露缩放。静态低预算大多亏或接近零；D08/C_10简单开关的改善不能完全由这条固定预算曲线解释，但这仍不证明路由alpha。新增0/50/100%状态预算在C_10仅12.32%，低于LEVEL的14.81%；C_MAX虽少亏仍为−21.67%。不晋级预算分支。

FULL_BOOK先只试坏状态目标0，并严格在下一合法开盘降风险。D08 LEVEL/C_10从14.81%降到1.03%，最大回撤由15.68%变为15.26%，共同交易价格/提前退出等项损失约14.82万元；收益代价大于这点回撤改善。共享池FULL_BOOK降低回撤却没有恢复盈利。没有证据据此继续优化每只股卖出顺序或开启确认长度搜索。

目标不是保证：D08 LEVEL/C_10有5个交易日未能降至0，最大仍持10.10万元；C_MAX相应33.83万元。共有100/88条降风险意图。延期及资本日详见 fullbook_unreduced.csv，未将超目标敞口从NAV中“修掉”。恢复状态不自动补回旧仓，也不重置所有权/持有时钟。

'''
    names=[f'R1_S1_D08_{stress}_{mode}' for mode in ['C_MAX','C_10'] for stress in ['COST2','DELAY1','C3']]+['R1_S1_D08_C_ONE','R1_LEVEL_D08_C_ONE']
    report+=metric_table(names)
    report+='''
COST2完整重走费用、整手、限价与资金链；DELAY1冻结原信息、限价及状态，延到T+2，未中途重决策。C3仅为一个连续3日坏状态确认邻居，不是1—30日搜索。LEVEL的完整同组压力亦在情景表，不只展示简单开关。单票压力均亏损，因此不从C_ONE中选冠军。D08简单开关相对基线的配对年化差区间约−2.23至+5.44个百分点，仍跨零；成本与延迟下的匹配基线增量见 paired_comparison.csv。

## 7. 过去信息顺序重建与跨年迁移

年度节奏事前冻结。每年末仅使用实际退出后已成熟的D08标准化诊断；每状态至少20个独立信号日期和3个连续状态段，等日期净收益均值>0才开放，否则现金。2020按原D08运行，2021起执行历史映射与同期间评分，不年初清仓、不重置本金。记录 fit_cutoff、最大label_available_t、effective_from 和每笔订单信息边界。4项官方事实修补后的标签估计略有变化，全部12个年度状态动作保持一致，另表核验。

'''
    selected=['A_D08_C_10_E10','R1_S1_D08_C_10','R1_LEVEL_D08_C_10_CA','PAST_ONLY_D08_C_10']
    report+=table(score[score.id.isin(selected)][['id','score_start','score_end','net_return','maxdd','mean_exposure']],percent=['net_return','maxdd','mean_exposure'])
    report+='\n四年的同账户年度表现：\n\n'
    yr=years[years.id.isin(selected)].pivot(index='id',columns='period',values='net_return').reset_index();report+=table(yr,percent=[2020,2021,2022,2023])
    report+='''
重建2023只剩高广度不改善格获得历史支持，却未带来当年优势；过去选择程序没有重现全样本候选的改善。此为 PAST_ONLY_RECONSTRUCTION_ON_CONSUMED_DATA，不能恢复2020—2023已消费历史的独立验证身份。没有LOYO未来训练回过去，也没有打开2024+。未来若验证，仅准备冻结D08/C_10简单开关与原D08的配对，须先单独授权并核对整个CY消费台账、合格历史制度/执行数据；不是本轮自动执行的下一步。

## 8. 自适应循环、实际状态与剩余缺口

研究按6轮有区分力的循环推进：①真实D09/Q3时序纠错及依赖重放；②全入口时钟/状态/排名地图；③S0时点、S1开关与FULL_BOOK；④地图驱动的D08优先级及广度Level贡献；⑤0/50/100与固定预算、两个候选压力；⑥年度过去信息重建、事实恢复、最终对账。每次收益导向变化之前均记录证据、经济顺序、变更、基线、预期和反驳条件；全部见 RESEARCH_LOG.jsonl。没有见到第一个赢家就停，也未重启失败策略入口参数。

完成48个V4新情景、48个必要纠错情景，54个原账户哈希及现金审计复用；另有原H02经济一致性全期回放1次、两个最终代表全期重复2次，另有D09纠错代表一次独立命令重放。新情景远少于240预算，主假说少于24；没有为了凑数扩张。11个先行阻塞尝试均有 `_CA` 完整恢复，原记录不删除。67个单事件诊断仍缺少更广公司行动的上市日期（其中D08剩1个），分母和缺失行保留；这不等于完整现金账户阻塞。公告、财务、ETF账户对照与五策略整合仍未运行，原因单列。

工程异常同样留档：初始纠错筛选错误地接受了I4标签并跑成普通P1独立账户；该尝试标 INVALIDATED_DISPATCH_ERROR，绝不称五策略整合或纳入经济比较，筛选已限制A/B/E。原过程加载的纠错引擎与运行期间磁盘后续版本的绑定差异已依据保留的原源码修复，原哈希与修复记录均留存。单事件修补曾因无缺失列而中断，随后针对已完成缓存恢复；统计曾触发缺少SciPy，改用等价秩相关和显式特征分解，无新增依赖。所有早期日志与失败记录保留，成功标准以最终审计为准。

'''+f"最终：{audit['verified_accounts']}个研究/复用账户通过独立现金流、NAV、持仓、已实现加未平仓PNL对账；20项基础/路由测试通过；{len(checks['checks'])}项最终检查通过，包括两代表12份Parquet逐字节重复一致、真正截断日历的历史NAV/订单一致、全十二路线标准化事件与原引擎现金时钟一致。38项输入哈希与原入口manifest通过。借款/保证金0、现金非负、合法整数股、同股单物理持仓与T+1约束保持。\n\n"
    report+='''
交付包含全部真实状态表、年/月/状态/交易及资金归因、订单决策信息样例、代表账户完整NAV/订单/成交/审计/持仓/期末仓位/输入、源码与实际命令。外接盘全量明细未全部复制入轻量包的部分有路径、大小与SHA256清单；代表账户并非只有本机路径。提交仅进入本任务分支，普通push结果按实际远端核验记录，不合并生产。

结论边界：本轮找到了应修复的事件定义、可核验的资金路径解释和一个受限影子开关；没有找到已被充分确认的多策略市场路由增量。
'''
    (HERE/'REPORT.md').write_text(report)
    dump(HERE/'completion.json',dict(status='COMPLETED_WITH_LOCAL_DATA_GAPS',reference_v3_commit='9f3c146939fd48759b113a74086164acfabcfae2',branch='research/usic-market-router-v4',start_head='9f3c146939fd48759b113a74086164acfabcfae2',new_completed_accounts=48,correction_completed_accounts=48,verified_reuse=54,verification_full_replays=4,blocked_attempts_recovered=11,invalidated_dispatch=1,adaptive_cycles_completed=6,new_hypothesis_families=22,new_account_budget=240,new_sealed_validation_opened=False,real_orders_sent=False,production_modified=False,data_grade='PIT-B',data_range='2018-2023; accounts 2020-2023',sample='CONSUMED_DEVELOPMENT',past_only='PAST_ONLY_RECONSTRUCTION_ON_CONSUMED_DATA',verdict={'router':'NO_INCREMENTAL_EDGE','D08_C10_simple_gate':'CONDITIONAL_COMPONENT_KEEP_SHADOW','FULL_BOOK':'DO_NOT_ADVANCE','capital_scaling':'DO_NOT_ADVANCE','online':'DO_NOT_ADVANCE'},final_checks_pass=True,commit_status='SEE_EXTERNAL_DELIVERY_STATUS',remaining_event_fact_gaps=status['statuses']['ACTION_DIAGNOSTIC_BLOCKED']))

if __name__=='__main__':main()
