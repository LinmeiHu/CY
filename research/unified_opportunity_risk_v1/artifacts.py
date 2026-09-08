"""Audit-only export repairs and canonical physical-state validation."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research.scaling_regime_v1.boundary import load_etf
from research.unified_opportunity_risk_v1.data import HERE,OUT,csv
from research.portfolio_closure_v1 import repair


def reconcile_liquidity_exports():
    _,minute,_=load_etf('2026-09-04');volume={}
    for symbol,m in minute.items():
        for r in m.loc[m.bar_role.eq('OPEN_BAR_09_30')].itertuples():volume[(symbol,pd.Timestamp(r.trade_date).normalize())]=float(r.volume_shares)
    rows=[]
    for dest in sorted((OUT/'accounts').glob('*/*')):
        file=dest/'admission.parquet';receipt=dest/'receipt.json'
        if not file.exists() or not receipt.exists():continue
        saved=json.loads(receipt.read_text());frame=pd.read_parquet(file)
        if saved.get('liquidity_export_reconciliation'):
            if repair.digest(file)!=saved['hashes']['admission.parquet']:raise ValueError('corrected admission hash drift')
            rows.append(saved['liquidity_export_reconciliation']);continue
        # The allocator's native execution ceiling is already conservative and
        # unchanged. Replace a requested-size proxy in the *reporting* denominator
        # with the registered actual minute window, never alter a fill.
        economic_before={p.name:repair.digest(p) for p in [dest/'daily.parquet',dest/'fills.parquet']}
        fills=pd.read_parquet(dest/'fills.parquet');buys=fills.loc[fills.side.eq('BUY')].set_index('event_id')
        event_file=dest/'smv6_events.parquet'
        events=pd.read_parquet(event_file) if event_file.exists() else pd.DataFrame()
        if len(events):
            events=events.loc[events.stage.eq('open')&events.event_type.isin(['BUY_FILLED','REBALANCE_FILLED','BUY_OR_REBALANCE_NO_FILL'])]
            events['trade_date']=pd.to_datetime(events.trade_date).dt.normalize()
        corrected=0;missing=0;max_ratio=0.
        for index,r in frame.loc[frame.strategy.eq('SMV6')].iterrows():
            day=pd.Timestamp(r.decision_at).normalize();shares=volume.get((r.symbol,day),np.nan)
            if r.event_id in buys.index:price=float(buys.loc[r.event_id,'price'])
            else:
                matches=events.loc[events.symbol.eq(r.symbol)&events.trade_date.eq(day)] if len(events) else pd.DataFrame()
                if len(matches)!=1:
                    # A cost run with no event export can still bind the original
                    # callback quote from the matched factor-specific native data.
                    from five_strategy_bundle.strategies import smv6
                    m=minute[r.symbol];m=m.loc[pd.to_datetime(m.trade_date).eq(day)&m.bar_role.eq('OPEN_BAR_09_30')]
                    if len(m)!=1:raise ValueError('unfunded ETF execution quote identity unavailable')
                    factor=float(saved.get('multiplier',1.));price=float(m.pre_adj_open.iloc[0])*(1+.0016*factor/2)
                else:price=float(matches.price_pre_adj.iloc[0])
            if not np.isfinite(shares) or shares<=0 or not np.isfinite(price):raise ValueError('registered ETF denominator missing')
            frame.loc[index,'liquidity_denominator']=shares*price
            frame.loc[index,'liquidity_denominator_basis']='REGISTERED_VOLUME_SHARES_TIMES_NATIVE_EXECUTION_PRICE'
            if r.allocated>0:max_ratio=max(max_ratio,float(buys.loc[r.event_id,'quantity'])/shares)
            corrected+=1
        assert max_ratio<=.5+1e-10
        original=repair.digest(file);frame.to_parquet(file,index=False)
        economic_after={p.name:repair.digest(p) for p in [dest/'daily.parquet',dest/'fills.parquet']};assert economic_before==economic_after
        row=dict(case=str(dest.relative_to(OUT/'accounts')),ETF_requests=corrected,max_funded_window_participation=max_ratio,
                 original_admission_sha256=original,corrected_admission_sha256=repair.digest(file),physical_fills_and_NAV_unchanged='PASS',status='PASS')
        saved['liquidity_export_reconciliation']=row;saved['hashes']['admission.parquet']=repair.digest(file);repair.write_json(receipt,saved);rows.append(row)
    csv(pd.DataFrame(rows),'liquidity_export_reconciliation.csv')


def validate_accounts():
    rows=[]
    for receipt in sorted((OUT/'accounts').glob('*/*/receipt.json')):
        dest=receipt.parent;r=json.loads(receipt.read_text());d=pd.read_parquet(dest/'daily.parquet');checks=pd.read_parquet(dest/'checkpoints.parquet')
        for name,h in r['hashes'].items():
            if repair.digest(dest/name)!=h:raise ValueError('artifact drift '+str(dest/name))
        assert checks.cash.ge(-1e-8).all() and checks.gross_exposure.le(checks.nav+1e-8).all()
        assert checks.pnl_delta.abs().max()<1e-6 and checks.quantity_delta.abs().max()<1e-8
        if (dest/'risk_history.parquet').exists():
            a=pd.read_parquet(dest/'admission.parquet');risk=pd.read_parquet(dest/'risk_history.parquet')
            buys=a.groupby('decision_at').allocated.sum();active=risk.timestamp.map(buys).fillna(0).gt(1e-8)
            assert risk.loc[active,'tail_risk'].le(risk.loc[active,'account_budget']+1e-10).all()
            assert a.loc[a.allocated.gt(0),'R1'].gt(0).all()
        rows.append(dict(case=str(dest.relative_to(OUT/'accounts')),days=len(d),checkpoints=len(checks),min_cash=checks.cash.min(),
                         max_gross=(checks.gross_exposure/checks.nav).max(),max_pnl_delta=checks.pnl_delta.abs().max(),status='PASS'))
    csv(pd.DataFrame(rows),'physical_account_validation.csv')

if __name__=='__main__':reconcile_liquidity_exports();validate_accounts()
