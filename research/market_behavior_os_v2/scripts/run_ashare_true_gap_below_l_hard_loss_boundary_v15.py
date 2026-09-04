#!/usr/bin/env python3
# ruff: noqa: E501
"""Test simple completed-daily hard loss boundaries on the V13 reversal signal."""

from __future__ import annotations

import argparse
import json
from collections import Counter
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
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-HARD-LOSS-BOUNDARY-V15"
START_HEAD = "8232e2645c"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_hard_loss_boundary_v15"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

RULES = ("S0_NO_STOP", "S8_DAILY_CLOSE", "S10_DAILY_CLOSE", "S12_DAILY_CLOSE")
STOP_FRACTIONS = {
    "S8_DAILY_CLOSE": 0.08,
    "S10_DAILY_CLOSE": 0.10,
    "S12_DAILY_CLOSE": 0.12,
}
TARGET_FRACTION = 0.67
TIME_STOP = 20
PORTFOLIO_K = 80
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)


class V15Error(RuntimeError):
    """Fail-closed V15 research error."""


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
        "actions": root / "qd010_actions.parquet",
        "outcome_daily": root / "outcome_daily.parquet",
        "sell_opens": root / "sell_opens.parquet",
        "outcomes": root / "outcomes.parquet",
    }


def trigger_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "hard_loss_trigger_clocks.parquet"


