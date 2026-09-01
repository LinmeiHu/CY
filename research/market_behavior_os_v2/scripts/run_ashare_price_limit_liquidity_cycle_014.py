#!/usr/bin/env python3
"""Run frozen price-limit lifecycle and liquidity-transition Cycle 014."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_result.json"
LIFECYCLE_SUMMARY_PATH = (
    PROGRAM / "artifacts/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_lifecycle_summary.csv"
)
CONTRAST_SUMMARY_PATH = (
    PROGRAM / "artifacts/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_contrast_summary.csv"
)
LIQUIDITY_SUMMARY_PATH = (
    PROGRAM / "artifacts/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_liquidity_summary.csv"
)
REPORT_PATH = PROGRAM / "reports/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/price_limit_liquidity_cycle_014")
LIFECYCLE_PANEL_PATH = EXTERNAL_ROOT / "price_limit_event_panel.parquet"
LIQUIDITY_PANEL_PATH = EXTERNAL_ROOT / "liquidity_transition_panel.parquet"
TEMP_PATH = EXTERNAL_ROOT / "duckdb_tmp"

CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY008_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/CY-008-pit-b-minute-v2-2018-2026-20260821.json"
)
QD004_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-004-2018-2026-20260820.json"
)
ADAPTER_PATH = PROGRAM / "scripts/vectorized_market_minute_adapter.py"
EXPECTED_SPEC_SHA256 = "5b3927bce011a83c13053a8be9ba0aceb4e046699960e3f35c9b99d910d457c2"
YEARS = tuple(range(2018, 2024))
COST_ROUND_TRIP = 0.004
SEVERE = -0.10


class CycleError(RuntimeError):
    """Fail-closed Cycle-014 error."""


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
    if value is None or pd.isna(value):
        return None
    return value


def _load_adapter() -> Any:
    module_spec = importlib.util.spec_from_file_location("minute_adapter_for_014", ADAPTER_PATH)
    if module_spec is None or module_spec.loader is None:
        raise CycleError("cannot load accepted minute adapter")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


ADAPTER = _load_adapter()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CycleError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BOTH_TRACKS_BEFORE_FORWARD_OUTCOME_ACCESS_REPLAY_LOCKED":
        raise CycleError("both tracks were not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CycleError(f"bound input changed: {role}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "within-minute", "replay before"):
        if phrase not in prohibited:
            raise CycleError(f"missing prohibition: {phrase}")
    return spec


def _manifest(path: Path) -> tuple[Path, dict[str, dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Path(raw["root"]), {item["path"]: item for item in raw["files"]}


def _paths() -> tuple[list[Path], list[Path], dict[int, Path]]:
    cy6_root, cy6 = _manifest(CY006_MANIFEST)
    cy8_root, cy8 = _manifest(CY008_MANIFEST)
    qd_root, qd = _manifest(QD004_MANIFEST)
    daily: list[Path] = []
    minute: list[Path] = []
    raw: dict[int, Path] = {}
    for year in YEARS:
        entries = [
            (cy6_root, cy6, f"partition_year={year}/data_0.parquet", daily),
            (cy8_root, cy8, f"daily/partition_year={year}/data_0.parquet", minute),
        ]
        for root, records, relative, output in entries:
            record = records.get(relative)
            path = root / relative
            if record is None or not path.is_file() or path.stat().st_size != int(record["size"]):
                raise CycleError(f"partition identity mismatch: {relative}")
            output.append(path)
        relative = f"bars/{year}_day_parquet_none.parquet"
        record = qd.get(relative)
        path = qd_root / relative
        if record is None or not path.is_file() or path.stat().st_size != int(record["size"]):
            raise CycleError(f"raw minute identity mismatch: {relative}")
        raw[year] = path
    return daily, minute, raw


def _verify_hashes(daily: list[Path], minute: list[Path], raw: dict[int, Path]) -> None:
    for manifest_path, paths in ((CY006_MANIFEST, daily), (CY008_MANIFEST, minute)):
        root, records = _manifest(manifest_path)
        lookup = {root / relative: item for relative, item in records.items()}
        for path in paths:
            if sha256_file(path) != lookup[path]["sha256"]:
                raise CycleError(f"content hash mismatch: {path}")
    root, records = _manifest(QD004_MANIFEST)
    lookup = {root / relative: item for relative, item in records.items()}
    for path in raw.values():
        if sha256_file(path) != lookup[path]["sha256"]:
            raise CycleError(f"content hash mismatch: {path}")


def _configure(daily_paths: list[Path]) -> duckdb.DuckDBPyConnection:
    TEMP_PATH.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='10GB'")
    connection.execute(f"SET temp_directory='{TEMP_PATH.as_posix()}'")
    path_sql = "[" + ",".join("'" + path.as_posix() + "'" for path in daily_paths) + "]"
    create_view_sql = (
        "CREATE TEMP VIEW daily_source AS SELECT * "
        f"FROM read_parquet({path_sql},union_by_name=true)"
    )
    connection.execute(create_view_sql)
    connection.execute("""
      CREATE TEMP TABLE calendar AS
      SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 cal_idx
      FROM (SELECT DISTINCT trade_date FROM daily_source) ORDER BY trade_date
    """)
    connection.execute("""
      CREATE TEMP TABLE stage1 AS
      SELECT d.*,c.cal_idx,
        CASE WHEN d.close>0 AND d.preclose>0 THEN ln(d.close/d.preclose) END daily_return,
        CASE WHEN d.high>d.low THEN (d.close-d.low)/(d.high-d.low) ELSE 0.5 END close_location,
        CASE WHEN d.up_limit_price>d.preclose
          THEN (d.close-d.preclose)/(d.up_limit_price-d.preclose) END close_limit_coordinate,
        (coalesce(d.corporate_action_count,-1)=0 AND d.corporate_action_blocking IS FALSE
          AND coalesce(d.cash_per_share,0)=0 AND coalesce(d.share_multiplier,1)=1
          AND coalesce(d.rights_ratio,0)=0) action_clean,
        (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
          AND d.industry_valid IS TRUE AND d.corporate_action_valid IS TRUE
          AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
          AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
          AND d.trade_status=1 AND d.current_day_data_tradable IS TRUE
          AND d.open>0 AND d.close>0 AND d.amount>0 AND d.up_limit_price>d.preclose
          AND d.limit_pct IS NOT NULL) signal_eligible
      FROM daily_source d JOIN calendar c USING(trade_date)
      WHERE year(d.trade_date) BETWEEN 2018 AND 2023
    """)
    connection.execute("""
      CREATE TEMP TABLE stage2 AS
      SELECT *,
        avg(amount) OVER w20 prior20_mean_amount,
        median(amount) OVER w20 prior20_median_amount,
        count(amount) OVER w20 prior20_count,
        avg(amount) OVER w5 prior5_mean_amount,
        median(amount) OVER w60 prior60_median_amount,
        count(amount) OVER w60 prior60_count,
        sum(daily_return) OVER w20 prior_r20,
        median(turnover_fraction) OVER w20 prior20_median_turnover
      FROM stage1
      WINDOW
        w5 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        w20 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w60 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
    """)
    connection.execute("""
      CREATE TEMP TABLE base AS
      SELECT *,amount/nullif(prior20_median_amount,0) activity_ratio,
        prior5_mean_amount/nullif(prior60_median_amount,0) dormant_ratio,
        turnover_fraction/nullif(prior20_median_turnover,0) turnover_ratio,
        lag(amount/nullif(prior20_median_amount,0)) OVER(PARTITION BY symbol ORDER BY cal_idx)
          lag_activity_ratio,
        (signal_eligible AND action_clean AND buy_blocked_open IS FALSE) buy_ok,
        (signal_eligible AND action_clean AND sell_blocked_open IS FALSE) sell_ok,
        (high>=up_limit_price-greatest(0.001,abs(up_limit_price)*1e-6)) touch_daily
      FROM stage2
    """)
    connection.execute("CREATE INDEX base_key ON base(symbol,cal_idx)")
    return connection


def classify_lifecycle(
    minutes: np.ndarray,
    high: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    preclose: float,
    up_limit: float,
) -> dict[str, Any]:
    tolerance = max(0.001, abs(up_limit) * 1e-6)
    touched = high >= up_limit - tolerance
    if not touched.any():
        raise CycleError("daily limit touch did not reconcile to minute bars")
    accepted = np.abs(close - up_limit) <= tolerance
    touch_index = int(np.flatnonzero(touched)[0])
    accept_indexes = np.flatnonzero(accepted)
    first_accept = int(accept_indexes[0]) if len(accept_indexes) else None
    reopen_episodes = int(np.sum(accepted[:-1] & ~accepted[1:]))
    final_accepted = bool(accepted[-1])
    if not final_accepted:
        lifecycle = "FAILED_ACCEPTANCE"
    elif reopen_episodes > 0:
        lifecycle = "REOPEN_SUCCESSFUL_RESEAL"
    elif first_accept is None:
        raise CycleError("accepted close without accepted minute")
    elif minutes[first_accept] <= 11 * 60:
        lifecycle = "EARLY_STABLE_ACCEPTANCE"
    elif minutes[first_accept] < 14 * 60:
        lifecycle = "MID_STABLE_ACCEPTANCE"
    else:
        lifecycle = "LATE_STABLE_ACCEPTANCE"
    coordinate = (high - preclose) / (up_limit - preclose)
    approach = np.flatnonzero(coordinate >= 0.98)
    remaining = accepted[touch_index:]
    below = np.maximum(0.0, (up_limit - close[touch_index:]) / up_limit)
    before_volume = float(np.mean(volume[:touch_index])) if touch_index else math.nan
    after_volume = float(np.mean(volume[touch_index:]))
    volume_ratio = after_volume / before_volume if before_volume > 0 else math.nan
    cutoff_1400 = int(np.flatnonzero(minutes <= 14 * 60)[-1])
    reopened_by_1400 = bool(
        first_accept is not None
        and first_accept < cutoff_1400
        and np.any(
            accepted[first_accept:cutoff_1400] & ~accepted[first_accept + 1 : cutoff_1400 + 1]
        )
    )
    return {
        "lifecycle": lifecycle,
        "first_approach_minute": int(minutes[int(approach[0])]) if len(approach) else None,
        "first_touch_minute": int(minutes[touch_index]),
        "first_accept_minute": int(minutes[first_accept]) if first_accept is not None else None,
        "accepted_fraction_remaining": float(np.mean(remaining)),
        "reopen_episodes": reopen_episodes,
        "cumulative_distance_below": float(np.sum(below)),
        "closing_distance": float(close[-1] / up_limit - 1.0),
        "post_pre_touch_volume_ratio": volume_ratio,
        "proxy_1400": bool(
            first_accept is not None
            and minutes[first_accept] <= 11 * 60
            and accepted[cutoff_1400]
            and not reopened_by_1400
        ),
    }


def _minute_context(
    year: int, minute_path: Path, connection: duckdb.DuckDBPyConnection
) -> pd.DataFrame:
    candidates = connection.execute(f"""
      SELECT trade_date,cal_idx,symbol,industry,limit_pct,up_limit_price,preclose,close,
        daily_return,prior_r20,prior20_mean_amount,turnover_ratio,is_st
        ,snapshot_id
      FROM base WHERE year(trade_date)={year} AND signal_eligible AND action_clean
        AND touch_daily AND prior20_count=20 AND prior20_mean_amount>=20000000
        AND isfinite(prior_r20) AND isfinite(turnover_ratio)
      ORDER BY trade_date,symbol
    """).fetch_df()
    columns = [
        "trade_date",
        "symbol",
        "available_at",
        "minute_count",
        "distinct_minute_count",
        "source_resolution_minutes",
        "session_complete",
        "ohlc_valid",
        "unit_valid",
        "volume_reconciled",
        "amount_reconciled",
        "daily_hard_valid",
        "hard_valid",
        "daily_snapshot_id",
    ]
    minute = pq.read_table(minute_path, columns=columns, use_threads=False).to_pandas()
    minute["trade_date"] = pd.to_datetime(minute.trade_date)
    expected = minute.trade_date + pd.Timedelta(hours=15, minutes=30)
    available = pd.to_datetime(minute.available_at, errors="coerce")
    valid = (
        available.eq(expected)
        & pd.to_numeric(minute.minute_count).eq(241)
        & pd.to_numeric(minute.distinct_minute_count).eq(241)
        & pd.to_numeric(minute.source_resolution_minutes).eq(1)
        & minute.session_complete.astype("boolean").fillna(False)
        & minute.ohlc_valid.astype("boolean").fillna(False)
        & minute.unit_valid.astype("boolean").fillna(False)
        & minute.volume_reconciled.astype("boolean").fillna(False)
        & minute.amount_reconciled.astype("boolean").fillna(False)
        & minute.daily_hard_valid.astype("boolean").fillna(False)
        & minute.hard_valid.astype("boolean").fillna(False)
    )
    minute = minute.loc[valid, ["trade_date", "symbol", "daily_snapshot_id"]]
    candidates["trade_date"] = pd.to_datetime(candidates.trade_date)
    merged = candidates.merge(
        minute, on=["trade_date", "symbol"], how="inner", validate="one_to_one"
    )
    merged = merged.loc[merged.daily_snapshot_id.eq(merged.snapshot_id)].copy()
    return merged.drop(columns=["daily_snapshot_id"])


def build_lifecycle_panel(
    connection: duckdb.DuckDBPyConnection,
    minute_paths: list[Path],
    raw_paths: dict[int, Path],
) -> tuple[pd.DataFrame, dict[str, int]]:
    rows: list[dict[str, Any]] = []
    invalid_matching = connection.execute("""
      SELECT count(*) FROM base WHERE signal_eligible AND action_clean AND touch_daily
        AND prior20_count=20 AND prior20_mean_amount>=20000000
        AND (NOT isfinite(prior_r20) OR NOT isfinite(turnover_ratio))
    """).fetchone()[0]
    audit = {
        "daily_touch_candidates": 0,
        "raw_touch_mismatches_excluded": 0,
        "invalid_matching_state_excluded": int(invalid_matching),
    }
    for year, minute_path in zip(YEARS, minute_paths, strict=True):
        context = _minute_context(year, minute_path, connection)
        for position, (trade_date, day) in enumerate(context.groupby("trade_date", sort=True), 1):
            source_symbols = day.symbol.astype(str).str.split(".", regex=False).str[0].unique()
            table = ADAPTER.read_raw_table(
                raw_paths[year], [pd.Timestamp(trade_date).date()], source_symbols
            )
            frame = table.select(
                ["symbol", "exchange", "bar_end_time", "high", "close", "volume"]
            ).to_pandas()
            frame["full_symbol"] = frame.symbol.astype(str) + "." + frame.exchange.astype(str)
            frame = frame.loc[frame.full_symbol.isin(set(day.symbol.astype(str)))].copy()
            frame = frame.sort_values(["full_symbol", "bar_end_time"], kind="mergesort")
            counts = frame.groupby("full_symbol", sort=False).size()
            if not counts.eq(241).all() or set(counts.index) != set(day.symbol.astype(str)):
                raise CycleError(f"raw/CY-008 lifecycle session mismatch: {trade_date}")
            for symbol, bars in frame.groupby("full_symbol", sort=False):
                daily = day.loc[day.symbol.astype(str).eq(symbol)].iloc[0]
                audit["daily_touch_candidates"] += 1
                minutes = (
                    pd.to_datetime(bars.bar_end_time).dt.hour * 60
                    + pd.to_datetime(bars.bar_end_time).dt.minute
                ).to_numpy(np.int16)
                if not np.array_equal(minutes, ADAPTER.EXPECTED_MINUTES):
                    raise CycleError("lifecycle minute grid changed")
                tolerance = max(0.001, abs(float(daily.up_limit_price)) * 1e-6)
                if float(bars.high.max()) < float(daily.up_limit_price) - tolerance:
                    audit["raw_touch_mismatches_excluded"] += 1
                    continue
                try:
                    classification = classify_lifecycle(
                        minutes,
                        bars.high.to_numpy(float),
                        bars.close.to_numpy(float),
                        bars.volume.to_numpy(float),
                        float(daily.preclose),
                        float(daily.up_limit_price),
                    )
                except CycleError as error:
                    raise CycleError(
                        f"{error}: date={pd.Timestamp(trade_date).date()} symbol={symbol} "
                        f"raw_high={bars.high.max()} registered_limit={daily.up_limit_price}"
                    ) from error
                row = daily.to_dict()
                row.update(classification)
                row.update({"track": "A", "uid": f"A|{pd.Timestamp(trade_date).date()}|{symbol}"})
                rows.append(row)
            if position % 100 == 0:
                print(f"track_a year={year} dates={position} events={len(rows)}", flush=True)
    panel = pd.DataFrame(rows)
    if panel.empty:
        raise CycleError("no lifecycle events")
    panel["block"] = np.where(pd.to_datetime(panel.trade_date).dt.year <= 2020, "early", "late")
    return panel, audit


def build_liquidity_candidates(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = connection.execute("""
      WITH eligible AS (
        SELECT * FROM base WHERE signal_eligible AND action_clean AND prior60_count=60
          AND prior20_count=20 AND prior20_mean_amount>=20000000 AND NOT touch_daily
          AND isfinite(activity_ratio) AND isfinite(prior_r20)
      )
      SELECT 'DORMANT_ACTIVE_CONSTRUCTIVE' hypothesis,'event' sample_role,* FROM eligible
        WHERE dormant_ratio<=0.65 AND activity_ratio BETWEEN 2 AND 5
          AND daily_return>0 AND close_location>=0.75 AND close_limit_coordinate<0.90
      UNION ALL
      SELECT 'DORMANT_ACTIVE_CONSTRUCTIVE','control',* FROM eligible
        WHERE dormant_ratio<=0.65 AND activity_ratio BETWEEN 2 AND 5
          AND NOT(daily_return>0 AND close_location>=0.75) AND close_limit_coordinate<0.90
      UNION ALL
      SELECT 'ACTIVITY_SHOCK_REJECTION','event',* FROM eligible
        WHERE activity_ratio>=3 AND (daily_return<=0 OR close_location<=0.25)
      UNION ALL
      SELECT 'ACTIVITY_SHOCK_REJECTION','control',* FROM eligible
        WHERE activity_ratio>=3 AND daily_return>0 AND close_location>=0.50
      UNION ALL
      SELECT 'LIQUIDITY_RECOVERY_AFTER_WITHDRAWAL','event',* FROM eligible
        WHERE lag_activity_ratio<=0.50 AND activity_ratio BETWEEN 0.8 AND 1.5
          AND abs(daily_return)<=0.02 AND close_location>=0.50
      UNION ALL
      SELECT 'LIQUIDITY_RECOVERY_AFTER_WITHDRAWAL','control',* FROM eligible
        WHERE lag_activity_ratio<=0.50 AND activity_ratio<=0.60
    """).fetch_df()
    keep = [
        "hypothesis",
        "sample_role",
        "trade_date",
        "cal_idx",
        "symbol",
        "industry",
        "close",
        "prior_r20",
        "prior20_mean_amount",
        "activity_ratio",
        "daily_return",
        "close_location",
    ]
    frame = frame[keep].copy()
    frame = frame.rename(columns={"sample_role": "role"})
    frame["uid"] = (
        "B|"
        + frame.hypothesis
        + "|"
        + frame.role
        + "|"
        + frame.trade_date.astype(str)
        + "|"
        + frame.symbol
    )
    frame["track"] = "B"
    frame["block"] = np.where(pd.to_datetime(frame.trade_date).dt.year <= 2020, "early", "late")
    return frame


def nearest_pairs(
    events: pd.DataFrame,
    controls: pd.DataFrame,
    features: list[str],
    scales: np.ndarray,
    group_columns: list[str],
    label: str,
) -> pd.DataFrame:
    pairs: list[dict[str, Any]] = []
    grouped_controls = {
        key: frame.sort_values("symbol")
        for key, frame in controls.groupby(group_columns, sort=False)
    }
    for key, event_group in events.groupby(group_columns, sort=False):
        control_group = grouped_controls.get(key)
        if control_group is None or control_group.empty:
            continue
        full_values = control_group[features].to_numpy(float) / scales
        full_tree = cKDTree(full_values)
        industry_pools = {
            industry: (
                frame.sort_values("symbol"),
                cKDTree(frame[features].to_numpy(float) / scales),
            )
            for industry, frame in control_group.groupby("industry", sort=False)
        }
        for _, event in event_group.iterrows():
            pool, tree = industry_pools.get(event.industry, (control_group, full_tree))
            distance, index = tree.query(event[features].to_numpy(float) / scales, k=1)
            control = pool.iloc[int(index)]
            pairs.append(
                {
                    "comparison": label,
                    "event_uid": event.uid,
                    "control_uid": control.uid,
                    "event_block": event.block,
                    "event_date": str(event.trade_date),
                    "event_symbol": event.symbol,
                    "control_symbol": control.symbol,
                    "same_industry": bool(event.industry == control.industry),
                    "match_distance": float(distance),
                }
            )
    return pd.DataFrame(pairs)


def build_pairs(
    lifecycle: pd.DataFrame, liquidity: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    lifecycle_match = lifecycle.copy()
    lifecycle_match["log_prior20_amount"] = np.log(
        lifecycle_match.prior20_mean_amount.astype(float)
    )
    stable = lifecycle_match.loc[lifecycle_match.lifecycle.str.contains("STABLE_ACCEPTANCE")]
    failed = lifecycle_match.loc[lifecycle_match.lifecycle.eq("FAILED_ACCEPTANCE")]
    reseal = lifecycle_match.loc[lifecycle_match.lifecycle.eq("REOPEN_SUCCESSFUL_RESEAL")]
    early = lifecycle_match.loc[lifecycle_match.lifecycle.eq("EARLY_STABLE_ACCEPTANCE")]
    late = lifecycle_match.loc[lifecycle_match.lifecycle.eq("LATE_STABLE_ACCEPTANCE")]
    a_features = ["prior_r20", "log_prior20_amount", "daily_return", "turnover_ratio"]
    a_pairs = pd.concat(
        [
            nearest_pairs(
                stable,
                failed,
                a_features,
                np.array([0.05, 1, 0.05, 1]),
                ["trade_date", "limit_pct"],
                "STABLE_VS_FAILED",
            ),
            nearest_pairs(
                stable,
                reseal,
                a_features,
                np.array([0.05, 1, 0.05, 1]),
                ["trade_date", "limit_pct"],
                "STABLE_VS_RESEAL",
            ),
            nearest_pairs(
                early,
                late,
                a_features,
                np.array([0.05, 1, 0.05, 1]),
                ["trade_date", "limit_pct"],
                "EARLY_VS_LATE",
            ),
        ],
        ignore_index=True,
    )
    b_pairs_list: list[pd.DataFrame] = []
    b_features = ["prior_r20", "log_prior20_amount", "activity_ratio"]
    liquidity = liquidity.copy()
    liquidity["log_prior20_amount"] = np.log(liquidity.prior20_mean_amount.astype(float))
    for hypothesis in sorted(liquidity.hypothesis.unique()):
        subset = liquidity.loc[liquidity.hypothesis.eq(hypothesis)]
        b_pairs_list.append(
            nearest_pairs(
                subset.loc[subset.role.eq("event")],
                subset.loc[subset.role.eq("control")],
                b_features,
                np.array([0.05, 1, 1]),
                ["trade_date"],
                hypothesis,
            )
        )
    return a_pairs, pd.concat(b_pairs_list, ignore_index=True)


def attach_execution(
    connection: duckdb.DuckDBPyConnection,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    daily = connection.execute("""
      SELECT symbol,cal_idx,trade_date,open,amount,buy_ok,sell_ok,action_clean,
        buy_blocked_open,trade_status,current_day_data_tradable
      FROM base ORDER BY symbol,cal_idx
    """).fetch_df()
    groups: dict[str, dict[str, np.ndarray]] = {}
    for symbol, frame in daily.groupby("symbol", sort=False):
        groups[str(symbol)] = {
            "cal_idx": frame.cal_idx.to_numpy(np.int64),
            "trade_date": frame.trade_date.to_numpy(),
            "open": frame.open.to_numpy(float),
            "amount": frame.amount.to_numpy(float),
            "buy_ok": frame.buy_ok.astype("boolean").fillna(False).to_numpy(bool),
            "sell_ok": frame.sell_ok.astype("boolean").fillna(False).to_numpy(bool),
            "action_clean": frame.action_clean.astype("boolean").fillna(False).to_numpy(bool),
            "buy_blocked": frame.buy_blocked_open.astype("boolean").fillna(True).to_numpy(bool),
            "trade_status": pd.to_numeric(frame.trade_status, errors="coerce")
            .fillna(0)
            .to_numpy(int),
            "tradable": frame.current_day_data_tradable.astype("boolean")
            .fillna(False)
            .to_numpy(bool),
        }
    del daily

    def exact_position(calendar: np.ndarray, target: int) -> int | None:
        position = int(np.searchsorted(calendar, target))
        return position if position < len(calendar) and int(calendar[position]) == target else None

    records: list[dict[str, Any]] = []
    minimal = candidates[["uid", "symbol", "cal_idx"]].drop_duplicates("uid")
    for number, row in enumerate(minimal.itertuples(index=False), 1):
        data = groups.get(str(row.symbol))
        record: dict[str, Any] = {
            "uid": row.uid,
            "entry_idx": math.nan,
            "entry_date": None,
            "entry_open": math.nan,
            "entry_amount": math.nan,
            "next_buy_ok": False,
            "next_buy_blocked": True,
            "next_suspended": True,
            "exit_open_h1": math.nan,
            "exit_open_h3": math.nan,
            "exit_open_h5": math.nan,
        }
        if data is None:
            records.append(record)
            continue
        calendar = data["cal_idx"]
        event_position = exact_position(calendar, int(row.cal_idx))
        if event_position is None:
            records.append(record)
            continue
        next_position = exact_position(calendar, int(row.cal_idx) + 1)
        if next_position is not None:
            record["next_buy_ok"] = bool(data["buy_ok"][next_position])
            record["next_buy_blocked"] = bool(data["buy_blocked"][next_position])
            record["next_suspended"] = bool(
                data["trade_status"][next_position] != 1 or not data["tradable"][next_position]
            )
        entry_position: int | None = None
        for target in range(int(row.cal_idx) + 1, int(row.cal_idx) + 4):
            position = exact_position(calendar, target)
            if position is None:
                continue
            if not data["action_clean"][event_position + 1 : position + 1].all():
                break
            if data["buy_ok"][position]:
                entry_position = position
                record.update(
                    {
                        "entry_idx": int(calendar[position]),
                        "entry_date": data["trade_date"][position],
                        "entry_open": float(data["open"][position]),
                        "entry_amount": float(data["amount"][position]),
                    }
                )
                break
        if entry_position is not None:
            for horizon in (1, 3, 5):
                target_start = int(calendar[entry_position]) + horizon
                for target in range(target_start, target_start + 4):
                    position = exact_position(calendar, target)
                    if position is None:
                        continue
                    if not data["action_clean"][event_position + 1 : position + 1].all():
                        break
                    if data["sell_ok"][position]:
                        record[f"exit_open_h{horizon}"] = float(data["open"][position])
                        break
        records.append(record)
        if number % 50000 == 0:
            print(f"execution_walk candidates={number}/{len(minimal)}", flush=True)
    execution = pd.DataFrame(records)
    output = candidates.merge(execution, on="uid", how="left", validate="many_to_one")
    output["entry_coverage"] = output.entry_open.notna()
    output["entry_delay"] = output.entry_idx - output.cal_idx
    output["capacity_cny"] = 0.01 * output.prior20_mean_amount.astype(float)
    output["next_gap"] = output.entry_open / output.close - 1
    for horizon in (1, 3, 5):
        output[f"net_h{horizon}"] = (
            output[f"exit_open_h{horizon}"] / output.entry_open - 1 - COST_ROUND_TRIP
        )
    return output


def summarize_groups(frame: pd.DataFrame, group: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, subset in frame.groupby(group, sort=True):
        row: dict[str, Any] = {
            group: label,
            "events": len(subset),
            "dates": subset.trade_date.nunique(),
            "symbols": subset.symbol.nunique(),
            "entry_coverage": float(subset.entry_coverage.mean()),
            "next_day_blocked": float(
                subset.next_buy_blocked.astype("boolean").fillna(False).mean()
            ),
            "next_day_suspended": float(
                subset.next_suspended.astype("boolean").fillna(False).mean()
            ),
            "median_capacity_cny": float(subset.capacity_cny.median()),
            "p10_capacity_cny": float(subset.capacity_cny.quantile(0.10)),
        }
        for horizon in (1, 3, 5):
            values = pd.to_numeric(subset[f"net_h{horizon}"], errors="coerce").dropna()
            row[f"complete_h{horizon}"] = len(values)
            row[f"mean_net_h{horizon}"] = float(values.mean()) if len(values) else math.nan
            row[f"median_net_h{horizon}"] = float(values.median()) if len(values) else math.nan
        h3 = pd.to_numeric(subset.net_h3, errors="coerce")
        h5 = pd.to_numeric(subset.net_h5, errors="coerce")
        row["winner_h3"] = float((h3.dropna() > 0).mean())
        row["severe_h5"] = float((h5.dropna() <= SEVERE).mean())
        for block in ("early", "late"):
            values = pd.to_numeric(
                subset.loc[subset.block.eq(block), "net_h3"], errors="coerce"
            ).dropna()
            row[f"mean_net_h3_{block}"] = float(values.mean()) if len(values) else math.nan
            row[f"events_{block}"] = int(subset.block.eq(block).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_pairs(pairs: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    indexed = outcomes.drop_duplicates("uid").set_index("uid")
    rows: list[dict[str, Any]] = []
    for comparison, subset in pairs.groupby("comparison", sort=True):
        event = indexed.loc[subset.event_uid]
        control = indexed.loc[subset.control_uid]
        valid = (
            event.net_h3.notna().to_numpy()
            & control.net_h3.notna().to_numpy()
            & event.net_h5.notna().to_numpy()
            & control.net_h5.notna().to_numpy()
        )
        event = event.iloc[np.flatnonzero(valid)]
        control = control.iloc[np.flatnonzero(valid)]
        block = subset.event_block.to_numpy()[valid]
        delta = event.net_h3.to_numpy(float) - control.net_h3.to_numpy(float)
        row = {
            "comparison": comparison,
            "pairs": len(subset),
            "complete_pairs": int(valid.sum()),
            "same_industry_fraction": float(subset.same_industry.mean()),
            "mean_match_distance": float(subset.match_distance.mean()),
            "mean_net_h3_delta": float(np.mean(delta)) if len(delta) else math.nan,
            "winner_improvement": float(
                np.mean(event.net_h3.to_numpy() > 0) - np.mean(control.net_h3.to_numpy() > 0)
            )
            if len(delta)
            else math.nan,
            "severe_h5_improvement": float(
                np.mean(control.net_h5.to_numpy() <= SEVERE)
                - np.mean(event.net_h5.to_numpy() <= SEVERE)
            )
            if len(delta)
            else math.nan,
            "mean_net_h3_delta_early": float(np.mean(delta[block == "early"]))
            if np.any(block == "early")
            else math.nan,
            "mean_net_h3_delta_late": float(np.mean(delta[block == "late"]))
            if np.any(block == "late")
            else math.nan,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def classify_results(
    lifecycle_summary: pd.DataFrame,
    contrasts: pd.DataFrame,
    liquidity_summary: pd.DataFrame,
    liquidity_contrasts: pd.DataFrame,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    stable = contrasts.loc[contrasts.comparison.eq("STABLE_VS_FAILED")].iloc[0]
    stable_rows = lifecycle_summary.loc[
        lifecycle_summary.lifecycle.str.contains("STABLE_ACCEPTANCE")
    ]
    coverage = float(np.average(stable_rows.entry_coverage, weights=stable_rows.events))
    info_checks = {
        "pairs": int(stable.complete_pairs) >= 500,
        "coverage": coverage >= 0.80,
        "h3_delta": float(stable.mean_net_h3_delta) >= 0.0025,
        "early": float(stable.mean_net_h3_delta_early) > 0,
        "late": float(stable.mean_net_h3_delta_late) > 0,
        "severe": float(stable.severe_h5_improvement) >= 0.01,
        "winner": float(stable.winner_improvement) >= 0.02,
    }
    stable_h3 = float(np.average(stable_rows.mean_net_h3, weights=stable_rows.complete_h3))
    standalone = (
        int(stable_rows.complete_h3.sum()) >= 500
        and coverage >= 0.80
        and stable_h3 >= 0.005
        and (stable_rows.mean_net_h3_early > 0).all()
        and (stable_rows.mean_net_h3_late > 0).all()
        and (stable_rows.severe_h5 <= 0.10).all()
    )
    if standalone:
        track_a = "PRICE_LIMIT_STRATEGY_CANDIDATE"
    elif all(info_checks.values()):
        track_a = "FAILED_ACCEPTANCE_DOWNSIDE_INFORMATION"
    elif np.sign(stable.mean_net_h3_delta_early) != np.sign(stable.mean_net_h3_delta_late):
        track_a = "CHRONOLOGICALLY_MIXED"
    elif (
        stable.mean_net_h3_delta > 0
        and stable.mean_net_h3_delta_early > 0
        and stable.mean_net_h3_delta_late > 0
    ):
        track_a = "PRICE_LIMIT_ACCEPTANCE_INFORMATION_ONLY"
    else:
        track_a = "NO_USEFUL_LIFECYCLE_INFORMATION"
    track_b: dict[str, str] = {}
    promotion: list[str] = []
    for _, row in liquidity_contrasts.iterrows():
        summary = liquidity_summary.loc[
            (liquidity_summary.hypothesis.eq(row.comparison)) & liquidity_summary.role.eq("event")
        ].iloc[0]
        orientation = -1.0 if row.comparison == "ACTIVITY_SHOCK_REJECTION" else 1.0
        oriented_delta = orientation * float(row.mean_net_h3_delta)
        oriented_early = orientation * float(row.mean_net_h3_delta_early)
        oriented_late = orientation * float(row.mean_net_h3_delta_late)
        oriented_severe = orientation * float(row.severe_h5_improvement)
        checks = (
            row.complete_pairs >= 1000
            and summary.entry_coverage >= 0.90
            and oriented_delta >= 0.0025
            and oriented_early > 0
            and oriented_late > 0
            and oriented_severe >= 0.01
            and summary.events_early >= 100
            and summary.events_late >= 100
        )
        if checks and row.comparison != "ACTIVITY_SHOCK_REJECTION":
            classification = "LIQUIDITY_TRANSITION_STRATEGY_CANDIDATE"
            promotion.append(row.comparison)
        elif checks:
            classification = "PROMISING_INFORMATION"
        elif np.sign(oriented_early) != np.sign(oriented_late):
            classification = "CHRONOLOGICALLY_MIXED"
        elif oriented_delta > 0 and oriented_early > 0 and oriented_late > 0:
            classification = "PROMISING_INFORMATION"
        elif oriented_delta < 0 and oriented_early < 0 and oriented_late < 0:
            classification = "ADVERSE"
        else:
            classification = "ECONOMICALLY_NULL"
        track_b[row.comparison] = classification
    gates = {
        "track_a_information_checks": info_checks,
        "track_a_standalone": standalone,
        "track_b_promotions": promotion[:1],
    }
    return track_a, track_b, gates


def _report(
    result: dict[str, Any],
    lifecycle: pd.DataFrame,
    contrasts: pd.DataFrame,
    liquidity: pd.DataFrame,
    liquidity_contrasts: pd.DataFrame,
) -> str:
    lines = [
        "# ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014",
        "",
        "Consumed 2018--2023 development history only; not OOS, independent "
        "confirmation, validation, live, or production evidence. Post-2023 "
        "outcomes and CY-011 were not read.",
        "",
        "## Price-limit lifecycle",
        "",
        "Historical `up_limit_price` and `limit_pct` are used stock-date by "
        "stock-date. A touch is a completed bar high at the registered limit; "
        "acceptance is a completed bar close at the limit. Transitions inside "
        "one bar remain unresolved.",
        "",
        f"Track-A classification: `{result['track_a']['classification']}`.",
        "",
        lifecycle.to_markdown(index=False, floatfmt=".4f"),
        "",
        "### Direct contrasts",
        "",
        contrasts.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Liquidity transition",
        "",
        liquidity.to_markdown(index=False, floatfmt=".4f"),
        "",
        "### Matched transition contrasts",
        "",
        liquidity_contrasts.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Advancement",
        "",
        f"Early proxy: `{result['track_a']['early_proxy_status']}`. Price-limit "
        f"replay: `{result['track_a']['replay_status']}`. Liquidity replay: "
        f"`{result['track_b']['replay_status']}`.",
        "",
        "No Track-A/Track-B signal combination was run. Cross-mechanism "
        "overlap is descriptive only.",
        "",
    ]
    return "\n".join(lines)


def run(*, verify_hashes: bool = True) -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, minute_paths, raw_paths = _paths()
    if verify_hashes:
        _verify_hashes(daily_paths, minute_paths, raw_paths)
    connection = _configure(daily_paths)
    lifecycle, lifecycle_audit = build_lifecycle_panel(connection, minute_paths, raw_paths)
    liquidity = build_liquidity_candidates(connection)
    a_pairs, b_pairs = build_pairs(lifecycle, liquidity)
    needed_uids = (
        set(lifecycle.uid)
        | set(liquidity.loc[liquidity.role.eq("event"), "uid"])
        | set(a_pairs.control_uid)
        | set(b_pairs.control_uid)
    )
    combined = pd.concat([lifecycle, liquidity], ignore_index=True, sort=False)
    candidates = combined.loc[combined.uid.isin(needed_uids)].copy()
    outcomes = attach_execution(connection, candidates)
    connection.close()
    lifecycle_outcomes = outcomes.loc[outcomes.track.eq("A")].copy()
    liquidity_outcomes = outcomes.loc[outcomes.track.eq("B")].copy()
    lifecycle_summary = summarize_groups(lifecycle_outcomes, "lifecycle")
    contrast_summary = summarize_pairs(a_pairs, outcomes)
    # Role-specific summaries are necessary because selected controls share a hypothesis.
    liquidity_summary = summarize_groups(
        liquidity_outcomes.assign(
            group_key=liquidity_outcomes.hypothesis + "|" + liquidity_outcomes.role
        ),
        "group_key",
    )
    liquidity_summary[["hypothesis", "role"]] = liquidity_summary.group_key.str.split(
        "|", expand=True
    )
    liquidity_summary = liquidity_summary.drop(columns="group_key")
    liquidity_contrasts = summarize_pairs(b_pairs, outcomes)
    track_a, track_b, gates = classify_results(
        lifecycle_summary, contrast_summary, liquidity_summary, liquidity_contrasts
    )
    early_authorized = track_a in {
        "PRICE_LIMIT_STRATEGY_CANDIDATE",
        "FAILED_ACCEPTANCE_DOWNSIDE_INFORMATION",
    }
    if early_authorized:
        proxy_precision = (
            float(
                lifecycle_outcomes.loc[lifecycle_outcomes.proxy_1400, "lifecycle"]
                .eq("EARLY_STABLE_ACCEPTANCE")
                .mean()
            )
            if lifecycle_outcomes.proxy_1400.any()
            else math.nan
        )
        proxy_recall = float(
            lifecycle_outcomes.loc[
                lifecycle_outcomes.lifecycle.eq("EARLY_STABLE_ACCEPTANCE"), "proxy_1400"
            ].mean()
        )
        proxy_pass = proxy_precision >= 0.80 and proxy_recall >= 0.50
    else:
        proxy_precision = math.nan
        proxy_recall = math.nan
        proxy_pass = False
    replay_authorized = track_a == "PRICE_LIMIT_STRATEGY_CANDIDATE"
    b_promotions = gates["track_b_promotions"]
    overlap = lifecycle[["trade_date", "symbol", "lifecycle"]].merge(
        liquidity.loc[liquidity.role.eq("event"), ["trade_date", "symbol", "hypothesis"]],
        on=["trade_date", "symbol"],
        how="inner",
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "claim_boundary": spec["claim_boundary"],
        "source_content_hashes_verified": verify_hashes,
        "track_a": {
            "classification": track_a,
            "event_audit": lifecycle_audit,
            "early_proxy_status": "PASSED"
            if proxy_pass
            else ("FAILED" if early_authorized else "NOT_AUTHORIZED"),
            "proxy_precision": proxy_precision,
            "proxy_recall": proxy_recall,
            "replay_status": "AUTHORIZED_NOT_RUN" if replay_authorized else "NOT_AUTHORIZED",
        },
        "track_b": {
            "classifications": track_b,
            "replay_status": "AUTHORIZED_NOT_RUN" if b_promotions else "NOT_AUTHORIZED",
        },
        "gates": gates,
        "protocol_audit": {"initial_early_proxy_diagnostic_quarantined_not_used": True},
        "cross_mechanism": {
            "overlap_rows": len(overlap),
            "overlap_fraction_of_lifecycle": len(overlap) / len(lifecycle),
        },
    }
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    lifecycle_outcomes.to_parquet(LIFECYCLE_PANEL_PATH, index=False, compression="zstd")
    liquidity_outcomes.to_parquet(LIQUIDITY_PANEL_PATH, index=False, compression="zstd")
    result["external_panels"] = {
        "lifecycle": {
            "path": str(LIFECYCLE_PANEL_PATH),
            "rows": len(lifecycle_outcomes),
            "bytes": LIFECYCLE_PANEL_PATH.stat().st_size,
            "sha256": sha256_file(LIFECYCLE_PANEL_PATH),
        },
        "liquidity": {
            "path": str(LIQUIDITY_PANEL_PATH),
            "rows": len(liquidity_outcomes),
            "bytes": LIQUIDITY_PANEL_PATH.stat().st_size,
            "sha256": sha256_file(LIQUIDITY_PANEL_PATH),
        },
    }
    for path, frame in (
        (LIFECYCLE_SUMMARY_PATH, lifecycle_summary),
        (CONTRAST_SUMMARY_PATH, contrast_summary),
        (LIQUIDITY_SUMMARY_PATH, liquidity_summary),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, float_format="%.10g")
    result["artifacts"] = {
        path.name: {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
        for path in (LIFECYCLE_SUMMARY_PATH, CONTRAST_SUMMARY_PATH, LIQUIDITY_SUMMARY_PATH)
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(
        REPORT_PATH,
        _report(
            result, lifecycle_summary, contrast_summary, liquidity_summary, liquidity_contrasts
        ),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-content-hashes", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        _load_spec()
        daily, minute, raw = _paths()
        _verify_hashes(daily, minute, raw)
        print("all frozen source content hashes verified")
        return
    print(
        json.dumps(
            _clean(run(verify_hashes=not args.skip_content_hashes)), indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
