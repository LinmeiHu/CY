#!/usr/bin/env python3
# ruff: noqa: E501
"""Causal capitulation-repair strategy below a clean overhead true gap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    ashare_below_gap_rebound_v1_core as core,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_reversal_repair_v1 as v1,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-CAPITULATION-REPAIR-V3"
START_HEAD = "70b7efbfcc88a81903d5ca814c0acb9f4e289a76"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_capitulation_repair_v3"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
VALIDATION_FREEZE = OS / f"artifacts/{EXPERIMENT}_validation_freeze.json"
VALIDATION_RESULT = OS / f"artifacts/{EXPERIMENT}_validation_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
VALIDATION_YEARS = (2022, 2023)
MIN_RECOVERY = 0.05
TARGET_FRACTION = 0.80
TIME_STOP = 20


def write_json(path: Path, value: Any) -> None:
    v1.write_json(path, value)


def sha256(path: Path) -> str:
    return v1.sha256(path)


def contract_value() -> dict[str, Any]:
    base = v1.contract_value()
    base["experiment"] = EXPERIMENT
    base["economic_hypothesis"] = (
        "A downward true gap formed during an existing decline can remain clean "
        "overhead repair space. After a causal washout at least 10% below L, "
        "require a 5% rebound from the recent low and the first completed daily "
        "MA5 reclaim; enter next legal minute open and monetize 80% of the "
        "remaining path toward L without entering the gap."
    )
    base["formation_gate"] = "20-session pre-gap coordinate return <= 0"
    base["reversal_gate"] = {
        "maximum_post_gap_depth": ">= 10% below L",
        "signal_still_below_L": ">= 5% below L",
        "recent_low_age": "2 through 10 completed sessions",
        "minimum_recovery_from_20_session_low": MIN_RECOVERY,
        "trigger": "first completed daily MA5 reclaim",
        "missing_policy": "FAIL_CLOSED",
    }
    base["exit"]["profit_target"] = "entry + 0.80*(L-entry)"
    base["exit"]["time_stop"] = "H20"
    base["exit"]["failure_stop"] = "NONE"
    base["validation_status_disclosure"] = (
        "2022-2023 aggregate outcomes from V1 and V2 were already observed. "
        "V3 is a post-observation robustness diagnostic, not pristine OOS."
    )
    return base


def persist_contracts() -> dict[str, str]:
    contract = contract_value()
    spec = {
        "experiment": EXPERIMENT,
        "status": "CAPITULATION_REPAIR_FIXED_BEFORE_V3_2022_2023_ROW_OR_OUTCOME_READ",
        "contract": contract,
        "dependency_hashes": {
            "v1_runner": sha256(Path(v1.__file__)),
            "v1_core": sha256(Path(core.__file__)),
        },
        "research_disclosure": (
            "The natural 5% recovery confirmation and 80%-to-L target were "
            "selected using 2014-2021 Development. No V3 2022-2023 row-level "
            "feature, signal, trade, or outcome was inspected during design."
        ),
    }
    write_json(CONTRACT, contract)
    write_json(SPEC, spec)
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def fixed_signal_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame.exact_minute_history.fillna(False)
        & frame.pre_gap_inside_density_relative_local.le(1.0)
        & frame.pre_gap_corridor_density_relative_local.le(1.0)
        & frame.pre_gap_return_20d.le(0.0)
        & frame.recovery_from_low20.ge(MIN_RECOVERY)
    ).fillna(False)


def prepare_candidates(
    raw: pd.DataFrame, daily: pd.DataFrame, root: Path, end: pd.Timestamp
) -> pd.DataFrame:
    root.mkdir(parents=True, exist_ok=True)
    v1.configure_external(root, end)
    candidates = raw.loc[raw.form.eq("MA5_RECLAIM")].copy()
    if "signal_time" not in candidates:
        candidates["signal_time"] = pd.to_datetime(candidates.signal_date) + pd.Timedelta(
            hours=15
        )
    candidates = candidates.sort_values(
        ["signal_time", "symbol", "L", "gap_id"], kind="mergesort"
    ).drop_duplicates(["symbol", "signal_date"], keep="first")
    candidates.to_parquet(
        root / "all_signal_candidates.parquet", index=False, compression="zstd"
    )
    vap, _profiles = v1.build_vap_for_signals(candidates, daily)
    panel = candidates.merge(vap, on="gap_id", how="left", validate="one_to_one")
    selected = panel.loc[fixed_signal_mask(panel)].copy()
    selected["signal_year"] = pd.to_datetime(selected.signal_date).dt.year
    selected["decision_latest_timestamp"] = selected.signal_time
    selected["feature_uses_post_signal_information"] = False
    selected = selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    if selected.empty:
        raise RuntimeError("V3 fixed signal selection empty")
    selected.to_parquet(root / "signals.parquet", index=False, compression="zstd")
    return selected


def run_selected(
    selected: pd.DataFrame,
    daily: pd.DataFrame,
    root: Path,
    end: pd.Timestamp,
    years: tuple[int, ...],
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    v1.configure_external(root, end)
    selected.to_parquet(v1.SIGNALS, index=False, compression="zstd")
    entries = v1.build_entries(selected)
    minutes = v1.build_minute_path(entries, daily)
    outcomes = v1.build_outcomes(
        entries,
        minutes,
        daily,
        alphas=(TARGET_FRACTION,),
        horizons=(TIME_STOP,),
        stops=("NONE",),
    )
    outcomes["entry_date"] = pd.to_datetime(outcomes.entry_date)
    portfolio = v1.run_portfolio(outcomes, daily, years)
    return outcomes, portfolio, entries


def audit_values(
    selected: pd.DataFrame, entries: pd.DataFrame, outcomes: pd.DataFrame
) -> dict[str, Any]:
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")]
    return {
        "feature_uses_post_signal_information_count": int(
            selected.feature_uses_post_signal_information.sum()
        ),
        "entry_at_or_before_signal_count": int(
            executable.entry_time.le(executable.signal_time).sum()
        ),
        "target_at_or_above_L_count": int(
            outcomes.target_coordinate.ge(outcomes.L).sum()
        ),
        "t1_violation_count": int(
            outcomes.exit_cal_idx.le(outcomes.entry_cal_idx).sum()
        ),
        "repository_2024_plus_data_opened": "NO",
    }


def run_development() -> dict[str, Any]:
    hashes = persist_contracts()
    root = EXT_ROOT / "development"
    daily = v1.source.load_daily_through_2021()
    raw = core.build_signals()
    selected = prepare_candidates(raw, daily, root, pd.Timestamp("2021-12-31"))
    selected = selected.loc[selected.signal_year.isin(DEVELOPMENT_YEARS)].copy()
    outcomes, portfolio, entries = run_selected(
        selected, daily, root, pd.Timestamp("2021-12-31"), DEVELOPMENT_YEARS
    )
    audit = audit_values(selected, entries, outcomes)
    if any(value for key, value in audit.items() if key.endswith("_count")):
        raise RuntimeError(f"V3 Development audit failed: {audit}")
    result = {
        "experiment": EXPERIMENT,
        "label": "FIXED_RULE_DEVELOPMENT_2017_2021",
        **hashes,
        "selected_signals": len(selected),
        "entry_status": {
            str(key): int(value)
            for key, value in entries.entry_status.value_counts().items()
        },
        "complete_outcomes": len(outcomes),
        "event_metrics": v1.trade_metrics(outcomes),
        "portfolio": portfolio,
        "hashes": {
            "signals": sha256(root / "signals.parquet"),
            "entries": sha256(v1.ENTRIES),
            "outcomes": sha256(v1.OUTCOMES),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
        },
        "audit": audit,
    }
    write_json(DEVELOPMENT_RESULT, result)
    return result


def freeze_validation() -> dict[str, Any]:
    if not DEVELOPMENT_RESULT.is_file():
        raise RuntimeError("V3 Development missing")
    hashes = persist_contracts()
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    if development["contract_sha256"] != hashes["contract_sha256"]:
        raise RuntimeError("V3 contract drift")
    freeze = {
        "experiment": EXPERIMENT,
        "frozen_before_v3_validation_row_or_outcome_read": True,
        "contract_sha256": hashes["contract_sha256"],
        "spec_sha256": hashes["spec_sha256"],
        "runner_sha256": sha256(Path(__file__)),
        "v1_runner_sha256": sha256(Path(v1.__file__)),
        "v1_core_sha256": sha256(Path(core.__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "fixed_minimum_recovery": MIN_RECOVERY,
        "fixed_target_fraction": TARGET_FRACTION,
        "fixed_time_stop": TIME_STOP,
        "validation_period": ["2022-01-01", "2023-12-31"],
        "validation_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_AFTER_V1_V2_AGGREGATES",
        "v3_validation_rows_opened": "NO",
        "v3_validation_outcomes_opened": "NO",
        "repository_2024_plus_data_opened": "NO",
    }
    write_json(VALIDATION_FREEZE, freeze)
    return freeze


def verify_freeze() -> dict[str, Any]:
    freeze = json.loads(VALIDATION_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "v1_runner_sha256": sha256(Path(v1.__file__)),
        "v1_core_sha256": sha256(Path(core.__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    if drift:
        raise RuntimeError(f"V3 freeze drift: {drift}")
    return freeze


def validation_passed(result: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    combined = result["portfolio"]["COMBINED"]
    main = result["portfolio"]["MAIN"]
    chinext = result["portfolio"]["CHINEXT"]
    checks = {
        "trade_count": 70 <= int(combined["trades"]) <= 150,
        "mean_net": float(combined["mean_net"]) >= 0.03,
        "median_net": float(combined["median_net"]) > 0,
        "both_years_positive": all(
            float(combined["annual_returns"][str(year)]) > 0
            for year in VALIDATION_YEARS
        ),
        "both_boards_positive": float(main["mean_net"]) > 0
        and float(chinext["mean_net"]) > 0,
        "severe10": float(combined["severe10"]) <= 0.15,
        "max_drawdown": float(combined["max_drawdown"]) >= -0.15,
        "excluding_best_five": float(combined["return_excluding_best_five_days"])
        > 0,
    }
    return all(checks.values()), checks


def run_validation() -> dict[str, Any]:
    freeze = verify_freeze()
    root = EXT_ROOT / "validation"
    daily = v1.load_daily(pd.Timestamp("2023-12-31"))
    gaps = core.build_all_true_gaps(daily)
    raw = core.build_ma5_signal_candidates(daily, gaps)
    raw = raw.loc[raw.signal_date.dt.year.isin(VALIDATION_YEARS)].copy()
    selected = prepare_candidates(raw, daily, root, pd.Timestamp("2023-12-31"))
    selected = selected.loc[selected.signal_year.isin(VALIDATION_YEARS)].copy()
    outcomes, portfolio, entries = run_selected(
        selected, daily, root, pd.Timestamp("2023-12-31"), VALIDATION_YEARS
    )
    audit = audit_values(selected, entries, outcomes)
    audit["validation_rule_changed_count"] = 0
    if any(value for key, value in audit.items() if key.endswith("_count")):
        raise RuntimeError(f"V3 Validation audit failed: {audit}")
    result = {
        "experiment": EXPERIMENT,
        "label": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_2022_2023",
        "selected_signals": len(selected),
        "entry_status": {
            str(key): int(value)
            for key, value in entries.entry_status.value_counts().items()
        },
        "complete_outcomes": len(outcomes),
        "event_metrics": v1.trade_metrics(outcomes),
        "portfolio": portfolio,
        "audit": audit,
        "validation_freeze_sha256": sha256(VALIDATION_FREEZE),
        "fixed_contract": {
            "minimum_recovery": freeze["fixed_minimum_recovery"],
            "target_fraction": freeze["fixed_target_fraction"],
            "time_stop": freeze["fixed_time_stop"],
        },
    }
    passed, checks = validation_passed(result)
    result["validation_checks"] = checks
    result["verdict"] = (
        "CAPITULATION_REPAIR_POST_OBSERVATION_DIAGNOSTIC_PASSED"
        if passed
        else "CAPITULATION_REPAIR_POST_OBSERVATION_DIAGNOSTIC_FAILED"
    )
    write_json(VALIDATION_RESULT, result)
    return result


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    validation = (
        json.loads(VALIDATION_RESULT.read_text(encoding="utf-8"))
        if VALIDATION_RESULT.is_file()
        else None
    )
    combined = development["portfolio"]["COMBINED"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Mechanism",
        "",
        "Buy below L only after a true-gap decline has washed out and then recovered at least 5% into its first daily MA5 reclaim. Exit after 80% of the remaining path to L, still below the gap.",
        "",
        "## Development 2017-2021",
        "",
        f"- Signals / complete outcomes: {development['selected_signals']} / {development['complete_outcomes']}",
        f"- K20 trades / mean / median: {combined['trades']} / {combined['mean_net']:.2%} / {combined['median_net']:.2%}",
        f"- Severe10 / CAGR / MaxDD / Sharpe: {combined['severe10']:.2%} / {combined['cagr']:.2%} / {combined['max_drawdown']:.2%} / {combined['sharpe']:.3f}",
        "",
    ]
    if validation is None:
        lines += ["## 2022-2023 diagnostic", "", "Not opened.", ""]
    else:
        value = validation["portfolio"]["COMBINED"]
        lines += [
            "## 2022-2023 post-observation robustness diagnostic",
            "",
            "This period is not pristine OOS because earlier V1/V2 aggregate outcomes were already observed.",
            f"- Signals / complete outcomes: {validation['selected_signals']} / {validation['complete_outcomes']}",
            f"- K20 trades / mean / median: {value['trades']} / {value['mean_net']:.2%} / {value['median_net']:.2%}",
            f"- Severe10 / total return / MaxDD: {value['severe10']:.2%} / {value['total_return']:.2%} / {value['max_drawdown']:.2%}",
            f"- Verdict: {validation['verdict']}",
            "",
        ]
    lines += [
        "## Governance",
        "",
        "No 2024+ data was opened. V1 and V2 implementation files were not modified.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=("development", "freeze-validation", "validation", "report")
    )
    args = parser.parse_args()
    if args.stage == "development":
        print(json.dumps(run_development(), indent=2, default=str))
    elif args.stage == "freeze-validation":
        print(json.dumps(freeze_validation(), indent=2, default=str))
    elif args.stage == "validation":
        print(json.dumps(run_validation(), indent=2, default=str))
    else:
        render_report()


if __name__ == "__main__":
    main()
