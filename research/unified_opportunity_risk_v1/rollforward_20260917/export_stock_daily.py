"""Read-only QMT raw daily export for the frozen 3,725-stock population."""
import json
from pathlib import Path
import pandas as pd
from xtquant import xtdata
root=Path(__file__).resolve().parent
out=root/'cache/qmt_stock_daily';out.mkdir(exist_ok=True)
symbols=[s.split('.')[1]+'.'+s.split('.')[0].upper() for s in (root/'symbols_baostock.txt').read_text().splitlines()]
needed=[s for s in symbols if not (out/f'{s}.parquet').exists()]
def progress(d):
    if d.get('finished',0)%100==0:print('QMT_PROGRESS',d.get('finished'),d.get('total'),flush=True)
if needed:
    print('QMT_RAW_STOCK_DOWNLOAD',len(needed),flush=True)
    result=xtdata.download_history_data2(needed,'1d','20260904','20260916',callback=progress,incrementally=False)
    (out/'download_result.json').write_text(json.dumps(result,default=str,indent=2))
    for begin in range(0,len(needed),100):
        batch=needed[begin:begin+100]
        data=xtdata.get_market_data_ex([],batch,period='1d',start_time='20260904',end_time='20260916',dividend_type='none',fill_data=False)
        for symbol in batch:
            f=data[symbol].copy();f['trade_date']=pd.to_datetime(f.index.astype(str),format='%Y%m%d');f['symbol']=symbol
            f.reset_index(drop=True).to_parquet(out/f'{symbol}.parquet',index=False)
        print('EXPORTED',begin+len(batch),flush=True)
print('QMT_RAW_STOCK_EXPORT_COMPLETE',len(symbols),flush=True)
