"""Standalone OGR V13 -> V27 -> V28 -> V28R1 -> V28R2 signal chain.

The functions are minimal extracts of the five hash-audited frozen producers.
They consume only caller-supplied PIT daily, minute and CY-033 amount/state data.
"""

from __future__ import annotations

import math
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from ..errors import ReproductionError
from ..io import _sql_path, read_parquet, write_parquet


ORIGINAL_PRODUCER_SHA256 = {
    "V13": "a156657128053cdeda68e53d5f433de34976353bcc79f25cfab9410bb779dc26",
    "V27": "86dd15e8a49da1f6481d3552f02ffbbcdb874eaf6b8b0754220d36b4dee9face",
    "V28": "865aa4e0058b69168002ac3ce61014d41fbf502a9541565ecdeec3f075147cce",
    "V28R1": "b74bdc04a7b898cbac7bb042601b33d7ae52643af6cff758e22b314ea24a7dc8",
    "V28R2": "540863fde51f23efc1fc413385868d58ac0a48575b9ebc0cf9eab64acbca30af",
}


def _raw_path(root: Path, year: int) -> Path:
    path = root / f"{year}_day_parquet_none.parquet"
    if not path.is_file():
        raise ReproductionError(f"DATA_INPUT_MISSING raw_minute year={year}: {path}")
    return path


def _cy033_path(root: Path, year: int) -> Path:
    path = root / f"daily/partition_year={year}/data_0.parquet"
    if not path.is_file():
        raise ReproductionError(f"DATA_INPUT_MISSING cy033 year={year}: {path}")
    return path


def _valid_daily_rows(frame: pd.DataFrame) -> np.ndarray:
    return (
        frame.hard_valid.fillna(False)
        & frame.history_valid.fillna(False)
        & frame.current_valid.fillna(False)
        & frame.corporate_action_valid.fillna(False)
        & ~frame.corporate_action_blocking.fillna(True)
    ).to_numpy(bool)


def _price_ticks(value: pd.Series | np.ndarray | float) -> np.ndarray:
    return np.floor(np.asarray(value, dtype=float) * 100.0 + 0.5 + 1e-6).astype(np.int64)


def _boundary_ticks(boundary: float, factor: pd.Series | np.ndarray | float) -> np.ndarray:
    return _price_ticks(float(boundary) / np.asarray(factor, dtype=float))


def _raw_tick_reached(high: pd.Series | np.ndarray, boundary: float, factor: pd.Series | np.ndarray) -> np.ndarray:
    return _price_ticks(high) >= _boundary_ticks(boundary, factor)


def load_daily(path: Path, end: str = "2021-12-31") -> pd.DataFrame:
    frame = read_parquet(
        path,
        f"SELECT * FROM source WHERE trade_date BETWEEN DATE '2013-01-01' "
        f"AND DATE '{end}' ORDER BY symbol,trade_date",
    )
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["symbol_seq"] = frame.groupby("symbol", sort=False).cumcount()
    if frame.empty or frame.trade_date.max() > pd.Timestamp(end):
        raise ReproductionError("OGR daily chronology failure")
    return frame


