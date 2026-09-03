#!/usr/bin/env python3
# ruff: noqa: E501
"""Outcome-blind causal timing repair for the frozen True-Gap V3 semantics."""

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
    run_ashare_collapse_true_gap_primary_hierarchy_semantic_v3 as v3,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_zone_semantic_fidelity_v2 as v2,
)

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-TRUE-GAP-CAUSAL-FORMATION-SEMANTIC-V4"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_HASH = "c63405a2f104eff0c09b00d107d655ddf395f0b740e2f1dc949af84c8c588eab"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_true_gap_causal_formation_semantic_v4")
BLIND_DIR = EXTERNAL / "charts/blind"
DIAGNOSTIC_DIR = EXTERNAL / "charts/diagnostic"
PROTRACTED_DIR = EXTERNAL / "charts/protracted"
ANCHORS = EXTERNAL / "causal_time_anchors.parquet"
FREEZE_GAPS = EXTERNAL / "primary_freeze_gap_states.parquet"
PRETOUCH_DAYS = EXTERNAL / "preconfirmation_touch_candidate_days.parquet"
PRETOUCH_EXACT = EXTERNAL / "preconfirmation_exact_touches.parquet"
CAUSAL_PRIMARY = EXTERNAL / "causally_frozen_primary_gaps.parquet"
BLIND_INDEX = EXTERNAL / "blind_chart_index.csv"
DIAGNOSTIC_INDEX = EXTERNAL / "diagnostic_chart_index.csv"
PROTRACTED_INDEX = EXTERNAL / "protracted_collapse_chart_index.csv"
CROSSWALK = OS_ROOT / f"artifacts/{EXPERIMENT}_crosswalk.parquet"
CANDIDATES = OS_ROOT / f"artifacts/{EXPERIMENT}_candidates.parquet"
DURATION = OS_ROOT / f"artifacts/{EXPERIMENT}_duration_diagnostic.parquet"
REGRESSIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_regressions.parquet"
REVIEW = OS_ROOT / f"artifacts/{EXPERIMENT}_review.csv"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class CausalSemanticError(RuntimeError):
    """Fail closed on chronology, lineage, sealed-period, or semantic drift."""


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
        raise CausalSemanticError("V4 frozen spec hash mismatch")
    prior = json.loads(v3.RESULT.read_text())
    if prior["population"]["core_active_candidates"] != 3_822 or prior["population"]["boundary_candidates"] != 497:
        raise CausalSemanticError("V3 candidate population mismatch")
    ledger = pd.read_parquet(v3.GAP_LEDGER, columns=["true_gap_id", "high", "prev_low", "future_depth_used_to_define_gap_identity"])
    if len(ledger) != 67_970 or not ledger.high.lt(ledger.prev_low).all() or ledger.future_depth_used_to_define_gap_identity.any():
        raise CausalSemanticError("true-gap primitive changed")


def build_anchors() -> pd.DataFrame:
    """Rebuild peak/end/confirmation clocks from frozen V3 lineage."""
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    anchors = con.execute(f"""
      WITH c AS (
        SELECT c.*,e.original_leg_end_date,e.original_leg_end_valid_seq
        FROM read_parquet('{v3.CANDIDATES}') c
        JOIN read_parquet('{v3.LEG_ENDS}') e USING(collapse_episode_id)
      ), after_end AS (
        SELECT c.collapse_episode_id,d.trade_date,
          row_number() OVER(PARTITION BY c.collapse_episode_id ORDER BY d.trade_date) AS after_end_session_number
        FROM c JOIN read_parquet('{v2.DAILY}') d ON d.symbol=c.symbol
          AND d.trade_date>c.original_leg_end_date AND d.trade_date<=DATE '2023-12-29'
          AND d.invalid_step_cum=c.peak_invalid_step_cum
        WHERE d.history_valid AND d.current_valid AND d.hard_valid
      ), confirmation AS (
        SELECT collapse_episode_id,trade_date AS leg_confirmation_date
        FROM after_end WHERE after_end_session_number=10
      ), duration AS (
        SELECT c.collapse_episode_id,count(*) AS original_collapse_leg_duration_sessions
        FROM c JOIN read_parquet('{v2.DAILY}') d ON d.symbol=c.symbol
          AND d.trade_date>c.peak_date AND d.trade_date<=c.original_leg_end_date
          AND d.invalid_step_cum=c.peak_invalid_step_cum
        WHERE d.history_valid AND d.current_valid AND d.hard_valid
        GROUP BY c.collapse_episode_id
      )
      SELECT c.candidate_id,c.collapse_episode_id,c.symbol,c.board,c.memory_state AS source_memory_state,
        c.primary_true_collapse_gap_id AS v3_primary_gap_id,c.gap_date AS v3_primary_gap_formation_date,
        c.first_return_time AS v3_first_return_time,c.gap_age_sessions AS v3_gap_age_sessions,
        c.peak_date,c.main_rise_start_date,c.peak_invalid_step_cum,
        cast(c.peak_date AS TIMESTAMP)+INTERVAL 15 HOUR AS peak_time,
        cast(c.original_leg_end_date AS TIMESTAMP)+INTERVAL 15 HOUR AS leg_end_time,
        cast(cf.leg_confirmation_date AS TIMESTAMP)+INTERVAL 15 HOUR AS leg_confirmation_time,
        cf.leg_confirmation_date,d.original_collapse_leg_duration_sessions
      FROM c JOIN confirmation cf USING(collapse_episode_id)
      JOIN duration d USING(collapse_episode_id)
      ORDER BY c.collapse_episode_id
    """).fetchdf()
    con.close()
    if len(anchors) != 4_319 or anchors.leg_confirmation_time.isna().any():
        raise CausalSemanticError("causal anchors incomplete")
    write_parquet(anchors, ANCHORS)
    return anchors


