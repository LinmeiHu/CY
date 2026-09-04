from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPT = PROGRAM / "scripts/run_ashare_industry_consensus_q1_event_v1.py"
RESULT = PROGRAM / "artifacts/ASHARE-INDUSTRY-CONSENSUS-Q1-EVENT-V1_result.json"
EQUITY = PROGRAM / "artifacts/ASHARE-INDUSTRY-CONSENSUS-Q1-EVENT-V1_equity.csv"
TRADES = PROGRAM / "artifacts/ASHARE-INDUSTRY-CONSENSUS-Q1-EVENT-V1_trades.csv"


def _module():
    spec = importlib.util.spec_from_file_location("industry_consensus_q1_event_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_rule_is_binary_simple_and_unlevered() -> None:
    module = _module()
    spec = module._load_spec()
    strategy = spec["frozen_strategy"]
    assert "both share the same" in strategy["selection"]
    assert strategy["cohort_capital"] == (
        "minimum of available cash and one-half of pre-entry NAV"
    )
    assert strategy["holding"].startswith("20 market sessions")
    assert strategy["cost_per_side"] == 0.002
    assert strategy["leverage"] is False
    assert module.COHORT_DIVISOR == 2
    assert module.EVALUATION_END == date(2023, 12, 28)


def test_plan_builder_keeps_only_same_industry_pairs() -> None:
    module = _module()
    start = date(2020, 1, 1)
    calendar = [start + timedelta(days=index) for index in range(60)]
    selection = pd.DataFrame(
        {
            "trade_date": [calendar[0], calendar[0], calendar[5], calendar[5]],
            "symbol": ["A", "B", "C", "D"],
            "industry": ["I", "I", "J", "K"],
        }
    )
    plans = module._plans(selection, calendar)
    assert list(plans.symbol) == ["A", "B"]
    assert plans.signal_date.nunique() == 1
    assert plans.entry_index.eq(1).all()
    assert plans.due_index.eq(21).all()


def test_result_recomputes_and_meets_both_user_targets() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    candidate = result["candidate"]
    equity = pd.read_csv(EQUITY)
    trades = pd.read_csv(TRADES)

    assert equity.trade_date.iloc[0] == "2018-07-10"
    assert equity.trade_date.iloc[-1] == "2023-12-28"
    assert equity.cash.min() == 0.0
    assert candidate["entries"] == candidate["completed_trades"] == len(trades) == 180
    assert candidate["market_unexecutable_entries"] == 0
    assert candidate["capital_skipped_entries"] == 18
    assert candidate["planned_entries"] == 198

    total_return = equity.nav.iloc[-1] / 10_000_000.0 - 1.0
    annualized = (1.0 + total_return) ** (252.0 / len(equity)) - 1.0
    max_drawdown = (equity.nav / equity.nav.cummax() - 1.0).min()
    assert abs(total_return - candidate["total_return"]) < 1e-12
    assert abs(annualized - candidate["annualized_return"]) < 1e-12
    assert abs(max_drawdown - candidate["maximum_drawdown"]) < 1e-12
    assert result["target_checks"] == {"annualized": True, "drawdown": True}
    assert result["target_met"] is True
    assert result["status"] == "USER_TARGET_ACHIEVED"
    assert all(value > 0 for value in result["calendar_year_returns"].values())


def test_quarantine_and_lineage_audits_remain_closed() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["post_2023_outcome_read"] == "NO"
    assert result["cy011_read"] == "NO"
    assert result["input_identity"]["asset_id"] == "CY-006"
    assert result["candidate"]["forced_exit_pending_days"] == 0
    assert result["candidate"]["minimum_cash"] == 0.0
