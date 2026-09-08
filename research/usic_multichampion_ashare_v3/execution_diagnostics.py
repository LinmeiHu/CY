"""Actual filled-lot diagnostics; common-clock Q3 comparisons and explicit capacity accounting."""
import json
import numpy as np
import pandas as pd
import duckdb
from .common import HERE,OUT,CACHE,sha,dump,parquet,scenarios
from .analyze import STATS

def main():
    ax=json.loads((CACHE/'axes.json').read_text());dates=ax['dates'];sy={s:i for i,s in enumerate(ax['symbols'])};a={p.stem:np.load(p,mmap_mode='r') for p in CACHE.glob('*.npy')};n=len(dates);fills=pd.read_parquet(STATS/'all_filled_buys.parquet');fills['j']=fills.symbol.map(sy);tail=fills[fills.entry_style=='TAIL'].copy();req=tail[['t','j','fill_clock']].drop_duplicates().copy();req['symbol']=[ax['symbols'][int(j)] for j in req.j];req['trade_date']=[dates[int(t)] for t in req.t];req['fill_clock']=req.fill_clock.astype(int);req['key']=np.arange(len(req));ext=[]
    for year in range(2020,2024):
        request=req[req.trade_date.str.startswith(str(year))].copy();request['symbol']=request.symbol.astype(object);request['trade_date']=request.trade_date.astype(object);src=f'/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars/{year}_day_parquet_none.parquet'
        with duckdb.connect() as con:
            con.execute('set threads=1');con.execute("set memory_limit='768MB'");con.register('requests',request)
            f=con.execute('''SELECT r.key,count(distinct s.bar_end_time) n_bars,max(s.high) post_high,min(s.low) post_low
              FROM read_parquet(?) s JOIN requests r ON s.qmt_code=r.symbol AND s.trade_date=r.trade_date::DATE
              WHERE extract(hour from s.bar_end_time)*60+extract(minute from s.bar_end_time)>r.fill_clock AND CAST(s.bar_end_time AS TIME)<=TIME '15:00:00'
              GROUP BY r.key''',[src]).fetchdf();ext.append(f)
    extrema=req.merge(pd.concat(ext),on='key',how='left');extrema['complete']=extrema.n_bars==900-extrema.fill_clock;parquet(STATS/'tail_post_entry_extrema.parquet',extrema)
    exmap={(int(r.t),int(r.j),int(r.fill_clock)):r for r in extrema.itertuples(index=False)};unique=fills[['t','j','fill','entry_style','fill_clock']].drop_duplicates() if 'fill_clock' in fills else fills[['t','j','fill','entry_style']].drop_duplicates();out=[]
    for r in unique.to_dict('records'):
        t=int(r['t']);j=int(r['j']);price=r['fill'];fac=a['factor'][t,j];entrycoord=price*fac;end=min(t+41,n);hh=a['high'][t:end,j]*a['factor'][t:end,j];ll=a['low'][t:end,j]*a['factor'][t:end,j];complete=True
        if r['entry_style']=='TAIL':
            ex=exmap[(t,j,int(r['fill_clock']))];complete=bool(ex.complete);hh[0]=ex.post_high*fac if complete else np.nan;ll[0]=ex.post_low*fac if complete else np.nan
        row=dict(r,first_day_range_complete=complete,mfe40=float(np.nanmax(hh)/entrycoord-1),mae40=float(np.nanmin(ll)/entrycoord-1),forward40_censored=end<t+41)
        for h in [1,3,5,10,20,40]:row[f'price_return_{h}']=a['coord'][t+h,j]/entrycoord-1 if t+h<n and np.isfinite(a['coord'][t:t+h+1,j]).all() else np.nan
        neg=np.flatnonzero(a['coord'][t:end,j]<entrycoord);row['first_adverse_close_session']=int(neg[0]) if len(neg) else None;out.append(row)
    diag=pd.DataFrame(out);parquet(STATS/'actual_filled_forward_diagnostics.parquet',diag)
    keys=['t','j','fill','entry_style','fill_clock'];joined=fills.merge(diag,on=keys,how='left',validate='many_to_one');parquet(STATS/'actual_filled_diagnostics_by_account.parquet',joined)
    joined.groupby('id').agg(filled_lots=('t','size'),mfe40_mean=('mfe40','mean'),mae40_mean=('mae40','mean'),r1_mean=('price_return_1','mean'),r3_mean=('price_return_3','mean'),r5_mean=('price_return_5','mean'),r10_mean=('price_return_10','mean'),r20_mean=('price_return_20','mean'),r40_mean=('price_return_40','mean'),first_adverse_mean=('first_adverse_close_session','mean')).to_csv(STATS/'actual_entry_summary.csv')
    # All 14:25 Q3 signals remain in each coverage table, including absent/unfilled orders.
    qs=pd.read_parquet(OUT/'Q3_signals.parquet');paired=[]
    for mode in ['C_MAX','C_10','C_ONE']:
        for exit in ['E10','EST']:
            records=qs[['setup_id','t','j','symbol']].copy();records['capital']=mode;records['exit']=exit
            for arm in ['BASE','ENHANCED']:
                sid=f'Q3_{arm}_{mode}_{exit}';f=pd.read_parquet(OUT/sid/'orders.parquet');f=f[f.setup_id.notna()].drop_duplicates('setup_id')
                f=f[['setup_id','status','t','fill']].rename(columns={'status':arm+'_status','t':arm+'_entry_t','fill':arm+'_fill'});records=records.merge(f,on='setup_id',how='left',validate='one_to_one')
                rr=[]
                for r in records.to_dict('records'):
                    j=int(r['j']);end=int(r['t'])+11;e=r.get(arm+'_entry_t');px=r.get(arm+'_fill');rr.append(a['coord'][end,j]/(px*a['factor'][int(e),j])-1 if r.get(arm+'_status')=='FILLED' and end<n else np.nan)
                records[arm+'_common_clock_return']=rr
            paired.append(records)
    qpair=pd.concat(paired,ignore_index=True);qpair['difference']=qpair.ENHANCED_common_clock_return-qpair.BASE_common_clock_return;parquet(STATS/'q3_all_signals_common_clock.parquet',qpair);qpair.groupby(['capital','exit']).agg(all_signals=('t','size'),both_filled=('difference','count'),mean_difference=('difference','mean'),base_mean=('BASE_common_clock_return','mean'),tail_mean=('ENHANCED_common_clock_return','mean')).to_csv(STATS/'q3_common_clock_summary.csv')
    cap=[];add=[]
    for sid,g in fills.groupby('id'):
        used=[]
        for (t,j),gg in g.groupby(['t','j']):
            t=int(t);j=int(j);capacity=np.median(a['amount'][t-20:t,j])*.005;nom=(gg.quantity*gg['limit']).sum();assert nom<=capacity+1e-5,(sid,t,j,nom,capacity);used.append(nom/capacity)
        cap.append(dict(id=sid,filled_orders=len(g),max_prior_daily_cap_usage=max(used,default=0),median_prior_daily_cap_usage=float(np.median(used)) if used else None,shared_stock_day_cap_pass=True))
        if sid.endswith('R_STAGE'):
            tr=pd.read_parquet(OUT/sid/'trades.parquet');aud=pd.read_parquet(OUT/sid/'audit.parquet');added=tr[tr.added] if len(tr) else tr
            ca=set(aud.loc[aud.type=='RECORD_ENTITLEMENT','lot']) if len(aud) and 'lot' in aud else set();assert not any(r in ca for r in added.lot),'Need explicit CA component allocation before attribution'
            add.append(dict(id=sid,initial_fills=len(g)-int(g.get('is_add',pd.Series(False,index=g.index)).fillna(False).astype(bool).sum()),add_fills=int(g.get('is_add',pd.Series(False,index=g.index)).fillna(False).astype(bool).sum()),closed_added_trades=len(added),add_gross_price_pnl=float(added.add_pnl.sum()) if len(added) else 0,total_added_position_net_pnl=float(added.pnl.sum()) if len(added) else 0,all_net_pnl=float(tr.pnl.sum()) if len(tr) else 0,add_tail_worst=float(added.add_pnl.min()) if len(added) else None,attribution_note='Add gross price component excludes its fees; net whole-position PnL remains exact; no added trade crosses a corporate-action entitlement'))
    pd.DataFrame(cap).to_csv(STATS/'capacity_check.csv',index=False);pd.DataFrame(add).to_csv(STATS/'stage_add_attribution.csv',index=False)
    # Whole-event known_at includes the trigger. Preserve inherited background timestamps separately.
    sig=pd.concat([pd.read_parquet(OUT/f'{r}_signals.parquet') for r in [f'D{i:02d}' for i in range(10)]+['H01','H02']],ignore_index=True);timeline=sig[['route','symbol','t','j','setup_id','formation_t','known_at','decision_at','expiry_t','S0','limit','factor']].rename(columns={'known_at':'background_known_at'});timeline['known_at']=timeline.decision_at;timeline['confirmation_at']=timeline.decision_at;timeline['formation_at']=[dates[int(t)]+'T15:00:00+08:00' for t in timeline.formation_t];timeline['formation_known_at']=timeline.background_known_at;timeline['anchor_session']=timeline.formation_t;timeline['entry_earliest_at']=[dates[int(t)+1]+'T09:30:00+08:00' if int(t)+1<n else None for t in timeline.t];parquet(STATS/'canonical_signal_timeline.parquet',timeline)
    sample=pd.concat([timeline.groupby('route').head(2),timeline.sample(24,random_state=20260908)]).drop_duplicates('setup_id');sample.to_csv(HERE/'decision_timeline_samples.csv',index=False)
    dump(HERE/'EXECUTION_DIAGNOSTIC_MANIFEST.json',dict(filled_rows=len(fills),unique_fill_diagnostics=len(diag),tail_ranges=len(extrema),tail_complete_ranges=int(extrema.complete.sum()),all_capacity_pass=True,gross_quote_diagnostic_not_net_account_pnl=True,files={str(p):sha(p) for p in [STATS/'actual_filled_forward_diagnostics.parquet',STATS/'q3_all_signals_common_clock.parquet',STATS/'capacity_check.csv',STATS/'stage_add_attribution.csv',STATS/'canonical_signal_timeline.parquet']}))
    print('EXECUTION_DIAGNOSTICS_COMPLETE',len(fills),len(diag),flush=True)
if __name__=='__main__':main()
