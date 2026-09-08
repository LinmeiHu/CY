"""Verified accounts, cash clock attribution, comparison residuals and prior-market failures."""
import json
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,ROUTES,sha,dump,parquet
from ..usic_multichampion_ashare_v3.analyze import account_audit
from .runner import publish

def comparisons(ids):
    pairs=[]
    for mode in ['C_MAX','C_10']:
        pairs += [(f'A_H02_{mode}_E10',f'A_D05_{mode}_E10'),(f'A_D08_{mode}_E10','A_D08_C_10_E10'),(f'A_H01_{mode}_E10','A_H01_C_10_E10')]
        pairs += [(f'C_H02_{mode}_G_DOWN',f'A_H02_{mode}_E10'),(f'C_H02_{mode}_G_RAMP',f'A_H02_{mode}_E10'),(f'R1_CURRENT_H02_{mode}',f'C_H02_{mode}_G_DOWN')]
        for route in ['H02','D08','H01','POOL']:
            pairs.append((f'R1_S1_{route}_{mode}',f'R0_POOL_{mode}' if route=='POOL' else f'A_{route}_{mode}_E10'))
        pairs += [(f'R4_S1_POOL_{mode}',f'R1_S1_POOL_{mode}'),(f'R4_S1_H02_{mode}',f'R1_S1_H02_{mode}'),(f'R2_PRIORITY_GATE_{mode}',f'R1_S1_POOL_{mode}'),(f'R2_PRIORITY_OPEN_{mode}',f'R0_POOL_{mode}'),(f'R1_LEVEL_D08_{mode}',f'R1_S1_D08_{mode}'),(f'R4_LEVEL_D08_{mode}',f'R1_LEVEL_D08_{mode}')]
        for route in ['H02','D08','H01','D06']:
            for stress in ['COST2','DELAY1']:pairs.append((f'B_{route}_{mode}_{stress}',f'A_{route}_{mode}_E10'))
        for policy in ['R1_S1_D08','R1_LEVEL_D08','R3_HALF_D08','R4_LEVEL_D08']:
            for stress in ['COST2','DELAY1','C3']:pairs.append((f'{policy}_{stress}_{mode}',f'{policy}_{mode}'))
        for stress in ['COST2','DELAY1']:pairs.append((f'R1_S1_D08_{stress}_{mode}',f'B_D08_{mode}_{stress}'))
        pairs += [(f'R3_HALF_D08_{mode}',f'R1_LEVEL_D08_{mode}')]
    # Recovered execution-fact attempts supersede only the blocked computational attempt.
    def resolve(x):return x+'_CA' if x+'_CA' in ids else x
    return [(resolve(a),resolve(b)) for a,b in pairs if resolve(a) in ids and resolve(b) in ids and resolve(a)!=resolve(b)]

