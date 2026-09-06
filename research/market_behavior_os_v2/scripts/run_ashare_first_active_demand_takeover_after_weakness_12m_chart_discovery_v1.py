#!/usr/bin/env python3
"""Build and replay the frozen high-recall active-demand mother, then render every path."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts


EXPERIMENT = "ASHARE-FIRST-ACTIVE-DEMAND-TAKEOVER-AFTER-WEAKNESS-12M-CHART-DISCOVERY-V1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "f39176f752aabbb340aa39bcd9f4caacbc889c073d95ae3f4716872e39c17b12"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = (
    DATA_ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
REGIME = (
    DATA_ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1"
    / "stage_a/causal_market_regime_2014_2023.parquet"
)
EXT_ROOT = DATA_ROOT / "ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1" / "development_2014_2020"
CANDIDATES = EXT_ROOT / "candidates_frozen.parquet"
OUTCOMES = EXT_ROOT / "outcomes.parquet"
WINDOW_PANEL = EXT_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = EXT_ROOT / "review_ledger.parquet"
REVIEW_CSV = EXT_ROOT / "review_ledger.csv"
CHART_DIR = EXT_ROOT / "individual_charts"
CHART_INDEX = EXT_ROOT / "chart_index.csv"
SHEET_DIR = EXT_ROOT / "contact_sheets"
OUTCOME_SHEET_ROOT = EXT_ROOT / "review_sheets_by_outcome"
MANIFEST = EXT_ROOT / "manifest.json"

EXPECTED_SIGNALS = 1754
EXPECTED_ANNUAL = {2014: 115, 2015: 436, 2016: 199, 2017: 148, 2018: 322, 2019: 210, 2020: 324}


class ResearchError(RuntimeError):
    """Fail closed on identity, chronology, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def legal_state(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and bool(row.market_rule_valid)
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
    )


def same_lineage(row: Any, event: Any) -> bool:
    return bool(
        np.isfinite(float(row.invalid_step_cum))
        and np.isfinite(float(event.invalid_step_cum))
        and float(row.invalid_step_cum) == float(event.invalid_step_cum)
    )


