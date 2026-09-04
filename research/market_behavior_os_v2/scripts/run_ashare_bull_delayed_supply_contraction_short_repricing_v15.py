#!/usr/bin/env python3
"""Causal BULL routing and short translation of the exact V5 signal."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-BULL-DELAYED-SUPPLY-CONTRACTION-SHORT-REPRICING-V15"
ROOT = Path("/Volumes/quant/CY_quant_research")
V5 = ROOT / "ashare_demand_impulse_inside_day_delayed_breakout_v5"
CANDIDATES = V5 / "stage_a/candidates_frozen.parquet"
DISCOVERY_OUTCOMES = V5 / "stage_b/discovery_outcomes.parquet"
CONFIRMATION_OUTCOMES = V5 / "stage_b/confirmation_outcomes.parquet"
POST_OBSERVATION_OUTCOMES = (
    V5 / "stage_b/post_observation_diagnostic_2022_2023/outcomes.parquet"
)
REGIME = (
    ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/"
    "causal_market_regime_2014_2023.parquet"
)
DAILY = (
    ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUT = ROOT / "ashare_bull_delayed_supply_contraction_short_repricing_v15"
CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "experiments/ASHARE-BULL-DELAYED-SUPPLY-CONTRACTION-SHORT-REPRICING-V15_contract.json"
)
PROFILES = {"T10_H20": 0.10, "T15_H20": 0.15}


class ResearchError(RuntimeError):
    """Fail closed on causal or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
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
    values = (
        row.trade_status,
        row.current_day_data_tradable,
        row.market_rule_valid,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
    )
    return bool(
        not any(pd.isna(value) for value in values)
        and int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
    )


def sellable_open(row: Any) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_population() -> tuple[pd.DataFrame, pd.DataFrame]:
    connection = duckdb.connect()
    candidates = connection.execute(
        f"""
        SELECT c.*,r.market_regime,r.latest_source_timestamp
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        LEFT JOIN read_parquet('{REGIME.as_posix()}') r
          ON CAST(c.signal_date AS DATE)=r.trade_date
        ORDER BY c.signal_date,c.sleeve,c.event_id
        """
    ).fetch_df()
    entries = connection.execute(
        f"""
        SELECT event_id,status,entry_date,entry_cal_idx,entry_price
        FROM (
          SELECT * FROM read_parquet('{DISCOVERY_OUTCOMES.as_posix()}')
          UNION ALL
          SELECT * FROM read_parquet('{CONFIRMATION_OUTCOMES.as_posix()}')
          UNION ALL
          SELECT * FROM read_parquet('{POST_OBSERVATION_OUTCOMES.as_posix()}')
        )
        """
    ).fetch_df()
    connection.close()
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date).dt.normalize()
    candidates["decision_at"] = pd.to_datetime(candidates.decision_at)
    candidates["latest_source_timestamp"] = pd.to_datetime(
        candidates.latest_source_timestamp
    )
    if candidates.event_id.duplicated().any() or entries.event_id.duplicated().any():
        raise ResearchError("duplicate V5 identity")
    bull = candidates.loc[candidates.market_regime.eq("BULL")].copy()
    if (bull.latest_source_timestamp > bull.decision_at).any():
        raise ResearchError("causal BULL state uses post-signal data")
    population = bull.merge(entries, on="event_id", how="left", validate="one_to_one")
    tradable = population.loc[population.entry_cal_idx.notna()].copy()
    for column in ("entry_date",):
        tradable[column] = pd.to_datetime(tradable[column]).dt.normalize()
    return population, tradable


