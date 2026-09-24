"""Bind the completed Baostock fallback window without altering prior evidence."""
from pathlib import Path
import json
import baostock as bs
import pandas as pd
from research.portfolio_closure_v1 import repair

HERE=Path(__file__).parent
MARKET=HERE/'cache/market'

def main():
    receipt=json.loads((HERE/'baostock_receipt_complete.json').read_text())
    if receipt['status']!='PASS' or receipt['dates']!=['2026-09-17','2026-09-18','2026-09-21','2026-09-22','2026-09-23']:
        raise RuntimeError('Incomplete daily window')
    MARKET.mkdir(parents=True,exist_ok=True)
    d=pd.read_parquet(HERE/'baostock_daily_complete.parquet')
    if d.duplicated(['date','code']).any():raise RuntimeError('Duplicate stock-date')
    d.to_parquet(MARKET/'raw_daily.parquet',index=False)
    login=bs.login()
    if login.error_code!='0':raise RuntimeError(login.error_msg)
    try:
        query=bs.query_history_k_data_plus('sh.000300','date,code,open,high,low,close,volume,amount',start_date='2026-09-17',end_date='2026-09-23',frequency='d',adjustflag='3')
        if query.error_code!='0':raise RuntimeError(query.error_msg)
        rows=[]
        while query.next():rows.append(query.get_row_data())
    finally:bs.logout()
    index=pd.DataFrame(rows,columns=['date','code','open','high','low','close','volume','amount'])
    if sorted(index.date.tolist())!=receipt['dates']:raise RuntimeError('Index dates incomplete')
    (MARKET/'index_daily').mkdir(exist_ok=True)
    index.to_parquet(MARKET/'index_daily/csi000300.parquet',index=False)
    audit=dict(status='FALLBACK_BAOSTOCK',end='2026-09-23',rows=len(d),symbols=d.code.nunique(),dates=receipt['dates'],source='Baostock unadjusted stock and CSI300 daily',hashes={str(p):repair.digest(p) for p in [MARKET/'raw_daily.parquet',MARKET/'index_daily/csi000300.parquet']})
    (MARKET/'manifest.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False))
    print(audit,flush=True)

if __name__=='__main__':main()
