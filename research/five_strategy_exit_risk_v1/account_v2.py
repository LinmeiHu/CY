"""Research-only adapters around current production accounts; no frozen edits."""
from __future__ import annotations
import json
from pathlib import Path
import math
import numpy as np
import pandas as pd
from five_strategy_bundle.execution.daily import replay_sleeves, replay_shared_router
from five_strategy_bundle.strategies.ogr import replay_portfolio
from state_v2 import END, normalize_stock, policy_mask, exit_at_state, cash_per_share


def replay(strategy, trades, daily, segment='CONTINUOUS_2014_2023'):
    if strategy=='MCB':
        a,s,n,_=replay_sleeves(trades,daily,rank_columns=('industry_positive_ret20_share','stock_minus_industry_ret20','turnover_expansion'),k_per_sleeve=30,daily_cap=10)
        n=n.rename(columns={'combined_nav':'nav'})
    elif strategy=='ATRDR':
        a,s,n=replay_shared_router(trades,daily,nav_end=END)
        n=n.rename(columns={'combined_nav':'nav'});n['cash']=n.main_cash+n.chinext_cash;n['gross_exposure']=n.nav-n.cash
    else:
        start,end=('2018-01-01','2021-12-31') if segment=='2018_2021' else ('2022-01-01','2023-12-31')
        a,s,n=replay_portfolio(trades,daily,account_start=start,account_end=end)
        n=n.loc[n.board.eq('COMBINED')].copy()
    return a,s,n


def audit_account(strategy, accepted, nav, daily, segment, policy):
    """Reconstruct every actual simulated fill and reconcile end-of-day cash.

    These production stock models fill immediately; pending buy reserve is zero.
    Target timestamp is an ordering surrogate after opens, not known minute time.
    """
    records=[]; checks=[]; equity_units='NORMALIZED_NAV'
    symbol_daily={s:g.set_index('trade_date') for s,g in daily.groupby('symbol',sort=False)}
    ogr=strategy in ['OGR','IFCGR']
    for sleeve in ['MAIN','CHINEXT']:
        a=accepted.loc[accepted['board' if ogr else 'sleeve'].eq(sleeve)]
        cash=1. if ogr else .5; active={};events=[]
        for row in a.to_dict('records'):
            eid=str(row['gap_id' if ogr else 'event_id'])
            entry=pd.Timestamp(row['entry_time']) if ogr else pd.Timestamp(row['entry_date'])+pd.Timedelta(hours=9,minutes=30)
            events.append((entry,1,eid,'BUY',row))
            if pd.notna(row.get('exit_date')):
                sell=pd.Timestamp(row['exit_time']) if ogr else pd.Timestamp(row['exit_date'])+pd.Timedelta(hours=15,minutes=59) if str(row['exit_reason']).startswith('TARGET_') else pd.Timestamp(row['exit_date'])+pd.Timedelta(hours=9,minutes=30)
                events.append((sell,0,eid,'SELL',row))
            if ogr:
                for ce in json.loads(row.get('cash_events_json') or '[]'):
                    date=pd.Timestamp(ce['date'])
                    if date>=pd.Timestamp(row['entry_date']) and date<=pd.Timestamp(row['exit_date']):
                        events.append((date+pd.Timedelta(hours=9),-1,eid,'CASH_ACTION',dict(row,cash_per_share=float(ce['cash_per_share']))))
        # Preserve engine acceptance order for simultaneous buys: Python stable sort.
        events.sort(key=lambda x:(x[0],x[1]))
        for when,_,eid,kind,row in events:
            if when.normalize()>nav.trade_date.max(): continue
            before=cash
            if kind=='BUY': cash-=float(row['entry_outlay']);active[eid]=row
            elif kind=='SELL': cash+=float(row['qty'])*float(row['exit_raw_price' if ogr else 'exit_price'])*.998;active.pop(eid,None)
            else: cash+=float(row['qty'])*float(row['cash_per_share'])
            exposure=0.
            for p in active.values():
                g=symbol_daily[p['symbol']]
                # Before open use previous close; throughout the trading day use
                # today's already observed open. EOD reconciliation is separate.
                before_open=when.time()<pd.Timestamp('09:30').time()
                d=g.loc[g.index<when.normalize()] if before_open else g.loc[g.index<=when.normalize()]
                field=('close' if ogr else 'coord_close') if before_open else ('open' if ogr else 'coord_open')
                price=float(d[field].iloc[-1]) if len(d) else float(p['entry_raw_price' if ogr else 'entry_price'])
                exposure+=float(p['qty'])*price
            total=cash+exposure
            records.append(dict(strategy=strategy,segment=segment,policy=policy,sleeve=sleeve,timestamp=when,
                                kind=kind,event_id=eid,cash_before=before,cash=cash,available_cash=cash,
                                gross_long_value=exposure,nav=total,gross_ratio=exposure/total,
                                reserved_buy_cash=0.,borrowed_cash=0.,margin=0.,units=equity_units,
                                marking_contract='PRIOR_CLOSE_BEFORE_OPEN; KNOWN_DAILY_OPEN_DURING_SESSION'))
        rec=pd.DataFrame([r for r in records if r['sleeve']==sleeve])
        if len(rec):
            checks.append(dict(strategy=strategy,segment=segment,policy=policy,sleeve=sleeve,
                               event_states=len(rec),min_cash=rec.cash.min(),max_gross_ratio=rec.gross_ratio.max(),
                               negative_cash_timestamps=int(rec.cash.lt(-1e-10).sum()),
                               exposure_violation_timestamps=int(rec.gross_ratio.gt(1+1e-10).sum()),
                               violation_dates=int(rec.loc[rec.cash.lt(-1e-10)|rec.gross_ratio.gt(1+1e-10),'timestamp'].dt.normalize().nunique()),
                               borrowed_cash=0,margin=0,reservation_contract='IMMEDIATE_FILLS_NO_DEFERRED_BUY',
                               absolute_tolerance_nav_units=1e-10,ratio_tolerance=1e-10,
                               execution_scope='FROZEN_NORMALIZED_MODEL; auction depth and integer-share brokerage equivalence unverified'))
    ledger=pd.DataFrame(records)
    for date, row in nav.set_index('trade_date').iterrows():
        total=0.
        for sleeve in ['MAIN','CHINEXT']:
            r=ledger.loc[ledger.sleeve.eq(sleeve)&ledger.timestamp.lt(pd.Timestamp(date)+pd.Timedelta(days=1))]
            c=float(r.cash.iloc[-1]) if len(r) else (1. if ogr else .5)
            total+=c*(.5 if ogr else 1.)
        if not math.isclose(total,float(row.cash),abs_tol=1e-9):
            raise AssertionError(f'event/eod cash reconciliation: {strategy} {date}: {total} vs {row.cash}')
    return pd.DataFrame(checks),ledger


