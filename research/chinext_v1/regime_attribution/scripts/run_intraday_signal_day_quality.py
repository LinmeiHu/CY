#!/usr/bin/env python3
"""Run the frozen CHINEXT V1 entry-signal-session path-quality experiment."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import pearsonr, spearmanr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"

SPEC = WORK / "experiments/EXP-IBQ-001_spec.json"
TRADES = WORK / "artifacts/yearly_trades.csv"
MECHANISMS = WORK / "artifacts/trade_mechanism_attribution.csv"
CONTROLS = WORK / "artifacts/pre_entry_transitions.csv"
QD004_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "QD-004-2018-2026-20260820.json"
)
CY008_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-008-pit-b-minute-v2-2018-2026-20260821.json"
)
CY008_AUDIT = Path(
    "/Users/linmei/Documents/CY/data/audit/"
    "CY-008-minute-pit-b-cross-year-gate.json"
)

OUTPUT_TABLE = WORK / "artifacts/intraday_signal_day_quality.csv"
OUTPUT_JSON = WORK / "artifacts/intraday_signal_day_quality.json"
REPORT = WORK / "reports/intraday_signal_day_quality.md"
EVIDENCE_PACKET = WORK / "reports/intraday_signal_day_quality_evidence_packet.md"

FEATURE_COMPONENTS = (
    "path_efficiency_1m",
    "time_above_session_vwap",
    "opening_peak_retention",
)
CONTROL_COLUMNS = (
    "signal_day_log_return",
    "signal_day_log_range",
    "signal_day_close_location",
    "signal_day_log_amount",
    "entry_rs_score",
    "entry_mom20",
    "entry_box_width",
    "entry_minvol_location",
    "entry_breakout_volume_ratio",
    "index_return_20d",
    "index_realized_vol20",
    "breadth_composite",
    "entry_beta60",
    "entry_log_amount20",
)
EXPECTED_TIMES = (
    [pd.Timestamp("2000-01-01 09:30").time()]
    + list(pd.date_range("2000-01-01 09:31", "2000-01-01 11:30", freq="1min").time)
    + list(pd.date_range("2000-01-01 13:01", "2000-01-01 15:00", freq="1min").time)
)


class IntradayQualityError(RuntimeError):
    """Raised when an identity, PIT, path, or scientific invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def validate_spec_and_bound_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-IBQ-001":
        raise IntradayQualityError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_INTRADAY_OUTCOME_JOIN":
        raise IntradayQualityError("experiment is not frozen before outcome join")
    if spec.get("hypothesis_id") != "H-021":
        raise IntradayQualityError("unexpected hypothesis identity")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise IntradayQualityError(f"missing bound input: {role}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise IntradayQualityError(f"frozen input mismatch: {mismatches}")
    return spec, identities


def inventory_files(inventory_path: Path, required: list[str]) -> dict[str, Path]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    root = Path(inventory["root"])
    indexed = {item["path"]: item for item in inventory["files"]}
    missing = sorted(set(required) - set(indexed))
    if missing:
        raise IntradayQualityError(f"inventory entries missing: {missing}")
    paths: dict[str, Path] = {}
    mismatches: dict[str, dict[str, Any]] = {}
    for relative in required:
        path = root / relative
        item = indexed[relative]
        if not path.is_file():
            raise IntradayQualityError(f"inventoried file missing: {path}")
        actual_size = path.stat().st_size
        actual_hash = sha256_file(path)
        if actual_size != int(item["size"]) or actual_hash != item["sha256"]:
            mismatches[relative] = {
                "expected_size": int(item["size"]),
                "actual_size": actual_size,
                "expected_sha256": item["sha256"],
                "actual_sha256": actual_hash,
            }
        paths[relative] = path
    if mismatches:
        raise IntradayQualityError(f"inventory content mismatch: {mismatches}")
    return paths


def load_identity_frame() -> pd.DataFrame:
    frame = pd.read_csv(
        TRADES,
        usecols=[
            "trade_id",
            "baseline_block",
            "symbol",
            "entry_signal_date",
            "entry_execution_date",
        ],
        dtype={"symbol": str},
    )
    for column in ("entry_signal_date", "entry_execution_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise")
    if len(frame) != 399 or frame.trade_id.nunique() != 399:
        raise IntradayQualityError("identity frame is not 399 unique cycles")
    if not (frame.entry_signal_date < frame.entry_execution_date).all():
        raise IntradayQualityError("signal session is not before entry execution")
    if not frame.symbol.str.fullmatch(r"30[01]\d{3}\.SZ").all():
        raise IntradayQualityError("experiment population is not fixed ChiNext symbols")
    frame["entry_year"] = frame.entry_signal_date.dt.year
    return frame.sort_values("trade_id").reset_index(drop=True)


def read_filtered(
    path: Path,
    identities: pd.DataFrame,
    columns: list[str],
    *,
    suffixed_symbol: bool,
) -> pd.DataFrame:
    dates = sorted(identities.entry_signal_date.dt.date.unique())
    symbols = sorted(
        identities.symbol.unique()
        if suffixed_symbol
        else identities.symbol.str[:6].unique()
    )
    table = pq.read_table(
        path,
        columns=columns,
        filters=[("trade_date", "in", dates), ("symbol", "in", symbols)],
    )
    frame = table.to_pandas()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    keys = identities[["trade_id", "symbol", "entry_signal_date"]].copy()
    keys["source_symbol"] = (
        keys.symbol if suffixed_symbol else keys.symbol.str[:6]
    )
    keys = keys[["trade_id", "entry_signal_date", "source_symbol"]]
    return frame.merge(
        keys,
        left_on=["symbol", "trade_date"],
        right_on=["source_symbol", "entry_signal_date"],
        how="inner",
        validate="many_to_one",
    )


def continuous_rows(rows: pd.DataFrame) -> pd.DataFrame:
    ordered = rows.sort_values("bar_end_time").reset_index(drop=True)
    times = pd.to_datetime(ordered.bar_end_time).dt.time.tolist()
    if times != EXPECTED_TIMES:
        raise IntradayQualityError("signal session does not have the exact 241-bar grid")
    return ordered.iloc[1:].reset_index(drop=True)


def signed_efficiency(rows: pd.DataFrame) -> float:
    closes = rows.close.to_numpy(float)
    first_open = float(rows.open.iloc[0])
    if first_open <= 0 or (closes <= 0).any():
        raise IntradayQualityError("nonpositive price in path efficiency")
    increments = np.r_[math.log(closes[0] / first_open), np.diff(np.log(closes))]
    variation = float(np.abs(increments).sum())
    if variation <= 1e-15:
        return 0.0
    return float(math.log(closes[-1] / first_open) / variation)


def aggregate_5m(rows: pd.DataFrame) -> pd.DataFrame:
    if len(rows) != 240:
        raise IntradayQualityError("5-minute aggregation requires 240 continuous bars")
    working = rows.copy()
    working["window_index"] = np.arange(240) // 5
    grouped = working.groupby("window_index", sort=True)
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
        bar_end_time=("bar_end_time", "last"),
    ).reset_index()
    if len(result) != 48:
        raise IntradayQualityError("full session did not aggregate to 48 windows")
    return result


