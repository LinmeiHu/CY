#!/usr/bin/env python3
# ruff: noqa: E501
"""Test earlier causal reversal triggers below a strict clean true gap."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    ashare_below_gap_rebound_v1_core as core,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-FIRST-REVERSAL-V13"
START_HEAD = "3d84de0e9d"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_first_reversal_v13"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

TRIGGERS = (
    "PRIOR_HIGH_REVERSAL",
    "TWO_HIGHER_CLOSES",
    "THREE_DAY_HIGH_BREAK",
)
TARGET_FRACTION = 0.67
PORTFOLIO_K = 80
TIME_STOP = 20
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
PERIODS = {
    "DEVELOPMENT": (
        pd.Timestamp("2021-12-31"),
        pd.Timestamp("2022-03-31"),
        DEVELOPMENT_YEARS,
    ),
    "POST_OBSERVATION_DIAGNOSTIC": (
        pd.Timestamp("2023-12-31"),
        pd.Timestamp("2024-03-31"),
        DIAGNOSTIC_YEARS,
    ),
}


class V13Error(RuntimeError):
    """Fail-closed V13 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def trigger_root(trigger: str) -> Path:
    return EXT_ROOT / trigger.lower()


@contextmanager
def trigger_runtime(trigger: str) -> Iterator[None]:
    old_root = repair.EXT_ROOT
    old_target = repair.TARGET_FRACTION
    old_time_stop = repair.TIME_STOP
    old_k = repair.v1.PORTFOLIO_K
    try:
        repair.EXT_ROOT = trigger_root(trigger)
        repair.TARGET_FRACTION = TARGET_FRACTION
        repair.TIME_STOP = TIME_STOP
        repair.v1.PORTFOLIO_K = PORTFOLIO_K
        yield
    finally:
        repair.EXT_ROOT = old_root
        repair.TARGET_FRACTION = old_target
        repair.TIME_STOP = old_time_stop
        repair.v1.PORTFOLIO_K = old_k


