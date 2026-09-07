"""Small descriptive figures; no parameter selection or new experiments."""
from pathlib import Path
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from state_v2 import HERE


def run():
    ext=Path(json.loads((HERE/'input_config.json').read_text())['external_root']);out=HERE/'figures';out.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':130})
    s=pd.read_csv(HERE/'simple_exit_response.csv')
    fig,axes=plt.subplots(2,3,figsize=(12,6),sharex=True,sharey=True)
    for ax,route in zip(axes.flat,['ATRDR_BULL','ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','MCB','OGR']):
        for phase,color in [('DISCOVERY','#286B9A'),('EVALUATION','#CC6E38')]:
            d=s.loc[s.route.eq(route)&s.period.eq(phase)&s.family.eq('fixed')].sort_values('value')
            ax.plot(d.value*100,d.mean_advantage*100,'o-',label=phase,color=color)
        ax.axhline(0,color='#777777',lw=.8);ax.set_title(route);ax.set_xlabel('Close loss threshold (%)');ax.set_ylabel('Mean event exit increment (pp)')
    axes.flat[5].axis('off');axes.flat[0].legend(fontsize=8)
    fig.suptitle('Same clock: observed close -> next legal open. All history consumed.');fig.tight_layout();fig.savefig(out/'fixed_stop_response.png');plt.close(fig)
    fig,axes=plt.subplots(2,1,figsize=(10,6),sharex=True)
    for name,file in [('Native','MCB_CONTINUOUS_2014_2023_nav.parquet'),('Fixed 10%','policy_MCB_CONTINUOUS_2014_2023_fixed_0.1_nav.parquet'),('MFE5 / close <= 0','policy_MCB_CONTINUOUS_2014_2023_profit_0_nav.parquet')]:
        n=pd.read_parquet(ext/file).set_index('trade_date').nav
        prior=n.loc[n.index<'2021-01-01'].iloc[-1];n=n.loc[n.index>='2021-01-01']/prior
        axes[0].plot(n.index,n,label=name);peak=np.maximum.accumulate(np.r_[1.,n.to_numpy()])[1:]
        axes[1].plot(n.index,(n/peak-1)*100,label=name)
    axes[0].set_ylabel('Evaluation wealth (start = 1)');axes[1].set_ylabel('Drawdown (%)');axes[0].legend()
    axes[0].set_title('MCB: unchanged entries, regenerated funding, frozen local execution model');fig.tight_layout();fig.savefig(out/'mcb_policy_nav_drawdown.png');plt.close(fig)
    e=pd.read_parquet(ext/'events_MCB_fixed_0.1.parquet');e=e.loc[e.qty.notna()&e.filled].sort_values(['signal_date','episode_id'])
    examples=[e.loc[e.native_return.gt(0)&e.advantage_return.lt(0)].iloc[0],e.loc[e.native_return.le(-.1)&e.advantage_return.gt(0)].iloc[0]]
    paths=pd.read_parquet(ext/'candidate_position_paths.parquet');fig,axes=plt.subplots(1,2,figsize=(11,4))
    for ax,row,title in zip(axes,examples,['Winner harmed: rebound after exit','Severe loss reduced under exit contract']):
        p=paths.loc[paths.episode_id.eq(row.episode_id)]
        p=p.loc[(p.trade_date+pd.Timedelta(hours=16)).lt(pd.Timestamp(row.native_time))]
        ax.plot(p.trade_date,p.current_pnl*100,label='Observed held-close PnL')
        ax.axhline(-10,color='#777777',ls='--',label='Close threshold');ax.axvline(row.decision_at,color='#CC6E38',ls=':',label='First decision')
        ax.scatter([row.exit_time_policy],[row.policy_return*100],color='#CC6E38',zorder=3,label='Net policy exit')
        ax.scatter([row.native_time],[row.native_return*100],marker='x',color='#286B9A',zorder=3,label='Net native exit')
        ax.set_title(title+'\n'+str(row.event_id).split('|')[-1]);ax.set_ylabel('Return (%)');ax.tick_params(axis='x',rotation=25)
    axes[0].legend(fontsize=7);fig.suptitle('Descriptive first chronological opposing examples; not rule selection');fig.tight_layout();fig.savefig(out/'mcb_opposing_paths.png');plt.close(fig)


if __name__=='__main__':run()
