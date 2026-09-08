"""Render the Chinese closure from the complete registered matrix, without selecting new experiments."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .common import HERE,OUT,sha,dump
from .analyze import STATS

NAMES={'D00':'成熟趋势普通突破','D01':'成熟趋势加动态VCP','D02':'VCP加前段路径排名','D03':'强趋势EMA回调收复','D04':'回调加AVWAP重合','D05':'旧突破水平与EMA支撑重合','D06':'早期低位转强','D07':'早期转强后的首次回测','D08':'父转强后的后续延续','D09':'突破前提前参与','H01':'VCP突破后等待第一次回调','H02':'支撑重合加父突破前路径排名'}
STATUS={'COMPLETED_NEW':'新运行完成','BLOCKED_PERMISSION':'权限阻塞','NOT_RUN_DATA_GATE':'未通过数据资格','BLOCKED_INPUT':'既有账户基线阻塞'}

def pct(v):return '—' if pd.isna(v) else f'{v*100:.2f}%'
def table(df,cols):
    lines=['| '+' | '.join(label for field,label in cols)+' |','|'+'|'.join(['---']*len(cols))+'|']
    for r in df.to_dict('records'):
        vals=[]
        for field,label in cols:
            v=r.get(field)
            if field in ['net_return','cagr','maxdd','mean_exposure','max_exposure','max_single','net_return_difference','cagr_difference','bootstrap_cagr_diff_p025','bootstrap_cagr_diff_p975']:v=pct(v)
            elif field in ['trades','signals','filled_buys']:v='—' if pd.isna(v) else str(int(v))
            elif field=='status':v=STATUS.get(v,v)
            elif v is None or isinstance(v,float) and np.isnan(v):v='—'
            vals.append(str(v).replace('|','/'))
        lines.append('| '+' | '.join(vals)+' |')
    return '\n'.join(lines)+'\n'

def main():
    f=pd.read_csv(HERE/'scenario_summary.csv');ok=f[f.status=='COMPLETED_NEW'];assert len(f)==296 and len(ok)==252 and not f.status.isin(['RUNNING','PLANNED_NOT_EXECUTED','INVALIDATED_BY_BUG']).any();by=f.set_index('id');pair=pd.read_csv(HERE/'incremental_comparison.csv');counts=json.loads((HERE/'FEATURE_MANIFEST.json').read_text())['counts'];audit=json.loads((HERE/'ACCOUNT_AUDIT.json').read_text());assert audit['accounts']==252 and audit['all_pass']
    decisions={r:dict(name=NAMES[r],research='NO_INCREMENTAL_EDGE',execution='FEASIBLE_UNDER_STATED_ASSUMPTIONS',deployment='REJECT',reason='本轮机械定义未形成可保留的稳健净收益/增量。') for r in NAMES}
    decisions['D00'].update(research='ALREADY_COVERED',reason='信号精确继承V2 N1，本轮重新验证真实现金与容量；基准为负收益。')
    decisions['D01'].update(research='COMPONENT_ONLY',reason='收缩准入部分改善普通突破亏损，但全部三资金模式主账户仍亏损。')
    decisions['D05'].update(research='COMPONENT_ONLY',reason='E10尽可能部署仅小幅正收益、回撤49.89%；作为H02可核查的同候选对照保留，不独立部署。')
    decisions['D08'].update(research='COMPONENT_ONLY',execution='EXECUTION_FRAGILE',deployment='SHADOW_ONLY',reason='仅冻结C_10/E10保留机会稀疏的影子组件；成本/延迟压力仍正，但平均利用率36.94%，C_MAX与C_ONE均失败。')
    decisions['H01'].update(research='INSUFFICIENT_EVIDENCE',execution='EXECUTION_FRAGILE',reason='C_10出现正收益但明显依赖资金模式，C_MAX/C_ONE深度亏损；等待回调损失大量不回头机会。')
    decisions['H02'].update(research='POSITIVE_EXPLORATORY_EVIDENCE',execution='EXECUTION_FRAGILE',deployment='SHADOW_ONLY',reason='仅E10下C_MAX/C_10保留，净收益及同候选排名增量为正，成本与延迟压力仍正；区间跨零、2022/2023亏损、回撤34%-39%，不具生产证据。')
    best=ok.loc[ok.net_return.idxmax()];risk=ok[(ok.net_return>0)&(ok.maxdd>=-.2)].sort_values('cagr',ascending=False).iloc[0]
    verdict=dict(task_status='COMPLETED_WITH_CONDITIONAL_GATES',method_label='CHAMPION_INSPIRED_MECHANICAL_A_SHARE_PROXIES_NOT_REPLICATIONS',newly_executed=252,core_completed=216,data_conditional_completed=36,verified_reused=0,zero_signal_replayed=0,exact_duplicate_evidence=0,not_run_with_reason=44,invalidated_by_bug_final=0,routes=decisions,shadow_candidates=['A_H02_C_MAX_E10','A_H02_C_10_E10','A_D08_C_10_E10'],portfolio_policy='NO_GENERAL_PORTFOLIO_POLICY_PROMOTED',P3_concentrated_case='KEEP_RECORDED_STRESS_OBSERVATION_ONLY; not a deployable shared-capital policy',Q=dict(Q1='INSUFFICIENT_EVIDENCE_PERMISSION',Q2='INSUFFICIENT_EVIDENCE_PIT_FINANCIAL_VERSIONS',Q3='NO_INCREMENTAL_EDGE',Q4='NO_INCREMENTAL_EDGE',Q5='NO_INCREMENTAL_EDGE',Q6='INSUFFICIENT_EVIDENCE_PERMISSION'),I='BLOCKED_EXISTING_ACCOUNT_BASELINE',overall_research='LIMITED_COMPONENT_LEVEL_EXPLORATORY_EVIDENCE',overall_execution='EXECUTION_FRAGILE',overall_deployment='SHADOW_ONLY_NO_PRODUCTION_OR_ORDERS',best_return_case=best.id,best_risk_tradeoff_case=risk.id,best_incremental_case='A_H02_C_MAX_E10 vs A_D05_C_MAX_E10',future_sample_opened=False,production_modified=False,trade_orders_sent=False)
    dump(HERE/'VERDICT.json',verdict)
    cols=[('id','情景'),('net_return','累计净收益'),('cagr','年化'),('maxdd','最大回撤'),('mean_exposure','平均利用率'),('trades','已平仓笔数')]
    lines=['# USIC多冠军方法启发的A股V3研究结论\n',
'研究已结束：216个核心账户全部完成，六个条件模块中Q3/Q4/Q5通过资格检查并完成36个账户，总计252个完整现金账户。其余44个槽位依事前条件门保留阻塞原因，没有用配置、信号生成或测试代替回放。全部296个预登记槽位见文末；每个完整账户都覆盖2020—2023全部970个市场交易日。\n',
'**判断：不支持把十二条入口或四个组合政策整体投入生产。只保留H02的E10、C_MAX/C_10两种资金模式，以及D08的C_10/E10作为冻结影子研究组件。** H02的排名线索值得留档，但大回撤、后两年亏损和统计不确定性尚未消除。D08只适合低利用率组件的描述，不能声称解决全资金效率。关闭其他本轮确切机械定义的生产候选资格；这不是否定任何冠军本人。\n',
'## 1. 身份、来源、样本与复用边界\n',
f'12个入口是公开方法启发的机械代理。冠军组别、2020—2025年度成绩、2026中期性质以及逐项可读层级见[SOURCE_AUDIT.md]({HERE}/SOURCE_AUDIT.md)和[SOURCE_REGISTER.json]({HERE}/SOURCE_REGISTER.json)。短视频/音频元数据未被当作完整策略。所有数值公式来自本次V3冻结规范；既未复制冠军年度真实交易，也未验证其A股原生等价。\n',
'样本只使用CY-006的2018—2023六个授权日线分区，2018—2019暖机，2020—2023记账户；分钟仅QD-004的2020—2023四个年度分区。5262个历史证券身份均在轴表登记，5233个属于允许的普通沪深板块并逐股票扫描，其余29个明确属于不支持身份，未暗中缩小允许池。T−31需252个必要历史交易日，故次新/IPO不在结论范围。停牌按市场日历保留，历史ST/退市身份不以今日名单替换。\n',
'数据等级为PIT-B/研究代理，历史归档及修订谱系不支持PIT-A宣称。本轮2020—2023是已经消费过的构建/探索区间，不是独立OOS；没有读取CY-011或2024以后的封存市场样本。来源网页的2025比赛成绩不是新打开的A股验证集。\n',
'D00/D01/D02的信号、分数与限价分别精确继承V2 N1/N3/N4；旧简单TR20均值与新增Wilder ATR20初始化差异明确保留。V3现金模式、容量、COST2法定税处理不同，故旧账户收益没有计为本轮精确复用。V1/V2和五策略的工作树、源码、进程均未由本任务切换、修改或终止。\n',
'## 2. 账户完成与执行约束\n',
'| 状态 | 唯一槽位数 | 含义 |\n|---|---:|---|\n| 新运行完整完成 | 252 | 216核心＋36条件；均有全期NAV/订单/成交/持仓 |\n| 精确复用旧账户 | 0 | 只复用输入、信号和引擎代码证据 |\n| 零信号完整回放 | 0 | 无此类情景，不虚凑数量 |\n| 权限阻塞 | 24 | Q1与Q6各12 |\n| 数据资格不足 | 12 | Q2财务数据 |\n| 既有账户基线阻塞 | 8 | I0—I7 |\n| 最终bug失效/计划中/运行中 | 0 | 必要错误已修，所有启动槽位均已闭合 |\n',
'以上是唯一预登记情景数。公司行动补齐、断点恢复和11个代表情景复现产生的额外计算尝试不构成新假说；尝试记录见RUN_ATTEMPTS.json。252个已新运行账户对应250条不同经济路径：D02与Q5同覆盖BASE的两个单票退出分别相同，不被当作额外独立支持；精确复用槽位仍为0。SCENARIO_MANIFEST保留预登记状态，实际完成以scenario_summary与每账户result.json为准。\n',
f'初始现金100万元，无借款、无保证金、无负现金。全部252账户独立现金流、现金＋市值＋应收、已实现与未平仓损益、整数股数、T+1和单一物理证券检查通过。最低现金{ok.min_cash.min():.6f}元，最大现金流核对误差{audit["maximum_cash_error"]:.12f}元。累计成交计数跨情景会重复，不能当作独立交易样本量。\n',
'日线为DAILY_OPEN_MODEL：买入为真实原始开盘价加冻结滑点并受事前限价、历史涨跌停、合法股数与此前20日成交额中位数0.5%约束；不以日后低点补成交，不预支同次竞价卖款。分钟入场为MINUTE_OHLC_PROXY，14:25冻结股数，14:30—14:35首个满足条件窗口成交，另受分钟股数5%约束；上午真实卖出收入才可在下午使用。两者都没有证明盘口排队、真实冲击或竞价卖出深度。\n',
'佣金3bp、最低5元、双向滑点5bp为继承的研究假设，法定过户费与印花税按历史生效日。COST2只翻倍佣金/最低佣金/滑点。EST仅收盘确认后的下一合法开盘卖出；新买日盘中触及结构线不虚构同日止损，跌停/停牌退出意图持续。送转、应收分红、支付和股份上市日分别记账，未将复权价格收益再记一份现金。\n',
'## 3. 四种结果视角\n',
table(f[f.id.isin([best.id,risk.id,'A_H02_C_MAX_E10','A_H02_C_10_E10','A_D08_C_10_E10','D_H02_C_ONE_R_STAGE'])],cols),
'纯收益上界为P3/C_ONE/EST，累计292.62%、年化42.66%、最大回撤37.96%，平均利用率39.08%、91笔平仓。其2021年收益271.13%，2020及2023亏损；最大的五只股票已实现利润之和高于全期总利润。它必须保留在集中风险视角，不能因此把P3推广为通用组合政策：P3的C_MAX和C_10、两种退出均亏损，单票E10也亏损。\n',
'作为描述性风险切片，在最大回撤不超过20%的正收益案例中，D08/C_10/DELAY1年化最高；该20%只是本报告展示切片，不是新增交易阈值或已批准风险预算。原始D08/C_10/E10累计15.15%、回撤17.49%、平均利用率36.94%；COST2仍6.11%，DELAY1为41.64%。原始C_MAX却亏42.95%，C_ONE亏35.38%，因此只能保留机会稀疏组件。\n',
'净增量优先看H02相对D05：C_MAX/E10累计44.70%对6.80%，平均利用率82.20%对81.99%，改善不是主要靠增加现金。C_10/E10累计34.07%，最大回撤33.81%。但把H02换成EST，C_MAX亏56.19%、C_10亏60.15%；C_ONE虽然E10有142.70%，延迟压力亏61.32%，不能将集中高收益视为可实施最优解。\n',
'低回撤不等于资金工作得更好：H02/C_ONE/R_STAGE累计仅1.32%、平均利用率6.25%，最大回撤7.04%。与H02/C_MAX/E10的44.70%收益、82.20%利用率及39.08%回撤必须并列。分钟Q4增强臂也主要靠少交易、大量空仓减少亏损，所有资金/持有期组合仍为负收益。\n',
f'![核心72账户完整比较]({HERE}/charts/core_matrix.png)\n',f'![全部252个账户散点]({HERE}/charts/account_comparison.png)\n',
'## 4. 十二入口及退出判断\n',
'| 入口 | 普通中文定义 | 全池触发数 | 研究判断 | 处理 |\n|---|---|---:|---|---|']
    zh={'ALREADY_COVERED':'继承对照已覆盖','NO_INCREMENTAL_EDGE':'无可保留净增量','COMPONENT_ONLY':'仅组件证据','POSITIVE_EXPLORATORY_EVIDENCE':'有限正向探索证据','INSUFFICIENT_EVIDENCE':'证据不一致/不足'}
    for r,d in decisions.items():lines.append(f'| {r} | {d["name"]} | {counts[r]} | {zh[d["research"]]} | {d["reason"]} |')
    lines += ['\n完整72个基线结果及其压力、市场和风险对照全部在文末表中。E10用于入口比较，不表示推荐无结构止损实盘；EST也不是保证损失锁在S0以内。失败主要包括高开超限、低于支撑仍合法成交后的继续下跌、买日触及结构线但不能当天卖出、短期反复收复与止损、持有期/市场阶段错配。用更快退出不能普遍挽救负期望入口。\n',
f'实际成交后的1/3/5/10/20/40日价格诊断、首次不利收盘、MFE/MAE见[实际成交统计]({STATS}/actual_entry_summary.csv)。价格诊断是因果复权坐标上的报价表现，不是已经兑现的现金收益；现金账户PnL另行严格记账。尾盘共3102个实际成交时点对应的成交后分钟区间全部完整，未用买入前上午低点冒充买后MAE。\n',
'## 5. 增量、父事件与不确定性\n',
table(pair[pair.id.isin(['A_H02_C_MAX_E10','A_H02_C_10_E10','A_D08_C_10_E10','A_D04_C_MAX_E10','E_P3_CORROBORATE_C_ONE_EST'])],[('id','对照情景'),('baseline','简单基线'),('net_return_difference','净收益差'),('cagr_difference','年化差'),('bootstrap_cagr_diff_p025','20日块区间下端'),('bootstrap_cagr_diff_p975','区间上端')]),
'H02相对D05的C_MAX年化差约8.35个百分点，固定20日块、1000次、seed=20260908的95%探索区间约−7.57至24.81个百分点；C_10约−2.54至19.55个百分点。不能称为稳健统计确认。D05与H02同一候选在无资金选择的事件价格收益完全相同，收益差来自排序、容量和实际获得资金的顺序，不能伪装成新入场形态。\n',
'AVWAP匹配诊断只在D03锚存在且数据完整的13649个事件中比较：通过附加规则5583个、未通过8066个。通过组可执行报价的10日均值约−0.54%，未通过约−0.37%；没有证明锚重合提供额外优势。D04主账户与D03全账户结果仍全部展示，数据有无没有被当作alpha。\n',
'共7146个D09固定观察episode保留了提前触发、首次突破、无触发、失败和末端截断。D07/H01分别记录延续、首次回测、确认超时和结构失效；不存在“只有后来成功回调的父事件进入分母”。信号到买入、高开/低开与买后表现分开保存。\n',
f'同日去均值、板块/行业及此前30日涨幅、最大单日涨幅、波动、120日beta、20日流动性、PIT-B流通市值控制见[固定回归诊断]({HERE}/factor_incremental_diagnostic.csv)。该描述性回归没有训练新排名，缺少可执行报价或同日双侧支持的观察明确计数，不把同日共振当独立样本。账户配对表共228项，完整见[incremental_comparison.csv]({HERE}/incremental_comparison.csv)。\n',
'## 6. 市场适配、投入时序及四种组合政策\n',
'大盘唯一使用继承的全池等权因果市场序列及事前SMA状态。H02/C_MAX的G_DOWN把利用率从82.20%降到68.39%，累计收益从44.70%降到17.34%，回撤从39.08%降到33.41%；有收益代价。G_RAMP仅41.86%利用率且累计亏15.25%，未支持该固定爬坡规则。市场状态分组使用上一收盘已知状态；资金暴露回归仅作解释，不宣称预测能力。\n',
'R_STAGE并没有普遍增加投入：12个账户合计只有10次真正加仓。大多数差异来自初始风险预算减半、机会顺序与空闲资金；加仓毛价格贡献按实际lot另计，未跨公司行动的这些加仓无需假造分红归属。逐账户预算/未加仓原因、加仓尾部损益见stage_add_attribution.csv和order_status.csv。不将低利用率的低回撤视为同等风险收益改善。\n',
table(f[f.group=='E_CORE_PORTFOLIO'],cols),
'P0合池、P1按路线已投入资本平衡、P2固定市场阶段顺序、P3五日跨路线确认均只有一份现金、一只股票一个物理持仓。同股多标签不重复计算盈利。四政策没有在C_MAX/C_10建立正收益结果；P3单票EST的大幅收益保留为集中压力观察，不在本轮追加组合参数、动态权重或事后压力赛。\n',
'## 7. 六个数据模块与既有五策略\n',
'Q1和Q6：24个槽位权限阻塞。现有公告档案有其他策略的精确用途限制，本轮未打开受限标题；也没有完整的本用途首次公开与修订谱系。Q2：12个槽位数据资格不足，QD-011为DISCOVERY_ONLY、无可用地址和合格财务版本，不生成财报信号。未知不能当成没有催化。\n',
'Q3/Q4：48个月完整分钟输入通过53项资格检查，统一14:25信息集，无全天成交量筛样本或T收盘补确认。Q3两臂同候选、同冻结L；Q4两臂同分钟覆盖/同排名参考，仅旗形准入不同。Q5：历史行业、可见日期、剔除自身贡献和至少五成员通过PIT-B资格，必须用同一有行业分数的D02子样本配对。三个模块都在读取自身账户结果前启用。\n',
table(f[(f.group=='Q_DATA_CONDITIONAL')&(f.status=='COMPLETED_NEW')],cols),
'Q3尾盘臂在C_MAX/C_10部分少亏，但投入约减半。以共同T+11收盘时钟比较同时成交事件，平均价格收益差约−0.57至−0.82个百分点，未见更早进场的额外收益；C_ONE每种退出只有1个两臂共同成交事件，不能支持推断。Q3/C_ONE/EST尾盘正收益只有4笔平仓、4.16%利用率，不能列为有效候选。\n',
'Q4：旗形筛选把82300个上午冲击基础信号压缩为673个，降低了交易和暴露，仍未产生任何正净收益账户。Q5：行业重排在部分多票模式少亏，单票反而显著恶化，没有救活D02主线。三个条件模块的本轮确切定义均不升级。\n',
'既有五策略I0—I7未运行：权威共享资本P0为400万元、四个活动原生袖套（OGR/IFCGR为互斥替代）、保留分数股；资本缩放合同也明确分数股及股票容量未建模。未找到满足本轮100万元、合法整数申报、同股总容量的权威基线。把旧NAV比例相加或改写冻结基线不构成真实账户复现，因此保留8个条件阻塞；本轮未证明任一新组件对既有五策略有净增益。\n',
'## 8. 全年度、集中性、错误影响与边界\n',
'H02/C_MAX/E10按年为2020 +30.90%、2021 +50.65%、2022 −19.18%、2023 −9.21%；H02/C_10对应+20.56%、+32.89%、−11.21%、−5.75%。后两年没有删除。最佳股票/日期贡献和完整板块、市场状态结果均落盘；单独正收益不能替代组合资本占用的证明。\n',
f'完整[年度表]({STATS}/annual.csv)、[月度表]({STATS}/monthly.csv)、[股票/日期集中贡献]({STATS}/concentration.csv)、[行业及计划/市价风险]({STATS}/risk_and_industry.csv)、[容量核对]({STATS}/capacity_check.csv)是交付的一部分。全部成交聚合127859次，26741个去重成交价格/时点诊断仍不是26741个独立假说。\n',
'必要修正包括：无配股事件的NaN语义、缺前日RS候选、截止点依赖的到期字段、Industry与industry大小写映射，以及复现驱动的状态写入。前三项在账户读取前修正，Q5映射在其账户启动前修正，复现状态问题在第一次repeat前修正；最终没有遗留bug失效槽位。后台一次SIGTERM导致长批中断，按每情景检查点恢复，无损已完成产物。分析阶段的字符串适配、布尔计数和矩阵运算警告也已修正并重新生成诊断，不归为策略增量。\n',
'首轮172个完整、44个公司行动阻塞；随后分两轮补14份发行人实施公告的日期事实并重放。旧结果/日志保存在外部输出的core_before_official_backfill与before_final_action_backfill目录，两次旧快照中的172个及230个完整账户，分别与最终对应账户的六份产物逐字节相同；执行事实补齐只解除原阻塞账户，没有改动已完成路径。无法完成的半程结果没有参与收益统计。原输入known_at字段承载背景时间，完整事件的确认时点在canonical_signal_timeline中单列为T收盘；没有把T低点或触发提前到q可知。\n',
'限制仍包括历史PIT-B归档、日线开盘及分钟OHLC成交代理、真实队列和冲击成本未验证、构建样本已消费、缺独立未来验证、IPO/次新不覆盖，以及五策略增量条件门未通过。公司行动原文用于修复执行事实，不解除公告alpha权限。\n',
'## 9. 最终裁决与真实复现\n',
'保留：A_H02_C_MAX_E10、A_H02_C_10_E10、A_D08_C_10_E10，全部仅SHADOW_ONLY。冻结阈值不追加搜索，不改生产策略，不发送真实订单。P3_C_ONE_EST作为最高收益但高集中风险的已观察压力情景留档，不推荐为通用组合政策。无支持的确切规则关闭；Q1/Q2/Q6/I明确是证据缺口，不能误写为策略无效。\n',
f'17项单元/合成账户测试、41项前缀与继承一致性检查、53项分钟资格检查、252账户独立核对，以及8个核心＋3个分钟完整代表账户的66份重跑文件哈希一致均已真实完成。完整命令和执行日志见[REPRODUCTION.md]({HERE}/REPRODUCTION.md)。代码和小结果在本分支，重型输入与逐日明细位于{OUT}，哈希见DELIVERY_SEAL.json及各层manifest。\n',
'```text\nENVIRONMENT_VALID: YES\nREPO: /Users/linmei/Documents/CY-worktrees/usic-multichampion-ashare-v3-20260908\nBRANCH: research/usic-multichampion-ashare-v3\nBASE_HEAD / START_HEAD: c5e3ec548e93df15f4ef492d2aef2dcdd5063df1\nEND_HEAD: see external DELIVERY_STATUS.json, written after the final commit\nTASK_STATUS: COMPLETED_WITH_CONDITIONAL_GATES\nMETHOD_LABEL: CHAMPION_INSPIRED_MECHANICAL_A_SHARE_PROXIES_NOT_REPLICATIONS\nCHAMPIONS_RESULTS_VERIFIED_THROUGH: 2025_FINAL\nCURRENT_YEAR_STATUS: 2026_INTERIM_NOT_CHAMPIONS\nSAMPLE_PERMISSION_STATUS: AUTHORIZED_CONSUMED_CONSTRUCTION_PIT_B\nHISTORY_ACTUALLY_USED: daily 2018-2023; accounts/minutes 2020-2023\nNEW_SEALED_VALIDATION_OPENED: NO\nRUNNING_V1_V2_OR_FIVE_STRATEGIES_DISTURBED: NO\nFROZEN_PRODUCTION_STRATEGIES_MODIFIED: NO\nCORE_SLOTS: 216; COMPLETED: 216\nDATA_CONDITIONAL_SLOTS_MAX: 72; COMPLETED: 36\nFIVE_STRATEGY_INTEGRATION_SLOTS_MAX: 8; COMPLETED: 0\nNEWLY_EXECUTED / VERIFIED_REUSED / ZERO_SIGNAL_REPLAYED: 252 / 0 / 0\nEXACT_DUPLICATE_EVIDENCE / NOT_RUN_WITH_REASON / INVALIDATED_BY_BUG: 0 / 44 / 0\nLEGACY_EVIDENCE_REUSED_SEPARATELY: V2 inputs, producer signals, cash/entitlement engine; no old account counted\nTEMPORAL_LEAKAGE_CHECK: PASS_PROGRAM_PREFIX; HISTORICAL_ARCHIVE_PIT_A_NOT_ESTABLISHED\nCASH_AND_LOT_ACCOUNTING_CHECK: 252/252 PASS\nEXECUTION_EVIDENCE_GRADE: DAILY_OPEN_MODEL / MINUTE_OHLC_PROXY\nQ1_TO_Q6_GATES: permission / data / pass / pass / pass / permission\nI_GATE: BLOCKED_EXISTING_ACCOUNT_BASELINE\nRESEARCH_VERDICT: LIMITED_COMPONENT_LEVEL_EXPLORATORY_EVIDENCE\nEXECUTION_VERDICT: EXECUTION_FRAGILE\nDEPLOYMENT_VERDICT: SHADOW_ONLY; NO_PRODUCTION; NO_REAL_ORDERS\nBEST_RETURN_CASE: E_P3_CORROBORATE_C_ONE_EST\nBEST_RISK_TRADEOFF_CASE: B_D08_C_10_DELAY1 (descriptive <=20% MaxDD slice)\nBEST_INCREMENTAL_CASE: A_H02_C_MAX_E10 vs A_D05_C_MAX_E10\nCOMMIT / PUSH: final verified values in external DELIVERY_STATUS.json and final task reply\n```\n',
f'最终Git交付凭证：[DELIVERY_STATUS.json]({OUT}/DELIVERY_STATUS.json)。该凭证在提交/普通push之后写入，避免报告正文试图包含自身最终Git哈希的自引用。\n',
'## 附录：全部296个预登记情景结果与状态\n',
'所有收益已含账户真实费用与税费，年化按252交易日计算。已平仓笔数不含期末持仓；结束持仓按可信价格记净值，不为补足持有期打开2024。阻塞行的收益为空，不填0。更多列（波动、胜率、盈亏比、换手、费用、回撤持续、集中度、最低现金、敞口等）见scenario_summary.csv。\n',
table(f,cols+[('status','实际状态')])]
    (HERE/'REPORT.md').write_text('\n'.join(lines))
    print('REPORT_COMPLETE',len(f),len(ok),flush=True)
if __name__=='__main__':main()
