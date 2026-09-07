#!/usr/bin/env python3
# ruff: noqa: E501
"""Replay a simple fresh-capitulation snapback rule on the frozen V13 source."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_first_reversal_v13 as first_reversal,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as replay,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-FRESH-CAPITULATION-SNAPBACK-V27"
START_HEAD = "4ebfad106675e4da51e86378cb376b6f523d88a4"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_fresh_capitulation_snapback_v27"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
CHART_AUDIT = OS / f"artifacts/{EXPERIMENT}_chart_audit.json"
CHART_INDEX = OS / f"artifacts/{EXPERIMENT}_blind_chart_index.csv"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
PDF = ROOT / f"output/pdf/{EXPERIMENT}_blind_semantic_review.pdf"

MAX_GAP_AGE = 14
MIN_REBOUND_FROM_POST_GAP_LOW_OVER_L = 0.05
MIN_PRIOR_PEAK_TO_GAP_SESSIONS = 20
TARGET_FRACTION = first_reversal.TARGET_FRACTION
TIME_STOP = first_reversal.TIME_STOP
PORTFOLIO_K = first_reversal.PORTFOLIO_K
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = replay.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = replay.DIAGNOSTIC_YEARS
ALL_YEARS = DEVELOPMENT_YEARS + DIAGNOSTIC_YEARS


class V27Error(RuntimeError):
    """Fail-closed V27 research error."""


def sha256(path: Path) -> str:
    return replay.sha256(path)


def write_json(path: Path, value: Any) -> None:
    replay.write_json(path, value)


def source_entries_path(label: str) -> Path:
    return replay.source_paths(label)["entries"]


def selected_entries_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "fresh_snapback_selected_entries.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "fresh_snapback"


@contextmanager
def v27_runtime() -> Iterator[None]:
    old_root = replay.EXT_ROOT
    old_selected_entries_path = replay.selected_entries_path
    old_lane_root = replay.lane_root
    try:
        replay.EXT_ROOT = EXT_ROOT
        replay.selected_entries_path = selected_entries_path
        replay.lane_root = lane_root
        yield
    finally:
        replay.EXT_ROOT = old_root
        replay.selected_entries_path = old_selected_entries_path
        replay.lane_root = old_lane_root


def rebound_from_post_gap_low_over_l(frame: pd.DataFrame) -> pd.Series:
    """Distance recovered from the post-gap low, normalized by frozen L."""
    return frame.max_depth.astype(float) - frame.current_depth.astype(float)


def fresh_snapback_mask(frame: pd.DataFrame) -> pd.Series:
    required = frame[
        ["gap_age", "max_depth", "current_depth", "pre_peak_to_gap_sessions"]
    ]
    return (
        required.notna().all(axis=1)
        & frame.gap_age.le(MAX_GAP_AGE)
        & rebound_from_post_gap_low_over_l(frame).ge(
            MIN_REBOUND_FROM_POST_GAP_LOW_OVER_L
        )
        & frame.pre_peak_to_gap_sessions.ge(MIN_PRIOR_PEAK_TO_GAP_SESSIONS)
    )


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "RETROSPECTIVE_FULL_OBSERVED_CANDIDATE_NOT_EXTERNAL_VALIDATION",
        "economic_hypothesis": (
            "A recent downward true gap may create a tradable below-gap snapback only "
            "when it occurs after an already-mature decline rather than an acute "
            "blow-off, price then washes out below L, and demand recovers a meaningful "
            "part of that fresh washout before the first prior-high reversal entry."
        ),
        "source_strategy": first_reversal.EXPERIMENT,
        "source_trigger": "PRIOR_HIGH_REVERSAL",
        "observed_period": ["2017-01-01", "2023-12-31"],
        "simple_admission": {
            "condition_count": 3,
            "mature_decline": "pre_peak_to_gap_sessions >= 20",
            "fresh_shock": "gap_age <= 14 completed sessions at signal",
            "forceful_snapback": "max_depth - current_depth >= 0.05 of frozen L",
            "known_time": "all three conditions known by completed signal-day close",
            "missing_policy": "fail closed",
        },
        "unchanged_v13": {
            "true_gap": "High_t < Low_t_minus_1",
            "strict_120_session_241_minute_vap": True,
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
        "goal_contract": {
            "combined_2017_2023_accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "combined_mean_net_min": 0.03,
            "combined_median_net_positive": True,
            "every_signal_year_trade_mean_positive": True,
            "every_signal_year_portfolio_return_positive": True,
            "combined_severe10_max": 0.15,
            "return_excluding_best_five_days_positive": True,
        },
        "governance": {
            "rule_discovered_after_2017_2023_outcomes_were_observed": True,
            "no_claim_of_external_validation": True,
            "2024_2025_outcomes_not_used_for_rule_selection": True,
            "2026_new_signal_use": False,
            "no_target_horizon_entry_cost_or_execution_change": True,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "THREE_CONDITION_RETROSPECTIVE_SEMANTIC_CANDIDATE",
            "frequency_definition": (
                "combined K80-accepted trades in 2017-2023 divided by seven; "
                "strictly greater than 50"
            ),
            "disclosure": (
                "The F14/R5/M20 rule was distilled after direct tables and chart "
                "review of already-observed 2017-2023 outcomes. It is a reproducible "
                "hypothesis, not new OOS evidence."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    paths: dict[str, Path] = {
        "v13_runner": Path(first_reversal.__file__),
        "v13_contract": first_reversal.CONTRACT,
        "v13_stage_a_freeze": first_reversal.STAGE_A_FREEZE,
        "replay_helper": Path(replay.__file__),
    }
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        paths[f"{label.lower()}_entries"] = replay.source_paths(label)["entries"]
        paths[f"{label.lower()}_outcomes"] = replay.source_paths(label)["outcomes"]
        paths[f"{label.lower()}_daily"] = replay.source_paths(label)["outcome_daily"]
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise V27Error(f"missing frozen source artifacts: {missing}")
    return {name: sha256(path) for name, path in paths.items()}


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(source_entries_path(label))
    for column in ("gap_date", "signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    if entries.gap_id.duplicated().any():
        raise V27Error(f"{label} duplicate source gap identity")
    required = ["gap_age", "max_depth", "current_depth", "pre_peak_to_gap_sessions"]
    if entries[required].isna().any().any():
        raise V27Error(f"{label} missing required semantic feature")
    selected = entries.loc[fresh_snapback_mask(entries)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(years)].copy()
    selected["rebound_from_post_gap_low_over_l"] = rebound_from_post_gap_low_over_l(
        selected
    )
    selected["v27_mature_decline_gate"] = True
    selected["v27_fresh_gap_gate"] = True
    selected["v27_forceful_snapback_gate"] = True
    selected["semantic_feature_latest_timestamp"] = selected.signal_time
    selected["feature_uses_post_signal_information"] = False
    selected = selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    if selected.empty or selected.gap_id.duplicated().any():
        raise V27Error(f"{label} selected identity failure")
    replay.repair.write_parquet(selected, selected_entries_path(label))
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
        "executable_by_year": {str(year): int(annual.get(year, 0)) for year in years},
        "feature_uses_post_signal_information_count": int(
            selected.feature_uses_post_signal_information.sum()
        ),
        "entry_at_or_before_signal_count": int(
            selected.entry_time.notna().mul(selected.entry_time.le(selected.signal_time)).sum()
        ),
        "selected_entries_sha256": sha256(selected_entries_path(label)),
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
        "stage": "RETROSPECTIVE_THREE_CONDITION_IDENTITY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "periods": periods,
        "return_analysis_run": "NO_IN_THIS_REPRODUCTION_STAGE",
        "strategy_backtest_run": "NO_IN_THIS_REPRODUCTION_STAGE",
        "2024_2025_outcomes_used_for_rule_selection": "NO",
        "2026_new_signal_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V27Error("Stage-A freeze missing")
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
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        current = sha256(selected_entries_path(label))
        expected = freeze["periods"][label]["selected_entries_sha256"]
        if current != expected:
            drift[f"{label}_selected_entries"] = [expected, current]
    if drift:
        raise V27Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def run_period(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    with v27_runtime():
        item = replay.run_lane(label, years)
    item["rule"] = "M20_AND_F14_AND_R5"
    return item


def run_combined_portfolio() -> tuple[dict[str, Any], pd.DataFrame]:
    outcomes: list[pd.DataFrame] = []
    daily: list[pd.DataFrame] = []
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        outcomes.append(pd.read_parquet(lane_root(label) / "outcomes.parquet"))
        daily.append(pd.read_parquet(replay.source_paths(label)["outcome_daily"]))
    trades = pd.concat(outcomes, ignore_index=True)
    for column in ("entry_date", "entry_time", "exit_date", "exit_time"):
        trades[column] = pd.to_datetime(trades[column])
    calendar = pd.concat(daily, ignore_index=True)
    calendar["trade_date"] = pd.to_datetime(calendar.trade_date)
    calendar = calendar.sort_values(
        ["symbol", "trade_date"], kind="mergesort"
    ).drop_duplicates(["symbol", "trade_date"], keep="last")
    max_exit = pd.Timestamp(trades.exit_date.max()).normalize()
    root = EXT_ROOT / "combined_2017_2023"
    root.mkdir(parents=True, exist_ok=True)
    old_k = replay.repair.v1.PORTFOLIO_K
    try:
        replay.repair.v1.PORTFOLIO_K = PORTFOLIO_K
        replay.repair.v1.configure_external(root, max_exit)
        portfolio = replay.repair.v1.run_portfolio(
            trades,
            calendar.loc[calendar.trade_date.le(max_exit)].copy(),
            tuple(range(min(ALL_YEARS), int(max_exit.year) + 1)),
        )
    finally:
        replay.repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    return portfolio, accepted


def combine_results(
    development: dict[str, Any], diagnostic: dict[str, Any]
) -> dict[str, Any]:
    portfolio, accepted = run_combined_portfolio()
    yearly = accepted.groupby(accepted.entry_date.dt.year).net_return.agg(
        trades="size",
        mean_net="mean",
        median_net="median",
        win=lambda values: float(values.gt(0).mean()),
        severe10=lambda values: float(values.le(-0.10).mean()),
    )
    yearly_payload = {
        str(int(index)): {
            "trades": int(row.trades),
            "mean_net": float(row.mean_net),
            "median_net": float(row.median_net),
            "win": float(row.win),
            "severe10": float(row.severe10),
        }
        for index, row in yearly.iterrows()
    }
    board = (
        accepted.groupby("board").net_return.agg(
            trades="size",
            mean_net="mean",
            median_net="median",
            win=lambda values: float(values.gt(0).mean()),
            severe10=lambda values: float(values.le(-0.10).mean()),
        )
    )
    board_payload = {
        str(index): {
            "trades": int(row.trades),
            "mean_net": float(row.mean_net),
            "median_net": float(row.median_net),
            "win": float(row.win),
            "severe10": float(row.severe10),
        }
        for index, row in board.iterrows()
    }
    v26_mask = accepted.gap_width_pct.le(0.03) & accepted.pre_gap_corridor_touch_sessions.le(10)
    non_2018 = accepted.loc[accepted.entry_date.dt.year.ne(2018)]
    per_date = accepted.groupby(accepted.entry_date.dt.normalize()).net_return.mean()
    combined = portfolio["COMBINED"]
    annual_returns = {
        str(year): float(combined["annual_returns"].get(str(year), 0.0))
        for year in ALL_YEARS
    }
    return {
        "accepted_trades": len(accepted),
        "accepted_trades_per_year": len(accepted) / len(ALL_YEARS),
        "mean_net": float(accepted.net_return.mean()),
        "median_net": float(accepted.net_return.median()),
        "win": float(accepted.net_return.gt(0).mean()),
        "target_hit": float(accepted.exit_reason.eq("PRE_L_TARGET").mean()),
        "severe10": float(accepted.net_return.le(-0.10).mean()),
        "attack_date_equal_mean": float(per_date.mean()),
        "mean_excluding_2018": float(non_2018.net_return.mean()),
        "trades_excluding_2018": len(non_2018),
        "2018_trade_share": float(accepted.entry_date.dt.year.eq(2018).mean()),
        "outside_v26_count": int((~v26_mask).sum()),
        "outside_v26_share": float((~v26_mask).mean()),
        "yearly": yearly_payload,
        "board": board_payload,
        "portfolio": combined,
        "portfolio_annual_returns_2017_2023": annual_returns,
        "positive_trade_mean_years": int(
            sum(item["mean_net"] > 0 for item in yearly_payload.values())
        ),
        "positive_portfolio_years": int(sum(value > 0 for value in annual_returns.values())),
        "development_reference": development,
        "post_observation_reference": diagnostic,
    }


def goal_checks(combined: dict[str, Any]) -> dict[str, bool]:
    return {
        "accepted_trades_per_year_gt_50": combined["accepted_trades_per_year"]
        > MIN_ACCEPTED_TRADES_PER_YEAR,
        "combined_mean_net_ge_3pct": combined["mean_net"] >= 0.03,
        "combined_median_net_positive": combined["median_net"] > 0,
        "combined_severe10_le_15pct": combined["severe10"] <= 0.15,
        "every_2017_2023_trade_mean_positive": all(
            combined["yearly"].get(str(year), {}).get("mean_net", -1.0) > 0
            for year in ALL_YEARS
        ),
        "every_2017_2023_portfolio_return_positive": all(
            combined["portfolio_annual_returns_2017_2023"].get(str(year), 0.0) > 0
            for year in ALL_YEARS
        ),
        "attack_date_equal_mean_positive": combined["attack_date_equal_mean"] > 0,
        "return_excluding_best_five_days_positive": combined["portfolio"][
            "return_excluding_best_five_days"
        ]
        > 0,
        "both_boards_mean_positive": all(
            combined["board"].get(board, {}).get("mean_net", -1.0) > 0
            for board in ("MAIN", "CHINEXT")
        ),
    }


def run_stage_b() -> dict[str, Any]:
    verification = verify_stage_a()
    development = run_period("DEVELOPMENT", DEVELOPMENT_YEARS)
    diagnostic = run_period("POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS)
    combined = combine_results(development, diagnostic)
    checks = goal_checks(combined)
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "combined_2017_2023": combined,
        "goal_checks": checks,
        "verdict": (
            "V27_RETROSPECTIVE_SIMPLE_CANDIDATE_MEETS_NUMERIC_GOAL"
            if all(checks.values())
            else "V27_RETROSPECTIVE_CANDIDATE_FAILS_NUMERIC_GOAL"
        ),
        "scientific_status": (
            "FULL_PERIOD_OBSERVED_HYPOTHESIS; NO UNTOUCHED EXTERNAL VALIDATION REMAINS"
        ),
        "research_logic_changed": False,
        "2024_2025_outcomes_used_for_rule_selection": "NO",
        "2026_new_signal_data_opened": "NO",
    }
    write_json(RESULT, result)
    return result


def pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2%}"


def render_report() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    combined = result["combined_2017_2023"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "## Economic pattern",
        "",
        "1. Mature decline: the prior 120-session peak is at least 20 completed sessions before the gap.",
        "2. Fresh shock: the first prior-high reversal occurs no later than 14 completed sessions after gap formation.",
        "3. Forceful snapback: signal close has recovered at least 5% of frozen L from the post-gap low.",
        "4. Frozen V13 entry, A67 target below L, H20, 40 bp costs, K80 and all execution/PIT rules remain unchanged.",
        "",
        "## Combined observed evidence",
        "",
        f"Accepted {combined['accepted_trades']} ({combined['accepted_trades_per_year']:.2f}/year); mean {pct(combined['mean_net'])}; median {pct(combined['median_net'])}; win {pct(combined['win'])}; target hit {pct(combined['target_hit'])}; severe10 {pct(combined['severe10'])}.",
        f"Portfolio total return {pct(combined['portfolio']['total_return'])}; CAGR {pct(combined['portfolio']['cagr'])}; MaxDD {pct(combined['portfolio']['max_drawdown'])}; Sharpe {combined['portfolio']['sharpe']:.3f}; average utilization {pct(combined['portfolio']['average_utilization'])}.",
        "",
        "|Year|Trades|Mean|Median|Win|Severe10|Portfolio return|",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for year in ALL_YEARS:
        item = combined["yearly"][str(year)]
        lines.append(
            f"|{year}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|{pct(item['severe10'])}|{pct(combined['portfolio_annual_returns_2017_2023'][str(year)])}|"
        )
    lines += [
        "",
        "## Robustness and complementarity",
        "",
        f"- Outside frozen V26: {combined['outside_v26_count']} trades ({pct(combined['outside_v26_share'])}).",
        f"- Excluding 2018: {combined['trades_excluding_2018']} trades, mean {pct(combined['mean_excluding_2018'])}.",
        f"- 2018 trade share: {pct(combined['2018_trade_share'])}.",
        f"- Return excluding best five days: {pct(combined['portfolio']['return_excluding_best_five_days'])}.",
        "",
        "## Board sleeves",
        "",
        "|Board|Trades|Mean|Median|Win|Severe10|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for board in ("MAIN", "CHINEXT"):
        item = combined["board"][board]
        lines.append(
            f"|{board}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|{pct(item['severe10'])}|"
        )
    lines += [
        "",
        "## Goal checks",
        "",
        *[f"- {key}: `{value}`" for key, value in result["goal_checks"].items()],
        "",
        "## Scientific limitation",
        "",
        "This rule was distilled after 2017-2023 outcomes had been observed. It is a reproducible retrospective candidate, not external validation. The already-opened 2024-2025 results were not used to select it and cannot now provide pristine confirmation.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def _candles(ax: plt.Axes, frame: pd.DataFrame) -> None:
    for row in frame.itertuples(index=False):
        x = mdates.date2num(pd.Timestamp(row.trade_date))
        color = "#d62728" if row.coord_close >= row.coord_open else "#008b72"
        ax.vlines(x, row.coord_low, row.coord_high, color=color, linewidth=0.55)
        bottom = min(row.coord_open, row.coord_close)
        height = max(
            abs(row.coord_close - row.coord_open),
            max(abs(row.coord_close) * 0.0004, 1e-6),
        )
        ax.add_patch(
            Rectangle(
                (x - 0.30, bottom),
                0.60,
                height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.3,
            )
        )
    ax.xaxis_date()


def blind_chart_sample() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        frame = pd.read_parquet(selected_entries_path(label))
        frame["signal_date"] = pd.to_datetime(frame.signal_date)
        frame = frame.loc[frame.entry_status.eq("EXECUTABLE_ENTRY")].copy()
        frames.append(frame)
    selected = pd.concat(frames, ignore_index=True)
    rows: list[pd.DataFrame] = []
    for year in ALL_YEARS:
        for board in ("MAIN", "CHINEXT"):
            part = selected.loc[
                selected.signal_date.dt.year.eq(year) & selected.board.eq(board)
            ].sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort")
            if part.empty:
                continue
            positions = np.unique(np.linspace(0, len(part) - 1, min(3, len(part))).astype(int))
            rows.append(part.iloc[positions])
    sample = pd.concat(rows, ignore_index=True)
    sample = sample.drop_duplicates("gap_id").sort_values(
        ["signal_date", "board", "symbol"], kind="mergesort"
    ).reset_index(drop=True)
    sample["chart_id"] = [f"V27-BLIND-{index:03d}" for index in range(1, len(sample) + 1)]
    return sample


def render_blind_charts() -> dict[str, Any]:
    verify_stage_a()
    sample = blind_chart_sample()
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.astype(str).unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    daily = con.execute(
        f"""SELECT d.trade_date,d.cal_idx,d.symbol,d.coord_open,d.coord_high,d.coord_low,d.coord_close
        FROM read_parquet('{replay.repair.source.DAILY}') d
        JOIN symbols s USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2016-01-01' AND DATE '2023-12-31'
        ORDER BY d.symbol,d.trade_date"""
    ).fetchdf()
    con.close()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    by_symbol = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    index_rows: list[dict[str, Any]] = []
    PDF.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "Title": f"{EXPERIMENT} blind semantic review",
        "Subject": "Outcome-free retrospective semantic chart audit",
        "Author": "CY Market Behavior OS",
        "CreationDate": pd.Timestamp("2000-01-01").to_pydatetime(),
        "ModDate": pd.Timestamp("2000-01-01").to_pydatetime(),
    }
    with PdfPages(PDF, metadata=metadata) as pdf:
        fig = plt.figure(figsize=(15.5, 8.69))
        fig.text(0.06, 0.88, "Fresh Capitulation Snapback V27", fontsize=24, weight="bold")
        fig.text(
            0.06,
            0.77,
            "Blind semantic review - no post-signal bars and no returns\n\n"
            "M20: prior 120-session peak is at least 20 sessions before gap\n"
            "F14: reversal signal occurs within 14 sessions after gap\n"
            "R5: signal close recovered at least 5% of frozen L from post-gap low\n\n"
            "Entry, A67 target, H20, costs and portfolio are not shown on these blind pages.",
            fontsize=14,
            va="top",
            linespacing=1.45,
        )
        fig.text(
            0.06,
            0.26,
            f"Charts: {len(sample)} | deterministic chronology-balanced sample | 2017-2023",
            fontsize=12,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        for event in sample.itertuples(index=False):
            part = by_symbol[str(event.symbol)]
            gap_positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.gap_date)).to_numpy())
            signal_positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
            if len(gap_positions) != 1 or len(signal_positions) != 1:
                raise V27Error(f"chart chronology missing {event.gap_id}")
            gap_pos = int(gap_positions[0])
            signal_pos = int(signal_positions[0])
            prior = part.iloc[max(0, gap_pos - 120) : gap_pos]
            path = part.iloc[gap_pos : signal_pos + 1]
            if len(prior) < 120 or path.empty:
                raise V27Error(f"chart history incomplete {event.gap_id}")
            peak_row = prior.iloc[int(np.nanargmax(prior.coord_high.to_numpy(float)))]
            low_row = path.iloc[int(np.nanargmin(path.coord_low.to_numpy(float)))]
            full = part.iloc[gap_pos - 120 : signal_pos + 1]
            local = part.iloc[max(0, gap_pos - 5) : signal_pos + 1]

            fig = plt.figure(figsize=(15.5, 8.69))
            grid = fig.add_gridspec(
                2,
                1,
                left=0.06,
                right=0.97,
                top=0.84,
                bottom=0.16,
                hspace=0.32,
            )
            ax_full = fig.add_subplot(grid[0, 0])
            ax_local = fig.add_subplot(grid[1, 0])
            fig.suptitle(
                f"{event.chart_id} | {event.symbol} | {event.board} | signal {pd.Timestamp(event.signal_date).date()}",
                fontsize=16,
                weight="bold",
            )
            fig.text(
                0.06,
                0.89,
                f"Gap {pd.Timestamp(event.gap_date).date()} [L,U]=[{event.L:.4f},{event.U:.4f}] | "
                f"peak-to-gap {int(event.pre_peak_to_gap_sessions)} | gap age {int(event.gap_age)} | "
                f"rebound/L {float(event.rebound_from_post_gap_low_over_l):.2%}",
                fontsize=10,
            )
            for ax, view in ((ax_full, full), (ax_local, local)):
                _candles(ax, view)
                ax.axhspan(float(event.L), float(event.U), color="#f6bd60", alpha=0.22)
                ax.axhline(float(event.L), color="#d97706", linestyle="--", linewidth=0.9)
                ax.axhline(float(event.U), color="#b45309", linestyle="--", linewidth=0.9)
                ax.axvline(pd.Timestamp(event.gap_date), color="#8b5e3c", linewidth=1.0)
                ax.axvline(pd.Timestamp(event.signal_date), color="#1d4ed8", linestyle="--", linewidth=1.0)
                ax.scatter(pd.Timestamp(peak_row.trade_date), float(peak_row.coord_high), marker="*", s=85, color="#6b21a8", zorder=8)
                ax.scatter(pd.Timestamp(low_row.trade_date), float(low_row.coord_low), marker="v", s=60, color="#047857", zorder=8)
                ax.grid(alpha=0.16)
                ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=11))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
                ax.tick_params(axis="x", rotation=12, labelsize=7)
                ax.tick_params(axis="y", labelsize=7)
            ax_full.set_title("120 completed sessions before gap through signal", fontsize=9)
            ax_local.set_title("Local gap-to-signal path", fontsize=9)
            fig.text(
                0.06,
                0.025,
                "Purple star = prior peak | Brown line = true-gap formation | Green triangle = post-gap low | Blue dashed line = completed reversal signal | Orange band = [L,U]",
                fontsize=8.8,
            )
            pdf.savefig(fig)
            plt.close(fig)
            index_rows.append(
                {
                    "chart_id": event.chart_id,
                    "gap_id": event.gap_id,
                    "symbol": event.symbol,
                    "board": event.board,
                    "gap_date": pd.Timestamp(event.gap_date),
                    "signal_date": pd.Timestamp(event.signal_date),
                    "pre_peak_to_gap_sessions": int(event.pre_peak_to_gap_sessions),
                    "gap_age": int(event.gap_age),
                    "rebound_from_post_gap_low_over_l": float(event.rebound_from_post_gap_low_over_l),
                    "post_signal_bars_shown": 0,
                    "outcome_shown": False,
                }
            )
    index = pd.DataFrame(index_rows)
    CHART_INDEX.parent.mkdir(parents=True, exist_ok=True)
    index.to_csv(CHART_INDEX, index=False)
    audit = {
        "experiment": EXPERIMENT,
        "chart_count": len(index),
        "pdf_pages": len(index) + 1,
        "selection": "three evenly spaced identities per year and board where available",
        "outcome_used_to_select_charts": False,
        "post_signal_bar_count": 0,
        "pdf": str(PDF),
        "pdf_sha256": sha256(PDF),
        "chart_index_sha256": sha256(CHART_INDEX),
    }
    write_json(CHART_AUDIT, audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    parser.add_argument("--charts", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if not (args.stage_a or args.stage_b or args.charts or args.all):
        parser.error("choose --stage-a, --stage-b, --charts, or --all")
    if args.stage_a or args.all:
        print(json.dumps(run_stage_a(), indent=2, default=str))
    if args.stage_b or args.all:
        result = run_stage_b()
        render_report()
        print(json.dumps(result, indent=2, default=str))
    if args.charts or args.all:
        print(json.dumps(render_blind_charts(), indent=2, default=str))


if __name__ == "__main__":
    main()
