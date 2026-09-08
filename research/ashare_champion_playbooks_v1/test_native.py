import unittest
from collections import defaultdict
import numpy as np,pandas as pd
from .native_engine import replay

class TinyMarket:
    def __init__(self,n=70,z=6):
        self.dates=pd.bdate_range('2020-01-01',periods=n).strftime('%Y-%m-%d').tolist();self.symbols=[f'60000{j}.SH' for j in range(z)];self.boards=['MAIN']*z;self.industries=['X'];self.sy={s[:6]:j for j,s in enumerate(self.symbols)};self.state=np.array(['BULL']*n);self.capacity=np.full((n,z),1e9);self.records=defaultdict(list);self.exdates=defaultdict(list)
        self.a={k:np.full((n,z),v) for k,v in dict(open=10.,high=10.2,low=9.8,close=10.,coord=10.,factor=1.,ma10=9.,up_limit_price=11.,down_limit_price=9.,hard_valid=1.,trade_status=1.,volume=1e8,buy_blocked_open=0.,sell_blocked_open=0.).items()}
    def val(self,f,t,j):return float(self.a[f][t,j])
    def legal(self,t,j,sell=False):
        from research.usic_multichampion_ashare_v3.engine import Market
        return Market.legal(self,t,j,sell)

def sig(m,j=0,t=0,stop=9.,limit=10.5):return dict(t=t,j=j,symbol=m.symbols[j],factor=1.,U=10.,limit=limit,S0=stop,a0=1.,amount20=1e8,industry=0,score=1-j*.01,route='P3B',setup_id=f'P3B:{t}:{j}',decision_at=m.dates[t]+'T15:00:00+08:00')
def cfg():return dict(id='TEST',delay=1,mode='NATIVE',cost=1,exit='NATIVE')