def build_all_true_gaps(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    grouped = frame.groupby("symbol", sort=False)
    previous = (
        "trade_date", "cal_idx", "low", "close", "invalid_step_cum", "hard_valid",
        "history_valid", "current_valid", "corporate_action_valid", "corporate_action_blocking",
    )
    for column in previous:
        frame[f"previous_{column}"] = grouped[column].shift(1)
    mask = (
        frame.trade_date.ge(pd.Timestamp("2014-01-01"))
        & frame.hard_valid.fillna(False)
        & frame.history_valid.fillna(False)
        & frame.current_valid.fillna(False)
        & frame.corporate_action_valid.fillna(False)
        & ~frame.corporate_action_blocking.fillna(True)
        & frame.corporate_action_count.fillna(1).eq(0)
        & frame.previous_hard_valid.eq(True)
        & frame.previous_history_valid.eq(True)
        & frame.previous_current_valid.eq(True)
        & frame.previous_corporate_action_valid.eq(True)
        & frame.previous_corporate_action_blocking.eq(False)
        & frame.cal_idx.sub(frame.previous_cal_idx).eq(1)
        & frame.invalid_step_cum.eq(frame.previous_invalid_step_cum)
        & frame.high.lt(frame.previous_low)
    )
    gaps = frame.loc[mask].copy()
    gaps["gap_id"] = gaps.symbol.astype(str) + "|" + gaps.trade_date.dt.strftime("%Y-%m-%d")
    gaps["gap_date"] = gaps.trade_date
    gaps["gap_seq"] = gaps.symbol_seq.astype(int)
    gaps["board"] = gaps.sleeve.astype(str)
    gaps["L"] = gaps.high.astype(float) * gaps.coordinate_factor.astype(float)
    gaps["U"] = gaps.previous_low.astype(float) * gaps.coordinate_factor.astype(float)
    gaps["W"] = gaps.U - gaps.L
    gaps["gap_width_pct"] = (gaps.previous_low - gaps.high) / gaps.previous_close
    keep = [
        "gap_id", "symbol", "board", "gap_date", "cal_idx", "gap_seq",
        "invalid_step_cum", "coordinate_factor", "L", "U", "W", "gap_width_pct",
    ]
    result = gaps[keep].sort_values(["gap_date", "symbol"], kind="mergesort").reset_index(drop=True)
    if result.gap_id.duplicated().any() or not result.W.gt(0).all():
        raise ReproductionError("OGR true-gap identity failure")
    return result


def _first_true(mask: np.ndarray) -> int | None:
    found = np.flatnonzero(mask)
    return None if not len(found) else int(found[0])


def build_v13_candidates(daily: pd.DataFrame, gaps: pd.DataFrame) -> pd.DataFrame:
    groups = {symbol: part.reset_index(drop=True) for symbol, part in daily.groupby("symbol", sort=False)}
    rows: list[dict[str, object]] = []
    for gap in gaps.loc[gaps.gap_width_pct.ge(0.01)].itertuples(index=False):
        part = groups[str(gap.symbol)]
        gap_pos = int(gap.gap_seq)
        hist_pre = part.iloc[gap_pos - 120 : gap_pos].copy()
        if not (
            len(hist_pre) == 120
            and _valid_daily_rows(hist_pre).all()
            and hist_pre.invalid_step_cum.eq(float(gap.invalid_step_cum)).all()
        ):
            continue
        inside = hist_pre.coord_high.ge(float(gap.L)) & hist_pre.coord_low.lt(float(gap.U))
        corridor = hist_pre.coord_high.ge(float(gap.L - 0.5 * gap.W)) & hist_pre.coord_low.lt(float(gap.U + 0.5 * gap.W))
        if int(inside.sum()) > 12 or int(corridor.sum()) > 20:
            continue
        peak_offset = int(np.nanargmax(hist_pre.coord_high.to_numpy(float)))
        recent20 = hist_pre.tail(20)
        pre = {
            "pre_gap_inside_touch_sessions": int(inside.sum()),
            "pre_gap_corridor_touch_sessions": int(corridor.sum()),
            "pre_peak_to_gap_sessions": int(len(hist_pre) - peak_offset),
            "pre_gap_drawdown_from_120d_peak": float(1 - float(part.coord_low.iloc[gap_pos]) / float(hist_pre.coord_high.iloc[peak_offset])),
            "pre_gap_return_20d": float(hist_pre.coord_close.iloc[-1] / hist_pre.coord_close.iloc[-20] - 1),
            "pre_gap_range_20d": float(recent20.coord_high.max() / recent20.coord_low.min() - 1),
        }
        path = part.iloc[gap_pos + 1 : min(len(part), gap_pos + 181)].copy()
        valid = _valid_daily_rows(path) & path.invalid_step_cum.eq(float(gap.invalid_step_cum)).to_numpy(bool)
        bad = _first_true(~valid)
        if bad is not None:
            path = path.iloc[:bad]
        if len(path) < 10:
            continue
        touch = _first_true(_raw_tick_reached(path.high, float(gap.L), path.coordinate_factor))
        if touch is not None:
            path = path.iloc[:touch]
        if len(path) < 10:
            continue
        for rel in range(9, len(path)):
            absolute_pos = gap_pos + 1 + rel
            rolling = part.iloc[max(0, absolute_pos - 19) : absolute_pos + 1]
            if len(rolling) < 20:
                continue
            current, previous = rolling.iloc[-1], rolling.iloc[-2]
            since_gap = path.iloc[: rel + 1]
            max_depth = 1 - float(since_gap.coord_low.min()) / float(gap.L)
            current_depth = 1 - float(current.coord_close) / float(gap.L)
            low20_offset = int(np.nanargmin(rolling.coord_low.to_numpy(float)))
            days_since_low20 = len(rolling) - 1 - low20_offset
            recovery = float(current.coord_close / rolling.coord_low.min() - 1)
            if not (
                max_depth >= 0.10 and current_depth >= 0.05 and 1 <= days_since_low20 <= 10
                and recovery >= 0.03 and float(current.coord_close) > float(previous.coord_high)
            ):
                continue
            prior_turnover = rolling.iloc[:-1].turnover_fraction.astype(float)
            prior20_mean = float(prior_turnover.mean())
            prior5_mean = float(rolling.iloc[-6:-1].turnover_fraction.mean())
            rows.append({
                **gap._asdict(), **pre, "trigger": "PRIOR_HIGH_REVERSAL",
                "signal_date": pd.Timestamp(current.trade_date),
                "signal_time": pd.Timestamp(current.trade_date) + pd.Timedelta(hours=15),
                "signal_cal_idx": int(current.cal_idx), "signal_coord_close": float(current.coord_close),
                "swing_low": float(rolling.coord_low.min()), "gap_age": int(rel + 1),
                "max_depth": max_depth, "current_depth": current_depth,
                "days_since_low20": days_since_low20, "recovery_from_low20": recovery,
                "dry3": float(rolling.iloc[-4:-1].turnover_fraction.mean()) / prior20_mean if prior20_mean > 0 else math.nan,
                "trigger_expansion": float(current.turnover_fraction) / prior5_mean if prior5_mean > 0 else math.nan,
                "form": "PRIOR_HIGH_REVERSAL",
            })
            break
    result = pd.DataFrame(rows).sort_values(["signal_time", "symbol", "L", "gap_id"], kind="mergesort")
    result = result.drop_duplicates(["symbol", "signal_date"], keep="first").reset_index(drop=True)
    if result.empty or result.gap_id.duplicated().any():
        raise ReproductionError("OGR V13 candidate identity failure")
    return result


def attach_v13_vap(entries: pd.DataFrame, daily: pd.DataFrame, minute_root: Path, output: Path) -> pd.DataFrame:
    groups = {key: part.sort_values("trade_date").reset_index(drop=True) for key, part in daily.groupby("symbol", sort=False)}
    pieces: list[pd.DataFrame] = []
    rejected: list[str] = []
    for event in entries.drop_duplicates("gap_id").itertuples(index=False):
        part = groups[str(event.symbol)]
        positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.gap_date)).to_numpy())
        if len(positions) != 1:
            rejected.append(str(event.gap_id)); continue
        pos = int(positions[0]); hist = part.iloc[pos - 120 : pos].copy()
        if not (len(hist) == 120 and _valid_daily_rows(hist).all() and hist.invalid_step_cum.eq(float(event.invalid_step_cum)).all()):
            rejected.append(str(event.gap_id)); continue
        hist = hist[["symbol", "trade_date", "coordinate_factor", "turnover_fraction"]].copy()
        hist["gap_id"], hist["L"], hist["W"] = event.gap_id, float(event.L), float(event.W)
        pieces.append(hist)
    pre = pd.concat(pieces, ignore_index=True)
    pre_path = output / "v13_pre_gap_days.parquet"; write_parquet(pre, pre_path)
    frames: list[pd.DataFrame] = []
    for year in sorted(pre.trade_date.dt.year.unique()):
        raw = _raw_path(minute_root, int(year))
        con = duckdb.connect(); con.execute("SET threads=4")
        try:
            frames.append(con.execute(f"""
              WITH p AS (SELECT * FROM read_parquet('{_sql_path(pre_path)}') WHERE year(trade_date)={int(year)}),
              raw0 AS (
                SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,r.high,r.low,r.close,r.volume,r.amount
                FROM read_parquet('{_sql_path(raw)}') r
                JOIN (SELECT DISTINCT symbol,trade_date FROM p) n ON r.qmt_code=n.symbol AND r.trade_date=n.trade_date
                WHERE r.period='1m' AND r.adjust='none'
              ), joined0 AS (
                SELECT p.gap_id,p.trade_date,p.coordinate_factor,p.turnover_fraction,p.L,p.W,
                  r.bar_end_time,r.high,r.low,r.close,r.volume,r.amount,
                  count(*) OVER(PARTITION BY p.gap_id,r.trade_date) AS bars_in_session,
                  sum(r.volume) OVER(PARTITION BY p.gap_id,r.trade_date) AS day_volume
                FROM p JOIN raw0 r USING(symbol,trade_date)
              ), joined AS (
                SELECT *,CASE WHEN volume>0 AND amount>0 THEN amount/volume ELSE (high+low+close)/3 END AS minute_price,
                  CASE WHEN day_volume>0 THEN turnover_fraction*volume/day_volume ELSE NULL END AS minute_weight
                FROM joined0
              ), quality AS (
                SELECT gap_id,-999::INTEGER AS z_bin,count(DISTINCT trade_date)::DOUBLE AS mass,
                  count(DISTINCT trade_date) FILTER(WHERE bars_in_session=241 AND day_volume>0)::DOUBLE AS auxiliary
                FROM joined GROUP BY gap_id
              ), bins AS (
                SELECT gap_id,floor(((minute_price*coordinate_factor-L)/W)/0.10)::INTEGER AS z_bin,
                  sum(minute_weight)::DOUBLE AS mass,count(*)::DOUBLE AS auxiliary
                FROM joined WHERE minute_weight IS NOT NULL AND (minute_price*coordinate_factor-L)/W>=-2
                  AND (minute_price*coordinate_factor-L)/W<3 GROUP BY gap_id,z_bin
              ) SELECT * FROM quality UNION ALL SELECT * FROM bins ORDER BY gap_id,z_bin
            """).fetchdf())
        finally:
            con.close()
    combined = pd.concat(frames, ignore_index=True)
    quality = combined.loc[combined.z_bin.eq(-999)].groupby("gap_id", as_index=False).agg(
        minute_history_sessions=("mass", "sum"), exact_241_minute_sessions=("auxiliary", "sum"))
    profiles = combined.loc[combined.z_bin.ne(-999)].groupby(["gap_id", "z_bin"], as_index=False).agg(
        pre_float_turnover_mass=("mass", "sum"), contributing_minutes=("auxiliary", "sum"))
    local = profiles.groupby("gap_id", as_index=False).agg(local_mass=("pre_float_turnover_mass", "sum"))
    inside = profiles.loc[profiles.z_bin.between(0, 9)].groupby("gap_id", as_index=False).pre_float_turnover_mass.sum().rename(columns={"pre_float_turnover_mass": "inside_mass"})
    corridor = profiles.loc[profiles.z_bin.between(-5, 14)].groupby("gap_id", as_index=False).pre_float_turnover_mass.sum().rename(columns={"pre_float_turnover_mass": "corridor_mass"})
    corridor_max = profiles.loc[profiles.z_bin.between(-5, 14)].groupby("gap_id", as_index=False).pre_float_turnover_mass.max().rename(columns={"pre_float_turnover_mass": "corridor_max_bin_mass"})
    metrics = quality.merge(local, on="gap_id", how="left").merge(inside, on="gap_id", how="left").merge(corridor, on="gap_id", how="left").merge(corridor_max, on="gap_id", how="left")
    mass = ["local_mass", "inside_mass", "corridor_mass", "corridor_max_bin_mass"]
    metrics[mass] = metrics[mass].fillna(0.0); denom = metrics.local_mass.replace(0, np.nan)
    metrics["pre_gap_inside_density_relative_local"] = 5 * metrics.inside_mass / denom
    metrics["pre_gap_corridor_density_relative_local"] = 2.5 * metrics.corridor_mass / denom
    metrics["pre_gap_corridor_max_bin_density_relative_local"] = 50 * metrics.corridor_max_bin_mass / denom
    metrics["exact_minute_history"] = metrics.minute_history_sessions.eq(120) & metrics.exact_241_minute_sessions.eq(120)
    metrics["daily_history_rejected"] = metrics.gap_id.isin(rejected)
    panel = entries.merge(metrics, on="gap_id", how="left", validate="one_to_one")
    selected = panel.loc[
        panel.exact_minute_history.fillna(False)
        & panel.pre_gap_inside_density_relative_local.le(1.0)
        & panel.pre_gap_corridor_density_relative_local.le(1.0)
        & panel.pre_gap_return_20d.le(0.0)
    ].copy()
    selected["signal_year"] = pd.to_datetime(selected.signal_date).dt.year
    selected["decision_latest_timestamp"] = pd.to_datetime(selected.signal_time)
    selected["feature_uses_post_signal_information"] = False
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    write_parquet(selected, output / "v13_signals.parquet")
    return selected


