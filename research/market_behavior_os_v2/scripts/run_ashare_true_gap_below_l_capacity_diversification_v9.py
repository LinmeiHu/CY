#!/usr/bin/env python3
# ruff: noqa: E501
"""Test whether K20 capacity selection suppresses the corrected signal economics."""

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
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-CAPACITY-DIVERSIFICATION-V9"
START_HEAD = "4cbed55d0d"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_capacity_diversification_v9"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

K_VALUES = (20, 40, 80)
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0


class V9Error(RuntimeError):
    """Fail-closed V9 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def k_root(label: str, k: int) -> Path:
    return EXT_ROOT / label.lower() / f"k{k:02d}"


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "The corrected V4R1 event population has positive average economics, but "
            "the deterministic K20 sleeve-capacity ordering may preferentially admit a "
            "weaker clustered subset. Broader diversification can test this without "
            "changing any signal or trade semantic."
        ),
        "source": repair.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "fixed_k_family_per_board_sleeve": list(K_VALUES),
        "allocation": "each accepted position receives 1/K of current board-sleeve NAV",
        "selector": {
            "eligibility": {
                "portfolio_accepted_trades_per_year_min": MIN_ACCEPTED_TRADES_PER_YEAR,
                "portfolio_mean_net_min": 0.03,
                "portfolio_median_net_positive": True,
                "portfolio_severe10_max": 0.15,
                "positive_calendar_years_min": 4,
                "portfolio_total_return_positive": True,
            },
            "order": "smallest K that passes every eligibility condition",
        },
        "unchanged_v4r1": {
            "signal_population": True,
            "features": True,
            "entry": True,
            "target": "entry + 0.80*(L-entry)",
            "failure_stop": "NONE",
            "time_stop": "H20",
            "costs": 0.004,
            "collision_rank": (
                "entry time, higher realized target headroom, lower inside density, "
                "symbol, gap_id"
            ),
            "T1_limits_suspensions_and_corporate_actions": True,
        },
        "governance": {
            "no_leverage": True,
            "unused_cash_stays_cash": True,
            "no_cross_sleeve_transfer": True,
            "one_active_position_per_symbol": True,
            "frequency_has_no_upper_cap": True,
            "post_2023_scope": "trade completion only; no new signal or selection data",
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "OUTCOME_BLIND_FIXED_K_CAPACITY_FAMILY",
            "development_disclosure": (
                "K20/K40/K80 and smallest-passing-K selection were frozen after V8 "
                "failed and before K40/K80 portfolio results were computed."
            ),
            "diagnostic_disclosure": "2022-2023 remains post-observation evidence.",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v4r1_stage_a_freeze": repair.STAGE_A_FREEZE,
        "v4r1_result": repair.RESULT,
    }
    for label in repair.PERIODS:
        paths = repair.paths(label)
        for name in ("entries", "outcomes", "outcome_daily"):
            values[f"{label.lower()}_{name}"] = paths[name]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V9Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_CAPACITY_CONTRACT_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "k40_or_k80_results_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V9Error("Stage-A freeze missing")
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
        raise V9Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": identities}


def run_k(label: str, k: int, years: tuple[int, ...]) -> dict[str, Any]:
    paths = repair.paths(label)
    outcomes = pd.read_parquet(paths["outcomes"])
    daily = pd.read_parquet(paths["outcome_daily"])
    for frame, columns in (
        (outcomes, ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time")),
        (daily, ("trade_date",)),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = k_root(label, k)
    root.mkdir(parents=True, exist_ok=True)
    repair.v1.configure_external(root, max_exit)
    old_k = repair.v1.PORTFOLIO_K
    try:
        repair.v1.PORTFOLIO_K = k
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
    accepted_yearly = accepted.assign(_year=accepted.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    combined = portfolio["COMBINED"]
    return {
        "k_per_board_sleeve": k,
        "source_executable_trades": len(outcomes),
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
        "max_k_violation_count": int(portfolio["audit"]["max_k_violation_count"]),
        "negative_cash_or_leverage_count": int(
            portfolio["audit"]["negative_cash_or_leverage_count"]
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(
            outcomes.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
        ),
        "hashes": {
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
        and item["portfolio_total_return"] > 0
    )


def select_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates.values() if candidate_eligible(item)]
    if not eligible:
        raise V9Error("no Development K passes selector")
    return sorted(eligible, key=lambda item: item["k_per_board_sleeve"])[0]


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    candidates = {
        str(k): run_k("DEVELOPMENT", k, DEVELOPMENT_YEARS) for k in K_VALUES
    }
    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "candidate_results": candidates,
        "development_capacity_results_opened": "YES",
        "diagnostic_capacity_results_opened": "NO",
    }
    try:
        selected = select_candidate(candidates)
    except V9Error:
        result.update(
            {
                "selector_passed": False,
                "selected_k": None,
                "verdict": "CAPACITY_DIVERSIFICATION_DEVELOPMENT_FAILED",
            }
        )
        write_json(DEVELOPMENT_RESULT, result)
        return result
    result.update(
        {
            "selector_passed": True,
            "selected_k": selected["k_per_board_sleeve"],
            "verdict": "CAPACITY_DIVERSIFICATION_DEVELOPMENT_CANDIDATE",
        }
    )
    write_json(DEVELOPMENT_RESULT, result)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_FREEZE_BEFORE_SELECTED_K_REPLAY",
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "selected_k": selected["k_per_board_sleeve"],
        "diagnostic_capacity_results_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(DIAGNOSTIC_FREEZE, freeze)
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V9Error("Development produced no diagnostic freeze")
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
        raise V9Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    k = int(freeze["selected_k"])
    diagnostic = run_k("POST_OBSERVATION_DIAGNOSTIC", k, DIAGNOSTIC_YEARS)
    yearly = diagnostic["accepted_trade_yearly"]
    checks = {
        "accepted_mean_net_ge_3pct": diagnostic["portfolio_mean_net"] >= 0.03,
        "accepted_median_positive": diagnostic["portfolio_median_net"] > 0,
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
        "CAPACITY_DIVERSIFICATION_POST_OBSERVATION_TARGET_RETAINED"
        if all(checks.values())
        else "CAPACITY_DIVERSIFICATION_POST_OBSERVATION_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_k": k,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": verdict,
        "scientific_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_ONLY",
        "post_2023_signal_data_opened": "NO",
        "repository_2024_plus_data_opened": (
            "AUTHORIZED_PRE_2024_TRADE_COMPLETION_ONLY"
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
        "|K / board sleeve|Accepted|Accepted/year|Mean|Median|Severe10|CAGR|MaxDD|Utilization|Capacity skips|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for k in K_VALUES:
        item = development["candidate_results"][str(k)]
        lines.append(
            f"|{k}|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|"
            f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
            f"{pct(item['portfolio_severe10'])}|{pct(item['portfolio_cagr'])}|"
            f"{pct(item['portfolio_max_drawdown'])}|{pct(item['portfolio_average_utilization'])}|"
            f"{item['capacity_skips']}|"
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
            f"Selected K: {result['selected_k']}; accepted/year: {item['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(item['portfolio_mean_net'])}; median: {pct(item['portfolio_median_net'])}; severe10: {pct(item['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "The selected-K 2022-2023 portfolio replay was not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- No signal, feature, entry, target, exit, cost, or collision rank changed.",
        "- K changes both maximum concurrent positions and 1/K sleeve sizing; there is no leverage.",
        "- The smallest K meeting all frozen gates is selected.",
        "- Later data are restricted to completing pre-cutoff trades.",
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
