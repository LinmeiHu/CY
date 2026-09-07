import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).parent))
import state_v2 as st
from account_v2 import policy_events,apply_events
from information_v2 import purged_split,preprocess
from five_strategy_bundle.strategies.smv6 import CashPlatform,Position
from five_strategy_bundle.strategies.atrdr import route_v27_bear
from five_strategy_bundle.execution.daily import replay_sleeves


def example():
    dates=pd.date_range('2020-01-01',periods=7)
    p=pd.DataFrame(dict(trade_date=dates,cal_idx=range(7),coord_open=[100,92,90,94,95,96,98],
                        coord_close=[92,91,94,95,96,97,98],coord_high=[102,94,96,97,98,99,99],
                        coord_low=[90,88,89,92,93,95,97],volume=[1000]*7,sellable_open=[False,True,True,True,True,True,True],
                        state_valid=[True]*7,available_at=dates+pd.Timedelta(hours=15)))
    t=pd.Series(dict(episode_id='E',event_id='E',event_cluster='S|D',route='MCB',segment='CONTINUOUS',symbol='S',sleeve='MAIN',
                     signal_date=dates[0]-pd.Timedelta(days=1),entry_date=dates[0],entry_time=dates[0]+pd.Timedelta(hours=9,minutes=30),entry_cal_idx=0,
                     entry_price=100.,exit_price=98.,native_time=dates[-1]+pd.Timedelta(hours=9,minutes=30),exit_date=dates[-1],exit_cal_idx=6,
                     horizon=15,anchor=95.,anchor_available_at=dates[0]-pd.Timedelta(days=1),qty=10.,entry_outlay=1002.,status='COMPLETED',exit_reason='H15_TIME_STOP'))
    return t,p


def test_prefix_features_and_first_exit_actions_ignore_future_price_and_outcome():
    t,p=example();future=p.copy();future.loc[future.cal_idx>=4,['coord_open','coord_high','coord_low','coord_close']]*=4
    a=st.causal_features(p,t,2.);b=st.causal_features(future,t,2.)
    pd.testing.assert_frame_equal(a.loc[:3,st.BASE+st.EXTRA+['mae_sofar']],b.loc[:3,st.BASE+st.EXTRA+['mae_sofar']])
    e1=policy_events(pd.DataFrame([t]),{'E':a},'fixed',.075)
    t2=t.copy();t2['exit_price']=500.
    e2=policy_events(pd.DataFrame([t2]),{'E':b},'fixed',.075)
    assert e1.decision_at.iloc[0]==e2.decision_at.iloc[0]
    assert e1.exit_time_policy.iloc[0]==e2.exit_time_policy.iloc[0]
    assert e1.exit_price_policy.iloc[0]==e2.exit_price_policy.iloc[0]==92
    assert len(e1)==1  # one first trigger, never one payoff per position day
    ledgers=[]
    for trade,path,events in [(t,a,e1),(t2,b,e2)]:
        source=pd.DataFrame([trade]).assign(r1=1.,r2=1.,r3=1.)
        changed=apply_events(source,source,events,'fixed')
        _,_,nav,_=replay_sleeves(changed,path.assign(symbol='S'),rank_columns=('r1','r2','r3'),k_per_sleeve=1,daily_cap=1)
        ledgers.append(nav.loc[nav.trade_date.lt(p.trade_date.iloc[4])].reset_index(drop=True))
    pd.testing.assert_frame_equal(ledgers[0],ledgers[1])  # past cash, inventory marks, NAV unchanged


def test_recovering_final_loser_should_not_be_sold_and_buy_cost_is_common_history():
    t,p=example();x=st.exit_at_state(t,p,p.trade_date.iloc[0]+pd.Timedelta(hours=16))
    immediate=x['exit_price_policy']*.998*t.qty
    native=t.exit_price*.998*t.qty
    assert t.exit_price/t.entry_price-1<0
    assert (immediate-native)/(t.qty*92)<0
    assert immediate-native==pytest.approx((92-98)*.998*10)  # no second buy fee


