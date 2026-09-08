"""Actual Native economic paths, unfunded-only shadows, and discovery-only calibration."""
from collections import defaultdict
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.portfolio_closure_v1.shadow import path_metrics

HERE=Path(__file__).resolve().parent; OUT=HERE/'output'; CONTRACT=HERE/'contracts/unified_opportunity_risk_v1.json'

def csv(frame,name):
    frame.to_csv(OUT/name,index=False,compression={'method':'gzip','mtime':0} if name.endswith('.gz') else None)

def sources():
    return {s:pd.read_parquet(repair.CACHE/s.lower()/'precapital_entry_population.parquet') for s in ['ATRDR','MCB']}

def source_metadata(src):
    meta={}; pairs={}; bull={}
    for s,d in src.items():
        for r in d.to_dict('records'):
            if s=='ATRDR':
                route='BULL' if r['route']=='BULL' else ('SLOW' if 'SLOW' in str(r['lane']) else 'FAST')
                score=r['source_rank_order']; vec=(r['rank1'],r['rank2'],r['rank3'])
            else:route='MCB';score=r['industry_positive_ret20_share'];vec=tuple(r[k] for k in ['industry_positive_ret20_share','stock_minus_industry_ret20','turnover_expansion'])
            meta[r['event_id']]=dict(route_key=route,native_score=score,family='DEMAND' if route in ['BULL','MCB'] else 'ATRDR_BEAR',producer_parent=r.get('parent_event_id',''),native_vector=json.dumps(vec))
            key=(r['symbol'],pd.Timestamp(r['signal_date']),pd.Timestamp(r['entry_date']))
            if route=='BULL':bull[key]=r
            if s=='MCB' and key in bull:
                b=bull[key]
                # Producer schema identifies the shared ignition and exact execution
                # contract; compare native feature values, not any future outcome.
                if str(r['event_id']).split('|')[-1].startswith('V53-') and str(b['parent_event_id']).startswith('V29B|') and r['profile']=='T15_H15_NO_STOP' and b['profile']=='T15_H15_NO_STOP' and np.allclose(vec,[b['rank1'],b['rank2'],b['rank3']],rtol=1e-9,atol=1e-10) and np.isclose(r['entry_price'],b['entry_price'],rtol=1e-10):
                    pairs[r['event_id']]=b['event_id']
    return meta,pairs

