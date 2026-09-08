"""Predeclared selection, paired controls, and descriptive finalist diagnostics."""
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import argparse
import ast
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from research.unified_opportunity_risk_v1.data import OUT,HERE,CONTRACT,csv,Calibration
from research.unified_opportunity_risk_v1.run import configs,case,metrics
from research.portfolio_closure_v1 import repair

NATIVE=OUT/'native_replay/OGR'
PERIODS=[('DISCOVERY','2018-01-01','2021-12-31'),('VALIDATION','2022-01-01','2023-12-31'),
         ('2024_POST_HOC','2024-01-01','2024-12-31'),('2025_POST_HOC','2025-01-01','2025-12-31'),('2026_YTD_POST_HOC','2026-01-01','2026-09-04'),('FULL','2018-01-01','2026-09-04')]

def canonical_context(value):
    parsed=json.loads(value)
    for key,item in parsed.items():
        if isinstance(item,str) and item.startswith("{'"):
            decoded=ast.literal_eval(item)
            if isinstance(decoded,set):parsed[key]=sorted(decoded)
    return json.dumps(parsed,sort_keys=True)

def equal_state(actual,expected):
    fields=['trade_date','cash','nav','gross_exposure','fees','positions_json','lots_json']
    pd.testing.assert_frame_equal(actual[fields].reset_index(drop=True),expected[fields].reset_index(drop=True),check_dtype=False,atol=1e-6,rtol=1e-10)
    a=actual.callback_state_json.map(canonical_context).reset_index(drop=True)
    b=expected.callback_state_json.map(canonical_context).reset_index(drop=True)
    assert a.eq(b).all(), 'native callback semantic state drift'

def validation_status(m,b):
    if (m['CAGR']>=b['CAGR'] and m['MaxDD']<=b['MaxDD']) or (b['CAGR']>0 and m['CAGR']>=.8*b['CAGR'] and m['MaxDD']<=.8*b['MaxDD'] and m['Sharpe']>=b['Sharpe']):return 'PASS'
    if m['CAGR']>0 and m['MaxDD']<=b['MaxDD']:return 'MARGINAL'
    return 'FAIL'

def validation_job(c):return case(c,end='2023-12-31',group='validation')
def diagnostic_job(c):return case(c,end='2026-09-04',group='diagnostic')
def evidence_job(args):
    c,end=args
    return case(c,end=end,group='finalist_evidence')

def finalist_evidence(workers=3):
    selected=json.loads((OUT/'candidate_freeze_receipt.json').read_text())['validation_cases'];survivors=json.loads((OUT/'validation_survivors.json').read_text())['survivors'];cfg={c['case_id']:c for c in configs()}
    with ProcessPoolExecutor(max_workers=workers) as pool:list(pool.map(evidence_job,[(cfg[k],'2026-09-04' if k in survivors else '2023-12-31') for k in selected]))
    for key in selected:
        original=OUT/'accounts'/('diagnostic' if key in survivors else 'validation')/key
        current=OUT/'accounts/finalist_evidence'/key
        equal_state(pd.read_parquet(current/'daily.parquet'),pd.read_parquet(original/'daily.parquet'))

def validate(workers=3):
    receipt=json.loads((OUT/'candidate_freeze_receipt.json').read_text())
    assert receipt['candidates_sha256']==repair.digest(OUT/'frozen_validation_candidates.csv')
    selected=receipt['validation_cases'];allc={c['case_id']:c for c in configs()};controls=set(selected)
    for eid in selected:
        c=allc[eid]
        for rank in ['R0',c['ranking']]:
            for fam in [False,True]:controls.add(f"{rank}_RP{int(c['risk_profile']*100)}_S{int(c['security_cap']*100)}_F{int(fam)}")
    repair.write_json(OUT/'matched_control_freeze.json',dict(selected=selected,controls=sorted(controls),frozen_before_validation=True,contract_sha256=repair.digest(CONTRACT)))
    with ProcessPoolExecutor(max_workers=workers) as pool:list(pool.map(validation_job,[allc[k] for k in sorted(controls)]))
    baseline=metrics(NATIVE,'2022-01-01','2023-12-31');rows=[]
    for key in sorted(controls):
        dest=OUT/'accounts/validation'/key;m=metrics(dest,'2022-01-01','2023-12-31')
        # Prefix identity proves validation was continued from the same discovery
        # history, including actual state, not reinitialized with cash.
        prefix=pd.read_parquet(dest/'daily.parquet');prefix=prefix.loc[prefix.trade_date.lt('2022-01-01')].reset_index(drop=True)
        previous=pd.read_parquet(OUT/'accounts/discovery'/key/'daily.parquet')
        fields=['trade_date','cash','nav','gross_exposure','fees','positions_json','lots_json','callback_state_json']
        equal_state(prefix,previous)
        rows.append(dict(allc[key],**m,validation_status=validation_status(m,baseline),selected=key in selected,prefix_identity='PASS'))
    frame=pd.DataFrame(rows);csv(frame,'validation_2022_2023.csv')
    survivors=frame.loc[frame.selected&frame.validation_status.eq('PASS'),'case_id'].tolist()
    repair.write_json(OUT/'validation_survivors.json',dict(survivors=survivors,validation_sha256=repair.digest(OUT/'validation_2022_2023.csv'),no_recalibration=True))
    return survivors

