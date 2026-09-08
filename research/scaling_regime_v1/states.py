"""Frozen one-dimensional pre-trade states; actual incremental P&L counted once."""
import json
import numpy as np
import pandas as pd
from five_strategy_bundle.strategies import smv6
from .audit import HERE,ROLL,write_json
from .snapshot import CACHE
from .accounts import folder,END
from .economics import require_identity,cases,read,KEY


def observable():
    market=pd.read_parquet(CACHE/'atrdr/market.parquet').sort_values('latest_source_timestamp')
    anchor=smv6.load_daily(ROLL/'smv6','000852.SH').sort_index()
    idx=pd.DataFrame({'state_as_of':anchor.index+pd.Timedelta(hours=15),
        'index_realized_vol20_prior':anchor.pre_adj_close.pct_change(fill_method=None).rolling(20).std()*np.sqrt(252),
        'index_amount_prior':anchor.amount_cny}).reset_index(drop=True)
    data=market.rename(columns={'latest_source_timestamp':'state_as_of','trade_date':'state_trade_date'}).merge(idx,on='state_as_of',how='left',validate='one_to_one')
    data['breadth_bucket']=np.where(data.market_positive_ret20_share.ge(.5),'MAJORITY_POSITIVE_20D','MINORITY_POSITIVE_20D')
    return data.sort_values('state_as_of')


def block(year):return 'DISCOVERY' if year<=2021 else 'CONFIRMATION' if year<=2023 else 'ROLLFORWARD_DIAGNOSTIC'


def join_states(frame,state,clock):
    frame=frame.copy();state=state.copy()
    frame[clock]=pd.to_datetime(frame[clock]).astype('datetime64[ns]')
    state['state_as_of']=pd.to_datetime(state.state_as_of).astype('datetime64[ns]')
    joined=pd.merge_asof(frame.sort_values(clock),state,on=None,left_on=clock,right_on='state_as_of',direction='backward',allow_exact_matches=True)
    assert joined.market_regime.notna().all() and joined.state_as_of.le(joined[clock]).all()
    return joined


