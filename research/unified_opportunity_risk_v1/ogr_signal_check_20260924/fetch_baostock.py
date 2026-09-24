"""Read-only fallback daily bars for the frozen OGR stock population."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import json
import time
import baostock as bs
import pandas as pd

HERE = Path(__file__).parent
PARENT = HERE.parent / 'rollforward_20260917'
SYMBOLS = (PARENT / 'symbols_baostock.txt').read_text().splitlines()
FIELDS = 'date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,pctChg,tradestatus,isST'

def worker(chunk):
    login = bs.login()
    if login.error_code != '0':
        raise RuntimeError(login.error_msg)
    rows=[];errors=[]
    try:
        for symbol in chunk:
            for attempt in range(3):
                query=bs.query_history_k_data_plus(symbol,FIELDS,start_date='2026-09-17',end_date='2026-09-23',frequency='d',adjustflag='3')
                if query.error_code == '0':
                    while query.next():rows.append(query.get_row_data())
                    break
                if attempt==2:errors.append((symbol,query.error_code,query.error_msg))
                time.sleep(1+attempt)
    finally:bs.logout()
    return rows,errors

def main():
    chunks=[SYMBOLS[i:i+50] for i in range(0,len(SYMBOLS),50)]
    allrows=[];errors=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(worker,chunk) for chunk in chunks]
        for i,job in enumerate(as_completed(jobs),1):
            rows,bad=job.result();allrows.extend(rows);errors.extend(bad)
            frame=pd.DataFrame(allrows,columns=FIELDS.split(','))
            frame.to_parquet(HERE/'baostock_daily.parquet',index=False)
            print('FETCH',i,'/',len(chunks),len(allrows),'rows',len(errors),'errors',flush=True)
    frame=pd.DataFrame(allrows,columns=FIELDS.split(','))
    frame.to_parquet(HERE/'baostock_daily.parquet',index=False)
    (HERE/'baostock_receipt.json').write_text(json.dumps(dict(symbols_requested=len(SYMBOLS),rows=len(frame),errors=errors,dates=sorted(frame.date.unique().tolist())),ensure_ascii=False,indent=2))
    if errors:raise RuntimeError(str(errors[:10]))
    print('DONE',len(frame),len(frame.code.unique()),sorted(frame.date.unique()),flush=True)

if __name__=='__main__':main()
