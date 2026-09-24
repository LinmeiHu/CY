"""Evaluate independent frozen PIT quality gates before minute VAP."""
from pathlib import Path
import inspect
import pandas as pd
from five_strategy_bundle.strategies import ogr
from research.shared_capital_v1.causal_adapters import corrected_function

HERE=Path(__file__).parent

def main():
    frame=pd.read_parquet(HERE/'v27_candidates.parquet')
    frame=frame.loc[frame.signal_date.gt('2026-09-16')].copy()
    root=HERE/'cache/pit_full'
    for name in ['select_v28','select_v28r1','select_v28r2']:
        source=inspect.getsource(getattr(ogr,name))
        if '(2018, 2019, 2020, 2021)' not in source:raise RuntimeError('Frozen year tuple moved')
        fn=corrected_function(getattr(ogr,name),[(source,source.replace('(2018, 2019, 2020, 2021)','(2024, 2025, 2026)'))])
        frame=fn(frame,root)
        print(name,len(frame),frame[['symbol','signal_date']].to_dict('records'),flush=True)
        frame.to_parquet(HERE/(name+'.parquet'),index=False)
        if frame.empty:break

if __name__=='__main__':main()
