"""T+1 / e+10 open event clocks, legal standardized lots, and real account maps."""
import copy,json,math,time
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,ROUTES,fee,quantity,parquet,dump,log
from .engine import Market,replay

def event(m,r):
    t=int(r['t']);j=int(r['j']);e=t+1;n=len(m.dates)
    row={k:r[k] for k in ['t','j','symbol','route','score','setup_id','board','formation_t']}
    row.update(entry_t=e,year=m.dates[t][:4],date=m.dates[t],status='END_BOUNDARY',std_pnl=np.nan,net_return=np.nan,label_available_t=np.nan)
    if e>=n:return row
    fac=m.val('factor',e,j);limit=math.floor(r['limit']*r['factor']/fac*100+1e-8)/100 if fac>0 else np.nan
    up=m.val('up_limit_price',e,j);down=m.val('down_limit_price',e,j);limit=min(limit,up) if np.isfinite(up) else limit
    cap=m.capacity[e-1,j];q=quantity(min(1e5,cap+fee(cap,m.dates[e])),limit,m.dates[e],m.boards[j],maxq=cap/limit) if limit>0 and np.isfinite(cap) else 0
    reason=m.legal(e,j);op=m.val('open',e,j);price=math.ceil(op*1.0005*100-1e-8)/100 if np.isfinite(op) else np.nan
    known=all(pd.notna(x['known_at']) and x['known_at']<=pd.Timestamp(m.dates[e]) for x in m.exdates.get((r['symbol'][:6],m.dates[e]),[]))
    reason=reason or ('UNRESOLVED_PREOPEN_ACTION' if not known else 'FROZEN_LIMIT_BELOW_LEGAL_RANGE' if limit<down or limit<=0 else 'OVER_LIMIT' if price>limit or price>up else 'LOT_OR_CAPACITY' if not q else '')
    row['status']=reason or 'FILLED_UNMATURED';row['legal_fill']=not bool(reason)
    if reason:return row
    debit=q*price+fee(q*price,m.dates[e]);row.update(entry_price=price,std_quantity=q,std_debit=debit,below_structure=op<r['S0']*r['factor']/fac)
    x=e+10
    while x<n:
        px=math.floor(m.val('open',x,j)*.9995*100+1e-8)/100 if np.isfinite(m.val('open',x,j)) else np.nan
        if not m.legal(x,j,True) and px>=m.val('down_limit_price',x,j):break
        x+=1
    if x>=n:return row
    actions=m.action_records_by_symbol.get(r['symbol'][:6],[])
    affected=any(m.dates[e]<=d<=m.dates[x] for d in actions)
    if affected:
        # Rare entitlement cases reuse the unchanged one-lot engine, not a second tax model.
        end=min(n,x+80);mm=copy.copy(m);mm.dates=m.dates[t:end];mm.a={k:v[t:end] for k,v in m.a.items()};mm.state=m.state[t:end];mm.capacity=m.capacity[t:end]
        rr=dict(r,t=0);s=dict(id='EVENT_DIAGNOSTIC',delay=1,cost=1,mode='C_10',exit='FIXED10',overlay='NONE')
        try:nav,tr,*_=replay(mm,s,pd.DataFrame([rr]))
        except Exception as err:row['status']='ACTION_DIAGNOSTIC_BLOCKED';row['reason']=repr(err);return row
        if len(tr)!=1:row['status']='ACTION_LABEL_UNMATURED';return row
        actual=tr.iloc[0];x=int(actual.exit_t)+t;pnl=float(actual.pnl);debit=float(actual.entry_cash)
        row['std_debit']=debit;row['std_quantity']=actual.initial_q
    else:pnl=q*px-fee(q*px,m.dates[x],True)-debit
    coord_price=price*fac
    hh=m.a['high'][e:x,j]*m.a['factor'][e:x,j]/coord_price-1
    ll=m.a['low'][e:x,j]*m.a['factor'][e:x,j]/coord_price-1
    row.update(status='MATURED',exit_t=x,label_available_t=x,held_sessions=x-e,std_pnl=pnl,net_return=pnl/debit,
        quote_open_return=px*m.val('factor',x,j)/coord_price-1,mfe=float(np.nanmax(hh)),mae=float(np.nanmin(ll)),parent_age=t-int(r['formation_t']))
    return row

def aggregate(f,keys):
    rows=[]
    for key,g in f.groupby(keys,dropna=False):
        key=key if isinstance(key,tuple) else (key,);q=g[g.status=='MATURED'];daily=q.groupby('t').net_return.mean();p=q.std_pnl
        rows.append(dict(zip(keys,key),signals=len(g),signal_dates=g.t.nunique(),state_episodes=g.episode.nunique(),
            legal_fill_rate=g.legal_fill.fillna(False).mean(),matured=len(q),equal_date_return=daily.mean(),equal_event_return=q.net_return.mean(),
            standardized_pnl=p.sum(),win_rate=(p>0).mean() if len(p) else np.nan,profit_factor=p[p>0].sum()/-p[p<0].sum() if (p<0).any() else np.nan,
            tail_p05=q.net_return.quantile(.05),mfe=q.mfe.mean(),mae=q.mae.mean(),mean_held=q.held_sessions.mean(),
            actual_orders=g.actual_orders.sum(),actual_fills=g.actual_fills.sum(),cash_pnl_contribution=g.actual_pnl.sum(),
            actual_cash_rejections=g.actual_cash_rejections.sum(),state_rejected_by_simple_gate=int((g.state=='LOW_NONIMPROVING').sum())))
    return pd.DataFrame(rows)

