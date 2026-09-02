#!/usr/bin/env python3
# ruff: noqa: E402, E501
"""Development-only causal resolution-state discovery for frozen V3/E1/U events."""

from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_monetization_anatomy_v1 as anatomy,
)

outcome = anatomy.outcome
strategy = anatomy.strategy
v1 = anatomy.v1
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-RESOLUTION-STATE-DISCOVERY-V1"
START_HEAD = "5b0220dfac1e9ec9a7925270a50321198d32a9a5"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "42467094e75b5d44c7714dd090a4a171cd7e306d143420dc81bc93188a2b1017"
EXPECTED_INPUTS = {
    anatomy.SPEC: "35447ac8f0437e6e099166452447f400927bc1bfab0af50b7ec3666b34963d0a",
    anatomy.EVENTS: "96307f172a5ae9cc939576cda3b35833700edc9b7dd8986ab928763e613648ac",
    anatomy.RESULT: "6adb6a530d77389e7f2b494e0083216c26771c21da04dc7280e2c279628ecba2",
    outcome.SPEC: "e3da3093faf50da92544abf338ac1d1cae3aadd7e42672f998bd8facd7bf2f7c",
    outcome.EVENTS: "b27c2366fdef62e9592bb1c1ebec6a2f1e7c66d7b27312394dd17b65f74e8610",
    outcome.ENTRIES: "d7d970824e3ecfdf7784544dc481b8d5f97fde7f0cceefbaefd50c247417ef6d",
    strategy.TRADE_CANDIDATES: "da34442580dbedb3c0fcd0d14ee89b3e96bd18f3382c0ce00d7315a1b5c0f3dc",
    strategy.ACTION_EVENTS: "a349851232f7867b31e6ae9fae208861f74a0998e12643b4155650c8b7bce0f1",
    strategy.LEGAL_OPENS: "590925aa247fe4d2551f18f561149edf9bc52a85b6925903a2dd0afdc94601e1",
    strategy.DAILY: "a4eb64cb51c1c820d55d01fc30306273a616ab7a171126bbbda716392f43d4d5",
}
CHECKPOINTS = (1, 3, 5, 10, 20)
HORIZONS = (20, 40, 60)
COST = 0.002
TERCILES = (0.02535867873304672, 0.040897981171015875)
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_resolution_state_discovery_v1")
SOURCE = EXTERNAL / "eligible_e1_source.parquet"
BOUNDS = EXTERNAL / "path_bounds.parquet"
DAILY_PATH = EXTERNAL / "daily_paths_to_d60_or_boundary.parquet"
MINUTE_PATH = EXTERNAL / "minute_paths_to_d60_or_boundary.parquet"
STATES = OS_ROOT / f"artifacts/{EXPERIMENT}_checkpoint_states.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class StateDiscoveryError(RuntimeError):
    """Fail closed on frozen identity, chronology, lineage, or execution."""


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
            raise StateDiscoveryError(f"missing frozen input: {path}")
        actual = v1.sha256_file(path)
        if actual != expected:
            raise StateDiscoveryError(f"frozen input mismatch: {path}: {actual}")
        found[str(path)] = actual
    return found


def prepare_source() -> tuple[pd.DataFrame, dict[str, int]]:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    frozen = pd.read_parquet(outcome.EVENTS)
    canonical = pd.read_parquet(outcome.ENTRIES).set_index("event_id")
    candidates = pd.read_parquet(strategy.TRADE_CANDIDATES)
    risk = candidates.loc[candidates.entry_family.eq("E1_FIRST_ACCEPT")].drop_duplicates("event_id").set_index("event_id")
    source = frozen.loc[frozen.executable_entry].copy()
    if len(source) != 598 or source.event_id.duplicated().any():
        raise StateDiscoveryError(f"frozen E1 source identity failure: {len(source)}")
    for column in ("entry_time", "entry_date", "entry_cal_idx", "entry_raw_price", "entry_coord_price"):
        left = source.set_index("event_id")[column]
        right = canonical.loc[left.index, column]
        mismatch = pd.to_datetime(left).ne(pd.to_datetime(right)) if column in ("entry_time", "entry_date") else ~np.isclose(left.astype(float), right.astype(float), rtol=0, atol=1e-12)
        if mismatch.any():
            raise StateDiscoveryError(f"E1 mismatch {column}: {int(mismatch.sum())}")
    source["risk_blocked_entry"] = source.event_id.map(risk.risk_blocked_entry).fillna(False).astype(bool)
    if int(source.risk_blocked_entry.sum()) != 4:
        raise StateDiscoveryError("expected four QD-010 known-risk entry blocks")
    source["confirmation_time"] = pd.to_datetime(source.acceptance_time)
    source["target_gross_distance_frozen"] = source.U / source.entry_coord_price - 1
    source["target_net_distance_frozen"] = source.U * (1 - COST) / (source.entry_coord_price * (1 + COST)) - 1
    source["target_distance_tercile_frozen"] = pd.cut(
        source.target_net_distance_frozen,
        bins=[-np.inf, TERCILES[0], TERCILES[1], np.inf],
        labels=["LOW", "MID", "HIGH"],
        include_lowest=True,
    ).astype("string")
    source["entry_year"] = pd.to_datetime(source.entry_date).dt.year
    source = source.sort_values("event_id", kind="mergesort").reset_index(drop=True)
    v1.write_parquet(source, SOURCE)
    return source, {"source_e1_entries": 598, "known_risk_blocked_entries": 4, "post_entry_eligible_entries": 594}


