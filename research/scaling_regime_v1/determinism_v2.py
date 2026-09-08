"""Independent account executions and byte-level artifact comparisons."""
from concurrent.futures import ProcessPoolExecutor
import json
from .accounts import group_cases,folder,run_case
from .audit import HERE,sha256
import pandas as pd


def main():
    rows=[]
    cases=[tuple(list(c[:5])+['capital_timeline_native']) for c in group_cases('native')]
    assert all((folder(*c)/'capital_trace_receipt.json').exists() for c in cases)
    for case in cases:
        actual=folder(*case);baseline=folder(*case[:5],'accounts')
        r=json.loads((actual/'receipt.json').read_text())
        for name,digest in r['hashes'].items():
            expected=sha256(baseline/name)
            assert digest==expected,(case,name)
            rows.append(dict(case=actual.name,layer='NATIVE_ACTUAL_RERUN',artifact=name,sha256=digest,status='PASS'))
    for original in sorted((HERE/'cache/identity_prefix_interrupted').glob('*/receipt.json')):
        dest=HERE/'cache/identity_prefix'/original.parent.name
        if not (dest/'receipt.json').exists():continue
        old=json.loads(original.read_text());new=json.loads((dest/'receipt.json').read_text())
        for name,digest in new['hashes'].items():
            assert old['hashes'][name]==digest==sha256(original.parent/name)
            rows.append(dict(case=dest.name,layer='TOP_PREFIX_ACTUAL_RERUN',artifact=name,sha256=digest,status='PASS'))
    pd.DataFrame(rows).to_csv(HERE/'output/continuous_determinism.csv',index=False)
    print('ACTUAL_ACCOUNT_DETERMINISM_PASS',len(rows),flush=True)


if __name__=='__main__':main()
