"""Mature holding-window close drawdown labels; never a signal-time input."""
import pandas as pd
from common import *

ASSET='CY-WAVE-LONG-MAE-CLOSE20'

def close_mae(window,entry,safe):
    valid=np.isfinite(window).all(1)&(window>0).all(1)&np.isfinite(entry)&(entry>0)&safe.all(1)
    result=np.full(len(entry),np.nan,np.float32)
    # Include the entry mark itself: MAE is nonpositive by definition.
    result[valid]=np.minimum(0,window[valid].min(1)/entry[valid]-1)
    return result

def main():
    destination=OUT/'mae_close20.npy';manifest=HERE/'MAE_LABEL_AUDIT.json'
    if manifest.exists():
        a=json.loads(manifest.read_text());assert a['builder_sha256']==sha(Path(__file__)) and a['label_sha256']==sha(destination)
        print('Existing MAE label identity verified');return
    bindings=json.loads((HERE/'INPUT_REPLAY_AUDIT.json').read_text())['panel_bindings'];required=[PANEL/(n+'.npy') for n in ['adj_open','adj_close','safe']]
    for p in required:
        b=next(b for b in bindings if b['path']==str(p));assert sha(p)==b['sha256']
    features=json.loads((HERE/'FEATURES.json').read_text());index_path=OUT/'index.parquet';binding=next(b for b in features['hashes'] if b['path']==str(index_path));assert sha(index_path)==binding['sha256']
    index=pd.read_parquet(index_path);dates=np.array(json.loads((PANEL/'axes.json').read_text())['dates']);op=get('adj_open');cl=get('adj_close');safe=get('safe')
    temporary=destination.with_suffix('.npy.tmp');out=np.lib.format.open_memmap(temporary,mode='w+',dtype='float32',shape=(len(index),));out[:]=np.nan
    for first in range(0,len(index),10000):
        rows=np.arange(first,min(first+10000,len(index)));t=index.t.to_numpy()[rows];j=index.j.to_numpy()[rows];valid=t+21<len(dates);rows=rows[valid];t=t[valid];j=j[valid]
        times=t[:,None]+np.arange(1,21)[None,:]
        out[rows]=close_mae(cl[times,j[:,None]],op[t+1,j],safe[times,j[:,None]])
    out.flush();del out;temporary.replace(destination);values=np.load(destination,mmap_mode='r');coverage=[]
    for fold in [2022,2023]:
        cut=int(np.searchsorted(dates,f'{fold}-01-01')-1);eligible=(index.t.to_numpy()+21<=cut)&np.isfinite(values);z=index[eligible]
        assert pd.Timestamp(z.decision_date.min())+pd.DateOffset(years=12)<=pd.Timestamp(z.decision_date.max())
        coverage.append(dict(fold=fold,first=z.decision_date.min(),last=z.decision_date.max(),annual=z.groupby('year').size().to_dict()))
    audit=dict(at=now(),builder_sha256=sha(Path(__file__)),label_path=str(destination),label_sha256=sha(destination),feature_manifest_sha256=sha(HERE/'FEATURES.json'),input_bindings=[b for b in bindings if b['path'] in list(map(str,required))],definition='min(0,min adjusted CLOSE of entry through entry+19 divided by next-open entry price minus1)',observable_at='Conservatively decision_index+21; gather only matured rows before training cutoff',missing='Any nonpositive/nonfinite quote or unsafe coordinate in the20-session window makes auxiliary label missing; no candidate or real order is removed',path_risk_event='holding-window close MAE20 < -10%',coverage=coverage)
    dump('MAE_LABEL_AUDIT.json',audit)
    registry=json.loads((HERE/'RESEARCH_REGISTRY.json').read_text());assert not any(a['asset_id']==ASSET for a in registry['assets'])
    registry['assets'].append(dict(asset_id=ASSET,kind='research_derived_supervision',status='RESEARCH_CONDITIONAL',pit_grade='B',physical_state='MATERIALIZED',location=str(destination),lineage=dict(manifest_path=str(manifest),manifest_sha256=sha(manifest)),allowed_uses=['This study mature auxiliary supervision and outcome diagnostics'],blocked_uses=['Signal-time feature','Live trading','Other project seals']))
    dump('RESEARCH_REGISTRY.json',registry);print('MAE labels admitted',coverage,flush=True)

def attach(data):
    a=json.loads((HERE/'MAE_LABEL_AUDIT.json').read_text());registry=json.loads((HERE/'RESEARCH_REGISTRY.json').read_text());asset=next(x for x in registry['assets'] if x['asset_id']==ASSET)
    assert asset['lineage']['manifest_sha256']==sha(HERE/'MAE_LABEL_AUDIT.json') and a['feature_manifest_sha256']==sha(HERE/'FEATURES.json')
    assert a['label_sha256']==sha(a['label_path']);labels=np.load(a['label_path'],mmap_mode='r')
    data.mae=np.full(len(data.idx),np.nan,np.float32);data.eval_mae=np.full(len(data.idx),np.nan,np.float32)
    for cutoff,target in [(data.cut,data.mae),(data.end,data.eval_mae)]:
        ok=data.t+21<=cutoff;target[ok]=labels[ok]
    data.path_risk=True

if __name__=='__main__':main()
