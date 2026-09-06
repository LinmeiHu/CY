#!/usr/bin/env python3
"""Replay the frozen causal market-state exit translation on 2014-2020 only."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import run_ashare_deep_decline_intraday_undercut_full_absorption_v1 as parent

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-DEEP-DECLINE-INTRADAY-UNDERCUT-MARKET-STATE-EXIT-V2"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
RESULT = OS_ROOT / f"experiments/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_deep_decline_intraday_undercut_market_state_exit_v2"
)
OUTCOMES = EXT_ROOT / "development_2014_2020/outcomes.parquet"
STATE_PANEL = EXT_ROOT / "development_2014_2020/market_state.parquet"
MANIFEST = EXT_ROOT / "development_2014_2020/manifest.json"

PROFILES = {
    "UP": {"target": 0.15, "horizon": 30},
    "DOWN_SYSTEMIC": {"target": 0.10, "horizon": 20},
    "DOWN_ORDINARY": {"target": 0.05, "horizon": 5},
}


class ExperimentError(RuntimeError):
    """Fail-closed V2 experiment error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )


def classify_market_state(frame: pd.DataFrame) -> pd.Series:
    """Classify state from signal-close and completed-history aggregates only."""
    required = [
        "market_median_ret60",
        "market_median_prior5_return",
        "market_positive_fraction",
    ]
    if frame[required].isna().any().any():
        raise ExperimentError("required causal market-state aggregate is missing")
    return pd.Series(
        np.where(
            frame.market_median_ret60.gt(0.0),
            "UP",
            np.where(
                frame.market_median_prior5_return.le(-0.05)
                | frame.market_positive_fraction.ge(0.90),
                "DOWN_SYSTEMIC",
                "DOWN_ORDINARY",
            ),
        ),
        index=frame.index,
        name="market_state",
    )


