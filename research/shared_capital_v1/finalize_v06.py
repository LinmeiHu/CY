"""Compact gate matrix and artifact integrity, without account simulation."""
import json
import subprocess
from pathlib import Path
import duckdb
import pandas as pd
from research.shared_capital_v1.run_shared_capital_v1 import HERE, ROOT, sha256


def run():
    out=HERE/'output'
    states=pd.read_csv(out/'native_segment_initial_states.csv')
    p0=pd.read_csv(out/'p0_reconciliation.csv')
    statuses=[
        ('600622 action state or irrelevance','FAIL_DATA_INPUT_MISSING','ca_600622_forensic.csv'),
        ('ATRDR 2018 initial state','FAIL_DATA_INPUT_MISSING','atrdr_initial_state_2018.json'),
        ('ATRDR 2022 initial state','FAIL_DATA_INPUT_MISSING','atrdr_initial_state_2022.json'),
        ('all five native initial states','FAIL',f'{int(states.validation_status.eq("VALIDATED").sum())}/10 validated'),
        ('opportunity adapters reconciled','STANDALONE_ONLY_COMMON_P0_NOT_VALIDATED','opportunity_adapter_reconciliation.csv'),
        ('common scheduler integrated','ADAPTER_STREAMS_INTEGRATED_NATIVE_BATCH_PHASE_CLOSURE_PENDING','reports/common_scheduler_accounting.md'),
        ('physical virtual common account reconciled','SYNTHETIC_AND_STANDALONE_ONLY_PRICE_UNIT_CONVERSION_PENDING','virtual_physical_reconciliation.csv'),
    ]
    for r in p0.itertuples():statuses.append((f'P0 {r.gap} {r.period}',r.status,'p0_reconciliation.csv'))
    statuses += [('prefix invariance','RAW_PARENT_AND_ACCOUNT_PROBES_PASS_FULL_CONTINUOUS_ATRDR_BLOCKED','gap_raw_prefix_v06.csv; ifcgr_prefix_v06.csv; atrdr_actual_prefix_probes.csv'),
        ('SMV6 future close perturbation','PASS','focused_tests_v06.xml'),
        ('financing/account validation','ENGINE_AND_STANDALONE_PASS_COMMON_P0_NOT_RUN','virtual_physical_reconciliation.csv'),
        ('deterministic rerun','PASS_STANDALONE_AND_REACHABLE_STATES_COMMON_P0_NOT_RUN','v06_deterministic_rerun.csv')]
    pd.DataFrame([dict(gate=i+1,requirement=name,status=status,evidence=evidence) for i,(name,status,evidence) in enumerate(statuses)]).to_csv(out/'baseline_gate_status_v06.csv',index=False)
    # The already-registered daily and rights inputs provide independent
    # downstream/schema evidence, not an invented conversion transition.
    inputs=json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs']
    hashes=pd.read_csv(out/'v06_input_hash_verification.csv').set_index('path').actual_sha256.to_dict()
    con=duckdb.connect()
    daily=con.execute("SELECT symbol,trade_date,available_at,corporate_action_count,corporate_action_valid,corporate_action_blocking,invalid_step_cum,coordinate_factor FROM read_parquet(?) WHERE symbol='600622.SH' AND trade_date BETWEEN DATE '2017-06-27' AND DATE '2017-07-03' ORDER BY trade_date",[inputs['daily_hist']]).fetchdf()
    daily['source']=inputs['daily_hist'];daily['sha256']=hashes[inputs['daily_hist']]
    daily.to_csv(out/'ca_600622_daily_lineage.csv',index=False)
    rights_count=con.execute("SELECT count(*) FROM read_parquet(?) WHERE symbol='600622' AND effective_date=DATE '2017-06-30'",[inputs['qd010_rights']]).fetchone()[0]
    title_paths=[inputs['ifcgr_sse_titles'],inputs['ifcgr_szse_titles'],
        '/Users/linmei/Documents/CY/data/staging/CY-062-V29R2-ISSUER-FACT-ROLLFORWARD-2022-2026-V1/sse_full_history_capture/announcements.parquet']
    title_rows=[]
    for source in title_paths:
        count,period_count=con.execute("SELECT count(*),count(*) FILTER(WHERE available_at BETWEEN TIMESTAMP '2017-01-01' AND TIMESTAMP '2017-12-31 23:59:59') FROM read_parquet(?) WHERE symbol LIKE '%600622%'",[source]).fetchone()
        title_rows.append(dict(source=source,sha256=hashes[source],symbol_rows=count,rows_2017=period_count,field_scope='registered title/route metadata; no share tradability field'))
    pd.DataFrame(title_rows).to_csv(out/'ca_600622_registered_title_search.csv',index=False)
    con.close()
    pd.DataFrame([dict(source=inputs['qd010_rights'],sha256=hashes[inputs['qd010_rights']],symbol='600622.SH',effective_date='2017-06-30',matching_event_count=rights_count,treatment='RIGHTS_LISTING_DATE_IS_NOT_DISTRIBUTION_SHARE_TRADABILITY')]).to_csv(out/'ca_600622_rights_search.csv',index=False)
    forensic=HERE/'reports/ca_600622_forensic.md'
    text=forensic.read_text()
    extra='\n补充核对：ca_600622_daily_lineage.csv 保存已注册历史 daily 在事件前后的状态与源哈希；ca_600622_rights_search.csv 记录同日期配股事件检索，配股上市字段不被移用于该分红转增事件。ca_600622_registered_title_search.csv 另记录三条已注册官方公告标题源中的该证券检索。\n'
    if extra not in text:forensic.write_text(text+extra)
    manifest=json.loads((HERE/'input_manifest.json').read_text())
    manifest['v06_runtime_hashes']={str(p.relative_to(ROOT)):sha256(p) for p in HERE.rglob('*.py') if 'cache' not in p.parts and not any(part.startswith('.') for part in p.relative_to(HERE).parts)}
    manifest['baseline_completion_gates']='output/baseline_gate_status_v06.csv'
    (HERE/'input_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    files=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard',str(HERE)],cwd=ROOT,text=True).splitlines()
    files=[ROOT/p for p in files if (ROOT/p).is_file() and not p.endswith('output_manifest.sha256')]
    (HERE/'output_manifest.sha256').write_text(''.join(f'{sha256(p)}  {p.relative_to(HERE)}\n' for p in sorted(set(files))))


if __name__=='__main__':run()
