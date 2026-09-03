#!/usr/bin/env python3
# ruff: noqa: E501
"""Outcome-blind V3 primary-hierarchy semantic reconstruction."""

from __future__ import annotations

import hashlib
import json
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

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_zone_semantic_fidelity_v2 as v2,
)

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-TRUE-GAP-PRIMARY-HIERARCHY-SEMANTIC-V3"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_HASH = "938f39487820cdd35cc77891c1f770bbacc0807a78bc8f73f71b5aa34fda8c2a"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_true_gap_primary_hierarchy_semantic_v3")
BLIND_DIR = EXTERNAL / "charts/blind"
DIAGNOSTIC_DIR = EXTERNAL / "charts/diagnostic"
LEG_ENDS = EXTERNAL / "original_impulsive_collapse_leg_ends.parquet"
DAILY_CANDIDATE_DAYS = EXTERNAL / "daily_candidate_days.parquet"
ALL_GAP_EVENTS = EXTERNAL / "all_gap_first_return_events.parquet"
MINUTE_UNMATCHED = EXTERNAL / "minute_unmatched_candidate_days.parquet"
GAP_LEDGER = EXTERNAL / f"{EXPERIMENT}_gap_ledger.parquet"
CANDIDATES = OS_ROOT / f"artifacts/{EXPERIMENT}_candidates.parquet"
REGRESSION = OS_ROOT / f"artifacts/{EXPERIMENT}_regression_30.parquet"
MAPPING = OS_ROOT / f"artifacts/{EXPERIMENT}_mapping.parquet"
REVIEW = OS_ROOT / f"artifacts/{EXPERIMENT}_review.csv"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
BLIND_INDEX = EXTERNAL / "blind_chart_index.csv"
DIAGNOSTIC_INDEX = EXTERNAL / "diagnostic_chart_index.csv"


class SemanticError(RuntimeError):
    """Fail closed on semantic, lineage, sealed-period, or determinism errors."""


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


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def validate_inputs() -> None:
    if sha256(SPEC) != EXPECTED_SPEC_HASH:
        raise SemanticError("V3 frozen spec hash mismatch")
    v2.verify_v1_immutable()
    prior = json.loads(v2.RESULT.read_text())
    if prior["audit"]["return_analysis_run"] != "NO" or prior["counts"]["true_gap_primitives"] != 67_970:
        raise SemanticError("V2 semantic source identity mismatch")
    max_daily_date = pd.Timestamp(pd.read_parquet(v2.DAILY, columns=["trade_date"]).trade_date.max())
    if max_daily_date >= pd.Timestamp("2024-01-01"):
        raise SemanticError("daily source crosses sealed boundary")


def build_leg_ends() -> pd.DataFrame:
    """Apply the frozen 30% + 10-session stabilization termination rule."""
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    query = f"""
      WITH daily0 AS (
        SELECT *,row_number() OVER(PARTITION BY symbol ORDER BY trade_date) AS valid_seq,
          lag(low) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_low_raw,
          lag(close) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_close_raw,
          lag(coord_low) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_coord_low,
          lag(invalid_step_cum) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_invalid_step_cum
        FROM read_parquet('{v2.DAILY}') WHERE trade_date<=DATE '2023-12-29'
      ), path0 AS (
        SELECT e.collapse_episode_id,e.symbol,e.peak_date,e.peak_coord_high,
          e.postcollapse_low_coord,e.peak_invalid_step_cum,
          d.trade_date,d.valid_seq,d.coord_low,
          d.high<d.prev_low_raw AND d.invalid_step_cum=d.prev_invalid_step_cum AND (
            (d.prev_low_raw-d.high)/nullif(d.prev_close_raw,0)>=0.025 OR
            (d.prev_coord_low-d.coord_high)/nullif(e.peak_coord_high-e.postcollapse_low_coord,0)>=0.08
          ) AS is_major_true_gap
        FROM read_parquet('{v2.EPISODES}') e
        JOIN daily0 d ON d.symbol=e.symbol AND d.trade_date>e.peak_date
          AND d.invalid_step_cum=e.peak_invalid_step_cum
        WHERE d.history_valid AND d.current_valid AND d.hard_valid
      ), path1 AS (
        SELECT *,
          count(*) OVER(PARTITION BY collapse_episode_id ORDER BY valid_seq ROWS BETWEEN 1 FOLLOWING AND 10 FOLLOWING) AS next_session_count,
          min(coord_low) OVER(PARTITION BY collapse_episode_id ORDER BY valid_seq ROWS BETWEEN 1 FOLLOWING AND 10 FOLLOWING) AS next10_min_low,
          count(*) FILTER(WHERE is_major_true_gap) OVER(PARTITION BY collapse_episode_id ORDER BY valid_seq ROWS BETWEEN 1 FOLLOWING AND 10 FOLLOWING) AS next10_major_gap_count
        FROM path0
      ), eligible AS (
        SELECT *,row_number() OVER(PARTITION BY collapse_episode_id ORDER BY valid_seq) AS termination_order
        FROM path1
        WHERE 1-coord_low/peak_coord_high>=0.30
          AND next_session_count=10 AND next10_min_low>=0.95*coord_low
          AND next10_major_gap_count=0
      )
      SELECT collapse_episode_id,symbol,peak_date,trade_date AS original_leg_end_date,
        valid_seq AS original_leg_end_valid_seq,coord_low AS original_leg_end_coord_low,
        next10_min_low,next10_major_gap_count,
        1-coord_low/peak_coord_high AS drawdown_at_leg_end,
        'FIRST_30PCT_TROUGH_WITH_10_SESSION_STABILIZATION' AS segmentation_rule
      FROM eligible WHERE termination_order=1 ORDER BY collapse_episode_id
    """
    ends = con.execute(query).fetchdf()
    con.close()
    write_parquet(ends, LEG_ENDS)
    return ends


