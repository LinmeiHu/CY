#!/usr/bin/env python3
# ruff: noqa: E501
"""Test simple causal failure exits on the corrected below-gap repair signal.

The signal, entry, target, cost, portfolio, and H20 terminal exit are inherited
unchanged from V4R1.  Stage A constructs only completed-daily-bar failure clocks.
Stage B may replace the inherited exit only when the new legal sell open occurs
strictly before the inherited target/risk/H20 exit.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-FAILURE-EXIT-V8"
START_HEAD = "bf7db92e06"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_failure_exit_v8"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

RULES = (
    "X1_SWING_LOW_BREAK",
    "X2_NO_PROGRESS_D3",
    "X3_NO_PROGRESS_D5",
    "X4_SWING_LOW_OR_D3",
)
ALL_LANES = ("X0_H20_BASELINE", *RULES)
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
MIN_TRADES_PER_YEAR = 50.0
NO_PROGRESS_FRACTION = 0.25


class V8Error(RuntimeError):
    """Fail-closed V8 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def stage_a_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "failure_trigger_clocks.parquet"


def lane_root(label: str, rule: str) -> Path:
    return EXT_ROOT / label.lower() / rule.lower()


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "The below-gap reflex repair has positive gross direction but H20 retains "
            "failed rebounds too long. A completed daily structural break or persistent "
            "lack of progress can invalidate the repair thesis without reducing signal count."
        ),
        "source": repair.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "signal_admission_changed": False,
        "entry_changed": False,
        "failure_exit_family": {
            "X1_SWING_LOW_BREAK": (
                "first completed valid daily close strictly below the signal-known swing_low"
            ),
            "X2_NO_PROGRESS_D3": (
                "at entry_cal_idx+3, max completed daily high progress toward L is below "
                "25% and completed close is below entry coordinate"
            ),
            "X3_NO_PROGRESS_D5": (
                "same no-progress rule at entry_cal_idx+5"
            ),
            "X4_SWING_LOW_OR_D3": "earliest X1 or X2 trigger",
            "execution": (
                "next authoritative legal sellable 1-minute open strictly after the "
                "completed daily trigger and strictly before inherited exit"
            ),
            "missing_or_lineage_break_policy": "FAIL_CLOSED_NO_NEW_FAILURE_TRIGGER",
        },
        "selector": {
            "eligibility": {
                "executable_entries_per_year_min": MIN_TRADES_PER_YEAR,
                "portfolio_mean_net_min": 0.03,
                "portfolio_median_net_positive": True,
                "portfolio_severe10_max": 0.15,
                "positive_calendar_years_min": 4,
            },
            "order": [
                "higher portfolio mean net return",
                "higher portfolio median net return",
                "lower severe_loss10",
                "fewer failure components",
            ],
        },
        "unchanged_v4r1": {
            "signal_population_and_features": True,
            "entry": "first buyable 1-minute open strictly after daily signal",
            "target": "entry + 0.80*(L-entry)",
            "terminal_time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "50/50 Main/ChiNext; K20 per sleeve",
            "T1_limits_suspensions_and_corporate_actions": True,
        },
        "post_2023_scope": (
            "only execution/outcome management of signals formed no later than 2023-12-31; "
            "no post-2023 signal, feature, threshold, or selection"
        ),
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "OUTCOME_BLIND_BOUNDED_FAILURE_EXIT_FAMILY",
            "development_disclosure": (
                "The four failure-exit rules and all thresholds were frozen after the "
                "V7 Development failure and before their exit returns were computed."
            ),
            "goal_clarification": (
                "User clarified that annual executable frequency must be at least 50, "
                "with no upper cap and no penalty for exceeding 50."
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
        for name in ("entries", "outcomes", "outcome_daily", "sell_opens", "actions"):
            values[f"{label.lower()}_{name}"] = paths[name]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V8Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def _valid_daily_path(days: pd.DataFrame, entry: Any) -> pd.DataFrame:
    path = days.loc[
        days.cal_idx.ge(int(entry.entry_cal_idx))
        & days.cal_idx.le(int(entry.entry_cal_idx) + repair.TIME_STOP)
    ].copy()
    required = (
        "hard_valid",
        "current_day_data_tradable",
        "market_rule_valid",
        "corporate_action_blocking",
        "coord_high",
        "coord_close",
        "invalid_step_cum",
    )
    complete = pd.Series(True, index=path.index)
    for column in required:
        complete &= path[column].notna()
    complete &= path.hard_valid.astype(bool)
    complete &= path.current_day_data_tradable.astype(bool)
    complete &= path.market_rule_valid.astype(bool)
    complete &= ~path.corporate_action_blocking.astype(bool)
    complete &= path.invalid_step_cum.eq(float(entry.entry_invalid_step_cum))
    return path.loc[complete].sort_values("cal_idx", kind="mergesort")


def failure_trigger_for_rule(
    entry: Any,
    days: pd.DataFrame,
    rule: str,
) -> tuple[pd.Timestamp | None, str | None]:
    """Construct one outcome-blind failure clock from completed daily bars."""
    path = _valid_daily_path(days, entry)
    if path.empty:
        return None, None

    candidates: list[tuple[pd.Timestamp, str]] = []
    if rule in ("X1_SWING_LOW_BREAK", "X4_SWING_LOW_OR_D3"):
        hit = path.loc[path.coord_close.lt(float(entry.swing_low))]
        if not hit.empty:
            candidates.append(
                (
                    pd.Timestamp(hit.trade_date.iloc[0]) + pd.Timedelta(hours=15),
                    "SWING_LOW_BREAK",
                )
            )

    if rule in ("X2_NO_PROGRESS_D3", "X3_NO_PROGRESS_D5", "X4_SWING_LOW_OR_D3"):
        offset = 5 if rule == "X3_NO_PROGRESS_D5" else 3
        checkpoint = int(entry.entry_cal_idx) + offset
        row = path.loc[path.cal_idx.eq(checkpoint)]
        observed = path.loc[path.cal_idx.le(checkpoint)]
        denominator = float(entry.L) - float(entry.entry_coordinate_price)
        if not row.empty and denominator > 0 and not observed.empty:
            progress = (
                float(observed.coord_high.max()) - float(entry.entry_coordinate_price)
            ) / denominator
            if (
                np.isfinite(progress)
                and progress < NO_PROGRESS_FRACTION
                and float(row.coord_close.iloc[0]) < float(entry.entry_coordinate_price)
            ):
                candidates.append(
                    (
                        pd.Timestamp(row.trade_date.iloc[0]) + pd.Timedelta(hours=15),
                        f"NO_PROGRESS_D{offset}",
                    )
                )

    if not candidates:
        return None, None
    return sorted(candidates, key=lambda item: (item[0], item[1]))[0]


def build_period_stage_a(label: str, signal_end: pd.Timestamp) -> dict[str, Any]:
    entries = pd.read_parquet(repair.paths(label)["entries"])
    days = pd.read_parquet(repair.paths(label)["outcome_daily"])
    for frame, columns in (
        (entries, ("signal_date", "signal_time", "entry_date", "entry_time")),
        (days, ("trade_date",)),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    day_by = {
        symbol: part.sort_values("cal_idx", kind="mergesort")
        for symbol, part in days.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for entry in executable.itertuples(index=False):
        path = day_by.get(str(entry.symbol), pd.DataFrame(columns=days.columns))
        for rule in RULES:
            trigger, reason = failure_trigger_for_rule(entry, path, rule)
            rows.append(
                {
                    "gap_id": str(entry.gap_id),
                    "symbol": str(entry.symbol),
                    "board": str(entry.board),
                    "signal_date": pd.Timestamp(entry.signal_date),
                    "signal_time": pd.Timestamp(entry.signal_time),
                    "entry_date": pd.Timestamp(entry.entry_date),
                    "entry_time": pd.Timestamp(entry.entry_time),
                    "entry_cal_idx": int(entry.entry_cal_idx),
                    "entry_invalid_step_cum": float(entry.entry_invalid_step_cum),
                    "rule": rule,
                    "failure_trigger_time": trigger,
                    "failure_trigger_reason": reason,
                    "decision_latest_timestamp": trigger,
                }
            )
    result = pd.DataFrame(rows).sort_values(
        ["rule", "entry_time", "symbol", "gap_id"], kind="mergesort"
    )
    if len(result) != len(executable) * len(RULES):
        raise V8Error(f"{label} Stage-A identity failure")
    result["trigger_at_or_before_entry"] = (
        result.failure_trigger_time.notna()
        & result.failure_trigger_time.le(result.entry_time)
    )
    result["post_cutoff_signal"] = result.signal_date.gt(signal_end)
    if result.trigger_at_or_before_entry.any() or result.post_cutoff_signal.any():
        raise V8Error(f"{label} Stage-A causal blocking audit")
    output = stage_a_path(label)
    repair.write_parquet(result, output)
    return {
        "source_executable_entries": len(executable),
        "rows": len(result),
        "trigger_counts": {
            rule: int(
                result.loc[result.rule.eq(rule), "failure_trigger_time"].notna().sum()
            )
            for rule in RULES
        },
        "post_cutoff_trade_management_trigger_counts": {
            rule: int(
                result.loc[
                    result.rule.eq(rule)
                    & result.failure_trigger_time.gt(signal_end),
                    "failure_trigger_time",
                ].notna().sum()
            )
            for rule in RULES
        },
        "audit": {
            "trigger_at_or_before_entry_count": int(result.trigger_at_or_before_entry.sum()),
            "post_cutoff_signal_count": int(result.post_cutoff_signal.sum()),
        },
        "sha256": sha256(output),
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    identities = source_hashes()
    periods = {
        label: build_period_stage_a(label, signal_end)
        for label, (signal_end, _tail_end, _years) in repair.PERIODS.items()
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_FAILURE_TRIGGER_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": identities,
        "periods": periods,
        "failure_exit_returns_opened": "NO",
        "post_2023_signal_data_opened": "NO",
        "later_data_authorization": (
            "Only management and completion of trades formed by the frozen cutoff."
        ),
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V8Error("Stage-A freeze missing")
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
    current_sources = source_hashes()
    if current_sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), current_sources]
    for label in repair.PERIODS:
        current = sha256(stage_a_path(label))
        expected = freeze["periods"][label]["sha256"]
        if current != expected:
            drift[f"{label}_stage_a"] = [expected, current]
    if drift:
        raise V8Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": current_sources}


def apply_failure_rule(label: str, rule: str) -> tuple[pd.DataFrame, dict[str, int]]:
    paths = repair.paths(label)
    base = pd.read_parquet(paths["outcomes"])
    triggers = pd.read_parquet(stage_a_path(label))
    sells = pd.read_parquet(paths["sell_opens"])
    actions = pd.read_parquet(paths["actions"])
    days = pd.read_parquet(paths["outcome_daily"])
    for frame, columns in (
        (base, ("entry_date", "entry_time", "exit_date", "exit_time")),
        (triggers, ("failure_trigger_time",)),
        (sells, ("trade_date", "bar_end_time")),
        (actions, ("known_date", "effective_date")),
        (days, ("trade_date",)),
    ):
        for column in columns:
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    trigger = triggers.loc[
        triggers.rule.eq(rule),
        ["gap_id", "failure_trigger_time", "failure_trigger_reason"],
    ]
    frame = base.merge(trigger, on="gap_id", how="left", validate="one_to_one")
    sell_by = {
        symbol: part.sort_values("bar_end_time", kind="mergesort")
        for symbol, part in sells.groupby("symbol", sort=False)
    }
    action_by = {
        symbol: part.sort_values(["known_date", "effective_date"], kind="mergesort")
        for symbol, part in actions.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    audit: Counter[str] = Counter()
    for entry in frame.itertuples(index=False):
        row = entry._asdict()
        original_net = float(entry.net_return)
        row["source_exit_time"] = pd.Timestamp(entry.exit_time)
        row["source_exit_reason"] = str(entry.exit_reason)
        row["source_net_return"] = original_net
        row["failure_exit_applied"] = False
        trigger_time = (
            None
            if pd.isna(entry.failure_trigger_time)
            else pd.Timestamp(entry.failure_trigger_time)
        )
        if trigger_time is not None:
            legal = sell_by.get(str(entry.symbol), pd.DataFrame(columns=sells.columns))
            fill = repair.next_sell_open(legal, trigger_time)
            if fill is not None and pd.Timestamp(fill["exit_time"]) < pd.Timestamp(entry.exit_time):
                if int(fill["exit_cal_idx"]) <= int(entry.entry_cal_idx):
                    audit["t1_violation_count"] += 1
                act = action_by.get(
                    str(entry.symbol), pd.DataFrame(columns=actions.columns)
                )
                cash, cash_json = repair.cash_events(
                    act,
                    pd.Timestamp(entry.entry_date),
                    pd.Timestamp(fill["exit_date"]),
                )
                net = (
                    (float(fill["exit_raw_price"]) * (1 - repair.COST) + cash)
                    / (float(entry.entry_raw_price) * (1 + repair.COST))
                    - 1
                )
                row.update(
                    {
                        "exit_time": pd.Timestamp(fill["exit_time"]),
                        "exit_date": pd.Timestamp(fill["exit_date"]),
                        "exit_cal_idx": int(fill["exit_cal_idx"]),
                        "exit_raw_price": float(fill["exit_raw_price"]),
                        "exit_reason": f"FAILURE_{entry.failure_trigger_reason}",
                        "net_return": net,
                        "holding_sessions": int(fill["exit_cal_idx"])
                        - int(entry.entry_cal_idx),
                        "cash_events_json": cash_json,
                        "failure_exit_applied": True,
                    }
                )
        row["net_delta_vs_x0"] = float(row["net_return"]) - original_net
        rows.append(row)
    outcomes = pd.DataFrame(rows).sort_values(
        ["entry_time", "symbol", "gap_id"], kind="mergesort"
    )
    if len(outcomes) != len(base) or set(outcomes.gap_id) != set(base.gap_id):
        raise V8Error(f"{label} {rule} outcome identity failure")
    if audit["t1_violation_count"]:
        raise V8Error(f"{label} {rule} T+1 failure: {dict(audit)}")
    output = lane_root(label, rule) / "outcomes.parquet"
    repair.write_parquet(outcomes, output)
    return outcomes, dict(audit)


def run_lane(label: str, rule: str, years: tuple[int, ...]) -> dict[str, Any]:
    paths = repair.paths(label)
    entries = pd.read_parquet(paths["entries"])
    entries["signal_date"] = pd.to_datetime(entries.signal_date)
    if rule == "X0_H20_BASELINE":
        outcomes = pd.read_parquet(paths["outcomes"])
        outcomes["failure_exit_applied"] = False
        outcomes["net_delta_vs_x0"] = 0.0
        outcome_audit: dict[str, int] = {}
    else:
        outcomes, outcome_audit = apply_failure_rule(label, rule)
    for column in ("entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    daily = pd.read_parquet(paths["outcome_daily"])
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = lane_root(label, rule)
    root.mkdir(parents=True, exist_ok=True)
    if rule == "X0_H20_BASELINE":
        repair.write_parquet(outcomes, root / "outcomes.parquet")
    repair.v1.configure_external(root, max_exit)
    replay_years = tuple(range(min(years), int(max_exit.year) + 1))
    portfolio = repair.v1.run_portfolio(
        outcomes,
        daily.loc[daily.trade_date.le(max_exit)].copy(),
        replay_years,
    )
    event = repair.v1.trade_metrics(outcomes)
    yearly = outcomes.assign(_year=outcomes.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    combined = portfolio["COMBINED"]
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")]
    accepted_path = root / "portfolio_accepted.parquet"
    accepted = pd.read_parquet(accepted_path)
    return {
        "rule": rule,
        "source_selected_signals": len(entries),
        "executable_entries": len(executable),
        "executable_entries_per_year": len(executable) / len(years),
        "complete_outcomes": len(outcomes),
        "failure_exits_applied": int(outcomes.failure_exit_applied.sum()),
        "mean_net_delta_vs_x0": float(outcomes.net_delta_vs_x0.mean()),
        "loss_saved_total": float(outcomes.loc[outcomes.net_delta_vs_x0.gt(0), "net_delta_vs_x0"].sum()),
        "winner_regret_total": float(outcomes.loc[outcomes.net_delta_vs_x0.lt(0), "net_delta_vs_x0"].sum()),
        "event_metrics": event,
        "event_yearly": {
            str(int(index)): {
                "trades": int(row.trades),
                "mean_net": float(row.mean_net),
                "median_net": float(row.median_net),
            }
            for index, row in yearly.iterrows()
        },
        "attack_date_equal_mean": float(
            outcomes.assign(_date=outcomes.entry_date.dt.normalize())
            .groupby("_date").net_return.mean().mean()
        ),
        "portfolio": portfolio,
        "portfolio_accepted_trades": len(accepted),
        "portfolio_mean_net": float(combined["mean_net"]),
        "portfolio_median_net": float(combined["median_net"]),
        "portfolio_severe10": float(combined["severe10"]),
        "positive_calendar_years": int(
            sum(float(combined["annual_returns"].get(str(year), 0.0)) > 0 for year in years)
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(entries.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "outcome_audit": outcome_audit,
        "hashes": {
            "outcomes": sha256(root / "outcomes.parquet"),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
            "portfolio_accepted": sha256(accepted_path),
        },
    }


def candidate_eligible(item: dict[str, Any]) -> bool:
    return bool(
        item["executable_entries_per_year"] >= MIN_TRADES_PER_YEAR
        and item["portfolio_mean_net"] >= 0.03
        and item["portfolio_median_net"] > 0
        and item["portfolio_severe10"] <= 0.15
        and item["positive_calendar_years"] >= 4
    )


def select_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        item for rule, item in candidates.items()
        if rule != "X0_H20_BASELINE" and candidate_eligible(item)
    ]
    if not eligible:
        raise V8Error("no Development failure exit passes selector")
    complexity = {
        "X1_SWING_LOW_BREAK": 1,
        "X2_NO_PROGRESS_D3": 1,
        "X3_NO_PROGRESS_D5": 1,
        "X4_SWING_LOW_OR_D3": 2,
    }
    return sorted(
        eligible,
        key=lambda item: (
            -item["portfolio_mean_net"],
            -item["portfolio_median_net"],
            item["portfolio_severe10"],
            complexity[item["rule"]],
            item["rule"],
        ),
    )[0]


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    candidates = {
        rule: run_lane("DEVELOPMENT", rule, DEVELOPMENT_YEARS)
        for rule in ALL_LANES
    }
    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "candidate_results": candidates,
        "development_failure_exit_returns_opened": "YES",
        "diagnostic_failure_exit_returns_opened": "NO",
    }
    try:
        selected = select_candidate(candidates)
    except V8Error:
        result.update(
            {
                "selector_passed": False,
                "selected_rule": None,
                "verdict": "FAILURE_EXIT_DEVELOPMENT_FAILED",
            }
        )
        write_json(DEVELOPMENT_RESULT, result)
        return result
    result.update(
        {
            "selector_passed": True,
            "selected_rule": selected["rule"],
            "verdict": "FAILURE_EXIT_DEVELOPMENT_CANDIDATE",
        }
    )
    write_json(DEVELOPMENT_RESULT, result)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_FREEZE_BEFORE_FAILURE_EXIT_RETURNS",
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "selected_rule": selected["rule"],
        "diagnostic_failure_exit_returns_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(DIAGNOSTIC_FREEZE, freeze)
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V8Error("Development produced no diagnostic freeze")
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
        raise V8Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    rule = str(freeze["selected_rule"])
    diagnostic = run_lane("POST_OBSERVATION_DIAGNOSTIC", rule, DIAGNOSTIC_YEARS)
    yearly = diagnostic["event_yearly"]
    checks = {
        "event_mean_net_ge_3pct": diagnostic["event_metrics"]["mean_net"] >= 0.03,
        "portfolio_mean_net_ge_3pct": diagnostic["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": diagnostic["portfolio_median_net"] > 0,
        "at_least_50_executable_entries_per_year": (
            diagnostic["executable_entries_per_year"] >= MIN_TRADES_PER_YEAR
        ),
        "severe10_le_15pct": diagnostic["portfolio_severe10"] <= 0.15,
        "both_year_event_means_positive": all(
            float(yearly.get(str(year), {}).get("mean_net", -1.0)) > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "post_2023_signal_count_zero": diagnostic["post_2023_signal_count"] == 0,
    }
    verdict = (
        "FAILURE_EXIT_POST_OBSERVATION_TARGET_RETAINED"
        if all(checks.values())
        else "FAILURE_EXIT_POST_OBSERVATION_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_rule": rule,
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
    return "—" if value is None else f"{float(value):.2%}"


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    lines = [f"# {EXPERIMENT}", "", "## Development", "", f"`{development['verdict']}`", ""]
    lines += [
        "|Lane|Executable/year|Accepted trades|Mean|Median|Severe10|Failure exits|Positive years|",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rule in ALL_LANES:
        item = development["candidate_results"][rule]
        lines.append(
            f"|{rule}|{item['executable_entries_per_year']:.1f}|{item['portfolio_accepted_trades']}|"
            f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
            f"{pct(item['portfolio_severe10'])}|{item['failure_exits_applied']}|"
            f"{item['positive_calendar_years']}/5|"
        )
    if DIAGNOSTIC_RESULT.is_file():
        diagnostic = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        item = diagnostic["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"`{diagnostic['verdict']}`",
            "",
            f"Selected rule: `{diagnostic['selected_rule']}`.",
            "",
            f"Executable/year: {item['executable_entries_per_year']:.1f}; portfolio mean: {pct(item['portfolio_mean_net'])}; median: {pct(item['portfolio_median_net'])}; severe10: {pct(item['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "The 2022-2023 rule-specific failure-exit returns were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Stage A constructed completed-daily-bar trigger clocks only.",
        "- Every replacement fill is the next authoritative legal sell open and obeys T+1.",
        "- Signal admission, entry, target, costs, K20 sleeves, and H20 terminal exit are unchanged.",
        "- Later data are used only to manage and complete trades formed by the frozen cutoff.",
        "- No post-2023 signal, feature, threshold, or selection is permitted.",
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
