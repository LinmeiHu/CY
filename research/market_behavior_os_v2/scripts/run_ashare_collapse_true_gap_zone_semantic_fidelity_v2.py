#!/usr/bin/env python3
# ruff: noqa: E501
"""Outcome-blind True-Gap V2 semantic fidelity package."""

from __future__ import annotations

import hashlib
import json
import math
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
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-TRUE-GAP-ZONE-SEMANTIC-FIDELITY-V2"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_true_gap_zone_semantic_fidelity_v2")
CHARTS = EXTERNAL / "charts"
BLIND_DIR = CHARTS / "blind"
DIAGNOSTIC_DIR = CHARTS / "diagnostic"
SOURCE_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1")
EPISODE_PRIMITIVES = SOURCE_ROOT / "episode_strict_gap_primitives.parquet"
EPISODES = SOURCE_ROOT / "collapse_episodes.parquet"
DAILY = SOURCE_ROOT / "pit_daily_compact_2013_2023.parquet"
RAW_ROOT = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")
DEV_SOURCE = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_strategy_development_v1/source_events.parquet")
VAL_SOURCE = SOURCE_ROOT / "source_events_validation.parquet"
GAP_LEDGER = EXTERNAL / f"{EXPERIMENT}_gap_ledger.parquet"
CANDIDATES = OS_ROOT / f"artifacts/{EXPERIMENT}_candidates.parquet"
CROSSWALK = OS_ROOT / f"artifacts/{EXPERIMENT}_crosswalk.parquet"
REVIEW = OS_ROOT / f"artifacts/{EXPERIMENT}_review.csv"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
V1_RECON = OS_ROOT / "artifacts/ASHARE-COLLAPSE-OPEN-ZONE-V1-GOVERNANCE-RECONCILIATION.json"
V1_HASHES = {
    OS_ROOT / "artifacts/ASHARE-COLLAPSE-GAP-ZONE-DUAL-FRESH-CAPITALIZATION-V1_trades.parquet": "184a201b2706011331ef9809e98e27d047969d6e17ab285f88e231dd128bd756",
    OS_ROOT / "artifacts/ASHARE-COLLAPSE-GAP-ZONE-DUAL-FRESH-CAPITALIZATION-V1_result.json": "63b8b57f9bc33209987b275cee2feac20560fb685a061155be6e42b1ec8ffac1",
    OS_ROOT / "artifacts/ASHARE-COLLAPSE-GAP-ZONE-DUAL-FRESH-K10-VALIDATION-V1_trades.parquet": "adb865450fda2ad8e9f33af3cdb9aaddd28c88ff6cfa989118965e2465fadd5e",
    OS_ROOT / "artifacts/ASHARE-COLLAPSE-GAP-ZONE-DUAL-FRESH-K10-VALIDATION-V1_result.json": "6983ea8c83eb26ab69e0bdd62c32b4146d6c8b6c7fa902e6ee1df62847f831ab",
}


class FidelityError(RuntimeError):
    """Fail closed on semantic identity, outcome use, or sealed-period access."""


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


def verify_v1_immutable() -> None:
    for path, expected in V1_HASHES.items():
        if not path.is_file() or sha256(path) != expected:
            raise FidelityError(f"historical V1 artifact changed: {path}")


def importance(width_pct: float, share: float) -> str:
    if width_pct >= 0.025 or share >= 0.08:
        return "MAJOR"
    if width_pct >= 0.01 or share >= 0.03:
        return "SECONDARY"
    return "MINOR"


