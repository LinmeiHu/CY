"""Attach exact occupancy, family overlap and additive tail evidence."""
import numpy as np
import pandas as pd
from .audit import HERE
from .economics import KEY
from .states import observable,join_states


def run():
    out=HERE/'output';cache=HERE/'cache'
    route=pd.read_csv(out/'route_state_capital_effect.csv');capital=pd.read_csv(out/'state_route_capital_days.csv')
    native=capital.loc[capital.target.eq('NATIVE')].drop(columns=['target','mechanic']).rename(columns={'capital_days':'native_capital_days'})
    keys=['gap','mcb_mode','year','strategy','route','state_family','state']
    capital=capital.merge(native,on=keys,how='outer',validate='many_to_one')
    capital[['capital_days','native_capital_days']]=capital[['capital_days','native_capital_days']].fillna(0.)
    capital['incremental_capital_days']=capital.capital_days-capital.native_capital_days
    route=route.drop(columns=[c for c in ['capital_days','native_capital_days','incremental_capital_days','capital_trace_scope'] if c in route])
    route=route.merge(capital[KEY+['year','strategy','route','state_family','state','capital_days','native_capital_days','incremental_capital_days']],on=KEY+['year','strategy','route','state_family','state'],how='left',validate='one_to_one')
    route[['capital_days','native_capital_days','incremental_capital_days']]=route[['capital_days','native_capital_days','incremental_capital_days']].fillna(0.)
    route['capital_trace_scope']='ACTUAL_ROOT_CALENDAR_TRACE'
    route.to_csv(out/'route_state_capital_effect.csv',index=False)
    daily=pd.read_parquet(cache/'daily_route_exposure.parquet').drop_duplicates(KEY+['trade_date'])
    context=[]
    for family in ['market_regime','breadth_bucket']:
        g=daily.groupby(KEY+['year',family],as_index=False).agg(average_Demand_gross=('Demand_gross','mean'),max_Demand_gross=('Demand_gross','max'),mean_overlap_names=('overlap_names','mean'),max_overlap_names=('overlap_names','max'),max_Demand_single_name=('Demand_max_single_name','max')).rename(columns={family:'state'})
        g['state_family']=family;context.append(g)
    demand=pd.read_csv(out/'demand_family_state_results.csv')
    demand=demand.drop(columns=[c for c in ['average_Demand_gross','max_Demand_gross','mean_overlap_names','max_overlap_names','max_Demand_single_name'] if c in demand])
    demand=demand.merge(pd.concat(context),on=KEY+['year','state_family','state'],how='left',validate='one_to_one')
    demand.to_csv(out/'demand_family_state_results.csv',index=False)
    dd=pd.read_csv(out/'yearly_drawdown_attribution.csv',parse_dates=['peak','trough'])
    components=pd.read_csv(out/'yearly_drawdown_components.csv')
    smv=components.loc[components.dimension.eq('strategy')&components.name.eq('SMV6')].copy()
    smv['effect_in_actual_drawdown']=np.where(smv.pnl.gt(0),'OFFSETS_ACTUAL_WINDOW_LOSS',np.where(smv.pnl.lt(0),'ADDS_ACTUAL_WINDOW_LOSS','NEUTRAL'))
    smv.to_csv(out/'smv6_drawdown_diversification.csv',index=False)
    dd['decision_at']=dd.peak+pd.Timedelta(days=1,hours=9,minutes=30)
    contexts=join_states(dd,observable(),'decision_at')
    transitions=pd.read_csv(out/'state_transitions.csv',parse_dates=['decision_at'])
    bridge=[]
    for row in contexts.itertuples():
        subset=transitions.loc[(transitions[KEY]==pd.Series(dict(zip(KEY,[getattr(row,k) for k in KEY])))).all(axis=1)&transitions.decision_at.gt(row.peak)&transitions.decision_at.le(row.trough+pd.Timedelta(days=1))]
        bridge.append(dict(zip(KEY,[getattr(row,k) for k in KEY]),year=row.year,scope=row.scope,peak=row.peak,trough=row.trough,market_state_after_peak=row.market_regime,breadth_after_peak=row.breadth_bucket,volatility_after_peak=row.index_realized_vol20_prior,state_source=row.state_as_of,market_transition_count=int(subset.state_family.eq('market_regime').sum()),breadth_transition_count=int(subset.state_family.eq('breadth_bucket').sum()),incremental_scaling_pnl=row.incremental_scaling_pnl))
    pd.DataFrame(bridge).to_csv(out/'drawdown_state_transitions.csv',index=False)
    print('FINAL_DETAIL_BRIDGES_COMPLETE',flush=True)


if __name__=='__main__':run()