def trigger_flags(
    current_close: float,
    previous_close: float,
    previous2_close: float,
    previous_high: float,
    previous3_highs: list[float],
) -> dict[str, bool]:
    return {
        "PRIOR_HIGH_REVERSAL": current_close > previous_high,
        "TWO_HIGHER_CLOSES": (
            current_close > previous_close and previous_close > previous2_close
        ),
        "THREE_DAY_HIGH_BREAK": current_close > max(previous3_highs),
    }


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "The first daily MA5 reclaim can enter after much of a below-gap rebound "
            "has already occurred. A first causal price-action reversal after a 10% "
            "washout may capture more of the path while the same clean-corridor and "
            "pre-L first-touch protections remain binding."
        ),
        "source_population": repair.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "common_state": {
            "true_gap": "High_t < Low_t_minus_1",
            "minimum_gap_width_pct": 0.01,
            "pre_gap_history": "exact 120 sessions x 241 minutes",
            "pre_gap_inside_touch_sessions_max": 12,
            "pre_gap_corridor_touch_sessions_max": 20,
            "pre_gap_inside_density_relative_local_max": 1.0,
            "pre_gap_corridor_density_relative_local_max": 1.0,
            "pre_gap_return_20d_max": 0.0,
            "maximum_depth_below_L_min": 0.10,
            "signal_depth_below_L_min": 0.05,
            "days_since_20d_low": [1, 10],
            "minimum_recovery_from_20d_low": 0.03,
            "no_L_touch_before_signal": True,
        },
        "bounded_trigger_family": {
            "PRIOR_HIGH_REVERSAL": "current completed daily close > previous completed daily high",
            "TWO_HIGHER_CLOSES": "two consecutive completed daily close increases",
            "THREE_DAY_HIGH_BREAK": "current completed daily close > maximum high of prior three completed sessions",
        },
        "first_trigger_only_per_gap": True,
        "entry": "first legal buyable 1-minute open strictly after completed daily trigger",
        "minimum_net_headroom_to_L": 0.05,
        "target": "entry + 0.67*(L-entry), strictly below L",
        "failure_stop": "NONE",
        "time_stop": "H20 completed sessions then next legal sellable 1-minute open",
        "round_trip_cost": 0.004,
        "portfolio": "Main/ChiNext 50/50; K80 per sleeve; 1/80 sleeve NAV per position",
        "development_selector": {
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
                "fixed trigger order",
            ],
        },
        "governance": {
            "diagnostic_opened_only_for_selected_trigger": True,
            "no_post_2023_signals_features_or_selection": True,
            "post_2023_data_scope": "entry/management/completion of pre-2024 signals only",
            "T1_limits_suspensions_and_QD010": True,
            "no_leverage_or_cross_sleeve_transfer": True,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "status": "OUTCOME_BLIND_BOUNDED_FIRST_REVERSAL_TRIGGER_FAMILY",
            "frequency_goal": "at least 50 accepted trades per year; no upper cap",
            "development_disclosure": (
                "The three natural price-action triggers, A67 target, K80 capacity, "
                "and selector were frozen before V13 outcomes were computed."
            ),
            "diagnostic_disclosure": (
                "Only the Development-selected trigger may open 2022-2023 outcomes; "
                "the broader period remains post-observation evidence."
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def first_true(mask: np.ndarray) -> int | None:
    found = np.flatnonzero(mask)
    return None if not len(found) else int(found[0])


def build_reversal_candidates(
    daily: pd.DataFrame, gaps: pd.DataFrame
) -> pd.DataFrame:
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for gap in gaps.loc[gaps.gap_width_pct.ge(0.01)].itertuples(index=False):
        part = groups[str(gap.symbol)]
        gap_pos = int(gap.gap_seq)
        hist_pre = part.iloc[gap_pos - 120 : gap_pos].copy()
        exact_history = (
            len(hist_pre) == 120
            and repair.source._valid_daily_rows(hist_pre).all()
            and hist_pre.invalid_step_cum.eq(float(gap.invalid_step_cum)).all()
        )
        if not exact_history:
            continue
        inside = hist_pre.coord_high.ge(float(gap.L)) & hist_pre.coord_low.lt(
            float(gap.U)
        )
        corridor = hist_pre.coord_high.ge(float(gap.L - 0.5 * gap.W)) & (
            hist_pre.coord_low < float(gap.U + 0.5 * gap.W)
        )
        inside_touches = int(inside.sum())
        corridor_touches = int(corridor.sum())
        if inside_touches > 12 or corridor_touches > 20:
            continue
        peak_offset = int(np.nanargmax(hist_pre.coord_high.to_numpy(float)))
        peak = float(hist_pre.coord_high.iloc[peak_offset])
        recent20 = hist_pre.tail(20)
        pre_features = {
            "pre_gap_inside_touch_sessions": inside_touches,
            "pre_gap_corridor_touch_sessions": corridor_touches,
            "pre_peak_to_gap_sessions": int(len(hist_pre) - peak_offset),
            "pre_gap_drawdown_from_120d_peak": float(
                1 - float(part.coord_low.iloc[gap_pos]) / peak
            ),
            "pre_gap_return_20d": float(
                hist_pre.coord_close.iloc[-1] / hist_pre.coord_close.iloc[-20] - 1
            ),
            "pre_gap_range_20d": float(
                recent20.coord_high.max() / recent20.coord_low.min() - 1
            ),
        }
        end = min(len(part), gap_pos + 181)
        path = part.iloc[gap_pos + 1 : end].copy()
        valid = repair.source._valid_daily_rows(path) & path.invalid_step_cum.eq(
            float(gap.invalid_step_cum)
        ).to_numpy(bool)
        bad = first_true(~valid)
        if bad is not None:
            path = path.iloc[:bad]
        if len(path) < 10:
            continue
        touched = repair.source._raw_tick_reached(
            path.high, float(gap.L), path.coordinate_factor
        )
        first_touch = first_true(touched)
        if first_touch is not None:
            path = path.iloc[:first_touch]
        if len(path) < 10:
            continue
        found: set[str] = set()
        for rel in range(9, len(path)):
            absolute_pos = gap_pos + 1 + rel
            rolling = part.iloc[max(0, absolute_pos - 19) : absolute_pos + 1]
            if len(rolling) < 20:
                continue
            current = rolling.iloc[-1]
            previous = rolling.iloc[-2]
            previous2 = rolling.iloc[-3]
            since_gap = path.iloc[: rel + 1]
            max_depth = 1 - float(since_gap.coord_low.min()) / float(gap.L)
            current_depth = 1 - float(current.coord_close) / float(gap.L)
            low20_offset = int(np.nanargmin(rolling.coord_low.to_numpy(float)))
            days_since_low20 = len(rolling) - 1 - low20_offset
            recovery = float(current.coord_close / rolling.coord_low.min() - 1)
            if not (
                max_depth >= 0.10
                and current_depth >= 0.05
                and 1 <= days_since_low20 <= 10
                and recovery >= 0.03
            ):
                continue
            flags = trigger_flags(
                float(current.coord_close),
                float(previous.coord_close),
                float(previous2.coord_close),
                float(previous.coord_high),
                rolling.iloc[-4:-1].coord_high.astype(float).tolist(),
            )
            prior_turnover = rolling.iloc[:-1].turnover_fraction.astype(float)
            prior20_mean = float(prior_turnover.mean())
            prior5_mean = float(rolling.iloc[-6:-1].turnover_fraction.mean())
            for trigger in TRIGGERS:
                if trigger in found or not flags[trigger]:
                    continue
                rows.append(
                    {
                        **gap._asdict(),
                        **pre_features,
                        "trigger": trigger,
                        "signal_date": pd.Timestamp(current.trade_date),
                        "signal_time": pd.Timestamp(current.trade_date)
                        + pd.Timedelta(hours=15),
                        "signal_cal_idx": int(current.cal_idx),
                        "signal_coord_close": float(current.coord_close),
                        "swing_low": float(rolling.coord_low.min()),
                        "gap_age": int(rel + 1),
                        "max_depth": max_depth,
                        "current_depth": current_depth,
                        "days_since_low20": days_since_low20,
                        "recovery_from_low20": recovery,
                        "dry3": (
                            float(rolling.iloc[-4:-1].turnover_fraction.mean())
                            / prior20_mean
                            if prior20_mean > 0
                            else math.nan
                        ),
                        "trigger_expansion": (
                            float(current.turnover_fraction) / prior5_mean
                            if prior5_mean > 0
                            else math.nan
                        ),
                        "form": trigger,
                    }
                )
                found.add(trigger)
            if len(found) == len(TRIGGERS):
                break
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).sort_values(
        ["trigger", "signal_time", "symbol", "L", "gap_id"], kind="mergesort"
    )
    result = result.drop_duplicates(
        ["trigger", "symbol", "signal_date"], keep="first"
    )
    if result.signal_time.le(result.gap_date).any():
        raise V13Error("signal chronology failure")
    if result.duplicated(["trigger", "gap_id"]).any():
        raise V13Error("trigger-gap identity failure")
    return result.reset_index(drop=True)


def prepare_trigger_stage_a(
    trigger: str,
    candidates: pd.DataFrame,
    daily: pd.DataFrame,
    signal_end: pd.Timestamp,
    tail_end: pd.Timestamp,
    years: tuple[int, ...],
) -> dict[str, Any]:
    with trigger_runtime(trigger):
        label = "DEVELOPMENT" if max(years) <= 2021 else "POST_OBSERVATION_DIAGNOSTIC"
        paths = repair.paths(label)
        paths["root"].mkdir(parents=True, exist_ok=True)
        subset = candidates.loc[candidates.trigger.eq(trigger)].copy()
        subset = subset.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort")
        if subset.empty or subset.gap_id.duplicated().any():
            raise V13Error(f"{label} {trigger} candidate identity failure")
        repair.write_parquet(subset, paths["candidates"])
        repair.v1.configure_external(paths["root"], signal_end)
        vap, _profiles = repair.v1.build_vap_for_signals(subset, daily)
        panel = subset.merge(vap, on="gap_id", how="left", validate="one_to_one")
        selected = panel.loc[repair.fixed_signal_mask(panel)].copy()
        selected["signal_year"] = pd.to_datetime(selected.signal_date).dt.year
        selected["decision_latest_timestamp"] = pd.to_datetime(selected.signal_time)
        selected["feature_uses_post_signal_information"] = False
        selected = selected.sort_values(
            ["signal_time", "symbol", "gap_id"], kind="mergesort"
        ).reset_index(drop=True)
        if selected.empty:
            raise V13Error(f"{label} {trigger} selected population empty")
        repair.write_parquet(selected, paths["signals"])
        actions = repair.build_actions(
            selected.symbol.drop_duplicates().tolist(),
            tail_end,
            paths["actions"],
            paths["action_registry"],
        )
        execution_state = repair.build_execution_state(
            selected.symbol.drop_duplicates().tolist(),
            pd.Timestamp(selected.signal_date.min()).normalize(),
            tail_end,
            paths["execution_state"],
        )
        entries = repair.build_buy_entries(
            selected, actions, signal_end, tail_end, paths
        )
        return {
            "trigger": trigger,
            "candidate_count": len(subset),
            "selected_signal_count": len(selected),
            "selected_symbols": int(selected.symbol.nunique()),
            "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
            "evaluation_eligible_entries": int(
                entries.entry_status.eq("EXECUTABLE_ENTRY").sum()
            ),
            "annual_eligible_entries": float(
                entries.entry_status.eq("EXECUTABLE_ENTRY").sum() / len(years)
            ),
            "post_cutoff_signal_count": int(
                pd.to_datetime(selected.signal_date).gt(signal_end).sum()
            ),
            "entry_at_or_before_signal_count": int(entries.entry_at_or_before_signal.sum()),
            "buy_at_or_above_up_limit_count": int(entries.buy_at_or_above_up_limit.sum()),
            "hashes": {
                "candidates": sha256(paths["candidates"]),
                "signals": sha256(paths["signals"]),
                "actions": sha256(paths["actions"]),
                "action_registry": sha256(paths["action_registry"]),
                "execution_state": sha256(paths["execution_state"]),
                "entries": sha256(paths["entries"]),
                "vap_metrics": sha256(paths["root"] / "vap_metrics.parquet"),
            },
            "execution_state_rows": len(execution_state),
        }


def source_hashes() -> dict[str, str]:
    values = {
        "v4r1_stage_a_freeze": repair.STAGE_A_FREEZE,
        "v4r1_result": repair.RESULT,
        "v4r1_core": Path(core.__file__),
        "v4r1_runner": Path(repair.__file__),
    }
    return {name: sha256(path) for name, path in values.items()}


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods: dict[str, Any] = {}
    for label, (signal_end, tail_end, years) in PERIODS.items():
        daily = repair.v1.load_daily(signal_end)
        gaps = core.build_all_true_gaps(daily)
        candidates = build_reversal_candidates(daily, gaps)
        candidates = candidates.loc[
            pd.to_datetime(candidates.signal_date).dt.year.isin(years)
        ].copy()
        period_values = {
            trigger: prepare_trigger_stage_a(
                trigger, candidates, daily, signal_end, tail_end, years
            )
            for trigger in TRIGGERS
        }
        periods[label] = {
            "signal_end": str(signal_end.date()),
            "authorized_trade_tail_end": str(tail_end.date()),
            "all_candidate_rows": len(candidates),
            "triggers": period_values,
        }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_FIRST_REVERSAL_CONTRACT_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "periods": periods,
        "return_analysis_run": "NO",
        "strategy_backtest_run": "NO",
        "diagnostic_outcomes_opened": "NO",
        "post_2023_signal_or_selection_data_opened": "NO",
        "repository_2024_plus_data_opened": "AUTHORIZED_PRE_2024_TRADE_EXECUTION_STATE_ONLY",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V13Error("Stage-A freeze missing")
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
    if source_hashes() != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), source_hashes()]
    for label in PERIODS:
        for trigger in TRIGGERS:
            with trigger_runtime(trigger):
                paths = repair.paths(label)
                current = {
                    "candidates": sha256(paths["candidates"]),
                    "signals": sha256(paths["signals"]),
                    "actions": sha256(paths["actions"]),
                    "action_registry": sha256(paths["action_registry"]),
                    "execution_state": sha256(paths["execution_state"]),
                    "entries": sha256(paths["entries"]),
                    "vap_metrics": sha256(paths["root"] / "vap_metrics.parquet"),
                }
            expected = freeze["periods"][label]["triggers"][trigger]["hashes"]
            if current != expected:
                drift[f"{label}_{trigger}_artifacts"] = [expected, current]
    if drift:
        raise V13Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


