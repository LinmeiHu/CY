import unittest
import numpy as np
from .common import pivots,quantity,fee,scenarios

class Semantics(unittest.TestCase):
    def test_matrix(self):
        s=scenarios();self.assertEqual(len(s),70);self.assertEqual(len({x['id'] for x in s}),70);self.assertEqual(sum(x['group'].startswith('OLD') for x in s),20)
    def test_flat_is_not_vcp(self):
        r,legs,_=pivots(np.ones(30),np.ones(30),np.ones(30));self.assertNotEqual(r,'PASS');self.assertEqual(legs,[])
    def test_asof_future(self):
        h=np.array([10,11,14,12,11,10,11,12,13,12,11.5,11,11.5,12,12.5,12,11.8,11.7,12,12.2,12.3,12.1,12,12.05,12.1,12.2,12.1,12.15,12.2,12.1]);l=h-.2
        before=pivots(h,l,np.ones(30));hf=np.r_[h,[1000,1,900]];lf=np.r_[l,[1,.01,500]]
        self.assertEqual(before,pivots(hf[:30],lf[:30],np.ones(30)))
        for leg in before[1]:self.assertEqual(leg['high_confirm'],leg['high']+2);self.assertEqual(leg['low_confirm'],leg['low']+2);self.assertLess(leg['low_confirm'],30)
    def test_double_extreme_skipped(self):
        h=np.array([3,4,7,4,3,4,5.]);l=np.array([2,2,1,2,2,2,2.]);_,legs,amb=pivots(h,l);self.assertIn(2,amb);self.assertEqual(legs,[])
    def test_ties_earliest(self):
        h=np.array([1.,2,5,5,2,1,2,3,2]);l=h-.1
        _,legs,_=pivots(h,l)
        if legs:self.assertEqual(legs[0]['high'],2)
    def test_budget_and_units(self):
        for board in ['MAIN','CHINEXT','STAR']:
            for b in [0.,500.,10000.,1000000.]:
                q=quantity(b,10.03,'2021-06-01',board)
                self.assertTrue(q==0 or q*10.03+fee(q*10.03,'2021-06-01')<=b)
                if board=='STAR':self.assertTrue(q==0 or q>=200)
                else:self.assertEqual(q%100,0)
        self.assertEqual(quantity(2020,10,'2021-01-01','STAR'),201)

