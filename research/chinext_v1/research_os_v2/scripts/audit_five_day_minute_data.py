#!/usr/bin/env python3
"""Audit five pre-signal minute sessions without reading trade outcomes."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/research_os_v2"
SPEC = WORK / "experiments/AUDIT-ROSV2-M001_spec.json"
IDENTITIES = ROOT / "research/chinext_v1/regime_attribution/artifacts/yearly_trades.csv"
REGISTRY = ROOT / "configs/data_asset_registry.json"
CALENDAR = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet")
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
PRIOR_AUDIT = (
    ROOT
    / "research/chinext_v1/regime_attribution/reports/"
    "intraday_breakout_quality_data_audit_20260830.md"
)

SESSION_AUDIT = WORK / "artifacts/AUDIT-ROSV2-M001_session_audit.csv"
DESCRIPTORS = WORK / "artifacts/AUDIT-ROSV2-M001_daily_descriptors.csv"
RESULT = WORK / "artifacts/AUDIT-ROSV2-M001_result.json"
REPORT = WORK / "reports/AUDIT-ROSV2-M001_five_day_minute_data.md"

IDENTITY_COLUMNS = (
    "trade_id",
    "baseline_block",
    "symbol",
    "entry_signal_date",
    "entry_execution_date",
)
FORBIDDEN_COLUMNS = {
    "round_trip_return",
    "realized_pnl",
    "mfe",
    "mae",
    "false_breakout",
    "winner20",
    "extreme_winner",
    "severe_loss",
    "exit_signal_date",
    "exit_execution_date",
    "canonical_exit_reason",
    "holding_trading_days",
}
EXPECTED_TIMES = (
    [pd.Timestamp("2000-01-01 09:30").time()]
    + list(pd.date_range("2000-01-01 09:31", "2000-01-01 11:30", freq="1min").time)
    + list(pd.date_range("2000-01-01 13:01", "2000-01-01 15:00", freq="1min").time)
)
DESCRIPTOR_COLUMNS = (
    "open_close_log_return",
    "morning_log_return",
    "afternoon_log_return",
    "final30_log_return",
    "high_time_fraction",
    "low_time_fraction",
    "close_location",
    "signed_directional_efficiency",
    "path_r2",
    "close_vs_vwap_log",
    "time_above_vwap_fraction",
    "volume_above_vwap_fraction",
    "vwap_halfday_log_slope",
    "vwap_recovery_count",
    "longest_below_vwap_fraction",
    "late_vwap_acceptance_fraction",
    "downside_excursion",
    "downside_realized_volatility",
    "down_minute_volume_share",
    "selloff_duration_fraction",
    "recovery_speed_30bar",
    "upside_excursion",
    "up_minute_volume_share",
    "positive_minute_fraction",
    "new_intraday_high_fraction",
    "intraday_log_range",
    "minute_realized_volatility",
    "vwap_deviation_std",
    "vwap_crossing_fraction",
    "opening30_volume_share",
    "afternoon_volume_share",
    "closing30_volume_share",
    "minute_volume_concentration",
    "auction_to_continuous_open_log_return",
)


class FiveDayMinuteAuditError(RuntimeError):
    """Raised when any identity, PIT, session, or outcome-blind gate fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, float_format="%.12g", lineterminator="\n")
    os.replace(temporary, path)


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
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "AUDIT-ROSV2-M001":
        raise FiveDayMinuteAuditError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIVE_DAY_MINUTE_ACCESS":
        raise FiveDayMinuteAuditError("audit is not frozen before minute access")
    if spec.get("outcome_access") is not False:
        raise FiveDayMinuteAuditError("outcome access prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise FiveDayMinuteAuditError(f"missing bound input: {role}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise FiveDayMinuteAuditError(f"frozen input mismatch: {mismatches}")
    return spec, identities


def inventory_files(inventory_path: Path, required: list[str]) -> dict[str, Path]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    root = Path(inventory["root"])
    indexed = {item["path"]: item for item in inventory["files"]}
    missing = sorted(set(required) - set(indexed))
    if missing:
        raise FiveDayMinuteAuditError(f"inventory entries missing: {missing}")
    paths: dict[str, Path] = {}
    mismatches: dict[str, dict[str, Any]] = {}
    for relative in required:
        item = indexed[relative]
        path = root / relative
        if not path.is_file():
            raise FiveDayMinuteAuditError(f"inventoried file missing: {path}")
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != int(item["size"]) or digest != item["sha256"]:
            mismatches[relative] = {
                "expected_size": int(item["size"]),
                "actual_size": size,
                "expected_sha256": item["sha256"],
                "actual_sha256": digest,
            }
        paths[relative] = path
    if mismatches:
        raise FiveDayMinuteAuditError(f"inventory content mismatch: {mismatches}")
    return paths


def inventoried_hashes(inventory_path: Path, required: list[str]) -> dict[str, str]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    root = Path(inventory["root"])
    indexed = {item["path"]: item for item in inventory["files"]}
    return {str(root / relative): indexed[relative]["sha256"] for relative in required}


def load_event_sessions() -> tuple[pd.DataFrame, pd.DataFrame]:
    events = pd.read_csv(
        IDENTITIES,
        usecols=list(IDENTITY_COLUMNS),
        dtype={"symbol": str},
    )
    if FORBIDDEN_COLUMNS.intersection(events.columns):
        raise FiveDayMinuteAuditError("outcome column entered identity frame")
    for column in ("entry_signal_date", "entry_execution_date"):
        events[column] = pd.to_datetime(events[column], errors="raise")
    if len(events) != 399 or events.trade_id.nunique() != 399:
        raise FiveDayMinuteAuditError("identity population is not 399 unique cycles")
    if events.duplicated(["baseline_block", "symbol", "entry_signal_date"]).any():
        raise FiveDayMinuteAuditError("duplicate canonical signal key")
    if not (events.entry_signal_date < events.entry_execution_date).all():
        raise FiveDayMinuteAuditError("signal is not strictly before execution")
    if not events.symbol.str.fullmatch(r"30[01]\d{3}\.SZ").all():
        raise FiveDayMinuteAuditError("identity population is not canonical ChiNext")

    calendar = pq.read_table(CALENDAR, columns=["trade_date"]).to_pandas()
    calendar["trade_date"] = pd.to_datetime(calendar.trade_date, errors="raise")
    calendar = calendar.drop_duplicates().sort_values("trade_date").reset_index(drop=True)
    index_by_date = {date: index for index, date in enumerate(calendar.trade_date)}
    rows: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        signal = pd.Timestamp(event.entry_signal_date)
        if signal not in index_by_date:
            raise FiveDayMinuteAuditError(f"signal date missing from calendar: {signal}")
        signal_index = index_by_date[signal]
        if signal_index < 5:
            raise FiveDayMinuteAuditError("insufficient pre-signal calendar history")
        for relative_day in range(-5, 0):
            trade_date = calendar.trade_date.iloc[signal_index + relative_day]
            rows.append(
                {
                    "trade_id": event.trade_id,
                    "baseline_block": event.baseline_block,
                    "symbol": event.symbol,
                    "source_symbol": str(event.symbol)[:6],
                    "entry_signal_date": signal,
                    "relative_day": relative_day,
                    "trade_date": trade_date,
                    "target_year": int(trade_date.year),
                }
            )
    targets = pd.DataFrame(rows)
    if len(targets) != 399 * 5:
        raise FiveDayMinuteAuditError("five-day target population changed")
    if targets.duplicated(["trade_id", "relative_day"]).any():
        raise FiveDayMinuteAuditError("duplicate event-relative-day key")
    if not (targets.trade_date < targets.entry_signal_date).all():
        raise FiveDayMinuteAuditError("pre-signal target is not before signal")
    return events.sort_values("trade_id").reset_index(drop=True), targets


def read_filtered(
    path: Path,
    targets: pd.DataFrame,
    columns: list[str],
    *,
    suffixed_symbol: bool,
) -> pd.DataFrame:
    dates = sorted(targets.trade_date.dt.date.unique())
    symbols = sorted(
        targets.symbol.unique() if suffixed_symbol else targets.source_symbol.unique()
    )
    table = pq.read_table(
        path,
        columns=columns,
        filters=[("trade_date", "in", dates), ("symbol", "in", symbols)],
    )
    frame = table.to_pandas()
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    key_column = "symbol" if suffixed_symbol else "source_symbol"
    keys = targets[
        ["trade_id", "relative_day", "trade_date", "symbol", "source_symbol"]
    ].copy()
    source = frame.rename(columns={"symbol": key_column})
    return source.merge(
        keys,
        on=[key_column, "trade_date"],
        how="inner",
        validate="many_to_many",
    )


def longest_true_run(values: np.ndarray) -> int:
    best = current = 0
    for value in values.astype(bool):
        current = current + 1 if value else 0
        best = max(best, current)
    return best


def aggregate_5m(rows: pd.DataFrame) -> pd.DataFrame:
    if len(rows) != 240:
        raise FiveDayMinuteAuditError("five-minute aggregation requires 240 rows")
    working = rows.copy()
    # Morning and afternoon are each exactly divisible by five; this sequential
    # index never creates a bar across the lunch break.
    working["window_index"] = np.arange(240) // 5
    result = (
        working.groupby("window_index", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
            bar_end_time=("bar_end_time", "last"),
        )
        .reset_index()
    )
    if len(result) != 48:
        raise FiveDayMinuteAuditError("full session did not aggregate to 48 windows")
    return result


def _safe_log_ratio(numerator: float, denominator: float) -> float:
    if not (math.isfinite(numerator) and math.isfinite(denominator)):
        raise FiveDayMinuteAuditError("nonfinite log-ratio input")
    if numerator <= 0 or denominator <= 0:
        raise FiveDayMinuteAuditError("nonpositive log-ratio input")
    return math.log(numerator / denominator)


def session_descriptors(rows: pd.DataFrame) -> dict[str, float]:
    ordered = rows.sort_values("bar_end_time").reset_index(drop=True)
    auction = ordered.iloc[0]
    continuous = ordered.iloc[1:].reset_index(drop=True)
    numeric = continuous[["open", "high", "low", "close", "volume", "amount"]].to_numpy(float)
    if not np.isfinite(numeric).all():
        raise FiveDayMinuteAuditError("nonfinite raw minute value")
    if (numeric[:, :4] <= 0).any() or (numeric[:, 4:] < 0).any():
        raise FiveDayMinuteAuditError("invalid minute price/volume/amount")
    if (
        (continuous.high < continuous[["open", "close"]].max(axis=1)).any()
        or (continuous.low > continuous[["open", "close"]].min(axis=1)).any()
        or (continuous.high < continuous.low).any()
    ):
        raise FiveDayMinuteAuditError("invalid minute OHLC ordering")

    open_price = float(continuous.open.iloc[0])
    close = continuous.close.to_numpy(float)
    high = continuous.high.to_numpy(float)
    low = continuous.low.to_numpy(float)
    volume = continuous.volume.to_numpy(float)
    amount = continuous.amount.to_numpy(float)
    total_volume = float(volume.sum())
    total_amount = float(amount.sum())
    if total_volume <= 0 or total_amount <= 0:
        raise FiveDayMinuteAuditError("nonpositive session volume or amount")
    session_vwap = total_amount / total_volume
    if not math.isfinite(session_vwap) or session_vwap <= 0:
        raise FiveDayMinuteAuditError("invalid session VWAP")

    minute_start = np.r_[open_price, close[:-1]]
    minute_log_returns = np.log(close / minute_start)
    close_log_path = np.r_[math.log(open_price), np.log(close)]
    path_length = float(np.abs(np.diff(close_log_path)).sum())
    signed_efficiency = (
        float(close_log_path[-1] - close_log_path[0]) / path_length
        if path_length > 0
        else 0.0
    )
    time_index = np.arange(len(close), dtype=float)
    if np.std(np.log(close)) > 0:
        path_r = float(np.corrcoef(time_index, np.log(close))[0, 1])
        path_r2 = path_r * path_r
    else:
        path_r2 = 0.0
    above_vwap = close > session_vwap
    below_vwap = close < session_vwap
    positive = minute_log_returns > 0
    negative = minute_log_returns < 0
    crossings = np.count_nonzero(above_vwap[1:] != above_vwap[:-1])
    recoveries = np.count_nonzero(above_vwap[1:] & ~above_vwap[:-1])
    volume_weights = volume / total_volume
    first_half_vwap = float(amount[:120].sum() / volume[:120].sum())
    second_half_vwap = float(amount[120:].sum() / volume[120:].sum())
    low_index = int(np.argmin(low))
    bars_remaining = max(1, len(close) - low_index - 1)
    new_highs = high > np.maximum.accumulate(np.r_[-np.inf, high[:-1]])
    range_low = float(low.min())
    range_high = float(high.max())
    close_location = (
        (float(close[-1]) - range_low) / (range_high - range_low)
        if range_high > range_low
        else 0.5
    )

    return {
        "open_close_log_return": _safe_log_ratio(float(close[-1]), open_price),
        "morning_log_return": _safe_log_ratio(float(close[119]), open_price),
        "afternoon_log_return": _safe_log_ratio(float(close[-1]), float(continuous.open.iloc[120])),
        "final30_log_return": _safe_log_ratio(float(close[-1]), float(continuous.open.iloc[210])),
        "high_time_fraction": float((int(np.argmax(high)) + 1) / 240),
        "low_time_fraction": float((low_index + 1) / 240),
        "close_location": float(close_location),
        "signed_directional_efficiency": signed_efficiency,
        "path_r2": path_r2,
        "close_vs_vwap_log": _safe_log_ratio(float(close[-1]), session_vwap),
        "time_above_vwap_fraction": float(above_vwap.mean()),
        "volume_above_vwap_fraction": float(volume[above_vwap].sum() / total_volume),
        "vwap_halfday_log_slope": _safe_log_ratio(second_half_vwap, first_half_vwap),
        "vwap_recovery_count": float(recoveries),
        "longest_below_vwap_fraction": float(longest_true_run(below_vwap) / 240),
        "late_vwap_acceptance_fraction": float(above_vwap[-30:].mean()),
        "downside_excursion": max(0.0, -_safe_log_ratio(range_low, open_price)),
        "downside_realized_volatility": float(np.sqrt(np.mean(np.minimum(minute_log_returns, 0.0) ** 2))),
        "down_minute_volume_share": float(volume[negative].sum() / total_volume),
        "selloff_duration_fraction": float(longest_true_run(negative) / 240),
        "recovery_speed_30bar": float(_safe_log_ratio(float(close[-1]), range_low) * 30 / bars_remaining),
        "upside_excursion": max(0.0, _safe_log_ratio(range_high, open_price)),
        "up_minute_volume_share": float(volume[positive].sum() / total_volume),
        "positive_minute_fraction": float(positive.mean()),
        "new_intraday_high_fraction": float(new_highs.mean()),
        "intraday_log_range": _safe_log_ratio(range_high, range_low),
        "minute_realized_volatility": float(np.std(minute_log_returns, ddof=1)),
        "vwap_deviation_std": float(np.std(np.log(close / session_vwap), ddof=1)),
        "vwap_crossing_fraction": float(crossings / 239),
        "opening30_volume_share": float(volume[:30].sum() / total_volume),
        "afternoon_volume_share": float(volume[120:].sum() / total_volume),
        "closing30_volume_share": float(volume[-30:].sum() / total_volume),
        "minute_volume_concentration": float(np.square(volume_weights).sum()),
        "auction_to_continuous_open_log_return": _safe_log_ratio(open_price, float(auction.close)),
    }


def validate_and_describe(
    targets: pd.DataFrame,
    qd004: dict[str, Path],
    cy008: dict[str, Path],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    audit_records: list[dict[str, Any]] = []
    descriptor_records: list[dict[str, Any]] = []
    max_opening_difference = 0.0
    max_conservation_difference = 0.0

    for year, yearly_targets in targets.groupby("target_year", sort=True):
        raw = read_filtered(
            qd004[f"bars/{year}_day_parquet_none.parquet"],
            yearly_targets,
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
            yearly_targets,
            [
                "symbol",
                "trade_date",
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
                "invalid_reasons",
                "snapshot_id",
                "daily_snapshot_id",
            ],
            suffixed_symbol=True,
        )
        execution = read_filtered(
            cy008[f"execution_5m/partition_year={year}/data_0.parquet"],
            yearly_targets,
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
                "circulating_shares",
                "trade_status",
                "up_limit_price",
                "down_limit_price",
                "market_rule_valid",
                "causal_inputs_valid",
                "source_resolution_minutes",
                "minute_count",
                "distinct_minute_count",
                "hard_valid",
                "snapshot_id",
            ],
            suffixed_symbol=True,
        )

        for target in yearly_targets.itertuples(index=False):
            key = (raw.trade_id == target.trade_id) & (raw.relative_day == target.relative_day)
            rows = raw.loc[key].sort_values("bar_end_time").reset_index(drop=True)
            gate = daily.loc[
                (daily.trade_id == target.trade_id)
                & (daily.relative_day == target.relative_day)
            ]
            windows = execution.loc[
                (execution.trade_id == target.trade_id)
                & (execution.relative_day == target.relative_day)
            ].sort_values("window_index")
            if len(rows) != 241 or rows.bar_end_time.nunique() != 241:
                raise FiveDayMinuteAuditError(
                    f"raw minute coverage changed: {target.trade_id}:{target.relative_day}"
                )
            times = pd.to_datetime(rows.bar_end_time).dt.time.tolist()
            if times != EXPECTED_TIMES:
                raise FiveDayMinuteAuditError(
                    f"session grid changed: {target.trade_id}:{target.relative_day}"
                )
            if not (
                rows.exchange.eq("SZ") & rows.period.eq("1m") & rows.adjust.eq("none")
            ).all():
                raise FiveDayMinuteAuditError(
                    f"raw minute semantics changed: {target.trade_id}:{target.relative_day}"
                )
            if len(gate) != 1 or len(windows) != 6:
                raise FiveDayMinuteAuditError(
                    f"CY-008 coverage changed: {target.trade_id}:{target.relative_day}"
                )
            item = gate.iloc[0]
            expected_available = pd.Timestamp(target.trade_date) + pd.Timedelta(
                hours=15, minutes=30
            )
            if pd.Timestamp(item.available_at) != expected_available:
                raise FiveDayMinuteAuditError(
                    f"daily availability changed: {target.trade_id}:{target.relative_day}"
                )
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
                windows.window_index.astype(int).tolist() == list(range(6)),
                windows.hard_valid.astype(bool).all(),
                windows.market_rule_valid.astype(bool).all(),
                windows.causal_inputs_valid.astype(bool).all(),
                windows.source_resolution_minutes.astype(int).eq(1).all(),
                windows.minute_count.astype(int).eq(5).all(),
                windows.distinct_minute_count.astype(int).eq(5).all(),
            )
            if not all(checks):
                raise FiveDayMinuteAuditError(
                    f"hard-valid gate failed: {target.trade_id}:{target.relative_day}"
                )
            continuous = rows.iloc[1:].reset_index(drop=True)
            five = aggregate_5m(continuous)
            for column in ("open", "high", "low", "close", "volume", "amount"):
                difference = float(
                    np.max(
                        np.abs(
                            five.loc[:5, column].to_numpy(float)
                            - windows[column].to_numpy(float)
                        )
                    )
                )
                scale = max(1.0, float(np.max(np.abs(windows[column].to_numpy(float)))))
                max_opening_difference = max(max_opening_difference, difference / scale)
            volume_difference = abs(float(five.volume.sum()) - float(continuous.volume.sum()))
            amount_difference = abs(float(five.amount.sum()) - float(continuous.amount.sum()))
            max_conservation_difference = max(
                max_conservation_difference,
                volume_difference,
                amount_difference,
            )
            if max_opening_difference > 1e-12:
                raise FiveDayMinuteAuditError(
                    f"opening-window mismatch: {target.trade_id}:{target.relative_day}"
                )
            if volume_difference != 0.0 or amount_difference != 0.0:
                raise FiveDayMinuteAuditError(
                    f"five-minute conservation failure: {target.trade_id}:{target.relative_day}"
                )

            descriptors = session_descriptors(rows)
            prices = continuous[["open", "high", "low", "close"]].to_numpy(float)
            flat = bool(np.max(prices) == np.min(prices))
            context = windows.iloc[0]
            tolerance_up = max(0.001, abs(float(context.up_limit_price)) * 1e-6)
            tolerance_down = max(0.001, abs(float(context.down_limit_price)) * 1e-6)
            locked_up = flat and abs(float(continuous.close.iloc[-1]) - float(context.up_limit_price)) <= tolerance_up
            locked_down = flat and abs(float(continuous.close.iloc[-1]) - float(context.down_limit_price)) <= tolerance_down
            audit_records.append(
                {
                    "trade_id": target.trade_id,
                    "baseline_block": target.baseline_block,
                    "symbol": target.symbol,
                    "entry_signal_date": pd.Timestamp(target.entry_signal_date).date().isoformat(),
                    "relative_day": int(target.relative_day),
                    "trade_date": pd.Timestamp(target.trade_date).date().isoformat(),
                    "raw_rows": len(rows),
                    "distinct_bar_end_times": rows.bar_end_time.nunique(),
                    "continuous_rows": len(continuous),
                    "derived_5m_windows": len(five),
                    "cy008_opening_windows": len(windows),
                    "hard_valid": True,
                    "flat_session": flat,
                    "limit_locked_up": bool(locked_up),
                    "limit_locked_down": bool(locked_down),
                    "trade_status": int(context.trade_status),
                    "available_at": expected_available.isoformat(),
                    "first_potential_action": "later than completed descriptor; full five-day path usable at Day-1 15:30 or later",
                    "minute_snapshot_id": item.snapshot_id,
                    "daily_snapshot_id": item.daily_snapshot_id,
                }
            )
            descriptor_records.append(
                {
                    "trade_id": target.trade_id,
                    "baseline_block": target.baseline_block,
                    "symbol": target.symbol,
                    "entry_signal_date": pd.Timestamp(target.entry_signal_date).date().isoformat(),
                    "relative_day": int(target.relative_day),
                    "trade_date": pd.Timestamp(target.trade_date).date().isoformat(),
                    "feature_available_at": expected_available.isoformat(),
                    **descriptors,
                }
            )

    audit = pd.DataFrame(audit_records).sort_values(["trade_id", "relative_day"])
    descriptors = pd.DataFrame(descriptor_records).sort_values(["trade_id", "relative_day"])
    if len(audit) != 1995 or audit[["trade_id", "relative_day"]].duplicated().any():
        raise FiveDayMinuteAuditError("session audit is not 1,995 unique keys")
    if len(descriptors) != 1995 or descriptors[list(DESCRIPTOR_COLUMNS)].isna().any().any():
        raise FiveDayMinuteAuditError("descriptor coverage is incomplete")
    if not np.isfinite(descriptors[list(DESCRIPTOR_COLUMNS)].to_numpy(float)).all():
        raise FiveDayMinuteAuditError("descriptor artifact contains nonfinite value")
    event_day_counts = descriptors.groupby("trade_id").relative_day.nunique()
    if not event_day_counts.eq(5).all():
        raise FiveDayMinuteAuditError("an event lacks five descriptor sessions")
    trajectory_available_at = (
        pd.to_datetime(descriptors[descriptors.relative_day == -1].trade_date)
        + pd.Timedelta(hours=15, minutes=30)
    )
    signal_dates = pd.to_datetime(
        descriptors[descriptors.relative_day == -1].entry_signal_date
    )
    if not (trajectory_available_at < signal_dates).all():
        raise FiveDayMinuteAuditError("five-day trajectory is not available before signal")
    return audit, descriptors, {
        "maximum_relative_opening_window_difference": max_opening_difference,
        "maximum_five_minute_conservation_difference": max_conservation_difference,
    }


