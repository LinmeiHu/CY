"""P0-only common account entry point; missing native states fail before dispatch."""
from copy import deepcopy
from math import isfinite
from .allocator import active_strategies
from .engine import PhysicalAccount
from .scheduler import run_streams


def initialize(gap, states):
    strategies=active_strategies(gap)
    if set(states)!=set(strategies):raise ValueError('all four native states required; no dropped sleeve')
    for strategy,state in states.items():
        if state.get('validation_status')!='VALIDATED':raise ValueError(f'{strategy}: native initial state not validated')
        if state.get('strategy')!=strategy:raise ValueError('initial state strategy mismatch')
        if not all(isfinite(state[k]) for k in ('cash','nav')) or state['cash']<0 or state['nav']<=0:raise ValueError('invalid native initial cash/NAV')
        if state.get('pending_entitlement') is None or state.get('tradable_quantity') is None:raise ValueError('native share state missing')
    if len({s['segment_start'] for s in states.values()})!=1:raise ValueError('native boundaries differ')
    account=PhysicalAccount(gap,initial_cash=sum(s['nav'] for s in states.values()))
    account.cash=sum(s['cash'] for s in states.values())
    account.sleeve_cash={s:states[s]['cash'] for s in strategies}
    account.initial_states=deepcopy(states)
    for strategy,state in states.items():
        if state.get('pending_entitlement') or state.get('nontradable_quantity'):
            raise ValueError('pending boundary restoration needs resolved event transition records')
        expected=state['positions']
        observed={}
        for eid,lot in state.get('virtual_lots',{}).items():
            if eid in account.lots:raise ValueError('duplicate cross-sleeve lot identity')
            symbol=lot['symbol']; qty=lot['quantity']; mark=state.get('marks',{}).get(symbol)
            if mark is None or not isfinite(mark) or mark<=0:raise ValueError('missing native boundary mark')
            account.mark({symbol:mark},basis=lot.get('price_basis','RAW'))
            # P&L is measured since this segment; native cost is retained as audit.
            account.lots[eid]={**deepcopy(lot),'strategy':strategy,'native_origin_outlay':lot['remaining_outlay'],'remaining_outlay':qty*mark}
            account.positions[symbol]=account.positions.get(symbol,0.)+qty
            observed[symbol]=observed.get(symbol,0.)+qty
        if observed!=expected:raise ValueError('native boundary lots/positions mismatch')
        equity=account.sleeve_cash[strategy]+account.exposure(strategy)
        if abs(equity-state['nav'])>1e-6:raise ValueError('native initial attributed NAV mismatch')
    account.checkpoint(next(iter(states.values()))['segment_start'],'INITIAL_STATE')
    return account


def run(gap,states,adapter_factories):
    """Factories bind live adapters to this account, not pre-funded ledgers."""
    account=initialize(gap,states)
    if set(adapter_factories)!=set(account.strategies):raise ValueError('all four native adapters required')
    streams=[adapter_factories[s](account,states[s]) for s in account.strategies]
    trace=run_streams(streams)
    return account,trace
