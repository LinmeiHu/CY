"""Small causal test of alternative cost-reclaim hypotheses."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chip_reclaim_variant_grid_2020_2023.csv"

def main() -> None:
    c = duckdb.connect()
    q = f"""
    COPY (WITH b AS (
      SELECT d.symbol,d.trade_date,d.close,d.open,d.hard_valid,d.buy_blocked_open,
        f.average_cost,f.asr,f.concentration_20,f.space20,
        lag(d.close) OVER w pc,lag(f.average_cost) OVER w pavg,
        lag(f.asr) OVER w pasr,lag(f.concentration_20) OVER w pconc,lag(f.space20) OVER w pspace,
        lead(d.open) OVER w entry_open,lead(d.hard_valid) OVER w ev,
        lead(d.buy_blocked_open) OVER w eb,lead(d.close,6) OVER w c5,
        lead(d.close,11) OVER w c10,lead(d.close,21) OVER w c20
      FROM read_parquet('{DAILY}',union_by_name=true) d
      JOIN read_parquet('{FEATURES}',union_by_name=true) f USING(symbol,trade_date)
      WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '2023-12-29'
        AND d.hard_valid AND f.strict_sample AND f.state_chain_valid
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
    ), p AS (SELECT * FROM (VALUES
      ('ASR_UP_CONC_DOWN',1),('ASR_FLAT_CONC_DOWN',2),
      ('ASR_DOWN_CONC_DOWN',3),('ASR_DOWN_SPACE_UP',4)
    ) v(rule_id,kind)), e AS (
      SELECT p.rule_id,b.* FROM b CROSS JOIN p
      WHERE b.close>b.average_cost AND b.pc<=b.pavg AND b.ev AND NOT b.eb AND b.entry_open>0
        AND ((p.kind=1 AND b.asr>=coalesce(b.pasr,b.asr) AND b.concentration_20<=coalesce(b.pconc,b.concentration_20))
          OR (p.kind=2 AND b.asr>=coalesce(b.pasr,b.asr)*0.98 AND b.concentration_20<=coalesce(b.pconc,b.concentration_20))
          OR (p.kind=3 AND b.asr<=coalesce(b.pasr,b.asr) AND b.concentration_20<=coalesce(b.pconc,b.concentration_20))
          OR (p.kind=4 AND b.asr<=coalesce(b.pasr,b.asr) AND b.space20>=coalesce(b.pspace,b.space20)))
    ) SELECT rule_id,CASE WHEN trade_date<DATE '2023-01-01' THEN 'FIT_2020_2022' ELSE 'HOLDOUT_2023' END sample_group,
      count(*) n,avg(c5/entry_open-1) ret5,median(c5/entry_open-1) med5,
      avg(c10/entry_open-1) ret10,avg(c20/entry_open-1) ret20,median(c20/entry_open-1) med20
      FROM e GROUP BY rule_id,sample_group ORDER BY rule_id,sample_group
    ) TO '{OUT}' (HEADER,DELIMITER ',');
    """
    c.execute(q)
    print(c.execute(f"SELECT * FROM read_csv_auto('{OUT}')").fetchall())

if __name__ == '__main__':
    main()