def enrich_period_result(
    trigger: str, label: str, years: tuple[int, ...], result: dict[str, Any]
) -> dict[str, Any]:
    with trigger_runtime(trigger):
        paths = repair.paths(label)
        accepted = pd.read_parquet(paths["root"] / "portfolio_accepted.parquet")
        outcomes = pd.read_parquet(paths["outcomes"])
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
    combined = result["portfolio"]["COMBINED"]
    result.update(
        {
            "trigger": trigger,
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
        }
    )
    return result


def run_trigger_period(
    trigger: str,
    label: str,
    signal_end: pd.Timestamp,
    tail_end: pd.Timestamp,
    years: tuple[int, ...],
) -> dict[str, Any]:
    with trigger_runtime(trigger):
        result = repair.run_period_stage_b(label, signal_end, tail_end, years)
    return enrich_period_result(trigger, label, years, result)


def candidate_eligible(item: dict[str, Any]) -> bool:
    return bool(
        item["portfolio_accepted_trades_per_year"] >= MIN_ACCEPTED_TRADES_PER_YEAR
        and item["portfolio_mean_net"] >= 0.03
        and item["portfolio_median_net"] > 0
        and item["portfolio_severe10"] <= 0.15
        and item["positive_trade_mean_years"] >= 4
        and item["positive_portfolio_years"] >= 4
        and item["attack_date_equal_mean"] > 0
    )


