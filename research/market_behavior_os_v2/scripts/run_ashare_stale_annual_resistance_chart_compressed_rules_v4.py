#!/usr/bin/env python3
"""Replay the frozen chart-compressed stale-resistance rules on 2014-2020."""

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


EXPERIMENT = "ASHARE-STALE-ANNUAL-RESISTANCE-CHART-COMPRESSED-RULES-V4"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "b2c6b725a35a2714c299756de26227a57a75fc86f4142fd6737a3a63d99960e9"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
SOURCE_ROOT = DATA_ROOT / "ashare_stale_annual_resistance_absorption_breakout_v1"
CANDIDATES = SOURCE_ROOT / "stage_a/candidates_frozen.parquet"
DISCOVERY_OUTCOMES = SOURCE_ROOT / "stage_b/development/discovery_outcomes.parquet"
CONFIRMATION_OUTCOMES = SOURCE_ROOT / "stage_b/development/confirmation_outcomes.parquet"
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
OUTPUT_ROOT = (
    DATA_ROOT
    / "ashare_stale_annual_resistance_chart_compressed_rules_v4"
    / "development_2014_2020"
)
REPLAY = OUTPUT_ROOT / "event_replay.parquet"
ANNUAL = OUTPUT_ROOT / "annual_metrics.csv"
RESULT = OUTPUT_ROOT / "result.json"