def main():
    states=pd.read_parquet(OUT/'state_daily.parquet');a={};results=[];audits=[];annual=[];monthly=[];statemap=[];entrymap=[];transitions=[];status=[];concentration=[];execution=[];decisions=[]
    refs=[f'A_{r}_{m}_E10' for r in ROUTES for m in ['C_MAX','C_10']]
    refs += [f'C_H02_{m}_{g}' for m in ['C_MAX','C_10'] for g in ['G_DOWN','G_RAMP']]
    refs += [f'B_{r}_{m}_{g}' for r in ['H02','D08','H01','D06'] for m in ['C_MAX','C_10'] for g in ['COST2','DELAY1']]
    refs += [f'A_{r}_{m}_EST' for r in ['H02','D08','H01','D06'] for m in ['C_MAX','C_10']]
    refs += [f'E_P2_PHASE_{m}_E10' for m in ['C_MAX','C_10']]
    sources=[(sid,V3/sid,True) for sid in refs]
    for p in sorted((OUT/'accounts').glob('*/result.json')):
        r=json.loads(p.read_text())
        if r['status']=='COMPLETED':sources.append((r['id'],p.parent,False))
    for sid,d,reused in sources:
        row=json.loads((d/'result.json').read_text());identity=json.loads((d/'identity.json').read_text()) if reused else row
        assert all(sha(d/n)==h for n,h in identity['artifacts'].items())
        nav,tr,od,au,op,h=[pd.read_parquet(d/(n+'.parquet')) for n in ['nav','trades','orders','audit','open_positions','holdings']]
        audits.append(account_audit({'id':sid},d,nav,tr,od,au,op,h))
        rr={k:v for k,v in row.items() if k not in ['identity','artifacts']};rr.update(id=sid,output=str(d),version_family='V3_ORIGINAL' if reused else row['version_family'],status='VERIFIED_REUSE' if reused else 'COMPLETED');results.append(rr)
        a[sid]=(nav,tr,od,au,op,h);nav['pnl_daily']=nav.nav.diff().fillna(nav.nav.iloc[0]-1e6)
        nav['prior_state']=states.S1.iloc[np.maximum(nav.t.to_numpy()-1,0)].to_numpy()
        for period,target in [(nav.date.str[:4],annual),(nav.date.str[:7],monthly)]:
            for key,g in nav.groupby(period):
                v=np.r_[1.,np.cumprod(1+g.return_daily)];target.append(dict(id=sid,period=key,net_return=v[-1]-1,maxdd=(v/np.maximum.accumulate(v)-1).min(),mean_exposure=g.exposure.mean(),pnl=g.pnl_daily.sum(),days=len(g)))
        for key,g in nav.groupby('prior_state'):statemap.append(dict(id=sid,state=key,days=len(g),pnl=g.pnl_daily.sum(),mean_exposure=g.exposure.mean(),log_return=np.log1p(g.return_daily).sum()))
        if len(tr):
            tt=tr.copy();tt['entry_state']=states.S1.iloc[tt.signal_t.astype(int)].to_numpy()
            for key,g in tt.groupby(['family','entry_state']):entrymap.append(dict(id=sid,route=key[0],entry_state=key[1],trades=len(g),pnl=g.pnl.sum(),mean_net_return=(g.pnl/g.entry_cash).mean(),capital_days=(g.entry_cash*g.held_sessions).sum()))
            for reason,g in tt.groupby('exit_reason'):execution.append(dict(id=sid,type='EXIT_REASON',key=reason,n=len(g),pnl=g.pnl.sum(),mean_hold=g.held_sessions.mean()))
            for sym,value in tt.groupby('symbol').pnl.sum().nlargest(5).items():concentration.append(dict(id=sid,type='TOP_STOCK_PNL',key=sym,value=value,total=tt.pnl.sum()))
            buys=od[od.status=='FILLED'].merge(tt[['signal_t','symbol','pnl','S0coord','e']],on=['signal_t','symbol'],how='left')
            fac=np.load(V3/'cache/factor.npy',mmap_mode='r');sy=json.loads((V3/'cache/axes.json').read_text())['symbols'];symidx={s:j for j,s in enumerate(sy)}
            if 'opening' in buys:
                buys['below_S0']=[o*fac[int(t),symidx[s]]<line for o,t,s,line in zip(buys.opening,buys.t,buys.symbol,buys.S0coord)]
                for key,g in buys.groupby('below_S0'):execution.append(dict(id=sid,type='BELOW_FROZEN_STRUCTURE',key=str(key),n=len(g),pnl=g.pnl.sum()))
        lots=pd.concat([tr[['lot','signal_t']],op[['lot','signal_t']] if len(op) else pd.DataFrame(columns=['lot','signal_t'])],ignore_index=True).drop_duplicates('lot')
        if len(h):
            hh=h.merge(lots,on='lot',how='left');hh['entry_state']=states.S1.iloc[hh.signal_t.astype(int)].to_numpy();hh['holding_state']=states.S1.iloc[np.maximum(hh.t.astype(int).to_numpy()-1,0)].to_numpy()
            for key,g in hh.groupby(['family','entry_state','holding_state']):transitions.append(dict(id=sid,route=key[0],entry_state=key[1],holding_state=key[2],holding_rows=len(g),dates=g.t.nunique(),capital_days=g.value.sum()))
            maxind=h.groupby(['date','industry']).value.sum().groupby('date').max()/nav.set_index('date').nav
            concentration.append(dict(id=sid,type='MAX_INDUSTRY_NAV',key='historical_industry',value=maxind.max(),total=1.))
        for key,g in od.groupby('status'):status.append(dict(id=sid,status=key,n=len(g)))
        if not reused and 'state' in od:
            dd=od.copy();dd['account_id']=sid;decisions.append(dd)
        for day,value in nav.nlargest(5,'return_daily')[['date','return_daily']].itertuples(index=False):concentration.append(dict(id=sid,type='TOP_DAY_RETURN',key=day,value=value,total=np.nan))
    # Matched trades are attributed by symmetric arithmetic; full-account remainder is retained.
    pairs=[];tradeparts=[];rng=np.random.default_rng(20260908);n=970
    starts=rng.integers(0,n,(1000,49));sample=((starts[:,:,None]+np.arange(20))%n).reshape(1000,-1)[:,:n]
    for sid,base in comparisons(a):
        na,ta,*_=a[sid];nb,tb,*_=a[base];ar=na.return_daily.to_numpy();br=nb.return_daily.to_numpy();boot=np.expm1(252*np.log1p(ar[sample]).mean(axis=1))-np.expm1(252*np.log1p(br[sample]).mean(axis=1))
        delta=na.nav.iloc[-1]-nb.nav.iloc[-1]
        pair=dict(id=sid,baseline=base,return_increment=delta/1e6,exposure_increment=na.exposure.mean()-nb.exposure.mean(),cagr_diff_ci_low=np.quantile(boot,.025),cagr_diff_ci_high=np.quantile(boot,.975),inference='EXPLORATORY_PAIRED_20_SESSION_BLOCKS')
        pairs.append(pair)
        if len(ta) and len(tb):
            aa=ta.groupby(['signal_t','symbol']).agg(pnl=('pnl','sum'),cash=('entry_cash','sum'));bb=tb.groupby(['signal_t','symbol']).agg(pnl=('pnl','sum'),cash=('entry_cash','sum'))
            joined=aa.join(bb,how='outer',lsuffix='_a',rsuffix='_b');common=joined.dropna();wa=common.pnl_a/common.cash_a;wb=common.pnl_b/common.cash_b
            weights=float(((wa+wb)/2*(common.cash_a-common.cash_b)).sum());repricing=float(((common.cash_a+common.cash_b)/2*(wa-wb)).sum());onlya=joined[joined.cash_b.isna()].pnl_a.sum();onlyb=-joined[joined.cash_a.isna()].pnl_b.sum()
            tradeparts.append(dict(id=sid,baseline=base,common=len(common),only_candidate=int(joined.cash_b.isna().sum()),only_base=int(joined.cash_a.isna().sum()),common_weight_effect=weights,common_price_exit_cost_effect=repricing,unique_candidate_pnl=onlya,missed_baseline_pnl=onlyb,open_receivable_and_interaction_residual=delta-weights-repricing-onlya-onlyb,total_nav_increment=delta))
    for name,data in [('account_audit',audits),('annual',annual),('monthly',monthly),('holding_state_account_pnl',statemap),('entry_state_trade_pnl',entrymap),('entry_to_holding_transition',transitions),('order_status',status),('concentration',concentration),('execution',execution),('paired_comparison',pairs),('trade_cash_attribution',tradeparts)]:pd.DataFrame(data).to_csv(HERE/(name+'.csv'),index=False)
    if decisions:parquet(OUT/'routing_decisions.parquet',pd.concat(decisions,ignore_index=True))
    new=publish();reused=pd.DataFrame(results);pd.concat([reused[reused.status=='VERIFIED_REUSE'],new],ignore_index=True).to_csv(HERE/'scenario_summary.csv',index=False)
    dump(HERE/'attribution_status.json',dict(verified_accounts=len(a),verified_reuse=len(refs),all_account_audits_pass=True,comparisons=len(pairs),inference='CONSUMED_DEVELOPMENT',excluded_invalid_dispatch='FIX_I4_P1_BALANCED_10PCT'))

if __name__=='__main__':main()