def lifecycle():
    ops=pd.read_csv(repair.OUT/'precapital_opportunities_v2.csv.gz')
    for c in ['decision_at','funding_at','signal_at']:ops[c]=pd.to_datetime(ops[c])
    rows=[];checks=[];causal=[]
    for gap in ['IFCGR','OGR']:
        dest=OUT/'native_replay'/gap
        receipt=json.loads((dest/'observation_receipt.json').read_text());checks+=receipt['reconciliation']
        paths=pd.read_parquet(dest/'actual_root_paths.parquet')
        fills=pd.read_parquet(dest/'fills.parquet'); events=pd.read_parquet(dest/'capital_events.parquet')
        account=json.loads((dest/'account.json').read_text())
        credits=pd.read_parquet(dest/'cash_distributions.parquet')
        keep=['ATRDR','MCB','SMV6','IFCGR'] if gap=='IFCGR' else ['OGR']
        buys=fills.loc[fills.side.eq('BUY') & fills.strategy.isin(keep)]
        assert buys.event_id.isin(ops.event_id).all()
        byroot={k:g for k,g in paths.groupby('opportunity_id',sort=False)}
        for b in buys.itertuples():
            p=byroot[b.event_id].copy(); related=fills.loc[(fills.event_id.eq(b.event_id)|fills.root_event_id.eq(b.event_id))]
            sell=related.loc[related.side.eq('SELL')]
            closed=p.iloc[-1].quantity+p.iloc[-1].pending_quantity < 1e-9
            exit_at=pd.Timestamp(sell.exit.max()) if closed else None
            metrics=path_metrics(p,b.funded_notional,pd.Timestamp(b.entry),exit_at)
            pre=p.loc[p.timestamp.lt(exit_at)] if exit_at is not None else p
            metrics['peak_unrealized_return']=float(((pre.exposure-pre.remaining_outlay)/b.funded_notional).max())
            metrics['capital_days']=account['capital_days_by_event'][b.event_id]
            metrics['normalized_capital_days']=metrics['capital_days']/b.funded_notional
            rows.append(dict(opportunity_id=b.event_id,strategy=b.strategy,symbol=b.symbol,entry_at=b.entry,exit_at=exit_at,entry_notional=b.funded_notional,
                fees=related.fee.sum(),exit_reason='|'.join(sell.reason.unique()),status='COMPLETED' if closed else 'RIGHT_CENSORED',
                lifecycle_source='AUTHORITATIVE_ACTUAL_HOLDINGS',native_account=gap,**metrics))
        op=ops.loc[ops.strategy.isin(keep)]
        before=events.loc[events.kind.eq('FUND')].drop(columns=['decision_at','ids','strategies'],errors='ignore')
        causal.append(op.merge(before,on='sequence',validate='many_to_one',suffixes=('','_event')))
    actual=pd.DataFrame(rows);assert not actual.duplicated(['strategy','opportunity_id']).any()
    unfunded=ops.loc[ops.actual_funding_status.eq('UNFUNDED')]
    shadow=pd.read_csv(repair.OUT/'shadow_stock_lifecycle_v2_unfunded_only.csv.gz')
    shadow=shadow.loc[shadow.opportunity_id.isin(unfunded.opportunity_id)].copy()
    assert set(shadow.opportunity_id)==set(unfunded.opportunity_id)
    assert not set(shadow.opportunity_id)&set(actual.opportunity_id)
    shadow['lifecycle_source']='SAME_NATIVE_MACHINERY_UNFUNDED_ONLY'
    shadow['normalized_capital_days']=shadow.capital_days/shadow.entry_notional
    shadow_paths=pd.read_csv(repair.OUT/'shadow_stock_marked_paths_v2_unfunded_only.csv.gz',parse_dates=['timestamp'])
    for index,r in shadow.iterrows():
        p=shadow_paths.loc[shadow_paths.opportunity_id.eq(r.opportunity_id)]
        if pd.notna(r.exit_at):p=p.loc[p.timestamp.lt(pd.Timestamp(r.exit_at))]
        shadow.loc[index,'peak_unrealized_return']=float((p.exposure/r.entry_notional-1).max())
    csv(actual,'actual_funded_strategy_label_lifecycle.csv.gz');csv(shadow,'unfunded_strategy_label_lifecycle.csv.gz');csv(pd.DataFrame(checks),'p0_reconciliation.csv')
    causal=pd.concat(causal,ignore_index=True);causal['legally_fundable_cash']=causal.legal_fundable_notional
    csv(causal,'causal_precapital_state.csv.gz')
    life=pd.concat([actual,shadow],ignore_index=True)
    master=ops.merge(life.drop(columns=['symbol']),on=['strategy','opportunity_id'],validate='one_to_one')
    meta,pairs=source_metadata(sources()); ifcgr=set(ops.loc[ops.strategy.eq('IFCGR'),'event_id'])
    master['economic_opportunity_id']=master.event_id.map(lambda x:pairs.get(x,x))
    master['MCB_confirmed']=master.economic_opportunity_id.isin(set(pairs.values()))
    master['IFCGR_pass']=master.event_id.isin(ifcgr)
    master['route_key']=master.event_id.map(lambda x:meta.get(x,{}).get('route_key',''))
    master.loc[master.strategy.eq('SMV6'),'route_key']='SMV6'
    master.loc[master.strategy.isin(['OGR','IFCGR']),'route_key']='GAP'
    master['native_score']=master.event_id.map(lambda x:meta.get(x,{}).get('native_score',np.nan))
    mask=master.route_key.eq('GAP');master.loc[mask,'native_score']=master.loc[mask,'native_priority'].map(lambda x:-json.loads(x)[0])
    master['family']=master.route_key.map({'BULL':'DEMAND','MCB':'DEMAND','FAST':'ATRDR_BEAR','SLOW':'ATRDR_BEAR','GAP':'GAP','SMV6':'ETF'})
    master['is_primary_economic_label']=~master.strategy.eq('IFCGR') & ~master.event_id.isin(pairs)
    # When the Bull counterpart is not a legal event, an otherwise legal MCB
    # request remains its own executable economic parent.
    absent=~master.economic_opportunity_id.isin(master.event_id)
    master.loc[absent,'economic_opportunity_id']=master.loc[absent,'event_id'];master.loc[absent,'is_primary_economic_label']=True
    master['lineage_evidence']=np.where(master.strategy.isin(['OGR','IFCGR']),'EXACT_GAP_ID_PARENT',np.where(master.MCB_confirmed,'SOURCE_IGNITION_AND_NATIVE_FEATURE_EXECUTION_IDENTITY','DISTINCT_NATIVE_PRODUCER_EVENT'))
    master['economic_lifecycle_source_event_id']=master.event_id
    master['economic_actually_funded']=master.actual_funding_status.eq('FUNDED')
    for mcb,bull in pairs.items():
        bi=master.index[master.event_id.eq(bull)&master.strategy.eq('ATRDR')]
        mi=master.index[master.event_id.eq(mcb)]
        if len(bi) and len(mi) and master.loc[mi[0],'actual_funding_status']=='FUNDED':
            master.loc[bi[0],'economic_actually_funded']=True
            if master.loc[bi[0],'actual_funding_status']=='UNFUNDED':
                for field in life.columns.difference(['opportunity_id','strategy','symbol']):
                    master.loc[bi[0],field]=master.loc[mi[0],field]
                master.loc[bi[0],'economic_lifecycle_source_event_id']=mcb
    csv(master,'strategy_labeled_opportunity_lineage.csv.gz')
    primary=master.loc[master.is_primary_economic_label].copy()
    csv(primary,'economic_opportunity_master_v2.csv.gz')
    economical_lifecycle=primary[[c for c in life.columns if c in primary]+['economic_opportunity_id','economic_lifecycle_source_event_id','economic_actually_funded']].copy()
    economical_lifecycle['primary_strategy']=economical_lifecycle.strategy
    economical_lifecycle.loc[economical_lifecycle.economic_lifecycle_source_event_id.ne(economical_lifecycle.opportunity_id),'strategy']='MCB'
    economical_lifecycle['opportunity_id']=economical_lifecycle.economic_lifecycle_source_event_id
    csv(economical_lifecycle.loc[economical_lifecycle.economic_actually_funded],'actual_funded_lifecycle.csv.gz')
    csv(economical_lifecycle.loc[~economical_lifecycle.economic_actually_funded],'unfunded_shadow_lifecycle.csv.gz')
    repair.write_json(OUT/'lineage_map.json',dict(pairs=pairs,metadata=meta,ifcgr_pass=sorted(ifcgr)))
    return master

