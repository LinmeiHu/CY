#!/usr/bin/env python3
"""V26/V27-inspired semantic anatomy for the displacement-zone mother event."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import run_ashare_bearish_displacement_supply_zone_reentry_rules_v1 as round1


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BEARISH-DISPLACEMENT-SUPPLY-ZONE-REENTRY-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_semantic_anatomy_v3_freeze.json"
RESULT = OS_ROOT / f"experiments/{EXPERIMENT}_semantic_anatomy_v3_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_semantic_anatomy_v3_report.md"
EXT_ROOT = round1.mother.EXT_ROOT / "semantic_anatomy_v3_2014_2020"
FEATURES = EXT_ROOT / "semantic_features.parquet"
PROFILE_EVENTS = EXT_ROOT / "profile_events.parquet"
ANNUAL = EXT_ROOT / "annual_summary.csv"
STATE = EXT_ROOT / "market_state_summary.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_semantic_features(candidates: pd.DataFrame) -> pd.DataFrame:
    identifiers = candidates[
        [
            "event_id",
            "symbol",
            "formation_idx",
            "first_below_idx",
            "signal_idx",
            "zone_l",
            "zone_u",
            "signal_close",
            "formation_turnover",
            "invalid_step_cum",
        ]
    ].copy()
    connection = duckdb.connect()
    connection.register("candidate_ids", identifiers)
    frame = connection.execute(
        f"""
        SELECT c.event_id,
          count(*) FILTER (
            WHERE d.cal_idx BETWEEN c.formation_idx-120 AND c.formation_idx-1
              AND d.invalid_step_cum=c.invalid_step_cum
              AND d.hard_valid AND d.history_valid AND d.current_valid
          ) AS pre120_n,
          arg_max(d.cal_idx,d.coord_high) FILTER (
            WHERE d.cal_idx BETWEEN c.formation_idx-120 AND c.formation_idx-1
              AND d.invalid_step_cum=c.invalid_step_cum
              AND d.hard_valid AND d.history_valid AND d.current_valid
          ) AS pre120_peak_idx,
          count(*) FILTER (
            WHERE d.cal_idx BETWEEN c.formation_idx-120 AND c.formation_idx-1
              AND d.invalid_step_cum=c.invalid_step_cum
              AND d.hard_valid AND d.history_valid AND d.current_valid
              AND d.coord_high >= c.zone_l-0.5*(c.zone_u-c.zone_l)
              AND d.coord_low <= c.zone_u+0.5*(c.zone_u-c.zone_l)
          ) AS pre_corridor_touch_sessions,
          min(d.coord_low) FILTER (
            WHERE d.cal_idx BETWEEN c.first_below_idx AND c.signal_idx-1
              AND d.invalid_step_cum=c.invalid_step_cum
              AND d.hard_valid AND d.current_valid
          ) AS washout_low,
          avg(d.turnover_fraction) FILTER (
            WHERE d.cal_idx BETWEEN c.signal_idx-20 AND c.signal_idx-1
              AND d.invalid_step_cum=c.invalid_step_cum
              AND d.hard_valid AND d.current_valid
          ) AS pre_signal_turn20,
          count(*) FILTER (
            WHERE d.cal_idx BETWEEN c.signal_idx-20 AND c.signal_idx-1
              AND d.invalid_step_cum=c.invalid_step_cum
              AND d.hard_valid AND d.current_valid
          ) AS pre_signal_n20
        FROM candidate_ids c JOIN read_parquet('{round1.mother.DAILY.as_posix()}') d
          ON c.symbol=d.symbol
         AND d.cal_idx BETWEEN c.formation_idx-120 AND c.signal_idx-1
        GROUP BY c.event_id
        ORDER BY c.event_id
        """
    ).fetch_df()
    connection.close()
    merged = identifiers.merge(frame, on="event_id", how="left", validate="one_to_one")
    merged["semantic_valid"] = (
        merged.pre120_n.eq(120)
        & merged.pre_signal_n20.eq(20)
        & merged.pre120_peak_idx.notna()
        & merged.washout_low.notna()
        & merged.pre_signal_turn20.notna()
    )
    merged["zone_width_pct"] = merged.zone_u / merged.zone_l - 1.0
    merged["pre_peak_age"] = merged.formation_idx - merged.pre120_peak_idx
    merged["washout_depth"] = 1.0 - merged.washout_low / merged.zone_l
    merged["snapback_from_low"] = (merged.signal_close - merged.washout_low) / merged.zone_l
    merged["dry_base_ratio"] = merged.pre_signal_turn20 / merged.formation_turnover
    merged["s1_modest_zone"] = merged.semantic_valid & merged.zone_width_pct.le(0.10)
    merged["s2_clean_corridor"] = merged.semantic_valid & merged.pre_corridor_touch_sessions.le(10)
    merged["s3_mature_decline"] = merged.semantic_valid & merged.pre_peak_age.ge(20)
    merged["s4_meaningful_washout"] = merged.semantic_valid & merged.washout_depth.ge(0.10)
    merged["s5_dry_base"] = merged.semantic_valid & merged.dry_base_ratio.le(1.0)
    merged["s1_to_s5_bundle"] = merged[
        [
            "s1_modest_zone",
            "s2_clean_corridor",
            "s3_mature_decline",
            "s4_meaningful_washout",
            "s5_dry_base",
        ]
    ].all(axis=1)
    return merged


def load_market_quadrants(signal_dates: pd.Series) -> pd.DataFrame:
    dates = pd.DataFrame({"signal_date": pd.to_datetime(signal_dates).drop_duplicates()})
    connection = duckdb.connect()
    connection.register("signal_dates", dates)
    frame = connection.execute(
        f"""
        SELECT d.trade_date AS signal_date,
          median(d.ret20) AS market_median_ret20,
          median(d.ret60) AS market_median_ret60,
          count(*) AS market_state_n
        FROM read_parquet('{round1.mother.DAILY.as_posix()}') d
        JOIN signal_dates s ON d.trade_date=s.signal_date
        WHERE d.trade_date<=DATE '2020-12-31'
          AND d.hard_valid AND d.history_valid AND d.current_valid
          AND d.current_day_data_tradable AND d.market_rule_valid
          AND d.corporate_action_valid AND NOT d.corporate_action_blocking
          AND NOT d.is_st AND isfinite(d.ret20) AND isfinite(d.ret60)
        GROUP BY d.trade_date
        ORDER BY d.trade_date
        """
    ).fetch_df()
    connection.close()
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    if len(frame) != len(dates) or int(frame.market_state_n.min()) < 100:
        raise round1.RuleEvaluationError("causal market quadrant coverage failed")
    conditions = [
        frame.market_median_ret20.ge(0) & frame.market_median_ret60.ge(0),
        frame.market_median_ret20.lt(0) & frame.market_median_ret60.lt(0),
        frame.market_median_ret20.ge(0) & frame.market_median_ret60.lt(0),
    ]
    frame["market_quadrant"] = np.select(
        conditions,
        ["BROAD_BULL", "BROAD_BEAR", "RECOVERY_TRANSITION"],
        default="DETERIORATION_TRANSITION",
    )
    return frame


def summarize(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    part = frame.loc[frame.status.eq("COMPLETED")].copy()
    part["positive"] = part.net_return.gt(0)
    part["ge_4pct"] = part.net_return.ge(0.04)
    part["severe_loss"] = part.net_return.le(-0.10)
    part["target_hit"] = part.exit_reason.eq("FULL_ZONE_U")
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
        )
        .reset_index()
    )


def run() -> dict[str, Any]:
    if not SPEC.exists():
        raise round1.RuleEvaluationError("frozen semantic anatomy specification missing")
    candidates = round1.load_development_candidates()
    features = load_semantic_features(candidates)
    round1.mother.execution.write_parquet(features, FEATURES)
    baseline = pd.read_parquet(round1.EVENT_RESULTS)
    baseline = baseline.loc[baseline.profile.eq("BASELINE")].copy()
    baseline["signal_date"] = pd.to_datetime(baseline.signal_date)
    base = baseline.merge(
        features[
            [
                "event_id",
                "semantic_valid",
                "s1_modest_zone",
                "s2_clean_corridor",
                "s3_mature_decline",
                "s4_meaningful_washout",
                "s5_dry_base",
                "s1_to_s5_bundle",
            ]
        ],
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    profiles = {
        "BASELINE": base.semantic_valid,
        "S1_ONLY": base.s1_modest_zone,
        "S2_ONLY": base.s2_clean_corridor,
        "S3_ONLY": base.s3_mature_decline,
        "S4_ONLY": base.s4_meaningful_washout,
        "S5_ONLY": base.s5_dry_base,
        "S1_TO_S5_BUNDLE": base.s1_to_s5_bundle,
    }
    selected: list[pd.DataFrame] = []
    for profile, mask in profiles.items():
        part = base.loc[mask.fillna(False)].copy()
        part["profile"] = profile
        selected.append(part)
    events = pd.concat(selected, ignore_index=True)
    states = load_market_quadrants(events.signal_date)
    events = events.drop(columns=["market_state", "market_median_ret60", "market_state_n"], errors="ignore")
    events = events.merge(states, on="signal_date", how="left", validate="many_to_one")
    events["signal_year"] = events.signal_date.dt.year
    round1.mother.execution.write_parquet(events, PROFILE_EVENTS)
    annual = summarize(events, ["profile", "signal_year"])
    state = summarize(events, ["profile", "market_quadrant"])
    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL, index=False)
    state.to_csv(STATE, index=False)
    bundle = annual.loc[annual.profile.eq("S1_TO_S5_BUNDLE")]
    user_gate = bool(
        len(bundle) == 7
        and bundle.completed.ge(50).all()
        and bundle.mean_net.gt(0.04).all()
    )
    payload = {
        "experiment": EXPERIMENT,
        "stage": "V26_V27_INSPIRED_SEMANTIC_ANATOMY_V3",
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "features_sha256": sha256(FEATURES),
        "profile_events_sha256": sha256(PROFILE_EVENTS),
        "annual_sha256": sha256(ANNUAL),
        "state_sha256": sha256(STATE),
        "development_candidates": int(len(candidates)),
        "semantic_valid_candidates": int(features.semantic_valid.sum()),
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
            f"# {EXPERIMENT} — Semantic Anatomy V3",
            "",
            "Post-hoc development semantics inspired by V26/V27; not confirmation.",
            "",
            "## Annual profile results",
            "",
            annual.to_markdown(index=False, floatfmt=".4f"),
            "",
            "## Causal market quadrants",
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
