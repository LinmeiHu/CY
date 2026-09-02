#!/usr/bin/env python3
# ruff: noqa: E402,E501
"""Build the outcome-blind 30-chart Collapse Gap-Zone high-precision pilot."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_pattern_fidelity_audit_v1 as v1,
)

OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-HIGH-PRECISION-PILOT-V2"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "16993136a13027fc33b11ffb2117d41eef44c3019dd6c9fbe62ce5621b477d00"
START_HEAD = "3f24b1b8a8e1071e83bf7cfc4e1257ec277b7643"

EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_high_precision_pilot_v2")
CANDIDATE_DAILY = EXTERNAL / "candidate_daily.parquet"
EXACT_REENTRY = EXTERNAL / "exact_reentry.parquet"
BLIND_DIR = EXTERNAL / "blind_charts"

CANDIDATE_POOL = OS_ROOT / f"artifacts/{EXPERIMENT}_candidate_pool.parquet"
SAMPLE_MANIFEST = OS_ROOT / f"artifacts/{EXPERIMENT}_sample_manifest.parquet"
AUDIT_MAPPING = OS_ROOT / f"artifacts/{EXPERIMENT}_audit_mapping.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
REVIEW_CSV = OS_ROOT / f"reports/{EXPERIMENT}_review.csv"
REVIEW_INSTRUCTIONS = OS_ROOT / f"reports/{EXPERIMENT}_REVIEW_INSTRUCTIONS.md"

GROUPED = v1.PRIMITIVES_GROUPED
DAILY = v1.DAILY_COMPACT


class PilotError(RuntimeError):
    """Fail-closed pilot construction error."""


def validate_inputs() -> dict[str, Any]:
    if v1.sha256_file(SPEC) != EXPECTED_SPEC_SHA256:
        raise PilotError("frozen V2 spec hash mismatch")
    source_identity = v1.validate_inputs()
    if not GROUPED.is_file() or not DAILY.is_file():
        v1.build_grouped_primitives()
        v1.build_daily_compact()
    return {
        "v2_spec_sha256": EXPECTED_SPEC_SHA256,
        "v1_source_contract": source_identity,
        "v1_partial_review_read_or_summarized": False,
    }


def candidate_query() -> str:
    """Frozen outcome-blind formation, persistence, depth, and daily re-entry query."""
    return f"""
    WITH primitive_enriched AS (
      SELECT g.*,
        gd.cal_idx-pd.cal_idx AS peak_to_gap_sessions,
        gd.coord_close/nullif(p5.coord_close,0)-1 AS return5_into_gap
      FROM read_parquet('{GROUPED}') g
      JOIN read_parquet('{DAILY}') gd
        ON gd.symbol=g.symbol AND gd.trade_date=g.gap_date
      JOIN read_parquet('{DAILY}') pd
        ON pd.symbol=g.symbol AND pd.trade_date=g.peak_date
      LEFT JOIN read_parquet('{DAILY}') p5
        ON p5.symbol=g.symbol AND p5.cal_idx=gd.cal_idx-5
    ), meaningful AS (
      SELECT * FROM primitive_enriched
      WHERE width_pct_vs_prev_close>=0.015
        AND peak_to_gap_sessions BETWEEN 1 AND 40
        AND decline_to_gap>=0.25
        AND return5_into_gap<=-0.05
    ), layer_summary AS (
      SELECT collapse_episode_id,
        count(*) AS meaningful_layer_count,
        min(lower_coord) AS meaningful_stack_lower,
        max(upper_coord) AS meaningful_stack_upper,
        max(gap_cal_idx) AS final_layer_cal_idx,
        max(gap_date) AS final_layer_date,
        string_agg(gap_primitive_id,'|' ORDER BY gap_date,gap_primitive_id) AS meaningful_primitive_ids,
        string_agg(strftime(gap_date,'%Y-%m-%d'),'|' ORDER BY gap_date,gap_primitive_id) AS meaningful_primitive_dates,
        string_agg(printf('%.12g',lower_coord),'|' ORDER BY gap_date,gap_primitive_id) AS meaningful_primitive_lower_coords,
        string_agg(printf('%.12g',upper_coord),'|' ORDER BY gap_date,gap_primitive_id) AS meaningful_primitive_upper_coords
      FROM meaningful GROUP BY collapse_episode_id
    ), ranked AS (
      SELECT m.*,row_number() OVER(
        PARTITION BY m.collapse_episode_id
        ORDER BY m.lower_coord,m.gap_date,m.gap_primitive_id
      ) AS lowest_order
      FROM meaningful m
    ), anchors AS (
      SELECT r.*,s.* EXCLUDE(collapse_episode_id)
      FROM ranked r JOIN layer_summary s USING(collapse_episode_id)
      WHERE r.lowest_order=1
        AND r.board_relative_return_percentile>=0.90
        AND r.max_runup_from_60_low>=0.50
        AND r.return60_into_peak>=0.30
        AND r.main_rise_duration BETWEEN 5 AND 80
        AND r.rise_speed>=0.01
        AND r.number_large_up_days>=3
        AND r.decline_to_gap>=0.30
        AND r.width_pct_vs_prev_close>=0.02
        AND r.return5_into_gap<=-0.08
    ), qualification AS (
      SELECT a.collapse_episode_id,
        min(d.trade_date) FILTER(
          WHERE d.cal_idx>=a.final_layer_cal_idx+5
            AND d.coord_low<=a.lower_coord*0.875
        ) AS depth_qualification_date,
        min(d.cal_idx) FILTER(
          WHERE d.cal_idx>=a.final_layer_cal_idx+5
            AND d.coord_low<=a.lower_coord*0.875
        ) AS depth_qualification_cal_idx,
        min(d.trade_date) FILTER(
          WHERE d.cal_idx>a.final_layer_cal_idx
            AND d.coord_high>=a.upper_coord
        ) AS first_full_fill_date
      FROM anchors a
      JOIN read_parquet('{DAILY}') d
        ON d.symbol=a.symbol
       AND d.cal_idx>a.final_layer_cal_idx
       AND d.trade_date<=DATE '2021-12-31'
       AND d.invalid_step_cum=a.invalid_step_cum
       AND d.history_valid AND d.current_valid
      GROUP BY a.collapse_episode_id
    ), daily_candidates AS (
      SELECT a.*,q.depth_qualification_date,q.depth_qualification_cal_idx,q.first_full_fill_date,
        d.trade_date AS candidate_reentry_date,d.cal_idx AS candidate_reentry_cal_idx,
        d.coord_open AS candidate_coord_open,d.coord_high AS candidate_coord_high,
        d.coord_low AS candidate_coord_low,d.coordinate_factor AS candidate_coordinate_factor,
        row_number() OVER(
          PARTITION BY a.collapse_episode_id ORDER BY d.trade_date
        ) AS candidate_order
      FROM anchors a JOIN qualification q USING(collapse_episode_id)
      JOIN read_parquet('{DAILY}') d
        ON d.symbol=a.symbol
       AND d.cal_idx>q.depth_qualification_cal_idx
       AND d.cal_idx>=a.final_layer_cal_idx+6
       AND d.cal_idx<=a.final_layer_cal_idx+250
       AND d.coord_open<a.lower_coord
       AND d.coord_high>=a.lower_coord
       AND d.invalid_step_cum=a.invalid_step_cum
       AND d.history_valid AND d.current_valid
       AND d.trade_date<=DATE '2021-12-31'
       AND (q.first_full_fill_date IS NULL OR d.trade_date<=q.first_full_fill_date)
      WHERE q.depth_qualification_date IS NOT NULL
    ), first_daily AS (
      SELECT * FROM daily_candidates WHERE candidate_order=1
    ), pre_reentry AS (
      SELECT f.collapse_episode_id,min(d.coord_low) AS pre_reentry_low_coord
      FROM first_daily f JOIN read_parquet('{DAILY}') d
        ON d.symbol=f.symbol
       AND d.cal_idx BETWEEN f.final_layer_cal_idx+1 AND f.candidate_reentry_cal_idx-1
       AND d.invalid_step_cum=f.invalid_step_cum
       AND d.history_valid AND d.current_valid
      GROUP BY f.collapse_episode_id
    )
    SELECT f.*,p.pre_reentry_low_coord,
      1-p.pre_reentry_low_coord/f.lower_coord AS depth_below_zone,
      f.candidate_reentry_cal_idx-f.final_layer_cal_idx AS candidate_session_lag_from_final_layer,
      f.meaningful_layer_count>1 AS multi_layer
    FROM first_daily f JOIN pre_reentry p USING(collapse_episode_id)
    ORDER BY f.collapse_episode_id
    """


def build_candidate_daily() -> pd.DataFrame:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    con = v1.connection()
    con.execute(f"COPY ({candidate_query()}) TO '{CANDIDATE_DAILY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    frame = pd.read_parquet(CANDIDATE_DAILY)
    for column in [c for c in frame.columns if c.endswith("_date")]:
        frame[column] = pd.to_datetime(frame[column])
    return frame


def build_exact_reentry(daily: pd.DataFrame) -> pd.DataFrame:
    pair_path = EXTERNAL / "exact_reentry_pairs.parquet"
    v1.write_parquet(
        daily[["collapse_episode_id", "symbol", "candidate_reentry_date", "lower_coord", "candidate_coordinate_factor"]],
        pair_path,
    )
    shards: list[Path] = []
    for year in v1.DEVELOPMENT_YEARS:
        shard = EXTERNAL / f"exact_reentry_{year}.parquet"
        shards.append(shard)
        con = v1.connection()
        query = f"""
        WITH pairs AS (
          SELECT *,lower_coord/candidate_coordinate_factor AS raw_threshold
          FROM read_parquet('{pair_path}')
          WHERE year(candidate_reentry_date)={year}
        ), bars AS (
          SELECT p.*,m.bar_end_time,m.open,m.high,m.low,
            count(*) OVER(PARTITION BY p.collapse_episode_id) AS minute_count,
            count(DISTINCT m.bar_end_time) OVER(PARTITION BY p.collapse_episode_id) AS distinct_minute_count
          FROM pairs p JOIN read_parquet('{v1.raw_path(year)}') m
            ON m.qmt_code=p.symbol AND m.trade_date=p.candidate_reentry_date
          WHERE m.period='1m' AND m.adjust='none'
        ), crossing AS (
          SELECT *,row_number() OVER(
            PARTITION BY collapse_episode_id ORDER BY bar_end_time
          ) AS crossing_order
          FROM bars
          WHERE minute_count=241 AND distinct_minute_count=241
            AND high>=raw_threshold
        )
        SELECT collapse_episode_id,bar_end_time AS candidate_reentry_time,
          raw_threshold,minute_count,distinct_minute_count
        FROM crossing WHERE crossing_order=1
        ORDER BY collapse_episode_id
        """
        con.execute(f"COPY ({query}) TO '{shard}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    con = v1.connection()
    exact = con.execute(f"SELECT * FROM read_parquet({v1.sql_paths(shards)}) ORDER BY collapse_episode_id").fetchdf()
    con.close()
    v1.write_parquet(exact, EXACT_REENTRY)
    return exact


def clipped(value: pd.Series, lower: float, width: float) -> pd.Series:
    return ((value-lower)/width).clip(0, 1)


def prepare_pool(daily: pd.DataFrame, exact: pd.DataFrame) -> pd.DataFrame:
    frame = daily.merge(exact, on="collapse_episode_id", how="inner", validate="one_to_one")
    frame["candidate_reentry_time"] = pd.to_datetime(frame.candidate_reentry_time)
    frame["semantic_retrieval_score"] = pd.concat(
        [
            clipped(frame.board_relative_return_percentile, 0.90, 0.10),
            clipped(frame.max_runup_from_60_low, 0.50, 1.00),
            clipped(frame.return60_into_peak, 0.30, 0.70),
            clipped(frame.rise_speed, 0.01, 0.04),
            clipped(frame.decline_to_gap, 0.30, 0.40),
            clipped(frame.width_pct_vs_prev_close, 0.02, 0.06),
            clipped(frame.depth_below_zone, 0.125, 0.275),
            clipped(frame.candidate_session_lag_from_final_layer, 6, 54),
        ],
        axis=1,
    ).mean(axis=1)
    frame["candidate_year"] = pd.to_datetime(frame.candidate_reentry_date).dt.year
    frame["zone_type"] = np.where(frame.meaningful_layer_count.gt(1), "LAYERED", "SINGLE")
    frame["sample_hash"] = frame.collapse_episode_id.map(v1.stable_hash)

    # Rename only the chart-facing semantic fields; retain source lineage columns.
    frame["peak_coord_high"] = frame.peak_coord_high
    frame["chosen_lower_coord"] = frame.lower_coord
    frame["chosen_upper_coord"] = frame.upper_coord
    frame["primitive_count"] = frame.meaningful_layer_count
    frame["primitive_dates"] = frame.meaningful_primitive_dates
    frame["primitive_lower_coords"] = frame.meaningful_primitive_lower_coords
    frame["primitive_upper_coords"] = frame.meaningful_primitive_upper_coords
    frame["stack_lower"] = frame.meaningful_stack_lower
    frame["stack_upper"] = frame.meaningful_stack_upper
    frame["max_decline_to_gap"] = frame.decline_to_gap
    frame["persistence_bucket"] = "FIVE_PLUS_UNFILLED_SESSIONS"

    v1.assert_no_outcome_columns(frame)
    hard = (
        frame.board_relative_return_percentile.ge(0.90)
        & frame.max_runup_from_60_low.ge(0.50)
        & frame.return60_into_peak.ge(0.30)
        & frame.main_rise_duration.between(5, 80)
        & frame.rise_speed.ge(0.01)
        & frame.number_large_up_days.ge(3)
        & frame.decline_to_gap.ge(0.30)
        & frame.peak_to_gap_sessions.between(1, 40)
        & frame.return5_into_gap.le(-0.08)
        & frame.width_pct_vs_prev_close.ge(0.02)
        & frame.candidate_session_lag_from_final_layer.ge(6)
        & frame.candidate_session_lag_from_final_layer.le(250)
        & frame.depth_below_zone.ge(0.125)
        & frame.candidate_coord_open.lt(frame.lower_coord)
    )
    if not hard.all():
        raise PilotError(f"high-precision hard-gate failures: {int((~hard).sum())}")
    if not frame.minute_count.eq(241).all() or not frame.distinct_minute_count.eq(241).all():
        raise PilotError("non-241-minute candidate session")
    return frame


def select_sample(pool: pd.DataFrame) -> pd.DataFrame:
    pool = pool.copy()
    if "sample_hash" not in pool:
        pool["sample_hash"] = pool.collapse_episode_id.map(v1.stable_hash)
    quotas = {"MAIN": 20, "CHINEXT": 10}
    selected: list[dict[str, Any]] = []
    for board, quota in quotas.items():
        board_pool = pool.loc[pool.board.eq(board)].sort_values(
            ["semantic_retrieval_score", "sample_hash"], ascending=[False, True], kind="mergesort"
        )
        board_pool = board_pool.drop_duplicates("symbol", keep="first")
        if len(board_pool) < quota:
            raise PilotError(f"insufficient unique {board} support: {len(board_pool)}<{quota}")
        board_pool["sampling_stratum"] = board_pool.candidate_year.astype(str)+"|"+board_pool.zone_type
        groups = {
            key: part.sort_values(["semantic_retrieval_score", "sample_hash"], ascending=[False, True], kind="mergesort").to_dict("records")
            for key, part in board_pool.groupby("sampling_stratum", sort=True)
        }
        positions: defaultdict[str, int] = defaultdict(int)
        while len([row for row in selected if row["board"] == board]) < quota:
            progressed = False
            for key in sorted(groups):
                pos = positions[key]
                if pos < len(groups[key]):
                    selected.append(groups[key][pos])
                    positions[key] += 1
                    progressed = True
                if len([row for row in selected if row["board"] == board]) == quota:
                    break
            if not progressed:
                raise PilotError(f"sampling exhausted for {board}")
    sample = pd.DataFrame(selected).sort_values("sample_hash", kind="mergesort").reset_index(drop=True)
    sample["audit_id"] = [f"HP_{index:03d}" for index in range(1, len(sample)+1)]
    if len(sample) != 30 or sample.audit_id.nunique() != 30 or sample.symbol.nunique() != 30:
        raise PilotError("30-case sample identity failure")
    if sample.board.value_counts().to_dict() != quotas:
        raise PilotError("board quota failure")
    return sample


def build_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    for path in BLIND_DIR.glob("HP_*.png"):
        path.unlink()
    for row in sample.itertuples(index=False):
        series = pd.Series(row._asdict())
        chart_frame = v1.load_chart_frame(series)
        v1.draw_chart(series, chart_frame, BLIND_DIR/f"{row.audit_id}.png", True)
    v1.create_html_index(BLIND_DIR, sample.audit_id.tolist(), True)


REVIEW_COLUMNS = [
    "audit_id",
    "PRIMARY_LABEL",
    "FORMER_LEADER_VISUALLY_VALID",
    "PRIOR_RUNUP_IMPULSIVE",
    "COLLAPSE_MAJOR_AND_COHERENT",
    "GAP_ZONE_VISUALLY_MEANINGFUL",
    "GAP_FORMED_DURING_MAIN_COLLAPSE_LEG",
    "ZONE_PERSISTED_UNRESOLVED",
    "MATERIAL_MOVE_BELOW_ZONE_VISIBLE",
    "FIRST_LATER_RETURN_BOUNDARY_LOOKS_CORRECT",
    "REJECTION_REASON",
    "FREE_TEXT_NOTE",
]


def write_review_package(sample: pd.DataFrame) -> None:
    review = pd.DataFrame({column: [""]*len(sample) for column in REVIEW_COLUMNS})
    review["audit_id"] = sample.audit_id
    instructions = f"""# {EXPERIMENT} review instructions

