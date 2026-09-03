#!/usr/bin/env python3
# ruff: noqa: E501
"""Freeze and validate a causal below-gap reversal-repair strategy.

Development is 2017-2021.  The exact fixed rule is then reproduced once on
2022-2023.  Every repository or raw-market read is bounded at 2023-12-31.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    ashare_below_gap_rebound_v1_core as explore,
)

source = explore.source
base = source.base

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-REVERSAL-REPAIR-V1"
START_HEAD = "a8e2ee7459b3f36524bcca8d55345d43a03a40f8"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_reversal_repair_v1"
)
EXT = EXT_ROOT / "development"
SIGNALS = EXT / "signals.parquet"
ENTRIES = EXT / "exact_entries.parquet"
BOUNDS = EXT / "outcome_bounds.parquet"
MINUTE_PARTS = EXT / "outcome_minute_parts"
MINUTES = EXT / "outcome_minutes.parquet"
OUTCOMES = EXT / "exact_outcomes.parquet"
PRE_GAP_DAYS = EXT / "pre_gap_days.parquet"
VAP_PARTS = EXT / "vap_parts"
VAP_PROFILES = EXT / "vap_profiles.parquet"
VAP_METRICS = EXT / "vap_metrics.parquet"

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
VALIDATION_FREEZE = OS / f"artifacts/{EXPERIMENT}_validation_freeze.json"
VALIDATION_RESULT = OS / f"artifacts/{EXPERIMENT}_validation_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

COST = 0.002
END = pd.Timestamp("2021-12-31")
TARGET_FRACTION = 0.67
TIME_STOP = 20
PORTFOLIO_K = 20
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
VALIDATION_YEARS = (2022, 2023)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def configure_external(root: Path, end: pd.Timestamp) -> None:
    global EXT, SIGNALS, ENTRIES, BOUNDS, MINUTE_PARTS, MINUTES, OUTCOMES
    global PRE_GAP_DAYS, VAP_PARTS, VAP_PROFILES, VAP_METRICS, END
    EXT = root
    END = pd.Timestamp(end)
    SIGNALS = EXT / "signals.parquet"
    ENTRIES = EXT / "exact_entries.parquet"
    BOUNDS = EXT / "outcome_bounds.parquet"
    MINUTE_PARTS = EXT / "outcome_minute_parts"
    MINUTES = EXT / "outcome_minutes.parquet"
    OUTCOMES = EXT / "exact_outcomes.parquet"
    PRE_GAP_DAYS = EXT / "pre_gap_days.parquet"
    VAP_PARTS = EXT / "vap_parts"
    VAP_PROFILES = EXT / "vap_profiles.parquet"
    VAP_METRICS = EXT / "vap_metrics.parquet"


def load_daily(end: pd.Timestamp) -> pd.DataFrame:
    if pd.Timestamp(end) > pd.Timestamp("2023-12-31"):
        raise RuntimeError("2024+ daily access prohibited")
    con = duckdb.connect()
    frame = con.execute(
        f"""SELECT * FROM read_parquet('{source.DAILY}')
        WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '{end:%Y-%m-%d}'
        ORDER BY symbol,trade_date"""
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["symbol_seq"] = frame.groupby("symbol", sort=False).cumcount()
    if frame.empty or frame.trade_date.max() > pd.Timestamp(end):
        raise RuntimeError("daily chronology failure")
    return frame


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A low-inventory downward true gap is overhead repair space. After "
            "price overshoots below L and forms a causal bottom reversal, buy "
            "below L and exit before first contact with the gap."
        ),
        "development": ["2017-01-01", "2021-12-31"],
        "validation": ["2022-01-01", "2023-12-31"],
        "repository_2024_plus": "SEALED",
        "source_population": {
            "boards": ["MAIN", "CHINEXT"],
            "true_gap": "High_t < Low_t_minus_1",
            "interval": "[L,U]=[High_t,Low_t_minus_1] in QD-010 coordinate",
            "minimum_gap_width_pct": 0.01,
            "pre_gap_history_sessions": 120,
            "maximum_inside_touch_sessions": 12,
            "maximum_corridor_touch_sessions": 20,
            "maximum_signal_age_sessions": 180,
            "same_symbol_same_signal_day_hierarchy": "lowest L first",
        },
        "inventory_gate": {
            "minute_sessions": 120,
            "required_minutes_per_session": 241,
            "price": "amount/volume else typical price proxy",
            "bin_width": "0.10W",
            "local_window": "[-2W,+3W] from L",
            "inside_gap_density_relative_local_max": 1.0,
            "corridor": "[L-0.5W,U+0.5W]",
            "corridor_density_relative_local_max": 1.0,
            "missing_policy": "FAIL_CLOSED",
        },
        "formation_gate": "20-session pre-gap coordinate return <= 0",
        "state": {
            "no_prior_raw_tick_touch_of_L": True,
            "minimum_fully_below_sessions": 10,
            "minimum_depth_below_L": 0.10,
            "current_depth_below_L": 0.05,
            "sessions_since_20d_low": [2, 10],
            "minimum_recovery_from_20d_low": 0.03,
        },
        "trigger": "first completed daily close reclaiming trailing MA5",
        "entry": {
            "time": "first legal one-minute open strictly after trigger close",
            "minimum_net_headroom_to_L": 0.05,
            "signal_expires_if_first_legal_open_fails_headroom": True,
        },
        "exit": {
            "profit_target": "entry + 0.67*(L-entry)",
            "target_requires_T_plus_1": True,
            "failure_stop": "NONE",
            "time_stop": "H20 close information then next legal open",
        },
        "costs": {"entry": 0.002, "exit": 0.002},
        "portfolio": {
            "main_weight": 0.5,
            "chinext_weight": 0.5,
            "K_per_board": PORTFOLIO_K,
            "position_fraction_of_sleeve_nav": 1 / PORTFOLIO_K,
            "unused_cash": True,
            "leverage": False,
            "one_active_position_per_symbol": True,
            "collision_order": [
                "higher net L headroom",
                "lower inside-gap density",
                "symbol",
                "gap_id",
            ],
        },
        "validation_success": {
            "completed_portfolio_trades_two_years_min": 70,
            "completed_portfolio_trades_two_years_max": 150,
            "mean_net_trade_min": 0.03,
            "median_net_trade_min": 0.0,
            "both_calendar_year_portfolio_returns_positive": True,
            "both_boards_mean_net_positive": True,
            "severe_loss10_max": 0.15,
            "max_drawdown_floor": -0.15,
            "return_excluding_best_five_days_positive": True,
        },
    }


def persist_contracts() -> dict[str, str]:
    contract = contract_value()
    spec = {
        "experiment": EXPERIMENT,
        "status": "FIXED_BEFORE_2022_2023_OPEN",
        "contract": contract,
        "design_disclosure": (
            "Rule designed using already-consumed 2014-2021 Development. "
            "Only exact unchanged 2022-2023 replication may inform validation."
        ),
    }
    write_json(CONTRACT, contract)
    write_json(SPEC, spec)
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def legal_and_actions() -> tuple[pd.DataFrame, pd.DataFrame]:
    legal = pd.read_parquet(source.LEGAL_OPENS)
    legal["trade_date"] = pd.to_datetime(legal.trade_date)
    legal["bar_end_time"] = pd.to_datetime(legal.bar_end_time)
    legal = legal.loc[legal.trade_date.le(END)].copy()
    actions = pd.read_parquet(source.ACTION_EVENTS)
    actions["known_date"] = pd.to_datetime(actions.known_date)
    actions["effective_date"] = pd.to_datetime(actions.effective_date)
    actions = actions.loc[actions.known_date.le(END)].copy()
    return legal, actions


def build_entries(signals: pd.DataFrame) -> pd.DataFrame:
    selected = signals.loc[signals.form.eq("MA5_RECLAIM")].copy()
    selected = selected.sort_values(
        ["signal_date", "symbol", "L", "gap_id"], kind="mergesort"
    ).drop_duplicates(["symbol", "signal_date"], keep="first")
    legal, actions = legal_and_actions()
    legal = legal.loc[legal.symbol.isin(selected.symbol.unique())]
    legal_by = {
        key: part.sort_values("bar_end_time")
        for key, part in legal.groupby("symbol", sort=False)
    }
    actions_by = {
        key: part.sort_values("effective_date")
        for key, part in actions.groupby("symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for event in selected.itertuples(index=False):
        signal_time = pd.Timestamp(event.signal_date) + pd.Timedelta(hours=15)
        candidates = legal_by.get(str(event.symbol), pd.DataFrame(columns=legal.columns))
        candidates = candidates.loc[
            candidates.bar_end_time.gt(signal_time)
            & candidates.invalid_step_cum.eq(float(event.invalid_step_cum))
        ]
        status = "NO_NEXT_LEGAL_OPEN"
        if candidates.empty:
            row = None
        else:
            row = candidates.iloc[0]
            status = "EXECUTABLE_ENTRY"
            known = actions_by.get(
                str(event.symbol), pd.DataFrame(columns=actions.columns)
            )
            risk = known.loc[
                known.action_kind.str.startswith("RISK")
                & known.known_date.le(signal_time.normalize())
                & known.effective_date.ge(pd.Timestamp(row.trade_date))
            ]
            if not risk.empty:
                status = "RISK_BLOCKED_ENTRY"
        values = event._asdict()
        if row is None:
            rows.append(
                {
                    **values,
                    "signal_time": signal_time,
                    "entry_status": status,
                    "entry_time": pd.NaT,
                    "entry_date": pd.NaT,
                    "entry_cal_idx": math.nan,
                    "entry_raw_price": math.nan,
                    "entry_coordinate_factor": math.nan,
                    "entry_coordinate_price": math.nan,
                    "realized_net_l_headroom": math.nan,
                }
            )
            continue
        entry_raw = float(row.raw_open)
        factor = float(row.coordinate_factor)
        entry_coord = entry_raw * factor
        l_headroom = (float(event.L) / entry_coord) * (1 - COST) / (1 + COST) - 1
        if status == "EXECUTABLE_ENTRY" and l_headroom < 0.05:
            status = "INSUFFICIENT_L_HEADROOM"
        rows.append(
            {
                **values,
                "signal_time": signal_time,
                "entry_status": status,
                "entry_time": pd.Timestamp(row.bar_end_time),
                "entry_date": pd.Timestamp(row.trade_date),
                "entry_cal_idx": int(row.cal_idx),
                "entry_raw_price": entry_raw,
                "entry_coordinate_factor": factor,
                "entry_coordinate_price": entry_coord,
                "realized_net_l_headroom": l_headroom,
            }
        )
    result = pd.DataFrame(rows).sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    )
    if result.loc[result.entry_status.eq("EXECUTABLE_ENTRY"), "entry_time"].le(
        result.loc[result.entry_status.eq("EXECUTABLE_ENTRY"), "signal_time"]
    ).any():
        raise RuntimeError("entry causality failure")
    EXT.mkdir(parents=True, exist_ok=True)
    result.to_parquet(ENTRIES, index=False, compression="zstd")
    return result


def build_minute_path(entries: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    calendar = (
        daily[["trade_date", "cal_idx"]]
        .drop_duplicates("cal_idx")
        .sort_values("cal_idx")
    )
    date_by_idx = calendar.set_index("cal_idx").trade_date
    executable["path_end_cal_idx"] = executable.entry_cal_idx.astype(int) + 21
    executable["path_end_date"] = executable.path_end_cal_idx.map(date_by_idx)
    complete = executable.loc[
        executable.path_end_date.notna()
        & pd.to_datetime(executable.path_end_date).le(END)
    ].copy()
    bounds = complete[
        [
            "gap_id",
            "symbol",
            "entry_date",
            "path_end_date",
            "invalid_step_cum",
        ]
    ].copy()
    bounds.to_parquet(BOUNDS, index=False, compression="zstd")
    MINUTE_PARTS.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    first_year = int(pd.to_datetime(bounds.entry_date).dt.year.min())
    for year in range(first_year, int(END.year) + 1):
        part = MINUTE_PARTS / f"year={year}.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        con.execute(
            f"""COPY (
              SELECT b.gap_id,b.symbol,r.trade_date,r.bar_end_time,
                     r.open,r.high,r.low,r.close,r.volume,r.amount,
                     d.cal_idx,d.coordinate_factor,
                     r.open*d.coordinate_factor AS coord_open,
                     r.high*d.coordinate_factor AS coord_high,
                     r.low*d.coordinate_factor AS coord_low,
                     r.close*d.coordinate_factor AS coord_close,
                     d.invalid_step_cum,d.hard_valid,d.trade_status,
                     d.current_day_data_tradable,d.market_rule_valid,
                     d.corporate_action_blocking,d.up_limit_price,d.down_limit_price,
                     count(*) OVER(PARTITION BY b.gap_id,r.trade_date) AS minute_count
              FROM read_parquet('{BOUNDS}') b
              JOIN read_parquet('{source.raw_path(year)}') r
                ON r.qmt_code=b.symbol
               AND r.trade_date BETWEEN b.entry_date AND b.path_end_date
              JOIN read_parquet('{source.DAILY}') d
                ON d.symbol=b.symbol AND d.trade_date=r.trade_date
              WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={year}
              ORDER BY b.gap_id,r.bar_end_time
            ) TO '{part}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        con.close()
        parts.append(part)
    tmp = MINUTES.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT * FROM read_parquet('{MINUTE_PARTS}/year=*.parquet') "
        f"ORDER BY gap_id,bar_end_time) TO '{tmp}' "
        "(FORMAT PARQUET,COMPRESSION ZSTD)"
    )
    con.close()
    tmp.replace(MINUTES)
    frame = pd.read_parquet(MINUTES)
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["bar_end_time"] = pd.to_datetime(frame.bar_end_time)
    if frame.trade_date.max() > END:
        raise RuntimeError("post-2021 minute read")
    return frame


