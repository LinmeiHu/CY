"""Expose independent original signal dates and route/family tail amounts."""
import json
import numpy as np
import pandas as pd
from .audit import HERE
from .economics import cases,KEY,fills_frame
from .accounts import folder


def run():
    cache=HERE/'cache';out=HERE/'output';events=pd.read_parquet(cache/'state_event_increments.parquet');metadata=[]
    for case in cases():
        if case[2]=='NATIVE' or case[3]!='FULL_BOOK_NORMALIZATION':continue
        parts=[]
        for c in [case,(case[0],case[1],'NATIVE','FULL_BOOK_NORMALIZATION',case[4],case[5])]:
            f=fills_frame(folder(*c));f=f.loc[f.side.eq('BUY')]
            account=json.loads((folder(*c)/'account.json').read_text())
            inherited=[]
            for initial in account['initial_states'].values():
                for root,lot in initial.get('virtual_lots',{}).items():
                    inherited.append(dict(root=lot.get('root_event_id') or root,decision_at=lot['decision_at'],timestamp=lot['entry']))
            if inherited:f=pd.concat([f,pd.DataFrame(inherited)],ignore_index=True)
            f['original_signal_date']=pd.to_datetime(f.decision_at).dt.normalize()
            assert pd.to_datetime(f.decision_at).le(pd.to_datetime(f.timestamp)).all()
            m=pd.read_parquet(cache/'attribution'/('__'.join(c[:4])+'.parquet'),columns=['root','strategy','route','symbol']).drop_duplicates()
            m=m.merge(f.groupby('root',as_index=False).original_signal_date.min(),on='root',how='left',validate='one_to_one');parts.append(m)
        combined=pd.concat(parts).sort_values('original_signal_date').drop_duplicates('root')
        for key,value in zip(KEY,case[:4]):combined[key]=value
        metadata.append(combined)
    events=events.merge(pd.concat(metadata),on=KEY+['root'],validate='many_to_one');events['family']=np.where(events.strategy.isin(['ATRDR','MCB']),'DEMAND',events.strategy)
    sample=[];tails=[]
    for family in ['market_regime','breadth_bucket']:
        for key,g in events.groupby(KEY+['block',family]):
            sample.append(dict(zip(KEY+['block','state'],key),state_family=family,independent_original_signal_dates=g.original_signal_date.nunique(),roots_missing_signal_timestamp=g.loc[g.original_signal_date.isna(),'root'].nunique(),sample_basis='Original signal dates of contributing roots; includes carried roots signalled before the evaluation block; daily P&L observation dates reported separately'))
        for dimension in ['route','family']:
            grouping=KEY+['year',family]+(['strategy','route'] if dimension=='route' else ['family'])
            daily=events.groupby(grouping+['trade_date'],as_index=False).incremental_pnl.sum()
            for key,g in daily.groupby(grouping):
                s=g.sort_values('trade_date').incremental_pnl;cum=s.cumsum();peak=cum.cummax().clip(lower=0)
                row=dict(zip(grouping,key));row['state']=row.pop(family);row['state_family']=family
                row.update(dimension=dimension,incremental_pnl_path_drawdown_cny=(peak-cum).max(),worst_5pct_daily_incremental_pnl=s.nsmallest(max(1,int(np.ceil(len(s)*.05)))).sum(),daily_observations=len(s),tail_basis='Disjoint daily actual scaling-minus-native P&L in this state; currency path drawdown is not additive portfolio MaxDD percent')
                tails.append(row)
    summary=pd.read_csv(out/'state_conditioned_scaling_results.csv')
    added=pd.DataFrame(sample);existing=[c for c in added if c not in KEY+['block','state','state_family'] and c in summary]
    summary=summary.drop(columns=existing).merge(added,on=KEY+['block','state_family','state'],validate='one_to_one')
    summary.to_csv(out/'state_conditioned_scaling_results.csv',index=False)
    pd.DataFrame(tails).to_csv(out/'state_route_family_tail_amounts.csv',index=False)
    print('SIGNAL_DATE_AND_TAIL_DISCLOSURES_COMPLETE',flush=True)


if __name__=='__main__':run()
