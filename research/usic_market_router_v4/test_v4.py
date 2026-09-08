import unittest
import numpy as np
import pandas as pd
from .features import new_events
from ..usic_multichampion_ashare_v3.features import new_events as old_events
class EventMarket:
    def __init__(self):
        self.n=310;self.symbols=['600000.SH'];self.boards=['MAIN']
        self.dates=pd.bdate_range('2019-01-01',periods=self.n).strftime('%Y-%m-%d').tolist()
        c=np.full(self.n,10.);o=np.full(self.n,10.);h=np.full(self.n,10.1);l=np.full(self.n,9.9)
        # Before the frozen episode the setup upper bound is 10.
        # Day 290 first breaks above 10. Day 291 pulls back below 10 and closes green.
        c[290]=10.6;o[290]=10.2;h[290]=10.7;l[290]=10.1
        c[291]=9.9;o[291]=9.8;h[291]=10.;l[291]=9.7
        self.x=dict(c=c,h=h,l=l,o=o,factor=np.ones(self.n),good=np.ones(self.n,dtype=bool),hist=np.ones(self.n,dtype=bool),e={n:np.full(self.n,10.) for n in [9,10,20,21,50]},atr=np.ones(self.n),amount20=np.full(self.n,1e8))
        self.a={'industry':np.zeros((self.n,1)),'is_st':np.zeros((self.n,1))}
    def symbol(self,j):return self.x

class CorrectionTests(unittest.TestCase):
 def test_breakout_precedes_advance(self):
  m=EventMarket();rank=np.full((m.n,1),.5);nr=[dict(t=290,long=True,VCP_GUARD=True,a0=1.,factor=1.,U=10.,S0=9.,RS=.8,Path=.8,VCP=.8)]
  old,oe=old_events(m,0,rank,rank,[],nr);new,ne=new_events(m,0,rank,rank,[],nr)
  self.assertEqual(oe[0]['advance_t'],291);self.assertEqual(ne[0]['breakout_t'],290);self.assertIsNone(ne[0]['advance_t'])
  self.assertEqual(len([r for r in new if r['route']=='D09']),0)
  m.x['c'][290]=10.;m.x['o'][290]=9.9;m.x['l'][290]=9.8
  new,ne=new_events(m,0,rank,rank,[],nr);self.assertEqual(ne[0]['advance_t'],290)
  m.x['c'][290]=8.9
  new,ne=new_events(m,0,rank,rank,[],nr);self.assertEqual(ne[0]['invalidated_t'],290);self.assertIsNone(ne[0]['advance_t'])
class RouterTests(unittest.TestCase):
 def test_no_overlay_parity_and_fullbook_t1_deferral(self):
  from ..usic_multichampion_ashare_v3.test_v3 import TinyMarket,signal,config
  from .engine import replay
  from .engine_correction import replay as original
  m=TinyMarket();f=pd.DataFrame([signal(m,0),signal(m,5,1)])
  old=original(m,config(),f);new=replay(m,config(),f)
  for a,b in zip(old,new):pd.testing.assert_frame_equal(a,b[a.columns])
  m.v4state=pd.DataFrame({'S1':['HIGH_IMPROVING']*65});m.v4state.loc[2,'S1']='LOW_NONIMPROVING'
  m.a['sell_blocked_open'][3,0]=1
  sc=dict(config(),state_key='S1',blocked_states=['LOW_NONIMPROVING','UNKNOWN'])
  entry=replay(m,sc,f);full=replay(m,dict(sc,book='FULL_BOOK'),f)
  self.assertEqual(entry[1].exit_t.iloc[0],11);self.assertEqual(full[1].exit_t.iloc[0],4)
  self.assertEqual(full[1].exit_reason.iloc[0],'STATE_REDUCE_ZERO');self.assertGreater(full[0].unreduced_exposure.iloc[3],0)
  a=full[0].copy();m.v4state.loc[25:,'S1']='LOW_NONIMPROVING';b=replay(m,dict(sc,book='FULL_BOOK'),f)[0]
  pd.testing.assert_frame_equal(a.iloc[:25],b.iloc[:25])
 def test_delay_freezes_signal_state(self):
  from ..usic_multichampion_ashare_v3.test_v3 import TinyMarket,signal,config
  from .engine import replay
  m=TinyMarket();m.v4state=pd.DataFrame({'S1':['HIGH_IMPROVING']*65});m.v4state.loc[1,'S1']='LOW_NONIMPROVING'
  _,_,orders,*_=replay(m,dict(config(),delay=2,state_key='S1',blocked_states=['LOW_NONIMPROVING']),pd.DataFrame([signal(m,0)]))
  self.assertEqual(orders.status.iloc[0],'FILLED');self.assertEqual(orders.state_t.iloc[0],0)
if __name__=='__main__':unittest.main()
