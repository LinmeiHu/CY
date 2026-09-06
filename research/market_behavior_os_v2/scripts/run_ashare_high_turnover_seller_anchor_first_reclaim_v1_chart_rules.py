#!/usr/bin/env python3
"""Evaluate the frozen chart-compressed seller-anchor rules once."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-HIGH-TURNOVER-SELLER-ANCHOR-FIRST-RECLAIM-V1-CHART-RULES"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-HIGH-TURNOVER-SELLER-ANCHOR-FIRST-RECLAIM-V1_chart_rules_freeze.json"
)
ROOT = Path("/Volumes/quant/CY_quant_research") / (
    "ashare_high_turnover_seller_anchor_first_reclaim_v1"
)
LEDGER = ROOT / "stage_c_charts/review_ledger.parquet"
WINDOW = ROOT / "stage_c_charts/chart_window_panel.parquet"
OUTPUT = ROOT / "stage_d_chart_rules"
RULE_EVENTS = OUTPUT / "rule_events.parquet"
RESULT = OUTPUT / "result.json"

EXPECTED_HASHES = {
    LEDGER: "39e26703482a761bef5967f8eac6db5ad5aae82dc339cc8f04fe5c83b4d5ac34",
    WINDOW: "9c8d0afaebcaa1bcde178f426e269845ff8881bdee59f20583adecbdc49d805a",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity or causal-feature drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(f"frozen input drift: {path}")
    if not SPEC.is_file():
        raise ResearchError(f"missing frozen spec: {SPEC}")
    actual[str(SPEC)] = sha256(SPEC)
    return actual


def event_features(event: pd.DataFrame, row: pd.Series) -> dict[str, float]:
    event = event.sort_values("cal_idx")
    causal = event.loc[event.cal_idx.le(int(row.signal_cal_idx))].copy()
    if causal.trade_date.max() > row.signal_date:
        raise ResearchError(f"future bar entered features: {row.event_id}")
    valid = causal.loc[
        causal.hard_valid.fillna(False)
        & causal.current_valid.fillna(False)
        & causal.current_day_data_tradable.fillna(False)
    ].copy()
    pre_anchor = valid.loc[
        valid.cal_idx.between(int(row.anchor_cal_idx) - 60, int(row.anchor_cal_idx))
    ]
    pre_signal = valid.loc[valid.cal_idx.lt(int(row.signal_cal_idx))]
    post_anchor = pre_signal.loc[pre_signal.cal_idx.gt(int(row.anchor_cal_idx))]
    late10 = pre_signal.tail(10)
    if len(post_anchor) < 5 or len(late10) < 10:
        raise ResearchError(f"insufficient causal chart history: {row.event_id}")
    anchor_pos = np.inf
    if len(pre_anchor) >= 10:
        anchor_range = float(pre_anchor.coord_high.max() - pre_anchor.coord_low.min())
        if not np.isfinite(anchor_range) or anchor_range <= 0:
            raise ResearchError(f"invalid anchor range: {row.event_id}")
        anchor_pos = (
            float(row.anchor_high) - float(pre_anchor.coord_low.min())
        ) / anchor_range
    first5_turn = float(post_anchor.head(5).turnover_fraction.median())
    late5_turn = float(late10.tail(5).turnover_fraction.median())
    if not np.isfinite(first5_turn) or first5_turn <= 0:
        raise ResearchError(f"invalid early turnover: {row.event_id}")
    prior_low = float(late10.head(5).coord_low.median())
    late_low = float(late10.tail(5).coord_low.median())
    if not np.isfinite(prior_low) or prior_low <= 0:
        raise ResearchError(f"invalid base low: {row.event_id}")
    age_denom = max(int(row.anchor_age_sessions) - 1, 1)
    return {
        "anchor_pre60_position": float(anchor_pos),
        "absorption_share": float(row.below_anchor_vwap_sessions) / age_denom,
        "prior10_range": float(late10.coord_high.max() / late10.coord_low.min() - 1.0),
        "late_to_early_turnover": late5_turn / first5_turn,
        "late_low_progression": late_low / prior_low - 1.0,
    }


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": int(len(frame)),
        "completed": int(len(completed)),
        "signal_dates": int(completed.signal_date.nunique()),
        "symbols": int(completed.symbol.nunique()),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "positive_rate": None if completed.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if completed.empty else float(values.ge(0.04).mean()),
        "severe10": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit": None
        if completed.empty
        else float(completed.exit_reason.eq("A67_PRE_ANCHOR60_TARGET").mean()),
    }


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    ledger = pd.read_parquet(LEDGER)
    window = pd.read_parquet(WINDOW)
    ledger["signal_date"] = pd.to_datetime(ledger.signal_date)
    window["trade_date"] = pd.to_datetime(window.trade_date)
    if len(ledger) != 655 or ledger.event_id.duplicated().any():
        raise ResearchError("chart-ledger event identity drift")
    if ledger.signal_year.max() > 2020 or window.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("date quarantine drift")
    required = [
        "market_regime", "market_median_ret20", "market_median_ret60",
        "market_positive_ret20_share", "market_positive_ret60_share",
        "anchor_age_sessions", "below_anchor_vwap_sessions", "anchor_high",
    ]
    if ledger[required].isna().any().any():
        raise ResearchError("missing frozen chart-rule input")

    grouped = {event_id: part for event_id, part in window.groupby("event_id", sort=False)}
    features = []
    for row in ledger.itertuples(index=False):
        part = grouped.get(row.event_id)
        if part is None:
            raise ResearchError(f"missing chart window: {row.event_id}")
        features.append({"event_id": row.event_id, **event_features(part, pd.Series(row._asdict()))})
    frame = ledger.merge(pd.DataFrame(features), on="event_id", how="left", validate="one_to_one")
    if frame[[c for c in features[0] if c != "event_id"]].isna().any().any():
        raise ResearchError("derived feature missing")

    frame["market_return_acceleration"] = frame.market_median_ret20 - frame.market_median_ret60
    frame["market_breadth_acceleration"] = (
        frame.market_positive_ret20_share - frame.market_positive_ret60_share
    )
    frame["r1_forced_transfer_not_mature_distribution"] = frame.anchor_pre60_position.le(0.80)
    frame["r2_inventory_absorption_time"] = (
        frame.anchor_age_sessions.ge(20) & frame.absorption_share.ge(0.50)
    )
    frame["r3_late_base_compression"] = frame.prior10_range.le(0.15)
    frame["r4_late_supply_not_strengthening"] = (
        frame.late_to_early_turnover.le(1.00) & frame.late_low_progression.ge(-0.02)
    )
    frame["digestion_score"] = frame[
        ["r2_inventory_absorption_time", "r3_late_base_compression", "r4_late_supply_not_strengthening"]
    ].sum(axis=1)
    bull = frame.market_regime.eq("BULL") & frame.digestion_score.ge(2)
    transition = (
        frame.market_regime.eq("TRANSITION")
        & frame.digestion_score.ge(2)
        & (frame.market_return_acceleration.gt(0) | frame.market_breadth_acceleration.gt(0))
    )
    bear = (
        frame.market_regime.eq("BEAR")
        & frame.digestion_score.eq(3)
        & frame.market_return_acceleration.gt(0)
        & frame.market_breadth_acceleration.gt(0)
    )
    frame["r5_causal_market_route"] = bull | transition | bear
    frame["admitted"] = (
        frame.r1_forced_transfer_not_mature_distribution & frame.r5_causal_market_route
    )
    selected = frame.loc[frame.admitted].copy()

    yearly = {str(int(year)): metrics(part) for year, part in selected.groupby("signal_year", sort=True)}
    expected_years = {str(year) for year in range(2014, 2021)}
    if set(yearly) != expected_years:
        raise ResearchError("one or more development years disappeared")
    yearly_gate = {
        year: bool(row["completed"] > 50 and row["mean_net"] > 0.04 and row["median_net"] > 0)
        for year, row in yearly.items()
    }
    pass_gate = bool(all(yearly_gate.values()))
    disposition = (
        "DEVELOPMENT_GATE_PASSED_LATER_PERIOD_AUTHORIZED"
        if pass_gate
        else "CLOSED_DEVELOPMENT_GATE_FAILED_NO_THRESHOLD_RESCUE"
    )
    compact = [
        "event_id", "symbol", "causal_industry", "signal_date", "signal_year",
        "market_regime", "market_return_acceleration", "market_breadth_acceleration",
        "anchor_pre60_position", "absorption_share", "prior10_range",
        "late_to_early_turnover", "late_low_progression",
        "r1_forced_transfer_not_mature_distribution", "r2_inventory_absorption_time",
        "r3_late_base_compression", "r4_late_supply_not_strengthening",
        "digestion_score", "r5_causal_market_route", "admitted", "status",
        "entry_date", "exit_date", "exit_reason", "holding_sessions", "net_return",
        "outcome_bucket",
    ]
    write_parquet(frame[compact], RULE_EVENTS)
    payload = {
        "experiment": EXPERIMENT,
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "rule_events_sha256": sha256(RULE_EVENTS),
        "charts_reviewed_before_freeze": 655,
        "rule_count": 5,
        "unfiltered": metrics(frame),
        "selected": metrics(selected),
        "selected_by_market_regime": {
            str(regime): metrics(part) for regime, part in selected.groupby("market_regime", sort=True)
        },
        "selected_by_year": yearly,
        "per_year_gate": yearly_gate,
        "complete_development_gate_passed": pass_gate,
        "disposition": disposition,
        "post_2021_06_rule_discovery_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "future_market_function": False,
        "future_price_feature": False,
        "next_step": (
            "Freeze an immutable 2022-2024 validation contract before reading it."
            if pass_gate
            else "Close exact formulation and launch a distinct, higher-recall economic mother."
        ),
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