def policy_events(trades, paths, family, value, *, active_from=None, delay=0, extra_cost=0):
    rows=[]
    for tr in trades.to_dict('records'):
        t=pd.Series(tr);p=paths.get(t.episode_id)
        if p is None or p.empty: continue
        eligible=p.loc[p.state_valid & pd.to_datetime(p.available_at).le(p.trade_date+pd.Timedelta(hours=16))].copy()
        if pd.notna(t.native_time): eligible=eligible.loc[(eligible.trade_date+pd.Timedelta(hours=16)).lt(t.native_time)]
        if active_from is not None: eligible=eligible.loc[eligible.trade_date.ge(pd.Timestamp(active_from))]
        mask=policy_mask(eligible,family,value)
        mature=pd.notna(t.native_time)
        base={'episode_id':t.episode_id,'event_id':t.event_id,'route':t.route,'segment':t.segment,
              'event_cluster':t.event_cluster,'signal_date':t.signal_date,'entry_date':t.entry_date,
              'native_time':t.native_time,'native_price':t.exit_price,'entry_price':t.entry_price,
              'qty':t.get('qty',np.nan),'entry_outlay':t.get('entry_outlay',np.nan),
              'family':family,'value':value,'mature':mature}
        if mask.any():
            decision=pd.Timestamp(eligible.loc[mask,'trade_date'].iloc[0])+pd.Timedelta(hours=16)
            result=exit_at_state(t,p,decision,delay=delay,extra_cost=extra_cost)
        else:
            decision=pd.NaT
            result=dict(exit_time_policy=t.native_time,exit_price_policy=t.exit_price,exit_cal_idx_policy=t.exit_cal_idx,exit_cost=.002,triggered=False,filled=False,attempts=0,unfilled=0,gap_return=np.nan)
        policy_cash=float(result['exit_price_policy'])*(1-result['exit_cost'])+cash_per_share(t,result['exit_time_policy']) if pd.notna(result['exit_time_policy']) else np.nan
        native_cash=float(t.exit_price)*.998+cash_per_share(t,t.native_time) if mature else np.nan
        delta=policy_cash-native_cash
        rows.append(dict(base,**result,decision_at=decision,
                         native_return=native_cash/(float(t.entry_price)*1.002)-1,
                         policy_return=policy_cash/(float(t.entry_price)*1.002)-1,
                         advantage_return=delta/(float(t.entry_price)*1.002),
                         advantage_amount=delta*float(t.get('qty',np.nan)),
                         released_calendar_days=(pd.Timestamp(t.native_time)-pd.Timestamp(result['exit_time_policy'])).days if mature else np.nan))
    return pd.DataFrame(rows)