def freeze_primary_gaps() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Enumerate only confirmation-time-known in-leg unresolved M/S gaps."""
    con = duckdb.connect()
    con.execute("SET threads=4")
    gap_states = con.execute(f"""
      WITH states AS (
        SELECT a.candidate_id,a.collapse_episode_id,a.symbol,a.board,a.source_memory_state,
          a.v3_primary_gap_id,a.peak_time,a.leg_end_time,a.leg_confirmation_time,
          a.leg_confirmation_date,a.original_collapse_leg_duration_sessions,
          g.* EXCLUDE(collapse_episode_id,symbol,board),
          count(*) FILTER(WHERE d.trade_date>g.gap_date
            AND round(d.high*100)>=round((g.true_gap_upper/d.coordinate_factor)*100)) AS full_resolution_count_by_confirmation
        FROM read_parquet('{ANCHORS}') a
        JOIN read_parquet('{v3.GAP_LEDGER}') g USING(collapse_episode_id,symbol,board)
        LEFT JOIN read_parquet('{v2.DAILY}') d ON d.symbol=g.symbol
          AND d.trade_date>g.gap_date AND d.trade_date<=a.leg_confirmation_date
          AND d.invalid_step_cum=g.peak_invalid_step_cum
          AND d.history_valid AND d.current_valid AND d.hard_valid
        WHERE g.in_original_impulsive_collapse_leg AND g.significance_primary_eligible
          AND g.gap_date<=a.leg_end_time::DATE
        GROUP BY ALL
      )
      SELECT *,full_resolution_count_by_confirmation=0 AS unresolved_at_confirmation,
        row_number() OVER(PARTITION BY collapse_episode_id ORDER BY
          CASE WHEN full_resolution_count_by_confirmation=0 THEN 0 ELSE 1 END,
          true_gap_lower,true_gap_id) AS freeze_order
      FROM states ORDER BY collapse_episode_id,true_gap_lower,true_gap_id
    """).fetchdf()
    con.close()
    write_parquet(gap_states, FREEZE_GAPS)
    primary = gap_states.loc[gap_states.unresolved_at_confirmation].sort_values(
        ["collapse_episode_id", "true_gap_lower", "true_gap_id"], kind="mergesort"
    ).groupby("collapse_episode_id", sort=False).head(1).copy()
    primary["causal_primary_gap_id"] = primary.true_gap_id
    primary["primary_gap_freeze_time"] = primary.leg_confirmation_time
    primary["primary_changed_at_causal_freeze"] = primary.causal_primary_gap_id.ne(primary.v3_primary_gap_id)
    primary["primary_gap_frozen_before_confirmation"] = False
    write_parquet(primary, CAUSAL_PRIMARY)
    return gap_states, primary


def raw_union() -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{v2.RAW_ROOT / f'{year}_day_parquet_none.parquet'}') WHERE period='1m' AND adjust='none'"
        for year in range(2014, 2024)
    )


def detect_preconfirmation_touches(primary: pd.DataFrame) -> pd.DataFrame:
    """Find any exact upward touch from below before the causal freeze."""
    if primary.empty:
        raise CausalSemanticError("no causal primary gaps")
    con = duckdb.connect()
    con.execute("SET threads=4")
    days = con.execute(f"""
      SELECT p.collapse_episode_id,p.causal_primary_gap_id,p.symbol,p.gap_date,
        p.leg_confirmation_time,p.true_gap_lower,d.trade_date,
        p.true_gap_lower/d.coordinate_factor AS raw_threshold,
        d.prior_coord_close/d.coordinate_factor AS prior_close_raw
      FROM read_parquet('{CAUSAL_PRIMARY}') p
      JOIN read_parquet('{v2.DAILY}') d ON d.symbol=p.symbol
        AND d.trade_date>p.gap_date AND d.trade_date<=p.leg_confirmation_time::DATE
        AND d.invalid_step_cum=p.peak_invalid_step_cum
      WHERE d.history_valid AND d.current_valid AND d.hard_valid
        AND (
          round(d.prior_coord_close/d.coordinate_factor*100)<round(p.true_gap_lower/d.coordinate_factor*100)
          OR round(d.open*100)<round(p.true_gap_lower/d.coordinate_factor*100)
        )
        AND round(d.high*100)>=round(p.true_gap_lower/d.coordinate_factor*100)
      ORDER BY p.collapse_episode_id,d.trade_date
    """).fetchdf()
    con.close()
    days["touch_day_id"] = days.collapse_episode_id + "|" + pd.to_datetime(days.trade_date).dt.strftime("%Y-%m-%d")
    write_parquet(days, PRETOUCH_DAYS)
    if days.empty:
        touches = pd.DataFrame(columns=["collapse_episode_id", "causal_primary_gap_id", "preconfirm_first_touch_time"])
        write_parquet(touches, PRETOUCH_EXACT)
        return touches
    con = duckdb.connect()
    con.execute("SET threads=4")
    exact = con.execute(f"""
      WITH raw AS ({raw_union()}), bars AS (
        SELECT s.*,r.bar_end_time,r.open,r.high,r.low,r.close,
          lag(r.close) OVER(PARTITION BY s.touch_day_id ORDER BY r.bar_end_time) AS lag_close,
          count(*) OVER(PARTITION BY s.touch_day_id) AS minute_count
        FROM read_parquet('{PRETOUCH_DAYS}') s
        JOIN raw r ON r.qmt_code=s.symbol AND r.trade_date=s.trade_date
      ), eligible AS (
        SELECT *,row_number() OVER(PARTITION BY touch_day_id ORDER BY bar_end_time) AS event_order
        FROM bars
        WHERE round(coalesce(lag_close,prior_close_raw)*100)<round(raw_threshold*100)
          AND round(greatest(open,high)*100)>=round(raw_threshold*100)
          AND bar_end_time<=leg_confirmation_time
      )
      SELECT collapse_episode_id,causal_primary_gap_id,bar_end_time AS touch_time,minute_count
      FROM eligible WHERE event_order=1 ORDER BY collapse_episode_id,touch_time
    """).fetchdf()
    con.close()
    if len(exact) and not exact.minute_count.eq(241).all():
        raise CausalSemanticError("preconfirmation minute coverage failed")
    touches = exact.sort_values(["collapse_episode_id", "touch_time"], kind="mergesort").groupby("collapse_episode_id", sort=False).head(1).rename(columns={"touch_time": "preconfirm_first_touch_time"})
    write_parquet(touches, PRETOUCH_EXACT)
    return touches


def build_crosswalk(anchors: pd.DataFrame, primary: pd.DataFrame, touches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pcols = ["collapse_episode_id", "causal_primary_gap_id", "gap_date", "true_gap_lower", "true_gap_upper", "importance", "primary_gap_freeze_time", "primary_changed_at_causal_freeze"]
    cross = anchors.merge(primary[pcols], on="collapse_episode_id", how="left", validate="one_to_one").merge(
        touches[["collapse_episode_id", "preconfirm_first_touch_time"]], on="collapse_episode_id", how="left", validate="one_to_one"
    )
    cross["no_causal_primary"] = cross.causal_primary_gap_id.isna()
    cross["primary_changed_at_causal_freeze"] = cross.primary_changed_at_causal_freeze.eq(True)
    cross["source_return_before_leg_end"] = cross.v3_first_return_time.lt(cross.leg_end_time)
    cross["source_return_end_to_confirmation"] = cross.v3_first_return_time.ge(cross.leg_end_time) & cross.v3_first_return_time.le(cross.leg_confirmation_time)
    cross["preconfirm_primary_touch"] = cross.preconfirm_first_touch_time.notna()
    cross["final_disposition"] = np.select(
        [
            cross.no_causal_primary,
            cross.primary_changed_at_causal_freeze,
            cross.source_return_before_leg_end,
            cross.source_return_end_to_confirmation,
            cross.preconfirm_primary_touch,
        ],
        [
            "NO_CAUSAL_PRIMARY",
            "PRIMARY_CHANGED_AT_CAUSAL_FREEZE",
            "REJECTED_RETURN_BEFORE_LEG_END",
            "REJECTED_RETURN_AFTER_END_BEFORE_CONFIRMATION",
            "REJECTED_PRECONFIRM_PRIMARY_TOUCH",
        ],
        default="RETAINED_CAUSAL_FIRST_RETURN",
    )
    cross["causal_first_return_time"] = cross.v3_first_return_time.where(cross.final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN"))
    cross["retained_after_confirmation"] = cross.causal_first_return_time.gt(cross.leg_confirmation_time) | cross.causal_first_return_time.isna()
    cross["preconfirm_touch_reset_as_new_first_return"] = False
    if not cross.retained_after_confirmation.all():
        raise CausalSemanticError("retained event is not after confirmation")
    write_parquet(cross, CROSSWALK)
    retained = cross.loc[cross.final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN")].copy()
    retained["memory_state"] = retained.source_memory_state
    retained["candidate_id"] = retained.collapse_episode_id + "|CAUSAL_FORMATION_V4"
    retained["primary_gap_formation_time"] = pd.to_datetime(retained.gap_date) + pd.Timedelta(hours=15)
    retained["primary_gap_freeze_time"] = retained.leg_confirmation_time
    write_parquet(retained, CANDIDATES)
    return cross, retained


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


def build_duration_diagnostic(cross: pd.DataFrame) -> pd.DataFrame:
    ledger = pd.read_parquet(v3.GAP_LEDGER)
    gap_counts = ledger.loc[ledger.in_original_impulsive_collapse_leg].groupby("collapse_episode_id", sort=False).agg(
        true_gaps_in_leg=("true_gap_id", "size"),
        major_gaps_in_leg=("importance", lambda x: int((x == "MAJOR").sum())),
        secondary_gaps_in_leg=("importance", lambda x: int((x == "SECONDARY").sum())),
    ).reset_index()
    rows = cross.merge(gap_counts, on="collapse_episode_id", how="left", validate="one_to_one")
    rows["duration_group"] = rows.original_collapse_leg_duration_sessions.map(duration_group)
    order = ["<=20", "21-40", "41-60", "61-90", ">90"]
    output = []
    for group in order:
        part = rows.loc[rows.duration_group.eq(group)]
        retained = int(part.final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN").sum())
        output.append({
            "duration_group": group,
            "episode_count": len(part),
            "source_candidate_count": len(part),
            "retained_causal_candidate_count": retained,
            "causal_candidate_retention_rate": retained / len(part) if len(part) else np.nan,
            "true_gaps_in_leg": int(part.true_gaps_in_leg.fillna(0).sum()),
            "major_gaps_in_leg": int(part.major_gaps_in_leg.fillna(0).sum()),
            "secondary_gaps_in_leg": int(part.secondary_gaps_in_leg.fillna(0).sum()),
        })
    diagnostic = pd.DataFrame(output)
    write_parquet(diagnostic, DURATION)
    return diagnostic


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def build_regressions(cross: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    v3_regression = pd.read_parquet(v3.REGRESSION)
    v3_sample = v3.diverse_sample(pd.read_parquet(v3.CANDIDATES), v3_regression)
    ids = ["TG3-008", "TG3-013", "TG3-009", "TG3-014", "TG3-017", "TG3-019", "TG3-020"]
    mapping = v3_sample[["chart_id", "collapse_episode_id", "candidate_id", "symbol", "board"]]
    regressions = mapping.loc[mapping.chart_id.isin(ids)].merge(cross, on="collapse_episode_id", how="left", validate="one_to_one", suffixes=("_tg3", ""))
    regressions = regressions.sort_values("chart_id")
    if set(regressions.chart_id) != set(ids):
        raise CausalSemanticError("TG3 regression identity mismatch")
    write_parquet(regressions, REGRESSIONS)
    return regressions, v3_sample


def choose_diverse(pool: pd.DataFrame, target: int, seen: set[str]) -> list[int]:
    selected: list[int] = []
    for _ in range(target):
        best_idx = None
        best_key = None
        for idx, row in pool.loc[~pool.index.isin(selected)].iterrows():
            tokens = {
                f"board:{row.board}", f"disp:{row.final_disposition}",
                f"gaps:{min(int(row.true_gaps_in_leg),5)}",
                f"year:{pd.Timestamp(row.leg_confirmation_time).year}",
            }
            key = (sum(token not in seen for token in tokens), -int(row.selection_hash[:15], 16))
            if best_key is None or key > best_key:
                best_key, best_idx = key, idx
        if best_idx is None:
            raise CausalSemanticError("insufficient diagnostic sample")
        selected.append(best_idx)
        row = pool.loc[best_idx]
        seen.update({f"board:{row.board}", f"disp:{row.final_disposition}", f"gaps:{min(int(row.true_gaps_in_leg),5)}", f"year:{pd.Timestamp(row.leg_confirmation_time).year}"})
    return selected


def protracted_sample(cross: pd.DataFrame) -> pd.DataFrame:
    ledger = pd.read_parquet(v3.GAP_LEDGER)
    gap_counts = ledger.loc[ledger.in_original_impulsive_collapse_leg].groupby("collapse_episode_id").size().rename("true_gaps_in_leg")
    work = cross.merge(gap_counts, on="collapse_episode_id", how="left")
    work["duration_group"] = work.original_collapse_leg_duration_sessions.map(duration_group)
    work["selection_hash"] = work.collapse_episode_id.map(stable_hash)
    selected: list[int] = []
    seen: set[str] = set()
    for group, target in (("41-60", 5), ("61-90", 5), (">90", 10)):
        pool = work.loc[work.duration_group.eq(group)]
        selected.extend(choose_diverse(pool, target, seen))
    sample = work.loc[selected].sort_values(["duration_group", "selection_hash"], kind="mergesort").reset_index(drop=True)
    sample["chart_id"] = [f"PC4-{i:03d}" for i in range(1, len(sample)+1)]
    return sample


def causal_blind_sample(retained: pd.DataFrame, v3_sample: pd.DataFrame) -> pd.DataFrame:
    excluded = set(v3_sample.collapse_episode_id)
    work = retained.loc[~retained.collapse_episode_id.isin(excluded)].copy()
    work["selection_hash"] = work.candidate_id.map(stable_hash)
    work["duration_group"] = work.original_collapse_leg_duration_sessions.map(duration_group)
    work["width_bin"] = pd.qcut(work.true_gap_upper.sub(work.true_gap_lower).rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
    targets = {("CORE", "MAIN"): 9, ("CORE", "CHINEXT"): 5, ("BOUNDARY", "MAIN"): 4, ("BOUNDARY", "CHINEXT"): 2}
    selected: list[int] = []
    seen: set[str] = set()
    for (memory, board), target in targets.items():
        pool = work.loc[work.source_memory_state.eq(memory) & work.board.eq(board)]
        for _ in range(target):
            best_idx = None
            best_key = None
            for idx, row in pool.loc[~pool.index.isin(selected)].iterrows():
                tokens = {f"duration:{row.duration_group}", f"importance:{row.importance}", f"width:{row.width_bin}", f"year:{pd.Timestamp(row.causal_first_return_time).year}"}
                key = (sum(token not in seen for token in tokens), -int(row.selection_hash[:15], 16))
                if best_key is None or key > best_key:
                    best_key, best_idx = key, idx
            if best_idx is None:
                raise CausalSemanticError(f"insufficient retained pool {memory}/{board}")
            selected.append(best_idx)
            row = work.loc[best_idx]
            seen.update({f"duration:{row.duration_group}", f"importance:{row.importance}", f"width:{row.width_bin}", f"year:{pd.Timestamp(row.causal_first_return_time).year}"})
    sample = work.loc[selected].sort_values(["source_memory_state", "board", "selection_hash"], kind="mergesort").reset_index(drop=True)
    sample["chart_id"] = [f"TG4-{i:03d}" for i in range(1, len(sample)+1)]
    return sample


def candle(ax: plt.Axes, frame: pd.DataFrame) -> None:
    x = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    for xi, o, h, low, close in zip(x, frame.coord_open, frame.coord_high, frame.coord_low, frame.coord_close, strict=True):
        color = "#d83b3b" if close >= o else "#15965f"
        ax.vlines(xi, low, h, color=color, linewidth=0.5, zorder=2)
        height = max(abs(close-o), max(abs(h-low)*0.015, 1e-8))
        ax.add_patch(Rectangle((xi-0.3, min(o, close)), 0.6, height, facecolor=color, edgecolor=color, linewidth=0.3, zorder=3))
    ax.grid(axis="y", color="#dfe5ec", linewidth=0.55)
    ax.spines[["top", "right"]].set_visible(False)


def draw_gaps(ax: plt.Axes, gaps: pd.DataFrame, event_date: pd.Timestamp, selected_id: str | None) -> None:
    for i, gap in gaps.sort_values("gap_date").reset_index(drop=True).iterrows():
        selected = gap.true_gap_id == selected_id
        color = "#e34a33" if selected else {"MAJOR": "#f0a128", "SECONDARY": "#5f8dd3", "MINOR": "#9aa3ad"}[gap.importance]
        x0 = mdates.date2num(pd.Timestamp(gap.gap_date))
        x1 = mdates.date2num(event_date)
        ax.add_patch(Rectangle((x0, gap.true_gap_lower), max(x1-x0, 0.7), gap.true_gap_upper-gap.true_gap_lower,
                               facecolor=color, edgecolor=color, alpha=0.24 if selected else 0.10,
                               linewidth=1.5 if selected else 0.7, zorder=1))
        ax.annotate(f"G{i+1:02d}", (x0, gap.true_gap_upper), xytext=(2, 2), textcoords="offset points", fontsize=7, color=color, weight="bold")


def render_causal_chart(row: pd.Series, ledger: pd.DataFrame, daily: pd.DataFrame, blind: bool) -> Path:
    event_time = pd.Timestamp(row.causal_first_return_time)
    event_date = event_time.normalize()
    start = pd.Timestamp(row.main_rise_start_date) - pd.Timedelta(days=30)
    frame = daily.loc[daily.symbol.eq(row.symbol) & daily.trade_date.between(start, event_date)].copy()
    gaps = ledger.loc[ledger.collapse_episode_id.eq(row.collapse_episode_id) & ledger.gap_date.le(event_date)]
    fig, ax = plt.subplots(figsize=(15, 8.4), facecolor="white")
    candle(ax, frame)
    draw_gaps(ax, gaps, event_date, row.causal_primary_gap_id)
    anchors = [
        (pd.Timestamp(row.peak_time), "PEAK", "#b7791f", ":"),
        (pd.Timestamp(row.leg_end_time), "LEG_END", "#1f77b4", "-."),
        (pd.Timestamp(row.leg_confirmation_time), "LEG_CONFIRM / PRIMARY_FREEZE", "#005f73", "--"),
        (pd.Timestamp(row.primary_gap_formation_time), "PRIMARY_FORM", "#d97706", ":"),
        (event_time, "CAUSAL_FIRST_RETURN", "#6f42c1", "--"),
    ]
    for time, label, color, style in anchors:
        ax.axvline(time, color=color, linestyle=style, linewidth=1.2, label=label)
    ax.scatter([event_time], [row.true_gap_lower], marker="^", s=80, color="#6f42c1", zorder=5)
    title = row.chart_id if blind else f"{row.chart_id} | {row.symbol} | {row.collapse_episode_id}"
    ax.set_title(f"{title} — causal True-Gap formation V4", loc="left", fontsize=14, weight="bold")
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    ax.text(0.99, 0.02, f"memory={row.source_memory_state} | primary={row.causal_primary_gap_id.split('|')[-1]} | freeze={pd.Timestamp(row.primary_gap_freeze_time):%Y-%m-%d 15:00} | no preconfirm touch | no post-event bars",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#f7f8fb", edgecolor="#c8d0da"))
    ax.set_ylabel("Corporate-action-consistent price coordinate")
    ax.set_xlabel("Completed sessions through causal first return")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=10)); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=25); fig.tight_layout()
    out = (BLIND_DIR if blind else DIAGNOSTIC_DIR) / f"{row.chart_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True); fig.savefig(out, dpi=160); plt.close(fig)
    return out


def interim_rebounds(frame: pd.DataFrame, peak_date: pd.Timestamp, confirmation_date: pd.Timestamp) -> pd.DataFrame:
    path = frame.loc[frame.trade_date.between(peak_date, confirmation_date)].copy()
    if len(path) < 7:
        return path.iloc[0:0]
    path["running_low"] = path.coord_low.cummin()
    path["rebound"] = path.coord_close / path.running_low - 1
    path["local_peak"] = path.coord_close.eq(path.coord_close.rolling(7, center=True, min_periods=7).max())
    return path.loc[path.local_peak].nlargest(3, "rebound")


def render_protracted_chart(row: pd.Series, ledger: pd.DataFrame, daily: pd.DataFrame) -> Path:
    end_time = max(pd.Timestamp(row.leg_confirmation_time), pd.Timestamp(row.v3_first_return_time))
    end_date = end_time.normalize()
    start = pd.Timestamp(row.main_rise_start_date) - pd.Timedelta(days=30)
    frame = daily.loc[daily.symbol.eq(row.symbol) & daily.trade_date.between(start, end_date)].copy()
    gaps = ledger.loc[ledger.collapse_episode_id.eq(row.collapse_episode_id) & ledger.in_original_impulsive_collapse_leg]
    fig, ax = plt.subplots(figsize=(15, 8.4), facecolor="white")
    candle(ax, frame); draw_gaps(ax, gaps, end_date, row.causal_primary_gap_id if pd.notna(row.causal_primary_gap_id) else None)
    for time, label, color, style in [
        (pd.Timestamp(row.peak_time), "PEAK", "#b7791f", ":"),
        (pd.Timestamp(row.leg_end_time), "LEG_END", "#1f77b4", "-."),
        (pd.Timestamp(row.leg_confirmation_time), "LEG_CONFIRM", "#005f73", "--"),
        (pd.Timestamp(row.v3_first_return_time), "V3_RETURN", "#6f42c1", "--"),
    ]:
        ax.axvline(time, color=color, linestyle=style, linewidth=1.2, label=label)
    rebounds = interim_rebounds(frame, pd.Timestamp(row.peak_time).normalize(), pd.Timestamp(row.leg_confirmation_time).normalize())
    ax.scatter(rebounds.trade_date, rebounds.coord_close, marker="*", s=90, color="#c2410c", label="top-3 causal interim rebound descriptors", zorder=5)
    ax.set_title(f"{row.chart_id} | {row.symbol} | duration={int(row.original_collapse_leg_duration_sessions)} | {row.final_disposition}", loc="left", fontsize=13, weight="bold")
    ax.legend(loc="upper right", fontsize=7, ncol=2)
    ax.set_ylabel("Corporate-action-consistent price coordinate"); ax.set_xlabel("Outcome-blind protracted-collapse diagnostic")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=10)); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=25); fig.tight_layout()
    out = PROTRACTED_DIR / f"{row.chart_id}.png"; out.parent.mkdir(parents=True, exist_ok=True); fig.savefig(out, dpi=160); plt.close(fig)
    return out


def load_chart_daily(symbols: pd.Series) -> pd.DataFrame:
    path = EXTERNAL / "chart_symbols.parquet"; write_parquet(pd.DataFrame({"symbol": symbols.drop_duplicates()}), path)
    con = duckdb.connect()
    daily = con.execute(f"""SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,d.coord_close
      FROM read_parquet('{v2.DAILY}') d JOIN read_parquet('{path}') s USING(symbol)
      WHERE d.trade_date<=DATE '2023-12-29' ORDER BY symbol,trade_date""").fetchdf()
    con.close(); daily["trade_date"] = pd.to_datetime(daily.trade_date); return daily


def render_packages(blind_sample: pd.DataFrame, protracted: pd.DataFrame) -> pd.DataFrame:
    ledger = pd.read_parquet(v3.GAP_LEDGER)
    daily = load_chart_daily(pd.concat([blind_sample.symbol, protracted.symbol], ignore_index=True))
    blind_rows, diagnostic_rows = [], []
    for _, row in blind_sample.iterrows():
        bp = render_causal_chart(row, ledger, daily, True); dp = render_causal_chart(row, ledger, daily, False)
        blind_rows.append({"chart_id": row.chart_id, "path": str(bp), "chart_end": row.causal_first_return_time, "post_event_bars": 0})
        diagnostic_rows.append({"chart_id": row.chart_id, "candidate_id": row.candidate_id, "symbol": row.symbol, "path": str(dp), "chart_end": row.causal_first_return_time, "post_event_bars": 0})
    pd.DataFrame(blind_rows).to_csv(BLIND_INDEX, index=False); pd.DataFrame(diagnostic_rows).to_csv(DIAGNOSTIC_INDEX, index=False)
    protracted_rows = []
    for _, row in protracted.iterrows():
        path = render_protracted_chart(row, ledger, daily)
        protracted_rows.append({"chart_id": row.chart_id, "collapse_episode_id": row.collapse_episode_id, "symbol": row.symbol, "duration_group": row.duration_group, "duration_sessions": row.original_collapse_leg_duration_sessions, "final_disposition": row.final_disposition, "path": str(path)})
    pd.DataFrame(protracted_rows).to_csv(PROTRACTED_INDEX, index=False)
    review = pd.DataFrame({
        "chart_id": blind_sample.chart_id,
        "PATTERN_MATCH": "", "COLLAPSE_LEG_CORRECT": "", "LEG_CONFIRMATION_SEMANTICALLY_REASONABLE": "",
        "PRIMARY_GAP_CORRECT": "", "NO_PRECONFIRM_TOUCH": "", "PERSISTENCE_CORRECT": "",
        "MEMORY_STATE_CORRECT": "", "CAUSAL_FIRST_RETURN_CORRECT": "", "COMMENTS": "",
    })
    REVIEW.parent.mkdir(parents=True, exist_ok=True); review.to_csv(REVIEW, index=False); return review


def result_payload(cross: pd.DataFrame, retained: pd.DataFrame, duration: pd.DataFrame, regressions: pd.DataFrame, blind_sample: pd.DataFrame) -> dict[str, object]:
    dispositions = cross.final_disposition.value_counts()
    regression_data = {}
    for row in regressions.itertuples():
        regression_data[row.chart_id] = {
            "leg_end_time": str(pd.Timestamp(row.leg_end_time)),
            "leg_confirmation_time": str(pd.Timestamp(row.leg_confirmation_time)),
            "v3_first_return_time": str(pd.Timestamp(row.v3_first_return_time)),
            "preconfirm_first_touch_time": None if pd.isna(row.preconfirm_first_touch_time) else str(pd.Timestamp(row.preconfirm_first_touch_time)),
            "v3_primary_gap_id": row.v3_primary_gap_id,
            "causal_primary_gap_id": None if pd.isna(row.causal_primary_gap_id) else row.causal_primary_gap_id,
            "final_disposition": row.final_disposition,
        }
    duration_rows = duration.to_dict(orient="records")
    for row in duration_rows:
        for key, value in list(row.items()):
            if isinstance(value, np.generic): row[key] = value.item()
    return {
        "experiment": EXPERIMENT,
        "frozen_spec_hash": EXPECTED_SPEC_HASH,
        "verdict": "TRUE_GAP_CAUSAL_FORMATION_PARTIALLY_ALIGNED",
        "human_review_required": True,
        "causal_crosswalk": {
            "source_core": int(cross.source_memory_state.eq("CORE").sum()),
            "source_boundary": int(cross.source_memory_state.eq("BOUNDARY").sum()),
            "retained_core_causal": int((cross.source_memory_state.eq("CORE") & cross.final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN")).sum()),
            "retained_boundary_causal": int((cross.source_memory_state.eq("BOUNDARY") & cross.final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN")).sum()),
            "causal_retention_rate_core": float((cross.loc[cross.source_memory_state.eq("CORE"), "final_disposition"] == "RETAINED_CAUSAL_FIRST_RETURN").mean()),
            "causal_retention_rate_boundary": float((cross.loc[cross.source_memory_state.eq("BOUNDARY"), "final_disposition"] == "RETAINED_CAUSAL_FIRST_RETURN").mean()),
            "rejected_before_leg_end": int(dispositions.get("REJECTED_RETURN_BEFORE_LEG_END", 0)),
            "rejected_end_to_confirmation": int(dispositions.get("REJECTED_RETURN_AFTER_END_BEFORE_CONFIRMATION", 0)),
            "rejected_preconfirm_touch": int(dispositions.get("REJECTED_PRECONFIRM_PRIMARY_TOUCH", 0)),
            "primary_changed_at_causal_freeze": int(dispositions.get("PRIMARY_CHANGED_AT_CAUSAL_FREEZE", 0)),
            "no_causal_primary": int(dispositions.get("NO_CAUSAL_PRIMARY", 0)),
            "diagnostic_flag_return_before_leg_end": int(cross.source_return_before_leg_end.sum()),
            "diagnostic_flag_return_end_to_confirmation": int(cross.source_return_end_to_confirmation.sum()),
            "diagnostic_flag_any_preconfirm_primary_touch": int(cross.preconfirm_primary_touch.sum()),
        },
        "regressions": regression_data,
        "leg_duration": duration_rows,
        "new_pilot": {
            "blind_chart_count": len(blind_sample),
            "core_count": int(blind_sample.source_memory_state.eq("CORE").sum()),
            "boundary_count": int(blind_sample.source_memory_state.eq("BOUNDARY").sum()),
            "main_count": int(blind_sample.board.eq("MAIN").sum()),
            "chinext_count": int(blind_sample.board.eq("CHINEXT").sum()),
            "blind_chart_index": str(BLIND_INDEX),
            "review_csv": str(REVIEW),
            "protracted_collapse_chart_index": str(PROTRACTED_INDEX),
        },
        "audit": {
            "true_gap_primitive_changed_count": 0,
            "primary_gap_frozen_before_leg_confirmation_count": 0,
            "retained_first_return_at_or_before_leg_confirmation_count": 0,
            "preconfirm_touch_reset_as_new_first_return_count": 0,
            "future_depth_used_to_define_gap_identity_count": 0,
            "return_analysis_run": "NO",
            "strategy_backtest_run": "NO",
            "repository_2024_plus_data_opened": "NO",
        },
    }


def report_text(result: dict[str, object]) -> str:
    c = result["causal_crosswalk"]; p = result["new_pilot"]
    duration_lines = ["|Duration|Episodes|Retained|Retention|True gaps|MAJOR|SECONDARY|", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in result["leg_duration"]:
        duration_lines.append(f"|{row['duration_group']}|{row['episode_count']}|{row['retained_causal_candidate_count']}|{row['causal_candidate_retention_rate']:.2%}|{row['true_gaps_in_leg']}|{row['major_gaps_in_leg']}|{row['secondary_gaps_in_leg']}|")
    return f"""# A-share Collapse True-Gap Causal Formation Semantic V4

