#!/usr/bin/env python3
"""Apply the frozen supply-expansion demand rules without outcome aggregation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_high_transfer_low_price_displacement_mother_v1_stage_b as execution,
)


EXPERIMENT = "ASHARE-MATERIAL-SUPPLY-EXPANSION-DEMAND-REASSERTION-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
MOTHER_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_material_circulating_supply_expansion_mother_v1"
)
CANDIDATES = MOTHER_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = MOTHER_ROOT / "stage_b/future_paths_through_2021h1.parquet"
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/"
    "causal_market_regime_2014_2023.parquet"
)
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_material_supply_expansion_demand_reassertion_v1/stage_1"
)
LEDGER = OUTPUT_ROOT / "selection_ledger_without_returns.parquet"
MANIFEST = OUTPUT_ROOT / "breadth_gate_manifest.json"
EXPECTED_HASHES = {
    SPEC: "9119e6631ac94466c691a580a4176fd1f770c241e8d00727c5f4d4b72fbf9873",
    CANDIDATES: "7c52bd0bc4603c52f86e540c96b560c578f588a6316bea9b75dc126b41449aa9",
    PATHS: "39c528941b3e04011264b2a3a2a8dd61950150e30f609c0fbbd50d59efc89a8a",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
}
EXPECTED_EVENTS = 1068
ABSORPTION_START = 1
ABSORPTION_END = 5
TRIGGER_START = 6
TRIGGER_END = 30
ENTRY_DELAY_MAX = 3
TIME_EXIT_SESSIONS = 120
MINIMUM_INDUSTRY_COVERAGE = 0.8
MINIMUM_ANNUAL_COMPLETED_STRICT = 50
MAXIMUM_CONTEXT_DATE = pd.Timestamp("2021-06-30")


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, or coordinate lineage."""


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


def same_coordinate_lineage(row: Any, lineage: float) -> bool:
    return bool(
        not pd.isna(row.invalid_step_cum)
        and float(row.invalid_step_cum) == lineage
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
    )


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
        and same_coordinate_lineage(row, lineage)
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid)
        and bool(row.market_rule_valid)
        and bool(row.hard_valid)
        and int(row.trade_status) == 1
        and float(row.coord_high) > 0
        and float(row.coord_low) > 0
        and float(row.coord_close) > 0
        and pd.Timestamp(row.available_at) <= pd.Timestamp(row.decision_at)
    )


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


def compound_industry_return(
    industry: str,
    start_idx: int,
    end_idx: int,
    lookup: dict[tuple[str, int], float],
) -> tuple[float, int, int] | None:
    expected = end_idx - start_idx + 1
    values = [lookup.get((industry, idx), math.nan) for idx in range(start_idx, end_idx + 1)]
    finite = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    minimum = int(math.ceil(MINIMUM_INDUSTRY_COVERAGE * expected))
    if len(finite) < minimum or np.any(finite <= -1.0):
        return None
    return float(np.expm1(np.log1p(finite).sum())), int(len(finite)), expected


