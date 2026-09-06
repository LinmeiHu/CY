#!/usr/bin/env python3
"""Evaluate the frozen V8 visual rules without a parameter or subset search."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-DEMAND-IMPULSE-DELAYED-BREAKOUT-VISUAL-RULES-V8"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "f7bac3573c8b58e947f09ae5f8068702735477451e12c1dd7a32c27185d540f0"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
SOURCE_ROOT = DATA_ROOT / "ashare_demand_impulse_inside_day_delayed_breakout_v5"
CANDIDATES = SOURCE_ROOT / "stage_a/candidates_development_2014_2021_frozen.parquet"
DISCOVERY_OUTCOMES = SOURCE_ROOT / "stage_b/discovery_outcomes.parquet"
CONFIRMATION_OUTCOMES = SOURCE_ROOT / "stage_b/confirmation_outcomes.parquet"
DAILY = (
    DATA_ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
REGIME = (
    DATA_ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1"
    / "stage_a/causal_market_regime_2014_2023.parquet"
)
OUT_ROOT = DATA_ROOT / "ashare_demand_impulse_delayed_breakout_visual_rules_v8"
RESULT = OUT_ROOT / "result.json"
LEDGER = OUT_ROOT / "event_ledger.parquet"
ANNUAL = OUT_ROOT / "annual.csv"
STEPS = OUT_ROOT / "stepwise.csv"

SOURCE_PROFILE = "T15_H30_DELAYED_BREAKOUT"
EXPECTED_SOURCE_SIGNALS = 421
EXPECTED_SOURCE_ANNUAL = {2014: 61, 2015: 144, 2016: 42, 2017: 18, 2018: 29, 2019: 47, 2020: 80}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def legal_state(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and bool(row.market_rule_valid)
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
    )


def same_coordinate_lineage(row: Any, event: Any) -> bool:
    return bool(
        np.isfinite(float(row.invalid_step_cum))
        and np.isfinite(float(event.invalid_step_cum))
        and float(row.invalid_step_cum) == float(event.invalid_step_cum)
    )


def buyable_open(row: Any) -> bool:
    required = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in required)
        and float(row.open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    required = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in required)
        and float(row.open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for path in (FREEZE, CANDIDATES, DISCOVERY_OUTCOMES, CONFIRMATION_OUTCOMES, DAILY, REGIME):
        if not path.is_file():
            raise ResearchError(f"missing required input: {path}")
    if sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("frozen V8 specification drift")
    connection = duckdb.connect()
    candidates = connection.execute(
        f"""
        SELECT c.*,r.market_regime,r.market_median_ret20,
          r.market_positive_ret20_share,r.market_median_ret60,
          r.market_positive_ret60_share,
          r.market_median_ret20-r.market_median_ret60 AS market_return_acceleration,
          r.market_positive_ret20_share-r.market_positive_ret60_share
            AS market_breadth_acceleration,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON CAST(c.signal_date AS DATE)=r.trade_date
        WHERE c.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY c.signal_date,c.sleeve,c.symbol,c.event_id
        """
    ).fetch_df()
    outcomes = connection.execute(
        f"""
        SELECT event_id,status,entry_date,entry_cal_idx,entry_price,exit_date,
          exit_cal_idx,exit_price,exit_reason,holding_sessions,gross_return,net_return
        FROM read_parquet([
          '{DISCOVERY_OUTCOMES.as_posix()}',
          '{CONFIRMATION_OUTCOMES.as_posix()}'
        ])
        WHERE profile='{SOURCE_PROFILE}' AND signal_date<=DATE '2020-12-31'
        ORDER BY event_id
        """
    ).fetch_df()
    connection.register(
        "events",
        candidates[["event_id", "symbol", "cal_idx"]],
    )
    paths = connection.execute(
        f"""
        SELECT e.event_id,d.*
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol
         AND d.cal_idx BETWEEN e.cal_idx-170 AND e.cal_idx+75
        ORDER BY e.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    for frame in (candidates, outcomes, paths):
        for column in ("signal_date", "setup_date", "entry_date", "exit_date", "trade_date", "decision_at", "available_at", "market_latest_source_timestamp"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    if len(candidates) != EXPECTED_SOURCE_SIGNALS or candidates.event_id.nunique() != EXPECTED_SOURCE_SIGNALS:
        raise ResearchError(f"source identity drift: {len(candidates)}")
    annual = candidates.groupby(candidates.signal_date.dt.year).size().to_dict()
    if annual != EXPECTED_SOURCE_ANNUAL:
        raise ResearchError(f"source annual identity drift: {annual}")
    if candidates.event_id.duplicated().any() or outcomes.event_id.duplicated().any():
        raise ResearchError("duplicate event identity")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("source availability exceeds source decision time")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("market state uses information after source decision time")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered V8 development")
    return candidates, outcomes, paths


def classify_and_replay(event: Any, path: pd.DataFrame) -> dict[str, Any]:
    ordered = path.sort_values("cal_idx", kind="mergesort")
    signal = ordered.loc[ordered.cal_idx.eq(int(event.cal_idx))]
    prior = ordered.loc[
        (ordered.cal_idx < int(event.cal_idx))
        & ordered.current_valid.fillna(False)
        & ordered.coord_high.notna()
        & ordered.coord_close.notna()
    ].tail(126)
    row: dict[str, Any] = {
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "sleeve": str(event.sleeve),
        "signal_date": pd.Timestamp(event.signal_date),
        "signal_year": int(pd.Timestamp(event.signal_date).year),
        "source_cal_idx": int(event.cal_idx),
        "market_regime": str(event.market_regime),
        "market_return_acceleration": float(event.market_return_acceleration),
        "market_breadth_acceleration": float(event.market_breadth_acceleration),
        "lifecycle": "INSUFFICIENT_HISTORY",
        "r1_pass": False,
        "r2_pass": False,
        "r4_pass": False,
        "r3_pass": False,
        "final_pass": False,
        "replay_status": "REJECTED",
    }
    if len(signal) != 1 or len(prior) != 126:
        return row
    signal_row = signal.iloc[0]
    if not np.isfinite(float(signal_row.coord_close)):
        return row
    if abs(float(signal_row.coord_close) - float(event.coord_close)) > 1e-9:
        raise ResearchError(f"{event.event_id}: source coordinate close drift")
    if not all(
        np.isfinite(float(value))
        for value in (prior.coord_high.max(), prior.coord_close.iloc[0])
    ):
        return row
    prior_high = float(prior.coord_high.max())
    signal_close = float(event.coord_close)
    pre126_return = signal_close / float(prior.coord_close.iloc[0]) - 1.0
    inventory_escape = signal_close >= prior_high
    deep_reset = (
        float(event.pre_impulse_ret60) <= 0.0
        and signal_close <= 0.80 * prior_high
    )
    if inventory_escape:
        lifecycle = "INVENTORY_ESCAPE"
    elif deep_reset:
        lifecycle = "DEEP_RESET_REPRICING"
    else:
        lifecycle = "MIDDLE_OVERHEAD"
    r1_pass = lifecycle in {"INVENTORY_ESCAPE", "DEEP_RESET_REPRICING"}
    r2_pass = bool(
        r1_pass
        and (
            lifecycle == "DEEP_RESET_REPRICING"
            or pre126_return <= 0.50
        )
    )
    r4_pass = bool(
        r2_pass
        and (
            (
                lifecycle == "INVENTORY_ESCAPE"
                and (
                    str(event.market_regime) == "BULL"
                    or float(event.market_return_acceleration) >= 0.0
                )
            )
            or (
                lifecycle == "DEEP_RESET_REPRICING"
                and float(event.market_breadth_acceleration) >= 0.0
            )
        )
    )
    row.update(
        {
            "prior126_high": prior_high,
            "pre126_return": pre126_return,
            "lifecycle": lifecycle,
            "r1_pass": r1_pass,
            "r2_pass": r2_pass,
            "r4_pass": r4_pass,
        }
    )
    if not r4_pass:
        return row

    acceptance = ordered.loc[
        ordered.cal_idx.isin([int(event.cal_idx) + 1, int(event.cal_idx) + 2])
    ].sort_values("cal_idx", kind="mergesort")
    if len(acceptance) != 2:
        row["replay_status"] = "ACCEPTANCE_BAR_MISSING"
        return row
    expected = [int(event.cal_idx) + 1, int(event.cal_idx) + 2]
    if acceptance.cal_idx.astype(int).tolist() != expected:
        row["replay_status"] = "ACCEPTANCE_CLOCK_DRIFT"
        return row
    valid_acceptance = True
    for candidate in acceptance.itertuples(index=False):
        valid_acceptance = bool(
            valid_acceptance
            and legal_state(candidate)
            and same_coordinate_lineage(candidate, event)
            and np.isfinite(float(candidate.coord_close))
            and float(candidate.coord_close) > float(event.setup_high_coord)
        )
    row["acceptance_1_close_vs_high"] = (
        float(acceptance.iloc[0].coord_close) / float(event.setup_high_coord) - 1.0
        if np.isfinite(float(acceptance.iloc[0].coord_close))
        else math.nan
    )
    row["acceptance_2_close_vs_high"] = (
        float(acceptance.iloc[1].coord_close) / float(event.setup_high_coord) - 1.0
        if np.isfinite(float(acceptance.iloc[1].coord_close))
        else math.nan
    )
    row["acceptance_decision_date"] = pd.Timestamp(acceptance.iloc[1].trade_date)
    row["r3_pass"] = valid_acceptance
    if not valid_acceptance:
        row["replay_status"] = "ACCEPTANCE_REJECTED"
        return row
    row["final_pass"] = True

    entry_search = ordered.loc[
        ordered.cal_idx.between(int(event.cal_idx) + 3, int(event.cal_idx) + 5)
    ].sort_values("cal_idx", kind="mergesort")
    chosen_entry: Any | None = None
    for candidate in entry_search.itertuples(index=False):
        if not same_coordinate_lineage(candidate, event):
            row["replay_status"] = "ENTRY_COORDINATE_LINEAGE_CHANGED"
            return row
        if buyable_open(candidate):
            chosen_entry = candidate
            break
    if chosen_entry is None:
        row["replay_status"] = "NO_LEGAL_ENTRY"
        return row
    entry_price = float(chosen_entry.coord_open)
    target = entry_price * 1.15
    row.update(
        {
            "entry_date": pd.Timestamp(chosen_entry.trade_date),
            "entry_cal_idx": int(chosen_entry.cal_idx),
            "entry_price": entry_price,
        }
    )

    pending_time_stop = False
    chosen_exit: Any | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    for candidate in ordered.loc[
        ordered.cal_idx > int(chosen_entry.cal_idx)
    ].sort_values("cal_idx", kind="mergesort").itertuples(index=False):
        if not same_coordinate_lineage(candidate, event):
            row["replay_status"] = "EXIT_COORDINATE_LINEAGE_CHANGED"
            return row
        if pending_time_stop and sellable_open(candidate):
            chosen_exit = candidate
            exit_price = float(candidate.coord_open)
            exit_reason = "H30_TIME_STOP"
            break
        if (
            legal_state(candidate)
            and np.isfinite(float(candidate.coord_high))
            and float(candidate.coord_high) >= target
        ):
            chosen_exit = candidate
            exit_price = target
            exit_reason = "TARGET_15"
            break
        if legal_state(candidate) and int(candidate.cal_idx) >= int(chosen_entry.cal_idx) + 30:
            pending_time_stop = True
    if chosen_exit is None:
        row["replay_status"] = "NO_COMPLETED_EXIT"
        return row
    gross = exit_price / entry_price - 1.0
    row.update(
        {
            "exit_date": pd.Timestamp(chosen_exit.trade_date),
            "exit_cal_idx": int(chosen_exit.cal_idx),
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "holding_sessions": int(chosen_exit.cal_idx) - int(chosen_entry.cal_idx),
            "gross_return": gross,
            "net_return": gross - 0.004,
            "replay_status": "COMPLETED",
        }
    )
    return row


def metrics(
    frame: pd.DataFrame,
    status_column: str,
    return_column: str,
    exit_reason_column: str,
    holding_column: str,
) -> dict[str, Any]:
    complete = frame.loc[frame[status_column].eq("COMPLETED")].copy()
    values = pd.to_numeric(complete[return_column], errors="coerce")
    signal_dates = frame.signal_date.nunique() if not frame.empty else 0
    counts = frame.groupby("signal_date").size() if not frame.empty else pd.Series(dtype=float)
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "independent_signal_dates": int(signal_dates),
        "mean_net": None if complete.empty else float(values.mean()),
        "median_net": None if complete.empty else float(values.median()),
        "positive_rate": None if complete.empty else float(values.gt(0).mean()),
        "severe_loss_rate": None if complete.empty else float(values.le(-0.10).mean()),
        "target_hit_rate": (
            None
            if complete.empty or exit_reason_column not in complete
            else float(complete[exit_reason_column].fillna("").str.startswith("TARGET").mean())
        ),
        "average_holding_sessions": (
            None
            if complete.empty or holding_column not in complete
            else float(pd.to_numeric(complete[holding_column], errors="coerce").mean())
        ),
        "largest_date_share": None if frame.empty else float(counts.max() / len(frame)),
        "top_five_date_share": None if frame.empty else float(counts.nlargest(5).sum() / len(frame)),
    }