def rollforward(workers=3):
    survivors=json.loads((OUT/'validation_survivors.json').read_text())['survivors'];allc={c['case_id']:c for c in configs()}
    with ProcessPoolExecutor(max_workers=workers) as pool:list(pool.map(diagnostic_job,[allc[k] for k in survivors]))
    rows=[]
    for key in survivors:
        dest=OUT/'accounts/diagnostic'/key
        d=pd.read_parquet(dest/'daily.parquet');v=pd.read_parquet(OUT/'accounts/validation'/key/'daily.parquet')
        fields=['trade_date','cash','nav','gross_exposure','fees','positions_json','lots_json','callback_state_json']
        equal_state(d.loc[d.trade_date.lt('2024-01-01')],v)
        for label,start,end in PERIODS[2:]:
            m=metrics(dest,start,end);base=metrics(NATIVE,start,end)
            rows.append(dict(allc[key],period=label,**m,grade='POST_HOC_ROLLFORWARD_DIAGNOSTIC',catastrophe=m['MaxDD']>max(2*base['MaxDD'],.15)))
    columns=['case_id','period','CAGR','MaxDD','grade','catastrophe']
    csv(pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns),'rollforward_2024_2026.csv')

def quality_of_allocations(dest,start,end):
    a=pd.read_parquet(dest/'admission.parquet');a=a.loc[a.decision_at.between(start,pd.Timestamp(end)+pd.Timedelta(days=1))]
    # Subsequent Native lifecycle is diagnostic only, never fed back to weights.
    m=pd.read_csv(OUT/'strategy_labeled_opportunity_lineage.csv.gz').drop_duplicates(['strategy','event_id']).set_index(['strategy','event_id'])
    rows=[]
    for funded in [True,False]:
        g=a.loc[a.allocated.gt(0).eq(funded)];ret=[];days=[]
        for r in g.itertuples():
            if (r.strategy,r.event_id) in m.index:
                event=m.loc[(r.strategy,r.event_id)];ret.append(event.native_realized_return);days.append(event.normalized_capital_days)
        rows.append(dict(group='FUNDED' if funded else 'REJECTED',requests=len(g),known_lifecycle=len(ret),median_native_return=float(np.nanmedian(ret)) if len(ret) else np.nan,
            median_capital_days=float(np.nanmedian(days)) if len(days) else np.nan))
    return rows

