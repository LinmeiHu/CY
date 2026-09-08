from dataclasses import replace
import pandas as pd
import pytest
from research.portfolio_closure_v1.repair import capital_state, classify
from research.portfolio_closure_v1.shadow import path_metrics
from research.shared_capital_v1.shared_account.engine import Intent, PhysicalAccount
from research.shared_capital_v1.shared_account.allocator import proportional_cash
from research.shared_capital_v1.shared_account.scheduler import Event, run_streams


def intent(eid='buy',qty=10):
    return Intent('ATRDR','BULL','DEMAND',eid,'','000001.SZ',pd.Timestamp('2020-01-01 15:00'),pd.Timestamp('2020-01-02 09:30'),(0,),qty,10.,.002)


@pytest.mark.parametrize('before,after,want',[(100,50,'EXPOSURE_REDUCTION'),(100,0,'EXPOSURE_REDUCTION'),(0,100,'EXPOSURE_INCREASE'),(100,120,'EXPOSURE_INCREASE'),(100,100,'NO_CAPITAL_CHANGE')])
def test_only_increases_create_capital_demand(before,after,want):
    assert classify(before,after)==want


def test_existing_market_value_is_not_cash_or_headroom():
    a=PhysicalAccount('OGR',initial_cash=1000)
    a._fill(intent(qty=70),1000,'BASE',pd.Timestamp('2020-01-02 09:30'))
    s=capital_state(a,'2020-01-02 10:00')
    assert s['cash_before_event']==pytest.approx(298.6)
    assert s['long_market_value_before_event']==700
    assert s['legal_fundable_notional']==pytest.approx(298.6)
    assert s['gross_headroom_before_event']==pytest.approx(s['NAV_before_event']-700)


def test_later_sell_cannot_fund_earlier_buy_and_prefix_invariant():
    def run(end):
        a=PhysicalAccount('OGR',initial_cash=1000)
        a._fill(intent(qty=70),1000,'BASE',pd.Timestamp('2020-01-02 09:30'))
        seen=[]
        events=[Event('2020-01-03 09:35','ENTRY','ATRDR','first',lambda:seen.append(capital_state(a,'2020-01-03 09:35'))),
                Event('2020-01-03 10:10','EXIT','ATRDR','sell',lambda:a.close('buy',11.,'2020-01-03 10:10',.002)),
                Event('2020-01-03 14:25','ENTRY','ATRDR','later',lambda:seen.append(capital_state(a,'2020-01-03 14:25')))]
        run_streams([[e for e in events if pd.Timestamp(e.when)<=pd.Timestamp(end)]])
        return seen
    prefix=run('2020-01-03 09:35');full=run('2020-01-03 15:00')
    assert prefix==full[:1]
    assert full[0]['cash_before_event']<full[1]['cash_before_event']


def test_simultaneous_pro_rata_uses_requested_cash_bill():
    p=proportional_cash(100,{'a':150,'b':50})
    assert float(p['a'])==75 and float(p['b'])==25


def test_marked_pnl_path_includes_cash_dividend_and_fees():
    entry=pd.Timestamp('2020-01-01 09:30');exit=pd.Timestamp('2020-01-03 09:30')
    # 100 outlay including fee; 9.8 dividend-adjusted market loss plus 10 cash
    # dividend leaves +0.2, then a +4 realized terminal cash P&L.
    p=[dict(timestamp=entry,pnl=-.2,exposure=99.8),dict(timestamp=pd.Timestamp('2020-01-02 15:00'),pnl=.2,exposure=90.2),dict(timestamp=exit,pnl=4.,exposure=0.)]
    r=path_metrics(p,100,entry,exit)
    assert r['pre_exit_MFE']==pytest.approx(.002)
    assert r['pre_exit_MAE']==pytest.approx(-.002)
    assert r['native_realized_return']==.04
    assert r['capital_days']>0


def test_right_censoring_never_invents_an_exit():
    t=pd.Timestamp('2026-09-04 09:30')
    r=path_metrics([dict(timestamp=t,pnl=-1.,exposure=99.)],100,t,None)
    assert r['native_realized_return'] is None
    assert r['open_at_cutoff'] and r['marked_pnl_at_cutoff']==-1