The V1 120-chart workflow is stopped. Do not finish or summarize it.

Review only the 30 blind charts at `{BLIND_DIR}` and fill `{REVIEW_CSV}`.

1. Judge visual semantic fidelity only; do not predict future returns.
2. Identity, dates, and all post-marker information are intentionally hidden.
3. Use `A_EXACT_PATTERN`, `B_CLOSE_BUT_MISSING_SOMETHING`, or `C_NOT_THE_PATTERN` for `PRIMARY_LABEL`.
4. An exact pattern should visibly contain a former strong/leader stock, impulsive run-up, major coherent collapse, meaningful strict-gap/layered zone formed during that collapse, persistence without full fill, material distance below, and a later first return to the lowest meaningful boundary.
5. Use `YES`, `NO`, or `UNCERTAIN` for component questions.
6. `REJECTION_REASON` may contain semicolon-separated values from: `NOT_FORMER_LEADER`, `RUNUP_NOT_IMPULSIVE`, `COLLAPSE_NOT_MAJOR`, `GAP_TOO_SMALL_OR_LOCAL`, `GAP_OUTSIDE_MAIN_COLLAPSE`, `ZONE_NOT_PERSISTENT`, `INSUFFICIENT_DEPTH`, `WRONG_BOUNDARY_OR_REENTRY`, `ORDINARY_SIDEWAYS_GAP`, `OTHER`.
7. Do not open the private mapping during first-pass review.

