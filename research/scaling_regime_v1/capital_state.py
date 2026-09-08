"""Exact calendar capital occupancy from independently reconciled root exposures."""
from collections import defaultdict
import json
import numpy as np
import pandas as pd
from .audit import HERE,write_json
from .accounts import folder,END
from .economics import cases,KEY,metadata,fills_frame
from .states import observable


def run():
    state=observable().set_index('state_as_of');rows=[];checks=[]
    for case in cases():
        if case[3]!='FULL_BOOK_NORMALIZATION' or case[2] not in ['NATIVE','G25','G50','G75','G100']:continue
        group='capital_timeline_native' if case[2]=='NATIVE' else 'capital_timeline_scaling'
        path=folder(*case[:5],group);base=folder(*case)
        receipt=json.loads((path/'capital_trace_receipt.json').read_text())
        assert receipt['all_baseline_artifacts_byte_identical']
        timeline=pd.read_parquet(path/'root_exposure_timeline.parquet').set_index('timestamp')
        account=json.loads((base/'account.json').read_text());meta=metadata(account,fills_frame(base))
        inherited={}
        for initial in account['initial_states'].values():
            for root,lot in initial.get('virtual_lots',{}).items():
                key=lot.get('root_event_id') or root
                inherited[key]=inherited.get(key,0.)+lot['quantity']*initial['marks'][lot['symbol']]
        assert np.isclose(sum(inherited.values()),sum(s['nav']-s['cash'] for s in account['initial_states'].values()))
        start=pd.Timestamp('2018-01-01');end=pd.Timestamp(END)+pd.Timedelta(days=1)
        clocks=timeline.index.union(state.index).union(pd.date_range(start,end,freq='YS')).union(pd.DatetimeIndex([start,end]))
        clocks=clocks[(clocks>=start)&(clocks<=end)].sort_values()
        exposures=timeline.root_exposure_json.reindex(clocks,method='ffill').fillna(json.dumps(inherited,sort_keys=True))
        states=state[['market_regime','breadth_bucket']].reindex(clocks,method='ffill')
        assert states.notna().all().all()
        sums=defaultdict(float);total=defaultdict(float)
        regimes=states.market_regime.to_numpy();breadths=states.breadth_bucket.to_numpy()
        for i in range(len(clocks)-1):
            when=clocks[i];elapsed=(clocks[i+1]-when).total_seconds()/86400
            for root,value in json.loads(exposures.iloc[i]).items():
                amount=value*elapsed;total[root]+=amount
                for family,bucket in [('market_regime',regimes[i]),('breadth_bucket',breadths[i])]:sums[(when.year,root,family,bucket)]+=amount
        expected=account['capital_days_by_event']
        errors=[abs(total.get(root,0)-value) for root,value in expected.items()]
        assert all(np.isclose(total.get(root,0),value,rtol=1e-11,atol=1e-5) for root,value in expected.items())
        for (year,root,family,bucket),value in sums.items():
            m=meta[root];route=m['route']
            if m['strategy']=='ATRDR':route='SLOW_BEAR' if 'SLOW' in root else 'FAST_BEAR' if 'V27' in root or 'FAST' in root else 'BULL'
            rows.append(dict(zip(KEY,case[:4]),year=year,root=root,strategy=m['strategy'],route=route,symbol=m['symbol'],state_family=family,state=bucket,capital_days=value))
        checks.append(dict(zip(KEY,case[:4]),root_count=len(expected),max_abs_difference=max(errors,default=0),total_capital_days=sum(total.values()),status='PASS'))
        print('CALENDAR_ROOT_CAPITAL_PASS',case[:4],flush=True)
    data=pd.DataFrame(rows);data.to_parquet(HERE/'cache/root_state_capital_days.parquet',index=False)
    agg=data.groupby(KEY+['year','strategy','route','state_family','state'],as_index=False).capital_days.sum()
    agg.to_csv(HERE/'output/state_route_capital_days.csv',index=False)
    pd.DataFrame(checks).to_csv(HERE/'output/root_capital_days_reconciliation.csv',index=False)
    annual=pd.read_csv(HERE/'output/annual_scaling_metrics.csv')
    bridge=data.loc[data.state_family.eq('market_regime')].groupby(KEY+['year'],as_index=False).capital_days.sum().merge(annual[KEY+['year','capital_days']],on=KEY+['year'],suffixes=('_root','_account'))
    assert np.allclose(bridge.capital_days_root,bridge.capital_days_account,atol=1e-4,rtol=1e-11)
    bridge.to_csv(HERE/'output/calendar_capital_days_bridge.csv',index=False)


if __name__=='__main__':run()


def portfolio_states():
    state=observable().set_index('state_as_of');rows=[]
    for case in cases():
        if case[3]!='FULL_BOOK_NORMALIZATION':continue
        timeline=pd.read_parquet(folder(*case)/'timeline.parquet').set_index('timestamp')
        start=pd.Timestamp('2018-01-01');end=pd.Timestamp(END)+pd.Timedelta(days=1)
        clocks=timeline.index.union(state.index).union(pd.date_range(start,end,freq='YS')).union(pd.DatetimeIndex([start,end]))
        clocks=clocks[(clocks>=start)&(clocks<=end)].sort_values()
        account=json.loads((folder(*case)/'account.json').read_text())
        opening_gross=sum(s['nav']-s['cash'] for s in account['initial_states'].values())
        exposure=timeline.gross_exposure.reindex(clocks,method='ffill').fillna(opening_gross)
        states=state[['market_regime','breadth_bucket']].reindex(clocks,method='ffill')
        duration=pd.Series(clocks,index=clocks).shift(-1)-pd.Series(clocks,index=clocks)
        frame=states.assign(capital_days=exposure*duration.dt.total_seconds()/86400,year=clocks.year).iloc[:-1]
        for family in ['market_regime','breadth_bucket']:
            grouped=frame.groupby(['year',family],as_index=False).capital_days.sum().rename(columns={family:'state'})
            grouped['state_family']=family
            for key,value in zip(KEY,case[:4]):grouped[key]=value
            rows.append(grouped)
    data=pd.concat(rows,ignore_index=True);data.to_csv(HERE/'output/portfolio_state_capital_days.csv',index=False)
    from .states import block
    data['block']=data.year.map(block)
    data=data.groupby(KEY+['block','state_family','state'],as_index=False).capital_days.sum()
    summaries=pd.read_csv(HERE/'output/state_conditioned_scaling_results.csv')
    native=data.loc[data.target.eq('NATIVE')].drop(columns=['target','mechanic']).rename(columns={'capital_days':'native_capital_days'})
    scaled=data.loc[data.target.ne('NATIVE')].merge(native,on=['gap','mcb_mode','block','state_family','state'],validate='many_to_one')
    scaled['capital_days']=scaled.capital_days-scaled.native_capital_days
    summaries=summaries.drop(columns=['capital_days']).merge(scaled[KEY+['block','state_family','state','capital_days']],on=KEY+['block','state_family','state'],validate='one_to_one')
    summaries['capital_days_basis']='Exact calendar occupancy; completed-timestamp exposure and state, including overnight/holiday/final carry'
    summaries.to_csv(HERE/'output/state_conditioned_scaling_results.csv',index=False)
