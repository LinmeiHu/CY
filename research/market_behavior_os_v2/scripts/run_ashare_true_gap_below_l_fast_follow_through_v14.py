#!/usr/bin/env python3
# ruff: noqa: E501
"""Test whether a true below-gap reversal must follow through quickly."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_first_reversal_v13 as first_reversal,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-FAST-FOLLOW-THROUGH-V14"
START_HEAD = "bfc5a802e6"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_fast_follow_through_v14"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

HORIZONS = (5, 10, 15, 20)
TARGET_FRACTION = 0.67
PORTFOLIO_K = 80
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)


class V14Error(RuntimeError):
    """Fail-closed V14 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def source_root(label: str) -> Path:
    return (
        first_reversal.trigger_root("PRIOR_HIGH_REVERSAL") / label.lower()
    )


def source_paths(label: str) -> dict[str, Path]:
    root = source_root(label)
    return {
        "root": root,
        "entries": root / "entries.parquet",
        "actions": root / "qd010_actions.parquet",
        "outcome_daily": root / "outcome_daily.parquet",
        "outcome_minutes": root / "outcome_minutes.parquet",
        "sell_opens": root / "sell_opens.parquet",
    }


def horizon_root(label: str, horizon: int) -> Path:
    return EXT_ROOT / label.lower() / f"h{horizon:02d}"


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A genuine first close-above-prior-high reversal below a clean true gap "
            "should continue promptly. If the A67 target remains unresolved for many "
            "sessions, the reversal is more likely being absorbed by persistent supply; "
            "a fixed earlier time stop may prevent slow deterioration."
        ),
        "source_strategy": first_reversal.EXPERIMENT,
        "source_trigger": "PRIOR_HIGH_REVERSAL",
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "fixed_horizon_family": list(HORIZONS),
        "time_stop_execution": (
            "after completed close information at entry_cal_idx + H, exit at next "
            "legal sellable 1-minute open; A-share T+1 remains binding"
        ),
        "selector": {
            "eligibility": {
                "accepted_trades_per_year_min": MIN_ACCEPTED_TRADES_PER_YEAR,
                "frequency_has_no_upper_cap": True,
                "portfolio_mean_net_min": 0.03,
                "portfolio_median_net_positive": True,
                "portfolio_severe10_max": 0.15,
                "positive_trade_mean_years_min": 4,
                "positive_portfolio_years_min": 4,
                "attack_date_equal_mean_positive": True,
            },
            "order": [
                "higher portfolio mean net",
                "higher portfolio median net",
                "lower severe_loss10",
                "shorter horizon",
            ],
        },
        "unchanged": {
            "signal_population_and_features": True,
            "trigger": "first completed daily close above previous completed daily high",
            "entry": True,
            "minimum_net_headroom_to_L": 0.05,
            "target": "entry + 0.67*(L-entry), strictly below L",
            "failure_stop": "NONE",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "collision_rank": True,
            "T1_limits_suspensions_and_QD010": True,
        },
        "governance": {
            "h20_result_already_known_from_v13": True,
            "h5_h10_h15_not_computed_before_freeze": True,
            "diagnostic_opened_only_for_development_selected_horizon": True,
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
            "status": "OUTCOME_BLIND_FIXED_FAST_FOLLOW_THROUGH_HORIZON_FAMILY",
            "frequency_goal": "at least 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "H5/H10/H15/H20 and the selector were frozen after V13 failed its "
                "post-observation diagnostic and before H5/H10/H15 outcomes were computed."
            ),
            "diagnostic_disclosure": (
                "Only the Development-selected horizon may be replayed on 2022-2023; "
                "that broader period is post-observation evidence."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v13_contract": first_reversal.CONTRACT,
        "v13_stage_a_freeze": first_reversal.STAGE_A_FREEZE,
        "v13_development_result": first_reversal.DEVELOPMENT_RESULT,
        "v13_diagnostic_freeze": first_reversal.DIAGNOSTIC_FREEZE,
        "v13_diagnostic_result": first_reversal.DIAGNOSTIC_RESULT,
    }
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        for name, path in source_paths(label).items():
            if name != "root":
                values[f"{label.lower()}_{name}"] = path
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V14Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_HORIZON_FAMILY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "h5_h10_h15_development_outcomes_opened": "NO",
        "selected_horizon_diagnostic_outcomes_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V14Error("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    identities = source_hashes()
    if identities != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), identities]
    if drift:
        raise V14Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": identities}


