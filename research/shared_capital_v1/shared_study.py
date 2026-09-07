"""Exactly the frozen 48 scenario-period executions, gated by native P0."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from .common_p0_v06 import load_inputs,replay,PERIODS,HERE

OUT=HERE/'output'
POLICIES=['P0','P1','P2','P3_D4','P3_D5','P3_D6']


def metrics(account,daily,start,end,intents,base_ids):
    nav=daily.nav.astype(float); initial=account.initial_cash
    returns=nav.pct_change();returns.iloc[0]=nav.iloc[0]/initial-1
    high=nav.cummax().clip(lower=initial);dd=1-nav/high
    trough=int(dd.to_numpy().argmax());peak=float(high.iloc[trough])
    before=np.flatnonzero(nav.iloc[:trough+1].to_numpy()>=peak-1e-9)
    peak_day=daily.trade_date.iloc[int(before[-1])] if len(before) else pd.Timestamp(start)
    after=np.flatnonzero(nav.iloc[trough+1:].to_numpy()>=peak-1e-9)
    recovery=daily.trade_date.iloc[trough+1+int(after[0])] if len(after) else None
    longest=0;begin=None
    for day,loss in zip(daily.trade_date,dd):
        if loss>1e-12 and begin is None:begin=day
        if begin is not None:longest=max(longest,(day-begin).days)
        if loss<=1e-12:begin=None
    exposure=daily.gross_exposure/nav
    buys={f['event_id']:f for f in account.fills if f['side']=='BUY'}
    shared_ids={eid for eid,f in buys.items() if f['funding_type']=='SHARED' and eid not in base_ids}
    final_pnl=json.loads(daily.root_pnl_json.iloc[-1])
    net=float(nav.iloc[-1]-initial);capital_days=sum(account.capital_days_by_event.values())
    years=(pd.Timestamp(end)+pd.Timedelta(days=1)-pd.Timestamp(start)).days/365.25
    calendar=pd.Series(returns.to_numpy(),index=pd.DatetimeIndex(daily.trade_date))
    monthly=(1+calendar).resample('ME').prod()-1
    quarters=(1+calendar).resample('QE').prod()-1
    annual=(1+calendar).resample('YE').prod()-1
    r=dict(initial_nav=initial,final_nav=float(nav.iloc[-1]),total_return=float(nav.iloc[-1]/initial-1),CAGR=float((nav.iloc[-1]/initial)**(1/years)-1),
        annual_return=json.dumps({str(k.year):v for k,v in annual.items()}),Sharpe=float(returns.mean()/returns.std(ddof=1)*np.sqrt(252)) if returns.std(ddof=1)>0 else 0.,
        gross_pnl=net+account.fees,fees=account.fees,net_pnl=net,MaxDD=float(dd.max()),drawdown_start=peak_day,drawdown_trough=daily.trade_date.iloc[trough],drawdown_recovery=recovery,longest_drawdown_days=longest,
        worst_portfolio_day=float(returns.min()),CVaR5=float(returns.nsmallest(max(1,int(np.ceil(len(returns)*.05)))).mean()),worst_21_day=float(np.expm1(np.log1p(returns).rolling(21).sum()).min()),worst_63_day=float(np.expm1(np.log1p(returns).rolling(63).sum()).min()),worst_month=float(monthly.min()),worst_quarter=float(quarters.min()),
        average_gross_exposure=float(exposure.mean()),median_exposure=float(exposure.median()),p90_exposure=float(exposure.quantile(.9)),p95_exposure=float(exposure.quantile(.95)),max_exposure=float(exposure.max()),average_cash=float(daily.cash.mean()),average_cash_ratio=float((daily.cash/nav).mean()),capital_days=capital_days,
        pre_capital_intent_count=len(intents),funded_trade_count=len(buys),funded_opportunity_rate=len(buys)/len(intents) if len(intents) else 0.,shared_funded_trade_count=len(shared_ids),shared_funded_opportunity_rate=len(shared_ids)/len(intents) if len(intents) else 0.,
        shared_funded_pnl=sum(final_pnl.get(eid,0.) for eid in shared_ids),all_shared_funding_count=sum(f['funding_type']=='SHARED' for f in buys.values()),
        base_entitlement_shortfall_count=len(account.shortfalls),base_entitlement_shortfall_amount=sum(x['requested']-x['cash'] for x in account.shortfalls),
        max_strategy_exposure=max(float((daily[s+'_exposure']/nav).max()) for s in account.strategies),max_family_exposure=max(float(((daily.ATRDR_exposure+daily.MCB_exposure)/nav).max()),float((daily[account.strategies[2]+'_exposure']/nav).max()),float((daily.SMV6_exposure/nav).max())),
        max_security_exposure=float((daily.max_security_exposure/nav).max()),max_simultaneously_active_strategies=int(pd.DataFrame({s:daily[s+'_exposure']>1e-8 for s in account.strategies}).sum(axis=1).max()),
        max_simultaneously_losing_strategies=int(pd.DataFrame({s:daily[s+'_nav'].diff().lt(0) for s in account.strategies}).sum(axis=1).max()),
        demand_share=float(((daily.ATRDR_exposure+daily.MCB_exposure)/nav).mean()),gap_share=float((daily[account.strategies[2]+'_exposure']/nav).mean()),smv6_share=float((daily.SMV6_exposure/nav).mean()))
    r['CAGR_per_average_exposure']=r['CAGR']/r['average_gross_exposure'] if r['average_gross_exposure'] else None
    r['net_pnl_per_capital_day']=net/capital_days if capital_days else None
    daily=daily.copy();daily['portfolio_return']=returns;daily['DD']=dd
    daily['incremental_shared_pnl']=[sum(json.loads(x).get(eid,0.) for eid in shared_ids) for x in daily.root_pnl_json]
    return r,daily,shared_ids,buys


def save_frame(frame,path):
    frame=frame.copy()
    if 'native_priority' in frame:frame.native_priority=frame.native_priority.map(json.dumps)
    for field in ('timestamp','entry','exit','entry_date','entry_time','decision_at','earliest_execution_at'):
        if field in frame:frame[field]=pd.to_datetime(frame[field],format='mixed')
    frame.to_parquet(path,index=False)


def gate():
    p0=pd.read_csv(OUT/'p0_reconciliation.csv')
    if len(p0)!=4 or not p0.status.eq('PASS').all():raise ValueError('hard P0 gate failed')
    prefix=pd.read_csv(OUT/'raw_continuous_prefix.csv')
    if len(prefix)!=4 or not prefix.status.eq('PASS').all():raise ValueError('native prefix gate failed')
    states=pd.read_csv(OUT/'native_segment_initial_states.csv')
    if len(states)!=10 or not states.validation_status.eq('VALIDATED').all():raise ValueError('initial state gate failed')
    suites=ET.parse(HERE/'cache/v2_tests.xml').getroot().iter('testsuite')
    if any(int(s.get('failures',0))+int(s.get('errors',0)) for s in suites):raise ValueError('focused tests failed')
    from .final_progress_v1 import hashes
    hashes() # Read-only frozen/source/evidence verification; no legacy audit runner.


def run(data=None):
    gate()
    if data is None:data=load_inputs()
    summaries=[];status=[];shared_rows=[];worst=[];demand_rows=[];shortfalls=[];headroom=[];exposures=[];action_rows=[]
    for gap in ('OGR','IFCGR'):
        for period,start,end in PERIODS:
            home=pd.read_parquet(HERE/'cache/common_p0'/gap/period/'account_timeline.parquet').set_index('timestamp')
            pre_funding=pd.read_parquet(HERE/'cache/common_p0'/gap/period/'home_before_funding.parquet').set_index('timestamp')
            home.loc[pre_funding.index,pre_funding.columns]=pre_funding
            base_fills=pd.read_parquet(HERE/'cache/common_p0'/gap/period/'fills.parquet')
            base_ids=set(base_fills.loc[base_fills.side.eq('BUY'),'event_id'])
            for mode in ('independent','confirmation_tag'):
                for policy in POLICIES:
                    identity=dict(gap=gap,period=period,mcb_mode=mode,policy=policy)
                    print('RUN',len(status)+1,'/48',identity,flush=True)
                    account,daily,results,platform,trace=replay(data,gap,period,start,end,policy=policy,mode=mode,home_path=home)
                    demand=pd.DataFrame(account.funding.demand)
                    demand=demand.loc[~demand.event_id.isin(account.native_failures)].copy()
                    summary,daily,shared_ids,buys=metrics(account,daily,start,end,demand,base_ids)
                    if policy=='P0' and mode=='independent':
                        reference=pd.read_parquet(HERE/'cache/common_p0'/gap/period/'daily.parquet')
                        for field in ('cash','nav','gross_exposure'):
                            if np.max(np.abs(reference[field].to_numpy()-daily[field].to_numpy()))>1e-6:raise ValueError('deterministic common P0 rerun failed')
                    if policy=='P0' and mode=='confirmation_tag':
                        repeated=replay(data,gap,period,start,end,policy=policy,mode=mode,home_path=home)
                        pd.testing.assert_frame_equal(daily[repeated[1].columns],repeated[1])
                        pd.testing.assert_frame_equal(pd.DataFrame(account.fills),pd.DataFrame(repeated[0].fills))
                    if policy=='P0':
                        base_ids=set(buys)
                        home=pd.DataFrame(account.account_timeline).set_index('timestamp')
                        before=pd.DataFrame(account.funding.home_history).set_index('timestamp')
                        home.loc[before.index,before.columns]=before
                    folder=HERE/'cache/scenarios'/gap/period/mode/policy;folder.mkdir(parents=True,exist_ok=True)
                    for name,frame in [('daily',daily),('fills',pd.DataFrame(account.fills)),('demand',demand),('timeline',pd.DataFrame(account.account_timeline)),('execution_state_transitions',pd.DataFrame(account.execution_state_transitions))]:save_frame(frame,folder/f'{name}.parquet')
                    (folder/'capital_days.json').write_text(json.dumps(account.capital_days_by_event,sort_keys=True))
                    rejected={r['event_id']:r['reason'] for r in account.rejections}
                    for row in demand.to_dict('records'):
                        fill=buys.get(row['event_id']);row.update(identity)
                        row['funded_notional']=fill['funded_notional'] if fill else 0.
                        row['funding_type']=fill['funding_type'] if fill else 'UNFUNDED'
                        row['reason']=rejected.get(row['event_id'],'FUNDED' if fill else 'NATIVE_REJECTION')
                        demand_rows.append(row)
                    final_pnl=json.loads(daily.root_pnl_json.iloc[-1])
                    for eid in shared_ids:
                        buy=buys[eid]
                        sells=[f for f in account.fills if f['side']=='SELL' and f.get('root_event_id',f['event_id'])==eid]
                        still_open=any(k==eid or l.get('root_event_id')==eid for k,l in account.lots.items())
                        exit_time=None if still_open else max((f['exit'] for f in sells),default=None)
                        elapsed=((pd.Timestamp(exit_time) if exit_time else pd.Timestamp(end)+pd.Timedelta(days=1))-pd.Timestamp(buy['entry'])).total_seconds()/86400
                        shared_rows.append(dict(identity,strategy=buy['strategy'],route=buy['route'],family=buy['family'],event_id=eid,symbol=buy['symbol'],decision_at=buy['decision_at'],requested_notional=buy['requested_notional'],funded_notional=buy['funded_notional'],
                            entry=buy['entry'],exit=exit_time,return_on_funded_notional=final_pnl.get(eid,0.)/buy['funded_notional'],pnl=final_pnl.get(eid,0.),fees=buy['fee']+sum(f['fee'] for f in sells),holding_days=elapsed,capital_days=account.capital_days_by_event.get(eid,0.),funding_reason='VALID_NATIVE_INTENT_UNFUNDED_BY_P0',status='OPEN_MARKED' if still_open else 'CLOSED'))
                    for row in account.shortfalls:shortfalls.append(dict(identity,**row,unavailable_amount=max(0.,row['requested']-row['cash']),later_outcome_pnl=final_pnl.get(row['event_id'])))
                    for reason,count in pd.Series(list(rejected.values()),dtype=str).value_counts().items():headroom.append(dict(identity,classification=reason,opportunity_count=int(count),units='NATIVE_REQUEST_CHECKPOINTS'))
                    unfunded_days=set(pd.Timestamp(r['timestamp']).normalize() for r in demand_rows if all(r[k]==v for k,v in identity.items()) and r['funded_notional']==0)
                    structural=~daily.trade_date.isin(unfunded_days)
                    summary['structural_idle_days']=int(structural.sum());summary['structural_idle_cash_daily_diagnostic']=float(daily.loc[structural,'cash'].mean()) if structural.any() else 0.
                    for cls in ('SEGMENTATION_IDLE','GLOBAL_DEMAND_CONFLICT','FAMILY_CAP_BLOCK','DRAWDOWN_GATE_BLOCK'):summary[cls.lower()+'_count']=sum(v==cls for v in rejected.values())
                    headroom.append(dict(identity,classification='STRUCTURAL_IDLE',opportunity_count=int(structural.sum()),units='TRADING_DAYS_WITH_NO_REJECTED_VALID_REQUEST; cash is not assumed shareable'))
                    for s in account.strategies:
                        for row in daily[['trade_date',s+'_exposure','nav']].itertuples(index=False):exposures.append(dict(identity,strategy=s,date=row[0],exposure=row[1],weight=row[1]/row[2],family='DEMAND' if s in ('ATRDR','MCB') else 'ETF_TIMING' if s=='SMV6' else 'GAP'))
                    prior_nav=daily.nav.shift(1).fillna(account.initial_cash)
                    contributions={s:daily[s+'_nav'].diff().fillna(daily[s+'_nav'].iloc[0]-account.initial_states[s]['nav'])/prior_nav for s in account.strategies}
                    shared_contribution=daily.incremental_shared_pnl.diff().fillna(daily.incremental_shared_pnl.iloc[0])/prior_nav
                    for idx in daily.portfolio_return.nsmallest(10).index:
                        d=daily.loc[idx];row=dict(identity,date=d.trade_date,portfolio_return=d.portfolio_return,DD=d.DD,ATRDR_contribution=contributions['ATRDR'].loc[idx],MCB_contribution=contributions['MCB'].loc[idx],Gap_contribution=contributions[gap].loc[idx],SMV6_contribution=contributions['SMV6'].loc[idx],shared_funded_contribution=shared_contribution.loc[idx],Demand_exposure=(d.ATRDR_exposure+d.MCB_exposure)/d.nav,Gap_exposure=d[gap+'_exposure']/d.nav,SMV6_exposure=d.SMV6_exposure/d.nav,total_gross=d.gross_exposure/d.nav,cash=d.cash,top_symbols=d.top_symbols)
                        if abs(sum(row[k] for k in ('ATRDR_contribution','MCB_contribution','Gap_contribution','SMV6_contribution'))-d.portfolio_return)>1e-10:raise ValueError('daily contribution reconciliation failed')
                        worst.append(row)
                    for service in account.held_actions.values():action_rows.extend(dict(identity,**row) for row in service.audit)
                    summaries.append(dict(identity,**summary));status.append(dict(identity,status='COMPLETE',source=str(folder.relative_to(HERE)),physical_virtual='PASS'))
                    pd.DataFrame(summaries).to_csv(OUT/'scenario_summary.csv',index=False)
                    pd.DataFrame(status).to_csv(OUT/'scenario_run_status.csv',index=False)
                    print('DONE',len(status),summary['CAGR'],summary['MaxDD'],'shared',summary['shared_funded_trade_count'],flush=True)
    for name,rows,columns in [('shared_funded_trades',shared_rows,['gap','period','mcb_mode','policy','event_id','pnl']),('worst_portfolio_days',worst,None),('daily_capital_demand',demand_rows,None),('base_entitlement_shortfall',shortfalls,['gap','period','mcb_mode','policy','timestamp','strategy','event_id','requested','unavailable_amount','later_outcome_pnl']),('capital_headroom_summary',headroom,None),('strategy_family_exposure',exposures,None),('scenario_held_actions',action_rows,None)]:
        pd.DataFrame(rows,columns=columns if not rows else None).to_csv(OUT/f'{name}.csv',index=False)
    if len(status)!=48:raise ValueError('frozen scenario grid incomplete')
    return summaries

if __name__=='__main__':run()
