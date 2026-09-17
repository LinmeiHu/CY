"""All X curves per Y, with independently scaled display-only benchmarks."""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter
from .run import OUT,XS,YS,directory,END
from .prepare_stock import CACHE
from research.unified_opportunity_risk_v1.exposure_scale import run as previous

def main():
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family':'Arial Unicode MS','font.size':10})
    colors=['#264653','#2a9d8f','#57a773','#b69622','#f4a261','#e76f51','#9b5de5','#111111']
    for mode in ['nav','nav_recent','drawdown','gross']:
        fig,axes=plt.subplots(2,2,figsize=(19,12),sharex=True,sharey=True);lines=[]
        for ax,y in zip(axes.flat,YS):
            for x,color in zip(XS,colors):
                dest=directory(x,y);d=pd.read_parquet(dest/'daily.parquet');d.trade_date=pd.to_datetime(d.trade_date)
                initial=json.loads((dest/'account.json').read_text())['initial_cash']
                if mode=='nav_recent':
                    initial=float(d.loc[d.trade_date.lt('2026-07-01'),'nav'].iloc[-1]);d=d.loc[d.trade_date.ge('2026-07-01')].copy()
                v=d.nav.to_numpy()/initial
                if mode=='drawdown':v=v/np.maximum.accumulate(np.r_[1.,v])[1:]-1
                if mode=='gross':v=(d.gross_exposure/d.nav).to_numpy()
                line=ax.plot(d.trade_date,v,color=color,label=previous.label(x),lw=1.5)[0]
                if y==YS[0]:lines.append(line)
            ax.set_title(f'单票新增上限 Y = {y:.0%}')
            ax.set_xlim(pd.Timestamp('2026-07-01' if mode=='nav_recent' else '2018-01-01'),pd.Timestamp(END))
            ax.grid(alpha=.18);ax.set_ylabel({'drawdown':'账户回撤','gross':'总仓位','nav_recent':'账户净值（2026-06-30收盘 = 1）'}.get(mode,'账户净值（初始权益 = 1）'))
            if mode in ['drawdown','gross']:ax.yaxis.set_major_formatter(PercentFormatter(1))
            else:
                right=ax.twinx();right.set_ylabel('指数（2026-06-30收盘 = 100）' if mode=='nav_recent' else '指数（2018首日收盘 = 100）')
                for symbol,label,color,style in [('000001.SH','上证指数（右轴）','#457b9d','--'),('399001.SZ','深证成指（右轴）','#d45087',':')]:
                    b=pd.read_parquet(CACHE/'benchmarks'/f'{symbol}.parquet');b=b[b.trade_date.ge('2018-01-01')].sort_values('trade_date')
                    seed=float(b.close.iloc[0])
                    if mode=='nav_recent':
                        seed=float(b.loc[b.trade_date.lt('2026-07-01'),'close'].iloc[-1]);b=b.loc[b.trade_date.ge('2026-07-01')].copy()
                    line=right.plot(b.trade_date,b.close/seed*100,label=label,color=color,ls=style,lw=1,alpha=.65)[0]
                    if y==YS[0]:lines.append(line)
            if mode=='nav_recent':ax.axvline(pd.Timestamp('2026-09-04'),color='#999999',ls=':',lw=1)
        title={'nav':'全历史净值与市场指数','nav_recent':'近期净值与市场指数','drawdown':'全历史回撤','gross':'全历史总仓位'}[mode]
        fig.suptitle('Candidate B：32组 X × Y 连续账户 — '+title,fontsize=17,y=.98)
        fig.legend(lines,[line.get_label() for line in lines],loc='lower center',ncol=5,frameon=False,bbox_to_anchor=(.5,.02))
        fig.text(.5,.006,f'2018—{END} | 最新ETF前复权全量重跑 | KEEP_NATIVE不变'+(' | 左右轴独立，屏幕高度不可比较收益' if mode.startswith('nav') else ''),ha='center',fontsize=10)
        fig.tight_layout(rect=[0,.085,1,.955]);fig.savefig(OUT/f'candidate_b_xy_{mode}.png',dpi=150)
        if mode in ['nav','drawdown','gross']:fig.savefig(OUT/f'candidate_b_exposure_scale_{mode}.png',dpi=150)
        plt.close(fig)
if __name__=='__main__':main()
