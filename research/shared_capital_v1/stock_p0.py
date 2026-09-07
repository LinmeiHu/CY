"""Native stock P0 funding replay through the physical/virtual ledger.

Frozen signal coordinates are immutable. The ledger holds raw economic shares;
registered corporate actions and actual fills drive all subsequent account state.
"""
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import numpy as np

from research.shared_capital_v1.shared_account.engine import Intent, PhysicalAccount
from research.shared_capital_v1.shared_account.scheduler import Event, run_streams

HERE = Path(__file__).resolve().parent


def replay(strategy, entries, daily, start, end, *, enforce_lineage=True, boundaries=(), physical=None, stream_only=False, initial_state=None, action_registry=None):
    """Native decisions on immutable coordinates; fills and holdings in raw units.

    Future outcome columns are never read. A completed target observation exits
    at the sealed daily target checkpoint. Time exits use a prior close decision.
    """
    from copy import deepcopy
    from research.shared_capital_v1.shared_account.price_space import raw_intent
    from research.shared_capital_v1.shared_account.held_actions import HeldActions, registered_actions
    from five_strategy_bundle.execution.daily import legal_state, legal_sell_open
    if not enforce_lineage:
        raise ValueError('lineage validation cannot be disabled')
    required={'symbol','trade_date','open','close','coord_open','coord_close','coord_high','coordinate_factor','cal_idx','invalid_step_cum',
              'hard_valid','history_valid','current_valid','corporate_action_valid','current_day_data_tradable','market_rule_valid',
              'corporate_action_blocking','trade_status','down_limit_price','corporate_action_count','historical_identity_valid'}
    if not required.issubset(daily): raise ValueError('missing raw native execution columns: '+','.join(sorted(required-set(daily))))
    entries=entries.loc[entries.entry_date.between(start,end)].copy()
    rank=['source_rank_order'] if strategy=='ATRDR' else ['industry_positive_ret20_share','stock_minus_industry_ret20','turnover_expansion']
    fields=['entry_date','sleeve','signal_date',*rank,'event_id'] if strategy=='ATRDR' else ['entry_date',*rank,'event_id']
    ascending=[True,True,False,True,True] if strategy=='ATRDR' else [True,False,False,False,True]
    entries=entries.sort_values(fields,ascending=ascending,kind='stable')
    days=pd.DatetimeIndex(sorted(daily.loc[daily.trade_date.between(start,end),'trade_date'].unique()))
    data=daily[list(required)].copy()
    if data[['symbol','trade_date']].duplicated().any(): raise ValueError('duplicate daily execution key')
    indexed=data.set_index(['symbol','trade_date']).sort_index()
    def get_row(symbol,day):
        try: return dict(indexed.loc[(symbol,day)],symbol=symbol,trade_date=day)
        except KeyError: return None
    candidates={pd.Timestamp(d):f for d,f in entries.groupby('entry_date')}
    account=physical if physical is not None else PhysicalAccount('OGR')
    if not hasattr(account,'boundary_snapshots'): account.boundary_snapshots={}
    cash=dict(initial_state['board_cash']) if initial_state else {b:account.sleeve_cash[strategy]/2 for b in ('MAIN','CHINEXT')}
    active=deepcopy(initial_state['native_active']) if initial_state else {}
    for position in active.values():
        position['entry_date']=pd.Timestamp(position['entry_date'])
        if position.get('time_decision') is not None: position['time_decision']=pd.Timestamp(position['time_decision'])
    intents,rejects,nav_rows=[],[],[]
    def credit(board,amount): cash[board]+=amount
    actions=HeldActions(account,registered_actions() if action_registry is None else action_registry,strategy,credit)
    account.held_actions=getattr(account,'held_actions',{})
    account.held_actions[strategy]=actions
    account.execution_state_transitions=getattr(account,'execution_state_transitions',[])

    native_marks=dict((initial_state or {}).get('marks',{}))
    def lots(eid):
        return [(key,lot) for key,lot in account.lots.items() if key==eid or lot.get('root_event_id')==eid]
    def value(eid):
        return sum((lot['quantity']+lot.get('pending_quantity',0.))*native_marks[lot['symbol']] for _,lot in lots(eid))
    def mark(day,field):
        for position in active.values():
            row=get_row(position['symbol'],day)
            if row is None or row['trade_status']!=1: continue # native previous-known mark during suspension
            price=row[field]
            if pd.notna(price) and np.isfinite(price) and price>0:
                native_marks[position['symbol']]=float(price)
                account.mark({position['symbol']:float(price)},basis='RAW',observed_at=day+pd.Timedelta(hours=9,minutes=30) if field=='open' else day+pd.Timedelta(hours=15))
    def apply_actions(day):
        prices={p['symbol']:row['open'] for p in active.values() if (row:=get_row(p['symbol'],day)) is not None}
        actions.open(day,prices)
        for p in active.values():
            if p['symbol'] in actions.rebased_symbols: p['ca_rebase_pending']=True
        actions.rebased_symbols.clear()
    def valid(p,row):
        if row is None: return False
        if (row['trade_status']==0 and not row['current_day_data_tradable'] and row['corporate_action_count']==0
                and row['corporate_action_valid'] and row['market_rule_valid'] and row['historical_identity_valid']):
            if not p.get('suspension_pending'):
                account.execution_state_transitions.append(dict(strategy=strategy,event_id=p['event_id'],symbol=p['symbol'],date=row['trade_date'],transition='REGISTERED_SUSPENSION_NO_FILL_NO_QUANTITY_CHANGE'))
            p['suspension_pending']=True
        lineage=float(row['invalid_step_cum'])
        if lineage != p['lineage']:
            if not (p.get('ca_rebase_pending') or p.get('suspension_pending')):
                raise ValueError(f"ACTIVE_COORDINATE_LINEAGE_CHANGE:{row['trade_date']}:{p['event_id']}: no applied held corporate action")
            # Never rewrite a coordinate or override validity flags. A resolved
            # action permits the first independently valid post-action lineage.
            if legal_state(pd.Series(row),lineage):
                p['lineage']=lineage
                if p.get('suspension_pending'):
                    account.execution_state_transitions.append(dict(strategy=strategy,event_id=p['event_id'],symbol=p['symbol'],date=row['trade_date'],transition='REGISTERED_RESUMPTION_SAME_RAW_HOLDINGS'))
                p['ca_rebase_pending']=False
                p['suspension_pending']=False
        return legal_state(pd.Series(row),p['lineage']) and (not p.get('strict_slow') or (int(row['corporate_action_count'])==0 and row['open']>0 and row['coord_open']>0))
    def liquidate(eid,p,price,when,reason):
        before=account.cash
        for key,lot in list(lots(eid)):
            if lot['quantity']-lot.get('nontradable_quantity',0.)>0:
                account.close(key,float(price),when,.002,reason=reason)
        cash[p['sleeve']]+=account.cash-before
        if not lots(eid): del active[eid]
        else: p['exit_pending']=True # retain actual ownership until legally sellable
    def exits(day,target):
        when=day+pd.Timedelta(hours=15) if target else day+pd.Timedelta(hours=9,minutes=30)
        for eid,p in sorted(list(active.items())):
            row=get_row(p['symbol'],day)
            if day<=pd.Timestamp(p['entry_date']) or not valid(p,row): continue
            if not target:
                known=p.get('exit_pending') or (p.get('strict_slow') and int(row['cal_idx'])>p['entry_cal_idx']+p['horizon']) or (p.get('time_decision') is not None and pd.Timestamp(p['time_decision'])<day)
                if known and legal_sell_open(pd.Series(row),p['lineage']):
                    liquidate(eid,p,row['open'],when,'NATIVE_PENDING_EXIT' if p.get('exit_pending') else f"H{p['horizon']}_TIME_STOP")
            elif not p.get('exit_pending'):
                if float(row['coord_high'])>=p['target_coordinate'] and p.get('time_decision') is None:
                    price=p['target_coordinate']/float(row['coordinate_factor'])
                    liquidate(eid,p,price,when,f"TARGET_{round(100*p['target_return'])}")
                elif not p.get('strict_slow') and int(row['cal_idx'])>=p['entry_cal_idx']+p['horizon'] and p.get('time_decision') is None:
                    p['time_decision']=day
    def boundary_step(day):
        for boundary in boundaries:
            if day>=pd.Timestamp(boundary) and boundary not in account.boundary_snapshots:
                owned={k:deepcopy(v) for k,v in account.lots.items() if v['strategy']==strategy}
                positions={}
                pending={}
                for lot in owned.values():
                    s=lot['symbol']
                    if lot['quantity']: positions[s]=positions.get(s,0.)+lot['quantity']
                    if lot.get('pending_quantity',0.):pending[s]=pending.get(s,0.)+lot['pending_quantity']
                account.boundary_snapshots[boundary]={'asof':nav_rows[-1]['trade_date'] if nav_rows else None,
                    'cash':sum(cash.values()),'board_cash':dict(cash),'nav':sum(cash.values())+account.exposure(strategy),
                    'positions':positions,'pending_entitlement':pending,'marks':{s:account.marks[s] for s in positions|pending},
                    'native_active':deepcopy(active),'virtual_lots':owned}
    def entry_step(day):
        board_nav={b:cash[b]+sum(value(eid) for eid,p in active.items() if p['sleeve']==b) for b in cash}
        batch=[];cohort_rows={}
        when=day+pd.Timedelta(hours=9,minutes=30)
        for ordinal,row in enumerate(candidates.get(day,pd.DataFrame()).itertuples(index=False)):
            board=row.sleeve
            live=[p for p in active.values() if p['sleeve']==board]
            reason='ACTIVE_SYMBOL' if any(p['symbol']==row.symbol for p in live) else 'MAX_K' if len(live)>=30 else None
            if reason:
                rejects.append({'event_id':row.event_id,'reason':reason});continue
            current=get_row(str(row.symbol),day)
            outlay=board_nav[board]/30
            when=day+pd.Timedelta(hours=9,minutes=30)
            priority=(ordinal,)+tuple(getattr(row,k) if strategy=='ATRDR' else -getattr(row,k) for k in rank)
            intent=Intent(strategy,getattr(row,'route','MCB'),'DEMAND',row.event_id,getattr(row,'parent_event_id',''),row.symbol,
                pd.Timestamp(row.signal_date)+pd.Timedelta(hours=15),when,priority,outlay/(float(row.entry_price)*1.002),float(row.entry_price),.002,
                board=board,native_base_cash_limit=max(0.,cash[board]),price_basis='NATIVE_COORDINATE',native_max_positions=30,native_daily_entries=10,
                economic_event_definition='NEXT_OPEN_T15_H15_STANDARD_NATIVE_EXIT' if strategy=='MCB' or getattr(row,'route','')=='BULL' else 'NEXT_OPEN_T10_H20_BEAR_NATIVE_EXIT')
            intent=raw_intent(intent,raw_price=float(current['open']),coordinate_factor=float(current['coordinate_factor']))
            batch.append(intent);cohort_rows[row.event_id]=row
        if not batch:return
        home={s:account.sleeve_cash[s]+account.exposure(s) for s in account.strategies}
        account.fund(batch,home,'P0',when)
        for intent in batch:
            row=cohort_rows[intent.event_id];board=row.sleeve
            current=get_row(str(row.symbol),day)
            if intent.event_id in account.native_failures:
                rejects.append(dict(event_id=intent.event_id,reason=account.native_failures[intent.event_id]));continue
            intents.append({**asdict(intent),'native_requested_notional':intent.native_requested_notional})
            if row.event_id in account.lots:
                cash[board]-=account.lots[row.event_id]['funded_notional']
                native_marks[row.symbol]=intent.price
                bear=strategy=='ATRDR' and row.route=='V27'
                active[row.event_id]={'event_id':row.event_id,'symbol':row.symbol,'sleeve':board,'route':intent.route,
                    'entry_date':day,'entry_cal_idx':int(current['cal_idx']),'entry_price':float(row.entry_price),
                    'target_coordinate':float(row.entry_price)*(1.10 if bear else 1.15),'target_return':.10 if bear else .15,
                    'horizon':20 if bear else 15,'lineage':float(current['invalid_step_cum']), 'time_decision':None,
                    'strict_slow':strategy=='ATRDR' and 'SLOW' in str(getattr(row,'lane',''))}
    def close_step(day):
        mark(day,'close')
        account.checkpoint(day+pd.Timedelta(hours=15),'CLOSE')
        if abs(sum(cash.values())-account.sleeve_cash[strategy])>1e-6: raise ValueError('native board cash mismatch')
        nav_rows.append({'trade_date':day,'nav':sum(cash.values())+account.exposure(strategy),'cash':sum(cash.values()),
            'gross_exposure':account.exposure(strategy),'active_positions':len(active)})
    def events():
        for day in days:
            yield Event(day,'BOUNDARY',strategy,str(day),lambda d=day:boundary_step(d))
            when=day+pd.Timedelta(hours=9,minutes=30)
            yield Event(when,'ACTION',strategy,str(day),lambda d=day:apply_actions(d))
            yield Event(when,'PREPARE',strategy,str(day),lambda d=day:mark(d,'open'))
            yield Event(when,'EXIT',strategy,str(day),lambda d=day:exits(d,False))
            yield Event(when,'ENTRY',strategy,str(day),lambda d=day:entry_step(d))
            when=day+pd.Timedelta(hours=15)
            yield Event(when,'EXIT',strategy,str(day),lambda d=day:exits(d,True))
            yield Event(when,'CLOSE',strategy,str(day),lambda d=day:close_step(d))
            yield Event(day+pd.Timedelta(hours=15,minutes=1),'RECORD',strategy,str(day),lambda d=day:actions.record(d))
    result=lambda:(pd.DataFrame(intents),pd.DataFrame(rejects),pd.DataFrame(nav_rows))
    if stream_only:return events(),result
    blocker=None
    try:account.scheduler_trace=run_streams([events()])
    except ValueError as exc:blocker=str(exc)
    return account,*result(),blocker

def run():
    # Keep the historical entry point, with one authoritative continuous path.
    from .continuous_replay import run as continuous
    return continuous()


if __name__ == "__main__":
    run()