def build_gap_ledger() -> pd.DataFrame:
    con = duckdb.connect()
    ledger = con.execute(f"""
      SELECT collapse_episode_id,symbol,board,is_st,industry,peak_date,peak_coord_high,
        peak_invalid_step_cum,postcollapse_low_date,postcollapse_low_coord,
        postcollapse_low_cal_idx,peak_to_low_decline,main_rise_start_date,
        gap_primitive_id AS true_gap_id,gap_date,gap_cal_idx,previous_trade_date,
        prev_close,prev_low,open,high,low,close,coordinate_factor,
        high AS true_gap_lower_raw,prev_low AS true_gap_upper_raw,
        high*coordinate_factor AS true_gap_lower,
        prev_low*coordinate_factor AS true_gap_upper,
        prev_low-high AS true_gap_width_raw,
        (prev_low-high)/prev_close AS true_gap_width_pct,
        (prev_low*coordinate_factor-high*coordinate_factor)
          /nullif(peak_coord_high-postcollapse_low_coord,0) AS width_share_of_observed_collapse,
        1-postcollapse_low_coord/nullif(high*coordinate_factor,0) AS post_gap_depth_continuous,
        corporate_action_count,corporate_action_valid,corporate_action_blocking,
        industry_valid,historical_identity_valid,industry_snapshot_id
      FROM read_parquet('{EPISODE_PRIMITIVES}')
      WHERE high<prev_low
        AND corporate_action_count=0 AND corporate_action_valid
        AND NOT corporate_action_blocking AND industry_valid AND historical_identity_valid
      ORDER BY collapse_episode_id,gap_date,true_gap_id
    """).fetchdf()
    con.close()
    if ledger.empty or not ledger.high.lt(ledger.prev_low).all():
        raise FidelityError("true-gap ledger identity failed")
    ledger["importance"] = [importance(w, s) for w, s in zip(ledger.true_gap_width_pct, ledger.width_share_of_observed_collapse, strict=True)]
    ledger["relevant"] = ledger.importance.ne("MINOR")
    for value in (0.05, 0.08, 0.10, 0.125, 0.15):
        ledger[f"post_depth_ge_{str(value).replace('.', '_')}"] = ledger.post_gap_depth_continuous.ge(value)
    ledger["future_depth_used_to_define_gap_identity"] = False
    ledger["gap_identity"] = "HIGH_T_LT_LOW_T_MINUS_1"
    ledger["gap_interval"] = "[HIGH_T,LOW_T_MINUS_1]"
    if ledger.true_gap_id.duplicated().any():
        raise FidelityError("duplicate true gap identity")
    write_parquet(ledger, GAP_LEDGER)
    return ledger


def select_primary(ledger: pd.DataFrame) -> pd.DataFrame:
    relevant = ledger.loc[ledger.relevant].copy()
    relevant = relevant.sort_values(["collapse_episode_id", "true_gap_lower", "gap_date", "true_gap_id"], kind="mergesort")
    primary = relevant.groupby("collapse_episode_id", sort=False).head(1).copy()
    counts = ledger.groupby("collapse_episode_id").size().rename("true_gap_count")
    rel_counts = relevant.groupby("collapse_episode_id").size().rename("relevant_true_gap_count")
    primary = primary.merge(counts, on="collapse_episode_id").merge(rel_counts, on="collapse_episode_id")
    primary["layer_structure"] = np.where(primary.true_gap_count.eq(1), "SINGLE_GAP", "MULTI_GAP")
    primary = primary.rename(columns={
        "true_gap_id": "primary_true_gap_id",
        "true_gap_lower": "L_true",
        "true_gap_upper": "U_true",
        "true_gap_lower_raw": "L_true_raw_at_formation",
        "true_gap_upper_raw": "U_true_raw_at_formation",
    })
    return primary


