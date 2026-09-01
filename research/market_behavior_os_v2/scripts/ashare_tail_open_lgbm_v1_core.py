"""Pure causal feature, execution, split, and model helpers for Tail-to-Open V1."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

EXPECTED_MINUTES = np.array(
    [
        9 * 60 + 30,
        *range(9 * 60 + 31, 11 * 60 + 31),
        *range(13 * 60 + 1, 15 * 60 + 1),
    ],
    dtype=np.int16,
)
CUTOFF_MINUTE = 14 * 60 + 25
ENTRY_BAR_MINUTE = 14 * 60 + 56
CUTOFF_POSITION = int(np.flatnonzero(EXPECTED_MINUTES == CUTOFF_MINUTE)[0])
ENTRY_POSITION = int(np.flatnonzero(EXPECTED_MINUTES == ENTRY_BAR_MINUTE)[0])

RAW_DIRECT_FEATURES = (
    "ret_open_to_1425",
    "ret_prevclose_to_1425",
    "ret_0931_1000",
    "ret_1000_1130",
    "ret_1301_1400",
    "ret_1400_1425",
    "ret_1301_1425",
    "cutoff_vs_high",
    "cutoff_vs_low",
    "range_to_1425",
    "close_location_1425",
    "max_drawdown_1425",
    "max_recovery_1425",
    "realized_vol_1425",
    "downside_semivol_1425",
    "upside_semivol_1425",
    "path_efficiency_1425",
    "positive_minute_fraction_1425",
    "sign_flip_rate_1425",
    "max_1m_return_1425",
    "min_1m_return_1425",
    "cutoff_vs_vwap_1425",
    "fraction_above_vwap_1425",
    "vwap_crossing_rate_1425",
    "morning_close_vs_vwap",
    "afternoon_close_vs_vwap_1425",
    "log_amount_1425",
    "afternoon_amount_fraction_1425",
    "activity_acceleration_1425",
    "amount_concentration_1425",
    "price_impact_abs_1425",
)


class TailOpenError(RuntimeError):
    """Fail-closed Tail-to-Open contract error."""


def _minute_number(values: Iterable[Any]) -> np.ndarray:
    parsed = pd.to_datetime(values, errors="raise")
    return (parsed.hour * 60 + parsed.minute).to_numpy(dtype=np.int16)


def _numeric(table: pa.Table, name: str) -> np.ndarray:
    values = table[name].combine_chunks().to_numpy(zero_copy_only=False)
    return np.asarray(values, dtype=np.float64)


def _group_layout(table: pa.Table) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    symbols = table["symbol"].combine_chunks()
    exchanges = table["exchange"].combine_chunks()
    trade_dates = table["trade_date"].combine_chunks()
    rows = table.num_rows
    same_key = np.asarray(
        pc.and_(
            pc.and_(
                pc.equal(symbols.slice(1), symbols.slice(0, rows - 1)),
                pc.equal(exchanges.slice(1), exchanges.slice(0, rows - 1)),
            ),
            pc.equal(trade_dates.slice(1), trade_dates.slice(0, rows - 1)),
        ).to_numpy(zero_copy_only=False),
        dtype=bool,
    )
    starts = np.r_[0, np.flatnonzero(~same_key) + 1].astype(np.int64)
    counts = np.diff(np.r_[starts, rows]).astype(np.int32)
    group_symbols = np.asarray(symbols.take(pa.array(starts)).to_pylist(), dtype=str)
    group_exchanges = np.asarray(exchanges.take(pa.array(starts)).to_pylist(), dtype=str)
    suffix = np.where(group_exchanges == "SH", ".SH", ".SZ")
    keys = pd.DataFrame(
        {
            "symbol": np.char.add(group_symbols, suffix),
            "trade_date": pd.to_datetime(trade_dates.take(pa.array(starts)).to_pylist()),
        }
    )
    if keys.duplicated(["symbol", "trade_date"]).any():
        raise TailOpenError("raw session keys are duplicated or noncontiguous")
    return starts, counts, keys


def extract_raw_day(table: pa.Table) -> tuple[pd.DataFrame, dict[str, int]]:
    """Compute stock-session primitives while keeping features at or before 14:25."""

    required = {
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
    }
    missing = sorted(required - set(table.column_names))
    if missing:
        raise TailOpenError(f"raw columns missing: {missing}")
    if table.num_rows < 2:
        raise TailOpenError("raw day is empty")
    if set(pc.unique(table["period"]).to_pylist()) != {"1m"}:
        raise TailOpenError("non-1m data entered raw extractor")
    if set(pc.unique(table["adjust"]).to_pylist()) != {"none"}:
        raise TailOpenError("adjusted data entered raw extractor")
    if any(table[name].null_count for name in required):
        raise TailOpenError("required raw null entered extractor")

    starts, counts, keys = _group_layout(table)
    positions = np.arange(table.num_rows, dtype=np.int32) - np.repeat(starts, counts)
    minutes = _minute_number(table["bar_end_time"].combine_chunks().to_pylist())
    expected = EXPECTED_MINUTES[np.minimum(positions, len(EXPECTED_MINUTES) - 1)]
    row_clock_ok = (positions < len(EXPECTED_MINUTES)) & (minutes == expected)
    clock_ok = np.logical_and.reduceat(row_clock_ok, starts)
    full_grid = (counts == len(EXPECTED_MINUTES)) & clock_ok

    numeric_names = ("open", "high", "low", "close", "volume", "amount")
    numeric = {name: _numeric(table, name) for name in numeric_names}
    finite = np.ones(table.num_rows, dtype=bool)
    for values in numeric.values():
        finite &= np.isfinite(values)
    finite &= (
        (numeric["open"] > 0)
        & (numeric["high"] > 0)
        & (numeric["low"] > 0)
        & (numeric["close"] > 0)
        & (numeric["volume"] >= 0)
        & (numeric["amount"] >= 0)
        & (numeric["high"] >= np.maximum(numeric["open"], numeric["close"]))
        & (numeric["low"] <= np.minimum(numeric["open"], numeric["close"]))
    )
    numeric_ok = np.logical_and.reduceat(finite, starts)
    valid = full_grid & numeric_ok
    if not valid.any():
        raise TailOpenError("no exact valid raw session on date")
    selected_rows = np.repeat(valid, counts)
    valid_count = int(valid.sum())
    arrays = {
        name: values[selected_rows].reshape(valid_count, len(EXPECTED_MINUTES))
        for name, values in numeric.items()
    }
    keys = keys.loc[valid].reset_index(drop=True)

    continuous_open = arrays["open"][:, 1 : CUTOFF_POSITION + 1]
    high = arrays["high"][:, 1 : CUTOFF_POSITION + 1]
    low = arrays["low"][:, 1 : CUTOFF_POSITION + 1]
    close = arrays["close"][:, 1 : CUTOFF_POSITION + 1]
    volume = arrays["volume"][:, 1 : CUTOFF_POSITION + 1]
    amount = arrays["amount"][:, 1 : CUTOFF_POSITION + 1]
    open_price = continuous_open[:, 0]
    cutoff_close = close[:, -1]
    previous = np.concatenate([open_price[:, None], close[:, :-1]], axis=1)

    with np.errstate(divide="ignore", invalid="ignore"):
        minute_return = np.log(close / previous)
        range_high = high.max(axis=1)
        range_low = low.min(axis=1)
        total_volume = volume.sum(axis=1)
        total_amount = amount.sum(axis=1)
        session_vwap = total_amount / total_volume
        cumulative_volume = np.cumsum(volume, axis=1)
        causal_vwap = np.divide(
            np.cumsum(amount, axis=1),
            cumulative_volume,
            out=np.full_like(amount, np.nan),
            where=cumulative_volume > 0,
        )
        relation = close - causal_vwap
        relation_sign = np.sign(relation)
        relation_valid = np.isfinite(relation[:, 1:]) & np.isfinite(relation[:, :-1])
        crossing = relation_valid & (relation_sign[:, 1:] * relation_sign[:, :-1] < 0)
        crossing_denominator = relation_valid.sum(axis=1)
        running_high = np.maximum.accumulate(high, axis=1)
        running_low = np.minimum.accumulate(low, axis=1)
        path_length = np.abs(minute_return).sum(axis=1)
        signs = np.sign(minute_return)
        sign_comparison = (signs[:, 1:] != 0) & (signs[:, :-1] != 0)
        sign_flips = sign_comparison & (signs[:, 1:] != signs[:, :-1])
        morning_amount = amount[:, :120].sum(axis=1)
        morning_volume = volume[:, :120].sum(axis=1)
        afternoon_amount = amount[:, 120:].sum(axis=1)
        afternoon_volume = volume[:, 120:].sum(axis=1)
        early_afternoon_amount = amount[:, 120:180].mean(axis=1)
        late_afternoon_amount = amount[:, 180:].mean(axis=1)
        amount_weights = amount / total_amount[:, None]

        values: dict[str, np.ndarray] = {
            "ret_open_to_1425": np.log(cutoff_close / open_price),
            "ret_prevclose_to_1425": np.full(valid_count, np.nan),
            "ret_0931_1000": np.log(close[:, 29] / open_price),
            "ret_1000_1130": np.log(close[:, 119] / close[:, 29]),
            "ret_1301_1400": np.log(close[:, 179] / continuous_open[:, 120]),
            "ret_1400_1425": np.log(cutoff_close / close[:, 179]),
            "ret_1301_1425": np.log(cutoff_close / continuous_open[:, 120]),
            "cutoff_vs_high": np.log(cutoff_close / range_high),
            "cutoff_vs_low": np.log(cutoff_close / range_low),
            "range_to_1425": np.log(range_high / range_low),
            "close_location_1425": np.divide(
                cutoff_close - range_low,
                range_high - range_low,
                out=np.full(valid_count, 0.5),
                where=range_high > range_low,
            ),
            "max_drawdown_1425": np.log(low / running_high).min(axis=1),
            "max_recovery_1425": np.log(high / running_low).max(axis=1),
            "realized_vol_1425": np.sqrt(np.square(minute_return).sum(axis=1)),
            "downside_semivol_1425": np.sqrt(np.square(np.minimum(minute_return, 0)).sum(axis=1)),
            "upside_semivol_1425": np.sqrt(np.square(np.maximum(minute_return, 0)).sum(axis=1)),
            "path_efficiency_1425": np.divide(
                np.abs(np.log(cutoff_close / open_price)),
                path_length,
                out=np.zeros(valid_count),
                where=path_length > 0,
            ),
            "positive_minute_fraction_1425": (minute_return > 0).mean(axis=1),
            "sign_flip_rate_1425": np.divide(
                sign_flips.sum(axis=1),
                sign_comparison.sum(axis=1),
                out=np.zeros(valid_count),
                where=sign_comparison.sum(axis=1) > 0,
            ),
            "max_1m_return_1425": minute_return.max(axis=1),
            "min_1m_return_1425": minute_return.min(axis=1),
            "cutoff_vs_vwap_1425": np.log(cutoff_close / session_vwap),
            "fraction_above_vwap_1425": np.nanmean(close > causal_vwap, axis=1),
            "vwap_crossing_rate_1425": np.divide(
                crossing.sum(axis=1),
                crossing_denominator,
                out=np.zeros(valid_count),
                where=crossing_denominator > 0,
            ),
            "morning_close_vs_vwap": np.log(close[:, 119] / (morning_amount / morning_volume)),
            "afternoon_close_vs_vwap_1425": np.log(
                cutoff_close / (afternoon_amount / afternoon_volume)
            ),
            "log_amount_1425": np.log(total_amount),
            "afternoon_amount_fraction_1425": afternoon_amount / total_amount,
            "activity_acceleration_1425": np.divide(
                late_afternoon_amount,
                early_afternoon_amount,
                out=np.full(valid_count, np.nan),
                where=early_afternoon_amount > 0,
            )
            - 1,
            "amount_concentration_1425": np.square(amount_weights).sum(axis=1),
            "price_impact_abs_1425": np.abs(minute_return).sum(axis=1) / (total_amount / 1e8),
        }

    result = keys.copy()
    result["raw_open"] = open_price
    result["cutoff_close"] = cutoff_close
    result["amount_1425"] = total_amount
    for name in RAW_DIRECT_FEATURES:
        result[name] = values[name]
    entry_volume = arrays["volume"][:, ENTRY_POSITION]
    entry_amount = arrays["amount"][:, ENTRY_POSITION]
    result["entry_open"] = arrays["open"][:, ENTRY_POSITION]
    result["entry_high"] = arrays["high"][:, ENTRY_POSITION]
    result["entry_low"] = arrays["low"][:, ENTRY_POSITION]
    result["entry_close"] = arrays["close"][:, ENTRY_POSITION]
    result["entry_volume"] = entry_volume
    result["entry_amount"] = entry_amount
    result["entry_vwap"] = np.divide(
        entry_amount,
        entry_volume,
        out=np.full(valid_count, np.nan),
        where=entry_volume > 0,
    )
    result["post_entry_tail_low"] = arrays["low"][:, ENTRY_POSITION + 1 :].min(axis=1)
    return result, {
        "raw_rows": int(table.num_rows),
        "raw_sessions": int(len(keys) + (~valid).sum()),
        "valid_sessions": valid_count,
        "invalid_grid_sessions": int((~full_grid).sum()),
        "invalid_numeric_sessions": int((~numeric_ok).sum()),
    }


def complete_prevclose_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    previous = pd.to_numeric(result["previous_close"], errors="coerce").to_numpy(float)
    raw_open = pd.to_numeric(result["raw_open"], errors="coerce").to_numpy(float)
    cutoff = pd.to_numeric(result["cutoff_close"], errors="coerce").to_numpy(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        result["open_gap"] = np.log(raw_open / previous)
        result["ret_prevclose_to_1425"] = np.log(cutoff / previous)
    return result


def causal_industry(source_notice_date: Any, trade_date: Any, industry: Any) -> bool:
    if pd.isna(source_notice_date) or pd.isna(trade_date) or not str(industry):
        return False
    return pd.Timestamp(source_notice_date).date() < pd.Timestamp(trade_date).date()


def entry_executable(entry_vwap: float, entry_low: float, upper_limit: float) -> bool:
    values = np.asarray([entry_vwap, entry_low, upper_limit], dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        return False
    entry_low_tick = int(np.rint(entry_low * 100))
    upper_tick = int(np.rint(upper_limit * 100))
    return entry_low_tick <= upper_tick - 1


def legal_open(row: dict[str, Any]) -> bool:
    required = ("hard_valid", "trade_status", "current_day_data_tradable", "sell_blocked_open")
    if any(name not in row for name in required):
        return False
    open_price = float(row.get("open", np.nan))
    return bool(
        row["hard_valid"]
        and int(row["trade_status"]) == 1
        and row["current_day_data_tradable"]
        and not row["sell_blocked_open"]
        and np.isfinite(open_price)
        and open_price > 0
        and not row.get("corporate_action_blocking", False)
    )


def first_legal_exit(rows: list[dict[str, Any]], entry_date: date) -> dict[str, Any] | None:
    for row in rows:
        row_date = pd.Timestamp(row["trade_date"]).date()
        if row_date <= entry_date:
            continue
        if legal_open(row):
            return row
    return None


def net_tail_open_return(
    entry_vwap: float,
    exit_open: float,
    cost: float = 0.002,
    action_cash_per_entry_share: float = 0.0,
) -> float:
    if entry_vwap <= 0 or exit_open <= 0 or action_cash_per_entry_share < 0:
        raise TailOpenError("nonpositive execution price")
    proceeds = exit_open * (1 - cost) + action_cash_per_entry_share
    return proceeds / (entry_vwap * (1 + cost)) - 1


def corporate_action_path_valid(rows: Iterable[dict[str, Any]]) -> bool:
    for row in rows:
        if row.get("corporate_action_blocking", False):
            return False
        if float(row.get("rights_ratio", 0.0) or 0.0) != 0.0:
            return False
        count = int(row.get("corporate_action_count", 0) or 0)
        if count and (
            not np.isfinite(float(row.get("share_multiplier", np.nan)))
            or float(row.get("share_multiplier", 0.0)) <= 0
            or not np.isfinite(float(row.get("cash_per_share", np.nan)))
        ):
            return False
    return True


@dataclass(frozen=True)
class Fold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    predict_start: pd.Timestamp
    predict_end: pd.Timestamp


def frozen_development_folds() -> tuple[Fold, ...]:
    return (
        Fold(
            pd.Timestamp("2014-01-01"),
            pd.Timestamp("2017-12-31"),
            pd.Timestamp("2018-01-01"),
            pd.Timestamp("2018-12-31"),
        ),
        Fold(
            pd.Timestamp("2014-01-01"),
            pd.Timestamp("2018-12-31"),
            pd.Timestamp("2019-01-01"),
            pd.Timestamp("2019-12-31"),
        ),
        Fold(
            pd.Timestamp("2014-01-01"),
            pd.Timestamp("2019-12-31"),
            pd.Timestamp("2020-01-02"),
            pd.Timestamp("2020-12-31"),
        ),
        Fold(
            pd.Timestamp("2014-01-01"),
            pd.Timestamp("2020-12-31"),
            pd.Timestamp("2021-01-04"),
            pd.Timestamp("2021-12-31"),
        ),
    )


def purged_training_mask(
    signal_dates: pd.Series,
    exit_dates: pd.Series,
    fold: Fold,
) -> np.ndarray:
    signal = pd.to_datetime(signal_dates)
    exits = pd.to_datetime(exit_dates)
    eligible = (
        signal.ge(fold.train_start)
        & signal.le(fold.train_end)
        & exits.notna()
        & exits.lt(fold.predict_start)
    )
    final_signal = signal.loc[eligible].max()
    if pd.notna(final_signal):
        eligible &= signal.ne(final_signal)
    return eligible.to_numpy(dtype=bool)


def ridge_pipeline(alpha: float = 10.0) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("ridge", Ridge(alpha=alpha, fit_intercept=True)),
        ]
    )


def lightgbm_model(
    profile: dict[str, Any], seed: int, n_estimators: int = 2000
) -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(
        objective="regression_l1",
        learning_rate=0.03,
        n_estimators=n_estimators,
        feature_fraction=0.8,
        bagging_fraction=0.8,
        bagging_freq=1,
        deterministic=True,
        force_col_wise=True,
        n_jobs=4,
        verbosity=-1,
        random_state=seed,
        bagging_seed=seed,
        feature_fraction_seed=seed,
        data_random_seed=seed,
        **{key: value for key, value in profile.items() if key != "name"},
    )
