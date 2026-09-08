"""Attach completed-date context to the full causal coverage map, after freeze.
No forward labels or strategy returns are produced or inspected here.
"""
import json,subprocess
import pandas as pd,numpy as np
from .build import HERE,EXT,DAILY,CACHE,PARENT,setup,sha,js

def main():
 subprocess.run(['git','cat-file','-e','7a1cb8ddf7:research/sixth_alpha_visual_discovery_v1/discovery_freeze/FROZEN_MECHANISM_SPEC.json'],check=True)
 c=setup();base=EXT/'coverage/five_strategy_coverage_map.parquet'
 c.execute(f"create temp table base_coverage as select symbol,trade_date,sleeve,causal_industry,industry_valid,ATRDR_BULL,ATRDR_FAST_BEAR,ATRDR_SLOW_BEAR,MCB,OGR,IFCGR,has_unfunded_opportunity,uncovered from read_parquet('{base}')")
 c.execute(f"""create temp table hist as select symbol,trade_date,amount,close,coord_close,cal_idx,invalid_step_cum,available_at,decision_at,
 coord_close/lag(coord_close,20) over w-1 breadth_ret20,
 case when cal_idx=lag(cal_idx) over w+1 and invalid_step_cum=lag(invalid_step_cum) over w then coord_close/lag(coord_close) over w-1 end daily_return,
 {','.join(f'case when cal_idx=lag(cal_idx,{h}) over w+{h} and invalid_step_cum=lag(invalid_step_cum,{h}) over w then coord_close/lag(coord_close,{h}) over w-1 end ret{h}' for h in [20,60,120])},
 avg(amount) over(partition by symbol order by trade_date rows between 19 preceding and current row) adv20
 from read_parquet('{DAILY}') window w as(partition by symbol order by trade_date)""")
 c.execute('create temp table features as select *,stddev_samp(daily_return) over(partition by symbol order by trade_date rows between 59 preceding and current row) vol60 from hist')
 c.execute('create temp table breadth as select trade_date,avg((breadth_ret20>0)::int) breadth from features join base_coverage using(symbol,trade_date) where industry_valid group by 1')
 breadth=c.execute('select * from breadth order by trade_date').fetchdf();rank=breadth.breadth.expanding().rank(pct=True);breadth['participation']=np.select([rank<=1/3,rank<=2/3],['LOW','MID'],default='HIGH');c.register('participation',breadth)
 manifest=HERE/'output/size_source_identity.json';sm=json.loads(manifest.read_text());source=json.loads(open(sm['manifest']).read());paths=[];ids=[]
 from pathlib import Path
 for row in source['files']:
  if any('partition_year='+str(y)+'/' in row['path'] for y in range(2018,2027)):
   p=Path(source['root'])/row['path'];h=sha(p);assert h==row['sha256'];paths.append(str(p));ids.append(dict(path=str(p),sha256=h))
 c.read_parquet(paths).create_view('sizes');c.execute('create temp table cap as select symbol,trade_date,close*circulating_shares circulating_market_value from sizes where hard_valid and float_valid and circulating_shares>0 and available_at<=decision_at and float_available_date<=trade_date')
 account=PARENT/'research/unified_opportunity_risk_v1/output/native_replay/IFCGR/daily.parquet'
 c.execute(f"create temp table account as select trade_date,cash existing_cash,gross_exposure existing_gross,nav existing_nav,ATRDR_exposure,MCB_exposure,IFCGR_exposure,SMV6_exposure from read_parquet('{account}') qualify row_number() over(partition by trade_date order by timestamp desc)=1")
 tmp=base.with_name('coverage_context.tmp.parquet')
 c.execute(f"""copy(select b.*,f.adv20,f.vol60,f.ret20,f.ret60,f.ret120,f.available_at,f.decision_at,s.circulating_market_value,p.breadth,p.participation,
 m.market_regime,m.latest_source_timestamp market_source_timestamp,a.* exclude(trade_date)
 from base_coverage b left join features f using(symbol,trade_date) left join cap s using(symbol,trade_date) left join participation p using(trade_date)
 left join read_parquet('{CACHE}/atrdr/market.parquet') m using(trade_date) left join account a using(trade_date)) to '{tmp}' (format parquet)""")
 assert c.execute(f"select count(*) from read_parquet('{tmp}')").fetchone()[0]==c.execute('select count(*) from base_coverage').fetchone()[0]
 assert c.execute(f"select count(*) from read_parquet('{tmp}') where available_at>decision_at").fetchone()[0]==0
 tmp.replace(base)
 summary=c.execute(f"select year(trade_date) calendar_year,sleeve,count(*) stock_dates,sum(uncovered::int) uncovered_stock_dates,avg(uncovered::int) uncovered_fraction,sum(has_unfunded_opportunity::int) covered_unfunded_dates,count(circulating_market_value) size_available_dates,count(existing_cash) account_context_dates,count(market_regime) market_state_dates from read_parquet('{base}') group by 1,2 order by 1,2").fetchdf();summary.to_csv(HERE/'coverage/coverage_summary.csv',index=False)
 js(HERE/'coverage/full_context_manifest.json',dict(freeze_commit='7a1cb8ddf73bbb1c795ddb6ebf6353593bc7986f',purpose='Causal descriptive coverage only; no forward validation outcomes',size_inputs=ids,account_source=str(account),account_sha256=sha(account),market_source=str(CACHE/'atrdr/market.parquet'),market_sha256=sha(CACHE/'atrdr/market.parquet'),size_missing='Leave missing; no fabricated shares or market cap',account='IFCGR alternative-gap Native account; no OGR/IFCGR double counting'))
 print(summary.to_string(index=False))
if __name__=='__main__':main()
