#!/usr/bin/env python3
# ruff: noqa: E501
"""One-shot A67 target plus K80 capacity synthesis on the corrected V4R1 signal."""

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
    run_ashare_true_gap_below_l_target_translation_v11 as target_translation,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-A67-K80-COMBINATION-V12"
START_HEAD = "fe8e7e5fb9"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_a67_k80_combination_v12"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
IMPLEMENTATION_AMENDMENT = OS / f"artifacts/{EXPERIMENT}_pre_result_implementation_amendment.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

TARGET_FRACTION = 0.67
PORTFOLIO_K = 80
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0


class V12Error(RuntimeError):
    """Fail-closed V12 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def run_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "a67_k80"


def outcomes_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "a67" / "outcomes.parquet"


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "Two independently observed Development mechanisms may be complementary: "
            "A67 realizes a partial repair before renewed overhead supply, while K80 "
            "reduces the adverse collision-selection effect of K20. The exact A67+K80 "
            "combination is tested once without another target or capacity search."
        ),
        "source_signal": repair.EXPERIMENT,
        "development_inputs_disclosed": {
            "a67_k20_development": "known from V11",
            "a80_k80_development": "known from V9",
            "a67_k80_development": "not computed before this contract freeze",
            "a67_2022_2023": "not opened before this contract freeze",
        },
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "single_fixed_translation": {
            "target": "entry + 0.67*(L-entry), strictly below L",
            "k_per_board_sleeve": PORTFOLIO_K,
            "allocation": "1/80 of current board-sleeve NAV per accepted position",
        },
        "development_gate": {
            "portfolio_accepted_trades_per_year_min": MIN_ACCEPTED_TRADES_PER_YEAR,
            "frequency_has_no_upper_cap": True,
            "portfolio_mean_net_min": 0.03,
            "portfolio_median_net_positive": True,
            "portfolio_severe10_max": 0.15,
            "positive_trade_mean_years_min": 4,
            "positive_portfolio_years_min": 4,
            "attack_date_equal_mean_positive": True,
        },
        "unchanged_v4r1": {
            "signal_population_and_features": True,
            "entry": True,
            "minimum_net_headroom_to_L": 0.05,
            "failure_stop": "NONE",
            "time_stop": "H20",
            "round_trip_cost": 0.004,
            "board_sleeves": "Main 50% / ChiNext 50%",
            "collision_rank": True,
            "T1_limits_suspensions_and_QD010": True,
        },
        "governance": {
            "no_alternative_target_or_k": True,
            "no_post_2023_signals_or_selection": True,
            "post_2023_scope": "management/completion of pre-2024 trades only",
            "no_leverage": True,
            "unused_capital_stays_cash": True,
            "no_cross_sleeve_transfer": True,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "ONE_SHOT_PRE_DIAGNOSTIC_A67_K80_SYNTHESIS",
            "frequency_goal": "at least 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "A67/K20 and A80/K80 Development evidence was known, but the exact "
                "A67/K80 replay had not been computed before this freeze."
            ),
            "diagnostic_disclosure": (
                "A67 2022-2023 executable outcomes were not opened before this freeze; "
                "2022-2023 remains post-observation evidence for the broader lane."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v4r1_stage_a_freeze": repair.STAGE_A_FREEZE,
        "v4r1_result": repair.RESULT,
        "v11_stage_a_freeze": target_translation.STAGE_A_FREEZE,
        "v11_development_result": target_translation.DEVELOPMENT_RESULT,
        "v11_contract": target_translation.CONTRACT,
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
        raise V12Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "PRE_DIAGNOSTIC_ONE_SHOT_COMBINATION_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "a67_k80_development_replay_opened": "NO",
        "a67_2022_2023_outcomes_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V12Error("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    current_runner_sha256 = sha256(Path(__file__))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    identities = source_hashes()
    if identities != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), identities]
    if freeze.get("runner_sha256") != current_runner_sha256:
        if not IMPLEMENTATION_AMENDMENT.is_file():
            drift["runner_sha256"] = [
                freeze.get("runner_sha256"),
                current_runner_sha256,
            ]
        else:
            amendment = json.loads(
                IMPLEMENTATION_AMENDMENT.read_text(encoding="utf-8")
            )
            amendment_valid = bool(
                amendment.get("original_runner_sha256") == freeze.get("runner_sha256")
                and amendment.get("amended_runner_sha256") == current_runner_sha256
                and amendment.get("research_semantics_changed") is False
                and amendment.get("development_combination_metrics_observed") is False
                and amendment.get("repair_scope")
                == "correct outcomes.parquet hash path from a67_k80 to a67"
            )
            if not amendment_valid:
                drift["implementation_amendment"] = [
                    amendment,
                    "valid pre-result path-only amendment",
                ]
    if drift:
        raise V12Error(f"Stage-A freeze drift: {drift}")
    return {
        "verified": True,
        "checks": {**checks, "runner_sha256": current_runner_sha256},
        "source_hashes": identities,
        "pre_result_implementation_amendment": (
            sha256(IMPLEMENTATION_AMENDMENT)
            if IMPLEMENTATION_AMENDMENT.is_file()
            else None
        ),
    }


def build_outcomes(label: str) -> tuple[pd.DataFrame, dict[str, int]]:
    old_root = target_translation.EXT_ROOT
    try:
        target_translation.EXT_ROOT = EXT_ROOT
        return target_translation.build_alpha_outcomes(label, TARGET_FRACTION)
    finally:
        target_translation.EXT_ROOT = old_root


def run_combination(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    outcomes, outcome_audit = build_outcomes(label)
    for column in ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    daily = pd.read_parquet(repair.paths(label)["outcome_daily"])
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = run_root(label)
    root.mkdir(parents=True, exist_ok=True)
    repair.v1.configure_external(root, max_exit)
    old_k = repair.v1.PORTFOLIO_K
    try:
        repair.v1.PORTFOLIO_K = PORTFOLIO_K
        replay_years = tuple(range(min(years), int(max_exit.year) + 1))
        portfolio = repair.v1.run_portfolio(
            outcomes,
            daily.loc[daily.trade_date.le(max_exit)].copy(),
            replay_years,
        )
    finally:
        repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    for column in ("entry_date", "entry_time", "exit_date", "exit_time"):
        accepted[column] = pd.to_datetime(accepted[column])
    accepted_yearly = (
        accepted.assign(_year=accepted.entry_date.dt.year)
        .groupby("_year")
        .net_return.agg(trades="size", mean_net="mean", median_net="median")
    )
    combined = portfolio["COMBINED"]
    annual = combined["annual_returns"]
    yearly_payload = {
        str(int(index)): {
            "trades": int(row.trades),
            "mean_net": float(row.mean_net),
            "median_net": float(row.median_net),
        }
        for index, row in accepted_yearly.iterrows()
    }
    return {
        "target_fraction": TARGET_FRACTION,
        "k_per_board_sleeve": PORTFOLIO_K,
        "source_executable_trades": len(outcomes),
        "event_metrics": repair.v1.trade_metrics(outcomes),
        "attack_date_equal_mean": float(
            outcomes.assign(_date=outcomes.entry_date.dt.normalize())
            .groupby("_date")
            .net_return.mean()
            .mean()
        ),
        "portfolio": portfolio,
        "portfolio_accepted_trades": len(accepted),
        "portfolio_accepted_trades_per_year": len(accepted) / len(years),
        "portfolio_mean_net": float(combined["mean_net"]),
        "portfolio_median_net": float(combined["median_net"]),
        "portfolio_win": float(combined["win"]),
        "portfolio_severe10": float(combined["severe10"]),
        "portfolio_total_return": float(combined["total_return"]),
        "portfolio_cagr": float(combined["cagr"]),
        "portfolio_max_drawdown": float(combined["max_drawdown"]),
        "portfolio_sharpe": float(combined["sharpe"]),
        "portfolio_average_utilization": float(combined["average_utilization"]),
        "positive_trade_mean_years": int(
            sum(float(yearly_payload.get(str(year), {}).get("mean_net", 0.0)) > 0 for year in years)
        ),
        "positive_portfolio_years": int(
            sum(float(annual.get(str(year), 0.0)) > 0 for year in years)
        ),
        "annual_returns": annual,
        "accepted_trade_yearly": yearly_payload,
        "capacity_skips": int(portfolio["audit"]["capacity_skips"]),
        "duplicate_symbol_skips": int(portfolio["audit"]["duplicate_symbol_skips"]),
        "max_k_violation_count": int(portfolio["audit"]["max_k_violation_count"]),
        "negative_cash_or_leverage_count": int(
            portfolio["audit"]["negative_cash_or_leverage_count"]
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(
            outcomes.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
        ),
        "outcome_audit": outcome_audit,
        "hashes": {
            "outcomes": sha256(outcomes_path(label)),
            "portfolio_accepted": sha256(root / "portfolio_accepted.parquet"),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
        },
    }


def development_checks(item: dict[str, Any]) -> dict[str, bool]:
    return {
        "accepted_trades_per_year_ge_50": (
            item["portfolio_accepted_trades_per_year"] >= MIN_ACCEPTED_TRADES_PER_YEAR
        ),
        "portfolio_mean_net_ge_3pct": item["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": item["portfolio_median_net"] > 0,
        "severe10_le_15pct": item["portfolio_severe10"] <= 0.15,
        "positive_trade_mean_years_ge_4": item["positive_trade_mean_years"] >= 4,
        "positive_portfolio_years_ge_4": item["positive_portfolio_years"] >= 4,
        "attack_date_equal_mean_positive": item["attack_date_equal_mean"] > 0,
        "audit_clean": (
            item["max_k_violation_count"] == 0
            and item["negative_cash_or_leverage_count"] == 0
            and item["post_2023_signal_count"] == 0
        ),
    }


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
            float(item["annual_returns"].get(str(year), -1.0)) > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "audit_clean": (
            item["max_k_violation_count"] == 0
            and item["negative_cash_or_leverage_count"] == 0
            and item["post_2023_signal_count"] == 0
        ),
    }


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    development = run_combination("DEVELOPMENT", DEVELOPMENT_YEARS)
    checks = development_checks(development)
    passed = all(checks.values())
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "combination": development,
        "goal_checks": checks,
        "development_gate_passed": passed,
        "diagnostic_combination_outcomes_opened": "NO",
        "verdict": (
            "A67_K80_DEVELOPMENT_CANDIDATE"
            if passed
            else "A67_K80_DEVELOPMENT_FAILED"
        ),
    }
    write_json(DEVELOPMENT_RESULT, result)
    if passed:
        write_json(
            DIAGNOSTIC_FREEZE,
            {
                "experiment": EXPERIMENT,
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_A67_K80_REPLAY",
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "target_fraction": TARGET_FRACTION,
                "k_per_board_sleeve": PORTFOLIO_K,
                "a67_2022_2023_outcomes_opened": "NO",
                "post_2023_signal_data_opened": "NO",
            },
        )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V12Error("Development produced no diagnostic freeze")
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
        raise V12Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    diagnostic = run_combination("POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS)
    checks = diagnostic_checks(diagnostic)
    passed = all(checks.values())
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": (
            "A67_K80_POST_OBSERVATION_TARGET_RETAINED"
            if passed
            else "A67_K80_POST_OBSERVATION_FAILED"
        ),
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
    item = development["combination"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Target|K/sleeve|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|67%|80|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|"
        f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
        f"{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|"
        f"{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|",
    ]
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        diagnostic = result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"`{result['verdict']}`",
            "",
            f"Accepted/year: {diagnostic['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(diagnostic['portfolio_mean_net'])}; median: {pct(diagnostic['portfolio_median_net'])}; severe10: {pct(diagnostic['portfolio_severe10'])}.",
            "",
            "This section is robustness evidence only because the broader 2022-2023 lane was previously observed.",
        ]
    else:
        lines += ["", "The A67 2022-2023 executable outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- This is one fixed A67 + K80 synthesis; there is no V12 target or capacity grid.",
        "- The minimum frequency is 50 accepted trades/year, with no upper cap or penalty.",
        "- Signal, features, entry, H20, costs, T+1, limits, QD-010, and collision rank are unchanged.",
        "- Later data may manage and complete pre-cutoff trades; no post-2023 signal or selection is allowed.",
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