def run() -> dict[str, Any]:
    candidates, outcomes, paths = load_inputs()
    outcomes = outcomes.rename(
        columns={column: f"{column}_source" for column in outcomes.columns if column != "event_id"}
    )
    source = candidates.merge(
        outcomes,
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        classify_and_replay(event, groups[str(event.event_id)])
        for event in candidates.itertuples(index=False)
    ]
    ledger = source.merge(
        pd.DataFrame(rows),
        on=["event_id", "symbol", "sleeve", "signal_date"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_rule"),
    )
    if ledger.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("later signal entered V8 result")
    final = ledger.loc[ledger.final_pass.fillna(False)].copy()

    step_definitions = [
        ("SOURCE_MOTHER", pd.Series(True, index=ledger.index)),
        ("R1_PRICE_LIFECYCLE", ledger.r1_pass.fillna(False)),
        ("R2_NO_LATE_BLOWOFF", ledger.r2_pass.fillna(False)),
        ("R4_CAUSAL_MARKET_ROUTE", ledger.r4_pass.fillna(False)),
        ("R3_TWO_SESSION_ACCEPTANCE", ledger.final_pass.fillna(False)),
    ]
    step_rows: list[dict[str, Any]] = []
    for name, mask in step_definitions:
        part = ledger.loc[mask].copy()
        item = metrics(
            part,
            "status_source",
            "net_return_source",
            "exit_reason_source",
            "holding_sessions_source",
        )
        item["step"] = name
        item["economics"] = "source next-open translation; final delayed-entry economics reported separately"
        step_rows.append(item)
    stepwise = pd.DataFrame(step_rows)

    annual_rows: list[dict[str, Any]] = []
    for year in range(2014, 2021):
        part = final.loc[final.signal_year.eq(year)].copy()
        item = metrics(part, "replay_status", "net_return", "exit_reason", "holding_sessions")
        item["year"] = year
        annual_rows.append(item)
    annual = pd.DataFrame(annual_rows)

    market_rows: dict[str, dict[str, Any]] = {}
    for state in ("BULL", "TRANSITION", "BEAR"):
        part = final.loc[final.market_regime_rule.eq(state)].copy()
        market_rows[state] = metrics(part, "replay_status", "net_return", "exit_reason", "holding_sessions")
    lifecycle_rows: dict[str, dict[str, Any]] = {}
    for state in ("INVENTORY_ESCAPE", "DEEP_RESET_REPRICING"):
        part = final.loc[final.lifecycle.eq(state)].copy()
        lifecycle_rows[state] = metrics(part, "replay_status", "net_return", "exit_reason", "holding_sessions")

    final_metrics = metrics(final, "replay_status", "net_return", "exit_reason", "holding_sessions")
    annual_signal_counts = {
        str(int(row.year)): int(row.signals) for row in annual.itertuples(index=False)
    }
    annual_date_counts = {
        str(int(row.year)): int(row.independent_signal_dates)
        for row in annual.itertuples(index=False)
    }
    literal_frequency_gate = bool(
        annual_signal_counts
        and all(value > 50 for value in annual_signal_counts.values())
    )
    mean_gate = bool(
        final_metrics["mean_net"] is not None
        and float(final_metrics["mean_net"]) > 0.04
    )
    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "freeze_sha256": sha256(FREEZE),
        "scientific_status": "POST_HOC_DEVELOPMENT_VISUAL_RULE_TEST",
        "source_period": ["2014-01-01", "2020-12-31"],
        "charts_reviewed": EXPECTED_SOURCE_SIGNALS,
        "source": metrics(
            ledger,
            "status_source",
            "net_return_source",
            "exit_reason_source",
            "holding_sessions_source",
        ),
        "stepwise_source_translation": step_rows,
        "final_delayed_translation": final_metrics,
        "annual_final": annual_rows,
        "annual_signal_counts": annual_signal_counts,
        "annual_independent_signal_dates": annual_date_counts,
        "average_signals_per_year": float(len(final) / 7.0),
        "minimum_signals_in_any_calendar_year": int(min(annual_signal_counts.values())),
        "market_state_final": market_rows,
        "lifecycle_final": lifecycle_rows,
        "gate": {
            "mean_net_above_4pct": mean_gate,
            "every_calendar_year_more_than_50_signals": literal_frequency_gate,
            "passes_both": bool(mean_gate and literal_frequency_gate),
            "later_period_2022_2024_opened": False,
        },
        "governance": {
            "future_market_return_used": False,
            "entry_same_as_decision_bar": False,
            "post_2020_used_to_define_or_test_rules": False,
            "threshold_grid_run": False,
            "rule_subset_search_run": False,
            "post_2024_outcome_read": False,
            "independent_confirmation_claim": False,
        },
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_parquet(ledger, LEDGER)
    annual.to_csv(ANNUAL, index=False, float_format="%.10g")
    stepwise.to_csv(STEPS, index=False, float_format="%.10g")
    canonical_json(RESULT, result)
    result["result_sha256"] = sha256(RESULT)
    result["ledger_sha256"] = sha256(LEDGER)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