def estimate(g):
    r=g.native_realized_return.dropna().sort_values(); n=len(r);cut=int(np.floor(n*.1))
    trimmed=r.iloc[cut:n-cut] if cut else r
    return dict(sample_count=n,median_return=float(r.median()) if n else 0.,trimmed_mean_return=float(trimmed.mean()) if n else 0.,
        CVaR10=float(r.iloc[:max(1,int(np.ceil(n*.1)))].mean()) if n else -0.05,
        median_capital_days=float(g.normalized_capital_days.median()) if n else 1.)

def calibration(master):
    c=json.loads(CONTRACT.read_text());end=pd.Timestamp(c['discovery_end'])+pd.Timedelta(days=1)
    economic=master.loc[master.is_primary_economic_label].copy()
    decisions=economic.loc[economic.decision_at.lt(end)]
    train=decisions.loc[pd.to_datetime(decisions.exit_at).lt(end)&decisions.status.eq('COMPLETED')].copy()
    edges={};rows=[]
    for route,g in decisions.groupby('route_key'):
        values=g.native_score.dropna();edges[route]=[float(v) for v in np.unique(np.quantile(values,[.2,.4,.6,.8])) if values.min()<v<values.max()] if len(values) and values.nunique()>1 else []
        parent=train.loc[train.route_key.eq(route)];p=estimate(parent)
        for bucket in range(len(edges[route])+1):
            subset=parent.loc[np.searchsorted(edges[route],parent.native_score.fillna(-np.inf),side='right')==bucket]
            b=estimate(subset);fallback=b['sample_count']<30;q=p if fallback else b
            tail=max(abs(q['CVaR10']),abs(p['CVaR10']),c['risk_floor'])
            value=q['median_return']/max(q['median_capital_days'],1/1440)
            rows.append(dict(route_key=route,bucket=bucket,**b,parent_sample_count=p['sample_count'],parent_CVaR10=p['CVaR10'],
                effective_median_return=q['median_return'],effective_capital_days=q['median_capital_days'],conservative_tail_loss=tail,
                R1=value,R2=value/tail,fallback_to_parent=fallback,risk_estimate_insufficient=p['sample_count']<30,training_latest_exit=str(pd.to_datetime(parent.exit_at).max())))
    frame=pd.DataFrame(rows);csv(frame,'discovery_quality_calibration.csv');csv(frame,'discovery_tail_risk_calibration.csv')
    repair.write_json(OUT/'calibration_frozen.json',dict(contract_sha256=repair.digest(CONTRACT),score_edges=edges,rows=rows,latest_training_exit=str(pd.to_datetime(train.exit_at).max()),trained_events=len(train)))
    csv(train[['economic_opportunity_id','decision_at','exit_at','route_key','native_score','lifecycle_source']],'discovery_training_identity.csv.gz')
    return frame

