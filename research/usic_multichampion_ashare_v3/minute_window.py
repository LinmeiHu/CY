"""Bind the last eligible 14:34-14:35 execution bar, separate from the 14:25 information set."""
import json
from pathlib import Path
import duckdb
from .common import HERE,OUT,INV,sha,dump,parquet

def main():
    invpath=INV/'QD-004-2018-2026-20260820.json';inv=json.loads(invpath.read_text());con=duckdb.connect();con.execute('set threads=1');con.execute("set memory_limit='768MB'");items=[]
    for year in range(2020,2024):
        info=next(f for f in inv['files'] if f['path']==f'bars/{year}_day_parquet_none.parquet');src=Path(inv['root'])/info['path'];assert sha(src)==info['sha256'];dest=OUT/'minute'/f'last_execution_bar_{year}.parquet'
        if not dest.exists():
            d=con.execute("select qmt_code symbol,trade_date,open,high,low,close,volume from read_parquet(?) where CAST(bar_end_time AS TIME)=TIME '14:35:00'",[str(src)]).fetchdf();parquet(dest,d)
        items.append(dict(path=str(dest),sha256=sha(dest),source=str(src),source_sha256=info['sha256']));print('WINDOW',year,flush=True)
    dump(HERE/'MINUTE_EXECUTION_MANIFEST.json',dict(files=items,bar_start='14:34',bar_end='14:35',use='execution only after order frozen 14:25; no admission or preallocation based on future bar'))
if __name__=='__main__':main()
