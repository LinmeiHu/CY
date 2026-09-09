"""Full 32-cell physical-account grid, yearly metrics and paired Y effects."""
from concurrent.futures import ThreadPoolExecutor
import json
import numpy as np
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1 import run as base
from research.unified_opportunity_risk_v1.analyze import canonical_context
from research.unified_opportunity_risk_v1.exposure_scale import run as previous
from research.unified_opportunity_risk_v1.max_fill_security_cap.grid import HERE,OUT,XS,YS,directory,verify,identity
from research.shared_capital_v1.causal_adapters import corrected_function


def structured_delta(left,right):
    """Compare decoded records without hiding identifiers or economic changes."""
    if isinstance(left,dict):
        assert isinstance(right,dict) and left.keys()==right.keys()
        return max((structured_delta(left[k],right[k]) for k in left),default=0.)
    if isinstance(left,list):
        assert isinstance(right,list) and len(left)==len(right)
        return max((structured_delta(a,b) for a,b in zip(left,right)),default=0.)
    if isinstance(left,(int,float)) and isinstance(right,(int,float)):
        delta=abs(left-right);assert delta<=1e-10,(left,right)
        return delta
    assert left==right,(left,right)
    return 0.


def frame_delta(left,right):
    assert left.columns.equals(right.columns) and left.index.equals(right.index)
    maximum=0.
    for c in left.columns:
        if left[c].equals(right[c]):continue
        if c.endswith('_json'):
            for a,b in zip(left[c],right[c]):maximum=max(maximum,structured_delta(json.loads(a),json.loads(b)))
        elif pd.api.types.is_numeric_dtype(left[c]):
            pd.testing.assert_series_equal(left[c],right[c],check_exact=False,rtol=0,atol=1e-10)
            maximum=max(maximum,float((left[c]-right[c]).abs().max()))
        else:pd.testing.assert_series_equal(left[c],right[c],check_exact=True)
    return maximum


