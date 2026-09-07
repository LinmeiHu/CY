"""Production raw-account transitions and causal native decisions."""
from dataclasses import replace
from copy import deepcopy
from pathlib import Path
import json
import pandas as pd
import pytest
from research.shared_capital_v1.stock_p0 import replay,HERE
from research.shared_capital_v1.continuous_replay import load_stock_daily
from research.shared_capital_v1.shared_account.held_actions import registered_actions
from research.shared_capital_v1.shared_account.engine import PhysicalAccount,Intent


@pytest.mark.parametrize('strategy,symbol,start,ex,listed,end,ratio,cash',[
    ('ATRDR','600622.SH','2017-06-26','2017-06-30','2017-07-03','2017-08-01',.3,.21),
    ('MCB','603368.SH','2020-06-18','2020-06-24','2020-06-29','2020-07-30',.4,.68)])
def test_official_events_execute_in_native_stock_replay(strategy,symbol,start,ex,listed,end,ratio,cash):
    inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    daily=load_stock_daily(inputs,[symbol]);registry=registered_actions()
    entries=pd.read_parquet(HERE/'cache'/strategy.lower()/'precapital_entry_population.parquet')
    entries=entries.loc[entries.symbol.eq(symbol)&entries.entry_date.eq(start)]
    # Poison future outcomes: a production decision must not read these fields.
    entries['exit_date']=pd.Timestamp(start);entries['exit_price']=999999.;entries['exit_reason']='POISON';entries['status']='INVALID'
    a,i,r,n,b=replay(strategy,entries,daily,start,end,action_registry=registry)
    assert b is None
    buy=next(f for f in a.fills if f['side']=='BUY');q=buy['quantity']
    timeline=pd.DataFrame(a.held_actions[strategy].timeline).set_index('phase')
    assert timeline.loc['RECORD_DATE','raw_quantity_total']==pytest.approx(q)
    assert timeline.loc['EX_DATE','pending_quantity']==pytest.approx(q*ratio)
    assert timeline.loc['EX_DATE','tradable_quantity']==pytest.approx(q)
    assert timeline.loc['TRADABLE_DATE','tradable_quantity']==pytest.approx(q*(1+ratio))
    assert timeline.loc['TRADABLE_DATE','timestamp']==pd.Timestamp(listed)+pd.Timedelta(hours=9,minutes=30)
    assert timeline.loc['EX_DATE','cash']-timeline.loc['RECORD_DATE','cash']==pytest.approx(q*cash)
    assert all(f['exit']>=pd.Timestamp(listed) for f in a.fills if f['side']=='SELL' and '|CA|' in f['event_id'])
    assert len([f for f in a.fills if f['side']=='SELL'])==2
    assert not a.positions and not a.pending_positions
    # Independent strict prefix includes the pending state, not only NAV.
    prefix=replay(strategy,entries,daily.loc[daily.trade_date.le(ex)],start,ex,action_registry=registry)
    pd.testing.assert_frame_equal(prefix[3],n.loc[n.trade_date.le(ex)].reset_index(drop=True))
    assert prefix[0].pending_positions[symbol]==pytest.approx(q*ratio)
    assert prefix[0].positions[symbol]==pytest.approx(q)
    assert all(x['status']=='APPLIED' for x in a.held_actions[strategy].audit)


def test_physical_marks_never_rewind_and_completed_timestamp_is_unique():
    a=PhysicalAccount('OGR')
    a.mark({'S':10.},basis='RAW',observed_at='2020-01-02 09:30')
    a.mark({'S':9.},basis='RAW',observed_at='2020-01-01 15:00')
    assert a.marks['S']==10.
    a.complete_timestamp('2020-01-02 09:30')
    with pytest.raises(ValueError,match='duplicate'):a.complete_timestamp('2020-01-02 09:30')


def test_native_funding_exposes_all_base_heads_before_shared_and_commits_actual_state():
    from research.shared_capital_v1.shared_account.native_funding import NativeFunding
    from research.shared_capital_v1.shared_account.scheduler import Event,run_streams
    when=pd.Timestamp('2020-01-02 09:30')
    results=[]
    for reverse in (False,True):
        a=PhysicalAccount('OGR',initial_cash=40000.)
        # Frozen P0 reference remains independent of actual sleeve profit/cash.
        path=pd.DataFrame([{s+'_nav':10000. for s in a.strategies}],index=[when])
        funding=NativeFunding(a,'P1','independent',path)
        state={}
        def stock(strategy,requests):
            for index,amount in enumerate(requests):
                i=Intent(strategy,'BULL','DEMAND',strategy+str(index),'',strategy+str(index),when-pd.Timedelta(days=1),when,(index,),amount/10,10.,0.)
                a.fund([i],{s:999999. for s in a.strategies},'P0',when)
                state[i.event_id]=i.event_id in a.lots
        events=[Event(when,'ENTRY','ATRDR','A',lambda:stock('ATRDR',[11000.])),
                Event(when,'ENTRY','MCB','M',lambda:stock('MCB',[5000.,5000.]))]
        run_streams([[e] for e in (events[::-1] if reverse else events)],funding=funding,complete_timestamp=a.complete_timestamp)
        fills=[(f['event_id'],f['funding_type'],f['funded_notional']) for f in a.fills]
        assert fills==[('MCB0','BASE',5000.),('MCB1','BASE',5000.),('ATRDR0','SHARED',11000.)]
        assert all(state.values()) and a.cash==19000.
        assert all(d['home_budget']==10000. for d in funding.demand)
        results.append((fills,state,a.positions))
    assert results[0]==results[1]


