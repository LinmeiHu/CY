import unittest
import math
import numpy as np
import pandas as pd
from .test_v3 import TinyMarket,signal,config
from .tail_engine import replay
from .minute_market import MinuteMarket

class TinyTail(TinyMarket):
    def __init__(self):
        super().__init__();self.marks=np.full((65,2),10.);self.window={(t,j):[dict(clock=871,open=10.,high=10.2,low=9.8,volume=1e8)] for t in range(65) for j in range(2)}
    def mark1425(self,t,j):return self.marks[t,j]
    def tail_fill(self,t,j,q,limit,cost):return MinuteMarket.tail_fill(self,t,j,q,limit,cost)

def sc(mode='C_MAX',exit='FIXED10',holding=1):return dict(config(mode,exit),delay=0,fixed_holding=holding)

class TailTests(unittest.TestCase):
    def test_same_day_breach_only_next_day_exit(self):
        m=TinyTail();m.a['close'][0,0]=8.5;m.a['coord'][0,0]=8.5;m.a['low'][0,0]=8.
        nav,tr,orders,aud,*_=replay(m,sc(exit='TREND40'),pd.DataFrame([signal(m)]));self.assertEqual(tr.exit_t.iloc[0],1);self.assertEqual(orders[orders.status=='FILLED'].t.iloc[0],0)
    def test_morning_settled_proceeds_are_available_at_tail(self):
        m=TinyTail();f=pd.DataFrame([signal(m,0,0),signal(m,1,1)])
        nav,tr,orders,aud,*_=replay(m,sc('C_ONE'),f);self.assertEqual(orders[orders.status=='FILLED'].t.tolist(),[0,1]);self.assertTrue((nav.cash>=0).all());self.assertTrue((tr.held_sessions==1).all())
    def test_daily_future_close_does_not_change_1425_cash_order(self):
        m=TinyTail();f=pd.DataFrame([signal(m,0),signal(m,1,1)]);a=replay(m,sc('C_10',holding=3),f)[2]
        m.a['close'][1,:]=100;m.a['coord'][1,:]=100;b=replay(m,sc('C_10',holding=3),f)[2]
        cols=['t','quantity','reserved','decision_nav','debit'];pd.testing.assert_frame_equal(a[a.status=='FILLED'][cols],b[b.status=='FILLED'][cols])
    def test_first_eligible_window_limit_and_depth(self):
        m=TinyTail();m.window[(0,0)]=[dict(clock=871,open=11.,high=11.,low=11.,volume=1e8),dict(clock=872,open=10.,high=10.2,low=9.9,volume=100.),dict(clock=875,open=10.,high=10.2,low=9.9,volume=1e8)]
        reason,op,price,clock=m.tail_fill(0,0,100,10.5,1);self.assertEqual(reason,'');self.assertEqual(clock,874);self.assertLessEqual(price,10.5)
        self.assertEqual(m.tail_fill(0,0,100,9.9,1)[0],'OVER_LIMIT')
    def test_legal_e3_and_account_prefix(self):
        m=TinyTail();f=pd.DataFrame([signal(m,0),signal(m,20,1)]);a=replay(m,sc(holding=3),f)
        self.assertTrue((a[1].held_sessions==3).all());m.a['close'][30:]*=2;b=replay(m,sc(holding=3),f);pd.testing.assert_frame_equal(a[0].iloc[:30],b[0].iloc[:30])
if __name__=='__main__':unittest.main()
