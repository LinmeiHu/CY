"""Historical same-clock eligibility under every frozen risk/cash constraint.

This optimistic flat-book feasibility check is not a performance backtest. The
actual continuous inventory and inherited positions are reported separately.
"""
import json
import numpy as np
import pandas as pd
from research.unified_opportunity_risk_v1.data import OUT,csv
from research.unified_opportunity_risk_v1.run import configs
from research.unified_opportunity_risk_v1.engine import constrain_pro_rata

def run():
    selected=json.loads((OUT/'candidate_freeze_receipt.json').read_text())['validation_cases'];cfg={c['case_id']:c for c in configs()};refs=json.loads((OUT/'risk_references_frozen.json').read_text())['references'];rows=[];peaks=[]
    for key in selected:
        c=cfg[key];a=pd.read_parquet(OUT/'accounts/finalist_evidence'/key/'admission.parquet')
        a=a.loc[a.R1.gt(0)&~a.reason.isin(['ECONOMIC_DUPLICATE','ACTIVE_SYMBOL','MAX_K','DAILY_CAP'])]
        for strategy,group in a.groupby('strategy'):
            observations=[]
            for when,g in group.groupby('decision_at'):
                g=g.sort_values(['rank','event_id'],ascending=[False,True]).copy()
                if strategy in ['ATRDR','MCB']:
                    g['board']=g.symbol.str.startswith('3');g=g.groupby('board',group_keys=False).head(10)
                fee=.0002 if strategy=='SMV6' else .002;nav=float(g.NAV_before_event.iloc[0]);safe=nav*(1-fee)
                allocated=np.zeros(len(g));sec={};fam={};risk=0.;cash=nav
                for rank in sorted(g['rank'].unique(),reverse=True):
                    idx=np.flatnonzero(g['rank'].to_numpy()==rank);sub=g.iloc[idx];target=np.minimum(sub.risk_desired,sub.liquidity_cap).to_numpy();con=[]
                    for symbol in sorted(sub.symbol.unique()):
                        flags=(sub.symbol==symbol).astype(float).to_numpy();notional,tail=sec.get(symbol,(0.,0.))
                        con.append((flags,c['security_cap']*safe-notional));con.append((flags*sub['tail'].to_numpy()/safe,c['risk_profile']*refs['security']-tail))
                    if c['family_cap']:
                        for family in sorted(sub.family.unique()):
                            con.append(((sub.family==family).astype(float).to_numpy()*sub['tail'].to_numpy()/safe,c['risk_profile']*refs['family_risk']-fam.get(family,0.)))
                    con.append((sub['tail'].to_numpy()/safe,c['risk_profile']*refs['account']-risk));con.append((np.ones(len(sub))*(1+fee),cash))
                    values=constrain_pro_rata(target,con)
                    # The native ETF execution bill is integer-share; using this
                    # upper bound without an extra lot assumes at most one lot
                    # residual and cannot manufacture a positive eligibility claim.
                    allocated[idx]=values
                    for (_,r),value in zip(sub.iterrows(),values):
                        delta=value/safe*r['tail'];old=sec.get(r.symbol,(0.,0.));sec[r.symbol]=(old[0]+value,old[1]+delta);fam[r.family]=fam.get(r.family,0.)+delta;risk+=delta;cash-=value*(1+fee)
                share=float(allocated.sum()/nav);assert share<=1+1e-8 and cash>=-1e-6
                observations.append(dict(case_id=key,strategy=strategy,timestamp=when,qualifying_requests=len(g),joint_feasible_upper_share=share,
                    account_tail_risk=risk,account_tail_budget=c['risk_profile']*refs['account'],cash_after_fraction=cash/nav,security_risk_aggregated=True,family_enforced=c['family_cap'],liquidity_enforced=True,strategy_cap='NONE'))
            frame=pd.DataFrame(observations)
            if len(frame):
                peak=frame.loc[frame.joint_feasible_upper_share.idxmax()].to_dict();peak.update(dates_upper_gt50=int(frame.joint_feasible_upper_share.gt(.5).sum()),dates_upper_gt75=int(frame.joint_feasible_upper_share.gt(.75).sum()),dates_upper_ge95=int(frame.joint_feasible_upper_share.ge(.95).sum()),
                    test='OPTIMISTIC_FLAT_BOOK_SAME_CLOCK_FEASIBILITY_NOT_NAV',interpretation='If this upper bound is below a threshold, that historical batch cannot reach it even with all cash; accumulated actual holdings are reported separately. ETF lot rounding can only reduce this bound.')
                peaks.append(peak);rows+=observations
    csv(pd.DataFrame(peaks),'extreme_eligibility.csv');csv(pd.DataFrame(rows),'historical_joint_eligibility.csv.gz')

if __name__=='__main__':run()
