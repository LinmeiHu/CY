"""Causal discovery background, not alpha formulas."""
from .build import *
def main():
 c=setup()
 source=PARENT/'research/unified_opportunity_risk_v1/output/native_replay/IFCGR/daily.parquet'
 c.execute(f"""copy(select trade_date,cash as existing_cash,gross_exposure as existing_gross,
 ATRDR_exposure,MCB_exposure,IFCGR_exposure,SMV6_exposure,nav as existing_nav
 from read_parquet('{source}') where trade_date<'2022-01-01' qualify row_number() over(partition by trade_date order by timestamp desc)=1)
 to '{EXT}/panel/discovery_account_context.parquet' (format parquet)""")
 c.execute(f"""copy(select * from read_parquet('{CACHE}/atrdr/market.parquet') where trade_date<'2022-01-01')
 to '{EXT}/panel/discovery_market_context.parquet' (format parquet)""")
 js(HERE/'coverage/context_manifest.json',dict(native_account='IFCGR alternative-gap Native physical account; OGR/IFCGR must not be added as simultaneous duplicate gap accounts',account_source=str(source),account_sha256=sha(source),market_source=str(CACHE/'atrdr/market.parquet'),market_sha256=sha(CACHE/'atrdr/market.parquet'),scope='2018-2021 only; join on completed decision date; no future account state'))
if __name__=='__main__':main()