def compute_session_features(rows: pd.DataFrame) -> dict[str, float]:
    numeric = rows[["open", "high", "low", "close", "volume", "amount"]].to_numpy(float)
    if not np.isfinite(numeric).all():
        raise IntradayQualityError("nonfinite raw intraday value")
    if (
        (rows.open <= 0).any()
        or (rows.low <= 0).any()
        or (rows.high < rows[["open", "close"]].max(axis=1)).any()
        or (rows.low > rows[["open", "close"]].min(axis=1)).any()
        or (rows.volume < 0).any()
        or (rows.amount < 0).any()
    ):
        raise IntradayQualityError("invalid raw OHLCV row")
    continuous = continuous_rows(rows)
    five = aggregate_5m(continuous)
    session_volume = float(continuous.volume.sum())
    session_amount = float(continuous.amount.sum())
    if session_volume <= 0 or session_amount <= 0:
        raise IntradayQualityError("nonpositive continuous-session volume or amount")
    session_vwap = session_amount / session_volume
    first_30 = continuous.iloc[:30]
    opening_peak = float(first_30.high.max())
    close_1000 = float(first_30.close.iloc[-1])
    daily_high = float(rows.high.max())
    daily_low = float(rows.low.min())
    daily_open = float(rows.open.iloc[0])
    daily_close = float(rows.close.iloc[-1])
    daily_amount = float(rows.amount.sum())
    if daily_high < daily_low or daily_amount <= 0:
        raise IntradayQualityError("invalid daily range or amount")
    auction_efficiency = signed_efficiency(rows)
    return {
        "path_efficiency_1m": signed_efficiency(continuous),
        "path_efficiency_5m": signed_efficiency(five),
        "path_efficiency_auction_inclusive": auction_efficiency,
        "time_above_session_vwap": float(
            (continuous.close > session_vwap).mean()
            + 0.5 * np.isclose(continuous.close, session_vwap, rtol=1e-12, atol=1e-12).mean()
        ),
        "opening_peak_retention": float(math.log(close_1000 / opening_peak)),
        "signal_day_log_return": float(math.log(daily_close / daily_open)),
        "signal_day_log_range": float(math.log(daily_high / daily_low)),
        "signal_day_close_location": (
            0.5
            if daily_high == daily_low
            else float((daily_close - daily_low) / (daily_high - daily_low))
        ),
        "signal_day_log_amount": float(math.log(daily_amount)),
        "raw_minute_volume": float(rows.volume.sum()),
        "raw_minute_amount": daily_amount,
        "continuous_session_vwap": session_vwap,
        "flat_signal_session": bool(daily_high == daily_low),
    }