All numeric construction rules are high-precision audit retrieval rules only, not strategy parameters.
"""
    v1.atomic_text(REVIEW_CSV, review.to_csv(index=False))
    v1.atomic_text(REVIEW_INSTRUCTIONS, instructions)
    v1.atomic_text(BLIND_DIR/REVIEW_CSV.name, review.to_csv(index=False))
    v1.atomic_text(BLIND_DIR/REVIEW_INSTRUCTIONS.name, instructions)


def identity_leak_count(sample: pd.DataFrame) -> int:
    leaks = 0
    for row in sample.itertuples(index=False):
        data = (BLIND_DIR/f"{row.audit_id}.png").read_bytes()
        forbidden = [
            row.symbol.encode(),
            pd.Timestamp(row.peak_date).strftime("%Y-%m-%d").encode(),
            pd.Timestamp(row.candidate_reentry_date).strftime("%Y-%m-%d").encode(),
        ]
        leaks += int(any(token in data for token in forbidden))
    return leaks


def render_report(result: dict[str, Any]) -> str:
    pool = result["candidate_pool"]
    sample = result["sample"]
    return f"""# {EXPERIMENT}

Status: `HIGH_PRECISION_PILOT_PACKAGE_COMPLETE`; `HUMAN_PATTERN_REVIEW_REQUIRED`.