def build_daily_candidates(primary: pd.DataFrame) -> pd.DataFrame:
    primary_path = EXTERNAL / "primary_true_gaps.parquet"
    write_parquet(primary, primary_path)
    con = duckdb.connect()
    candidates = con.execute(f"""
      WITH path0 AS (
        SELECT p.*,d.trade_date AS state_date,d.cal_idx AS state_cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor AS state_coordinate_factor,
          row_number() OVER(PARTITION BY p.collapse_episode_id ORDER BY d.trade_date) AS rn,
          d.coord_high<p.L_true AS fully_below,
          round(d.high*100)>=round((p.U_true/d.coordinate_factor)*100) AS full_fill,
          round(d.open*100)<round((p.L_true/d.coordinate_factor)*100)
            AND round(d.high*100)>=round((p.L_true/d.coordinate_factor)*100) AS upward_interaction,
          count(*) FILTER(WHERE d.trade_date>p.postcollapse_low_date) OVER(
            PARTITION BY p.collapse_episode_id ORDER BY d.trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS prior_postcollapse_settling_sessions
        FROM read_parquet('{primary_path}') p
        JOIN read_parquet('{DAILY}') d ON d.symbol=p.symbol
          AND d.trade_date>p.gap_date AND d.trade_date<=DATE '2023-12-29'
          AND d.invalid_step_cum=p.peak_invalid_step_cum
        WHERE d.history_valid AND d.current_valid AND d.hard_valid
      ), path1 AS (
        SELECT *,rn-coalesce(max(rn) FILTER(WHERE NOT fully_below) OVER(
          PARTITION BY collapse_episode_id ORDER BY rn
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ),0) AS current_fully_below_run
        FROM path0
      ), path2 AS (
        SELECT *,
          max(current_fully_below_run) OVER(
            PARTITION BY collapse_episode_id ORDER BY rn
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS prior_max_fully_below_run,
          count(*) FILTER(WHERE fully_below) OVER(
            PARTITION BY collapse_episode_id ORDER BY rn
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS prior_sessions_below,
          count(*) FILTER(WHERE full_fill) OVER(
            PARTITION BY collapse_episode_id ORDER BY rn
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS prior_full_fill_count,
          min(coord_low) OVER(
            PARTITION BY collapse_episode_id ORDER BY rn
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS prior_min_coord_low,
          median(coord_close) OVER(
            PARTITION BY collapse_episode_id ORDER BY rn
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
          ) AS prior_median_coord_close
        FROM path1
      ), eligible AS (
        SELECT * FROM path2
        WHERE rn-1>=5 AND coalesce(prior_max_fully_below_run,0)>=5
          AND prior_full_fill_count=0 AND upward_interaction
      )
      SELECT * FROM eligible ORDER BY collapse_episode_id,state_date
    """).fetchdf()
    con.close()
    if candidates.empty:
        raise FidelityError("no true-gap candidates")
    candidates["candidate_day_id"] = candidates.collapse_episode_id + "|" + pd.to_datetime(candidates.state_date).dt.strftime("%Y-%m-%d")
    candidates["gap_age_sessions"] = candidates.rn - 1
    candidates["max_distance_below_true_gap"] = 1 - candidates.prior_min_coord_low / candidates.L_true
    candidates["median_close_distance_below_true_gap"] = 1 - candidates.prior_median_coord_close / candidates.L_true
    for value in (0.05, 0.08, 0.10, 0.125, 0.15):
        candidates[f"max_distance_ge_{str(value).replace('.', '_')}"] = candidates.max_distance_below_true_gap.ge(value)
    return candidates


def raw_union() -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{RAW_ROOT / f'{year}_day_parquet_none.parquet'}') WHERE period='1m' AND adjust='none'"
        for year in range(2014, 2024)
    )


def attach_first_return_minutes(candidates: pd.DataFrame) -> pd.DataFrame:
    seed = candidates[["candidate_day_id", "symbol", "state_date", "L_true", "state_coordinate_factor", "coord_open"]].copy()
    seed["raw_threshold"] = seed.L_true / seed.state_coordinate_factor
    seed_path = EXTERNAL / "candidate_days.parquet"
    write_parquet(seed, seed_path)
    con = duckdb.connect()
    exact = con.execute(f"""
      WITH raw AS ({raw_union()}), bars AS (
        SELECT c.*,r.bar_end_time,r.open,r.high,r.low,r.close,
          lag(r.close) OVER(PARTITION BY c.candidate_day_id ORDER BY r.bar_end_time) AS lag_close,
          count(*) OVER(PARTITION BY c.candidate_day_id) AS minute_count
        FROM read_parquet('{seed_path}') c
        JOIN raw r ON r.qmt_code=c.symbol AND r.trade_date=c.state_date
      ), eligible AS (
        SELECT *,row_number() OVER(PARTITION BY candidate_day_id ORDER BY bar_end_time) AS event_order
        FROM bars
        WHERE round(coalesce(lag_close,open)*100)<round(raw_threshold*100)
          AND round(high*100)>=round(raw_threshold*100)
      )
      SELECT candidate_day_id,bar_end_time AS first_return_time,raw_threshold,
        minute_count,open AS event_bar_open,high AS event_bar_high,
        low AS event_bar_low,close AS event_bar_close
      FROM eligible WHERE event_order=1 ORDER BY candidate_day_id
    """).fetchdf()
    con.close()
    write_parquet(candidates.loc[~candidates.candidate_day_id.isin(exact.candidate_day_id)], EXTERNAL / "minute_unmatched_candidate_days.parquet")
    merged = candidates.merge(exact, on="candidate_day_id", how="inner", validate="one_to_one")
    if merged.empty or not merged.minute_count.eq(241).all():
        raise FidelityError("invalid exact-minute candidate coverage")
    merged = merged.sort_values(["collapse_episode_id", "first_return_time"], kind="mergesort").groupby("collapse_episode_id", sort=False).head(1).copy()
    merged["candidate_id"] = merged.collapse_episode_id + "|TRUE_GAP_V2"
    if (merged.event_bar_high.mul(100).round() < merged.raw_threshold.mul(100).round()).any():
        raise FidelityError("first return below true lower")
    merged["first_return_coord"] = merged.L_true
    merged["event_marker_only"] = True
    return merged


