#!/usr/bin/env python3
"""Freeze then evaluate the 2022-2024 V17 dual-engine challenge."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_bull_quiet_inventory_three_session_acceptance_v2 as acceptdev  # noqa: E402
import run_ashare_quiet_inventory_fast_repricing_v1 as qfast  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-CAUSAL-BEAR-STRONG-BULL-DUAL-ENGINE-V17"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_challenge_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_challenge_report.md"

FEATURES = qfast.FEATURES
REGIME = qfast.REGIME
DAILY = qfast.DAILY
BEAR_ACCEPTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bear_fast_capitulation_active_demand_v10/stage_b/accepted_trades.parquet"
)
BEAR_SKIPPED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bear_fast_capitulation_active_demand_v10/stage_b/skipped_trades.parquet"
)
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_bear_strong_bull_dual_engine_v17/challenge_2022_2024"
)
MARKET_2024 = EXT_ROOT / "stage_a/causal_market_2024.parquet"
BULL_MOTHERS = EXT_ROOT / "stage_a/bull_mother_candidates_2022_2024.parquet"
BULL_ACCEPTED = EXT_ROOT / "stage_a/bull_accepted_candidates_2022_2024.parquet"
BEAR_RAW_2024 = EXT_ROOT / "stage_a/bear_raw_candidates_2024.parquet"
STAGE_A_FREEZE = EXT_ROOT / "stage_a/stage_a_freeze.json"
BULL_OUTCOMES = EXT_ROOT / "stage_b/bull_outcomes_2022_2024.parquet"
BEAR_RAW_OUTCOMES_2024 = EXT_ROOT / "stage_b/bear_raw_outcomes_2024.parquet"
BEAR_ACCEPTED_2024 = EXT_ROOT / "stage_b/bear_accepted_trades_2024.parquet"
COMBINED_TRADES = EXT_ROOT / "stage_b/combined_completed_trades.parquet"
MANIFEST = EXT_ROOT / "stage_b/manifest.json"

SIGNAL_END = pd.Timestamp("2024-12-31")
OUTCOME_END = pd.Timestamp("2025-03-31")
TARGET = 0.20
HORIZON = 60
COST = 0.004

EXPECTED_HASHES = {
    "contract": "5bcca65c12fb590137a45e454e309f79b70a1a79cfa3fff51124246d3a809b7c",
    "features": "887ffd4d92fb992a718671f1b0d6eda28e4a6086ec948e27956ec3ceb3b5daea",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    "bear_accepted": "d4e3c43e64ddae0b81c93b802ceb9cc7b674defd87d18ecb2c01d09b387b5835",
    "bear_skipped": "72446287ac47c3c983784a73fde486fbf87591b31364d8d366fdb097a33faded",
    "daily": "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9",
    "qfast_runner": "42be0aed77c63197320b127b483bd7bb0b9518c8dc999405be80ab1b84d45da5",
    "acceptance_runner": "c963f7ce1acaaf06f593f4860b28bc9159eb812320ef8b313c72403af9baedb3",
}


class ChallengeError(RuntimeError):
    """Fail closed when challenge identity or execution semantics drift."""


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


def verify_inputs() -> dict[str, str]:
    paths = {
        "contract": CONTRACT,
        "features": FEATURES,
        "regime": REGIME,
        "bear_accepted": BEAR_ACCEPTED,
        "bear_skipped": BEAR_SKIPPED,
        "daily": DAILY,
        "qfast_runner": Path(qfast.__file__),
        "acceptance_runner": Path(acceptdev.__file__),
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ChallengeError(f"missing frozen input: {missing}")
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": EXPECTED_HASHES[name], "actual": value}
        for name, value in actual.items()
        if value != EXPECTED_HASHES[name]
    }
    if drift:
        raise ChallengeError(f"frozen input drift: {drift}")
    return actual


def market_query(start: str, end: str) -> str:
    return qfast.feature_ctes() + f"""
    SELECT CAST(trade_date AS DATE) AS trade_date,
      median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
        AS market_median_ret20,
      avg((ret20>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL)
        AS market_positive_ret20_share,
      median(ret60) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
        AS market_median_ret60,
      avg((ret60>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret60 IS NOT NULL)
        AS market_positive_ret60_share,
      max(available_at) FILTER(WHERE current_valid AND NOT is_st) AS latest_source_timestamp
    FROM featured
    WHERE trade_date BETWEEN DATE '{start}' AND DATE '{end}'
    GROUP BY trade_date
    ORDER BY trade_date
    """


def label_market(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy().sort_values("trade_date", kind="mergesort")
    bull = (
        frame.market_median_ret20.gt(0)
        & frame.market_positive_ret20_share.gt(0.50)
        & frame.market_median_ret60.gt(0)
        & frame.market_positive_ret60_share.gt(0.50)
    )
    bear = (
        frame.market_median_ret20.le(0)
        & frame.market_positive_ret20_share.le(0.50)
        & frame.market_median_ret60.le(0)
        & frame.market_positive_ret60_share.le(0.50)
    )
    frame["market_regime"] = np.where(
        bull, "BULL", np.where(bear, "BEAR", "TRANSITION")
    )
    frame["strong_bull"] = (
        frame.market_regime.eq("BULL")
        & frame.market_median_ret60.ge(0.05)
        & frame.market_positive_ret60_share.ge(0.60)
    )
    frame["positive_ret20_share_lag5"] = frame.market_positive_ret20_share.shift(5)
    return frame


def build_market(connection: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict[str, Any]]:
    current = label_market(
        connection.execute(market_query("2023-01-01", "2024-12-31")).fetch_df()
    )
    rebuilt_2023 = current.loc[pd.to_datetime(current.trade_date).dt.year.eq(2023)].copy()
    frozen_2023 = connection.execute(
        f"""
        SELECT * FROM read_parquet('{REGIME.as_posix()}')
        WHERE year(trade_date)=2023 ORDER BY trade_date
        """
    ).fetch_df()
    frozen_2023["strong_bull"] = (
        frozen_2023.market_regime.eq("BULL")
        & frozen_2023.market_median_ret60.ge(0.05)
        & frozen_2023.market_positive_ret60_share.ge(0.60)
    )
    if len(rebuilt_2023) != len(frozen_2023):
        raise ChallengeError("2023 market-session reproduction count drift")
    audit = {
        "base_regime_mismatch_2023": int(
            rebuilt_2023.market_regime.reset_index(drop=True).ne(
                frozen_2023.market_regime.reset_index(drop=True)
            ).sum()
        ),
        "strong_bull_mismatch_2023": int(
            rebuilt_2023.strong_bull.reset_index(drop=True).ne(
                frozen_2023.strong_bull.reset_index(drop=True)
            ).sum()
        ),
        "max_abs_median_ret20_difference_2023": float(
            (
                rebuilt_2023.market_median_ret20.reset_index(drop=True)
                - frozen_2023.market_median_ret20.reset_index(drop=True)
            ).abs().max()
        ),
        "max_abs_median_ret60_difference_2023": float(
            (
                rebuilt_2023.market_median_ret60.reset_index(drop=True)
                - frozen_2023.market_median_ret60.reset_index(drop=True)
            ).abs().max()
        ),
    }
    if audit["base_regime_mismatch_2023"] or audit["strong_bull_mismatch_2023"]:
        raise ChallengeError(f"market-state reproduction failed: {audit}")
    market_2024 = current.loc[pd.to_datetime(current.trade_date).dt.year.eq(2024)].copy()
    if len(market_2024) != 242:
        raise ChallengeError(f"unexpected 2024 market sessions: {len(market_2024)}")
    return market_2024.reset_index(drop=True), audit


def build_bull_mothers(
    connection: duckdb.DuckDBPyConnection, market_2024: pd.DataFrame
) -> pd.DataFrame:
    connection.register("market_2024_frame", market_2024)
    historical = connection.execute(
        f"""
        SELECT f.event_id,f.symbol,f.sleeve,CAST(f.signal_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,f.invalid_step_cum AS signal_invalid_step_cum,
          f.platform_high,r.latest_source_timestamp AS state_source_timestamp,
          'FROZEN_2022_2023_MOTHER' AS candidate_source
        FROM read_parquet('{FEATURES.as_posix()}') f
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON CAST(f.signal_date AS DATE)=r.trade_date
        WHERE year(f.signal_date) IN (2022,2023)
          AND r.market_regime='BULL'
          AND r.market_median_ret60>=0.05
          AND r.market_positive_ret60_share>=0.60
        ORDER BY signal_date,f.symbol
        """
    ).fetch_df()
    current = connection.execute(
        qfast.feature_ctes()
        + f"""
        SELECT
          'QIG-' || strftime(f.trade_date,'%Y%m%d') || '-' || f.symbol AS event_id,
          f.symbol,f.sleeve,CAST(f.trade_date AS DATE) AS signal_date,
          f.cal_idx AS signal_cal_idx,f.invalid_step_cum AS signal_invalid_step_cum,
          f.platform_high,m.latest_source_timestamp AS state_source_timestamp,
          'EXACT_PIT_2024_MOTHER' AS candidate_source
        FROM featured f
        JOIN market_2024_frame m ON CAST(f.trade_date AS DATE)=m.trade_date
        WHERE year(f.trade_date)=2024
          AND {qfast.mother_condition()}
          AND m.strong_bull
        ORDER BY signal_date,f.symbol
        """
    ).fetch_df()
    frame = pd.concat([historical, current], ignore_index=True)
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    frame["state_source_timestamp"] = pd.to_datetime(frame.state_source_timestamp)
    frame = frame.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
    if frame.event_id.duplicated().any():
        raise ChallengeError("duplicate bull mother identity")
    if frame.state_source_timestamp.gt(frame.signal_date + pd.Timedelta(hours=15)).any():
        raise ChallengeError("bull state source after signal decision")
    return frame.reset_index(drop=True)


def freeze_acceptance_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    base = dict(candidate._asdict()) if hasattr(candidate, "_asdict") else vars(candidate)
    lineage = float(candidate.signal_invalid_step_cum)
    same_lineage = path.loc[path.invalid_step_cum.eq(lineage)]
    observations = [row for _, row in same_lineage.iterrows() if acceptdev.legal_observation(row)]
    if len(observations) < 3:
        return {**base, "acceptance_status": "NO_THIRD_OBSERVATION_BY_2024_END"}
    first_three = observations[:3]
    decision = first_three[2]
    accepted = float(decision.coord_close) >= float(candidate.platform_high)
    return {
        **base,
        "observation_1_date": pd.Timestamp(first_three[0].trade_date),
        "observation_2_date": pd.Timestamp(first_three[1].trade_date),
        "acceptance_decision_date": pd.Timestamp(decision.trade_date),
        "acceptance_decision_cal_idx": int(decision.cal_idx),
        "observation_3_close_to_platform": float(decision.coord_close)
        / float(candidate.platform_high)
        - 1.0,
        "accepted": accepted,
        "acceptance_status": "ACCEPTED" if accepted else "REJECTED_NOT_ACCEPTED",
    }


def freeze_bull_acceptance(
    connection: duckdb.DuckDBPyConnection, mothers: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    connection.register(
        "bull_mothers",
        mothers[["event_id", "symbol", "signal_cal_idx"]],
    )
    paths = connection.execute(
        f"""
        SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price
        FROM bull_mothers c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
        WHERE d.trade_date<=DATE '2024-12-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    ledger = pd.DataFrame(
        [
            freeze_acceptance_one(row, groups.get(str(row.event_id), pd.DataFrame()))
            for row in mothers.itertuples(index=False)
        ]
    )
    accepted = ledger.loc[ledger.acceptance_status.eq("ACCEPTED")].copy()
    if not accepted.empty and pd.to_datetime(accepted.acceptance_decision_date).gt(SIGNAL_END).any():
        raise ChallengeError("post-2024 acceptance decision entered freeze")
    return ledger, accepted.reset_index(drop=True)


def oai_query() -> str:
    excluded = qfast.quoted_industries()
    return f"""
    WITH source AS (
      SELECT * FROM read_parquet('{DAILY.as_posix()}')
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '2024-12-31'
        AND sleeve IN ('MAIN','CHINEXT')
        AND causal_industry NOT IN ({excluded})
    ), windows AS (
      SELECT *,
        lag(coord_close,20) OVER w AS lag20_close_x,
        lag(cal_idx,20) OVER w AS lag20_idx_x,
        lag(invalid_step_cum,20) OVER w AS lag20_invalid_x,
        lag(coord_close,10) OVER w AS lag10_close_x,
        max(coord_high) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) AS prior5_high_x,
        avg(turnover_fraction) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_to20_x,
        count(*) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_n_x,
        bool_and(history_valid) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_valid_x
      FROM source
      WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
    ), featured AS (
      SELECT *,
        coord_close/nullif(lag20_close_x,0)-1 AS ret20_x,
        coord_close/nullif(prior_coord_close,0)-1 AS step_return_x,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location_x,
        turnover_fraction/nullif(avg_to20_x,0) AS turnover_ratio_x,
        prior_coord_close/nullif(lag10_close_x,0)-1 AS prior10_return_x
      FROM windows
      WHERE year(trade_date) IN (2023,2024)
    )
    SELECT symbol,sleeve,CAST(trade_date AS DATE) AS signal_date,cal_idx,
      invalid_step_cum,available_at,decision_at,step_return_x,close_location_x,
      turnover_ratio_x,prior10_return_x
    FROM featured
    WHERE hard_valid AND history_valid AND current_valid
      AND current_day_data_tradable AND market_rule_valid
      AND corporate_action_valid AND NOT corporate_action_blocking AND NOT is_st
      AND prior20_n_x=20 AND prior20_valid_x
      AND cal_idx-lag20_idx_x=20 AND invalid_step_cum=lag20_invalid_x
      AND ret20_x<=-0.10 AND step_return_x>=0.05
      AND coord_close>prior5_high_x AND turnover_ratio_x>=1.0
      AND close_location_x>=0.70
      AND round(close*100)<round(up_limit_price*100)
    ORDER BY symbol,cal_idx
    """


def apply_cooldown(frame: pd.DataFrame) -> pd.DataFrame:
    keep: list[int] = []
    for _, part in frame.groupby("symbol", sort=False):
        last = -10**12
        for index, row in part.sort_values("cal_idx", kind="mergesort").iterrows():
            if int(row.cal_idx) - last > 20:
                keep.append(index)
                last = int(row.cal_idx)
    result = frame.loc[keep].copy()
    result["event_id"] = (
        "OAI-"
        + pd.to_datetime(result.signal_date).dt.strftime("%Y%m%d")
        + "-"
        + result.symbol.astype(str)
    )
    return result.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")


def build_bear_2024(
    connection: duckdb.DuckDBPyConnection, market_2024: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    high_recall = connection.execute(oai_query()).fetch_df()
    high_recall["signal_date"] = pd.to_datetime(high_recall.signal_date)
    base = apply_cooldown(high_recall)
    market_all = label_market(
        connection.execute(market_query("2023-01-01", "2024-12-31")).fetch_df()
    )
    base = base.merge(
        market_all[
            [
                "trade_date",
                "market_regime",
                "market_positive_ret20_share",
                "positive_ret20_share_lag5",
                "latest_source_timestamp",
            ]
        ],
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    )
    selected = base.loc[
        base.market_regime.eq("BEAR")
        & base.market_positive_ret20_share.gt(base.positive_ret20_share_lag5)
        & base.prior10_return_x.le(-0.08)
    ].copy()
    frozen_2023 = connection.execute(
        f"""
        SELECT event_id FROM read_parquet([
          '{BEAR_ACCEPTED.as_posix()}','{BEAR_SKIPPED.as_posix()}'
        ]) WHERE year(signal_date)=2023
        """
    ).fetch_df()
    rebuilt_ids = set(selected.loc[selected.signal_date.dt.year.eq(2023), "event_id"])
    frozen_ids = set(frozen_2023.event_id.astype(str))
    audit = {
        "rebuilt_v10_2023": int(len(rebuilt_ids)),
        "frozen_v10_2023": int(len(frozen_ids)),
        "missing_v10_2023": int(len(frozen_ids - rebuilt_ids)),
        "extra_v10_2023": int(len(rebuilt_ids - frozen_ids)),
    }
    if audit["missing_v10_2023"] or audit["extra_v10_2023"]:
        raise ChallengeError(f"bear detector reproduction failed: {audit}")
    current = selected.loc[selected.signal_date.dt.year.eq(2024)].copy()
    current = current.rename(
        columns={
            "cal_idx": "signal_cal_idx",
            "invalid_step_cum": "signal_invalid_step_cum",
            "close_location_x": "rank_close_location",
            "turnover_ratio_x": "rank_turnover_ratio",
            "latest_source_timestamp": "state_source_timestamp",
        }
    )
    if current.state_source_timestamp.gt(current.signal_date + pd.Timedelta(hours=15)).any():
        raise ChallengeError("bear market source after signal decision")
    return current.reset_index(drop=True), audit


def run_freeze() -> dict[str, Any]:
    source_hashes = verify_inputs()
    connection = duckdb.connect()
    market_2024, market_audit = build_market(connection)
    mothers = build_bull_mothers(connection, market_2024)
    acceptance_ledger, accepted_bull = freeze_bull_acceptance(connection, mothers)
    bear_2024, bear_audit = build_bear_2024(connection, market_2024)
    connection.close()
    write_parquet(market_2024, MARKET_2024)
    write_parquet(acceptance_ledger, BULL_MOTHERS)
    write_parquet(accepted_bull, BULL_ACCEPTED)
    write_parquet(bear_2024, BEAR_RAW_2024)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_2022_2024_IDENTITY_FREEZE",
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "market_reproduction_audit": market_audit,
        "bear_detector_reproduction_audit": bear_audit,
        "bull_mother_counts": {
            str(year): int(mothers.signal_date.dt.year.eq(year).sum())
            for year in (2022, 2023, 2024)
        },
        "bull_accepted_counts": {
            str(year): int(pd.to_datetime(accepted_bull.signal_date).dt.year.eq(year).sum())
            for year in (2022, 2023, 2024)
        },
        "bear_raw_2024": int(len(bear_2024)),
        "market_2024_sha256": sha256(MARKET_2024),
        "bull_mothers_sha256": sha256(BULL_MOTHERS),
        "bull_accepted_sha256": sha256(BULL_ACCEPTED),
        "bear_raw_2024_sha256": sha256(BEAR_RAW_2024),
        "max_bull_acceptance_decision": None
        if accepted_bull.empty
        else str(pd.to_datetime(accepted_bull.acceptance_decision_date).max().date()),
        "max_bear_signal_date": None
        if bear_2024.empty
        else str(pd.to_datetime(bear_2024.signal_date).max().date()),
        "return_or_exit_outcome_read_for_2024": "NO",
        "post_2024_acceptance_predictor_read": "NO",
        "2025_signal_read": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise ChallengeError("missing Stage-A identity freeze")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    current = {
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "market_2024_sha256": sha256(MARKET_2024),
        "bull_mothers_sha256": sha256(BULL_MOTHERS),
        "bull_accepted_sha256": sha256(BULL_ACCEPTED),
        "bear_raw_2024_sha256": sha256(BEAR_RAW_2024),
    }
    drift = {
        key: {"frozen": freeze.get(key), "current": value}
        for key, value in current.items()
        if freeze.get(key) != value
    }
    if drift:
        raise ChallengeError(f"Stage-A freeze drift: {drift}")
    verify_inputs()
    return freeze


def replay_after_decision(candidate: Any, path: pd.DataFrame, bear: bool) -> dict[str, Any]:
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.signal_invalid_step_cum)
    decision_idx = signal_idx if bear else int(candidate.acceptance_decision_cal_idx)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "decision_cal_idx": decision_idx,
        "engine": "BEAR_FAST_CAPITULATION_ACTIVE_DEMAND"
        if bear
        else "STRONG_BULL_QUIET_INVENTORY_ACCEPTANCE",
    }
    same_lineage = path.loc[path.invalid_step_cum.eq(lineage)]
    entry_pool = same_lineage.loc[
        same_lineage.cal_idx.gt(decision_idx)
        & same_lineage.cal_idx.le(decision_idx + 3)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if acceptdev.buyable_open(row)), None)
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * (1.0 + TARGET)
    pending = False
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    invalid = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending and acceptdev.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "H60_TIME_STOP"
            break
        if (
            acceptdev.legal_observation(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_20"
            break
        if acceptdev.legal_observation(row) and int(row.cal_idx) >= entry_idx + HORIZON:
            pending = True
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {**base, **entry_payload, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"}
    if exit_row is None:
        return {**base, **entry_payload, "status": "INCOMPLETE_BY_2025_03_31"}
    gross = float(exit_price) / entry_price - 1.0
    return {
        **base,
        **entry_payload,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - COST,
    }


def replay_candidates(candidates: pd.DataFrame, bear: bool) -> pd.DataFrame:
    connection = duckdb.connect()
    id_columns = ["event_id", "symbol", "signal_cal_idx"]
    connection.register("candidates", candidates[id_columns])
    paths = connection.execute(
        f"""
        SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price
        FROM candidates c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
        WHERE d.trade_date<=DATE '2025-03-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    records: list[dict[str, Any]] = []
    for candidate in candidates.itertuples(index=False):
        record = replay_after_decision(
            candidate, groups.get(str(candidate.event_id), pd.DataFrame()), bear
        )
        if bear:
            record["rank_close_location"] = float(candidate.rank_close_location)
            record["rank_turnover_ratio"] = float(candidate.rank_turnover_ratio)
        records.append(record)
    return pd.DataFrame(records)


def release_before_open(active: dict[str, Any], date: pd.Timestamp) -> None:
    for symbol, row in list(active.items()):
        exit_date = pd.Timestamp(row.exit_date)
        open_exit = str(row.exit_reason) != "TARGET_20"
        if exit_date < date or (exit_date == date and open_exit):
            del active[symbol]


def apply_bear_capacity(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    ordered = completed.sort_values(
        [
            "entry_date",
            "sleeve",
            "rank_close_location",
            "rank_turnover_ratio",
            "event_id",
        ],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    )
    active: dict[str, dict[str, Any]] = {"MAIN": {}, "CHINEXT": {}}
    accepted_ids: list[str] = []
    reasons: dict[str, str] = {}
    for date, date_rows in ordered.groupby("entry_date", sort=True):
        date = pd.Timestamp(date)
        for sleeve in active:
            release_before_open(active[sleeve], date)
        for sleeve, part in date_rows.groupby("sleeve", sort=True):
            accepted_today = 0
            for row in part.itertuples(index=False):
                reason = None
                if row.symbol in active[sleeve]:
                    reason = "ACTIVE_SYMBOL"
                elif len(active[sleeve]) >= 75:
                    reason = "K75_ACTIVE_CAP"
                elif accepted_today >= 20:
                    reason = "DAILY_ENTRY_CAP_20"
                if reason is not None:
                    reasons[str(row.event_id)] = reason
                    continue
                accepted_ids.append(str(row.event_id))
                active[sleeve][str(row.symbol)] = row
                accepted_today += 1
    accepted = ordered.loc[ordered.event_id.isin(accepted_ids)].copy()
    accepted["capacity_status"] = "ACCEPTED"
    skipped = frame.loc[~frame.event_id.isin(accepted_ids)].copy()
    skipped["capacity_status"] = "SKIPPED"
    skipped["skip_reason"] = skipped.event_id.map(reasons).fillna(skipped.status)
    return accepted, skipped


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame.net_return, errors="coerce")
    return {
        "trades": int(len(frame)),
        "mean_net": None if frame.empty else float(values.mean()),
        "median_net": None if frame.empty else float(values.median()),
        "win_rate": None if frame.empty else float(values.gt(0).mean()),
        "severe10": None if frame.empty else float(values.le(-0.10).mean()),
        "target_hit": None if frame.empty else float(frame.exit_reason.eq("TARGET_20").mean()),
        "mean_holding_sessions": None
        if frame.empty
        else float(frame.holding_sessions.mean()),
        "signal_dates": int(frame.signal_date.nunique()),
    }


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    frame = frame.copy()
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    yearly = {
        str(year): metrics(frame.loc[frame.signal_date.dt.year.eq(year)])
        for year in (2022, 2023, 2024)
    }
    engines = {
        str(engine): metrics(part)
        for engine, part in frame.groupby("engine", sort=True)
    }
    pooled = metrics(frame)
    gate = {
        "completed_per_year_gt_50": pooled["trades"] / 3.0 > 50,
        "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None
        and pooled["mean_net"] > 0.04,
        "pooled_median_net_positive": pooled["median_net"] is not None
        and pooled["median_net"] > 0,
        "every_calendar_year_mean_positive": all(
            item["trades"] > 0
            and item["mean_net"] is not None
            and item["mean_net"] > 0
            for item in yearly.values()
        ),
        "severe10_le_20pct": pooled["severe10"] is not None
        and pooled["severe10"] <= 0.20,
    }
    return {
        "pooled": pooled,
        "completed_per_year": pooled["trades"] / 3.0,
        "yearly": yearly,
        "engines": engines,
        "gate": gate,
    }


def render_report(result: dict[str, Any]) -> None:
    challenge = result["challenge_2022_2024"]
    lines = [
        f"# {EXPERIMENT} — 2022–2024 challenge",
        "",
        f"`{result['verdict']}`",
        "",
        "## Frozen strategy",
        "",
        "1. Causal BEAR: fast capitulation plus active-demand ignition and improving breadth.",
        "2. Causal STRONG_BULL: median stock ret60 >=5% and ret60 breadth >=60%, followed by quiet-inventory breakout and three-session platform acceptance.",
        "3. Weak BULL and TRANSITION: cash.",
        "4. Enter only at a later legal open; +20% target or H60 next legal open; no stop; 40 bp round trip.",
        "",
        "## Challenge result",
        "",
        f"Completed {challenge['pooled']['trades']} ({challenge['completed_per_year']:.1f}/year); mean {challenge['pooled']['mean_net']:.2%}; median {challenge['pooled']['median_net']:.2%}; win {challenge['pooled']['win_rate']:.2%}; severe10 {challenge['pooled']['severe10']:.2%}.",
        "",
        "|Year|Trades|Mean net|Median net|Win|Severe10|",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year in (2022, 2023, 2024):
        item = challenge["yearly"][str(year)]
        lines.append(
            f"|{year}|{item['trades']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|{item['win_rate']:.2%}|{item['severe10']:.2%}|"
        )
    lines += [
        "",
        "## Scientific status",
        "",
        "2022–2023 component outcomes were previously consumed and are robustness evidence only. 2024 identities were frozen before exit outcomes were read. No 2025 signal or predictor entered selection; 2025 rows only complete frozen 2024 trades.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_evaluate() -> dict[str, Any]:
    freeze = verify_stage_a()
    bull_candidates = duckdb.sql(
        f"SELECT * FROM read_parquet('{BULL_ACCEPTED.as_posix()}')"
    ).df()
    bull_outcomes = replay_candidates(bull_candidates, bear=False)
    write_parquet(bull_outcomes, BULL_OUTCOMES)

    bear_candidates = duckdb.sql(
        f"SELECT * FROM read_parquet('{BEAR_RAW_2024.as_posix()}')"
    ).df()
    bear_raw_outcomes = replay_candidates(bear_candidates, bear=True)
    bear_accepted_2024, _ = apply_bear_capacity(bear_raw_outcomes)
    write_parquet(bear_raw_outcomes, BEAR_RAW_OUTCOMES_2024)
    write_parquet(bear_accepted_2024, BEAR_ACCEPTED_2024)

    historical_bear = duckdb.sql(
        f"""
        SELECT event_id,symbol,sleeve,signal_date,entry_date,entry_cal_idx,
          entry_price,exit_date,exit_cal_idx,exit_price,exit_reason,
          holding_sessions,gross_return,net_return,
          'BEAR_FAST_CAPITULATION_ACTIVE_DEMAND' AS engine
        FROM read_parquet('{BEAR_ACCEPTED.as_posix()}')
        WHERE year(signal_date) IN (2022,2023) AND status='COMPLETED'
        """
    ).df()
    bull_completed = bull_outcomes.loc[bull_outcomes.status.eq("COMPLETED")].copy()
    bear_current = bear_accepted_2024.copy()
    common = [
        "event_id",
        "symbol",
        "sleeve",
        "signal_date",
        "entry_date",
        "entry_cal_idx",
        "entry_price",
        "exit_date",
        "exit_cal_idx",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "gross_return",
        "net_return",
        "engine",
    ]
    combined = pd.concat(
        [historical_bear[common], bear_current[common], bull_completed[common]],
        ignore_index=True,
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        combined[column] = pd.to_datetime(combined[column])
    combined = combined.sort_values(
        ["signal_date", "engine", "sleeve", "symbol", "event_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    if combined.event_id.duplicated().any():
        raise ChallengeError("duplicate combined trade identity")
    chronology = {
        "signal_bar_fill_count": int(
            combined.entry_date.le(combined.signal_date).sum()
        ),
        "exit_at_or_before_entry_count": int(
            combined.exit_cal_idx.le(combined.entry_cal_idx).sum()
        ),
        "post_2024_signal_count": int(combined.signal_date.dt.year.gt(2024).sum()),
    }
    if any(chronology.values()):
        raise ChallengeError(f"challenge chronology failed: {chronology}")
    write_parquet(combined, COMBINED_TRADES)
    challenge = summarize(combined)
    result = {
        "experiment": EXPERIMENT,
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "challenge_2022_2024": challenge,
        "chronology_audit": chronology,
        "bull_outcome_status_counts": bull_outcomes.status.value_counts().to_dict(),
        "bear_2024_raw_status_counts": bear_raw_outcomes.status.value_counts().to_dict(),
        "bear_2024_capacity_accepted": int(len(bear_accepted_2024)),
        "challenge_components": {
            "2022_2023": "PREVIOUSLY_CONSUMED_ROBUSTNESS",
            "2024": "OUTCOME_BLIND_FROZEN_IDENTITY_CHALLENGE",
        },
        "2025_signal_read": "NO",
        "2025_rows_role": "FROZEN_2024_TRADE_COMPLETION_ONLY",
        "bull_outcomes_sha256": sha256(BULL_OUTCOMES),
        "bear_raw_outcomes_2024_sha256": sha256(BEAR_RAW_OUTCOMES_2024),
        "bear_accepted_2024_sha256": sha256(BEAR_ACCEPTED_2024),
        "combined_trades_sha256": sha256(COMBINED_TRADES),
        "verdict": (
            "DUAL_ENGINE_PASSES_2022_2024_CHALLENGE_GATE"
            if all(challenge["gate"].values())
            else "DUAL_ENGINE_FAILS_2022_2024_CHALLENGE_GATE"
        ),
    }
    write_json(RESULT, result)
    render_report(result)
    manifest = {
        **result,
        "result_sha256": sha256(RESULT),
        "report_sha256": sha256(REPORT),
        "freeze": freeze,
    }
    write_json(MANIFEST, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("freeze", "evaluate"), required=True)
    args = parser.parse_args()
    result = run_freeze() if args.stage == "freeze" else run_evaluate()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))


if __name__ == "__main__":
    main()
