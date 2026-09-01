#!/usr/bin/env python3
"""Run frozen Phase-A A-share industry minute leader/follower research."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-INDUSTRY-LEAD-FOLLOW-CYCLE-013_spec.json"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-INDUSTRY-LEAD-FOLLOW-CYCLE-013_summary.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-INDUSTRY-LEAD-FOLLOW-CYCLE-013_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-INDUSTRY-LEAD-FOLLOW-CYCLE-013_report.md"
EXTERNAL_PANEL_PATH = Path(
    "/Volumes/quant/CY_quant_research/industry_lead_follow_cycle_013/event_panel.parquet"
)

CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY008_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-008-pit-b-minute-v2-2018-2026-20260821.json"
)
QD004_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-004-2018-2026-20260820.json"
)
ADAPTER_PATH = PROGRAM / "scripts/vectorized_market_minute_adapter.py"

EXPECTED_SPEC_SHA256 = "80549c71352cd312d8169a61242116c2126bc63a2b3ced0313787fc18bd1a41c"
YEARS = tuple(range(2018, 2024))
THRESHOLD = 0.01
MIN_INDUSTRY = 6
MIN_PRIOR_AMOUNT = 50_000_000.0
MATCH_SCALE_FLOORS = np.array([0.0005, 0.0005, 0.05, 0.25], dtype=float)
CONTINUOUS_MINUTES = np.array(
    list(range(9 * 60 + 31, 11 * 60 + 31))
    + list(range(13 * 60 + 1, 15 * 60 + 1)),
    dtype=np.int16,
)
EVENT_MASK = (
    ((CONTINUOUS_MINUTES >= 9 * 60 + 36) & (CONTINUOUS_MINUTES <= 11 * 60 + 20))
    | ((CONTINUOUS_MINUTES >= 13 * 60 + 6) & (CONTINUOUS_MINUTES <= 14 * 60 + 50))
)
EVENT_INDICES = np.flatnonzero(EVENT_MASK)


class CycleError(RuntimeError):
    """Fail-closed error for Cycle 013."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_module() -> Any:
    module_spec = importlib.util.spec_from_file_location("minute_adapter_for_013", ADAPTER_PATH)
    if module_spec is None or module_spec.loader is None:
        raise CycleError("cannot load accepted minute adapter")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