EXPECTED_HASHES = {
    "candidates": "4518bd47845d068d36f85016786d3743276364410a5bec6c434f10c82b27e455",
    "discovery_outcomes": "8e86ef65b0f0f6bfaf82e5424165dfd4c5d6768a67fe7f6a584bd09ba6d0c711",
    "confirmation_outcomes": "f05ac84340f65839ae1ef8f45b4b2a861644e5e0da067d8c0c5fd281ae587981",
    "daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
EXPECTED_ANNUAL = {2014: 237, 2015: 172, 2016: 55, 2017: 134, 2018: 72, 2019: 157, 2020: 220}
TARGET = 0.20
HORIZON = 60
COST = 0.004


class ResearchError(RuntimeError):
    """Fail closed on identity, chronology, execution, or lineage drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def verify_inputs() -> dict[str, str]:
    paths = {
        "candidates": CANDIDATES,
        "discovery_outcomes": DISCOVERY_OUTCOMES,
        "confirmation_outcomes": CONFIRMATION_OUTCOMES,
        "daily": DAILY,
        "regime": REGIME,
    }
    if not FREEZE.is_file() or sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("frozen chart-rule specification drift")
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ResearchError(f"missing frozen input: {missing}")
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": EXPECTED_HASHES[name], "actual": digest}
        for name, digest in actual.items()
        if EXPECTED_HASHES[name] != digest
    }
    if drift:
        raise ResearchError(f"frozen input identity drift: {drift}")
    return actual


def legal_observation(row: Any) -> bool:
    fields = (
        "trade_status",
        "current_day_data_tradable",
        "current_valid",
        "market_rule_valid",
        "corporate_action_valid",
        "corporate_action_blocking",
        "hard_valid",
    )
    if any(pd.isna(getattr(row, field)) for field in fields):
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


def buyable_open(row: Any) -> bool:
    values = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    return bool(
        legal_observation(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        legal_observation(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    connection = duckdb.connect()
    candidates = connection.execute(
        f"""
        SELECT c.*,r.market_regime,r.latest_source_timestamp AS market_latest_source_timestamp
        FROM read_parquet('{CANDIDATES.as_posix()}') c
        JOIN read_parquet('{REGIME.as_posix()}') r ON c.signal_date=r.trade_date
        WHERE c.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY c.signal_date,c.sleeve,c.symbol,c.event_id
        """
    ).fetch_df()
    baseline = connection.execute(
        f"""
        SELECT * FROM (
          SELECT * FROM read_parquet('{DISCOVERY_OUTCOMES.as_posix()}')
          UNION ALL BY NAME
          SELECT * FROM read_parquet('{CONFIRMATION_OUTCOMES.as_posix()}')
        )
        WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY signal_date,symbol,event_id
        """
    ).fetch_df()
    connection.register(
        "candidate_ids",
        candidates[["event_id", "symbol", "cal_idx"]].rename(columns={"cal_idx": "signal_cal_idx"}),
    )
    paths = connection.execute(
        f"""
        SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price,
          d.available_at,d.decision_at
        FROM candidate_ids c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    for column in ("signal_date", "available_at", "decision_at", "market_latest_source_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("signal_date", "entry_date", "exit_date"):
        baseline[column] = pd.to_datetime(baseline[column])
    for column in ("trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    annual = candidates.groupby(candidates.signal_date.dt.year).size().to_dict()
    if annual != EXPECTED_ANNUAL:
        raise ResearchError(f"candidate count drift: {annual}")
    if candidates.event_id.duplicated().any() or baseline.event_id.duplicated().any():
        raise ResearchError("duplicate event identity")
    if set(candidates.event_id) != set(baseline.event_id):
        raise ResearchError("candidate and source-outcome identity differ")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("candidate information is later than decision_at")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("causal market state uses information after decision_at")
    if not candidates.market_regime.isin(["BULL", "BEAR", "TRANSITION"]).all():
        raise ResearchError("missing or unknown causal market state")
    if paths.available_at.dt.date.gt(paths.trade_date.dt.date).any():
        raise ResearchError("daily row is unavailable on its trade date")
    if paths.trade_date.max() >= pd.Timestamp("2022-01-01"):
        raise ResearchError("replay opened 2022 or later")
    return candidates, baseline, paths


def replay_one(candidate: Any, path: pd.DataFrame, structural_exit: bool) -> dict[str, Any]:
    signal_idx = int(candidate.cal_idx)
    lineage = float(candidate.invalid_step_cum)
    stale_high = float(candidate.prior250_peak_high)
    state = str(candidate.market_regime)
    confirmation_closes = 3 if state == "BULL" else 2
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_year": int(pd.Timestamp(candidate.signal_date).year),
        "signal_cal_idx": signal_idx,
        "market_regime": state,
        "market_state_source_timestamp": pd.Timestamp(candidate.market_latest_source_timestamp),
        "stale_high": stale_high,
        "confirmation_closes": confirmation_closes,
        "structural_exit_enabled": structural_exit,
    }
    same_lineage = path.loc[path.invalid_step_cum.eq(lineage)]
    entry_pool = same_lineage.loc[
        same_lineage.cal_idx.gt(signal_idx) & same_lineage.cal_idx.le(signal_idx + 3)
    ]
    entry = next((row for row in entry_pool.itertuples(index=False) if buyable_open(row)), None)
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}

    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * (1.0 + TARGET)
    pending_reason: str | None = None
    exit_row: Any | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    below_count = 0
    failure_decision_date = pd.NaT
    failure_decision_idx = math.nan
    max_below_count = 0
    invalid = False

    for row in path.loc[path.cal_idx.ge(entry_idx)].itertuples(index=False):
        row_idx = int(row.cal_idx)
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if row_idx > entry_idx and pending_reason is not None and sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = pending_reason
            break
        if (
            row_idx > entry_idx
            and legal_observation(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_20"
            break
        if legal_observation(row):
            if structural_exit:
                if float(row.coord_close) < stale_high:
                    below_count += 1
                    max_below_count = max(max_below_count, below_count)
                else:
                    below_count = 0
                if below_count >= confirmation_closes and pending_reason is None:
                    pending_reason = f"STALE_HIGH_FAILURE_{confirmation_closes}C"
                    failure_decision_date = pd.Timestamp(row.trade_date)
                    failure_decision_idx = row_idx
            if row_idx >= entry_idx + HORIZON and pending_reason is None:
                pending_reason = "H60_TIME_STOP"

    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        "failure_decision_date": failure_decision_date,
        "failure_decision_cal_idx": failure_decision_idx,
        "max_consecutive_closes_below_stale_high": max_below_count,
    }
    if invalid:
        return {**base, **entry_payload, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"}
    if exit_row is None:
        return {**base, **entry_payload, "status": "INCOMPLETE_BY_2021_END"}
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


def replay(candidates: pd.DataFrame, paths: pd.DataFrame, structural_exit: bool) -> pd.DataFrame:
    path_map = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, path_map.get(str(candidate.event_id), pd.DataFrame()), structural_exit)
        for candidate in candidates.itertuples(index=False)
    ]
    return pd.DataFrame(rows).sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def validate_baseline(rebuilt: pd.DataFrame, frozen: pd.DataFrame) -> dict[str, Any]:
    frozen_complete = frozen.loc[frozen.status.eq("COMPLETED")].set_index("event_id")
    rebuilt_complete = rebuilt.loc[rebuilt.status.eq("COMPLETED")].set_index("event_id")
    missing = set(frozen_complete.index) - set(rebuilt_complete.index)
    recovered = set(rebuilt_complete.index) - set(frozen_complete.index)
    expected_recovered = {"601928.SH|2018-12-26|SAR1"}
    if missing or recovered != expected_recovered:
        raise ResearchError(
            "baseline completed identity mismatch: "
            f"missing={sorted(missing)}, recovered={sorted(recovered)}"
        )
    recovered_source = frozen.loc[frozen.event_id.isin(recovered), ["event_id", "status"]]
    if recovered_source.status.tolist() != ["INCOMPLETE_BY_2021_END"]:
        raise ResearchError(f"unexpected frozen status for recovered path: {recovered_source.to_dict('records')}")
    joined = frozen_complete[["entry_date", "entry_price", "exit_date", "exit_price", "net_return"]].join(
        rebuilt_complete[["entry_date", "entry_price", "exit_date", "exit_price", "net_return"]],
        lsuffix="_frozen",
        rsuffix="_rebuilt",
    )
    date_bad = (
        joined.entry_date_frozen.ne(joined.entry_date_rebuilt)
        | joined.exit_date_frozen.ne(joined.exit_date_rebuilt)
    )
    numeric_bad = np.zeros(len(joined), dtype=bool)
    for column in ("entry_price", "exit_price", "net_return"):
        numeric_bad |= ~np.isclose(
            joined[f"{column}_frozen"].astype(float),
            joined[f"{column}_rebuilt"].astype(float),
            rtol=0.0,
            atol=1e-10,
        )
    if date_bad.any() or numeric_bad.any():
        examples = joined.loc[date_bad | numeric_bad].head(5).to_dict("index")
        raise ResearchError(f"baseline execution reproduction mismatch: {examples}")
    return {
        "frozen_completed": int(len(frozen_complete)),
        "rebuilt_completed": int(len(rebuilt_complete)),
        "recovered_legacy_incomplete_event_ids": sorted(recovered),
        "recovered_legacy_incomplete_reason": (
            "The registered daily path contains the exact legal H60 exit on 2019-04-02; "
            "all 1024 originally completed trades reproduce bit-for-bit."
        ),
        "date_mismatches": int(date_bad.sum()),
        "numeric_mismatches": int(numeric_bad.sum()),
    }


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    returns = complete.net_return.astype(float)
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "decision_dates": int(frame.signal_date.nunique()),
        "securities": int(frame.symbol.nunique()),
        "mean_net": None if complete.empty else float(returns.mean()),
        "median_net": None if complete.empty else float(returns.median()),
        "positive_rate": None if complete.empty else float(returns.gt(0).mean()),
        "ge_4pct_rate": None if complete.empty else float(returns.ge(0.04).mean()),
        "severe_loss_rate": None if complete.empty else float(returns.le(-0.10).mean()),
        "mean_holding_sessions": None if complete.empty else float(complete.holding_sessions.mean()),
        "exit_reasons": complete.exit_reason.value_counts().sort_index().to_dict(),
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates, frozen_baseline, paths = load_inputs()
    rebuilt_baseline = replay(candidates, paths, structural_exit=False)
    reproduction = validate_baseline(rebuilt_baseline, frozen_baseline)
    routed = replay(candidates, paths, structural_exit=True)
    write_parquet(routed, REPLAY)

    annual_rows: list[dict[str, Any]] = []
    for year in EXPECTED_ANNUAL:
        base_metrics = metrics(rebuilt_baseline.loc[rebuilt_baseline.signal_year.eq(year)])
        routed_metrics = metrics(routed.loc[routed.signal_year.eq(year)])
        annual_rows.append(
            {
                "year": year,
                **{f"baseline_{key}": value for key, value in base_metrics.items() if key != "exit_reasons"},
                **{f"routed_{key}": value for key, value in routed_metrics.items() if key != "exit_reasons"},
                "mean_net_delta": routed_metrics["mean_net"] - base_metrics["mean_net"],
                "severe_loss_rate_delta": routed_metrics["severe_loss_rate"] - base_metrics["severe_loss_rate"],
            }
        )
    annual = pd.DataFrame(annual_rows)
    ANNUAL.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL, index=False, float_format="%.10g")

    pooled_base = metrics(rebuilt_baseline)
    pooled_routed = metrics(routed)
    states = {
        state: metrics(part)
        for state, part in routed.groupby("market_regime", sort=True)
    }
    each_year_count_pass = bool(annual.routed_signals.gt(50).all())
    pooled_mean_pass = bool(float(pooled_routed["mean_net"]) > 0.04)
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_DEVELOPMENT_CHART_RULE_COMPRESSION_NOT_INDEPENDENT_CONFIRMATION",
        "freeze_sha256": sha256(FREEZE),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "baseline_reproduction": reproduction,
        "baseline": pooled_base,
        "routed": pooled_routed,
        "routed_by_signal_market_state": states,
        "annual": annual.to_dict("records"),
        "deltas": {
            "mean_net": pooled_routed["mean_net"] - pooled_base["mean_net"],
            "median_net": pooled_routed["median_net"] - pooled_base["median_net"],
            "severe_loss_rate": pooled_routed["severe_loss_rate"] - pooled_base["severe_loss_rate"],
            "mean_holding_sessions": pooled_routed["mean_holding_sessions"] - pooled_base["mean_holding_sessions"],
        },
        "development_gate": {
            "each_2014_2020_year_signal_count_gt_50": each_year_count_pass,
            "pooled_completed_mean_net_gt_4pct": pooled_mean_pass,
            "pass": each_year_count_pass and pooled_mean_pass,
        },
        "causality_audit": {
            "market_state_source_after_signal_decision": int(
                candidates.market_latest_source_timestamp.gt(candidates.decision_at).sum()
            ),
            "max_signal_date": str(candidates.signal_date.max().date()),
            "max_replay_source_date": str(paths.trade_date.max().date()),
            "post_2021_signal_or_outcome_read": False,
            "2022_2024_outcome_read": False,
        },
        "event_replay_sha256": sha256(REPLAY),
        "annual_metrics_sha256": sha256(ANNUAL),
    }
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-result", action="store_true")
    args = parser.parse_args()
    result = run()
    if args.print_result:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
