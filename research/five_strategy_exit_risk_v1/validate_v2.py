"""Artifact-level checks and compact audits; uses only bounded study outputs."""
from pathlib import Path
import json
import subprocess
import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from state_v2 import HERE,ROOT,sha256,write_json,canonical_frame_hash,read_bound
from account_v2 import audit_account,nav_metrics,policy_events,replay,apply_events


def validate(config):
    ext=Path(config['external_root']);daily=pd.read_parquet(ext/'daily_relevant.parquet')
    policies=pd.read_csv(HERE/'account_effects.csv');audits=[];baseline_rows=[];funnel=[];paired_windows=[]
    cases=[(s,g,'NATIVE',f'{s}_{g}') for s in ['ATRDR','MCB','OGR','IFCGR'] for g in (['CONTINUOUS_2014_2023'] if s in ['ATRDR','MCB'] else ['2018_2021','2022_2023'])]
    cases += [('ATRDR' if r.route.startswith('ATRDR') else r.route,r.segment,r.route+':'+r.policy,f'policy_{r.route}_{r.segment}_{r.policy}') for r in policies.itertuples(index=False)]
    for strategy,segment,policy,prefix in cases:
        a=pd.read_parquet(ext/f'{prefix}_accepted.parquet');n=pd.read_parquet(ext/f'{prefix}_nav.parquet');s=pd.read_parquet(ext/f'{prefix}_skipped.parquet')
        if policy!='NATIVE':
            native=pd.read_parquet(ext/f'{strategy}_{segment}_nav.parquet')
            assert native.trade_date.tolist()==n.trade_date.tolist()
            paired_windows.append(dict(route=policy.split(':')[0],segment=segment,policy=policy.split(':')[1],dates_identical=True,
                days=len(n),start=n.trade_date.min(),end=n.trade_date.max()))
        d=daily.loc[daily.symbol.isin(a.symbol)]
        audit,ledger=audit_account(strategy,a,n,d,segment,policy)
        rejected=s.loc[s.status.ne('EXECUTED')] if strategy in ['OGR','IFCGR'] else s
        reasons=rejected['status' if strategy in ['OGR','IFCGR'] else 'skip_reason'].value_counts().to_dict()
        audit['rejected_orders_account']=len(rejected);audit['partial_fills_account']=0
        audit['rejection_reasons']=json.dumps(reasons,sort_keys=True)
        audit['account_days']=len(n);audit['daily_min_cash']=n.cash.min()
        audit['daily_max_gross_ratio']=(n.gross_exposure/n.nav).max()
        audit['daily_negative_cash_dates']=int(n.cash.lt(-1e-10).sum())
        audit['daily_exposure_violation_dates']=int(n.gross_exposure.gt(n.nav+1e-10).sum())
        audit['unvalued_event_states']=int(ledger.nav.isna().sum());audit['unvalued_account_dates']=int(n.nav.isna().sum())
        audit['units']='NORMALIZED_NAV';audit['amount_tolerance']=1e-10
        audits.append(audit)
        ledger.to_parquet(ext/f'{prefix}_audited_event_states.parquet',index=False)
        for reason,count in reasons.items():funnel.append(dict(strategy=strategy,segment=segment,policy=policy,reason=reason,count=count))
        if policy=='NATIVE':
            source=pd.read_parquet(ext/f'{prefix}_source.parquet')
            baseline_rows.append(dict(strategy=strategy,segment=segment,opportunities=len(source),accepted=len(a),skipped=len(rejected),
                                      no_entry_opportunities=int(source.entry_date.isna().sum()),**nav_metrics(n)))
    ledger=pd.read_parquet(ext/'SMV6_event_account_states.parquet');n=pd.read_parquet(ext/'SMV6_current_nav.parquet');e=pd.read_parquet(ext/'SMV6_current_events.parquet')
    audits.append(pd.DataFrame([dict(strategy='SMV6',segment='CONTINUOUS_2013_2023',policy='NATIVE',sleeve='ALL',event_states=len(ledger),
                    min_cash=ledger.cash.min(),max_gross_ratio=ledger.gross_ratio.max(),negative_cash_timestamps=int(ledger.cash.lt(-1e-8).sum()),
                    exposure_violation_timestamps=int(ledger.gross_ratio.gt(1+1e-10).sum()),violation_dates=0,borrowed_cash=0,margin=0,
                    absolute_tolerance_nav_units=np.nan,amount_tolerance=1e-8,units='CNY',ratio_tolerance=1e-10,
                    rejected_orders_account=int(e.event_type.str.contains('NO_FILL').sum()),partial_fills_account=int(e.event_type.eq('SELL_PARTIAL').sum()),
                    account_days=len(n),daily_min_cash=n.cash.min(),daily_max_gross_ratio=(n.gross_exposure/n.nav).max(),
                    daily_negative_cash_dates=int(n.cash.lt(-1e-8).sum()),daily_exposure_violation_dates=int(n.gross_exposure.gt(n.nav+1e-8).sum()),
                    unvalued_event_states=int(ledger.nav.isna().sum()),unvalued_account_dates=int(n.nav.isna().sum()),
                    execution_scope='LOCAL_CALLBACK; CNY lot100 minute-cap50% fee0.0002 spread0.0016; native equivalence unverified',
                    reservation_contract='IMMEDIATE_FILL_FEE_INCLUDED; NO_DEFERRED_BUYS')]))
    audit=pd.concat(audits,ignore_index=True);audit.to_csv(HERE/'execution_and_no_financing_audit.csv',index=False)
    pd.DataFrame(baseline_rows).to_csv(HERE/'baseline_accounts.csv',index=False);pd.DataFrame(funnel).to_csv(HERE/'order_rejection_flow.csv',index=False)
    pd.DataFrame(paired_windows).to_csv(HERE/'paired_account_windows.csv',index=False)
    for col in ['negative_cash_timestamps','exposure_violation_timestamps','daily_negative_cash_dates','daily_exposure_violation_dates']:
        assert audit[col].eq(0).all(),col
    state=pd.read_parquet(ext/'position_state_snapshots.parquet');sm=pd.read_parquet(ext/'SMV6_position_state_snapshots.parquet')
    allstate=pd.concat([state,sm],ignore_index=True);mature=allstate.loc[allstate.label_status.eq('MATURE')]
    assert mature.earliest_legal_execution_at.le(mature.native_time).all()
    assert pd.to_datetime(allstate.decision_at).dt.year.le(2023).all()
    assert allstate.loc[allstate.label_status.eq('CENSORED'),'EXIT_ADVANTAGE_NET'].isna().all()
    assert not allstate.duplicated(['episode_id','decision_at']).any()
    split=pd.read_csv(HERE/'temporal_split_audit.csv');ok=split.status.eq('PURGED_FORWARD_SPLIT')
    assert pd.to_datetime(split.loc[ok,'train_last_label']).lt(pd.to_datetime(split.loc[ok,'year'].astype(str)+'-01-01')).all()
    assert split[['episode_overlap','event_cluster_overlap']].eq(0).all().all()
    assert 'future_downside' not in __import__('state_v2').BASE+__import__('state_v2').EXTRA
    # Deterministic recomputation of a complete policy's first exits and causal account.
    t=pd.read_parquet(ext/'all_source_normalized.parquet');p=pd.read_parquet(ext/'candidate_position_paths.parquet')
    paths={k:g for k,g in p.loc[p.episode_id.str.startswith('MCB|')].groupby('episode_id',sort=False)}
    events=policy_events(t.loc[t.route.eq('MCB')],paths,'fixed',.1,active_from='2021-01-01')
    prefix='policy_MCB_CONTINUOUS_2014_2023_fixed_0.1'
    expected=pd.read_parquet(ext/f'{prefix}_events.parquet')
    event_hash=canonical_frame_hash(events);assert event_hash==canonical_frame_hash(expected)
    source=pd.read_parquet(ext/'MCB_CONTINUOUS_2014_2023_source.parquet')
    changed=apply_events(source,__import__('state_v2').normalize_stock(source,'MCB'),events,'fixed_0.1')
    a,_,n=replay('MCB',changed,daily.loc[daily.symbol.isin(changed.symbol)])
    hashes={}
    for name,frame in [('events',events),('accepted',a),('nav',n)]:
        expected=pd.read_parquet(ext/f'{prefix}_{name}.parquet')
        hashes[name]=canonical_frame_hash(frame);assert hashes[name]==canonical_frame_hash(expected),name
    manifest=json.loads((HERE/'input_and_exposure_manifest.json').read_text())
    frozen=manifest['frozen_hashes']
    assert all(sha256(ROOT/name)==value for name,value in frozen.items())
    assert not subprocess.check_output(['git','diff','--name-only','40d924ca718be40c6e891a64b3a9cac7f8d58f95','--','src','configs/frozen'],cwd=ROOT,text=True).strip()
    # The six selected-but-nonexecutable later OGR signals are known entry gates.
    where="signal_date BETWEEN DATE '2022-01-01' AND DATE '2023-12-31'"
    signal=read_bound(config['inputs']['ogr_rollforward_signals'],where,'gap_id,signal_date,entry_date,entry_status,realized_net_l_headroom')
    out=read_bound(config['inputs']['ogr_rollforward_outcomes'],where,'gap_id')
    missing=signal.loc[~signal.gap_id.isin(out.gap_id)].copy()
    assert missing.entry_status.isin(['INSUFFICIENT_L_HEADROOM','RISK_BLOCKED_ENTRY']).all()
    missing.to_csv(HERE/'ogr_entry_gate_exclusions.csv',index=False)
    b=Path(config['baseline_root']);source_funnel=[]
    for layer,name in [('MCB_signal','mcb_integrated/signals.parquet'),('MCB_trade','mcb_integrated/trades.parquet'),
                       ('OGR_signal','ogr_integrated/signals.parquet'),('OGR_entry','ogr_integrated/entries.parquet'),('IFCGR_trade','ifcgr_integrated/trades.parquet')]:
        columns=read_bound(b/name,'FALSE').columns
        used=[c for c in ['signal_date','status','entry_status'] if c in columns]
        frame=read_bound(b/name,"signal_date<=DATE '2023-12-31'",','.join(used))
        source_funnel.append(dict(layer=layer,rows=len(frame),first=str(frame.signal_date.min()),last=str(frame.signal_date.max()),
            statuses={c:frame[c].value_counts().to_dict() for c in used if c!='signal_date'},source=str(b/name)))
    write_json(HERE/'source_funnel_manifest.json',source_funnel)
    coverage=pd.read_csv(HERE/'coverage_and_exposure_manifest.csv');coverage=coverage.loc[coverage.route.ne('SMV6')]
    res=pd.read_csv(HERE/'smv6_residual_loss.csv');main=res.loc[pd.to_datetime(res.entry_date).ge('2018-01-01')]
    coverage=pd.concat([coverage,pd.DataFrame([dict(route='SMV6',candidate_rows=np.nan,funded_episodes=len(main),
           candidate_signal_start='2018-01-01',candidate_signal_end='2023-12-31',authorized_scan_start='2018-01-01',authorized_scan_end='2023-12-31',
           raw_daily_start='2013-04-01',raw_daily_end='2023-12-29',warmup='Actual callbacks initialized 2013-04-01; study entries from 2018',
           discovery_end='2021-12-31',evaluation_start='2022-01-01',evidence='CONSUMED_HISTORY_TEMPORAL_CHECK',
           position_days=int(pd.to_datetime(sm.entry_date).ge('2018-01-01').sum()),independent_signal_dates=main.entry_date.nunique(),
           censored_states=int(sm.label_status.eq('CENSORED').sum()),account_construction='Continuous actual local callback; full-history 84 episodes; later windows carry prior account cash',
           minute_coverage='Frozen per-security open/final/decision availability and 50% minute volume',
           source='All frozen ETF callbacks replayed, candidate generation uses current account state')])],ignore_index=True)
    coverage.to_csv(HERE/'coverage_and_exposure_manifest.csv',index=False)
    schemas=[]
    for file in sorted(ext.glob('*.parquet')):
        meta=pq.ParquetFile(file)
        schemas.append(dict(file=file.name,rows=meta.metadata.num_rows,schema=str(meta.schema_arrow)))
    write_json(HERE/'external_artifact_schemas.json',schemas)
    manifest['artifacts']={p.name:dict(bytes=p.stat().st_size,sha256=sha256(p)) for p in sorted(ext.glob('*.parquet'))}
    manifest['unused_registered_inputs_in_v2']=[k for k in config['inputs'] if k not in ['daily_hist','raw_minute_root','smv6_qmt_root','smv6_hybrid_root','ogr_rollforward_signals','ogr_rollforward_outcomes','ifcgr_cy065_trades']]
    manifest['not_a_full_raw_scanner_rerun']='Stock opportunity streams are source-found frozen producer intermediates; current account and Fast capacity regenerated. No inference of yearly zero signals from accepted ledger.'
    write_json(HERE/'input_and_exposure_manifest.json',manifest)
    write_json(HERE/'verification_results.json',dict(
        research_checks='PASS',no_financing='CASH_PASS; EXPOSURE_PASS_WHERE_VALUED; SMV6_FULL_HISTORY_TWO_UNVALUED_DAYS',
        production_prefix_invariance='FAIL_ATRDR_BULL_SLOW_COMPLETION_GATE',research_feature_action_prefix='PASS_UNIT_COUNTEREXAMPLES',
        temporal_split='PASS_AFTER_DISCOVERY_MATURITY_BOUNDARY_FIX',states=len(allstate),censored_states=int(allstate.label_status.eq('CENSORED').sum()),
        identical_paired_account_windows=len(paired_windows),
        maturity_boundary_excluded_states=int(split.discovery_boundary_excluded_states.sum()),
        frozen_rules_unchanged=True,frozen_file_count=len(frozen),same_input_determinism_hashes=hashes,
        maximum_independent_account_residual=float(policies.decomposition_residual.abs().max()),
        smv6_exit_after_native_states=int(sm.earliest_legal_execution_at.gt(sm.native_time).sum()),
        runtime=dict(python=sys.version,numpy=np.__version__,pandas=pd.__version__,duckdb=__import__('duckdb').__version__,sklearn=__import__('sklearn').__version__),
        candidate_min_cash_by_units=audit.groupby('units').min_cash.min().to_dict(),
        caveat='Audit proves declared local models; normalized stock fills do not prove broker integer lots or auction depth. A test proving a known production defect does not make its invariant pass.'))
    print('V2 artifact verification complete; ATRDR production prefix failure remains quarantined.',flush=True)


if __name__=='__main__':
    validate(json.loads((HERE/'input_config.json').read_text()))
