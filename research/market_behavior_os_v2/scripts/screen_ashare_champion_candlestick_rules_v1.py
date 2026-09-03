#!/usr/bin/env python3
"""Screen the six frozen chart-generated rules without changing their definitions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
CHART_RUNNER_PATH = PROGRAM / "scripts/run_ashare_champion_candlestick_rule_discovery_v1.py"
ANATOMY_RUNNER_PATH = PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py"
RULES_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V1_round1_rules.json"
OUTPUT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V1_screen.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V1_screen_result.json"
FEATURE_PATH = Path(
    "/Volumes/quant/CY_quant_research/champion_candlestick_rule_discovery_v1/causal_chart_feature_panel.parquet"
)
EXPECTED_RULES_SHA256 = "2ea6a850ba5a20d2ed8951f3e711ce56121434b9695224ff0ddf9933fd3fe9c2"
COST = 0.002
SEVERE = -0.10


class CandlestickRuleScreenError(RuntimeError):
    """Fail-closed rule-screen error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise CandlestickRuleScreenError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _mask(frame: pd.DataFrame, rule: dict[str, Any]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    operations = {
        ">=": lambda values, threshold: values.ge(threshold),
        "<=": lambda values, threshold: values.le(threshold),
        "==": lambda values, threshold: values.eq(threshold),
    }
    for condition in rule["conditions"]:
        field = condition["field"]
        if field not in frame:
            raise CandlestickRuleScreenError(f"missing rule field: {field}")
        operator = condition["operator"]
        if operator not in operations:
            raise CandlestickRuleScreenError(f"unsupported operator: {operator}")
        mask &= operations[operator](frame[field], condition["value"]).fillna(False)
    return mask


def _early_exit_payoff(
    trade: Any,
    history: pd.DataFrame,
    checkpoint: int,
    sellable: Any,
) -> tuple[float, str | None]:
    signal_date = pd.Timestamp(trade.signal_date)
    entry_date = pd.Timestamp(trade.entry_date)
    original_exit = pd.Timestamp(trade.exit_date)
    signal_hits = history.index[history.trade_date.eq(signal_date)]
    entry_hits = history.index[history.trade_date.eq(entry_date)]
    if len(signal_hits) != 1 or len(entry_hits) != 1:
        raise CandlestickRuleScreenError(f"missing trade rows: {trade.trade_id}")
    signal_index = int(signal_hits[0])
    trigger_index = signal_index + checkpoint + 1
    if trigger_index >= len(history):
        return float(trade.final_net_return), None
    entry_row = history.iloc[int(entry_hits[0])]
    shares = float(trade.invested_cost) / (float(entry_row.open) * (1.0 + COST))
    for row in history.iloc[trigger_index + 1 :].itertuples(index=False):
        current_date = pd.Timestamp(row.trade_date)
        if current_date >= original_exit:
            return float(trade.final_net_return), None
        if sellable(row):
            payoff = shares * float(row.open) * (1.0 - COST) / float(trade.invested_cost) - 1.0
            return float(payoff), current_date.date().isoformat()
    return float(trade.final_net_return), None


def _screen_period(
    frame: pd.DataFrame,
    rules: list[dict[str, Any]],
    histories: dict[str, pd.DataFrame],
    sellable: Any,
    label: str,
) -> list[dict[str, Any]]:
    baseline_mean = float(frame.final_net_return.mean())
    baseline_severe = float(frame.final_net_return.le(SEVERE).mean())
    rows: list[dict[str, Any]] = []
    for rule in rules:
        affected_mask = _mask(frame, rule)
        affected = frame.loc[affected_mask]
        if rule["role"] == "ADMISSION_VETO":
            candidate = frame.loc[~affected_mask, "final_net_return"]
            changed = len(affected)
            executable = changed
        else:
            checkpoint = 3 if rule["role"] == "D3_EXIT" else 5
            candidate = frame.final_net_return.copy()
            executable = 0
            for trade in affected.itertuples(index=False):
                payoff, exit_date = _early_exit_payoff(
                    trade, histories[trade.symbol], checkpoint, sellable
                )
                if exit_date is not None:
                    candidate.loc[
                        trade.Index
                        if hasattr(trade, "Index")
                        else affected.index[affected.trade_id.eq(trade.trade_id)][0]
                    ] = payoff
                    executable += 1
            changed = len(affected)
        candidate_mean = float(candidate.mean()) if len(candidate) else math.nan
        candidate_severe = float(candidate.le(SEVERE).mean()) if len(candidate) else math.nan
        rows.append(
            {
                "period": label,
                "rule_id": rule["rule_id"],
                "role": rule["role"],
                "trades": len(frame),
                "affected_trades": changed,
                "executable_affected_trades": executable,
                "baseline_mean_net_payoff": baseline_mean,
                "candidate_mean_net_payoff": candidate_mean,
                "mean_net_payoff_improvement": candidate_mean - baseline_mean,
                "baseline_severe_fraction": baseline_severe,
                "candidate_severe_fraction": candidate_severe,
                "severe_fraction_improvement": baseline_severe - candidate_severe,
            }
        )
    return rows


def main() -> None:
    if sha256_file(RULES_PATH) != EXPECTED_RULES_SHA256:
        raise CandlestickRuleScreenError("frozen Round-1 rule identity mismatch")
    chart = _load_module("candlestick_chart_for_screen_v1", CHART_RUNNER_PATH)
    anatomy = _load_module("champion_anatomy_for_candlestick_screen_v1", ANATOMY_RUNNER_PATH)
    spec = chart.load_spec()
    rules_doc = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    features = pd.read_parquet(FEATURE_PATH)
    if int(features.entry_year.max()) > 2023:
        raise CandlestickRuleScreenError("post-2023 feature encountered")
    trades = pd.read_parquet(chart.resolve_path(spec["inputs"]["trade_panel"]["path"]))
    trades["entry_year"] = pd.to_datetime(trades.entry_date).dt.year
    merged = trades.drop(columns=["entry_year"]).merge(
        features.drop(
            columns=[
                "final_net_return",
                "entry_date",
                "exit_date",
                "block",
                "industry",
                "symbol",
                "signal_date",
                "signal_rank",
            ]
        ),
        on="trade_id",
        validate="one_to_one",
    )
    merged["entry_year"] = pd.to_datetime(merged.entry_date).dt.year
    daily = chart.load_daily(
        spec, sorted(merged.loc[merged.entry_year.le(2020), "symbol"].unique())
    )
    histories = {
        symbol: group.reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    periods = {
        "round1_2018_2019": merged.loc[merged.entry_year.isin([2018, 2019])].copy(),
        "round2_2020": merged.loc[merged.entry_year.eq(2020)].copy(),
    }
    for label, frame in periods.items():
        rows.extend(
            _screen_period(frame, rules_doc["rules"], histories, anatomy.CA._sellable, label)
        )
    panel = pd.DataFrame(rows)
    gate = rules_doc["round2_gate"]
    early = panel.loc[panel.period.eq("round1_2018_2019")].set_index("rule_id")
    later = panel.loc[panel.period.eq("round2_2020")].set_index("rule_id")
    survivors: list[str] = []
    for rule_id in early.index:
        row1 = early.loc[rule_id]
        row2 = later.loc[rule_id]
        enough = int(row2.affected_trades) >= int(gate["minimum_affected_trades"])
        same_direction = (
            row1.mean_net_payoff_improvement > 0 and row2.mean_net_payoff_improvement > 0
        )
        economic = (
            row2.mean_net_payoff_improvement >= gate["minimum_mean_net_payoff_improvement_pp"] / 100
            or row2.severe_fraction_improvement
            >= gate["alternative_minimum_severe_loss_improvement_pp"] / 100
        )
        if enough and same_direction and economic:
            survivors.append(str(rule_id))
    survivors = sorted(
        survivors,
        key=lambda rule_id: (
            later.loc[rule_id, "mean_net_payoff_improvement"],
            later.loc[rule_id, "severe_fraction_improvement"],
        ),
        reverse=True,
    )[: int(gate["maximum_survivors"])]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUTPUT_PATH, index=False, float_format="%.12f")
    result = {
        "experiment_id": rules_doc["experiment_id"],
        "rules_sha256": EXPECTED_RULES_SHA256,
        "feature_panel_sha256": sha256_file(FEATURE_PATH),
        "screen_panel_sha256": sha256_file(OUTPUT_PATH),
        "round1_trades": len(periods["round1_2018_2019"]),
        "round2_trades": len(periods["round2_2020"]),
        "survivors": survivors,
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "maximum_evaluation_outcome_date": "2020-12-31",
    }
    RESULT_PATH.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(panel.to_string(index=False))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
