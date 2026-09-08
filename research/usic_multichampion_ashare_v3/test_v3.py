import unittest
from collections import defaultdict
import numpy as np
import pandas as pd
from .common import fee,quantity
from .features import smooth,avwap
from .engine import replay,cash_budgets

class TinyMarket:
    def __init__(self,n=65,z=2):
        self.dates=pd.bdate_range('2020-01-01',periods=n).strftime('%Y-%m-%d').tolist();self.symbols=[f'60000{j}.SH' for j in range(z)];self.boards=['MAIN']*z;self.industries=['X'];self.sy={s[:6]:j for j,s in enumerate(self.symbols)};self.state=np.array(['BULL']*n);self.capacity=np.full((n,z),1e9);self.records=defaultdict(list);self.exdates=defaultdict(list)
        self.a={k:np.full((n,z),v) for k,v in dict(open=10.,high=10.2,low=9.8,close=10.,coord=10.,factor=1.,ma10=9.,up_limit_price=11.,down_limit_price=9.,hard_valid=1.,trade_status=1.,volume=1e8,buy_blocked_open=0.,sell_blocked_open=0.).items()}
    def val(self,f,t,j):return float(self.a[f][t,j])
    def legal(self,t,j,sell=False):
        from .engine import Market
        return Market.legal(self,t,j,sell)

def signal(m,t=0,j=0,S0=9.,A=1.,limit=10.5):
    return dict(t=t,j=j,symbol=m.symbols[j],factor=1.,U=10.,limit=limit,S0=S0,a0=A,amount20=1e8,industry=0,score=1.-j*.1,route='D03',setup_id=f'D03:{j}:{t}',decision_at=m.dates[t]+'T15:00:00+08:00')

def config(mode='C_MAX',exit='FIXED10',overlay='NONE'):
    return dict(id='TEST',delay=1,mode=mode,exit=exit,overlay=overlay,cost=1)

