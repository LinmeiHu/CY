#!/usr/bin/env python3
"""Evaluate the frozen causal one-session acceptance rules for the FADT mother."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1 as mother


EXPERIMENT = "ASHARE-FIRST-ACTIVE-DEMAND-TAKEOVER-CAUSAL-ACCEPTANCE-V2"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "54f2730d23dc151a458d1054cb34d3087f0a8bac536b56366566c6fd1f2c61d1"
PARENT_ROOT = (
    Path("/Volumes/quant/CY_quant_research")
    / "ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1"
    / "development_2014_2020"
)
PARENT_CANDIDATES = PARENT_ROOT / "candidates_frozen.parquet"
EXPECTED_PARENT_CANDIDATE_SHA256 = (
    "d9db88581007601b7ba4c72723ec55f9f37207358c987b3fa44aeffa0657192a"
)
EXT_ROOT = (
    Path("/Volumes/quant/CY_quant_research")
    / "ashare_first_active_demand_takeover_causal_acceptance_v2"
    / "development_2014_2020"
)
SELECTED = EXT_ROOT / "selected_candidates.parquet"
OUTCOMES = EXT_ROOT / "outcomes.parquet"
RESULT = EXT_ROOT / "result.json"


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_parent_candidates() -> pd.DataFrame:
    if sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("frozen causal-acceptance specification drift")
    if sha256(PARENT_CANDIDATES) != EXPECTED_PARENT_CANDIDATE_SHA256:
        raise ResearchError("parent candidate identity drift")
    candidates = pd.read_parquet(PARENT_CANDIDATES)
    for column in (
        "signal_date",
        "available_at",
        "decision_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != 1754 or candidates.event_id.nunique() != 1754:
        raise ResearchError("parent candidate count drift")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered rule development")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("parent stock source exceeds signal decision time")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("parent market state exceeds signal decision time")
    return candidates


def build_confirmation_panel(candidates: pd.DataFrame) -> pd.DataFrame:
    events = candidates[
        [
            "event_id",
            "symbol",
            "cal_idx",
            "invalid_step_cum",
            "coord_open",
            "coord_close",
            "market_regime",
        ]
    ].rename(
        columns={
            "invalid_step_cum": "signal_invalid_step_cum",
            "coord_open": "signal_coord_open",
            "coord_close": "signal_coord_close",
        }
    )
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    connection.register("events", events)
    panel = connection.execute(
        f"""
        WITH daily AS (
          SELECT *
          FROM read_parquet('{mother.DAILY.as_posix()}')
          WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-01-08'
        ), breadth AS (
          SELECT trade_date,cal_idx,
            count(*) FILTER (WHERE
              current_valid AND hard_valid AND trade_status=1
              AND current_day_data_tradable AND market_rule_valid
              AND corporate_action_valid AND NOT corporate_action_blocking
              AND available_at IS NOT NULL AND decision_at IS NOT NULL
              AND available_at<=decision_at
            ) AS eligible_stocks,
            avg(CASE WHEN step_return>0 THEN 1.0 ELSE 0.0 END) FILTER (WHERE
              current_valid AND hard_valid AND trade_status=1
              AND current_day_data_tradable AND market_rule_valid
              AND corporate_action_valid AND NOT corporate_action_blocking
              AND available_at IS NOT NULL AND decision_at IS NOT NULL
              AND available_at<=decision_at
            ) AS positive_step_share,
            max(available_at) FILTER (WHERE
              current_valid AND hard_valid AND trade_status=1
              AND current_day_data_tradable AND market_rule_valid
              AND corporate_action_valid AND NOT corporate_action_blocking
              AND available_at IS NOT NULL AND decision_at IS NOT NULL
              AND available_at<=decision_at
            ) AS latest_breadth_source_timestamp,
            max(decision_at) AS breadth_decision_at
          FROM daily
          GROUP BY trade_date,cal_idx
        )
        SELECT e.event_id,e.symbol,e.cal_idx AS signal_cal_idx,e.market_regime,
          e.signal_invalid_step_cum,e.signal_coord_open,e.signal_coord_close,
          d.trade_date AS confirmation_date,d.cal_idx AS confirmation_cal_idx,
          d.invalid_step_cum AS confirmation_invalid_step_cum,
          d.coord_open AS confirmation_coord_open,
          d.coord_high AS confirmation_coord_high,
          d.coord_low AS confirmation_coord_low,
          d.coord_close AS confirmation_coord_close,
          d.trade_status,d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.available_at AS confirmation_available_at,
          d.decision_at AS confirmation_decision_at,
          b.eligible_stocks,b.positive_step_share,
          b.latest_breadth_source_timestamp,b.breadth_decision_at
        FROM events e
        LEFT JOIN daily d ON d.symbol=e.symbol AND d.cal_idx=e.cal_idx+1
        LEFT JOIN breadth b ON b.cal_idx=e.cal_idx+1
        ORDER BY e.event_id
        """
    ).fetch_df()
    connection.close()
    if len(panel) != len(candidates) or panel.event_id.nunique() != len(candidates):
        raise ResearchError("confirmation panel identity drift")
    for column in (
        "confirmation_date",
        "confirmation_available_at",
        "confirmation_decision_at",
        "latest_breadth_source_timestamp",
        "breadth_decision_at",
    ):
        panel[column] = pd.to_datetime(panel[column])
    known = panel.confirmation_decision_at.notna()
    if panel.loc[known, "confirmation_available_at"].gt(
        panel.loc[known, "confirmation_decision_at"]
    ).any():
        raise ResearchError("stock confirmation source exceeds confirmation decision")
    if panel.loc[known, "latest_breadth_source_timestamp"].gt(
        panel.loc[known, "breadth_decision_at"]
    ).any():
        raise ResearchError("breadth source exceeds confirmation decision")
    return panel


def confirmation_is_legal(row: Any) -> bool:
    required = (
        row.confirmation_cal_idx,
        row.confirmation_invalid_step_cum,
        row.trade_status,
        row.current_day_data_tradable,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.confirmation_coord_close,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.confirmation_cal_idx) == int(row.signal_cal_idx) + 1
        and float(row.confirmation_invalid_step_cum)
        == float(row.signal_invalid_step_cum)
        and int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and bool(row.market_rule_valid)
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
    )


def apply_frozen_rules(
    candidates: pd.DataFrame, confirmation: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in confirmation.itertuples(index=False):
        legal = confirmation_is_legal(row)
        midpoint = (float(row.signal_coord_open) + float(row.signal_coord_close)) / 2.0
        bull = str(row.market_regime) == "BULL"
        price_acceptance = bool(
            legal
            and (
                float(row.confirmation_coord_close) >= float(row.signal_coord_close)
                if bull
                else float(row.confirmation_coord_close) >= midpoint
            )
        )
        market_repair = bool(
            bull
            or (
                pd.notna(row.eligible_stocks)
                and int(row.eligible_stocks) > 0
                and pd.notna(row.positive_step_share)
                and float(row.positive_step_share) >= 0.50
            )
        )
        rows.append(
            {
                "event_id": str(row.event_id),
                "confirmation_legal": legal,
                "signal_body_midpoint": midpoint,
                "price_acceptance": price_acceptance,
                "market_repair": market_repair,
                "rule_selected": bool(legal and price_acceptance and market_repair),
            }
        )
    decisions = pd.DataFrame(rows)
    confirmation_only = confirmation.drop(
        columns=[
            "symbol",
            "signal_cal_idx",
            "market_regime",
            "signal_invalid_step_cum",
            "signal_coord_open",
            "signal_coord_close",
        ]
    )
    merged = candidates.merge(
        confirmation_only, on="event_id", how="left", validate="one_to_one"
    )
    merged = merged.merge(decisions, on="event_id", how="left", validate="one_to_one")
    selected = merged.loc[merged.rule_selected].copy()
    if selected.event_id.duplicated().any():
        raise ResearchError("selected identity duplicated")
    return selected.sort_values(["signal_date", "sleeve", "symbol"], kind="mergesort")


def replay_one(event: Any, path: pd.DataFrame) -> dict[str, Any]:
    ordered = path.sort_values("cal_idx", kind="mergesort")
    entry: Any | None = None
    for row in ordered.loc[
        ordered.cal_idx.between(int(event.cal_idx) + 2, int(event.cal_idx) + 4)
    ].itertuples(index=False):
        if not mother.same_lineage(row, event):
            return {"event_id": str(event.event_id), "status": "ENTRY_COORDINATE_LINEAGE_CHANGED"}
        if mother.buyable_open(row):
            entry = row
            break
    if entry is None:
        return {"event_id": str(event.event_id), "status": "NO_LEGAL_ENTRY"}
    entry_price = float(entry.coord_open)
    target = entry_price * 1.15
    pending_time_stop = False
    exit_row: Any | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    for row in ordered.loc[ordered.cal_idx > int(entry.cal_idx)].itertuples(index=False):
        if not mother.same_lineage(row, event):
            return {
                "event_id": str(event.event_id),
                "status": "EXIT_COORDINATE_LINEAGE_CHANGED",
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": int(entry.cal_idx),
                "entry_price": entry_price,
            }
        if pending_time_stop and mother.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H30_TIME_STOP"
            break
        if (
            mother.legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_15"
            break
        if mother.legal_state(row) and int(row.cal_idx) >= int(entry.cal_idx) + 30:
            pending_time_stop = True
    if exit_row is None:
        return {
            "event_id": str(event.event_id),
            "status": "NO_COMPLETED_EXIT",
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": int(entry.cal_idx),
            "entry_price": entry_price,
        }
    gross = exit_price / entry_price - 1.0
    return {
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "sleeve": str(event.sleeve),
        "signal_date": pd.Timestamp(event.signal_date),
        "confirmation_date": pd.Timestamp(event.confirmation_date),
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": int(entry.cal_idx),
        "entry_price": entry_price,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
        "gross_return": gross,
        "net_return": gross - 0.004,
        "status": "COMPLETED",
    }


def replay(selected: pd.DataFrame) -> pd.DataFrame:
    if selected.empty:
        return pd.DataFrame(columns=["event_id", "status"])
    paths = mother.load_execution_paths(selected)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(event, groups[str(event.event_id)])
        for event in selected.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows)
    if len(outcomes) != len(selected) or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome identity drift")
    return outcomes


def metric_record(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    if completed.empty:
        return {"selected": int(len(frame)), "completed": 0}
    values = completed.net_return.astype(float)
    return {
        "selected": int(len(frame)),
        "completed": int(len(completed)),
        "mean_net_return": float(values.mean()),
        "median_net_return": float(values.median()),
        "positive_rate": float(values.gt(0).mean()),
        "severe_loss_rate": float(values.le(-0.10).mean()),
        "target_hit_rate": float(completed.exit_reason.eq("TARGET_15").mean()),
    }


def summarize(selected: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, Any]:
    joined = selected[
        ["event_id", "signal_date", "market_regime", "positive_step_share"]
    ].merge(outcomes, on="event_id", how="left", validate="one_to_one")
    joined["signal_year"] = pd.to_datetime(joined.signal_date_x).dt.year
    annual: dict[str, Any] = {}
    for year, part in joined.groupby("signal_year", sort=True):
        annual[str(int(year))] = metric_record(part)
    by_regime: dict[str, Any] = {}
    for regime, part in joined.groupby("market_regime", sort=True):
        by_regime[str(regime)] = metric_record(part)
    count_gate = bool(annual and all(v["selected"] > 50 for v in annual.values()))
    return_gate = bool(
        annual
        and all(
            v.get("completed", 0) > 0 and v.get("mean_net_return", -math.inf) > 0.04
            for v in annual.values()
        )
    )
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "CONSUMED_2014_2020_POST_VISUAL_RULE_DEVELOPMENT",
        "freeze_sha256": sha256(FREEZE),
        "parent_candidate_sha256": sha256(PARENT_CANDIDATES),
        "parent_signals": 1754,
        "selected_signals": int(len(selected)),
        "retention_rate": float(len(selected) / 1754.0),
        "overall": metric_record(joined),
        "annual": annual,
        "by_signal_market_regime": by_regime,
        "literal_count_gate_pass": count_gate,
        "literal_return_gate_pass": return_gate,
        "later_period_open_authorized": bool(count_gate and return_gate),
        "2021_signal_or_rule_read": "NO",
        "2022_2024_read": "NO",
        "future_market_return_used": False,
        "same_bar_entry": False,
        "selected_sha256": sha256(SELECTED),
        "outcomes_sha256": sha256(OUTCOMES),
    }


def main() -> int:
    candidates = load_parent_candidates()
    confirmation = build_confirmation_panel(candidates)
    selected = apply_frozen_rules(candidates, confirmation)
    write_parquet(selected, SELECTED)
    outcomes = replay(selected)
    write_parquet(outcomes, OUTCOMES)
    result = summarize(selected, outcomes)
    write_json(result, RESULT)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"result_sha256={sha256(RESULT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
