"""Separate Q3 close-observation temporal audit and original account replay."""
import json
import pandas as pd
import numpy as np
from .common import HERE,OUT,V3,log,parquet,dump
from ..usic_multichampion_ashare_v3.common import scenarios
from ..usic_multichampion_ashare_v3.minute_market import MinuteMarket
from ..usic_multichampion_ashare_v3.run import config
from .engine_correction import replay as open_replay
from .tail_correction import replay as tail_replay
from .runner import run,publish

def prior_breakout(m,r,prefix):
    j=int(r['j']);start=int(r['formation_t']);end=int(r['t']);U=r['U']*r['factor']
    for t in range(start,end):
        if (j,t) in prefix.index:
            p=prefix.loc[(j,t)]
            if p.close1425*p.factor>U:return True
        if m.a['coord'][t,j]>U:return True
    return False

def main():
    log('BUG_Q3','BUG_FIX','Q3 independent audit: 412 past 14:25 close crossings; 393 past daily close crossings; union 423/1805',
        'Q3首次已观察收盘突破之后不再发提前参与；只查当前信号以前已完成14:25或日收盘',
        'Frozen Q3 BASE and ENHANCED','恢复突破前语义，不以收益方向判修复','任何使用当前日最终收盘；任何不相关Q4改变')
    m=MinuteMarket();f=pd.read_parquet(V3/'Q3_signals.parquet');prefix=pd.read_parquet(V3/'q_prefix_marks.parquet').set_index(['j','t'])
    bad=[prior_breakout(m,r,prefix) for r in f.to_dict('records')];assert sum(bad)==423
    f=f[~np.array(bad)].sort_values(['t','score','symbol'],ascending=[True,False,True]);parquet(OUT/'Q3_corrected_signals.parquet',f)
    impacts=[]
    for s in scenarios():
        if not s['id'].startswith('Q3_'):continue
        tail=s['arm']=='ENHANCED';sc=config(s);sc.update(id='FIX_'+s['id'],delay=0 if tail else 1,fixed_holding=10,overlay='NONE')
        row=run(m,sc,f,'V3_CORRECTION',tail_replay if tail else open_replay);old=json.loads((V3/s['id']/'result.json').read_text())
        impacts.append(dict(id=sc['id'],reference=s['id'],status=row['status'],old_return=old['net_return'],new_return=row.get('net_return')))
        publish();pd.DataFrame(impacts).to_csv(HERE/'q3_correction_impact.csv',index=False)

if __name__=='__main__':main()
