"""Original frozen producers on the extended data; no signal optimization."""
import argparse
import inspect
import shutil
from pathlib import Path
import duckdb
import pandas as pd
from five_strategy_bundle.strategies import mcb
from research.scaling_regime_v1 import snapshot
from research.scaling_regime_v1.evidence import build_rollforward_inputs as producer
from research.shared_capital_v1.causal_adapters import corrected_function
from research.portfolio_closure_v1 import repair
from .prepare_stock import CACHE,HERE,END


def main(stage):
    producer.OUT=CACHE;producer.END=END
    daily=CACHE/'daily_with_snapshot.parquet'
    if stage=='ATRDR':
        producer.screens(daily);producer.entries(daily,'ATRDR')
    elif stage=='MCB':
        # Reuse the exact two feature/state SQL statements from frozen snapshot.prepare.
        source=inspect.getsource(snapshot.prepare)
        begin=source.index("        c.execute(f'''COPY (WITH w")
        end=source.index('    proof = dict')
        function="def features():\n    with duckdb.connect() as c:\n        c.execute('SET threads=4')\n"+source[begin:end]
        namespace=dict(duckdb=duckdb,CACHE=CACHE)
        exec(compile(function,str(HERE/'build_signals.py'),'exec'),namespace)
        namespace['features']()
        folder=CACHE/'mcb';folder.mkdir(exist_ok=True)
        v53=snapshot.producer(END)(CACHE/'mcb_features.parquet',CACHE/'mcb_market_industry_state.parquet',folder/'v53.parquet')
        v65=mcb.build_v65(v53,folder/'v65.parquet');mcb.build_v72(v65,folder/'signals.parquet')
        producer.entries(daily,'MCB')
    elif stage=='OGR':
        producer.gap_candidates(daily)
        candidates=pd.read_parquet(CACHE/'ogr/v13_post2023_candidates.parquet')
        from five_strategy_bundle.strategies import ogr
        select=corrected_function(ogr.select_v27,[('(2017, 2018, 2019, 2020, 2021)','(2024, 2025, 2026)')])
        pre=select(candidates);new=pre.loc[pre.signal_date.gt('2026-09-04')]
        new.to_parquet(CACHE/'ogr/new_daily_qualified_candidates.parquet',index=False)
        print('NEW OGR PRE-VAP',len(new),new[['symbol','signal_date']].to_dict('records'),flush=True)
        return
    old=pd.read_parquet(repair.CACHE/stage.lower()/'precapital_entry_population.parquet')
    new=pd.read_parquet(CACHE/stage.lower()/'precapital_entry_population.parquet')
    fields=[c for c in ['event_id','symbol','signal_date','entry_date','entry_price','route','lane','source_rank_order','rank1','rank2','rank3'] if c in old and c in new]
    missing=set(old.event_id)-set(new.event_id);assert not missing,(stage,'missing historical request',list(missing)[:3])
    compared=new.loc[new.event_id.isin(old.event_id)]
    pd.testing.assert_frame_equal(old[fields].sort_values('event_id').reset_index(drop=True),compared[fields].sort_values('event_id').reset_index(drop=True),check_dtype=False,check_exact=False,rtol=1e-10,atol=1e-10)
    added=new.loc[~new.event_id.isin(old.event_id)]
    if len(added):assert pd.to_datetime(added.entry_date).gt('2026-09-04').all()
    repair.write_json(HERE/f'{stage.lower()}_signal_prefix.json',dict(status='PASS',old_count=len(old),new_count=len(new),added=len(added),latest_signal=str(new.signal_date.max()),fields=fields))
    print(stage,'SIGNALS PASS',len(old),len(new),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['ATRDR','MCB','OGR']);main(parser.parse_args().stage)
