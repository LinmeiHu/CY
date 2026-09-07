from copy import deepcopy
from dataclasses import replace
import pandas as pd
import pytest
from research.shared_capital_v1.shared_account.engine import PhysicalAccount, Intent
from research.shared_capital_v1.shared_account.corporate_actions import ShareConversion
from research.shared_capital_v1.shared_account.scheduler import Event, run_streams

T = pd.Timestamp('2020-06-01 09:30')
HOME = {s:10000. for s in ('ATRDR','MCB','OGR','SMV6')}


def seeded(two=False):
    account = PhysicalAccount('OGR', initial_cash=40000.)
    intents = [Intent('ATRDR','BULL','DEMAND','A','','S',T-pd.Timedelta(days=1),T,(0,),100.,13.,0.)]
    if two:
        intents.append(replace(intents[0],strategy='MCB',event_id='B',native_requested_quantity=200.))
    account.fund(intents,HOME,'P0',T)
    action = ShareConversion(account)
    return account,action


def apply_record(account,action):
    action.record('C','S',.3,T+pd.Timedelta(hours=5,minutes=30),T)
    assert account.positions['S'] in (100.,300.)
    assert not account.pending_positions
    assert action.events['C']['entitlements']['A'] == 30.


def apply_ex(action):
    action.transition('C','ACCOUNTING_EFFECTIVE_DATE',T+pd.Timedelta(days=1),T,ex_price=10.)


def test_conversion_100_to_30_entitlement_nav_and_pro_rata():
    account,action = seeded(True)
    before = account.checkpoint(T,'BEFORE')['nav']
    apply_record(account,action)
    apply_ex(action)
    assert account.positions == {'S':300.}
    assert account.pending_positions == {'S':90.}
    assert account.lots['A|CA|C']['pending_quantity'] == 30.
    assert account.lots['B|CA|C']['pending_quantity'] == 60.
    assert account.checkpoint(T+pd.Timedelta(days=1),'EX')['nav'] == pytest.approx(before)
    assert account.lots['A|CA|C']['remaining_outlay'] == pytest.approx(300.)


@pytest.mark.parametrize('exit_before_arrival',[True,False])
def test_exit_before_or_after_tradable_keeps_entitlement(exit_before_arrival):
    account,action = seeded()
    apply_record(account,action); apply_ex(action)
    caid='A|CA|C'
    with pytest.raises(ValueError,match='exit'):
        account.close(caid,10.,T+pd.Timedelta(days=1),0.,quantity=30.)
    if exit_before_arrival:
        account.close('A',10.,T+pd.Timedelta(days=1),0.)
        assert caid in account.lots and account.pending_positions == {'S':30.}
    action.transition('C','SHARE_ARRIVAL_DATE',T+pd.Timedelta(days=2),T)
    assert not account.pending_positions
    assert account.lots[caid]['nontradable_quantity'] == 30.
    with pytest.raises(ValueError,match='exit'):
        account.close(caid,10.,T+pd.Timedelta(days=2),0.,quantity=30.)
    action.transition('C','TRADABLE_DATE',T+pd.Timedelta(days=3),T)
    if not exit_before_arrival:
        account.close('A',10.,T+pd.Timedelta(days=3),0.)
    account.close(caid,10.,T+pd.Timedelta(days=3),0.)
    assert account.positions == {} and not account.lots
    assert account.cash == pytest.approx(account.initial_cash)


def test_future_listing_information_cannot_rewrite_prefix():
    results=[]
    for future in (False,True):
        account,action = seeded()
        events=[Event(T+pd.Timedelta(hours=5,minutes=30),'ACTION','ATRDR','record',lambda:apply_record(account,action)),
                Event(T+pd.Timedelta(days=1),'ACTION','ATRDR','ex',lambda:apply_ex(action))]
        states=[]
        events.append(Event(T+pd.Timedelta(days=1),'CLOSE','ATRDR','capture',lambda:states.append(deepcopy((account.fills,account.lots,account.positions,account.pending_positions,account.cash,account.exposure(),action.events)))))
        if future:
            events.extend([Event(T+pd.Timedelta(days=2),'ACTION','ATRDR','arrival',lambda:action.transition('C','SHARE_ARRIVAL_DATE',T+pd.Timedelta(days=2),T+pd.Timedelta(days=2))),Event(T+pd.Timedelta(days=3),'ACTION','ATRDR','listed',lambda:action.transition('C','TRADABLE_DATE',T+pd.Timedelta(days=3),T+pd.Timedelta(days=2)))])
        run_streams([iter(events)])
        results.append(states)
    assert results[0]==results[1]


def test_future_known_or_out_of_order_action_fails_without_mutation():
    account,action=seeded();apply_record(account,action)
    prior=deepcopy(account.__dict__)
    with pytest.raises(ValueError):action.transition('C','ACCOUNTING_EFFECTIVE_DATE',T+pd.Timedelta(days=1),T+pd.Timedelta(days=2),ex_price=10.)
    with pytest.raises(ValueError):action.transition('C','TRADABLE_DATE',T+pd.Timedelta(days=1),T)
    assert account.__dict__==prior


