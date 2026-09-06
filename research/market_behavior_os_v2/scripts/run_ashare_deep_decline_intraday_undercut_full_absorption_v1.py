#!/usr/bin/env python3
"""Build the frozen intraday-undercut/full-absorption chart-discovery panel.

Signal identities are built through 2021, but this stage attaches outcomes and
renders charts only for 2014-2020 signals.  The 2021 cohort remains unavailable
to chart-rule formation and is reserved for one frozen-rule confirmation.
"""

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

import run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-DEEP-DECLINE-INTRADAY-UNDERCUT-FULL-ABSORPTION-V1"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_deep_decline_intraday_undercut_full_absorption_v1"
)
CANDIDATES = EXT_ROOT / "stage_a/frozen_candidates_2014_2021.parquet"
OUTCOMES = EXT_ROOT / "chart_discovery_2014_2020/outcomes.parquet"
WINDOW_PANEL = EXT_ROOT / "chart_discovery_2014_2020/chart_window_panel.parquet"
REVIEW_LEDGER = EXT_ROOT / "chart_discovery_2014_2020/review_ledger.parquet"
REVIEW_CSV = EXT_ROOT / "chart_discovery_2014_2020/review_ledger.csv"
CHART_INDEX = EXT_ROOT / "chart_discovery_2014_2020/chart_index.csv"
CHART_DIR = EXT_ROOT / "chart_discovery_2014_2020/individual_charts"
SHEET_DIR = EXT_ROOT / "chart_discovery_2014_2020/contact_sheets"
OUTCOME_SHEET_ROOT = EXT_ROOT / "chart_discovery_2014_2020/review_sheets_by_outcome"
MANIFEST = EXT_ROOT / "chart_discovery_2014_2020/manifest.json"


class ExperimentError(RuntimeError):
    """Fail-closed experiment error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def detect_candidates() -> pd.DataFrame:
    query = f"""
    WITH features AS (
      SELECT *,
        lag(coord_close,20) OVER w AS lag20_close_x,
        lag(cal_idx,20) OVER w AS lag20_idx_x,
        lag(invalid_step_cum,20) OVER w AS lag20_invalid_x,
        lag(coord_high,1) OVER w AS prior_high_x,
        lag(coord_low,1) OVER w AS prior_low_x,
        min(coord_low) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) AS low5prev_x,
        avg(turnover_fraction) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS turn20_x,
        count(*) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS n20,
        min(current_day_data_tradable::INTEGER) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS tradable20,
        min(current_valid::INTEGER) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS valid20
      FROM read_parquet('{DAILY.as_posix()}')
      WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
    ), eligible AS (
      SELECT *,
        coord_close / lag20_close_x - 1.0 AS ret20_x,
        coord_open / prior_coord_close - 1.0 AS open_gap_x,
        (coord_close - coord_low) / nullif(coord_high - coord_low, 0.0) AS close_location_x
      FROM features
      WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31'
    )
    SELECT
      symbol,sleeve,trade_date AS signal_date,cal_idx,
      coord_open,coord_high,coord_low,coord_close,prior_coord_close,
      up_limit_price,turnover_fraction,step_return,
      ret20_x AS ret20,ret60,prior_high_x AS prior_high,
      prior_low_x AS prior_low,low5prev_x AS low5prev,
      coord_low AS stabilized_low_coord,turn20_x AS turn20,
      open_gap_x AS open_gap,close_location_x AS close_location,
      invalid_step_cum,available_at,decision_at
    FROM eligible
    WHERE hard_valid AND history_valid AND current_valid
      AND current_day_data_tradable AND market_rule_valid
      AND corporate_action_valid AND NOT corporate_action_blocking AND NOT is_st
      AND n20=20 AND tradable20=1 AND valid20=1
      AND cal_idx-lag20_idx_x=20
      AND invalid_step_cum=lag20_invalid_x
      AND ret20_x<=-0.10
      AND coord_low<=low5prev_x
      AND turnover_fraction>=turn20_x
      AND coord_close>=prior_high_x
      AND close_location_x>=0.70
      AND round(close*100)<round(up_limit_price*100)
    ORDER BY symbol,cal_idx
    """
    connection = duckdb.connect()
    high_recall = connection.execute(query).fetch_df()
    connection.close()
    high_recall["signal_date"] = pd.to_datetime(high_recall.signal_date)
    keep: list[int] = []
    for _, part in high_recall.groupby("symbol", sort=False):
        last = -10**12
        for index, row in part.iterrows():
            if int(row.cal_idx) - last > 20:
                keep.append(index)
                last = int(row.cal_idx)
    frozen = high_recall.loc[keep].copy()
    frozen["event_id"] = (
        frozen.symbol.astype(str)
        + "|"
        + frozen.signal_date.dt.strftime("%Y-%m-%d")
    )
    frozen = frozen.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if frozen.event_id.duplicated().any():
        raise ExperimentError("duplicate candidate event_id")
    expected = {
        2014: 64,
        2015: 134,
        2016: 136,
        2017: 308,
        2018: 357,
        2019: 325,
        2020: 259,
        2021: 354,
    }
    actual = frozen.groupby(frozen.signal_date.dt.year).size().to_dict()
    if actual != expected:
        raise ExperimentError(f"candidate identity drift: {actual}")
    return frozen


def legal_state(row: pd.Series) -> bool:
    fields = (
        "trade_status",
        "current_day_data_tradable",
        "market_rule_valid",
        "corporate_action_valid",
        "corporate_action_blocking",
        "hard_valid",
    )
    if any(pd.isna(row.get(field)) for field in fields):
        return False
    return bool(
        int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
    )


def buyable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_paths(candidates: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register("candidate_ids", candidates)
    result = connection.execute(
        f"""
        SELECT c.event_id,c.symbol,c.sleeve,c.signal_date,
          c.cal_idx AS signal_cal_idx,
          c.invalid_step_cum AS signal_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM candidate_ids c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.cal_idx
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    result["trade_date"] = pd.to_datetime(result.trade_date)
    return result


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.cal_idx)
    lineage = float(candidate.invalid_step_cum)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "profile": "T10_H20_NO_STOP",
    }
    if path.empty:
        return {**base, "status": "NO_FUTURE_PATH_THROUGH_2021"}
    entry_pool = path.loc[
        path.cal_idx.le(signal_idx + 3) & path.invalid_step_cum.eq(lineage)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if buyable_open(row)), None)
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * 1.10
    pending = False
    decision_idx: int | None = None
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    invalid = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H20_TIME_STOP"
            break
        if legal_state(row) and np.isfinite(float(row.coord_high)) and float(row.coord_high) >= target:
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_10"
            decision_idx = entry_idx
            break
        if legal_state(row) and int(row.cal_idx) >= entry_idx + 20:
            pending = True
            decision_idx = int(row.cal_idx)
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {
            **base,
            "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            **entry_payload,
        }
    if exit_row is None:
        return {**base, "status": "INCOMPLETE_BY_2021_END", **entry_payload}
    gross = exit_price / entry_price - 1.0
    return {
        **base,
        "status": "COMPLETED",
        **entry_payload,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "exit_decision_cal_idx": decision_idx,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - 0.004,
    }


