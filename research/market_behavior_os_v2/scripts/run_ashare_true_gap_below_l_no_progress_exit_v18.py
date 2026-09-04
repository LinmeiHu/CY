#!/usr/bin/env python3
# ruff: noqa: E501
"""Test one fixed D10 no-progress failure exit on the V17 candidate."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_hard_loss_boundary_v15 as hard_loss,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_mature_decline_v17 as mature_decline,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-NO-PROGRESS-EXIT-V18"
START_HEAD = "bc9ed1371e"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_no_progress_exit_v18"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

CHECK_SESSION = 10
MIN_PROGRESS_FRACTION = 0.50
TARGET_FRACTION = 0.67
TIME_STOP = 20
PORTFOLIO_K = 80
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = mature_decline.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = mature_decline.DIAGNOSTIC_YEARS


class V18Error(RuntimeError):
    """Fail-closed V18 research error."""


def sha256(path: Path) -> str:
    return mature_decline.sha256(path)


def write_json(path: Path, value: Any) -> None:
    mature_decline.write_json(path, value)


def source_paths(label: str) -> dict[str, Path]:
    return hard_loss.source_paths(label)


def selected_entries_path(label: str) -> Path:
    return mature_decline.selected_entries_path(label)


def trigger_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d10_no_progress_clocks.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "d10_no_progress"


def target_coordinate(entry: Any) -> float:
    return float(entry.entry_coordinate_price) + TARGET_FRACTION * (
        float(entry.L) - float(entry.entry_coordinate_price)
    )


def no_progress_state(entry: Any, days: pd.DataFrame) -> dict[str, Any]:
    check_cal_idx = int(entry.entry_cal_idx) + CHECK_SESSION
    path = days.loc[
        days.symbol.eq(str(entry.symbol))
        & days.cal_idx.ge(int(entry.entry_cal_idx))
        & days.cal_idx.le(check_cal_idx)
    ].copy()
    path = path.sort_values("cal_idx", kind="mergesort")
    check = path.loc[path.cal_idx.eq(check_cal_idx)]
    if check.empty:
        return {
            "state_available": False,
            "state_unavailable_reason": "NO_D10_ROW",
            "trigger_time": pd.NaT,
        }
    required = (
        "trade_date",
        "cal_idx",
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
    valid = (
        complete
        & path.hard_valid.astype(bool)
        & path.current_day_data_tradable.astype(bool)
        & path.market_rule_valid.astype(bool)
        & ~path.corporate_action_blocking.astype(bool)
        & path.invalid_step_cum.eq(float(entry.entry_invalid_step_cum))
    )
    check_valid = bool(valid.loc[check.index].all()) and bool(
        check.current_day_data_tradable.astype(bool).all()
    )
    if not check_valid:
        return {
            "state_available": False,
            "state_unavailable_reason": "D10_NOT_VALID_OR_TRADABLE",
            "trigger_time": pd.NaT,
        }
    observed = path.loc[valid].copy()
    if observed.empty:
        return {
            "state_available": False,
            "state_unavailable_reason": "NO_VALID_PATH",
            "trigger_time": pd.NaT,
        }
    target = target_coordinate(entry)
    target_distance = target - float(entry.entry_coordinate_price)
    if not target_distance > 0:
        raise V18Error(f"non-positive target distance for {entry.gap_id}")
    maximum_progress = (
        float(observed.coord_high.max()) - float(entry.entry_coordinate_price)
    ) / target_distance
    current_close = float(check.coord_close.iloc[-1])
    below_or_at_entry = current_close <= float(entry.entry_coordinate_price)
    no_progress = maximum_progress < MIN_PROGRESS_FRACTION
    triggered = bool(no_progress and below_or_at_entry)
    return {
        "state_available": True,
        "state_unavailable_reason": "",
        "check_date": pd.Timestamp(check.trade_date.iloc[-1]),
        "check_cal_idx": check_cal_idx,
        "target_coordinate": target,
        "maximum_progress_fraction": maximum_progress,
        "current_coordinate_close": current_close,
        "below_or_at_entry": below_or_at_entry,
        "no_progress": no_progress,
        "trigger_time": (
            pd.Timestamp(check.trade_date.iloc[-1]) + pd.Timedelta(hours=15)
            if triggered
            else pd.NaT
        ),
    }


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "The V17 mature-decline signal should begin a reflexive repair rather than "
            "remain below cost without traversing meaningful distance. At the close of "
            "D10, failure to reach half of the fixed A67 target distance while closing "
            "at or below entry is a direct, causal failure of the rebound thesis."
        ),
        "source_strategy": mature_decline.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "single_fixed_failure_exit": {
            "decision_time": "close of entry_cal_idx + 10 market sessions",
            "condition_1": "maximum coordinate high since entry < entry + 0.50*(A67 target-entry)",
            "condition_2": "D10 completed valid coordinate close <= entry coordinate",
            "execution": "next legal sellable 1-minute open strictly after D10 close",
            "unavailable_state": "fail closed to no early exit; retain original H20 path",
            "parameter_search": "NONE",
        },
        "unchanged": {
            "D30_M20_signal_population": True,
            "V13_first_reversal_and_next_minute_entry": True,
            "target": "A67 below L",
            "fallback_time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "T1_limits_suspensions_gap_through_and_QD010": True,
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
            "failure_clocks_built_before_failure_exit_returns": True,
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
            "status": "OUTCOME_BLIND_SINGLE_FIXED_D10_NO_PROGRESS_EXIT",
            "frequency_goal": "at least 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "D10 and 50% target progress are a single natural half-horizon/half-path "
                "falsification clock; no exit family or threshold grid is searched."
            ),
            "diagnostic_disclosure": (
                "Only the frozen D10 no-progress exit may open 2022-2023 returns after "
                "Development passes; that period remains post-observation evidence."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v17_runner": Path(mature_decline.__file__),
        "v17_contract": mature_decline.CONTRACT,
        "v17_stage_a_freeze": mature_decline.STAGE_A_FREEZE,
        "v15_execution_helper": Path(hard_loss.__file__),
    }
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        values[f"{label.lower()}_selected_entries"] = selected_entries_path(label)
        for name in ("actions", "outcome_daily", "sell_opens"):
            values[f"{label.lower()}_{name}"] = source_paths(label)[name]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V18Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def build_period_stage_a(label: str) -> dict[str, Any]:
    entries = pd.read_parquet(selected_entries_path(label))
    days = pd.read_parquet(source_paths(label)["outcome_daily"])
    for frame, columns in (
        (entries, ("signal_date", "signal_time", "entry_date", "entry_time")),
        (days, ("trade_date",)),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in days.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for entry in executable.itertuples(index=False):
        state = no_progress_state(entry, groups[str(entry.symbol)])
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
                "entry_raw_price": float(entry.entry_raw_price),
                "entry_coordinate_price": float(entry.entry_coordinate_price),
                "entry_invalid_step_cum": float(entry.entry_invalid_step_cum),
                **state,
            }
        )
    result = pd.DataFrame(rows).sort_values(
        ["entry_time", "symbol", "gap_id"], kind="mergesort"
    )
    if len(result) != len(executable) or result.gap_id.duplicated().any():
        raise V18Error(f"{label} trigger-clock identity failure")
    result["trigger_at_or_before_entry"] = (
        result.trigger_time.notna() & result.trigger_time.le(result.entry_time)
    )
    if result.trigger_at_or_before_entry.any():
        raise V18Error(f"{label} noncausal trigger clock")
    output = trigger_path(label)
    mature_decline.prior_decline.repair.write_parquet(result, output)
    return {
        "source_executable_entries": len(executable),
        "rows": len(result),
        "state_available": int(result.state_available.sum()),
        "trigger_count": int(result.trigger_time.notna().sum()),
        "unavailable_reasons": result.loc[
            ~result.state_available, "state_unavailable_reason"
        ].value_counts().astype(int).to_dict(),
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
        "stage": "OUTCOME_BLIND_D10_NO_PROGRESS_CLOCK_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "periods": periods,
        "failure_exit_returns_opened": "NO",
        "diagnostic_outcomes_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V18Error("Stage-A freeze missing")
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
        raise V18Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def apply_no_progress_exit(label: str) -> tuple[pd.DataFrame, dict[str, int]]:
    paths = source_paths(label)
    selected = pd.read_parquet(selected_entries_path(label))
    base = pd.read_parquet(paths["outcomes"])
    clocks = pd.read_parquet(trigger_path(label))
    sells = pd.read_parquet(paths["sell_opens"])
    actions = pd.read_parquet(paths["actions"])
    for frame, columns in (
        (selected, ("signal_date", "entry_date", "entry_time")),
        (base, ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time")),
        (clocks, ("trigger_time",)),
        (sells, ("trade_date", "bar_end_time")),
        (actions, ("known_date", "effective_date")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    ids = set(executable.gap_id.astype(str))
    base = base.loc[base.gap_id.astype(str).isin(ids)].copy()
    if len(base) != len(executable) or set(base.gap_id.astype(str)) != ids:
        raise V18Error(f"{label} source outcome identity failure")
    clock_columns = [
        "gap_id",
        "trigger_time",
        "maximum_progress_fraction",
        "current_coordinate_close",
    ]
    frame = base.merge(
        clocks[clock_columns], on="gap_id", how="left", validate="one_to_one"
    )
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
        row["no_progress_exit_applied"] = False
        trigger_time = (
            None if pd.isna(entry.trigger_time) else pd.Timestamp(entry.trigger_time)
        )
        if trigger_time is not None:
            legal = sell_by.get(
                str(entry.symbol), pd.DataFrame(columns=sells.columns)
            )
            fill = hard_loss.repair.next_sell_open(legal, trigger_time)
            if fill is not None and pd.Timestamp(fill["exit_time"]) < pd.Timestamp(
                entry.exit_time
            ):
                if int(fill["exit_cal_idx"]) <= int(entry.entry_cal_idx):
                    audit["t1_violation_count"] += 1
                act = action_by.get(
                    str(entry.symbol), pd.DataFrame(columns=actions.columns)
                )
                cash, cash_json = hard_loss.repair.cash_events(
                    act,
                    pd.Timestamp(entry.entry_date),
                    pd.Timestamp(fill["exit_date"]),
                )
                net = (
                    (float(fill["exit_raw_price"]) * (1 - hard_loss.repair.COST) + cash)
                    / (float(entry.entry_raw_price) * (1 + hard_loss.repair.COST))
                    - 1
                )
                row.update(
                    {
                        "exit_time": pd.Timestamp(fill["exit_time"]),
                        "exit_date": pd.Timestamp(fill["exit_date"]),
                        "exit_cal_idx": int(fill["exit_cal_idx"]),
                        "exit_raw_price": float(fill["exit_raw_price"]),
                        "exit_reason": "D10_NO_PROGRESS",
                        "net_return": net,
                        "holding_sessions": int(fill["exit_cal_idx"])
                        - int(entry.entry_cal_idx),
                        "cash_events_json": cash_json,
                        "no_progress_exit_applied": True,
                    }
                )
        row["net_delta_vs_v17"] = float(row["net_return"]) - original_net
        rows.append(row)
    outcomes = pd.DataFrame(rows).sort_values(
        ["entry_time", "symbol", "gap_id"], kind="mergesort"
    )
    if len(outcomes) != len(base) or set(outcomes.gap_id) != set(base.gap_id):
        raise V18Error(f"{label} outcome conservation failure")
    if audit["t1_violation_count"]:
        raise V18Error(f"{label} T+1 failure: {dict(audit)}")
    output = lane_root(label) / "outcomes.parquet"
    mature_decline.prior_decline.repair.write_parquet(outcomes, output)
    return outcomes, dict(audit)


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    outcomes, outcome_audit = apply_no_progress_exit(label)
    paths = source_paths(label)
    for column in ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    daily = pd.read_parquet(paths["outcome_daily"])
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = lane_root(label)
    root.mkdir(parents=True, exist_ok=True)
    replay = mature_decline.prior_decline.repair
    old_k = replay.v1.PORTFOLIO_K
    try:
        replay.v1.PORTFOLIO_K = PORTFOLIO_K
        replay.v1.configure_external(root, max_exit)
        replay_years = tuple(range(min(years), int(max_exit.year) + 1))
        portfolio = replay.v1.run_portfolio(
            outcomes,
            daily.loc[daily.trade_date.le(max_exit)].copy(),
            replay_years,
        )
    finally:
        replay.v1.PORTFOLIO_K = old_k
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
    return {
        "rule": "D30_M20_D10_NO_PROGRESS_EXIT",
        "source_complete_outcomes": len(outcomes),
        "no_progress_exits_applied": int(outcomes.no_progress_exit_applied.sum()),
        "mean_net_delta_vs_v17": float(outcomes.net_delta_vs_v17.mean()),
        "loss_saved_total": float(
            outcomes.loc[outcomes.net_delta_vs_v17.gt(0), "net_delta_vs_v17"].sum()
        ),
        "winner_regret_total": float(
            outcomes.loc[outcomes.net_delta_vs_v17.lt(0), "net_delta_vs_v17"].sum()
        ),
        "event_metrics": replay.v1.trade_metrics(outcomes),
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


def development_checks(item: dict[str, Any]) -> dict[str, bool]:
    return mature_decline.development_checks(item)


def diagnostic_checks(item: dict[str, Any]) -> dict[str, bool]:
    return mature_decline.diagnostic_checks(item)


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
            "NO_PROGRESS_EXIT_DEVELOPMENT_CANDIDATE"
            if passed
            else "NO_PROGRESS_EXIT_DEVELOPMENT_FAILED"
        ),
        "development_exit_returns_opened": "YES",
        "diagnostic_exit_returns_opened": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    if passed:
        write_json(
            DIAGNOSTIC_FREEZE,
            {
                "experiment": EXPERIMENT,
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_D10_NO_PROGRESS_EXIT_REPLAY",
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "diagnostic_trigger_clocks_sha256": sha256(
                    trigger_path("POST_OBSERVATION_DIAGNOSTIC")
                ),
                "diagnostic_exit_returns_opened": "NO",
            },
        )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V18Error("Development produced no diagnostic freeze")
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "diagnostic_trigger_clocks_sha256": sha256(
            trigger_path("POST_OBSERVATION_DIAGNOSTIC")
        ),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    if drift:
        raise V18Error(f"diagnostic freeze drift: {drift}")
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
            "NO_PROGRESS_EXIT_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "NO_PROGRESS_EXIT_POST_OBSERVATION_FAILED"
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
    baseline = json.loads(
        mature_decline.DEVELOPMENT_RESULT.read_text(encoding="utf-8")
    )["rule_result"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Fixed failure exit",
        "",
        "At D10 close: maximum progress < half the A67 target distance and close <= entry; exit next legal minute open.",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|Exits|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|V17 control|{baseline['portfolio_accepted_trades']}|{baseline['portfolio_accepted_trades_per_year']:.1f}|{pct(baseline['portfolio_mean_net'])}|{pct(baseline['portfolio_median_net'])}|{pct(baseline['portfolio_win'])}|{pct(baseline['portfolio_severe10'])}|0|{pct(baseline['portfolio_cagr'])}|{pct(baseline['portfolio_max_drawdown'])}|",
        f"|D10 no progress|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|{item['no_progress_exits_applied']}|{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|",
    ]
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        observed = result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"Verdict: `{result['verdict']}`.",
            f"Accepted/year: {observed['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(observed['portfolio_mean_net'])}; median: {pct(observed['portfolio_median_net'])}; severe10: {pct(observed['portfolio_severe10'])}; exits: {observed['no_progress_exits_applied']}.",
        ]
    else:
        lines += ["", "2022-2023 D10 no-progress exit returns were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Frequency is a floor of at least 50 accepted trades/year, never a target or upper cap.",
        "- D10/half-target is one fixed causal failure state; no stop grid is searched.",
        "- Signals, entries, target, fallback H20, costs, portfolio, limits, T+1, and QD-010 are unchanged.",
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
