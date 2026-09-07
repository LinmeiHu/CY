"""Fixed exit closure: source callbacks, four overlays, existing stock accounts.

No frozen strategy edits, golden production inputs, parameter searches or new periods.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
ROOT = PARENT.parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(PARENT))
import state_v2 as st
from smv6_v2 import AuditedPlatform, load_platform
from five_strategy_bundle.strategies import smv6

PERIODS = {'EARLY_2013_2017': ('2013-04-01','2017-12-31'),
           '2018_2021': ('2018-01-01','2021-12-31'),
           '2022_2023': ('2022-01-01','2023-12-31'),
           'ALL_AUTHORIZED': ('2013-04-01','2023-12-31')}
EVIDENCE = 'ALREADY_CONSUMED_HISTORY_NOT_INDEPENDENT_VALIDATION'

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()

def write_json(p,d):
    Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,default=str)+'\n')

def log(msg):
    print(datetime.now(timezone.utc).isoformat(),msg,flush=True)

def prepare(out, reference):
    """Snapshot only authorized raw rows; runtime has no other-worktree dependency."""
    assert Path('/Volumes/quant').is_mount()
    out.mkdir(parents=True,exist_ok=True)
    old=json.loads((PARENT/'input_config.json').read_text())
    inputs=[]
    cfg={'external_root':str(out),'inputs':{},'reference_root':str(out/'reference'),
         'stock_root':str(Path(old['external_root']).parent/'20260907_visual_v1_01/risk_preference_review'),
         'old_root':old['external_root'],'start_head':'bd0dc4d1e2b9f1a7bc6513de4a1b87f0a998c8a3'}
    for key,parts in [('smv6_qmt_root','daily'),('smv6_hybrid_root','minute_critical')]:
        target=out/'inputs'/key;cfg['inputs'][key]=str(target)
        for symbol in [smv6.canonical_symbol(s) for s in smv6.raw_pool()]+['000852.SH']:
            tail=Path(parts)/f'symbol={symbol}'/('daily.parquet' if parts=='daily' else 'critical.parquet')
            src=Path(old['inputs'][key])/tail;dest=target/tail;dest.parent.mkdir(parents=True,exist_ok=True)
            before=sha(src);d=st.read_bound(src,"trade_date<=DATE '2023-12-31'")
            d.to_parquet(dest,index=False)
            inputs.append(dict(source=str(src),source_sha256=before,path=str(dest),sha256=sha(dest),rows=len(d),role='BOUNDED_RAW_INPUT'))
    tail=Path('execution_availability/critical_execution.parquet')
    src=Path(old['inputs']['smv6_hybrid_root'])/tail;dest=Path(cfg['inputs']['smv6_hybrid_root'])/tail
    dest.parent.mkdir(parents=True,exist_ok=True)
    d=st.read_bound(src,"trade_date<=DATE '2023-12-31'");d.to_parquet(dest,index=False)
    inputs.append(dict(source=str(src),source_sha256=sha(src),path=str(dest),sha256=sha(dest),rows=len(d),role='BOUNDED_RAW_INPUT'))
    ref=Path(cfg['reference_root']);ref.mkdir(exist_ok=True)
    meta=json.loads((reference/'result.json').read_text())
    assert meta['counts']==dict(strategy_events=779,local_execution_events=1081,nav=3260)
    write_json(ref/'result.json',meta)
    for name in ['events','local_execution_events','nav']:
        src=reference/(name+'.parquet');dest=ref/(name+'.parquet')
        st.read_bound(src,"trade_date<=DATE '2023-12-31'").to_parquet(dest,index=False)
        inputs.append(dict(source=str(src),source_sha256=sha(src),path=str(dest),sha256=sha(dest),role='REFERENCE_ONLY_NOT_PRODUCTION_INPUT'))
    # Hash frozen code and all already sealed research inputs before new replay.
    seals=json.loads((PARENT/'visual_v1/completion_manifest.json').read_text())
    protected=[]
    for base in [ROOT/'src',ROOT/'configs/frozen']:
        for p in sorted(base.rglob('*')):
            if p.is_file() and '__pycache__' not in str(p): protected.append(dict(path=str(p),sha256=sha(p)))
    for p in sorted(PARENT.iterdir()):
        if p.is_file() and p.name!='smv6_exit_candidate_contract.json': protected.append(dict(path=str(p),sha256=sha(p)))
    cfg['contract_sha256']=sha(HERE/'smv6_exit_candidate_contract.json')
    write_json(HERE/'input_manifest.json',dict(config=cfg,inputs=inputs,protected=protected,
        authority_counts=meta['counts'],full_reference_interval='2013-04-01..2026-08-28 (metadata only; results after 2023 not read)',
        rejected_stale_reference='five_strategy_standalone_v4/smv6_integrated_full:769 events',
        code_origin_commit='40d924ca718be40c6e891a64b3a9cac7f8d58f95',evidence=EVIDENCE))
    write_json(HERE/'run_config.json',cfg)
    log('Prepared bounded input snapshot and authoritative reference prefix')

class OverlayPlatform(AuditedPlatform):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.policy=None;self.context=None;self.pending={};self.suppressed=set()
        self.risk_order=False;self.volume_used={};self.signals=[];self.day_state=[]
        self.feature_daily={}
        calendar_index={t:i for i,t in enumerate(self.calendar)}
        for symbol,d in self.daily.items():
            f=d.reset_index().rename(columns={f'pre_adj_{x}':f'coord_{x}' for x in ['open','high','low','close']})
            f['cal_idx']=f.trade_date.map(calendar_index)
            f=f.loc[f.cal_idx.notna()].copy()
            valid=f.row_status.eq('VALID')&np.isfinite(f[['coord_open','coord_high','coord_low','coord_close']]).all(axis=1)
            f['invalid_step_cum']=0
            for x in ['hard_valid','history_valid','current_valid']:f[x]=valid
            f['volume']=f.volume_raw
            self.feature_daily[symbol]=f

    def _volume_cap(self,symbol,role):
        cap=super()._volume_cap(symbol,role)
        return max(0,cap-self.volume_used.get((self.current_date,symbol,role),0)) if self.policy else cap

    def _record(self,event_type,symbol,**kwargs):
        context=self.context
        reason=('RISK_'+self.policy['candidate_id'] if self.risk_order else
                (getattr(context,'pending_reason','') if self.event_stage=='open' else getattr(context,'pending_close_reason','')))
        signal=self.pending.get(symbol,{})
        super()._record(event_type,symbol,execution_reason=reason,risk_order=self.risk_order,
                        risk_trigger_at=signal.get('trigger_at'),**kwargs)
        delta=float(kwargs.get('filled_delta_qty',0))
        if delta:
            role='OPEN_BAR_09_30' if self.event_stage=='open' else 'FINAL_CLOSE_BAR'
            key=(self.current_date,symbol,role)
            self.volume_used[key]=self.volume_used.get(key,0)+abs(delta)
        if self.fill_states:
            last=self.fill_states[-1]
            assert last['cash']>=-1e-8
            if np.isfinite(last['nav']):assert last['gross_ratio']<=1+1e-10

    def order_target_percent(self,symbol,target_weight):
        if self.policy and symbol in self.suppressed:
            self._record('OVERLAY_PENDING_BUY_SUPPRESSED',symbol,price=self._mark(symbol,'open'))
            return None
        return super().order_target_percent(symbol,target_weight)

    def risk_open(self):
        for symbol in list(self.pending):
            if symbol not in self.shares:self.pending.pop(symbol);continue
            if self.current_date<=self.positions[symbol].entry_date:continue
            row=self._current_row(symbol)
            price=self._minute_price(symbol,'OPEN_BAR_09_30','pre_adj_close')
            if row is None or not bool(row.executable_09_30) or not np.isfinite(price) or price<=0:
                self._record('RISK_SELL_NO_FILL',symbol,price=price,reject_reason='NO_LEGAL_COMPLETED_OPEN_BAR');continue
            self.risk_order=True
            self.order_target(symbol,0)
            self.risk_order=False
            if symbol not in self.shares:self.pending.pop(symbol)

    def completed_features(self,symbol):
        pos=self.positions[symbol];today=pd.Timestamp(self.current_date);entry=pd.Timestamp(pos.entry_date)
        d=self.feature_daily[symbol];held=d.loc[d.trade_date.between(entry,today)]
        if held.empty or held.iloc[-1].trade_date!=today or not bool(held.iloc[-1].current_valid):return None
        # Do not infer MFE through a missing held-day observation.
        if not held.current_valid.all():return None
        atr=st.entry_atr(d,entry,0)
        trade=pd.Series(dict(entry_price=pos.entry_price,entry_cal_idx=held.iloc[0].cal_idx,horizon=20,
                             entry_time=entry+pd.Timedelta(hours=9,minutes=30)))
        return st.causal_features(held,trade,atr).iloc[[-1]]

    def latch(self):
        for symbol in list(self.shares):
            f=self.completed_features(symbol)
            if f is None:continue
            self.day_state.append(dict(symbol=symbol,trade_date=self.current_date,entry_date=self.positions[symbol].entry_date,
                                      **f.iloc[0][['current_pnl','mfe_sofar','mae_sofar','atr_entry_frac']].to_dict()))
            if self.policy and symbol not in self.pending and bool(st.policy_mask(f,self.policy['family'],self.policy['value']).iloc[0]):
                row=dict(symbol=symbol,trigger_at=pd.Timestamp(self.current_date)+pd.Timedelta(hours=16),
                         entry_date=self.positions[symbol].entry_date,**f.iloc[0][['current_pnl','mfe_sofar','atr_entry_frac']].to_dict())
                self.pending[symbol]=row;self.signals.append(row)

def replay(platform,calendar,policy=None):
    """Frozen driver order; insert risk sells after native sells and before new buys."""
    platform.policy=policy
    ns=smv6.frozen_namespace(platform)
    context=SimpleNamespace(portfolio=SimpleNamespace(stock_account=SimpleNamespace(positions=platform.positions)))
    platform.context=context;ns['init'](context)
    for t in calendar:
        platform.current_date=t.date();platform.event_stage='before_trading'
        prior=set(platform.positions);ns['before_trading'](context)
        smv6.record_pending_signals(platform,context,prior)
        platform.pending={s:v for s,v in platform.pending.items() if s in platform.shares}
        platform.event_stage='open';platform.suppressed=set(platform.pending)
        # Native callback sells before buys. A hook at its first target-percent call
        # runs risk exits after native sells; if no buys, run them after callback.
        done=False
        def target(symbol,weight):
            nonlocal done
            if not done:platform.risk_open();done=True
            return platform.order_target_percent(symbol,weight)
        ns['order_target_percent']=target
        ns['execute_pending_open'](context,platform.bar_dict(),'LOCAL_09_30')
        if not done:platform.risk_open()
        platform.event_stage='signal'
        ns['run_1457_exit_signal'](context,platform.bar_dict(include_signal=True))
        for symbol in context.pending_close_sells:
            platform._record('TAIL_SELL_SIGNAL',symbol,price=platform._minute_price(symbol,'PSEUDO_CLOSE_14_57_OPEN','pre_adj_open'),reason=context.pending_close_reason)
        platform.event_stage='close'
        ns['execute_pending_close_sells'](context,platform.bar_dict(include_close=True))
        platform.record_account();platform.latch()
    return pd.DataFrame(platform.events),pd.DataFrame(platform.accounts)

def episodes(p,events,calendar):
    active={};rows=[];fills=[];indices={x.date():i for i,x in enumerate(calendar)}
    for e in events.sort_values('event_sequence').to_dict('records'):
        delta=e.get('filled_delta_qty',np.nan)
        if not np.isfinite(delta) or delta==0:continue
        s=e['symbol'];day=pd.Timestamp(e['trade_date']);price=e['price_pre_adj'];fee=e['fee']
        if s not in active:
            assert delta>0
            active[s]=dict(episode_id=f'{s}|{day.date()}',symbol=s,entry_date=day,entry_price=price,
                entry_reason=e.get('execution_reason',''),buy_outlay=0.,sale_proceeds=0.,transaction_cost=0.,slippage_cost=0.,qty=0)
        a=active[s];a['transaction_cost']+=fee
        a['slippage_cost']+=abs(delta)*abs(price-e['market_price'])
        a['qty']+=delta
        if delta>0:a['buy_outlay']+=delta*price+fee
        else:a['sale_proceeds']+=-delta*price-fee
        fills.append(dict(episode_id=a['episode_id'],trade_date=day,symbol=s,delta_qty=delta,
             gross_value=abs(delta)*price,commission=fee,slippage=abs(delta)*abs(price-e['market_price']),stage=e['stage']))
        if a['qty']==0:
            a.update(exit_date=day,exit_stage=e['stage'],exit_price=price,exit_reason=e.get('execution_reason',''),
                     net_return=a['sale_proceeds']/a['buy_outlay']-1,pnl=a['sale_proceeds']-a['buy_outlay'],right_censored=False)
            rows.append(a);active.pop(s)
    for a in active.values():
        a.update(exit_date=pd.NaT,exit_stage='',exit_price=np.nan,exit_reason='RIGHT_CENSORED',net_return=np.nan,pnl=np.nan,right_censored=True)
        rows.append(a)
    inv=pd.DataFrame(p.inventory)
    for a in rows:
        end=calendar[-1] if a['right_censored'] else a['exit_date']
        a['holding_days']=indices[end.date()]-indices[a['entry_date'].date()]
        a['calendar_holding_days']=(end-a['entry_date']).days
        d=p.feature_daily[a['symbol']]
        last=end if a['right_censored'] or a['exit_stage']=='close' else end-pd.Timedelta(days=1)
        path=d.loc[d.trade_date.between(a['entry_date'],last)]
        values_hi=list(path.coord_high.dropna()/a['entry_price']-1)
        values_lo=list(path.coord_low.dropna()/a['entry_price']-1)
        if not a['right_censored']:
            values_hi.append(a['exit_price']/a['entry_price']-1);values_lo.append(values_hi[-1])
        a['MFE']=max([0.]+values_hi);a['MAE']=min([0.]+values_lo)
        a['peak_giveback']=a['MFE']-(a['exit_price']/a['entry_price']-1) if not a['right_censored'] else np.nan
        a['post_MFE_giveback']=a['peak_giveback']
        peak=path.loc[path.coord_high.idxmax()] if len(path) and path.coord_high.notna().any() else None
        a['time_to_MFE']=indices[peak.trade_date.date()]-indices[a['entry_date'].date()] if peak is not None else np.nan
        atr=st.entry_atr(d,a['entry_date'],0);a['entry_ATR']=atr
        a['max_adverse_ATR']=-a['MAE']*a['entry_price']/atr if np.isfinite(atr) and atr>0 else np.nan
        prev=d.coord_close.shift(1);gaps=(d.coord_open-prev)/a['entry_price']
        a['overnight_gap_contribution']=gaps.loc[d.trade_date.gt(a['entry_date'])&d.trade_date.le(end)].sum(min_count=1)
        occupied=inv.loc[inv.symbol.eq(a['symbol'])&inv.entry_date.eq(a['entry_date'])]
        a['capital_occupied']=a['buy_outlay'];a['capital_days']=(occupied.qty*occupied.price).sum(min_count=1)
        a['state']='ORIGINAL_CALLBACK_REASON_RECORDED; no new market classifier'
        a['anatomy_caveat']='First-fill price excursion; cash-weighted episode return includes rebalances; intraday exit day extremes excluded; gap sum is path arithmetic, not additive cash attribution'
    return pd.DataFrame(rows),pd.DataFrame(fills)

def account_metrics(nav,start,end,initial=1.):
    n=nav.copy();n['trade_date']=pd.to_datetime(n.trade_date);n=n.sort_values('trade_date').set_index('trade_date')
    prior=n.loc[n.index<pd.Timestamp(start),'nav'];base=float(prior.iloc[-1]) if len(prior) else initial
    g=n.loc[start:end].copy();q=g.nav/base
    missing=int(q.isna().sum())
    if missing:
        # Endpoints identify total return/CAGR even when path-dependent risk is unknown.
        return dict(days=len(g),missing_nav_days=missing,metric_status='PARTIAL_PATH_METRICS_NOT_ESTIMABLE',base_nav=base,
            total_return=float(q.iloc[-1]-1),CAGR=float(q.iloc[-1]**(365.25/((pd.Timestamp(end)-pd.Timestamp(start)).days+1))-1),
            start=str(g.index[0].date()),end=str(g.index[-1].date()))
    r=q.pct_change(fill_method=None);r.iloc[0]=q.iloc[0]-1
    dd=q/np.maximum(1.,q.cummax())-1
    duration=longest=0
    for v in dd:
        duration=duration+1 if v<-1e-12 else 0;longest=max(longest,duration)
    trough=int(np.argmin(dd.values));recovery=np.flatnonzero(dd.iloc[trough+1:].ge(-1e-12).values)
    recovery_days=int(recovery[0]+1) if len(recovery) else np.nan
    tail=r.nsmallest(max(1,int(np.ceil(.05*len(r)))))
    result=dict(days=len(g),missing_nav_days=0,metric_status='OK',start=str(g.index[0].date()),end=str(g.index[-1].date()),
        total_return=float(q.iloc[-1]-1),CAGR=float(q.iloc[-1]**(365.25/((pd.Timestamp(end)-pd.Timestamp(start)).days+1))-1),
        MaxDD=float(-dd.min()),CVaR5=float(tail.mean()),worst_21day=float(((1+r).rolling(21).apply(np.prod,raw=True)-1).min()),
        worst_month=float(r.groupby(r.index.to_period('M')).apply(lambda x:(1+x).prod()-1).min()),
        worst_quarter=float(r.groupby(r.index.to_period('Q')).apply(lambda x:(1+x).prod()-1).min()),
        longest_drawdown_days=longest,recovery_days=recovery_days,recovery_censored=not bool(len(recovery)),
        Sharpe=float(r.mean()/r.std(ddof=1)*np.sqrt(252)) if r.std(ddof=1)>0 else np.nan,
        avg_gross_exposure=float((g.gross_exposure/g.nav).mean()),avg_cash=float((g.cash/g.nav).mean()),
        capital_days=float((g.gross_exposure/base).sum()),base_nav=base)
    return result

def smv_metrics(p,nav,trades,fills,base_trades,candidate):
    result=[];holding=[];added=[]
    ids=set(base_trades.episode_id)
    common=trades.merge(base_trades[['episode_id','exit_date','holding_days']],on='episode_id',suffixes=('','_native'))
    for period,(start,end) in PERIODS.items():
        m=account_metrics(nav,start,end,1e6)
        t=trades.loc[trades.entry_date.between(start,end)].copy()
        t['right_censored']=t.right_censored|t.exit_date.gt(end)
        b=base_trades.loc[base_trades.entry_date.between(start,end)]
        closed=t.loc[~t.right_censored];c=common.loc[common.entry_date.between(start,end)&common.exit_date.le(end)&common.exit_date_native.le(end)]
        f=fills.loc[fills.trade_date.between(start,end)]
        new=t.loc[~t.episode_id.isin(ids)].copy()
        for row in new.to_dict('records'):added.append(dict(candidate=candidate,period=period,**row))
        base=m.get('base_nav',1e6)
        extras=dict(candidate=candidate,period=period,evidence=EVIDENCE,account_reset=False,native_trades=len(b),trades=len(t),
            carried_in_positions=int((trades.entry_date.lt(start)&(trades.exit_date.ge(start)|trades.exit_date.isna())).sum()),
            open_at_end_positions=int((trades.entry_date.le(end)&(trades.exit_date.gt(end)|trades.exit_date.isna())).sum()),
            closed_trades=len(closed),right_censored=int(t.right_censored.sum()),added_trades=len(new),
            early_exits=int(c.exit_date.lt(c.exit_date_native).sum()),worst_trade=closed.net_return.min(),
            severe_loss_rate=closed.net_return.le(-.10).mean(),loss5_rate=closed.net_return.le(-.05).mean(),
            avg_holding_days=closed.holding_days.mean(),capital_weighted_holding_days=np.average(closed.holding_days,weights=closed.buy_outlay) if len(closed) else np.nan,
            common_holding_days=c.holding_days.mean(),common_native_holding_days=c.holding_days_native.mean(),
            turnover=f.gross_value.sum()/base,costs=(f.commission.sum()+f.slippage.sum())/base,
            commission=f.commission.sum()/base,slippage=f.slippage.sum()/base,
            added_trade_realized_pnl=new.loc[~new.right_censored,'pnl'].sum()/base,added_trade_censored=int(new.right_censored.sum()),
            released_capital_attribution='ACCOUNT_FEEDBACK_ASSOCIATION_NOT_PURE_CAUSAL_CASH_LABEL',cost_contract='2bp commission +8bp/side slippage;100 shares;minute50%')
        result.append(dict(**m,**extras));holding.append({k:v for k,v in extras.items() if 'holding' in k or k in ['candidate','period','trades','closed_trades','right_censored']})
    return result,holding,added

def run_smv(cfg,repeat=False):
    out=Path(cfg['external_root']);contract=json.loads((HERE/'smv6_exit_candidate_contract.json').read_text())
    assert sha(HERE/'smv6_exit_candidate_contract.json')==cfg['contract_sha256']
    assert sha(PARENT/'smv6_exit_candidate_contract.json')==cfg['contract_sha256']
    write_json(out/('repeat_started.json' if repeat else 'replay_started.json'),dict(time=datetime.now(timezone.utc).isoformat(),contract_sha256=cfg['contract_sha256']))
    allrows=[];allhold=[];allnew=[];hashes={};native=None
    for policy in [None]+contract['candidates']:
        name=policy['candidate_id'] if policy else 'NATIVE'
        log('SMV6 '+name+(' deterministic repeat' if repeat else ''))
        p,calendar=load_platform(cfg,OverlayPlatform)
        e,n=replay(p,calendar,policy);t,f=episodes(p,e,calendar)
        if policy is None:
            native=t
        if policy is None and not repeat:
            # Separate source-generated golden test; never feed reference events to execution.
            shadow=smv6.ShadowPlatform(p.daily,{s:smv6.load_minute(Path(cfg['inputs']['smv6_hybrid_root']),s) for s in p.daily},
                st.read_bound(Path(cfg['inputs']['smv6_hybrid_root'])/'execution_availability/critical_execution.parquet'),calendar)
            # Loader stores date objects for availability.
            shadow.availability=p.availability
            generated,_=smv6._run_callbacks(shadow,calendar,account=False)
            ref=Path(cfg['reference_root'])
            g=pd.read_parquet(ref/'events.parquet')
            keys=['trade_date','symbol','event_type','stage']
            for x in [generated,g]:x['trade_date']=pd.to_datetime(x.trade_date)
            pd.testing.assert_frame_equal(generated[keys].reset_index(drop=True),g[keys].reset_index(drop=True),check_dtype=False)
            rn=pd.read_parquet(ref/'nav.parquet')
            for x in [n,rn]:x['trade_date']=pd.to_datetime(x.trade_date)
            pd.testing.assert_frame_equal(n,rn,check_dtype=False,atol=1e-8,rtol=1e-12)
            if not repeat:write_json(HERE/'baseline_identity.json',dict(full_sealed_strategy_events=779,full_sealed_account_days=3260,
                authorized_prefix_strategy_events=len(generated),authorized_prefix_days=len(n),source_generated_prefix_matches=True,
                native_nav_matches_authoritative_prefix=True,missing_nav_dates=n.loc[n.nav.isna(),'trade_date'].astype(str).tolist(),
                reference_used_only_after_production_replay=True))
        frames={'events':e,'nav':n,'trades':t,'fills':f,'inventory':pd.DataFrame(p.inventory),'event_states':pd.DataFrame(p.fill_states),'signals':pd.DataFrame(p.signals)}
        for kind,frame in frames.items():
            # CSV canonical bytes verify logical values independent of parquet metadata.
            digest=hashlib.sha256(frame.to_csv(index=False,float_format='%.12g').encode()).hexdigest();hashes[f'{name}_{kind}']=digest
            if not repeat:frame.to_parquet(out/f'SMV6_{name}_{kind}.parquet',index=False)
        rows,hold,new=smv_metrics(p,n,t,f,native,name);allrows+=rows;allhold+=hold;allnew+=new
        if policy is None and not repeat:t.to_csv(HERE/'smv6_native_trade_anatomy.csv',index=False)
    if repeat:
        first=json.loads((out/'core_hashes.json').read_text());assert hashes==first
        write_json(HERE/'determinism.json',dict(status='PASS',core_outputs=len(hashes),all_hashes=hashes))
    else:
        write_json(out/'core_hashes.json',hashes)
        pd.DataFrame(allrows).to_csv(HERE/'smv6_account_comparison.csv',index=False)
        pd.DataFrame(allrows).to_csv(HERE/'smv6_candidate_trade_comparison.csv',index=False)
        pd.DataFrame(allhold).to_csv(HERE/'smv6_holding_duration.csv',index=False)
        pd.DataFrame(allnew).to_csv(HERE/'smv6_released_capital_trades.csv',index=False)

def summarize(cfg):
    """Refresh endpoint/cohort statistics from completed accounts, without new replays."""
    out=Path(cfg['external_root']);rows=[];holding=[];added=[]
    native=pd.read_parquet(out/'SMV6_NATIVE_trades.parquet')
    names=['NATIVE']+[x['candidate_id'] for x in json.loads((HERE/'smv6_exit_candidate_contract.json').read_text())['candidates']]
    for name in names:
        n,t,f=[pd.read_parquet(out/f'SMV6_{name}_{kind}.parquet') for kind in ['nav','trades','fills']]
        r,h,a=smv_metrics(None,n,t,f,native,name);rows+=r;holding+=h;added+=a
    for name,data in [('smv6_account_comparison',rows),('smv6_candidate_trade_comparison',rows),('smv6_holding_duration',holding),('smv6_released_capital_trades',added)]:
        pd.DataFrame(data).to_csv(HERE/(name+'.csv'),index=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','smv','repeat','summarize']);parser.add_argument('--output-root',type=Path)
    parser.add_argument('--reference-root',type=Path);args=parser.parse_args()
    if args.action=='prepare':prepare(args.output_root,args.reference_root)
    elif args.action=='summarize':summarize(json.loads((HERE/'run_config.json').read_text()))
    else:run_smv(json.loads((HERE/'run_config.json').read_text()),repeat=args.action=='repeat')
