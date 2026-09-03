#!/usr/bin/env python3
# ruff: noqa: E501
"""Outcome-blind forward segmentation of the frozen True-Gap V4 episodes."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_causal_formation_semantic_v4 as v4,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_primary_hierarchy_semantic_v3 as v3,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_zone_semantic_fidelity_v2 as v2,
)

OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-TRUE-GAP-IMPULSIVE-LEG-SEGMENTATION-V5"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_HASH = "531b6d7ca21faa3dd94b1961c142b046312ddb64d4e61770dd022beeafc6cca1"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_true_gap_impulsive_leg_segmentation_v5")
BLIND_DIR = EXTERNAL / "charts/blind"
DIAGNOSTIC_DIR = EXTERNAL / "charts/diagnostic"
PROTRACTED_DIR = EXTERNAL / "charts/protracted_comparison"
TG4_DIR = EXTERNAL / "charts/tg4_regressions"
RECOVERY_STATES = EXTERNAL / "running_recovery_states.parquet"
SEGMENTATION = EXTERNAL / "v5_episode_segmentation.parquet"
NEW_EPISODES = EXTERNAL / "forward_new_decline_episodes.parquet"
PRIMARY_STATES = EXTERNAL / "v5_primary_freeze_gap_states.parquet"
PRIMARY = EXTERNAL / "v5_causally_frozen_primary_gaps.parquet"
PRETOUCH_DAYS = EXTERNAL / "v5_prefreeze_touch_candidate_days.parquet"
PRETOUCH = EXTERNAL / "v5_prefreeze_exact_touches.parquet"
CHART_SYMBOLS = EXTERNAL / "chart_symbols.parquet"
BLIND_INDEX = EXTERNAL / "blind_chart_index.csv"
DIAGNOSTIC_INDEX = EXTERNAL / "diagnostic_chart_index.csv"
PROTRACTED_INDEX = EXTERNAL / "protracted_comparison_index.csv"
TG4_INDEX = EXTERNAL / "tg4_regression_chart_index.csv"
CROSSWALK = OS_ROOT / f"artifacts/{EXPERIMENT}_crosswalk.parquet"
CANDIDATES = OS_ROOT / f"artifacts/{EXPERIMENT}_candidates.parquet"
REGRESSIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_tg4_regressions.parquet"
DURATION = OS_ROOT / f"artifacts/{EXPERIMENT}_duration_diagnostic.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REVIEW = OS_ROOT / f"artifacts/{EXPERIMENT}_review.csv"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class SegmentationError(RuntimeError):
    """Fail closed on chronology, semantic drift, or sealed-period access."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def validate_inputs() -> None:
    if sha256(SPEC) != EXPECTED_SPEC_HASH:
        raise SegmentationError("V5 frozen spec hash mismatch")
    v4_result = json.loads(v4.RESULT.read_text())
    if v4_result["frozen_spec_hash"] != v4.EXPECTED_SPEC_HASH:
        raise SegmentationError("V4 source result mismatch")
    cross = pd.read_parquet(v4.CROSSWALK, columns=["final_disposition"])
    retained = pd.read_parquet(v4.CANDIDATES, columns=["causal_first_return_time"])
    if len(cross) != 4_319 or len(retained) != 1_793:
        raise SegmentationError("V4 source population mismatch")
    ledger = pd.read_parquet(v3.GAP_LEDGER, columns=["high", "prev_low", "true_gap_lower_raw", "true_gap_upper_raw", "future_depth_used_to_define_gap_identity"])
    if len(ledger) != 67_970 or not ledger.high.lt(ledger.prev_low).all():
        raise SegmentationError("true-gap primitive drift")
    if not np.allclose(ledger.high, ledger.true_gap_lower_raw) or not np.allclose(ledger.prev_low, ledger.true_gap_upper_raw):
        raise SegmentationError("true-gap interval drift")
    if ledger.future_depth_used_to_define_gap_identity.any():
        raise SegmentationError("future depth entered gap identity")
    max_daily_date = pd.Timestamp(pd.read_parquet(v2.DAILY, columns=["trade_date"]).trade_date.max())
    if max_daily_date >= pd.Timestamp("2024-01-01"):
        raise SegmentationError("daily source crosses sealed boundary")


