"""Reproduce truthful progress evidence; exit 2 while continuous P0 is unclosed.

This is a diagnostic closure command, not a 48-scenario replay implementation.
It never converts official date recovery or isolated tests into a baseline pass.
"""
import json,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import xml.etree.ElementTree as ET
import pandas as pd
from research.shared_capital_v1.run_shared_capital_v1 import HERE,ROOT,sha256,frozen_hashes
from research.shared_capital_v1 import universe,ca_execution_audit,ca_final_facts,common_p0_v06
from research.shared_capital_v1.native_states_v06 import state_hash

START='e667b9ee8f6b9780bbee339209790bf150c90f8e'
OUT=HERE/'output'


def hashes():
    expected=pd.read_csv(OUT/'v06_input_hash_verification.csv').set_index('path').expected_sha256.to_dict()
    docs=json.loads((HERE/'manifests/corporate_action_official_backfill_v1.json').read_text())['documents']
    expected.update({d['raw_path']:d['source_hash'] for d in docs})
    expected.update({d['text_path']:d['text_sha256'] for d in docs})
    expected.update({d['query_path']:d['query_sha256'] for d in docs})
    cache_paths=[]
    for strategy in ('atrdr','mcb'):
        cache_paths.extend(HERE/'cache'/strategy/p for p in ('precapital_entry_population.parquet','native_continuous/fills.parquet','native_continuous/nav.parquet'))
    for strategy in ('ogr','ifcgr'):
        cache_paths.extend(HERE/'cache'/strategy/p/'p0_fills.parquet' for p in ('2018_2021','2022_2023'))
    cache_paths.append(HERE/'cache/ogr/signals.parquet')
    cache_paths.extend(HERE/'cache/ifcgr'/p/'signals.parquet' for p in ('2018_2021','2022_2023'))
    cache_receipt=OUT/'final_cache_input_hashes.csv'
    if cache_receipt.exists():
        captured=pd.read_csv(cache_receipt).set_index('path').sha256.to_dict()
        if set(captured)!=set(map(str,cache_paths)):raise ValueError('cache input set changed')
    else:
        captured={str(p):sha256(p) for p in cache_paths}
        pd.DataFrame([dict(path=p,sha256=h,scope='CURRENT_TASK_CACHE_CAPTURE_NOT_COLD_REGENERATION') for p,h in captured.items()]).to_csv(cache_receipt,index=False)
    expected.update(captured)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values=list(pool.map(sha256,expected))
    rows=[dict(path=p,expected_sha256=h,actual_sha256=a,status='PASS' if h==a else 'FAIL') for (p,h),a in zip(expected.items(),values)]
    pd.DataFrame(rows).to_csv(OUT/'final_input_hash_verification.csv',index=False)
    if any(r['status']!='PASS' for r in rows):raise ValueError('input hash drift')
    manifest=json.loads((HERE/'input_manifest.json').read_text())
    current=frozen_hashes()
    expected_frozen=manifest['implementation_hashes']
    f=[dict(path=p,expected_sha256=h,actual_sha256=current.get(p),status='PASS' if current.get(p)==h else 'FAIL') for p,h in expected_frozen.items()]
    pd.DataFrame(f).to_csv(OUT/'final_frozen_hash_verification.csv',index=False)
    if any(r['status']!='PASS' for r in f):raise ValueError('frozen economic source changed')
    policy=HERE/'contracts/shared_capital_policy_v1.json'
    expected_policy=json.loads((HERE/'contracts/initial_state_v05.json').read_text())['original_policy_sha256']
    if sha256(policy)!=expected_policy:raise ValueError('frozen capital policy changed')
    return len(rows),len(f)


def states():
    table=pd.read_csv(OUT/'native_segment_initial_states.csv')
    for i,row in table.iterrows():
        p=HERE/row.state_file;state=json.loads(p.read_text())
        if state_hash({k:v for k,v in state.items() if k!='state_hash'})!=state['state_hash']:raise ValueError('initial state hash drift')
        if state['validation_status']!='VALIDATED':
            state['validation_status']='ENGINEERING_INCOMPLETE_RAW_CONTINUOUS_STATE'
            state['official_execution_dates']='RECOVERED; see corporate_action_official_backfill_facts.csv'
            state['native_blocker']=state.get('native_blocker',state['reason'])
            state['reason']='Official listing/payment dates recovered; raw continuous account and native exit coordinate mapping not integrated. '+state['native_blocker']
            state['state_hash']=state_hash({k:v for k,v in state.items() if k!='state_hash'})
            p.write_text(json.dumps(state,indent=2,sort_keys=True)+'\n')
            table.loc[i,'validation_status']=state['validation_status'];table.loc[i,'reason']=state['reason'];table.loc[i,'state_hash']=state['state_hash']
        for key,value in dict(positions=state['positions'],tradable_quantity=state['tradable_quantity'],pending_quantity=state['pending_entitlement']).items():
            if key not in table:table[key]=pd.Series(dtype=object)
            table.loc[i,key]=json.dumps(value,sort_keys=True)
        table.loc[i,'cooldown_state_hash']=state_hash(state['cooldown_state'])
        table.loc[i,'strategy_state_hash']=state['state_hash']
        table.loc[i,'source']=row.state_file
        table.loc[i,'route_if_needed']='NATIVE_ROUTE_STATE_IN_JSON'
    table.to_csv(OUT/'native_segment_initial_states.csv',index=False)


