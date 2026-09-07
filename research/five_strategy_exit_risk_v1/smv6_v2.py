"""Actual frozen SMV6 callbacks, event inventory and residual decision values."""
from __future__ import annotations
from pathlib import Path
import json
import math
import numpy as np
import pandas as pd
from state_v2 import read_bound, HERE, write_json, BASE, EXTRA
from five_strategy_bundle.strategies.smv6 import CashPlatform, raw_pool, canonical_symbol, _run_callbacks


def event_time(row):
    return pd.Timestamp(row['trade_date'])+pd.Timedelta(hours=9,minutes=30) if row['stage']=='open' else pd.Timestamp(row['trade_date'])+pd.Timedelta(hours=15)


def inventory_exit(platform,symbol,quantity,day,calendar,native_events):
    """Latched next-open exits; already scheduled native closes may finish sooner."""
    remaining=float(quantity);cash=0.;completed=pd.NaT;failed=partial=0
    close_days=set(pd.to_datetime(native_events.loc[native_events.stage.eq('close')&native_events.event_type.isin(['SELL_PARTIAL','SELL_FILLED']),'trade_date']))
    for date in calendar:
        if date<=day:continue
        av=platform.availability.get((date.date(),symbol))
        stages=[('OPEN_BAR_09_30','executable_09_30',pd.Timedelta(hours=9,minutes=30))]
        if date in close_days:stages.append(('FINAL_CLOSE_BAR','executable_15_00',pd.Timedelta(hours=15)))
        for role,field,offset in stages:
            bar=platform.minute_rows[symbol].get((date.date(),role))
            if av is None or not bool(getattr(av,field)) or bar is None:failed+=1;continue
            cap=math.floor(bar[2]*platform.minute_volume_limit/platform.lot_size)*platform.lot_size
            qty=min(remaining,cap)
            if qty<=0:failed+=1;continue
            cash+=qty*bar[1]*(1-platform.slippage_total/2)*(1-platform.commission_rate);remaining-=qty
            if remaining>0:partial+=1
            else:return cash,date+offset,failed,partial,remaining
    return cash,completed,failed,partial,remaining


class AuditedPlatform(CashPlatform):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.inventory=[];self.fill_states=[];self.event_sequence=0

    def _record(self, event_type, symbol, **kwargs):
        self.event_sequence+=1
        super()._record(event_type,symbol,event_sequence=self.event_sequence,**kwargs)
        if 'FILLED' in event_type or event_type=='SELL_PARTIAL':
            nav=self.nav(self.event_stage)
            self.fill_states.append(dict(timestamp=pd.Timestamp(self.current_date)+pd.Timedelta(hours=9,minutes=30) if self.event_stage=='open' else pd.Timestamp(self.current_date)+pd.Timedelta(hours=15),
                                         stage=self.event_stage,event_sequence=self.event_sequence,cash=self.cash,available_cash=self.cash,
                                         gross_long_value=nav-self.cash,nav=nav,gross_ratio=(nav-self.cash)/nav,
                                         borrowed_cash=0,margin=0,reserved_buy_cash=0,event_type=event_type,symbol=symbol))

    def record_account(self):
        super().record_account()
        for symbol,qty in self.shares.items():
            pos=self.positions[symbol]
            self.inventory.append(dict(symbol=symbol,trade_date=pd.Timestamp(self.current_date),qty=qty,
                                       entry_date=pd.Timestamp(pos.entry_date),entry_price=pos.entry_price,
                                       price=self._mark(symbol,'eod'),account_nav=self.accounts[-1]['nav']))


def load_platform(config,cls=AuditedPlatform):
    inp=config['inputs'];qmt=Path(inp['smv6_qmt_root']);hybrid=Path(inp['smv6_hybrid_root'])
    symbols=[canonical_symbol(x) for x in raw_pool()]+['000852.SH']
    daily={};minute={}
    for symbol in symbols:
        d=read_bound(qmt/'daily'/f'symbol={symbol}'/'daily.parquet',"trade_date<=DATE '2023-12-31'")
        d['trade_date']=pd.to_datetime(d.trade_date);d=d.set_index('trade_date').sort_index()
        d.loc[~d.row_status.eq('VALID'),['pre_adj_open','pre_adj_high','pre_adj_low','pre_adj_close','volume_raw','amount_cny']]=np.nan
        daily[symbol]=d
        m=read_bound(hybrid/'minute_critical'/f'symbol={symbol}'/'critical.parquet',"trade_date<=DATE '2023-12-31'")
        m['trade_date']=pd.to_datetime(m.trade_date).dt.date;minute[symbol]=m
    av=read_bound(hybrid/'execution_availability/critical_execution.parquet',"trade_date<=DATE '2023-12-31'")
    av['trade_date']=pd.to_datetime(av.trade_date).dt.date
    calendar=[d for d in daily['000852.SH'].index if d>=pd.Timestamp('2013-01-01') and np.isfinite(daily['000852.SH'].loc[d,'pre_adj_close'])]
    return cls(daily,minute,av,calendar,initial_cash=1e6,lot_size=100,fee_bps=0),calendar


