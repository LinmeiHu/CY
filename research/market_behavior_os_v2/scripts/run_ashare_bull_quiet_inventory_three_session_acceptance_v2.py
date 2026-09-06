#!/usr/bin/env python3
"""Evaluate the single chart-derived three-session acceptance rule."""

from __future__ import annotations

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
EXPERIMENT = "ASHARE-BULL-QUIET-INVENTORY-THREE-SESSION-ACCEPTANCE-V2"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_development_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_development_report.md"

FEATURES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_information_repricing_long_translation_v2/"
    "stage_a/candidates_features_2014_2023_frozen.parquet"
)
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
CHART_LEDGER = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_quiet_inventory_repricing_chart_rules_v1/"
    "development_2014_2020/review_ledger.parquet"
)
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_quiet_inventory_three_session_acceptance_v2/development_2014_2020"
)
OUTCOMES = EXT_ROOT / "outcomes.parquet"
ACCEPTANCE_LEDGER = EXT_ROOT / "acceptance_ledger.parquet"
MANIFEST = EXT_ROOT / "manifest.json"

EXPECTED_HASHES = {
    "contract": "4d5b4249276cc4f2ca5ab3651443832aa3c581dc57022e479a8ef51d8f251822",
    "features": "887ffd4d92fb992a718671f1b0d6eda28e4a6086ec948e27956ec3ceb3b5daea",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    "daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
}
EXPECTED_SIGNALS = 606
TARGET = 0.20
HORIZON = 60
ROUND_TRIP_COST = 0.004


class ExperimentError(RuntimeError):
    """Fail closed when a frozen input or execution invariant is violated."""


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
        "daily": DAILY,
    }
    missing = [str(path) for path in [*paths.values(), CHART_LEDGER] if not path.is_file()]
    if missing:
        raise ExperimentError(f"missing required input: {missing}")
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": EXPECTED_HASHES[name], "actual": value}
        for name, value in actual.items()
        if value != EXPECTED_HASHES[name]
    }
    if drift:
        raise ExperimentError(f"frozen input drift: {drift}")
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


def load_candidates() -> pd.DataFrame:
    connection = duckdb.connect()
    candidates = connection.execute(
        f"""
        SELECT f.event_id,f.symbol,f.sleeve,f.signal_date,f.cal_idx,
          f.platform_high,f.invalid_step_cum,f.available_at,f.decision_at,
          r.market_regime
        FROM read_parquet('{FEATURES.as_posix()}') f
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON f.signal_date=r.trade_date
        WHERE f.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
          AND r.market_regime='BULL'
        ORDER BY f.signal_date,f.sleeve,f.symbol,f.event_id
        """
    ).fetch_df()
    connection.close()
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    if len(candidates) != EXPECTED_SIGNALS or candidates.event_id.nunique() != EXPECTED_SIGNALS:
        raise ExperimentError(f"expected {EXPECTED_SIGNALS} signals, got {len(candidates)}")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ExperimentError("candidate availability exceeds signal decision time")
    if candidates.platform_high.isna().any():
        raise ExperimentError("missing frozen platform high")
    return candidates