def main():
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    if ROOT!=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1') or branch!='research/five-strategy-shared-capital-v1':raise ValueError('environment mismatch')
    subprocess.run(['git','merge-base','--is-ancestor',START,'HEAD'],cwd=ROOT,check=True)
    universe.run();universe.verify()
    print('Verify full registered inputs and all official documents',flush=True)
    n,f=hashes()
    ca_execution_audit.run();ca_final_facts.run();states();common_p0_v06.run()
    # Regenerate twice and compare deterministic compact facts/position probes.
    files=['corporate_action_official_backfill_facts.csv','official_ca_position_probes.csv','native_segment_initial_states.csv','p0_reconciliation.csv']
    first={x:sha256(OUT/x) for x in files}
    ca_final_facts.run();states();common_p0_v06.run()
    rows=[dict(file=x,first_sha256=h,second_sha256=sha256(OUT/x),status='PASS' if h==sha256(OUT/x) else 'FAIL') for x,h in first.items()]
    pd.DataFrame(rows).to_csv(OUT/'final_deterministic_rerun.csv',index=False)
    if any(r['status']!='PASS' for r in rows):raise ValueError('nondeterministic diagnostic rerun')
    subprocess.run([sys.executable,'-m','pytest','-q','research/shared_capital_v1/tests','tests/unit','--junitxml='+str(OUT/'focused_tests_final_v1.xml')],cwd=ROOT,check=True)
    suite=ET.parse(OUT/'focused_tests_final_v1.xml').getroot();tests=sum(int(x.get('tests','0')) for x in suite.findall('.//testsuite'))
    baseline=pd.read_csv(OUT/'baseline_integrity_status.csv')
    for i,row in baseline.iterrows():
        if row.strategy in ('ATRDR','MCB'):
            baseline.loc[i,'status']='ENGINEERING_INCOMPLETE_RAW_CONTINUOUS_STATE'
            baseline.loc[i,'reason']='Official execution dates recovered; continuous raw quantity/cash/native-exit mapping still unimplemented'
    baseline.to_csv(OUT/'baseline_integrity_status.csv',index=False)
    status=dict(ENVIRONMENT_VALID=True,BRANCH=branch,START_HEAD=START,TASK_STATUS='PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE',
        FROZEN_STRATEGIES_MODIFIED='NO',NEW_SEALED_VALIDATION_OPENED='NO',EXIT_RULES_USED='NATIVE_ONLY',
        STRATEGY_UNIVERSE_STATUS='FROZEN_REGISTERED_SCOPE_TESTED',OFFICIAL_BACKFILL_DOCUMENTS=16,
        CA_600622_STATUS='OFFICIAL_DATES_VERIFIED_ISOLATED_TIMELINE_PASS_CONTINUOUS_INTEGRATION_PENDING',
        CA_603368_STATUS='OFFICIAL_DATES_VERIFIED_ISOLATED_TIMELINE_PASS_CONTINUOUS_INTEGRATION_PENDING',
        CORPORATE_ACTION_EVENTS_AUDITED=len(pd.read_csv(OUT/'corporate_action_execution_completeness.csv')),
        CORPORATE_ACTION_EVENTS_UNRESOLVED=int(pd.read_csv(OUT/'corporate_action_execution_completeness.csv').status.ne('PASS').sum()),
        CORPORATE_ACTION_COMPLETENESS='PARTIAL_VERIFIED_PREFIX_ONLY; full held population not yet known',
        COMMON_SCHEDULER_STATUS='STREAMS_EXIST_FULL_PHASE_INTEGRATION_INCOMPLETE',
        PHYSICAL_VIRTUAL_ACCOUNT_STATUS='ISOLATED_TESTS_PASS_FULL_CONTINUOUS_COMMON_ACCOUNT_NOT_RUN',
        P0_STATUS='BLOCKED',SCENARIOS_COMPLETED='0/48',tests_passed=tests,tests_failed=0,
        input_hashes_verified=n,frozen_hashes_verified=f,
        MCB_CAPITAL_ROLE='EVIDENCE_INSUFFICIENT',GAP_FAMILY_CHOICE='GAP_CAPITAL_VALUE_INSUFFICIENT',BEST_ADMISSIBLE_POLICY='EVIDENCE_INSUFFICIENT',
        MAX_DRAWDOWN_CONSTRAINT_STATUS='NOT_ESTIMABLE',
        remaining_engineering=['Full continuous raw stock account and action feedback; all actual-held actions after first blocker',
            'Causal native exits through changed coordinate lineage without modifying signal-space source',
            'SMV6 full cross-sleeve exits/entries with native sequential resize feedback',
            'Four formal P0 multi-layer reconciliation and historical prefix invariance',
            'Shared scenario scheduler/48 runs/metrics and final capital decision'])
    (OUT/'task_status_final_v1.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    manifest=json.loads((HERE/'input_manifest.json').read_text())
    manifest.update(current_run_head=START,evidence_stage='FINAL_V1_OFFICIAL_DATE_RECOVERY_ENGINEERING_PARTIAL',
        all_consumed_inputs_hash_verified=True,consumed_input_count=n,consumed_input_hash_evidence='output/final_input_hash_verification.csv',
        strategy_universe_contract='contracts/strategy_universe_v1.json',strategy_universe_sha256=sha256(universe.CONTRACT),
        official_ca_backfill='manifests/corporate_action_official_backfill_v1.json',official_ca_backfill_sha256=sha256(HERE/'manifests/corporate_action_official_backfill_v1.json'),
        common_p0_reconciled=False,baseline_completion_gates='output/task_status_final_v1.json')
    (HERE/'input_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    print(json.dumps(status,ensure_ascii=False,indent=2),flush=True)
    return 2

if __name__=='__main__':raise SystemExit(main())
