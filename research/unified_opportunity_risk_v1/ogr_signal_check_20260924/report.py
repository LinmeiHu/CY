"""Record the exact completed stage and missing final gate."""
import json
from pathlib import Path
import pandas as pd
from research.portfolio_closure_v1 import repair

HERE=Path(__file__).parent
PRIOR=HERE.parent/'rollforward_20260917'

def main():
    a=pd.read_parquet(HERE/'select_v28r2.parquet')
    out=a[['symbol','signal_date','gap_date','gap_age','signal_raw_close','signal_raw_amount','signal_amount_to_prior20_median']].copy()
    out['status']='PENDING_120_SESSION_MINUTE_VAP'
    out['formal_signal']=False
    out.to_csv(HERE/'candidate_status.csv',index=False)
    old=pd.read_parquet(PRIOR/'cache/ogr/v13_post2023_candidates.parquet')
    new=pd.read_parquet(HERE/'v13_candidates.parquet')
    prior=set(old.loc[old.signal_date.ge('2026-09-07'),'gap_id'])
    now=set(new.loc[new.signal_date.ge('2026-09-07'),'gap_id'])
    assert prior<=now
    files=[HERE/'baostock_daily_complete.parquet',HERE/'cache/daily_with_snapshot.parquet',HERE/'v13_candidates.parquet',HERE/'select_v28r2.parquet',PRIOR/'cache/daily_with_snapshot.parquet',PRIOR/'cache/ogr/signals_all.parquet']
    status=dict(status='MINUTE_GATE_BLOCKED_QMT_UNAVAILABLE',start='2026-09-17',end='2026-09-23',daily_source='Baostock unadjusted fallback',daily_rows=18565,hard_valid_rows=17855,prior_v13_candidates_preserved=len(prior),new_v13_candidates=10,new_v27_and_daily_quality_survivors=len(out),formal_signals_confirmed=None,minute_requirement='exact 120 trading sessions of 1-minute data per candidate',additional_gates=['QMT overlap','post-2026-09-16 corporate actions'],missing_symbols_with_no_post_september16_bars=json.loads((HERE/'baostock_receipt_complete.json').read_text())['absent_symbols'],input_hashes={str(f):repair.digest(f) for f in files})
    (HERE/'status.json').write_text(json.dumps(status,indent=2,ensure_ascii=False))
    print(out.to_string(index=False),flush=True)

if __name__=='__main__':main()
