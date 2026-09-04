#!/usr/bin/env python3
# ruff: noqa: E501
"""Test a bounded intraday-acceptance translation of the corrected V4R1 signal.

At the 5th, 15th, or 30th completed minute after the original next-session
open, require (a) at least 60% of completed closes at or above that opening
coordinate and (b) the final close at or above the prior signal close.  Enter
at the next legal minute open.  All later target, H20, cost, T+1, corporate
action, and portfolio semantics remain unchanged.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_deep_mature_decline_repair_v5 as v5,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-INTRADAY-ACCEPTANCE-REPAIR-V7"
START_HEAD = "6657e8d74a"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_intraday_acceptance_repair_v7"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

WINDOWS = (5, 15, 30)
ACCEPTANCE_SHARE = 0.60
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
MIN_TRADES_PER_YEAR = 50.0


class V7Error(RuntimeError):
    """Fail-closed V7 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def stage_a_entries_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "stage_a_acceptance_entries.parquet"


def candidate_root(label: str, window: int) -> Path:
    return EXT_ROOT / label.lower() / f"window_{window:02d}"


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A daily below-gap reversal that immediately loses its next-session "
            "opening cost is likely a weak reflex bounce. Requiring completed-minute "
            "acceptance above both opening cost and the signal close seeks genuine "
            "follow-through before committing capital."
        ),
        "source": repair.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "entry_family": {
            "windows_completed_minutes": list(WINDOWS),
            "condition_1": "share of completed closes >= original opening coordinate is at least 60%",
            "condition_2": "final completed close >= prior signal close coordinate",
            "entry": "next legal 1-minute open strictly after the completed acceptance window",
            "minimum_net_headroom_to_L": 0.05,
            "missing_policy": "FAIL_CLOSED",
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
                "shorter confirmation window",
            ],
        },
        "unchanged_v4r1": {
            "signal_population_and_features": True,
            "target": "delayed_entry + 0.80*(L-delayed_entry)",
            "failure_stop": "NONE",
            "time_stop": "H20 from delayed-entry session",
            "round_trip_cost": 0.004,
            "portfolio": "50/50 Main/ChiNext; K20 per sleeve",
            "T1_limits_suspensions_and_corporate_actions": True,
        },
        "post_2023_scope": "pre-2024 trade-resolution tail only; no post-2023 signal",
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "OUTCOME_BLIND_THREE_WINDOW_ENTRY_TRANSLATION",
            "development_disclosure": (
                "The acceptance mechanism and 5/15/30-minute family were fixed after "
                "prior V4R1 and V6 failures, before delayed-entry outcomes were computed."
            ),
            "diagnostic_disclosure": "2022-2023 remains post-observation evidence.",
            "pre_outcome_mechanical_amendment": {
                "issue": (
                    "The first Stage-A attempt required a volume field that the "
                    "authoritative execution-minute panel does not carry, so every "
                    "otherwise accepted trigger failed closed."
                ),
                "repair": (
                    "Use the authoritative V4R1 legal-minute state fields and the "
                    "existence of the raw minute bar, without inventing volume."
                ),
                "delayed_entry_outcomes_opened_before_repair": "NO",
            },
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    hashes = v5.source_hashes()
    for label in repair.PERIODS:
        for name in ("outcome_minutes", "sell_opens", "actions"):
            hashes[f"{label.lower()}_{name}"] = sha256(repair.paths(label)[name])
    return hashes


def acceptance_passes(
    closes: pd.Series,
    opening_coordinate: float,
    signal_close_coordinate: float,
    window: int,
) -> bool:
    """Return the frozen completed-minute acceptance decision."""
    if len(closes) != window:
        return False
    final_close = float(closes.iloc[-1])
    close_count = int(closes.ge(opening_coordinate).sum())
    return bool(
        np.isfinite(final_close)
        and close_count >= math.ceil(window * ACCEPTANCE_SHARE)
        and final_close >= signal_close_coordinate
    )


