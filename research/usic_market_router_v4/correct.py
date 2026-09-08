"""D09 historical semantic correction; only affected dependency replays."""
import json
import pandas as pd
from .common import HERE,OUT,V3,ROUTES,log,dump,parquet,sha
from ..usic_multichampion_ashare_v3.common import scenarios
from ..usic_multichampion_ashare_v3.run import portfolio_frames,config
from .engine_correction import Market,replay
from .runner import run,publish

def main():
    log('BUG_D09','BUG_FIX','Original episodes: 422 breakout_t < advance_t / 1843 signals',
        '首次突破后禁止新提前参与；原episode及后续事实完整保留', 'V3 frozen D09/P0/P1/P2/P3',
        '删除语义错误信号；收益可升可降', '修复产生任何不相关入口差异')
    ep=pd.read_parquet(V3/'episodes.parquet');bad=ep[(ep.route=='D09_EPISODE')&(ep.breakout_t<ep.advance_t)]
    frames={r:pd.read_parquet(V3/f'{r}_signals.parquet') for r in ROUTES}
    frames['D09']=frames['D09'][~frames['D09'].setup_id.isin(bad.setup_id)].copy()
    parquet(OUT/'D09_corrected_signals.parquet',frames['D09'])
    corrected=ep.copy();corrected['original_advance_t']=corrected.advance_t
    corrected.loc[bad.index,'advance_t']=float('nan');parquet(OUT/'episodes_corrected.parquet',corrected)
    m=Market();oldframes={r:pd.read_parquet(V3/f'{r}_signals.parquet') for r in ROUTES}
    oldframes.update(portfolio_frames(m,oldframes));frames.update(portfolio_frames(m,frames))
    impact=[]
    for s in scenarios():
        if s['group'].split('_')[0] not in ['A','B','E']:continue
        if s['signal'] not in ['D09','P0_POOL','P1_BALANCED','P2_PHASE','P3_CORROBORATE']:continue
        f=frames[s['signal']].copy()
        if not s['signal'].startswith('P'):f=f.sort_values(['t','score','symbol'],ascending=[True,False,True])
        sc=config(s);sc['id']='FIX_'+s['id']
        r=run(m,sc,f,'V3_CORRECTION',replay_fn=replay)
        old=json.loads((V3/s['id']/'result.json').read_text())
        impact.append(dict(id=sc['id'],reference=s['id'],original_return=old['net_return'],corrected_return=r.get('net_return'),
            delta_return=r.get('net_return',float('nan'))-old['net_return'],original_signals=len(oldframes[s['signal']]),corrected_signals=len(f),status=r['status']))
        pd.DataFrame(impact).to_csv(HERE/'d09_correction_impact.csv',index=False);publish()
    dump(HERE/'d09_correction.json',dict(bad_episodes=len(bad),original_signals=1843,corrected_signals=len(frames['D09']),replays=len(impact),episode_ledger_preserved=True))

if __name__=='__main__':main()