def apply_events(source, normalized, events, policy):
    t=source.copy();mapping=normalized.set_index('event_id').episode_id.to_dict()
    e=events.set_index('episode_id')
    key='gap_id' if 'gap_id' in source else 'event_id'
    for i,row in t.iterrows():
        eid=mapping.get(str(row[key]));x=e.loc[eid] if eid in e.index else None
        if x is None or not bool(x.filled): continue
        when=pd.Timestamp(x.exit_time_policy)
        t.at[i,'exit_date']=when.normalize();t.at[i,'exit_cal_idx']=x.exit_cal_idx_policy
        # Non-TARGET_ is the sealed engine's open-exit clock.
        t.at[i,'exit_reason']='SHADOW_OPEN_'+policy
        t.at[i,'holding_sessions']=float(x.exit_cal_idx_policy)-float(row.entry_cal_idx)
        t.at[i,'net_return']=x.policy_return
        if key=='gap_id':
            t.at[i,'exit_time']=when;t.at[i,'exit_raw_price']=x.exit_price_policy
            ces=json.loads(row.cash_events_json or '[]')
            t.at[i,'cash_events_json']=json.dumps([ce for ce in ces if pd.Timestamp(ce['date'])<=when.normalize()])
        else:
            t.at[i,'exit_price']=x.exit_price_policy;t.at[i,'gross_return']=float(x.exit_price_policy)/float(row.entry_price)-1
            if 'status' in t: t.at[i,'status']='COMPLETED'
    return t


def nav_metrics(nav, start=None, end=None):
    n=nav.copy();n['trade_date']=pd.to_datetime(n.trade_date);n=n.sort_values('trade_date')
    allret=n.nav.pct_change(fill_method=None);allret.iloc[0]=n.nav.iloc[0]-1
    n['r']=allret
    if start is not None: n=n.loc[n.trade_date.ge(pd.Timestamp(start))]
    if end is not None: n=n.loc[n.trade_date.le(pd.Timestamp(end))]
    if n.empty: return {}
    if n.r.isna().any():raise ValueError('Missing NAV in the requested metric window; do not forward-fill prices')
    r=n.r;wealth=(1+r).cumprod();initial=np.r_[1.,wealth.to_numpy()]
    total=float(wealth.iloc[-1]-1);years=max((n.trade_date.max()-n.trade_date.min()).days/365.25,1/252)
    monthly=n.assign(month=n.trade_date.dt.to_period('M')).groupby('month').r.apply(lambda a:np.prod(1+a)-1)
    return dict(start=n.trade_date.min(),end=n.trade_date.max(),days=len(n),total_return=total,
                cagr=(1+total)**(1/years)-1,max_drawdown=float(np.min(initial/np.maximum.accumulate(initial)-1)),
                sharpe=float(r.mean()/r.std()*np.sqrt(252)) if r.std()>0 else 0,
                worst5_daily=float(r.nsmallest(max(1,math.ceil(len(r)*.05))).mean()),worst_month=float(monthly.min()),
                utilization=float((n.gross_exposure/n.nav).mean()),capital_days=float((n.gross_exposure/n.nav).sum()))


