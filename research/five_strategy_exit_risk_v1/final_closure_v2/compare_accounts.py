"""Read existing retained stock replays; compose initial equal sleeve portfolios."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from run_closure import HERE,PARENT,PERIODS,EVIDENCE,account_metrics,sha,write_json

def stock_fills(t,strategy):
    ogr=strategy in ['OGR','IFCGR'];w=.5 if ogr else 1.
    pbuy='entry_raw_price' if ogr else 'entry_price';psell='exit_raw_price' if ogr else 'exit_price'
    rows=[]
    for a in t.to_dict('records'):
        for field,price in [('entry_date',pbuy),('exit_date',psell)]:
            if pd.notna(a[field]) and pd.notna(a[price]):
                gross=float(a['qty'])*float(a[price])*w
                rows.append(dict(trade_date=pd.Timestamp(a[field]),gross_value=gross,cost=gross*.002))
    return pd.DataFrame(rows)

def trade_summary(t,base,strategy,start,end):
    ogr=strategy in ['OGR','IFCGR'];key='gap_id' if ogr else 'event_id';w=.5 if ogr else 1.
    t=t.copy();base=base.copy()
    for d in [t,base]:
        d['entry_date']=pd.to_datetime(d.entry_date);d['exit_date']=pd.to_datetime(d.exit_date)
    carried=int((t.entry_date.lt(start)&(t.exit_date.ge(start)|t.exit_date.isna())).sum())
    open_end=int((t.entry_date.le(end)&(t.exit_date.gt(end)|t.exit_date.isna())).sum())
    t=t.loc[t.entry_date.between(start,end)]
    completed=t.loc[t.exit_date.le(end)].copy()
    proceeds=completed.qty*completed['exit_raw_price' if ogr else 'exit_price']*.998
    if ogr:
        cash=completed.apply(lambda r:sum(float(x['cash_per_share']) for x in json.loads(r.cash_events_json or '[]')
            if r.entry_date<=pd.Timestamp(x['date'])<=r.exit_date),axis=1)
        proceeds+=completed.qty*cash
    returns=proceeds/completed.entry_outlay-1
    new=~completed[key].isin(base[key]);common=completed.merge(base[[key,'holding_sessions']],on=key,suffixes=('','_native'))
    return dict(trades=len(t),closed_trades=len(completed),right_censored=len(t)-len(completed),carried_in_positions=carried,open_at_end_positions=open_end,worst_trade=returns.min(),
        severe_loss_rate=returns.le(-.1).mean(),avg_holding_days=completed.holding_sessions.mean(),
        capital_weighted_holding_days=np.average(completed.holding_sessions,weights=completed.entry_outlay) if len(completed) else np.nan,
        common_holding_days=common.holding_sessions.mean(),common_native_holding_days=common.holding_sessions_native.mean(),
        added_trades=int((~t[key].isin(base[key])).sum()),added_trade_realized_pnl=float(((proceeds-completed.entry_outlay).loc[new]*w).sum()),
        added_trade_censored=int((~t[key].isin(base[key])&~t.exit_date.le(end)).sum()))

def combine(sleeves,start,end):
    assert 'OGR' not in sleeves or 'IFCGR' not in sleeves
    assert len(sleeves)==4 and set(sleeves)>={'ATRDR','MCB','SMV6'}
    normalized={};frames={};scales={}
    for name,n in sleeves.items():
        n=n.set_index('trade_date').sort_index()
        prev=n.loc[n.index<pd.Timestamp(start),'nav'];scale=float(prev.iloc[-1]) if len(prev) else 1.
        if name=='SMV6' and not len(prev):scale=1e6
        g=n.loc[start:end,['nav','cash','gross_exposure']].copy()/scale
        assert g.notna().all().all(),f'Missing {name} portfolio NAV'
        assert g.index.is_unique
        normalized[name]=g.nav;frames[name]=g;scales[name]=scale
    calendar=next(iter(frames.values())).index
    assert all(calendar.equals(x.index) for x in frames.values()),'Do not silently intersect unequal sleeve calendars'
    nav=sum(x*.25 for x in frames.values());nav.index.name='trade_date'
    assert (nav.cash>=-1e-10).all() and (nav.gross_exposure<=nav.nav+1e-10).all()
    qs=pd.DataFrame(normalized)
    return nav.reset_index(),qs,scales

def run(selected):
    cfg=json.loads((HERE/'run_config.json').read_text());out=Path(cfg['external_root']);old=Path(cfg['old_root']);risk=Path(cfg['stock_root'])
    reads=[]
    def read(p):
        reads.append(dict(path=str(p),sha256=sha(p)));return pd.read_parquet(p)
    accounts={};fills={};summaries=[]
    for strategy,route,policy in [('ATRDR','ATRDR_FAST_BEAR','fixed_0.05'),('MCB','MCB','profit_0'),('OGR','OGR','atr_1'),('IFCGR','IFCGR','atr_1')]:
        for period in ['2018_2021','2022_2023']:
            start,end=PERIODS[period];segment=period if strategy in ['OGR','IFCGR'] else 'CONTINUOUS_2014_2023'
            base=read(old/f'{strategy}_{segment}_accepted.parquet')
            for variant in ['NATIVE','CANDIDATE']:
                prefix=f'{route}_{segment}_{policy}'
                t=base if variant=='NATIVE' else read(risk/f'{prefix}_accepted.parquet')
                n=read(risk/(f'{strategy}_{segment}_baseline_account_nav.parquet' if variant=='NATIVE' else f'{prefix}_account_nav.parquet'))
                n['trade_date']=pd.to_datetime(n.trade_date)
                f=stock_fills(t,strategy);accounts[(strategy,period,variant)]=n;fills[(strategy,period,variant)]=f
                m=account_metrics(n,start,end);ts=trade_summary(t,base,strategy,start,end)
                costs=f.loc[f.trade_date.between(start,end)]
                ts['added_trade_realized_pnl']/=m['base_nav']
                summaries.append(dict(strategy=strategy,candidate='NATIVE' if variant=='NATIVE' else policy,variant=variant,period=period,
                    **m,**ts,turnover=costs.gross_value.sum()/m['base_nav'],costs=costs.cost.sum()/m['base_nav'],
                    evidence=EVIDENCE,account_reset=strategy in ['OGR','IFCGR'],
                    cost_contract='Existing normalized stock replay:0.2% per side; OGR board accounts weighted0.5',
                    evidence_limitation=('QUARANTINED_PRODUCTION_PREFIX_DEFECT; diagnostic only' if strategy=='ATRDR' else
                        'PIT_B_ISSUER_REVISION_HISTORY_INCOMPLETE' if strategy=='IFCGR' else 'Historical selected candidate; not forward validation')))
    sm=pd.read_csv(HERE/'smv6_account_comparison.csv')
    if selected!='NONE':assert selected in set(sm.candidate)-{'NATIVE'}
    for period in ['2018_2021','2022_2023']:
        for variant,name in [('NATIVE','NATIVE')]+([('CANDIDATE',selected)] if selected!='NONE' else []):
            n=read(out/f'SMV6_{name}_nav.parquet');n['trade_date']=pd.to_datetime(n.trade_date)
            accounts[('SMV6',period,variant)]=n
            f=read(out/f'SMV6_{name}_fills.parquet');f['cost']=f.commission+f.slippage
            fills[('SMV6',period,variant)]=f
    stock=pd.DataFrame(summaries);stock.to_csv(HERE/'retained_stock_account_comparison.csv',index=False)
    portfolio=[];worstdays=[]
    for family,gap in [('A','OGR'),('B','IFCGR')]:
        for period in ['2018_2021','2022_2023']:
            start,end=PERIODS[period]
            variants={'ALL_NATIVE':[], 'GAP_ATR1_ONLY':[gap], 'MCB_PROFIT_ONLY':['MCB'],
                'ALL_RETAINED':[gap,'MCB']+(['SMV6'] if selected!='NONE' else []),
                'ATRDR_FAST5_DIAGNOSTIC_ONLY':['ATRDR']}
            if selected!='NONE':variants['SMV6_CANDIDATE_ONLY']=['SMV6']
            for variant,changes in variants.items():
                sleeves={s:accounts[(s,period,'CANDIDATE' if s in changes else 'NATIVE')] for s in ['ATRDR','MCB',gap,'SMV6']}
                n,qs,scales=combine(sleeves,start,end);m=account_metrics(n,start,end)
                cost=turnover=0.
                for s in sleeves:
                    f=fills[(s,period,'CANDIDATE' if s in changes else 'NATIVE')]
                    f=f.loc[f.trade_date.between(start,end)]
                    cost+=.25*f.cost.sum()/scales[s];turnover+=.25*f.gross_value.sum()/scales[s]
                portfolio.append(dict(portfolio=family,period=period,variant=variant,**m,costs=cost,turnover=turnover,
                    smv6_candidate=selected,evidence=EVIDENCE,portfolio_type='INITIAL_EQUAL_SLEEVE_INDEPENDENT_COMPOUNDING',
                    limitation='ALL_VARIANTS_CONDITIONAL_ON_KNOWN_ATRDR_PREFIX_DEFECT'+('; IFCGR PIT-B' if family=='B' else '')))
                n.to_parquet(out/f'portfolio_{family}_{period}_{variant}.parquet',index=False)
                q=qs.mean(axis=1);prior=q.shift(1).fillna(1.);r=q/prior-1
                contributions=qs.diff();contributions.iloc[0]=qs.iloc[0]-1
                contributions=contributions*.25/prior.to_numpy()[:,None]
                assert np.allclose(contributions.sum(axis=1),r,atol=1e-12)
                for day in r.nsmallest(10).index:
                    worstdays.append(dict(portfolio=family,period=period,variant=variant,trade_date=str(day.date()),return_=r.loc[day],
                        **{f'{s}_contribution':contributions.loc[day,s] for s in sleeves}))
    pd.DataFrame(portfolio).to_csv(HERE/'portfolio_exit_overlay_comparison.csv',index=False)
    pd.DataFrame(worstdays).to_csv(HERE/'portfolio_worst_days.csv',index=False)
    # Complete side-by-side matrix; conclusions are historical states, not production edits.
    matrix=[]
    for strategy in ['ATRDR','MCB','OGR','IFCGR','SMV6']:
        source=sm if strategy=='SMV6' else stock.loc[stock.strategy.eq(strategy)]
        choices=sorted(set(source.candidate)-{'NATIVE'})
        for period in ['2018_2021','2022_2023']:
            b=source.loc[source.period.eq(period)&source.candidate.eq('NATIVE')].iloc[0]
            for choice in choices:
                c=source.loc[source.period.eq(period)&source.candidate.eq(choice)].iloc[0]
                recommendation=('REJECT_CANDIDATE' if strategy=='ATRDR' else
                    ('RETAIN_SHADOW_CANDIDATE' if choice==selected else 'REJECT_CANDIDATE') if strategy=='SMV6' else 'RETAIN_SHADOW_CANDIDATE')
                row=dict(strategy=strategy,route_family='GAP_FAMILY' if strategy in ['OGR','IFCGR'] else 'ATRDR_FAST_BEAR_IN_SHARED_ACCOUNT' if strategy=='ATRDR' else strategy,native_rule='FROZEN_NATIVE_EXIT',production_exit='KEEP_NATIVE_EXIT',
                    candidate_rule=choice,period=period,sample_stage=EVIDENCE,final_recommendation=recommendation,
                    evidence_limitation='ATRDR prefix defect affects all portfolio comparisons; no production promotion; SMV6 native platform unverified; IFCGR PIT-B',
                    account_reset=strategy in ['OGR','IFCGR'],cost_contract=c.cost_contract,
                    added_trades=c.added_trades,released_capital_contribution=c.added_trade_realized_pnl)
                for metric in ['trades','closed_trades','right_censored','worst_trade','CAGR','MaxDD','CVaR5','worst_month','worst_quarter','recovery_days','recovery_censored','longest_drawdown_days','avg_holding_days','capital_weighted_holding_days','capital_days','costs']:
                    row[metric+'_native']=b[metric];row[metric+'_candidate']=c[metric]
                row['CAGR_delta']=c.CAGR-b.CAGR;matrix.append(row)
    pd.DataFrame(matrix).to_csv(HERE/'five_strategy_exit_decision_matrix.csv',index=False)
    unique={x['path']:x for x in reads}
    write_json(HERE/'reused_input_hashes.json',list(unique.values()))
    write_json(HERE/'portfolio_selection.json',dict(smv6_candidate=selected,weights='initial25% each; independent compounding; no transfers',periods=['2018_2021','2022_2023'],
        attribution='new episode realized PnL is one account-feedback component; never added again to CAGR'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--smv6-candidate',required=True);run(p.parse_args().smv6_candidate)