def build_v3_ledger(ends: pd.DataFrame) -> pd.DataFrame:
    ledger = pd.read_parquet(v2.GAP_LEDGER)
    if len(ledger) != 67_970 or not ledger.high.lt(ledger.prev_low).all():
        raise SemanticError("V2 true-gap primitive changed")
    ledger = ledger.merge(
        ends[["collapse_episode_id", "original_leg_end_date", "original_leg_end_coord_low", "drawdown_at_leg_end"]],
        on="collapse_episode_id",
        how="left",
        validate="many_to_one",
    )
    ledger["original_leg_segmented"] = ledger.original_leg_end_date.notna()
    ledger["in_original_impulsive_collapse_leg"] = ledger.original_leg_segmented & ledger.gap_date.le(ledger.original_leg_end_date)
    ledger["post_collapse_local_gap"] = ledger.original_leg_segmented & ledger.gap_date.gt(ledger.original_leg_end_date)
    ledger["significance_primary_eligible"] = ledger.importance.isin(["MAJOR", "SECONDARY"])
    ledger["collapse_primary_eligible"] = ledger.in_original_impulsive_collapse_leg & ledger.significance_primary_eligible
    ledger["minor_retained_not_primary"] = ledger.importance.eq("MINOR")
    ledger["future_depth_used_to_define_gap_identity"] = False
    ledger["true_gap_primitive_version"] = "V2_FROZEN_HIGH_T_LT_LOW_T_MINUS_1"
    if ledger.true_gap_id.duplicated().any() or len(ledger) != 67_970:
        raise SemanticError("V3 ledger lost or duplicated a true gap")
    if ledger.post_collapse_local_gap.mul(ledger.collapse_primary_eligible).any():
        raise SemanticError("post-collapse local gap remained primary eligible")
    if ledger.importance.eq("MINOR").mul(ledger.collapse_primary_eligible).any():
        raise SemanticError("minor gap remained primary eligible")
    write_parquet(ledger, GAP_LEDGER)
    return ledger


def raw_union() -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{v2.RAW_ROOT / f'{year}_day_parquet_none.parquet'}') WHERE period='1m' AND adjust='none'"
        for year in range(2014, 2024)
    )


