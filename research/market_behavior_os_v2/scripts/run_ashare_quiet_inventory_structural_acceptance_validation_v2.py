#!/usr/bin/env python3
"""Frozen V2 temporal challenge on 2022-2024 mother-signal years.

The V2 freeze predates this exact replay.  Earlier V1 work had already exposed
the years, so the output is labelled a temporal challenge rather than pristine
out-of-sample evidence.  The first legal post-breakout close confirms the
signal, the confirmation bar cannot fill, and entry begins at the next legal
open.  All required state and coordinate lineage fail closed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import run_ashare_quiet_inventory_fast_repricing_v1 as v1


ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = "ASHARE-QUIET-INVENTORY-STRUCTURAL-ACCEPTANCE-V2"
FREEZE = ROOT / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "b45392e4aa28e4141ebeb3f34ca446dcb42941784cfc452f94b40f4ec9a5ac7d"

FEATURES = v1.FEATURES
REGIME = v1.REGIME
DAILY = v1.DAILY
EXPECTED_INPUT_HASHES = {
    "features": "887ffd4d92fb992a718671f1b0d6eda28e4a6086ec948e27956ec3ceb3b5daea",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    "daily": "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9",
}

OUTPUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_structural_acceptance_v2/temporal_challenge_2022_2024"
)
MOTHER_CANDIDATES = OUTPUT / "mother_candidates.parquet"
ACCEPTANCE_LEDGER = OUTPUT / "acceptance_ledger.parquet"
OUTCOMES = OUTPUT / "accepted_outcomes.parquet"
MARKET_2024 = OUTPUT / "causal_market_regime_2024.parquet"
IDENTITY_AUDIT = OUTPUT / "pre_outcome_identity_audit.json"
RESULT = OUTPUT / "result.json"

SIGNAL_YEARS = (2022, 2023, 2024)
OUTCOME_END = pd.Timestamp("2025-03-31")
MARKET_RET60_MIN = 0.025
MARKET_RET60_MAX = 0.18
CONFIRMATION_WINDOW = 3
ENTRY_WINDOW = 3
HORIZON = 20
TARGET_GROSS_RETURN = 0.10
ROUND_TRIP_COST = 0.004


class ValidationError(RuntimeError):
    """Fail-closed V2 challenge error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(json_ready(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd"
    )
    os.replace(temporary, path)


def verify_inputs() -> dict[str, str]:
    paths = {"features": FEATURES, "regime": REGIME, "daily": DAILY}
    missing = [str(path) for path in [FREEZE, *paths.values()] if not path.is_file()]
    if missing:
        raise ValidationError(f"missing required input: {missing}")
    freeze_hash = sha256(FREEZE)
    if freeze_hash != EXPECTED_FREEZE_SHA256:
        raise ValidationError(f"V2 freeze hash changed: {freeze_hash}")
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": EXPECTED_INPUT_HASHES[name], "actual": value}
        for name, value in actual.items()
        if value != EXPECTED_INPUT_HASHES[name]
    }
    if drift:
        raise ValidationError(f"frozen input drift: {drift}")
    return {"freeze": freeze_hash, **actual}


