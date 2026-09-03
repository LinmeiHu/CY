#!/usr/bin/env python3
"""Screen the frozen cohort-synchronous candlestick exit without tuning it."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V3_spec.json"
CHART_RUNNER_PATH = PROGRAM / "scripts/run_ashare_champion_candlestick_rule_discovery_v1.py"
V1_SCREEN_PATH = PROGRAM / "scripts/screen_ashare_champion_candlestick_rules_v1.py"
ANATOMY_RUNNER_PATH = PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py"
OUTPUT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V3_screen.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V3_screen_result.json"
SEVERE = -0.10


class CandlestickRuleScreenV3Error(RuntimeError):
    """Fail-closed V3 screen error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise CandlestickRuleScreenV3Error(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _cohort_triggers(features: pd.DataFrame) -> pd.DataFrame:
    features = features.copy()
    features["signal_date"] = pd.to_datetime(features.signal_date).dt.date
    rows: list[dict[str, Any]] = []
    for signal_date, group in features.groupby("signal_date", sort=True):
        if group.d5_close_below_signal_low.isna().any():
            raise CandlestickRuleScreenV3Error(f"missing d5 cohort state: {signal_date}")
        d5_fraction = float(group.d5_close_below_signal_low.mean())
        d10_median = float(group.d10_close_from_entry.median())
        checkpoint = 5 if d5_fraction >= 0.70 else 10 if d10_median <= -0.03 else None
        rows.append(
            {
                "signal_date": signal_date,
                "executed_cohort_size": len(group),
                "d5_below_signal_low_fraction": d5_fraction,
                "d10_median_close_from_entry": d10_median,
                "trigger_checkpoint": checkpoint,
                "trigger_reason": (
                    "D5_SYNCHRONIZED_SIGNAL_LOW_FAILURE"
                    if checkpoint == 5
                    else "D10_SYNCHRONIZED_NEGATIVE_COHORT"
                    if checkpoint == 10
                    else "NONE"
                ),
            }
        )
    return pd.DataFrame(rows)


def _evaluate(
    frame: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    early_exit_payoff: Any,
    sellable: Any,
    label: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    candidate = frame.final_net_return.copy()
    affected = frame.loc[frame.trigger_checkpoint.notna()]
    executable = 0
    exits: list[dict[str, Any]] = []
    for index, trade in affected.iterrows():
        payoff, exit_date = early_exit_payoff(
            trade,
            histories[trade.symbol],
            int(trade.trigger_checkpoint),
            sellable,
        )
        if exit_date is not None:
            candidate.loc[index] = payoff
            executable += 1
        exits.append(
            {
                "period": label,
                "trade_id": trade.trade_id,
                "signal_date": trade.signal_date,
                "trigger_checkpoint": int(trade.trigger_checkpoint),
                "trigger_reason": trade.trigger_reason,
                "baseline_payoff": float(trade.final_net_return),
                "candidate_payoff": float(candidate.loc[index]),
                "payoff_improvement": float(candidate.loc[index] - trade.final_net_return),
                "counterfactual_exit_date": exit_date,
            }
        )
    baseline_mean = float(frame.final_net_return.mean())
    candidate_mean = float(candidate.mean())
    baseline_severe = float(frame.final_net_return.le(SEVERE).mean())
    candidate_severe = float(candidate.le(SEVERE).mean())
    return (
        {
            "period": label,
            "trades": len(frame),
            "decision_dates": int(frame.signal_date.nunique()),
            "triggered_cohorts": int(affected.signal_date.nunique()),
            "affected_trades": len(affected),
            "executable_affected_trades": executable,
            "baseline_mean_net_payoff": baseline_mean,
            "candidate_mean_net_payoff": candidate_mean,
            "mean_net_payoff_improvement": candidate_mean - baseline_mean,
            "baseline_severe_fraction": baseline_severe,
            "candidate_severe_fraction": candidate_severe,
            "severe_fraction_improvement": baseline_severe - candidate_severe,
        },
        pd.DataFrame(exits),
    )


def main() -> None:
    spec_sha256 = sha256_file(SPEC_PATH)
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_COHORT_CONFIRMATION_OUTCOMES":
        raise CandlestickRuleScreenV3Error("V3 specification is not frozen")
    for binding in spec["inputs"].values():
        path = Path(binding["path"])
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CandlestickRuleScreenV3Error(f"bound input changed: {path}")

    chart = _load_module("candlestick_chart_for_screen_v3", CHART_RUNNER_PATH)
    v1_screen = _load_module("candlestick_screen_v1_for_v3", V1_SCREEN_PATH)
    anatomy = _load_module("champion_anatomy_for_candlestick_screen_v3", ANATOMY_RUNNER_PATH)
    trades = pd.read_parquet(spec["inputs"]["champion_trade_panel"]["path"])
    features = pd.read_parquet(spec["inputs"]["causal_chart_feature_panel_v2"]["path"])
    if pd.to_datetime(trades.exit_date).dt.year.max() > 2023:
        raise CandlestickRuleScreenV3Error("post-2023 outcome encountered")
    triggers = _cohort_triggers(features)
    merged = trades.merge(triggers, on="signal_date", validate="many_to_one")
    merged["signal_year"] = pd.to_datetime(merged.signal_date).dt.year
    merged["exit_year"] = pd.to_datetime(merged.exit_date).dt.year
    daily_spec = chart.load_spec()
    daily = chart.load_daily(daily_spec, sorted(merged.symbol.unique()))
    histories = {
        symbol: group.reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }

    period_frames = {
        "generation_2018_2019": merged.loc[merged.signal_year.le(2019)].copy(),
        "generation_2020_2021": merged.loc[
            merged.signal_year.between(2020, 2021) & merged.exit_year.le(2021)
        ].copy(),
    }
    rows: list[dict[str, Any]] = []
    exit_frames: list[pd.DataFrame] = []
    for label, frame in period_frames.items():
        row, exits = _evaluate(
            frame,
            histories,
            v1_screen._early_exit_payoff,
            anatomy.CA._sellable,
            label,
        )
        rows.append(row)
        exit_frames.append(exits)

    gate = spec["generation_gate_all_required"]
    generation_passes = all(
        row["triggered_cohorts"] >= int(gate["triggered_cohorts_minimum"])
        and row["mean_net_payoff_improvement"] > 0
        and row["severe_fraction_improvement"] >= 0
        for row in rows
    ) and sum(row["mean_net_payoff_improvement"] * row["trades"] for row in rows) / sum(
        row["trades"] for row in rows
    ) >= float(gate["mean_all_trade_payoff_improvement_minimum"])

    validation_opened = False
    validation_passes = False
    if generation_passes:
        validation_opened = True
        validation = merged.loc[
            merged.signal_year.between(2022, 2023) & merged.exit_year.le(2023)
        ].copy()
        row, exits = _evaluate(
            validation,
            histories,
            v1_screen._early_exit_payoff,
            anatomy.CA._sellable,
            "fixed_validation_2022_2023",
        )
        rows.append(row)
        exit_frames.append(exits)
        yearly_rows: list[dict[str, Any]] = []
        for year in (2022, 2023):
            year_row, _ = _evaluate(
                validation.loc[validation.signal_year.eq(year)],
                histories,
                v1_screen._early_exit_payoff,
                anatomy.CA._sellable,
                f"fixed_validation_{year}",
            )
            yearly_rows.append(year_row)
        rows.extend(yearly_rows)
        validation_gate = spec["fixed_validation_gate_all_required"]
        validation_passes = (
            row["triggered_cohorts"] >= int(validation_gate["triggered_cohorts_minimum"])
            and row["mean_net_payoff_improvement"] > 0
            and row["severe_fraction_improvement"] >= 0
            and all(item["mean_net_payoff_improvement"] >= 0 for item in yearly_rows)
        )

    panel = pd.DataFrame(rows)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUTPUT_PATH, index=False, float_format="%.12f")
    exits = pd.concat(exit_frames, ignore_index=True) if exit_frames else pd.DataFrame()
    result = {
        "experiment_id": spec["experiment_id"],
        "spec_sha256": spec_sha256,
        "screen_sha256": sha256_file(OUTPUT_PATH),
        "generation_passes": generation_passes,
        "validation_opened": validation_opened,
        "validation_passes": validation_passes,
        "portfolio_replay_authorized": generation_passes and validation_passes,
        "trigger_counts": triggers.trigger_reason.value_counts().sort_index().to_dict(),
        "evaluated_counterfactual_exits": len(exits),
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "maximum_evaluation_outcome_date": "2023-12-31" if validation_opened else "2021-12-31",
    }
    RESULT_PATH.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(panel.to_string(index=False))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
