"""Small causal parameter study; 2020-2022 is fit, 2023 is holdout."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chip_rule_grid_2020_2023.csv"


def main() -> None:
    con = duckdb.connect()
    q = f"""
    COPY (
      WITH market_daily AS (
        SELECT trade_date, avg(market_close) AS market_close
        FROM read_parquet('{DAILY}',union_by_name=true)
        WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
        GROUP BY trade_date
      ), market AS (
        SELECT *, avg(market_close) OVER (ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS mavg20
        FROM market_daily
      ), b AS (
        SELECT d.symbol,d.trade_date,d.close,d.open,d.volume,m.market_close,m.mavg20,
          f.p90,f.p50,f.average_cost,f.asr,f.concentration_20,
          lag(d.close) OVER w pc, lag(f.p90) OVER w pp90,
          lag(f.average_cost) OVER w pavg, lag(f.asr) OVER w pasr,
          lag(f.concentration_20) OVER w pconc,
          median(d.volume) OVER (PARTITION BY d.symbol ORDER BY d.trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) vmed20,
          lead(d.open) OVER w entry_open, lead(d.hard_valid) OVER w entry_valid,
          lead(d.buy_blocked_open) OVER w entry_blocked,
          lead(d.close,6) OVER w c5, lead(d.close,11) OVER w c10,
          lead(d.close,21) OVER w c20
        FROM read_parquet('{DAILY}',union_by_name=true) d
        JOIN read_parquet('{FEATURES}',union_by_name=true) f USING(symbol,trade_date)
        JOIN market m USING(trade_date)
        WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
          AND d.hard_valid AND f.strict_sample AND f.state_chain_valid
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
      ), p AS (
        SELECT * FROM (VALUES
          ('MKT_VOL12_ASR0_CONC0',1.2,0.00,0.00),
          ('MKT_VOL15_ASR0_CONC0',1.5,0.00,0.00),
          ('MKT_VOL12_ASR2_CONC0',1.2,0.02,0.00),
          ('MKT_VOL12_ASR0_CONC2',1.2,0.00,0.02),
          ('MKT_VOL15_ASR2_CONC2',1.5,0.02,0.02),
          ('NOMKT_VOL15_ASR2_CONC2',1.5,0.02,0.02)
        ) v(rule_id,vol_mult,asr_delta,conc_delta)
      ), e AS (
        SELECT p.rule_id, b.*,
          CASE WHEN b.close>b.p90 AND b.pc<=b.pp90
             AND b.volume>=b.vmed20*p.vol_mult
             AND b.asr>=coalesce(b.pasr,b.asr)*(1+p.asr_delta)
             AND b.concentration_20<=coalesce(b.pconc,b.concentration_20)*(1-p.conc_delta)
             AND (p.rule_id LIKE 'NOMKT%' OR b.market_close>b.mavg20)
             AND b.entry_valid AND NOT b.entry_blocked AND b.entry_open>0
             THEN 1 ELSE 0 END signal
        FROM b CROSS JOIN p
      )
      SELECT rule_id,
        CASE WHEN trade_date<DATE '2023-01-01' THEN 'FIT_2020_2022' ELSE 'HOLDOUT_2023' END sample_group,
        count(*) FILTER(WHERE signal=1) n,
        avg(c5/entry_open-1) FILTER(WHERE signal=1) ret5,
        median(c5/entry_open-1) FILTER(WHERE signal=1) med5,
        avg(c10/entry_open-1) FILTER(WHERE signal=1) ret10,
        median(c10/entry_open-1) FILTER(WHERE signal=1) med10,
        avg(c20/entry_open-1) FILTER(WHERE signal=1) ret20,
        median(c20/entry_open-1) FILTER(WHERE signal=1) med20
      FROM e GROUP BY rule_id,sample_group ORDER BY rule_id,sample_group
    ) TO '{OUT}' (HEADER,DELIMITER ',');
    """
    con.execute(q)
    print(OUT)
    print(con.execute(f"SELECT * FROM read_csv_auto('{OUT}') ORDER BY rule_id,sample_group").fetchall())


if __name__ == "__main__":
    main()
