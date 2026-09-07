"""Reproduce V2 in this existing research directory. Large artifacts stay external."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
import time
import numpy as np
import pandas as pd

import state_v2 as st
from state_v2 import HERE, ROOT, END, write_json, sha256, canonical_frame_hash
from account_v2 import replay, audit_account, policy_events, event_summary, apply_events, nav_metrics


def log(message):
    print(datetime.now().isoformat(timespec='seconds'),message,flush=True)


def registry(experiment, stage, route, spec, status, artifact):
    import csv
    with (HERE/'experiment_registry.csv').open('a',newline='') as f:
        csv.writer(f,lineterminator='\n').writerow([experiment,stage,route,spec,'2023-12-31',status,artifact])


def checkpoint(stage, message, command):
    (HERE/'RUN_STATE.md').write_text(f'# RUN_STATE\n\nRun: 20260907_v2_01\nStage: {stage}\nUpdated: {datetime.now().astimezone().isoformat()}\n\n{message}\n\nActual command: `{command}`\nNext: continue registered stages with run_v2.py.\nFrozen production files are read-only to this study.\n')


def prepare(config):
    ext=Path(config['external_root'])
    if str(ext).startswith('/Volumes/'):
        mount=Path(*ext.parts[:3])
        if not mount.is_mount():raise RuntimeError(f'External volume is not mounted: {mount}')
    ext.mkdir(parents=True,exist_ok=True)
    src=st.load_sources(config)
    log('load bounded daily cache')
    daily=st.daily_cache(config,src)
    fast=pd.read_parquet(ext/'fast_corrected.parquet') if (ext/'fast_corrected.parquet').exists() else st.build_atr_sources(src,daily,ext)
    market=st.read_bound(Path(config['baseline_root'])/'atrdr_full_closed_20260907/atrdr/market_state.parquet',"trade_date <= DATE '2023-12-31'")
    src['ATRDR']=st.route_union(src,fast,market,ext)
    src['MCB']=src['MCB'].merge(src['mcb_signals'][['event_id','coord_low','feature_latest_timestamp']].rename(columns={'coord_low':'anchor','feature_latest_timestamp':'anchor_available_at'}),on='event_id',validate='one_to_one')
    normalized=[]; audits=[]; ledgers=[]; baseline_summary=[]
    for strategy in ['ATRDR','MCB','OGR','IFCGR']:
        source=src[strategy]
        segments=['CONTINUOUS_2014_2023'] if strategy in ['ATRDR','MCB'] else ['2018_2021','2022_2023']
        for segment in segments:
            t=source if len(segments)==1 else source.loc[source.segment.eq(segment)].copy()
            d=daily.loc[daily.symbol.isin(t.symbol.unique())]
            log(f'baseline replay {strategy} {segment}: {len(t)} opportunities')
            a,s,n=replay(strategy,t,d,segment)
            key=f'{strategy}_{segment}'
            for label,frame in [('source',t),('accepted',a),('skipped',s),('nav',n)]:frame.to_parquet(ext/f'{key}_{label}.parquet',index=False)
            audit,ledger=audit_account(strategy,a,n,d,segment,'NATIVE');audits.append(audit);ledgers.append(ledger)
            skipped=int(s.status.ne('EXECUTED').sum()) if strategy in ['OGR','IFCGR'] else len(s)
            baseline_summary.append(dict(strategy=strategy,segment=segment,opportunities=len(t),accepted=len(a),skipped=skipped,**nav_metrics(n)))
            normalized_t=st.normalize_stock(t,None if strategy=='ATRDR' else strategy)
            norm_a=st.normalize_stock(a,None if strategy=='ATRDR' else strategy)
            norm_a=norm_a.set_index('episode_id')
            normalized_t['qty']=normalized_t.episode_id.map(norm_a.qty)
            normalized_t['entry_outlay']=normalized_t.episode_id.map(norm_a.entry_outlay)
            normalized.append(normalized_t)
            log(f'{key} accepted={len(a)} NAV={n.nav.iloc[-1]:.8f}')
    alltrades=pd.concat(normalized,ignore_index=True)
    alltrades.to_parquet(ext/'all_source_normalized.parquet',index=False)
    pd.concat(audits).to_csv(HERE/'execution_and_no_financing_audit.csv',index=False)
    pd.concat(ledgers).to_parquet(ext/'baseline_event_account_states.parquet',index=False)
    pd.DataFrame(baseline_summary).to_csv(HERE/'baseline_accounts.csv',index=False)
    # Exact existing source bug materiality, without changing production.
    retained=st.route_union(src,fast,market,ext,retain_entered=True)
    excluded=retained.loc[~retained.event_id.isin(src['ATRDR'].event_id)].copy()
    excluded.to_csv(HERE/'production_excluded_entered.csv',index=False)
    retained.to_parquet(ext/'ATRDR_ENTERED_RETAINED_DIAGNOSTIC_source.parquet',index=False)
    if len(excluded):
        log(f'production route completion filter drops {len(excluded)} entered events; impact replay quarantined')
        a,s,n=replay('ATRDR',retained,daily.loc[daily.symbol.isin(retained.symbol.unique())])
        a.to_parquet(ext/'ATRDR_ENTERED_RETAINED_DIAGNOSTIC_accepted.parquet',index=False)
        n.to_parquet(ext/'ATRDR_ENTERED_RETAINED_DIAGNOSTIC_nav.parquet',index=False)
        write_json(HERE/'production_bug_impact.json',dict(status='CONFIRMED_SOURCE_PREFIX_FAILURE',
                  excluded_entered=len(excluded),by_route=excluded.route.value_counts().to_dict(),
                  research_retention_adapter_accepted=len(a),research_retention_adapter_metrics=nav_metrics(n),
                  caveat='Retained positions with unavailable legal outcome are still censored. Diagnostic NAV has inherited coordinate marks; not a newly sealed baseline. All ATRDR account policy conclusions quarantined.'))
    finalize_paths(config, alltrades, daily)


def paths(config):
    ext=Path(config['external_root'])
    finalize_paths(config,pd.read_parquet(ext/'all_source_normalized.parquet'),pd.read_parquet(ext/'daily_relevant.parquet'))


def finalize_paths(config,alltrades,daily):
    ext=Path(config['external_root'])
    log('generate funded state snapshots and complete opportunity paths')
    states,losses,paths=st.snapshots(alltrades,daily,ext)
    # Compact complete paths, not a separate platform or accepted-only future flow.
    frames=[p.assign(episode_id=k) for k,p in paths.items()]
    pd.concat(frames,ignore_index=True).to_parquet(ext/'candidate_position_paths.parquet',index=False)
    log(f'states={len(states)}, funded episodes={len(losses)}, all paths={len(paths)}')
    losses.to_csv(HERE/'loss_anatomy.csv',index=False)
    coverage=[]
    contract=json.loads((HERE/'research_contract.json').read_text())
    for route,t in alltrades.groupby('route'):
        x=states.loc[states.route.eq(route)]
        split=contract['splits'][route]
        coverage.append(dict(route=route,candidate_rows=len(t),funded_episodes=int(t.qty.notna().sum()),
                             candidate_signal_start=t.signal_date.min(),candidate_signal_end=t.signal_date.max(),
                             authorized_scan_start=split[0],authorized_scan_end=split[3],
                             raw_daily_start=daily.trade_date.min(),raw_daily_end=daily.trade_date.max(),warmup='2013 raw history, producer-specific completed prior windows',
                             discovery_end=split[1],evaluation_start=split[2],evidence='CONSUMED_HISTORY_TEMPORAL_CHECK',
                             position_days=len(x),independent_signal_dates=t.loc[t.qty.notna(),'signal_date'].nunique(),
                             censored_states=int(x.label_status.eq('CENSORED').sum()),
                             account_construction='Two independent resets, not concatenated NAV' if route in ['OGR','IFCGR'] else 'Continuous normalized account; ATRDR completion-filter defect quarantined',
                             minute_coverage='Native OGR order timestamps; new daily next-open simulated capacity unknown',
                             source='Frozen same-version producers and registered selected opportunity outputs; no ledger-derived scan assertion'))
    pd.DataFrame(coverage).to_csv(HERE/'coverage_and_exposure_manifest.csv',index=False)
    frozen={str(p.relative_to(ROOT)):sha256(p) for directory in ['configs/frozen','src/five_strategy_bundle'] for p in sorted((ROOT/directory).rglob('*')) if p.is_file() and '__pycache__' not in str(p)}
    files=[p for p in ext.glob('*.parquet')]
    write_json(HERE/'input_and_exposure_manifest.json',dict(run_id=config['run_id'],baseline_head='40d924ca718be40c6e891a64b3a9cac7f8d58f95',
               registered_inputs=config['inputs'],read_cutoff='2023-12-31',atrdr_identity='V29 actual Bull + V27 Bear subroutes + V29 shared router; no post-2023 V27 account',
               evidence='CONSUMED_HISTORY_TEMPORAL_CHECK',production_bug='production_bug_impact.json',
               frozen_hashes=frozen,external_root=str(ext),artifacts={p.name:{'sha256':sha256(p),'bytes':p.stat().st_size} for p in files},
               prior_exposure='takeover_inventory.json',new_sealed_validation_opened=False))
    registry('V2_PREPARE','PATH','ALL','Current production replay + full-source path + state snapshots','COMPUTED','input_and_exposure_manifest.json')
    checkpoint('PATH_COMPLETE','Actual source/account/path outputs saved and hashed; ATRDR completion-filter bug isolated.',' '.join(sys.argv))


def simple(config):
    ext=Path(config['external_root']);t=pd.read_parquet(ext/'all_source_normalized.parquet')
    p=pd.read_parquet(ext/'candidate_position_paths.parquet');paths={k:g for k,g in p.groupby('episode_id',sort=False)}
    contract=json.loads((HERE/'research_contract.json').read_text());rows=[];selections=[]
    for route in ['ATRDR_BULL','ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','MCB','OGR']:
        source=t.loc[t.route.eq(route)];split=contract['splits'][route]
        specs=[('native',0)]+[('fixed',v) for v in contract['budgets']['fixed']]+[('atr',v) for v in contract['budgets']['atr']]
        if route in ['ATRDR_BULL','MCB','OGR']:specs += [('time',v) for v in [3,5,8]]
        # H1/H2 action descriptions are preregistered; their account admission is gated by information tests.
        specs += [('H1',2),('H2',0)]
        for family,value in specs:
            policy=f'{family}_{value:g}'
            registry(f'{route}_{policy}','EVENT',route,policy,'RUNNING','')
            e=policy_events(source,paths,family,value)
            e.to_parquet(ext/f'events_{route}_{policy}.parquet',index=False)
            e=e.loc[e.qty.notna()]
            for period,start,end in [('DISCOVERY',split[0],split[1]),('EVALUATION',split[2],split[3])]:
                cohort=e.loc[pd.to_datetime(e.entry_date).between(start,end)]
                boundary_excluded=0
                if period=='DISCOVERY':
                    usable=pd.to_datetime(cohort.native_time).lt(pd.Timestamp(split[2]))
                    boundary_excluded=int((~usable).sum());cohort=cohort.loc[usable]
                rows.append(dict(route=route,policy=policy,family=family,value=value,period=period,start=start,end=end,selection_boundary_excluded=boundary_excluded,**event_summary(cohort)))
            registry(f'{route}_{policy}','EVENT',route,policy,'COMPUTED',f'events_{route}_{policy}.parquet')
        r=pd.DataFrame(rows);r=r.loc[r.route.eq(route)&r.period.eq('DISCOVERY')]
        choice=None;region=[]
        for family,minlength in [('fixed',3),('atr',2)]:
            ordered=r.loc[r.family.eq(family)].sort_values('value')
            groups=[];active=[]
            for x in ordered.itertuples(index=False):
                if x.mean_advantage>0 and x.policy_tail>=x.native_tail:active.append(x)
                else:
                    if active:groups.append(active)
                    active=[]
            if active:groups.append(active)
            groups=[g for g in groups if len(g)>=minlength]
            if groups:
                group=max(groups,key=len);choice=group[(len(group)-1)//2];region=[x.value for x in group];break
        selections.append(dict(route=route,policy=choice.policy if choice else 'fixed_0.1',
                               family=choice.family if choice else 'fixed',value=choice.value if choice else .1,
                               stable_region=json.dumps(region),selection_status='STABLE_DISCOVERY_REGION' if choice else 'NO_STABLE_SIMPLE_STOP_DIAGNOSTIC_10PCT_ONLY',
                               selection_visibility_end=split[1]))
        log(f'{route}: simple representative {selections[-1]}')
    pd.DataFrame(rows).to_csv(HERE/'simple_exit_response.csv',index=False)
    pd.DataFrame(selections).to_csv(HERE/'simple_selection.csv',index=False)
    # One inherited, previously registered profit-protection family. No grid.
    profit=[]
    for route in [contract['profit_protection_activation']['route']]:
        split=contract['splits'][route]
        e=policy_events(t.loc[t.route.eq(route)],paths,'profit',0)
        e.to_parquet(ext/f'events_{route}_profit_0.parquet',index=False)
        for period,start,end in [('DISCOVERY',split[0],split[1]),('EVALUATION',split[2],split[3])]:
            cohort=e.loc[e.qty.notna()&pd.to_datetime(e.entry_date).between(start,end)]
            if period=='DISCOVERY':cohort=cohort.loc[pd.to_datetime(cohort.native_time).lt(pd.Timestamp(split[2]))]
            profit.append(dict(route=route,policy='profit_0',period=period,**event_summary(cohort)))
        registry(f'{route}_profit_0','EVENT',route,'Inherited single MFE5/close<=0 family; no tuning','COMPUTED',f'events_{route}_profit_0.parquet')
    pd.DataFrame(profit).to_csv(HERE/'profit_protection_response.csv',index=False)
    checkpoint('SIMPLE_COMPLETE','Fixed/ATR/time and two preregistered mechanisms event responses computed. Account candidates still gated by information evidence.',' '.join(sys.argv))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=HERE/'input_config.json');parser.add_argument('--stage',choices=['prepare','paths','simple','smv6','information','accounts'],required=True)
    args=parser.parse_args();config=json.loads(args.config.read_text());globals()[args.stage](config)


def smv6(config):
    from smv6_v2 import run
    state=run(config);log(f'SMV6 callback residual and state values: {len(state)} states')
    registry('SMV6_RESIDUAL','INFORMATION','SMV6','Frozen callbacks, rebalance-aware residual, same original inventory payoff','COMPUTED','smv6_execution_summary.json')


def information(config):
    from information_v2 import probe
    ext=Path(config['external_root'])
    states=pd.concat([pd.read_parquet(ext/'position_state_snapshots.parquet'),pd.read_parquet(ext/'SMV6_position_state_snapshots.parquet')],ignore_index=True)
    result=probe(states,config);log(f'Information comparisons: {len(result)} rows')
    registry('V2_INFORMATION','INFORMATION','ALL','Purged annual expanding probes; preregistered feature groups','COMPUTED','incremental_information.csv')
    checkpoint('INFORMATION_COMPLETE','All eligible route probes evaluated with train-only preprocessing and event weights.',' '.join(sys.argv))


def accounts(config):
    ext=Path(config['external_root']);contract=json.loads((HERE/'research_contract.json').read_text())
    daily=pd.read_parquet(ext/'daily_relevant.parquet');t=pd.read_parquet(ext/'all_source_normalized.parquet')
    pathframe=pd.read_parquet(ext/'candidate_position_paths.parquet');paths={k:g for k,g in pathframe.groupby('episode_id',sort=False)}
    information=pd.read_csv(HERE/'incremental_information.csv');selections=pd.read_csv(HERE/'simple_selection.csv')
    audit=pd.read_csv(HERE/'execution_and_no_financing_audit.csv');audit=audit.loc[audit.policy.eq('NATIVE')]
    policyrows=[];effectrows=[];funnel=[];temporal=[];admission=[]
    fast_context=None
    for route in ['ATRDR_BULL','ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','MCB','OGR','IFCGR']:
        strategy='ATRDR' if route.startswith('ATRDR') else route
        split=contract['splits'][route]
        representative=selections.loc[selections.route.eq('OGR' if route=='IFCGR' else route)].iloc[0]
        specs=[(representative.family,float(representative.value))]
        info=information.loc[information.route.eq(route)&information.model.eq('B1')&information.phase.eq('DISCOVERY_FORWARD')]
        admitted=bool(len(info) and info.mse_improvement_over_b0.mean()>0 and info.top_mean_realized.mean()>0 and info.top_events.sum()>=20 and info.top_signal_dates.sum()>=5)
        if admitted:specs += [('H1',2),('H2',0)]
        if route==contract['profit_protection_activation']['route']:
            specs += [('profit',0)]  # single registered family; evaluate its tail/return tradeoff in real cash
        admission.append(dict(route=route,mechanism_account_admitted=admitted,reason='Predeclared discovery B1 gate; no evaluation parameter selection',
                              top_events=info.top_events.sum(),top_dates=info.top_signal_dates.sum()))
        segments=['CONTINUOUS_2014_2023'] if strategy in ['ATRDR','MCB'] else ['2018_2021','2022_2023']
        for family,value in specs:
            policy=f'{family}_{value:g}'
            for segment in segments:
                key=f'{strategy}_{segment}'
                source=pd.read_parquet(ext/f'{key}_source.parquet')
                base_a=pd.read_parquet(ext/f'{key}_accepted.parquet');base_n=pd.read_parquet(ext/f'{key}_nav.parquet')
                norm=st.normalize_stock(source,None if strategy=='ATRDR' else strategy)
                funded=t.loc[t.route.eq(route)&t.segment.eq(segment)]
                # Final forward policy begins at the registered evaluation boundary. For OGR discovery
                # reset, run the same frozen representative solely as a labelled discovery account.
                active_from=split[0] if segment=='2018_2021' else split[2]
                e=policy_events(funded,paths,family,value,active_from=active_from)
                if route=='ATRDR_FAST_BEAR':
                    if fast_context is None:
                        src=st.load_sources(config);fast=pd.read_parquet(ext/'fast_corrected.parquet')
                        f=fast.merge(src['fast_signal'][['event_id','coord_low','signal_decision_at','market_median_ret20','market_median_ret60']],on='event_id',validate='one_to_one')
                        f=f.rename(columns={'coord_low':'anchor','signal_decision_at_y':'anchor_available_at'})
                        if 'anchor_available_at' not in f: f['anchor_available_at']=f['signal_decision_at']
                        fn=st.normalize_stock(f,'ATRDR_FAST_BEAR');fn['qty']=np.nan
                        scratch=ext/'fast_upstream';scratch.mkdir(exist_ok=True)
                        _,_,fp=st.snapshots(fn,daily,scratch)
                        market=st.read_bound(Path(config['baseline_root'])/'atrdr_full_closed_20260907/atrdr/market_state.parquet',"trade_date<=DATE '2023-12-31'")
                        fast_context=(src,fast,fn,fp,market,scratch)
                    src,fast,fn,fp,market,scratch=fast_context
                    target=fn.loc[fn.market_median_ret20.lt(fn.market_median_ret60)]
                    upstream_e=policy_events(target,fp,family,value,active_from=active_from)
                    changed_fast=apply_events(fast,fn,upstream_e,policy)
                    changed=st.route_union(src,changed_fast,market,scratch)
                    upstream_e.to_parquet(ext/f'upstream_fast_{policy}.parquet',index=False)
                else:
                    changed=apply_events(source,norm,e,policy)
                log(f'account {route} {segment} {policy}; {int(e.filled.sum())} source exits')
                d=daily.loc[daily.symbol.isin(changed.symbol.unique())]
                a,s,n=replay(strategy,changed,d,segment)
                label=f'{route}_{segment}_{policy}'
                a.to_parquet(ext/f'policy_{label}_accepted.parquet',index=False);n.to_parquet(ext/f'policy_{label}_nav.parquet',index=False)
                s.to_parquet(ext/f'policy_{label}_skipped.parquet',index=False)
                e.to_parquet(ext/f'policy_{label}_events.parquet',index=False)
                au,ledger=audit_account(strategy,a,n,d,segment,f'{route}:{policy}');audit=pd.concat([audit,au],ignore_index=True)
                ledger.to_parquet(ext/f'policy_{label}_event_states.parquet',index=False)
                event_key='gap_id' if strategy in ['OGR','IFCGR'] else 'event_id'
                base_ids=set(base_a[event_key]);new_ids=set(a[event_key]);shared=base_ids&new_ids
                base_q=base_a.set_index(event_key).qty;new_q=a.set_index(event_key).qty
                new_ids_only=new_ids-base_ids;cancelled=base_ids-new_ids
                qtychanged=int(sum(abs(float(new_q.loc[k])-float(base_q.loc[k]))>1e-12 for k in shared))
                for period,start,end in [('DISCOVERY',split[0],split[1]),('EVALUATION',split[2],split[3])]:
                    bm=nav_metrics(base_n,start,end);pm=nav_metrics(n,start,end)
                    if not bm or not pm:continue
                    cohort=e.loc[e.qty.notna()&pd.to_datetime(e.entry_date).between(start,end)]
                    policyrows.append(dict(route=route,segment=segment,policy=policy,period=period,
                                           account_status='QUARANTINED_PRODUCTION_PREFIX_DEFECT' if strategy=='ATRDR' else 'FROZEN_EXECUTION_MODEL_SIMULATION',
                                           **event_summary(cohort),**{'baseline_'+k:v for k,v in bm.items()},**pm))
                fixed_original=e.loc[e.qty.notna(),'advantage_amount'].sum(min_count=1)
                navdelta=float(n.nav.iloc[-1]-base_n.nav.iloc[-1])
                from account_v2 import accounting_decomposition
                parts=accounting_decomposition(strategy,base_a,a,d,n.trade_date.max(),navdelta)
                effectrows.append(dict(route=route,segment=segment,policy=policy,original_fixed_quantity_exit_delta=fixed_original,
                                       total_account_nav_delta=navdelta,quantity_compounding_funded_set_interaction=navdelta-fixed_original,
                                       **parts,
                                       newly_funded=len(new_ids_only),cancelled=len(cancelled),quantity_changed=qtychanged,
                                       base_accepted=len(base_a),policy_accepted=len(a),
                                       interpretation='Residual contains compounding, quantity and path interactions; not pure capital release',units='NORMALIZED_COMBINED_NAV'))
                for k in sorted(new_ids_only):funnel.append(dict(route=route,segment=segment,policy=policy,event_id=k,change='NEWLY_FUNDED'))
                for k in sorted(cancelled):funnel.append(dict(route=route,segment=segment,policy=policy,event_id=k,change='CANCELLED'))
                # Frozen policy stress: one cost and one delayed execution scenario, same cohort and clock.
                for stress,delay,cost in [('EXTRA_EXIT_10BP',0,.001),('DELAY_ONE_SESSION',1,0)]:
                    stress_e=policy_events(funded,paths,family,value,active_from=active_from,delay=delay,extra_cost=cost)
                    stress_e=stress_e.loc[stress_e.qty.notna()&pd.to_datetime(stress_e.entry_date).ge(split[2])]
                    temporal.append(dict(route=route,segment=segment,policy=policy,test=stress,**event_summary(stress_e)))
                late=e.loc[e.qty.notna()&pd.to_datetime(e.entry_date).ge(split[2])]
                for year,g in late.groupby(pd.to_datetime(late.entry_date).dt.year):
                    temporal.append(dict(route=route,segment=segment,policy=policy,test=f'YEAR_{year}',**event_summary(g)))
                gains=late.groupby(pd.to_datetime(late.decision_at).dt.normalize()).advantage_amount.sum().sort_values(ascending=False)
                for remove in [1,5]:
                    remaining=float(late.advantage_amount.sum()-gains.head(remove).sum())
                    temporal.append(dict(route=route,segment=segment,policy=policy,test=f'REMOVE_BEST_{remove}_TRIGGER_DATES',n=len(late),remaining_advantage_amount=remaining,independent_trigger_dates=len(gains)))
                registry(label,'ACCOUNT',route,'Full source regeneration, legal-time cash; evaluation-frozen rules','COMPUTED',f'policy_{label}_nav.parquet')
    pd.DataFrame(admission).to_csv(HERE/'mechanism_admission.csv',index=False)
    pd.DataFrame(policyrows).to_csv(HERE/'policy_comparison.csv',index=False)
    pd.DataFrame(effectrows).to_csv(HERE/'account_effects.csv',index=False)
    pd.DataFrame(funnel).to_csv(HERE/'funded_flow_changes.csv',index=False)
    pd.DataFrame(temporal).to_csv(HERE/'temporal_robustness.csv',index=False)
    audit.to_csv(HERE/'execution_and_no_financing_audit.csv',index=False)
    checkpoint('ACCOUNTS_COMPLETE','Frozen simple diagnostics and admitted Fast Bear mechanisms replayed from full opportunities, with event cash reconciliation.',' '.join(sys.argv))


if __name__=='__main__':main()
