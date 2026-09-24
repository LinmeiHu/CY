"""Retry only failed Baostock symbols with fresh single connections."""
from pathlib import Path
import json
import time
import baostock as bs
import pandas as pd
from .fetch_baostock import FIELDS,HERE,SYMBOLS

def main():
    receipt=json.loads((HERE/'baostock_receipt_complete.json').read_text())
    missing=[row[0] for row in receipt['errors']]
    base=pd.read_parquet(HERE/'baostock_daily_complete.parquet')
    rows=[];bad=[]
    for i,symbol in enumerate(missing,1):
        success=False
        for attempt in range(5):
            login=bs.login()
            if login.error_code=='0':
                try:
                    q=bs.query_history_k_data_plus(symbol,FIELDS,start_date='2026-09-17',end_date='2026-09-23',frequency='d',adjustflag='3')
                    if q.error_code=='0':
                        while q.next():rows.append(q.get_row_data())
                        success=True
                        break
                    error=(symbol,q.error_code,q.error_msg)
                finally:bs.logout()
            else:error=(symbol,login.error_code,login.error_msg)
            time.sleep(1+attempt)
        if not success:bad.append(error)
        if i%25==0 or i==len(missing):
            combined=pd.concat([base,pd.DataFrame(rows,columns=FIELDS.split(','))],ignore_index=True)
            combined.to_parquet(HERE/'baostock_daily_complete.parquet',index=False)
            (HERE/'retry_progress.json').write_text(json.dumps(dict(completed=i,total=len(missing),remaining=bad),ensure_ascii=False))
            print('RETRY',i,'/',len(missing),'bad',len(bad),flush=True)
    if bad:raise RuntimeError(str(bad[:10]))
    combined=pd.read_parquet(HERE/'baostock_daily_complete.parquet')
    absent=sorted(set(SYMBOLS)-set(combined.code))
    print('ALL',len(combined),'symbols',combined.code.nunique(),'absent',len(absent),flush=True)
    (HERE/'baostock_receipt_complete.json').write_text(json.dumps(dict(status='PASS',rows=len(combined),symbols_with_rows=combined.code.nunique(),absent_symbols=absent,dates=sorted(combined.date.unique().tolist())),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
