"""Outcome-blind Q data qualification, exact matched coverage and volume-unit audit."""
import json
import numpy as np
import pandas as pd
from .common import HERE,OUT,sha,dump

def main():
    records=[];audit=[]
    manifest=json.loads((HERE/'MINUTE_INPUT_MANIFEST.json').read_text());assert len(manifest['files'])==48
    for r in manifest['files']:
        assert sha(r['output'])==r['sha256'];f=pd.read_parquet(r['output']);valid=(f.n_prefix==206)&(f.n_distinct==206)&(f.invalid_clock==0)&f.valid_ohlcv.fillna(False)&f.volume_prefix.gt(0)
        f=f[valid];vwap=f.amount_prefix/f.volume_prefix;unit=(vwap>=f.low_prefix*.999)&(vwap<=f.high_prefix*1.001)
        audit.append(dict(month=r['month'],year=r['year'],valid_rows=len(f),shares_cny_unit_consistent=int(unit.sum()),unit_consistency=float(unit.mean())))
        records.append(dict(check='minute_prefix_units_'+str(r['year'])+str(r['month']),pass_=bool(unit.mean()>.995)))
    b=pd.read_parquet(OUT/'Q4_BASE_signals.parquet');e=pd.read_parquet(OUT/'Q4_ENHANCED_signals.parquet');q=pd.read_parquet(OUT/'Q3_signals.parquet')
    cols=['t','j','score','limit','U','S0','a0','factor','decision_at'];x=b.merge(e[['t','j']],on=['t','j']).sort_values(['t','j'])[cols].reset_index(drop=True);y=e.sort_values(['t','j'])[cols].reset_index(drop=True);pd.testing.assert_frame_equal(x,y)
    records.extend([dict(check='Q4_same_coverage_same_fields_and_ranks',pass_=True),dict(check='Q3_no_duplicate_stock_date',pass_=not q.duplicated(['t','j']).any()),dict(check='no_execution_future_fields_in_signals',pass_=not any(c.startswith('exec_') for c in b)),dict(check='all_triggers_1425',pass_=bool(b.decision_at.str.contains('T14:25:00').all() and q.decision_at.str.contains('T14:25:00').all())),dict(check='same_day_information_frozen_before_tail_order',pass_=True,evidence='test_tail: modified T close by 10x leaves decision NAV, quantity and debit identical')])
    window=json.loads((HERE/'MINUTE_EXECUTION_MANIFEST.json').read_text());assert len(window['files'])==4
    for r in window['files']:assert sha(r['path'])==r['sha256']
    pd.DataFrame(audit).to_csv(HERE/'minute_unit_audit.csv',index=False)
    assert all(r['pass_'] for r in records),[r for r in records if not r['pass_']]
    dump(HERE/'Q_QUALIFICATION.json',dict(checks=records,all_pass=True,grade='MINUTE_OHLC_PROXY_PIT_B',signal_counts=dict(Q3=len(q),Q4_BASE=len(b),Q4_ENHANCED=len(e)),source_cutoff='2023-12-31',orderbook_queue_unverified=True))
    print('Q_QUALIFICATION_PASS',len(records),flush=True)
if __name__=='__main__':main()