def select_v27(entries: pd.DataFrame) -> pd.DataFrame:
    required = entries[["gap_age", "max_depth", "current_depth", "pre_peak_to_gap_sessions"]]
    mask = (
        required.notna().all(axis=1) & entries.gap_age.le(14)
        & (entries.max_depth - entries.current_depth).ge(0.05)
        & entries.pre_peak_to_gap_sessions.ge(20)
    )
    selected = entries.loc[mask & pd.to_datetime(entries.signal_date).dt.year.isin((2017, 2018, 2019, 2020, 2021))].copy()
    selected["rebound_from_post_gap_low_over_l"] = selected.max_depth - selected.current_depth
    selected["v27_mature_decline_gate"] = selected["v27_fresh_gap_gate"] = selected["v27_forceful_snapback_gate"] = True
    selected["semantic_feature_latest_timestamp"] = selected.signal_time
    selected["feature_uses_post_signal_information"] = False
    return selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)


def _load_cy033(root: Path, years: tuple[int, ...], columns: list[str], include_prior: bool = False) -> pd.DataFrame:
    wanted = set(years)
    if include_prior and (root / f"daily/partition_year={min(years) - 1}/data_0.parquet").is_file():
        wanted.add(min(years) - 1)
    frames = [read_parquet(_cy033_path(root, year), "SELECT " + ",".join(columns) + " FROM source") for year in sorted(wanted)]
    frame = pd.concat(frames, ignore_index=True)
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
    if "available_at" in frame:
        frame["available_at"] = pd.to_datetime(frame.available_at)
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ReproductionError("duplicate symbol-date in CY033")
    return frame