def select_candidate(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates.values() if candidate_eligible(item)]
    if not eligible:
        raise V13Error("no Development reversal trigger passes selector")
    order = {name: index for index, name in enumerate(TRIGGERS)}
    return sorted(
        eligible,
        key=lambda item: (
            -item["portfolio_mean_net"],
            -item["portfolio_median_net"],
            item["portfolio_severe10"],
            order[item["trigger"]],
        ),
    )[0]


def run_development_and_freeze() -> dict[str, Any]:
    verification = verify_stage_a()
    signal_end, tail_end, years = PERIODS["DEVELOPMENT"]
    candidates = {
        trigger: run_trigger_period(
            trigger, "DEVELOPMENT", signal_end, tail_end, years
        )
        for trigger in TRIGGERS
    }
    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "candidate_results": candidates,
        "development_outcomes_opened": "YES",
        "diagnostic_outcomes_opened": "NO",
    }
    try:
        selected = select_candidate(candidates)
    except V13Error:
        result.update(
            {
                "selector_passed": False,
                "selected_trigger": None,
                "verdict": "FIRST_REVERSAL_DEVELOPMENT_FAILED",
            }
        )
        write_json(DEVELOPMENT_RESULT, result)
        return result
    result.update(
        {
            "selector_passed": True,
            "selected_trigger": selected["trigger"],
            "verdict": "FIRST_REVERSAL_DEVELOPMENT_CANDIDATE",
        }
    )
    write_json(DEVELOPMENT_RESULT, result)
    write_json(
        DIAGNOSTIC_FREEZE,
        {
            "experiment": EXPERIMENT,
            "stage": "DIAGNOSTIC_FREEZE_BEFORE_SELECTED_REVERSAL_OUTCOME_OPEN",
            "contract_sha256": sha256(CONTRACT),
            "spec_sha256": sha256(SPEC),
            "runner_sha256": sha256(Path(__file__)),
            "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
            "development_result_sha256": sha256(DEVELOPMENT_RESULT),
            "selected_trigger": selected["trigger"],
            "target_fraction": TARGET_FRACTION,
            "k_per_board_sleeve": PORTFOLIO_K,
            "diagnostic_outcomes_opened": "NO",
            "post_2023_signal_or_selection_data_opened": "NO",
        },
    )
    return result


