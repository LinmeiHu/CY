"""Finish missing stock codes from a saved partial download."""
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
import pandas as pd
from .fetch_baostock import HERE,SYMBOLS,FIELDS,worker

def main():
    base=pd.read_parquet(HERE/'baostock_daily.parquet')
    missing=sorted(set(SYMBOLS)-set(base.code))
    print('RECOVER',len(missing),flush=True)
    chunks=[missing[i:i+5] for i in range(0,len(missing),5)]
    rows=[];bad=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(worker,chunk) for chunk in chunks]
        for i,job in enumerate(as_completed(jobs),1):
            got,errors=job.result();rows.extend(got);bad.extend(errors)
            allrows=pd.concat([base,pd.DataFrame(rows,columns=FIELDS.split(','))],ignore_index=True)
            allrows.to_parquet(HERE/'baostock_daily_complete.parquet',index=False)
            print('CHUNK',i,'/',len(chunks),'new_rows',len(rows),'errors',len(bad),flush=True)
    allrows=pd.read_parquet(HERE/'baostock_daily_complete.parquet')
    absent=sorted(set(SYMBOLS)-set(allrows.code))
    audit=dict(status='PASS' if not bad else 'ERROR',rows=len(allrows),symbols_with_rows=allrows.code.nunique(),absent_symbols=absent,errors=bad,dates=sorted(allrows.date.unique().tolist()))
    (HERE/'baostock_receipt_complete.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False))
    print('COMPLETE',audit['status'],len(allrows),len(absent),flush=True)
    if bad:raise RuntimeError(str(bad[:10]))

if __name__=='__main__':main()
