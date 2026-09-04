#!/usr/bin/env python3
# ruff: noqa: E501
"""Test the frozen three-day-high confirmation with the native A80 target."""

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

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-THREE-DAY-CONFIRMED-A80-V23"
START_HEAD = "3862c7388d"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_three_day_confirmed_a80_v23"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

TRIGGER = "THREE_DAY_HIGH_BREAK"
TARGET_FRACTION = 0.80
TIME_STOP = 20
PORTFOLIO_K = 80
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = first_reversal.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = first_reversal.DIAGNOSTIC_YEARS


class V23Error(RuntimeError):
    """Fail-closed V23 research error."""


def sha256(path: Path) -> str:
    return first_reversal.sha256(path)


def write_json(path: Path, value: Any) -> None:
    first_reversal.write_json(path, value)


def source_root(label: str) -> Path:
    return first_reversal.trigger_root(TRIGGER) / label.lower()


def source_paths(label: str) -> dict[str, Path]:
    root = source_root(label)
    return {
        "entries": root / "entries.parquet",
        "actions": root / "qd010_actions.parquet",
        "execution_state": root / "execution_state.parquet",
    }


@contextmanager
def v23_runtime() -> Iterator[None]:
    replay = first_reversal.repair
    old_root = replay.EXT_ROOT
    old_target = replay.TARGET_FRACTION
    old_time_stop = replay.TIME_STOP
    old_k = replay.v1.PORTFOLIO_K
    try:
        replay.EXT_ROOT = EXT_ROOT
        replay.TARGET_FRACTION = TARGET_FRACTION
        replay.TIME_STOP = TIME_STOP
        replay.v1.PORTFOLIO_K = PORTFOLIO_K
        yield
    finally:
        replay.EXT_ROOT = old_root
        replay.TARGET_FRACTION = old_target
        replay.TIME_STOP = old_time_stop
        replay.v1.PORTFOLIO_K = old_k


def output_paths(label: str) -> dict[str, Path]:
    with v23_runtime():
        return first_reversal.repair.paths(label)


