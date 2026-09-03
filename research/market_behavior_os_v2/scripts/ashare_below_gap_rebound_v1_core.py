"""Causal daily signal construction for below-gap reversal repair research."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_all_true_gap_clean_corridor_profit_confirmation_v2 as source,
)


def first_true(mask: np.ndarray) -> int | None:
    found = np.flatnonzero(mask)
    return None if not len(found) else int(found[0])


def build_all_true_gaps(daily: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct direct true gaps without using a later return-to-gap label."""
    frame = daily.copy()
    grouped = frame.groupby("symbol", sort=False)
    previous = (
        "trade_date",
        "cal_idx",
        "low",
        "close",
        "invalid_step_cum",
        "hard_valid",
        "history_valid",
        "current_valid",
        "corporate_action_valid",
        "corporate_action_blocking",
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
    gaps["gap_id"] = (
        gaps.symbol.astype(str) + "|" + gaps.trade_date.dt.strftime("%Y-%m-%d")
    )
    gaps["gap_date"] = gaps.trade_date
    gaps["gap_seq"] = gaps.symbol_seq.astype(int)
    gaps["board"] = gaps.sleeve.astype(str)
    gaps["L"] = gaps.high.astype(float) * gaps.coordinate_factor.astype(float)
    gaps["U"] = gaps.previous_low.astype(float) * gaps.coordinate_factor.astype(float)
    gaps["W"] = gaps.U - gaps.L
    gaps["gap_width_pct"] = (
        gaps.previous_low - gaps.high
    ) / gaps.previous_close
    keep = [
        "gap_id",
        "symbol",
        "board",
        "gap_date",
        "cal_idx",
        "gap_seq",
        "invalid_step_cum",
        "coordinate_factor",
        "L",
        "U",
        "W",
        "gap_width_pct",
    ]
    result = gaps[keep].sort_values(
        ["gap_date", "symbol"], kind="mergesort"
    ).reset_index(drop=True)
    if result.gap_id.duplicated().any() or not result.W.gt(0).all():
        raise RuntimeError("true-gap identity failure")
    return result


def build_ma5_signal_candidates(
    daily: pd.DataFrame, gaps: pd.DataFrame
) -> pd.DataFrame:
    """Find each gap's first causal below-L exhaustion/reversal signal."""
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for gap in gaps.loc[gaps.gap_width_pct.ge(0.01)].itertuples(index=False):
        part = groups[str(gap.symbol)]
        gap_pos = int(gap.gap_seq)
        hist_pre = part.iloc[gap_pos - 120 : gap_pos].copy()
        exact_history = (
            len(hist_pre) == 120
            and source._valid_daily_rows(hist_pre).all()
            and hist_pre.invalid_step_cum.eq(float(gap.invalid_step_cum)).all()
        )
        if not exact_history:
            continue
        inside = hist_pre.coord_high.ge(float(gap.L)) & hist_pre.coord_low.lt(
            float(gap.U)
        )
        corridor = hist_pre.coord_high.ge(float(gap.L - 0.5 * gap.W)) & (
            hist_pre.coord_low < float(gap.U + 0.5 * gap.W)
        )
        inside_touches = int(inside.sum())
        corridor_touches = int(corridor.sum())
        if inside_touches > 12 or corridor_touches > 20:
            continue
        peak_offset = int(np.nanargmax(hist_pre.coord_high.to_numpy(float)))
        peak = float(hist_pre.coord_high.iloc[peak_offset])
        recent20 = hist_pre.tail(20)
        pre_features = {
            "pre_gap_inside_touch_sessions": inside_touches,
            "pre_gap_corridor_touch_sessions": corridor_touches,
            "pre_peak_to_gap_sessions": int(len(hist_pre) - peak_offset),
            "pre_gap_drawdown_from_120d_peak": float(
                1 - float(part.coord_low.iloc[gap_pos]) / peak
            ),
            "pre_gap_return_20d": float(
                hist_pre.coord_close.iloc[-1] / hist_pre.coord_close.iloc[-20] - 1
            ),
            "pre_gap_range_20d": float(
                recent20.coord_high.max() / recent20.coord_low.min() - 1
            ),
        }
        end = min(len(part), gap_pos + 181)
        path = part.iloc[gap_pos + 1 : end].copy()
        valid = source._valid_daily_rows(path) & path.invalid_step_cum.eq(
            float(gap.invalid_step_cum)
        ).to_numpy(bool)
        bad = first_true(~valid)
        if bad is not None:
            path = path.iloc[:bad]
        if len(path) < 10:
            continue
        touched = source._raw_tick_reached(
            path.high, float(gap.L), path.coordinate_factor
        )
        first_touch = first_true(touched)
        if first_touch is not None:
            path = path.iloc[:first_touch]
        if len(path) < 10:
            continue
        for rel in range(9, len(path)):
            rolling = part.iloc[
                max(0, gap_pos + 1 + rel - 19) : gap_pos + 2 + rel
            ]
            if len(rolling) < 20:
                continue
            current = rolling.iloc[-1]
            previous = rolling.iloc[:-1]
            since_gap = path.iloc[: rel + 1]
            max_depth = 1 - float(since_gap.coord_low.min()) / float(gap.L)
            current_depth = 1 - float(current.coord_close) / float(gap.L)
            low20_offset = int(np.nanargmin(rolling.coord_low.to_numpy(float)))
            days_since_low20 = len(rolling) - 1 - low20_offset
            recovery = float(
                current.coord_close / rolling.coord_low.min() - 1
            )
            ma5_reclaim = bool(
                float(previous.iloc[-1].coord_close)
                <= float(rolling.iloc[-6:-1].coord_close.mean())
                and float(current.coord_close)
                > float(rolling.tail(5).coord_close.mean())
            )
            if not (
                max_depth >= 0.10
                and current_depth >= 0.05
                and 2 <= days_since_low20 <= 10
                and recovery >= 0.03
                and ma5_reclaim
            ):
                continue
            prior_turnover = previous.turnover_fraction.astype(float)
            prior20_mean = float(prior_turnover.mean())
            prior5_mean = float(previous.tail(5).turnover_fraction.mean())
            rows.append(
                {
                    **gap._asdict(),
                    **pre_features,
                    "signal_date": pd.Timestamp(current.trade_date),
                    "signal_time": pd.Timestamp(current.trade_date)
                    + pd.Timedelta(hours=15),
                    "signal_cal_idx": int(current.cal_idx),
                    "signal_coord_close": float(current.coord_close),
                    "swing_low": float(rolling.coord_low.min()),
                    "gap_age": int(rel + 1),
                    "max_depth": max_depth,
                    "current_depth": current_depth,
                    "days_since_low20": days_since_low20,
                    "recovery_from_low20": recovery,
                    "dry3": (
                        float(previous.tail(3).turnover_fraction.mean())
                        / prior20_mean
                        if prior20_mean > 0
                        else math.nan
                    ),
                    "trigger_expansion": (
                        float(current.turnover_fraction) / prior5_mean
                        if prior5_mean > 0
                        else math.nan
                    ),
                    "form": "MA5_RECLAIM",
                }
            )
            break
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).sort_values(
        ["signal_time", "symbol", "L", "gap_id"], kind="mergesort"
    )
    result = result.drop_duplicates(["symbol", "signal_date"], keep="first")
    if result.signal_time.le(result.gap_date).any():
        raise RuntimeError("signal chronology failure")
    return result.reset_index(drop=True)