def event_summary(e):
    mature=e.loc[e.mature].copy();w=mature.native_return.gt(0);severe=mature.native_return.le(-.10)
    return dict(n=len(e),mature_n=len(mature),censored_n=int((~e.mature).sum()),
                independent_events=e.event_cluster.nunique(),signal_dates=pd.to_datetime(e.signal_date).nunique(),
                triggered=int(e.triggered.sum()),filled=int(e.filled.sum()),unfilled_attempts=int(e.unfilled.sum()),
                trigger_dates=pd.to_datetime(e.decision_at).dt.normalize().nunique(),
                mean_advantage=mature.advantage_return.mean(),median_advantage=mature.advantage_return.median(),
                total_advantage_amount=mature.advantage_amount.sum(min_count=1),
                winner_denominator=int(w.sum()),winner_interruption=int((w&mature.filled).sum()),
                winner_harm=int((w&mature.filled&mature.advantage_return.lt(0)).sum()),
                winner_to_loss=int((w&mature.policy_return.lt(0)).sum()),
                winner_harm_amount=mature.loc[w&mature.advantage_return.lt(0),'advantage_amount'].sum(min_count=1),
                severe_denominator=int(severe.sum()),loss_rescue=int((severe&mature.filled&mature.advantage_return.gt(0)).sum()),
                loss_rescue_amount=mature.loc[severe&mature.filled&mature.advantage_return.gt(0),'advantage_amount'].sum(min_count=1),
                native_tail=mature.native_return.nsmallest(max(1,math.ceil(len(mature)*.05))).mean(),
                policy_tail=mature.policy_return.nsmallest(max(1,math.ceil(len(mature)*.05))).mean(),
                released_calendar_days=mature.released_calendar_days.sum())


def accounting_decomposition(strategy,baseline,policy,daily,end,nav_delta):
    """Independent fill cash plus end inventory reconciliation; all terms in NAV units."""
    ogr=strategy in ['OGR','IFCGR'];key='gap_id' if ogr else 'event_id';weight=.5 if ogr else 1.
    pricefield='close' if ogr else 'coord_close';groups={s:g for s,g in daily.groupby('symbol',sort=False)}
    def inventory(a):
        result={}
        for row in a.to_dict('records'):
            qty=float(row['qty']);cash_actions=0.
            if ogr:
                cash_actions=sum(float(x['cash_per_share']) for x in json.loads(row.get('cash_events_json') or '[]') if pd.Timestamp(x['date'])<=end)
            closed=pd.notna(row.get('exit_date')) and pd.Timestamp(row['exit_date'])<=end
            if closed:unit_cash=float(row['exit_raw_price' if ogr else 'exit_price'])*.998+cash_actions;unit_mark=0.
            else:
                prices=groups[row['symbol']].loc[groups[row['symbol']].trade_date.le(end),pricefield].dropna()
                unit_mark=float(prices.iloc[-1]) if len(prices) else float(row['entry_raw_price' if ogr else 'entry_price'])
                unit_cash=cash_actions
            outlay=float(row['entry_outlay']);unit_pnl=unit_cash+unit_mark-outlay/qty
            result[str(row[key])]=dict(qty=qty*weight,cash=(qty*unit_cash-outlay)*weight,mark=qty*unit_mark*weight,unit_pnl=unit_pnl)
        return result
    b=inventory(baseline);p=inventory(policy);common=set(b)&set(p)
    cash_delta=sum(x['cash'] for x in p.values())-sum(x['cash'] for x in b.values())
    mark_delta=sum(x['mark'] for x in p.values())-sum(x['mark'] for x in b.values())
    residual=nav_delta-cash_delta-mark_delta
    assert abs(residual)<1e-9,(strategy,residual)
    exit_effect=sum(b[k]['qty']*(p[k]['unit_pnl']-b[k]['unit_pnl']) for k in common)
    sizing_effect=sum((p[k]['qty']-b[k]['qty'])*p[k]['unit_pnl'] for k in common)
    new=sum(p[k]['qty']*p[k]['unit_pnl'] for k in set(p)-set(b))
    cancelled=-sum(b[k]['qty']*b[k]['unit_pnl'] for k in set(b)-set(p))
    assert abs(nav_delta-exit_effect-sizing_effect-new-cancelled)<1e-9
    return dict(net_fill_cash_flow_delta=cash_delta,terminal_inventory_mark_delta=mark_delta,
                decomposition_residual=residual,common_event_exit_pnl_delta=exit_effect,common_event_quantity_pnl_delta=sizing_effect,
                newly_funded_pnl=new,cancelled_event_pnl=cancelled)
