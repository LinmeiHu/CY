"""Actual virtual-lot P&L and explicitly labeled marginal action diagnostics."""
from bisect import bisect_right
from collections import defaultdict
import json
import time
import duckdb
import numpy as np
import pandas as pd
from .audit import HERE,write_json
from .snapshot import CACHE
from .accounts import folder
from .economics import require_identity,cases,read,KEY


def seed(key):return key.split('|CA|')[0]


def run_one(case,cache_group="rebalance"):
    path=folder(*case);identity=dict(zip(KEY,case[:4]))
    dest=CACHE/cache_group/('__'.join(case[:4]));dest.mkdir(parents=True,exist_ok=True)
    if (dest/'annual.parquet').exists() and (dest/'details.parquet').exists():
        from .forward_quality import qualify
        details=qualify(pd.read_parquet(dest/'details.parquet'),case)
        details.to_parquet(dest/'details.parquet',index=False)
        return details,pd.read_parquet(dest/'annual.parquet')
    while not (path/'observation_receipt.json').exists():time.sleep(10)
    d,a,t,f=read(path)
    scale=json.loads((path/'scaling.json').read_text());targets=pd.read_parquet(path/'normalization_targets.parquet')
    target_lookup={}
    for root,part in targets.groupby('event_id',sort=False):
        records=part.to_dict('records')
        target_lookup[root]=([pd.Timestamp(r['timestamp']) for r in records],records)
    calendar=list(d.trade_date);lots=[json.loads(x) for x in d.lots_json]
    marks=[json.loads(x) for x in d.marks_json]
    allmeta={};categories={};initial={};vintage_for_key={}
    for state in a['initial_states'].values():
        for key,lot in state.get('virtual_lots',{}).items():
            root=lot.get('root_event_id',key);initial[root]=initial.get(root,0)+lot['quantity']
            vintage='INITIAL|'+key;vintage_for_key[key]=vintage
            categories[vintage]='INHERITED_POSITION';allmeta[vintage]=lot
    byday={day:frame for day,frame in f.groupby(f.timestamp.dt.normalize(),sort=True)}
    action_lookup={r['action_id']+'|'+r['strategy']:r for r in a['held_actions']}
    payments=defaultdict(lambda:defaultdict(float))
    for credit in json.loads(d.cash_distributions_json.iloc[-1]):
        payments[pd.Timestamp(credit['timestamp']).normalize()][(credit['action_id'],credit['root_event_id'])]+=credit['amount']
    action_rows=[];root_quantity=dict(initial);record_maps=[]
    histories=defaultdict(list);prior={};credits=defaultdict(float);realized=defaultdict(float);annual=[]
    for index,day in enumerate(calendar):
        if index:
            root_quantity=defaultdict(float)
            for key,lot in lots[index-1].items():root_quantity[lot.get('root_event_id') or key]+=lot['quantity']+(lot.get('pending_quantity') or 0.)
        for action in a['held_actions']:
            if action['share_ratio'] and pd.Timestamp(action['accounting_effective_date']).normalize()==day:
                record_index=calendar.index(pd.Timestamp(action['record_date']).normalize())
                recorded=lots[record_index]
                for key,lot in recorded.items():
                    if lot['symbol']==action['symbol'] and lot['strategy']==action['strategy']:
                        root=lot.get('root_event_id') or key
                        root_quantity[root]=root_quantity.get(root,0.)+lot['quantity']*action['share_ratio']
                        child=key+'|CA|'+action['action_id']+'|'+action['strategy']
                        vintage_for_key[child]=record_maps[record_index][key]
        for row in byday.get(day,pd.DataFrame()).itertuples():
            before=root_quantity.get(row.root,0.);delta=row.actual_quantity*(1 if row.side=='BUY' else -1)
            if row.side=='BUY':category='EXISTING_POSITION_INCREASE' if before>1e-8 else 'NEW_ENTRY_INCREASE'
            else:category='EXISTING_POSITION_REDUCTION' if row.reason=='CAPITAL_TARGET_DECREASE' else 'EXIT'
            after=before+delta;root_quantity[row.root]=after
            if row.side=='BUY':
                # The parent may reuse a root lot key after selling that base lot
                # while other add-on lots remain. Every BUY is its own vintage.
                vintage=row.event_id+'|BUY_FILL|'+str(row.Index)
                vintage_for_key[row.event_id]=vintage;categories[vintage]=category;allmeta[vintage]=row._asdict()
            else:
                vintage=vintage_for_key[row.event_id];realized[vintage]+=row.pnl
            target_times,target_records=target_lookup.get(row.root,([],[]))
            target_index=bisect_right(target_times,row.timestamp)-1
            target=target_records[target_index] if target_index>=0 else None
            ambiguous=target_index>0 and target_times[target_index]==row.timestamp and target_times[target_index-1]==row.timestamp
            action_rows.append(dict(**identity,timestamp=row.timestamp,event_id=row.root,lot_event_id=row.event_id,vintage_id=vintage,strategy=row.strategy,symbol=row.symbol,
                category=category,side=row.side,delta_notional=delta*row.actual_price,reason=row.reason,fees=row.fee,
                native_target_notional=None if target is None or ambiguous else target['native_target_notional'],
                scaled_target_before=None if target is None or ambiguous else target['scaled_target_before'],
                scaled_target_after=None if target is None or ambiguous else target['scaled_target_after'],
                target_observed_at=None if target is None else target['timestamp'],
                actual_quantity_before=before,actual_quantity_after=after,actual_realized_disposal_pnl=row.pnl if row.side=='SELL' else 0.,
                target_basis='MULTIPLE_SAME_TIMESTAMP_TARGETS_SEE_ORDERED_TARGET_LEDGER' if ambiguous else 'Frozen solver desired vector; actual fill quantities separately reported'))
        record_maps.append({key:vintage_for_key[key] for key in lots[index]})
        for (action_id,root),amount in payments.get(day,{}).items():
            action=action_lookup[action_id];record_index=calendar.index(pd.Timestamp(action['record_date']).normalize())
            eligible={key:lot['quantity'] for key,lot in lots[record_index].items() if (lot.get('root_event_id') or key)==root and lot['strategy']==action['strategy']}
            total=sum(eligible.values());assert total>0
            for key,quantity in eligible.items():credits[record_maps[record_index][key]]+=amount*quantity/total
        pnl=defaultdict(float,realized)
        for vintage,value in credits.items():pnl[vintage]+=value
        for key,lot in lots[index].items():
            vintage=vintage_for_key[key]
            pnl[vintage]+=(lot['quantity']+(lot.get('pending_quantity') or 0.))*marks[index][lot['symbol']]-lot['remaining_outlay']
        assert abs(sum(pnl.values())-(d.nav.iloc[index]-a['initial_cash']))<1e-5,(case,day,'LOT_PNL_RECONCILIATION')
        for vintage in pnl.keys()|prior.keys():
            value=pnl.get(vintage,0.);change=value-prior.get(vintage,0.)
            if abs(change)>1e-10:
                histories[vintage].append((day,value));meta=allmeta[vintage]
                annual.append(dict(**identity,year=day.year,seed_event_id=vintage,strategy=meta['strategy'],symbol=meta['symbol'],category=categories[vintage],pnl=change))
        prior=dict(pnl)
    details=pd.DataFrame(action_rows)
    # Buy forwards are the actual new lot's marked + realized + dividend P&L,
    # retaining actual partial exits, final liquidation and corporate shares.
    for horizon in [1,3,5,10,20]:
        values=[];statuses=[]
        for row in details.itertuples():
            index=bisect_right(calendar,row.timestamp.normalize())-1
            if index+horizon>=len(calendar):values.append(np.nan);statuses.append('RIGHT_CENSORED');continue
            if row.side=='SELL':values.append(np.nan);statuses.append('COUNTERFACTUAL_RETAINED_EXPOSURE_REQUIRES_SEPARATE_PRICE_DIAGNOSTIC');continue
            target=calendar[index+horizon];history=histories.get(row.vintage_id,[])
            end=bisect_right([r[0] for r in history],target)-1
            values.append(history[end][1] if end>=0 else 0.);statuses.append('ACTUAL_LOT_PNL_WITH_ACTUAL_EXITS_AND_CA')
        details[f'forward_{horizon}d_pnl']=values;details[f'forward_{horizon}d_status']=statuses
    # Reductions have no owned forward asset. Their signed-price diagnostic is
    # kept distinct from actual lot P&L and from the realized disposal P&L.
    sells=details.loc[details.side.eq('SELL') & details.strategy.ne('SMV6')]
    registry=sells[['symbol']].drop_duplicates()
    with duckdb.connect() as c:
        c.register('registry',registry)
        prices=c.execute('SELECT symbol,trade_date,coord_close,coordinate_factor FROM read_parquet(?) JOIN registry USING(symbol) ORDER BY symbol,trade_date',[str(CACHE/'daily_with_snapshot.parquet')]).fetchdf()
    prices=prices.set_index(['symbol','trade_date'])
    from five_strategy_bundle.strategies import smv6
    from .audit import ROLL
    all_sells=details.loc[details.side.eq('SELL')].copy()
    sell_indexes=all_sells.index
    day_positions=np.searchsorted(np.array(calendar,dtype='datetime64[ns]'),all_sells.timestamp.dt.normalize().to_numpy())
    executed=all_sells.delta_notional.abs()/(all_sells.actual_quantity_after-all_sells.actual_quantity_before).abs()
    stock_mask=all_sells.strategy.ne('SMV6').to_numpy()
    stock=all_sells.loc[stock_mask]
    factors=prices.coordinate_factor.reindex(pd.MultiIndex.from_arrays([stock.symbol,stock.timestamp.dt.normalize()])).to_numpy()
    etf_prices={symbol:smv6.load_daily(ROLL/'smv6',symbol).pre_adj_close for symbol in all_sells.loc[~stock_mask,'symbol'].unique()}
    for horizon in [1,3,5,10,20]:
        valid=day_positions+horizon<len(calendar)
        future_dates=np.array(calendar,dtype='datetime64[ns]')[np.minimum(day_positions+horizon,len(calendar)-1)]
        future=np.full(len(all_sells),np.nan);base=executed.to_numpy().copy()
        future[stock_mask]=prices.coord_close.reindex(pd.MultiIndex.from_arrays([stock.symbol,future_dates[stock_mask]])).to_numpy()
        base[stock_mask]*=factors
        for symbol,series in etf_prices.items():
            mask=(all_sells.symbol.eq(symbol)&all_sells.strategy.eq('SMV6')).to_numpy()
            future[mask]=series.reindex(pd.DatetimeIndex(future_dates[mask])).to_numpy()
        valid &= np.isfinite(future)&np.isfinite(base)&(base>0)
        values=all_sells.delta_notional.to_numpy()*(future/base-1)-all_sells.fees.to_numpy()
        details.loc[sell_indexes[valid],f'forward_{horizon}d_pnl']=values[valid]
        details.loc[sell_indexes[valid & stock_mask],f'forward_{horizon}d_status']='COUNTERFACTUAL_SIGNED_COORDINATE_RETURN;NO_EXIT_REPLAY;NOT_ADDITIVE_ACTUAL_PNL'
        details.loc[sell_indexes[valid & ~stock_mask],f'forward_{horizon}d_status']='COUNTERFACTUAL_SIGNED_PRE_ADJUSTED_ETF_RETURN;NO_EXIT_REPLAY;NOT_ADDITIVE_ACTUAL_PNL'
    timeline=t.set_index(pd.to_datetime(t.timestamp))
    residual=[]
    for normal in scale['normalizations']:
        when=pd.Timestamp(normal['timestamp']);row=timeline.loc[when]
        if isinstance(row,pd.DataFrame):row=row.iloc[-1]
        residual.append(dict(**identity,timestamp=when,event_id='CASH',strategy='CASH',symbol='CASH',category='CASH_RESIDUAL',delta_notional=0.,cash_residual=row.cash,fees=0.,reason=normal['reason'],**{f'forward_{h}d_pnl':0. for h in [1,3,5,10,20]},target_basis='Actual completed timestamp cash; zero interest in frozen account'))
    annual=pd.DataFrame(annual).groupby(KEY+['year','seed_event_id','strategy','symbol','category'],as_index=False).pnl.sum()
    details=pd.concat([details,pd.DataFrame(residual)],ignore_index=True)
    from .forward_quality import qualify
    details=qualify(details,case)
    details.to_parquet(dest/'details.parquet',index=False)
    annual.to_parquet(dest/'annual.parquet',index=False)
    return details,annual


