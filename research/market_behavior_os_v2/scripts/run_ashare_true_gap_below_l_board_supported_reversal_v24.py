#!/usr/bin/env python3
# ruff: noqa: E501
"""Test one same-day nonnegative-board support gate on the broad V13 lane."""

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
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as replay_lane,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-BOARD-SUPPORTED-REVERSAL-V24"
START_HEAD = "8b4f7a4a47"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_board_supported_reversal_v24"
)
BOARD_CONTEXT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_v6_full_signal_strategy_research_v1/board_daily_context.parquet"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

BOARD_RETURN_MIN = 0.0
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = replay_lane.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = replay_lane.DIAGNOSTIC_YEARS


class V24Error(RuntimeError):
    """Fail-closed V24 research error."""


def sha256(path: Path) -> str:
    return replay_lane.sha256(path)


def write_json(path: Path, value: Any) -> None:
    replay_lane.write_json(path, value)


def source_entries_path(label: str) -> Path:
    return replay_lane.source_paths(label)["entries"]


def selected_entries_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d30_selected_entries.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d30"


@contextmanager
def v24_runtime() -> Iterator[None]:
    old_root = replay_lane.EXT_ROOT
    try:
        replay_lane.EXT_ROOT = EXT_ROOT
        yield
    finally:
        replay_lane.EXT_ROOT = old_root