def verify_diagnostic_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V13Error("Development produced no diagnostic freeze")
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
        raise V13Error(f"diagnostic freeze drift: {drift}")
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
        "post_cutoff_signal_count_zero": item["audit"]["post_cutoff_signal_count"] == 0,
    }


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    trigger = str(freeze["selected_trigger"])
    signal_end, tail_end, years = PERIODS["POST_OBSERVATION_DIAGNOSTIC"]
    diagnostic = run_trigger_period(
        trigger,
        "POST_OBSERVATION_DIAGNOSTIC",
        signal_end,
        tail_end,
        years,
    )
    checks = diagnostic_checks(diagnostic)
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_trigger": trigger,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": (
            "FIRST_REVERSAL_POST_OBSERVATION_TARGET_RETAINED"
            if all(checks.values())
            else "FIRST_REVERSAL_POST_OBSERVATION_FAILED"
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
        "|Trigger|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for trigger in TRIGGERS:
        item = development["candidate_results"][trigger]
        lines.append(
            f"|{trigger}|{item['portfolio_accepted_trades']}|{item['portfolio_accepted_trades_per_year']:.1f}|"
            f"{pct(item['portfolio_mean_net'])}|{pct(item['portfolio_median_net'])}|"
            f"{pct(item['portfolio_win'])}|{pct(item['portfolio_severe10'])}|"
            f"{pct(item['portfolio_cagr'])}|{pct(item['portfolio_max_drawdown'])}|"
        )
    if DIAGNOSTIC_RESULT.is_file():
        result = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
        item = result["diagnostic"]
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            f"Selected trigger: `{result['selected_trigger']}`.",
            f"Verdict: `{result['verdict']}`.",
            f"Accepted/year: {item['portfolio_accepted_trades_per_year']:.1f}; mean: {pct(item['portfolio_mean_net'])}; median: {pct(item['portfolio_median_net'])}; severe10: {pct(item['portfolio_severe10'])}.",
        ]
    else:
        lines += ["", "The 2022-2023 trigger outcomes were not opened."]
    lines += [
        "",
        "## Governance",
        "",
        "- Frequency means at least 50 accepted trades/year; there is no upper cap.",
        "- Every trigger is completed-daily-bar causal and enters only at a later legal minute open.",
        "- The clean-corridor, pre-L first-touch, A67, H20, 40 bp, K80, T+1, limits, and QD-010 contracts are unchanged.",
        "- 2024 data may only execute/manage/complete signals formed no later than 2023-12-31.",
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
