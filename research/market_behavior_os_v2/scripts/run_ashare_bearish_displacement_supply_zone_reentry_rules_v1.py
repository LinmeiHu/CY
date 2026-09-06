#!/usr/bin/env python3
"""Evaluate frozen chart-derived rules for displacement-zone re-entry events."""

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
import run_ashare_bearish_displacement_supply_zone_reentry_v1 as mother


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BEARISH-DISPLACEMENT-SUPPLY-ZONE-REENTRY-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_rules_v1_freeze.json"
RESULT = OS_ROOT / f"experiments/{EXPERIMENT}_rules_v1_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_rules_v1_report.md"
EXT_ROOT = mother.EXT_ROOT / "rules_v1_2014_2020"
EVENT_RESULTS = EXT_ROOT / "event_results.parquet"
ANNUAL_TABLE = EXT_ROOT / "annual_summary.csv"
STATE_TABLE = EXT_ROOT / "market_state_summary.csv"

DEVELOPMENT_END = pd.Timestamp("2020-12-31")
COST = 0.004
HORIZON = 20


class RuleEvaluationError(RuntimeError):
    """Fail-closed rule-evaluation error."""


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


def load_development_candidates() -> pd.DataFrame:
    candidates = mother.verify_freeze()
    candidates = candidates.loc[candidates.signal_date.le(DEVELOPMENT_END)].copy()
    if candidates.empty or candidates.signal_date.max() > DEVELOPMENT_END:
        raise RuleEvaluationError("development candidate boundary failed")
    return candidates


