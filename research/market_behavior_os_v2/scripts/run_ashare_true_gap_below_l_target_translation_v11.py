#!/usr/bin/env python3
# ruff: noqa: E501
"""Test three fixed pre-gap profit targets on the corrected V4R1 signal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-TARGET-TRANSLATION-V11"
START_HEAD = "43cde347bf"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_target_translation_v11"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

TARGET_FRACTIONS = (0.50, 0.67, 0.80)
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0


class V11Error(RuntimeError):
    """Fail-closed V11 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def alpha_key(alpha: float) -> str:
    return f"A{round(alpha * 100):02d}"


def alpha_root(label: str, alpha: float) -> Path:
    return EXT_ROOT / label.lower() / alpha_key(alpha).lower()


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "The strict low-inventory below-gap signal may identify a rebound, but an "
            "80%-to-L target can overstay a partial repair. Earlier fixed targets may "
            "monetize the rebound before renewed overhead supply appears."
        ),
        "source": repair.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "target_family": {
            alpha_key(alpha): f"entry + {alpha:.2f}*(L-entry), strictly below L"
            for alpha in TARGET_FRACTIONS
        },
        "selector": {
            "eligibility": {
                "portfolio_accepted_trades_per_year_min": MIN_ACCEPTED_TRADES_PER_YEAR,
                "portfolio_mean_net_min": 0.03,
                "portfolio_median_net_positive": True,
                "portfolio_severe10_max": 0.15,
                "positive_calendar_years_min": 4,
                "attack_date_equal_mean_positive": True,
            },
            "order": [
                "higher portfolio mean net return",
                "higher portfolio median net return",
                "lower severe_loss10",
                "lower target fraction",
            ],
        },
        "unchanged_v4r1": {
            "signal_population_and_features": True,
            "entry": True,
            "minimum_net_headroom_to_L": 0.05,
            "failure_stop": "NONE",
            "time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K20 per sleeve",
            "collision_rank": True,
            "T1_limits_suspensions_and_QD010": True,
        },
        "post_2023_scope": "trade management/completion only; no post-2023 signal or selection",
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "OUTCOME_BLIND_THREE_FIXED_TARGET_TRANSLATIONS",
            "development_disclosure": (
                "A50/A67/A80 and their selector were frozen after V10 failed and "
                "before corrected A50/A67 executable outcomes were computed."
            ),
            "diagnostic_disclosure": "2022-2023 remains post-observation evidence.",
            "frequency_goal": "at least 50 accepted trades per year; no upper cap",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v4r1_stage_a_freeze": repair.STAGE_A_FREEZE,
        "v4r1_result": repair.RESULT,
    }
    for label in repair.PERIODS:
        source = repair.paths(label)
        for name in (
            "entries",
            "outcome_daily",
            "outcome_minutes",
            "sell_opens",
            "actions",
        ):
            values[f"{label.lower()}_{name}"] = source[name]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V11Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_TARGET_FAMILY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "a50_or_a67_outcomes_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V11Error("Stage-A freeze missing")
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
        raise V11Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": identities}


