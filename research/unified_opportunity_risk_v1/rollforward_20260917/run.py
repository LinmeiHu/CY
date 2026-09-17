"""Full 32-cell replay on latest authorized inputs, preserving frozen economics."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import argparse
import json
import time
import duckdb
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1 import engine
from research.unified_opportunity_risk_v1.exposure_scale import run as previous
from research.unified_opportunity_risk_v1.max_fill_security_cap.run import CapPool
from research.shared_capital_v1.causal_adapters import corrected_function
from research.capital_scaling_v1.run import save_account
from five_strategy_bundle.strategies import smv6
from .prepare_stock import HERE,CACHE,END

OUT=HERE/'output'
XS=previous.SCALES
YS=[.1,.15,.2,.3]
_DATA=None
_LIQ=None
_REQ=None


def directory(x,y):return OUT/'accounts'/f'{previous.label(x)}_Y{round(y*100)}'


def identity():
    paths=[Path(__file__),HERE/'contract.json',HERE/'input_manifest.json',Path(engine.__file__),Path(previous.__file__),
        Path(__import__(CapPool.__module__,fromlist=['x']).__file__),previous.PARENT_OUT/'calibration_frozen.json',previous.PARENT_OUT/'risk_references_frozen.json']
    return {str(p):repair.digest(p) for p in paths}


def verify(x,y):
    dest=directory(x,y);r=json.loads((dest/'receipt.json').read_text());assert r['identity']==identity()
    for n,h in r['hashes'].items():assert repair.digest(dest/n)==h
    return r


def load():
    global _DATA,_LIQ,_REQ
    if _DATA is not None:return _DATA,_LIQ,_REQ
    data={'actions':pd.read_parquet(CACHE/'action_registry.parquet')}
    with duckdb.connect() as c:
        c.execute('SET threads=2')
        for strategy in ['ATRDR','MCB']:
            entries=pd.read_parquet(CACHE/strategy.lower()/'precapital_entry_population.parquet')
            registry=pd.DataFrame({'symbol':entries.symbol.unique()});c.register('registry',registry)
            prices=c.execute('SELECT d.* FROM read_parquet(?) d JOIN registry USING(symbol) ORDER BY symbol,trade_date',[str(CACHE/'daily_with_snapshot.parquet')]).fetchdf()
            data[strategy]=(entries,prices)
        data['gap_daily']=c.execute('SELECT symbol,trade_date,open,close FROM read_parquet(?) ORDER BY symbol,trade_date',[str(CACHE/'daily_with_snapshot.parquet')]).fetchdf()
        liquidity=c.execute('''SELECT symbol,trade_date,
          CASE WHEN count(CASE WHEN amount>0 AND volume>0 AND abs(amount/(volume*close)-1)<0.5 THEN 1 END) OVER w=20
          THEN avg(amount) OVER w ELSE NULL END adv20 FROM read_parquet(?)
          WINDOW w AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)''',[str(CACHE/'daily_with_snapshot.parquet')]).fetchdf()
    for strategy in ['OGR','IFCGR']:data[strategy]=pd.read_parquet(CACHE/strategy.lower()/'signals_all.parquet')
    data['gap_outcomes']=pd.read_parquet(CACHE/'ogr/outcomes_all.parquet')
    daily={};minute={}
    for symbol in [smv6.canonical_symbol(s) for s in smv6.raw_pool()]+['000852.SH']:
        daily[symbol]=smv6.load_daily(CACHE/'smv6',symbol).loc[:END]
        minute[symbol]=smv6.load_minute(CACHE/'smv6',symbol)
    data['etf']=(daily,minute,pd.read_parquet(CACHE/'smv6/availability.parquet'))
    symbols=set(data['ATRDR'][0].symbol)|set(data['MCB'][0].symbol)|set(data['OGR'].symbol)
    liquidity=liquidity.loc[liquidity.trade_date.ge('2018-01-01')&liquidity.symbol.isin(symbols)&liquidity.adv20.notna()]
    _LIQ={(r.symbol,r.trade_date):r.adv20 for r in liquidity.itertuples(index=False)}
    req=pd.read_parquet(previous.PARENT_OUT/'native_replay/OGR/precapital.parquet')
    _REQ={(r.strategy,r.event_id):r.requested_increase_notional for r in req.itertuples(index=False)}
    _DATA=data
    return _DATA,_LIQ,_REQ


def job(pair):
    x,y=pair;dest=directory(x,y);dest.mkdir(parents=True,exist_ok=True)
    if (dest/'receipt.json').exists():verify(x,y);print('VERIFIED',x,y,flush=True);return
    binding=identity();data,liq,req=load();start=time.monotonic()
    config=dict(previous.BASE_CONFIG,exposure_scale=x,risk_profile=1. if x=='MAX_FILL' else x,security_cap=y)
    print('START',x,y,flush=True)
    replay=corrected_function(engine.run,[],Pool=CapPool,PoolPlatform=previous.Platform)
    a,d,p,platform=replay(data,config,liq,req,END)
    assert str(pd.to_datetime(d.trade_date).max().date())==END
    save_account(dest,a,d,None)
    for name,rows in [('admission',p.admissions),('risk_history',p.risk_history),('cash_attribution',p.cash_attribution),('smv6_events',platform.events),('cash_distributions',a.cash_distributions)]:
        pd.DataFrame(rows).to_parquet(dest/f'{name}.parquet',index=False)
    repair.write_json(dest/'receipt.json',dict(status='PASS',X=x,Y=y,end=END,config=config,identity=binding,seconds=time.monotonic()-start,
        hashes={f.name:repair.digest(f) for f in dest.glob('*.parquet')}|{'account.json':repair.digest(dest/'account.json')}))
    print('PASS',x,y,round(time.monotonic()-start,1),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=3);args=parser.parse_args()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:list(pool.map(job,[(x,y) for x in XS for y in YS]))