The V1 120-chart workflow is stopped because the human reported very low semantic precision. Its partial review was neither read nor summarized and its artifacts remain preserved. This V2 package is a new outcome-blind 30-chart semantic pilot, not a strategy test.

## Corrected semantic clock

V1 treated any lower-boundary touch as a return. V2 treats the strict gap as unresolved until its upper boundary is fully filled. It requires five completed unfilled sessions and a 12.5% move below the lowest meaningful layer, then marks the first later intraday upward touch from below. Earlier lower-boundary touches before depth qualification are not the candidate event.

The detector also requires board-relative leader status, a strong/impulsive 60-session run-up, at least a 30% collapse, a 1-to-40-session main-collapse formation clock, negative five-session collapse momentum, and at least a 2% strict-gap width. Layer displays exclude primitives below the separate 1.5% meaningful-layer floor. A 250-session staleness guard ensures the prior peak remains visible. Every number is an audit-retrieval rule only.

## Outcome-blind support

- High-precision candidate pool: {pool['rows']} rows / {pool['symbols']} unique securities.
- Board counts: {pool['main']} Main / {pool['chinext']} ChiNext.
- Meaningful layered zones: {pool['layered']}.
- Candidate dates: {pool['first_candidate_date']} through {pool['last_candidate_date']}.

