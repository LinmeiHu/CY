"""Outcome-blind minute prefix and execution-window extraction from exact registered sources."""
import json,time,calendar
from pathlib import Path
import duckdb
import pyarrow.parquet as pq
from .common import HERE,OUT,INV,sha,dump


def main():
    dest=OUT/'minute';dest.mkdir(exist_ok=True);con=duckdb.connect();con.execute('set threads=1');con.execute("set memory_limit='1GB'");con.execute('set temp_directory=?',[str(dest/'spill')])
    reg=json.loads((HERE.parents[1]/'configs/data_asset_registry.json').read_text());assets={x['asset_id']:x for x in reg['assets']}
    manifest=INV/'QD-004-2018-2026-20260820.json';assert sha(manifest)==assets['QD-004']['lineage']['manifest_sha256'];inv=json.loads(manifest.read_text());records=[]
    # V3 construction cutoff and source permission are pre-2024; no later partition is opened.
    for year in range(2020,2024):
        info=next(f for f in inv['files'] if f['path']==f'bars/{year}_day_parquet_none.parquet');src=Path(inv['root'])/info['path'];assert sha(src)==info['sha256']
        print('MINUTE_SOURCE_VERIFIED',year,flush=True)
        # Minute index is clock minutes; lunch is never represented by empty bars.
        sql='''WITH source AS (
          SELECT qmt_code symbol,trade_date,bar_end_time,extract(hour from bar_end_time)*60+extract(minute from bar_end_time) clock,
                 open,high,low,close,volume,amount
          FROM read_parquet(?) WHERE trade_date BETWEEN ?::DATE AND ?::DATE AND CAST(bar_end_time AS TIME)<=TIME '14:34:00'
        ) SELECT symbol,trade_date,
          count(*) FILTER(WHERE clock<=865) n_prefix,
          count(DISTINCT bar_end_time) FILTER(WHERE clock<=865) n_distinct,
          count(*) FILTER(WHERE clock<=865 AND NOT (clock BETWEEN 570 AND 690 OR clock BETWEEN 781 AND 865)) invalid_clock,
          bool_and(open>0 AND low>0 AND low<=high AND close BETWEEN low-0.00001 AND high+0.00001 AND open BETWEEN low-0.00001 AND high+0.00001 AND volume>=0 AND amount>=0) FILTER(WHERE clock<=865) valid_ohlcv,
          arg_min(open,clock) FILTER(WHERE clock<=865) open_prefix,
          max(high) FILTER(WHERE clock<=865) high_prefix,min(low) FILTER(WHERE clock<=865) low_prefix,
          max(close) FILTER(WHERE clock=865) close1425,
          max(close) FILTER(WHERE clock=690) morning_close,max(high) FILTER(WHERE clock<=690) morning_high,
          max(high) FILTER(WHERE clock BETWEEN 836 AND 865) flag_high,min(low) FILTER(WHERE clock BETWEEN 836 AND 865) flag_low,
          max(high) FILTER(WHERE clock BETWEEN 836 AND 850)-min(low) FILTER(WHERE clock BETWEEN 836 AND 850) width_first,
          max(high) FILTER(WHERE clock BETWEEN 851 AND 865)-min(low) FILTER(WHERE clock BETWEEN 851 AND 865) width_last,
          max(high) FILTER(WHERE clock BETWEEN 836 AND 860) prior25_high,
          sum(volume) FILTER(WHERE clock<=865) volume_prefix,sum(amount) FILTER(WHERE clock<=865) amount_prefix,
          list(clock ORDER BY clock) FILTER(WHERE clock BETWEEN 871 AND 874) exec_clocks,
          list(open ORDER BY clock) FILTER(WHERE clock BETWEEN 871 AND 874) exec_opens,
          list(high ORDER BY clock) FILTER(WHERE clock BETWEEN 871 AND 874) exec_highs,
          list(low ORDER BY clock) FILTER(WHERE clock BETWEEN 871 AND 874) exec_lows,
          list(volume ORDER BY clock) FILTER(WHERE clock BETWEEN 871 AND 874) exec_volumes
        FROM source GROUP BY symbol,trade_date'''
        for month in range(1,13):
            output=dest/f'prefix_{year}{month:02d}.parquet'
            if not output.exists():
                tmp=output.with_suffix('.tmp')
                reader=con.execute(sql,[str(src),f'{year}-{month:02d}-01',f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}']).fetch_record_batch(20000)
                with pq.ParquetWriter(tmp,reader.schema,compression='zstd') as writer:
                    for batch in reader:writer.write_batch(batch)
                tmp.replace(output)
            stats=con.execute('select count(*) sessions, sum((n_prefix=206 AND n_distinct=206 AND invalid_clock=0 AND valid_ohlcv AND close1425>0)::INT) valid_prefixes from read_parquet(?)',[str(output)]).fetchone()
            records.append(dict(year=year,month=month,source=str(src),source_sha256=info['sha256'],output=str(output),sha256=sha(output),sessions=stats[0],valid_prefixes=stats[1]))
            dump(HERE/'MINUTE_INPUT_MANIFEST.json',dict(source_manifest=str(manifest),source_manifest_sha256=sha(manifest),files=records,qualification_uses='Only bars ending <=14:25; later bars are execution evidence only',cutoff='2023-12-31'))
            print('MINUTE_PREFIX',year,month,stats,flush=True)
        assert sha(src)==info['sha256']
    dump(HERE/'MINUTE_INPUT_MANIFEST.json',dict(source_manifest=str(manifest),source_manifest_sha256=sha(manifest),files=records,qualification_uses='Only bars ending <=14:25; later bars are execution evidence only',cutoff='2023-12-31'))

if __name__=='__main__':main()
