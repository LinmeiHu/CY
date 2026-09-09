"""All 32 actual curves, grouped by Y, with display-only market benchmarks."""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import PercentFormatter
from research.unified_opportunity_risk_v1.max_fill_security_cap.grid import OUT,XS,YS,directory
from research.unified_opportunity_risk_v1.exposure_scale import run as previous


def main():
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family':'Arial Unicode MS','font.size':10})
    benchmark=pd.read_csv(previous.OUT/'benchmark_prices.csv',parse_dates=['trade_date'])
    colors=['#264653','#2a9d8f','#57a773','#b69622','#f4a261','#e76f51','#9b5de5','#111111']
    for drawdown in [False,True]:
        fig,axes=plt.subplots(2,2,figsize=(19,12),sharex=True,sharey=True)
        lines=[]
        for ax,y in zip(axes.flat,YS):
            for x,color in zip(XS,colors):
                dest=directory(x,y);daily=pd.read_parquet(dest/'daily.parquet')
                initial=json.loads((dest/'account.json').read_text())['initial_cash']
                values=daily.nav.to_numpy()/initial
                if drawdown:values=values/np.maximum.accumulate(np.r_[1.,values])[1:]-1
                line=ax.plot(pd.to_datetime(daily.trade_date),values,color=color,label=previous.label(x),lw=1.5)[0]
                if y==YS[0]:lines.append(line)
            ax.set_title(f'单票新增上限 Y = {y:.0%}')
            ax.set_xlim(pd.Timestamp('2018-01-01'),pd.Timestamp('2026-09-04'))
            ax.grid(alpha=.18)
            ax.set_ylabel('回撤' if drawdown else '账户净值（初始权益 = 1）')
            if drawdown:ax.yaxis.set_major_formatter(PercentFormatter(1))
            else:
                right=ax.twinx();right.set_ylim(40,190);right.set_ylabel('指数（首日收盘 = 100）')
                for name,label,color,style in [('SSE Composite','上证指数（右轴）','#457b9d','--'),('SZSE Component','深证成指（右轴）','#d45087',':')]:
                    b=benchmark.loc[benchmark.benchmark.eq(name)]
                    line=right.plot(b.trade_date,b.normalized_100,label=label,color=color,ls=style,lw=1,alpha=.6)[0]
                    if y==YS[0]:lines.append(line)
        fig.suptitle('Candidate B：完整 X × Y 连续账户'+('回撤' if drawdown else '净值与市场指数'),fontsize=17,y=.98)
        fig.legend(lines,[line.get_label() for line in lines],loc='lower center',ncol=5,frameon=False,bbox_to_anchor=(.5,.02))
        fig.text(.5,.006,'2018—2026-09-04 | 2024年起为事后诊断 | KEEP_NATIVE 不变'+('' if drawdown else ' | 左右轴独立，屏幕高度不可直接比较收益'),ha='center',fontsize=10)
        fig.tight_layout(rect=[0,.085,1,.955])
        fig.savefig(OUT/('candidate_b_xy_drawdown.png' if drawdown else 'candidate_b_xy_nav.png'),dpi=150)
        plt.close(fig)


if __name__=='__main__':main()