def descriptor_diagnostics(descriptors: pd.DataFrame) -> dict[str, Any]:
    values = descriptors[list(DESCRIPTOR_COLUMNS)]
    summary: dict[str, Any] = {}
    for column in DESCRIPTOR_COLUMNS:
        series = values[column]
        summary[column] = {
            "minimum": float(series.min()),
            "p05": float(series.quantile(0.05)),
            "median": float(series.median()),
            "p95": float(series.quantile(0.95)),
            "maximum": float(series.max()),
            "unique": int(series.nunique()),
        }
    correlations = values.corr(method="spearman")
    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(DESCRIPTOR_COLUMNS):
        for right in DESCRIPTOR_COLUMNS[left_index + 1 :]:
            rho = float(correlations.loc[left, right])
            pairs.append({"left": left, "right": right, "rho": rho, "abs_rho": abs(rho)})
    pairs.sort(key=lambda item: (-item["abs_rho"], item["left"], item["right"]))
    return {
        "descriptors": summary,
        "top_absolute_spearman_pairs": pairs[:25],
        "descriptor_count": len(DESCRIPTOR_COLUMNS),
    }


def build_report(result: dict[str, Any]) -> str:
    counts = result["coverage"]
    return "\n".join(
        [
            "# AUDIT-ROSV2-M001 — five-day minute data audit",
            "",
            f"Decision: `{result['decision']}`.",
            "",
            "## Outcome-blind population",
            "",
            f"- canonical events: `{counts['events']}`;",
            f"- Day -5..Day -1 event-sessions: `{counts['event_sessions']}`;",
            f"- distinct symbol/date source sessions: `{counts['distinct_source_sessions']}`;",
            f"- raw rows after event mapping: `{counts['raw_rows']}`;",
            f"- descriptor rows and fields: `{counts['descriptor_rows']}` x `{counts['descriptor_count']}`;",
            "- outcome, return, P&L, MFE, MAE, exit, and holding fields read: `0`.",
            "",
            "## Contract result",
            "",
            "Every event has the exact five preceding exchange sessions. Every session has a separate 09:30 auction row plus 240 continuous rows at 09:31..11:30 and 13:01..15:00. All QD-004 files use raw/unadjusted 1m SZ semantics. CY-008 daily and opening-window rows pass the frozen hard-valid, session, unit, trading-rule, causal-input, volume, amount, and timestamp gates.",
            "",
            f"Maximum relative QD-004 versus CY-008 opening-window difference: `{result['reconciliation']['maximum_relative_opening_window_difference']:.3g}`.",
            f"Maximum derived-5m volume/amount conservation difference: `{result['reconciliation']['maximum_five_minute_conservation_difference']:.3g}`.",
            "",
            "## Corporate actions and execution",
            "",
            "Prices remain raw/unadjusted and all preview descriptors are same-session dimensionless quantities. No raw price is compared across sessions. Cross-day price-level/support features remain deferred to an accepted action-safe daily coordinate. The complete Day -5..Day -1 trajectory is known after Day -1 at 15:30, strictly before the signal session; it can never justify an earlier or same-bar fill.",
            "",
            "## Representation feasibility",
            "",
            "The audit materializes interpretable daily descriptor previews for price path, VWAP, selling/buying pressure, volatility, and volume concentration. These are outcome-blind feasibility evidence, not frozen predictors. The recorded rank-correlation pairs must be used to compress redundant representations before any outcome reveal.",
            "",
            "## Limitations",
            "",
            "OHLCV bars do not reveal aggressor side, queue state, cancellations, hidden liquidity, absorption, or participant identity. Support/resistance progression that compares price levels across days requires a separate action-safe level contract. All history remains bounded PIT-B and outcome-consumed for later association.",
            "",
            "## Next decision",
            "",
            "If PASS, rank one minimal outcome-blind five-day representation freeze against the three-coordinate trend build. Do not combine or outcome-screen the 34 preview descriptors.",
            "",
        ]
    )


