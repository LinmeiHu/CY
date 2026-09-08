"""Common chronological physical P0, reconciled to continuous native accounts."""
import json
from pathlib import Path
import pandas as pd
from five_strategy_bundle.strategies import ogr
from .stock_p0 import replay as stock_replay
from .gap_p0 import replay as gap_replay
from .smv6_physical import PhysicalPlatform, callback_stream
from .smv6_baseline import load_bounded
from .continuous_replay import load_stock_daily
from .native_states_v06 import state_hash
from .shared_account.allocator import active_strategies
from .shared_account.p0 import initialize
from .shared_account.scheduler import Event, run_streams
from .shared_account.held_actions import registered_actions
from .run_shared_capital_v1 import HERE

PERIODS=[('2018_2021','2018-01-01','2021-12-31'),('2022_2023','2022-01-01','2023-12-31')]


def load_inputs(*, execution_hardening=None):
    from .universe import verify
    verify(execution_hardening=execution_hardening)
    inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    data={'actions':registered_actions()}
    for strategy in ('ATRDR','MCB'):
        entries=pd.read_parquet(HERE/'cache'/strategy.lower()/'precapital_entry_population.parquet')
        data[strategy]=(entries,load_stock_daily(inputs,entries.symbol))
    import duckdb
    with duckdb.connect() as con:
        data['gap_daily']=con.execute("SELECT symbol,trade_date,open,close FROM read_parquet(?) WHERE trade_date BETWEEN '2013-01-01' AND '2023-12-31'",[str(inputs['daily_hist'])]).fetchdf()
    data['gap_outcomes']=pd.read_parquet(HERE/'cache/ogr/outcomes.parquet')
    data['OGR']=pd.read_parquet(HERE/'cache/ogr/signals.parquet')
    data['IFCGR']=pd.concat([pd.read_parquet(HERE/'cache/ifcgr'/p/'signals.parquet') for p,_,_ in PERIODS])
    data['etf']=load_bounded(inputs)
    return data