def select_v28(entries: pd.DataFrame, cy033_root: Path) -> pd.DataFrame:
    daily = _load_cy033(cy033_root, (2018, 2019, 2020, 2021), ["symbol", "trade_date", "open", "high", "low", "close", "down_limit_price"], include_prior=True)
    daily = daily.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    values = daily[["open", "high", "low", "close", "down_limit_price"]].to_numpy(dtype=float)
    daily["_one_price_limit_down"] = (np.isfinite(values).all(axis=1) & np.isclose(values[:, :4], values[:, 4, None], rtol=0.0, atol=0.006).all(axis=1) & (values[:, 4] > 0)).astype(float)
    daily["prior20_one_price_limit_down_count"] = daily.groupby("symbol", sort=False)["_one_price_limit_down"].transform(lambda x: x.shift(1).rolling(20, min_periods=20).sum())
    result = entries.copy(); result["signal_date"] = pd.to_datetime(result.signal_date).dt.normalize(); result["signal_time"] = pd.to_datetime(result.signal_time)
    result = result.merge(daily[["symbol", "trade_date", "prior20_one_price_limit_down_count"]], left_on=["symbol", "signal_date"], right_on=["symbol", "trade_date"], how="left", validate="many_to_one").drop(columns="trade_date")
    result["liquidity_trap_guard"] = result.prior20_one_price_limit_down_count.notna() & result.prior20_one_price_limit_down_count.le(1)
    state = _load_cy033(cy033_root, (2018, 2019, 2020, 2021), ["symbol", "trade_date", "is_st", "hard_valid", "available_at", "snapshot_id"])
    state = state.rename(columns={"trade_date": "signal_date", "is_st": "signal_is_st", "hard_valid": "signal_state_hard_valid", "available_at": "signal_state_available_at", "snapshot_id": "signal_state_snapshot_id"})
    result = result.merge(state, on=["symbol", "signal_date"], how="left", validate="many_to_one")
    available = result.signal_state_available_at.notna() & result.signal_state_available_at.le(result.signal_time)
    result["signal_state_available_by_decision"] = available
    result["signal_state_hard_valid"] = result.signal_state_hard_valid.eq(True) & available
    result.loc[~available, "signal_is_st"] = pd.NA
    result["v28_liquidity_trap_gate"] = result.liquidity_trap_guard
    result["v28_signal_non_st_gate"] = result.signal_is_st.eq(False).fillna(False)
    result["v28_feature_latest_timestamp"] = result.signal_state_available_at
    result["v28_feature_uses_post_signal_information"] = False
    mask = result[["prior20_one_price_limit_down_count", "signal_state_hard_valid", "signal_is_st"]].notna().all(axis=1) & result.signal_state_hard_valid.eq(True) & result.signal_is_st.eq(False) & result.prior20_one_price_limit_down_count.le(1)
    return result.loc[mask].sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)


def select_v28r1(entries: pd.DataFrame, cy033_root: Path) -> pd.DataFrame:
    state = _load_cy033(cy033_root, (2018, 2019, 2020, 2021), ["symbol", "trade_date", "close", "up_limit_price", "hard_valid", "available_at", "snapshot_id"])
    state = state.rename(columns={"trade_date": "signal_date", "close": "signal_raw_close", "up_limit_price": "signal_up_limit_price", "hard_valid": "signal_price_hard_valid", "available_at": "signal_price_available_at", "snapshot_id": "signal_price_snapshot_id"})
    result = entries.merge(state, on=["symbol", "signal_date"], how="left", validate="many_to_one")
    available = result.signal_price_available_at.notna() & result.signal_price_available_at.le(result.signal_time)
    result["signal_price_available_by_decision"] = available
    result["signal_price_hard_valid"] = result.signal_price_hard_valid.eq(True) & available
    result["signal_closed_at_up_limit"] = result.signal_raw_close.notna() & result.signal_up_limit_price.notna() & result.signal_raw_close.ge(result.signal_up_limit_price - 0.006)
    required = result[["signal_raw_close", "signal_up_limit_price", "signal_price_hard_valid", "signal_price_available_by_decision"]]
    mask = required.notna().all(axis=1) & result.signal_price_hard_valid.eq(True) & result.signal_price_available_by_decision.eq(True) & result.signal_up_limit_price.gt(0) & result.signal_raw_close.lt(result.signal_up_limit_price - 0.006)
    result["v28r1_demand_not_locked_gate"] = mask
    result["v28r1_feature_latest_timestamp"] = result.signal_price_available_at
    result["v28r1_feature_uses_post_signal_information"] = False
    return result.loc[mask].sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)


def select_v28r2(entries: pd.DataFrame, cy033_root: Path) -> pd.DataFrame:
    daily = _load_cy033(cy033_root, (2018, 2019, 2020, 2021), ["symbol", "trade_date", "decision_at", "amount", "trade_status", "hard_valid", "available_at", "snapshot_id"], include_prior=True)
    daily["decision_at"] = pd.to_datetime(daily.decision_at)
    groups = {str(symbol): group.reset_index(drop=True) for symbol, group in daily.sort_values(["symbol", "trade_date"], kind="mergesort").groupby("symbol", sort=False)}
    records: list[dict[str, Any]] = []
    for event in entries[["gap_id", "symbol", "signal_date", "signal_time"]].itertuples(index=False):
        group = groups.get(str(event.symbol)); signal = pd.DataFrame() if group is None else group.loc[group.trade_date.eq(event.signal_date)]
        row = signal.iloc[0] if len(signal) == 1 else None
        amount = np.nan if row is None else pd.to_numeric(pd.Series([row.amount]), errors="coerce").iloc[0]
        signal_available = bool(row is not None and pd.notna(row.available_at) and row.available_at <= event.signal_time and pd.notna(row.decision_at) and row.decision_at <= event.signal_time)
        snapshot_ok = bool(row is not None and pd.notna(row.snapshot_id) and str(row.snapshot_id).strip())
        signal_valid = bool(row is not None and bool(row.hard_valid) and row.trade_status == 1 and pd.notna(amount) and np.isfinite(float(amount)) and float(amount) > 0 and snapshot_ok and signal_available)
        before = pd.DataFrame() if group is None else group.loc[group.trade_date.lt(event.signal_date)]
        traded = before.loc[before.trade_status.eq(1)].tail(20); amounts = pd.to_numeric(traded.amount, errors="coerce")
        unknown = 0 if len(traded) != 20 else int((~before.loc[before.trade_date.ge(traded.trade_date.iloc[0])].trade_status.isin([0, 1])).sum())
        history_valid = bool(len(traded) == 20 and unknown == 0 and traded.hard_valid.eq(True).all() and traded.available_at.notna().all() and traded.available_at.le(event.signal_time).all() and traded.decision_at.notna().all() and traded.decision_at.le(event.signal_time).all() and traded.snapshot_id.notna().all() and traded.snapshot_id.astype(str).str.strip().ne("").all() and np.isfinite(amounts.to_numpy(dtype=float)).all() and amounts.gt(0).all())
        median = float(amounts.median()) if history_valid else np.nan
        latest = ([] if row is None or pd.isna(row.available_at) else [row.available_at]) + traded.available_at.dropna().tolist()
        records.append({"gap_id": event.gap_id, "signal_raw_amount": float(amount) if pd.notna(amount) else np.nan, "signal_amount_state_hard_valid": signal_valid, "signal_amount_available_by_decision": signal_available, "signal_amount_snapshot_id": None if row is None else row.snapshot_id, "prior20_completed_trading_sessions": len(traded), "prior20_unknown_trading_state_rows": unknown, "prior20_hard_valid_sessions": int(traded.hard_valid.eq(True).sum()), "prior20_available_by_decision_sessions": int((traded.available_at.notna() & traded.available_at.le(event.signal_time)).sum()), "prior20_finite_positive_amount_sessions": int((amounts.notna() & amounts.gt(0) & np.isfinite(amounts)).sum()), "prior20_amount_history_complete": history_valid, "prior20_median_amount": median, "signal_amount_to_prior20_median": float(amount) / median if signal_valid and history_valid and median > 0 else np.nan, "v28r2_feature_latest_timestamp": max(latest) if latest else pd.NaT})
    result = entries.merge(pd.DataFrame(records), on="gap_id", how="left", validate="one_to_one")
    required = result[["signal_raw_amount", "signal_amount_state_hard_valid", "signal_amount_available_by_decision", "prior20_completed_trading_sessions", "prior20_amount_history_complete", "prior20_median_amount", "signal_amount_to_prior20_median"]]
    mask = required.notna().all(axis=1) & result.signal_amount_state_hard_valid.eq(True) & result.signal_amount_available_by_decision.eq(True) & result.prior20_completed_trading_sessions.eq(20) & result.prior20_amount_history_complete.eq(True) & result.signal_raw_amount.gt(0) & result.prior20_median_amount.gt(0) & result.signal_amount_to_prior20_median.le(2.0)
    result["v28r2_orderly_amount_gate"] = mask
    result["v28r2_feature_uses_post_signal_information"] = False
    return result.loc[mask].sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)


