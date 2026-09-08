"""Extend only missing legal morning quotes for restored stock candidates."""
import duckdb
import pandas as pd
from .audit import ROLL
from .snapshot import CACHE


def main():
    registry=pd.concat([pd.read_parquet(CACHE/s/'precapital_entry_population.parquet')[['symbol']] for s in ['atrdr','mcb']]).drop_duplicates()
    with duckdb.connect() as c:
        c.register('registry',registry)
        c.execute("""CREATE TEMP TABLE extra AS SELECT d.symbol,trade_date+INTERVAL '9 hours 30 minutes' AS timestamp,
          open AS price,current_day_data_tradable AND market_rule_valid AND trade_status=1 AND round(open*100)<round(up_limit_price*100) AS buy,
          current_day_data_tradable AND market_rule_valid AND trade_status=1 AND round(open*100)>round(down_limit_price*100) AS sell
          FROM read_parquet(?) d JOIN registry USING(symbol) WHERE trade_date>='2024-01-01' AND trade_status=1 AND isfinite(open) AND open>0""",[str(CACHE/'daily_with_snapshot.parquet')])
        c.execute(f"""COPY (WITH q AS(SELECT *,0 priority FROM read_parquet('{ROLL}/legal_quotes.parquet') UNION ALL SELECT *,1 priority FROM extra)
          SELECT * EXCLUDE(priority) FROM q QUALIFY row_number() OVER(PARTITION BY timestamp,symbol ORDER BY priority)=1
          ORDER BY timestamp,symbol) TO '{CACHE}/legal_quotes.parquet' (FORMAT PARQUET)""")


if __name__=='__main__':main()