class AccountTests(unittest.TestCase):
    def market(self):
        import pandas as pd
        from collections import defaultdict
        from .replay import Market
        m=Market.__new__(Market);m.dates=[str(x.date()) for x in pd.bdate_range('2020-01-01',periods=30)];m.symbols=['000001.SZ','000002.SZ'];m.boards=['MAIN','MAIN'];m.industries=['X'];m.sy={'000001':0,'000002':1};m.records=defaultdict(list);m.exdates={};m.actions=pd.DataFrame()
        m.a={f:np.full((30,2),v) for f,v in dict(open=10.,high=10.5,low=9.5,close=10.,factor=1.,coord=10.,ma10=10.,volume=100000.,trade_status=1.,hard_valid=1.,buy_blocked_open=0.,sell_blocked_open=0.,up_limit_price=11.,down_limit_price=9.,share_multiplier=1.,cash_per_share=0.,rights_ratio=0.,corporate_action_blocking=0.).items()};return m
    def frame(self,t=0,j=0):
        import pandas as pd
        return pd.DataFrame([dict(t=t,j=j,symbol=f'00000{j+1}.SZ',RS=.9,Path=.5,Consolidation=.5,limit=10.6,U=10.2,S0=9.8,factor=1.,amount20=1e9,industry=0)])
    def run_account(self,m,f,exit='FIXED10',delay=1):
        from .replay import replay
        s=dict(id='SYNTHETIC',version='B0',mode='MAX_DEPLOYABLE',delay=delay,cost=1,exit=exit,module='');return replay(m,s,f)
    def test_real_cash_low_open_timing(self):
        m=self.market();nav,tr,orders,_,_=self.run_account(m,self.frame());self.assertEqual(len(tr),1);self.assertEqual(tr.iloc[0].e,1);self.assertEqual(tr.iloc[0].exit_t,11);self.assertTrue(tr.iloc[0].lowopen);self.assertGreaterEqual(nav.cash.min(),0);self.assertTrue(np.allclose(nav.nav,nav.cash+nav.market_value+nav.receivable));self.assertLess(nav.nav.iloc[-1],1e6)
    def test_no_same_auction_recycling(self):
        import pandas as pd
        m=self.market();f=pd.concat([self.frame(),self.frame(10,1)],ignore_index=True);nav,tr,o,_,_=self.run_account(m,f);fills=o[o.status=='FILLED'];self.assertEqual(len(fills),2);self.assertLess(fills.iloc[1].debit,100000);self.assertLessEqual(fills.iloc[1].debit,fills.iloc[1].preauction_cash)
    def test_limits_no_fill(self):
        for field in ['buy_blocked_open','trade_status']:
            m=self.market();m.a[field][1,0]=1 if field=='buy_blocked_open' else 0
            nav,tr,o,_,_=self.run_account(m,self.frame());self.assertEqual(len(tr),0);self.assertEqual(nav.nav.iloc[-1],1e6)
        m=self.market();m.a['open'][1,0]=10.8;_,tr,_,_,_=self.run_account(m,self.frame());self.assertEqual(len(tr),0)
    def test_delayed_exit_and_entry(self):
        m=self.market();m.a['sell_blocked_open'][11:14,0]=1;_,tr,_,_,_=self.run_account(m,self.frame());self.assertEqual(tr.iloc[0].exit_t,14);self.assertEqual(tr.iloc[0].exit_delay,3)
        _,tr,_,_,_=self.run_account(self.market(),self.frame(),delay=2);self.assertEqual(tr.iloc[0].e,2);self.assertEqual(tr.iloc[0].exit_t,12)
    def test_buy_day_close_stop_next_session(self):
        m=self.market();m.a['coord'][1,0]=9.7;_,tr,_,_,_=self.run_account(m,self.frame(),exit='TREND40');self.assertEqual(tr.iloc[0].exit_t,2);self.assertEqual(tr.iloc[0].exit_reason,'STRUCTURE')
    def test_legal_submission_band_and_boundary(self):
        m=self.market();f=self.frame();f.loc[0,'limit']=20.
        _,_,orders,_,_=self.run_account(m,f);self.assertEqual(orders.iloc[0]['limit'],11.)
        m=self.market();m.a['down_limit_price'][1,0]=10.7
        _,tr,orders,_,_=self.run_account(m,self.frame());self.assertEqual(len(tr),0);self.assertEqual(orders.iloc[0].status,'FROZEN_LIMIT_BELOW_LEGAL_RANGE')
        _,_,orders,_,_=self.run_account(self.market(),self.frame(29));self.assertEqual(orders.iloc[0].status,'END_BOUNDARY_NO_ENTRY_SESSION')
    def test_end_remains_open(self):
        _,tr,_,_,op=self.run_account(self.market(),self.frame(25));self.assertEqual(len(tr),0);self.assertEqual(len(op),1)
    def test_preopen_coordinate_does_not_use_entry_close(self):
        m=self.market();_,_,a,_,_=self.run_account(m,self.frame())
        m=self.market();m.a['close'][1,0]=1000.;m.a['factor'][1,0]=.01
        _,_,b,_,_=self.run_account(m,self.frame());self.assertEqual(a.iloc[0]['limit'],b.iloc[0]['limit']);self.assertEqual(a.iloc[0].quantity,b.iloc[0].quantity)
        m=self.market();m.a['coord'][1,0]=np.nan
        _,tr,o,_,_=self.run_account(m,self.frame(),delay=2);self.assertEqual(len(tr),0);self.assertEqual(o.iloc[0].status,'UNRESOLVED_PREOPEN_ACTION')

class CorporateActionTests(AccountTests):
    def test_record_ex_credit_separate(self):
        import pandas as pd
        m=self.market();a=dict(event_id='TEST',symbol='000001',event_type='distribution',known_at=pd.Timestamp(m.dates[1]),record_date=pd.Timestamp(m.dates[2]),effective_date=pd.Timestamp(m.dates[3]),share_credit_date=pd.Timestamp(m.dates[5]),pay_date=pd.Timestamp(m.dates[3]),share_multiplier=1.1,cash_per_share_gross=.2,bonus_share_ratio=.1)
        m.records[m.dates[2]]=[a];m.a['open'][3:,0]=(10-.2)/1.1;m.a['close'][3:,0]=(10-.2)/1.1;m.a['down_limit_price'][3:,0]=7.;m.a['up_limit_price'][3:,0]=11.
        nav,tr,o,audit,_=self.run_account(m,self.frame());self.assertEqual(len(tr),1);self.assertLess(nav.nav.iloc[-1],1e6);self.assertTrue((audit.type=='SHARE_EFFECTIVE').any());self.assertEqual(audit[audit.type=='SHARE_TRADABLE'].day.iloc[0],m.dates[5]);self.assertGreater(nav.tax_reserve.iloc[3],0)
        delta=audit.groupby('day').cash_delta.sum();buys=o[o.status=='FILLED'].set_index('t').debit
        expected=1e6
        for z in nav.itertuples():
            expected+=delta.get(z.date,0)-buys.get(z.t,0);self.assertAlmostEqual(expected,z.book_cash,places=7)

if __name__=='__main__':unittest.main()
