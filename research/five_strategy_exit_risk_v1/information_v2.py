"""Predeclared, event-weighted, purged expanding-year research probes."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor
from state_v2 import BASE, EXTRA, HERE, write_json


def event_weights(d):
    return (1/d.groupby('episode_id').episode_id.transform('size')).to_numpy()


def purged_split(d, year):
    start=pd.Timestamp(f'{year}-01-01')
    test=d.loc[pd.to_datetime(d.entry_date).dt.year.eq(year)].copy()
    train=d.loc[pd.to_datetime(d.entry_date).lt(start)&pd.to_datetime(d.label_available_at).lt(start)].copy()
    train=train.loc[~train.episode_id.isin(test.episode_id)&~train.event_cluster.isin(test.event_cluster)]
    assert not set(train.episode_id)&set(test.episode_id)
    assert not set(train.event_cluster)&set(test.event_cluster)
    assert pd.to_datetime(train.label_available_at).lt(start).all()
    return train,test


def preprocess(train, test, columns):
    x=train[columns].replace([np.inf,-np.inf],np.nan)
    applicable=x.notna().any()
    median=x.median().fillna(0)
    x=x.fillna(median); z=test[columns].replace([np.inf,-np.inf],np.nan).fillna(median)
    weights=event_weights(train)
    mean=np.average(x,axis=0,weights=weights)
    scale=np.sqrt(np.average((x-mean)**2,axis=0,weights=weights));scale=np.where(scale>1e-12,scale,1)
    observed=[c for c in columns if applicable[c]]
    domain=(z[observed].lt(x[observed].min())|z[observed].gt(x[observed].max())).any(axis=1)
    unexpected_missing=test[observed].replace([np.inf,-np.inf],np.nan).isna().any(axis=1)
    return (x.to_numpy()-mean)/scale,(z.to_numpy()-mean)/scale,weights,domain,dict(median=median.to_dict(),mean=dict(zip(columns,mean)),scale=dict(zip(columns,scale)),
            not_applicable_columns=[c for c in columns if not applicable[c]],unexpected_missing_fraction=float(unexpected_missing.mean()))


def probe(states, config):
    ext=Path(config['external_root']);contract=json.loads((HERE/'research_contract.json').read_text())
    rows=[];predictions=[];splits=[];preprocessors=[];negative=[]
    # Explicit future-label allowlist boundary: never choose features by numeric dtype.
    d=states.loc[states.label_status.eq('MATURE')&states.state_valid.astype(bool)&states.exit_advantage_normalized.notna()].copy()
    d=d.loc[pd.to_datetime(d.data_available_at).le(pd.to_datetime(d.decision_at))]
    for route,group in d.groupby('route',sort=True):
        if route=='IFCGR': continue
        begin,discovery_end,eval_start,end=contract['splits'][route]
        group=group.loc[pd.to_datetime(group.entry_date).between(begin,end)]
        firstyear=max(int(begin[:4])+2,int(pd.to_datetime(group.entry_date).dt.year.min())+1)
        for year in range(firstyear,2024):
            train,test=purged_split(group,year)
            boundary_excluded=0
            if year<=int(discovery_end[:4]):
                usable=pd.to_datetime(test.label_available_at).lt(pd.Timestamp(eval_start))
                boundary_excluded=int((~usable).sum());test=test.loc[usable]
            split=dict(route=route,year=year,train_states=len(train),test_states=len(test),train_events=train.episode_id.nunique(),test_events=test.episode_id.nunique(),
                       train_last_label=train.label_available_at.max(),test_first_entry=test.entry_date.min(),episode_overlap=0,event_cluster_overlap=0,
                       train_signal_dates=train.signal_date.nunique(),test_signal_dates=test.signal_date.nunique(),discovery_boundary_excluded_states=boundary_excluded)
            if train.episode_id.nunique()<20 or test.episode_id.nunique()<5:
                splits.append(dict(split,status='INSUFFICIENT_EVENTS'));continue
            splits.append(dict(split,status='PURGED_FORWARD_SPLIT'))
            phase='DISCOVERY_FORWARD' if year<=int(discovery_end[:4]) else 'CONSUMED_HISTORY_TEMPORAL_CHECK'
            specs=[('B0','ridge',BASE),('B1','ridge',BASE+EXTRA)]
            if train.episode_id.nunique()>=100:
                specs += [('B2_PRICE','tree',BASE),('B2_EXTENDED','tree',BASE+EXTRA)]
            # Matched samples and same model capacity in ablation comparisons.
            specs += [('B1_NO_STRUCTURE','ridge',BASE+EXTRA[2:]),('B1_NO_VOLUME','ridge',BASE+[c for c in EXTRA if c!='down_volume_ratio'])]
            specs += [('B1_PRICE_AUGMENT_ONLY','ridge',BASE+['close_location','recovery_3'])]
            for name,kind,columns in specs:
                x,z,w,domain,prep=preprocess(train,test,columns)
                y=train.exit_advantage_normalized.to_numpy()
                model=Ridge(alpha=10) if kind=='ridge' else DecisionTreeRegressor(max_depth=2,min_samples_leaf=max(40,round(len(train)*10/train.episode_id.nunique())),random_state=1729)
                model.fit(x,y,sample_weight=w);yp=model.predict(z)
                wt=event_weights(test);truth=test.exit_advantage_normalized.to_numpy()
                mse=np.average((yp-truth)**2,weights=wt)
                # Bins use predictions only; realized label never controls membership.
                ranks=pd.Series(yp).rank(method='average',pct=True).to_numpy()
                top=yp>=np.quantile(yp,.8)  # keep tied scores together, including a constant tree
                row=dict(route=route,year=year,phase=phase,model=name,states=len(test),events=test.episode_id.nunique(),signal_dates=test.signal_date.nunique(),
                         weighted_mse=mse,weighted_bias=np.average(yp-truth,weights=wt),mean_predicted=np.average(yp,weights=wt),
                         mean_realized=np.average(truth,weights=wt),top_mean_predicted=np.average(yp[top],weights=wt[top]),
                         top_mean_realized=np.average(truth[top],weights=wt[top]),top_events=test.loc[top,'episode_id'].nunique(),
                         top_signal_dates=test.loc[top,'signal_date'].nunique(),top_tail=float(pd.Series(truth[top]).quantile(.05)),
                         domain_out_fraction=float(np.average(domain,weights=wt)),n_features=len(columns),
                         not_applicable_columns='|'.join(prep['not_applicable_columns']),unexpected_missing_fraction=prep['unexpected_missing_fraction'])
                rows.append(row);preprocessors.append(dict(route=route,year=year,model=name,trained_through=str(pd.Timestamp(f'{year}-01-01')-pd.Timedelta(seconds=1)),**prep))
                if name in ['B0','B1','B2_PRICE','B2_EXTENDED']:
                    p=test[['route','episode_id','event_cluster','entry_date','signal_date','decision_at','label_available_at','exit_advantage_normalized']].copy()
                    p['year']=year;p['phase']=phase;p['model']=name;p['prediction']=yp;p['prediction_bin']=np.minimum(4,(ranks*5).astype(int));p['event_weight']=wt;p['out_of_domain']=domain.to_numpy()
                    predictions.append(p)
            # One family of date-dependent label control, discovery only, never used to pick rules.
            if year==int(discovery_end[:4]):
                x,z,w,_,_=preprocess(train,test,BASE+EXTRA)
                event=train.groupby(['signal_date','episode_id']).exit_advantage_normalized.mean().sort_index()
                # Preserve entire signal-date groups and within-event rows under a one-date block rotation.
                date_means=event.groupby(level=0).mean();rolled={}
                for _,values in date_means.groupby(pd.to_datetime(date_means.index).year):
                    rolled.update(zip(values.index,np.roll(values.to_numpy(),1)))
                control=train.signal_date.map(rolled).to_numpy()
                model=Ridge(alpha=10).fit(x,control,sample_weight=w);yp=model.predict(z)
                negative.append(dict(route=route,year=year,control='ONE_SIGNAL_DATE_BLOCK_ROTATION',weighted_mse=np.average((yp-test.exit_advantage_normalized.to_numpy())**2,weights=event_weights(test)),events=test.episode_id.nunique()))
    result=pd.DataFrame(rows)
    if len(result):
        reference=result.loc[result.model.eq('B0'),['route','year','weighted_mse']].rename(columns={'weighted_mse':'b0_mse'})
        result=result.merge(reference,on=['route','year'],validate='many_to_one');result['mse_improvement_over_b0']=result.b0_mse-result.weighted_mse
    result.to_csv(HERE/'incremental_information.csv',index=False)
    pd.DataFrame(splits).to_csv(HERE/'temporal_split_audit.csv',index=False)
    pd.DataFrame(negative).to_csv(HERE/'label_negative_control.csv',index=False)
    write_json(ext/'model_preprocessing.json',preprocessors)
    if predictions:
        pred=pd.concat(predictions,ignore_index=True);pred.to_parquet(ext/'out_of_training_predictions.parquet',index=False)
        calibration=[]
        for key,g in pred.groupby(['route','phase','model','prediction_bin']):
            calibration.append(dict(zip(['route','phase','model','bin'],key),states=len(g),events=g.episode_id.nunique(),signal_dates=g.signal_date.nunique(),
                                    predicted=np.average(g.prediction,weights=g.event_weight),realized=np.average(g.exit_advantage_normalized,weights=g.event_weight)))
        pd.DataFrame(calibration).to_csv(HERE/'prediction_calibration.csv',index=False)
    return result
