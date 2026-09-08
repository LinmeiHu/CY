"""Independent completion checks and fresh deterministic replay evidence."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

from five_strategy_bundle.io import sha256, write_json
from .preflight import HERE, run as preflight
from .run import ACCOUNT_ARTIFACTS, case_key, engine_identity, run_case, scenarios, verify_running_source, verify_case_receipt, verify_baseline
from .data import EXTERNAL, load

OUT = HERE/'output'


def tests_evidence():
    xml = ET.parse(OUT/'hardening_tests.xml')
    cases = []
    for item in xml.iter('testcase'):
        status = 'FAIL' if item.find('failure') is not None or item.find('error') is not None else ('SKIP' if item.find('skipped') is not None else 'PASS')
        cases.append(dict(test=item.attrib['classname']+'::'+item.attrib['name'], status=status))
    if not cases or any(c['status'] == 'FAIL' for c in cases):
        raise ValueError('full relevant test suite has failures')
    # Stable test identities and outcomes; timing/host fields are diagnostic only.
    write_json(OUT/'test_results.json', dict(passed=sum(c['status'] == 'PASS' for c in cases),
                                           skipped=sum(c['status'] == 'SKIP' for c in cases), tests=cases))
    return cases


def derived():
    from .report import plots
    figures = sorted(HERE.glob('reports/*frontiers.*'))
    before = {p: sha256(p) for p in figures}
    plots()
    rows = [dict(file=str(p.relative_to(HERE)), first_sha256=before[p], second_sha256=sha256(p),
                 status='PASS' if before[p] == sha256(p) else 'FAIL') for p in figures]
    pd.DataFrame(rows).to_csv(OUT/'plot_determinism.csv', index=False)
    excluded = {'input_hash_verification.csv', 'frozen_hash_verification.csv', 'plot_determinism.csv',
        'derived_output_determinism.csv', 'deterministic_rerun.csv', 'external_artifact_manifest.csv',
        'physical_account_invariants.csv', 'baseline_reconciliation.csv', 'bug_hardening_status.csv', 'requirement_test_coverage.csv'}
    files = sorted(p for p in OUT.glob('*.csv') if p.name not in excluded)
    files += [HERE/'REPORT.md', HERE/'reports/capacity_assumptions.md', HERE/'reports/structural_idle_habitat.md', OUT/'decision.json', *figures]
    before = {p: sha256(p) for p in files}
    subprocess.run([sys.executable, '-m', 'research.capital_scaling_v1.run', '--stage', 'all'], cwd=HERE.parents[1], check=True)
    rows = [dict(file=str(p.relative_to(HERE)), before_sha256=before[p], after_sha256=sha256(p),
                 status='PASS' if before[p] == sha256(p) else 'FAIL') for p in files]
    pd.DataFrame(rows).to_csv(OUT/'derived_output_determinism.csv', index=False)


def verify_derived():
    counts = {}
    for name, left, right, count in [('plot_determinism', 'first_sha256', 'second_sha256', 4),
                                    ('derived_output_determinism', 'before_sha256', 'after_sha256', 35)]:
        proof = pd.read_csv(OUT/(name+'.csv'))
        if len(proof) != count or proof.file.duplicated().any() or not proof.status.eq('PASS').all():
            raise ValueError('incomplete derived determinism evidence: '+name)
        for row in proof.to_dict('records'):
            if row[left] != row[right] or sha256(HERE/row['file']) != row[right]:
                raise ValueError('derived output changed after repeated generation: '+row['file'])
        counts[name] = len(proof)
    return counts


def deterministic(table, gate):
    data = load()
    identity, payload = engine_identity(data, gate['contract_sha256'])
    if identity != gate['engine_identity']:
        raise ValueError('fresh replay producer is not the completed grid producer')
    native, scaled = scenarios()
    requested = [
        ('SINGLE', 'ATRDR', 'OGR', 'independent', '2018_2021', 'FULL_BOOK_NORMALIZATION', ''),
        ('SINGLE', 'SMV6', 'OGR', 'independent', '2018_2021', 'FULL_BOOK_NORMALIZATION', ''),
        ('COMBINED', 'COMBINED', 'OGR', 'independent', '2018_2021', 'FULL_BOOK_NORMALIZATION', ''),
        ('COMBINED', 'COMBINED', 'IFCGR', 'confirmation_tag', '2022_2023', 'FULL_BOOK_NORMALIZATION', ''),
        ('COMBINED', 'COMBINED', 'OGR', 'independent', '2022_2023', 'ENTRY_ONLY', ''),
        ('COMBINED', 'COMBINED', 'OGR', 'independent', '2022_2023', 'FULL_BOOK_NORMALIZATION', 'ATRDR'),
    ]
    fields = ('scope', 'strategy', 'gap', 'mcb_mode', 'period', 'mechanic', 'priority')
    reference = {case_key(r): Path(r['source']) for r in table.to_dict('records')}
    external = EXTERNAL/'deterministic'
    external.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=identity[:16]+'-', dir=external))
    write_json(root/'identity.json', payload)
    rows = []
    for chosen in requested:
        candidates = [c for c in scaled if tuple(c[k] for k in fields) == chosen and c['target'] == 'G100' and c['grade'] == 'EXECUTION_AWARE_SCALING']
        if len(candidates) != 1:
            raise ValueError('ambiguous registered deterministic case')
        case = candidates[0]
        verify_running_source(payload)
        run_case(case, data, root)  # New empty folder guarantees actual replay.
        verify_running_source(payload)
        for name in (*ACCOUNT_ARTIFACTS, 'scaling.json'):
            expected = sha256(reference[case_key(case)]/name)
            actual = sha256(root/case_key(case)/name)
            rows.append(dict(case=case_key(case), artifact=name, expected_sha256=expected, actual_sha256=actual,
                             actual_path=str(root/case_key(case)/name), engine_identity=identity,
                             status='PASS' if actual == expected else 'FAIL'))
        if any(r['status'] != 'PASS' for r in rows):
            pd.DataFrame(rows).to_csv(OUT/'deterministic_rerun.csv', index=False)
            raise ValueError('fresh deterministic account output differs')
    pd.DataFrame(rows).to_csv(OUT/'deterministic_rerun.csv', index=False)


def verify_deterministic(rerun, table, identity):
    artifacts = set((*ACCOUNT_ARTIFACTS, 'scaling.json'))
    if (len(rerun) != 42 or rerun[['case', 'artifact']].duplicated().any() or rerun.case.nunique() != 6
        or not rerun.status.eq('PASS').all() or not rerun.engine_identity.eq(identity).all()):
        raise ValueError('six fresh physical replays must match all seven account artifacts')
    sources = {case_key(r): Path(r['source']) for r in table.to_dict('records')}
    for key, group in rerun.groupby('case'):
        if set(group.artifact) != artifacts:
            raise ValueError('incomplete deterministic account layer coverage')
        for r in group.itertuples(index=False):
            actual = Path(r.actual_path)
            if not actual.is_relative_to(EXTERNAL/'deterministic') or actual.parent == sources[key]:
                raise ValueError('deterministic evidence must reference a fresh replay directory')
            if sha256(actual) != r.actual_sha256 or sha256(sources[key]/r.artifact) != r.expected_sha256 or r.actual_sha256 != r.expected_sha256:
                raise ValueError('deterministic evidence no longer matches actual account files')


def external_manifest(table):
    rows = []
    invariants = []
    native, scaled = scenarios()
    expected_cases = {case_key(case): case for case in native + scaled}
    for row in table.to_dict('records'):
        folder = Path(row['source'])
        verify_case_receipt(folder, expected_cases[case_key(row)])
        checkpoints = pd.read_parquet(folder/'checkpoints.parquet')
        critical = checkpoints[['cash', 'nav', 'gross_exposure', 'virtual_nav', 'quantity_delta', 'pnl_delta']]
        if critical.empty or not np.isfinite(critical.to_numpy(dtype=float)).all() or checkpoints.timestamp.isna().any():
            raise ValueError('missing or nonfinite physical checkpoint')
        proof = dict(case=case_key(row), checkpoints=len(checkpoints), minimum_cash=float(checkpoints.cash.min()),
            maximum_gross=float((checkpoints.gross_exposure/checkpoints.nav).max()),
            maximum_account_equation_error=float((checkpoints.nav-checkpoints.cash-checkpoints.gross_exposure).abs().max()),
            maximum_virtual_equity_error=float((checkpoints.nav-checkpoints.virtual_nav).abs().max()),
            maximum_quantity_error=float(checkpoints.quantity_delta.abs().max()),
            maximum_pnl_error=float(checkpoints.pnl_delta.abs().max()))
        if (proof['minimum_cash'] < 0 or proof['maximum_gross'] > 1.+1e-12 or checkpoints.nav.min() <= 0
            or max(proof[k] for k in proof if k.startswith('maximum_') and k.endswith('_error')) > 1e-6):
            raise ValueError('physical account invariant failed: '+case_key(row))
        invariants.append(dict(proof, status='PASS'))
        for path in sorted(folder.iterdir()):
            if path.is_file():
                rows.append(dict(case=case_key(row), path=str(path), bytes=path.stat().st_size, sha256=sha256(path)))
    pd.DataFrame(rows).to_csv(OUT/'external_artifact_manifest.csv', index=False)
    pd.DataFrame(invariants).to_csv(OUT/'physical_account_invariants.csv', index=False)


def manifest():
    excluded = {'output_manifest.sha256', 'hardening_tests.xml', 'parent_tests.xml'}
    files = sorted(p for p in HERE.rglob('*') if p.is_file() and p.name not in excluded
                   and not any(x in p.parts for x in ('__pycache__', '.pytest_cache', 'cache')))
    lines = [sha256(p)+'  '+str(p.relative_to(HERE)) for p in files]
    (OUT/'output_manifest.sha256').write_text('\n'.join(lines)+'\n')
    for line in lines:
        expected, name = line.split('  ', 1)
        if sha256(HERE/name) != expected:
            raise ValueError('output changed while sealing')
    return len(files)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--deterministic', action='store_true')
    parser.add_argument('--derived', action='store_true', help='Actually regenerate all derived tables and plots and record byte comparisons')
    args = parser.parse_args(argv)
    preflight()
    gate = json.loads((OUT/'research_gate.json').read_text())
    baseline = json.loads((OUT/'baseline_gate.json').read_text())
    if gate['status'] != 'PASS' or gate['completed'] != 132 or baseline['status'] != 'PASS':
        raise ValueError('incomplete research/baseline gate')
    engine = json.loads((EXTERNAL/'runs'/gate['engine_identity'][:16]/'identity.json').read_text())
    if hashlib.sha256(json.dumps(engine, sort_keys=True).encode()).hexdigest() != gate['engine_identity']:
        raise ValueError('completed engine identity mismatch')
    verify_running_source(engine)
    write_json(OUT/'engine_manifest.json', engine)
    contract = sha256(HERE/'contracts/capital_scaling_policy_v1.json')
    if contract != gate['contract_sha256'] or contract != json.loads((HERE/'contracts/freeze_receipt.json').read_text())['contract_sha256']:
        raise ValueError('pre-outcome frozen contract changed')
    table = pd.read_csv(OUT/'scenario_summary.csv').fillna({'priority': ''})
    native, scaled = scenarios()
    if {case_key(c) for c in native+scaled} != {case_key(c) for c in table.to_dict('records')} or len(table) != 132:
        raise ValueError('frozen grid identity coverage')
    baseline_rows = []
    for case in table.loc[table.target.eq('NATIVE')].to_dict('records'):
        errors = verify_baseline(case, pd.read_parquet(Path(case['source'])/'daily.parquet'))
        baseline_rows.append(dict(case=case_key(case), **{'maximum_'+key+'_error':value for key,value in errors.items()}, status='PASS'))
    pd.DataFrame(baseline_rows).to_csv(OUT/'baseline_reconciliation.csv', index=False)
    tests = tests_evidence()
    if args.derived:
        derived()
    derived_checks = verify_derived()
    if args.deterministic:
        deterministic(table, gate)
    rerun = pd.read_csv(OUT/'deterministic_rerun.csv')
    verify_deterministic(rerun, table, gate['engine_identity'])
    from .audit import run as audit
    audit(tests)
    required = ['bug_hardening_status', 'single_strategy_scaling_frontier', 'single_strategy_g100_results',
        'single_strategy_g100_concentration', 'single_strategy_g100_drawdowns', 'combined_g100_results',
        'capital_scaling_frontier', 'capital_scaling_segment_results', 'scaling_trade_attribution',
        'incremental_capital_efficiency', 'concentration_diagnostics', 'return_concentration_diagnostics',
        'worst_drawdown_attribution', 'idealized_vs_execution_aware', 'capacity_diagnostics',
        'mcb_scaling_role_comparison', 'gap_scaling_comparison', 'priority_scaling_diagnostics',
        'g100_scaling_mechanics_sensitivity', 'risk_budget_reference', 'marginal_frontier',
        'structural_idle_habitat', 'next_alpha_hypotheses', 'final_scaling_decision_matrix', 'requirement_test_coverage']
    for name in required:
        if pd.read_csv(OUT/(name+'.csv')).empty:
            raise ValueError('required compact output empty: '+name)
    for name in ('REPORT.md', 'REPRODUCTION_COMMANDS.md', 'reports/bug_hardening_report.md',
                 'reports/capacity_assumptions.md', 'reports/structural_idle_habitat.md', 'reports/code_simplification_audit.md'):
        if not (HERE/name).is_file() or not (HERE/name).read_text().strip():
            raise ValueError('required research report missing: '+name)
    external_manifest(table)
    write_json(OUT/'completion.json', dict(COMPUTATION_STATUS='COMPLETE', scenarios=132,
        tests_passed=sum(c['status'] == 'PASS' for c in tests), tests_skipped=sum(c['status'] == 'SKIP' for c in tests),
        deterministic_artifact_matches=len(rerun), contract_sha256=contract, engine_identity=gate['engine_identity'],
        derived_determinism=derived_checks,
        frozen_strategies_modified=False, new_sealed_validation_opened=False, production_authorized=False,
        publication='Commit and normal-push evidence must be checked separately against Git.'))
    count = manifest()
    print(json.dumps(dict(COMPUTATION_STATUS='COMPLETE', compact_hashes=count, deterministic_hashes=len(rerun))))


if __name__ == '__main__':
    main()
