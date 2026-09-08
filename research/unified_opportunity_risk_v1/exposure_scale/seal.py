"""Bind this diagnostic separately, without rewriting the parent study verdict."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.data import CONTRACT
from research.unified_opportunity_risk_v1.exposure_scale.run import HERE,OUT


def seal():
    parent=HERE.parent
    assert json.loads((OUT/'test_results.json').read_text())['exit_code']==0
    validation=pd.read_csv(OUT/'account_validation.csv');assert len(validation)==8 and validation.status.eq('PASS').all()
    for line in (parent/'output/output_manifest.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);assert repair.digest(parent/name)==digest,'parent study artifact changed'
    registered_file=parent.parent/'scaling_regime_v1/account_run_input_identity.json'
    registered=json.loads(registered_file.read_text())
    def check(item):
        file,expected=item;actual=repair.digest(file)
        return dict(path=file,expected_sha256=expected,actual_sha256=actual,status='PASS' if actual==expected else 'FAIL')
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(check,registered.items()))
    assert all(r['status']=='PASS' for r in rows)
    pd.DataFrame(rows).to_csv(OUT/'registered_input_hash_verification.csv',index=False)
    old=json.loads((parent/'input_manifest.json').read_text())
    for file,digest in old['frozen_producers'].items():assert repair.digest(file)==digest
    assert json.loads((parent/'output/final_system_spec.json').read_text())['final_decision']=='KEEP_NATIVE'
    accounts={p.parent.name:json.loads(p.read_text()) for p in sorted((OUT/'accounts').glob('*/receipt.json'))}
    assert len(accounts)==8
    repair.write_json(OUT/'account_run_manifest.json',accounts)
    repair.write_json(HERE/'input_manifest.json',dict(parent_contract=repair.digest(CONTRACT),
        parent_verdict_sha256=repair.digest(parent/'output/final_system_spec.json'),parent_engine_sha256=repair.digest(parent/'engine.py'),
        frozen_calibration_sha256=repair.digest(parent/'output/calibration_frozen.json'),risk_reference_sha256=repair.digest(parent/'output/risk_references_frozen.json'),
        diagnostic_contract_sha256=repair.digest(HERE/'contract.json'),registered_inputs=registered,
        research_sources={p.name:repair.digest(p) for p in HERE.glob('*.py')},benchmark_display_only=json.loads((OUT/'benchmark_manifest.json').read_text()),
        existing_verdict='KEEP_NATIVE_UNCHANGED',cash_clipping=False,cash_tolerance=1e-8))
    paths=[p for p in HERE.iterdir() if p.is_file() and p.name!='.DS_Store']+[p for p in OUT.iterdir() if p.is_file() and p.suffix!='.log' and p.name!='output_manifest.sha256']
    (OUT/'output_manifest.sha256').write_text(''.join(f'{repair.digest(p)}  {p.relative_to(HERE)}\n' for p in sorted(paths)))
    print('SEALED',len(rows),'registered inputs',len(accounts),'accounts',len(paths),'artifacts')

if __name__=='__main__':seal()
