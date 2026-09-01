from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_multiscale_diffusion_daily_alpha_cycle_015.py"
)
RESULT = (
    ROOT
    / "research/market_behavior_os_v2/artifacts/"
    "ASHARE-MULTISCALE-DIFFUSION-DAILY-ALPHA-CYCLE-015_result.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("multiscale_cycle_015_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _replay(total: float, annualized: float, drawdown: float, sharpe: float) -> dict:
    return {
        "total_return": total,
        "annualized_return": annualized,
        "maximum_drawdown": drawdown,
        "daily_sharpe": sharpe,
        "calmar": annualized / abs(drawdown),
        "severe_trade_fraction": 0.10,
        "turnover_multiple_initial_capital": 200.0,
        "mean_industry_hhi_invested_days": 0.17,
        "p10_capacity_cny_at_5pct_amount": 100_000_000.0,
    }


def test_contract_freezes_only_weekly_and_daily_architectures() -> None:
    module = _module()
    spec = module._load_spec()
    assert "exact frozen weekly Industry Diffusion" in spec["track_a"]["architecture_a"]
    assert "20 sessions" in spec["track_a"]["architecture_b"]["quality"]
    assert "lower is better" in spec["track_a"]["architecture_b"]["quality"]
    assert any("other frequency" in item for item in spec["prohibited"])


def test_architecture_gate_rejects_return_and_sharpe_degradation() -> None:
    module = _module()
    weekly = {}
    daily = {}
    for label in ("20bps", "30bps", "40bps"):
        weekly[label] = {"low_max": _replay(1.0, 0.15, -0.25, 0.70)}
        daily[label] = _replay(0.5, 0.08, -0.27, 0.40)
    decision, comparison = module._architecture_decision(weekly, daily)
    assert decision == "DAILY_REFRESH_DEGRADES_STRATEGY"
    assert comparison["gate"]["return_20"] is False
    assert comparison["gate"]["sharpe_40"] is False


def test_matching_drops_nonfinite_covariates() -> None:
    module = _module()
    candidates = pd.DataFrame(
        [
            {
                "hypothesis": "H",
                "role": "event",
                "trade_date": "2020-01-02",
                "industry": "I",
                "symbol": "E",
                "uid": "e",
                "block": "early",
                "step_return": 0.01,
                "avg_amount20": 100.0,
                "r20": 0.02,
                "range_ratio": 1.0,
            },
            {
                "hypothesis": "H",
                "role": "control",
                "trade_date": "2020-01-02",
                "industry": "I",
                "symbol": "C",
                "uid": "c",
                "block": "early",
                "step_return": 0.00,
                "avg_amount20": 100.0,
                "r20": 0.01,
                "range_ratio": 1.1,
            },
            {
                "hypothesis": "H",
                "role": "control",
                "trade_date": "2020-01-02",
                "industry": "I",
                "symbol": "BAD",
                "uid": "bad",
                "block": "early",
                "step_return": 0.00,
                "avg_amount20": float("nan"),
                "r20": 0.01,
                "range_ratio": 1.0,
            },
        ]
    )
    pairs = module._nearest_pairs(candidates)
    assert pairs.iloc[0].control_uid == "c"


def test_accepted_result_preserves_boundaries_and_authorizes_no_daily_replay() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["track_a"]["classification"] == "DAILY_REFRESH_DEGRADES_STRATEGY"
    assert result["track_a"]["daily_replays"]["40bps"]["total_return"] < 0
    assert result["track_b"]["promotions"] == []
    assert result["track_b"]["replay_status"] == "NOT_AUTHORIZED"
    assert result["boundaries"]["post_2023_read"] is False
    assert result["boundaries"]["cy011_read"] is False
