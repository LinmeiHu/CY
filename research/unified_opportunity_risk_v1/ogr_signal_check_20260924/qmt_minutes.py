"""Read-only QMT minute export for new OGR daily survivors."""
import json
from pathlib import Path
import pandas as pd
from xtquant import xtdata

HERE=Path(__file__).parent
OUT=HERE/'cache/gap_minutes'
OUT.mkdir(parents=True,exist_ok=True)
audit={}
for symbol in ['600363.SH','603137.SH']:
    try:
        xtdata.download_history_data(symbol,'1m','20260813','20260923',incrementally=False)
        d=xtdata.get_market_data_ex([],[symbol],period='1m',start_time='20260813',end_time='20260923',dividend_type='none',fill_data=False)[symbol].copy()
        d['bar_end_time']=pd.to_datetime(d['time'],unit='ms',utc=True).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
        d['trade_date']=d.bar_end_time.dt.normalize()
        d['qmt_code']=symbol;d['symbol']=symbol[:6];d['exchange']=symbol[-2:]
        d['period']='1m';d['adjust']='none';d['source']='qmt_xtdata';d['volume']=d.volume*100
        d.reset_index(drop=True).to_parquet(OUT/(symbol+'_1m.parquet'),index=False)
        audit[symbol]={'rows':len(d),'start':str(d.trade_date.min()),'end':str(d.trade_date.max())}
    except Exception as exc:audit[symbol]={'error':repr(exc)}
(HERE/'qmt_minutes_audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False))
