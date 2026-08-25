"""Audit causal chip features and daily PIT joins for chapter 8/9 research."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2023-12-31")
    ap.add_argument("--out", default="data/audit/chapter8_9_chip_truth_2020_2023.json")
    args = ap.parse_args()
    feat = "data/processed/chip_state_features_by_year_2018_2026_v2/year=*/data.parquet"
    daily = "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
    con = duckdb.connect()
    where = "trade_date between ? and ?"
    f = con.execute(f"""
      select count(*) n, count(distinct symbol) symbols,
        min(trade_date)::varchar min_date, max(trade_date)::varchar max_date,
        count(*) filter (where chip_input_valid) chip_valid,
        count(*) filter (where daily_hard_valid) daily_valid,
        count(*) filter (where minute_hard_valid) minute_valid,
        count(*) filter (where state_chain_valid) chain_valid,
        count(*) filter (where strict_sample) strict_n,
        count(*) filter (where strict_sample and (available_at is null or available_at > trade_date::timestamp + interval '23 hours 59 minutes 59 seconds')) strict_time_bad,
        count(*) filter (where strict_sample and (daily_snapshot_id is null or minute_snapshot_id is null)) strict_snapshot_bad,
        count(*) filter (where not strict_sample and (daily_snapshot_id is null or minute_snapshot_id is null)) blocked_snapshot_missing,
        count(*) filter (where strict_sample and (mass_sum is null or abs(mass_sum-1.0) > 1e-8)) mass_bad,
        count(*) filter (where strict_sample and (p01 is null or p10 is null or p50 is null or p90 is null or p99 is null
          or not (p01 <= p10 and p10 <= p50 and p50 <= p90 and p90 <= p99))) quantile_bad,
        count(*) filter (where strict_sample and (profit_ratio is null or trapped_ratio is null
          or profit_ratio < -1e-8 or trapped_ratio < -1e-8
          or abs(profit_ratio + trapped_ratio - 1.0) > 1e-6)) ratio_bad,
        count(*) filter (where strict_sample and (concentration_20 is null or concentration_20 < -1e-8 or concentration_20 > 1+1e-8
          or base_retention is null or base_retention < -1e-8 or base_retention > 1+1e-8
          or space20 is null or space20 < -1e-8 or space20 > 1+1e-8)) range_bad
      from read_parquet(?) where {where}
    """, [feat, args.start, args.end]).fetchone()
    d = con.execute(f"""
      select count(*) n, count(distinct symbol) symbols,
        min(trade_date)::varchar min_date, max(trade_date)::varchar max_date,
        count(*) filter (where hard_valid) hard_valid,
        count(*) filter (where hard_valid and (available_at is null or available_at > decision_at)) hard_time_bad,
        count(*) filter (where hard_valid and snapshot_id is null) hard_snapshot_bad,
        count(*) filter (where not bar_valid or not trading_state_valid or not industry_valid
          or not float_valid or not corporate_action_valid or not market_valid or not market_rule_valid) component_bad
      from read_parquet(?) where {where}
    """, [daily, args.start, args.end]).fetchone()
    result = {"period": [args.start, args.end], "feature_asset": feat,
              "daily_asset": daily, "features": dict(zip(["rows","symbols","min_date","max_date","chip_valid","daily_valid","minute_valid","chain_valid","strict_rows","strict_time_bad","strict_snapshot_bad","blocked_snapshot_missing","mass_bad","quantile_bad","ratio_bad","range_bad"], f)),
              "daily": dict(zip(["rows","symbols","min_date","max_date","hard_valid","hard_time_bad","hard_snapshot_bad","component_bad"], d)),
              "conclusion": "PASS" if all(x == 0 for x in [f[9],f[10],f[12],f[13],f[14],f[15],d[5],d[6]]) else "FAIL_REVIEW_REQUIRED"}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
