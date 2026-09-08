"""Complete discovery-only path labels, censored at invalid/missing sessions."""
import numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
from .build import HERE,EXT,DAILY,setup,js

def path_arrays(close,high,low,idx,invalid,h):
 n=len(close);out=np.full((n,5),np.nan)
 if n<=h:return out
 from numpy.lib.stride_tricks import sliding_window_view as sw
 cl=sw(close,h+1);hi=sw(high,h+1)[:,1:];lo=sw(low,h+1)[:,1:]
 valid=(idx[h:]-idx[:-h]==h)&(invalid[h:]==invalid[:-h])&(cl[:,0]>0)
 equity=cl/cl[:,0,None];dd=(equity/np.maximum.accumulate(equity,axis=1)-1).min(axis=1)
 values=np.column_stack([hi.max(axis=1)/cl[:,0]-1,lo.min(axis=1)/cl[:,0]-1,dd,hi.argmax(axis=1)+1,lo.argmin(axis=1)+1]);values[~valid]=np.nan;out[:n-h]=values
 return out

def main():
 c=setup();raw=c.execute(f"select symbol,trade_date,coord_close,coord_high,coord_low,cal_idx,invalid_step_cum from read_parquet('{DAILY}') where trade_date>='2018-01-01' and trade_date<'2022-01-01' order by symbol,trade_date").fetchdf()
 target=EXT/'panel/discovery_path_labels.parquet';writer=None;count=0
 for symbol,g in raw.groupby('symbol',sort=False):
  out=g[['symbol','trade_date']].copy()
  for h in [20,40,60]:
   a=path_arrays(*(g[k].to_numpy() for k in ['coord_close','coord_high','coord_low','cal_idx','invalid_step_cum']),h)
   for j,k in enumerate(['mfe','mae','future_dd','time_to_mfe','time_to_mae']):out[k+str(h)]=a[:,j]
  table=pa.Table.from_pandas(out,preserve_index=False)
  if writer is None:writer=pq.ParquetWriter(target,table.schema)
  writer.write_table(table);count+=len(out)
 writer.close()
 c.execute(f"copy(select d.*,r.q20,r.q40,r.q60,r.persistent_excess_score,r.persistent_rank,p.* exclude(symbol,trade_date),s.circulating_market_value,a.* exclude(trade_date),m.* exclude(trade_date),b.participation from read_parquet('{EXT}/panel/discovery_uncovered_labels.parquet') d left join read_parquet('{EXT}/panel/discovery_scored.parquet') r using(symbol,trade_date) left join read_parquet('{target}') p using(symbol,trade_date) left join read_parquet('{EXT}/panel/discovery_size.parquet') s using(symbol,trade_date) left join read_parquet('{EXT}/panel/discovery_account_context.parquet') a using(trade_date) left join read_parquet('{EXT}/panel/discovery_market_context.parquet') m using(trade_date) left join read_parquet('{EXT}/panel/discovery_breadth.parquet') b using(trade_date)) to '{EXT}/panel/discovery_complete.parquet' (format parquet)")
 summary=c.execute(f"select count(*) n,count(mfe60) path_complete60,min(trade_date) start_date,max(trade_date) end_date from read_parquet('{EXT}/panel/discovery_complete.parquet')").fetchdf().iloc[0].to_dict();js(HERE/'output/path_labels_summary.json',summary);print(summary)
if __name__=='__main__':main()
