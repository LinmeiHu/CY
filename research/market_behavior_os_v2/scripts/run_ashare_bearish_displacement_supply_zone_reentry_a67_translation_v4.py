#!/usr/bin/env python3
"""Frozen A67 partial-repair translation for displacement-zone re-entry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import run_ashare_bearish_displacement_supply_zone_reentry_rules_v1 as round1
import run_ashare_bearish_displacement_supply_zone_reentry_semantic_anatomy_v3 as anatomy


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BEARISH-DISPLACEMENT-SUPPLY-ZONE-REENTRY-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_a67_translation_v4_freeze.json"
RESULT = OS_ROOT / f"experiments/{EXPERIMENT}_a67_translation_v4_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_a67_translation_v4_report.md"
EXT_ROOT = round1.mother.EXT_ROOT / "a67_translation_v4_2014_2020"
EVENTS = EXT_ROOT / "event_results.parquet"
ANNUAL = EXT_ROOT / "annual_summary.csv"
STATE = EXT_ROOT / "market_state_summary.csv"
A67 = 0.67
COST = 0.004
HORIZON = 20


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
    target_fraction: float,
    require_net4: bool,
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
    if float(candidate.zone_u) / entry_price - 1.0 < round1.mother.ENTRY_GROSS_HEADROOM:
        return {**base, "status": "INSUFFICIENT_ENTRY_HEADROOM"}
    target_price = entry_price + target_fraction * (float(candidate.zone_u) - entry_price)
    target_net = target_price / entry_price - 1.0 - COST
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_idx": entry_idx,
        "entry_price": entry_price,
        "target_price": target_price,
        "target_fraction": target_fraction,
        "target_net_headroom": target_net,
    }
    if require_net4 and target_net < 0.04:
        return {**base, **entry_payload, "status": "A67_NET_HEADROOM_LT_4PCT"}
    pending = False
    for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **base,
                **entry_payload,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if pending and round1.mother.execution.sellable_open(row):
            exit_price = float(row.coord_open)
            gross = exit_price / entry_price - 1.0
            return {
                **base,
                **entry_payload,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_idx": int(row.cal_idx),
                "exit_price": exit_price,
                "exit_reason": "H20_TIME_STOP",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if (
            round1.mother.execution.legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            gross = target_price / entry_price - 1.0
            return {
                **base,
                **entry_payload,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_idx": int(row.cal_idx),
                "exit_price": target_price,
                "exit_reason": "TARGET",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if round1.mother.execution.legal_state(row) and int(row.cal_idx) >= entry_idx + HORIZON:
            pending = True
    return {**base, **entry_payload, "status": "INCOMPLETE_BOUNDED_PATH"}


def summarize(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    part = frame.loc[frame.status.eq("COMPLETED")].copy()
    part["positive"] = part.net_return.gt(0)
    part["ge_4pct"] = part.net_return.ge(0.04)
    part["severe_loss"] = part.net_return.le(-0.10)
    part["target_hit"] = part.exit_reason.eq("TARGET")
    return (
        part.groupby(groups, dropna=False)
        .agg(
            completed=("event_id", "size"),
            mean_net=("net_return", "mean"),
            median_net=("net_return", "median"),
            positive_rate=("positive", "mean"),
            ge_4pct_rate=("ge_4pct", "mean"),
            severe_loss_rate=("severe_loss", "mean"),
            target_hit_rate=("target_hit", "mean"),
            mean_target_net=("target_net_headroom", "mean"),
        )
        .reset_index()
    )


def run() -> dict[str, Any]:
    if not SPEC.exists():
        raise round1.RuleEvaluationError("frozen A67 specification missing")
    candidates = round1.load_development_candidates()
    paths = round1.load_bounded_paths(candidates)
    path_groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    profiles = {
        "FULL_ZONE_U": (1.0, False),
        "A67": (A67, False),
        "A67_NET4": (A67, True),
    }
    rows: list[dict[str, Any]] = []
    for profile, (fraction, net4) in profiles.items():
        for event in candidates.itertuples(index=False):
            rows.append(
                {
                    "profile": profile,
                    **replay_profile(
                        event,
                        path_groups.get(str(event.event_id), pd.DataFrame()),
                        target_fraction=fraction,
                        require_net4=net4,
                    ),
                }
            )
    events = pd.DataFrame(rows)
    states = anatomy.load_market_quadrants(candidates.signal_date)
    events = events.merge(states, on="signal_date", how="left", validate="many_to_one")
    if events.market_quadrant.isna().any():
        raise round1.RuleEvaluationError("A67 market state merge failed")
    events["signal_year"] = events.signal_date.dt.year
    round1.mother.execution.write_parquet(events, EVENTS)
    annual = summarize(events, ["profile", "signal_year"])
    state = summarize(events, ["profile", "market_quadrant"])
    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL, index=False)
    state.to_csv(STATE, index=False)
    chosen = annual.loc[annual.profile.eq("A67_NET4")]
    user_gate = bool(
        len(chosen) == 7
        and chosen.completed.ge(50).all()
        and chosen.mean_net.gt(0.04).all()
    )
    payload = {
        "experiment": EXPERIMENT,
        "stage": "V26_INSPIRED_A67_TRANSLATION_V4",
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "events_sha256": sha256(EVENTS),
        "annual_sha256": sha256(ANNUAL),
        "state_sha256": sha256(STATE),
        "annual": annual.to_dict(orient="records"),
        "market_quadrants": state.to_dict(orient="records"),
        "user_gate_passed": user_gate,
        "2021_signal_outcomes_read": False,
        "2022_plus_outcomes_read": False,
        "post_2024_outcomes_read": False,
        "cy011_read": False,
    }
    round1.canonical_json(RESULT, payload)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_report(payload), encoding="utf-8")
    return payload


def render_report(payload: dict[str, Any]) -> str:
    annual = pd.DataFrame(payload["annual"])
    state = pd.DataFrame(payload["market_quadrants"])
    return "\n".join(
        [
            f"# {EXPERIMENT} — A67 Translation V4",
            "",
            "Post-hoc chart-generated development translation; not confirmation.",
            "",
            "## Annual results",
            "",
            annual.to_markdown(index=False, floatfmt=".4f"),
            "",
            "## Causal market-state results",
            "",
            state.to_markdown(index=False, floatfmt=".4f"),
            "",
            f"User gate passed: **{payload['user_gate_passed']}**",
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