def load_sources(label: str) -> tuple[pd.DataFrame, ...]:
    paths = source_paths(label)
    entries = pd.read_parquet(paths["entries"])
    actions = pd.read_parquet(paths["actions"])
    daily = pd.read_parquet(paths["outcome_daily"])
    minutes = pd.read_parquet(paths["outcome_minutes"])
    sells = pd.read_parquet(paths["sell_opens"])
    for frame, columns in (
        (entries, ("signal_time", "signal_date", "entry_time", "entry_date")),
        (actions, ("known_date", "effective_date")),
        (daily, ("trade_date",)),
        (minutes, ("trade_date", "bar_end_time")),
        (sells, ("trade_date", "bar_end_time")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    return entries, actions, daily, minutes, sells


def run_horizon(
    label: str, horizon: int, years: tuple[int, ...]
) -> dict[str, Any]:
    entries, actions, daily, minutes, sells = load_sources(label)
    root = horizon_root(label, horizon)
    root.mkdir(parents=True, exist_ok=True)
    old_target = repair.TARGET_FRACTION
    old_horizon = repair.TIME_STOP
    old_k = repair.v1.PORTFOLIO_K
    try:
        repair.TARGET_FRACTION = TARGET_FRACTION
        repair.TIME_STOP = horizon
        repair.v1.PORTFOLIO_K = PORTFOLIO_K
        outcomes, outcome_audit = repair.build_outcomes(
            entries,
            daily,
            minutes,
            sells,
            actions,
            first_reversal.PERIODS[label][1],
            {"outcomes": root / "outcomes.parquet"},
        )
        max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
        repair.v1.configure_external(root, max_exit)
        replay_years = tuple(range(min(years), int(max_exit.year) + 1))
        portfolio = repair.v1.run_portfolio(
            outcomes,
            daily.loc[daily.trade_date.le(max_exit)].copy(),
            replay_years,
        )
    finally:
        repair.TARGET_FRACTION = old_target
        repair.TIME_STOP = old_horizon
        repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    for frame, column in ((accepted, "entry_date"), (outcomes, "entry_date")):
        frame[column] = pd.to_datetime(frame[column])
    yearly = (
        accepted.assign(_year=accepted.entry_date.dt.year)
        .groupby("_year")
        .net_return.agg(trades="size", mean_net="mean", median_net="median")
    )
    yearly_payload = {
        str(int(index)): {
            "trades": int(row.trades),
            "mean_net": float(row.mean_net),
            "median_net": float(row.median_net),
        }
        for index, row in yearly.iterrows()
    }
    combined = portfolio["COMBINED"]
    return {
        "horizon": horizon,
        "source_executable_trades": len(outcomes),
        "event_metrics": repair.v1.trade_metrics(outcomes),
        "portfolio": portfolio,
        "portfolio_accepted_trades": len(accepted),
        "portfolio_accepted_trades_per_year": len(accepted) / len(years),
        "portfolio_mean_net": float(combined["mean_net"]),
        "portfolio_median_net": float(combined["median_net"]),
        "portfolio_win": float(combined["win"]),
        "portfolio_severe10": float(combined["severe10"]),
        "portfolio_cagr": float(combined["cagr"]),
        "portfolio_max_drawdown": float(combined["max_drawdown"]),
        "portfolio_sharpe": float(combined["sharpe"]),
        "accepted_trade_yearly": yearly_payload,
        "positive_trade_mean_years": int(
            sum(
                float(yearly_payload.get(str(year), {}).get("mean_net", 0.0)) > 0
                for year in years
            )
        ),
        "positive_portfolio_years": int(
            sum(
                float(combined["annual_returns"].get(str(year), 0.0)) > 0
                for year in years
            )
        ),
        "attack_date_equal_mean": float(
            outcomes.assign(_date=outcomes.entry_date.dt.normalize())
            .groupby("_date")
            .net_return.mean()
            .mean()
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(
            outcomes.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
        ),
        "outcome_audit": outcome_audit,
        "hashes": {
            "outcomes": sha256(root / "outcomes.parquet"),
            "portfolio_accepted": sha256(root / "portfolio_accepted.parquet"),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
        },
    }


def candidate_eligible(item: dict[str, Any]) -> bool:
    return bool(
        item["portfolio_accepted_trades_per_year"] >= MIN_ACCEPTED_TRADES_PER_YEAR
        and item["portfolio_mean_net"] >= 0.03
        and item["portfolio_median_net"] > 0
        and item["portfolio_severe10"] <= 0.15
        and item["positive_trade_mean_years"] >= 4
        and item["positive_portfolio_years"] >= 4
        and item["attack_date_equal_mean"] > 0
        and item["post_2023_signal_count"] == 0
    )


def select_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates.values() if candidate_eligible(item)]
    if not eligible:
        raise V14Error("no Development horizon passes selector")
    return sorted(
        eligible,
        key=lambda item: (
            -item["portfolio_mean_net"],
            -item["portfolio_median_net"],
            item["portfolio_severe10"],
            item["horizon"],
        ),
    )[0]


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    candidates = {
        f"H{horizon}": run_horizon("DEVELOPMENT", horizon, DEVELOPMENT_YEARS)
        for horizon in HORIZONS
    }
    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "candidate_results": candidates,
        "development_horizon_outcomes_opened": "YES",
        "diagnostic_selected_horizon_outcomes_opened": "NO",
    }
    try:
        selected = select_candidate(candidates)
    except V14Error:
        result.update(
            {
                "selector_passed": False,
                "selected_horizon": None,
                "verdict": "FAST_FOLLOW_THROUGH_DEVELOPMENT_FAILED",
            }
        )
        write_json(DEVELOPMENT_RESULT, result)
        return result
    result.update(
        {
            "selector_passed": True,
            "selected_horizon": selected["horizon"],
            "verdict": "FAST_FOLLOW_THROUGH_DEVELOPMENT_CANDIDATE",
        }
    )
    write_json(DEVELOPMENT_RESULT, result)
    write_json(
        DIAGNOSTIC_FREEZE,
        {
            "experiment": EXPERIMENT,
            "stage": "DIAGNOSTIC_FREEZE_BEFORE_SELECTED_HORIZON_REPLAY",
            "contract_sha256": sha256(CONTRACT),
            "spec_sha256": sha256(SPEC),
            "runner_sha256": sha256(Path(__file__)),
            "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
            "development_result_sha256": sha256(DEVELOPMENT_RESULT),
            "selected_horizon": selected["horizon"],
            "target_fraction": TARGET_FRACTION,
            "k_per_board_sleeve": PORTFOLIO_K,
            "diagnostic_selected_horizon_outcomes_opened": "NO",
        },
    )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V14Error("Development produced no diagnostic freeze")
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    if drift:
        raise V14Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def diagnostic_checks(item: dict[str, Any]) -> dict[str, bool]:
    yearly = item["accepted_trade_yearly"]
    return {
        "accepted_trades_per_year_ge_50": (
            item["portfolio_accepted_trades_per_year"] >= MIN_ACCEPTED_TRADES_PER_YEAR
        ),
        "portfolio_mean_net_ge_3pct": item["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": item["portfolio_median_net"] > 0,
        "severe10_le_15pct": item["portfolio_severe10"] <= 0.15,
        "both_year_trade_means_positive": all(
            float(yearly.get(str(year), {}).get("mean_net", -1.0)) > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "both_year_portfolio_returns_positive": all(
            float(item["portfolio"]["COMBINED"]["annual_returns"].get(str(year), -1.0))
            > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "post_2023_signal_count_zero": item["post_2023_signal_count"] == 0,
    }


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    horizon = int(freeze["selected_horizon"])
    diagnostic = run_horizon(
        "POST_OBSERVATION_DIAGNOSTIC", horizon, DIAGNOSTIC_YEARS
    )
    checks = diagnostic_checks(diagnostic)
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_horizon": horizon,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": (
            "FAST_FOLLOW_THROUGH_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "FAST_FOLLOW_THROUGH_POST_OBSERVATION_FAILED"
        ),
        "scientific_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_ONLY",
        "post_2023_signal_or_selection_data_opened": "NO",
        "repository_2024_plus_data_opened": (
            "AUTHORIZED_PRE_2024_TRADE_MANAGEMENT_AND_COMPLETION_ONLY"
        ),
    }
    write_json(DIAGNOSTIC_RESULT, result)
    return result


def pct(value: Any) -> str:
    return f"{float(value):.2%}"


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Horizon|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon in HORIZONS:
        item = development["candidate_results"][f"H{horizon}"]
        lines.append(
            f"|H{horizon}|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|"
            f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
            f"{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|"
            f"{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|"
        )
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        item = result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"Selected horizon: H{result['selected_horizon']}.",
            f"Verdict: `{result['verdict']}`.",
            f"Accepted/year: {item['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(item['portfolio_mean_net'])}; median: {pct(item['portfolio_median_net'])}; severe10: {pct(item['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "The selected 2022-2023 horizon outcome was not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Frequency means at least 50 accepted trades/year; there is no upper cap.",
        "- Only the fixed time stop changes; signal, entry, A67 target, costs, K80, T+1, limits, and QD-010 are unchanged.",
        "- 2024 data may only manage and complete pre-2024 signals.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=(
            "stage-a",
            "verify-stage-a",
            "development-freeze",
            "verify-diagnostic-freeze",
            "diagnostic",
            "report",
        ),
    )
    args = parser.parse_args()
    if args.stage == "stage-a":
        payload = run_stage_a()
    elif args.stage == "verify-stage-a":
        payload = verify_stage_a()
    elif args.stage == "development-freeze":
        payload = run_development_and_freeze()
    elif args.stage == "verify-diagnostic-freeze":
        payload = verify_diagnostic_freeze()
    elif args.stage == "diagnostic":
        payload = run_diagnostic()
    else:
        render_report()
        payload = {"report": str(REPORT)}
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
