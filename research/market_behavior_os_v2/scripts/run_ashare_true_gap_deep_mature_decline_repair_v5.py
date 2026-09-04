#!/usr/bin/env python3
# ruff: noqa: E501
"""Develop and diagnose one simple mature-decline below-gap repair rule.

The source execution/outcome ledger is the corrected V4R1 replay.  This runner
does not reconstruct outcomes or change execution.  Development may select
only one of three natural pre-gap drawdown levels.  The selected rule is frozen
before its 2022-2023 row-level subset is opened.  That period remains an
explicit post-observation diagnostic, never pristine validation.
"""

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
EXPERIMENT = "ASHARE-TRUE-GAP-DEEP-MATURE-DECLINE-REPAIR-V5"
START_HEAD = "20eebd0fdf"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_deep_mature_decline_repair_v5"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

THRESHOLDS = (0.40, 0.45, 0.50)
TARGET_SIGNALS_PER_YEAR = 50.0
MIN_SIGNALS_PER_YEAR = 40.0
MAX_SIGNALS_PER_YEAR = 80.0
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)


class V5Error(RuntimeError):
    """Fail-closed V5 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def source_paths(label: str) -> dict[str, Path]:
    return repair.paths(label)


def source_hashes() -> dict[str, str]:
    values = {
        "v4r1_result": repair.RESULT,
        "v4r1_stage_a_freeze": repair.STAGE_A_FREEZE,
    }
    for label in repair.PERIODS:
        for name in ("entries", "outcomes", "outcome_daily"):
            values[f"{label.lower()}_{name}"] = source_paths(label)[name]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V5Error(f"missing corrected source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A clean downward true gap is more likely to mark late-stage forced "
            "liquidation when it forms only after a deep, already-mature decline. "
            "The subsequent below-L washout and first MA5 reclaim may then monetize "
            "a reflexive repair toward, but not into, the gap."
        ),
        "source": repair.EXPERIMENT,
        "source_execution_outcomes": "UNCHANGED_AND_IDENTITY_CONSERVED",
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "candidate_family": {
            "only_added_condition": "pre_gap_drawdown_from_120d_peak >= threshold",
            "thresholds": list(THRESHOLDS),
            "threshold_meaning": (
                "causally completed maximum decline from the highest coordinate high "
                "inside the 120 completed sessions preceding gap formation"
            ),
        },
        "selector": {
            "eligibility": {
                "selected_signals_per_year": [MIN_SIGNALS_PER_YEAR, MAX_SIGNALS_PER_YEAR],
                "portfolio_mean_net_min": 0.03,
                "portfolio_median_net_positive": True,
                "portfolio_severe10_max": 0.15,
                "positive_calendar_years_min": 4,
            },
            "order": [
                "minimum absolute distance from 50 selected signals per year",
                "lower severe_loss10",
                "lower threshold",
            ],
        },
        "unchanged_v4r1": {
            "true_gap_and_vap": True,
            "washout_and_first_ma5_trigger": True,
            "next_legal_minute_entry": True,
            "target": "entry + 0.80*(L-entry)",
            "failure_stop": "NONE",
            "time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "50/50 Main/ChiNext; K20 per sleeve",
            "corporate_action_and_t1": True,
        },
        "post_2023_scope": (
            "No post-2023 signal, feature, threshold, or selection row. Existing "
            "V4R1 post-cutoff rows may be inherited only for pre-2024 trade closure."
        ),
    }


def persist_spec() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    contract_hash = sha256(CONTRACT)
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": contract_hash,
            "status": "BOUNDED_THREE_LEVEL_DEVELOPMENT_SELECTION",
            "development_selection_disclosure": (
                "The deep prior-decline mechanism and bounded 40/45/50 percent family "
                "were proposed after exploratory 2017-2021 outcome analysis."
            ),
            "diagnostic_disclosure": (
                "V4R1 aggregate 2022-2023 outcomes were already observed; the V5-specific "
                "subset is frozen before opening but remains post-observation evidence."
            ),
        },
    )
    return {"contract_sha256": contract_hash, "spec_sha256": sha256(SPEC)}


def load_source(label: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = source_paths(label)
    entries = pd.read_parquet(paths["entries"])
    outcomes = pd.read_parquet(paths["outcomes"])
    daily = pd.read_parquet(paths["outcome_daily"])
    for frame, columns in (
        (entries, ("signal_date", "signal_time", "entry_date", "entry_time")),
        (outcomes, ("signal_date", "signal_time", "entry_date", "entry_time", "exit_date", "exit_time")),
        (daily, ("trade_date",)),
    ):
        for column in columns:
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    return entries, outcomes, daily


def threshold_mask(frame: pd.DataFrame, threshold: float) -> pd.Series:
    return frame.pre_gap_drawdown_from_120d_peak.ge(float(threshold)).fillna(False)


def replay_threshold(
    label: str,
    threshold: float,
    years: tuple[int, ...],
    entries: pd.DataFrame,
    outcomes: pd.DataFrame,
    daily: pd.DataFrame,
) -> dict[str, Any]:
    selected = entries.loc[threshold_mask(entries, threshold)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(years)].copy()
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    trades = outcomes.loc[outcomes.gap_id.isin(executable.gap_id)].copy()
    if len(trades) != len(executable) or set(trades.gap_id.astype(str)) != set(executable.gap_id.astype(str)):
        raise V5Error(f"{label} threshold {threshold} outcome conservation failure")
    if trades.empty:
        raise V5Error(f"{label} threshold {threshold} has no trades")
    max_exit = pd.Timestamp(trades.exit_date.max()).normalize()
    replay_years = tuple(range(min(years), int(max_exit.year) + 1))
    replay_daily = daily.loc[daily.trade_date.le(max_exit)].copy()
    root = EXT_ROOT / label.lower() / f"d{round(threshold * 100):02d}"
    root.mkdir(parents=True, exist_ok=True)
    repair.v1.configure_external(root, max_exit)
    portfolio = repair.v1.run_portfolio(trades, replay_daily, replay_years)
    event = repair.v1.trade_metrics(trades)
    combined = portfolio["COMBINED"]
    signal_year = selected.signal_date.dt.year
    selected_by_year = {
        str(year): int(signal_year.eq(year).sum()) for year in years
    }
    trade_year = trades.entry_date.dt.year
    event_year = trades.assign(_year=trade_year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    dates = trades.entry_date.dt.normalize().value_counts()
    return {
        "threshold": float(threshold),
        "selected_signals": len(selected),
        "selected_signals_per_year": len(selected) / len(years),
        "selected_by_year": selected_by_year,
        "entry_status": selected.entry_status.value_counts().astype(int).to_dict(),
        "executable_entries": len(executable),
        "complete_outcomes": len(trades),
        "event_metrics": event,
        "event_yearly": {
            str(int(index)): {
                "trades": int(row.trades),
                "mean_net": float(row.mean_net),
                "median_net": float(row.median_net),
            }
            for index, row in event_year.iterrows()
        },
        "attack_date_equal_mean": float(
            trades.assign(_date=trades.entry_date.dt.normalize())
            .groupby("_date")
            .net_return.mean()
            .mean()
        ),
        "top_five_entry_date_event_share": float(dates.head(5).sum() / len(trades)),
        "portfolio": portfolio,
        "portfolio_mean_net": float(combined["mean_net"]),
        "portfolio_median_net": float(combined["median_net"]),
        "portfolio_severe10": float(combined["severe10"]),
        "positive_calendar_years": int(
            sum(float(combined["annual_returns"].get(str(year), 0.0)) > 0 for year in years)
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_signal_period_exit_count": int(trades.exit_date.gt(pd.Timestamp(f"{max(years)}-12-31")).sum()),
        "post_2023_signal_count": int(selected.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "hashes": {
            "fixed_trades": sha256(root / "fixed_trades.parquet"),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
            "portfolio_accepted": sha256(root / "portfolio_accepted.parquet"),
        },
    }


def eligible_candidate(item: dict[str, Any]) -> bool:
    return bool(
        MIN_SIGNALS_PER_YEAR <= item["selected_signals_per_year"] <= MAX_SIGNALS_PER_YEAR
        and item["portfolio_mean_net"] >= 0.03
        and item["portfolio_median_net"] > 0
        and item["portfolio_severe10"] <= 0.15
        and item["positive_calendar_years"] >= 4
    )


def select_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates.values() if eligible_candidate(item)]
    if not eligible:
        raise V5Error("no Development threshold passes the frozen selector")
    return sorted(
        eligible,
        key=lambda item: (
            abs(item["selected_signals_per_year"] - TARGET_SIGNALS_PER_YEAR),
            item["portfolio_severe10"],
            item["threshold"],
        ),
    )[0]


def run_development_and_freeze() -> dict[str, Any]:
    hashes = persist_spec()
    identities = source_hashes()
    entries, outcomes, daily = load_source("DEVELOPMENT")
    candidates = {
        f"D{round(threshold * 100)}": replay_threshold(
            "DEVELOPMENT", threshold, DEVELOPMENT_YEARS, entries, outcomes, daily
        )
        for threshold in THRESHOLDS
    }
    selected = select_candidate(candidates)
    result = {
        "experiment": EXPERIMENT,
        **hashes,
        "source_hashes": identities,
        "candidate_results": candidates,
        "selected_threshold": selected["threshold"],
        "selected_rule": (
            f"pre_gap_drawdown_from_120d_peak >= {selected['threshold']:.2f}; "
            "all corrected V4R1 signal/execution/exit rules unchanged"
        ),
        "selector_passed": True,
        "diagnostic_specific_rows_opened": "NO",
        "repository_2024_plus_signal_data_opened": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_FREEZE_BEFORE_V5_SPECIFIC_SUBSET_OPEN",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "source_hashes": identities,
        "selected_threshold": selected["threshold"],
        "selected_rule": result["selected_rule"],
        "diagnostic_specific_rows_opened": "NO",
        "diagnostic_specific_outcomes_opened": "NO",
        "post_2023_signal_feature_selection_use": "NO",
    }
    write_json(DIAGNOSTIC_FREEZE, freeze)
    return freeze


def verify_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V5Error("diagnostic freeze missing")
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
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
        raise V5Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": identities}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    threshold = float(freeze["selected_threshold"])
    entries, outcomes, daily = load_source("POST_OBSERVATION_DIAGNOSTIC")
    diagnostic = replay_threshold(
        "POST_OBSERVATION_DIAGNOSTIC",
        threshold,
        DIAGNOSTIC_YEARS,
        entries,
        outcomes,
        daily,
    )
    yearly = diagnostic["event_yearly"]
    checks = {
        "event_mean_net_ge_3pct": diagnostic["event_metrics"]["mean_net"] >= 0.03,
        "portfolio_mean_net_ge_3pct": diagnostic["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": diagnostic["portfolio_median_net"] > 0,
        "signals_per_year_40_to_80": (
            MIN_SIGNALS_PER_YEAR
            <= diagnostic["selected_signals_per_year"]
            <= MAX_SIGNALS_PER_YEAR
        ),
        "severe10_le_15pct": diagnostic["portfolio_severe10"] <= 0.15,
        "both_year_event_means_positive": all(
            float(yearly.get(str(year), {}).get("mean_net", -1.0)) > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "post_2023_signal_count_zero": diagnostic["post_2023_signal_count"] == 0,
    }
    verdict = (
        "DEEP_MATURE_DECLINE_REPAIR_POST_OBSERVATION_TARGET_RETAINED"
        if all(checks.values())
        else "DEEP_MATURE_DECLINE_REPAIR_POST_OBSERVATION_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_threshold": threshold,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": verdict,
        "scientific_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_ONLY",
        "post_2023_signal_feature_selection_use": "NO",
        "repository_2024_plus_data_opened": "INHERITED_AUTHORIZED_PRE_2024_TRADE_RESOLUTION_TAIL_ONLY",
    }
    write_json(DIAGNOSTIC_RESULT, result)
    return result


def pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    diagnostic = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
    selected = development["candidate_results"][
        f"D{round(float(development['selected_threshold']) * 100)}"
    ]
    observed = diagnostic["diagnostic"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Result",
        "",
        f"`{diagnostic['verdict']}`",
        "",
        "The sole added condition is a causal pre-gap 120-session peak drawdown of at least 45%. All corrected V4R1 entry, target, H20, cost, T+1, limit, and corporate-action semantics are unchanged.",
        "",
        "|Period|Selected signals|Signals/year|Executable|Portfolio trades|Event mean|Portfolio mean|Median|Severe10|Total return|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, item in (("Development 2017–2021", selected), ("Post-observation 2022–2023", observed)):
        combined = item["portfolio"]["COMBINED"]
        lines.append(
            f"|{label}|{item['selected_signals']}|{item['selected_signals_per_year']:.1f}|"
            f"{item['executable_entries']}|{combined['trades']}|{pct(item['event_metrics']['mean_net'])}|"
            f"{pct(combined['mean_net'])}|{pct(combined['median_net'])}|{pct(combined['severe10'])}|"
            f"{pct(combined['total_return'])}|{pct(combined['max_drawdown'])}|"
        )
    lines += [
        "",
        "## Development threshold trace",
        "",
        "|Threshold|Signals/year|Portfolio mean|Median|Severe10|Positive years|",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("D40", "D45", "D50"):
        item = development["candidate_results"][key]
        lines.append(
            f"|{pct(item['threshold'])}|{item['selected_signals_per_year']:.1f}|"
            f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
            f"{pct(item['portfolio_severe10'])}|{item['positive_calendar_years']}/5|"
        )
    lines += [
        "",
        "## Governance",
        "",
        "- The 45% threshold is Development-selected from only 40/45/50%.",
        "- 2022–2023 is post-observation diagnostic evidence, not pristine validation.",
        "- No post-2023 signal, feature, threshold, or selection row was used.",
        "- Any 2024 row is inherited solely to close a pre-2024 position.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=("development-freeze", "verify-freeze", "diagnostic", "report")
    )
    args = parser.parse_args()
    if args.stage == "development-freeze":
        payload = run_development_and_freeze()
    elif args.stage == "verify-freeze":
        payload = verify_freeze()
    elif args.stage == "diagnostic":
        payload = run_diagnostic()
    else:
        render_report()
        payload = {"report": str(REPORT)}
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
