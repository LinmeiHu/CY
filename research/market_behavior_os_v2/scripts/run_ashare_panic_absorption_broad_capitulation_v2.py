#!/usr/bin/env python3
"""Freeze and evaluate the chart-derived broad panic-absorption rule.

Stage ``freeze`` reads 2024 rows only through each candidate's completed signal
close and writes outcome-blind identities.  Stage ``evaluate`` verifies that
freeze before attaching the already frozen 2022-2023 outcomes and the newly
authorized 2024 paths.  No 2025 signal may enter either stage.
"""

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


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-PANIC-ABSORPTION-BROAD-CAPITULATION-V2"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
RULE_FREEZE = OS_ROOT / (
    "experiments/ASHARE-PANIC-ABSORPTION-12M-CHART-RULE-"
    "DISCOVERY-V1_rules_freeze.json"
)
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

SOURCE_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_panic_gap_down_full_absorption_reversal_v1"
)
DEV_CANDIDATES = SOURCE_ROOT / "stage_a/freeze/frozen_candidates.parquet"
DEV_OUTCOMES = SOURCE_ROOT / "stage_b/outcomes.parquet"
OLD_VALIDATION_CANDIDATES = (
    SOURCE_ROOT / "validation/freeze/frozen_candidates_2022_2023.parquet"
)
OLD_VALIDATION_OUTCOMES = (
    SOURCE_ROOT / "validation/results/validation_outcomes.parquet"
)
OLD_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
CURRENT_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "pit_daily_qd010_exact_2022_2026q1.parquet"
)
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_panic_absorption_broad_capitulation_v2"
)
FROZEN_2024 = EXT_ROOT / "stage_a/frozen_2024_candidates.parquet"
SELECTED_2024 = EXT_ROOT / "stage_a/frozen_2024_broad_capitulation.parquet"
STAGE_A_FREEZE = EXT_ROOT / "stage_a/stage_a_freeze.json"
OUTCOMES_2024 = EXT_ROOT / "stage_b/outcomes_2024.parquet"

PROFILE = "T10_H20_NO_STOP"
SIGNAL_END = pd.Timestamp("2024-12-31")
OUTCOME_END = pd.Timestamp("2025-03-31")

EXPECTED = {
    "development_candidates": "c4d4d5a4feef587d6ec5ea4f69b39f0992e4cb758bd1336c4740f1bde173dd85",
    "development_outcomes": "c13281f9702f6b89831a514810f281745637819e5860fda36810c1bfb548496f",
    "validation_candidates": "791dec7f430fb8d2fdee22e77f77745b908f87fac3b9754f0a09c9a2a2f3464f",
    "validation_outcomes": "44474f1a5e88c0a747b65daa2fd9356a18e7fcd7aa34ff93c7734ad8fad95130",
    "chart_rule_freeze": "8313df3f825dc1ef8cef14fcc4e0fa1d657a047b51d091d53c127934cfcdaeba",
}


