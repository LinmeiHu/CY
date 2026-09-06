#!/usr/bin/env python3
"""Build outcome-unaggregated entries/exits for the frozen size-corridor rule."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_high_transfer_low_price_displacement_mother_v1_stage_b as execution,
)


EXPERIMENT = "ASHARE-INDUSTRY-NEUTRAL-SIZE-EVENT-CORRIDOR-ACCEPTANCE-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
MOTHER_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_industry_neutral_circulating_size_extremes_mother_v1"
)
CANDIDATES = MOTHER_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = MOTHER_ROOT / "stage_b/future_paths_through_2021h1.parquet"
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/"
    "causal_market_regime_2014_2023.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_industry_neutral_size_event_corridor_acceptance_v1/stage_1"
)
LEDGER = OUTPUT_ROOT / "selection_ledger_without_returns.parquet"
MANIFEST = OUTPUT_ROOT / "breadth_gate_manifest.json"
EXPECTED_HASHES = {
    SPEC: "52cd905e371b518d92097ae360c0e62f5c6b07edeb506dd57766d6a4df74fe76",
    CANDIDATES: "5d05b6a0d3bc4b812484d3513cb3f67f60f05982c56fb2930d18c6b892614dfc",
    PATHS: "3cd09c1cf6d9f026ea60f98b9b9e94631abf7fad034c21526e16b3db4c257137",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
EXPECTED_EVENTS = 1975
FORMATION_SESSIONS = 5
TRIGGER_RELATIVE_START = 5
TRIGGER_RELATIVE_END = 19
ACCEPTANCE_WINDOW = 5
ACCEPTANCE_MIN_ABOVE = 3
ENTRY_DELAY_MAX = 3
TIME_EXIT_SESSIONS = 120
MINIMUM_ANNUAL_COMPLETED_STRICT = 50
MAXIMUM_CONTEXT_DATE = pd.Timestamp("2021-06-30")


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, or execution drift."""


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
        value = sha256(path)
        actual[str(path)] = value
        if value != expected:
            raise ResearchError(f"frozen input drift: {path}: {value} != {expected}")
    return actual


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def valid_completed_close(row: Any, lineage: float) -> bool:
    required = (
        row.cal_idx,
        row.coord_high,
        row.coord_low,
        row.coord_close,
        row.invalid_step_cum,
        row.available_at,
        row.decision_at,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and float(row.invalid_step_cum) == lineage
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid)
        and bool(row.hard_valid)
        and int(row.trade_status) == 1
        and float(row.coord_high) > 0
        and float(row.coord_low) > 0
        and float(row.coord_close) > 0
        and pd.Timestamp(row.available_at) <= pd.Timestamp(row.decision_at)
    )


def valid_signal_candidate(row: Any, lineage: float) -> bool:
    required = (
        row.signal_cal_idx,
        row.coord_high,
        row.coord_low,
        row.coord_close,
        row.invalid_step_cum,
        row.available_at,
        row.decision_at,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and float(row.invalid_step_cum) == lineage
        and float(row.coord_high) > 0
        and float(row.coord_low) > 0
        and float(row.coord_close) > 0
        and pd.Timestamp(row.available_at) <= pd.Timestamp(row.decision_at)
    )


def price_acceptance(last_five: list[Any], ceiling: float, lineage: float) -> bool:
    if len(last_five) != ACCEPTANCE_WINDOW:
        return False
    if not all(valid_completed_close(row, lineage) for row in last_five):
        return False
    closes = [float(row.coord_close) for row in last_five]
    return bool(closes[-1] > ceiling and sum(value > ceiling for value in closes) >= ACCEPTANCE_MIN_ABOVE)


def market_opportunity(row: Any, decision_at: pd.Timestamp) -> bool:
    required = (
        row.market_median_ret20,
        row.market_median_ret60,
        row.market_positive_ret20_share,
        row.market_positive_ret60_share,
        row.latest_source_timestamp,
    )
    if any(pd.isna(value) for value in required):
        return False
    if pd.Timestamp(row.latest_source_timestamp) > pd.Timestamp(decision_at):
        return False
    repair = bool(
        float(row.market_median_ret20) > float(row.market_median_ret60)
        and float(row.market_positive_ret20_share)
        > float(row.market_positive_ret60_share)
    )
    return bool(str(row.market_regime) == "BULL" or repair)


def consecutive_indices(rows: list[Any], expected: list[int]) -> bool:
    return [int(row.cal_idx) for row in rows] == expected


