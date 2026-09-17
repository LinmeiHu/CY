"""Read-only QMT native one-minute data for newly qualified gap parents."""
from pathlib import Path
import pandas as pd
from xtquant import xtdata
h=Path(__file__).resolve().parent;o=h/'cache/gap_minutes';o.mkdir(exist_ok=True)
for symbol in ['300308.SZ','600667.SH']:
 xtdata.download_history_data(symbol,'1m','20260813','20260916',incrementally=False)
 d=xtdata.get_market_data_ex([],[symbol],period='1m',start_time='20260813',end_time='20260916',dividend_type='none',fill_data=False)[symbol].copy()
 d['bar_end_time']=pd.to_datetime(d['time'],unit='ms',utc=True).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
 d['trade_date']=d.bar_end_time.dt.normalize();d['qmt_code']=symbol;d['symbol']=symbol[:6];d['exchange']=symbol[-2:];d['period']='1m';d['adjust']='none';d['source']='qmt_xtdata';d['volume']=d.volume*100
 d.reset_index(drop=True).to_parquet(o/f'{symbol}_1m.parquet',index=False);print(symbol,len(d),d.trade_date.min(),d.trade_date.max(),flush=True)
