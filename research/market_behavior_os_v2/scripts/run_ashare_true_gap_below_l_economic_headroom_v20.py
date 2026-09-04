#!/usr/bin/env python3
# ruff: noqa: E501
"""Test one fixed 6% net-to-L executable-entry headroom gate on V19."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_fresh_mature_decline_v19 as fresh_decline,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-ECONOMIC-HEADROOM-V20"
START_HEAD = "ef1ab83600"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_economic_headroom_v20"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

MIN_NET_L_HEADROOM = 0.06
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = fresh_decline.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = fresh_decline.DIAGNOSTIC_YEARS


class V20Error(RuntimeError):
    """Fail-closed V20 research error."""


def sha256(path: Path) -> str:
    return fresh_decline.sha256(path)


def write_json(path: Path, value: Any) -> None:
    fresh_decline.write_json(path, value)


def source_entries_path(label: str) -> Path:
    return fresh_decline.selected_entries_path(label)


def selected_entries_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d30_selected_entries.parquet"


@contextmanager
def v20_runtime() -> Iterator[None]:
    replay = fresh_decline.mature_decline.prior_decline
    old_root = replay.EXT_ROOT
    try:
        replay.EXT_ROOT = EXT_ROOT
        yield
    finally:
        replay.EXT_ROOT = old_root


def economic_headroom_mask(frame: pd.DataFrame) -> pd.Series:
    return frame.realized_net_l_headroom.ge(MIN_NET_L_HEADROOM).fillna(False)


def implied_a67_net_target_return(net_l_headroom: float) -> float:
    cost = fresh_decline.mature_decline.prior_decline.repair.COST
    round_trip_factor = (1 - cost) / (1 + cost)
    raw_l_ratio = (1 + net_l_headroom) / round_trip_factor
    raw_target_ratio = 1 + 0.67 * (raw_l_ratio - 1)
    return raw_target_ratio * round_trip_factor - 1


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A V19 signal should only be bought when the first legal open leaves enough "
            "absolute reward to support the 3% net objective. Requiring 6% realized net "
            "headroom to L implies about 3.9% net return at the unchanged A67 target, "
            "leaving a modest execution/outcome buffer without selecting on future return."
        ),
        "source_strategy": fresh_decline.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "single_fixed_gate": {
            "condition": "realized_net_l_headroom >= 0.06 at first legal buyable open",
            "equivalent_execution": (
                "pre-specified maximum buy-price limit derived from L, 40 bp round-trip "
                "cost, and 6% net headroom; fill at the legal open only when price is at or below that limit"
            ),
            "implied_a67_net_target_return": implied_a67_net_target_return(
                MIN_NET_L_HEADROOM
            ),
            "missing_policy": "fail closed",
            "threshold_search": "NONE",
        },
        "unchanged": {
            "D30_M20_AGE30_signal_population": True,
            "V13_first_reversal": True,
            "target": "A67 below L",
            "failure_stop": "NONE",
            "time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "T1_limits_suspensions_and_QD010": True,
        },
        "success_contract": {
            "accepted_trades_per_year_min": MIN_ACCEPTED_TRADES_PER_YEAR,
            "frequency_has_no_upper_cap": True,
            "portfolio_mean_net_min": 0.03,
            "portfolio_median_net_positive": True,
            "portfolio_severe10_max": 0.15,
            "positive_trade_mean_years_min": 4,
            "positive_portfolio_years_min": 4,
            "attack_date_equal_mean_positive": True,
            "diagnostic_each_year_trade_mean_positive": True,
        },
        "governance": {
            "one_rule_no_parameter_selection": True,
            "diagnostic_outcomes_opened_only_after_development_pass": True,
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
            "status": "OUTCOME_BLIND_SINGLE_FIXED_6PCT_NET_HEADROOM_GATE",
            "frequency_goal": "strictly more than 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "Six percent is one fixed economic reward-space requirement; no "
                "headroom family is searched."
            ),
            "diagnostic_disclosure": (
                "Only D30+M20+AGE30+H6 may open 2022-2023 outcomes after Development passes."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    replay = fresh_decline.mature_decline.prior_decline
    values: dict[str, Path] = {
        "v19_runner": Path(fresh_decline.__file__),
        "v19_contract": fresh_decline.CONTRACT,
        "v19_stage_a_freeze": fresh_decline.STAGE_A_FREEZE,
        "v16_replay_dependency": Path(replay.__file__),
    }
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        values[f"{label.lower()}_v19_entries"] = source_entries_path(label)
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V20Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(source_entries_path(label))
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    if entries.gap_id.duplicated().any():
        raise V20Error(f"{label} duplicate source gap identity")
    executable = entries.entry_status.eq("EXECUTABLE_ENTRY")
    if entries.loc[executable, "realized_net_l_headroom"].isna().any():
        raise V20Error(f"{label} executable entry missing net L headroom")
    entries["economic_headroom_gate_passed"] = False
    entries.loc[executable, "economic_headroom_gate_passed"] = economic_headroom_mask(
        entries.loc[executable]
    )
    rejected = executable & ~entries.economic_headroom_gate_passed
    entries.loc[rejected, "entry_status"] = "INSUFFICIENT_6PCT_L_HEADROOM"
    entries["headroom_decision_latest_timestamp"] = entries.entry_time
    entries["feature_uses_post_entry_information"] = False
    entries = entries.loc[entries.signal_date.dt.year.isin(years)].copy()
    entries = entries.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    output = selected_entries_path(label)
    replay = fresh_decline.mature_decline.prior_decline.repair
    replay.write_parquet(entries, output)
    retained = entries.entry_status.eq("EXECUTABLE_ENTRY")
    annual = (
        entries.loc[retained]
        .assign(_year=entries.loc[retained, "signal_date"].dt.year)
        .groupby("_year")
        .size()
    )
    return {
        "source_entries": len(entries),
        "source_executable_entries": int(executable.sum()),
        "headroom_rejections": int(rejected.sum()),
        "retained_executable_entries": int(retained.sum()),
        "retained_executable_entries_per_year": float(retained.sum() / len(years)),
        "retained_by_year": {
            str(year): int(annual.get(year, 0)) for year in years
        },
        "feature_uses_post_entry_information_count": 0,
        "selected_entries_sha256": sha256(output),
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods = {
        "DEVELOPMENT": build_period_stage_a("DEVELOPMENT", DEVELOPMENT_YEARS),
        "POST_OBSERVATION_DIAGNOSTIC": build_period_stage_a(
            "POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS
        ),
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_FIXED_D30_M20_AGE30_H6_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "periods": periods,
        "return_analysis_run": "NO",
        "strategy_backtest_run": "NO",
        "diagnostic_outcomes_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V20Error("Stage-A freeze missing")
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
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        current = sha256(selected_entries_path(label))
        expected = freeze["periods"][label]["selected_entries_sha256"]
        if current != expected:
            drift[f"{label}_selected_entries"] = [expected, current]
    if drift:
        raise V20Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    with v20_runtime():
        item = fresh_decline.mature_decline.prior_decline.run_lane(label, years)
    item["rule"] = "D30_M20_AGE30_H6_ECONOMIC_HEADROOM"
    return item


def development_checks(item: dict[str, Any]) -> dict[str, bool]:
    checks = fresh_decline.development_checks(item)
    checks["accepted_trades_per_year_gt_50"] = (
        item["portfolio_accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR
    )
    checks.pop("accepted_trades_per_year_ge_50", None)
    return checks


def diagnostic_checks(item: dict[str, Any]) -> dict[str, bool]:
    checks = fresh_decline.diagnostic_checks(item)
    checks["accepted_trades_per_year_gt_50"] = (
        item["portfolio_accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR
    )
    checks.pop("accepted_trades_per_year_ge_50", None)
    return checks


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    item = run_lane("DEVELOPMENT", DEVELOPMENT_YEARS)
    checks = development_checks(item)
    passed = all(checks.values())
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "rule_result": item,
        "goal_checks": checks,
        "selector_passed": passed,
        "verdict": (
            "ECONOMIC_HEADROOM_DEVELOPMENT_CANDIDATE"
            if passed
            else "ECONOMIC_HEADROOM_DEVELOPMENT_FAILED"
        ),
        "development_outcomes_opened": "YES",
        "diagnostic_outcomes_opened": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    if passed:
        write_json(
            DIAGNOSTIC_FREEZE,
            {
                "experiment": EXPERIMENT,
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_FIXED_H6_OUTCOME_OPEN",
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "diagnostic_selected_entries_sha256": sha256(
                    selected_entries_path("POST_OBSERVATION_DIAGNOSTIC")
                ),
                "diagnostic_outcomes_opened": "NO",
            },
        )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V20Error("Development produced no diagnostic freeze")
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "diagnostic_selected_entries_sha256": sha256(
            selected_entries_path("POST_OBSERVATION_DIAGNOSTIC")
        ),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    if drift:
        raise V20Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    item = run_lane("POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS)
    checks = diagnostic_checks(item)
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "diagnostic": item,
        "goal_checks": checks,
        "verdict": (
            "ECONOMIC_HEADROOM_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "ECONOMIC_HEADROOM_POST_OBSERVATION_FAILED"
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
    item = development["rule_result"]
    baseline = json.loads(
        fresh_decline.DEVELOPMENT_RESULT.read_text(encoding="utf-8")
    )["rule_result"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Fixed rule",
        "",
        "V19 plus `realized_net_l_headroom >= 6%` at the first legal open.",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|V19 control|{baseline['portfolio_accepted_trades']}|{baseline['portfolio_accepted_trades_per_year']:.1f}|{pct(baseline['portfolio_mean_net'])}|{pct(baseline['portfolio_median_net'])}|{pct(baseline['portfolio_win'])}|{pct(baseline['portfolio_severe10'])}|{pct(baseline['portfolio_cagr'])}|{pct(baseline['portfolio_max_drawdown'])}|",
        f"|H6|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|",
    ]
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        observed = result["diagnostic"]
        yearly_text = ", ".join(
            f"{year} {pct(values['mean_net'])}"
            for year, values in observed["accepted_trade_yearly"].items()
        )
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"Verdict: `{result['verdict']}`.",
            f"Accepted/year: {observed['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(observed['portfolio_mean_net'])}; median: {pct(observed['portfolio_median_net'])}; severe10: {pct(observed['portfolio_severe10'])}.",
            f"Yearly trade means: {yearly_text}.",
        ]
    else:
        lines += ["", "2022-2023 H6 outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Frequency must remain strictly above 50 accepted trades/year; there is no upper cap.",
        "- H6 is a pre-specified executable price limit, not a post-open discretionary selection.",
        "- All V19 signal, A67, H20, cost, portfolio, and PIT semantics are unchanged.",
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
