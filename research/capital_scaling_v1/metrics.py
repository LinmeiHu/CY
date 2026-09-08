"""Reuse parent metrics, adding capital-frontier concentration and attribution."""
from collections import defaultdict
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd

from research.shared_capital_v1.shared_study import metrics as parent_metrics


def ratio(numerator, denominator):
    if denominator is None or not np.isfinite(denominator):
        return None, 'MISSING_DENOMINATOR'
    if denominator == 0:
        return None, 'ZERO_DENOMINATOR'
    if denominator < 0:
        return None, 'NEGATIVE_DENOMINATOR'
    return numerator/denominator, 'DEFINED'


def summarize(account, daily, start, end, gap, scaling=None):
    d = daily.copy()
    if d.empty:
        raise ValueError('required daily account layer empty')
    strategies = ('ATRDR', 'MCB', gap, 'SMV6')
    proxy = SimpleNamespace(**account.__dict__)
    proxy.strategies = strategies
    proxy.initial_states = dict(account.initial_states)
    for s in strategies:
        proxy.initial_states.setdefault(s, dict(nav=0., cash=0.))
        for field in ('cash', 'nav', 'exposure'):
            if s+'_'+field not in d:
                d[s+'_'+field] = 0.
    demand = pd.DataFrame(account.funding.demand)
    if demand.empty:
        demand = pd.DataFrame(columns=['event_id'])
    base_ids = {f['event_id'] for f in account.fills if f['side'] == 'BUY'}
    result, d, _, _ = parent_metrics(proxy, d, start, end, demand, base_ids)
    nav = d.nav.astype(float)
    weight = d.max_security_exposure/nav
    demand_weight = (d.ATRDR_exposure+d.MCB_exposure)/nav
    result.update(trade_count=len({f.get('root_event_id', f['event_id']) for f in account.fills if f['side'] == 'BUY'}),
                  scaled_trade_count=len({f.get('root_event_id', f['event_id']) for f in account.fills if f['side'] == 'BUY' and f['funding_type'] == 'SCALED'}),
                  max_single_security_weight=float(weight.max()), max_family_weight=result['max_family_exposure'],
                  recovery_time_days=None if pd.isna(result['drawdown_recovery']) else (pd.Timestamp(result['drawdown_recovery'])-pd.Timestamp(result['drawdown_trough'])).days,
                  target_gross=None if scaling is None else scaling.target,
                  share_days_90pct_target=None if scaling is None else float((d.gross_exposure/nav >= .9*scaling.target).mean()),
                  share_checkpoints_90pct_target=None if scaling is None or not scaling.normalizations else float(np.mean([r['achieving_90pct'] for r in scaling.normalizations])),
                  scaling_checkpoint_count=0 if scaling is None else len(scaling.normalizations),
                  pending_adjustments_at_end=0 if scaling is None else len(scaling.pending))
    for threshold in (.25, .50, .75, .90):
        tag = str(round(threshold*100))
        result['security_days_gt'+tag] = int((weight > threshold).sum())
        result['security_fraction_gt'+tag] = float((weight > threshold).mean())
    for threshold in (.50, .75, .90):
        tag = str(round(threshold*100))
        result['demand_days_gt'+tag] = int((demand_weight > threshold).sum())
        result['demand_fraction_gt'+tag] = float((demand_weight > threshold).mean())
    timeline = pd.DataFrame(account.account_timeline)
    result['observed_checkpoint_max_security_weight'] = float((timeline.max_security_exposure/timeline.nav).max())
    result['observed_checkpoint_max_gross'] = float((timeline.gross_exposure/timeline.nav).max())
    result['observed_completed_timestamp_MaxDD'] = float((1-timeline.nav/timeline.nav.cummax().clip(lower=account.initial_cash)).max())
    result['daily_close_max_security_weight'] = result['max_single_security_weight']
    result['daily_close_max_family_weight'] = result['max_family_weight']
    result['daily_close_max_strategy_weight'] = result['max_strategy_exposure']
    exposures = pd.DataFrame({s: timeline.get(s+'_exposure', pd.Series(0., index=timeline.index))/timeline.nav for s in strategies})
    result['max_single_security_weight'] = result['observed_checkpoint_max_security_weight']
    result['max_strategy_exposure'] = float(exposures.max().max())
    result['max_family_weight'] = max(float((exposures.ATRDR+exposures.MCB).max()), float(exposures[gap].max()), float(exposures.SMV6.max()))
    result['concentration_observation_basis'] = 'ALL_RECORDED_COMPLETED_TIMESTAMPS; THRESHOLD_DAY_COUNTS_ARE_DAILY_CLOSE'
    result['zero_actual_exposure_days'] = int(d.gross_exposure.le(1e-8).sum())
    normalizations = pd.DataFrame(scaling.normalizations) if scaling is not None else pd.DataFrame()
    errors = normalizations.relative_weight_error.dropna() if 'relative_weight_error' in normalizations else pd.Series(dtype=float)
    result['normalization_weight_error_max'] = float(errors.max()) if len(errors) else None
    result['normalization_weight_error_p95'] = float(errors.quantile(.95)) if len(errors) else None
    result['normalization_weight_error_median'] = float(errors.median()) if len(errors) else None
    result['normalization_max_gross_overshoot'] = max(0., float((normalizations.actual_gross-scaling.target).max())) if len(normalizations) else None
    # All round trips, add-ons and reductions are measured from actual fills.
    fill_rows = []
    metadata = {}
    for f in [*account.fills, *account.lots.values()]:
        root = f.get('root_event_id', f['event_id'])
        metadata.setdefault(root, f)
    for f in account.fills:
        sell = f['side'] == 'SELL'
        quantity = f['filled_quantity'] if sell else f['quantity']
        price = f['exit_price'] if sell else f['price']
        fill_rows.append(dict(timestamp=pd.Timestamp(f['exit'] if sell else f['entry']), event_id=f.get('root_event_id', f['event_id']),
                              symbol=f['symbol'], strategy=f['strategy'], side=f['side'], notional=quantity*price, fee=f['fee']))
    fills = pd.DataFrame(fill_rows, columns=['timestamp', 'event_id', 'symbol', 'strategy', 'side', 'notional', 'fee'])
    result['turnover'] = float(fills.notional.sum()/nav.mean())
    result['traded_notional'] = float(fills.notional.sum())
    result['max_position_notional'] = float(timeline.max_security_exposure.max())
    result['max_physical_fill_notional'] = float(fills.notional.max()) if len(fills) else 0.
    # Native exits can split a root event over virtual add-on lots. Aggregate
    # those pieces without merging different sides, events or exit reasons.
    orders = pd.DataFrame(scaling.orders) if scaling is not None else fills
    keys = ['timestamp', 'event_id', 'strategy', 'symbol', 'side']
    if 'reason' in orders:
        keys.append('reason')
    if len(orders):
        grouped = orders.assign(timestamp=pd.to_datetime(orders.timestamp)).groupby(keys, as_index=False).notional.sum()
        timestamp_nav = timeline.assign(timestamp=pd.to_datetime(timeline.timestamp)).set_index('timestamp').nav
        order_nav = grouped.timestamp.map(timestamp_nav)
        if order_nav.isna().any() or order_nav.le(0).any():
            raise ValueError('order notional has no matching completed account NAV')
        result['max_single_order_notional'] = float(grouped.notional.max())
        result['max_order_notional_over_completed_timestamp_NAV'] = float((grouped.notional/order_nav).max())
    else:
        result.update(max_single_order_notional=0., max_order_notional_over_completed_timestamp_NAV=0.)
    result['order_aggregation_basis'] = 'NATIVE_EVENT_SYMBOL_SIDE_TIMESTAMP_AND_REASON; NOT_EXCHANGE_ORDER_ID'
    if len(fills):
        fills['date'] = fills.timestamp.dt.normalize()
        result['max_daily_traded_notional'] = float(fills.groupby('date').notional.sum().max())
        result['max_same_symbol_daily_traded_notional'] = float(fills.groupby(['date', 'symbol']).notional.sum().max())
        result['max_same_symbol_checkpoint_traded_notional'] = float(fills.groupby(['timestamp', 'symbol']).notional.sum().max())
    else:
        result.update(max_daily_traded_notional=0., max_same_symbol_daily_traded_notional=0., max_same_symbol_checkpoint_traded_notional=0.)
    result['max_position_notional_over_NAV'] = result['observed_checkpoint_max_security_weight']
    result['max_order_over_initial_NAV'] = result['max_single_order_notional']/account.initial_cash
    result['capacity_limited_order_count'] = 0 if scaling is None else len(scaling.capacity)
    result['capacity_limited_requested_notional'] = 0. if scaling is None else sum(r['limited_notional'] for r in scaling.capacity)
    result['capacity_status'] = 'CAPACITY_NOT_MODELED'
    final_pnl = json.loads(d.root_pnl_json.iloc[-1])
    events = []
    for eid, pnl in final_pnl.items():
        m = metadata[eid]
        events.append(dict(event_id=eid, strategy=m['strategy'], route=m['route'], symbol=m['symbol'],
                           entry_date=str(pd.Timestamp(m['entry']).date()), pnl=pnl,
                           capital_days=account.capital_days_by_event.get(eid, 0.),
                           open_at_end=any(k == eid or l.get('root_event_id') == eid for k, l in account.lots.items())))
    events = pd.DataFrame(events, columns=['event_id', 'strategy', 'route', 'symbol', 'entry_date', 'pnl', 'capital_days', 'open_at_end']).astype({'pnl': float, 'capital_days': float})
    if abs(events.pnl.sum()-result['net_pnl']) > 1e-5:
        raise ValueError('event P&L does not reconcile to physical account')
    symbol_pnl = events.groupby('symbol').pnl.sum().sort_values(ascending=False)
    date_pnl = events.groupby('entry_date').pnl.sum().sort_values(ascending=False)
    result['top_5_symbols_pnl'] = json.dumps(symbol_pnl.head(5).to_dict(), sort_keys=True)
    result['top_5_events_pnl'] = json.dumps(events.set_index('event_id').pnl.nlargest(5).to_dict(), sort_keys=True)
    result['top_5_event_dates_pnl'] = json.dumps(date_pnl.head(5).to_dict(), sort_keys=True)
    result['worst_5_events_pnl'] = json.dumps(events.set_index('event_id').pnl.nsmallest(5).to_dict(), sort_keys=True)
    returns = d.portfolio_return
    years = (pd.Timestamp(end)+pd.Timedelta(days=1)-pd.Timestamp(start)).days/365.25
    daily_pnl = nav.diff().fillna(nav.iloc[0]-account.initial_cash)
    for count in (1, 5):
        best = returns.nlargest(count).index
        changed = returns.copy()
        changed.loc[best] = 0.
        hypothetical = account.initial_cash*(1+changed).cumprod()
        result[f'best_{count}_day_return_contribution'] = float(returns.loc[best].sum())
        result[f'best_{count}_day_pnl'] = float(daily_pnl.loc[best].sum())
        result[f'CAGR_excluding_best_{count}_days'] = float((hypothetical.iloc[-1]/account.initial_cash)**(1/years)-1)
        result[f'MaxDD_excluding_best_{count}_days'] = float((1-hypothetical/hypothetical.cummax().clip(lower=account.initial_cash)).max())
    result['top_5_symbols_pnl_fraction'], _ = ratio(float(symbol_pnl.head(5).sum()), result['net_pnl'])
    result['top_5_events_pnl_fraction'], _ = ratio(float(events.pnl.nlargest(5).sum()), result['net_pnl'])
    result['fragility_grade'] = 'DESCRIPTIVE_NON_EXECUTABLE'
    return result, d, events, fills