class Calibration:
    def __init__(self):
        self.frozen=json.loads((OUT/'calibration_frozen.json').read_text());self.rows={(r['route_key'],r['bucket']):r for r in self.frozen['rows']}
        self.lineage=json.loads((OUT/'lineage_map.json').read_text());self.meta=self.lineage['metadata'];self.pairs=self.lineage['pairs']
    def get(self,eid,strategy,route='',priority=()):
        m=self.meta.get(eid,{})
        r=m.get('route_key','SMV6' if strategy=='SMV6' else 'GAP' if strategy in ['OGR','IFCGR'] else 'BULL' if route=='BULL' else 'MCB' if strategy=='MCB' else 'SLOW' if 'SLOW' in eid else 'FAST')
        score=m.get('native_score',-priority[0] if r=='GAP' and len(priority) else float('-inf'))
        b=int(np.searchsorted(self.frozen['score_edges'].get(r,[]),score,side='right'))
        q=self.rows.get((r,b))
        if q is None:raise ValueError('missing frozen calibration '+r)
        family={'BULL':'DEMAND','MCB':'DEMAND','FAST':'ATRDR_BEAR','SLOW':'ATRDR_BEAR','GAP':'GAP','SMV6':'ETF'}[r]
        return dict(q,family=family,native_score=score,economic_id=self.pairs.get(eid,eid))

