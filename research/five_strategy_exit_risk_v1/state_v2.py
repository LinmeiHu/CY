"""Bounded V2 data and position-state research, using the sealed execution code."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from five_strategy_bundle.execution.daily import fixed_target_outcomes, legal_state
from five_strategy_bundle.strategies.atrdr import select_fast_capacity, route_v27_bear
from engine import sha256, canonical_frame_hash

END = pd.Timestamp('2023-12-31')
ROUTES = {'SIMPLE_BULL_PARTICIPATION_IGNITION': 'ATRDR_BULL',
          'BEAR_WORSENING_FAST_CAPITULATION': 'ATRDR_FAST_BEAR',
          'BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION': 'ATRDR_SLOW_BEAR'}
BASE = ['current_pnl', 'age', 'remaining_horizon', 'mfe_sofar', 'giveback', 'atr_entry_frac']
EXTRA = ['anchor_distance', 'anchor_below_run', 'close_location', 'down_volume_ratio', 'recovery_3']


def read_bound(path, where='TRUE', columns='*'):
    con = duckdb.connect(config={'threads': 2, 'memory_limit': '2GB'})
    try:
        return con.execute(f"SELECT {columns} FROM read_parquet(?) WHERE {where}", [str(path)]).fetchdf()
    finally:
        con.close()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + '\n')


def load_sources(config):
    """Read only authorized source columns/rows. Future exit fields SQL-masked."""
    b = Path(config['baseline_root']); a = b / 'atrdr_full_closed_20260907/atrdr'
    src = {name: read_bound(a / f'{name}.parquet', "signal_date <= DATE '2023-12-31'")
           for name in ['bull_mother', 'fast_signal', 'slow_mother']}
    for name, path in [('bull_outcomes', a/'bull_outcomes.parquet'),
                       ('slow_outcomes', a/'slow_outcomes.parquet'),
                       ('MCB', b/'mcb_integrated/trades.parquet')]:
        cols = read_bound(path, 'FALSE').columns
        # Do not read post-2023 outcome payloads even when the input has a tail.
        expressions = []
        for c in cols:
            if c in ['exit_date', 'exit_cal_idx', 'exit_price', 'exit_reason', 'holding_sessions', 'gross_return', 'net_return', 'exit_decision_cal_idx']:
                expressions.append(f"CASE WHEN exit_date <= DATE '2023-12-31' THEN {c} ELSE NULL END AS {c}")
            elif c == 'status':
                expressions.append("CASE WHEN exit_date > DATE '2023-12-31' THEN 'INCOMPLETE_OUTCOME_TAIL' ELSE status END AS status")
            else:
                expressions.append(c)
        src[name] = read_bound(path, "signal_date <= DATE '2023-12-31' AND (entry_date IS NULL OR entry_date <= DATE '2023-12-31')", ','.join(expressions))
    src['mcb_signals'] = read_bound(b/'mcb_integrated/signals.parquet', "signal_date <= DATE '2023-12-31'")
    for strategy in ['OGR', 'IFCGR']:
        src[strategy] = read_bound(b/f'{strategy.lower()}_integrated/trades.parquet', "signal_date <= DATE '2021-12-31' AND exit_date <= DATE '2023-12-31'")
        src[strategy]['segment'] = '2018_2021'
    p = config['inputs']
    for strategy, key in [('OGR', 'ogr_rollforward_outcomes'), ('IFCGR', 'ifcgr_cy065_trades')]:
        part = read_bound(p[key], "signal_date BETWEEN DATE '2022-01-01' AND DATE '2023-12-31' AND entry_date <= DATE '2023-12-31' AND exit_date <= DATE '2023-12-31'")
        part['segment'] = '2022_2023'
        src[strategy] = pd.concat([src[strategy], part], ignore_index=True)
    return src


def daily_cache(config, src):
    out = Path(config['external_root']) / 'daily_relevant.parquet'
    if out.exists():
        return pd.read_parquet(out)
    symbols = sorted(set().union(*(set(d.symbol.astype(str)) for d in src.values() if 'symbol' in d)))
    registry = pd.DataFrame({'symbol': symbols})
    con = duckdb.connect(config={'threads': 2, 'memory_limit': '2GB'})
    con.register('wanted', registry)
    columns = ['symbol', 'trade_date', 'cal_idx', 'open', 'high', 'low', 'close', 'volume', 'amount',
               'coord_open', 'coord_high', 'coord_low', 'coord_close', 'coordinate_factor',
               'invalid_step_cum', 'hard_valid', 'history_valid', 'current_valid',
               'corporate_action_valid', 'corporate_action_count', 'corporate_action_blocking',
               'current_day_data_tradable', 'market_rule_valid', 'trade_status',
               'up_limit_price', 'down_limit_price', 'available_at', 'decision_at', 'is_st', 'causal_industry']
    query = f"SELECT {','.join('d.'+c for c in columns)} FROM read_parquet(?) d JOIN wanted USING(symbol) WHERE trade_date <= DATE '2023-12-31' ORDER BY symbol,trade_date"
    d = con.execute(query, [config['inputs']['daily_hist']]).fetchdf(); con.close()
    d.to_parquet(out, index=False)
    return d


def build_atr_sources(src, daily, external):
    """Recompute the corrected T10/H20 producer, not the old H60-gated file."""
    f = src['fast_signal']
    fast = fixed_target_outcomes(f, daily.loc[daily.symbol.isin(f.symbol)], target=.10, horizon=20, profile='T10_H20_NO_STOP')
    fields = ['event_id', 'step_return', 'signal_decision_at', 'regime_latest_source_timestamp',
              'b20_l5_source_timestamp', 'market_positive_ret20_share', 'b20_l5', 'prior10_return',
              'close_location_x', 'turnover_ratio_x', 'invalid_step_cum',
              'stock_minus_industry_ret20', 'close_vs_prior10_high']
    fast = fast.merge(f[fields], on='event_id', validate='one_to_one').rename(columns={'invalid_step_cum':'signal_invalid'})
    fast.to_parquet(external/'fast_corrected.parquet', index=False)
    return fast


def route_union(src, fast, market, external, *, retain_entered=False):
    accepted = select_fast_capacity(fast, external/'fast_capacity.parquet')
    accepted = accepted.merge(src['fast_signal'][['event_id','market_regime','market_median_ret20','market_median_ret60','latest_source_timestamp']], on='event_id', validate='one_to_one')
    slow = src['slow_outcomes'].copy()
    # This separate research adapter is NOT described as an unchanged baseline.
    if retain_entered:
        slow.loc[slow.entry_date.notna(), 'status'] = 'COMPLETED'
    bear = route_v27_bear(accepted, slow, src['slow_mother'], market, external/'bear_routes.parquet')
    bull = src['bull_outcomes']
    mask = bull.entry_date.notna() if retain_entered else bull.status.eq('COMPLETED')
    bull = bull.loc[mask].merge(src['bull_mother'][['event_id','lane','industry_breadth20_delta5','ret60','turnover_ratio']], on='event_id', validate='one_to_one')
    bull['source'] = 'V29_SIMPLE_BULL'; bull['source_event_id'] = bull.event_id
    bull['event_id'] = 'V29|BULL|' + bull.event_id
    bull['source_rank1'] = bull.industry_breadth20_delta5; bull['source_rank2'] = -bull.ret60; bull['source_rank3'] = bull.turnover_ratio
    bear['source'] = 'V27_BEAR'; bear['source_event_id'] = bear.event_id; bear['event_id'] = 'V29|V27|' + bear.event_id
    for n in range(1,4): bear[f'source_rank{n}'] = bear[f'rank{n}']
    union = pd.concat([bear,bull], ignore_index=True).sort_values(['signal_date','sleeve','source','source_rank1','source_rank2','source_rank3','event_id'], ascending=[True,True,True,False,False,False,True], kind='stable')
    union['source_rank_order'] = union.groupby(['signal_date','sleeve','source']).cumcount()
    union['route'] = union.lane.map(ROUTES)
    anchors = []
    for name, route, col, avail in [('bull_mother','ATRDR_BULL','coord_low','feature_latest_timestamp'),('fast_signal','ATRDR_FAST_BEAR','coord_low','signal_decision_at'),('slow_mother','ATRDR_SLOW_BEAR','last5_low','available_at')]:
        d = src[name]
        anchors.append(pd.DataFrame({'source_event_id':d.event_id,'route':route,'anchor':d[col],'anchor_available_at':d[avail]}))
    return union.merge(pd.concat(anchors), on=['source_event_id','route'], validate='many_to_one').reset_index(drop=True)


def normalize_stock(trades, route=None):
    t=trades.copy()
    if route: t['route']=route
    if 'gap_id' in t:
        t['event_id'] = t.gap_id
        t['entry_price'] = t.entry_raw_price
        t['exit_price'] = t.exit_raw_price
        t['anchor'] = t.swing_low / t.entry_coordinate_factor
        t['anchor_available_at'] = t.semantic_feature_latest_timestamp.fillna(pd.to_datetime(t.signal_time))
        t['sleeve'] = t.board
        t['native_time'] = pd.to_datetime(t.exit_time)
        if 'qty' in t: t['qty']=t.qty*.5
        if 'entry_outlay' in t: t['entry_outlay']=t.entry_outlay*.5
    else:
        t['segment'] = 'CONTINUOUS_2014_2023'
        t['entry_time'] = pd.to_datetime(t.entry_date) + pd.Timedelta(hours=9, minutes=30)
        t['native_time'] = pd.to_datetime(t.exit_date) + pd.to_timedelta(np.where(t.exit_reason.fillna('').str.startswith('TARGET_'), 16*60, 9*60+30),unit='m')
    t['episode_id'] = t.route + '|' + t.segment + '|' + t.event_id.astype(str)
    # Bull and MCB overlap gets the same event cluster; never pooled as independent evidence.
    t['event_cluster'] = t.symbol.astype(str)+'|'+pd.to_datetime(t.signal_date).dt.strftime('%Y-%m-%d')
    t['horizon'] = np.where(t.route.isin(['ATRDR_BULL','MCB']),15,20)
    return t


def entry_atr(d, when, lineage):
    prior=d.loc[d.trade_date.lt(when)].sort_values('cal_idx').tail(21)
    if len(prior)!=21 or not prior.cal_idx.diff().iloc[1:].eq(1).all(): return np.nan
    if not (prior.invalid_step_cum.eq(lineage)&prior.hard_valid&prior.history_valid&prior.current_valid).all(): return np.nan
    previous=prior.coord_close.shift(1)
    tr=pd.concat([prior.coord_high-prior.coord_low,(prior.coord_high-previous).abs(),(prior.coord_low-previous).abs()],axis=1).max(axis=1)
    return float(tr.iloc[1:].mean())


def cash_per_share(trade, through):
    raw=trade.get('cash_events_json','[]')
    events=json.loads(raw) if isinstance(raw,str) and raw else []
    return sum(float(x['cash_per_share']) for x in events if pd.Timestamp(x['date'])<=pd.Timestamp(through).normalize())


def causal_features(path, trade, atr):
    """Features are prefix-only; includes entry-day observations after the close."""
    p=path.sort_values('cal_idx').copy(); price=float(trade.entry_price)
    cash=p.get('cash_accrued_per_share',0.)
    close=p.coord_close+cash;high=p.coord_high+cash;low=p.coord_low+cash
    p['age']=p.cal_idx-float(trade.entry_cal_idx)
    p['current_pnl']=close/price-1
    p['mae_sofar']=(low/price-1).cummin()
    p['mfe_sofar']=(high/price-1).cummax()
    p['giveback']=p.mfe_sofar-p.current_pnl
    p['remaining_horizon']=(float(trade.horizon)-p.age).clip(lower=0)
    p['atr_entry_frac']=atr/price
    anchor=float(trade.get('anchor',np.nan))
    known=pd.notna(trade.get('anchor_available_at')) and pd.Timestamp(trade.anchor_available_at)<=pd.Timestamp(trade.entry_time)
    if not known: anchor=np.nan
    p['anchor_distance']=close/anchor-1
    below=close.lt(anchor)
    p['anchor_below_run']=below.groupby((~below).cumsum()).cumsum().astype(float)
    if not np.isfinite(anchor): p['anchor_below_run']=np.nan
    span=p.coord_high-p.coord_low
    p['close_location']=((p.coord_close-p.coord_low)/span.replace(0,np.nan)).clip(0,1)
    prior_volume=p.volume.shift(1).rolling(5,min_periods=3).mean()
    p['down_volume_ratio']=(p.volume/prior_volume).where(close.lt(close.shift(1)),0).where(prior_volume.notna())
    p['recovery_3']=close/close.shift(3)-1
    return p


def policy_mask(p, family, value=None):
    if family=='fixed': return p.current_pnl.le(-value)
    if family=='atr': return p.current_pnl.le(-value*p.atr_entry_frac)
    if family=='time': return p.age.ge(value)&p.current_pnl.lt(0)
    if family=='H1': return p.anchor_below_run.ge(value or 2)&p.close_location.lt(.5)
    if family=='H2': return p.current_pnl.lt(0)&p.down_volume_ratio.gt(1)&p.recovery_3.lt(0)
    if family=='profit': return p.mfe_sofar.ge(.05)&p.current_pnl.le(0)
    return pd.Series(False,index=p.index)


def exit_at_state(trade, path, decision, delay=0, extra_cost=0):
    """Latched next-open counterfactual, preserves native if it actually wins."""
    native_time=pd.Timestamp(trade.native_time)
    p=path.loc[path.trade_date.gt(pd.Timestamp(decision).normalize()) & path.cal_idx.gt(trade.entry_cal_idx)].copy()
    if delay: p=p.iloc[delay:]
    if pd.notna(native_time): p=p.loc[(p.trade_date+pd.Timedelta(hours=9,minutes=30)).lt(native_time)]
    legal=np.flatnonzero(p.sellable_open.to_numpy())
    attempts=len(p)
    if len(legal):
            index=int(legal[0]); row=p.iloc[index]; attempts=index+1
            when=pd.Timestamp(row.trade_date)+pd.Timedelta(hours=9,minutes=30)
            native_target=str(trade.get('exit_reason','')).startswith('TARGET_') or str(trade.get('exit_reason',''))=='PRE_L_TARGET'
            if native_target and pd.notna(native_time) and when.normalize()==native_time.normalize() and float(row.coord_open)>=float(trade.exit_price):
                return {'exit_time_policy':native_time,'exit_price_policy':float(trade.exit_price),
                        'exit_cal_idx_policy':trade.exit_cal_idx,'exit_cost':.002,'triggered':True,'filled':False,
                        'attempts':attempts,'unfilled':attempts-1,'gap_return':np.nan}
            return {'exit_time_policy':when,'exit_price_policy':float(row.coord_open),
                    'exit_cal_idx_policy':int(row.cal_idx),'exit_cost':.002+extra_cost,
                    'triggered':True,'filled':True,'attempts':attempts,'unfilled':attempts-1,
                    'gap_return':float(row.coord_open/path.loc[path.trade_date.le(pd.Timestamp(decision).normalize()),'coord_close'].iloc[-1]-1)}
    return {'exit_time_policy':native_time,'exit_price_policy':float(trade.exit_price) if pd.notna(trade.exit_price) else np.nan,
            'exit_cal_idx_policy':trade.exit_cal_idx,'exit_cost':.002,'triggered':True,'filled':False,
            'attempts':attempts,'unfilled':attempts,'gap_return':np.nan}


def forward_observed_downside(trade, held, state):
    """Only full days actually held plus the known native liquidation price.

    A native intraday exit's unobserved partial-day low is not invented. This is
    an observed-path diagnostic bound, not an exact intraday MAE label.
    """
    if pd.isna(trade.native_time): return np.nan
    current_cash=float(state.cash_accrued_per_share)
    future=held.loc[held.trade_date.gt(state.trade_date)]
    prices=(future.coord_low+future.cash_accrued_per_share-current_cash).tolist()
    prices.append(float(trade.exit_price)+cash_per_share(trade,trade.native_time)-current_cash)
    return min(prices)/float(state.coord_close)-1


def snapshots(trades, daily, external):
    groups={str(s):g.reset_index(drop=True) for s,g in daily.groupby('symbol',sort=False)}
    paths={}; rows=[]; anatomy=[]
    for trade in trades.itertuples(index=False):
        t=pd.Series(trade._asdict())
        if pd.isna(t.entry_date): continue
        d=groups[str(t.symbol)]
        if t.route in ['OGR','IFCGR']:
            d=d.copy()
            for col in ['open','high','low','close']: d['coord_'+col]=d[col]
        entry=d.loc[d.trade_date.eq(t.entry_date)]
        if entry.empty: continue
        lineage=float(entry.invalid_step_cum.iloc[0])
        finish=min(END,pd.Timestamp(t.native_time).normalize()) if pd.notna(t.native_time) else END
        p=d.loc[d.trade_date.between(t.entry_date,finish)].copy()
        p['cash_accrued_per_share']=[cash_per_share(t,day) for day in p.trade_date]
        legal=p.invalid_step_cum.eq(lineage)
        for col in ['hard_valid','history_valid','current_valid','corporate_action_valid','current_day_data_tradable','market_rule_valid']:
            legal &= p[col].fillna(False).astype(bool)
        legal &= ~p.corporate_action_blocking.fillna(True).astype(bool) & p.trade_status.eq(1)
        p['state_valid']=legal
        p['sellable_open']=legal & p.volume.gt(0) & (np.rint(p.open*100)>np.rint(p.down_limit_price*100))
        atr=entry_atr(groups[str(t.symbol)],pd.Timestamp(t.entry_date),lineage)
        if t.route in ['OGR','IFCGR']: atr/=float(t.entry_coordinate_factor)
        p=causal_features(p,t,atr).reset_index(drop=True)
        paths[t.episode_id]=p
        if not np.isfinite(float(t.get('qty',np.nan))): continue
        # Avoid exit-day OHLC after an open/intraday liquidation in anatomy too.
        held=p.loc[(p.trade_date+pd.Timedelta(hours=16)).lt(pd.Timestamp(t.native_time))] if pd.notna(t.native_time) else p
        mature=pd.notna(t.native_time) and pd.Timestamp(t.native_time)<=END+pd.Timedelta(hours=23)
        native_cash=float(t.exit_price)*(1-.002)+cash_per_share(t,t.native_time) if mature else np.nan
        native_ret=native_cash/(float(t.entry_price)*(1+.002))-1 if mature else np.nan
        qty=float(t.get('qty',np.nan)); basis=float(t.get('entry_outlay',np.nan))
        profit=(held.coord_high+held.cash_accrued_per_share)/float(t.entry_price)-1
        loss=(held.coord_low+held.cash_accrued_per_share)/float(t.entry_price)-1
        native_gross=(float(t.exit_price)+cash_per_share(t,t.native_time))/float(t.entry_price)-1 if mature else np.nan
        breaches=(held.coord_close+held.cash_accrued_per_share).lt(float(t.get('anchor',np.nan)))
        recovered=bool((((held.coord_close+held.cash_accrued_per_share).ge(float(t.get('anchor',np.nan)))) & breaches.cummax()).any())
        anatomy.append({'route':t.route,'segment':t.segment,'episode_id':t.episode_id,'symbol':t.symbol,
                        'signal_date':t.signal_date,'entry_date':t.entry_date,'native_time':t.native_time,
                        'mature':mature,'native_net_return':native_ret,'qty_coordinate':qty,'entry_outlay':basis,
                        'mae_observed':min(loss.min(),native_gross) if mature else loss.min(),
                        'mfe_observed':max(profit.max(),native_gross) if mature else profit.max(),
                        'never_profited_5pct':profit.max()<.05,'profit_giveback':profit.max()>=.05 and native_ret<0,
                        'breached_then_recovered':recovered,'sustained_breach':bool((held.anchor_below_run>=2).any()),
                        'underwater_days':int(held.current_pnl.lt(0).sum()),'untradable_days':int((~p.sellable_open).sum()),
                        'path_days':len(p),'label_status':'MATURE' if mature else 'CENSORED',
                        'mae_scope':'held full-day wealth OHLC plus native exit price; intraday exit-day low/high unavailable'})
        for state in held.itertuples(index=False):
            decision=pd.Timestamp(state.trade_date)+pd.Timedelta(hours=16)
            # Every observed holding state is retained, missing/invalid features explicit.
            x=exit_at_state(t,p,decision)
            policy_cash=float(x['exit_price_policy'])*(1-x['exit_cost'])+cash_per_share(t,x['exit_time_policy']) if pd.notna(x['exit_time_policy']) else np.nan
            advantage=policy_cash-native_cash if mature else np.nan
            rows.append({'route':t.route,'segment':t.segment,'episode_id':t.episode_id,'event_cluster':t.event_cluster,
                         'symbol':t.symbol,'signal_date':t.signal_date,'entry_date':t.entry_date,
                         'state_observed_at':decision,'decision_at':decision,'data_available_at':state.available_at,
                         'earliest_legal_execution_at':x['exit_time_policy'],'native_time':t.native_time,
                         'label_available_at':max(pd.Timestamp(t.native_time),pd.Timestamp(x['exit_time_policy'])) if mature else pd.NaT,
                         'label_status':'MATURE' if mature else 'CENSORED','state_valid':state.state_valid,
                         'quantity_coordinate':qty,'holding_value':qty*float(state.coord_close),
                         'EXIT_ADVANTAGE_NET':advantage*qty,'exit_advantage_normalized':advantage/float(state.coord_close),
                         'native_net_return':native_ret,'future_downside':forward_observed_downside(t,held,state),
                         'future_downside_scope':'HELD_FULL_DAYS_AND_NATIVE_EXIT_ONLY; partial intraday exit-day extrema unobserved',
                         'state_days_to_native':(pd.Timestamp(t.native_time)-decision).days if mature else np.nan,
                         'exit_filled':x['filled'],'failed_attempts':x['unfilled'],
                         **{c:getattr(state,c) for c in BASE+EXTRA+['mae_sofar']}})
    states=pd.DataFrame(rows); losses=pd.DataFrame(anatomy)
    states.to_parquet(external/'position_state_snapshots.parquet',index=False)
    losses.to_parquet(external/'loss_episodes.parquet',index=False)
    return states,losses,paths
