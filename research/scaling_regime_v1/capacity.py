"""Descriptive G25 participation; fills are never changed by capacity flags."""
import json
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from .audit import HERE,ROOT,ORIGINAL,write_json,sha256
from .accounts import folder,END
from .snapshot import CACHE
from .economics import require_identity,fills_frame


def main():
    require_identity();orders=[];positions=[];base_sizes={}
    for gap in ['OGR','IFCGR']:
        for mode in ['independent','confirmation_tag']:
            path=folder(gap,mode,'G25','FULL_BOOK_NORMALIZATION',END)
            base_sizes[(gap,mode)]=json.loads((path/'account.json').read_text())['initial_cash']
            daily_account=pd.read_parquet(path/'daily.parquet',columns=['trade_date','marks_json','lots_json'])
            for row in daily_account.itertuples():
                marks=json.loads(row.marks_json);totals={}
                for lot in json.loads(row.lots_json).values():
                    if lot['strategy']=='SMV6':continue
                    key=(lot['strategy'],lot['symbol'])
                    totals[key]=totals.get(key,0.)+(lot['quantity']+(lot.get('pending_quantity') or 0.))*marks[lot['symbol']]
                for (strategy,symbol),value in totals.items():positions.append(dict(gap=gap,mcb_mode=mode,trade_date=row.trade_date,strategy=strategy,symbol=symbol,closing_position_cny=value))
            f=fills_frame(path)
            f=f.loc[f.strategy.ne('SMV6')]
            group=f.groupby(['timestamp','root','strategy','symbol','side'],as_index=False).agg(notional=('notional','sum'),fee=('fee','sum'))
            group['gap']=gap;group['mcb_mode']=mode;group['trade_date']=group.timestamp.dt.normalize();orders.append(group)
    orders=pd.concat(orders,ignore_index=True)
    registry=orders[['symbol']].drop_duplicates()
    with duckdb.connect() as c:
        c.register('registry',registry)
        daily=c.execute('''SELECT symbol,trade_date,amount AS daily_turnover_cny,
            avg(amount) OVER(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS trailing_ADV20_cny
            FROM read_parquet(?) JOIN registry USING(symbol) ORDER BY symbol,trade_date''',[str(CACHE/'daily_with_snapshot.parquet')]).fetchdf()
    orders=orders.merge(daily,on=['symbol','trade_date'],how='left',validate='many_to_one')
    positions=pd.DataFrame(positions)
    orders=orders.merge(positions,on=['gap','mcb_mode','trade_date','strategy','symbol'],how='left',validate='many_to_one')
    orders['closing_position_cny']=orders.closing_position_cny.fillna(0.)
    orders['position_over_daily_turnover']=orders.closing_position_cny/orders.daily_turnover_cny
    minute,source=minute_amounts(orders[['timestamp','symbol']].drop_duplicates())
    orders=orders.merge(minute,on=['timestamp','symbol'],how='left',validate='many_to_one')
    orders['order_over_minute_amount']=orders.notional/orders.minute_amount_cny.where(orders.minute_amount_cny.gt(0))
    valid=orders.daily_turnover_cny.notna() & orders.daily_turnover_cny.gt(0)
    orders['participation_daily']=orders.notional.div(orders.daily_turnover_cny).where(valid)
    orders['participation_ADV20']=orders.notional.div(orders.trailing_ADV20_cny).where(orders.trailing_ADV20_cny.gt(0))
    orders['data_status']=np.where(valid,'OBSERVED_DAILY_TURNOVER','DATA_INPUT_MISSING')
    orders['denominator_timing']='Same-day realized turnover is retrospective capacity diagnostic; trailing ADV excludes current day'
    orders['order_basis']='Aggregate actual fills by native root/symbol/side/timestamp; no exchange-order-id claim'
    expanded=[]
    for multiple in [1,2,5,10]:
        f=orders.copy();f['account_size_multiple']=multiple;f['diagnostic_order_notional']=f.notional*multiple
        for column in ['participation_daily','participation_ADV20','order_over_minute_amount','position_over_daily_turnover']:
            f[column]=f[column]*multiple
        f['interpretation']='Actual current-account orders' if multiple==1 else 'Fixed-order proportional stress only; no fill or strategy path replay'
        for value in [1,2,5,10,20]:f['gt_'+str(value)+'pct']=f.participation_daily.gt(value/100).where(valid)
        expanded.append(f)
    output=pd.concat(expanded);output.to_csv(HERE/'output/g25_capacity_orders.csv',index=False)
    summaries=[]
    for key,f in output.groupby(['gap','mcb_mode','strategy','account_size_multiple']):
        summaries.append(dict(zip(['gap','mcb_mode','strategy','account_size_multiple'],key),base_initial_nav_cny=base_sizes[key[:2]],diagnostic_initial_nav_cny=base_sizes[key[:2]]*key[3],orders=len(f),independent_dates=f.trade_date.nunique(),
            missing_denominator=int(f.participation_daily.isna().sum()),max_participation=float(f.participation_daily.max()),
            **{'p'+str(q)+'_participation':float(f.participation_daily.quantile(q/100)) for q in [50,75,90,95,99]},
            **{'orders_gt_'+str(v)+'pct':int(f['gt_'+str(v)+'pct'].fillna(False).sum()) for v in [1,2,5,10,20]}))
    pd.DataFrame(summaries).to_csv(HERE/'output/g25_capacity_summary.csv',index=False)
    pd.DataFrame(summaries).to_csv(HERE/'output/account_size_capacity_reference.csv',index=False)
    quantiles=[]
    for key,frame in orders.groupby(['gap','mcb_mode','strategy']):
        for metric in ['participation_daily','participation_ADV20','order_over_minute_amount','position_over_daily_turnover']:
            quantiles.append(dict(zip(['gap','mcb_mode','strategy'],key),metric=metric,observed=frame[metric].notna().sum(),missing=frame[metric].isna().sum(),maximum=frame[metric].max(),**{'p'+str(q):frame[metric].quantile(q/100) for q in [50,75,90,95,99]}))
    pd.DataFrame(quantiles).to_csv(HERE/'output/g25_capacity_percentiles.csv',index=False)
    orders.to_csv(HERE/'output/g25_capacity_audit.csv',index=False)
    flags=[]
    attributed=pd.read_csv(HERE/'output/annual_event_contribution.csv')
    attributed=attributed.loc[attributed.target.eq('G25') & attributed.mechanic.eq('FULL_BOOK_NORMALIZATION')]
    for key,frame in orders.groupby(['gap','mcb_mode','strategy',orders.trade_date.dt.year]):
        gap,mode,strategy,year=key
        for denominator in ['participation_daily','participation_ADV20','order_over_minute_amount']:
            for threshold in [.01,.02,.05,.1,.2]:
                flagged=frame.loc[frame[denominator].gt(threshold)]
                pnl=attributed.loc[attributed.gap.eq(gap)&attributed.mcb_mode.eq(mode)&attributed.strategy.eq(strategy)&attributed.year.eq(year)&attributed.root.isin(flagged.root)]
                flags.append(dict(gap=gap,mcb_mode=mode,strategy=strategy,year=year,denominator=denominator,threshold=threshold,count=len(flagged),fraction=len(flagged)/len(frame),observed_denominators=int(frame[denominator].notna().sum()),fraction_of_observed=len(flagged)/max(1,int(frame[denominator].notna().sum())),notional=flagged.notional.sum(),unique_roots=flagged.root.nunique(),pnl_of_unique_flagged_roots_in_year=pnl.pnl.sum(),pnl_scope='Descriptive actual root-year P&L, counted once per threshold; not causal market impact'))
    pd.DataFrame(flags).to_csv(HERE/'output/g25_capacity_flags.csv',index=False)
    daily_aggregate=orders.groupby(['gap','mcb_mode','trade_date','symbol'],as_index=False).agg(notional=('notional','sum'),daily_turnover_cny=('daily_turnover_cny','first'))
    daily_aggregate['all_sides_daily_participation']=daily_aggregate.notional/daily_aggregate.daily_turnover_cny
    daily_aggregate.to_csv(HERE/'output/g25_capacity_symbol_day.csv',index=False)
    write_json(HERE/'output/g25_capacity_status.json',dict(status='COMPLETE' if valid.all() else 'COMPLETE_WITH_MISSING_DENOMINATORS',orders=len(orders),missing=int((~valid).sum()),fills_modified=False,unit='CNY',source='Frozen daily amount; full_market.py casts original amount without scaling',minute_capacity='EXACT_MATCHED_REGISTERED_MINUTE_AMOUNT;UNMATCHED_REMAINS_NA',missing_minute_denominators=int(orders.order_over_minute_amount.isna().sum()),missing_minute_observations=int(orders.minute_amount_cny.isna().sum()),nonpositive_minute_amounts=int(orders.minute_amount_cny.le(0).sum()),etf_scope='Frozen local per-order volume cap only; no native aggregate platform-equivalence claim'))