def build_gap_events() -> pd.DataFrame:
    """Find each eligible gap's first minute return after frozen persistence."""
    con = duckdb.connect()
    con.execute("SET threads=4")
    query = f"""
      WITH path0 AS (
        SELECT g.*,d.trade_date AS state_date,d.cal_idx AS state_cal_idx,
          d.open AS state_open,d.high AS state_high,d.low AS state_low,d.close AS state_close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.prior_coord_close,
          d.coordinate_factor AS state_coordinate_factor,
          row_number() OVER(PARTITION BY g.true_gap_id ORDER BY d.trade_date) AS rn,
          round(d.high*100)<round((g.true_gap_lower/d.coordinate_factor)*100) AS fully_below,
          round(d.high*100)>=round((g.true_gap_upper/d.coordinate_factor)*100) AS full_fill,
          (
            round(d.prior_coord_close/d.coordinate_factor*100)<round((g.true_gap_lower/d.coordinate_factor)*100)
            OR round(d.open*100)<round((g.true_gap_lower/d.coordinate_factor)*100)
          ) AND round(d.high*100)>=round((g.true_gap_lower/d.coordinate_factor)*100) AS possible_upward_interaction
        FROM read_parquet('{GAP_LEDGER}') g
        JOIN read_parquet('{v2.DAILY}') d ON d.symbol=g.symbol AND d.trade_date>g.gap_date
          AND d.trade_date<=DATE '2023-12-29' AND d.invalid_step_cum=g.peak_invalid_step_cum
        WHERE g.collapse_primary_eligible
          AND d.history_valid AND d.current_valid AND d.hard_valid
      ), path1 AS (
        SELECT *,rn-coalesce(max(rn) FILTER(WHERE NOT fully_below) OVER(
          PARTITION BY true_gap_id ORDER BY rn ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ),0) AS current_fully_below_run
        FROM path0
      ), path2 AS (
        SELECT *,
          max(current_fully_below_run) OVER(PARTITION BY true_gap_id ORDER BY rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_max_fully_below_run,
          count(*) FILTER(WHERE full_fill) OVER(PARTITION BY true_gap_id ORDER BY rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_full_fill_count,
          min(coord_low) OVER(PARTITION BY true_gap_id ORDER BY rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_min_coord_low,
          median(coord_close) OVER(PARTITION BY true_gap_id ORDER BY rn ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_median_coord_close
        FROM path1
      )
      SELECT *,rn-1 AS gap_age_sessions,
        true_gap_lower/state_coordinate_factor AS raw_threshold,
        prior_coord_close/state_coordinate_factor AS prior_close_raw
      FROM path2
      WHERE rn-1>=10 AND coalesce(prior_max_fully_below_run,0)>=5
        AND prior_full_fill_count=0 AND possible_upward_interaction
      ORDER BY true_gap_id,state_date
    """
    candidate_days = con.execute(query).fetchdf()
    con.close()
    write_parquet(candidate_days, DAILY_CANDIDATE_DAYS)
    if candidate_days.empty:
        raise SemanticError("no V3 daily candidate days")

    seed_cols = ["true_gap_id", "state_date", "symbol", "raw_threshold", "prior_close_raw"]
    seed = candidate_days[seed_cols].copy()
    seed["candidate_day_id"] = seed.true_gap_id + "|" + pd.to_datetime(seed.state_date).dt.strftime("%Y-%m-%d")
    seed_path = EXTERNAL / "minute_seed.parquet"
    write_parquet(seed, seed_path)
    con = duckdb.connect()
    con.execute("SET threads=4")
    exact = con.execute(f"""
      WITH raw AS ({raw_union()}), bars AS (
        SELECT s.*,r.bar_end_time,r.open,r.high,r.low,r.close,
          lag(r.close) OVER(PARTITION BY s.candidate_day_id ORDER BY r.bar_end_time) AS lag_close,
          count(*) OVER(PARTITION BY s.candidate_day_id) AS minute_count
        FROM read_parquet('{seed_path}') s
        JOIN raw r ON r.qmt_code=s.symbol AND r.trade_date=s.state_date
      ), eligible AS (
        SELECT *,row_number() OVER(PARTITION BY candidate_day_id ORDER BY bar_end_time) AS event_order
        FROM bars
        WHERE round(coalesce(lag_close,prior_close_raw)*100)<round(raw_threshold*100)
          AND round(greatest(open,high)*100)>=round(raw_threshold*100)
      )
      SELECT candidate_day_id,true_gap_id,bar_end_time AS first_return_time,
        minute_count,open AS event_bar_open,high AS event_bar_high,
        low AS event_bar_low,close AS event_bar_close
      FROM eligible WHERE event_order=1 ORDER BY true_gap_id,first_return_time
    """).fetchdf()
    con.close()
    write_parquet(candidate_days.loc[~(candidate_days.true_gap_id + "|" + pd.to_datetime(candidate_days.state_date).dt.strftime("%Y-%m-%d")).isin(exact.candidate_day_id)], MINUTE_UNMATCHED)
    merged = candidate_days.assign(candidate_day_id=lambda x: x.true_gap_id + "|" + pd.to_datetime(x.state_date).dt.strftime("%Y-%m-%d")).merge(
        exact, on=["candidate_day_id", "true_gap_id"], how="inner", validate="one_to_one"
    )
    if merged.empty or not merged.minute_count.eq(241).all():
        raise SemanticError("exact minute coverage failed")
    merged = merged.sort_values(["true_gap_id", "first_return_time"], kind="mergesort").groupby("true_gap_id", sort=False).head(1).copy()
    merged["memory_state"] = np.select(
        [merged.gap_age_sessions.le(60), merged.gap_age_sessions.le(90)],
        ["CORE", "BOUNDARY"],
        default="STALE",
    )
    merged["max_below_true_gap_pct"] = 1 - merged.prior_min_coord_low / merged.true_gap_lower
    merged["max_below_true_gap_in_gap_widths"] = (merged.true_gap_lower - merged.prior_min_coord_low) / (merged.true_gap_upper - merged.true_gap_lower)
    merged["first_return_reaches_true_l"] = merged.event_bar_high.mul(100).round().ge(merged.raw_threshold.mul(100).round())
    if not merged.first_return_reaches_true_l.all():
        raise SemanticError("first return below true lower")
    write_parquet(merged, ALL_GAP_EVENTS)
    return merged