def test_t1_gap_locked_retry_native_priority_and_no_intraday_touch_execution():
    t,p=example();p.loc[1,'sellable_open']=False;p.loc[2,'coord_open']=97
    x=st.exit_at_state(t,p,p.trade_date.iloc[0]+pd.Timedelta(hours=16))
    assert x['exit_time_policy']==p.trade_date.iloc[2]+pd.Timedelta(hours=9,minutes=30)
    assert x['exit_price_policy']==97 and x['unfilled']==1  # latched despite recovery
    p['coord_close']=100;p['coord_low']=50;p['coord_high']=200
    f=st.causal_features(p,t,2.)
    e=policy_events(pd.DataFrame([t]),{'E':f},'fixed',.1)
    assert not e.triggered.iloc[0]  # daily same-bar high/low not an executable state signal
    t.native_time=p.trade_date.iloc[1]+pd.Timedelta(hours=9,minutes=30)
    assert not st.exit_at_state(t,p,p.trade_date.iloc[0]+pd.Timedelta(hours=16))['filled']


def test_missing_anchor_no_phantom_state_and_atr_requires_exact_prior_sessions():
    t,p=example();t.anchor=np.nan
    f=st.causal_features(p,t,2.)
    assert len(f)==len(p) and f.anchor_below_run.isna().all()
    d=pd.concat([p]*4,ignore_index=True).iloc[:21].copy();d['trade_date']=pd.date_range('2019-01-01',periods=21);d['cal_idx']=range(21)
    for c in ['hard_valid','history_valid','current_valid']:d[c]=True
    d['invalid_step_cum']=0.
    assert np.isfinite(st.entry_atr(d,pd.Timestamp('2020-01-01'),0.))
    d.loc[10,'cal_idx']=50
    assert np.isnan(st.entry_atr(d,pd.Timestamp('2020-01-01'),0.))


def test_purge_episode_overlapping_labels_and_training_only_preprocessing():
    d=pd.DataFrame(dict(episode_id=['A','A','B','C'],event_cluster=['X','X','Y','Z'],
                        entry_date=pd.to_datetime(['2019-12-01','2019-12-01','2019-01-01','2020-01-01']),
                        label_available_at=pd.to_datetime(['2020-01-04','2020-01-04','2019-02-01','2020-02-01']),x=[2.,3.,4.,1e9]))
    train,test=purged_split(d,2020)
    assert train.episode_id.tolist()==['B'] and test.episode_id.tolist()==['C']
    *_,prep=preprocess(train,test,['x'])
    assert prep['median']['x']==prep['mean']['x']==4.


def test_dividend_cash_only_while_still_entitled_and_censored_is_not_zero():
    t,p=example();t['cash_events_json']='[{"date":"2020-01-03","cash_per_share":1.5}]'
    assert st.cash_per_share(t,'2020-01-02')==0 and st.cash_per_share(t,'2020-01-07')==1.5
    t.native_time=pd.NaT;t.exit_price=np.nan;t.exit_cal_idx=np.nan
    e=policy_events(pd.DataFrame([t]),{'E':st.causal_features(p,t,2.)},'fixed',.075)
    assert not e.mature.iloc[0] and np.isnan(e.advantage_return.iloc[0]) and e.filled.iloc[0]


def platform(cash=1002.):
    p=CashPlatform({}, {},pd.DataFrame(columns=['trade_date','symbol']),[pd.Timestamp('2020-01-02')],initial_cash=cash,lot_size=100,fee_bps=20)
    p.event_stage='open';p._current_row=lambda _:SimpleNamespace(executable_09_30=True,executable_15_00=True)
    p._mark=lambda *_:10.;p._volume_cap=lambda *_:100;p.slippage_total=0.
    return p


def test_actual_smv_partial_position_and_fee_reserved_cash_cannot_double_spend():
    p=platform();p.order_target_percent('S',1.)
    assert p.shares['S']==100 and p.cash==pytest.approx(0)
    p.order_target_percent('OTHER',1.)
    assert 'OTHER' not in p.shares and p.cash>=-1e-8
    p.shares['S']=200;p.order_target('S',0)
    assert p.shares['S']==100 and p.events[-1]['event_type']=='SELL_PARTIAL'
    p.order_target('S',0)
    assert 'S' not in p.shares and p.events[-1]['event_type']=='SELL_FILLED'


