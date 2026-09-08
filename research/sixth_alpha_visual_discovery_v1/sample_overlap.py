"""Descriptive coverage caveat for the visual sample; not a candidate near-miss pass."""
import pandas as pd
from .build import HERE,EXT,PARENT,setup,sha,js

def main():
 c=setup();s=pd.read_parquet(EXT/'visual/revealed_discovery_sample.parquet');s=s.loc[s.stage.eq('formal')];c.register('sample',s[['blind_id','symbol','trade_date','label']]);source=PARENT/'research/unified_opportunity_risk_v1/output/native_replay/IFCGR/actual_root_paths.parquet'
 c.execute(f"create temp table holdings as select cast(timestamp as date) trade_date,opportunity_id,symbol,quantity,pending_quantity from read_parquet('{source}') where timestamp<'2022-01-01' qualify row_number() over(partition by cast(timestamp as date),opportunity_id order by timestamp desc)=1")
 result=c.execute(f"""select s.*,exists(select 1 from read_parquet('{EXT}/coverage/causal_opportunity_lineage.parquet') o where s.symbol=o.symbol and o.trade_date<s.trade_date) prior_native_opportunity,
 exists(select 1 from holdings h where h.symbol=s.symbol and h.trade_date=cast(s.trade_date as date) and h.quantity+h.pending_quantity>0) currently_held_native
 from sample s""").fetchdf();result.to_csv(HERE/'coverage/visual_sample_native_overlap.csv',index=False)
 result.groupby('label').agg(n=('blind_id','size'),prior_native_symbol=('prior_native_opportunity','sum'),held_native=('currently_held_native','sum')).to_csv(HERE/'coverage/visual_sample_native_overlap_summary.csv')
 pd.DataFrame([dict(family=f,same_date_overlap=None,same_symbol_overlap=None,holding_overlap=None,threshold_distance=None,status='NOT_APPLICABLE_NO_CANDIDATE',note='Visual sample descriptive native overlap separately in coverage; no independence or near-miss qualification claimed') for f in ['ATRDR_BULL','MCB','OGR_IFCGR']]).to_csv(HERE/'quant/existing_strategy_near_miss.csv',index=False)
 js(HERE/'coverage/sample_overlap_source.json',dict(path=str(source),sha256=sha(source),scope='2018-2021 projected quantity only; IFCGR alternative account',threshold_distance='NOT_RUN_NO_CANDIDATE'))
 print(result.groupby('label')[['prior_native_opportunity','currently_held_native']].sum().to_string())
if __name__=='__main__':main()
