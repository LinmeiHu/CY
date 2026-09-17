"""Append verified new corporate actions, leaving the registered past untouched."""
from pathlib import Path
import pandas as pd
from research.portfolio_closure_v1 import repair
from .prepare_stock import HERE,CACHE

def main():
    d=pd.read_parquet(HERE/'official_facts/stock_action_official_delta.parquet')
    assert not d.duplicated(['symbol','effective_date']).any()
    assert d.source_terms_complete.all() and d.execution_timing_resolved.all()
    p=pd.read_parquet(HERE/'official_facts/stock_action_delta.parquet').iloc[0]
    q=d.loc[d.symbol.eq('601318')].iloc[0]
    for c in ['record_date','effective_date','pay_date']:assert p[c]==q[c],c
    for c in ['cash_per_share_gross','share_multiplier']:assert abs(p[c]-q[c])<1e-12,c
    for c in ['evidence_source','evidence_hash','retrieved_at','evidence_grade','registered_source']:d[c]=''
    for i,r in d.iterrows():
        source=HERE/'official_facts/cninfo'/f'{r.symbol}.body'
        d.loc[i,['evidence_source','evidence_hash','retrieved_at','evidence_grade','registered_source']]=[r.source_api,repair.digest(source),r.fetched_at,'OFFICIAL_EX_POST_EXECUTION_FACT',str(source)]
    d['tradable_date']=d.share_credit_date
    d.to_parquet(HERE/'official_facts/stock_action_combined_delta.parquet',index=False)
    old=pd.read_parquet('/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2/atrdr/action_registry.parquet')
    assert not set(old.event_id)&set(d.event_id)
    pd.concat([old,d],ignore_index=True).to_parquet(CACHE/'action_registry.parquet',index=False)
    d[['symbol','announcement_date','known_at','record_date','effective_date','pay_date','share_credit_date','cash_per_share_gross','share_multiplier','event_id']].to_csv(HERE/'new_corporate_actions.csv',index=False)
    print('ACTION DELTA PASS',len(d),flush=True)
if __name__=='__main__':main()
