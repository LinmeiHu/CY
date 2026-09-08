"""Reuse the cash engine; resume only exact scenario/input/artifact identities."""
import json, time, inspect
import numpy as np
import pandas as pd
from .common import HERE, OUT, V3, sha, dump, parquet
from .engine import replay, metrics, ExecutionGap
from ..usic_multichampion_ashare_v3.run import more_metrics

LOADED_HASHES={}

def run(m, sc, frame, family='V4_NEW', replay_fn=replay):
    dest=OUT/'accounts'/sc['id'];dest.mkdir(parents=True,exist_ok=True)
    parquet(dest/'input_signals.parquet',frame)
    source=inspect.getsourcefile(replay_fn)
    if source not in LOADED_HASHES:LOADED_HASHES[source]=sha(source)
    assert sha(source)==LOADED_HASHES[source], 'Do not edit an engine while its process is running'
    identity=dict(config=sc,signal_hash=sha(dest/'input_signals.parquet'),engine=LOADED_HASHES[source],engine_source=source.rsplit('/',1)[-1],
        actions=m.execution_binding,states=sha(OUT/'state_daily.parquet') if sc.get('state_key') else None)
    result=dest/'result.json'
    if result.exists():
        old=json.loads(result.read_text())
        if old.get('identity')==identity and old['status']=='COMPLETED' and all(sha(dest/n)==h for n,h in old['artifacts'].items()):
            print('VERIFIED_RESUME',sc['id'],flush=True);return old
        raise RuntimeError('Existing attempt has different identity or failed: use explicit new attempt id '+sc['id'])
    row=dict(sc,status='RUNNING',version_family=family,started=time.time(),identity=identity,output=str(dest))
    dump(result,row)
    try:
        nav,tr,orders,audit,op,holds=replay_fn(m,sc,frame)
        artifacts={}
        for name,f in zip(['nav','trades','orders','audit','open_positions','holdings'],[nav,tr,orders,audit,op,holds]):
            parquet(dest/(name+'.parquet'),f);artifacts[name+'.parquet']=sha(dest/(name+'.parquet'))
        assert len(nav)==970 and (nav.cash>=-1e-7).all() and (nav.market_value<=nav.nav+1e-7).all()
        np.testing.assert_allclose(nav.nav,nav.cash+nav.market_value+nav.receivable,rtol=0,atol=1e-7)
        assert not holds.duplicated(['t','symbol']).any()
        row.update(metrics(nav,tr),**more_metrics(nav,tr,orders,holds),status='COMPLETED',artifacts=artifacts,ended=time.time())
        row={k:None if isinstance(v,(float,np.floating)) and not np.isfinite(v) else v for k,v in row.items()}
    except ExecutionGap as e:row.update(status='BLOCKED_INPUT',reason=str(e))
    except Exception as e:
        row.update(status='INVALIDATED',reason=repr(e));dump(result,row);raise
    dump(result,row);print(sc['id'],row['status'],row.get('net_return'),round(time.time()-row['started'],2),flush=True)
    return row

def publish():
    rows=[]
    for p in sorted((OUT/'accounts').glob('*/result.json')):
        r=json.loads(p.read_text());rows.append({k:v for k,v in r.items() if k not in ['identity','artifacts']})
    pd.DataFrame(rows).to_csv(HERE/'scenario_summary.csv',index=False)
    return pd.DataFrame(rows)