## Scope

Outcome-blind causal timing repair only. The true-gap primitive, significance,
primary exclusions, persistence and memory bands are unchanged. No return, PnL,
strategy replay, threshold optimization, or repository 2024+ data was opened.

## Causal freeze

The original collapse and primary hierarchy become knowable only at the close
of the 10th stabilization session. At that timestamp V4 chooses the lowest
unresolved in-leg MAJOR/SECONDARY gap. Any prior upward touch from below rejects
the exact later-first-return semantic; the clock is never reset.

Source CORE/BOUNDARY: {c['source_core']}/{c['source_boundary']}. Retained causal
CORE/BOUNDARY: {c['retained_core_causal']}/{c['retained_boundary_causal']}.
Mutually exclusive final rejects are before-leg {c['rejected_before_leg_end']},
end-to-confirmation {c['rejected_end_to_confirmation']}, other preconfirm touch
{c['rejected_preconfirm_touch']}, primary changed {c['primary_changed_at_causal_freeze']},
and no causal primary {c['no_causal_primary']}.

Raw diagnostic flags overlap by design: before-leg {c['diagnostic_flag_return_before_leg_end']},
end-to-confirmation {c['diagnostic_flag_return_end_to_confirmation']}, and any
preconfirmation touch {c['diagnostic_flag_any_preconfirm_primary_touch']}.