def replay(data,gap,period,start,end,*,policy='P0',mode='independent',home_path=None,scaling=None,selected=None):
    states={s:json.loads((HERE/'output'/f'{s.lower()}_initial_state_{start[:4]}.json').read_text()) for s in active_strategies(gap)}
    for s,state in states.items():
        if state_hash({k:v for k,v in state.items() if k!='state_hash'})!=state['state_hash']:raise ValueError(f'{s} state hash mismatch')
    account=initialize(gap,states)
    if selected is not None:
        from .shared_account.p0 import restrict_to_strategies
        restrict_to_strategies(account, selected)
    if scaling is not None:
        scaling.bind(account, states, data, period, start, end)
    from .shared_account.native_funding import NativeFunding
    from .shared_account.drawdown_gate import DrawdownGate
    gate=DrawdownGate(int(policy[-1])/100,account.initial_cash) if policy.startswith('P3') else None
    funding=NativeFunding(account,policy,mode,home_path,gate)
    account.funding=funding
    streams=[];results={};daily=[]
    for strategy in ('ATRDR','MCB'):
        if strategy not in account.strategies:
            continue
        entries,prices=data[strategy]
        stream,result=stock_replay(strategy,entries,prices,start,end,physical=account,stream_only=True,initial_state=states[strategy],action_registry=data['actions'])
        streams.append(stream);results[strategy]=result
    if gap in account.strategies:
        trades=data['gap_outcomes'].loc[data['gap_outcomes'].gap_id.isin(data[gap].gap_id)]
        stream,result=gap_replay(gap,trades,data['gap_daily'],start,end,physical=account,stream_only=True,initial_state=states[gap],action_registry=data['actions'])
        streams.append(stream);results[gap]=result
    etf_daily,minute,availability=data['etf']
    calendar=list(etf_daily['000852.SH'].loc[start:end].dropna(subset=['pre_adj_close']).index)
    platform = None
    if 'SMV6' in account.strategies:
        cls = PhysicalPlatform if scaling is None else scaling.platform_class
        platform=cls(etf_daily,minute,availability,calendar,initial_cash=states['SMV6']['cash'],lot_size=100,fee_bps=0,physical=account)
        streams.append(callback_stream(platform,calendar))
    if scaling is not None:
        streams = scaling.wrap_streams(streams, calendar, platform)
    if account.strategies == ('SMV6',):
        streams.append((Event(day+pd.Timedelta(hours=15, minutes=1), 'RECORD', 'ACCOUNT', str(day), lambda: None) for day in calendar))
    from collections import defaultdict
    capital_days=defaultdict(float)
    last_time=pd.Timestamp(start)
    last_values={}
    def lot_values():
        values=defaultdict(float)
        for eid,lot in account.lots.items():values[lot.get('root_event_id',eid)]+=(lot['quantity']+lot.get('pending_quantity',0.))*account.marks[lot['symbol']]
        return values
    last_values=lot_values()
    def completed(when):
        nonlocal last_time,last_values
        elapsed=(when-last_time).total_seconds()/86400
        for eid,value in last_values.items():capital_days[eid]+=value*elapsed
        last_time,last_values=when,lot_values()
        if scaling is not None:
            scaling.completed(when)
        row=account.complete_timestamp(when)
        for s in account.strategies:
            row[s+'_cash']=account.sleeve_cash[s]
            row[s+'_exposure']=account.exposure(s)
            row[s+'_nav']=account.sleeve_cash[s]+account.exposure(s)
        row['shared_exposure']=sum((l['quantity']+l.get('pending_quantity',0.))*account.marks[l['symbol']] for l in account.lots.values() if l.get('funding_type')=='SHARED')
        row['shared_pnl']=sum(f['pnl'] for f in account.fills if f['side']=='SELL' and f.get('funding_type')=='SHARED')+sum(f['amount'] for f in account.cash_distributions if f['funding_type']=='SHARED')+sum((l['quantity']+l.get('pending_quantity',0.))*account.marks[l['symbol']]-l['remaining_outlay'] for l in account.lots.values() if l.get('funding_type')=='SHARED')
        row['capital_days']=sum(capital_days.values())
        security_values={s:(account.positions.get(s,0.)+account.pending_positions.get(s,0.))*account.marks[s]
                         for s in dict.fromkeys([*account.positions,*account.pending_positions])}
        row['max_security_exposure']=max(security_values.values(),default=0.)
        row['top_symbols']=json.dumps(sorted(security_values.items(),key=lambda x:-x[1])[:10])
        account.account_timeline[-1].update(row)
        if when.hour==15 and when.minute==1:
            root_pnl=defaultdict(float)
            for fill in account.fills:
                if fill['side']=='SELL':root_pnl[fill.get('root_event_id',fill['event_id'])]+=fill['pnl']
            for credit in account.cash_distributions:root_pnl[credit['root_event_id']]+=credit['amount']
            for eid,lot in account.lots.items():root_pnl[lot.get('root_event_id',eid)]+=(lot['quantity']+lot.get('pending_quantity',0.))*account.marks[lot['symbol']]-lot['remaining_outlay']
            row['root_pnl_json']=json.dumps(dict(root_pnl),sort_keys=True)
            daily.append(dict(row,trade_date=when.normalize()))
            if gate:gate.complete_close(when.date(),row['nav'])
    trace=run_streams(streams,complete_timestamp=completed,funding=funding)
    terminal=pd.Timestamp(end)+pd.Timedelta(days=1)
    for eid,value in last_values.items():capital_days[eid]+=value*(terminal-last_time).total_seconds()/86400
    account.capital_days_by_event=dict(capital_days)
    return account,pd.DataFrame(daily),results,platform,trace