def test_current_production_slow_completion_filter_reproduces_known_prefix_defect(tmp_path):
    fields=['event_id','symbol','sleeve','signal_date','entry_date','entry_cal_idx','entry_price','exit_date','exit_cal_idx','exit_price','exit_reason','holding_sessions','gross_return','net_return','market_regime','market_median_ret20','market_median_ret60','latest_source_timestamp',
            'stock_minus_industry_ret20','close_vs_prior10_high','close_location_x']
    fast=pd.DataFrame(columns=fields)
    slow=pd.DataFrame([dict(event_id='S',symbol='600001.SH',sleeve='MAIN',signal_date=pd.Timestamp('2020-01-01'),entry_date=pd.Timestamp('2020-01-02'),entry_cal_idx=2,entry_price=10.,exit_date=pd.NaT,exit_cal_idx=np.nan,exit_price=np.nan,exit_reason=None,holding_sessions=np.nan,gross_return=np.nan,net_return=np.nan,status='INCOMPLETE_PATH',market_regime='BEAR')])
    candidates=pd.DataFrame([dict(event_id='S',exact_prior20_return=-.2,last5_downside_turnover=.001,previous5_downside_turnover=.01,close_location=.8)])
    market=pd.DataFrame([dict(trade_date=pd.Timestamp('2020-01-01'),market_median_ret20=-.04,market_median_ret60=-.06,latest_source_timestamp=pd.Timestamp('2020-01-01 15:00'))])
    before=route_v27_bear(fast,slow,candidates,market,tmp_path/'before.parquet')
    slow['status']='COMPLETED';slow['exit_date']=pd.Timestamp('2020-02-03')
    after=route_v27_bear(fast,slow,candidates,market,tmp_path/'after.parquet')
    assert before.empty and after.event_id.tolist()==['S']  # a confirmed failing invariant, NOT prefix PASS


def test_policy_regenerates_full_opportunities_without_future_funding_or_same_episode_loop():
    t,p=example();t['r1']=t['r2']=t['r3']=1.
    second=t.copy();second.event_id='NEW';second.symbol='OTHER';second.entry_date=p.trade_date.iloc[1];second.entry_price=92.;second.exit_price=98.
    t.exit_reason='TARGET_15'
    source=pd.DataFrame([t,second])
    daily=pd.concat([p.assign(symbol=s) for s in ['S','OTHER']])
    a,s,_,_=replay_sleeves(source,daily,rank_columns=('r1','r2','r3'),k_per_sleeve=1,daily_cap=1)
    assert a.event_id.tolist()==['E']
    f=st.causal_features(p,t,2.);e=policy_events(pd.DataFrame([t]),{'E':f},'fixed',.075)
    changed=source.copy();changed.loc[changed.event_id.eq('E'),'exit_date']=e.exit_time_policy.iloc[0].normalize()
    changed.loc[changed.event_id.eq('E'),'exit_price']=e.exit_price_policy.iloc[0]
    changed.loc[changed.event_id.eq('E'),'exit_reason']='SHADOW_OPEN_FIXED'
    a,_,n,_=replay_sleeves(changed,daily,rank_columns=('r1','r2','r3'),k_per_sleeve=1,daily_cap=1)
    assert a.event_id.tolist()==['E','NEW'] and n.cash.min()>=-1e-10


def test_known_cash_action_is_not_a_structural_break_or_price_loss():
    t,p=example();p['coord_close']=100.;p['coord_high']=102.;p['coord_low']=99.
    p['cash_accrued_per_share']=0.
    p.loc[2:,['coord_close','coord_high','coord_low']]-=10
    p.loc[2:,'cash_accrued_per_share']=10.
    f=st.causal_features(p,t,2.)
    assert f.current_pnl.eq(0).all() and f.anchor_below_run.eq(0).all()
    assert f.mfe_sofar.iloc[-1]==pytest.approx(.02)
    assert not st.policy_mask(f,'fixed',.075).any()