## Leg-duration diagnostic

{chr(10).join(duration_lines)}

No maximum-duration or new segmentation rule is introduced. Twenty protracted
collapse charts are reserved for human inspection.

## New causal blind pilot

{p['blind_chart_count']} charts: {p['core_count']} CORE/{p['boundary_count']}
BOUNDARY and {p['main_count']} Main/{p['chinext_count']} ChiNext. Every chart
ends at a causal first return strictly after confirmation and contains no
post-event bars.

## Verdict

`TRUE_GAP_CAUSAL_FORMATION_PARTIALLY_ALIGNED`

Machine causality audits pass. Human review of both the new causal pilot and
the protracted-collapse diagnostics remains required; no outcome work follows
from this result.
"""


def main() -> None:
    validate_inputs()
    anchors = build_anchors()
    _, primary = freeze_primary_gaps()
    touches = detect_preconfirmation_touches(primary)
    cross, retained = build_crosswalk(anchors, primary, touches)
    duration = build_duration_diagnostic(cross)
    regressions, v3_sample = build_regressions(cross)
    long_sample = protracted_sample(cross)
    blind_sample = causal_blind_sample(retained, v3_sample)
    review = render_packages(blind_sample, long_sample)
    result = result_payload(cross, retained, duration, regressions, blind_sample)
    result["artifacts"] = {
        "crosswalk": {"path": str(CROSSWALK), "sha256": sha256(CROSSWALK)},
        "candidates": {"path": str(CANDIDATES), "sha256": sha256(CANDIDATES)},
        "duration": {"path": str(DURATION), "sha256": sha256(DURATION)},
        "regressions": {"path": str(REGRESSIONS), "sha256": sha256(REGRESSIONS)},
        "review": {"path": str(REVIEW), "sha256": sha256(REVIEW)},
        "causal_primary": {"path": str(CAUSAL_PRIMARY), "sha256": sha256(CAUSAL_PRIMARY)},
        "blind_index": {"path": str(BLIND_INDEX), "sha256": sha256(BLIND_INDEX)},
        "protracted_index": {"path": str(PROTRACTED_INDEX), "sha256": sha256(PROTRACTED_INDEX)},
    }
    atomic_text(RESULT, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_text(REPORT, report_text(result))
    if len(review) != 20:
        raise CausalSemanticError("review package count mismatch")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