class NativeContract(unittest.TestCase):
    def test_planned_risk_lots_cash_and_aggregate_partial(self):
        m=TinyMarket();f=pd.DataFrame([sig(m,j) for j in range(5)]);nav,tr,o,a,op,h=replay(m,cfg(),f);fills=o[o.status=='FILLED']
        self.assertTrue((fills.planned_risk<=fills.risk_cap/4+1e-7).all());self.assertTrue((fills.quantity%100==0).all());self.assertTrue((nav.cash>=0).all());self.assertTrue((fills.aggregate_risk_after<=fills.risk_cap+1e-7).all());self.assertLess(fills.quantity.iloc[-1],fills.quantity.iloc[0]);self.assertTrue((nav.borrowed_cash==0).all());self.assertTrue((nav.margin==0).all());self.assertTrue((nav.holdings<=5).all())
    def test_invalid_geometry_and_entry_limits(self):
        m=TinyMarket();_,_,o,*_=replay(m,cfg(),pd.DataFrame([sig(m,stop=11)]));self.assertEqual(o.status.iloc[0],'INVALID_RISK_GEOMETRY')
        m=TinyMarket();m.a['open'][1,0]=11.;_,_,o,*_=replay(m,cfg(),pd.DataFrame([sig(m)]));self.assertEqual(o.status.iloc[0],'LIMIT_OPEN')
    def test_t1_stop_gap_and_deferred_limit(self):
        m=TinyMarket();m.a['low'][1,0]=8.;m.a['close'][1,0]=8.5;m.a['coord'][1,0]=8.5;m.a['open'][2,0]=8.;m.a['down_limit_price'][2,0]=7.
        _,tr,_,a,*_=replay(m,cfg(),pd.DataFrame([sig(m)]));self.assertEqual(tr.exit_t.iloc[0],2);self.assertTrue(tr.buy_day_breach.iloc[0]);self.assertLess(tr.realized_r.iloc[0],-1)
        m=TinyMarket();m.a['close'][1,0]=m.a['coord'][1,0]=8.5;m.a['low'][1,0]=8.;m.a['open'][2,0]=m.a['down_limit_price'][2,0]=9.
        _,tr,_,a,*_=replay(m,cfg(),pd.DataFrame([sig(m)]));self.assertEqual(tr.exit_t.iloc[0],3);self.assertIn('LIMIT_OPEN',a[a.type=='EXIT_DEFERRED'].reason.tolist())
    def test_suspension_exit_delay(self):
        m=TinyMarket();m.a['close'][1,0]=m.a['coord'][1,0]=8.5;m.a['trade_status'][2,0]=0
        _,tr,_,a,*_=replay(m,cfg(),pd.DataFrame([sig(m)]));self.assertEqual(tr.exit_t.iloc[0],3);self.assertIn('SUSPENDED_OR_NO_TRADE',a[a.type=='EXIT_DEFERRED'].reason.tolist())
    def test_winner_trail_and_max_hold(self):
        m=TinyMarket();m.a['up_limit_price'][:]=20
        for k in ['close','coord']:m.a[k][3:6,0]=14;m.a[k][6:,0]=9.5
        m.a['high'][3:6,0]=14.2;m.a['low'][3:6,0]=13.8
        _,tr,_,_,_,h=replay(m,cfg(),pd.DataFrame([sig(m)]));self.assertTrue(tr.winner.iloc[0]);self.assertEqual(tr.exit_reason.iloc[0],'WINNER_TRAIL10');self.assertGreaterEqual(tr.stop_coord.iloc[0],tr.S0coord.iloc[0])
        m=TinyMarket(n=70);_,tr,*_=replay(m,cfg(),pd.DataFrame([sig(m)]));self.assertEqual(tr.exit_reason.iloc[0],'MAX60');self.assertEqual(tr.held_sessions.iloc[0],60)
    def test_r_reconciliation_and_determinism(self):
        m=TinyMarket();a=replay(m,cfg(),pd.DataFrame([sig(m)]));b=replay(m,cfg(),pd.DataFrame([sig(m)]));pd.testing.assert_frame_equal(a[0],b[0]);pd.testing.assert_frame_equal(a[1],b[1]);self.assertTrue(np.allclose(a[1].realized_r,a[1].pnl/a[1].initial_planned_r));self.assertTrue(np.allclose(a[0].cash+a[0].market_value+a[0].receivable,a[0].nav))
    def test_company_action_share_credit_and_dividend(self):
        m=TinyMarket();record=m.dates[3];ex=m.dates[4];credit=m.dates[5];x=dict(symbol='600000',event_id='hand',event_type='distribution',known_at=pd.Timestamp(record)-pd.Timedelta(days=2),record_date=pd.Timestamp(record),effective_date=pd.Timestamp(ex),share_credit_date=pd.Timestamp(credit),pay_date=pd.Timestamp(ex),share_multiplier=2.,cash_per_share_gross=1.,bonus_share_ratio=0.,source_api='hand',response_sha256='hand')
        m.records[record].append(x);m.exdates[('600000',ex)].append(x)
        for field in ['open','high','low','close']:m.a[field][4:,0]=(m.a[field][4:,0]-1)/2
        m.a['coord'][4:,0]=10.;m.a['up_limit_price'][4:,0]=5.;m.a['down_limit_price'][4:,0]=4.;m.a['factor'][4:,0]=10/4.5
        nav,tr,o,a,op,h=replay(m,cfg(),pd.DataFrame([sig(m)]));q=int(o[o.status=='FILLED'].quantity.iloc[0]);self.assertEqual(h[h.t==4].pending.iloc[0],q);self.assertEqual(h[h.t==5].q.iloc[0],2*q);self.assertEqual((a.type=='DIVIDEND_PAYMENT').sum(),1);self.assertEqual((a.type=='SHARE_TRADABLE').sum(),1);self.assertTrue(np.allclose(nav.cash+nav.market_value+nav.receivable,nav.nav))

if __name__=='__main__':unittest.main()
