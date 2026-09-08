"""Fail-closed baseline, extreme-first capital grid and reproducible artifacts."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
import hashlib
import json
from multiprocessing import get_context
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from five_strategy_bundle.io import sha256, write_json
from research.shared_capital_v1.common_p0_v06 import replay, PERIODS
from research.shared_capital_v1.shared_study import save_frame
from research.shared_capital_v1.validation import account_validation
from .contract import freeze, POLICY
from .data import load, EXTERNAL
from .metrics import summarize
from .preflight import HERE, PARENT, ROOT, run as preflight
from .scaling import Scaling

OUT = HERE/'output'
ACCOUNT_ARTIFACTS = ('account.json', 'daily.parquet', 'fills.parquet', 'timeline.parquet', 'demand.parquet', 'checkpoints.parquet')


def scenarios():
    singles = [dict(scope='SINGLE', strategy=s, gap=s if s in ('OGR', 'IFCGR') else 'OGR', mcb_mode='independent') for s in ('ATRDR', 'MCB', 'OGR', 'IFCGR', 'SMV6')]
    combined = [dict(scope='COMBINED', strategy='COMBINED', gap=g, mcb_mode=m) for g in ('OGR', 'IFCGR') for m in ('independent', 'confirmation_tag')]
    bases = [dict(b, period=p, start=start, end=end, mechanic='FULL_BOOK_NORMALIZATION', priority='') for b in singles+combined for p, start, end in PERIODS]
    native = [dict(b, target='NATIVE', grade='EXECUTION_AWARE_SCALING') for b in bases]
    extreme = [dict(b, target='G100', grade=grade) for b in bases for grade in ('EXECUTION_AWARE_SCALING', 'IDEALIZED_SCALING_BOUND')]
    middle = [dict(b, target=t, grade='EXECUTION_AWARE_SCALING') for t in ('G25', 'G50', 'G75') for b in bases]
    entry = [dict(b, target='G100', grade='EXECUTION_AWARE_SCALING', mechanic='ENTRY_ONLY') for b in bases if b['scope'] == 'COMBINED']
    priority = [dict(b, target='G100', grade='EXECUTION_AWARE_SCALING', priority=s) for b in bases if b['scope'] == 'COMBINED' and b['mcb_mode'] == 'independent' for s in ('ATRDR', 'MCB', b['gap'], 'SMV6')]
    return native, extreme+middle+entry+priority


def engine_identity(data, contract_hash):
    names = ['common_p0_v06.py', 'stock_p0.py', 'gap_p0.py', 'causal_adapters.py', 'smv6_physical.py',
             'native_states_v06.py', 'universe.py', 'smv6_baseline.py', 'continuous_replay.py', 'build_inputs.py']
    paths = ([PARENT/n for n in names] + sorted((PARENT/'shared_account').glob('*.py'))
             + sorted((ROOT/'src/five_strategy_bundle').rglob('*.py')) + [HERE/'scaling.py', HERE/'data.py', HERE/'run.py'])
    payload = dict(contract=contract_hash, input_manifest=sha256(HERE/'input_manifest.json'), native_reference_manifest=sha256(HERE/'native_reference_manifest.json'), quotes=data['quote_hash'],
                   initial_states={str(p.relative_to(ROOT)): sha256(p) for p in sorted((PARENT/'output').glob('*_initial_state_*.json'))},
                   producers={str(p.relative_to(ROOT)): sha256(p) for p in paths})
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(), payload


def case_key(case):
    return '__'.join(str(case[k]) or 'NONE' for k in ('scope', 'strategy', 'gap', 'mcb_mode', 'period', 'target', 'grade', 'mechanic', 'priority'))


def verify_running_source(payload):
    for name, expected in {**payload['producers'], **payload.get('initial_states', {})}.items():
        if sha256(ROOT/name) != expected:
            raise ValueError('producer changed during active run: '+name)


def native_identity_matches(previous, current):
    fields = ('contract', 'input_manifest', 'native_reference_manifest', 'initial_states')
    if any(key not in previous or previous[key] != current[key] for key in fields):
        return False
    scaling_prefix = str(HERE.relative_to(ROOT)) + '/'
    native_sources = {k: v for k, v in current['producers'].items() if not k.startswith(scaling_prefix)}
    return all(previous.get('producers', {}).get(k) == v for k, v in native_sources.items())


def save_account(folder, account, daily, scaling):
    folder.mkdir(parents=True, exist_ok=True)
    frames = dict(daily=daily, fills=pd.DataFrame(account.fills), timeline=pd.DataFrame(account.account_timeline),
                  demand=pd.DataFrame(account.funding.demand), checkpoints=pd.DataFrame(account.checkpoints))
    for name, frame in frames.items():
        save_frame(frame, folder/f'{name}.parquet')
    names = ['initial_cash', 'cash', 'sleeve_cash', 'lots', 'positions', 'pending_positions', 'marks', 'realized', 'fees',
             'initial_states', 'strategies', 'capital_days_by_event', 'shortfalls', 'native_failures']
    snapshot = {k: getattr(account, k) for k in names}
    snapshot['held_actions'] = [r for service in getattr(account, 'held_actions', {}).values() for r in service.audit]
    if any(r['status'] != 'APPLIED' for r in snapshot['held_actions']):
        raise ValueError('scaled actually held corporate-action gate')
    write_json(folder/'account.json', snapshot)
    if scaling is not None:
        write_json(folder/'scaling.json', dict(target=scaling.target, normalizations=scaling.normalizations,
                                              capacity=scaling.capacity, pending=scaling.pending,
                                              membership=scaling.membership, orders=scaling.orders, execution_grade=scaling.grade))


def read_account(folder):
    a = SimpleNamespace(**json.loads((folder/'account.json').read_text()))
    a.fills = pd.read_parquet(folder/'fills.parquet').to_dict('records')
    for f in a.fills:
        if pd.isna(f.get('root_event_id')):
            f.pop('root_event_id', None)
    a.account_timeline = pd.read_parquet(folder/'timeline.parquet').to_dict('records')
    a.funding = SimpleNamespace(demand=pd.read_parquet(folder/'demand.parquet').to_dict('records'))
    d = pd.read_parquet(folder/'daily.parquet')
    s = SimpleNamespace(**json.loads((folder/'scaling.json').read_text())) if (folder/'scaling.json').exists() else None
    return a, d, s


def verify_baseline(case, daily):
    if case['scope'] == 'COMBINED':
        path = PARENT/'cache/scenarios'/case['gap']/case['period']/case['mcb_mode']/'P0/daily.parquet'
        reference = pd.read_parquet(path)
        fields = ['cash', 'nav', 'gross_exposure']
    else:
        reference = pd.read_parquet(PARENT/'cache/common_p0'/case['gap']/case['period']/'daily.parquet')
        reference = reference.rename(columns={case['strategy']+'_'+f: f+'_reference' for f in ('cash', 'nav', 'exposure')})
        reference['gross_exposure_reference'] = reference.exposure_reference
        fields = ['cash', 'nav', 'gross_exposure']
    if len(reference) != len(daily) or list(pd.to_datetime(reference.trade_date)) != list(pd.to_datetime(daily.trade_date)):
        raise ValueError('required baseline dates differ')
    reference_fields = fields if case['scope'] == 'COMBINED' else [f+'_reference' for f in fields]
    if daily.empty or not np.isfinite(daily[fields].to_numpy(dtype=float)).all() or not np.isfinite(reference[reference_fields].to_numpy(dtype=float)).all():
        raise ValueError('nonfinite or empty baseline account')
    errors = {f: float(np.max(np.abs(daily[f].to_numpy()-reference[f if case['scope'] == 'COMBINED' else f+'_reference'].to_numpy()))) for f in fields}
    if max(errors.values()) > 1e-6:
        raise ValueError('baseline regression: '+json.dumps(errors))
    return errors


def verify_case_receipt(folder, case):
    evidence = json.loads((folder/'receipt.json').read_text())
    if evidence['case'] != case:
        raise ValueError('scenario identity collision')
    for name, expected in evidence['hashes'].items():
        if sha256(folder/name) != expected:
            raise ValueError('cached scenario hash mismatch: '+name)
    artifacts = ACCOUNT_ARTIFACTS + (() if case['target'] == 'NATIVE' else ('scaling.json',))
    if not set(artifacts) <= set(evidence['hashes']) or evidence.get('validation') != 'PASS':
        raise ValueError('incomplete or unvalidated scenario receipt')
    return evidence


def run_case(case, data, root):
    folder = root/case_key(case)
    receipt = folder/'receipt.json'
    artifacts = ACCOUNT_ARTIFACTS + (() if case['target'] == 'NATIVE' else ('scaling.json',))
    if receipt.exists():
        verify_case_receipt(folder, case)
        account, daily, scaling = read_account(folder)
        if (scaling is None) != (case['target'] == 'NATIVE'):
            raise ValueError('cached scaling artifact differs from scenario')
        calendar = data['etf'][0]['000852.SH'].loc[case['start']:case['end']].dropna(subset=['pre_adj_close']).index
        audit = account_validation(daily, calendar)
        if audit['status'] != 'PASS':
            raise ValueError('daily account gate: '+str(audit))
        if case['target'] == 'NATIVE':
            verify_baseline(case, daily)
        print('VERIFIED CACHE', case_key(case), flush=True)
    else:
        print('RUN', case_key(case), flush=True)
        selected = (case['strategy'],) if case['scope'] == 'SINGLE' else ('ATRDR', 'MCB', case['gap'], 'SMV6')
        scaling = None if case['target'] == 'NATIVE' else Scaling(selected, int(case['target'][1:])/100,
                    grade=case['grade'], mechanic=case['mechanic'], priority=case['priority'] or None, mode=case['mcb_mode'])
        working = dict(data, gap=case['gap'])
        account, daily, results, _, _ = replay(working, case['gap'], case['period'], case['start'], case['end'],
                                       mode=case['mcb_mode'], scaling=scaling, selected=selected)
        calendar = data['etf'][0]['000852.SH'].loc[case['start']:case['end']].dropna(subset=['pre_adj_close']).index
        audit = account_validation(daily, calendar)
        if audit['status'] != 'PASS':
            raise ValueError('daily account gate: '+str(audit))
        if case['target'] == 'NATIVE':
            verify_baseline(case, daily)
            if case['mcb_mode'] == 'independent':
                for strategy, result in results.items():
                    actual = result()[0]
                    reference = pd.read_parquet(PARENT/'cache/common_p0'/case['gap']/case['period']/f'{strategy.lower()}_intents.parquet')
                    columns = ['event_id', 'symbol', 'native_requested_notional']
                    pd.testing.assert_frame_equal(actual[columns].reset_index(drop=True), reference[columns].reset_index(drop=True), check_dtype=False, atol=1e-6, rtol=0.)
        save_account(folder, account, daily, scaling)
        # Summaries are regenerated below; only immutable replay artifacts belong
        # in this receipt, including when resuming an interrupted folder.
        hashes = {name: sha256(folder/name) for name in artifacts}
        write_json(receipt, dict(case=case, hashes=hashes, validation='PASS'))
    summary, _, events, fills = summarize(account, daily, case['start'], case['end'], case['gap'], scaling)
    events.to_csv(folder/'event_attribution.csv', index=False)
    fills.to_parquet(folder/'normalized_fills.parquet', index=False)
    row = dict(case, **summary, source=str(folder), validation='PASS')
    write_json(folder/'summary.json', row)
    print('DONE', case['strategy'], case['period'], case['target'], 'CAGR', summary['CAGR'], 'MaxDD', summary['MaxDD'], flush=True)
    return row


def checked_case(case, data, root, payload):
    verify_running_source(payload)
    if sha256(POLICY) != payload['contract']:
        raise ValueError('contract changed after outcome start')
    row = run_case(case, data, root)
    try:
        verify_running_source(payload)
    except ValueError as exc:
        receipt = root/case_key(case)/'receipt.json'
        evidence = json.loads(receipt.read_text())
        write_json(receipt, dict(evidence, validation='FAIL', error=str(exc)))
        raise
    return row


def init_worker(payload):
    global WORKER_DATA, WORKER_PAYLOAD
    verify_running_source(payload)
    WORKER_DATA, WORKER_PAYLOAD = load(), payload
    verify_running_source(payload)


def worker_case(arguments):
    case, root = arguments
    return checked_case(case, WORKER_DATA, Path(root), WORKER_PAYLOAD)


def replay_group(cases, folder, data, payload, pool):
    if pool is None:
        for case in cases:
            yield checked_case(case, data, folder, payload)
        return
    futures = [pool.submit(worker_case, (case, str(folder))) for case in cases]
    try:
        for future in futures:  # Canonical output order, independent case processes.
            yield future.result()
    except BaseException:
        for future in futures:
            future.cancel()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['baseline', 'research', 'all'], default='all')
    parser.add_argument('--revalidate-native', action='store_true')
    parser.add_argument('--workers', type=int, choices=(1, 2, 4), default=1)
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    gate_path = OUT/'baseline_gate.json'
    prior_gate = json.loads(gate_path.read_text()) if gate_path.exists() else {}
    write_json(OUT/'baseline_gate.json', dict(status='RUNNING'))
    write_json(OUT/'research_gate.json', dict(status='NOT_RUN'))
    try:
        return run_stage(args.stage, revalidate_native=args.revalidate_native, prior_gate=prior_gate, workers=args.workers)
    except Exception as exc:
        for name in ('baseline_gate.json', 'research_gate.json'):
            path = OUT/name
            status = json.loads(path.read_text())
            if status['status'] != 'PASS':
                write_json(path, dict(status='FAIL', error=f'{type(exc).__name__}: {exc}'))
        raise


def run_stage(stage, *, revalidate_native=False, prior_gate=None, workers=1):
    preflight()
    contract_hash = freeze()
    data = load()
    identity, payload = engine_identity(data, contract_hash)
    root = EXTERNAL/'runs'/identity[:16]
    root.mkdir(parents=True, exist_ok=True)
    write_json(root/'identity.json', payload)
    native, scaled = scenarios()
    native_root = root
    if prior_gate and prior_gate.get('status') == 'PASS' and not revalidate_native:
        prior_id = prior_gate.get('native_engine_identity') or prior_gate['engine_identity']
        candidate = EXTERNAL/'runs'/prior_id[:16]
        prior_identity = json.loads((candidate/'identity.json').read_text())
        if native_identity_matches(prior_identity, payload):
            # This is the explicitly approved native baseline, bound to its own
            # actual producer identity. Scaling-only repairs do not relabel it
            # as having been generated by a different producer.
            native_root = candidate
    rows = []
    execution = nullcontext(None) if workers == 1 else ProcessPoolExecutor(
        max_workers=workers, mp_context=get_context('spawn'), initializer=init_worker, initargs=(payload,))
    with execution as pool:
        for row in replay_group(native, native_root, data, payload, pool):
            rows.append(row)
            pd.DataFrame(rows).to_csv(OUT/'scenario_summary.csv', index=False)
        write_json(OUT/'baseline_gate.json', dict(status='PASS', scenarios=len(native), parent_reference='LEGACY_SEALED_REFERENCE',
                                                 active_reference='CAUSAL_CORRECTED_REFERENCE', economic_cash_nav_change=False,
                                                 engine_identity=identity, native_engine_identity=(identity if native_root == root else prior_id),
                                                 native_reference_root=str(native_root)))
        if stage == 'baseline':
            return 0
        write_json(HERE/'contracts/outcome_start.json', dict(contract_sha256=contract_hash, engine_identity=identity,
                                                            order='ALL_G100_BEFORE_G25_G50_G75', stage='OUTCOME_STARTED'))
        groups = [scaled[:36], scaled[36:54], scaled[54:72], scaled[72:90], scaled[90:98], scaled[98:]]
        for label, group in zip(('G100_BOTH_GRADES', 'G25', 'G50', 'G75', 'G100_ENTRY_ONLY', 'PRIORITY'), groups):
            print('STAGE', label, 'CASES', len(group), 'WORKERS', workers, flush=True)
            for row in replay_group(group, root, data, payload, pool):
                rows.append(row)
                print('SCALING PROGRESS', len(rows)-len(native), '/', len(scaled), flush=True)
                pd.DataFrame(rows).to_csv(OUT/'scenario_summary.csv', index=False)
    if len(rows) != 132:
        raise ValueError('incomplete frozen grid')
    from .analysis import run
    run()
    write_json(OUT/'research_gate.json', dict(status='PASS', completed=len(rows), engine_identity=identity, contract_sha256=contract_hash))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
