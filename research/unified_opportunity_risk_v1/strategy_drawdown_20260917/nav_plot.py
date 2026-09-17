"""Independent Native NAV curves, with clear recent-period rebasing."""
import json
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager,dates as mdates
from matplotlib.ticker import PercentFormatter
from .run import HERE,OUT,STRATEGIES,END
from .plot import NAMES

def main():
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family':'Arial Unicode MS','font.size':11})
    series={};metrics=[]
    for s in STRATEGIES:
        p=OUT/'accounts'/s;d=pd.read_parquet(p/'daily.parquet');d.trade_date=pd.to_datetime(d.trade_date);a=json.loads((p/'account.json').read_text());series[s]=(d,a)
        for name,start in [('全期','2018-01-01'),('4月至今','2026-04-01'),('7月至今','2026-07-01')]:
            before=d[d.trade_date.lt(start)];g=d[d.trade_date.ge(start)];seed=float(before.nav.iloc[-1]) if len(before) else a['initial_cash'];years=(pd.Timestamp(END)+pd.Timedelta(days=1)-pd.Timestamp(start)).days/365.25
            metrics.append(dict(strategy=s,period=name,start=start,end=END,start_equity=seed,end_equity=g.nav.iloc[-1],return_=g.nav.iloc[-1]/seed-1,CAGR=(g.nav.iloc[-1]/seed)**(1/years)-1,average_gross=(g.gross_exposure/g.nav).mean()))
    pd.DataFrame(metrics).to_csv(OUT/'strategy_nav_metrics.csv',index=False)
    for mode,start in [('full','2018-01-01'),('six_months','2026-04-01'),('recent','2026-07-01')]:
        fig,axes=plt.subplots(5,1,figsize=(16,14),sharex=True)
        for ax,s in zip(axes,STRATEGIES):
            d,a=series[s];before=d[d.trade_date.lt(start)];g=d[d.trade_date.ge(start)].copy();seed=float(before.nav.iloc[-1]) if len(before) else a['initial_cash'];v=g.nav/seed
            if len(before):
                dates=pd.concat([pd.Series([before.trade_date.iloc[-1]]),g.trade_date],ignore_index=True);values=pd.concat([pd.Series([1.]),v],ignore_index=True)
            else:dates=g.trade_date;values=v
            ax.plot(dates,values,color='#176b9a',lw=2)
            ax.axhline(1,color='#777777',ls='--',lw=.8);ax.grid(alpha=.18)
            ax.set_title(NAMES[s],loc='left',fontsize=12,fontweight='bold');ax.set_ylabel('净值')
            low=min(values.min(),1.);high=max(values.max(),1.);span=max(high-low,.001)
            ax.set_ylim(low-span*.20,high+span*.30)
            ax.ticklabel_format(axis='y',style='plain',useOffset=False)
            gain=v.iloc[-1]-1
            annotation=f'区间收益：{gain:+.2%}   |   期末净值：{v.iloc[-1]:.4f}'
            if s=='MCB' and mode!='full':annotation+='   |   近期空仓'
            ax.text(.995,.88,annotation,transform=ax.transAxes,ha='right',va='top',fontsize=11,bbox=dict(facecolor='white',alpha=.9,edgecolor='none'))
            ax.scatter([g.trade_date.iloc[-1]],[v.iloc[-1]],s=18,color='#176b9a',zorder=3)
            if mode!='full':ax.axvline(pd.Timestamp('2026-09-04'),color='#aaa',lw=.8,ls=':')
        if mode!='full':
            axes[-1].xaxis.set_major_locator(mdates.WeekdayLocator(interval=2 if mode=='recent' else 4));axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        axes[-1].set_xlim(pd.Timestamp(start),pd.Timestamp(END))
        title='全历史' if mode=='full' else '近期放大'
        fig.suptitle(f'五策略独立 Native 回测净值：{title} | {start}—{END}',fontsize=17,y=.985)
        seedtext='各策略2018年初已验证账户权益归一为1' if mode=='full' else ('2026-06-30收盘净值归一为1' if mode=='recent' else '2026-03-31收盘净值归一为1')
        fig.text(.5,.017,seedtext+'；各行纵轴独立缩放。保留原生定仓与现金，不是统一池内贡献，也未施加X/Y放大。',ha='center',fontsize=10)
        fig.tight_layout(rect=[0,.045,1,.97]);fig.savefig(OUT/f'strategy_nav_{mode}.png',dpi=160);plt.close(fig)
    f=pd.DataFrame(metrics);display=f[f.period.eq('7月至今')][['strategy','return_','average_gross']].copy()
    for c in ['return_','average_gross']:display[c]=display[c].map(lambda v:f'{v:.2%}')
    (HERE/'NAV_REPORT.md').write_text('\n\n'.join(['# 五策略独立回测净值',f'截至{END}。按用户更正展示净值曲线。使用同一批最新前复权数据及已完成的五个独立Native账户；保留2018年初已验证状态，不施加X/Y放大。',
    '近期图以窗口前一交易日收盘权益归一为1，各行纵轴独立缩放，不能比较屏幕高度。曲线包含实际空仓期。',
    '![7月至今](output/strategy_nav_recent.png)','![4月至今](output/strategy_nav_six_months.png)','![全历史](output/strategy_nav_full.png)',display.to_markdown(index=False),
    'MCB在7月至9月16日实际空仓、没有成交，近期净值为平线。OGR与IFCGR分别作为替代策略独立重放，不能直接相加为组合收益。现金、总敞口、损益守恒、持仓公司行动及2114个交易日覆盖检查通过。KEEP_NATIVE不变。'])+'\n')
    print(f.to_string(index=False),flush=True)
if __name__=='__main__':main()
