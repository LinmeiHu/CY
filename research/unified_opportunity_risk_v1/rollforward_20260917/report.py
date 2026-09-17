"""Separate response-curve evidence; never optimize or promote the diagnostic."""
import json
import pandas as pd
from .run import OUT,XS,YS,END
from .prepare_stock import HERE
from research.unified_opportunity_risk_v1.exposure_scale.run import label

def table(frame,cols,formats=None):
    d=frame[cols].copy()
    for c,fmt in (formats or {}).items():d[c]=d[c].map(fmt)
    return d.to_markdown(index=False)

def diagnostic_answers(f,baseline,c):
    finite=baseline.loc[[label(x) for x in XS if x!='MAX_FILL']].copy()
    steps=finite[['CAGR','MaxDD','CVaR5','average_gross']].diff()
    steps.columns=['CAGR增量','MaxDD增量','CVaR5增量','平均仓位增量']
    cash=c[c.Y.eq(.1)&c.period.eq('full')&c.X.eq('X1')].set_index('reason')
    first=finite.index[finite.CAGR.diff().le(0)]
    stopping=('在本次离散网格中，首次出现相邻X提高但CAGR不再提高的是 '+str(first[0])+'；这只是响应曲线观测，不是最优参数选择。') if len(first) else '本次有限X网格中，尚未出现相邻X提高而CAGR下降；不能据此推断网格外仍会提高。'
    maxfill=f[f.X.eq('MAX_FILL')].sort_values('Y')
    lines=['## 对六个问题的直接回答',
        '**1. 平均仓位随X提高有多快？** Y=10%时：'+ '；'.join(f'{x}：{v.average_gross:.2%}' for x,v in baseline.iterrows())+'。这是真实连续账户平均仓位，不是目标仓位。',
        '**2. 从哪个X开始追加资金不再提高CAGR？** Y=10%时，'+stopping+' Y=15%、20%、30%的有限X网格内仍上升至X10，但增益已很小；所有Y切到MAX_FILL后CAGR都下降。',
        '**3. MaxDD／CVaR何时加速？** 没有共同、持续的加速拐点。Y=10%时，MaxDD每增加1单位X的增量从X3→5约0.576个百分点，回升到X5→8约0.732个百分点；但CVaR5每单位X增幅继续递减，不能称为同步加速。实际值得注意的是X5以后新增收益趋缓，而风险仍增加：X5→8 CAGR仅增加0.53个百分点，MaxDD增加2.20个百分点；X8→10 CAGR下降0.29个百分点，MaxDD再增加1.37个百分点。下表列出原始增量，避免拟合精确风险阈值。',
        steps.dropna().map(lambda v:f'{100*v:+.3f}个百分点').reset_index().to_markdown(index=False),
        '**4. 低利用率主要因为缺机会还是风险预算？** 在X1、Y=10%的原瀑布口径中，无合格机会占平均NAV的 '+f"{cash.loc['NO_QUALIFYING_OPPORTUNITY','average_cash_NAV_share']:.2%}"+'，单票上限占 '+f"{cash.loc['SINGLE_SECURITY_CAP','average_cash_NAV_share']:.2%}"+'，目标大小／软风险预算占 '+f"{cash.loc['SOFT_RISK_BUDGET','average_cash_NAV_share']:.2%}"+'。因此不能将闲置全部归因于RP总预算，也不能将“有合格机会”理解为“有足够多可分散部署的机会”。',
        '**5. 五个现有策略能否不降低质量就用掉大部分账户？** 如果“大部分”只指超过一半，放宽Y的MAX_FILL可以做到；如果指长期75%—90%或接近满仓，这组证据不支持。Y=10%的极端上界平均仓位48.50%，即使Y=30%也只有57.12%；后者超过90%仓位仅614/2114天（29.04%）。质量门槛未降，但提高集中度明显恶化收益与回撤，不能据此视为实用方案。',
        '**6. MAX_FILL极端上界是什么样？** 下表是原机会和原退出下的真实账户极端请求结果，未使用软风险或家族风险预算。',
        table(maxfill,['Y','CAGR','MaxDD','CVaR5','average_gross','P95_gross','max_gross','days_gross_gt75','days_gross_ge99'],{k:lambda v:f'{v:.2%}' for k in ['Y','CAGR','MaxDD','CVaR5','average_gross','P95_gross','max_gross']})]
    return lines