def build_candidates(
    connection: duckdb.DuckDBPyConnection, market_2024: pd.DataFrame
) -> pd.DataFrame:
    connection.register("market_2024_frame", market_2024)
    historical = connection.execute(
        f"""
        SELECT
          f.event_id,f.symbol,f.sleeve,CAST(f.signal_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,
          f.invalid_step_cum AS signal_invalid_step_cum,
          f.platform_high,f.platform_low,f.platform_width,
          f.avg_to20,f.avg_to_old,f.turnover_contraction,
          f.open_gap,f.turnover_expansion,f.close_location,
          f.coord_close AS signal_coord_close,f.causal_industry,
          f.available_at,f.decision_at,f.hard_valid,f.current_valid,
          r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
          r.market_median_ret60,r.market_positive_ret60_share,
          'FROZEN_2022_2023_MOTHER_IDENTITY' AS candidate_source
        FROM read_parquet('{FEATURES.as_posix()}') f
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON CAST(f.signal_date AS DATE)=r.trade_date
        WHERE year(f.signal_date) IN (2022,2023)
          AND r.market_regime='BULL'
          AND r.market_median_ret60 BETWEEN {MARKET_RET60_MIN} AND {MARKET_RET60_MAX}
        ORDER BY f.signal_date,f.symbol,f.event_id
        """
    ).fetchdf()
    current = connection.execute(
        v1.feature_ctes()
        + f"""
        SELECT
          '{EXPERIMENT}|' || f.symbol || '|' || strftime(f.trade_date,'%Y-%m-%d') AS event_id,
          f.symbol,f.sleeve,CAST(f.trade_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,
          f.invalid_step_cum AS signal_invalid_step_cum,
          f.platform_high,f.platform_low,f.platform_width,
          f.avg_to20,f.avg_to_old,f.turnover_contraction,
          f.open_gap,f.turnover_expansion,f.close_location,
          f.coord_close AS signal_coord_close,f.causal_industry,
          f.available_at,f.decision_at,f.hard_valid,f.current_valid,
          m.market_regime,m.market_median_ret20,m.market_positive_ret20_share,
          m.market_median_ret60,m.market_positive_ret60_share,
          'EXACT_PIT_2024_MOTHER_REBUILD' AS candidate_source
        FROM featured f
        JOIN market_2024_frame m ON CAST(f.trade_date AS DATE)=m.trade_date
        WHERE year(f.trade_date)=2024
          AND {v1.mother_condition()}
          AND m.market_regime='BULL'
          AND m.market_median_ret60 BETWEEN {MARKET_RET60_MIN} AND {MARKET_RET60_MAX}
        ORDER BY f.trade_date,f.symbol
        """
    ).fetchdf()
    frame = pd.concat([historical, current], ignore_index=True)
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    frame = frame.sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if frame.event_id.duplicated().any():
        raise ValidationError("duplicate mother candidate event_id")
    if set(frame.signal_date.dt.year.unique()) - set(SIGNAL_YEARS):
        raise ValidationError("candidate outside challenge years")
    required = (
        "event_id",
        "symbol",
        "signal_date",
        "signal_cal_idx",
        "signal_invalid_step_cum",
        "platform_high",
        "platform_low",
        "market_median_ret60",
        "available_at",
        "decision_at",
        "hard_valid",
        "current_valid",
    )
    if frame[list(required)].isna().any().any():
        raise ValidationError("unknown required candidate feature or lineage")
    if frame.available_at.gt(frame.decision_at).any():
        raise ValidationError("candidate availability exceeds decision_at")
    if not frame.hard_valid.all() or not frame.current_valid.all():
        raise ValidationError("candidate contains non-hard-valid signal row")
    return frame


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