ADAPTER = _load_module()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if EXPECTED_SPEC_SHA256 == "TO_BE_FROZEN":
        raise CycleError("runner spec identity has not been frozen")
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CycleError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_PHASE_A_BEFORE_FOLLOWER_OUTCOME_ACCESS_PHASE_B_C_LOCKED":
        raise CycleError("Phase A was not frozen before outcome access")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CycleError(f"bound input identity changed: {role}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "same-minute", "same-bar", "Phase B/C"):
        if phrase not in prohibited:
            raise CycleError(f"missing scientific prohibition: {phrase}")
    return spec


def _manifest_records(path: Path) -> tuple[Path, dict[str, dict[str, Any]]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return Path(manifest["root"]), {record["path"]: record for record in manifest["files"]}


def _partition_paths() -> tuple[list[Path], list[Path], dict[int, Path]]:
    cy6_root, cy6_records = _manifest_records(CY006_MANIFEST)
    cy8_root, cy8_records = _manifest_records(CY008_MANIFEST)
    qd_root, qd_records = _manifest_records(QD004_MANIFEST)
    daily_paths: list[Path] = []
    minute_daily_paths: list[Path] = []
    raw_paths: dict[int, Path] = {}
    for year in YEARS:
        cy6_relative = f"partition_year={year}/data_0.parquet"
        cy8_relative = f"daily/partition_year={year}/data_0.parquet"
        qd_relative = f"bars/{year}_day_parquet_none.parquet"
        for root, records, relative, output in (
            (cy6_root, cy6_records, cy6_relative, daily_paths),
            (cy8_root, cy8_records, cy8_relative, minute_daily_paths),
        ):
            record = records.get(relative)
            path = root / relative
            if record is None or not path.is_file() or path.stat().st_size != int(record["size"]):
                raise CycleError(f"manifest partition mismatch: {relative}")
            output.append(path)
        qd_record = qd_records.get(qd_relative)
        qd_path = qd_root / qd_relative
        if (
            qd_record is None
            or not qd_path.is_file()
            or qd_path.stat().st_size != int(qd_record["size"])
        ):
            raise CycleError(f"raw minute partition mismatch: {qd_relative}")
        raw_paths[year] = qd_path
    return daily_paths, minute_daily_paths, raw_paths


def _verify_content_hashes(
    daily_paths: list[Path], minute_daily_paths: list[Path], raw_paths: dict[int, Path]
) -> None:
    for manifest_path, paths in (
        (CY006_MANIFEST, daily_paths),
        (CY008_MANIFEST, minute_daily_paths),
    ):
        root, records = _manifest_records(manifest_path)
        by_path = {root / relative: record for relative, record in records.items()}
        for path in paths:
            if sha256_file(path) != by_path[path]["sha256"]:
                raise CycleError(f"content hash mismatch: {path}")
    qd_root, qd_records = _manifest_records(QD004_MANIFEST)
    by_path = {qd_root / relative: record for relative, record in qd_records.items()}
    for path in raw_paths.values():
        if sha256_file(path) != by_path[path]["sha256"]:
            raise CycleError(f"content hash mismatch: {path}")


def _true(series: pd.Series) -> np.ndarray:
    return series.astype("boolean").fillna(False).to_numpy(dtype=bool)


def _load_year_context(
    year: int, daily_paths: list[Path], minute_daily_path: Path
) -> pd.DataFrame:
    source_paths = [path for path in daily_paths if int(path.parent.name.split("=")[1]) <= year]
    source_paths = source_paths[-2:]
    path_sql = "[" + ",".join("'" + path.as_posix().replace("'", "''") + "'" for path in source_paths) + "]"
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    daily = connection.execute(
        f"""
        WITH base AS (
          SELECT trade_date,decision_at,symbol,amount,trade_status,is_st,industry,
                 up_limit_price,corporate_action_blocking,rights_ratio,
                 bar_valid,trading_state_valid,industry_valid,float_valid,
                 corporate_action_valid,market_valid,market_rule_valid,
                 historical_identity_valid,hard_valid,current_day_data_tradable,
                 available_at,snapshot_id,
                 avg(amount) OVER (PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) prior20_amount,
                 count(amount) OVER (PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) prior20_count
          FROM read_parquet({path_sql}, union_by_name=true)
        )
        SELECT * FROM base WHERE year(trade_date)={year}
        ORDER BY trade_date,symbol
        """
    ).fetch_df()
    connection.close()
    if daily.duplicated(["trade_date", "symbol"]).any():
        raise CycleError(f"duplicate CY-006 context in {year}")
    available = pd.to_datetime(daily.available_at, errors="coerce", utc=True)
    decision = pd.to_datetime(daily.decision_at, errors="coerce", utc=True)
    daily["daily_eligible"] = (
        _true(daily.hard_valid)
        & _true(daily.bar_valid)
        & _true(daily.trading_state_valid)
        & _true(daily.industry_valid)
        & _true(daily.float_valid)
        & _true(daily.corporate_action_valid)
        & _true(daily.market_valid)
        & _true(daily.market_rule_valid)
        & _true(daily.historical_identity_valid)
        & ~_true(daily.corporate_action_blocking)
        & pd.to_numeric(daily.rights_ratio, errors="coerce").fillna(0).eq(0).to_numpy()
        & available.notna().to_numpy()
        & decision.notna().to_numpy()
        & available.le(decision).to_numpy()
        & pd.to_numeric(daily.trade_status, errors="coerce").eq(1).to_numpy()
        & _true(daily.current_day_data_tradable)
        & ~_true(daily.is_st)
        & daily.industry.notna().to_numpy()
        & daily.industry.astype(str).ne("").to_numpy()
        & pd.to_numeric(daily.prior20_count, errors="coerce").eq(20).to_numpy()
        & pd.to_numeric(daily.prior20_amount, errors="coerce").ge(MIN_PRIOR_AMOUNT).to_numpy()
        & pd.to_numeric(daily.up_limit_price, errors="coerce").gt(0).to_numpy()
    )

    minute_columns = [
        "trade_date", "symbol", "available_at", "minute_count", "distinct_minute_count",
        "source_resolution_minutes", "session_complete", "ohlc_valid", "unit_valid",
        "volume_reconciled", "amount_reconciled", "daily_hard_valid", "hard_valid",
        "daily_snapshot_id",
    ]
    minute = pq.read_table(minute_daily_path, columns=minute_columns, use_threads=False).to_pandas()
    if minute.duplicated(["trade_date", "symbol"]).any():
        raise CycleError(f"duplicate CY-008 context in {year}")
    minute_date = pd.to_datetime(minute.trade_date, errors="raise")
    minute["trade_date"] = minute_date
    minute_available = pd.to_datetime(minute.available_at, errors="coerce")
    expected_available = minute_date + pd.Timedelta(hours=15, minutes=30)
    minute["minute_eligible"] = (
        minute_available.eq(expected_available).to_numpy()
        & pd.to_numeric(minute.minute_count, errors="coerce").eq(241).to_numpy()
        & pd.to_numeric(minute.distinct_minute_count, errors="coerce").eq(241).to_numpy()
        & pd.to_numeric(minute.source_resolution_minutes, errors="coerce").eq(1).to_numpy()
        & _true(minute.session_complete)
        & _true(minute.ohlc_valid)
        & _true(minute.unit_valid)
        & _true(minute.volume_reconciled)
        & _true(minute.amount_reconciled)
        & _true(minute.daily_hard_valid)
        & _true(minute.hard_valid)
    )
    minute = minute[["trade_date", "symbol", "daily_snapshot_id", "minute_eligible"]]
    context = daily.merge(minute, on=["trade_date", "symbol"], how="left", validate="one_to_one")
    snapshot_match = context.daily_snapshot_id.eq(context.snapshot_id)
    context["eligible"] = (
        context.daily_eligible.to_numpy(dtype=bool)
        & context.minute_eligible.astype("boolean").fillna(False).to_numpy(dtype=bool)
        & snapshot_match.fillna(False).to_numpy(dtype=bool)
    )
    context = context.loc[context.eligible, [
        "trade_date", "symbol", "industry", "up_limit_price", "prior20_amount", "snapshot_id"
    ]].copy()
    context["trade_date"] = pd.to_datetime(context.trade_date, errors="raise")
    return context.reset_index(drop=True)


def _minute_number(values: pd.Series) -> np.ndarray:
    timestamps = pd.to_datetime(values, errors="raise")
    return (timestamps.dt.hour * 60 + timestamps.dt.minute).to_numpy(dtype=np.int16)


def _load_minute_arrays(
    raw_path: Path, trade_date: pd.Timestamp, context: pd.DataFrame
) -> dict[str, Any]:
    if context.empty:
        raise CycleError(f"empty eligible context: {trade_date.date()}")
    source_symbols = context.symbol.astype(str).str.split(".", regex=False).str[0].unique()
    table = ADAPTER.read_raw_table(raw_path, [trade_date.date()], source_symbols)
    frame = table.select([
        "symbol", "exchange", "period", "adjust", "trade_date", "bar_end_time",
        "open", "high", "low", "close", "volume", "amount", "source",
    ]).to_pandas()
    frame["full_symbol"] = frame.symbol.astype(str) + "." + frame.exchange.astype(str)
    allowed = set(context.symbol.astype(str))
    frame = frame.loc[frame.full_symbol.isin(allowed)].copy()
    if frame.empty:
        raise CycleError(f"raw minute join returned no eligible symbols: {trade_date.date()}")
    if set(frame.period.astype(str)) != {"1m"} or set(frame.adjust.astype(str)) != {"none"}:
        raise CycleError("raw minute coordinate changed")
    frame = frame.sort_values(["full_symbol", "bar_end_time"], kind="mergesort")
    counts = frame.groupby("full_symbol", sort=False).size()
    valid_symbols = counts.index[counts.eq(241)]
    frame = frame.loc[frame.full_symbol.isin(valid_symbols)].copy()
    context = context.loc[context.symbol.astype(str).isin(set(valid_symbols))].copy()
    symbols = frame.full_symbol.drop_duplicates().to_numpy(dtype=str)
    if len(symbols) != len(context) or set(symbols) != set(context.symbol.astype(str)):
        raise CycleError(f"CY-008/raw 241-session identity mismatch: {trade_date.date()}")
    minutes = _minute_number(frame.bar_end_time).reshape(-1, 241)
    if not np.array_equal(minutes, np.broadcast_to(ADAPTER.EXPECTED_MINUTES, minutes.shape)):
        raise CycleError(f"unexpected minute grid: {trade_date.date()}")
    matrices: dict[str, np.ndarray] = {}
    for column in ("open", "high", "low", "close", "volume", "amount"):
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float).reshape(-1, 241)
        if not np.isfinite(values).all():
            raise CycleError(f"nonfinite raw {column}: {trade_date.date()}")
        matrices[column] = values
    if (matrices["close"] <= 0).any() or (matrices["volume"] < 0).any():
        raise CycleError(f"invalid raw price/volume: {trade_date.date()}")
    context = context.set_index(context.symbol.astype(str)).loc[symbols]
    returns = np.log(matrices["close"][:, 1:] / matrices["close"][:, :-1])
    if not np.isfinite(returns).all():
        raise CycleError(f"nonfinite minute returns: {trade_date.date()}")
    return {
        "symbols": symbols,
        "industries": context.industry.astype(str).to_numpy(),
        "up_limits": pd.to_numeric(context.up_limit_price, errors="raise").to_numpy(dtype=float),
        "prior_amount": pd.to_numeric(context.prior20_amount, errors="raise").to_numpy(dtype=float),
        "returns": returns,
        "closes": matrices["close"][:, 1:],
        "volumes": matrices["volume"][:, 1:],
        "market_returns": np.median(returns, axis=0),
    }


def _industry_views(arrays: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    industries = arrays["industries"]
    for industry in sorted(set(industries)):
        indexes = np.flatnonzero(industries == industry)
        if len(indexes) < MIN_INDUSTRY:
            continue
        returns = arrays["returns"][indexes]
        total = returns.sum(axis=0)
        abnormal = returns - (total[None, :] - returns) / (len(indexes) - 1)
        output.append({
            "industry": industry,
            "global_indexes": indexes,
            "symbols": arrays["symbols"][indexes],
            "returns": returns,
            "abnormal": abnormal,
            "closes": arrays["closes"][indexes],
            "up_limits": arrays["up_limits"][indexes],
            "prior_amount": arrays["prior_amount"][indexes],
            "market_returns": arrays["market_returns"],
        })
    return output


def _window_metrics(
    returns: np.ndarray,
    abnormal: np.ndarray,
    market_returns: np.ndarray,
    excluded_index: int,
    start: int,
    stop: int,
) -> dict[str, float]:
    peers = np.arange(returns.shape[0]) != excluded_index
    peer_returns = returns[peers, start:stop]
    peer_abnormal = abnormal[peers, start:stop]
    market_cumulative = float(market_returns[start:stop].sum())
    raw_cumulative = peer_returns.sum(axis=1)
    market_abnormal = raw_cumulative - market_cumulative
    cumulative_abnormal_path = np.cumsum(peer_returns, axis=1) - np.cumsum(
        market_returns[start:stop]
    )[None, :]
    return {
        "median_abnormal": float(np.median(market_abnormal)),
        "mean_abnormal": float(np.mean(market_abnormal)),
        "positive_fraction": float(np.mean(raw_cumulative > 0)),
        "new_trigger_fraction": float(np.mean(np.any(peer_abnormal >= THRESHOLD, axis=1))),
        "median_worst_abnormal": float(np.median(np.min(cumulative_abnormal_path, axis=1))),
    }


def calculate_outcomes(view: dict[str, Any], excluded_index: int, minute_index: int) -> dict[str, float]:
    returns = view["returns"]
    abnormal = view["abnormal"]
    market = view["market_returns"]
    peers = np.arange(returns.shape[0]) != excluded_index
    base_breadth = float(np.mean(returns[peers, minute_index] > 0))
    windows = {
        "w1_3": (minute_index + 1, minute_index + 4),
        "w4_10": (minute_index + 4, minute_index + 11),
        "remainder": (minute_index + 1, returns.shape[1]),
        "reverse": (minute_index - 3, minute_index),
    }
    output: dict[str, float] = {"base_positive_breadth": base_breadth}
    for name, (start, stop) in windows.items():
        metrics = _window_metrics(returns, abnormal, market, excluded_index, start, stop)
        for metric, value in metrics.items():
            output[f"{name}_{metric}"] = value
        output[f"{name}_breadth_expansion"] = metrics["positive_fraction"] - base_breadth
    return output


def _state(view: dict[str, Any], excluded_index: int, minute_index: int) -> np.ndarray:
    peers = np.arange(view["returns"].shape[0]) != excluded_index
    return np.array([
        view["market_returns"][minute_index],
        float(np.mean(view["returns"][:, minute_index])),
        float(np.mean(view["returns"][peers, minute_index] > 0)),
        float(np.log(np.median(view["prior_amount"]))),
    ], dtype=float)


def match_control(
    candidates: deque[tuple[int, str, str, tuple[float, float, float, float]]],
    event_state: np.ndarray,
    calendar_index: int,
) -> tuple[int, str, str, float] | None:
    eligible = [record for record in candidates if 0 < calendar_index - record[0] <= 60]
    if len(eligible) < 20:
        return None
    matrix = np.asarray([record[3] for record in eligible], dtype=float)
    scales = np.maximum(np.std(matrix, axis=0), MATCH_SCALE_FLOORS)
    distances = np.mean(((matrix - event_state[None, :]) / scales[None, :]) ** 2, axis=1)
    order = sorted(
        range(len(eligible)),
        key=lambda index: (float(distances[index]), -eligible[index][0], eligible[index][2]),
    )
    selected = eligible[order[0]]
    return selected[0], selected[1], selected[2], float(distances[order[0]])


def detect_first_event(view: dict[str, Any]) -> tuple[int, int] | None:
    abnormal = view["abnormal"]
    closes = view["closes"]
    up_limits = view["up_limits"]
    for minute_index in range(abnormal.shape[1]):
        triggers = np.flatnonzero(abnormal[:, minute_index] >= THRESHOLD)
        if len(triggers) == 0:
            continue
        if not EVENT_MASK[minute_index]:
            return None
        if len(triggers) != 1:
            return None
        leader = int(triggers[0])
        if view["returns"][leader, minute_index] <= 0:
            return None
        if leader != int(np.argmax(abnormal[:, minute_index])):
            return None
        if closes[leader, minute_index] > up_limits[leader] - 0.01 + 1e-9:
            return None
        return minute_index, leader
    return None


def phase_a_first_pass(
    daily_paths: list[Path], minute_paths: list[Path], raw_paths: dict[int, Path]
) -> tuple[pd.DataFrame, dict[str, Any], list[pd.Timestamp]]:
    history: dict[
        tuple[str, int], deque[tuple[int, str, str, tuple[float, float, float, float]]]
    ] = defaultdict(lambda: deque(maxlen=60))
    events: list[dict[str, Any]] = []
    calendar: list[pd.Timestamp] = []
    audit = {
        "eligible_stock_sessions": 0,
        "eligible_industry_days": 0,
        "industry_minute_control_states": 0,
        "strict_events": 0,
        "simultaneous_cluster_industry_days": 0,
        "out_of_window_first_trigger_industry_days": 0,
        "unbuyable_first_trigger_industry_days": 0,
    }
    for year, minute_path in zip(YEARS, minute_paths):
        context = _load_year_context(year, daily_paths, minute_path)
        by_date = {key: frame for key, frame in context.groupby("trade_date", sort=True)}
        dates = sorted(by_date)
        for trade_date in dates:
            calendar_index = len(calendar)
            calendar.append(pd.Timestamp(trade_date))
            day_context = by_date[trade_date]
            audit["eligible_stock_sessions"] += len(day_context)
            arrays = _load_minute_arrays(raw_paths[year], pd.Timestamp(trade_date), day_context)
            views = _industry_views(arrays)
            audit["eligible_industry_days"] += len(views)
            pending_controls: list[
                tuple[tuple[str, int], tuple[int, str, str, tuple[float, float, float, float]]]
            ] = []
            for view in views:
                threshold_counts = (view["abnormal"] >= THRESHOLD).sum(axis=0)
                nonzero = np.flatnonzero(threshold_counts > 0)
                first_minute = int(nonzero[0]) if len(nonzero) else None
                event = detect_first_event(view)
                if first_minute is not None and not EVENT_MASK[first_minute]:
                    audit["out_of_window_first_trigger_industry_days"] += 1
                elif first_minute is not None and threshold_counts[first_minute] > 1:
                    audit["simultaneous_cluster_industry_days"] += 1
                elif first_minute is not None and event is None:
                    audit["unbuyable_first_trigger_industry_days"] += 1
                if event is not None:
                    minute_index, leader = event
                    event_state = _state(view, leader, minute_index)
                    matched = match_control(
                        history[(view["industry"], minute_index)], event_state, calendar_index
                    )
                    outcomes = calculate_outcomes(view, leader, minute_index)
                    row: dict[str, Any] = {
                        "event_date": pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
                        "calendar_index": calendar_index,
                        "block": "early" if year <= 2020 else "late",
                        "industry": view["industry"],
                        "event_minute": int(CONTINUOUS_MINUTES[minute_index]),
                        "minute_index": int(minute_index),
                        "leader_symbol": str(view["symbols"][leader]),
                        "industry_size": int(len(view["symbols"])),
                        "leader_return": float(view["returns"][leader, minute_index]),
                        "leader_abnormal": float(view["abnormal"][leader, minute_index]),
                        "leader_close_to_limit": float(
                            view["closes"][leader, minute_index] / view["up_limits"][leader] - 1
                        ),
                        "event_market_return": float(event_state[0]),
                        "event_industry_return": float(event_state[1]),
                        "event_peer_breadth": float(event_state[2]),
                        "event_log_median_prior20_amount": float(event_state[3]),
                        "matched": matched is not None,
                    }
                    row.update({f"event_{key}": value for key, value in outcomes.items()})
                    if matched is not None:
                        row.update({
                            "control_calendar_index": matched[0],
                            "control_date": matched[1],
                            "control_pseudo_leader": matched[2],
                            "match_distance": matched[3],
                        })
                    events.append(row)
                    audit["strict_events"] += 1

                for minute_index in EVENT_INDICES:
                    if np.any(view["abnormal"][:, : minute_index + 1] >= THRESHOLD):
                        continue
                    pseudo_leader = int(np.argmax(view["abnormal"][:, minute_index]))
                    state = _state(view, pseudo_leader, int(minute_index))
                    record = (
                        calendar_index,
                        pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
                        str(view["symbols"][pseudo_leader]),
                        tuple(float(value) for value in state),
                    )
                    pending_controls.append(((view["industry"], int(minute_index)), record))
            for key, record in pending_controls:
                history[key].append(record)
            audit["industry_minute_control_states"] += len(pending_controls)
            if len(calendar) % 50 == 0:
                print(
                    f"phase_a_pass1 dates={len(calendar)} events={len(events)} "
                    f"controls={audit['industry_minute_control_states']}",
                    flush=True,
                )
    return pd.DataFrame(events), audit, calendar


def phase_a_control_outcomes(
    events: pd.DataFrame,
    daily_paths: list[Path],
    minute_paths: list[Path],
    raw_paths: dict[int, Path],
) -> pd.DataFrame:
    matched = events.loc[events.matched].copy()
    requests = {
        pd.Timestamp(key): frame
        for key, frame in matched.groupby(pd.to_datetime(matched.control_date), sort=True)
    }
    additions: dict[int, dict[str, float]] = {}
    processed = 0
    for year, minute_path in zip(YEARS, minute_paths):
        year_dates = sorted(date_value for date_value in requests if date_value.year == year)
        if not year_dates:
            continue
        context = _load_year_context(year, daily_paths, minute_path)
        by_date = {key: frame for key, frame in context.groupby("trade_date", sort=True)}
        for trade_date in year_dates:
            if trade_date not in by_date:
                raise CycleError(f"matched control context disappeared: {trade_date.date()}")
            arrays = _load_minute_arrays(raw_paths[year], trade_date, by_date[trade_date])
            views = {view["industry"]: view for view in _industry_views(arrays)}
            for row_index, request in requests[trade_date].iterrows():
                view = views.get(request.industry)
                if view is None:
                    raise CycleError(f"control industry disappeared: {request.industry}")
                symbols = list(view["symbols"])
                if request.control_pseudo_leader not in symbols:
                    raise CycleError("matched pseudo-leader disappeared")
                excluded = symbols.index(request.control_pseudo_leader)
                outcomes = calculate_outcomes(view, excluded, int(request.minute_index))
                additions[int(row_index)] = {
                    f"control_{key}": value for key, value in outcomes.items()
                }
            processed += 1
            if processed % 50 == 0:
                print(f"phase_a_pass2 control_dates={processed}/{len(requests)}", flush=True)
    if len(additions) != int(events.matched.sum()):
        raise CycleError("not every matched control received outcomes")
    for row_index, values in additions.items():
        for column, value in values.items():
            events.loc[row_index, column] = value
    return events


def _delta(frame: pd.DataFrame, metric: str) -> pd.Series:
    return pd.to_numeric(frame[f"event_{metric}"], errors="raise") - pd.to_numeric(
        frame[f"control_{metric}"], errors="raise"
    )


def classify_phase_a(events: pd.DataFrame, audit: dict[str, Any]) -> tuple[str, dict[str, Any], pd.DataFrame]:
    matched = events.loc[events.matched].copy()
    if matched.empty:
        return "NO_PROPAGATION", {"matched_events": 0}, pd.DataFrame()
    metrics = [
        "w1_3_median_abnormal", "w1_3_mean_abnormal", "w1_3_breadth_expansion",
        "w1_3_new_trigger_fraction", "w1_3_median_worst_abnormal",
        "w4_10_median_abnormal", "remainder_median_abnormal", "reverse_median_abnormal",
    ]
    for metric in metrics:
        matched[f"delta_{metric}"] = _delta(matched, metric)
    summary_rows: list[dict[str, Any]] = []
    for label, frame in [("full", matched), ("early", matched.loc[matched.block.eq("early")]), ("late", matched.loc[matched.block.eq("late")])]:
        row: dict[str, Any] = {
            "period": label,
            "matched_events": len(frame),
            "industries": frame.industry.nunique(),
            "decision_dates": frame.event_date.nunique(),
            "median_industry_size": float(frame.industry_size.median()) if len(frame) else math.nan,
            "mean_match_distance": float(frame.match_distance.mean()) if len(frame) else math.nan,
        }
        for metric in metrics:
            row[f"mean_delta_{metric}"] = float(frame[f"delta_{metric}"].mean()) if len(frame) else math.nan
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows)
    full = summary.loc[summary.period.eq("full")].iloc[0]
    early = summary.loc[summary.period.eq("early")].iloc[0]
    late = summary.loc[summary.period.eq("late")].iloc[0]
    match_coverage = len(matched) / len(events) if len(events) else 0.0
    future = float(full.mean_delta_w1_3_median_abnormal)
    reverse = float(full.mean_delta_reverse_median_abnormal)
    later_positive = (
        float(full.mean_delta_w4_10_median_abnormal) > 0
        or float(full.mean_delta_remainder_median_abnormal) > 0
    )
    confirmed_checks = {
        "matched_events": len(matched) >= 1000,
        "industries": int(full.industries) >= 20,
        "decision_dates_early": int(early.decision_dates) >= 100,
        "decision_dates_late": int(late.decision_dates) >= 100,
        "match_coverage": match_coverage >= 0.80,
        "w1_3_return_delta": future >= 0.0002,
        "w1_3_breadth_delta": float(full.mean_delta_w1_3_breadth_expansion) >= 0.01,
        "w1_3_trigger_delta": float(full.mean_delta_w1_3_new_trigger_fraction) >= 0.005,
        "early_positive": float(early.mean_delta_w1_3_median_abnormal) > 0,
        "late_positive": float(late.mean_delta_w1_3_median_abnormal) > 0,
        "future_over_reverse": future - reverse >= 0.0001,
        "later_window_positive": later_positive,
    }
    weak_checks = {
        "matched_events": len(matched) >= 500,
        "full_positive": future > 0,
        "early_positive": float(early.mean_delta_w1_3_median_abnormal) > 0,
        "late_positive": float(late.mean_delta_w1_3_median_abnormal) > 0,
        "future_exceeds_reverse": future > reverse,
    }
    if all(confirmed_checks.values()):
        classification = "PROPAGATION_CONFIRMED"
    elif np.sign(float(early.mean_delta_w1_3_median_abnormal)) != np.sign(
        float(late.mean_delta_w1_3_median_abnormal)
    ):
        classification = "CHRONOLOGICALLY_UNSTABLE"
    elif all(weak_checks.values()):
        classification = "WEAK_PROPAGATION"
    elif future <= reverse and float(matched.event_w1_3_median_abnormal.mean()) > 0:
        classification = "SIMULTANEOUS_COMOVEMENT_ONLY"
    else:
        classification = "NO_PROPAGATION"
    result = {
        "strict_events": len(events),
        "matched_events": len(matched),
        "match_coverage": match_coverage,
        "industries": int(full.industries),
        "decision_dates": int(full.decision_dates),
        "confirmed_checks": confirmed_checks,
        "weak_checks": weak_checks,
        "future_over_reverse_delta": future - reverse,
        "phase_b_c_authorized": classification == "PROPAGATION_CONFIRMED",
        "audit": audit,
    }
    return classification, result, summary


def _render_report(result: dict[str, Any], summary: pd.DataFrame) -> str:
    phase = result["phase_a"]
    lines = [
        "# ASHARE-INDUSTRY-LEAD-FOLLOW-CYCLE-013",
        "",
        "## Claim boundary",
        "",
        "Consumed 2018--2023 development history only. This is not OOS, independent confirmation, validation, live, or production evidence. Post-2023 outcomes and CY-011 were not read.",
        "",
        "## Frozen causal contract",
        "",
        "A strict event is the first industry-day threshold occurrence: one stock alone has leave-one-out industry-abnormal one-minute return at least 1%, has positive raw return, is the unique maximum, and closes at least one tick below its historical upper limit. Multiple same-minute triggers are unresolved simultaneous clusters. The completed minute is signal formation only.",
        "",
        "Followers are all non-triggered peers. Windows are t+1--t+3, t+4--t+10, and t+1--close. Controls come only from the prior 60 market sessions in the same PIT industry and exact clock minute, have no earlier same-day trigger, and are matched on contemporaneous market return, industry return, breadth, and prior liquidity. No future control outcome enters matching.",
        "",
        "## Phase A result",
        "",
        f"Classification: `{phase['classification']}`.",
        "",
        f"Strict events: {phase['strict_events']:,}; matched: {phase['matched_events']:,}; coverage: {phase['match_coverage']:.2%}; industries: {phase['industries']}; decision dates: {phase['decision_dates']}.",
        "",
        "| Period | Events | Industries | Dates | w1--3 return delta | w1--3 breadth delta | w1--3 new-trigger delta | reverse return delta | w4--10 return delta | remainder return delta |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"| {row.period} | {int(row.matched_events):,} | {int(row.industries)} | {int(row.decision_dates)} | "
            f"{row.mean_delta_w1_3_median_abnormal:+.4%} | {row.mean_delta_w1_3_breadth_expansion:+.3%} | "
            f"{row.mean_delta_w1_3_new_trigger_fraction:+.3%} | {row.mean_delta_reverse_median_abnormal:+.4%} | "
            f"{row.mean_delta_w4_10_median_abnormal:+.4%} | {row.mean_delta_remainder_median_abnormal:+.4%} |"
        )
    lines += [
        "",
        f"Future-minus-reverse falsification margin: {phase['future_over_reverse_delta']:+.4%}.",
        "",
        "## Advancement decision",
        "",
    ]
    if phase["phase_b_c_authorized"]:
        lines.append("Phase A cleared every preregistered gate. Phase B/C require a separate locked execution in this same cycle.")
    else:
        lines.append("Phase A did not clear the preregistered confirmation gate. Per the frozen stopping rule, leader identity, leader/follower action testing, portfolio replay, and Industry Diffusion timing analysis were not accessed.")
    lines += [
        "",
        "## Family conclusion",
        "",
        f"Family status: `{result['family_status']}`. The minute data do not support any stronger within-minute or causal claim than the frozen classification permits.",
        "",
    ]
    return "\n".join(lines)


def run(*, verify_hashes: bool = True) -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, minute_paths, raw_paths = _partition_paths()
    if verify_hashes:
        _verify_content_hashes(daily_paths, minute_paths, raw_paths)
    events, audit, calendar = phase_a_first_pass(daily_paths, minute_paths, raw_paths)
    if events.empty:
        raise CycleError("no strict leader events")
    events = phase_a_control_outcomes(events, daily_paths, minute_paths, raw_paths)
    classification, phase_result, summary = classify_phase_a(events, audit)
    family_map = {
        "PROPAGATION_CONFIRMED": "PROPAGATION_CONFIRMED_LONG_ACTION_WEAK",
        "WEAK_PROPAGATION": "NO_PROPAGATION",
        "SIMULTANEOUS_COMOVEMENT_ONLY": "SIMULTANEOUS_COMOVEMENT_ONLY",
        "CHRONOLOGICALLY_UNSTABLE": "CHRONOLOGICALLY_UNSTABLE",
        "NO_PROPAGATION": "NO_PROPAGATION",
    }
    result = {
        "experiment_id": spec["experiment_id"],
        "claim_boundary": spec["claim_boundary"],
        "phase_a": {"classification": classification, **phase_result},
        "phase_b": {"status": "AUTHORIZED_NOT_RUN" if classification == "PROPAGATION_CONFIRMED" else "LOCKED_BY_PHASE_A"},
        "phase_c": {"status": "AUTHORIZED_NOT_RUN" if classification == "PROPAGATION_CONFIRMED" else "LOCKED_BY_PHASE_A"},
        "industry_diffusion_relation": "LOCKED_BY_PHASE_A" if classification != "PROPAGATION_CONFIRMED" else "PENDING_AUTHORIZED_PHASE",
        "family_status": family_map[classification],
        "calendar_sessions": len(calendar),
        "source_content_hashes_verified": verify_hashes,
        "external_panel": str(EXTERNAL_PANEL_PATH),
        "external_panel_sha256": None,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_PATH, index=False, float_format="%.10g")
    EXTERNAL_PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    events.to_parquet(EXTERNAL_PANEL_PATH, index=False, compression="zstd")
    result["external_panel_sha256"] = sha256_file(EXTERNAL_PANEL_PATH)
    result["external_panel_bytes"] = EXTERNAL_PANEL_PATH.stat().st_size
    result["external_panel_rows"] = len(events)
    result["artifacts"] = {
        "summary": {"path": str(SUMMARY_PATH.relative_to(ROOT)), "sha256": sha256_file(SUMMARY_PATH)},
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render_report(result, summary))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-content-hashes", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.verify_only:
        _load_spec()
        daily_paths, minute_paths, raw_paths = _partition_paths()
        _verify_content_hashes(daily_paths, minute_paths, raw_paths)
        print("all frozen source content hashes verified")
        return
    result = run(verify_hashes=not arguments.skip_content_hashes)
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
