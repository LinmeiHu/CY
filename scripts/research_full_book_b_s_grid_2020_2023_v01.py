#!/usr/bin/env python3
"""Full-book B1-B6/S1-S6 research scan for the 2020-2023 probe.

The expensive causal join and all lagged chip/market/sector features are
materialized once and keyed by source/config/code hashes. Parameter batches
then run concurrently against that immutable cache. This is research-only:
2024-2026 is never read by the tuning query and no result is a promotion claim.

The source daily bar is timestamped at the exchange close, while the causal
chip feature can become available after the close (for example after the
minute-derived state is finalized).  ``decision_at`` in the derived base is
therefore the latest required input timestamp; the fill remains the next
tradable open.  Source timestamps are retained separately for auditability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/full_book_research_2020_2023_v01.yaml"
SCRIPT_VERSION = "full-book-b-s-grid-v0.2-semantic"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return value


def sql_path(path: str) -> str:
    return path.replace("'", "''")


def make_grid(config: dict[str, Any]) -> list[dict[str, Any]]:
    rules = config["rules"]
    rows: list[dict[str, Any]] = []
    param_id = 1
    for contraction in rules["contraction_pct"]:
        for pullback in rules["pullback_volume_mult"]:
            for breakout in rules["breakout_volume_mult"]:
                for market_gate in rules["market_gate"]:
                    for sector_gate in rules["sector_gate"]:
                        for confirmation in rules["confirmation_days"]:
                            for cooldown in config["cooldown_days"]:
                                for grace in rules["exit_grace_days"]:
                                    rows.append(
                                        {
                                            "param_id": param_id,
                                            "contraction": float(contraction),
                                            "pullback": float(pullback),
                                            "breakout": float(breakout),
                                            "market_gate": int(bool(market_gate)),
                                            "sector_gate": int(bool(sector_gate)),
                                            "confirmation": int(confirmation),
                                            "cooldown": int(cooldown),
                                            "grace": int(grace),
                                        }
                                    )
                                    param_id += 1
    return rows


def values_sql(params: list[dict[str, Any]]) -> str:
    return ", ".join(
        "({param_id}, {contraction:.8f}, {pullback:.8f}, {breakout:.8f}, "
        "{market_gate}, {sector_gate}, {confirmation}, {cooldown}, {grace})".format(**p)
        for p in params
    )


def materialize_base(
    cache_path: Path,
    feature_glob: str,
    daily_glob: str,
    start: str,
    end: str,
    threads: int,
    semantic_v3: bool = False,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        return
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={max(1, threads)}")
    con.execute("PRAGMA enable_progress_bar=false")
    feature = sql_path(feature_glob)
    daily = sql_path(daily_glob)
    if semantic_v3:
        p10_expr = "f.i90_lower"
        p90_expr = "f.i90_upper"
        retention_expr = "f.i90_base_retention"
        peak1_center_expr = "f.main_peak_center"
        peak1_mass_expr = "f.main_peak_mass"
        peak1_lower_expr = "f.main_peak_lower"
        peak1_upper_expr = "f.main_peak_upper"
        peak1_prominence_expr = "f.main_peak_prominence"
        peak2_center_expr = "f.upper_peak_center"
        peak2_mass_expr = "f.upper_peak_mass"
        peak2_lower_expr = "f.upper_peak_lower"
        peak2_upper_expr = "f.upper_peak_upper"
        peak2_prominence_expr = "f.upper_peak_prominence"
        i70_lower_expr = "f.i70_lower"
        i70_upper_expr = "f.i70_upper"
        migration_expr = "f.migration_mass"
        avg_delta_expr = "f.average_cost_delta"
    else:
        p10_expr = "f.p10"
        p90_expr = "f.p90"
        retention_expr = "f.base_retention"
        peak1_center_expr = "try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE)"
        peak1_mass_expr = "NULL::DOUBLE"
        peak1_lower_expr = "NULL::DOUBLE"
        peak1_upper_expr = "NULL::DOUBLE"
        peak1_prominence_expr = "try_cast(json_extract_string(f.peaks_json, '$[0].prominence') AS DOUBLE)"
        peak2_center_expr = "try_cast(json_extract_string(f.peaks_json, '$[1].center_price') AS DOUBLE)"
        peak2_mass_expr = "NULL::DOUBLE"
        peak2_lower_expr = "NULL::DOUBLE"
        peak2_upper_expr = "NULL::DOUBLE"
        peak2_prominence_expr = "try_cast(json_extract_string(f.peaks_json, '$[1].prominence') AS DOUBLE)"
        i70_lower_expr = "NULL::DOUBLE"
        i70_upper_expr = "NULL::DOUBLE"
        migration_expr = "NULL::DOUBLE"
        avg_delta_expr = "NULL::DOUBLE"
    query = f"""
    COPY (
      WITH raw AS (
        SELECT d.symbol, d.trade_date,
               d.decision_at AS bar_decision_at,
               greatest(d.decision_at, f.available_at) AS decision_at,
               d.available_at AS daily_available_at,
               f.available_at AS feature_available_at,
               d.snapshot_id, d.open, d.high, d.low, d.close, d.volume,
               d.hard_valid, d.buy_blocked_open, d.sell_blocked_open,
               d.industry, d.industry_valid, d.market_close, d.market_valid,
               f.strict_sample, f.chip_input_valid, f.daily_hard_valid,
               f.minute_hard_valid, f.state_chain_valid,
               f.daily_snapshot_id, f.minute_snapshot_id, f.state_version,
               {p10_expr} AS p10, f.p50, {p90_expr} AS p90, f.average_cost, f.space20,
               f.concentration_20, {retention_expr} AS base_retention, f.peak_count,
               {peak1_center_expr} AS peak1_center,
               {peak1_mass_expr} AS peak1_mass,
               {peak1_lower_expr} AS peak1_lower,
               {peak1_upper_expr} AS peak1_upper,
               {peak1_prominence_expr} AS peak1_prominence,
               {peak2_center_expr} AS peak2_center,
               {peak2_mass_expr} AS peak2_mass,
               {peak2_lower_expr} AS peak2_lower,
               {peak2_upper_expr} AS peak2_upper,
               {peak2_prominence_expr} AS peak2_prominence,
               {i70_lower_expr} AS i70_lower, {i70_upper_expr} AS i70_upper,
               {migration_expr} AS migration_mass, {avg_delta_expr} AS average_cost_delta,
               lag(d.close) OVER w AS prev_close,
               lag(d.close, 2) OVER w AS prev2_close,
               lag(d.close, 5) OVER w AS close5,
               lag({p10_expr}) OVER w AS prev_p10,
               lag(f.p50) OVER w AS prev_p50,
               lag(f.p50, 2) OVER w AS prev2_p50,
               lag({p90_expr}) OVER w AS prev_p90,
               lag({p90_expr}, 2) OVER w AS prev2_p90,
               lag(f.average_cost) OVER w AS prev_avg,
               lag(f.concentration_20) OVER w AS prev_conc,
               lag({retention_expr}) OVER w AS prev_ret,
               lag(f.space20) OVER w AS prev_space,
               lag({peak1_center_expr}) OVER w AS prev_peak1_center,
               lag({peak1_mass_expr}) OVER w AS prev_peak1_mass,
               lag({peak1_lower_expr}) OVER w AS prev_peak1_lower,
               lag({peak1_upper_expr}) OVER w AS prev_peak1_upper,
               lag({peak1_prominence_expr}) OVER w AS prev_peak1_prominence,
               lag({peak1_prominence_expr}, 2) OVER w AS prev2_peak1_prominence,
               lag({i70_lower_expr}) OVER w AS prev_i70_lower,
               lag({i70_upper_expr}) OVER w AS prev_i70_upper,
               lag({migration_expr}) OVER w AS prev_migration_mass,
               lag({avg_delta_expr}) OVER w AS prev_average_cost_delta,
               lag({p90_expr}-{p10_expr}, 60) OVER w AS old_width,
               avg(d.close) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS avgclose20,
               avg(d.market_close) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS market_avg20,
               median(d.volume) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS vmed20,
               min(d.low) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS low20,
               max(d.high) OVER (PARTITION BY d.symbol ORDER BY d.trade_date
                 ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) AS high60,
               sum(CASE WHEN d.close > {p90_expr} THEN 1 ELSE 0 END) OVER
                 (PARTITION BY d.symbol ORDER BY d.trade_date
                  ROWS BETWEEN 15 PRECEDING AND 1 PRECEDING) AS prior_break_count,
               lead(d.trade_date) OVER w AS entry_date,
               lead(d.open) OVER w AS entry_open,
               lead(d.hard_valid) OVER w AS entry_hard_valid,
               lead(d.buy_blocked_open) OVER w AS entry_buy_blocked
        FROM read_parquet('{daily}', union_by_name=true) d
        JOIN read_parquet('{feature}', union_by_name=true) f USING (symbol, trade_date)
        WHERE d.trade_date BETWEEN DATE '{start}' AND DATE '{end}'
          AND d.hard_valid AND f.strict_sample AND f.chip_input_valid
          AND f.daily_hard_valid AND (f.minute_hard_valid OR f.minute_requirement_waived)
          AND f.state_chain_valid
          AND f.daily_snapshot_id = d.snapshot_id
          AND d.available_at <= greatest(d.decision_at, f.available_at)
          AND f.available_at <= greatest(d.decision_at, f.available_at)
          AND NOT regexp_matches(d.symbol, '^(688|689)')
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
      ), loo AS (
        SELECT r.*,
               CASE WHEN industry_n > 1 THEN (industry_ret_sum - stock_ret)/(industry_n-1)
               END AS industry_loo_ret,
               CASE WHEN industry_n > 1 THEN TRUE ELSE FALSE END AS industry_loo_valid
        FROM (
          SELECT raw.*,
                 CASE WHEN prev_close > 0 THEN close/prev_close-1 END AS stock_ret,
                 sum(CASE WHEN prev_close > 0 THEN close/prev_close-1 END)
                   OVER (PARTITION BY trade_date, industry) AS industry_ret_sum,
                 count(CASE WHEN prev_close > 0 THEN 1 END)
                   OVER (PARTITION BY trade_date, industry) AS industry_n
          FROM raw
        ) r
      )
      SELECT *, CASE WHEN regexp_matches(symbol, '^(300|301)') THEN '创业板' ELSE '主板' END AS board
      FROM loo
    ) TO '{sql_path(str(cache_path))}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    try:
        con.execute(query)
    finally:
        con.close()


