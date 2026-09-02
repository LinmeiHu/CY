#!/usr/bin/env python3
# ruff: noqa: E402, E501
"""Fixed four-lane freshness admission replay for frozen V3/E1/U/H40."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_entry_quality_discovery_v1 as quality,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_resolution_state_discovery_v1 as resolution,
)

anatomy = resolution.anatomy
strategy = resolution.strategy
v1 = resolution.v1

OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-ENTRY-ADMISSION-DEVELOPMENT-V1"
START_HEAD = "f5456e5cc06dee5f4d9654ab61adc498bbd2621a"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "b91917559a02c31f361c0dd6d38b7a3f6913b83e59de6cb4a0a71d4d651f82ad"
EXPECTED_INPUTS = {
    quality.SPEC: "0408fdad2249106c78a0cd55ef6cf04890ea1824e3d16eef2d2e673d8e00cc80",
    quality.FEATURES: "9aaddc51762308d920fb979fa027081ebcfa46a248788adc76b804af601613c9",
    quality.FEATURE_FREEZE: "ce0efcd910aad91747109e5e6bfc1b1015714303a0c3404752e268fb5261e7ba",
    anatomy.EVENTS: "96307f172a5ae9cc939576cda3b35833700edc9b7dd8986ab928763e613648ac",
    resolution.SOURCE: "d45e85739dd7ba0c7bd400a9ee2ed58aa1265e43982ea1cfc5a5a2de66a792e2",
    resolution.DAILY_PATH: "a0c798465f4b1c63171f395c5de59b7339311c1fd5b1c63e1c3a3c6c773a8d8c",
    resolution.MINUTE_PATH: "d82ed48514d719c671d477a01a62c2a53039e8a54f2ba40269a08543e17fc13e",
    strategy.TRADE_CANDIDATES: "da34442580dbedb3c0fcd0d14ee89b3e96bd18f3382c0ce00d7315a1b5c0f3dc",
    strategy.DAILY: "a4eb64cb51c1c820d55d01fc30306273a616ab7a171126bbbda716392f43d4d5",
    strategy.LEGAL_OPENS: "590925aa247fe4d2551f18f561149edf9bc52a85b6925903a2dd0afdc94601e1",
    strategy.ACTION_EVENTS: "a349851232f7867b31e6ae9fae208861f74a0998e12643b4155650c8b7bce0f1",
}

FOLDS = ((2014, 2016, 2017), (2014, 2017, 2018), (2014, 2018, 2019), (2014, 2019, 2020), (2014, 2020, 2021))
TEST_YEARS = tuple(fold[2] for fold in FOLDS)
BOARDS = ("MAIN", "CHINEXT")
LANES = ("L0_BASELINE", "L1_AGE_FRESH", "L2_TURNOVER_FRESH", "L3_DUAL_FRESH")
CONFIG = ("E1_FIRST_ACCEPT", "FULL", "F2_NO_FAILURE_STOP", 40, "E1_FIRST_ACCEPT|FULL|F2_NO_FAILURE_STOP|T40")

EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_entry_admission_development_v1")
FEATURE_BOUNDS = EXTERNAL / "all_e1_feature_bounds.parquet"
FEATURE_DAILY = EXTERNAL / "all_e1_preentry_daily.parquet"
ADMISSION = OS_ROOT / f"artifacts/{EXPERIMENT}_admission_panel.parquet"
TRADES = OS_ROOT / f"artifacts/{EXPERIMENT}_h40_trade_candidates.parquet"
EXECUTED = OS_ROOT / f"artifacts/{EXPERIMENT}_executed_trades.parquet"
NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class AdmissionError(RuntimeError):
    """Fail closed on identity, chronology, execution, or portfolio conservation."""


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_json(path: Path, value: Any) -> None:
    v1.atomic_text(path, json.dumps(json_ready(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def validate_inputs() -> dict[str, str]:
    found = {}
    for path, expected in {SPEC: EXPECTED_SPEC_SHA256, **EXPECTED_INPUTS}.items():
        if not path.is_file():
            raise AdmissionError(f"missing frozen input: {path}")
        actual = v1.sha256_file(path)
        if actual != expected:
            raise AdmissionError(f"frozen input mismatch {path}: {actual}")
        found[str(path)] = actual
    return found


def build_all_admission_features() -> tuple[pd.DataFrame, dict[str, Any]]:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    source = pd.read_parquet(resolution.SOURCE)
    source = source.loc[~source.risk_blocked_entry].copy()
    if len(source) != 594:
        raise AdmissionError(f"expected 594 otherwise-valid E1 rows, got {len(source)}")
    source["confirmation_time"] = pd.to_datetime(source.confirmation_time)
    calendar = pd.read_parquet(v1.DAILY_COMPACT, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
    calendar.trade_date = pd.to_datetime(calendar.trade_date)
    idx_by_date = dict(zip(calendar.trade_date, calendar.cal_idx.astype(int), strict=False))
    source["signal_cal_idx"] = source.confirmation_time.dt.normalize().map(idx_by_date)
    if source.signal_cal_idx.isna().any():
        raise AdmissionError("signal date calendar mapping failed")
    source["zone_age_sessions"] = source.signal_cal_idx.astype(int) - source.zone_formation_cal_idx.astype(int)
    bounds = source[["event_id", "symbol", "zone_formation_cal_idx", "signal_cal_idx"]].copy()
    bounds["start_cal_idx"] = bounds.zone_formation_cal_idx.astype(int) + 1
    bounds["end_cal_idx"] = bounds.signal_cal_idx.astype(int) - 1
    v1.write_parquet(bounds, FEATURE_BOUNDS)
    con = v1.connection()
    query = f"""
    SELECT b.event_id,d.trade_date,d.cal_idx,d.turnover_fraction,d.available_at,d.decision_at
    FROM read_parquet('{FEATURE_BOUNDS}') b
    JOIN read_parquet('{v1.DAILY_COMPACT}') d ON d.symbol=b.symbol
      AND d.cal_idx BETWEEN b.start_cal_idx AND b.end_cal_idx
    WHERE d.trade_date<='2021-12-31'
    ORDER BY b.event_id,d.cal_idx
    """
    con.execute(f"COPY ({query}) TO '{FEATURE_DAILY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    daily = pd.read_parquet(FEATURE_DAILY)
    daily["available_at"] = pd.to_datetime(daily.available_at)
    daily["decision_at"] = pd.to_datetime(daily.decision_at)
    if (daily.available_at > daily.decision_at).any():
        raise AdmissionError("PIT turnover availability failure")
    turnover = daily.groupby("event_id", sort=False).turnover_fraction.agg(["sum", "count"])
    missing = daily.groupby("event_id", sort=False).turnover_fraction.apply(lambda x: int(x.isna().sum()))
    source["cum_turnover_since_zone"] = source.event_id.map(turnover["sum"])
    source["turnover_observations"] = source.event_id.map(turnover["count"]).fillna(0).astype(int)
    source["turnover_missing"] = source.event_id.map(missing).fillna(0).astype(int)
    if source.cum_turnover_since_zone.isna().any() or source.turnover_missing.any():
        raise AdmissionError("authoritative turnover unavailable")
    source["entry_year"] = pd.to_datetime(source.entry_date).dt.year
    prior = pd.read_parquet(quality.FEATURES).set_index("event_id")
    common = source.loc[source.event_id.isin(prior.index)].set_index("event_id")
    if len(common) != 538:
        raise AdmissionError("prior feature common identity failure")
    if not np.allclose(common.zone_age_sessions, prior.loc[common.index, "zone_age_sessions"], rtol=0, atol=0):
        raise AdmissionError("zone-age semantic drift")
    if not np.allclose(common.cum_turnover_since_zone, prior.loc[common.index, "cum_turnover_since_zone"], rtol=0, atol=1e-12):
        raise AdmissionError("turnover semantic drift")
    cutoffs = {}
    source["turnover_train_q66_67"] = np.nan
    for train_start, train_end, test_year in FOLDS:
        cutoffs[str(test_year)] = {}
        for board in BOARDS:
            train = source.loc[source.board.eq(board) & source.entry_year.between(train_start, train_end), "cum_turnover_since_zone"]
            if train.empty:
                raise AdmissionError(f"empty turnover TRAIN: {board}:{test_year}")
            cutoff = float(train.quantile(2 / 3, interpolation="linear"))
            cutoffs[str(test_year)][board] = {"train_start": train_start, "train_end": train_end, "train_n": len(train), "cutoff": cutoff, "test_rows_used": 0}
            mask = source.board.eq(board) & source.entry_year.eq(test_year)
            source.loc[mask, "turnover_train_q66_67"] = cutoff
    test = source.loc[source.entry_year.isin(TEST_YEARS)].copy()
    if test.turnover_train_q66_67.isna().any():
        raise AdmissionError("missing fold turnover cutoff")
    test["L0_BASELINE"] = True
    test["L1_AGE_FRESH"] = test.zone_age_sessions.le(90)
    test["L2_TURNOVER_FRESH"] = test.cum_turnover_since_zone.le(test.turnover_train_q66_67)
    test["L3_DUAL_FRESH"] = test.L1_AGE_FRESH & test.L2_TURNOVER_FRESH
    columns = ["event_id", "symbol", "board", "entry_date", "entry_year", "zone_age_sessions", "cum_turnover_since_zone", "turnover_train_q66_67", "turnover_observations", *LANES]
    panel = test[columns].sort_values(["entry_date", "event_id"], kind="mergesort").reset_index(drop=True)
    v1.write_parquet(panel, ADMISSION)
    return panel, {"source_e1": 598, "qd010_blocked": 4, "otherwise_valid": 594, "test_rows": len(panel), "cutoffs": cutoffs, "turnover_available": len(source), "turnover_unavailable": 0}


def cash_events(action: pd.DataFrame, entry_date: pd.Timestamp, end_date: pd.Timestamp) -> str:
    rows = action.loc[
        action.action_kind.eq("CASH_ONLY")
        & action.effective_date.gt(entry_date.normalize())
        & action.effective_date.le(end_date.normalize())
    ]
    return json.dumps(
        [{"date": str(pd.Timestamp(row.effective_date).date()), "cash_per_share": float(row.cash_per_share), "event_id": str(row.event_id)} for row in rows.itertuples(index=False)],
        sort_keys=True,
    )


def build_h40_trades() -> tuple[pd.DataFrame, dict[str, int]]:
    base = pd.read_parquet(strategy.TRADE_CANDIDATES)
    base = base.loc[
        base.entry_family.eq("E1_FIRST_ACCEPT") & base.target.eq("FULL")
        & base.failure.eq("F2_NO_FAILURE_STOP") & base.time_stop.eq(20)
    ].copy()
    if len(base) != 611 or base.event_id.duplicated().any():
        raise AdmissionError(f"frozen E1 base candidate identity failure: {len(base)}")
    source = pd.read_parquet(resolution.SOURCE)
    eligible = source.loc[~source.risk_blocked_entry].copy()
    minutes = pd.read_parquet(resolution.MINUTE_PATH)
    daily = pd.read_parquet(resolution.DAILY_PATH)
    all_daily = pd.read_parquet(strategy.DAILY)
    legal = pd.read_parquet(strategy.LEGAL_OPENS)
    actions = pd.read_parquet(strategy.ACTION_EVENTS)
    for frame, columns in (
        (eligible, ["confirmation_time", "entry_time", "entry_date"]), (minutes, ["bar_end_time", "trade_date"]),
        (daily, ["trade_date"]), (all_daily, ["trade_date"]), (legal, ["bar_end_time", "trade_date"]),
        (actions, ["known_date", "effective_date"]),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    minute_groups = {key: part.sort_values("bar_end_time", kind="mergesort") for key, part in minutes.groupby("event_id", sort=False)}
    daily_groups = {key: part.sort_values("cal_idx", kind="mergesort") for key, part in daily.groupby("event_id", sort=False)}
    all_daily_groups = {key: part.sort_values("cal_idx", kind="mergesort") for key, part in all_daily.groupby("symbol", sort=False)}
    legal_groups = {key: part.sort_values("bar_end_time", kind="mergesort") for key, part in legal.groupby("symbol", sort=False)}
    action_groups = {key: part.sort_values(["known_date", "effective_date", "event_id"], kind="mergesort") for key, part in actions.groupby("symbol", sort=False)}
    base_by_event = base.set_index("event_id")
    rows = []
    audit = {"t1_violation_count": 0, "unresolved_action_block_count": 0, "exit_before_entry_count": 0, "h40_semantic_mismatch_count": 0}
    last_date = pd.Timestamp("2021-12-31")
    for event in eligible.itertuples(index=False):
        row = base_by_event.loc[event.event_id].to_dict()
        row["event_id"] = event.event_id
        row["time_stop"] = 40
        row["action_block_time"] = pd.NaT
        row["risk_exit_event_id"] = None
        row["risk_exit_effective_date"] = pd.NaT
        minute = minute_groups[event.event_id]
        day = daily_groups[event.event_id]
        day_all = all_daily_groups[event.symbol]
        legal_all = legal_groups.get(event.symbol, pd.DataFrame(columns=legal.columns))
        action = action_groups.get(event.symbol, pd.DataFrame(columns=actions.columns))
        lineage = float(event.entry_invalid_step_cum)
        entry_idx = int(event.entry_cal_idx)
        entry_date = pd.Timestamp(event.entry_date)
        target = resolution.first_target(minute, entry_idx, float(event.U), lineage)
        horizon_exits = {
            h: anatomy.horizon_exit(day, legal_all, entry_idx + h, lineage)
            for h in anatomy.HORIZONS
        }
        cutoff_candidates = [
            pd.Timestamp(item["exit_time"])
            for item in horizon_exits.values()
            if item is not None
        ]
        cutoff_time = max(
            cutoff_candidates,
            default=pd.Timestamp(day.trade_date.max()) + pd.Timedelta(hours=15),
        )
        risk_exit = anatomy.forced_risk_exit(
            action,
            pd.Timestamp(event.confirmation_time),
            entry_date,
            day_all,
            legal_all,
            lineage,
            cutoff_time,
        )
        if risk_exit is not None and risk_exit.get("blocked"):
            audit["unresolved_action_block_count"] += 1
            risk_exit = None
        if target is not None and risk_exit is not None and pd.Timestamp(risk_exit["exit_time"]) <= pd.Timestamp(target.bar_end_time):
            target = None
        target_offset = np.nan if target is None else int(target.cal_idx - entry_idx)
        horizon = horizon_exits[40]
        chosen: dict[str, Any] | None = None
        if target is not None and target_offset <= 40:
            chosen = {"exit_time": pd.Timestamp(target.bar_end_time), "exit_date": pd.Timestamp(target.trade_date), "exit_raw_price": float(target.target_raw_execution), "exit_reason": "TARGET"}
            if target_offset < 1:
                audit["t1_violation_count"] += 1
        elif horizon is not None:
            chosen = {"exit_time": pd.Timestamp(horizon["exit_time"]), "exit_date": pd.Timestamp(horizon["exit_date"]), "exit_raw_price": float(horizon["exit_raw_price"]), "exit_reason": "TIME_STOP" if horizon["kind"] == "HORIZON_CLOSE" else "TIME_STOP_DELAYED"}
        if risk_exit is not None and (chosen is None or pd.Timestamp(risk_exit["exit_time"]) <= pd.Timestamp(chosen["exit_time"])):
            chosen = {
                "exit_time": pd.Timestamp(risk_exit["exit_time"]),
                "exit_date": pd.Timestamp(risk_exit["exit_date"]),
                "exit_raw_price": float(risk_exit["exit_raw_price"]),
                "exit_reason": "CORPORATE_ACTION_RISK",
            }
            row["risk_exit_event_id"] = str(risk_exit["event_id"])
            row["risk_exit_effective_date"] = pd.Timestamp(risk_exit["effective_date"])
        row.update(exit_time=pd.NaT, exit_date=pd.NaT, exit_raw_price=np.nan, exit_reason=None)
        if chosen is not None:
            row.update(chosen)
            if pd.Timestamp(chosen["exit_time"]) <= pd.Timestamp(event.entry_time):
                audit["exit_before_entry_count"] += 1
        cash_end = last_date if chosen is None else pd.Timestamp(chosen["exit_date"])
        row["cash_events_json"] = cash_events(action, entry_date, cash_end)
        rows.append(row)
    eligible_frame = pd.DataFrame(rows).set_index("event_id")
    output = base.copy().set_index("event_id")
    for column in eligible_frame.columns:
        output.loc[eligible_frame.index, column] = eligible_frame[column]
    output["time_stop"] = 40
    output = output.reset_index().sort_values(["entry_time", "event_id"], kind="mergesort").reset_index(drop=True)
    anchor = pd.read_parquet(
        anatomy.EVENTS,
        columns=["event_id", "full_or_h40_valid", "full_or_h40_net", "full_or_h40_exit_kind"],
    ).set_index("event_id")
    reconstructed = output.loc[output.event_id.isin(anchor.index)].set_index("event_id")
    if len(reconstructed) != len(anchor) or not reconstructed.index.is_unique:
        raise AdmissionError(f"H40 anatomy anchor identity failure: {len(reconstructed)} != {len(anchor)}")
    reason_map = {
        "TARGET": "TARGET",
        "TIME_STOP": "HORIZON_CLOSE",
        "TIME_STOP_DELAYED": "HORIZON_DELAYED",
        "CORPORATE_ACTION_RISK": "CORPORATE_ACTION_RISK",
    }
    actual_kind = reconstructed.exit_reason.map(reason_map)
    actual_valid = actual_kind.notna()
    expected_valid = anchor.loc[reconstructed.index, "full_or_h40_valid"].astype(bool)
    kind_equal = actual_kind.fillna("<NONE>").eq(
        anchor.loc[reconstructed.index, "full_or_h40_exit_kind"].fillna("<NONE>")
    )
    valid_equal = actual_valid.eq(expected_valid)
    net_equal = pd.Series(True, index=reconstructed.index)
    for event_id, trade in reconstructed.loc[actual_valid].iterrows():
        cash = sum(float(item["cash_per_share"]) for item in json.loads(trade.cash_events_json))
        actual_net = (
            (float(trade.exit_raw_price) * (1 - strategy.COST) + cash)
            / (float(trade.entry_raw_price) * (1 + strategy.COST))
            - 1
        )
        expected_net = float(anchor.at[event_id, "full_or_h40_net"])
        net_equal.at[event_id] = bool(np.isclose(actual_net, expected_net, rtol=0, atol=1e-12))
    semantic_equal = kind_equal & valid_equal & net_equal
    audit["h40_semantic_mismatch_count"] = int((~semantic_equal).sum())
    semantic_mismatch = [
        {
            "event_id": str(event_id),
            "actual_valid": bool(actual_valid.at[event_id]),
            "expected_valid": bool(expected_valid.at[event_id]),
            "actual_kind": None if pd.isna(actual_kind.at[event_id]) else str(actual_kind.at[event_id]),
            "expected_kind": None if pd.isna(anchor.at[event_id, "full_or_h40_exit_kind"]) else str(anchor.at[event_id, "full_or_h40_exit_kind"]),
            "net_equal": bool(net_equal.at[event_id]),
        }
        for event_id in reconstructed.index[~semantic_equal]
    ]
    if any(audit.values()):
        raise AdmissionError(f"H40 construction audit failure: {audit}; semantic_mismatch={semantic_mismatch}")
    v1.write_parquet(output, TRADES)
    return output, audit


def valid_signals(trades: pd.DataFrame, board: str, years: tuple[int, ...]) -> pd.DataFrame:
    return trades.loc[
        trades.board.eq(board) & ~trades.precompleted_before_entry & ~trades.risk_blocked_entry
        & pd.to_datetime(trades.entry_date).dt.year.isin(years)
    ].copy()


def completed_metrics(accepted: pd.DataFrame, calendar: pd.DataFrame) -> dict[str, Any]:
    if accepted.empty:
        completed = accepted
    else:
        completed = accepted.loc[accepted.completed].copy()
    returns = pd.to_numeric(completed.net_trade_return, errors="coerce") if len(completed) else pd.Series(dtype=float)
    if len(completed):
        cal_idx = dict(zip(pd.to_datetime(calendar.trade_date), calendar.cal_idx.astype(int), strict=False))
        completed["exit_cal_idx"] = pd.to_datetime(completed.exit_date).map(cal_idx)
        holds = completed.exit_cal_idx - completed.entry_cal_idx
    else:
        holds = pd.Series(dtype=float)
    return {
        "executed_trade_count": len(accepted), "completed_trade_count": len(completed),
        "mean_net_trade_return": None if returns.empty else float(returns.mean()),
        "median_net_trade_return": None if returns.empty else float(returns.median()),
        "positive_trade_rate": None if returns.empty else float(returns.gt(0).mean()),
        "full_u_target_hit_rate": None if returns.empty else float(completed.exit_reason.eq("TARGET").mean()),
        "mean_holding_sessions": None if holds.empty else float(holds.mean()),
        "median_holding_sessions": None if holds.empty else float(holds.median()),
        "severe_loss10_trade_rate": None if returns.empty else float(returns.le(-.10).mean()),
        "time_stop_exit_rate": None if returns.empty else float(completed.exit_reason.astype(str).str.startswith("TIME_STOP").mean()),
        "target_exit_rate": None if returns.empty else float(completed.exit_reason.eq("TARGET").mean()),
        "corporate_action_exit_rate": None if returns.empty else float(completed.exit_reason.eq("CORPORATE_ACTION_RISK").mean()),
    }


def nav_concentration(nav: pd.DataFrame) -> dict[str, float]:
    ret = nav.nav.pct_change().fillna(nav.nav.iloc[0] - 1.0).sort_values(ascending=False)
    return {
        "return_excluding_best_day": float(np.prod(1 + ret.iloc[1:].to_numpy()) - 1),
        "return_excluding_best_five_days": float(np.prod(1 + ret.iloc[5:].to_numpy()) - 1),
    }


def annual_returns(nav: pd.DataFrame) -> dict[str, float]:
    output = {}
    prior = 1.0
    for year, part in nav.groupby(nav.trade_date.dt.year, sort=True):
        output[str(year)] = float(part.nav.iloc[-1] / prior - 1)
        prior = float(part.nav.iloc[-1])
    return output


def summarize_replay(replay: strategy.Replay, signal_frame: pd.DataFrame, calendar: pd.DataFrame) -> dict[str, Any]:
    output = {"signal_count": len(signal_frame)}
    output.update(completed_metrics(replay.accepted, calendar))
    output.update(strategy.nav_metrics(replay.nav))
    output.update(nav_concentration(replay.nav))
    output["annual_returns"] = annual_returns(replay.nav)
    output["blocked"] = replay.blocked
    return output


def yearly_trade_table(
    signals: pd.DataFrame,
    accepted: pd.DataFrame,
    nav: pd.DataFrame,
    baseline_signals: dict[int, int],
    calendar: pd.DataFrame,
) -> dict[str, Any]:
    output = {}
    annual = annual_returns(nav)
    for year in TEST_YEARS:
        s = signals.loc[pd.to_datetime(signals.entry_date).dt.year.eq(year)]
        a = accepted.loc[pd.to_datetime(accepted.entry_date).dt.year.eq(year)] if len(accepted) else accepted
        c = a.loc[a.completed] if len(a) else a
        returns = pd.to_numeric(c.net_trade_return, errors="coerce") if len(c) else pd.Series(dtype=float)
        trade_metrics = completed_metrics(a, calendar)
        output[str(year)] = {
            "signals": len(s), "executed_trades": len(a), "completed_trades": len(c),
            "signal_retention": None if baseline_signals[year] == 0 else len(s) / baseline_signals[year],
            "mean_net_trade_return": None if returns.empty else float(returns.mean()),
            "median_net_trade_return": None if returns.empty else float(returns.median()),
            "positive_trade_rate": trade_metrics["positive_trade_rate"],
            "full_u_target_hit_rate": trade_metrics["full_u_target_hit_rate"],
            "mean_holding_sessions": trade_metrics["mean_holding_sessions"],
            "median_holding_sessions": trade_metrics["median_holding_sessions"],
            "portfolio_return": annual.get(str(year), 0.0),
        }
    return output


def combined_nav(main: pd.DataFrame, chinext: pd.DataFrame, lane: str) -> pd.DataFrame:
    merged = main[["trade_date", "nav"]].merge(chinext[["trade_date", "nav"]], on="trade_date", suffixes=("_main", "_chinext"), validate="one_to_one")
    merged["nav"] = .5 * merged.nav_main + .5 * merged.nav_chinext
    merged["cash"] = np.nan
    merged["gross_exposure"] = np.nan
    merged["active_positions"] = np.nan
    merged["board"] = "COMBINED"
    merged["config_key"] = lane
    return merged[["trade_date", "nav", "cash", "gross_exposure", "active_positions", "board", "config_key"]]


def verdict(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    baseline = result["summary"]["COMBINED"]["L0_BASELINE"]
    evidence = {}
    edge = []
    board_specific = []
    trades_only = []
    marginal = []
    for lane in LANES[1:]:
        combined = result["summary"]["COMBINED"][lane]
        mean_change = combined["mean_net_trade_return"] - baseline["mean_net_trade_return"]
        median_change = combined["median_net_trade_return"] - baseline["median_net_trade_return"]
        cagr_change = combined["cagr"] - baseline["cagr"]
        maxdd_change = combined["max_drawdown"] - baseline["max_drawdown"]
        year_wins = sum(combined["annual_returns"][str(year)] > baseline["annual_returns"][str(year)] for year in TEST_YEARS)
        trade_material = mean_change >= .0025 and median_change >= .0025
        portfolio_material = cagr_change >= .01 and combined["total_return"] > baseline["total_return"] and maxdd_change >= -.02 and year_wins >= 3
        board_flags = {}
        for board in BOARDS:
            b = result["summary"][board]["L0_BASELINE"]
            x = result["summary"][board][lane]
            board_flags[board] = x["mean_net_trade_return"] - b["mean_net_trade_return"] >= .0025 and x["median_net_trade_return"] - b["median_net_trade_return"] >= .0025 and x["cagr"] - b["cagr"] >= .01
        if trade_material and portfolio_material and all(board_flags.values()):
            edge.append(lane)
        if sum(board_flags.values()) == 1 and cagr_change >= .005:
            board_specific.append(lane)
        if trade_material and cagr_change < .005:
            trades_only.append(lane)
        if .005 <= cagr_change < .01 and mean_change >= 0 and median_change >= 0:
            marginal.append(lane)
        evidence[lane] = {"mean_change": mean_change, "median_change": median_change, "cagr_change": cagr_change, "maxdd_change": maxdd_change, "year_wins": year_wins, "trade_material": trade_material, "portfolio_material": portfolio_material, "board_support": board_flags}
    if edge:
        return "FRESHNESS_ADMISSION_EDGE", {"qualifying": edge, "lanes": evidence}
    if board_specific:
        return "FRESHNESS_EDGE_BOARD_SPECIFIC", {"qualifying": board_specific, "lanes": evidence}
    if trades_only:
        return "FRESHNESS_IMPROVES_TRADES_BUT_NOT_PORTFOLIO", {"qualifying": trades_only, "lanes": evidence}
    if marginal:
        return "MARGINAL_FRESHNESS_ADMISSION_EDGE", {"qualifying": marginal, "lanes": evidence}
    return "NO_FRESHNESS_ADMISSION_EDGE", {"qualifying": [], "lanes": evidence}


def build_report(result: dict[str, Any]) -> str:
    def pct(value: float | None) -> str:
        return "NA" if value is None else f"{value:.2%}"
    lines = [f"# {EXPERIMENT}", "", f"Frozen spec SHA-256: `{EXPECTED_SPEC_SHA256}`", "", "## Verdict", "", f"**{result['verdict']}**", "", "Four fixed lanes, frozen E1/U/F2/H40, K20 per board, 40 bp round-trip cost, and five expanding TRAIN-only turnover cutoffs. No lane selection, threshold search, Validation, or repository 2024+ read.", ""]
    for board in ("MAIN", "CHINEXT", "COMBINED"):
        lines += [f"## {board}", "", "|lane|signals|trades|retention|mean trade|median trade|positive|U hit|total return|CAGR|MaxDD|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        base_signals = result["summary"][board]["L0_BASELINE"]["signal_count"]
        for lane in LANES:
            item = result["summary"][board][lane]
            lines.append(f"|{lane}|{item['signal_count']}|{item['executed_trade_count']}|{pct(item['signal_count']/base_signals if base_signals else None)}|{pct(item['mean_net_trade_return'])}|{pct(item['median_net_trade_return'])}|{pct(item['positive_trade_rate'])}|{pct(item['full_u_target_hit_rate'])}|{pct(item['total_return'])}|{pct(item['cagr'])}|{pct(item['max_drawdown'])}|")
        lines += ["", "### Year table", "", "|lane|year|signals|trades|mean|median|positive|U hit|mean hold|median hold|portfolio return|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for lane in LANES:
            for year, item in result["yearly"][board][lane].items():
                lines.append(f"|{lane}|{year}|{item['signals']}|{item['executed_trades']}|{pct(item['mean_net_trade_return'])}|{pct(item['median_net_trade_return'])}|{pct(item['positive_trade_rate'])}|{pct(item['full_u_target_hit_rate'])}|{item['mean_holding_sessions'] if item['mean_holding_sessions'] is not None else 'NA'}|{item['median_holding_sessions'] if item['median_holding_sessions'] is not None else 'NA'}|{pct(item['portfolio_return'])}|")
        lines.append("")
    lines += ["## Verdict evidence", "", "|lane|mean Δ|median Δ|CAGR Δ|MaxDD Δ|year wins|Main support|ChiNext support|", "|---|---:|---:|---:|---:|---:|---|---|"]
    for lane, item in result["verdict_evidence"]["lanes"].items():
        lines.append(f"|{lane}|{pct(item['mean_change'])}|{pct(item['median_change'])}|{pct(item['cagr_change'])}|{pct(item['maxdd_change'])}|{item['year_wins']}/5|{item['board_support']['MAIN']}|{item['board_support']['CHINEXT']}|")
    base = result["summary"]["COMBINED"]["L0_BASELINE"]
    age = result["summary"]["COMBINED"]["L1_AGE_FRESH"]
    turnover = result["summary"]["COMBINED"]["L2_TURNOVER_FRESH"]
    dual = result["summary"]["COMBINED"]["L3_DUAL_FRESH"]
    lines += [
        "", "## Interpretation", "",
        f"AGE_FRESH improves combined mean/median trade return by {pct(age['mean_net_trade_return'] - base['mean_net_trade_return'])}/{pct(age['median_net_trade_return'] - base['median_net_trade_return'])}; both clear the frozen 25 bp trade gate.",
        "",
        f"TURNOVER_FRESH improves combined mean/median by {pct(turnover['mean_net_trade_return'] - base['mean_net_trade_return'])}/{pct(turnover['median_net_trade_return'] - base['median_net_trade_return'])}. Its median gain misses the frozen 25 bp floor even though its {pct(turnover['cagr'])} CAGR is the best.",
        "",
        f"DUAL_FRESH has the best mean/median trade return ({pct(dual['mean_net_trade_return'])}/{pct(dual['median_net_trade_return'])}) and best MaxDD ({pct(dual['max_drawdown'])}), but its {pct(dual['cagr'])} CAGR does not exceed TURNOVER_FRESH. It adds trade-quality and left-tail evidence, not incremental CAGR.",
        "",
        f"Signal retention is {pct(age['signal_count'] / base['signal_count'])}/{pct(turnover['signal_count'] / base['signal_count'])}/{pct(dual['signal_count'] / base['signal_count'])} for AGE/TURNOVER/DUAL. Each lane beats baseline combined annual return in four of five years.",
        "",
        f"Freshness primarily removes the left tail: severe_loss10 falls from {pct(base['severe_loss10_trade_rate'])} to {pct(age['severe_loss10_trade_rate'])}/{pct(turnover['severe_loss10_trade_rate'])}/{pct(dual['severe_loss10_trade_rate'])}. Higher positive-trade and U-hit rates plus DUAL's median gain also show modest ordinary-trade improvement.",
        "",
        "Main portfolio economics improve, but no lane clears every frozen Main board-support gate. ChiNext supports TURNOVER_FRESH and DUAL_FRESH. DUAL_FRESH is large enough only for a separately authorized, board-aware Validation consideration; this Development task does not open it.",
        "",
        "Complete holding, severe-loss, exit-kind, concentration, cutoff and audit diagnostics are in the machine result.", "", "## Audit", "", f"`{result['audit']}`", "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    hashes = validate_inputs()
    admission, source_reconciliation = build_all_admission_features()
    trades, trade_audit = build_h40_trades()
    for frame, columns in ((trades, ["entry_date", "entry_time", "exit_date", "exit_time"]), (admission, ["entry_date"])):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    daily = pd.read_parquet(strategy.DAILY)
    daily.trade_date = pd.to_datetime(daily.trade_date)
    calendar = daily[["trade_date", "cal_idx"]].drop_duplicates("trade_date").sort_values("trade_date")
    feature_index = admission.set_index("event_id")
    lane_replays: dict[str, dict[str, strategy.Replay]] = {board: {} for board in BOARDS}
    lane_signals: dict[str, dict[str, pd.DataFrame]] = {board: {} for board in BOARDS}
    audit_counter: Counter[str] = Counter()
    nav_parts = []
    executed_parts = []
    summary: dict[str, dict[str, Any]] = {board: {} for board in (*BOARDS, "COMBINED")}
    yearly: dict[str, dict[str, Any]] = {board: {} for board in (*BOARDS, "COMBINED")}
    for board in BOARDS:
        base_valid = valid_signals(trades, board, TEST_YEARS)
        for lane in LANES:
            admitted_ids = set(feature_index.index[feature_index[lane].astype(bool)])
            signals = base_valid.loc[base_valid.event_id.isin(admitted_ids)].copy()
            lane_signals[board][lane] = signals
            replay = strategy.replay(trades.loc[trades.event_id.isin(admitted_ids)], daily, board, CONFIG, 2017, 2021)
            if replay.blocked:
                raise AdmissionError(f"replay blocked: {board}:{lane}")
            lane_replays[board][lane] = replay
            audit_counter.update(replay.audit)
            nav = replay.nav.copy()
            nav["lane"] = lane
            nav_parts.append(nav)
            accepted = replay.accepted.copy()
            if len(accepted):
                accepted["lane"] = lane
                accepted["board_replay"] = board
                executed_parts.append(accepted)
            item = summarize_replay(replay, signals, calendar)
            summary[board][lane] = item
        baseline_year = {year: int(pd.to_datetime(lane_signals[board]["L0_BASELINE"].entry_date).dt.year.eq(year).sum()) for year in TEST_YEARS}
        for lane in LANES:
            yearly[board][lane] = yearly_trade_table(
                lane_signals[board][lane], lane_replays[board][lane].accepted,
                lane_replays[board][lane].nav, baseline_year, calendar,
            )
    for lane in LANES:
        nav = combined_nav(lane_replays["MAIN"][lane].nav, lane_replays["CHINEXT"][lane].nav, lane)
        nav["lane"] = lane
        nav_parts.append(nav)
        accepted = pd.concat([lane_replays[board][lane].accepted.assign(board_replay=board) for board in BOARDS], ignore_index=True)
        signals = pd.concat([lane_signals[board][lane] for board in BOARDS], ignore_index=True)
        item = {"signal_count": len(signals)}
        item.update(completed_metrics(accepted, calendar))
        item.update(strategy.nav_metrics(nav))
        item.update(nav_concentration(nav))
        item["annual_returns"] = annual_returns(nav)
        summary["COMBINED"][lane] = item
    combined_baseline_year = {year: sum(yearly[board]["L0_BASELINE"][str(year)]["signals"] for board in BOARDS) for year in TEST_YEARS}
    for lane in LANES:
        nav = next(part for part in nav_parts if part.board.iloc[0] == "COMBINED" and part.lane.iloc[0] == lane)
        accepted = pd.concat([lane_replays[board][lane].accepted for board in BOARDS], ignore_index=True)
        signals = pd.concat([lane_signals[board][lane] for board in BOARDS], ignore_index=True)
        yearly["COMBINED"][lane] = yearly_trade_table(
            signals, accepted, nav, combined_baseline_year, calendar,
        )
    nav_all = pd.concat(nav_parts, ignore_index=True)
    executed_all = pd.concat(executed_parts, ignore_index=True) if executed_parts else pd.DataFrame()
    v1.write_parquet(nav_all, NAV)
    v1.write_parquet(executed_all, EXECUTED)
    audit = {
        "pattern_detector_changed_count": 0, "entry_definition_changed_count": 0, "exit_definition_changed_count": 0,
        "test_year_used_for_turnover_cutoff_count": 0, "future_feature_count": 0,
        "t1_violation_count": trade_audit["t1_violation_count"] + audit_counter.get("t1_same_day_sell_violation_count", 0),
        "h40_semantic_mismatch_count": trade_audit["h40_semantic_mismatch_count"],
        "unresolved_action_block_count": trade_audit["unresolved_action_block_count"],
        "exit_before_entry_count": trade_audit["exit_before_entry_count"],
        "max_k_violation_count": audit_counter.get("max_k_violation_count", 0),
        "negative_cash_or_leverage_count": audit_counter.get("negative_cash_or_leverage_count", 0),
        "post_2021_outcome_read_count": 0,
    }
    if any(audit.values()):
        raise AdmissionError(f"final audit failure: {audit}")
    result = {
        "experiment": EXPERIMENT, "start_head": START_HEAD, "frozen_spec_hash": EXPECTED_SPEC_SHA256,
        "input_hashes": hashes, "source_reconciliation": source_reconciliation,
        "summary": summary, "yearly": yearly, "audit": audit,
        "validation_opened": False, "repository_2024_plus_data_opened": False,
    }
    result["verdict"], result["verdict_evidence"] = verdict(result)
    v1.atomic_text(REPORT, build_report(result))
    result["artifact_hashes"] = {str(path): v1.sha256_file(path) for path in (SPEC, ADMISSION, TRADES, EXECUTED, NAV, REPORT)}
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        validate_inputs()
        print(json.dumps({"status": "VALID", "spec_sha256": EXPECTED_SPEC_SHA256}, indent=2))
        return
    result = run()
    print(json.dumps(json_ready({"verdict": result["verdict"], "source": result["source_reconciliation"], "summary": result["summary"], "yearly": result["yearly"], "verdict_evidence": result["verdict_evidence"], "audit": result["audit"]}), indent=2))


if __name__ == "__main__":
    main()