def run():
    print('Loading common raw/ETF inputs',flush=True)
    data=load_inputs();rows=[];adapters=[];actions=[];reconciliation=[]
    for gap in ('OGR','IFCGR'):
        for period,start,end in PERIODS:
            print('Common P0',gap,period,flush=True)
            account,daily,results,platform,trace=replay(data,gap,period,start,end)
            folder=HERE/'cache/common_p0'/gap/period;folder.mkdir(parents=True,exist_ok=True)
            for name,frame in [('scheduler',pd.DataFrame(trace)),('checkpoints',pd.DataFrame(account.checkpoints)),('account_timeline',pd.DataFrame(account.account_timeline)),('daily',daily),('fills',pd.DataFrame(account.fills)),('home_before_funding',pd.DataFrame(account.funding.home_history))]:
                if 'native_priority' in frame:frame.native_priority=frame.native_priority.map(json.dumps)
                for field in ('timestamp','entry','exit','entry_date','entry_time','decision_at','earliest_execution_at'):
                    if field in frame:frame[field]=pd.to_datetime(frame[field],format='mixed')
                frame.to_parquet(folder/f'{name}.parquet',index=False)
            differences=[]
            for strategy,result in results.items():
                intents,rejects,native_nav=result()
                native_nav.to_parquet(folder/f'{strategy.lower()}_native_nav.parquet',index=False)
                if 'native_priority' in intents:intents.native_priority=intents.native_priority.map(json.dumps)
                intents.to_parquet(folder/f'{strategy.lower()}_intents.parquet',index=False)
                reference_folder='raw_continuous' if strategy in ('ATRDR','MCB') else 'native_continuous'
                reference=pd.read_parquet(HERE/'cache'/strategy.lower()/reference_folder/'nav.parquet')
                reference=reference.loc[reference.trade_date.between(start,end)]
                joined=native_nav.merge(reference,on='trade_date',suffixes=('_common','_native'),validate='one_to_one')
                if len(joined)!=len(reference) or len(joined)!=len(native_nav):raise ValueError('missing common native dates')
                error=max(float((joined[f+'_common']-joined[f+'_native']).abs().max()) for f in ('cash','nav','gross_exposure'))
                differences.append(error)
                reconciliation.append(dict(strategy=strategy,gap=gap,period=period,max_abs_cash_nav_exposure_diff=error,status='PASS' if error<=1e-6 else 'REGRESSION'))
                adapters.append(dict(strategy=strategy,gap=gap,period=period,PRE_CAPITAL_INTENT_COUNT=len(intents),NATIVE_FUNDED_COUNT=sum(f['side']=='BUY' and f['strategy']==strategy for f in account.fills),OTHER_REJECTED_COUNT=len(rejects),status='PASS' if error<=1e-6 else 'REGRESSION'))
                actions.extend(account.held_actions[strategy].audit)
            native=pd.DataFrame(platform.accounts)
            reference=pd.read_parquet(HERE/'cache/smv6'/period/'CAUSAL_CORRECTED_BASELINE_nav.parquet')
            joined=native.merge(reference,on='trade_date',suffixes=('_common','_native'),validate='one_to_one')
            error=max(float((joined[f+'_common']-joined[f+'_native']).abs().max()) for f in ('cash','nav'))
            differences.append(error)
            reconciliation.append(dict(strategy='SMV6',gap=gap,period=period,max_abs_cash_nav_exposure_diff=error,status='PASS' if error<=1e-6 else 'REGRESSION'))
            if (platform.commission_rate,platform.slippage_total,platform.minute_volume_limit)!=(.0002,.0016,.5):raise ValueError('SMV6 execution contract changed')
            status='PASS' if max(differences)<=1e-6 else 'REGRESSION'
            row=dict(policy='P0',gap=gap,period=period,status=status,physical_account_created=True,max_abs_native_difference=max(differences),final_nav=float(daily.nav.iloc[-1]),shared_scenarios_run=0)
            rows.append(row);print(row,flush=True)
            pd.DataFrame(rows).to_csv(HERE/'output/p0_reconciliation.csv',index=False)
            pd.DataFrame(reconciliation).to_csv(HERE/'output/common_native_reconciliation.csv',index=False)
    pd.DataFrame(adapters).to_csv(HERE/'output/common_opportunity_adapter_reconciliation.csv',index=False)
    pd.DataFrame(actions).drop_duplicates(['strategy','action_id']).to_csv(HERE/'output/common_held_actions.csv',index=False)
    if any(r['status']!='PASS' for r in rows):raise ValueError('P0 native comparison regression')
    return rows

if __name__=='__main__':run()