def incremental():
    discovery=pd.read_csv(OUT/'unified_discovery_grid.csv');validation=pd.read_csv(OUT/'validation_2022_2023.csv');rows=[];riskrows=[];familyrows=[];quality=[]
    for label,f,start,end,folder in [('DISCOVERY',discovery,'2018-01-01','2021-12-31','discovery'),('VALIDATION',validation,'2022-01-01','2023-12-31','validation')]:
        base=metrics(NATIVE,start,end);lookup=f.set_index('case_id')
        for r in f.to_dict('records'):
            key=r['case_id'];dest=OUT/'accounts'/folder/key
            for q in quality_of_allocations(dest,start,end):quality.append(dict(case_id=key,period=label,**q))
            if r['ranking']=='R0':
                riskrows.append(dict(case_id=key,period=label,**{f'delta_{k}':r[k]-base[k] for k in ['CAGR','MaxDD','CVaR5','Sharpe','net_pnl','top5_event_concentration']},
                    risk_improves=r['MaxDD']<base['MaxDD'] and r['CVaR5']<base['CVaR5'],return_retention=r['CAGR']/base['CAGR'] if base['CAGR'] else np.nan))
            else:
                neutral=key.replace(r['ranking'],'R0',1)
                if neutral in lookup.index:
                    b=lookup.loc[neutral];rows.append(dict(case_id=key,matched_R0=neutral,period=label,**{f'delta_{k}':r[k]-b[k] for k in ['CAGR','MaxDD','CVaR5','Sharpe','net_pnl']},
                        incremental=r['CAGR']>b.CAGR and r['Sharpe']>b.Sharpe and r['MaxDD']<=b.MaxDD))
            if r['family_cap']:
                off=key[:-1]+'0'
                if off in lookup.index:
                    b=lookup.loc[off];familyrows.append(dict(case_id=key,matched_family_OFF=off,period=label,**{f'delta_{k}':r[k]-b[k] for k in ['CAGR','MaxDD','CVaR5','Sharpe','net_pnl']},
                        incremental=r['MaxDD']<b.MaxDD and r['CVaR5']<b.CVaR5 and r['CAGR']>=.8*b.CAGR))
    csv(pd.DataFrame(rows),'ranking_incrementality.csv');csv(pd.DataFrame(riskrows),'risk_engine_incrementality.csv');csv(pd.DataFrame(familyrows),'family_risk_incrementality.csv');csv(pd.DataFrame(quality),'funded_rejected_quality.csv')

def capital_shares():
    selected=json.loads((OUT/'candidate_freeze_receipt.json').read_text())['validation_cases'];survivors=json.loads((OUT/'validation_survivors.json').read_text())['survivors'];rows=[];distributions=[];eligibility=[]
    for key in selected:
        group='diagnostic' if key in survivors else 'validation';dest=OUT/'accounts'/group/key;d=pd.read_parquet(dest/'daily.parquet')
        for s in ['ATRDR','MCB','OGR','SMV6']:
            share=d[s+'_exposure']/d.nav
            distributions.append(dict(case_id=key,strategy=s,**{f'p{int(q*100)}':share.quantile(q) for q in [.5,.75,.9,.95]},max=share.max(),days_gt25=share.gt(.25).sum(),days_gt50=share.gt(.5).sum(),days_gt75=share.gt(.75).sum()))
        for r in d.itertuples():
            shares={s:getattr(r,s+'_exposure')/r.nav for s in ['ATRDR','MCB','OGR','SMV6']}
            rows.append(dict(case_id=key,trade_date=r.trade_date,**shares,cash=r.cash/r.nav,any_gt50=max(shares.values())>.5,any_gt75=max(shares.values())>.75))
        a=pd.read_parquet(dest/'admission.parquet')
        for s in ['ATRDR','MCB','OGR','SMV6']:
            g=a.loc[a.strategy.eq(s)&a.R1.gt(0)].copy();g['eligible_size']=np.minimum(g.risk_desired,g.liquidity_cap)
            # This is a simultaneous-demand upper bound, not a traded curve.
            # Individual security, family and whole-book constraints can only
            # lower it. Actual dominance is reported alongside the bound.
            upper=g.groupby('decision_at').apply(lambda x:float(x.eligible_size.sum()/x.NAV_before_event.iloc[0]),include_groups=False) if len(g) else pd.Series(dtype=float)
            eligibility.append(dict(case_id=key,strategy=s,strategy_cap='NONE',historical_timestamp_upper_bound=upper.max() if len(upper) else 0.,
                dates_upper_gt50=int(upper.gt(.5).sum()),dates_upper_gt75=int(upper.gt(.75).sum()),dates_upper_approach100=int(upper.ge(.95).sum()),
                interpretation='Necessary upper bound before shared security/family/account/cash caps; no strategy budget; actual account share is separately measured',
                peak_demand_timestamp=str(upper.idxmax()) if len(upper) else 'NO_POSITIVE_QUALITY_DEMAND'))
    csv(pd.DataFrame(rows),'daily_strategy_capital_share.csv.gz');csv(pd.DataFrame(distributions),'strategy_share_distributions.csv');csv(pd.DataFrame(eligibility),'extreme_eligibility.csv')

def drawdowns(d,seed):
    nav=np.r_[seed,d.nav.to_numpy()];dates=[pd.Timestamp(d.trade_date.iloc[0])-pd.Timedelta(days=1)]+list(d.trade_date)
    peak=0;episodes=[];start=None;trough=None
    for j in range(1,len(nav)):
        if nav[j]>=nav[peak]:
            if start is not None:episodes.append(dict(peak_index=peak,trough_index=trough,recovery_index=j,depth=1-nav[trough]/nav[peak]))
            peak=j;start=None;trough=None
        else:
            if start is None:start=j;trough=j
            if nav[j]<nav[trough]:trough=j
    if start is not None:episodes.append(dict(peak_index=peak,trough_index=trough,recovery_index=None,depth=1-nav[trough]/nav[peak]))
    return sorted(episodes,key=lambda x:-x['depth'])[:5],dates

