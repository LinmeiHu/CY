from copy import deepcopy
from dataclasses import replace
import pandas as pd
import pytest
from research.shared_capital_v1.shared_account.engine import Intent, PhysicalAccount
from research.shared_capital_v1.shared_account.price_space import raw_intent
from research.shared_capital_v1.shared_account.corporate_actions import CashDistribution, ShareConversion
from research.shared_capital_v1.ca_execution_audit import holding_intervals, overlap


def test_coordinate_mapping_same_symbol_two_strategies_preserves_money():
    t=pd.Timestamp('2017-06-26 09:30');a=PhysicalAccount('OGR')
    i=Intent('ATRDR','BULL','DEMAND','A','','600622.SH',t-pd.Timedelta(days=1),t,(),123.45,3.,.002,price_basis='NATIVE_COORDINATE')
    r=raw_intent(i,raw_price=20.,coordinate_factor=.15)
    g=replace(r,strategy='OGR',event_id='G')
    a.fund([r,g],{s:1e6 for s in a.strategies},'P0',t)
    assert r.native_requested_notional==pytest.approx(i.native_requested_notional)
    assert a.positions[i.symbol]==pytest.approx(2*123.45*.15)
    assert a.checkpoint(t,'VERIFY')['nav']==pytest.approx(4e6-2*123.45*3*.002)
    with pytest.raises(ValueError,match='identity'):
        raw_intent(i,raw_price=21.,coordinate_factor=.15)
    with pytest.raises(ValueError,match='nonfinite'):
        raw_intent(i,raw_price=float('nan'),coordinate_factor=.15)


@pytest.mark.parametrize('symbol,record,ex,listed,ratio,cash',[('600622.SH','2017-06-29','2017-06-30','2017-07-03',.3,.21),('603368.SH','2020-06-23','2020-06-24','2020-06-29',.4,.68)])
def test_official_timeline_pending_dividend_nav_prefix(symbol,record,ex,listed,ratio,cash):
    snapshots=[]
    for with_future in [False,True]:
        a=PhysicalAccount('OGR');t=pd.Timestamp(record);e=pd.Timestamp(ex)+pd.Timedelta(hours=9,minutes=30)
        i=Intent('ATRDR','BULL','DEMAND','A','',symbol,t-pd.Timedelta(days=1),t,(),100.,20.,0.)
        a.fund([i],{s:1e6 for s in a.strategies},'P0',t)
        before=a.checkpoint(t,'BEFORE')['nav'];shares=ShareConversion(a);dividend=CashDistribution(a)
        shares.record('S',symbol,ratio,t+pd.Timedelta(hours=15),t)
        dividend.record('D',symbol,cash,t+pd.Timedelta(hours=15),t,ex_date=e,payment_date=e)
        price=(20.-cash)/(1+ratio)
        shares.transition('S','ACCOUNTING_EFFECTIVE_DATE',e,t,ex_price=price)
        dividend.pay('D',e,t)
        assert a.checkpoint(e,'EX')['nav']==pytest.approx(before)
        assert a.cash==pytest.approx(4e6-2000+100*cash)
        ca='A|CA|S'
        with pytest.raises(ValueError):a.close(ca,price,e,0.)
        snapshots.append(deepcopy((a.cash,a.lots,a.positions,a.pending_positions)))
        if with_future:
            l=pd.Timestamp(listed)+pd.Timedelta(hours=9,minutes=30)
            shares.transition('S','SHARE_ARRIVAL_DATE',l,t)
            shares.transition('S','TRADABLE_DATE',l,t)
            a.close(ca,price,l,0.)
            assert not a.pending_positions
    assert snapshots[0]==snapshots[1]


def test_dividend_uses_record_holdings_not_payment_holdings():
    a=PhysicalAccount('OGR');t=pd.Timestamp('2020-01-01');pay=t+pd.Timedelta(days=1)
    i=Intent('MCB','MCB','DEMAND','A','','S',t-pd.Timedelta(days=1),t,(),100.,10.,0.)
    a.fund([i],{s:1e6 for s in a.strategies},'P0',t)
    d=CashDistribution(a);d.record('D','S',.5,t,t,ex_date=pay,payment_date=pay)
    a.close('A',10.,t,0.)
    d.pay('D',pay,t)
    assert a.cash==4e6+50
    with pytest.raises(ValueError,match='duplicate'):d.pay('D',pay,t)
    with pytest.raises(ValueError,match='receivable'):d.record('X','S',.5,t,t,ex_date=pay,payment_date=pay+pd.Timedelta(days=1))


def test_audit_record_close_ownership_not_ex_date_overlap():
    t=pd.Timestamp('2020-01-02')
    fills=pd.DataFrame([dict(side='BUY',event_id='A',symbol='600000.SH',entry=t,exit=pd.NaT),dict(side='SELL',event_id='A',symbol='600000.SH',entry=t,exit=t+pd.Timedelta(hours=15))])
    intervals=holding_intervals(fills,t)
    actions=pd.DataFrame([dict(symbol='600000',record_date=t)])
    assert overlap(intervals,actions).empty
    fills.loc[1,'exit']=t+pd.Timedelta(days=1)
    assert len(overlap(holding_intervals(fills,t),actions))==1


def test_official_fact_identity_dates_and_execution_only_boundary():
    from research.shared_capital_v1.run_shared_capital_v1 import HERE
    facts=pd.read_csv(HERE/'output/corporate_action_official_backfill_facts.csv')
    assert not facts[['symbol','action_id','raw_hash']].isna().any().any()
    assert not facts.action_id.duplicated().any()
    for symbol,ex,listing in [('600622.SH','2017-06-30','2017-07-03'),('603368.SH','2020-06-24','2020-06-29')]:
        row=facts.loc[facts.symbol.eq(symbol)&facts.ex_date.eq(ex)].iloc[0]
        assert row.tradable_date==listing and row.cash_payment_date==ex
    assert facts.source_grade.eq('OFFICIAL_EX_POST_EXECUTION_FACT').all()
    assert facts.alpha_use.eq('PROHIBITED').all()
    assert (pd.to_datetime(facts.available_at,utc=True)>pd.to_datetime(facts.ex_date,utc=True)).all()
