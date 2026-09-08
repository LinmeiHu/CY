"""Regenerate unchanged stock rules on the restored industry source."""
import importlib.util
import shutil

import pandas as pd

from .audit import HERE, ROOT, ROLL, sha256, write_json
from .snapshot import CACHE


def main():
    path=HERE/'evidence/build_rollforward_inputs.py'
    spec=importlib.util.spec_from_file_location('bound_rollforward_inputs',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT=CACHE
    module.screens(CACHE/'daily_with_snapshot.parquet')
    (CACHE/'mcb').mkdir(exist_ok=True)
    for name in ['v53','v65','signals']:
        shutil.copyfile(CACHE/'mcb_2026-09-04'/f'{name}.parquet',CACHE/'mcb'/f'{name}.parquet')
    module.entries(CACHE/'daily_with_snapshot.parquet','ATRDR')
    module.entries(CACHE/'daily_with_snapshot.parquet','MCB')
    rows=[]
    for strategy in ['atrdr','mcb']:
        new=pd.read_parquet(CACHE/strategy/'precapital_entry_population.parquet')
        old=pd.read_parquet(ROOT/'research/shared_capital_v1/cache'/strategy/'precapital_entry_population.parquet')
        prefix=new.loc[new.signal_date.le('2023-12-31')].copy()
        if set(prefix.event_id)!=set(old.event_id):raise ValueError(strategy+' parent signal prefix changed')
        fields=[c for c in ['event_id','symbol','signal_date','entry_date','entry_price','route','lane','source_rank_order',
                'rank1','rank2','rank3','industry_positive_ret20_share','stock_minus_industry_ret20','turnover_expansion'] if c in old and c in prefix]
        pd.testing.assert_frame_equal(prefix[fields].sort_values('event_id').reset_index(drop=True),
                                      old[fields].sort_values('event_id').reset_index(drop=True),
                                      check_dtype=False,check_exact=False,rtol=1e-10,atol=1e-10)
        legacy=pd.read_parquet(ROLL/strategy/'precapital_entry_population.parquet')
        rows.append(dict(strategy=strategy.upper(),historical_events=len(old),historical_prefix='PASS',
                         authoritative_events=len(new),legacy_events=len(legacy),
                         added_events=len(set(new.event_id)-set(legacy.event_id)),
                         removed_events=len(set(legacy.event_id)-set(new.event_id)),compared_fields='|'.join(fields)))
    pd.DataFrame(rows).to_csv(HERE/'output/stock_signal_prefix_identity.csv',index=False)
    files=sorted((CACHE/'atrdr').glob('*.parquet'))+sorted((CACHE/'mcb').glob('*.parquet'))
    write_json(HERE/'output/restored_signal_manifest.json',[dict(path=str(p),sha256=sha256(p)) for p in files])
    print('SIGNAL_PREFIX_PASS',rows,flush=True)


if __name__=='__main__':main()
