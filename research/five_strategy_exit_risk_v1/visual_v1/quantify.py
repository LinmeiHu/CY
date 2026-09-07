"""Frozen visual representations tested against price-path controls, no exit rules."""
from packets import *
from information_v2 import event_weights, purged_split, preprocess
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor

MOTIFS={
    'ATRDR_FAST_BEAR':('VM_FAST_RECOVERY',['close_location_mean3','recovery_3']),
    'ATRDR_SLOW_BEAR':('VM_SLOW_VOLUME',['close_location_mean3','recovery_3','down_volume_mean3']),
    'MCB':('VM_MCB_CLOSE',['close_location_mean3','recovery_3']),
    'OGR':('VM_OGR_RECOVERY',['close_location_mean3','recovery_3'])}


def representations(states):
    parts=[]
    for _,g in states.groupby('episode_id',sort=False):
        g=g.sort_values('decision_at').copy()
        consecutive=g.age.diff().eq(1).rolling(2,min_periods=2).sum().eq(2)
        valid=g.state_valid.fillna(False)&(pd.to_datetime(g.data_available_at)<=pd.to_datetime(g.decision_at))
        for source,target in [('close_location','close_location_mean3'),('down_volume_ratio','down_volume_mean3')]:
            g[target]=g[source].where(valid).rolling(3,min_periods=3).mean().where(consecutive)
        parts.append(g)
    return pd.concat(parts,ignore_index=True)


def check_freeze():
    f=json.loads((HERE/'visual_hypothesis_freeze.json').read_text())
    for path,h in f['files'].items():
        if digest(HERE/path)!=h:raise RuntimeError('Frozen visual hypothesis/code changed: '+path)
    return f


def paired_bootstrap(frame,reference,model):
    # Month blocks preserve same-calendar episode dependence; descriptive consumed-history CI.
    d=frame[['signal_date','event_weight',reference,model]].copy()
    d['month']=pd.to_datetime(d.signal_date).dt.to_period('M').astype(str)
    d['gain']=d.event_weight*(d[reference]-d[model])
    m=d.groupby('month').agg(gain=('gain','sum'),weight=('event_weight','sum'))
    if len(m)<5:return [np.nan,np.nan]
    rng=np.random.default_rng(1729);idx=rng.integers(0,len(m),(1000,len(m)))
    boot=m.gain.to_numpy()[idx].sum(axis=1)/m.weight.to_numpy()[idx].sum(axis=1)
    return np.quantile(boot,[.025,.975]).tolist()