def load_bounded_paths(candidates: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "candidate_ids",
        candidates[
            ["event_id", "symbol", "signal_date", "signal_idx", "invalid_step_cum"]
        ],
    )
    frame = connection.execute(
        f"""
        SELECT c.event_id,c.signal_date,c.signal_idx,
          c.invalid_step_cum AS signal_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,
          d.market_rule_valid,d.corporate_action_valid,d.corporate_action_blocking,
          d.hard_valid,d.up_limit_price,d.down_limit_price
        FROM candidate_ids c JOIN read_parquet('{mother.DAILY.as_posix()}') d
          ON c.symbol=d.symbol
         AND d.cal_idx BETWEEN c.signal_idx+1 AND c.signal_idx+35
        WHERE d.trade_date<=DATE '2021-07-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def load_causal_market_state(signal_dates: pd.Series) -> pd.DataFrame:
    dates = pd.DataFrame({"signal_date": pd.to_datetime(signal_dates).drop_duplicates()})
    connection = duckdb.connect()
    connection.register("signal_dates", dates)
    frame = connection.execute(
        f"""
        SELECT d.trade_date AS signal_date,
          median(d.ret60) AS market_median_ret60,
          count(*) AS market_state_n
        FROM read_parquet('{mother.DAILY.as_posix()}') d
        JOIN signal_dates s ON d.trade_date=s.signal_date
        WHERE d.trade_date<=DATE '2020-12-31'
          AND d.hard_valid AND d.history_valid AND d.current_valid
          AND d.current_day_data_tradable AND d.market_rule_valid
          AND d.corporate_action_valid AND NOT d.corporate_action_blocking
          AND NOT d.is_st AND isfinite(d.ret60)
        GROUP BY d.trade_date
        ORDER BY d.trade_date
        """
    ).fetch_df()
    connection.close()
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if frame.signal_date.nunique() != dates.signal_date.nunique():
        raise RuleEvaluationError("market state coverage is incomplete")
    if int(frame.market_state_n.min()) < 100:
        raise RuleEvaluationError("market state breadth is insufficient")
    frame["market_state"] = np.where(
        frame.market_median_ret60.ge(0.0), "BULL", "BEAR"
    )
    return frame


def replay_profile(
    candidate: Any,
    path: pd.DataFrame,
    *,
    retain_zone_at_entry: bool,
    failure_exit: bool,
) -> dict[str, Any]:
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_idx": int(candidate.signal_idx),
        "zone_l": float(candidate.zone_l),
        "zone_u": float(candidate.zone_u),
    }
    lineage = float(candidate.invalid_step_cum)
    if path.empty:
        return {**base, "status": "NO_BOUNDED_PATH"}
    entry_pool = path.loc[
        path.cal_idx.le(int(candidate.signal_idx) + 3)
        & path.invalid_step_cum.eq(lineage)
    ]
    entry = next(
        (row for _, row in entry_pool.iterrows() if mother.execution.buyable_open(row)),
        None,
    )
    if entry is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_idx": entry_idx,
        "entry_price": entry_price,
        "gross_headroom": float(candidate.zone_u) / entry_price - 1.0,
    }
    if float(candidate.zone_u) / entry_price - 1.0 < mother.ENTRY_GROSS_HEADROOM:
        return {**base, **entry_payload, "status": "INSUFFICIENT_ENTRY_HEADROOM"}
    if retain_zone_at_entry and entry_price < float(candidate.zone_l):
        return {**base, **entry_payload, "status": "ENTRY_OPEN_BELOW_ZONE_L"}

    pending_reason: str | None = None
    exit_row: pd.Series | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **base,
                **entry_payload,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if pending_reason is not None and mother.execution.sellable_open(row):
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = pending_reason
            break
        if (
            mother.execution.legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= float(candidate.zone_u)
        ):
            exit_row = row
            exit_price = float(candidate.zone_u)
            exit_reason = "FULL_ZONE_U"
            break
        if (
            failure_exit
            and mother.execution.legal_state(row)
            and np.isfinite(float(row.coord_close))
            and float(row.coord_close) < float(candidate.zone_l)
        ):
            pending_reason = "CLOSE_BACK_BELOW_ZONE_L"
        elif mother.execution.legal_state(row) and int(row.cal_idx) >= entry_idx + HORIZON:
            pending_reason = "H20_TIME_STOP"
    if exit_row is None:
        return {**base, **entry_payload, "status": "INCOMPLETE_BOUNDED_PATH"}
    gross = exit_price / entry_price - 1.0
    return {
        **base,
        **entry_payload,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_idx": int(exit_row.cal_idx),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - COST,
    }


def summarize(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    completed["positive"] = completed.net_return.gt(0.0)
    completed["ge_4pct"] = completed.net_return.ge(0.04)
    completed["severe_loss"] = completed.net_return.le(-0.10)
    completed["target_hit"] = completed.exit_reason.eq("FULL_ZONE_U")
    return (
        completed.groupby(groups, dropna=False)
        .agg(
            completed=("event_id", "size"),
            mean_net=("net_return", "mean"),
            median_net=("net_return", "median"),
            positive_rate=("positive", "mean"),
            ge_4pct_rate=("ge_4pct", "mean"),
            severe_loss_rate=("severe_loss", "mean"),
            target_hit_rate=("target_hit", "mean"),
            mean_holding=("holding_sessions", "mean"),
        )
        .reset_index()
    )


def run() -> dict[str, Any]:
    if not SPEC.exists():
        raise RuleEvaluationError("frozen rule specification is missing")
    candidates = load_development_candidates()
    paths = load_bounded_paths(candidates)
    groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    profiles = {
        "BASELINE": (False, False),
        "R1_ONLY": (True, False),
        "R2_ONLY": (False, True),
        "R1_PLUS_R2": (True, True),
    }
    rows: list[dict[str, Any]] = []
    for profile, (retain_zone, failure_exit) in profiles.items():
        for event in candidates.itertuples(index=False):
            result = replay_profile(
                event,
                groups.get(str(event.event_id), pd.DataFrame()),
                retain_zone_at_entry=retain_zone,
                failure_exit=failure_exit,
            )
            rows.append({"profile": profile, **result})
    results = pd.DataFrame(rows)
    states = load_causal_market_state(candidates.signal_date)
    results = results.merge(states, on="signal_date", how="left", validate="many_to_one")
    if results.market_state.isna().any():
        raise RuleEvaluationError("event state merge failed")
    results["signal_year"] = results.signal_date.dt.year
    mother.execution.write_parquet(results, EVENT_RESULTS)
    annual = summarize(results, ["profile", "signal_year"])
    state = summarize(results, ["profile", "market_state"])
    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL_TABLE, index=False)
    state.to_csv(STATE_TABLE, index=False)

    chosen = annual.loc[annual.profile.eq("R1_PLUS_R2")]
    user_gate = bool(
        len(chosen) == 7
        and chosen.completed.ge(50).all()
        and chosen.mean_net.gt(0.04).all()
    )
    payload = {
        "experiment": EXPERIMENT,
        "stage": "V26_STYLE_CHART_RULE_COMPRESSION_ROUND_1",
        "spec_sha256": sha256(SPEC),
        "mother_candidate_sha256": sha256(mother.CANDIDATES),
        "event_results_sha256": sha256(EVENT_RESULTS),
        "annual_summary_sha256": sha256(ANNUAL_TABLE),
        "market_state_summary_sha256": sha256(STATE_TABLE),
        "development_signal_start": str(candidates.signal_date.min().date()),
        "development_signal_end": str(candidates.signal_date.max().date()),
        "development_candidate_count": int(len(candidates)),
        "2021_signal_outcomes_read": False,
        "2022_plus_outcomes_read": False,
        "post_2024_outcomes_read": False,
        "cy011_read": False,
        "profiles": annual.to_dict(orient="records"),
        "market_states": state.to_dict(orient="records"),
        "user_gate_passed": user_gate,
    }
    canonical_json(RESULT, payload)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_report(payload), encoding="utf-8")
    return payload


def render_report(payload: dict[str, Any]) -> str:
    annual = pd.DataFrame(payload["profiles"])
    state = pd.DataFrame(payload["market_states"])
    return "\n".join(
        [
            f"# {EXPERIMENT} — Chart Rule Compression Round 1",
            "",
            "This is chart-generated development research, not independent confirmation.",
            "",
            "## Annual results",
            "",
            annual.to_markdown(index=False, floatfmt=".4f"),
            "",
            "## Causal market-state anatomy",
            "",
            state.to_markdown(index=False, floatfmt=".4f"),
            "",
            f"User gate passed: **{payload['user_gate_passed']}**",
            "",
            "2021 signal outcomes remain unread. 2022+ outcomes remain unread. CY011 remains unread.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        raise SystemExit("use --run")
    print(json.dumps(run(), sort_keys=True, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
