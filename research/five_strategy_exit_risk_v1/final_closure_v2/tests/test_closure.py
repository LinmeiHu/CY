import json
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import run_closure as run
from compare_accounts import combine
from five_strategy_bundle.strategies import smv6

def platform(price=80.,volume=400.):
    dates=pd.bdate_range('2020-01-01',periods=24)
    d=pd.DataFrame(dict(trade_date=dates,pre_adj_open=100.,pre_adj_high=101.,pre_adj_low=99.,pre_adj_close=100.,
                        volume_raw=10000.,amount_cny=1e6,row_status='VALID')).set_index('trade_date')
    m=pd.DataFrame([dict(trade_date=x.date(),bar_role=role,pre_adj_open=price,pre_adj_close=price,volume_shares=volume)
                   for x in dates for role in ['OPEN_BAR_09_30','FINAL_CLOSE_BAR','PSEUDO_CLOSE_14_57_OPEN']])
    av=pd.DataFrame([dict(trade_date=x.date(),symbol='510300.SH',executable_09_30=True,executable_15_00=True,tail_signal_available_14_57=True) for x in dates])
    p=run.OverlayPlatform({'510300.SH':d},{'510300.SH':m},av,list(dates),initial_cash=1e6,lot_size=100,fee_bps=0)
    ns=smv6.frozen_namespace(p);ns['init'](SimpleNamespace())
    p.current_date=dates[-1].date();p.event_stage='open'
    p.positions['510300.SH']=smv6.Position('510300.SH',.5,dates[-2].date(),100.)
    p.shares['510300.SH']=500;p.cash=950000.
    p.policy=dict(candidate_id='FIXED_5_PERCENT',family='fixed',value=.05)
    p.pending={'510300.SH':dict(trigger_at=dates[-2]+pd.Timedelta(hours=16))}
    return p

def test_frozen_source_is_authority_and_no_golden_production_input():
    assert smv6.source_sha256()==smv6.FROZEN_SHA256
    text=(HERE/'run_closure.py').read_text()
    body=text.split('def replay(')[1].split('def episodes')[0]
    assert 'frozen_namespace(platform)' in body and 'read_parquet' not in body
    identity=json.loads((HERE/'baseline_identity.json').read_text())
    assert identity['full_sealed_strategy_events']==779 and identity['full_sealed_account_days']==3260
    assert identity['source_generated_prefix_matches'] and identity['native_nav_matches_authoritative_prefix']

def test_contract_frozen_before_first_replay():
    cfg=json.loads((HERE/'run_config.json').read_text())
    receipt=json.loads((HERE/'contract_freeze_receipt.json').read_text())
    began=json.loads((Path(cfg['external_root'])/'replay_started.json').read_text())
    assert pd.Timestamp(receipt['frozen_at'])<pd.Timestamp(began['time'])
    assert receipt['sha256']==began['contract_sha256']==run.sha(HERE/'smv6_exit_candidate_contract.json')
    assert receipt['sha256']==run.sha(HERE.parent/'smv6_exit_candidate_contract.json')

def test_existing_profit_definition_not_new_trailing_parameter():
    p=pd.DataFrame(dict(mfe_sofar=[.049,.05,.2],current_pnl=[-.1,0,.01]))
    assert run.st.policy_mask(p,'profit',0).tolist()==[False,True,False]

def test_future_daily_values_do_not_change_current_feature():
    p=platform();p.current_date=p.calendar[-2].date()
    first=p.completed_features('510300.SH')
    d=p.feature_daily['510300.SH'];d.loc[d.trade_date.gt(pd.Timestamp(p.current_date)),['coord_high','coord_low','coord_close']]=[1e8,1.,1e8]
    pd.testing.assert_frame_equal(first,p.completed_features('510300.SH'))

def test_entry_atr_requires_completed_consecutive_history():
    p=platform();d=p.feature_daily['510300.SH'];date=d.trade_date.iloc[-2]
    assert run.st.entry_atr(d,date,0)==2.
    broken=d.drop(d.index[3]);assert np.isnan(run.st.entry_atr(broken,date,0))

def test_gap_through_actual_price_fees_slippage_and_lots():
    p=platform();p.risk_open();e=p.events[-1]
    assert e['price_pre_adj']==80*(1-.0008)
    assert e['price_pre_adj']<95.
    assert e['fee']==pytest.approx(200*80*(1-.0008)*.0002)
    assert e['filled_delta_qty']==-200 and e['filled_delta_qty']%100==0
    assert e['event_type']=='SELL_PARTIAL' and p.shares['510300.SH']==300
    assert '510300.SH' in p.pending

