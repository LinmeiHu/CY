"""Read-only identity gate. No outcome attribution runs after a mismatch."""
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PARENT = ROOT / 'research/capital_scaling_v1'
ORIGINAL = Path('/Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1')
ROLL = Path('/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2')
START_HEAD = '77128f86ff40673102f60860100d8504d801e2d2'
OUT = HERE / 'output'


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n')


def frozen_ranking(frame):
    selected = frame.loc[frame.scope.eq('COMBINED') & frame.period.eq('2018_2021')
                         & frame.grade.eq('EXECUTION_AWARE_SCALING')
                         & frame.mechanic.eq('FULL_BOOK_NORMALIZATION')
                         & frame.priority.fillna('').eq('')]
    if selected[['gap', 'mcb_mode', 'target']].duplicated().any():
        raise ValueError('duplicate ranking candidate')
    return selected.sort_values(['CAGR', 'gap', 'mcb_mode', 'target'],
                                ascending=[False, True, True, True]).head(5).reset_index(drop=True)


def compare_accounts(actual, expected, fields, tolerance=1e-6):
    if actual.trade_date.duplicated().any() or expected.trade_date.duplicated().any():
        raise ValueError('duplicate account date')
    paired = actual.merge(expected, on='trade_date', suffixes=('_actual', '_expected'), validate='one_to_one')
    if len(paired) != len(expected):
        raise ValueError('missing required account dates')
    errors = {}
    for field in fields:
        values = paired[[field + '_actual', field + '_expected']].to_numpy(float)
        if not np.isfinite(values).all():
            raise ValueError('nonfinite identity evidence')
        errors[field] = float(abs(values[:, 0] - values[:, 1]).max())
    return len(paired), errors, max(errors.values()) <= tolerance


def require_identity(rows):
    failures = [r for r in rows if r['required'] and r['status'] != 'PASS']
    if failures:
        raise ValueError('ROLLFORWARD_IDENTITY_FAILED: ' + ','.join(sorted({r['check'] for r in failures})))


def verify_inputs():
    manifest = json.loads((HERE / 'input_manifest.json').read_text())
    def verify(row):
        path = Path(row['path'])
        actual = sha256(path) if path.is_file() else 'MISSING'
        return dict(row, actual_sha256=actual, status='PASS' if actual == row['sha256'] else 'FAIL')
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(verify, manifest['files']))
    pd.DataFrame(result).to_csv(OUT / 'input_hash_verification.csv', index=False)
    if any(row['status'] != 'PASS' for row in result):
        raise ValueError('audit input identity drift; see input_hash_verification.csv')
    print('INPUT_HASHES_PASS', len(result), flush=True)


