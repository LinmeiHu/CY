"""Publish only completed transaction-level Top 5 replays and annual accounts."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from build_rollforward_inputs import OUT,END

HERE=Path(__file__).resolve().parents[1]
REPORT=HERE/'reports/continuous_rollforward_v2'
OUTPUT=HERE/'output/continuous_rollforward_v2'


def annual_metrics(frame,initial_nav,label,rank=0):
    frame=frame.sort_values('trade_date').copy()
    assert not frame.trade_date.duplicated().any() and frame.nav.notna().all() and frame.nav.gt(0).all()
    frame['previous_nav']=frame.nav.shift(1,fill_value=initial_nav)
    frame['daily_return']=frame.nav/frame.previous_nav-1
    rows=[]
    for year,f in frame.groupby(frame.trade_date.dt.year):
        if year<2022:continue
        base=float(f.previous_nav.iloc[0]);values=np.r_[base,f.nav.to_numpy()]
        ret=float(values[-1]/base-1);r=f.daily_return.to_numpy();vol=float(np.std(r,ddof=1)*np.sqrt(252)) if len(r)>1 else np.nan
        dd=float(-np.min(values/np.maximum.accumulate(values)-1))
        annualized=float((1+ret)**(252/len(f))-1)
        rows.append(dict(rank=rank,combination=label,year=int(year),period='YTD' if year==2026 else 'FULL_YEAR',
            start=str(f.trade_date.iloc[0].date()),end=str(f.trade_date.iloc[-1].date()),trading_days=len(f),
            return_pct=ret*100,max_drawdown_pct=dd*100,annualized_volatility_pct=vol*100,
            sharpe=float(np.mean(r)*252/vol) if vol>0 else np.nan,
            annualized_return_pct=annualized*100,calmar=annualized/dd if dd>0 else np.nan,
            start_nav=base,end_nav=float(f.nav.iloc[-1]),
            average_exposure_pct=float((f.gross_exposure/f.nav).mean()*100) if 'gross_exposure' in f else np.nan,
            min_cash=float(f.cash.min()) if 'cash' in f else np.nan))
    return rows


def main():
    REPORT.mkdir(exist_ok=True,parents=True);OUTPUT.mkdir(exist_ok=True,parents=True)
    selected=pd.read_csv(HERE/'output/combined_top5_backtest_curve_selection.csv').sort_values('rank')
    curves=[];metrics=[];audits=[];benchmarks={};parities=[]
    for symbol,label in [('000001.SH','上证指数'),('399001.SZ','深证成指')]:
        f=pd.read_parquet(HERE/'qmt_stock_delta'/f'{symbol}_1d.parquet').sort_values('trade_date').set_index('trade_date')
        benchmarks[label]=f.close
    calendar=None
    for row in selected.itertuples(index=False):
        folder=OUT/'combinations'/f'{row.gap}_{row.mcb_mode}_{row.target}'
        receipt=json.loads((folder/'receipt.json').read_text())
        assert receipt['status']=='PASS' and receipt['end'].startswith(END)
        f=pd.read_parquet(folder/'daily.parquet').sort_values('trade_date')
        f['trade_date']=pd.to_datetime(f.trade_date)
        reference=pd.read_parquet(Path(row.source)/'daily.parquet')
        paired=f.merge(reference,on='trade_date',suffixes=('_new','_old'),validate='one_to_one')
        parity=dict(rank=int(row.rank),days=len(paired))
        for field in ['nav','cash','gross_exposure']:
            difference=float(abs(paired[field+'_new']-paired[field+'_old']).max())
            if difference>1e-5:raise ValueError(f'scaled historical prefix mismatch: {row.rank} {field} {difference}')
            parity[field+'_max_abs_difference']=difference
        assert len(paired)==973
        parity['status']='PASS';parities.append(parity)
        if calendar is None:calendar=pd.DatetimeIndex(f.trade_date)
        else:assert calendar.equals(pd.DatetimeIndex(f.trade_date))
        assert f.cash.ge(-1e-6).all() and (f.gross_exposure<=f.nav+1e-6).all()
        label=f'{row.gap} / {row.mcb_mode} / {row.target}'
        metric=annual_metrics(f,receipt['initial_nav'],label,int(row.rank));metrics.extend(metric)
        curve=f[['trade_date','nav','cash','gross_exposure']].copy();curve['nav_multiple']=curve.nav/receipt['initial_nav'];curve['rank']=row.rank;curve['combination']=label
        curves.append(curve);audits.append(receipt)
    curves=pd.concat(curves,ignore_index=True);metrics=pd.DataFrame(metrics)
    for label,series in benchmarks.items():
        aligned=series.reindex(calendar)
        assert aligned.notna().all(),f'missing real benchmark bars: {label}'
        benchmarks[label]=aligned/aligned.iloc[0]*100
    curves.to_csv(OUTPUT/'top5_daily_accounts.csv',index=False)
    metrics.to_csv(OUTPUT/'top5_annual_metrics_2022_onward.csv',index=False)
    pd.DataFrame(benchmarks).rename_axis('trade_date').to_csv(OUTPUT/'benchmark_rebased.csv')
    pd.DataFrame(audits).to_csv(OUTPUT/'account_completion_audit.csv',index=False)
    pd.DataFrame(parities).to_csv(OUTPUT/'scaled_historical_prefix_parity.csv',index=False)
    plt.rcParams.update({'font.sans-serif':['PingFang SC','Heiti TC','Arial Unicode MS','DejaVu Sans'],'axes.unicode_minus':False})
    colors=['#2457B3','#BD3C32','#25836C','#9357A5','#A47111']
    fig,axes=plt.subplots(3,2,figsize=(18,17),layout='constrained')
    for rank,ax in enumerate(axes.flat[:5],start=1):
        f=curves.loc[curves['rank'].eq(rank)];r=ax.twinx()
        ax.plot(f.trade_date,f.nav_multiple,color=colors[rank-1],lw=1.5,label='组合净值')
        for (label,series),color,style in zip(benchmarks.items(),['#66737C','#D38A4D'],['--',':']):
            r.plot(series.index,series,color=color,lw=1.05,ls=style,label=label,alpha=.85)
        ax.set_title(f'#{rank}  {f.combination.iloc[0]}',fontsize=13)
        ax.set_ylabel('组合净值（初始资本 = 1）');r.set_ylabel('指数（首日收盘 = 100）')
        ax.grid(alpha=.18);ax.axvline(pd.Timestamp('2024-01-01'),color='#555',lw=.7,alpha=.5)
        handles,labels=ax.get_legend_handles_labels();h,l=r.get_legend_handles_labels();ax.legend(handles+h,labels+l,loc='upper left',fontsize=9)
    axes.flat[5].axis('off')
    table=metrics.pivot(index='rank',columns='year',values='return_pct')
    table.to_csv(OUTPUT/'top5_annual_returns_pct.csv')
    cell=[[f'#{i}',*[f'{v:+.2f}%' for v in row]] for i,row in table.iterrows()]
    t=axes.flat[5].table(cellText=cell,colLabels=['组合',*map(str,table.columns)],loc='center',cellLoc='center')
    t.auto_set_font_size(False);t.set_fontsize(11);t.scale(1,2)
    axes.flat[5].set_title('年度收益率（2026 为截至 9 月 4 日的 YTD）',fontsize=13)
    ytd=metrics.loc[metrics.year.eq(2026)].sort_values('rank')
    dd_label='2026 年最大回撤\n'+'   '.join(f"#{int(r['rank'])}  {r['max_drawdown_pct']:.2f}%" for r in ytd.to_dict('records'))
    axes.flat[5].text(.5,.15,dd_label,ha='center',va='center',transform=axes.flat[5].transAxes,fontsize=10,color='#9E302A')
    fig.suptitle(f'原 Top 5 组合：连续账户回测至 {END}\n2018–2021 历史排名固定；2022 年以后未重新选优；实际资金缩放成交',fontsize=17)
    fig.savefig(REPORT/'top5_dual_axis_with_indices.png',dpi=170)
    fig.savefig(REPORT/'top5_dual_axis_with_indices.pdf')
    plt.close(fig)
    # Deliver annual native sleeve metrics separately from the scaled combinations.
    singles=[]
    for gap in ['OGR','IFCGR']:
        f=pd.read_parquet(OUT/'combinations'/f'{gap}_independent_NATIVE'/'daily.parquet')
        f['trade_date']=pd.to_datetime(f.trade_date)
        state=json.loads((OUT/'combinations'/f'{gap}_independent_NATIVE'/'account.json').read_text())
        for s in (['ATRDR','MCB','OGR','SMV6'] if gap=='OGR' else ['IFCGR']):
            part=f[['trade_date',s+'_nav',s+'_cash',s+'_exposure']].rename(columns={s+'_nav':'nav',s+'_cash':'cash',s+'_exposure':'gross_exposure'})
            singles.extend(annual_metrics(part,state['initial_states'][s]['nav'],s))
    pd.DataFrame(singles).to_csv(OUTPUT/'five_native_strategies_annual_metrics_2022_onward.csv',index=False)
    text=['# 五策略原 Top 5：连续滚动回测',
        f'组合共同截止日：**{END}**。SMV6 独立账户及两个指数的原始行情已到 2026-09-07；股票完整状态面板截至 2026-09-04，因此组合图统一使用 9 月 4 日。',
        '## 计算范围',
        '五套信号生产器已重新计算。组合从原验证的 2018 年初现金、持仓和路线状态起连续运行，没有在 2022 年或 2024 年重置账户。G100、G75 均通过资金缩放引擎计算实际订单、成交、费用、持仓和现金。',
        'Top 5 沿用原 2018–2021 年 CAGR 排名；没有根据 2024 年以后的表现重新选优。本报告属于事后滚动研究，不声称新增期间是未观察样本。',
        '股票保留原登记的 3,725 个标的，ETF 保留原 152 个标的；OGR、IFCGR 在每个组合中互斥。',
        '## 原 Top 5 年度收益',
        '|组合|2022|2023|2024|2025|2026 YTD|','|---|---:|---:|---:|---:|---:|']
    for i,row in table.iterrows():text.append('|#'+str(i)+'|'+'|'.join(f'{v:+.2f}%' for v in row)+'|')
    for row in selected.itertuples(index=False):text.append(f'- #{row.rank}: {row.gap} / {row.mcb_mode} / {row.target}')
    text.extend(['## 图表与指标口径',
        '曲线左轴是组合净值（2018 年初资本为 1）；右轴是上证指数和深证成指（首日收盘归一为 100）。两轴量纲不同，均在图中标明。',
        '年度收益以上年末净值为基数；年度最大回撤包含上年末净值作为初始高点。波动率与 Sharpe 使用日收益、252 个交易日年化，Sharpe 的无风险利率取 0。2026 年收益是实际 YTD，另列年化收益字段。最大回撤字段为正数幅度。',
        '完整年度表包括收益、最大回撤、波动率、Sharpe、Calmar、平均仓位、最低现金、起止净值及交易日数；另提供五套原生策略的年度指标。',
        '## 验证与数据修正',
        'OGR、IFCGR 两套原生组合的 2018–2021 年 973 个交易日，与原账户的净值、现金及持仓金额逐日完全一致。每套资金缩放账户另核对旧区间，并检查日期完整、净值有限、现金非负和总多头持仓金额不超过净值。',
        'OGR 重算后的 126 个后续信号与原股票池内旧信号完全一致；旧报告多出的 21 个信号全部不属于原组合登记股票池。IFCGR 对同批 126 个父信号重做发行人公告过滤，保留 116 个、否决 10 个。',
        '新增 QMT 股票分钟数据与日线有 1,241 个可对照股票交易日，每日 241 根；收盘价一致。个别日高低价相差 1 分，成交量差异最高约 1.84%，已保留跨源差异审计；执行分钟价格使用实际 QMT 分钟记录。',
        '按公告补全两笔送转股可交易/派息日期，并修正天际股份的 ST 生效日与涨跌幅规则：2026-07-14 停牌，7 月 15 日起 ST，涨跌幅仍为 10%。随后重建受影响的价格坐标、信号及账户。',
        '官方事实依据：[常熟银行](https://static.cninfo.com.cn/finalpage/2025-05-28/1223695580.PDF)、[南凌科技](https://static.cninfo.com.cn/finalpage/2026-05-21/1225323425.PDF)、[天际股份](https://static.cninfo.com.cn/finalpage/2026-07-14/1225422610.PDF)。PDF、哈希及修正前后数据均保留。',
        'IFCGR 仍属于 PIT-B 官方历史枚举研究；SMV6 使用原始回调和本地执行平台，未验证原生 SuperMind 等价性。',
        '## 产物位置',f'- 图表：`{REPORT}`',f'- CSV 指标与逐日账户：`{OUTPUT}`',f'- 信号、成交、连续账户、输入哈希和事实审计：`{OUT}`'])
    (REPORT/'研究报告.md').write_text('\n\n'.join(text).replace('|\n\n|','|\n|'),encoding='utf-8')
    print(table.to_string(),flush=True)


if __name__=='__main__':main()