def test_volume_cap_cannot_be_consumed_twice_at_same_minute():
    p=platform();p.risk_open();cash=p.cash;p.risk_open()
    assert p.cash==cash and p.shares['510300.SH']==300
    assert p.events[-1]['event_type']=='SELL_NO_FILL'

def test_no_same_uncompleted_bar_or_t0_exit():
    p=platform();p.positions['510300.SH'].entry_date=p.current_date
    p.risk_open();assert p.shares['510300.SH']==500 and not p.events

def test_missing_minute_availability_fails_closed():
    p=platform();p.availability={};p.risk_open()
    assert p.shares['510300.SH']==500 and p.events[-1]['event_type']=='RISK_SELL_NO_FILL'

def test_full_exit_then_next_legal_native_entry_allowed():
    p=platform(volume=100000.);p.suppressed={'510300.SH'};p.risk_open()
    assert '510300.SH' not in p.shares
    p.order_target_percent('510300.SH',.5);assert '510300.SH' not in p.shares
    p.suppressed=set();p.volume_used={}
    p.order_target_percent('510300.SH',.5)
    assert p.shares['510300.SH']>0 and p.cash>=0

def test_cash_affordability_and_no_hidden_financing():
    p=platform(volume=1e9);p.shares={};p.positions={};p.pending={};p.cash=101.
    p.order_target_percent('510300.SH',1.)
    assert p.cash==101. and not p.shares
    assert smv6.affordable_lot_quantity(8000.,80.,.0002,100)==0

def test_missing_nav_not_imputed():
    n=pd.DataFrame(dict(trade_date=pd.date_range('2020-01-01',periods=3),nav=[1.,np.nan,1.1],cash=[1.,np.nan,1.1],gross_exposure=0.))
    m=run.account_metrics(n,'2020-01-01','2020-01-03')
    assert m['metric_status']=='PARTIAL_PATH_METRICS_NOT_ESTIMABLE' and 'MaxDD' not in m
    assert m['total_return']==pytest.approx(.1)

def sleeve(values):
    return pd.DataFrame(dict(trade_date=pd.date_range('2020-01-01',periods=len(values)),nav=values,cash=values,gross_exposure=0.))

def test_initial_equal_sleeves_not_daily_rebalanced():
    n,_,_=combine(dict(ATRDR=sleeve([2.,1.]),MCB=sleeve([1.,2.]),OGR=sleeve([1.,1.]),SMV6=sleeve([1e6,1e6])), '2020-01-01','2020-01-02')
    assert n.nav.tolist()==[1.25,1.25]
    daily_rebalanced=1.25*(1+(-.5+1.+0+0)/4)
    assert n.nav.iloc[-1]!=daily_rebalanced

def test_gap_family_exclusion():
    with pytest.raises(AssertionError):combine(dict(ATRDR=sleeve([1]),MCB=sleeve([1]),OGR=sleeve([1]),IFCGR=sleeve([1])),'2020-01-01','2020-01-01')

def test_no_silent_calendar_intersection():
    with pytest.raises(AssertionError):combine(dict(ATRDR=sleeve([1,1]),MCB=sleeve([1]),OGR=sleeve([1,1]),SMV6=sleeve([1e6,1e6])),'2020-01-01','2020-01-02')

def test_two_portfolio_periods_remain_separate():
    p=pd.read_csv(HERE/'portfolio_exit_overlay_comparison.csv')
    assert set(p.period)=={'2018_2021','2022_2023'}
    assert p.groupby(['portfolio','period']).start.nunique().max()==1
    assert p.groupby(['portfolio','period']).end.nunique().max()==1
    assert not p.variant.eq('ATRDR_FAST5_DIAGNOSTIC_ONLY').empty

def test_released_capital_cashflow_reconciles_and_reentry_exists():
    d=pd.read_csv(HERE/'smv6_cashflow_decomposition.csv')
    assert d.reconciliation_error.abs().max()<1e-7
    t=pd.read_csv(HERE/'smv6_released_capital_trades.csv')
    assert len(t)>0

def test_frozen_inputs_and_replay_are_deterministic():
    d=json.loads((HERE/'integrity_validation.json').read_text());assert d['mismatches']==[]
    d=json.loads((HERE/'determinism.json').read_text());assert d['status']=='PASS' and d['core_outputs']==35