class Invariants(unittest.TestCase):
    def test_indicator_seed_prefix(self):
        x=np.arange(1.,101);y=smooth(x,9);self.assertEqual(y[8],5.);np.testing.assert_array_equal(y[:50],smooth(x[:50],9))
    def test_avwap_units(self):
        self.assertEqual(avwap(np.array([1000.,900.]),np.array([100.,200.]),np.array([0.,1.]),np.array([1.,2.]),[True,True]),4.5)
        self.assertTrue(np.isnan(avwap(np.array([1000.,900.]),np.array([100.,200.]),np.array([0.,1.]),np.array([1.,2.]),[True,False])))
    def test_fee_tax_not_doubled(self):
        self.assertAlmostEqual(fee(1e5,'2020-01-01',True,2)-fee(1e5,'2020-01-01',True),30)
        self.assertEqual(quantity(1000,10,'2020-01-01','MAIN'),0)
        self.assertEqual(quantity(2006,10,'2020-01-01','STAR'),200)
    def test_budget_waterfill_and_cap10_order(self):
        np.testing.assert_allclose(cash_budgets(np.array([100.,900.]),1000.,'C_MAX'),[100.,900.])
        np.testing.assert_allclose(cash_budgets(np.array([100.,100.]),150.,'C_10'),[100.,50.])
    def test_cash_single_security_no_auction_reuse(self):
        m=TinyMarket();f=pd.DataFrame([signal(m,0,0),signal(m,0,1),signal(m,10,1),signal(m,11,1)])
        nav,tr,orders,aud,op,hold=replay(m,config('C_ONE'),f)
        self.assertTrue((nav.cash>=0).all());self.assertLessEqual(nav.holdings.max(),1)
        self.assertEqual(orders[(orders.t==11)&(orders.symbol==m.symbols[1])].status.iloc[0],'SLOTS_OR_RANK')
        self.assertIn(12,orders[orders.status=='FILLED'].t.tolist());self.assertTrue((tr.held_sessions==10).all())
        np.testing.assert_allclose(nav.cash+nav.market_value+nav.receivable,nav.nav,rtol=0,atol=1e-8)
    def test_open_limits_and_no_intraday_fill(self):
        m=TinyMarket();m.a['open'][1,0]=11.;f=pd.DataFrame([signal(m,limit=10.5)])
        nav,tr,orders,*_=replay(m,config(),f);self.assertEqual(orders.status.iloc[0],'LIMIT_OPEN');self.assertEqual(nav.nav.iloc[-1],1e6)
        m=TinyMarket();m.a['open'][1,0]=10.6
        nav,tr,orders,*_=replay(m,config(),pd.DataFrame([signal(m,limit=10.5)]));self.assertEqual(orders.status.iloc[0],'OVER_LIMIT')
    def test_exit_persists_after_rebound_and_t1(self):
        m=TinyMarket();m.a['coord'][1,0]=8.5;m.a['close'][1,0]=8.5;m.a['low'][1,0]=8.
        m.a['open'][2,0]=9.;m.a['down_limit_price'][2,0]=9.
        nav,tr,orders,audit,*_=replay(m,config(exit='TREND40'),pd.DataFrame([signal(m)]))
        self.assertEqual(tr.exit_t.iloc[0],3);self.assertEqual(tr.exit_reason.iloc[0],'STRUCTURE');self.assertEqual(tr.exit_delay.iloc[0],1)
    def test_cap10_and_risk_budget(self):
        m=TinyMarket();f=pd.DataFrame([signal(m,0,j,S0=9.) for j in [0,1]])
        nav,tr,orders,*_=replay(m,config('C_10'),f);self.assertTrue((orders[orders.status=='FILLED'].debit<=1e5+1e-8).all())
        nav,tr,orders,aud,op,hold=replay(m,config(overlay='R_ONCE',exit='TREND40'),f)
        self.assertLessEqual(hold.groupby('date').risk_used.sum().max(),20000+1e-8)
    def test_market_gate_only_new_buys(self):
        m=TinyMarket();m.state[:]='BEAR';nav,tr,orders,*_=replay(m,config(overlay='G_DOWN'),pd.DataFrame([signal(m)]));self.assertEqual(nav.nav.iloc[-1],1e6);self.assertEqual(orders.status.iloc[0],'MARKET_BUDGET_BLOCK')
    def test_once_profitable_add_and_no_downward_add(self):
        m=TinyMarket();m.a['up_limit_price'][:]=20.
        for k in ['close','coord']:m.a[k][1:4,0]=11.;m.a[k][4:,0]=11.3
        m.a['high'][1:4,0]=11.1;m.a['low'][1:4,0]=10.8
        m.a['high'][4:,0]=11.5;m.a['low'][4:,0]=10.9;m.a['open'][5:,0]=11.15
        nav,tr,orders,aud,op,holds=replay(m,config(exit='TREND40',overlay='R_STAGE'),pd.DataFrame([signal(m)]))
        filled=orders[orders.status=='FILLED'];self.assertEqual(len(filled),2)
        self.assertLessEqual(filled.quantity.iloc[1],filled.quantity.iloc[0]/2);self.assertEqual(filled.t.iloc[1],5)
        self.assertTrue((tr.exit_t>filled.t.max()).all());self.assertLessEqual(holds.groupby('date').risk_used.sum().max(),20000)
        m=TinyMarket();nav,tr,orders,*_=replay(m,config(exit='TREND40',overlay='R_STAGE'),pd.DataFrame([signal(m)]));self.assertEqual((orders.status=='FILLED').sum(),1)
    def test_account_future_mutation_prefix(self):
        m=TinyMarket();f=pd.DataFrame([signal(m,0),signal(m,15,1)]);a=replay(m,config(),f)[0]
        m.a['close'][25:]*=2;m.a['coord'][25:]*=2;b=replay(m,config(),f)[0]
        pd.testing.assert_frame_equal(a.iloc[:25],b.iloc[:25])
    def test_corporate_action_shares_cash_nav(self):
        m=TinyMarket();record=m.dates[3];ex=m.dates[4];credit=m.dates[5]
        a=dict(symbol='600000',event_id='hand',event_type='distribution',known_at=pd.Timestamp(record)-pd.Timedelta(days=2),record_date=pd.Timestamp(record),effective_date=pd.Timestamp(ex),share_credit_date=pd.Timestamp(credit),pay_date=pd.Timestamp(ex),share_multiplier=2.,cash_per_share_gross=1.,bonus_share_ratio=0.,source_api='hand',response_sha256='hand')
        m.records[record].append(a);m.exdates[('600000',ex)].append(a)
        for field in ['open','high','low','close'] :m.a[field][4:,0]=(m.a[field][4:,0]-1)/2
        m.a['up_limit_price'][4:,0]=5.;m.a['down_limit_price'][4:,0]=4.;m.a['factor'][4:,0]=10/4.5
        nav,tr,orders,aud,op,hold=replay(m,config('C_10'),pd.DataFrame([signal(m)]))
        initial=int(orders[orders.status=='FILLED'].quantity.iloc[0]);self.assertEqual(hold[hold.t==4].pending.iloc[0],initial);self.assertEqual(hold[hold.t==5].q.iloc[0],initial*2)
        self.assertEqual(int(aud[aud.type=='SELL_FILL'].quantity.iloc[0]),initial*2)
        np.testing.assert_allclose(nav.cash+nav.market_value+nav.receivable,nav.nav,rtol=0,atol=1e-8)

if __name__=='__main__':unittest.main()
