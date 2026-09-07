"""Read-only temporal error anatomy after the hypothesis/code freeze."""
from packets import *
from quantify import check_freeze


def run(complete=False):
    check_freeze()
    pred=pd.read_parquet(OUT/'visual_predictions.parquet')
    pred=pred.loc[pred.phase.eq('CONSUMED_TEMPORAL')&pred.model.eq('VISUAL')]
    if complete:pred=pred.loc[pred.representations_complete]
    folder='temporal_complete_errors' if complete else 'temporal_errors'
    prefix='visual_complete_state_error' if complete else 'visual_model_error'
    case_prefix='ECOMP_' if complete else 'ERROR_'
    states=pd.read_parquet(OUT/'visual_quant_states.parquet')
    pred=pred.merge(states[['episode_id','decision_at','native_net_return','age']],on=['episode_id','decision_at'],validate='one_to_one')
    selected=[];coverage=[]
    for route,g in pred.groupby('route',sort=True):
        masks={'HIGH_SCORE_NATIVE_WINNER':g.top_quintile&g.native_net_return.ge(.05)&g.exit_advantage_normalized.lt(0),
               'LOW_SCORE_SEVERE_LOSS':~g.top_quintile&g.native_net_return.le(-.10)&g.exit_advantage_normalized.gt(0)}
        for kind,mask in masks.items():
            q=g.loc[mask].copy();q['error_size']=(q.prediction-q.exit_advantage_normalized).abs();q['tie']=q.episode_id.map(token)
            coverage.append(dict(route=route,category=kind,eligible_states=len(q),eligible_events=q.episode_id.nunique(),selection='MAX_ABSOLUTE_FROZEN_MODEL_ERROR; diagnostic only'))
            if len(q):selected.append(dict(q.sort_values(['error_size','tie'],ascending=[False,True]).iloc[0],category=kind,case_id=case_prefix+token(route+'|'+kind)[:8].upper()))
    sel=pd.DataFrame(selected);sel.to_csv(HERE/(prefix+'_cases.csv'),index=False)
    pd.DataFrame(coverage).to_csv(HERE/(prefix+'_coverage.csv'),index=False)
    (OUT/folder).mkdir(exist_ok=True)
    e=read_bound(OLD/'all_source_normalized.parquet',"route IN ('ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','MCB','OGR') AND entry_date>=CASE WHEN route='OGR' THEN DATE '2022-01-01' ELSE DATE '2021-01-01' END AND native_time<DATE '2024-01-01'")
    e=e.loc[e.episode_id.isin(sel.episode_id)].drop_duplicates('episode_id').set_index('episode_id')
    manifest=[]
    for route,g in sel.groupby('route',sort=True):
        fig,axes=plt.subplots(5,len(g),figsize=(6.4*len(g),12),squeeze=False,sharex='col')
        for j,r in enumerate(g.itertuples(index=False)):
            src=e.loc[r.episode_id].copy();src['episode_id']=r.episode_id;p=stock_path(src,src.native_time);a=axes[:,j];x=p.age
            a[0].vlines(x,p.low,p.high,color='#b2bec3',lw=1);a[0].plot(x,p.close,color='#126782')
            a[0].plot(x,p.anchor,'--',color='#b5651d',label='registered anchor');a[0].plot(x,p.target,':',color='#6a4c93',label='entry-known target')
            a[0].scatter([0],[1],marker='>',color='black',s=30,label='entry')
            ex=float(src.exit_cal_idx-src.entry_cal_idx);ep=float(src.exit_price/src.entry_price)
            a[0].scatter([ex],[ep],marker='x',color='#d1495b',label='native exit')
            a[0].plot([x.iloc[-1],ex],[p.close.iloc[-1],ep],':',color='#d1495b')
            a[0].set_ylim(.4,1.6);a[0].axhline(1,color='#777',lw=.5)
            a[0].set_title(f'{r.case_id} | {r.category}\nnative net {r.native_net_return:+.1%}; observed age {r.age:g}\nexit advantage: predicted {r.prediction:+.1%}; actual {r.exit_advantage_normalized:+.1%}',fontsize=9)
            ins=a[0].inset_axes([.53,.07,.44,.34]);ins.plot(x,p.close,color='#126782');ins.axhline(1,color='#777',lw=.5);ins.set_xlim(0,20);ins.set_ylim(.4,1.6);ins.set_yticks([.5,1,1.5]);ins.set_xticks([0,10,20]);ins.tick_params(labelsize=5);ins.set_title('fixed 0..20 detail',fontsize=6)
            for col,color in [('current_pnl','#126782'),('mae_sofar','#d1495b'),('mfe_sofar','#2a9d8f'),('giveback','#e9a23b')]:a[1].plot(x,p[col],color=color,label=col)
            a[1].set_ylim(-.6,.6)
            a[2].bar(x,p.volume_entry,color='#cad2c5',label='volume / entry');a[2].plot(x,p.volume_prior5,color='#52796f',label='volume / prior5');a[2].set_ylim(0,5)
            a[3].set_ylim(-.3,.3);a[3].text(.5,.5,'FROZEN RETURN BENCHMARK UNAVAILABLE',transform=a[3].transAxes,ha='center',fontsize=8)
            a[4].set_ylim(-.03,.03);a[4].text(.5,.5,'PREREGISTERED MINUTE QUALITY UNAVAILABLE',transform=a[4].transAxes,ha='center',fontsize=8)
            for k,ax in enumerate(a):
                ax.axvline(r.age,color='#d1495b',ls='--',lw=.8,label='model observation t' if k==0 else None);ax.axvline(1,color='#888',ls=':',lw=.5)
                ax.set_xlim(0,160);ax.grid(alpha=.2)
                if j==0:ax.set_ylabel(['A price / entry','B path excursions','C relative volume','D relative strength','E minute summary'][k])
                handles,_=ax.get_legend_handles_labels()
                if handles:ax.legend(loc='upper right',fontsize=6)
            a[4].set_xlabel('holding session; full future path intentionally visible')
            manifest.append(dict(route=route,period='TEMPORAL_EVALUATION',case_id=r.case_id,episode_id=r.episode_id,chart_type='FULL_PATH_POSTMORTEM_ERROR_ANALYSIS',labels_visible=True,future_path_visible=True,observation_age=r.age,
                native_return=r.native_net_return,source_packet=str(OUT/folder/f'{route}.png'),purpose=('POSTHOC_COMPLETE_STATE_ERROR_ANATOMY; CANNOT_RESCUE_FAILED_GATE' if complete else 'READ_ONLY_FROZEN_MODEL_ERRORS; NOT_EXIT_RULE_COUNTERFACTUAL'),
                price_clipped_points=int((p.low.lt(.4)|p.high.gt(1.6)).sum()),age_clipped_points=int(p.age.gt(160).sum())+int(ex>160)))
        fig.suptitle(route+' | FULL-PATH-POSTMORTEM | TEMPORAL ERROR ANALYSIS\n'+('Complete representations only; posthoc diagnosis cannot rescue failed gate' if complete else 'Hypotheses already frozen; score bins are diagnostic, not executable exit triggers'),fontsize=13)
        fig.tight_layout(rect=[0,0,1,.94]);fig.savefig(OUT/folder/f'{route}.png',dpi=150);plt.close(fig)
    m=pd.read_csv(HERE/'visual_case_manifest.csv');pd.concat([m,pd.DataFrame(manifest)],ignore_index=True).to_csv(HERE/'visual_case_manifest.csv',index=False)
    log('TEMPORAL_ERROR_GALLERIES_RENDERED_AFTER_FREEZE',cases=len(sel),hypotheses_changed=False,complete_state_only=complete)
    print(sel[['route','case_id','category','prediction','exit_advantage_normalized']].to_string(index=False))


if __name__=='__main__':run(complete='--complete' in sys.argv)