class ExperimentError(RuntimeError):
    """Fail closed when a frozen identity or execution contract drifts."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        + "\n",
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


def read_parquet(path: Path, where: str = "") -> pd.DataFrame:
    query = f"SELECT * FROM read_parquet('{path.as_posix()}')"
    if where:
        query += f" WHERE {where}"
    return duckdb.connect().execute(query).fetch_df()


def verify_frozen_inputs() -> dict[str, str]:
    paths = {
        "development_candidates": DEV_CANDIDATES,
        "development_outcomes": DEV_OUTCOMES,
        "validation_candidates": OLD_VALIDATION_CANDIDATES,
        "validation_outcomes": OLD_VALIDATION_OUTCOMES,
        "chart_rule_freeze": RULE_FREEZE,
    }
    missing = [str(path) for path in [CONTRACT, OLD_DAILY, CURRENT_DAILY, *paths.values()] if not path.is_file()]
    if missing:
        raise ExperimentError(f"missing required frozen input: {missing}")
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": EXPECTED[name], "actual": value}
        for name, value in actual.items()
        if value != EXPECTED[name]
    }
    if drift:
        raise ExperimentError(f"frozen source drift: {drift}")
    return actual


def candidate_query(daily: Path, start: str, end: str) -> str:
    return f"""
    WITH source AS (
      SELECT * FROM read_parquet('{daily.as_posix()}')
      WHERE trade_date <= DATE '{end}'
    ), features AS (
      SELECT *,
        lag(coord_close,20) OVER w AS lag20_close_x,
        lag(cal_idx,20) OVER w AS lag20_idx_x,
        lag(invalid_step_cum,20) OVER w AS lag20_invalid_x,
        lag(coord_high,1) OVER w AS prior_high_x,
        lag(coord_low,1) OVER w AS prior_low_x,
        min(coord_low) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) AS low5prev_x,
        avg(turnover_fraction) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS turn20_x,
        count(*) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS n20,
        min(current_day_data_tradable::INTEGER) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS tradable20,
        min(current_valid::INTEGER) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS valid20
      FROM source
      WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
    ), eligible AS (
      SELECT *,
        coord_close / lag20_close_x - 1.0 AS ret20_x,
        coord_open / prior_coord_close - 1.0 AS open_gap_x,
        (coord_close - coord_low) / nullif(coord_high - coord_low, 0.0) AS close_location_x
      FROM features
      WHERE trade_date BETWEEN DATE '{start}' AND DATE '{end}'
    )
    SELECT
      symbol,sleeve,trade_date AS signal_date,cal_idx,
      coord_open,coord_high,coord_low,coord_close,prior_coord_close,
      up_limit_price,turnover_fraction,
      coord_close/prior_coord_close-1.0 AS step_return,
      ret20_x AS ret20,prior_high_x AS prior_high,prior_low_x AS prior_low,
      low5prev_x AS low5prev,coord_low AS stabilized_low_coord,
      turn20_x AS turn20,open_gap_x AS open_gap,
      close_location_x AS close_location,invalid_step_cum,available_at,decision_at
    FROM eligible
    WHERE hard_valid AND history_valid AND current_valid
      AND current_day_data_tradable AND market_rule_valid
      AND corporate_action_valid AND NOT corporate_action_blocking AND NOT is_st
      AND n20=20 AND tradable20=1 AND valid20=1
      AND cal_idx-lag20_idx_x=20
      AND invalid_step_cum=lag20_invalid_x
      AND ret20_x<=-0.10
      AND open_gap_x<=-0.01
      AND coord_low<=low5prev_x
      AND turnover_fraction>=turn20_x
      AND coord_close>=prior_high_x
      AND close_location_x>=0.70
      AND round(close*100)<round(up_limit_price*100)
    ORDER BY symbol,cal_idx
    """


def apply_cooldown(high_recall: pd.DataFrame) -> pd.DataFrame:
    high_recall = high_recall.copy()
    high_recall["signal_date"] = pd.to_datetime(high_recall.signal_date)
    keep: list[int] = []
    for _, part in high_recall.groupby("symbol", sort=False):
        last = -10**12
        for index, row in part.sort_values("cal_idx", kind="mergesort").iterrows():
            if int(row.cal_idx) - last > 20:
                keep.append(index)
                last = int(row.cal_idx)
    frozen = high_recall.loc[keep].copy()
    frozen["event_id"] = (
        frozen.symbol.astype(str)
        + "|"
        + frozen.signal_date.dt.strftime("%Y-%m-%d")
    )
    frozen = frozen.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if frozen.event_id.duplicated().any():
        raise ExperimentError("duplicate frozen event identity")
    return frozen


def audit_detector_reproduction() -> dict[str, Any]:
    high = duckdb.connect().execute(
        candidate_query(OLD_DAILY, "2014-01-01", "2021-12-31")
    ).fetch_df()
    rebuilt = apply_cooldown(high)
    source = read_parquet(DEV_CANDIDATES)
    source_ids = set(source.event_id.astype(str))
    rebuilt_ids = set(rebuilt.event_id.astype(str))
    if rebuilt_ids != source_ids:
        raise ExperimentError(
            "mother detector does not reproduce frozen 2014-2021 identities: "
            f"missing={len(source_ids-rebuilt_ids)} extra={len(rebuilt_ids-source_ids)}"
        )
    return {
        "rebuilt_count": int(len(rebuilt)),
        "source_count": int(len(source)),
        "identity_match": True,
    }


def build_2024_candidates() -> tuple[pd.DataFrame, pd.DataFrame]:
    # The 2023 lookback is used only so a late-2023 event can enforce the exact
    # 20-session symbol cooldown on an early-2024 event.
    high = duckdb.connect().execute(
        candidate_query(CURRENT_DAILY, "2023-10-01", "2024-12-31")
    ).fetch_df()
    frozen = apply_cooldown(high)
    frozen = frozen.loc[frozen.signal_date.dt.year.eq(2024)].copy()
    frozen["same_date_signal_count"] = frozen.groupby("signal_date").event_id.transform("size")
    selected = frozen.loc[frozen.same_date_signal_count.ge(2)].copy()
    for frame in (frozen, selected):
        if pd.to_datetime(frame.signal_date).max() > SIGNAL_END:
            raise ExperimentError("post-2024 signal entered Stage A")
        if pd.to_datetime(frame.available_at).gt(pd.to_datetime(frame.decision_at)).any():
            raise ExperimentError("feature availability exceeds decision time")
    return frozen.reset_index(drop=True), selected.reset_index(drop=True)


def development_metrics() -> dict[str, Any]:
    candidates = read_parquet(
        DEV_CANDIDATES,
        "signal_date >= DATE '2014-01-01' AND signal_date <= DATE '2020-12-31'",
    )
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    candidates["same_date_signal_count"] = candidates.groupby("signal_date").event_id.transform("size")
    selected = candidates.loc[candidates.same_date_signal_count.ge(2)].copy()
    outcomes = read_parquet(DEV_OUTCOMES, f"profile = '{PROFILE}'")
    return summarize(selected, outcomes, range(2014, 2021))


def run_freeze() -> dict[str, Any]:
    source_hashes = verify_frozen_inputs()
    reproduction = audit_detector_reproduction()
    development = development_metrics()
    if not all(development["gate"].values()):
        raise ExperimentError(f"development gate did not authorize 2024: {development['gate']}")
    frozen, selected = build_2024_candidates()
    write_parquet(frozen, FROZEN_2024)
    write_parquet(selected, SELECTED_2024)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_2024_IDENTITY_FREEZE",
        "contract_sha256": sha256(CONTRACT),
        "rule_freeze_sha256": sha256(RULE_FREEZE),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "current_daily_sha256": sha256(CURRENT_DAILY),
        "detector_reproduction": reproduction,
        "development_2014_2020": development,
        "raw_2024_signals": int(len(frozen)),
        "selected_2024_signals": int(len(selected)),
        "selected_2024_signal_dates": int(selected.signal_date.nunique()),
        "frozen_2024_sha256": sha256(FROZEN_2024),
        "selected_2024_sha256": sha256(SELECTED_2024),
        "max_signal_date": None if selected.empty else str(selected.signal_date.max().date()),
        "return_or_target_outcome_read": "NO",
        "2025_signal_read": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise ExperimentError("Stage-A freeze is missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    current = {
        "contract_sha256": sha256(CONTRACT),
        "rule_freeze_sha256": sha256(RULE_FREEZE),
        "runner_sha256": sha256(Path(__file__)),
        "current_daily_sha256": sha256(CURRENT_DAILY),
        "frozen_2024_sha256": sha256(FROZEN_2024),
        "selected_2024_sha256": sha256(SELECTED_2024),
    }
    drift = {
        key: {"frozen": freeze.get(key), "current": value}
        for key, value in current.items()
        if freeze.get(key) != value
    }
    if drift:
        raise ExperimentError(f"Stage-A freeze drift: {drift}")
    return freeze


def legal_state(row: pd.Series) -> bool:
    required = (
        "trade_status",
        "current_day_data_tradable",
        "market_rule_valid",
        "corporate_action_valid",
        "corporate_action_blocking",
        "hard_valid",
    )
    if any(pd.isna(row.get(field)) for field in required):
        return False
    return bool(
        int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
    )


def buyable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_2024_paths(candidates: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "candidate_ids",
        candidates[["event_id", "symbol", "sleeve", "signal_date", "cal_idx", "invalid_step_cum"]],
    )
    result = connection.execute(
        f"""
        SELECT c.event_id,c.symbol,c.sleeve,c.signal_date,
          c.cal_idx AS signal_cal_idx,
          c.invalid_step_cum AS signal_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM candidate_ids c
        JOIN read_parquet('{CURRENT_DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.cal_idx
        WHERE d.trade_date<=DATE '2025-03-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    result["trade_date"] = pd.to_datetime(result.trade_date)
    return result


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.cal_idx)
    lineage = float(candidate.invalid_step_cum)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "profile": PROFILE,
    }
    entry_pool = path.loc[
        path.cal_idx.le(signal_idx + 3) & path.invalid_step_cum.eq(lineage)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if buyable_open(row)), None)
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * 1.10
    pending = False
    decision_idx: int | None = None
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    invalid = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H20_TIME_STOP"
            break
        if legal_state(row) and np.isfinite(float(row.coord_high)) and float(row.coord_high) >= target:
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_10"
            decision_idx = entry_idx
            break
        if legal_state(row) and int(row.cal_idx) >= entry_idx + 20:
            pending = True
            decision_idx = int(row.cal_idx)
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {**base, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY", **entry_payload}
    if exit_row is None:
        return {**base, "status": "INCOMPLETE_BY_2025_03_31", **entry_payload}
    gross = float(exit_price) / entry_price - 1.0
    return {
        **base,
        "status": "COMPLETED",
        **entry_payload,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "exit_decision_cal_idx": decision_idx,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - 0.004,
    }


def replay_2024(candidates: pd.DataFrame) -> pd.DataFrame:
    paths = load_2024_paths(candidates)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    records = [
        replay_one(event, groups.get(str(event.event_id), pd.DataFrame()))
        for event in candidates.itertuples(index=False)
    ]
    result = pd.DataFrame(records)
    if not result.empty and pd.to_datetime(result.signal_date).dt.year.ne(2024).any():
        raise ExperimentError("non-2024 signal entered new challenge")
    return result


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(complete.net_return, errors="coerce")
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "mean_net": None if complete.empty else float(values.mean()),
        "median_net": None if complete.empty else float(values.median()),
        "win": None if complete.empty else float(values.gt(0).mean()),
        "severe10": None if complete.empty else float(values.le(-0.10).mean()),
        "target_hit": None if complete.empty else float(complete.exit_reason.eq("TARGET_10").mean()),
        "mean_holding": None if complete.empty else float(complete.holding_sessions.mean()),
    }