def load_paths(candidates: pd.DataFrame) -> pd.DataFrame:
    ids = candidates[
        ["event_id", "symbol", "signal_date", "cal_idx", "invalid_step_cum"]
    ].copy()
    connection = duckdb.connect()
    connection.register("candidate_ids", ids)
    paths = connection.execute(
        f"""
        SELECT c.event_id,c.signal_date,c.cal_idx AS signal_cal_idx,
          c.invalid_step_cum AS signal_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.current_valid,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM candidate_ids c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol
         AND d.cal_idx>c.cal_idx
         AND d.cal_idx<=c.cal_idx+75
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    return paths


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.cal_idx)
    lineage = float(candidate.invalid_step_cum)
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "platform_high": float(candidate.platform_high),
    }
    same_lineage = path.loc[path.invalid_step_cum.eq(lineage)].copy()
    observations = [row for _, row in same_lineage.iterrows() if legal_observation(row)]
    if len(observations) < 3:
        return {**base, "status": "NO_THIRD_OBSERVATION"}
    first_three = observations[:3]
    decision = first_three[2]
    decision_idx = int(decision.cal_idx)
    accepted = float(decision.coord_close) >= float(candidate.platform_high)
    acceptance_payload = {
        "observation_1_date": pd.Timestamp(first_three[0].trade_date),
        "observation_2_date": pd.Timestamp(first_three[1].trade_date),
        "acceptance_decision_date": pd.Timestamp(decision.trade_date),
        "acceptance_decision_cal_idx": decision_idx,
        "observation_1_close_to_platform": float(first_three[0].coord_close)
        / float(candidate.platform_high)
        - 1.0,
        "observation_2_close_to_platform": float(first_three[1].coord_close)
        / float(candidate.platform_high)
        - 1.0,
        "observation_3_close_to_platform": float(decision.coord_close)
        / float(candidate.platform_high)
        - 1.0,
        "accepted": accepted,
    }
    if not accepted:
        return {**base, **acceptance_payload, "status": "REJECTED_NOT_ACCEPTED"}
    entry_pool = same_lineage.loc[
        same_lineage.cal_idx.gt(decision_idx)
        & same_lineage.cal_idx.le(decision_idx + 3)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if buyable_open(row)), None)
    if entry is None:
        return {**base, **acceptance_payload, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * (1.0 + TARGET)
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
            exit_reason = "H60_TIME_STOP"
            break
        if (
            legal_observation(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = "TARGET_20"
            break
        if legal_observation(row) and int(row.cal_idx) >= entry_idx + HORIZON:
            pending_time_exit = True
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {
            **base,
            **acceptance_payload,
            **entry_payload,
            "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
        }
    if exit_row is None:
        return {
            **base,
            **acceptance_payload,
            **entry_payload,
            "status": "INCOMPLETE_PATH",
        }
    gross = float(exit_price) / entry_price - 1.0
    return {
        **base,
        **acceptance_payload,
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
        "mother_signals": int(len(frame)),
        "accepted": int(frame.get("accepted", pd.Series(dtype=bool)).fillna(False).sum()),
        "completed": int(len(completed)),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "win_rate": None if completed.empty else float(values.gt(0).mean()),
        "severe10": None if completed.empty else float(values.le(-0.10).mean()),
        "target_hit": None
        if completed.empty
        else float(completed.exit_reason.eq("TARGET_20").mean()),
        "mean_holding_sessions": None
        if completed.empty
        else float(completed.holding_sessions.mean()),
    }


def summarize(outcomes: pd.DataFrame) -> dict[str, Any]:
    outcomes = outcomes.copy()
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date)
    yearly = {
        str(year): metrics(outcomes.loc[outcomes.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    pooled = metrics(outcomes)
    gate = {
        "completed_per_year_gt_50": pooled["completed"] / 7.0 > 50,
        "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None
        and pooled["mean_net"] > 0.04,
        "every_year_with_completed_trades_mean_positive": all(
            item["completed"] == 0
            or (item["mean_net"] is not None and item["mean_net"] > 0)
            for item in yearly.values()
        ),
        "pooled_median_net_positive": pooled["median_net"] is not None
        and pooled["median_net"] > 0,
        "severe10_le_15pct": pooled["severe10"] is not None
        and pooled["severe10"] <= 0.15,
    }
    return {
        "pooled": pooled,
        "completed_per_year": pooled["completed"] / 7.0,
        "yearly": yearly,
        "gate": gate,
    }


def outcome_bucket_acceptance(outcomes: pd.DataFrame) -> dict[str, Any]:
    chart = duckdb.connect().execute(
        f"SELECT event_id,outcome_bucket FROM read_parquet('{CHART_LEDGER.as_posix()}')"
    ).fetch_df()
    joined = chart.merge(
        outcomes[["event_id", "accepted", "status"]],
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    result: dict[str, Any] = {}
    for bucket, part in joined.groupby("outcome_bucket", dropna=False, sort=True):
        result[str(bucket)] = {
            "signals": int(len(part)),
            "accepted": int(part.accepted.fillna(False).sum()),
            "acceptance_rate": float(part.accepted.fillna(False).mean()),
        }
    return result


def render_report(result: dict[str, Any]) -> None:
    summary = result["development_2014_2020"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "## Frozen simple rule",
        "",
        "1. In the causal BULL state, find the unchanged quiet-inventory 40-session platform breakout.",
        "2. Wait for exactly three subsequent completed tradable stock sessions.",
        "3. If the third close is still at or above the platform high known before the breakout, buy the next legal open; otherwise skip.",
        "4. Sell at +20% or the first legal open after the H60 close decision; no stop; 40 bp round trip.",
        "",
        "The BULL state is known at the mother-signal close. The acceptance decision is known at the third observation close. No signal or acceptance bar is used for its own fill.",
        "",
        "## Development result",
        "",
        f"Mother signals {summary['pooled']['mother_signals']}; accepted {summary['pooled']['accepted']}; completed {summary['pooled']['completed']} ({summary['completed_per_year']:.1f}/year); mean net {summary['pooled']['mean_net']:.2%}; median {summary['pooled']['median_net']:.2%}; win {summary['pooled']['win_rate']:.2%}; severe10 {summary['pooled']['severe10']:.2%}.",
        "",
        "|Year|Mother|Accepted|Completed|Mean net|Median net|Win|Severe10|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in range(2014, 2021):
        item = summary["yearly"][str(year)]
        mean = "NA" if item["mean_net"] is None else f"{item['mean_net']:.2%}"
        median = "NA" if item["median_net"] is None else f"{item['median_net']:.2%}"
        win = "NA" if item["win_rate"] is None else f"{item['win_rate']:.2%}"
        severe = "NA" if item["severe10"] is None else f"{item['severe10']:.2%}"
        lines.append(
            f"|{year}|{item['mother_signals']}|{item['accepted']}|{item['completed']}|{mean}|{median}|{win}|{severe}|"
        )
    lines += [
        "",
        "## Scientific status",
        "",
        "The acceptance direction was generated by visual inspection of consumed 2014-2020 outcomes. This is post-hoc development evidence, not independent confirmation. No 2021-plus mother-signal outcome is read by this development run.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = load_candidates()
    paths = load_paths(candidates)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            replay_one(candidate, groups.get(str(candidate.event_id), pd.DataFrame()))
            for candidate in candidates.itertuples(index=False)
        ]
    )
    if outcomes.event_id.duplicated().any():
        raise ExperimentError("duplicate outcome identity")
    if pd.to_datetime(outcomes.signal_date).dt.year.gt(2020).any():
        raise ExperimentError("post-2020 mother signal entered development")
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "entry_at_or_before_signal": int(
            completed.entry_cal_idx.le(completed.signal_cal_idx).sum()
        ),
        "entry_at_or_before_acceptance": int(
            completed.entry_cal_idx.le(completed.acceptance_decision_cal_idx).sum()
        ),
        "exit_at_or_before_entry": int(
            completed.exit_cal_idx.le(completed.entry_cal_idx).sum()
        ),
    }
    if any(chronology.values()):
        raise ExperimentError(f"execution chronology failure: {chronology}")
    write_parquet(outcomes, OUTCOMES)
    acceptance_columns = [
        "event_id",
        "symbol",
        "sleeve",
        "signal_date",
        "signal_cal_idx",
        "platform_high",
        "observation_1_date",
        "observation_2_date",
        "acceptance_decision_date",
        "acceptance_decision_cal_idx",
        "observation_1_close_to_platform",
        "observation_2_close_to_platform",
        "observation_3_close_to_platform",
        "accepted",
        "status",
    ]
    write_parquet(outcomes.reindex(columns=acceptance_columns), ACCEPTANCE_LEDGER)
    development = summarize(outcomes)
    result = {
        "experiment": EXPERIMENT,
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "development_2014_2020": development,
        "original_outcome_bucket_acceptance": outcome_bucket_acceptance(outcomes),
        "chronology_audit": chronology,
        "outcomes_sha256": sha256(OUTCOMES),
        "acceptance_ledger_sha256": sha256(ACCEPTANCE_LEDGER),
        "post_2020_mother_signal_outcome_read": "NO",
        "verdict": (
            "THREE_SESSION_ACCEPTANCE_PASSES_DEVELOPMENT_GATE"
            if all(development["gate"].values())
            else "THREE_SESSION_ACCEPTANCE_FAILS_DEVELOPMENT_GATE"
        ),
    }
    write_json(RESULT, result)
    render_report(result)
    manifest = {
        **result,
        "result_sha256": sha256(RESULT),
        "report_sha256": sha256(REPORT),
    }
    write_json(MANIFEST, manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2, default=str))