def initialize_manifest():
    target = HERE / 'input_manifest.json'
    if target.exists():
        return
    files = {}
    def add(path, expected=None, role='identity_evidence'):
        path = Path(path).resolve()
        row = dict(path=str(path), sha256=expected or sha256(path), role=role)
        if str(path) in files and files[str(path)]['sha256'] != row['sha256']:
            raise ValueError('conflicting expected hashes')
        row['roles'] = sorted(set(files.get(str(path), {}).get('roles', [])) | {role})
        files[str(path)] = row
    for row in json.loads((HERE / 'evidence/source_inventory.json').read_text()):
        add(row['original_path'], row['sha256'], 'uncommitted_rollforward_source')
        add(ROOT / row['snapshot'], row['sha256'], 'reviewable_source_snapshot')
    add(HERE / 'contracts/scaling_regime_attribution_v1.json',
        json.loads((HERE / 'contracts/freeze_receipt.json').read_text())['contract_sha256'], 'pre_analysis_contract')
    add(PARENT / 'contracts/capital_scaling_policy_v1.json')
    add(PARENT / 'output/scenario_summary.csv')
    parent = json.loads((PARENT / 'input_manifest.json').read_text())
    for path, digest in parent['frozen_source_hashes'].items():
        add(ROOT / path, digest, 'frozen_strategy_identity')
    for row in parent['registered_inputs']:
        add(row['path'], row['expected_sha256'], 'parent_registered_input')
    for row in parent['parent_cache_files']:
        add(row['path'], row['sha256'], 'parent_cache')
    for path, digest in json.loads((PARENT / 'output/engine_manifest.json').read_text())['producers'].items():
        add(ROOT / path, digest, 'frozen_parent_engine')
        add(ORIGINAL / path, digest, 'rollforward_imported_parent_engine')
    top = pd.read_csv(HERE / 'evidence/combined_top5_backtest_curve_selection.csv')
    for row in top.itertuples(index=False):
        folder = Path(row.source)
        receipt = json.loads((folder / 'receipt.json').read_text())
        add(folder / 'receipt.json')
        for name, digest in receipt['hashes'].items():
            add(folder / name, digest, 'sealed_parent_top5_account')
    for folder in sorted((ROLL / 'combinations').iterdir()):
        for name in ('account.json', 'daily.parquet', 'receipt.json', 'scaling.json',
                     'fills.parquet', 'timeline.parquet', 'home_before_funding.parquet',
                     'atrdr_intents.parquet', 'mcb_intents.parquet', 'ogr_intents.parquet', 'ifcgr_intents.parquet'):
            if (folder / name).exists():
                add(folder / name, role='observed_rollforward_account_not_parent_sealed')
    # Metadata only: no market state/outcome join and no new tail scan.
    add(ROLL / 'daily.parquet', role='rollforward_panel_schema_evidence')
    for name in ('common_p0_v06.py', 'native_states_v06.py'):
        add(ROOT / 'research/shared_capital_v1' / name)
    for gap in ('OGR', 'IFCGR'):
        cache = ORIGINAL / 'research/shared_capital_v1/cache/common_p0' / gap / '2022_2023'
        for name in ('daily.parquet', 'atrdr_intents.parquet', 'mcb_intents.parquet', gap.lower() + '_intents.parquet'):
            add(cache / name, role='parent_2022_boundary_evidence')
    add(ROOT / 'research/shared_capital_v1/output/smv6_initial_state_2022.json')
    write_json(target, dict(parent_head=START_HEAD, files=sorted(files.values(), key=lambda r: r['path']),
                           binding='Existing parent expected hashes preserved; unsealed rollforward bound to observed bytes, not retroactively sealed',
                           no_state_conditioned_outcomes_read=True))


