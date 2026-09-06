#!/usr/bin/env python3
"""Bull early-diffusion, first-support-test, reacceleration research lane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-EARLY-DIFFUSION-SUPPORT-REACCELERATION-V28"
EXT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_early_diffusion_support_reacceleration_v28"
)
MOTHER = EXT / "exploration/high_recall_candidates_v2.parquet"
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
CANDIDATES = EXT / "stage_a/candidates.parquet"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"
SELECTION = EXT / "stage_b/profile_selection.parquet"

PROFILES = {
    "T10_H10_NO_STOP": {"horizon": 10, "target": 0.10},
    "T15_H15_NO_STOP": {"horizon": 15, "target": 0.15},
}
DISCOVERY_YEARS = tuple(range(2014, 2021))
FORWARD_YEARS = (2021, 2022, 2023)
ALL_YEARS = tuple(range(2014, 2024))


class ResearchError(RuntimeError):
    """Fail-closed V28 research error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "An early or middle bull diffusion phase can finance a stock's first "
            "support test after a demand-backed 60-session ceiling break. If the "
            "pullback preserves the old ceiling and the ignition cost area on lower "
            "turnover, a later high-location, turnover-backed short-ceiling reclaim "
            "represents renewed demand after a supply test, not saturated market beta."
        ),
        "four_grouped_conditions": {
            "EARLY_MID_BULL_NOT_SATURATED": (
                "PIT market regime BULL; positive-ret20 breadth <=85%; five-session "
                "breadth change >=-5 percentage points"
            ),
            "INDUSTRY_PARTICIPATION": (
                "PIT industry median ret20 >0; positive-ret20 share >50%; cross-industry "
                "ret20 percentile >=30%; five-session breadth change >=-10 points"
            ),
            "FIRST_SUPPORT_TEST_AFTER_IGNITION": (
                "first frozen high-recall episode 2-30 sessions after a causal first "
                "60-session ceiling ignition; pullback drawdown 4-20%; old ceiling "
                "preserved within 5%; ignition-cost test between -12% and +6%; "
                "three-session pullback turnover <= prior ignition baseline; when "
                "multiple old ignitions map to one symbol/signal date, retain the "
                "most recent ignition because it is the current holder-cost episode"
            ),
            "DEMAND_REACCELERATION": (
                "completed close above prior-three-session high; +1.5% to +8% signal "
                "bar; close location >=65%; turnover >=1.1 times prior five-session mean"
            ),
        },
        "decision_clock": "completed daily signal close",
        "entry": "first legal daily open after signal within three market sessions",
        "profiles": PROFILES,
        "failure_stop": "none",
        "cost": 0.004,
        "profile_selection": {
            "years": list(DISCOVERY_YEARS),
            "minimum_completed": 350,
            "minimum_positive_years": 5,
            "maximum_mean_holding_sessions": 15,
            "order": [
                "median annual mean net return",
                "pooled mean net return",
                "lower severe-loss10",
                "shorter horizon",
            ],
        },
        "chronology": {
            "2014_2020": "profile selection and mechanism development",
            "2021_2023": "predetermined later chronological check, not used in selection",
            "post_2023_signal_or_feature": False,
        },
        "portfolio": v1.contract_value()["portfolio"],
    }


def _read_candidates() -> pd.DataFrame:
    frame = v1.read_parquet_duckdb(MOTHER)
    for column in (
        "trade_date",
        "signal_date",
        "ignition_date",
        "available_at",
        "decision_at",
        "market_latest_source",
        "industry_latest_source",
        "feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    mask = (
        frame.market_regime.eq("BULL")
        & frame.market_positive_ret20_share.le(0.85)
        & frame.market_breadth_delta5.ge(-0.05)
        & frame.industry_median_ret20.gt(0)
        & frame.industry_positive_ret20_share.gt(0.50)
        & frame.industry_ret20_percentile.ge(0.30)
        & frame.industry_breadth_delta5.ge(-0.10)
    )
    selected = frame.loc[mask].copy()
    selected = (
        selected.sort_values(
            ["symbol", "signal_date", "ignition_date", "ignition_id"],
            ascending=[True, True, False, True],
            kind="mergesort",
        )
        .drop_duplicates(["symbol", "signal_date"], keep="first")
        .copy()
    )
    selected["turnover_expansion"] = selected.signal_turnover_expansion
    selected["admission_lane"] = "EARLY_DIFFUSION_FIRST_SUPPORT_REACCELERATION"
    selected = selected.sort_values(["signal_date", "symbol", "event_id"]).reset_index(drop=True)
    return selected


