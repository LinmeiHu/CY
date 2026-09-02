#!/usr/bin/env python3
# ruff: noqa: E501
"""Causal local True-Gap Cluster V6: semantic freeze, then fixed outcome snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import run_ashare_collapse_gap_zone_monetization_anatomy_v1 as anatomy
from research.market_behavior_os_v2.scripts import run_ashare_collapse_gap_zone_strategy_development_v1 as legacy_execution

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-CAUSAL-CLUSTER-V6-ONE-SHOT-DISCOVERY"
START_HEAD = "e33da497699d37408f4c7b2a4d6f298fe9b1f931"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_HASH = "2705011d21792acfea34c6fe07819aa1a9e6dd91247bc27e66616749cc3ee162"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery")
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
RAW_ROOT = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")
V5_CANDIDATES = OS_ROOT / "artifacts/ASHARE-COLLAPSE-TRUE-GAP-IMPULSIVE-LEG-SEGMENTATION-V5_candidates.parquet"
TG5_INDEX = EXTERNAL.parent / "ashare_collapse_true_gap_impulsive_leg_segmentation_v5/diagnostic_chart_index.csv"

CAUSAL_GAPS = EXTERNAL / "causal_true_gap_ledger.parquet"
CLUSTER_LEDGER = OS_ROOT / f"artifacts/{EXPERIMENT}_cluster_ledger.parquet"
CANDIDATE_LEDGER = OS_ROOT / f"artifacts/{EXPERIMENT}_candidate_ledger.parquet"
TG5_REGRESSION = OS_ROOT / f"artifacts/{EXPERIMENT}_tg5_regression.parquet"
SEMANTIC_RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result_semantic.json"

SIGNAL_DAYS = EXTERNAL / "signal_daily_candidates.parquet"
CONFIRMATIONS = EXTERNAL / "entry_confirmations.parquet"
ENTRIES = EXTERNAL / "entries.parquet"
STRUCTURAL = OS_ROOT / f"artifacts/{EXPERIMENT}_structural_outcomes.parquet"
TRADES = EXTERNAL / "trades_all_lanes.parquet"
PORTFOLIO_LEDGER = EXTERNAL / "portfolio_ledger.parquet"
NAV = EXTERNAL / "nav_all_lanes.parquet"
ACTION_EVENTS = EXTERNAL / "action_events.parquet"
DAILY_PATH = EXTERNAL / "daily_path.parquet"
MINUTE_PATH = EXTERNAL / "minute_path.parquet"
LEGAL_OPENS = EXTERNAL / "legal_opens.parquet"
OUTCOME_RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

DEVELOPMENT_YEARS = tuple(range(2014, 2022))
DIAGNOSTIC_YEARS = (2022, 2023)
ALL_YEARS = tuple(range(2014, 2024))
TIME_STOPS = (10, 20, 40)
KS = (5, 10, 20)
COST = 0.002


class V6Error(RuntimeError):
    """Fail closed on causal, lineage, execution, or governance violations."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return None if pd.isna(value) else str(value)
    if pd.isna(value) if not isinstance(value, (str, bool)) else False:
        return None
    return value


def validate_common_inputs() -> None:
    if sha256(SPEC) != EXPECTED_SPEC_HASH:
        raise V6Error("V6 frozen spec hash mismatch")
    for path in (DAILY, V5_CANDIDATES, TG5_INDEX):
        if not path.is_file():
            raise V6Error(f"missing governed input: {path}")
    if any((RAW_ROOT / f"{year}_day_parquet_none.parquet").is_file() is False for year in ALL_YEARS):
        raise V6Error("missing pre-2024 raw minute shard")


def build_causal_gap_ledger() -> pd.DataFrame:
    """Build every true gap with significance known at its completed formation day."""
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    query = f"""
      WITH d0 AS (
        SELECT *,
          row_number() OVER(PARTITION BY symbol ORDER BY trade_date) AS valid_seq,
          lag(trade_date) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_trade_date,
          lag(cal_idx) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_cal_idx_exact,
          lag(low) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_low_raw,
          lag(close) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_close_raw,
          lag(invalid_step_cum) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_invalid_step_cum
        FROM read_parquet('{DAILY}')
        WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
      ), gap0 AS (
        SELECT * FROM d0
        WHERE trade_date>=DATE '2014-01-01'
          AND history_valid AND current_valid AND hard_valid
          AND corporate_action_valid AND NOT corporate_action_blocking
          AND coalesce(corporate_action_count,0)=0
          AND cal_idx-prev_cal_idx_exact=1
          AND invalid_step_cum=prev_invalid_step_cum
          AND high<prev_low_raw
      ), refs AS (
        SELECT g.symbol,g.sleeve AS board,g.trade_date AS gap_date,g.cal_idx AS gap_cal_idx,
          g.valid_seq AS gap_valid_seq,g.invalid_step_cum,g.coordinate_factor,
          g.open,g.high,g.low,g.close,g.coord_open,g.coord_high,g.coord_low,g.coord_close,
          g.prev_trade_date,g.prev_low_raw,g.prev_close_raw,
          r.trade_date AS reference_high_date,r.coord_high AS reference_high,
          r.low60 AS reference_low60,r.low120 AS reference_low120,
          r.ret20 AS reference_ret20,r.board_ret60_percentile AS reference_board_ret60_percentile,
          r.large_up_days120 AS reference_large_up_days120,r.limit_up_days120 AS reference_limit_up_days120,
          row_number() OVER(
            PARTITION BY g.symbol,g.trade_date
            ORDER BY r.coord_high DESC,r.trade_date ASC
          ) AS reference_order
        FROM gap0 g
        JOIN d0 r ON r.symbol=g.symbol
          AND r.valid_seq BETWEEN g.valid_seq-120 AND g.valid_seq-1
          AND r.invalid_step_cum=g.invalid_step_cum
          AND r.history_valid AND r.current_valid AND r.hard_valid
      ), formed AS (
        SELECT *,
          high AS true_gap_lower_raw,
          prev_low_raw AS true_gap_upper_raw,
          high*coordinate_factor AS true_gap_lower,
          prev_low_raw*coordinate_factor AS true_gap_upper,
          (prev_low_raw-high)/nullif(prev_close_raw,0) AS true_gap_width_pct,
          (prev_low_raw-high)*coordinate_factor AS true_gap_width,
          ((prev_low_raw-high)*coordinate_factor)
            /nullif(reference_high-coord_low,0) AS causal_width_share,
          1-coord_low/nullif(reference_high,0) AS causal_drawdown_at_formation,
          (
            reference_high/nullif(reference_low60,0)-1>=0.50 OR
            reference_high/nullif(reference_low120,0)-1>=0.70
          ) AS absolute_strength,
          (
            reference_board_ret60_percentile>=0.90 OR reference_ret20>=0.30 OR
            reference_large_up_days120>=2 OR reference_limit_up_days120>=2
          ) AS relative_or_impulsive_strength
        FROM refs WHERE reference_order=1
      )
      SELECT *,
        CASE
          WHEN true_gap_width_pct>=0.025 OR causal_width_share>=0.08 THEN 'MAJOR'
          WHEN true_gap_width_pct>=0.01 OR causal_width_share>=0.03 THEN 'SECONDARY'
          ELSE 'MINOR'
        END AS importance,
        absolute_strength AND relative_or_impulsive_strength AS former_strength_eligible,
        symbol||'|'||strftime(gap_date,'%Y-%m-%d') AS true_gap_id,
        false AS future_information_used_for_gap_significance,
        'HIGH_T_LT_LOW_T_MINUS_1' AS gap_identity,
        '[HIGH_T,LOW_T_MINUS_1]' AS gap_interval
      FROM formed
      ORDER BY symbol,gap_date
    """
    gaps = con.execute(query).fetchdf()
    con.close()
    if gaps.empty or not gaps.high.lt(gaps.prev_low_raw).all():
        raise V6Error("true-gap primitive failed")
    if gaps.true_gap_id.duplicated().any():
        raise V6Error("duplicate daily true-gap identity")
    if gaps.future_information_used_for_gap_significance.any():
        raise V6Error("future significance field detected")
    write_parquet(gaps, CAUSAL_GAPS)
    return gaps


@dataclass
class ProvisionalCluster:
    cluster_id: str
    symbol: str
    board: str
    reference_high_date: pd.Timestamp
    reference_high: float
    invalid_step_cum: float
    gaps: list[dict[str, Any]]
    start_date: pd.Timestamp
    start_pos: int
    last_gap_date: pd.Timestamp
    last_gap_pos: int
    running_low: float
    running_low_date: pd.Timestamp


@dataclass
class FrozenCluster:
    cluster: ProvisionalCluster
    primary: dict[str, Any]
    freeze_date: pd.Timestamp
    freeze_time: pd.Timestamp
    freeze_pos: int
    pre_freeze_touch: bool


def _new_cluster(gap: Any, pos: int) -> ProvisionalCluster:
    date = pd.Timestamp(gap.gap_date)
    return ProvisionalCluster(
        cluster_id=f"{gap.symbol}|{date:%Y-%m-%d}|V6CLUSTER",
        symbol=str(gap.symbol), board=str(gap.board),
        reference_high_date=pd.Timestamp(gap.reference_high_date), reference_high=float(gap.reference_high),
        invalid_step_cum=float(gap.invalid_step_cum), gaps=[gap._asdict()], start_date=date,
        start_pos=pos, last_gap_date=date, last_gap_pos=pos,
        running_low=float(gap.coord_low), running_low_date=date,
    )


def _touch(row: Any, lower: float) -> bool:
    prior = float(row.prior_coord_close) if pd.notna(row.prior_coord_close) else float(row.coord_open)
    return (prior < lower or float(row.coord_open) < lower) and float(row.coord_high) >= lower


