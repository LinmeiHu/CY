"""Same parent accounts, with continuous initialization and audit observations."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import hashlib
from pathlib import Path

import duckdb
import pandas as pd

from research.shared_capital_v1.common_p0_v06 import replay
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1.validation import account_validation
from research.capital_scaling_v1.run import save_account
from research.capital_scaling_v1.scaling import Scaling
from .audit import HERE, ROOT, ROLL, sha256, write_json, compare_accounts
from .snapshot import CACHE
from .boundary import load_etf, plain

PERIOD='CONTINUOUS_LIVE_PROTOCOL_V1'
END='2026-09-04'


def daily_observation(account,platform,scaling,row):
    row['positions_json']=json.dumps(dict(positions=account.positions,pending=account.pending_positions),sort_keys=True)
    row['lots_json']=json.dumps({eid:{k:plain(lot.get(k)) for k in ['strategy','route','symbol','root_event_id','quantity','pending_quantity','remaining_outlay','entry']}
                                 for eid,lot in account.lots.items()},sort_keys=True,default=str)
    if platform:
        context={k:plain(v) for k,v in vars(platform.native_context).items() if k!='portfolio'}
        row['callback_state_json']=json.dumps(context,sort_keys=True,default=str)


observed_replay=corrected_function(replay,[
    ('daily.append(dict(row,trade_date=when.normalize()))',
     'daily_observation(account,platform,scaling,row)\n            daily.append(dict(row,trade_date=when.normalize()))')],daily_observation=daily_observation)


def load(end):
    data={'actions':pd.read_parquet(ROLL/'atrdr/action_registry.parquet')}
    with duckdb.connect() as c:
        c.execute('SET threads=2')
        for s in ['ATRDR','MCB']:
            entries=pd.read_parquet(CACHE/s.lower()/'precapital_entry_population.parquet')
            entries=entries.loc[entries.signal_date.le(end)].copy()
            registry=pd.DataFrame({'symbol':entries.symbol.unique()})
            c.register('registry',registry)
            prices=c.execute('SELECT d.* FROM read_parquet(?) d JOIN registry USING(symbol) WHERE trade_date<=? ORDER BY symbol,trade_date',
                             [str(CACHE/'daily_with_snapshot.parquet'),end]).fetchdf()
            data[s]=(entries,prices)
        data['gap_daily']=c.execute('SELECT symbol,trade_date,open,close FROM read_parquet(?) WHERE trade_date<=? ORDER BY symbol,trade_date',
                                   [str(CACHE/'daily_with_snapshot.parquet'),end]).fetchdf()
    for s in ['OGR','IFCGR']:
        parent=ROOT/'research/shared_capital_v1/cache'
        old=pd.read_parquet(parent/'ogr/signals.parquet') if s=='OGR' else pd.concat([pd.read_parquet(parent/'ifcgr'/p/'signals.parquet') for p in ['2018_2021','2022_2023']])
        new=pd.read_parquet(ROLL/s.lower()/'signals_post2023.parquet')
        signals=pd.concat([old.loc[old.signal_date.lt('2024-01-01')],new],ignore_index=True)
        data[s]=signals.loc[signals.signal_date.le(end)].copy()
    old=pd.read_parquet(parent/'ogr/outcomes.parquet')
    new=pd.read_parquet(ROLL/'ogr/outcomes_post2023.parquet')
    outcomes=pd.concat([old.loc[old.signal_date.lt('2024-01-01')],new],ignore_index=True)
    outcomes=outcomes.loc[outcomes.signal_date.le(end)].copy()
    # Future exit metadata is deliberately removed from each replay prefix.
    # Active pending exits stay pending; they must not influence admission.
    future=pd.to_datetime(outcomes.exit_date).gt(end)
    outcomes.loc[future,['exit_time','exit_date']]=pd.NaT
    outcomes.loc[future,'exit_raw_price']=float('nan')
    data['gap_outcomes']=outcomes
    data['etf']=load_etf(end)
    return data


def folder(gap,mode,target,mechanic,end,group='accounts'):
    return CACHE/group/f'{gap}__{mode}__{target}__{mechanic}__{end}'


def run_case(case):
    gap,mode,target,mechanic,end,group=case
    dest=folder(*case)
    identity=sha256(HERE/'account_run_input_identity.json')
    if (dest/'receipt.json').exists():
        receipt=json.loads((dest/'receipt.json').read_text())
        if receipt.get('input_identity')!=identity or receipt['case']!=list(case):raise ValueError('account source/input identity drift')
        for name,digest in receipt['hashes'].items():
            if sha256(dest/name)!=digest:raise ValueError('account cache hash drift')
        print('VERIFIED',dest.name,flush=True)
        return receipt
    data=load(end)
    data['gap']=gap
    scaling=None
    if target!='NATIVE':
        native=folder(gap,'independent','NATIVE','FULL_BOOK_NORMALIZATION',end,group)
        if not native.exists() and group=='identity_prefix':
            native=ROLL/'combinations'/f'{gap}_independent_NATIVE'
        home=pd.read_parquet(native/'timeline.parquet').set_index('timestamp')
        before=pd.read_parquet(native/'home_before_funding.parquet').set_index('timestamp')
        home.loc[before.index,before.columns]=before
        data['native_home']={(PERIOD,gap):home.loc[:end]}
        data['native_requests']={}
        for s in ['ATRDR','MCB',gap]:
            intents=pd.read_parquet(native/f'{s.lower()}_intents.parquet')
            for row in intents.to_dict('records'):
                if pd.Timestamp(row['earliest_execution_at'])<=pd.Timestamp(end)+pd.Timedelta(days=1):
                    data['native_requests'][(PERIOD,gap,s,row['event_id'])]=row
        quotes=pd.read_parquet(CACHE/'legal_quotes.parquet')
        quotes=quotes.loc[quotes.timestamp.le(pd.Timestamp(end)+pd.Timedelta(days=1))]
        data['quotes']={pd.Timestamp(t):{r.symbol:dict(price=r.price,buy=bool(r.buy),sell=bool(r.sell)) for r in g.itertuples(index=False)}
                        for t,g in quotes.groupby('timestamp',sort=True)}
        scaling=Scaling(('ATRDR','MCB',gap,'SMV6'),int(target[1:])/100,mode=mode,mechanic=mechanic)
    print('REPLAY',dest.name,flush=True)
    account,nav,results,platform,trace=observed_replay(data,gap,PERIOD,'2018-01-01',end,mode=mode,scaling=scaling)
    calendar=data['etf'][0]['000852.SH'].loc['2018-01-01':end].dropna(subset=['pre_adj_close']).index
    audit=account_validation(nav,calendar)
    if audit['status']!='PASS':raise ValueError(audit)
    save_account(dest,account,nav,scaling)
    pd.DataFrame(account.funding.home_history).to_parquet(dest/'home_before_funding.parquet',index=False)
    for s,result in results.items():
        intents,other,_=result()
        if 'native_priority' in intents:
            intents=intents.copy();intents.native_priority=intents.native_priority.map(json.dumps)
        intents.to_parquet(dest/f'{s.lower()}_intents.parquet',index=False)
    files=sorted(dest.glob('*.parquet'))+sorted(dest.glob('account.json'))+sorted(dest.glob('scaling.json'))
    receipt=dict(case=list(case),input_identity=identity,status='PASS',days=len(nav),initial_nav=account.initial_cash,
                 protocol=PERIOD,hashes={p.name:sha256(p) for p in files})
    write_json(dest/'receipt.json',receipt)
    print('ACCOUNT_PASS',dest.name,len(nav),flush=True)
    return receipt


def group_cases(group):
    structures=[(g,m) for g in ['OGR','IFCGR'] for m in ['independent','confirmation_tag']]
    if group=='identity_prefix':
        return [(r.gap,r.mcb_mode,r.target,'FULL_BOOK_NORMALIZATION','2021-12-31',group)
                for r in pd.read_csv(HERE/'evidence/combined_top5_backtest_curve_selection.csv').itertuples(index=False)]
    if group=='native':
        return [(g,m,'NATIVE','FULL_BOOK_NORMALIZATION',END,'accounts') for g,m in structures]
    if group=='prefixes':
        return [(g,m,'NATIVE','FULL_BOOK_NORMALIZATION',end,'accounts') for end in ['2021-12-31','2022-12-31','2023-12-31','2024-12-31','2025-12-31'] for g,m in structures]
    if group=='scaling':
        return [(g,m,t,mechanic,END,'accounts') for t,mechanic in [('G25','FULL_BOOK_NORMALIZATION'),('G100','FULL_BOOK_NORMALIZATION'),('G100','ENTRY_ONLY'),('G25','ENTRY_ONLY')]
                for g,m in structures]+[('OGR','independent','G75','FULL_BOOK_NORMALIZATION',END,'accounts')]
    raise ValueError(group)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--group',choices=['identity_prefix','native','prefixes','scaling'],required=True)
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    cases=group_cases(args.group)
    binding=json.loads((HERE/'account_run_input_identity.json').read_text())
    for path,digest in binding.items():
        if sha256(Path(path))!=digest:raise ValueError('account input hash drift: '+path)
    if args.group!='identity_prefix':
        protocol=HERE/'contracts/continuous_rollforward_protocol_v1.json'
        receipt=json.loads((HERE/'contracts/continuous_protocol_freeze_receipt.json').read_text())
        if sha256(protocol)!=receipt['sha256']:raise ValueError('continuous contract drift')
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results=list(pool.map(run_case,cases))
    write_json(HERE/'output'/f'{args.group}_run_receipts.json',results)
    if args.group=='identity_prefix':
        rows=[]
        selected=pd.read_csv(HERE/'evidence/combined_top5_backtest_curve_selection.csv')
        for case,old in zip(cases,selected.itertuples(index=False)):
            actual=pd.read_parquet(folder(*case)/'daily.parquet')
            expected=pd.read_parquet(Path(old.source)/'daily.parquet')
            n,errors,passed=compare_accounts(actual,expected,['cash','gross_exposure','nav'])
            if not passed or n!=973:raise ValueError('Top5 identity prefix drift')
            # Quantity-level fills check in addition to NAV. Native lots may be
            # serialized with different nullable dtypes; economic fields must agree.
            a=pd.read_parquet(folder(*case)/'fills.parquet');b=pd.read_parquet(Path(old.source)/'fills.parquet')
            fields=[c for c in ['event_id','root_event_id','strategy','symbol','side','entry','exit','quantity','filled_quantity','price','exit_price','funded_notional'] if c in a and c in b]
            pd.testing.assert_frame_equal(a[fields],b[fields],check_dtype=False,rtol=1e-10,atol=1e-6)
            rows.append(dict(rank=int(old.rank),days=n,**errors,status='PASS',fills_identity='PASS'))
        pd.DataFrame(rows).to_csv(HERE/'output/new_top5_prefix_identity.csv',index=False)


if __name__=='__main__':main()