def _candidate_audit(frame: pd.DataFrame) -> dict[str, int]:
    feature_latest = frame[
        [
            "available_at",
            "market_latest_source",
            "industry_latest_source",
            "feature_latest_timestamp",
        ]
    ].max(axis=1)
    return {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(feature_latest.gt(frame.decision_at).sum()),
        "signal_after_2023_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "hard_invalid_count": int((~frame.hard_valid.fillna(False)).sum()),
        "corporate_action_invalid_count": int(
            ((~frame.corporate_action_valid.fillna(False)) | frame.corporate_action_blocking.fillna(True)).sum()
        ),
        "invalid_industry_count": int((~frame.industry_valid.fillna(False)).sum()),
    }


def run_stage_a() -> dict[str, Any]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_ECONOMIC_CONTRACT_FROZEN",
            "mother_sha256": v1.sha256(MOTHER),
            "contract_sha256": v1.sha256(CONTRACT),
            "runner_sha256": v1.sha256(Path(__file__)),
            "execution_dependency_sha256": v1.sha256(Path(v2.__file__)),
            "portfolio_dependency_sha256": v1.sha256(Path(v1.__file__)),
        },
    )
    frame = _read_candidates()
    audit = _candidate_audit(frame)
    if any(audit.values()):
        raise ResearchError(f"Stage-A candidate audit failed: {audit}")
    v1.write_parquet(frame, CANDIDATES)
    reproduced = _read_candidates()
    if not frame.equals(reproduced):
        raise ResearchError("deterministic candidate reconstruction failed")
    freeze = {
        "experiment": EXPERIMENT,
        "status": "STAGE_A_FROZEN_BEFORE_OUTCOME_OPEN",
        "source_rows": 5050,
        "candidate_rows": len(frame),
        "annual_signal_counts": {
            str(year): int(frame.signal_date.dt.year.eq(year).sum()) for year in ALL_YEARS
        },
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "mother_sha256": v1.sha256(MOTHER),
        "candidates_sha256": v1.sha256(CANDIDATES),
        "audit": audit,
        "outcomes_opened": False,
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def _verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    expected = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "mother_sha256": v1.sha256(MOTHER),
        "candidates_sha256": v1.sha256(CANDIDATES),
    }
    drift = {key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value}
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def _metrics(frame: pd.DataFrame, target: float | None = None) -> dict[str, Any]:
    part = frame.loc[frame.status.eq("COMPLETED")].copy()
    if part.empty:
        return {
            "completed_trades": 0,
            "mean_net": None,
            "median_net": None,
            "win_rate": None,
            "severe_loss10": None,
            "target_hit_rate": None,
            "mean_holding_sessions": None,
            "median_holding_sessions": None,
        }
    target_name = None if target is None else f"TARGET_{int(target * 100)}"
    return {
        "completed_trades": len(part),
        "mean_net": float(part.net_return.mean()),
        "median_net": float(part.net_return.median()),
        "win_rate": float(part.net_return.gt(0).mean()),
        "severe_loss10": float(part.net_return.le(-0.10).mean()),
        "target_hit_rate": float(part.exit_reason.eq(target_name).mean()) if target_name else None,
        "mean_holding_sessions": float(part.holding_sessions.mean()),
        "median_holding_sessions": float(part.holding_sessions.median()),
    }


