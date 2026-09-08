"""Run only evidence-supported D08 timing accounts on the verified V4 engine."""
import inspect,json,time
from pathlib import Path
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,V4,sha,dump,log
from ..usic_market_router_v4.engine import replay
from .market import Market
from ..usic_multichampion_ashare_v3.run import more_metrics
from ..usic_multichampion_ashare_v3.engine import metrics

def parquet(path,frame):frame.to_parquet(path,index=False)

def digested(events,boundary):
    return events.t1_structure_holds & (events.t1_close_extension_A<=boundary)

def run_account(m,sc,frame):
    d=OUT/'accounts'/sc['id'];d.mkdir(parents=True,exist_ok=True);parquet(d/'input_signals.parquet',frame)
    source=Path(inspect.getsourcefile(replay));identity=dict(config=sc,signal_hash=sha(d/'input_signals.parquet'),engine_path=str(source),engine_sha256=sha(source),
        actions=m.execution_binding,v4_state_sha256=sha(V4/'state_daily.parquet'),decision_map_sha256=sha(HERE/sc.get('decision_map','entry_decisions.csv')))
    result=d/'result.json'
    if result.exists():
        old=json.loads(result.read_text())
        if old.get('identity')==identity and old['status']=='COMPLETED' and all(sha(d/n)==h for n,h in old['artifacts'].items()):print('VERIFIED_RESUME',sc['id']);return old
        raise RuntimeError('identity mismatch for '+sc['id'])
    row=dict(sc,status='RUNNING',version_family='V5_NEW',identity=identity,output=str(d),started=time.time());dump(result,row)
    try:
        nav,tr,orders,audit,op,holds=replay(m,sc,frame)
        artifacts={}
        for name,x in zip(['nav','trades','orders','audit','open_positions','holdings'],[nav,tr,orders,audit,op,holds]):parquet(d/(name+'.parquet'),x);artifacts[name+'.parquet']=sha(d/(name+'.parquet'))
        assert len(nav)==970 and (nav.cash>=-1e-7).all() and (nav.borrowed_cash==0).all() and (nav.margin==0).all()
        np.testing.assert_allclose(nav.nav,nav.cash+nav.market_value+nav.receivable,rtol=0,atol=1e-7)
        assert not holds.duplicated(['t','symbol']).any()
        row.update(metrics(nav,tr),**more_metrics(nav,tr,orders,holds),status='COMPLETED',artifacts=artifacts,ended=time.time())
    except Exception as e:row.update(status='BLOCKED_OR_INVALIDATED',reason=repr(e),ended=time.time());dump(result,row);raise
    dump(result,row);print(sc['id'],row['net_return'],row['maxdd'],row['trades']);return row

def main():
    events=pd.read_parquet(OUT/'event_timeline.parquet');signals=pd.read_parquet(V3/'A_D08_C_10_E10/input_signals.parquet');m=Market();m.v4state=pd.read_parquet(V4/'confirmation_state_daily.parquet')
    log('E3_FROZEN_BAND','Common trades: lower T+1 close extension relates to larger delay improvement in all years; open extension does not. Natural boundary is the already-frozen U+0.5A entry limit.','Waiting through T+1 helps when the close has digested back inside the original executable structure band.','At T+1 close retain only S0 < close <= U+0.5A; execute at T+2 under original frozen limit. No re-ranking.','A_D08_C_10_E10 and B_D08_C_10_DELAY1','Conditional account beats original D08 and retains most fixed-delay improvement with fewer structurally poor events.','Fails to beat original, improvement is unstable by year, or gains are only from reduced exposure.',phase='BEFORE_ACCOUNT')
    decisions=events[['setup_id','t','signal_date','t1_date','t1_close_extension_A','t1_close_vs_S0_A','t1_structure_holds','S1']].copy()
    decisions['rule']='S0_LT_T1_CLOSE_LE_U_PLUS_0.5A';decisions['allow']=digested(decisions,.5)
    decisions['decision_cutoff']=decisions.t1_date+'T15:00:00+08:00';decisions.to_csv(HERE/'entry_decisions.csv',index=False)
    f=signals.merge(decisions[['setup_id','t1_date','allow']],on='setup_id',validate='one_to_one');f=f[f.allow].drop(columns='allow').copy();f['origin_t']=f.t;f['t']=f.t+1;f['decision_at']=f.t1_date+'T15:00:00+08:00';f=f.drop(columns='t1_date')
    sc=dict(id='E3_FROZEN_BAND_C10_E10',mode='C_10',delay=1,cost=1,exit='FIXED10',overlay='NONE',book='ENTRY_ONLY',entry_rule='S0_LT_T1_CLOSE_LE_U_PLUS_0.5A',ranking='V4_FIXED',origin_signal_t='origin_t')
    if not (OUT/'accounts'/sc['id']/'result.json').exists():run_account(m,sc,f)
    else:print('PRESERVED_EXISTING',sc['id'])

    log('E3_QUARTER_NEIGHBOR','The frozen-band account returned 35.04% versus base 15.15% and fixed delay 41.64%; common-trade diagnostics showed larger relative benefit below U+0.25A.','A single narrower half-band tests whether the digestion relation is stable rather than an artifact of the outer frozen limit.','Replace only the upper T+1 close boundary with U+0.25A; keep setup, ranking, C10, execution and E10.','E3_FROZEN_BAND_C10_E10 and B_D08_C_10_DELAY1','The narrower band beats the 0.5A rule and fixed delay without merely collapsing exposure.','It remains below fixed delay, loses cross-year consistency, or improvement follows materially lower exposure.',phase='BEFORE_ACCOUNT')
    q=events[['setup_id','t','signal_date','t1_date','t1_close_extension_A','t1_close_vs_S0_A','t1_structure_holds','S1']].copy()
    q['rule']='S0_LT_T1_CLOSE_LE_U_PLUS_0.25A';q['allow']=digested(q,.25);q['decision_cutoff']=q.t1_date+'T15:00:00+08:00';q.to_csv(HERE/'entry_decisions_quarter.csv',index=False)
    f=signals.merge(q[['setup_id','t1_date','allow']],on='setup_id',validate='one_to_one');f=f[f.allow].drop(columns='allow').copy();f['origin_t']=f.t;f['t']=f.t+1;f['decision_at']=f.t1_date+'T15:00:00+08:00';f=f.drop(columns='t1_date')
    sc=dict(id='E3_QUARTER_BAND_C10_E10_CA',mode='C_10',delay=1,cost=1,exit='FIXED10',overlay='NONE',book='ENTRY_ONLY',entry_rule='S0_LT_T1_CLOSE_LE_U_PLUS_0.25A',ranking='V4_FIXED',origin_signal_t='origin_t',decision_map='entry_decisions_quarter.csv')
    run_account(m,sc,f)

if __name__=='__main__':main()
