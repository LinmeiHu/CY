import unittest
from .run import ema
import numpy as np

class ContractTests(unittest.TestCase):
    def test_ema_is_past_only(self):
        x=np.array([[1.],[2.],[3.],[4.]],float); a=ema(x,2); y=x.copy();y[-1]=999
        self.assertTrue(np.allclose(a[:-1],ema(y,2)[:-1],equal_nan=True))

if __name__=='__main__': unittest.main()