def main():
    log('MAP_CLOCK','DIAGNOSTIC','V3 close-based event return and cash PNL used different clocks',
        '全十二入口统一T+1合法开盘、e+10下一合法开盘、10万元计划单笔与整手费用；公司行动复用引擎',
        'V3 quote diagnostics and unchanged actual accounts','定位事件/排序/现金及持有状态差异','时钟对齐后仍不能支持任何相对优势')
    m=Market();m.action_records_by_symbol={s:[str(x.date()) for x in g.record_date.dropna()] for s,g in m.actions.groupby('symbol')}
    state=pd.read_parquet(OUT/'state_daily.parquet');allrows=[];start=time.time()
    for route in ROUTES:
        dest=OUT/f'events_{route}.parquet'
        if dest.exists():f=pd.read_parquet(dest)
        else:
            src=OUT/'D09_corrected_signals.parquet' if route=='D09' else V3/f'{route}_signals.parquet'
            signals=pd.read_parquet(src);rows=[event(m,r) for r in signals.to_dict('records')];f=pd.DataFrame(rows);parquet(dest,f)
        allrows.append(f);print('MAP_EVENTS',route,len(f),f.status.value_counts().to_dict(),round(time.time()-start),flush=True)
    f=pd.concat(allrows,ignore_index=True);parquet(OUT/'event_cash_diagnostics.parquet',f)
    maps=[];years=[];boards=[];holdmaps=[]
    for mode in ['C_MAX','C_10']:
        for route in ROUTES:
            account=(OUT/'accounts'/f'FIX_A_D09_{mode}_E10') if route=='D09' else V3/f'A_{route}_{mode}_E10'
            orders=pd.read_parquet(account/'orders.parquet');tr=pd.read_parquet(account/'trades.parquet')
            g=f[f.route==route].copy();g['actual_orders']=0;g['actual_fills']=0;g['actual_pnl']=0.;g['actual_cash_rejections']=0
            od=orders.groupby(['signal_t','symbol']).agg(actual_orders=('status','size'),actual_fills=('status',lambda s:(s=='FILLED').sum()),actual_cash_rejections=('status',lambda s:s.isin(['NO_CASH','RISK_OR_CASH_OR_CAPACITY']).sum())).reset_index().rename(columns={'signal_t':'t'})
            if len(tr):od=od.merge(tr.groupby(['signal_t','symbol']).pnl.sum().rename('actual_pnl').reset_index().rename(columns={'signal_t':'t'}),on=['t','symbol'],how='left')
            g=g.drop(columns=[c for c in od if c not in ['t','symbol']]).merge(od,on=['t','symbol'],how='left');g[['actual_orders','actual_fills','actual_pnl','actual_cash_rejections']]=g[['actual_orders','actual_fills','actual_pnl','actual_cash_rejections']].fillna(0)
            for key in ['S0','S0_CURRENT','S1']:
                a=g.merge(state[['t',key,key+'_episode']],on='t');a['state']=a[key];a['episode']=a[key+'_episode'];a['state_definition']=key;a['capital']=mode
                maps.append(aggregate(a,['route','capital','state_definition','state']));years.append(aggregate(a,['route','capital','state_definition','state','year']));boards.append(aggregate(a,['route','capital','state_definition','state','board']))
            nav=pd.read_parquet(account/'nav.parquet');nav['pnl_daily']=nav.nav.diff().fillna(nav.nav.iloc[0]-1e6)
            nav['state']=state.S1.iloc[np.maximum(nav.t.to_numpy()-1,0)].to_numpy()
            h=nav.groupby('state').agg(days=('t','size'),cash_account_daily_pnl=('pnl_daily','sum'),mean_exposure=('exposure','mean')).reset_index();h['route']=route;h['capital']=mode;holdmaps.append(h)
    pd.concat(maps).to_csv(HERE/'strategy_state_map.csv',index=False);pd.concat(years).to_csv(HERE/'strategy_state_year.csv',index=False);pd.concat(boards).to_csv(HERE/'strategy_state_board.csv',index=False);pd.concat(holdmaps).to_csv(HERE/'holding_state_map.csv',index=False)
    dump(HERE/'map_status.json',dict(events=len(f),statuses=f.status.value_counts().to_dict(),standardized='100k intended legal-share single-event cash diagnostic; independent observation capital never pooled',actual='12 standalone cash accounts x two capital modes; D09 corrected'))

if __name__=='__main__':main()