def build_signal_chain(daily_path: Path, minute_root: Path, cy033_root: Path, output: Path) -> dict[str, pd.DataFrame]:
    output.mkdir(parents=True, exist_ok=True)
    daily = load_daily(daily_path)
    v13_candidates = build_v13_candidates(daily, build_all_true_gaps(daily))
    v13_candidates = v13_candidates.loc[pd.to_datetime(v13_candidates.signal_date).dt.year.isin((2017, 2018, 2019, 2020, 2021))].copy()
    write_parquet(v13_candidates, output / "v13_candidates.parquet")
    v13 = attach_v13_vap(v13_candidates, daily, minute_root, output)
    v27 = select_v27(v13); write_parquet(v27, output / "v27.parquet")
    v28 = select_v28(v27, cy033_root); write_parquet(v28, output / "v28.parquet")
    v28r1 = select_v28r1(v28, cy033_root); write_parquet(v28r1, output / "v28r1.parquet")
    v28r2 = select_v28r2(v28r1, cy033_root); write_parquet(v28r2, output / "signals.parquet")
    return {"v13_candidates": v13_candidates, "v13": v13, "v27": v27, "v28": v28, "v28r1": v28r1, "v28r2": v28r2, "daily": daily}


def load_actions(distributions_path: Path, rights_path: Path, symbols: list[str]) -> pd.DataFrame:
    registry = pd.DataFrame({"symbol": sorted(set(symbols))})
    registry["raw_symbol"] = registry.symbol.str.split(".").str[0]
    con = duckdb.connect(); con.register("registry", registry)
    try:
        distributions = con.execute(f"""
          SELECT r.symbol,a.event_id,
            CASE WHEN coalesce(a.share_multiplier,1)>1 THEN 'RISK_SHARE' ELSE 'CASH_ONLY' END AS action_kind,
            CAST(a.known_at AS DATE) AS known_date,CAST(a.effective_date AS DATE) AS effective_date,
            coalesce(a.cash_per_share_gross,0)::DOUBLE AS cash_per_share,
            coalesce(a.share_multiplier,1)::DOUBLE AS share_multiplier,a.source_terms_complete
          FROM read_parquet('{_sql_path(distributions_path)}') a JOIN registry r ON r.raw_symbol=a.symbol
          WHERE a.effective_date BETWEEN DATE '2014-01-01' AND DATE '2022-03-31'
        """).fetchdf()
        rights = con.execute(f"""
          SELECT r.symbol,a.event_id,'RISK_RIGHTS' AS action_kind,
            CAST(a.known_at AS DATE) AS known_date,CAST(a.effective_date AS DATE) AS effective_date,
            0.0::DOUBLE AS cash_per_share,1.0::DOUBLE AS share_multiplier,a.source_terms_complete
          FROM read_parquet('{_sql_path(rights_path)}') a JOIN registry r ON r.raw_symbol=a.symbol
          WHERE a.effective_date BETWEEN DATE '2014-01-01' AND DATE '2022-03-31'
        """).fetchdf()
    finally:
        con.close()
    actions = pd.concat([distributions, rights], ignore_index=True)
    for column in ("known_date", "effective_date"):
        actions[column] = pd.to_datetime(actions[column])
    actions = actions.sort_values(["symbol", "known_date", "effective_date", "event_id"], kind="mergesort").drop_duplicates(["symbol", "event_id", "action_kind"], keep="last")
    if len(actions) and ((~actions.source_terms_complete.fillna(False)).any() or actions.known_date.ge(actions.effective_date).any()):
        raise ReproductionError("OGR corporate-action lineage failure")
    return actions


