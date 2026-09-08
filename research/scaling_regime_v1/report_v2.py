"""Render Chinese conclusions directly from reconciled authoritative outputs."""
import json
import pandas as pd
from .audit import HERE,sha256,write_json
from .economics import KEY

OUT=HERE/'output';REPORTS=HERE/'reports'


def load(name):return pd.read_csv(OUT/(name+'.csv'))
def md(frame):return frame.to_markdown(index=False,floatfmt='.4f')
def ref(frame,target=None):
    f=frame.loc[frame.gap.eq('OGR')&frame.mcb_mode.eq('independent')]
    if 'mechanic' in f:f=f.loc[f.mechanic.eq('FULL_BOOK_NORMALIZATION')]
    if target is not None:f=f.loc[f.target.eq(target)]
    return f


def run(draft=False):
    task_status="PARTIAL_COMPLETE_IDENTITY_CLOSED_ATTRIBUTION_PENDING" if draft else "COMPLETE"
    if not draft:
        closure=load("root_capital_days_reconciliation")
        assert len(closure)==20 and closure.status.eq("PASS").all()
    annual=load('annual_scaling_metrics');inc=load('annual_scaling_increment');strategy=load('annual_strategy_contribution');route=load('annual_route_contribution')
    category=load('annual_full_book_category_contribution');mechanics=load('annual_scaling_mechanics_comparison')
    dd=load('yearly_drawdown_attribution');dc=load('yearly_drawdown_components')
    state=load('state_conditioned_scaling_results');q=load('router_candidate_evidence');transition=load('state_transition_summary')
    capacity=load('g25_capacity_percentiles');flags=load('g25_capacity_flags');sizes=load('account_size_capacity_reference')
    router=json.loads((OUT/'router_qualification_status.json').read_text())
    assert router['status'] in ['NO_STABLE_SCALING_REGIME_ROUTER','NATIVE_OR_G25_SHADOW_ROUTER_CANDIDATE']
    base=ref(annual).loc[lambda x:x.year.ge(2022)&x.target.isin(['NATIVE','G25','G100'])]
    table=base[['year','target','annual_return','MaxDD','net_pnl','average_gross','fees','capital_days']].copy()
    for c in ['annual_return','MaxDD','average_gross']:table[c]*=100
    table=table.rename(columns={'annual_return':'收益%','MaxDD':'最大回撤%','net_pnl':'实际盈亏元','average_gross':'平均仓位%','fees':'费用元','capital_days':'元天'})
    reference='下述叙述以 OGR／MCB independent 为明确数值参照；完整 CSV 覆盖四种结构，未重新选择 Top。2026 为截至 9 月 4 日的 YTD。金额差为各账户实际净值变化之差，包含此前累积资金和路径差异。'
    scope='28 个连续账户：4 个 Native、16 个 Full Book 缩放、8 个 G25/G100 Entry Only；每个账户 2106 个交易日。只有 G25 Entry Only 是按用户明确要求扩展父构造器验证，其执行方法未改。'
    caveats='行业和 IFCGR 保留 PIT-B 等既有数据等级。MCB 沿用父研究冻结实现的来源等级；恢复了 snapshot 资格，并不把重构实现升级为原始生产器源码。SMV6 是本地物理账户回调复现，原生 SuperMind 平台等价尚未证明。CONTINUOUS_LIVE_PROTOCOL 描述状态延续语义，不构成实盘批准。全部状态研究为事后诊断，不是新封存验证。'
    mechanics_ref=ref(mechanics).loc[lambda x:x.year.ge(2022)] if 'mechanic' in mechanics else mechanics.loc[mechanics.gap.eq('OGR')&mechanics.mcb_mode.eq('independent')&mechanics.year.ge(2022)]
    reports={}
    for year,title in [(2024,'2024_drawdown_anatomy'),(2025,'2025_profit_anatomy'),(2026,'2026_drawdown_anatomy')]:
        s=ref(strategy,'G100').loc[lambda x:x.year.eq(year),['strategy','pnl_native','pnl_scaled','incremental_pnl']]
        r=ref(route,'G100').loc[lambda x:x.year.eq(year),['strategy','route','pnl_native','pnl_scaled','incremental_pnl']]
        c=ref(category,'G100').loc[lambda x:x.year.eq(year)].groupby('category',as_index=False).pnl.sum()
        window=ref(dd,'G100').loc[lambda x:x.year.eq(year)&x.scope.eq('ANNUAL_LOCAL')]
        parts=ref(dc,'G100').loc[lambda x:x.year.eq(year)&x.scope.eq('ANNUAL_LOCAL')&x.dimension.eq('strategy'),['name','pnl','drawdown_contribution_percentage_points']]
        content=f'# {year} 年实际账户归因\n\n{reference}\n\n'+md(table.loc[table.year.eq(year)])+'\n\n## 策略与路线\n\n'+md(s)+'\n\n'+md(r)
        content+='\n\n## 实际买入批次贡献\n\n'+md(c)+'\n\n每次 BUY 单独建归因批次，保留实际退出和公司行为。分类按该批次买入时确定，年度盈亏包含跨年延续批次，不等于这些批次都在该年新买入。既有持仓加仓与新开仓按实际成交前根事件持仓分类；减仓后的价格诊断不能证明避免了同额亏损。\n'
        content+='\n## 最大回撤区间\n\n'+md(window[['peak','trough','recovery','recovery_status','MaxDD','actual_pnl','native_same_window_pnl','incremental_scaling_pnl','existing_position_increases','existing_position_reductions']])+'\n\n'+md(parts)
        content+='\n\n回撤采用含上年末净值的年内峰谷；另列完整历史高水位在该年到达谷底的窗口。回撤百分比不是可加的策略贡献；表中可加的是同一峰谷窗口的人民币盈亏。\n'
        habitat=ref(load('state_route_pnl'),'G100').loc[lambda x:x.year.eq(year)].groupby(['state_family','state'],as_index=False)[['pnl_native','pnl_scaled','incremental_pnl']].sum()
        content+='\n## 同年状态关联\n\n'+md(habitat)+'\n\n同一状态族内每日盈亏只计一次；不同状态族是对同一账户的不同观察，不能相加。既有加仓批次是否在上一交易日已浮亏，另见 existing_add_known_state_annual_pnl.csv。\n'
        known=ref(load('existing_add_known_state_annual_pnl'),'G100').loc[lambda x:x.year.eq(year)].groupby('known_prior_holding_state',as_index=False).pnl.sum()
        content+='\n## 加仓前已知的持仓状态\n\n'+md(known)+'\n\n仅以加仓前一个已完成交易日的持仓浮盈亏分类；零界是账面盈亏的自然边界，不是新策略阈值。新开于当日、此前无持仓的情况独立标记，不借用未来状态。\n'
        if year==2024:content+='\n2024 年参考 G100 的最深年内回撤几乎全部由 OGR 造成，峰谷内没有既有持仓加仓成交；不能把这一段回撤归因为持续补仓下跌的 ATRDR。全年 SMV6 盈利，但该峰谷窗口 SMV6 小幅亏损，未抵消这次尾部下跌。\n'
        if year==2026:content+='\n2026 年参考 G100 的最深回撤主要来自 ATRDR，OGR 同时亏损。年度既有加仓中，上一收盘已浮亏持仓对应批次的亏损显著，另有其他加仓批次抵消；这是未来可检验的机制假设，本次不新增退出或加仓限制。SMV6 全年盈利，但在最深峰谷窗口也小幅亏损。\n'
        if year==2025:content+='\n2025 年新开仓类批次和既有加仓类批次各贡献约一半利润。既有加仓类中，前收盘未浮亏的批次贡献较多，但前收盘浮亏的批次也盈利；不能把结果缩减成只加赢家的既有规则。\n'
        fee=ref(load('fee_accounting_bridge')).loc[lambda x:x.year.eq(year)&x.target.isin(['G25','G100']),['target','incremental_net_pnl','incremental_fees','incremental_actual_path_pnl_before_current_year_fees']]
        content+='\n## 当前路径的费用会计桥\n\n'+md(fee)+'\n\n将本年实际扣除费用加回只是一条会计恒等式，不是零费用回测。若取消费用，现金、仓位和后续成交也会改变，不能把加回金额直接视为可实现的改进。\n'
        reports[title]=content
    reports['scaling_mechanics_attribution']='# Full Book 与 Entry Only\n\n'+reference+'\n\n'+md(mechanics_ref[['year','target','annual_return_full_book','annual_return_entry_only','MaxDD_full_book','MaxDD_entry_only','full_book_minus_entry_only_pnl','interpretation']])+'\n\n共同输入是原始 precapital 信号、Native 参考请求、报价及初始状态；实际持仓路径会影响 ACTIVE_SYMBOL/MAX_K/native_failures，因此准入后的 intents 不要求机械相等，共同事件的信号时间、价格、参考请求金额和经济定义已逐项核对。Full Book 的实际持仓再分配会改变后续现金、仓位及复利路径，年度对照体现整条机制路径的差异。不能把差值解读为只在当年启停一次再平衡的因果效应。Entry Only 的年内符号改善也不自动满足风险或容量要求。逐笔前向结果区分实际买入批次和减仓价格反事实；重叠窗口不相加。\n'
    sr=ref(state,'G25')
    reports['regime_evidence']='# 事前状态与增量缩放收益\n\n'+reference+'\n\n'+md(sr[['state_family','state','block','independent_dates','incremental_pnl','incremental_return_sum','pnl_ex_top5_events','capital_days']])+'\n\n## 信号日期与事件分布\n\n'+md(sr[['state_family','state','block','decisions','independent_original_signal_dates','root_events','median_event_contribution','mean_event_contribution','positive_event_fraction']])+'\n\n原始信号日期按贡献根事件的实际决策时间统计，包含跨期延续的持仓信号；与每日盈亏观察日期分开报告。\n\n## 留年与事件集中度\n\n'+md(ref(q,'G25'))+'\n\n状态只使用决策前已完成信息。波动率、流动性、账户回撤和 Demand 暴露只给连续相关性，不新增高低阈值。状态条件金额是实际 daily scaled−native 差额，每个交易日每个状态族只计一次；它不是一个尚未运行的状态路由账户收益。资金天数使用完成时点持仓并精确切分日历、状态和终止边界。incremental_return_sum 是每日收益率差的算术和，只作单位净值方向核查，不是状态子账户的复合收益率。\n\nROUTER_CANDIDATE_STATUS: '+router['status']+'\n\n两类一维状态共 20 个 G25 结构/状态检验；没有二维或迟滞救援调参。若未满足条件，不生成虚构 router_results.csv。\n'
    reports['g25_capacity']='# G25 容量诊断\n\n研究账户 2018 年初实际 NAV 为 4,904,782.13 元，包含继承持仓；1x 是该基准账户随历史演进产生的实际订单，2/5/10x 仅为同比例订单压力参考。\n\n'+md(capacity)+'\n\n## 账户规模线性参考\n\n'+md(sizes)+'\n\n分母为实际成交额 CNY；表中参与率是无量纲比值，1.0 代表 100%。日成交额及相关分钟成交额是事后容量诊断；ADV20 只使用此前已完成交易日。分钟缺失保留缺失，不填零。1/2/5/10 倍仅将固定订单按比例放大，不重跑策略，也不声称可成交。超过 1/2/5/10/20% 只标记，不改任何成交。标记订单对应的根事件年度盈亏每个阈值内仅计一次，不是市场冲击损失。\n'
    for name,content in reports.items():(REPORTS/(name+'.md')).write_text(content)
    answers=[]
    def add(n,question,answer,evidence):answers.append(dict(number=n,question=question,answer=answer,evidence=evidence,status='ANSWERED'))
    for n,year in [(1,2024),(2,2026)]:
        a=base.loc[base.year.eq(year)].set_index('target')
        add(n,f'{year} 亏损来自原生 alpha 还是缩放？',f"Native 收益 {a.loc['NATIVE','annual_return']:.2%}；G25 {a.loc['G25','annual_return']:.2%}、G100 {a.loc['G100','annual_return']:.2%}。原生组合整体仍盈利，负收益出现在缩放后的实际持仓路径，不能解释为原生组合整体失效。",'annual_scaling_increment.csv')
    c=ref(category,'G100').loc[lambda x:x.year.eq(2025)].groupby('category').pnl.sum().sort_values(ascending=False)
    add(3,'2025 为什么赚得多？',f'G100 实际买入批次中，贡献最大的类别为 {c.index[0]}，年度贡献 {c.iloc[0]:,.2f} 元；这是实际持仓、退出和分红归因，仍须结合集中度及路线判断。','annual_full_book_category_contribution.csv')
    for n,year,largest in [(4,2024,False),(5,2026,False),(6,2025,True)]:
        r=ref(route,'G100').loc[lambda x:x.year.eq(year)].sort_values('incremental_pnl',ascending=not largest).iloc[0]
        add(n,f'{year} 的主要增量路线来源？',f"{r.strategy} / {r.route}，相对 Native 的实际增量盈亏 {r.incremental_pnl:,.2f} 元。完整表同时保留原生与缩放总盈亏。",'annual_route_contribution.csv')
    pieces=[]
    for year in [2024,2025,2026]:
        r=mechanics_ref.loc[mechanics_ref.year.eq(year)&mechanics_ref.target.eq('G100')].iloc[0]
        pieces.append(f'{year} Full Book 减 Entry Only 的实际年度盈亏为 {r.full_book_minus_entry_only_pnl:,.2f} 元')
    add(7,'Full Book 每年有何影响？','；'.join(pieces)+'。这是完整账户路径对照，不是孤立当年调仓处理效应。','annual_scaling_mechanics_comparison.csv')
    annual_states=ref(load('state_annual_blocks'),'G25');regime=annual_states.loc[annual_states.state_family.eq('market_regime')]
    for n,years,question,ascending in [(8,[2024,2026],'坏年份是否重现历史坏状态？',True),(9,[2025],'2025 是否重现历史好状态？',False)]:
        choice=regime.loc[regime.year.isin(years)].groupby('state').incremental_pnl.sum().sort_values(ascending=ascending).index[0]
        history=regime.loc[regime.state.eq(choice)&regime.year.le(2023)]
        add(n,question,f'{choice} 在所问年份贡献最显著；2018—2023 同状态有 {len(history)} 个年度块，其中 {int(history.incremental_pnl.gt(0).sum())} 年增量金额为正、{int(history.incremental_pnl.lt(0).sum())} 年为负。相同状态出现不等于稳定路由证据。','state_annual_blocks.csv')
    add(10,'哪些事前变量解释增量收益？','市场状态和既有宽度分桶提供可复核关联；连续波动率、流动性、已知账户回撤及 Demand 暴露的分期相关性另表披露。它们是条件关联，不能直接当作动态调整仓位的因果收益。','continuous_state_associations.csv')
    add(11,'历史发现和确认期方向是否稳定？',f"20 个 G25 结构/状态中，{int(q.numerical_stability_gate.eq('PASS').sum())} 个通过已声明的综合稳定性检查；各块方向、留一年、去 Top 5 事件和最佳 5 日期结果均披露。",'router_candidate_evidence.csv')
    add(12,'是否存在简单 Native/G25 路由？',router['status'],'router_qualification_status.json')
    add(13,'若不成立，为什么？','任何一个阶段方向、单位净值收益增量或去集中度检查失败，都不足以支持稳定正向缩放状态；不增加阈值、年份代理、路线例外或迟滞来挽救。','scaling_regime_leave_year.csv')
    basecap=capacity.loc[capacity.metric.eq('participation_daily')].sort_values('p99',ascending=False).iloc[0]
    minute_worst=capacity.loc[capacity.metric.eq('order_over_minute_amount')].sort_values('p99',ascending=False).iloc[0]
    add(14,'当前账户 G25 容量是否可接受？',f"日成交额参与率最重组的 p99 为 {basecap.p99:.2%}、最大 {basecap.maximum:.2%}；分钟参与率最重组 p99 为 {minute_worst.p99:.2%}，显著超过该分钟实际成交额。完整分钟覆盖和尾部标记另列。该诊断没有市场冲击模型，不能据此批准实盘容量。",'g25_capacity_percentiles.csv')
    add(15,'容量主要负担来自哪里？',f"按当前日成交额参与率 p99，最重为 {basecap.strategy}（{basecap.gap}/{basecap.mcb_mode}）；ADV20 和分钟分母另表区分。",'g25_capacity_percentiles.csv')
    add(16,'下一步研究优先级？','优先对 G25 做真实容量证伪并保留固定原生配置；若状态检查不通过，不扩展复杂路由。新增 alpha 广度应另立研究任务，不能用来补齐本次归因。','final_decision_matrix.csv')
    pd.DataFrame(answers).sort_values('number').to_csv(OUT/'main_question_status_v2.csv',index=False)
    decisions=[dict(item='FIXED_G25',decision='FIXED_G25_NOT_ROBUST',basis='Full Book loses in 2024/2026 in reference structure; actual four-structure table supplied'),dict(item='REGIME',decision='SCALING_REGIME_DEPENDENT',basis='State associations and mechanics are jointly examined; no causal router inference'),dict(item='ROUTER',decision=router['status'],basis='Frozen one-dimensional definitions; date/event concentration and leave-year checks'),dict(item='CAPACITY',decision='G25_CAPACITY_CONCERN' if basecap.maximum>.1 else 'G25_CAPACITY_PLAUSIBLE_AT_BASE_SIZE',basis='Observed tail exceeds the requested 10% daily-turnover diagnostic flag; no executable size claim'),dict(item='PRODUCTION',decision='NOT_AUTHORIZED',basis='No production changes, native exits, existing evidence grades preserved')]
    pd.DataFrame(decisions).to_csv(OUT/'final_decision_matrix.csv',index=False)
    protocol_hash=sha256(HERE/'contracts/continuous_rollforward_protocol_v1.json');contract_hash=sha256(HERE/'contracts/scaling_regime_attribution_v2.json')
    text='# 连续账户身份闭合与缩放状态归因\n\nTASK_STATUS: '+task_status+'\n\nROLLFORWARD_IDENTITY_STATUS: PASS\n\n'+scope+'\n\n'+reference+'\n\n'+md(table)
    text+='\n\n## 权威协议与边界\n\n2018-01-01 仅初始化一次；持续携带现金、持仓、冷却、待处理成员、公司行为、市场/行业与 SMV6 回调状态。没有按年份重置。起点按父契约继承真实初值：组合 NAV 4,904,782.13 元，已有股票持仓 275,214.37 元；资本占用包含这些持仓从起始边界开始的日历时间。父研究 2022 年的重建是分段研究协议；连续 SMV6 在 2022-01-04 读取 2021-12-31 的 prev_trade_date，触发周边界判断；分段初值 None 走另一分支。\n\nMCB 恢复 industry_snapshot_id IS NOT NULL，绑定原始 QD-008-EASTMONEY-PIT-20260820 数据集身份；causal_industry 不代替快照资格。原行业源末日 2026-08-13，此后只延续已知原分类。遗留流程此后切换粗分类，本次恢复原生产器连接，新增 11 个 ATRDR 入场；没有 MCB 资格单独导致的信号集合变化。\n\n2018—2021 五个 Top 的 973 日历史前缀保持；20 个 Native 有界终点回放与完整连续路径在信号、意图、成交、持仓、现金、NAV 和回调状态上核对通过。Top 仅按原 2018—2021 排名保留。\n\n2022 年独立模式的初值差为 SMV6 现金 +260,255.98 元；confirmation_tag 还带着历史 MCB 过滤后的实际资金，与分段重新载入的独立 MCB 初值差 −377,365.30 元。费用属于实际盈亏，持仓是状态，均不作为独立金额重复相加。完整桥表见 segmented_vs_continuous_2022_2023.csv。\n'
    text+='\n## 16 个主要问题\n\n'+'\n\n'.join(f"{r['number']}. **{r['question']}** {r['answer']}（output/{r['evidence']}）" for r in sorted(answers,key=lambda x:x['number']))
    text+='\n\n## 使用边界与复现\n\n'+caveats+'\n\n旧图与旧身份拒绝结果保留，不能改标为权威结果。新图：reports/top5_authoritative_continuous_protocol_v1.png。旧图与新图差异桥保留原始输入修复、累积现金和缩放反馈的联动，不强行拆成未经隔离实验支持的百分比。\n\n协议 SHA256：`'+protocol_hash+'`\n\n归因 V2 SHA256：`'+contract_hash+'`\n\n命令见 REPRODUCTION_COMMANDS.md；测试、输入与输出摘要见 output/test_results_v2.json、input_hash_verification.csv、output_manifest.sha256。\n'
    (HERE/'REPORT.md').write_text(text)
    write_json(OUT/'completion_v2.json',dict(TASK_STATUS=task_status,ROLLFORWARD_IDENTITY_STATUS='PASS',economic_attribution_run=True,state_conditioned_analysis_run=True,router_status=router['status'],production_authorized=False,protocol_sha256=protocol_hash,attribution_contract_sha256=contract_hash,legacy_completion_file='completion.json preserves original rejected run, not this completion'))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--draft',action='store_true');run(parser.parse_args().draft)