def build_alpha_outcomes(label: str, alpha: float) -> tuple[pd.DataFrame, dict[str, int]]:
    source = repair.paths(label)
    entries = pd.read_parquet(source["entries"])
    daily = pd.read_parquet(source["outcome_daily"])
    minutes = pd.read_parquet(source["outcome_minutes"])
    sells = pd.read_parquet(source["sell_opens"])
    actions = pd.read_parquet(source["actions"])
    for frame, columns in (
        (entries, ("signal_date", "signal_time", "entry_date", "entry_time")),
        (daily, ("trade_date",)),
        (minutes, ("trade_date", "bar_end_time")),
        (sells, ("trade_date", "bar_end_time")),
        (actions, ("known_date", "effective_date")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    root = alpha_root(label, alpha)
    root.mkdir(parents=True, exist_ok=True)
    old_alpha = repair.TARGET_FRACTION
    try:
        repair.TARGET_FRACTION = alpha
        outcomes, audit = repair.build_outcomes(
            entries,
            daily,
            minutes,
            sells,
            actions,
            repair.PERIODS[label][1],
            {"outcomes": root / "outcomes.parquet"},
        )
    finally:
        repair.TARGET_FRACTION = old_alpha
    return outcomes, audit


def run_alpha(label: str, alpha: float, years: tuple[int, ...]) -> dict[str, Any]:
    outcomes, outcome_audit = build_alpha_outcomes(label, alpha)
    for column in ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    daily = pd.read_parquet(repair.paths(label)["outcome_daily"])
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = alpha_root(label, alpha)
    repair.v1.configure_external(root, max_exit)
    repair.v1.PORTFOLIO_K = 20
    replay_years = tuple(range(min(years), int(max_exit.year) + 1))
    portfolio = repair.v1.run_portfolio(
        outcomes,
        daily.loc[daily.trade_date.le(max_exit)].copy(),
        replay_years,
    )
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    for column in ("entry_date", "entry_time", "exit_date", "exit_time"):
        accepted[column] = pd.to_datetime(accepted[column])
    event_yearly = outcomes.assign(_year=outcomes.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    accepted_yearly = accepted.assign(_year=accepted.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    combined = portfolio["COMBINED"]
    return {
        "target_fraction": alpha,
        "target_key": alpha_key(alpha),
        "source_executable_trades": len(outcomes),
        "event_metrics": repair.v1.trade_metrics(outcomes),
        "event_yearly": {
            str(int(index)): {
                "trades": int(row.trades),
                "mean_net": float(row.mean_net),
                "median_net": float(row.median_net),
            }
            for index, row in event_yearly.iterrows()
        },
        "attack_date_equal_mean": float(
            outcomes.assign(_date=outcomes.entry_date.dt.normalize())
            .groupby("_date").net_return.mean().mean()
        ),
        "portfolio": portfolio,
        "portfolio_accepted_trades": len(accepted),
        "portfolio_accepted_trades_per_year": len(accepted) / len(years),
        "portfolio_mean_net": float(combined["mean_net"]),
        "portfolio_median_net": float(combined["median_net"]),
        "portfolio_severe10": float(combined["severe10"]),
        "portfolio_total_return": float(combined["total_return"]),
        "portfolio_cagr": float(combined["cagr"]),
        "portfolio_max_drawdown": float(combined["max_drawdown"]),
        "portfolio_sharpe": float(combined["sharpe"]),
        "positive_calendar_years": int(
            sum(float(combined["annual_returns"].get(str(year), 0.0)) > 0 for year in years)
        ),
        "annual_returns": combined["annual_returns"],
        "accepted_trade_yearly": {
            str(int(index)): {
                "trades": int(row.trades),
                "mean_net": float(row.mean_net),
                "median_net": float(row.median_net),
            }
            for index, row in accepted_yearly.iterrows()
        },
        "capacity_skips": int(portfolio["audit"]["capacity_skips"]),
        "duplicate_symbol_skips": int(portfolio["audit"]["duplicate_symbol_skips"]),
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
        and item["positive_calendar_years"] >= 4
        and item["attack_date_equal_mean"] > 0
    )


def select_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates.values() if candidate_eligible(item)]
    if not eligible:
        raise V11Error("no Development target passes selector")
    return sorted(
        eligible,
        key=lambda item: (
            -item["portfolio_mean_net"],
            -item["portfolio_median_net"],
            item["portfolio_severe10"],
            item["target_fraction"],
        ),
    )[0]


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    candidates = {
        alpha_key(alpha): run_alpha("DEVELOPMENT", alpha, DEVELOPMENT_YEARS)
        for alpha in TARGET_FRACTIONS
    }
    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "candidate_results": candidates,
        "development_target_results_opened": "YES",
        "diagnostic_target_results_opened": "NO",
    }
    try:
        selected = select_candidate(candidates)
    except V11Error:
        result.update(
            {
                "selector_passed": False,
                "selected_target_fraction": None,
                "verdict": "TARGET_TRANSLATION_DEVELOPMENT_FAILED",
            }
        )
        write_json(DEVELOPMENT_RESULT, result)
        return result
    result.update(
        {
            "selector_passed": True,
            "selected_target_fraction": selected["target_fraction"],
            "verdict": "TARGET_TRANSLATION_DEVELOPMENT_CANDIDATE",
        }
    )
    write_json(DEVELOPMENT_RESULT, result)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_FREEZE_BEFORE_SELECTED_TARGET_REPLAY",
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "selected_target_fraction": selected["target_fraction"],
        "diagnostic_target_results_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(DIAGNOSTIC_FREEZE, freeze)
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V11Error("Development produced no diagnostic freeze")
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
        raise V11Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    alpha = float(freeze["selected_target_fraction"])
    diagnostic = run_alpha("POST_OBSERVATION_DIAGNOSTIC", alpha, DIAGNOSTIC_YEARS)
    yearly = diagnostic["accepted_trade_yearly"]
    checks = {
        "portfolio_mean_net_ge_3pct": diagnostic["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": diagnostic["portfolio_median_net"] > 0,
        "accepted_trades_per_year_ge_50": (
            diagnostic["portfolio_accepted_trades_per_year"]
            >= MIN_ACCEPTED_TRADES_PER_YEAR
        ),
        "severe10_le_15pct": diagnostic["portfolio_severe10"] <= 0.15,
        "both_year_trade_means_positive": all(
            float(yearly.get(str(year), {}).get("mean_net", -1.0)) > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "both_year_portfolio_returns_positive": all(
            float(diagnostic["annual_returns"].get(str(year), -1.0)) > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "post_2023_signal_count_zero": diagnostic["post_2023_signal_count"] == 0,
    }
    verdict = (
        "TARGET_TRANSLATION_POST_OBSERVATION_TARGET_RETAINED"
        if all(checks.values())
        else "TARGET_TRANSLATION_POST_OBSERVATION_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_target_fraction": alpha,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": verdict,
        "scientific_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_ONLY",
        "post_2023_signal_data_opened": "NO",
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
    lines = [f"# {EXPERIMENT}", "", "## Development", "", f"`{development['verdict']}`", ""]
    lines += [
        "|Target|Accepted|Accepted/year|Mean|Median|U-like hit|Severe10|CAGR|MaxDD|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for alpha in TARGET_FRACTIONS:
        item = development["candidate_results"][alpha_key(alpha)]
        lines.append(
            f"|{alpha:.0%}|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|"
            f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
            f"{pct(item['portfolio']['COMBINED']['u_hit'])}|{pct(item['portfolio_severe10'])}|"
            f"{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|"
        )
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        item = result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"`{result['verdict']}`",
            "",
            f"Selected target: {result['selected_target_fraction']:.0%}; accepted/year: {item['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(item['portfolio_mean_net'])}; median: {pct(item['portfolio_median_net'])}; severe10: {pct(item['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "The 2022-2023 selected-target outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Only the fixed fraction of the entry-to-L path changes.",
        "- Every target remains strictly below the true-gap lower boundary L.",
        "- Signal, features, entry, H20, costs, T+1, limits, QD-010, collision rank, and K20 are unchanged.",
        "- Later data are used only to manage and complete pre-cutoff trades.",
        "- No post-2023 signal or selection data are permitted.",
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