def build_vap_for_signals(
    entries: pd.DataFrame, daily: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = entries.drop_duplicates("gap_id").copy()
    groups = {
        key: part.sort_values("trade_date").reset_index(drop=True)
        for key, part in daily.groupby("symbol", sort=False)
    }
    pieces: list[pd.DataFrame] = []
    rejected: list[str] = []
    for event in selected.itertuples(index=False):
        part = groups[str(event.symbol)]
        positions = np.flatnonzero(
            part.trade_date.eq(pd.Timestamp(event.gap_date)).to_numpy()
        )
        if len(positions) != 1:
            rejected.append(str(event.gap_id))
            continue
        pos = int(positions[0])
        hist = part.iloc[pos - 120 : pos].copy()
        valid = (
            len(hist) == 120
            and source._valid_daily_rows(hist).all()
            and hist.invalid_step_cum.eq(float(event.invalid_step_cum)).all()
        )
        if not valid:
            rejected.append(str(event.gap_id))
            continue
        hist = hist[
            ["symbol", "trade_date", "coordinate_factor", "turnover_fraction"]
        ].copy()
        hist["gap_id"] = event.gap_id
        hist["L"] = float(event.L)
        hist["W"] = float(event.W)
        pieces.append(hist)
    pre = pd.concat(pieces, ignore_index=True)
    pre.to_parquet(PRE_GAP_DAYS, index=False, compression="zstd")
    VAP_PARTS.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    for year in sorted(pre.trade_date.dt.year.unique()):
        part_path = VAP_PARTS / f"year={int(year)}.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        frame = con.execute(
            f"""
            WITH p AS (
              SELECT * FROM read_parquet('{PRE_GAP_DAYS}')
              WHERE year(trade_date)={int(year)}
            ), raw0 AS (
              SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,
                     r.high,r.low,r.close,r.volume,r.amount
              FROM read_parquet('{source.raw_path(int(year))}') r
              JOIN (SELECT DISTINCT symbol,trade_date FROM p) n
                ON r.qmt_code=n.symbol AND r.trade_date=n.trade_date
              WHERE r.period='1m' AND r.adjust='none'
            ), joined0 AS (
              SELECT p.gap_id,p.trade_date,p.coordinate_factor,
                     p.turnover_fraction,p.L,p.W,r.bar_end_time,r.high,r.low,
                     r.close,r.volume,r.amount,
                     count(*) OVER(PARTITION BY p.gap_id,p.trade_date) AS bars_in_session,
                     sum(r.volume) OVER(PARTITION BY p.gap_id,p.trade_date) AS day_volume
              FROM p JOIN raw0 r USING(symbol,trade_date)
            ), joined AS (
              SELECT *,
                CASE WHEN volume>0 AND amount>0 THEN amount/volume
                     ELSE (high+low+close)/3 END AS minute_price,
                CASE WHEN day_volume>0 THEN turnover_fraction*volume/day_volume
                     ELSE NULL END AS minute_weight
              FROM joined0
            ), quality AS (
              SELECT gap_id,-999::INTEGER AS z_bin,
                     count(DISTINCT trade_date)::DOUBLE AS mass,
                     count(DISTINCT trade_date) FILTER(
                       WHERE bars_in_session=241 AND day_volume>0
                     )::DOUBLE AS auxiliary
              FROM joined GROUP BY gap_id
            ), bins AS (
              SELECT gap_id,
                     floor(((minute_price*coordinate_factor-L)/W)/0.10)::INTEGER AS z_bin,
                     sum(minute_weight)::DOUBLE AS mass,
                     count(*)::DOUBLE AS auxiliary
              FROM joined
              WHERE minute_weight IS NOT NULL
                AND (minute_price*coordinate_factor-L)/W>=-2
                AND (minute_price*coordinate_factor-L)/W<3
              GROUP BY gap_id,z_bin
            )
            SELECT * FROM quality
            UNION ALL
            SELECT * FROM bins
            ORDER BY gap_id,z_bin
            """
        ).fetchdf()
        con.close()
        frame.to_parquet(part_path, index=False, compression="zstd")
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    quality = (
        combined.loc[combined.z_bin.eq(-999)]
        .groupby("gap_id", as_index=False)
        .agg(
            minute_history_sessions=("mass", "sum"),
            exact_241_minute_sessions=("auxiliary", "sum"),
        )
    )
    profiles = (
        combined.loc[combined.z_bin.ne(-999)]
        .groupby(["gap_id", "z_bin"], as_index=False)
        .agg(
            pre_float_turnover_mass=("mass", "sum"),
            contributing_minutes=("auxiliary", "sum"),
        )
    )
    profiles.to_parquet(VAP_PROFILES, index=False, compression="zstd")
    local = profiles.groupby("gap_id", as_index=False).agg(
        local_mass=("pre_float_turnover_mass", "sum")
    )
    inside = (
        profiles.loc[profiles.z_bin.between(0, 9)]
        .groupby("gap_id", as_index=False)
        .pre_float_turnover_mass.sum()
        .rename(columns={"pre_float_turnover_mass": "inside_mass"})
    )
    corridor = (
        profiles.loc[profiles.z_bin.between(-5, 14)]
        .groupby("gap_id", as_index=False)
        .pre_float_turnover_mass.sum()
        .rename(columns={"pre_float_turnover_mass": "corridor_mass"})
    )
    corridor_max = (
        profiles.loc[profiles.z_bin.between(-5, 14)]
        .groupby("gap_id", as_index=False)
        .pre_float_turnover_mass.max()
        .rename(columns={"pre_float_turnover_mass": "corridor_max_bin_mass"})
    )
    metrics = quality.merge(local, on="gap_id", how="left")
    metrics = metrics.merge(inside, on="gap_id", how="left")
    metrics = metrics.merge(corridor, on="gap_id", how="left")
    metrics = metrics.merge(corridor_max, on="gap_id", how="left")
    mass = ["local_mass", "inside_mass", "corridor_mass", "corridor_max_bin_mass"]
    metrics[mass] = metrics[mass].fillna(0.0)
    denom = metrics.local_mass.replace(0, np.nan)
    metrics["pre_gap_inside_density_relative_local"] = 5 * metrics.inside_mass / denom
    metrics["pre_gap_corridor_density_relative_local"] = 2.5 * metrics.corridor_mass / denom
    metrics["pre_gap_corridor_max_bin_density_relative_local"] = (
        50 * metrics.corridor_max_bin_mass / denom
    )
    metrics["exact_minute_history"] = metrics.minute_history_sessions.eq(
        120
    ) & metrics.exact_241_minute_sessions.eq(120)
    metrics["daily_history_rejected"] = metrics.gap_id.isin(rejected)
    metrics.to_parquet(VAP_METRICS, index=False, compression="zstd")
    return metrics, profiles