def finalist_diagnostics():
    selected=json.loads((OUT/'candidate_freeze_receipt.json').read_text())['validation_cases'];survivors=json.loads((OUT/'validation_survivors.json').read_text())['survivors']
    episodes=[];stress=[];tails=[];capacity=[];cal=Calibration()
    daily_liq=pd.read_parquet(OUT/'liquidity.parquet',columns=['symbol','trade_date','amount','adv20']).set_index(['symbol','trade_date'])
    from research.scaling_regime_v1.boundary import load_etf
    _,minute,_=load_etf('2026-09-04')
    etf_window={}
    for symbol,m in minute.items():
        for r in m.loc[m.bar_role.eq('OPEN_BAR_09_30')].itertuples():
            etf_window[(symbol,pd.Timestamp(r.trade_date))]=float(r.volume_shares)

    for key in selected:
        group='finalist_evidence';dest=OUT/'accounts'/group/key
        d=pd.read_parquet(dest/'daily.parquet');account=json.loads((dest/'account.json').read_text());a=pd.read_parquet(dest/'admission.parquet');f=pd.read_parquet(dest/'fills.parquet')
        credits=pd.read_parquet(dest/'cash_distributions.parquet')
        ep,dates=drawdowns(d,account['initial_cash']);roots={r.event_id:(r.strategy,r.symbol,r.route) for r in f.itertuples()}
        for n,e in enumerate(ep,1):
            p=e['peak_index'];t=e['trough_index'];peak=d.iloc[p-1] if p else None;trough=d.iloc[t-1]
            sell_window=f.loc[f.side.eq('SELL')&pd.to_datetime(f.exit).between(dates[p],dates[t]+pd.Timedelta(days=1),inclusive='right')]
            credit_window=credits.loc[pd.to_datetime(credits.timestamp).between(dates[p],dates[t]+pd.Timedelta(days=1),inclusive='right')] if len(credits) else credits
            realized=float(sell_window.pnl.sum())+(float(credit_window.amount.sum()) if len(credit_window) else 0.)
            active_at_peak=set(json.loads(peak.lots_json)) if p else set(account['initial_states']['ATRDR']['virtual_lots'])|set(account['initial_states']['MCB']['virtual_lots'])
            pre=json.loads(peak.root_pnl_json) if p else {};post=json.loads(trough.root_pnl_json);contribution={eid:v-pre.get(eid,0.) for eid,v in post.items()}
            for eid,pnl in sorted(contribution.items(),key=lambda x:x[1]):
                if abs(pnl)<1e-9:continue
                s,symbol,route=roots.get(eid,('INHERITED','UNKNOWN',''));q=cal.get(eid,s,route) if s!='INHERITED' else dict(family='INHERITED')
                entry=a.loc[a.event_id.eq(eid)];entry=entry.iloc[0] if len(entry) else None
                episodes.append(dict(case_id=key,episode=n,peak=dates[p],trough=dates[t],recovery=dates[e['recovery_index']] if e['recovery_index'] else None,depth=e['depth'],opportunity_id=eid,strategy=s,symbol=symbol,family=q['family'],
                    pnl_contribution=pnl,active_at_peak=eid in active_at_peak,actual_realized_pnl_in_episode=realized,account_drawdown_loss=float(trough.nav-(peak.nav if p else account['initial_cash'])),estimated_tail_before_drawdown=float(peak.estimated_tail_risk) if p else np.nan,
                    entry_rank=entry['rank'] if entry is not None else np.nan,liquidity_state=entry.liquidity_source if entry is not None else 'INHERITED',
                    attribution='MARKED_ECONOMIC_PNL_DIFFERENCE; realized trade PnL remains in authoritative fills'))
        end=json.loads(d.root_pnl_json.iloc[-1]);rootp=pd.Series(end);symbols=defaultdict(float)
        for eid,v in end.items():symbols[roots.get(eid,('','UNKNOWN',''))[1]]+=v
        base=account['initial_cash'];returns=pd.Series(np.r_[base,d.nav.to_numpy()]).pct_change().dropna();pnl_daily=pd.Series(np.diff(np.r_[base,d.nav.to_numpy()]))
        for unit,series in [('DAY',pnl_daily),('EVENT',rootp),('SYMBOL',pd.Series(symbols))]:
            for n in [1,5]:
                removed=series.nlargest(n).clip(lower=0).sum();terminal=float(d.nav.iloc[-1]-removed);years=(d.trade_date.iloc[-1]-pd.Timestamp('2018-01-01')).days/365.25
                stress.append(dict(case_id=key,unit=unit,remove_best_n=n,removed_pnl=removed,remaining_pnl=terminal-base,remaining_return=terminal/base-1,remaining_CAGR=(terminal/base)**(1/years)-1 if terminal>0 else -1.,method='ATTRIBUTION_ONLY_NO_ALLOCATION_RERUN'))
        # Subsequent loss is from this very account's actual native economic
        # lifecycle. No P0 shadow is substituted for a changed funded position.
        terminal_lots={l.get('root_event_id',eid) for eid,l in account['lots'].items()}
        buys=f.loc[f.side.eq('BUY')].set_index('event_id')
        diagnostic=[]
        for r in a.loc[a.allocated.gt(0)].itertuples():
            if r.event_id in terminal_lots or r.event_id not in end:continue
            if r.event_id not in buys.index:raise ValueError('funded admission missing BUY')
            outlay=float(buys.loc[r.event_id,'funded_notional'])
            diagnostic.append(dict(estimated_tail=r.tail,realized_loss=-end[r.event_id]/outlay,strategy=r.strategy,entry=r.decision_at))
        df=pd.DataFrame(diagnostic)
        if len(df):
            df['decile']=pd.qcut(df.estimated_tail.rank(method='first'),10,labels=False,duplicates='drop')
            for dec,g in df.groupby('decile'):
                actual=g.realized_loss.nlargest(max(1,math.ceil(len(g)*.1))).mean();pred=g.estimated_tail.mean()
                tails.append(dict(case_id=key,decile=int(dec)+1,count=len(g),estimated=pred,realized_left_tail=actual,status='RISK_UNDERESTIMATION' if actual>pred else 'WITHIN_ESTIMATE',coverage=len(df)/int(a.allocated.gt(0).sum())))
        for strategy,g in a.loc[a.allocated.gt(0)].groupby('strategy'):
            ratio_columns=defaultdict(list)
            for r in g.itertuples():
                when=pd.Timestamp(r.decision_at).normalize()
                fill=buys.loc[r.event_id]
                if strategy=='SMV6':
                    volume=etf_window.get((r.symbol,when),np.nan)
                    ratio_columns['order_to_execution_window_volume'].append(float(fill.quantity)/volume if volume>0 else np.nan)
                else:
                    info=daily_liq.loc[(r.symbol,when)] if (r.symbol,when) in daily_liq.index else {}
                    for label,column in [('order_to_daily_amount','amount'),('order_to_ADV20','adv20')]:
                        denom=info.get(column,np.nan);ratio_columns[label].append(r.allocated/denom if denom>0 else np.nan)
            for mult in [1,2,5,10]:
                for name,values in ratio_columns.items():
                    ratio=pd.Series(values)*mult
                    capacity.append(dict(case_id=key,strategy=strategy,account_multiplier=mult,ratio_type=name,**{f'p{int(q*100)}':ratio.quantile(q) for q in [.5,.75,.9,.95,.99]},max=ratio.max(),missing_denominator=int(ratio.isna().sum()),grade='DESCRIPTIVE_NO_IMPACT_MODEL'))
    for frame,name,columns in [(episodes,'finalist_risk_episode_attribution.csv',['case_id','episode','pnl_contribution']), (stress,'finalist_concentration_stress.csv',['case_id','unit','remaining_return']), (tails,'tail_risk_calibration_diagnostic.csv',['case_id','decile','status']), (capacity,'finalist_capacity.csv',['case_id','strategy','ratio_type'])]:
        csv(pd.DataFrame(frame) if frame else pd.DataFrame(columns=columns),name)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['validate','rollforward','diagnostics','evidence']);p.add_argument('--workers',type=int,default=3);args=p.parse_args()
    if args.stage=='validate':validate(args.workers)
    elif args.stage=='rollforward':rollforward(args.workers)
    elif args.stage=='evidence':finalist_evidence(args.workers)
    else:incremental();capital_shares();finalist_diagnostics()
