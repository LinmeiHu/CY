"""Static research figures from completed accounts, using the existing read-only plotting runtime."""
import csv,json,os
from pathlib import Path
HERE=Path(__file__).resolve().parent;OUT=Path('/Volumes/quant/CY_quant_research/usic_multichampion_ashare_v3');os.environ['MPLCONFIGDIR']=str(OUT/'mpl_cache')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def main():
    dest=HERE/'charts';dest.mkdir(exist_ok=True)
    rows=list(csv.DictReader((HERE/'scenario_summary.csv').open()));done=[r for r in rows if r['status']=='COMPLETED_NEW'];by={r['id']:r for r in done};routes=[f'D{i:02d}' for i in range(10)]+['H01','H02'];modes=['C_MAX','C_10','C_ONE'];cols=[(m,e) for m in modes for e in ['E10','EST']]
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white'})
    fig,axes=plt.subplots(1,3,figsize=(19,8.5),layout='constrained')
    for ax,field,title,lo,hi,cmap in zip(axes,['net_return','maxdd','mean_exposure'],['Net account return (%)','Maximum drawdown (%)','Mean deployed exposure (%)'],[-1,-1,0],[1.5,.0,1],['RdYlGn','RdYlGn','Blues']):
        arr=np.array([[float(by[f'A_{r}_{m}_{e}'][field])*100 for m,e in cols] for r in routes]);im=ax.imshow(arr,vmin=lo*100,vmax=hi*100,cmap=cmap,aspect='auto')
        for i in range(12):
            for j in range(6):ax.text(j,i,f'{arr[i,j]:.1f}',ha='center',va='center',fontsize=9,color='black' if field!='mean_exposure' or arr[i,j]<70 else 'white')
        ax.set_xticks(range(6),[m.replace('C_','')+'\n'+e for m,e in cols]);ax.set_yticks(range(12),routes);ax.set_title(title,pad=12);fig.colorbar(im,ax=ax,shrink=.6)
    fig.suptitle('All 72 core baseline accounts | 2020–2023 | Initial cash CNY 1,000,000',fontsize=17);fig.savefig(dest/'core_matrix.png',dpi=170);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,7),layout='constrained');colors={'C_MAX':'#2463aa','C_10':'#da8531','C_ONE':'#8757aa'}
    for mode in modes:
        group=[r for r in done if r['capital']==mode];ax.scatter([-float(r['maxdd'])*100 for r in group],[float(r['cagr'])*100 for r in group],s=[20+65*float(r['mean_exposure']) for r in group],alpha=.65,c=colors[mode],label=mode)
    for sid in ['A_H02_C_MAX_E10','A_D08_C_10_E10','B_D08_C_10_DELAY1','E_P3_CORROBORATE_C_ONE_EST']:
        r=by[sid];ax.annotate(sid,(-float(r['maxdd'])*100,float(r['cagr'])*100),xytext=(4,6),textcoords='offset points',fontsize=8)
    ax.axhline(0,color='#777',lw=.8);ax.set(xlabel='Maximum drawdown magnitude (%)',ylabel='CAGR (%)',title='252 completed accounts: return, drawdown, deployment\nPoint size = mean exposure; no independent OOS claim');ax.legend();ax.grid(alpha=.2);fig.savefig(dest/'account_comparison.png',dpi=170);plt.close(fig)
    # Exported tiny series avoids importing the research environment into the plotting runtime.
    navfile=OUT/'statistics/nav_plot_series.json'
    if navfile.exists():
        data=json.loads(navfile.read_text());fig,axs=plt.subplots(1,3,figsize=(16,5),layout='constrained')
        for ax,mode in zip(axs,modes):
            for route in ['D00','D02','D05','D08','H02']:
                key=f'A_{route}_{mode}_E10';v=data[key];ax.plot(range(len(v)),np.array(v)/1e6,label=route,lw=1.3)
            ax.set_title(mode+' / E10');ax.set_xlabel('Market sessions, 2020–2023');ax.axhline(1,color='#999',lw=.6);ax.grid(alpha=.2)
        axs[0].set_ylabel('NAV / initial capital');axs[-1].legend();fig.suptitle('Full cash NAV paths, including all losing years');fig.savefig(dest/'nav_comparison.png',dpi=170);plt.close(fig)
    print('PLOTS_COMPLETE',dest)
if __name__=='__main__':main()