def compare_opening_windows(raw: pd.DataFrame, execution: pd.DataFrame) -> float:
    continuous = continuous_rows(raw)
    observed = aggregate_5m(continuous).iloc[:6].copy()
    expected = execution.sort_values("window_index").reset_index(drop=True)
    if expected.window_index.astype(int).tolist() != list(range(6)):
        raise IntradayQualityError("CY-008 opening windows are not exactly 0..5")
    maximum = 0.0
    for column in ("open", "high", "low", "close", "volume", "amount"):
        left = observed[column].to_numpy(float)
        right = expected[column].to_numpy(float)
        scale = np.maximum(1.0, np.maximum(np.abs(left), np.abs(right)))
        maximum = max(maximum, float(np.max(np.abs(left - right) / scale)))
    return maximum


def construct_feature_frame(
    identities: pd.DataFrame,
    qd004: dict[str, Path],
    cy008: dict[str, Path],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    records: list[dict[str, Any]] = []
    max_opening_difference = 0.0
    for year, yearly in identities.groupby("entry_year", sort=True):
        raw = read_filtered(
            qd004[f"bars/{year}_day_parquet_none.parquet"],
            yearly,
            [
                "symbol",
                "exchange",
                "period",
                "adjust",
                "trade_date",
                "bar_end_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "source",
            ],
            suffixed_symbol=False,
        )
        daily = read_filtered(
            cy008[f"daily/partition_year={year}/data_0.parquet"],
            yearly,
            [
                "symbol",
                "trade_date",
                "available_at",
                "minute_count",
                "distinct_minute_count",
                "minute_volume",
                "minute_amount",
                "source_resolution_minutes",
                "session_complete",
                "ohlc_valid",
                "unit_valid",
                "volume_reconciled",
                "amount_reconciled",
                "daily_hard_valid",
                "hard_valid",
                "invalid_reasons",
                "source",
                "snapshot_id",
                "daily_snapshot_id",
            ],
            suffixed_symbol=True,
        )
        execution = read_filtered(
            cy008[f"execution_5m/partition_year={year}/data_0.parquet"],
            yearly,
            [
                "symbol",
                "trade_date",
                "window_index",
                "available_at",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "hard_valid",
                "snapshot_id",
            ],
            suffixed_symbol=True,
        )
        for trade_id, identity_rows in raw.groupby("trade_id", sort=True):
            if len(identity_rows) != 241:
                raise IntradayQualityError(f"{trade_id} has {len(identity_rows)} raw bars")
            if identity_rows.bar_end_time.nunique() != 241:
                raise IntradayQualityError(f"{trade_id} has duplicate raw timestamps")
            if not (identity_rows.exchange.eq("SZ") & identity_rows.period.eq("1m") & identity_rows.adjust.eq("none")).all():
                raise IntradayQualityError(f"{trade_id} raw source semantics changed")
            daily_row = daily[daily.trade_id == trade_id]
            execution_rows = execution[execution.trade_id == trade_id]
            if len(daily_row) != 1 or len(execution_rows) != 6:
                raise IntradayQualityError(f"{trade_id} CY-008 coverage changed")
            item = daily_row.iloc[0]
            checks = (
                int(item.minute_count) == 241,
                int(item.distinct_minute_count) == 241,
                int(item.source_resolution_minutes) == 1,
                bool(item.session_complete),
                bool(item.ohlc_valid),
                bool(item.unit_valid),
                bool(item.volume_reconciled),
                bool(item.amount_reconciled),
                bool(item.daily_hard_valid),
                bool(item.hard_valid),
                execution_rows.hard_valid.astype(bool).all(),
            )
            if not all(checks):
                raise IntradayQualityError(f"{trade_id} CY-008 hard-valid gate failed")
            available_at = pd.Timestamp(item.available_at)
            signal_date = pd.Timestamp(identity_rows.entry_signal_date.iloc[0])
            execution_date = pd.Timestamp(
                identities.loc[identities.trade_id == trade_id, "entry_execution_date"].iloc[0]
            )
            if available_at != signal_date + pd.Timedelta(hours=15, minutes=30):
                raise IntradayQualityError(f"{trade_id} feature availability changed")
            if not (available_at < execution_date):
                raise IntradayQualityError(f"{trade_id} feature is not available before T+1")
            raw_volume = float(identity_rows.volume.sum())
            raw_amount = float(identity_rows.amount.sum())
            if not math.isclose(raw_volume, float(item.minute_volume), rel_tol=1e-12, abs_tol=1e-6):
                raise IntradayQualityError(f"{trade_id} raw/CY-008 volume mismatch")
            if not math.isclose(raw_amount, float(item.minute_amount), rel_tol=1e-12, abs_tol=1e-4):
                raise IntradayQualityError(f"{trade_id} raw/CY-008 amount mismatch")
            maximum = compare_opening_windows(identity_rows, execution_rows)
            max_opening_difference = max(max_opening_difference, maximum)
            if maximum > 1e-12:
                raise IntradayQualityError(f"{trade_id} raw/CY-008 opening-window mismatch")
            features = compute_session_features(identity_rows)
            records.append(
                {
                    "trade_id": trade_id,
                    "feature_available_at": available_at.isoformat(),
                    "potential_action_timestamp": execution_date.date().isoformat() + "T09:30:00+08:00",
                    "minute_snapshot_id": item.snapshot_id,
                    "daily_snapshot_id": item.daily_snapshot_id,
                    **features,
                }
            )
    features = identities.merge(pd.DataFrame(records), on="trade_id", validate="one_to_one")
    if len(features) != 399 or features[list(FEATURE_COMPONENTS)].isna().any().any():
        raise IntradayQualityError("constructed feature frame is incomplete")
    for component in FEATURE_COMPONENTS:
        features[f"{component}_rank"] = features.groupby("entry_year")[component].rank(
            method="average", pct=True
        )
    features["signal_day_path_acceptance"] = features[
        [f"{component}_rank" for component in FEATURE_COMPONENTS]
    ].mean(axis=1)
    features["signal_day_path_acceptance_5m"] = features.groupby("entry_year")[
        "path_efficiency_5m"
    ].rank(method="average", pct=True)
    features["signal_day_path_acceptance_5m"] = pd.concat(
        [
            features["signal_day_path_acceptance_5m"],
            features["time_above_session_vwap_rank"],
            features["opening_peak_retention_rank"],
        ],
        axis=1,
    ).mean(axis=1)
    features["signal_day_path_acceptance_auction"] = features.groupby("entry_year")[
        "path_efficiency_auction_inclusive"
    ].rank(method="average", pct=True)
    features["signal_day_path_acceptance_auction"] = pd.concat(
        [
            features["signal_day_path_acceptance_auction"],
            features["time_above_session_vwap_rank"],
            features["opening_peak_retention_rank"],
        ],
        axis=1,
    ).mean(axis=1)
    audit = {
        "identity_rows": len(identities),
        "feature_rows": len(features),
        "raw_bar_rows": 399 * 241,
        "continuous_bar_rows": 399 * 240,
        "cy008_daily_hard_valid": 399,
        "cy008_opening_windows_hard_valid": 399 * 6,
        "maximum_relative_opening_window_difference": max_opening_difference,
        "available_at_timestamp": "entry signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "T+1 open or later; never same-session",
        "flat_signal_sessions": int(features.flat_signal_session.sum()),
    }
    return features, audit


def rank_series(series: pd.Series) -> pd.Series:
    return series.rank(method="average")


def spearman(frame: pd.DataFrame, x: str, y: str) -> float:
    sample = frame[[x, y]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(sample) < 8 or sample[x].nunique() < 2 or sample[y].nunique() < 2:
        return float("nan")
    return float(spearmanr(sample[x], sample[y]).statistic)


def partial_rank(frame: pd.DataFrame, x: str, y: str, controls: tuple[str, ...]) -> float:
    columns = [x, y, *controls]
    sample = frame[columns].replace([np.inf, -np.inf], np.nan).dropna()
    if len(sample) < len(controls) + 10 or sample[x].nunique() < 2 or sample[y].nunique() < 2:
        return float("nan")
    ranked = sample.apply(rank_series)
    design = np.column_stack(
        [np.ones(len(ranked)), ranked[list(controls)].to_numpy(float)]
    )
    x_values = ranked[x].to_numpy(float)
    y_values = ranked[y].to_numpy(float)
    x_resid = x_values - design @ np.linalg.lstsq(design, x_values, rcond=None)[0]
    y_resid = y_values - design @ np.linalg.lstsq(design, y_values, rcond=None)[0]
    if np.std(x_resid) < 1e-10 or np.std(y_resid) < 1e-10:
        return float("nan")
    return float(pearsonr(x_resid, y_resid).statistic)


def add_year_dummies(frame: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
    dummies = pd.get_dummies(frame.entry_year.astype(int), prefix="year", drop_first=True, dtype=float)
    result = pd.concat([frame.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)
    return result, tuple(dummies.columns)


def loyo(
    frame: pd.DataFrame,
    x: str,
    y: str,
    controls: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    values: dict[str, float | None] = {}
    for year in sorted(frame.entry_year.dropna().astype(int).unique()):
        sample = frame[frame.entry_year != year].copy()
        if controls is None:
            estimate = spearman(sample, x, y)
        else:
            sample, year_columns = add_year_dummies(sample)
            estimate = partial_rank(sample, x, y, (*controls, *year_columns))
        values[str(year)] = None if not math.isfinite(estimate) else estimate
    finite = [value for value in values.values() if value is not None]
    return {
        "values": values,
        "positive": sum(value > 0 for value in finite),
        "total": len(finite),
    }


def leave_group_out(frame: pd.DataFrame, group: str, x: str, y: str) -> dict[str, Any]:
    estimates: list[float] = []
    for _, sample in frame.groupby(group, sort=True):
        remaining = frame.drop(sample.index)
        estimate = spearman(remaining, x, y)
        if math.isfinite(estimate):
            estimates.append(estimate)
    return {
        "groups": len(estimates),
        "positive_fraction": float(np.mean(np.asarray(estimates) > 0)) if estimates else None,
        "minimum": min(estimates) if estimates else None,
        "maximum": max(estimates) if estimates else None,
    }


def analyze(features: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    mechanisms = pd.read_csv(
        MECHANISMS,
        usecols=[
            "trade_id",
            "mfe",
            "round_trip_return",
            "realized_pnl",
            "opportunity20",
            "false_breakout",
            "severe_loss",
        ],
    )
    controls = pd.read_csv(
        CONTROLS,
        usecols=["trade_id", "entry_industry", *CONTROL_COLUMNS[4:]],
    )
    if len(mechanisms) != 399 or mechanisms.trade_id.nunique() != 399:
        raise IntradayQualityError("mechanism input is not 399 unique cycles")
    if len(controls) != 399 or controls.trade_id.nunique() != 399:
        raise IntradayQualityError("control input is not 399 unique cycles")
    frame = features.merge(mechanisms, on="trade_id", validate="one_to_one")
    frame = frame.merge(controls, on="trade_id", validate="one_to_one")
    for column in ("opportunity20", "false_breakout", "severe_loss"):
        frame[column] = frame[column].astype(bool)
    if int(frame.opportunity20.sum()) != 80 or int(frame.false_breakout.sum()) != 213:
        raise IntradayQualityError("fixed outcome counts changed")
    if (frame.opportunity20 & frame.false_breakout).any():
        raise IntradayQualityError("success and false-breakout endpoints overlap")
    frame["breakout_success"] = np.where(
        frame.opportunity20,
        1.0,
        np.where(frame.false_breakout, 0.0, np.nan),
    )
    frame["non_false_breakout"] = (~frame.false_breakout).astype(float)
    primary = frame[frame.breakout_success.notna()].copy()
    if len(primary) != 293:
        raise IntradayQualityError("fixed success-versus-false population changed")

    primary_year, year_columns = add_year_dummies(primary)
    fixed_controls = (*CONTROL_COLUMNS, *year_columns)
    raw = spearman(primary, "signal_day_path_acceptance", "breakout_success")
    controlled = partial_rank(
        primary_year,
        "signal_day_path_acceptance",
        "breakout_success",
        fixed_controls,
    )
    raw_loyo = loyo(primary, "signal_day_path_acceptance", "breakout_success")
    controlled_loyo = loyo(
        primary,
        "signal_day_path_acceptance",
        "breakout_success",
        CONTROL_COLUMNS,
    )
    within_year = spearman(
        primary.assign(
            x=primary.groupby("entry_year").signal_day_path_acceptance.rank(pct=True),
            y=primary.groupby("entry_year").breakout_success.rank(pct=True),
        ),
        "x",
        "y",
    )
    blocks = {
        block: spearman(sample, "signal_day_path_acceptance", "breakout_success")
        for block, sample in primary.groupby("baseline_block", sort=True)
    }
    components = {
        component: {
            "rho": spearman(primary, component, "breakout_success"),
            "loyo": loyo(primary, component, "breakout_success"),
        }
        for component in FEATURE_COMPONENTS
    }
    neighbors = {
        name: {
            "rho": spearman(primary, name, "breakout_success"),
            "loyo": loyo(primary, name, "breakout_success"),
        }
        for name in (
            "signal_day_path_acceptance_5m",
            "signal_day_path_acceptance_auction",
        )
    }
    secondary = {
        endpoint: {
            "rho": spearman(frame, "signal_day_path_acceptance", endpoint),
            "loyo": loyo(frame, "signal_day_path_acceptance", endpoint),
        }
        for endpoint in (
            "opportunity20",
            "non_false_breakout",
            "mfe",
            "round_trip_return",
        )
    }
    top4 = set(frame.assign(abs_pnl=frame.realized_pnl.abs()).nlargest(4, "abs_pnl").trade_id)
    attacks = {
        "ex_top4_absolute_pnl": spearman(
            primary[~primary.trade_id.isin(top4)],
            "signal_day_path_acceptance",
            "breakout_success",
        ),
        "ex_extreme_winners": spearman(
            primary[primary.round_trip_return < 0.50],
            "signal_day_path_acceptance",
            "breakout_success",
        ),
        "ex_severe_losses": spearman(
            primary[~primary.severe_loss],
            "signal_day_path_acceptance",
            "breakout_success",
        ),
        "security_leave_one_out": leave_group_out(
            primary, "symbol", "signal_day_path_acceptance", "breakout_success"
        ),
        "industry_leave_one_out": leave_group_out(
            primary, "entry_industry", "signal_day_path_acceptance", "breakout_success"
        ),
    }
    gates_spec = spec["decision_gates"]
    raw_gate = raw >= gates_spec["raw_minimum_rho"] and raw_loyo["positive"] >= gates_spec["raw_minimum_positive_loyo"]
    controlled_gate = (
        controlled >= gates_spec["controlled_minimum_rho"]
        and controlled_loyo["positive"] >= gates_spec["controlled_minimum_positive_loyo"]
    )
    temporal_gate = (
        sum(value > 0 for value in blocks.values()) >= gates_spec["minimum_positive_blocks"]
        and min(blocks.values()) > gates_spec["minimum_block_rho_exclusive"]
    )
    outcome_gate = all(
        secondary[name]["rho"] >= gates_spec["secondary_minimum_rho"]
        and secondary[name]["loyo"]["positive"] >= gates_spec["secondary_minimum_positive_loyo"]
        for name in ("opportunity20", "non_false_breakout")
    )
    neighbor_gate = all(
        item["rho"] >= gates_spec["neighbor_minimum_rho"]
        and item["loyo"]["positive"] >= gates_spec["neighbor_minimum_positive_loyo"]
        for item in neighbors.values()
    )
    tail_gate = all(
        attacks[name] > gates_spec["tail_minimum_rho_exclusive"]
        for name in ("ex_top4_absolute_pnl", "ex_extreme_winners", "ex_severe_losses")
    )
    concentration_gate = all(
        attacks[name]["positive_fraction"] >= gates_spec["minimum_leave_group_positive_fraction"]
        and attacks[name]["minimum"] > 0
        for name in ("security_leave_one_out", "industry_leave_one_out")
    )
    falsification_gate = neighbor_gate and tail_gate and concentration_gate
    gates = {
        "raw": raw_gate,
        "controlled_daily_incrementality": controlled_gate,
        "temporal": temporal_gate,
        "outcome_neighbors": outcome_gate,
        "falsification": falsification_gate,
    }
    if all(gates.values()):
        decision = "VALIDATE"
        verdict = "SIGNAL_DAY_PATH_ACCEPTANCE_SURVIVES_EXPLORATORY_FALSIFICATION"
    elif raw_gate and controlled_gate:
        decision = "SUPPORTED_WEAK"
        verdict = "SIGNAL_DAY_PATH_ACCEPTANCE_IS_PRESENT_BUT_NOT_FULLY_ROBUST"
    else:
        decision = "REJECTED"
        verdict = "SIGNAL_DAY_PATH_ACCEPTANCE_FAILS_RAW_OR_DAILY_INCREMENTAL_GATES"

    ordered_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "feature_available_at",
        "potential_action_timestamp",
        "minute_snapshot_id",
        "daily_snapshot_id",
        *FEATURE_COMPONENTS,
        "path_efficiency_5m",
        "path_efficiency_auction_inclusive",
        "signal_day_path_acceptance",
        "signal_day_path_acceptance_5m",
        "signal_day_path_acceptance_auction",
        *CONTROL_COLUMNS[:4],
        "continuous_session_vwap",
        "flat_signal_session",
        "opportunity20",
        "false_breakout",
        "breakout_success",
        "non_false_breakout",
        "mfe",
        "round_trip_return",
        "realized_pnl",
        "severe_loss",
        "entry_year",
        "entry_industry",
        *CONTROL_COLUMNS[4:],
    ]
    result = {
        "experiment_id": "EXP-IBQ-001",
        "hypothesis_id": "H-021",
        "evidence_grade": "EXPLORATORY_MECHANISM_EVIDENCE_ON_OUTCOME_CONSUMED_HISTORY",
        "population": {
            "all_completed_cycles": len(frame),
            "success_opportunity20": int(frame.opportunity20.sum()),
            "false_breakout": int(frame.false_breakout.sum()),
            "primary_disjoint_population": len(primary),
        },
        "primary": {
            "raw_rho": raw,
            "within_year_rho": within_year,
            "raw_loyo": raw_loyo,
            "controlled_rho": controlled,
            "controlled_loyo": controlled_loyo,
            "blocks": blocks,
        },
        "components": components,
        "neighbors": neighbors,
        "secondary": secondary,
        "attacks": attacks,
        "gates": gates,
        "decision": decision,
        "verdict": verdict,
        "interpretation_boundary": (
            "Features are complete entry-signal-session observations available at 15:30 "
            "for T+1 or later. They cannot justify an earlier same-session action and do "
            "not identify the original lifecycle breakout timestamp."
        ),
    }
    return frame[ordered_columns].sort_values("trade_id").reset_index(drop=True), result


def render_report(result: dict[str, Any], audit: dict[str, Any]) -> str:
    primary = result["primary"]
    lines = [
        "# Intraday entry-signal-session path quality",
        "",
        "EXP-IBQ-001 tests one preregistered path-acceptance composite on the completed",
        "entry-signal session. It does not identify the earlier lifecycle breakout date,",
        "does not test a rule, and cannot be used before its 15:30 availability timestamp.",
        "",
        "## Integrity and PIT",
        "",
        f"- Completed cycles / raw bars: `{audit['identity_rows']}` / `{audit['raw_bar_rows']}`.",
        f"- Hard-valid CY-008 daily rows / opening windows: `{audit['cy008_daily_hard_valid']}` / `{audit['cy008_opening_windows_hard_valid']}`.",
        f"- Maximum raw-versus-CY-008 opening-window relative difference: `{audit['maximum_relative_opening_window_difference']:.3g}`.",
        f"- Available at: `{audit['available_at_timestamp']}`.",
        f"- Potential action: `{audit['potential_action_timestamp']}`.",
        "",
        "## Primary evidence",
        "",
        "| Metric | Estimate |",
        "|---|---:|",
        f"| Raw success-vs-false rho | {primary['raw_rho']:.3f} |",
        f"| Within-year rho | {primary['within_year_rho']:.3f} |",
        f"| Raw LOYO positive | {primary['raw_loyo']['positive']}/{primary['raw_loyo']['total']} |",
        f"| Daily/incrementality-controlled rho | {primary['controlled_rho']:.3f} |",
        f"| Controlled LOYO positive | {primary['controlled_loyo']['positive']}/{primary['controlled_loyo']['total']} |",
        "",
        "## Decision",
        "",
        f"`{result['decision']}` — `{result['verdict']}`.",
        "",
        result["interpretation_boundary"],
    ]
    return "\n".join(lines) + "\n"


def render_evidence_packet(result: dict[str, Any], audit: dict[str, Any]) -> str:
    lines = [
        "# EXP-IBQ-001 structured evidence packet",
        "",
        "## Question and mechanism",
        "",
        "Does persistent demand/acceptance during the completed V1 entry-signal session",
        "distinguish fixed MFE>=20% opportunities from the existing false-breakout class?",
        "",
        "## Fixed measurement",
        "",
        "The sole primary predictor is the equal-weight within-year rank composite of",
        "signed one-minute path efficiency, time above full-session VWAP, and first-30-minute",
        "peak retention. Daily OHLC/amount, V1 entry state, market/breadth, beta, liquidity,",
        "and year are fixed controls. No component, threshold, horizon, or interaction is",
        "selected from results.",
        "",
        "## PIT and execution boundary",
        "",
        f"- Raw rows: {audit['raw_bar_rows']}; exact 241-bar sessions: {audit['identity_rows']}.",
        "- The 09:30 auction bar is excluded from the primary continuous-session path and",
        "  retained only in a frozen neighboring definition.",
        "- Full-session features are available at 15:30 on the entry-signal date.",
        "- Earliest potential action is T+1 open; same-session or already-completed open",
        "  interpretation is forbidden.",
        "- Full-depth order book, tick orders, queue, cancellations, and participant identity",
        "  are unavailable and are not inferred.",
        "",
        "## Results",
        "",
        f"- Decision: `{result['decision']}`.",
        f"- Verdict: `{result['verdict']}`.",
        f"- Gates: `{json.dumps(result['gates'], sort_keys=True)}`.",
        f"- Raw/controlled rho: `{result['primary']['raw_rho']:.6f}` / `{result['primary']['controlled_rho']:.6f}`.",
        f"- Raw/controlled LOYO: `{result['primary']['raw_loyo']['positive']}/8` / `{result['primary']['controlled_loyo']['positive']}/8`.",
        "",
        "## Interpretation boundary",
        "",
        result["interpretation_boundary"],
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    spec, bound_identities = validate_spec_and_bound_inputs()
    years = list(range(2018, 2026))
    qd004_required = [f"bars/{year}_day_parquet_none.parquet" for year in years]
    cy008_required = [
        path
        for year in years
        for path in (
            f"daily/partition_year={year}/data_0.parquet",
            f"execution_5m/partition_year={year}/data_0.parquet",
        )
    ]
    qd004 = inventory_files(QD004_INVENTORY, qd004_required)
    cy008 = inventory_files(CY008_INVENTORY, cy008_required)
    cross_audit = json.loads(CY008_AUDIT.read_text(encoding="utf-8"))
    if cross_audit.get("pass") is not True or not all(cross_audit.get("checks", {}).values()):
        raise IntradayQualityError("CY-008 cross-year audit is not PASS")
    identities = load_identity_frame()
    features, audit = construct_feature_frame(identities, qd004, cy008)
    table, result = analyze(features, spec)
    result["audit"] = audit
    result["input_identities"] = bound_identities

    OUTPUT_TABLE.parent.mkdir(parents=True, exist_ok=True)
    temporary_table = OUTPUT_TABLE.with_suffix(".tmp.csv")
    table.to_csv(temporary_table, index=False, float_format="%.12g")
    temporary_table.replace(OUTPUT_TABLE)
    atomic_write(
        OUTPUT_JSON,
        json.dumps(clean_json(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(REPORT, render_report(result, audit))
    atomic_write(EVIDENCE_PACKET, render_evidence_packet(result, audit))
    print(json.dumps(clean_json(result), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