def run():
    frozen=check_freeze()
    log('FIRST_NEW_TEMPORAL_STATE_READ_AFTER_FREEZE',freeze_sha256=digest(HERE/'visual_hypothesis_freeze.json'))
    # SQL cutoff precedes fetch. No 2024+, no native producer or existing result rewritten.
    raw=read_bound(OLD/'position_state_snapshots.parquet',"route IN ('ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','MCB','OGR') AND entry_date>=CASE WHEN route='OGR' THEN DATE '2018-01-01' ELSE DATE '2014-01-01' END AND decision_at<DATE '2024-01-01' AND entry_date<DATE '2024-01-01'")
    states=representations(raw)
    states.to_parquet(OUT/'visual_quant_states.parquet',index=False)
    eligible=states.loc[states.label_status.eq('MATURE')&states.state_valid&states.exit_advantage_normalized.notna()&pd.to_datetime(states.data_available_at).le(pd.to_datetime(states.decision_at))&pd.to_datetime(states.label_available_at).lt('2024-01-01')]
    folds=[];pred=[];preps=[];availability=[];neg=[]
    for route,(motif,extra) in MOTIFS.items():
        g=eligible.loc[eligible.route.eq(route)].copy();begin,discovery_end,eval_start,end=PC['splits'][route]
        for phase,bound in [('DISCOVERY',g.entry_date.lt(eval_start)&g.label_available_at.lt(eval_start)),('CONSUMED_TEMPORAL',g.entry_date.ge(eval_start))]:
            z=g.loc[bound];availability.append(dict(route=route,phase=phase,states=len(z),events=z.episode_id.nunique(),representations='|'.join(extra),complete_state_fraction=z[extra].notna().all(axis=1).mean()))
        first=max(int(begin[:4])+2,int(pd.to_datetime(g.entry_date).dt.year.min())+1)
        for year in range(first,2024):
            train,test=purged_split(g,year)
            phase='DISCOVERY' if year<=int(discovery_end[:4]) else 'CONSUMED_TEMPORAL'
            if phase=='DISCOVERY':test=test.loc[test.label_available_at.lt(eval_start)]
            info=dict(route=route,year=year,phase=phase,train_events=train.episode_id.nunique(),test_events=test.episode_id.nunique(),train_last_label=train.label_available_at.max(),overlap_episode=0,overlap_cluster=0)
            if train.episode_id.nunique()<20 or test.episode_id.nunique()<5:
                folds.append(dict(info,status='INSUFFICIENT_EVENTS'));continue
            folds.append(dict(info,status='PURGED_FORWARD'))
            spec=[('B0','ridge',BASE),('PRICE_AUGMENT','ridge',BASE+['close_location','recovery_3']),('B1_INCUMBENT','ridge',BASE+EXTRA),('VISUAL','ridge',BASE+extra)]
            if route=='ATRDR_SLOW_BEAR':spec.append(('MATCHED_PRICE_CONTROL','ridge',BASE+['close_location_mean3','recovery_3']))
            if train.episode_id.nunique()>=100:spec += [('TREE_B0','tree',BASE),('TREE_VISUAL','tree',BASE+extra)]
            for name,kind,cols in spec:
                x,z,w,domain,prep=preprocess(train,test,cols)
                model=Ridge(alpha=10) if kind=='ridge' else DecisionTreeRegressor(max_depth=2,min_samples_leaf=max(40,round(len(train)*10/train.episode_id.nunique())),random_state=1729)
                model.fit(x,train.exit_advantage_normalized.to_numpy(),sample_weight=w);yp=model.predict(z)
                p=test[['route','episode_id','event_cluster','signal_date','entry_date','decision_at','exit_advantage_normalized']].copy()
                p['year']=year;p['phase']=phase;p['model']=name;p['motif']=motif;p['prediction']=yp;p['squared_error']=(yp-test.exit_advantage_normalized.to_numpy())**2
                p['event_weight']=event_weights(test);p['top_quintile']=yp>=np.quantile(yp,.8);p['out_of_domain']=domain.to_numpy();p['representations_complete']=test[extra].notna().all(axis=1).to_numpy()
                pred.append(p);preps.append(dict(route=route,year=year,model=name,columns=cols,coefficients=model.coef_.tolist() if kind=='ridge' else None,**prep))
                if name=='VISUAL' and phase=='DISCOVERY' and year==int(discovery_end[:4]):
                    means=train.groupby(['signal_date','episode_id']).exit_advantage_normalized.mean().groupby(level=0).mean();rotation={}
                    for _,values in means.groupby(pd.to_datetime(means.index).year):rotation.update(zip(values.index,np.roll(values.to_numpy(),1)))
                    control=Ridge(alpha=10).fit(x,train.signal_date.map(rotation).to_numpy(),sample_weight=w).predict(z)
                    neg.append(dict(route=route,year=year,control='ONE_SIGNAL_DATE_BLOCK_ROTATION',weighted_mse=np.average((control-test.exit_advantage_normalized.to_numpy())**2,weights=event_weights(test))))
    pred=pd.concat(pred,ignore_index=True);pred.to_parquet(OUT/'visual_predictions.parquet',index=False)
    pd.DataFrame(folds).to_csv(HERE/'visual_temporal_split_audit.csv',index=False)
    pd.DataFrame(availability).to_csv(HERE/'visual_feature_coverage.csv',index=False)
    pd.DataFrame(neg).to_csv(HERE/'visual_negative_control.csv',index=False)
    write_json(OUT/'visual_preprocessing.json',preps)
    metrics=[]
    for (route,phase,model),p in pred.groupby(['route','phase','model']):
        top=p.loc[p.top_quintile]
        metrics.append(dict(route=route,phase=phase,model=model,events=p.episode_id.nunique(),states=len(p),weighted_mse=np.average(p.squared_error,weights=p.event_weight),
            top_advantage=np.average(top.exit_advantage_normalized,weights=top.event_weight),top_events=top.episode_id.nunique(),top_signal_dates=top.signal_date.nunique(),
            out_of_domain_fraction=np.average(p.out_of_domain,weights=p.event_weight),complete_fraction=np.average(p.representations_complete,weights=p.event_weight)))
    metrics=pd.DataFrame(metrics);metrics.to_csv(HERE/'visual_incremental_information.csv',index=False)
    sensitivity=[];results=[]
    for (route,phase),p in pred.groupby(['route','phase']):
        pivot=p.pivot(index=['episode_id','decision_at','signal_date','event_weight'],columns='model',values='squared_error').reset_index()
        ref='MATCHED_PRICE_CONTROL' if route=='ATRDR_SLOW_BEAR' else 'PRICE_AUGMENT'
        if pivot[['B0',ref,'VISUAL']].isna().any().any():raise RuntimeError('Comparisons not on matched states')
        contributions=(pivot.event_weight*(pivot[ref]-pivot.VISUAL)).groupby(pivot.signal_date).sum().sort_values(ascending=False)
        for removed in [0,1,5]:
            q=pivot.loc[~pivot.signal_date.isin(contributions.head(removed).index)]
            sensitivity.append(dict(route=route,phase=phase,removed_top_signal_dates=removed,reference=ref,
                gain_over_b0=np.average(q.B0-q.VISUAL,weights=q.event_weight),gain_over_price=np.average(q[ref]-q.VISUAL,weights=q.event_weight),
                events=q.episode_id.nunique(),signal_dates=q.signal_date.nunique()))
        m=metrics.loc[metrics.route.eq(route)&metrics.phase.eq(phase)].set_index('model')
        gain_b0=m.loc['B0','weighted_mse']-m.loc['VISUAL','weighted_mse'];gain_price=m.loc[ref,'weighted_mse']-m.loc['VISUAL','weighted_mse']
        s=sensitivity[-1];top=m.loc['VISUAL'];ci=paired_bootstrap(pivot,ref,'VISUAL')
        passed=bool(gain_b0>0 and gain_price>0 and top.top_advantage>0 and top.top_events>=20 and top.top_signal_dates>=5 and s['gain_over_b0']>0 and s['gain_over_price']>0)
        results.append(dict(route=route,phase=phase,motif=MOTIFS[route][0],price_reference=ref,mse_gain_b0=gain_b0,mse_gain_price=gain_price,
            paired_month_ci_low=ci[0],paired_month_ci_high=ci[1],top_advantage=top.top_advantage,top_events=int(top.top_events),top_signal_dates=int(top.top_signal_dates),
            gain_price_after_top5_removed=s['gain_over_price'],phase_gate='PASS' if passed else 'FAIL',evidence='CONSUMED_HISTORY_NOT_BLIND_VALIDATION'))
    pd.DataFrame(sensitivity).to_csv(HERE/'visual_date_sensitivity.csv',index=False)
    results=pd.DataFrame(results);results.to_csv(HERE/'visual_admission.csv',index=False)
    log('FROZEN_QUANTITATIVE_TEST_COMPLETED',prediction_sha256=digest(OUT/'visual_predictions.parquet'),candidates=int(results.groupby('route').phase_gate.apply(lambda x:x.eq('PASS').all()).sum()))
    print(results.to_string(index=False))


if __name__=='__main__':run()