## Blind pilot

- Charts: {sample['blind_chart_count']} ({sample['main']} Main / {sample['chinext']} ChiNext).
- Unique securities: {sample['unique_symbols']}.
- Layered zones: {sample['layered']}.
- Identity/date leaks: {sample['identity_leak_count']}.
- Post-reentry bars: {sample['post_reentry_bar_count']}.
- Outcome-selected rows: {sample['outcome_selected_row_count']}.

Validation 2022–2023 and repository 2024+ data remain unopened. No return field, replay, or economic analysis was constructed.

## Next action

Human reviews only the 30 V2 blind charts and fills `{REVIEW_CSV}`. Do not continue the V1 review and do not run return analysis.
"""


def run() -> dict[str, Any]:
    inputs = validate_inputs()
    daily = build_candidate_daily()
    exact = build_exact_reentry(daily)
    pool = prepare_pool(daily, exact)
    v1.write_parquet(pool.drop(columns=["sample_hash"]), CANDIDATE_POOL)
    sample = select_sample(pool)
    build_blind_charts(sample)
    write_review_package(sample)

    mapping = sample.drop(columns=["sample_hash"])
    v1.write_parquet(mapping, AUDIT_MAPPING)
    manifest = pd.DataFrame(
        {
            "audit_id": sample.audit_id,
            "blind_chart_path": sample.audit_id.map(lambda value: str(BLIND_DIR/f"{value}.png")),
            "chart_end_time": sample.candidate_reentry_time,
            "post_reentry_bars": 0,
            "identity_fields_in_blind_metadata": 0,
        }
    )
    v1.write_parquet(manifest, SAMPLE_MANIFEST)

    blind_count = len(list(BLIND_DIR.glob("HP_*.png")))
    leaks = identity_leak_count(sample)
    if blind_count != 30 or leaks:
        raise PilotError(f"blind-package audit failure: charts={blind_count}, leaks={leaks}")
    review = pd.read_csv(REVIEW_CSV, keep_default_na=False)
    nonblank = sum((review[column].str.strip() != "").sum() for column in review.columns if column != "audit_id")
    if nonblank:
        raise PilotError("new review CSV is not blank")

    result = {
        "experiment_id": EXPERIMENT,
        "start_checkpoint": START_HEAD,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "research_type": "OUTCOME_BLIND_HIGH_PRECISION_HUMAN_PATTERN_PILOT",
        "input_identity": inputs,
        "v1_review_workflow": {
            "status": "STOPPED_INCOMPLETE_BY_AUTHORIZATION",
            "human_asked_to_finish": False,
            "partial_labels_read_or_summarized": False,
            "artifacts_preserved": True,
        },
        "candidate_pool": {
            "rows": len(pool),
            "symbols": int(pool.symbol.nunique()),
            "main": int(pool.board.eq("MAIN").sum()),
            "chinext": int(pool.board.eq("CHINEXT").sum()),
            "layered": int(pool.multi_layer.sum()),
            "first_candidate_date": str(pd.Timestamp(pool.candidate_reentry_date.min()).date()),
            "last_candidate_date": str(pd.Timestamp(pool.candidate_reentry_date.max()).date()),
        },
        "sample": {
            "blind_chart_count": blind_count,
            "main": int(sample.board.eq("MAIN").sum()),
            "chinext": int(sample.board.eq("CHINEXT").sum()),
            "unique_symbols": int(sample.symbol.nunique()),
            "layered": int(sample.multi_layer.sum()),
            "identity_leak_count": leaks,
            "post_reentry_bar_count": 0,
            "outcome_selected_row_count": 0,
            "nonblank_human_label_count": int(nonblank),
        },
        "governance": {
            "post_2021_outcome_read_count": 0,
            "validation_opened": False,
            "repository_2024_plus_data_opened": False,
            "strategy_backtest_run": False,
            "return_outcome_analysis_run": False,
        },
        "paths": {
            "blind_package": str(BLIND_DIR),
            "review_csv": str(REVIEW_CSV),
            "review_instructions": str(REVIEW_INSTRUCTIONS),
            "audit_mapping": str(AUDIT_MAPPING),
        },
        "status": {
            "high_precision_pilot_package_complete": True,
            "human_pattern_review_required": True,
            "v1_review_workflow_stopped": True,
            "strategy_backtest_run": False,
            "return_outcome_analysis_run": False,
        },
    }
    v1.atomic_json(RESULT, result)
    v1.atomic_text(REPORT, render_report(result))
    return result


if __name__ == "__main__":
    outcome = run()
    print(json.dumps({"experiment_id": outcome["experiment_id"], "candidate_pool": outcome["candidate_pool"], "sample": outcome["sample"], "status": outcome["status"]}, indent=2))
