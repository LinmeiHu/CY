from pathlib import Path
import pandas as pd
HERE=Path(__file__).resolve().parent
OUT=Path('/Volumes/quant/CY_quant_research/minervini_ashare_clean_ascent_v2')
navs={p.parent.name:pd.read_parquet(p) for p in OUT.glob('*/nav.parquet')}
# Plot reusable scientific figure, not an interactive product.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,axes=plt.subplots(2,2,figsize=(13,7),sharex=True)
for col,mode in enumerate(['MAX_DEPLOYABLE','CAP10']):
    for key in ['OLD_MAIN_B0','OLD_MAIN_PC','N_MAIN_N0','N_MAIN_N1','N_MAIN_N4','N_MAIN_N9']:
        sid=key+'_'+mode
        if sid not in navs:continue
        n=navs[sid];x=pd.to_datetime(n.date);axes[0,col].plot(x,n.nav/1e6,label=key.replace('_MAIN_',' '),linewidth=1)
        axes[1,col].plot(x,n.exposure,label=key,linewidth=.6,alpha=.7)
    axes[0,col].set_title(mode);axes[0,col].legend(fontsize=7);axes[0,col].set_ylabel('NAV / initial');axes[1,col].set_ylabel('Actual invested / NAV')
    for ax in axes[:,col]:ax.grid(alpha=.2)
fig.tight_layout();fig.savefig(HERE/'nav_and_utilization.png',dpi=150);plt.close(fig)
