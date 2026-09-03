#!/usr/bin/env python3
"""Build D10/D15 descriptors and prune the frozen second candlestick rule family."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V2_spec.json"
CHART_RUNNER_PATH = PROGRAM / "scripts/run_ashare_champion_candlestick_rule_discovery_v1.py"
V1_SCREEN_PATH = PROGRAM / "scripts/screen_ashare_champion_candlestick_rules_v1.py"
ANATOMY_RUNNER_PATH = PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py"
FEATURE_PATH = Path(
    "/Volumes/quant/CY_quant_research/champion_candlestick_rule_discovery_v1/"
    "causal_chart_feature_panel_v2.parquet"
)
OUTPUT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V2_screen.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-CANDLESTICK-RULE-DISCOVERY-V2_screen_result.json"
EXPECTED_SPEC_SHA256 = "cdff3a06822ea7c5cb407a3f4893e0dcf1cdd91a4dabac53aa9228bcb88e0132"
SEVERE = -0.10


class CandlestickRuleScreenV2Error(RuntimeError):
    """Fail-closed V2 screen error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise CandlestickRuleScreenV2Error(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _screen_period(
    frame: pd.DataFrame,
    rules: list[dict[str, Any]],
    histories: dict[str, pd.DataFrame],
    mask_rule: Any,
    early_exit_payoff: Any,
    sellable: Any,
    label: str,
) -> list[dict[str, Any]]:
    baseline_mean = float(frame.final_net_return.mean())
    baseline_severe = float(frame.final_net_return.le(SEVERE).mean())
    rows: list[dict[str, Any]] = []
    for rule in rules:
        affected_mask = mask_rule(frame, rule)
        affected = frame.loc[affected_mask]
        candidate = frame.final_net_return.copy()
        checkpoint = 10 if rule["role"] == "D10_EXIT" else 15
        executable = 0
        for index, trade in affected.iterrows():
            payoff, exit_date = early_exit_payoff(
                trade, histories[trade.symbol], checkpoint, sellable
            )
            if exit_date is not None:
                candidate.loc[index] = payoff
                executable += 1
        candidate_mean = float(candidate.mean())
        candidate_severe = float(candidate.le(SEVERE).mean())
        rows.append(
            {
                "period": label,
                "rule_id": rule["rule_id"],
                "role": rule["role"],
                "trades": len(frame),
                "affected_trades": len(affected),
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
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CandlestickRuleScreenV2Error("frozen V2 specification identity mismatch")
    spec_v2 = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    chart = _load_module("candlestick_chart_for_screen_v2", CHART_RUNNER_PATH)
    v1_screen = _load_module("candlestick_screen_v1_for_v2", V1_SCREEN_PATH)
    anatomy = _load_module("champion_anatomy_for_candlestick_screen_v2", ANATOMY_RUNNER_PATH)
    spec_v1 = chart.load_spec()
    trades = pd.read_parquet(chart.resolve_path(spec_v1["inputs"]["trade_panel"]["path"]))
    trades["entry_year"] = pd.to_datetime(trades.entry_date).dt.year
    if int(trades.entry_year.max()) > 2023:
        raise CandlestickRuleScreenV2Error("post-2023 trade encountered")
    daily = chart.load_daily(spec_v1, sorted(trades.symbol.unique()))
    if not FEATURE_PATH.exists():
        features = chart.build_feature_panel(trades, daily, checkpoints=(3, 5, 10, 15))
        for checkpoint in (10, 15):
            features[f"d{checkpoint}_close_from_peak"] = (
                1.0 + features[f"d{checkpoint}_close_from_entry"]
            ) / (1.0 + features[f"d{checkpoint}_max_runup"]) - 1.0
        features.to_parquet(FEATURE_PATH, index=False, compression="zstd")
    features = pd.read_parquet(FEATURE_PATH)
    merge_drop = [
        "final_net_return",
        "entry_date",
        "exit_date",
        "block",
        "industry",
        "symbol",
        "signal_date",
        "signal_rank",
    ]
    merged = trades.drop(columns=["entry_year"]).merge(
        features.drop(columns=merge_drop), on="trade_id", validate="one_to_one"
    )
    merged["entry_year"] = pd.to_datetime(merged.entry_date).dt.year
    merged["signal_timestamp"] = pd.to_datetime(merged.signal_date)
    merged["exit_timestamp"] = pd.to_datetime(merged.exit_date)
    histories = {
        symbol: group.reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }
    periods = {
        "generation_2018_2020": merged.loc[merged.entry_year.le(2020)].copy(),
        "pruning_2021": merged.loc[
            merged.signal_timestamp.dt.year.eq(2021) & merged.exit_timestamp.dt.year.eq(2021)
        ].copy(),
    }
    rows: list[dict[str, Any]] = []
    for label, frame in periods.items():
        rows.extend(
            _screen_period(
                frame,
                spec_v2["rules"],
                histories,
                v1_screen._mask,
                v1_screen._early_exit_payoff,
                anatomy.CA._sellable,
                label,
            )
        )
    panel = pd.DataFrame(rows)
    generation = panel.loc[panel.period.eq("generation_2018_2020")].set_index("rule_id")
    pruning = panel.loc[panel.period.eq("pruning_2021")].set_index("rule_id")
    gate = spec_v2["pruning_gate"]
    survivors: list[str] = []
    for rule_id in generation.index:
        row0 = generation.loc[rule_id]
        row1 = pruning.loc[rule_id]
        if (
            int(row1.affected_trades) >= int(gate["minimum_affected_2021_trades"])
            and row0.mean_net_payoff_improvement > 0
            and row1.mean_net_payoff_improvement
            >= gate["minimum_2021_mean_payoff_improvement_pp"] / 100
        ):
            survivors.append(str(rule_id))
    survivors = sorted(
        survivors,
        key=lambda rule_id: (
            pruning.loc[rule_id, "mean_net_payoff_improvement"],
            pruning.loc[rule_id, "severe_fraction_improvement"],
        ),
        reverse=True,
    )[: int(gate["maximum_survivors"])]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUTPUT_PATH, index=False, float_format="%.12f")
    result = {
        "experiment_id": spec_v2["experiment_id"],
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "feature_panel_sha256": sha256_file(FEATURE_PATH),
        "screen_panel_sha256": sha256_file(OUTPUT_PATH),
        "generation_trades": len(periods["generation_2018_2020"]),
        "pruning_trades": len(periods["pruning_2021"]),
        "survivors": survivors,
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "maximum_evaluation_outcome_date": "2021-12-31",
    }
    RESULT_PATH.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(panel.to_string(index=False))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
