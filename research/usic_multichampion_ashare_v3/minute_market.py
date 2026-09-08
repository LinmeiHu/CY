"""Sparse five-minute execution evidence and full observable prefix marks."""
import math
import numpy as np
import pandas as pd
from .common import OUT,parquet
from .engine import Market

class MinuteMarket(Market):
    def __init__(self):
        super().__init__();self.window={};self.marks=np.full(self.a['close'].shape,np.nan);self.tail_factors=np.full_like(self.marks,np.nan)
        sy={s:i for i,s in enumerate(self.symbols)};ds={d:t for t,d in enumerate(self.dates)}
        frames=[pd.read_parquet(OUT/p) for p in ['Q3_signals.parquet','Q4_BASE_signals.parquet']];keys=set((int(t),int(j)) for f in frames for t,j in zip(f.t,f.j));del frames
        for src in sorted((OUT/'minute').glob('prefix_*.parquet')):
            f=pd.read_parquet(src);f['t']=f.trade_date.astype(str).str[:10].map(ds);f['j']=f.symbol.map(sy);f=f[f.t.notna()&f.j.notna()].copy();f['t']=f.t.astype(int);f['j']=f.j.astype(int)
            valid=(f.n_prefix==206)&(f.n_distinct==206)&(f.invalid_clock==0)&f.valid_ohlcv.fillna(False)&(f.close1425>0)
            self.marks[f.loc[valid,'t'],f.loc[valid,'j']]=f.loc[valid,'close1425']
            mask=[(int(t),int(j)) in keys for t,j in zip(f.t,f.j)]
            for r in f[mask].to_dict('records'):
                self.window[(r['t'],r['j'])]=[dict(clock=int(k),open=float(o),high=float(h),low=float(l),volume=float(v)) for k,o,h,l,v in zip(r['exec_clocks'],r['exec_opens'],r['exec_highs'],r['exec_lows'],r['exec_volumes'])]
        for src in sorted((OUT/'minute').glob('last_execution_bar_*.parquet')):
            f=pd.read_parquet(src);f['t']=f.trade_date.astype(str).str[:10].map(ds);f['j']=f.symbol.map(sy)
            for r in f[f.t.notna()&f.j.notna()].itertuples(index=False):
                key=(int(r.t),int(r.j))
                if key in keys:self.window.setdefault(key,[]).append(dict(clock=875,open=r.open,high=r.high,low=r.low,volume=r.volume))
        for t in range(1,len(self.dates)):
            self.tail_factors[t]=self.a['coord'][t-1]/((self.a['close'][t-1]-self.a['cash_per_share'][t])/self.a['share_multiplier'][t])
    def mark1425(self,t,j):return float(self.marks[t,j])
    def val(self,f,t,j):
        return float(self.tail_factors[t,j]) if f=='factor' else super().val(f,t,j)
    def tail_fill(self,t,j,q,limit,cost):
        upper=self.a['up_limit_price'][t,j];lower=self.a['down_limit_price'][t,j];reason='NO_EXECUTION_WINDOW'
        for bar in sorted(self.window.get((t,j),[]),key=lambda x:x['clock']):
            op=bar['open'];px=math.ceil(op*(1+.0005*cost)*100-1e-8)/100 if np.isfinite(op) else np.nan
            if not all(np.isfinite(bar[x]) for x in ['open','high','low','volume']) or bar['volume']<=0 or op<=0 or bar['low']>op or op>bar['high']:reason='INVALID_MINUTE_EXECUTION';continue
            if op>=upper-1e-6:reason='MINUTE_UPPER_LIMIT_QUEUE_UNVERIFIED';continue
            if px>upper+1e-8 or px<lower-1e-8 or px>bar['high']+1e-6:reason='NO_LEGAL_SLIPPED_MINUTE_PRICE';continue
            if px>limit+1e-8:reason='OVER_LIMIT';continue
            if q>bar['volume']*.05+1e-8:reason='MINUTE_VOLUME_CAP';continue
            return '',op,px,int(bar['clock'])-1
        return reason,np.nan,np.nan,None
