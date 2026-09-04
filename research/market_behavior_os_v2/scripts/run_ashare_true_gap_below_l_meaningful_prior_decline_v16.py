#!/usr/bin/env python3
# ruff: noqa: E501
"""Test one fixed, causal prior-decline gate on the V13 reversal strategy."""

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
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-MEANINGFUL-PRIOR-DECLINE-V16"
START_HEAD = "09231cfece"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_meaningful_prior_decline_v16"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

PRIOR_DRAWDOWN_MIN = 0.30
TARGET_FRACTION = 0.67
TIME_STOP = 20
PORTFOLIO_K = 80
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)


class V16Error(RuntimeError):
    """Fail-closed V16 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def source_root(label: str) -> Path:
    return first_reversal.trigger_root("PRIOR_HIGH_REVERSAL") / label.lower()


def source_paths(label: str) -> dict[str, Path]:
    root = source_root(label)
    return {
        "root": root,
        "entries": root / "entries.parquet",
        "outcomes": root / "outcomes.parquet",
        "outcome_daily": root / "outcome_daily.parquet",
    }


def selected_entries_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d30_selected_entries.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d30"


def prior_decline_mask(frame: pd.DataFrame) -> pd.Series:
    """A missing prior high/decline fails closed."""
    return frame.pre_gap_drawdown_from_120d_peak.ge(PRIOR_DRAWDOWN_MIN).fillna(False)


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A strict low-inventory true gap formed after at least a 30% decline "
            "from the highest coordinate high in the prior 120 completed sessions "
            "is more likely to be part of a meaningful liquidation episode than an "
            "ordinary sideways-market gap. The unchanged first daily reversal below L "
            "may then retain more absolute rebound economics."
        ),
        "source_strategy": first_reversal.EXPERIMENT,
        "source_trigger": "PRIOR_HIGH_REVERSAL",
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "single_fixed_gate": {
            "condition": "pre_gap_drawdown_from_120d_peak >= 0.30",
            "definition": (
                "1 - gap-day coordinate low / maximum coordinate high over the exact "
                "120 completed sessions preceding true-gap formation"
            ),
            "known_time": "gap formation close; strictly before V13 reversal signal",
            "missing_policy": "fail closed",
            "threshold_search": "NONE",
        },
        "unchanged": {
            "true_gap_and_strict_vap_corridor": True,
            "no_L_touch_before_signal": True,
            "maximum_depth_below_L_min": 0.10,
            "signal_depth_below_L_min": 0.05,
            "trigger": "first completed daily close > previous completed daily high",
            "entry": "next legal buyable 1-minute open",
            "target": "entry + 0.67*(L-entry), strictly below L",
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
            "status": "OUTCOME_BLIND_SINGLE_FIXED_MEANINGFUL_PRIOR_DECLINE_GATE",
            "frequency_goal": "at least 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "D30 is one natural, economically interpretable gate rather than a "
                "threshold search. The V13 source signal and all trade semantics are unchanged."
            ),
            "diagnostic_disclosure": (
                "Only D30 may open 2022-2023 outcomes after a Development pass; that "
                "period remains post-observation evidence."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def stage_a_source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v13_runner": Path(first_reversal.__file__),
        "v13_contract": first_reversal.CONTRACT,
        "v13_stage_a_freeze": first_reversal.STAGE_A_FREEZE,
    }
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        values[f"{label.lower()}_entries"] = source_paths(label)["entries"]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V16Error(f"missing Stage-A source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(source_paths(label)["entries"])
    for column in ("gap_date", "signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    if entries.gap_id.duplicated().any():
        raise V16Error(f"{label} duplicate source gap identity")
    if entries.pre_gap_drawdown_from_120d_peak.isna().any():
        raise V16Error(f"{label} missing required prior-decline feature")
    if entries.gap_date.ge(entries.signal_time).any():
        raise V16Error(f"{label} prior-decline feature not known before signal")
    selected = entries.loc[prior_decline_mask(entries)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(years)].copy()
    selected["prior_decline_gate"] = True
    selected["prior_decline_feature_latest_timestamp"] = selected.gap_date + pd.Timedelta(hours=15)
    selected["feature_uses_post_signal_information"] = (
        selected.prior_decline_feature_latest_timestamp > selected.signal_time
    )
    if selected.feature_uses_post_signal_information.any():
        raise V16Error(f"{label} prior-decline causality failure")
    selected = selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    output = selected_entries_path(label)
    repair.write_parquet(selected, output)
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
        "post_period_signal_count": 0,
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
        "stage": "OUTCOME_BLIND_FIXED_D30_GATE_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_source_hashes": stage_a_source_hashes(),
        "prior_drawdown_min": PRIOR_DRAWDOWN_MIN,
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
        raise V16Error("Stage-A freeze missing")
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
    source_hashes = stage_a_source_hashes()
    if source_hashes != freeze.get("stage_a_source_hashes"):
        drift["stage_a_source_hashes"] = [
            freeze.get("stage_a_source_hashes"),
            source_hashes,
        ]
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        current = sha256(selected_entries_path(label))
        expected = freeze["periods"][label]["selected_entries_sha256"]
        if current != expected:
            drift[f"{label}_selected_entries"] = [expected, current]
    if drift:
        raise V16Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    paths = source_paths(label)
    selected = pd.read_parquet(selected_entries_path(label))
    source_outcomes = pd.read_parquet(paths["outcomes"])
    daily = pd.read_parquet(paths["outcome_daily"])
    for frame, columns in (
        (selected, ("signal_date", "entry_date", "entry_time")),
        (source_outcomes, ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time")),
        (daily, ("trade_date",)),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    ids = set(executable.gap_id.astype(str))
    outcomes = source_outcomes.loc[source_outcomes.gap_id.astype(str).isin(ids)].copy()
    if len(outcomes) != len(executable) or set(outcomes.gap_id.astype(str)) != ids:
        raise V16Error(f"{label} outcome identity conservation failure")
    if not bool(outcomes.signal_date.dt.year.isin(years).all()):
        raise V16Error(f"{label} signal-period boundary failure")
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = lane_root(label)
    root.mkdir(parents=True, exist_ok=True)
    repair.write_parquet(outcomes, root / "outcomes.parquet")
    old_k = repair.v1.PORTFOLIO_K
    try:
        repair.v1.PORTFOLIO_K = PORTFOLIO_K
        repair.v1.configure_external(root, max_exit)
        replay_years = tuple(range(min(years), int(max_exit.year) + 1))
        portfolio = repair.v1.run_portfolio(
            outcomes,
            daily.loc[daily.trade_date.le(max_exit)].copy(),
            replay_years,
        )
    finally:
        repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
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
    per_date = (
        outcomes.assign(_date=outcomes.entry_date.dt.normalize())
        .groupby("_date")
        .net_return.mean()
    )
    accepted_year_counts = accepted.entry_date.dt.year.value_counts()
    return {
        "rule": "D30_PRIOR_120D_PEAK_DRAWDOWN",
        "selected_signals": len(selected),
        "executable_entries": len(executable),
        "source_complete_outcomes": len(outcomes),
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
        "attack_date_equal_mean": float(per_date.mean()),
        "largest_year_trade_share": float(
            accepted_year_counts.max() / len(accepted) if len(accepted) else 0.0
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(
            outcomes.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
        ),
        "source_hashes_opened_in_stage_b": {
            "outcomes": sha256(paths["outcomes"]),
            "outcome_daily": sha256(paths["outcome_daily"]),
        },
        "hashes": {
            "outcomes": sha256(root / "outcomes.parquet"),
            "portfolio_accepted": sha256(root / "portfolio_accepted.parquet"),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
        },
    }


def development_checks(item: dict[str, Any]) -> dict[str, bool]:
    return {
        "accepted_trades_per_year_ge_50": (
            item["portfolio_accepted_trades_per_year"]
            >= MIN_ACCEPTED_TRADES_PER_YEAR
        ),
        "portfolio_mean_net_ge_3pct": item["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": item["portfolio_median_net"] > 0,
        "severe10_le_15pct": item["portfolio_severe10"] <= 0.15,
        "positive_trade_mean_years_ge_4": item["positive_trade_mean_years"] >= 4,
        "positive_portfolio_years_ge_4": item["positive_portfolio_years"] >= 4,
        "attack_date_equal_mean_positive": item["attack_date_equal_mean"] > 0,
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
            "MEANINGFUL_PRIOR_DECLINE_DEVELOPMENT_CANDIDATE"
            if passed
            else "MEANINGFUL_PRIOR_DECLINE_DEVELOPMENT_FAILED"
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
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_FIXED_D30_OUTCOME_OPEN",
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "prior_drawdown_min": PRIOR_DRAWDOWN_MIN,
                "diagnostic_selected_entries_sha256": sha256(
                    selected_entries_path("POST_OBSERVATION_DIAGNOSTIC")
                ),
                "diagnostic_outcomes_opened": "NO",
            },
        )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V16Error("Development produced no diagnostic freeze")
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
        raise V16Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def diagnostic_checks(item: dict[str, Any]) -> dict[str, bool]:
    yearly = item["accepted_trade_yearly"]
    return {
        "accepted_trades_per_year_ge_50": (
            item["portfolio_accepted_trades_per_year"]
            >= MIN_ACCEPTED_TRADES_PER_YEAR
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
    item = run_lane("POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS)
    checks = diagnostic_checks(item)
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "diagnostic": item,
        "goal_checks": checks,
        "verdict": (
            "MEANINGFUL_PRIOR_DECLINE_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "MEANINGFUL_PRIOR_DECLINE_POST_OBSERVATION_FAILED"
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
    baseline = json.loads(first_reversal.DEVELOPMENT_RESULT.read_text(encoding="utf-8"))[
        "candidate_results"
    ]["PRIOR_HIGH_REVERSAL"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Fixed rule",
        "",
        "`pre_gap_drawdown_from_120d_peak >= 30%`; no threshold search.",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|V13 control|{baseline['portfolio_accepted_trades']}|{baseline['portfolio_accepted_trades_per_year']:.1f}|{pct(baseline['portfolio_mean_net'])}|{pct(baseline['portfolio_median_net'])}|{pct(baseline['portfolio_win'])}|{pct(baseline['portfolio_severe10'])}|{pct(baseline['portfolio_cagr'])}|{pct(baseline['portfolio_max_drawdown'])}|",
        f"|D30|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|",
    ]
    if DIAGNOSTIC_RESULT.is_file():
        diagnostic_result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        observed = diagnostic_result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"Verdict: `{diagnostic_result['verdict']}`.",
            f"Accepted/year: {observed['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(observed['portfolio_mean_net'])}; median: {pct(observed['portfolio_median_net'])}; severe10: {pct(observed['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "2022-2023 D30 outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Frequency is a floor of at least 50 accepted trades/year, never a target or upper cap.",
        "- D30 is one fixed economic rule; there is no candidate threshold selection.",
        "- Signal, strict VAP/corridor, entry, A67, H20, 40 bp, K80, limits, and QD-010 are unchanged.",
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
