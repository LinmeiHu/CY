"""Re-execute every completed account and compare five serialized artifacts exactly."""
import json,tempfile,time
from pathlib import Path
import pandas as pd
from .common import HERE,OUT,sha,dump,scenarios
from .replay import Market,replay

def run():
    m=Market();rows=[];frames={};start=time.time()
    assert m.execution_binding==json.loads((HERE/'execution_input_binding.json').read_text())
    with tempfile.TemporaryDirectory(prefix='minervini_verify_',dir=OUT) as temporary:
        for s in scenarios():
            if s['module'] in ['CATALYST','FUNDAMENTALS']:continue
            family='N' if not s['group'].startswith('OLD') else f"OLD_{s['a']}_{s['w']}"
            if family not in frames:frames[family]=pd.read_parquet(OUT/(family+'_signals.parquet'))
            result=replay(m,s,frames[family]);identity=json.loads((OUT/s['id']/'identity.json').read_text());assert identity['source_hash']==sha(HERE/'replay.py')
            assert identity['execution_input_hash']==sha(HERE/'execution_input_binding.json')
            for name,data in zip(['nav','trades','orders','audit','open_positions'],result):
                p=Path(temporary)/(name+'.parquet');data.to_parquet(p,index=False);assert sha(p)==identity['artifacts'][p.name],(s['id'],name)
            rows.append(dict(scenario=s['id'],status='EXACT_MATCH_5_ARTIFACTS'));print('VERIFIED_REPEAT',len(rows),s['id'],flush=True)
    pd.DataFrame(rows).to_csv(HERE/'repeated_execution_checks.csv',index=False)
    dump(HERE/'repeat_execution.json',dict(status='PASS',accounts=len(rows),artifacts=len(rows)*5,seconds=time.time()-start,source_hash=sha(HERE/'replay.py'),counting='verification repeats, not extra scenarios or historical result reuse'))
if __name__=='__main__':run()