def run():
    require_identity();state=observable();decisions=[];days=[];event_details=[]
    for case in cases():
        if case[2]=='NATIVE' or case[3]!='FULL_BOOK_NORMALIZATION':continue
        path=folder(*case);identity=dict(zip(KEY,case[:4]));d,a,t,f=read(path)
        native_path=folder(case[0],case[1],'NATIVE','FULL_BOOK_NORMALIZATION',END)
        n,na,nt,nf=read(native_path)
        assert d.trade_date.equals(n.trade_date)
        daily=pd.DataFrame(dict(trade_date=d.trade_date,decision_at=d.trade_date+pd.Timedelta(hours=9,minutes=30),
            incremental_pnl=d.daily_pnl-n.daily_pnl,incremental_daily_return=d.daily_return-n.daily_return,
            incremental_capital_days=d.capital_days.diff().fillna(d.capital_days.iloc[0])-n.capital_days.diff().fillna(n.capital_days.iloc[0]),
            concentration=d.max_security_exposure/d.nav,gross_after=d.gross,
            current_account_drawdown=(1-d.nav/d.nav.cummax().clip(lower=a['initial_cash'])).shift(1,fill_value=0),
            gross_before=d.gross.shift(1,fill_value=sum(s['nav']-s['cash'] for s in a['initial_states'].values())/a['initial_cash'])))
        daily=join_states(daily,state,'decision_at');daily['year']=daily.trade_date.dt.year;daily['block']=daily.year.map(block)
        for key,value in identity.items():daily[key]=value
        days.append(daily)
        norms=pd.DataFrame(json.loads((path/'scaling.json').read_text())['normalizations'])
        norms['decision_at']=pd.to_datetime(norms.timestamp)
        norms=join_states(norms,state,'decision_at')
        before=t.copy();before['account_state_as_of']=pd.to_datetime(before.timestamp).astype('datetime64[ns]')
        before=before[['account_state_as_of','cash','nav','gross_exposure','max_security_exposure','ATRDR_exposure','MCB_exposure',case[0]+'_exposure','SMV6_exposure']].sort_values('account_state_as_of')
        initial=dict(account_state_as_of=pd.Timestamp('2018-01-01'),cash=sum(s['cash'] for s in a['initial_states'].values()),nav=a['initial_cash'],gross_exposure=sum(s['nav']-s['cash'] for s in a['initial_states'].values()),max_security_exposure=np.nan)
        for strategy,opening in a['initial_states'].items():initial[strategy+'_exposure']=opening['nav']-opening['cash']
        before=pd.concat([pd.DataFrame([initial]),before],ignore_index=True).sort_values('account_state_as_of')
        before['prior_peak']=before.nav.cummax().clip(lower=a['initial_cash'])
        norms=pd.merge_asof(norms.sort_values('decision_at'),before,left_on='decision_at',right_on='account_state_as_of',direction='backward',allow_exact_matches=False)
        assert norms.account_state_as_of.lt(norms.decision_at).all()
        norms['gross_before']=norms.gross_exposure/norms.nav
        norms['gross_after']=norms.actual_gross
        norms['current_account_drawdown']=1-norms.nav/norms.prior_peak
        norms['active_strategies']=norms.apply(lambda r:'|'.join(s for s in ['ATRDR','MCB',case[0],'SMV6'] if r[s+'_exposure']>1e-8),axis=1)
        holdings=[]
        for record in d.itertuples():
            lots=json.loads(record.lots_json)
            demand={lot.get('root_event_id') or key for key,lot in lots.items() if lot['strategy'] in ['ATRDR','MCB'] and lot['quantity']+(lot.get('pending_quantity') or 0.)>1e-8}
            routes={('SLOW_BEAR' if 'SLOW' in key else 'FAST_BEAR' if 'V27' in key else 'BULL') for key,lot in lots.items() if lot['strategy']=='ATRDR' and lot['quantity']+(lot.get('pending_quantity') or 0.)>1e-8}
            holdings.append(dict(active_Demand_as_of=record.trade_date+pd.Timedelta(hours=15,minutes=5),active_Demand_count=len(demand),ATRDR_route_composition='|'.join(sorted(routes))))
        initial_hold=dict(active_Demand_as_of=pd.Timestamp('2018-01-01'),active_Demand_count=sum(len(s.get('native_active',{})) for k,s in a['initial_states'].items() if k in ['ATRDR','MCB']),ATRDR_route_composition='REGISTERED_INITIAL_STATE')
        holdings=pd.DataFrame([initial_hold]+holdings).sort_values('active_Demand_as_of')
        norms=pd.merge_asof(norms.sort_values('decision_at'),holdings,left_on='decision_at',right_on='active_Demand_as_of',direction='backward',allow_exact_matches=False)
        signed=f.assign(signed=f.notional*np.where(f.side.eq('BUY'),1,-1)).groupby('timestamp').signed.sum()
        signed_native=nf.assign(signed=nf.notional*np.where(nf.side.eq('BUY'),1,-1)).groupby('timestamp').signed.sum()
        norms['incremental_scaling_notional']=norms.decision_at.map(signed).fillna(0)-norms.decision_at.map(signed_native).fillna(0)
        norms['dispersion']='NOT_REGISTERED_IN_PARENT'
        norms['volatility_bucket']='NO_REGISTERED_THRESHOLD_CONTINUOUS_ONLY'
        norms['account_DD_bucket']='NO_REGISTERED_THRESHOLD_CONTINUOUS_ONLY'
        for key,value in identity.items():norms[key]=value
        norms['trade_date']=norms.decision_at.dt.normalize();decisions.append(norms)
        # One disjoint daily increment for each root, with explicit absent-event
        # zero. This does not use entry-year or future success as a state feature.
        def roots(p):
            return pd.read_parquet(CACHE/'attribution'/('__'.join(p)+'.parquet'))[['trade_date','root','pnl']].groupby(['trade_date','root'],as_index=False).pnl.sum()
        scaled=roots(list(case[:4]));base=roots([case[0],case[1],'NATIVE','FULL_BOOK_NORMALIZATION'])
        event=scaled.merge(base,on=['trade_date','root'],how='outer',suffixes=('_scaled','_native')).fillna({'pnl_scaled':0.,'pnl_native':0.})
        event['incremental_pnl']=event.pnl_scaled-event.pnl_native
        event=event.merge(daily[['trade_date','market_regime','breadth_bucket','year','block']],on='trade_date',validate='many_to_one')
        for key,value in identity.items():event[key]=value
        event_details.append(event)
    days=pd.concat(days,ignore_index=True);decisions=pd.concat(decisions,ignore_index=True);events=pd.concat(event_details,ignore_index=True)
    days.to_csv(HERE/'output/scaling_daily_state_increment.csv',index=False)
    decisions.to_csv(HERE/'output/scaling_decision_state.csv',index=False)
    events.to_parquet(CACHE/'state_event_increments.parquet',index=False)
    summaries=[];blocks=[];qualifications=[];leave=[]
    for family in ['market_regime','breadth_bucket']:
        for key,group in days.groupby(KEY+[family],sort=True):
            identity=dict(zip(KEY,key[:4]));bucket=key[-1]
            ev=events.loc[(events[KEY]==pd.Series(identity)).all(axis=1) & events[family].eq(bucket)]
            dec=decisions.loc[(decisions[KEY]==pd.Series(identity)).all(axis=1) & decisions[family].eq(bucket)]
            for name,g in group.groupby('block'):
                e=ev.loc[ev.block.eq(name)].groupby('root').incremental_pnl.sum()
                count=int(dec.trade_date.isin(g.trade_date).sum())
                summaries.append(dict(**identity,state_family=family,state=bucket,block=name,decisions=count,independent_dates=g.trade_date.nunique(),
                    incremental_pnl=g.incremental_pnl.sum(),incremental_return_sum=g.incremental_daily_return.sum(),
                    incremental_pnl_path_max_drawdown=float((g.incremental_pnl.cumsum().cummax().clip(lower=0)-g.incremental_pnl.cumsum()).max()),
                    day_hit_rate=g.incremental_pnl.gt(0).mean(),capital_days=g.incremental_capital_days.sum(),average_concentration=g.concentration.mean(),
                    root_events=len(e),median_event_contribution=e.median(),mean_event_contribution=e.mean(),positive_event_fraction=e.gt(0).mean(),
                    top5_positive_event_pnl=e.nlargest(5).clip(lower=0).sum(),pnl_ex_top5_events=e.sum()-e.nlargest(5).clip(lower=0).sum(),annual_blocks='|'.join(map(str,sorted(g.year.unique()))),
                    evidence_grade='OBSERVATIONAL_INCREMENTAL_ACCOUNT_PNL;PATH_CAPITAL_AND_STATE_ASSOCIATION_NOT_CAUSAL_ROUTER_EFFECT'))
            for year,g in group.groupby('year'):
                blocks.append(dict(**identity,state_family=family,state=bucket,year=year,dates=len(g),incremental_pnl=g.incremental_pnl.sum(),mean_daily_incremental_return=g.incremental_daily_return.mean()))
            if identity['target']!='G25':continue
            hist=group.loc[group.year.le(2023)]
            e_hist=ev.loc[ev.year.le(2023)].groupby('root').incremental_pnl.sum()
            removed=set(e_hist.nlargest(5).loc[lambda x:x>0].index)
            directions=[]
            for year in range(2018,2024):
                g=hist.loc[hist.year.ne(year)]
                e=ev.loc[ev.year.le(2023)&ev.year.ne(year)&~ev.root.isin(removed)]
                pnl=g.incremental_pnl.sum();without=e.incremental_pnl.sum()
                leave.append(dict(**identity,state_family=family,state=bucket,omitted_year=year,independent_dates=len(g),incremental_pnl=pnl,pnl_ex_frozen_top5_events=without,direction_positive=pnl>0 and without>0))
                directions.append(pnl>0 and without>0)
            amounts=group.groupby('block').incremental_pnl.sum()
            d_ev=ev.loc[ev.block.eq('DISCOVERY')].groupby('root').incremental_pnl.sum()
            c_ev=ev.loc[ev.block.eq('CONFIRMATION')].groupby('root').incremental_pnl.sum()
            robust=d_ev.sum()-d_ev.nlargest(5).clip(lower=0).sum()>0 and c_ev.sum()-c_ev.nlargest(5).clip(lower=0).sum()>0
            date_robust=all((g.incremental_pnl.sum()-g.incremental_pnl.nlargest(5).clip(lower=0).sum())>0 for name,g in group.loc[group.block.isin(['DISCOVERY','CONFIRMATION'])].groupby('block'))
            returns_by_block=group.groupby('block').incremental_daily_return.mean()
            unit_return_positive=all(returns_by_block.get(b,0)>0 for b in ['DISCOVERY','CONFIRMATION','ROLLFORWARD_DIAGNOSTIC'])
            passed=unit_return_positive and date_robust and all(amounts.get(b,0)>0 for b in ['DISCOVERY','CONFIRMATION','ROLLFORWARD_DIAGNOSTIC']) and all(directions) and robust
            qualifications.append(dict(**identity,state_family=family,state=bucket,discovery_pnl=amounts.get('DISCOVERY',0),confirmation_pnl=amounts.get('CONFIRMATION',0),diagnostic_pnl=amounts.get('ROLLFORWARD_DIAGNOSTIC',0),
                all_blocks_unit_return_increment_positive=unit_return_positive,all_leave_year_directions_positive=all(directions),both_historical_blocks_positive_ex_top5=robust,both_historical_blocks_positive_ex_best5_dates=date_robust,
                numerical_stability_gate='PASS' if passed else 'FAIL',qualification='REQUIRES_ECONOMIC_AND_ACTIONABILITY_REVIEW' if passed else 'FAIL_STABILITY_OR_EVENT_CONCENTRATION'))
    pd.DataFrame(summaries).to_csv(HERE/'output/state_conditioned_scaling_results.csv',index=False)
    pd.DataFrame(blocks).to_csv(HERE/'output/state_annual_blocks.csv',index=False)
    pd.DataFrame(leave).to_csv(HERE/'output/scaling_regime_leave_year.csv',index=False)
    q=pd.DataFrame(qualifications);q.to_csv(HERE/'output/router_qualification.csv',index=False)
    write_json(HERE/'output/router_qualification_status.json',dict(status='NO_STABLE_SCALING_REGIME_ROUTER' if not q.numerical_stability_gate.eq('PASS').any() else 'NUMERICAL_STATE_CANDIDATE_REQUIRES_REVIEW',qualified_numeric_states=int(q.numerical_stability_gate.eq('PASS').sum()),router_run=False,thresholds_optimized=False,year_is_feature=False))
    print('STATE_ATTRIBUTION_COMPLETE',len(summaries),flush=True)


if __name__=='__main__':run()
