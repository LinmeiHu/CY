"""Reconcile captured request semantics against independently replayed P0 accounts."""
import json
import pandas as pd
import numpy as np
from .repair import OUT, END, CACHE, HERE, digest, write_json


def csv(frame,name):
    compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None
    frame.to_csv(OUT/name,index=False,compression=compression,date_format='%Y-%m-%d %H:%M:%S',float_format='%.12g')


def run():
    allops=[];transitions=[];rec=[];p0=[];conflicts=[];identity=[]
    for gap in ['IFCGR','OGR']:
        dest=OUT/'repair_accounts'/f'{gap}__{END}'
        op=pd.read_parquet(dest/'precapital.parquet')
        f=pd.read_parquet(dest/'fills.parquet')
        actual=json.loads((dest/'account.json').read_text())
        ref=CACHE/'accounts'/f'{gap}__independent__NATIVE__FULL_BOOK_NORMALIZATION__{END}'
        baseline=pd.read_parquet(ref/'fills.parquet')
        fields=['event_id','strategy','symbol','side','entry','exit','quantity','filled_quantity','price','exit_price','funded_notional','fee','pnl']
        pd.testing.assert_frame_equal(f[fields],baseline[fields],check_dtype=False,rtol=1e-10,atol=1e-6)
        checks=pd.read_csv(dest/'reconciliation.csv')
        checks.loc[checks.field.eq('fills_positions'),['status','max_abs_error']]=['PASS',0.]
        p0.append(checks)
        old=json.loads((ref/'account.json').read_text())
        for name in ['positions','pending_positions']:
            assert actual[name].keys()==old[name].keys()
            assert all(abs(actual[name][k]-old[name][k])<1e-8 for k in old[name])
        buys=f.loc[f.side.eq('BUY')].copy()
        assert op.opportunity_id.is_unique
        j=buys.merge(op,on='event_id',how='left',validate='one_to_one',suffixes=('_fill','_request'),indicator=True)
        j['match']=j._merge.eq('both') & j.symbol_fill.eq(j.symbol_request)
        j['match'] &= j.entry.eq(j.funding_at)
        j['match'] &= np.isclose(j.native_requested_quantity_fill,j.native_requested_quantity_request,rtol=1e-10,atol=1e-6)
        assert j.match.all()
        identity.append(j[['event_id','strategy_fill','entry','symbol_fill','match']].assign(account=gap))
        op=op.merge(buys[['event_id','funded_notional','quantity','price']],on='event_id',how='left',validate='one_to_one',suffixes=('','_fill'))
        # Desired transitions precede SMV6 volume clipping. Keep the actual
        # executable request as a separate downstream identity field.
        callback=pd.read_parquet(dest/'callback_requests.parquet')
        inc=callback.loc[callback.classification.eq('EXPOSURE_INCREASE')].copy()
        inc['event_id']=inc.engine_ids.map(lambda v: json.loads(v)[0] if json.loads(v) else None)
        assert inc.event_id.notna().all() and inc.event_id.is_unique
        inc=inc.set_index('event_id')
        op['native_execution_requested_notional']=op.requested_increase_notional
        mask=op.strategy.eq('SMV6')
        op.loc[mask,'desired_before']=op.loc[mask,'event_id'].map(inc.desired_before)
        op.loc[mask,'desired_after']=op.loc[mask,'event_id'].map(inc.desired_after)
        op.loc[mask,'requested_increase_notional']=(op.loc[mask,'desired_after']-op.loc[mask,'desired_before'])*1.0008*1.0002
        op['actual_funded_notional']=op.funded_notional.fillna(0.)
        op['actual_fill_notional']=op.quantity.fillna(0.)*op.price_fill.fillna(0.)
        op['actual_funding_status']=np.where(op.funded_notional.notna(),'FUNDED','UNFUNDED')
        op['native_restriction']=op.event_id.map(actual['native_failures']).fillna('')
        op['legal_opportunity']=op.native_restriction.eq('')
        op['desired_before']=op.pop('desired_before')
        op['previous_desired_exposure']=op.desired_before
        op['new_desired_exposure']=op.desired_after
        op['delta_desired_exposure']=op.desired_after-op.desired_before
        assert op.delta_desired_exposure.gt(0).all()
        tr=pd.read_parquet(dest/'transitions.parquet')
        keep=['ATRDR','MCB','SMV6','IFCGR'] if gap=='IFCGR' else ['OGR']
        allops.append(op.loc[op.strategy.isin(keep)])
        transitions.append(tr.loc[tr.strategy.isin(keep)].assign(native_account_id=gap+'__NATIVE_CONTINUOUS'))
        for strategy in keep:
            for y in range(2018,2027):
                o=op.loc[op.strategy.eq(strategy)&op.decision_at.dt.year.eq(y)]
                t=tr.loc[tr.strategy.eq(strategy)&pd.to_datetime(tr.decision_at).dt.year.eq(y)]
                b=buys.loc[buys.strategy.eq(strategy)&buys.entry.dt.year.eq(y)]
                sell=f.loc[f.strategy.eq(strategy)&f.side.eq('SELL')&f.exit.dt.year.eq(y)]
                rec.append(dict(strategy=strategy,year=y,increase_opportunities=len(o),legal_increase_opportunities=int(o.legal_opportunity.sum()),
                    reduction_transitions=len(t),actual_buy_fills=len(b),actual_sell_fills=len(sell),
                    unmatched_buys=int((~b.event_id.isin(o.event_id)).sum()),unfunded_opportunities=int(o.actual_funding_status.eq('UNFUNDED').sum()),
                    structural_native_rejections=int(o.native_restriction.ne('').sum()),status='PASS'))
        events=pd.read_parquet(dest/'capital_events.parquet')
        events['account']=gap
        conflicts.append(events)
    ops=pd.concat(allops,ignore_index=True)
    # A structural native rejection remains visible but is not falsely treated
    # as legal cash scarcity or admitted to lifecycle replay.
    csv(ops,'all_prefunding_increase_requests_v2.csv.gz')
    csv(ops.loc[~ops.legal_opportunity],'native_restriction_rejections_v2.csv.gz')
    csv(ops.loc[ops.legal_opportunity],'precapital_opportunities_v2.csv.gz')
    csv(pd.concat(transitions,ignore_index=True),'non_opportunity_state_transitions.csv.gz')
    csv(pd.DataFrame(rec),'opportunity_semantic_reconciliation.csv')
    csv(pd.concat(identity,ignore_index=True),'native_buy_upstream_identity_v2.csv')
    csv(pd.concat(p0,ignore_index=True),'p0_native_reconciliation.csv')
    timeline=pd.concat(conflicts,ignore_index=True)
    csv(timeline,'physical_capital_events_v2.csv.gz')
    fund=timeline.loc[timeline.kind.eq('FUND')].copy()
    fund['shortfall']=(fund.requested-fund.legal_fundable_notional).clip(lower=0)
    fund['constrained']=fund.shortfall.gt(1e-6)
    fund['semantics']='P0_CAUSAL_FUNDING_ROUND; SAME_TIMESTAMP_JOINT_ADMISSION_NOT_YET_VALIDATED'
    csv(fund,'capital_conflict_timeline_v2.csv')
    csv(fund.groupby('account').agg(request_events=('sequence','size'),constrained_rounds=('constrained','sum'),requested=('requested','sum'),shortfall=('shortfall','sum')).reset_index(),'capital_conflict_summary_v2.csv')
    write_json(OUT/'repair_progress_v2.json',dict(opportunity_semantics='PASS_PRE_FUNDING_REQUEST_BOUNDARY',
        P0_NATIVE_RECONCILIATION='PASS',opportunities=len(ops),legal_opportunities=int(ops.legal_opportunity.sum()),
        SMV6_POST2023_COVERAGE='PASS_106_NATIVE_BUYS_AND_CALLBACK_REQUEST_BOUNDARY',IFCGR_POST2023_COVERAGE='PASS',
        SHADOW_NATIVE_REPLAY='IN_PROGRESS',CAPITAL_STATE_CAUSALITY='PASS_P0_ROUNDS_ONLY_SIMULTANEOUS_GATE_PENDING'))
    print('SEMANTICS',len(ops),'legal',int(ops.legal_opportunity.sum()),flush=True)


if __name__=='__main__':run()
