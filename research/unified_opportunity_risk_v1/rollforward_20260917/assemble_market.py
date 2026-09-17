"""QMT daily prices plus captured date-effective trading-state snapshots."""
import json
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
from research.portfolio_closure_v1 import repair
from .prepare_stock import HERE,CACHE,END


def main():
    root=CACHE/'qmt_market';root.mkdir(exist_ok=True)
    rows=[];checks=[];coverage=[]
    requested=set((HERE/'symbols_baostock.txt').read_text().splitlines())
    bysymbol={}
    for file in sorted((CACHE/'frozen_reference/universe').glob('*.json')):
        payload=json.loads(file.read_text())
        for row in payload['rows']:
            assert row['code'] in requested
            bysymbol.setdefault(row['code'],{})[payload['trade_date']]=row
    for code,states in sorted(bysymbol.items()):
        symbol=code.split('.')[1]+'.'+code.split('.')[0].upper()
        q=pd.read_parquet(CACHE/'qmt_stock_daily'/f'{symbol}.parquet');q.trade_date=pd.to_datetime(q.trade_date)
        # A-share quoted prices are integer cents; remove binary API representation noise.
        q[['open','high','low','close','preClose']]=q[['open','high','low','close','preClose']].round(2)
        q=q.set_index(q.trade_date.dt.strftime('%Y-%m-%d'))
        missing=[]
        for day,state in sorted(states.items()):
            if day not in q.index:
                missing.append(day)
                assert state['trade_status']=='0',(symbol,day,'missing active quote')
                rows.append(dict(date=day,code=code,open='',high='',low='',close='',preclose='',volume='',amount='',adjustflag='3',turn='',pctChg='',tradestatus='0',isST='1' if 'ST' in state['code_name'].upper() else '0',source='qmt-missing-suspended-bar+captured-baostock-universe'))
                continue
            r=q.loc[day];assert isinstance(r,pd.Series)
            active=state['trade_status']=='1'
            assert (not active) or (r.close>0 and r.volume>0),(symbol,day,'active quote invalid')
            rows.append(dict(date=day,code=code,open=str(r.open),high=str(r.high),low=str(r.low),close=str(r.close),
                preclose=str(r.preClose),volume=str(r.volume*100),amount=str(r.amount),adjustflag='3',turn='',pctChg='',
                tradestatus=state['trade_status'],isST='1' if 'ST' in state['code_name'].upper() else '0',
                source='qmt-none-daily+captured-baostock-universe'))
        coverage.append(dict(symbol=symbol,expected_days=len(states),missing_days='|'.join(missing)))
        old=CACHE/'market/_parts/daily'/f"{code.replace('.','_')}.parquet"
        if old.exists():
            b=pd.read_parquet(old).set_index('date');j=b.join(q,how='inner',lsuffix='_bao',rsuffix='_qmt')
            j=j.loc[pd.to_numeric(j.tradestatus).eq(1)&pd.to_numeric(j.volume_bao).gt(0)]
            for day,r in j.iterrows():
                price=max(abs(float(r[f'{f}_bao'])-float(r[f'{f}_qmt'])) for f in ['open','high','low','close'])
                checks.append(dict(symbol=symbol,trade_date=day,max_abs_ohlc_error=price,
                    volume_relative_error=abs(float(r.volume_bao)-r.volume_qmt*100)/float(r.volume_bao),
                    amount_relative_error=abs(float(r.amount_bao)-r.amount_qmt)/float(r.amount_bao)))
    cov=pd.DataFrame(coverage);cov.to_csv(HERE/'qmt_stock_coverage.csv',index=False)
    # Missing bars are retained as NULL only for independently confirmed suspended sessions.
    checks=pd.DataFrame(checks);checks.to_csv(HERE/'qmt_baostock_daily_comparison.csv',index=False)
    proof=dict(overlap_symbols=int(checks.symbol.nunique()),overlap_rows=len(checks),
        ohlc_within_one_cent=float(checks.max_abs_ohlc_error.le(.0100001).mean()),
        volume_within_1pct=float(checks.volume_relative_error.le(.01).mean()),
        amount_within_1pct=float(checks.amount_relative_error.le(.01).mean()))
    repair.write_json(HERE/'qmt_daily_cross_provider_audit.json',proof)
    assert proof['overlap_symbols']>=1000 and min(proof[k] for k in ['ohlc_within_one_cent','volume_within_1pct','amount_within_1pct'])>=.95,proof
    pd.DataFrame(rows).to_parquet(root/'raw_daily.parquet',index=False)
    shutil.copytree(CACHE/'frozen_reference/index_daily',root/'index_daily',dirs_exist_ok=True)
    inputs=list((CACHE/'qmt_stock_daily').glob('*.parquet'))+list((CACHE/'frozen_reference/universe').glob('*.json'))+list((root/'index_daily').glob('*.parquet'))
    repair.write_json(root/'manifest.json',dict(status='PASS',end=END,rows=len(rows),symbols=len(bysymbol),
        source='QMT raw daily and captured date-effective trading states',
        source_turnover_rate='Unavailable in QMT raw daily; unchanged registered missing-turnover branch applies; no inferred turnover used',
        hashes={'raw_daily_sha256':repair.digest(root/'raw_daily.parquet')},
        files={str(p):repair.digest(p) for p in inputs},cross_provider=proof))
    print('QMT STOCK MARKET PASS',proof,flush=True)


if __name__=='__main__':main()