def board_support_mask(frame: pd.DataFrame) -> pd.Series:
    return frame.signal_board_return.ge(BOARD_RETURN_MIN).fillna(False)


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A first stock-level reversal below a clean true gap has a greater chance "
            "of propagating when its board has stopped falling by the same completed "
            "close. A nonnegative same-day equal-weight board return is a causal zero "
            "boundary for common repair support, preserving early entry and reward space."
        ),
        "source_strategy": first_reversal.EXPERIMENT,
        "source_trigger": "PRIOR_HIGH_REVERSAL",
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "single_fixed_gate": {
            "condition": "same completed signal-day equal-weight board return >= 0",
            "board_groups": ["MAIN", "CHINEXT"],
            "context_source": str(BOARD_CONTEXT),
            "known_time": "signal-day close, before next-session entry",
            "missing_policy": "fail closed",
            "threshold_semantics": "natural zero; no numeric search",
        },
        "unchanged_v13": {
            "strict_true_gap_and_clean_vap_corridor": True,
            "no_L_touch_before_signal": True,
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
        "not_carried_forward": [
            "D30",
            "M20",
            "AGE30",
            "H6",
            "dry3",
            "three-day confirmation",
            "V21 progress-protection exit",
        ],
        "development_success_contract": {
            "accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "portfolio_mean_net_min": 0.03,
            "portfolio_median_net_positive": True,
            "portfolio_severe10_max": 0.15,
            "positive_trade_mean_years_min": 4,
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
            "development_informed_single_natural_gate": True,
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
            "status": "DEVELOPMENT_INFORMED_SINGLE_ZERO_BOUNDARY_BOARD_SUPPORT_GATE",
            "frequency_goal": "strictly more than 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "same-day board return >= 0 was promoted from direct 2017-2021 natural-state analysis; no board threshold grid is run."
            ),
            "diagnostic_disclosure": (
                "Identity-only audit found 126 executable 2022-2023 candidates before outcomes; exact 2023 gates are frozen before replay."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v13_runner": Path(first_reversal.__file__),
        "v13_contract": first_reversal.CONTRACT,
        "v13_stage_a_freeze": first_reversal.STAGE_A_FREEZE,
        "v13_development_result": first_reversal.DEVELOPMENT_RESULT,
        "v16_replay_helper": Path(replay_lane.__file__),
        "board_context": BOARD_CONTEXT,
        "development_v13_entries": source_entries_path("DEVELOPMENT"),
    }
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V24Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def diagnostic_source_hashes() -> dict[str, str]:
    values = {
        "v13_diagnostic_result": first_reversal.DIAGNOSTIC_RESULT,
        "board_context": BOARD_CONTEXT,
        "diagnostic_v13_entries": source_entries_path(
            "POST_OBSERVATION_DIAGNOSTIC"
        ),
        "diagnostic_v13_outcomes": replay_lane.source_paths(
            "POST_OBSERVATION_DIAGNOSTIC"
        )["outcomes"],
        "diagnostic_v13_outcome_daily": replay_lane.source_paths(
            "POST_OBSERVATION_DIAGNOSTIC"
        )["outcome_daily"],
    }
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V24Error(f"missing diagnostic source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def attach_board_context(entries: pd.DataFrame) -> pd.DataFrame:
    context = pd.read_parquet(BOARD_CONTEXT, columns=["trade_date", "group_id", "ret"])
    context["trade_date"] = pd.to_datetime(context.trade_date)
    if context.duplicated(["trade_date", "group_id"]).any():
        raise V24Error("duplicate board context identity")
    merged = entries.merge(
        context.rename(columns={"ret": "signal_board_return"}),
        left_on=["signal_date", "board"],
        right_on=["trade_date", "group_id"],
        how="left",
        validate="many_to_one",
    )
    if merged.signal_board_return.isna().any():
        raise V24Error("missing signal-day board context")
    return merged.drop(columns=["trade_date", "group_id"])


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(source_entries_path(label))
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    if entries.gap_id.duplicated().any():
        raise V24Error(f"{label} duplicate source gap identity")
    entries = attach_board_context(entries)
    selected = entries.loc[board_support_mask(entries)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(years)].copy()
    selected["board_support_gate"] = True
    selected["board_context_latest_timestamp"] = selected.signal_time
    selected["feature_uses_post_signal_information"] = False
    selected = selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    output = selected_entries_path(label)
    replay_lane.repair.write_parquet(selected, output)
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
        "feature_uses_post_signal_information_count": 0,
        "selected_entries_sha256": sha256(output),
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods = {
        "DEVELOPMENT": build_period_stage_a("DEVELOPMENT", DEVELOPMENT_YEARS)
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_FIXED_NONNEGATIVE_BOARD_SUPPORT_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "periods": periods,
        "development_portfolio_replay_run": "NO",
        "diagnostic_outcomes_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V24Error("Stage-A freeze missing")
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
    current = sha256(selected_entries_path("DEVELOPMENT"))
    expected = freeze["periods"]["DEVELOPMENT"]["selected_entries_sha256"]
    if current != expected:
        drift["development_selected_entries"] = [expected, current]
    if drift:
        raise V24Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    with v24_runtime():
        item = replay_lane.run_lane(label, years)
    accepted = pd.read_parquet(lane_root(label) / "portfolio_accepted.parquet")
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    win = (
        accepted.assign(_year=accepted.entry_date.dt.year)
        .groupby("_year")
        .net_return.apply(lambda values: float(values.gt(0).mean()))
    )
    for year, value in win.items():
        item["accepted_trade_yearly"][str(int(year))]["win"] = float(value)
    item["rule"] = "V13_PRIOR_HIGH_REVERSAL_PLUS_NONNEGATIVE_BOARD"
    return item


def development_checks(item: dict[str, Any]) -> dict[str, bool]:
    return {
        "accepted_trades_per_year_gt_50": (
            item["portfolio_accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR
        ),
        "portfolio_mean_net_ge_3pct": item["portfolio_mean_net"] >= 0.03,
        "portfolio_median_net_positive": item["portfolio_median_net"] > 0,
        "portfolio_severe10_le_15pct": item["portfolio_severe10"] <= 0.15,
        "positive_trade_mean_years_ge_4": item["positive_trade_mean_years"] >= 4,
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
            "BOARD_SUPPORTED_REVERSAL_DEVELOPMENT_CANDIDATE"
            if passed
            else "BOARD_SUPPORTED_REVERSAL_DEVELOPMENT_FAILED"
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
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_BOARD_SUPPORTED_REPLAY",
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "diagnostic_source_hashes": diagnostic_source_hashes(),
                "diagnostic_period": diagnostic_period,
                "diagnostic_selected_entries_sha256": sha256(
                    selected_entries_path("POST_OBSERVATION_DIAGNOSTIC")
                ),
                "diagnostic_outcomes_opened": "NO",
            },
        )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V24Error("Development produced no diagnostic freeze")
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
    identities = diagnostic_source_hashes()
    if identities != freeze.get("diagnostic_source_hashes"):
        drift["diagnostic_source_hashes"] = [
            freeze.get("diagnostic_source_hashes"),
            identities,
        ]
    if drift:
        raise V24Error(f"diagnostic freeze drift: {drift}")
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
            "BOARD_SUPPORTED_REVERSAL_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "BOARD_SUPPORTED_REVERSAL_POST_OBSERVATION_FAILED"
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
        "Frozen V13 prior-high reversal plus same completed signal-day equal-weight board return >= 0. A67/H20 unchanged.",
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
        lines += ["", "2022-2023 V24 outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Board context is the completed signal-day equal-weight board return and is known before entry.",
        "- Frequency must remain strictly above 50 accepted trades/year; there is no upper cap.",
        "- V13 signal, entry, A67, H20, costs, portfolio, T+1, limits, suspensions, and QD-010 are unchanged.",
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
