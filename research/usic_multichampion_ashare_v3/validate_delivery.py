"""Validate completed V3 artifacts and seal their bytes; never executes a strategy."""
import argparse
import collections
import json
import platform
from pathlib import Path
import pandas as pd
import numpy as np
from .common import HERE, OUT, sha, dump, scenarios


def read(p):
    return json.loads(Path(p).read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seal', action='store_true')
    args = ap.parse_args()
    expected = {}

    def bind(p, digest=None):
        p = Path(p)
        digest = digest or sha(p)
        assert p.is_file(), p
        assert str(p) not in expected or expected[str(p)] == digest, ('conflicting binding', p)
        expected[str(p)] = digest

    def bindings(obj):
        if isinstance(obj, list):
            for row in obj:
                bindings(row)
        elif isinstance(obj, dict):
            for key, digest_key in [('path', 'sha256'), ('output', 'sha256'), ('source', 'source_sha256'), ('source_manifest', 'source_manifest_sha256'), ('raw_path', 'raw_hash'), ('text_path', 'text_hash'), ('snapshot', 'sha256')]:
                if key in obj and digest_key in obj:
                    bind(obj[key], obj[digest_key])
            for key, val in obj.items():
                if key.startswith('/') and isinstance(val, str) and len(val) == 64:
                    bind(key, val)
                elif isinstance(val, (dict, list)):
                    bindings(val)

    frame = pd.read_csv(HERE/'scenario_summary.csv')
    registered = scenarios()
    assert len(frame) == frame.id.nunique() == len(registered) == 296
    assert set(frame.id) == {s['id'] for s in registered}
    counts = frame.status.value_counts().to_dict()
    assert counts == {'COMPLETED_NEW': 252, 'BLOCKED_PERMISSION': 24, 'NOT_RUN_DATA_GATE': 12, 'BLOCKED_INPUT': 8}, counts
    assert (frame[frame.gate == 'CORE'].status == 'COMPLETED_NEW').sum() == 216
    assert frame.loc[frame.status != 'COMPLETED_NEW', 'net_return'].isna().all()
    assert frame.loc[frame.status != 'COMPLETED_NEW', 'reason'].notna().all()
    audit = read(HERE/'ACCOUNT_AUDIT.json')
    assert audit['all_pass'] and audit['accounts'] == 252
    assert all(x['pass_check'] for x in read(HERE/'PREFIX_CHECKS.json')['checks'])
    assert all(x['pass_'] for x in read(HERE/'Q_QUALIFICATION.json')['checks'])
    analysis = read(HERE/'ANALYSIS_MANIFEST.json')
    repeat_count = 0
    for row in frame[frame.status == 'COMPLETED_NEW'].itertuples():
        folder = OUT/row.id
        identity = read(folder/'identity.json')
        result = read(folder/'result.json')
        assert result['status'] == 'COMPLETED_NEW' and result['nav_rows'] == 970
        for name, digest in identity['artifacts'].items():
            bind(folder/name, digest)
        for name, digest in identity['inputs']['engine'].items():
            bind(HERE/name, digest)
        inputs = identity['inputs']
        bind(folder/'input_signals.parquet', inputs.get('features', inputs.get('signals')))
        bind(HERE/'action_backfill.csv', inputs.get('action_backfill', inputs.get('actions')))
        bind(HERE/'INPUT_MANIFEST.json', inputs.get('input_manifest', inputs.get('daily_inputs')))
        if 'minute_inputs' in inputs:
            bind(HERE/'MINUTE_INPUT_MANIFEST.json', inputs['minute_inputs'])
            bind(HERE/'MINUTE_EXECUTION_MANIFEST.json', inputs['minute_window'])
        nav = pd.read_parquet(folder/'nav.parquet')
        assert len(nav) == 970 and nav.date.is_unique and nav.date.is_monotonic_increasing
        assert str(nav.date.iloc[0])[:10] == '2020-01-02' and str(nav.date.iloc[-1])[:10] == '2023-12-29'
        assert (nav.cash >= 0).all() and (nav.borrowed_cash == 0).all() and (nav.margin == 0).all()
        assert (nav.market_value <= nav.nav + 1e-7).all()
        assert np.max(np.abs(nav.cash + nav.market_value + nav.receivable - nav.nav)) < 1e-6
        assert abs(nav.nav.iloc[-1]/1e6 - 1 - row.net_return) < 1e-12
        checks = folder/'repeat_checks.json'
        if checks.exists():
            values = read(checks)
            assert len(values) == 6 and all(values.values())
            for name in values:
                bind(folder/name.replace('.parquet', '_repeat.parquet'), identity['artifacts'][name])
                repeat_count += 1
        for p in folder.glob('*.json'):
            bind(p)
    assert repeat_count == 66, repeat_count
    for row in analysis['all_account_bindings']:
        bind(OUT/row['id']/'identity.json', row['identity'])
        for name, digest in row['artifacts'].items():
            bind(OUT/row['id']/name, digest)
    for name in ['INPUT_MANIFEST.json', 'EXECUTION_INPUT_BINDING.json', 'Q_EXECUTION_INPUT_BINDING.json', 'FEATURE_MANIFEST.json', 'MINUTE_INPUT_MANIFEST.json', 'MINUTE_EXECUTION_MANIFEST.json', 'Q_FEATURE_MANIFEST.json', 'INHERITED_SOURCE_BINDING.json', 'official_sources.json', 'ANALYSIS_MANIFEST.json', 'EVENT_ANALYSIS_MANIFEST.json', 'EXECUTION_DIAGNOSTIC_MANIFEST.json']:
        bindings(read(HERE/name))
    # Bind all retained input shards and diagnostics, including files outside compact manifests.
    for dirname in ['cache', 'features', 'indicators', 'inherited', 'minute', 'statistics']:
        for p in sorted((OUT/dirname).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                bind(p, expected.get(str(p)))
    for pattern in ['*.parquet', '*.log']:
        for p in OUT.glob(pattern):
            if not p.name.startswith('delivery_'):
                bind(p, expected.get(str(p)))
    for p in HERE.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.name != 'DELIVERY_SEAL.json':
            bind(p, expected.get(str(p)))
    if not args.seal:
        saved = read(HERE/'DELIVERY_SEAL.json')
        assert saved['files'] == expected, 'delivery file set or expected hashes changed'
    for i, (name, digest) in enumerate(sorted(expected.items()), 1):
        assert sha(name) == digest, ('hash mismatch', name)
        if i % 1000 == 0:
            print('VERIFIED_FILES', i, flush=True)
    result = dict(passed=True, unique_slots=296, states=counts, complete_accounts=252, account_artifact_hashes=1512, repeat_hashes=repeat_count, files_verified=len(expected), full_period_sessions=970, python=platform.python_version())
    if args.seal:
        dump(HERE/'DELIVERY_SEAL.json', dict(validation=result, files=expected, exclusions=['DELIVERY_SEAL.json self hash', 'external delivery verification logs and DELIVERY_STATUS.json', 'source ZIP written from final Git commit'], note='No account was run by this validator. All accounts and repeat artifacts were previously executed.'))
    dump(OUT/'delivery_validation.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
