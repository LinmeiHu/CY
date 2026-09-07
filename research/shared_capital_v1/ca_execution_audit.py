"""Held-action audit from verified fill prefixes; unreachable history stays explicit.

No outcome replay. Accepted fills here establish historical holding overlap only;
they are never inputs to a signal or allocator. Potential future overlaps are a
separate coverage envelope, never counted as actual held events.
"""
import json
from pathlib import Path
import duckdb
import pandas as pd
from research.shared_capital_v1.run_shared_capital_v1 import HERE, sha256
from research.shared_capital_v1.universe import verify


def holding_intervals(fills, through):
    buys=fills.loc[fills.side.eq('BUY')].copy()
    if buys.event_id.isna().any() or buys.event_id.duplicated().any():raise ValueError('invalid fill identity')
    sells=fills.loc[fills.side.eq('SELL')]
    exits=sells.groupby('event_id').exit.max()
    buys['holding_end']=buys.event_id.map(exits).fillna(pd.Timestamp(through)+pd.Timedelta(hours=23,minutes=59))
    buys['record_cutoff']=pd.Timestamp(through)+pd.Timedelta(hours=15)
    return buys


def overlap(intervals, actions):
    i=intervals.copy();i['raw_symbol']=i.symbol.str[:6]
    j=i.merge(actions,left_on='raw_symbol',right_on='symbol',suffixes=('_holding','_action'))
    record=j.record_date+pd.Timedelta(hours=15)
    # Record-date close determines ownership, not ex-date or announcement date.
    return j.loc[record.ge(j.entry)&record.lt(j.holding_end)&record.le(j.record_cutoff)].copy()


def run():
    verify()
    config=json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs']
    con=duckdb.connect(); parts=[]
    for key in ('qd010_distributions','qd010_rights'):
        f=con.execute("SELECT * FROM read_parquet(?) WHERE effective_date BETWEEN '2014-01-01' AND '2023-12-31'",[config[key]]).fetchdf()
        f['registered_source']=config[key];parts.append(f)
    actions=pd.concat(parts,ignore_index=True);actions.symbol=actions.symbol.str.zfill(6)
    rows=[];coverage=[];potentials=[]
    for strategy in ('ATRDR','MCB','OGR','IFCGR'):
        folder=HERE/'cache'/strategy.lower()
        if strategy in ('ATRDR','MCB'):
            fills=pd.read_parquet(folder/'native_continuous/fills.parquet')
            nav=pd.read_parquet(folder/'native_continuous/nav.parquet');through=nav.trade_date.max()
            population=pd.read_parquet(folder/'precapital_entry_population.parquet')
            # All incomplete holdings conservatively extend to 2023. This is an
            # audit search envelope, NOT an invented native holding horizon.
            potential=population.rename(columns={'entry_date':'entry'}).copy()
            potential['holding_end']=pd.to_datetime(potential.exit_date).fillna(pd.Timestamp('2024-01-01'))
            potential['record_cutoff']=pd.Timestamp('2023-12-31')
            pp=overlap(potential,actions)
            pp['strategy']=strategy;pp['holding_overlap']='POTENTIAL_ONLY_NOT_FUNDED_STATE'
            potentials.append(pp)
            intervals=holding_intervals(fills,through)
        else:
            frames=[pd.read_parquet(folder/p/'p0_fills.parquet') for p in ('2018_2021','2022_2023')]
            fills=pd.concat(frames,ignore_index=True);through=pd.Timestamp('2023-12-29')
            intervals=holding_intervals(fills,through)
            # Previously validated both boundaries flat; segment resets cannot
            # alter the record-date overlap identities. Quantity is diagnostic
            # for 2022 until continued-account fills are materialized.
        covered=overlap(intervals,actions)
        coverage.append(dict(strategy=strategy,through=str(through.date()),history_required_through='2023-12-29',
            status='PREFIX_ONLY_ENGINEERING_BLOCKED' if through<pd.Timestamp('2023-12-29') else 'OVERLAP_IDENTITIES_COVERED',
            quantity_scope='NATIVE_CONTINUOUS_COORDINATE' if strategy in ('ATRDR','MCB') else 'PER_SEGMENT_DIAGNOSTIC_RAW; 2022 continuation quantity pending'))
        for x in covered.itertuples(index=False):
            ratio=float(x.share_multiplier)-1 if pd.notna(x.share_multiplier) else None
            missing='tradable_date' if ratio and pd.isna(x.share_credit_date) else ''
            if pd.isna(x.record_date):missing='record_date'
            if pd.isna(x.pay_date) and x.cash_per_share_gross:missing=missing or 'cash_payment_date'
            rows.append(dict(strategy=strategy,route=x.route,symbol=x.symbol_holding,action_id=x.event_id_action,
                holding_event_id=x.event_id_holding,action_type=x.event_type,holding_overlap=True,
                announcement_date=x.announcement_date,record_date=x.record_date,ex_date=x.effective_date,
                accounting_effective_date=None,tradable_date=None,cash_payment_date=x.pay_date,
                share_ratio=ratio,cash_ratio=x.cash_per_share_gross,tradable_quantity_before=None,
                pending_quantity_before=None,native_quantity_before=x.quantity,quantity_basis=x.price_basis,
                source=x.registered_source,source_grade=x.knowledge_quality,available_at=x.known_at,raw_hash=x.response_sha256,
                status='EXECUTION_RECONSTRUCTION_REQUIRED',first_missing_field=missing or 'physical_quantity_and_accounting_transition'))
    pd.DataFrame(rows).sort_values(['strategy','record_date','symbol','holding_event_id']).to_csv(HERE/'output/corporate_action_execution_completeness.csv',index=False)
    pd.DataFrame(coverage).to_csv(HERE/'output/corporate_action_audit_coverage.csv',index=False)
    p=pd.concat(potentials,ignore_index=True)
    fields=['strategy','symbol_action','event_id_action','record_date','effective_date','share_multiplier','cash_per_share_gross','share_credit_date','pay_date','announcement_date','holding_overlap','registered_source','execution_timing_resolved']
    p[fields].drop_duplicates().sort_values(['strategy','effective_date','symbol_action']).to_csv(HERE/'output/corporate_action_potential_envelope.csv',index=False)
    con.close()
    print('Verified-prefix held action rows',len(rows),'potential search rows',len(p),'coverage',coverage)
    return rows


if __name__=='__main__':run()