def drawdown_attribution(summary, daily, native, metadata, strategies):
    peak, trough = pd.Timestamp(summary['drawdown_start']), pd.Timestamp(summary['drawdown_trough'])
    prior = daily.loc[daily.trade_date.le(peak)]
    last = daily.loc[daily.trade_date.eq(trough)].iloc[0]
    first = prior.iloc[-1] if len(prior) else None
    row = dict(peak_date=peak, trough_date=trough, recovery_date=summary['drawdown_recovery'], MaxDD=summary['MaxDD'])
    cumulative = json.loads(last.root_pnl_json)
    peak_pnl = json.loads(first.root_pnl_json) if first is not None else {}
    changes = {k: v-peak_pnl.get(k, 0.) for k, v in cumulative.items()}
    losses = defaultdict(float)
    for eid, value in changes.items():
        losses[metadata[eid]['symbol']] += value
    row['top_losing_securities'] = json.dumps(dict(sorted(losses.items(), key=lambda x: x[1])[:5]))
    nlast = native.loc[native.trade_date.eq(trough)].iloc[0]
    nprior = native.loc[native.trade_date.le(peak)]
    nfirst = nprior.iloc[-1] if len(nprior) else None
    for s in strategies:
        value = sum(v for eid, v in changes.items() if metadata[eid]['strategy'] == s)
        # Native contribution from the account's own attributed equity is
        # independent of different ETF lot IDs across capital policies.
        nvalue = float(nlast[s+'_nav']-(nfirst[s+'_nav'] if nfirst is not None else native.attrs['initial_states'][s]['nav']))
        row[s+'_pnl'] = value
        row[s+'_native_equivalent_pnl'] = nvalue
        row[s+'_incremental_scaled_pnl'] = value-nvalue
    row.update(single_security_weight=float(last.max_security_exposure/last.nav),
               demand_family_gross=float((last.ATRDR_exposure+last.MCB_exposure)/last.nav),
               total_gross=float(last.gross_exposure/last.nav), cash=float(last.cash))
    return row