def run():
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    if branch != 'research/five-strategy-scaling-regime-v1':
        raise ValueError('wrong branch')
    subprocess.run(['git', 'merge-base', '--is-ancestor', START_HEAD, 'HEAD'], cwd=ROOT, check=True)
    initialize_manifest()
    verify_inputs()
    top = pd.read_csv(HERE / 'evidence/combined_top5_backtest_curve_selection.csv').sort_values('rank')
    ranking = frozen_ranking(pd.read_csv(PARENT / 'output/scenario_summary.csv'))
    if len(top) != 5:
        raise ValueError('Top 5 identity incomplete')
    rows, boundary, prefixes, request_checks = [], [], [], []
    parent_policy = json.loads((PARENT / 'contracts/capital_scaling_policy_v1.json').read_text())
    builder = (HERE / 'evidence/build_rollforward_inputs.py').read_text()
    import pyarrow.parquet as pq
    schema = pq.read_schema(ROLL / 'daily.parquet').names
    replacement = "('d.industry_snapshot_id IS NOT NULL','d.causal_industry IS NOT NULL')" in builder
    parent_guard = 'd.industry_snapshot_id IS NOT NULL' in (ROOT / 'src/five_strategy_bundle/strategies/mcb.py').read_text()
    smv6_state = json.loads((ROOT / 'research/shared_capital_v1/output/smv6_initial_state_2022.json').read_text())
    for gap in ('OGR', 'IFCGR'):
        native = ROLL / 'combinations' / f'{gap}_independent_NATIVE'
        old = ORIGINAL / 'research/shared_capital_v1/cache/common_p0' / gap / '2022_2023'
        actual = pd.read_parquet(native / 'daily.parquet')
        expected = pd.read_parquet(old / 'daily.parquet')
        fields = ['nav', 'cash', 'gross_exposure', 'SMV6_nav', 'SMV6_cash', 'SMV6_exposure']
        count, errors, passed = compare_accounts(actual, expected, fields)
        first = expected.trade_date.iloc[0]
        for field in fields:
            x = float(actual.loc[actual.trade_date.eq(first), field].iloc[0])
            y = float(expected.iloc[0][field])
            boundary.append(dict(gap=gap, date=str(first.date()), field=field, parent_value=y,
                                 rollforward_value=x, difference=x-y, max_abs_difference_2022_2023=errors[field],
                                 shared_dates=count, status='PASS' if errors[field] <= 1e-6 else 'FAIL'))
        before = actual.loc[actual.trade_date.eq('2021-12-31')].iloc[0]
        boundary.append(dict(gap=gap, date='2022-01-01', field='SMV6_initial_cash',
                             parent_value=smv6_state['cash'], rollforward_value=float(before.SMV6_cash),
                             difference=float(before.SMV6_cash)-smv6_state['cash'],
                             max_abs_difference_2022_2023=None, shared_dates=1, status='FAIL'))
        for strategy in ('ATRDR', 'MCB', gap):
            name = strategy.lower() + '_intents.parquet'
            x, y = pd.read_parquet(native / name), pd.read_parquet(old / name)
            z = x.merge(y, on='event_id', suffixes=('_actual', '_expected'), validate='one_to_one')
            delta = z.native_requested_notional_actual - z.native_requested_notional_expected
            request_checks.append(dict(gap=gap, strategy=strategy, shared_events=len(z),
                                       parent_events=len(y), max_abs_difference=float(delta.abs().max()),
                                       status='PASS' if len(z)==len(y) and delta.abs().max()<=1e-6 else 'FAIL'))
    for index, row in enumerate(top.itertuples(index=False)):
        expected = ranking.iloc[index]
        key = ['gap', 'mcb_mode', 'target']
        base = dict(rank=int(row.rank), gap=row.gap, mcb_mode=row.mcb_mode, target=row.target)
        def check(name, status, expected_value, actual_value, evidence, required=True):
            rows.append(dict(base, check=name, required=required, status=status, expected=str(expected_value),
                             actual=str(actual_value), evidence=evidence))
        same = all(getattr(row, k)==expected[k] for k in key) and abs(row.CAGR-expected.CAGR)<1e-12
        check('FROZEN_2018_2021_RANKING', 'PASS' if same else 'FAIL',
              '/'.join(str(expected[k]) for k in key), '/'.join(str(getattr(row,k)) for k in key),
              'Recomputed only from parent 2018_2021 combined Full Book execution-aware scenario_summary')
        check('NO_POST_2021_RESELECTION', 'PASS' if same else 'FAIL', 'same ranked identity',
              'same ranked identity' if same else 'changed identity', 'export_continuous_top5.py reads original ranked selection')
        folder = ROLL / 'combinations' / f'{row.gap}_{row.mcb_mode}_{row.target}'
        receipt = json.loads((folder / 'receipt.json').read_text())
        scaling = json.loads((folder / 'scaling.json').read_text())
        from research.capital_scaling_v1.scaling import Scaling
        actual_mechanic = Scaling(('ATRDR', 'MCB', row.gap, 'SMV6'), scaling['target']).mechanic
        identity = receipt['gap']==row.gap and receipt['mode']==row.mcb_mode and receipt['target']==row.target
        check('COMBINATION_GAP_MCB_TARGET', 'PASS' if identity else 'FAIL',
              f'{row.gap}/{row.mcb_mode}/{row.target}', f"{receipt['gap']}/{receipt['mode']}/{receipt['target']}", 'actual account receipt')
        check('FULL_BOOK_MECHANIC', 'PASS' if actual_mechanic=='FULL_BOOK_NORMALIZATION' else 'FAIL',
              'FULL_BOOK_NORMALIZATION', actual_mechanic, 'hash-matched Scaling default and actual rollforward constructor')
        a, b = pd.read_parquet(folder / 'daily.parquet'), pd.read_parquet(Path(row.source) / 'daily.parquet')
        count, errors, passed = compare_accounts(a, b, ['nav', 'cash', 'gross_exposure'])
        prefixes.append(dict(base, shared_days=count, **{k+'_max_abs_difference':v for k,v in errors.items()}, status='PASS' if passed else 'FAIL'))
        check('2018_2021_ACCOUNT_PREFIX', 'PASS' if passed and count==973 else 'FAIL',
              '973 dates; max absolute difference <=1e-6 CNY', json.dumps(errors,sort_keys=True), 'direct account comparison; does not prove later identity')
        check('FROZEN_SOURCE_AND_COSTS', 'PASS', 'same parent source hashes and costs',
              'same imported engine and frozen strategy file hashes', 'input_hash_verification.csv; runtime transformation audited separately')
        check('INITIAL_STATE_BOUNDARY_PROTOCOL', 'FAIL', parent_policy['initial_states'],
              'CONTINUOUS_2018_2026; SMV6 callback initialized once in 2018',
              'run_continuous_combinations.py; native_boundary_mismatch.csv')
        check('NATIVE_SIZING_REFERENCE_PROTOCOL', 'FAIL', 'per-segment independent P0 HOME_BUDGET',
              'continuous independent P0 HOME_BUDGET; SMV6 state differs from 2022 onward',
              'native_boundary_mismatch.csv; stock request amounts separately reconcile in native_request_comparison.csv')
        check('MCB_ELIGIBILITY_PREDICATE', 'FAIL' if replacement and parent_guard else 'UNVERIFIED',
              'industry_snapshot_id IS NOT NULL', 'causal_industry IS NOT NULL',
              'build_rollforward_inputs.py mcb_screens; the two guards are not logically equivalent')
        check('POST_2021_PARAMETERS_UNCHANGED', 'UNVERIFIED', 'unchanged predicates including provenance guard',
              'numerical alpha thresholds appear unchanged; MCB runtime guard changed',
              'source file hashes alone cannot certify corrected_function runtime substitutions')
        check('STRATEGY_UNIVERSES', 'UNVERIFIED', 'same eligible universes, not only same symbol list',
              'symbol registries claimed unchanged; MCB provenance eligibility differs',
              '3,725 raw symbols / 152 ETFs does not prove per-date eligibility equivalence')
        check('EXECUTION_SEMANTICS_UNCHANGED', 'FAIL', 'parent segment initialization and callback behavior',
              'continuous callbacks give different actual 2022 opening holdings', 'native_boundary_mismatch.csv')
        check('2026_YTD_ONLY', 'PASS' if str(a.trade_date.max().date())=='2026-09-04' else 'FAIL',
              'YTD through 2026-09-04', str(a.trade_date.max().date()), 'daily max date plus export annual_metrics period field')
    pd.DataFrame(rows).to_csv(OUT / 'rollforward_identity_audit.csv', index=False)
    pd.DataFrame(prefixes).to_csv(OUT / 'historical_prefix_reconciliation.csv', index=False)
    pd.DataFrame(boundary).to_csv(OUT / 'native_boundary_mismatch.csv', index=False)
    pd.DataFrame(request_checks).to_csv(OUT / 'native_request_comparison.csv', index=False)
    write_json(OUT / 'mcb_predicate_audit.json', dict(parent_guard_present=parent_guard,
               runtime_replacement_present=replacement, panel_has_industry_snapshot_id='industry_snapshot_id' in schema,
               panel_has_causal_industry='causal_industry' in schema,
               conclusion='PREDICATE_CHANGED_EQUIVALENCE_UNPROVED', signal_difference_claimed=False))
    try:
        require_identity(rows)
    except ValueError as error:
        status = dict(task_status='BLOCKED_ROLLFORWARD_IDENTITY_MISMATCH', identity_status='FAIL',
                      reason=str(error), rejected_top_combinations=5, economic_attribution_run=False,
                      state_conditioned_analysis_run=False, router_status='NOT_EVALUATED_IDENTITY_GATE',
                      capacity_status='NOT_RUN_IDENTITY_GATE', production_authorized=False)
    else:
        raise RuntimeError('Identity outcome changed: review before implementing any economics')
    write_json(OUT / 'completion.json', status)
    pd.DataFrame([dict(decision=k, value=v) for k,v in status.items()]).to_csv(OUT / 'final_decision_matrix.csv', index=False)
    print(json.dumps(status), flush=True)
    return 2


if __name__ == '__main__':
    raise SystemExit(run())