def build_candidates_and_mapping(ledger: pd.DataFrame, events: pd.DataFrame, ends: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    active = events.loc[events.memory_state.isin(["CORE", "BOUNDARY"])].copy()
    active = active.sort_values(["collapse_episode_id", "true_gap_lower", "first_return_time", "true_gap_id"], kind="mergesort")
    candidates = active.groupby("collapse_episode_id", sort=False).head(1).copy()
    candidates["candidate_id"] = candidates.collapse_episode_id + "|PRIMARY_HIERARCHY_V3"
    candidates["primary_true_collapse_gap_id"] = candidates.true_gap_id
    gap_counts = ledger.groupby("collapse_episode_id", sort=False).size().rename("episode_true_gap_count")
    candidates = candidates.merge(gap_counts, on="collapse_episode_id", how="left", validate="one_to_one")
    candidates["upper_collapse_gap_count"] = [
        int(((active.collapse_episode_id == row.collapse_episode_id) & (active.true_gap_lower > row.true_gap_lower)).sum())
        for row in candidates.itertuples()
    ]
    write_parquet(candidates, CANDIDATES)

    episodes = pd.read_parquet(v2.EPISODES)
    grouped = ledger.groupby("collapse_episode_id", sort=False).agg(
        true_gap_count=("true_gap_id", "size"),
        in_leg_gap_count=("in_original_impulsive_collapse_leg", "sum"),
        in_leg_relevant_count=("collapse_primary_eligible", "sum"),
        in_leg_minor_count=("minor_retained_not_primary", lambda x: int((x & ledger.loc[x.index, "in_original_impulsive_collapse_leg"]).sum())),
        post_local_gap_count=("post_collapse_local_gap", "sum"),
        post_local_relevant_count=("post_collapse_local_gap", lambda x: int((x & ledger.loc[x.index, "significance_primary_eligible"]).sum())),
    ).reset_index()
    event_stats = events.groupby("collapse_episode_id", sort=False).agg(
        eligible_gap_event_count=("true_gap_id", "size"),
        stale_gap_event_count=("memory_state", lambda x: int((x == "STALE").sum())),
        active_gap_event_count=("memory_state", lambda x: int(x.isin(["CORE", "BOUNDARY"]).sum())),
    ).reset_index()
    chosen = candidates[["collapse_episode_id", "candidate_id", "primary_true_collapse_gap_id", "memory_state", "first_return_time", "gap_age_sessions"]].rename(columns={"memory_state": "primary_memory_state"})
    mapping = episodes[["collapse_episode_id", "symbol", "board", "peak_date"]].merge(
        ends[["collapse_episode_id", "original_leg_end_date"]], on="collapse_episode_id", how="left"
    ).merge(grouped, on="collapse_episode_id", how="left").merge(event_stats, on="collapse_episode_id", how="left").merge(chosen, on="collapse_episode_id", how="left")
    for col in ["true_gap_count", "in_leg_gap_count", "in_leg_relevant_count", "in_leg_minor_count", "post_local_gap_count", "post_local_relevant_count", "eligible_gap_event_count", "stale_gap_event_count", "active_gap_event_count"]:
        mapping[col] = mapping[col].fillna(0).astype(int)
    mapping["final_status"] = np.select(
        [
            mapping.primary_memory_state.eq("CORE"),
            mapping.primary_memory_state.eq("BOUNDARY"),
            mapping.original_leg_end_date.isna(),
            mapping.in_leg_relevant_count.eq(0) & mapping.post_local_relevant_count.gt(0),
            mapping.in_leg_relevant_count.eq(0) & mapping.in_leg_minor_count.gt(0),
            mapping.in_leg_relevant_count.eq(0),
            mapping.eligible_gap_event_count.eq(0),
            mapping.active_gap_event_count.eq(0) & mapping.stale_gap_event_count.gt(0),
        ],
        [
            "CORE_CANDIDATE",
            "BOUNDARY_CANDIDATE",
            "NO_ELIGIBLE_PRIMARY",
            "REJECTED_POST_COLLAPSE_LOCAL",
            "REJECTED_MINOR_PRIMARY",
            "NO_ELIGIBLE_PRIMARY",
            "REJECTED_INSUFFICIENT_PERSISTENCE",
            "REJECTED_STALE",
        ],
        default="NO_ELIGIBLE_PRIMARY",
    )
    write_parquet(mapping, MAPPING)
    return candidates, mapping


def memory_state(age: int) -> str:
    if age <= 60:
        return "CORE"
    if age <= 90:
        return "BOUNDARY"
    return "STALE"


def build_regression(ledger: pd.DataFrame, events: pd.DataFrame, candidates: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    v2_candidates = pd.read_parquet(v2.CANDIDATES)
    sample = v2.diverse_sample(v2_candidates)
    led = ledger.set_index("true_gap_id")
    event_by_gap = events.sort_values("first_return_time").drop_duplicates("true_gap_id").set_index("true_gap_id")
    chosen = candidates.set_index("collapse_episode_id")
    map_by_episode = mapping.set_index("collapse_episode_id")
    rows = []
    for row in sample.itertuples():
        gap = led.loc[row.primary_true_gap_id]
        event = event_by_gap.loc[row.primary_true_gap_id] if row.primary_true_gap_id in event_by_gap.index else None
        v3_primary = chosen.loc[row.collapse_episode_id].primary_true_collapse_gap_id if row.collapse_episode_id in chosen.index else pd.NA
        if not bool(gap.in_original_impulsive_collapse_leg):
            status = "REJECTED_POST_COLLAPSE_LOCAL"
        elif not bool(gap.significance_primary_eligible):
            status = "REJECTED_MINOR_PRIMARY"
        elif event is None:
            status = "REJECTED_INSUFFICIENT_PERSISTENCE"
        elif event.memory_state == "STALE":
            status = "REJECTED_STALE"
        elif event.memory_state == "BOUNDARY":
            status = "BOUNDARY_CANDIDATE"
        else:
            status = "CORE_CANDIDATE"
        rows.append({
            "chart_id": row.audit_id,
            "collapse_episode_id": row.collapse_episode_id,
            "symbol": row.symbol,
            "board": row.board,
            "v2_primary_gap": row.primary_true_gap_id,
            "v3_primary_gap": v3_primary,
            "v3_collapse_leg_member": bool(gap.in_original_impulsive_collapse_leg),
            "v3_significance_eligible": bool(gap.significance_primary_eligible),
            "v3_persistence_eligible": event is not None,
            "v3_memory_state": memory_state(int(event.gap_age_sessions)) if event is not None else memory_state(int(row.gap_age_sessions)),
            "v3_first_return_time": pd.Timestamp(event.first_return_time) if event is not None else pd.NaT,
            "v3_final_status": status,
            "episode_v3_final_status": map_by_episode.loc[row.collapse_episode_id].final_status,
            "primary_changed": pd.notna(v3_primary) and v3_primary != row.primary_true_gap_id,
        })
    regression = pd.DataFrame(rows).sort_values("chart_id")
    write_parquet(regression, REGRESSION)
    return regression


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def diverse_sample(candidates: pd.DataFrame, regression: pd.DataFrame) -> pd.DataFrame:
    work = candidates.loc[
        ~candidates.collapse_episode_id.isin(regression.collapse_episode_id)
        & candidates.episode_true_gap_count.le(8)
    ].copy()
    work["selection_hash"] = work.candidate_id.map(stable_hash)
    work["gap_width_bin"] = pd.qcut(work.true_gap_width_pct.rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
    work["collapse_bin"] = pd.qcut(work.peak_to_low_decline.rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
    work["age_bin"] = pd.cut(work.gap_age_sessions, [0, 30, 60, 75, 90], labels=["A", "B", "C", "D"], include_lowest=True)
    targets = {("CORE", "MAIN"): 9, ("CORE", "CHINEXT"): 5, ("BOUNDARY", "MAIN"): 4, ("BOUNDARY", "CHINEXT"): 2}
    picked: list[int] = []
    seen: set[str] = set()
    for (memory, board), target in targets.items():
        pool = work.loc[work.memory_state.eq(memory) & work.board.eq(board)]
        for _ in range(target):
            best_idx = None
            best_key = None
            for idx, row in pool.loc[~pool.index.isin(picked)].iterrows():
                tokens = {f"importance:{row.importance}", f"width:{row.gap_width_bin}", f"collapse:{row.collapse_bin}", f"age:{row.age_bin}", f"upper:{min(int(row.upper_collapse_gap_count),2)}", f"year:{pd.Timestamp(row.first_return_time).year}"}
                key = (sum(token not in seen for token in tokens), -int(row.selection_hash[:15], 16))
                if best_key is None or key > best_key:
                    best_key, best_idx = key, idx
            if best_idx is None:
                raise SemanticError(f"insufficient pilot pool for {memory}/{board}")
            picked.append(best_idx)
            row = work.loc[best_idx]
            seen.update({f"importance:{row.importance}", f"width:{row.gap_width_bin}", f"collapse:{row.collapse_bin}", f"age:{row.age_bin}", f"upper:{min(int(row.upper_collapse_gap_count),2)}", f"year:{pd.Timestamp(row.first_return_time).year}"})
    sample = work.loc[picked].sort_values(["memory_state", "board", "selection_hash"], kind="mergesort").reset_index(drop=True)
    sample["chart_id"] = [f"TG3-{i:03d}" for i in range(1, len(sample) + 1)]
    return sample


def candle(ax: plt.Axes, frame: pd.DataFrame) -> None:
    x = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    for xi, o, h, low, close in zip(x, frame.coord_open, frame.coord_high, frame.coord_low, frame.coord_close, strict=True):
        color = "#d83b3b" if close >= o else "#15965f"
        ax.vlines(xi, low, h, color=color, linewidth=0.55, zorder=2)
        height = max(abs(close-o), max(abs(h-low)*0.015, 1e-8))
        ax.add_patch(Rectangle((xi-0.3, min(o, close)), 0.6, height, facecolor=color, edgecolor=color, linewidth=0.3, zorder=3))
    ax.xaxis_date()
    ax.grid(axis="y", color="#dfe5ec", linewidth=0.55)
    ax.spines[["top", "right"]].set_visible(False)


def gap_resolution(gap: pd.Series, daily: pd.DataFrame, event_date: pd.Timestamp) -> tuple[str, pd.Timestamp | None]:
    later = daily.loc[(daily.trade_date > gap.gap_date) & (daily.trade_date <= event_date)]
    filled = later.loc[later.coord_high.ge(gap.true_gap_upper)]
    return ("RESOLVED", pd.Timestamp(filled.trade_date.iloc[0])) if len(filled) else ("UNRESOLVED", None)


def render_chart(row: pd.Series, ledger: pd.DataFrame, daily: pd.DataFrame, blind: bool) -> Path:
    event_date = pd.Timestamp(row.first_return_time).normalize()
    gaps = ledger.loc[ledger.collapse_episode_id.eq(row.collapse_episode_id) & ledger.gap_date.le(event_date)].sort_values("gap_date").reset_index(drop=True)
    start = pd.Timestamp(row.main_rise_start_date) - pd.Timedelta(days=30)
    frame = daily.loc[daily.symbol.eq(row.symbol) & daily.trade_date.between(start, event_date)].copy()
    if frame.empty or frame.trade_date.max() != event_date:
        raise SemanticError(f"chart frame missing for {row.chart_id}")
    fig, ax = plt.subplots(figsize=(15, 8.4), facecolor="white")
    candle(ax, frame)
    event_num = mdates.date2num(event_date)
    labels = []
    for i, gap in gaps.iterrows():
        status, resolved_date = gap_resolution(gap, frame, event_date)
        selected = gap.true_gap_id == row.primary_true_collapse_gap_id
        if selected:
            color = "#e34a33"
        elif gap.post_collapse_local_gap:
            color = "#8e63c7"
        else:
            color = {"MAJOR": "#f0a128", "SECONDARY": "#5f8dd3", "MINOR": "#9aa3ad"}[gap.importance]
        x0 = mdates.date2num(pd.Timestamp(gap.gap_date))
        x1 = mdates.date2num(resolved_date) if resolved_date is not None else event_num
        ax.add_patch(Rectangle((x0, gap.true_gap_lower), max(x1-x0, 0.7), gap.true_gap_upper-gap.true_gap_lower,
                               facecolor=color, edgecolor=color, alpha=0.25 if selected else (0.13 if status == "UNRESOLVED" else 0.06),
                               linewidth=1.6 if selected else 0.8, linestyle="--" if status == "RESOLVED" else "-", zorder=1))
        gid = f"G{i+1:02d}"
        ax.annotate(gid, (x0, gap.true_gap_upper), xytext=(3, 3), textcoords="offset points", fontsize=7, color=color, weight="bold")
        age = int((frame.trade_date > gap.gap_date).sum())
        labels.append(f"{gid} {pd.Timestamp(gap.gap_date):%Y-%m-%d} [{gap.true_gap_lower_raw:.2f},{gap.true_gap_upper_raw:.2f}] {gap.true_gap_width_pct:.1%} {gap.importance} IN_LEG={'Y' if gap.in_original_impulsive_collapse_leg else 'N'} LOCAL={'Y' if gap.post_collapse_local_gap else 'N'} {status} age={age} eligible={'Y' if gap.collapse_primary_eligible else 'N'}")
    peak_date = pd.Timestamp(row.peak_date)
    leg_end = pd.Timestamp(row.original_leg_end_date)
    ax.axvline(peak_date, color="#b7791f", linestyle=":", linewidth=1.2)
    ax.axvline(leg_end, color="#1f77b4", linestyle="-.", linewidth=1.2)
    ax.axvline(event_date, color="#6f42c1", linestyle="--", linewidth=1.3)
    ax.scatter([event_date], [row.true_gap_lower], marker="^", s=80, color="#6f42c1", zorder=5)
    title = row.chart_id if blind else f"{row.chart_id} | {row.symbol} | {row.collapse_episode_id}"
    ax.set_title(f"{title} — True-Gap primary hierarchy V3", loc="left", fontsize=14, weight="bold")
    if not blind:
        ax.text(0.01, 0.98, "\n".join(labels), transform=ax.transAxes, va="top", fontsize=6.7,
                bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#c8d0da", alpha=0.93))
    ax.text(0.99, 0.02,
            f"peak={peak_date:%Y-%m-%d} | original-leg end={leg_end:%Y-%m-%d} | primary={row.primary_true_collapse_gap_id.split('|')[-1]} | "
            f"memory={row.memory_state} age={int(row.gap_age_sessions)} | max-below={row.max_below_true_gap_pct:.1%} / {row.max_below_true_gap_in_gap_widths:.1f} gap widths | no post-event bars",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#f7f8fb", edgecolor="#c8d0da"))
    ax.set_ylabel("Corporate-action-consistent price coordinate")
    ax.set_xlabel("Completed sessions through semantic first-return marker")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=25)
    fig.tight_layout()
    out = (BLIND_DIR if blind else DIAGNOSTIC_DIR) / f"{row.chart_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def render_pilot(sample: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    symbols_path = EXTERNAL / "pilot_symbols.parquet"
    write_parquet(sample[["symbol"]].drop_duplicates(), symbols_path)
    con = duckdb.connect()
    daily = con.execute(f"""
      SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,d.coord_close
      FROM read_parquet('{v2.DAILY}') d JOIN read_parquet('{symbols_path}') s USING(symbol)
      WHERE d.trade_date<=DATE '2023-12-29' ORDER BY symbol,trade_date
    """).fetchdf()
    con.close()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    rows = []
    blind_index = []
    diagnostic_index = []
    for _, row in sample.iterrows():
        blind_path = render_chart(row, ledger, daily, True)
        diagnostic_path = render_chart(row, ledger, daily, False)
        blind_index.append({"chart_id": row.chart_id, "path": str(blind_path), "chart_end": row.first_return_time, "post_event_bars": 0})
        diagnostic_index.append({"chart_id": row.chart_id, "candidate_id": row.candidate_id, "symbol": row.symbol, "path": str(diagnostic_path), "chart_end": row.first_return_time, "post_event_bars": 0})
        rows.append({
            "chart_id": row.chart_id,
            "PATTERN_MATCH": "",
            "COLLAPSE_LEG_CORRECT": "",
            "ALL_TRUE_GAPS_CORRECT": "",
            "PRIMARY_GAP_CORRECT": "",
            "POST_COLLAPSE_LOCAL_EXCLUDED_CORRECTLY": "",
            "PERSISTENCE_CORRECT": "",
            "MEMORY_STATE_CORRECT": "",
            "FIRST_RETURN_CORRECT": "",
            "COMMENTS": "",
        })
    pd.DataFrame(blind_index).to_csv(BLIND_INDEX, index=False)
    pd.DataFrame(diagnostic_index).to_csv(DIAGNOSTIC_INDEX, index=False)
    review = pd.DataFrame(rows)
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(REVIEW, index=False)
    return review


def build_result(ledger: pd.DataFrame, candidates: pd.DataFrame, mapping: pd.DataFrame, regression: pd.DataFrame, sample: pd.DataFrame) -> dict[str, object]:
    positive = {"TG2-001", "TG2-006", "TG2-009", "TG2-010", "TG2-012", "TG2-016", "TG2-022", "TG2-024", "TG2-028"}
    negative = {"TG2-004", "TG2-017", "TG2-018", "TG2-019", "TG2-025", "TG2-027", "TG2-029", "TG2-007", "TG2-015", "TG2-023", "TG2-026", "TG2-008", "TG2-013"}
    survived = set(regression.loc[regression.v3_final_status.isin(["CORE_CANDIDATE", "BOUNDARY_CANDIDATE"]), "chart_id"])
    status = dict(zip(regression.chart_id, regression.v3_final_status, strict=True))
    return {
        "experiment": EXPERIMENT,
        "frozen_spec_hash": EXPECTED_SPEC_HASH,
        "verdict": "TRUE_GAP_PRIMARY_HIERARCHY_PARTIALLY_ALIGNED",
        "human_review_required": True,
        "regression_30": {
            "positive_regression_survived": len(positive & survived),
            "positive_regression_total": len(positive),
            "negative_regression_rejected": len(negative - survived),
            "negative_regression_total": len(negative),
            "TG2_010_STATUS": status["TG2-010"],
            "TG2_015_STATUS": status["TG2-015"],
            "TG2_018_STATUS": status["TG2-018"],
            "TG2_024_STATUS": status["TG2-024"],
        },
        "population": {
            "true_gaps_total": len(ledger),
            "true_gaps_in_original_collapse_leg": int(ledger.in_original_impulsive_collapse_leg.sum()),
            "major_in_leg": int((ledger.in_original_impulsive_collapse_leg & ledger.importance.eq("MAJOR")).sum()),
            "secondary_in_leg": int((ledger.in_original_impulsive_collapse_leg & ledger.importance.eq("SECONDARY")).sum()),
            "minor_in_leg": int((ledger.in_original_impulsive_collapse_leg & ledger.importance.eq("MINOR")).sum()),
            "post_collapse_local_gaps": int(ledger.post_collapse_local_gap.sum()),
            "unsegmented_gaps": int((~ledger.original_leg_segmented).sum()),
            "core_active_candidates": int(candidates.memory_state.eq("CORE").sum()),
            "boundary_candidates": int(candidates.memory_state.eq("BOUNDARY").sum()),
            "stale_rejected": int(mapping.final_status.eq("REJECTED_STALE").sum()),
            "minor_primary_rejected": int(mapping.final_status.eq("REJECTED_MINOR_PRIMARY").sum()),
            "insufficient_persistence_rejected": int(mapping.final_status.eq("REJECTED_INSUFFICIENT_PERSISTENCE").sum()),
            "no_eligible_primary": int(mapping.final_status.eq("NO_ELIGIBLE_PRIMARY").sum()),
            "unsegmented_episodes": int(mapping.original_leg_end_date.isna().sum()),
        },
        "new_pilot": {
            "blind_chart_count": len(sample),
            "core_count": int(sample.memory_state.eq("CORE").sum()),
            "boundary_count": int(sample.memory_state.eq("BOUNDARY").sum()),
            "main_count": int(sample.board.eq("MAIN").sum()),
            "chinext_count": int(sample.board.eq("CHINEXT").sum()),
            "blind_chart_index": str(BLIND_INDEX),
            "diagnostic_chart_index": str(DIAGNOSTIC_INDEX),
            "review_csv": str(REVIEW),
        },
        "audit": {
            "true_gap_primitive_changed_count": 0,
            "open_based_true_gap_count": 0,
            "future_depth_used_to_define_gap_identity_count": 0,
            "post_collapse_local_gap_used_as_primary_count": 0,
            "minor_gap_used_as_primary_count": 0,
            "stale_gap_used_as_core_primary_count": 0,
            "first_return_below_true_gap_count": 0,
            "return_analysis_run": "NO",
            "strategy_backtest_run": "NO",
            "repository_2024_plus_data_opened": "NO",
        },
    }


def report_text(result: dict[str, object], regression: pd.DataFrame) -> str:
    p = result["population"]
    r = result["regression_30"]
    n = result["new_pilot"]
    failures = regression.loc[regression.chart_id.isin(["TG2-001", "TG2-006", "TG2-009", "TG2-010", "TG2-012", "TG2-016", "TG2-022", "TG2-024", "TG2-028"]) & ~regression.v3_final_status.isin(["CORE_CANDIDATE", "BOUNDARY_CANDIDATE"]), ["chart_id", "v3_final_status"]]
    failure_text = "; ".join(f"{row.chart_id}={row.v3_final_status}" for row in failures.itertuples()) or "none"
    return f"""# A-share Collapse True-Gap Primary Hierarchy Semantic V3

## Scope

Outcome-blind semantic refinement only. The true-gap primitive remains
`High_t < Low_t-1`, interval `[High_t, Low_t-1]`. No return, PnL, entry,
strategy replay, or repository 2024+ security data was opened.

## Frozen hierarchy

The original impulsive collapse leg ends at the earliest >=30% peak-drawdown
candidate trough whose next 10 completed sessions contain neither a low more
than 5% below the trough nor a new MAJOR true gap. Gaps after that end remain
visible as `POST_COLLAPSE_LOCAL_GAP` but cannot become primary. MINOR gaps also
remain in the ledger but cannot become primary.

Active repair requires at least 10 completed sessions, a prior run of five
completed sessions with `High < L`, no full resolution, and a minute return
from below to `L`. Age <=60 is CORE, 61--90 BOUNDARY, and >90 STALE. These are
semantic memory bands, not alpha parameters.

## Population

- True gaps retained: {p['true_gaps_total']:,}
- In original impulsive collapse legs: {p['true_gaps_in_original_collapse_leg']:,}
- In-leg MAJOR / SECONDARY / MINOR: {p['major_in_leg']:,} / {p['secondary_in_leg']:,} / {p['minor_in_leg']:,}
- Post-collapse local gaps: {p['post_collapse_local_gaps']:,}
- Unsegmented gaps retained but primary-ineligible: {p['unsegmented_gaps']:,}
- CORE / BOUNDARY candidates: {p['core_active_candidates']:,} / {p['boundary_candidates']:,}
- STALE / MINOR / persistence / no-primary rejects: {p['stale_rejected']:,} / {p['minor_primary_rejected']:,} / {p['insufficient_persistence_rejected']:,} / {p['no_eligible_primary']:,}

## Frozen 30-chart regression

Positive references surviving as CORE/BOUNDARY: {r['positive_regression_survived']}/{r['positive_regression_total']}.
Known negative references rejected: {r['negative_regression_rejected']}/{r['negative_regression_total']}.
Positive-reference rule failures are: {failure_text}. They were not forced to
pass; each follows the preregistered segmentation/persistence rule.

TG2-010: `{r['TG2_010_STATUS']}`; TG2-015: `{r['TG2_015_STATUS']}`;
TG2-018: `{r['TG2_018_STATUS']}`; TG2-024: `{r['TG2_024_STATUS']}`.

## New blind pilot

Exactly {n['blind_chart_count']} new outcome-blind charts were generated:
{n['core_count']} CORE, {n['boundary_count']} BOUNDARY, {n['main_count']} Main,
and {n['chinext_count']} ChiNext. Every chart ends at the semantic first-return
marker and contains no post-event bars. Human review remains mandatory.

## Verdict

`TRUE_GAP_PRIMARY_HIERARCHY_PARTIALLY_ALIGNED`

Implementation invariants pass, but alignment cannot be declared before the
new 20-chart human review. No outcome discovery is authorized here.
"""


def main() -> None:
    validate_inputs()
    ends = build_leg_ends()
    ledger = build_v3_ledger(ends)
    events = build_gap_events()
    candidates, mapping = build_candidates_and_mapping(ledger, events, ends)
    regression = build_regression(ledger, events, candidates, mapping)
    sample = diverse_sample(candidates, regression)
    review = render_pilot(sample, ledger)
    result = build_result(ledger, candidates, mapping, regression, sample)
    result["artifacts"] = {
        "gap_ledger": {"path": str(GAP_LEDGER), "sha256": sha256(GAP_LEDGER)},
        "candidates": {"path": str(CANDIDATES), "sha256": sha256(CANDIDATES)},
        "regression_30": {"path": str(REGRESSION), "sha256": sha256(REGRESSION)},
        "mapping": {"path": str(MAPPING), "sha256": sha256(MAPPING)},
        "review": {"path": str(REVIEW), "sha256": sha256(REVIEW)},
        "blind_chart_index": {"path": str(BLIND_INDEX), "sha256": sha256(BLIND_INDEX)},
        "diagnostic_chart_index": {"path": str(DIAGNOSTIC_INDEX), "sha256": sha256(DIAGNOSTIC_INDEX)},
    }
    atomic_text(RESULT, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_text(REPORT, report_text(result, regression))
    if len(review) != 20:
        raise SemanticError("blind review package count mismatch")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
