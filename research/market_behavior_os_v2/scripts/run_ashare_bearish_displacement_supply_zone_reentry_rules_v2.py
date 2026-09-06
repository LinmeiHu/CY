#!/usr/bin/env python3
"""Round-2 frozen chart rules for displacement-zone re-entry events."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import run_ashare_bearish_displacement_supply_zone_reentry_rules_v1 as round1


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BEARISH-DISPLACEMENT-SUPPLY-ZONE-REENTRY-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_rules_v2_freeze.json"
RESULT = OS_ROOT / f"experiments/{EXPERIMENT}_rules_v2_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_rules_v2_report.md"
EXT_ROOT = round1.mother.EXT_ROOT / "rules_v2_2014_2020"
EVENT_RESULTS = EXT_ROOT / "event_results.parquet"
ANNUAL_TABLE = EXT_ROOT / "annual_summary.csv"
STATE_TABLE = EXT_ROOT / "market_state_summary.csv"
COST = 0.004


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def replay_profile(
    candidate: Any,
    path: pd.DataFrame,
    *,
    signal_low_exit: bool,
    horizon: int,
) -> dict[str, Any]:
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_idx": int(candidate.signal_idx),
        "signal_low": float(candidate.signal_low),
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
        (
            row
            for _, row in entry_pool.iterrows()
            if round1.mother.execution.buyable_open(row)
        ),
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
    if float(candidate.zone_u) / entry_price - 1.0 < round1.mother.ENTRY_GROSS_HEADROOM:
        return {**base, **entry_payload, "status": "INSUFFICIENT_ENTRY_HEADROOM"}

    pending_reason: str | None = None
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **base,
                **entry_payload,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if pending_reason is not None and round1.mother.execution.sellable_open(row):
            exit_price = float(row.coord_open)
            gross = exit_price / entry_price - 1.0
            return {
                **base,
                **entry_payload,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_idx": int(row.cal_idx),
                "exit_price": exit_price,
                "exit_reason": pending_reason,
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if (
            round1.mother.execution.legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= float(candidate.zone_u)
        ):
            gross = float(candidate.zone_u) / entry_price - 1.0
            return {
                **base,
                **entry_payload,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_idx": int(row.cal_idx),
                "exit_price": float(candidate.zone_u),
                "exit_reason": "FULL_ZONE_U",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if (
            signal_low_exit
            and round1.mother.execution.legal_state(row)
            and np.isfinite(float(row.coord_close))
            and float(row.coord_close) < float(candidate.signal_low)
        ):
            pending_reason = "CLOSE_BELOW_SIGNAL_LOW"
        elif round1.mother.execution.legal_state(row) and int(row.cal_idx) >= entry_idx + horizon:
            pending_reason = f"H{horizon}_TIME_STOP"
    return {**base, **entry_payload, "status": "INCOMPLETE_BOUNDED_PATH"}


def run() -> dict[str, Any]:
    if not SPEC.exists():
        raise round1.RuleEvaluationError("round-2 frozen specification is missing")
    candidates = round1.load_development_candidates()
    paths = round1.load_bounded_paths(candidates)
    path_groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    profiles = {
        "BASELINE_H20": (False, 20),
        "R3_SIGNAL_LOW": (True, 20),
        "R4_H10": (False, 10),
        "R3_PLUS_R4": (True, 10),
    }
    rows: list[dict[str, Any]] = []
    for profile, (signal_low_exit, horizon) in profiles.items():
        for event in candidates.itertuples(index=False):
            rows.append(
                {
                    "profile": profile,
                    **replay_profile(
                        event,
                        path_groups.get(str(event.event_id), pd.DataFrame()),
                        signal_low_exit=signal_low_exit,
                        horizon=horizon,
                    ),
                }
            )
    results = pd.DataFrame(rows)
    states = round1.load_causal_market_state(candidates.signal_date)
    results = results.merge(states, on="signal_date", how="left", validate="many_to_one")
    if results.market_state.isna().any():
        raise round1.RuleEvaluationError("round-2 event state merge failed")
    results["signal_year"] = results.signal_date.dt.year
    round1.mother.execution.write_parquet(results, EVENT_RESULTS)
    annual = round1.summarize(results, ["profile", "signal_year"])
    state = round1.summarize(results, ["profile", "market_state"])
    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL_TABLE, index=False)
    state.to_csv(STATE_TABLE, index=False)
    chosen = annual.loc[annual.profile.eq("R3_PLUS_R4")]
    user_gate = bool(
        len(chosen) == 7
        and chosen.completed.ge(50).all()
        and chosen.mean_net.gt(0.04).all()
    )
    payload = {
        "experiment": EXPERIMENT,
        "stage": "V26_STYLE_CHART_RULE_COMPRESSION_ROUND_2",
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "event_results_sha256": sha256(EVENT_RESULTS),
        "annual_summary_sha256": sha256(ANNUAL_TABLE),
        "market_state_summary_sha256": sha256(STATE_TABLE),
        "development_candidate_count": int(len(candidates)),
        "profiles": annual.to_dict(orient="records"),
        "market_states": state.to_dict(orient="records"),
        "user_gate_passed": user_gate,
        "2021_signal_outcomes_read": False,
        "2022_plus_outcomes_read": False,
        "post_2024_outcomes_read": False,
        "cy011_read": False,
    }
    round1.canonical_json(RESULT, payload)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(round1.render_report(payload), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        raise SystemExit("use --run")
    print(json.dumps(run(), sort_keys=True, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
