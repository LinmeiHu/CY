"""New-date performance, prior-period data revisions, and physical-account guards."""
import json
import numpy as np
import pandas as pd
from research.unified_opportunity_risk_v1 import run as base
from research.unified_opportunity_risk_v1.exposure_scale import run as previous
from research.unified_opportunity_risk_v1.max_fill_security_cap import grid as old_grid
from research.shared_capital_v1.causal_adapters import corrected_function
from research.portfolio_closure_v1 import repair
from .run import OUT,XS,YS,END,directory,verify
from .prepare_stock import HERE,CACHE
from research.unified_opportunity_risk_v1.exposure_scale.analyze import cash_provenance
PERIODS=[("2018–2021","2018-01-01","2021-12-31"),("2022–2023","2022-01-01","2023-12-31"),("2024","2024-01-01","2024-12-31"),("2025","2025-01-01","2025-12-31"),("2026 YTD","2026-01-01",END),("full","2018-01-01",END)]


def main():
    full=[];yearly=[];revision=[];curves=[];audits=[];receipts={};periods=[];cash=[];capacity=[]
    for x in XS:
        for y in YS:
            tag=previous.label(x);dest=directory(x,y);receipts[f'{tag}_Y{int(y*100)}']=verify(x,y)
            d=pd.read_parquet(dest/'daily.parquet');d.trade_date=pd.to_datetime(d.trade_date)
            f=pd.read_parquet(dest/'fills.parquet');a=json.loads((dest/'account.json').read_text())
            metric=corrected_function(base.metrics,[("pd.read_parquet(dest/'daily.parquet')",'daily.copy()'),
                ("json.loads((dest/'account.json').read_text())",'snapshot'),("pd.read_parquet(dest/'fills.parquet')",'fills.copy()')],daily=d,snapshot=a,fills=f)
            core_metric=metric
            def metric(dest,start,end):
                g=d.loc[d.trade_date.between(start,end)];gross=g.gross_exposure/g.nav
                return dict(core_metric(dest,start,end),max_gross=gross.max(),trading_days=len(g),**{f'days_gross_gt{n}':int(gross.gt(n/100).sum()) for n in [25,50,75,90]},days_gross_ge99=int(gross.ge(.99).sum()))
            full.append(dict(X=tag,Y=y,**metric(dest,'2018-01-01',END)))
            ledger,clock=cash_provenance(dest,d)
            ledger.to_csv(OUT/f'{tag}_Y{int(y*100)}_daily_cash_provenance.csv.gz',index=False)
            for name,start,end in PERIODS:
                periods.append(dict(X=tag,Y=y,period=name,**metric(dest,start,end)))
                g=ledger.loc[ledger.trade_date.between(start,end)]
                for reason in previous.REASONS:
                    cash.append(dict(X=tag,Y=y,period=name,reason=reason,average_cash_NAV_share=(g[reason]/g.nav).mean(),share_of_unused_cash_NAV_days=(g[reason]/g.nav).sum()/(g.cash/g.nav).sum(),cash_currency_days=g[reason].sum(),method='EXCLUSIVE_SIGNED_SNAPSHOT_WATERFALL; ORDER_DEPENDENT_NOT_SHAPLEY'))
            for year in range(2018,2027):yearly.append(dict(X=tag,Y=y,year=year,**metric(dest,f'{year}-01-01',END if year==2026 else f'{year}-12-31')))
            before=metric(dest,'2018-01-01','2026-09-04');old=base.metrics(old_grid.directory(x,y),'2018-01-01','2026-09-04')
            recent=metric(dest,'2026-09-07',END)
            revision.append(dict(X=tag,Y=y,old_CAGR=old['CAGR'],refreshed_history_CAGR=before['CAGR'],CAGR_revision_pp=100*(before['CAGR']-old['CAGR']),
                old_MaxDD=old['MaxDD'],refreshed_history_MaxDD=before['MaxDD'],MaxDD_revision_pp=100*(before['MaxDD']-old['MaxDD']),
                new_period_return=recent['return_'],new_period_MaxDD=recent['MaxDD'],new_period_start='2026-09-07',new_period_end=END))
            checkpoints=pd.read_parquet(dest/'checkpoints.parquet');timeline=pd.read_parquet(dest/'timeline.parquet').set_index('timestamp')
            admission=pd.read_parquet(dest/'admission.parquet')
            assert checkpoints.cash.ge(-1e-8).all() and checkpoints.gross_exposure.le(checkpoints.nav+1e-8).all()
            assert checkpoints.pnl_delta.abs().max()<1e-6
            assert all(r['status']=='APPLIED' for r in a['held_actions'])
            distributions=pd.read_parquet(dest/'cash_distributions.parquet')
            for event in a['held_actions']:
                if event['ex_date']<'2026-09-07' or event['cash_ratio']<=0:continue
                actual=distributions.loc[distributions.action_id.eq(event['action_id']+'|'+event['strategy']),'amount'].sum()
                expected=event['tradable_quantity_before']*event['cash_ratio']
                assert abs(actual-expected)<1e-6,(tag,y,event['action_id'],actual,expected)
            assert admission.loc[admission.allocated.gt(0),'R1'].gt(0).all()
            cap_max=0.;liq_max=0.
            for when,g in admission.loc[admission.allocated.gt(0)].groupby('decision_at'):
                state=timeline.loc[when];positions=dict(json.loads(state.top_symbols))
                for symbol in set(g.symbol):
                    if symbol in positions:
                        ratio=positions[symbol]/state.nav;cap_max=max(cap_max,ratio);assert ratio<=y+1e-9
                    else:assert len(positions)==10 and min(positions.values())/state.nav<=y+1e-9
            for _,g in admission.loc[admission.allocated.gt(0)].groupby(['decision_at','symbol']):
                limit=g.liquidity_cap.sum() if g.liquidity_source.eq('NATIVE_EXECUTABLE_FALLBACK').all() else g.liquidity_cap.min()
                ratio=g.allocated.sum()/limit;liq_max=max(liq_max,ratio);assert ratio<=1+1e-9
            for name,start,end in PERIODS:
                g=admission.loc[admission.decision_at.between(start,pd.Timestamp(end)+pd.Timedelta(days=1))]
                for strategy,v in g.groupby('strategy'):
                    z=v.loc[v.allocated.gt(0)];util=z.allocated/z.liquidity_cap
                    capacity.append(dict(X=tag,Y=y,period=name,strategy=strategy,requests=len(v),funded_requests=len(z),positive_R1_requests=int(v.R1.gt(0).sum()),p50_registered_limit_use=util.median(),p95_registered_limit_use=util.quantile(.95),max_registered_limit_use=util.max(),grade='REGISTERED_LIMIT_UTILIZATION; NO_ESTIMATED_IMPACT_MODEL'))
            ca=pd.read_parquet(dest/'cash_attribution.parquet')
            if x=='MAX_FILL':assert ca.SOFT_RISK_BUDGET.eq(0).all() and ca.FAMILY_RISK_BUDGET.eq(0).all()
            else:
                risk=pd.read_parquet(dest/'risk_history.parquet');active=risk.timestamp.map(admission.groupby('decision_at').allocated.sum()).fillna(0).gt(1e-8)
                assert risk.loc[active,'tail_risk'].le(risk.loc[active,'account_budget']+1e-10).all()
            audits.append(dict(X=tag,Y=y,end=str(d.trade_date.max().date()),days=len(d),min_cash=checkpoints.cash.min(),
                max_gross=(checkpoints.gross_exposure/checkpoints.nav).max(),max_new_security_share=cap_max,max_liquidity_ratio=liq_max,status='PASS'))
            curves.append(d.assign(X=tag,Y=y,nav_multiple=d.nav/a['initial_cash'],gross=d.gross_exposure/d.nav)[['X','Y','trade_date','nav_multiple','gross','nav','cash']])
            print('ANALYZED',tag,y,flush=True)
    pd.DataFrame(periods).to_csv(OUT/'candidate_b_exposure_scale_metrics.csv',index=False)
    pd.DataFrame(yearly).to_csv(OUT/'candidate_b_exposure_scale_yearly.csv',index=False)
    pd.DataFrame(cash).to_csv(OUT/'candidate_b_unused_cash_attribution.csv',index=False)
    pd.DataFrame(capacity).to_csv(OUT/'candidate_b_exposure_scale_capacity.csv',index=False)
    pd.DataFrame(full).to_csv(OUT/'candidate_b_xy_full_metrics.csv',index=False)
    pd.DataFrame(yearly).to_csv(OUT/'candidate_b_xy_yearly_metrics.csv',index=False)
    pd.DataFrame(revision).to_csv(OUT/'history_revision_and_new_period.csv',index=False)
    pd.DataFrame(audits).to_csv(OUT/'account_validation.csv',index=False)
    pd.concat(curves,ignore_index=True).to_csv(OUT/'candidate_b_xy_daily.csv.gz',index=False)
    repair.write_json(OUT/'account_run_manifest.json',receipts)
    print(f'{len(audits)} ACCOUNTS VERIFIED',flush=True)


if __name__=='__main__':main()
