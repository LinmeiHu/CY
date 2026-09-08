"""Fixed diagnostic tables and independent share-flow reconciliation."""
import json
from collections import defaultdict
import numpy as np
import pandas as pd
from .common import HERE,OUT,dump,sha
from .replay import Market,select

def run():
    m=Market();summary=pd.read_csv(HERE/'scenario_summary.csv');quantity_checks=[];concentration=[];statuses=[];slices=[];corrections=[];interactions=[];horizons=[];funnel=[];preopen=[];partial=[]
    for family in ['OLD_30_5','N']:
        c=pd.read_parquet(OUT/(family+'_candidates.parquet'));f=pd.read_parquet(OUT/(family+'_events.parquet'))
        funnel.extend([dict(family=family,stage='STRONG_CANDIDATE',count=len(c)),dict(family=family,stage='BREAKOUT_BEFORE_TT_VCP',count=int(c.breakout.sum()))])
        if family=='N':
            for name,mask in [('LONG_TT',c.long),('LONG_TT_AND_VCP',c.long&c.VCP_GUARD),('LONG_TT_VCP_BREAKOUT',c.long&c.VCP_GUARD&c.breakout),('LONG_TT_VCP_BREAKOUT_GATE',c.long&c.VCP_GUARD&c.breakout&c.market_gate)]:funnel.append(dict(family=family,stage=name,count=int(mask.sum())))
        other='Consolidation' if family!='N' else 'VCP'
        d=f.copy()
        if family=='N':d=d[(d.long==1)&(d.VCP_GUARD==1)].copy()
        for col in ['Path',other]:d[col+'_high']=d[col]>=d.groupby(['t','board'])[col].transform('median')
        d=d[d.net10.notna()]
        for (p,v),g in d.groupby(['Path_high',other+'_high']):interactions.append(dict(family=family,path_high=p,other_high=v,n=len(g),net10_mean=g.net10.mean(),net10_median=g.net10.median()))
        for horizon in [5,10,20]:
            for name,mask in [('ALL',np.ones(len(f),bool))]+([('LONG_TT',f.long==1),('LONG_TT_VCP',(f.long==1)&(f.VCP_GUARD==1))] if family=='N' else []):
                g=f.loc[mask];horizons.append(dict(family=family,subset=name,horizon=horizon,n=g['net'+str(horizon)].notna().sum(),mean=g['net'+str(horizon)].mean(),median=g['net'+str(horizon)].median(),gross_mean=g['gross'+str(horizon)].mean(),MFE10=g.MFE.mean(),MAE10=g.MAE.mean()))
    dates=np.array(m.dates);eligible=(m.a['hard_valid']==1)&(m.a['is_st']==0)&(np.array(m.boards)[None,:]!='UNSUPPORTED')
    funnel.append(dict(family='COMMON_RAW',stage='BASIC_VALID_NON_ST_STOCK_DAYS_BEFORE_HISTORY_WINDOWS',count=int(eligible[dates>='2020-01-01'].sum())))
    dump(HERE/'unsupported_identifiers.json',[s for s,b in zip(m.symbols,m.boards) if b=='UNSUPPORTED'])
    for s in summary[summary.status=='NEWLY_EXECUTED'].to_dict('records'):
        sid=s['id'];d=OUT/sid;n=pd.read_parquet(d/'nav.parquet');o=pd.read_parquet(d/'orders.parquet');a=pd.read_parquet(d/'audit.parquet');op=pd.read_parquet(d/'open_positions.parquet');tr=pd.read_parquet(d/'trades.parquet')
        for status,g in o.groupby('status'):statuses.append(dict(scenario=sid,stage='ENTRY',status=status,count=len(g)))
        if len(a) and 'reason' in a:
            for reason,g in a[a.type=='EXIT_DEFERRED'].groupby('reason'):statuses.append(dict(scenario=sid,stage='EXIT_ATTEMPT',status=reason,count=len(g)))
        flow=defaultdict(list)
        for r in o[o.status=='FILLED'].itertuples():flow[m.dates[int(r.t)]].append((r.symbol,int(r.quantity)))
        for r in a[a.type.isin(['SHARE_EFFECTIVE','SELL_FILL'])].itertuples():flow[r.day].append((r.symbol,int(r.quantity)*(1 if r.type=='SHARE_EFFECTIVE' else -1)))
        held={};mark={};err=0.;icon=[];weight=[]
        for r in n.itertuples():
            for sym,delta in flow[r.date]:held[sym]=held.get(sym,0)+delta;assert held[sym]>=0
            byind=defaultdict(float);mv=0.
            for sym,q in held.items():
                if not q:continue
                j=m.sy[sym[:6]];px=m.val('close',r.t,j)
                if np.isfinite(px) and px>0:mark[sym]=px
                assert sym in mark
                value=q*mark[sym];mv+=value;byind[int(m.a['industry'][r.t,j])]+=value
            err=max(err,abs(mv-r.market_value));icon.append(max(byind.values(),default=0)/r.nav);weight.append(byind.get(-1,0)/r.nav)
        assert err<1e-6,(sid,err)
        ending={r.symbol:int(r.q+r.pending) for r in op.itertuples()};assert {s:q for s,q in held.items() if q}==ending
        quantity_checks.append(dict(scenario=sid,status='PASS',daily_rebuilt_market_value_error=err,end_quantity_reconciled=True))
        bestyear=n.assign(year=n.date.str[:4]).groupby('year').return_daily.apply(lambda x:np.prod(1+x)-1).idxmax()
        submitted=o[o['limit'].notna()];js=np.array([m.sy[x[:6]] for x in submitted.symbol]);ts=submitted.t.to_numpy(int)
        violations=(submitted['limit'].to_numpy()>m.a['up_limit_price'][ts,js]+1e-8)|(submitted['limit'].to_numpy()<m.a['down_limit_price'][ts,js]-1e-8)
        assert np.isfinite(m.a['coord'][ts-1,js]).all(),sid
        expected_factor=m.a['coord'][ts-1,js]/((m.a['close'][ts-1,js]-m.a['cash_per_share'][ts,js])/m.a['share_multiplier'][ts,js])
        np.testing.assert_allclose(submitted.preopen_factor,expected_factor,rtol=1e-12,atol=1e-12)
        preopen.append(dict(scenario=sid,orders_with_price=len(submitted),prior_coordinate_unavailable=0,preopen_factor_reconstruction='PASS'))
        assert not violations.any(),sid
        buys=o[o.status=='FILLED']
        for r in buys.itertuples():
            board=m.boards[m.sy[r.symbol[:6]]];assert (200<=r.quantity<=100000) if board=='STAR' else (r.quantity%100==0 and 100<=r.quantity<=1000000)
            if s['mode']=='CAP10':
                prior=n.loc[n.t<r.t,'nav'];assert r.reserved<=(prior.iloc[-1] if len(prior) else 1e6)*.1+1e-7
        concentration.append(dict(scenario=sid,max_industry_NAV=max(icon),mean_largest_industry_NAV=np.mean(icon),max_unknown_industry_NAV=max(weight),cash_no_signal_daily_mean=n.cash_no_signal.mean(),cash_slots_daily_mean=n.cash_slots.mean(),best_year=bestyear,return_ex_best_year=np.prod(1+n.loc[~n.date.str.startswith(bestyear),'return_daily'])-1,illegal_submissions=int(violations.sum())))
        if len(tr):
            lots=tr.set_index('lot')
            for lot,g in a[a.type=='SELL_FILL'].groupby('lot'):
                if len(g)<2 or lot not in lots.index:continue
                start=pd.Timestamp(lots.loc[lot,'entry_date']);rates=[.2 if pd.Timestamp(day)<=start+pd.DateOffset(months=1) else .1 if pd.Timestamp(day)<=start+pd.DateOffset(years=1) else 0 for day in g.day]
                assert len(set(rates))==1,(sid,lot,'partial sale tax rate boundary requires allocation')
                partial.append(dict(scenario=sid,lot=lot,sell_dates='|'.join(g.day),tax_rate_changes=False))
            tr['board']=[m.boards[int(j)] for j in tr.j];tr['entry_gate']=[bool(m.a['market_gate'][int(t)-1]) for t in tr.signal_t]
            for column in ['board','entry_gate']:
                for cell,g in tr.groupby(column):slices.append(dict(scenario=sid,split=column,cell=cell,closed_trades=len(g),pnl=g.pnl.sum(),win_rate=(g.pnl>0).mean()))
        for archive in ['provisional_before_legal_submission','provisional_after_upper_cap','provisional_before_universe_correction','provisional_before_preopen_coordinate','provisional_before_industry_history_completeness']:
            prior=OUT/archive/sid
            if not (prior/'nav.parquet').exists():continue
            old=pd.read_parquet(prior/'nav.parquet');od=pd.read_parquet(prior/'orders.parquet')
            changed=[name for name in ['nav','trades','orders','audit','open_positions'] if sha(prior/(name+'.parquet'))!=sha(d/(name+'.parquet'))]
            corrections.append(dict(archive=archive,scenario=sid,changed_artifacts='|'.join(changed),nav_max_abs_delta=float((old.nav-n.nav).abs().max()),net_return_delta=(n.nav.iloc[-1]-old.nav.iloc[-1])/1e6,old_orders=len(od),new_orders=len(o)))
    for name,rows in [('share_flow_checks',quantity_checks),('concentration_and_cash',concentration),('order_statuses',statuses),('trade_slices',slices),('correction_effects',corrections),('fixed_interactions',interactions),('event_horizons',horizons),('candidate_funnel',funnel),('preopen_coordinate_checks',preopen),('partial_exit_tax_check',partial)]:pd.DataFrame(rows).to_csv(HERE/(name+'.csv'),index=False)
    print('SUPPLEMENT_COMPLETE',len(quantity_checks),'accounts',flush=True)
if __name__=='__main__':run()