def market_state_panel() -> pd.DataFrame:
    query = f"""
    WITH features AS (
      SELECT *,
        lag(coord_close,1) OVER w AS lag1_close,
        lag(coord_close,6) OVER w AS lag6_close,
        lag(cal_idx,1) OVER w AS lag1_idx,
        lag(cal_idx,6) OVER w AS lag6_idx,
        lag(invalid_step_cum,6) OVER w AS lag6_invalid
      FROM read_parquet('{parent.DAILY.as_posix()}')
      WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
    ), eligible AS (
      SELECT trade_date,ret60,step_return,
        CASE
          WHEN lag1_idx-lag6_idx=5 AND invalid_step_cum=lag6_invalid
          THEN lag1_close/lag6_close-1.0
        END AS prior5_return
      FROM features
      WHERE hard_valid AND history_valid AND current_valid
        AND current_day_data_tradable AND market_rule_valid
        AND corporate_action_valid AND NOT corporate_action_blocking AND NOT is_st
    )
    SELECT trade_date,
      count(*) AS eligible_n,
      median(ret60) AS market_median_ret60,
      median(prior5_return) AS market_median_prior5_return,
      avg((step_return>0)::INTEGER) AS market_positive_fraction
    FROM eligible
    WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
    GROUP BY trade_date
    ORDER BY trade_date
    """
    frame = duckdb.connect().execute(query).fetch_df()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["market_state"] = classify_market_state(frame)
    return frame


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    signal_idx = int(candidate.cal_idx)
    lineage = float(candidate.invalid_step_cum)
    profile = PROFILES[str(candidate.market_state)]
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "market_state": str(candidate.market_state),
        "target_fraction": float(profile["target"]),
        "horizon": int(profile["horizon"]),
    }
    if path.empty:
        return {**base, "status": "NO_FUTURE_PATH_THROUGH_2021"}
    entry_pool = path.loc[
        path.cal_idx.le(signal_idx + 3) & path.invalid_step_cum.eq(lineage)
    ]
    entry = next((row for _, row in entry_pool.iterrows() if parent.buyable_open(row)), None)
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price * (1.0 + float(profile["target"]))
    pending = False
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    invalid = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            invalid = True
            break
        if pending and parent.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = f"H{int(profile['horizon'])}_TIME_STOP"
            break
        if (
            parent.legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = f"TARGET_{round(float(profile['target']) * 100)}"
            break
        if parent.legal_state(row) and int(row.cal_idx) >= entry_idx + int(profile["horizon"]):
            pending = True
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    if invalid:
        return {**base, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY", **entry_payload}
    if exit_row is None:
        return {**base, "status": "INCOMPLETE_BY_2021_END", **entry_payload}
    gross = exit_price / entry_price - 1.0
    return {
        **base,
        "status": "COMPLETED",
        **entry_payload,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - 0.004,
    }


def annual_summary(outcomes: pd.DataFrame) -> list[dict[str, Any]]:
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    completed["year"] = completed.signal_date.dt.year
    rows = []
    for year, part in completed.groupby("year", sort=True):
        rows.append(
            {
                "year": int(year),
                "completed": len(part),
                "mean_net": float(part.net_return.mean()),
                "median_net": float(part.net_return.median()),
                "severe_loss10": float(part.net_return.le(-0.10).mean()),
                "hit4": float(part.net_return.ge(0.04).mean()),
            }
        )
    return rows


def gate(annual: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        "all_seven_years_present": [row["year"] for row in annual]
        == list(range(2014, 2021)),
        "each_year_completed_gt_50": all(row["completed"] > 50 for row in annual),
        "each_year_mean_net_gt_4pct": all(row["mean_net"] > 0.04 for row in annual),
        "each_year_median_net_positive": all(row["median_net"] > 0 for row in annual),
        "each_year_severe_loss10_at_most_15pct": all(
            row["severe_loss10"] <= 0.15 for row in annual
        ),
    }


def report_text(result: dict[str, Any]) -> str:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{result['verdict']}`.",
        "",
        (
            "Market state uses only the completed signal close and prior observations. "
            "No future return, year label, later breadth, or full-sample percentile enters "
            "state construction. The first possible fill is the next legal open."
        ),
        "",
        "|Year|Completed|Mean net|Median net|Severe <=-10%|Hit >=4%|",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["annual"]:
        lines.append(
            f"|{row['year']}|{row['completed']}|{row['mean_net']:.2%}|"
            f"{row['median_net']:.2%}|{row['severe_loss10']:.2%}|{row['hit4']:.2%}|"
        )
    lines.extend(
        [
            "",
            (
                "Frozen state-routed exits: UP -> T15/H30; DOWN_SYSTEMIC -> T10/H20; "
                "DOWN_ORDINARY -> T5/H5. The parent signal and entry identities are unchanged."
            ),
            "",
            "2021 signal outcomes read: "
            f"**{str(result['outcome_governance']['2021_signal_outcomes_read']).upper()}**.",
            "2022+ signal outcomes read: "
            f"**{str(result['outcome_governance']['2022_plus_signal_outcomes_read']).upper()}**.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    if not CONTRACT.exists() or not parent.CANDIDATES.exists():
        raise ExperimentError("missing frozen contract or parent candidate artifact")
    connection = duckdb.connect()
    candidates = connection.execute(
        f"SELECT * FROM read_parquet('{parent.CANDIDATES.as_posix()}') "
        "WHERE signal_date<=DATE '2020-12-31' ORDER BY signal_date,sleeve,symbol,event_id"
    ).fetch_df()
    connection.close()
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    if len(candidates) != 1583 or candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ExperimentError("parent development candidate identity drift")
    states = market_state_panel()
    candidates = candidates.merge(
        states, left_on="signal_date", right_on="trade_date", how="left", validate="many_to_one"
    )
    if candidates.market_state.isna().any():
        raise ExperimentError("candidate is missing frozen causal market state")
    paths = parent.load_paths(candidates)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    outcomes = pd.DataFrame(
        [
            replay_one(event, groups.get(str(event.event_id), pd.DataFrame()))
            for event in candidates.itertuples(index=False)
        ]
    )
    parent.write_parquet(outcomes, OUTCOMES)
    parent.write_parquet(states, STATE_PANEL)
    annual = annual_summary(outcomes)
    checks = gate(annual)
    passed = all(checks.values())
    result = {
        "experiment": EXPERIMENT,
        "contract_sha256": sha256(CONTRACT),
        "verdict": "DEVELOPMENT_GATE_PASS" if passed else "DEVELOPMENT_GATE_FAIL_CLOSED",
        "candidate_count": len(candidates),
        "completed_count": int(outcomes.status.eq("COMPLETED").sum()),
        "state_counts": {
            str(key): int(value)
            for key, value in candidates.market_state.value_counts().sort_index().items()
        },
        "annual": annual,
        "gate": checks,
        "outcome_governance": {
            "maximum_signal_date_read": str(candidates.signal_date.max().date()),
            "maximum_exit_date_materialized": str(
                pd.to_datetime(outcomes.exit_date).dropna().max().date()
            ),
            "2021_signal_outcomes_read": False,
            "2022_plus_signal_outcomes_read": False,
            "post_2024_outcomes_read": False,
            "cy011_read": False,
        },
    }
    canonical_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report_text(result), encoding="utf-8")
    manifest = {
        **result,
        "outcomes_sha256": sha256(OUTCOMES),
        "market_state_sha256": sha256(STATE_PANEL),
        "result_sha256": sha256(RESULT),
    }
    canonical_json(MANIFEST, manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