def build_signals() -> pd.DataFrame:
    daily = source.load_daily_through_2021()
    gaps = pd.read_parquet(source.DAILY_CANDIDATES_2021)
    gaps["gap_date"] = pd.to_datetime(gaps.gap_date)
    gaps = gaps.loc[
        gaps.daily_history_complete
        & gaps.pre_gap_inside_touch_sessions.le(12)
        & gaps.pre_gap_corridor_touch_sessions.le(20)
    ].copy()
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for gap in gaps.itertuples(index=False):
        part = groups[str(gap.symbol)]
        gap_pos = int(gap.gap_seq)
        end = min(len(part), gap_pos + 181)
        path = part.iloc[gap_pos + 1 : end].copy()
        valid = source._valid_daily_rows(path) & path.invalid_step_cum.eq(
            float(gap.invalid_step_cum)
        ).to_numpy(bool)
        bad = first_true(~valid)
        if bad is not None:
            path = path.iloc[:bad]
        if len(path) < 10:
            continue
        touched = source._raw_tick_reached(path.high, float(gap.L), path.coordinate_factor)
        first_touch = first_true(touched)
        if first_touch is not None:
            path = path.iloc[:first_touch]
        if len(path) < 10:
            continue
        for rel in range(9, len(path)):
            hist = part.iloc[max(0, gap_pos + 1 + rel - 19) : gap_pos + 2 + rel]
            if len(hist) < 20:
                continue
            current = hist.iloc[-1]
            previous = hist.iloc[:-1]
            since_gap = path.iloc[: rel + 1]
            max_depth = 1 - float(since_gap.coord_low.min()) / float(gap.L)
            current_depth = 1 - float(current.coord_close) / float(gap.L)
            low20_offset = int(np.nanargmin(hist.coord_low.to_numpy(float)))
            days_since_low20 = len(hist) - 1 - low20_offset
            recovery_from_low20 = (
                float(current.coord_close) / float(hist.coord_low.min()) - 1
            )
            previous_turnover = previous.turnover_fraction.astype(float)
            prior20_mean = float(previous_turnover.mean())
            dry3 = (
                float(previous.tail(3).turnover_fraction.mean()) / prior20_mean
                if prior20_mean > 0
                else math.nan
            )
            expansion = (
                float(current.turnover_fraction)
                / float(previous.tail(5).turnover_fraction.mean())
                if float(previous.tail(5).turnover_fraction.mean()) > 0
                else math.nan
            )
            forms = {
                "BREAK3": float(current.coord_close) > float(previous.tail(3).coord_high.max()),
                "BREAK5": float(current.coord_close) > float(previous.tail(5).coord_high.max()),
                "UPDAY_BREAK1": (
                    float(current.coord_close) > float(current.coord_open)
                    and float(current.coord_close) > float(previous.iloc[-1].coord_high)
                ),
                "MA5_RECLAIM": (
                    float(previous.iloc[-1].coord_close)
                    <= float(hist.iloc[-6:-1].coord_close.mean())
                    and float(current.coord_close) > float(hist.tail(5).coord_close.mean())
                ),
            }
            common = (
                max_depth >= 0.10
                and current_depth >= 0.05
                and 2 <= days_since_low20 <= 10
                and recovery_from_low20 >= 0.03
            )
            if not common or not any(forms.values()):
                continue
            for form, hit in forms.items():
                if hit:
                    rows.append(
                        {
                            "gap_id": gap.gap_id,
                            "symbol": gap.symbol,
                            "board": gap.board,
                            "gap_date": gap.gap_date,
                            "L": float(gap.L),
                            "U": float(gap.U),
                            "W": float(gap.W),
                            "gap_width_pct": float(gap.gap_width_pct),
                            "signal_date": pd.Timestamp(current.trade_date),
                            "signal_cal_idx": int(current.cal_idx),
                            "signal_coord_close": float(current.coord_close),
                            "invalid_step_cum": float(gap.invalid_step_cum),
                            "entry_date": pd.NaT,
                            "entry_cal_idx": math.nan,
                            "entry_coord": math.nan,
                            "swing_low": float(hist.coord_low.min()),
                            "gap_age": int(rel + 1),
                            "max_depth": max_depth,
                            "current_depth": current_depth,
                            "days_since_low20": days_since_low20,
                            "recovery_from_low20": recovery_from_low20,
                            "dry3": dry3,
                            "trigger_expansion": expansion,
                            "form": form,
                            "target_headroom": (
                                float(gap.L) / float(current.coord_close) - 1 - 0.004
                            ),
                            "pre_gap_inside_touch_sessions": int(
                                gap.pre_gap_inside_touch_sessions
                            ),
                            "pre_gap_corridor_touch_sessions": int(
                                gap.pre_gap_corridor_touch_sessions
                            ),
                            "pre_peak_to_gap_sessions": int(
                                gap.pre_peak_to_gap_sessions
                            ),
                            "pre_gap_range_20d": float(gap.pre_gap_range_20d),
                            "pre_gap_drawdown_from_120d_peak": float(
                                gap.pre_gap_drawdown_from_120d_peak
                            ),
                            "pre_gap_return_20d": float(gap.pre_gap_return_20d),
                        }
                    )
            break
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result = result.sort_values(
        ["signal_date", "symbol", "L", "form"], kind="mergesort"
    )
    return result.reset_index(drop=True)