def replay(candidates: pd.DataFrame) -> pd.DataFrame:
    paths = load_paths(candidates)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(event, groups.get(str(event.event_id), pd.DataFrame()))
        for event in candidates.itertuples(index=False)
    ]
    return pd.DataFrame(rows)


def configure_chart_module() -> None:
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


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    charts.EXPERIMENT = EXPERIMENT
    return charts.render_worker(payload)


def run(workers: int) -> dict[str, Any]:
    if not CONTRACT.exists() or not DAILY.exists():
        raise ExperimentError("missing frozen contract or registered daily input")
    candidates = detect_candidates()
    write_parquet(candidates, CANDIDATES)
    chart_candidates = candidates.loc[
        candidates.signal_date.le(pd.Timestamp("2020-12-31"))
    ].copy()
    outcomes = replay(chart_candidates)
    write_parquet(outcomes, OUTCOMES)

    configure_chart_module()
    windows = charts.load_windows(chart_candidates)
    if pd.to_datetime(windows.trade_date).max() > pd.Timestamp("2021-12-31"):
        raise ExperimentError("chart window escaped rule-discovery horizon")
    ledger = charts.build_ledger(chart_candidates, outcomes, windows)
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    REVIEW_CSV.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")

    groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
    tasks: list[tuple[dict[str, Any], pd.DataFrame, str]] = []
    for _, event in ledger.iterrows():
        output = CHART_DIR / (
            f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_"
            f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        )
        tasks.append((event.to_dict(), groups[str(event.event_id)], str(output)))
    with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
        index_rows = list(executor.map(render_worker, tasks, chunksize=1))
    index = pd.DataFrame(index_rows)
    index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
    sheets = charts.build_contact_sheets(index)
    outcome_sheets = charts.build_outcome_review_sheets(index)

    completed = ledger.loc[ledger.status.eq("COMPLETED")].copy()
    annual = (
        completed.assign(year=completed.signal_date.dt.year)
        .groupby("year")
        .agg(
            completed=("event_id", "size"),
            mean_net=("net_return", "mean"),
            median_net=("net_return", "median"),
            severe_loss10=("net_return", lambda values: float((values <= -0.10).mean())),
        )
        .reset_index()
    )
    manifest = {
        "experiment": EXPERIMENT,
        "contract_sha256": sha256(CONTRACT),
        "candidate_sha256": sha256(CANDIDATES),
        "candidate_count_2014_2021": int(len(candidates)),
        "chart_signal_count_2014_2020": int(len(chart_candidates)),
        "chart_count": int(len(index)),
        "contact_sheet_count": int(len(sheets)),
        "outcome_review_sheet_count": int(len(outcome_sheets)),
        "maximum_signal_date_used_in_chart_rule_formation": str(
            chart_candidates.signal_date.max().date()
        ),
        "maximum_chart_bar_date": str(pd.to_datetime(windows.trade_date).max().date()),
        "2021_signal_outcomes_read": False,
        "2022_plus_signal_outcomes_read": False,
        "post_2024_outcomes_read": False,
        "annual_chart_sample": annual.to_dict("records"),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "chart_index_sha256": sha256(CHART_INDEX),
        "window_panel_sha256": sha256(WINDOW_PANEL),
    }
    charts.canonical_json(MANIFEST, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    print(json.dumps(run(args.workers), indent=2, default=str))


if __name__ == "__main__":
    main()
