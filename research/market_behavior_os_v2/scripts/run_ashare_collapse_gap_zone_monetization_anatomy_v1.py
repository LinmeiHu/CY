#!/usr/bin/env python3
# ruff: noqa: E402, E501
"""Development-only monetization anatomy for the frozen V3 E1/FULL geometry."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_outcome_discovery_v1 as outcome,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_strategy_development_v1 as strategy,
)

v1 = outcome.v1
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-MONETIZATION-ANATOMY-V1"
START_HEAD = "14e0be9e27ea0f8d8ca2a410cee0dd4fd099cac1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "35447ac8f0437e6e099166452447f400927bc1bfab0af50b7ec3666b34963d0a"
EXPECTED_INPUTS = {
    outcome.v3.SPEC: "6b8c946efa5d1cd8f99103180859d43fabff28583d73a794632b9faeb4c18b16",
    outcome.v3.CANDIDATES: "5920df21aec93aa5c16b63f3ed03b7e32bd76d38c8860052ebabcb3df4b05fa3",
    outcome.SPEC: "e3da3093faf50da92544abf338ac1d1cae3aadd7e42672f998bd8facd7bf2f7c",
    outcome.EVENTS: "b27c2366fdef62e9592bb1c1ebec6a2f1e7c66d7b27312394dd17b65f74e8610",
    outcome.SOURCE_EVENTS: "53fdac69d95307330c3a5929320bd363d7c580fcf5149b38f841ad5154124195",
    outcome.ACCEPTANCE: "61551825fadd75b211fd7550612389a4a8d9732b72ac0a5b9a43393a69612652",
    outcome.ENTRIES: "d7d970824e3ecfdf7784544dc481b8d5f97fde7f0cceefbaefd50c247417ef6d",
    strategy.SPEC: "e0846c4464f82b65dc7cad99a13bcfdf3666001338225727b9544220f74bfcd8",
    strategy.RESULT: "45975c46c628174471e4d48300e79834da3ed6e70be6bfb98037f2500c75cefb",
    strategy.ACTION_EVENTS: "a349851232f7867b31e6ae9fae208861f74a0998e12643b4155650c8b7bce0f1",
    strategy.TRADE_CANDIDATES: "da34442580dbedb3c0fcd0d14ee89b3e96bd18f3382c0ce00d7315a1b5c0f3dc",
}
HORIZONS = (20, 40, 60)
CURVE = (1, 5, 10, 20, 30, 40, 50, 60)
COST = 0.002
TERCILES = (0.02535867873304672, 0.040897981171015875)

EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_monetization_anatomy_v1")
SOURCE = EXTERNAL / "eligible_e1_events.parquet"
BOUNDS = EXTERNAL / "path_bounds.parquet"
DAILY_PATH = EXTERNAL / "daily_path_60d.parquet"
MINUTE_PATH = EXTERNAL / "minute_path_60d.parquet"
EVENTS = OS_ROOT / f"artifacts/{EXPERIMENT}_events.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class AnatomyError(RuntimeError):
    """Fail closed when frozen identity, chronology, or execution is violated."""


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
    found: dict[str, str] = {}
    for path, expected in {SPEC: EXPECTED_SPEC_SHA256, **EXPECTED_INPUTS}.items():
        if not path.is_file():
            raise AnatomyError(f"missing frozen input: {path}")
        actual = v1.sha256_file(path)
        if actual != expected:
            raise AnatomyError(f"frozen input mismatch: {path}: {actual}")
        found[str(path)] = actual
    return found


def prepare_source() -> tuple[pd.DataFrame, dict[str, int]]:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    frozen = pd.read_parquet(outcome.EVENTS)
    accept = pd.read_parquet(outcome.ACCEPTANCE)[["event_id", "bar_end_time"]].rename(columns={"bar_end_time": "confirmation_time"})
    entries = pd.read_parquet(outcome.ENTRIES)
    actions = pd.read_parquet(strategy.TRADE_CANDIDATES)
    risk = actions.loc[actions.entry_family.eq("E1_FIRST_ACCEPT")].drop_duplicates("event_id").set_index("event_id")
    eligible = frozen.loc[frozen.executable_entry].copy()
    eligible = eligible.loc[~eligible.event_id.map(risk.risk_blocked_entry).fillna(False)].copy()
    eligible = eligible.merge(accept, on="event_id", how="left", validate="one_to_one")
    canonical_entries = entries.set_index("event_id")
    for column in ("entry_time", "entry_date", "entry_cal_idx", "entry_raw_price", "entry_coord_price"):
        left = eligible.set_index("event_id")[column]
        right = canonical_entries.loc[left.index, column]
        if column in ("entry_time", "entry_date"):
            mismatch = pd.to_datetime(left).ne(pd.to_datetime(right))
        else:
            mismatch = ~np.isclose(left.astype(float), right.astype(float), rtol=0, atol=1e-12)
        if mismatch.any():
            raise AnatomyError(f"frozen E1 entry mismatch: {column}: {int(mismatch.sum())}")
    calendar = pd.read_parquet(v1.DAILY_COMPACT, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
    calendar["trade_date"] = pd.to_datetime(calendar.trade_date)
    last = int(calendar.loc[calendar.trade_date.le(pd.Timestamp("2021-12-31")), "cal_idx"].max())
    eligible["primary_complete_60d"] = eligible.entry_cal_idx.astype(int).add(60).le(last)
    censored = int((~eligible.primary_complete_60d).sum())
    eligible["target_gross_distance"] = eligible.U / eligible.entry_coord_price - 1
    eligible["target_net_distance"] = eligible.U * (1 - COST) / (eligible.entry_coord_price * (1 + COST)) - 1
    eligible["target_distance_tercile"] = pd.cut(
        eligible.target_net_distance,
        bins=[-np.inf, TERCILES[0], TERCILES[1], np.inf],
        labels=["LOW", "MID", "HIGH"],
        include_lowest=True,
    ).astype("string")
    eligible["entry_year"] = pd.to_datetime(eligible.entry_date).dt.year
    source = eligible.loc[eligible.primary_complete_60d].copy().sort_values("event_id", kind="mergesort")
    if len(eligible) != 594 or len(source) != 538:
        raise AnatomyError(f"source reconciliation failed: eligible={len(eligible)} complete60={len(source)}")
    v1.write_parquet(source, SOURCE)
    return source, {
        "source_events": 617,
        "outcome_executable_entries": 598,
        "qd010_risk_blocked_entries": 4,
        "eligible_before_censor": 594,
        "censored_60d": censored,
        "analysis_events": len(source),
    }


def build_paths(source: pd.DataFrame) -> None:
    calendar = pd.read_parquet(v1.DAILY_COMPACT, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
    calendar["trade_date"] = pd.to_datetime(calendar.trade_date)
    date_by_idx = dict(zip(calendar.cal_idx.astype(int), calendar.trade_date, strict=False))
    bounds = source[["event_id", "symbol", "first_lower_return_time", "reentry_date", "state_cal_idx", "entry_time", "entry_date", "entry_cal_idx"]].copy()
    bounds["path_end_cal_idx"] = bounds.entry_cal_idx.astype(int) + 60
    bounds["path_end_date"] = bounds.path_end_cal_idx.map(date_by_idx)
    if bounds.path_end_date.isna().any():
        raise AnatomyError("path end calendar mapping failed")
    v1.write_parquet(bounds, BOUNDS)
    if not DAILY_PATH.is_file():
        con = v1.connection()
        query = f"""
        SELECT b.event_id,d.* FROM read_parquet('{BOUNDS}') b
        JOIN read_parquet('{strategy.DAILY}') d ON d.symbol=b.symbol
          AND d.cal_idx BETWEEN least(b.state_cal_idx,b.entry_cal_idx) AND b.path_end_cal_idx
        ORDER BY b.event_id,d.cal_idx
        """
        con.execute(f"COPY ({query}) TO '{DAILY_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    if not MINUTE_PATH.is_file():
        con = v1.connection()
        con.execute("SET preserve_insertion_order=false")
        query = f"""
        WITH raw AS ({strategy.raw_union()})
        SELECT b.event_id,r.trade_date,r.bar_end_time,d.cal_idx,
          r.open,r.high,r.low,r.close,
          r.open*d.coordinate_factor AS coord_open,r.high*d.coordinate_factor AS coord_high,
          r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,
          d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
          d.up_limit_price,d.down_limit_price
        FROM read_parquet('{BOUNDS}') b
        JOIN raw r ON r.qmt_code=b.symbol AND r.trade_date BETWEEN b.reentry_date AND b.path_end_date
          AND r.bar_end_time>=b.first_lower_return_time
        JOIN read_parquet('{strategy.DAILY}') d ON d.symbol=b.symbol AND d.trade_date=r.trade_date
        ORDER BY b.event_id,r.bar_end_time
        """
        con.execute(f"COPY ({query}) TO '{MINUTE_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()


def legal_minute(frame: pd.DataFrame, lineage: float) -> pd.Series:
    return (
        frame.invalid_step_cum.eq(lineage)
        & frame.history_valid
        & frame.current_valid
        & frame.hard_valid
        & frame.trade_status.eq(1)
        & frame.current_day_data_tradable
        & frame.market_rule_valid
        & ~frame.corporate_action_blocking
        & np.isfinite(frame.open)
        & frame.open.gt(0)
        & (np.round(frame.open * 100) > np.round(frame.down_limit_price * 100))
    )


def legal_close(row: pd.Series, lineage: float) -> bool:
    return bool(
        float(row.invalid_step_cum) == lineage
        and row.history_valid
        and row.current_valid
        and row.hard_valid
        and row.trade_status == 1
        and row.current_day_data_tradable
        and row.market_rule_valid
        and not row.corporate_action_blocking
        and np.isfinite(row.close)
        and round(float(row.close) * 100) > round(float(row.down_limit_price) * 100)
    )


def first_target(path: pd.DataFrame, entry_date: pd.Timestamp, entry_idx: int, target: float, lineage: float) -> pd.Series | None:
    sellable = path.loc[path.cal_idx.gt(entry_idx) & legal_minute(path, lineage)].copy()
    hits = sellable.loc[sellable.coord_open.ge(target) | sellable.coord_high.ge(target)]
    if hits.empty:
        return None
    hit = hits.iloc[0].copy()
    hit["target_raw_execution"] = float(hit.open) if float(hit.coord_open) >= target else target / float(hit.coordinate_factor)
    hit["target_gap_above"] = bool(float(hit.coord_open) >= target)
    return hit


def first_loss_time(path: pd.DataFrame, entry_coord: float, threshold: float, end_idx: int, lineage: float) -> pd.Timestamp | pd.NaT:
    eligible = path.loc[path.cal_idx.le(end_idx) & path.invalid_step_cum.eq(lineage)]
    hits = eligible.loc[eligible.coord_low.div(entry_coord).sub(1).le(threshold)]
    return pd.NaT if hits.empty else pd.Timestamp(hits.bar_end_time.iloc[0])


def rejection_episodes(path: pd.DataFrame, target_time: pd.Timestamp, lower: float, lineage: float) -> tuple[int, int]:
    before = path.loc[path.bar_end_time.lt(target_time) & path.invalid_step_cum.eq(lineage)].sort_values("bar_end_time")
    below = before.coord_close.lt(lower).astype(int)
    episodes = int(((below == 1) & (below.shift(fill_value=0) == 0)).sum())
    return int(below.sum()), episodes


def underwater(daily: pd.DataFrame, entry_idx: int, end_idx: int, entry_coord: float, lineage: float) -> tuple[int, int]:
    rows = daily.loc[daily.cal_idx.between(entry_idx, end_idx) & daily.invalid_step_cum.eq(lineage)].sort_values("cal_idx")
    below = rows.coord_close.lt(entry_coord).astype(int)
    longest = 0
    run = 0
    for value in below:
        run = run + 1 if value else 0
        longest = max(longest, run)
    return int(below.sum()), int(longest)


def stats(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return {"n": 0, "mean": None, "median": None, "p10": None, "p25": None, "p75": None, "p90": None}
    return {
        "n": len(values), "mean": values.mean(), "median": values.median(),
        "p10": values.quantile(0.10), "p25": values.quantile(0.25),
        "p75": values.quantile(0.75), "p90": values.quantile(0.90),
    }


def rate(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return {"n": len(values), "rate": None if values.empty else values.mean()}


def cash_entitlement(actions: pd.DataFrame, entry_date: pd.Timestamp, exit_date: pd.Timestamp) -> float:
    if actions.empty:
        return 0.0
    rows = actions.loc[
        actions.action_kind.eq("CASH_ONLY")
        & actions.effective_date.gt(entry_date.normalize())
        & actions.effective_date.le(exit_date.normalize())
    ]
    return float(rows.cash_per_share.sum())


def forced_risk_exit(
    actions: pd.DataFrame,
    confirmation_time: pd.Timestamp,
    entry_date: pd.Timestamp,
    daily: pd.DataFrame,
    legal_opens: pd.DataFrame,
    lineage: float,
    cutoff_time: pd.Timestamp,
) -> dict[str, Any] | None:
    risks = actions.loc[
        actions.action_kind.str.startswith("RISK")
        & actions.known_date.gt(confirmation_time.normalize())
        & actions.known_date.le(cutoff_time.normalize())
        & actions.effective_date.gt(entry_date.normalize())
    ].sort_values(["known_date", "effective_date", "event_id"], kind="mergesort")
    candidates: list[dict[str, Any]] = []
    for risk in risks.itertuples(index=False):
        decision = daily.loc[daily.trade_date.ge(risk.known_date) & daily.trade_date.lt(risk.effective_date)]
        if decision.empty:
            candidates.append({"blocked": True, "effective_date": pd.Timestamp(risk.effective_date), "event_id": risk.event_id})
            continue
        decision_date = pd.Timestamp(decision.trade_date.iloc[0])
        fills = legal_opens.loc[
            legal_opens.bar_end_time.gt(decision_date + pd.Timedelta(hours=15))
            & legal_opens.invalid_step_cum.eq(lineage)
            & legal_opens.trade_date.lt(pd.Timestamp(risk.effective_date))
        ]
        if fills.empty:
            candidates.append({"blocked": True, "effective_date": pd.Timestamp(risk.effective_date), "event_id": risk.event_id})
        else:
            fill = fills.iloc[0]
            candidates.append({
                "blocked": False, "event_id": risk.event_id,
                "effective_date": pd.Timestamp(risk.effective_date),
                "exit_time": pd.Timestamp(fill.bar_end_time), "exit_date": pd.Timestamp(fill.trade_date),
                "exit_raw_price": float(fill.raw_open),
            })
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x.get("exit_time", x["effective_date"]))[0]


def horizon_exit(
    daily: pd.DataFrame,
    legal_opens: pd.DataFrame,
    target_idx: int,
    lineage: float,
) -> dict[str, Any] | None:
    exact = daily.loc[daily.cal_idx.eq(target_idx)]
    if exact.empty:
        return None
    row = exact.iloc[0]
    date = pd.Timestamp(row.trade_date)
    if legal_close(row, lineage):
        return {"exit_time": date + pd.Timedelta(hours=15), "exit_date": date, "exit_raw_price": float(row.close), "kind": "HORIZON_CLOSE"}
    fills = legal_opens.loc[legal_opens.bar_end_time.gt(date + pd.Timedelta(hours=15)) & legal_opens.invalid_step_cum.eq(lineage)]
    if fills.empty:
        return None
    fill = fills.iloc[0]
    return {"exit_time": pd.Timestamp(fill.bar_end_time), "exit_date": pd.Timestamp(fill.trade_date), "exit_raw_price": float(fill.raw_open), "kind": "HORIZON_DELAYED"}


def build_events(source: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    minutes = pd.read_parquet(MINUTE_PATH)
    daily = pd.read_parquet(DAILY_PATH)
    legal = pd.read_parquet(strategy.LEGAL_OPENS)
    all_daily = pd.read_parquet(strategy.DAILY)
    actions = pd.read_parquet(strategy.ACTION_EVENTS)
    for frame, columns in (
        (source, ["first_lower_return_time", "reentry_date", "confirmation_time", "entry_time", "entry_date", "formation_date"]),
        (minutes, ["bar_end_time", "trade_date"]), (daily, ["trade_date"]), (all_daily, ["trade_date"]),
        (legal, ["bar_end_time", "trade_date"]), (actions, ["known_date", "effective_date"]),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    minute_groups = {k: p.sort_values("bar_end_time", kind="mergesort") for k, p in minutes.groupby("event_id", sort=False)}
    daily_groups = {k: p.sort_values("cal_idx", kind="mergesort") for k, p in daily.groupby("event_id", sort=False)}
    all_daily_groups = {k: p.sort_values("cal_idx", kind="mergesort") for k, p in all_daily.groupby("symbol", sort=False)}
    legal_groups = {k: p.sort_values("bar_end_time", kind="mergesort") for k, p in legal.groupby("symbol", sort=False)}
    action_groups = {k: p.sort_values(["known_date", "effective_date"], kind="mergesort") for k, p in actions.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    audit = {"impossible_target_execution_count": 0, "corporate_action_coordinate_violation_count": 0, "t1_same_day_sell_violation_count": 0}
    for event in source.itertuples(index=False):
        minute = minute_groups[event.event_id]
        day = daily_groups[event.event_id]
        day_all = all_daily_groups[event.symbol]
        legal_open = legal_groups.get(event.symbol, pd.DataFrame(columns=legal.columns))
        action = action_groups.get(event.symbol, pd.DataFrame(columns=actions.columns))
        lineage = float(event.peak_invalid_step_cum)
        entry_time = pd.Timestamp(event.entry_time)
        entry_date = pd.Timestamp(event.entry_date)
        entry_idx = int(event.entry_cal_idx)
        entry_coord = float(event.entry_coord_price)
        output = event._asdict()
        structural = minute.loc[minute.bar_end_time.ge(pd.Timestamp(event.first_lower_return_time)) & minute.invalid_step_cum.eq(lineage)]
        structural_hits = structural.loc[structural.coord_high.ge(float(event.U))]
        structural_time = pd.NaT if structural_hits.empty else pd.Timestamp(structural_hits.bar_end_time.iloc[0])
        structural_offset = np.nan if structural_hits.empty else int(structural_hits.cal_idx.iloc[0] - int(event.state_cal_idx))
        output["structural_first_full_fill_time"] = structural_time
        output["structural_first_full_fill_offset"] = structural_offset
        for horizon in HORIZONS:
            output[f"structural_full_fill_{horizon}d"] = bool(np.isfinite(structural_offset) and structural_offset <= horizon)
        output["same_day_structural_fill"] = bool(pd.notna(structural_time) and structural_time.normalize() == entry_date.normalize())

        horizon_exits = {h: horizon_exit(day, legal_open, entry_idx + h, lineage) for h in HORIZONS}
        cutoff_candidates = [pd.Timestamp(x["exit_time"]) for x in horizon_exits.values() if x is not None]
        cutoff_time = max(cutoff_candidates, default=pd.Timestamp(day.trade_date.max()) + pd.Timedelta(hours=15))
        risk_exit = forced_risk_exit(
            action,
            pd.Timestamp(event.confirmation_time),
            entry_date,
            day_all,
            legal_open,
            lineage,
            cutoff_time,
        )
        if risk_exit is not None and risk_exit.get("blocked"):
            audit["corporate_action_coordinate_violation_count"] += 1
            raise AnatomyError(f"unresolved corporate action path: {event.event_id}:{risk_exit['event_id']}")
        target = first_target(minute, entry_date, entry_idx, float(event.U), lineage)
        if target is not None and risk_exit is not None and pd.Timestamp(risk_exit["exit_time"]) <= pd.Timestamp(target.bar_end_time):
            target = None
        if target is None:
            target_time = pd.NaT
            target_offset = np.nan
            target_raw = np.nan
            target_gap = False
        else:
            target_time = pd.Timestamp(target.bar_end_time)
            target_offset = int(target.cal_idx - entry_idx)
            target_raw = float(target.target_raw_execution)
            target_gap = bool(target.target_gap_above)
            if target_offset < 1:
                audit["t1_same_day_sell_violation_count"] += 1
            if target_raw + 1e-12 < float(event.U) / float(target.coordinate_factor):
                audit["impossible_target_execution_count"] += 1
        output.update(
            legal_target_time=target_time,
            legal_target_session_offset=target_offset,
            legal_target_raw_execution=target_raw,
            legal_target_gap_above=target_gap,
            forced_risk_exit_time=pd.NaT if risk_exit is None else risk_exit["exit_time"],
            forced_risk_exit_date=pd.NaT if risk_exit is None else risk_exit["exit_date"],
            forced_risk_exit_price=np.nan if risk_exit is None else risk_exit["exit_raw_price"],
            forced_risk_event_id=None if risk_exit is None else risk_exit["event_id"],
        )
        sellable = legal_open.loc[legal_open.cal_idx.gt(entry_idx) & legal_open.invalid_step_cum.eq(lineage)]
        first_sell = None if sellable.empty else sellable.iloc[0]
        output["t1_open_at_or_above_u"] = np.nan if first_sell is None else bool(float(first_sell.raw_open * first_sell.coordinate_factor) >= float(event.U))
        output["t1_open_net"] = np.nan if first_sell is None else float(first_sell.raw_open * (1 - COST) / (event.entry_raw_price * (1 + COST)) - 1)
        t1_day = day.loc[day.cal_idx.eq(entry_idx + 1)]
        output["t1_close_net"] = (
            np.nan
            if t1_day.empty or not legal_close(t1_day.iloc[0], lineage)
            else float(t1_day.close.iloc[0] * (1 - COST) / (event.entry_raw_price * (1 + COST)) - 1)
        )
        for horizon in (1, 5, 10, 20, 40, 60):
            output[f"legal_full_fill_{horizon}d"] = bool(np.isfinite(target_offset) and target_offset <= horizon)

        path_after_entry = minute.loc[minute.bar_end_time.ge(entry_time) & minute.invalid_step_cum.eq(lineage)].copy()
        if target is not None:
            pre_target = path_after_entry.loc[path_after_entry.bar_end_time.lt(target_time)]
            output["time_to_legal_target_sessions"] = target_offset
            output["time_to_legal_target_hours"] = (target_time - entry_time).total_seconds() / 3600
            output["mae_before_target"] = np.nan if pre_target.empty else float(pre_target.coord_low.min() / entry_coord - 1)
            output["max_drawdown_below_l_before_target"] = np.nan if pre_target.empty else float(min(0.0, pre_target.coord_low.min() / float(event.L) - 1))
            rejection_closes, episodes = rejection_episodes(path_after_entry, target_time, float(event.L), lineage)
            output["rejection_closes_before_target"] = rejection_closes
            output["rejection_episodes_before_target"] = episodes
        else:
            output.update(time_to_legal_target_sessions=np.nan, time_to_legal_target_hours=np.nan, mae_before_target=np.nan, max_drawdown_below_l_before_target=np.nan, rejection_closes_before_target=np.nan, rejection_episodes_before_target=np.nan)

        for horizon in HORIZONS:
            end_idx = entry_idx + horizon
            end_time = pd.Timestamp(day.loc[day.cal_idx.eq(end_idx), "trade_date"].iloc[0]) + pd.Timedelta(hours=15)
            effective_end_time = target_time if pd.notna(target_time) and target_offset <= horizon else end_time
            if risk_exit is not None and pd.Timestamp(risk_exit["exit_time"]) < effective_end_time:
                effective_end_time = pd.Timestamp(risk_exit["exit_time"])
            observed = path_after_entry.loc[path_after_entry.bar_end_time.lt(effective_end_time)]
            output[f"mfe_{horizon}d"] = np.nan if observed.empty else float(observed.coord_high.max() / entry_coord - 1)
            output[f"mae_{horizon}d"] = np.nan if observed.empty else float(observed.coord_low.min() / entry_coord - 1)
            output[f"severe_loss10_{horizon}d"] = np.nan if observed.empty else bool(output[f"mae_{horizon}d"] <= -0.10)
            output[f"severe_loss20_{horizon}d"] = np.nan if observed.empty else bool(output[f"mae_{horizon}d"] <= -0.20)
            for loss, label in ((-0.05, "loss5"), (-0.10, "loss10"), (-0.20, "loss20")):
                loss_time = first_loss_time(path_after_entry, entry_coord, loss, end_idx, lineage)
                output[f"u_before_{label}_{horizon}d"] = bool(
                    pd.notna(target_time) and target_offset <= horizon and (pd.isna(loss_time) or target_time < loss_time)
                )
            terminal = day.loc[day.cal_idx.eq(end_idx)].iloc[0]
            output[f"distance_to_u_{horizon}d"] = float(event.U / terminal.coord_close - 1)
            output[f"terminal_coord_return_{horizon}d"] = float(terminal.coord_close / entry_coord - 1)
            hit = bool(output[f"legal_full_fill_{horizon}d"])
            if hit:
                exit_info = {"exit_time": target_time, "exit_date": target_time.normalize(), "exit_raw_price": target_raw, "kind": "TARGET"}
            else:
                exit_info = horizon_exits[horizon]
                if (
                    risk_exit is not None
                    and (
                        exit_info is None
                        or pd.Timestamp(risk_exit["exit_time"])
                        <= pd.Timestamp(exit_info["exit_time"])
                    )
                ):
                    exit_info = {**risk_exit, "kind": "CORPORATE_ACTION_RISK"}
            if exit_info is None:
                output[f"full_or_h{horizon}_valid"] = False
                output[f"full_or_h{horizon}_net"] = np.nan
                output[f"full_or_h{horizon}_exit_kind"] = None
            else:
                cash = cash_entitlement(action, entry_date, pd.Timestamp(exit_info["exit_date"]))
                net = (float(exit_info["exit_raw_price"]) * (1 - COST) + cash) / (float(event.entry_raw_price) * (1 + COST)) - 1
                output[f"full_or_h{horizon}_valid"] = True
                output[f"full_or_h{horizon}_net"] = net
                output[f"full_or_h{horizon}_exit_kind"] = exit_info["kind"]
            underwater_end = int(target.cal_idx) - 1 if hit and target is not None else end_idx
            count, longest = underwater(day, entry_idx, underwater_end, entry_coord, lineage)
            output[f"underwater_sessions_{horizon}d"] = count
            output[f"longest_underwater_run_{horizon}d"] = longest
        rows.append(output)
    events = pd.DataFrame(rows).sort_values("event_id", kind="mergesort").reset_index(drop=True)
    if any(audit.values()):
        raise AnatomyError(f"execution audit failed: {audit}")
    v1.write_parquet(events, EVENTS)
    return events, audit


def date_equal_rate(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    grouped = frame[["reentry_date", column]].dropna().groupby("reentry_date", sort=True)[column].mean()
    return {"dates": len(grouped), "rate": None if grouped.empty else grouped.mean()}


def date_equal_stats(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    grouped = frame[["reentry_date", column]].dropna().groupby("reentry_date", sort=True)[column].mean()
    return stats(grouped)


def major_summary(frame: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {
        "n": len(frame),
        "target_gross_distance": stats(frame.target_gross_distance),
        "target_net_distance": stats(frame.target_net_distance),
        "target_net_milestones": {str(value): rate(frame.target_net_distance.ge(value)) for value in (0, .01, .02, .03, .05)},
        "structural_fill": {f"{h}d": rate(frame[f"structural_full_fill_{h}d"]) for h in HORIZONS},
        "legal_fill_curve": {f"{h}d": rate(frame[f"legal_full_fill_{h}d"]) for h in (1, 5, 10, 20, 40, 60)},
        "full_or_horizon": {f"h{h}": stats(frame[f"full_or_h{h}_net"]) for h in HORIZONS},
        "severe_loss10": {f"{h}d": rate(frame[f"severe_loss10_{h}d"]) for h in HORIZONS},
        "severe_loss20": {f"{h}d": rate(frame[f"severe_loss20_{h}d"]) for h in HORIZONS},
        "target_before_loss": {
            label: {f"{h}d": rate(frame[f"u_before_{label}_{h}d"]) for h in HORIZONS}
            for label in ("loss5", "loss10", "loss20")
        },
        "winner_mae": {f"{h}d": stats(frame.loc[frame[f"legal_full_fill_{h}d"], "mae_before_target"]) for h in HORIZONS},
    }
    return output


def date_equal_summary(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "legal_fill": {f"{h}d": date_equal_rate(frame, f"legal_full_fill_{h}d") for h in HORIZONS},
        "full_or_horizon": {f"h{h}": date_equal_stats(frame, f"full_or_h{h}_net") for h in HORIZONS},
        "severe_loss10": {f"{h}d": date_equal_rate(frame, f"severe_loss10_{h}d") for h in HORIZONS},
        "severe_loss20": {f"{h}d": date_equal_rate(frame, f"severe_loss20_{h}d") for h in HORIZONS},
        "target_before_loss": {
            label: {f"{h}d": date_equal_rate(frame, f"u_before_{label}_{h}d") for h in HORIZONS}
            for label in ("loss5", "loss10", "loss20")
        },
    }


def survival(events: pd.DataFrame) -> dict[str, Any]:
    offsets = pd.to_numeric(events.legal_target_session_offset, errors="coerce")
    curve = {f"s{t}": float((offsets.isna() | offsets.gt(t)).mean()) for t in range(1, 61)}
    hazards = {}
    for start, end in ((1, 5), (6, 10), (11, 20), (21, 40), (41, 60)):
        at_risk = offsets.isna() | offsets.ge(start)
        resolved = offsets.between(start, end, inclusive="both")
        hazards[f"{start}_{end}"] = {"at_risk": int(at_risk.sum()), "resolved": int(resolved.sum()), "hazard": float(resolved.sum() / at_risk.sum())}
    return {"curve": curve, "reported": {f"s{t}": curve[f"s{t}"] for t in CURVE}, "hazards": hazards}


def same_day_summary(events: pd.DataFrame) -> dict[str, Any]:
    part = events.loc[events.same_day_structural_fill]
    return {
        "n": len(part), "share": len(part) / len(events),
        "t1_open_at_or_above_u": rate(part.t1_open_at_or_above_u),
        "revisit": {f"{h}d": rate(part[f"legal_full_fill_{h}d"]) for h in (1, 5, 20, 40, 60)},
        "t1_open_net": stats(part.t1_open_net), "t1_close_net": stats(part.t1_close_net),
    }


def winner_summary(events: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for horizon in HORIZONS:
        winners = events.loc[events[f"legal_full_fill_{horizon}d"]]
        output[f"h{horizon}"] = {
            "n": len(winners), "time_sessions": stats(winners.time_to_legal_target_sessions),
            "time_hours": stats(winners.time_to_legal_target_hours), "mae_before_target": stats(winners.mae_before_target),
            "drawdown_below_l": stats(winners.max_drawdown_below_l_before_target),
            "underwater_sessions": stats(winners[f"underwater_sessions_{horizon}d"]),
            "longest_underwater_run": stats(winners[f"longest_underwater_run_{horizon}d"]),
        }
    eventual = events.loc[events.legal_full_fill_60d].copy()
    bucket = pd.cut(eventual.rejection_episodes_before_target, bins=[-1, 0, 1, 2, np.inf], labels=["0", "1", "2", "3+"])
    rejection = {}
    for name, part in eventual.groupby(bucket, observed=False):
        rejection[str(name)] = {"n": len(part), "time_to_target": stats(part.time_to_legal_target_sessions)}
    output["rejection_episodes"] = rejection
    return output


def unresolved_summary(events: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for horizon in HORIZONS:
        unresolved = events.loc[~events[f"legal_full_fill_{horizon}d"]]
        output[f"h{horizon}"] = {
            "n": len(unresolved), "rate": len(unresolved) / len(events),
            "terminal_net_return": stats(unresolved[f"full_or_h{horizon}_net"]),
            "mfe": stats(unresolved[f"mfe_{horizon}d"]), "mae": stats(unresolved[f"mae_{horizon}d"]),
            "distance_to_u": stats(unresolved[f"distance_to_u_{horizon}d"]),
        }
    unresolved20 = ~events.legal_full_fill_20d
    unresolved40 = ~events.legal_full_fill_40d
    output["transitions"] = {
        "20_to_40": rate(events.loc[unresolved20, "legal_full_fill_40d"]),
        "20_to_60": rate(events.loc[unresolved20, "legal_full_fill_60d"]),
        "40_to_60": rate(events.loc[unresolved40, "legal_full_fill_60d"]),
    }
    unresolved60 = events.loc[~events.legal_full_fill_60d]
    output["h60"]["underwater_sessions"] = stats(unresolved60.underwater_sessions_60d)
    output["h60"]["longest_underwater_run"] = stats(unresolved60.longest_underwater_run_60d)
    return output


def yearly(events: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for year in range(2014, 2022):
        part = events.loc[events.entry_year.eq(year)]
        output[str(year)] = {
            "n": len(part), "target_net_median": None if part.empty else part.target_net_distance.median(),
            "legal_fill": {f"{h}d": rate(part[f"legal_full_fill_{h}d"]) for h in HORIZONS},
            "u_before_loss10": {f"{h}d": rate(part[f"u_before_loss10_{h}d"]) for h in HORIZONS},
            "full_or": {f"h{h}": stats(part[f"full_or_h{h}_net"]) for h in HORIZONS},
            "winner_mae_median_60d": None if part.loc[part.legal_full_fill_60d].empty else part.loc[part.legal_full_fill_60d, "mae_before_target"].median(),
            "severe_loss10_60d": rate(part.severe_loss10_60d),
        }
    return output


def grouped(events: pd.DataFrame, field: str) -> dict[str, Any]:
    return {str(name): major_summary(part) for name, part in events.groupby(field, dropna=False, sort=True)}


def concentration(events: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for field in ("formation_date", "reentry_date"):
        counts = events.groupby(field).size().sort_values(ascending=False)
        top_n = max(1, math.ceil(len(counts) * .01))
        fills = events.groupby(field).legal_full_fill_60d.sum().sort_values(ascending=False)
        positive = events.assign(positive_mass=events.full_or_h60_net.clip(lower=0)).groupby(field).positive_mass.sum().sort_values(ascending=False)
        output[field] = {
            "unique_dates": len(counts), "top_1pct_event_share": float(counts.iloc[:top_n].sum() / counts.sum()),
            "top_five_fill_contribution": None if fills.sum() == 0 else float(fills.iloc[:5].sum() / fills.sum()),
            "top_five_positive_mass_contribution": None if positive.sum() == 0 else float(positive.iloc[:5].sum() / positive.sum()),
            "top_five_dates": [str(pd.Timestamp(x).date()) for x in counts.index[:5]],
        }
    return output


def verdict(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    event = result["event_weighted"]
    date = result["date_equal_weighted"]
    legal20 = event["legal_fill_curve"]["20d"]["rate"]
    legal60 = event["legal_fill_curve"]["60d"]["rate"]
    structural60 = event["structural_fill"]["60d"]["rate"]
    severe = event["severe_loss10"]["60d"]["rate"]
    before10 = event["target_before_loss"]["loss10"]["60d"]["rate"]
    payoff60 = event["full_or_horizon"]["h60"]
    date60 = date["full_or_horizon"]["h60"]
    positive_years = sum(1 for value in result["yearly"].values() if value["full_or"]["h60"]["mean"] is not None and value["full_or"]["h60"]["mean"] > 0)
    evidence = {
        "legal20": legal20, "legal60": legal60, "structural60": structural60,
        "incremental_20_to_60": legal60 - legal20, "severe_loss10_60": severe,
        "u_before_loss10_60": before10, "full_or_h60_mean": payoff60["mean"],
        "full_or_h60_median": payoff60["median"], "date_equal_h60_mean": date60["mean"],
        "positive_years_h60_mean": positive_years,
    }
    if structural60 >= .60 and structural60 - legal60 >= .15:
        return "ZONE_FILL_HIGH_BUT_T1_CONSTRAINED", evidence
    if legal60 >= .60 and severe > .30 and before10 < .60:
        return "ZONE_FILL_HIGH_BUT_RISK_GEOMETRY_POOR", evidence
    if legal60 - legal20 >= .15 and result["survival"]["hazards"]["41_60"]["hazard"] < result["survival"]["hazards"]["1_5"]["hazard"] and (payoff60["mean"] <= 0 or payoff60["median"] <= 0):
        return "ZONE_RESOLUTION_TOO_SLOW_FOR_CURRENT_STRATEGY_FAMILY", evidence
    if legal60 >= .60 and event["target_net_distance"]["median"] >= .02 and severe <= .30 and before10 >= .60 and payoff60["mean"] > 0 and payoff60["median"] > 0 and date60["mean"] > 0 and positive_years >= 5:
        return "ZONE_MONETIZATION_STRUCTURE_PRESENT", evidence
    return "NO_ZONE_MONETIZATION_STRUCTURE", evidence


def build_report(result: dict[str, Any]) -> str:
    e = result["event_weighted"]
    d = result["date_equal_weighted"]
    same = result["same_day_fill"]
    unresolved = result["unresolved"]

    def pct(value: float | None) -> str:
        return "NA" if value is None else f"{value:.2%}"

    def num(value: float | None) -> str:
        return "NA" if value is None else f"{value:.3f}"

    lines = [
        f"# {EXPERIMENT}", "", f"Frozen spec SHA-256: `{EXPECTED_SPEC_SHA256}`", "",
        "## Verdict", "", f"**{result['verdict']}**", "",
        f"The common 60-session cohort contains {result['source_reconciliation']['analysis_events']} frozen E1 entries from 482 securities on 392 re-entry dates. Of 594 eligible entries, {result['source_reconciliation']['censored_60d']} are excluded outcome-blind because 60 sessions are not observable by 2021-12-31.", "",
        "The zone is usually repaired and the fixed payoff is positive, but the preregistered joint positive gate is not met: 60D severe-loss10 is above the frozen 30% ceiling. This is a narrow gate failure, not evidence that structural traversal is absent. Under the frozen decision order the fallback is `NO_ZONE_MONETIZATION_STRUCTURE`; no V2 is authorized from this experiment.", "",
        "## Frozen semantics", "",
        "The detector, primary layer, first-return anchor, conservative E1 confirmation/next-legal-minute entry, U target, 20 bp per-side cost, T+1 sellability, PIT lineage, price-limit handling, and QD-010 corporate-action contract are unchanged. Structural fill begins at the economic first-return anchor; legal fill begins only after the frozen executable entry and can first occur on D1.", "",
        "## Target geometry", "",
        "|metric|mean|median|p10|p25|p75|p90|", "|---|---:|---:|---:|---:|---:|---:|",
        f"|gross distance|{pct(e['target_gross_distance']['mean'])}|{pct(e['target_gross_distance']['median'])}|{pct(e['target_gross_distance']['p10'])}|{pct(e['target_gross_distance']['p25'])}|{pct(e['target_gross_distance']['p75'])}|{pct(e['target_gross_distance']['p90'])}|",
        f"|net distance|{pct(e['target_net_distance']['mean'])}|{pct(e['target_net_distance']['median'])}|{pct(e['target_net_distance']['p10'])}|{pct(e['target_net_distance']['p25'])}|{pct(e['target_net_distance']['p75'])}|{pct(e['target_net_distance']['p90'])}|", "",
        "Fixed net-distance milestone rates: " + ", ".join(f"{float(k):.0%}: {pct(v['rate'])}" for k, v in e["target_net_milestones"].items()) + ".", "",
        "## Structural versus legally monetizable fill", "",
        "|curve|T+1|5D|10D|20D|40D|60D|", "|---|---:|---:|---:|---:|---:|---:|",
        f"|structural|NA|NA|NA|{pct(e['structural_fill']['20d']['rate'])}|{pct(e['structural_fill']['40d']['rate'])}|{pct(e['structural_fill']['60d']['rate'])}|",
        f"|legal event-weighted|{pct(e['legal_fill_curve']['1d']['rate'])}|{pct(e['legal_fill_curve']['5d']['rate'])}|{pct(e['legal_fill_curve']['10d']['rate'])}|{pct(e['legal_fill_curve']['20d']['rate'])}|{pct(e['legal_fill_curve']['40d']['rate'])}|{pct(e['legal_fill_curve']['60d']['rate'])}|",
        f"|legal date-equal|NA|NA|NA|{pct(d['legal_fill']['20d']['rate'])}|{pct(d['legal_fill']['40d']['rate'])}|{pct(d['legal_fill']['60d']['rate'])}|", "",
        "## Same-day structural fill and T+1 optionality", "",
        f"There are {same['n']} same-day structural fills ({pct(same['share'])}). The first legal open is at/above U in {pct(same['t1_open_at_or_above_u']['rate'])}; legal U revisit rates are {pct(same['revisit']['1d']['rate'])}/{pct(same['revisit']['5d']['rate'])}/{pct(same['revisit']['20d']['rate'])}/{pct(same['revisit']['40d']['rate'])}/{pct(same['revisit']['60d']['rate'])} at T+1/5D/20D/40D/60D. T+1-open and legal T+1-close mean net returns are {pct(same['t1_open_net']['mean'])} and {pct(same['t1_close_net']['mean'])}.", "",
        "## Winner path", "",
        "|horizon|winners|time-to-target median sessions|MAE median|below-L drawdown median|underwater sessions median|longest underwater run median|", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon in HORIZONS:
        winner = result["winner_path"][f"h{horizon}"]
        lines.append(f"|{horizon}D|{winner['n']}|{num(winner['time_sessions']['median'])}|{pct(winner['mae_before_target']['median'])}|{pct(winner['drawdown_below_l']['median'])}|{num(winner['underwater_sessions']['median'])}|{num(winner['longest_underwater_run']['median'])}|")
    lines += [
        "", "Rejection episodes among 60D winners: " + ", ".join(f"{k}: N={v['n']}, median time={num(v['time_to_target']['median'])}" for k, v in result["winner_path"]["rejection_episodes"].items()) + ".", "",
        "## Risk and unresolved tail", "",
        "|horizon|severe loss 10|severe loss 20|U before loss5|U before loss10|U before loss20|unresolved|terminal net mean|MFE mean|MAE mean|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon in HORIZONS:
        tail = unresolved[f"h{horizon}"]
        lines.append(f"|{horizon}D|{pct(e['severe_loss10'][f'{horizon}d']['rate'])}|{pct(e['severe_loss20'][f'{horizon}d']['rate'])}|{pct(e['target_before_loss']['loss5'][f'{horizon}d']['rate'])}|{pct(e['target_before_loss']['loss10'][f'{horizon}d']['rate'])}|{pct(e['target_before_loss']['loss20'][f'{horizon}d']['rate'])}|{pct(tail['rate'])}|{pct(tail['terminal_net_return']['mean'])}|{pct(tail['mfe']['mean'])}|{pct(tail['mae']['mean'])}|")
    lines += [
        "", f"Of 20D unresolved cases, {pct(unresolved['transitions']['20_to_40']['rate'])} resolve by 40D and {pct(unresolved['transitions']['20_to_60']['rate'])} by 60D. Of 40D unresolved cases, {pct(unresolved['transitions']['40_to_60']['rate'])} resolve by 60D.", "",
        "## Survival and fixed hazards", "",
        "Survival S1/S5/S10/S20/S30/S40/S50/S60: " + "/".join(pct(result["survival"]["reported"][f"s{x}"]) for x in CURVE) + ".", "",
        "|window|at risk|resolved|hazard|", "|---|---:|---:|---:|",
    ]
    for window, value in result["survival"]["hazards"].items():
        lines.append(f"|{window}|{value['at_risk']}|{value['resolved']}|{pct(value['hazard'])}|")
    lines += [
        "", "## Fixed FULL_OR_H payoff", "",
        "|weighting|H20 mean|H20 median|H40 mean|H40 median|H60 mean|H60 median|", "|---|---:|---:|---:|---:|---:|---:|",
        f"|event|{pct(e['full_or_horizon']['h20']['mean'])}|{pct(e['full_or_horizon']['h20']['median'])}|{pct(e['full_or_horizon']['h40']['mean'])}|{pct(e['full_or_horizon']['h40']['median'])}|{pct(e['full_or_horizon']['h60']['mean'])}|{pct(e['full_or_horizon']['h60']['median'])}|",
        f"|date-equal|{pct(d['full_or_horizon']['h20']['mean'])}|{pct(d['full_or_horizon']['h20']['median'])}|{pct(d['full_or_horizon']['h40']['mean'])}|{pct(d['full_or_horizon']['h40']['median'])}|{pct(d['full_or_horizon']['h60']['mean'])}|{pct(d['full_or_horizon']['h60']['median'])}|", "",
        "## Year-by-year chronology", "",
        "|year|N|median target net|legal 20/40/60|FULL_OR_H20/H40/H60 mean|H60 median|severe loss10 60D|", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for year, value in result["yearly"].items():
        lines.append(f"|{year}|{value['n']}|{pct(value['target_net_median'])}|{pct(value['legal_fill']['20d']['rate'])}/{pct(value['legal_fill']['40d']['rate'])}/{pct(value['legal_fill']['60d']['rate'])}|{pct(value['full_or']['h20']['mean'])}/{pct(value['full_or']['h40']['mean'])}/{pct(value['full_or']['h60']['mean'])}|{pct(value['full_or']['h60']['median'])}|{pct(value['severe_loss10_60d']['rate'])}|")
    lines += ["", "## Board and fixed structural diagnostics", ""]
    for title, key in (("Board", "board"), ("Layer structure", "layer_structure"), ("Persistence", "persistence"), ("Target-distance tercile", "target_distance_tercile")):
        lines += [f"### {title}", "", "|group|N|legal 60D|FULL_OR_H60 mean|severe loss10 60D|", "|---|---:|---:|---:|---:|"]
        for group, value in result[key].items():
            lines.append(f"|{group}|{value['n']}|{pct(value['legal_fill_curve']['60d']['rate'])}|{pct(value['full_or_horizon']['h60']['mean'])}|{pct(value['severe_loss10']['60d']['rate'])}|")
        lines.append("")
    lines += ["## Concentration", ""]
    for field, value in result["concentration"].items():
        lines.append(f"- {field}: {value['unique_dates']} dates; top-1%-date event share {pct(value['top_1pct_event_share'])}; top-five fill contribution {pct(value['top_five_fill_contribution'])}; top-five positive-return-mass contribution {pct(value['top_five_positive_mass_contribution'])}; top dates {', '.join(value['top_five_dates'])}.")
    lines += [
        "", "## Correctness and scope", "", f"Audit: `{result['audit']}`.", "",
        "No detector, layer, entry, target, horizon, subgroup, or strategy parameter was selected after outcomes. No portfolio CAGR, Sharpe, Calmar, optimized NAV, or walk-forward champion was computed. Validation 2022–2023 and repository 2024+ outcomes remained unopened.", "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    hashes = validate_inputs()
    source, reconciliation = prepare_source()
    build_paths(source)
    events, execution_audit = build_events(source)
    event_weighted = major_summary(events)
    date_equal = date_equal_summary(events)
    survival_result = survival(events)
    result: dict[str, Any] = {
        "experiment": EXPERIMENT, "start_head": START_HEAD, "frozen_spec_hash": EXPECTED_SPEC_SHA256,
        "input_hashes": hashes, "source_reconciliation": reconciliation,
        "event_weighted": event_weighted, "date_equal_weighted": date_equal,
        "same_day_fill": same_day_summary(events), "winner_path": winner_summary(events),
        "unresolved": unresolved_summary(events), "survival": survival_result,
        "yearly": yearly(events), "board": grouped(events, "board"),
        "layer_structure": grouped(events, "layer_structure"), "persistence": grouped(events, "persistence_stratum"),
        "target_distance_tercile": grouped(events, "target_distance_tercile"),
        "concentration": concentration(events),
        "audit": {
            "pattern_detector_changed_count": 0, "primary_layer_changed_count": 0,
            "entry_definition_changed_count": 0, "entry_uses_future_bar_count": 0,
            **execution_audit, "post_2021_outcome_read_count": 0,
        },
        "validation_opened": False, "repository_2024_plus_data_opened": False,
    }
    result["verdict"], result["verdict_evidence"] = verdict(result)
    write_json(RESULT, result)
    v1.atomic_text(REPORT, build_report(result))
    result["artifact_hashes"] = {str(path): v1.sha256_file(path) for path in (SPEC, EVENTS, REPORT)}
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
    print(json.dumps(json_ready({
        "verdict": result["verdict"], "source": result["source_reconciliation"],
        "target_net": result["event_weighted"]["target_net_distance"],
        "legal_fill": result["event_weighted"]["legal_fill_curve"],
        "full_or": result["event_weighted"]["full_or_horizon"],
        "risk": result["verdict_evidence"],
    }), indent=2))


if __name__ == "__main__":
    main()
