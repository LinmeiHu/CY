"""Actual-account calendar P&L and additive root attribution after identity closure."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from .audit import HERE,ROOT,PARENT,ROLL,sha256,write_json
from .accounts import END,folder,group_cases

OUT=HERE/'output'
KEY=['gap','mcb_mode','target','mechanic']


def require_identity():
    status=json.loads((OUT/'continuous_identity_status.json').read_text())
    assert status['ROLLFORWARD_IDENTITY_STATUS']=='PASS'
    assert sha256(HERE/'contracts/continuous_rollforward_protocol_v1.json')==status['protocol_sha256']


def fills_frame(path):
    f=pd.read_parquet(path/'fills.parquet').copy()
    sell=f.side.eq('SELL')
    f['timestamp']=pd.to_datetime(f.exit.where(sell,f.entry))
    f['actual_quantity']=f.filled_quantity.where(sell,f.quantity)
    f['actual_price']=f.exit_price.where(sell,f.price)
    f['notional']=f.actual_quantity*f.actual_price
    f['root']=f.root_event_id.fillna(f.event_id) if 'root_event_id' in f else f.event_id
    assert f[['timestamp','notional','fee']].notna().all().all()
    return f


def read(path,observations=True):
    import pyarrow.parquet as pq
    columns=None if observations is True else [c for c in pq.read_schema(path/'daily.parquet').names if not c.endswith('_json') or (observations=='root' and c=='root_pnl_json')]
    d=pd.read_parquet(path/'daily.parquet',columns=columns).sort_values('trade_date').reset_index(drop=True)
    a=json.loads((path/'account.json').read_text())
    t=pd.read_parquet(path/'timeline.parquet')
    f=fills_frame(path)
    d['previous_nav']=d.nav.shift(1,fill_value=a['initial_cash'])
    d['daily_pnl']=d.nav-d.previous_nav
    d['daily_return']=d.daily_pnl/d.previous_nav
    d['gross']=d.gross_exposure/d.nav
    return d,a,t,f


def capital_at(t, boundary):
    boundary=pd.Timestamp(boundary)
    prior=t.loc[pd.to_datetime(t.timestamp).le(boundary)]
    if prior.empty:return 0.  # Cumulative occupancy starts at zero at the initialization boundary.
    row=prior.iloc[-1]
    return float(row.capital_days+row.gross_exposure*(boundary-pd.Timestamp(row.timestamp)).total_seconds()/86400)


def annual(path,identity):
    d,a,t,f=read(path,observations=False);rows=[]
    for year,part in d.groupby(d.trade_date.dt.year):
        first=int(part.index[0]);prev=d.iloc[first-1] if first else None
        opening=float(part.previous_nav.iloc[0]);nav=part.nav
        returns=part.daily_return;peak=nav.cummax().clip(lower=opening)
        dd=1-nav/peak
        trades=f.loc[f.timestamp.dt.year.eq(year)]
        intra=t.loc[pd.to_datetime(t.timestamp).dt.year.eq(year)]
        family=pd.DataFrame({'DEMAND':intra.ATRDR_exposure+intra.MCB_exposure,'GAP':intra[identity['gap']+'_exposure'],'SMV6':intra.SMV6_exposure}).div(intra.nav,axis=0)
        rows.append(dict(identity,year=int(year),period_label=str(year)+' YTD' if year==2026 else str(year),days=len(part),opening_nav=opening,closing_nav=float(nav.iloc[-1]),
            net_pnl=float(nav.iloc[-1]-opening),annual_return=float(nav.iloc[-1]/opening-1),MaxDD=float(dd.max()),
            CVaR5=float(returns.nsmallest(max(1,int(np.ceil(len(returns)*.05)))).mean()),
            Sharpe=float(returns.mean()/returns.std(ddof=1)*np.sqrt(252)) if returns.std(ddof=1)>0 else None,
            average_gross=float(part.gross.mean()),p95_gross=float(part.gross.quantile(.95)),
            turnover=float(trades.notional.sum()/nav.mean()),traded_notional=float(trades.notional.sum()),
            fees=float(part.fees.iloc[-1]-(prev.fees if prev is not None else 0)),
            capital_days=capital_at(t,min(pd.Timestamp(year+1,1,1),pd.Timestamp(END)+pd.Timedelta(days=1)))-capital_at(t,pd.Timestamp(year,1,1)),
            capital_days_basis='Calendar Jan 1 to next Jan 1; final YTD through end date plus one midnight',
            max_single_name=float((intra.max_security_exposure/intra.nav).max()),max_family_exposure=float(family.max().max()),
            max_Demand_family=float(family.DEMAND.max()),max_gross=float(part.gross.max()),source=str(path),
            MaxDD_basis='Prior year-end NAV included in annual peak; daily closes',concentration_basis='All recorded completed timestamps'))
        assert abs(rows[-1]['fees']-trades.fee.sum())<1e-5
    return rows


def metadata(a,f):
    meta={}
    for row in [*f.to_dict('records'),*a['lots'].values()]:
        root=row.get('root_event_id')
        if root is None or pd.isna(root):root=row['event_id']
        meta.setdefault(root,row)
    for state in a['initial_states'].values():
        for eid,row in state.get('virtual_lots',{}).items():meta.setdefault(row.get('root_event_id') or eid,row)
    return meta


def root_deltas(d):
    rows=[];previous={}
    for r in d.itertuples():
        current=json.loads(r.root_pnl_json)
        delta={key:current.get(key,0)-previous.get(key,0) for key in current.keys()|previous.keys()}
        assert abs(sum(delta.values())-r.daily_pnl)<1e-5,(r.trade_date,sum(delta.values()),r.daily_pnl)
        rows.extend(dict(trade_date=r.trade_date,root=key,pnl=value) for key,value in delta.items() if abs(value)>1e-12)
        previous=current
    return pd.DataFrame(rows)


def contribution(path,identity):
    d,a,t,f=read(path,observations="root");meta=metadata(a,f);roots=root_deltas(d)
    roots['strategy']=roots.root.map(lambda key:meta[key]['strategy'])
    roots['route']=roots.root.map(lambda key:meta[key]['route'])
    roots['symbol']=roots.root.map(lambda key:meta[key]['symbol'])
    # ATRDR economic routes: parent V27 adapter includes Fast/Slow information
    # in its immutable event identity. The original source lane is also retained.
    roots['route']=roots.apply(lambda r: ('SLOW_BEAR' if 'SLOW' in r.root else 'FAST_BEAR' if ('FAST' in r.root or 'V27' in r.root) else 'BULL') if r.strategy=='ATRDR' else r.route,axis=1)
    roots['year']=roots.trade_date.dt.year
    for key,value in identity.items():roots[key]=value
    (HERE/'cache/attribution').mkdir(exist_ok=True)
    roots.to_parquet(HERE/'cache/attribution'/('__'.join(identity[k] for k in KEY)+'.parquet'),index=False)
    rows=roots.groupby(KEY+['year','strategy','route','symbol','root'],as_index=False).pnl.sum()
    return rows


def cases():
    return [(g,m,t,mech,END,'accounts') for g in ['OGR','IFCGR'] for m in ['independent','confirmation_tag']
            for t,mech in [('NATIVE','FULL_BOOK_NORMALIZATION'),('G25','FULL_BOOK_NORMALIZATION'),('G50','FULL_BOOK_NORMALIZATION'),('G75','FULL_BOOK_NORMALIZATION'),('G100','FULL_BOOK_NORMALIZATION'),('G25','ENTRY_ONLY'),('G100','ENTRY_ONLY')]]


def run(native_only=False):
    require_identity();metrics=[];roots=[];accounts=[]
    selected=group_cases('native') if native_only else cases()
    for case in selected:
        path=folder(*case);identity=dict(zip(KEY,case[:4]))
        while not (path/'receipt.json').exists():time.sleep(10)
        print('ECONOMICS',case[:4],flush=True)
        metrics+=annual(path,identity)
        d,_,_,_=read(path,observations=False)
        cols=['trade_date','cash','gross_exposure','nav','fees','max_security_exposure']+[c for c in d if c.endswith('_nav') or c.endswith('_exposure')]
        accounts.append(d[list(dict.fromkeys(cols))].assign(**identity))
        if not native_only:roots.append(contribution(path,identity))
    table=pd.DataFrame(metrics)
    table.to_csv(OUT/('continuous_native_annual_metrics.csv' if native_only else 'annual_scaling_metrics.csv'),index=False)
    pd.concat(accounts).to_csv(OUT/('continuous_native_account.csv' if native_only else 'continuous_scaling_accounts.csv'),index=False)
    if native_only:return
    table.loc[table.target.eq('NATIVE')].to_csv(OUT/'continuous_native_annual_metrics.csv',index=False)
    selected=pd.read_csv(HERE/'evidence/combined_top5_backtest_curve_selection.csv')[['rank','gap','mcb_mode','target']]
    table.loc[table.mechanic.eq('FULL_BOOK_NORMALIZATION')&table.year.ge(2022)].merge(selected,on=['gap','mcb_mode','target'],validate='many_to_one').sort_values(['rank','year']).to_csv(OUT/'top5_authoritative_annual_metrics.csv',index=False)
    table.loc[table.target.ne('NATIVE')].to_csv(OUT/'continuous_scaling_annual_metrics.csv',index=False)
    native=table.loc[table.target.eq('NATIVE')].drop(columns=['target','mechanic'])
    increment=table.merge(native,on=['gap','mcb_mode','year'],suffixes=('_scaled','_native'),validate='many_to_one')
    for name in ['net_pnl','annual_return','fees','turnover','capital_days','MaxDD']:
        increment['incremental_'+name]=increment[name+'_scaled']-increment[name+'_native']
    increment['MaxDD_difference_interpretation']='Descriptive difference of path extrema, not additive P&L attribution'
    increment.to_csv(OUT/'annual_scaling_increment.csv',index=False)
    roots=pd.concat(roots,ignore_index=True);roots.to_csv(OUT/'annual_event_contribution.csv',index=False)
    for name,extra in [('strategy',['strategy']),('route',['strategy','route']),('symbol',['strategy','symbol'])]:
        group=roots.groupby(KEY+['year']+extra,as_index=False).pnl.sum()
        pieces=[]
        for (gap,mode,target,mechanic),scaled in group.groupby(KEY):
            native=group.loc[group.target.eq('NATIVE') & group.gap.eq(gap) & group.mcb_mode.eq(mode)]
            joined=scaled[['year']+extra+['pnl']].merge(native[['year']+extra+['pnl']],on=['year']+extra,how='outer',suffixes=('_scaled','_native'),validate='one_to_one')
            joined[['pnl_scaled','pnl_native']]=joined[['pnl_scaled','pnl_native']].fillna(0.)
            for key,value in zip(KEY,[gap,mode,target,mechanic]):joined[key]=value
            joined['incremental_pnl']=joined.pnl_scaled-joined.pnl_native
            pieces.append(joined)
        merged=pd.concat(pieces,ignore_index=True)
        merged.to_csv(OUT/('annual_'+name+'_contribution.csv'),index=False)
    full=table.loc[table.mechanic.eq('FULL_BOOK_NORMALIZATION') & table.target.isin(['G25','G100'])]
    entry=table.loc[table.mechanic.eq('ENTRY_ONLY')]
    mech=full.merge(entry,on=['gap','mcb_mode','target','year'],suffixes=('_full_book','_entry_only'))
    mech['full_book_minus_entry_only_pnl']=mech.net_pnl_full_book-mech.net_pnl_entry_only
    mech['interpretation']=np.where(np.sign(mech.net_pnl_full_book)!=np.sign(mech.net_pnl_entry_only),'MECHANISM_DEPENDENT_REGIME_EFFECT','SAME_ANNUAL_PNL_DIRECTION')
    mech.to_csv(OUT/'annual_scaling_mechanics_comparison.csv',index=False)
    print('ANNUAL_ACCOUNT_ATTRIBUTION_COMPLETE',len(table),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--native-only',action='store_true');args=parser.parse_args();run(args.native_only)
