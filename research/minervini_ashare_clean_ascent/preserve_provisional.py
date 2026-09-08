"""Recover exact pre-correction artifacts from hash-verified source, preserving audit trail."""
import json
import pandas as pd
from . import replay_before_legal_submission as legacy
from .common import HERE,OUT,sha,dump,scenarios

def run():
    original=json.loads((OUT/'provisional_before_legal_submission/original_identity_index.json').read_text());frozen=OUT/'provisional_before_universe_correction';legacy.OUT=frozen;m=legacy.Market();configs={s['id']:s for s in scenarios()};frames={};results=[]
    for item in original:
        s=configs[item['scenario']];family='N' if not s['group'].startswith('OLD') else f"OLD_{s['a']}_{s['w']}"
        assert sha(frozen/(family+'_signals.parquet'))==item['features_hash']
        if family not in frames:frames[family]=pd.read_parquet(frozen/(family+'_signals.parquet'))
        nav,trades,orders,audit,op=legacy.replay(m,s,frames[family]);d=OUT/'provisional_before_legal_submission'/s['id'];d.mkdir(exist_ok=True)
        for name,data in [('nav',nav),('trades',trades),('orders',orders),('audit',audit),('open_positions',op)]:
            p=d/(name+'.parquet');data.to_parquet(p,index=False);actual=sha(p);expected=item['artifacts'][p.name];assert actual==expected,(s['id'],name,actual,expected)
        results.append(dict(scenario=s['id'],status='EXACT_OLD_ARTIFACT_HASH_RECOVERED',source_hash=sha(HERE/'replay_before_legal_submission.py'),path=str(d)))
    dump(HERE/'provisional_recovery.json',results);print('EXACT_PROVISIONAL_RECOVERY',len(results),flush=True)
if __name__=='__main__':run()