def summarize(candidates: pd.DataFrame, outcomes: pd.DataFrame, years: range) -> dict[str, Any]:
    candidates = candidates.copy()
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    outcomes = outcomes.copy()
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    if outcomes.event_id.duplicated().any():
        raise ExperimentError("duplicate selected-profile outcome identity")
    joined = candidates[["event_id", "signal_date", "symbol", "sleeve"]].merge(
        outcomes.drop(columns=["signal_date", "symbol", "sleeve"], errors="ignore"),
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    yearly = {
        str(year): metrics(joined.loc[joined.signal_date.dt.year.eq(year)])
        for year in years
    }
    pooled = metrics(joined)
    n_years = len(list(years))
    gate = {
        "completed_per_year_gt_50": pooled["completed"] / n_years > 50,
        "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None and pooled["mean_net"] > 0.04,
        "pooled_median_net_positive": pooled["median_net"] is not None and pooled["median_net"] > 0,
        "severe10_le_15pct": pooled["severe10"] is not None and pooled["severe10"] <= 0.15,
        "every_year_with_completed_trades_mean_positive": all(
            item["completed"] == 0 or (item["mean_net"] is not None and item["mean_net"] > 0)
            for item in yearly.values()
        ),
    }
    return {
        "pooled": pooled,
        "completed_per_year": pooled["completed"] / n_years,
        "yearly": yearly,
        "gate": gate,
    }


def load_old_validation_selected() -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = read_parquet(OLD_VALIDATION_CANDIDATES)
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    candidates["same_date_signal_count"] = candidates.groupby("signal_date").event_id.transform("size")
    selected = candidates.loc[candidates.same_date_signal_count.ge(2)].copy()
    outcomes = read_parquet(OLD_VALIDATION_OUTCOMES, f"profile = '{PROFILE}'")
    outcomes = outcomes.loc[outcomes.event_id.isin(set(selected.event_id.astype(str)))].copy()
    return selected, outcomes


def render_report(result: dict[str, Any]) -> None:
    development = result["development_2014_2020"]
    challenge = result["challenge_2022_2024"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "## Simple strategy",
        "",
        "1. After a 20-session loss of at least 10%, require a >=1% gap-down to a new five-session low.",
        "2. Require same-day turnover at least its prior-20 mean and a close above the prior high in the top 30% of the daily range.",
        "3. Admit only when at least two independent stocks show this same completed-session absorption event.",
        "4. Buy the first legal open in the next three market sessions; sell at +10% or the next legal open after H20; no failure stop; 40 bp round trip.",
        "",
        "All signal and cluster information is known at the completed signal close. No future-function market state is used.",
        "",
        "## Development 2014-2020",
        "",
        f"Completed {development['pooled']['completed']} ({development['completed_per_year']:.1f}/year); mean {development['pooled']['mean_net']:.2%}; median {development['pooled']['median_net']:.2%}; severe10 {development['pooled']['severe10']:.2%}.",
        "",
        "## Challenge 2022-2024",
        "",
        f"Completed {challenge['pooled']['completed']} ({challenge['completed_per_year']:.1f}/year); mean {challenge['pooled']['mean_net']:.2%}; median {challenge['pooled']['median_net']:.2%}; severe10 {challenge['pooled']['severe10']:.2%}.",
        "",
        "|Year|Signals|Completed|Mean net|Median net|Win|Severe10|Target hit|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in (2022, 2023, 2024):
        item = challenge["yearly"][str(year)]
        lines.append(
            f"|{year}|{item['signals']}|{item['completed']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|{item['win']:.2%}|{item['severe10']:.2%}|{item['target_hit']:.2%}|"
        )
    lines += [
        "",
        "## Scientific status",
        "",
        "The chart-derived rule is post-hoc to consumed 2014-2021 charts. The 2022-2023 rows were already consumed by the mother experiment and are reused as a robustness block, not untouched validation. Only 2024 is a newly opened frozen-rule challenge. No 2025 signal is read; 2025 rows only complete pre-2025 positions.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_evaluate() -> dict[str, Any]:
    freeze = verify_stage_a()
    selected_2024 = read_parquet(SELECTED_2024)
    selected_2024["signal_date"] = pd.to_datetime(selected_2024.signal_date)
    outcomes_2024 = replay_2024(selected_2024)
    write_parquet(outcomes_2024, OUTCOMES_2024)

    old_candidates, old_outcomes = load_old_validation_selected()
    all_candidates = pd.concat([old_candidates, selected_2024], ignore_index=True)
    all_outcomes = pd.concat([old_outcomes, outcomes_2024], ignore_index=True)
    challenge = summarize(all_candidates, all_outcomes, range(2022, 2025))
    development = freeze["development_2014_2020"]
    audit = {
        "signal_bar_fill_count": int(
            all_outcomes.loc[all_outcomes.status.eq("COMPLETED")]
            .entry_cal_idx.le(all_outcomes.loc[all_outcomes.status.eq("COMPLETED")].signal_cal_idx)
            .sum()
        ),
        "exit_at_or_before_entry_count": int(
            all_outcomes.loc[all_outcomes.status.eq("COMPLETED")]
            .exit_cal_idx.le(all_outcomes.loc[all_outcomes.status.eq("COMPLETED")].entry_cal_idx)
            .sum()
        ),
        "post_2024_signal_count": int(pd.to_datetime(all_outcomes.signal_date).dt.year.gt(2024).sum()),
        "new_2024_max_exit_date": None
        if outcomes_2024.empty or outcomes_2024.get("exit_date") is None
        else str(pd.to_datetime(outcomes_2024.exit_date).max().date()),
        "2025_signal_read": "NO",
        "2025_rows_role": "PRE_2025_TRADE_COMPLETION_ONLY",
    }
    if any(audit[key] for key in ("signal_bar_fill_count", "exit_at_or_before_entry_count", "post_2024_signal_count")):
        raise ExperimentError(f"execution chronology audit failed: {audit}")
    result = {
        "experiment": EXPERIMENT,
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_2014_2020": development,
        "challenge_2022_2024": challenge,
        "challenge_components": {
            "2022_2023": "PREVIOUSLY_CONSUMED_FROZEN_VALIDATION",
            "2024": "NEWLY_OPENED_FROZEN_RULE_CHALLENGE",
        },
        "audit": audit,
        "outcomes_2024_sha256": sha256(OUTCOMES_2024),
        "verdict": (
            "BROAD_CAPITULATION_RULE_PASSES_2022_2024_GATE"
            if all(challenge["gate"].values())
            else "BROAD_CAPITULATION_RULE_FAILS_2022_2024_GATE"
        ),
    }
    write_json(RESULT, result)
    render_report(result)
    result["result_sha256"] = sha256(RESULT)
    result["report_sha256"] = sha256(REPORT)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("freeze", "evaluate"), required=True)
    args = parser.parse_args()
    result = run_freeze() if args.stage == "freeze" else run_evaluate()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))


if __name__ == "__main__":
    main()