def attach_outcomes(signals: pd.DataFrame) -> pd.DataFrame:
    daily = source.load_daily_through_2021()
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for event in signals.itertuples(index=False):
        part = groups[str(event.symbol)]
        entry_pos = int(np.flatnonzero(part.cal_idx.eq(event.entry_cal_idx).to_numpy())[0])
        for alpha, horizon, stop in itertools.product(
            (0.50, 0.67, 0.80), (5, 10, 20), ("NONE", "SWING_LOW_CLOSE")
        ):
            target = float(event.entry_coord) + alpha * (
                float(event.L) - float(event.entry_coord)
            )
            exit_coord = None
            exit_reason = None
            exit_date = None
            for rel in range(1, horizon + 2):
                pos = entry_pos + rel
                if pos >= len(part):
                    break
                day = part.iloc[pos]
                if (
                    not source._valid_daily_rows(part.iloc[pos : pos + 1]).all()
                    or float(day.invalid_step_cum) != float(part.iloc[entry_pos].invalid_step_cum)
                ):
                    break
                if rel <= horizon and float(day.coord_high) >= target:
                    exit_coord = target
                    exit_reason = "TARGET"
                    exit_date = pd.Timestamp(day.trade_date)
                    break
                if stop == "SWING_LOW_CLOSE" and rel <= horizon:
                    if float(day.coord_close) < float(event.swing_low):
                        next_pos = pos + 1
                        if next_pos < len(part):
                            nxt = part.iloc[next_pos]
                            if source._valid_daily_rows(part.iloc[next_pos : next_pos + 1]).all():
                                exit_coord = float(nxt.coord_open)
                                exit_reason = "STOP"
                                exit_date = pd.Timestamp(nxt.trade_date)
                        break
                if rel == horizon + 1:
                    exit_coord = float(day.coord_open)
                    exit_reason = "TIME"
                    exit_date = pd.Timestamp(day.trade_date)
                    break
            if exit_coord is None:
                continue
            rows.append(
                {
                    **event._asdict(),
                    "alpha": alpha,
                    "horizon": horizon,
                    "stop": stop,
                    "target": target,
                    "exit_date": exit_date,
                    "exit_reason": exit_reason,
                    "net_return": exit_coord / float(event.entry_coord) - 1 - 0.004,
                }
            )
    return pd.DataFrame(rows)


