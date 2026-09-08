"""Read-only root capital-day trace; replay must match every baseline byte."""
from concurrent.futures import ProcessPoolExecutor
import json
import time
import pandas as pd
from research.shared_capital_v1.common_p0_v06 import replay
from research.shared_capital_v1.causal_adapters import corrected_function
from . import accounts
from .scaling_observer import ObservedScaling,observer
from .audit import HERE,sha256,write_json
from .economics import require_identity,cases


def trace(case):
    base=accounts.folder(*case)
    while not (base/'receipt.json').exists():time.sleep(10)
    group='capital_timeline_native' if case[2]=='NATIVE' else 'capital_timeline_scaling'
    code_hash=sha256(__file__)
    own=tuple(list(case[:5])+[group]);dest=accounts.folder(*own)
    source=json.loads((base/'receipt.json').read_text())
    if (dest/'capital_trace_receipt.json').exists():
        r=json.loads((dest/'capital_trace_receipt.json').read_text())
        assert r['source_sha256']==sha256(__file__)
        assert r['trace_sha256']==sha256(dest/'root_exposure_timeline.parquet')
        return r
    if case[2]!='NATIVE':
        native=accounts.folder(case[0],'independent','NATIVE','FULL_BOOK_NORMALIZATION',case[4],group)
        native.parent.mkdir(exist_ok=True)
        if not native.exists():native.symlink_to(accounts.folder(case[0],'independent','NATIVE','FULL_BOOK_NORMALIZATION',case[4]))
    records=[]
    def capture(when,values):
        records.append(dict(timestamp=pd.Timestamp(when),root_exposure_json=json.dumps(dict(values),sort_keys=True)))
    observe=accounts.daily_observation if case[2]=='NATIVE' else observer
    accounts.Scaling=ObservedScaling
    accounts.observed_replay=corrected_function(replay,[
        ("row['capital_days']=sum(capital_days.values())",
         "row['capital_days']=sum(capital_days.values())\n        capture(when,last_values)"),
        ('daily.append(dict(row,trade_date=when.normalize()))',
         'observe(account,platform,scaling,row)\n            daily.append(dict(row,trade_date=when.normalize()))')],observe=observe,capture=capture)
    r=accounts.run_case(own)
    if not records:raise ValueError('Orphaned trace account: move own trace folder aside and replay')
    # Read-only observation is proved by all baseline economic artifacts, not
    # by a comparison of this trace with itself.
    for name,digest in source['hashes'].items():assert digest==sha256(dest/name),(case,name,'READ_ONLY_TRACE_CHANGED_ACCOUNT')
    frame=pd.DataFrame(records)
    account=json.loads((base/'account.json').read_text())
    timeline=pd.read_parquet(base/'timeline.parquet')
    assert frame.timestamp.equals(pd.to_datetime(timeline.timestamp))
    totals=frame.root_exposure_json.map(lambda x:sum(json.loads(x).values()))
    assert (totals-timeline.gross_exposure).abs().max()<1e-5
    assert code_hash==sha256(__file__)
    frame.to_parquet(dest/'root_exposure_timeline.parquet',index=False)
    result=dict(case=list(case),source_sha256=sha256(__file__),source_receipt_sha256=sha256(base/'receipt.json'),
        trace_sha256=sha256(dest/'root_exposure_timeline.parquet'),days=len(frame),status='PASS',all_baseline_artifacts_byte_identical=True,
        path=str(dest/'root_exposure_timeline.parquet'))
    write_json(dest/'capital_trace_receipt.json',result)
    print('ROOT_CAPITAL_TRACE_AND_BYTE_PARITY_PASS',case[:4],flush=True)
    return result


def main():
    require_identity()
    # Main action space and extreme comparison; other targets keep the exact
    # portfolio-level capital-days from the parent ledger.
    selected=[c for c in cases() if c[3]=='FULL_BOOK_NORMALIZATION' and c[2] in ['NATIVE','G25','G100']]
    selected.sort(key=lambda c:(c[2]!='NATIVE',c[0],c[1],c[2]))
    with ProcessPoolExecutor(max_workers=2) as pool:r=list(pool.map(trace,selected))
    write_json(HERE/'output/root_capital_trace_receipts.json',r)


if __name__=='__main__':main()
