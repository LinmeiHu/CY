#!/usr/bin/env python3
# ruff: noqa: E501
"""Test one fixed board-regime translation on the V24 signal identity."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_board_supported_reversal_v24 as v24,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as replay_lane,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-REGIME-ADAPTIVE-TRANSLATION-V25"
START_HEAD = "ff75736db9"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_regime_adaptive_translation_v25"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

BOARD_WINDOW = 5
STRONG_TARGET_FRACTION = 0.67
STRONG_TIME_STOP = 20
WEAK_TARGET_FRACTION = 0.50
WEAK_TIME_STOP = 10
PORTFOLIO_K = 80
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = replay_lane.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = replay_lane.DIAGNOSTIC_YEARS


class V25Error(RuntimeError):
    """Fail-closed V25 research error."""


def sha256(path: Path) -> str:
    return replay_lane.sha256(path)


def write_json(path: Path, value: Any) -> None:
    replay_lane.write_json(path, value)


def source_root(label: str) -> Path:
    return replay_lane.source_root(label)


def source_paths(label: str) -> dict[str, Path]:
    root = source_root(label)
    return {
        "entries": root / "entries.parquet",
        "outcomes": root / "outcomes.parquet",
        "outcome_daily": root / "outcome_daily.parquet",
        "outcome_minutes": root / "outcome_minutes.parquet",
        "sell_opens": root / "sell_opens.parquet",
        "actions": root / "qd010_actions.parquet",
    }


def selected_entries_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "regime_selected_entries.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "regime_translation"


def board_context_with_trailing_return() -> pd.DataFrame:
    frame = pd.read_parquet(v24.BOARD_CONTEXT, columns=["trade_date", "group_id", "ret"])
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    if frame.duplicated(["trade_date", "group_id"]).any():
        raise V25Error("duplicate board context identity")
    frame = frame.sort_values(["group_id", "trade_date"], kind="mergesort")
    frame["board_return_5d"] = frame.groupby("group_id", sort=False).ret.transform(
        lambda values: (1.0 + values).rolling(BOARD_WINDOW, min_periods=BOARD_WINDOW).apply(lambda window: float(window.prod()), raw=True) - 1.0
    )
    return frame.rename(columns={"ret": "signal_board_return"})


def translation_regime(return_5d: pd.Series) -> pd.Series:
    if return_5d.isna().any():
        raise V25Error("missing five-session board return")
    return return_5d.ge(0.0).map({True: "REPAIRED_A67_H20", False: "WEAK_A50_H10"})


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A nonnegative signal-day board bounce inside a still-negative five-session "
            "board path is a weaker counter-trend state than a board whose five-session "
            "return has recovered to nonnegative. Keep the same stock signal and entry, "
            "but realize a nearer half-path rebound over H10 in the weak state while "
            "retaining A67/H20 in the repaired state."
        ),
        "source_signal": v24.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "signal_identity": {
            "trigger": "V13 PRIOR_HIGH_REVERSAL",
            "same_day_board_gate": "completed signal-day equal-weight board return >= 0",
            "entry": "unchanged first legal buyable 1-minute open after signal",
        },
        "single_translation_rule": {
            "feature": "five-session compounded equal-weight board return ending on signal day",
            "known_time": "signal-day close, before next-session entry",
            "missing_policy": "fail closed",
            "threshold": "natural zero; no threshold search",
            "if_nonnegative": {"target": "A67 below L", "time_stop": "H20"},
            "if_negative": {"target": "A50 below L", "time_stop": "H10"},
            "admission_filter": "NONE; all V24 signals remain eligible",
        },
        "unchanged": {
            "true_gap_and_clean_vap_corridor": True,
            "no_L_touch_before_signal": True,
            "maximum_depth_below_L_min": 0.10,
            "signal_depth_below_L_min": 0.05,
            "minimum_net_headroom_to_L": 0.05,
            "failure_stop": "NONE",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "T1_limits_suspensions_and_QD010": True,
        },
        "development_success_contract": {
            "accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "portfolio_mean_net_min": 0.03,
            "portfolio_median_net_positive": True,
            "portfolio_severe10_max": 0.15,
            "positive_trade_mean_years_min": 4,
            "positive_portfolio_years_min": 4,
            "attack_date_equal_mean_positive": True,
        },
        "diagnostic_success_contract": v24.contract_value()["diagnostic_success_contract"],
        "governance": {
            "development_informed_fixed_regime_translation": True,
            "development_disclosure": "A50/H10 in a negative five-session board regime was specified after Development-only mechanism analysis.",
            "diagnostic_opened_only_after_development_pass": True,
            "no_diagnostic_threshold_selection": True,
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
            "status": "DEVELOPMENT_INFORMED_FIXED_BOARD_REGIME_TRANSLATION",
            "frequency_goal": "strictly more than 50 accepted trades per year; no upper cap",
            "scientific_scope": "same V24 admission and entry; only A67/H20 versus A50/H10 translation changes",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes(label: str, outcomes: bool) -> dict[str, str]:
    paths: dict[str, Path] = {
        "v24_runner": Path(v24.__file__),
        "v24_contract": v24.CONTRACT,
        "board_context": v24.BOARD_CONTEXT,
        "source_entries": source_paths(label)["entries"],
    }
    if outcomes:
        for name in ("outcomes", "outcome_daily", "outcome_minutes", "sell_opens", "actions"):
            paths[f"source_{name}"] = source_paths(label)[name]
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise V25Error(f"missing source artifacts: {missing}")
    return {name: sha256(path) for name, path in paths.items()}


def build_period_stage_a(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(source_paths(label)["entries"])
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    if entries.gap_id.duplicated().any():
        raise V25Error(f"{label} duplicate source gap identity")
    context = board_context_with_trailing_return()
    merged = entries.merge(
        context,
        left_on=["signal_date", "board"],
        right_on=["trade_date", "group_id"],
        how="left",
        validate="many_to_one",
    ).drop(columns=["trade_date", "group_id"])
    if merged[["signal_board_return", "board_return_5d"]].isna().any().any():
        raise V25Error(f"{label} missing board state")
    selected = merged.loc[v24.board_support_mask(merged)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(years)].copy()
    selected["translation_regime"] = translation_regime(selected.board_return_5d)
    selected["target_fraction"] = selected.translation_regime.map(
        {"REPAIRED_A67_H20": STRONG_TARGET_FRACTION, "WEAK_A50_H10": WEAK_TARGET_FRACTION}
    )
    selected["time_stop"] = selected.translation_regime.map(
        {"REPAIRED_A67_H20": STRONG_TIME_STOP, "WEAK_A50_H10": WEAK_TIME_STOP}
    ).astype(int)
    selected["board_context_latest_timestamp"] = selected.signal_time
    selected["feature_uses_post_signal_information"] = False
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    output = selected_entries_path(label)
    replay_lane.repair.write_parquet(selected, output)
    executable = selected.entry_status.eq("EXECUTABLE_ENTRY")
    annual = selected.loc[executable].assign(_year=selected.loc[executable, "signal_date"].dt.year).groupby("_year").size()
    regimes = selected.loc[executable, "translation_regime"].value_counts()
    return {
        "source_entries": len(entries),
        "selected_signals": len(selected),
        "executable_entries": int(executable.sum()),
        "executable_entries_per_year": float(executable.sum() / len(years)),
        "executable_by_year": {str(year): int(annual.get(year, 0)) for year in years},
        "translation_regime_counts": {str(key): int(value) for key, value in regimes.items()},
        "feature_uses_post_signal_information_count": 0,
        "selected_entries_sha256": sha256(output),
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    period = build_period_stage_a("DEVELOPMENT", DEVELOPMENT_YEARS)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_FIXED_REGIME_TRANSLATION_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes("DEVELOPMENT", outcomes=False),
        "periods": {"DEVELOPMENT": period},
        "development_outcomes_opened": "NO",
        "diagnostic_outcomes_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V25Error("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC), "runner_sha256": sha256(Path(__file__))}
    drift = {key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value}
    current_sources = source_hashes("DEVELOPMENT", outcomes=False)
    if current_sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), current_sources]
    current_entries = sha256(selected_entries_path("DEVELOPMENT"))
    expected_entries = freeze["periods"]["DEVELOPMENT"]["selected_entries_sha256"]
    if current_entries != expected_entries:
        drift["development_selected_entries"] = [expected_entries, current_entries]
    if drift:
        raise V25Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


@contextmanager
def weak_outcome_runtime() -> Iterator[None]:
    repair = replay_lane.repair
    old_target = repair.TARGET_FRACTION
    old_horizon = repair.TIME_STOP
    try:
        repair.TARGET_FRACTION = WEAK_TARGET_FRACTION
        repair.TIME_STOP = WEAK_TIME_STOP
        yield
    finally:
        repair.TARGET_FRACTION = old_target
        repair.TIME_STOP = old_horizon


def read_period_sources(label: str, weak_ids: set[str]) -> dict[str, pd.DataFrame]:
    paths = source_paths(label)
    frames = {
        "outcomes": pd.read_parquet(paths["outcomes"]),
        "daily": pd.read_parquet(paths["outcome_daily"]),
        "minutes": pd.read_parquet(paths["outcome_minutes"], filters=[("gap_id", "in", sorted(weak_ids))]),
        "sell": pd.read_parquet(paths["sell_opens"]),
        "actions": pd.read_parquet(paths["actions"]),
    }
    date_columns = {
        "outcomes": ("signal_date", "signal_time", "entry_date", "entry_time", "exit_date", "exit_time"),
        "daily": ("trade_date",),
        "minutes": ("trade_date", "bar_end_time"),
        "sell": ("trade_date", "bar_end_time"),
        "actions": ("known_date", "effective_date"),
    }
    for name, columns in date_columns.items():
        for column in columns:
            frames[name][column] = pd.to_datetime(frames[name][column])
    return frames


def build_regime_outcomes(label: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    selected = pd.read_parquet(selected_entries_path(label))
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        selected[column] = pd.to_datetime(selected[column])
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    weak = executable.loc[executable.translation_regime.eq("WEAK_A50_H10")].copy()
    strong = executable.loc[executable.translation_regime.eq("REPAIRED_A67_H20")].copy()
    weak_ids = set(weak.gap_id.astype(str))
    frames = read_period_sources(label, weak_ids)
    source_outcomes = frames["outcomes"]
    strong_ids = set(strong.gap_id.astype(str))
    strong_outcomes = source_outcomes.loc[source_outcomes.gap_id.astype(str).isin(strong_ids)].copy()
    enrich = selected[["gap_id", "signal_board_return", "board_return_5d", "translation_regime", "target_fraction", "time_stop"]]
    strong_outcomes = strong_outcomes.merge(enrich, on="gap_id", how="left", validate="one_to_one")
    root = lane_root(label)
    root.mkdir(parents=True, exist_ok=True)
    weak_path = root / "weak_a50_h10_outcomes.parquet"
    if len(weak):
        weak_symbols = set(weak.symbol.astype(str))
        minutes = frames["minutes"].loc[frames["minutes"].gap_id.astype(str).isin(weak_ids)].copy()
        sell = frames["sell"].loc[frames["sell"].symbol.astype(str).isin(weak_symbols)].copy()
        actions = frames["actions"].loc[frames["actions"].symbol.astype(str).isin(weak_symbols)].copy()
        tail_end = pd.Timestamp("2022-03-31" if label == "DEVELOPMENT" else "2024-03-31")
        with weak_outcome_runtime():
            weak_outcomes, audit = replay_lane.repair.build_outcomes(
                weak,
                frames["daily"],
                minutes,
                sell,
                actions,
                tail_end,
                {"outcomes": weak_path},
            )
        weak_outcomes.loc[weak_outcomes.exit_reason.eq("H20_TIME_STOP"), "exit_reason"] = "H10_TIME_STOP"
        replay_lane.repair.write_parquet(weak_outcomes, weak_path)
    else:
        weak_outcomes = strong_outcomes.iloc[0:0].copy()
        audit = {}
    outcomes = pd.concat([strong_outcomes, weak_outcomes], ignore_index=True, sort=False).sort_values(
        ["entry_time", "symbol", "gap_id"], kind="mergesort"
    )
    if len(outcomes) != len(executable) or set(outcomes.gap_id.astype(str)) != set(executable.gap_id.astype(str)):
        raise V25Error(f"{label} outcome identity conservation failure")
    if outcomes.target_fraction.isna().any() or outcomes.time_stop.isna().any():
        raise V25Error(f"{label} missing translation fields")
    replay_lane.repair.write_parquet(outcomes, root / "outcomes.parquet")
    return outcomes, frames["daily"], audit


def run_lane(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    outcomes, daily, audit = build_regime_outcomes(label)
    if not outcomes.signal_date.dt.year.isin(years).all():
        raise V25Error(f"{label} signal-period boundary failure")
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = lane_root(label)
    old_k = replay_lane.repair.v1.PORTFOLIO_K
    try:
        replay_lane.repair.v1.PORTFOLIO_K = PORTFOLIO_K
        replay_lane.repair.v1.configure_external(root, max_exit)
        replay_years = tuple(range(min(years), int(max_exit.year) + 1))
        portfolio = replay_lane.repair.v1.run_portfolio(outcomes, daily.loc[daily.trade_date.le(max_exit)].copy(), replay_years)
    finally:
        replay_lane.repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    yearly = accepted.assign(_year=accepted.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median", win=lambda values: float(values.gt(0).mean())
    )
    yearly_payload = {
        str(int(index)): {"trades": int(row.trades), "mean_net": float(row.mean_net), "median_net": float(row.median_net), "win": float(row.win)}
        for index, row in yearly.iterrows()
    }
    regime_metrics = {
        str(regime): replay_lane.repair.v1.trade_metrics(part)
        for regime, part in accepted.groupby("translation_regime", sort=True)
    }
    combined = portfolio["COMBINED"]
    per_date = outcomes.assign(_date=pd.to_datetime(outcomes.entry_date).dt.normalize()).groupby("_date").net_return.mean()
    return {
        "rule": "V24_SIGNAL_WITH_BOARD_5D_REGIME_TRANSLATION",
        "selected_signals": len(pd.read_parquet(selected_entries_path(label))),
        "executable_entries": len(outcomes),
        "event_metrics": replay_lane.repair.v1.trade_metrics(outcomes),
        "translation_regime_metrics_accepted": regime_metrics,
        "weak_outcome_audit": audit,
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
        "positive_trade_mean_years": int(sum(float(yearly_payload.get(str(year), {}).get("mean_net", 0.0)) > 0 for year in years)),
        "positive_portfolio_years": int(sum(float(combined["annual_returns"].get(str(year), 0.0)) > 0 for year in years)),
        "attack_date_equal_mean": float(per_date.mean()),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_2023_signal_count": int(pd.to_datetime(outcomes.signal_date).gt(pd.Timestamp("2023-12-31")).sum()),
        "hashes": {
            "outcomes": sha256(root / "outcomes.parquet"),
            "portfolio_accepted": sha256(root / "portfolio_accepted.parquet"),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
        },
    }


def development_checks(item: dict[str, Any]) -> dict[str, bool]:
    return {
        "accepted_trades_per_year_gt_50": item["portfolio_accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR,
        "portfolio_mean_net_ge_3pct": item["portfolio_mean_net"] >= 0.03,
        "portfolio_median_net_positive": item["portfolio_median_net"] > 0,
        "portfolio_severe10_le_15pct": item["portfolio_severe10"] <= 0.15,
        "positive_trade_mean_years_ge_4": item["positive_trade_mean_years"] >= 4,
        "positive_portfolio_years_ge_4": item["positive_portfolio_years"] >= 4,
        "attack_date_equal_mean_positive": item["attack_date_equal_mean"] > 0,
        "post_2023_signal_count_zero": item["post_2023_signal_count"] == 0,
    }


def diagnostic_checks(item: dict[str, Any]) -> dict[str, bool]:
    return v24.diagnostic_checks(item)


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
        "verdict": "REGIME_ADAPTIVE_TRANSLATION_DEVELOPMENT_CANDIDATE" if passed else "REGIME_ADAPTIVE_TRANSLATION_DEVELOPMENT_FAILED",
        "development_outcomes_opened": "YES",
        "diagnostic_outcomes_opened": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    if passed:
        diagnostic_period = build_period_stage_a("POST_OBSERVATION_DIAGNOSTIC", DIAGNOSTIC_YEARS)
        write_json(
            DIAGNOSTIC_FREEZE,
            {
                "experiment": EXPERIMENT,
                "stage": "DIAGNOSTIC_FREEZE_BEFORE_REGIME_TRANSLATION_REPLAY",
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "diagnostic_source_hashes": source_hashes("POST_OBSERVATION_DIAGNOSTIC", outcomes=True),
                "diagnostic_period": diagnostic_period,
                "diagnostic_selected_entries_sha256": sha256(selected_entries_path("POST_OBSERVATION_DIAGNOSTIC")),
                "diagnostic_outcomes_opened": "NO",
            },
        )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V25Error("Development produced no diagnostic freeze")
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "diagnostic_selected_entries_sha256": sha256(selected_entries_path("POST_OBSERVATION_DIAGNOSTIC")),
    }
    drift = {key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value}
    current_sources = source_hashes("POST_OBSERVATION_DIAGNOSTIC", outcomes=True)
    if current_sources != freeze.get("diagnostic_source_hashes"):
        drift["diagnostic_source_hashes"] = [freeze.get("diagnostic_source_hashes"), current_sources]
    if drift:
        raise V25Error(f"diagnostic freeze drift: {drift}")
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
        "verdict": "REGIME_ADAPTIVE_TRANSLATION_POST_OBSERVATION_TARGET_RETAINED" if all(checks.values()) else "REGIME_ADAPTIVE_TRANSLATION_POST_OBSERVATION_FAILED",
        "scientific_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_ONLY",
        "post_2023_signal_or_selection_data_opened": "NO",
        "repository_2024_plus_data_opened": "AUTHORIZED_PRE_2024_TRADE_MANAGEMENT_AND_COMPLETION_ONLY",
    }
    write_json(DIAGNOSTIC_RESULT, result)
    return result


def pct(value: Any) -> str:
    return f"{float(value):.2%}"


def yearly_rows(item: dict[str, Any]) -> list[str]:
    annual_returns = item["portfolio"]["COMBINED"]["annual_returns"]
    return [
        f"|{year}|{values['trades']}|{pct(values['mean_net'])}|{pct(values['median_net'])}|{pct(values['win'])}|{pct(annual_returns.get(year, 0.0))}|"
        for year, values in item["accepted_trade_yearly"].items()
    ]


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    item = development["rule_result"]
    lines = [
        f"# {EXPERIMENT}", "", "## Fixed mechanism", "",
        "V24 signal identity and entry. Five-session board return >=0 keeps A67/H20; a negative five-session board return uses A50/H10. No signal is removed.",
        "", "## Development", "", f"`{development['verdict']}`", "",
        f"Accepted {item['portfolio_accepted_trades']} ({item['portfolio_accepted_trades_per_year']:.1f}/year); mean {pct(item['portfolio_mean_net'])}; median {pct(item['portfolio_median_net'])}; win {pct(item['portfolio_win'])}; severe10 {pct(item['portfolio_severe10'])}; CAGR {pct(item['portfolio_cagr'])}; MaxDD {pct(item['portfolio_max_drawdown'])}.",
        "", "|Year|Trades|Mean|Median|Win|Portfolio return|", "|---|---:|---:|---:|---:|---:|", *yearly_rows(item),
        "", "## Translation regimes", "", "```json", json.dumps(item["translation_regime_metrics_accepted"], indent=2, sort_keys=True), "```",
    ]
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        observed = result["diagnostic"]
        lines += [
            "", "## Post-observation diagnostic", "", f"Verdict: `{result['verdict']}`.",
            f"Accepted/year: {observed['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(observed['portfolio_mean_net'])}; median: {pct(observed['portfolio_median_net'])}; win: {pct(observed['portfolio_win'])}; severe10: {pct(observed['portfolio_severe10'])}.",
            "", "|Year|Trades|Mean|Median|Win|Portfolio return|", "|---|---:|---:|---:|---:|---:|", *yearly_rows(observed),
        ]
    else:
        lines += ["", "2022-2023 outcomes were not opened."]
    lines += [
        "", "## Governance", "",
        "- The translation rule was frozen after Development-only mechanism analysis and before this lane opened 2022-2023 outcomes.",
        "- The five-session board feature uses completed sessions ending at the signal-day close; entry remains next session.",
        "- No diagnostic threshold selection is permitted.",
        "- 2024 data may only manage and complete pre-2024 signals.", "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("stage-a", "verify-stage-a", "development-freeze", "verify-diagnostic-freeze", "diagnostic", "report"))
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