def period_bounds(label: str) -> tuple[pd.Timestamp, pd.Timestamp, tuple[int, ...]]:
    return first_reversal.PERIODS[label]


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A close above only the previous day's high can be a one-day weak rebound. "
            "Requiring the first completed close above the maximum high of the prior "
            "three completed sessions demonstrates multi-session demand acceptance. "
            "The native A80 target retains 20% of the entry-to-L path as a supply buffer "
            "while seeking enough absolute return to exceed the 3% trade objective."
        ),
        "source_strategy": first_reversal.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "fixed_trigger": {
            "name": TRIGGER,
            "condition": "current completed daily close > maximum high of prior three completed sessions",
            "first_trigger_only_per_gap": True,
            "entry": "first legal buyable 1-minute open strictly after completed trigger",
        },
        "fixed_translation": {
            "target": "entry + 0.80*(L-entry), strictly below L",
            "target_origin": "native A80 target in the causal replay infrastructure",
            "failure_stop": "NONE",
            "time_stop": "H20",
        },
        "unchanged_v13": {
            "strict_true_gap_and_clean_vap_corridor": True,
            "no_L_touch_before_signal": True,
            "maximum_depth_below_L_min": 0.10,
            "signal_depth_below_L_min": 0.05,
            "minimum_net_headroom_to_L": 0.05,
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "T1_limits_suspensions_and_QD010": True,
        },
        "not_carried_forward": [
            "D30",
            "M20",
            "AGE30",
            "H6",
            "dry3",
            "V21 progress-protection exit",
        ],
        "development_success_contract": {
            "accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "portfolio_mean_net_min": 0.03,
            "portfolio_median_net_positive": True,
            "portfolio_severe10_max": 0.15,
            "positive_trade_mean_years_min": 5,
            "positive_portfolio_years_min": 4,
            "attack_date_equal_mean_positive": True,
        },
        "diagnostic_success_contract": {
            "accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "combined_mean_net_min": 0.03,
            "combined_median_net_positive": True,
            "combined_severe10_max": 0.15,
            "year_2022_trade_mean_positive": True,
            "year_2023_mean_net_min": 0.01,
            "year_2023_median_net_min": 0.0,
            "year_2023_win_rate_min": 0.50,
            "both_2022_and_2023_portfolio_returns_positive": True,
        },
        "governance": {
            "single_trigger_single_target_no_grid": True,
            "diagnostic_opened_only_after_development_pass": True,
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
            "status": "FIXED_THREE_DAY_CONFIRMATION_WITH_NATIVE_A80_TRANSLATION",
            "frequency_goal": "strictly more than 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "THREE_DAY_HIGH_BREAK is a frozen V13 trigger and A80 is the replay "
                "infrastructure's native target; no trigger or target grid is searched."
            ),
            "diagnostic_disclosure": (
                "Identity-only audit found 133 executable 2022-2023 candidates before "
                "outcomes; exact 2023 requirements are frozen before replay."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes(label: str) -> dict[str, str]:
    values: dict[str, Path] = {
        "v13_runner": Path(first_reversal.__file__),
        "v13_contract": first_reversal.CONTRACT,
        "v13_stage_a_freeze": first_reversal.STAGE_A_FREEZE,
        f"{label.lower()}_entries": source_paths(label)["entries"],
        f"{label.lower()}_actions": source_paths(label)["actions"],
        f"{label.lower()}_execution_state": source_paths(label)["execution_state"],
    }
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V23Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    source = source_paths(label)
    entries = pd.read_parquet(source["entries"])
    actions = pd.read_parquet(source["actions"])
    execution_state = pd.read_parquet(source["execution_state"])
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    for column in ("known_date", "effective_date"):
        actions[column] = pd.to_datetime(actions[column])
    if not entries.trigger.eq(TRIGGER).all() or entries.gap_id.duplicated().any():
        raise V23Error(f"{label} source trigger identity failure")
    entries = entries.loc[entries.signal_date.dt.year.isin(years)].copy()
    paths = output_paths(label)
    first_reversal.repair.write_parquet(entries, paths["entries"])
    first_reversal.repair.write_parquet(actions, paths["actions"])
    first_reversal.repair.write_parquet(
        execution_state, paths["execution_state"]
    )
    executable = entries.entry_status.eq("EXECUTABLE_ENTRY")
    annual = (
        entries.loc[executable]
        .assign(_year=entries.loc[executable, "signal_date"].dt.year)
        .groupby("_year")
        .size()
    )
    return {
        "source_entries": len(entries),
        "executable_entries": int(executable.sum()),
        "executable_entries_per_year": float(executable.sum() / len(years)),
        "executable_by_year": {
            str(year): int(annual.get(year, 0)) for year in years
        },
        "entry_at_or_before_signal_count": int(
            entries.entry_at_or_before_signal.fillna(False).sum()
        ),
        "buy_at_or_above_up_limit_count": int(
            entries.buy_at_or_above_up_limit.fillna(False).sum()
        ),
        "post_period_signal_count": int(
            (~entries.signal_date.dt.year.isin(years)).sum()
        ),
        "hashes": {
            "entries": sha256(paths["entries"]),
            "actions": sha256(paths["actions"]),
            "execution_state": sha256(paths["execution_state"]),
        },
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods = {
        "DEVELOPMENT": build_period_stage_a("DEVELOPMENT", DEVELOPMENT_YEARS)
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "FIXED_THREE_DAY_CONFIRMATION_A80_DEVELOPMENT_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes("DEVELOPMENT"),
        "periods": periods,
        "development_returns_rebuilt": "NO",
        "diagnostic_outcomes_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V23Error("Stage-A freeze missing")
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
    identities = source_hashes("DEVELOPMENT")
    if identities != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), identities]
    paths = output_paths("DEVELOPMENT")
    current = {
        name: sha256(paths[name])
        for name in ("entries", "actions", "execution_state")
    }
    expected = freeze["periods"]["DEVELOPMENT"]["hashes"]
    if current != expected:
        drift["development_stage_a_files"] = [expected, current]
    if drift:
        raise V23Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def enrich_result(
    label: str, years: tuple[int, ...], result: dict[str, Any]
) -> dict[str, Any]:
    paths = output_paths(label)
    accepted = pd.read_parquet(paths["root"] / "portfolio_accepted.parquet")
    outcomes = pd.read_parquet(paths["outcomes"])
    for frame, column in ((accepted, "entry_date"), (outcomes, "entry_date")):
        frame[column] = pd.to_datetime(frame[column])
    yearly = (
        accepted.assign(_year=accepted.entry_date.dt.year)
        .groupby("_year")
        .net_return.agg(
            trades="size",
            mean_net="mean",
            median_net="median",
            win=lambda values: values.gt(0).mean(),
        )
    )
    yearly_payload = {
        str(int(index)): {
            "trades": int(row.trades),
            "mean_net": float(row.mean_net),
            "median_net": float(row.median_net),
            "win": float(row.win),
        }
        for index, row in yearly.iterrows()
    }
    combined = result["portfolio"]["COMBINED"]
    result.update(
        {
            "rule": "THREE_DAY_HIGH_BREAK_A80_H20",
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
            "maximum_exit_date_used": str(
                pd.Timestamp(outcomes.exit_date.max()).date()
            ),
            "post_2023_signal_count": int(
                pd.to_datetime(outcomes.signal_date)
                .gt(pd.Timestamp("2023-12-31"))
                .sum()
            ),
        }
    )
    return result


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    signal_end, tail_end, expected_years = period_bounds(label)
    if tuple(years) != tuple(expected_years):
        raise V23Error(f"{label} year contract mismatch")
    with v23_runtime():
        result = first_reversal.repair.run_period_stage_b(
            label, signal_end, tail_end, years
        )
    return enrich_result(label, years, result)


def development_checks(item: dict[str, Any]) -> dict[str, bool]:
    return {
        "accepted_trades_per_year_gt_50": (
            item["portfolio_accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR
        ),
        "portfolio_mean_net_ge_3pct": item["portfolio_mean_net"] >= 0.03,
        "portfolio_median_net_positive": item["portfolio_median_net"] > 0,
        "portfolio_severe10_le_15pct": item["portfolio_severe10"] <= 0.15,
        "positive_trade_mean_years_eq_5": item["positive_trade_mean_years"] == 5,
        "positive_portfolio_years_ge_4": item["positive_portfolio_years"] >= 4,
        "attack_date_equal_mean_positive": item["attack_date_equal_mean"] > 0,
        "post_2023_signal_count_zero": item["post_2023_signal_count"] == 0,
    }


def diagnostic_checks(item: dict[str, Any]) -> dict[str, bool]:
    yearly = item["accepted_trade_yearly"]
    y2022 = yearly.get("2022", {})
    y2023 = yearly.get("2023", {})
    annual_returns = item["portfolio"]["COMBINED"]["annual_returns"]
    return {
        "accepted_trades_per_year_gt_50": (
            item["portfolio_accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR
        ),
        "combined_mean_net_ge_3pct": item["portfolio_mean_net"] >= 0.03,
        "combined_median_net_positive": item["portfolio_median_net"] > 0,
        "combined_severe10_le_15pct": item["portfolio_severe10"] <= 0.15,
        "year_2022_trade_mean_positive": float(y2022.get("mean_net", -1.0)) > 0,
        "year_2023_trade_mean_ge_1pct": float(y2023.get("mean_net", -1.0)) >= 0.01,
        "year_2023_trade_median_nonnegative": float(
            y2023.get("median_net", -1.0)
        )
        >= 0,
        "year_2023_win_ge_50pct": float(y2023.get("win", -1.0)) >= 0.50,
        "year_2022_portfolio_return_positive": float(
            annual_returns.get("2022", 0.0)
        )
        > 0,
        "year_2023_portfolio_return_positive": float(
            annual_returns.get("2023", 0.0)
        )
        > 0,
        "post_2023_signal_count_zero": item["post_2023_signal_count"] == 0,
    }


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
            "THREE_DAY_CONFIRMED_A80_DEVELOPMENT_CANDIDATE"
            if passed
            else "THREE_DAY_CONFIRMED_A80_DEVELOPMENT_FAILED"
        ),
        "development_outcomes_opened": "YES",
        "diagnostic_outcomes_opened": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    if passed:
        diagnostic_period = build_period_stage_a(
            "POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS
        )
        write_json(
            DIAGNOSTIC_FREEZE,
            {
                "experiment": EXPERIMENT,
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_THREE_DAY_A80_REPLAY",
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "diagnostic_source_hashes": source_hashes(
                    "POST_OBSERVATION_DIAGNOSTIC"
                ),
                "diagnostic_period": diagnostic_period,
                "diagnostic_outcomes_opened": "NO",
            },
        )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V23Error("Development produced no diagnostic freeze")
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
    identities = source_hashes("POST_OBSERVATION_DIAGNOSTIC")
    if identities != freeze.get("diagnostic_source_hashes"):
        drift["diagnostic_source_hashes"] = [
            freeze.get("diagnostic_source_hashes"),
            identities,
        ]
    paths = output_paths("POST_OBSERVATION_DIAGNOSTIC")
    current = {
        name: sha256(paths[name])
        for name in ("entries", "actions", "execution_state")
    }
    expected = freeze["diagnostic_period"]["hashes"]
    if current != expected:
        drift["diagnostic_stage_a_files"] = [expected, current]
    if drift:
        raise V23Error(f"diagnostic freeze drift: {drift}")
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
            "THREE_DAY_CONFIRMED_A80_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "THREE_DAY_CONFIRMED_A80_POST_OBSERVATION_FAILED"
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


def yearly_rows(item: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    annual_returns = item["portfolio"]["COMBINED"]["annual_returns"]
    for year, values in item["accepted_trade_yearly"].items():
        rows.append(
            f"|{year}|{values['trades']}|{pct(values['mean_net'])}|"
            f"{pct(values['median_net'])}|{pct(values['win'])}|"
            f"{pct(annual_returns.get(year, 0.0))}|"
        )
    return rows


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    item = development["rule_result"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Fixed rule",
        "",
        "First completed close above the prior three-session high; next legal minute-open entry; A80 target; H20 fallback.",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        f"Accepted {item['portfolio_accepted_trades']} ({item['portfolio_accepted_trades_per_year']:.1f}/year); mean {pct(item['portfolio_mean_net'])}; median {pct(item['portfolio_median_net'])}; win {pct(item['portfolio_win'])}; severe10 {pct(item['portfolio_severe10'])}; CAGR {pct(item['portfolio_cagr'])}; MaxDD {pct(item['portfolio_max_drawdown'])}.",
        "",
        "|Year|Trades|Mean|Median|Win|Portfolio return|",
        "|---|---:|---:|---:|---:|---:|",
        *yearly_rows(item),
    ]
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        observed = result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"Verdict: `{result['verdict']}`.",
            f"Accepted/year: {observed['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(observed['portfolio_mean_net'])}; median: {pct(observed['portfolio_median_net'])}; win: {pct(observed['portfolio_win'])}; severe10: {pct(observed['portfolio_severe10'])}.",
            "",
            "|Year|Trades|Mean|Median|Win|Portfolio return|",
            "|---|---:|---:|---:|---:|---:|",
            *yearly_rows(observed),
        ]
    else:
        lines += ["", "2022-2023 V23 outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- No trigger or target grid was searched.",
        "- Frequency must remain strictly above 50 accepted trades/year; there is no upper cap.",
        "- Every signal and entry is causal; T+1, limits, suspensions, actual execution, costs, and QD-010 are enforced by the frozen replay.",
        "- 2022-2023 is post-observation diagnostic evidence, not pristine validation.",
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