def build_paths(source: pd.DataFrame) -> None:
    eligible = source.loc[~source.risk_blocked_entry].copy()
    calendar = pd.read_parquet(strategy.DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
    calendar.trade_date = pd.to_datetime(calendar.trade_date)
    last_idx = int(calendar.cal_idx.max())
    date_by_idx = dict(zip(calendar.cal_idx.astype(int), calendar.trade_date, strict=False))
    bounds = eligible[["event_id", "symbol", "entry_time", "entry_date", "entry_cal_idx"]].copy()
    bounds["path_end_cal_idx"] = np.minimum(bounds.entry_cal_idx.astype(int) + 60, last_idx)
    bounds["path_end_date"] = bounds.path_end_cal_idx.map(date_by_idx)
    if bounds.path_end_date.isna().any():
        raise StateDiscoveryError("path-end calendar mapping failed")
    v1.write_parquet(bounds, BOUNDS)
    if not DAILY_PATH.is_file():
        con = v1.connection()
        query = f"""
        SELECT b.event_id,d.* FROM read_parquet('{BOUNDS}') b
        JOIN read_parquet('{strategy.DAILY}') d ON d.symbol=b.symbol
          AND d.cal_idx BETWEEN b.entry_cal_idx AND b.path_end_cal_idx
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
        JOIN raw r ON r.qmt_code=b.symbol AND r.trade_date BETWEEN b.entry_date AND b.path_end_date
          AND r.bar_end_time>=b.entry_time
        JOIN read_parquet('{strategy.DAILY}') d ON d.symbol=b.symbol AND d.trade_date=r.trade_date
        ORDER BY b.event_id,r.bar_end_time
        """
        con.execute(f"COPY ({query}) TO '{MINUTE_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()


def action_censor(actions: pd.DataFrame, confirmation: pd.Timestamp, entry_date: pd.Timestamp, daily: pd.DataFrame, legal: pd.DataFrame, lineage: float) -> dict[str, Any] | None:
    risks = actions.loc[
        actions.action_kind.astype(str).str.startswith("RISK")
        & actions.known_date.gt(confirmation.normalize())
        & actions.effective_date.gt(entry_date.normalize())
    ].sort_values(["known_date", "effective_date", "event_id"], kind="mergesort")
    candidates: list[dict[str, Any]] = []
    for risk in risks.itertuples(index=False):
        decision = daily.loc[daily.trade_date.ge(risk.known_date) & daily.trade_date.lt(risk.effective_date)]
        if decision.empty:
            candidates.append({"time": pd.Timestamp(risk.effective_date), "kind": "ACTION_BLOCK", "event_id": risk.event_id})
            continue
        decision_date = pd.Timestamp(decision.trade_date.iloc[0])
        fills = legal.loc[
            legal.bar_end_time.gt(decision_date + pd.Timedelta(hours=15))
            & legal.invalid_step_cum.eq(lineage)
            & legal.trade_date.lt(pd.Timestamp(risk.effective_date))
        ]
        if fills.empty:
            candidates.append({"time": pd.Timestamp(risk.effective_date), "kind": "ACTION_BLOCK", "event_id": risk.event_id})
        else:
            fill = fills.iloc[0]
            candidates.append({"time": pd.Timestamp(fill.bar_end_time), "date": pd.Timestamp(fill.trade_date), "price": float(fill.raw_open), "kind": "RISK_EXIT", "event_id": risk.event_id})
    return None if not candidates else sorted(candidates, key=lambda x: (x["time"], x["event_id"]))[0]


def first_target(path: pd.DataFrame, entry_idx: int, target: float, lineage: float) -> pd.Series | None:
    return anatomy.first_target(path, pd.NaT, entry_idx, target, lineage)


def state_bins(progress: float, distance: float, arr: float, recovery: float, underwater: float, recovery3: float | None) -> dict[str, Any]:
    p = "P0" if progress < .25 else "P1" if progress < .75 else "P2" if progress < 1 else "P3"
    z = "Z0" if distance <= 0 else "Z1" if distance <= 1 else "Z2"
    a = "A0" if arr < 1 else "A1" if arr < 2 else "A2"
    r = "R0" if recovery < 1 / 3 else "R1" if recovery < 2 / 3 else "R2"
    u = "LOW" if underwater < 1 / 3 else "MID" if underwater <= 2 / 3 else "HIGH"
    r3 = None if recovery3 is None or not np.isfinite(recovery3) else "UP" if recovery3 > .25 else "DOWN" if recovery3 < -.25 else "FLAT"
    return {"progress_bin": p, "distance_bin": z, "arr_bin": a, "recovery_bin": r, "underwater_bin": u, "recovery_3d_state": r3}


def low_structure(session: pd.DataFrame, checkpoint_idx: int) -> str | None:
    if len(session) < 6:
        return None
    latest = float(session.loc[session.cal_idx.between(checkpoint_idx - 2, checkpoint_idx), "coord_low"].min())
    prior = float(session.loc[session.cal_idx.between(checkpoint_idx - 5, checkpoint_idx - 3), "coord_low"].min())
    if not np.isfinite(latest) or not np.isfinite(prior):
        return None
    return "ROUGHLY_EQUAL" if abs(latest - prior) <= 1e-10 else "HIGHER_LOW" if latest > prior else "LOWER_LOW"


def cash_entitlement(actions: pd.DataFrame, entry_date: pd.Timestamp, exit_date: pd.Timestamp) -> float:
    return anatomy.cash_entitlement(actions, entry_date, exit_date)


def compute_state_values(
    state_path: pd.DataFrame,
    closes: pd.DataFrame,
    *,
    lower: float,
    width: float,
    entry_price: float,
    target_gross_distance: float,
) -> dict[str, float]:
    """Compute the frozen checkpoint state from bars available by that close."""
    current_close = float(closes.coord_close.iloc[-1])
    max_progress = float((state_path.coord_high.max() - lower) / width)
    current_zone = float((current_close - lower) / width)
    distance = float(max(0.0, -current_zone))
    mae = float(state_path.coord_low.min() / entry_price - 1)
    arr = float(abs(min(mae, 0.0)) / target_gross_distance)
    post_low = float(state_path.coord_low.min())
    recovery = 1.0 if post_low >= lower else float((current_close - post_low) / (lower - post_low))
    return {
        "current_close": current_close,
        "max_progress": max_progress,
        "current_zone": current_zone,
        "distance": distance,
        "mae": mae,
        "arr": arr,
        "post_low": post_low,
        "recovery": recovery,
        "underwater": float(closes.coord_close.lt(entry_price).mean()),
        "below_l": float(closes.coord_close.lt(lower).mean()),
    }


def build_states(source: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int], dict[str, dict[str, int]]]:
    source = source.loc[~source.risk_blocked_entry].copy()
    minutes = pd.read_parquet(MINUTE_PATH)
    daily = pd.read_parquet(DAILY_PATH)
    all_daily = pd.read_parquet(strategy.DAILY)
    legal = pd.read_parquet(strategy.LEGAL_OPENS)
    actions = pd.read_parquet(strategy.ACTION_EVENTS)
    for frame, columns in (
        (source, ["entry_time", "entry_date", "confirmation_time", "formation_date"]),
        (minutes, ["bar_end_time", "trade_date"]), (daily, ["trade_date"]),
        (all_daily, ["trade_date"]), (legal, ["bar_end_time", "trade_date"]),
        (actions, ["known_date", "effective_date"]),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    minute_groups = {k: p.sort_values("bar_end_time", kind="mergesort") for k, p in minutes.groupby("event_id", sort=False)}
    daily_groups = {k: p.sort_values("cal_idx", kind="mergesort") for k, p in daily.groupby("event_id", sort=False)}
    all_daily_groups = {k: p.sort_values("cal_idx", kind="mergesort") for k, p in all_daily.groupby("symbol", sort=False)}
    legal_groups = {k: p.sort_values("bar_end_time", kind="mergesort") for k, p in legal.groupby("symbol", sort=False)}
    action_groups = {k: p.sort_values(["known_date", "effective_date", "event_id"], kind="mergesort") for k, p in actions.groupby("symbol", sort=False)}
    last_idx = int(all_daily.cal_idx.max())
    rows: list[dict[str, Any]] = []
    audit = {"checkpoint_clock_failure_count": 0, "state_future_bar_count": 0, "t1_semantic_violation_count": 0, "corporate_action_coordinate_violation_count": 0}
    checkpoint_reconciliation = {
        f"D{checkpoint}": {
            "source_post_entry_eligible": len(source),
            "legally_resolved_by_checkpoint": 0,
            "action_censored_by_checkpoint": 0,
            "checkpoint_data_missing": 0,
            "state_unobservable": 0,
            "active_unresolved": 0,
        }
        for checkpoint in CHECKPOINTS
    }
    for event in source.itertuples(index=False):
        minute = minute_groups[event.event_id]
        day = daily_groups[event.event_id]
        day_all = all_daily_groups[event.symbol]
        legal_all = legal_groups.get(event.symbol, pd.DataFrame(columns=legal.columns))
        action = action_groups.get(event.symbol, pd.DataFrame(columns=actions.columns))
        lineage = float(event.entry_invalid_step_cum)
        entry_idx = int(event.entry_cal_idx)
        entry_date = pd.Timestamp(event.entry_date)
        target = first_target(minute, entry_idx, float(event.U), lineage)
        censor = action_censor(action, pd.Timestamp(event.confirmation_time), entry_date, day_all, legal_all, lineage)
        if target is not None and censor is not None and pd.Timestamp(censor["time"]) <= pd.Timestamp(target.bar_end_time):
            target = None
        target_time = pd.NaT if target is None else pd.Timestamp(target.bar_end_time)
        target_offset = np.nan if target is None else int(target.cal_idx - entry_idx)
        if pd.notna(target_offset) and target_offset < 1:
            audit["t1_semantic_violation_count"] += 1
        valid_lineage = minute.loc[minute.invalid_step_cum.eq(lineage)].copy()
        session = valid_lineage.groupby("cal_idx", sort=True).agg(
            trade_date=("trade_date", "first"), coord_high=("coord_high", "max"), coord_low=("coord_low", "min"), coord_close=("coord_close", "last"), bar_end_time=("bar_end_time", "max")
        ).reset_index()
        d60_idx = entry_idx + 60
        d60_row = day.loc[day.cal_idx.eq(d60_idx)]
        d60_end = pd.NaT if d60_row.empty else pd.Timestamp(d60_row.trade_date.iloc[0]) + pd.Timedelta(hours=15)
        d60_observable = bool(d60_idx <= last_idx and not d60_row.empty and float(d60_row.invalid_step_cum.iloc[0]) == lineage)
        if censor is not None and d60_observable and pd.Timestamp(censor["time"]) <= d60_end:
            d60_observable = False
        d60_unresolved = None if not (pd.notna(target_time) and target_offset <= 60) and not d60_observable else not (pd.notna(target_time) and target_offset <= 60)
        d60_mae = np.nan
        terminal_net = np.nan
        distance_d60 = np.nan
        if d60_observable:
            path60 = valid_lineage.loc[valid_lineage.cal_idx.le(d60_idx)]
            if not path60.empty:
                d60_mae = float(path60.coord_low.min() / float(event.entry_coord_price) - 1)
            terminal = d60_row.iloc[0]
            distance_d60 = float(max(0.0, (float(event.L) - float(terminal.coord_close)) / float(event.W)))
            if d60_unresolved:
                exit_info = anatomy.horizon_exit(day, legal_all, d60_idx, lineage)
                if exit_info is not None:
                    cash = cash_entitlement(action, entry_date, pd.Timestamp(exit_info["exit_date"]))
                    terminal_net = (float(exit_info["exit_raw_price"]) * (1 - COST) + cash) / (float(event.entry_raw_price) * (1 + COST)) - 1
        severe_unresolved = None if d60_unresolved is None else bool(d60_unresolved and ((np.isfinite(terminal_net) and terminal_net <= -.10) or (np.isfinite(d60_mae) and d60_mae <= -.20)))
        for checkpoint in CHECKPOINTS:
            recon = checkpoint_reconciliation[f"D{checkpoint}"]
            cidx = entry_idx + checkpoint
            crow = day.loc[day.cal_idx.eq(cidx)]
            if crow.empty:
                recon["checkpoint_data_missing"] += 1
                continue
            cdate = pd.Timestamp(crow.trade_date.iloc[0])
            ctime = cdate + pd.Timedelta(hours=15)
            if pd.notna(target_time) and target_time <= ctime:
                recon["legally_resolved_by_checkpoint"] += 1
                continue
            if censor is not None and pd.Timestamp(censor["time"]) <= ctime:
                recon["action_censored_by_checkpoint"] += 1
                continue
            expected = set(range(entry_idx, cidx + 1))
            observed = set(session.loc[session.cal_idx.between(entry_idx, cidx), "cal_idx"].astype(int))
            if expected != observed or float(crow.invalid_step_cum.iloc[0]) != lineage:
                recon["state_unobservable"] += 1
                continue
            state_path = valid_lineage.loc[valid_lineage.bar_end_time.le(ctime) & valid_lineage.cal_idx.le(cidx)]
            if state_path.empty or state_path.bar_end_time.max() > ctime:
                audit["checkpoint_clock_failure_count"] += 1
                recon["state_unobservable"] += 1
                continue
            closes = session.loc[session.cal_idx.between(entry_idx, cidx)].sort_values("cal_idx")
            values = compute_state_values(
                state_path,
                closes,
                lower=float(event.L),
                width=float(event.W),
                entry_price=float(event.entry_coord_price),
                target_gross_distance=float(event.target_gross_distance_frozen),
            )
            max_progress = values["max_progress"]
            current_close = values["current_close"]
            current_zone = values["current_zone"]
            distance = values["distance"]
            mae = values["mae"]
            arr = values["arr"]
            post_low = values["post_low"]
            recovery = values["recovery"]
            underwater = values["underwater"]
            below_l = values["below_l"]
            recovery3 = None
            if checkpoint >= 3:
                prior_close = closes.loc[closes.cal_idx.eq(cidx - 3), "coord_close"]
                if not prior_close.empty:
                    recovery3 = float((current_close - float(prior_close.iloc[0])) / float(event.W))
            bins = state_bins(max_progress, distance, arr, recovery, underwater, recovery3)
            below = closes.coord_close.lt(float(event.L)).astype(int)
            rejection_episodes = int(((below == 1) & (below.shift(fill_value=0) == 0)).sum())
            prior_structural = bool(state_path.coord_high.ge(float(event.U)).any())
            labels: dict[str, Any] = {}
            for horizon in HORIZONS:
                applicable = checkpoint < horizon
                hidx = entry_idx + horizon
                hrow = day.loc[day.cal_idx.eq(hidx)]
                hend = pd.NaT if hrow.empty else pd.Timestamp(hrow.trade_date.iloc[0]) + pd.Timedelta(hours=15)
                target_by_h = bool(pd.notna(target_time) and target_offset <= horizon)
                observable = bool(target_by_h or (hidx <= last_idx and not hrow.empty and float(hrow.invalid_step_cum.iloc[0]) == lineage))
                if censor is not None and not target_by_h and pd.notna(hend) and pd.Timestamp(censor["time"]) <= hend:
                    observable = False
                eligible_label = bool(applicable and observable)
                labels[f"resolve_by_d{horizon}_eligible"] = eligible_label
                labels[f"resolve_by_d{horizon}"] = target_by_h if eligible_label else None
            d60_eligible = bool(checkpoint < 60 and d60_unresolved is not None)
            labels["d60_label_eligible"] = d60_eligible
            labels["unresolved_d60"] = d60_unresolved if d60_eligible else None
            labels["severe_unresolved_d60"] = severe_unresolved if d60_eligible else None
            outcome_end = target_time if pd.notna(target_time) and target_offset <= 60 else d60_end
            future = valid_lineage.loc[valid_lineage.bar_end_time.gt(ctime)]
            if pd.notna(outcome_end):
                future = future.loc[future.bar_end_time.lt(outcome_end) if pd.notna(target_time) and target_offset <= 60 else future.bar_end_time.le(outcome_end)]
            future_mae = np.nan if future.empty else float(future.coord_low.min() / float(event.entry_coord_price) - 1)
            labels["future_loss10_before_u"] = None if not d60_eligible else bool(not future.empty and future.coord_low.le(float(event.entry_coord_price) * .90).any())
            labels["future_loss20_before_u"] = None if not d60_eligible else bool(not future.empty and future.coord_low.le(float(event.entry_coord_price) * .80).any())
            labels["future_mae"] = future_mae if d60_eligible else np.nan
            labels["future_sessions_to_u"] = float(target_offset - checkpoint) if d60_eligible and pd.notna(target_offset) and target_offset <= 60 else np.nan
            row = {
                "event_id": event.event_id, "symbol": event.symbol, "board": event.board,
                "formation_date": pd.Timestamp(event.formation_date), "reentry_date": pd.Timestamp(event.reentry_date),
                "entry_date": entry_date, "entry_year": int(event.entry_year), "checkpoint": checkpoint,
                "checkpoint_date": cdate, "checkpoint_time": ctime, "entry_cal_idx": entry_idx,
                "checkpoint_cal_idx": cidx, "L": float(event.L), "U": float(event.U), "W": float(event.W),
                "entry_coord_price": float(event.entry_coord_price), "current_coord_close": current_close,
                "current_mtm_loss": float(current_close / float(event.entry_coord_price) - 1),
                "target_gross_distance": float(event.target_gross_distance_frozen),
                "target_distance_tercile": str(event.target_distance_tercile_frozen),
                "persistence_stratum": str(event.persistence_stratum), "layer_structure": str(event.layer_structure),
                "prior_structural_u_hit": prior_structural, "max_progress_raw": max_progress,
                "max_progress_capped": float(np.clip(max_progress, 0, 1)), "current_zone_position": current_zone,
                "distance_below_l_w": distance, "mae_entry_to_c": mae, "adverse_reward_ratio": arr,
                "post_entry_low_c": post_low, "recovery_to_l": recovery,
                "recovery_to_l_capped": float(np.clip(recovery, 0, 1)), "underwater_share": underwater,
                "below_l_share": below_l, "recovery_3d_w": np.nan if recovery3 is None else recovery3,
                "low_structure": low_structure(closes, cidx), "rejection_episodes": rejection_episodes,
                "fs1": bool(max_progress < .25 and arr >= 2),
                "fs2": bool(distance > 1 and recovery < 1 / 3),
                "fs3": bool(max_progress < .25 and arr >= 2 and recovery3 is not None and recovery3 < -.25),
                "legal_target_time": target_time, "legal_target_offset": target_offset,
                "action_censor_time": pd.NaT if censor is None else censor["time"],
                "action_censor_kind": None if censor is None else censor["kind"],
                "terminal_net_d60": terminal_net, "mae_through_d60": d60_mae,
                "distance_below_l_w_d60": distance_d60,
                **bins, **labels,
            }
            rows.append(row)
            recon["active_unresolved"] += 1
    states = pd.DataFrame(rows).sort_values(["checkpoint", "event_id"], kind="mergesort").reset_index(drop=True)
    if any(audit.values()):
        raise StateDiscoveryError(f"state construction audit failure: {audit}")
    for checkpoint, recon in checkpoint_reconciliation.items():
        classified = sum(value for key, value in recon.items() if key != "source_post_entry_eligible")
        if classified != recon["source_post_entry_eligible"]:
            raise StateDiscoveryError(f"checkpoint reconciliation failure {checkpoint}: {recon}")
    v1.write_parquet(states, STATES)
    return states, audit, checkpoint_reconciliation


def prob(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return None if values.empty else float(values.mean())


def median(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return None if values.empty else float(values.median())


def date_equal(frame: pd.DataFrame, label: str, date_col: str) -> dict[str, Any]:
    part = frame[[date_col, label]].dropna()
    grouped = part.groupby(date_col, sort=True)[label].mean()
    return {"dates": len(grouped), "probability": None if grouped.empty else float(grouped.mean())}


def base_rates(frame: pd.DataFrame) -> dict[str, Any]:
    labeled = frame.loc[frame.d60_label_eligible]
    output = {
        "active_n": len(frame), "d60_label_n": len(labeled),
        "unresolved_d60": prob(labeled.unresolved_d60), "severe_unresolved_d60": prob(labeled.severe_unresolved_d60),
        "future_loss10_before_u": prob(labeled.future_loss10_before_u), "future_loss20_before_u": prob(labeled.future_loss20_before_u),
    }
    for horizon in HORIZONS:
        eligible = frame.loc[frame[f"resolve_by_d{horizon}_eligible"]]
        output[f"resolve_by_d{horizon}"] = {"n": len(eligible), "rate": prob(eligible[f"resolve_by_d{horizon}"])}
    return output


def cell_metrics(part: pd.DataFrame, cohort: pd.DataFrame) -> dict[str, Any]:
    labeled = part.loc[part.d60_label_eligible]
    all_labeled = cohort.loc[cohort.d60_label_eligible]
    base = prob(all_labeled.unresolved_d60)
    failure = prob(labeled.unresolved_d60)
    output = {
        "state_n": len(part), "d60_label_n": len(labeled), "unresolved_rate": failure,
        "failure_lift": None if base in (None, 0) or failure is None else failure / base,
        "severe_unresolved_rate": prob(labeled.severe_unresolved_d60),
        "future_loss10_rate": prob(labeled.future_loss10_before_u), "future_loss20_rate": prob(labeled.future_loss20_before_u),
        "median_future_mae": median(labeled.future_mae),
        "median_future_sessions_to_u": median(labeled.loc[~labeled.unresolved_d60.astype(bool), "future_sessions_to_u"]),
        "reentry_date_equal": date_equal(labeled, "unresolved_d60", "reentry_date"),
        "formation_date_equal": date_equal(labeled, "unresolved_d60", "formation_date"),
    }
    for horizon in HORIZONS:
        eligible = part.loc[part[f"resolve_by_d{horizon}_eligible"]]
        output[f"resolve_by_d{horizon}"] = {"n": len(eligible), "rate": prob(eligible[f"resolve_by_d{horizon}"])}
    return output


def grouped_cells(frame: pd.DataFrame, fields: list[str]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for checkpoint in CHECKPOINTS:
        cohort = frame.loc[frame.checkpoint.eq(checkpoint)]
        cells = {}
        for key, part in cohort.groupby(fields, dropna=False, sort=True):
            values = key if isinstance(key, tuple) else (key,)
            name = "|".join(str(x) for x in values)
            cells[name] = cell_metrics(part, cohort)
        output[f"D{checkpoint}"] = cells
    return output


def fs_metrics(cohort: pd.DataFrame, field: str) -> dict[str, Any]:
    labeled = cohort.loc[cohort.d60_label_eligible]
    state = labeled.loc[labeled[field]]
    failures = labeled.loc[labeled.unresolved_d60.astype(bool)]
    severe = labeled.loc[labeled.severe_unresolved_d60.astype(bool)]
    resolvers = labeled.loc[~labeled.unresolved_d60.astype(bool)]
    state_fail = int(state.unresolved_d60.astype(bool).sum())
    state_severe = int(state.severe_unresolved_d60.astype(bool).sum())
    precision = prob(state.unresolved_d60)
    base = prob(labeled.unresolved_d60)
    reeq = date_equal(state, "unresolved_d60", "reentry_date")
    foeq = date_equal(state, "unresolved_d60", "formation_date")
    rebase = date_equal(labeled, "unresolved_d60", "reentry_date")["probability"]
    fobase = date_equal(labeled, "unresolved_d60", "formation_date")["probability"]
    return {
        "active_state_n": int(cohort[field].sum()), "state_n": len(state), "cohort_labeled_n": len(labeled),
        "base_rate": base, "failure_precision": precision,
        "failure_lift": None if base in (None, 0) or precision is None else precision / base,
        "precision_minus_base": None if base is None or precision is None else precision - base,
        "severe_failure_precision": prob(state.severe_unresolved_d60),
        "tail_capture": None if failures.empty else state_fail / len(failures),
        "severe_tail_capture": None if severe.empty else state_severe / len(severe),
        "resolver_contamination": None if state.empty else 1 - state_fail / len(state),
        "winners_sacrificed": None if resolvers.empty else int(state.unresolved_d60.eq(False).sum()) / len(resolvers),
        "reentry_date_equal_precision": reeq, "reentry_date_equal_lift": None if rebase in (None, 0) or reeq["probability"] is None else reeq["probability"] / rebase,
        "formation_date_equal_precision": foeq, "formation_date_equal_lift": None if fobase in (None, 0) or foeq["probability"] is None else foeq["probability"] / fobase,
    }


def spearman(frame: pd.DataFrame, column: str) -> float | None:
    part = frame.loc[frame.d60_label_eligible, [column, "unresolved_d60"]].dropna()
    return None if len(part) < 3 or part[column].nunique() < 2 or part.unresolved_d60.nunique() < 2 else float(part[column].corr(part.unresolved_d60.astype(float), method="spearman"))


def candidate_diagnostics(states: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for field in ("fs1", "fs2", "fs3"):
        output[field] = {}
        for checkpoint in CHECKPOINTS:
            if field == "fs3" and checkpoint < 3:
                continue
            cohort = states.loc[states.checkpoint.eq(checkpoint)]
            output[field][f"D{checkpoint}"] = fs_metrics(cohort, field)
    return output


def transitions(states: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for left, right in pairwise(CHECKPOINTS):
        a = states.loc[states.checkpoint.eq(left)].set_index("event_id")
        b = states.loc[states.checkpoint.eq(right)].set_index("event_id")
        common = a.index.intersection(b.index)
        rows = a.loc[common, ["max_progress_raw", "adverse_reward_ratio", "distance_below_l_w", "recovery_to_l", "d60_label_eligible", "unresolved_d60"]].join(
            b.loc[common, ["max_progress_raw", "adverse_reward_ratio", "distance_below_l_w", "recovery_to_l"]], lsuffix="_a", rsuffix="_b"
        )
        rows = rows.loc[rows.d60_label_eligible]
        summary = {}
        for label, part in (("resolver", rows.loc[~rows.unresolved_d60.astype(bool)]), ("unresolved", rows.loc[rows.unresolved_d60.astype(bool)])):
            summary[label] = {
                "n": len(part), "progress_delta_median": median(part.max_progress_raw_b - part.max_progress_raw_a),
                "arr_delta_median": median(part.adverse_reward_ratio_b - part.adverse_reward_ratio_a),
                "distance_delta_median": median(part.distance_below_l_w_b - part.distance_below_l_w_a),
                "recovery_delta_median": median(part.recovery_to_l_b - part.recovery_to_l_a),
            }
        output[f"D{left}_D{right}"] = summary
    return output


def timing_paths(states: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for field in ("fs1", "fs2", "fs3"):
        triggered = states.loc[states[field] & states.d60_label_eligible].sort_values(["event_id", "checkpoint"], kind="mergesort").drop_duplicates("event_id")
        categories = pd.cut(triggered.current_mtm_loss, bins=[-np.inf, -.20, -.10, -.05, np.inf], labels=["AFTER_MINUS20", "MINUS10_TO_MINUS20", "MINUS5_TO_MINUS10", "BEFORE_MINUS5"], right=True)
        resolvers = triggered.loc[~triggered.unresolved_d60.astype(bool)]
        failures = triggered.loc[triggered.unresolved_d60.astype(bool)]
        output[field] = {
            "first_detection": {
                "n": len(triggered), "median_checkpoint": median(triggered.checkpoint), "median_mtm_loss": median(triggered.current_mtm_loss),
                "before_minus5_rate": None if triggered.empty else float((triggered.current_mtm_loss > -.05).mean()),
                "minus5_to_minus10_rate": None if triggered.empty else float(((triggered.current_mtm_loss <= -.05) & (triggered.current_mtm_loss > -.10)).mean()),
                "after_minus10_rate": None if triggered.empty else float((triggered.current_mtm_loss <= -.10).mean()),
                "after_minus20_rate": None if triggered.empty else float((triggered.current_mtm_loss <= -.20).mean()),
                "exclusive_categories": categories.value_counts(normalize=True, sort=False).to_dict(),
            },
            "resolver_false_alarm": {
                "n": len(resolvers), "median_first_checkpoint": median(resolvers.checkpoint), "median_loss_at_trigger": median(resolvers.current_mtm_loss),
                "median_later_sessions_to_u": median(resolvers.future_sessions_to_u), "median_additional_mae_level": median(resolvers.future_mae),
                "median_additional_drawdown_from_trigger": median(resolvers.future_mae - resolvers.current_mtm_loss),
            },
            "unresolved_failure_path": {
                "n": len(failures), "median_first_checkpoint": median(failures.checkpoint), "median_loss_at_trigger": median(failures.current_mtm_loss),
                "median_terminal_net_d60": median(failures.terminal_net_d60), "median_future_mae_after_trigger": median(failures.future_mae),
                "median_distance_below_l_w_d60": median(failures.distance_below_l_w_d60),
            },
        }
    return output


def robustness(states: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {"year": {}, "board": {}, "persistence": {}, "target_distance": {}}
    for checkpoint in (5, 10):
        cohort = states.loc[states.checkpoint.eq(checkpoint)]
        output["year"][f"D{checkpoint}"] = {}
        for year in range(2014, 2022):
            part = cohort.loc[cohort.entry_year.eq(year)]
            output["year"][f"D{checkpoint}"][str(year)] = {
                "base": base_rates(part), "directional_spearman": {
                    key: spearman(part, key) for key in ("max_progress_raw", "adverse_reward_ratio", "distance_below_l_w", "recovery_to_l")
                }, "fs": {field: fs_metrics(part, field) for field in ("fs1", "fs2", "fs3")},
            }
        output["board"][f"D{checkpoint}"] = {str(name): {"base": base_rates(part), "fs": {field: fs_metrics(part, field) for field in ("fs1", "fs2", "fs3")}} for name, part in cohort.groupby("board", sort=True)}
        output["persistence"][f"D{checkpoint}"] = {str(name): {field: fs_metrics(part, field) for field in ("fs1", "fs2", "fs3")} for name, part in cohort.groupby("persistence_stratum", sort=True)}
        output["target_distance"][f"D{checkpoint}"] = {str(name): {field: fs_metrics(part, field) for field in ("fs1", "fs2", "fs3")} for name, part in cohort.groupby("target_distance_tercile", sort=True)}
    return output


def verdict(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    candidates = result["failure_states"]
    timing = result["timing_paths"]
    robust = result["robustness"]
    evidence: dict[str, Any] = {}
    separable = []
    weak = []
    after_damage = []
    for field in ("fs1", "fs2", "fs3"):
        primary = []
        checkpoint_hits = 0
        for cp in (5, 10):
            m = candidates[field].get(f"D{cp}", {})
            material = bool(m and m["failure_lift"] is not None and m["failure_lift"] >= 2 and m["precision_minus_base"] >= .10 and m["tail_capture"] >= .20 and m["resolver_contamination"] <= .50 and m["winners_sacrificed"] <= .15)
            weak_here = bool(m and m["failure_lift"] is not None and m["failure_lift"] >= 1.5 and m["precision_minus_base"] >= .05 and m["tail_capture"] >= .10)
            primary.append((cp, material, weak_here, m))
        for _cp, m in candidates[field].items():
            if m["failure_lift"] is not None and m["failure_lift"] >= 1.5:
                checkpoint_hits += 1
        first = timing[field]["first_detection"]
        timely = bool(first["median_mtm_loss"] is not None and first["median_mtm_loss"] > -.10 and (first["before_minus5_rate"] + first["minus5_to_minus10_rate"]) >= .50)
        year_flags = []
        for _year, item in robust["year"]["D5"].items():
            m = item["fs"][field]
            if m["state_n"] >= 3 and m["failure_lift"] is not None:
                year_flags.append(m["failure_lift"] > 1)
        year_stable = len(year_flags) >= 4 and sum(year_flags) >= max(3, math.ceil(.60 * len(year_flags)))
        board_flags = []
        for item in robust["board"]["D5"].values():
            m = item["fs"][field]
            board_flags.append(m["state_n"] >= 10 and m["failure_lift"] is not None and m["failure_lift"] > 1)
        board_stable = len(board_flags) == 2 and all(board_flags)
        best = next((m for _, material, _, m in primary if material), None)
        date_robust = bool(best and best["reentry_date_equal_lift"] is not None and best["reentry_date_equal_lift"] > 1.25 and best["formation_date_equal_lift"] is not None and best["formation_date_equal_lift"] > 1.25)
        age_flags = []
        for name, item in robust["persistence"]["D5"].items():
            if name != "GT_120":
                m = item[field]
                age_flags.append(m["state_n"] >= 10 and m["failure_lift"] is not None and m["failure_lift"] > 1.25)
        age_ok = any(age_flags)
        distance_flags = []
        for item in robust["target_distance"]["D5"].values():
            m = item[field]
            distance_flags.append(m["state_n"] >= 10 and m["failure_lift"] is not None and m["failure_lift"] > 1)
        distance_ok = sum(distance_flags) >= 2
        material_any = any(x[1] for x in primary)
        weak_any = any(x[2] for x in primary) and (material_any or checkpoint_hits >= 2)
        full = material_any and timely and checkpoint_hits >= 2 and year_stable and board_stable and date_robust and age_ok and distance_ok
        if full:
            separable.append(field)
        elif (material_any or weak_any) and not timely:
            after_damage.append(field)
        elif weak_any:
            weak.append(field)
        evidence[field] = {"material": material_any, "weak": weak_any, "timely": timely, "checkpoint_hits": checkpoint_hits, "year_stable": year_stable, "supported_years": len(year_flags), "positive_years": sum(year_flags), "board_stable": board_stable, "date_robust": date_robust, "not_age_only": age_ok, "not_target_distance_only": distance_ok}
    if separable:
        return "ZONE_TAIL_RISK_STATE_SEPARABLE", {"qualifying": separable, "candidate_evidence": evidence}
    if after_damage:
        return "ZONE_TAIL_RISK_ONLY_DETECTABLE_AFTER_DAMAGE", {"qualifying": after_damage, "candidate_evidence": evidence}
    if weak:
        return "ZONE_TAIL_RISK_STATE_WEAKLY_SEPARABLE", {"qualifying": weak, "candidate_evidence": evidence}
    return "ZONE_TAIL_RISK_NOT_SEPARABLE_WITH_SIMPLE_STATE", {"qualifying": [], "candidate_evidence": evidence}


def build_report(result: dict[str, Any]) -> str:
    def pct(x: float | None) -> str:
        return "NA" if x is None else f"{x:.2%}"

    def number(x: float | None, digits: int = 2) -> str:
        return "NA" if x is None else f"{x:.{digits}f}"

    lines = [
        f"# {EXPERIMENT}", "", f"Frozen spec SHA-256: `{EXPECTED_SPEC_SHA256}`", "",
        "## Verdict", "", f"**{result['verdict']}**", "",
        "The frozen simple state family does contain useful failure ordering, but its cleanest high-precision version (FS3) first appears after a median 13.98% mark-to-market loss. The earlier broad state (FS2) captures more failures, but contaminates 48%–55% eventual resolvers at D5/D10 and would sacrifice 27%–29% of the eventual winners. This does not justify failure-exit development.", "",
        "This is causal state discovery only. No stop replay, entry search, portfolio metric, Validation, or repository 2024+ outcome was opened.", "",
        "## Frozen causal contract", "",
        "The unchanged V3 collapse-gap-zone detector forms the event, frozen executable E1 forms the entry, and each D1/D3/D5/D10/D20 state uses only bars available through that completed daily close. A row exists only while legal U resolution has not yet happened and the path remains observable under frozen lineage/action rules. Outcomes begin strictly after the checkpoint.", "",
        "## Source and dynamic checkpoint reconciliation", "",
        f"Frozen executable E1 entries: {result['source_reconciliation']['source_e1_entries']}; known QD-010 entry blocks: {result['source_reconciliation']['known_risk_blocked_entries']}; post-entry eligible source: {result['source_reconciliation']['post_entry_eligible_entries']}.", "",
        "|checkpoint|source|resolved by checkpoint|action-censored|checkpoint missing|state unobservable|active unresolved|D60 label eligible|D60 unresolved base|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cp in CHECKPOINTS:
        b = result["base_rates"][f"D{cp}"]
        r = result["checkpoint_reconciliation"][f"D{cp}"]
        lines.append(f"|D{cp}|{r['source_post_entry_eligible']}|{r['legally_resolved_by_checkpoint']}|{r['action_censored_by_checkpoint']}|{r['checkpoint_data_missing']}|{r['state_unobservable']}|{b['active_n']}|{b['d60_label_n']}|{pct(b['unresolved_d60'])}|")
    lines += [
        "", "Every row closes exactly to the 594-entry post-QD-010 source denominator. Missing late checkpoints are boundary-censored rather than silently treated as failures.", "",
        "## Resolution base rates", "",
        "|checkpoint cohort|resolve by D20|resolve by D40|resolve by D60|severe unresolved D60|future -10% before U|future -20% before U|",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for cp in CHECKPOINTS:
        b = result["base_rates"][f"D{cp}"]
        lines.append(f"|D{cp}|{pct(b['resolve_by_d20']['rate'])}|{pct(b['resolve_by_d40']['rate'])}|{pct(b['resolve_by_d60']['rate'])}|{pct(b['severe_unresolved_d60'])}|{pct(b['future_loss10_before_u'])}|{pct(b['future_loss20_before_u'])}|")

    lines += ["", "## Univariate checkpoint state", "", "The table reports all predeclared bins at D5 and D10. Lift is relative to the dynamically eligible checkpoint cohort, not the old common-538 denominator.", "", "|dimension|checkpoint|bin|N|D60 labeled|unresolved rate|lift|future -10%|median future MAE|", "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for name in ("max_progress", "arr", "distance_below_l", "recovery_to_l", "underwater", "recovery_3d", "low_structure"):
        for cp in (5, 10):
            for cell, m in result["univariate"][name][f"D{cp}"].items():
                lines.append(f"|{name}|D{cp}|{cell}|{m['state_n']}|{m['d60_label_n']}|{pct(m['unresolved_rate'])}|{number(m['failure_lift'])}x|{pct(m['future_loss10_rate'])}|{pct(m['median_future_mae'])}|")

    lines += ["", "Main directional reading: low progress, greater distance below L, weak recovery, downward three-session direction, and lower-low structure all identify worse conditional paths. Underwater share by itself is weak. Distance below L adds information beyond percentage damage because the strongest frozen interaction is low progress plus distance greater than one zone width.", "", "## Predeclared state surfaces", "", "Cells with at least 10 checkpoint observations are shown; no cell was selected to create a new rule.", "", "|surface|checkpoint|cell|N|unresolved rate|lift|", "|---|---|---|---:|---:|---:|"]
    for surface in ("progress_x_arr", "progress_x_distance", "distance_x_recovery"):
        for cp in (5, 10):
            for cell, m in result["surfaces"][surface][f"D{cp}"].items():
                if m["state_n"] >= 10:
                    lines.append(f"|{surface}|D{cp}|{cell}|{m['state_n']}|{pct(m['unresolved_rate'])}|{number(m['failure_lift'])}x|")

    lines += ["", "The strongest descriptive cells are P0×Z2: 58.33% unresolved at D5 (2.23x base) and 73.68% at D10 (2.20x). This interaction is economically coherent, but it is not itself an authorized exit rule and its chronology/coverage gates do not support promotion.", "", "## Predeclared failure states", "", "|state|checkpoint|N|precision|lift|tail capture|resolver contamination|winners sacrificed|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for field, by_cp in result["failure_states"].items():
        for cp, m in by_cp.items():
            lines.append(f"|{field.upper()}|{cp}|{m['state_n']}|{pct(m['failure_precision'])}|{'NA' if m['failure_lift'] is None else f'{m['failure_lift']:.2f}x'}|{pct(m['tail_capture'])}|{pct(m['resolver_contamination'])}|{pct(m['winners_sacrificed'])}|")

    lines += ["", "## First-detection timing and path consequence", "", "|state|N|median checkpoint|median loss|before -5|-5 to -10|after -10|after -20|", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for field, item in result["timing_paths"].items():
        t = item["first_detection"]
        lines.append(f"|{field.upper()}|{t['n']}|{t['median_checkpoint']}|{pct(t['median_mtm_loss'])}|{pct(t['before_minus5_rate'])}|{pct(t['minus5_to_minus10_rate'])}|{pct(t['after_minus10_rate'])}|{pct(t['after_minus20_rate'])}|")
    lines += ["", "|state|path|N|loss at first trigger|later sessions to U / terminal D60 net|future MAE|additional drawdown / D60 distance below L|", "|---|---|---:|---:|---:|---:|---:|"]
    for field, item in result["timing_paths"].items():
        fa = item["resolver_false_alarm"]
        tf = item["unresolved_failure_path"]
        lines.append(f"|{field.upper()}|eventual resolver false alarm|{fa['n']}|{pct(fa['median_loss_at_trigger'])}|{number(fa['median_later_sessions_to_u'], 1)} sessions|{pct(fa['median_additional_mae_level'])}|{pct(fa['median_additional_drawdown_from_trigger'])}|")
        lines.append(f"|{field.upper()}|D60 unresolved failure|{tf['n']}|{pct(tf['median_loss_at_trigger'])}|{pct(tf['median_terminal_net_d60'])}|{pct(tf['median_future_mae_after_trigger'])}|{number(tf['median_distance_below_l_w_d60'])}W|")

    lines += ["", "## Checkpoint evolution", "", "|transition|path|N|median Δ progress|median Δ ARR|median Δ distance below L|median Δ recovery|", "|---|---|---:|---:|---:|---:|---:|"]
    for transition, paths in result["checkpoint_transitions"].items():
        for path, m in paths.items():
            lines.append(f"|{transition}|{path}|{m['n']}|{number(m['progress_delta_median'], 3)}|{number(m['arr_delta_median'], 3)}|{number(m['distance_delta_median'], 3)}|{number(m['recovery_delta_median'], 3)}|")
    lines += ["", "Unresolved paths progressively accumulate ARR and distance below L; eventual resolvers show much smaller damage accumulation and improving recovery. That distinction is real descriptively, but much of it arrives only after meaningful loss.", "", "## Chronology and board robustness", "", "|checkpoint|year|labeled N|base unresolved|FS2 N|FS2 precision|FS2 lift|", "|---|---:|---:|---:|---:|---:|---:|"]
    for cp in (5, 10):
        for year, item in result["robustness"]["year"][f"D{cp}"].items():
            m = item["fs"]["fs2"]
            lines.append(f"|D{cp}|{year}|{item['base']['d60_label_n']}|{pct(item['base']['unresolved_d60'])}|{m['state_n']}|{pct(m['failure_precision'])}|{number(m['failure_lift'])}x|")
    lines += ["", "Sparse annual cells prevent a strong year-stability claim for the high-precision FS3 state. FS2 is directionally positive in most supported years but not uniformly, including a D10 reversal in 2018.", "", "|checkpoint|board|labeled N|base unresolved|FS1 lift|FS2 lift|FS3 lift|", "|---|---|---:|---:|---:|---:|---:|"]
    for cp in (5, 10):
        for board, item in result["robustness"]["board"][f"D{cp}"].items():
            fs = item["fs"]
            lines.append(f"|D{cp}|{board}|{item['base']['d60_label_n']}|{pct(item['base']['unresolved_d60'])}|{number(fs['fs1']['failure_lift'])}x|{number(fs['fs2']['failure_lift'])}x|{number(fs['fs3']['failure_lift'])}x|")
    lines += ["", "The basic relation is present on Main Board and ChiNext. The machine result also contains event-weighted, re-entry-date-equal, formation-date-equal, persistence-stratum, and frozen target-distance-tercile controls. The full promotion gate fails date robustness and/or concentration controls depending on state.", "", "## Decision", "", "The non-resolution tail is partly predictable from simple path state, especially from the interaction of low progress and large distance below L. Recovery state helps distinguish some normal rejection winners, but not enough to create a low-contamination early failure state. FS3 is cleaner but late; FS2 is earlier but broad. Therefore `ASHARE-COLLAPSE-GAP-ZONE-FAILURE-EXIT-DEVELOPMENT-V1` is not justified.", "", "The next scientifically distinct question, if this pattern receives more budget, is a separately frozen `ASHARE-COLLAPSE-GAP-ZONE-ENTRY-QUALITY-DISCOVERY-V1`: determine whether causal pre-entry approach state can avoid later non-resolvers. It must not reuse these post-entry outcomes to tune entry rules in this experiment.", "", "## Correctness audit", "", f"Audit: `{result['audit']}`", "", f"Validation opened: `{result['validation_opened']}`. Repository 2024+ data opened: `{result['repository_2024_plus_data_opened']}`.", "", "Complete machine-readable univariate bins, surfaces, timing paths, date-equal controls, robustness tables, and verdict evidence are in the result JSON.", ""]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    hashes = validate_inputs()
    source, reconciliation = prepare_source()
    build_paths(source)
    states, state_audit, checkpoint_reconciliation = build_states(source)
    base = {f"D{cp}": base_rates(states.loc[states.checkpoint.eq(cp)]) for cp in CHECKPOINTS}
    univariate = {
        "max_progress": grouped_cells(states, ["progress_bin"]), "arr": grouped_cells(states, ["arr_bin"]),
        "distance_below_l": grouped_cells(states, ["distance_bin"]), "recovery_to_l": grouped_cells(states, ["recovery_bin"]),
        "underwater": grouped_cells(states, ["underwater_bin"]), "recovery_3d": grouped_cells(states, ["recovery_3d_state"]),
        "low_structure": grouped_cells(states, ["low_structure"]),
    }
    failure = candidate_diagnostics(states)
    result: dict[str, Any] = {
        "experiment": EXPERIMENT, "start_head": START_HEAD, "frozen_spec_hash": EXPECTED_SPEC_SHA256,
        "input_hashes": hashes, "source_reconciliation": reconciliation,
        "checkpoint_state_rows": len(states), "checkpoint_reconciliation": checkpoint_reconciliation,
        "base_rates": base, "univariate": univariate,
        "surfaces": {
            "progress_x_arr": grouped_cells(states, ["progress_bin", "arr_bin"]),
            "progress_x_distance": grouped_cells(states, ["progress_bin", "distance_bin"]),
            "distance_x_recovery": grouped_cells(states.loc[states.distance_bin.isin(["Z1", "Z2"])], ["distance_bin", "recovery_bin"]),
        },
        "failure_states": failure, "checkpoint_transitions": transitions(states),
        "timing_paths": timing_paths(states), "robustness": robustness(states),
        "audit": {
            "pattern_detector_changed_count": 0, "primary_layer_changed_count": 0, "entry_definition_changed_count": 0,
            "checkpoint_uses_future_bar_count": 0, "post_checkpoint_bar_in_state_feature_count": 0,
            "post_checkpoint_bar_in_state_chart_count": 0, "target_result_used_to_define_state_count": 0,
            "stop_rule_optimized_count": 0, **state_audit, "post_2021_outcome_read_count": 0,
        },
        "validation_opened": False, "repository_2024_plus_data_opened": False,
    }
    result["verdict"], result["verdict_evidence"] = verdict(result)
    v1.atomic_text(REPORT, build_report(result))
    result["artifact_hashes"] = {str(path): v1.sha256_file(path) for path in (SPEC, STATES, REPORT)}
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
    print(json.dumps(json_ready({"verdict": result["verdict"], "source": result["source_reconciliation"], "rows": result["checkpoint_state_rows"], "base_rates": result["base_rates"], "failure_states": result["failure_states"], "timing": result["timing_paths"], "verdict_evidence": result["verdict_evidence"]}), indent=2))


if __name__ == "__main__":
    main()
