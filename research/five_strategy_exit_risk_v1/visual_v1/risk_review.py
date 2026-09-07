"""User-directed risk-first comparison using the existing complete cash engines.

This is a consumed-history preference review, separate from the frozen visual test.
No changes to production, entries, weights, frozen policies, or parent artifacts.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path.insert(0, str(PARENT))
import state_v2 as st
from account_v2 import (replay, apply_events, policy_events, nav_metrics,
                        audit_account, accounting_decomposition)

CONFIG = json.loads((PARENT/'input_config.json').read_text())
OLD = Path(CONFIG['external_root'])
OUT = OLD.parent/'20260907_visual_v1_01'/'risk_preference_review'
CONTRACT = json.loads((PARENT/'research_contract.json').read_text())
EVIDENCE = 'USER_PREFERENCE_UPDATE_AFTER_RESULT_EXPOSURE'


def log(message):
    print(datetime.now().astimezone().isoformat(timespec='seconds'), message, flush=True)
    with (HERE/'risk_stage_audit.jsonl').open('a') as f:
        f.write(json.dumps(dict(time=datetime.now().astimezone().isoformat(),action=message))+'\n')


def select():
    d = pd.read_csv(HERE/'risk_event_screen.csv')
    selected = []
    def choose(frame, col):
        top = frame.loc[frame[col].ge(frame[col].max()-1e-12)]
        return top.sort_values(['mean_advantage','policy'], ascending=[False,True]).iloc[0]
    for route,g in d.groupby('route', sort=False):
        improved = g.loc[g.policy_worst.gt(g.native_worst+1e-12)]
        tail = g.loc[g.policy_tail.gt(g.native_tail+1e-12)]
        both = improved.loc[improved.policy_tail.gt(improved.native_tail+1e-12)]
        picks = []
        if len(improved): picks.append(('BEST_WORST_TRADE',choose(improved,'policy_worst')))
        if len(tail): picks.append(('BEST_TAIL',choose(tail,'policy_tail')))
        if len(both): picks.append(('LOWEST_STATIC_COST_WITH_BOTH_RISKS_IMPROVED',choose(both,'mean_advantage')))
        for role,r in picks:
            found = next((x for x in selected if x['route']==route and x['policy']==r.policy),None)
            if found: found['profile'] += '|'+role
            else: selected.append(dict(route=route,policy=r.policy,profile=role,
                selection_period='DISCOVERY_MATURE_EVENT_SCREEN',evidence=EVIDENCE))
    for x in list(selected):
        if x['route']=='OGR': selected.append(dict(x,route='IFCGR',profile='INHERITED_OGR:'+x['profile']))
    s = pd.DataFrame(selected)
    s.to_csv(HERE/'risk_account_selection.csv',index=False)
    return s


def realized_returns(accepted):
    """Use actual fee-bearing fills; original producer net_return can use a different convention."""
    ogr='exit_raw_price' in accepted
    proceeds=accepted.qty*accepted['exit_raw_price' if ogr else 'exit_price']*.998
    if ogr:
        cash=accepted.apply(lambda r:sum(float(x['cash_per_share']) for x in json.loads(r.cash_events_json or '[]')
            if pd.Timestamp(r.entry_date)<=pd.Timestamp(x['date'])<=pd.Timestamp(r.exit_date)),axis=1)
        proceeds=proceeds+accepted.qty*cash
    return proceeds/accepted.entry_outlay-1


def align_cash_calendar(nav, daily, start, end):
    """Common endpoints; only extend genuinely empty accounts, never missing held-price marks."""
    dates=pd.DatetimeIndex(sorted(daily.loc[daily.trade_date.between(start,end),'trade_date'].unique()))
    n=nav.set_index('trade_date').sort_index()
    assert len(dates) and n.index.is_unique
    inside=dates[(dates>=n.index.min())&(dates<=n.index.max())]
    assert inside.isin(n.index).all(),'Missing internal NAV cannot be filled'
    aligned=n.reindex(dates);aligned.index.name='trade_date'
    before=dates<n.index.min();after=dates>n.index.max()
    aligned.loc[before,['nav','cash','gross_exposure']]=[1.,1.,0.]
    if after.any():
        assert abs(float(n.gross_exposure.iloc[-1]))<1e-12,'Cannot extend an invested account'
        assert abs(float(n.nav.iloc[-1]-n.cash.iloc[-1]))<1e-12
        aligned.loc[after,['nav','cash','gross_exposure']]=[n.nav.iloc[-1],n.cash.iloc[-1],0.]
    assert aligned[['nav','cash','gross_exposure']].notna().all().all()
    return aligned.reset_index()


def trade_risk(accepted, route, start, end):
    """Actually funded policy cohort; fees included, open positions not zero-filled."""
    g = accepted.loc[pd.to_datetime(accepted.entry_date).between(start,end)].copy()
    if route.startswith('ATRDR'): g = g.loc[g.route.eq(route)]
    closed = pd.to_datetime(g.exit_date).le(pd.Timestamp(end))
    r = realized_returns(g.loc[closed]).dropna()
    return dict(funded=len(g),closed=len(r),open_at_period_end=int((~closed).sum()),
        worst_trade=r.min(),worst5_trade=r.nsmallest(max(1,math.ceil(len(r)*.05))).mean(),
        below10=int(r.le(-.10).sum()),below20=int(r.le(-.20).sum()),below30=int(r.le(-.30).sum()))


def flow_changes(strategy, base, changed, route, policy, segment):
    key = 'gap_id' if strategy in ['OGR','IFCGR'] else 'event_id'
    b,p = base.set_index(key),changed.set_index(key)
    shared = set(b.index)&set(p.index)
    counts = dict(newly_funded=len(set(p.index)-set(b.index)),
        cancelled=len(set(b.index)-set(p.index)),
        quantity_changed=sum(abs(float(p.loc[k,'qty'])-float(b.loc[k,'qty']))>1e-12 for k in shared))
    rows = []
    for change,ids,frame in [('NEWLY_FUNDED',set(p.index)-set(b.index),p),('CANCELLED',set(b.index)-set(p.index),b)]:
        for k in sorted(ids):
            r = frame.loc[k]
            rows.append(dict(route=route,policy=policy,segment=segment,change=change,event_id=k,
                symbol=r.symbol,entry_date=r.entry_date,exit_date=r.exit_date,
                net_return=float(realized_returns(frame.loc[[k]]).iloc[0]),entry_outlay=r.entry_outlay))
    return counts,rows


def run(resume=False):
    if not Path('/Volumes/quant').is_mount(): raise RuntimeError('External volume unavailable')
    OUT.mkdir(parents=True,exist_ok=True)
    selections = select()
    provenance = dict(evidence=EVIDENCE,read_cutoff='2023-12-31',started_at=datetime.now().astimezone().isoformat(),
        contract_sha256=st.sha256(HERE/'risk_preference_contract.json'),
        selection_sha256=st.sha256(HERE/'risk_account_selection.csv'),runner_sha256=st.sha256(Path(__file__)),
        source_root=str(OLD),policy_active='FROM_REGISTERED_ACCOUNT_START',
        caveat='Full opportunity replay with original ranks and cash reuse. ATRDR shared-router prefix defect remains quarantined. No cross-strategy allocator.')
    if (OUT/'run_provenance.json').exists():
        previous=json.loads((OUT/'run_provenance.json').read_text())
        st.write_json(OUT/'prior_run_provenance.json',previous)
    st.write_json(OUT/'run_provenance.json',provenance)
    log('load bounded original daily and complete opportunities')
    daily = st.read_bound(OLD/'daily_relevant.parquet',"trade_date<=DATE '2023-12-31'")
    normalized = st.read_bound(OLD/'all_source_normalized.parquet',"entry_date<=DATE '2023-12-31'")
    pathframe = st.read_bound(OLD/'candidate_position_paths.parquet',"trade_date<=DATE '2023-12-31'")
    paths = {k:g for k,g in pathframe.groupby('episode_id',sort=False)}
    comparisons=[];effects=[];flows=[];audits=[];fast_context=None;completed=set()
    if resume:
        names=['risk_account_comparison.csv','risk_cash_reuse_decomposition.csv','risk_funded_flow_changes.csv','risk_no_financing_audit.csv']
        frames=[pd.read_csv(HERE/name) for name in names]
        comparisons,effects,flows=[g.to_dict('records') for g in frames[:3]];audits=[frames[3]]
        assert frames[0].start.eq(frames[0].baseline_start).all() and frames[0].end.eq(frames[0].baseline_end).all()
        assert frames[1].decomposition_residual.abs().le(1e-9).all()
        assert (frames[3].negative_cash_timestamps+frames[3].exposure_violation_timestamps).sum()==0
        completed={(x['route'],x['policy'],x['segment']) for x in effects}
        provenance['verified_resume_artifacts']={name:st.sha256(HERE/name) for name in names}
        st.write_json(OUT/'run_provenance.json',provenance)
        log(f'resume {len(completed)} completed common-calendar account comparisons')
    for spec in selections.itertuples(index=False):
        route,policy = spec.route,spec.policy
        family,value = policy.rsplit('_',1);value=float(value)
        strategy = 'ATRDR' if route.startswith('ATRDR') else route
        split = CONTRACT['splits'][route]
        segments = ['CONTINUOUS_2014_2023'] if strategy in ['ATRDR','MCB'] else ['2018_2021','2022_2023']
        for segment in segments:
            if (route,policy,segment) in completed:continue
            key=f'{strategy}_{segment}';label=f'{route}_{segment}_{policy}'
            source=pd.read_parquet(OLD/f'{key}_source.parquet')
            base_a=pd.read_parquet(OLD/f'{key}_accepted.parquet');base_n=pd.read_parquet(OLD/f'{key}_nav.parquet')
            norm=st.normalize_stock(source,None if strategy=='ATRDR' else strategy)
            funded=normalized.loc[normalized.route.eq(route)&normalized.segment.eq(segment)]
            eventfile=OLD/f'events_{route}_{policy}.parquet'
            if eventfile.exists():
                e=pd.read_parquet(eventfile);e=e.loc[e.segment.eq(segment)].copy()
            else: e=policy_events(funded,paths,family,value,active_from=split[0])
            if route=='ATRDR_FAST_BEAR':
                if fast_context is None:
                    src=st.load_sources(CONFIG);fast=pd.read_parquet(OLD/'fast_corrected.parquet')
                    f=fast.merge(src['fast_signal'][['event_id','coord_low','signal_decision_at','market_median_ret20','market_median_ret60']],on='event_id',validate='one_to_one')
                    f=f.rename(columns={'coord_low':'anchor','signal_decision_at_y':'anchor_available_at'})
                    if 'anchor_available_at' not in f: f['anchor_available_at']=f['signal_decision_at']
                    fn=st.normalize_stock(f,'ATRDR_FAST_BEAR');fn['qty']=np.nan
                    scratch=OUT/'fast_upstream';scratch.mkdir(exist_ok=True)
                    _,_,fp=st.snapshots(fn,daily,scratch)
                    market=st.read_bound(Path(CONFIG['baseline_root'])/'atrdr_full_closed_20260907/atrdr/market_state.parquet',"trade_date<=DATE '2023-12-31'")
                    fast_context=src,fast,fn,fp,market
                src,fast,fn,fp,market=fast_context
                target=fn.loc[fn.market_median_ret20.lt(fn.market_median_ret60)]
                upstream=policy_events(target,fp,family,value,active_from=split[0])
                changed_fast=apply_events(fast,fn,upstream,policy)
                scratch=OUT/f'fast_route_{policy}';scratch.mkdir(exist_ok=True)
                changed=st.route_union(src,changed_fast,market,scratch)
                upstream.to_parquet(scratch/'upstream_events.parquet',index=False)
            else: changed=apply_events(source,norm,e,policy)
            log(f'replay {label}; {int(e.filled.sum())} full-source exits')
            # Include original symbols as well for independent terminal inventory reconciliation.
            d=daily.loc[daily.symbol.isin(set(changed.symbol)|set(source.symbol))]
            cached=[OUT/f'{label}_{kind}.parquet' for kind in ['accepted','skipped','nav','source']]
            if all(p.exists() for p in cached):
                pd.testing.assert_frame_equal(pd.read_parquet(cached[3]),changed.reset_index(drop=True),check_dtype=False)
                a,s,n=[pd.read_parquet(p) for p in cached[:3]]
                log('verified reusable engine frames '+label)
            else:a,s,n=replay(strategy,changed,d,segment)
            for name,frame in [('accepted',a),('skipped',s),('nav',n),('events',e),('source',changed)]:
                frame.to_parquet(OUT/f'{label}_{name}.parquet',index=False)
            start,end=(split[0],split[3]) if len(segments)==1 else (split[0],split[1]) if segment=='2018_2021' else (split[2],split[3])
            n=align_cash_calendar(n,d,start,end);base_n=align_cash_calendar(base_n,d,start,end)
            n.to_parquet(OUT/f'{label}_account_nav.parquet',index=False)
            base_n.to_parquet(OUT/f'{key}_baseline_account_nav.parquet',index=False)
            au,ledger=audit_account(strategy,a,n,d,segment,route+':'+policy)
            assert au.negative_cash_timestamps.sum()==0 and au.exposure_violation_timestamps.sum()==0
            ledger.to_parquet(OUT/f'{label}_event_states.parquet',index=False);audits.append(au)
            counts,flow=flow_changes(strategy,base_a,a,route,policy,segment);flows.extend(flow)
            navdelta=float(n.nav.iloc[-1]-base_n.nav.iloc[-1])
            parts=accounting_decomposition(strategy,base_a,a,d,n.trade_date.max(),navdelta)
            effects.append(dict(route=route,segment=segment,policy=policy,total_account_nav_delta=navdelta,
                **parts,**counts,base_accepted=len(base_a),policy_accepted=len(a),
                released_baseline_calendar_days=e.loc[e.qty.notna(),'released_calendar_days'].sum(),
                units='INITIAL_COMBINED_NAV',cash_reuse_scope='Existing opportunity/rank/router paths; no invented future allocator return'))
            periods=[('DISCOVERY',split[0],split[1]),('CONSUMED_TEMPORAL',split[2],split[3])]
            if len(segments)==1: periods.insert(0,('FULL_HISTORY',split[0],split[3]))
            for period,start,end in periods:
                bm=nav_metrics(base_n,start,end);pm=nav_metrics(n,start,end)
                if not bm or not pm:continue
                br=trade_risk(base_a,route,start,end);pr=trade_risk(a,route,start,end)
                comparisons.append(dict(route=route,segment=segment,policy=policy,period=period,profile=spec.profile,
                    account_status='QUARANTINED_PRODUCTION_PREFIX_DEFECT' if strategy=='ATRDR' else 'FROZEN_EXECUTION_MODEL_SIMULATION',
                    evidence=EVIDENCE,**{'baseline_'+k:v for k,v in bm.items()},**pm,
                    **{'baseline_'+k:v for k,v in br.items()},**pr,
                    cagr_cost_pp=(bm['cagr']-pm['cagr'])*100,
                    mdd_reduction_pp=(pm['max_drawdown']-bm['max_drawdown'])*100,
                    worst_trade_reduction_pp=(pr['worst_trade']-br['worst_trade'])*100))
            pd.DataFrame(comparisons).to_csv(HERE/'risk_account_comparison.csv',index=False)
            pd.DataFrame(effects).to_csv(HERE/'risk_cash_reuse_decomposition.csv',index=False)
            pd.DataFrame(flows).to_csv(HERE/'risk_funded_flow_changes.csv',index=False)
            pd.concat(audits,ignore_index=True).to_csv(HERE/'risk_no_financing_audit.csv',index=False)
            log(f'complete {label}: NAV delta {navdelta:+.8f}; new {counts["newly_funded"]}, cancelled {counts["cancelled"]}')
    st.write_json(OUT/'completed.json',dict(provenance,completed_at=datetime.now().astimezone().isoformat(),
        account_replays=len(effects),comparison_rows=len(comparisons),no_financing='PASS',decomposition='RECONCILED_AT_1E-9_NAV'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--select-only',action='store_true');parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    if args.select_only:print(select().to_string(index=False))
    else:run(resume=args.resume)
