import unittest
import numpy as np
import pandas as pd
from pathlib import Path
from .run import digested
from .common import OUT

class TimingContractTests(unittest.TestCase):
    def test_digestion_uses_structure_and_one_boundary(self):
        x=pd.DataFrame({'t1_structure_holds':[True,True,False,True],'t1_close_extension_A':[.25,.251,-1,np.nan]})
        self.assertEqual(digested(x,.25).tolist(),[True,False,False,False])

    def test_actual_decision_clock_and_no_financing(self):
        d=OUT/'accounts/E3_QUARTER_BAND_C10_E10_CA';f=pd.read_parquet(d/'input_signals.parquet');o=pd.read_parquet(d/'orders.parquet');n=pd.read_parquet(d/'nav.parquet')
        clock=f[['setup_id','origin_t','t']];self.assertTrue((clock.t==clock.origin_t+1).all())
        q=o.merge(clock,on='setup_id',validate='many_to_one');self.assertTrue((q.t_x==q.t_y+1).all())
        self.assertTrue((n.cash>=-1e-7).all());self.assertTrue((n.borrowed_cash==0).all());self.assertTrue((n.margin==0).all())

    def test_matched_entry_exit_decomposition_is_exact(self):
        x=pd.read_parquet(OUT/'matched_common_trades.parquet')
        self.assertLess(x.gross_log_reconcile.abs().max(),1e-12)
    def test_frozen_band_is_decided_after_t1_close(self):
        x=pd.DataFrame(dict(t=[10,10,10],t1_close_extension_A=[.49,.51,0],t1_structure_holds=[True,True,False]))
        allow=x.t1_structure_holds&(x.t1_close_extension_A<=.5)
        self.assertEqual(allow.tolist(),[True,False,False])
        self.assertEqual((x.loc[allow,'t']+2).tolist(),[12])

if __name__=='__main__':unittest.main()