def run(config):
    ext=Path(config['external_root']);p,calendar=load_platform(config)
    events,nav=_run_callbacks(p,calendar,account=True)
    events=events.sort_values('event_sequence');events['trade_date']=pd.to_datetime(events.trade_date)
    events.to_parquet(ext/'SMV6_current_events.parquet',index=False);nav.to_parquet(ext/'SMV6_current_nav.parquet',index=False)
    inventory=pd.DataFrame(p.inventory);inventory.to_parquet(ext/'SMV6_inventory.parquet',index=False)
    ledger=pd.DataFrame(p.fill_states);ledger.to_parquet(ext/'SMV6_event_account_states.parquet',index=False)
    audit=pd.read_csv(HERE/'execution_and_no_financing_audit.csv')
    a=dict(strategy='SMV6',segment='CONTINUOUS',policy='NATIVE',sleeve='ALL',event_states=len(ledger),min_cash=ledger.cash.min(),max_gross_ratio=ledger.gross_ratio.max(),negative_cash_timestamps=int(ledger.cash.lt(-1e-8).sum()),exposure_violation_timestamps=int(ledger.gross_ratio.gt(1+1e-10).sum()),violation_dates=0,borrowed_cash=0,margin=0,absolute_tolerance_nav_units=1e-8,ratio_tolerance=1e-10,execution_scope='CNY cash, lot100, frozen volume and spread, local callback semantics',reservation_contract='IMMEDIATE_FILL_AFFORDABILITY_FEE_INCLUDED')
    audit=pd.concat([audit.loc[~audit.strategy.eq('SMV6')],pd.DataFrame([a])],ignore_index=True);audit.to_csv(HERE/'execution_and_no_financing_audit.csv',index=False)
    # Track actual episodes including all rebalances and both fees.
    active={};completed=[];event_episode={}
    for r in events.to_dict('records'):
        if r['event_type']=='BUY_FILLED':
            active[r['symbol']]=dict(episode_id=f"SMV6|{r['symbol']}|{r['trade_date'].date()}",symbol=r['symbol'],entry_date=r['trade_date'],outlay=0.,proceeds=0.,buys=0,sells=0)
        if r['symbol'] not in active:continue
        e=active[r['symbol']];event_episode[r['event_sequence']]=e['episode_id']
        delta=r.get('filled_delta_qty',np.nan)
        if np.isfinite(delta):
            if delta>0:e['outlay']+=delta*r['price_pre_adj']+r['fee'];e['buys']+=1
            elif delta<0:e['proceeds']+=-delta*r['price_pre_adj']-r['fee'];e['sells']+=1
        if r['event_type']=='SELL_FILLED':
            completed.append(dict(e,native_time=event_time(r),realized_pnl=e['proceeds']-e['outlay'],native_return=e['proceeds']/e['outlay']-1));del active[r['symbol']]
    residual=pd.DataFrame(completed);residual.to_csv(HERE/'smv6_residual_loss.csv',index=False)
    events['episode_id']=events.event_sequence.map(event_episode)
    fills=events.loc[events.filled_delta_qty.fillna(0).ne(0)]
    grouped={k:g for k,g in fills.groupby('episode_id',sort=False)}
    observations=[]
    for (symbol,entry),inv in inventory.groupby(['symbol','entry_date'],sort=False):
        episode=f"SMV6|{symbol}|{entry.date()}";d=p.daily[symbol]
        path=d.loc[d.index>=entry].copy().reindex(d.loc[d.index>=entry].index.union(pd.DatetimeIndex(inv.trade_date))).sort_index()
        path['mfe']=(path.pre_adj_high/float(inv.entry_price.iloc[0])-1).cummax();path['mae']=(path.pre_adj_low/float(inv.entry_price.iloc[0])-1).cummin()
        before=d.loc[d.index<entry].tail(21);prev=before.pre_adj_close.shift(1)
        atr=pd.concat([before.pre_adj_high-before.pre_adj_low,(before.pre_adj_high-prev).abs(),(before.pre_adj_low-prev).abs()],axis=1).max(axis=1).iloc[1:].mean() if len(before)==21 else np.nan
        for r in inv.itertuples(index=False):
            day=r.trade_date;ob=day+pd.Timedelta(hours=16);future=grouped.get(episode,pd.DataFrame())
            if future.empty:continue
            future=future.loc[future.trade_date.gt(day)]
            # Same original shares carried through native rebalances; subsequent purchases are separate inventory.
            total=float(r.qty);original=float(r.qty);native_cash=0.;native_time=pd.NaT
            for x in future.itertuples(index=False):
                delta=float(x.filled_delta_qty)
                if delta<0:
                    allocated=min(original,(-delta)*original/total)
                    native_cash+=allocated*float(x.price_pre_adj)*(1-p.commission_rate);original-=allocated
                total+=delta
                if total<=0 or original<=1e-9:native_time=event_time(x._asdict());break
            exit_cash,exit_time,failed,partial,remaining=inventory_exit(p,symbol,r.qty,day,calendar,future)
            mature=pd.notna(native_time) and pd.notna(exit_time)
            value=float(r.qty)*float(r.price);row=path.loc[day];age=len(d.loc[(d.index>=entry)&(d.index<=day)])-1
            pnl=float(r.price/r.entry_price-1);seen=path.loc[:day]
            observations.append(dict(route='SMV6',segment='CONTINUOUS',episode_id=episode,event_cluster=episode,symbol=symbol,signal_date=entry,entry_date=entry,
                                     state_observed_at=ob,decision_at=ob,data_available_at=day+pd.Timedelta(hours=15),earliest_legal_execution_at=exit_time,
                                     native_time=native_time,label_available_at=max(native_time,exit_time) if mature else pd.NaT,
                                     label_status='MATURE' if mature else 'CENSORED',state_valid=np.isfinite(r.price),quantity_coordinate=r.qty,holding_value=value,
                                     EXIT_ADVANTAGE_NET=exit_cash-native_cash if mature else np.nan,exit_advantage_normalized=(exit_cash-native_cash)/value if mature else np.nan,
                                     native_net_return=residual.set_index('episode_id').native_return.get(episode,np.nan),
                                     current_pnl=pnl,age=age,remaining_horizon=np.nan,mfe_sofar=row.mfe,giveback=row.mfe-pnl,atr_entry_frac=atr/r.entry_price,
                                     anchor_distance=float(r.price/d.loc[:day].pre_adj_close.tail(40).mean()-1) if len(d.loc[:day])>=40 else np.nan,
                                     anchor_below_run=np.nan,close_location=(row.pre_adj_close-row.pre_adj_low)/(row.pre_adj_high-row.pre_adj_low) if row.pre_adj_high>row.pre_adj_low else np.nan,
                                     down_volume_ratio=np.nan,recovery_3=r.price/seen.pre_adj_close.iloc[-4]-1 if len(seen)>=4 else np.nan,mae_sofar=row.mae,
                                     failed_attempts=failed,partial_fills=partial,exit_filled=remaining==0,
                                     label_contract='SAME_CURRENT_INVENTORY_PROPORTIONAL_NATIVE_SALES; future purchases excluded; zero cash yield'))
    state=pd.DataFrame(observations);state.to_parquet(ext/'SMV6_position_state_snapshots.parquet',index=False)
    write_json(HERE/'smv6_execution_summary.json',dict(episodes=len(residual),signal_dates=int(residual.entry_date.nunique()),severe_10=int(residual.native_return.le(-.10).sum()),severe_5=int(residual.native_return.le(-.05).sum()),
               state_rows=len(state),partial_sales=int(events.event_type.eq('SELL_PARTIAL').sum()),rebalances=int(events.event_type.eq('REBALANCE_FILLED').sum()),
               native_end_nav=float(nav.nav.iloc[-1]),start=str(nav.trade_date.min()),end=str(nav.trade_date.max()),
               native_platform_equivalence='UNVERIFIED',missing_native_nav_days=int(nav.nav.isna().sum()),missing_native_nav_dates=[str(x) for x in nav.loc[nav.nav.isna(),'trade_date']],
               old_v4_residual_reuse='SUPERSEDED_WRONG_EXECUTION_OUTPUT; use current callback replay, matched against current causal seal',
               new_stop_scan='NOT_OPENED_PENDING_DISCOVERY_INFORMATION'))
    return state