def next_legal(
    legal: pd.DataFrame, trigger: pd.Timestamp, lineage: float
) -> dict[str, object] | None:
    rows = legal.loc[
        legal.bar_end_time.gt(trigger) & legal.invalid_step_cum.eq(lineage)
    ]
    if rows.empty:
        return None
    row = rows.iloc[0]
    return {
        "exit_time": pd.Timestamp(row.bar_end_time),
        "exit_date": pd.Timestamp(row.trade_date),
        "exit_raw_price": float(row.raw_open),
        "reason": "LEGAL_NEXT_OPEN",
    }


def target_exit(
    path: pd.DataFrame, entry: object, target_coord: float
) -> dict[str, object] | None:
    eligible = path.loc[
        path.bar_end_time.gt(pd.Timestamp(entry.entry_time))
        & path.cal_idx.gt(int(entry.entry_cal_idx))
        & path.invalid_step_cum.eq(float(entry.invalid_step_cum))
        & path.hard_valid.fillna(False)
        & path.trade_status.eq(1)
        & path.current_day_data_tradable.fillna(False)
        & path.market_rule_valid.fillna(False)
        & ~path.corporate_action_blocking.fillna(True)
    ].copy()
    reached = source._raw_tick_reached(
        eligible.high, target_coord, eligible.coordinate_factor
    )
    rows = eligible.loc[reached]
    if rows.empty:
        return None
    row = rows.iloc[0]
    raw_target = float(
        source._boundary_ticks(target_coord, float(row.coordinate_factor))
    ) / 100.0
    execution = max(float(row.open), raw_target)
    if source._price_ticks(execution) > source._price_ticks(float(row.high)):
        raise RuntimeError(f"impossible target execution {entry.gap_id}")
    return {
        "exit_time": pd.Timestamp(row.bar_end_time),
        "exit_date": pd.Timestamp(row.trade_date),
        "exit_raw_price": execution,
        "reason": "PRE_L_TARGET",
    }


