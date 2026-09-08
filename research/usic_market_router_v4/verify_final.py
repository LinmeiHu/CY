"""Targeted full replay and true truncated-calendar checks, without source writes."""
import copy,json
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,ROUTES,sha,parquet,dump
from .market import Market
from .engine import replay
from .maps import event

def main():
    checks=[];m=Market();m.v4state=pd.read_parquet(OUT/'confirmation_state_daily.parquet')
    manifest=json.loads((HERE.parent/'usic_multichampion_ashare_v3/FEATURE_MANIFEST.json').read_text())
    for item in manifest['files']:assert sha(item['path'])==item['sha256']
    for sid in ['R1_S1_D08_C_10','PAST_ONLY_D08_C_10']:
        dest=OUT/'accounts'/sid;r=json.loads((dest/'result.json').read_text());sc=r['identity']['config'];f=pd.read_parquet(dest/'input_signals.parquet')
        output=replay(m,sc,f);repeat=OUT/'verification'/sid;repeat.mkdir(parents=True,exist_ok=True)
        for name,df in zip(['nav','trades','orders','audit','open_positions','holdings'],output):
            p=repeat/(name+'.parquet');parquet(p,df);assert sha(p)==r['artifacts'][name+'.parquet'],(sid,name);checks.append(dict(id=sid,test='FULL_REPLAY_HASH_'+name,passed=True))
        end=1100;mm=copy.copy(m);mm.dates=m.dates[:end];mm.a={k:v[:end] for k,v in m.a.items()};mm.capacity=m.capacity[:end];mm.state=m.state[:end];mm.v4state=m.v4state.iloc[:end].copy()
        cut=replay(mm,sc,f[f.t<end-1]);pd.testing.assert_frame_equal(output[0][output[0].t<end].reset_index(drop=True),cut[0])
        # Full-run boundary rows introduce nullable float columns; compare the exact
        # historical order values after canonical dtype alignment, never tolerances.
        fullorders=output[2][output[2].t<end].reset_index(drop=True);shortorders=cut[2].reset_index(drop=True)
        for col in fullorders:shortorders[col]=shortorders[col].astype(fullorders[col].dtype)
        pd.testing.assert_frame_equal(fullorders,shortorders,check_exact=True)
        checks.append(dict(id=sid,test='TRUNCATED_CALENDAR_1100_NAV_ORDERS',passed=True))
    # Exact standardized-lot clock versus the original engine on deterministic events.
    m.action_records_by_symbol={s:[str(x.date()) for x in g.record_date.dropna()] for s,g in m.actions.groupby('symbol')}
    for route in ROUTES:
        ev=pd.read_parquet(OUT/f'events_{route}.parquet');mature=ev[ev.status=='MATURED'];chosen=mature.iloc[len(mature)//2]
        src=OUT/'D09_corrected_signals.parquet' if route=='D09' else V3/f'{route}_signals.parquet';f=pd.read_parquet(src);r=f[f.setup_id==chosen.setup_id].iloc[0].to_dict();t=int(r['t']);end=min(len(m.dates),int(chosen.exit_t)+81)
        mm=copy.copy(m);mm.dates=m.dates[t:end];mm.a={k:v[t:end] for k,v in m.a.items()};mm.capacity=m.capacity[t:end];mm.state=m.state[t:end]
        sc=dict(id='SINGLE_CLOCK_VERIFY',mode='C_10',delay=1,cost=1,exit='FIXED10',overlay='NONE');_,tr,*_=replay(mm,sc,pd.DataFrame([dict(r,t=0)]))
        assert len(tr)==1;np.testing.assert_allclose(tr.pnl.iloc[0],chosen.std_pnl,rtol=0,atol=1e-7)
        checks.append(dict(id=route,test='SINGLE_EVENT_CASH_CLOCK',passed=True))
    # Repaired event facts changed estimates but not the historical mappings.
    ev=pd.read_parquet(OUT/'events_D08.parquet').merge(m.v4state[['t','S1','S1_episode']],on='t');old=pd.read_csv(HERE/'past_only_mapping.csv');rows=[]
    for r in old.to_dict('records'):
        g=ev[(ev.label_available_t<=r['fit_cutoff_t'])&(ev.status=='MATURED')&(ev.S1==r['state'])];mu=g.groupby('t').net_return.mean().mean();allow=g.t.nunique()>=20 and g.S1_episode.nunique()>=3 and mu>0
        rows.append(dict(year=r['year'],state=r['state'],old_allow=r['allow'],repaired_allow=allow,old_mean=r['equal_date_return'],repaired_mean=mu));assert bool(r['allow'])==allow
    pd.DataFrame(rows).to_csv(HERE/'past_only_repaired_fact_parity.csv',index=False)
    # Bind the exact state sequence used, including generated confirmation/mapping columns.
    bindings=[]
    for p in (OUT/'accounts').glob('*/result.json'):
        r=json.loads(p.read_text());sc=r.get('identity',{}).get('config',{});key=sc.get('state_key')
        if key and key in m.v4state:
            import hashlib
            h=hashlib.sha256(m.v4state[['t','date',key]].to_json(orient='records').encode()).hexdigest();bindings.append(dict(id=r['id'],state_key=key,state_sequence_sha256=h,source=str(OUT/'confirmation_state_daily.parquet')))
    pd.DataFrame(bindings).to_csv(HERE/'account_state_bindings.csv',index=False)
    dump(HERE/'FINAL_CHECKS.json',dict(checks=checks,signal_manifest_verified=True,past_mapping_repaired_facts_parity=True,all_passed=True))
    print('FINAL_CHECKS',len(checks),'PASS',flush=True)

if __name__=='__main__':main()