def footprint():
    cal=Calibration();ev=pd.read_parquet(OUT/'native_replay/OGR/capital_events.parquet')
    req=pd.read_parquet(OUT/'native_replay/OGR/precapital.parquet').set_index('event_id')
    ev=ev.loc[ev.kind.eq('FUND')&ev.decision_at.lt('2022-01-01')];rows=[]
    failures=json.loads((OUT/'native_replay/OGR/account.json').read_text())['native_failures']
    for e in ev.itertuples():
        held=json.loads(e.risk_holdings_json);security=defaultdict(float);family=defaultdict(float);total=0.
        for eid,l in held.items():
            q=cal.get(eid,l['strategy'],l['route']);risk=l['exposure']/e.NAV_before_event*q['conservative_tail_loss']
            security[l['symbol']]+=risk;family[q['family']]+=risk;total+=risk
        for eid in json.loads(e.ids):
            if eid in failures:continue
            r=req.loc[eid];q=cal.get(eid,r.strategy,r.route,json.loads(r.native_priority));risk=r.native_requested_quantity*r.price/e.NAV_before_event*q['conservative_tail_loss']
            rows.append(dict(timestamp=e.decision_at,event_id=eid,family=q['family'],opportunity=risk,security=security[r.symbol]+risk,family_risk=family[q['family']]+risk,account=total+risk))
    raw=pd.DataFrame(rows);csv(raw,'native_risk_pretrade_observations.csv.gz')
    quantile=json.loads(CONTRACT.read_text())['native_reference_quantile'];refs={k:float(raw[k].quantile(quantile)) for k in ['opportunity','security','family_risk','account']}
    csv(pd.DataFrame([dict(scope=k,reference=v,quantile=quantile,period='2018_2021',source='AUTHORITATIVE_NATIVE_PRE_FUNDING') for k,v in refs.items()]),'native_risk_footprint.csv')
    repair.write_json(OUT/'risk_references_frozen.json',dict(contract_sha256=repair.digest(CONTRACT),references=refs))

def quality(master):
    rows=[]
    groups={k:master.route_key.eq(k)&master.is_primary_economic_label for k in master.route_key.unique()}
    groups.update(MCB_CONFIRMED_BULL=master.route_key.eq('BULL')&master.MCB_confirmed,NON_MCB_BULL=master.route_key.eq('BULL')&~master.MCB_confirmed,
        IFCGR_PASS=master.strategy.eq('OGR')&master.IFCGR_pass,IFCGR_REJECT=master.strategy.eq('OGR')&~master.IFCGR_pass)
    for label,mask in groups.items():
        for period,start,end in [('DISCOVERY','2018-01-01','2021-12-31'),('VALIDATION','2022-01-01','2023-12-31'),('POST_HOC','2024-01-01','2026-09-04')]:
            g=master.loc[mask&master.decision_at.between(start,pd.Timestamp(end)+pd.Timedelta(days=1))];done=g.loc[g.status.eq('COMPLETED')];r=done.native_realized_return
            positive=r.clip(lower=0);sym=done.assign(positive=positive).groupby('symbol').positive.sum()
            rows.append(dict(group=label,period=period,opportunities=len(g),completed=len(done),independent_dates=g.decision_at.dt.normalize().nunique(),
                mean=r.mean(),median=r.median(),**{f'p{int(q*100)}':r.quantile(q) for q in [.1,.25,.75,.9]},positive_fraction=r.gt(0).mean(),profit_factor=r.clip(lower=0).sum()/-r.clip(upper=0).sum() if r.clip(upper=0).sum()<0 else np.nan,
                MAE_median=done.pre_exit_MAE.median(),MAE_p10=done.pre_exit_MAE.quantile(.1),MFE_median=done.pre_exit_MFE.median(),MFE_p75=done.pre_exit_MFE.quantile(.75),MFE_p90=done.pre_exit_MFE.quantile(.9),
                holding_days=done.holding_days.median(),capital_days=done.normalized_capital_days.median(),giveback=done.giveback_from_peak_to_exit.median(),
                top5_event_concentration=positive.nlargest(5).sum()/positive.sum() if positive.sum()>0 else np.nan,top5_symbol_concentration=sym.nlargest(5).sum()/sym.sum() if sym.sum()>0 else np.nan))
    csv(pd.DataFrame(rows),'native_opportunity_quality.csv')

if __name__=='__main__':
    m=lifecycle();calibration(m);footprint();quality(m)
    print('DERIVED_PASS',len(m),int(m.is_primary_economic_label.sum()),flush=True)