def test_scheduler_native_clocks_ties_no_cross_sleeve_and_rerun():
    results=[]
    for reverse in (False,True):
        account=PhysicalAccount('OGR',initial_cash=40000.)
        streams=[]
        for strategy in HOME:
            request=Intent(strategy,'native','test',strategy,'','S',T-pd.Timedelta(days=1),T,(0,),1100.,10.,0.)
            # Every request exceeds its own 10k home cash despite 40k physical cash.
            events=[Event(T,'EXIT',strategy,'exit',lambda:None),Event(T,'ENTRY',strategy,'entry',lambda r=request:account.fund([r],HOME,'P0',T)),Event(T+pd.Timedelta(hours=5,minutes=27),'SIGNAL',strategy,'tail',lambda:None),Event(T+pd.Timedelta(hours=5,minutes=30),'CLOSE',strategy,'close',lambda:account.checkpoint(T+pd.Timedelta(hours=5,minutes=30),'CLOSE'))]
            streams.append(iter(events))
        trace=run_streams(list(reversed(streams)) if reverse else streams)
        assert [r['phase'] for r in trace[:8]]==['EXIT']*4+['ENTRY']*4
        assert not account.lots and account.cash==40000.
        assert len(account.rejections)==4
        results.append((trace,account.checkpoints,account.rejections))
    assert results[0]==results[1]


def test_scheduler_rejects_duplicate_and_backward_events():
    e=Event(T,'ENTRY','ATRDR','x',lambda:None)
    with pytest.raises(ValueError,match='duplicate'):run_streams([[e],[e]])
    with pytest.raises(ValueError,match='chronology'):run_streams([[e,replace(e,when=T-pd.Timedelta(days=1))]])


@pytest.mark.parametrize('field',['quantity','remaining_outlay','pending_quantity','nontradable_quantity'])
@pytest.mark.parametrize('bad',[float('nan'),float('inf'),-1.])
def test_nonfinite_or_negative_lot_state_fails(field,bad):
    account,_=seeded();account.lots['A'][field]=bad
    with pytest.raises(ValueError):account.checkpoint(T,'BAD')


def test_physical_nan_cannot_hide_in_quantity_comparison():
    account,_=seeded();account.positions['S']=float('nan')
    with pytest.raises(ValueError):account.checkpoint(T,'BAD')


def test_common_p0_refuses_cash_replacement_or_missing_strategy():
    from research.shared_capital_v1.shared_account.p0 import initialize
    with pytest.raises(ValueError,match='four'):initialize('OGR',{})
    states={s:dict(strategy=s,validation_status='VALIDATED',cash=10000.,nav=10000.,positions={},virtual_lots={},tradable_quantity={},pending_entitlement={},segment_start='2020-06-01') for s in HOME}
    states['ATRDR']['validation_status']='CORPORATE_ACTION_STATE_UNRESOLVED'
    with pytest.raises(ValueError,match='ATRDR'):initialize('OGR',states)


def test_common_p0_actual_stock_adapter_streams_share_one_account():
    from research.shared_capital_v1.stock_p0 import replay
    from research.shared_capital_v1.shared_account.p0 import run
    from research.shared_capital_v1.gap_p0 import replay as gap_replay
    states={s:dict(strategy=s,validation_status='VALIDATED',cash=10000.,nav=10000.,positions={},virtual_lots={},tradable_quantity={},pending_entitlement={},segment_start='2020-06-01') for s in HOME}
    day=T.normalize()
    factories={}
    for strategy in ('ATRDR','MCB'):
        symbol=strategy
        entries=pd.DataFrame([dict(event_id=strategy,symbol=symbol,sleeve='MAIN',route='BULL',signal_date=day-pd.Timedelta(days=1),entry_date=day,entry_price=10.,exit_date=day+pd.Timedelta(days=1),exit_price=10.,exit_reason='H15_TIME',source_rank_order=0,industry_positive_ret20_share=1.,stock_minus_industry_ret20=1.,turnover_expansion=1.)])
        daily=pd.DataFrame([dict(symbol=symbol,trade_date=day+pd.Timedelta(days=i),coord_open=10.,coord_close=10.,coord_high=12. if i else 10.,open=10.,close=10.,coordinate_factor=1.,cal_idx=i,invalid_step_cum=0.,corporate_action_count=0,trade_status=1,down_limit_price=1.,hard_valid=True,history_valid=True,current_valid=True,corporate_action_valid=True,current_day_data_tradable=True,historical_identity_valid=True,market_rule_valid=True,corporate_action_blocking=False) for i in range(2)])
        factories[strategy]=lambda account,state,s=strategy,e=entries,d=daily:replay(s,e,d,'2020-06-01','2020-06-02',physical=account,stream_only=True)[0]
    gap=pd.DataFrame([dict(gap_id='G',symbol='G',board='MAIN',signal_time=T-pd.Timedelta(minutes=1),entry_time=T,entry_date=day,exit_time=T+pd.Timedelta(days=1),exit_date=day+pd.Timedelta(days=1),entry_raw_price=10.,exit_raw_price=10.,entry_coordinate_price=10.,target_coordinate=11.,pre_gap_inside_density_relative_local=.1,cash_events_json='[]')])
    gd=pd.DataFrame([dict(symbol='G',trade_date=day+pd.Timedelta(days=i),close=10.) for i in range(2)])
    factories['OGR']=lambda account,state:gap_replay('OGR',gap,gd,'2020-06-01','2020-06-02',physical=account,stream_only=True)[0]
    # Synthetic ETF event exercises fourth sleeve; real native callback historical
    # equivalence is separately verified by smv6_physical.run on both full periods.
    def etf(account,state):
        intent=Intent('SMV6','callback','ETF','ETF','','ETF',T-pd.Timedelta(days=1),T,(0,),100.,10.,.0002,lot_size=100)
        yield Event(T,'OPEN_CALLBACK','SMV6','open',lambda:account.fund([intent],HOME,'P0',T))
        yield Event(T+pd.Timedelta(days=1),'EXIT','SMV6','close',lambda:account.close('ETF',10.,T+pd.Timedelta(days=1),.0002))
    factories['SMV6']=etf
    account,trace=run('OGR',states,factories)
    assert len(account.fills)==8 and not account.positions
    assert set(f['strategy'] for f in account.fills)==set(HOME)
    assert account.cash==pytest.approx(sum(account.sleeve_cash.values()))
    assert account.checkpoints[-1]['pnl_delta']==pytest.approx(0.,abs=1e-6)
    assert all(r['timestamp']<=trace[i+1]['timestamp'] for i,r in enumerate(trace[:-1]))


