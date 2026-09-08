"""Daily lot marked/cash PNL, with explicit corporate-receivable residual."""
import json
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,parquet

def main():
    states=pd.read_parquet(OUT/'state_daily.parquet');summary=pd.read_csv(HERE/'scenario_summary.csv');maps=[];remainder=[];risk=[];cash=[]
    for r in summary[summary.status.isin(['COMPLETED','VERIFIED_REUSE'])].to_dict('records'):
        from pathlib import Path
        d=Path(r['output']);sid=r['id'];nav,tr,od,au,op,h=[pd.read_parquet(d/(n+'.parquet')) for n in ['nav','trades','orders','audit','open_positions','holdings']]
        lots=pd.concat([tr[['lot','signal_t','symbol','e']],op[['lot','signal_t','symbol','e']] if len(op) else pd.DataFrame(columns=['lot','signal_t','symbol','e'])],ignore_index=True).drop_duplicates('lot')
        if not len(h):continue
        current=h.set_index(['t','lot']).value;prev=h[['t','lot','value']].copy();prev.t+=1;prev=prev[prev.t<=nav.t.max()].set_index(['t','lot']).value
        delta=current.subtract(prev,fill_value=0).rename('marked_change').reset_index();delta['cash_flow']=0.
        flows=[];buy=od[od.status=='FILLED'].merge(lots[['lot','symbol','e']],left_on=['t','symbol'],right_on=['e','symbol'],how='left')
        flows.append(buy[['t','lot','debit']].rename(columns={'debit':'cash_delta'}).assign(cash_delta=-buy.debit.to_numpy()))
        if len(au) and 'cash_delta' in au:
            x=au[au.cash_delta.notna()].copy();dates=dict(zip(nav.date,nav.t));x['t']=x.day.map(dates);flows.append(x[['t','lot','cash_delta']])
        fl=pd.concat(flows).groupby(['t','lot']).cash_delta.sum().reset_index();delta=delta.merge(fl,on=['t','lot'],how='outer');delta[['marked_change','cash_delta']]=delta[['marked_change','cash_delta']].fillna(0)
        delta['pnl_marked_and_cash']=delta.marked_change+delta.cash_delta;delta=delta.merge(lots[['lot','signal_t']],on='lot')
        delta['entry_state']=states.S1.iloc[delta.signal_t.astype(int)].to_numpy();delta['holding_state']=states.S1.iloc[np.maximum(delta.t.astype(int).to_numpy()-1,0)].to_numpy()
        for key,g in delta.groupby(['entry_state','holding_state']):maps.append(dict(id=sid,entry_state=key[0],holding_state=key[1],pnl_marked_and_cash=g.pnl_marked_and_cash.sum(),dates=g.t.nunique()))
        exact=nav.nav.diff().fillna(nav.nav.iloc[0]-1e6).to_numpy();allocated=delta.groupby('t').pnl_marked_and_cash.sum().reindex(nav.t,fill_value=0).to_numpy();res=exact-allocated
        for st in states.S1.unique():
            mask=states.S1.iloc[np.maximum(nav.t.to_numpy()-1,0)].to_numpy()==st
            remainder.append(dict(id=sid,holding_state=st,receivable_tax_timing_residual=res[mask].sum(),exact_total_daily_pnl=exact[mask].sum(),allocated_lot_pnl=allocated[mask].sum()))
        if sid.startswith(('R4','R1_S1_D08')):
            delta['account_id']=sid;parquet(OUT/'attribution'/(sid+'_lot_daily.parquet'),delta)
        if 'unreduced_exposure' in nav:
            intents=au[au.type=='STATE_REDUCE_INTENT'] if 'type' in au else pd.DataFrame()
            pending=pd.Series(dtype=float)
            if len(intents):
                first=intents.groupby('lot').t.min().rename('intent_t');z=h.merge(first,on='lot');pending=z[z.t>=z.intent_t].groupby('t').value.sum()
            risk.append(dict(id=sid,days_unreduced=(nav.unreduced_exposure>1e-7).sum(),max_unreduced=nav.unreduced_exposure.max(),unreduced_capital_days=nav.unreduced_exposure.sum(),pending_reduce_any_state_days=len(pending),pending_reduce_any_state_capital_days=pending.sum(),reduce_intents=len(intents),exit_deferred=int((au.type=='EXIT_DEFERRED').sum()) if 'type' in au else 0))
        cash.append(dict(id=sid,mean_cash=nav.cash.mean(),no_signal_cash_days=nav.cash_no_signal.sum(),slots_full_cash_days=nav.cash_slots.sum(),state_forbidden_cash_days=nav.loc[nav.target==0,'cash'].sum() if 'target' in nav else np.nan,status='OVERLAPPING_DIAGNOSTIC_CAUSES_NOT_ADDITIVE'))
    for name,data in [('holding_transition_pnl',maps),('holding_pnl_residual',remainder),('fullbook_unreduced',risk),('idle_cash_causes',cash)]:pd.DataFrame(data).to_csv(HERE/(name+'.csv'),index=False)

if __name__=='__main__':main()