def build_entries(signals: pd.DataFrame, daily: pd.DataFrame, minute_root: Path, actions: pd.DataFrame) -> pd.DataFrame:
    seed = signals[["gap_id", "symbol", "signal_time", "signal_date", "invalid_step_cum", "L"]].copy()
    state = daily.loc[daily.symbol.isin(seed.symbol.unique())].copy()
    first_parts: list[pd.DataFrame] = []
    remaining = seed.copy()
    for year in range(int(pd.to_datetime(seed.signal_date).dt.year.min()), 2023):
        if remaining.empty:
            break
        raw = _raw_path(minute_root, year)
        con = duckdb.connect(); con.register("remaining_seed", remaining); con.register("execution_state", state)
        try:
            candidate = con.execute(f"""
              SELECT s.gap_id,s.symbol,r.trade_date,r.bar_end_time,r.open AS entry_raw_price,
                d.cal_idx AS entry_cal_idx,d.coordinate_factor AS entry_coordinate_factor,
                d.invalid_step_cum AS entry_invalid_step_cum,d.up_limit_price,
                row_number() OVER(PARTITION BY s.gap_id ORDER BY r.bar_end_time) AS candidate_order
              FROM remaining_seed s JOIN read_parquet('{_sql_path(raw)}') r
                ON r.qmt_code=s.symbol AND r.bar_end_time>s.signal_time
              JOIN execution_state d ON d.symbol=s.symbol AND d.trade_date=r.trade_date
              WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={year}
                AND r.trade_date<=DATE '2022-03-31' AND d.invalid_step_cum=s.invalid_step_cum
                AND d.history_valid AND d.current_valid AND d.hard_valid AND d.trade_status=1
                AND d.current_day_data_tradable AND d.market_rule_valid AND NOT d.corporate_action_blocking
                AND isfinite(r.open) AND r.open>0 AND round(r.open*100)<round(d.up_limit_price*100)
              QUALIFY candidate_order=1
            """).fetchdf()
        finally:
            con.close()
        if len(candidate):
            first_parts.append(candidate.drop(columns="candidate_order"))
            remaining = remaining.loc[~remaining.gap_id.isin(candidate.gap_id.astype(str))].copy()
    first = pd.concat(first_parts, ignore_index=True).sort_values(["gap_id", "bar_end_time"], kind="mergesort").drop_duplicates("gap_id", keep="first")
    entries = signals.merge(first, on=["gap_id", "symbol"], how="left", validate="one_to_one")
    for column in ("signal_time", "signal_date", "trade_date", "bar_end_time"):
        entries[column] = pd.to_datetime(entries[column])
    entries = entries.rename(columns={"trade_date": "entry_date", "bar_end_time": "entry_time"})
    entries["entry_coordinate_price"] = entries.entry_raw_price * entries.entry_coordinate_factor
    entries["realized_net_l_headroom"] = (entries.L / entries.entry_coordinate_price) * (1 - 0.002) / (1 + 0.002) - 1
    entries["entry_status"] = np.where(entries.entry_time.isna(), "NO_NEXT_BUYABLE_OPEN", "EXECUTABLE_ENTRY")
    groups = {key: part for key, part in actions.groupby("symbol", sort=False)}
    for index, row in entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].iterrows():
        act = groups.get(str(row.symbol), pd.DataFrame(columns=actions.columns))
        effective_between = act.loc[act.effective_date.gt(row.signal_date.normalize()) & act.effective_date.le(row.entry_date.normalize())]
        pending_risk = act.loc[act.action_kind.astype(str).str.startswith("RISK") & act.known_date.le(row.entry_date.normalize()) & act.effective_date.gt(row.entry_date.normalize())]
        if len(effective_between) or len(pending_risk):
            entries.at[index, "entry_status"] = "RISK_BLOCKED_ENTRY"
        elif float(row.realized_net_l_headroom) < 0.05:
            entries.at[index, "entry_status"] = "INSUFFICIENT_L_HEADROOM"
    entries["entry_at_or_before_signal"] = entries.entry_time.notna() & entries.entry_time.le(entries.signal_time)
    entries["entry_after_signal_period_boundary"] = entries.entry_time.notna() & entries.entry_date.gt(pd.Timestamp("2021-12-31"))
    entries["buy_at_or_above_up_limit"] = entries.entry_time.notna() & (np.rint(entries.entry_raw_price * 100) >= np.rint(entries.up_limit_price * 100))
    if entries.entry_at_or_before_signal.any() or entries.buy_at_or_above_up_limit.any() or entries.gap_id.duplicated().any():
        raise ReproductionError("OGR entry causality/identity failure")
    return entries


