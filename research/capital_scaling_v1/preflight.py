"""Read-only parent evidence verification; never invokes superseded producers."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from five_strategy_bundle.io import sha256, write_json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PARENT = HERE.parent / 'shared_capital_v1'
PARENT_HEAD = '7fc40594377c3ec11148e10c5c8a907b43fbd04f'


def run():
    (HERE / 'output').mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'merge-base', '--is-ancestor', PARENT_HEAD, 'HEAD'], cwd=ROOT, check=True)
    status = json.loads((PARENT / 'output/task_status_final_v2.json').read_text())
    if status['COMPUTATION_STATUS'] != 'COMPLETE' or status['P0_STATUS'] != 'PASS':
        raise ValueError('sealed parent baseline gate')
    inputs = pd.read_csv(PARENT / 'output/final_input_hash_verification.csv')
    with ThreadPoolExecutor(max_workers=4) as pool:
        inputs['current_sha256'] = list(pool.map(lambda p: sha256(Path(p)), inputs.path))
    inputs['status'] = inputs.current_sha256.eq(inputs.expected_sha256).map({True: 'PASS', False: 'FAIL'})
    inputs.to_csv(HERE / 'output/input_hash_verification.csv', index=False)
    if not inputs.status.eq('PASS').all():
        raise ValueError('registered input drift')
    frozen = json.loads((PARENT / 'input_manifest.json').read_text())['implementation_hashes']
    frozen = {p: h for p, h in frozen.items() if p.startswith(('original_sources/', 'configs/frozen/', 'src/five_strategy_bundle/strategies/', 'manifests/'))}
    rows = [dict(path=p, expected=h, actual=sha256(ROOT / p)) for p, h in frozen.items()]
    for row in rows:
        row['status'] = 'PASS' if row['expected'] == row['actual'] else 'FAIL'
    pd.DataFrame(rows).to_csv(HERE / 'output/frozen_hash_verification.csv', index=False)
    if any(r['status'] != 'PASS' for r in rows):
        raise ValueError('frozen alpha identity changed')
    from research.shared_capital_v1.universe import verify
    universe = verify(execution_hardening=HERE/'contracts/execution_hardening_v1.json')
    pd.DataFrame(universe['routes']).to_csv(HERE / 'input_universe_confirmation.csv', index=False)
    cached = []
    for strategy in ('atrdr', 'mcb', 'ogr', 'ifcgr', 'smv6'):
        for p in sorted((PARENT / 'cache' / strategy).rglob('*')):
            if p.is_file():
                cached.append(dict(path=str(p.resolve()), sha256=sha256(p), bytes=p.stat().st_size))
    manifest = dict(parent_head=PARENT_HEAD, source_config=str((PARENT.parent / 'five_strategy_exit_risk_v1/input_config.json').resolve()),
                    source_config_sha256=sha256(PARENT.parent / 'five_strategy_exit_risk_v1/input_config.json'),
                    parent_manifest_sha256=sha256(PARENT / 'input_manifest.json'),
                    frozen_source_hashes=frozen, registered_inputs=inputs[['path', 'expected_sha256']].to_dict('records'),
                    parent_cache_files=cached, cache_authority='SEALED_PARENT_REUSE_WITH_INPUT_SOURCE_PERIOD_CONFIG_HASH_BINDING',
                    parent_producer_hashes={str(p.relative_to(ROOT)): sha256(p) for p in sorted(PARENT.rglob('*.py')) if 'cache' not in p.parts and '.venv' not in p.parts},
                    periods=[['2018-01-01', '2021-12-31'], ['2022-01-01', '2023-12-31']],
                    stock_initial_state='PARENT_VALIDATED_CONTINUOUS', etf_initial_state='PARENT_NATIVE_CALLBACK_INIT_RESET',
                    universe_sha256=sha256(PARENT / 'contracts/strategy_universe_v1.json'),
                    external_mount='/Volumes/quant', post_2023_outcomes_used=False)
    target = HERE / 'input_manifest.json'
    if target.exists():
        previous = json.loads(target.read_text())
        # Runtime bug fixes are recorded separately; source inputs never silently drift.
        for key in ('registered_inputs', 'parent_cache_files', 'frozen_source_hashes', 'source_config_sha256', 'periods'):
            if previous[key] != manifest[key]:
                raise ValueError('cache/input identity changed: ' + key)
    else:
        write_json(target, manifest)
    print(json.dumps(dict(ENVIRONMENT_VALID=True, PARENT_HEAD=PARENT_HEAD,
                          input_hashes=len(inputs), frozen_hashes=len(rows), cache_files=len(cached))), flush=True)


if __name__ == '__main__':
    run()
