#!/usr/bin/env python3
# ruff: noqa: E501
"""Test one natural dry-base state on the broad frozen V13 reversal lane."""

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
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-DRY-BASE-REVERSAL-V22"
START_HEAD = "5d4a689609"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_dry_base_reversal_v22"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

DRY3_MAX = 1.0
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = replay_lane.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = replay_lane.DIAGNOSTIC_YEARS


class V22Error(RuntimeError):
    """Fail-closed V22 research error."""


def sha256(path: Path) -> str:
    return replay_lane.sha256(path)


def write_json(path: Path, value: Any) -> None:
    replay_lane.write_json(path, value)


def source_entries_path(label: str) -> Path:
    return replay_lane.source_paths(label)["entries"]


def selected_entries_path(label: str) -> Path:
    # Preserve the replay helper's mechanical filename inside the isolated V22 root.
    return EXT_ROOT / label.lower() / "d30_selected_entries.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d30"


@contextmanager
def v22_runtime() -> Iterator[None]:
    old_root = replay_lane.EXT_ROOT
    try:
        replay_lane.EXT_ROOT = EXT_ROOT
        yield
    finally:
        replay_lane.EXT_ROOT = old_root


def dry_base_mask(frame: pd.DataFrame) -> pd.Series:
    return frame.dry3.le(DRY3_MAX).fillna(False)


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A causal first reversal below a clean true gap is more credible when the "
            "three completed sessions immediately before the reversal show no turnover "
            "expansion versus the preceding local baseline. This represents contraction "
            "of active supply before demand turns price, while preserving the broad V13 "
            "population needed for more than 50 accepted trades per year."
        ),
        "source_strategy": first_reversal.EXPERIMENT,
        "source_trigger": "PRIOR_HIGH_REVERSAL",
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "single_fixed_gate": {
            "condition": "dry3 <= 1.0",
            "dry3_definition": (
                "mean turnover_fraction over the three completed sessions immediately "
                "before the signal divided by mean turnover_fraction over all 19 "
                "completed pre-signal sessions in the frozen 20-session signal window"
            ),
            "known_time": "before the completed daily reversal signal",
            "missing_policy": "fail closed",
            "threshold_semantics": "natural no-expansion boundary; no numeric search",
        },
        "removed_post_v13_gates": [
            "D30 prior drawdown",
            "M20 decline duration",
            "AGE30 freshness",
            "H6 net-to-L headroom",
        ],
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
        "development_success_contract": {
            "accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "frequency_has_no_upper_cap": True,
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
            "development_informed_single_rule": True,
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
            "status": "DEVELOPMENT_INFORMED_SINGLE_NATURAL_DRY_BASE_GATE",
            "frequency_goal": "strictly more than 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "dry3 <= 1 was promoted after direct 2017-2021 analysis because it "
                "preserved all five positive trade-mean years; no dry threshold grid is run."
            ),
            "diagnostic_disclosure": (
                "Identity-only counts show 101 executable 2022-2023 candidates before "
                "outcomes; exact 2023 mean/median/win gates are frozen before replay."
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
        "development_v13_entries": source_entries_path("DEVELOPMENT"),
    }
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V22Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def diagnostic_source_hashes() -> dict[str, str]:
    values = {
        "v13_diagnostic_result": first_reversal.DIAGNOSTIC_RESULT,
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
        raise V22Error(f"missing diagnostic source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(source_entries_path(label))
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    if entries.gap_id.duplicated().any():
        raise V22Error(f"{label} duplicate source gap identity")
    selected = entries.loc[dry_base_mask(entries)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(years)].copy()
    selected["dry_base_gate"] = True
    selected["dry_base_latest_timestamp"] = selected.signal_time - pd.Timedelta(
        days=1
    )
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
        "stage": "DEVELOPMENT_FIXED_DRY3_NATURAL_BOUNDARY_FREEZE",
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
        raise V22Error("Stage-A freeze missing")
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
        raise V22Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    with v22_runtime():
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
    item["rule"] = "V13_PRIOR_HIGH_REVERSAL_PLUS_DRY3_LE_1"
    return item


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
            "DRY_BASE_REVERSAL_DEVELOPMENT_CANDIDATE"
            if passed
            else "DRY_BASE_REVERSAL_DEVELOPMENT_FAILED"
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
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_DRY_BASE_REVERSAL_REPLAY",
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
        raise V22Error("Development produced no diagnostic freeze")
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
        raise V22Error(f"diagnostic freeze drift: {drift}")
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
            "DRY_BASE_REVERSAL_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "DRY_BASE_REVERSAL_POST_OBSERVATION_FAILED"
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
    v20 = json.loads(
        (
            OS
            / "artifacts/ASHARE-TRUE-GAP-BELOW-L-ECONOMIC-HEADROOM-V20_development_result.json"
        ).read_text(encoding="utf-8")
    )["rule_result"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Fixed rule",
        "",
        "Frozen V13 prior-high reversal population plus one natural condition: `dry3 <= 1`. Post-V13 D30/M20/AGE30/H6 gates are not carried forward.",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|V20 reference|{v20['portfolio_accepted_trades']}|{v20['portfolio_accepted_trades_per_year']:.1f}|{pct(v20['portfolio_mean_net'])}|{pct(v20['portfolio_median_net'])}|{pct(v20['portfolio_win'])}|{pct(v20['portfolio_severe10'])}|{pct(v20['portfolio_cagr'])}|{pct(v20['portfolio_max_drawdown'])}|",
        f"|V22 dry base|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|",
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
        lines += ["", "2022-2023 V22 outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- dry3 uses only the three and 19 completed sessions preceding the signal.",
        "- Frequency must remain strictly above 50 accepted trades/year; there is no upper cap.",
        "- No exit rule, target, horizon, cost, portfolio, T+1, limit, suspension, or QD-010 semantic changed.",
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
