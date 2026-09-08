"""State, family, route and transition diagnostics; no policy or thresholds."""
import json
import numpy as np
import pandas as pd
from .audit import HERE
from .snapshot import CACHE
from .accounts import folder
from .economics import cases,KEY
from .states import observable,join_states


def run():
    days=pd.read_csv(HERE/'output/scaling_daily_state_increment.csv',parse_dates=['trade_date','decision_at','state_as_of'])
    events=pd.read_parquet(CACHE/'state_event_increments.parquet')
    meta=[]
    for case in cases():
        p=pd.read_parquet(CACHE/'attribution'/('__'.join(case[:4])+'.parquet'),columns=['root','strategy','route','symbol'])
        p['gap']=case[0];meta.append(p)
    meta=pd.concat(meta).drop_duplicates()
    assert not meta[['gap','root']].duplicated().any()
    events=events.merge(meta,on=['gap','root'],validate='many_to_one')
    events['family']=np.where(events.strategy.isin(['ATRDR','MCB']),'DEMAND',events.strategy)
    detail=[]
    for family in ['market_regime','breadth_bucket']:
        group=events.groupby(KEY+['year',family,'strategy','route'],as_index=False)[['pnl_scaled','pnl_native','incremental_pnl']].sum().rename(columns={family:'state'})
        group['state_family']=family;detail.append(group)
    detail=pd.concat(detail,ignore_index=True)
    detail.to_csv(HERE/'output/state_route_pnl.csv',index=False)
    group=detail.groupby(KEY+['year','state_family','state','strategy'],as_index=False)[['pnl_scaled','pnl_native','incremental_pnl']].sum()
    group['family']=np.where(group.strategy.isin(['ATRDR','MCB']),'DEMAND',group.strategy)
    families=group.groupby(KEY+['year','state_family','state','family'],as_index=False)[['pnl_scaled','pnl_native','incremental_pnl']].sum()
    families.to_csv(HERE/'output/state_family_pnl.csv',index=False)
    families.loc[families.family.eq('DEMAND')].to_csv(HERE/'output/demand_family_state_results.csv',index=False)
    families.loc[families.family.isin(['OGR','IFCGR'])].to_csv(HERE/'output/gap_family_state_results.csv',index=False)
    families.loc[families.family.eq('SMV6')].to_csv(HERE/'output/smv6_diversification_by_state.csv',index=False)
    detail.loc[detail.year.ne(2025)].sort_values('incremental_pnl').to_csv(HERE/'output/bad_scaling_state_anatomy.csv',index=False)
    detail.loc[detail.year.eq(2025)].sort_values('incremental_pnl',ascending=False).to_csv(HERE/'output/good_scaling_state_anatomy.csv',index=False)
    exposures=[];transitions=[];continuous=[]
    for case in cases():
        if case[2]=='NATIVE' or case[3]!='FULL_BOOK_NORMALIZATION':continue
        identity=dict(zip(KEY,case[:4]));subset=days.loc[(days[KEY]==pd.Series(identity)).all(axis=1)].sort_values('trade_date').reset_index(drop=True)
        d=pd.read_parquet(folder(*case)/'daily.parquet',columns=['trade_date','nav','cash','ATRDR_exposure','MCB_exposure',case[0]+'_exposure','SMV6_exposure','lots_json','marks_json'])
        for row in d.itertuples():
            lots=json.loads(row.lots_json);marks=json.loads(row.marks_json);routes={};symbols={};names={'ATRDR':set(),'MCB':set()}
            for key,lot in lots.items():
                value=(lot['quantity']+(lot.get('pending_quantity') or 0.))*marks[lot['symbol']]
                if lot['strategy'] in names and value>0:names[lot['strategy']].add(lot['symbol'])
                route=('SLOW_BEAR' if 'SLOW' in key else 'FAST_BEAR' if 'V27' in key or 'FAST' in key else 'BULL') if lot['strategy']=='ATRDR' else lot['route']
                routes[(lot['strategy'],route)]=routes.get((lot['strategy'],route),0)+value
                if lot['strategy'] in names:symbols[lot['symbol']]=symbols.get(lot['symbol'],0)+value
            context=dict(**identity,trade_date=row.trade_date,year=row.trade_date.year,Demand_gross=(row.ATRDR_exposure+row.MCB_exposure)/row.nav,overlap_names=len(names['ATRDR']&names['MCB']),Demand_max_single_name=max(symbols.values(),default=0)/row.nav,cash=row.cash)
            for (strategy,route),value in routes.items():exposures.append(dict(context,strategy=strategy,route=route,route_exposure=value/row.nav))
        for family in ['market_regime','breadth_bucket']:
            previous=subset[family].shift(1)
            changes=subset.index[(subset[family]!=previous)&previous.notna()]
            for i in changes:
                row=subset.iloc[i];result=dict(**identity,state_family=family,decision_at=row.decision_at,state_as_of=row.state_as_of,year=row.year,from_state=previous.iloc[i],to_state=row[family])
                for h in [1,3,5,10,20]:
                    result[f'forward_{h}d_incremental_pnl']=subset.incremental_pnl.iloc[i:i+h].sum() if i+h<=len(subset) else np.nan
                result['interpretation']='Overlapping forward diagnostics from observable morning state; not additive annual P&L'
                transitions.append(result)
        initial_account=json.loads((folder(*case)/'account.json').read_text())
        initial_demand=sum(s['nav']-s['cash'] for name,s in initial_account['initial_states'].items() if name in ['ATRDR','MCB'])/initial_account['initial_cash']
        subset['prior_Demand_gross']=((d.ATRDR_exposure+d.MCB_exposure)/d.nav).shift(1,fill_value=initial_demand).to_numpy()
        for name,part in subset.groupby('block'):
            for feature in ['index_realized_vol20_prior','index_amount_prior','current_account_drawdown','gross_before','prior_Demand_gross','market_positive_ret20_share']:
                observed=part[[feature,'incremental_pnl','incremental_daily_return']].dropna()
                continuous.append(dict(**identity,block=name,feature=feature,independent_dates=len(observed),spearman_incremental_pnl=observed[feature].corr(observed.incremental_pnl,method='spearman'),spearman_incremental_daily_return=observed[feature].corr(observed.incremental_daily_return,method='spearman'),basis='Continuous descriptive association only; no outcome-selected bins or policy'))
        # Volatility has no registered high/low threshold. Record its continuous
        # change alongside every day; no new volatility state is declared.
        subset['volatility_change']=subset.index_realized_vol20_prior.diff()
    exposure=pd.DataFrame(exposures).merge(days[KEY+['trade_date','market_regime','breadth_bucket']],on=KEY+['trade_date'],validate='many_to_one')
    exposure.to_parquet(CACHE/'daily_route_exposure.parquet',index=False)
    route=[]
    for family in ['market_regime','breadth_bucket']:
        r=exposure.groupby(KEY+['year',family,'strategy','route'],as_index=False).agg(mean_route_gross=('route_exposure','mean'),max_route_gross=('route_exposure','max'),mean_Demand_gross=('Demand_gross','mean'),max_Demand_gross=('Demand_gross','max'),max_Demand_single_name=('Demand_max_single_name','max'),max_overlap_names=('overlap_names','max')).rename(columns={family:'state'})
        r['state_family']=family;route.append(r)
    detail.merge(pd.concat(route),on=KEY+['year','state_family','state','strategy','route'],how='left').to_csv(HERE/'output/route_state_capital_effect.csv',index=False)
    transitions=pd.DataFrame(transitions);transitions.to_csv(HERE/'output/state_transitions.csv',index=False);transitions.to_csv(HERE/'output/state_transition_scaling_results.csv',index=False)
    transitions.groupby(KEY+['year','state_family','from_state','to_state'],as_index=False).agg(switch_count=('decision_at','size'),mean_forward_5d_incremental_pnl=('forward_5d_incremental_pnl','mean'),sum_overlapping_forward_5d_incremental_pnl=('forward_5d_incremental_pnl','sum'),mean_forward_20d_incremental_pnl=('forward_20d_incremental_pnl','mean')).to_csv(HERE/'output/state_transition_summary.csv',index=False)
    pd.DataFrame(continuous).to_csv(HERE/'output/continuous_state_associations.csv',index=False)
    q=pd.read_csv(HERE/'output/router_qualification.csv');q.to_csv(HERE/'output/router_candidate_evidence.csv',index=False)
    print('STATE_FAMILY_ROUTE_TRANSITIONS_COMPLETE',flush=True)


def rebalance_states():
    state=observable();pieces=[]
    for case in cases():
        if case[2]=='NATIVE' or case[3]!='FULL_BOOK_NORMALIZATION':continue
        d=pd.read_parquet(CACHE/'rebalance'/('__'.join(case[:4]))/'details.parquet')
        d['decision_at']=pd.to_datetime(d.timestamp);d=join_states(d,state,'decision_at');d['year']=d.decision_at.dt.year
        for family in ['market_regime','breadth_bucket']:
            g=d.groupby(KEY+['year',family,'strategy','category'],as_index=False).agg(actions=('timestamp','size'),notional=('delta_notional',lambda x:x.abs().sum()),fees=('fees','sum'),forward_5d_diagnostic=('forward_5d_pnl','sum'),forward_20d_diagnostic=('forward_20d_pnl','sum')).rename(columns={family:'state'})
            g['state_family']=family;g['interpretation']='Overlapping action horizons; BUY actual lot P&L, SELL signed-price counterfactual; never add to annual P&L';pieces.append(g)
    pd.concat(pieces).to_csv(HERE/'output/state_full_book_action_diagnostics.csv',index=False)


if __name__=='__main__':run();rebalance_states()
