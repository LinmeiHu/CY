"""Independent bounded checks and exact equal-industry score finalization before G5."""
import numpy as np,pandas as pd,json
from .common import HERE,OUT,dump,sha,pivots

def run():
    f=pd.read_parquet(OUT/'N_candidates.parquet');c=np.load(OUT/'coord.npy',mmap_mode='r');ind=np.load(OUT/'industry.npy',mmap_mode='r');valid=np.load(OUT/'hard_valid.npy',mmap_mode='r')==1
    h=np.load(OUT/'high.npy',mmap_mode='r');l=np.load(OUT/'low.npy',mmap_mode='r');factor=np.load(OUT/'factor.npy',mmap_mode='r');vol=np.load(OUT/'volume.npy',mmap_mode='r')
    boards=np.array(json.loads((OUT/'axes.json').read_text())['boards']);industry={};checks=[];step=np.load(OUT/'step.npy',mmap_mode='r')
    for t in sorted(f.t.unique()):
        r=c[t-1]/c[t-61]-1;v=pd.DataFrame(dict(j=np.arange(c.shape[1]),industry=ind[t-1],r=r));v=v[(v.industry>=0)&v.r.notna()&valid[t-1]&(boards!='UNSUPPORTED')&np.isfinite(step[t-60:t]).all(axis=0)]
        g=v.groupby('industry').r;v['n']=g.transform('size');v['loo']=(g.transform('sum')-v.r)/(v.n-1);means=v[v.n>=5].groupby('industry').r.mean().sort_values().to_numpy();v=v[v.n>=5]
        for j,loo in zip(v.j,v.loo):industry[(t,j)]=float(np.searchsorted(means,loo,side='right')/len(means)) if len(means) else np.nan
    f['Industry']=[industry.get((t,j),np.nan) for t,j in zip(f.t,f.j)]
    # Fixed chronology-spaced sample, not chosen using returns or success.
    sample=f.sort_values(['t','symbol']).iloc[np.linspace(0,len(f)-1,min(500,len(f)),dtype=int)]
    for r in sample.itertuples():
        hh=h[r.t-30:r.t,r.j]*factor[r.t-30:r.t,r.j];ll=l[r.t-30:r.t,r.j]*factor[r.t-30:r.t,r.j]
        reason,legs,amb=pivots(hh,ll,vol[r.t-30:r.t,r.j]);assert (reason=='PASS')==r.VCP_GUARD
        assert json.loads(r.legs)==legs
        # Future bars are excluded by independent reconstruction of a prefix snapshot.
        paddedh=np.r_[hh,[1e8,1e-8,1e9]];paddedl=np.r_[ll,[1e-9,1e7,1e-10]]
        assert pivots(paddedh[:30],paddedl[:30],vol[r.t-30:r.t,r.j])==(reason,legs,amb)
        q=r.t-31;start=r.t-61;A=c[start:q+1,r.j];P1=np.mean(1-A[1:]/np.maximum.accumulate(A)[1:]);assert abs(P1-r.P1)<1e-12
        assert q<r.t-30 and all(x['low_confirm']<30 for x in legs)
    f.to_parquet(OUT/'N_candidates.parquet',index=False);f[f.breakout].to_parquet(OUT/'N_signals.parquet',index=False)
    dump(HERE/'feature_checks.json',dict(status='PASS',prefix_pivot_snapshots=len(sample),path_window_separation=len(sample),industry_ranking='equal industry reference distribution, focal stock excluded',future_bars_mutated='extreme arbitrary values; no prior snapshot change',limitations='real prefix VCP/Path test; full input pipeline truncation is not yet independently rerun'))
    dump(HERE/'feature_manifest.json',dict(artifacts=[dict(path=str(p),sha256=sha(p),size=p.stat().st_size) for p in sorted(OUT.glob('*')) if p.is_file() and (p.suffix=='.npy' or p.name in ['axes.json','market.csv'] or p.name.endswith(('_candidates.parquet','_signals.parquet','_funnel.csv')))],outcomes_used_to_change_scores=False))
    print('FEATURE_CHECKS_PASS',len(f),int(f.breakout.sum()),flush=True)
if __name__=='__main__':run()
