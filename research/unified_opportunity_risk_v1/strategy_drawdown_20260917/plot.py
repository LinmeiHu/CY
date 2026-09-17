"""Native standalone drawdowns: full high water and explicitly reset windows."""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager,dates as mdates
from matplotlib.ticker import PercentFormatter
from .run import HERE,OUT,STRATEGIES,END
from research.portfolio_closure_v1 import repair
NAMES={'ATRDR':'ATRDR 原生多路由','MCB':'MCB 行业点火','OGR':'OGR 缺口回收','IFCGR':'IFCGR 发行人事实过滤','SMV6':'SMV6 ETF轮动'}

def main():
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family':'Arial Unicode MS','font.size':11})
    series={};rows=[];daily=[];receipts={}
    for s in STRATEGIES:
        dest=OUT/'accounts'/s;r=json.loads((dest/'receipt.json').read_text());receipts[s]=r
        for name,h in r['hashes'].items():assert repair.digest(dest/name)==h
        d=pd.read_parquet(dest/'daily.parquet');d.trade_date=pd.to_datetime(d.trade_date)
        a=json.loads((dest/'account.json').read_text());d['nav_multiple']=d.nav/a['initial_cash']
        d['full_drawdown']=d.nav_multiple/np.maximum.accumulate(np.r_[1.,d.nav_multiple])[1:]-1
        series[s]=d
        for title,start in [('全期','2018-01-01'),('近六个月','2026-04-01'),('7月至今','2026-07-01')]:
            g=d[d.trade_date.ge(start)].copy();prior=d[d.trade_date.lt(start)]
            seed=prior.nav.iloc[-1] if len(prior) else a['initial_cash'];g['window_drawdown']=g.nav/np.maximum.accumulate(np.r_[seed,g.nav])[1:]-1
            trough=g.loc[g.full_drawdown.idxmin()];wtrough=g.loc[g.window_drawdown.idxmin()]
            rows.append(dict(strategy=s,window=title,start=start,end=END,return_=g.nav.iloc[-1]/seed-1,window_MaxDD=max(0.,-g.window_drawdown.min()),window_trough=str(wtrough.trade_date.date()),deepest_full_history_drawdown_in_window=-g.full_drawdown.min(),full_history_trough=str(trough.trade_date.date()),current_full_history_drawdown=-g.full_drawdown.iloc[-1]))
            daily.append(g[['trade_date','nav','nav_multiple','full_drawdown','window_drawdown']].assign(strategy=s,window=title))
    f=pd.DataFrame(rows);f.to_csv(OUT/'strategy_drawdown_metrics.csv',index=False)
    pd.concat(daily).to_csv(OUT/'strategy_drawdown_daily.csv.gz',index=False)
    colors=['#176b9a','#c24c2b','#329563','#8f5aac','#b09219']
    fig,ax=plt.subplots(figsize=(16,6))
    for s,color in zip(STRATEGIES,colors):
        d=series[s];ax.plot(d.trade_date,d.full_drawdown,label=NAMES[s],color=color,lw=1.35)
    ax.yaxis.set_major_formatter(PercentFormatter(1));ax.grid(alpha=.2);ax.set_ylabel('相对2018年以来高水位的回撤');ax.set_title(f'五策略独立 Native 账户：全历史回撤 | 2018—{END}')
    ax.legend(ncol=5,loc='lower center',bbox_to_anchor=(.5,-.23));fig.tight_layout();fig.savefig(OUT/'strategy_drawdown_full.png',dpi=160);plt.close(fig)
    for start,tag in [('2026-04-01','six_months'),('2026-07-01','recent')]:
        fig,axes=plt.subplots(5,1,figsize=(16,14),sharex=True)
        for ax,s in zip(axes,STRATEGIES):
            d=series[s];g=d[d.trade_date.ge(start)].copy();seed=d.loc[d.trade_date.lt(start),'nav'].iloc[-1]
            g['window_drawdown']=g.nav/np.maximum.accumulate(np.r_[seed,g.nav])[1:]-1
            ax.plot(g.trade_date,g.full_drawdown,color='#c34b45',lw=2,label='延续全历史高水位（真实回撤）')
            ax.fill_between(g.trade_date,g.full_drawdown,0,color='#c34b45',alpha=.10)
            ax.plot(g.trade_date,g.window_drawdown,color='#176b9a',lw=1.7,ls='--',label='窗口前一交易日重置高水位')
            ax.axhline(0,color='#777777',lw=.7);ax.yaxis.set_major_formatter(PercentFormatter(1));ax.grid(alpha=.18)
            ax.set_title(NAMES[s],loc='left',fontsize=12,fontweight='bold')
            low=g.loc[g.full_drawdown.idxmin()]
            ax.scatter([low.trade_date],[low.full_drawdown],s=20,color='#c34b45',zorder=3)
            ax.text(.995,.08,f'截至9/16真实回撤：{-g.full_drawdown.iloc[-1]:.2%}   |   窗口内真实最深：{-g.full_drawdown.min():.2%}（{low.trade_date:%m/%d}）\n窗口重置后的最大回撤：{max(0.,-g.window_drawdown.min()):.2%}',transform=ax.transAxes,ha='right',va='bottom',fontsize=10,bbox=dict(facecolor='white',alpha=.88,edgecolor='none'))
            span=max(-g.full_drawdown.min(),-g.window_drawdown.min(),.002)
            ax.set_ylim(-span*1.25,span*.06)
        axes[-1].xaxis.set_major_locator(mdates.WeekdayLocator(interval=2 if tag=='recent' else 4));axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        axes[-1].set_xlim(pd.Timestamp(start),pd.Timestamp(END))
        handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=2,bbox_to_anchor=(.5,.025))
        fig.suptitle(f'五策略独立 Native 账户：近期回撤放大 | {start}—{END}',fontsize=17,y=.985)
        fig.text(.5,.01,'各策略纵轴分别缩放以看清细节；红线不在窗口起点清零。原生定仓，无X/Y放大；不是统一池内收益贡献。',ha='center',fontsize=10)
        fig.tight_layout(rect=[0,.065,1,.97]);fig.savefig(OUT/f'strategy_drawdown_{tag}.png',dpi=160);plt.close(fig)
    repair.write_json(OUT/'verification.json',dict(status='PASS',accounts=5,days=2114,end=END,mode='INDEPENDENT_NATIVE',source_manifest_sha256=repair.digest(HERE.parent/'rollforward_20260917/input_manifest.json'),receipts=receipts))
    recent=f[f.window.eq('7月至今')].copy()
    report=['# 五策略独立 Native 回撤',f'数据截至 {END}，与上一轮32组实验使用相同的冻结刷新数据。分别重放五个独立原生账户，保留各自已验证的2018年初现金和持仓；没有X/Y放大，也不是组合内贡献曲线。',
            '红线延续全历史高水位，蓝虚线仅用于观察窗口内回撤，窗口前已有亏损不会从红线消失。各策略近景纵轴独立缩放。',
            '![近三个月](output/strategy_drawdown_recent.png)','![近六个月](output/strategy_drawdown_six_months.png)','![全历史](output/strategy_drawdown_full.png)',
            recent.to_markdown(index=False),'MCB自6月2日退出后，7月至9月16日实际空仓，近期平线并非缺失值填零。Gap适配器仅沿用上一轮已使用的未退出日期为空值保护，未改变入场、定仓或退出规则。OGR与IFCGR是分别运行的替代策略，不能相加理解为组合收益。KEEP_NATIVE保持不变。']
    (HERE/'REPORT.md').write_text('\n\n'.join(report)+'\n');print(f.to_string(index=False),flush=True)
if __name__=='__main__':main()