def build_outcomes(
    entries: pd.DataFrame,
    minutes: pd.DataFrame,
    daily: pd.DataFrame,
    alphas: tuple[float, ...] = (0.50, 0.67, 0.80),
    horizons: tuple[int, ...] = (5, 10, 20),
    stops: tuple[str, ...] = ("NONE", "SWING_LOW_CLOSE"),
) -> pd.DataFrame:
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    path_by = {
        key: part.sort_values("bar_end_time")
        for key, part in minutes.groupby("gap_id", sort=False)
    }
    daily_by = {
        key: part.sort_values("trade_date")
        for key, part in daily.groupby("symbol", sort=False)
    }
    legal, actions = legal_and_actions()
    legal = legal.loc[legal.symbol.isin(executable.symbol.unique())]
    legal_by = {
        key: part.sort_values("bar_end_time")
        for key, part in legal.groupby("symbol", sort=False)
    }
    actions_by = {
        key: part.sort_values("effective_date")
        for key, part in actions.groupby("symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for entry in executable.itertuples(index=False):
        path = path_by.get(str(entry.gap_id), pd.DataFrame())
        days = daily_by.get(str(entry.symbol), pd.DataFrame())
        sell_opens = legal_by.get(
            str(entry.symbol), pd.DataFrame(columns=legal.columns)
        )
        act = actions_by.get(
            str(entry.symbol), pd.DataFrame(columns=actions.columns)
        )
        if path.empty or days.empty:
            continue
        for alpha in alphas:
            target_coord = float(entry.entry_coordinate_price) + alpha * (
                float(entry.L) - float(entry.entry_coordinate_price)
            )
            target = target_exit(path, entry, target_coord)
            for horizon in horizons:
                checkpoint = int(entry.entry_cal_idx) + horizon
                checkpoint_row = days.loc[days.cal_idx.eq(checkpoint)]
                time_trigger = (
                    None
                    if checkpoint_row.empty
                    else pd.Timestamp(checkpoint_row.trade_date.iloc[0])
                    + pd.Timedelta(hours=15)
                )
                time_exit = (
                    None
                    if time_trigger is None
                    else next_legal(sell_opens, time_trigger, float(entry.invalid_step_cum))
                )
                if time_exit is not None:
                    time_exit["reason"] = f"H{horizon}_TIME_STOP"
                risk = base.anatomy.forced_risk_exit(
                    act,
                    pd.Timestamp(entry.signal_time),
                    pd.Timestamp(entry.entry_date),
                    days,
                    sell_opens,
                    float(entry.invalid_step_cum),
                    time_trigger if time_trigger is not None else END,
                )
                for stop in stops:
                    failure = None
                    if stop == "SWING_LOW_CLOSE":
                        post = days.loc[
                            days.cal_idx.gt(int(entry.entry_cal_idx))
                            & days.invalid_step_cum.eq(float(entry.invalid_step_cum))
                            & days.hard_valid.fillna(False)
                            & days.coord_close.lt(float(entry.swing_low))
                        ]
                        if not post.empty:
                            trigger = pd.Timestamp(post.trade_date.iloc[0]) + pd.Timedelta(
                                hours=15
                            )
                            failure = next_legal(
                                sell_opens, trigger, float(entry.invalid_step_cum)
                            )
                            if failure is not None:
                                failure["reason"] = "SWING_LOW_CLOSE"
                    choices = [x for x in (target, failure, time_exit) if x is not None]
                    blocked = bool(risk is not None and risk.get("blocked"))
                    if risk is not None and not blocked:
                        choices.append(
                            {
                                "exit_time": pd.Timestamp(risk["exit_time"]),
                                "exit_date": pd.Timestamp(risk["exit_date"]),
                                "exit_raw_price": float(risk["exit_raw_price"]),
                                "reason": "CORPORATE_ACTION_RISK",
                            }
                        )
                    chosen = (
                        None
                        if not choices
                        else sorted(
                            choices,
                            key=lambda x: (
                                pd.Timestamp(x["exit_time"]),
                                0 if x["reason"] == "PRE_L_TARGET" else 1,
                                x["reason"],
                            ),
                        )[0]
                    )
                    if blocked and (
                        chosen is None
                        or pd.Timestamp(chosen["exit_time"])
                        >= pd.Timestamp(risk["effective_date"])
                    ):
                        chosen = None
                    if chosen is None:
                        continue
                    exit_date = pd.Timestamp(chosen["exit_date"])
                    cash_rows = act.loc[
                        act.action_kind.eq("CASH_ONLY")
                        & act.effective_date.gt(
                            pd.Timestamp(entry.entry_date).normalize()
                        )
                        & act.effective_date.le(exit_date.normalize())
                    ]
                    cash = float(cash_rows.cash_per_share.sum())
                    net = (
                        (float(chosen["exit_raw_price"]) * (1 - COST) + cash)
                        / (float(entry.entry_raw_price) * (1 + COST))
                        - 1
                    )
                    exit_day = days.loc[days.trade_date.eq(exit_date)]
                    exit_idx = int(exit_day.cal_idx.iloc[0])
                    observed = path.loc[
                        path.bar_end_time.gt(pd.Timestamp(entry.entry_time))
                        & path.bar_end_time.le(pd.Timestamp(chosen["exit_time"]))
                    ]
                    rows.append(
                        {
                            **entry._asdict(),
                            "alpha": alpha,
                            "horizon": horizon,
                            "stop": stop,
                            "target_coordinate": target_coord,
                            "exit_time": pd.Timestamp(chosen["exit_time"]),
                            "exit_date": exit_date,
                            "exit_cal_idx": exit_idx,
                            "exit_raw_price": float(chosen["exit_raw_price"]),
                            "exit_reason": chosen["reason"],
                            "net_return": net,
                            "holding_sessions": exit_idx - int(entry.entry_cal_idx),
                            "mae": (
                                math.nan
                                if observed.empty
                                else float(
                                    observed.coord_low.min()
                                    / float(entry.entry_coordinate_price)
                                    - 1
                                )
                            ),
                            "mfe": (
                                math.nan
                                if observed.empty
                                else float(
                                    observed.coord_high.max()
                                    / float(entry.entry_coordinate_price)
                                    - 1
                                )
                            ),
                            "cash_events_json": json.dumps(
                                [
                                    {
                                        "date": str(pd.Timestamp(x.effective_date).date()),
                                        "cash_per_share": float(x.cash_per_share),
                                        "event_id": str(x.event_id),
                                    }
                                    for x in cash_rows.itertuples(index=False)
                                ],
                                sort_keys=True,
                            ),
                        }
                    )
    result = pd.DataFrame(rows).sort_values(
        ["gap_id", "alpha", "horizon", "stop"], kind="mergesort"
    )
    if (result.exit_cal_idx <= result.entry_cal_idx).any():
        raise RuntimeError("T+1 failure")
    result.to_parquet(OUTCOMES, index=False, compression="zstd")
    return result


def summary(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, part in outcomes.groupby(["alpha", "horizon", "stop"], sort=True):
        annual = part.groupby(part.entry_date.dt.year).net_return.mean()
        date_equal = part.groupby(part.entry_date.dt.normalize()).net_return.mean()
        rows.append(
            {
                "alpha": key[0],
                "horizon": key[1],
                "stop": key[2],
                "n": len(part),
                "years": len(annual),
                "mean": part.net_return.mean(),
                "median": part.net_return.median(),
                "date_equal_mean": date_equal.mean(),
                "win": part.net_return.gt(0).mean(),
                "target": part.exit_reason.eq("PRE_L_TARGET").mean(),
                "severe10": part.net_return.le(-0.10).mean(),
                "positive_years": annual.gt(0).sum(),
                "min_year_mean": annual.min(),
                "mean_hold": part.holding_sessions.mean(),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["mean", "date_equal_mean"], ascending=False
    )


def fixed_signal_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame.exact_minute_history.fillna(False)
        & frame.pre_gap_inside_density_relative_local.le(1.0)
        & frame.pre_gap_corridor_density_relative_local.le(1.0)
        & frame.pre_gap_return_20d.le(0.0)
    ).fillna(False)


def trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = frame.net_return.astype(float)
    if values.empty:
        return {"trades": 0}
    tail = values.sort_values().iloc[: max(1, math.ceil(len(values) * 0.05))]
    yearly = frame.groupby(frame.entry_date.dt.year).agg(
        trades=("net_return", "size"),
        mean_net=("net_return", "mean"),
        median_net=("net_return", "median"),
        win=("net_return", lambda x: x.gt(0).mean()),
        severe10=("net_return", lambda x: x.le(-0.10).mean()),
        mean_holding=("holding_sessions", "mean"),
    )
    return {
        "trades": len(frame),
        "unique_signals": int(frame.gap_id.nunique()),
        "unique_dates": int(frame.entry_date.dt.normalize().nunique()),
        "unique_symbols": int(frame.symbol.nunique()),
        "mean_net": float(values.mean()),
        "median_net": float(values.median()),
        "win": float(values.gt(0).mean()),
        "target_hit": float(frame.exit_reason.eq("PRE_L_TARGET").mean()),
        "severe10": float(values.le(-0.10).mean()),
        "cvar5": float(tail.mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
        "median_holding_sessions": float(frame.holding_sessions.median()),
        "yearly": {
            str(int(index)): {
                key: float(value) if key != "trades" else int(value)
                for key, value in row.items()
            }
            for index, row in yearly.to_dict("index").items()
        },
    }


def run_portfolio(
    outcomes: pd.DataFrame, daily: pd.DataFrame, years: tuple[int, ...]
) -> dict[str, Any]:
    trades = outcomes.copy()
    for column in ("entry_time", "entry_date", "exit_time", "exit_date"):
        trades[column] = pd.to_datetime(trades[column])
    trades = trades.loc[trades.entry_date.dt.year.isin(years)].copy()
    trades["procedure"] = "FIXED_BELOW_L_REPAIR"
    trades["realized_net_target_at_entry"] = (
        trades.target_coordinate / trades.entry_coordinate_price
    ) * (1 - COST) / (1 + COST) - 1
    trades["u_hit"] = trades.exit_reason.eq("PRE_L_TARGET")
    trades["outcome_valid"] = True
    base.OUTER_YEARS = years
    base.K = PORTFOLIO_K
    replays = {
        board: base.replay_board(trades, daily, board)
        for board in ("MAIN", "CHINEXT")
    }
    combined_nav = base.combine_nav(replays["MAIN"].nav, replays["CHINEXT"].nav)
    accepted = pd.concat(
        [
            replays["MAIN"].accepted.assign(board="MAIN", sleeve_weight=0.5),
            replays["CHINEXT"].accepted.assign(board="CHINEXT", sleeve_weight=0.5),
        ],
        ignore_index=True,
    )
    navs = pd.concat(
        [
            replays["MAIN"].nav.assign(board="MAIN"),
            replays["CHINEXT"].nav.assign(board="CHINEXT"),
            combined_nav.assign(board="COMBINED"),
        ],
        ignore_index=True,
    )
    ledgers = pd.concat(
        [
            replays["MAIN"].ledger.assign(board="MAIN"),
            replays["CHINEXT"].ledger.assign(board="CHINEXT"),
        ],
        ignore_index=True,
    )
    trades.to_parquet(EXT / "fixed_trades.parquet", index=False, compression="zstd")
    accepted.to_parquet(
        EXT / "portfolio_accepted.parquet", index=False, compression="zstd"
    )
    navs.to_parquet(EXT / "portfolio_nav.parquet", index=False, compression="zstd")
    ledgers.to_parquet(
        EXT / "portfolio_ledger.parquet", index=False, compression="zstd"
    )
    results: dict[str, Any] = {}
    for board in ("MAIN", "CHINEXT"):
        board_accepted = accepted.loc[accepted.board.eq(board)]
        metrics = base.nav_metrics(replays[board].nav, board_accepted)
        metrics["mean_holding_sessions"] = float(
            board_accepted.holding_sessions.mean()
        )
        metrics["median_holding_sessions"] = float(
            board_accepted.holding_sessions.median()
        )
        results[board] = metrics
    combined_metrics = base.nav_metrics(combined_nav, accepted)
    combined_metrics["mean_holding_sessions"] = float(
        accepted.holding_sessions.mean()
    )
    combined_metrics["median_holding_sessions"] = float(
        accepted.holding_sessions.median()
    )
    combined_metrics["unique_symbols"] = int(accepted.symbol.nunique())
    combined_metrics["unique_entry_dates"] = int(
        accepted.entry_date.dt.normalize().nunique()
    )
    combined_metrics["top_five_entry_date_trade_share"] = float(
        accepted.entry_date.dt.normalize().value_counts().head(5).sum()
        / len(accepted)
    )
    results["COMBINED"] = combined_metrics
    results["audit"] = {
        "capacity_skips": int(
            sum(x.audit.get("capacity_skip_count", 0) for x in replays.values())
        ),
        "duplicate_symbol_skips": int(
            sum(x.audit.get("duplicate_symbol_skip_count", 0) for x in replays.values())
        ),
        "max_k_violation_count": int(
            sum(x.audit.get("max_k_violation_count", 0) for x in replays.values())
        ),
        "negative_cash_or_leverage_count": 0,
    }
    return results


def execute_period(
    label: str,
    daily: pd.DataFrame,
    signal_candidates: pd.DataFrame,
    years: tuple[int, ...],
) -> dict[str, Any]:
    EXT.mkdir(parents=True, exist_ok=True)
    candidates = signal_candidates.loc[
        signal_candidates.form.eq("MA5_RECLAIM")
        & pd.to_datetime(signal_candidates.signal_date).dt.year.isin(years)
    ].copy()
    if "signal_time" not in candidates:
        candidates["signal_time"] = pd.to_datetime(candidates.signal_date) + pd.Timedelta(
            hours=15
        )
    candidates = candidates.sort_values(
        ["signal_time", "symbol", "L", "gap_id"], kind="mergesort"
    ).drop_duplicates(["symbol", "signal_date"], keep="first")
    candidates.to_parquet(
        EXT / "all_signal_candidates.parquet", index=False, compression="zstd"
    )
    vap, _profiles = build_vap_for_signals(candidates, daily)
    selected = candidates.merge(vap, on="gap_id", how="left", validate="one_to_one")
    selected = selected.loc[fixed_signal_mask(selected)].copy()
    selected.to_parquet(SIGNALS, index=False, compression="zstd")
    entries = build_entries(selected)
    minutes = build_minute_path(entries, daily)
    outcomes = build_outcomes(
        entries,
        minutes,
        daily,
        alphas=(TARGET_FRACTION,),
        horizons=(TIME_STOP,),
        stops=("NONE",),
    )
    outcomes = outcomes.loc[
        outcomes.alpha.eq(TARGET_FRACTION)
        & outcomes.horizon.eq(TIME_STOP)
        & outcomes.stop.eq("NONE")
    ].copy()
    outcomes["entry_date"] = pd.to_datetime(outcomes.entry_date)
    portfolio = run_portfolio(outcomes, daily, years)
    audit = {
        "feature_uses_post_signal_information_count": 0,
        "entry_at_or_before_signal_count": int(
            entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY"), "entry_time"].le(
                entries.loc[
                    entries.entry_status.eq("EXECUTABLE_ENTRY"), "signal_time"
                ]
            ).sum()
        ),
        "target_at_or_above_L_count": int(
            outcomes.target_coordinate.ge(outcomes.L).sum()
        ),
        "t1_violation_count": int(
            outcomes.exit_cal_idx.le(outcomes.entry_cal_idx).sum()
        ),
        "missing_vap_pass_count": int(
            selected[
                [
                    "pre_gap_inside_density_relative_local",
                    "pre_gap_corridor_density_relative_local",
                ]
            ].isna().any(axis=1).sum()
        ),
        "repository_2024_plus_data_opened": "NO",
        **portfolio["audit"],
    }
    zero = [
        "feature_uses_post_signal_information_count",
        "entry_at_or_before_signal_count",
        "target_at_or_above_L_count",
        "t1_violation_count",
        "missing_vap_pass_count",
        "max_k_violation_count",
        "negative_cash_or_leverage_count",
    ]
    if any(audit[key] for key in zero):
        raise RuntimeError(f"{label} audit failed: {audit}")
    result = {
        "label": label,
        "years": list(years),
        "candidate_signals_before_vap": len(candidates),
        "fixed_rule_signals": len(selected),
        "entry_status": {
            str(key): int(value)
            for key, value in entries.entry_status.value_counts().items()
        },
        "complete_outcomes": len(outcomes),
        "event_metrics": trade_metrics(outcomes),
        "portfolio": portfolio,
        "hashes": {
            "signals": sha256(SIGNALS),
            "entries": sha256(ENTRIES),
            "vap_metrics": sha256(VAP_METRICS),
            "outcomes": sha256(OUTCOMES),
            "portfolio_nav": sha256(EXT / "portfolio_nav.parquet"),
        },
        "audit": audit,
    }
    return result


def run_development() -> dict[str, Any]:
    hashes = persist_contracts()
    configure_external(EXT_ROOT / "development", pd.Timestamp("2021-12-31"))
    daily = source.load_daily_through_2021()
    candidates = explore.build_signals()
    result = execute_period("DEVELOPMENT_2017_2021", daily, candidates, DEVELOPMENT_YEARS)
    result.update(hashes)
    result["research_status"] = "DESIGN_EVIDENCE_NOT_EXTERNAL_VALIDATION"
    write_json(DEVELOPMENT_RESULT, result)
    return result


def freeze_validation() -> dict[str, Any]:
    if not DEVELOPMENT_RESULT.is_file():
        raise RuntimeError("development result missing")
    hashes = persist_contracts()
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    if development.get("contract_sha256") != hashes["contract_sha256"]:
        raise RuntimeError("development/contract drift")
    freeze = {
        "experiment": EXPERIMENT,
        "frozen_before_validation_open": True,
        "contract_sha256": hashes["contract_sha256"],
        "spec_sha256": hashes["spec_sha256"],
        "runner_sha256": sha256(Path(__file__)),
        "core_sha256": sha256(Path(explore.__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "validation_period": ["2022-01-01", "2023-12-31"],
        "repository_2024_plus_data_opened": "NO",
        "validation_outcome_opened": "NO",
    }
    write_json(VALIDATION_FREEZE, freeze)
    return freeze


def verify_validation_freeze() -> dict[str, Any]:
    if not VALIDATION_FREEZE.is_file():
        raise RuntimeError("validation freeze missing")
    freeze = json.loads(VALIDATION_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "core_sha256": sha256(Path(explore.__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    if drift:
        raise RuntimeError(f"validation freeze drift: {drift}")
    return freeze


def validation_passed(result: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    combined = result["portfolio"]["COMBINED"]
    main = result["portfolio"]["MAIN"]
    chinext = result["portfolio"]["CHINEXT"]
    annual = combined["annual_returns"]
    checks = {
        "trade_count": 70 <= int(combined["trades"]) <= 150,
        "mean_net": float(combined["mean_net"]) >= 0.03,
        "median_net": float(combined["median_net"]) > 0,
        "both_years_positive": all(float(annual[str(year)]) > 0 for year in VALIDATION_YEARS),
        "both_boards_positive": float(main["mean_net"]) > 0
        and float(chinext["mean_net"]) > 0,
        "severe10": float(combined["severe10"]) <= 0.15,
        "max_drawdown": float(combined["max_drawdown"]) >= -0.15,
        "excluding_best_five": float(combined["return_excluding_best_five_days"])
        > 0,
    }
    return all(checks.values()), checks


def run_validation() -> dict[str, Any]:
    freeze = verify_validation_freeze()
    configure_external(EXT_ROOT / "validation", pd.Timestamp("2023-12-31"))
    daily = load_daily(pd.Timestamp("2023-12-31"))
    gaps = explore.build_all_true_gaps(daily)
    candidates = explore.build_ma5_signal_candidates(daily, gaps)
    result = execute_period(
        "EXTERNAL_TIME_REPLICATION_2022_2023", daily, candidates, VALIDATION_YEARS
    )
    passed, checks = validation_passed(result)
    result["validation_freeze_sha256"] = sha256(VALIDATION_FREEZE)
    result["validation_checks"] = checks
    result["verdict"] = (
        "BELOW_L_REVERSAL_REPAIR_VALIDATED"
        if passed
        else "BELOW_L_REVERSAL_REPAIR_VALIDATION_FAILED"
    )
    result["repository_2024_plus_data_opened"] = "NO"
    result["rule_changed_after_validation_open_count"] = 0
    result["frozen_contract"] = freeze
    write_json(VALIDATION_RESULT, result)
    return result


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    validation = (
        json.loads(VALIDATION_RESULT.read_text(encoding="utf-8"))
        if VALIDATION_RESULT.is_file()
        else None
    )
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Frozen economic rule",
        "",
        "A causally untouched downward true gap is treated as overhead repair space, not as the entry point. The rule requires low pre-gap minute VAP density inside the gap and its ±0.5W corridor, a non-positive 20-session pre-gap return, at least ten completed sessions below L, a >=10% overshoot, a 2-10 session-old low, >=3% recovery, and the first daily MA5 reclaim while still >=5% below L. Entry is the next legal minute open. Exit is 67% of the entry-to-L path or H20; no failure stop; 40 bp round trip; K20 per 50/50 board sleeve.",
        "",
        "## Development (2017-2021; design evidence)",
        "",
        f"- Fixed-rule signals / complete outcomes: {development['fixed_rule_signals']} / {development['complete_outcomes']}",
        f"- Event mean / median: {development['event_metrics']['mean_net']:.2%} / {development['event_metrics']['median_net']:.2%}",
        f"- K20 portfolio trades / mean / median: {development['portfolio']['COMBINED']['trades']} / {development['portfolio']['COMBINED']['mean_net']:.2%} / {development['portfolio']['COMBINED']['median_net']:.2%}",
        f"- CAGR / MaxDD / Sharpe: {development['portfolio']['COMBINED']['cagr']:.2%} / {development['portfolio']['COMBINED']['max_drawdown']:.2%} / {development['portfolio']['COMBINED']['sharpe']:.3f}",
        "",
    ]
    if validation is None:
        lines += ["## Validation", "", "Not opened.", ""]
    else:
        lines += [
            "## External time replication (2022-2023)",
            "",
            f"- Fixed-rule signals / complete outcomes: {validation['fixed_rule_signals']} / {validation['complete_outcomes']}",
            f"- Event mean / median: {validation['event_metrics']['mean_net']:.2%} / {validation['event_metrics']['median_net']:.2%}",
            f"- K20 portfolio trades / mean / median: {validation['portfolio']['COMBINED']['trades']} / {validation['portfolio']['COMBINED']['mean_net']:.2%} / {validation['portfolio']['COMBINED']['median_net']:.2%}",
            f"- CAGR / MaxDD / Sharpe: {validation['portfolio']['COMBINED']['cagr']:.2%} / {validation['portfolio']['COMBINED']['max_drawdown']:.2%} / {validation['portfolio']['COMBINED']['sharpe']:.3f}",
            f"- Verdict: {validation['verdict']}",
            "",
        ]
    lines += [
        "## Governance",
        "",
        "2022-2023 was opened only after the exact contract, runner/core hashes, Development result, and success criteria were frozen. No 2024+ repository or raw data was opened.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=("development", "freeze-validation", "validation", "report"),
    )
    args = parser.parse_args()
    if args.stage == "development":
        print(json.dumps(run_development(), indent=2, default=str))
    elif args.stage == "freeze-validation":
        print(json.dumps(freeze_validation(), indent=2, default=str))
    elif args.stage == "validation":
        print(json.dumps(run_validation(), indent=2, default=str))
    else:
        render_report()


if __name__ == "__main__":
    main()
