"""Read-only comparisons and counterexamples for already evaluated simple policies."""
from packets import *
import risk_review as rr


def run():
    done=json.loads((rr.OUT/'completed.json').read_text());assert done['account_replays']==20
    c=pd.read_csv(HERE/'risk_account_comparison.csv');effects=pd.read_csv(HERE/'risk_cash_reuse_decomposition.csv')
    f=pd.read_csv(HERE/'risk_funded_flow_changes.csv')
    reasons=[]
    for row in f.itertuples(index=False):
        strategy='ATRDR' if row.route.startswith('ATRDR') else row.route
        key='gap_id' if strategy in ['OGR','IFCGR'] else 'event_id'
        p=OLD/f'{strategy}_{row.segment}_skipped.parquet' if row.change=='NEWLY_FUNDED' else rr.OUT/f'{row.route}_{row.segment}_{row.policy}_skipped.parquet'
        skips=pd.read_parquet(p);found=skips.loc[skips[key].eq(row.event_id)]
        col='skip_reason' if 'skip_reason' in skips else 'status'
        reasons.append('|'.join(found[col].dropna().astype(str).unique()) if len(found) else 'UPSTREAM_ROUTE_OPPORTUNITY_SET_CHANGED')
    f['other_account_skip_reason']=reasons;f.to_csv(HERE/'risk_funded_flow_reason_audit.csv',index=False)
    f.groupby(['route','policy','segment','change','other_account_skip_reason']).size().rename('events').reset_index().to_csv(HERE/'risk_funding_reason_summary.csv',index=False)
    frontier=[]
    for (route,segment,period),g in c.groupby(['route','segment','period'],sort=False):
        for x in g.itertuples(index=False):
            dominates=(g.cagr.ge(x.cagr)&g.max_drawdown.ge(x.max_drawdown)&g.worst_trade.ge(x.worst_trade)&g.worst5_trade.ge(x.worst5_trade))
            strict=(g.cagr.gt(x.cagr+1e-12)|g.max_drawdown.gt(x.max_drawdown+1e-12)|g.worst_trade.gt(x.worst_trade+1e-12)|g.worst5_trade.gt(x.worst5_trade+1e-12))
            native_dominates=(x.baseline_cagr>=x.cagr and x.baseline_max_drawdown>=x.max_drawdown and x.baseline_worst_trade>=x.worst_trade and x.baseline_worst5_trade>=x.worst5_trade)
            frontier.append(dict(route=route,segment=segment,period=period,policy=x.policy,pareto_among_compared=not (dominates&strict).any() and not native_dominates,
                cagr_cost_pp=x.cagr_cost_pp,mdd_reduction_pp=x.mdd_reduction_pp,worst_trade_reduction_pp=x.worst_trade_reduction_pp,
                cost_per_mdd_point=x.cagr_cost_pp/x.mdd_reduction_pp if x.mdd_reduction_pp>1e-12 else np.nan,
                caveat='Descriptive four-objective frontier; not proof of optimum or statistical validation'))
    pd.DataFrame(frontier).to_csv(HERE/'risk_account_frontier.csv',index=False)
    fig,axes=plt.subplots(2,2,figsize=(12,8),sharex=True,sharey=True)
    for ax,route in zip(axes.flat,['ATRDR_BULL','ATRDR_FAST_BEAR','MCB','OGR']):
        phase='DISCOVERY' if route=='OGR' else 'FULL_HISTORY';g=c.loc[c.route.eq(route)&c.period.eq(phase)]
        ax.axhline(0,color='#bbb',lw=1);ax.axvline(0,color='#bbb',lw=1)
        for x in g.itertuples(index=False):
            color='#126782' if x.mdd_reduction_pp>=0 else '#d17a22'
            ax.scatter(x.cagr_cost_pp,x.worst_trade_reduction_pp,s=55,color=color)
            label=f"fixed {float(x.policy.split('_')[1])*100:g}%" if x.policy.startswith('fixed') else x.policy.replace('profit_0','MFE5 giveback')
            offset=(5,6) if route!='OGR' else {'fixed_0.05':(5,27),'fixed_0.03':(9,8),'atr_1':(5,-18)}[x.policy]
            ax.annotate(label,(x.cagr_cost_pp,x.worst_trade_reduction_pp),xytext=offset,textcoords='offset points',fontsize=8)
        ax.set_title(route+' | '+phase,fontsize=10);ax.set_xlim(-.25,4.8);ax.set_ylim(-4,20);ax.grid(alpha=.15)
        ax.set_xlabel('Account CAGR sacrificed (percentage points / year)');ax.set_ylabel('Worst funded trade loss reduction (pp)')
    fig.suptitle('Actual opportunity replay incl. cash reuse | blue: MDD improves; orange: MDD worsens\nATRDR conditional on known prefix defect; OGR is a separate 2018-2021 reset',fontsize=11)
    fig.tight_layout(rect=[0,0,1,.93]);fig.savefig(HERE/'representative_figures/risk_return_frontier.png',dpi=150);plt.close(fig)
    if '--summary-only' in sys.argv:return
    source=read_bound(OLD/'all_source_normalized.parquet',"route IN ('ATRDR_FAST_BEAR','MCB','OGR') AND entry_date<=DATE '2023-12-31' AND native_time<DATE '2024-01-01'").set_index('episode_id')
    folder=OUT/'risk_counterexamples';folder.mkdir(exist_ok=True);manifest=[];selection=[];coverage=[]
    for route,policy in [('ATRDR_FAST_BEAR','fixed_0.05'),('MCB','profit_0'),('OGR','fixed_0.05'),('OGR','atr_1')]:
        e=pd.read_parquet(OLD/f'events_{route}_{policy}.parquet');e=e.loc[e.qty.notna()&e.mature].copy()
        masks={'HARMED_WINNER':e.filled&e.native_return.ge(.05)&e.advantage_return.lt(0),
            'MISSED_SEVERE_LOSS':~e.triggered&e.native_return.le(-.10),
            'WORST_REALIZED_STOP':e.filled,
            'RESCUED_SEVERE_LOSS':e.filled&e.native_return.le(-.10)&e.advantage_return.gt(0)}
        chosen=[]
        for category,mask in masks.items():
            g=e.loc[mask].copy();g['tie']=g.episode_id.map(token)
            coverage.append(dict(route=route,policy=policy,category=category,eligible_events=len(g)))
            if g.empty:continue
            col='advantage_return' if category in ['HARMED_WINNER','RESCUED_SEVERE_LOSS'] else 'native_return' if category=='MISSED_SEVERE_LOSS' else 'policy_return'
            r=g.sort_values([col,'tie'],ascending=[category!='RESCUED_SEVERE_LOSS',True]).iloc[0]
            chosen.append(dict(r,category=category,case_id='RISK_'+token(route+'|'+policy+'|'+category)[:8].upper()))
        fig,axes=plt.subplots(5,len(chosen),figsize=(5.5*len(chosen),11),squeeze=False)
        for j,x in enumerate(chosen):
            src=source.loc[x['episode_id']].copy();src['episode_id']=x['episode_id'];p=stock_path(src,src.native_time);a=axes[:,j];age=p.age
            a[0].vlines(age,p.low,p.high,color='#b2bec3',lw=1);a[0].plot(age,p.close,color='#126782',label='native held path')
            a[0].plot(age,p.anchor,'--',color='#b5651d',label='registered anchor');a[0].plot(age,p.target,':',color='#6a4c93',label='entry-known target')
            a[0].scatter([0],[1],marker='>',color='black');a[0].scatter([src.exit_cal_idx-src.entry_cal_idx],[src.exit_price/src.entry_price],marker='x',color='#d1495b',label='native exit')
            if x['filled']:
                sx=x['exit_cal_idx_policy']-src.entry_cal_idx;sy=x['exit_price_policy']/src.entry_price
                a[0].scatter([sx],[sy],marker='s',color='#e9a23b',label='policy fill',s=28)
            a[0].set_ylim(.4,1.6);a[0].axhline(1,color='#aaa',lw=.6)
            a[0].set_title(f"{x['case_id']} | {x['category']}\nnative {x['native_return']:+.1%}; policy {x['policy_return']:+.1%}",fontsize=8)
            ins=a[0].inset_axes([.48,.06,.49,.31]);ins.plot(age,p.close,color='#126782');ins.set_xlim(0,20);ins.set_ylim(.4,1.6);ins.set_xticks([0,10,20]);ins.set_yticks([.5,1,1.5]);ins.tick_params(labelsize=5)
            for col,color in [('current_pnl','#126782'),('mae_sofar','#d1495b'),('mfe_sofar','#2a9d8f'),('giveback','#e9a23b')]:a[1].plot(age,p[col],color=color,label=col)
            a[1].set_ylim(-.6,.6);a[2].bar(age,p.volume_entry,color='#cad2c5');a[2].plot(age,p.volume_prior5,color='#52796f');a[2].set_ylim(0,5)
            for k,limit in [(3,(-.3,.3)),(4,(-.03,.03))]:
                a[k].set_ylim(*limit);a[k].text(.5,.5,'REGISTERED INPUT UNAVAILABLE',ha='center',transform=a[k].transAxes,fontsize=7)
            for k,ax in enumerate(a):
                ax.set_xlim(0,160);ax.axvline(1,color='#bbb',ls=':',lw=.5);ax.grid(alpha=.15)
                if j==0:ax.set_ylabel(['A price / entry','B excursions','C relative volume','D relative strength','E minute summary'][k])
                if k<2:ax.legend(fontsize=5,loc='upper right')
            a[4].set_xlabel('holding session | future explicitly visible')
            period='DISCOVERY' if src.entry_date<pd.Timestamp(PC['splits'][route][2]) else 'TEMPORAL_EVALUATION'
            x.update(route=route,policy=policy,period=period);selection.append(x)
            manifest.append(dict(route=route,period=period,case_id=x['case_id'],episode_id=x['episode_id'],category=x['category'],chart_type='FULL_PATH_POSTMORTEM_SIMPLE_RISK_COUNTEREXAMPLE',labels_visible=True,future_path_visible=True,observation_age=p.age.max(),native_return=x['native_return'],source_packet=str(folder/f'{route}_{policy}.png'),purpose='READ_ONLY_SIMPLE_RISK_REVIEW_AFTER_USER_PREFERENCE_UPDATE; NO_RULE_CHANGE',
                price_clipped_points=int((p.low.lt(.4)|p.high.gt(1.6)).sum()),age_clipped_points=int(p.age.gt(160).sum()),volume_clipped_points=int((p.volume_entry.gt(5)|p.volume_prior5.gt(5)).sum()),rs_clipped_points=0,minute_clipped_points=0))
        fig.suptitle(route+' | '+policy+' | FULL-PATH-POSTMORTEM\nConsumed history; baseline-funded counterfactual cases; inspect limitations only, no rule changes',fontsize=12)
        fig.tight_layout(rect=[0,0,1,.93]);fig.savefig(folder/f'{route}_{policy}.png',dpi=150);plt.close(fig)
    pd.DataFrame(selection).to_csv(HERE/'risk_policy_counterexample_cases.csv',index=False);pd.DataFrame(coverage).to_csv(HERE/'risk_policy_counterexample_coverage.csv',index=False)
    m=pd.read_csv(HERE/'visual_case_manifest.csv');m=m.loc[~m.chart_type.eq('FULL_PATH_POSTMORTEM_SIMPLE_RISK_COUNTEREXAMPLE')]
    pd.concat([m,pd.DataFrame(manifest)],ignore_index=True).to_csv(HERE/'visual_case_manifest.csv',index=False)
    log('SIMPLE_RISK_COUNTEREXAMPLES_RENDERED',cases=len(selection),rule_changes=0)
    print(pd.DataFrame(selection)[['route','policy','category','native_return','policy_return','case_id']].to_string(index=False))


if __name__=='__main__':run()