def buyable_open(row: Any) -> bool:
    required = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in required)
        and float(row.open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    required = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in required)
        and float(row.open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_candidates() -> pd.DataFrame:
    if sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("frozen active-demand specification drift")
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    candidates = connection.execute(
        f"""
        WITH descriptors AS (
          SELECT d.*,
            median(turnover_fraction) OVER (
              PARTITION BY symbol ORDER BY cal_idx
              ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
            ) AS prior20_turn,
            CASE WHEN coord_high>coord_low
              THEN (coord_close-coord_low)/(coord_high-coord_low)
              ELSE NULL END AS close_location
          FROM read_parquet('{DAILY.as_posix()}') d
          WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
        ), raw AS (
          SELECT *,CASE WHEN
            current_valid AND hard_valid AND trade_status=1
            AND current_day_data_tradable AND market_rule_valid
            AND corporate_action_valid AND NOT corporate_action_blocking
            AND step_return>=0.07 AND close_location>=0.80
            AND prior20_turn>0 AND turnover_fraction>0
            AND turnover_fraction>=2.0*prior20_turn AND ret20<=0.0
            AND round(close*100)<round(up_limit_price*100)
          THEN 1 ELSE 0 END AS raw_demand_flag
          FROM descriptors
        ), first_takeover AS (
          SELECT *,max(raw_demand_flag) OVER (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
          ) AS prior60_raw_demand
          FROM raw
        )
        SELECT
          'FADT-' || strftime(f.trade_date,'%Y%m%d') || '-' || replace(f.symbol,'.','') AS event_id,
          f.symbol,f.sleeve,f.industry,f.trade_date AS signal_date,f.cal_idx,
          f.invalid_step_cum,f.coord_open,f.coord_high,f.coord_low,f.coord_close,
          f.turnover_fraction,f.prior20_turn AS turn20,f.step_return,f.ret20,f.ret60,
          f.close_location,f.coord_open/f.prior_coord_close-1 AS open_gap,
          f.available_at,f.decision_at,
          r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
          r.market_median_ret60,r.market_positive_ret60_share,
          r.market_median_ret20-r.market_median_ret60 AS market_return_acceleration,
          r.market_positive_ret20_share-r.market_positive_ret60_share
            AS market_breadth_acceleration,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM first_takeover f
        JOIN read_parquet('{REGIME.as_posix()}') r ON f.trade_date=r.trade_date
        WHERE f.trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
          AND f.raw_demand_flag=1 AND coalesce(f.prior60_raw_demand,0)=0
        ORDER BY f.trade_date,f.sleeve,f.symbol
        """
    ).fetch_df()
    connection.close()
    for column in ("signal_date", "available_at", "decision_at", "market_latest_source_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != EXPECTED_SIGNALS or candidates.event_id.nunique() != EXPECTED_SIGNALS:
        raise ResearchError(f"expected {EXPECTED_SIGNALS} candidates, got {len(candidates)}")
    annual = candidates.groupby(candidates.signal_date.dt.year).size().to_dict()
    if annual != EXPECTED_ANNUAL:
        raise ResearchError(f"candidate frequency drift: {annual}")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("candidate source availability exceeds decision time")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("market state availability exceeds decision time")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered discovery")
    return candidates


def load_execution_paths(candidates: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register("events", candidates[["event_id", "symbol", "cal_idx"]])
    paths = connection.execute(
        f"""
        SELECT e.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol
         AND d.cal_idx BETWEEN e.cal_idx AND e.cal_idx+75
        ORDER BY e.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    return paths


def replay_one(event: Any, path: pd.DataFrame) -> dict[str, Any]:
    ordered = path.sort_values("cal_idx", kind="mergesort")
    entry: Any | None = None
    for row in ordered.loc[
        ordered.cal_idx.between(int(event.cal_idx) + 1, int(event.cal_idx) + 3)
    ].itertuples(index=False):
        if not same_lineage(row, event):
            return {"event_id": str(event.event_id), "status": "ENTRY_COORDINATE_LINEAGE_CHANGED"}
        if buyable_open(row):
            entry = row
            break
    if entry is None:
        return {"event_id": str(event.event_id), "status": "NO_LEGAL_ENTRY"}
    entry_price = float(entry.coord_open)
    target = entry_price * 1.15
    pending_time_stop = False
    exit_row: Any | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    for row in ordered.loc[ordered.cal_idx > int(entry.cal_idx)].itertuples(index=False):
        if not same_lineage(row, event):
            return {
                "event_id": str(event.event_id),
                "status": "EXIT_COORDINATE_LINEAGE_CHANGED",
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": int(entry.cal_idx),
                "entry_price": entry_price,
            }
        if pending_time_stop and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H30_TIME_STOP"
            break
        if legal_state(row) and np.isfinite(float(row.coord_high)) and float(row.coord_high) >= target:
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_15"
            break
        if legal_state(row) and int(row.cal_idx) >= int(entry.cal_idx) + 30:
            pending_time_stop = True
    if exit_row is None:
        return {
            "event_id": str(event.event_id),
            "status": "NO_COMPLETED_EXIT",
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": int(entry.cal_idx),
            "entry_price": entry_price,
        }
    gross = exit_price / entry_price - 1.0
    return {
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "sleeve": str(event.sleeve),
        "signal_date": pd.Timestamp(event.signal_date),
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": int(entry.cal_idx),
        "entry_price": entry_price,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
        "gross_return": gross,
        "net_return": gross - 0.004,
        "status": "COMPLETED",
    }


def replay(candidates: pd.DataFrame) -> pd.DataFrame:
    paths = load_execution_paths(candidates)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(event, groups[str(event.event_id)])
        for event in candidates.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows)
    if outcomes.event_id.duplicated().any() or len(outcomes) != len(candidates):
        raise ResearchError("outcome identity drift")
    return outcomes


def configure_charts() -> None:
    charts.EXPERIMENT = EXPERIMENT
    charts.DAILY = DAILY
    charts.EXT_ROOT = EXT_ROOT
    charts.CHART_DIR = CHART_DIR
    charts.SHEET_DIR = SHEET_DIR
    charts.OUTCOME_SHEET_ROOT = OUTCOME_SHEET_ROOT
    charts.WINDOW_PANEL = WINDOW_PANEL
    charts.REVIEW_LEDGER = REVIEW_LEDGER
    charts.REVIEW_CSV = REVIEW_CSV
    charts.CHART_INDEX = CHART_INDEX


def chart_path_features(
    event: pd.Series,
    frame: pd.DataFrame,
    outcome: pd.Series | None,
    cluster_count: int,
) -> dict[str, Any]:
    ordered = frame.sort_values("cal_idx", kind="mergesort")
    valid = ordered.loc[
        ordered.current_valid.fillna(False)
        & ordered[["coord_open", "coord_high", "coord_low", "coord_close"]].notna().all(axis=1)
    ].copy()
    signal_rows = valid.loc[valid.cal_idx.eq(int(event.cal_idx))]
    if len(signal_rows) != 1:
        raise ResearchError(f"{event.event_id}: signal chart bar not unique")
    signal = signal_rows.iloc[0]
    before = valid.loc[valid.cal_idx < int(event.cal_idx)].tail(126)
    if before.empty:
        raise ResearchError(f"{event.event_id}: no valid pre-signal chart bar")
    signal_close = float(signal.coord_close)
    prior20 = before.tail(20)
    prior60 = before.tail(60)
    returns20 = prior20.coord_close.pct_change().dropna()
    path_sum = float(returns20.abs().sum())
    endpoint = abs(float(prior20.coord_close.iloc[-1] / prior20.coord_close.iloc[0] - 1.0))
    efficiency = endpoint / path_sum if path_sum > 0 else math.nan
    prior_ranges = (prior20.coord_high - prior20.coord_low) / prior20.coord_close
    older = prior60.head(max(len(prior60) - 10, 1))
    older_ranges = (older.coord_high - older.coord_low) / older.coord_close
    recent_range = float(((prior20.tail(10).coord_high - prior20.tail(10).coord_low) / prior20.tail(10).coord_close).median())
    older_range = float(older_ranges.median())
    contraction = recent_range / older_range if older_range > 0 else math.nan
    signal_range = float(signal.coord_high - signal.coord_low)
    prior126_high = float(before.coord_high.max())
    prior126_low = float(before.coord_low.min())
    first_close = float(before.coord_close.iloc[0])
    prior5_high = float(before.tail(5).coord_high.max())
    net_return = math.nan if outcome is None else charts.safe_float(outcome.net_return)
    status = None if outcome is None else str(outcome.status)
    entry_date = pd.NaT if outcome is None or "entry_date" not in outcome else outcome.entry_date
    entry_price = math.nan if outcome is None or "entry_price" not in outcome else charts.safe_float(outcome.entry_price)
    exit_date = pd.NaT if outcome is None or "exit_date" not in outcome else outcome.exit_date
    exit_price = math.nan if outcome is None or "exit_price" not in outcome else charts.safe_float(outcome.exit_price)
    exit_reason = None if outcome is None or "exit_reason" not in outcome else outcome.exit_reason
    holding_sessions = math.nan if outcome is None or "holding_sessions" not in outcome else charts.safe_float(outcome.holding_sessions)
    return {
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "sleeve": str(event.sleeve),
        "signal_date": pd.Timestamp(event.signal_date),
        "signal_year": int(pd.Timestamp(event.signal_date).year),
        "chart_number": 0,
        "cluster_signal_count": int(cluster_count),
        "ret20": float(event.ret20),
        "ret60": float(event.ret60),
        "pre126_return": signal_close / first_close - 1.0,
        "pre126_drawdown_from_high": signal_close / prior126_high - 1.0,
        "pre126_position": ((signal_close - prior126_low) / (prior126_high - prior126_low)) if prior126_high > prior126_low else math.nan,
        "pre20_path_efficiency": efficiency,
        "pre20_down_day_fraction": float((returns20 < 0).mean()),
        "pre20_median_range_pct": float(prior_ranges.median()),
        "pre60_range_contraction": contraction,
        "open_gap": float(event.open_gap),
        "signal_step_return": float(event.step_return),
        "signal_close_location": float(event.close_location),
        "signal_body_fraction": ((float(signal.coord_close) - float(signal.coord_open)) / signal_range) if signal_range > 0 else math.nan,
        "signal_range_to_prior20_median": ((signal_range / signal_close) / float(prior_ranges.median())) if float(prior_ranges.median()) > 0 else math.nan,
        "signal_turnover_ratio": float(event.turnover_fraction / event.turn20),
        "signal_close_vs_prior5_high": signal_close / prior5_high - 1.0,
        "status": status,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": holding_sessions,
        "net_return": net_return,
        "outcome_bucket": charts.outcome_bucket(status, net_return),
    }


def build_chart_ledger(
    candidates: pd.DataFrame,
    outcomes: pd.DataFrame,
    windows: pd.DataFrame,
) -> pd.DataFrame:
    outcome_lookup = {
        str(row.event_id): row for _, row in outcomes.iterrows()
    }
    window_lookup = {key: part for key, part in windows.groupby("event_id", sort=False)}
    cluster = candidates.groupby("signal_date").size()
    rows = []
    for _, event in candidates.iterrows():
        rows.append(
            chart_path_features(
                event,
                window_lookup[str(event.event_id)],
                outcome_lookup.get(str(event.event_id)),
                int(cluster[pd.Timestamp(event.signal_date)]),
            )
        )
    ledger = pd.DataFrame(rows).sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    return ledger


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise ResearchError(f"{event.event_id}: chart signal row not unique")
    signal_close = float(signal.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = charts.plt.subplots(
        2,1,figsize=(13.2,7.4),gridspec_kw={"height_ratios":[4.4,1.0],"hspace":0.05},sharex=True
    )
    charts.draw_candles(price_ax, frame, signal_close)
    signal_x = charts.mdates.date2num(signal_date.to_pydatetime())
    price_ax.axvline(signal_x,color="#b45309",linewidth=1.3,label="active-demand takeover")
    price_ax.axhline(100.0,color="#b45309",linewidth=0.7,linestyle=":",label="signal close")
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x=charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        price_ax.scatter(entry_x,float(event.entry_price)*100.0/signal_close,marker="^",s=65,color="#7b2cbf",zorder=8,label="entry")
        price_ax.axhline(float(event.entry_price)*1.15*100.0/signal_close,color="#ff7f0e",linewidth=0.75,linestyle="--",label="+15% target")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x=charts.mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        price_ax.scatter(exit_x,float(event.exit_price)*100.0/signal_close,marker="v",s=65,color="#111111",zorder=8,label="exit")
    state=str(event.market_regime)
    if state=="BULL":
        state += "_ACCEL" if float(event.market_return_acceleration)>=0 else "_DECEL"
    status=str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):
        status += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | {state} | {status}\n"
        f"demand day {float(event.signal_step_return):+.1%} | prior20 {float(event.ret20):+.1%} | "
        f"turn/20med {float(event.signal_turnover_ratio):.2f}x | close-loc {float(event.signal_close_location):.0%} | "
        f"market r20/r60 {float(event.market_median_ret20):+.1%}/{float(event.market_median_ret60):+.1%} | same-date {int(event.cluster_signal_count)}",
        fontsize=10.0,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17,linewidth=0.5)
    handles,labels=price_ax.get_legend_handles_labels()
    by_label=dict(zip(labels,handles,strict=False))
    price_ax.legend(by_label.values(),by_label.keys(),loc="upper left",ncol=5,fontsize=7.0)
    valid_turn=frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates=charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates,valid_turn.turnover_fraction*100.0,width=0.75,color="#8b8b8b",alpha=0.55)
    volume_ax.axvline(signal_x,color="#b45309",linewidth=1.0)
    volume_ax.set_ylabel("Turnover %")
    volume_ax.grid(alpha=0.12,linewidth=0.4)
    volume_ax.xaxis.set_major_locator(charts.mdates.MonthLocator(interval=2))
    volume_ax.xaxis.set_major_formatter(charts.mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():
        label.set_rotation(25);label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065,right=0.985,top=0.88,bottom=0.10)
    output.parent.mkdir(parents=True,exist_ok=True)
    figure.savefig(output,dpi=115,bbox_inches="tight",facecolor="white",metadata={"Creator":EXPERIMENT,"Title":str(event.event_id)})
    charts.plt.close(figure)


def render_worker(payload: tuple[dict[str, Any],pd.DataFrame,str]) -> dict[str, Any]:
    event_dict,frame,output_text=payload
    event=pd.Series(event_dict);output=Path(output_text)
    render_chart(event,frame,output)
    return {"chart_number":int(event.chart_number),"event_id":str(event.event_id),"symbol":str(event.symbol),"signal_date":pd.Timestamp(event.signal_date),"outcome_bucket":str(event.outcome_bucket),"net_return":charts.safe_float(event.net_return),"chart_path":str(output)}


def build_nine_up(index: pd.DataFrame, root: Path, prefix: str) -> list[Path]:
    root.mkdir(parents=True,exist_ok=True);rows=index.to_dict("records");paths=[]
    for start in range(0,len(rows),9):
        group=rows[start:start+9];canvas=Image.new("RGB",(3600,2130),"white");draw=ImageDraw.Draw(canvas)
        for offset,row in enumerate(group):
            source=Image.open(row["chart_path"]).convert("RGB");source.thumbnail((1180,680),Image.Resampling.LANCZOS)
            canvas.paste(source,(10+(offset%3)*1195,35+(offset//3)*695));source.close()
        sheet_no=start//9+1;draw.text((15,8),f"{prefix} | sheet {sheet_no:03d} | events {start+1}-{start+len(group)}",fill="black")
        target=root/f"sheet_{sheet_no:03d}.jpg";canvas.save(target,"JPEG",quality=90,optimize=True);paths.append(target)
    return paths


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete=frame.loc[frame.status.eq("COMPLETED")].copy();values=pd.to_numeric(complete.net_return,errors="coerce")
    counts=frame.groupby("signal_date").size() if not frame.empty else pd.Series(dtype=float)
    return {
        "signals":int(len(frame)),"completed":int(len(complete)),"independent_signal_dates":int(frame.signal_date.nunique()),
        "mean_net":None if complete.empty else float(values.mean()),"median_net":None if complete.empty else float(values.median()),
        "positive_rate":None if complete.empty else float(values.gt(0).mean()),"severe_loss_rate":None if complete.empty else float(values.le(-0.10).mean()),
        "target_hit_rate":None if complete.empty else float(complete.exit_reason.fillna("").str.startswith("TARGET").mean()),
        "average_holding_sessions":None if complete.empty else float(complete.holding_sessions.mean()),
        "largest_date_share":None if frame.empty else float(counts.max()/len(frame)),"top_five_date_share":None if frame.empty else float(counts.nlargest(5).sum()/len(frame)),
    }


def run(workers: int, skip_render: bool) -> dict[str, Any]:
    for path in (FREEZE,DAILY,REGIME):
        if not path.is_file(): raise ResearchError(f"missing input {path}")
    candidates=load_candidates();outcomes=replay(candidates)
    write_parquet(candidates,CANDIDATES);write_parquet(outcomes,OUTCOMES)
    configure_charts();windows=charts.load_windows(candidates);ledger=build_chart_ledger(candidates,outcomes,windows)
    extras=candidates[["event_id","market_regime","market_median_ret20","market_positive_ret20_share","market_median_ret60","market_positive_ret60_share","market_return_acceleration","market_breadth_acceleration"]]
    ledger=ledger.merge(extras,on="event_id",how="left",validate="one_to_one")
    write_parquet(windows,WINDOW_PANEL);write_parquet(ledger,REVIEW_LEDGER);ledger.to_csv(REVIEW_CSV,index=False,float_format="%.10g")
    contact=[];outcome_sheets=[]
    if not skip_render:
        groups={key:part for key,part in windows.groupby("event_id",sort=False)};tasks=[]
        for _,event in ledger.iterrows():
            target=CHART_DIR/f"{int(event.chart_number):04d}_{event.symbol.replace('.','_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            tasks.append((event.to_dict(),groups[str(event.event_id)],str(target)))
        with ProcessPoolExecutor(max_workers=max(1,workers)) as executor:
            index=pd.DataFrame(list(executor.map(render_worker,tasks,chunksize=1)))
        index.to_csv(CHART_INDEX,index=False,float_format="%.10g")
        contact=build_nine_up(index,SHEET_DIR,EXPERIMENT)
        for bucket in ("SEVERE_LOSS","LOSS_0_TO_10PCT","PROFIT_0_TO_4PCT","PROFIT_GE_4PCT","NO_COMPLETED_TRADE"):
            subset=index.loc[index.outcome_bucket.eq(bucket)].sort_values(["signal_date","symbol","event_id"],kind="mergesort")
            outcome_sheets.extend(build_nine_up(subset,OUTCOME_SHEET_ROOT/bucket.lower(),bucket))
    complete=ledger.loc[ledger.status.eq("COMPLETED")].copy()
    annual={str(year):metrics(ledger.loc[ledger.signal_year.eq(year)]) for year in range(2014,2021)}
    market={state:metrics(ledger.loc[ledger.market_regime.eq(state)]) for state in ("BULL","TRANSITION","BEAR")}
    manifest={
        "experiment":EXPERIMENT,"freeze_sha256":sha256(FREEZE),"signals":len(ledger),"completed":len(complete),
        "charts":0 if skip_render else len(ledger),"contact_sheets":len(contact),"outcome_sheets":len(outcome_sheets),
        "signal_dates":int(ledger.signal_date.nunique()),"symbols":int(ledger.symbol.nunique()),
        "annual":annual,"market_state":market,"pooled":metrics(ledger),
        "outcome_buckets":{str(k):int(v) for k,v in ledger.outcome_bucket.value_counts().items()},
        "max_signal_date":str(ledger.signal_date.max().date()),"max_exit_date":str(pd.to_datetime(complete.exit_date).max().date()),
        "max_chart_bar_date":str(pd.to_datetime(windows.trade_date).max().date()),
        "2021_signal_or_rule_read":"NO","2022_plus_read":"NO","future_market_return_used":False,"same_bar_entry":False,
        "candidate_sha256":sha256(CANDIDATES),"outcomes_sha256":sha256(OUTCOMES),"review_ledger_sha256":sha256(REVIEW_LEDGER),
    }
    canonical_json(MANIFEST,manifest);manifest["manifest_sha256"]=sha256(MANIFEST);return manifest


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--workers",type=int,default=6);parser.add_argument("--skip-render",action="store_true");args=parser.parse_args()
    print(json.dumps(run(args.workers,args.skip_render),ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