def test_next_open_marketable_native_target_wins_and_later_low_is_excluded():
    t,p=example();t.native_time=p.trade_date.iloc[1]+pd.Timedelta(hours=16)
    t.exit_reason='TARGET_15';t.exit_price=110.;p.loc[1,'coord_open']=115.
    x=st.exit_at_state(t,p,p.trade_date.iloc[0]+pd.Timedelta(hours=16))
    assert not x['filled'] and x['exit_price_policy']==110.
    p['cash_accrued_per_share']=0.;p.loc[1,'coord_low']=1.
    held=p.iloc[:1];state=SimpleNamespace(**held.iloc[0].to_dict())
    assert st.forward_observed_downside(t,held,state)==pytest.approx(110/92-1)


def test_smv_native_close_finishes_remaining_exit_inventory_with_volume_cap():
    from smv6_v2 import inventory_exit,event_time
    day=pd.Timestamp('2020-01-01');date=day+pd.Timedelta(days=1)
    av=SimpleNamespace(executable_09_30=True,executable_15_00=True)
    p=SimpleNamespace(availability={(date.date(),'S'):av},minute_rows={'S':{(date.date(),'OPEN_BAR_09_30'):(0,10.,200.),(date.date(),'FINAL_CLOSE_BAR'):(0,9.,200.)}},
                      minute_volume_limit=.5,lot_size=100,slippage_total=0.,commission_rate=.002)
    events=pd.DataFrame([dict(trade_date=date,stage='close',event_type='SELL_FILLED')])
    cash,when,failed,partial,remaining=inventory_exit(p,'S',200.,day,[date],events)
    assert when==date+pd.Timedelta(hours=15) and remaining==0 and partial==1
    assert cash==pytest.approx((100*10+100*9)*.998)
    assert event_time(dict(trade_date=date,stage='open'))==date+pd.Timedelta(hours=9,minutes=30)


def test_not_applicable_feature_does_not_count_as_out_of_domain():
    train=pd.DataFrame(dict(episode_id=['A','B'],x=[1.,3.],unavailable=[np.nan,np.nan]))
    test=pd.DataFrame(dict(episode_id=['C'],x=[2.],unavailable=[np.nan]))
    _,_,_,domain,prep=preprocess(train,test,['x','unavailable'])
    assert not domain.any() and prep['not_applicable_columns']==['unavailable']


def test_account_decomposition_independently_detects_wrong_nav_delta():
    from account_v2 import accounting_decomposition
    a=pd.DataFrame([dict(event_id='A',symbol='S',qty=.01,entry_price=10.,entry_outlay=.1002,exit_price=11.,exit_date=pd.Timestamp('2020-01-03'))])
    b=a.copy();b['exit_price']=12.
    daily=pd.DataFrame(dict(symbol=['S'],trade_date=pd.to_datetime(['2020-01-03']),coord_close=[12.]))
    expected=.01*(12-11)*.998
    result=accounting_decomposition('MCB',a,b,daily,pd.Timestamp('2020-01-03'),expected)
    assert abs(result['decomposition_residual'])<1e-12
    with pytest.raises(AssertionError):accounting_decomposition('MCB',a,b,daily,pd.Timestamp('2020-01-03'),expected+.01)


def test_metric_window_does_not_fill_unknown_nav_and_accepts_native_date_type():
    from account_v2 import nav_metrics
    n=pd.DataFrame(dict(trade_date=[pd.Timestamp('2020-01-01').date(),pd.Timestamp('2020-01-02').date(),pd.Timestamp('2020-01-03').date()],
                        nav=[1.,np.nan,1.1],gross_exposure=[.1,np.nan,.1]))
    with pytest.raises(ValueError):nav_metrics(n)
    n['nav']=[1.,1.05,1.1]
    assert nav_metrics(n,'2020-01-02','2020-01-03')['total_return']==pytest.approx(.1)