def main() -> None:
    spec, input_hashes = validate_spec_and_inputs()
    events, targets = load_event_sessions()
    years = sorted(targets.target_year.unique().tolist())
    if years != list(range(2018, 2026)):
        raise FiveDayMinuteAuditError(f"unexpected target years: {years}")
    qd004_required = [f"bars/{year}_day_parquet_none.parquet" for year in years]
    cy008_required = [
        relative
        for year in years
        for relative in (
            f"daily/partition_year={year}/data_0.parquet",
            f"execution_5m/partition_year={year}/data_0.parquet",
        )
    ]
    qd004 = inventory_files(QD004_INVENTORY, qd004_required)
    cy008 = inventory_files(CY008_INVENTORY, cy008_required)
    audit, descriptors, reconciliation = validate_and_describe(targets, qd004, cy008)
    diagnostics = descriptor_diagnostics(descriptors)
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "experiment_id": "AUDIT-ROSV2-M001",
        "hypothesis_id": "H-ROSV2-M001",
        "decision": "PASS_FIVE_DAY_MINUTE_DATA_AND_DESCRIPTOR_FEASIBILITY",
        "outcome_access": False,
        "coverage": {
            "events": len(events),
            "event_sessions": len(audit),
            "distinct_source_sessions": int(audit[["symbol", "trade_date"]].drop_duplicates().shape[0]),
            "raw_rows": int(audit.raw_rows.sum()),
            "continuous_rows": int(audit.continuous_rows.sum()),
            "derived_5m_windows": int(audit.derived_5m_windows.sum()),
            "cy008_opening_windows": int(audit.cy008_opening_windows.sum()),
            "descriptor_rows": len(descriptors),
            "descriptor_count": len(DESCRIPTOR_COLUMNS),
            "flat_sessions": int(audit.flat_session.sum()),
            "limit_locked_up_sessions": int(audit.limit_locked_up.sum()),
            "limit_locked_down_sessions": int(audit.limit_locked_down.sum()),
            "relative_days": sorted(audit.relative_day.unique().astype(int).tolist()),
            "years": years,
            "by_year": {
                str(year): int((pd.to_datetime(audit.trade_date).dt.year == year).sum())
                for year in years
            },
        },
        "timestamp_contract": {
            "bar_timestamp": "completed bar end in Asia/Shanghai",
            "session_grid": "09:30 auction; 09:31..11:30 and 13:01..15:00 continuous",
            "daily_available_at": "trade_date 15:30 Asia/Shanghai",
            "five_day_trajectory_available_at": "Day -1 15:30 Asia/Shanghai",
            "signal_relation": "strictly before entry signal session",
            "same_bar_fill_allowed": False,
        },
        "price_coordinate": {
            "minute_adjustment": "none/raw",
            "same_session_dimensionless_descriptors_only": True,
            "cross_session_raw_price_comparison": False,
            "cross_day_level_features": "DEFERRED_PENDING_ACTION_SAFE_DAILY_COORDINATE",
            "future_adjustment_allowed": False,
        },
        "reconciliation": reconciliation,
        "descriptor_diagnostics": diagnostics,
        "input_hashes": input_hashes,
        "inventory_files": {
            **inventoried_hashes(QD004_INVENTORY, qd004_required),
            **inventoried_hashes(CY008_INVENTORY, cy008_required),
        },
        "spec_sha256": sha256_file(SPEC),
        "runner_sha256": sha256_file(Path(__file__)),
        "outputs": {
            "session_audit": str(SESSION_AUDIT.relative_to(ROOT)),
            "daily_descriptors": str(DESCRIPTORS.relative_to(ROOT)),
            "result": str(RESULT.relative_to(ROOT)),
            "report": str(REPORT.relative_to(ROOT)),
        },
        "limitations": [
            "bounded PIT-B rather than strict archival PIT-A",
            "accepted-entry-conditioned population",
            "preview descriptors are outcome-blind feasibility artifacts, not selected predictors",
            "raw OHLCV cannot identify aggressor side, queues, cancellations, hidden liquidity, or participants",
            "cross-day price-level features require a separate action-safe coordinate",
        ],
    }
    atomic_csv(SESSION_AUDIT, audit)
    atomic_csv(DESCRIPTORS, descriptors)
    atomic_write(RESULT, json.dumps(clean_json(result), ensure_ascii=False, indent=2) + "\n")
    atomic_write(REPORT, build_report(result))


if __name__ == "__main__":
    main()