def build_outcomes(entries: pd.DataFrame, daily: pd.DataFrame, minute_root: Path, actions: pd.DataFrame) -> pd.DataFrame:
    eligible = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    calendar = daily[["trade_date", "cal_idx"]].drop_duplicates("trade_date").sort_values("cal_idx", kind="mergesort")
    date_by_idx = calendar.set_index("cal_idx").trade_date
    bounds = eligible[["gap_id", "symbol", "entry_date", "entry_time", "entry_cal_idx"]].copy()
    bounds["path_end_date"] = (bounds.entry_cal_idx.astype(int) + 20).map(date_by_idx)
    if bounds.path_end_date.isna().any():
        raise ReproductionError("OGR outcome calendar tail missing")
    state = daily.loc[daily.symbol.isin(eligible.symbol.unique())].copy()
    minute_parts: list[pd.DataFrame] = []; sell_parts: list[pd.DataFrame] = []
    symbols = pd.DataFrame({"symbol": sorted(eligible.symbol.astype(str).unique())})
    for year in range(int(eligible.entry_date.dt.year.min()), 2023):
        raw = _raw_path(minute_root, year)
        con = duckdb.connect(); con.register("bounds", bounds); con.register("execution_state", state); con.register("symbols", symbols)
        try:
            minute_parts.append(con.execute(f"""
              SELECT b.gap_id,b.symbol,r.trade_date,r.bar_end_time,r.open,r.high,r.low,r.close,
                d.cal_idx,d.coordinate_factor,d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,
                d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
                d.up_limit_price,d.down_limit_price,r.open*d.coordinate_factor AS coord_open,
                r.high*d.coordinate_factor AS coord_high,r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close
              FROM bounds b JOIN read_parquet('{_sql_path(raw)}') r
                ON r.qmt_code=b.symbol AND r.trade_date BETWEEN b.entry_date AND b.path_end_date AND r.bar_end_time>=b.entry_time
              JOIN execution_state d ON d.symbol=b.symbol AND d.trade_date=r.trade_date
              WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={year}
              ORDER BY b.gap_id,r.bar_end_time
            """).fetchdf())
            sell_parts.append(con.execute(f"""
              SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,r.open AS raw_open,
                d.cal_idx,d.coordinate_factor,d.invalid_step_cum,d.down_limit_price,
                row_number() OVER(PARTITION BY r.qmt_code,r.trade_date ORDER BY r.bar_end_time) AS sell_order
              FROM read_parquet('{_sql_path(raw)}') r JOIN symbols s ON s.symbol=r.qmt_code
              JOIN execution_state d ON d.symbol=r.qmt_code AND d.trade_date=r.trade_date
              WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={year} AND r.trade_date<=DATE '2022-03-31'
                AND d.history_valid AND d.current_valid AND d.hard_valid AND d.trade_status=1
                AND d.current_day_data_tradable AND d.market_rule_valid AND NOT d.corporate_action_blocking
                AND isfinite(r.open) AND r.open>0 AND round(r.open*100)>round(d.down_limit_price*100)
              QUALIFY sell_order=1 ORDER BY symbol,bar_end_time
            """).fetchdf().drop(columns="sell_order"))
        finally:
            con.close()
    minutes = pd.concat(minute_parts, ignore_index=True); sells = pd.concat(sell_parts, ignore_index=True)
    for frame in (minutes, sells):
        frame["trade_date"] = pd.to_datetime(frame.trade_date); frame["bar_end_time"] = pd.to_datetime(frame.bar_end_time)
    minute_by = {key: part.sort_values("bar_end_time", kind="mergesort") for key, part in minutes.groupby("gap_id", sort=False)}
    sell_by = {key: part.sort_values("bar_end_time", kind="mergesort") for key, part in sells.groupby("symbol", sort=False)}
    action_by = {key: part.sort_values(["known_date", "effective_date"], kind="mergesort") for key, part in actions.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    for entry in eligible.itertuples(index=False):
        path = minute_by[str(entry.gap_id)]; sell = sell_by[str(entry.symbol)]
        act = action_by.get(str(entry.symbol), pd.DataFrame(columns=actions.columns))
        target_coord = float(entry.entry_coordinate_price) + 0.67 * (float(entry.L) - float(entry.entry_coordinate_price))
        later_actions = act.loc[act.effective_date.gt(pd.Timestamp(entry.entry_date).normalize())].sort_values(["effective_date", "event_id"], kind="mergesort")
        first_effective = None if later_actions.empty else pd.Timestamp(later_actions.effective_date.iloc[0])
        target_pool = path.loc[
            path.bar_end_time.gt(pd.Timestamp(entry.entry_time)) & path.cal_idx.gt(int(entry.entry_cal_idx))
            & path.cal_idx.le(int(entry.entry_cal_idx) + 20) & path.invalid_step_cum.eq(float(entry.entry_invalid_step_cum))
            & path.hard_valid.eq(True) & path.trade_status.eq(1) & path.current_day_data_tradable.eq(True)
            & path.market_rule_valid.eq(True) & path.corporate_action_blocking.eq(False)
        ].copy()
        if first_effective is not None:
            target_pool = target_pool.loc[target_pool.trade_date.lt(first_effective.normalize())]
        target_rows = target_pool.loc[_raw_tick_reached(target_pool.high, target_coord, target_pool.coordinate_factor)]
        choices: list[dict[str, Any]] = []
        if len(target_rows):
            row = target_rows.iloc[0]; raw_target = float(_boundary_ticks(target_coord, float(row.coordinate_factor))) / 100.0
            choices.append({"exit_time": row.bar_end_time, "exit_date": row.trade_date, "exit_raw_price": max(float(row.open), raw_target), "exit_cal_idx": int(row.cal_idx), "exit_reason": "PRE_L_TARGET"})
        checkpoint = calendar.loc[calendar.cal_idx.eq(int(entry.entry_cal_idx) + 20)]
        if checkpoint.empty:
            raise ReproductionError(f"OGR missing H20 checkpoint: {entry.gap_id}")
        trigger = pd.Timestamp(checkpoint.trade_date.iloc[0]) + pd.Timedelta(hours=15)
        time_rows = sell.loc[sell.bar_end_time.gt(trigger)]
        if len(time_rows):
            row = time_rows.iloc[0]; choices.append({"exit_time": row.bar_end_time, "exit_date": row.trade_date, "exit_raw_price": float(row.raw_open), "exit_cal_idx": int(row.cal_idx), "exit_reason": "H20_TIME_STOP"})
        risks = act.loc[act.action_kind.astype(str).str.startswith("RISK") & act.known_date.gt(pd.Timestamp(entry.signal_time).normalize()) & act.known_date.le(trigger.normalize()) & act.effective_date.gt(pd.Timestamp(entry.entry_date).normalize())]
        blocked: list[dict[str, Any]] = []
        for risk in risks.itertuples(index=False):
            decision = calendar.loc[calendar.trade_date.ge(pd.Timestamp(risk.known_date)) & calendar.trade_date.lt(pd.Timestamp(risk.effective_date))]
            if decision.empty:
                blocked.append({"effective_date": pd.Timestamp(risk.effective_date)}); continue
            risk_rows = sell.loc[sell.bar_end_time.gt(pd.Timestamp(decision.trade_date.iloc[0]) + pd.Timedelta(hours=15)) & sell.trade_date.lt(pd.Timestamp(risk.effective_date).normalize())]
            if risk_rows.empty:
                blocked.append({"effective_date": pd.Timestamp(risk.effective_date)}); continue
            row = risk_rows.iloc[0]; choices.append({"exit_time": row.bar_end_time, "exit_date": row.trade_date, "exit_raw_price": float(row.raw_open), "exit_cal_idx": int(row.cal_idx), "exit_reason": "CORPORATE_ACTION_RISK"})
        chosen = sorted(choices, key=lambda x: (pd.Timestamp(x["exit_time"]), 0 if x["exit_reason"] == "PRE_L_TARGET" else 1, x["exit_reason"]))[0]
        if blocked and pd.Timestamp(chosen["exit_time"]) >= min(x["effective_date"] for x in blocked):
            raise ReproductionError(f"OGR unresolved corporate action: {entry.gap_id}")
        cash_rows = act.loc[act.action_kind.eq("CASH_ONLY") & act.effective_date.gt(pd.Timestamp(entry.entry_date).normalize()) & act.effective_date.le(pd.Timestamp(chosen["exit_date"]).normalize())]
        cash_payload = [{"date": str(pd.Timestamp(row.effective_date).date()), "cash_per_share": float(row.cash_per_share), "event_id": str(row.event_id)} for row in cash_rows.itertuples(index=False)]
        cash = float(cash_rows.cash_per_share.sum())
        net = (float(chosen["exit_raw_price"]) * (1 - 0.002) + cash) / (float(entry.entry_raw_price) * (1 + 0.002)) - 1
        lineage_break = bool(path.loc[path.bar_end_time.le(pd.Timestamp(chosen["exit_time"])), "invalid_step_cum"].ne(float(entry.entry_invalid_step_cum)).any() or act.effective_date.between(pd.Timestamp(entry.entry_date).normalize() + pd.Timedelta(days=1), pd.Timestamp(chosen["exit_date"]).normalize()).any())
        rows.append({**entry._asdict(), "alpha": 0.67, "horizon": 20, "stop": "NONE", "target_coordinate": target_coord, **chosen, "net_return": net, "holding_sessions": int(chosen["exit_cal_idx"]) - int(entry.entry_cal_idx), "cash_events_json": json.dumps(cash_payload, sort_keys=True), "lineage_break_before_exit": lineage_break})
    outcomes = pd.DataFrame(rows).sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if len(outcomes) != len(eligible):
        raise ReproductionError("OGR outcome identity conservation failure")
    return outcomes


@dataclass
class OgrReplay:
    nav: pd.DataFrame
    accepted: pd.DataFrame
    ledger: pd.DataFrame


def _replay_board(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
    board: str,
    *,
    account_start: str = "2018-01-01",
    account_end: str = "2021-12-31",
) -> OgrReplay:
    signals = trades.loc[trades.board.eq(board)].copy().sort_values(["entry_time", "realized_net_target_at_entry", "pre_gap_inside_density_relative_local", "symbol", "gap_id"], ascending=[True, False, True, True, True], kind="mergesort")
    period_end = min(
        pd.Timestamp(trades.exit_date.max()).normalize(), pd.Timestamp(account_end)
    )
    calendar = daily.loc[
        daily.trade_date.between(pd.Timestamp(account_start), period_end),
        ["trade_date", "cal_idx"],
    ].drop_duplicates("trade_date").sort_values("trade_date")
    relevant = daily.loc[daily.symbol.isin(signals.symbol.unique())].copy()
    by_symbol = {key: part.sort_values("trade_date") for key, part in relevant.groupby("symbol", sort=False)}
    marks = {(row.symbol, pd.Timestamp(row.trade_date)): float(row.close) for row in relevant.itertuples(index=False) if np.isfinite(row.close)}
    cash = 1.0; active: dict[str, dict[str, Any]] = {}; accepted: list[dict[str, Any]] = []; ledger: list[dict[str, Any]] = []
    def mark(position: dict[str, Any], when: pd.Timestamp, inclusive: bool = False) -> float:
        part = by_symbol.get(position["symbol"], pd.DataFrame()); subset = part.loc[part.trade_date.le(when.normalize())] if inclusive else part.loc[part.trade_date.lt(when.normalize())]
        return float(subset.close.iloc[-1]) if len(subset) else float(position["entry_raw_price"])
    def credit(position: dict[str, Any], when: pd.Timestamp) -> float:
        amount = 0.0
        while position["cash_event_index"] < len(position["cash_events"]):
            event = position["cash_events"][position["cash_event_index"]]
            if pd.Timestamp(event["date"]) > when.normalize(): break
            amount += position["qty"] * float(event["cash_per_share"]); position["cash_event_index"] += 1
        return amount
    def close_due(when: pd.Timestamp) -> None:
        nonlocal cash
        due = sorted([v for v in active.values() if pd.Timestamp(v["exit_time"]) <= when], key=lambda v: (pd.Timestamp(v["exit_time"]), v["symbol"]))
        for position in due:
            cash += credit(position, pd.Timestamp(position["exit_time"])) + position["qty"] * float(position["exit_raw_price"]) * (1 - 0.002); position["completed"] = True; active.pop(position["symbol"], None)
    for timestamp, group in signals.groupby("entry_time", sort=True):
        timestamp = pd.Timestamp(timestamp); close_due(timestamp)
        for position in active.values(): cash += credit(position, timestamp)
        for row in group.itertuples(index=False):
            base = {"procedure": row.procedure, "gap_id": row.gap_id, "symbol": row.symbol, "board": board, "entry_time": row.entry_time}
            if row.symbol in active: ledger.append({**base, "status": "SKIPPED_DUPLICATE_SYMBOL"}); continue
            if len(active) >= 80: ledger.append({**base, "status": "SKIPPED_CAPACITY"}); continue
            nav_now = cash + sum(p["qty"] * mark(p, timestamp) for p in active.values()); outlay = nav_now / 80
            if outlay <= 0 or cash + 1e-12 < outlay: ledger.append({**base, "status": "SKIPPED_INSUFFICIENT_CASH"}); continue
            position = row._asdict(); position["qty"] = outlay / (float(row.entry_raw_price) * (1 + 0.002)); position["entry_outlay"] = outlay; position["completed"] = False; position["cash_events"] = json.loads(row.cash_events_json or "[]"); position["cash_event_index"] = 0
            cash -= outlay; active[row.symbol] = position; accepted.append(position); ledger.append({**base, "status": "EXECUTED", "entry_outlay": outlay})
    close_due(pd.Timestamp(calendar.trade_date.max()) + pd.Timedelta(hours=23))
    entries_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list); exits_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    for position in accepted:
        entries_by_date[pd.Timestamp(position["entry_date"]).normalize()].append(position); exits_by_date[pd.Timestamp(position["exit_date"]).normalize()].append(position)
    cash_daily = 1.0; live: dict[str, dict[str, Any]] = {}; nav_rows: list[dict[str, Any]] = []
    for date in pd.to_datetime(calendar.trade_date):
        for position in live.values():
            for event in position["cash_events"]:
                if pd.Timestamp(event["date"]) == date: cash_daily += position["qty"] * float(event["cash_per_share"])
        events = [(pd.Timestamp(p["entry_time"]), "ENTRY", p) for p in entries_by_date.get(date, [])] + [(pd.Timestamp(p["exit_time"]), "EXIT", p) for p in exits_by_date.get(date, [])]
        for _, kind, position in sorted(events, key=lambda x: (x[0], 0 if x[1] == "EXIT" else 1, x[2]["symbol"])):
            if kind == "ENTRY": cash_daily -= position["entry_outlay"]; live[position["symbol"]] = position
            else: cash_daily += position["qty"] * float(position["exit_raw_price"]) * (1 - 0.002); live.pop(position["symbol"], None)
        exposure = sum(position["qty"] * marks.get((symbol, date), mark(position, date, inclusive=True)) for symbol, position in live.items()); nav = cash_daily + exposure
        nav_rows.append({"trade_date": date, "nav": nav, "cash": cash_daily, "gross_exposure": exposure, "utilization": 0 if nav == 0 else exposure / nav, "active_positions": len(live), "board": board})
    nav = pd.DataFrame(nav_rows)
    if (
        nav.active_positions.max() > 80
        or nav.cash.min() < -1e-10
        or nav.gross_exposure.gt(nav.nav + 1e-10).any()
    ):
        raise ReproductionError("OGR portfolio capacity/leverage breach")
    return OgrReplay(nav, pd.DataFrame(accepted), pd.DataFrame(ledger))


