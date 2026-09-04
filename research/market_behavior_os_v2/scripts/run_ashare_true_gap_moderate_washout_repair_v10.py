#!/usr/bin/env python3
# ruff: noqa: E501
"""Develop a broader causal moderate-washout repair rule below true gaps."""

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
EXPERIMENT = "ASHARE-TRUE-GAP-MODERATE-WASHOUT-REPAIR-V10"
START_HEAD = "62dbc64221"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_moderate_washout_repair_v10"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
MECHANICAL_AMENDMENT = OS / f"experiments/{EXPERIMENT}_pre_result_mechanical_amendment_001.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

RULES = (
    "DEPTH_15_25",
    "DEPTH_15_30",
    "DEPTH_15_30_RECOVERY_05_15",
)
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0


class V10Error(RuntimeError):
    """Fail-closed V10 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def paths(label: str) -> dict[str, Path]:
    root = EXT_ROOT / label.lower()
    return {
        "root": root,
        "rule_panel": root / "rule_panel.parquet",
        "signals": root / "signals_union.parquet",
        "actions": root / "qd010_actions.parquet",
        "action_registry": root / "action_registry_symbols.parquet",
        "entry_seed": root / "entry_seed.parquet",
        "execution_state": root / "execution_state.parquet",
        "entries": root / "entries.parquet",
        "outcome_daily": root / "outcome_daily.parquet",
        "sell_opens": root / "sell_opens.parquet",
        "outcome_bounds": root / "outcome_bounds.parquet",
        "outcome_minutes": root / "outcome_minutes.parquet",
        "outcomes": root / "outcomes.parquet",
    }


def lane_root(label: str, rule: str) -> Path:
    return EXT_ROOT / label.lower() / "lanes" / rule.lower()


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A first causal MA5 reclaim below a low-occupancy true gap is most useful "
            "after a meaningful but non-destructive washout. Shallow declines are noise, "
            "while extreme declines may represent unresolved structural damage."
        ),
        "source_population": {
            "source": "V4R1 direct_first_ma5_candidates, before VAP and pre-gap-return filtering",
            "true_gap": "High_t < Low_t_minus_1",
            "gap_width_min": 0.01,
            "pre_gap_history": "exact 120 valid coordinate-consistent sessions",
            "daily_low_occupancy": {
                "inside_gap_touch_sessions_max": 12,
                "gap_corridor_touch_sessions_max": 20,
            },
            "pre_L_touch": "none before the first signal",
            "base_washout": "max_depth >=10%; current_depth >=5%",
            "base_reversal": (
                "first MA5 reclaim with recent low age 2-10 and recovery from low >=3%"
            ),
        },
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "candidate_rules": {
            "DEPTH_15_25": "15% <= maximum causal depth below L <= 25%",
            "DEPTH_15_30": "15% <= maximum causal depth below L <= 30%",
            "DEPTH_15_30_RECOVERY_05_15": (
                "15%-30% maximum depth and 5%-15% recovery from the signal-known 20-session low"
            ),
        },
        "selector": {
            "eligibility": {
                "portfolio_accepted_trades_per_year_min": MIN_ACCEPTED_TRADES_PER_YEAR,
                "portfolio_mean_net_min": 0.03,
                "portfolio_median_net_positive": True,
                "portfolio_severe10_max": 0.15,
                "positive_calendar_years_min": 4,
                "attack_date_equal_mean_positive": True,
            },
            "order": [
                "higher accepted-trade frequency",
                "fewer rule conditions",
                "higher portfolio mean net",
                "lower severe_loss10",
            ],
        },
        "execution": {
            "entry": "first legal buyable 1-minute open strictly after signal close",
            "minimum_net_headroom_to_L": 0.05,
            "target": "entry + 0.80*(L-entry), strictly below L",
            "failure_stop": "NONE",
            "time_stop": "H20 then next legal sellable 1-minute open",
            "cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K20 per sleeve",
            "collision_low_occupancy_rank": (
                "pre_gap_inside_touch_sessions / 120; lower first; causal daily proxy "
                "used because the broader direct population has no minute-VAP field"
            ),
            "T1_limits_suspensions_and_QD010": True,
        },
        "post_2023_scope": "trade management/completion only; no post-2023 signal or selection",
    }


def persist_contracts() -> dict[str, str]:
    write_json(
        MECHANICAL_AMENDMENT,
        {
            "experiment": EXPERIMENT,
            "amendment_id": "PRE_RESULT_MECHANICAL_AMENDMENT_001",
            "issue": (
                "The inherited portfolio replay requires "
                "pre_gap_inside_density_relative_local for collision ordering, while "
                "the broader direct-candidate population does not carry minute VAP."
            ),
            "failed_at": "first Development lane portfolio sort before any portfolio metric",
            "repair": (
                "Populate that required ordering field with the already frozen causal "
                "daily low-occupancy proxy pre_gap_inside_touch_sessions / 120."
            ),
            "rule_or_threshold_changed": False,
            "performance_metric_observed_before_repair": False,
            "broader_row_outcomes_constructed_before_repair": True,
            "diagnostic_outcomes_opened": False,
        },
    )
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "OUTCOME_BLIND_THREE_RULE_MODERATE_WASHOUT_FAMILY",
            "development_disclosure": (
                "The three natural depth/recovery rules were frozen from Development-only "
                "feature-shape diagnostics before outcomes for the broader direct-candidate "
                "population were constructed."
            ),
            "diagnostic_disclosure": "2022-2023 remains post-observation evidence.",
            "frequency_goal": "at least 50 accepted executable trades per year; no upper cap",
            "pre_result_mechanical_amendment_sha256": sha256(MECHANICAL_AMENDMENT),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_candidate_path(label: str) -> Path:
    return repair.paths(label)["candidates"]


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v4r1_stage_a_freeze": repair.STAGE_A_FREEZE,
        "v4r1_runner": Path(repair.__file__),
    }
    for label in repair.PERIODS:
        values[f"{label.lower()}_direct_candidates"] = source_candidate_path(label)
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V10Error(f"missing source files: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def rule_mask(frame: pd.DataFrame, rule: str) -> pd.Series:
    depth = pd.to_numeric(frame.max_depth, errors="coerce")
    recovery = pd.to_numeric(frame.recovery_from_low20, errors="coerce")
    if rule == "DEPTH_15_25":
        mask = depth.between(0.15, 0.25, inclusive="both")
    elif rule == "DEPTH_15_30":
        mask = depth.between(0.15, 0.30, inclusive="both")
    elif rule == "DEPTH_15_30_RECOVERY_05_15":
        mask = depth.between(0.15, 0.30, inclusive="both") & recovery.between(
            0.05, 0.15, inclusive="both"
        )
    else:
        raise V10Error(f"unknown rule {rule}")
    return mask.fillna(False)


def build_period_stage_a(
    label: str,
    signal_end: pd.Timestamp,
    tail_end: pd.Timestamp,
    years: tuple[int, ...],
) -> dict[str, Any]:
    output = paths(label)
    output["root"].mkdir(parents=True, exist_ok=True)
    candidates = pd.read_parquet(source_candidate_path(label))
    for column in ("gap_date", "signal_date", "signal_time"):
        candidates[column] = pd.to_datetime(candidates[column])
    candidates = candidates.loc[candidates.signal_date.dt.year.isin(years)].copy()
    if candidates.empty or candidates.gap_id.duplicated().any():
        raise V10Error(f"{label} direct candidate identity failure")
    panel = candidates[["gap_id", "symbol", "board", "signal_date", "signal_time"]].copy()
    for rule in RULES:
        panel[rule] = rule_mask(candidates, rule).to_numpy(bool)
    panel["selected_any_rule"] = panel[list(RULES)].any(axis=1)
    selected = candidates.loc[panel.selected_any_rule].copy()
    selected["pre_gap_inside_density_relative_local"] = (
        pd.to_numeric(selected.pre_gap_inside_touch_sessions, errors="coerce") / 120.0
    )
    if selected.pre_gap_inside_density_relative_local.isna().any():
        raise V10Error(f"{label} low-occupancy rank proxy missing")
    selected["decision_latest_timestamp"] = selected.signal_time
    selected["feature_uses_post_signal_information"] = False
    if selected.empty or selected.gap_id.duplicated().any():
        raise V10Error(f"{label} selected union identity failure")
    repair.write_parquet(panel, output["rule_panel"])
    repair.write_parquet(selected, output["signals"])
    actions = repair.build_actions(
        selected.symbol.drop_duplicates().tolist(),
        tail_end,
        output["actions"],
        output["action_registry"],
    )
    execution_state = repair.build_execution_state(
        selected.symbol.drop_duplicates().tolist(),
        pd.Timestamp(selected.signal_date.min()).normalize(),
        tail_end,
        output["execution_state"],
    )
    entries = repair.build_buy_entries(
        selected, actions, signal_end, tail_end, output
    )
    rule_counts = {rule: int(panel[rule].sum()) for rule in RULES}
    executable_by_rule = {
        rule: int(
            entries.loc[
                entries.gap_id.isin(panel.loc[panel[rule], "gap_id"]),
                "entry_status",
            ].eq("EXECUTABLE_ENTRY").sum()
        )
        for rule in RULES
    }
    blocking = {
        "post_cutoff_signal_count": int(selected.signal_date.gt(signal_end).sum()),
        "entry_at_or_before_signal_count": int(entries.entry_at_or_before_signal.sum()),
        "buy_at_or_above_up_limit_count": int(entries.buy_at_or_above_up_limit.sum()),
        "duplicate_gap_count": int(entries.gap_id.duplicated().sum()),
    }
    if any(blocking.values()):
        raise V10Error(f"{label} Stage-A blocking audit: {blocking}")
    return {
        "direct_candidates": len(candidates),
        "selected_union_signals": len(selected),
        "selected_symbols": int(selected.symbol.nunique()),
        "rule_signal_counts": rule_counts,
        "rule_executable_entry_counts": executable_by_rule,
        "union_entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "execution_state_rows": len(execution_state),
        "audit": blocking,
        "hashes": {
            name: sha256(output[name])
            for name in (
                "rule_panel",
                "signals",
                "actions",
                "action_registry",
                "execution_state",
                "entries",
            )
        },
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods = {
        label: build_period_stage_a(label, signal_end, tail_end, years)
        for label, (signal_end, tail_end, years) in repair.PERIODS.items()
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_BROADER_SIGNAL_AND_EXECUTION_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "pre_result_mechanical_amendment_sha256": sha256(MECHANICAL_AMENDMENT),
        "source_hashes": source_hashes(),
        "periods": periods,
        "broader_candidate_outcomes_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V10Error("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "pre_result_mechanical_amendment_sha256": sha256(MECHANICAL_AMENDMENT),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    identities = source_hashes()
    if identities != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), identities]
    for label in repair.PERIODS:
        output = paths(label)
        for name, expected in freeze["periods"][label]["hashes"].items():
            current = sha256(output[name])
            if current != expected:
                drift[f"{label}_{name}"] = [expected, current]
    if drift:
        raise V10Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": identities}


def build_union_outcomes(label: str) -> tuple[pd.DataFrame, dict[str, int]]:
    output = paths(label)
    entries = pd.read_parquet(output["entries"])
    actions = pd.read_parquet(output["actions"])
    for frame, columns in (
        (entries, ("signal_date", "signal_time", "entry_date", "entry_time")),
        (actions, ("known_date", "effective_date")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    signal_start = pd.Timestamp(entries.signal_date.min()).normalize()
    tail_end = repair.PERIODS[label][1]
    daily = repair.build_outcome_daily(entries, signal_start, tail_end, output)
    sell_opens = repair.build_sell_opens(entries, tail_end, output)
    minutes = repair.build_outcome_minutes(entries, daily, tail_end, output)
    outcomes, audit = repair.build_outcomes(
        entries,
        daily,
        minutes,
        sell_opens,
        actions,
        tail_end,
        output,
    )
    return outcomes, audit


def run_rule(
    label: str,
    rule: str,
    years: tuple[int, ...],
    union_outcomes: pd.DataFrame,
) -> dict[str, Any]:
    output = paths(label)
    panel = pd.read_parquet(output["rule_panel"])
    entries = pd.read_parquet(output["entries"])
    daily = pd.read_parquet(output["outcome_daily"])
    for frame, columns in (
        (entries, ("signal_date", "entry_date", "entry_time")),
        (daily, ("trade_date",)),
        (union_outcomes, ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time")),
    ):
        for column in columns:
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    ids = set(panel.loc[panel[rule], "gap_id"].astype(str))
    rule_entries = entries.loc[entries.gap_id.astype(str).isin(ids)].copy()
    outcomes = union_outcomes.loc[union_outcomes.gap_id.astype(str).isin(ids)].copy()
    executable = rule_entries.loc[rule_entries.entry_status.eq("EXECUTABLE_ENTRY")]
    if len(outcomes) != len(executable):
        raise V10Error(f"{label} {rule} outcome conservation failure")
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = lane_root(label, rule)
    root.mkdir(parents=True, exist_ok=True)
    repair.write_parquet(outcomes, root / "outcomes.parquet")
    repair.v1.configure_external(root, max_exit)
    repair.v1.PORTFOLIO_K = 20
    replay_years = tuple(range(min(years), int(max_exit.year) + 1))
    portfolio = repair.v1.run_portfolio(
        outcomes,
        daily.loc[daily.trade_date.le(max_exit)].copy(),
        replay_years,
    )
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    for column in ("entry_date", "entry_time", "exit_date", "exit_time"):
        accepted[column] = pd.to_datetime(accepted[column])
    event_yearly = outcomes.assign(_year=outcomes.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    accepted_yearly = accepted.assign(_year=accepted.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    combined = portfolio["COMBINED"]
    return {
        "rule": rule,
        "conditions": 2 if rule.endswith("RECOVERY_05_15") else 1,
        "selected_signals": len(rule_entries),
        "executable_entries": len(executable),
        "complete_outcomes": len(outcomes),
        "event_metrics": repair.v1.trade_metrics(outcomes),
        "event_yearly": {
            str(int(index)): {
                "trades": int(row.trades),
                "mean_net": float(row.mean_net),
                "median_net": float(row.median_net),
            }
            for index, row in event_yearly.iterrows()
        },
        "attack_date_equal_mean": float(
            outcomes.assign(_date=outcomes.entry_date.dt.normalize())
            .groupby("_date").net_return.mean().mean()
        ),
        "portfolio": portfolio,
        "portfolio_accepted_trades": len(accepted),
        "portfolio_accepted_trades_per_year": len(accepted) / len(years),
        "portfolio_mean_net": float(combined["mean_net"]),
        "portfolio_median_net": float(combined["median_net"]),
        "portfolio_severe10": float(combined["severe10"]),
        "portfolio_total_return": float(combined["total_return"]),
        "portfolio_cagr": float(combined["cagr"]),
        "portfolio_max_drawdown": float(combined["max_drawdown"]),
        "portfolio_sharpe": float(combined["sharpe"]),
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
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(rule_entries.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "hashes": {
            "outcomes": sha256(root / "outcomes.parquet"),
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
        and item["attack_date_equal_mean"] > 0
    )


def select_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates.values() if candidate_eligible(item)]
    if not eligible:
        raise V10Error("no Development moderate-washout rule passes selector")
    return sorted(
        eligible,
        key=lambda item: (
            -item["portfolio_accepted_trades_per_year"],
            item["conditions"],
            -item["portfolio_mean_net"],
            item["portfolio_severe10"],
            item["rule"],
        ),
    )[0]


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    union_outcomes, outcome_audit = build_union_outcomes("DEVELOPMENT")
    candidates = {
        rule: run_rule("DEVELOPMENT", rule, DEVELOPMENT_YEARS, union_outcomes.copy())
        for rule in RULES
    }
    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "union_outcome_audit": outcome_audit,
        "candidate_results": candidates,
        "development_broader_outcomes_opened": "YES",
        "diagnostic_broader_outcomes_opened": "NO",
    }
    try:
        selected = select_candidate(candidates)
    except V10Error:
        result.update(
            {
                "selector_passed": False,
                "selected_rule": None,
                "verdict": "MODERATE_WASHOUT_DEVELOPMENT_FAILED",
            }
        )
        write_json(DEVELOPMENT_RESULT, result)
        return result
    result.update(
        {
            "selector_passed": True,
            "selected_rule": selected["rule"],
            "verdict": "MODERATE_WASHOUT_DEVELOPMENT_CANDIDATE",
        }
    )
    write_json(DEVELOPMENT_RESULT, result)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_FREEZE_BEFORE_BROADER_OUTCOMES",
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "selected_rule": selected["rule"],
        "diagnostic_broader_outcomes_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(DIAGNOSTIC_FREEZE, freeze)
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V10Error("Development produced no diagnostic freeze")
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
        raise V10Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    rule = str(freeze["selected_rule"])
    union_outcomes, outcome_audit = build_union_outcomes("POST_OBSERVATION_DIAGNOSTIC")
    diagnostic = run_rule(
        "POST_OBSERVATION_DIAGNOSTIC", rule, DIAGNOSTIC_YEARS, union_outcomes
    )
    yearly = diagnostic["accepted_trade_yearly"]
    checks = {
        "portfolio_mean_net_ge_3pct": diagnostic["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": diagnostic["portfolio_median_net"] > 0,
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
        "MODERATE_WASHOUT_POST_OBSERVATION_TARGET_RETAINED"
        if all(checks.values())
        else "MODERATE_WASHOUT_POST_OBSERVATION_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_rule": rule,
        "union_outcome_audit": outcome_audit,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": verdict,
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
    lines = [f"# {EXPERIMENT}", "", "## Development", "", f"`{development['verdict']}`", ""]
    lines += [
        "|Rule|Signals|Executable|Accepted|Accepted/year|Mean|Median|Severe10|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rule in RULES:
        item = development["candidate_results"][rule]
        lines.append(
            f"|{rule}|{item['selected_signals']}|{item['executable_entries']}|"
            f"{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|"
            f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
            f"{pct(item['portfolio_severe10'])}|{pct(item['portfolio_cagr'])}|"
            f"{pct(item['portfolio_max_drawdown'])}|"
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
            f"Selected rule: `{result['selected_rule']}`; accepted/year: {item['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(item['portfolio_mean_net'])}; median: {pct(item['portfolio_median_net'])}; severe10: {pct(item['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "The 2022-2023 broader-population outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Direct candidates still enforce exact daily history and sparse prior gap/corridor touches.",
        "- No VAP outcome was used; the rule is only causal washout depth plus optional recovery band.",
        "- Entry, target, H20, costs, T+1, limits, QD-010, and K20 are unchanged.",
        "- Later data are used only to manage and complete pre-cutoff trades.",
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