def load_paths(tradable: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "events",
        tradable[["event_id", "symbol", "entry_cal_idx"]],
    )
    paths = connection.execute(
        f"""
        SELECT e.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol
         AND d.cal_idx BETWEEN CAST(e.entry_cal_idx AS BIGINT)
                           AND CAST(e.entry_cal_idx AS BIGINT)+30
        ORDER BY e.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date).dt.normalize()
    return paths


def replay_one(event: Any, path: pd.DataFrame, profile: str, target_return: float) -> dict[str, Any]:
    pending = False
    decision_idx: int | None = None
    chosen: Any | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    target = float(event.entry_price) * (1.0 + target_return)
    for row in path.sort_values("cal_idx", kind="mergesort").itertuples(index=False):
        if int(row.cal_idx) <= int(event.entry_cal_idx):
            continue
        if (
            not np.isfinite(float(row.invalid_step_cum))
            or float(row.invalid_step_cum) != float(event.invalid_step_cum)
        ):
            return {"event_id": str(event.event_id), "status": "INVALID_COORDINATE_LINEAGE"}
        if pending and sellable_open(row):
            chosen = row
            exit_price = float(row.coord_open)
            exit_reason = "H20_TIME_STOP"
            break
        if (
            legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            chosen = row
            exit_price = target
            exit_reason = f"TARGET_{int(target_return * 100)}"
            decision_idx = int(event.entry_cal_idx)
            break
        if legal_state(row) and int(row.cal_idx) >= int(event.entry_cal_idx) + 20:
            pending = True
            decision_idx = int(row.cal_idx)
    if chosen is None:
        return {"event_id": str(event.event_id), "status": "NO_COMPLETED_EXIT"}
    gross = float(exit_price) / float(event.entry_price) - 1.0
    return {
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "sleeve": str(event.sleeve),
        "signal_date": pd.Timestamp(event.signal_date),
        "signal_cal_idx": int(event.cal_idx),
        "entry_date": pd.Timestamp(event.entry_date),
        "entry_cal_idx": int(event.entry_cal_idx),
        "entry_price": float(event.entry_price),
        "exit_date": pd.Timestamp(chosen.trade_date),
        "exit_cal_idx": int(chosen.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "exit_decision_cal_idx": int(decision_idx),
        "holding_sessions": int(chosen.cal_idx) - int(event.entry_cal_idx),
        "gross_return": gross,
        "net_return": gross - 0.004,
        "profile": profile,
        "status": "COMPLETED",
    }


def replay(tradable: pd.DataFrame, profile: str, target: float) -> pd.DataFrame:
    paths = load_paths(tradable)
    groups = {key: value for key, value in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(event, groups[str(event.event_id)], profile, target)
        for event in tradable.itertuples(index=False)
    ]
    return pd.DataFrame(rows)


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(complete.net_return, errors="coerce")
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "mean_net": None if complete.empty else float(values.mean()),
        "median_net": None if complete.empty else float(values.median()),
        "win_rate": None if complete.empty else float(values.gt(0).mean()),
        "severe10": None if complete.empty else float(values.le(-0.10).mean()),
        "target_hit": (
            None if complete.empty else float(complete.exit_reason.str.startswith("TARGET").mean())
        ),
        "average_holding_sessions": (
            None if complete.empty else float(complete.holding_sessions.mean())
        ),
    }


def summarize(frame: pd.DataFrame, start_year: int, end_year: int) -> dict[str, Any]:
    part = frame.loc[
        frame.signal_date.dt.year.between(start_year, end_year)
    ].copy()
    annual = {
        str(year): metrics(part.loc[part.signal_date.dt.year.eq(year)])
        for year in range(start_year, end_year + 1)
    }
    yearly_means = [
        item["mean_net"] for item in annual.values() if item["mean_net"] is not None
    ]
    return {
        "pooled": metrics(part),
        "annual": annual,
        "median_annual_mean_net": (
            None if not yearly_means else float(np.median(yearly_means))
        ),
    }


def select_profile(development: list[dict[str, Any]]) -> str | None:
    eligible = [
        item
        for item in development
        if item["development"]["pooled"]["mean_net"] > 0.03
        and item["development"]["pooled"]["average_holding_sessions"] <= 15
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda item: (
            -item["development"]["median_annual_mean_net"],
            -item["development"]["pooled"]["mean_net"],
            0 if item["profile"] == "T10_H20" else 1,
        )
    )
    return str(eligible[0]["profile"])


def main() -> None:
    for path in (
        CONTRACT,
        CANDIDATES,
        DISCOVERY_OUTCOMES,
        CONFIRMATION_OUTCOMES,
        POST_OBSERVATION_OUTCOMES,
        REGIME,
        DAILY,
    ):
        if not path.is_file():
            raise ResearchError(f"missing required input: {path}")
    population, tradable = load_population()
    if len(population) != 260:
        raise ResearchError(f"BULL-routed identity drift: {len(population)}")
    pre_diagnostic = tradable.loc[tradable.signal_date.dt.year.le(2021)].copy()
    development_results: list[dict[str, Any]] = []
    ledgers: dict[str, pd.DataFrame] = {}
    for profile, target in PROFILES.items():
        ledger = replay(pre_diagnostic, profile, target)
        ledger["signal_date"] = pd.to_datetime(ledger.signal_date)
        ledgers[profile] = ledger
        development_results.append(
            {
                "profile": profile,
                "development": summarize(ledger, 2014, 2018),
            }
        )
    selected = select_profile(development_results)
    if selected is None:
        result = {
            "experiment": EXPERIMENT,
            "verdict": "NO_BULL_SHORT_TRANSLATION_PASSES_DEVELOPMENT",
            "population": int(len(population)),
            "development_profiles": development_results,
            "confirmation_opened": False,
            "audit": {
                "regime_after_signal_count": 0,
                "repository_2024_plus_data_opened": False,
            },
        }
    else:
        ledger = replay(tradable, selected, PROFILES[selected])
        ledger["signal_date"] = pd.to_datetime(ledger.signal_date)
        confirmation = summarize(ledger, 2019, 2021)
        post_observation = summarize(ledger, 2022, 2023)
        result = {
            "experiment": EXPERIMENT,
            "verdict": "BULL_SHORT_TRANSLATION_CANDIDATE",
            "population": int(len(population)),
            "tradable_entries": int(len(tradable)),
            "development_profiles": development_results,
            "selected_profile": selected,
            "confirmation": confirmation,
            "post_observation_2022_2023": post_observation,
            "full_2014_2023": summarize(ledger, 2014, 2023),
            "audit": {
                "regime_after_signal_count": int(
                    (population.latest_source_timestamp > population.decision_at).sum()
                ),
                "entry_at_or_before_signal_count": int(
                    (tradable.entry_date <= tradable.signal_date).sum()
                ),
                "t1_same_day_exit_count": int(
                    ledger.loc[ledger.status.eq("COMPLETED"), "exit_date"].eq(
                        ledger.loc[ledger.status.eq("COMPLETED"), "entry_date"]
                    ).sum()
                ),
                "repository_2024_plus_data_opened": False,
                "post_2021_used_in_profile_selection": False,
            },
        }
        OUT.mkdir(parents=True, exist_ok=True)
        write_parquet(ledger, OUT / "selected_profile_trades.parquet")
    OUT.mkdir(parents=True, exist_ok=True)
    result["contract_sha256"] = sha256(CONTRACT)
    result["candidate_sha256"] = sha256(CANDIDATES)
    write_json(OUT / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