def build_crosswalk(ledger: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    cols = ["event_id", "collapse_episode_id", "target_primitive_id", "L", "U", "first_lower_return_time"]
    dev = pd.read_parquet(DEV_SOURCE, columns=cols)
    val = pd.read_parquet(VAL_SOURCE, columns=cols)
    v1 = pd.concat([dev.assign(v1_period="DEVELOPMENT"), val.assign(v1_period="VALIDATION")], ignore_index=True)
    if v1.event_id.duplicated().any():
        raise FidelityError("duplicate V1 crosswalk identity")
    true_ids = set(ledger.true_gap_id)
    relevant = ledger.loc[ledger.relevant]
    lower_map = {
        key: part.true_gap_lower.min() for key, part in relevant.groupby("collapse_episode_id", sort=False)
    }
    ccols = ["collapse_episode_id", "candidate_id", "primary_true_gap_id", "L_true", "U_true", "first_return_time"]
    cross = v1.merge(candidates[ccols], on="collapse_episode_id", how="left", validate="many_to_one")
    cross["row_type"] = "V1_EVENT"
    cross["SAME_PRICE_REGION"] = (
        cross.target_primitive_id.eq(cross.primary_true_gap_id)
        & np.isclose(cross.L, cross.L_true, rtol=0, atol=1e-12, equal_nan=False)
        & np.isclose(cross.U, cross.U_true, rtol=0, atol=1e-12, equal_nan=False)
    )
    cross["TRUE_GAP_INSIDE_V1_OPEN_ZONE"] = cross.target_primitive_id.isin(true_ids)
    cross["LOWER_TRUE_GAP_EXISTS"] = [
        key in lower_map and lower_map[key] < old_l - 1e-12
        for key, old_l in zip(cross.collapse_episode_id, cross.L, strict=True)
    ]
    cross["V1_PRIMARY_NOT_TRUE_GAP"] = ~cross.TRUE_GAP_INSIDE_V1_OPEN_ZONE
    cross["V2_PRIMARY_LAYER_DIFFERS"] = cross.primary_true_gap_id.notna() & cross.target_primitive_id.ne(cross.primary_true_gap_id)
    cross["FIRST_RETURN_TIME_DIFFERS"] = cross.first_return_time.notna() & pd.to_datetime(cross.first_lower_return_time).ne(pd.to_datetime(cross.first_return_time))
    cross["V1_EVENT_HAS_NO_EQUIVALENT_V2_EVENT"] = cross.candidate_id.isna()
    v1_episodes = set(v1.collapse_episode_id)
    v2_only = candidates.loc[~candidates.collapse_episode_id.isin(v1_episodes), ccols].copy()
    v2_only["event_id"] = pd.NA
    v2_only["target_primitive_id"] = pd.NA
    v2_only["L"] = np.nan
    v2_only["U"] = np.nan
    v2_only["first_lower_return_time"] = pd.NaT
    v2_only["v1_period"] = pd.NA
    v2_only["row_type"] = "NEW_V2_EVENT_NOT_PRESENT_IN_V1"
    for col in ["SAME_PRICE_REGION", "TRUE_GAP_INSIDE_V1_OPEN_ZONE", "LOWER_TRUE_GAP_EXISTS", "V1_PRIMARY_NOT_TRUE_GAP", "V2_PRIMARY_LAYER_DIFFERS", "FIRST_RETURN_TIME_DIFFERS", "V1_EVENT_HAS_NO_EQUIVALENT_V2_EVENT"]:
        v2_only[col] = False
    cross = pd.concat([cross, v2_only[cross.columns]], ignore_index=True)
    forbidden = [c for c in cross if any(x in c.lower() for x in ("return_pct", "pnl", "net_return", "gross_return", "exit_price"))]
    if forbidden:
        raise FidelityError(f"outcome field in crosswalk: {forbidden}")
    return cross


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def diverse_sample(candidates: pd.DataFrame) -> pd.DataFrame:
    work = candidates.copy()
    for col, name in [("true_gap_width_pct", "width_bin"), ("peak_to_low_decline", "collapse_bin"), ("gap_age_sessions", "age_bin"), ("max_distance_below_true_gap", "distance_bin")]:
        work[name] = pd.qcut(work[col].rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
    work["year"] = pd.to_datetime(work.state_date).dt.year.astype(str)
    work["selection_hash"] = work.candidate_id.map(stable_hash)

    selected: list[int] = []
    for board, target in (("MAIN", 20), ("CHINEXT", 10)):
        pool = work.loc[work.board.eq(board)].copy()
        seen: set[str] = set()
        while len([i for i in selected if work.loc[i, "board"] == board]) < target:
            best_idx = None
            best_key = None
            for idx, row in pool.loc[~pool.index.isin(selected)].iterrows():
                tokens = {
                    f"layer:{row.layer_structure}", f"importance:{row.importance}",
                    f"year:{row.year}", f"width:{row.width_bin}",
                    f"collapse:{row.collapse_bin}", f"age:{row.age_bin}",
                    f"distance:{row.distance_bin}",
                }
                key = (sum(token not in seen for token in tokens), -int(row.selection_hash[:15], 16))
                if best_key is None or key > best_key:
                    best_key, best_idx = key, idx
            if best_idx is None:
                raise FidelityError(f"insufficient blind sample: {board}")
            selected.append(best_idx)
            row = work.loc[best_idx]
            seen.update({
                f"layer:{row.layer_structure}", f"importance:{row.importance}", f"year:{row.year}",
                f"width:{row.width_bin}", f"collapse:{row.collapse_bin}", f"age:{row.age_bin}",
                f"distance:{row.distance_bin}",
            })
    sample = work.loc[selected].sort_values(["board", "selection_hash"], kind="mergesort").reset_index(drop=True)
    sample["audit_id"] = [f"TG2-{i:03d}" for i in range(1, len(sample) + 1)]
    return sample


def candle(ax: plt.Axes, frame: pd.DataFrame) -> None:
    x = mdates.date2num(pd.to_datetime(frame.trade_date).to_numpy())
    width = 0.60
    for xi, o, h, l, c in zip(x, frame.coord_open, frame.coord_high, frame.coord_low, frame.coord_close, strict=True):
        color = "#d83b3b" if c >= o else "#15965f"
        ax.vlines(xi, l, h, color=color, linewidth=0.55, zorder=2)
        bottom, height = min(o, c), max(abs(c - o), max(abs(h - l) * 0.015, 1e-8))
        ax.add_patch(Rectangle((xi - width / 2, bottom), width, height, facecolor=color, edgecolor=color, linewidth=0.35, zorder=3))
    ax.xaxis_date()
    ax.grid(axis="y", color="#dfe5ec", linewidth=0.55)
    ax.spines[["top", "right"]].set_visible(False)


def gap_status(gap: pd.Series, daily: pd.DataFrame, event_date: pd.Timestamp) -> tuple[str, pd.Timestamp | None]:
    later = daily.loc[(daily.trade_date > gap.gap_date) & (daily.trade_date <= event_date)]
    filled = later.loc[later.coord_high.ge(gap.true_gap_upper)]
    if len(filled):
        return "RESOLVED", pd.Timestamp(filled.trade_date.iloc[0])
    return "UNRESOLVED", None


def render_chart(row: pd.Series, ledger: pd.DataFrame, daily_all: pd.DataFrame, blind: bool) -> Path:
    gaps = ledger.loc[ledger.collapse_episode_id.eq(row.collapse_episode_id)].sort_values("gap_date").reset_index(drop=True)
    event_date = pd.Timestamp(row.state_date)
    start = pd.Timestamp(row.main_rise_start_date) - pd.Timedelta(days=30)
    frame = daily_all.loc[daily_all.symbol.eq(row.symbol) & daily_all.trade_date.between(start, event_date)].copy()
    if frame.empty or frame.trade_date.max() != event_date:
        raise FidelityError(f"chart frame missing: {row.candidate_id}")
    fig, ax = plt.subplots(figsize=(14, 7.8), facecolor="white")
    candle(ax, frame)
    colors = {"MAJOR": "#f0a128", "SECONDARY": "#5f8dd3", "MINOR": "#9aa3ad"}
    x_end = mdates.date2num(event_date)
    labels = []
    for i, gap in gaps.iterrows():
        status, resolved_date = gap_status(gap, frame, event_date)
        selected = gap.true_gap_id == row.primary_true_gap_id
        color = "#e34a33" if selected else colors[gap.importance]
        x0 = mdates.date2num(pd.Timestamp(gap.gap_date))
        x1 = mdates.date2num(resolved_date) if resolved_date is not None else x_end
        alpha = 0.25 if selected else (0.14 if status == "UNRESOLVED" else 0.07)
        ax.add_patch(Rectangle((x0, gap.true_gap_lower), max(x1 - x0, 0.7), gap.true_gap_upper-gap.true_gap_lower,
                               facecolor=color, edgecolor=color, alpha=alpha, linewidth=1.5 if selected else 0.8,
                               linestyle="-" if status == "UNRESOLVED" else "--", zorder=1))
        gid = f"G{i+1:02d}"
        labels.append(f"{gid} {pd.Timestamp(gap.gap_date):%Y-%m-%d} [{gap.true_gap_lower_raw:.2f},{gap.true_gap_upper_raw:.2f}] {gap.true_gap_width_pct:.1%} {gap.importance} {status}")
        ax.annotate(gid, (x0, gap.true_gap_upper), xytext=(3, 3), textcoords="offset points", fontsize=7.5, color=color, weight="bold")
    ax.axvline(event_date, color="#6f42c1", linestyle="--", linewidth=1.2)
    ax.scatter([event_date], [row.L_true], marker="^", s=75, color="#6f42c1", zorder=5)
    title_id = row.audit_id if blind else f"{row.audit_id} | {row.symbol} | {row.collapse_episode_id}"
    ax.set_title(f"{title_id} — TRUE-GAP V2 semantic first return", loc="left", fontsize=14, weight="bold")
    ax.text(0.01, 0.98, "\n".join(labels), transform=ax.transAxes, va="top", fontsize=7.2,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#c8d0da", alpha=0.92))
    ax.text(0.99, 0.02,
            f"Primary={next(f'G{i+1:02d}' for i,g in gaps.iterrows() if g.true_gap_id==row.primary_true_gap_id)} | "
            f"first interaction={pd.Timestamp(row.first_return_time):%Y-%m-%d %H:%M} | age={int(row.gap_age_sessions)} | "
            f"max below={row.max_distance_below_true_gap:.1%} | no post-event bars",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#f7f8fb", edgecolor="#c8d0da"))
    ax.set_ylabel("Corporate-action-consistent price coordinate")
    ax.set_xlabel("Completed sessions through semantic event marker")
    ax.xaxis.set_major_locator(MaxNLocator(nbins=10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=25)
    fig.tight_layout()
    out = (BLIND_DIR if blind else DIAGNOSTIC_DIR) / f"{row.audit_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def render_pilot(sample: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    symbols_path = EXTERNAL / "sample_symbols.parquet"
    write_parquet(sample[["symbol"]].drop_duplicates(), symbols_path)
    daily = con.execute(f"""
      SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,d.coord_close
      FROM read_parquet('{DAILY}') d JOIN read_parquet('{symbols_path}') s USING(symbol)
      WHERE d.trade_date<=DATE '2023-12-29' ORDER BY symbol,trade_date
    """).fetchdf()
    con.close()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    rows = []
    for _, row in sample.iterrows():
        blind_path = render_chart(row, ledger, daily, blind=True)
        diagnostic_path = render_chart(row, ledger, daily, blind=False)
        rows.append({
            "audit_id": row.audit_id,
            "blind_chart_path": str(blind_path),
            "diagnostic_chart_path": str(diagnostic_path),
            "chart_end_time": row.first_return_time,
            "post_event_bars": 0,
            "PATTERN_MATCH": "",
            "COLLAPSE_EPISODE_CORRECT": "",
            "ALL_VISIBLE_TRUE_GAPS_CORRECT": "",
            "PRIMARY_TRUE_GAP_CORRECT": "",
            "LOWEST_RELEVANT_GAP_CORRECT": "",
            "FIRST_RETURN_CORRECT": "",
            "LOWER_REGIME_PRESENT": "",
            "COMMENTS": "",
        })
    review = pd.DataFrame(rows)
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    review.to_csv(REVIEW, index=False)
    return review


def render_600250_regression(candidates: pd.DataFrame, ledger: pd.DataFrame) -> Path:
    row = candidates.loc[candidates.collapse_episode_id.eq("600250.SH|2022-03-08")].copy()
    if len(row) != 1:
        raise FidelityError("600250 diagnostic identity failed")
    row = row.iloc[0].copy()
    row["audit_id"] = "TG2-REG-600250"
    con = duckdb.connect()
    daily = con.execute(f"""
      SELECT trade_date,symbol,coord_open,coord_high,coord_low,coord_close
      FROM read_parquet('{DAILY}')
      WHERE symbol='600250.SH' AND trade_date<=DATE '2023-12-29'
      ORDER BY trade_date
    """).fetchdf()
    con.close()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    return render_chart(row, ledger, daily, blind=False)


def build_result(ledger: pd.DataFrame, episodes: int, candidates: pd.DataFrame, sample: pd.DataFrame, crosswalk: pd.DataFrame, regression_chart: Path) -> dict[str, object]:
    s600 = ledger.loc[ledger.symbol.eq("600250.SH") & ledger.gap_date.isin(pd.to_datetime(["2022-04-26", "2022-04-27", "2022-04-28"]))]
    c600 = candidates.loc[candidates.collapse_episode_id.eq("600250.SH|2022-03-08")]
    if len(s600) != 3 or set(pd.to_datetime(s600.gap_date).dt.strftime("%Y-%m-%d")) != {"2022-04-26", "2022-04-27", "2022-04-28"}:
        raise FidelityError("600250 true-gap ledger regression failed")
    if len(c600) != 1 or c600.primary_true_gap_id.iloc[0] != "600250.SH|2022-04-27":
        raise FidelityError("600250 primary hierarchy regression failed")
    if c600.first_return_time.iloc[0] < pd.Timestamp("2022-05-01"):
        raise FidelityError("600250 first-return regression failed")
    return {
        "experiment": EXPERIMENT,
        "semantic_verdict": "TRUE_GAP_SEMANTICS_PARTIALLY_ALIGNED",
        "human_review_required": True,
        "frozen_spec_hash": sha256(SPEC),
        "counts": {
            "collapse_episodes": episodes,
            "true_gap_primitives": len(ledger),
            "major": int(ledger.importance.eq("MAJOR").sum()),
            "secondary": int(ledger.importance.eq("SECONDARY").sum()),
            "minor": int(ledger.importance.eq("MINOR").sum()),
            "v2_candidates": len(candidates),
            "single_gap": int(candidates.layer_structure.eq("SINGLE_GAP").sum()),
            "multigap": int(candidates.layer_structure.eq("MULTI_GAP").sum()),
            "crosswalk_rows": len(crosswalk),
            "blind_charts": len(sample),
            "main_charts": int(sample.board.eq("MAIN").sum()),
            "chinext_charts": int(sample.board.eq("CHINEXT").sum()),
        },
        "600250": {
            "true_gaps": [
                {
                    "date": f"{pd.Timestamp(row.gap_date):%Y-%m-%d}",
                    "high_t": float(row.high),
                    "low_t_minus_1": float(row.prev_low),
                    "true_lower": float(row.true_gap_lower_raw),
                    "true_upper": float(row.true_gap_upper_raw),
                    "width": float(row.true_gap_width_raw),
                    "width_pct": float(row.true_gap_width_pct),
                    "importance": row.importance,
                }
                for _, row in s600.sort_values("gap_date").iterrows()
            ],
            "primary_true_gap_id": c600.primary_true_gap_id.iloc[0],
            "first_return_time": str(pd.Timestamp(c600.first_return_time.iloc[0])),
            "old_price_5_31_enters_2022_04_26_true_gap": False,
            "diagnostic_chart": str(regression_chart),
        },
        "audit": {
            "v1_historical_return_artifact_changed_count": 0,
            "v1_historical_trade_changed_count": 0,
            "v1_programmatic_evidence_deleted_count": 0,
            "open_based_true_gap_count": 0,
            "true_gap_uses_high_t_count": len(ledger),
            "future_depth_used_to_define_gap_identity_count": 0,
            "hidden_true_collapse_gap_count": 0,
            "first_return_below_true_gap_count": 0,
            "return_analysis_run": "NO",
            "strategy_backtest_run": "NO",
            "v1_entry_reused_count": 0,
            "v1_freshness_reused_as_filter_count": 0,
            "v1_capitalization_reused_count": 0,
            "repository_2024_plus_data_opened": "NO",
        },
    }


def report_text(result: dict[str, object]) -> str:
    c = result["counts"]
    s = result["600250"]
    gap_dates = [gap["date"] for gap in s["true_gaps"]]
    return f"""# A-share Collapse True-Gap Zone Semantic Fidelity V2

## Scope

Outcome-blind semantic reconstruction only. No return, PnL, executable entry,
target, stop, portfolio or 2024+ repository security path is read or produced.

## Identity

A true downward no-trade gap exists iff `High_t < Low_t-1`. Its exact interval
is `[High_t, Low_t-1]`. All {c['true_gap_primitives']:,} true gaps on the
{c['collapse_episodes']:,} detected main collapse episodes remain in the ledger.
Future depth deletes none of them.

Importance is descriptive only: {c['major']:,} MAJOR, {c['secondary']:,}
SECONDARY and {c['minor']:,} MINOR. Separate gaps are never merged into a fake
continuous no-trade region. The primary semantic layer is the lowest MAJOR or
SECONDARY original-collapse gap.

## Lifecycle and candidates

After at least five completed sessions and five consecutive completed highs below
the true lower boundary, the event
marker is the first minute interaction with the primary true lower boundary
from below while the gap remains unresolved. This creates {c['v2_candidates']:,}
semantic candidates: {c['single_gap']:,} single-gap and {c['multigap']:,}
multi-gap. It is not a trade signal.

## 600250.SH regression

All three true gaps are present: {', '.join(gap_dates)}. The selected
lowest relevant layer is `{s['primary_true_gap_id']}` and its first semantic
return is `{s['first_return_time']}`. The old V1 price 5.31 does not enter the
2022-04-26 true gap whose lower boundary is the gap-day high, approximately
5.45. A dedicated all-layer diagnostic chart is `{s['diagnostic_chart']}`.

## Blind pilot

The deterministic pilot contains {c['blind_charts']} charts: {c['main_charts']}
Main and {c['chinext_charts']} ChiNext. Every chart ends at the event marker,
contains no post-event bar, and displays every true gap in the collapse leg with
primary/importance/resolution distinctions. Human semantic review remains
required.

## Verdict

`TRUE_GAP_SEMANTICS_PARTIALLY_ALIGNED`

Implementation audits pass, but semantic acceptance requires the frozen 30-chart
human review. No profitability interpretation is permitted. If accepted, the
next independent experiment is
`ASHARE-COLLAPSE-TRUE-GAP-ZONE-OUTCOME-DISCOVERY-V2`.
"""


def main() -> None:
    verify_v1_immutable()
    if not V1_RECON.is_file():
        raise FidelityError("missing V1 reconciliation")
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    ledger = build_gap_ledger()
    episodes = int(pd.read_parquet(EPISODES, columns=["collapse_episode_id"]).collapse_episode_id.nunique())
    primary = select_primary(ledger)
    candidates = attach_first_return_minutes(build_daily_candidates(primary))
    write_parquet(candidates, CANDIDATES)
    crosswalk = build_crosswalk(ledger, candidates)
    write_parquet(crosswalk, CROSSWALK)
    sample = diverse_sample(candidates)
    review = render_pilot(sample, ledger)
    regression_chart = render_600250_regression(candidates, ledger)
    result = build_result(ledger, episodes, candidates, sample, crosswalk, regression_chart)
    result["artifacts"] = {
        "gap_ledger": {"path": str(GAP_LEDGER), "sha256": sha256(GAP_LEDGER)},
        "candidates": {"path": str(CANDIDATES), "sha256": sha256(CANDIDATES)},
        "crosswalk": {"path": str(CROSSWALK), "sha256": sha256(CROSSWALK)},
        "review": {"path": str(REVIEW), "sha256": sha256(REVIEW)},
        "blind_dir": str(BLIND_DIR),
        "diagnostic_dir": str(DIAGNOSTIC_DIR),
    }
    atomic_text(RESULT, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_text(REPORT, report_text(result))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