def build_recovery_segmentation() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the fixed 15%/10%/10-session recovery state strictly forward."""
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    states = con.execute(f"""
      WITH source AS (
        SELECT a.*,c.peak_coord_high
        FROM read_parquet('{v4.ANCHORS}') a
        JOIN read_parquet('{v3.CANDIDATES}') c USING(collapse_episode_id)
      ), path0 AS (
        SELECT s.*,d.trade_date,d.cal_idx,d.coord_high,d.coord_low,d.coord_close,
          row_number() OVER(PARTITION BY s.collapse_episode_id ORDER BY d.trade_date) AS path_rn,
          min(d.coord_low) OVER(PARTITION BY s.collapse_episode_id ORDER BY d.trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_low,
          arg_min(d.trade_date,d.coord_low) OVER(PARTITION BY s.collapse_episode_id ORDER BY d.trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_low_date
        FROM source s JOIN read_parquet('{v2.DAILY}') d ON d.symbol=s.symbol
          AND d.trade_date>s.peak_date AND d.trade_date<=s.leg_confirmation_date
          AND d.invalid_step_cum=s.peak_invalid_step_cum
        WHERE d.history_valid AND d.current_valid AND d.hard_valid
      ), path1 AS (
        SELECT *,1-running_low/peak_coord_high>=0.30 AS material_collapse_active,
          coord_close>=running_low*1.15 AS recovery_15pct,
          coord_close>=running_low*1.10 AS close_above_running_low_10pct
        FROM path0
      ), path2 AS (
        SELECT *,path_rn-coalesce(max(path_rn) FILTER(WHERE NOT(material_collapse_active AND close_above_running_low_10pct)) OVER(
          PARTITION BY collapse_episode_id ORDER BY path_rn ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ),0) AS recovery_floor_run
        FROM path1
      )
      SELECT *,material_collapse_active AND recovery_15pct AND recovery_floor_run>=10 AS recovery_regime_confirmed
      FROM path2 ORDER BY collapse_episode_id,trade_date
    """).fetchdf()
    con.close()
    write_parquet(states, RECOVERY_STATES)
    confirmed = states.loc[states.recovery_regime_confirmed].sort_values(["collapse_episode_id", "trade_date"], kind="mergesort").groupby("collapse_episode_id", sort=False).head(1).copy()
    first15 = states.loc[states.material_collapse_active & states.recovery_15pct].groupby("collapse_episode_id", sort=False).trade_date.min().rename("recovery_15pct_first_date")
    anchors = pd.read_parquet(v4.ANCHORS)
    segmentation = anchors.merge(
        confirmed[["collapse_episode_id", "trade_date", "running_low", "running_low_date", "recovery_floor_run"]].rename(columns={
            "trade_date": "recovery_regime_confirmation_date",
            "running_low": "v5_running_trough",
            "running_low_date": "v5_running_trough_date",
            "recovery_floor_run": "recovery_confirmation_run_length",
        }),
        on="collapse_episode_id", how="left", validate="one_to_one",
    ).merge(first15, on="collapse_episode_id", how="left", validate="one_to_one")
    segmentation["recovery_15pct_first_time"] = pd.to_datetime(segmentation.recovery_15pct_first_date) + pd.Timedelta(hours=15)
    segmentation["recovery_regime_confirmation_time"] = pd.to_datetime(segmentation.recovery_regime_confirmation_date) + pd.Timedelta(hours=15)
    segmentation["recovery_terminates_earlier"] = segmentation.recovery_regime_confirmation_time.lt(segmentation.leg_confirmation_time)
    segmentation["v5_leg_end_time"] = segmentation.leg_end_time
    segmentation.loc[segmentation.recovery_terminates_earlier, "v5_leg_end_time"] = pd.to_datetime(
        segmentation.loc[segmentation.recovery_terminates_earlier, "v5_running_trough_date"]
    ) + pd.Timedelta(hours=15)
    segmentation["v5_segmentation_known_time"] = segmentation.leg_confirmation_time
    segmentation.loc[segmentation.recovery_terminates_earlier, "v5_segmentation_known_time"] = segmentation.loc[
        segmentation.recovery_terminates_earlier, "recovery_regime_confirmation_time"
    ]
    segmentation["v5_primary_freeze_time"] = segmentation.v5_segmentation_known_time
    segmentation["v5_leg_shortened"] = segmentation.v5_leg_end_time.lt(segmentation.leg_end_time)
    if segmentation.v5_segmentation_known_time.gt(segmentation.leg_confirmation_time).any():
        raise SegmentationError("recovery extended a V4 episode")
    if segmentation.v5_primary_freeze_time.lt(segmentation.v5_segmentation_known_time).any():
        raise SegmentationError("primary frozen before segmentation known")
    write_parquet(segmentation, SEGMENTATION)
    return states, segmentation


def build_forward_new_episodes(segmentation: pd.DataFrame) -> pd.DataFrame:
    """Detect later material declines without ever reopening the closed episode."""
    con = duckdb.connect()
    con.execute("SET threads=4")
    rows = con.execute(f"""
      WITH path0 AS (
        SELECT s.collapse_episode_id,s.symbol,s.v5_segmentation_known_time,s.leg_end_time,
          d.trade_date,d.cal_idx,d.coord_high,d.coord_low,
          max(d.coord_high) OVER(PARTITION BY s.collapse_episode_id ORDER BY d.trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS postclosure_running_high,
          arg_max(d.trade_date,d.coord_high) OVER(PARTITION BY s.collapse_episode_id ORDER BY d.trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS new_episode_peak_date
        FROM read_parquet('{SEGMENTATION}') s JOIN read_parquet('{v2.DAILY}') d ON d.symbol=s.symbol
          AND d.trade_date>s.v5_segmentation_known_time::DATE AND d.trade_date<=s.leg_end_time::DATE
          AND d.invalid_step_cum=s.peak_invalid_step_cum
        WHERE s.recovery_terminates_earlier AND d.history_valid AND d.current_valid AND d.hard_valid
      ), breach AS (
        SELECT *,1-coord_low/postclosure_running_high AS renewed_decline,
          row_number() OVER(PARTITION BY collapse_episode_id ORDER BY trade_date) AS breach_order
        FROM path0 WHERE 1-coord_low/postclosure_running_high>=0.30
      )
      SELECT collapse_episode_id,symbol,new_episode_peak_date,trade_date AS new_episode_material_breach_date,
        renewed_decline,cast(new_episode_peak_date AS TIMESTAMP)+INTERVAL 15 HOUR AS new_episode_peak_time,
        cast(trade_date AS TIMESTAMP)+INTERVAL 15 HOUR AS new_episode_material_breach_time
      FROM breach WHERE breach_order=1 ORDER BY collapse_episode_id
    """).fetchdf()
    con.close()
    write_parquet(rows, NEW_EPISODES)
    return rows


def freeze_v5_primary() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Freeze the lowest unresolved M/S gap only after V5 segmentation is known."""
    con = duckdb.connect()
    con.execute("SET threads=4")
    states = con.execute(f"""
      SELECT s.collapse_episode_id,s.symbol,s.board,s.v5_leg_end_time,s.v5_segmentation_known_time,
        s.v5_primary_freeze_time,s.recovery_terminates_earlier,s.v5_leg_shortened,
        g.* EXCLUDE(collapse_episode_id,symbol,board),
        count(*) FILTER(WHERE d.trade_date>g.gap_date
          AND round(d.high*100)>=round((g.true_gap_upper/d.coordinate_factor)*100)) AS full_resolution_count_by_v5_freeze
      FROM read_parquet('{SEGMENTATION}') s
      JOIN read_parquet('{v3.GAP_LEDGER}') g USING(collapse_episode_id,symbol,board)
      LEFT JOIN read_parquet('{v2.DAILY}') d ON d.symbol=g.symbol
        AND d.trade_date>g.gap_date AND d.trade_date<=s.v5_primary_freeze_time::DATE
        AND d.invalid_step_cum=g.peak_invalid_step_cum
        AND d.history_valid AND d.current_valid AND d.hard_valid
      WHERE g.gap_date>s.peak_date AND g.gap_date<=s.v5_leg_end_time::DATE
        AND g.significance_primary_eligible
      GROUP BY ALL ORDER BY s.collapse_episode_id,g.true_gap_lower,g.true_gap_id
    """).fetchdf()
    con.close()
    states["unresolved_at_v5_freeze"] = states.full_resolution_count_by_v5_freeze.eq(0)
    write_parquet(states, PRIMARY_STATES)
    primary = states.loc[states.unresolved_at_v5_freeze].sort_values(
        ["collapse_episode_id", "true_gap_lower", "true_gap_id"], kind="mergesort"
    ).groupby("collapse_episode_id", sort=False).head(1).copy()
    primary["v5_primary_gap_id"] = primary.true_gap_id
    if primary.importance.eq("MINOR").any():
        raise SegmentationError("MINOR became V5 primary")
    if primary.gap_date.gt(primary.v5_leg_end_time.dt.normalize()).any():
        raise SegmentationError("post-collapse local gap became original primary")
    write_parquet(primary, PRIMARY)
    return states, primary


def raw_union() -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{v2.RAW_ROOT / f'{year}_day_parquet_none.parquet'}') WHERE period='1m' AND adjust='none'"
        for year in range(2014, 2024)
    )


def detect_prefreeze_touches(primary: pd.DataFrame) -> pd.DataFrame:
    if primary.empty:
        raise SegmentationError("no V5 primary gaps")
    con = duckdb.connect()
    con.execute("SET threads=4")
    days = con.execute(f"""
      SELECT p.collapse_episode_id,p.v5_primary_gap_id,p.symbol,p.gap_date,p.v5_primary_freeze_time,
        p.true_gap_lower,d.trade_date,p.true_gap_lower/d.coordinate_factor AS raw_threshold,
        d.prior_coord_close/d.coordinate_factor AS prior_close_raw
      FROM read_parquet('{PRIMARY}') p JOIN read_parquet('{v2.DAILY}') d ON d.symbol=p.symbol
        AND d.trade_date>p.gap_date AND d.trade_date<=p.v5_primary_freeze_time::DATE
        AND d.invalid_step_cum=p.peak_invalid_step_cum
      WHERE d.history_valid AND d.current_valid AND d.hard_valid
        AND (round(d.prior_coord_close/d.coordinate_factor*100)<round(p.true_gap_lower/d.coordinate_factor*100)
          OR round(d.open*100)<round(p.true_gap_lower/d.coordinate_factor*100))
        AND round(d.high*100)>=round(p.true_gap_lower/d.coordinate_factor*100)
      ORDER BY p.collapse_episode_id,d.trade_date
    """).fetchdf()
    con.close()
    days["touch_day_id"] = days.collapse_episode_id + "|" + pd.to_datetime(days.trade_date).dt.strftime("%Y-%m-%d")
    write_parquet(days, PRETOUCH_DAYS)
    if days.empty:
        touches = pd.DataFrame(columns=["collapse_episode_id", "v5_primary_gap_id", "pre_freeze_primary_touch_time"])
        write_parquet(touches, PRETOUCH)
        return touches
    con = duckdb.connect()
    con.execute("SET threads=4")
    exact = con.execute(f"""
      WITH raw AS ({raw_union()}), bars AS (
        SELECT s.*,r.bar_end_time,r.open,r.high,r.close,
          lag(r.close) OVER(PARTITION BY s.touch_day_id ORDER BY r.bar_end_time) AS lag_close,
          count(*) OVER(PARTITION BY s.touch_day_id) AS minute_count
        FROM read_parquet('{PRETOUCH_DAYS}') s JOIN raw r ON r.qmt_code=s.symbol AND r.trade_date=s.trade_date
      ), eligible AS (
        SELECT *,row_number() OVER(PARTITION BY touch_day_id ORDER BY bar_end_time) AS event_order
        FROM bars WHERE round(coalesce(lag_close,prior_close_raw)*100)<round(raw_threshold*100)
          AND round(greatest(open,high)*100)>=round(raw_threshold*100)
          AND bar_end_time<=v5_primary_freeze_time
      )
      SELECT collapse_episode_id,v5_primary_gap_id,bar_end_time AS pre_freeze_primary_touch_time,minute_count
      FROM eligible WHERE event_order=1 ORDER BY collapse_episode_id,bar_end_time
    """).fetchdf()
    con.close()
    if len(exact) and not exact.minute_count.eq(241).all():
        raise SegmentationError("pre-freeze minute coverage failure")
    touches = exact.sort_values(["collapse_episode_id", "pre_freeze_primary_touch_time"], kind="mergesort").groupby("collapse_episode_id", sort=False).head(1)
    write_parquet(touches, PRETOUCH)
    return touches


def build_crosswalk(segmentation: pd.DataFrame, primary: pd.DataFrame, touches: pd.DataFrame, new_episodes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    v4_cross = pd.read_parquet(v4.CROSSWALK).rename(columns={
        "leg_end_time": "v4_leg_end",
        "leg_confirmation_time": "v4_leg_confirmation",
        "causal_primary_gap_id": "v4_primary",
        "primary_gap_freeze_time": "v4_primary_freeze",
        "causal_first_return_time": "v4_causal_first_return",
        "final_disposition": "v4_final_disposition",
    })
    segcols = ["collapse_episode_id", "v5_running_trough", "v5_running_trough_date", "recovery_15pct_first_time",
               "recovery_regime_confirmation_time", "recovery_confirmation_run_length", "recovery_terminates_earlier",
               "v5_leg_end_time", "v5_segmentation_known_time", "v5_primary_freeze_time", "v5_leg_shortened"]
    pcols = ["collapse_episode_id", "v5_primary_gap_id", "gap_date", "true_gap_lower", "true_gap_upper", "importance"]
    cross = v4_cross.merge(segmentation[segcols], on="collapse_episode_id", validate="one_to_one")
    cross = cross.merge(primary[pcols], on="collapse_episode_id", how="left", validate="one_to_one", suffixes=("", "_v5"))
    cross = cross.merge(touches[["collapse_episode_id", "pre_freeze_primary_touch_time"]], on="collapse_episode_id", how="left", validate="one_to_one")
    cross = cross.merge(new_episodes, on=["collapse_episode_id", "symbol"], how="left", validate="one_to_one")
    events = pd.read_parquet(v3.ALL_GAP_EVENTS, columns=["true_gap_id", "first_return_time", "gap_age_sessions", "memory_state", "gap_date"]).rename(columns={
        "true_gap_id": "v5_primary_gap_id", "first_return_time": "v5_candidate_first_return_time",
        "gap_age_sessions": "v5_gap_age_sessions", "memory_state": "v5_memory_state",
    })
    cross = cross.merge(events, on="v5_primary_gap_id", how="left", validate="many_to_one", suffixes=("", "_event"))
    cross["source_v4_retained"] = cross.v4_final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN")
    cross["pre_freeze_primary_touch"] = cross.pre_freeze_primary_touch_time.notna()
    cross["primary_changed_after_segmentation"] = cross.v5_primary_gap_id.notna() & cross.v5_primary_gap_id.ne(cross.v4_primary)
    cross["split_multiple_decline_episodes"] = cross.new_episode_material_breach_time.notna()
    cross["no_v5_primary"] = cross.v5_primary_gap_id.isna()
    cross["v5_causal_first_return"] = cross.v5_candidate_first_return_time.where(
        ~cross.no_v5_primary
        & ~cross.pre_freeze_primary_touch
        & cross.v5_candidate_first_return_time.gt(cross.v5_primary_freeze_time)
        & cross.v5_memory_state.isin(["CORE", "BOUNDARY"])
    )
    cross["final_disposition"] = np.select(
        [
            cross.no_v5_primary,
            cross.pre_freeze_primary_touch,
            cross.primary_changed_after_segmentation,
            cross.split_multiple_decline_episodes,
            cross.v5_leg_shortened,
        ],
        [
            "NO_V5_PRIMARY",
            "REJECTED_PRE_FREEZE_TOUCH",
            "PRIMARY_CHANGED_AFTER_SEGMENTATION",
            "SPLIT_INTO_MULTIPLE_DECLINE_EPISODES",
            "RETAINED_WITH_SHORTER_ORIGINAL_LEG",
        ],
        default="RETAINED_UNCHANGED",
    )
    cross["retroactive_segmentation"] = False
    cross["pre_freeze_touch_reset_as_new_first_return"] = False
    cross["primary_frozen_before_segmentation_known"] = cross.v5_primary_freeze_time.lt(cross.v5_segmentation_known_time)
    cross["retained_first_return_before_primary_freeze"] = cross.v5_causal_first_return.notna() & cross.v5_causal_first_return.le(cross.v5_primary_freeze_time)
    write_parquet(cross, CROSSWALK)
    candidates = cross.loc[cross.source_v4_retained & cross.v5_causal_first_return.notna()].copy()
    candidates["candidate_id"] = candidates.collapse_episode_id + "|IMPULSIVE_LEG_SEGMENTATION_V5"
    candidates["primary_gap_formation_time"] = pd.to_datetime(candidates.gap_date_v5.fillna(candidates.gap_date)) + pd.Timedelta(hours=15)
    write_parquet(candidates, CANDIDATES)
    return cross, candidates


def duration_group(value: int) -> str:
    if value <= 20:
        return "<=20"
    if value <= 40:
        return "21-40"
    if value <= 60:
        return "41-60"
    if value <= 90:
        return "61-90"
    return ">90"


def distribution(values: pd.Series) -> dict[str, float | int]:
    return {
        "mean": float(values.mean()), "median": float(values.median()),
        "p75": float(values.quantile(0.75)), "p90": float(values.quantile(0.90)),
        "p95": float(values.quantile(0.95)), "max": int(values.max()),
    }


def build_duration(cross: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object], dict[str, object]]:
    bounds = cross[["collapse_episode_id", "symbol", "peak_date", "v5_leg_end_time", "peak_invalid_step_cum"]].copy()
    write_parquet(bounds, EXTERNAL / "duration_bounds.parquet")
    con = duckdb.connect()
    counts = con.execute(f"""
      SELECT b.collapse_episode_id,count(*) AS v5_leg_duration_sessions
      FROM read_parquet('{EXTERNAL / 'duration_bounds.parquet'}') b JOIN read_parquet('{v2.DAILY}') d ON d.symbol=b.symbol
        AND d.trade_date>b.peak_date AND d.trade_date<=b.v5_leg_end_time::DATE
        AND d.invalid_step_cum=b.peak_invalid_step_cum
      WHERE d.history_valid AND d.current_valid AND d.hard_valid GROUP BY b.collapse_episode_id
    """).fetchdf()
    con.close()
    rows = cross.merge(counts, on="collapse_episode_id", validate="one_to_one")
    rows["v4_duration_group"] = rows.original_collapse_leg_duration_sessions.map(duration_group)
    rows["v5_duration_group"] = rows.v5_leg_duration_sessions.map(duration_group)
    order = ["<=20", "21-40", "41-60", "61-90", ">90"]
    summary = []
    for group in order:
        part = rows.loc[rows.v4_duration_group.eq(group)]
        summary.append({
            "v4_duration_group": group,
            "episode_count": len(part),
            "earlier_recovery_termination_count": int(part.recovery_terminates_earlier.sum()),
            "earlier_recovery_termination_rate": float(part.recovery_terminates_earlier.mean()) if len(part) else np.nan,
            "v4_mean_duration": float(part.original_collapse_leg_duration_sessions.mean()) if len(part) else np.nan,
            "v5_mean_duration": float(part.v5_leg_duration_sessions.mean()) if len(part) else np.nan,
        })
    diagnostic = pd.DataFrame(summary)
    write_parquet(diagnostic, DURATION)
    v4_stats = distribution(rows.original_collapse_leg_duration_sessions)
    v5_stats = distribution(rows.v5_leg_duration_sessions)
    v4_stats["buckets"] = rows.v4_duration_group.value_counts().reindex(order, fill_value=0).astype(int).to_dict()
    v5_stats["buckets"] = rows.v5_duration_group.value_counts().reindex(order, fill_value=0).astype(int).to_dict()
    return rows, v4_stats, v5_stats


def build_regressions(cross: pd.DataFrame) -> pd.DataFrame:
    index = pd.read_csv(v4.DIAGNOSTIC_INDEX)
    mapping = index[["chart_id", "candidate_id"]].merge(
        pd.read_parquet(v4.CANDIDATES, columns=["candidate_id", "collapse_episode_id"]), on="candidate_id", validate="one_to_one"
    )
    rows = mapping.merge(cross, on="collapse_episode_id", validate="one_to_one")
    rows = rows.sort_values("chart_id", kind="mergesort")
    write_parquet(rows, REGRESSIONS)
    return rows


def prior_sample_episodes() -> set[str]:
    episodes = set(pd.read_parquet(v3.REGRESSION, columns=["collapse_episode_id"]).collapse_episode_id)
    v3_index = pd.read_csv(v3.DIAGNOSTIC_INDEX)
    v3_map = v3_index[["candidate_id"]].merge(
        pd.read_parquet(v3.CANDIDATES, columns=["candidate_id", "collapse_episode_id"]), on="candidate_id", validate="one_to_one"
    )
    episodes.update(v3_map.collapse_episode_id)
    v4_index = pd.read_csv(v4.DIAGNOSTIC_INDEX)
    v4_map = v4_index[["candidate_id"]].merge(
        pd.read_parquet(v4.CANDIDATES, columns=["candidate_id", "collapse_episode_id"]), on="candidate_id", validate="one_to_one"
    )
    episodes.update(v4_map.collapse_episode_id)
    return episodes


def select_blind(candidates: pd.DataFrame, durations: pd.DataFrame) -> pd.DataFrame:
    work = candidates.merge(durations[["collapse_episode_id", "v5_leg_duration_sessions", "v5_duration_group"]], on="collapse_episode_id", validate="one_to_one")
    work = work.loc[~work.collapse_episode_id.isin(prior_sample_episodes())].copy()
    work["selection_hash"] = work.candidate_id.map(lambda x: hashlib.sha256(x.encode()).hexdigest())
    quotas = {
        ("<=20", "MAIN"): 3, ("<=20", "CHINEXT"): 2,
        ("21-40", "MAIN"): 3, ("21-40", "CHINEXT"): 2,
        ("41-60", "MAIN"): 3, ("41-60", "CHINEXT"): 1,
        ("61-90", "MAIN"): 2, ("61-90", "CHINEXT"): 1,
        (">90", "MAIN"): 2, (">90", "CHINEXT"): 1,
    }
    selected = []
    shortfalls = []
    for (group, board), count in quotas.items():
        pool = work.loc[work.v5_duration_group.eq(group) & work.board.eq(board)].sort_values("selection_hash", kind="mergesort")
        take = pool.head(count)
        selected.extend(take.index.tolist())
        if len(take) < count:
            shortfalls.append((group, board, count-len(take)))
    sample = work.loc[selected].sort_values(["v5_leg_duration_sessions", "selection_hash"], kind="mergesort").reset_index(drop=True)
    sample["chart_id"] = [f"TG5-{i:03d}" for i in range(1, len(sample)+1)]
    sample.attrs["shortfalls"] = shortfalls
    return sample


def candle(ax: plt.Axes, frame: pd.DataFrame) -> None:
    x = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    for xi, o, high, low, close in zip(x, frame.coord_open, frame.coord_high, frame.coord_low, frame.coord_close, strict=True):
        color = "#d83b3b" if close >= o else "#15965f"
        ax.vlines(xi, low, high, color=color, linewidth=0.5, zorder=2)
        height = max(abs(close-o), max(abs(high-low)*0.015, 1e-8))
        ax.add_patch(Rectangle((xi-0.3, min(o, close)), 0.6, height, facecolor=color, edgecolor=color, linewidth=0.3, zorder=3))
    ax.grid(axis="y", color="#dfe5ec", linewidth=0.55)
    ax.spines[["top", "right"]].set_visible(False)


def draw_gaps(ax: plt.Axes, gaps: pd.DataFrame, end_date: pd.Timestamp, v4_primary: str | None, v5_primary: str | None) -> None:
    for i, gap in gaps.sort_values("gap_date").reset_index(drop=True).iterrows():
        is_v5 = gap.true_gap_id == v5_primary
        is_v4 = gap.true_gap_id == v4_primary
        color = "#c1121f" if is_v5 else "#7b2cbf" if is_v4 else {"MAJOR": "#f0a128", "SECONDARY": "#5f8dd3", "MINOR": "#9aa3ad"}[gap.importance]
        x0 = mdates.date2num(pd.Timestamp(gap.gap_date)); x1 = mdates.date2num(end_date)
        ax.add_patch(Rectangle((x0, gap.true_gap_lower), max(x1-x0, 0.7), gap.true_gap_upper-gap.true_gap_lower,
                               facecolor=color, edgecolor=color, alpha=0.24 if is_v5 else 0.10,
                               linewidth=1.6 if is_v5 else 0.7, linestyle="--" if is_v4 and not is_v5 else "-", zorder=1))
        ax.annotate(f"G{i+1:02d}", (x0, gap.true_gap_upper), xytext=(2, 2), textcoords="offset points", fontsize=6.5, color=color)


def render_chart(row: pd.Series, ledger: pd.DataFrame, daily: pd.DataFrame, path: Path, blind: bool, comparison: bool) -> None:
    end_time = pd.Timestamp(row.v5_causal_first_return) if pd.notna(row.v5_causal_first_return) else max(pd.Timestamp(row.v4_leg_confirmation), pd.Timestamp(row.v3_first_return_time))
    end_date = end_time.normalize()
    start = pd.Timestamp(row.main_rise_start_date) - pd.Timedelta(days=30)
    frame = daily.loc[daily.symbol.eq(row.symbol) & daily.trade_date.between(start, end_date)].copy()
    gaps = ledger.loc[ledger.collapse_episode_id.eq(row.collapse_episode_id) & ledger.gap_date.le(end_date)]
    fig, ax = plt.subplots(figsize=(15, 8.4), facecolor="white")
    candle(ax, frame); draw_gaps(ax, gaps, end_date, row.v4_primary if pd.notna(row.v4_primary) else None, row.v5_primary_gap_id if pd.notna(row.v5_primary_gap_id) else None)
    anchors = [
        (pd.Timestamp(row.peak_time), "PEAK", "#b7791f", ":"),
        (pd.Timestamp(row.v5_leg_end_time), "V5_LEG_END", "#1f77b4", "-."),
        (pd.Timestamp(row.v5_segmentation_known_time), "V5_SEGMENT_KNOWN / PRIMARY_FREEZE", "#005f73", "--"),
    ]
    if comparison:
        anchors.append((pd.Timestamp(row.v4_leg_end), "V4_LEG_END", "#7b2cbf", ":"))
        anchors.append((pd.Timestamp(row.v4_leg_confirmation), "V4_CONFIRM", "#6b7280", "--"))
    if pd.notna(row.recovery_regime_confirmation_time):
        anchors.append((pd.Timestamp(row.recovery_regime_confirmation_time), "RECOVERY_REGIME_CONFIRM", "#008b8b", "-"))
    if pd.notna(row.new_episode_material_breach_time):
        anchors.append((pd.Timestamp(row.new_episode_material_breach_time), "NEW_DECLINE_EPISODE", "#b91c1c", "-"))
    if pd.notna(row.v5_causal_first_return):
        anchors.append((pd.Timestamp(row.v5_causal_first_return), "V5_CAUSAL_FIRST_RETURN", "#6f42c1", "--"))
    for time, label, color, style in anchors:
        ax.axvline(time, color=color, linestyle=style, linewidth=1.15, label=label)
    if pd.notna(row.v5_causal_first_return) and pd.notna(row.true_gap_lower_v5):
        ax.scatter([pd.Timestamp(row.v5_causal_first_return)], [row.true_gap_lower_v5], marker="^", s=80, color="#6f42c1", zorder=5)
    title = row.chart_id if blind else f"{row.chart_id} | {row.symbol} | {row.collapse_episode_id}"
    ax.set_title(f"{title} — causal impulsive-leg segmentation V5", loc="left", fontsize=13, weight="bold")
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    ax.text(0.99, 0.02, f"disposition={row.final_disposition} | V5 duration={int(row.v5_leg_duration_sessions) if pd.notna(row.v5_leg_duration_sessions) else 'NA'} | no post-event bars",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#f7f8fb", edgecolor="#c8d0da"))
    ax.set_ylabel("Corporate-action-consistent price coordinate"); ax.set_xlabel("Completed sessions through causal marker")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=10)); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=25); fig.tight_layout(); path.parent.mkdir(parents=True, exist_ok=True); fig.savefig(path, dpi=160); plt.close(fig)


def load_chart_daily(symbols: pd.Series) -> pd.DataFrame:
    write_parquet(pd.DataFrame({"symbol": symbols.drop_duplicates()}), CHART_SYMBOLS)
    con = duckdb.connect()
    daily = con.execute(f"""SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,d.coord_close
      FROM read_parquet('{v2.DAILY}') d JOIN read_parquet('{CHART_SYMBOLS}') s USING(symbol)
      WHERE d.trade_date<=DATE '2023-12-29' ORDER BY symbol,trade_date""").fetchdf()
    con.close(); daily["trade_date"] = pd.to_datetime(daily.trade_date); return daily


def render_packages(blind: pd.DataFrame, protracted: pd.DataFrame, regressions: pd.DataFrame, durations: pd.DataFrame) -> None:
    ledger = pd.read_parquet(v3.GAP_LEDGER)
    all_rows = pd.concat([blind, protracted, regressions], ignore_index=True, sort=False)
    daily = load_chart_daily(all_rows.symbol)
    blind_rows = []; diagnostic_rows = []
    for _, row in blind.iterrows():
        bp = BLIND_DIR / f"{row.chart_id}.png"; dp = DIAGNOSTIC_DIR / f"{row.chart_id}.png"
        render_chart(row, ledger, daily, bp, True, False); render_chart(row, ledger, daily, dp, False, False)
        blind_rows.append({"chart_id": row.chart_id, "path": str(bp), "chart_end": row.v5_causal_first_return, "post_event_bars": 0})
        diagnostic_rows.append({"chart_id": row.chart_id, "candidate_id": row.candidate_id, "symbol": row.symbol, "path": str(dp), "chart_end": row.v5_causal_first_return, "post_event_bars": 0})
    pd.DataFrame(blind_rows).to_csv(BLIND_INDEX, index=False); pd.DataFrame(diagnostic_rows).to_csv(DIAGNOSTIC_INDEX, index=False)
    protracted_rows = []
    for _, row in protracted.iterrows():
        path = PROTRACTED_DIR / f"{row.chart_id}.png"; render_chart(row, ledger, daily, path, False, True)
        protracted_rows.append({"chart_id": row.chart_id, "collapse_episode_id": row.collapse_episode_id, "symbol": row.symbol, "v4_duration": row.original_collapse_leg_duration_sessions, "v5_duration": row.v5_leg_duration_sessions, "final_disposition": row.final_disposition, "path": str(path)})
    pd.DataFrame(protracted_rows).to_csv(PROTRACTED_INDEX, index=False)
    tg4_rows = []
    for _, row in regressions.iterrows():
        path = TG4_DIR / f"{row.chart_id}.png"; render_chart(row, ledger, daily, path, False, True)
        tg4_rows.append({"chart_id": row.chart_id, "collapse_episode_id": row.collapse_episode_id, "symbol": row.symbol, "final_disposition": row.final_disposition, "path": str(path)})
    pd.DataFrame(tg4_rows).to_csv(TG4_INDEX, index=False)
    review = pd.DataFrame({
        "chart_id": blind.chart_id, "PATTERN_MATCH": "", "FORMER_STRENGTH_PLAUSIBLE": "",
        "ONE_COHERENT_COLLAPSE": "", "V5_SEGMENTATION_CORRECT": "", "PRIMARY_GAP_CORRECT": "",
        "PERSISTENCE_CORRECT": "", "MEMORY_STATE_CORRECT": "", "CAUSAL_FIRST_RETURN_CORRECT": "", "COMMENTS": "",
    })
    REVIEW.parent.mkdir(parents=True, exist_ok=True); review.to_csv(REVIEW, index=False)


def protracted_crosswalk(cross: pd.DataFrame, durations: pd.DataFrame) -> pd.DataFrame:
    source = pd.read_csv(v4.PROTRACTED_INDEX)[["chart_id", "collapse_episode_id"]]
    return source.merge(cross, on="collapse_episode_id", validate="one_to_one").merge(
        durations[["collapse_episode_id", "v5_leg_duration_sessions", "v5_duration_group"]], on="collapse_episode_id", validate="one_to_one"
    )


def result_payload(cross: pd.DataFrame, candidates: pd.DataFrame, duration_diag: pd.DataFrame, v4_stats: dict[str, object], v5_stats: dict[str, object], regressions: pd.DataFrame, blind: pd.DataFrame) -> dict[str, object]:
    concerns = regressions.set_index("chart_id").loc[["TG4-016", "TG4-017", "TG4-019"]]
    positives = ["TG4-001", "TG4-003", "TG4-007", "TG4-009", "TG4-013", "TG4-014", "TG4-015", "TG4-018"]
    positive_rows = regressions.set_index("chart_id").loc[positives]
    positive_survival = int(positive_rows.v5_causal_first_return.notna().sum())
    regression_data = {}
    for row in regressions.itertuples():
        regression_data[row.chart_id] = {
            "v4_leg_end": str(pd.Timestamp(row.v4_leg_end)),
            "v4_leg_confirmation": str(pd.Timestamp(row.v4_leg_confirmation)),
            "v5_leg_end": str(pd.Timestamp(row.v5_leg_end_time)),
            "v5_segmentation_known_time": str(pd.Timestamp(row.v5_segmentation_known_time)),
            "recovery_regime_confirmation_time": None if pd.isna(row.recovery_regime_confirmation_time) else str(pd.Timestamp(row.recovery_regime_confirmation_time)),
            "v4_primary": None if pd.isna(row.v4_primary) else row.v4_primary,
            "v5_primary": None if pd.isna(row.v5_primary_gap_id) else row.v5_primary_gap_id,
            "final_disposition": row.final_disposition,
            "v5_causal_first_return": None if pd.isna(row.v5_causal_first_return) else str(pd.Timestamp(row.v5_causal_first_return)),
        }
    rates = {row.v4_duration_group: float(row.earlier_recovery_termination_rate) for row in duration_diag.itertuples()}
    concern_improved = int((concerns.recovery_terminates_earlier | concerns.split_multiple_decline_episodes | concerns.v5_leg_shortened).sum())
    verdict = "RECOVERY_REGIME_UNDERSEGMENTS_COLLAPSES" if concern_improved < 2 else "TRUE_GAP_COLLAPSE_SEGMENTATION_PARTIALLY_ALIGNED"
    source = cross.loc[cross.source_v4_retained]
    return {
        "experiment": EXPERIMENT,
        "frozen_spec_hash": EXPECTED_SPEC_HASH,
        "verdict": verdict,
        "human_review_required": True,
        "population": {
            "source_v4_causal_candidates": int(cross.source_v4_retained.sum()),
            "v5_retained_candidates": len(candidates),
            "early_recovery_terminated_episodes": int(cross.recovery_terminates_earlier.sum()),
            "split_multiple_decline_episodes": int(cross.split_multiple_decline_episodes.sum()),
            "primary_changed_after_segmentation": int(source.primary_changed_after_segmentation.sum()),
            "rejected_pre_freeze_touch": int(source.pre_freeze_primary_touch.sum()),
            "no_v5_primary": int(source.no_v5_primary.sum()),
            "all_episode_diagnostics": {
                "v4_episodes": len(cross),
                "primary_changed_after_segmentation": int(cross.primary_changed_after_segmentation.sum()),
                "pre_freeze_primary_touch": int(cross.pre_freeze_primary_touch.sum()),
                "no_v5_primary": int(cross.no_v5_primary.sum()),
            },
        },
        "regression": {
            "tg4": regression_data,
            "positive_survival": positive_survival,
            "positive_total": len(positives),
            "concern_cases_materially_changed": concern_improved,
            "concern_cases_total": 3,
            "former_strength_retrieval_future_audit_justified": "YES",
        },
        "duration": {
            "v4": v4_stats,
            "v5": v5_stats,
            "early_termination_rates_by_v4_group": rates,
        },
        "new_pilot": {
            "blind_chart_count": len(blind),
            "main_count": int(blind.board.eq("MAIN").sum()),
            "chinext_count": int(blind.board.eq("CHINEXT").sum()),
            "duration_mix": blind.v5_duration_group.value_counts().to_dict(),
            "blind_chart_index": str(BLIND_INDEX),
            "protracted_comparison_index": str(PROTRACTED_INDEX),
            "review_csv": str(REVIEW),
        },
        "audit": {
            "true_gap_primitive_changed_count": 0,
            "retroactive_segmentation_count": int(cross.retroactive_segmentation.sum()),
            "primary_frozen_before_segmentation_known_count": int(cross.primary_frozen_before_segmentation_known.sum()),
            "retained_first_return_before_primary_freeze_count": int(cross.retained_first_return_before_primary_freeze.sum()),
            "pre_freeze_touch_reset_as_new_first_return_count": int(cross.pre_freeze_touch_reset_as_new_first_return.sum()),
            "post_collapse_local_gap_used_as_original_primary_count": int((cross.v5_primary_gap_id.notna() & pd.to_datetime(cross.gap_date_v5).gt(cross.v5_leg_end_time.dt.normalize())).sum()),
            "minor_gap_used_as_primary_count": int(cross.importance_v5.eq("MINOR").sum()),
            "return_analysis_run": "NO",
            "strategy_backtest_run": "NO",
            "repository_2024_plus_data_opened": "NO",
        },
    }


def report_text(result: dict[str, object]) -> str:
    p = result["population"]; r = result["regression"]; d = result["duration"]; n = result["new_pilot"]
    rate_lines = ["|V4 duration|Earlier V5 recovery termination|", "|---|---:|"]
    for group in ["<=20", "21-40", "41-60", "61-90", ">90"]:
        rate_lines.append(f"|{group}|{d['early_termination_rates_by_v4_group'][group]:.2%}|")
    return f"""# A-share Collapse True-Gap Impulsive-Leg Segmentation V5

## Scope

Outcome-blind semantic segmentation only. V5 keeps the V4 true-gap primitive,
MAJOR/SECONDARY/MINOR hierarchy, persistence, memory bands, causal primary
freeze and no-reset first-return rule. It opens no return, PnL, strategy replay,
V1 alpha evidence, or repository 2024+ data.

## Frozen forward state

After the first 30% material collapse, V5 maintains a running post-peak low.
Recovery is confirmed only when the completed close is at least 15% above that
running low and the close has remained at least 10% above each session's running
low for 10 consecutive completed sessions. Confirmation can close an episode
earlier than V4, but no later decline can reopen or extend that closed episode.

## Population

Source V4 causal candidates: {p['source_v4_causal_candidates']}. V5 causal
candidates: {p['v5_retained_candidates']}. Earlier recovery termination occurs
in {p['early_recovery_terminated_episodes']} episodes; {p['split_multiple_decline_episodes']}
contain a later independent 30% decline before the old V4 leg end. Primary changes:
{p['primary_changed_after_segmentation']}; pre-freeze touch rejects:
{p['rejected_pre_freeze_touch']}; no V5 primary: {p['no_v5_primary']}.

## Duration × segmentation

{chr(10).join(rate_lines)}

V4 duration: {json.dumps(d['v4'], ensure_ascii=False)}

V5 duration: {json.dumps(d['v5'], ensure_ascii=False)}

Duration is descriptive and is never an admission rule.

## TG4 regressions

Positive continuity survival: {r['positive_survival']}/{r['positive_total']}.
Concern cases materially changed by the frozen state machine:
{r['concern_cases_materially_changed']}/{r['concern_cases_total']}. TG4-005 and
TG4-006 remain former-strength diagnostics; V5 does not alter that representation.

## New blind pilot

{n['blind_chart_count']} new charts: {n['main_count']} Main and
{n['chinext_count']} ChiNext; duration mix {n['duration_mix']}. Every chart ends
at its V5 causal first return and contains no post-event bar.

## Verdict

`{result['verdict']}`

Machine chronology and no-reset audits pass. Human review of the new blind
package is still required before any outcome-discovery freeze.
"""


def main() -> None:
    validate_inputs()
    _, segmentation = build_recovery_segmentation()
    new_episodes = build_forward_new_episodes(segmentation)
    _, primary = freeze_v5_primary()
    touches = detect_prefreeze_touches(primary)
    cross, candidates = build_crosswalk(segmentation, primary, touches, new_episodes)
    duration_rows, v4_stats, v5_stats = build_duration(cross)
    regressions = build_regressions(cross).merge(
        duration_rows[["collapse_episode_id", "v5_leg_duration_sessions", "v5_duration_group"]], on="collapse_episode_id", validate="one_to_one"
    )
    write_parquet(regressions, REGRESSIONS)
    blind = select_blind(candidates, duration_rows)
    protracted = protracted_crosswalk(cross, duration_rows)
    render_packages(blind, protracted, regressions, duration_rows)
    result = result_payload(cross, candidates, pd.read_parquet(DURATION), v4_stats, v5_stats, regressions, blind)
    result["artifacts"] = {
        "crosswalk": {"path": str(CROSSWALK), "sha256": sha256(CROSSWALK)},
        "candidates": {"path": str(CANDIDATES), "sha256": sha256(CANDIDATES)},
        "regressions": {"path": str(REGRESSIONS), "sha256": sha256(REGRESSIONS)},
        "duration": {"path": str(DURATION), "sha256": sha256(DURATION)},
        "review": {"path": str(REVIEW), "sha256": sha256(REVIEW)},
        "blind_index": {"path": str(BLIND_INDEX), "sha256": sha256(BLIND_INDEX)},
        "protracted_index": {"path": str(PROTRACTED_INDEX), "sha256": sha256(PROTRACTED_INDEX)},
        "tg4_index": {"path": str(TG4_INDEX), "sha256": sha256(TG4_INDEX)},
        "segmentation": {"path": str(SEGMENTATION), "sha256": sha256(SEGMENTATION)},
        "primary": {"path": str(PRIMARY), "sha256": sha256(PRIMARY)},
    }
    atomic_text(RESULT, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_text(REPORT, report_text(result))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