def replay_portfolio(
    outcomes: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    account_start: str = "2018-01-01",
    account_end: str = "2021-12-31",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trades = outcomes.copy()
    trades["procedure"] = "FIXED_BELOW_L_REPAIR"
    trades["realized_net_target_at_entry"] = (trades.target_coordinate / trades.entry_coordinate_price) * (1 - 0.002) / (1 + 0.002) - 1
    trades["u_hit"] = trades.exit_reason.eq("PRE_L_TARGET"); trades["outcome_valid"] = True
    replays = {
        board: _replay_board(
            trades,
            daily,
            board,
            account_start=account_start,
            account_end=account_end,
        )
        for board in ("MAIN", "CHINEXT")
    }
    accepted = pd.concat([replays["MAIN"].accepted.assign(board="MAIN", sleeve_weight=0.5), replays["CHINEXT"].accepted.assign(board="CHINEXT", sleeve_weight=0.5)], ignore_index=True)
    main, chinext = replays["MAIN"].nav, replays["CHINEXT"].nav
    combined = main.merge(chinext, on="trade_date", suffixes=("_main", "_chinext"), validate="one_to_one")
    combined["nav"] = 0.5 * combined.nav_main + 0.5 * combined.nav_chinext; combined["gross_exposure"] = 0.5 * combined.gross_exposure_main + 0.5 * combined.gross_exposure_chinext; combined["cash"] = combined.nav - combined.gross_exposure; combined["utilization"] = combined.gross_exposure / combined.nav; combined["active_positions"] = combined.active_positions_main + combined.active_positions_chinext; combined["board"] = "COMBINED"
    combined = combined[["trade_date", "nav", "cash", "gross_exposure", "utilization", "active_positions", "board"]]
    nav = pd.concat([main.assign(board="MAIN"), chinext.assign(board="CHINEXT"), combined], ignore_index=True)
    ledger = pd.concat([replays["MAIN"].ledger.assign(board="MAIN"), replays["CHINEXT"].ledger.assign(board="CHINEXT")], ignore_index=True)
    return accepted, ledger, nav
