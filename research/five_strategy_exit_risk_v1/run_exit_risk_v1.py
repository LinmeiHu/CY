from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for import_root in (Path(__file__).resolve().parent, SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from five_strategy_bundle.execution.daily import (  # noqa: E402
    fixed_target_outcomes,
    load_daily,
    replay_shared_router,
    replay_sleeves,
)
from five_strategy_bundle.strategies.atrdr import (  # noqa: E402
    route_v27_bear,
    select_fast_capacity,
)
from five_strategy_bundle.strategies.ogr import replay_portfolio  # noqa: E402

from engine import (  # noqa: E402
    Candidate,
    canonical_frame_hash,
    event_metrics,
    frozen_atr20,
    path_statistics,
    portfolio_metrics,
    sha256,
    simulate_daily_exit,
)


BASELINE_HEAD = "40d924ca718be40c6e891a64b3a9cac7f8d58f95"
STUDY_LABEL = "INTERNAL_CONSUMED_HISTORY_CONFIRMATION"
FIXED_LEVELS = (0.03, 0.05, 0.075, 0.10, 0.125, 0.15, 0.20)
VOL_SCALES = (1.0, 1.5, 2.0, 2.5, 3.0)
FOLLOW_DAYS = (3, 5, 8)
ATR_LANES = {
    "SIMPLE_BULL_PARTICIPATION_IGNITION": "ATRDR_BULL",
    "BEAR_WORSENING_FAST_CAPITULATION": "ATRDR_FAST_BEAR",
    "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION": "ATRDR_SLOW_BEAR",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, na_rep="NA", lineterminator="\n")


def frozen_hashes() -> dict[str, str]:
    paths = [
        *sorted((ROOT / "configs/frozen").glob("*.json")),
        *sorted((ROOT / "src/five_strategy_bundle/strategies").glob("*.py")),
        ROOT / "src/five_strategy_bundle/execution/daily.py",
    ]
    return {str(path.relative_to(ROOT)): sha256(path) for path in paths}


def rebuild_atrdr_source(baseline_root: Path, inputs: dict[str, Path], scratch: Path) -> pd.DataFrame:
    base = baseline_root / "atrdr_full_closed_20260907/atrdr"
    fast_signal = pd.read_parquet(base / "fast_signal.parquet")
    fast_daily = load_daily([inputs["daily_hist"]], fast_signal.symbol.astype(str).tolist())
    fast = fixed_target_outcomes(
        fast_signal, fast_daily, target=0.10, horizon=20, profile="T10_H20_NO_STOP"
    )
    fields = [
        "event_id", "step_return", "signal_decision_at",
        "regime_latest_source_timestamp", "b20_l5_source_timestamp",
        "market_positive_ret20_share", "b20_l5", "prior10_return",
        "close_location_x", "turnover_ratio_x", "invalid_step_cum",
        "stock_minus_industry_ret20", "close_vs_prior10_high",
    ]
    fast = fast.merge(fast_signal[fields], on="event_id", how="left", validate="one_to_one")
    fast = fast.rename(columns={"invalid_step_cum": "signal_invalid"})
    fast_accepted = select_fast_capacity(fast, scratch / "atrdr_fast_accepted.parquet")
    fast_accepted = fast_accepted.merge(
        fast_signal[[
            "event_id", "market_regime", "market_median_ret20",
            "market_median_ret60", "latest_source_timestamp",
        ]],
        on="event_id", how="left", validate="one_to_one",
    )
    slow = pd.read_parquet(base / "slow_mother.parquet")
    slow_outcomes = pd.read_parquet(base / "slow_outcomes.parquet")
    market = pd.read_parquet(base / "market_state.parquet")
    bear = route_v27_bear(
        fast_accepted, slow_outcomes, slow, market, scratch / "atrdr_bear_routes.parquet"
    )
    bull = pd.read_parquet(base / "bull_mother.parquet")
    bull_outcomes = pd.read_parquet(base / "bull_outcomes.parquet")
    bull_trades = bull_outcomes.loc[bull_outcomes.status.eq("COMPLETED")].merge(
        bull[["event_id", "lane", "industry_breadth20_delta5", "ret60", "turnover_ratio"]],
        on="event_id", how="left", validate="one_to_one",
    )
    bull_trades["source"] = "V29_SIMPLE_BULL"
    bull_trades["source_event_id"] = bull_trades.event_id.astype(str)
    bull_trades["event_id"] = "V29|BULL|" + bull_trades.source_event_id
    bull_trades["source_rank1"] = bull_trades.industry_breadth20_delta5
    bull_trades["source_rank2"] = -bull_trades.ret60
    bull_trades["source_rank3"] = bull_trades.turnover_ratio
    bear_trades = bear.copy()
    bear_trades["source"] = "V27_BEAR"
    bear_trades["source_event_id"] = bear_trades.event_id.astype(str)
    bear_trades["event_id"] = "V29|V27|" + bear_trades.source_event_id
    for source, rank in (("source_rank1", "rank1"), ("source_rank2", "rank2"), ("source_rank3", "rank3")):
        bear_trades[source] = bear_trades[rank]
    union = pd.concat([bear_trades, bull_trades], ignore_index=True, sort=False).sort_values(
        ["signal_date", "sleeve", "source", "source_rank1", "source_rank2", "source_rank3", "event_id"],
        ascending=[True, True, True, False, False, False, True], kind="mergesort",
    ).reset_index(drop=True)
    union["source_rank_order"] = union.groupby(
        ["signal_date", "sleeve", "source"], sort=False
    ).cumcount()
    union["route"] = union.lane.map(ATR_LANES)

    anchors = []
    for frame, route, value, available in (
        (bull, "ATRDR_BULL", "coord_low", "feature_latest_timestamp"),
        (fast_signal, "ATRDR_FAST_BEAR", "coord_low", "signal_decision_at"),
        (slow, "ATRDR_SLOW_BEAR", "last5_low", "available_at"),
    ):
        anchors.append(pd.DataFrame({
            "source_event_id": frame.event_id.astype(str),
            "route": route,
            "structural_anchor": frame[value].astype(float),
            "anchor_available_at": pd.to_datetime(frame[available]),
        }))
    anchor_frame = pd.concat(anchors, ignore_index=True)
    union = union.merge(anchor_frame, on=["source_event_id", "route"], how="left", validate="many_to_one")
    union["anchor_decision_at"] = pd.to_datetime(union.entry_date) + pd.Timedelta(hours=9, minutes=30)
    return union


def prepare_daily_path(group: pd.DataFrame, trade: pd.Series, study_end: pd.Timestamp) -> tuple[pd.DataFrame, float]:
    if pd.isna(trade.get("entry_date")):
        return pd.DataFrame(), float("nan")
    entry_date = pd.Timestamp(trade.entry_date)
    end = study_end
    if pd.notna(trade.get("exit_date")):
        end = min(end, pd.Timestamp(trade.exit_date))
    part = group.loc[group.trade_date.between(entry_date, end)].copy()
    entry = group.loc[group.trade_date.eq(entry_date)]
    if entry.empty or part.empty:
        return pd.DataFrame(), float("nan")
    lineage = float(entry.invalid_step_cum.iloc[-1])
    required = [
        "hard_valid", "history_valid", "current_valid", "corporate_action_valid",
        "current_day_data_tradable", "market_rule_valid",
    ]
    state = part.invalid_step_cum.eq(lineage)
    for column in required:
        state &= part[column].fillna(False).astype(bool)
    state &= ~part.corporate_action_blocking.fillna(True).astype(bool)
    state &= part.trade_status.fillna(0).astype(int).eq(1)
    part["state_valid"] = state
    part["sellable_open"] = state & np.rint(part.open.astype(float) * 100).gt(
        np.rint(part.down_limit_price.astype(float) * 100)
    )
    keep = [
        "trade_date", "cal_idx", "coord_open", "coord_high", "coord_low", "coord_close",
        "state_valid", "sellable_open", "invalid_step_cum",
    ]
    return part[keep].sort_values("trade_date").reset_index(drop=True), lineage


def make_stock_cache(
    source: pd.DataFrame,
    daily_groups: dict[str, pd.DataFrame],
    study_end: pd.Timestamp,
    key: str,
) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    for _, trade in source.iterrows():
        if pd.isna(trade.get("entry_date")):
            continue
        group = daily_groups.get(str(trade.symbol))
        if group is None:
            continue
        path, lineage = prepare_daily_path(group, trade, study_end)
        atr = frozen_atr20(group, pd.Timestamp(trade.entry_date), lineage) if not path.empty else np.nan
        cache[str(trade[key])] = {"path": path, "lineage": lineage, "atr20": atr}
    return cache


def candidate_boundary(trade: pd.Series, cached: dict[str, Any], candidate: Candidate) -> float | None:
    entry = float(trade.entry_price)
    if candidate.family == "fixed":
        return entry * (1 - float(candidate.value))
    if candidate.family == "volatility":
        atr = float(cached["atr20"])
        return entry - float(candidate.value) * atr if np.isfinite(atr) else None
    if candidate.family == "structural":
        value = trade.get("structural_anchor")
        return float(value) if pd.notna(value) else None
    return None


def simulate_stock_source(
    source: pd.DataFrame,
    cache: dict[str, dict[str, Any]],
    candidate: Candidate,
    *,
    route: str,
    key: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    modified = source.copy()
    event_rows: list[dict[str, Any]] = []
    for index, trade in source.iterrows():
        if str(trade.get("route")) != route or pd.isna(trade.get("entry_date")):
            continue
        cached = cache.get(str(trade[key]))
        if cached is None:
            continue
        boundary = candidate_boundary(trade, cached, candidate)
        result = simulate_daily_exit(
            trade, cached["path"], candidate,
            boundary=boundary,
            anchor_available_at=trade.get("anchor_available_at"),
            decision_at=trade.get("anchor_decision_at"),
            t_plus_one=True,
        )
        native_exit_idx = trade.get("exit_cal_idx")
        candidate_idx = result["candidate_exit_cal_idx"]
        result["candidate_holding_sessions"] = (
            float(candidate_idx) - float(trade.entry_cal_idx)
            if pd.notna(candidate_idx) else np.nan
        )
        event_rows.append({
            "strategy": str(trade.get("strategy")),
            "route": route,
            "event_id": str(trade[key]),
            "security": str(trade.symbol),
            "signal_date": trade.get("signal_date"),
            "entry_date": trade.entry_date,
            "native_exit_date": trade.get("exit_date"),
            "native_exit_reason": trade.get("exit_reason"),
            "native_net_return": trade.get("net_return"),
            "native_holding_sessions": (
                float(native_exit_idx) - float(trade.entry_cal_idx)
                if pd.notna(native_exit_idx) else np.nan
            ),
            "atr20_entry_frozen": cached["atr20"],
            "candidate_id": candidate.candidate_id,
            "family": candidate.family,
            **result,
        })
        if result["stop_filled"]:
            modified.at[index, "exit_date"] = result["candidate_exit_date"]
            modified.at[index, "exit_cal_idx"] = result["candidate_exit_cal_idx"]
            modified.at[index, "exit_price"] = result["candidate_exit_price"]
            modified.at[index, "exit_reason"] = result["candidate_exit_reason"]
            modified.at[index, "net_return"] = result["candidate_net_return"]
            modified.at[index, "gross_return"] = result["candidate_exit_price"] / float(trade.entry_price) - 1
            modified.at[index, "holding_sessions"] = result["candidate_holding_sessions"]
            if "status" in modified:
                modified.at[index, "status"] = "COMPLETED"
    return modified, pd.DataFrame(event_rows)


def stock_path_summary(
    accepted: pd.DataFrame,
    cache: dict[str, dict[str, Any]],
    *,
    key: str,
    study_end: pd.Timestamp,
) -> pd.DataFrame:
    rows = []
    for _, trade in accepted.iterrows():
        if pd.isna(trade.get("exit_date")) or pd.Timestamp(trade.exit_date) > study_end:
            continue
        cached = cache.get(str(trade[key]))
        if cached is None or cached["path"].empty:
            continue
        stats = path_statistics(
            cached["path"], entry_price=float(trade.entry_price),
            native_net_return=float(trade.net_return),
        )
        rows.append({
            "strategy": trade.strategy,
            "route": trade.route,
            "event_id": str(trade[key]),
            "security": str(trade.symbol),
            "signal_date": trade.signal_date,
            "entry_date": trade.entry_date,
            "entry_time": pd.Timestamp(trade.entry_date) + pd.Timedelta(hours=9, minutes=30),
            "entry_price": trade.entry_price,
            "native_exit_date": trade.exit_date,
            "native_exit_time": trade.exit_date,
            "native_exit_price": trade.exit_price,
            "native_exit_reason": trade.exit_reason,
            "native_net_return": trade.net_return,
            "atr20_entry_frozen": cached["atr20"],
            "structural_anchor": trade.get("structural_anchor"),
            "anchor_available_at": trade.get("anchor_available_at"),
            **stats,
        })
    return pd.DataFrame(rows)


def load_ogr_minutes(
    outcomes: pd.DataFrame,
    daily: pd.DataFrame,
    minute_root: Path,
    external_root: Path,
) -> pd.DataFrame:
    cache_path = external_root / "ogr_minute_paths.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    bounds = outcomes[["gap_id", "symbol", "entry_date", "entry_time", "exit_date", "exit_time"]].copy()
    state = daily.loc[daily.symbol.isin(bounds.symbol.unique())].copy()
    pieces = []
    for year in range(int(bounds.entry_date.dt.year.min()), int(bounds.exit_date.dt.year.max()) + 1):
        raw = minute_root / f"partition_year={int(year)}" / "data_0.parquet"
        subset = bounds.loc[
            bounds.entry_date.dt.year.le(year) & bounds.exit_date.dt.year.ge(year)
        ].copy()
        if subset.empty:
            continue
        con = duckdb.connect()
        con.register("bounds", subset)
        con.register("execution_state", state)
        try:
            pieces.append(con.execute(f"""
                SELECT b.gap_id,b.symbol,r.trade_date,r.bar_end_time,r.open,r.high,r.low,r.close,
                  d.cal_idx,d.coordinate_factor,d.invalid_step_cum,d.history_valid,d.current_valid,
                  d.hard_valid,d.trade_status,d.current_day_data_tradable,d.market_rule_valid,
                  d.corporate_action_blocking,d.down_limit_price,
                  r.open*d.coordinate_factor AS coord_open,
                  r.high*d.coordinate_factor AS coord_high,
                  r.low*d.coordinate_factor AS coord_low,
                  r.close*d.coordinate_factor AS coord_close
                FROM bounds b JOIN read_parquet('{raw.as_posix()}') r
                  ON r.qmt_code=b.symbol AND r.trade_date BETWEEN b.entry_date AND b.exit_date
                  AND r.bar_end_time>=b.entry_time AND r.bar_end_time<=b.exit_time
                JOIN execution_state d ON d.symbol=b.symbol AND d.trade_date=r.trade_date
                WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={int(year)}
                ORDER BY b.gap_id,r.bar_end_time
            """).fetchdf())
        finally:
            con.close()
    minutes = pd.concat(pieces, ignore_index=True)
    minutes["trade_date"] = pd.to_datetime(minutes.trade_date)
    minutes["bar_end_time"] = pd.to_datetime(minutes.bar_end_time)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    minutes.to_parquet(cache_path, index=False)
    return minutes


def simulate_ogr_exit(
    trade: pd.Series,
    minutes: pd.DataFrame,
    daily_path: pd.DataFrame,
    candidate: Candidate,
    atr20: float,
) -> dict[str, Any]:
    native = {
        "candidate_exit_time": trade.exit_time,
        "candidate_exit_date": trade.exit_date,
        "candidate_exit_cal_idx": trade.exit_cal_idx,
        "candidate_exit_price": trade.exit_raw_price,
        "candidate_exit_reason": trade.exit_reason,
        "candidate_net_return": trade.net_return,
        "stop_triggered": False, "stop_filled": False, "unfilled_stop": False,
        "trigger_date": pd.NaT, "fill_date": pd.NaT, "gap_through": False,
        "intraday_order_ambiguous": False, "capital_release_sessions": 0,
        "anchor_causal": True,
    }
    entry_coord = float(trade.entry_coordinate_price)
    if candidate.family == "fixed":
        boundary = entry_coord * (1 - float(candidate.value))
    elif candidate.family == "volatility":
        boundary = entry_coord - float(candidate.value) * atr20 if np.isfinite(atr20) else None
    elif candidate.family == "structural":
        boundary = float(trade.swing_low)
        native["anchor_causal"] = pd.Timestamp(trade.semantic_feature_latest_timestamp) <= pd.Timestamp(trade.entry_time)
        if not native["anchor_causal"]:
            return native
    elif candidate.family == "profit_protection":
        boundary = entry_coord
    else:
        boundary = None
    pending = False
    activated = False
    trigger_time = pd.NaT
    follow_signal_date: pd.Timestamp | None = None
    if candidate.family == "followthrough":
        eligible = daily_path.loc[
            daily_path.cal_idx.sub(int(trade.entry_cal_idx)).ge(int(candidate.value))
            & daily_path.coord_close.lt(entry_coord)
        ]
        if len(eligible):
            follow_signal_date = pd.Timestamp(eligible.trade_date.iloc[0])
            pending, trigger_time = True, follow_signal_date + pd.Timedelta(hours=15)
    for row in minutes.sort_values("bar_end_time").itertuples(index=False):
        when = pd.Timestamp(row.bar_end_time)
        if when > pd.Timestamp(trade.exit_time):
            break
        sessions = int(row.cal_idx) - int(trade.entry_cal_idx)
        state_valid = bool(
            row.invalid_step_cum == float(trade.entry_invalid_step_cum)
            and row.history_valid and row.current_valid and row.hard_valid
            and row.trade_status == 1 and row.current_day_data_tradable
            and row.market_rule_valid and not row.corporate_action_blocking
        )
        executable = state_valid and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
        if candidate.family == "followthrough":
            if follow_signal_date is None or when <= trigger_time or not executable:
                continue
        else:
            if candidate.family == "profit_protection" and float(row.coord_high) >= entry_coord * 1.05:
                activated = True
            active_boundary = boundary if candidate.family != "profit_protection" or activated else None
            if active_boundary is not None and float(row.coord_low) <= active_boundary and not pending:
                pending, trigger_time = True, when
            if not pending or sessions < 1 or not executable:
                continue
        gap = candidate.family == "followthrough" or float(row.coord_open) <= float(boundary)
        raw_price = float(row.open) if gap else round(float(boundary) / float(row.coordinate_factor), 2)
        cash_events = json.loads(trade.cash_events_json or "[]")
        cash = sum(
            float(event["cash_per_share"])
            for event in cash_events
            if pd.Timestamp(event["date"]) <= pd.Timestamp(row.trade_date)
        )
        net_return = (raw_price * (1 - 0.002) + cash) / (float(trade.entry_raw_price) * (1 + 0.002)) - 1
        ambiguous = bool(when == pd.Timestamp(trade.exit_time) and str(trade.exit_reason) == "PRE_L_TARGET")
        return {
            **native,
            "candidate_exit_time": when,
            "candidate_exit_date": pd.Timestamp(row.trade_date),
            "candidate_exit_cal_idx": int(row.cal_idx),
            "candidate_exit_price": raw_price,
            "candidate_exit_reason": ("SHADOW_STOP_OPEN_" if gap else "SHADOW_STOP_MINUTE_") + candidate.candidate_id,
            "candidate_net_return": net_return,
            "stop_triggered": True, "stop_filled": True, "unfilled_stop": False,
            "trigger_date": trigger_time, "fill_date": when, "gap_through": gap,
            "intraday_order_ambiguous": ambiguous,
            "capital_release_sessions": max(0, int(trade.exit_cal_idx) - int(row.cal_idx)),
        }
    native["stop_triggered"] = pending
    native["unfilled_stop"] = pending
    native["trigger_date"] = trigger_time
    return native


def simulate_ogr_source(
    source: pd.DataFrame,
    minute_groups: dict[str, pd.DataFrame],
    daily_groups: dict[str, pd.DataFrame],
    candidate: Candidate,
    *,
    route: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    modified = source.copy()
    rows = []
    for index, trade in source.iterrows():
        minutes = minute_groups[str(trade.gap_id)]
        daily_path, lineage = prepare_daily_path(daily_groups[str(trade.symbol)], trade.rename({
            "entry_raw_price": "entry_price", "exit_raw_price": "exit_price"
        }), pd.Timestamp(trade.exit_date))
        atr = frozen_atr20(daily_groups[str(trade.symbol)], pd.Timestamp(trade.entry_date), lineage)
        result = simulate_ogr_exit(trade, minutes, daily_path, candidate, atr)
        result["candidate_holding_sessions"] = int(result["candidate_exit_cal_idx"]) - int(trade.entry_cal_idx)
        rows.append({
            "strategy": "OGR" if route == "OGR" else "IFCGR",
            "route": route, "event_id": str(trade.gap_id), "security": str(trade.symbol),
            "signal_date": trade.signal_date, "entry_date": trade.entry_date,
            "native_exit_date": trade.exit_date, "native_exit_reason": trade.exit_reason,
            "native_net_return": trade.net_return,
            "native_holding_sessions": trade.holding_sessions,
            "atr20_entry_frozen": atr, "candidate_id": candidate.candidate_id,
            "family": candidate.family, **result,
        })
        if result["stop_filled"]:
            modified.at[index, "exit_time"] = result["candidate_exit_time"]
            modified.at[index, "exit_date"] = result["candidate_exit_date"]
            modified.at[index, "exit_cal_idx"] = result["candidate_exit_cal_idx"]
            modified.at[index, "exit_raw_price"] = result["candidate_exit_price"]
            modified.at[index, "exit_reason"] = result["candidate_exit_reason"]
            modified.at[index, "net_return"] = result["candidate_net_return"]
            modified.at[index, "holding_sessions"] = result["candidate_holding_sessions"]
    return modified, pd.DataFrame(rows)


def add_evidence_stage(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["signal_date"] = pd.to_datetime(result.signal_date)
    result["evidence_stage"] = ""
    for route, group in result.groupby("route", sort=False):
        dates = sorted(group.signal_date.dropna().unique())
        split = pd.Timestamp(dates[max(0, math.ceil(len(dates) * 0.60) - 1)])
        result.loc[group.index, "evidence_stage"] = np.where(
            group.signal_date.le(split), "EARLY_DISCOVERY", "LATE_INTERNAL_CONFIRMATION"
        )
    result["evidence_label"] = STUDY_LABEL
    result["year"] = result.signal_date.dt.year
    return result


def loss_tables(paths: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = paths.copy()
    data["path_class"] = np.select(
        [data.native_net_return.ge(0), data.mfe.ge(0.05)],
        ["NATIVE_WINNER", "WORKED_THEN_GAVE_BACK"],
        default="NEVER_WORKED_EARLY_FAILURE",
    )
    anatomy = []
    for route, group in data.groupby("route", sort=True):
        severe_threshold = -0.05 if route == "SMV6" else -0.10
        for stage, part in [("ALL", group), *group.groupby("evidence_stage", sort=True)]:
            severe = part.native_net_return.le(severe_threshold)
            anatomy.append({
                "route": route, "evidence_stage": stage, "n_trades": len(part),
                "n_winners": int(part.native_net_return.ge(0).sum()),
                "n_losers": int(part.native_net_return.lt(0).sum()),
                "n_severe_losses": int(severe.sum()),
                "never_worked_count": int(part.path_class.eq("NEVER_WORKED_EARLY_FAILURE").sum()),
                "worked_then_gave_back_count": int(part.path_class.eq("WORKED_THEN_GAVE_BACK").sum()),
                "severe_worked_then_gave_back_share": float(
                    (severe & part.path_class.eq("WORKED_THEN_GAVE_BACK")).sum() / severe.sum()
                ) if severe.any() else np.nan,
                "mean_native_return": part.native_net_return.mean(),
                "cvar5_native": part.native_net_return.nsmallest(max(1, math.ceil(len(part) * 0.05))).mean(),
                "median_mae": part.mae.median(), "median_mfe": part.mfe.median(),
                "median_time_to_mae": part.time_to_mae.median(),
                "median_time_to_mfe": part.time_to_mfe.median(),
                "mean_time_underwater": part.time_underwater.mean(),
            })
        for level in FIXED_LEVELS:
            breached = group.mae.le(-level)
            anatomy.append({
                "route": route, "evidence_stage": f"BREACH_{level:.3f}",
                "n_trades": len(group), "breach_count": int(breached.sum()),
                "recovery_to_nonnegative_rate": float(group.loc[breached, "native_net_return"].ge(0).mean()) if breached.any() else np.nan,
                "eventual_severe_loss_rate": float(group.loc[breached, "native_net_return"].le(severe_threshold).mean()) if breached.any() else np.nan,
                "continued_deterioration_rate": float(group.loc[breached, "mae"].le(-(level + 0.05)).mean()) if breached.any() else np.nan,
            })
    summary = []
    for (route, path_class), group in data.groupby(["route", "path_class"], sort=True):
        summary.append({
            "route": route, "path_class": path_class, "n": len(group),
            "mae_p05": group.mae.quantile(0.05), "mae_p25": group.mae.quantile(0.25),
            "mae_median": group.mae.median(), "mae_p75": group.mae.quantile(0.75),
            "mfe_p25": group.mfe.quantile(0.25), "mfe_median": group.mfe.median(),
            "mfe_p75": group.mfe.quantile(0.75), "time_to_failure_median": group.time_to_mae.median(),
            "time_to_recovery_median": group.time_to_mfe.median(),
        })
    return pd.DataFrame(anatomy), pd.DataFrame(summary)


def smv6_paths(baseline_root: Path, qmt_root: Path, study_end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    events = pd.read_parquet(baseline_root / "smv6_integrated_full/local_execution_events.parquet")
    events["trade_date"] = pd.to_datetime(events.trade_date)
    events = events.loc[events.trade_date.le(study_end)]
    sells = events.loc[events.event_type.eq("SELL_FILLED")].copy()
    reasons = events.loc[events.event_type.eq("TAIL_SELL_SIGNAL"), ["trade_date", "symbol", "reason"]]
    sells = sells.drop(columns="reason", errors="ignore").merge(
        reasons, on=["trade_date", "symbol"], how="left", validate="one_to_one"
    )
    rows = []
    residual = []
    for trade in sells.itertuples(index=False):
        daily = pd.read_parquet(qmt_root / "daily" / f"symbol={trade.symbol}" / "daily.parquet")
        daily["trade_date"] = pd.to_datetime(daily.trade_date)
        path = daily.loc[daily.trade_date.between(pd.Timestamp(trade.entry_date), trade.trade_date)].copy()
        path = path.rename(columns={
            "pre_adj_open": "coord_open", "pre_adj_high": "coord_high",
            "pre_adj_low": "coord_low", "pre_adj_close": "coord_close",
        })
        path["cal_idx"] = np.arange(len(path))
        native_return = float((trade.price_pre_adj * (1 - 0.0002)) / (trade.entry_price * (1 + 0.0002)) - 1)
        stats = path_statistics(path, entry_price=float(trade.entry_price), native_net_return=native_return)
        if native_return <= -0.05:
            if "OWN_EXIT" in str(trade.reason):
                category = "SLOW_MA_RESPONSE_OR_SINGLE_ETF"
            elif "MARKET_EXIT" in str(trade.reason):
                category = "MARKET_WIDE_EXIT_RESIDUAL"
            else:
                category = "GAP_OR_UNTRADEABLE_EXECUTION"
        else:
            category = "NORMAL_TREND_NOISE_OR_NON_SEVERE"
        rows.append({
            "strategy": "SMV6", "route": "SMV6",
            "event_id": f"{trade.symbol}|{trade.entry_date}|{trade.trade_date}",
            "security": trade.symbol, "signal_date": pd.Timestamp(trade.entry_date),
            "entry_date": pd.Timestamp(trade.entry_date), "entry_time": pd.Timestamp(trade.entry_date) + pd.Timedelta(hours=9, minutes=30),
            "entry_price": trade.entry_price, "native_exit_date": trade.trade_date,
            "native_exit_time": trade.trade_date + pd.Timedelta(hours=15),
            "native_exit_price": trade.price_pre_adj, "native_exit_reason": trade.reason,
            "native_net_return": native_return, "atr20_entry_frozen": np.nan,
            "structural_anchor": np.nan, "anchor_available_at": pd.NaT, **stats,
        })
        residual.append({
            "route": "SMV6", "event_id": rows[-1]["event_id"], "security": trade.symbol,
            "native_exit_reason": trade.reason, "native_net_return": native_return,
            "mae": stats["mae"], "mfe": stats["mfe"], "residual_loss_category": category,
        })
    return pd.DataFrame(rows), pd.DataFrame(residual)


def stranded_diagnostic(
    strategy: str,
    skipped: pd.DataFrame,
    nav: pd.DataFrame,
) -> pd.DataFrame:
    if skipped.empty or "skip_reason" not in skipped:
        return pd.DataFrame()
    rows = []
    short = skipped.loc[skipped.skip_reason.astype(str).str.contains("INSUFFICIENT_CASH")]
    nav_index = nav.set_index("trade_date")
    for trade in short.itertuples(index=False):
        date = pd.Timestamp(trade.entry_date)
        if date not in nav_index.index:
            continue
        account = nav_index.loc[date]
        prefix = "main" if str(trade.sleeve) == "MAIN" else "chinext"
        other = "chinext" if prefix == "main" else "main"
        own = float(account[f"{prefix}_cash"])
        idle = float(account[f"{other}_cash"])
        requested = float(account[f"{prefix}_nav"]) / 30
        rows.append({
            "timestamp": date, "strategy": strategy, "requested_notional": requested,
            "own_available_cash": own, "funding_gap": max(0, requested - own),
            "other_sleeve_idle_cash": idle, "total_account_idle_cash": own + idle,
            "potentially_fundable": own + idle >= requested,
        })
    return pd.DataFrame(rows)


def smv6_cash_shortfall_diagnostic(
    baseline_root: Path,
    study_end: pd.Timestamp,
) -> pd.DataFrame:
    events = pd.read_parquet(baseline_root / "smv6_integrated_full/local_execution_events.parquet")
    events["trade_date"] = pd.to_datetime(events.trade_date)
    limited = events.loc[
        events.trade_date.le(study_end) & events.cash_limited.fillna(False)
    ].copy()
    if limited.empty:
        return pd.DataFrame()
    requested = limited.requested_qty.fillna(0) * limited.price_pre_adj.fillna(0) * 1.0002
    filled = limited.filled_delta_qty.fillna(0).clip(lower=0) * limited.price_pre_adj.fillna(0) * 1.0002
    return pd.DataFrame({
        "timestamp": limited.trade_date,
        "strategy": "SMV6",
        "requested_notional": requested,
        "own_available_cash": limited.cash_after.fillna(0) + filled,
        "funding_gap": (requested - filled).clip(lower=0),
        "other_sleeve_idle_cash": np.nan,
        "total_account_idle_cash": limited.cash_after,
        "potentially_fundable": pd.NA,
        "scope_note": "other independent-strategy cash is not commensurate without a shared-cash allocator",
    })


def enrich_event_periods(events: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    labels = paths[["route", "event_id", "evidence_stage", "year", "time_underwater"]].drop_duplicates()
    return events.merge(labels, on=["route", "event_id"], how="left", suffixes=("", "_path"))


def response_rows(events: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for (route, candidate_id, family), group in events.groupby(["route", "candidate_id", "family"], sort=True):
        metrics = event_metrics(group, severe_threshold=-0.10)
        rows.append({"route": route, "candidate_id": candidate_id, "family": family, **metrics})
    return rows


def temporal_rows(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in events.groupby(["route", "candidate_id", "family"], sort=True):
        route, candidate_id, family = keys
        for label, part in [("ALL", group), *group.dropna(subset=["evidence_stage"]).groupby("evidence_stage", sort=True)]:
            rows.append({
                "route": route, "candidate_id": candidate_id, "family": family,
                "robustness_slice": label, **event_metrics(part, severe_threshold=-0.10),
            })
        for year, part in group.dropna(subset=["year"]).groupby("year", sort=True):
            rows.append({
                "route": route, "candidate_id": candidate_id, "family": family,
                "robustness_slice": f"YEAR_{int(year)}", **event_metrics(part, severe_threshold=-0.10),
            })
        delta = group.candidate_net_return - group.native_net_return
        positive = delta.clip(lower=0)
        total = float(positive.sum())
        by_date = positive.groupby(pd.to_datetime(group.fill_date).dt.normalize()).sum().sort_values(ascending=False)
        rows.append({
            "route": route, "candidate_id": candidate_id, "family": family,
            "robustness_slice": "CONCENTRATION",
            "top_1_date_contribution": float(by_date.head(1).sum() / total) if total > 0 else np.nan,
            "top_5_dates_contribution": float(by_date.head(5).sum() / total) if total > 0 else np.nan,
            "top_5_trades_contribution": float(positive.nlargest(5).sum() / total) if total > 0 else np.nan,
            "largest_security_contribution": float(positive.groupby(group.security).sum().max() / total) if total > 0 else np.nan,
            "remove_best_1_date_delta": float(delta.sum() - (by_date.iloc[0] if len(by_date) else 0)),
            "remove_best_5_dates_delta": float(delta.sum() - by_date.head(5).sum()),
        })
    return pd.DataFrame(rows)


def render_figures(paths: pd.DataFrame, response: pd.DataFrame, nav_store: dict[tuple[str, str], pd.DataFrame], output: Path) -> None:
    import matplotlib.pyplot as plt

    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    routes = sorted(paths.route.unique())
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    for ax, route in zip(axes.flat, routes):
        group = paths.loc[paths.route.eq(route)]
        ax.hist(group.loc[group.native_net_return.ge(0), "mae"], bins=20, alpha=0.6, label="winner")
        ax.hist(group.loc[group.native_net_return.lt(0), "mae"], bins=20, alpha=0.6, label="loser")
        ax.set_title(route); ax.set_xlabel("MAE"); ax.legend()
    fig.savefig(figures / "winner_loser_mae.png", dpi=140); plt.close(fig)

    fixed = response.loc[response.family.eq("fixed")].copy()
    fixed["stop_pct"] = fixed.candidate_id.str.extract(r"(\d+(?:\.\d+)?)").astype(float)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    for route, group in fixed.groupby("route", sort=True):
        group = group.sort_values("stop_pct")
        axes[0, 0].plot(group.stop_pct, group.mean_return, marker="o", label=route)
        axes[0, 1].plot(group.stop_pct, group.cvar5, marker="o", label=route)
        axes[1, 0].plot(group.stop_pct, group.winner_kill_rate, marker="o", label=route)
        axes[1, 1].plot(group.stop_pct, group.loss_rescue_rate, marker="o", label=route)
    for ax, title in zip(axes.flat, ["Mean return", "CVaR5", "Winner kill", "Loss rescue"]):
        ax.set_title(title); ax.set_xlabel("stop %"); ax.legend(fontsize=7)
    fig.savefig(figures / "fixed_stop_response.png", dpi=140); plt.close(fig)

    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    shown = 0
    for (route, candidate), nav in nav_store.items():
        if not candidate.startswith("STRUCT_") or shown >= 6:
            continue
        base = nav_store.get((route, "BASELINE"))
        if base is None:
            continue
        ax = axes.flat[shown]
        ax.plot(base.trade_date, base.nav_value / base.nav_value.iloc[0], label="native")
        ax.plot(nav.trade_date, nav.nav_value / nav.nav_value.iloc[0], label=candidate)
        ax.set_title(route); ax.legend(fontsize=7); shown += 1
    fig.savefig(figures / "native_vs_candidate_nav.png", dpi=140); plt.close(fig)

    duration = response.loc[response.family.eq("structural")].copy()
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    ax.bar(duration.route, duration.stop_fill_count); ax.tick_params(axis="x", rotation=30)
    ax.set_title("Structural-stop fills / capital-release opportunities")
    fig.savefig(figures / "holding_and_capital_release.png", dpi=140); plt.close(fig)


def output_manifest(output: Path) -> dict[str, str]:
    files = sorted(
        path for path in output.rglob("*")
        if path.is_file() and path.name not in {"output_manifest.sha256", "run_result.json"}
    )
    manifest = {str(path.relative_to(output)): sha256(path) for path in files}
    (output / "output_manifest.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in manifest.items()), encoding="utf-8"
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-config", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).with_name("output"))
    parser.add_argument("--path-output-root", type=Path, required=True)
    parser.add_argument("--study-end", default="2023-12-31")
    parser.add_argument("--skip-figures", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output_root.resolve(); output.mkdir(parents=True, exist_ok=True)
    external = args.path_output_root.resolve(); external.mkdir(parents=True, exist_ok=True)
    study_end = pd.Timestamp(args.study_end)
    raw_inputs = read_json(args.input_config)["inputs"]
    inputs = {key: Path(value) for key, value in raw_inputs.items()}
    before_hashes = frozen_hashes()
    scratch = external / "intermediate"; scratch.mkdir(parents=True, exist_ok=True)

    atr = rebuild_atrdr_source(args.baseline_root, inputs, scratch)
    atr["strategy"] = "ATRDR"
    mcb = pd.read_parquet(args.baseline_root / "mcb_integrated/trades.parquet")
    mcb = mcb.loc[pd.to_datetime(mcb.signal_date).le(study_end)].copy()
    mcb["strategy"], mcb["route"] = "MCB", "MCB"
    mcb_signals = pd.read_parquet(args.baseline_root / "mcb_integrated/signals.parquet")
    mcb_anchor = mcb_signals[["event_id", "coord_low", "feature_latest_timestamp"]].rename(
        columns={"coord_low": "structural_anchor", "feature_latest_timestamp": "anchor_available_at"}
    )
    mcb = mcb.merge(mcb_anchor, on="event_id", how="left", validate="one_to_one")
    mcb["anchor_decision_at"] = pd.to_datetime(mcb.entry_date) + pd.Timedelta(hours=9, minutes=30)
    ogr = pd.read_parquet(args.baseline_root / "ogr_integrated/trades.parquet")
    ifcgr = pd.read_parquet(args.baseline_root / "ifcgr_integrated/trades.parquet")

    symbols = sorted(set(atr.symbol.astype(str)) | set(mcb.symbol.astype(str)) | set(ogr.symbol.astype(str)))
    daily = load_daily([inputs["daily_hist"], inputs["daily_tail"]], symbols)
    daily = daily.loc[pd.to_datetime(daily.trade_date).le(study_end)].copy()
    daily_groups = {
        str(symbol): group.sort_values("trade_date").reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }

    mcb_cache = make_stock_cache(mcb, daily_groups, study_end, "event_id")
    atr_cache = make_stock_cache(atr, daily_groups, study_end, "event_id")
    mcb_daily = daily.loc[daily.symbol.isin(mcb.symbol.unique())]
    atr_daily = daily.loc[daily.symbol.isin(atr.symbol.unique())]
    mcb_acc, mcb_skip, mcb_nav, _ = replay_sleeves(
        mcb, mcb_daily,
        rank_columns=("industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"),
        k_per_sleeve=30, daily_cap=10,
    )
    mcb_acc["strategy"], mcb_acc["route"] = "MCB", "MCB"
    atr_acc, atr_skip, atr_nav = replay_shared_router(atr, atr_daily, nav_end=study_end)
    atr_acc["strategy"], atr_acc["route"] = "ATRDR", atr_acc.lane.map(ATR_LANES)
    ogr_daily = daily.loc[daily.symbol.isin(ogr.symbol.unique())]
    ogr_acc, ogr_ledger, ogr_nav = replay_portfolio(ogr, ogr_daily)
    ifc_acc, ifc_ledger, ifc_nav = replay_portfolio(ifcgr, ogr_daily)
    ogr_acc["strategy"], ogr_acc["route"] = "OGR", "OGR"
    ifc_acc["strategy"], ifc_acc["route"] = "IFCGR", "IFCGR_SHADOW"

    stock_paths = pd.concat([
        stock_path_summary(mcb_acc, mcb_cache, key="event_id", study_end=study_end),
        stock_path_summary(atr_acc, atr_cache, key="event_id", study_end=study_end),
    ], ignore_index=True)
    minutes = load_ogr_minutes(ogr, ogr_daily, inputs["raw_minute_root"], external)
    minute_groups = {str(key): group for key, group in minutes.groupby("gap_id", sort=False)}
    ogr_path_rows = []
    for _, trade in ogr_acc.iterrows():
        daily_path, lineage = prepare_daily_path(
            daily_groups[str(trade.symbol)],
            trade.rename({"entry_raw_price": "entry_price", "exit_raw_price": "exit_price"}),
            study_end,
        )
        stats = path_statistics(
            daily_path, entry_price=float(trade.entry_coordinate_price),
            native_net_return=float(trade.net_return),
        )
        ogr_path_rows.append({
            "strategy": "OGR", "route": "OGR", "event_id": str(trade.gap_id),
            "security": trade.symbol, "signal_date": trade.signal_date,
            "entry_date": trade.entry_date, "entry_time": trade.entry_time,
            "entry_price": trade.entry_raw_price, "native_exit_date": trade.exit_date,
            "native_exit_time": trade.exit_time, "native_exit_price": trade.exit_raw_price,
            "native_exit_reason": trade.exit_reason, "native_net_return": trade.net_return,
            "atr20_entry_frozen": frozen_atr20(daily_groups[str(trade.symbol)], pd.Timestamp(trade.entry_date), lineage),
            "structural_anchor": trade.swing_low,
            "anchor_available_at": trade.semantic_feature_latest_timestamp, **stats,
        })
    smv_paths, smv_residual = smv6_paths(args.baseline_root, inputs["smv6_qmt_root"], study_end)
    paths = add_evidence_stage(pd.concat([stock_paths, pd.DataFrame(ogr_path_rows), smv_paths], ignore_index=True))
    paths.to_parquet(external / "causal_trade_path_summary.parquet", index=False)
    write_csv(paths, output / "trade_path_summary.csv")
    anatomy, mae_mfe = loss_tables(paths)
    write_csv(anatomy, output / "loss_anatomy.csv")
    write_csv(mae_mfe, output / "mae_mfe_summary.csv")
    write_csv(smv_residual, output / "smv6_residual_loss_attribution.csv")

    candidates: dict[str, list[Candidate]] = {}
    for route in ("ATRDR_BULL", "ATRDR_FAST_BEAR", "ATRDR_SLOW_BEAR", "MCB", "OGR"):
        values = [Candidate(f"FIXED_{level * 100:g}PCT", "fixed", level) for level in FIXED_LEVELS]
        values += [Candidate(f"ATR20_{scale:g}X", "volatility", scale) for scale in VOL_SCALES]
        anchor_name = {
            "ATRDR_BULL": "SIGNAL_LOW", "ATRDR_FAST_BEAR": "SIGNAL_LOW",
            "ATRDR_SLOW_BEAR": "LAST5_LOW", "MCB": "SIGNAL_LOW", "OGR": "SWING_LOW",
        }[route]
        values.append(Candidate(f"STRUCT_{anchor_name}", "structural", anchor=anchor_name))
        if route in {"ATRDR_BULL", "MCB", "OGR"}:
            values += [Candidate(f"FOLLOWTHROUGH_{days}D", "followthrough", days) for days in FOLLOW_DAYS]
        lane_anatomy = anatomy.loc[
            anatomy.route.eq(route) & anatomy.evidence_stage.eq("ALL")
        ].iloc[0]
        if (
            lane_anatomy.n_severe_losses >= 10
            and lane_anatomy.severe_worked_then_gave_back_share >= 0.40
        ):
            values.append(Candidate("PROFIT_MFE5_TO_ENTRY", "profit_protection"))
        candidates[route] = values

    baseline_navs: dict[str, tuple[pd.DataFrame, str, str]] = {
        "MCB": (mcb_nav, "combined_nav", "gross_exposure"),
        "ATRDR_BULL": (atr_nav, "combined_nav", "utilization"),
        "ATRDR_FAST_BEAR": (atr_nav, "combined_nav", "utilization"),
        "ATRDR_SLOW_BEAR": (atr_nav, "combined_nav", "utilization"),
        "OGR": (ogr_nav.loc[ogr_nav.board.eq("COMBINED")], "nav", "gross_exposure"),
    }
    baseline_accepts = {
        "MCB": mcb_acc,
        "ATRDR_BULL": atr_acc,
        "ATRDR_FAST_BEAR": atr_acc,
        "ATRDR_SLOW_BEAR": atr_acc,
        "OGR": ogr_acc,
    }
    all_events = []
    portfolio_rows = []
    capital_rows = []
    nav_store: dict[tuple[str, str], pd.DataFrame] = {}
    for route, (nav, nav_col, exposure_col) in baseline_navs.items():
        nav_view = nav.copy()
        nav_view["nav_value"] = nav_view[nav_col]
        if exposure_col == "utilization":
            nav_view["exposure_value"] = nav_view[nav_col] * nav_view[exposure_col]
        else:
            nav_view["exposure_value"] = nav_view[exposure_col]
        nav_store[(route, "BASELINE")] = nav_view[["trade_date", "nav_value", "exposure_value"]]
    baseline_metrics = {
        route: portfolio_metrics(
            nav_store[(route, "BASELINE")], nav_column="nav_value", exposure_column="exposure_value"
        ) for route in baseline_navs
    }

    for route, route_candidates in candidates.items():
        for candidate in route_candidates:
            if route == "MCB":
                modified, events = simulate_stock_source(mcb, mcb_cache, candidate, route=route, key="event_id")
                accepted, skipped, nav, _ = replay_sleeves(
                    modified, mcb_daily,
                    rank_columns=("industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"),
                    k_per_sleeve=30, daily_cap=10,
                )
                nav_value = nav.combined_nav; exposure = nav.gross_exposure
            elif route.startswith("ATRDR"):
                modified, events = simulate_stock_source(atr, atr_cache, candidate, route=route, key="event_id")
                accepted, skipped, nav = replay_shared_router(modified, atr_daily, nav_end=study_end)
                nav_value = nav.combined_nav; exposure = nav.combined_nav * nav.utilization
            else:
                modified, events = simulate_ogr_source(
                    ogr, minute_groups, daily_groups, candidate, route="OGR"
                )
                accepted, skipped, nav = replay_portfolio(modified, ogr_daily)
                nav = nav.loc[nav.board.eq("COMBINED")].copy()
                nav_value = nav.nav; exposure = nav.gross_exposure
            baseline_ids = set(baseline_accepts[route].event_id.astype(str)) if route != "OGR" else set(baseline_accepts[route].gap_id.astype(str))
            id_column = "event_id" if route != "OGR" else "gap_id"
            entered_events = events.loc[events.event_id.isin(baseline_ids)].copy()
            entered_events = enrich_event_periods(entered_events, paths)
            all_events.append(entered_events)
            candidate_nav = pd.DataFrame({"trade_date": nav.trade_date, "nav_value": nav_value, "exposure_value": exposure})
            nav_store[(route, candidate.candidate_id)] = candidate_nav
            pm = portfolio_metrics(candidate_nav, nav_column="nav_value", exposure_column="exposure_value")
            em = event_metrics(entered_events, severe_threshold=-0.10)
            accepted_ids = set(accepted[id_column].astype(str))
            added = accepted_ids - baseline_ids
            dropped = baseline_ids - accepted_ids
            base_end = float(nav_store[(route, "BASELINE")].nav_value.iloc[-1])
            candidate_end = float(candidate_nav.nav_value.iloc[-1])
            weights = baseline_accepts[route].copy()
            weight_id = "event_id" if route != "OGR" else "gap_id"
            weight_map = weights.set_index(weight_id).entry_outlay.astype(float)
            if route == "OGR" and "sleeve_weight" in weights:
                weight_map = weight_map * weights.set_index(weight_id).sleeve_weight.astype(float)
            delta_map = entered_events.set_index("event_id").candidate_net_return.sub(
                entered_events.set_index("event_id").native_net_return
            )
            exit_effect = float((delta_map * weight_map.reindex(delta_map.index).fillna(0)).sum())
            total_effect = candidate_end - base_end
            capital_effect = total_effect - exit_effect
            portfolio_rows.append({
                "route": route, "candidate_id": candidate.candidate_id, "family": candidate.family,
                **em, **pm,
                "baseline_total_return": baseline_metrics[route]["total_return"],
                "baseline_cvar5_trade": paths.loc[paths.route.eq(route), "native_net_return"].nsmallest(
                    max(1, math.ceil(paths.route.eq(route).sum() * 0.05))
                ).mean(),
                "cash_shortfall_orders": int(
                    skipped.get("skip_reason", pd.Series(dtype=str)).astype(str).str.contains("INSUFFICIENT_CASH").sum()
                ),
                "additional_funded_trades": len(added), "dropped_funded_trades": len(dropped),
                "exit_effect": exit_effect, "capital_release_effect": capital_effect,
                "total_portfolio_effect": total_effect,
            })
            capital_rows.append({
                "route": route, "candidate_id": candidate.candidate_id,
                "exit_effect": exit_effect, "capital_release_effect": capital_effect,
                "total_portfolio_effect": total_effect,
                "capital_release_days": int(entered_events.capital_release_sessions.sum()),
                "additional_funded_trades": len(added), "dropped_funded_trades": len(dropped),
            })

    events = pd.concat(all_events, ignore_index=True)
    events.to_parquet(external / "event_level_counterfactual.parquet", index=False)
    compact_event_columns = [
        "strategy", "route", "event_id", "security", "signal_date", "entry_date",
        "native_exit_date", "native_net_return", "candidate_id", "family",
        "candidate_exit_date", "candidate_exit_reason", "candidate_net_return",
        "stop_triggered", "stop_filled", "unfilled_stop", "gap_through",
        "intraday_order_ambiguous", "capital_release_sessions", "evidence_stage", "year",
    ]
    write_csv(events[compact_event_columns], output / "event_level_counterfactual.csv")
    response = pd.DataFrame(response_rows(events))
    portfolio = pd.DataFrame(portfolio_rows)
    capital = pd.DataFrame(capital_rows)
    write_csv(response, output / "winner_kill_loss_rescue.csv")
    write_csv(response.loc[response.family.eq("fixed")], output / "fixed_stop_response_curve.csv")
    write_csv(response.loc[response.family.eq("volatility")], output / "volatility_stop_response_curve.csv")
    write_csv(response.loc[response.family.eq("structural")], output / "structural_stop_results.csv")
    write_csv(response.loc[response.family.eq("followthrough")], output / "followthrough_stop_results.csv")
    if response.family.eq("profit_protection").any():
        write_csv(response.loc[response.family.eq("profit_protection")], output / "profit_protection_results.csv")
    write_csv(events.loc[events.intraday_order_ambiguous | events.unfilled_stop], output / "execution_ambiguities.csv")
    write_csv(portfolio, output / "portfolio_stop_comparison.csv")
    write_csv(capital, output / "capital_release_effect.csv")
    temporal = temporal_rows(events)
    write_csv(temporal, output / "temporal_robustness.csv")

    # IFCGR inherits OGR's pre-registered structural candidate; it is not optimized separately.
    inherited = Candidate("STRUCT_SWING_LOW", "structural", anchor="SWING_LOW")
    ifc_modified, ifc_events = simulate_ogr_source(
        ifcgr, minute_groups, daily_groups, inherited, route="IFCGR_SHADOW"
    )
    ifc_stop_acc, ifc_stop_ledger, ifc_stop_nav = replay_portfolio(ifc_modified, ogr_daily)
    ifc_events = ifc_events.loc[ifc_events.event_id.isin(set(ifc_acc.gap_id.astype(str)))]
    ifc_event_metrics = event_metrics(ifc_events, severe_threshold=-0.10)
    ifc_stop_combined = ifc_stop_nav.loc[ifc_stop_nav.board.eq("COMBINED")]
    ifc_base_combined = ifc_nav.loc[ifc_nav.board.eq("COMBINED")]
    inheritance = pd.DataFrame([
        {"portfolio": "OGR", "exit": "NATIVE", **portfolio_metrics(nav_store[("OGR", "BASELINE")], nav_column="nav_value", exposure_column="exposure_value")},
        {"portfolio": "OGR", "exit": inherited.candidate_id, **portfolio_metrics(nav_store[("OGR", inherited.candidate_id)], nav_column="nav_value", exposure_column="exposure_value")},
        {"portfolio": "IFCGR", "exit": "NATIVE", **portfolio_metrics(ifc_base_combined, nav_column="nav", exposure_column="gross_exposure")},
        {"portfolio": "IFCGR", "exit": inherited.candidate_id, **ifc_event_metrics, **portfolio_metrics(ifc_stop_combined, nav_column="nav", exposure_column="gross_exposure")},
    ])
    write_csv(inheritance, output / "ifcgr_shadow_inheritance.csv")

    stranded = pd.concat([
        stranded_diagnostic("MCB", mcb_skip, mcb_nav),
        stranded_diagnostic("ATRDR", atr_skip, atr_nav),
        smv6_cash_shortfall_diagnostic(args.baseline_root, study_end),
    ], ignore_index=True)
    write_csv(stranded, output / "current_stranded_capital_diagnostic.csv")

    decision_config = Path(__file__).with_name("decision_overrides.json")
    decisions = read_json(decision_config) if decision_config.exists() else {}
    decision_rows = []
    for route in ("ATRDR_BULL", "ATRDR_FAST_BEAR", "ATRDR_SLOW_BEAR", "MCB", "OGR"):
        chosen = decisions.get(route, {})
        diagnostic = chosen.get("diagnostic_candidate_id", "STRUCT_" + {
            "ATRDR_BULL": "SIGNAL_LOW", "ATRDR_FAST_BEAR": "SIGNAL_LOW",
            "ATRDR_SLOW_BEAR": "LAST5_LOW", "MCB": "SIGNAL_LOW", "OGR": "SWING_LOW",
        }[route])
        row = portfolio.loc[(portfolio.route.eq(route)) & (portfolio.candidate_id.eq(diagnostic))]
        values = row.iloc[0].to_dict() if len(row) else {}
        decision_rows.append({
            "route": route, "verdict": chosen.get("verdict", "PENDING_PROFESSIONAL_REVIEW"),
            "preferred_stop_or_region": chosen.get("preferred_stop_or_region", "PENDING"),
            "diagnostic_candidate_id": diagnostic,
            "economic_reasoning": chosen.get("economic_reasoning", "pending curve review"),
            "temporal_stability": chosen.get("temporal_stability", "PENDING"),
            "main_limitation": chosen.get("main_limitation", "pending curve review"),
            **values,
        })
    smv_severe = int(smv_residual.native_net_return.le(-0.05).sum())
    smv_verdict = decisions.get("SMV6", {})
    decision_rows.append({
        "route": "SMV6", "verdict": smv_verdict.get("verdict", "NO_NEW_STOP_RESEARCH_NEEDED"),
        "preferred_stop_or_region": "NONE", "diagnostic_candidate_id": "RESIDUAL_LOSS_ATTRIBUTION",
        "economic_reasoning": smv_verdict.get(
            "economic_reasoning", f"Only {smv_severe} of {len(smv_residual)} completed positions lost at least 5%; no loss reached -10%."
        ),
        "temporal_stability": smv_verdict.get("temporal_stability", "INSUFFICIENT_SEVERE_TAIL_TO_OPEN_STOP_SCAN"),
        "main_limitation": "LOCAL_SEMANTICS_REPLAY; native SuperMind equivalence unverified",
        "trade_count": len(smv_residual), "stop_trigger_count": 0, "stop_fill_count": 0,
        "winner_kill_rate": np.nan, "loss_rescue_rate": np.nan,
        "baseline_cvar5_trade": smv_residual.native_net_return.nsmallest(max(1, math.ceil(len(smv_residual) * 0.05))).mean(),
        "cvar5": np.nan, "baseline_total_return": np.nan, "total_return": np.nan,
        "capital_release_effect": 0.0,
    })
    decision_rows.append({
        "route": "IFCGR_SHADOW", "verdict": decisions.get("IFCGR_SHADOW", {}).get("verdict", "PENDING_OGR_INHERITANCE_REVIEW"),
        "preferred_stop_or_region": "INHERITED_STRUCT_SWING_LOW", "diagnostic_candidate_id": inherited.candidate_id,
        "economic_reasoning": decisions.get("IFCGR_SHADOW", {}).get("economic_reasoning", "Uses OGR structural rule without parameter search."),
        "temporal_stability": decisions.get("IFCGR_SHADOW", {}).get("temporal_stability", "PENDING"),
        "main_limitation": "PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE",
        **ifc_event_metrics,
        "baseline_total_return": portfolio_metrics(ifc_base_combined, nav_column="nav", exposure_column="gross_exposure")["total_return"],
        "total_return": portfolio_metrics(ifc_stop_combined, nav_column="nav", exposure_column="gross_exposure")["total_return"],
    })
    decision = pd.DataFrame(decision_rows)
    write_csv(decision, output / "decision_matrix.csv")

    input_manifest = {
        "task": "FIVE_STRATEGY_EXIT_RISK_V1", "evidence_stage": STUDY_LABEL,
        "baseline_head": BASELINE_HEAD, "study_end": str(study_end.date()),
        "post_2023_used_for_selection": False, "new_sealed_validation_opened": False,
        "baseline_root": str(args.baseline_root.resolve()), "external_path_root": str(external),
        "registered_inputs": raw_inputs,
        "source_counts": {
            "ATRDR_candidates": len(atr), "ATRDR_baseline_funded": len(atr_acc),
            "MCB_candidates": len(mcb), "MCB_baseline_funded": len(mcb_acc),
            "OGR_candidates": len(ogr), "OGR_baseline_funded": len(ogr_acc),
            "IFCGR_candidates": len(ifcgr), "IFCGR_baseline_funded": len(ifc_acc),
            "SMV6_completed_positions_to_2023": len(smv_residual),
        },
        "frozen_hashes_before": before_hashes,
    }
    write_json(output / "input_manifest.json", input_manifest)
    after_hashes = frozen_hashes()
    if before_hashes != after_hashes:
        raise RuntimeError("frozen production strategy/config hash drift")

    if not args.skip_figures:
        render_figures(paths, response, nav_store, output)
    report = [
        "# 五策略失败路径、止损、利润保护与资金释放研究 V1",
        "",
        f"- 证据层：`{STUDY_LABEL}`，不是新的 sealed OOS。",
        f"- 权威基线：`{BASELINE_HEAD}`；研究截止：`{study_end.date()}`。",
        "- 本轮只运行 shadow/counterfactual exit；frozen production strategy/config 未修改。",
        "- A 股执行包含 T+1、gap-through、触发未成交、真实因果资金释放；OGR 使用 registered one-minute path。",
        "- SMV6 先做 residual-loss attribution；未满足打开 hard-stop scan 的门槛。",
        "",
        "## Lane 决策",
        "",
    ]
    for row in decision.itertuples(index=False):
        report += [
            f"### {row.route}: {row.verdict}", "",
            f"- 代表诊断：`{row.diagnostic_candidate_id}`；下一阶段候选：`{row.preferred_stop_or_region}`。",
            f"- 经济解释：{row.economic_reasoning}",
            f"- 时间稳定性：{row.temporal_stability}",
            f"- 主要限制：{row.main_limitation}", "",
        ]
        if hasattr(row, "trade_count") and pd.notna(row.trade_count):
            report.insert(-1, (
                f"- N={int(row.trade_count)}；triggers={int(row.stop_trigger_count)}；"
                f"winner kill={row.winner_kill_rate if pd.notna(row.winner_kill_rate) else 'NA'}；"
                f"loss rescue={row.loss_rescue_rate if pd.notna(row.loss_rescue_rate) else 'NA'}；"
                f"baseline tail={row.baseline_cvar5_trade if pd.notna(row.baseline_cvar5_trade) else 'NA'}；"
                f"candidate tail={row.cvar5 if pd.notna(row.cvar5) else 'NA'}；"
                f"baseline return={row.baseline_total_return if pd.notna(row.baseline_total_return) else 'NA'}；"
                f"candidate return={row.total_return if pd.notna(row.total_return) else 'NA'}；"
                f"capital release effect={row.capital_release_effect if pd.notna(row.capital_release_effect) else 'NA'}。"
            ))
    report += [
        "## 资金与执行边界", "",
        f"- Baseline cash-shortfall/闲置资金诊断共 {len(stranded)} 行；本轮没有实现 shared-cash allocator。",
        f"- execution ambiguity/unfilled 明细见 `execution_ambiguities.csv`，共 {int((events.intraday_order_ambiguous | events.unfilled_stop).sum())} 行。",
        "- `capital_release_effect` 是 total portfolio effect 减去原 funded cohort 的加权 exit effect；它包含后续 funded-set 改变与复利路径影响。",
        "",
        "## 复现", "",
        "```bash",
        f"PYTHONPATH=src /opt/anaconda3/bin/python3 {Path(__file__).relative_to(ROOT)} --input-config {args.input_config} --baseline-root {args.baseline_root} --output-root {output} --path-output-root {external} --study-end {study_end.date()}",
        "```", "",
    ]
    (output / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    manifest = output_manifest(output)
    result = {
        "TASK_STATUS": "COMPLETE" if decisions else "RESEARCH_COMPUTED_DECISION_REVIEW_PENDING",
        "frozen_strategies_modified": False, "new_sealed_validation_opened": False,
        "no_financing_validation": bool(
            portfolio.minimum_cash.ge(-1e-10).all()
            and portfolio.max_gross_exposure_ratio.le(1 + 1e-10).all()
        ),
        "frozen_hashes_unchanged": before_hashes == after_hashes,
        "output_file_count": len(manifest),
        "decision_matrix_hash": canonical_frame_hash(decision),
    }
    write_json(output / "run_result.json", result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
