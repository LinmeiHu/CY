#!/usr/bin/env python3
# ruff: noqa: E501
"""Freeze and replay the simple narrow-gap, low-touch-corridor V26 candidate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_first_reversal_v13 as first_reversal,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as replay,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-CLEAN-CORRIDOR-V26"
START_HEAD = "41fe351e31"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_clean_corridor_v26"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

MAX_GAP_WIDTH_PCT = 0.03
MAX_PRE_GAP_CORRIDOR_TOUCH_SESSIONS = 10
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = replay.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = replay.DIAGNOSTIC_YEARS
ALL_YEARS = DEVELOPMENT_YEARS + DIAGNOSTIC_YEARS


class V26Error(RuntimeError):
    """Fail-closed V26 research error."""


def sha256(path: Path) -> str:
    return replay.sha256(path)


def write_json(path: Path, value: Any) -> None:
    replay.write_json(path, value)


def source_entries_path(label: str) -> Path:
    return replay.source_paths(label)["entries"]


def selected_entries_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d30_selected_entries.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d30"


@contextmanager
def v26_runtime() -> Iterator[None]:
    old_root = replay.EXT_ROOT
    try:
        replay.EXT_ROOT = EXT_ROOT
        yield
    finally:
        replay.EXT_ROOT = old_root


def clean_corridor_mask(frame: pd.DataFrame) -> pd.Series:
    required = frame[["gap_width_pct", "pre_gap_corridor_touch_sessions"]]
    return (
        required.notna().all(axis=1)
        & frame.gap_width_pct.le(MAX_GAP_WIDTH_PCT)
        & frame.pre_gap_corridor_touch_sessions.le(
            MAX_PRE_GAP_CORRIDOR_TOUCH_SESSIONS
        )
    )


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "RETROSPECTIVE_FULL_OBSERVED_CANDIDATE_NOT_EXTERNAL_VALIDATION",
        "economic_hypothesis": (
            "A tradable below-gap rebound requires a modest price discontinuity rather "
            "than an extreme structural break, and little historical occupancy in the "
            "immediate gap corridor. Gap width does not define the profit distance: the "
            "unchanged target remains a fraction of the entry-to-L rebound path."
        ),
        "source_strategy": first_reversal.EXPERIMENT,
        "source_trigger": "PRIOR_HIGH_REVERSAL",
        "observed_period": ["2017-01-01", "2023-12-31"],
        "simple_admission": {
            "conditions": 2,
            "gap_width_pct": "source minimum 1%; maximum 3%",
            "pre_gap_corridor_touch_sessions": "<=10 of exact 120 completed sessions",
            "corridor": "[L-0.5W, U+0.5W]",
            "known_time": "gap-formation close, before reversal signal and entry",
            "missing_policy": "fail closed",
        },
        "unchanged_v13": {
            "true_gap": "High_t < Low_t_minus_1",
            "pre_gap_history": "exact 120 completed sessions with exact 241-minute VAP history",
            "inside_touch_sessions_max": 12,
            "inside_and_corridor_density_relative_local_max": 1.0,
            "pre_gap_return_20d_max": 0.0,
            "maximum_depth_below_L_min": 0.10,
            "signal_depth_below_L_min": 0.05,
            "trigger": "first completed daily close > previous completed daily high",
            "entry": "first legal buyable 1-minute open after signal",
            "minimum_net_headroom_to_L": 0.05,
            "target": "A67 below L",
            "failure_stop": "NONE",
            "time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "T1_limits_suspensions_and_QD010": True,
        },
        "goal_contract": {
            "combined_2017_2023_accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "combined_mean_net_min": 0.03,
            "every_signal_year_trade_mean_positive": True,
            "combined_median_net_positive": True,
            "combined_severe10_max": 0.15,
            "every_signal_year_portfolio_return_positive": True,
        },
        "governance": {
            "rule_discovered_after_2022_2023_were_observed": True,
            "no_claim_of_external_validation": True,
            "no_target_horizon_entry_cost_or_execution_change": True,
            "post_2023_scope": "management/completion of pre-2024 trades only",
            "no_post_2023_signals_features_or_selection": True,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "TWO_CONDITION_RETROSPECTIVE_SEMANTIC_CANDIDATE",
            "frequency_definition": "combined accepted trades in 2017-2023 divided by seven; strictly greater than 50",
            "disclosure": "Both 3% width and 10-session corridor limits were promoted after 2022-2023 outcomes had already been observed in predecessor lanes.",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    paths: dict[str, Path] = {
        "v13_runner": Path(first_reversal.__file__),
        "v13_contract": first_reversal.CONTRACT,
        "v13_stage_a_freeze": first_reversal.STAGE_A_FREEZE,
        "replay_helper": Path(replay.__file__),
    }
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        paths[f"{label.lower()}_entries"] = replay.source_paths(label)["entries"]
        paths[f"{label.lower()}_outcomes"] = replay.source_paths(label)["outcomes"]
        paths[f"{label.lower()}_daily"] = replay.source_paths(label)["outcome_daily"]
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise V26Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in paths.items()}


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(source_entries_path(label))
    for column in ("gap_date", "signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    if entries.gap_id.duplicated().any():
        raise V26Error(f"{label} duplicate source gap identity")
    if entries[["gap_width_pct", "pre_gap_corridor_touch_sessions"]].isna().any().any():
        raise V26Error(f"{label} missing required semantic field")
    selected = entries.loc[clean_corridor_mask(entries)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(years)].copy()
    selected["v26_gap_width_gate"] = True
    selected["v26_low_corridor_touch_gate"] = True
    selected["semantic_feature_latest_timestamp"] = selected.gap_date + pd.Timedelta(hours=15)
    selected["feature_uses_post_signal_information"] = selected.semantic_feature_latest_timestamp.gt(selected.signal_time)
    if selected.feature_uses_post_signal_information.any():
        raise V26Error(f"{label} causal timing failure")
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    replay.repair.write_parquet(selected, selected_entries_path(label))
    executable = selected.entry_status.eq("EXECUTABLE_ENTRY")
    annual = selected.loc[executable].assign(_year=selected.loc[executable, "signal_date"].dt.year).groupby("_year").size()
    return {
        "source_entries": len(entries),
        "selected_signals": len(selected),
        "executable_entries": int(executable.sum()),
        "executable_by_year": {str(year): int(annual.get(year, 0)) for year in years},
        "feature_uses_post_signal_information_count": int(selected.feature_uses_post_signal_information.sum()),
        "selected_entries_sha256": sha256(selected_entries_path(label)),
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods = {
        "DEVELOPMENT": build_period_stage_a("DEVELOPMENT", DEVELOPMENT_YEARS),
        "POST_OBSERVATION_DIAGNOSTIC": build_period_stage_a("POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS),
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "TWO_CONDITION_CAUSAL_IDENTITY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "periods": periods,
        "return_analysis_run": "NO",
        "strategy_backtest_run": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V26Error("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC), "runner_sha256": sha256(Path(__file__))}
    drift = {key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value}
    current_sources = source_hashes()
    if current_sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), current_sources]
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        current = sha256(selected_entries_path(label))
        expected = freeze["periods"][label]["selected_entries_sha256"]
        if current != expected:
            drift[f"{label}_selected_entries"] = [expected, current]
    if drift:
        raise V26Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_period(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    with v26_runtime():
        item = replay.run_lane(label, years)
    accepted = pd.read_parquet(lane_root(label) / "portfolio_accepted.parquet")
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    wins = accepted.assign(_year=accepted.entry_date.dt.year).groupby("_year").net_return.apply(lambda values: float(values.gt(0).mean()))
    for year, value in wins.items():
        item["accepted_trade_yearly"][str(int(year))]["win"] = float(value)
    item["rule"] = "GAP_WIDTH_1_TO_3PCT_AND_PRE_GAP_CORRIDOR_TOUCH_LE10"
    return item


def combine_results(development: dict[str, Any], diagnostic: dict[str, Any]) -> dict[str, Any]:
    frames: list[pd.DataFrame] = []
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        frame = pd.read_parquet(lane_root(label) / "portfolio_accepted.parquet")
        frame["entry_date"] = pd.to_datetime(frame.entry_date)
        frames.append(frame)
    accepted = pd.concat(frames, ignore_index=True).sort_values(["entry_date", "symbol", "gap_id"], kind="mergesort")
    yearly = accepted.assign(_year=accepted.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median", win=lambda values: float(values.gt(0).mean())
    )
    yearly_payload = {
        str(int(index)): {"trades": int(row.trades), "mean_net": float(row.mean_net), "median_net": float(row.median_net), "win": float(row.win)}
        for index, row in yearly.iterrows()
    }
    annual_returns: dict[str, float] = {}
    for item, years in ((development, DEVELOPMENT_YEARS), (diagnostic, DIAGNOSTIC_YEARS)):
        source = item["portfolio"]["COMBINED"]["annual_returns"]
        annual_returns.update({str(year): float(source.get(str(year), 0.0)) for year in years})
    per_date = accepted.assign(_date=accepted.entry_date.dt.normalize()).groupby("_date").net_return.mean()
    return {
        "accepted_trades": len(accepted),
        "accepted_trades_per_year": len(accepted) / len(ALL_YEARS),
        "mean_net": float(accepted.net_return.mean()),
        "median_net": float(accepted.net_return.median()),
        "win": float(accepted.net_return.gt(0).mean()),
        "severe10": float(accepted.net_return.le(-0.10).mean()),
        "attack_date_equal_mean": float(per_date.mean()),
        "yearly": yearly_payload,
        "portfolio_annual_returns": annual_returns,
        "positive_trade_mean_years": int(sum(values["mean_net"] > 0 for values in yearly_payload.values())),
        "positive_portfolio_years": int(sum(value > 0 for value in annual_returns.values())),
    }


def goal_checks(combined: dict[str, Any]) -> dict[str, bool]:
    yearly = combined["yearly"]
    returns = combined["portfolio_annual_returns"]
    return {
        "accepted_trades_per_year_gt_50": combined["accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR,
        "combined_mean_net_ge_3pct": combined["mean_net"] >= 0.03,
        "combined_median_net_positive": combined["median_net"] > 0,
        "combined_severe10_le_15pct": combined["severe10"] <= 0.15,
        "every_2017_2023_trade_mean_positive": all(float(yearly.get(str(year), {}).get("mean_net", -1.0)) > 0 for year in ALL_YEARS),
        "every_2017_2023_portfolio_return_positive": all(float(returns.get(str(year), 0.0)) > 0 for year in ALL_YEARS),
        "attack_date_equal_mean_positive": combined["attack_date_equal_mean"] > 0,
    }


def run_all() -> dict[str, Any]:
    verification = verify_stage_a()
    development = run_period("DEVELOPMENT", DEVELOPMENT_YEARS)
    diagnostic = run_period("POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS)
    combined = combine_results(development, diagnostic)
    checks = goal_checks(combined)
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "development": development,
        "post_observation_diagnostic": diagnostic,
        "combined_2017_2023": combined,
        "goal_checks": checks,
        "verdict": "V26_RETROSPECTIVE_CANDIDATE_MEETS_NUMERIC_GOAL" if all(checks.values()) else "V26_RETROSPECTIVE_CANDIDATE_FAILS_NUMERIC_GOAL",
        "scientific_status": "FULL_PERIOD_OBSERVED_HYPOTHESIS_REQUIRES_FUTURE_SEALED_CHALLENGE",
        "post_2023_signal_or_selection_data_opened": "NO",
        "repository_2024_plus_data_opened": "AUTHORIZED_PRE_2024_TRADE_MANAGEMENT_AND_COMPLETION_ONLY",
    }
    write_json(RESULT, result)
    return result


def pct(value: Any) -> str:
    return f"{float(value):.2%}"


def render_report() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    combined = result["combined_2017_2023"]
    lines = [
        f"# {EXPERIMENT}", "", f"`{result['verdict']}`", "",
        "## Simple candidate", "",
        "1. Frozen V13 prior-high reversal signal and execution.",
        "2. True-gap width is at least the V13 source minimum of 1% and no more than 3%.",
        "3. In the exact 120 completed sessions before gap formation, no more than 10 sessions touch `[L-0.5W, U+0.5W]`.",
        "4. Entry, A67 target below L, H20, 40 bp costs, K80, T+1, limits, suspensions and QD-010 are unchanged.",
        "", "Gap width does not cap the rebound target. The target is 67% of the entry-to-L distance, so the rule removes extreme discontinuities without shrinking the chosen payoff path.",
        "", "## Combined observed evidence", "",
        f"Accepted {combined['accepted_trades']} ({combined['accepted_trades_per_year']:.1f}/year); mean {pct(combined['mean_net'])}; median {pct(combined['median_net'])}; win {pct(combined['win'])}; severe10 {pct(combined['severe10'])}.",
        "", "|Year|Trades|Mean|Median|Win|Portfolio return|", "|---|---:|---:|---:|---:|---:|",
    ]
    for year in ALL_YEARS:
        item = combined["yearly"][str(year)]
        lines.append(f"|{year}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|{pct(combined['portfolio_annual_returns'][str(year)])}|")
    lines += [
        "", "## Scientific limitation", "",
        "This is a retrospective full-observed candidate: 2022-2023 had already been observed before the two-condition rule was promoted. The result is reproducible but is not external validation. It requires semantic chart review and a separately sealed future challenge before a deployment claim.",
        "", "No 2024+ signal, feature or selection data were opened. Later data were used only to complete pre-2024 trades.", "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("stage-a", "verify-stage-a", "run", "report"))
    args = parser.parse_args()
    if args.stage == "stage-a":
        payload = run_stage_a()
    elif args.stage == "verify-stage-a":
        payload = verify_stage_a()
    elif args.stage == "run":
        payload = run_all()
    else:
        render_report()
        payload = {"report": str(REPORT)}
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
