#!/usr/bin/env python3
"""Replay the single frozen V19R1 chart-rule compression on 2014-2020 only."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-CAUSAL-BEAR-BULL-DUAL-ENGINE-CHART-RULE-COMPRESSION-V19R1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "54a753040130389eda0d3f6e0dca3d08522bf08a60b3221bb02961a616ab8d69"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
CHART_ROOT = DATA_ROOT / "ashare_causal_bear_bull_dual_engine_12m_chart_discovery_v19"
MOTHER = CHART_ROOT / "frozen_candidate_ledger.parquet"
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
    "mother": "b19991bc6ae2e6540c794faf3c83fdb0ce8eb2f09f1539cad2702f63ba1e2ed6",
    "daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_causal_bear_bull_dual_engine_chart_rule_compression_v19r1"
OUTCOMES = OUTPUT_ROOT / "development_2014_2020_outcomes.parquet"
DECISIONS = OUTPUT_ROOT / "development_2014_2020_confirmation_ledger.parquet"
RESULT = OUTPUT_ROOT / "result.json"
ROUND_TRIP_COST = 0.004
MAX_PATH_SESSIONS = 256


class ResearchError(RuntimeError):
    """Fail closed on identity, PIT chronology, lineage, or execution."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
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


def verify_inputs() -> dict[str, str]:
    paths = {"freeze": FREEZE, "mother": MOTHER, "daily": DAILY, "regime": REGIME}
    expected = {"freeze": EXPECTED_FREEZE_SHA256, **EXPECTED_HASHES}
    actual: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[name] = sha256(path)
        if actual[name] != expected[name]:
            raise ResearchError(f"{name} identity drift: {actual[name]} != {expected[name]}")
    return actual


def legal_observation(row: pd.Series) -> bool:
    required = (
        "trade_status",
        "current_day_data_tradable",
        "current_valid",
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
        and row.current_valid
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
    )