def _profile_table(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for profile, params in PROFILES.items():
        part = outcomes.loc[
            outcomes.profile.eq(profile)
            & outcomes.signal_date.dt.year.isin(DISCOVERY_YEARS)
        ]
        annual = {
            str(year): _metrics(
                part.loc[part.signal_date.dt.year.eq(year)], params["target"]
            )
            for year in DISCOVERY_YEARS
        }
        means = [value["mean_net"] for value in annual.values() if value["mean_net"] is not None]
        rows.append(
            {
                "profile": profile,
                **_metrics(part, params["target"]),
                "positive_years": sum(value > 0 for value in means),
                "median_annual_mean_net": float(np.median(means)),
                "annual_json": json.dumps(annual, sort_keys=True),
            }
        )
    return pd.DataFrame(rows)


def _select_profile(table: pd.DataFrame) -> pd.Series:
    eligible = table.loc[
        table.completed_trades.ge(350)
        & table.positive_years.ge(5)
        & table.mean_holding_sessions.lt(15)
    ].copy()
    if eligible.empty:
        raise ResearchError("no frozen profile meets predeclared Development support")
    eligible["profile_order"] = eligible.profile.map(
        {"T10_H10_NO_STOP": 0, "T15_H15_NO_STOP": 1}
    )
    eligible = eligible.sort_values(
        ["median_annual_mean_net", "mean_net", "severe_loss10", "profile_order"],
        ascending=[False, False, True, True],
        kind="mergesort",
    )
    return eligible.iloc[0]


def run_stage_b() -> dict[str, Any]:
    freeze = _verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at"):
        candidates[column] = pd.to_datetime(candidates[column])
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES = PROFILES
        v2.OUTCOMES = OUTCOMES
        outcomes, execution_audit = v2.build_outcomes(candidates)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    table = _profile_table(outcomes)
    v1.write_parquet(table, SELECTION)
    selected = _select_profile(table)
    profile = str(selected.profile)
    params = PROFILES[profile]
    features = candidates[
        [
            "event_id",
            "causal_industry",
            "industry_positive_ret20_share",
            "stock_minus_industry_ret20",
            "turnover_expansion",
        ]
    ]
    trades = outcomes.loc[outcomes.profile.eq(profile)].merge(
        features, on="event_id", how="left", validate="one_to_one"
    )
    symbols = trades.loc[trades.status.eq("COMPLETED"), "symbol"].astype(str).unique().tolist()
    daily = v1.load_trade_daily(symbols)
    old_paths = v1.ACCEPTED, v1.SKIPPED, v1.NAV
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = ACCEPTED, SKIPPED, NAV
        accepted, skipped, _nav, portfolio = v1.replay_portfolio(trades, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    annual = {
        str(year): _metrics(
            accepted.loc[accepted.signal_date.dt.year.eq(year)], params["target"]
        )
        for year in ALL_YEARS
    }
    discovery = _metrics(
        accepted.loc[accepted.signal_date.dt.year.isin(DISCOVERY_YEARS)], params["target"]
    )
    forward = _metrics(
        accepted.loc[accepted.signal_date.dt.year.isin(FORWARD_YEARS)], params["target"]
    )
    full = _metrics(accepted, params["target"])
    board = {
        name: _metrics(part, params["target"])
        for name, part in accepted.groupby("sleeve", sort=True)
    }
    concentration = v1.concentration_metrics(accepted)
    concentration["signal_date_equal_mean_net"] = float(
        accepted.groupby(accepted.signal_date.dt.normalize()).net_return.mean().mean()
    )
    later_means = [annual[str(year)]["mean_net"] for year in FORWARD_YEARS]
    gate = {
        "accepted_completed_trades_gt_500": len(accepted) > 500,
        "accepted_trades_per_year_gt_50": len(accepted) / 10 > 50,
        "mean_net_gt_5pct": full["mean_net"] is not None and full["mean_net"] > 0.05,
        "mean_holding_lt_15": full["mean_holding_sessions"] is not None and full["mean_holding_sessions"] < 15,
        "all_2021_2023_means_positive": all(value is not None and value > 0 for value in later_means),
        "both_boards_positive_mean": set(board) == {"MAIN", "CHINEXT"} and all(value["mean_net"] > 0 for value in board.values()),
        "mean_excluding_best_five_signal_dates_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top_five_signal_date_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"] <= 0.25,
    }
    audit = {
        **execution_audit,
        **_candidate_audit(candidates),
        "signal_bar_fill_count": int((accepted.entry_date <= accepted.signal_date).sum()),
        "t1_same_day_exit_count": int((accepted.exit_cal_idx <= accepted.entry_cal_idx).sum()),
        "negative_cash_count": portfolio["negative_cash_count"],
        "max_k_violation_count": portfolio["max_k_violation_count"],
    }
    if any(audit.values()):
        raise ResearchError(f"final audit failed: {audit}")
    result = {
        "experiment": EXPERIMENT,
        "contract_sha256": freeze["contract_sha256"],
        "selected_profile": profile,
        "profile_selection_2014_2020": table.to_dict(orient="records"),
        "source_signals": len(candidates),
        "capacity_accepted_completed_trades": len(accepted),
        "capacity_skips": len(skipped),
        "average_trades_per_year": len(accepted) / 10,
        "development_2014_2020": discovery,
        "later_chronology_2021_2023": forward,
        "full_2014_2023": full,
        "annual": annual,
        "board": board,
        "portfolio": portfolio,
        "concentration": concentration,
        "gate": gate,
        "audit": audit,
        "verdict": "V28_TARGET_MET" if all(gate.values()) else "V28_MECHANISM_FAILS_TARGET",
        "hashes": {
            "candidates": v1.sha256(CANDIDATES),
            "outcomes": v1.sha256(OUTCOMES),
            "accepted": v1.sha256(ACCEPTED),
            "skipped": v1.sha256(SKIPPED),
            "nav": v1.sha256(NAV),
            "selection": v1.sha256(SELECTION),
        },
    }
    v1.write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if args.stage_a:
        print(json.dumps(run_stage_a(), indent=2, default=str))
    elif args.stage_b:
        print(json.dumps(run_stage_b(), indent=2, default=str))
    else:
        parser.error("choose --stage-a or --stage-b")


if __name__ == "__main__":
    main()
