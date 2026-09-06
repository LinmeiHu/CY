#!/usr/bin/env python3
"""Run the one frozen rule compression from the complete V2 chart review."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-BEAR-BROAD-REPAIR-SLOW-SUPPLY-EXHAUSTION-V2R1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "ef659dab8a645aac3c0d7b92f4fb48cfde246f90d20995569ed491a4a8dd8d19"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
CHART_ROOT = DATA_ROOT / "ashare_bear_slow_supply_exhaustion_12m_chart_discovery_v2"
LEDGER = CHART_ROOT / "frozen_candidate_ledger.parquet"
WINDOWS = CHART_ROOT / "chart_window_panel.parquet"
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
EXPECTED_HASHES = {
    "ledger": "cb8459b95b9c11edea88183c33af7384cd284cf45b5410103ff1463361a28913",
    "windows": "4939d92a90b1a26fae1122069f28bd06be316bebca4fc22ffd1d86604bfc6ef1",
    "daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_bear_broad_repair_slow_supply_exhaustion_v2r1"
BREADTH = OUTPUT_ROOT / "causal_signal_date_breadth.parquet"
FILTERED = OUTPUT_ROOT / "filtered_candidate_ledger.parquet"
OUTCOMES = OUTPUT_ROOT / "development_2014_2020_outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"

ROUND_TRIP_COST = 0.004
SIGNAL_START = pd.Timestamp("2014-01-01")
SIGNAL_END = pd.Timestamp("2020-12-31")


class ResearchError(RuntimeError):
    """Fail closed on source identity, PIT state, chronology, or replay state."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sources() -> dict[str, str]:
    paths = {
        "freeze": FREEZE,
        "ledger": LEDGER,
        "windows": WINDOWS,
        "daily": DAILY,
        "regime": REGIME,
    }
    expected = {"freeze": EXPECTED_FREEZE_SHA256, **EXPECTED_HASHES}
    actual: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen source: {path}")
        actual[name] = sha256(path)
        if actual[name] != expected[name]:
            raise ResearchError(f"{name} identity drift: {actual[name]} != {expected[name]}")
    return actual


def connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads=4")
    return con


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connection()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def build_causal_breadth() -> pd.DataFrame:
    con = connection()
    breadth = con.execute(
        f"""
        SELECT trade_date,
          COUNT(*) AS eligible_stocks,
          MEDIAN(step_return) AS market_repair_median_return,
          AVG(CASE WHEN step_return>0 THEN 1.0 ELSE 0.0 END) AS market_repair_positive_share,
          MAX(available_at) AS latest_source_timestamp,
          MAX(decision_at) AS decision_at
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
          AND hard_valid
          AND current_valid
          AND current_day_data_tradable
          AND market_rule_valid
          AND corporate_action_valid
          AND NOT corporate_action_blocking
          AND COALESCE(corporate_action_count,0)=0
          AND historical_identity_valid
          AND trade_status=1
          AND NOT is_st
          AND isfinite(step_return)
          AND available_at<=decision_at
        GROUP BY trade_date
        ORDER BY trade_date
        """
    ).fetch_df()
    con.close()
    breadth["trade_date"] = pd.to_datetime(breadth.trade_date)
    breadth["latest_source_timestamp"] = pd.to_datetime(breadth.latest_source_timestamp)
    breadth["decision_at"] = pd.to_datetime(breadth.decision_at)
    invalid_dates = (
        breadth.empty
        or breadth.trade_date.min() < SIGNAL_START
        or breadth.trade_date.max() > SIGNAL_END
    )
    if invalid_dates:
        raise ResearchError("unexpected causal breadth date coverage")
    if breadth.latest_source_timestamp.gt(breadth.decision_at).any():
        raise ResearchError("market repair source after its decision timestamp")
    if breadth.eligible_stocks.lt(100).any():
        raise ResearchError("market repair universe unexpectedly narrow")
    breadth["broad_repair"] = breadth.market_repair_median_return.gt(
        0
    ) & breadth.market_repair_positive_share.gt(0.50)
    return breadth