def batch_query(
    cache_path: Path,
    params: list[dict[str, Any]],
    out_path: Path,
    max_hold: int,
    signal_start: str,
    signal_end: str,
    commission: float,
    stamp: float,
    slippage: float,
    impact: float,
    threads: int,
    sample_group_expr: str,
) -> None:
    if not params:
        return
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={max(1, threads)}")
    con.execute("PRAGMA enable_progress_bar=false")
    psql = values_sql(params)
    cache = sql_path(str(cache_path))
    cost_entry = 1.0 + (commission + slippage + impact) / 10000.0
    cost_exit = 1.0 - (commission + stamp + slippage + impact) / 10000.0
    query = f"""
    COPY (
      WITH params AS (
        SELECT * FROM (VALUES {psql}) AS p(
          param_id, contraction, pullback, breakout, market_gate,
          sector_gate, confirmation, cooldown, grace)
      ),
      b AS (SELECT * FROM read_parquet('{cache}')),
      raw_entries AS (
        SELECT b.symbol, b.board, b.industry, b.trade_date AS signal_date,
               b.entry_date, b.entry_open, 'B1' AS signal,
               b.vmed20, b.prev_p10, b.prev_p50, b.prev2_p50,
               b.prev_p90, b.prev2_p90, b.prev_avg, b.prev_conc, b.prev_ret,
               b.prev_space, b.prev_peak1_center, b.prev_peak1_prominence,
               b.prev_peak1_mass, b.prev_peak1_lower, b.prev_peak1_upper,
               b.prev_i70_lower, b.prev_i70_upper, b.prev_migration_mass,
               b.prev_average_cost_delta, b.prev2_peak1_prominence, p.*
        FROM b CROSS JOIN params p
        WHERE b.old_width IS NOT NULL AND b.peak_count = 1
          AND b.p90-b.p10 <= b.old_width*(1-p.contraction)
          AND b.close > b.p90 AND b.prev_close <= b.prev_p90
          AND b.p50 >= coalesce(b.prev_p50, b.p50)
          AND b.migration_mass IS NOT NULL
          AND b.volume >= p.breakout*b.vmed20 AND b.close >= b.low20
          AND b.entry_hard_valid AND NOT b.entry_buy_blocked
          AND (p.market_gate=0 OR b.market_close > b.market_avg20)
          AND (p.sector_gate=0 OR b.industry_loo_valid AND b.industry_loo_ret > 0)
        UNION ALL
        SELECT b.symbol, b.board, b.industry, b.trade_date, b.entry_date,
               b.entry_open, 'B3', b.vmed20, b.prev_p10, b.prev_p50, b.prev2_p50,
               b.prev_p90, b.prev2_p90, b.prev_avg, b.prev_conc, b.prev_ret,
               b.prev_space, b.prev_peak1_center, b.prev_peak1_prominence,
               b.prev_peak1_mass, b.prev_peak1_lower, b.prev_peak1_upper,
               b.prev_i70_lower, b.prev_i70_upper, b.prev_migration_mass,
               b.prev_average_cost_delta, b.prev2_peak1_prominence, p.*
        FROM b CROSS JOIN params p
        WHERE b.peak_count >= 2 AND b.peak2_center > b.p50
          AND b.peak2_mass IS NOT NULL AND b.peak2_mass > 0
          AND b.close > b.p50 AND b.prev_close <= b.prev_p50
          AND b.p50 > b.prev_p50 AND b.prior_break_count BETWEEN 1 AND 8
          AND b.base_retention >= b.prev_ret AND b.entry_hard_valid
          AND NOT b.entry_buy_blocked
          AND (p.market_gate=0 OR b.market_close > b.market_avg20)
          AND (p.sector_gate=0 OR b.industry_loo_valid AND b.industry_loo_ret > 0)
        UNION ALL
        SELECT b.symbol, b.board, b.industry, b.trade_date, b.entry_date,
               b.entry_open, 'B4', b.vmed20, b.prev_p10, b.prev_p50, b.prev2_p50,
               b.prev_p90, b.prev2_p90, b.prev_avg, b.prev_conc, b.prev_ret,
               b.prev_space, b.prev_peak1_center, b.prev_peak1_prominence,
               b.prev_peak1_mass, b.prev_peak1_lower, b.prev_peak1_upper,
               b.prev_i70_lower, b.prev_i70_upper, b.prev_migration_mass,
               b.prev_average_cost_delta, b.prev2_peak1_prominence, p.*
        FROM b CROSS JOIN params p
        WHERE b.close > b.avgclose20 AND b.prev_close <= b.avgclose20
          AND b.close > b.p50 AND b.close5 IS NOT NULL AND b.close/b.close5 > 1.02
          AND b.volume <= b.vmed20*p.pullback AND b.base_retention >= b.prev_ret
          AND b.peak1_center >= coalesce(b.prev_peak1_center, b.peak1_center)
          AND b.migration_mass IS NOT NULL
          AND b.concentration_20 >= b.prev_conc AND b.entry_hard_valid
          AND NOT b.entry_buy_blocked
          AND (p.market_gate=0 OR b.market_close > b.market_avg20)
          AND (p.sector_gate=0 OR b.industry_loo_valid AND b.industry_loo_ret > 0)
        UNION ALL
        SELECT b.symbol, b.board, b.industry, b.trade_date, b.entry_date,
               b.entry_open, 'B5', b.vmed20, b.prev_p10, b.prev_p50, b.prev2_p50,
               b.prev_p90, b.prev2_p90, b.prev_avg, b.prev_conc, b.prev_ret,
               b.prev_space, b.prev_peak1_center, b.prev_peak1_prominence,
               b.prev_peak1_mass, b.prev_peak1_lower, b.prev_peak1_upper,
               b.prev_i70_lower, b.prev_i70_upper, b.prev_migration_mass,
               b.prev_average_cost_delta, b.prev2_peak1_prominence, p.*
        FROM b CROSS JOIN params p
        WHERE b.prev_p50 IS NOT NULL AND b.close > b.p50
          AND b.prev_close <= b.prev_p50 AND b.volume <= b.vmed20*p.pullback
          AND b.base_retention >= b.prev_ret AND b.concentration_20 >= b.prev_conc
          AND b.prev_i70_lower IS NOT NULL AND b.prev_i70_upper IS NOT NULL
          AND (b.low20 BETWEEN b.prev_i70_lower AND b.prev_i70_upper
               OR b.prev_close BETWEEN b.prev_i70_lower AND b.prev_i70_upper)
          AND b.close >= coalesce(b.prev_peak1_lower, b.prev_p50)
          AND b.close >= b.low20 AND b.entry_hard_valid AND NOT b.entry_buy_blocked
          AND (p.market_gate=0 OR b.market_close > b.market_avg20)
          AND (p.sector_gate=0 OR b.industry_loo_valid AND b.industry_loo_ret > 0)
        UNION ALL
        SELECT b.symbol, b.board, b.industry, b.trade_date, b.entry_date,
               b.entry_open, 'B6', b.vmed20, b.prev_p10, b.prev_p50, b.prev2_p50,
               b.prev_p90, b.prev2_p90, b.prev_avg, b.prev_conc, b.prev_ret,
               b.prev_space, b.prev_peak1_center, b.prev_peak1_prominence,
               b.prev_peak1_mass, b.prev_peak1_lower, b.prev_peak1_upper,
               b.prev_i70_lower, b.prev_i70_upper, b.prev_migration_mass,
               b.prev_average_cost_delta, b.prev2_peak1_prominence, p.*
        FROM b CROSS JOIN params p
        WHERE b.close > b.p90 AND b.prev_close <= b.prev_p50
          AND b.close5 IS NOT NULL AND b.close5 > b.close
          AND b.high60 IS NOT NULL AND b.close < b.high60*0.85
          AND b.prev_p10 IS NOT NULL AND b.low >= b.prev_p10*0.98
          AND b.prev_peak1_center IS NOT NULL
          AND b.volume >= b.vmed20*p.breakout AND b.prior_break_count BETWEEN 1 AND 8
          AND b.base_retention >= b.prev_ret AND b.entry_hard_valid
          AND NOT b.entry_buy_blocked
          AND (p.market_gate=0 OR b.market_close > b.market_avg20)
          AND (p.sector_gate=0 OR b.industry_loo_valid AND b.industry_loo_ret > 0)
        UNION ALL
        SELECT rec.symbol, rec.board, rec.industry, br.trade_date AS signal_date,
               rec.entry_date, rec.entry_open, 'B2',
               rec.vmed20, rec.prev_p10, rec.prev_p50, rec.prev2_p50,
               rec.prev_p90, rec.prev2_p90, rec.prev_avg, rec.prev_conc, rec.prev_ret,
               rec.prev_space, rec.prev_peak1_center, rec.prev_peak1_prominence,
               rec.prev_peak1_mass, rec.prev_peak1_lower, rec.prev_peak1_upper,
               rec.prev_i70_lower, rec.prev_i70_upper, rec.prev_migration_mass,
               rec.prev_average_cost_delta, rec.prev2_peak1_prominence, p.*
        FROM b br CROSS JOIN params p
        JOIN b pb ON pb.symbol=br.symbol AND pb.trade_date>br.trade_date
          AND pb.trade_date<=br.trade_date + INTERVAL 10 DAY
          AND pb.volume <= pb.vmed20*p.pullback
          AND pb.low <= coalesce(br.peak1_upper, br.p90)
          AND pb.low >= coalesce(br.peak1_lower, br.p10)*0.98
          AND pb.close >= pb.p50
        JOIN b rec ON rec.symbol=br.symbol AND rec.trade_date>pb.trade_date
          AND rec.trade_date<=pb.trade_date + INTERVAL 3 DAY
          AND rec.close > rec.prev_p90
          AND rec.close > coalesce(rec.prev_peak1_lower, rec.prev_p90)
          AND rec.low >= coalesce(br.peak1_lower, br.p10)*0.98
          AND rec.close >= rec.prev_close AND rec.entry_hard_valid
          AND NOT rec.entry_buy_blocked
          AND (p.market_gate=0 OR rec.market_close > rec.market_avg20)
          AND (p.sector_gate=0 OR rec.industry_loo_valid AND rec.industry_loo_ret > 0)
        WHERE br.prev_close <= br.prev_p90 AND br.close > br.p90
          AND br.volume >= p.breakout*br.vmed20
          AND br.prior_break_count >= p.confirmation
          AND br.old_width IS NOT NULL
          AND br.p90-br.p10 <= br.old_width*(1-p.contraction)
        QUALIFY row_number() OVER (
          PARTITION BY br.symbol, br.trade_date, p.param_id ORDER BY rec.trade_date
        ) = 1
      ),
      dedup AS (
        SELECT * EXCLUDE(prev_signal, rn)
        FROM (
          SELECT raw_entries.*, lag(signal_date) OVER
            (PARTITION BY symbol, param_id, signal ORDER BY signal_date) AS prev_signal,
            row_number() OVER
            (PARTITION BY symbol, param_id, signal, signal_date ORDER BY signal) AS rn
          FROM raw_entries
          WHERE signal_date BETWEEN DATE '{signal_start}' AND DATE '{signal_end}'
        ) q
        WHERE rn=1 AND (prev_signal IS NULL OR signal_date > prev_signal + cooldown*INTERVAL 1 DAY)
      ),
      future0 AS (
        SELECT e.*, x.trade_date AS future_date, x.open AS future_open,
               x.close AS future_close, x.low AS future_low, x.volume AS future_volume,
               x.prev_close AS future_prev_close, x.prev_p10, x.prev_p50, x.prev_p90,
               x.prev2_p90, x.prev2_p50, x.prev_avg, x.prev_conc, x.prev_ret,
               x.prev_space, x.peak1_center AS future_peak1_center,
               x.peak1_lower AS future_peak1_lower,
               x.peak1_upper AS future_peak1_upper,
               x.peak1_mass AS future_peak1_mass,
               x.peak2_center AS future_peak2_center,
               x.peak2_mass AS future_peak2_mass,
               x.prev_peak1_center AS future_prev_peak1_center,
               x.prev_peak1_lower AS future_prev_peak1_lower,
               x.prev_peak1_upper AS future_prev_peak1_upper,
               x.prev_peak1_mass AS future_prev_peak1_mass,
               x.prev_peak1_prominence AS future_peak1_prominence,
               x.prev2_peak1_prominence AS future_prev2_peak1_prominence,
               x.p10 AS future_p10, x.p50 AS future_p50, x.p90 AS future_p90,
               x.i70_lower AS future_i70_lower, x.i70_upper AS future_i70_upper,
               x.average_cost AS future_avg, x.space20 AS future_space,
               x.concentration_20 AS future_conc, x.base_retention AS future_ret,
               x.migration_mass AS future_migration_mass,
               x.average_cost_delta AS future_average_cost_delta,
               x.peak_count AS future_peak_count, x.market_close AS future_market,
               row_number() OVER (PARTITION BY e.symbol, e.param_id, e.signal, e.signal_date
                                  ORDER BY x.trade_date) AS bar_no
        FROM dedup e JOIN b x ON x.symbol=e.symbol AND x.trade_date>e.entry_date
          AND x.trade_date<=e.entry_date + INTERVAL {max_hold + 30} DAY
          AND x.hard_valid
      ),
      flags AS (
        SELECT *,
          (future_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_close < coalesce(future_peak1_lower, future_p50)
           AND future_prev_close < prev_p90 AND future_prev_close < prev2_p90
           AND future_close < future_prev_close AND future_volume > vmed20) AS s1,
          (future_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_conc > prev_conc AND future_close <= future_prev_close
           AND future_peak1_mass > coalesce(prev_peak1_mass, 0)
           AND future_average_cost_delta > 0
           AND future_peak1_prominence < coalesce(prev_peak1_prominence, future_peak1_prominence)
           AND future_volume > vmed20) AS s2,
          (future_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_ret < prev_ret AND future_close < future_p50
           AND future_prev_close < prev2_p50
           AND future_peak1_center < prev_peak1_center
           AND future_close < coalesce(future_i70_lower, future_p50)) AS s3,
          (future_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_peak_count >= 2 AND future_close < future_p50
           AND future_peak2_mass > 0 AND future_prev_close >= prev_p50) AS s4,
          (future_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_close < coalesce(future_peak1_lower, future_p10)
           AND future_prev_close >= coalesce(future_prev_peak1_lower, prev_p10)
           AND future_volume > vmed20 AND future_close < future_open) AS s5,
          (future_date >= entry_date + grace*INTERVAL 1 DAY
           AND future_space < prev_space AND future_migration_mass > coalesce(prev_migration_mass, 0)
           AND future_close < prev_avg
           AND future_close < coalesce(future_peak1_center, future_avg)) AS s6,
          (future_close <= entry_open*0.92) AS stop_hit,
          (bar_no >= {max_hold}) AS time_hit
        FROM future0
      ),
      ranked AS (
        SELECT *, CASE WHEN stop_hit THEN 'STOP'
          WHEN s5 THEN 'S5' WHEN s1 THEN 'S1' WHEN s2 THEN 'S2'
          WHEN s3 THEN 'S3' WHEN s4 THEN 'S4' WHEN s6 THEN 'S6'
          WHEN time_hit THEN 'TIME' END AS exit_reason,
          row_number() OVER (PARTITION BY symbol, param_id, signal, signal_date
            ORDER BY future_date,
              CASE WHEN stop_hit THEN 0 WHEN s5 THEN 1 WHEN s1 THEN 2 WHEN s2 THEN 3
                   WHEN s3 THEN 4 WHEN s4 THEN 5 WHEN s6 THEN 6 WHEN time_hit THEN 7 ELSE 8 END) AS exit_rank
        FROM flags
        WHERE stop_hit OR s1 OR s2 OR s3 OR s4 OR s5 OR s6 OR time_hit
      ),
      chosen AS (
        SELECT * FROM ranked WHERE exit_rank=1
      ),
      fwd AS (
        SELECT symbol, param_id, signal, signal_date,
          max(future_close) FILTER (WHERE bar_no=5) AS close5,
          max(future_close) FILTER (WHERE bar_no=10) AS close10,
          max(future_close) FILTER (WHERE bar_no=20) AS close20,
          max(future_close) FILTER (WHERE bar_no={max_hold}) AS close60
        FROM future0 GROUP BY ALL
      )
      SELECT c.param_id, c.symbol, c.board, c.industry, c.signal, c.signal_date,
             c.entry_date, c.entry_open, c.future_date AS exit_date,
             c.future_close AS exit_close, c.exit_reason,
             c.s1, c.s2, c.s3, c.s4, c.s5, c.s6, c.stop_hit,
             f.close5/c.entry_open*{cost_entry:.12f}*{cost_exit:.12f}-1 AS net_r5,
             f.close10/c.entry_open*{cost_entry:.12f}*{cost_exit:.12f}-1 AS net_r10,
             f.close20/c.entry_open*{cost_entry:.12f}*{cost_exit:.12f}-1 AS net_r20,
             f.close60/c.entry_open*{cost_entry:.12f}*{cost_exit:.12f}-1 AS net_r60,
             c.future_close/c.entry_open*{cost_entry:.12f}*{cost_exit:.12f}-1 AS selected_net_return,
             {sample_group_expr} AS sample_group
      FROM chosen c LEFT JOIN fwd f USING (symbol, param_id, signal, signal_date)
    ) TO '{sql_path(str(out_path))}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    try:
        con.execute(query)
    finally:
        con.close()


def write_ledger(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--output", type=Path, default=ROOT / "data/audit/full_book_b_s_grid_2020_2023_v01")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--threads-per-worker", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=24)
    ap.add_argument("--max-parameters", type=int, default=None,
                    help="development smoke limit; omit for the complete grid")
    ap.add_argument("--semantic-v3", action="store_true",
                    help="use the book-semantic I90/I70, migration and peak fields")
    ap.add_argument("--base-end", default=None,
                    help="last source date read for the causal outcome tail")
    ap.add_argument("--signal-start", default=None,
                    help="override signal start; does not change the warmup range")
    ap.add_argument("--signal-end", default=None,
                    help="override signal end; use only for a locked evaluation")
    ap.add_argument("--parameter-ids", default=None,
                    help="comma-separated frozen parameter IDs; omit for the full grid")
    ap.add_argument("--sample-label", default=None,
                    help="label all events with a locked sample name")
    ap.add_argument("--sample-years", type=float, default=None,
                    help="years represented by --sample-label for signals_per_year")
    ap.add_argument("--base-cache", type=Path, default=None,
                    help="reuse an existing immutable causal base parquet")
    args = ap.parse_args()
    config = load_yaml(args.config)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    workers = int(args.workers or config["workers"])
    threads = int(args.threads_per_worker or config["duckdb_threads_per_worker"])
    feature_manifest = ROOT / "data/processed/chip_state_features_2018_2026_v2/manifest.json"
    if args.semantic_v3:
        feature_glob = str(ROOT / "data/processed/chip_state_features_semantic_v3_2018_2026/bucket=*/data.parquet")
        feature_manifest = ROOT / "data/processed/chip_state_features_semantic_v3_2018_2026/manifest.json"
    else:
        feature_glob = str(ROOT / config["feature_asset"])
    daily_glob = str(ROOT / config["daily_asset"])
    start = str(config["warmup_start"])
    # 2024 is read only as the natural exit-outcome tail for late-2023 signals.
    end = str(args.base_end or "2024-04-30")
    signal_start = str(args.signal_start or config["discovery_start"])
    signal_end = str(args.signal_end or config["timeout_end"])
    grid = make_grid(config)
    if args.max_parameters is not None:
        grid = grid[:max(0, args.max_parameters)]
    if args.parameter_ids:
        wanted = {int(item.strip()) for item in args.parameter_ids.split(",") if item.strip()}
        grid = [row for row in grid if int(row["param_id"]) in wanted]
    if not grid:
        raise ValueError("parameter grid is empty after applying parameter filters")
    if args.sample_label:
        sample_label = args.sample_label.replace("'", "''")
        sample_group_expr = f"'{sample_label}'"
        sample_group_filter = f"'{sample_label}'"
        sample_years = float(args.sample_years or 1.0)
        rate_expr = f"count(*) / {sample_years:.12f}"
    else:
        sample_group_expr = (
            "CASE WHEN c.signal_date <= DATE '2022-12-30' THEN 'DISCOVERY_2020_2022' "
            "ELSE 'TIMEOUT_2023' END"
        )
        sample_group_filter = "'DISCOVERY_2020_2022'"
        rate_expr = (
            "count(*) / max(CASE WHEN sample_group='DISCOVERY_2020_2022' THEN 3.0 "
            "WHEN sample_group='TIMEOUT_2023' THEN 1.0 ELSE NULL END)"
        )
    source_hash = hashlib.sha256(
        (sha256_file(feature_manifest)
         + sha256_file(ROOT / "data/processed/pit_b_daily_2018_2026_v2/audit.json")
         + sha256_file(args.config)
         + sha256_file(Path(__file__))
         + str(args.semantic_v3).encode().hex()
        ).encode()
    ).hexdigest()
    cache = (args.base_cache or (output / f"base_{source_hash[:16]}.parquet")).resolve()
    cache_reused = cache.exists()
    if cache_reused and cache.stat().st_size == 0:
        raise RuntimeError(f"base cache exists but is empty: {cache}")
    manifest_path = output / "run_manifest.json"
    manifest = {
        "research_id": config["research_id"],
        "script_version": SCRIPT_VERSION,
        "semantic_v3": bool(args.semantic_v3),
        "generated_at": datetime.now(UTC).isoformat(),
        "config": str(args.config.resolve()),
        "config_sha256": sha256_file(args.config),
        "base_cache": str(cache.resolve()),
        "base_cache_key": source_hash,
        "base_cache_reused": cache_reused,
        "sample_label": args.sample_label,
        "sample_years": args.sample_years,
        "frozen_parameter_ids": [int(row["param_id"]) for row in grid]
        if args.parameter_ids else None,
        "base_input_range": [start, end],
        "signal_tuning_range": [signal_start, signal_end],
        "discovery_range": [str(config["discovery_start"]), str(config["discovery_end"])],
        "timeout_range": [str(config["timeout_start"]), str(config["timeout_end"])],
        "retrospective_range_not_read": [str(config["retrospective_only_start"]), str(config["retrospective_only_end"])],
        "holdout_accessed": bool(args.sample_label and "HOLDOUT" in args.sample_label.upper()),
        "holdout_tuning_allowed": False,
        "parameter_count": len(grid),
        "parallel": {"workers": workers, "threads_per_worker": threads, "batch_size": args.batch_size},
        "dedup": "causal lag/join base materialized once; repeated parameter scans read hash-keyed parquet",
        "signal_timing": {
            "decision_at": "max(source daily decision_at, causal chip feature available_at)",
            "fill": "next tradable open; never inside signal bar",
            "source_timestamps_retained": ["bar_decision_at", "daily_available_at", "feature_available_at"],
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "materialize_base", "cache": str(cache), "parameters": len(grid)}))
    if not cache_reused:
        materialize_base(cache, feature_glob, daily_glob, start, end, max(1, workers * threads), args.semantic_v3)
    check_con = duckdb.connect()
    try:
        base_rows = int(check_con.execute(
            f"SELECT count(*) FROM read_parquet('{sql_path(str(cache))}')"
        ).fetchone()[0])
    finally:
        check_con.close()
    manifest["base_rows"] = base_rows
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if base_rows == 0:
        raise RuntimeError(
            "causal base materialized zero rows; refusing to run a false-success parameter scan"
        )

    batches = [grid[i:i + args.batch_size] for i in range(0, len(grid), args.batch_size)]
    batch_paths = [output / f"batch_{i:04d}.parquet" for i in range(len(batches))]
    costs = config["costs"]
    jobs: list[tuple[int, list[dict[str, Any]], Path]] = []
    for i, (batch, path) in enumerate(zip(batches, batch_paths, strict=True)):
        if not path.exists() or path.stat().st_size == 0:
            jobs.append((i, batch, path))
    print(json.dumps({"phase": "parallel_parameter_scan", "batches": len(batches), "pending": len(jobs)}))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(
                batch_query, cache, batch, path, int(config["max_hold_days"]),
                signal_start, signal_end,
                float(costs["commission_bps_each_side"]), float(costs["stamp_duty_bps_sell"]),
                float(costs["slippage_bps_each_side"]), float(costs["impact_bps_each_side"]), threads,
                sample_group_expr,
            ): i for i, batch, path in jobs
        }
        for future in as_completed(futures):
            idx = futures[future]
            future.result()
            print(json.dumps({"completed_batch": idx + 1, "total_batches": len(batches)}))

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={max(1, workers * threads)}")
    glob = sql_path(str(output / "batch_*.parquet"))
    con.execute(f"CREATE OR REPLACE TEMP VIEW events AS SELECT * FROM read_parquet('{glob}')")
    con.execute(f"COPY (SELECT * FROM events ORDER BY param_id, signal_date, symbol, signal) TO '{sql_path(str(output / 'events.parquet'))}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"""COPY (SELECT param_id, sample_group, board, signal, count(*) AS n, count(DISTINCT symbol) AS symbols,
        avg(selected_net_return) AS mean_selected_return, median(selected_net_return) AS median_selected_return,
        avg(CASE WHEN selected_net_return>0 THEN 1.0 ELSE 0.0 END) AS win_rate,
        avg(net_r20) AS mean_r20, median(net_r20) AS median_r20,
        {rate_expr} AS signals_per_year
      FROM events GROUP BY ALL ORDER BY param_id, sample_group, board, signal) TO '{sql_path(str(output / 'summary.csv'))}' (HEADER, DELIMITER ',')""")
    con.execute(f"""COPY (SELECT param_id, sample_group, board, extract(year FROM signal_date) AS year, signal,
        count(*) AS n, avg(selected_net_return) AS mean_selected_return,
        median(selected_net_return) AS median_selected_return,
        avg(CASE WHEN selected_net_return>0 THEN 1.0 ELSE 0.0 END) AS win_rate,
        avg(net_r5) AS mean_r5, avg(net_r10) AS mean_r10, avg(net_r20) AS mean_r20,
        avg(net_r60) AS mean_r60
      FROM events GROUP BY ALL ORDER BY param_id, year, board, signal) TO '{sql_path(str(output / 'annual.csv'))}' (HEADER, DELIMITER ',')""")
    con.execute(f"""COPY (SELECT param_id, sample_group, signal, exit_reason, count(*) AS n,
        avg(selected_net_return) AS mean_return FROM events GROUP BY ALL ORDER BY param_id, sample_group, signal, exit_reason)
      TO '{sql_path(str(output / 'exit_attribution.csv'))}' (HEADER, DELIMITER ',')""")
    best = con.execute(f"""
      WITH s AS (
        SELECT param_id, sample_group, count(*) AS n,
               {rate_expr} AS signals_per_year,
               avg(selected_net_return) AS mean_return,
               median(selected_net_return) AS median_return,
               avg(CASE WHEN selected_net_return>0 THEN 1.0 ELSE 0.0 END) AS win_rate
        FROM events GROUP BY param_id, sample_group
      )
      SELECT * FROM s WHERE sample_group={sample_group_filter}
      ORDER BY abs(signals_per_year-200) ASC, mean_return DESC, median_return DESC LIMIT 20
    """).fetchall()
    columns = [x[0] for x in con.description]
    best_rows = [dict(zip(columns, row, strict=True)) for row in best]
    con.close()
    result = {**manifest, "status": "COMPLETE", "best_by_signal_target": best_rows,
              "outputs": [str((output / name).resolve()) for name in ("events.parquet", "summary.csv", "annual.csv", "exit_attribution.csv")]}
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    write_ledger(ROOT / "data/audit/experiment_ledger.jsonl", {
        "event_id": f"{config['research_id']}-{source_hash[:12]}",
        "event_type": "FULL_BOOK_GRID_COMPLETE",
        "at": datetime.now(UTC).isoformat(),
        "status": "COMPLETE",
        "research_only": True,
        "parameter_count": len(grid),
        "discovery_range": [str(config["discovery_start"]), str(config["discovery_end"])],
        "timeout_range": [str(config["timeout_start"]), str(config["timeout_end"])],
        "holdout_accessed": bool(args.sample_label and "HOLDOUT" in args.sample_label.upper()),
        "holdout_tainted": False,
        "base_cache_key": source_hash,
        "outputs": str(output.resolve()),
    })
    print(json.dumps({"phase": "complete", "output": str(output), "best": best_rows[:5]}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
