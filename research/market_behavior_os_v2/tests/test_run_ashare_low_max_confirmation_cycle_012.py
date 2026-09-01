from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/run_ashare_low_max_confirmation_cycle_012.py"
)
SPEC = (
    ROOT
    / "research/market_behavior_os_v2/experiments/ASHARE-LOW-MAX-CONFIRMATION-CYCLE-012_spec.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("low_max_confirmation_cycle_012_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _replay(total, annualized, drawdown, sharpe, severe, turnover=100.0):
    return {
        "total_return": total,
        "annualized_return": annualized,
        "maximum_drawdown": drawdown,
        "daily_sharpe": sharpe,
        "calmar": annualized / abs(drawdown),
        "severe_trade_fraction": severe,
        "turnover_multiple_initial_capital": turnover,
        "completed_trades": 100,
        "p10_capacity_cny_at_5pct_amount": 100_000_000.0,
        "mean_industry_hhi_invested_days": 0.20,
    }


def test_frozen_contract_binds_exact_costs_and_one_portability_baseline():
    module = _module()
    spec = module._load_spec()
    assert spec["track_a"]["cost_per_side"] == [0.002, 0.003, 0.004]
    assert spec["track_b"]["baseline"]["name"] == "CHINEXT_V1_RS_ACCEL_VETO_CANDIDATE_LIFECYCLE"
    assert spec["frozen_low_max"]["lookback_sessions"] == 20
    assert spec["frozen_low_max"]["orientation"] == "lower is better"
    assert spec["frozen_low_max"]["parameter_search"] is False


def test_cost_resilience_requires_high_cost_risk_and_return_improvement():
    module = _module()
    spec = module._load_spec()
    baseline = _replay(0.50, 0.08, -0.30, 0.40, 0.18)
    comparisons = {}
    for label, advantage in (("20bps", 0.60), ("30bps", 0.55), ("40bps", 0.40)):
        low = _replay(
            baseline["total_return"] + advantage,
            0.15,
            -0.25,
            0.65,
            0.14,
            130.0,
        )
        comparisons[label] = {
            "baseline": baseline,
            "low_max": low,
            "delta": module._cost_delta(baseline, low),
        }
    assert module.classify_cost_resilience(comparisons, spec) == "COST_RESILIENT"
    comparisons["40bps"]["delta"]["daily_sharpe"] = -0.01
    assert module.classify_cost_resilience(comparisons, spec) == "COST_FRAGILE"


def test_portability_gate_requires_both_blocks_and_decision_headroom():
    module = _module()
    spec = module._load_spec()
    period = {"mean_net_improvement": 0.002, "severe_loss_improvement": 0.01}
    metrics = {
        "quality_coverage": 1.0,
        "multi_candidate_dates": 75,
        "changed_selections": 30,
        "changed_fraction": 0.40,
        "industry_hhi_increase": 0.01,
        "largest_industry_share_increase": 0.02,
        "periods": {
            "full": period.copy(),
            "development_2018_2021": period.copy(),
            "consumed_2022_2023": period.copy(),
        },
    }
    assert module.portability_gate(metrics, spec)["authorized"] is True
    metrics["periods"]["consumed_2022_2023"]["mean_net_improvement"] = -0.0001
    assert module.portability_gate(metrics, spec)["authorized"] is False


def test_reusable_portability_requires_no_severe_rate_worsening():
    module = _module()
    metrics = {"replay_gate": {"authorized": True}}
    favorable = {
        "delta": {
            "total_return": 0.01,
            "sharpe_rf0": 0.01,
            "max_drawdown": 0.01,
            "severe_loss_rate": -0.01,
        }
    }
    replay = {"blocks": {"early": favorable, "late": favorable}}
    assert (
        module._portability_classification(metrics, replay)
        == "REUSABLE_CONDITIONAL_STOCK_QUALITY"
    )
    replay["blocks"]["late"] = {
        "delta": {**favorable["delta"], "severe_loss_rate": 0.001}
    }
    assert module._portability_classification(metrics, replay) == "PORTABILITY_FAILED"
