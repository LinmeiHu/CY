"""Frozen comparisons and conservative cross-period policy interpretation."""
import json
import pandas as pd
import numpy as np
from .shared_study import OUT,HERE,POLICIES

KEY=['gap','period','mcb_mode']


def run():
    summary=pd.read_csv(OUT/'scenario_summary.csv')
    if len(summary)!=48 or summary[KEY+['policy']].isna().any().any() or summary.duplicated(KEY+['policy']).any():raise ValueError('incomplete/null/duplicate frozen comparison grid')
    demand=pd.read_csv(OUT/'daily_capital_demand.csv')
    if 'native_requested_before_confirmation' not in demand:
        demand['native_requested_before_confirmation']=demand.requested_notional
    demand['capital_required']=~demand.reason.eq('EXACT_CONFIRMATION_TAG')
    demand.loc[~demand.capital_required,'requested_notional']=0.
    demand.to_csv(OUT/'daily_capital_demand.csv',index=False)
    drawdowns=[]
    for index,row in summary.iterrows():
        cohort=demand
        for key in KEY+['policy']:cohort=cohort.loc[cohort[key].eq(row[key])]
        tags=int((~cohort.capital_required).sum())
        count=len(cohort)-tags
        summary.loc[index,'raw_native_intent_count']=len(cohort)
        summary.loc[index,'confirmation_tag_count']=tags
        summary.loc[index,'pre_capital_intent_count']=count
        summary.loc[index,'funded_opportunity_rate']=row.funded_trade_count/count if count else 0.
        summary.loc[index,'shared_funded_opportunity_rate']=row.shared_funded_trade_count/count if count else 0.
        folder=HERE/'cache/scenarios'/row.gap/row.period/row.mcb_mode/row.policy
        daily=pd.read_parquet(folder/'daily.parquet')
        observed=pd.read_parquet(folder/'timeline.parquet')
        observed_high=observed.nav.cummax().clip(lower=float(row.initial_nav))
        summary.loc[index,'observed_checkpoint_MaxDD']=float((1-observed.nav/observed_high).max())
        blocked_days=set(pd.to_datetime(cohort.loc[cohort.capital_required&cohort.funded_notional.eq(0),'timestamp']).dt.normalize())
        structural=~daily.trade_date.isin(blocked_days)
        summary.loc[index,'structural_idle_days']=int(structural.sum())
        summary.loc[index,'structural_idle_cash_daily_diagnostic']=float(daily.loc[structural,'cash'].mean()) if structural.any() else 0.
        summary.loc[index,'max_demand_exposure']=float(((daily.ATRDR_exposure+daily.MCB_exposure)/daily.nav).max())
        initial=json.loads((HERE/'output'/f'mcb_initial_state_{row.period[:4]}.json').read_text())['nav']
        summary.loc[index,'MCB_net_pnl']=float(daily.MCB_nav.iloc[-1]-initial)
        peak_day=pd.Timestamp(row.drawdown_start);trough_day=pd.Timestamp(row.drawdown_trough)
        trough=daily.loc[daily.trade_date.eq(trough_day)].iloc[0]
        peaks=daily.loc[daily.trade_date.eq(peak_day)]
        peak=peaks.iloc[0] if len(peaks) else None
        peak_nav=float(peak.nav) if peak is not None else row.initial_nav
        contribution={}
        for sleeve in ('ATRDR','MCB',row.gap,'SMV6'):
            initial_state=json.loads((HERE/'output'/f'{sleeve.lower()}_initial_state_{row.period[:4]}.json').read_text())
            contribution[sleeve if sleeve in ('ATRDR','MCB','SMV6') else 'Gap']=float(trough[sleeve+'_nav']-(peak[sleeve+'_nav'] if peak is not None else initial_state['nav']))
        loss=float(trough.nav-peak_nav)
        if abs(sum(contribution.values())-loss)>1e-6:raise ValueError('peak-to-trough sleeve attribution mismatch')
        drawdowns.append(dict(**{k:row[k] for k in KEY+['policy']},peak_date=peak_day,trough_date=trough_day,peak_nav=peak_nav,
            portfolio_pnl=loss,**{s+'_pnl':v for s,v in contribution.items()},shared_funded_pnl=float(trough.incremental_shared_pnl-(peak.incremental_shared_pnl if peak is not None else 0.)),
            MaxDD=-loss/peak_nav,top_symbols_at_trough=trough.top_symbols))
    pd.DataFrame(drawdowns).to_csv(OUT/'drawdown_peak_to_trough_attribution.csv',index=False)
    summary.to_csv(OUT/'scenario_summary.csv',index=False)
    headroom=pd.read_csv(OUT/'capital_headroom_summary.csv')
    for index,row in headroom.loc[headroom.classification.eq('STRUCTURAL_IDLE')].iterrows():
        cohort=summary
        for key in KEY+['policy']:cohort=cohort.loc[cohort[key].eq(row[key])]
        headroom.loc[index,'opportunity_count']=int(cohort.structural_idle_days.iloc[0])
    headroom.to_csv(OUT/'capital_headroom_summary.csv',index=False)
    base=summary.loc[summary.policy.eq('P0')].set_index(KEY)
    incremental=[]
    for row in summary.to_dict('records'):
        p0=base.loc[tuple(row[k] for k in KEY)]
        d={k:row[k] for k in KEY+['policy']}
        for field in ('CAGR','MaxDD','CVaR5','average_gross_exposure','capital_days','funded_trade_count','funded_opportunity_rate','net_pnl','observed_checkpoint_MaxDD'):
            d[field+'_delta']=row[field]-p0[field]
        d['shared_funded_pnl']=row['shared_funded_pnl'];d['shared_funded_trade_count']=row['shared_funded_trade_count']
        d['incremental_pnl_per_added_capital_day']=d['net_pnl_delta']/d['capital_days_delta'] if d['capital_days_delta']>0 else None
        d['maxdd_admissible']=row['MaxDD']<=p0['MaxDD']+.005+1e-12
        d['checkpoint_risk_budget_status']='ADMISSIBLE' if row['observed_checkpoint_MaxDD']<=p0['observed_checkpoint_MaxDD']+.005+1e-12 else 'RISK_BUDGET_BREACH'
        d['risk_status']='ADMISSIBLE' if d['maxdd_admissible'] else 'RISK_BUDGET_BREACH'
        # Exposure-normalized diagnostic, not an additive second return.
        d['exposure_only_cagr_benchmark']=p0['CAGR']*row['average_gross_exposure']/p0['average_gross_exposure']
        d['cagr_above_exposure_only_benchmark']=row['CAGR']-d['exposure_only_cagr_benchmark']
        incremental.append(d)
    inc=pd.DataFrame(incremental)
    demand=pd.read_csv(OUT/'daily_capital_demand.csv')
    removed=[]
    for row in inc.to_dict('records'):
        native=demand.loc[demand.policy.eq('P0')]
        actual=demand.loc[demand.policy.eq(row['policy'])]
        for key in KEY:
            native=native.loc[native[key].eq(row[key])];actual=actual.loc[actual[key].eq(row[key])]
        blocked=native.loc[native.reason.eq('SEGMENTATION_IDLE')].set_index('event_id')
        funded=actual.loc[actual.funded_notional.gt(0)].set_index('event_id')
        ids=blocked.index.intersection(funded.index)
        removed.append(dict(**{k:row[k] for k in KEY+['policy']},segmentation_idle_removed_count=len(ids),
            segmentation_idle_removed_notional=sum(min(float(blocked.loc[eid,'requested_notional']),float(funded.loc[eid,'funded_notional'])) for eid in ids),
            previously_rejected_requests_no_longer_in_actual_state=len(blocked.index.difference(actual.event_id))))
    inc=inc.merge(pd.DataFrame(removed),on=KEY+['policy'],validate='one_to_one')
    inc.to_csv(OUT/'incremental_capital_efficiency.csv',index=False)
    merged=summary.merge(inc,on=KEY+['policy'],validate='one_to_one',suffixes=('','_comparison'))
    merged.to_csv(OUT/'scenario_segment_results.csv',index=False)
    frontier=merged.loc[merged.policy.isin(['P2','P3_D4','P3_D5','P3_D6'])].copy()
    frontier['D']=frontier.policy.map({'P3_D4':.04,'P3_D5':.05,'P3_D6':.06})
    frontier['MDD_gate_overshoot']=np.maximum(frontier.MaxDD-frontier.D,0)
    frontier.to_csv(OUT/'drawdown_gate_frontier.csv',index=False)
    decisions=[]
    for (gap,mode), group in merged.groupby(['gap','mcb_mode']):
        selected='KEEP_FIXED_SLEEVES';classification='KEEP_FIXED_SLEEVES';review=False
        for policy in ['P2','P3_D6','P3_D5','P3_D4']:
            rows=group.loc[group.policy.eq(policy)]
            numerical=(len(rows)==2 and rows.maxdd_admissible.all() and rows.shared_funded_pnl.ge(0).all() and rows.base_entitlement_shortfall_count.eq(0).all() and rows.average_gross_exposure_delta.gt(0).all() and rows.funded_opportunity_rate_delta.gt(0).all() and rows.funded_trade_count_delta.gt(0).all())
            if not numerical:continue
            strong=rows.CAGR_delta.ge(0).all() and rows.MaxDD_delta.le(0).all()
            if strong:
                selected=policy;classification='SHARED_CAPITAL_SHADOW_CANDIDATE';break
            if rows.CAGR_delta.lt(0).sum()<=1:
                # The frozen conditional branch permits degradation in at most
                # one segment. Its undefined "modest" term is NOT replaced by
                # a newly invented zero-CAGR cutoff or a tuned numeric cutoff.
                selected=policy;classification='CONDITIONAL_ON_RISK_BUDGET';review=True;break
        selected_rows=group.loc[group.policy.eq(selected)]
        decisions.append(dict(gap=gap,mcb_mode=mode,best_admissible_policy=selected,classification=classification,
            qualitative_review_required=review,worst_CAGR_delta=float(selected_rows.CAGR_delta.min()) if len(selected_rows) else None,
            rule='Frozen preference P2,D6,D5,D4; strong branch or conditional numeric gates with at most one declining segment. Conditional label leaves modestness and date concentration explicit; no new quantitative threshold and no live allocation approval'))
    decision=pd.DataFrame(decisions);decision.to_csv(OUT/'final_decision_matrix.csv',index=False)
    independent=merged.loc[merged.mcb_mode.eq('independent')]
    tags=merged.loc[merged.mcb_mode.eq('confirmation_tag')]
    mc=independent.merge(tags,on=['gap','period','policy'],suffixes=('_independent','_tag'),validate='one_to_one')
    for f in ('CAGR','MaxDD','CVaR5','net_pnl','capital_days','demand_share','funded_trade_count','worst_portfolio_day'):mc[f+'_independent_minus_tag']=mc[f+'_independent']-mc[f+'_tag']
    ae=pd.read_parquet(HERE/'cache/atrdr/precapital_entry_population.parquet')
    ae=ae.loc[ae.route.eq('BULL')].set_index('event_id')
    me=pd.read_parquet(HERE/'cache/mcb/precapital_entry_population.parquet').set_index('event_id')
    source_keys={}
    for eid,r in ae.iterrows():
        source_keys.setdefault((r.symbol,pd.Timestamp(r.signal_date),pd.Timestamp(r.entry_date)),[]).append(eid)
    matches=[];opportunity_counts=[]
    for identity,cohort in demand.groupby(KEY+['policy']):
        keydict=dict(zip(KEY+['policy'],identity))
        eligible_a=set(cohort.loc[cohort.strategy.eq('ATRDR'),'event_id'])&set(ae.index)
        keys={}
        for eid in eligible_a:
            r=ae.loc[eid];keys.setdefault((r.symbol,pd.Timestamp(r.signal_date),pd.Timestamp(r.entry_date)),[]).append(eid)
        m=cohort.loc[cohort.strategy.eq('MCB')]
        overlap=0;only=[]
        for r in m.itertuples(index=False):
            e=me.loc[r.event_id];ids=keys.get((e.symbol,pd.Timestamp(e.signal_date),pd.Timestamp(e.entry_date)),[])
            if r.reason=='EXACT_CONFIRMATION_TAG':
                # A recorded tag proves an ATRDR intent was present and native-
                # legal in engine.fund at the merge checkpoint. Later shared
                # fills may consume its daily capacity, removing it from the
                # final demand table. Do not rewrite the earlier identity using
                # that later state or require the merged ATRDR lot to be funded.
                phase='RETAINED_IN_FINAL_DEMAND' if ids else 'LEGAL_AT_MERGE_LATER_NATIVE_CAPACITY_REJECTED'
                ids=ids or source_keys.get((e.symbol,pd.Timestamp(e.signal_date),pd.Timestamp(e.entry_date)),[])
                if len(ids)!=1:raise ValueError('production confirmation lacks a unique exact frozen ATRDR identity')
                matches.append(dict(keydict,mcb_event_id=r.event_id,atrdr_event_id=ids[0],symbol=e.symbol,decision_at=pd.Timestamp(e.signal_date)+pd.Timedelta(hours=15),entry_session=pd.Timestamp(e.entry_date)+pd.Timedelta(hours=9,minutes=30),economic_event_definition='NEXT_OPEN_T15_H15_STANDARD_NATIVE_EXIT',mcb_native_requested_notional=r.native_requested_before_confirmation,identity_stage=phase))
            if ids:overlap+=1
            else:only.append(r.event_id)
        folder=HERE/'cache/scenarios'/keydict['gap']/keydict['period']/keydict['mcb_mode']/keydict['policy']
        final=json.loads(pd.read_parquet(folder/'daily.parquet').root_pnl_json.iloc[-1])
        opportunity_counts.append(dict(keydict,exact_overlap_count=overlap,mcb_only_opportunities=len(only),mcb_only_pnl=sum(final.get(eid,0.) for eid in only)))
    pd.DataFrame(matches).to_csv(OUT/'mcb_exact_confirmation_matches.csv',index=False)
    counts=pd.DataFrame(opportunity_counts)
    for mode,label in [('independent','independent'),('confirmation_tag','tag')]:
        part=counts.loc[counts.mcb_mode.eq(mode)].drop(columns='mcb_mode').rename(columns={f:f+'_'+label for f in ('exact_overlap_count','mcb_only_opportunities','mcb_only_pnl')})
        mc=mc.merge(part,on=['gap','period','policy'],validate='one_to_one')
    avoided=[]
    for r in mc.itertuples(index=False):
        capital=json.loads((HERE/'cache/scenarios'/r.gap/r.period/'independent'/r.policy/'capital_days.json').read_text())
        ids={m['mcb_event_id'] for m in matches if m['gap']==r.gap and m['period']==r.period and m['policy']==r.policy}
        avoided.append(sum(capital.get(eid,0.) for eid in ids))
    mc['duplicate_capital_days_avoided']=avoided
    mc['independent_MCB_incremental_pnl']=mc.MCB_net_pnl_independent-mc.MCB_net_pnl_tag
    mc.to_csv(OUT/'mcb_mode_comparison.csv',index=False)
    og=merged.loc[merged.gap.eq('OGR')];ig=merged.loc[merged.gap.eq('IFCGR')]
    gc=og.merge(ig,on=['period','mcb_mode','policy'],suffixes=('_OGR','_IFCGR'),validate='one_to_one')
    for f in ('CAGR','MaxDD','CVaR5','net_pnl','capital_days','average_cash','shared_funded_pnl','funded_trade_count'):gc[f+'_IFCGR_minus_OGR']=gc[f+'_IFCGR']-gc[f+'_OGR']
    issuer_rows=[]
    for period in ('2018_2021','2022_2023'):
        ogr_demand=demand.loc[demand.gap.eq('OGR')&demand.period.eq(period)&demand.mcb_mode.eq('independent')&demand.policy.eq('P0')&demand.strategy.eq('OGR')]
        selected=set(pd.read_parquet(HERE/'cache/ifcgr'/period/'signals.parquet').gap_id)
        excluded=set(ogr_demand.loc[ogr_demand.funded_notional.gt(0),'event_id'])-selected
        daily=pd.read_parquet(HERE/'cache/scenarios/OGR'/period/'independent/P0/daily.parquet')
        pnl=json.loads(daily.root_pnl_json.iloc[-1]);values=[pnl.get(eid,0.) for eid in excluded]
        issuer_rows.append(dict(period=period,excluded_native_funded_count=len(excluded),excluded_native_pnl=sum(values),excluded_winner_pnl=sum(v for v in values if v>0),excluded_loss_pnl=sum(v for v in values if v<0),worst_excluded_pnl=min(values) if values else None,
            scope='OGR independent P0 native-funded events absent from the same PIT-B IFCGR parent subset; account feedback and inherited wealth reported separately'))
    pd.DataFrame(issuer_rows).to_csv(OUT/'issuer_filter_effect.csv',index=False)
    gc=gc.merge(pd.DataFrame(issuer_rows),on='period',validate='many_to_one')
    gc.to_csv(OUT/'gap_family_comparison.csv',index=False)
    worst=pd.read_csv(OUT/'worst_portfolio_days.csv')
    worst.to_csv(OUT/'drawdown_attribution.csv',index=False)
    crowded=pd.read_csv(OUT/'daily_capital_demand.csv').groupby(KEY+['policy','timestamp'],dropna=False).agg(request_count=('event_id','size'),requested_notional=('requested_notional','sum'),funded_notional=('funded_notional','sum')).reset_index()
    crowded=crowded.sort_values('requested_notional',ascending=False).groupby(KEY+['policy']).head(10)
    crowded.to_csv(OUT/'crowded_dates.csv',index=False)
    shared=pd.read_csv(OUT/'shared_funded_trades.csv')
    shared['virtual_lot_id']=shared.event_id
    shared.to_csv(OUT/'shared_funded_trades.csv',index=False)
    for extra,name in [(['strategy'],'shared_funded_strategy_attribution'),(['entry'],'shared_funded_date_attribution')]:
        grouped=shared.groupby(KEY+['policy']+extra).agg(count=('event_id','size'),wins=('pnl',lambda x:int(x.gt(0).sum())),losses=('pnl',lambda x:int(x.lt(0).sum())),total_pnl=('pnl','sum'),best_trade=('pnl','max'),worst_trade=('pnl','min'),capital_days=('capital_days','sum')).reset_index()
        grouped.to_csv(OUT/f'{name}.csv',index=False)
    # Role conclusions remain conservative unless both periods give an
    # unambiguous capital/risk dominance comparison at P0.
    p0mc=mc.loc[mc.policy.eq('P0')]
    tag_dominates=p0mc.CAGR_independent_minus_tag.le(0).all() and p0mc.MaxDD_independent_minus_tag.ge(0).all() and p0mc.worst_portfolio_day_independent_minus_tag.le(0).all() and p0mc.capital_days_independent_minus_tag.gt(0).any()
    ind_dominates=p0mc.CAGR_independent_minus_tag.ge(0).all() and p0mc.MaxDD_independent_minus_tag.le(0).all() and p0mc.worst_portfolio_day_independent_minus_tag.ge(0).all() and p0mc.net_pnl_independent_minus_tag.gt(0).any()
    mcb_role='MCB_USE_AS_CONFIRMATION_TAG' if tag_dominates else 'MCB_KEEP_INDEPENDENT_SLEEVE' if ind_dominates else 'EVIDENCE_INSUFFICIENT'
    p0gap=gc.loc[gc.policy.eq('P0')]
    gap_role='USE_IFCGR_GAP_SLEEVE' if p0gap.CAGR_IFCGR_minus_OGR.ge(0).all() and p0gap.MaxDD_IFCGR_minus_OGR.le(0).all() else 'USE_OGR_GAP_SLEEVE' if p0gap.CAGR_IFCGR_minus_OGR.le(0).all() and p0gap.MaxDD_IFCGR_minus_OGR.ge(0).all() else 'KEEP_BOTH_AS_ALTERNATIVE_SHADOWS'
    result=dict(MCB_CAPITAL_ROLE=mcb_role,GAP_FAMILY_CHOICE=gap_role,policy_decisions=decisions,SCENARIOS_COMPLETED='48/48',
        BEST_ADMISSIBLE_POLICY='P2' if decision.best_admissible_policy.eq('P2').all() else 'SEE_FROZEN_DECISION_MATRIX',
        FINAL_CAPITAL_DECISION='KEEP_FIXED_SLEEVES' if not decision.classification.eq('SHARED_CAPITAL_SHADOW_CANDIDATE').any() else 'SHARED_CAPITAL_SHADOW_CANDIDATE',
        MAX_DRAWDOWN_CONSTRAINT_STATUS='PASS' if inc.maxdd_admissible.all() and inc.checkpoint_risk_budget_status.eq('ADMISSIBLE').all() else 'RISK_BUDGET_BREACH')
    (OUT/'capital_decision_v2.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result,flush=True)
    return result

if __name__=='__main__':run()
