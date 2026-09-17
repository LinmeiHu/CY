"""Read-only QMT adjustment facts for the user-authorized history refresh."""
import json
from pathlib import Path
import pandas as pd
from xtquant import xtdata
p=Path(__file__).resolve().parent
rows=[]
for symbol in json.loads((p/'revised_etf_symbols.json').read_text())['symbols']:
    d=xtdata.get_divid_factors(symbol,start_time='20260908',end_time='20260916').copy()
    d['symbol']=symbol;d['effective_date']=pd.to_datetime(d.index.astype(str),format='%Y%m%d')
    rows.append(d.reset_index(drop=True))
out=pd.concat(rows,ignore_index=True);out.to_parquet(p/'cache/etf_adjustment_facts.parquet',index=False)
print(out.to_string(index=False))
