"""Auditable attribution for all state-machine entry rows.

This deliberately joins diagnostics at signal_date, never after decision_at.
The state-machine CSV may contain one row per parameter; parameter-level
duplicates are retained for parameter diagnostics and de-duplicated for the
best probe setting when reporting case studies.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = ROOT / "data/audit/chapter8_9_state_machine_v01.csv"
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_by_year_2018_2026_v2/year=*/data.parquet"
OUT = ROOT / "data/audit/chapter8_9_attribution_v02"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    con.execute(
        f"""
        CREATE OR REPLACE TABLE entries AS
        SELECT *,
               CASE
                 WHEN substr(symbol, 1, 3) IN ('300', '301') THEN 'ChiNext'
                 ELSE 'MainBoard'
               END AS board
        FROM read_csv_auto('{ENTRIES}', header=true);
        CREATE OR REPLACE TABLE enriched AS
        WITH d0 AS (
          SELECT * FROM read_parquet('{DAILY}', union_by_name=true)
        ), m0 AS (
          SELECT DISTINCT index_symbol, trade_date, market_close
          FROM d0
          WHERE index_symbol IS NOT NULL AND market_close IS NOT NULL
        ), m AS (
          SELECT index_symbol, trade_date,
                 market_close / NULLIF(lag(market_close, 20) OVER
                   (PARTITION BY index_symbol ORDER BY trade_date), 0) - 1.0
                   AS market_ret20
          FROM m0
        ), d AS (
          SELECT d0.*, m.market_ret20
          FROM d0 LEFT JOIN m USING (index_symbol, trade_date)
        ), f AS (
          SELECT * FROM read_parquet('{FEATURES}', union_by_name=true)
        ), x AS (
          SELECT e.*, d.industry, d.market_close, d.market_ret20, d.market_valid,
                 d.buy_blocked_open, d.sell_blocked_open,
                 d.hard_valid AS signal_daily_valid,
                 f.state_quality, f.profit_ratio, f.trapped_ratio,
                 f.average_cost, f.p50, f.space20, f.concentration_20,
                 f.base_retention, f.peak_count, f.realized_volatility,
                 f.strict_sample, f.chip_input_valid
          FROM entries e
          LEFT JOIN d ON d.symbol=e.symbol AND CAST(d.trade_date AS VARCHAR)=e.signal_date
          LEFT JOIN f ON f.symbol=e.symbol
                     AND CAST(f.trade_date AS VARCHAR)=e.signal_date
                     AND f.daily_snapshot_id=d.snapshot_id
        )
        SELECT *,
               CASE
                 WHEN market_ret20 IS NULL THEN 'UNKNOWN'
                 WHEN market_ret20 >= 0.03 THEN 'MARKET_UP'
                 WHEN market_ret20 <= -0.03 THEN 'MARKET_DOWN'
                 ELSE 'MARKET_FLAT'
               END AS market_cycle_proxy,
               CASE
                 WHEN net_return IS NULL THEN 'NO_EXIT'
                 WHEN net_return > 0 THEN 'WIN'
                 ELSE 'LOSS'
               END AS outcome
        FROM x;
        """
    )
    reports = {
        "fixed231_by_signal.csv": """
          SELECT board, signal, COUNT(*) n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched
          WHERE sample_group='PROBE_2020_2023' AND param_id=231
          GROUP BY ALL ORDER BY signal, board
        """,
        "fixed231_by_market_cycle.csv": """
          SELECT market_cycle_proxy, board, signal, COUNT(*) n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched
          WHERE sample_group='PROBE_2020_2023' AND param_id=231
          GROUP BY ALL ORDER BY market_cycle_proxy, board, signal
        """,
        "fixed231_by_industry.csv": """
          SELECT industry, board, signal, COUNT(*) n,
                 COUNT(net_return) exited_n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched
          WHERE sample_group='PROBE_2020_2023' AND param_id=231
            AND industry IS NOT NULL
          GROUP BY ALL HAVING COUNT(*) >= 5
          ORDER BY mean_net_return DESC
        """,
        "fixed231_by_year.csv": """
          SELECT YEAR(CAST(signal_date AS DATE)) signal_year, board, signal,
                 COUNT(*) n, COUNT(net_return) exited_n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched
          WHERE sample_group='PROBE_2020_2023' AND param_id=231
          GROUP BY ALL ORDER BY signal_year, board, signal
        """,
        "fixed231_by_exit.csv": """
          SELECT board, signal, exit_reason, COUNT(*) n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched
          WHERE sample_group='PROBE_2020_2023' AND param_id=231
            AND net_return IS NOT NULL
          GROUP BY ALL ORDER BY signal, board, exit_reason
        """,
        "by_signal.csv": """
          SELECT sample_group, board, signal, COUNT(*) n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate,
                 AVG(state_quality) mean_state_quality,
                 AVG(profit_ratio) mean_profit_ratio,
                 AVG(concentration_20) mean_concentration_20
          FROM enriched WHERE sample_group='PROBE_2020_2023'
          GROUP BY ALL ORDER BY signal, board
        """,
        "by_exit.csv": """
          SELECT sample_group, board, signal, exit_reason, COUNT(*) n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched WHERE sample_group='PROBE_2020_2023'
          GROUP BY ALL ORDER BY signal, board, exit_reason
        """,
        "by_industry.csv": """
          SELECT industry, signal, COUNT(*) n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched
          WHERE sample_group='PROBE_2020_2023' AND industry IS NOT NULL
          GROUP BY ALL HAVING COUNT(*) >= 10
          ORDER BY mean_net_return DESC
        """,
        "by_year.csv": """
          SELECT YEAR(CAST(signal_date AS DATE)) signal_year, board, signal, COUNT(*) n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched WHERE sample_group='PROBE_2020_2023'
          GROUP BY ALL ORDER BY signal_year, board, signal
        """,
        "by_market_cycle.csv": """
          SELECT market_cycle_proxy, board, signal, COUNT(*) n,
                 AVG(net_return) mean_net_return,
                 median(net_return) median_net_return,
                 AVG(CASE WHEN net_return > 0 THEN 1 ELSE 0 END) win_rate
          FROM enriched WHERE sample_group='PROBE_2020_2023'
          GROUP BY ALL ORDER BY market_cycle_proxy, board, signal
        """,
        "cases.csv": """
          SELECT param_id, symbol, signal_date, entry_date, signal, board, industry,
                 exit_date, exit_reason, net_return, state_quality,
                 profit_ratio, trapped_ratio, concentration_20, base_retention,
                 peak_count, market_cycle_proxy
          FROM enriched
          WHERE sample_group='PROBE_2020_2023' AND net_return IS NOT NULL
          QUALIFY row_number() OVER (PARTITION BY symbol, signal ORDER BY net_return DESC) <= 5
             OR row_number() OVER (PARTITION BY symbol, signal ORDER BY net_return) <= 5
          ORDER BY signal, net_return
        """,
        "fixed231_cases.csv": """
          SELECT symbol, signal_date, entry_date, signal, board, industry,
                 exit_date, exit_reason, net_return, state_quality,
                 profit_ratio, trapped_ratio, concentration_20, base_retention,
                 peak_count, market_cycle_proxy
          FROM enriched
          WHERE sample_group='PROBE_2020_2023' AND param_id=231
            AND net_return IS NOT NULL
          ORDER BY net_return
        """,
    }
    # The holdout is reported with the identical frozen queries.  It is never
    # used to select parameters; this makes probe/holdout drift visible.
    for group, suffix in (("PROBE_2020_2023", ""), ("HOLDOUT_2024_2026", "_holdout")):
        for name, query in reports.items():
            query = query.replace("sample_group='PROBE_2020_2023'", f"sample_group='{group}'")
            con.execute(f"COPY ({query}) TO '{OUT / name.replace('.csv', suffix + '.csv')}' (HEADER, DELIMITER ',')")
    print(OUT)


if __name__ == "__main__":
    main()
