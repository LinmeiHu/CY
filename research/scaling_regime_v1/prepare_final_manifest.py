"""Extend provenance without replacing any parent's expected digest."""
import json
from pathlib import Path
from .audit import HERE,ROOT,sha256,write_json,verify_inputs
from .snapshot import INDUSTRY


def run():
    path=HERE/'input_manifest.json';manifest=json.loads(path.read_text());files={r['path']:r for r in manifest['files']}
    def add(p,digest=None,role='continuous_identity_extension'):
        p=Path(p);key=str(p);expected=digest or sha256(p)
        if key in files:
            assert files[key]['sha256']==expected,(key,'EXPECTED_HASH_DRIFT')
            return
        files[key]=dict(path=key,sha256=expected,role=role,roles=[role])
    for p,digest in json.loads((HERE/'account_run_input_identity.json').read_text()).items():add(p,digest)
    for p in [ROOT.parent.parent/'CY/src/cyq_game/data/full_market.py',INDUSTRY,
        Path('/Users/linmei/Documents/CY/data/input_snapshots/CYQ-PREP-2018-2026-20260820.json'),
        Path('/Users/linmei/Documents/CY/data/input_inventories/QD-008-eastmoney-pit-20260820.json')]:add(p,role='original_industry_snapshot_source')
    for p in json.loads((HERE/'output/capacity_minute_source_paths.json').read_text()):add(p,role='actual_capacity_minute_denominator')
    for p in sorted((HERE/'contracts').glob('*.json')):add(p,role='versioned_contract_or_freeze_receipt')
    add(HERE/'scaling_observer.py',json.loads((HERE/'contracts/scaling_observation_extension_v1.json').read_text())['observer_source_sha256'],role='read_only_scaling_observation_extension')
    manifest['files']=sorted(files.values(),key=lambda r:r['path'])
    manifest['extension']='Continuous protocol source, prepared execution inputs and actual capacity denominator sources appended; all original expected digests preserved'
    manifest['no_state_conditioned_outcomes_read_at_initial_manifest_creation']=manifest.pop('no_state_conditioned_outcomes_read',True)
    write_json(path,manifest);verify_inputs()


if __name__=='__main__':run()