def load_filtered_candidates(breadth: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = connection()
    candidates = con.execute(
        f"""
        SELECT *
        FROM read_parquet('{LEDGER.as_posix()}')
        WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY signal_date,symbol,chart_event_id
        """
    ).fetch_df()
    con.close()
    for column in ("signal_date", "decision_at", "available_at", "entry_date", "exit_date"):
        candidates[column] = pd.to_datetime(candidates[column])
    if len(candidates) != 1765 or candidates.chart_event_id.nunique() != 1765:
        raise ResearchError(f"frozen candidate identity drift: {len(candidates)}")
    if not candidates.market_regime.eq("BEAR").all():
        raise ResearchError("non-BEAR row in frozen candidate ledger")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("candidate source after decision")
    merged = candidates.merge(
        breadth[
            [
                "trade_date",
                "eligible_stocks",
                "market_repair_median_return",
                "market_repair_positive_share",
                "latest_source_timestamp",
                "broad_repair",
            ]
        ],
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    )
    if merged.broad_repair.isna().any():
        raise ResearchError("missing causal breadth for candidate signal date")
    if merged.latest_source_timestamp.gt(merged.decision_at).any():
        raise ResearchError("same-day market repair source after candidate decision")
    selected = merged.loc[merged.broad_repair].copy()
    if selected.empty:
        raise ResearchError("frozen broad-repair filter selected no candidates")
    return merged, selected


def load_paths(selected: pd.DataFrame) -> dict[str, pd.DataFrame]:
    con = connection()
    con.register("events", selected[["chart_event_id"]])
    paths = con.execute(
        f"""
        SELECT w.*
        FROM read_parquet('{WINDOWS.as_posix()}') w
        JOIN events e USING(chart_event_id)
        ORDER BY chart_event_id,cal_idx
        """
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    if paths.chart_event_id.nunique() != len(selected):
        raise ResearchError("missing replay path")
    return {str(key): part for key, part in paths.groupby("chart_event_id", sort=False)}


def legal(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.open,
        row.coord_open,
        row.coordinate_factor,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.current_valid
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and int(row.corporate_action_count) == 0
        and row.hard_valid
        and float(row.open) > 0
        and float(row.coord_open) > 0
    )


def sellable_open(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def observable_close(row: Any, lineage: float) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.coord_close,
        row.invalid_step_cum,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and float(row.invalid_step_cum) == lineage
        and int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.current_valid
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and int(row.corporate_action_count) == 0
        and row.hard_valid
        and np.isfinite(float(row.coord_close))
    )


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    common = {
        "chart_event_id": candidate.chart_event_id,
        "symbol": candidate.symbol,
        "signal_date": candidate.signal_date,
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "prior5_high": float(candidate.prior5_high),
        "market_repair_median_return": float(candidate.market_repair_median_return),
        "market_repair_positive_share": float(candidate.market_repair_positive_share),
        "baseline_status": candidate.status,
        "baseline_net_return": candidate.net_return,
    }
    if candidate.status == "NO_LEGAL_ENTRY" or pd.isna(candidate.entry_cal_idx):
        return {**common, "status": "NO_LEGAL_ENTRY"}
    if candidate.status == "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY":
        return {**common, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"}
    entry_idx = int(candidate.entry_cal_idx)
    entry_price = float(candidate.entry_price)
    lineage = float(candidate.invalid_step_cum)
    target_price = entry_price * 1.10
    consecutive_below = 0
    pending_reason: str | None = None
    exit_row = None
    exit_price = math.nan
    exit_reason: str | None = None

    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                "entry_date": candidate.entry_date,
                "entry_cal_idx": entry_idx,
                "entry_price": entry_price,
            }
        if pending_reason is not None and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = pending_reason
            break
        if int(row.cal_idx) > entry_idx + 20 and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H20_TIME_STOP"
            break
        target_reached = (
            legal(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        )
        if target_reached:
            exit_row = row
            exit_price = target_price
            exit_reason = "TARGET_10"
            break
        if observable_close(row, lineage):
            if float(row.coord_close) < float(candidate.prior5_high):
                consecutive_below += 1
                if consecutive_below == 2:
                    pending_reason = "TWO_CLOSE_PLATFORM_FAILURE"
            else:
                consecutive_below = 0

    if exit_row is None:
        return {
            **common,
            "status": "INCOMPLETE_PATH",
            "entry_date": candidate.entry_date,
            "entry_cal_idx": entry_idx,
            "entry_price": entry_price,
            "pending_reason_at_path_end": pending_reason,
        }
    gross = exit_price / entry_price - 1
    return {
        **common,
        "status": "COMPLETED",
        "entry_date": candidate.entry_date,
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def metrics(frame: pd.DataFrame, return_column: str = "net_return") -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")]
    values = pd.to_numeric(completed[return_column], errors="coerce")
    return {
        "signals": len(frame),
        "completed": len(completed),
        "signal_dates": int(completed.signal_date.nunique()),
        "mean_net": float(values.mean()) if len(values) else None,
        "median_net": float(values.median()) if len(values) else None,
        "win_rate": float(values.gt(0).mean()) if len(values) else None,
        "ge_4pct_rate": float(values.ge(0.04).mean()) if len(values) else None,
        "severe10": float(values.le(-0.10).mean()) if len(values) else None,
        "mean_holding_sessions": float(completed.holding_sessions.mean()) if len(values) else None,
    }


def baseline_metrics(selected: pd.DataFrame) -> dict[str, Any]:
    completed = selected.loc[selected.status.eq("COMPLETED")]
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": len(selected),
        "completed": len(completed),
        "signal_dates": int(completed.signal_date.nunique()),
        "mean_net": float(values.mean()) if len(values) else None,
        "median_net": float(values.median()) if len(values) else None,
        "win_rate": float(values.gt(0).mean()) if len(values) else None,
        "ge_4pct_rate": float(values.ge(0.04).mean()) if len(values) else None,
        "severe10": float(values.le(-0.10).mean()) if len(values) else None,
        "mean_holding_sessions": float(completed.holding_sessions.mean()) if len(values) else None,
    }


def run() -> dict[str, Any]:
    source_hashes = verify_sources()
    breadth = build_causal_breadth()
    _, selected = load_filtered_candidates(breadth)
    paths = load_paths(selected)
    outcomes = pd.DataFrame(
        [
            replay_one(candidate, paths[str(candidate.chart_event_id)])
            for candidate in selected.itertuples(index=False)
        ]
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    for column in ("entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(outcomes) != len(selected) or outcomes.chart_event_id.duplicated().any():
        raise ResearchError("outcome identity mismatch")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "entry_at_or_before_signal": int(
            completed.entry_cal_idx.le(completed.signal_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(completed.exit_cal_idx.le(completed.entry_cal_idx).sum()),
        "platform_exit_not_after_entry": int(
            completed.loc[
                completed.exit_reason.eq("TWO_CLOSE_PLATFORM_FAILURE"), "exit_cal_idx"
            ]
            .le(
                completed.loc[
                    completed.exit_reason.eq("TWO_CLOSE_PLATFORM_FAILURE"),
                    "entry_cal_idx",
                ]
            )
            .sum()
        ),
    }
    if any(chronology.values()):
        raise ResearchError(f"chronology failure: {chronology}")

    write_parquet(breadth, BREADTH)
    write_parquet(selected, FILTERED)
    write_parquet(outcomes, OUTCOMES)

    pooled = metrics(outcomes)
    baseline_pooled = baseline_metrics(selected)
    annual = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    baseline_annual = {
        str(year): baseline_metrics(selected.loc[selected.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    gates = {
        "completed_gt_50_each_year": all(item["completed"] > 50 for item in annual.values()),
        "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None and pooled["mean_net"] > 0.04,
        "pooled_median_positive": pooled["median_net"] is not None and pooled["median_net"] > 0,
        "severe10_le_20pct": pooled["severe10"] is not None and pooled["severe10"] <= 0.20,
    }
    annual_mean_diagnostic = {
        year: bool(item["mean_net"] is not None and item["mean_net"] > 0.04)
        for year, item in annual.items()
    }
    exit_counts = {
        str(key): int(value)
        for key, value in completed.exit_reason.value_counts(dropna=False).sort_index().items()
    }
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "CONSUMED_2014_2020_POST_CHART_DEVELOPMENT_REPLAY",
        "source_hashes": source_hashes,
        "breadth_sha256": sha256(BREADTH),
        "filtered_candidates_sha256": sha256(FILTERED),
        "outcomes_sha256": sha256(OUTCOMES),
        "runner_sha256": sha256(Path(__file__)),
        "market_repair_dates": int(breadth.broad_repair.sum()),
        "candidate_filter": {
            "mother_candidates": 1765,
            "selected_candidates": len(selected),
            "selected_signal_dates": int(selected.signal_date.nunique()),
        },
        "replay": {
            "pooled": pooled,
            "annual": annual,
            "exit_counts": exit_counts,
            "baseline_same_filtered_candidates": {
                "pooled": baseline_pooled,
                "annual": baseline_annual,
            },
            "delta_vs_baseline": {
                "mean_net": pooled["mean_net"] - baseline_pooled["mean_net"],
                "median_net": pooled["median_net"] - baseline_pooled["median_net"],
                "severe10": pooled["severe10"] - baseline_pooled["severe10"],
                "mean_holding_sessions": (
                    pooled["mean_holding_sessions"]
                    - baseline_pooled["mean_holding_sessions"]
                ),
            },
        },
        "gates": gates,
        "all_written_gates_pass": all(gates.values()),
        "annual_mean_net_gt_4pct_diagnostic": annual_mean_diagnostic,
        "chronology_audit": chronology,
        "status_counts": {
            str(key): int(value)
            for key, value in outcomes.status.value_counts(dropna=False).sort_index().items()
        },
        "2021_signal_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "future_market_function": False,
        "verdict": "LATER_PERIOD_GATE_PASSES" if all(gates.values()) else "LATER_PERIOD_GATE_FAILS",
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
