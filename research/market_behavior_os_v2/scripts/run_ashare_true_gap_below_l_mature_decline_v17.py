#!/usr/bin/env python3
# ruff: noqa: E501
"""Test a fixed minimum decline duration on the V16 D30 candidate."""

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
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as prior_decline,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-MATURE-DECLINE-V17"
START_HEAD = "b70c921dd3"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_mature_decline_v17"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

PRIOR_DRAWDOWN_MIN = 0.30
PEAK_TO_GAP_SESSIONS_MIN = 20
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = prior_decline.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = prior_decline.DIAGNOSTIC_YEARS


class V17Error(RuntimeError):
    """Fail-closed V17 research error."""


def sha256(path: Path) -> str:
    return prior_decline.sha256(path)


def write_json(path: Path, value: Any) -> None:
    prior_decline.write_json(path, value)


def selected_entries_path(label: str) -> Path:
    # Keep the dependency's expected mechanical filename inside the isolated V17 root.
    return EXT_ROOT / label.lower() / "d30_selected_entries.parquet"


@contextmanager
def v17_runtime() -> Iterator[None]:
    old_root = prior_decline.EXT_ROOT
    try:
        prior_decline.EXT_ROOT = EXT_ROOT
        yield
    finally:
        prior_decline.EXT_ROOT = old_root


def mature_decline_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame.pre_gap_drawdown_from_120d_peak.ge(PRIOR_DRAWDOWN_MIN)
        & frame.pre_peak_to_gap_sessions.ge(PEAK_TO_GAP_SESSIONS_MIN)
    ).fillna(False)


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A 30% decline that reaches a clean downward true gap in fewer than one "
            "trading month is an acute crash or rise-and-fall episode rather than the "
            "mature liquidation path in the visual hypothesis. Requiring at least 20 "
            "completed sessions from the prior 120-session peak to gap formation may "
            "exclude acute failures while retaining broad signal coverage."
        ),
        "source_strategy": prior_decline.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "fixed_conditions": {
            "prior_drawdown": "pre_gap_drawdown_from_120d_peak >= 0.30",
            "decline_duration": "pre_peak_to_gap_sessions >= 20",
            "duration_definition": (
                "completed-session distance from the maximum coordinate high in the "
                "exact prior 120 sessions to true-gap formation"
            ),
            "known_time": "true-gap formation close; before reversal signal",
            "missing_policy": "fail closed",
            "threshold_search": "NONE",
        },
        "unchanged": {
            "V13_strict_true_gap_vap_and_first_reversal": True,
            "no_L_touch_before_signal": True,
            "entry": "next legal buyable 1-minute open",
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
            "status": "OUTCOME_BLIND_SINGLE_FIXED_MATURE_DECLINE_GATE",
            "frequency_goal": "at least 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "The natural one-trading-month M20 condition was fixed from the "
                "economic distinction between acute and mature declines; no duration family is searched."
            ),
            "diagnostic_disclosure": (
                "Only D30+M20 may open 2022-2023 outcomes after Development passes; "
                "that period remains post-observation evidence."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v13_runner": Path(first_reversal.__file__),
        "v13_contract": first_reversal.CONTRACT,
        "v13_stage_a_freeze": first_reversal.STAGE_A_FREEZE,
        "v16_runner_replay_dependency": Path(prior_decline.__file__),
        "v16_contract": prior_decline.CONTRACT,
    }
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        values[f"{label.lower()}_entries"] = prior_decline.source_paths(label)[
            "entries"
        ]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V17Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(prior_decline.source_paths(label)["entries"])
    for column in ("gap_date", "signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    if entries.gap_id.duplicated().any():
        raise V17Error(f"{label} duplicate source gap identity")
    required = entries[
        ["pre_gap_drawdown_from_120d_peak", "pre_peak_to_gap_sessions"]
    ]
    if required.isna().any().any():
        raise V17Error(f"{label} missing mature-decline feature")
    selected = entries.loc[mature_decline_mask(entries)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(years)].copy()
    selected["mature_decline_gate"] = True
    selected["mature_decline_latest_timestamp"] = selected.gap_date + pd.Timedelta(
        hours=15
    )
    selected["feature_uses_post_signal_information"] = (
        selected.mature_decline_latest_timestamp > selected.signal_time
    )
    if selected.feature_uses_post_signal_information.any():
        raise V17Error(f"{label} mature-decline causality failure")
    selected = selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    output = selected_entries_path(label)
    prior_decline.repair.write_parquet(selected, output)
    executable = selected.entry_status.eq("EXECUTABLE_ENTRY")
    annual = (
        selected.loc[executable]
        .assign(_year=selected.loc[executable, "signal_date"].dt.year)
        .groupby("_year")
        .size()
    )
    return {
        "source_entries": len(entries),
        "selected_signals": len(selected),
        "executable_entries": int(executable.sum()),
        "executable_entries_per_year": float(executable.sum() / len(years)),
        "executable_by_year": {
            str(year): int(annual.get(year, 0)) for year in years
        },
        "feature_uses_post_signal_information_count": int(
            selected.feature_uses_post_signal_information.sum()
        ),
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
        "stage": "OUTCOME_BLIND_FIXED_D30_M20_GATE_FREEZE",
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
        raise V17Error("Stage-A freeze missing")
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
        raise V17Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    with v17_runtime():
        item = prior_decline.run_lane(label, years)
    item["rule"] = "D30_M20_MATURE_DECLINE"
    return item


def development_checks(item: dict[str, Any]) -> dict[str, bool]:
    return prior_decline.development_checks(item)


def diagnostic_checks(item: dict[str, Any]) -> dict[str, bool]:
    return prior_decline.diagnostic_checks(item)


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
            "MATURE_DECLINE_DEVELOPMENT_CANDIDATE"
            if passed
            else "MATURE_DECLINE_DEVELOPMENT_FAILED"
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
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_FIXED_D30_M20_OUTCOME_OPEN",
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
        raise V17Error("Development produced no diagnostic freeze")
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
        raise V17Error(f"diagnostic freeze drift: {drift}")
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
            "MATURE_DECLINE_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "MATURE_DECLINE_POST_OBSERVATION_FAILED"
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
    d30 = json.loads(prior_decline.DEVELOPMENT_RESULT.read_text(encoding="utf-8"))[
        "rule_result"
    ]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Fixed rule",
        "",
        "`D30 + pre_peak_to_gap_sessions >= 20`; no duration search.",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|D30 control|{d30['portfolio_accepted_trades']}|{d30['portfolio_accepted_trades_per_year']:.1f}|{pct(d30['portfolio_mean_net'])}|{pct(d30['portfolio_median_net'])}|{pct(d30['portfolio_win'])}|{pct(d30['portfolio_severe10'])}|{pct(d30['portfolio_cagr'])}|{pct(d30['portfolio_max_drawdown'])}|",
        f"|D30+M20|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|",
    ]
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        observed = result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"Verdict: `{result['verdict']}`.",
            f"Accepted/year: {observed['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(observed['portfolio_mean_net'])}; median: {pct(observed['portfolio_median_net'])}; severe10: {pct(observed['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "2022-2023 D30+M20 outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Frequency is a floor of at least 50 accepted trades/year, never a target or upper cap.",
        "- M20 is one fixed economic distinction between acute and mature declines.",
        "- All V13 signal, execution, target, time-stop, cost, portfolio, and PIT rules are unchanged.",
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
