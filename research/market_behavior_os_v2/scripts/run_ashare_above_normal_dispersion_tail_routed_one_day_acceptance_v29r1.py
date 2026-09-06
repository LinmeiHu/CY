#!/usr/bin/env python3
"""Run the frozen post-chart V29R1 causal one-session acceptance test."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-ABOVE-NORMAL-DISPERSION-TAIL-ROUTED-ONE-DAY-ACCEPTANCE-V29R1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
PARENT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_above_normal_cross_sectional_dispersion_"
    "idiosyncratic_tail_mother_v29"
)
CANDIDATES = PARENT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = PARENT_ROOT / "stage_b/future_paths.parquet"
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_above_normal_dispersion_tail_routed_one_day_acceptance_v29r1"
)
DECISIONS = OUTPUT_ROOT / "outcome_blind_decisions.parquet"
OUTCOMES = OUTPUT_ROOT / "development_outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"
EXPECTED_HASHES = {
    FREEZE: "af7530b17fe9cf3031423d200b9a3edad538308c9794c4006835e6f028fb1a54",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    CANDIDATES: "5c5d70e96ae65552bc5f53a008c50fcba34392b252a666f43386b9d1b6bde6ef",
    PATHS: "68c735dc63ea4f4a6f0a22c7998f7059070f18ea1a39cf0ebf4aae6f8c9917c0",
}
YEARS = tuple(range(2014, 2021))
EXPECTED_EVENTS = 9368
ROUND_TRIP_COST = 0.004
MAX_PATH_DATE = pd.Timestamp("2021-06-30")


class ResearchError(RuntimeError):
    """Fail closed on identity, PIT timing, chronology, or execution drift."""


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
            raise ResearchError(f"input identity drift: {path}: {value} != {expected}")
    return actual


def connect() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return con


def write_parquet(con: duckdb.DuckDBPyConnection, frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con.register("write_frame", frame)
    con.execute(f"COPY write_frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.unregister("write_frame")


def route_lane(market_regime: str, market_median_ret20: float) -> str:
    if market_regime == "BULL":
        return "IDIOSYNCRATIC_UP_SHOCK"
    if market_regime == "BEAR":
        return "IDIOSYNCRATIC_DOWN_SHOCK"
    if market_regime != "TRANSITION" or not np.isfinite(market_median_ret20):
        raise ResearchError(f"invalid causal market state: {market_regime!r}")
    return "IDIOSYNCRATIC_UP_SHOCK" if market_median_ret20 > 0 else "IDIOSYNCRATIC_DOWN_SHOCK"


def build_outcome_blind_decisions(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = con.execute(
        f"""
        WITH candidates AS (
          SELECT * FROM read_parquet('{CANDIDATES.as_posix()}')
        ), stock_confirmation AS (
          SELECT c.event_id,p.trade_date AS confirmation_date,
            p.cal_idx AS confirmation_cal_idx,
            p.coord_close AS confirmation_coord_close,
            p.invalid_step_cum AS confirmation_invalid_step_cum,
            p.coordinate_factor AS confirmation_coordinate_factor,
            p.trade_status AS confirmation_trade_status,
            p.current_day_data_tradable AS confirmation_tradable,
            p.current_valid AS confirmation_current_valid,
            p.market_rule_valid AS confirmation_market_rule_valid,
            p.corporate_action_count AS confirmation_corporate_action_count,
            p.corporate_action_valid AS confirmation_corporate_action_valid,
            p.corporate_action_blocking AS confirmation_corporate_action_blocking,
            p.hard_valid AS confirmation_hard_valid,
            p.available_at AS confirmation_available_at,
            p.decision_at AS confirmation_decision_at
          FROM candidates c
          LEFT JOIN read_parquet('{PATHS.as_posix()}') p
            ON p.event_id=c.event_id AND p.cal_idx=c.signal_cal_idx+1
        ), needed_confirmation AS (
          SELECT DISTINCT signal_cal_idx+1 AS confirmation_cal_idx
          FROM candidates
        ), broad_confirmation AS (
          SELECT d.cal_idx AS confirmation_cal_idx,
            min(d.trade_date) AS market_confirmation_date,
            count(*) AS market_confirmation_member_n,
            count(DISTINCT d.causal_industry) AS market_confirmation_industry_n,
            median(d.step_return) AS market_confirmation_median_step_return,
            avg(CASE WHEN d.step_return>0 THEN 1.0 ELSE 0.0 END)
              AS market_confirmation_positive_share,
            max(d.available_at) AS market_confirmation_latest_available_at,
            min(d.decision_at) AS market_confirmation_earliest_decision_at
          FROM read_parquet('{DAILY.as_posix()}') d
          JOIN needed_confirmation n
            ON d.cal_idx=n.confirmation_cal_idx
          WHERE d.hard_valid AND d.current_valid
            AND d.current_day_data_tradable AND d.trade_status=1
            AND d.market_rule_valid AND d.corporate_action_valid
            AND NOT d.corporate_action_blocking
            AND coalesce(d.corporate_action_count,0)=0
            AND d.historical_identity_valid AND d.industry_valid
            AND d.causal_industry IS NOT NULL
            AND d.industry_snapshot_id IS NOT NULL
            AND NOT d.is_st AND d.available_at<=d.decision_at
            AND d.coord_open>0 AND d.coord_high>=d.coord_low
            AND d.coord_close>0 AND d.amount>0 AND d.step_return IS NOT NULL
          GROUP BY d.cal_idx
          HAVING count(*)>=500
        )
        SELECT c.event_id,c.direction_lane,c.symbol,c.sleeve,c.causal_industry,
          c.signal_date,c.signal_cal_idx,c.decision_at AS signal_decision_at,
          c.coord_close AS signal_coord_close,c.invalid_step_cum AS signal_lineage,
          r.market_regime,r.market_median_ret20,r.market_median_ret60,
          r.latest_source_timestamp AS regime_latest_source_timestamp,
          s.confirmation_date,s.confirmation_cal_idx,s.confirmation_coord_close,
          s.confirmation_invalid_step_cum,s.confirmation_coordinate_factor,
          s.confirmation_trade_status,s.confirmation_tradable,
          s.confirmation_current_valid,s.confirmation_market_rule_valid,
          s.confirmation_corporate_action_count,
          s.confirmation_corporate_action_valid,
          s.confirmation_corporate_action_blocking,s.confirmation_hard_valid,
          s.confirmation_available_at,s.confirmation_decision_at,
          b.market_confirmation_date,b.market_confirmation_member_n,
          b.market_confirmation_industry_n,
          b.market_confirmation_median_step_return,
          b.market_confirmation_positive_share,
          b.market_confirmation_latest_available_at,
          b.market_confirmation_earliest_decision_at
        FROM candidates c
        LEFT JOIN stock_confirmation s USING(event_id)
        LEFT JOIN broad_confirmation b USING(confirmation_cal_idx)
        LEFT JOIN read_parquet('{REGIME.as_posix()}') r
          ON r.trade_date=c.signal_date
        ORDER BY c.signal_cal_idx,c.direction_lane,c.causal_industry,c.symbol
        """
    ).fetch_df()
    for column in (
        "signal_date",
        "signal_decision_at",
        "regime_latest_source_timestamp",
        "confirmation_date",
        "confirmation_available_at",
        "confirmation_decision_at",
        "market_confirmation_date",
        "market_confirmation_latest_available_at",
        "market_confirmation_earliest_decision_at",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if len(frame) != EXPECTED_EVENTS or frame.event_id.duplicated().any():
        raise ResearchError("candidate or exact-confirmation identity drift")
    if frame.signal_date.dt.year.gt(2020).any():
        raise ResearchError("post-2020 mother signal entered development decisions")
    if frame.regime_latest_source_timestamp.gt(frame.signal_decision_at).any():
        raise ResearchError("causal market regime arrived after signal decision")

    frame["routed_lane"] = [
        route_lane(str(regime), float(ret20))
        for regime, ret20 in zip(frame.market_regime, frame.market_median_ret20, strict=True)
    ]
    reasons: list[str] = []
    accepted: list[bool] = []
    for row in frame.itertuples(index=False):
        reason = "ACCEPTED"
        if row.direction_lane != row.routed_lane:
            reason = "REJECTED_CAUSAL_MARKET_ROUTE"
        elif pd.isna(row.confirmation_cal_idx):
            reason = "REJECTED_NO_EXACT_CONFIRMATION_SESSION"
        elif int(row.confirmation_cal_idx) != int(row.signal_cal_idx) + 1:
            reason = "REJECTED_CONFIRMATION_NOT_EXACT_NEXT_SESSION"
        elif pd.isna(row.confirmation_invalid_step_cum) or float(
            row.confirmation_invalid_step_cum
        ) != float(row.signal_lineage):
            reason = "REJECTED_CONFIRMATION_LINEAGE_CHANGE"
        elif not (
            int(row.confirmation_trade_status) == 1
            and bool(row.confirmation_tradable)
            and bool(row.confirmation_current_valid)
            and bool(row.confirmation_market_rule_valid)
            and int(row.confirmation_corporate_action_count) == 0
            and bool(row.confirmation_corporate_action_valid)
            and not bool(row.confirmation_corporate_action_blocking)
            and bool(row.confirmation_hard_valid)
            and np.isfinite(float(row.confirmation_coordinate_factor))
            and float(row.confirmation_coordinate_factor) > 0
            and np.isfinite(float(row.confirmation_coord_close))
            and float(row.confirmation_coord_close) > 0
            and pd.notna(row.confirmation_available_at)
            and pd.notna(row.confirmation_decision_at)
            and row.confirmation_available_at <= row.confirmation_decision_at
        ):
            reason = "REJECTED_INVALID_STOCK_CONFIRMATION"
        elif float(row.confirmation_coord_close) < float(row.signal_coord_close):
            reason = "REJECTED_STOCK_NOT_ACCEPTED"
        elif pd.isna(row.market_confirmation_member_n):
            reason = "REJECTED_NO_VALID_BROAD_MARKET_CONFIRMATION"
        elif (
            int(row.market_confirmation_member_n) < 500
            or not np.isfinite(float(row.market_confirmation_median_step_return))
            or float(row.market_confirmation_median_step_return) <= 0
        ):
            reason = "REJECTED_BROAD_MARKET_NOT_ACCEPTED"
        elif (
            pd.isna(row.market_confirmation_latest_available_at)
            or pd.isna(row.market_confirmation_earliest_decision_at)
            or row.market_confirmation_latest_available_at
            > row.market_confirmation_earliest_decision_at
        ):
            reason = "REJECTED_BROAD_MARKET_TIMING"
        elif pd.Timestamp(row.confirmation_date) != pd.Timestamp(row.market_confirmation_date):
            reason = "REJECTED_CONFIRMATION_DATE_MISMATCH"
        reasons.append(reason)
        accepted.append(reason == "ACCEPTED")
    frame["decision_status"] = reasons
    frame["accepted"] = accepted
    return frame


def opportunity_summary(frame: pd.DataFrame) -> tuple[dict[str, Any], bool]:
    annual: dict[str, Any] = {}
    passed = True
    for year in YEARS:
        part = frame.loc[frame.signal_date.dt.year.eq(year)]
        selected = part.loc[part.accepted]
        annual[str(year)] = {
            "mother_events": len(part),
            "accepted_signals": len(selected),
            "decision_dates": int(selected.signal_date.nunique()),
            "symbols": int(selected.symbol.nunique()),
            "industries": int(selected.causal_industry.nunique()),
            "up": int(selected.direction_lane.eq("IDIOSYNCRATIC_UP_SHOCK").sum()),
            "down": int(selected.direction_lane.eq("IDIOSYNCRATIC_DOWN_SHOCK").sum()),
        }
        passed &= len(selected) > 50
    return annual, bool(passed)


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
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid)
        and bool(row.market_rule_valid)
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and int(row.corporate_action_count) == 0
        and bool(row.hard_valid)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and float(row.coordinate_factor) > 0
        and pd.notna(row.available_at)
        and pd.notna(row.decision_at)
        and row.available_at <= row.decision_at
    )


def buyable(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    return bool(
        legal(row)
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    common = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "direction_lane": str(candidate.direction_lane),
        "routed_lane": str(candidate.routed_lane),
        "market_regime": str(candidate.market_regime),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "confirmation_date": pd.Timestamp(candidate.confirmation_date),
        "confirmation_cal_idx": int(candidate.confirmation_cal_idx),
        "stock_confirmation_return": float(candidate.confirmation_coord_close)
        / float(candidate.signal_coord_close)
        - 1,
        "market_confirmation_median_step_return": float(
            candidate.market_confirmation_median_step_return
        ),
        "target_return": 0.10,
        "horizon_sessions": 20,
    }
    lineage = float(candidate.signal_lineage)
    entry_pool = path.loc[
        path.cal_idx.gt(candidate.confirmation_cal_idx)
        & path.cal_idx.le(candidate.signal_cal_idx + 4)
    ]
    entry = next(
        (
            row
            for row in entry_pool.itertuples(index=False)
            if np.isfinite(float(row.invalid_step_cum))
            and float(row.invalid_step_cum) == lineage
            and buyable(row)
        ),
        None,
    )
    if entry is None:
        return {**common, "status": "NO_LEGAL_ENTRY_AFTER_CONFIRMATION"}

    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target_price = entry_price * 1.10
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "entry_price": entry_price,
            }
        if (
            legal(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            gross = target_price / entry_price - 1
            return {
                **common,
                "status": "COMPLETED",
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "entry_price": entry_price,
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": target_price,
                "exit_reason": "TARGET_10",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - ROUND_TRIP_COST,
            }
        if int(row.cal_idx) > entry_idx + 20 and sellable_open(row):
            exit_price = float(row.coord_open)
            gross = exit_price / entry_price - 1
            return {
                **common,
                "status": "COMPLETED",
                "entry_date": pd.Timestamp(entry.trade_date),
                "entry_cal_idx": entry_idx,
                "entry_price": entry_price,
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": exit_price,
                "exit_reason": "H20_TIME_STOP",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - ROUND_TRIP_COST,
            }
    return {
        **common,
        "status": "INCOMPLETE_PATH",
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }


def load_replay_paths(con: duckdb.DuckDBPyConnection, accepted: pd.DataFrame) -> pd.DataFrame:
    con.register("accepted_events", accepted[["event_id"]])
    frame = con.execute(
        f"""
        SELECT p.*
        FROM read_parquet('{PATHS.as_posix()}') p
        JOIN accepted_events a USING(event_id)
        ORDER BY p.event_id,p.cal_idx
        """
    ).fetch_df()
    con.unregister("accepted_events")
    for column in ("trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    if not frame.empty and frame.trade_date.max() > MAX_PATH_DATE:
        raise ResearchError("development replay crossed maximum path date")
    return frame


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")]
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "accepted_signals": len(frame),
        "completed": len(completed),
        "decision_dates": int(completed.signal_date.nunique()),
        "symbols": int(completed.symbol.nunique()),
        "industries": int(completed.causal_industry.nunique()),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "positive_rate": None if completed.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if completed.empty else float(values.ge(0.04).mean()),
        "severe10": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit_rate": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_10").mean()),
        "mean_holding_sessions": None
        if completed.empty
        else float(completed.holding_sessions.mean()),
    }


def write_result(payload: dict[str, Any]) -> dict[str, Any]:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return {**payload, "result_sha256": sha256(RESULT)}


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    con = connect()
    decisions = build_outcome_blind_decisions(con)
    write_parquet(con, decisions, DECISIONS)
    annual_opportunity, opportunity_gate = opportunity_summary(decisions)
    status_counts = {
        str(key): int(value)
        for key, value in decisions.decision_status.value_counts(dropna=False).sort_index().items()
    }
    base_payload: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_CHART_DERIVED_DEVELOPMENT_TEST",
        "freeze_sha256": source_hashes[str(FREEZE)],
        "source_hashes": source_hashes,
        "outcome_blind_decision_sha256": sha256(DECISIONS),
        "outcome_blind_annual": annual_opportunity,
        "outcome_blind_status_counts": status_counts,
        "outcome_blind_opportunity_gate_passed": opportunity_gate,
        "post_2020_signal_outcome_read": False,
        "2022_2024_outcome_read": "NO",
        "maximum_evaluation_path_date": str(MAX_PATH_DATE.date()),
        "independent_confirmation": False,
    }
    if not opportunity_gate:
        con.close()
        return write_result(
            {
                **base_payload,
                "development_outcomes_read_for_v29r1": False,
                "later_2022_2024_open_authorized": False,
                "verdict": "CLOSE_OUTCOME_BLIND_ANNUAL_COUNT_GATE_FAILED",
            }
        )

    accepted = decisions.loc[decisions.accepted].copy()
    paths = load_replay_paths(con, accepted)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, groups.get(str(candidate.event_id), paths.iloc[0:0]))
        for candidate in accepted.itertuples(index=False)
    ]
    outcomes = pd.DataFrame(rows)
    for column in ("signal_date", "confirmation_date", "entry_date", "exit_date"):
        if column not in outcomes:
            outcomes[column] = pd.NaT
        outcomes[column] = pd.to_datetime(outcomes[column])
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "entry_at_or_before_signal": int(
            completed.entry_cal_idx.le(completed.signal_cal_idx).sum()
        ),
        "entry_at_or_before_confirmation": int(
            completed.entry_cal_idx.le(completed.confirmation_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(completed.exit_cal_idx.le(completed.entry_cal_idx).sum()),
        "post_2020_signals": int(outcomes.signal_date.dt.year.gt(2020).sum()),
        "post_max_path_exits": int(completed.exit_date.gt(MAX_PATH_DATE).sum()),
        "nonfinite_completed_return": int(
            (~np.isfinite(pd.to_numeric(completed.net_return, errors="coerce"))).sum()
        ),
    }
    if any(chronology.values()):
        raise ResearchError(f"development chronology audit failed: {chronology}")
    write_parquet(con, outcomes, OUTCOMES)
    con.close()

    annual = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)]) for year in YEARS
    }
    annual_conditions = {
        str(year): {
            "completed_gt_50": annual[str(year)]["completed"] > 50,
            "mean_net_gt_4pct": annual[str(year)]["mean_net"] is not None
            and annual[str(year)]["mean_net"] > 0.04,
        }
        for year in YEARS
    }
    development_gate = all(all(condition.values()) for condition in annual_conditions.values())
    payload = {
        **base_payload,
        "development_outcomes_read_for_v29r1": True,
        "development_outcomes_sha256": sha256(OUTCOMES),
        "development_overall": metrics(outcomes),
        "development_annual": annual,
        "development_by_lane": {
            str(lane): metrics(part) for lane, part in outcomes.groupby("direction_lane", sort=True)
        },
        "development_by_signal_regime": {
            str(regime): metrics(part)
            for regime, part in outcomes.groupby("market_regime", sort=True)
        },
        "development_gate_by_year": annual_conditions,
        "strict_annual_development_gate_passed": development_gate,
        "chronology_audit": chronology,
        "later_2022_2024_open_authorized": development_gate,
        "2022_2024_outcome_read": "NO",
        "verdict": (
            "V29R1_STRICT_ANNUAL_GATE_PASS"
            if development_gate
            else "V29R1_STRICT_ANNUAL_GATE_FAIL_CLOSE_NO_RESCUE"
        ),
        "runner_sha256": sha256(Path(__file__)),
    }
    return write_result(payload)


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