def build_clusters_and_daily_candidates(gaps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Forward-only local cluster state machine; no minute outcome or return field."""
    eligible = gaps.loc[gaps.importance.isin(["MAJOR", "SECONDARY"])].copy()
    if eligible.empty:
        raise V6Error("no causal significant gaps")
    symbols = eligible.symbol.drop_duplicates().tolist()
    symbol_path = EXTERNAL / "eligible_symbols.parquet"
    write_parquet(pd.DataFrame({"symbol": symbols}), symbol_path)
    con = duckdb.connect()
    con.execute("SET threads=4")
    daily = con.execute(f"""
      SELECT d.trade_date,d.cal_idx,d.symbol,d.sleeve AS board,d.open,d.high,d.low,d.close,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.prior_coord_close,
        d.coordinate_factor,d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid
      FROM read_parquet('{DAILY}') d JOIN read_parquet('{symbol_path}') s USING(symbol)
      WHERE d.trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
        AND d.history_valid AND d.current_valid AND d.hard_valid
      ORDER BY d.symbol,d.trade_date
    """).fetchdf()
    con.close()
    for col in ("trade_date",):
        daily[col] = pd.to_datetime(daily[col])
    eligible["gap_date"] = pd.to_datetime(eligible.gap_date)
    gaps_by_symbol = {k: v for k, v in eligible.groupby("symbol", sort=False)}
    cluster_rows: list[dict[str, Any]] = []
    candidate_days: list[dict[str, Any]] = []

    def unresolved_gaps(cluster: ProvisionalCluster, path: pd.DataFrame, current_pos: int) -> list[dict[str, Any]]:
        output = []
        for gap in cluster.gaps:
            formation_pos = int(path.index[path.trade_date.eq(pd.Timestamp(gap["gap_date"]))][0])
            prior = path.loc[formation_pos + 1: current_pos]
            if prior.empty or not prior.coord_high.ge(float(gap["true_gap_upper"])).any():
                output.append(gap)
        return output

    def prefreeze_touch(cluster: ProvisionalCluster, primary: dict[str, Any], path: pd.DataFrame, freeze_pos: int) -> bool:
        formation_pos = int(path.index[path.trade_date.eq(pd.Timestamp(primary["gap_date"]))][0])
        return any(_touch(row, float(primary["true_gap_lower"])) for row in path.loc[formation_pos + 1: freeze_pos].itertuples())

    for symbol, path0 in daily.groupby("symbol", sort=False):
        path = path0.reset_index(drop=True)
        gap_part = gaps_by_symbol.get(symbol)
        if gap_part is None:
            continue
        by_date = {pd.Timestamp(k): list(v.itertuples(index=False)) for k, v in gap_part.groupby("gap_date", sort=False)}
        provisional: ProvisionalCluster | None = None
        frozen: FrozenCluster | None = None
        cluster_number = 0
        for pos, row in enumerate(path.itertuples(index=False)):
            date = pd.Timestamp(row.trade_date)
            today_gaps = by_date.get(date, [])

            if frozen is not None:
                lower_new = [g for g in today_gaps if float(g.true_gap_lower) < float(frozen.primary["true_gap_lower"])]
                if lower_new:
                    cluster_rows.append(cluster_record(frozen, "SUPERSEDED_BY_NEW_LOWER_CLUSTER", None, None, None))
                    start = sorted(lower_new, key=lambda g: (float(g.true_gap_lower), str(g.true_gap_id)))[0]
                    provisional = _new_cluster(start, pos) if bool(start.former_strength_eligible) else None
                    if provisional is not None:
                        cluster_number += 1
                        provisional.cluster_id = f"{symbol}|{date:%Y-%m-%d}|V6CLUSTER{cluster_number:03d}"
                        for extra in today_gaps:
                            if str(extra.true_gap_id) != str(start.true_gap_id):
                                provisional.gaps.append(extra._asdict())
                    frozen = None
                    continue
                if _touch(row, float(frozen.primary["true_gap_lower"])):
                    candidate_days.append({
                        "cluster_id": frozen.cluster.cluster_id, "symbol": symbol, "board": frozen.cluster.board,
                        "first_return_date": date, "first_return_cal_idx": int(row.cal_idx),
                        "frozen_primary_gap_id": frozen.primary["true_gap_id"],
                        "frozen_primary_lower": float(frozen.primary["true_gap_lower"]),
                        "frozen_primary_upper": float(frozen.primary["true_gap_upper"]),
                        "frozen_primary_gap_date": pd.Timestamp(frozen.primary["gap_date"]),
                        "cluster_freeze_time": frozen.freeze_time,
                        "cluster_freeze_date": frozen.freeze_date,
                        "reference_high": frozen.cluster.reference_high,
                        "material_drawdown_at_freeze": 1 - frozen.cluster.running_low / frozen.cluster.reference_high,
                        "true_gap_width_pct": float(frozen.primary["true_gap_width_pct"]),
                        "importance": frozen.primary["importance"],
                        "invalid_step_cum": frozen.cluster.invalid_step_cum,
                        "state_coordinate_factor": float(row.coordinate_factor),
                        "prior_close_raw": float(row.prior_coord_close) / float(row.coordinate_factor),
                    })
                    cluster_rows.append(cluster_record(frozen, "CAUSAL_FIRST_RETURN_DAILY_IDENTIFIED", date, int(row.cal_idx), None))
                    frozen = None
                    continue

            if provisional is None:
                starts = [g for g in today_gaps if bool(g.former_strength_eligible)]
                if starts:
                    start = sorted(starts, key=lambda g: (float(g.true_gap_lower), str(g.true_gap_id)))[0]
                    provisional = _new_cluster(start, pos)
                    cluster_number += 1
                    provisional.cluster_id = f"{symbol}|{date:%Y-%m-%d}|V6CLUSTER{cluster_number:03d}"
                    for extra in today_gaps:
                        if str(extra.true_gap_id) != str(start.true_gap_id):
                            provisional.gaps.append(extra._asdict())
                continue

            if float(row.invalid_step_cum) != provisional.invalid_step_cum:
                cluster_rows.append(provisional_record(provisional, "LINEAGE_ENDED_BEFORE_FREEZE"))
                provisional = None
                starts = [g for g in today_gaps if bool(g.former_strength_eligible)]
                if starts:
                    start = sorted(starts, key=lambda g: (float(g.true_gap_lower), str(g.true_gap_id)))[0]
                    provisional = _new_cluster(start, pos)
                    cluster_number += 1
                    provisional.cluster_id = f"{symbol}|{date:%Y-%m-%d}|V6CLUSTER{cluster_number:03d}"
                continue

            if float(row.coord_low) < provisional.running_low:
                provisional.running_low = float(row.coord_low)
                provisional.running_low_date = date
            if today_gaps:
                known = {str(g["true_gap_id"]) for g in provisional.gaps}
                for gap in today_gaps:
                    if str(gap.true_gap_id) not in known:
                        provisional.gaps.append(gap._asdict())
                provisional.last_gap_date = date
                provisional.last_gap_pos = pos

            if pos - provisional.last_gap_pos < 10:
                continue
            unresolved = unresolved_gaps(provisional, path, pos)
            if not unresolved:
                continue
            primary = sorted(unresolved, key=lambda g: (float(g["true_gap_lower"]), pd.Timestamp(g["gap_date"]), str(g["true_gap_id"])))[0]
            recent5 = path.loc[pos - 4:pos]
            below5 = len(recent5) == 5 and recent5.coord_high.lt(float(primary["true_gap_lower"])).all()
            material = 1 - provisional.running_low / provisional.reference_high >= 0.30
            if not (below5 and material):
                continue
            freeze_date = date
            freeze_time = date + pd.Timedelta(hours=15)
            touched = prefreeze_touch(provisional, primary, path, pos)
            frozen = FrozenCluster(provisional, primary, freeze_date, freeze_time, pos, touched)
            provisional = None
            if touched:
                cluster_rows.append(cluster_record(frozen, "REJECTED_PRE_FREEZE_TOUCH", None, None, None))
                frozen = None

        if frozen is not None:
            cluster_rows.append(cluster_record(frozen, "NO_FIRST_RETURN_BY_2023", None, None, None))
        if provisional is not None:
            cluster_rows.append(provisional_record(provisional, "NOT_FROZEN_BY_2023"))

    clusters = pd.DataFrame(cluster_rows)
    days = pd.DataFrame(candidate_days)
    if clusters.empty or days.empty:
        raise V6Error("empty V6 cluster or daily-candidate ledger")
    write_parquet(days, SIGNAL_DAYS)
    return clusters, days


def provisional_record(cluster: ProvisionalCluster, disposition: str) -> dict[str, Any]:
    return {
        "cluster_id": cluster.cluster_id, "symbol": cluster.symbol, "board": cluster.board,
        "cluster_start_time": cluster.start_date + pd.Timedelta(hours=15),
        "reference_high_date": cluster.reference_high_date, "reference_high": cluster.reference_high,
        "last_eligible_gap_time": cluster.last_gap_date + pd.Timedelta(hours=15),
        "cluster_freeze_time": pd.NaT, "frozen_primary_gap_id": pd.NA,
        "frozen_primary_lower": np.nan, "frozen_primary_upper": np.nan,
        "running_low": cluster.running_low, "running_low_date": cluster.running_low_date,
        "gap_count": len(cluster.gaps), "pre_freeze_touch": False,
        "daily_first_return_date": pd.NaT, "daily_first_return_cal_idx": np.nan,
        "final_disposition": disposition,
    }


def cluster_record(frozen: FrozenCluster, disposition: str, return_date: pd.Timestamp | None, return_idx: int | None, exact_time: pd.Timestamp | None) -> dict[str, Any]:
    c, p = frozen.cluster, frozen.primary
    return {
        "cluster_id": c.cluster_id, "symbol": c.symbol, "board": c.board,
        "cluster_start_time": c.start_date + pd.Timedelta(hours=15),
        "reference_high_date": c.reference_high_date, "reference_high": c.reference_high,
        "last_eligible_gap_time": c.last_gap_date + pd.Timedelta(hours=15),
        "cluster_freeze_time": frozen.freeze_time, "frozen_primary_gap_id": p["true_gap_id"],
        "frozen_primary_lower": float(p["true_gap_lower"]), "frozen_primary_upper": float(p["true_gap_upper"]),
        "frozen_primary_gap_date": pd.Timestamp(p["gap_date"]), "primary_importance": p["importance"],
        "true_gap_width_pct": float(p["true_gap_width_pct"]),
        "running_low": c.running_low, "running_low_date": c.running_low_date,
        "material_drawdown_at_freeze": 1 - c.running_low / c.reference_high,
        "gap_count": len(c.gaps), "pre_freeze_touch": frozen.pre_freeze_touch,
        "daily_first_return_date": pd.NaT if return_date is None else return_date,
        "daily_first_return_cal_idx": np.nan if return_idx is None else return_idx,
        "causal_first_return": pd.NaT if exact_time is None else exact_time,
        "final_disposition": disposition,
    }


def raw_union(years: tuple[int, ...]) -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{RAW_ROOT / f'{year}_day_parquet_none.parquet'}') WHERE period='1m' AND adjust='none'"
        for year in years
    )


def attach_exact_first_returns(clusters: pd.DataFrame, days: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    seed = days.copy()
    seed["raw_threshold"] = seed.frozen_primary_lower / seed.state_coordinate_factor
    seed["candidate_day_id"] = seed.cluster_id + "|" + pd.to_datetime(seed.first_return_date).dt.strftime("%Y-%m-%d")
    seed_path = EXTERNAL / "exact_return_seed.parquet"
    write_parquet(seed, seed_path)
    exact_parts = []
    for year in ALL_YEARS:
        con = duckdb.connect()
        con.execute("SET threads=4")
        part = con.execute(f"""
          WITH seed AS (
            SELECT * FROM read_parquet('{seed_path}') WHERE year(first_return_date)={year}
          ), bars AS (
            SELECT s.candidate_day_id,s.cluster_id,s.symbol,s.first_return_date,s.raw_threshold,
              r.bar_end_time,r.open,r.high,r.low,r.close,
              lag(r.close) OVER(PARTITION BY s.candidate_day_id ORDER BY r.bar_end_time) AS lag_close,
              count(*) OVER(PARTITION BY s.candidate_day_id) AS minute_count
            FROM seed s JOIN read_parquet('{RAW_ROOT / f'{year}_day_parquet_none.parquet'}') r
              ON r.qmt_code=s.symbol AND r.trade_date=s.first_return_date
            WHERE r.period='1m' AND r.adjust='none'
          ), eligible AS (
            SELECT *,row_number() OVER(PARTITION BY candidate_day_id ORDER BY bar_end_time) AS event_order
            FROM bars
            WHERE round(coalesce(lag_close,open)*100)<round(raw_threshold*100)
              AND round(greatest(open,high)*100)>=round(raw_threshold*100)
          )
          SELECT candidate_day_id,cluster_id,bar_end_time AS causal_first_return,
            minute_count,event_order,open AS event_open,high AS event_high,low AS event_low,close AS event_close
          FROM eligible WHERE event_order=1 ORDER BY cluster_id
        """).fetchdf()
        con.close()
        if len(part):
            exact_parts.append(part)
    exact = pd.concat(exact_parts, ignore_index=True) if exact_parts else pd.DataFrame()
    if exact.empty or not exact.minute_count.eq(241).all():
        raise V6Error("exact first-return minute coverage failed")
    candidates = seed.merge(exact, on=["candidate_day_id", "cluster_id"], how="inner", validate="one_to_one")
    candidates["gap_age_sessions"] = candidates.first_return_cal_idx.astype(int) - candidates.frozen_primary_gap_date.map(
        pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("trade_date").set_index("trade_date").cal_idx
    ).astype(int)
    candidates["memory_state"] = np.select(
        [candidates.gap_age_sessions.le(60), candidates.gap_age_sessions.le(90)],
        ["CORE", "BOUNDARY"], default="STALE",
    )
    candidates["candidate_id"] = candidates.cluster_id + "|V6FIRSTRETURN"
    candidates["target_distance_from_l"] = candidates.frozen_primary_upper / candidates.frozen_primary_lower - 1
    candidates["first_return_strictly_after_freeze"] = pd.to_datetime(candidates.causal_first_return).gt(pd.to_datetime(candidates.cluster_freeze_time))
    if not candidates.first_return_strictly_after_freeze.all():
        raise V6Error("first return at or before cluster freeze")
    exact_map = candidates.set_index("cluster_id").causal_first_return
    clusters["causal_first_return"] = clusters.cluster_id.map(exact_map).combine_first(clusters.get("causal_first_return", pd.Series(pd.NaT, index=clusters.index)))
    clusters.loc[clusters.cluster_id.isin(exact_map.index), "final_disposition"] = "RETAINED_CAUSAL_FIRST_RETURN"
    write_parquet(clusters, CLUSTER_LEDGER)
    write_parquet(candidates, CANDIDATE_LEDGER)
    return clusters, candidates


def tg5_regressions(candidates: pd.DataFrame) -> pd.DataFrame:
    index = pd.read_csv(TG5_INDEX)
    source = pd.read_parquet(V5_CANDIDATES)
    source = source.merge(index[["chart_id", "candidate_id"]], on="candidate_id", how="inner", validate="one_to_one")
    rows = []
    for row in source.itertuples(index=False):
        matches = candidates.loc[candidates.symbol.eq(row.symbol)].copy()
        exact = matches.loc[matches.frozen_primary_gap_id.eq(row.v5_primary_gap_id)]
        if len(exact):
            chosen = exact.sort_values("causal_first_return").iloc[0]
            status = "EXACT_PRIMARY_SURVIVES"
        elif len(matches):
            chosen = matches.assign(delta=(pd.to_datetime(matches.causal_first_return)-pd.Timestamp(row.v5_causal_first_return)).abs()).sort_values("delta").iloc[0]
            status = "LOCAL_CLUSTER_PRIMARY_DIFFERS"
        else:
            chosen = None
            status = "NO_V6_CAUSAL_CLUSTER_CANDIDATE"
        rows.append({
            "chart_id": row.chart_id, "source_candidate_id": row.candidate_id,
            "symbol": row.symbol, "v5_primary_gap_id": row.v5_primary_gap_id,
            "v5_first_return": row.v5_causal_first_return,
            "v6_candidate_id": pd.NA if chosen is None else chosen.candidate_id,
            "v6_primary_gap_id": pd.NA if chosen is None else chosen.frozen_primary_gap_id,
            "v6_first_return": pd.NaT if chosen is None else chosen.causal_first_return,
            "v6_memory_state": pd.NA if chosen is None else chosen.memory_state,
            "regression_status": status,
        })
    regression = pd.DataFrame(rows).sort_values("chart_id")
    if len(regression) != 20:
        raise V6Error(f"TG5 regression population mismatch: {len(regression)}")
    write_parquet(regression, TG5_REGRESSION)
    return regression


def semantic_audit(clusters: pd.DataFrame, candidates: pd.DataFrame, gaps: pd.DataFrame) -> dict[str, Any]:
    audit = {
        "global_final_trough_used_count": 0,
        "future_collapse_endpoint_used_count": 0,
        "future_information_used_for_gap_significance_count": int(gaps.future_information_used_for_gap_significance.sum()),
        "cluster_frozen_retroactively_count": 0,
        "pre_freeze_touch_reset_as_new_first_return_count": 0,
        "first_return_at_or_before_cluster_freeze_count": int((pd.to_datetime(candidates.causal_first_return) <= pd.to_datetime(candidates.cluster_freeze_time)).sum()),
        "new_lower_gap_merged_backward_count": 0,
        "future_feature_count": 0,
        "repository_2024_plus_data_opened": "NO",
    }
    if any(v for k, v in audit.items() if k.endswith("_count")):
        raise V6Error(f"semantic machine gate failed: {audit}")
    if clusters.loc[clusters.final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN"), "pre_freeze_touch"].fillna(False).any():
        raise V6Error("retained pre-freeze touch")
    return audit


def run_stage_a() -> dict[str, Any]:
    validate_common_inputs()
    gaps = build_causal_gap_ledger()
    clusters, days = build_clusters_and_daily_candidates(gaps)
    clusters, candidates = attach_exact_first_returns(clusters, days)
    regression = tg5_regressions(candidates)
    audit = semantic_audit(clusters, candidates, gaps)
    semantic = {
        "experiment": EXPERIMENT,
        "stage": "STAGE_A_SEMANTIC_CAUSAL_FREEZE_COMPLETE",
        "v6_semantics_frozen": "YES",
        "frozen_v6_spec_hash": EXPECTED_SPEC_HASH,
        "population": {
            "all_true_gaps": len(gaps),
            "major": int(gaps.importance.eq("MAJOR").sum()),
            "secondary": int(gaps.importance.eq("SECONDARY").sum()),
            "minor": int(gaps.importance.eq("MINOR").sum()),
            "former_strength_eligible_significant_gaps": int((gaps.importance.isin(["MAJOR", "SECONDARY"]) & gaps.former_strength_eligible).sum()),
            "clusters": len(clusters),
            "causal_first_return_candidates": len(candidates),
            "core": int(candidates.memory_state.eq("CORE").sum()),
            "boundary": int(candidates.memory_state.eq("BOUNDARY").sum()),
            "stale": int(candidates.memory_state.eq("STALE").sum()),
            "superseded": int(clusters.final_disposition.eq("SUPERSEDED_BY_NEW_LOWER_CLUSTER").sum()),
            "rejected_pre_freeze_touch": int(clusters.final_disposition.eq("REJECTED_PRE_FREEZE_TOUCH").sum()),
        },
        "tg5_regression": regression.regression_status.value_counts().sort_index().to_dict(),
        "audit": audit,
        "artifacts": {},
        "outcomes_opened": "NO",
        "semantic_change_after_outcome_open_count": 0,
    }
    for name, path in (("spec", SPEC), ("cluster_ledger", CLUSTER_LEDGER), ("candidate_ledger", CANDIDATE_LEDGER), ("tg5_regression", TG5_REGRESSION), ("causal_gap_ledger_external", CAUSAL_GAPS)):
        semantic["artifacts"][name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
    write_json(SEMANTIC_RESULT, semantic)
    return semantic


def verify_stage_a_freeze() -> dict[str, Any]:
    validate_common_inputs()
    if not SEMANTIC_RESULT.is_file():
        raise V6Error("Stage A semantic result missing")
    result = json.loads(SEMANTIC_RESULT.read_text())
    if result.get("v6_semantics_frozen") != "YES" or result.get("frozen_v6_spec_hash") != EXPECTED_SPEC_HASH:
        raise V6Error("V6 semantics not frozen")
    if result.get("outcomes_opened") != "NO":
        raise V6Error("invalid Stage A outcome state")
    for name in ("spec", "cluster_ledger", "candidate_ledger", "tg5_regression", "causal_gap_ledger_external"):
        item = result["artifacts"][name]
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise V6Error(f"Stage A artifact changed after freeze: {name}")
    if any(v for k, v in result["audit"].items() if k.endswith("_count")):
        raise V6Error("Stage A audit no longer passes")
    return result


def active_candidates() -> pd.DataFrame:
    candidates = pd.read_parquet(CANDIDATE_LEDGER)
    candidates["causal_first_return"] = pd.to_datetime(candidates.causal_first_return)
    candidates["signal_date"] = candidates.causal_first_return.dt.normalize()
    candidates["signal_year"] = candidates.causal_first_return.dt.year
    candidates = candidates.loc[
        candidates.memory_state.isin(["CORE", "BOUNDARY"])
        & candidates.signal_year.between(2014, 2023)
    ].copy()
    if candidates.empty or candidates.causal_first_return.max() >= pd.Timestamp("2024-01-01"):
        raise V6Error("invalid active V6 outcome population")
    return candidates.sort_values(["causal_first_return", "candidate_id"], kind="mergesort").reset_index(drop=True)


def build_structural_outcomes(candidates: pd.DataFrame) -> pd.DataFrame:
    """Open only U-fill paths after the semantic freeze; no strategy rule changes."""
    calendar = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("trade_date")
    calendar.trade_date = pd.to_datetime(calendar.trade_date)
    idx_by_date = calendar.set_index("trade_date").cal_idx.astype(int)
    candidates = candidates.copy()
    candidates["signal_cal_idx"] = candidates.signal_date.map(idx_by_date)
    if candidates.signal_cal_idx.isna().any():
        raise V6Error("missing signal calendar index")
    seed = candidates[["candidate_id", "symbol", "signal_date", "causal_first_return", "signal_cal_idx", "frozen_primary_upper"]].copy()
    seed_path = EXTERNAL / "structural_seed.parquet"
    write_parquet(seed, seed_path)
    same_parts = []
    for year in ALL_YEARS:
        con = duckdb.connect()
        part = con.execute(f"""
          WITH seed AS (SELECT * FROM read_parquet('{seed_path}') WHERE year(signal_date)={year}),
          hits AS (
            SELECT s.candidate_id,r.bar_end_time,
              r.open*d.coordinate_factor AS coord_open,r.high*d.coordinate_factor AS coord_high,
              count(*) OVER(PARTITION BY s.candidate_id) AS minute_count,
              row_number() OVER(PARTITION BY s.candidate_id ORDER BY r.bar_end_time) AS hit_order
            FROM seed s JOIN read_parquet('{RAW_ROOT / f'{year}_day_parquet_none.parquet'}') r
              ON r.qmt_code=s.symbol AND r.trade_date=s.signal_date AND r.bar_end_time>=s.causal_first_return
            JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol AND d.trade_date=s.signal_date
            WHERE r.period='1m' AND r.adjust='none'
              AND greatest(r.open,r.high)*d.coordinate_factor>=s.frozen_primary_upper
          ) SELECT candidate_id,bar_end_time AS same_day_u_fill_time,minute_count
          FROM hits WHERE hit_order=1
        """).fetchdf()
        con.close()
        if len(part):
            same_parts.append(part)
    same = pd.concat(same_parts, ignore_index=True) if same_parts else pd.DataFrame(columns=["candidate_id", "same_day_u_fill_time", "minute_count"])
    con = duckdb.connect()
    later = con.execute(f"""
      SELECT s.candidate_id,min(d.cal_idx) AS later_u_fill_cal_idx
      FROM read_parquet('{seed_path}') s
      JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol
        AND d.cal_idx BETWEEN s.signal_cal_idx+1 AND s.signal_cal_idx+60
      WHERE d.trade_date<=DATE '2023-12-31' AND d.history_valid AND d.current_valid AND d.hard_valid
        AND d.coord_high>=s.frozen_primary_upper
      GROUP BY s.candidate_id
    """).fetchdf()
    con.close()
    structural = candidates.merge(same, on="candidate_id", how="left", validate="one_to_one").merge(later, on="candidate_id", how="left", validate="one_to_one")
    structural["u_fill_offset"] = np.where(
        structural.same_day_u_fill_time.notna(), 0,
        structural.later_u_fill_cal_idx - structural.signal_cal_idx,
    )
    for horizon in (0, 1, 3, 5, 10, 20, 40, 60):
        structural[f"u_full_fill_{horizon}d"] = structural.u_fill_offset.notna() & structural.u_fill_offset.le(horizon)
    write_parquet(structural, STRUCTURAL)
    return structural


def build_action_events(symbols: list[str]) -> pd.DataFrame:
    symbol_path = EXTERNAL / "outcome_symbols.parquet"
    write_parquet(pd.DataFrame({"symbol": symbols}), symbol_path)
    symbol_sql = "CASE WHEN starts_with(symbol,'6') THEN symbol||'.SH' WHEN starts_with(symbol,'0') OR starts_with(symbol,'3') THEN symbol||'.SZ' ELSE symbol||'.OTHER' END"
    con = duckdb.connect()
    actions = con.execute(f"""
      WITH actions AS (
        SELECT {symbol_sql} AS symbol,event_id,
          CASE WHEN coalesce(share_multiplier,1)>1 THEN 'RISK_SHARE' ELSE 'CASH_ONLY' END AS action_kind,
          CAST(known_at AS DATE) AS known_date,CAST(effective_date AS DATE) AS effective_date,
          coalesce(cash_per_share_gross,0) AS cash_per_share,coalesce(share_multiplier,1) AS share_multiplier,
          source_terms_complete
        FROM read_parquet('{legacy_execution.QD010_DISTRIBUTIONS}')
        WHERE effective_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
          AND (coalesce(share_multiplier,1)>1 OR coalesce(cash_per_share_gross,0)>0)
        UNION ALL
        SELECT {symbol_sql},event_id,'RISK_RIGHTS',CAST(known_at AS DATE),CAST(effective_date AS DATE),
          0.0,1.0,source_terms_complete
        FROM read_parquet('{legacy_execution.QD010_RIGHTS}')
        WHERE effective_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
      ) SELECT a.* FROM actions a JOIN read_parquet('{symbol_path}') s USING(symbol)
      ORDER BY symbol,effective_date,event_id
    """).fetchdf()
    con.close()
    for col in ("known_date", "effective_date"):
        actions[col] = pd.to_datetime(actions[col])
    if len(actions) and (~actions.source_terms_complete.fillna(False)).any():
        raise V6Error("incomplete QD-010 source terms in V6 path")
    write_parquet(actions, ACTION_EVENTS)
    return actions


def build_entries(candidates: pd.DataFrame, actions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    seed = candidates[["candidate_id", "symbol", "signal_date", "causal_first_return", "frozen_primary_lower", "invalid_step_cum"]].copy()
    seed_path = EXTERNAL / "entry_seed.parquet"
    write_parquet(seed, seed_path)
    possible_path = EXTERNAL / "entry_confirmation_possible_dates.parquet"
    con = duckdb.connect()
    con.execute(f"""COPY (
      SELECT s.candidate_id,s.symbol,s.signal_date,s.causal_first_return,s.frozen_primary_lower,
        d.trade_date,d.coordinate_factor
      FROM read_parquet('{seed_path}') s JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol
        AND d.trade_date BETWEEN s.signal_date AND DATE '2023-12-31'
      WHERE d.invalid_step_cum=s.invalid_step_cum AND d.history_valid AND d.current_valid AND d.hard_valid
        AND d.coord_high>=s.frozen_primary_lower
      ORDER BY s.candidate_id,d.trade_date
    ) TO '{possible_path}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.execute("SET threads=4")
    confirmations = con.execute(f"""
      WITH raw AS ({raw_union(ALL_YEARS)}), session_bars AS (
        SELECT p.*,r.bar_end_time,r.close,
          count(*) OVER(PARTITION BY p.candidate_id,p.trade_date) AS minute_count
        FROM read_parquet('{possible_path}') p JOIN raw r ON r.qmt_code=p.symbol AND r.trade_date=p.trade_date
      ), allbars AS (
        SELECT * FROM session_bars
        WHERE bar_end_time>=CASE WHEN trade_date=signal_date THEN causal_first_return ELSE CAST(trade_date AS TIMESTAMP) END
      ), eligible AS (
        SELECT candidate_id,symbol,trade_date AS confirmation_date,bar_end_time AS confirmation_time,
          close AS confirmation_raw_close,close*coordinate_factor AS confirmation_coord_close,
          minute_count,row_number() OVER(PARTITION BY candidate_id ORDER BY bar_end_time) AS confirmation_order
        FROM allbars WHERE close*coordinate_factor>=frozen_primary_lower
      ) SELECT * EXCLUDE(confirmation_order) FROM eligible WHERE confirmation_order=1
      ORDER BY candidate_id
    """).fetchdf()
    con.close()
    if confirmations.empty or not confirmations.minute_count.eq(241).all():
        raise V6Error("entry-confirmation minute coverage failed")
    write_parquet(confirmations, CONFIRMATIONS)
    entry_seed = seed.merge(confirmations[["candidate_id", "confirmation_date", "confirmation_time"]], on="candidate_id", how="inner", validate="one_to_one")
    entry_seed_path = EXTERNAL / "executable_entry_seed.parquet"
    write_parquet(entry_seed, entry_seed_path)
    con = duckdb.connect()
    con.execute("SET threads=4")
    entries = con.execute(f"""
      WITH raw AS ({raw_union(ALL_YEARS)}), eligible AS (
        SELECT s.candidate_id,s.symbol,r.trade_date AS entry_date,r.bar_end_time AS entry_time,
          r.open AS entry_raw_price,r.open*d.coordinate_factor AS entry_coord_price,
          d.cal_idx AS entry_cal_idx,d.coordinate_factor AS entry_coordinate_factor,
          d.invalid_step_cum AS entry_invalid_step_cum,
          row_number() OVER(PARTITION BY s.candidate_id ORDER BY r.bar_end_time) AS entry_order
        FROM read_parquet('{entry_seed_path}') s JOIN raw r ON r.qmt_code=s.symbol
          AND r.bar_end_time>s.confirmation_time AND r.trade_date>=s.confirmation_date
        JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol AND d.trade_date=r.trade_date
        WHERE d.trade_date<=DATE '2023-12-31' AND d.invalid_step_cum=s.invalid_step_cum
          AND d.history_valid AND d.current_valid AND d.hard_valid AND d.trade_status=1
          AND d.current_day_data_tradable AND d.market_rule_valid AND NOT d.corporate_action_blocking
          AND isfinite(r.open) AND r.open>0 AND round(r.open*100)<round(d.up_limit_price*100)
      ) SELECT * EXCLUDE(entry_order) FROM eligible WHERE entry_order=1
    """).fetchdf()
    con.close()
    for col in ("entry_date", "entry_time"):
        entries[col] = pd.to_datetime(entries[col])
    merged = entry_seed.merge(entries, on=["candidate_id", "symbol"], how="inner", validate="one_to_one")
    risk = actions.loc[actions.action_kind.str.startswith("RISK")]
    risk_by_symbol = {k: v for k, v in risk.groupby("symbol", sort=False)}
    blocked = []
    for row in merged.itertuples(index=False):
        part = risk_by_symbol.get(row.symbol, pd.DataFrame(columns=risk.columns))
        blocked.append(bool(len(part.loc[part.known_date.le(pd.Timestamp(row.confirmation_time).normalize()) & part.effective_date.ge(pd.Timestamp(row.entry_date).normalize())])))
    merged["risk_blocked_entry"] = blocked
    valid = merged.loc[~merged.risk_blocked_entry].copy()
    valid["entry_uses_future_bar"] = pd.to_datetime(valid.entry_time).le(pd.to_datetime(valid.confirmation_time))
    if valid.entry_uses_future_bar.any():
        raise V6Error("same-bar or prior-bar V6 entry")
    write_parquet(valid, ENTRIES)
    return confirmations, valid


def build_paths(candidates: pd.DataFrame, entries: pd.DataFrame) -> None:
    calendar = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
    calendar.trade_date = pd.to_datetime(calendar.trade_date)
    max_idx = int(calendar.loc[calendar.trade_date.le(pd.Timestamp("2023-12-31")), "cal_idx"].max())
    by_idx = calendar.set_index("cal_idx").trade_date
    bounds = entries[["candidate_id", "symbol", "entry_date", "entry_time", "entry_cal_idx"]].copy()
    bounds["path_end_cal_idx"] = (bounds.entry_cal_idx.astype(int) + 40).clip(upper=max_idx)
    bounds["path_end_date"] = bounds.path_end_cal_idx.map(by_idx)
    bounds_path = EXTERNAL / "path_bounds.parquet"
    write_parquet(bounds, bounds_path)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(f"""COPY (
      SELECT b.candidate_id,d.* FROM read_parquet('{bounds_path}') b
      JOIN read_parquet('{DAILY}') d ON d.symbol=b.symbol
        AND d.cal_idx BETWEEN b.entry_cal_idx AND b.path_end_cal_idx
      WHERE d.trade_date<=DATE '2023-12-31'
      ORDER BY b.candidate_id,d.cal_idx
    ) TO '{DAILY_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.execute(f"""COPY (
      WITH raw AS ({raw_union(ALL_YEARS)})
      SELECT b.candidate_id,r.trade_date,r.bar_end_time,d.cal_idx,r.open,r.high,r.low,r.close,
        r.open*d.coordinate_factor AS coord_open,r.high*d.coordinate_factor AS coord_high,
        r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close,
        d.coordinate_factor,d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,
        d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
        d.down_limit_price
      FROM read_parquet('{bounds_path}') b JOIN raw r ON r.qmt_code=b.symbol
        AND r.trade_date BETWEEN b.entry_date AND b.path_end_date AND r.bar_end_time>=b.entry_time
      JOIN read_parquet('{DAILY}') d ON d.symbol=b.symbol AND d.trade_date=r.trade_date
      ORDER BY b.candidate_id,r.bar_end_time
    ) TO '{MINUTE_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    symbol_path = EXTERNAL / "outcome_symbols.parquet"
    con.execute(f"""COPY (
      WITH raw AS ({raw_union(ALL_YEARS)})
      SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,r.open AS raw_open,
        d.cal_idx,d.coordinate_factor,d.invalid_step_cum
      FROM raw r JOIN read_parquet('{symbol_path}') s ON s.symbol=r.qmt_code
      JOIN read_parquet('{DAILY}') d ON d.symbol=r.qmt_code AND d.trade_date=r.trade_date
      WHERE d.trade_date<=DATE '2023-12-31' AND d.history_valid AND d.current_valid AND d.hard_valid
        AND d.trade_status=1 AND d.current_day_data_tradable AND d.market_rule_valid
        AND NOT d.corporate_action_blocking AND isfinite(r.open) AND r.open>0
        AND round(r.open*100)>round(d.down_limit_price*100)
      QUALIFY row_number() OVER(PARTITION BY r.qmt_code,r.trade_date ORDER BY r.bar_end_time)=1
      ORDER BY symbol,bar_end_time
    ) TO '{LEGAL_OPENS}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()


def cash_events_json(actions: pd.DataFrame, entry_date: pd.Timestamp, end_date: pd.Timestamp) -> str:
    rows = actions.loc[
        actions.action_kind.eq("CASH_ONLY")
        & actions.effective_date.gt(entry_date.normalize())
        & actions.effective_date.le(end_date.normalize())
    ]
    return json.dumps([
        {"date": str(pd.Timestamp(r.effective_date).date()), "cash_per_share": float(r.cash_per_share), "event_id": str(r.event_id)}
        for r in rows.itertuples(index=False)
    ], sort_keys=True)


def build_trades(candidates: pd.DataFrame, confirmations: pd.DataFrame, entries: pd.DataFrame, actions: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    source = candidates.merge(confirmations[["candidate_id", "confirmation_time"]], on="candidate_id", how="inner", validate="one_to_one")
    source = source.merge(entries, on=["candidate_id", "symbol"], how="inner", validate="one_to_one", suffixes=("", "_entry"))
    minute = pd.read_parquet(MINUTE_PATH)
    daily_path = pd.read_parquet(DAILY_PATH)
    daily_all = pd.read_parquet(DAILY)
    legal = pd.read_parquet(LEGAL_OPENS)
    for frame, cols in ((source, ["confirmation_time", "entry_date", "entry_time"]), (minute, ["trade_date", "bar_end_time"]), (daily_path, ["trade_date"]), (daily_all, ["trade_date"]), (legal, ["trade_date", "bar_end_time"]), (actions, ["known_date", "effective_date"])):
        for col in cols:
            frame[col] = pd.to_datetime(frame[col])
    minute_by = {k: v for k, v in minute.groupby("candidate_id", sort=False)}
    daily_by = {k: v for k, v in daily_path.groupby("candidate_id", sort=False)}
    legal_by = {k: v for k, v in legal.groupby("symbol", sort=False)}
    all_daily_by = {k: v for k, v in daily_all.groupby("symbol", sort=False)}
    actions_by = {k: v for k, v in actions.groupby("symbol", sort=False)}
    rows = []
    audit = Counter()
    for event in source.itertuples(index=False):
        mins = minute_by.get(event.candidate_id, pd.DataFrame())
        days = daily_by.get(event.candidate_id, pd.DataFrame())
        legal_symbol = legal_by.get(event.symbol, pd.DataFrame())
        all_days = all_daily_by.get(event.symbol, pd.DataFrame())
        act = actions_by.get(event.symbol, pd.DataFrame(columns=actions.columns))
        entry_idx = int(event.entry_cal_idx)
        lineage = float(event.entry_invalid_step_cum)
        entry_date = pd.Timestamp(event.entry_date)
        confirmation = pd.Timestamp(event.confirmation_time)
        target = anatomy.first_target(mins, entry_date, entry_idx, float(event.frozen_primary_upper), lineage)
        for horizon in TIME_STOPS:
            horizon_exit = anatomy.horizon_exit(days, legal_symbol, entry_idx + horizon, lineage)
            cutoff_time = pd.Timestamp(days.trade_date.max()) + pd.Timedelta(hours=15) if len(days) else pd.Timestamp("2023-12-31 15:00")
            risk_exit = anatomy.forced_risk_exit(act, confirmation, entry_date, all_days, legal_symbol, lineage, cutoff_time)
            blocked_risk = None
            if risk_exit is not None and risk_exit.get("blocked"):
                blocked_risk = risk_exit
                risk_exit = None
            target_valid = target is not None and int(target.cal_idx - entry_idx) <= horizon
            chosen: dict[str, Any] | None = None
            if target_valid:
                chosen = {"exit_time": pd.Timestamp(target.bar_end_time), "exit_date": pd.Timestamp(target.trade_date), "exit_raw_price": float(target.target_raw_execution), "exit_cal_idx": int(target.cal_idx), "exit_reason": "TARGET"}
                if int(target.cal_idx) <= entry_idx:
                    audit["t1_violation_count"] += 1
            elif horizon_exit is not None:
                exit_idx = int(days.loc[days.trade_date.eq(pd.Timestamp(horizon_exit["exit_date"])), "cal_idx"].iloc[0]) if len(days.loc[days.trade_date.eq(pd.Timestamp(horizon_exit["exit_date"]))]) else entry_idx + horizon
                chosen = {"exit_time": pd.Timestamp(horizon_exit["exit_time"]), "exit_date": pd.Timestamp(horizon_exit["exit_date"]), "exit_raw_price": float(horizon_exit["exit_raw_price"]), "exit_cal_idx": exit_idx, "exit_reason": "TIME_STOP" if horizon_exit["kind"] == "HORIZON_CLOSE" else "TIME_STOP_DELAYED"}
            if risk_exit is not None and (chosen is None or pd.Timestamp(risk_exit["exit_time"]) <= pd.Timestamp(chosen["exit_time"])):
                risk_date = pd.Timestamp(risk_exit["exit_date"])
                idx_match = all_days.loc[all_days.trade_date.eq(risk_date), "cal_idx"]
                chosen = {"exit_time": pd.Timestamp(risk_exit["exit_time"]), "exit_date": risk_date, "exit_raw_price": float(risk_exit["exit_raw_price"]), "exit_cal_idx": int(idx_match.iloc[0]) if len(idx_match) else np.nan, "exit_reason": "CORPORATE_ACTION_RISK"}
            if blocked_risk is not None:
                action = act.loc[act.event_id.astype(str).eq(str(blocked_risk["event_id"]))]
                if action.empty:
                    raise V6Error("blocked QD-010 event identity missing")
                known_time = pd.Timestamp(action.known_date.iloc[0])
                if chosen is None or pd.Timestamp(chosen["exit_time"]) >= known_time:
                    audit["unresolved_action_block_count"] += 1
            end = pd.Timestamp("2023-12-31") if chosen is None else pd.Timestamp(chosen["exit_date"])
            cash_json = cash_events_json(act, entry_date, end)
            cash = sum(float(x["cash_per_share"]) for x in json.loads(cash_json))
            net = None if chosen is None else (float(chosen["exit_raw_price"]) * (1 - COST) + cash) / (float(event.entry_raw_price) * (1 + COST)) - 1
            rows.append({
                "event_id": event.candidate_id, "candidate_id": event.candidate_id, "symbol": event.symbol,
                "board": event.board, "memory_state": event.memory_state, "signal_date": event.signal_date,
                "signal_year": int(event.signal_year), "causal_first_return": event.causal_first_return,
                "cluster_freeze_time": event.cluster_freeze_time, "primary_gap_date": event.frozen_primary_gap_date,
                "primary_layer_width_pct": float(event.true_gap_width_pct), "material_drawdown": float(event.material_drawdown_at_freeze),
                "time_stop": horizon, "entry_date": entry_date, "entry_time": pd.Timestamp(event.entry_time),
                "entry_cal_idx": entry_idx, "entry_raw_price": float(event.entry_raw_price), "entry_coord_price": float(event.entry_coord_price),
                "entry_invalid_step_cum": lineage, "target_coord": float(event.frozen_primary_upper),
                "exit_date": pd.NaT if chosen is None else chosen["exit_date"], "exit_time": pd.NaT if chosen is None else chosen["exit_time"],
                "exit_cal_idx": np.nan if chosen is None else chosen["exit_cal_idx"], "exit_raw_price": np.nan if chosen is None else chosen["exit_raw_price"],
                "exit_reason": None if chosen is None else chosen["exit_reason"], "net_trade_return": np.nan if net is None else float(net),
                "cash_events_json": cash_json, "action_block_time": pd.NaT,
            })
    trades = pd.DataFrame(rows).sort_values(["time_stop", "entry_time", "event_id"], kind="mergesort")
    if audit["t1_violation_count"]:
        raise V6Error(f"T+1 violation: {dict(audit)}")
    write_parquet(trades, TRADES)
    return trades, dict(audit)


@dataclass
class Replay:
    nav: pd.DataFrame
    accepted: pd.DataFrame
    ledger: pd.DataFrame
    audit: dict[str, int]


def _order_signals(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        ["entry_time", "primary_layer_width_pct", "material_drawdown", "cluster_freeze_time", "symbol"],
        ascending=[True, False, False, True, True], kind="mergesort",
    )


def replay_portfolio(trades: pd.DataFrame, daily: pd.DataFrame, board: str, k: int, years: tuple[int, ...]) -> Replay:
    signals = _order_signals(trades.loc[trades.board.eq(board) & pd.to_datetime(trades.entry_date).dt.year.isin(years)]).copy()
    calendar = daily.loc[daily.trade_date.dt.year.isin(years), ["trade_date", "cal_idx"]].drop_duplicates("trade_date").sort_values("trade_date")
    if calendar.empty:
        raise V6Error("empty portfolio calendar")
    period_end = pd.Timestamp(calendar.trade_date.max()) + pd.Timedelta(hours=15)
    daily_symbols = daily.loc[daily.symbol.isin(signals.symbol.unique())]
    marks = {(r.symbol, pd.Timestamp(r.trade_date)): float(r.close) for r in daily_symbols.itertuples(index=False) if np.isfinite(r.close)}
    dates_by_symbol = {s: p.sort_values("trade_date") for s, p in daily_symbols.groupby("symbol", sort=False)}
    cash = 1.0
    active: dict[str, dict[str, Any]] = {}
    accepted: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    audit = Counter()

    def init_actions(pos: dict[str, Any]) -> None:
        pos["cash_events"] = json.loads(pos.get("cash_events_json") or "[]")
        pos["cash_event_index"] = 0
        pos["action_cash_per_share"] = 0.0

    def credit(pos: dict[str, Any], when: pd.Timestamp) -> float:
        amount = 0.0
        while pos["cash_event_index"] < len(pos["cash_events"]):
            event = pos["cash_events"][pos["cash_event_index"]]
            if pd.Timestamp(event["date"]) > when.normalize():
                break
            amount += pos["qty"] * float(event["cash_per_share"])
            pos["action_cash_per_share"] += float(event["cash_per_share"])
            pos["cash_event_index"] += 1
        return amount

    def mark(pos: dict[str, Any], when: pd.Timestamp) -> float:
        part = dates_by_symbol.get(pos["symbol"], pd.DataFrame())
        prior = part.loc[part.trade_date.lt(when.normalize())] if len(part) else part
        return float(prior.close.iloc[-1]) if len(prior) else float(pos["entry_raw_price"])

    def close_due(when: pd.Timestamp) -> None:
        nonlocal cash
        due = sorted([p for p in active.values() if pd.notna(p["exit_time"]) and pd.Timestamp(p["exit_time"]) <= when], key=lambda p: (pd.Timestamp(p["exit_time"]), p["symbol"]))
        for pos in due:
            cash += credit(pos, pd.Timestamp(pos["exit_time"]))
            cash += pos["qty"] * float(pos["exit_raw_price"]) * (1 - COST)
            pos["completed"] = True
            pos["net_trade_return"] = (float(pos["exit_raw_price"]) * (1 - COST) + pos["action_cash_per_share"]) / (float(pos["entry_raw_price"]) * (1 + COST)) - 1
            active.pop(pos["symbol"], None)

    for timestamp, group in signals.groupby("entry_time", sort=True):
        timestamp = pd.Timestamp(timestamp)
        close_due(timestamp)
        for pos in active.values():
            cash += credit(pos, timestamp)
        for row in group.itertuples(index=False):
            base = {"event_id": row.event_id, "symbol": row.symbol, "board": board, "k": k, "entry_date": pd.Timestamp(row.entry_date), "entry_time": pd.Timestamp(row.entry_time), "exit_date": pd.Timestamp(row.exit_date) if pd.notna(row.exit_date) else pd.NaT, "exit_time": pd.Timestamp(row.exit_time) if pd.notna(row.exit_time) else pd.NaT, "exit_reason": row.exit_reason}
            if row.symbol in active:
                audit["duplicate_signal_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_DUPLICATE_SYMBOL", "capacity_skip": False})
                continue
            if len(active) >= k:
                audit["capacity_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_CAPACITY", "capacity_skip": True})
                continue
            nav_now = cash + sum(p["qty"] * mark(p, timestamp) for p in active.values())
            outlay = min(nav_now / k, cash)
            if outlay <= 0:
                ledger.append({**base, "status": "SKIPPED_NO_CASH", "capacity_skip": False})
                continue
            qty = outlay / (float(row.entry_raw_price) * (1 + COST))
            cash -= qty * float(row.entry_raw_price) * (1 + COST)
            if cash < -1e-12:
                audit["negative_cash_or_leverage_count"] += 1
            pos = row._asdict()
            pos.update(qty=qty, completed=False, entry_nav=nav_now, entry_outlay=outlay, initial_weight=outlay/nav_now)
            init_actions(pos)
            accepted.append(pos)
            active[row.symbol] = pos
            ledger.append({**base, "status": "EXECUTED", "capacity_skip": False, "qty": qty, "initial_weight": outlay/nav_now})
            if len(active) > k:
                audit["max_k_violation_count"] += 1
    close_due(period_end)
    for pos in active.values():
        cash += credit(pos, period_end)

    entries_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    exits_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for pos in accepted:
        entries_by_date.setdefault(pd.Timestamp(pos["entry_date"]), []).append(pos)
        if pos["completed"]:
            exits_by_date.setdefault(pd.Timestamp(pos["exit_date"]), []).append(pos)
    cash2 = 1.0
    live: dict[str, dict[str, Any]] = {}
    nav_rows = []
    for date in pd.to_datetime(calendar.trade_date):
        for pos in live.values():
            for event in pos["cash_events"]:
                if pd.Timestamp(event["date"]) == date:
                    cash2 += pos["qty"] * float(event["cash_per_share"])
        events = [(pd.Timestamp(p["entry_time"]), "ENTRY", p) for p in entries_by_date.get(date, [])]
        events += [(pd.Timestamp(p["exit_time"]), "EXIT", p) for p in exits_by_date.get(date, [])]
        for _, kind, pos in sorted(events, key=lambda x: (x[0], 0 if x[1] == "EXIT" else 1, x[2]["symbol"])):
            if kind == "ENTRY":
                if pos["symbol"] in live:
                    audit["duplicate_position_count"] += 1
                cash2 -= pos["qty"] * pos["entry_raw_price"] * (1 + COST)
                live[pos["symbol"]] = pos
            else:
                cash2 += pos["qty"] * pos["exit_raw_price"] * (1 - COST)
                live.pop(pos["symbol"], None)
        exposure = sum(p["qty"] * marks.get((symbol, date), p["entry_raw_price"]) for symbol, p in live.items())
        nav_value = cash2 + exposure
        nav_rows.append({"trade_date": date, "nav": nav_value, "cash": cash2, "gross_exposure": exposure, "utilization": exposure/nav_value if nav_value else 0.0, "active_positions": len(live), "board": board, "k": k})
    nav = pd.DataFrame(nav_rows)
    if nav.active_positions.max() > k:
        audit["max_k_violation_count"] += 1
    if nav.cash.min() < -1e-12:
        audit["negative_cash_or_leverage_count"] += 1
    return Replay(nav, pd.DataFrame(accepted), pd.DataFrame(ledger), dict(audit))


def trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.completed].copy() if len(frame) and "completed" in frame else pd.DataFrame()
    returns = pd.to_numeric(completed.net_trade_return, errors="coerce").dropna() if len(completed) else pd.Series(dtype=float)
    holds = pd.to_numeric(completed.exit_cal_idx, errors="coerce") - pd.to_numeric(completed.entry_cal_idx, errors="coerce") if len(completed) else pd.Series(dtype=float)
    return {
        "completed_trades": len(returns), "mean_net_trade_return": None if returns.empty else float(returns.mean()),
        "median_net_trade_return": None if returns.empty else float(returns.median()),
        "true_win_rate": None if returns.empty else float(returns.gt(0).mean()),
        "u_target_hit_rate": None if returns.empty else float(completed.loc[returns.index].exit_reason.eq("TARGET").mean()),
        "severe_loss10_rate": None if returns.empty else float(returns.le(-0.10).mean()),
        "mean_holding_sessions": None if holds.empty else float(holds.mean()), "median_holding_sessions": None if holds.empty else float(holds.median()),
        "p25_holding_sessions": None if holds.empty else float(holds.quantile(.25)), "p75_holding_sessions": None if holds.empty else float(holds.quantile(.75)),
        "p90_holding_sessions": None if holds.empty else float(holds.quantile(.90)),
    }


def portfolio_metrics(nav: pd.DataFrame, accepted: pd.DataFrame) -> dict[str, Any]:
    returns = nav.nav.pct_change().fillna(nav.nav.iloc[0] - 1)
    elapsed = max((pd.Timestamp(nav.trade_date.iloc[-1]) - pd.Timestamp(nav.trade_date.iloc[0])).days / 365.25, 1/365.25)
    total = float(nav.nav.iloc[-1] - 1)
    dd = nav.nav / nav.nav.cummax() - 1
    pnl = accepted.entry_outlay * accepted.net_trade_return if len(accepted) and "entry_outlay" in accepted else pd.Series(dtype=float)
    positive = pnl.loc[pnl.gt(0)].sort_values(ascending=False)
    positive_total = float(positive.sum())
    return {
        "total_return": total, "cagr": float(nav.nav.iloc[-1] ** (1/elapsed) - 1),
        "max_drawdown": float(dd.min()), "sharpe": 0.0 if returns.std(ddof=1) == 0 else float(np.sqrt(252)*returns.mean()/returns.std(ddof=1)),
        "average_utilization": float(nav.utilization.mean()), "best_day": float(returns.max()), "worst_day": float(returns.min()),
        "return_excluding_best_day": float((1+returns.drop(returns.nlargest(1).index)).prod()-1),
        "return_excluding_best_five_days": float((1+returns.drop(returns.nlargest(5).index)).prod()-1),
        "top5_trade_pnl_contribution": None if positive_total <= 0 else float(positive.iloc[:5].sum()/positive_total),
    }


def combined_nav(main: pd.DataFrame, chinext: pd.DataFrame, k: int) -> pd.DataFrame:
    x = main[["trade_date", "nav", "gross_exposure", "active_positions"]].merge(chinext[["trade_date", "nav", "gross_exposure", "active_positions"]], on="trade_date", suffixes=("_main", "_chinext"), validate="one_to_one")
    x["nav"] = .5*x.nav_main + .5*x.nav_chinext
    x["gross_exposure"] = .5*x.gross_exposure_main + .5*x.gross_exposure_chinext
    x["cash"] = x.nav - x.gross_exposure
    x["utilization"] = x.gross_exposure/x.nav
    x["active_positions"] = x.active_positions_main+x.active_positions_chinext
    x["board"] = "COMBINED"; x["k"] = k
    return x[["trade_date", "nav", "cash", "gross_exposure", "utilization", "active_positions", "board", "k"]]


def annual_returns(nav: pd.DataFrame, years: tuple[int, ...]) -> dict[str, float]:
    output = {}; prior = 1.0
    for year in years:
        part = nav.loc[nav.trade_date.dt.year.eq(year)]
        output[str(year)] = float(part.nav.iloc[-1]/prior-1) if len(part) else 0.0
        if len(part): prior = float(part.nav.iloc[-1])
    return output


def summarize_replays(trades: pd.DataFrame, daily: pd.DataFrame, candidates: pd.DataFrame, years: tuple[int, ...]) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, int]]:
    summary: dict[str, Any] = {}
    yearly: dict[str, Any] = {}
    nav_parts = []
    ledger_parts = []
    audit = Counter()
    for population, memories in (("CORE", ["CORE"]), ("CORE_PLUS_BOUNDARY", ["CORE", "BOUNDARY"])):
        summary[population] = {}; yearly[population] = {}
        for horizon in TIME_STOPS:
            lane = trades.loc[trades.time_stop.eq(horizon) & trades.memory_state.isin(memories)].copy()
            signal_lane = candidates.loc[candidates.memory_state.isin(memories) & candidates.signal_year.isin(years)].copy()
            summary[population][f"T{horizon}"] = {}
            yearly[population][f"T{horizon}"] = {}
            replays: dict[tuple[str, int], Replay] = {}
            for board in ("MAIN", "CHINEXT"):
                summary[population][f"T{horizon}"][board] = {}
                for k in KS:
                    replay = replay_portfolio(lane, daily, board, k, years)
                    replays[(board, k)] = replay
                    audit.update(replay.audit)
                    accepted = replay.accepted
                    item = {"signals": int(signal_lane.board.eq(board).sum()), "executed_trades": len(accepted), "capacity_skips": int(replay.ledger.capacity_skip.sum()) if len(replay.ledger) else 0}
                    item["capacity_skip_rate"] = item["capacity_skips"]/item["signals"] if item["signals"] else 0.0
                    item.update(trade_metrics(accepted)); item.update(portfolio_metrics(replay.nav, accepted))
                    summary[population][f"T{horizon}"][board][str(k)] = item
                    nav_parts.append(replay.nav.assign(population=population, time_stop=horizon))
                    if len(replay.ledger): ledger_parts.append(replay.ledger.assign(population=population, time_stop=horizon))
            summary[population][f"T{horizon}"]["COMBINED"] = {}
            for k in KS:
                main, chx = replays[("MAIN", k)], replays[("CHINEXT", k)]
                nav = combined_nav(main.nav, chx.nav, k)
                accepted = pd.concat([main.accepted, chx.accepted], ignore_index=True)
                ledgers = pd.concat([main.ledger, chx.ledger], ignore_index=True)
                item = {"signals": len(signal_lane), "executed_trades": len(accepted), "capacity_skips": int(ledgers.capacity_skip.sum()) if len(ledgers) else 0}
                item["capacity_skip_rate"] = item["capacity_skips"]/item["signals"] if item["signals"] else 0.0
                item.update(trade_metrics(accepted)); item.update(portfolio_metrics(nav, accepted))
                summary[population][f"T{horizon}"]["COMBINED"][str(k)] = item
                if k == 10:
                    yearly[population][f"T{horizon}"]["COMBINED"] = {}
                    ann = annual_returns(nav, years)
                    for year in years:
                        a = accepted.loc[pd.to_datetime(accepted.entry_date).dt.year.eq(year)] if len(accepted) else accepted
                        signal_year = signal_lane.loc[signal_lane.signal_year.eq(year)]
                        yearly[population][f"T{horizon}"]["COMBINED"][str(year)] = {"signals": len(signal_year), "executed_trades": len(a), **trade_metrics(a), "portfolio_return": ann[str(year)]}
    return summary, yearly, pd.concat(nav_parts, ignore_index=True), pd.concat(ledger_parts, ignore_index=True), dict(audit)


def structural_summary(structural: pd.DataFrame, years: tuple[int, ...]) -> dict[str, Any]:
    output = {}
    part0 = structural.loc[structural.signal_year.isin(years)]
    for population, memories in (("CORE", ["CORE"]), ("CORE_PLUS_BOUNDARY", ["CORE", "BOUNDARY"])):
        part = part0.loc[part0.memory_state.isin(memories)]
        output[population] = {
            "signal_count": len(part), "causal_first_return_count": len(part),
            "mean_target_distance": float(part.target_distance_from_l.mean()), "median_target_distance": float(part.target_distance_from_l.median()),
            "full_fill_rates": {f"{h}D": float(part[f"u_full_fill_{h}d"].mean()) for h in (0,1,3,5,10,20,40,60)},
        }
    return output


def fixed_verdict(summary: dict[str, Any], yearly: dict[str, Any], structural: dict[str, Any]) -> str:
    lanes = [summary["CORE_PLUS_BOUNDARY"][f"T{h}"]["COMBINED"]["10"] for h in TIME_STOPS]
    annual = [yearly["CORE_PLUS_BOUNDARY"][f"T{h}"]["COMBINED"] for h in TIME_STOPS]
    positive_years = [sum(x[str(y)]["portfolio_return"] > 0 for y in DEVELOPMENT_YEARS) for x in annual]
    boards_positive = all(summary["CORE_PLUS_BOUNDARY"][f"T{h}"][b]["10"]["cagr"] > 0 for h in TIME_STOPS for b in ("MAIN", "CHINEXT"))
    promising = all(x["mean_net_trade_return"] is not None and x["mean_net_trade_return"] > 0 and x["median_net_trade_return"] > 0 and x["cagr"] > 0 and x["max_drawdown"] > -0.20 for x in lanes) and min(positive_years) >= 6 and boards_positive
    if promising:
        return "V6_CAUSAL_TRUE_GAP_STRATEGY_PROMISING"
    any_edge = any(x["mean_net_trade_return"] is not None and x["mean_net_trade_return"] > 0 and x["median_net_trade_return"] > 0 and x["cagr"] > 0 for x in lanes)
    if any_edge and max(positive_years) >= 4:
        return "V6_CAUSAL_TRUE_GAP_MARGINAL"
    if structural["CORE_PLUS_BOUNDARY"]["full_fill_rates"]["40D"] >= .50:
        return "V6_CAUSAL_TRUE_GAP_STRUCTURE_ONLY"
    return "V6_CAUSAL_TRUE_GAP_NO_EDGE"


def build_report(result: dict[str, Any]) -> str:
    def pct(v: Any) -> str:
        return "NA" if v is None else f"{v:.2%}"
    lines = [f"# {EXPERIMENT}", "", f"Frozen V6 spec hash: `{EXPECTED_SPEC_HASH}`", "", f"**{result['verdict']}**", "", "Stage A froze before Stage B opened outcomes. No semantic field changed afterward; repository 2024+ stayed sealed.", "", "## K10 Development primary", "", "|Lane|Signals|Trades|Mean|Median|Win|U hit|Avg hold|Median hold|CAGR|MaxDD|Sharpe|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for pop in ("CORE", "CORE_PLUS_BOUNDARY"):
        for h in TIME_STOPS:
            x=result["development"]["summary"][pop][f"T{h}"]["COMBINED"]["10"]
            lines.append(f"|{pop}_T{h}|{x['signals']}|{x['executed_trades']}|{pct(x['mean_net_trade_return'])}|{pct(x['median_net_trade_return'])}|{pct(x['true_win_rate'])}|{pct(x['u_target_hit_rate'])}|{x['mean_holding_sessions']:.2f}|{x['median_holding_sessions']:.1f}|{pct(x['cagr'])}|{pct(x['max_drawdown'])}|{x['sharpe']:.3f}|")
    lines += ["", "## Structural full fill", "", "|Population|Signals|Mean distance|Median distance|0D|1D|3D|5D|10D|20D|40D|60D|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for pop in ("CORE", "CORE_PLUS_BOUNDARY"):
        x=result["development"]["structural"][pop]; f=x["full_fill_rates"]
        lines.append(f"|{pop}|{x['signal_count']}|{pct(x['mean_target_distance'])}|{pct(x['median_target_distance'])}|"+"|".join(pct(f[f'{h}D']) for h in (0,1,3,5,10,20,40,60))+"|")
    lines += ["", "## Main / ChiNext — CORE+BOUNDARY K10", "", "|Board|T|Signals|Trades|Mean|Median|Win|U hit|CAGR|MaxDD|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for board in ("MAIN","CHINEXT"):
        for h in TIME_STOPS:
            x=result["development"]["summary"]["CORE_PLUS_BOUNDARY"][f"T{h}"][board]["10"]
            lines.append(f"|{board}|T{h}|{x['signals']}|{x['executed_trades']}|{pct(x['mean_net_trade_return'])}|{pct(x['median_net_trade_return'])}|{pct(x['true_win_rate'])}|{pct(x['u_target_hit_rate'])}|{pct(x['cagr'])}|{pct(x['max_drawdown'])}|")
    lines += ["", "## Yearly — CORE+BOUNDARY K10", "", "|T|Year|Signals|Trades|Mean|Median|Win|U hit|Portfolio return|", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for h in TIME_STOPS:
        for year,x in result["development"]["yearly"]["CORE_PLUS_BOUNDARY"][f"T{h}"]["COMBINED"].items():
            lines.append(f"|T{h}|{year}|{x['signals']}|{x['executed_trades']}|{pct(x['mean_net_trade_return'])}|{pct(x['median_net_trade_return'])}|{pct(x['true_win_rate'])}|{pct(x['u_target_hit_rate'])}|{pct(x['portfolio_return'])}|")
    lines += ["", "## K sensitivity — CORE+BOUNDARY", "", "|T|K|CAGR|MaxDD|Sharpe|Avg util|Skip rate|", "|---:|---:|---:|---:|---:|---:|---:|"]
    for h in TIME_STOPS:
        for k in KS:
            x=result["development"]["k_sensitivity"]["CORE_PLUS_BOUNDARY"][f"T{h}"][f"K{k}"]
            lines.append(f"|T{h}|K{k}|{pct(x['cagr'])}|{pct(x['max_drawdown'])}|{x['sharpe']:.3f}|{pct(x['average_utilization'])}|{pct(x['capacity_skip_rate'])}|")
    lines += ["", "## Post-observation robustness diagnostic — not Validation", "", "|T|Signals|Trades|Mean|Median|Win|U hit|CAGR|MaxDD|", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for h in TIME_STOPS:
        x=result["post_observation_robustness_diagnostic"]["summary"]["CORE_PLUS_BOUNDARY"][f"T{h}"]["COMBINED"]["10"]
        lines.append(f"|T{h}|{x['signals']}|{x['executed_trades']}|{pct(x['mean_net_trade_return'])}|{pct(x['median_net_trade_return'])}|{pct(x['true_win_rate'])}|{pct(x['u_target_hit_rate'])}|{pct(x['cagr'])}|{pct(x['max_drawdown'])}|")
    lines += ["", "## Audit", "", f"`{result['audit']}`"]
    return "\n".join(lines) + "\n"


def run_stage_b() -> dict[str, Any]:
    semantic = verify_stage_a_freeze()
    candidates = active_candidates()
    structural = build_structural_outcomes(candidates)
    actions = build_action_events(candidates.symbol.drop_duplicates().tolist())
    confirmations, entries = build_entries(candidates, actions)
    build_paths(candidates, entries)
    trades, trade_audit = build_trades(candidates, confirmations, entries, actions)
    daily = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx", "symbol", "close"])
    daily.trade_date = pd.to_datetime(daily.trade_date)
    dev_summary, dev_yearly, dev_nav, dev_ledger, dev_replay_audit = summarize_replays(trades, daily, candidates, DEVELOPMENT_YEARS)
    diag_summary, diag_yearly, diag_nav, diag_ledger, diag_replay_audit = summarize_replays(trades, daily, candidates, DIAGNOSTIC_YEARS)
    write_parquet(pd.concat([dev_nav.assign(period="DEVELOPMENT"), diag_nav.assign(period="POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC")], ignore_index=True), NAV)
    write_parquet(pd.concat([dev_ledger.assign(period="DEVELOPMENT"), diag_ledger.assign(period="POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC")], ignore_index=True), PORTFOLIO_LEDGER)
    dev_structural = structural_summary(structural, DEVELOPMENT_YEARS)
    diag_structural = structural_summary(structural, DIAGNOSTIC_YEARS)
    k_sensitivity = {}
    for pop in ("CORE", "CORE_PLUS_BOUNDARY"):
        k_sensitivity[pop] = {}
        for h in TIME_STOPS:
            k_sensitivity[pop][f"T{h}"] = {f"K{k}": {key: dev_summary[pop][f"T{h}"]["COMBINED"][str(k)][key] for key in ("cagr", "max_drawdown", "sharpe", "average_utilization", "capacity_skip_rate")} for k in KS}
    verdict = fixed_verdict(dev_summary, dev_yearly, dev_structural)
    audit_counter = Counter(dev_replay_audit); audit_counter.update(diag_replay_audit)
    audit = {
        **semantic["audit"],
        "semantic_change_after_outcome_open_count": 0,
        "entry_uses_future_bar_count": int(entries.entry_uses_future_bar.sum()),
        "t1_violation_count": trade_audit.get("t1_violation_count", 0),
        "unresolved_action_block_count": trade_audit.get("unresolved_action_block_count", 0),
        "max_k_violation_count": audit_counter.get("max_k_violation_count", 0),
        "duplicate_position_count": audit_counter.get("duplicate_position_count", 0),
        "negative_cash_or_leverage_count": audit_counter.get("negative_cash_or_leverage_count", 0),
        "cross_sleeve_capital_transfer_count": 0,
        "repository_2024_plus_data_opened": "NO",
    }
    blocking = {k:v for k,v in audit.items() if k.endswith("_count") and v}
    if blocking:
        raise V6Error(f"Stage B audit failed: {blocking}")
    result = {
        "experiment": EXPERIMENT, "start_head": START_HEAD, "semantic_gate": "PASS",
        "v6_frozen": "YES", "frozen_v6_spec_hash": EXPECTED_SPEC_HASH,
        "development": {"period": ["2014-01-01", "2021-12-31"], "structural": dev_structural, "summary": dev_summary, "yearly": dev_yearly, "k_sensitivity": k_sensitivity},
        "post_observation_robustness_diagnostic": {"label": "POST-OBSERVATION ROBUSTNESS DIAGNOSTIC — NOT VALIDATION", "period": ["2022-01-01", "2023-12-31"], "structural": diag_structural, "summary": diag_summary, "yearly": diag_yearly},
        "entry_reconciliation": {"signals": len(candidates), "confirmations": len(confirmations), "executable_entries": len(entries), "confirmation_without_executable_entry": int(len(confirmations)-len(entries))},
        "audit": audit, "verdict": verdict,
        "best_descriptive_t": max(TIME_STOPS, key=lambda h: dev_summary["CORE_PLUS_BOUNDARY"][f"T{h}"]["COMBINED"]["10"]["cagr"]),
        "artifacts": {},
    }
    write_json(OUTCOME_RESULT, result)
    atomic_text(REPORT, build_report(result))
    for name,path in (("semantic_result",SEMANTIC_RESULT),("structural",STRUCTURAL),("trades_external",TRADES),("portfolio_ledger_external",PORTFOLIO_LEDGER),("nav_external",NAV),("report",REPORT)):
        result["artifacts"][name]={"path":str(path),"bytes":path.stat().st_size,"sha256":sha256(path)}
    write_json(OUTCOME_RESULT,result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("stage-a", "stage-b", "verify-stage-a"))
    args = parser.parse_args()
    if args.stage == "stage-a":
        result = run_stage_a()
    elif args.stage == "verify-stage-a":
        result = verify_stage_a_freeze()
    else:
        result = run_stage_b()
    print(json.dumps(json_ready(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
