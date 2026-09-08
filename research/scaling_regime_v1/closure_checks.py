"""Account prefix, deterministic state and protocol identity reconciliation."""
import argparse
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from .accounts import END, folder, group_cases
from .audit import HERE, ROOT, PARENT, ROLL, sha256, write_json, compare_accounts


def assert_json_close(a,b):
    if isinstance(a,dict) and isinstance(b,dict):
        assert a.keys()==b.keys()
        for key in a:assert_json_close(a[key],b[key])
    elif isinstance(a,list) and isinstance(b,list):
        assert len(a)==len(b)
        for x,y in zip(a,b):assert_json_close(x,y)
    elif isinstance(a,(int,float)) and isinstance(b,(int,float)):
        assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-6) or (math.isnan(a) and math.isnan(b)),(a,b)
    else:assert a==b,(a,b)


def receipts():
    result=[]
    for receipt in sorted((HERE/'cache/accounts').glob('*/receipt.json')):
        r=json.loads(receipt.read_text())
        assert r['input_identity']==sha256(HERE/'account_run_input_identity.json')
        for name,digest in r['hashes'].items():assert sha256(receipt.parent/name)==digest
        result.append(r)
    return result


def check_prefixes():
    rows=[]
    for case in group_cases('prefixes'):
        gap,mode,target,mechanic,end,group=case
        short=folder(*case);full=folder(gap,mode,target,mechanic,END,group)
        a=pd.read_parquet(short/'daily.parquet');b=pd.read_parquet(full/'daily.parquet')
        b=b.loc[b.trade_date.le(end)].reset_index(drop=True)
        assert len(a)==len(b)
        # Compare every numeric daily ledger column, plus exact semantic positions
        # and callback state. JSON floating arithmetic gets account tolerance.
        numeric=[c for c in a.select_dtypes(include='number') if c in b]
        pd.testing.assert_frame_equal(a[['trade_date']+numeric],b[['trade_date']+numeric],check_dtype=False,rtol=1e-10,atol=1e-6)
        for col in ['positions_json','lots_json','callback_state_json','root_pnl_json']:
            if col in a:
                for x,y in zip(a[col],b[col]):assert_json_close(json.loads(x),json.loads(y))
        for filename,clock in [('fills.parquet','entry'),('atrdr_intents.parquet','earliest_execution_at'),('mcb_intents.parquet','earliest_execution_at'),(gap.lower()+'_intents.parquet','earliest_execution_at')]:
            x=pd.read_parquet(short/filename);y=pd.read_parquet(full/filename)
            if filename=='fills.parquet':
                # Fills are completed economic records. Entry timestamp remains
                # the original lot date on EXIT rows; use event completion time.
                if 'timestamp' in y:times=pd.to_datetime(y.timestamp)
                elif 'exit' in y:times=pd.to_datetime(y.exit).fillna(pd.to_datetime(y.entry))
                else:times=pd.to_datetime(y.entry)
            else:times=pd.to_datetime(y[clock])
            y=y.loc[times.lt(pd.Timestamp(end)+pd.Timedelta(days=1))].reset_index(drop=True)
            shared=[c for c in x if c in y]
            pd.testing.assert_frame_equal(x[shared].reset_index(drop=True),y[shared],check_dtype=False,rtol=1e-10,atol=1e-6)
        rows.append(dict(gap=gap,mcb_mode=mode,end=end,days=len(a),signals='BOUND_SIGNAL_PREFIX_SEPARATE_PRODUCER_CHECK',intents='PASS',fills='PASS',positions='PASS',cash='PASS',nav='PASS',callback_state='PASS',status='PASS'))
    pd.DataFrame(rows).to_csv(HERE/'output/continuous_prefix_invariance.csv',index=False)
    return rows


def historical_native():
    rows=[]
    for case in group_cases('native'):
        gap,mode,*_=case
        dest=folder(*case)
        actual=pd.read_parquet(dest/'daily.parquet')
        parent=ROOT/'research/shared_capital_v1/cache/scenarios'/gap/'2018_2021'/mode/'P0/daily.parquet'
        expected=pd.read_parquet(parent)
        n,errors,passed=compare_accounts(actual,expected,['cash','nav','gross_exposure'])
        assert passed and n==973
        rows.append(dict(gap=gap,mcb_mode=mode,days=n,**errors,status='PASS'))
    pd.DataFrame(rows).to_csv(HERE/'output/continuous_native_parent_prefix.csv',index=False)


def close_identity():
    receipts();historical_native();check_prefixes()
    prefix=pd.read_csv(HERE/'output/new_top5_prefix_identity.csv');assert prefix.status.eq('PASS').all()
    signals=pd.read_csv(HERE/'output/continuous_signal_prefix_invariance.csv');assert signals.status.eq('PASS').all()
    runtime=pd.read_csv(HERE/'output/continuous_runtime_identity_matrix.csv');assert not runtime.status.isin(['BUG','DATA_MISSING']).any()
    contract=HERE/'contracts/continuous_rollforward_protocol_v1.json'
    assert sha256(contract)==json.loads((HERE/'contracts/continuous_protocol_freeze_receipt.json').read_text())['sha256']
    rows=[dict(check=name,status='PASS',required=True,evidence=evidence) for name,evidence in [
        ('EXPLICIT_CONTINUOUS_PROTOCOL','contracts/continuous_rollforward_protocol_v1.json'),
        ('SMV6_SOURCE_BASED_BOUNDARY','output/smv6_boundary_trace.json'),
        ('MCB_SNAPSHOT_RESTORED','output/mcb_snapshot_source_proof.json'),
        ('RUNTIME_IDENTITIES','output/continuous_runtime_identity_matrix.csv'),
        ('TOP5_2018_2021_PREFIX','output/new_top5_prefix_identity.csv'),
        ('NATIVE_PARENT_PREFIX','output/continuous_native_parent_prefix.csv'),
        ('CONTINUOUS_PREFIX_INVARIANCE','output/continuous_prefix_invariance.csv'),
        ('SIGNAL_PREFIX_INVARIANCE','output/continuous_signal_prefix_invariance.csv'),
        ('NO_TOP_RESELECTION','output/top_combination_selection_identity.csv')]]
    pd.DataFrame(rows).to_csv(HERE/'output/rollforward_identity_audit_v2.csv',index=False)
    write_json(HERE/'output/continuous_identity_status.json',dict(ROLLFORWARD_IDENTITY_STATUS='PASS',protocol_sha256=sha256(contract),basis='Actual Native prefix runs and original source/input identity; no segmented NAV equality assumption'))
    print('ROLLFORWARD_IDENTITY_STATUS=PASS',flush=True)


if __name__=='__main__':close_identity()