def summarize(outcomes: pd.DataFrame) -> pd.DataFrame:
    group = ["form", "alpha", "horizon", "stop"]
    rows = []
    for key, part in outcomes.groupby(group, sort=True):
        yearly = part.groupby(part.entry_date.dt.year).net_return.mean()
        rows.append(
            {
                **dict(zip(group, key, strict=True)),
                "n": len(part),
                "per_year": part.entry_date.dt.year.value_counts().mean(),
                "mean": part.net_return.mean(),
                "median": part.net_return.median(),
                "win": part.net_return.gt(0).mean(),
                "severe10": part.net_return.le(-0.10).mean(),
                "positive_years": yearly.gt(0).sum(),
                "years": len(yearly),
                "min_year_mean": yearly.min(),
                "target_hit": part.exit_reason.eq("TARGET").mean(),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["mean", "positive_years", "n"], ascending=[False, False, False]
    )


if __name__ == "__main__":
    signals = build_signals()
    signals.to_parquet("/tmp/below_gap_signals.parquet", index=False)
    print("signals", len(signals))
    print(signals.groupby([signals.entry_date.dt.year, "form"]).size().unstack(fill_value=0))
    outcomes = attach_outcomes(signals)
    outcomes.to_parquet("/tmp/below_gap_outcomes.parquet", index=False)
    summary = summarize(outcomes)
    print(summary.head(30).to_string(index=False))