def lane_root(label: str, rule: str) -> Path:
    return EXT_ROOT / label.lower() / rule.lower()


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "The V13 signal has positive median economics but a damaging left tail. "
            "A completed daily close materially below entry is a direct falsification "
            "of the first-reversal thesis. A hard boundary may cut structural failures "
            "while avoiding the frequent winner interruption of swing-low or no-progress exits."
        ),
        "source_strategy": first_reversal.EXPERIMENT,
        "source_trigger": "PRIOR_HIGH_REVERSAL",
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "fixed_rule_family": {
            "S0_NO_STOP": "A67 target or H20",
            "S8_DAILY_CLOSE": "first completed valid daily close <= entry coordinate * 0.92",
            "S10_DAILY_CLOSE": "first completed valid daily close <= entry coordinate * 0.90",
            "S12_DAILY_CLOSE": "first completed valid daily close <= entry coordinate * 0.88",
        },
        "stop_execution": (
            "next legal sellable 1-minute open strictly after completed daily close; "
            "actual gap-through price; no fill at or below authoritative down limit"
        ),
        "selector": {
            "eligibility": {
                "accepted_trades_per_year_min": MIN_ACCEPTED_TRADES_PER_YEAR,
                "frequency_has_no_upper_cap": True,
                "portfolio_mean_net_min": 0.03,
                "portfolio_median_net_positive": True,
                "portfolio_severe10_max": 0.15,
                "positive_trade_mean_years_min": 4,
                "positive_portfolio_years_min": 4,
                "attack_date_equal_mean_positive": True,
            },
            "order": [
                "higher portfolio mean net",
                "higher portfolio median net",
                "lower severe_loss10",
                "less restrictive stop",
            ],
        },
        "unchanged": {
            "signal_population_features_and_entry": True,
            "target": "entry + 0.67*(L-entry), strictly below L",
            "time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "collision_rank": True,
            "T1_limits_suspensions_and_QD010": True,
        },
        "governance": {
            "stop_clocks_built_before_stop_returns": True,
            "diagnostic_opened_only_for_development_selected_rule": True,
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
            "status": "OUTCOME_BLIND_COMPLETED_DAILY_HARD_LOSS_BOUNDARY_FAMILY",
            "frequency_goal": "at least 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "S8/S10/S12 and the selector were frozen before stop-specific returns "
                "were computed; S0 is the already-known V13 control."
            ),
            "diagnostic_disclosure": (
                "Only the Development-selected rule may be replayed on 2022-2023; "
                "the broader period is post-observation evidence."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v13_contract": first_reversal.CONTRACT,
        "v13_stage_a_freeze": first_reversal.STAGE_A_FREEZE,
        "v13_development_result": first_reversal.DEVELOPMENT_RESULT,
        "v13_diagnostic_result": first_reversal.DIAGNOSTIC_RESULT,
    }
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        for name, path in source_paths(label).items():
            if name != "root":
                values[f"{label.lower()}_{name}"] = path
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V15Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def valid_daily_path(days: pd.DataFrame, entry: Any) -> pd.DataFrame:
    path = days.loc[
        days.symbol.eq(str(entry.symbol))
        & days.cal_idx.ge(int(entry.entry_cal_idx))
        & days.cal_idx.le(int(entry.entry_cal_idx) + TIME_STOP)
    ].copy()
    required = (
        "trade_date",
        "cal_idx",
        "hard_valid",
        "current_day_data_tradable",
        "market_rule_valid",
        "corporate_action_blocking",
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


def first_stop_trigger(
    entry: Any, days: pd.DataFrame, stop_fraction: float
) -> pd.Timestamp | None:
    path = valid_daily_path(days, entry)
    stop_coordinate = float(entry.entry_coordinate_price) * (1 - stop_fraction)
    hit = path.loc[path.coord_close.le(stop_coordinate)]
    if hit.empty:
        return None
    return pd.Timestamp(hit.trade_date.iloc[0]) + pd.Timedelta(hours=15)


def build_period_stage_a(label: str) -> dict[str, Any]:
    paths = source_paths(label)
    entries = pd.read_parquet(paths["entries"])
    days = pd.read_parquet(paths["outcome_daily"])
    for frame, columns in (
        (entries, ("signal_date", "signal_time", "entry_date", "entry_time")),
        (days, ("trade_date",)),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    rows: list[dict[str, Any]] = []
    for entry in executable.itertuples(index=False):
        for rule, fraction in STOP_FRACTIONS.items():
            trigger = first_stop_trigger(entry, days, fraction)
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
                    "entry_coordinate_price": float(entry.entry_coordinate_price),
                    "rule": rule,
                    "stop_fraction": fraction,
                    "stop_coordinate": float(entry.entry_coordinate_price)
                    * (1 - fraction),
                    "stop_trigger_time": trigger,
                    "decision_latest_timestamp": trigger,
                }
            )
    result = pd.DataFrame(rows).sort_values(
        ["rule", "entry_time", "symbol", "gap_id"], kind="mergesort"
    )
    if len(result) != len(executable) * len(STOP_FRACTIONS):
        raise V15Error(f"{label} Stage-A identity failure")
    result["trigger_at_or_before_entry"] = (
        result.stop_trigger_time.notna()
        & result.stop_trigger_time.le(result.entry_time)
    )
    if result.trigger_at_or_before_entry.any():
        raise V15Error(f"{label} noncausal stop trigger")
    output = trigger_path(label)
    repair.write_parquet(result, output)
    return {
        "source_executable_entries": len(executable),
        "rows": len(result),
        "trigger_counts": {
            rule: int(
                result.loc[result.rule.eq(rule), "stop_trigger_time"].notna().sum()
            )
            for rule in STOP_FRACTIONS
        },
        "trigger_at_or_before_entry_count": int(
            result.trigger_at_or_before_entry.sum()
        ),
        "sha256": sha256(output),
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods = {
        label: build_period_stage_a(label)
        for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC")
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_HARD_LOSS_TRIGGER_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "periods": periods,
        "stop_specific_returns_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V15Error("Stage-A freeze missing")
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
        current = sha256(trigger_path(label))
        expected = freeze["periods"][label]["sha256"]
        if current != expected:
            drift[f"{label}_trigger_clocks"] = [expected, current]
    if drift:
        raise V15Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": identities}


def apply_stop_rule(
    label: str, rule: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    paths = source_paths(label)
    base = pd.read_parquet(paths["outcomes"])
    triggers = pd.read_parquet(trigger_path(label))
    sells = pd.read_parquet(paths["sell_opens"])
    actions = pd.read_parquet(paths["actions"])
    for frame, columns in (
        (base, ("entry_date", "entry_time", "exit_date", "exit_time")),
        (triggers, ("stop_trigger_time",)),
        (sells, ("trade_date", "bar_end_time")),
        (actions, ("known_date", "effective_date")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    trigger = triggers.loc[
        triggers.rule.eq(rule),
        ["gap_id", "stop_trigger_time", "stop_coordinate"],
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
        row["hard_stop_applied"] = False
        trigger_time = (
            None
            if pd.isna(entry.stop_trigger_time)
            else pd.Timestamp(entry.stop_trigger_time)
        )
        if trigger_time is not None:
            legal = sell_by.get(
                str(entry.symbol), pd.DataFrame(columns=sells.columns)
            )
            fill = repair.next_sell_open(legal, trigger_time)
            if fill is not None and pd.Timestamp(fill["exit_time"]) < pd.Timestamp(
                entry.exit_time
            ):
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
                        "exit_reason": f"HARD_LOSS_{rule}",
                        "net_return": net,
                        "holding_sessions": int(fill["exit_cal_idx"])
                        - int(entry.entry_cal_idx),
                        "cash_events_json": cash_json,
                        "hard_stop_applied": True,
                    }
                )
        row["net_delta_vs_s0"] = float(row["net_return"]) - original_net
        rows.append(row)
    outcomes = pd.DataFrame(rows).sort_values(
        ["entry_time", "symbol", "gap_id"], kind="mergesort"
    )
    if len(outcomes) != len(base) or set(outcomes.gap_id) != set(base.gap_id):
        raise V15Error(f"{label} {rule} outcome identity failure")
    if audit["t1_violation_count"]:
        raise V15Error(f"{label} {rule} T+1 failure: {dict(audit)}")
    output = lane_root(label, rule) / "outcomes.parquet"
    repair.write_parquet(outcomes, output)
    return outcomes, dict(audit)


def run_lane(label: str, rule: str, years: tuple[int, ...]) -> dict[str, Any]:
    paths = source_paths(label)
    if rule == "S0_NO_STOP":
        outcomes = pd.read_parquet(paths["outcomes"])
        outcomes["hard_stop_applied"] = False
        outcomes["net_delta_vs_s0"] = 0.0
        outcome_audit: dict[str, int] = {}
    else:
        outcomes, outcome_audit = apply_stop_rule(label, rule)
    for column in ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    daily = pd.read_parquet(paths["outcome_daily"])
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = lane_root(label, rule)
    root.mkdir(parents=True, exist_ok=True)
    if rule == "S0_NO_STOP":
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
    for frame, column in ((accepted, "entry_date"), (outcomes, "entry_date")):
        frame[column] = pd.to_datetime(frame[column])
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
    return {
        "rule": rule,
        "source_executable_trades": len(outcomes),
        "hard_stops_applied": int(outcomes.hard_stop_applied.sum()),
        "mean_net_delta_vs_s0": float(outcomes.net_delta_vs_s0.mean()),
        "loss_saved_total": float(
            outcomes.loc[outcomes.net_delta_vs_s0.gt(0), "net_delta_vs_s0"].sum()
        ),
        "winner_regret_total": float(
            outcomes.loc[outcomes.net_delta_vs_s0.lt(0), "net_delta_vs_s0"].sum()
        ),
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
        "attack_date_equal_mean": float(
            outcomes.assign(_date=outcomes.entry_date.dt.normalize())
            .groupby("_date")
            .net_return.mean()
            .mean()
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(
            outcomes.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
        ),
        "outcome_audit": outcome_audit,
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
        and item["positive_trade_mean_years"] >= 4
        and item["positive_portfolio_years"] >= 4
        and item["attack_date_equal_mean"] > 0
        and item["post_2023_signal_count"] == 0
    )


def select_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates.values() if candidate_eligible(item)]
    if not eligible:
        raise V15Error("no Development hard-loss rule passes selector")
    restrictiveness = {
        "S0_NO_STOP": 99,
        "S12_DAILY_CLOSE": 12,
        "S10_DAILY_CLOSE": 10,
        "S8_DAILY_CLOSE": 8,
    }
    return sorted(
        eligible,
        key=lambda item: (
            -item["portfolio_mean_net"],
            -item["portfolio_median_net"],
            item["portfolio_severe10"],
            -restrictiveness[item["rule"]],
        ),
    )[0]


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    candidates = {
        rule: run_lane("DEVELOPMENT", rule, DEVELOPMENT_YEARS) for rule in RULES
    }
    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "candidate_results": candidates,
        "development_stop_returns_opened": "YES",
        "diagnostic_selected_rule_returns_opened": "NO",
    }
    try:
        selected = select_candidate(candidates)
    except V15Error:
        result.update(
            {
                "selector_passed": False,
                "selected_rule": None,
                "verdict": "HARD_LOSS_BOUNDARY_DEVELOPMENT_FAILED",
            }
        )
        write_json(DEVELOPMENT_RESULT, result)
        return result
    result.update(
        {
            "selector_passed": True,
            "selected_rule": selected["rule"],
            "verdict": "HARD_LOSS_BOUNDARY_DEVELOPMENT_CANDIDATE",
        }
    )
    write_json(DEVELOPMENT_RESULT, result)
    write_json(
        DIAGNOSTIC_FREEZE,
        {
            "experiment": EXPERIMENT,
            "stage": "DIAGNOSTIC_FREEZE_BEFORE_SELECTED_HARD_LOSS_REPLAY",
            "contract_sha256": sha256(CONTRACT),
            "spec_sha256": sha256(SPEC),
            "runner_sha256": sha256(Path(__file__)),
            "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
            "development_result_sha256": sha256(DEVELOPMENT_RESULT),
            "selected_rule": selected["rule"],
            "diagnostic_selected_rule_returns_opened": "NO",
        },
    )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V15Error("Development produced no diagnostic freeze")
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
        raise V15Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def diagnostic_checks(item: dict[str, Any]) -> dict[str, bool]:
    yearly = item["accepted_trade_yearly"]
    return {
        "accepted_trades_per_year_ge_50": (
            item["portfolio_accepted_trades_per_year"] >= MIN_ACCEPTED_TRADES_PER_YEAR
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
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    rule = str(freeze["selected_rule"])
    diagnostic = run_lane("POST_OBSERVATION_DIAGNOSTIC", rule, DIAGNOSTIC_YEARS)
    checks = diagnostic_checks(diagnostic)
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_rule": rule,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": (
            "HARD_LOSS_BOUNDARY_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "HARD_LOSS_BOUNDARY_POST_OBSERVATION_FAILED"
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
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|Stops|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rule in RULES:
        item = development["candidate_results"][rule]
        lines.append(
            f"|{rule}|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|"
            f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
            f"{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|"
            f"{item['hard_stops_applied']}|{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|"
        )
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        item = result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"Selected rule: `{result['selected_rule']}`.",
            f"Verdict: `{result['verdict']}`.",
            f"Accepted/year: {item['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(item['portfolio_mean_net'])}; median: {pct(item['portfolio_median_net'])}; severe10: {pct(item['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "The selected 2022-2023 stop outcome was not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Frequency means at least 50 accepted trades/year; there is no upper cap.",
        "- Stop information is a completed valid daily close; execution is the next legal open with T+1 and actual gap-through handling.",
        "- Signal, entry, A67, H20, 40 bp, K80, limits, and QD-010 are unchanged.",
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