def main():
    full=[];annual=[];audits=[];receipts={};parity=[];effects=[]
    for x in XS:
        ref=None
        for y in YS:
            dest=directory(x,y);saved=verify(x,y);key=f'{previous.label(x)}_Y{round(y*100)}'
            receipts[key]=dict(path=str(dest),receipt=saved)
            d=pd.read_parquet(dest/'daily.parquet');f=pd.read_parquet(dest/'fills.parquet');snapshot=json.loads((dest/'account.json').read_text())
            # Same established metric formulas, without rereading the same
            # full account ten times for the yearly slices.
            metric=corrected_function(base.metrics,[
                ("pd.read_parquet(dest/'daily.parquet')",'daily.copy()'),
                ("json.loads((dest/'account.json').read_text())",'account_snapshot'),
                ("pd.read_parquet(dest/'fills.parquet')",'fills.copy()')],daily=d,fills=f,account_snapshot=snapshot)
            full.append(dict(X=previous.label(x),Y=y,**metric(dest,'2018-01-01','2026-09-04')))
            for year in range(2018,2027):
                annual.append(dict(X=previous.label(x),Y=y,year=year,**metric(dest,f'{year}-01-01','2026-09-04' if year==2026 else f'{year}-12-31')))
            a=pd.read_parquet(dest/'admission.parquet');t=pd.read_parquet(dest/'timeline.parquet').set_index('timestamp');checks=pd.read_parquet(dest/'checkpoints.parquet')
            assert checks.cash.ge(-1e-8).all() and checks.gross_exposure.le(checks.nav+1e-8).all() and checks.pnl_delta.abs().max()<1e-6
            highest=0.;count=0
            for when,g in a.loc[a.allocated.gt(0)].groupby('decision_at'):
                state=t.loc[when];top=dict(json.loads(state.top_symbols))
                for symbol in set(g.symbol):
                    if symbol in top:
                        ratio=top[symbol]/state.nav;highest=max(highest,ratio);assert ratio<=y+1e-9,(x,y,when,symbol,ratio)
                    else:assert len(top)==10 and min(top.values())/state.nav<=y+1e-9
                    count+=1
            assert a.loc[a.allocated.gt(0),'R1'].gt(0).all()
            cash=pd.read_parquet(dest/'cash_attribution.parquet')
            if x=='MAX_FILL':assert cash.SOFT_RISK_BUDGET.eq(0).all() and cash.FAMILY_RISK_BUDGET.eq(0).all()
            else:
                risk=pd.read_parquet(dest/'risk_history.parquet');active=risk.timestamp.map(a.groupby('decision_at').allocated.sum()).fillna(0).gt(1e-8)
                assert risk.loc[active,'tail_risk'].le(risk.loc[active,'account_budget']+1e-10).all()
            audits.append(dict(X=previous.label(x),Y=y,days=len(d),min_cash=checks.cash.min(),max_gross=(checks.gross_exposure/checks.nav).max(),new_funding_checks=count,
                max_newly_funded_security_share=highest,max_held_security_share=(t.max_security_exposure/t.nav).max(),status='PASS'))
            # Independently run nonbinding cells must match the actual Y10
            # economic/callback path, not merely rounded performance numbers.
            comparable=d.copy();comparable.callback_state_json=comparable.callback_state_json.map(canonical_context)
            if y==.1:ref=(comparable,f,snapshot)
            if x!='MAX_FILL' and x<=5:
                pd.testing.assert_frame_equal(ref[0][['nav','cash','gross_exposure','callback_state_json']],comparable[['nav','cash','gross_exposure','callback_state_json']],check_exact=True)
                delta=max(frame_delta(ref[0],comparable),frame_delta(ref[1],f))
                assert ref[2]==snapshot
                parity.append(dict(X=previous.label(x),Y=y,days=len(d),daily_NAV_cash_gross_callback_final_account='EXACT',detail_max_abs_delta=delta,detail_tolerance=1e-10,status='PASS'))
            print('ANALYZED',key,flush=True)
    full=pd.DataFrame(full);annual=pd.DataFrame(annual)
    full.to_csv(OUT/'candidate_b_xy_full_metrics.csv',index=False);annual.to_csv(OUT/'candidate_b_xy_yearly_metrics.csv',index=False)
    for value,name in [('CAGR','cagr'),('MaxDD','max_drawdown')]:
        full.pivot(index='X',columns='Y',values=value).reindex([previous.label(x) for x in XS]).to_csv(OUT/f'candidate_b_xy_{name}_matrix.csv')
    annual.pivot(index=['X','year'],columns='Y',values='MaxDD').to_csv(OUT/'candidate_b_xy_yearly_max_drawdown.csv')
    for x,g in full.groupby('X',sort=False):
        b=g.loc[g.Y.eq(.1)].iloc[0]
        for r in g.itertuples():effects.append(dict(X=x,Y=r.Y,CAGR_delta_pp=(r.CAGR-b.CAGR)*100,MaxDD_delta_pp=(r.MaxDD-b.MaxDD)*100,
            CAGR_not_lower_and_MaxDD_not_higher=r.CAGR>=b.CAGR-1e-12 and r.MaxDD<=b.MaxDD+1e-12,strict_improvement=(r.CAGR>b.CAGR+1e-12 or r.MaxDD<b.MaxDD-1e-12)))
    pd.DataFrame(effects).to_csv(OUT/'paired_Y_effects.csv',index=False)
    pd.DataFrame(audits).to_csv(OUT/'account_validation.csv',index=False);pd.DataFrame(parity).to_csv(OUT/'nonbinding_Y_replay_validation.csv',index=False)
    repair.write_json(OUT/'account_run_manifest.json',receipts)
    # Check empirical execution caps from every request, aggregated at each clock.
    liquidity_checks=[]
    for x in XS:
        for y in YS:
            a=pd.read_parquet(directory(x,y)/'admission.parquet');maximum=0.
            for _,g in a.loc[a.allocated.gt(0)].groupby(['decision_at','symbol']):
                cap=g.liquidity_cap.sum() if g.liquidity_source.eq('NATIVE_EXECUTABLE_FALLBACK').all() else g.liquidity_cap.min()
                ratio=g.allocated.sum()/cap;assert ratio<=1+1e-9,(x,y,ratio);maximum=max(maximum,ratio)
            liquidity_checks.append(dict(X=previous.label(x),Y=y,max_funded_to_shared_registered_or_native_fallback_cap=maximum,status='PASS'))
    pd.DataFrame(liquidity_checks).to_csv(OUT/'liquidity_validation.csv',index=False)
    for line in (previous.OUT/'output_manifest.sha256').read_text().splitlines():
        h,n=line.split('  ',1);assert repair.digest(previous.HERE/n)==h,'previous study changed'
    registered=json.loads((previous.HERE/'input_manifest.json').read_text())['registered_inputs']
    def check(item):
        p,h=item;actual=repair.digest(p);return dict(path=p,expected=h,actual=actual,status='PASS' if actual==h else 'FAIL')
    with ThreadPoolExecutor(max_workers=4) as pool:checked=list(pool.map(check,registered.items()))
    assert all(r['status']=='PASS' for r in checked);pd.DataFrame(checked).to_csv(OUT/'registered_input_hash_verification.csv',index=False)
    repair.write_json(HERE/'input_manifest.json',dict(grid_identity=identity(),registered_inputs=registered,previous_experiment_manifest_sha256=repair.digest(previous.OUT/'output_manifest.sha256'),existing_verdict='KEEP_NATIVE_UNCHANGED'))
    print('32 ACCOUNTS PASS; 288 YEARLY ROWS; 442 INPUT HASHES PASS')

if __name__=='__main__':main()