def next_minute_is_buyable(row: pd.Series) -> bool:
    """Fail closed unless the next minute has a real legal buyable open."""
    required = (
        "hard_valid",
        "current_day_data_tradable",
        "market_rule_valid",
        "corporate_action_blocking",
        "open",
        "up_limit_price",
    )
    if any(pd.isna(row.get(column)) for column in required):
        return False
    return bool(
        bool(row.hard_valid)
        and bool(row.current_day_data_tradable)
        and bool(row.market_rule_valid)
        and not bool(row.corporate_action_blocking)
        and np.isfinite(float(row.open))
        and float(row.open) > 0
        and round(float(row.open) * 100)
        < round(float(row.up_limit_price) * 100)
    )


def load_first_session_minutes(label: str, entries: pd.DataFrame) -> pd.DataFrame:
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY"), ["gap_id", "entry_date"]].copy()
    con = duckdb.connect()
    con.register("eligible", executable)
    path = repair.paths(label)["outcome_minutes"]
    frame = con.execute(
        f"""
        SELECT m.*,
          row_number() OVER(PARTITION BY m.gap_id ORDER BY m.bar_end_time) AS minute_number
        FROM read_parquet('{path}') m
        JOIN eligible e USING(gap_id)
        WHERE m.trade_date=e.entry_date
        QUALIFY minute_number<={max(WINDOWS) + 1}
        ORDER BY m.gap_id,m.bar_end_time
        """
    ).fetchdf()
    con.close()
    for column in ("trade_date", "bar_end_time"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def build_period_stage_a(label: str, signal_end: pd.Timestamp) -> dict[str, Any]:
    source_entries = pd.read_parquet(repair.paths(label)["entries"])
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        source_entries[column] = pd.to_datetime(source_entries[column])
    base = source_entries.loc[source_entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    minutes = load_first_session_minutes(label, source_entries)
    minute_by = {
        gap_id: part.sort_values("bar_end_time", kind="mergesort")
        for gap_id, part in minutes.groupby("gap_id", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for entry in base.itertuples(index=False):
        path = minute_by.get(str(entry.gap_id), pd.DataFrame())
        for window in WINDOWS:
            row = entry._asdict()
            row.update(
                {
                    "base_entry_date": pd.Timestamp(entry.entry_date),
                    "base_entry_time": pd.Timestamp(entry.entry_time),
                    "base_entry_raw_price": float(entry.entry_raw_price),
                    "base_entry_coordinate_price": float(entry.entry_coordinate_price),
                    "entry_date": pd.NaT,
                    "entry_time": pd.NaT,
                    "entry_raw_price": np.nan,
                    "entry_coordinate_price": np.nan,
                    "entry_cal_idx": np.nan,
                    "entry_coordinate_factor": np.nan,
                    "entry_invalid_step_cum": np.nan,
                    "up_limit_price": np.nan,
                    "realized_net_l_headroom": np.nan,
                    "acceptance_window_minutes": window,
                    "acceptance_required_close_count": math.ceil(window * ACCEPTANCE_SHARE),
                    "acceptance_close_count": 0,
                    "acceptance_ratio": np.nan,
                    "acceptance_final_coord_close": np.nan,
                    "acceptance_trigger_time": pd.NaT,
                    "acceptance_status": "NO_ACCEPTANCE",
                    "entry_status": "NO_ACCEPTANCE",
                }
            )
            observed = path.iloc[:window]
            if len(observed) == window:
                close_count = int(
                    observed.coord_close.ge(float(entry.entry_coordinate_price)).sum()
                )
                ratio = close_count / window
                final_close = float(observed.coord_close.iloc[-1])
                trigger_time = pd.Timestamp(observed.bar_end_time.iloc[-1])
                row.update(
                    {
                        "acceptance_close_count": close_count,
                        "acceptance_ratio": ratio,
                        "acceptance_final_coord_close": final_close,
                        "acceptance_trigger_time": trigger_time,
                    }
                )
                accepted = acceptance_passes(
                    observed.coord_close,
                    float(entry.entry_coordinate_price),
                    float(entry.signal_coord_close),
                    window,
                )
                if accepted:
                    next_rows = path.loc[path.bar_end_time.gt(trigger_time)].head(1)
                    if next_rows.empty:
                        row["acceptance_status"] = "NO_NEXT_MINUTE"
                        row["entry_status"] = "NO_NEXT_BUYABLE_OPEN"
                    else:
                        nxt = next_rows.iloc[0]
                        legal = next_minute_is_buyable(nxt)
                        if not legal:
                            row["acceptance_status"] = "NO_NEXT_BUYABLE_OPEN"
                            row["entry_status"] = "NO_NEXT_BUYABLE_OPEN"
                        else:
                            row.update(
                                {
                                    "entry_date": pd.Timestamp(nxt.trade_date),
                                    "entry_time": pd.Timestamp(nxt.bar_end_time),
                                    "entry_raw_price": float(nxt.open),
                                    "entry_cal_idx": int(nxt.cal_idx),
                                    "entry_coordinate_factor": float(nxt.coordinate_factor),
                                    "entry_invalid_step_cum": float(nxt.invalid_step_cum),
                                    "up_limit_price": float(nxt.up_limit_price),
                                }
                            )
                            row["entry_coordinate_price"] = (
                                row["entry_raw_price"] * row["entry_coordinate_factor"]
                            )
                            row["realized_net_l_headroom"] = (
                                (float(entry.L) / row["entry_coordinate_price"])
                                * (1 - repair.COST)
                                / (1 + repair.COST)
                                - 1
                            )
                            row["acceptance_status"] = "ACCEPTED"
                            row["entry_status"] = (
                                "EXECUTABLE_ENTRY"
                                if row["realized_net_l_headroom"] >= 0.05
                                else "INSUFFICIENT_L_HEADROOM"
                            )
            row["entry_at_or_before_trigger"] = bool(
                pd.notna(row.get("entry_time"))
                and pd.notna(row.get("acceptance_trigger_time"))
                and pd.Timestamp(row["entry_time"])
                <= pd.Timestamp(row["acceptance_trigger_time"])
            )
            row["entry_at_or_before_signal"] = bool(
                pd.notna(row.get("entry_time"))
                and pd.Timestamp(row["entry_time"]) <= pd.Timestamp(entry.signal_time)
            )
            row["entry_after_signal_period_boundary"] = bool(
                pd.notna(row.get("entry_date"))
                and pd.Timestamp(row["entry_date"]) > signal_end
            )
            row["buy_at_or_above_up_limit"] = bool(
                row["entry_status"] == "EXECUTABLE_ENTRY"
                and round(float(row["entry_raw_price"]) * 100)
                >= round(float(row["up_limit_price"]) * 100)
            )
            rows.append(row)
    result = pd.DataFrame(rows).sort_values(
        ["acceptance_window_minutes", "signal_time", "symbol", "gap_id"],
        kind="mergesort",
    )
    if len(result) != len(base) * len(WINDOWS):
        raise V7Error(f"{label} Stage-A identity failure")
    blocking = {
        "entry_at_or_before_trigger_count": int(result.entry_at_or_before_trigger.sum()),
        "entry_at_or_before_signal_count": int(result.entry_at_or_before_signal.sum()),
        "buy_at_or_above_up_limit_count": int(result.buy_at_or_above_up_limit.sum()),
        "post_cutoff_signal_count": int(result.signal_date.gt(signal_end).sum()),
    }
    if any(blocking.values()):
        raise V7Error(f"{label} Stage-A blocking audit: {blocking}")
    output = stage_a_entries_path(label)
    repair.write_parquet(result, output)
    return {
        "source_executable_entries": len(base),
        "rows": len(result),
        "window_status": {
            str(window): result.loc[
                result.acceptance_window_minutes.eq(window), "entry_status"
            ].value_counts().astype(int).to_dict()
            for window in WINDOWS
        },
        "window_executable_entries_by_signal_year": {
            str(window): {
                str(int(year)): int(count)
                for year, count in result.loc[
                    result.acceptance_window_minutes.eq(window)
                    & result.entry_status.eq("EXECUTABLE_ENTRY")
                ].groupby(result.signal_date.dt.year).size().items()
            }
            for window in WINDOWS
        },
        "audit": blocking,
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
        "stage": "OUTCOME_BLIND_ACCEPTANCE_ENTRY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": identities,
        "periods": periods,
        "delayed_entry_outcomes_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V7Error("Stage-A freeze missing")
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
    for label in repair.PERIODS:
        current = sha256(stage_a_entries_path(label))
        expected = freeze["periods"][label]["sha256"]
        if current != expected:
            drift[f"{label}_stage_a_entries"] = [expected, current]
    if drift:
        raise V7Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": identities}


def run_candidate(label: str, window: int, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(stage_a_entries_path(label))
    entries = entries.loc[entries.acceptance_window_minutes.eq(window)].copy()
    for column in (
        "signal_date", "signal_time", "entry_date", "entry_time",
        "acceptance_trigger_time", "base_entry_date", "base_entry_time",
    ):
        entries[column] = pd.to_datetime(entries[column])
    paths = repair.paths(label)
    daily = pd.read_parquet(paths["outcome_daily"])
    minutes = pd.read_parquet(paths["outcome_minutes"])
    sell_opens = pd.read_parquet(paths["sell_opens"])
    actions = pd.read_parquet(paths["actions"])
    for frame, columns in (
        (daily, ("trade_date",)),
        (minutes, ("trade_date", "bar_end_time")),
        (sell_opens, ("trade_date", "bar_end_time")),
        (actions, ("known_date", "effective_date")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    tail_end = repair.PERIODS[label][1]
    root = candidate_root(label, window)
    root.mkdir(parents=True, exist_ok=True)
    outcomes, audit = repair.build_outcomes(
        entries,
        daily,
        minutes,
        sell_opens,
        actions,
        tail_end,
        {"outcomes": root / "outcomes.parquet"},
    )
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    replay_years = tuple(range(min(years), int(max_exit.year) + 1))
    repair.v1.configure_external(root, max_exit)
    portfolio = repair.v1.run_portfolio(
        outcomes,
        daily.loc[daily.trade_date.le(max_exit)].copy(),
        replay_years,
    )
    event = repair.v1.trade_metrics(outcomes)
    combined = portfolio["COMBINED"]
    yearly = outcomes.assign(_year=outcomes.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")]
    return {
        "window_minutes": window,
        "accepted_triggers": int(entries.acceptance_status.eq("ACCEPTED").sum()),
        "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "executable_entries": len(executable),
        "executable_entries_per_year": len(executable) / len(years),
        "complete_outcomes": len(outcomes),
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
        "portfolio_mean_net": float(combined["mean_net"]),
        "portfolio_median_net": float(combined["median_net"]),
        "portfolio_severe10": float(combined["severe10"]),
        "positive_calendar_years": int(
            sum(float(combined["annual_returns"].get(str(year), 0.0)) > 0 for year in years)
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(entries.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "outcome_audit": audit,
        "hashes": {
            "outcomes": sha256(root / "outcomes.parquet"),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
            "portfolio_accepted": sha256(root / "portfolio_accepted.parquet"),
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
    eligible = [item for item in candidates.values() if candidate_eligible(item)]
    if not eligible:
        raise V7Error("no Development acceptance window passes selector")
    return sorted(
        eligible,
        key=lambda item: (
            -item["portfolio_mean_net"],
            -item["portfolio_median_net"],
            item["portfolio_severe10"],
            item["window_minutes"],
        ),
    )[0]


def run_development_and_freeze() -> dict[str, Any]:
    stage_a = verify_stage_a()
    candidates = {
        str(window): run_candidate("DEVELOPMENT", window, DEVELOPMENT_YEARS)
        for window in WINDOWS
    }
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": stage_a,
        "candidate_results": candidates,
        "development_outcomes_opened": "YES",
        "diagnostic_delayed_entry_outcomes_opened": "NO",
    }
    try:
        selected = select_candidate(candidates)
    except V7Error:
        result["selector_passed"] = False
        result["selected_window_minutes"] = None
        result["verdict"] = "INTRADAY_ACCEPTANCE_DEVELOPMENT_FAILED"
        write_json(DEVELOPMENT_RESULT, result)
        return result
    result.update(
        {
            "selector_passed": True,
            "selected_window_minutes": selected["window_minutes"],
            "verdict": "INTRADAY_ACCEPTANCE_DEVELOPMENT_CANDIDATE",
        }
    )
    write_json(DEVELOPMENT_RESULT, result)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_FREEZE_BEFORE_DELAYED_ENTRY_OUTCOMES",
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "selected_window_minutes": selected["window_minutes"],
        "diagnostic_delayed_entry_outcomes_opened": "NO",
        "post_2023_signal_data_opened": "NO",
    }
    write_json(DIAGNOSTIC_FREEZE, freeze)
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V7Error("Development produced no diagnostic freeze")
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
        raise V7Error(f"diagnostic freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    window = int(freeze["selected_window_minutes"])
    diagnostic = run_candidate(
        "POST_OBSERVATION_DIAGNOSTIC", window, DIAGNOSTIC_YEARS
    )
    yearly = diagnostic["event_yearly"]
    checks = {
        "event_mean_net_ge_3pct": diagnostic["event_metrics"]["mean_net"] >= 0.03,
        "portfolio_mean_net_ge_3pct": diagnostic["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": diagnostic["portfolio_median_net"] > 0,
        "at_least_50_trades_per_year": diagnostic["executable_entries_per_year"] >= MIN_TRADES_PER_YEAR,
        "severe10_le_15pct": diagnostic["portfolio_severe10"] <= 0.15,
        "both_year_event_means_positive": all(
            float(yearly.get(str(year), {}).get("mean_net", -1.0)) > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "post_2023_signal_count_zero": diagnostic["post_2023_signal_count"] == 0,
    }
    verdict = (
        "INTRADAY_ACCEPTANCE_POST_OBSERVATION_TARGET_RETAINED"
        if all(checks.values())
        else "INTRADAY_ACCEPTANCE_POST_OBSERVATION_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_window_minutes": window,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": verdict,
        "scientific_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_ONLY",
        "post_2023_signal_data_opened": "NO",
        "repository_2024_plus_data_opened": "INHERITED_AUTHORIZED_PRE_2024_TRADE_RESOLUTION_TAIL_ONLY",
    }
    write_json(DIAGNOSTIC_RESULT, result)
    return result


def pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    lines = [f"# {EXPERIMENT}", "", "## Development", ""]
    lines.append(f"`{development['verdict']}`")
    lines += [
        "",
        "|Window|Executable/year|Mean|Median|Severe10|Positive years|",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for window in WINDOWS:
        item = development["candidate_results"][str(window)]
        lines.append(
            f"|{window}m|{item['executable_entries_per_year']:.1f}|{pct(item['portfolio_mean_net'])}|"
            f"{pct(item['portfolio_median_net'])}|{pct(item['portfolio_severe10'])}|"
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
            f"Selected window: {diagnostic['selected_window_minutes']} minutes.",
            "",
            f"Trades/year: {item['executable_entries_per_year']:.1f}; mean: {pct(item['portfolio_mean_net'])}; median: {pct(item['portfolio_median_net'])}; severe10: {pct(item['portfolio_severe10'])}.",
        ]
    lines += [
        "",
        "## Governance",
        "",
        "- Stage A used only the first 31 same-session minute rows and no delayed-entry returns.",
        "- Entry is strictly after completed acceptance information.",
        "- 2022–2023 is post-observation diagnostic evidence.",
        "- No post-2023 signal was generated.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=(
            "stage-a", "verify-stage-a", "development-freeze",
            "verify-diagnostic-freeze", "diagnostic", "report",
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
