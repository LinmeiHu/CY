"""Small, causal exit-research primitives; production strategies never import this."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ENTRY_COST = 0.002
EXIT_COST = 0.002


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    family: str
    value: float | int | None = None
    anchor: str | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def anchor_is_causal(available_at: Any, decision_at: Any) -> bool:
    return bool(
        pd.notna(available_at)
        and pd.notna(decision_at)
        and pd.Timestamp(available_at) <= pd.Timestamp(decision_at)
    )


def frozen_atr20(
    daily: pd.DataFrame,
    entry_date: pd.Timestamp,
    lineage: float,
) -> float:
    """Entry-time frozen coordinate ATR20 using only prior completed sessions."""
    prior = daily.loc[
        daily.trade_date.lt(pd.Timestamp(entry_date))
        & daily.invalid_step_cum.eq(float(lineage))
        & daily.hard_valid.fillna(False)
        & daily.history_valid.fillna(False)
        & daily.current_valid.fillna(False)
    ].sort_values("trade_date").tail(21)
    if len(prior) < 21:
        return float("nan")
    previous_close = prior.coord_close.shift(1)
    true_range = pd.concat(
        [
            prior.coord_high - prior.coord_low,
            (prior.coord_high - previous_close).abs(),
            (prior.coord_low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return float(true_range.iloc[-20:].mean())


def path_statistics(
    path: pd.DataFrame,
    *,
    entry_price: float,
    native_net_return: float,
) -> dict[str, Any]:
    if path.empty:
        return {
            "mae": np.nan,
            "mfe": np.nan,
            "time_to_mae": np.nan,
            "time_to_mfe": np.nan,
            "time_underwater": np.nan,
            "mfe_before_mae": np.nan,
            "mfe_before_native_loss": np.nan,
            "maximum_profit_given_back": np.nan,
        }
    ordered = path.sort_values(["trade_date", "cal_idx"], kind="mergesort")
    low_ret = ordered.coord_low.astype(float) / entry_price - 1
    high_ret = ordered.coord_high.astype(float) / entry_price - 1
    close_ret = ordered.coord_close.astype(float) / entry_price - 1
    mae_pos, mfe_pos = int(np.nanargmin(low_ret)), int(np.nanargmax(high_ret))
    mae, mfe = float(low_ret.iloc[mae_pos]), float(high_ret.iloc[mfe_pos])
    result: dict[str, Any] = {
        "mae": mae,
        "mfe": mfe,
        "time_to_mae": int(ordered.cal_idx.iloc[mae_pos] - ordered.cal_idx.iloc[0]),
        "time_to_mfe": int(ordered.cal_idx.iloc[mfe_pos] - ordered.cal_idx.iloc[0]),
        "time_underwater": int(close_ret.lt(0).sum()),
        "mfe_before_mae": bool(mfe_pos < mae_pos),
        "mfe_before_native_loss": float(high_ret.iloc[:].max()) if native_net_return < 0 else np.nan,
        "maximum_profit_given_back": max(0.0, mfe - native_net_return),
    }
    for level in (0.03, 0.05, 0.075, 0.10, 0.125, 0.15, 0.20):
        hit = ordered.loc[low_ret.le(-level)]
        key = f"first_day_below_{str(level).replace('.', '_')}"
        result[key] = None if hit.empty else str(pd.Timestamp(hit.trade_date.iloc[0]).date())
    return result


def _native_result(trade: pd.Series) -> dict[str, Any]:
    return {
        "candidate_exit_date": trade.get("exit_date", pd.NaT),
        "candidate_exit_cal_idx": trade.get("exit_cal_idx", np.nan),
        "candidate_exit_price": trade.get("exit_price", np.nan),
        "candidate_exit_reason": trade.get("exit_reason"),
        "candidate_net_return": trade.get("net_return", np.nan),
        "stop_triggered": False,
        "stop_filled": False,
        "unfilled_stop": False,
        "trigger_date": pd.NaT,
        "fill_date": pd.NaT,
        "gap_through": False,
        "intraday_order_ambiguous": False,
        "capital_release_sessions": 0,
        "anchor_causal": True,
    }


def simulate_daily_exit(
    trade: pd.Series,
    path: pd.DataFrame,
    candidate: Candidate,
    *,
    boundary: float | None = None,
    anchor_available_at: Any = None,
    decision_at: Any = None,
    t_plus_one: bool = True,
) -> dict[str, Any]:
    """Simulate an A-share daily stop without assuming a touched price filled."""
    native = _native_result(trade)
    if pd.isna(trade.get("entry_date")) or path.empty:
        return native
    if candidate.family == "structural":
        native["anchor_causal"] = anchor_is_causal(anchor_available_at, decision_at)
        if not native["anchor_causal"] or boundary is None or not np.isfinite(boundary):
            return native
    entry_date = pd.Timestamp(trade.entry_date)
    entry_idx = int(trade.entry_cal_idx)
    entry_price = float(trade.entry_price)
    native_date = pd.Timestamp(trade.exit_date) if pd.notna(trade.get("exit_date")) else None
    native_reason = str(trade.get("exit_reason") or "")
    pending = False
    triggered_at = pd.NaT
    activation = False
    close_signal_date: pd.Timestamp | None = None

    def finish(row: Any, price: float, reason: str, *, gap: bool, ambiguous: bool = False) -> dict[str, Any]:
        exit_idx = int(row.cal_idx)
        result = dict(native)
        result.update(
            {
                "candidate_exit_date": pd.Timestamp(row.trade_date),
                "candidate_exit_cal_idx": exit_idx,
                "candidate_exit_price": float(price),
                "candidate_exit_reason": reason,
                "candidate_net_return": float(price / entry_price - 1 - ENTRY_COST - EXIT_COST),
                "stop_triggered": True,
                "stop_filled": True,
                "unfilled_stop": False,
                "trigger_date": triggered_at,
                "fill_date": pd.Timestamp(row.trade_date),
                "gap_through": gap,
                "intraday_order_ambiguous": ambiguous,
                "capital_release_sessions": (
                    max(0, int(trade.exit_cal_idx) - exit_idx)
                    if pd.notna(trade.get("exit_cal_idx"))
                    else 0
                ),
            }
        )
        return result

    ordered = path.sort_values(["trade_date", "cal_idx"], kind="mergesort")
    for row in ordered.itertuples(index=False):
        date = pd.Timestamp(row.trade_date)
        sessions = int(row.cal_idx) - entry_idx
        legal_open = bool(row.sellable_open)
        legal_intraday = bool(row.state_valid and row.sellable_open)

        if native_date is not None and date > native_date:
            break
        if native_date is not None and date == native_date and not native_reason.startswith("TARGET_"):
            if pending and legal_open:
                return finish(row, float(row.coord_open), f"SHADOW_STOP_OPEN_{candidate.candidate_id}", gap=True)
            break

        if pending and (not t_plus_one or sessions >= 1) and legal_open:
            return finish(row, float(row.coord_open), f"SHADOW_STOP_OPEN_{candidate.candidate_id}", gap=True)

        if candidate.family == "followthrough":
            if sessions >= int(candidate.value) and float(row.coord_close) < entry_price and close_signal_date is None:
                triggered_at, close_signal_date, pending = date, date, True
            continue

        if candidate.family == "profit_protection":
            if float(row.coord_high) >= entry_price * 1.05:
                activation = True
            active_boundary = entry_price if activation else None
        else:
            active_boundary = boundary
        if active_boundary is None or not np.isfinite(active_boundary):
            continue
        if float(row.coord_low) > float(active_boundary):
            continue
        if not pending:
            pending = True
            triggered_at = date
        if t_plus_one and sessions < 1:
            continue
        if not legal_intraday:
            continue
        gap = float(row.coord_open) <= float(active_boundary)
        price = float(row.coord_open) if gap else float(active_boundary)
        ambiguous = bool(native_date is not None and date == native_date and native_reason.startswith("TARGET_"))
        return finish(
            row,
            price,
            ("SHADOW_STOP_OPEN_" if gap else "TARGET_SHADOW_STOP_INTRADAY_") + candidate.candidate_id,
            gap=gap,
            ambiguous=ambiguous,
        )

    native["stop_triggered"] = bool(pending)
    native["unfilled_stop"] = bool(pending)
    native["trigger_date"] = triggered_at
    return native


def event_metrics(frame: pd.DataFrame, *, severe_threshold: float = -0.10) -> dict[str, Any]:
    if frame.empty:
        return {}
    native = frame.native_net_return.astype(float)
    candidate = frame.candidate_net_return.astype(float)
    winners = native.gt(0)
    severe = native.le(severe_threshold)
    killed = winners & frame.stop_filled.fillna(False) & candidate.lt(native)
    rescued = severe & frame.stop_filled.fillna(False) & candidate.ge(native + 0.02)
    tail_n = max(1, int(math.ceil(len(frame) * 0.05)))
    return {
        "trade_count": int(len(frame)),
        "stop_trigger_count": int(frame.stop_triggered.sum()),
        "stop_fill_count": int(frame.stop_filled.sum()),
        "unfilled_stop_count": int(frame.unfilled_stop.sum()),
        "winner_kill_rate": float(killed.sum() / winners.sum()) if winners.any() else np.nan,
        "loss_rescue_rate": float(rescued.sum() / severe.sum()) if severe.any() else np.nan,
        "severe_loss_rate": float(candidate.le(severe_threshold).mean()),
        "mean_return": float(candidate.mean()),
        "median_return": float(candidate.median()),
        "win_rate": float(candidate.gt(0).mean()),
        "cvar5": float(candidate.nsmallest(tail_n).mean()),
        "max_single_trade_loss": float(candidate.min()),
        "holding_days": float(frame.candidate_holding_sessions.mean()),
        "native_holding_days": float(frame.native_holding_sessions.mean()),
        "time_underwater": float(frame.time_underwater.mean()),
        "gap_through_count": int(frame.gap_through.sum()),
        "intraday_order_ambiguous_count": int(frame.intraday_order_ambiguous.sum()),
    }


def portfolio_metrics(nav: pd.DataFrame, *, nav_column: str, exposure_column: str) -> dict[str, float]:
    ordered = nav.sort_values("trade_date").copy()
    values = ordered[nav_column].astype(float)
    returns = values.pct_change().fillna(values.iloc[0] - 1.0)
    drawdown = values / values.cummax().clip(lower=values.iloc[0]) - 1
    years = max((pd.Timestamp(ordered.trade_date.max()) - pd.Timestamp(ordered.trade_date.min())).days / 365.25, 1 / 252)
    monthly = ordered.assign(month=pd.to_datetime(ordered.trade_date).dt.to_period("M"), r=returns).groupby("month").r.apply(lambda x: float((1 + x).prod() - 1))
    tail_n = max(1, int(math.ceil(len(returns) * 0.05)))
    exposure = ordered[exposure_column].astype(float)
    initial = float(values.iloc[0])
    return {
        "total_return": float(values.iloc[-1] / initial - 1),
        "cagr": float((values.iloc[-1] / initial) ** (1 / years) - 1),
        "max_drawdown": float(drawdown.min()),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * math.sqrt(252)) if returns.std(ddof=1) > 0 else 0.0,
        "worst_5pct_daily_mean": float(returns.nsmallest(tail_n).mean()),
        "worst_month": float(monthly.min()),
        "average_exposure": float(exposure.mean()),
        "p95_exposure": float(exposure.quantile(0.95)),
        "minimum_cash": float((values - exposure).min()),
        "max_gross_exposure_ratio": float((exposure / values).max()),
    }


def canonical_frame_hash(frame: pd.DataFrame) -> str:
    stable = frame.copy()
    for column in stable.select_dtypes(include=["float"]).columns:
        stable[column] = stable[column].round(12)
    payload = stable.sort_index(axis=1).to_csv(index=False, na_rep="NA", lineterminator="\n")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
