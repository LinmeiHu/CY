"""Run frozen OGR V13 and V27 on the refreshed daily chronology."""
from pathlib import Path
import inspect
import duckdb
import pandas as pd
from five_strategy_bundle.strategies import ogr
from research.shared_capital_v1.causal_adapters import corrected_function

HERE=Path(__file__).parent
PRIOR=HERE.parent/'rollforward_20260917'

def main():
    path=HERE/'cache/daily_with_snapshot.parquet'
    with duckdb.connect() as conn:
        frame=conn.execute("SELECT * FROM read_parquet(?) WHERE trade_date>='2025-01-01' ORDER BY symbol,trade_date",[str(path)]).fetchdf()
    frame['symbol_seq']=frame.groupby('symbol',sort=False).cumcount()
    print('DAILY',len(frame),frame.trade_date.max(),flush=True)
    gaps=ogr.build_all_true_gaps(frame)
    print('GAPS',len(gaps),flush=True)
    v13=ogr.build_v13_candidates(frame,gaps)
    old=pd.read_parquet(PRIOR/'cache/ogr/v13_post2023_candidates.parquet')
    cutoff=pd.Timestamp('2026-09-07')
    a=set(map(tuple,v13.loc[v13.signal_date.ge(cutoff),['gap_id','signal_date']].to_records(index=False)))
    b=set(map(tuple,old.loc[old.signal_date.ge(cutoff),['gap_id','signal_date']].to_records(index=False)))
    if not b.issubset(a):raise RuntimeError('Prior V13 signals disappeared: '+str(b-a))
    fresh=v13.loc[v13.signal_date.gt('2026-09-16')]
    print('FRESH_V13',len(fresh),fresh[['symbol','signal_date']].to_dict('records'),flush=True)
    v13.to_parquet(HERE/'v13_candidates.parquet',index=False)
    source=inspect.getsource(ogr.select_v27)
    v27=corrected_function(ogr.select_v27,[('(2017, 2018, 2019, 2020, 2021)','(2024, 2025, 2026)')])(v13)
    fresh27=v27.loc[v27.signal_date.gt('2026-09-16')]
    print('FRESH_V27',len(fresh27),fresh27[['symbol','signal_date']].to_dict('records'),flush=True)
    v27.to_parquet(HERE/'v27_candidates.parquet',index=False)

if __name__=='__main__':main()