def replay_one(candidate: pd.Series, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.signal_invalid_step_cum)
    platform_high = float(candidate.platform_high)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "mother_signal_date": pd.Timestamp(candidate.signal_date),
        "mother_signal_cal_idx": signal_idx,
        "platform_high": platform_high,
        "platform_low": float(candidate.platform_low),
        "candidate_source": str(candidate.candidate_source),
    }
    if path.empty:
        return {**base, "accepted": False, "status": "NO_FUTURE_PATH"}
    confirm_pool = path.loc[path.cal_idx.le(signal_idx + CONFIRMATION_WINDOW)]
    if confirm_pool.empty:
        return {**base, "accepted": False, "status": "NO_CONFIRMATION_PATH"}
    if confirm_pool.invalid_step_cum.isna().any():
        return {**base, "accepted": False, "status": "UNKNOWN_CONFIRMATION_LINEAGE"}
    same_lineage = confirm_pool.loc[
        confirm_pool.invalid_step_cum.eq(lineage)
    ].sort_values("cal_idx")
    confirmation = next(
        (row for _, row in same_lineage.iterrows() if legal_observation(row)), None
    )
    if confirmation is None:
        changed = confirm_pool.invalid_step_cum.ne(lineage).any()
        status = "CONFIRMATION_LINEAGE_CHANGED" if changed else "NO_LEGAL_CONFIRMATION"
        return {**base, "accepted": False, "status": status}
    if not np.isfinite(float(confirmation.coord_close)):
        return {**base, "accepted": False, "status": "UNKNOWN_CONFIRMATION_CLOSE"}
    confirmation_idx = int(confirmation.cal_idx)
    confirmation_payload = {
        "confirmation_date": pd.Timestamp(confirmation.trade_date),
        "confirmation_cal_idx": confirmation_idx,
        "confirmation_coord_close": float(confirmation.coord_close),
        "confirmation_close_to_platform": float(confirmation.coord_close) / platform_high - 1.0,
    }
    if float(confirmation.coord_close) < platform_high:
        return {
            **base,
            **confirmation_payload,
            "accepted": False,
            "status": "REJECTED_FIRST_LEGAL_CLOSE_BELOW_PLATFORM",
        }

    accepted_payload = {**base, **confirmation_payload, "accepted": True}
    post_confirmation = path.loc[
        path.cal_idx.gt(confirmation_idx)
        & path.cal_idx.le(confirmation_idx + ENTRY_WINDOW)
    ].sort_values("cal_idx")
    if post_confirmation.invalid_step_cum.isna().any():
        return {**accepted_payload, "status": "UNKNOWN_ENTRY_LINEAGE"}
    entry_pool = post_confirmation.loc[post_confirmation.invalid_step_cum.eq(lineage)]
    entry = next((row for _, row in entry_pool.iterrows() if buyable_open(row)), None)
    if entry is None:
        changed = post_confirmation.invalid_step_cum.ne(lineage).any()
        status = "ENTRY_LINEAGE_CHANGED" if changed else "NO_LEGAL_ENTRY"
        return {**accepted_payload, "status": status}
    entry_idx = int(entry.cal_idx)
    if entry_idx <= confirmation_idx or confirmation_idx <= signal_idx:
        raise ValidationError("confirmation or entry chronology violated")
    entry_price = float(entry.coord_open)
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    target_price = entry_price * (1.0 + TARGET_GROSS_RETURN)
    pending_reason: str | None = None
    decision_idx: int | None = None
    exit_payload: dict[str, Any] | None = None
    censored = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].sort_values("cal_idx").iterrows():
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            censored = True
            break
        if pending_reason is not None and sellable_open(row):
            exit_payload = {
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": float(row.coord_open),
                "exit_reason": pending_reason,
                "exit_decision_cal_idx": decision_idx,
            }
            break
        if (
            legal_observation(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            exit_payload = {
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": target_price,
                "exit_reason": "TARGET_10",
                "exit_decision_cal_idx": entry_idx,
            }
            break
        if (
            legal_observation(row)
            and np.isfinite(float(row.coord_close))
            and int(row.cal_idx) >= entry_idx + HORIZON
        ):
            pending_reason = "H20_TIME_STOP"
            decision_idx = int(row.cal_idx)

    if censored:
        return {
            **accepted_payload,
            **entry_payload,
            "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
        }
    if exit_payload is None:
        return {
            **accepted_payload,
            **entry_payload,
            "status": "INCOMPLETE_BY_OUTCOME_END",
        }
    gross_return = float(exit_payload["exit_price"]) / entry_price - 1.0
    result = {
        **accepted_payload,
        **entry_payload,
        **exit_payload,
        "status": "COMPLETED",
        "holding_sessions": int(exit_payload["exit_cal_idx"]) - entry_idx,
        "gross_return": gross_return,
        "net_return": gross_return - ROUND_TRIP_COST,
    }
    if int(result["exit_cal_idx"]) <= entry_idx:
        raise ValidationError("entry-day or pre-entry exit")
    return result


def replay(
    connection: duckdb.DuckDBPyConnection, candidates: pd.DataFrame
) -> pd.DataFrame:
    connection.register(
        "validation_candidates",
        candidates[
            ["event_id", "symbol", "signal_cal_idx", "signal_invalid_step_cum"]
        ],
    )
    path = connection.execute(
        f"""
        SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.current_valid,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM validation_candidates c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
        WHERE d.trade_date<=DATE '{OUTCOME_END:%Y-%m-%d}'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetchdf()
    path["trade_date"] = pd.to_datetime(path.trade_date)
    groups = {event_id: part for event_id, part in path.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, groups.get(candidate.event_id, pd.DataFrame()))
        for _, candidate in candidates.iterrows()
    ]
    frame = pd.DataFrame(rows)
    for column in ("mother_signal_date", "confirmation_date", "entry_date", "exit_date"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame.sort_values(
        ["mother_signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    accepted = frame.loc[frame.accepted.fillna(False)].copy()
    completed = accepted.loc[accepted.status.eq("COMPLETED")].copy()
    returns = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": int(len(accepted)),
        "completed_trades": int(len(completed)),
        "completion_rate": None if accepted.empty else float(len(completed) / len(accepted)),
        "mean_net_return": None if completed.empty else float(returns.mean()),
        "median_net_return": None if completed.empty else float(returns.median()),
        "win_rate": None if completed.empty else float(returns.gt(0).mean()),
        "target_hit_rate": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_10").mean()),
        "severe_loss_10pct_rate": None
        if completed.empty
        else float(returns.le(-0.10).mean()),
        "mean_holding_sessions": None
        if completed.empty
        else float(completed.holding_sessions.mean()),
        "status_counts": accepted.status.value_counts(dropna=False).to_dict(),
    }


def concentration(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[
        frame.accepted.fillna(False) & frame.status.eq("COMPLETED")
    ].copy()
    if completed.empty:
        return {}
    summary = (
        completed.groupby("confirmation_date", as_index=False)
        .agg(signals=("event_id", "size"), mean_net_return=("net_return", "mean"))
        .sort_values(["signals", "confirmation_date"], ascending=[False, True])
        .reset_index(drop=True)
    )
    top = [set(summary.head(size).confirmation_date) for size in (1, 3, 5)]

    def without(excluded: set[pd.Timestamp]) -> float | None:
        kept = completed.loc[~completed.confirmation_date.isin(excluded)]
        return None if kept.empty else float(kept.net_return.mean())

    special_date = pd.Timestamp("2024-09-30")
    # Mother signals on 2024-09-27 confirm on the next market session.
    without_special = completed.loc[completed.confirmation_date.ne(special_date)]
    return {
        "distinct_confirmation_dates": int(len(summary)),
        "maximum_signals_on_one_date": int(summary.iloc[0].signals),
        "largest_confirmation_date": str(pd.Timestamp(summary.iloc[0].confirmation_date).date()),
        "top5_dates_signal_share": float(summary.head(5).signals.sum() / len(completed)),
        "confirmation_date_equal_weight_mean_net_return": float(summary.mean_net_return.mean()),
        "mean_net_return_excluding_largest_date": without(top[0]),
        "mean_net_return_excluding_top3_dates": without(top[1]),
        "mean_net_return_excluding_top5_dates": without(top[2]),
        "signals_confirmed_2024_09_30": int(completed.confirmation_date.eq(special_date).sum()),
        "mean_net_return_excluding_2024_09_30": None
        if without_special.empty
        else float(without_special.net_return.mean()),
        "top_dates": summary.head(10).to_dict("records"),
    }


def run() -> dict[str, Any]:
    input_hashes = verify_inputs()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=8")
    connection.execute("SET memory_limit='12GB'")
    audit = v1.identity_audit(connection)
    atomic_json(IDENTITY_AUDIT, audit)
    market_2024 = v1.build_2024_market(connection)
    candidates = build_candidates(connection, market_2024)
    ledger = replay(connection, candidates)
    connection.close()
    accepted = ledger.loc[ledger.accepted.fillna(False)].copy()
    atomic_parquet(market_2024, MARKET_2024)
    atomic_parquet(candidates, MOTHER_CANDIDATES)
    atomic_parquet(ledger, ACCEPTANCE_LEDGER)
    atomic_parquet(accepted, OUTCOMES)

    pooled = metrics(ledger)
    annual = {
        str(year): metrics(
            ledger.loc[ledger.mother_signal_date.dt.year.eq(year)].copy()
        )
        for year in SIGNAL_YEARS
    }
    mother_annual = {
        str(year): int(ledger.mother_signal_date.dt.year.eq(year).sum())
        for year in SIGNAL_YEARS
    }
    mean_signals_per_year = pooled["signals"] / len(SIGNAL_YEARS)
    result = {
        "experiment": EXPERIMENT,
        "status": "FROZEN_V2_TEMPORAL_CHALLENGE_COMPLETE",
        "evidence_label": (
            "post-observation temporal challenge; 2022-2024 were exposed by V1, "
            "but no V2 rule or threshold changed after this V2 freeze"
        ),
        "chronology": {
            "development_final_decision_end": "2021-12-31",
            "challenge_mother_signal_years": list(SIGNAL_YEARS),
            "outcome_tail_end": str(OUTCOME_END.date()),
            "v2_threshold_changes_after_freeze": False,
        },
        "mother_candidates": int(len(ledger)),
        "mother_candidates_by_year": mother_annual,
        "rejection_status_counts": ledger.loc[
            ~ledger.accepted.fillna(False), "status"
        ].value_counts(dropna=False).to_dict(),
        "pooled": pooled,
        "annual": annual,
        "mean_signals_per_year": mean_signals_per_year,
        "mean_completed_trades_per_year": pooled["completed_trades"] / len(SIGNAL_YEARS),
        "concentration": concentration(ledger),
        "user_gates": {
            "mean_signals_per_year_strictly_above_50": mean_signals_per_year > 50,
            "mean_net_return_at_least_4pct": pooled["mean_net_return"] is not None
            and pooled["mean_net_return"] >= 0.04,
            "mean_holding_sessions_strictly_below_15": pooled["mean_holding_sessions"]
            is not None
            and pooled["mean_holding_sessions"] < 15,
        },
        "pre_outcome_identity_audit": audit,
        "input_hashes_sha256": input_hashes,
    }
    atomic_json(RESULT, result)
    result["output_hashes_sha256"] = {
        "mother_candidates": sha256(MOTHER_CANDIDATES),
        "acceptance_ledger": sha256(ACCEPTANCE_LEDGER),
        "accepted_outcomes": sha256(OUTCOMES),
        "market_2024": sha256(MARKET_2024),
        "identity_audit": sha256(IDENTITY_AUDIT),
    }
    atomic_json(RESULT, result)
    return result


if __name__ == "__main__":
    print(json.dumps(json_ready(run()), ensure_ascii=False, indent=2))
