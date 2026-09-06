#!/usr/bin/env python3
"""Run the one frozen candle-derived annual-Amihud acceptance rule."""

from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-ANNUAL-AMIHUD-CAUSAL-ACCEPTANCE-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
REGIME = DATA_ROOT / (
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
CANDIDATES = DATA_ROOT / (
    "ashare_annual_amihud_illiquidity_compensation_mother_v1/"
    "stage_a/candidates_frozen.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_annual_amihud_causal_acceptance_v1"
PATHS = OUTPUT_ROOT / "development_paths_through_2020.parquet"
TRADES = OUTPUT_ROOT / "development_event_results.parquet"
RESULT = OUTPUT_ROOT / "development_result.json"

EXPECTED_HASHES = {
    SPEC: "e9aee9981f606ba4eae5f55cc257a3e37312ffade3f19209535e20033a15faa9",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    CANDIDATES: "575f0b7ebd22947b9b61729f91ef7182d492c2261c713bb1681c76aebe8e457e",
}
EXPECTED_CANDIDATES = 2286
OBSERVATION_SESSIONS = 120
ACCEPTANCE_WINDOW = 20
MINIMUM_CLOSES_ABOVE_ANCHOR = 15
ENTRY_SEARCH_SESSIONS = 3
FAILURE_MEDIAN_WINDOW = 20
FAILURE_CONSECUTIVE_CLOSES = 5
MAXIMUM_HOLDING_SESSIONS = 120
ROUND_TRIP_COST = 0.004
MAXIMUM_DATE = pd.Timestamp("2020-12-31")


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, or execution semantics."""


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
            raise ResearchError(
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def build_paths() -> pd.DataFrame:
    """Materialize only pre-2021 rows needed by the frozen dynamic lifecycle."""
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    query = f"""
      SELECT c.event_id,c.symbol,c.portfolio_year,c.signal_date,
        c.signal_cal_idx,c.coord_close AS signal_coord_close,
        c.invalid_step_cum AS signal_invalid_step_cum,
        d.trade_date,d.cal_idx,d.open,d.close,d.coord_open,d.coord_close,
        d.ret20,d.invalid_step_cum,d.coordinate_factor,d.trade_status,
        d.current_day_data_tradable,d.current_valid,d.history_valid,
        d.market_rule_valid,d.historical_identity_valid,
        d.corporate_action_count,d.corporate_action_valid,
        d.corporate_action_blocking,d.hard_valid,d.up_limit_price,
        d.down_limit_price,d.available_at,d.decision_at,
        m.market_median_ret20,m.n20,
        m.latest_source_timestamp AS market_latest_source_timestamp
      FROM read_parquet('{CANDIDATES.as_posix()}') c
      JOIN read_parquet('{DAILY.as_posix()}') d
        ON c.symbol=d.symbol
       AND d.cal_idx>c.signal_cal_idx
       AND d.cal_idx<=c.signal_cal_idx+243
       AND d.trade_date<=DATE '2020-12-31'
      LEFT JOIN read_parquet('{REGIME.as_posix()}') m
        ON m.trade_date=d.trade_date
      WHERE c.portfolio_year BETWEEN 2015 AND 2020
        AND c.signal_date<=DATE '2019-12-31'
      ORDER BY c.event_id,d.cal_idx
    """
    con.execute(
        f"COPY ({query}) TO '{PATHS.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    frame = con.execute(
        f"SELECT * FROM read_parquet('{PATHS.as_posix()}') ORDER BY event_id,cal_idx"
    ).fetch_df()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    for column in ("available_at", "decision_at", "market_latest_source_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.trade_date.max() > MAXIMUM_DATE:
        raise ResearchError("development path is empty or crossed the pre-2021 cap")
    return frame


def same_lineage(value: Any, expected: float) -> bool:
    return bool(not pd.isna(value) and float(value) == float(expected))


def base_valid(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.history_valid,
        row.market_rule_valid,
        row.historical_identity_valid,
        row.corporate_action_count,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.coordinate_factor,
        row.available_at,
        row.decision_at,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid)
        and bool(row.history_valid)
        and bool(row.market_rule_valid)
        and bool(row.historical_identity_valid)
        and int(row.corporate_action_count) == 0
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
        and np.isfinite(float(row.coordinate_factor))
        and float(row.coordinate_factor) > 0
        and pd.Timestamp(row.available_at) <= pd.Timestamp(row.decision_at)
    )


def valid_close(row: Any) -> bool:
    market_required = (
        row.coord_close,
        row.ret20,
        row.market_median_ret20,
        row.n20,
        row.market_latest_source_timestamp,
    )
    return bool(
        base_valid(row)
        and not any(pd.isna(value) for value in market_required)
        and np.isfinite(float(row.coord_close))
        and float(row.coord_close) > 0
        and np.isfinite(float(row.ret20))
        and np.isfinite(float(row.market_median_ret20))
        and int(row.n20) > 0
        and pd.Timestamp(row.market_latest_source_timestamp)
        <= pd.Timestamp(row.decision_at)
    )


def buyable(row: Any) -> bool:
    return bool(
        base_valid(row)
        and not pd.isna(row.open)
        and not pd.isna(row.coord_open)
        and not pd.isna(row.up_limit_price)
        and np.isfinite(float(row.open))
        and float(row.open) > 0
        and np.isfinite(float(row.coord_open))
        and float(row.coord_open) > 0
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable(row: Any) -> bool:
    return bool(
        base_valid(row)
        and not pd.isna(row.open)
        and not pd.isna(row.coord_open)
        and not pd.isna(row.down_limit_price)
        and np.isfinite(float(row.open))
        and float(row.open) > 0
        and np.isfinite(float(row.coord_open))
        and float(row.coord_open) > 0
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def trigger_passes(
    recent_closes: deque[float],
    anchor: float,
    stock_ret20: float,
    market_median_ret20: float,
) -> bool:
    if len(recent_closes) != ACCEPTANCE_WINDOW:
        return False
    closes_above = sum(float(value) > float(anchor) for value in recent_closes)
    return bool(
        closes_above >= MINIMUM_CLOSES_ABOVE_ANCHOR
        and float(stock_ret20) > max(0.0, float(market_median_ret20))
    )


def common_fields(candidate: Any) -> dict[str, Any]:
    return {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "portfolio_year": int(candidate.portfolio_year),
        "formation_year": int(candidate.formation_year),
        "annual_amihud": float(candidate.annual_amihud),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "signal_coord_close": float(candidate.coord_close),
    }


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    common = common_fields(candidate)
    lineage = float(candidate.invalid_step_cum)
    if path.empty:
        return {**common, "status": "NO_DEVELOPMENT_PATH"}

    recent_closes: deque[float] = deque(maxlen=ACCEPTANCE_WINDOW)
    trigger: Any | None = None
    entry: Any | None = None
    failure_streak = 0
    pending_failure_cal_idx: int | None = None

    for row in path.sort_values("cal_idx", kind="mergesort").itertuples(index=False):
        if pd.Timestamp(row.trade_date) > MAXIMUM_DATE:
            raise ResearchError("post-2020 row entered replay")
        phase = "AFTER_ENTRY" if entry is not None else "BEFORE_ENTRY"
        if not same_lineage(row.invalid_step_cum, lineage):
            return {**common, **({} if trigger is None else {
                "trigger_date": pd.Timestamp(trigger.trade_date),
                "trigger_cal_idx": int(trigger.cal_idx),
            }), **({} if entry is None else {
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": int(entry.cal_idx),
                "entry_price": float(entry.coord_open),
            }), "status": f"INVALID_COORDINATE_LINEAGE_{phase}"}

        if trigger is None:
            if int(row.cal_idx) > int(candidate.signal_cal_idx) + OBSERVATION_SESSIONS:
                break
            if valid_close(row):
                recent_closes.append(float(row.coord_close))
                if trigger_passes(
                    recent_closes,
                    float(candidate.coord_close),
                    float(row.ret20),
                    float(row.market_median_ret20),
                ):
                    trigger = row
            continue

        if entry is None:
            if int(row.cal_idx) <= int(trigger.cal_idx):
                continue
            if int(row.cal_idx) > int(trigger.cal_idx) + ENTRY_SEARCH_SESSIONS:
                return {
                    **common,
                    "trigger_date": pd.Timestamp(trigger.trade_date),
                    "trigger_cal_idx": int(trigger.cal_idx),
                    "trigger_stock_ret20": float(trigger.ret20),
                    "trigger_market_median_ret20": float(trigger.market_median_ret20),
                    "trigger_market_state": (
                        "STRONG" if float(trigger.market_median_ret20) > 0 else "WEAK"
                    ),
                    "status": "NO_LEGAL_ENTRY",
                }
            if buyable(row):
                entry = row
            else:
                if valid_close(row):
                    recent_closes.append(float(row.coord_close))
                continue

        assert trigger is not None and entry is not None
        trigger_fields = {
            "trigger_date": pd.Timestamp(trigger.trade_date),
            "trigger_cal_idx": int(trigger.cal_idx),
            "trigger_stock_ret20": float(trigger.ret20),
            "trigger_market_median_ret20": float(trigger.market_median_ret20),
            "trigger_market_state": (
                "STRONG" if float(trigger.market_median_ret20) > 0 else "WEAK"
            ),
        }
        entry_fields = {
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": int(entry.cal_idx),
            "entry_price": float(entry.coord_open),
        }

        if (
            pending_failure_cal_idx is not None
            and int(row.cal_idx) > pending_failure_cal_idx
            and sellable(row)
        ):
            gross = float(row.coord_open) / float(entry.coord_open) - 1
            return {
                **common,
                **trigger_fields,
                **entry_fields,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": float(row.coord_open),
                "exit_reason": "LOSS_OF_ACCEPTANCE_NEXT_LEGAL_OPEN",
                "failure_signal_cal_idx": pending_failure_cal_idx,
                "holding_sessions": int(row.cal_idx) - int(entry.cal_idx),
                "gross_return": gross,
                "net_return": gross - ROUND_TRIP_COST,
            }

        if (
            int(row.cal_idx) >= int(entry.cal_idx) + MAXIMUM_HOLDING_SESSIONS
            and sellable(row)
        ):
            gross = float(row.coord_open) / float(entry.coord_open) - 1
            return {
                **common,
                **trigger_fields,
                **entry_fields,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": float(row.coord_open),
                "exit_reason": "H120_NEXT_LEGAL_OPEN",
                "holding_sessions": int(row.cal_idx) - int(entry.cal_idx),
                "gross_return": gross,
                "net_return": gross - ROUND_TRIP_COST,
            }

        if valid_close(row):
            recent_closes.append(float(row.coord_close))
            if len(recent_closes) == FAILURE_MEDIAN_WINDOW:
                rolling_median = float(np.median(list(recent_closes)))
                if float(row.coord_close) < rolling_median:
                    failure_streak += 1
                else:
                    failure_streak = 0
                if failure_streak >= FAILURE_CONSECUTIVE_CLOSES:
                    pending_failure_cal_idx = int(row.cal_idx)

    if trigger is None:
        return {**common, "status": "NO_TRIGGER"}
    trigger_fields = {
        "trigger_date": pd.Timestamp(trigger.trade_date),
        "trigger_cal_idx": int(trigger.cal_idx),
        "trigger_stock_ret20": float(trigger.ret20),
        "trigger_market_median_ret20": float(trigger.market_median_ret20),
        "trigger_market_state": (
            "STRONG" if float(trigger.market_median_ret20) > 0 else "WEAK"
        ),
    }
    if entry is None:
        return {**common, **trigger_fields, "status": "NO_LEGAL_ENTRY"}
    return {
        **common,
        **trigger_fields,
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": int(entry.cal_idx),
        "entry_price": float(entry.coord_open),
        "status": "INCOMPLETE_PATH",
    }


def summarize(outcomes: pd.DataFrame) -> tuple[dict[str, Any], bool]:
    annual: dict[str, Any] = {}
    for year in range(2015, 2021):
        population = outcomes.loc[outcomes.portfolio_year.eq(year)]
        completed = population.loc[population.status.eq("COMPLETED")]
        triggered = population.loc[population.trigger_date.notna()]
        mean_net = float(completed.net_return.mean()) if len(completed) else None
        count_pass = len(completed) > 50
        mean_pass = mean_net is not None and mean_net > 0.04
        annual[str(year)] = {
            "mother_candidates": int(len(population)),
            "triggered": int(len(triggered)),
            "completed_signals": int(len(completed)),
            "completion_rate_of_mother": float(len(completed) / len(population)),
            "status_counts": {
                str(key): int(value)
                for key, value in population.status.value_counts().items()
            },
            "trigger_market_state_counts": {
                str(key): int(value)
                for key, value in triggered.trigger_market_state.value_counts().items()
            },
            "mean_gross_return": (
                float(completed.gross_return.mean()) if len(completed) else None
            ),
            "mean_net_return": mean_net,
            "median_net_return": (
                float(completed.net_return.median()) if len(completed) else None
            ),
            "positive_net_rate": (
                float(completed.net_return.gt(0).mean()) if len(completed) else None
            ),
            "severe_loss_rate": (
                float(completed.net_return.le(-0.10).mean()) if len(completed) else None
            ),
            "exit_reason_counts": {
                str(key): int(value)
                for key, value in completed.exit_reason.value_counts().items()
            },
            "completed_signals_strictly_greater_than_50": count_pass,
            "mean_net_return_strictly_greater_than_4pct": mean_pass,
            "year_gate_pass": bool(count_pass and mean_pass),
        }
    return annual, all(row["year_gate_pass"] for row in annual.values())


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    if len(candidates) != EXPECTED_CANDIDATES or candidates.event_id.duplicated().any():
        raise ResearchError("mother candidate identity drift")
    if candidates.signal_date.max() > pd.Timestamp("2019-12-31"):
        raise ResearchError("post-2019 annual signal entered development")

    paths = build_paths()
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            replay_one(candidate, groups.get(str(candidate.event_id), pd.DataFrame()))
            for candidate in candidates.itertuples(index=False)
        ]
    ).sort_values(["portfolio_year", "symbol", "event_id"], kind="mergesort")
    if len(outcomes) != EXPECTED_CANDIDATES or outcomes.event_id.duplicated().any():
        raise ResearchError("development result identity drift")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    if not completed.empty:
        if completed.trigger_date.ge(completed.entry_date).any():
            raise ResearchError("entry did not occur after the trigger close")
        if completed.entry_date.ge(completed.exit_date).any():
            raise ResearchError("exit did not occur after entry")
        if completed.exit_date.max() > MAXIMUM_DATE:
            raise ResearchError("post-2020 outcome entered development")

    write_parquet(outcomes, TRADES)
    annual, gate_pass = summarize(outcomes)
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FROZEN_DYNAMIC_RULE_DEVELOPMENT_GATE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "paths_path": str(PATHS),
        "paths_sha256": sha256(PATHS),
        "event_results_path": str(TRADES),
        "event_results_sha256": sha256(TRADES),
        "mother_candidates": int(len(outcomes)),
        "status_counts": {
            str(key): int(value) for key, value in outcomes.status.value_counts().items()
        },
        "annual": annual,
        "all_year_gate_pass": gate_pass,
        "decision": (
            "OPEN_2022_2024_VALIDATION_UNCHANGED"
            if gate_pass
            else "CLOSE_EXACT_FAMILY_AND_CONTINUE_NEW_ECONOMIC_MOTHER"
        ),
        "maximum_path_date": str(paths.trade_date.max().date()),
        "maximum_completed_exit_date": (
            str(completed.exit_date.max().date()) if len(completed) else None
        ),
        "post_2020_data_read": "NO",
        "post_2021_signal_read": "NO",
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "parameter_grid_run": "NO",
        "rule_rescue_allowed": "NO",
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