def main():
    f=pd.read_csv(OUT/'candidate_b_xy_full_metrics.csv');a=pd.read_csv(OUT/'candidate_b_xy_yearly_metrics.csv');r=pd.read_csv(OUT/'history_revision_and_new_period.csv')
    c=pd.read_csv(OUT/'candidate_b_unused_cash_attribution.csv');p=pd.read_csv(OUT/'candidate_b_exposure_scale_metrics.csv')
    baseline=f[f.Y.eq(.1)].set_index('X').reindex([label(x) for x in XS]);pct=lambda v:f'{v:.2%}'
    lines=[f'# Candidate B：32组 X × Y 更新至 {END}',
        '本次是冻结 Candidate B 的曝光响应曲线诊断。全部账户从 2018 年连续重跑；不挑选最优 X，不修改 KEEP_NATIVE。',
        '数据采集时为 2026-09-17 盘中，统一使用最近完整交易日 2026-09-16。每个账户延续实际现金、持仓与原生状态；年度指标是连续账户切片，未按年重置本金。',
        '## 32组全期结果',
        '表格每格为 **CAGR / 最大回撤**。Y 是新增／增加请求的单只证券硬上限；原生持仓被动价格漂移继续沿用冻结规则。']
    matrix=[]
    for x in XS:
        tag=label(x);row={'X':tag}
        for y in YS:
            v=f[f.X.eq(tag)&f.Y.eq(y)].iloc[0];row[f'Y={y:.0%}']=f'{v.CAGR:.2%} / {v.MaxDD:.2%}'
        matrix.append(row)
    lines += [pd.DataFrame(matrix).to_markdown(index=False),'## 全期净值与市场指数','![32组净值](output/candidate_b_xy_nav.png)',
        '每个 Y 面板叠加全部 8 个 X；左轴账户净值，右轴上证指数、深证成指（2018首日收盘归一为100）。左右轴独立，不能比较屏幕高度。指数只用于展示。',
        '## 近期放大','![近期净值](output/candidate_b_xy_nav_recent.png)','## 全期回撤','![回撤](output/candidate_b_xy_drawdown.png)',
        '## 仓位响应','![仓位](output/candidate_b_xy_gross.png)',
        'Y=10% 的响应曲线：',table(baseline.reset_index(),['X','CAGR','MaxDD','CVaR5','Sharpe','average_gross','P95_gross','max_gross','cash_ratio','days_gross_gt25','days_gross_gt50','days_gross_gt75','days_gross_gt90','days_gross_ge99'],{k:pct for k in ['CAGR','MaxDD','CVaR5','average_gross','P95_gross','max_gross','cash_ratio']}),
        '## 历史重算和新增交易日分开解释',
        '按用户确认，采用最新 ETF 前复权数据从 2018 年完整重跑。8只 ETF 新增分红／拆分引起历史前复权价格变化；其余策略、参数、校准、信号时点与原生退出规则未改。历史分钟行情采用已登记原始分钟记录，用新发生的实际分红／拆分事实更新复权列，并与新 QMT 可取重叠区间核对；未伪造早期原始分钟行情。股票维持原算法的原始价格与 QD010 因果坐标，9月4日以前输入逐行保持一致。',
        f'重算旧区间（截至9月4日）的 CAGR 变化范围为 {r.CAGR_revision_pp.min():+.4f} 至 {r.CAGR_revision_pp.max():+.4f} 个百分点，最大回撤变化范围为 {r.MaxDD_revision_pp.min():+.4f} 至 {r.MaxDD_revision_pp.max():+.4f} 个百分点。这部分不能解释为9月新赚取的收益。',
        '9月7日至16日是8个新增交易日，单列实际区间收益，避免将短区间年化当作策略表现。公告沿用PIT-B当前历史快照与保守可用时间，不声称拥有严格归档PIT-A证据。',
        table(r,['X','Y','CAGR_revision_pp','MaxDD_revision_pp','new_period_return','new_period_MaxDD'],{'Y':pct,'new_period_return':pct,'new_period_MaxDD':pct}),
        '## 每年最大回撤',
        '2026为截至9月16日的YTD；所有年份以年初权益作为回撤起点，不将跨年高水位带入年度最大回撤。全期最大回撤另外保留跨年高水位。']
    for x in XS:
        tag=label(x);v=a[a.X.eq(tag)].pivot(index='year',columns='Y',values='MaxDD').reindex(columns=YS)
        v.columns=[f'Y={y:.0%}' for y in YS]
        lines += [f'### {tag}',v.map(pct).reset_index().to_markdown(index=False)]
    lines += ['## 闲置现金归因',
        '沿用原有同一时点、只读的约束放松瀑布，并追踪至每日收盘。各分类金额合计等于实际闲置现金；属于顺序相关的有符号归因，不是 Shapley 因果分解。SOFT_RISK_BUDGET 包含有限X目标大小及软风险约束的限制；不得把它解释为只有组合总风险预算一个因素。',
        'MAX_FILL 不使用软风险／家族风险预算，这两列必须为零。GROSS_CAP、CASH_EXHAUSTED 对剩余现金的金额归因可能为零；零不表示回测取消了这些硬约束。',
        table(c[c.Y.eq(.1)&c.period.eq('full')],['X','reason','average_cash_NAV_share','share_of_unused_cash_NAV_days'],{'average_cash_NAV_share':pct,'share_of_unused_cash_NAV_days':pct}),
        '## 数据和账户验证',
        '- 冻结股票人口3,725只；新增区间日期快照中的3,712只逐日核对。QMT与另一已保存来源比较2,511只、20,061个股票日记录，价格及量额一致性门槛通过。停牌缺失报价保留NULL且不可交易。股票报价按分规范化，消除API二进制浮点尾差导致的零宽假缺口。',
        '- 90条新增公司行动事实来自原登记的巨潮接口；原有记录保留。全部未解释参考价跳变清零。中国平安0.98元分红另与发行人实施公告核对，按原生登记日权益与支付日计入现金。',
        '- 新增两个日线缺口候选均补齐120天、每日241条的一分钟历史；一个通过原门槛。新中际旭创请求通过官方120天公告窗口的冻结IFCGR分类，退出按Native规则持续跟踪，截至数据终点仍持有。',
        '- QMT取不到独立换手率字段，采用原登记的数据构建器既有缺失换手率分支，不推算流通股本。ST历史状态不能确认的行按原质量门槛排除；没有降低门槛。',
        '- 逐账户验证现金非负、总敞口不超NAV、PnL守恒、新增证券上限、同证券合并、登记流动性限制、正质量门槛和实际持仓公司行动。',
        '- 容量表提供登记执行限额使用率及请求/成交数量；未拟合额外冲击模型，不声称任意大本金都能复制收益。',
        '发行人分红依据：[中国平安2026年半年度权益分派实施公告](https://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2026/2026-9/2026-09-03/12580396.PDF)。',
        '## 可复核文件',
        '- `output/candidate_b_xy_full_metrics.csv`：32组全期指标。',
        '- `output/candidate_b_xy_yearly_metrics.csv`：288组年度指标，含实际收益与年化指标。',
        '- `output/candidate_b_exposure_scale_metrics.csv`：六个指定时间区间 × 32组。',
        '- `output/candidate_b_unused_cash_attribution.csv`：七项现金归因。',
        '- `output/history_revision_and_new_period.csv`：旧历史重算影响与新增8日收益拆开。',
        '- `input_manifest.json`、`contract.json`、`output/account_run_manifest.json`、`output/account_validation.csv`：输入与实际运行证据。',
        'KEEP_NATIVE 保持不变。本报告是独立的新证据，既不优化X，也不将MAX_FILL升级为生产候选。']
    lines[-1:-1]=diagnostic_answers(f,baseline,c)
    (HERE/'REPORT.md').write_text('\n\n'.join(lines)+'\n')
    print('REPORT WRITTEN',flush=True)
if __name__=='__main__':main()