def test_incompatible_price_units_fail_before_cash_mutation():
    account,_=seeded();before=account.cash
    bad=Intent('MCB','native','DEMAND','bad','','S',T-pd.Timedelta(days=1),T,(0,),100.,13.,0.,price_basis='NATIVE_COORDINATE')
    with pytest.raises(ValueError,match='price-unit'):account.fund([bad],HOME,'P0',T)
    assert account.cash==before


def test_registered_gap_action_loader_includes_2023_without_changing_terms(tmp_path):
    from research.shared_capital_v1.build_inputs import load_gap_actions
    row=dict(symbol='600001',event_id='action',known_at=pd.Timestamp('2023-05-10'),effective_date=pd.Timestamp('2023-05-18'),share_multiplier=1.3,cash_per_share_gross=.2,source_terms_complete=True)
    distributions=tmp_path/'distributions.parquet';rights=tmp_path/'rights.parquet'
    pd.DataFrame([row]).to_parquet(distributions)
    pd.DataFrame([row]).iloc[:0].to_parquet(rights)
    result=load_gap_actions({'qd010_distributions':distributions,'qd010_rights':rights},['600001.SH'])
    assert len(result)==1 and result.iloc[0].effective_date==row['effective_date']
    assert result.iloc[0].share_multiplier==1.3 and result.iloc[0].action_kind=='RISK_SHARE'


def test_native_boundary_roundtrip_preserves_home_and_inherited_position():
    from research.shared_capital_v1.shared_account.p0 import initialize
    from research.shared_capital_v1.native_states_v06 import state_hash
    states={s:dict(strategy=s,validation_status='VALIDATED',cash=10000.,nav=10000.,positions={},virtual_lots={},tradable_quantity={},pending_entitlement={},segment_start='2020-06-01') for s in HOME}
    state=states['OGR'];state.update(cash=9000.,nav=10200.,positions={'S':100.},tradable_quantity={'S':100.},marks={'S':12.},virtual_lots={'inherited':dict(symbol='S',quantity=100.,remaining_outlay=1000.)})
    a,b=initialize('OGR',deepcopy(states)),initialize('OGR',deepcopy(states))
    assert a.cash==39000. and a.initial_cash==40200.
    assert a.sleeve_cash['OGR']==9000. and a.positions=={'S':100.}
    assert a.checkpoints==b.checkpoints
    assert state_hash(states)==state_hash(deepcopy(states))
    a.close('inherited',12.,T,0.)
    assert a.realized['OGR']==0. # segment P&L starts at inherited market value
    assert a.sleeve_cash['OGR']==10200.
    states['OGR']['cash']=float('nan')
    with pytest.raises(ValueError):state_hash(states)


@pytest.mark.parametrize('missing',[None,pd.NaT])
def test_unknown_corporate_timestamp_never_authorizes_transition(missing):
    account,action=seeded();apply_record(account,action)
    before=deepcopy(account.__dict__)
    with pytest.raises(ValueError):action.transition('C','ACCOUNTING_EFFECTIVE_DATE',T+pd.Timedelta(days=1),missing,ex_price=10.)
    assert account.__dict__==before