def main():
    require_identity();details=[];annual=[]
    for case in cases():
        if case[2]=='NATIVE' or case[3]!='FULL_BOOK_NORMALIZATION':continue
        d,a=run_one(case);details.append(d);annual.append(a)
        print('REBALANCE_ATTRIBUTED',case[:4],flush=True)
    ledgers=[]
    for case in cases():
        if case[2]=='NATIVE' or case[3]!='FULL_BOOK_NORMALIZATION':continue
        frame=pd.read_parquet(folder(*case)/'normalization_targets.parquet')
        frame['observation_sequence']=range(len(frame))
        for key,value in zip(KEY,case[:4]):frame[key]=value
        ledgers.append(frame)
    pd.concat(ledgers,ignore_index=True).to_csv(HERE/'output/full_book_normalization_targets.csv',index=False)
    details=pd.concat(details,ignore_index=True);annual=pd.concat(annual,ignore_index=True)
    details.to_csv(HERE/'output/full_book_rebalance_attribution.csv',index=False)
    quality=[]
    for horizon in [1,3,5,10,20]:
        frame=details.groupby(f'forward_{horizon}d_status',dropna=False).size().rename('actions').reset_index().rename(columns={f'forward_{horizon}d_status':'status'})
        frame['horizon']=horizon;quality.append(frame)
    pd.concat(quality)[['horizon','status','actions']].to_csv(HERE/'output/full_book_forward_quality_counts.csv',index=False)
    annual.to_csv(HERE/'output/annual_full_book_lot_contribution.csv',index=False)
    annual.groupby(KEY+['year','strategy','category'],as_index=False).pnl.sum().to_csv(HERE/'output/annual_full_book_category_contribution.csv',index=False)
    write_json(HERE/'output/full_book_attribution_status.json',dict(status='COMPLETE',actual_lot_pnl_reconciled=True,buy_horizons='Actual lot with exits and CA; overlapping horizons not additive',sell_horizons='Counterfactual signed stock-coordinate or pre-adjusted ETF return; no retained-lot exit replay. Invalid/missing stock marks or changed coordinate lineage are not estimated. Actual realized disposal P&L separately available',cash='Actual residual cash, zero native interest'))


if __name__=='__main__':main()
