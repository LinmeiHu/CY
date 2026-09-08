"""Real-data prefix, global-rank, inherited-signal and artifact coverage checks."""
import numpy as np,pandas as pd,duckdb
from .common import HERE,OUT,CACHE,dump,sha
from .features import Features,new_events
from .legacy_common import pivots

def main():
    m=Features();rs20=np.load(OUT/'indicators/rs20.npy',mmap_mode='r');rs60=np.load(OUT/'indicators/rs60.npy',mmap_mode='r');checks=[]
    parents=pd.read_parquet(OUT/'D02_signals.parquet');js=sorted(set([0,600,1200,2200,3500]+parents.j.drop_duplicates().astype(int).head(5).tolist()))
    con=duckdb.connect();con.execute('set threads=1')
    for j in js:
        nr=con.execute('select * from read_parquet(?) where j=? and long order by t',[str(CACHE/'N_candidates.parquet'),j]).fetchdf().to_dict('records');ps=parents[parents.j==j].to_dict('records')
        rows,_=new_events(m,j,rs20,rs60,ps,nr)
        for cutoff in [700,950,1200]:
            pre=Features(cutoff);got,_=new_events(pre,j,rs20[:cutoff+1],rs60[:cutoff+1],ps,nr)
            left=pd.DataFrame([r for r in rows if r['t']<=cutoff]);right=pd.DataFrame(got)
            pd.testing.assert_frame_equal(left.reset_index(drop=True),right.reset_index(drop=True));checks.append(dict(kind='raw_symbol_prefix',j=j,cutoff=cutoff,signals=len(got),pass_check=True))
    for q in [600,850,1100,1400]:
        for n,rs in [(20,rs20),(60,rs60)]:
            hist=np.isfinite(m.a['step'][q-251:q+1]).sum(axis=0)==252
            good=hist&(m.a['is_st'][q]==0)&(m.a['hard_valid'][q]==1)
            values=m.a['coord'][q]/m.a['coord'][q-n]-1
            for board in ['MAIN','CHINEXT','STAR']:
                ids=np.flatnonzero(good&(np.array(m.boards)==board));want=pd.Series(values[ids]).rank(pct=True,method='average').to_numpy()
                if len(ids)==1:want[:]=.5
                np.testing.assert_allclose(rs[q,ids],want,rtol=0,atol=0)
            checks.append(dict(kind='global_asof_rank',cutoff=q,lookback=n,pass_check=True))
    for route,version in [('D00','N1'),('D01','N3'),('D02','N4')]:
        from .legacy_replay import select
        original=pd.read_parquet(CACHE/'N_signals.parquet');want=select(original,dict(version=version,module=''))
        got=pd.read_parquet(OUT/f'{route}_signals.parquet')
        cols=['t','j','score','limit','S0','U','a0','factor'];pd.testing.assert_frame_equal(want[cols].sort_values(['t','j']).reset_index(drop=True),got[cols].sort_values(['t','j']).reset_index(drop=True),check_dtype=False)
        checks.append(dict(kind='inherited_signal_identity',route=route,signals=len(got),pass_check=True))
    f=pd.read_parquet(OUT/'all_signals_before_dedup.parquet');assert (f.known_t<=f.t).all();assert (f.factor>0).all();assert (f.a0>0).all()
    dump(HERE/'PREFIX_CHECKS.json',dict(checks=checks,source_hash=sha(HERE/'features.py'),no_post_2023_input=True,all_pass=True));print('CORE_PREFIX_PASS',len(checks),flush=True)

if __name__=='__main__':main()