def minute_amounts(keys):
    config=json.loads((ROOT/'research/five_strategy_exit_risk_v1/input_config.json').read_text())['inputs']
    root=Path(config['raw_minute_root']);original=ORIGINAL/'research/capital_scaling_v1'
    rows=[];sources=[]
    for year,requested in keys.groupby(keys.timestamp.dt.year):
        paths=[root/f'{year}_day_parquet_none.parquet']
        if year==2026:
            paths.append(root/'2026_qmt_tail.parquet')
            symbols=json.loads((original/'stock_minute_request.json').read_text())['symbols']
            paths.extend(original/'qmt_stock_delta'/f'{symbol}_1m.parquet' for symbol in symbols)
        cache=CACHE/f'capacity_minutes_{year}.parquet'
        if cache.exists():frame=pd.read_parquet(cache)
        else:
            with duckdb.connect() as c:
                c.execute('SET threads=2');c.register('keys',requested)
                frame=c.execute("SELECT r.qmt_code symbol,r.bar_end_time AS \"timestamp\",r.amount minute_amount_cny,r.volume minute_volume_source_units FROM read_parquet(?,union_by_name=true) r JOIN keys k ON r.qmt_code=k.symbol AND r.bar_end_time=k.timestamp WHERE r.period='1m' AND r.adjust='none'",[[str(p) for p in paths]]).fetchdf()
            duplicates=frame.groupby(['timestamp','symbol'])[['minute_amount_cny','minute_volume_source_units']].nunique()
            assert not duplicates.gt(1).any().any(),'Disagreeing source minute observations'
            frame=frame.drop_duplicates(['timestamp','symbol']).sort_values(['timestamp','symbol'])
            frame.to_parquet(cache,index=False)
        rows.append(frame);sources.extend(str(p) for p in paths)
        print('CAPACITY_MINUTE_MATCH',year,len(frame),'/',len(requested),flush=True)
    write_json(HERE/'output/capacity_minute_source_paths.json',sorted(set(sources)))
    return pd.concat(rows,ignore_index=True),sources


if __name__=='__main__':main()
