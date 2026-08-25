"""Strict buy-side density probe; no annual post-selection cap."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / 'data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet'
D = ROOT / 'data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet'
OUTPUT = ROOT / 'data/audit/chapter8_9_strict_density_v03.csv'

def main():
    c = duckdb.connect()
    c.execute('PRAGMA threads=8')
    c.execute(f"""create or replace temp table b as select d.symbol,d.trade_date,d.close,d.volume,
      f.p10,f.p90,f.average_cost,f.profit_ratio,f.trapped_ratio,f.asr,f.space20,f.base_retention,
      lag(d.close) over w pc,lag(f.p90) over w pp,
      lag(f.p10) over w pp10,lag(f.average_cost) over w pavg,
      lag(f.p90-f.p10,60) over w oldw,
      median(d.volume) over(partition by d.symbol order by d.trade_date rows between 60 preceding and 1 preceding) vm,
      sum(case when d.close>f.p90 then 1 else 0 end) over(partition by d.symbol order by d.trade_date rows between 15 preceding and 1 preceding) br,
      lead(d.close) over w c1,lead(d.trade_date) over w d1
      from read_parquet('{D}',union_by_name=true) d join read_parquet('{F}',union_by_name=true) f using(symbol,trade_date)
      where d.trade_date between date '2020-01-02' and date '2026-08-12' and d.hard_valid and f.chip_input_valid and f.daily_hard_valid
        and not regexp_matches(d.symbol, '^(688|689)')
      window w as(partition by d.symbol order by d.trade_date)""")
    c.execute(f"""copy(with p as(select * from(values
      (40,2.0,5,0.010),(50,2.0,7,0.015),(60,2.0,10,0.020),(50,2.5,10,0.025),(60,2.5,15,0.025),(70,2.5,15,0.025),(60,3.0,15,0.030),(70,3.0,20,0.030),(70,4.0,20,0.040)
      )t(narrow_pct,vol_mult,confirm_days,breakout_buffer)),s as(select p.*,b.*,
      case when oldw is not null and pp is not null and pp10 is not null
        and pp-pp10<=oldw*(1-p.narrow_pct/100) and close>pp*(1+p.breakout_buffer)
        and pc<=pp and volume>=vm*p.vol_mult and br>=p.confirm_days then 'B1'
      when close>pp*(1+p.breakout_buffer) and pc<=pp and volume>=vm*p.vol_mult and br>=p.confirm_days then 'B2'
      when close>pavg and pc<=pavg and volume<vm*0.7 and br>=p.confirm_days then 'B5' end signal
      from b cross join p)
      select narrow_pct,vol_mult,confirm_days,breakout_buffer,symbol,trade_date,extract(year from trade_date) yr,signal,count(*) n,
        avg(c1/close-1) fwd1_mean from s where signal is not null and c1 is not null group by all)
      to '{OUTPUT}' (HEADER, DELIMITER ',')""")
    print(c.execute(f"select narrow_pct,vol_mult,confirm_days,breakout_buffer,sum(n) total_n,sum(n)/4 avg_year from read_csv_auto('{OUTPUT}') where yr between 2020 and 2023 group by all order by avg_year limit 20").fetchdf().to_string(index=False))

if __name__ == '__main__':
    main()