def replay_without_returns(
    candidate: Any,
    path: pd.DataFrame,
    regime_lookup: dict[pd.Timestamp, Any],
) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.invalid_step_cum)
    common = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "size_lane": str(candidate.size_lane),
        "pit_industry": str(candidate.pit_industry),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_year": int(pd.Timestamp(candidate.signal_date).year),
        "signal_cal_idx": signal_idx,
    }
    by_idx = {
        int(row.cal_idx): row
        for row in path.sort_values("cal_idx", kind="mergesort").itertuples(index=False)
    }
    formation: list[Any] = [candidate]
    formation.extend(by_idx.get(signal_idx + offset) for offset in range(1, FORMATION_SESSIONS))
    if any(row is None for row in formation):
        return {**common, "status": "INCOMPLETE_FORMATION"}
    formation_rows = list(formation)
    observed_formation_indices = [signal_idx] + [
        int(row.cal_idx) for row in formation_rows[1:]
    ]
    if observed_formation_indices != list(
        range(signal_idx, signal_idx + FORMATION_SESSIONS)
    ):
        return {**common, "status": "NONCONSECUTIVE_FORMATION"}
    if not valid_signal_candidate(formation_rows[0], lineage) or not all(
        valid_completed_close(row, lineage) for row in formation_rows[1:]
    ):
        return {**common, "status": "INVALID_FORMATION"}
    ceiling = max(float(row.coord_high) for row in formation_rows)
    floor = min(float(row.coord_low) for row in formation_rows)

    trigger = None
    trigger_market = None
    below_floor_streak = 0
    for relative_idx in range(TRIGGER_RELATIVE_START, TRIGGER_RELATIVE_END + 1):
        current_idx = signal_idx + relative_idx
        row = by_idx.get(current_idx)
        if row is None or not valid_completed_close(row, lineage):
            return {
                **common,
                "corridor_ceiling": ceiling,
                "corridor_floor": floor,
                "status": "INVALID_TRIGGER_WINDOW",
            }
        below_floor_streak = below_floor_streak + 1 if float(row.coord_close) < floor else 0
        if below_floor_streak >= 2:
            return {
                **common,
                "corridor_ceiling": ceiling,
                "corridor_floor": floor,
                "status": "PRETRIGGER_FLOOR_FAILURE",
            }
        latest = [by_idx.get(idx) for idx in range(current_idx - 4, current_idx + 1)]
        if any(item is None for item in latest):
            return {
                **common,
                "corridor_ceiling": ceiling,
                "corridor_floor": floor,
                "status": "INCOMPLETE_ACCEPTANCE_WINDOW",
            }
        latest_rows = list(latest)
        if not price_acceptance(latest_rows, ceiling, lineage):
            continue
        market_row = regime_lookup.get(pd.Timestamp(row.trade_date).normalize())
        if market_row is None or not market_opportunity(market_row, pd.Timestamp(row.decision_at)):
            continue
        trigger = row
        trigger_market = market_row
        break
    if trigger is None or trigger_market is None:
        return {
            **common,
            "corridor_ceiling": ceiling,
            "corridor_floor": floor,
            "status": "NO_QUALIFYING_ACCEPTANCE",
        }

    trigger_idx = int(trigger.cal_idx)
    entry = next(
        (
            by_idx.get(idx)
            for idx in range(trigger_idx + 1, trigger_idx + ENTRY_DELAY_MAX + 1)
            if by_idx.get(idx) is not None
            and not pd.isna(by_idx[idx].invalid_step_cum)
            and float(by_idx[idx].invalid_step_cum) == lineage
            and execution.buyable(by_idx[idx])
        ),
        None,
    )
    selected = {
        **common,
        "corridor_ceiling": ceiling,
        "corridor_floor": floor,
        "trigger_date": pd.Timestamp(trigger.trade_date),
        "trigger_cal_idx": trigger_idx,
        "trigger_market_regime": str(trigger_market.market_regime),
        "trigger_market_median_ret20": float(trigger_market.market_median_ret20),
        "trigger_market_median_ret60": float(trigger_market.market_median_ret60),
        "trigger_market_positive_ret20_share": float(trigger_market.market_positive_ret20_share),
        "trigger_market_positive_ret60_share": float(trigger_market.market_positive_ret60_share),
    }
    if entry is None:
        return {**selected, "status": "NO_LEGAL_ENTRY"}

    entry_idx = int(entry.cal_idx)
    below_ceiling_streak = 0
    pending_failure_exit = False
    exit_row = None
    exit_reason = None
    for idx in range(entry_idx + 1, int(path.cal_idx.max()) + 1):
        row = by_idx.get(idx)
        if row is None:
            return {
                **selected,
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "status": "MISSING_POST_ENTRY_MARKET_SESSION",
            }
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {
                **selected,
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "status": "INVALID_COORDINATE_LINEAGE",
            }
        if pending_failure_exit and execution.sellable_open(row):
            exit_row = row
            exit_reason = "FAILED_ACCEPTANCE"
            break
        if idx >= entry_idx + TIME_EXIT_SESSIONS and execution.sellable_open(row):
            exit_row = row
            exit_reason = "TIME_EXIT_H120"
            break
        if valid_completed_close(row, lineage):
            below_ceiling_streak = (
                below_ceiling_streak + 1 if float(row.coord_close) < ceiling else 0
            )
            if below_ceiling_streak >= 2:
                pending_failure_exit = True
        else:
            below_ceiling_streak = 0
    if exit_row is None:
        return {
            **selected,
            "entry_date": pd.Timestamp(entry.trade_date),
            "entry_cal_idx": entry_idx,
            "status": "NO_COMPLETED_EXIT",
        }
    return {
        **selected,
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_reason": exit_reason,
        "holding_market_sessions": int(exit_row.cal_idx) - entry_idx,
        "status": "COMPLETED",
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    paths = pd.read_parquet(PATHS)
    regimes = pd.read_parquet(REGIME)
    for column in ("signal_date", "decision_at", "available_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("trade_date", "decision_at", "available_at"):
        paths[column] = pd.to_datetime(paths[column])
    for column in ("trade_date", "latest_source_timestamp"):
        regimes[column] = pd.to_datetime(regimes[column])
    if len(candidates) != EXPECTED_EVENTS or candidates.event_id.duplicated().any():
        raise ResearchError("mother candidate identity drift")
    if candidates.signal_date.dt.year.gt(2020).any():
        raise ResearchError("post-2020 signal identity entered development")
    if paths.trade_date.max() > MAXIMUM_CONTEXT_DATE:
        raise ResearchError("post-2021H1 context entered stage 1")
    regime_lookup = {
        pd.Timestamp(row.trade_date).normalize(): row
        for row in regimes.itertuples(index=False)
    }
    path_lookup = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_without_returns(candidate, path_lookup[str(candidate.event_id)], regime_lookup)
        for candidate in candidates.sort_values(
            ["signal_date", "pit_industry", "size_lane", "symbol"],
            kind="mergesort",
        ).itertuples(index=False)
    ]
    ledger = pd.DataFrame(rows).sort_values(
        ["signal_date", "pit_industry", "size_lane", "symbol"], kind="mergesort"
    )
    write_parquet(ledger, LEDGER)
    completed = ledger.loc[ledger.status.eq("COMPLETED")]
    annual_counts = {
        str(year): int(completed.signal_year.eq(year).sum()) for year in (2018, 2019, 2020)
    }
    breadth_pass = all(value > MINIMUM_ANNUAL_COMPLETED_STRICT for value in annual_counts.values())
    manifest = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_UNAGGREGATED_BREADTH_GATE",
        "source_hashes": source_hashes,
        "script_sha256": sha256(Path(__file__)),
        "ledger": str(LEDGER),
        "ledger_sha256": sha256(LEDGER),
        "mother_events": int(len(ledger)),
        "completed_entries_and_exits_by_signal_year": annual_counts,
        "completed_entries_and_exits_total": int(len(completed)),
        "status_counts": {
            str(key): int(value) for key, value in ledger.status.value_counts().sort_index().items()
        },
        "breadth_requirement": "strictly more than 50 completed signals in each of 2018, 2019, and 2020",
        "breadth_gate_pass": bool(breadth_pass),
        "annual_or_pooled_return_aggregate_produced": False,
        "post_2021_signal_identity_read": False,
        "validation_2022_2024_outcome_read": False,
        "maximum_context_date": str(paths.trade_date.max().date()),
        "next_action": (
            "RUN_ONE_SHOT_DEVELOPMENT_RETURN_AGGREGATION"
            if breadth_pass
            else "CLOSE_EXACT_RULE_WITHOUT_RETURN_AGGREGATION"
        ),
    }
    write_json(MANIFEST, manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
