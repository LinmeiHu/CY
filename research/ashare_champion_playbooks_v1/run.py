"""Frozen daily playbook signal producer; no account outcomes are read."""
import argparse,sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.usic_multichampion_ashare_v3.engine import Market

HERE = Path(__file__).resolve().parent
OUT = Path("/Volumes/quant/CY_quant_research/ashare_champion_playbooks_v1")


def ema(x, span):
    return pd.DataFrame(x).ewm(span=span, adjust=False, min_periods=span).mean().to_numpy()


def signals(m):
    a = m.a; close, high, low = a['close'], a['high'], a['low']
    n, z = close.shape
    e9, e21, e50 = ema(close, 9), ema(close, 21), ema(close, 50)
    rs = np.full((n,z), np.nan); rs[60:] = close[60:] / close[:-60] - 1
    rsrank = np.full((n,z), np.nan)
    for t in range(60,n): rsrank[t] = pd.Series(rs[t]).rank(pct=True).to_numpy()
    valid = (a['hard_valid']==1)&(a['is_st']==0)&(a['trade_status']==1)&np.isfinite(close)&(close>0)
    rows = {k:[] for k in ('P1_NATIVE','P3B_NATIVE','P4_NATIVE')}
    for t in range(61,n-1):
        if m.dates[t] < '2020-01-01': continue
        good = valid[t] & (e9[t]>e21[t]) & (e21[t]>e50[t]) & (e21[t]>e21[t-5]) & (e50[t]>e50[t-5]) & (rsrank[t]>=.9)
        medamt=np.nanmedian(a['amount'][t-20:t],axis=0)
        p3=valid[t]&np.isfinite(medamt)&(medamt>0)&(a['open'][t]>=a['preclose'][t]*1.10)&(a['amount'][t]>=3*medamt)&(close[t]>=(high[t]+low[t])/2)
        for j in np.flatnonzero(p3):
            atr=float(np.nanmean(high[t-20:t,j]-low[t-20:t,j]))
            prior=np.diff(np.log(close[t-60:t,j]))
            common=dict(t=t,j=int(j),symbol=m.symbols[j],factor=float(a['factor'][t,j]),U=float(high[t,j]),a0=atr,amount20=float(medamt[j]),industry=int(a['industry'][t,j]),decision_at=m.dates[t]+'T15:00:00+08:00')
            rows['P3B_NATIVE'].append(dict(common,route='P3B',setup_id=f'P3B:{t}:{j}',score=float(a['amount'][t,j]/medamt[j]),limit=float(close[t,j]*1.03),S0=float(low[t,j]),prior60_return=float(close[t-1,j]/close[t-60,j]-1),prior60_volatility=float(np.nanstd(prior,ddof=1))))
        for j in np.flatnonzero(good):
            # Values are frozen at t close; each row fills through V3 at t+1 open.
            event = np.any(close[max(0,t-10):t+1,j] > np.maximum.accumulate(high[max(0,t-30):t-10,j]).max()) if t>=30 else False
            pivot = high[t-5:t,j].max()
            common = dict(t=t,j=int(j),symbol=m.symbols[j],factor=float(a['factor'][t,j]),U=float(high[t,j]),a0=float(np.nanmean(high[t-20:t,j]-low[t-20:t,j])),amount20=float(np.nanmedian(a['amount'][t-20:t,j])),industry=int(a['industry'][t,j]),decision_at=m.dates[t]+'T15:00:00+08:00')
            if event:
                episode = (low[t-9:t+1,j] <= e21[t-9:t+1,j]) | (close[t-9:t+1,j] <= e9[t-9:t+1,j])
                first = np.flatnonzero(episode)
                if len(first) and first[0] < 9 and close[t,j] > high[t-1,j] and close[t,j] > e50[t,j]:
                    stop = low[t-9+first[0]:t+1,j].min()
                    rows['P1_NATIVE'].append(dict(common, route='P1', setup_id=f'P1:{t}:{j}', score=float(rsrank[t,j]), limit=float(close[t,j]*1.03), S0=float(stop)))
            # P4 is an explicit union of existing early strength, first crossback, continuation.
            crossback = close[t-1,j] <= e9[t-1,j] and close[t,j] > e9[t,j]
            continuation = close[t,j] > pivot and close[t-1,j] <= pivot
            if event or crossback or continuation:
                stop = min(low[t-5:t+1,j].min(), e50[t,j])
                rows['P4_NATIVE'].append(dict(common, route='P4', setup_id=f'P4:{t}:{j}', score=float(rsrank[t,j]), limit=float(close[t,j]*1.03), S0=float(stop)))
    return {k:pd.DataFrame(v) for k,v in rows.items()}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--stage', choices=['signals'], default='signals'); args=ap.parse_args()
    HERE.mkdir(exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
    m=Market()
    if args.stage == 'signals':
        for name,f in signals(m).items(): f.to_parquet(OUT/(name+'_signals.parquet'),index=False)
        return

if __name__=='__main__': main()
