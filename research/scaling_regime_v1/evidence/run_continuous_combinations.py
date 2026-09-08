"""Continuous native and capital-scaled accounts, without period NAV splicing."""
import argparse
import json
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
from five_strategy_bundle.strategies import smv6
from research.shared_capital_v1.common_p0_v06 import replay
from research.shared_capital_v1.validation import account_validation
from research.capital_scaling_v1.run import save_account
from research.capital_scaling_v1.scaling import Scaling
from research.shared_capital_v1.causal_adapters import corrected_function
from build_rollforward_inputs import OUT,END

PARENT=Path(__file__).resolve().parents[2]/'shared_capital_v1'
PERIOD='CONTINUOUS_2018_2026'
replay=corrected_function(replay,[
    ("daily.append(dict(row,trade_date=when.normalize()))",
     "daily.append(dict(row,trade_date=when.normalize()))\n            if len(daily)==1 or daily[-2]['trade_date'].year != when.year:\n                print('ACCOUNT_YEAR',when.year,'NAV',round(row['nav'],2),flush=True)")])


def load(gap):
    data={'gap':gap,'actions':pd.read_parquet(OUT/'atrdr/action_registry.parquet')}
    with duckdb.connect() as c:
        for s in ['ATRDR','MCB']:
            entries=pd.read_parquet(OUT/s.lower()/'precapital_entry_population.parquet')
            registry=pd.DataFrame({'symbol':entries.symbol.unique()});c.register('registry',registry)
            prices=c.execute('SELECT d.* FROM read_parquet(?) d JOIN registry USING(symbol)',[str(OUT/'daily.parquet')]).fetchdf()
            data[s]=(entries,prices)
        data['gap_daily']=c.execute('SELECT symbol,trade_date,open,close FROM read_parquet(?)',[str(OUT/'daily.parquet')]).fetchdf()
    for s in ['OGR','IFCGR']:
        old=pd.read_parquet(PARENT/'cache/ogr/signals.parquet') if s=='OGR' else pd.concat([pd.read_parquet(PARENT/'cache/ifcgr'/p/'signals.parquet') for p in ['2018_2021','2022_2023']],ignore_index=True)
        new=pd.read_parquet(OUT/s.lower()/'signals_post2023.parquet')
        data[s]=pd.concat([old.loc[pd.to_datetime(old.signal_date)<'2024-01-01'],new],ignore_index=True)
        assert not data[s].gap_id.duplicated().any()
    old=pd.read_parquet(PARENT/'cache/ogr/outcomes.parquet')
    new=pd.read_parquet(OUT/'ogr/outcomes_post2023.parquet')
    data['gap_outcomes']=pd.concat([old.loc[pd.to_datetime(old.signal_date)<'2024-01-01'],new],ignore_index=True)
    d,m={},{}
    for symbol in [smv6.canonical_symbol(s) for s in smv6.raw_pool()]+['000852.SH']:
        d[symbol]=smv6.load_daily(OUT/'smv6',symbol)
        m[symbol]=smv6.load_minute(OUT/'smv6',symbol)
    a=pd.read_parquet(OUT/'smv6/availability.parquet');a['trade_date']=pd.to_datetime(a.trade_date).dt.date
    data['etf']=(d,m,a)
    return data


def run(gap,target,mode):
    data=load(gap)
    folder=OUT/'combinations'/f'{gap}_{mode}_{target}';folder.mkdir(parents=True,exist_ok=True)
    scaling=None
    if target!='NATIVE':
        native=OUT/'combinations'/f'{gap}_independent_NATIVE'
        home=pd.read_parquet(native/'timeline.parquet').set_index('timestamp')
        before=pd.read_parquet(native/'home_before_funding.parquet').set_index('timestamp')
        home.loc[before.index,before.columns]=before
        data['native_home']={(PERIOD,gap):home};data['native_requests']={}
        for s in ['ATRDR','MCB',gap]:
            for row in pd.read_parquet(native/f'{s.lower()}_intents.parquet').to_dict('records'):
                data['native_requests'][(PERIOD,gap,s,row['event_id'])]=row
        q=pd.read_parquet(OUT/'legal_quotes.parquet')
        data['quotes']={pd.Timestamp(t):{r.symbol:dict(price=r.price,buy=bool(r.buy),sell=bool(r.sell)) for r in group.itertuples(index=False)} for t,group in q.groupby('timestamp',sort=True)}
        scaling=Scaling(('ATRDR','MCB',gap,'SMV6'),int(target[1:])/100,mode=mode)
    print('REPLAY',gap,target,mode,'2018-01-01',END,flush=True)
    account,nav,results,platform,trace=replay(data,gap,PERIOD,'2018-01-01',END,mode=mode,scaling=scaling)
    calendar=data['etf'][0]['000852.SH'].loc['2018-01-01':END].dropna(subset=['pre_adj_close']).index
    audit=account_validation(nav,calendar)
    if audit['status']!='PASS':raise ValueError(audit)
    save_account(folder,account,nav,scaling)
    pd.DataFrame(account.funding.home_history).to_parquet(folder/'home_before_funding.parquet',index=False)
    for s,result in results.items():
        intents,other,_=result()
        if 'native_priority' in intents:
            intents=intents.copy();intents['native_priority']=intents.native_priority.map(json.dumps)
        intents.to_parquet(folder/f'{s.lower()}_intents.parquet',index=False)
    audit.update(gap=gap,target=target,mode=mode,end=str(nav.trade_date.max()),days=len(nav),initial_nav=account.initial_cash,final_nav=float(nav.nav.iloc[-1]),min_cash=float(nav.cash.min()))
    (folder/'receipt.json').write_text(json.dumps(audit,indent=2,default=str))
    print(audit,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--gap',choices=['OGR','IFCGR'],required=True);parser.add_argument('--target',default='NATIVE');parser.add_argument('--mode',default='independent')
    args=parser.parse_args();run(args.gap,args.target,args.mode)
