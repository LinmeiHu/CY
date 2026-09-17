"""Acquire official action evidence with the registered CNInfo producer."""
import importlib.util,sys,json,hashlib,time
from pathlib import Path
from datetime import date
import pandas as pd
H=Path(__file__).resolve().parent
P=Path('/Users/linmei/Downloads/workspace/quant/data/staging/crsp_lean_market_data_20260809_v5/lineage/cninfo_producer/fetch_crsp_lean_cninfo_corporate_actions_v1.py')
s=importlib.util.spec_from_file_location('registered_cninfo_producer',P);m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
out=H/'official_facts/cninfo';out.mkdir(parents=True,exist_ok=True)
symbols=sorted({r['symbol'][:6] for r in json.loads((H/'cache/stock_reference_gaps.json').read_text())})
frames=[]
for symbol in symbols:
 p=out/f'{symbol}.parquet'
 if not p.exists():
  r=m.fetch_source_frame('distribution',symbol,rights_start_date='20260901',as_of_date=date(2026,9,16))
  (out/f'{symbol}.body').write_bytes(r.raw_body)
  sha=hashlib.sha256(r.raw_body).hexdigest()
  f=m.normalize_dividend_frame(r.frame,symbol=symbol,security_id='A:'+symbol,vintage_id='candidate_b_20260917',fetched_at=pd.Timestamp.now(tz='UTC').isoformat(),response_sha256=sha)
  f.to_parquet(p,index=False);time.sleep(.35)
 f=pd.read_parquet(p);f=f[f.effective_date.between('2026-09-07','2026-09-16')];frames.append(f);print(symbol,len(f),flush=True)
full=pd.concat(frames,ignore_index=True);full.to_parquet(H/'official_facts/stock_action_official_delta.parquet',index=False)
print('OFFICIAL_ACTION_DELTA',len(full),flush=True)
