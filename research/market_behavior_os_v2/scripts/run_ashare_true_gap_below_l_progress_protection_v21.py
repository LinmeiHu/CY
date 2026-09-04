#!/usr/bin/env python3
# ruff: noqa: E501
"""Test one fixed post-progress giveback exit on the frozen V20 strategy."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_economic_headroom_v20 as economic_headroom,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_hard_loss_boundary_v15 as hard_loss,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-PROGRESS-PROTECTION-V21"
START_HEAD = "4533f19983"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_progress_protection_v21"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

TARGET_FRACTION = 0.67
ARM_FRACTION_OF_TARGET_PATH = 0.50
TIME_STOP = 20
PORTFOLIO_K = 80
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = economic_headroom.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = economic_headroom.DIAGNOSTIC_YEARS


class V21Error(RuntimeError):
    """Fail-closed V21 research error."""


def sha256(path: Path) -> str:
    return economic_headroom.sha256(path)


def write_json(path: Path, value: Any) -> None:
    economic_headroom.write_json(path, value)


def source_paths(label: str) -> dict[str, Path]:
    return hard_loss.source_paths(label)


def selected_entries_path(label: str) -> Path:
    return economic_headroom.selected_entries_path(label)


def trigger_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "progress_protection_clocks.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "progress_protection"


def target_coordinate(entry: Any) -> float:
    return float(entry.entry_coordinate_price) + TARGET_FRACTION * (
        float(entry.L) - float(entry.entry_coordinate_price)
    )


def arm_coordinate(entry: Any) -> float:
    target = target_coordinate(entry)
    return float(entry.entry_coordinate_price) + ARM_FRACTION_OF_TARGET_PATH * (
        target - float(entry.entry_coordinate_price)
    )


def entry_day_high_is_post_entry_observable(entry: Any) -> bool:
    """The daily high is entirely post-entry only for the 09:30 opening fill."""

    return pd.Timestamp(entry.entry_time).time() == pd.Timestamp("09:30").time()


def progress_protection_state(entry: Any, days: pd.DataFrame) -> dict[str, Any]:
    """Build one causal completed-daily progress/giveback trigger clock."""

    entry_cal_idx = int(entry.entry_cal_idx)
    path = days.loc[
        days.symbol.eq(str(entry.symbol))
        & days.cal_idx.ge(entry_cal_idx)
        & days.cal_idx.le(entry_cal_idx + TIME_STOP)
    ].copy()
    path = path.sort_values("cal_idx", kind="mergesort")
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
    missing_columns = [column for column in required if column not in path.columns]
    if missing_columns:
        raise V21Error(f"missing daily state columns: {missing_columns}")
    if path.empty:
        return {
            "state_available": False,
            "state_unavailable_reason": "NO_H20_PATH",
            "trigger_time": pd.NaT,
        }

    expected = set(range(entry_cal_idx, entry_cal_idx + TIME_STOP + 1))
    observed = set(path.cal_idx.astype(int))
    if not expected.issubset(observed):
        return {
            "state_available": False,
            "state_unavailable_reason": "INCOMPLETE_H20_PATH",
            "trigger_time": pd.NaT,
        }

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
    if not bool(valid.all()):
        return {
            "state_available": False,
            "state_unavailable_reason": "INVALID_OR_NONCOMPARABLE_H20_PATH",
            "trigger_time": pd.NaT,
        }

    eligible = path.copy()
    if not entry_day_high_is_post_entry_observable(entry):
        eligible = eligible.loc[eligible.cal_idx.gt(entry_cal_idx)].copy()
    if eligible.empty:
        return {
            "state_available": False,
            "state_unavailable_reason": "NO_POST_ENTRY_COMPLETED_DAILY_STATE",
            "trigger_time": pd.NaT,
        }

    target = target_coordinate(entry)
    arm = arm_coordinate(entry)
    entry_price = float(entry.entry_coordinate_price)
    if not target > arm > entry_price:
        raise V21Error(f"invalid target/arm geometry for {entry.gap_id}")

    eligible["maximum_coordinate_high_since_entry"] = eligible.coord_high.cummax()
    eligible["armed"] = eligible.maximum_coordinate_high_since_entry.ge(arm)
    eligible["closed_at_or_below_entry"] = eligible.coord_close.le(entry_price)
    armed_rows = eligible.loc[eligible.armed]
    armed_time = (
        pd.NaT
        if armed_rows.empty
        else pd.Timestamp(armed_rows.trade_date.iloc[0]) + pd.Timedelta(hours=15)
    )
    triggered = eligible.loc[
        eligible.armed & eligible.closed_at_or_below_entry
    ]
    if triggered.empty:
        trigger_time = pd.NaT
        trigger_cal_idx: int | None = None
        trigger_close: float | None = None
        maximum_high_at_trigger: float | None = None
    else:
        first = triggered.iloc[0]
        trigger_time = pd.Timestamp(first.trade_date) + pd.Timedelta(hours=15)
        trigger_cal_idx = int(first.cal_idx)
        trigger_close = float(first.coord_close)
        maximum_high_at_trigger = float(first.maximum_coordinate_high_since_entry)

    return {
        "state_available": True,
        "state_unavailable_reason": "",
        "target_coordinate": target,
        "arm_coordinate": arm,
        "armed": bool(eligible.armed.any()),
        "armed_time": armed_time,
        "maximum_progress_fraction": float(
            (eligible.coord_high.max() - entry_price) / (target - entry_price)
        ),
        "trigger_cal_idx": trigger_cal_idx,
        "trigger_coordinate_close": trigger_close,
        "maximum_coordinate_high_at_trigger": maximum_high_at_trigger,
        "trigger_time": trigger_time,
    }


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "The V20 signal has adequate reward headroom, but some attacks demonstrate "
            "real repair progress and then lose the entire move. Once half of the fixed "
            "A67 path has been reached, a completed daily close back at or below entry "
            "invalidates persistence of the rebound and should exit before H20."
        ),
        "source_strategy": economic_headroom.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "single_fixed_exit": {
            "arm": "cumulative post-entry coordinate high >= entry + 0.50*(A67 target-entry)",
            "failure": "first completed valid daily close <= entry coordinate after arm",
            "execution": "next legal sellable 1-minute open strictly after completed failure close",
            "entry_day_policy": (
                "entry-day high may arm only for a 09:30 opening fill; later fills begin "
                "daily-high accumulation on the next completed session"
            ),
            "unavailable_state": "fail closed to no early exit; retain original A67/H20 path",
            "parameter_search": "NONE",
        },
        "unchanged": {
            "V20_signal_population_and_entry": True,
            "target": "A67 below L",
            "fallback_time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "T1_limits_suspensions_gap_through_and_QD010": True,
        },
        "development_success_contract": {
            "accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "frequency_has_no_upper_cap": True,
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
            "both_2022_and_2023_trade_means_positive": True,
            "both_2022_and_2023_portfolio_returns_positive": True,
            "year_2023_mean_net_min": 0.01,
            "year_2023_median_net_min": 0.0,
            "year_2023_win_rate_min": 0.50,
        },
        "governance": {
            "one_exit_no_parameter_selection": True,
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
            "status": "OUTCOME_BLIND_SINGLE_FIXED_HALF_PATH_GIVEBACK_EXIT",
            "frequency_goal": "strictly more than 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "The 50% activation and entry-cost close are one fixed economic state; "
                "no activation, close, or execution family is searched."
            ),
            "diagnostic_disclosure": (
                "Only the frozen V21 exit may open 2022-2023 after Development passes; "
                "the exact 2023 mean/median/win requirements were fixed in advance."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values: dict[str, Path] = {
        "v20_runner": Path(economic_headroom.__file__),
        "v20_contract": economic_headroom.CONTRACT,
        "v20_stage_a_freeze": economic_headroom.STAGE_A_FREEZE,
        "v20_development_result": economic_headroom.DEVELOPMENT_RESULT,
        "v15_execution_helper": Path(hard_loss.__file__),
    }
    label = "DEVELOPMENT"
    values[f"{label.lower()}_v20_entries"] = selected_entries_path(label)
    for name in ("actions", "outcome_daily", "sell_opens", "outcomes"):
        values[f"{label.lower()}_{name}"] = source_paths(label)[name]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V21Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in values.items()}


def diagnostic_source_hashes() -> dict[str, str]:
    label = "POST_OBSERVATION_DIAGNOSTIC"
    values: dict[str, Path] = {
        "v20_diagnostic_result": economic_headroom.DIAGNOSTIC_RESULT,
        f"{label.lower()}_v20_entries": selected_entries_path(label),
    }
    for name in ("actions", "outcome_daily", "sell_opens", "outcomes"):
        values[f"{label.lower()}_{name}"] = source_paths(label)[name]
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise V21Error(f"missing diagnostic source artifacts: {missing}")
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
        str(symbol): part.reset_index(drop=True)
        for symbol, part in days.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for entry in executable.itertuples(index=False):
        symbol_days = groups.get(str(entry.symbol))
        if symbol_days is None:
            state = {
                "state_available": False,
                "state_unavailable_reason": "NO_SYMBOL_DAILY_PATH",
                "trigger_time": pd.NaT,
            }
        else:
            state = progress_protection_state(entry, symbol_days)
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
        raise V21Error(f"{label} trigger-clock identity failure")
    result["trigger_at_or_before_entry"] = (
        result.trigger_time.notna() & result.trigger_time.le(result.entry_time)
    )
    if result.trigger_at_or_before_entry.any():
        raise V21Error(f"{label} noncausal trigger clock")
    output = trigger_path(label)
    hard_loss.repair.write_parquet(result, output)
    armed = (
        result["armed"].fillna(False)
        if "armed" in result.columns
        else pd.Series(False, index=result.index)
    )
    return {
        "source_executable_entries": len(executable),
        "rows": len(result),
        "state_available": int(result.state_available.sum()),
        "armed_count": int(armed.sum()),
        "trigger_count": int(result.trigger_time.notna().sum()),
        "unavailable_reasons": result.loc[
            ~result.state_available, "state_unavailable_reason"
        ].value_counts().astype(int).to_dict(),
        "trigger_at_or_before_entry_count": int(result.trigger_at_or_before_entry.sum()),
        "sha256": sha256(output),
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods = {"DEVELOPMENT": build_period_stage_a("DEVELOPMENT")}
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_HALF_PATH_PROGRESS_PROTECTION_CLOCK_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "periods": periods,
        "failure_exit_returns_opened": "NO",
        "diagnostic_exit_returns_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V21Error("Stage-A freeze missing")
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
    for label in freeze["periods"]:
        current = sha256(trigger_path(label))
        expected = freeze["periods"][label]["sha256"]
        if current != expected:
            drift[f"{label}_trigger_clocks"] = [expected, current]
    if drift:
        raise V21Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def apply_progress_protection_exit(
    label: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    paths = source_paths(label)
    selected = pd.read_parquet(selected_entries_path(label))
    base = pd.read_parquet(paths["outcomes"])
    clocks = pd.read_parquet(trigger_path(label))
    sells = pd.read_parquet(paths["sell_opens"])
    actions = pd.read_parquet(paths["actions"])
    for frame, columns in (
        (selected, ("signal_date", "entry_date", "entry_time")),
        (base, ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time")),
        (clocks, ("armed_time", "trigger_time")),
        (sells, ("trade_date", "bar_end_time")),
        (actions, ("known_date", "effective_date")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    ids = set(executable.gap_id.astype(str))
    base = base.loc[base.gap_id.astype(str).isin(ids)].copy()
    if len(base) != len(executable) or set(base.gap_id.astype(str)) != ids:
        raise V21Error(f"{label} source outcome identity failure")
    clock_columns = [
        "gap_id",
        "state_available",
        "state_unavailable_reason",
        "arm_coordinate",
        "armed",
        "armed_time",
        "maximum_progress_fraction",
        "trigger_cal_idx",
        "trigger_coordinate_close",
        "maximum_coordinate_high_at_trigger",
        "trigger_time",
    ]
    frame = base.merge(
        clocks[clock_columns], on="gap_id", how="left", validate="one_to_one"
    )
    sell_by = {
        str(symbol): part.sort_values("bar_end_time", kind="mergesort")
        for symbol, part in sells.groupby("symbol", sort=False)
    }
    action_by = {
        str(symbol): part.sort_values(["known_date", "effective_date"], kind="mergesort")
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
        row["progress_protection_exit_applied"] = False
        trigger_time = (
            None if pd.isna(entry.trigger_time) else pd.Timestamp(entry.trigger_time)
        )
        if trigger_time is not None:
            legal = sell_by.get(str(entry.symbol), pd.DataFrame(columns=sells.columns))
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
                        "exit_reason": "HALF_PATH_GIVEBACK_TO_ENTRY",
                        "net_return": net,
                        "holding_sessions": int(fill["exit_cal_idx"])
                        - int(entry.entry_cal_idx),
                        "cash_events_json": cash_json,
                        "progress_protection_exit_applied": True,
                    }
                )
        row["net_delta_vs_v20"] = float(row["net_return"]) - original_net
        rows.append(row)
    outcomes = pd.DataFrame(rows).sort_values(
        ["entry_time", "symbol", "gap_id"], kind="mergesort"
    )
    if len(outcomes) != len(base) or set(outcomes.gap_id) != set(base.gap_id):
        raise V21Error(f"{label} outcome conservation failure")
    if audit["t1_violation_count"]:
        raise V21Error(f"{label} T+1 failure: {dict(audit)}")
    output = lane_root(label) / "outcomes.parquet"
    hard_loss.repair.write_parquet(outcomes, output)
    return outcomes, dict(audit)


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    outcomes, outcome_audit = apply_progress_protection_exit(label)
    paths = source_paths(label)
    for column in ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    daily = pd.read_parquet(paths["outcome_daily"])
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = lane_root(label)
    root.mkdir(parents=True, exist_ok=True)
    replay = economic_headroom.fresh_decline.mature_decline.prior_decline.repair
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
    combined = portfolio["COMBINED"]
    return {
        "rule": "V20_HALF_PATH_GIVEBACK_TO_ENTRY",
        "source_complete_outcomes": len(outcomes),
        "progress_protection_exits_applied": int(
            outcomes.progress_protection_exit_applied.sum()
        ),
        "mean_net_delta_vs_v20": float(outcomes.net_delta_vs_v20.mean()),
        "loss_saved_total": float(
            outcomes.loc[outcomes.net_delta_vs_v20.gt(0), "net_delta_vs_v20"].sum()
        ),
        "winner_regret_total": float(
            outcomes.loc[outcomes.net_delta_vs_v20.lt(0), "net_delta_vs_v20"].sum()
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
            "PROGRESS_PROTECTION_DEVELOPMENT_CANDIDATE"
            if passed
            else "PROGRESS_PROTECTION_DEVELOPMENT_FAILED"
        ),
        "development_exit_returns_opened": "YES",
        "diagnostic_exit_returns_opened": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    if passed:
        diagnostic_period = build_period_stage_a("POST_OBSERVATION_DIAGNOSTIC")
        write_json(
            DIAGNOSTIC_FREEZE,
            {
                "experiment": EXPERIMENT,
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_HALF_PATH_GIVEBACK_REPLAY",
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "diagnostic_source_hashes": diagnostic_source_hashes(),
                "diagnostic_period": diagnostic_period,
                "diagnostic_trigger_clocks_sha256": sha256(
                    trigger_path("POST_OBSERVATION_DIAGNOSTIC")
                ),
                "diagnostic_exit_returns_opened": "NO",
            },
        )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V21Error("Development produced no diagnostic freeze")
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
        raise V21Error(f"diagnostic freeze drift: {drift}")
    identities = diagnostic_source_hashes()
    if identities != freeze.get("diagnostic_source_hashes"):
        raise V21Error(
            "diagnostic source drift: "
            f"{[freeze.get('diagnostic_source_hashes'), identities]}"
        )
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
            "PROGRESS_PROTECTION_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "PROGRESS_PROTECTION_POST_OBSERVATION_FAILED"
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
    baseline = json.loads(
        economic_headroom.DEVELOPMENT_RESULT.read_text(encoding="utf-8")
    )["rule_result"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Fixed rule",
        "",
        "V20 unchanged. After the post-entry high reaches 50% of the fixed A67 path, the first completed daily close at or below entry exits at the next legal minute open.",
        "",
        "## Development",
        "",
        f"`{development['verdict']}`",
        "",
        "|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|Exits|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|V20 control|{baseline['portfolio_accepted_trades']}|{baseline['portfolio_accepted_trades_per_year']:.1f}|{pct(baseline['portfolio_mean_net'])}|{pct(baseline['portfolio_median_net'])}|{pct(baseline['portfolio_win'])}|{pct(baseline['portfolio_severe10'])}|0|{pct(baseline['portfolio_cagr'])}|{pct(baseline['portfolio_max_drawdown'])}|",
        f"|V21|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|{item['progress_protection_exits_applied']}|{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|",
        "",
        "### Development chronology",
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
            f"Accepted/year: {observed['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(observed['portfolio_mean_net'])}; median: {pct(observed['portfolio_median_net'])}; win: {pct(observed['portfolio_win'])}; severe10: {pct(observed['portfolio_severe10'])}; exits: {observed['progress_protection_exits_applied']}.",
            "",
            "|Year|Trades|Mean|Median|Win|Portfolio return|",
            "|---|---:|---:|---:|---:|---:|",
            *yearly_rows(observed),
        ]
    else:
        lines += ["", "2022-2023 V21 returns were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Frequency must remain strictly above 50 accepted trades/year; there is no upper cap.",
        "- V21 uses exactly one 50%-path activation and one entry-cost close failure line.",
        "- Signals, entries, A67, fallback H20, costs, portfolio, T+1, limits, suspensions, and QD-010 are unchanged.",
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