def buyable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    return bool(
        legal_observation(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        legal_observation(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_mother() -> pd.DataFrame:
    connection = duckdb.connect()
    mother = connection.execute(
        f"""
        SELECT m.chart_event_id,m.source_event_id,m.symbol,m.sleeve,m.engine,
          m.admission_lane,m.signal_date,m.signal_cal_idx,m.structural_level,
          m.market_regime,m.outcome_bucket,m.net_return AS original_net_return,
          d.coord_close AS signal_coord_close,d.invalid_step_cum AS signal_lineage,
          d.available_at AS signal_available_at,d.decision_at AS signal_decision_at
        FROM read_parquet('{MOTHER.as_posix()}') m
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON m.symbol=d.symbol AND m.signal_cal_idx=d.cal_idx
        WHERE m.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY m.signal_date,m.engine,m.sleeve,m.symbol,m.chart_event_id
        """
    ).fetch_df()
    connection.close()
    mother["signal_date"] = pd.to_datetime(mother.signal_date)
    mother["signal_available_at"] = pd.to_datetime(mother.signal_available_at)
    mother["signal_decision_at"] = pd.to_datetime(mother.signal_decision_at)
    if len(mother) != 840 or mother.chart_event_id.nunique() != 840:
        raise ResearchError(f"mother identity drift: {len(mother)}")
    if mother.signal_available_at.gt(mother.signal_decision_at).any():
        raise ResearchError("mother signal available after decision")
    if mother.signal_coord_close.isna().any() or mother.signal_lineage.isna().any():
        raise ResearchError("missing signal coordinate or lineage")
    return mother


def load_paths(mother: pd.DataFrame) -> pd.DataFrame:
    event_ids = mother[
        ["chart_event_id", "symbol", "signal_cal_idx", "signal_lineage"]
    ].copy()
    connection = duckdb.connect()
    connection.register("events", event_ids)
    paths = connection.execute(
        f"""
        SELECT e.chart_event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price,
          d.available_at,d.decision_at,r.market_regime,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol
         AND d.cal_idx>e.signal_cal_idx
         AND d.cal_idx<=e.signal_cal_idx+{MAX_PATH_SESSIONS}
        LEFT JOIN read_parquet('{REGIME.as_posix()}') r ON d.trade_date=r.trade_date
        ORDER BY e.chart_event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    for column in (
        "trade_date",
        "available_at",
        "decision_at",
        "market_latest_source_timestamp",
    ):
        paths[column] = pd.to_datetime(paths[column])
    return paths


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.signal_lineage)
    expected_regime = "BULL" if candidate.engine == "BULL_CONTINUATION" else "BEAR"
    target_return = 0.15 if expected_regime == "BULL" else 0.10
    horizon = 15 if expected_regime == "BULL" else 20
    base = {
        "chart_event_id": str(candidate.chart_event_id),
        "source_event_id": str(candidate.source_event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "engine": str(candidate.engine),
        "admission_lane": str(candidate.admission_lane),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "signal_coord_close": float(candidate.signal_coord_close),
        "structural_level": float(candidate.structural_level),
        "expected_market_regime": expected_regime,
        "target_return": target_return,
        "horizon_sessions": horizon,
    }
    confirmation_rows = path.loc[path.cal_idx.eq(signal_idx + 1)]
    if len(confirmation_rows) != 1:
        return {**base, "accepted": False, "status": "NO_IMMEDIATE_CONFIRMATION_BAR"}
    confirmation = confirmation_rows.iloc[0]
    confirmation_payload = {
        "confirmation_date": pd.Timestamp(confirmation.trade_date),
        "confirmation_cal_idx": int(confirmation.cal_idx),
        "confirmation_coord_close": float(confirmation.coord_close),
        "confirmation_market_regime": confirmation.market_regime,
        "confirmation_close_to_structure": float(confirmation.coord_close)
        / float(candidate.structural_level)
        - 1.0,
    }
    if (
        not np.isfinite(float(confirmation.invalid_step_cum))
        or float(confirmation.invalid_step_cum) != lineage
    ):
        return {
            **base,
            **confirmation_payload,
            "accepted": False,
            "status": "CONFIRMATION_LINEAGE_CHANGE",
        }
    if not legal_observation(confirmation):
        return {
            **base,
            **confirmation_payload,
            "accepted": False,
            "status": "INVALID_IMMEDIATE_CONFIRMATION_BAR",
        }
    if pd.isna(confirmation.market_latest_source_timestamp) or pd.Timestamp(
        confirmation.market_latest_source_timestamp
    ) > pd.Timestamp(confirmation.trade_date) + pd.Timedelta(hours=15):
        return {
            **base,
            **confirmation_payload,
            "accepted": False,
            "status": "INVALID_CONFIRMATION_MARKET_STATE_TIMESTAMP",
        }
    if confirmation.market_regime != expected_regime:
        return {
            **base,
            **confirmation_payload,
            "accepted": False,
            "status": "MARKET_STATE_NOT_PERSISTENT",
        }
    threshold = float(candidate.structural_level)
    if candidate.admission_lane == "IDIOSYNCRATIC_INFORMATION_JUMP":
        threshold = max(threshold, float(candidate.signal_coord_close))
    accepted = float(confirmation.coord_close) >= threshold
    confirmation_payload["confirmation_threshold"] = threshold
    confirmation_payload["accepted"] = accepted
    if not accepted:
        return {
            **base,
            **confirmation_payload,
            "status": "REJECTED_STRUCTURE_NOT_ACCEPTED",
        }
    same_lineage = path.loc[path.invalid_step_cum.eq(lineage)].copy()
    entry_pool = same_lineage.loc[
        same_lineage.cal_idx.gt(signal_idx + 1)
        & same_lineage.cal_idx.le(signal_idx + 4)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if buyable_open(row)), None)
    if entry is None:
        return {**base, **confirmation_payload, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target_price = entry_price * (1.0 + target_return)
    pending_time_exit = False
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    invalid = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending_time_exit and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = f"H{horizon}_TIME_STOP"
            break
        if (
            legal_observation(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            exit_row = row
            exit_price = target_price
            exit_reason = f"TARGET_{int(target_return * 100)}"
            break
        if legal_observation(row) and int(row.cal_idx) >= entry_idx + horizon:
            pending_time_exit = True
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {
            **base,
            **confirmation_payload,
            **entry_payload,
            "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
        }
    if exit_row is None:
        return {
            **base,
            **confirmation_payload,
            **entry_payload,
            "status": "INCOMPLETE_PATH",
        }
    gross = float(exit_price) / entry_price - 1.0
    return {
        **base,
        **confirmation_payload,
        **entry_payload,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "mother_signals": len(frame),
        "accepted": int(frame.accepted.fillna(False).sum()),
        "completed": len(completed),
        "signal_dates": int(completed.signal_date.nunique()),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "win_rate": None if completed.empty else float(values.gt(0).mean()),
        "severe10": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit": None
        if completed.empty
        else float(completed.exit_reason.str.startswith("TARGET_").mean()),
        "mean_holding_sessions": None
        if completed.empty
        else float(completed.holding_sessions.mean()),
    }


def summarize(outcomes: pd.DataFrame) -> dict[str, Any]:
    pooled = metrics(outcomes)
    yearly = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    by_engine = {
        str(engine): metrics(part)
        for engine, part in outcomes.groupby("engine", sort=True)
    }
    by_lane = {
        str(lane): metrics(part)
        for lane, part in outcomes.groupby("admission_lane", sort=True)
    }
    gates = {
        "completed_gt_50_each_year": all(
            item["completed"] > 50 for item in yearly.values()
        ),
        "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None
        and pooled["mean_net"] > 0.04,
        "pooled_median_net_positive": pooled["median_net"] is not None
        and pooled["median_net"] > 0,
        "every_year_mean_net_positive": all(
            item["mean_net"] is not None and item["mean_net"] > 0
            for item in yearly.values()
        ),
        "severe10_le_15pct": pooled["severe10"] is not None
        and pooled["severe10"] <= 0.15,
    }
    return {
        "pooled": pooled,
        "yearly": yearly,
        "by_engine": by_engine,
        "by_admission_lane": by_lane,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
    }


def original_bucket_acceptance(outcomes: pd.DataFrame, mother: pd.DataFrame) -> dict[str, Any]:
    joined = mother[["chart_event_id", "engine", "outcome_bucket"]].merge(
        outcomes[["chart_event_id", "accepted", "status"]],
        on="chart_event_id",
        how="left",
        validate="one_to_one",
    )
    payload: dict[str, Any] = {}
    for keys, part in joined.groupby(["engine", "outcome_bucket"], sort=True):
        engine, bucket = keys
        payload[f"{engine}|{bucket}"] = {
            "signals": len(part),
            "accepted": int(part.accepted.fillna(False).sum()),
            "acceptance_rate": float(part.accepted.fillna(False).mean()),
        }
    return payload


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    mother = load_mother()
    paths = load_paths(mother)
    groups = {key: part for key, part in paths.groupby("chart_event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            replay_one(candidate, groups.get(str(candidate.chart_event_id), pd.DataFrame()))
            for candidate in mother.itertuples(index=False)
        ]
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    if outcomes.chart_event_id.duplicated().any() or len(outcomes) != len(mother):
        raise ResearchError("outcome identity mismatch")
    if outcomes.signal_date.dt.year.gt(2020).any():
        raise ResearchError("post-2020 mother signal entered development")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    chronology = {
        "entry_at_or_before_signal": int(
            completed.entry_cal_idx.le(completed.signal_cal_idx).sum()
        ),
        "entry_at_or_before_confirmation": int(
            completed.entry_cal_idx.le(completed.confirmation_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(
            completed.exit_cal_idx.le(completed.entry_cal_idx).sum()
        ),
    }
    if any(chronology.values()):
        raise ResearchError(f"execution chronology failure: {chronology}")
    write_parquet(outcomes, OUTCOMES)
    decision_columns = [
        "chart_event_id",
        "source_event_id",
        "symbol",
        "sleeve",
        "engine",
        "admission_lane",
        "signal_date",
        "signal_cal_idx",
        "confirmation_date",
        "confirmation_cal_idx",
        "confirmation_coord_close",
        "confirmation_threshold",
        "confirmation_close_to_structure",
        "expected_market_regime",
        "confirmation_market_regime",
        "accepted",
        "status",
    ]
    write_parquet(outcomes.reindex(columns=decision_columns), DECISIONS)
    development = summarize(outcomes)
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_DEVELOPMENT_REPLAY",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "development_2014_2020": development,
        "original_outcome_bucket_acceptance": original_bucket_acceptance(outcomes, mother),
        "status_counts": {
            str(key): int(value)
            for key, value in outcomes.status.value_counts(dropna=False).sort_index().items()
        },
        "chronology_audit": chronology,
        "outcomes_sha256": sha256(OUTCOMES),
        "confirmation_ledger_sha256": sha256(DECISIONS),
        "post_2020_mother_signal_outcome_read": "NO",
        "later_period_open_authorized": development["all_gates_pass"],
        "verdict": (
            "V19R1_CHART_RULES_PASS_ALL_DEVELOPMENT_GATES"
            if development["all_gates_pass"]
            else "V19R1_CHART_RULES_FAIL_DEVELOPMENT_GATE"
        ),
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
