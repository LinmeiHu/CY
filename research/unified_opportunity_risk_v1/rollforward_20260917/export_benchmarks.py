"""Read-only latest raw benchmark history, for chart display only."""
from pathlib import Path
import pandas as pd
from xtquant import xtdata
root=Path(__file__).resolve().parent/'cache/benchmarks';root.mkdir(exist_ok=True)
for symbol in ['000001.SH','399001.SZ']:
    xtdata.download_history_data(symbol,period='1d',start_time='20180101',end_time='20260916',incrementally=True)
    frame=xtdata.get_market_data_ex([], [symbol],period='1d',start_time='20180101',end_time='20260916',dividend_type='none',fill_data=False)[symbol].copy()
    frame['trade_date']=pd.to_datetime(frame.index.astype(str),format='%Y%m%d');frame['symbol']=symbol
    assert str(frame.trade_date.max().date())=='2026-09-16'
    frame.reset_index(drop=True).to_parquet(root/f'{symbol}.parquet',index=False)
    print(symbol,len(frame),frame.trade_date.max())
