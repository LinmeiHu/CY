#!/usr/bin/env python3
# ruff: noqa: E402,E501
"""Build the outcome-blind collapse-first 20-chart semantic pilot V3."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_pattern_fidelity_audit_v1 as v1,
)

OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-DEFINING-GAP-ZONE-HIGH-PRECISION-PILOT-V3"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "6b8c946efa5d1cd8f99103180859d43fabff28583d73a794632b9faeb4c18b16"
START_HEAD = "d331b039c8fd1c60b937286b7631a192ed8164df"

EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_defining_gap_zone_high_precision_pilot_v3")
VALID_DAILY = EXTERNAL / "valid_daily_2014_2021.parquet"
COLLAPSE_SEEDS = EXTERNAL / "collapse_seeds.parquet"
COLLAPSE_EPISODES = EXTERNAL / "collapse_episodes.parquet"
EPISODE_PRIMITIVES = EXTERNAL / "episode_strict_gap_primitives.parquet"
MEANINGFUL_PRIMITIVES = EXTERNAL / "meaningful_collapse_gap_primitives.parquet"
PAIR_RECOVERY = EXTERNAL / "meaningful_primitive_pair_recovery.parquet"
ZONE_STACKS = EXTERNAL / "meaningful_zone_stacks.parquet"
LIFECYCLE_ROWS = EXTERNAL / "zone_lifecycle_rows.parquet"
LIFECYCLE_SUMMARY = EXTERNAL / "zone_lifecycle_summary.parquet"
EXACT_REENTRY = EXTERNAL / "exact_reentry.parquet"
BLIND_DIR = EXTERNAL / "blind_charts"
DIAGNOSTIC_DIR = EXTERNAL / "diagnostic_charts"
CHART_SAMPLE_IDENTITY = EXTERNAL / "chart_sample_identity.txt"
CHART_RENDER_VERSION = "v3.1-primitive-lineage"

CANDIDATES = OS_ROOT / f"artifacts/{EXPERIMENT}_candidates.parquet"
MAPPING = OS_ROOT / f"artifacts/{EXPERIMENT}_mapping.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
REVIEW_CSV = OS_ROOT / f"reports/{EXPERIMENT}_review.csv"
REVIEW_INSTRUCTIONS = OS_ROOT / f"reports/{EXPERIMENT}_REVIEW_INSTRUCTIONS.md"

DAILY = v1.DAILY_COMPACT
STRICT_PRIMITIVES = v1.PRIMITIVES_FULL


class PilotError(RuntimeError):
    """Fail closed when a V3 semantic or governance invariant fails."""


def validate_inputs() -> dict[str, Any]:
    if v1.sha256_file(SPEC) != EXPECTED_SPEC_SHA256:
        raise PilotError("frozen V3 spec hash mismatch")
    source = v1.validate_inputs()
    if not DAILY.is_file():
        v1.build_daily_compact()
    if not STRICT_PRIMITIVES.is_file():
        v1.build_primitives()
    return {
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "source_contract": source,
        "v2_human_labels_read": False,
        "outcome_fields_read": False,
    }


def build_collapse_episodes() -> pd.DataFrame:
    """Detect broad peak-to-trough collapse episodes before reading gap primitives."""
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    if COLLAPSE_EPISODES.is_file():
        frame = pd.read_parquet(COLLAPSE_EPISODES)
        for column in [c for c in frame.columns if c.endswith("_date")]:
            frame[column] = pd.to_datetime(frame[column])
        return frame
    con = v1.connection()
    con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    valid_query = f"""
      SELECT *,row_number() OVER(PARTITION BY symbol ORDER BY trade_date) AS valid_seq,
        lag(coord_close,1) OVER(PARTITION BY symbol ORDER BY trade_date) AS valid_lag1_close,
        lag(coord_close,2) OVER(PARTITION BY symbol ORDER BY trade_date) AS valid_lag2_close
      FROM read_parquet('{DAILY}')
      WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31'
        AND history_valid AND current_valid
    """
    con.execute(f"COPY ({valid_query}) TO '{VALID_DAILY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    seed_query = f"""
    WITH breach_seed AS (
      SELECT symbol,prior250_peak_date AS peak_date,prior250_peak_high AS peak_coord_high,
        prior250_peak_invalid_cum AS peak_invalid_step_cum,
        min(trade_date) AS first_breach_date
      FROM read_parquet('{VALID_DAILY}')
      WHERE prior250_peak_date IS NOT NULL
        AND trade_date>prior250_peak_date
        AND invalid_step_cum=prior250_peak_invalid_cum
        AND 1-coord_low/prior250_peak_high>=0.30
      GROUP BY symbol,prior250_peak_date,prior250_peak_high,prior250_peak_invalid_cum
    ), seed AS (
      SELECT b.*,p.valid_seq AS peak_valid_seq,p.cal_idx AS peak_cal_idx,
        p.coord_high/p.low60-1 AS max_runup_from_60_low,
        p.coord_high/p.low120-1 AS max_runup_from_120_low,
        p.ret20 AS return20_into_peak,p.ret60 AS return60_into_peak,
        p.board_ret60_percentile AS board_relative_return_percentile,
        p.large_up_days120 AS number_large_up_days,p.limit_up_days120 AS number_limit_up_sessions,
        p.cal_idx-p.low120_idx AS main_rise_duration,
        (p.coord_high/p.low120-1)/nullif(p.cal_idx-p.low120_idx,0) AS runup_speed,
        p.max_drawdown_main_rise AS max_drawdown_during_rise,
        p.sleeve AS board,p.is_st,p.industry,
        fb.valid_seq AS first_breach_valid_seq,fb.cal_idx AS first_breach_cal_idx
      FROM breach_seed b
      JOIN read_parquet('{VALID_DAILY}') p ON p.symbol=b.symbol AND p.trade_date=b.peak_date
      JOIN read_parquet('{VALID_DAILY}') fb ON fb.symbol=b.symbol AND fb.trade_date=b.first_breach_date
      WHERE (
          p.coord_high/p.low60-1>=0.50
          OR p.coord_high/p.low120-1>=0.70
        )
        AND (
          p.board_ret60_percentile>=0.90
          OR p.ret20>=0.30
          OR p.large_up_days120>=2
          OR p.limit_up_days120>=2
        )
    ) SELECT * FROM seed ORDER BY symbol,peak_date
    """
    con.execute(f"COPY ({seed_query}) TO '{COLLAPSE_SEEDS}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    query = f"""
    WITH recovery_candidates AS (
      SELECT s.symbol,s.peak_date,d.trade_date AS recovery_date,d.valid_seq AS recovery_valid_seq
      FROM read_parquet('{COLLAPSE_SEEDS}') s
      JOIN read_parquet('{VALID_DAILY}') d ON d.symbol=s.symbol
        AND d.valid_seq BETWEEN s.first_breach_valid_seq+2 AND s.peak_valid_seq+250
        AND d.invalid_step_cum=s.peak_invalid_step_cum
      WHERE d.coord_close>=0.90*s.peak_coord_high
        AND d.valid_lag1_close>=0.90*s.peak_coord_high
        AND d.valid_lag2_close>=0.90*s.peak_coord_high
    ), recovery AS (
      SELECT symbol,peak_date,min(recovery_valid_seq) AS recovery_valid_seq,
        arg_min(recovery_date,recovery_valid_seq) AS recovery_date
      FROM recovery_candidates GROUP BY symbol,peak_date
    ), bounded AS (
      SELECT s.*,r.recovery_date,r.recovery_valid_seq,
        least(s.peak_valid_seq+250,coalesce(r.recovery_valid_seq,s.peak_valid_seq+250)) AS episode_end_valid_seq
      FROM read_parquet('{COLLAPSE_SEEDS}') s LEFT JOIN recovery r USING(symbol,peak_date)
    ), trough AS (
      SELECT b.symbol,b.peak_date,
        min(d.coord_low) AS postcollapse_low_coord,
        arg_min(d.trade_date,d.coord_low) AS postcollapse_low_date,
        arg_min(d.valid_seq,d.coord_low) AS postcollapse_low_valid_seq,
        arg_min(d.cal_idx,d.coord_low) AS postcollapse_low_cal_idx,
        max(d.trade_date) AS episode_end_date
      FROM bounded b JOIN read_parquet('{VALID_DAILY}') d
        ON d.symbol=b.symbol
       AND d.valid_seq BETWEEN b.first_breach_valid_seq AND b.episode_end_valid_seq
       AND d.invalid_step_cum=b.peak_invalid_step_cum
      GROUP BY b.symbol,b.peak_date
    )
    SELECT concat(b.symbol,'|',strftime(b.peak_date,'%Y-%m-%d')) AS collapse_episode_id,
      b.*,t.* EXCLUDE(symbol,peak_date),
      1-t.postcollapse_low_coord/b.peak_coord_high AS peak_to_low_decline
    FROM bounded b JOIN trough t USING(symbol,peak_date)
    WHERE t.postcollapse_low_date>b.peak_date
      AND 1-t.postcollapse_low_coord/b.peak_coord_high>=0.30
    ORDER BY b.symbol,b.peak_date
    """
    con.execute(f"COPY ({query}) TO '{COLLAPSE_EPISODES}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    frame = pd.read_parquet(COLLAPSE_EPISODES)
    for column in [c for c in frame.columns if c.endswith("_date")]:
        frame[column] = pd.to_datetime(frame[column])
    return frame


def build_episode_primitives() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign strict primitives only after collapse episodes exist, then classify significance."""
    if EPISODE_PRIMITIVES.is_file() and MEANINGFUL_PRIMITIVES.is_file():
        all_primitives = pd.read_parquet(EPISODE_PRIMITIVES)
        meaningful = pd.read_parquet(MEANINGFUL_PRIMITIVES)
        for frame in (all_primitives, meaningful):
            for column in [c for c in frame.columns if c.endswith("_date")]:
                frame[column] = pd.to_datetime(frame[column])
        return all_primitives, meaningful
    con = v1.connection()
    query = f"""
    WITH assigned AS (
      SELECT e.*,g.* EXCLUDE(symbol,board,is_st,industry,invalid_step_cum,peak_date,peak_coord_high,
        return20_into_peak,return60_into_peak,board_relative_return_percentile,number_large_up_days,
        number_limit_up_sessions,main_rise_duration,rise_speed,maximum_drawdown_during_main_rise),
        row_number() OVER(
          PARTITION BY g.gap_primitive_id ORDER BY e.peak_date DESC,e.postcollapse_low_date
        ) AS episode_choice
      FROM read_parquet('{COLLAPSE_EPISODES}') e
      JOIN read_parquet('{STRICT_PRIMITIVES}') g
        ON g.symbol=e.symbol
       AND g.gap_date>e.peak_date
       AND g.gap_date<=e.postcollapse_low_date
       AND g.invalid_step_cum=e.peak_invalid_step_cum
    )
    SELECT * EXCLUDE(episode_choice),
      1-lower_coord/peak_coord_high AS peak_to_zone_decline,
      1-postcollapse_low_coord/peak_coord_high AS peak_to_low_decline_v2,
      1-postcollapse_low_coord/lower_coord AS zone_to_low_decline,
      (upper_coord-lower_coord)/nullif(peak_coord_high-postcollapse_low_coord,0) AS width_share_of_peak_to_low_decline,
      (
        width_pct_vs_prev_close>=0.025
        OR (upper_coord-lower_coord)/nullif(peak_coord_high-postcollapse_low_coord,0)>=0.08
      ) AS significance_pass,
      postcollapse_low_coord<=lower_coord*0.875 AS post_zone_depth_pass
    FROM assigned WHERE episode_choice=1
    ORDER BY collapse_episode_id,gap_date,gap_primitive_id
    """
    con.execute(f"COPY ({query}) TO '{EPISODE_PRIMITIVES}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"""COPY (
      SELECT * FROM read_parquet('{EPISODE_PRIMITIVES}')
      WHERE significance_pass AND post_zone_depth_pass
      ORDER BY collapse_episode_id,gap_date,gap_primitive_id
    ) TO '{MEANINGFUL_PRIMITIVES}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()
    all_primitives = pd.read_parquet(EPISODE_PRIMITIVES)
    meaningful = pd.read_parquet(MEANINGFUL_PRIMITIVES)
    for frame in (all_primitives, meaningful):
        for column in [c for c in frame.columns if c.endswith("_date")]:
            frame[column] = pd.to_datetime(frame[column])
    return all_primitives, meaningful


def group_meaningful_zones(meaningful: pd.DataFrame, all_primitives: pd.DataFrame) -> pd.DataFrame:
    """Group retained primitives without representing traded vertical distance as a gap."""
    if ZONE_STACKS.is_file():
        stacks = pd.read_parquet(ZONE_STACKS)
        for column in [c for c in stacks.columns if c.endswith("_date")]:
            stacks[column] = pd.to_datetime(stacks[column])
        # Early resumable shards used ``|`` both inside a primitive ID and as
        # the list delimiter. Reconstruct the IDs from their separately stored
        # dates so every primitive remains unambiguous in compact lineage.
        stacks["meaningful_primitive_ids"] = stacks.apply(
            lambda row: ";".join(
                f"{row.symbol}|{date}" for date in str(row.meaningful_primitive_dates).split("|")
            ),
            axis=1,
        )
        stacks["all_primitive_ids"] = stacks.apply(
            lambda row: ";".join(
                f"{row.symbol}|{date}" for date in str(row.all_primitive_dates).split("|")
            ),
            axis=1,
        )
        v1.write_parquet(stacks, ZONE_STACKS)
        return stacks
    work = meaningful.sort_values(["collapse_episode_id", "gap_cal_idx", "gap_primitive_id"], kind="mergesort").copy()
    work["previous_primitive_id"] = work.groupby("collapse_episode_id", sort=False).gap_primitive_id.shift()
    work["previous_gap_cal_idx"] = work.groupby("collapse_episode_id", sort=False).gap_cal_idx.shift()
    work["previous_upper_coord"] = work.groupby("collapse_episode_id", sort=False).upper_coord.shift()
    pairs = work.loc[work.previous_primitive_id.notna(), [
        "gap_primitive_id", "previous_primitive_id", "symbol", "previous_gap_cal_idx", "gap_cal_idx",
        "previous_upper_coord", "peak_invalid_step_cum",
    ]].copy()
    pair_path = EXTERNAL / "meaningful_primitive_pairs.parquet"
    v1.write_parquet(pairs, pair_path)
    if len(pairs):
        con = v1.connection()
        query = f"""
        WITH path0 AS (
          SELECT p.*,d.cal_idx,d.coord_close,
            row_number() OVER(PARTITION BY p.gap_primitive_id ORDER BY d.cal_idx) AS rn,
            d.coord_close>=p.previous_upper_coord AS recovered_close
          FROM read_parquet('{pair_path}') p
          JOIN read_parquet('{DAILY}') d
            ON d.symbol=p.symbol
           AND d.cal_idx>p.previous_gap_cal_idx AND d.cal_idx<p.gap_cal_idx
           AND d.invalid_step_cum=p.peak_invalid_step_cum
           AND d.history_valid AND d.current_valid
        ), path1 AS (
          SELECT *,rn-coalesce(max(rn) FILTER(WHERE NOT recovered_close) OVER(
            PARTITION BY gap_primitive_id ORDER BY rn ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ),0) AS recovered_run
          FROM path0
        )
        SELECT p.gap_primitive_id,
          coalesce(max(path1.recovered_run),0)>=3 AS durable_recovery_between
        FROM read_parquet('{pair_path}') p LEFT JOIN path1 USING(gap_primitive_id)
        GROUP BY p.gap_primitive_id ORDER BY p.gap_primitive_id
        """
        recovery = con.execute(query).fetchdf()
        con.close()
    else:
        recovery = pd.DataFrame(columns=["gap_primitive_id", "durable_recovery_between"])
    v1.write_parquet(recovery, PAIR_RECOVERY)
    work = work.merge(recovery, on="gap_primitive_id", how="left", validate="one_to_one")
    work["durable_recovery_between"] = work.durable_recovery_between.astype("boolean").fillna(False)
    new_stack = (
        work.previous_primitive_id.isna()
        | work.gap_cal_idx.sub(work.previous_gap_cal_idx).gt(15)
        | work.durable_recovery_between
    )
    work["stack_sequence"] = new_stack.groupby(work.collapse_episode_id, sort=False).cumsum().astype(int)
    work["zone_stack_id"] = work.collapse_episode_id+"|Z"+work.stack_sequence.astype(str).str.zfill(2)

    rows: list[dict[str, Any]] = []
    episode_all = {key: part.sort_values(["gap_date", "gap_primitive_id"], kind="mergesort") for key, part in all_primitives.groupby("collapse_episode_id", sort=False)}
    for stack_id, part in work.groupby("zone_stack_id", sort=False):
        ordered_time = part.sort_values(["gap_date", "gap_primitive_id"], kind="mergesort")
        ordered_price = part.sort_values(["lower_coord", "gap_date", "gap_primitive_id"], kind="mergesort")
        target = ordered_price.iloc[0]
        all_part = episode_all[target.collapse_episode_id]
        sum_width = float((part.upper_coord-part.lower_coord).sum())
        stack_lower = float(part.lower_coord.min())
        stack_upper = float(part.upper_coord.max())
        rows.append({
            "zone_stack_id": stack_id,
            "collapse_episode_id": target.collapse_episode_id,
            "symbol": target.symbol,
            "board": target.board,
            "is_st": bool(target.is_st),
            "industry": target.industry,
            "peak_date": target.peak_date,
            "peak_coord_high": target.peak_coord_high,
            "peak_invalid_step_cum": target.peak_invalid_step_cum,
            "postcollapse_low_date": target.postcollapse_low_date,
            "postcollapse_low_coord": target.postcollapse_low_coord,
            "postcollapse_low_cal_idx": target.postcollapse_low_cal_idx,
            "peak_to_low_decline": target.peak_to_low_decline_v2,
            "max_runup_from_60_low": target.max_runup_from_60_low,
            "max_runup_from_120_low": target.max_runup_from_120_low,
            "return20_into_peak": target.return20_into_peak,
            "return60_into_peak": target.return60_into_peak,
            "board_relative_return_percentile": target.board_relative_return_percentile,
            "number_large_up_days": target.number_large_up_days,
            "number_limit_up_sessions": target.number_limit_up_sessions,
            "main_rise_duration": target.main_rise_duration,
            "runup_speed": target.runup_speed,
            "maximum_drawdown_during_rise": target.max_drawdown_during_rise,
            "target_primitive_id": target.gap_primitive_id,
            "zone_lower_boundary": target.lower_coord,
            "zone_upper_boundary": target.upper_coord,
            "zone_formation_date": ordered_time.gap_date.max(),
            "zone_formation_cal_idx": int(ordered_time.gap_cal_idx.max()),
            "sum_strict_gap_width": sum_width,
            "stack_lower_boundary": stack_lower,
            "stack_upper_boundary": stack_upper,
            "number_of_layers": len(part),
            "vertical_traded_distance_between_layers": max(0.0, stack_upper-stack_lower-sum_width),
            "peak_to_zone_decline": 1-target.lower_coord/target.peak_coord_high,
            "zone_to_low_decline": 1-target.postcollapse_low_coord/target.lower_coord,
            "meaningful_primitive_ids": ";".join(ordered_time.gap_primitive_id),
            "meaningful_primitive_dates": "|".join(ordered_time.gap_date.dt.strftime("%Y-%m-%d")),
            "meaningful_primitive_lowers": "|".join(f"{value:.12g}" for value in ordered_time.lower_coord),
            "meaningful_primitive_uppers": "|".join(f"{value:.12g}" for value in ordered_time.upper_coord),
            "meaningful_primitive_width_pcts": "|".join(f"{value:.8g}" for value in ordered_time.width_pct_vs_prev_close),
            "meaningful_primitive_collapse_shares": "|".join(f"{value:.8g}" for value in ordered_time.width_share_of_peak_to_low_decline),
            "all_primitive_ids": ";".join(all_part.gap_primitive_id),
            "all_primitive_dates": "|".join(all_part.gap_date.dt.strftime("%Y-%m-%d")),
            "all_primitive_lowers": "|".join(f"{value:.12g}" for value in all_part.lower_coord),
            "all_primitive_uppers": "|".join(f"{value:.12g}" for value in all_part.upper_coord),
            "all_primitive_meaningful": "|".join("1" if value else "0" for value in (all_part.significance_pass & all_part.post_zone_depth_pass)),
        })
    stacks = pd.DataFrame(rows)
    v1.write_parquet(stacks, ZONE_STACKS)
    return stacks


def lifecycle_query() -> str:
    return f"""
    WITH path0 AS (
      SELECT s.*,d.trade_date AS state_date,d.cal_idx AS state_cal_idx,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,d.coordinate_factor,
        row_number() OVER(PARTITION BY s.zone_stack_id ORDER BY d.cal_idx) AS path_rn,
        d.coord_high<s.zone_lower_boundary AS fully_below,
        d.coord_high>=s.zone_lower_boundary AS partial_entry,
        d.coord_high>=s.zone_upper_boundary AS full_fill,
        median(d.coord_close) OVER(
          PARTITION BY s.zone_stack_id ORDER BY d.cal_idx ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS rolling_median_close5,
        count(*) OVER(
          PARTITION BY s.zone_stack_id ORDER BY d.cal_idx ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS rolling_count5
      FROM read_parquet('{ZONE_STACKS}') s
      JOIN read_parquet('{DAILY}') d
        ON d.symbol=s.symbol
       AND d.cal_idx>s.zone_formation_cal_idx
       AND d.trade_date<=DATE '2021-12-31'
       AND d.invalid_step_cum=s.peak_invalid_step_cum
       AND d.history_valid AND d.current_valid
    ), path1 AS (
      SELECT *,path_rn-coalesce(max(path_rn) FILTER(WHERE NOT fully_below) OVER(
        PARTITION BY zone_stack_id ORDER BY path_rn ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ),0) AS current_fully_below_run
      FROM path0
    ), path2 AS (
      SELECT *,
        coalesce(max(current_fully_below_run) OVER(
          PARTITION BY zone_stack_id ORDER BY path_rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ),0) AS prior_max_fully_below_run,
        count(*) FILTER(WHERE partial_entry) OVER(
          PARTITION BY zone_stack_id ORDER BY path_rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_partial_entry_count,
        count(*) FILTER(WHERE full_fill) OVER(
          PARTITION BY zone_stack_id ORDER BY path_rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_full_fill_count,
        min(coord_low) OVER(
          PARTITION BY zone_stack_id ORDER BY path_rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_post_zone_low,
        min(rolling_median_close5) FILTER(WHERE rolling_count5=5) OVER(
          PARTITION BY zone_stack_id ORDER BY path_rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS prior_min_rolling_median_close5,
        count(*) FILTER(WHERE state_date>postcollapse_low_date) OVER(
          PARTITION BY zone_stack_id ORDER BY path_rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS base_duration
      FROM path1
    ), assessed AS (
      SELECT *,
        path_rn-1>=10 AS persistence_pass,
        prior_max_fully_below_run>=5 AS fully_below_pass,
        prior_post_zone_low<=zone_lower_boundary*0.875 AS post_zone_depth_pass,
        prior_min_rolling_median_close5<=zone_lower_boundary*0.925 AS lower_regime_pass,
        base_duration>=5 AS base_pass,
        prior_partial_entry_count=0 AS no_prior_partial_entry_pass,
        prior_full_fill_count=0 AS unresolved_pass,
        coord_open<zone_lower_boundary AND coord_high>=zone_lower_boundary AS current_upward_entry
      FROM path2
    ), accepted AS (
      SELECT *,row_number() OVER(PARTITION BY zone_stack_id ORDER BY state_date) AS candidate_order
      FROM assessed
      WHERE persistence_pass AND fully_below_pass AND post_zone_depth_pass
        AND lower_regime_pass AND base_pass AND no_prior_partial_entry_pass
        AND unresolved_pass AND current_upward_entry
    )
    SELECT * FROM accepted WHERE candidate_order=1 ORDER BY zone_stack_id
    """


def build_lifecycle(stacks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if LIFECYCLE_ROWS.is_file() and LIFECYCLE_SUMMARY.is_file():
        rows = pd.read_parquet(LIFECYCLE_ROWS)
        accepted = pd.read_parquet(LIFECYCLE_SUMMARY)
        for frame in (rows, accepted):
            for column in [c for c in frame.columns if c.endswith("_date") or c.endswith("_time")]:
                frame[column] = pd.to_datetime(frame[column])
        if len(accepted):
            accepted = add_base_descriptors(accepted)
        return rows, accepted
    con = v1.connection()
    # Preserve the complete assessed lifecycle to support deterministic rejection counts.
    full_query = lifecycle_query().replace(
        "), accepted AS (\n      SELECT *,row_number() OVER(PARTITION BY zone_stack_id ORDER BY state_date) AS candidate_order\n      FROM assessed\n      WHERE persistence_pass AND fully_below_pass AND post_zone_depth_pass\n        AND lower_regime_pass AND base_pass AND no_prior_partial_entry_pass\n        AND unresolved_pass AND current_upward_entry\n    )\n    SELECT * FROM accepted WHERE candidate_order=1 ORDER BY zone_stack_id",
        ") SELECT * FROM assessed ORDER BY zone_stack_id,state_date",
    )
    con.execute(f"COPY ({full_query}) TO '{LIFECYCLE_ROWS}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"COPY ({lifecycle_query()}) TO '{LIFECYCLE_SUMMARY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    rows = pd.read_parquet(LIFECYCLE_ROWS)
    accepted = pd.read_parquet(LIFECYCLE_SUMMARY)
    for frame in (rows, accepted):
        for column in [c for c in frame.columns if c.endswith("_date") or c.endswith("_time")]:
            frame[column] = pd.to_datetime(frame[column])
    if len(accepted):
        accepted = add_base_descriptors(accepted)
    return rows, accepted


def add_base_descriptors(candidates: pd.DataFrame) -> pd.DataFrame:
    path = EXTERNAL / "accepted_daily_candidates.parquet"
    v1.write_parquet(candidates, path)
    con = v1.connection()
    query = f"""
    WITH hist0 AS (
      SELECT c.zone_stack_id,d.trade_date,d.cal_idx,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
        min(d.coord_low) OVER(PARTITION BY c.zone_stack_id ORDER BY d.cal_idx ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_min_low
      FROM read_parquet('{path}') c JOIN read_parquet('{DAILY}') d
        ON d.symbol=c.symbol
       AND d.cal_idx<c.state_cal_idx
       AND d.cal_idx>=c.postcollapse_low_cal_idx
       AND d.invalid_step_cum=c.peak_invalid_step_cum
       AND d.history_valid AND d.current_valid
    ), hist AS (
      SELECT *,coord_low<coalesce(prior_min_low,1e300) AS new_low FROM hist0
    )
    SELECT c.zone_stack_id,
      max(h.coord_high) FILTER(WHERE h.cal_idx>=c.state_cal_idx-5)/nullif(min(h.coord_low) FILTER(WHERE h.cal_idx>=c.state_cal_idx-5),0)-1 AS base_range_5,
      max(h.coord_high) FILTER(WHERE h.cal_idx>=c.state_cal_idx-10)/nullif(min(h.coord_low) FILTER(WHERE h.cal_idx>=c.state_cal_idx-10),0)-1 AS base_range_10,
      regr_slope(h.coord_close,h.cal_idx) FILTER(WHERE h.cal_idx>=c.state_cal_idx-5) AS close_slope_5,
      regr_slope(h.coord_low,h.cal_idx) FILTER(WHERE h.cal_idx>=c.state_cal_idx-5) AS low_slope_5,
      median(h.turnover_fraction) FILTER(WHERE h.cal_idx>=c.state_cal_idx-5)/nullif(median(h.turnover_fraction) FILTER(WHERE h.cal_idx>=c.state_cal_idx-20),0) AS turnover_5_20,
      count(*) FILTER(WHERE h.cal_idx>=c.state_cal_idx-10 AND h.new_low) AS number_of_new_lows_10
    FROM read_parquet('{path}') c LEFT JOIN hist h USING(zone_stack_id)
    GROUP BY c.zone_stack_id ORDER BY c.zone_stack_id
    """
    descriptors = con.execute(query).fetchdf()
    con.close()
    return candidates.merge(descriptors, on="zone_stack_id", how="left", validate="one_to_one")


def build_exact_reentry(candidates: pd.DataFrame) -> pd.DataFrame:
    if EXACT_REENTRY.is_file():
        exact = pd.read_parquet(EXACT_REENTRY)
        exact["candidate_reentry_time"] = pd.to_datetime(exact.candidate_reentry_time)
        return exact
    pairs = candidates[["zone_stack_id", "symbol", "state_date", "zone_lower_boundary", "coordinate_factor"]].rename(columns={"state_date": "candidate_reentry_date"})
    pair_path = EXTERNAL / "exact_reentry_pairs.parquet"
    v1.write_parquet(pairs, pair_path)
    shards: list[Path] = []
    for year in v1.DEVELOPMENT_YEARS:
        shard = EXTERNAL / f"exact_reentry_{year}.parquet"
        shards.append(shard)
        con = v1.connection()
        query = f"""
        WITH pairs AS (
          SELECT *,zone_lower_boundary/coordinate_factor AS raw_threshold
          FROM read_parquet('{pair_path}') WHERE year(candidate_reentry_date)={year}
        ), bars AS (
          SELECT p.*,m.bar_end_time,m.open,m.high,m.low,
            count(*) OVER(PARTITION BY p.zone_stack_id) AS minute_count,
            count(DISTINCT m.bar_end_time) OVER(PARTITION BY p.zone_stack_id) AS distinct_minute_count
          FROM pairs p JOIN read_parquet('{v1.raw_path(year)}') m
            ON m.qmt_code=p.symbol AND m.trade_date=p.candidate_reentry_date
          WHERE m.period='1m' AND m.adjust='none'
        ), crossed AS (
          SELECT *,row_number() OVER(PARTITION BY zone_stack_id ORDER BY bar_end_time) AS crossing_order
          FROM bars WHERE minute_count=241 AND distinct_minute_count=241 AND high>=raw_threshold
        )
        SELECT zone_stack_id,bar_end_time AS candidate_reentry_time,raw_threshold,minute_count,distinct_minute_count
        FROM crossed WHERE crossing_order=1 ORDER BY zone_stack_id
        """
        con.execute(f"COPY ({query}) TO '{shard}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    con = v1.connection()
    exact = con.execute(f"SELECT * FROM read_parquet({v1.sql_paths(shards)}) ORDER BY zone_stack_id").fetchdf()
    con.close()
    v1.write_parquet(exact, EXACT_REENTRY)
    return exact


def prepare_candidates(candidates: pd.DataFrame, exact: pd.DataFrame) -> pd.DataFrame:
    frame = candidates.merge(exact, on="zone_stack_id", how="inner", validate="one_to_one")
    frame["candidate_reentry_time"] = pd.to_datetime(frame.candidate_reentry_time)
    frame["candidate_reentry_date"] = pd.to_datetime(frame.state_date)
    frame["multi_layer"] = frame.number_of_layers.gt(1)
    frame["candidate_year"] = frame.candidate_reentry_date.dt.year
    frame["persistence_sessions"] = frame.path_rn-1
    frame["persistence_bucket"] = pd.cut(
        frame.persistence_sessions,
        bins=[9, 20, 60, 120, np.inf],
        labels=["10_20", "21_60", "61_120", "GT120"],
    ).astype(str)
    frame["strength_structure"] = np.select(
        [
            frame.board_relative_return_percentile.ge(0.90),
            frame.return20_into_peak.ge(0.30),
        ],
        ["RELATIVE_LEADER", "FAST_20D"],
        default="LARGE_UP_PATH",
    )
    frame["sample_hash"] = frame.zone_stack_id.map(v1.stable_hash)
    v1.assert_no_outcome_columns(frame)
    hard = (
        frame.persistence_sessions.ge(10)
        & frame.prior_max_fully_below_run.ge(5)
        & frame.prior_post_zone_low.le(frame.zone_lower_boundary*0.875)
        & frame.prior_min_rolling_median_close5.le(frame.zone_lower_boundary*0.925)
        & frame.base_duration.ge(5)
        & frame.prior_partial_entry_count.eq(0)
        & frame.prior_full_fill_count.eq(0)
        & frame.coord_open.lt(frame.zone_lower_boundary)
        & frame.coord_high.ge(frame.zone_lower_boundary)
        & frame.minute_count.eq(241)
        & frame.distinct_minute_count.eq(241)
    )
    if not hard.all():
        raise PilotError(f"accepted lifecycle hard-gate failure: {int((~hard).sum())}")
    return frame


def select_sample(candidates: pd.DataFrame) -> pd.DataFrame:
    work = candidates.copy()
    if "sample_hash" not in work:
        work["sample_hash"] = work.zone_stack_id.map(v1.stable_hash)
    work = work.sort_values("sample_hash", kind="mergesort")
    year_quotas = {
        "MAIN": {2014: 2, 2015: 2, 2016: 2, 2017: 2, 2018: 2, 2019: 1, 2020: 1, 2021: 1},
        "CHINEXT": {2014: 1, 2015: 1, 2016: 1, 2017: 1, 2018: 1, 2020: 1, 2021: 1},
    }
    slots: list[tuple[str, int]] = []
    for board, by_year in year_quotas.items():
        for year, count in by_year.items():
            slots.extend([(board, year)]*count)
    selected: list[dict[str, Any]] = []
    used_symbols: set[str] = set()
    used_structures: defaultdict[str, int] = defaultdict(int)
    for slot_index, (board, year) in enumerate(slots):
        preferred_multi = slot_index % 2 == 0
        cell = work.loc[
            work.board.eq(board)
            & work.candidate_year.eq(year)
            & ~work.symbol.isin(used_symbols)
        ].copy()
        preferred = cell.loc[cell.multi_layer.eq(preferred_multi)]
        if not preferred.empty:
            cell = preferred
        if cell.empty:
            raise PilotError(f"empty deterministic sample cell: {board}/{year}")
        cell["diversity_key"] = cell.persistence_bucket+"|"+cell.strength_structure
        cell["prior_structure_use"] = cell.diversity_key.map(used_structures)
        chosen = cell.sort_values(["prior_structure_use", "sample_hash"], kind="mergesort").iloc[0]
        selected.append(chosen.to_dict())
        used_symbols.add(str(chosen.symbol))
        used_structures[str(chosen.diversity_key)] += 1
    sample = pd.DataFrame(selected).sort_values("sample_hash", kind="mergesort").reset_index(drop=True)
    sample["audit_id"] = [f"V3_{index:03d}" for index in range(1, len(sample)+1)]
    if len(sample) != 20 or sample.symbol.nunique() != 20:
        raise PilotError("pilot size or unique-security failure")
    if sample.board.value_counts().to_dict() != {"MAIN": 13, "CHINEXT": 7}:
        raise PilotError("board quota failure")
    if set(sample.candidate_year) != set(range(2014, 2022)):
        raise PilotError("candidate-year coverage failure")
    if sample.multi_layer.sum() < 8 or (~sample.multi_layer).sum() < 8:
        raise PilotError("single/multilayer preference not met")
    return sample


def layer_tuples(row: pd.Series, meaningful: bool = True) -> list[tuple[pd.Timestamp, float, float, bool]]:
    prefix = "meaningful_primitive" if meaningful else "all_primitive"
    dates = str(row[f"{prefix}_dates"]).split("|")
    lowers = str(row[f"{prefix}_lowers"]).split("|")
    uppers = str(row[f"{prefix}_uppers"]).split("|")
    if meaningful:
        flags = [True]*len(dates)
    else:
        flags = [value == "1" for value in str(row.all_primitive_meaningful).split("|")]
    return [(pd.Timestamp(date), float(lower), float(upper), flag) for date, lower, upper, flag in zip(dates, lowers, uppers, flags, strict=True)]


def normalize_primitive_id_lists(frame: pd.DataFrame) -> pd.DataFrame:
    """Rebuild unambiguous ID lists from symbol plus the separately stored dates."""
    frame = frame.copy()
    for prefix in ("meaningful_primitive", "all_primitive"):
        frame[f"{prefix}_ids"] = frame.apply(
            lambda row, prefix=prefix: ";".join(
                f"{row.symbol}|{date}" for date in str(row[f"{prefix}_dates"]).split("|")
            ),
            axis=1,
        )
    return frame


def load_chart_frame(row: pd.Series) -> pd.DataFrame:
    con = v1.connection()
    peak = con.execute(f"SELECT cal_idx FROM read_parquet('{DAILY}') WHERE symbol=? AND trade_date=?", [row.symbol, pd.Timestamp(row.peak_date).date()]).fetchone()
    reentry = con.execute(f"SELECT cal_idx FROM read_parquet('{DAILY}') WHERE symbol=? AND trade_date=?", [row.symbol, pd.Timestamp(row.candidate_reentry_date).date()]).fetchone()
    if peak is None or reentry is None:
        con.close()
        raise PilotError(f"chart clock missing: {row.audit_id}")
    frame = con.execute(f"""SELECT trade_date,cal_idx,coord_open,coord_high,coord_low,coord_close,turnover_fraction,coordinate_factor
      FROM read_parquet('{DAILY}') WHERE symbol=? AND cal_idx BETWEEN ? AND ?
      AND history_valid AND current_valid ORDER BY cal_idx""", [row.symbol, peak[0]-80, reentry[0]]).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    year = int(pd.Timestamp(row.candidate_reentry_date).year)
    con = v1.connection()
    partial = con.execute(f"""SELECT first(open ORDER BY bar_end_time),max(high),min(low),last(close ORDER BY bar_end_time)
      FROM read_parquet('{v1.raw_path(year)}') WHERE qmt_code=? AND trade_date=?
      AND period='1m' AND adjust='none' AND bar_end_time<=?""", [row.symbol, pd.Timestamp(row.candidate_reentry_date).date(), pd.Timestamp(row.candidate_reentry_time).to_pydatetime()]).fetchone()
    con.close()
    if partial[0] is None:
        raise PilotError(f"missing partial candidate candle: {row.audit_id}")
    factor = float(frame.iloc[-1].coordinate_factor)
    frame.loc[frame.index[-1], ["coord_open", "coord_high", "coord_low", "coord_close"]] = np.asarray(partial, dtype=float)*factor
    return frame


def draw_chart(row: pd.Series, frame: pd.DataFrame, path: Path, blind: bool) -> None:
    peak = float(row.peak_coord_high)
    scale = 100/peak
    x = np.arange(len(frame))
    fig, (ax, vol) = plt.subplots(2, 1, figsize=(15, 8), sharex=True, gridspec_kw={"height_ratios": [4, 1]}, layout="constrained")
    for index, item in enumerate(frame.itertuples(index=False)):
        color = "#c0392b" if item.coord_close >= item.coord_open else "#178f63"
        ax.vlines(index, item.coord_low*scale, item.coord_high*scale, color=color, linewidth=0.65)
        lower = min(item.coord_open, item.coord_close)*scale
        height = max(abs(item.coord_close-item.coord_open)*scale, 0.025)
        ax.add_patch(Rectangle((index-0.3, lower), 0.6, height, facecolor=color, edgecolor=color, linewidth=0.35))

    formation_start = int(np.searchsorted(frame.trade_date.to_numpy(), pd.Timestamp(row.zone_formation_date).to_datetime64(), side="left"))
    ax.add_patch(Rectangle(
        (formation_start-0.5, row.stack_lower_boundary*scale),
        len(frame)-formation_start,
        max((row.stack_upper_boundary-row.stack_lower_boundary)*scale, 0.02),
        facecolor="#d9d9d9", edgecolor="#8c8c8c", linestyle="--", alpha=0.25, linewidth=1.1,
        label="STACK ENVELOPE — MAY CONTAIN TRADED PRICE REGIONS",
    ))
    layers = layer_tuples(row, meaningful=True)
    for index, (date, lower, upper, _) in enumerate(layers):
        start = int(np.searchsorted(frame.trade_date.to_numpy(), date.to_datetime64(), side="left"))
        ax.add_patch(Rectangle(
            (start-0.5, lower*scale), len(frame)-start, max((upper-lower)*scale, 0.02),
            facecolor="#e67e22", edgecolor="#d35400", alpha=0.28, linewidth=0.8,
            label="True strict no-trade collapse-defining layers" if index == 0 else None,
        ))
    if not blind:
        other_math_label_used = False
        other_meaningful_label_used = False
        selected_ids = {
            f"{row.symbol}|{date}" for date in str(row.meaningful_primitive_dates).split("|")
        }
        all_ids = [f"{row.symbol}|{date}" for date in str(row.all_primitive_dates).split("|")]
        for primitive_id, (date, lower, upper, flag) in zip(
            all_ids, layer_tuples(row, meaningful=False), strict=True
        ):
            if primitive_id in selected_ids:
                continue
            start = int(np.searchsorted(frame.trade_date.to_numpy(), date.to_datetime64(), side="left"))
            if flag:
                ax.add_patch(Rectangle((start-0.5, lower*scale), len(frame)-start, max((upper-lower)*scale, 0.015), facecolor="#f5b041", edgecolor="#b9770e", alpha=0.13, linewidth=0.5, label="Other meaningful collapse gaps" if not other_meaningful_label_used else None))
                other_meaningful_label_used = True
            else:
                ax.add_patch(Rectangle((start-0.5, lower*scale), len(frame)-start, max((upper-lower)*scale, 0.015), facecolor="#85c1e9", edgecolor="#5dade2", alpha=0.10, linewidth=0.45, label="Other mathematical strict gaps" if not other_math_label_used else None))
                other_math_label_used = True

    peak_pos = int(np.argmin(np.abs(frame.trade_date-pd.Timestamp(row.peak_date))))
    trough_pos = int(np.argmin(np.abs(frame.trade_date-pd.Timestamp(row.postcollapse_low_date))))
    ax.scatter([peak_pos], [100], marker="v", color="#2c3e50", s=42, label="Prior peak")
    ax.scatter([trough_pos], [row.postcollapse_low_coord*scale], marker="o", facecolors="none", edgecolors="#5b2c6f", s=42, label="Post-collapse low")
    ax.scatter([len(frame)-1], [row.zone_lower_boundary*scale], marker="^", color="#2471a3", s=58, label="First meaningful-zone return")
    turnover = frame.turnover_fraction.astype(float)
    norm = turnover/turnover.rolling(20, min_periods=5).median().replace(0, np.nan)
    vol.bar(x, norm.fillna(0), color="#7f8c8d", width=0.7)
    vol.axhline(1, color="#34495e", linewidth=0.7, linestyle=":")
    ax.set_ylabel("Normalized price (prior peak = 100)")
    vol.set_ylabel("Turnover /\n20-session median")
    vol.set_xlabel("Relative trading sessions")
    ax.grid(alpha=0.14)
    vol.grid(alpha=0.10)
    ax.legend(loc="best", fontsize=7.5)
    if blind:
        ax.set_title(str(row.audit_id))
        ax.set_xticks([])
        metadata = {"Title": str(row.audit_id), "Subject": "Outcome-blind V3 semantic review"}
    else:
        ax.set_title(f"{row.audit_id} | {row.symbol} | peak {pd.Timestamp(row.peak_date).date()} | return {pd.Timestamp(row.candidate_reentry_time)}")
        step = max(1, len(frame)//9)
        ticks = x[::step]
        vol.set_xticks(ticks)
        vol.set_xticklabels([frame.trade_date.iloc[i].strftime("%Y-%m-%d") for i in ticks], rotation=30, ha="right", fontsize=7)
        text = (
            f"layers={int(row.number_of_layers)} width_sum={row.sum_strict_gap_width/row.peak_coord_high:.2%} "
            f"collapse_share={row.sum_strict_gap_width/(row.peak_coord_high-row.postcollapse_low_coord):.2%}\n"
            f"peak-low={row.peak_to_low_decline:.1%} zone-low={row.zone_to_low_decline:.1%} "
            f"persistence={int(row.persistence_sessions)} full-below={int(row.prior_max_fully_below_run)} base={int(row.base_duration)}\n"
            f"runup60/120={row.max_runup_from_60_low:.1%}/{row.max_runup_from_120_low:.1%} "
            f"board-rank={row.board_relative_return_percentile:.2f} turnover5/20={row.turnover_5_20:.2f}"
        )
        ax.text(0.01, 0.02, text, transform=ax.transAxes, fontsize=7, va="bottom", bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "#bbbbbb"})
        metadata = {"Title": f"{row.audit_id} diagnostic", "Subject": "No post-entry outcomes"}
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=135, metadata=metadata)
    plt.close(fig)


def build_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)
    expected = {f"{value}.png" for value in sample.audit_id}
    identity = CHART_RENDER_VERSION+"\n"+"\n".join(
        f"{row.audit_id}|{row.zone_stack_id}" for row in sample.itertuples(index=False)
    )+"\n"
    if (
        {path.name for path in BLIND_DIR.glob("V3_*.png")} == expected
        and {path.name for path in DIAGNOSTIC_DIR.glob("V3_*.png")} == expected
        and CHART_SAMPLE_IDENTITY.is_file()
        and CHART_SAMPLE_IDENTITY.read_text(encoding="utf-8") == identity
    ):
        return
    for directory in (BLIND_DIR, DIAGNOSTIC_DIR):
        for path in directory.glob("V3_*.png"):
            path.unlink()
    for row in sample.itertuples(index=False):
        series = pd.Series(row._asdict())
        frame = load_chart_frame(series)
        draw_chart(series, frame, BLIND_DIR/f"{row.audit_id}.png", True)
        draw_chart(series, frame, DIAGNOSTIC_DIR/f"{row.audit_id}.png", False)
    v1.create_html_index(BLIND_DIR, sample.audit_id.tolist(), True)
    v1.create_html_index(DIAGNOSTIC_DIR, sample.audit_id.tolist(), False)
    v1.atomic_text(CHART_SAMPLE_IDENTITY, identity)


REVIEW_COLUMNS = [
    "audit_id", "PRIMARY_LABEL", "FORMER_STRONG_STOCK_VALID", "PRIOR_RISE_IMPULSIVE_ENOUGH",
    "COLLAPSE_MAIN_LEG_VALID", "ZONE_IS_MEANINGFUL_COLLAPSE_GAP", "ZONE_IS_TOO_SMALL_OR_LOCAL",
    "ZONE_PERSISTED_LONG_ENOUGH", "DISTINCT_BELOW_ZONE_REGIME_EXISTS", "BASE_OR_SETTLING_PHASE_LOOKS_RIGHT",
    "SELECTED_LAYER_IS_CORRECT", "FIRST_RETURN_MARKER_IS_CORRECT",
    "WOULD_CONSIDER_THIS_THE_USER_DEFINED_SETUP", "REJECTION_REASON", "FREE_TEXT_NOTE",
]


def write_review_files(sample: pd.DataFrame) -> None:
    review = pd.DataFrame({column: [""]*len(sample) for column in REVIEW_COLUMNS})
    review["audit_id"] = sample.audit_id
    instructions = f"""# {EXPERIMENT} review instructions

Review the 20 blind charts at `{BLIND_DIR}` and fill `{REVIEW_CSV}`.

1. Judge only machine-to-human semantic fidelity. Do not predict returns.
2. View blind charts before the private diagnostic package.
3. `PRIMARY_LABEL` allows `A_EXACT_PATTERN`, `B_CLOSE`, or `C_NOT_PATTERN`.
4. Component fields allow `YES`, `NO`, or `UNCERTAIN`.
5. The orange rectangles are true strict no-trade collapse-defining layers.
6. The light-gray context is explicitly a stack envelope and may contain traded price regions; never judge it as one continuous gap.
7. `REJECTION_REASON` accepts semicolon-separated values from: `NOT_FORMER_STRONG_STOCK`, `RISE_TOO_SLOW`, `RISE_TOO_WEAK`, `COLLAPSE_NOT_MAIN_LEG`, `ZONE_TOO_SMALL`, `ZONE_TOO_LOCAL`, `WRONG_ZONE`, `WRONG_LAYER`, `ZONE_NOT_PERSISTENT`, `NO_DISTINCT_LOWER_REGIME`, `NO_SETTLING_PHASE`, `RETURN_TOO_FAST`, `WRONG_FIRST_RETURN_MARKER`, `OTHER`.
8. Identity, calendar dates, machine scores/classes, and all post-marker bars are hidden.

All numeric gates are semantic retrieval rules only, not strategy parameters. Do not run returns after labeling without separate authorization.
"""
    v1.atomic_text(REVIEW_CSV, review.to_csv(index=False))
    v1.atomic_text(REVIEW_INSTRUCTIONS, instructions)
    v1.atomic_text(BLIND_DIR/REVIEW_CSV.name, review.to_csv(index=False))
    v1.atomic_text(BLIND_DIR/REVIEW_INSTRUCTIONS.name, instructions)


def identity_leak_count(sample: pd.DataFrame) -> int:
    leaks = 0
    for row in sample.itertuples(index=False):
        data = (BLIND_DIR/f"{row.audit_id}.png").read_bytes()
        forbidden = [row.symbol.encode(), pd.Timestamp(row.peak_date).strftime("%Y-%m-%d").encode(), pd.Timestamp(row.candidate_reentry_date).strftime("%Y-%m-%d").encode()]
        leaks += int(any(token in data for token in forbidden))
    return leaks


def rejection_counts(rows: pd.DataFrame, all_primitives: pd.DataFrame, meaningful: pd.DataFrame, stacks: pd.DataFrame) -> dict[str, int]:
    touches = rows.loc[rows.current_upward_entry].copy()
    for column in (
        "persistence_pass", "fully_below_pass", "post_zone_depth_pass", "lower_regime_pass",
        "base_pass", "unresolved_pass",
    ):
        touches[column] = touches[column].astype("boolean").fillna(False).astype(bool)
    later_qualified_with_prior = touches.loc[
        touches.persistence_pass & touches.fully_below_pass & touches.post_zone_depth_pass
        & touches.lower_regime_pass & touches.base_pass & touches.unresolved_pass
        & touches.prior_partial_entry_count.gt(0)
    ]
    return {
        "rejected_tiny_local_gaps": int(len(all_primitives)-len(meaningful)),
        "rejected_insufficient_persistence": int(touches.loc[~(touches.persistence_pass & touches.fully_below_pass), "zone_stack_id"].nunique()),
        "rejected_insufficient_post_zone_depth": int(touches.loc[~touches.post_zone_depth_pass, "zone_stack_id"].nunique()),
        "rejected_no_distinct_lower_regime": int(touches.loc[~touches.lower_regime_pass, "zone_stack_id"].nunique()),
        "rejected_prior_partial_reentry": int(later_qualified_with_prior.zone_stack_id.nunique()),
        "stacks_without_any_return_by_2021": int(len(stacks)-touches.zone_stack_id.nunique()),
    }


def render_report(result: dict[str, Any]) -> str:
    detector = result["detector"]
    pilot = result["pilot"]
    return f"""# {EXPERIMENT}

Status: `PILOT_PACKAGE_COMPLETE`; `HUMAN_REVIEW_REQUIRED`.

This is a collapse-first, outcome-blind machine-to-human semantic precision pilot. It is not a strategy study. Retrieval uses 2014–2021 only; Validation 2022–2023 and repository 2024+ remain unopened.

## Semantic preflight

Prior leader/strength → impulsive rise → objective peak → material peak-to-trough collapse → economically significant strict no-trade primitive(s) during that collapse → unresolved overhead layers → material independent lower regime → post-trough settling → first return from below to the lowest meaningful unresolved layer.

Strict primitive, collapse-defining gap, grouped collapse zone, and human visual “断层带” remain distinct objects. Every numeric gate is a high-precision retrieval rule only.

## Detector

- Eligible symbols: {detector['eligible_symbols']:,}
- Collapse episodes detected before gap assignment: {detector['collapse_episodes']:,}
- Source strict primitives: {detector['strict_gap_primitives']:,}
- Collapse-defining meaningful primitives: {detector['meaningful_collapse_gap_primitives']:,}
- Meaningful stacks: {detector['meaningful_zone_stacks']:,}; multilayer: {detector['multilayer_stacks']:,}
- Candidate stacks surviving the full lifecycle: {detector['candidate_stacks']:,}

True strict gap layers are orange. The light-gray stack envelope is explicitly labeled `STACK ENVELOPE — MAY CONTAIN TRADED PRICE REGIONS` and is never represented as one no-trade gap.

## Rejections

- Tiny/local significance failure: {detector['rejected_tiny_local_gaps']:,}
- Off-collapse strict gaps: {detector['rejected_off_collapse_gaps']:,}
- Insufficient persistence: {detector['rejected_insufficient_persistence']:,}
- Insufficient post-zone depth: {detector['rejected_insufficient_post_zone_depth']:,}
- No distinct lower regime: {detector['rejected_no_distinct_lower_regime']:,}
- Prior partial re-entry: {detector['rejected_prior_partial_reentry']:,}

Rejection diagnostics may overlap; they are semantic attrition counts, not statistical outcomes.

## Pilot

- Blind/diagnostic charts: {pilot['blind_chart_count']}/{pilot['diagnostic_chart_count']}
- Main/ChiNext: {pilot['main_count']}/{pilot['chinext_count']}
- ST: {pilot['st_count']}; multilayer/single: {pilot['multilayer_count']}/{pilot['single_layer_count']}
- Outcome-selected sample: {pilot['outcome_selected_sample_count']}
- Identity leaks: {pilot['identity_leak_count']}; post-entry bars: {pilot['post_entry_bar_count']}

No post-entry returns, MFE/MAE, replay, model, or parameter optimization was constructed.

## Next action

Human reviews the 20 V3 blind charts. If semantic precision is high, use only those human labels to freeze meaningful-zone/lower-regime/first-return semantics. If precision remains low, revise the detector again. Do not run returns.
"""


def run() -> dict[str, Any]:
    inputs = validate_inputs()
    episodes = build_collapse_episodes()
    all_primitives, meaningful = build_episode_primitives()
    stacks = group_meaningful_zones(meaningful, all_primitives)
    lifecycle_rows, daily_candidates = build_lifecycle(stacks)
    if daily_candidates.empty:
        raise PilotError("no V3 candidates survive the frozen lifecycle")
    exact = build_exact_reentry(daily_candidates)
    candidates = normalize_primitive_id_lists(prepare_candidates(daily_candidates, exact))
    v1.write_parquet(candidates.drop(columns=["sample_hash"]), CANDIDATES)
    sample = select_sample(candidates)
    build_charts(sample)
    write_review_files(sample)
    v1.write_parquet(sample.drop(columns=["sample_hash"]), MAPPING)

    rejected = rejection_counts(lifecycle_rows, all_primitives, meaningful, stacks)
    total_strict = pd.read_parquet(STRICT_PRIMITIVES, columns=["gap_primitive_id"]).gap_primitive_id.nunique()
    assigned_unique = all_primitives.gap_primitive_id.nunique()
    blind_count = len(list(BLIND_DIR.glob("V3_*.png")))
    diagnostic_count = len(list(DIAGNOSTIC_DIR.glob("V3_*.png")))
    leaks = identity_leak_count(sample)
    if blind_count != 20 or diagnostic_count != 20 or leaks:
        raise PilotError(f"chart audit failure: blind={blind_count}, diagnostic={diagnostic_count}, leaks={leaks}")
    review = pd.read_csv(REVIEW_CSV, keep_default_na=False)
    if any(review[column].ne("").any() for column in review.columns if column != "audit_id"):
        raise PilotError("review CSV must start blank")

    detector = {
        "eligible_symbols": int(pd.read_parquet(DAILY, columns=["symbol"]).symbol.nunique()),
        "collapse_episodes": len(episodes),
        "strict_gap_primitives": int(total_strict),
        "meaningful_collapse_gap_primitives": len(meaningful),
        "meaningful_zone_stacks": len(stacks),
        "multilayer_stacks": int(stacks.number_of_layers.gt(1).sum()),
        "candidate_stacks": len(candidates),
        "rejected_off_collapse_gaps": int(total_strict-assigned_unique),
        **rejected,
    }
    pilot = {
        "blind_chart_count": blind_count,
        "diagnostic_chart_count": diagnostic_count,
        "main_count": int(sample.board.eq("MAIN").sum()),
        "chinext_count": int(sample.board.eq("CHINEXT").sum()),
        "st_count": int(sample.is_st.sum()),
        "multilayer_count": int(sample.multi_layer.sum()),
        "single_layer_count": int((~sample.multi_layer).sum()),
        "outcome_selected_sample_count": 0,
        "identity_leak_count": leaks,
        "post_entry_bar_count": 0,
    }
    result = {
        "experiment_id": EXPERIMENT,
        "start_checkpoint": START_HEAD,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "research_type": "OUTCOME_BLIND_COLLAPSE_FIRST_HUMAN_PATTERN_PRECISION_PILOT",
        "input_identity": inputs,
        "semantic_preflight": json.loads(SPEC.read_text(encoding="utf-8"))["semantic_preflight"],
        "detector": detector,
        "pilot": pilot,
        "governance": {
            "post_2021_outcome_read_count": 0,
            "validation_opened": False,
            "repository_2024_plus_data_opened": False,
            "outcome_used_for_candidate_selection_count": 0,
            "return_analysis_run": False,
            "strategy_backtest_run": False,
            "reentry_references_postcollapse_local_gap_count": 0,
        },
        "status": {
            "pilot_package_complete": True,
            "human_review_required": True,
            "return_analysis_run": False,
            "strategy_backtest_run": False,
        },
        "paths": {
            "blind_package": str(BLIND_DIR),
            "diagnostic_package": str(DIAGNOSTIC_DIR),
            "review_csv": str(REVIEW_CSV),
            "review_instructions": str(REVIEW_INSTRUCTIONS),
            "mapping": str(MAPPING),
        },
    }
    v1.atomic_json(RESULT, result)
    v1.atomic_text(REPORT, render_report(result))
    return result


if __name__ == "__main__":
    outcome = run()
    print(json.dumps({"experiment_id": outcome["experiment_id"], "detector": outcome["detector"], "pilot": outcome["pilot"], "status": outcome["status"]}, indent=2))