def replay_without_returns(
    candidate: Any,
    path: pd.DataFrame,
    regime_lookup: dict[pd.Timestamp, Any],
    industry_returns: dict[tuple[str, int], float],
) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.invalid_step_cum)
    event_low = float(candidate.coord_low)
    event_high = float(candidate.coord_high)
    event_close = float(candidate.coord_close)
    common = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "pit_industry": str(candidate.causal_industry),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_year": int(pd.Timestamp(candidate.signal_date).year),
        "signal_cal_idx": signal_idx,
        "event_low": event_low,
        "event_high": event_high,
        "event_close": event_close,
        "circulating_share_increase": float(candidate.circulating_share_increase),
    }
    by_idx = {
        int(row.cal_idx): row
        for row in path.sort_values("cal_idx", kind="mergesort").itertuples(index=False)
    }

    below_low_streak = 0
    absorption_valid_closes = 0
    for offset in range(ABSORPTION_START, ABSORPTION_END + 1):
        row = by_idx.get(signal_idx + offset)
        if row is None:
            return {**common, "status": "MISSING_ABSORPTION_SESSION"}
        if not same_coordinate_lineage(row, lineage):
            return {**common, "status": "INVALID_ABSORPTION_LINEAGE"}
        if not valid_completed_close(row, lineage):
            continue
        absorption_valid_closes += 1
        below_low_streak = below_low_streak + 1 if float(row.coord_close) < event_low else 0
        if below_low_streak >= 2:
            return {
                **common,
                "absorption_valid_closes": absorption_valid_closes,
                "status": "IMMEDIATE_SUPPLY_REJECTION",
            }

    trigger = None
    trigger_market = None
    trigger_stock_return = math.nan
    trigger_industry_return = math.nan
    trigger_industry_observations = 0
    trigger_industry_expected = 0
    for offset in range(TRIGGER_START, TRIGGER_END + 1):
        row = by_idx.get(signal_idx + offset)
        if row is None:
            return {
                **common,
                "absorption_valid_closes": absorption_valid_closes,
                "status": "MISSING_TRIGGER_SESSION",
            }
        if not same_coordinate_lineage(row, lineage):
            return {
                **common,
                "absorption_valid_closes": absorption_valid_closes,
                "status": "INVALID_TRIGGER_LINEAGE",
            }
        if not valid_completed_close(row, lineage) or float(row.coord_close) <= event_high:
            continue
        industry_result = compound_industry_return(
            str(candidate.causal_industry), signal_idx + 1, int(row.cal_idx), industry_returns
        )
        if industry_result is None:
            continue
        industry_return, observed, expected = industry_result
        stock_return = float(row.coord_close) / event_close - 1.0
        if stock_return <= industry_return:
            continue
        market_row = regime_lookup.get(pd.Timestamp(row.trade_date).normalize())
        if market_row is None or not market_opportunity(market_row, pd.Timestamp(row.decision_at)):
            continue
        trigger = row
        trigger_market = market_row
        trigger_stock_return = stock_return
        trigger_industry_return = industry_return
        trigger_industry_observations = observed
        trigger_industry_expected = expected
        break

    if trigger is None or trigger_market is None:
        return {
            **common,
            "absorption_valid_closes": absorption_valid_closes,
            "status": "NO_QUALIFYING_DEMAND_REASSERTION",
        }

    trigger_idx = int(trigger.cal_idx)
    selected = {
        **common,
        "absorption_valid_closes": absorption_valid_closes,
        "trigger_date": pd.Timestamp(trigger.trade_date),
        "trigger_cal_idx": trigger_idx,
        "trigger_stock_return_from_event": trigger_stock_return,
        "trigger_industry_return_from_event": trigger_industry_return,
        "trigger_industry_observations": trigger_industry_observations,
        "trigger_industry_expected": trigger_industry_expected,
        "trigger_market_regime": str(trigger_market.market_regime),
        "trigger_market_median_ret20": float(trigger_market.market_median_ret20),
        "trigger_market_median_ret60": float(trigger_market.market_median_ret60),
        "trigger_market_positive_ret20_share": float(trigger_market.market_positive_ret20_share),
        "trigger_market_positive_ret60_share": float(trigger_market.market_positive_ret60_share),
    }
    entry = next(
        (
            by_idx.get(idx)
            for idx in range(trigger_idx + 1, trigger_idx + ENTRY_DELAY_MAX + 1)
            if by_idx.get(idx) is not None
            and same_coordinate_lineage(by_idx[idx], lineage)
            and execution.buyable(by_idx[idx])
        ),
        None,
    )
    if entry is None:
        return {**selected, "status": "NO_LEGAL_ENTRY"}

    entry_idx = int(entry.cal_idx)
    below_low_streak = 0
    pending_failure_exit = False
    exit_row = None
    exit_reason = None
    maximum_idx = int(path.cal_idx.max())
    for idx in range(entry_idx, maximum_idx + 1):
        row = by_idx.get(idx)
        if row is None:
            return {
                **selected,
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "status": "MISSING_POST_ENTRY_MARKET_SESSION",
            }
        if not same_coordinate_lineage(row, lineage):
            return {
                **selected,
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "status": "INVALID_COORDINATE_LINEAGE",
            }
        if pending_failure_exit and idx > entry_idx and execution.sellable_open(row):
            exit_row = row
            exit_reason = "EVENT_LOW_FAILURE"
            break
        if idx >= entry_idx + TIME_EXIT_SESSIONS and execution.sellable_open(row):
            exit_row = row
            exit_reason = "TIME_EXIT_H120"
            break
        if valid_completed_close(row, lineage):
            below_low_streak = below_low_streak + 1 if float(row.coord_close) < event_low else 0
            if below_low_streak >= 2:
                pending_failure_exit = True

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


def industry_lookup() -> dict[tuple[str, int], float]:
    con = duckdb.connect()
    frame = con.execute(
        f"""
        SELECT causal_industry,cal_idx,median(step_return) AS median_step_return
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date<=DATE '2021-06-30'
          AND sleeve IN ('MAIN','CHINEXT') AND NOT is_st
          AND hard_valid AND current_valid AND current_day_data_tradable
          AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking AND historical_identity_valid
          AND causal_industry IS NOT NULL AND step_return IS NOT NULL
        GROUP BY causal_industry,cal_idx
        """
    ).fetch_df()
    con.close()
    return {
        (str(row.causal_industry), int(row.cal_idx)): float(row.median_step_return)
        for row in frame.itertuples(index=False)
        if np.isfinite(float(row.median_step_return))
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

    regime_by_date = {
        pd.Timestamp(row.trade_date).normalize(): row
        for row in regimes.itertuples(index=False)
    }
    returns_by_industry = industry_lookup()
    path_lookup = {key: part for key, part in paths.groupby("event_id", sort=False)}
    selections = pd.DataFrame(
        [
            replay_without_returns(
                candidate,
                path_lookup[str(candidate.event_id)],
                regime_by_date,
                returns_by_industry,
            )
            for candidate in candidates.sort_values(
                ["signal_date", "causal_industry", "symbol"], kind="mergesort"
            ).itertuples(index=False)
        ]
    ).sort_values(["signal_date", "pit_industry", "symbol"], kind="mergesort")
    write_parquet(selections, LEDGER)

    completed = selections.loc[selections.status.eq("COMPLETED")]
    annual_completed = {
        str(year): int(completed.signal_year.eq(year).sum()) for year in (2018, 2019, 2020)
    }
    breadth_gate_pass = all(
        count > MINIMUM_ANNUAL_COMPLETED_STRICT for count in annual_completed.values()
    )
    manifest = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_UNAGGREGATED_RULE_APPLICATION",
        "source_hashes": source_hashes,
        "script_sha256": sha256(Path(__file__)),
        "selection_ledger": str(LEDGER),
        "selection_ledger_sha256": sha256(LEDGER),
        "mother_events": int(len(selections)),
        "status_counts": {
            str(key): int(value)
            for key, value in selections.status.value_counts().sort_index().items()
        },
        "annual_completed": annual_completed,
        "minimum_annual_completed_strictly_greater_than": MINIMUM_ANNUAL_COMPLETED_STRICT,
        "breadth_gate_pass": bool(breadth_gate_pass),
        "annual_or_pooled_return_aggregate_produced": False,
        "post_2021_signal_identity_read": False,
        "validation_2022_2024_outcome_read": False,
        "maximum_context_date": str(paths.trade_date.max().date()),
    }
    write_json(MANIFEST, manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
