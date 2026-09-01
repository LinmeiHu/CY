from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/run_ashare_industry_diffusion_construction_011.py"
)
SPEC = (
    ROOT
    / "research"
    / "market_behavior_os_v2"
    / "experiments"
    / "ASHARE-INDUSTRY-DIFFUSION-CONSTRUCTION-011_spec.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("cycle011_construction_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_spec_has_only_authorized_arms_and_materiality() -> None:
    module = _module()
    frozen = module._load_spec()
    assert module.sha256_file(SPEC) == module.EXPECTED_SPEC_SHA256
    assert list(frozen["arms"]) == [
        "arm0_baseline",
        "arm1_upper_limit_clean",
        "arm2_low_max",
        "arm3_optional_equal_rank",
    ]
    assert frozen["arms"]["arm1_upper_limit_clean"]["revised_240"].startswith(
        "sum causal log returns"
    )
    assert frozen["arms"]["arm2_low_max"]["max_return20"].startswith(
        "maximum causal daily log return"
    )
    assert frozen["portfolio_materiality"]["all_required"]["risk_improvement_any"]


def test_modifier_preserves_industry_allocation_and_uses_baseline_fallback() -> None:
    module = _module()
    day = pd.Timestamp("2020-01-10")
    baseline = pd.DataFrame(
        {
            "trade_date": [day, day],
            "industry": ["I", "I"],
            "symbol": ["A", "B"],
            "signal_rank": [1, 2],
        }
    )
    candidates = pd.DataFrame(
        {
            "trade_date": [day, day, day],
            "industry": ["I", "I", "I"],
            "symbol": ["A", "B", "C"],
            "quality": [float("nan"), float("nan"), 1.0],
        }
    )
    selected = module._select_modifier(
        candidates, baseline, "arm", "quality", ascending=False
    )
    assert set(selected.symbol) == {"A", "C"}
    assert module._allocation_difference(baseline, selected) == 0.0
    assert selected.groupby(["trade_date", "industry"]).size().iloc[0] == 2


def test_portfolio_materiality_requires_risk_improvement_and_preserves_return() -> None:
    module = _module()
    frozen = module._load_spec()
    baseline = {
        "total_return": 0.50,
        "annualized_return": 0.08,
        "maximum_drawdown": -0.30,
        "daily_sharpe": 0.44,
        "calmar": 0.27,
        "severe_trade_fraction": 0.18,
        "turnover_multiple_initial_capital": 100.0,
        "mean_positions": 39.0,
        "mean_industries": 12.0,
        "mean_industry_hhi_invested_days": 0.20,
        "p10_capacity_cny_at_5pct_amount": 100.0,
    }
    arm = {
        **baseline,
        "total_return": 0.48,
        "annualized_return": 0.079,
        "maximum_drawdown": -0.27,
        "daily_sharpe": 0.55,
        "calmar": 0.29,
        "severe_trade_fraction": 0.15,
        "turnover_multiple_initial_capital": 105.0,
        "entry_execution_fraction": 0.99,
        "terminal_open_lots": 0,
    }
    comparison = module._portfolio_comparison(
        baseline, arm, {"changed_fraction": 0.50}, frozen
    )
    assert comparison["materiality_pass"] is True
    assert comparison["risk_improvement_checks"] == {
        "sharpe": True,
        "drawdown": True,
        "severe_loss": True,
    }