def test_slow_bear_expired_open_exit_never_reads_unfinished_target_high():
    days=pd.bdate_range('2020-01-02',periods=22)
    entries=pd.DataFrame([dict(event_id='SLOW',symbol='000001.SZ',sleeve='MAIN',route='V27',lane='BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION',signal_date=days[0]-pd.Timedelta(days=1),entry_date=days[0],entry_price=10.,source_rank_order=0)])
    rows=[dict(symbol='000001.SZ',trade_date=d,open=10.,close=10.,coord_open=10.,coord_close=10.,coord_high=10.,coordinate_factor=1.,cal_idx=n,invalid_step_cum=0.,corporate_action_count=0,trade_status=1,down_limit_price=9.,hard_valid=True,history_valid=True,current_valid=True,corporate_action_valid=True,current_day_data_tradable=True,historical_identity_valid=True,market_rule_valid=True,corporate_action_blocking=False) for n,d in enumerate(days)]
    exits=[]
    for high in (10.,100.):
        daily=pd.DataFrame(rows);daily.loc[daily.index[-1],'coord_high']=high
        empty=registered_actions().iloc[:0]
        account,*_,blocker=replay('ATRDR',entries,daily,str(days[0].date()),str(days[-1].date()),action_registry=empty)
        assert blocker is None
        sells=[f for f in account.fills if f['side']=='SELL']
        assert len(sells)==1 and sells[0]['exit']==days[-1]+pd.Timedelta(hours=9,minutes=30)
        assert sells[0]['exit_price']==10. and sells[0]['reason']=='H20_TIME_STOP'
        exits.append((sells[0]['exit'],account.cash,account.positions))
    assert exits[0]==exits[1]


def test_native_batch_keeps_board_budgets_priority_and_exact_confirmation():
    from research.shared_capital_v1.shared_account.native_funding import NativeFunding
    from research.shared_capital_v1.shared_account.scheduler import Event,run_streams
    t=pd.Timestamp('2020-01-02 09:30');home={s:10000. for s in ('ATRDR','MCB','OGR','SMV6')}
    a=PhysicalAccount('OGR',initial_cash=40000.)
    base=Intent('ATRDR','BULL','DEMAND','new','','S',t-pd.Timedelta(days=1),t,(0,),400.,10.,0.,board='MAIN',native_base_cash_limit=5000.,native_max_positions=30,native_daily_entries=10,economic_event_definition='NEXT_OPEN_T15_H15_STANDARD_NATIVE_EXIT')
    # Older signal must not override native (newer-first) priority. Neither may
    # use the other board's idle home cash in P0.
    older=replace(base,event_id='old',symbol='T',decision_at=t-pd.Timedelta(days=2),native_priority=(1,))
    a.fund([older,base],home,'P0',t)
    assert list(a.lots)==['new'] and a.sleeve_cash['ATRDR']==6000.
    for mode,count in [('independent',2),('confirmation_tag',1)]:
        b=PhysicalAccount('OGR',initial_cash=40000.)
        f=NativeFunding(b,'P0',mode)
        mcb=replace(base,strategy='MCB',route='MCB',event_id='mcb')
        streams=[[Event(t,'ENTRY',i.strategy,i.event_id,lambda i=i:b.fund([i],home,'P0',t))] for i in [base,mcb]]
        run_streams(streams,funding=f)
        assert len(b.lots)==count
        if mode=='confirmation_tag':assert b.rejections==[dict(event_id='mcb',reason='EXACT_CONFIRMATION_TAG')]


def test_confirmation_never_discards_mcb_for_native_capacity_rejected_atrdr():
    t=pd.Timestamp('2020-01-02 09:30');a=PhysicalAccount('OGR',initial_cash=40000.);home={s:10000. for s in a.strategies}
    first=Intent('ATRDR','BULL','DEMAND','first','','X',t-pd.Timedelta(days=1),t,(0,),100.,10.,0.,board='MAIN',native_max_positions=1,native_daily_entries=10,economic_event_definition='NEXT_OPEN_T15_H15_STANDARD_NATIVE_EXIT')
    rejected=replace(first,event_id='capacity',symbol='Y',native_priority=(1,))
    mcb=replace(rejected,strategy='MCB',route='MCB',event_id='mcb',native_priority=(0,))
    a.fund([mcb,rejected,first],home,'P0',t,mcb_mode='confirmation_tag')
    assert set(a.lots)=={'first','mcb'}
    assert a.native_failures=={'capacity':'MAX_K'}


def test_actual_300561_suspension_carries_raw_holdings_and_resumes_causally():
    inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    daily=load_stock_daily(inputs,['300561.SZ'])
    entries=pd.read_parquet(HERE/'cache/mcb/precapital_entry_population.parquet')
    entries=entries.loc[entries.event_id.eq('V72|V65|MEDIUM_PARTICIPATION|V53-20230119-300561.SZ')]
    result=replay('MCB',entries,daily,'2023-01-20','2023-03-01')
    account,intents,_,nav,blocker=result
    assert blocker is None
    suspended=pd.date_range('2023-02-02','2023-02-06')
    assert not any(pd.Timestamp(f.get('exit',f['entry'])).normalize() in suspended for f in account.fills)
    assert [x['transition'] for x in account.execution_state_transitions]==['REGISTERED_SUSPENSION_NO_FILL_NO_QUANTITY_CHANGE','REGISTERED_RESUMPTION_SAME_RAW_HOLDINGS']
    prefix=replay('MCB',entries,daily.loc[daily.trade_date.le('2023-02-06')],'2023-01-20','2023-02-06')
    assert prefix[-1] is None and prefix[0].positions['300561.SZ']==next(f['quantity'] for f in account.fills if f['side']=='BUY')
    pd.testing.assert_frame_equal(prefix[3],nav.loc[nav.trade_date.le('2023-02-06')].reset_index(drop=True))
